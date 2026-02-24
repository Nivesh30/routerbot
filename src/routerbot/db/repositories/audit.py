"""Audit-log repository — immutable trail with retention management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select

from routerbot.db.models import AuditLog

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession
from routerbot.db.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    """Data-access layer for :class:`AuditLog` entries."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AuditLog, session)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_by_actor(
        self, actor_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[AuditLog]:
        """Return audit logs created by a specific actor."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.actor_id == actor_id)
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_action(
        self, action: str, *, offset: int = 0, limit: int = 100
    ) -> list[AuditLog]:
        """Return audit logs of a specific action type."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.action == action)
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_target(
        self, target_type: str, target_id: uuid.UUID | None = None, *, offset: int = 0, limit: int = 100
    ) -> list[AuditLog]:
        """Return audit logs for a specific target type (and optionally ID)."""
        stmt = select(AuditLog).where(AuditLog.target_type == target_type)
        if target_id is not None:
            stmt = stmt.where(AuditLog.target_id == target_id)
        stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_date_range(
        self,
        *,
        start: datetime,
        end: datetime,
        offset: int = 0,
        limit: int = 100,
    ) -> list[AuditLog]:
        """Return audit logs within a date range."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.created_at >= start, AuditLog.created_at <= end)
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_filtered(
        self,
        *,
        actor_id: uuid.UUID | None = None,
        action: str | None = None,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[AuditLog]:
        """Return audit logs matching **all** supplied filters.

        Filters are combined with AND.  Any filter set to ``None`` is
        ignored so callers can pass only the filters they care about.
        """
        stmt = select(AuditLog)
        if actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if target_type is not None:
            stmt = stmt.where(AuditLog.target_type == target_type)
        if target_id is not None:
            stmt = stmt.where(AuditLog.target_id == target_id)
        if start is not None:
            stmt = stmt.where(AuditLog.created_at >= start)
        if end is not None:
            stmt = stmt.where(AuditLog.created_at <= end)
        stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_filtered(
        self,
        *,
        actor_id: uuid.UUID | None = None,
        action: str | None = None,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        """Return total count of audit logs matching filters."""
        stmt = select(func.count(AuditLog.id))
        if actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if target_type is not None:
            stmt = stmt.where(AuditLog.target_type == target_type)
        if target_id is not None:
            stmt = stmt.where(AuditLog.target_id == target_id)
        if start is not None:
            stmt = stmt.where(AuditLog.created_at >= start)
        if end is not None:
            stmt = stmt.where(AuditLog.created_at <= end)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Delete audit logs older than *cutoff*.

        Returns
        -------
        int
            Number of rows deleted.
        """
        stmt = delete(AuditLog).where(AuditLog.created_at < cutoff)
        result = await self._session.execute(stmt)
        await self._session.flush()
        # CursorResult from DML has rowcount; cast to satisfy mypy
        return int(getattr(result, "rowcount", 0) or 0)
