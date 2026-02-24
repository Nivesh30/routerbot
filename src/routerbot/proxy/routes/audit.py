"""Audit log routes.

Endpoints:
    GET  /audit/logs       — List audit logs (admin only, paginated, filtered)
    GET  /audit/logs/{id}  — Get a single audit log entry

All audit endpoints require ``audit:view`` permission (admin-only by default).
"""

from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime  # noqa: TC003
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from routerbot.auth.rbac import (
    AuthContext,
    Permission,
    require_permission,
)
from routerbot.db.repositories.audit import AuditRepository
from routerbot.db.session import get_session
from routerbot.proxy.middleware.auth import get_auth_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["Audit Logs"])


# ---------------------------------------------------------------------------
# Serialiser
# ---------------------------------------------------------------------------


def _audit_log_info(entry: Any) -> dict[str, Any]:
    """Convert an :class:`AuditLog` ORM instance to a JSON-safe dict."""
    return {
        "id": str(entry.id),
        "action": entry.action,
        "actor_id": str(entry.actor_id) if entry.actor_id else None,
        "actor_type": entry.actor_type,
        "target_type": entry.target_type,
        "target_id": str(entry.target_id) if entry.target_id else None,
        "old_value": entry.old_value,
        "new_value": entry.new_value,
        "ip_address": entry.ip_address,
        "user_agent": entry.user_agent,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/logs", response_model=None)
async def list_audit_logs(
    *,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(get_auth_context),
    actor_id: str | None = Query(None, description="Filter by actor UUID"),
    action: str | None = Query(None, description="Filter by action (e.g. key.create, team.delete)"),
    target_type: str | None = Query(None, description="Filter by target type (e.g. key, team, user)"),
    target_id: str | None = Query(None, description="Filter by target UUID"),
    start_date: datetime | None = Query(None, description="Start of date range (ISO 8601)"),
    end_date: datetime | None = Query(None, description="End of date range (ISO 8601)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Pagination limit"),
) -> JSONResponse:
    """Return paginated audit logs with optional filters.

    Requires ``audit:view`` permission (admin-only).
    """
    require_permission(auth, Permission.AUDIT_VIEW)

    repo = AuditRepository(session)

    # Parse UUID strings
    parsed_actor_id: _uuid.UUID | None = None
    parsed_target_id: _uuid.UUID | None = None
    if actor_id:
        try:
            parsed_actor_id = _uuid.UUID(actor_id)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid actor_id UUID: {actor_id}"},
            )
    if target_id:
        try:
            parsed_target_id = _uuid.UUID(target_id)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"error": f"Invalid target_id UUID: {target_id}"},
            )

    logs = await repo.list_filtered(
        actor_id=parsed_actor_id,
        action=action,
        target_type=target_type,
        target_id=parsed_target_id,
        start=start_date,
        end=end_date,
        offset=offset,
        limit=limit,
    )
    total = await repo.count_filtered(
        actor_id=parsed_actor_id,
        action=action,
        target_type=target_type,
        target_id=parsed_target_id,
        start=start_date,
        end=end_date,
    )

    return JSONResponse(
        content={
            "logs": [_audit_log_info(entry) for entry in logs],
            "total": total,
            "offset": offset,
            "limit": limit,
        },
    )


@router.get("/logs/{log_id}", response_model=None)
async def get_audit_log(
    log_id: str,
    *,
    session: AsyncSession = Depends(get_session),
    auth: AuthContext = Depends(get_auth_context),
) -> JSONResponse:
    """Return a single audit log entry by ID.

    Requires ``audit:view`` permission (admin-only).
    """
    require_permission(auth, Permission.AUDIT_VIEW)

    try:
        parsed_id = _uuid.UUID(log_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid log_id UUID: {log_id}"},
        )

    repo = AuditRepository(session)
    entry = await repo.get_by_id(parsed_id)
    if entry is None:
        return JSONResponse(
            status_code=404,
            content={"error": "Audit log entry not found"},
        )

    return JSONResponse(content=_audit_log_info(entry))
