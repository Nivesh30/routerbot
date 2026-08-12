"""Batch operations routes — /v1/batches.

Delegates to the real ``BatchManager`` (``state.batch_manager``, wired up in
``proxy/app.py`` with a handler that calls actual providers — see
``proxy/completion_helper.py``) instead of maintaining its own in-memory
store. Batch processing must be enabled via ``batch.enabled: true`` in
config for these routes to work; otherwise they return 503.

Note: unlike OpenAI's batch API, which takes an uploaded JSONL file
(``input_file_id``), this implementation accepts the list of requests
inline in the request body — RouterBot has no file-upload/storage
subsystem yet. Everything else (status polling, cancellation, result
shape) follows the OpenAI batch object format.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from routerbot.core.batch.models import BatchRequest  # noqa: TC001 - needed at runtime for pydantic model resolution

if TYPE_CHECKING:
    from routerbot.core.batch.batch_manager import BatchManager
    from routerbot.core.batch.models import Batch

router = APIRouter(tags=["Batches"])


class BatchCreateRequest(BaseModel):
    """Request body for ``POST /v1/batches``.

    Diverges from OpenAI's file-based API: requests are supplied inline
    rather than via an uploaded file id.
    """

    requests: list[BatchRequest]
    metadata: dict[str, str] | None = None


def _get_batch_manager(request: Request) -> BatchManager:
    """Retrieve the BatchManager from app state, or 503 if not configured."""
    state = getattr(request.app.state, "routerbot", None)
    mgr: BatchManager | None = getattr(state, "batch_manager", None) if state else None
    if mgr is None:
        raise HTTPException(
            status_code=503,
            detail="Batch processing is not enabled (set batch.enabled: true in config).",
        )
    return mgr


def _epoch(dt: Any) -> int | None:
    """Convert a datetime to a unix epoch int, or None."""
    if dt is None:
        return None
    return int(dt.timestamp())


def _batch_to_response(batch: Batch) -> dict[str, Any]:
    """Map an internal ``Batch`` to an OpenAI-compatible batch object."""
    status = batch.status.value
    return {
        "id": batch.batch_id,
        "object": "batch",
        "endpoint": "/v1/chat/completions",
        "errors": {"data": [{"message": e} for e in batch.errors]} if batch.errors else None,
        "input_file_id": None,
        "completion_window": "24h",
        "status": status,
        "output_file_id": None,
        "error_file_id": None,
        "created_at": _epoch(batch.created_at) or int(time.time()),
        "in_progress_at": _epoch(batch.started_at),
        "expires_at": None,
        "finalizing_at": None,
        "completed_at": _epoch(batch.completed_at) if status == "completed" else None,
        "failed_at": _epoch(batch.completed_at) if status == "failed" else None,
        "expired_at": _epoch(batch.completed_at) if status == "expired" else None,
        "cancelling_at": None,
        "cancelled_at": _epoch(batch.completed_at) if status == "cancelled" else None,
        "request_counts": {
            "total": batch.total_requests,
            "completed": batch.completed_requests,
            "failed": batch.failed_requests,
        },
        "metadata": batch.metadata or None,
        # Extension (not part of the OpenAI schema): results are returned
        # inline since there's no file-storage subsystem to write them to.
        "results": [r.model_dump() for r in batch.results] if batch.results else None,
    }


@router.post("/batches", summary="Create a batch")
async def create_batch(
    body: BatchCreateRequest,
    raw_request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Create a new batch job and start executing it in the background."""
    request_id = getattr(raw_request.state, "request_id", None) or "unknown"
    manager = _get_batch_manager(raw_request)

    try:
        batch = await manager.create_batch(body.requests, metadata=body.metadata)
    except Exception as exc:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": str(exc),
                    "type": "invalid_request_error",
                    "param": "requests",
                    "code": "batch_validation_error",
                }
            },
            headers={"X-Request-ID": request_id},
        )

    background_tasks.add_task(manager.execute_batch, batch.batch_id)

    return JSONResponse(
        status_code=200,
        content=_batch_to_response(batch),
        headers={"X-Request-ID": request_id},
    )


@router.get("/batches", summary="List batches")
async def list_batches(
    raw_request: Request,
) -> JSONResponse:
    """List all batch jobs."""
    request_id = getattr(raw_request.state, "request_id", None) or "unknown"
    manager = _get_batch_manager(raw_request)

    batches = [_batch_to_response(b) for b in manager.list_batches()]

    return JSONResponse(
        content={
            "object": "list",
            "data": batches,
            "first_id": batches[0]["id"] if batches else None,
            "last_id": batches[-1]["id"] if batches else None,
            "has_more": False,
        },
        headers={"X-Request-ID": request_id},
    )


@router.get("/batches/{batch_id}", summary="Get batch status")
async def get_batch(
    batch_id: str,
    raw_request: Request,
) -> JSONResponse:
    """Get the status of a specific batch job."""
    request_id = getattr(raw_request.state, "request_id", None) or "unknown"
    manager = _get_batch_manager(raw_request)

    batch = manager.get_batch(batch_id)
    if batch is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "message": f"Batch '{batch_id}' not found.",
                    "type": "invalid_request_error",
                    "param": "batch_id",
                    "code": "batch_not_found",
                }
            },
            headers={"X-Request-ID": request_id},
        )

    return JSONResponse(
        content=_batch_to_response(batch),
        headers={"X-Request-ID": request_id},
    )


@router.post("/batches/{batch_id}/cancel", summary="Cancel a batch")
async def cancel_batch(
    batch_id: str,
    raw_request: Request,
) -> JSONResponse:
    """Cancel a pending or in-progress batch job."""
    request_id = getattr(raw_request.state, "request_id", None) or "unknown"
    manager = _get_batch_manager(raw_request)

    batch = manager.get_batch(batch_id)
    if batch is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "message": f"Batch '{batch_id}' not found.",
                    "type": "invalid_request_error",
                    "param": "batch_id",
                    "code": "batch_not_found",
                }
            },
            headers={"X-Request-ID": request_id},
        )

    manager.cancel_batch(batch_id)
    updated = manager.get_batch(batch_id)
    assert updated is not None  # just fetched above

    return JSONResponse(
        content=_batch_to_response(updated),
        headers={"X-Request-ID": request_id},
    )
