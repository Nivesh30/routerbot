"""MCP server registry — manages configured MCP servers.

Provides:
- Server registration and lookup
- Tool discovery across all servers
- Health checking with periodic background tasks
- Team-based access control
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from routerbot.core.mcp.client import MCPClient, MCPClientError
from routerbot.core.mcp.models import (
    MCPServerConfig,
    MCPServerHealth,
    MCPServerStatus,
    MCPTool,
    MCPToolCall,
    MCPToolResult,
)

logger = logging.getLogger(__name__)


class MCPServerRegistry:
    """Registry for managing MCP server connections.

    Maintains a pool of MCP clients and provides unified access to
    tools across all servers.

    Parameters
    ----------
    health_check_interval:
        Seconds between automatic health checks (0 to disable).
    """

    def __init__(self, health_check_interval: float = 300.0) -> None:
        self._servers: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}
        self._health_check_interval = health_check_interval
        self._health_check_task: asyncio.Task[None] | None = None
        self._last_health_check: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Server management
    # ------------------------------------------------------------------

    async def register_server(self, config: MCPServerConfig) -> None:
        """Register and connect to an MCP server.

        Parameters
        ----------
        config:
            Configuration for the MCP server.

        Raises
        ------
        MCPClientError
            If the initial connection fails.
        """
        name = config.name

        # If already registered, disconnect first
        if name in self._clients:
            await self.unregister_server(name)

        self._servers[name] = config
        client = MCPClient(config)

        if config.enabled:
            try:
                await client.connect()
            except MCPClientError:
                logger.warning("MCP server '%s' registered but initial connection failed", name)

        self._clients[name] = client
        logger.info("MCP server '%s' registered (enabled=%s)", name, config.enabled)

    async def unregister_server(self, name: str) -> None:
        """Remove and disconnect an MCP server."""
        client = self._clients.pop(name, None)
        self._servers.pop(name, None)
        self._last_health_check.pop(name, None)

        if client is not None:
            await client.disconnect()
            logger.info("MCP server '%s' unregistered", name)

    async def register_from_config(self, configs: list[MCPServerConfig]) -> None:
        """Register multiple servers from config."""
        for config in configs:
            try:
                await self.register_server(config)
            except Exception as exc:
                logger.error("Failed to register MCP server '%s': %s", config.name, exc)

    # ------------------------------------------------------------------
    # Tool access
    # ------------------------------------------------------------------

    async def list_tools(
        self,
        server_name: str | None = None,
        team: str | None = None,
    ) -> list[MCPTool]:
        """List available MCP tools.

        Parameters
        ----------
        server_name:
            If provided, only list tools from this server.
        team:
            If provided, filter to tools accessible by this team.

        Returns
        -------
        list[MCPTool]
            Available tools.
        """
        tools: list[MCPTool] = []

        for name, client in self._clients.items():
            config = self._servers.get(name)
            if config is None or not config.enabled:
                continue

            # Apply server_name filter
            if server_name and name != server_name:
                continue

            # Apply team access control
            if team and not self._has_team_access(config, team):
                continue

            if client.is_initialized:
                tools.extend(client.tools)

        return tools

    async def call_tool(self, call: MCPToolCall) -> MCPToolResult:
        """Call a tool on a specific MCP server.

        Parameters
        ----------
        call:
            The tool call request.

        Returns
        -------
        MCPToolResult
            The result from the tool execution.
        """
        client = self._clients.get(call.server_name)
        if client is None:
            return MCPToolResult(
                server_name=call.server_name,
                tool_name=call.tool_name,
                content=[{"type": "text", "text": f"MCP server '{call.server_name}' not found"}],
                is_error=True,
            )

        config = self._servers.get(call.server_name)
        if config is None or not config.enabled:
            return MCPToolResult(
                server_name=call.server_name,
                tool_name=call.tool_name,
                content=[{"type": "text", "text": f"MCP server '{call.server_name}' is disabled"}],
                is_error=True,
            )

        return await client.call_tool(call.tool_name, call.arguments)

    def resolve_tool_call(self, function_name: str) -> tuple[str, str] | None:
        """Resolve an OpenAI-style function name to (server_name, tool_name).

        Function names from ``MCPTool.to_openai_function()`` use the format
        ``{server_name}__{tool_name}``.

        Returns
        -------
        tuple[str, str] | None
            ``(server_name, tool_name)`` or ``None`` if not resolvable.
        """
        if "__" in function_name:
            server_name, tool_name = function_name.split("__", 1)
            if server_name in self._clients:
                return server_name, tool_name
        return None

    # ------------------------------------------------------------------
    # Status and health
    # ------------------------------------------------------------------

    def get_server_status(self, name: str) -> MCPServerStatus | None:
        """Get the status of a specific MCP server."""
        config = self._servers.get(name)
        client = self._clients.get(name)
        if config is None or client is None:
            return None

        return MCPServerStatus(
            name=name,
            transport=config.transport,
            health=client.health,
            tools_count=len(client.tools),
            last_health_check=self._last_health_check.get(name),
            enabled=config.enabled,
        )

    def list_servers(self) -> list[MCPServerStatus]:
        """Get status of all registered MCP servers."""
        statuses = []
        for name in self._servers:
            status = self.get_server_status(name)
            if status is not None:
                statuses.append(status)
        return statuses

    async def check_health(self, name: str | None = None) -> dict[str, MCPServerHealth]:
        """Run health checks on MCP servers.

        Parameters
        ----------
        name:
            If provided, only check this server. Otherwise check all.

        Returns
        -------
        dict[str, MCPServerHealth]
            Health status for each checked server.
        """
        results: dict[str, MCPServerHealth] = {}
        targets = [name] if name else list(self._clients.keys())

        for server_name in targets:
            client = self._clients.get(server_name)
            if client is None:
                continue

            health = await client.check_health()
            self._last_health_check[server_name] = time.time()
            results[server_name] = health

        return results

    # ------------------------------------------------------------------
    # Background health checking
    # ------------------------------------------------------------------

    async def start_health_checks(self) -> None:
        """Start periodic background health checks."""
        if self._health_check_interval <= 0:
            return

        if self._health_check_task is not None:
            return

        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info(
            "MCP health checks started (interval=%ss)",
            self._health_check_interval,
        )

    async def stop_health_checks(self) -> None:
        """Stop periodic background health checks."""
        if self._health_check_task is not None:
            self._health_check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_check_task
            self._health_check_task = None
            logger.info("MCP health checks stopped")

    async def _health_check_loop(self) -> None:
        """Background loop for periodic health checks."""
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self.check_health()
                logger.debug("MCP health check completed for %d servers", len(self._clients))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("MCP health check error: %s", exc)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Disconnect all servers and stop health checks."""
        await self.stop_health_checks()

        for name in list(self._clients.keys()):
            await self.unregister_server(name)

        logger.info("MCP registry shut down")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_team_access(config: MCPServerConfig, team: str) -> bool:
        """Check if a team has access to the server."""
        if config.visibility == "public":
            return True
        return team in config.allowed_teams

    # ------------------------------------------------------------------
    # Iteration
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._servers)

    def __contains__(self, name: str) -> bool:
        return name in self._servers

    def get_client(self, name: str) -> MCPClient | None:
        """Return the MCPClient for a given server, or None."""
        return self._clients.get(name)
