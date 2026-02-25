"""Authentication middleware.

Extracts the Bearer token (or SSO session cookie) from incoming requests,
determines the auth type (master key, API key, JWT, SSO session), and
resolves an :class:`~routerbot.auth.rbac.AuthContext` that is attached to
``request.state.auth_context`` for downstream route handlers.

Routes that don't require authentication (health, docs, SSO login) are
skipped via a configurable allow-list.
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request  # noqa: TC002
from starlette.responses import Response  # noqa: TC002

from routerbot.auth.rbac import AuthContext, Role

logger = logging.getLogger(__name__)

# Paths that never require authentication
_PUBLIC_PATHS: frozenset[str] = frozenset({
    "/",
    "/health",
    "/health/liveness",
    "/health/readiness",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/robots.txt",
    "/sso/login",
    "/sso/callback",
    "/sso/providers",
    "/sso/logout",
    "/auth/login",
    "/metrics",
})


class AuthMiddleware(BaseHTTPMiddleware):
    """Resolve auth context for every request.

    The middleware inspects three sources (in order of priority):

    1. ``Authorization: Bearer <token>`` (or ``X-Master-Key`` header)
    2. JWT token (if JWT auth is enabled)
    3. SSO session cookie

    On unauthenticated requests to non-public paths, an anonymous
    :class:`AuthContext` is attached (``auth_method="none"``).  Route
    handlers decide independently whether to reject.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """Process the request and resolve auth context."""
        # Skip auth for public paths
        path = request.url.path.rstrip("/") or "/"
        if path in _PUBLIC_PATHS:
            request.state.auth_context = AuthContext(auth_method="none")
            response: Response = await call_next(request)
            return response

        ctx = await self._resolve_auth(request)
        request.state.auth_context = ctx
        response = await call_next(request)
        return response

    async def _resolve_auth(self, request: Request) -> AuthContext:
        """Determine the auth context from the request."""
        state = getattr(request.app.state, "routerbot", None)
        config = getattr(state, "config", None) if state else None

        # 1. Check for Bearer token
        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

        # Also check X-Master-Key header
        master_header = request.headers.get("X-Master-Key", "")

        # 2. Check master key
        master_key = ""
        if config and config.general_settings:
            master_key = config.general_settings.master_key or ""

        if master_key and (token == master_key or master_header == master_key):
            return AuthContext(
                user_id="master",
                role=Role.ADMIN,
                auth_method="master_key",
            )

        # 3. Try API key validation (if we have a bearer token)
        if token:
            ctx = await self._try_api_key(token, state)
            if ctx is not None:
                return ctx

            # 4. Try JWT
            ctx = await self._try_jwt(token, state, config)
            if ctx is not None:
                return ctx

        # 5. Try SSO session cookie
        ctx = self._try_sso_session(request, state)
        if ctx is not None:
            return ctx

        # No valid auth — return anonymous context
        return AuthContext(auth_method="none")

    async def _try_api_key(self, token: str, state: Any) -> AuthContext | None:
        """Attempt to authenticate via API key.

        Returns ``None`` if the token doesn't look like an API key or
        validation fails.
        """
        # API keys start with a known prefix (default: "rb-")
        if not token.startswith("rb-"):
            return None

        try:
            from routerbot.auth.api_key import KeyValidationResult, validate_key
            from routerbot.db.session import get_session_factory

            factory = get_session_factory()
            if factory is None:
                return None

            async with factory() as session:
                result: KeyValidationResult = await validate_key(token, session)
                if result.valid and result.key:
                    vk = result.key
                    return AuthContext(
                        user_id=str(vk.user_id) if vk.user_id else None,
                        team_id=str(vk.team_id) if vk.team_id else None,
                        role=Role.API_USER,
                        auth_method="api_key",
                        key_id=str(vk.id),
                        allowed_models=vk.models or [],
                        max_budget=vk.max_budget,
                        current_spend=float(vk.spend or 0),
                    )
        except Exception:
            logger.debug("API key validation failed", exc_info=True)

        return None

    async def _try_jwt(self, token: str, state: Any, config: Any) -> AuthContext | None:
        """Attempt to authenticate via JWT token.

        Returns ``None`` if JWT auth is not configured or the token is invalid.
        """
        jwt_auth = getattr(state, "jwt_authenticator", None)
        if jwt_auth is None:
            return None

        try:
            claims = await jwt_auth.verify_token(token)
            return AuthContext(
                user_id=claims.user_id,
                email=claims.email,
                team_id=claims.team_id,
                role=Role.from_str(claims.role) if claims.role else Role.API_USER,
                auth_method="jwt",
                extra=claims.raw,
            )
        except Exception:
            logger.debug("JWT verification failed", exc_info=True)

        return None

    def _try_sso_session(self, request: Request, state: Any) -> AuthContext | None:
        """Attempt to authenticate via SSO session cookie.

        Returns ``None`` if no valid session found.
        """
        session_mgr = getattr(state, "session_manager", None)
        if session_mgr is None:
            return None

        cookie_name = session_mgr._config.cookie_name
        session_id = request.cookies.get(cookie_name)
        if not session_id:
            return None

        data = session_mgr.get_session(session_id)
        if data is None:
            return None

        return AuthContext(
            user_id=data.get("provider_user_id"),
            email=data.get("email"),
            role=Role.from_str(data.get("role", "editor")),
            auth_method="sso",
            extra=data,
        )


# ---------------------------------------------------------------------------
# Dependency for route handlers
# ---------------------------------------------------------------------------


def get_auth_context(request: Request) -> AuthContext:
    """FastAPI dependency that extracts the auth context from the request.

    Must be used after :class:`AuthMiddleware` has run.

    Usage in a route handler::

        @router.get("/protected")
        async def protected(ctx: AuthContext = Depends(get_auth_context)):
            require_permission(ctx, Permission.SETTINGS_MANAGE)
            ...
    """
    ctx: AuthContext | None = getattr(request.state, "auth_context", None)
    if ctx is None:
        return AuthContext(auth_method="none")
    return ctx
