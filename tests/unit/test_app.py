"""Unit tests for the FastAPI app factory, middleware, health routes, and model routes.

Tests cover:
- create_app() returns a configured FastAPI instance
- Middleware: request-ID header injection, response-time header
- Health endpoints: /health, /health/liveness, /health/readiness
- Model endpoints: GET /v1/models, GET /v1/models/{id}
- Exception handlers: 401, 429, 400, 404, 500
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from routerbot.core.config_models import ModelEntry, ModelParams, RouterBotConfig
from routerbot.core.exceptions import (
    AuthenticationError,
    BadRequestError,
    ProviderError,
    RateLimitError,
    ServiceUnavailableError,
)
from routerbot.proxy.app import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(models: list[tuple[str, str]] | None = None) -> RouterBotConfig:
    """Build a minimal RouterBotConfig with optional model entries."""
    config = RouterBotConfig()
    if models:
        config.model_list = [
            ModelEntry(
                model_name=name,
                provider_params=ModelParams(model=provider_model),
            )
            for name, provider_model in models
        ]
    return config


@pytest_asyncio.fixture()
async def client() -> AsyncClient:
    """Async test client with a pre-configured (ready) app."""
    config = _make_config([("gpt-4o", "openai/gpt-4o"), ("claude-3", "anthropic/claude-3-opus-20240229")])
    test_app = create_app(config=config)
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def unready_client() -> AsyncClient:
    """Async test client with an app that has no config (not ready)."""
    test_app = create_app(config=None)
    # Override the startup so it does NOT load from disk
    test_app.state.routerbot.config = None  # type: ignore[attr-defined]
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_create_app_returns_fastapi_instance() -> None:
    """create_app() should return a FastAPI app without errors."""
    from fastapi import FastAPI

    config = _make_config()
    app = create_app(config=config)
    assert isinstance(app, FastAPI)


def test_create_app_title() -> None:
    """The app title should be RouterBot."""
    app = create_app(config=_make_config())
    assert app.title == "RouterBot"


def test_create_app_version() -> None:
    """The app version should be 0.1.0."""
    app = create_app(config=_make_config())
    assert app.version == "0.1.0"


def test_default_app_has_routes() -> None:
    """The default app should have routes registered."""
    app = create_app(config=_make_config())
    route_paths = [getattr(r, "path", "") for r in app.routes]
    assert "/health" in route_paths
    assert "/health/liveness" in route_paths
    assert "/health/readiness" in route_paths
    assert "/v1/models" in route_paths


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient) -> None:
    """GET / should return 200 with RouterBot metadata."""
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "RouterBot"
    assert data["status"] == "running"


# ---------------------------------------------------------------------------
# Request-ID middleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_id_header_generated(client: AsyncClient) -> None:
    """The response should include an X-Request-ID header."""
    resp = await client.get("/health")
    assert "x-request-id" in resp.headers
    req_id = resp.headers["x-request-id"]
    assert req_id.startswith("req-") or len(req_id) > 0


@pytest.mark.asyncio
async def test_request_id_header_propagated(client: AsyncClient) -> None:
    """If X-Request-ID is sent, it should be echoed back."""
    custom_id = "custom-test-id-12345"
    resp = await client.get("/health", headers={"X-Request-ID": custom_id})
    assert resp.headers["x-request-id"] == custom_id


@pytest.mark.asyncio
async def test_response_time_header_present(client: AsyncClient) -> None:
    """The response should include an X-Response-Time-Ms header."""
    resp = await client.get("/health")
    assert "x-response-time-ms" in resp.headers
    elapsed = float(resp.headers["x-response-time-ms"])
    assert elapsed >= 0


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient) -> None:
    """GET /health should return 200."""
    resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_response_schema(client: AsyncClient) -> None:
    """GET /health should include status, uptime_seconds, version."""
    resp = await client.get("/health")
    data = resp.json()
    assert "status" in data
    assert "uptime_seconds" in data
    assert "version" in data
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_health_status_healthy_when_ready(client: AsyncClient) -> None:
    """/health should say 'healthy' when config is loaded."""
    resp = await client.get("/health")
    assert resp.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_status_starting_when_not_ready(unready_client: AsyncClient) -> None:
    """/health should say 'starting' when config is not yet loaded."""
    resp = await unready_client.get("/health")
    assert resp.json()["status"] == "starting"


@pytest.mark.asyncio
async def test_liveness_always_200(client: AsyncClient) -> None:
    """GET /health/liveness should always return 200."""
    resp = await client.get("/health/liveness")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_liveness_not_ready_app_still_200(unready_client: AsyncClient) -> None:
    """Liveness should be 200 even if app isn't ready yet."""
    resp = await unready_client.get("/health/liveness")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_readiness_200_when_ready(client: AsyncClient) -> None:
    """GET /health/readiness should return 200 when config is loaded."""
    resp = await client.get("/health/readiness")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_readiness_503_when_not_ready(unready_client: AsyncClient) -> None:
    """GET /health/readiness should return 503 when config not loaded."""
    resp = await unready_client.get("/health/readiness")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


# ---------------------------------------------------------------------------
# Model endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_returns_200(client: AsyncClient) -> None:
    """GET /v1/models should return 200."""
    resp = await client.get("/v1/models")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_models_response_schema(client: AsyncClient) -> None:
    """GET /v1/models should return an OpenAI-compatible list object."""
    resp = await client.get("/v1/models")
    data = resp.json()
    assert data["object"] == "list"
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_list_models_includes_configured_models(client: AsyncClient) -> None:
    """Configured models should appear in the list."""
    resp = await client.get("/v1/models")
    data = resp.json()
    model_ids = [m["id"] for m in data["data"]]
    assert "gpt-4o" in model_ids
    assert "claude-3" in model_ids


