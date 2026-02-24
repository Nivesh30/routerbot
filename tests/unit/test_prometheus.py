"""Tests for Prometheus metrics callback and /metrics endpoint (Task 5.2).

Uses a fresh CollectorRegistry per test to avoid duplicate metric errors.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from prometheus_client import CollectorRegistry

from routerbot.observability.callbacks import (
    RequestEndData,
    RequestErrorData,
    RequestStartData,
)
from routerbot.observability.prometheus import (
    PrometheusCallback,
    create_metrics,
    metrics_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def registry():
    """Fresh registry for each test."""
    return CollectorRegistry()


@pytest.fixture
def callback(registry):
    """PrometheusCallback with isolated registry."""
    return PrometheusCallback(registry=registry)


# ---------------------------------------------------------------------------
# Test: Metric creation
# ---------------------------------------------------------------------------


class TestMetricCreation:
    """Metrics are created correctly."""

    def test_all_metrics_created(self, registry):
        metrics = create_metrics(registry=registry)
        expected = {
            "request_total",
            "request_duration",
            "tokens_total",
            "cost_total",
            "errors_total",
            "active_requests",
            "cache_hits",
            "rate_limit_hits",
            "provider_health",
        }
        assert set(metrics) == expected


# ---------------------------------------------------------------------------
# Test: PrometheusCallback lifecycle
# ---------------------------------------------------------------------------


class TestPrometheusCallback:
    """Callback records correct metrics."""

    async def test_request_start_increments_active(self, callback, registry):
        data = RequestStartData(request_id="r1", model="gpt-4")
        await callback.on_request_start(data)
        assert registry.get_sample_value("routerbot_active_requests") == 1.0

    async def test_request_end_records_metrics(self, callback, registry):
        # Start first to increment active
        await callback.on_request_start(RequestStartData(request_id="r1", model="gpt-4"))

        data = RequestEndData(
            request_id="r1",
            model="gpt-4",
            provider="openai",
            tokens_prompt=100,
            tokens_completion=50,
            cost=0.005,
            latency_ms=1500.0,
        )
        await callback.on_request_end(data)

        # Request count
        assert registry.get_sample_value(
            "routerbot_request_total",
            {"model": "gpt-4", "provider": "openai", "status": "success"},
        ) == 1.0

        # Tokens
        assert registry.get_sample_value(
            "routerbot_tokens_total",
            {"model": "gpt-4", "provider": "openai", "type": "prompt"},
        ) == 100.0
        assert registry.get_sample_value(
            "routerbot_tokens_total",
            {"model": "gpt-4", "provider": "openai", "type": "completion"},
        ) == 50.0

        # Cost
        assert registry.get_sample_value(
            "routerbot_cost_total",
            {"model": "gpt-4", "provider": "openai"},
        ) == 0.005

        # Active requests back to 0
        assert registry.get_sample_value("routerbot_active_requests") == 0.0

    async def test_request_end_skips_zero_tokens(self, callback, registry):
        """Zero tokens/cost should not increment counters."""
        data = RequestEndData(
            request_id="r1",
            model="gpt-4",
            provider="openai",
            tokens_prompt=0,
            tokens_completion=0,
            cost=0.0,
            latency_ms=100.0,
        )
        await callback.on_request_end(data)

        # Tokens should not be recorded
        assert registry.get_sample_value(
            "routerbot_tokens_total",
            {"model": "gpt-4", "provider": "openai", "type": "prompt"},
        ) is None

    async def test_request_error_records_error_metrics(self, callback, registry):
        await callback.on_request_start(RequestStartData(request_id="r1", model="gpt-4"))

        data = RequestErrorData(
            request_id="r1",
            model="gpt-4",
            provider="openai",
            error="timeout",
            error_type="TimeoutError",
        )
        await callback.on_request_error(data)

        assert registry.get_sample_value(
            "routerbot_request_total",
            {"model": "gpt-4", "provider": "openai", "status": "error"},
        ) == 1.0

        assert registry.get_sample_value(
            "routerbot_errors_total",
            {"model": "gpt-4", "provider": "openai", "error_type": "TimeoutError"},
        ) == 1.0

        assert registry.get_sample_value("routerbot_active_requests") == 0.0

    async def test_request_error_unknown_type(self, callback, registry):
        """Missing error_type defaults to 'unknown'."""
        data = RequestErrorData(
            request_id="r1",
            model="gpt-4",
            provider="openai",
        )
        await callback.on_request_error(data)

        assert registry.get_sample_value(
            "routerbot_errors_total",
            {"model": "gpt-4", "provider": "openai", "error_type": "unknown"},
        ) == 1.0

    async def test_latency_histogram(self, callback, registry):
        """Latency is recorded in seconds (not ms)."""
        data = RequestEndData(
            request_id="r1",
            model="gpt-4",
            provider="openai",
            latency_ms=2500.0,
        )
        await callback.on_request_end(data)

        # 2500ms = 2.5s, bucket le="5.0" should have count 1
        assert registry.get_sample_value(
            "routerbot_request_duration_seconds_bucket",
            {"model": "gpt-4", "provider": "openai", "le": "5.0"},
        ) == 1.0


# ---------------------------------------------------------------------------
# Test: Convenience methods
# ---------------------------------------------------------------------------


class TestConvenienceMethods:
    """Cache, rate limit, and provider health helpers."""

    def test_cache_hit(self, callback, registry):
        callback.record_cache_hit()
        assert registry.get_sample_value(
            "routerbot_cache_hits_total", {"result": "hit"},
        ) == 1.0

    def test_cache_miss(self, callback, registry):
        callback.record_cache_miss()
        assert registry.get_sample_value(
            "routerbot_cache_hits_total", {"result": "miss"},
        ) == 1.0

    def test_rate_limit(self, callback, registry):
        callback.record_rate_limit("gpt-4")
        assert registry.get_sample_value(
            "routerbot_rate_limit_hits_total", {"model": "gpt-4"},
        ) == 1.0

    def test_provider_health_healthy(self, callback, registry):
        callback.set_provider_health("openai", healthy=True)
        assert registry.get_sample_value(
            "routerbot_provider_health", {"provider": "openai"},
        ) == 1.0

    def test_provider_health_unhealthy(self, callback, registry):
        callback.set_provider_health("openai", healthy=False)
        assert registry.get_sample_value(
            "routerbot_provider_health", {"provider": "openai"},
        ) == 0.0


# ---------------------------------------------------------------------------
# Test: metrics_response
# ---------------------------------------------------------------------------


class TestMetricsResponse:
    """The metrics_response helper returns valid Prometheus text."""

    def test_returns_bytes(self, callback, registry):
        body = metrics_response(registry)
        assert isinstance(body, bytes)

    def test_contains_metric_names(self, callback, registry):
        # Fire some events so metrics are populated
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            callback.on_request_start(RequestStartData(request_id="r1", model="gpt-4")),
        )
        body = metrics_response(registry).decode()
        assert "routerbot_active_requests" in body


# ---------------------------------------------------------------------------
# Test: /metrics endpoint
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    """GET /metrics returns Prometheus exposition format."""

    async def test_metrics_endpoint(self):
        from routerbot.core.config_models import RouterBotConfig
        from routerbot.proxy.app import create_app

        config = RouterBotConfig()
        app = create_app(config=config)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/metrics")

        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        # Should contain at least some standard process metrics
        # or our custom metrics names
        body = resp.text
        assert "routerbot" in body or "process" in body or "python" in body
