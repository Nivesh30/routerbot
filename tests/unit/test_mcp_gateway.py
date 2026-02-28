"""Tests for MCP Gateway integration (Task 8A).

Covers:
- MCPServerConfig and model validation
- MCPTool to OpenAI function conversion
- MCPClient: connect, list_tools, call_tool, health check
- MCPServerRegistry: registration, tool listing, team access, health
- MCP gateway routes: /v1/mcp/tools, /v1/mcp/call, /v1/mcp/servers, /v1/mcp/health
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from routerbot.core.mcp.client import MCPClient, MCPClientError
from routerbot.core.mcp.models import (
    MCPServerConfig,
    MCPServerHealth,
    MCPServerStatus,
    MCPTool,
    MCPToolCall,
    MCPToolInputSchema,
    MCPToolParameter,
    MCPToolResult,
    MCPTransport,
    MCPVisibility,
)
from routerbot.core.mcp.registry import MCPServerRegistry

# ═══════════════════════════════════════════════════════════════════════════
# MCPServerConfig tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMCPServerConfig:
    def test_minimal_config(self) -> None:
        config = MCPServerConfig(name="test-server")
        assert config.name == "test-server"
        assert config.transport == MCPTransport.SSE
        assert config.url is None
        assert config.visibility == MCPVisibility.PUBLIC
        assert config.enabled is True
        assert config.timeout == 30.0

    def test_full_config(self) -> None:
        config = MCPServerConfig(
            name="github",
            transport="sse",
            url="http://github-mcp:3000/sse",
            visibility="private",
            allowed_teams=["dev-team"],
            headers={"Authorization": "Bearer token"},
            timeout=60.0,
        )
        assert config.transport == MCPTransport.SSE
        assert config.visibility == MCPVisibility.PRIVATE
        assert config.allowed_teams == ["dev-team"]
        assert config.headers == {"Authorization": "Bearer token"}

    def test_stdio_config(self) -> None:
        config = MCPServerConfig(
            name="local-db",
            transport="stdio",
            command="npx @internal/db-mcp",
            args=["--verbose"],
            env={"DB_HOST": "localhost"},
        )
        assert config.transport == MCPTransport.STDIO
        assert config.command == "npx @internal/db-mcp"
        assert config.args == ["--verbose"]
        assert config.env == {"DB_HOST": "localhost"}


# ═══════════════════════════════════════════════════════════════════════════
# MCPTool tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMCPTool:
    def test_to_openai_function(self) -> None:
        tool = MCPTool(
            name="get_file",
            description="Read a file from the repository",
            input_schema=MCPToolInputSchema(
                type="object",
                properties={
                    "path": MCPToolParameter(type="string", description="File path"),
                    "ref": MCPToolParameter(type="string", description="Git ref"),
                },
                required=["path"],
            ),
            server_name="github",
        )
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "github__get_file"
        assert fn["function"]["description"] == "Read a file from the repository"
        assert "path" in fn["function"]["parameters"]["properties"]

    def test_to_openai_function_no_server(self) -> None:
        tool = MCPTool(name="search", description="Search")
        fn = tool.to_openai_function()
        assert fn["function"]["name"] == "search"


class TestMCPToolResult:
    def test_success_result(self) -> None:
        result = MCPToolResult(
            server_name="test",
            tool_name="query",
            content=[{"type": "text", "text": "42"}],
        )
        assert not result.is_error
        assert result.content[0]["text"] == "42"

    def test_error_result(self) -> None:
        result = MCPToolResult(
            server_name="test",
            tool_name="query",
            content=[{"type": "text", "text": "Error: timeout"}],
            is_error=True,
        )
        assert result.is_error


# ═══════════════════════════════════════════════════════════════════════════
# MCPClient tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMCPClient:
    def test_init(self) -> None:
        config = MCPServerConfig(name="test", url="http://localhost:3000")
        client = MCPClient(config)
        assert client.server_name == "test"
        assert client.health == MCPServerHealth.UNKNOWN
        assert not client.is_initialized

    @pytest.mark.asyncio
    async def test_connect_http_success(self) -> None:
        config = MCPServerConfig(name="test", transport="sse", url="http://localhost:3000")
        client = MCPClient(config)

        # Mock the initialization sequence
        init_response = {"result": {"serverInfo": {"name": "TestMCP", "version": "1.0"}}}
        tools_response = {
            "result": {
                "tools": [
                    {
                        "name": "search",
                        "description": "Search stuff",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                ]
            }
        }

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = [init_response, tools_response]
            with patch.object(client, "_send_notification", new_callable=AsyncMock):
                await client.connect()

        assert client.is_initialized
        assert client.health == MCPServerHealth.HEALTHY
        assert len(client.tools) == 1
        assert client.tools[0].name == "search"

    @pytest.mark.asyncio
    async def test_connect_fails(self) -> None:
        config = MCPServerConfig(name="test", transport="sse", url="http://localhost:3000")
        client = MCPClient(config)

        with (
            patch.object(client, "_connect_http", new_callable=AsyncMock, side_effect=Exception("conn refused")),
            pytest.raises(MCPClientError, match="Failed to connect"),
        ):
            await client.connect()

        assert client.health == MCPServerHealth.UNHEALTHY
        assert not client.is_initialized

    @pytest.mark.asyncio
    async def test_connect_requires_url_for_http(self) -> None:
        config = MCPServerConfig(name="test", transport="sse")
        client = MCPClient(config)

        with pytest.raises(MCPClientError, match="requires a URL"):
            await client.connect()

    @pytest.mark.asyncio
    async def test_connect_requires_command_for_stdio(self) -> None:
        config = MCPServerConfig(name="test", transport="stdio")
        client = MCPClient(config)

        with pytest.raises(MCPClientError, match="requires a command"):
            await client.connect()

    @pytest.mark.asyncio
    async def test_call_tool(self) -> None:
        config = MCPServerConfig(name="test", url="http://localhost:3000")
        client = MCPClient(config)
        client._initialized = True

        call_response = {
            "result": {
                "content": [{"type": "text", "text": "hello world"}],
                "isError": False,
            }
        }

        with patch.object(client, "_send_request", new_callable=AsyncMock, return_value=call_response):
            result = await client.call_tool("greet", {"name": "Alice"})

        assert not result.is_error
        assert result.content[0]["text"] == "hello world"
        assert result.server_name == "test"

    @pytest.mark.asyncio
    async def test_call_tool_error(self) -> None:
        config = MCPServerConfig(name="test", url="http://localhost:3000")
        client = MCPClient(config)
        client._initialized = True

        with patch.object(client, "_send_request", new_callable=AsyncMock, side_effect=Exception("timeout")):
            result = await client.call_tool("broken", {})

        assert result.is_error
        assert "Error" in result.content[0]["text"]

    @pytest.mark.asyncio
    async def test_check_health_healthy(self) -> None:
        config = MCPServerConfig(name="test", url="http://localhost:3000")
        client = MCPClient(config)

        with patch.object(client, "_send_request", new_callable=AsyncMock, return_value={"result": {}}):
            health = await client.check_health()

        assert health == MCPServerHealth.HEALTHY

    @pytest.mark.asyncio
    async def test_check_health_unhealthy(self) -> None:
        config = MCPServerConfig(name="test", url="http://localhost:3000")
        client = MCPClient(config)

        with patch.object(client, "_send_request", new_callable=AsyncMock, side_effect=Exception("down")):
            health = await client.check_health()

        assert health == MCPServerHealth.UNHEALTHY

    @pytest.mark.asyncio
    async def test_disconnect(self) -> None:
        config = MCPServerConfig(name="test", url="http://localhost:3000")
        client = MCPClient(config)
        client._initialized = True
        mock_http = AsyncMock()
        client._http_client = mock_http

        await client.disconnect()

        assert not client.is_initialized
        assert client.health == MCPServerHealth.UNKNOWN
        mock_http.aclose.assert_called_once()

    def test_build_jsonrpc(self) -> None:
        config = MCPServerConfig(name="test")
        client = MCPClient(config)
        req = client._build_jsonrpc("tools/list", {"cursor": None})
        assert req["jsonrpc"] == "2.0"
        assert req["method"] == "tools/list"
        assert req["id"] == 1

        req2 = client._build_jsonrpc("tools/call", {})
        assert req2["id"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# MCPServerRegistry tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMCPServerRegistry:
    @pytest.mark.asyncio
    async def test_register_and_list(self) -> None:
        registry = MCPServerRegistry(health_check_interval=0)
        config = MCPServerConfig(name="test", url="http://localhost:3000")

        with patch.object(MCPClient, "connect", new_callable=AsyncMock):
            await registry.register_server(config)

        assert "test" in registry
        assert len(registry) == 1

        servers = registry.list_servers()
        assert len(servers) == 1
        assert servers[0].name == "test"

    @pytest.mark.asyncio
    async def test_unregister(self) -> None:
        registry = MCPServerRegistry(health_check_interval=0)
        config = MCPServerConfig(name="test", url="http://localhost:3000")

        with patch.object(MCPClient, "connect", new_callable=AsyncMock):
            await registry.register_server(config)

        await registry.unregister_server("test")
        assert "test" not in registry
        assert len(registry) == 0

    @pytest.mark.asyncio
    async def test_list_tools_all_servers(self) -> None:
        registry = MCPServerRegistry(health_check_interval=0)
        config1 = MCPServerConfig(name="s1", url="http://s1:3000")
        config2 = MCPServerConfig(name="s2", url="http://s2:3000")

        tool1 = MCPTool(name="tool_a", description="A", server_name="s1")
        tool2 = MCPTool(name="tool_b", description="B", server_name="s2")

        with patch.object(MCPClient, "connect", new_callable=AsyncMock):
            await registry.register_server(config1)
            await registry.register_server(config2)

        # Manually set tools on clients
        registry._clients["s1"]._tools = [tool1]
        registry._clients["s1"]._initialized = True
        registry._clients["s2"]._tools = [tool2]
        registry._clients["s2"]._initialized = True

        tools = await registry.list_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"tool_a", "tool_b"}

    @pytest.mark.asyncio
    async def test_list_tools_filtered_by_server(self) -> None:
        registry = MCPServerRegistry(health_check_interval=0)
        config1 = MCPServerConfig(name="s1", url="http://s1:3000")
        config2 = MCPServerConfig(name="s2", url="http://s2:3000")

        with patch.object(MCPClient, "connect", new_callable=AsyncMock):
            await registry.register_server(config1)
            await registry.register_server(config2)

        registry._clients["s1"]._tools = [MCPTool(name="a", server_name="s1")]
        registry._clients["s1"]._initialized = True
        registry._clients["s2"]._tools = [MCPTool(name="b", server_name="s2")]
        registry._clients["s2"]._initialized = True

        tools = await registry.list_tools(server_name="s1")
        assert len(tools) == 1
        assert tools[0].name == "a"

    @pytest.mark.asyncio
    async def test_list_tools_team_access(self) -> None:
        registry = MCPServerRegistry(health_check_interval=0)
        public = MCPServerConfig(name="pub", url="http://pub:3000", visibility="public")
        private = MCPServerConfig(
            name="priv",
            url="http://priv:3000",
            visibility="private",
            allowed_teams=["data-team"],
        )

        with patch.object(MCPClient, "connect", new_callable=AsyncMock):
            await registry.register_server(public)
            await registry.register_server(private)

        registry._clients["pub"]._tools = [MCPTool(name="pub_tool", server_name="pub")]
        registry._clients["pub"]._initialized = True
        registry._clients["priv"]._tools = [MCPTool(name="priv_tool", server_name="priv")]
        registry._clients["priv"]._initialized = True

        # data-team can see both
        tools_data = await registry.list_tools(team="data-team")
        assert len(tools_data) == 2

        # other-team can only see public
        tools_other = await registry.list_tools(team="other-team")
        assert len(tools_other) == 1
        assert tools_other[0].name == "pub_tool"

    @pytest.mark.asyncio
    async def test_call_tool(self) -> None:
        registry = MCPServerRegistry(health_check_interval=0)
        config = MCPServerConfig(name="test", url="http://localhost:3000")

        with patch.object(MCPClient, "connect", new_callable=AsyncMock):
            await registry.register_server(config)

        expected_result = MCPToolResult(
            server_name="test",
            tool_name="greet",
            content=[{"type": "text", "text": "Hello!"}],
        )

        with patch.object(MCPClient, "call_tool", new_callable=AsyncMock, return_value=expected_result):
            result = await registry.call_tool(
                MCPToolCall(server_name="test", tool_name="greet", arguments={"name": "Alice"})
            )

        assert not result.is_error
        assert result.content[0]["text"] == "Hello!"

    @pytest.mark.asyncio
    async def test_call_tool_unknown_server(self) -> None:
        registry = MCPServerRegistry(health_check_interval=0)
        result = await registry.call_tool(MCPToolCall(server_name="unknown", tool_name="x"))
        assert result.is_error
        assert "not found" in result.content[0]["text"]

    def test_resolve_tool_call(self) -> None:
        registry = MCPServerRegistry(health_check_interval=0)
        registry._clients["github"] = MagicMock()

        result = registry.resolve_tool_call("github__get_file")
        assert result == ("github", "get_file")

        result = registry.resolve_tool_call("unknown__get_file")
        assert result is None

        result = registry.resolve_tool_call("plain_name")
        assert result is None

    @pytest.mark.asyncio
    async def test_check_health(self) -> None:
        registry = MCPServerRegistry(health_check_interval=0)
        config = MCPServerConfig(name="test", url="http://localhost:3000")

        with patch.object(MCPClient, "connect", new_callable=AsyncMock):
            await registry.register_server(config)

        with patch.object(MCPClient, "check_health", new_callable=AsyncMock, return_value=MCPServerHealth.HEALTHY):
            results = await registry.check_health()

        assert results["test"] == MCPServerHealth.HEALTHY

    @pytest.mark.asyncio
    async def test_shutdown(self) -> None:
        registry = MCPServerRegistry(health_check_interval=0)
        config = MCPServerConfig(name="test", url="http://localhost:3000")

        with patch.object(MCPClient, "connect", new_callable=AsyncMock):
            await registry.register_server(config)

        await registry.shutdown()
        assert len(registry) == 0


# ═══════════════════════════════════════════════════════════════════════════
# MCP Route tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMCPRoutes:
    """Test MCP gateway HTTP routes via TestClient."""

    def _create_app_with_registry(self, registry: MCPServerRegistry | None = None) -> Any:
        """Create a minimal FastAPI app with MCP routes."""
        from fastapi import FastAPI

        from routerbot.proxy.routes.mcp import router

        app = FastAPI()
        app.include_router(router, prefix="/v1")

        # Set up state
        state = MagicMock()
        state.mcp_registry = registry
        app.state.routerbot = state

        return app

    def test_list_tools_no_registry(self) -> None:
        app = self._create_app_with_registry(None)
        # When registry is None, the route should check mcp_registry attr
        state = MagicMock(spec=[])  # No attributes
        app.state.routerbot = state

        client = TestClient(app)
        resp = client.post("/v1/mcp/tools")
        assert resp.status_code == 503

    def test_list_servers_no_registry(self) -> None:
        app = self._create_app_with_registry(None)
        state = MagicMock(spec=[])
        app.state.routerbot = state

        client = TestClient(app)
        resp = client.get("/v1/mcp/servers")
        assert resp.status_code == 503

    def test_list_tools_success(self) -> None:
        registry = MagicMock()
        tool = MCPTool(name="search", description="Search", server_name="github")
        registry.list_tools = AsyncMock(return_value=[tool])

        app = self._create_app_with_registry(registry)
        client = TestClient(app)
        resp = client.post("/v1/mcp/tools", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["tools"][0]["name"] == "search"
        assert data["tools"][0]["server_name"] == "github"
        assert "openai_function" in data["tools"][0]

    def test_call_tool_success(self) -> None:
        registry = MagicMock()
        registry.call_tool = AsyncMock(
            return_value=MCPToolResult(
                server_name="github",
                tool_name="search",
                content=[{"type": "text", "text": "Found 3 results"}],
            )
        )

        app = self._create_app_with_registry(registry)
        client = TestClient(app)
        resp = client.post(
            "/v1/mcp/call",
            json={
                "server_name": "github",
                "tool_name": "search",
                "arguments": {"query": "test"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool_name"] == "search"
        assert not data["is_error"]

    def test_call_tool_error_result(self) -> None:
        registry = MagicMock()
        registry.call_tool = AsyncMock(
            return_value=MCPToolResult(
                server_name="github",
                tool_name="broken",
                content=[{"type": "text", "text": "Error: timeout"}],
                is_error=True,
            )
        )

        app = self._create_app_with_registry(registry)
        client = TestClient(app)
        resp = client.post(
            "/v1/mcp/call",
            json={
                "server_name": "github",
                "tool_name": "broken",
                "arguments": {},
            },
        )
        assert resp.status_code == 422
        assert resp.json()["is_error"] is True

    def test_list_servers(self) -> None:
        registry = MagicMock()
        registry.list_servers.return_value = [
            MCPServerStatus(
                name="github",
                transport=MCPTransport.SSE,
                health=MCPServerHealth.HEALTHY,
                tools_count=5,
                enabled=True,
            ),
        ]

        app = self._create_app_with_registry(registry)
        client = TestClient(app)
        resp = client.get("/v1/mcp/servers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["servers"][0]["name"] == "github"
        assert data["servers"][0]["health"] == "healthy"

    def test_health_check(self) -> None:
        registry = MagicMock()
        registry.check_health = AsyncMock(return_value={"github": MCPServerHealth.HEALTHY})

        app = self._create_app_with_registry(registry)
        client = TestClient(app)
        resp = client.post("/v1/mcp/health", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"]["github"] == "healthy"
