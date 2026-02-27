"""Semantic routing configuration models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════


class IntentCategory(StrEnum):
    """Built-in intent categories."""

    SIMPLE_QA = "simple_qa"
    COMPLEX_REASONING = "complex_reasoning"
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    CREATIVE_WRITING = "creative_writing"
    TRANSLATION = "translation"
    SUMMARISATION = "summarisation"
    MATH = "math"
    VISION = "vision"
    GENERAL = "general"


# ═══════════════════════════════════════════════════════════════════════════
# Rule models
# ═══════════════════════════════════════════════════════════════════════════


class IntentRule(BaseModel):
    """Map an intent category to a target model."""

    intent: str = Field(..., description="Intent category (e.g. 'code_generation')")
    route_to: str = Field(..., description="Model name to route to")
    priority: int = Field(default=0, description="Higher priority rules match first")


class PatternRule(BaseModel):
    """Route by keyword or regex pattern match on the prompt."""

    pattern: str = Field(
        ...,
        description="Regex pattern to match against the user message",
    )
    route_to: str = Field(..., description="Model name to route to")
    priority: int = Field(default=0, description="Higher priority rules match first")


class ABTestConfig(BaseModel):
    """A/B test configuration — split traffic between models."""

    name: str = Field(..., description="Test name for tracking")
    model_a: str = Field(..., description="Primary model name")
    model_b: str = Field(..., description="Variant model name")
    traffic_split: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Fraction of traffic to model_a (rest goes to model_b)",
    )
    enabled: bool = Field(default=True)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# Top-level config
# ═══════════════════════════════════════════════════════════════════════════


class SemanticRoutingConfig(BaseModel):
    """Configuration for semantic routing."""

    enabled: bool = Field(default=False, description="Enable semantic routing")
    classifier_model: str | None = Field(
        default=None,
        description="Model to use for intent classification (e.g. 'openai/gpt-4o-mini')",
    )
    rules: list[IntentRule] = Field(
        default_factory=list,
        description="Intent → model routing rules",
    )
    pattern_rules: list[PatternRule] = Field(
        default_factory=list,
        description="Regex pattern → model routing rules",
    )
    ab_tests: list[ABTestConfig] = Field(
        default_factory=list,
        description="A/B test configurations",
    )
    default_model: str | None = Field(
        default=None,
        description="Fallback model when no rule matches",
    )
    cache_classifications: bool = Field(
        default=True,
        description="Cache intent classifications for identical prompts",
    )
    classification_timeout: float = Field(
        default=5.0,
        description="Timeout for classifier model calls (seconds)",
    )
