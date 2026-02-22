"""OpenAI provider — chat completions, embeddings, images, audio.

This is the reference provider implementation. Since RouterBot's internal
format matches OpenAI exactly, transformations are minimal.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

from routerbot.core.exceptions import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
    ServiceUnavailableError,
)
from routerbot.core.types import (
    AudioTranscriptionResponse,
    CompletionResponse,
    CompletionResponseChunk,
    EmbeddingResponse,
    ImageResponse,
)
from routerbot.providers.base import BaseProvider
from routerbot.providers.openai.config import OPENAI_API_BASE
from routerbot.providers.openai.transform import prepare_chat_payload
from routerbot.providers.registry import register_provider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from routerbot.core.types import (
        AudioSpeechRequest,
        AudioTranscriptionRequest,
        CompletionRequest,
        EmbeddingRequest,
        ImageRequest,
    )

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseProvider):
    """Provider for the OpenAI API (api.openai.com).

    Supports:
    - Chat completions (including streaming, tool calling, vision, JSON mode)
    - Embeddings
    - Image generation (DALL-E)
    - Audio transcription (Whisper)
    - Text-to-speech (TTS)
    """

    provider_name: str = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_base=api_base or OPENAI_API_BASE,
            **kwargs,
        )
        self.organization = organization
        self.project = project

    def _build_headers(self) -> dict[str, str]:
        """Build OpenAI-specific headers."""
        headers = super()._build_headers()
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        if self.project:
            headers["OpenAI-Project"] = self.project
        return headers

    # ------------------------------------------------------------------
    # Chat completions
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> CompletionResponse:
        """Execute a non-streaming chat completion."""
        payload = prepare_chat_payload(request)
        payload["stream"] = False

        data = await self._post("/chat/completions", payload)
        return CompletionResponse.model_validate(data)

    async def chat_completion_stream(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> AsyncIterator[CompletionResponseChunk]:
        """Execute a streaming chat completion."""
        payload = prepare_chat_payload(request)
        payload["stream"] = True

        # Include stream_options if requested
        if request.stream_options:
            payload["stream_options"] = request.stream_options.model_dump(exclude_none=True)

        async for line in self._stream_post("/chat/completions", payload):
            if line == "[DONE]":
                return
            try:
                chunk = CompletionResponseChunk.model_validate_json(line)
                yield chunk
            except Exception:
                logger.debug("Skipping unparseable SSE chunk: %s", line[:200])

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embedding(
        self,
        request: EmbeddingRequest,
        **kwargs: Any,
    ) -> EmbeddingResponse:
        """Create embeddings via the OpenAI /embeddings endpoint."""
        payload = request.model_dump(exclude_none=True)
        data = await self._post("/embeddings", payload)
        return EmbeddingResponse.model_validate(data)

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------

    async def image_generation(
        self,
        request: ImageRequest,
        **kwargs: Any,
    ) -> ImageResponse:
        """Generate images via the OpenAI /images/generations endpoint."""
        payload = request.model_dump(exclude_none=True)
        data = await self._post("/images/generations", payload)
        return ImageResponse.model_validate(data)

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    async def audio_speech(
        self,
        request: AudioSpeechRequest,
        **kwargs: Any,
    ) -> bytes:
        """Generate speech via the OpenAI /audio/speech endpoint."""
        payload = request.model_dump(exclude_none=True)
        try:
            response = await self.client.post(
                "/audio/speech",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            msg = f"OpenAI TTS error: {exc}"
            raise ProviderError(message=msg, provider=self.provider_name, original_error=exc) from exc

        self._check_response(response)
        return response.content

    async def audio_transcription(
        self,
        request: AudioTranscriptionRequest,
        **kwargs: Any,
    ) -> AudioTranscriptionResponse:
        """Transcribe audio via the OpenAI /audio/transcriptions endpoint.

        The audio file bytes should be passed as ``file=<bytes>`` in kwargs
        since the request model does not carry the file itself (it's handled
        as multipart form data at the proxy layer).
        """
        file_bytes: bytes | None = kwargs.get("file")
        if file_bytes is None:
            msg = "audio_transcription requires file=<bytes> in kwargs"
            raise ProviderError(message=msg, provider=self.provider_name)

        # Transcription uses multipart form data
        form_data: dict[str, Any] = {"model": request.model}
        if request.language:
            form_data["language"] = request.language
        if request.prompt:
            form_data["prompt"] = request.prompt
        if request.response_format:
            form_data["response_format"] = request.response_format
        if request.temperature is not None:
            form_data["temperature"] = str(request.temperature)

        files = {"file": ("audio.webm", file_bytes, "application/octet-stream")}

        try:
            response = await self.client.post(
                "/audio/transcriptions",
                data=form_data,
                files=files,
            )
        except httpx.HTTPError as exc:
            msg = f"OpenAI transcription error: {exc}"
            raise ProviderError(message=msg, provider=self.provider_name, original_error=exc) from exc

        self._check_response(response)
        resp_data = response.json()
        # The simple text response format just returns {"text": "..."}
        if isinstance(resp_data, dict):
            return AudioTranscriptionResponse.model_validate(resp_data)
        return AudioTranscriptionResponse(text=str(resp_data))

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON and return parsed response."""
        try:
            response = await self.client.post(
                path,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        except httpx.TimeoutException as exc:
            msg = f"OpenAI request to {path} timed out"
            raise ProviderError(message=msg, provider=self.provider_name, original_error=exc) from exc
        except httpx.HTTPError as exc:
            msg = f"OpenAI HTTP error on {path}: {exc}"
            raise ProviderError(message=msg, provider=self.provider_name, original_error=exc) from exc

        self._check_response(response)
        return response.json()  # type: ignore[no-any-return]

    async def _stream_post(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> AsyncIterator[str]:
        """POST and yield SSE data lines."""
        try:
            async with self.client.stream(
                "POST",
                path,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            ) as response:
                self._check_response(response)
                async for line in response.aiter_lines():
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if stripped.startswith("data: "):
                        yield stripped[6:]
        except httpx.TimeoutException as exc:
            msg = f"OpenAI stream on {path} timed out"
            raise ProviderError(message=msg, provider=self.provider_name, original_error=exc) from exc
        except httpx.HTTPError as exc:
            msg = f"OpenAI stream HTTP error on {path}: {exc}"
            raise ProviderError(message=msg, provider=self.provider_name, original_error=exc) from exc

    def _check_response(self, response: httpx.Response) -> None:
        """Raise appropriate RouterBot exceptions for HTTP errors."""
        if response.status_code < 400:
            return

        try:
            body = response.json()
            error_msg = body.get("error", {}).get("message", response.text)
        except (json.JSONDecodeError, ValueError):
            error_msg = response.text[:500]

        status = response.status_code

        if status == 401:
            raise AuthenticationError(message=f"OpenAI: {error_msg}")
        if status == 429:
            raise RateLimitError(message=f"OpenAI: {error_msg}")
        if status >= 500:
            raise ServiceUnavailableError(message=f"OpenAI: {error_msg}")

        raise ProviderError(
            message=f"OpenAI error ({status}): {error_msg}",
            provider=self.provider_name,
            status_code=status,
        )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check if OpenAI API is reachable."""
        try:
            resp = await self.client.get("/models")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False


# Auto-register with provider registry
register_provider("openai", OpenAIProvider)
