"""Ollama local LLM provider.

Ollama runs locally (default ``http://localhost:11434``) and serves
models via a REST API.  The chat API (``/api/chat``) uses a different
request/response shape from OpenAI, so we translate in
:mod:`routerbot.providers.ollama.transform`.

References
----------
- Chat API: https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-chat-completion
- Embed API: https://github.com/ollama/ollama/blob/main/docs/api.md#generate-embeddings
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

import httpx

from routerbot.core.exceptions import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
    ServiceUnavailableError,
)
from routerbot.core.logging import get_logger
from routerbot.core.types import (
    CompletionResponse,
    CompletionResponseChunk,
    EmbeddingData,
    EmbeddingResponse,
    EmbeddingUsage,
)
from routerbot.providers.base import BaseProvider
from routerbot.providers.ollama.transform import (
    ollama_chunk_to_openai,
    ollama_response_to_openai,
)
from routerbot.providers.registry import register_provider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from routerbot.core.types import (
        AudioTranscriptionRequest,
        AudioTranscriptionResponse,
        CompletionRequest,
        EmbeddingRequest,
        ImageRequest,
        ImageResponse,
    )

logger = get_logger(__name__)

OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider(BaseProvider):
    """Provider for Ollama local LLM inference server.

    Ollama exposes a REST API for running open-source models locally.
    No API key is required by default (can be configured with an optional
    bearer token for secured Ollama instances).

    Parameters
    ----------
    api_key:
        Optional bearer token for password-protected Ollama instances.
    api_base:
        Override the Ollama base URL (default: ``http://localhost:11434``).
    """

    provider_name: str = "ollama"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_base=api_base or OLLAMA_DEFAULT_BASE_URL,
            **kwargs,
        )

    def _build_headers(self) -> dict[str, str]:
        """Build Ollama request headers (auth is optional)."""
        headers: dict[str, str] = {
            "User-Agent": "RouterBot/0.1",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.custom_headers)
        return headers

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_chat_payload(self, request: CompletionRequest) -> dict[str, Any]:
        """Build an Ollama ``/api/chat`` payload from a CompletionRequest."""
        messages = []
        for msg in request.messages:
            m: dict[str, Any] = {
                "role": msg.role.value if hasattr(msg.role, "value") else str(msg.role),
                "content": msg.content or "",
            }
            # Pass through images if present (Ollama multimodal support)
            if hasattr(msg, "images") and getattr(msg, "images", None):
                m["images"] = msg.images
            messages.append(m)

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
        }

        # Options: Ollama wraps sampling params inside "options"
        options: dict[str, Any] = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.top_p is not None:
            options["top_p"] = request.top_p
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        if request.stop is not None:
            options["stop"] = request.stop if isinstance(request.stop, list) else [request.stop]
        if request.seed is not None:
            options["seed"] = request.seed
        if options:
            payload["options"] = options

        # Tools (function calling)
        if request.tools:
            payload["tools"] = [t.model_dump(exclude_none=True) for t in request.tools]

        return payload

    def _check_response(self, response: httpx.Response) -> None:
        """Raise provider-specific exceptions for HTTP errors."""
        if response.status_code < 400:
            return

        try:
            body: dict[str, Any] = response.json()
        except Exception:
            body = {}

        message: str = body.get("error") or body.get("message") or response.text[:500] or "Unknown error"
        status = response.status_code

        if status == 401:
            raise AuthenticationError(message)
        if status == 429:
            raise RateLimitError(message)
        if status >= 500:
            raise ServiceUnavailableError(message)

        raise ProviderError(
            message=message,
            provider=self.provider_name,
            status_code=status,
        )

    # ------------------------------------------------------------------
    # Chat completions
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> CompletionResponse:
        """Execute a non-streaming chat completion via ``POST /api/chat``."""
        payload = self._build_chat_payload(request)
        payload["stream"] = False

        client = self.client
        try:
            response = await client.post("/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                message=f"Ollama request timed out: {exc}",
                provider=self.provider_name,
                original_error=exc,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                message=f"Ollama HTTP error: {exc}",
                provider=self.provider_name,
                original_error=exc,
            ) from exc

        self._check_response(response)
        data: dict[str, Any] = response.json()
        return ollama_response_to_openai(data, request.model)

    def chat_completion_stream(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> AsyncIterator[CompletionResponseChunk]:
        """Execute a streaming chat completion via ``POST /api/chat``."""
        return self._stream_generator(request)

    async def _stream_generator(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[CompletionResponseChunk]:
        """Stream Ollama NDJSON (newline-delimited JSON) responses."""
        payload = self._build_chat_payload(request)
        payload["stream"] = True

        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
        client = self.client

        try:
            async with client.stream("POST", "/api/chat", json=payload) as response:
                self._check_response(response)
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        chunk = ollama_chunk_to_openai(data, request.model, chunk_id)
                        yield chunk
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        logger.debug("Skipping non-JSON Ollama stream line: %s", line[:200])
                    except Exception:
                        logger.debug("Failed to parse Ollama stream chunk: %s", line[:200])
        except httpx.TimeoutException as exc:
            raise ProviderError(
                message=f"Ollama stream timed out: {exc}",
                provider=self.provider_name,
                original_error=exc,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                message=f"Ollama stream HTTP error: {exc}",
                provider=self.provider_name,
                original_error=exc,
            ) from exc

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embedding(
        self,
        request: EmbeddingRequest,
        **kwargs: Any,
    ) -> EmbeddingResponse:
        """Create embeddings via ``POST /api/embed``.

        Ollama ``/api/embed`` accepts a list of strings and returns
        ``{"embeddings": [[...], ...], "model": "...", ...}``.
        """
        inputs = request.input
        if isinstance(inputs, str):
            texts: list[str] = [inputs]
        elif isinstance(inputs, list) and all(isinstance(i, str) for i in inputs):
            texts = list(inputs)  # type: ignore[arg-type]
        else:
            raise ProviderError(
                message="Ollama embeddings only support string or list-of-string input.",
                provider=self.provider_name,
            )

        payload: dict[str, Any] = {
            "model": request.model,
            "input": texts,
        }

        client = self.client
        try:
            response = await client.post("/api/embed", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(
                message=f"Ollama embed error: {exc}",
                provider=self.provider_name,
                original_error=exc,
            ) from exc

        self._check_response(response)
        data = response.json()

        # Ollama /api/embed returns: {"embeddings": [[...], ...]}
        raw_embeddings: list[list[float]] = data.get("embeddings", [])
        total_tokens: int = data.get("prompt_eval_count", len(texts))

        return EmbeddingResponse(
            data=[EmbeddingData(index=i, embedding=vec) for i, vec in enumerate(raw_embeddings)],
            model=request.model,
            usage=EmbeddingUsage(
                prompt_tokens=total_tokens,
                total_tokens=total_tokens,
            ),
        )

    # ------------------------------------------------------------------
    # Unsupported endpoints
    # ------------------------------------------------------------------

    async def image_generation(
        self,
        request: ImageRequest,
        **kwargs: Any,
    ) -> ImageResponse:
        raise ProviderError(
            message="Ollama does not support image generation.",
            provider=self.provider_name,
        )

    async def audio_transcription(
        self,
        request: AudioTranscriptionRequest,
        **kwargs: Any,
    ) -> AudioTranscriptionResponse:
        raise ProviderError(
            message="Ollama does not support audio transcription.",
            provider=self.provider_name,
        )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check if Ollama server is running by hitting ``GET /api/tags``."""
        try:
            resp = await self.client.get("/api/tags", timeout=5.0)
            return resp.status_code < 500
        except Exception:
            return False


# Auto-register with provider registry
register_provider("ollama", OllamaProvider)
