"""Team repository — CRUD + member management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from routerbot.db.models import Team, UserTeam

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession
from routerbot.db.repositories.base import BaseRepository


class TeamRepository(BaseRepository[Team]):
    """Data-access layer for :class:`Team` entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Team, session)

    async def get_by_name(self, name: str) -> Team | None:
        """Look up a team by name."""
        stmt = select(Team).where(Team.name == name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_member(self, team_id: uuid.UUID, user_id: uuid.UUID, *, role: str = "member") -> UserTeam:
        """Add a user to a team with the given role."""
        membership = UserTeam(team_id=team_id, user_id=user_id, role=role)
        self._session.add(membership)
        await self._session.flush()
        return membership

    async def remove_member(self, team_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Remove a user from a team.  Returns ``True`` if removed."""
        stmt = select(UserTeam).where(
            UserTeam.team_id == team_id,
            UserTeam.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        membership = result.scalar_one_or_none()
        if membership is None:
            return False
        await self._session.delete(membership)
        await self._session.flush()
        return True

    async def list_members(self, team_id: uuid.UUID) -> list[UserTeam]:
        """Return all memberships for a given team."""
        stmt = select(UserTeam).where(UserTeam.team_id == team_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_membership(self, team_id: uuid.UUID, user_id: uuid.UUID) -> UserTeam | None:
        """Look up a specific user-team membership."""
        stmt = select(UserTeam).where(
            UserTeam.team_id == team_id,
            UserTeam.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def increment_spend(self, team: Team, amount: float) -> Team:
        """Add *amount* to the team's running spend total."""
        team.spend += amount
        await self._session.flush()
        return team
