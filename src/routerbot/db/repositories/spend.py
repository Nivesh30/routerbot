"""Spend-log repository — logging + aggregation queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from routerbot.db.models import SpendLog

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession
from routerbot.db.repositories.base import BaseRepository


class SpendRepository(BaseRepository[SpendLog]):
    """Data-access layer for :class:`SpendLog` entries."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(SpendLog, session)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_by_key(
        self, key_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[SpendLog]:
        """Return spend logs for a specific virtual key."""
        stmt = (
            select(SpendLog)
            .where(SpendLog.key_id == key_id)
            .order_by(SpendLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_user(
        self, user_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[SpendLog]:
        """Return spend logs for a specific user."""
        stmt = (
            select(SpendLog)
            .where(SpendLog.user_id == user_id)
            .order_by(SpendLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_team(
        self, team_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[SpendLog]:
        """Return spend logs for a specific team."""
        stmt = (
            select(SpendLog)
            .where(SpendLog.team_id == team_id)
            .order_by(SpendLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_date_range(
        self,
        *,
        start: datetime,
        end: datetime,
        offset: int = 0,
        limit: int = 100,
    ) -> list[SpendLog]:
        """Return spend logs within a date range."""
        stmt = (
            select(SpendLog)
            .where(SpendLog.created_at >= start, SpendLog.created_at <= end)
            .order_by(SpendLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Aggregations
    # ------------------------------------------------------------------

    async def total_cost_by_key(self, key_id: uuid.UUID) -> float:
        """Sum total cost for a key."""
        stmt = select(func.coalesce(func.sum(SpendLog.cost), 0.0)).where(
            SpendLog.key_id == key_id
        )
        result = await self._session.execute(stmt)
        return float(result.scalar_one())

    async def total_cost_by_user(self, user_id: uuid.UUID) -> float:
        """Sum total cost for a user."""
        stmt = select(func.coalesce(func.sum(SpendLog.cost), 0.0)).where(
            SpendLog.user_id == user_id
        )
        result = await self._session.execute(stmt)
        return float(result.scalar_one())

    async def total_cost_by_team(self, team_id: uuid.UUID) -> float:
        """Sum total cost for a team."""
        stmt = select(func.coalesce(func.sum(SpendLog.cost), 0.0)).where(
            SpendLog.team_id == team_id
        )
        result = await self._session.execute(stmt)
        return float(result.scalar_one())

    async def cost_by_model(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[tuple[str, float]]:
        """Return (model, total_cost) aggregated by model name."""
        stmt = select(SpendLog.model, func.sum(SpendLog.cost).label("total"))
        if start:
            stmt = stmt.where(SpendLog.created_at >= start)
        if end:
            stmt = stmt.where(SpendLog.created_at <= end)
        stmt = stmt.group_by(SpendLog.model).order_by(func.sum(SpendLog.cost).desc())
        result = await self._session.execute(stmt)
        return [(row[0], float(row[1])) for row in result.all()]

    async def token_totals(
        self,
        *,
        key_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
    ) -> tuple[int, int]:
        """Return (prompt_tokens, completion_tokens) totals.

        Optionally filtered by key or user.
        """
        stmt = select(
            func.coalesce(func.sum(SpendLog.tokens_prompt), 0),
            func.coalesce(func.sum(SpendLog.tokens_completion), 0),
        )
        if key_id:
            stmt = stmt.where(SpendLog.key_id == key_id)
        if user_id:
            stmt = stmt.where(SpendLog.user_id == user_id)
        result = await self._session.execute(stmt)
        row = result.one()
        return (int(row[0]), int(row[1]))
