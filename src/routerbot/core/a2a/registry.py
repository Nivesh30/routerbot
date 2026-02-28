"""A2A agent registry — manages registered A2A agents.

Provides:
- Agent registration and deregistration
- Agent discovery with team-based access control
- Agent invocation routing
- Background health monitoring
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from routerbot.core.a2a.client import A2AClient, A2AClientError
from routerbot.core.a2a.models import (
    A2AAgentCard,
    A2AAgentConfig,
    A2AAgentHealth,
    A2AAgentStatus,
    A2AInvocationRequest,
    A2AInvocationResult,
    A2AVisibility,
)

logger = logging.getLogger(__name__)


class A2AAgentRegistry:
    """Central registry for A2A agents.

    Manages agent connections, discovery, invocation, and health.
    """

    def __init__(self, health_check_interval: float = 300.0) -> None:
        self._clients: dict[str, A2AClient] = {}
        self._configs: dict[str, A2AAgentConfig] = {}
        self._health_check_interval = health_check_interval
        self._health_check_task: asyncio.Task[None] | None = None

    # ── Container protocol ──────────────────────────────────────────────

    def __contains__(self, name: str) -> bool:
        return name in self._clients

    def __len__(self) -> int:
        return len(self._clients)

    # ── Registration ────────────────────────────────────────────────────

    async def register_agent(self, config: A2AAgentConfig) -> None:
        """Register and connect to an A2A agent."""
        if not config.enabled:
            logger.info("A2A agent '%s' is disabled, skipping", config.name)
            return

        client = A2AClient(config)
        try:
            await client.connect()
        except A2AClientError:
            logger.warning(
                "A2A agent '%s' failed to connect — registering as unhealthy",
                config.name,
            )

        self._clients[config.name] = client
        self._configs[config.name] = config
        logger.info("A2A agent '%s' registered", config.name)

    async def unregister_agent(self, name: str) -> None:
        """Unregister and disconnect an agent."""
        client = self._clients.pop(name, None)
        self._configs.pop(name, None)
        if client:
            await client.disconnect()
            logger.info("A2A agent '%s' unregistered", name)

    async def register_from_config(self, configs: list[A2AAgentConfig]) -> None:
        """Register multiple agents from configuration."""
        for config in configs:
            try:
                await self.register_agent(config)
            except Exception:
                logger.exception("Failed to register A2A agent '%s'", config.name)

    # ── Discovery ───────────────────────────────────────────────────────

    def discover_agents(
        self,
        *,
        team: str | None = None,
        skill_tag: str | None = None,
    ) -> list[A2AAgentCard]:
        """Discover available agents, filtered by team and/or skill tag.

        Args:
            team: Filter to agents accessible by this team.
            skill_tag: Filter to agents that have a skill with this tag.

        Returns:
            List of agent cards matching the filters.
        """
        cards: list[A2AAgentCard] = []
        for name, client in self._clients.items():
            config = self._configs.get(name)
            if config is None:
                continue

            if not config.enabled:
                continue

            # Team access check
            if team and not self._has_team_access(config, team):
                continue

            card = client.agent_card
            if card is None:
                continue

            # Skill tag filter
            if skill_tag and not any(skill_tag in skill.tags for skill in card.skills):
                continue

            cards.append(card)

        return cards

    def get_agent_card(self, name: str) -> A2AAgentCard | None:
        """Get the agent card for a specific agent."""
        client = self._clients.get(name)
        if client is None:
            return None
        return client.agent_card

    # ── Invocation ──────────────────────────────────────────────────────

    async def invoke_agent(self, request: A2AInvocationRequest) -> A2AInvocationResult:
        """Invoke an agent by name."""
        client = self._clients.get(request.agent_name)
        if client is None:
            return A2AInvocationResult(
                agent_name=request.agent_name,
                status="error",
                is_error=True,
                error_message=f"Agent '{request.agent_name}' not found",
            )

        messages_dicts = [m.model_dump() for m in request.messages]

        return await client.invoke(
            messages=messages_dicts,
            input_data=request.input_data,
            skill_id=request.skill_id,
            metadata=request.metadata,
        )

    # ── Status & Health ─────────────────────────────────────────────────

    def get_agent_status(self, name: str) -> A2AAgentStatus | None:
        """Get status for a specific agent."""
        client = self._clients.get(name)
        config = self._configs.get(name)
        if client is None or config is None:
            return None

        card = client.agent_card
        skills_count = len(card.skills) if card else 0

        return A2AAgentStatus(
            name=name,
            url=config.url,
            framework=config.framework,
            health=client.health,
            skills_count=skills_count,
            last_health_check=client.last_health_check,
            enabled=config.enabled,
        )

    def list_agents(self) -> list[A2AAgentStatus]:
        """List status for all registered agents."""
        statuses: list[A2AAgentStatus] = []
        for name in self._clients:
            status = self.get_agent_status(name)
            if status:
                statuses.append(status)
        return statuses

    async def check_health(self, name: str | None = None) -> dict[str, A2AAgentHealth]:
        """Run health checks on agents.

        Args:
            name: Check a specific agent, or all if None.
        """
        results: dict[str, A2AAgentHealth] = {}

        if name:
            client = self._clients.get(name)
            if client:
                results[name] = await client.check_health()
        else:
            for agent_name, client in self._clients.items():
                try:
                    results[agent_name] = await client.check_health()
                except Exception:
                    logger.exception("Health check failed for agent '%s'", agent_name)
                    results[agent_name] = A2AAgentHealth.UNHEALTHY

        return results

    # ── Background health checks ────────────────────────────────────────

    async def start_health_checks(self) -> None:
        """Start periodic background health checks."""
        if self._health_check_interval <= 0:
            return
        if self._health_check_task is not None:
            return

        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info(
            "A2A health checks started (interval=%.0fs)",
            self._health_check_interval,
        )

    async def stop_health_checks(self) -> None:
        """Stop periodic background health checks."""
        if self._health_check_task is not None:
            self._health_check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_check_task
            self._health_check_task = None
            logger.info("A2A health checks stopped")

    async def _health_check_loop(self) -> None:
        """Background loop for periodic health checks."""
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self.check_health()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Error during A2A health check loop")

    # ── Shutdown ────────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """Disconnect all agents and stop health checks."""
        await self.stop_health_checks()
        for name in list(self._clients):
            await self.unregister_agent(name)
        logger.info("A2A agent registry shut down")

    # ── Access control helpers ──────────────────────────────────────────

    @staticmethod
    def _has_team_access(config: A2AAgentConfig, team: str) -> bool:
        """Check if a team has access to an agent."""
        if config.visibility == A2AVisibility.PUBLIC:
            return True
        return team in config.allowed_teams
