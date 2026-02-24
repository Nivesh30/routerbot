"""Async SQLAlchemy engine setup and connection pooling.

Provides factory functions for creating async engines and session
factories.  Supports PostgreSQL (production) and SQLite (development).

Usage::

    from routerbot.db.engine import create_engine, create_session_factory

    engine = create_engine("sqlite+aiosqlite:///routerbot.db")
    SessionLocal = create_session_factory(engine)
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------


def create_engine(
    url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_pre_ping: bool = True,
    echo: bool = False,
) -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    Parameters
    ----------
    url:
        Database URL.  Example values:

        - ``sqlite+aiosqlite:///routerbot.db`` (dev)
        - ``postgresql+asyncpg://user:pass@host/db`` (production)
    pool_size:
        Number of persistent connections in the pool (ignored for SQLite).
    max_overflow:
        Allowed temporary connections above *pool_size*.
    pool_timeout:
        Seconds to wait for a connection from the pool.
    pool_pre_ping:
        Issue a ``SELECT 1`` health-check before using a pooled connection.
    echo:
        Log all emitted SQL statements (noisy — dev only).

    Returns
    -------
    AsyncEngine
        The configured engine.
    """
    # SQLite does not support connection pooling in the same way
    is_sqlite = url.startswith("sqlite")
    kwargs: dict[str, object] = {
        "echo": echo,
        "pool_pre_ping": pool_pre_ping,
    }
    if not is_sqlite:
        kwargs.update(
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
        )

    engine = create_async_engine(url, **kwargs)
    logger.info("Database engine created (url=%s, pool_size=%d)", _mask_url(url), pool_size)
    return engine


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to *engine*.

    Parameters
    ----------
    engine:
        The async engine to bind sessions to.

    Returns
    -------
    async_sessionmaker[AsyncSession]
        A callable that produces ``AsyncSession`` instances.
    """
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mask_url(url: str) -> str:
    """Mask credentials in a database URL for safe logging."""
    if "@" in url:
        scheme_rest = url.split("://", 1)
        if len(scheme_rest) == 2:
            creds_host = scheme_rest[1].split("@", 1)
            if len(creds_host) == 2:
                return f"{scheme_rest[0]}://***@{creds_host[1]}"
    return url
