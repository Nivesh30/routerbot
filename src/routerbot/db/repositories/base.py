"""Base repository with common CRUD helpers.

All concrete repositories inherit from :class:`BaseRepository` and
get ``get_by_id``, ``list_all``, ``create``, ``update``, and
``delete`` for free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, TypeVar

from sqlalchemy import select

from routerbot.db.models import Base

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Generic async repository providing CRUD primitives.

    Parameters
    ----------
    model:
        The SQLAlchemy ORM model class this repository manages.
    session:
        An active async session.
    """

    def __init__(self, model: type[T], session: AsyncSession) -> None:
        self._model = model
        self._session = session

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_by_id(self, entity_id: uuid.UUID) -> T | None:
        """Return a single entity by primary key, or ``None``."""
        return await self._session.get(self._model, entity_id)

    async def list_all(self, *, offset: int = 0, limit: int = 100) -> list[T]:
        """Return a paginated list of entities."""
        stmt = select(self._model).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create(self, **kwargs: Any) -> T:
        """Create and persist a new entity.

        Returns
        -------
        T
            The newly created entity (with generated defaults populated
            after flush).
        """
        entity = self._model(**kwargs)
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update(self, entity: T, **kwargs: Any) -> T:
        """Update an existing entity's attributes.

        After flushing, the entity is refreshed so that server-side
        defaults (e.g. ``onupdate=func.now()``) are eagerly loaded in
        the async context — preventing ``MissingGreenlet`` errors on
        subsequent attribute access.

        Returns
        -------
        T
            The updated entity.
        """
        for key, value in kwargs.items():
            setattr(entity, key, value)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def delete(self, entity: T) -> None:
        """Hard-delete an entity from the database."""
        await self._session.delete(entity)
        await self._session.flush()
