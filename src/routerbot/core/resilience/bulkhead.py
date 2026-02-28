"""Bulkhead pattern — concurrency isolation per provider.

Prevents one slow or overloaded provider from consuming all available
capacity and starving other providers.  Each provider gets an independent
:class:`asyncio.Semaphore` that limits concurrent in-flight requests.

Usage::

    bh = BulkheadManager()
    async with bh.acquire("openai/gpt-4o"):
        response = await call_provider(...)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from routerbot.core.resilience.models import BulkheadConfig, BulkheadStats

logger = logging.getLogger(__name__)


class Bulkhead:
    """Concurrency limiter for a single provider.

    Parameters
    ----------
    provider:
        Provider identifier.
    config:
        Max concurrent requests and wait timeout.
    """

    def __init__(self, provider: str, config: BulkheadConfig | None = None) -> None:
        self.provider = provider
        self.config = config or BulkheadConfig()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._active = 0
        self._waiting = 0
        self._total_accepted = 0
        self._total_rejected = 0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        """Acquire a concurrency slot, raising ``BulkheadFullError`` on timeout."""
        async with self._lock:
            self._waiting += 1

        try:
            if (
                self.config.max_wait_seconds <= 0
                and self._semaphore.locked()
                and self._active >= self.config.max_concurrent
            ):
                async with self._lock:
                    self._waiting -= 1
                    self._total_rejected += 1
                raise BulkheadFullError(self.provider)
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self.config.max_wait_seconds if self.config.max_wait_seconds > 0 else None,
            )
        except TimeoutError:
            async with self._lock:
                self._waiting -= 1
                self._total_rejected += 1
            raise BulkheadFullError(self.provider) from None

        async with self._lock:
            self._waiting -= 1
            self._active += 1
            self._total_accepted += 1

        try:
            yield
        finally:
            self._semaphore.release()
            async with self._lock:
                self._active -= 1

    def stats(self) -> BulkheadStats:
        return BulkheadStats(
            provider=self.provider,
            max_concurrent=self.config.max_concurrent,
            active=self._active,
            waiting=self._waiting,
            total_accepted=self._total_accepted,
            total_rejected=self._total_rejected,
        )


class BulkheadFullError(Exception):
    """Raised when a bulkhead cannot admit more concurrent requests."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"Bulkhead full for provider {provider!r}")


class BulkheadManager:
    """Manages per-provider bulkheads.

    Parameters
    ----------
    default_config:
        Default concurrency limits applied to all providers.
    overrides:
        Per-provider overrides keyed by provider name.
    """

    def __init__(
        self,
        default_config: BulkheadConfig | None = None,
        overrides: dict[str, BulkheadConfig] | None = None,
    ) -> None:
        self._default_config = default_config or BulkheadConfig()
        self._overrides = overrides or {}
        self._bulkheads: dict[str, Bulkhead] = {}

    def get(self, provider: str) -> Bulkhead:
        """Get or create a bulkhead for *provider*."""
        if provider not in self._bulkheads:
            cfg = self._overrides.get(provider, self._default_config)
            self._bulkheads[provider] = Bulkhead(provider, cfg)
        return self._bulkheads[provider]

    @asynccontextmanager
    async def acquire(self, provider: str) -> AsyncIterator[None]:
        """Convenience: acquire the bulkhead for *provider*."""
        async with self.get(provider).acquire():
            yield

    def all_stats(self) -> list[BulkheadStats]:
        return [b.stats() for b in self._bulkheads.values()]

    def total_active(self) -> int:
        return sum(b._active for b in self._bulkheads.values())

    def summary(self) -> dict[str, int]:
        return {
            "total_providers": len(self._bulkheads),
            "total_active": self.total_active(),
            "total_rejected": sum(b._total_rejected for b in self._bulkheads.values()),
        }
