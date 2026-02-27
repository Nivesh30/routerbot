"""A2A agent client — communicates with individual A2A agents.

Handles:
- Agent health checks (GET /health or HEAD /)
- Agent invocation (POST /invoke or POST /tasks/send)
- Agent card fetching (GET /.well-known/agent.json)
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from routerbot.core.a2a.models import (
    A2AAgentCard,
    A2AAgentConfig,
    A2AAgentHealth,
    A2AAgentSkill,
    A2AInvocationResult,
    A2AMessage,
)

logger = logging.getLogger(__name__)


class A2AClientError(Exception):
    """Error communicating with an A2A agent."""


class A2AClient:
    """Client for a single A2A agent.

    Lifecycle:
        client = A2AClient(config)
        await client.connect()          # fetch agent card
        result = await client.invoke(…)  # call the agent
        await client.disconnect()
    """

    def __init__(self, config: A2AAgentConfig) -> None:
        self._config = config
        self._http_client: httpx.AsyncClient | None = None
        self._agent_card: A2AAgentCard | None = None
        self._health: A2AAgentHealth = A2AAgentHealth.UNKNOWN
        self._initialized: bool = False
        self._last_health_check: float | None = None

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def agent_name(self) -> str:
        return self._config.name

    @property
    def health(self) -> A2AAgentHealth:
        return self._health

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def agent_card(self) -> A2AAgentCard | None:
        return self._agent_card

    @property
    def last_health_check(self) -> float | None:
        return self._last_health_check

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Connect to the agent and fetch its agent card."""
        try:
            self._health = A2AAgentHealth.CONNECTING
            self._http_client = httpx.AsyncClient(
                base_url=self._config.url,
                timeout=self._config.timeout,
                headers=self._config.headers or {},
            )

            # Try to fetch the well-known agent card
            await self._fetch_agent_card()
            self._initialized = True
            self._health = A2AAgentHealth.HEALTHY
            logger.info("A2A agent '%s' connected at %s", self.agent_name, self._config.url)
        except Exception as exc:
            self._health = A2AAgentHealth.UNHEALTHY
            msg = f"Failed to connect to A2A agent '{self.agent_name}': {exc}"
            raise A2AClientError(msg) from exc

    async def disconnect(self) -> None:
        """Disconnect from the agent."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        self._initialized = False
        self._health = A2AAgentHealth.UNKNOWN
        logger.info("A2A agent '%s' disconnected", self.agent_name)

    # ── Agent Card ──────────────────────────────────────────────────────

    async def _fetch_agent_card(self) -> None:
        """Fetch the agent card from /.well-known/agent.json.

        Falls back to building a card from config if the endpoint
        is unavailable.
        """
        if self._http_client is None:
            msg = "HTTP client not initialised"
            raise A2AClientError(msg)

        try:
            resp = await self._http_client.get("/.well-known/agent.json")
            resp.raise_for_status()
            data = resp.json()

            # Parse skills from the card
            skills: list[A2AAgentSkill] = []
            for s in data.get("skills", []):
                skills.append(
                    A2AAgentSkill(
                        id=s.get("id", s.get("name", "")),
                        name=s.get("name", ""),
                        description=s.get("description", ""),
                        tags=s.get("tags", []),
                        examples=s.get("examples", []),
                    )
                )

            self._agent_card = A2AAgentCard(
                name=data.get("name", self._config.name),
                description=data.get("description", self._config.description),
                url=str(self._config.url),
                version=data.get("version", self._config.version),
                framework=self._config.framework,
                skills=skills,
                authentication=data.get("authentication", {}),
                metadata=data.get("metadata", {}),
            )
        except (httpx.HTTPError, KeyError, ValueError):
            # Build card from config as fallback
            logger.debug("Could not fetch agent card for '%s', using config", self.agent_name)
            self._build_card_from_config()

    def _build_card_from_config(self) -> None:
        """Build an agent card from the configuration entry."""
        skills: list[A2AAgentSkill] = []
        for s in self._config.skills:
            skills.append(
                A2AAgentSkill(
                    id=s.get("id", s.get("name", "")),
                    name=s.get("name", ""),
                    description=s.get("description", ""),
                    tags=s.get("tags", []),
                    examples=s.get("examples", []),
                )
            )

        self._agent_card = A2AAgentCard(
            name=self._config.name,
            description=self._config.description,
            url=self._config.url,
            version=self._config.version,
            framework=self._config.framework,
            skills=skills,
        )

    # ── Invocation ──────────────────────────────────────────────────────

    async def invoke(
        self,
        messages: list[dict[str, Any]] | None = None,
        input_data: dict[str, Any] | None = None,
        skill_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> A2AInvocationResult:
        """Invoke the agent with the given input.

        Tries POST /tasks/send (A2A protocol), then falls back to
        POST /invoke (generic), then POST / (bare endpoint).
        """
        if not self._initialized or self._http_client is None:
            return A2AInvocationResult(
                agent_name=self.agent_name,
                status="error",
                is_error=True,
                error_message=f"Agent '{self.agent_name}' is not connected",
            )

        payload: dict[str, Any] = {
            "messages": messages or [],
            "input": input_data or {},
            "metadata": metadata or {},
        }
        if skill_id:
            payload["skill_id"] = skill_id

        # Try A2A protocol endpoint, then generic, then root
        for path in ("/tasks/send", "/invoke", "/"):
            try:
                resp = await self._http_client.post(
                    path,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                return self._parse_response(resp.json())
            except httpx.HTTPStatusError:
                continue
            except httpx.HTTPError as exc:
                return A2AInvocationResult(
                    agent_name=self.agent_name,
                    status="error",
                    is_error=True,
                    error_message=f"HTTP error invoking '{self.agent_name}': {exc}",
                )

        return A2AInvocationResult(
            agent_name=self.agent_name,
            status="error",
            is_error=True,
            error_message=f"No invocation endpoint found on agent '{self.agent_name}'",
        )

    def _parse_response(self, data: dict[str, Any]) -> A2AInvocationResult:
        """Parse the invocation response into an A2AInvocationResult."""
        messages: list[A2AMessage] = []
        for m in data.get("messages", []):
            messages.append(
                A2AMessage(
                    role=m.get("role", "agent"),
                    content=m.get("content", ""),
                    metadata=m.get("metadata", {}),
                )
            )

        return A2AInvocationResult(
            agent_name=self.agent_name,
            status=data.get("status", "completed"),
            messages=messages,
            output_data=data.get("output", data.get("output_data", {})),
            is_error=data.get("is_error", False),
            error_message=data.get("error_message"),
            metadata=data.get("metadata", {}),
        )

    # ── Health ──────────────────────────────────────────────────────────

    async def check_health(self) -> A2AAgentHealth:
        """Check agent health via GET /health or HEAD /."""
        if self._http_client is None:
            self._health = A2AAgentHealth.UNHEALTHY
            self._last_health_check = time.time()
            return self._health

        for method, path in [("GET", "/health"), ("HEAD", "/")]:
            try:
                if method == "GET":
                    resp = await self._http_client.get(path, timeout=10.0)
                else:
                    resp = await self._http_client.head(path, timeout=10.0)

                if resp.status_code < 500:
                    self._health = A2AAgentHealth.HEALTHY
                    self._last_health_check = time.time()
                    return self._health
            except httpx.HTTPError:
                continue

        self._health = A2AAgentHealth.UNHEALTHY
        self._last_health_check = time.time()
        return self._health
