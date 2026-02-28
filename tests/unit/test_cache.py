"""Tests for the response caching system (Task 6.6).

Covers:
- CacheEntry: creation, expiration, properties
- build_cache_key: deterministic key generation
- InMemoryCacheBackend: get/set/delete/clear, LRU eviction, TTL, stats
- RedisCacheBackend: get/set/delete/clear with mocked Redis client
- ResponseCacheManager: lookup/store, streaming skip, cache_control bypass,
  enable/disable, invalidation
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from routerbot.cache.base import CacheEntry, build_cache_key
from routerbot.cache.manager import ResponseCacheManager
from routerbot.cache.memory import InMemoryCacheBackend

# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture()
def sample_messages() -> list[dict[str, Any]]:
    return [{"role": "user", "content": "Hello, world!"}]


@pytest.fixture()
def sample_response_data() -> dict[str, Any]:
    return {
        "id": "chatcmpl-abc123",
        "object": "chat.completion",
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hi there!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }


@pytest.fixture()
def memory_backend() -> InMemoryCacheBackend:
    return InMemoryCacheBackend(max_size=10, default_ttl=3600)


@pytest.fixture()
def cache_manager(memory_backend: InMemoryCacheBackend) -> ResponseCacheManager:
    return ResponseCacheManager(
        backend=memory_backend,
        default_ttl=3600,
        namespace="test",
    )


# ===================================================================
# CacheEntry Tests
# ===================================================================


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_create_with_defaults(self) -> None:
        entry = CacheEntry(key="k1", response_data={"a": 1})
        assert entry.key == "k1"
        assert entry.response_data == {"a": 1}
        assert entry.model == ""
        assert entry.created_at > 0
        assert entry.ttl is None
        assert entry.metadata == {}

    def test_create_with_values(self) -> None:
        entry = CacheEntry(
            key="k2",
            response_data={"b": 2},
            model="gpt-4",
            created_at=1000.0,
            ttl=60,
            metadata={"cost": 0.01},
        )
        assert entry.model == "gpt-4"
        assert entry.created_at == 1000.0
        assert entry.ttl == 60
        assert entry.metadata == {"cost": 0.01}

    def test_is_expired_no_ttl(self) -> None:
        entry = CacheEntry(key="k", response_data={}, ttl=None)
        assert entry.is_expired is False

    def test_is_expired_not_yet(self) -> None:
        entry = CacheEntry(
            key="k",
            response_data={},
            created_at=time.time(),
            ttl=3600,
        )
        assert entry.is_expired is False

    def test_is_expired_yes(self) -> None:
        entry = CacheEntry(
            key="k",
            response_data={},
            created_at=time.time() - 100,
            ttl=50,
        )
        assert entry.is_expired is True


# ===================================================================
# build_cache_key Tests
# ===================================================================


class TestBuildCacheKey:
    """Tests for deterministic cache key generation."""

    def test_same_input_same_key(self, sample_messages: list[dict[str, Any]]) -> None:
        key1 = build_cache_key(model="gpt-4", messages=sample_messages)
        key2 = build_cache_key(model="gpt-4", messages=sample_messages)
        assert key1 == key2

    def test_different_model_different_key(self, sample_messages: list[dict[str, Any]]) -> None:
        key1 = build_cache_key(model="gpt-4", messages=sample_messages)
        key2 = build_cache_key(model="gpt-3.5-turbo", messages=sample_messages)
        assert key1 != key2

    def test_different_temperature_different_key(self, sample_messages: list[dict[str, Any]]) -> None:
        key1 = build_cache_key(model="gpt-4", messages=sample_messages, temperature=0.0)
        key2 = build_cache_key(model="gpt-4", messages=sample_messages, temperature=1.0)
        assert key1 != key2

    def test_different_messages_different_key(self) -> None:
        m1 = [{"role": "user", "content": "Hello"}]
        m2 = [{"role": "user", "content": "Goodbye"}]
        key1 = build_cache_key(model="gpt-4", messages=m1)
        key2 = build_cache_key(model="gpt-4", messages=m2)
        assert key1 != key2

    def test_namespace_prefix(self, sample_messages: list[dict[str, Any]]) -> None:
        key = build_cache_key(model="gpt-4", messages=sample_messages, namespace="myns")
        assert key.startswith("myns:cache:")

    def test_with_tools(self, sample_messages: list[dict[str, Any]]) -> None:
        key1 = build_cache_key(model="gpt-4", messages=sample_messages)
        key2 = build_cache_key(
            model="gpt-4",
            messages=sample_messages,
            tools=[{"type": "function", "function": {"name": "get_weather"}}],
        )
        assert key1 != key2

    def test_with_max_tokens(self, sample_messages: list[dict[str, Any]]) -> None:
        key1 = build_cache_key(model="gpt-4", messages=sample_messages, max_tokens=100)
        key2 = build_cache_key(model="gpt-4", messages=sample_messages, max_tokens=200)
        assert key1 != key2

    def test_key_is_sha256(self, sample_messages: list[dict[str, Any]]) -> None:
        key = build_cache_key(model="gpt-4", messages=sample_messages)
        # namespace:cache:<64-char hex>
        parts = key.split(":")
        assert len(parts) == 3
        assert len(parts[2]) == 64  # SHA-256 hex digest


# ===================================================================
# InMemoryCacheBackend Tests
# ===================================================================


class TestInMemoryCacheBackend:
    """Tests for the in-memory LRU cache."""

    @pytest.mark.asyncio()
    async def test_set_and_get(self, memory_backend: InMemoryCacheBackend) -> None:
        entry = CacheEntry(key="k1", response_data={"x": 1}, model="gpt-4")
        await memory_backend.set("k1", entry)
        result = await memory_backend.get("k1")
        assert result is not None
        assert result.response_data == {"x": 1}

    @pytest.mark.asyncio()
    async def test_get_missing(self, memory_backend: InMemoryCacheBackend) -> None:
        result = await memory_backend.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio()
    async def test_delete(self, memory_backend: InMemoryCacheBackend) -> None:
        entry = CacheEntry(key="k1", response_data={"x": 1})
        await memory_backend.set("k1", entry)
        await memory_backend.delete("k1")
        result = await memory_backend.get("k1")
        assert result is None

    @pytest.mark.asyncio()
    async def test_clear(self, memory_backend: InMemoryCacheBackend) -> None:
        for i in range(5):
            await memory_backend.set(f"k{i}", CacheEntry(key=f"k{i}", response_data={"i": i}))
        assert memory_backend.size == 5
        await memory_backend.clear()
        assert memory_backend.size == 0

    @pytest.mark.asyncio()
    async def test_lru_eviction(self) -> None:
        backend = InMemoryCacheBackend(max_size=3, default_ttl=3600)
        for i in range(4):
            await backend.set(f"k{i}", CacheEntry(key=f"k{i}", response_data={"i": i}))
        # k0 should have been evicted (oldest)
        assert await backend.get("k0") is None
        assert await backend.get("k1") is not None
        assert backend.size == 3

    @pytest.mark.asyncio()
    async def test_lru_access_updates_order(self) -> None:
        backend = InMemoryCacheBackend(max_size=3, default_ttl=3600)
        for i in range(3):
            await backend.set(f"k{i}", CacheEntry(key=f"k{i}", response_data={"i": i}))
        # Access k0 to make it recently used
        await backend.get("k0")
        # Add k3 — should evict k1 (least recently used)
        await backend.set("k3", CacheEntry(key="k3", response_data={"i": 3}))
        assert await backend.get("k0") is not None  # still there
        assert await backend.get("k1") is None  # evicted
        assert await backend.get("k3") is not None  # just added

    @pytest.mark.asyncio()
    async def test_ttl_expiration(self) -> None:
        backend = InMemoryCacheBackend(max_size=10, default_ttl=1)
        entry = CacheEntry(
            key="k1",
            response_data={"x": 1},
            created_at=time.time() - 2,  # already expired
        )
        await backend.set("k1", entry, ttl=1)
        result = await backend.get("k1")
        assert result is None

    @pytest.mark.asyncio()
    async def test_ttl_override(self, memory_backend: InMemoryCacheBackend) -> None:
        entry = CacheEntry(key="k1", response_data={"x": 1})
        await memory_backend.set("k1", entry, ttl=999)
        result = await memory_backend.get("k1")
        assert result is not None
        assert result.ttl == 999

    @pytest.mark.asyncio()
    async def test_stats(self, memory_backend: InMemoryCacheBackend) -> None:
        entry = CacheEntry(key="k1", response_data={"x": 1})
        await memory_backend.set("k1", entry)
        await memory_backend.get("k1")  # hit
        await memory_backend.get("missing")  # miss
        stats = memory_backend.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["backend"] == "memory"

    @pytest.mark.asyncio()
    async def test_overwrite_existing_key(self, memory_backend: InMemoryCacheBackend) -> None:
        await memory_backend.set("k1", CacheEntry(key="k1", response_data={"v": 1}))
        await memory_backend.set("k1", CacheEntry(key="k1", response_data={"v": 2}))
        result = await memory_backend.get("k1")
        assert result is not None
        assert result.response_data == {"v": 2}
        assert memory_backend.size == 1

    @pytest.mark.asyncio()
    async def test_delete_nonexistent(self, memory_backend: InMemoryCacheBackend) -> None:
        # Should not raise
        await memory_backend.delete("nope")


# ===================================================================
# RedisCacheBackend Tests (mocked)
# ===================================================================


class TestRedisCacheBackend:
    """Tests for the Redis cache backend with a mocked client."""

    @pytest.fixture()
    def mock_redis(self) -> AsyncMock:
        client = AsyncMock()
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock()
        client.setex = AsyncMock()
        client.delete = AsyncMock()
        client.scan = AsyncMock(return_value=(0, []))
        client.close = AsyncMock()
        return client

    @pytest.fixture()
    def redis_backend(self, mock_redis: AsyncMock) -> Any:
        from routerbot.cache.redis import RedisCacheBackend

        return RedisCacheBackend(
            redis_url="redis://localhost:6379/0",
            default_ttl=3600,
            namespace="test",
            redis_client=mock_redis,
        )

    @pytest.mark.asyncio()
    async def test_get_miss(self, redis_backend: Any, mock_redis: AsyncMock) -> None:
        result = await redis_backend.get("missing")
        assert result is None
        assert redis_backend.misses == 1

    @pytest.mark.asyncio()
    async def test_set_with_ttl(self, redis_backend: Any, mock_redis: AsyncMock) -> None:
        entry = CacheEntry(key="k1", response_data={"x": 1}, model="gpt-4")
        await redis_backend.set("k1", entry, ttl=120)
        mock_redis.setex.assert_awaited_once()
        args = mock_redis.setex.call_args[0]
        assert args[1] == 120  # TTL

    @pytest.mark.asyncio()
    async def test_set_without_ttl(self, redis_backend: Any, mock_redis: AsyncMock) -> None:
        from routerbot.cache.redis import RedisCacheBackend

        backend = RedisCacheBackend(
            redis_url="redis://localhost",
            default_ttl=None,
            namespace="test",
            redis_client=mock_redis,
        )
        entry = CacheEntry(key="k1", response_data={"x": 1})
        await backend.set("k1", entry, ttl=None)
        mock_redis.set.assert_awaited()

    @pytest.mark.asyncio()
    async def test_get_hit(self, redis_backend: Any, mock_redis: AsyncMock) -> None:
        import json

        stored = {
            "key": "k1",
            "response_data": {"x": 1},
            "model": "gpt-4",
            "created_at": time.time(),
            "ttl": 3600,
            "metadata": {},
        }
        mock_redis.get = AsyncMock(return_value=json.dumps(stored))
        result = await redis_backend.get("k1")
        assert result is not None
        assert result.response_data == {"x": 1}
        assert redis_backend.hits == 1

    @pytest.mark.asyncio()
    async def test_delete(self, redis_backend: Any, mock_redis: AsyncMock) -> None:
        await redis_backend.delete("k1")
        mock_redis.delete.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_clear(self, redis_backend: Any, mock_redis: AsyncMock) -> None:
        mock_redis.scan = AsyncMock(return_value=(0, ["test:cache:k1", "test:cache:k2"]))
        await redis_backend.clear()
        mock_redis.delete.assert_awaited()

    @pytest.mark.asyncio()
    async def test_close(self, redis_backend: Any, mock_redis: AsyncMock) -> None:
        await redis_backend.close()
        mock_redis.close.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_get_error_returns_none(self, redis_backend: Any, mock_redis: AsyncMock) -> None:
        mock_redis.get = AsyncMock(side_effect=ConnectionError("offline"))
        result = await redis_backend.get("k1")
        assert result is None
        assert redis_backend.misses == 1

    @pytest.mark.asyncio()
    async def test_set_error_silent(self, redis_backend: Any, mock_redis: AsyncMock) -> None:
        mock_redis.setex = AsyncMock(side_effect=ConnectionError("offline"))
        entry = CacheEntry(key="k1", response_data={"x": 1})
        # Should not raise
        await redis_backend.set("k1", entry)

    @pytest.mark.asyncio()
    async def test_stats(self, redis_backend: Any) -> None:
        stats = redis_backend.stats
        assert stats["backend"] == "redis"
        assert stats["namespace"] == "test"

    @pytest.mark.asyncio()
    async def test_make_key_prefix(self, redis_backend: Any) -> None:
        key = redis_backend._make_key("some_hash")
        assert key == "test:cache:some_hash"

    @pytest.mark.asyncio()
    async def test_make_key_already_prefixed(self, redis_backend: Any) -> None:
        key = redis_backend._make_key("test:cache:abc")
        assert key == "test:cache:abc"


# ===================================================================
# ResponseCacheManager Tests
# ===================================================================


class TestResponseCacheManager:
    """Tests for the high-level cache manager."""

    @pytest.mark.asyncio()
    async def test_store_and_lookup(
        self,
        cache_manager: ResponseCacheManager,
        sample_messages: list[dict[str, Any]],
        sample_response_data: dict[str, Any],
    ) -> None:
        await cache_manager.store(
            model="gpt-4",
            messages=sample_messages,
            response_data=sample_response_data,
        )
        result = await cache_manager.lookup(
            model="gpt-4",
            messages=sample_messages,
        )
        assert result is not None
        assert result.response_data == sample_response_data

    @pytest.mark.asyncio()
    async def test_lookup_miss(
        self,
        cache_manager: ResponseCacheManager,
        sample_messages: list[dict[str, Any]],
    ) -> None:
        result = await cache_manager.lookup(
            model="gpt-4",
            messages=sample_messages,
        )
        assert result is None

    @pytest.mark.asyncio()
    async def test_skip_streaming(
        self,
        cache_manager: ResponseCacheManager,
        sample_messages: list[dict[str, Any]],
        sample_response_data: dict[str, Any],
    ) -> None:
        await cache_manager.store(
            model="gpt-4",
            messages=sample_messages,
            response_data=sample_response_data,
        )
        result = await cache_manager.lookup(
            model="gpt-4",
            messages=sample_messages,
            stream=True,
        )
        assert result is None  # skipped for streaming

    @pytest.mark.asyncio()
    async def test_no_skip_streaming_when_disabled(
        self,
        memory_backend: InMemoryCacheBackend,
        sample_messages: list[dict[str, Any]],
        sample_response_data: dict[str, Any],
    ) -> None:
        manager = ResponseCacheManager(backend=memory_backend, skip_streaming=False, namespace="test")
        await manager.store(
            model="gpt-4",
            messages=sample_messages,
            response_data=sample_response_data,
        )
        result = await manager.lookup(
            model="gpt-4",
            messages=sample_messages,
            stream=True,
        )
        assert result is not None

    @pytest.mark.asyncio()
    async def test_cache_control_no_cache(
        self,
        cache_manager: ResponseCacheManager,
        sample_messages: list[dict[str, Any]],
        sample_response_data: dict[str, Any],
    ) -> None:
        await cache_manager.store(
            model="gpt-4",
            messages=sample_messages,
            response_data=sample_response_data,
        )
        result = await cache_manager.lookup(
            model="gpt-4",
            messages=sample_messages,
            cache_control="no-cache",
        )
        assert result is None

    @pytest.mark.asyncio()
    async def test_disabled(
        self,
        cache_manager: ResponseCacheManager,
        sample_messages: list[dict[str, Any]],
        sample_response_data: dict[str, Any],
    ) -> None:
        cache_manager.enabled = False
        await cache_manager.store(
            model="gpt-4",
            messages=sample_messages,
            response_data=sample_response_data,
        )
        result = await cache_manager.lookup(
            model="gpt-4",
            messages=sample_messages,
        )
        assert result is None

    @pytest.mark.asyncio()
    async def test_invalidate(
        self,
        cache_manager: ResponseCacheManager,
        sample_messages: list[dict[str, Any]],
        sample_response_data: dict[str, Any],
    ) -> None:
        await cache_manager.store(
            model="gpt-4",
            messages=sample_messages,
            response_data=sample_response_data,
        )
        await cache_manager.invalidate(
            model="gpt-4",
            messages=sample_messages,
        )
        result = await cache_manager.lookup(
            model="gpt-4",
            messages=sample_messages,
        )
        assert result is None

    @pytest.mark.asyncio()
    async def test_clear(
        self,
        cache_manager: ResponseCacheManager,
        sample_messages: list[dict[str, Any]],
        sample_response_data: dict[str, Any],
    ) -> None:
        await cache_manager.store(
            model="gpt-4",
            messages=sample_messages,
            response_data=sample_response_data,
        )
        await cache_manager.clear()
        result = await cache_manager.lookup(
            model="gpt-4",
            messages=sample_messages,
        )
        assert result is None

    @pytest.mark.asyncio()
    async def test_different_temperature_different_entry(
        self,
        cache_manager: ResponseCacheManager,
        sample_messages: list[dict[str, Any]],
    ) -> None:
        data1 = {"choices": [{"message": {"content": "T=0"}}]}
        data2 = {"choices": [{"message": {"content": "T=1"}}]}

        await cache_manager.store(
            model="gpt-4",
            messages=sample_messages,
            response_data=data1,
            temperature=0.0,
        )
        await cache_manager.store(
            model="gpt-4",
            messages=sample_messages,
            response_data=data2,
            temperature=1.0,
        )

        r1 = await cache_manager.lookup(model="gpt-4", messages=sample_messages, temperature=0.0)
        r2 = await cache_manager.lookup(model="gpt-4", messages=sample_messages, temperature=1.0)
        assert r1 is not None
        assert r2 is not None
        assert r1.response_data != r2.response_data

    @pytest.mark.asyncio()
    async def test_backend_property(
        self,
        cache_manager: ResponseCacheManager,
        memory_backend: InMemoryCacheBackend,
    ) -> None:
        assert cache_manager.backend is memory_backend

    @pytest.mark.asyncio()
    async def test_store_with_metadata(
        self,
        cache_manager: ResponseCacheManager,
        sample_messages: list[dict[str, Any]],
    ) -> None:
        await cache_manager.store(
            model="gpt-4",
            messages=sample_messages,
            response_data={"x": 1},
            metadata={"cost": 0.01, "tokens": 15},
        )
        result = await cache_manager.lookup(model="gpt-4", messages=sample_messages)
        assert result is not None
        assert result.metadata["cost"] == 0.01
