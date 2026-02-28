"""Tests for the resilience & HA module (Task 8E)."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC
from typing import Any

import pytest

from routerbot.core.resilience.bulkhead import (
    Bulkhead,
    BulkheadFullError,
    BulkheadManager,
)
from routerbot.core.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
)
from routerbot.core.resilience.degradation import DegradationManager
from routerbot.core.resilience.models import (
    BulkheadConfig,
    BulkheadStats,
    CircuitBreakerConfig,
    CircuitBreakerSnapshot,
    CircuitState,
    DegradationLevel,
    DegradationPolicy,
    DegradationStatus,
    ProviderRegion,
    QueuedRequest,
    Region,
    RegionRoutingConfig,
    RequestQueueConfig,
    RequestQueueStats,
    ResilienceConfig,
)
from routerbot.core.resilience.region import RegionRouter, haversine
from routerbot.core.resilience.request_queue import (
    RequestQueue,
    RequestQueueManager,
)

UTC = UTC


# ═════════════════════════════════════════════════════════════════════
# Models
# ═════════════════════════════════════════════════════════════════════


class TestModels:
    """Test Pydantic models."""

    def test_circuit_state_enum(self) -> None:
        assert CircuitState.CLOSED == "closed"
        assert CircuitState.HALF_OPEN == "half_open"

    def test_circuit_breaker_config_defaults(self) -> None:
        cfg = CircuitBreakerConfig()
        assert cfg.failure_threshold == 5
        assert cfg.recovery_timeout == 30.0
        assert cfg.half_open_max_calls == 3
        assert cfg.success_threshold == 2

    def test_circuit_breaker_snapshot(self) -> None:
        snap = CircuitBreakerSnapshot(name="test", state=CircuitState.CLOSED)
        assert snap.failure_count == 0

    def test_queued_request_expiry(self) -> None:
        item = QueuedRequest(
            request_id="q-1",
            provider="test",
            ttl_seconds=0.01,
        )
        time.sleep(0.02)
        assert item.is_expired

    def test_queued_request_not_expired(self) -> None:
        item = QueuedRequest(
            request_id="q-1",
            provider="test",
            ttl_seconds=60,
        )
        assert not item.is_expired

    def test_request_queue_config_defaults(self) -> None:
        cfg = RequestQueueConfig()
        assert cfg.max_size == 1000
        assert cfg.default_ttl == 30.0

    def test_request_queue_stats(self) -> None:
        stats = RequestQueueStats(provider="test")
        assert stats.depth == 0
        assert stats.total_enqueued == 0

    def test_bulkhead_config_defaults(self) -> None:
        cfg = BulkheadConfig()
        assert cfg.max_concurrent == 50
        assert cfg.max_wait_seconds == 5.0

    def test_bulkhead_stats(self) -> None:
        stats = BulkheadStats(provider="test", max_concurrent=10)
        assert stats.active == 0

    def test_region_model(self) -> None:
        r = Region(name="us-east-1", latitude=39.0, longitude=-77.0)
        assert r.name == "us-east-1"

    def test_provider_region_model(self) -> None:
        pr = ProviderRegion(provider="openai/gpt-4o", region="us-east-1")
        assert pr.healthy is True
        assert pr.weight == 1.0

    def test_region_routing_config_defaults(self) -> None:
        cfg = RegionRoutingConfig()
        assert cfg.enabled is True
        assert cfg.failover_enabled is True

    def test_degradation_level_enum(self) -> None:
        assert DegradationLevel.NORMAL == "normal"
        assert DegradationLevel.EMERGENCY == "emergency"

    def test_degradation_policy_defaults(self) -> None:
        p = DegradationPolicy()
        assert p.level == DegradationLevel.NORMAL
        assert p.reject_new_requests is False

    def test_degradation_status(self) -> None:
        s = DegradationStatus(provider="test", level=DegradationLevel.DEGRADED, reason="test")
        assert s.provider == "test"
        assert s.level == DegradationLevel.DEGRADED

    def test_resilience_config_defaults(self) -> None:
        cfg = ResilienceConfig()
        assert cfg.enabled is True
        assert cfg.circuit_breaker.failure_threshold == 5


# ═════════════════════════════════════════════════════════════════════
# Circuit Breaker
# ═════════════════════════════════════════════════════════════════════


class TestCircuitBreaker:
    """Test the CircuitBreaker state machine."""

    async def test_starts_closed(self) -> None:
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    async def test_allows_when_closed(self) -> None:
        cb = CircuitBreaker("test")
        assert await cb.allow_request() is True

    async def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
        for _ in range(3):
            await cb.record_failure()
        assert cb.state == CircuitState.OPEN

    async def test_rejects_when_open(self) -> None:
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=2))
        await cb.record_failure()
        await cb.record_failure()
        assert await cb.allow_request() is False

    async def test_transitions_to_half_open(self) -> None:
        cb = CircuitBreaker(
            "test",
            CircuitBreakerConfig(
                failure_threshold=2,
                recovery_timeout=0.05,
            ),
        )
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.06)
        assert cb.state == CircuitState.HALF_OPEN

    async def test_half_open_allows_limited_probes(self) -> None:
        cb = CircuitBreaker(
            "test",
            CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout=0.01,
                half_open_max_calls=2,
            ),
        )
        await cb.record_failure()
        await asyncio.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

        assert await cb.allow_request() is True
        assert await cb.allow_request() is True
        assert await cb.allow_request() is False

    async def test_half_open_closes_on_success(self) -> None:
        cb = CircuitBreaker(
            "test",
            CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout=0.01,
                success_threshold=2,
            ),
        )
        await cb.record_failure()
        await asyncio.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

        await cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN  # still half-open, need 2
        await cb.record_success()
        assert cb.state == CircuitState.CLOSED

    async def test_half_open_reopens_on_failure(self) -> None:
        cb = CircuitBreaker(
            "test",
            CircuitBreakerConfig(
                failure_threshold=1,
                recovery_timeout=0.01,
            ),
        )
        await cb.record_failure()
        await asyncio.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

        await cb.record_failure()
        assert cb.state == CircuitState.OPEN

    async def test_success_resets_failure_count(self) -> None:
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))
        await cb.record_failure()
        await cb.record_failure()
        await cb.record_success()
        await cb.record_failure()
        # Only 1 failure after reset, not 3
        assert cb.state == CircuitState.CLOSED

    async def test_excluded_exception(self) -> None:
        cb = CircuitBreaker(
            "test",
            CircuitBreakerConfig(
                failure_threshold=1,
                excluded_exceptions=["ValueError"],
            ),
        )
        await cb.record_failure(ValueError("bad input"))
        assert cb.state == CircuitState.CLOSED

    async def test_non_excluded_exception(self) -> None:
        cb = CircuitBreaker(
            "test",
            CircuitBreakerConfig(
                failure_threshold=1,
                excluded_exceptions=["ValueError"],
            ),
        )
        await cb.record_failure(RuntimeError("timeout"))
        assert cb.state == CircuitState.OPEN

    async def test_reset_closes_circuit(self) -> None:
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=1))
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN
        await cb.reset()
        assert cb.state == CircuitState.CLOSED

    async def test_snapshot(self) -> None:
        cb = CircuitBreaker("test")
        snap = cb.snapshot()
        assert snap.name == "test"
        assert snap.state == CircuitState.CLOSED
        assert snap.failure_count == 0


class TestCircuitBreakerRegistry:
    """Test the CircuitBreakerRegistry."""

    async def test_register_and_get(self) -> None:
        reg = CircuitBreakerRegistry()
        cb = reg.register("provider-a")
        assert reg.get("provider-a") is cb

    async def test_auto_creates_on_get(self) -> None:
        reg = CircuitBreakerRegistry()
        cb = reg.get("new-provider")
        assert cb.name == "new-provider"
        assert cb.state == CircuitState.CLOSED

    async def test_override_config(self) -> None:
        reg = CircuitBreakerRegistry()
        reg.set_override("fast", CircuitBreakerConfig(failure_threshold=1))
        cb = reg.register("fast")
        assert cb.config.failure_threshold == 1

    async def test_all_snapshots(self) -> None:
        reg = CircuitBreakerRegistry()
        reg.register("a")
        reg.register("b")
        snaps = reg.all_snapshots()
        assert len(snaps) == 2

    async def test_all_open(self) -> None:
        reg = CircuitBreakerRegistry(CircuitBreakerConfig(failure_threshold=1))
        cb = reg.register("faulty")
        await cb.record_failure()
        assert reg.all_open() == ["faulty"]

    async def test_summary(self) -> None:
        reg = CircuitBreakerRegistry()
        reg.register("a")
        reg.register("b")
        s = reg.summary()
        assert s["total"] == 2
        assert s["states"]["closed"] == 2

    async def test_reset_all(self) -> None:
        reg = CircuitBreakerRegistry(CircuitBreakerConfig(failure_threshold=1))
        for name in ("a", "b"):
            cb = reg.register(name)
            await cb.record_failure()
        assert len(reg.all_open()) == 2
        await reg.reset_all()
        assert len(reg.all_open()) == 0


# ═════════════════════════════════════════════════════════════════════
# Request Queue
# ═════════════════════════════════════════════════════════════════════


class TestRequestQueue:
    """Test the per-provider RequestQueue."""

    async def test_enqueue_and_drain(self) -> None:
        q = RequestQueue("provider-a")
        item = await q.enqueue({"model": "gpt-4"})
        assert item is not None
        assert q.depth == 1

        drained = await q.drain()
        assert len(drained) == 1
        assert drained[0].request_id == item.request_id

    async def test_queue_full_rejection(self) -> None:
        q = RequestQueue("a", RequestQueueConfig(max_size=2))
        await q.enqueue({"x": 1})
        await q.enqueue({"x": 2})
        result = await q.enqueue({"x": 3})
        assert result is None
        assert q.stats().total_rejected == 1

    async def test_expired_items_skipped(self) -> None:
        q = RequestQueue("a", RequestQueueConfig(default_ttl=0.01))
        await q.enqueue({"x": 1})
        await asyncio.sleep(0.02)
        drained = await q.drain()
        assert len(drained) == 0
        assert q.stats().total_expired == 1

    async def test_custom_ttl(self) -> None:
        q = RequestQueue("a")
        item = await q.enqueue({"x": 1}, ttl=60.0)
        assert item is not None
        assert item.ttl_seconds == 60.0

    async def test_drain_all(self) -> None:
        q = RequestQueue("a")
        for i in range(5):
            await q.enqueue({"x": i})
        drained = await q.drain_all()
        assert len(drained) == 5

    async def test_clear(self) -> None:
        q = RequestQueue("a")
        for i in range(3):
            await q.enqueue({"x": i})
        dropped = await q.clear()
        assert dropped == 3
        assert q.is_empty

    async def test_stats(self) -> None:
        q = RequestQueue("a")
        await q.enqueue({"x": 1})
        await q.drain()
        stats = q.stats()
        assert stats.total_enqueued == 1
        assert stats.total_drained == 1

    async def test_disabled_queue(self) -> None:
        q = RequestQueue("a", RequestQueueConfig(enabled=False))
        result = await q.enqueue({"x": 1})
        assert result is None

    async def test_is_full(self) -> None:
        q = RequestQueue("a", RequestQueueConfig(max_size=1))
        await q.enqueue({"x": 1})
        assert q.is_full

    async def test_is_empty(self) -> None:
        q = RequestQueue("a")
        assert q.is_empty


class TestRequestQueueManager:
    """Test the RequestQueueManager."""

    async def test_get_or_create(self) -> None:
        mgr = RequestQueueManager()
        q = mgr.get("provider-a")
        assert q.provider == "provider-a"
        assert mgr.get("provider-a") is q

    async def test_enqueue_via_manager(self) -> None:
        mgr = RequestQueueManager()
        item = await mgr.enqueue("provider-a", {"x": 1})
        assert item is not None
        assert mgr.total_depth() == 1

    async def test_drain_via_manager(self) -> None:
        mgr = RequestQueueManager()
        await mgr.enqueue("a", {"x": 1})
        await mgr.enqueue("a", {"x": 2})
        drained = await mgr.drain("a")
        assert len(drained) == 2

    async def test_all_stats(self) -> None:
        mgr = RequestQueueManager()
        await mgr.enqueue("a", {"x": 1})
        await mgr.enqueue("b", {"x": 1})
        stats = mgr.all_stats()
        assert len(stats) == 2

    async def test_clear_all(self) -> None:
        mgr = RequestQueueManager()
        await mgr.enqueue("a", {"x": 1})
        await mgr.enqueue("b", {"x": 1})
        total = await mgr.clear_all()
        assert total == 2
        assert mgr.total_depth() == 0


# ═════════════════════════════════════════════════════════════════════
# Bulkhead
# ═════════════════════════════════════════════════════════════════════


class TestBulkhead:
    """Test the Bulkhead concurrency limiter."""

    async def test_allows_within_limit(self) -> None:
        bh = Bulkhead("a", BulkheadConfig(max_concurrent=2, max_wait_seconds=1.0))
        async with bh.acquire():
            assert bh._active == 1
        assert bh._active == 0

    async def test_concurrent_requests(self) -> None:
        bh = Bulkhead("a", BulkheadConfig(max_concurrent=3, max_wait_seconds=1.0))
        acquired = []

        async def work() -> None:
            async with bh.acquire():
                acquired.append(True)
                await asyncio.sleep(0.05)

        await asyncio.gather(work(), work(), work())
        assert len(acquired) == 3

    async def test_timeout_raises_bulkhead_full(self) -> None:
        bh = Bulkhead("a", BulkheadConfig(max_concurrent=1, max_wait_seconds=0.05))
        # Hold the semaphore
        await bh._semaphore.acquire()
        bh._active = 1

        with pytest.raises(BulkheadFullError, match="a"):
            async with bh.acquire():
                pass  # Should not reach here

    async def test_stats(self) -> None:
        bh = Bulkhead("a", BulkheadConfig(max_concurrent=5, max_wait_seconds=1.0))
        async with bh.acquire():
            stats = bh.stats()
            assert stats.active == 1
            assert stats.max_concurrent == 5
        assert bh.stats().total_accepted == 1

    async def test_rejected_count(self) -> None:
        bh = Bulkhead("a", BulkheadConfig(max_concurrent=1, max_wait_seconds=0.01))
        await bh._semaphore.acquire()
        bh._active = 1

        with pytest.raises(BulkheadFullError):
            async with bh.acquire():
                pass

        assert bh.stats().total_rejected == 1


class TestBulkheadManager:
    """Test the BulkheadManager."""

    async def test_get_or_create(self) -> None:
        mgr = BulkheadManager()
        bh = mgr.get("provider-a")
        assert bh.provider == "provider-a"
        assert mgr.get("provider-a") is bh

    async def test_acquire_via_manager(self) -> None:
        mgr = BulkheadManager()
        async with mgr.acquire("a"):
            assert mgr.total_active() == 1
        assert mgr.total_active() == 0

    async def test_overrides(self) -> None:
        mgr = BulkheadManager(
            overrides={"fast": BulkheadConfig(max_concurrent=5)},
        )
        bh = mgr.get("fast")
        assert bh.config.max_concurrent == 5

    async def test_all_stats(self) -> None:
        mgr = BulkheadManager()
        mgr.get("a")
        mgr.get("b")
        assert len(mgr.all_stats()) == 2

    async def test_summary(self) -> None:
        mgr = BulkheadManager()
        mgr.get("a")
        s = mgr.summary()
        assert s["total_providers"] == 1


# ═════════════════════════════════════════════════════════════════════
# Region Router
# ═════════════════════════════════════════════════════════════════════


def _sample_config() -> RegionRoutingConfig:
    """Build a sample config with US East, US West, and EU West regions."""
    return RegionRoutingConfig(
        regions=[
            Region(name="us-east-1", latitude=39.0, longitude=-77.0),
            Region(name="us-west-2", latitude=46.0, longitude=-120.0),
            Region(name="eu-west-1", latitude=53.0, longitude=-6.0),
        ],
        provider_regions=[
            ProviderRegion(provider="openai/gpt-4o", region="us-east-1", weight=1.0),
            ProviderRegion(provider="openai/gpt-4o", region="us-west-2", weight=0.8),
            ProviderRegion(provider="openai/gpt-4o", region="eu-west-1", weight=0.9),
        ],
        default_region="us-east-1",
        failover_enabled=True,
    )


class TestHaversine:
    """Test the Haversine distance function."""

    def test_same_point(self) -> None:
        assert haversine(0, 0, 0, 0) == 0.0

    def test_known_distance(self) -> None:
        # New York to London: ~5570 km
        d = haversine(40.7, -74.0, 51.5, -0.1)
        assert 5500 < d < 5700

    def test_antipodal(self) -> None:
        # Roughly half the earth circumference
        d = haversine(0, 0, 0, 180)
        assert 20000 < d < 20100


class TestRegionRouter:
    """Test region-aware routing."""

    def test_select_closest_region(self) -> None:
        rr = RegionRouter(_sample_config())
        pr = rr.select_provider("openai/gpt-4o", client_region="us-east-1")
        assert pr is not None
        assert pr.region == "us-east-1"

    def test_select_from_eu(self) -> None:
        rr = RegionRouter(_sample_config())
        pr = rr.select_provider("openai/gpt-4o", client_region="eu-west-1")
        assert pr is not None
        assert pr.region == "eu-west-1"

    def test_select_no_region_returns_highest_weight(self) -> None:
        rr = RegionRouter(_sample_config())
        pr = rr.select_provider("openai/gpt-4o", client_region=None)
        # Falls back to default_region (us-east-1)
        assert pr is not None
        assert pr.region == "us-east-1"

    def test_select_unknown_provider(self) -> None:
        rr = RegionRouter(_sample_config())
        assert rr.select_provider("nonexistent/model") is None

    def test_failover_excludes_failed_region(self) -> None:
        rr = RegionRouter(_sample_config())
        fo = rr.failover("openai/gpt-4o", failed_region="us-east-1", client_region="us-east-1")
        assert fo is not None
        assert fo.region != "us-east-1"
        # Should pick us-west-2 (closer than eu-west-1 from us-east-1)
        assert fo.region == "us-west-2"

    def test_failover_disabled(self) -> None:
        cfg = _sample_config()
        cfg.failover_enabled = False
        rr = RegionRouter(cfg)
        assert rr.failover("openai/gpt-4o", failed_region="us-east-1") is None

    def test_failover_max_distance(self) -> None:
        cfg = _sample_config()
        cfg.max_failover_distance_km = 100.0  # Very short — nothing qualifies
        rr = RegionRouter(cfg)
        fo = rr.failover("openai/gpt-4o", failed_region="us-east-1", client_region="us-east-1")
        assert fo is None

    def test_mark_unhealthy_and_healthy(self) -> None:
        rr = RegionRouter(_sample_config())
        rr.mark_unhealthy("openai/gpt-4o", "us-east-1")
        pr = rr.select_provider("openai/gpt-4o", client_region="us-east-1")
        assert pr is not None
        assert pr.region != "us-east-1"

        rr.mark_healthy("openai/gpt-4o", "us-east-1")
        pr = rr.select_provider("openai/gpt-4o", client_region="us-east-1")
        assert pr is not None
        assert pr.region == "us-east-1"

    def test_healthy_regions(self) -> None:
        rr = RegionRouter(_sample_config())
        assert len(rr.healthy_regions("openai/gpt-4o")) == 3
        rr.mark_unhealthy("openai/gpt-4o", "eu-west-1")
        assert len(rr.healthy_regions("openai/gpt-4o")) == 2

    def test_all_providers_in_region(self) -> None:
        rr = RegionRouter(_sample_config())
        providers = rr.all_providers_in_region("us-east-1")
        assert len(providers) == 1
        assert providers[0].provider == "openai/gpt-4o"

    def test_add_region(self) -> None:
        rr = RegionRouter(_sample_config())
        rr.add_region(Region(name="ap-northeast-1", latitude=35.7, longitude=139.7))
        assert "ap-northeast-1" in rr._regions

    def test_add_provider_region(self) -> None:
        rr = RegionRouter(_sample_config())
        rr.add_provider_region(ProviderRegion(provider="anthropic/claude", region="us-east-1"))
        assert rr.select_provider("anthropic/claude", "us-east-1") is not None

    def test_summary(self) -> None:
        rr = RegionRouter(_sample_config())
        s = rr.summary()
        assert s["regions"] == ["us-east-1", "us-west-2", "eu-west-1"]
        assert s["deployments"] == 3
        assert s["healthy"] == 3

    def test_all_unhealthy_returns_none(self) -> None:
        rr = RegionRouter(_sample_config())
        for region in ("us-east-1", "us-west-2", "eu-west-1"):
            rr.mark_unhealthy("openai/gpt-4o", region)
        assert rr.select_provider("openai/gpt-4o", "us-east-1") is None

    def test_no_region_no_default_returns_highest_weight(self) -> None:
        cfg = RegionRoutingConfig(
            regions=[Region(name="us-east-1", latitude=39.0, longitude=-77.0)],
            provider_regions=[
                ProviderRegion(provider="a", region="us-east-1", weight=0.5),
                ProviderRegion(provider="a", region="us-east-1", weight=1.0),
            ],
            default_region="",
        )
        rr = RegionRouter(cfg)
        pr = rr.select_provider("a")
        assert pr is not None
        assert pr.weight == 1.0


# ═════════════════════════════════════════════════════════════════════
# Degradation Manager
# ═════════════════════════════════════════════════════════════════════


class TestDegradationManager:
    """Test the DegradationManager."""

    def test_starts_normal(self) -> None:
        dm = DegradationManager()
        assert dm.global_level == DegradationLevel.NORMAL

    def test_set_global_level(self) -> None:
        dm = DegradationManager()
        dm.set_global_level(DegradationLevel.DEGRADED, reason="test")
        assert dm.global_level == DegradationLevel.DEGRADED
        assert dm.global_status.reason == "test"

    def test_get_policy(self) -> None:
        dm = DegradationManager()
        policy = dm.get_policy(DegradationLevel.EMERGENCY)
        assert policy.reject_new_requests is True

    def test_get_default_policy(self) -> None:
        dm = DegradationManager()
        policy = dm.get_policy()
        assert policy.level == DegradationLevel.NORMAL
        assert policy.reject_new_requests is False

    def test_set_provider_level(self) -> None:
        dm = DegradationManager()
        dm.set_provider_level("openai", DegradationLevel.LIMITED)
        assert dm.get_provider_level("openai") == DegradationLevel.LIMITED

    def test_clear_provider(self) -> None:
        dm = DegradationManager()
        dm.set_provider_level("openai", DegradationLevel.DEGRADED)
        dm.clear_provider("openai")
        assert dm.get_provider_level("openai") == DegradationLevel.NORMAL

    def test_auto_escalate_normal(self) -> None:
        dm = DegradationManager()
        level = dm.auto_escalate(total_providers=10, unhealthy_count=1)
        assert level == DegradationLevel.NORMAL

    def test_auto_escalate_degraded(self) -> None:
        dm = DegradationManager()
        level = dm.auto_escalate(total_providers=10, unhealthy_count=2)
        assert level == DegradationLevel.DEGRADED

    def test_auto_escalate_limited(self) -> None:
        dm = DegradationManager()
        level = dm.auto_escalate(total_providers=10, unhealthy_count=5)
        assert level == DegradationLevel.LIMITED

    def test_auto_escalate_emergency(self) -> None:
        dm = DegradationManager()
        level = dm.auto_escalate(total_providers=10, unhealthy_count=8)
        assert level == DegradationLevel.EMERGENCY

    def test_auto_escalate_zero_providers(self) -> None:
        dm = DegradationManager()
        level = dm.auto_escalate(total_providers=0, unhealthy_count=0)
        assert level == DegradationLevel.NORMAL

    def test_should_reject_emergency(self) -> None:
        dm = DegradationManager()
        dm.set_global_level(DegradationLevel.EMERGENCY)
        assert dm.should_reject() is True

    def test_should_not_reject_normal(self) -> None:
        dm = DegradationManager()
        assert dm.should_reject() is False

    def test_should_queue_degraded(self) -> None:
        dm = DegradationManager()
        dm.set_global_level(DegradationLevel.DEGRADED)
        assert dm.should_queue() is True

    def test_should_not_queue_normal(self) -> None:
        dm = DegradationManager()
        assert dm.should_queue() is False

    def test_effective_max_tokens_limited(self) -> None:
        dm = DegradationManager()
        dm.set_global_level(DegradationLevel.LIMITED)
        assert dm.effective_max_tokens() == 1000

    def test_effective_max_tokens_normal(self) -> None:
        dm = DegradationManager()
        assert dm.effective_max_tokens() is None

    def test_is_model_allowed_normal(self) -> None:
        dm = DegradationManager()
        assert dm.is_model_allowed("any-model") is True

    def test_is_model_allowed_limited(self) -> None:
        dm = DegradationManager(
            policies={
                DegradationLevel.LIMITED: DegradationPolicy(
                    level=DegradationLevel.LIMITED,
                    allowed_models=["gpt-3.5-turbo"],
                ),
            }
        )
        dm.set_global_level(DegradationLevel.LIMITED)
        assert dm.is_model_allowed("gpt-3.5-turbo") is True
        assert dm.is_model_allowed("gpt-4o") is False

    def test_is_streaming_allowed(self) -> None:
        dm = DegradationManager()
        assert dm.is_streaming_allowed() is True
        dm.set_global_level(DegradationLevel.LIMITED)
        assert dm.is_streaming_allowed() is False

    def test_summary(self) -> None:
        dm = DegradationManager()
        dm.set_provider_level("a", DegradationLevel.DEGRADED)
        s = dm.summary()
        assert s["global_level"] == "normal"
        assert s["provider_count"] == 1

    def test_custom_thresholds(self) -> None:
        dm = DegradationManager(auto_escalate_thresholds=(0.1, 0.3, 0.5))
        level = dm.auto_escalate(total_providers=10, unhealthy_count=1)
        assert level == DegradationLevel.DEGRADED

    def test_should_reject_per_provider(self) -> None:
        dm = DegradationManager()
        dm.set_provider_level("openai", DegradationLevel.EMERGENCY)
        assert dm.should_reject("openai") is True
        assert dm.should_reject("anthropic") is False

    def test_should_queue_per_provider(self) -> None:
        dm = DegradationManager()
        dm.set_provider_level("openai", DegradationLevel.DEGRADED)
        assert dm.should_queue("openai") is True
        assert dm.should_queue("anthropic") is False


# ═════════════════════════════════════════════════════════════════════
# Integration: app startup config
# ═════════════════════════════════════════════════════════════════════


class TestResilienceIntegration:
    """Test that ResilienceConfig can be parsed from dict form."""

    def test_full_config_from_dict(self) -> None:
        raw: dict[str, Any] = {
            "enabled": True,
            "circuit_breaker": {
                "failure_threshold": 10,
                "recovery_timeout": 60,
            },
            "request_queue": {
                "max_size": 500,
                "default_ttl": 15.0,
            },
            "bulkhead_defaults": {
                "max_concurrent": 100,
            },
            "bulkhead_overrides": {
                "slow-provider": {"max_concurrent": 10},
            },
            "region_routing": {
                "enabled": True,
                "regions": [
                    {"name": "us-east-1", "latitude": 39.0, "longitude": -77.0},
                ],
                "provider_regions": [
                    {"provider": "openai/gpt-4o", "region": "us-east-1"},
                ],
                "default_region": "us-east-1",
            },
        }
        cfg = ResilienceConfig(**raw)
        assert cfg.circuit_breaker.failure_threshold == 10
        assert cfg.request_queue.max_size == 500
        assert cfg.bulkhead_defaults.max_concurrent == 100
        assert "slow-provider" in cfg.bulkhead_overrides
        assert cfg.bulkhead_overrides["slow-provider"].max_concurrent == 10
        assert len(cfg.region_routing.regions) == 1
