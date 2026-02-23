"""Batch operations routes — /v1/batches.

Stub implementation for OpenAI-compatible batch API.
Batches will be persisted to the database in Stage 4+.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["Batches"])

# In-memory store for now (will be replaced by DB in Stage 4)
_batches: dict[str, dict[str, object]] = {}


def _batch_object(batch_id: str, status: str = "validating") -> dict[str, object]:
    """Build a batch status object."""
    return {
        "id": batch_id,
        "object": "batch",
        "endpoint": "/v1/chat/completions",
        "errors": None,
        "input_file_id": None,
        "completion_window": "24h",
        "status": status,
        "output_file_id": None,
        "error_file_id": None,
        "created_at": int(time.time()),
        "in_progress_at": None,
        "expires_at": None,
        "finalizing_at": None,
        "completed_at": None,
        "failed_at": None,
        "expired_at": None,
        "cancelling_at": None,
        "cancelled_at": None,
        "request_counts": {"total": 0, "completed": 0, "failed": 0},
        "metadata": None,
    }


@router.post("/batches", summary="Create a batch")
async def create_batch(
    raw_request: Request,
) -> JSONResponse:
    """Create a new batch job.

    Note: Full batch processing will be implemented in Stage 4 with
    database persistence. This stub acknowledges the request.
    """
    request_id = getattr(raw_request.state, "request_id", None) or "unknown"

    batch_id = f"batch_{uuid.uuid4().hex[:24]}"
    batch = _batch_object(batch_id)
    _batches[batch_id] = batch

    return JSONResponse(
        status_code=200,
        content=batch,
        headers={"X-Request-ID": request_id},
    )


@router.get("/batches", summary="List batches")
async def list_batches(
    raw_request: Request,
) -> JSONResponse:
    """List all batch jobs."""
    request_id = getattr(raw_request.state, "request_id", None) or "unknown"

    return JSONResponse(
        content={
            "object": "list",
            "data": list(_batches.values()),
            "first_id": next(iter(_batches), None),
            "last_id": next(reversed(_batches), None) if _batches else None,
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

    batch = _batches.get(batch_id)
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
        content=batch,
        headers={"X-Request-ID": request_id},
    )


@router.post("/batches/{batch_id}/cancel", summary="Cancel a batch")
async def cancel_batch(
    batch_id: str,
    raw_request: Request,
) -> JSONResponse:
    """Cancel a pending or in-progress batch job."""
    request_id = getattr(raw_request.state, "request_id", None) or "unknown"

    batch = _batches.get(batch_id)
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

    batch["status"] = "cancelling"
    batch["cancelling_at"] = int(time.time())
    _batches[batch_id] = batch

    return JSONResponse(
        content=batch,
        headers={"X-Request-ID": request_id},
    )
