"""A2A data models — agent cards, skills, invocation, and status.

Follows the A2A (Agent-to-Agent) protocol specification for agent
registration, discovery, and inter-agent communication.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════


class A2AAgentHealth(StrEnum):
    """Health status of a registered agent."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CONNECTING = "connecting"


class A2AVisibility(StrEnum):
    """Visibility level for agent access control."""

    PUBLIC = "public"
    PRIVATE = "private"


class A2AAgentFramework(StrEnum):
    """Known agent framework types for specialised handling."""

    GENERIC = "generic"
    PYDANTIC_AI = "pydantic-ai"
    LANGGRAPH = "langgraph"
    CUSTOM = "custom"


# ═══════════════════════════════════════════════════════════════════════════
# Agent Card & Configuration
# ═══════════════════════════════════════════════════════════════════════════


class A2AAgentSkill(BaseModel):
    """A capability / skill exposed by an agent."""

    id: str = Field(..., description="Unique skill identifier")
    name: str = Field(..., description="Human-readable skill name")
    description: str = Field(default="", description="What this skill does")
    tags: list[str] = Field(default_factory=list, description="Search tags")
    examples: list[str] = Field(default_factory=list, description="Example invocations")


class A2AAgentCard(BaseModel):
    """Public agent metadata — the A2A 'agent card'.

    This is what gets returned from the discovery endpoint and what
    other agents use to decide whether to invoke this agent.
    """

    name: str = Field(..., description="Agent name (unique within registry)")
    description: str = Field(default="", description="What the agent does")
    url: str = Field(..., description="Base URL for invoking the agent")
    version: str = Field(default="1.0.0", description="Agent version")
    framework: A2AAgentFramework = Field(
        default=A2AAgentFramework.GENERIC,
        description="Agent framework type",
    )
    skills: list[A2AAgentSkill] = Field(
        default_factory=list,
        description="Skills/capabilities exposed by this agent",
    )
    authentication: dict[str, Any] = Field(
        default_factory=dict,
        description="Auth requirements (e.g. {'type': 'bearer'})",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra metadata",
    )


class A2AAgentConfig(BaseModel):
    """Configuration entry for an A2A agent in routerbot_config.yaml."""

    name: str = Field(..., description="Agent name (unique)")
    url: str = Field(..., description="Agent endpoint URL")
    description: str = Field(default="", description="Agent description")
    version: str = Field(default="1.0.0")
    framework: A2AAgentFramework = Field(default=A2AAgentFramework.GENERIC)
    skills: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Skill definitions",
    )
    visibility: A2AVisibility = Field(
        default=A2AVisibility.PUBLIC,
        description="Access level",
    )
    allowed_teams: list[str] = Field(
        default_factory=list,
        description="Teams allowed access when visibility=private",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Custom headers for agent invocation",
    )
    timeout: float = Field(default=60.0, description="Request timeout in seconds")
    enabled: bool = Field(default=True)


# ═══════════════════════════════════════════════════════════════════════════
# Invocation models
# ═══════════════════════════════════════════════════════════════════════════


class A2AMessage(BaseModel):
    """A single message in an A2A conversation."""

    role: str = Field(..., description="Message role (user, agent, system)")
    content: str = Field(..., description="Message content")
    metadata: dict[str, Any] = Field(default_factory=dict)


class A2AInvocationRequest(BaseModel):
    """Request to invoke an agent."""

    agent_name: str = Field(..., description="Target agent name")
    skill_id: str | None = Field(default=None, description="Specific skill to invoke")
    messages: list[A2AMessage] = Field(
        default_factory=list,
        description="Conversation messages",
    )
    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured input for the agent",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Request metadata",
    )


class A2AInvocationResult(BaseModel):
    """Result of an agent invocation."""

    agent_name: str
    status: str = Field(default="completed", description="completed | error | pending")
    messages: list[A2AMessage] = Field(default_factory=list)
    output_data: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# Status
# ═══════════════════════════════════════════════════════════════════════════


class A2AAgentStatus(BaseModel):
    """Runtime status of a registered agent."""

    name: str
    url: str
    framework: A2AAgentFramework
    health: A2AAgentHealth = A2AAgentHealth.UNKNOWN
    skills_count: int = 0
    last_health_check: float | None = None
    enabled: bool = True
