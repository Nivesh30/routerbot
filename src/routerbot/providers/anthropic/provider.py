"""Anthropic Claude provider implementation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from routerbot.core.enums import FinishReason
from routerbot.core.exceptions import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
    ServiceUnavailableError,
)
from routerbot.core.logging import get_logger
from routerbot.core.types import ChunkChoice, CompletionResponse, CompletionResponseChunk, DeltaMessage
from routerbot.providers.anthropic.config import (
    ANTHROPIC_API_BASE,
    ANTHROPIC_VERSION,
    CHAT_MODELS,
    DEFAULT_MAX_TOKENS,
    MAX_TOKENS,
)
from routerbot.providers.anthropic.transform import (
    anthropic_response_to_openai,
    anthropic_stream_event_to_delta,
    build_anthropic_request,
    openai_messages_to_anthropic,
    openai_tools_to_anthropic,
)
from routerbot.providers.base import BaseProvider
from routerbot.providers.registry import register_provider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from routerbot.core.types import (
        AudioTranscriptionRequest,
        AudioTranscriptionResponse,
        CompletionRequest,
        EmbeddingRequest,
        EmbeddingResponse,
        ImageRequest,
        ImageResponse,
    )

logger = get_logger(__name__)


class AnthropicProvider(BaseProvider):
    """Provider for Anthropic's Claude models."""

    PROVIDER_NAME = "anthropic"
    SUPPORTED_MODELS = CHAT_MODELS

    def __init__(
        self,
        api_key: str,
        api_base: str = ANTHROPIC_API_BASE,
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base, **kwargs)
        self._headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                headers=self._headers,
                timeout=self._timeout,
            )
        return self._client

    # ------------------------------------------------------------------
    # Chat completion
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> CompletionResponse:
        messages_dicts = [m.model_dump(exclude_none=True) for m in request.messages]
        system, anthropic_messages = openai_messages_to_anthropic(messages_dicts)
        anthropic_tools = openai_tools_to_anthropic([t.model_dump() for t in request.tools] if request.tools else None)

        max_tokens = int(request.max_tokens or MAX_TOKENS.get(request.model, DEFAULT_MAX_TOKENS))

        payload = build_anthropic_request(
            model=request.model,
            messages=anthropic_messages,
            system=system,
            max_tokens=max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            stop=request.stop,
            tools=anthropic_tools,
            stream=False,
        )

        client = self._get_client()

        logger.debug("anthropic.chat_completion", model=request.model, stream=False)

        response = await client.post("/v1/messages", content=json.dumps(payload))
        self._check_response(response)

        data: dict[str, Any] = response.json()
        return anthropic_response_to_openai(data, request.model)

    def chat_completion_stream(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> AsyncIterator[CompletionResponseChunk]:
        return self._stream_generator(request)

    async def _stream_generator(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[CompletionResponseChunk]:
        messages_dicts = [m.model_dump(exclude_none=True) for m in request.messages]
        system, anthropic_messages = openai_messages_to_anthropic(messages_dicts)
        anthropic_tools = openai_tools_to_anthropic([t.model_dump() for t in request.tools] if request.tools else None)

        max_tokens = int(request.max_tokens or MAX_TOKENS.get(request.model, DEFAULT_MAX_TOKENS))

        payload = build_anthropic_request(
            model=request.model,
            messages=anthropic_messages,
            system=system,
            max_tokens=max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            stop=request.stop,
            tools=anthropic_tools,
            stream=True,
        )

        client = self._get_client()
        state: dict[str, Any] = {}

        logger.debug("anthropic.chat_completion_stream", model=request.model, stream=True)

        async with client.stream("POST", "/v1/messages", content=json.dumps(payload)) as resp:
            self._check_response(resp)

            async for line in resp.aiter_lines():
                if not line:
                    continue

                if line.startswith("event:"):
                    state["_pending_event"] = line[6:].strip()
                    continue

                if line.startswith("data:"):
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break

                    try:
                        event_data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    event_type = state.pop("_pending_event", event_data.get("type", ""))
                    delta_dict = anthropic_stream_event_to_delta(event_type, event_data, state)

                    if delta_dict is not None:
                        fr_str = state.get("finish_reason")
                        fr = FinishReason(fr_str) if fr_str else None
                        yield CompletionResponseChunk(
                            id=state.get("id", ""),
                            object="chat.completion.chunk",
                            created=0,
                            model=state.get("model", request.model),
                            choices=[
                                ChunkChoice(
                                    index=0,
                                    delta=DeltaMessage.model_validate(delta_dict),
                                    finish_reason=fr,
                                )
                            ],
                        )

    # ------------------------------------------------------------------
    # Unsupported operations
    # ------------------------------------------------------------------

    async def embedding(
        self,
        request: EmbeddingRequest,
        **kwargs: Any,
    ) -> EmbeddingResponse:
        raise ProviderError(
            provider="anthropic",
            message="Anthropic does not support embeddings",
        )

    async def image_generation(
        self,
        request: ImageRequest,
        **kwargs: Any,
    ) -> ImageResponse:
        raise ProviderError(
            provider="anthropic",
            message="Anthropic does not support image generation",
        )

    async def text_to_speech(
        self,
        request: Any,
    ) -> bytes:
        raise ProviderError(
            provider="anthropic",
            message="Anthropic does not support text-to-speech",
        )

    async def audio_transcription(
        self,
        request: AudioTranscriptionRequest,
        **kwargs: Any,
    ) -> AudioTranscriptionResponse:
        raise ProviderError(
            provider="anthropic",
            message="Anthropic does not support audio transcription",
        )

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def _check_response(self, response: httpx.Response) -> None:
        """Raise appropriate exception for non-2xx responses."""
        if response.status_code < 400:
            return

        try:
            body: dict[str, Any] = response.json()
        except Exception:
            body = {}

        error_obj = body.get("error", {})
        message: str = error_obj.get("message", response.text or "Unknown error")
        error_type: str = error_obj.get("type", "")

        if response.status_code == 401:
            raise AuthenticationError(message)
        if response.status_code == 429:
            raise RateLimitError(message)
        if response.status_code >= 500:
            raise ServiceUnavailableError(message)

        raise ProviderError(f"[{error_type}] {message}")


register_provider("anthropic", AnthropicProvider)
