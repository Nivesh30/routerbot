"""Structured request/response logging middleware.

Logs a JSON record for every HTTP request including:
- Method, path, status code
- Request ID
- Response time in ms
- Model name (extracted from request body for LLM routes)

Usage::

    from routerbot.proxy.middleware.logging_mw import RequestLoggingMiddleware

    app.add_middleware(RequestLoggingMiddleware)
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request  # noqa: TC002
from starlette.responses import Response  # noqa: TC002

if TYPE_CHECKING:
    from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Paths that should not be logged (noisy / health checks)
_SKIP_PATHS = frozenset({"/health", "/health/liveness", "/health/readiness", "/robots.txt"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log structured JSON records for every HTTP request.

    Each log record includes:

    - ``method`` — HTTP method (GET, POST, …)
    - ``path`` — URL path
    - ``status_code`` — response status code
    - ``request_id`` — value of the ``X-Request-ID`` header (if present)
    - ``latency_ms`` — total server-side response time in milliseconds
    - ``model`` — LLM model name extracted from JSON body (best-effort)

    Parameters
    ----------
    app:
        The ASGI application to wrap.
    skip_paths:
        Set of paths to skip logging for (defaults to health + robots).
    log_level:
        Python logging level to emit records at (defaults to ``logging.INFO``).
    """

    def __init__(
        self,
        app: ASGIApp,
        skip_paths: frozenset[str] | None = None,
        log_level: int = logging.INFO,
    ) -> None:
        super().__init__(app)
        self._skip_paths = skip_paths if skip_paths is not None else _SKIP_PATHS
        self._log_level = log_level

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if request.url.path in self._skip_paths:
            skip_response: Response = await call_next(request)
            return skip_response

        start = time.perf_counter()

        # Extract model name from JSON body (best-effort, do NOT fail on errors)
        # NOTE: Do NOT replace request._receive after reading — Starlette's
        # _CachedRequest already caches the body and re-serves it to the
        # next middleware via wrapped_receive.  Manual re-injection breaks
        # streaming responses.
        model: str | None = None
        try:
            body_bytes = await request.body()
            if body_bytes and request.headers.get("content-type", "").startswith("application/json"):
                data = json.loads(body_bytes)
                model = data.get("model")
        except Exception:  # noqa: S110
            pass  # never let logging break the request

        response: Response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start) * 1000
        request_id = getattr(getattr(request, "state", None), "request_id", None)

        record: dict[str, Any] = {
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "latency_ms": round(elapsed_ms, 1),
        }
        if request_id:
            record["request_id"] = request_id
        if model:
            record["model"] = model

        logger.log(self._log_level, "http_request", extra={"http": record})

        return response