@pytest.mark.asyncio
async def test_list_models_model_object_fields(client: AsyncClient) -> None:
    """Each model object should have id, object, created, owned_by."""
    resp = await client.get("/v1/models")
    data = resp.json()
    assert len(data["data"]) > 0
    model = data["data"][0]
    assert "id" in model
    assert model["object"] == "model"
    assert "created" in model
    assert "owned_by" in model


@pytest.mark.asyncio
async def test_list_models_empty_when_no_config(unready_client: AsyncClient) -> None:
    """With no config, /v1/models should return an empty list."""
    resp = await unready_client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"] == []


@pytest.mark.asyncio
async def test_get_model_returns_200(client: AsyncClient) -> None:
    """GET /v1/models/{id} should return 200 for a known model."""
    resp = await client.get("/v1/models/gpt-4o")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "gpt-4o"
    assert data["object"] == "model"


@pytest.mark.asyncio
async def test_get_model_unknown_returns_404(client: AsyncClient) -> None:
    """GET /v1/models/{id} should return 404 for an unknown model."""
    resp = await client.get("/v1/models/nonexistent-model-xyz")
    assert resp.status_code == 404
    error = resp.json()
    assert "error" in error


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authentication_error_returns_401() -> None:
    """AuthenticationError should map to 401 with OpenAI error format."""
    from fastapi import APIRouter

    config = _make_config()
    test_app = create_app(config=config)
    test_router = APIRouter()

    @test_router.get("/test-auth-error")
    async def _raise() -> None:
        raise AuthenticationError("Invalid API key")

    test_app.include_router(test_router)

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        resp = await ac.get("/test-auth-error")

    assert resp.status_code == 401
    error = resp.json()["error"]
    assert "Invalid API key" in error["message"]


@pytest.mark.asyncio
async def test_rate_limit_error_returns_429() -> None:
    """RateLimitError should map to 429."""
    from fastapi import APIRouter

    config = _make_config()
    test_app = create_app(config=config)
    test_router = APIRouter()

    @test_router.get("/test-rate-limit")
    async def _raise() -> None:
        raise RateLimitError("Too many requests")

    test_app.include_router(test_router)

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        resp = await ac.get("/test-rate-limit")

    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_bad_request_error_returns_400() -> None:
    """BadRequestError should map to 400."""
    from fastapi import APIRouter

    config = _make_config()
    test_app = create_app(config=config)
    test_router = APIRouter()

    @test_router.get("/test-bad-request")
    async def _raise() -> None:
        raise BadRequestError("Bad params")

    test_app.include_router(test_router)

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        resp = await ac.get("/test-bad-request")

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_service_unavailable_returns_503() -> None:
    """ServiceUnavailableError should map to 503."""
    from fastapi import APIRouter

    config = _make_config()
    test_app = create_app(config=config)
    test_router = APIRouter()

    @test_router.get("/test-service-unavailable")
    async def _raise() -> None:
        raise ServiceUnavailableError("Service down")

    test_app.include_router(test_router)

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        resp = await ac.get("/test-service-unavailable")

    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_provider_error_returns_500() -> None:
    """ProviderError should map to 500."""
    from fastapi import APIRouter

    config = _make_config()
    test_app = create_app(config=config)
    test_router = APIRouter()

    @test_router.get("/test-provider-error")
    async def _raise() -> None:
        raise ProviderError("Provider blew up")

    test_app.include_router(test_router)

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        resp = await ac.get("/test-provider-error")

    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_unhandled_exception_handler_returns_500() -> None:
    """unhandled_exception_handler should return 500 with internal_error type."""
    from unittest.mock import MagicMock

    from fastapi import Request

    from routerbot.proxy.error_handlers import unhandled_exception_handler

    # Create a mock request
    mock_request = MagicMock(spec=Request)
    exc = RuntimeError("Something exploded")

    response = await unhandled_exception_handler(mock_request, exc)

    assert response.status_code == 500
    import json

    data = json.loads(response.body)
    assert data["error"]["type"] == "internal_error"
    assert data["error"]["message"] == "An internal server error occurred."


@pytest.mark.asyncio
async def test_error_response_has_openai_format() -> None:
    """All error responses should use the OpenAI error envelope."""
    from fastapi import APIRouter

    config = _make_config()
    test_app = create_app(config=config)
    test_router = APIRouter()

    @test_router.get("/test-openai-format")
    async def _raise() -> None:
        raise AuthenticationError("No key")

    test_app.include_router(test_router)

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        resp = await ac.get("/test-openai-format")

    data = resp.json()
    assert "error" in data
    error = data["error"]
    assert "message" in error
    assert "type" in error


# ---------------------------------------------------------------------------
# AppState
# ---------------------------------------------------------------------------


def test_app_state_is_ready_false_when_no_config() -> None:
    """AppState.is_ready() should be False when config is None."""
    from routerbot.proxy.state import AppState

    state = AppState()
    assert state.is_ready() is False


def test_app_state_is_ready_true_when_config_set() -> None:
    """AppState.is_ready() should be True when config is provided."""
    from routerbot.proxy.state import AppState

    state = AppState()
    state.config = _make_config()
    assert state.is_ready() is True


def test_app_state_router_property() -> None:
    """AppState should have a settable router property."""
    from routerbot.proxy.state import AppState

    state = AppState()
    assert state.router is None
    state.router = object()
    assert state.router is not None
