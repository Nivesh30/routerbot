"""Pydantic models for Kubernetes operator resources and CRDs."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ResourcePhase(StrEnum):
    """Lifecycle phase for a Kubernetes-managed resource."""

    PENDING = "Pending"
    CREATING = "Creating"
    RUNNING = "Running"
    UPDATING = "Updating"
    SCALING = "Scaling"
    FAILED = "Failed"
    DELETING = "Deleting"
    DELETED = "Deleted"


class HealthStatus(StrEnum):
    """Health status for a managed pod / resource."""

    HEALTHY = "Healthy"
    DEGRADED = "Degraded"
    UNHEALTHY = "Unhealthy"
    UNKNOWN = "Unknown"


class ScalingDirection(StrEnum):
    """Direction of a scaling event."""

    UP = "up"
    DOWN = "down"
    NONE = "none"


# ---------------------------------------------------------------------------
# Kubernetes metadata (simplified)
# ---------------------------------------------------------------------------


class ObjectMeta(BaseModel):
    """Simplified Kubernetes ObjectMeta."""

    name: str = ""
    namespace: str = "default"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    uid: str = ""
    generation: int = 1
    created_at: datetime | None = None


class OwnerReference(BaseModel):
    """Simplified owner reference for resource relationships."""

    api_version: str = "routerbot.io/v1alpha1"
    kind: str = ""
    name: str = ""
    uid: str = ""


# ---------------------------------------------------------------------------
# CRD: LLMGateway
# ---------------------------------------------------------------------------


class GatewaySpec(BaseModel):
    """Spec for LLMGateway CRD - main RouterBot deployment."""

    replicas: int = Field(default=1, ge=1, le=100)
    image: str = Field(default="routerbot:latest")
    port: int = Field(default=8000, ge=1, le=65535)
    config_map: str = Field(default="routerbot-config")
    secret_ref: str = Field(default="routerbot-secrets")
    resources: ResourceRequirements = Field(default_factory=lambda: ResourceRequirements())
    autoscaling: AutoscalingSpec | None = None
    health_check: HealthCheckSpec = Field(default_factory=lambda: HealthCheckSpec())
    env: dict[str, str] = Field(default_factory=dict)


class ResourceRequirements(BaseModel):
    """CPU/memory resource requirements."""

    cpu_request: str = Field(default="100m")
    cpu_limit: str = Field(default="1000m")
    memory_request: str = Field(default="256Mi")
    memory_limit: str = Field(default="1Gi")


class AutoscalingSpec(BaseModel):
    """Horizontal Pod Autoscaler spec."""

    enabled: bool = Field(default=True)
    min_replicas: int = Field(default=1, ge=1)
    max_replicas: int = Field(default=10, ge=1)
    target_cpu_percent: int = Field(default=70, ge=1, le=100)
    target_memory_percent: int = Field(default=80, ge=1, le=100)
    target_rps: int | None = Field(default=None, ge=1, description="Target requests per second")
    scale_up_cooldown_seconds: int = Field(default=60, ge=0)
    scale_down_cooldown_seconds: int = Field(default=300, ge=0)


class HealthCheckSpec(BaseModel):
    """Health check / probe configuration."""

    liveness_path: str = "/health"
    readiness_path: str = "/ready"
    startup_path: str = "/health"
    initial_delay_seconds: int = Field(default=10, ge=0)
    period_seconds: int = Field(default=10, ge=1)
    timeout_seconds: int = Field(default=5, ge=1)
    failure_threshold: int = Field(default=3, ge=1)
    success_threshold: int = Field(default=1, ge=1)


class GatewayStatus(BaseModel):
    """Status for LLMGateway CRD."""

    phase: ResourcePhase = ResourcePhase.PENDING
    replicas: int = 0
    ready_replicas: int = 0
    available_replicas: int = 0
    observed_generation: int = 0
    conditions: list[ResourceCondition] = Field(default_factory=list)
    last_updated: datetime | None = None


class ResourceCondition(BaseModel):
    """Condition entry in resource status."""

    condition_type: str = ""
    status: str = "False"  # "True", "False", "Unknown"
    reason: str = ""
    message: str = ""
    last_transition: datetime | None = None


class LLMGateway(BaseModel):
    """LLMGateway Custom Resource Definition."""

    api_version: str = "routerbot.io/v1alpha1"
    kind: str = "LLMGateway"
    metadata: ObjectMeta = Field(default_factory=ObjectMeta)
    spec: GatewaySpec = Field(default_factory=GatewaySpec)
    status: GatewayStatus = Field(default_factory=GatewayStatus)


# ---------------------------------------------------------------------------
# CRD: LLMModel
# ---------------------------------------------------------------------------


class ModelSpec(BaseModel):
    """Spec for LLMModel CRD - model configuration."""

    provider: str = Field(default="", description="Provider name (openai, anthropic, etc.)")
    model_name: str = Field(default="", description="Model identifier (gpt-4o, etc.)")
    endpoint: str = Field(default="")
    max_tokens: int = Field(default=4096, ge=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    rate_limit_rpm: int = Field(default=60, ge=1)
    rate_limit_tpm: int = Field(default=100000, ge=1)
    priority: int = Field(default=1, ge=1, le=10)
    enabled: bool = True
    secret_ref: str = Field(default="", description="K8s secret containing API key")
    fallback_model: str = Field(default="", description="Model to fall back to on failure")


class ModelStatus(BaseModel):
    """Status for LLMModel CRD."""

    phase: ResourcePhase = ResourcePhase.PENDING
    healthy: bool = False
    last_check: datetime | None = None
    total_requests: int = 0
    error_rate: float = 0.0
    average_latency_ms: float = 0.0
    conditions: list[ResourceCondition] = Field(default_factory=list)


class LLMModel(BaseModel):
    """LLMModel Custom Resource Definition."""

    api_version: str = "routerbot.io/v1alpha1"
    kind: str = "LLMModel"
    metadata: ObjectMeta = Field(default_factory=ObjectMeta)
    spec: ModelSpec = Field(default_factory=ModelSpec)
    status: ModelStatus = Field(default_factory=ModelStatus)


# ---------------------------------------------------------------------------
# CRD: LLMKey
# ---------------------------------------------------------------------------


class KeySpec(BaseModel):
    """Spec for LLMKey CRD - virtual API key management."""

    owner: str = Field(default="", description="Key owner (user/team)")
    team_ref: str = Field(default="", description="LLMTeam reference")
    models: list[str] = Field(default_factory=list, description="Allowed models")
    rate_limit_rpm: int = Field(default=60, ge=1)
    budget_limit: float = Field(default=0.0, ge=0, description="Monthly budget in USD")
    expires_at: datetime | None = None
    enabled: bool = True
    metadata_labels: dict[str, str] = Field(default_factory=dict)


class KeyStatus(BaseModel):
    """Status for LLMKey CRD."""

    phase: ResourcePhase = ResourcePhase.PENDING
    active: bool = False
    total_requests: int = 0
    current_spend: float = 0.0
    last_used: datetime | None = None
    conditions: list[ResourceCondition] = Field(default_factory=list)


class LLMKey(BaseModel):
    """LLMKey Custom Resource Definition."""

    api_version: str = "routerbot.io/v1alpha1"
    kind: str = "LLMKey"
    metadata: ObjectMeta = Field(default_factory=ObjectMeta)
    spec: KeySpec = Field(default_factory=KeySpec)
    status: KeyStatus = Field(default_factory=KeyStatus)


# ---------------------------------------------------------------------------
# CRD: LLMTeam
# ---------------------------------------------------------------------------


class TeamSpec(BaseModel):
    """Spec for LLMTeam CRD - team configuration."""

    display_name: str = ""
    members: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    budget_limit: float = Field(default=0.0, ge=0, description="Monthly budget in USD")
    rate_limit_rpm: int = Field(default=120, ge=1)
    max_keys: int = Field(default=10, ge=1)


class TeamStatus(BaseModel):
    """Status for LLMTeam CRD."""

    phase: ResourcePhase = ResourcePhase.PENDING
    active_keys: int = 0
    total_requests: int = 0
    current_spend: float = 0.0
    conditions: list[ResourceCondition] = Field(default_factory=list)


class LLMTeam(BaseModel):
    """LLMTeam Custom Resource Definition."""

    api_version: str = "routerbot.io/v1alpha1"
    kind: str = "LLMTeam"
    metadata: ObjectMeta = Field(default_factory=ObjectMeta)
    spec: TeamSpec = Field(default_factory=TeamSpec)
    status: TeamStatus = Field(default_factory=TeamStatus)


# ---------------------------------------------------------------------------
# Operator events
# ---------------------------------------------------------------------------


class ReconcileEvent(BaseModel):
    """Event produced by the operator reconciliation loop."""

    resource_kind: str = ""
    resource_name: str = ""
    namespace: str = "default"
    action: str = ""  # Created, Updated, Deleted, Scaled, HealthChanged
    message: str = ""
    timestamp: datetime | None = None


class ScalingEvent(BaseModel):
    """Record of an autoscaling decision."""

    gateway_name: str = ""
    direction: ScalingDirection = ScalingDirection.NONE
    from_replicas: int = 0
    to_replicas: int = 0
    reason: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)
    timestamp: datetime | None = None


class PodHealth(BaseModel):
    """Health state for a single pod."""

    pod_name: str = ""
    status: HealthStatus = HealthStatus.UNKNOWN
    ready: bool = False
    restarts: int = 0
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    last_check: datetime | None = None


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class K8sOperatorConfig(BaseModel):
    """Configuration for the Kubernetes operator module."""

    enabled: bool = Field(default=False)
    reconcile_interval_seconds: int = Field(default=30, ge=5)
    health_check_interval_seconds: int = Field(default=15, ge=5)
    autoscale_enabled: bool = Field(default=True)
    leader_election: bool = Field(default=True)
    namespace: str = Field(default="default")
    api_version: str = Field(default="routerbot.io/v1alpha1")
