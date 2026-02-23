"""Model listing endpoints — OpenAI /v1/models compatibility.

Endpoints:
    GET  /v1/models           — list all configured models
    GET  /v1/models/{model}   — retrieve a single model's details
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from routerbot.core.exceptions import ModelNotFoundError

router = APIRouter(tags=["Models"])


def _model_object(model_name: str, provider: str = "routerbot") -> dict[str, object]:
    """Build an OpenAI-compatible model object."""
    return {
        "id": model_name,
        "object": "model",
        "created": int(time.time()),
        "owned_by": provider,
    }


@router.get("/models", summary="List available models")
async def list_models(request: Request) -> JSONResponse:
    """Return all models configured in the RouterBot model_list.

    Response matches the OpenAI ``GET /v1/models`` format.
    """
    state = getattr(request.app.state, "routerbot", None)
    config = state.config if state else None

    if config is None or not config.model_list:
        # Return an empty list rather than an error
        return JSONResponse(
            content={
                "object": "list",
                "data": [],
            }
        )

    models = [
        _model_object(
            entry.model_name,
            provider=entry.provider_params.model.split("/")[0] if "/" in entry.provider_params.model else "routerbot",
        )
        for entry in config.model_list
    ]

    return JSONResponse(
        content={
            "object": "list",
            "data": models,
        }
    )


@router.get("/models/{model_id:path}", summary="Retrieve a specific model")
async def get_model(model_id: str, request: Request) -> JSONResponse:
    """Return details for a specific model by ID.

    Raises 404 (ModelNotFoundError) if the model is not configured.
    """
    state = getattr(request.app.state, "routerbot", None)
    config = state.config if state else None

    if config and config.model_list:
        for entry in config.model_list:
            if entry.model_name == model_id:
                provider = (
                    entry.provider_params.model.split("/")[0] if "/" in entry.provider_params.model else "routerbot"
                )
                return JSONResponse(content=_model_object(model_id, provider))

    raise ModelNotFoundError(model_id)
