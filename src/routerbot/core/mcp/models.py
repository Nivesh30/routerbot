"""MCP data models and configuration types.

Defines the Pydantic models for MCP server configuration, tool definitions,
tool calls, and results.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────────────


class MCPTransport(StrEnum):
    """Supported MCP transport types."""

    SSE = "sse"
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable-http"


class MCPServerHealth(StrEnum):
    """MCP server health state."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CONNECTING = "connecting"


class MCPVisibility(StrEnum):
    """MCP server visibility scope."""

    PUBLIC = "public"
    PRIVATE = "private"


# ── Configuration ──────────────────────────────────────────────────────────


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server.

    Matches the YAML config format::

        mcp_servers:
          - name: "github"
            transport: "sse"
            url: "http://github-mcp:3000/sse"
            visibility: "public"
    """

    name: str = Field(..., description="Unique server name (used as identifier)")
    transport: MCPTransport = Field(MCPTransport.SSE, description="Transport protocol")
    url: str | None = Field(None, description="Server URL (for SSE/HTTP transports)")
    command: str | None = Field(None, description="Command to start server (for STDIO transport)")
    args: list[str] = Field(default_factory=list, description="Arguments for STDIO command")
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables for STDIO")
    visibility: MCPVisibility = Field(MCPVisibility.PUBLIC, description="Access visibility")
    allowed_teams: list[str] = Field(default_factory=list, description="Teams with access (if private)")
    headers: dict[str, str] = Field(default_factory=dict, description="Custom headers for HTTP/SSE")
    timeout: float = Field(30.0, description="Request timeout in seconds")
    enabled: bool = Field(True, description="Whether this server is active")

    model_config = {"extra": "allow"}


# ── Tool definitions ───────────────────────────────────────────────────────


class MCPToolParameter(BaseModel):
    """A parameter in an MCP tool's input schema."""

    type: str = Field("string", description="JSON Schema type")
    description: str = Field("", description="Parameter description")
    enum: list[str] | None = Field(None, description="Allowed values")
    default: Any = Field(None, description="Default value")


class MCPToolInputSchema(BaseModel):
    """JSON Schema for MCP tool input."""

    type: str = Field("object")
    properties: dict[str, MCPToolParameter] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class MCPTool(BaseModel):
    """A tool exposed by an MCP server.

    Maps to the MCP ``Tool`` type from the protocol spec.
    """

    name: str = Field(..., description="Tool name (unique within a server)")
    description: str = Field("", description="Human-readable description")
    input_schema: MCPToolInputSchema = Field(
        default_factory=MCPToolInputSchema,
        alias="inputSchema",
        description="JSON Schema for tool arguments",
    )
    server_name: str = Field("", description="Name of the MCP server providing this tool")

    model_config = {"populate_by_name": True}

    def to_openai_function(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format.

        Returns a dict suitable for the ``tools`` array in a chat completion
        request.
        """
        return {
            "type": "function",
            "function": {
                "name": f"{self.server_name}__{self.name}" if self.server_name else self.name,
                "description": self.description,
                "parameters": self.input_schema.model_dump(exclude_none=True),
            },
        }


# ── Tool calls and results ─────────────────────────────────────────────────


class MCPToolCall(BaseModel):
    """A request to call an MCP tool."""

    server_name: str = Field(..., description="MCP server name")
    tool_name: str = Field(..., description="Tool name on the server")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")

    model_config = {"extra": "allow"}


class MCPToolResult(BaseModel):
    """Result from an MCP tool call."""

    server_name: str = Field(..., description="MCP server that executed the tool")
    tool_name: str = Field(..., description="Tool that was called")
    content: list[dict[str, Any]] = Field(default_factory=list, description="Result content items")
    is_error: bool = Field(False, description="Whether the result is an error")


# ── Server status ──────────────────────────────────────────────────────────


class MCPServerStatus(BaseModel):
    """Runtime status of an MCP server."""

    name: str
    transport: MCPTransport
    health: MCPServerHealth = MCPServerHealth.UNKNOWN
    tools_count: int = 0
    last_health_check: float | None = None
    error: str | None = None
    enabled: bool = True
