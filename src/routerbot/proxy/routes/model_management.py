"""Model management admin routes.

Endpoints for adding, updating, deleting, and testing model
configurations at runtime.  All endpoints require the master key.

Endpoints:
    GET    /model/list            — List all models with extended info
    GET    /model/info            — Get detailed info for a single model
    POST   /model/new             — Add a new model to the config
    POST   /model/update          — Update an existing model's settings
    POST   /model/delete          — Remove a model from the config
    POST   /model/test_connection — Test connectivity to a model's provider
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from routerbot.core.config_models import ModelEntry, ModelInfo, ModelParams

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/model", tags=["Model Management"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ModelNewRequest(BaseModel):
    """Body for ``POST /model/new``."""

    model_name: str = Field(..., description="Virtual model name clients use")
    model: str = Field(..., description="Provider/model format, e.g. 'openai/gpt-4o'")
    api_key: str | None = Field(default=None, description="API key or os.environ/VAR_NAME")
    api_base: str | None = Field(default=None, description="Custom API base URL")
    api_version: str | None = Field(default=None, description="API version (e.g. Azure)")
    max_tokens: int | None = Field(default=None, gt=0, description="Default max tokens")
    rpm: int | None = Field(default=None, gt=0, description="Requests per minute limit")
    tpm: int | None = Field(default=None, gt=0, description="Tokens per minute limit")
    timeout: int | None = Field(default=None, gt=0, description="Request timeout in seconds")
    input_cost_per_token: float | None = Field(default=None, description="USD per input token")
    output_cost_per_token: float | None = Field(default=None, description="USD per output token")
    supports_streaming: bool = Field(default=True, description="Supports streaming")
    supports_function_calling: bool = Field(default=False, description="Supports tools")
    supports_vision: bool = Field(default=False, description="Supports image input")
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)


class ModelUpdateRequest(BaseModel):
    """Body for ``POST /model/update``."""

    model_name: str = Field(..., description="Virtual model name to update")
    model: str | None = Field(default=None, description="New provider/model string")
    api_key: str | None = Field(default=None, description="New API key")
    api_base: str | None = Field(default=None, description="New API base URL")
    api_version: str | None = Field(default=None, description="New API version")
    max_tokens: int | None = Field(default=None, gt=0, description="New max tokens")
    rpm: int | None = Field(default=None, gt=0, description="New RPM limit")
    tpm: int | None = Field(default=None, gt=0, description="New TPM limit")
    timeout: int | None = Field(default=None, gt=0, description="New timeout in seconds")
    input_cost_per_token: float | None = Field(default=None)
    output_cost_per_token: float | None = Field(default=None)
    supports_streaming: bool | None = Field(default=None)
    supports_function_calling: bool | None = Field(default=None)
    supports_vision: bool | None = Field(default=None)


class ModelDeleteRequest(BaseModel):
    """Body for ``POST /model/delete``."""

    model_name: str = Field(..., description="Virtual model name to remove")


class ModelTestRequest(BaseModel):
    """Body for ``POST /model/test_connection``."""

    model_name: str = Field(..., description="Virtual model name to test")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_master_key(request: Request) -> None:
    """Assert that the caller provided a valid master key."""
    state = getattr(request.app.state, "routerbot", None)
    config = getattr(state, "config", None) if state else None
    master_key = ""
    if config and config.general_settings:
        master_key = config.general_settings.master_key or ""

    if not master_key:
        # No master key configured — allow all admin operations
        return

    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    x_master = request.headers.get("X-Master-Key", "")

    if token != master_key and x_master != master_key:
        raise HTTPException(status_code=401, detail="Invalid or missing master key")


def _model_entry_to_dict(entry: ModelEntry) -> dict[str, Any]:
    """Serialize a ModelEntry to a dict, masking the API key."""
    params = entry.provider_params
    provider = params.model.split("/")[0] if "/" in params.model else "routerbot"

    result: dict[str, Any] = {
        "model_name": entry.model_name,
        "model": params.model,
        "provider": provider,
        "api_base": params.api_base,
        "api_key_set": params.api_key is not None,
        "max_tokens": params.max_tokens,
        "rpm": params.rpm,
        "tpm": params.tpm,
        "timeout": params.timeout,
        "extra_headers": dict.fromkeys(params.extra_headers, "***") if params.extra_headers else {},
        "extra_body": params.extra_body,
        "created": int(time.time()),
    }

    if entry.model_info:
        result["model_info"] = {
            "input_cost_per_token": entry.model_info.input_cost_per_token,
            "output_cost_per_token": entry.model_info.output_cost_per_token,
            "supports_streaming": entry.model_info.supports_streaming,
            "supports_function_calling": entry.model_info.supports_function_calling,
            "supports_vision": entry.model_info.supports_vision,
            "max_input_tokens": entry.model_info.max_input_tokens,
            "max_output_tokens": entry.model_info.max_output_tokens,
        }

    return result


def _find_model_index(config: Any, model_name: str) -> int | None:
    """Find the index of a model in the config's model_list."""
    if not config or not config.model_list:
        return None
    for i, entry in enumerate(config.model_list):
        if entry.model_name == model_name:
            return i
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/list", summary="List all models with extended info")
async def list_models(request: Request) -> JSONResponse:
    """Return all models with admin-level detail (no API keys exposed)."""
    _require_master_key(request)

    state = getattr(request.app.state, "routerbot", None)
    config = getattr(state, "config", None) if state else None

    if not config or not config.model_list:
        return JSONResponse(content={"data": [], "total": 0})

    models = [_model_entry_to_dict(entry) for entry in config.model_list]
    return JSONResponse(content={"data": models, "total": len(models)})


