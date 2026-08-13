"""Embeddings route — POST /v1/embeddings.

Implements the OpenAI-compatible embeddings API. Requests are dispatched
through the :class:`~routerbot.router.router.Router`
(``proxy/completion_helper.get_router``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from routerbot.core.types import EmbeddingRequest  # noqa: TC001

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Embeddings"])


@router.post("/embeddings", summary="Create embeddings")
async def create_embeddings(
    body: EmbeddingRequest,
    raw_request: Request,
) -> JSONResponse:
    """Generate embeddings for the provided input.

    Returns an OpenAI-compatible embedding response.
    """
    from routerbot.proxy.completion_helper import get_router

    request_id = getattr(raw_request.state, "request_id", None) or "unknown"
    state = getattr(raw_request.app.state, "routerbot", None)

    llm_router = get_router(state)
    response = await llm_router.embeddings(body, request_id=request_id)

    return JSONResponse(
        content=response.model_dump(),
        headers={"X-Request-ID": request_id},
    )
