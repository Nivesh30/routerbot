"""MCP client for communicating with MCP servers.

Supports SSE and Streamable HTTP transports using httpx.
STDIO transport creates a subprocess for the MCP server.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

import httpx

from routerbot.core.mcp.models import (
    MCPServerConfig,
    MCPServerHealth,
    MCPTool,
    MCPToolInputSchema,
    MCPToolParameter,
    MCPToolResult,
    MCPTransport,
)

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    """Error communicating with an MCP server."""


class MCPClient:
    """Client for a single MCP server.

    Handles the connection lifecycle and provides methods to:
    - Initialize and negotiate capabilities
    - List available tools
    - Call tools and return results
    - Check server health

    Parameters
    ----------
    config:
        MCP server configuration.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._tools: list[MCPTool] = []
        self._health = MCPServerHealth.UNKNOWN
        self._http_client: httpx.AsyncClient | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._initialized = False
        self._request_id = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def server_name(self) -> str:
        return self._config.name

    @property
    def health(self) -> MCPServerHealth:
        return self._health

    @property
    def tools(self) -> list[MCPTool]:
        return list(self._tools)

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish a connection to the MCP server and initialize."""
        self._health = MCPServerHealth.CONNECTING
        try:
            if self._config.transport in (MCPTransport.SSE, MCPTransport.STREAMABLE_HTTP):
                await self._connect_http()
            elif self._config.transport == MCPTransport.STDIO:
                await self._connect_stdio()
            else:
                msg = f"Unsupported transport: {self._config.transport}"
                raise MCPClientError(msg)

            # Initialize the MCP session
            await self._initialize()

            # Discover tools
            await self._discover_tools()

            self._health = MCPServerHealth.HEALTHY
            self._initialized = True
            logger.info(
                "MCP server '%s' connected — %d tools available",
                self.server_name,
                len(self._tools),
            )
        except Exception as exc:
            self._health = MCPServerHealth.UNHEALTHY
            logger.error("Failed to connect to MCP server '%s': %s", self.server_name, exc)
            raise MCPClientError(f"Failed to connect to MCP server '{self.server_name}': {exc}") from exc

    async def disconnect(self) -> None:
        """Close the connection to the MCP server."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

        if self._process is not None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()
            self._process = None

        self._initialized = False
        self._health = MCPServerHealth.UNKNOWN
        logger.info("MCP server '%s' disconnected", self.server_name)

    # ------------------------------------------------------------------
    # Tool operations
    # ------------------------------------------------------------------

    async def list_tools(self) -> list[MCPTool]:
        """Return the tools available on this MCP server."""
        if not self._initialized:
            await self.connect()
        return list(self._tools)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> MCPToolResult:
        """Call a tool on the MCP server.

        Parameters
        ----------
        tool_name:
            Name of the tool to call.
        arguments:
            Tool arguments (JSON-serializable dict).

        Returns
        -------
        MCPToolResult
            The result from the tool execution.

        Raises
        ------
        MCPClientError
            If the tool call fails.
        """
        if not self._initialized:
            await self.connect()

        request = self._build_jsonrpc(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments or {},
            },
        )

        try:
            response = await self._send_request(request)
        except Exception as exc:
            logger.error(
                "MCP tool call failed: server='%s', tool='%s': %s",
                self.server_name,
                tool_name,
                exc,
            )
            return MCPToolResult(
                server_name=self.server_name,
                tool_name=tool_name,
                content=[{"type": "text", "text": f"Error: {exc}"}],
                is_error=True,
            )

        # Parse the result
        result = response.get("result", {})
        content = result.get("content", [])
        is_error = result.get("isError", False)

        return MCPToolResult(
            server_name=self.server_name,
            tool_name=tool_name,
            content=content,
            is_error=is_error,
        )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def check_health(self) -> MCPServerHealth:
        """Ping the MCP server and return its health status."""
        try:
            request = self._build_jsonrpc("ping", {})
            await self._send_request(request)
            self._health = MCPServerHealth.HEALTHY
        except Exception as exc:
            logger.warning("Health check failed for MCP server '%s': %s", self.server_name, exc)
            self._health = MCPServerHealth.UNHEALTHY
        return self._health

    # ------------------------------------------------------------------
    # Internal - connection setup
    # ------------------------------------------------------------------

    async def _connect_http(self) -> None:
        """Set up an HTTP client for SSE/HTTP transport."""
        url = self._config.url
        if not url:
            msg = f"MCP server '{self.server_name}' requires a URL for {self._config.transport} transport"
            raise MCPClientError(msg)

        self._http_client = httpx.AsyncClient(
            base_url=url.rstrip("/"),
            timeout=httpx.Timeout(self._config.timeout),
            headers=self._config.headers,
        )

    async def _connect_stdio(self) -> None:
        """Start a subprocess for STDIO transport."""
        command = self._config.command
        if not command:
            msg = f"MCP server '{self.server_name}' requires a command for stdio transport"
            raise MCPClientError(msg)

        import shlex

        cmd_parts = shlex.split(command) + self._config.args
        env = {**dict(__import__("os").environ), **self._config.env} if self._config.env else None

        self._process = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

    # ------------------------------------------------------------------
    # Internal - MCP protocol
    # ------------------------------------------------------------------

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _build_jsonrpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Build a JSON-RPC 2.0 request."""
        return {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params,
        }

    async def _initialize(self) -> None:
        """Send the MCP initialize request."""
        request = self._build_jsonrpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "routerbot",
                    "version": "0.1.0",
                },
            },
        )
        response = await self._send_request(request)

        # Validate server capabilities
        result = response.get("result", {})
        server_info = result.get("serverInfo", {})
        logger.debug(
            "MCP server '%s' initialized: %s v%s",
            self.server_name,
            server_info.get("name", "unknown"),
            server_info.get("version", "unknown"),
        )

        # Send initialized notification
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        await self._send_notification(notification)

    async def _discover_tools(self) -> None:
        """Discover available tools on the MCP server."""
        request = self._build_jsonrpc("tools/list", {})
        response = await self._send_request(request)

        result = response.get("result", {})
        raw_tools = result.get("tools", [])

        self._tools = []
        for tool_data in raw_tools:
            input_schema_data = tool_data.get("inputSchema", {})
            properties = {}
            for prop_name, prop_data in input_schema_data.get("properties", {}).items():
                properties[prop_name] = MCPToolParameter(
                    type=prop_data.get("type", "string"),
                    description=prop_data.get("description", ""),
                    enum=prop_data.get("enum"),
                    default=prop_data.get("default"),
                )

            input_schema = MCPToolInputSchema(
                type=input_schema_data.get("type", "object"),
                properties=properties,
                required=input_schema_data.get("required", []),
            )

            self._tools.append(
                MCPTool(
                    name=tool_data["name"],
                    description=tool_data.get("description", ""),
                    input_schema=input_schema,
                    server_name=self.server_name,
                )
            )

    # ------------------------------------------------------------------
    # Internal - transport layer
    # ------------------------------------------------------------------

    async def _send_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and return the response."""
        if self._config.transport in (MCPTransport.SSE, MCPTransport.STREAMABLE_HTTP):
            return await self._send_http_request(request)
        if self._config.transport == MCPTransport.STDIO:
            return await self._send_stdio_request(request)
        msg = f"Unsupported transport: {self._config.transport}"
        raise MCPClientError(msg)

    async def _send_http_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request over HTTP."""
        if self._http_client is None:
            msg = "HTTP client not initialized"
            raise MCPClientError(msg)

        try:
            response = await self._http_client.post(
                "/",
                json=request,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            msg = f"HTTP error from MCP server '{self.server_name}': {exc.response.status_code}"
            raise MCPClientError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"Connection error to MCP server '{self.server_name}': {exc}"
            raise MCPClientError(msg) from exc

        if "error" in data:
            error = data["error"]
            msg = f"MCP error: [{error.get('code', -1)}] {error.get('message', 'Unknown error')}"
            raise MCPClientError(msg)

        return data

    async def _send_stdio_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request over STDIO."""
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            msg = "STDIO process not initialized"
            raise MCPClientError(msg)

        # Write request
        payload = json.dumps(request) + "\n"
        self._process.stdin.write(payload.encode())
        await self._process.stdin.drain()

        # Read response
        try:
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=self._config.timeout,
            )
        except TimeoutError as exc:
            msg = f"STDIO timeout from MCP server '{self.server_name}'"
            raise MCPClientError(msg) from exc

        if not line:
            msg = f"STDIO EOF from MCP server '{self.server_name}'"
            raise MCPClientError(msg)

        data = json.loads(line.decode())
        if "error" in data:
            error = data["error"]
            msg = f"MCP error: [{error.get('code', -1)}] {error.get('message', 'Unknown error')}"
            raise MCPClientError(msg)

        return data

    async def _send_notification(self, notification: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if self._config.transport in (MCPTransport.SSE, MCPTransport.STREAMABLE_HTTP):
            if self._http_client is not None:
                with contextlib.suppress(httpx.HTTPError):
                    await self._http_client.post(
                        "/",
                        json=notification,
                        headers={"Content-Type": "application/json"},
                    )
        elif (
            self._config.transport == MCPTransport.STDIO
            and self._process is not None
            and self._process.stdin is not None
        ):
            payload = json.dumps(notification) + "\n"
            self._process.stdin.write(payload.encode())
            await self._process.stdin.drain()
