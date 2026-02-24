"""User management routes.

Endpoints:
    POST  /user/new    — Create a new user
    POST  /user/update — Update user settings
    POST  /user/delete — Deactivate a user
    GET   /user/info   — Get user details
    GET   /user/list   — List users (admin only)

All management endpoints require authentication.
"""

from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from routerbot.auth.rbac import (
    AuthContext,
    Permission,
    require_authenticated,
    require_owner_or_admin,
    require_permission,
)
from routerbot.db.repositories.users import UserRepository
from routerbot.db.session import get_session
from routerbot.proxy.middleware.auth import get_auth_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/user", tags=["User Management"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class UserCreateRequest(BaseModel):
    """Body for ``POST /user/new``."""

    email: str = Field(..., description="User email address")
    role: str = Field(default="api_user", description="User role (admin, editor, viewer, api_user)")
    max_budget: float | None = Field(default=None, ge=0, description="Max spend in USD")
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserUpdateRequest(BaseModel):
    """Body for ``POST /user/update``."""

    user_id: str = Field(..., description="User UUID")
    email: str | None = Field(default=None)
    role: str | None = Field(default=None)
    max_budget: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] | None = Field(default=None)


class UserDeleteRequest(BaseModel):
    """Body for ``POST /user/delete``."""

    user_id: str = Field(..., description="User UUID")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_info(user: Any) -> dict[str, Any]:
    """Serialize a User entity to a JSON-safe dict."""
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "max_budget": user.max_budget,
        "spend": user.spend,
        "is_active": user.is_active,
        "sso_provider_id": user.sso_provider_id,
        "metadata": user.metadata_,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/new", summary="Create a new user")
async def user_create(
    body: UserCreateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Create a new user. Admin only."""
    require_permission(ctx, Permission.USERS_MANAGE)

    repo = UserRepository(session)

    # Check uniqueness
    existing = await repo.get_by_email(body.email)
    if existing:
        return JSONResponse(
            status_code=409,
            content={"error": f"User with email '{body.email}' already exists"},
        )

    user = await repo.create(
        email=body.email,
        role=body.role,
        max_budget=body.max_budget,
        metadata_=body.metadata,
    )
    return JSONResponse(status_code=201, content=_user_info(user))


@router.post("/update", summary="Update a user")
async def user_update(
    body: UserUpdateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Update a user's settings. Admin or self."""
    require_authenticated(ctx)
    require_owner_or_admin(ctx, body.user_id)

    repo = UserRepository(session)
    user = await repo.get_by_id(_uuid.UUID(body.user_id))
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    updates: dict[str, Any] = {}
    if body.email is not None:
        updates["email"] = body.email
    if body.role is not None:
        # Only admin can change roles
        if not ctx.is_admin:
            return JSONResponse(status_code=403, content={"error": "Only admins can change roles"})
        updates["role"] = body.role
    if body.max_budget is not None:
        if not ctx.is_admin:
            return JSONResponse(status_code=403, content={"error": "Only admins can change budgets"})
        updates["max_budget"] = body.max_budget
    if body.metadata is not None:
        updates["metadata_"] = body.metadata

    if updates:
        user = await repo.update(user, **updates)

    return JSONResponse(content=_user_info(user))


@router.post("/delete", summary="Deactivate a user")
async def user_delete(
    body: UserDeleteRequest,
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Soft-delete (deactivate) a user. Admin only."""
    require_permission(ctx, Permission.USERS_MANAGE)

    repo = UserRepository(session)
    user = await repo.get_by_id(_uuid.UUID(body.user_id))
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    await repo.deactivate(user)
    return JSONResponse(content={"status": "deactivated", "user_id": body.user_id})


@router.get("/info", summary="Get user details")
async def user_info(
    user_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Get user details. Admin or self."""
    require_authenticated(ctx)
    require_owner_or_admin(ctx, user_id)

    repo = UserRepository(session)
    user = await repo.get_by_id(_uuid.UUID(user_id))
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    return JSONResponse(content=_user_info(user))


@router.get("/list", summary="List all users")
async def user_list(
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
    offset: int = 0,
    limit: int = 100,
) -> JSONResponse:
    """List all active users. Admin only."""
    require_permission(ctx, Permission.USERS_MANAGE)

    repo = UserRepository(session)
    users = await repo.list_active(offset=offset, limit=limit)
    return JSONResponse(content={"users": [_user_info(u) for u in users]})
