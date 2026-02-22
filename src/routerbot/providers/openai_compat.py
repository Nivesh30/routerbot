"""Generic OpenAI-compatible provider adapter.

Works with any provider that implements the OpenAI chat completions API
(e.g. Groq, DeepSeek, Together AI, Fireworks, vLLM, etc.). Only requires
``api_base`` and ``api_key`` to be configured.
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
    CompletionResponse,
    CompletionResponseChunk,
    EmbeddingResponse,
)
from routerbot.providers.base import BaseProvider
from routerbot.providers.registry import register_provider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from routerbot.core.types import (
        CompletionRequest,
        EmbeddingRequest,
    )

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(BaseProvider):
    """Provider for any OpenAI-compatible API.

    This provider works out-of-the-box with services that implement:
    - ``POST /chat/completions``
    - ``POST /embeddings`` (optional)
    - ``GET /models`` (optional, for health check)

    Parameters
    ----------
    api_key:
        API key (sent as ``Authorization: Bearer <key>``).
    api_base:
        The base URL for the API (e.g. ``https://api.groq.com/openai/v1``).
    provider_label:
        Display name for this provider in logs (defaults to ``"openai_compat"``).
    """

    provider_name: str = "openai_compat"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        provider_label: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base, **kwargs)
        if provider_label:
            self.provider_name = provider_label

    # ------------------------------------------------------------------
    # Chat completions
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> CompletionResponse:
        """Send a non-streaming chat completion request."""
        payload = request.model_dump(exclude_none=True)
        payload["stream"] = False

        resp = await self._post("/chat/completions", payload)
        return CompletionResponse.model_validate(resp)

    async def chat_completion_stream(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> AsyncIterator[CompletionResponseChunk]:
        """Send a streaming chat completion request and yield chunks."""
        payload = request.model_dump(exclude_none=True)
        payload["stream"] = True

        async for line in self._stream_post("/chat/completions", payload):
            if line == "[DONE]":
                return
            try:
                chunk = CompletionResponseChunk.model_validate_json(line)
                yield chunk
            except Exception:
                logger.debug("Skipping unparseable SSE line: %s", line[:200])

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embedding(
        self,
        request: EmbeddingRequest,
        **kwargs: Any,
    ) -> EmbeddingResponse:
        """Create embeddings."""
        payload = request.model_dump(exclude_none=True)
        resp = await self._post("/embeddings", payload)
        return EmbeddingResponse.model_validate(resp)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON and return parsed response, handling errors."""
        try:
            response = await self.client.post(
                path,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        except httpx.TimeoutException as exc:
            msg = f"{self.provider_name} request timed out"
            raise ProviderError(
                message=msg,
                provider=self.provider_name,
                original_error=exc,
            ) from exc
        except httpx.HTTPError as exc:
            msg = f"{self.provider_name} HTTP error: {exc}"
            raise ProviderError(
                message=msg,
                provider=self.provider_name,
                original_error=exc,
            ) from exc

        self._check_response(response)
        return response.json()  # type: ignore[no-any-return]

    async def _stream_post(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> AsyncIterator[str]:
        """POST JSON and yield SSE data lines."""
        try:
            async with self.client.stream(
                "POST",
                path,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            ) as response:
                self._check_response(response)
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data = line[6:]
                        yield data
        except httpx.TimeoutException as exc:
            msg = f"{self.provider_name} stream timed out"
            raise ProviderError(
                message=msg,
                provider=self.provider_name,
                original_error=exc,
            ) from exc
        except httpx.HTTPError as exc:
            msg = f"{self.provider_name} stream HTTP error: {exc}"
            raise ProviderError(
                message=msg,
                provider=self.provider_name,
                original_error=exc,
            ) from exc

    def _check_response(self, response: httpx.Response) -> None:
        """Raise the appropriate RouterBot exception for HTTP error codes."""
        if response.status_code < 400:
            return

        try:
            body = response.json()
            error_msg = body.get("error", {}).get("message", response.text)
        except (json.JSONDecodeError, ValueError):
            error_msg = response.text[:500]

        status = response.status_code

        if status == 401:
            raise AuthenticationError(message=f"{self.provider_name}: {error_msg}")
        if status == 429:
            raise RateLimitError(message=f"{self.provider_name}: {error_msg}")
        if status >= 500:
            raise ServiceUnavailableError(message=f"{self.provider_name}: {error_msg}")

        raise ProviderError(
            message=f"{self.provider_name} error ({status}): {error_msg}",
            provider=self.provider_name,
            status_code=status,
        )


# Auto-register with the provider registry on import
register_provider("openai_compat", OpenAICompatibleProvider)
