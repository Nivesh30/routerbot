"""Spend tracking and reporting routes.

Endpoints:
    GET   /spend/logs    — Detailed spend logs (paginated, filterable)
    GET   /spend/report  — Spend report (by model, user, team)
    GET   /spend/keys    — Spend per key
    GET   /spend/tags    — Spend aggregated by tag  (future)

All endpoints require authentication and appropriate permissions.
"""

from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from routerbot.auth.rbac import (
    AuthContext,
    Permission,
    require_authenticated,
    require_permission,
)
from routerbot.db.repositories.spend import SpendRepository
from routerbot.db.session import get_session
from routerbot.proxy.middleware.auth import get_auth_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/spend", tags=["Spend Tracking"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spend_log_info(log: Any) -> dict[str, Any]:
    """Serialize a SpendLog entity to a JSON-safe dict."""
    return {
        "id": str(log.id),
        "key_id": str(log.key_id) if log.key_id else None,
        "user_id": str(log.user_id) if log.user_id else None,
        "team_id": str(log.team_id) if log.team_id else None,
        "model": log.model,
        "provider": log.provider,
        "request_id": log.request_id,
        "tokens_prompt": log.tokens_prompt,
        "tokens_completion": log.tokens_completion,
        "cost": log.cost,
        "tags": log.tags,
        "metadata": log.metadata_,
        "ip_address": log.ip_address,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/logs", summary="List spend logs")
async def spend_logs(
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
    user_id: str | None = None,
    team_id: str | None = None,
    key_id: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> JSONResponse:
    """List spend logs with optional filters.

    Admin can see all logs. Editor/viewer can see own logs only.
    """
    require_authenticated(ctx)

    repo = SpendRepository(session)

    # Non-admins can only see their own spend
    if not ctx.has_permission(Permission.SPEND_VIEW_ALL):
        require_permission(ctx, Permission.SPEND_VIEW_OWN)
        if ctx.user_id:
            user_id = ctx.user_id
        else:
            return JSONResponse(content={"logs": []})

    if key_id:
        logs = await repo.list_by_key(_uuid.UUID(key_id), offset=offset, limit=limit)
    elif user_id:
        logs = await repo.list_by_user(_uuid.UUID(user_id), offset=offset, limit=limit)
    elif team_id:
        logs = await repo.list_by_team(_uuid.UUID(team_id), offset=offset, limit=limit)
    else:
        logs = await repo.list_all(offset=offset, limit=limit)

    return JSONResponse(content={"logs": [_spend_log_info(entry) for entry in logs]})


@router.get("/report", summary="Spend report by model")
async def spend_report(
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Generate a spend report aggregated by model.

    Admin only.
    """
    require_permission(ctx, Permission.SPEND_VIEW_ALL)

    repo = SpendRepository(session)
    by_model = await repo.cost_by_model()

    return JSONResponse(content={
        "report": [
            {"model": model, "total_cost": cost}
            for model, cost in by_model
        ],
    })


@router.get("/keys", summary="Spend per key")
async def spend_keys(
    key_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Get total spend and token usage for a specific key."""
    require_authenticated(ctx)

    repo = SpendRepository(session)
    total_cost = await repo.total_cost_by_key(_uuid.UUID(key_id))
    prompt_tokens, completion_tokens = await repo.token_totals(key_id=_uuid.UUID(key_id))

    return JSONResponse(content={
        "key_id": key_id,
        "total_cost": total_cost,
        "tokens_prompt": prompt_tokens,
        "tokens_completion": completion_tokens,
    })
