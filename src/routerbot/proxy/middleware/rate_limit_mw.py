"""Rate limiting middleware — enforces limits built by ``InMemoryRateLimiter``.

Only checked for the LLM-serving endpoints (chat/completions, embeddings,
images, audio, rerank) since those are what rate limits are meant to
protect. Requires :class:`~routerbot.proxy.middleware.auth.AuthMiddleware`
to have already run (reads ``request.state.auth_context``) — registered
accordingly in ``proxy/app.py``.
"""

from __future__ import annotations

from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request  # noqa: TC002
from starlette.responses import JSONResponse, Response

_LLM_PATH_PREFIXES = (
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/embeddings",
    "/v1/images/generations",
    "/v1/audio/",
    "/v1/rerank",
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce request-count rate limits on LLM-serving endpoints.

    The limiter is looked up from ``request.app.state.routerbot.rate_limiter``
    on every request (rather than captured at construction time), since it's
    built during the app's async startup hook — after this middleware is
    already constructed by ``create_app()``. A missing limiter (rate
    limiting not configured) makes this a no-op.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        routerbot_state = getattr(request.app.state, "routerbot", None)
        limiter = getattr(routerbot_state, "rate_limiter", None) if routerbot_state else None

        if limiter is None or not request.url.path.startswith(_LLM_PATH_PREFIXES):
            bypass_response: Response = await call_next(request)
            return bypass_response

        ctx = getattr(request.state, "auth_context", None)
        key_id = getattr(ctx, "key_id", None)
        user_id = getattr(ctx, "user_id", None)
        team_id = getattr(ctx, "team_id", None)

        result = limiter.check_rate_limit(key_id=key_id, user_id=user_id, team_id=team_id)
        if not result.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "message": "Rate limit exceeded",
                        "type": "rate_limit_error",
                        "code": "rate_limit_exceeded",
                    }
                },
                headers=result.to_headers(),
            )

        # Token usage (TPM) is recorded separately once the actual response's
        # usage is known — see the spend/callback dispatch in completions.py.
        limiter.record_request(key_id=key_id, user_id=user_id, team_id=team_id)

        response: Response = await call_next(request)
        for header, value in result.to_headers().items():
            response.headers[header] = value
        return response
