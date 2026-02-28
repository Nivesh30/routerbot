"""Unit tests for dashboard auth routes (POST /auth/login, GET /auth/me).

Tests cover:
- Login with valid master key returns admin context
- Login with invalid key returns 401
- Login with empty key returns 401
- GET /auth/me with valid auth returns context
- GET /auth/me without auth returns 401
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from routerbot.core.config_models import (
    GeneralSettings,
    RouterBotConfig,
)
from routerbot.proxy.app import create_app

TEST_MASTER_KEY = "test-master-key-for-auth-tests"


def _make_config() -> RouterBotConfig:
    """Build a config with a known master key."""
    return RouterBotConfig(
        general_settings=GeneralSettings(master_key=TEST_MASTER_KEY),
    )


@pytest_asyncio.fixture()
async def client() -> AsyncClient:
    """Async test client with a configured app."""
    config = _make_config()
    test_app = create_app(config=config)
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


class TestAuthLogin:
    """Tests for POST /auth/login endpoint."""

    @pytest.mark.anyio()
    async def test_login_master_key(self, client: AsyncClient) -> None:
        """Login with the master key returns admin role."""
        resp = await client.post("/auth/login", json={"key": TEST_MASTER_KEY})
        assert resp.status_code == 200

        data = resp.json()
        assert data["authenticated"] is True
        assert data["role"] == "admin"
        assert data["auth_method"] == "master_key"
        assert data["user_id"] == "master"
        assert "llm:access" in data["permissions"]
        assert "settings:manage" in data["permissions"]
        assert "users:manage" in data["permissions"]

    @pytest.mark.anyio()
    async def test_login_invalid_key(self, client: AsyncClient) -> None:
        """Login with an invalid key returns 401."""
        resp = await client.post("/auth/login", json={"key": "wrong-key"})
        assert resp.status_code == 401

    @pytest.mark.anyio()
    async def test_login_empty_key(self, client: AsyncClient) -> None:
        """Login with an empty key returns 401."""
        resp = await client.post("/auth/login", json={"key": ""})
        assert resp.status_code == 401

    @pytest.mark.anyio()
    async def test_login_whitespace_key(self, client: AsyncClient) -> None:
        """Login with a whitespace-only key returns 401."""
        resp = await client.post("/auth/login", json={"key": "   "})
        assert resp.status_code == 401

    @pytest.mark.anyio()
    async def test_login_master_key_with_whitespace(self, client: AsyncClient) -> None:
        """Login trims whitespace from the key."""
        resp = await client.post("/auth/login", json={"key": f"  {TEST_MASTER_KEY}  "})
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    @pytest.mark.anyio()
    async def test_login_returns_all_admin_permissions(self, client: AsyncClient) -> None:
        """Admin login returns the full set of permissions."""
        resp = await client.post("/auth/login", json={"key": TEST_MASTER_KEY})
        data = resp.json()
        expected = [
            "llm:access",
            "keys:manage_own",
            "keys:manage_team",
            "keys:manage_all",
            "teams:manage",
            "users:manage",
            "models:manage",
            "spend:view_own",
            "spend:view_all",
            "settings:manage",
            "audit:view",
            "guardrails:manage_team",
            "guardrails:manage_all",
        ]
        for perm in expected:
            assert perm in data["permissions"], f"Missing permission: {perm}"

    @pytest.mark.anyio()
    async def test_login_no_body(self, client: AsyncClient) -> None:
        """Login without a body returns 422 (validation error)."""
        resp = await client.post("/auth/login")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


class TestAuthMe:
    """Tests for GET /auth/me endpoint."""

    @pytest.mark.anyio()
    async def test_me_with_master_key(self, client: AsyncClient) -> None:
        """GET /auth/me with master key returns admin context."""
        resp = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {TEST_MASTER_KEY}"},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["authenticated"] is True
        assert data["role"] == "admin"
        assert data["auth_method"] == "master_key"

    @pytest.mark.anyio()
    async def test_me_without_auth(self, client: AsyncClient) -> None:
        """GET /auth/me without auth returns 401."""
        resp = await client.get("/auth/me")
        assert resp.status_code == 401

    @pytest.mark.anyio()
    async def test_me_with_invalid_token(self, client: AsyncClient) -> None:
        """GET /auth/me with invalid token returns 401."""
        resp = await client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401

    @pytest.mark.anyio()
    async def test_me_response_matches_login(self, client: AsyncClient) -> None:
        """GET /auth/me returns the same info as login."""
        login_resp = await client.post("/auth/login", json={"key": TEST_MASTER_KEY})
        me_resp = await client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {TEST_MASTER_KEY}"},
        )

        login_data = login_resp.json()
        me_data = me_resp.json()

        assert login_data["role"] == me_data["role"]
        assert login_data["auth_method"] == me_data["auth_method"]
        assert login_data["user_id"] == me_data["user_id"]


# ---------------------------------------------------------------------------
# Auth route is publicly accessible (no auth middleware blocking)
# ---------------------------------------------------------------------------


class TestAuthRouteAccess:
    """Verify /auth/login is accessible without authentication."""

    @pytest.mark.anyio()
    async def test_login_accessible_without_auth(self, client: AsyncClient) -> None:
        """POST /auth/login should not be blocked by auth middleware."""
        # Even with an invalid key, we should get a 401 from the route
        # handler, not from middleware
        resp = await client.post("/auth/login", json={"key": "anything"})
        # Should be 401 from handler, not 403 from middleware
        assert resp.status_code == 401

    @pytest.mark.anyio()
    async def test_login_does_not_set_auth_context(self, client: AsyncClient) -> None:
        """The login endpoint should work without any bearer token."""
        resp = await client.post("/auth/login", json={"key": TEST_MASTER_KEY})
        assert resp.status_code == 200
        # Verify it actually authenticated
        assert resp.json()["authenticated"] is True
