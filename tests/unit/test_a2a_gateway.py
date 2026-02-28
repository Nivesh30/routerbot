"""Tests for A2A (Agent-to-Agent) Gateway integration (Task 8B).

Covers:
- A2AAgentConfig / A2AAgentCard model validation
- A2AClient: connect, disconnect, invoke, health check, agent card fetch
- A2AAgentRegistry: registration, discovery, invocation, team access, health
- A2A gateway routes: /v1/a2a/agents, /v1/a2a/invoke, /v1/a2a/status, /v1/a2a/health
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from routerbot.core.a2a.client import A2AClient, A2AClientError
from routerbot.core.a2a.models import (
    A2AAgentCard,
    A2AAgentConfig,
    A2AAgentFramework,
    A2AAgentHealth,
    A2AAgentSkill,
    A2AAgentStatus,
    A2AInvocationRequest,
    A2AInvocationResult,
    A2AMessage,
    A2AVisibility,
)
from routerbot.core.a2a.registry import A2AAgentRegistry

# ═══════════════════════════════════════════════════════════════════════════
# Model tests
# ═══════════════════════════════════════════════════════════════════════════


class TestA2AAgentConfig:
    def test_minimal_config(self) -> None:
        config = A2AAgentConfig(name="test-agent", url="http://localhost:8080")
        assert config.name == "test-agent"
        assert config.framework == A2AAgentFramework.GENERIC
        assert config.visibility == A2AVisibility.PUBLIC
        assert config.enabled is True
        assert config.timeout == 60.0

    def test_full_config(self) -> None:
        config = A2AAgentConfig(
            name="data-agent",
            url="http://data-agent:9000",
            description="Processes data queries",
            version="2.0.0",
            framework="langgraph",
            visibility="private",
            allowed_teams=["data-team", "ml-team"],
            headers={"Authorization": "Bearer xxx"},
            timeout=120.0,
            skills=[{"id": "query", "name": "SQL Query", "tags": ["sql"]}],
        )
        assert config.framework == A2AAgentFramework.LANGGRAPH
        assert config.visibility == A2AVisibility.PRIVATE
        assert len(config.skills) == 1
        assert config.allowed_teams == ["data-team", "ml-team"]


class TestA2AAgentCard:
    def test_agent_card(self) -> None:
        card = A2AAgentCard(
            name="test",
            url="http://localhost:8080",
            skills=[
                A2AAgentSkill(id="search", name="Search", tags=["search", "web"]),
            ],
        )
        assert card.name == "test"
        assert len(card.skills) == 1
        assert "search" in card.skills[0].tags


class TestA2AInvocationResult:
    def test_success(self) -> None:
        result = A2AInvocationResult(
            agent_name="test",
            status="completed",
            messages=[A2AMessage(role="agent", content="Done!")],
        )
        assert not result.is_error
        assert result.messages[0].content == "Done!"

    def test_error(self) -> None:
        result = A2AInvocationResult(
            agent_name="test",
            status="error",
            is_error=True,
            error_message="Timeout",
        )
        assert result.is_error
        assert result.error_message == "Timeout"


# ═══════════════════════════════════════════════════════════════════════════
# A2AClient tests
# ═══════════════════════════════════════════════════════════════════════════


class TestA2AClient:
    def test_init(self) -> None:
        config = A2AAgentConfig(name="test", url="http://localhost:8080")
        client = A2AClient(config)
        assert client.agent_name == "test"
        assert client.health == A2AAgentHealth.UNKNOWN
        assert not client.is_initialized

    @pytest.mark.asyncio
    async def test_connect_with_agent_card(self) -> None:
        config = A2AAgentConfig(name="test", url="http://localhost:8080")
        client = A2AClient(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "name": "TestAgent",
            "description": "A test agent",
            "skills": [{"id": "greet", "name": "Greet", "description": "Say hello", "tags": ["greet"]}],
        }

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_http):
            await client.connect()

        assert client.is_initialized
        assert client.health == A2AAgentHealth.HEALTHY
        assert client.agent_card is not None
        assert client.agent_card.name == "TestAgent"
        assert len(client.agent_card.skills) == 1

    @pytest.mark.asyncio
    async def test_connect_fallback_to_config(self) -> None:
        config = A2AAgentConfig(
            name="test",
            url="http://localhost:8080",
            description="From config",
            skills=[{"id": "skill1", "name": "Skill 1"}],
        )
        client = A2AClient(config)

        import httpx

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=httpx.HTTPError("Not found"))

        with patch("httpx.AsyncClient", return_value=mock_http):
            await client.connect()

        assert client.is_initialized
        assert client.agent_card is not None
        assert client.agent_card.description == "From config"

    @pytest.mark.asyncio
    async def test_connect_failure(self) -> None:
        config = A2AAgentConfig(name="test", url="http://localhost:8080")
        client = A2AClient(config)

        with (
            patch("httpx.AsyncClient", side_effect=Exception("Connection refused")),
            pytest.raises(A2AClientError, match="Failed to connect"),
        ):
            await client.connect()

        assert client.health == A2AAgentHealth.UNHEALTHY

    @pytest.mark.asyncio
    async def test_invoke_success(self) -> None:
        config = A2AAgentConfig(name="test", url="http://localhost:8080")
        client = A2AClient(config)
        client._initialized = True

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "completed",
            "messages": [{"role": "agent", "content": "Hello!"}],
            "output": {"result": 42},
        }

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        result = await client.invoke(messages=[{"role": "user", "content": "Hi"}])
        assert not result.is_error
        assert result.status == "completed"
        assert result.messages[0].content == "Hello!"

    @pytest.mark.asyncio
    async def test_invoke_not_connected(self) -> None:
        config = A2AAgentConfig(name="test", url="http://localhost:8080")
        client = A2AClient(config)

        result = await client.invoke(messages=[{"role": "user", "content": "Hi"}])
        assert result.is_error
        assert "not connected" in result.error_message

    @pytest.mark.asyncio
    async def test_invoke_tries_multiple_endpoints(self) -> None:
        config = A2AAgentConfig(name="test", url="http://localhost:8080")
        client = A2AClient(config)
        client._initialized = True

        # First endpoint returns 404, second succeeds
        resp_404 = MagicMock()
        resp_404.status_code = 404

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.raise_for_status = MagicMock()
        resp_ok.json.return_value = {"status": "completed", "messages": []}

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=[resp_404, resp_ok])
        client._http_client = mock_http

        result = await client.invoke()
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_check_health_healthy(self) -> None:
        config = A2AAgentConfig(name="test", url="http://localhost:8080")
        client = A2AClient(config)

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        client._http_client = mock_http

        health = await client.check_health()
        assert health == A2AAgentHealth.HEALTHY

    @pytest.mark.asyncio
    async def test_check_health_unhealthy(self) -> None:
        config = A2AAgentConfig(name="test", url="http://localhost:8080")
        client = A2AClient(config)

        import httpx

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=httpx.HTTPError("down"))
        mock_http.head = AsyncMock(side_effect=httpx.HTTPError("down"))
        client._http_client = mock_http

        health = await client.check_health()
        assert health == A2AAgentHealth.UNHEALTHY

    @pytest.mark.asyncio
    async def test_disconnect(self) -> None:
        config = A2AAgentConfig(name="test", url="http://localhost:8080")
        client = A2AClient(config)
        client._initialized = True
        mock_http = AsyncMock()
        client._http_client = mock_http

        await client.disconnect()
        assert not client.is_initialized
        mock_http.aclose.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# A2AAgentRegistry tests
# ═══════════════════════════════════════════════════════════════════════════


class TestA2AAgentRegistry:
    @pytest.mark.asyncio
    async def test_register_and_list(self) -> None:
        registry = A2AAgentRegistry(health_check_interval=0)
        config = A2AAgentConfig(name="test", url="http://localhost:8080")

        with patch.object(A2AClient, "connect", new_callable=AsyncMock):
            await registry.register_agent(config)

        assert "test" in registry
        assert len(registry) == 1
        agents = registry.list_agents()
        assert len(agents) == 1

    @pytest.mark.asyncio
    async def test_unregister(self) -> None:
        registry = A2AAgentRegistry(health_check_interval=0)
        config = A2AAgentConfig(name="test", url="http://localhost:8080")

        with patch.object(A2AClient, "connect", new_callable=AsyncMock):
            await registry.register_agent(config)

        await registry.unregister_agent("test")
        assert "test" not in registry

    @pytest.mark.asyncio
    async def test_discover_agents_public(self) -> None:
        registry = A2AAgentRegistry(health_check_interval=0)
        config = A2AAgentConfig(name="pub", url="http://pub:8080")

        with patch.object(A2AClient, "connect", new_callable=AsyncMock):
            await registry.register_agent(config)

        # Set agent card
        registry._clients["pub"]._agent_card = A2AAgentCard(
            name="pub",
            url="http://pub:8080",
            skills=[A2AAgentSkill(id="s1", name="S1", tags=["search"])],
        )

        cards = registry.discover_agents()
        assert len(cards) == 1
        assert cards[0].name == "pub"

    @pytest.mark.asyncio
    async def test_discover_agents_team_filter(self) -> None:
        registry = A2AAgentRegistry(health_check_interval=0)
        pub = A2AAgentConfig(name="pub", url="http://pub:8080")
        priv = A2AAgentConfig(
            name="priv",
            url="http://priv:8080",
            visibility="private",
            allowed_teams=["data-team"],
        )

        with patch.object(A2AClient, "connect", new_callable=AsyncMock):
            await registry.register_agent(pub)
            await registry.register_agent(priv)

        registry._clients["pub"]._agent_card = A2AAgentCard(name="pub", url="http://pub:8080")
        registry._clients["priv"]._agent_card = A2AAgentCard(name="priv", url="http://priv:8080")

        # data-team sees both
        assert len(registry.discover_agents(team="data-team")) == 2
        # other-team sees only public
        assert len(registry.discover_agents(team="other-team")) == 1

    @pytest.mark.asyncio
    async def test_discover_agents_skill_filter(self) -> None:
        registry = A2AAgentRegistry(health_check_interval=0)
        config = A2AAgentConfig(name="test", url="http://test:8080")

        with patch.object(A2AClient, "connect", new_callable=AsyncMock):
            await registry.register_agent(config)

        registry._clients["test"]._agent_card = A2AAgentCard(
            name="test",
            url="http://test:8080",
            skills=[A2AAgentSkill(id="s1", name="S1", tags=["sql", "data"])],
        )

        assert len(registry.discover_agents(skill_tag="sql")) == 1
        assert len(registry.discover_agents(skill_tag="vision")) == 0

    @pytest.mark.asyncio
    async def test_invoke_agent(self) -> None:
        registry = A2AAgentRegistry(health_check_interval=0)
        config = A2AAgentConfig(name="test", url="http://localhost:8080")

        with patch.object(A2AClient, "connect", new_callable=AsyncMock):
            await registry.register_agent(config)

        expected = A2AInvocationResult(
            agent_name="test",
            status="completed",
            messages=[A2AMessage(role="agent", content="Done!")],
        )

        with patch.object(A2AClient, "invoke", new_callable=AsyncMock, return_value=expected):
            result = await registry.invoke_agent(
                A2AInvocationRequest(
                    agent_name="test",
                    messages=[A2AMessage(role="user", content="Do it")],
                )
            )

        assert not result.is_error
        assert result.messages[0].content == "Done!"

    @pytest.mark.asyncio
    async def test_invoke_unknown_agent(self) -> None:
        registry = A2AAgentRegistry(health_check_interval=0)
        result = await registry.invoke_agent(A2AInvocationRequest(agent_name="unknown"))
        assert result.is_error
        assert "not found" in result.error_message

    @pytest.mark.asyncio
    async def test_check_health(self) -> None:
        registry = A2AAgentRegistry(health_check_interval=0)
        config = A2AAgentConfig(name="test", url="http://localhost:8080")

        with patch.object(A2AClient, "connect", new_callable=AsyncMock):
            await registry.register_agent(config)

        with patch.object(A2AClient, "check_health", new_callable=AsyncMock, return_value=A2AAgentHealth.HEALTHY):
            results = await registry.check_health()

        assert results["test"] == A2AAgentHealth.HEALTHY

    @pytest.mark.asyncio
    async def test_shutdown(self) -> None:
        registry = A2AAgentRegistry(health_check_interval=0)
        config = A2AAgentConfig(name="test", url="http://localhost:8080")

        with patch.object(A2AClient, "connect", new_callable=AsyncMock):
            await registry.register_agent(config)

        await registry.shutdown()
        assert len(registry) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Route tests
# ═══════════════════════════════════════════════════════════════════════════


class TestA2ARoutes:
    def _create_app(self, registry: A2AAgentRegistry | None = None) -> Any:
        from fastapi import FastAPI

        from routerbot.proxy.routes.a2a import router

        app = FastAPI()
        app.include_router(router, prefix="/v1")

        state = MagicMock()
        state.a2a_registry = registry
        app.state.routerbot = state
        return app

    def test_discover_no_registry(self) -> None:
        app = self._create_app(None)
        state = MagicMock(spec=[])
        app.state.routerbot = state

        client = TestClient(app)
        resp = client.get("/v1/a2a/agents")
        assert resp.status_code == 503

    def test_discover_agents(self) -> None:
        registry = MagicMock()
        card = A2AAgentCard(name="test", url="http://test:8080", description="Test agent")
        registry.discover_agents.return_value = [card]

        app = self._create_app(registry)
        client = TestClient(app)
        resp = client.get("/v1/a2a/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["agents"][0]["name"] == "test"

    def test_get_agent_card(self) -> None:
        registry = MagicMock()
        card = A2AAgentCard(name="test", url="http://test:8080")
        registry.get_agent_card.return_value = card

        app = self._create_app(registry)
        client = TestClient(app)
        resp = client.get("/v1/a2a/agents/test")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test"

    def test_get_agent_card_not_found(self) -> None:
        registry = MagicMock()
        registry.get_agent_card.return_value = None

        app = self._create_app(registry)
        client = TestClient(app)
        resp = client.get("/v1/a2a/agents/unknown")
        assert resp.status_code == 404

    def test_invoke_agent(self) -> None:
        registry = MagicMock()
        registry.invoke_agent = AsyncMock(
            return_value=A2AInvocationResult(
                agent_name="test",
                status="completed",
                messages=[A2AMessage(role="agent", content="Done!")],
            )
        )

        app = self._create_app(registry)
        client = TestClient(app)
        resp = client.post(
            "/v1/a2a/invoke",
            json={
                "agent_name": "test",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "test"
        assert not data["is_error"]

    def test_invoke_agent_error(self) -> None:
        registry = MagicMock()
        registry.invoke_agent = AsyncMock(
            return_value=A2AInvocationResult(
                agent_name="test",
                status="error",
                is_error=True,
                error_message="Agent crashed",
            )
        )

        app = self._create_app(registry)
        client = TestClient(app)
        resp = client.post(
            "/v1/a2a/invoke",
            json={
                "agent_name": "test",
            },
        )
        assert resp.status_code == 422
        assert resp.json()["is_error"] is True

    def test_list_status(self) -> None:
        registry = MagicMock()
        registry.list_agents.return_value = [
            A2AAgentStatus(
                name="test",
                url="http://test:8080",
                framework=A2AAgentFramework.GENERIC,
                health=A2AAgentHealth.HEALTHY,
                skills_count=3,
                enabled=True,
            ),
        ]

        app = self._create_app(registry)
        client = TestClient(app)
        resp = client.get("/v1/a2a/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["agents"][0]["health"] == "healthy"

    def test_health_check(self) -> None:
        registry = MagicMock()
        registry.check_health = AsyncMock(return_value={"test": A2AAgentHealth.HEALTHY})

        app = self._create_app(registry)
        client = TestClient(app)
        resp = client.post("/v1/a2a/health", json={})
        assert resp.status_code == 200
        assert resp.json()["results"]["test"] == "healthy"
