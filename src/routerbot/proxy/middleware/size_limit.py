"""Request body size-limit middleware.

Rejects incoming requests whose body size (reported via ``Content-Length``
header or streamed body length) exceeds a configurable threshold.

Usage::

    from routerbot.proxy.middleware.size_limit import RequestSizeLimitMiddleware

    app.add_middleware(
        RequestSizeLimitMiddleware,
        max_request_body_mb=100.0,
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request  # noqa: TC002
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

_MB = 1024 * 1024


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose body exceeds *max_request_body_mb* megabytes.

    The check is performed in two stages:

    1. **Fast path** — if the ``Content-Length`` header is present and
       exceeds the limit, the request is rejected immediately without
       buffering the body.
    2. **Streaming path** — if ``Content-Length`` is absent (e.g.,
       chunked transfer encoding), the body bytes are accumulated and
       checked before the request is forwarded to the application.

    Parameters
    ----------
    app:
        The ASGI application to wrap.
    max_request_body_mb:
        Maximum allowed request body in megabytes (default 100 MB).
    """

    def __init__(self, app: ASGIApp, max_request_body_mb: float = 100.0) -> None:
        super().__init__(app)
        self._max_bytes = int(max_request_body_mb * _MB)

    async def dispatch(self, request: Request, call_next: Any) -> Response:

        # ------------------------------------------------------------------
        # Fast path: Content-Length header present
        # ------------------------------------------------------------------
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                size = 0
            if size > self._max_bytes:
                logger.warning(
                    "Request rejected: Content-Length %d exceeds limit %d",
                    size,
                    self._max_bytes,
                )
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "message": (
                                f"Request body too large. Maximum allowed size is {self._max_bytes // _MB} MB."
                            ),
                            "type": "invalid_request_error",
                            "code": "request_too_large",
                        }
                    },
                )

        # ------------------------------------------------------------------
        # Streaming path: buffer body and measure
        # ------------------------------------------------------------------
        # NOTE: Do NOT replace request._receive after reading — Starlette's
        # _CachedRequest already caches the body and re-serves it to the
        # next middleware via wrapped_receive.  Manual re-injection breaks
        # streaming responses.
        body = await request.body()
        if len(body) > self._max_bytes:
            logger.warning(
                "Request rejected: body length %d exceeds limit %d",
                len(body),
                self._max_bytes,
            )
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "message": (f"Request body too large. Maximum allowed size is {self._max_bytes // _MB} MB."),
                        "type": "invalid_request_error",
                        "code": "request_too_large",
                    }
                },
            )

        response: Response = await call_next(request)
        return response
