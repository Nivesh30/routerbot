"""Pydantic models for the AI Hub & Playground module."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ModelCapability(StrEnum):
    """Capabilities a model may support."""

    CHAT = "chat"
    COMPLETION = "completion"
    EMBEDDING = "embedding"
    IMAGE_GENERATION = "image_generation"
    VISION = "vision"
    CODE = "code"
    FUNCTION_CALLING = "function_calling"
    STREAMING = "streaming"
    JSON_MODE = "json_mode"


class PlaygroundStatus(StrEnum):
    """Status of a playground session."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PromptStatus(StrEnum):
    """Status of a prompt template."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


# ---------------------------------------------------------------------------
# Model catalogue
# ---------------------------------------------------------------------------


class ModelPricing(BaseModel):
    """Per-token pricing for a model."""

    input_cost_per_1k: float = Field(default=0.0, ge=0, description="Cost per 1K input tokens")
    output_cost_per_1k: float = Field(default=0.0, ge=0, description="Cost per 1K output tokens")
    currency: str = Field(default="USD")


class ModelInfo(BaseModel):
    """Public information about an available model."""

    model_id: str = Field(..., description="Full model identifier (e.g. openai/gpt-4o)")
    provider: str = Field(default="", description="Provider name")
    display_name: str = Field(default="", description="Human-friendly name")
    description: str = Field(default="", description="Brief description")
    capabilities: list[ModelCapability] = Field(default_factory=list)
    pricing: ModelPricing = Field(default_factory=ModelPricing)
    context_window: int = Field(default=0, ge=0, description="Max context length in tokens")
    max_output_tokens: int = Field(default=0, ge=0)
    is_available: bool = Field(default=True)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelCatalogue(BaseModel):
    """Collection of available models."""

    models: list[ModelInfo] = Field(default_factory=list)
    updated_at: datetime | None = None

    @property
    def available_models(self) -> list[ModelInfo]:
        return [m for m in self.models if m.is_available]

    @property
    def providers(self) -> list[str]:
        return sorted({m.provider for m in self.models if m.provider})


# ---------------------------------------------------------------------------
# Model comparison
# ---------------------------------------------------------------------------


class ComparisonRequest(BaseModel):
    """Request to compare multiple models side-by-side."""

    models: list[str] = Field(..., min_length=2, max_length=10, description="Model IDs to compare")
    messages: list[dict[str, Any]] = Field(default_factory=list, description="Chat messages")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Shared parameters (temperature, max_tokens, etc.)",
    )


class ComparisonResult(BaseModel):
    """Result of a single model in a comparison."""

    model_id: str = ""
    response: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost: float = 0.0
    error: str = ""


class ComparisonResponse(BaseModel):
    """Full comparison response across all models."""

    request_id: str = ""
    results: list[ComparisonResult] = Field(default_factory=list)
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Playground
# ---------------------------------------------------------------------------


class PlaygroundMessage(BaseModel):
    """A single message in a playground conversation."""

    role: str = Field(default="user")
    content: str = Field(default="")
    model_id: str = Field(default="", description="Model that generated this (for assistant msgs)")
    tokens: int = 0
    latency_ms: float = 0.0


class PlaygroundSession(BaseModel):
    """An interactive playground session."""

    session_id: str = Field(default="")
    status: PlaygroundStatus = Field(default=PlaygroundStatus.ACTIVE)
    model_id: str = Field(default="")
    messages: list[PlaygroundMessage] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    total_tokens: int = 0
    total_cost: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlaygroundRequest(BaseModel):
    """Request to send a message in a playground session."""

    session_id: str = Field(default="")
    model_id: str = Field(default="")
    message: str = Field(default="")
    parameters: dict[str, Any] = Field(default_factory=dict)


class PlaygroundResponse(BaseModel):
    """Response from the playground."""

    session_id: str = ""
    response: str = ""
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost: float = 0.0


# ---------------------------------------------------------------------------
# Prompt management
# ---------------------------------------------------------------------------


class PromptVariable(BaseModel):
    """A variable placeholder in a prompt template."""

    name: str = Field(..., description="Variable name (e.g. 'topic')")
    description: str = Field(default="")
    default_value: str = Field(default="")
    required: bool = Field(default=True)


class PromptTemplate(BaseModel):
    """A versioned prompt template."""

    template_id: str = Field(default="")
    name: str = Field(default="")
    description: str = Field(default="")
    content: str = Field(default="", description="Template content with {{variable}} placeholders")
    variables: list[PromptVariable] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)
    status: PromptStatus = Field(default=PromptStatus.DRAFT)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptVersion(BaseModel):
    """A specific version of a prompt template."""

    template_id: str = ""
    version: int = 1
    content: str = ""
    variables: list[PromptVariable] = Field(default_factory=list)
    created_at: datetime | None = None


class PromptTestResult(BaseModel):
    """Result of testing a prompt with a model."""

    template_id: str = ""
    version: int = 1
    model_id: str = ""
    rendered_prompt: str = ""
    response: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost: float = 0.0


class PromptABTest(BaseModel):
    """A/B test configuration for prompts."""

    test_id: str = ""
    name: str = ""
    template_id: str = ""
    variant_a_version: int = 1
    variant_b_version: int = 2
    traffic_split: float = Field(default=0.5, ge=0.0, le=1.0, description="Fraction to variant A")
    total_requests: int = 0
    variant_a_requests: int = 0
    variant_b_requests: int = 0
    status: str = Field(default="active")
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptAnalytics(BaseModel):
    """Analytics for a prompt template."""

    template_id: str = ""
    version: int = 1
    total_uses: int = 0
    average_latency_ms: float = 0.0
    average_cost: float = 0.0
    average_tokens: float = 0.0
    success_rate: float = 0.0


# ---------------------------------------------------------------------------
# Hub configuration
# ---------------------------------------------------------------------------


class HubConfig(BaseModel):
    """Top-level AI Hub configuration."""

    enabled: bool = Field(default=False)
    public_catalogue: bool = Field(default=True, description="Expose model catalogue publicly")
    playground_enabled: bool = Field(default=True)
    prompt_management_enabled: bool = Field(default=True)
    max_playground_sessions: int = Field(default=100, ge=1)
    max_comparison_models: int = Field(default=10, ge=2)
    max_prompt_templates: int = Field(default=1000, ge=1)
