"""Prometheus ``/metrics`` endpoint.

Exposes all Prometheus metrics in text format for scraping.
"""

from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import Response

from routerbot.observability.prometheus import metrics_response

router = APIRouter(tags=["Observability"])


@router.get("/metrics", response_model=None)
async def prometheus_metrics() -> Response:
    """Return Prometheus-format metrics for scraping."""
    body = metrics_response()
    return Response(
        content=body,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
