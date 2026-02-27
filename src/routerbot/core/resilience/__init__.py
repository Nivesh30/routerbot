"""Resilience & high-availability module for RouterBot.

Provides production-grade fault-tolerance primitives:

* **CircuitBreaker** - three-state (closed/open/half-open) circuit breaker with
  configurable failure thresholds, recovery timeouts, and half-open probe limits.
* **RequestQueue** - async bounded queue that buffers requests while a provider
  is temporarily unavailable, with per-item TTL and back-pressure.
* **Bulkhead** - semaphore-based concurrency isolation so one noisy provider
  cannot exhaust shared resources.
* **RegionRouter** - region-aware routing with latency-based selection and
  automatic cross-region failover.
* **DegradationManager** - coordinated graceful-degradation modes that compose
  the above primitives into higher-level policies.
"""
