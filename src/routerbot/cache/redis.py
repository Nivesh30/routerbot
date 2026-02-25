"""Redis cache backend.

Uses an async Redis client to store and retrieve LLM responses.  Requires
the ``redis`` package (``pip install redis``).  Falls back gracefully when
Redis is unavailable: *get* returns ``None`` and *set* silently drops.

Configuration example::

    routerbot_settings:
      cache: true
      cache_params:
        type: "redis"
        ttl: 3600
        namespace: "routerbot"
        redis_url: "redis://localhost:6379/0"
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from routerbot.cache.base import CacheEntry

logger = logging.getLogger(__name__)


class RedisCacheBackend:
    """Redis-backed cache with TTL support.

    Parameters
    ----------
    redis_url:
        Redis connection URL.
    default_ttl:
        Default time-to-live in seconds.  ``None`` means no expiry.
    namespace:
        Prefix for all cache keys (for multi-tenant isolation).
    redis_client:
        Optional pre-instantiated async Redis client.  If not provided,
        the backend lazily connects using *redis_url*.
    """

    def __init__(
        self,
        *,
        redis_url: str = "redis://localhost:6379/0",
        default_ttl: int | None = 3600,
        namespace: str = "routerbot",
        redis_client: Any | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._default_ttl = default_ttl
        self._namespace = namespace
        self._client = redis_client
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Lazy connection
    # ------------------------------------------------------------------

    async def _get_client(self) -> Any:
        """Return the Redis client, lazily connecting if needed."""
        if self._client is None:
            try:
                import redis.asyncio as aioredis
            except ImportError as exc:
                msg = (
                    "redis package is required for RedisCacheBackend. "
                    "Install with: pip install redis"
                )
                raise ImportError(msg) from exc
            self._client = aioredis.from_url(
                self._redis_url, decode_responses=True
            )
        return self._client

    def _make_key(self, key: str) -> str:
        """Prefix the key with the namespace."""
        return f"{self._namespace}:cache:{key}" if not key.startswith(self._namespace) else key

    # ------------------------------------------------------------------
    # Protocol implementation
    # ------------------------------------------------------------------

    async def get(self, key: str) -> CacheEntry | None:
        """Retrieve a cached entry from Redis."""
        try:
            client = await self._get_client()
            redis_key = self._make_key(key)
            raw = await client.get(redis_key)
            if raw is None:
                self._misses += 1
                return None

            data = json.loads(raw)
            entry = CacheEntry(
                key=data["key"],
                response_data=data["response_data"],
                model=data.get("model", ""),
                created_at=data.get("created_at", time.time()),
                ttl=data.get("ttl"),
                metadata=data.get("metadata", {}),
            )

            # TTL is handled by Redis EXPIRE, but double-check
            if entry.is_expired:
                await self.delete(key)
                self._misses += 1
                return None

            self._hits += 1
            return entry

        except Exception:
            logger.exception("Redis cache GET failed for key=%s", key)
            self._misses += 1
            return None

    async def set(
        self,
        key: str,
        value: CacheEntry,
        ttl: int | None = None,
    ) -> None:
        """Store a cache entry in Redis with optional TTL."""
        try:
            client = await self._get_client()
            redis_key = self._make_key(key)
            effective_ttl = ttl if ttl is not None else self._default_ttl

            payload = {
                "key": value.key,
                "response_data": value.response_data,
                "model": value.model,
                "created_at": value.created_at,
                "ttl": effective_ttl,
                "metadata": value.metadata,
            }

            serialised = json.dumps(payload, separators=(",", ":"))

            if effective_ttl is not None:
                await client.setex(redis_key, effective_ttl, serialised)
            else:
                await client.set(redis_key, serialised)

        except Exception:
            logger.exception("Redis cache SET failed for key=%s", key)

    async def delete(self, key: str) -> None:
        """Delete a specific cache entry from Redis."""
        try:
            client = await self._get_client()
            redis_key = self._make_key(key)
            await client.delete(redis_key)
        except Exception:
            logger.exception("Redis cache DELETE failed for key=%s", key)

    async def clear(self) -> None:
        """Clear all cache entries under this namespace."""
        try:
            client = await self._get_client()
            pattern = f"{self._namespace}:cache:*"
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor, match=pattern, count=100)
                if keys:
                    await client.delete(*keys)
                if cursor == 0:
                    break
            self._hits = 0
            self._misses = 0
        except Exception:
            logger.exception("Redis cache CLEAR failed")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

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
            "backend": "redis",
            "redis_url": self._redis_url,
            "namespace": self._namespace,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
        }
