"""Authentication routes for the dashboard.

Provides a login endpoint that validates credentials (master key, API key,
or SSO session) and returns the resolved identity with role and permissions.

Endpoints:
    POST /auth/login    — Validate credentials and return auth info
    GET  /auth/me       — Return current auth context (requires valid auth)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from routerbot.auth.rbac import AuthContext, Role
from routerbot.core.exceptions import AuthenticationError
from routerbot.proxy.middleware.auth import get_auth_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Login request body."""

    key: str


class AuthInfoResponse(BaseModel):
    """Authentication info returned on login or /auth/me."""

    authenticated: bool
    user_id: str | None = None
    email: str | None = None
    team_id: str | None = None
    role: str
    auth_method: str
    permissions: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_context_to_response(ctx: AuthContext) -> AuthInfoResponse:
    """Convert an AuthContext to an API response."""
    return AuthInfoResponse(
        authenticated=ctx.is_authenticated,
        user_id=ctx.user_id,
        email=ctx.email,
        team_id=ctx.team_id,
        role=ctx.role.value,
        auth_method=ctx.auth_method,
        permissions=[p.value for p in ctx.permissions],
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/login", summary="Validate credentials and return auth info")
async def login(body: LoginRequest, request: Request) -> JSONResponse:
    """Validate a master key or API key and return the auth context.

    The dashboard uses this to authenticate users and determine their
    role and permissions without making a separate API call.
    """
    token = body.key.strip()
    if not token:
        raise AuthenticationError(message="API key is required")

    state = getattr(request.app.state, "routerbot", None)
    config = getattr(state, "config", None) if state else None

    # 1. Check master key
    master_key = ""
    if config and config.general_settings:
        master_key = config.general_settings.master_key or ""

    if master_key and token == master_key:
        ctx = AuthContext(
            user_id="master",
            role=Role.ADMIN,
            auth_method="master_key",
        )
        resp = _auth_context_to_response(ctx)
        return JSONResponse(content=resp.model_dump())

    # 2. Try API key
    if token.startswith("rb-"):
        try:
            from routerbot.auth.api_key import validate_key
            from routerbot.db.session import get_session_factory

            factory = get_session_factory()
            if factory is not None:
                async with factory() as session:
                    result = await validate_key(token, session)
                    if result.valid and result.key:
                        vk = result.key
                        ctx = AuthContext(
                            user_id=str(vk.user_id) if vk.user_id else None,
                            team_id=str(vk.team_id) if vk.team_id else None,
                            role=Role.API_USER,
                            auth_method="api_key",
                            key_id=str(vk.id),
                            allowed_models=vk.models or [],
                            max_budget=vk.max_budget,
                            current_spend=float(vk.spend or 0),
                        )
                        resp = _auth_context_to_response(ctx)
                        return JSONResponse(content=resp.model_dump())
        except Exception:
            logger.debug("API key validation failed during login", exc_info=True)

    raise AuthenticationError(message="Invalid API key")


@router.get("/me", summary="Get current auth context")
async def get_me(
    ctx: AuthContext = Depends(get_auth_context),
) -> JSONResponse:
    """Return the auth context for the current request.

    Requires a valid ``Authorization: Bearer <token>`` header.
    """
    if not ctx.is_authenticated:
        raise AuthenticationError(message="Not authenticated")

    resp = _auth_context_to_response(ctx)
    return JSONResponse(content=resp.model_dump())
