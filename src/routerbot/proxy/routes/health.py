"""Health check endpoints.

Provides liveness and readiness probes for Kubernetes/Docker and a simple
status endpoint for human operators.

Endpoints:
    GET  /health              — basic liveness (always 200 if server is up)
    GET  /health/liveness     — Kubernetes liveness probe
    GET  /health/readiness    — Kubernetes readiness probe (checks providers)
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["Health"])

_START_TIME = time.time()


@router.get("/health", summary="Basic health check")
async def health(request: Request) -> JSONResponse:
    """Return a simple healthy status.

    Always returns 200 as long as the server process is running.
    Used as a basic uptime check.
    """
    state = getattr(request.app.state, "routerbot", None)
    ready = state.is_ready() if state else False

    return JSONResponse(
        content={
            "status": "healthy" if ready else "starting",
            "uptime_seconds": round(time.time() - _START_TIME, 1),
            "version": "0.1.0",
        }
    )


@router.get("/health/liveness", summary="Kubernetes liveness probe")
async def liveness() -> JSONResponse:
    """Liveness probe — returns 200 as long as the process is alive."""
    return JSONResponse(content={"status": "alive"})


@router.get("/health/readiness", summary="Kubernetes readiness probe")
async def readiness(request: Request) -> JSONResponse:
    """Readiness probe — returns 200 when the app is ready to serve traffic.

    Returns 503 during startup (config not yet loaded).
    """
    state = getattr(request.app.state, "routerbot", None)
    if state is None or not state.is_ready():
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "reason": "Application still initializing"},
        )
    return JSONResponse(content={"status": "ready"})
