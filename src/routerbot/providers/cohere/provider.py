"""Cohere provider implementation.

Cohere's v2 API uses an OpenAI-compatible message format but returns
Cohere-specific finish reasons and embedding shapes.  We inherit from
``OpenAICompatibleProvider`` for chat completions via ``/v2/chat``
and override the response parsing only where Cohere differs.
"""

from __future__ import annotations

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
from routerbot.providers.cohere.config import COHERE_BASE_URL
from routerbot.providers.cohere.transform import cohere_response_to_openai
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


class CohereProvider(BaseProvider):
    """Provider for Cohere (Command R+, Command R, etc.).

    Uses the Cohere v2 Chat API. Cohere's v2 API accepts OpenAI-style
    messages but returns Cohere-specific response shapes.

    Parameters
    ----------
    api_key:
        Cohere API key (from ``https://dashboard.cohere.com/``).
    api_base:
        Override the Cohere base URL (useful for testing).
    """

    provider_name: str = "cohere"

    def __init__(
        self,
        api_key: str,
        *,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_base=api_base or COHERE_BASE_URL,
            **kwargs,
        )

    def _build_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "RouterBot/0.1",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    # ------------------------------------------------------------------
    # Chat completion
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> CompletionResponse:
        payload = request.model_dump(exclude_none=True)
        payload["stream"] = False

        client = self.client
        try:
            response = await client.post("/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(message=str(exc), provider=self.provider_name, original_error=exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(message=str(exc), provider=self.provider_name, original_error=exc) from exc

        self._check_response(response)
        data: dict[str, Any] = response.json()
        return cohere_response_to_openai(data, request.model)

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
        """Stream via Cohere SSE, which is in OpenAI's SSE format for v2."""

        payload = request.model_dump(exclude_none=True)
        payload["stream"] = True

        client = self.client
        try:
            async with client.stream("POST", "/chat", json=payload) as response:
                self._check_response(response)
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw in ("[DONE]", ""):
                        break
                    try:
                        chunk = CompletionResponseChunk.model_validate_json(raw)
                        yield chunk
                    except Exception:
                        logger.debug("Skipping unparseable Cohere SSE line: %s", raw[:200])
        except httpx.TimeoutException as exc:
            raise ProviderError(message=str(exc), provider=self.provider_name, original_error=exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(message=str(exc), provider=self.provider_name, original_error=exc) from exc

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embedding(
        self,
        request: EmbeddingRequest,
        **kwargs: Any,
    ) -> EmbeddingResponse:
        """Embed text using the Cohere Embed API."""
        inputs = request.input
        if isinstance(inputs, str):
            texts = [inputs]
        elif isinstance(inputs, list) and all(isinstance(i, str) for i in inputs):
            texts = list(inputs)  # type: ignore[arg-type]
        else:
            raise ProviderError(
                message="Cohere embeddings only support string or list-of-string input.",
                provider=self.provider_name,
            )

        payload: dict[str, Any] = {
            "model": request.model,
            "texts": texts,
            "input_type": "search_query",
            "embedding_types": ["float"],
        }

        client = self.client
        try:
            response = await client.post("/embed", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(message=str(exc), provider=self.provider_name, original_error=exc) from exc

        self._check_response(response)
        data = response.json()

        # Cohere v2: {"id": "...", "embeddings": {"float": [[...], ...]}, ...}
        float_embeddings: list[list[float]] = data.get("embeddings", {}).get("float", []) or data.get("embeddings", [])

        return EmbeddingResponse(
            data=[EmbeddingData(index=i, embedding=vec) for i, vec in enumerate(float_embeddings)],
            model=request.model,
            usage=EmbeddingUsage(
                prompt_tokens=len(texts),
                total_tokens=len(texts),
            ),
        )

    # ------------------------------------------------------------------
    # Unsupported
    # ------------------------------------------------------------------

    async def image_generation(
        self,
        request: ImageRequest,
        **kwargs: Any,
    ) -> ImageResponse:
        raise ProviderError(
            message="Cohere does not support image generation.",
            provider=self.provider_name,
        )

    async def audio_transcription(
        self,
        request: AudioTranscriptionRequest,
        **kwargs: Any,
    ) -> AudioTranscriptionResponse:
        raise ProviderError(
            message="Cohere does not support audio transcription.",
            provider=self.provider_name,
        )

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def _check_response(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return

        try:
            body: dict[str, Any] = response.json()
        except Exception:
            body = {}

        message: str = body.get("message") or body.get("error", {}).get("message") or response.text or "Unknown error"
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
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        try:
            client = self.client
            resp = await client.get("/models", timeout=5.0)
            return resp.status_code < 500
        except Exception:
            return False


register_provider("cohere", CohereProvider)
