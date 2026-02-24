"""Team management routes.

Endpoints:
    POST  /team/new           — Create a new team
    POST  /team/update        — Update team settings
    POST  /team/delete        — Soft-delete (deactivate) a team
    GET   /team/list          — List all teams
    GET   /team/info          — Get team details + members
    POST  /team/member/add    — Add a member to a team
    POST  /team/member/remove — Remove a member from a team

All endpoints require authentication (admin or team-level permissions).
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
    require_permission,
    require_team_member_or_admin,
)
from routerbot.db.repositories.teams import TeamRepository
from routerbot.db.repositories.users import UserRepository
from routerbot.db.session import get_session
from routerbot.proxy.middleware.auth import get_auth_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/team", tags=["Team Management"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class TeamCreateRequest(BaseModel):
    """Body for ``POST /team/new``."""

    name: str = Field(..., min_length=1, max_length=255, description="Team name")
    budget_limit: float | None = Field(default=None, ge=0, description="Budget limit in USD")
    max_budget_per_member: float | None = Field(default=None, ge=0)
    settings: dict[str, Any] = Field(default_factory=dict)


class TeamUpdateRequest(BaseModel):
    """Body for ``POST /team/update``."""

    team_id: str = Field(..., description="Team UUID")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    budget_limit: float | None = Field(default=None, ge=0)
    max_budget_per_member: float | None = Field(default=None, ge=0)
    settings: dict[str, Any] | None = Field(default=None)


class TeamDeleteRequest(BaseModel):
    """Body for ``POST /team/delete``."""

    team_id: str = Field(..., description="Team UUID")


class TeamMemberAddRequest(BaseModel):
    """Body for ``POST /team/member/add``."""

    team_id: str = Field(..., description="Team UUID")
    user_id: str = Field(..., description="User UUID")
    role: str = Field(default="member", description="Team role: 'admin' or 'member'")


class TeamMemberRemoveRequest(BaseModel):
    """Body for ``POST /team/member/remove``."""

    team_id: str = Field(..., description="Team UUID")
    user_id: str = Field(..., description="User UUID")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _team_info(team: Any) -> dict[str, Any]:
    """Serialize a Team entity to a JSON-safe dict.

    Safely handles cases where the ``members`` relationship has not
    been eagerly loaded (avoids MissingGreenlet in async context).
    """
    from sqlalchemy import inspect as sa_inspect

    # Only access relationships that are already loaded in memory
    state = sa_inspect(team)
    members: list[Any] = []
    if "members" not in state.unloaded:
        members = team.members or []

    return {
        "id": str(team.id),
        "name": team.name,
        "budget_limit": team.budget_limit,
        "spend": team.spend,
        "max_budget_per_member": team.max_budget_per_member,
        "settings": team.settings,
        "created_at": team.created_at.isoformat() if team.created_at else None,
        "updated_at": team.updated_at.isoformat() if team.updated_at else None,
        "members": [
            {
                "user_id": str(m.user_id),
                "role": m.role,
                "added_at": m.added_at.isoformat() if m.added_at else None,
            }
            for m in members
        ],
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/new", summary="Create a new team")
async def team_create(
    body: TeamCreateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Create a new team. Requires admin permission."""
    require_permission(ctx, Permission.TEAMS_MANAGE)

    repo = TeamRepository(session)

    # Check uniqueness
    existing = await repo.get_by_name(body.name)
    if existing:
        return JSONResponse(
            status_code=409,
            content={"error": f"Team '{body.name}' already exists"},
        )

    team = await repo.create(
        name=body.name,
        budget_limit=body.budget_limit,
        max_budget_per_member=body.max_budget_per_member,
        settings=body.settings,
    )
    return JSONResponse(status_code=201, content=_team_info(team))


@router.post("/update", summary="Update a team")
async def team_update(
    body: TeamUpdateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Update team settings. Admin only."""
    require_permission(ctx, Permission.TEAMS_MANAGE)

    repo = TeamRepository(session)
    team = await repo.get_by_id(_uuid.UUID(body.team_id))
    if not team:
        return JSONResponse(status_code=404, content={"error": "Team not found"})

    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.budget_limit is not None:
        updates["budget_limit"] = body.budget_limit
    if body.max_budget_per_member is not None:
        updates["max_budget_per_member"] = body.max_budget_per_member
    if body.settings is not None:
        updates["settings"] = body.settings

    if updates:
        team = await repo.update(team, **updates)

    return JSONResponse(content=_team_info(team))


@router.post("/delete", summary="Delete a team")
async def team_delete(
    body: TeamDeleteRequest,
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Soft-delete a team. Admin only."""
    require_permission(ctx, Permission.TEAMS_MANAGE)

    repo = TeamRepository(session)
    team = await repo.get_by_id(_uuid.UUID(body.team_id))
    if not team:
        return JSONResponse(status_code=404, content={"error": "Team not found"})

    await repo.delete(team)
    return JSONResponse(content={"status": "deleted", "team_id": body.team_id})


@router.get("/list", summary="List teams")
async def team_list(
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """List all teams. Admin only."""
    require_permission(ctx, Permission.TEAMS_MANAGE)

    repo = TeamRepository(session)
    teams = await repo.list_all(limit=500)
    return JSONResponse(content={"teams": [_team_info(t) for t in teams]})


@router.get("/info", summary="Get team details")
async def team_info(
    team_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Get team details including members. Admin or team member."""
    require_authenticated(ctx)
    require_team_member_or_admin(ctx, team_id)

    repo = TeamRepository(session)
    team = await repo.get_by_id(_uuid.UUID(team_id))
    if not team:
        return JSONResponse(status_code=404, content={"error": "Team not found"})

    return JSONResponse(content=_team_info(team))


@router.post("/member/add", summary="Add a team member")
async def team_member_add(
    body: TeamMemberAddRequest,
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Add a user to a team. Admin only."""
    require_permission(ctx, Permission.TEAMS_MANAGE)

    team_repo = TeamRepository(session)
    user_repo = UserRepository(session)

    team = await team_repo.get_by_id(_uuid.UUID(body.team_id))
    if not team:
        return JSONResponse(status_code=404, content={"error": "Team not found"})

    user = await user_repo.get_by_id(_uuid.UUID(body.user_id))
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    # Check for existing membership
    existing = await team_repo.get_membership(_uuid.UUID(body.team_id), _uuid.UUID(body.user_id))
    if existing:
        return JSONResponse(
            status_code=409,
            content={"error": "User is already a member of this team"},
        )

    membership = await team_repo.add_member(
        _uuid.UUID(body.team_id), _uuid.UUID(body.user_id), role=body.role
    )
    return JSONResponse(
        status_code=201,
        content={
            "status": "added",
            "team_id": body.team_id,
            "user_id": body.user_id,
            "role": membership.role,
        },
    )


@router.post("/member/remove", summary="Remove a team member")
async def team_member_remove(
    body: TeamMemberRemoveRequest,
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Remove a user from a team. Admin only."""
    require_permission(ctx, Permission.TEAMS_MANAGE)

    repo = TeamRepository(session)
    removed = await repo.remove_member(_uuid.UUID(body.team_id), _uuid.UUID(body.user_id))
    if not removed:
        return JSONResponse(status_code=404, content={"error": "Membership not found"})

    return JSONResponse(content={
        "status": "removed",
        "team_id": body.team_id,
        "user_id": body.user_id,
    })
