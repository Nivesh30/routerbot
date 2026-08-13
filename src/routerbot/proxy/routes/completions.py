"""Chat completions route — POST /v1/chat/completions.

Implements the OpenAI-compatible chat completions API with support for
both synchronous and streaming (SSE) responses.

Requests are dispatched through the :class:`~routerbot.router.router.Router`
(``proxy/completion_helper.get_router``), which applies load balancing,
retries, cooldown, and configured fallback models.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, StreamingResponse

from routerbot.core.exceptions import BadRequestError
from routerbot.core.types import CompletionRequest, CompletionResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from routerbot.core.types import CompletionResponseChunk

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat Completions"])


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------


async def _dispatch_request_end(
    callback_manager: Any,
    *,
    request_id: str,
    model: str,
    response: CompletionResponse,
    user_id: str | None,
    team_id: str | None,
    key_id: str | None,
) -> None:
    """Background task: dispatch REQUEST_END with spend/usage data."""
    from routerbot.core.cost import calculate_cost
    from routerbot.observability.callbacks import CallbackEvent, RequestEndData

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

    if callback_manager is None:
        return

    cost = calculate_cost(model, response.usage) if response.usage else 0.0
    await callback_manager.dispatch(
        CallbackEvent.REQUEST_END,
        RequestEndData(
            request_id=request_id,
            model=model,
            provider=model.split("/", 1)[0] if "/" in model else "",
            tokens_prompt=response.usage.prompt_tokens if response.usage else 0,
            tokens_completion=response.usage.completion_tokens if response.usage else 0,
            cost=cost,
            user_id=user_id,
            team_id=team_id,
            key_id=key_id,
        ),
    )


async def _stream_sse(
    generator: AsyncIterator[CompletionResponseChunk],
) -> AsyncIterator[str]:
    """Convert a chunk iterator to SSE-formatted strings."""
    async for chunk in generator:
        yield f"data: {chunk.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"


def _auth_ids(raw_request: Request) -> tuple[str | None, str | None, str | None]:
    """Return ``(user_id, team_id, key_id)`` from the resolved auth context."""
    ctx = getattr(raw_request.state, "auth_context", None)
    if ctx is None:
        return None, None, None
    return ctx.user_id, ctx.team_id, ctx.key_id


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
    from routerbot.proxy.completion_helper import get_router

    request_id = getattr(raw_request.state, "request_id", None) or "unknown"
    state = getattr(raw_request.app.state, "routerbot", None)
    user_id, team_id, key_id = _auth_ids(raw_request)

    # Apply semantic routing if configured
    effective_model = body.model
    semantic_router = getattr(state, "semantic_router", None) if state else None
    if semantic_router and semantic_router.enabled:
        effective_model = await semantic_router.route(
            model=body.model,
            messages=[m.model_dump() for m in body.messages] if body.messages else None,
            session_key=key_id or user_id,
        )
        if effective_model != body.model:
            logger.info(
                "Semantic routing: %s → %s (request=%s)",
                body.model,
                effective_model,
                request_id,
            )
            body = body.model_copy(update={"model": effective_model})

    # ── Request transformation pipeline (pre-request) ──
    transform_pipeline = getattr(state, "transform_pipeline", None) if state else None
    if transform_pipeline and transform_pipeline.enabled:
        from routerbot.core.transform.models import TransformContext

        tf_context = TransformContext(
            model=effective_model,
            request_id=request_id,
            team_id=team_id,
            key_id=key_id,
            user_id=user_id,
        )
        request_data = body.model_dump(exclude_none=True)
        await transform_pipeline.run_pre_request(request_data, tf_context)
        body = CompletionRequest(**request_data)

    # ── Guardrails (request) ──
    guardrail_manager = getattr(state, "guardrail_manager", None) if state else None
    if guardrail_manager is not None:
        from routerbot.proxy.guardrails.base import GuardrailContext

        guardrail_ctx = GuardrailContext(
            request_id=request_id,
            user_id=user_id,
            team_id=team_id,
            key_id=key_id,
            model=effective_model,
        )
        request_result = await guardrail_manager.run_request_guardrails(
            [m.model_dump() for m in body.messages],
            guardrail_ctx,
        )
        if request_result.blocked:
            reason = request_result.blocking_result.reason if request_result.blocking_result else None
            raise BadRequestError(reason or "Request blocked by guardrail")
        if request_result.modified and request_result.modified_messages is not None:
            # Rebuild (not model_copy) — guardrails return plain message dicts,
            # and CompletionRequest.messages needs real Message instances.
            body = CompletionRequest(
                **{**body.model_dump(exclude={"messages"}), "messages": request_result.modified_messages}
            )

    if body.stream:
        # --- Streaming response ---
        llm_router = get_router(state)
        generator = llm_router.chat_completion_stream(body, request_id=request_id)

        return StreamingResponse(
            _stream_sse(generator),
            media_type="text/event-stream",
            headers={
                "X-Request-ID": request_id,
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    # ── Response cache lookup ──
    # Tenant-scoped (key, falling back to team) so two callers never share a
    # cached response for the same prompt. Guardrails above still ran on
    # this request even on a cache hit; response guardrails don't need to
    # re-run since the cached content already passed them when it was stored.
    tenant = key_id or team_id
    cache_manager = getattr(state, "cache_manager", None) if state else None
    cache_extra = {
        k: v
        for k, v in {
            "seed": getattr(body, "seed", None),
            "frequency_penalty": getattr(body, "frequency_penalty", None),
            "presence_penalty": getattr(body, "presence_penalty", None),
            "n": getattr(body, "n", None),
        }.items()
        if v is not None
    }
    cache_hit = False
    if cache_manager is not None:
        cached_entry = await cache_manager.lookup(
            model=body.model,
            messages=[m.model_dump() for m in body.messages],
            temperature=body.temperature,
            top_p=body.top_p,
            max_tokens=body.max_tokens,
            tools=[t.model_dump() for t in body.tools] if body.tools else None,
            stream=False,
            tenant=tenant,
            extra=cache_extra or None,
        )
        if cached_entry is not None:
            response = CompletionResponse.model_validate(cached_entry.response_data)
            cache_hit = True

    if not cache_hit:
        llm_router = get_router(state)
        response = await llm_router.chat_completion(body, request_id=request_id)

    callback_manager = getattr(state, "callback_manager", None) if state else None
    background_tasks.add_task(
        _dispatch_request_end,
        callback_manager,
        request_id=request_id,
        model=body.model,
        response=response,
        user_id=user_id,
        team_id=team_id,
        key_id=key_id,
    )

    # ── Guardrails (response) ──
    # Streaming responses aren't checked: by the time a violation could be
    # detected, the content has already been sent to the client. Cache hits
    # skip this too — the cached content already passed it when stored.
    if not cache_hit and guardrail_manager is not None and response.choices:
        response_text = response.choices[0].message.content or ""
        response_result = await guardrail_manager.run_response_guardrails(response_text, guardrail_ctx)
        if response_result.blocked:
            reason = response_result.blocking_result.reason if response_result.blocking_result else None
            raise BadRequestError(reason or "Response blocked by guardrail")
        if response_result.modified and response_result.modified_messages:
            response.choices[0].message.content = response_result.modified_messages[0]["content"]

    # ── Response cache store ──
    if not cache_hit and cache_manager is not None:
        await cache_manager.store(
            model=body.model,
            messages=[m.model_dump() for m in body.messages],
            response_data=response.model_dump(),
            temperature=body.temperature,
            top_p=body.top_p,
            max_tokens=body.max_tokens,
            tools=[t.model_dump() for t in body.tools] if body.tools else None,
            tenant=tenant,
            extra=cache_extra or None,
        )

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
