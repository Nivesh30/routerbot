"""Prometheus metrics callback and ``/metrics`` endpoint.

Metrics exposed:
    - ``routerbot_request_total`` — Counter: total requests (model, provider, status)
    - ``routerbot_request_duration_seconds`` — Histogram: request latency
    - ``routerbot_tokens_total`` — Counter: tokens used (model, provider, type)
    - ``routerbot_cost_total`` — Counter: total cost in USD
    - ``routerbot_errors_total`` — Counter: errors (model, provider, error_type)
    - ``routerbot_active_requests`` — Gauge: in-progress requests
    - ``routerbot_cache_hits_total`` — Counter: cache hits/misses
    - ``routerbot_rate_limit_hits_total`` — Counter: rate limit rejections
    - ``routerbot_provider_health`` — Gauge: provider health (1=healthy, 0=unhealthy)

All metrics are exposed at ``GET /metrics`` in Prometheus text format.
"""

from __future__ import annotations

import logging
from typing import Any

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from routerbot.observability.callbacks import (
    BaseCallback,
    RequestEndData,
    RequestErrorData,
    RequestStartData,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metric definitions (using default registry by default)
# ---------------------------------------------------------------------------


def create_metrics(
    registry: CollectorRegistry | None = None,
) -> dict[str, Any]:
    """Create all Prometheus metrics.

    Parameters
    ----------
    registry:
        A custom :class:`CollectorRegistry`.  When ``None`` (the
        default), metrics are registered in the global
        ``REGISTRY``.

    Returns a dict of metric objects keyed by short name.
    """
    reg = registry or REGISTRY

    return {
        "request_total": Counter(
            "routerbot_request_total",
            "Total LLM requests",
            ["model", "provider", "status"],
            registry=reg,
        ),
        "request_duration": Histogram(
            "routerbot_request_duration_seconds",
            "LLM request latency in seconds",
            ["model", "provider"],
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
            registry=reg,
        ),
        "tokens_total": Counter(
            "routerbot_tokens_total",
            "Total tokens used",
            ["model", "provider", "type"],
            registry=reg,
        ),
        "cost_total": Counter(
            "routerbot_cost_total",
            "Total cost in USD",
            ["model", "provider"],
            registry=reg,
        ),
        "errors_total": Counter(
            "routerbot_errors_total",
            "Total errors",
            ["model", "provider", "error_type"],
            registry=reg,
        ),
        "active_requests": Gauge(
            "routerbot_active_requests",
            "Currently in-progress requests",
            registry=reg,
        ),
        "cache_hits": Counter(
            "routerbot_cache_hits_total",
            "Cache hits and misses",
            ["result"],
            registry=reg,
        ),
        "rate_limit_hits": Counter(
            "routerbot_rate_limit_hits_total",
            "Rate limit rejections",
            ["model"],
            registry=reg,
        ),
        "provider_health": Gauge(
            "routerbot_provider_health",
            "Provider health status (1=healthy, 0=unhealthy)",
            ["provider"],
            registry=reg,
        ),
    }


# ---------------------------------------------------------------------------
# Prometheus callback
# ---------------------------------------------------------------------------


class PrometheusCallback(BaseCallback):
    """Record Prometheus metrics on LLM request lifecycle events.

    Parameters
    ----------
    registry:
        A custom CollectorRegistry.  When ``None``, the default global
        registry is used.  Pass a custom one for tests to avoid
        duplicate registration errors.
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or REGISTRY
        self._metrics = create_metrics(registry=registry)

    @property
    def registry(self) -> CollectorRegistry:
        """Return the registry used by this callback."""
        return self._registry

    # ------------------------------------------------------------------
    # Lifecycle handlers
    # ------------------------------------------------------------------

    async def on_request_start(self, data: RequestStartData) -> None:
        """Increment active request gauge."""
        self._metrics["active_requests"].inc()

    async def on_request_end(self, data: RequestEndData) -> None:
        """Record success metrics: count, latency, tokens, cost."""
        model = data.model
        provider = data.provider

        self._metrics["request_total"].labels(
            model=model, provider=provider, status="success",
        ).inc()

        self._metrics["request_duration"].labels(
            model=model, provider=provider,
        ).observe(data.latency_ms / 1000.0)

        if data.tokens_prompt > 0:
            self._metrics["tokens_total"].labels(
                model=model, provider=provider, type="prompt",
            ).inc(data.tokens_prompt)

        if data.tokens_completion > 0:
            self._metrics["tokens_total"].labels(
                model=model, provider=provider, type="completion",
            ).inc(data.tokens_completion)

        if data.cost > 0:
            self._metrics["cost_total"].labels(
                model=model, provider=provider,
            ).inc(data.cost)

        self._metrics["active_requests"].dec()

    async def on_request_error(self, data: RequestErrorData) -> None:
        """Record error metrics."""
        model = data.model
        provider = data.provider

        self._metrics["request_total"].labels(
            model=model, provider=provider, status="error",
        ).inc()

        self._metrics["errors_total"].labels(
            model=model, provider=provider, error_type=data.error_type or "unknown",
        ).inc()

        self._metrics["active_requests"].dec()

    # ------------------------------------------------------------------
    # Convenience methods for cache/rate-limit events
    # ------------------------------------------------------------------

    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        self._metrics["cache_hits"].labels(result="hit").inc()

    def record_cache_miss(self) -> None:
        """Record a cache miss."""
        self._metrics["cache_hits"].labels(result="miss").inc()

    def record_rate_limit(self, model: str) -> None:
        """Record a rate-limit rejection."""
        self._metrics["rate_limit_hits"].labels(model=model).inc()

    def set_provider_health(self, provider: str, *, healthy: bool) -> None:
        """Set the health gauge for a provider."""
        self._metrics["provider_health"].labels(provider=provider).set(1 if healthy else 0)


# ---------------------------------------------------------------------------
# /metrics endpoint helper
# ---------------------------------------------------------------------------


def metrics_response(registry: CollectorRegistry | None = None) -> bytes:
    """Generate Prometheus text-format exposition.

    Returns raw bytes suitable for an HTTP response with
    ``Content-Type: text/plain; version=0.0.4; charset=utf-8``.
    """
    return generate_latest(registry or REGISTRY)
