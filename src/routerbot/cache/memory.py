"""In-memory LRU cache backend.

Suitable for development and single-instance deployments.  Uses an
:class:`OrderedDict` to maintain LRU ordering with configurable max size
and TTL-based expiration.

Configuration example::

    routerbot_settings:
      cache: true
      cache_params:
        type: "memory"
        ttl: 3600
        max_memory_items: 1000
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any

from routerbot.cache.base import CacheEntry  # noqa: TC001

logger = logging.getLogger(__name__)


class InMemoryCacheBackend:
    """LRU in-memory cache with TTL support.

    Parameters
    ----------
    max_size:
        Maximum number of entries to keep.  Oldest entries are evicted
        when the limit is reached.
    default_ttl:
        Default time-to-live in seconds.  ``None`` means no expiry.
    namespace:
        Logical namespace for key isolation (informational only for
        in-memory backend — keys are already isolated per instance).
    """

    def __init__(
        self,
        *,
        max_size: int = 1000,
        default_ttl: int | None = 3600,
        namespace: str = "routerbot",
    ) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._namespace = namespace
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Protocol implementation
    # ------------------------------------------------------------------

    async def get(self, key: str) -> CacheEntry | None:
        """Retrieve a cached entry, evicting it if expired."""
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return None

        if entry.is_expired:
            del self._store[key]
            self._misses += 1
            return None

        # Move to end (most recently used)
        self._store.move_to_end(key)
        self._hits += 1
        return entry

    async def set(
        self,
        key: str,
        value: CacheEntry,
        ttl: int | None = None,
    ) -> None:
        """Store a cache entry, evicting LRU entries if over capacity."""
        effective_ttl = ttl if ttl is not None else self._default_ttl
        value.ttl = effective_ttl
        if value.created_at == 0.0:
            value.created_at = time.time()

        # If key already exists, remove it first so it goes to end
        if key in self._store:
            del self._store[key]

        self._store[key] = value

        # Evict oldest entries if over capacity
        while len(self._store) > self._max_size:
            evicted_key, _ = self._store.popitem(last=False)
            logger.debug("Evicted cache entry: %s", evicted_key)

    async def delete(self, key: str) -> None:
        """Delete a specific cache entry."""
        self._store.pop(key, None)

    async def clear(self) -> None:
        """Clear all cache entries."""
        self._store.clear()
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Return the number of entries currently in the cache."""
        return len(self._store)

    @property
    def hits(self) -> int:
        """Total number of cache hits."""
        return self._hits

    @property
    def misses(self) -> int:
        """Total number of cache misses."""
        return self._misses

    @property
    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        total = self._hits + self._misses
        return {
            "backend": "memory",
            "size": self.size,
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
        }
