"""Audit logging helper.

Provides :func:`emit_audit_event` for route handlers to record admin
actions into the ``audit_logs`` table, and :func:`run_retention_cleanup`
for periodic purging of old entries.

Usage::

    from routerbot.auth.audit import emit_audit_event

    await emit_audit_event(
        session=session,
        action="key.create",
        auth=auth,
        target_type="key",
        target_id=new_key.id,
        new_value={"key_prefix": "rb-abc"},
        request=request,
    )
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from routerbot.db.repositories.audit import AuditRepository

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession
    from starlette.requests import Request

    from routerbot.auth.rbac import AuthContext
    from routerbot.db.models import AuditLog

logger = logging.getLogger(__name__)

# Default retention: 90 days
DEFAULT_RETENTION_DAYS = 90


async def emit_audit_event(
    *,
    session: AsyncSession,
    action: str,
    auth: AuthContext,
    target_type: str,
    target_id: uuid.UUID | str | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Write a single audit log entry.

    Parameters
    ----------
    session:
        Active async session (will be flushed but NOT committed).
    action:
        Dot-notation action string, e.g. ``"key.create"``, ``"team.delete"``.
    auth:
        The resolved :class:`AuthContext` for the current request.
    target_type:
        Entity type being acted on (``"key"``, ``"team"``, ``"user"``, etc.).
    target_id:
        UUID of the entity being acted on (optional if N/A).
    old_value:
        Snapshot of the entity *before* the change (for update/delete).
    new_value:
        Snapshot of the entity *after* the change (for create/update).
    request:
        The Starlette :class:`Request`, used to extract IP and User-Agent.

    Returns
    -------
    AuditLog
        The persisted audit log entry.
    """
    ip_address: str | None = None
    user_agent: str | None = None

    if request is not None:
        # Prefer X-Forwarded-For for reverse-proxy setups
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip_address = forwarded.split(",")[0].strip()
        elif request.client:
            ip_address = request.client.host
        user_agent = request.headers.get("user-agent")

    # Normalise target_id to UUID-compatible string for the column
    import uuid as _uuid

    tid: _uuid.UUID | None = None
    if target_id is not None:
        tid = _uuid.UUID(str(target_id)) if not isinstance(target_id, _uuid.UUID) else target_id

    actor_id: _uuid.UUID | None = None
    if auth.user_id:
        with contextlib.suppress(ValueError, AttributeError):
            actor_id = _uuid.UUID(str(auth.user_id))

    repo = AuditRepository(session)
    entry = await repo.create(
        action=action,
        actor_id=actor_id,
        actor_type="user",
        target_type=target_type,
        target_id=tid,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    logger.info(
        "Audit: %s by %s on %s/%s",
        action,
        auth.user_id or "anonymous",
        target_type,
        target_id or "-",
    )

    return entry


async def run_retention_cleanup(
    session: AsyncSession,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> int:
    """Delete audit logs older than *retention_days*.

    Intended to be called from a background task or scheduled job.

    Returns
    -------
    int
        Number of deleted rows.
    """
    cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
    repo = AuditRepository(session)
    deleted = await repo.delete_older_than(cutoff)
    if deleted:
        logger.info("Audit retention cleanup: deleted %d entries older than %s", deleted, cutoff.isoformat())
    return deleted
