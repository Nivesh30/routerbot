"""Models for the request transformation pipeline."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TransformStage(StrEnum):
    """When in the pipeline a transform runs."""

    PRE_REQUEST = "pre_request"
    POST_RESPONSE = "post_response"


class TransformContext(BaseModel):
    """Context passed through the transformation pipeline.

    Carries metadata about the current request so transforms can make
    team/key/model-specific decisions.
    """

    model: str = ""
    team_id: str | None = None
    key_id: str | None = None
    user_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TransformResult(BaseModel):
    """Outcome of a single transform step.

    ``modified`` is *True* when the transform actually changed the data.
    ``metadata`` is optional extra info that later transforms or logging
    can inspect.
    """

    modified: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Prompt injection config ─────────────────────────────────────────────


class PromptTemplate(BaseModel):
    """A system-prompt template that can be injected into requests.

    Templates are matched by *scope*: they can apply globally, to a
    specific team, to a specific key, or to a specific model.
    """

    name: str
    content: str
    position: str = Field(
        default="prepend",
        description="'prepend' adds before existing system prompt; "
        "'append' adds after; 'replace' overwrites it.",
    )
    # Scope filters (all optional — omit to make it global)
    team_ids: list[str] = Field(default_factory=list)
    key_ids: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    enabled: bool = True
    priority: int = Field(default=0, description="Higher runs first.")


# ── Enrichment config ───────────────────────────────────────────────────


class EnrichmentSource(BaseModel):
    """An external source used to enrich requests with extra context.

    Supported types:
    * ``static``  - inject a fixed string
    * ``header``  - pull from an HTTP header value
    * ``metadata`` - pull from key/team metadata
    """

    name: str
    source_type: str = Field(
        default="static",
        description="static | header | metadata",
    )
    content: str | None = Field(
        default=None,
        description="Static content to inject (for source_type='static').",
    )
    header_name: str | None = Field(
        default=None,
        description="HTTP header to read (for source_type='header').",
    )
    metadata_key: str | None = Field(
        default=None,
        description="Metadata field to read (for source_type='metadata').",
    )
    position: str = Field(
        default="prepend",
        description="'prepend' or 'append' (relative to existing messages).",
    )
    team_ids: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    enabled: bool = True


# ── Post-processing config ──────────────────────────────────────────────


class PostProcessingRule(BaseModel):
    """A rule for modifying model responses before returning to the caller.

    Supported actions:
    * ``strip_thinking`` - remove ``<thinking>...</thinking>`` blocks
    * ``regex_replace``  - apply a regex substitution
    * ``truncate``       - limit output to *max_chars* characters
    * ``add_metadata``   - attach extra key-value pairs to the response
    """

    name: str
    action: str = Field(
        description="strip_thinking | regex_replace | truncate | add_metadata",
    )
    pattern: str | None = Field(
        default=None,
        description="Regex pattern (for regex_replace action).",
    )
    replacement: str | None = Field(
        default=None,
        description="Replacement string (for regex_replace action).",
    )
    max_chars: int | None = Field(
        default=None,
        description="Maximum characters (for truncate action).",
    )
    metadata_pairs: dict[str, str] = Field(
        default_factory=dict,
        description="Key-value pairs to add (for add_metadata action).",
    )
    team_ids: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    enabled: bool = True


# ── Aggregate config object ─────────────────────────────────────────────


class TransformConfig(BaseModel):
    """Top-level configuration for the request-transformation pipeline."""

    enabled: bool = False
    prompt_templates: list[PromptTemplate] = Field(default_factory=list)
    enrichment_sources: list[EnrichmentSource] = Field(default_factory=list)
    post_processing_rules: list[PostProcessingRule] = Field(default_factory=list)
    log_full_content: bool = Field(
        default=False,
        description="When True, log the full request/response content (opt-in).",
    )
