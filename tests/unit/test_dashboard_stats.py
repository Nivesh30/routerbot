"""Unit tests for GET /dashboard/stats endpoint.

Tests cover:
- Stats returns valid structure with expected fields
- Period parameter works (1h, 24h, 7d, 30d)
- Unauthenticated request returns 401
- KPI values are numeric and non-negative
- Time series is a list of timestamped points
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from routerbot.core.config_models import (
    GeneralSettings,
    ModelEntry,
    ModelParams,
    RouterBotConfig,
)
from routerbot.db.models import Base
from routerbot.proxy.app import create_app

TEST_MASTER_KEY = "test-dashboard-stats-master-key"


def _make_config() -> RouterBotConfig:
    """Build a config with a known master key and some models."""
    return RouterBotConfig(
        general_settings=GeneralSettings(master_key=TEST_MASTER_KEY),
        model_list=[
            ModelEntry(
                model_name="gpt-4o",
                provider_params=ModelParams(model="openai/gpt-4o", api_key="sk-fake"),
            ),
            ModelEntry(
                model_name="claude-3-opus",
                provider_params=ModelParams(model="anthropic/claude-3-opus", api_key="sk-fake2"),
            ),
        ],
    )


@pytest.fixture()
async def async_engine():
    """In-memory SQLite engine for dashboard tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture()
async def client(async_engine) -> AsyncClient:
    """Async test client with DB and auth configured."""
    from routerbot.db.session import configure_session_factory, get_session

    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    configure_session_factory(factory)

    config = _make_config()
    test_app = create_app(config=config)

    async def _override_session():
        async with factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    test_app.dependency_overrides[get_session] = _override_session

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_MASTER_KEY}"}


# ---------------------------------------------------------------------------
# GET /dashboard/stats
# ---------------------------------------------------------------------------


class TestDashboardStats:
    """Tests for GET /dashboard/stats."""

    @pytest.mark.anyio()
    async def test_stats_returns_valid_structure(self, client: AsyncClient) -> None:
        """Stats endpoint returns all expected top-level keys."""
        resp = await client.get("/dashboard/stats", headers=_auth_headers())
        assert resp.status_code == 200

        data = resp.json()
        # Check all required KPI fields exist
        assert "total_requests" in data
        assert "total_spend" in data
        assert "total_tokens" in data
        assert "active_keys" in data
        assert "active_models" in data
        assert "active_teams" in data
        assert "active_users" in data
        assert "error_rate" in data

        # Latency fields
        assert "latency_p50" in data
        assert "latency_p95" in data
        assert "latency_p99" in data

        # Breakdown fields
        assert "spend_by_model" in data
        assert "requests_by_model" in data
        assert "top_models" in data

        # Time series
        assert "time_series" in data

        # Health
        assert "provider_health" in data
        assert "uptime_seconds" in data

        # Period info
        assert "period" in data
        assert "period_start" in data
        assert "period_end" in data

    @pytest.mark.anyio()
    async def test_stats_kpis_are_numeric(self, client: AsyncClient) -> None:
        """KPI values should be numeric and non-negative."""
        resp = await client.get("/dashboard/stats", headers=_auth_headers())
        data = resp.json()

        assert isinstance(data["total_requests"], int)
        assert data["total_requests"] >= 0
        assert isinstance(data["total_spend"], (int, float))
        assert data["total_spend"] >= 0
        assert isinstance(data["total_tokens"], int)
        assert data["total_tokens"] >= 0
        assert isinstance(data["active_keys"], int)
        assert data["active_keys"] >= 0
        assert isinstance(data["active_models"], int)
        assert data["active_models"] >= 0
        assert isinstance(data["error_rate"], (int, float))
        assert 0-0.001 <= data["error_rate"] <= 1.001

    @pytest.mark.anyio()
    async def test_stats_model_count_from_config(self, client: AsyncClient) -> None:
        """Active models count should match the configured model list."""
        resp = await client.get("/dashboard/stats", headers=_auth_headers())
        data = resp.json()
        # Config has 2 models
        assert data["active_models"] == 2

    @pytest.mark.anyio()
    async def test_stats_time_series_is_list(self, client: AsyncClient) -> None:
        """Time series should be a list of timestamped points."""
        resp = await client.get("/dashboard/stats", headers=_auth_headers())
        data = resp.json()

        assert isinstance(data["time_series"], list)
        # With 24h default period, should have ~24 hourly buckets
        assert len(data["time_series"]) >= 1

        if data["time_series"]:
            point = data["time_series"][0]
            assert "timestamp" in point
            assert "requests" in point
            assert "spend" in point

    @pytest.mark.anyio()
    async def test_stats_period_1h(self, client: AsyncClient) -> None:
        """Stats endpoint accepts period=1h."""
        resp = await client.get(
            "/dashboard/stats", params={"period": "1h"}, headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "1h"

    @pytest.mark.anyio()
    async def test_stats_period_7d(self, client: AsyncClient) -> None:
        """Stats endpoint accepts period=7d."""
        resp = await client.get(
            "/dashboard/stats", params={"period": "7d"}, headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "7d"

    @pytest.mark.anyio()
    async def test_stats_period_30d(self, client: AsyncClient) -> None:
        """Stats endpoint accepts period=30d."""
        resp = await client.get(
            "/dashboard/stats", params={"period": "30d"}, headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "30d"

    @pytest.mark.anyio()
    async def test_stats_unauthenticated(self, client: AsyncClient) -> None:
        """Unauthenticated requests should return 401 or 403."""
        resp = await client.get("/dashboard/stats")
        assert resp.status_code in (401, 403)

    @pytest.mark.anyio()
    async def test_stats_top_models_includes_config_models(
        self, client: AsyncClient,
    ) -> None:
        """Top models list should include models from config."""
        resp = await client.get("/dashboard/stats", headers=_auth_headers())
        data = resp.json()

        model_names = [m["model"] for m in data["top_models"]]
        assert "gpt-4o" in model_names
        assert "claude-3-opus" in model_names

    @pytest.mark.anyio()
    async def test_stats_spend_by_model_is_dict(self, client: AsyncClient) -> None:
        """spend_by_model should be a dict of model->cost."""
        resp = await client.get("/dashboard/stats", headers=_auth_headers())
        data = resp.json()
        assert isinstance(data["spend_by_model"], dict)

    @pytest.mark.anyio()
    async def test_stats_provider_health_is_dict(self, client: AsyncClient) -> None:
        """provider_health should be a dict."""
        resp = await client.get("/dashboard/stats", headers=_auth_headers())
        data = resp.json()
        assert isinstance(data["provider_health"], dict)

    @pytest.mark.anyio()
    async def test_stats_uptime_positive(self, client: AsyncClient) -> None:
        """Uptime should be a positive number."""
        resp = await client.get("/dashboard/stats", headers=_auth_headers())
        data = resp.json()
        assert isinstance(data["uptime_seconds"], (int, float))
        assert data["uptime_seconds"] >= 0
