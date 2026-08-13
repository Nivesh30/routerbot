"""Rerank route — POST /v1/rerank.

Implements a Cohere/Jina-compatible reranking API. Requests are dispatched
through the :class:`~routerbot.router.router.Router`
(``proxy/completion_helper.get_router``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from routerbot.core.types import RerankRequest  # noqa: TC001

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Rerank"])


@router.post("/rerank", summary="Rerank documents")
async def rerank(
    body: RerankRequest,
    raw_request: Request,
) -> JSONResponse:
    """Rerank a list of documents based on relevance to a query.

    Returns a Cohere/Jina-compatible rerank response.
    """
    from routerbot.proxy.completion_helper import get_router

    request_id = getattr(raw_request.state, "request_id", None) or "unknown"
    state = getattr(raw_request.app.state, "routerbot", None)

    llm_router = get_router(state)
    response = await llm_router.rerank(body, request_id=request_id)

    return JSONResponse(
        content=response.model_dump(),
        headers={"X-Request-ID": request_id},
    )
