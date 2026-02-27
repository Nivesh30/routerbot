"""MCP (Model Context Protocol) integration package.

Provides:
- MCP client for connecting to MCP servers
- MCP server registry for managing server configurations
- MCP tool routing for exposing MCP tools to LLM function calling
"""

from routerbot.core.mcp.models import (
    MCPServerConfig,
    MCPServerStatus,
    MCPTool,
    MCPToolCall,
    MCPToolResult,
)
from routerbot.core.mcp.registry import MCPServerRegistry

__all__ = [
    "MCPServerConfig",
    "MCPServerRegistry",
    "MCPServerStatus",
    "MCPTool",
    "MCPToolCall",
    "MCPToolResult",
]
