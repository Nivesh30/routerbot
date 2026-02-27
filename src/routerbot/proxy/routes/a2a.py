"""A2A gateway routes — agent discovery, invocation, status, and health.

Endpoints:
    GET  /v1/a2a/agents         — Discover available agents
    GET  /v1/a2a/agents/{name}  — Get a specific agent card
    POST /v1/a2a/invoke         — Invoke an agent
    GET  /v1/a2a/status         — List agent statuses
    POST /v1/a2a/health         — Trigger health checks
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from routerbot.core.a2a.models import (
    A2AInvocationRequest,
)

if TYPE_CHECKING:
    from routerbot.core.a2a.registry import A2AAgentRegistry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["a2a"])


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _get_registry(request: Request) -> A2AAgentRegistry | None:
    """Get the A2A registry from application state."""
    state = getattr(request.app.state, "routerbot", None)
    if state is None:
        return None
    return getattr(state, "a2a_registry", None)


def _no_registry_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error": "A2A gateway not configured"},
    )


# ═══════════════════════════════════════════════════════════════════════════
# Discovery
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/a2a/agents", response_model=None)
async def discover_agents(
    request: Request,
    team: str | None = None,
    skill_tag: str | None = None,
) -> JSONResponse:
    """Discover available A2A agents.

    Query params:
        team: Filter by team access.
        skill_tag: Filter by skill tag.
    """
    registry = _get_registry(request)
    if registry is None:
        return _no_registry_response()

    cards = registry.discover_agents(team=team, skill_tag=skill_tag)

    return JSONResponse(
        content={
            "agents": [card.model_dump() for card in cards],
            "total": len(cards),
        }
    )


@router.get("/a2a/agents/{name}", response_model=None)
async def get_agent_card(request: Request, name: str) -> JSONResponse:
    """Get the agent card for a specific agent."""
    registry = _get_registry(request)
    if registry is None:
        return _no_registry_response()

    card = registry.get_agent_card(name)
    if card is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"Agent '{name}' not found"},
        )

    return JSONResponse(content=card.model_dump())


# ═══════════════════════════════════════════════════════════════════════════
# Invocation
# ═══════════════════════════════════════════════════════════════════════════


class InvokeRequest(A2AInvocationRequest):
    """Request body for agent invocation."""


@router.post("/a2a/invoke", response_model=None)
async def invoke_agent(request: Request, body: InvokeRequest) -> JSONResponse:
    """Invoke an A2A agent."""
    registry = _get_registry(request)
    if registry is None:
        return _no_registry_response()

    result = await registry.invoke_agent(body)

    status_code = 200
    if result.is_error:
        status_code = 422

    return JSONResponse(
        status_code=status_code,
        content=result.model_dump(),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Status & Health
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/a2a/status", response_model=None)
async def list_agent_status(request: Request) -> JSONResponse:
    """List status for all registered agents."""
    registry = _get_registry(request)
    if registry is None:
        return _no_registry_response()

    statuses = registry.list_agents()

    return JSONResponse(
        content={
            "agents": [s.model_dump() for s in statuses],
            "total": len(statuses),
        }
    )


class HealthCheckRequest(A2AInvocationRequest):
    """Reuse model but only use agent_name field."""


@router.post("/a2a/health", response_model=None)
async def check_health(
    request: Request,
    body: dict[str, Any] | None = None,
) -> JSONResponse:
    """Trigger health checks on A2A agents.

    Body (optional):
        {"agent_name": "specific-agent"}  — check one agent
        {} or omitted — check all agents
    """
    registry = _get_registry(request)
    if registry is None:
        return _no_registry_response()

    agent_name = None
    if body:
        agent_name = body.get("agent_name")

    results = await registry.check_health(name=agent_name)

    return JSONResponse(
        content={
            "results": {k: v.value for k, v in results.items()},
        }
    )
