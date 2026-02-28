"""User repository — CRUD + lookup by email/SSO ID."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from routerbot.db.models import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
from routerbot.db.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Data-access layer for :class:`User` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> User | None:
        """Look up a user by email address."""
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_sso_id(self, sso_provider_id: str) -> User | None:
        """Look up a user by SSO provider ID."""
        stmt = select(User).where(User.sso_provider_id == sso_provider_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self, *, offset: int = 0, limit: int = 100) -> list[User]:
        """Return only active users."""
        stmt = select(User).where(User.is_active.is_(True)).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def deactivate(self, user: User) -> User:
        """Soft-delete a user (``is_active = False``)."""
        return await self.update(user, is_active=False)

    async def increment_spend(self, user: User, amount: float) -> User:
        """Add *amount* to the user's running spend total."""
        user.spend += amount
        await self._session.flush()
        return user