@router.get("/info", summary="Get model details")
async def get_model_info(request: Request, model_name: str) -> JSONResponse:
    """Return detail for a single model by name."""
    _require_master_key(request)

    state = getattr(request.app.state, "routerbot", None)
    config = getattr(state, "config", None) if state else None

    idx = _find_model_index(config, model_name)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not found")

    return JSONResponse(content=_model_entry_to_dict(config.model_list[idx]))


@router.post("/new", summary="Add a new model")
async def add_model(body: ModelNewRequest, request: Request) -> JSONResponse:
    """Add a new model deployment to the running config.

    The model is immediately available for routing.
    """
    _require_master_key(request)

    state = getattr(request.app.state, "routerbot", None)
    config = getattr(state, "config", None) if state else None
    if not config:
        raise HTTPException(status_code=503, detail="Configuration not loaded")

    # Check for duplicate
    if _find_model_index(config, body.model_name) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Model '{body.model_name}' already exists",
        )

    # Build ModelParams
    params = ModelParams(
        model=body.model,
        api_key=body.api_key,
        api_base=body.api_base,
        api_version=body.api_version,
        max_tokens=body.max_tokens,
        rpm=body.rpm,
        tpm=body.tpm,
        timeout=body.timeout,
        extra_headers=body.extra_headers,
        extra_body=body.extra_body,
    )

    # Build ModelInfo if cost/capability fields provided
    info_fields: dict[str, Any] = {}
    if body.input_cost_per_token is not None:
        info_fields["input_cost_per_token"] = body.input_cost_per_token
    if body.output_cost_per_token is not None:
        info_fields["output_cost_per_token"] = body.output_cost_per_token
    info_fields["supports_streaming"] = body.supports_streaming
    info_fields["supports_function_calling"] = body.supports_function_calling
    info_fields["supports_vision"] = body.supports_vision

    model_info = ModelInfo(**info_fields) if info_fields else None

    entry = ModelEntry(
        model_name=body.model_name,
        provider_params=params,
        model_info=model_info,
    )

    config.model_list.append(entry)

    logger.info("Added model '%s' (%s)", body.model_name, body.model)

    return JSONResponse(
        status_code=201,
        content={
            "status": "created",
            "model": _model_entry_to_dict(entry),
        },
    )


