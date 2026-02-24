"""Robots.txt middleware.

Returns a ``Disallow: /`` robots.txt when ``block_robots`` is enabled in
the configuration.  This prevents web crawlers from indexing the API.

Usage::

    from routerbot.proxy.middleware.robots import RobotsTxtMiddleware

    app.add_middleware(RobotsTxtMiddleware, enabled=True)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request  # noqa: TC002
from starlette.responses import PlainTextResponse, Response

if TYPE_CHECKING:
    from starlette.types import ASGIApp

_ROBOTS_TXT = "User-agent: *\nDisallow: /\n"


class RobotsTxtMiddleware(BaseHTTPMiddleware):
    """Respond to ``GET /robots.txt`` with ``Disallow: /`` when enabled.

    Parameters
    ----------
    app:
        The ASGI application to wrap.
    enabled:
        Whether to serve the disallow-all robots.txt.  Defaults to
        ``True``.  When ``False``, the request falls through to the
        normal application routes.
    """

    def __init__(self, app: ASGIApp, enabled: bool = True) -> None:
        super().__init__(app)
        self._enabled = enabled

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if self._enabled and request.method == "GET" and request.url.path == "/robots.txt":
            return PlainTextResponse(_ROBOTS_TXT, status_code=200)
        response: Response = await call_next(request)
        return response
