"""Pydantic models for the resilience & HA module."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

UTC = UTC


# ---------------------------------------------------------------------------
# Circuit-breaker
# ---------------------------------------------------------------------------


class CircuitState(StrEnum):
    """Circuit-breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerConfig(BaseModel):
    """Configuration for a single circuit breaker."""

    failure_threshold: int = Field(default=5, ge=1, description="Consecutive failures before opening")
    recovery_timeout: float = Field(default=30.0, gt=0, description="Seconds in OPEN before moving to HALF_OPEN")
    half_open_max_calls: int = Field(default=3, ge=1, description="Max probe calls allowed in HALF_OPEN")
    success_threshold: int = Field(default=2, ge=1, description="Successes in HALF_OPEN to close circuit")
    excluded_exceptions: list[str] = Field(
        default_factory=list,
        description="Exception class names that do NOT count as failures (e.g. 'BadRequestError')",
    )


class CircuitBreakerSnapshot(BaseModel):
    """Point-in-time snapshot of a circuit breaker."""

    name: str
    state: CircuitState
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: datetime | None = None
    last_success_time: datetime | None = None
    opened_at: datetime | None = None
    half_opened_at: datetime | None = None


# ---------------------------------------------------------------------------
# Request queue
# ---------------------------------------------------------------------------


class QueuedRequest(BaseModel):
    """A request waiting in the buffer queue."""

    request_id: str
    provider: str
    payload: dict[str, Any] = Field(default_factory=dict)
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    ttl_seconds: float = Field(default=30.0, gt=0)

    @property
    def is_expired(self) -> bool:
        elapsed = (datetime.now(tz=UTC) - self.enqueued_at).total_seconds()
        return elapsed > self.ttl_seconds


class RequestQueueConfig(BaseModel):
    """Configuration for the request queue."""

    max_size: int = Field(default=1000, ge=1, description="Maximum queue depth")
    default_ttl: float = Field(default=30.0, gt=0, description="Default request TTL in seconds")
    drain_batch_size: int = Field(default=10, ge=1, description="Items to drain per batch on recovery")
    enabled: bool = Field(default=True)


class RequestQueueStats(BaseModel):
    """Queue statistics snapshot."""

    provider: str
    depth: int = 0
    total_enqueued: int = 0
    total_drained: int = 0
    total_expired: int = 0
    total_rejected: int = 0


# ---------------------------------------------------------------------------
# Bulkhead
# ---------------------------------------------------------------------------


class BulkheadConfig(BaseModel):
    """Concurrency isolation configuration for a provider."""

    max_concurrent: int = Field(default=50, ge=1, description="Max concurrent requests to this provider")
    max_wait_seconds: float = Field(default=5.0, ge=0, description="Max time to wait for a slot (0=fail fast)")


class BulkheadStats(BaseModel):
    """Bulkhead statistics snapshot."""

    provider: str
    max_concurrent: int
    active: int = 0
    waiting: int = 0
    total_accepted: int = 0
    total_rejected: int = 0


# ---------------------------------------------------------------------------
# Region routing
# ---------------------------------------------------------------------------


class Region(BaseModel):
    """A geographic region definition."""

    name: str = Field(..., description="Region identifier, e.g. 'us-east-1'")
    display_name: str = Field(default="", description="Human-readable name")
    latitude: float = Field(default=0.0, ge=-90, le=90)
    longitude: float = Field(default=0.0, ge=-180, le=180)
    priority: int = Field(default=0, ge=0, description="Lower = higher priority")


class ProviderRegion(BaseModel):
    """Maps a provider deployment to a geographic region."""

    provider: str = Field(..., description="Provider name, e.g. 'openai/gpt-4o'")
    region: str = Field(..., description="Region name, e.g. 'us-east-1'")
    endpoint: str = Field(default="", description="Region-specific endpoint URL")
    weight: float = Field(default=1.0, ge=0, description="Routing weight within region")
    healthy: bool = Field(default=True)


class RegionRoutingConfig(BaseModel):
    """Configuration for region-aware routing."""

    enabled: bool = Field(default=True)
    regions: list[Region] = Field(default_factory=list)
    provider_regions: list[ProviderRegion] = Field(default_factory=list)
    default_region: str = Field(default="", description="Fallback region when detection fails")
    failover_enabled: bool = Field(default=True, description="Allow cross-region failover")
    max_failover_distance_km: float = Field(
        default=0.0,
        ge=0,
        description="Max failover distance in km (0 = unlimited)",
    )


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


class DegradationLevel(StrEnum):
    """Service degradation levels."""

    NORMAL = "normal"
    DEGRADED = "degraded"
    LIMITED = "limited"
    EMERGENCY = "emergency"


class DegradationPolicy(BaseModel):
    """Policy for a specific degradation level."""

    level: DegradationLevel = DegradationLevel.NORMAL
    description: str = ""
    reject_new_requests: bool = Field(default=False)
    queue_requests: bool = Field(default=False)
    allow_cached_only: bool = Field(default=False)
    max_tokens_override: int | None = Field(default=None, ge=1)
    allowed_models: list[str] = Field(default_factory=list, description="If non-empty, only these models served")
    disable_streaming: bool = Field(default=False)


class DegradationStatus(BaseModel):
    """Current degradation status for a provider or global."""

    provider: str = Field(default="global")
    level: DegradationLevel = DegradationLevel.NORMAL
    reason: str = ""
    since: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    auto_recovered: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Top-level resilience config
# ---------------------------------------------------------------------------


class ResilienceConfig(BaseModel):
    """Top-level configuration for all resilience features."""

    enabled: bool = Field(default=True)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    request_queue: RequestQueueConfig = Field(default_factory=RequestQueueConfig)
    bulkhead_defaults: BulkheadConfig = Field(default_factory=BulkheadConfig)
    bulkhead_overrides: dict[str, BulkheadConfig] = Field(
        default_factory=dict,
        description="Per-provider bulkhead overrides keyed by provider name",
    )
    region_routing: RegionRoutingConfig = Field(default_factory=RegionRoutingConfig)
    degradation_policies: dict[str, DegradationPolicy] = Field(
        default_factory=dict,
        description="Named degradation policies keyed by level name",
    )
