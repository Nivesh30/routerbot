"""Google Gemini (AI Studio) provider implementation.

Uses the Gemini ``generateContent`` API with API key authentication.
Supports chat completions (streaming + tool use) and embeddings.
"""

from __future__ import annotations

import json
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
from routerbot.providers.gemini.config import (
    GEMINI_API_VERSION,
    GEMINI_DEFAULT_BASE,
)
from routerbot.providers.gemini.transform import (
    build_gemini_request,
    gemini_response_to_openai,
    gemini_sse_chunk_to_openai,
    openai_to_gemini_contents,
    openai_tools_to_gemini,
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


class GeminiProvider(BaseProvider):
    """Provider for Google Gemini AI Studio.

    Uses the ``generateContent`` / ``streamGenerateContent`` API
    with an API key passed as a query parameter.

    Parameters
    ----------
    api_key:
        Google Gemini API key (from ``https://aistudio.google.com/``).
    api_base:
        Override the base URL (useful for testing).
    """

    provider_name: str = "gemini"

    def __init__(
        self,
        api_key: str,
        *,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_base=api_base or GEMINI_DEFAULT_BASE,
            **kwargs,
        )

    def _build_headers(self) -> dict[str, str]:
        """Gemini uses a query-param API key, so no Authorization header."""
        return {
            "User-Agent": "RouterBot/0.1",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _base_params(self) -> dict[str, str]:
        """Return query params containing the API key."""
        return {"key": self.api_key or ""}

    def _chat_path(self, model: str, streaming: bool = False) -> str:
        endpoint = "streamGenerateContent" if streaming else "generateContent"
        return f"/{GEMINI_API_VERSION}/models/{model}:{endpoint}"

    def _embed_path(self, model: str) -> str:
        return f"/{GEMINI_API_VERSION}/models/{model}:embedContent"

    # ------------------------------------------------------------------
    # Chat completion
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> CompletionResponse:
        messages_dicts = [m.model_dump(exclude_none=True) for m in request.messages]
        system_instruction, gemini_contents = openai_to_gemini_contents(messages_dicts)
        gemini_tools = openai_tools_to_gemini([t.model_dump() for t in request.tools] if request.tools else None)

        payload = build_gemini_request(
            gemini_contents,
            system_instruction,
            max_tokens=int(request.max_tokens) if request.max_tokens else None,
            temperature=request.temperature,
            top_p=request.top_p,
            stop=request.stop,
            tools=gemini_tools,
        )

        path = self._chat_path(request.model)
        logger.debug("gemini.chat_completion", model=request.model)

        client = self.client
        try:
            response = await client.post(
                path,
                json=payload,
                params=self._base_params(),
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(message=str(exc), provider=self.provider_name, original_error=exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(message=str(exc), provider=self.provider_name, original_error=exc) from exc

        self._check_response(response)
        data: dict[str, Any] = response.json()
        return gemini_response_to_openai(data, request.model)

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
        system_instruction, gemini_contents = openai_to_gemini_contents(messages_dicts)
        gemini_tools = openai_tools_to_gemini([t.model_dump() for t in request.tools] if request.tools else None)

        payload = build_gemini_request(
            gemini_contents,
            system_instruction,
            max_tokens=int(request.max_tokens) if request.max_tokens else None,
            temperature=request.temperature,
            top_p=request.top_p,
            stop=request.stop,
            tools=gemini_tools,
        )

        # Streaming requires alt=sse query parameter
        params = {**self._base_params(), "alt": "sse"}
        path = self._chat_path(request.model, streaming=True)
        chunk_id = f"chatcmpl-{request.model.replace('.', '-')}-{id(request)}"

        state: dict[str, Any] = {}
        logger.debug("gemini.chat_completion_stream", model=request.model)

        client = self.client
        try:
            async with client.stream(
                "POST",
                path,
                json=payload,
                params=params,
            ) as response:
                self._check_response(response)

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    raw_json = line[5:].strip()
                    if raw_json in ("[DONE]", ""):
                        break
                    try:
                        chunk_data: dict[str, Any] = json.loads(raw_json)
                    except json.JSONDecodeError:
                        continue

                    chunk = gemini_sse_chunk_to_openai(chunk_data, request.model, chunk_id, state)
                    if chunk is not None:
                        yield chunk

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
        """Embed text using the Gemini embedding API.

        Accepts a single string or list of strings (batch).
        """
        inputs = request.input
        texts: list[str]
        if isinstance(inputs, str):
            texts = [inputs]
        elif isinstance(inputs, list) and all(isinstance(i, str) for i in inputs):
            texts = list(inputs)  # type: ignore[arg-type]
        else:
            raise ProviderError(
                message="Gemini embeddings only support string or list-of-string input.",
                provider=self.provider_name,
            )

        embeddings: list[EmbeddingData] = []
        total_tokens = 0

        client = self.client
        for idx, text in enumerate(texts):
            payload = {"content": {"parts": [{"text": text}]}}
            if request.dimensions:
                payload["outputDimensionality"] = request.dimensions  # type: ignore[assignment]

            path = self._embed_path(request.model)
            try:
                response = await client.post(
                    path,
                    json=payload,
                    params=self._base_params(),
                )
            except httpx.HTTPError as exc:
                raise ProviderError(message=str(exc), provider=self.provider_name, original_error=exc) from exc

            self._check_response(response)
            data = response.json()
            values: list[float] = data.get("embedding", {}).get("values", [])
            embeddings.append(EmbeddingData(index=idx, embedding=values))
            # Gemini doesn't return token counts per embed call
            total_tokens += len(text.split())

        return EmbeddingResponse(
            data=embeddings,
            model=request.model,
            usage=EmbeddingUsage(
                prompt_tokens=total_tokens,
                total_tokens=total_tokens,
            ),
        )

    # ------------------------------------------------------------------
    # Unsupported operations
    # ------------------------------------------------------------------

    async def image_generation(
        self,
        request: ImageRequest,
        **kwargs: Any,
    ) -> ImageResponse:
        raise ProviderError(
            message="Gemini AI Studio does not support image generation via this provider.",
            provider=self.provider_name,
        )

    async def audio_transcription(
        self,
        request: AudioTranscriptionRequest,
        **kwargs: Any,
    ) -> AudioTranscriptionResponse:
        raise ProviderError(
            message="Gemini does not support audio transcription via the generateContent API.",
            provider=self.provider_name,
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

        error = body.get("error", {})
        message: str = error.get("message") or body.get("message") or response.text or "Unknown error"
        status = response.status_code

        if status == 401 or status == 403:
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
        """List available models as a lightweight health probe."""
        try:
            client = self.client
            resp = await client.get(
                f"/{GEMINI_API_VERSION}/models",
                params=self._base_params(),
                timeout=5.0,
            )
            return resp.status_code < 500
        except Exception:
            return False


register_provider("gemini", GeminiProvider)
