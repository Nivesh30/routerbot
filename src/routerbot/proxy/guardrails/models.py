"""Configuration model for the guardrail pipeline."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GuardrailsConfig(BaseModel):
    """Top-level guardrails configuration.

    Each guardrail field is the raw kwargs dict for that guardrail's
    constructor (mode, entity_types, keywords, etc.) — present only if
    that guardrail should be registered; ``None`` skips it entirely.
    """

    enabled: bool = Field(default=False)
    pii_detection: dict[str, Any] | None = Field(default=None)
    secret_detection: dict[str, Any] | None = Field(default=None)
    banned_keywords: dict[str, Any] | None = Field(default=None)
    content_moderation: dict[str, Any] | None = Field(
        default=None,
        description="Extra keys 'backend' ('keyword' | 'openai', default 'keyword') and "
        "'backend_config' (kwargs for that backend) are popped before constructing the guardrail.",
    )
