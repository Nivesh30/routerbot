"""Chat completions route — POST /v1/chat/completions.

Implements the OpenAI-compatible chat completions API with support for
both synchronous and streaming (SSE) responses.

The route dispatches requests to the configured provider for the requested
model. In Stage 3.3 this will be replaced by the full Router layer.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, StreamingResponse

from routerbot.core.exceptions import BadRequestError, ModelNotFoundError
from routerbot.core.types import CompletionRequest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from routerbot.core.types import CompletionResponse, CompletionResponseChunk

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat Completions"])


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------


async def _get_provider_for_model(request: Request, model_name: str) -> Any:
    """Resolve a provider instance for the requested model.

    Looks up the model in the RouterBot config and instantiates the
    appropriate provider.

    Raises
    ------
    ModelNotFoundError
        If the model is not configured.
    """
    state = getattr(request.app.state, "routerbot", None)
    config = state.config if state else None

    if config is None:
        raise ModelNotFoundError(model_name)

    # Find the model entry in config
    entry = next((m for m in config.model_list if m.model_name == model_name), None)
    if entry is None:
        raise ModelNotFoundError(model_name)

    # Resolve provider from the model field (format: "provider/model")
    provider_model = entry.provider_params.model
    if "/" not in provider_model:
        raise BadRequestError(f"Invalid provider/model format: {provider_model!r}")

    provider_name, _ = provider_model.split("/", 1)

    # Import and instantiate the provider
    from routerbot.providers.registry import get_provider_class

    provider_cls = get_provider_class(provider_name)

    # Resolve API key (support os.environ/ references)
    api_key = entry.provider_params.api_key
    if api_key and api_key.startswith("os.environ/"):
        import os

        env_var = api_key.removeprefix("os.environ/")
        api_key = os.environ.get(env_var)

    return provider_cls(
        api_key=api_key,
        api_base=entry.provider_params.api_base,
        custom_headers=entry.provider_params.extra_headers,
    )


def _log_usage(response: CompletionResponse, model: str) -> None:
    """Background task: log token usage after a completion."""
    if response.usage:
        logger.info(
            "Completion usage",
            extra={
                "model": model,
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        )


async def _stream_sse(
    generator: AsyncIterator[CompletionResponseChunk],
) -> AsyncIterator[str]:
    """Convert a chunk iterator to SSE-formatted strings."""
    async for chunk in generator:
        yield f"data: {chunk.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("/chat/completions", summary="Create chat completion", response_model=None)
async def chat_completions(
    body: CompletionRequest,
    raw_request: Request,
    background_tasks: BackgroundTasks,
) -> StreamingResponse | JSONResponse:
    """Create a chat completion — OpenAI API compatible.

    Supports both regular (JSON) and streaming (SSE) responses.
    Set ``stream: true`` in the request body to enable streaming.
    """
    request_id = getattr(raw_request.state, "request_id", None) or "unknown"

    # Apply semantic routing if configured
    effective_model = body.model
    state = getattr(raw_request.app.state, "routerbot", None)
    semantic_router = getattr(state, "semantic_router", None) if state else None
    if semantic_router and semantic_router.enabled:
        effective_model = await semantic_router.route(
            model=body.model,
            messages=[m.model_dump() for m in body.messages] if body.messages else None,
        )
        if effective_model != body.model:
            logger.info(
                "Semantic routing: %s → %s (request=%s)",
                body.model,
                effective_model,
                request_id,
            )

    provider = await _get_provider_for_model(raw_request, effective_model)

    # ── Request transformation pipeline (pre-request) ──
    transform_pipeline = getattr(state, "transform_pipeline", None) if state else None
    if transform_pipeline and transform_pipeline.enabled:
        from routerbot.core.transform.models import TransformContext

        tf_context = TransformContext(
            model=effective_model,
            request_id=request_id,
            team_id=getattr(raw_request.state, "team_id", None),
            key_id=getattr(raw_request.state, "key_id", None),
            user_id=getattr(raw_request.state, "user_id", None),
        )
        request_data = body.model_dump(exclude_none=True)
        await transform_pipeline.run_pre_request(request_data, tf_context)
        body = CompletionRequest(**request_data)

    if body.stream:
        # --- Streaming response ---
        generator = provider.chat_completion_stream(body)

        return StreamingResponse(
            _stream_sse(generator),
            media_type="text/event-stream",
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    # --- Synchronous response ---
    response: CompletionResponse = await provider.chat_completion(body)
    background_tasks.add_task(_log_usage, response, body.model)

    # ── Response transformation pipeline (post-response) ──
    response_data = response.model_dump()
    if transform_pipeline and transform_pipeline.enabled:
        await transform_pipeline.run_post_response(response_data, tf_context)

    return JSONResponse(
        content=response_data,
        headers={"X-Request-ID": request_id},
    )


@router.post("/completions", summary="Create legacy text completion", response_model=None)
async def text_completions(
    body: CompletionRequest,
    raw_request: Request,
    background_tasks: BackgroundTasks,
) -> StreamingResponse | JSONResponse:
    """Create a legacy text completion (OpenAI completions endpoint).

    Proxied to ``/v1/chat/completions`` internally since most modern
    providers only support the chat format.
    """
    # Legacy completions delegate to the chat completions handler.
    return await chat_completions(body, raw_request, background_tasks)
