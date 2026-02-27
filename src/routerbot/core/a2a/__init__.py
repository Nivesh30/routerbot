"""A2A (Agent-to-Agent) protocol package.

Provides agent registration, discovery, invocation, and health monitoring
following the A2A protocol specification.
"""

from routerbot.core.a2a.models import (
    A2AAgentCard,
    A2AAgentConfig,
    A2AAgentHealth,
    A2AAgentSkill,
    A2AAgentStatus,
    A2AInvocationRequest,
    A2AInvocationResult,
    A2AVisibility,
)
from routerbot.core.a2a.registry import A2AAgentRegistry

__all__ = [
    "A2AAgentCard",
    "A2AAgentConfig",
    "A2AAgentHealth",
    "A2AAgentRegistry",
    "A2AAgentSkill",
    "A2AAgentStatus",
    "A2AInvocationRequest",
    "A2AInvocationResult",
    "A2AVisibility",
]
