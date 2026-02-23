"""AWS Bedrock provider implementation.

Uses the Bedrock Converse API for chat completions via SigV4 signing.
No boto3/botocore dependency — signs requests using built-in ``hashlib``
and ``hmac``.
"""

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
from routerbot.core.types import (
    ChunkChoice,
    CompletionResponse,
    CompletionResponseChunk,
    DeltaMessage,
)
from routerbot.providers.base import BaseProvider
from routerbot.providers.bedrock.config import (
    BEDROCK_SERVICE,
    DEFAULT_REGION,
    build_bedrock_base_url,
)
from routerbot.providers.bedrock.sigv4 import sign_request
from routerbot.providers.bedrock.transform import (
    build_converse_request,
    converse_response_to_openai,
    decode_event_stream,
    openai_to_converse_messages,
    openai_tools_to_converse,
    parse_converse_stream_event,
)
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


class BedrockProvider(BaseProvider):
    """Provider for AWS Bedrock (Converse API).

    Supports:
    - Chat completions (including streaming and tool use)
    - No embeddings or image generation via Converse API

    Authentication is via AWS credentials — either explicit key/secret
    or environment variables (``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``,
    ``AWS_SESSION_TOKEN``).

    Parameters
    ----------
    access_key_id:
        AWS Access Key ID.
    secret_access_key:
        AWS Secret Access Key.
    session_token:
        Optional STS session token.
    region:
        AWS region (default ``us-east-1``).
    api_base:
        Override the Bedrock Runtime endpoint (useful for testing).
    """

    provider_name: str = "bedrock"

    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        *,
        session_token: str | None = None,
        region: str = DEFAULT_REGION,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        computed_base = api_base or build_bedrock_base_url(region)
        super().__init__(
            api_key=None,  # Auth is handled via SigV4, not Bearer token
            api_base=computed_base,
            **kwargs,
        )
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.session_token = session_token
        self.region = region

    # ------------------------------------------------------------------
    # Base class: no default Authorization header
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """Bedrock does not use a static Authorization header."""
        return {
            "User-Agent": "RouterBot/0.1",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Signed request helper
    # ------------------------------------------------------------------

    def _sign_and_send_headers(
        self,
        path: str,
        payload: bytes,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Return headers with the SigV4 Authorization appended."""
        url = f"{self.api_base}{path}"
        base_headers = self._build_headers()
        if extra_headers:
            base_headers.update(extra_headers)

        sig_headers = sign_request(
            method="POST",
            url=url,
            payload=payload,
            region=self.region,
            service=BEDROCK_SERVICE,
            access_key=self.access_key_id,
            secret_key=self.secret_access_key,
            session_token=self.session_token,
        )

        return {**base_headers, **sig_headers}

    # ------------------------------------------------------------------
    # Chat completion
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        request: CompletionRequest,
        **kwargs: Any,
    ) -> CompletionResponse:
        messages_dicts = [m.model_dump(exclude_none=True) for m in request.messages]
        system, converse_messages = openai_to_converse_messages(messages_dicts)
        tool_config = openai_tools_to_converse([t.model_dump() for t in request.tools] if request.tools else None)

        payload_dict = build_converse_request(
            model=request.model,
            messages=converse_messages,
            system=system,
            max_tokens=int(request.max_tokens or 4096),
            temperature=request.temperature,
            top_p=request.top_p,
            stop=request.stop,
            tool_config=tool_config,
        )

        path = f"/model/{request.model}/converse"
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        headers = self._sign_and_send_headers(path, payload_bytes)

        logger.debug("bedrock.chat_completion", model=request.model)

        client = self.client
        try:
            response = await client.post(path, content=payload_bytes, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError(message=str(exc), provider=self.provider_name, original_error=exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(message=str(exc), provider=self.provider_name, original_error=exc) from exc

        self._check_response(response)
        data: dict[str, Any] = response.json()
        return converse_response_to_openai(data, request.model)

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
        system, converse_messages = openai_to_converse_messages(messages_dicts)
        tool_config = openai_tools_to_converse([t.model_dump() for t in request.tools] if request.tools else None)

        payload_dict = build_converse_request(
            model=request.model,
            messages=converse_messages,
            system=system,
            max_tokens=int(request.max_tokens or 4096),
            temperature=request.temperature,
            top_p=request.top_p,
            stop=request.stop,
            tool_config=tool_config,
        )

        path = f"/model/{request.model}/converse-stream"
        payload_bytes = json.dumps(payload_dict).encode("utf-8")
        headers = self._sign_and_send_headers(
            path,
            payload_bytes,
            extra_headers={"Accept": "application/vnd.amazon.eventstream"},
        )

        state: dict[str, Any] = {}
        chunk_id = f"chatcmpl-{request.model.replace(':', '-').replace('.', '-')}"

        logger.debug("bedrock.chat_completion_stream", model=request.model)

        client = self.client
        try:
            async with client.stream("POST", path, content=payload_bytes, headers=headers) as response:
                self._check_response(response)

                # Accumulate full binary EventStream response
                raw_bytes = b""
                async for chunk in response.aiter_bytes():
                    raw_bytes += chunk

                # Decode all events from EventStream binary format
                events = decode_event_stream(raw_bytes)

        except httpx.TimeoutException as exc:
            raise ProviderError(message=str(exc), provider=self.provider_name, original_error=exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(message=str(exc), provider=self.provider_name, original_error=exc) from exc

        for event in events:
            delta_dict = parse_converse_stream_event(event, state)
            if delta_dict is not None:
                fr_str = state.get("finish_reason")
                fr = FinishReason(fr_str) if fr_str else None
                yield CompletionResponseChunk(
                    id=chunk_id,
                    object="chat.completion.chunk",
                    created=0,
                    model=request.model,
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
            message="Bedrock Converse API does not support embeddings. Use amazon.titan-embed-text-v2:0 via the InvokeModel API.",
            provider=self.provider_name,
        )

    async def image_generation(
        self,
        request: ImageRequest,
        **kwargs: Any,
    ) -> ImageResponse:
        raise ProviderError(
            message="Bedrock does not support image generation via the Converse API.",
            provider=self.provider_name,
        )

    async def audio_transcription(
        self,
        request: AudioTranscriptionRequest,
        **kwargs: Any,
    ) -> AudioTranscriptionResponse:
        raise ProviderError(
            message="Bedrock does not support audio transcription.",
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

        message: str = body.get("message", response.text or "Unknown error")
        error_type: str = body.get("__type", "")

        if response.status_code == 401 or "UnrecognizedClientException" in error_type:
            raise AuthenticationError(message)
        if response.status_code == 429 or "TooManyRequestsException" in error_type:
            raise RateLimitError(message)
        if response.status_code >= 500:
            raise ServiceUnavailableError(message)

        raise ProviderError(
            message=f"[{error_type}] {message}",
            provider=self.provider_name,
            status_code=response.status_code,
        )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Bedrock doesn't have a dedicated health endpoint; return True by default."""
        try:
            # Try listing foundation models (ListFoundationModels)
            path = "/foundation-models"
            url = f"https://bedrock.{self.region}.amazonaws.com{path}"
            # Use the non-runtime endpoint for listing
            sig_headers = sign_request(
                method="GET",
                url=url,
                payload=b"",
                region=self.region,
                service="bedrock",
                access_key=self.access_key_id,
                secret_key=self.secret_access_key,
                session_token=self.session_token,
            )
            headers = {**self._build_headers(), **sig_headers}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers, timeout=5.0)
                return resp.status_code < 500
        except Exception:
            return False


register_provider("bedrock", BedrockProvider)
