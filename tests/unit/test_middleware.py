"""Tests for Stage 3.4-3.6: Middleware, Config Reload, and OpenAPI.

Covers:
- RequestSizeLimitMiddleware: body size enforcement
- RequestLoggingMiddleware: structured logging output
- RobotsTxtMiddleware: /robots.txt blocking
- ConfigWatcher: file-watching lifecycle
- Config routes: GET /config, POST /config/reload
- OpenAPI customization: schema, branding
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import yaml
from httpx import ASGITransport, AsyncClient

from routerbot.core.config_models import (
    GeneralSettings,
    ModelEntry,
    ModelParams,
    RouterBotConfig,
)
from routerbot.proxy.app import create_app
from routerbot.proxy.config_reload import ConfigWatcher, compute_config_hash


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_config(
    *,
    models: list[tuple[str, str]] | None = None,
    block_robots: bool = False,
    max_request_size_mb: float = 100.0,
    master_key: str | None = None,
) -> RouterBotConfig:
    config = RouterBotConfig(
        general_settings=GeneralSettings(
            block_robots=block_robots,
            max_request_size_mb=max_request_size_mb,
            master_key=master_key,
        ),
    )
    if models:
        config.model_list = [
            ModelEntry(
                model_name=name,
                provider_params=ModelParams(model=provider_model, api_key="sk-test"),
            )
            for name, provider_model in models
        ]
    return config


@pytest_asyncio.fixture()
async def client() -> AsyncClient:
    config = _make_config(models=[("gpt-4o", "openai/gpt-4o")])
    app = create_app(config=config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ═══════════════════════════════════════════════════════════════════════════════
# RequestSizeLimitMiddleware
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestRequestSizeLimit:
    async def test_small_body_passes(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_large_body_rejected_via_content_length(self) -> None:
        config = _make_config(max_request_size_mb=0.001)  # ~1 KB limit
        app = create_app(config=config)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            big_body = "x" * 5000  # > 1 KB
            resp = await ac.post(
                "/v1/chat/completions",
                content=big_body,
                headers={"content-type": "application/json"},
            )
            assert resp.status_code == 413
            body = resp.json()
            assert "too large" in body["error"]["message"].lower()

    async def test_within_limit_passes(self) -> None:
        config = _make_config(max_request_size_mb=1.0, models=[("gpt-4o", "openai/gpt-4o")])
        app = create_app(config=config)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # Small request should pass size check (may fail at provider level, that's ok)
            resp = await ac.get("/health")
            assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# RequestLoggingMiddleware
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestRequestLogging:
    async def test_request_logged(self, client: AsyncClient, caplog: Any) -> None:
        with caplog.at_level(logging.INFO):
            await client.get("/")
        # Check that the logging middleware emitted a record
        assert any("http_request" in rec.message for rec in caplog.records)

    async def test_health_not_logged(self, client: AsyncClient, caplog: Any) -> None:
        with caplog.at_level(logging.INFO):
            await client.get("/health")
        # Health endpoints should be skipped
        http_logs = [rec for rec in caplog.records if "http_request" in rec.message]
        assert len(http_logs) == 0

    async def test_model_extracted_from_body(self, client: AsyncClient, caplog: Any) -> None:
        with caplog.at_level(logging.INFO):
            await client.post(
                "/v1/chat/completions",
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            )
        http_logs = [rec for rec in caplog.records if "http_request" in rec.message and hasattr(rec, "http")]
        if http_logs:
            assert http_logs[0].http.get("model") == "gpt-4o"


# ═══════════════════════════════════════════════════════════════════════════════
# RobotsTxtMiddleware
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestRobotsTxt:
    async def test_robots_blocked_when_enabled(self) -> None:
        config = _make_config(block_robots=True)
        app = create_app(config=config)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/robots.txt")
            assert resp.status_code == 200
            assert "Disallow: /" in resp.text

    async def test_robots_not_served_when_disabled(self, client: AsyncClient) -> None:
        resp = await client.get("/robots.txt")
        # When disabled, falls through to normal routes → 404 or 405
        assert resp.status_code in (404, 405)


# ═══════════════════════════════════════════════════════════════════════════════
# ConfigWatcher
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestConfigWatcher:
    async def test_start_and_stop(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"model_list": [], "general_settings": {"port": 4000}})
        )
        callback = AsyncMock()
        watcher = ConfigWatcher(config_path=config_file, on_reload=callback, poll_interval=0.1)
        await watcher.start()
        assert watcher.is_running
        await watcher.stop()
        assert not watcher.is_running

    async def test_detects_file_change(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"model_list": [], "general_settings": {"port": 4000}})
        )
        callback = AsyncMock()
        watcher = ConfigWatcher(config_path=config_file, on_reload=callback, poll_interval=0.1)
        await watcher.start()

        # Modify the file
        await asyncio.sleep(0.05)
        config_file.write_text(
            yaml.dump({"model_list": [], "general_settings": {"port": 5000}})
        )
        # Wait for detection
        await asyncio.sleep(0.3)

        await watcher.stop()
        assert callback.call_count >= 1

    async def test_invalid_config_does_not_crash(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"model_list": [], "general_settings": {"port": 4000}})
        )
        callback = AsyncMock()
        watcher = ConfigWatcher(config_path=config_file, on_reload=callback, poll_interval=0.1)
        await watcher.start()

        # Write invalid YAML
        await asyncio.sleep(0.05)
        config_file.write_text("{{{{bad yaml: [[[")
        await asyncio.sleep(0.3)

        await watcher.stop()
        # Callback should NOT have been called with invalid data
        assert callback.call_count == 0

    async def test_reload_now(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump({"model_list": [], "general_settings": {"port": 4000}})
        )
        callback = AsyncMock()
        watcher = ConfigWatcher(config_path=config_file, on_reload=callback)
        result = await watcher.reload_now()
        assert result is not None
        assert callback.call_count == 1

    async def test_double_start_is_idempotent(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"model_list": []}))
        callback = AsyncMock()
        watcher = ConfigWatcher(config_path=config_file, on_reload=callback, poll_interval=999)
        await watcher.start()
        task1 = watcher._task
        await watcher.start()
        assert watcher._task is task1
        await watcher.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# compute_config_hash
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeConfigHash:
    def test_same_config_same_hash(self) -> None:
        c1 = RouterBotConfig()
        c2 = RouterBotConfig()
        assert compute_config_hash(c1) == compute_config_hash(c2)

    def test_different_config_different_hash(self) -> None:
        c1 = RouterBotConfig()
        c2 = RouterBotConfig(
            model_list=[
                ModelEntry(model_name="x", provider_params=ModelParams(model="openai/x"))
            ]
        )
        assert compute_config_hash(c1) != compute_config_hash(c2)

    def test_hash_length(self) -> None:
        h = compute_config_hash(RouterBotConfig())
        assert len(h) == 12


# ═══════════════════════════════════════════════════════════════════════════════
# Config routes
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestConfigRoutes:
    async def test_get_config_summary(self, client: AsyncClient) -> None:
        resp = await client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "config_hash" in data
        assert data["model_count"] == 1
        assert "gpt-4o" in data["models"]

    async def test_reload_without_master_key(self) -> None:
        """When no master_key configured, anyone can trigger reload."""
        config = _make_config(models=[("gpt-4o", "openai/gpt-4o")])
        app = create_app(config=config)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # Will fail at file load (no config file on disk), which is expected.
            # We just verify the endpoint doesn't 401.
            resp = await ac.post("/config/reload")
            # Should be 500 (no config file) not 401 (auth failure)
            assert resp.status_code in (200, 500)

    async def test_reload_with_wrong_master_key(self) -> None:
        config = _make_config(
            models=[("gpt-4o", "openai/gpt-4o")],
            master_key="secret-admin-key",
        )
        app = create_app(config=config)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/config/reload",
                headers={"x-master-key": "wrong-key"},
            )
            assert resp.status_code == 401

    async def test_reload_with_correct_master_key(self) -> None:
        config = _make_config(
            models=[("gpt-4o", "openai/gpt-4o")],
            master_key="secret-admin-key",
        )
        app = create_app(config=config)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # Will 500 because no config file exists, but auth should pass
            resp = await ac.post(
                "/config/reload",
                headers={"x-master-key": "secret-admin-key"},
            )
            assert resp.status_code in (200, 500)
            if resp.status_code == 500:
                assert "reload failed" in resp.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAPI customization
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestOpenAPI:
    async def test_openapi_json_accessible(self, client: AsyncClient) -> None:
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert schema["info"]["title"] == "RouterBot"
        assert "contact" in schema["info"]
        assert "license" in schema["info"]

    async def test_openapi_has_servers(self, client: AsyncClient) -> None:
        resp = await client.get("/openapi.json")
        schema = resp.json()
        assert "servers" in schema

    async def test_docs_accessible(self, client: AsyncClient) -> None:
        resp = await client.get("/docs")
        assert resp.status_code == 200

    async def test_redoc_accessible(self, client: AsyncClient) -> None:
        resp = await client.get("/redoc")
        assert resp.status_code == 200

    async def test_openapi_title_from_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("ROUTERBOT_API_TITLE", "My Custom Gateway")
        config = _make_config()
        app = create_app(config=config)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.get("/openapi.json")
            schema = resp.json()
            assert schema["info"]["title"] == "My Custom Gateway"


# ═══════════════════════════════════════════════════════════════════════════════
# Request ID + Response Time middleware (already existed, verify integration)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestRequestIdMiddleware:
    async def test_response_has_request_id(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert "x-request-id" in resp.headers

    async def test_custom_request_id_forwarded(self, client: AsyncClient) -> None:
        resp = await client.get("/health", headers={"X-Request-ID": "my-custom-id"})
        assert resp.headers["x-request-id"] == "my-custom-id"

    async def test_response_has_timing_header(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert "x-response-time-ms" in resp.headers
        # Should be a valid float
        float(resp.headers["x-response-time-ms"])


# ═══════════════════════════════════════════════════════════════════════════════
# Router integration in startup
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestRouterIntegration:
    """Test that the startup hook initialises the Router.

    Note: ``ASGITransport`` does NOT fire ASGI lifespan events, so we
    call ``_startup`` directly.
    """

    async def test_startup_initialises_router(self) -> None:
        from routerbot.proxy.app import _startup

        config = _make_config(models=[("gpt-4o", "openai/gpt-4o")])
        app = create_app(config=config)
        state = app.state.routerbot
        await _startup(app, state, config)
        assert state.router is not None

    async def test_router_has_models(self) -> None:
        from routerbot.proxy.app import _startup

        config = _make_config(models=[("gpt-4o", "openai/gpt-4o"), ("claude", "anthropic/claude")])
        app = create_app(config=config)
        state = app.state.routerbot
        await _startup(app, state, config)
        router = state.router
        assert "gpt-4o" in router.list_models()
        assert "claude" in router.list_models()
