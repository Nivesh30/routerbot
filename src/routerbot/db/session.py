"""Async session management for RouterBot database.

Provides a request-scoped session via FastAPI dependency injection
and transaction management helpers.

Usage::

    from routerbot.db.session import get_session

    @router.get("/items")
    async def list_items(session: AsyncSession = Depends(get_session)):
        ...
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

# Module-level session factory — set during app startup
_session_factory: async_sessionmaker[AsyncSession] | None = None


def configure_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    """Set the module-level session factory (called once at startup).

    Parameters
    ----------
    factory:
        An ``async_sessionmaker`` bound to the application's engine.
    """
    global _session_factory
    _session_factory = factory
    logger.debug("Session factory configured")


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the module-level session factory.

    Raises
    ------
    RuntimeError
        If the session factory has not been configured yet.
    """
    if _session_factory is None:
        msg = "Session factory not initialised — call configure_session_factory() at startup."
        raise RuntimeError(msg)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a request-scoped async session.

    The session is automatically committed on success and rolled back
    on exception.

    Usage::

        @router.post("/items")
        async def create_item(
            session: AsyncSession = Depends(get_session),
        ):
            session.add(item)
            # commit happens automatically at the end of the request

    Yields
    ------
    AsyncSession
        A scoped async session.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
