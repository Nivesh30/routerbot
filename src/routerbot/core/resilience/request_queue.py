"""Async bounded request queue for provider outage buffering.

When a provider's circuit breaker is OPEN, incoming requests can be
enqueued instead of immediately rejected.  Once the provider recovers
(circuit transitions back to CLOSED/HALF_OPEN), requests are drained
in FIFO order.

Expired items are silently dropped during drain.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC
from typing import Any

from routerbot.core.resilience.models import (
    QueuedRequest,
    RequestQueueConfig,
    RequestQueueStats,
)

UTC = UTC
logger = logging.getLogger(__name__)


class RequestQueue:
    """Per-provider async bounded request queue.

    Parameters
    ----------
    provider:
        Identifier for the target provider.
    config:
        Queue depth and TTL configuration.
    """

    def __init__(self, provider: str, config: RequestQueueConfig | None = None) -> None:
        self.provider = provider
        self.config = config or RequestQueueConfig()
        self._queue: asyncio.Queue[QueuedRequest] = asyncio.Queue(maxsize=self.config.max_size)
        self._total_enqueued = 0
        self._total_drained = 0
        self._total_expired = 0
        self._total_rejected = 0

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    async def enqueue(self, payload: dict[str, Any], ttl: float | None = None) -> QueuedRequest | None:
        """Enqueue a request.  Returns the queued item, or ``None`` if full."""
        if not self.config.enabled:
            return None

        item = QueuedRequest(
            request_id=f"q-{uuid.uuid4().hex[:12]}",
            provider=self.provider,
            payload=payload,
            ttl_seconds=ttl or self.config.default_ttl,
        )
        try:
            self._queue.put_nowait(item)
            self._total_enqueued += 1
            logger.debug("Queued request %s for %s (depth=%d)", item.request_id, self.provider, self.depth)
            return item
        except asyncio.QueueFull:
            self._total_rejected += 1
            logger.warning("Queue full for %s — rejecting request", self.provider)
            return None

    # ------------------------------------------------------------------
    # Drain
    # ------------------------------------------------------------------

    async def drain(self, max_items: int | None = None) -> list[QueuedRequest]:
        """Drain up to *max_items* non-expired requests.

        Returns
        -------
        list[QueuedRequest]
            Live (non-expired) requests in FIFO order.
        """
        limit = max_items or self.config.drain_batch_size
        results: list[QueuedRequest] = []

        while len(results) < limit and not self._queue.empty():
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item.is_expired:
                self._total_expired += 1
                logger.debug("Expired queued request %s for %s", item.request_id, self.provider)
                continue
            results.append(item)
            self._total_drained += 1

        return results

    async def drain_all(self) -> list[QueuedRequest]:
        """Drain the entire queue (non-expired items only)."""
        return await self.drain(max_items=self._queue.qsize() + 1)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    @property
    def is_empty(self) -> bool:
        return self._queue.empty()

    @property
    def is_full(self) -> bool:
        return self._queue.full()

    def stats(self) -> RequestQueueStats:
        return RequestQueueStats(
            provider=self.provider,
            depth=self.depth,
            total_enqueued=self._total_enqueued,
            total_drained=self._total_drained,
            total_expired=self._total_expired,
            total_rejected=self._total_rejected,
        )

    async def clear(self) -> int:
        """Drop all queued items, returning the count dropped."""
        dropped = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                dropped += 1
            except asyncio.QueueEmpty:
                break
        return dropped


class RequestQueueManager:
    """Manages per-provider request queues."""

    def __init__(self, default_config: RequestQueueConfig | None = None) -> None:
        self._default_config = default_config or RequestQueueConfig()
        self._queues: dict[str, RequestQueue] = {}

    def get(self, provider: str) -> RequestQueue:
        """Get or create a queue for *provider*."""
        if provider not in self._queues:
            self._queues[provider] = RequestQueue(provider, self._default_config)
        return self._queues[provider]

    async def enqueue(self, provider: str, payload: dict[str, Any], ttl: float | None = None) -> QueuedRequest | None:
        return await self.get(provider).enqueue(payload, ttl)

    async def drain(self, provider: str, max_items: int | None = None) -> list[QueuedRequest]:
        return await self.get(provider).drain(max_items)

    def all_stats(self) -> list[RequestQueueStats]:
        return [q.stats() for q in self._queues.values()]

    def total_depth(self) -> int:
        return sum(q.depth for q in self._queues.values())

    async def clear_all(self) -> int:
        total = 0
        for q in self._queues.values():
            total += await q.clear()
        return total
