"""Image generation routes — POST /v1/images/generations.

Implements the OpenAI-compatible image generation API. Requests are
dispatched through the :class:`~routerbot.router.router.Router`
(``proxy/completion_helper.get_router``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from routerbot.core.types import ImageRequest  # noqa: TC001

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Images"])


@router.post("/images/generations", summary="Generate images")
async def generate_images(
    body: ImageRequest,
    raw_request: Request,
) -> JSONResponse:
    """Generate images from a text prompt.

    Returns an OpenAI-compatible image generation response.
    """
    from routerbot.proxy.completion_helper import get_router

    request_id = getattr(raw_request.state, "request_id", None) or "unknown"
    state = getattr(raw_request.app.state, "routerbot", None)

    llm_router = get_router(state)
    response = await llm_router.image_generation(body, request_id=request_id)

    return JSONResponse(
        content=response.model_dump(),
        headers={"X-Request-ID": request_id},
    )