@router.post("/update", summary="Update model settings")
async def update_model(body: ModelUpdateRequest, request: Request) -> JSONResponse:
    """Update an existing model's configuration at runtime."""
    _require_master_key(request)

    state = getattr(request.app.state, "routerbot", None)
    config = getattr(state, "config", None) if state else None
    if not config:
        raise HTTPException(status_code=503, detail="Configuration not loaded")

    idx = _find_model_index(config, body.model_name)
    if idx is None:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{body.model_name}' not found",
        )

    entry = config.model_list[idx]
    params = entry.provider_params

    # Update provider params
    if body.model is not None:
        params.model = body.model
    if body.api_key is not None:
        params.api_key = body.api_key
    if body.api_base is not None:
        params.api_base = body.api_base
    if body.api_version is not None:
        params.api_version = body.api_version
    if body.max_tokens is not None:
        params.max_tokens = body.max_tokens
    if body.rpm is not None:
        params.rpm = body.rpm
    if body.tpm is not None:
        params.tpm = body.tpm
    if body.timeout is not None:
        params.timeout = body.timeout

    # Update model info
    if any(
        v is not None
        for v in [
            body.input_cost_per_token,
            body.output_cost_per_token,
            body.supports_streaming,
            body.supports_function_calling,
            body.supports_vision,
        ]
    ):
        if entry.model_info is None:
            entry.model_info = ModelInfo()
        if body.input_cost_per_token is not None:
            entry.model_info.input_cost_per_token = body.input_cost_per_token
        if body.output_cost_per_token is not None:
            entry.model_info.output_cost_per_token = body.output_cost_per_token
        if body.supports_streaming is not None:
            entry.model_info.supports_streaming = body.supports_streaming
        if body.supports_function_calling is not None:
            entry.model_info.supports_function_calling = body.supports_function_calling
        if body.supports_vision is not None:
            entry.model_info.supports_vision = body.supports_vision

    logger.info("Updated model '%s'", body.model_name)

    return JSONResponse(
        content={
            "status": "updated",
            "model": _model_entry_to_dict(entry),
        }
    )


@router.post("/delete", summary="Remove a model")
async def delete_model(body: ModelDeleteRequest, request: Request) -> JSONResponse:
    """Remove a model from the running config.

    Requests in-flight may still complete, but no new requests will
    be routed to this model.
    """
    _require_master_key(request)

    state = getattr(request.app.state, "routerbot", None)
    config = getattr(state, "config", None) if state else None
    if not config:
        raise HTTPException(status_code=503, detail="Configuration not loaded")

    idx = _find_model_index(config, body.model_name)
    if idx is None:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{body.model_name}' not found",
        )

    removed = config.model_list.pop(idx)
    logger.info("Deleted model '%s'", removed.model_name)

    return JSONResponse(
        content={
            "status": "deleted",
            "model_name": body.model_name,
        }
    )


@router.post("/test_connection", summary="Test model connectivity")
async def test_connection(body: ModelTestRequest, request: Request) -> JSONResponse:
    """Send a minimal request to verify the model's provider is reachable.

    Returns a success/failure status with latency information.
    """
    _require_master_key(request)

    state = getattr(request.app.state, "routerbot", None)
    config = getattr(state, "config", None) if state else None
    if not config:
        raise HTTPException(status_code=503, detail="Configuration not loaded")

    idx = _find_model_index(config, body.model_name)
    if idx is None:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{body.model_name}' not found",
        )

    entry = config.model_list[idx]
    provider_model = entry.provider_params.model

    # Try using the router to send a minimal request
    router_instance = getattr(state, "router", None)
    if router_instance is None:
        return JSONResponse(
            content={
                "status": "error",
                "model_name": body.model_name,
                "message": "Router not initialized",
                "latency_ms": 0,
            }
        )

    start = time.perf_counter()
    try:
        # Attempt a lightweight chat completion
        await router_instance.completion(
            model=entry.model_name,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        return JSONResponse(
            content={
                "status": "success",
                "model_name": body.model_name,
                "provider_model": provider_model,
                "latency_ms": round(latency_ms, 1),
                "message": "Connection successful",
            }
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return JSONResponse(
            status_code=200,
            content={
                "status": "error",
                "model_name": body.model_name,
                "provider_model": provider_model,
                "latency_ms": round(latency_ms, 1),
                "message": str(exc),
            },
        )
