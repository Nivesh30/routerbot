"""MCP Gateway routes — tool discovery and invocation.

Provides:
- ``POST /v1/mcp/tools``  — List available MCP tools
- ``POST /v1/mcp/call``   — Call an MCP tool directly
- ``GET  /v1/mcp/servers`` — List MCP server status
- ``POST /v1/mcp/health``  — Trigger health check
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from routerbot.core.mcp.models import MCPToolCall

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["MCP Gateway"])


# ── Request/Response schemas ───────────────────────────────────────────────


class ListToolsRequest(BaseModel):
    """Request body for listing MCP tools."""

    server_name: str | None = Field(None, description="Filter to a specific MCP server")
    team: str | None = Field(None, description="Filter to tools accessible by this team")


class ToolCallRequest(BaseModel):
    """Request body for calling an MCP tool."""

    server_name: str = Field(..., description="MCP server name")
    tool_name: str = Field(..., description="Tool to call")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class HealthCheckRequest(BaseModel):
    """Request body for triggering a health check."""

    server_name: str | None = Field(None, description="Server to check (None = all)")


# ── Helper ─────────────────────────────────────────────────────────────────


def _get_registry(request: Request) -> Any:
    """Get the MCP registry from app state."""
    state = getattr(request.app.state, "routerbot", None)
    if state is None:
        return None
    return getattr(state, "mcp_registry", None)


# ── Routes ─────────────────────────────────────────────────────────────────


@router.post("/tools", response_model=None)
async def list_tools(request: Request, body: ListToolsRequest | None = None) -> JSONResponse:
    """List available MCP tools across all connected servers.

    Optionally filter by server name or team.
    """
    registry = _get_registry(request)
    if registry is None:
        return JSONResponse(
            status_code=503,
            content={"error": "MCP gateway not configured"},
        )

    body = body or ListToolsRequest()
    tools = await registry.list_tools(
        server_name=body.server_name,
        team=body.team,
    )

    return JSONResponse(
        content={
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "server_name": t.server_name,
                    "input_schema": t.input_schema.model_dump(exclude_none=True),
                    "openai_function": t.to_openai_function(),
                }
                for t in tools
            ],
            "total": len(tools),
        }
    )


@router.post("/call", response_model=None)
async def call_tool(request: Request, body: ToolCallRequest) -> JSONResponse:
    """Call an MCP tool directly.

    The request specifies which server and tool to call, along with
    the arguments.
    """
    registry = _get_registry(request)
    if registry is None:
        return JSONResponse(
            status_code=503,
            content={"error": "MCP gateway not configured"},
        )

    tool_call = MCPToolCall(
        server_name=body.server_name,
        tool_name=body.tool_name,
        arguments=body.arguments,
    )

    result = await registry.call_tool(tool_call)

    status_code = 200 if not result.is_error else 422
    return JSONResponse(
        status_code=status_code,
        content={
            "server_name": result.server_name,
            "tool_name": result.tool_name,
            "content": result.content,
            "is_error": result.is_error,
        },
    )


@router.get("/servers", response_model=None)
async def list_servers(request: Request) -> JSONResponse:
    """List all registered MCP servers and their status."""
    registry = _get_registry(request)
    if registry is None:
        return JSONResponse(
            status_code=503,
            content={"error": "MCP gateway not configured"},
        )

    servers = registry.list_servers()
    return JSONResponse(
        content={
            "servers": [s.model_dump() for s in servers],
            "total": len(servers),
        }
    )


@router.post("/health", response_model=None)
async def check_health(request: Request, body: HealthCheckRequest | None = None) -> JSONResponse:
    """Trigger a health check on MCP servers.

    If ``server_name`` is provided, only that server is checked.
    Otherwise, all servers are checked.
    """
    registry = _get_registry(request)
    if registry is None:
        return JSONResponse(
            status_code=503,
            content={"error": "MCP gateway not configured"},
        )

    body = body or HealthCheckRequest()
    results = await registry.check_health(name=body.server_name)

    return JSONResponse(
        content={
            "results": {name: health.value for name, health in results.items()},
        }
    )
