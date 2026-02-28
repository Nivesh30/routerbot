"""Pydantic configuration models for RouterBot.

All config sections are defined here as Pydantic models. The top-level
RouterBotConfig model represents the full routerbot_config.yaml file.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RoutingStrategy(StrEnum):
    """Load balancing strategy for routing requests across model deployments."""

    ROUND_ROBIN = "round-robin"
    WEIGHTED_ROUND_ROBIN = "weighted-round-robin"
    LEAST_LATENCY = "latency-based"
    COST_BASED = "cost-based"
    RANDOM = "random"
    LEAST_CONNECTIONS = "least-connections"


class CacheType(StrEnum):
    """Supported cache backends."""

    REDIS = "redis"
    MEMORY = "memory"
    NONE = "none"


class ModelParams(BaseModel):
    """Provider-specific parameters for a model deployment."""

    model: str = Field(..., description="Provider/model format, e.g. 'openai/gpt-4o'")
    api_key: str | None = Field(default=None, description="API key or os.environ/VAR_NAME reference")
    api_base: str | None = Field(default=None, description="Custom API base URL")
    api_version: str | None = Field(default=None, description="API version (e.g. Azure)")
    max_tokens: int | None = Field(default=None, gt=0, description="Default max tokens")
    rpm: int | None = Field(default=None, gt=0, description="Requests per minute limit")
    tpm: int | None = Field(default=None, gt=0, description="Tokens per minute limit")
    timeout: int | None = Field(default=None, gt=0, description="Request timeout in seconds")
    organization: str | None = Field(default=None, description="Organization ID (OpenAI)")
    region: str | None = Field(default=None, description="Region (AWS Bedrock, Vertex AI)")
    project: str | None = Field(default=None, description="Project ID (Vertex AI)")
    extra_headers: dict[str, str] = Field(default_factory=dict, description="Extra headers for requests")
    extra_body: dict[str, Any] = Field(default_factory=dict, description="Extra body params for requests")

    model_config = {"extra": "allow"}


class ModelInfo(BaseModel):
    """Optional metadata about a model deployment."""

    id: str | None = Field(default=None, description="Unique model identifier")
    max_input_tokens: int | None = Field(default=None, description="Max input context length")
    max_output_tokens: int | None = Field(default=None, description="Max output tokens")
    input_cost_per_token: float | None = Field(default=None, description="USD cost per input token")
    output_cost_per_token: float | None = Field(default=None, description="USD cost per output token")
    supports_vision: bool = Field(default=False, description="Supports image input")
    supports_function_calling: bool = Field(default=False, description="Supports function/tool calling")
    supports_streaming: bool = Field(default=True, description="Supports streaming responses")

    model_config = {"extra": "allow"}


class ModelEntry(BaseModel):
    """A single model deployment entry in the config."""

    model_name: str = Field(..., description="Virtual model name clients use")
    provider_params: ModelParams = Field(..., description="Provider-specific parameters")
    model_info: ModelInfo | None = Field(default=None, description="Optional model metadata overrides")

    model_config = {"extra": "allow"}


class GeneralSettings(BaseModel):
    """General server settings."""

    master_key: str | None = Field(default=None, description="Master API key for admin operations")
    database_url: str = Field(
        default="sqlite+aiosqlite:///routerbot.db",
        description="Database connection string (async driver)",
    )
    redis_url: str | None = Field(default=None, description="Redis connection URL")
    port: int = Field(default=4000, ge=1, le=65535, description="HTTP server port")
    host: str = Field(default="0.0.0.0", description="HTTP server bind address")  # noqa: S104
    num_workers: int = Field(default=1, ge=1, description="Number of Uvicorn workers")
    request_timeout: int = Field(default=600, gt=0, description="Request timeout in seconds")
    max_request_size_mb: float = Field(default=100.0, gt=0, description="Max request body size in MB")
    max_response_size_mb: float = Field(default=100.0, gt=0, description="Max response body size for logging")
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"], description="CORS allowed origins")
    cors_allow_credentials: bool = Field(default=True, description="CORS allow credentials")
    block_robots: bool = Field(default=False, description="Return disallow-all robots.txt")
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format: json or text")
    allowed_ips: list[str] = Field(default_factory=list, description="IP/CIDR allowlist (empty = allow all)")
    blocked_ips: list[str] = Field(default_factory=list, description="IP/CIDR blocklist")
    trust_proxy_headers: bool = Field(default=False, description="Trust X-Forwarded-For for client IP")


class RouterSettings(BaseModel):
    """Router layer settings: retries, fallbacks, routing strategy."""

    routing_strategy: RoutingStrategy = Field(
        default=RoutingStrategy.ROUND_ROBIN,
        description="Load balancing strategy",
    )
    num_retries: int = Field(default=3, ge=0, le=10, description="Number of retries on failure")
    retry_delay: float = Field(default=1.0, ge=0, description="Base retry delay in seconds")
    timeout: int = Field(default=600, gt=0, description="Per-request timeout in seconds")
    cooldown_time: int = Field(default=60, ge=0, description="Cooldown time for failed deployments in seconds")
    fallbacks: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Fallback model mappings: {'model': ['fallback1', 'fallback2']}",
    )
    allowed_fails: int = Field(default=3, ge=1, description="Failures before marking deployment unhealthy")
    enable_health_check: bool = Field(default=True, description="Enable periodic provider health checks")
    health_check_interval: int = Field(default=300, gt=0, description="Health check interval in seconds")


class CacheSettings(BaseModel):
    """Cache layer configuration."""

    type: CacheType = Field(default=CacheType.NONE, description="Cache backend type")
    ttl: int = Field(default=3600, gt=0, description="Default cache TTL in seconds")
    namespace: str = Field(default="routerbot", description="Cache key namespace")
    redis_url: str | None = Field(default=None, description="Redis URL (if different from general)")
    max_memory_items: int = Field(default=1000, gt=0, description="Max in-memory cache items")
    similarity_threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Semantic cache similarity threshold",
    )


class RouterBotSettings(BaseModel):
    """Global settings for callbacks, caching, and misc behavior."""

    callbacks: list[str] = Field(default_factory=list, description="Active callback names")
    success_callback: list[str] = Field(default_factory=list, description="Callbacks on success")
    failure_callback: list[str] = Field(default_factory=list, description="Callbacks on failure")
    cache: bool = Field(default=False, description="Enable response caching")
    cache_params: CacheSettings = Field(default_factory=CacheSettings, description="Cache configuration")


class RouterBotConfig(BaseModel):
    """Top-level configuration model representing routerbot_config.yaml."""

    model_list: list[ModelEntry] = Field(default_factory=list, description="Model deployment entries")
    general_settings: GeneralSettings = Field(default_factory=GeneralSettings, description="General server settings")
    router_settings: RouterSettings = Field(default_factory=RouterSettings, description="Router layer settings")
    routerbot_settings: RouterBotSettings = Field(
        default_factory=RouterBotSettings,
        description="Global callbacks and cache settings",
    )
    environment_variables: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to set on startup",
    )
    mcp_servers: list[dict[str, Any]] = Field(
        default_factory=list,
        description="MCP server configurations (parsed by MCP module)",
    )
    a2a_agents: list[dict[str, Any]] = Field(
        default_factory=list,
        description="A2A agent configurations (parsed by A2A module)",
    )
    semantic_routing: dict[str, Any] = Field(
        default_factory=dict,
        description="Semantic routing configuration (parsed by semantic module)",
    )
    request_transform: dict[str, Any] = Field(
        default_factory=dict,
        description="Request transformation pipeline configuration",
    )
    scaling: dict[str, Any] = Field(
        default_factory=dict,
        description="Auto-scaling, cost alerts, and recommendation configuration",
    )
    plugins: dict[str, Any] = Field(
        default_factory=dict,
        description="Plugin system configuration",
    )
    resilience: dict[str, Any] = Field(
        default_factory=dict,
        description="Resilience, circuit-breaker, bulkhead, and region-routing configuration",
    )
    advanced_auth: dict[str, Any] = Field(
        default_factory=dict,
        description="Advanced auth: mTLS, key scoping, webhook auth, token exchange, permissions",
    )
    batch: dict[str, Any] = Field(
        default_factory=dict,
        description="Batch processing and async job queue configuration",
    )
    hub: dict[str, Any] = Field(
        default_factory=dict,
        description="AI Hub & Playground configuration",
    )

    model_config = {"extra": "allow"}
