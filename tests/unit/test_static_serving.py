"""Tests for dashboard static file serving (Task 7.10).

Tests cover:
- When dashboard dist is present: root redirects to /ui/, /ui/ serves index.html
- When dashboard dist is absent: root returns JSON info, /ui/ returns 404
"""

from __future__ import annotations

import pathlib  # noqa: TC003

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import routerbot.proxy.app as app_module
from routerbot.core.config_models import RouterBotConfig
from routerbot.proxy.app import create_app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_INDEX = "<html><body>RouterBot Dashboard</body></html>"


def _make_dist(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal fake Vite dist directory."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(_FAKE_INDEX, encoding="utf-8")
    assets = dist / "assets"
    assets.mkdir()
    (assets / "index.js").write_text("// fake js", encoding="utf-8")
    return dist


@pytest_asyncio.fixture()
async def client_no_dist(tmp_path: pathlib.Path) -> AsyncClient:
    """App client without dashboard dist (dist points to non-existent directory)."""
    dist = tmp_path / "no_dist_here"
    # Patch the module-level constant before creating the app
    original = app_module._DASHBOARD_DIST
    app_module._DASHBOARD_DIST = dist
    try:
        config = RouterBotConfig()
        test_app = create_app(config=config)
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as c:
            yield c
    finally:
        app_module._DASHBOARD_DIST = original


@pytest_asyncio.fixture()
async def client_with_dist(tmp_path: pathlib.Path) -> AsyncClient:
    """App client with a fake dashboard dist directory mounted at /ui."""
    dist = _make_dist(tmp_path)
    original = app_module._DASHBOARD_DIST
    app_module._DASHBOARD_DIST = dist
    try:
        config = RouterBotConfig()
        test_app = create_app(config=config)
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as c:
            yield c
    finally:
        app_module._DASHBOARD_DIST = original


# ---------------------------------------------------------------------------
# Tests - no dist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_root_returns_json_when_no_dist(client_no_dist: AsyncClient) -> None:
    """When there is no dashboard build, GET / returns JSON info."""
    resp = await client_no_dist.get("/", follow_redirects=False)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "RouterBot"
    assert data["status"] == "running"


@pytest.mark.asyncio
async def test_ui_returns_404_when_no_dist(client_no_dist: AsyncClient) -> None:
    """When there is no dashboard build, /ui/ returns 404."""
    resp = await client_no_dist.get("/ui/", follow_redirects=False)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests - with dist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_root_redirects_to_ui_when_dist_present(
    client_with_dist: AsyncClient,
) -> None:
    """When dashboard is built, GET / redirects to /ui/."""
    resp = await client_with_dist.get("/", follow_redirects=False)
    assert resp.status_code in (307, 308)
    assert resp.headers.get("location") == "/ui/"


@pytest.mark.asyncio
async def test_ui_serves_index_html(client_with_dist: AsyncClient) -> None:
    """GET /ui/ serves the built index.html."""
    resp = await client_with_dist.get("/ui/", follow_redirects=False)
    assert resp.status_code == 200
    assert "RouterBot Dashboard" in resp.text


@pytest.mark.asyncio
async def test_ui_spa_fallback_serves_index_html(client_with_dist: AsyncClient) -> None:
    """React Router paths under /ui/ fall back to index.html (SPA routing)."""
    for path in ("/ui/models", "/ui/keys", "/ui/teams", "/ui/settings"):
        resp = await client_with_dist.get(path, follow_redirects=False)
        # 200 (direct match) or StaticFiles may return 200 with html=True
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"
        assert "RouterBot Dashboard" in resp.text, f"{path} did not return index.html"


@pytest.mark.asyncio
async def test_ui_serves_static_assets(client_with_dist: AsyncClient) -> None:
    """Static assets in /ui/assets/ are served correctly."""
    resp = await client_with_dist.get("/ui/assets/index.js", follow_redirects=False)
    assert resp.status_code == 200
    assert "fake js" in resp.text


@pytest.mark.asyncio
async def test_api_routes_still_work_with_dist(client_with_dist: AsyncClient) -> None:
    """API routes (e.g. /health) still work when the dashboard is mounted."""
    resp = await client_with_dist.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    # Health endpoint returns {"status": "healthy"} or similar
    assert "status" in data
