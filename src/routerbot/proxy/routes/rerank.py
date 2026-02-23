"""Rerank route — POST /v1/rerank.

Implements a Cohere/Jina-compatible reranking API.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from routerbot.core.exceptions import BadRequestError, ModelNotFoundError
from routerbot.core.types import RerankRequest  # noqa: TC001

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Rerank"])


async def _get_provider_for_model(request: Request, model_name: str) -> Any:
    """Resolve a provider for the given model name."""
    state = getattr(request.app.state, "routerbot", None)
    config = state.config if state else None

    if config is None:
        raise ModelNotFoundError(model_name)

    entry = next((m for m in config.model_list if m.model_name == model_name), None)
    if entry is None:
        raise ModelNotFoundError(model_name)

    provider_model = entry.provider_params.model
    if "/" not in provider_model:
        raise BadRequestError(f"Invalid provider/model format: {provider_model!r}")

    provider_name, _ = provider_model.split("/", 1)

    from routerbot.providers.registry import get_provider_class

    provider_cls = get_provider_class(provider_name)

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


@router.post("/rerank", summary="Rerank documents")
async def rerank(
    body: RerankRequest,
    raw_request: Request,
) -> JSONResponse:
    """Rerank a list of documents based on relevance to a query.

    Returns a Cohere/Jina-compatible rerank response.
    """
    request_id = getattr(raw_request.state, "request_id", None) or "unknown"

    provider = await _get_provider_for_model(raw_request, body.model)

    response = await provider.rerank(body)

    return JSONResponse(
        content=response.model_dump(),
        headers={"X-Request-ID": request_id},
    )
