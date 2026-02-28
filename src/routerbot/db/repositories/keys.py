"""Virtual key repository — CRUD + hash lookup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from routerbot.db.models import VirtualKey

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession
from routerbot.db.repositories.base import BaseRepository


class KeyRepository(BaseRepository[VirtualKey]):
    """Data-access layer for :class:`VirtualKey` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(VirtualKey, session)

    async def get_by_hash(self, key_hash: str) -> VirtualKey | None:
        """Look up a key by its SHA-256 hash (O(1) via unique index)."""
        stmt = select(VirtualKey).where(VirtualKey.key_hash == key_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: uuid.UUID, *, offset: int = 0, limit: int = 100) -> list[VirtualKey]:
        """Return keys belonging to a specific user."""
        stmt = select(VirtualKey).where(VirtualKey.user_id == user_id).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_team(self, team_id: uuid.UUID, *, offset: int = 0, limit: int = 100) -> list[VirtualKey]:
        """Return keys belonging to a specific team."""
        stmt = select(VirtualKey).where(VirtualKey.team_id == team_id).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_active(self, *, offset: int = 0, limit: int = 100) -> list[VirtualKey]:
        """Return only active (non-deactivated) keys."""
        stmt = select(VirtualKey).where(VirtualKey.is_active.is_(True)).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def deactivate(self, key: VirtualKey) -> VirtualKey:
        """Soft-delete a key by setting ``is_active = False``."""
        return await self.update(key, is_active=False)

    async def increment_spend(self, key: VirtualKey, amount: float) -> VirtualKey:
        """Add *amount* to the key's running spend total."""
        key.spend += amount
        await self._session.flush()
        return key
