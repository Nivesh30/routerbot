"""Abstract base class for all LLM provider adapters.

Every provider implements this interface to translate between
RouterBot's OpenAI-compatible format and the provider's native API.
Providers must be self-contained, testable in isolation, and use
``httpx.AsyncClient`` for all HTTP communication.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from routerbot.core.types import (
        AudioSpeechRequest,
        AudioTranscriptionRequest,
        AudioTranscriptionResponse,
        CompletionRequest,
        CompletionResponse,
        CompletionResponseChunk,
        EmbeddingRequest,
        EmbeddingResponse,
        ImageRequest,
        ImageResponse,
        RerankRequest,
        RerankResponse,
    )

logger = logging.getLogger(__name__)

# Default HTTP timeout configuration (seconds)
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 600.0
DEFAULT_WRITE_TIMEOUT = 10.0
DEFAULT_POOL_TIMEOUT = 5.0


class BaseProvider(ABC):
    """Abstract base class for all LLM provider adapters.

    Subclasses must implement at minimum :meth:`chat_completion` and
    :meth:`chat_completion_stream`. Other methods raise
    :class:`NotImplementedError` by default so providers only need to
    implement the endpoints they actually support.

    Parameters
    ----------
    api_key:
        Provider API key (if required).
    api_base:
        Base URL for the provider API.
    custom_headers:
        Extra headers to include on every request.
    timeout:
        Override default httpx timeout.
    max_retries:
        Maximum number of retries for transient failures (handled
        at the provider level for simple retry logic).
    """

    provider_name: str = "base"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        custom_headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        max_retries: int = 0,
        **kwargs: Any,
    ) -> None:
        self.api_key = api_key
        self.api_base = (api_base or "").rstrip("/")
        self.custom_headers = custom_headers or {}
        self.max_retries = max_retries
        self._extra_kwargs = kwargs

        self._timeout = timeout or httpx.Timeout(
            connect=DEFAULT_CONNECT_TIMEOUT,
            read=DEFAULT_READ_TIMEOUT,
            write=DEFAULT_WRITE_TIMEOUT,
            pool=DEFAULT_POOL_TIMEOUT,
        )

        # Lazy-initialized HTTP client — created on first use
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # HTTP client management
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """Build default headers for the HTTP client.

        Subclasses should override to add provider-specific auth headers.
        """
        headers: dict[str, str] = {
            "User-Agent": "RouterBot/0.1",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.custom_headers)
        return headers

    @property
    def client(self) -> httpx.AsyncClient:
        """Return (or lazily create) the shared HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                headers=self._build_headers(),
                timeout=self._timeout,
                follow_redirects=True,
            )
        return self._client

    # ------------------------------------------------------------------
    # Abstract methods — must be implemented by every provider
    # ------------------------------------------------------------------

    @abstractmethod
    async def chat_completion(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> CompletionResponse:
        """Execute a non-streaming chat completion request.

        Parameters
        ----------
        request:
            The OpenAI-compatible completion request.
        **kwargs:
            Extra provider-specific parameters.

        Returns
        -------
        CompletionResponse
            The normalised completion response.
        """

    @abstractmethod
    def chat_completion_stream(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> AsyncIterator[CompletionResponseChunk]:
        """Execute a streaming chat completion request.

        Yields
        ------
        CompletionResponseChunk
            Incremental response chunks in OpenAI format.
        """
        ...

    # ------------------------------------------------------------------
    # Optional endpoints — default to NotImplementedError
    # ------------------------------------------------------------------

    async def embedding(
        self,
        request: EmbeddingRequest,
        **kwargs: Any,
    ) -> EmbeddingResponse:
        """Create embeddings for the given input."""
        raise NotImplementedError(f"{self.provider_name} does not support embeddings")

    async def image_generation(
        self,
        request: ImageRequest,
        **kwargs: Any,
    ) -> ImageResponse:
        """Generate images from a text prompt."""
        raise NotImplementedError(f"{self.provider_name} does not support image generation")

    async def audio_speech(
        self,
        request: AudioSpeechRequest,
        **kwargs: Any,
    ) -> bytes:
        """Generate speech audio from text (TTS)."""
        raise NotImplementedError(f"{self.provider_name} does not support text-to-speech")

    async def audio_transcription(
        self,
        request: AudioTranscriptionRequest,
        **kwargs: Any,
    ) -> AudioTranscriptionResponse:
        """Transcribe audio to text."""
        raise NotImplementedError(f"{self.provider_name} does not support audio transcription")

    async def rerank(
        self,
        request: RerankRequest,
        **kwargs: Any,
    ) -> RerankResponse:
        """Rerank documents by relevance to a query."""
        raise NotImplementedError(f"{self.provider_name} does not support reranking")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check if the provider is reachable.

        Default implementation tries to list models. Override for
        providers with a dedicated health endpoint.
        """
        try:
            resp = await self.client.get("/v1/models")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        """Release HTTP client resources."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> BaseProvider:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<{type(self).__name__} provider={self.provider_name!r} base={self.api_base!r}>"
