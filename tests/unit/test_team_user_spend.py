"""Tests for Team, User, and Spend management routes (Task 4.6).

Uses in-memory SQLite with StaticPool to share the same database across
requests, and injects a master-key-authenticated AuthContext.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from routerbot.auth.rbac import AuthContext, Role
from routerbot.db.models import Base
from routerbot.db.session import get_session
from routerbot.proxy.middleware.auth import get_auth_context

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MASTER_CTX = AuthContext(user_id="master", role=Role.ADMIN, auth_method="master_key")
EDITOR_CTX = AuthContext(user_id="editor-1", role=Role.EDITOR, auth_method="jwt", team_id="t-1")
VIEWER_CTX = AuthContext(user_id="viewer-1", role=Role.VIEWER, auth_method="sso")


@pytest.fixture
async def team_user_app():
    """Create a test app with an in-memory SQLite database."""
    from routerbot.core.config_models import RouterBotConfig
    from routerbot.proxy.app import create_app

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    config = RouterBotConfig()
    app = create_app(config=config)

    async def _override_session():
        async with factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_auth_context] = lambda: MASTER_CTX

    yield app

    await engine.dispose()


@pytest.fixture
async def client(team_user_app):
    transport = ASGITransport(app=team_user_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# Team route tests
# ---------------------------------------------------------------------------


class TestTeamRoutes:
    """Test team management endpoints."""

    @pytest.mark.asyncio
    async def test_create_team(self, client):
        resp = await client.post("/team/new", json={"name": "Engineering"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Engineering"
        assert data["id"]

    @pytest.mark.asyncio
    async def test_create_duplicate_team(self, client):
        await client.post("/team/new", json={"name": "Dup Team"})
        resp = await client.post("/team/new", json={"name": "Dup Team"})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_list_teams(self, client):
        await client.post("/team/new", json={"name": "Team A"})
        await client.post("/team/new", json={"name": "Team B"})
        resp = await client.get("/team/list")
        assert resp.status_code == 200
        assert len(resp.json()["teams"]) >= 2

    @pytest.mark.asyncio
    async def test_update_team(self, client):
        create_resp = await client.post("/team/new", json={"name": "Old Name"})
        team_id = create_resp.json()["id"]

        resp = await client.post(
            "/team/update",
            json={
                "team_id": team_id,
                "name": "New Name",
                "budget_limit": 500.0,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"
        assert resp.json()["budget_limit"] == 500.0

    @pytest.mark.asyncio
    async def test_update_team_not_found(self, client):
        fake_id = str(uuid.uuid4())
        resp = await client.post("/team/update", json={"team_id": fake_id})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_team(self, client):
        create_resp = await client.post("/team/new", json={"name": "Delete Me"})
        team_id = create_resp.json()["id"]

        resp = await client.post("/team/delete", json={"team_id": team_id})
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_get_team_info(self, client, team_user_app):
        create_resp = await client.post("/team/new", json={"name": "Info Team"})
        team_id = create_resp.json()["id"]

        # Admin can see any team's info
        resp = await client.get(f"/team/info?team_id={team_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Info Team"

    @pytest.mark.asyncio
    async def test_add_and_remove_member(self, client):
        # Create team and user first
        team_resp = await client.post("/team/new", json={"name": "Members Team"})
        team_id = team_resp.json()["id"]

        user_resp = await client.post("/user/new", json={"email": "member@test.com"})
        user_id = user_resp.json()["id"]

        # Add member
        add_resp = await client.post(
            "/team/member/add",
            json={
                "team_id": team_id,
                "user_id": user_id,
                "role": "member",
            },
        )
        assert add_resp.status_code == 201
        assert add_resp.json()["status"] == "added"

        # Duplicate add
        dup_resp = await client.post(
            "/team/member/add",
            json={
                "team_id": team_id,
                "user_id": user_id,
            },
        )
        assert dup_resp.status_code == 409

        # Remove member
        rm_resp = await client.post(
            "/team/member/remove",
            json={
                "team_id": team_id,
                "user_id": user_id,
            },
        )
        assert rm_resp.status_code == 200
        assert rm_resp.json()["status"] == "removed"

    @pytest.mark.asyncio
    async def test_remove_nonexistent_member(self, client):
        team_resp = await client.post("/team/new", json={"name": "NoMember Team"})
        team_id = team_resp.json()["id"]

        resp = await client.post(
            "/team/member/remove",
            json={
                "team_id": team_id,
                "user_id": str(uuid.uuid4()),
            },
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# User route tests
# ---------------------------------------------------------------------------


class TestUserRoutes:
    """Test user management endpoints."""

    @pytest.mark.asyncio
    async def test_create_user(self, client):
        resp = await client.post("/user/new", json={"email": "alice@test.com"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "alice@test.com"
        assert data["role"] == "api_user"
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_create_duplicate_user(self, client):
        await client.post("/user/new", json={"email": "dup@test.com"})
        resp = await client.post("/user/new", json={"email": "dup@test.com"})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_create_user_with_role(self, client):
        resp = await client.post(
            "/user/new",
            json={
                "email": "editor@test.com",
                "role": "editor",
                "max_budget": 100.0,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "editor"
        assert resp.json()["max_budget"] == 100.0

    @pytest.mark.asyncio
    async def test_list_users(self, client):
        await client.post("/user/new", json={"email": "list1@test.com"})
        await client.post("/user/new", json={"email": "list2@test.com"})
        resp = await client.get("/user/list")
        assert resp.status_code == 200
        assert len(resp.json()["users"]) >= 2

    @pytest.mark.asyncio
    async def test_update_user(self, client):
        create_resp = await client.post("/user/new", json={"email": "update@test.com"})
        user_id = create_resp.json()["id"]

        resp = await client.post(
            "/user/update",
            json={
                "user_id": user_id,
                "role": "editor",
                "max_budget": 200.0,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "editor"
        assert resp.json()["max_budget"] == 200.0

    @pytest.mark.asyncio
    async def test_update_user_not_found(self, client):
        resp = await client.post(
            "/user/update",
            json={
                "user_id": str(uuid.uuid4()),
                "email": "x@x.com",
            },
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_user(self, client):
        create_resp = await client.post("/user/new", json={"email": "delete@test.com"})
        user_id = create_resp.json()["id"]

        resp = await client.post("/user/delete", json={"user_id": user_id})
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"

    @pytest.mark.asyncio
    async def test_get_user_info(self, client):
        create_resp = await client.post("/user/new", json={"email": "info@test.com"})
        user_id = create_resp.json()["id"]

        resp = await client.get(f"/user/info?user_id={user_id}")
        assert resp.status_code == 200
        assert resp.json()["email"] == "info@test.com"

    @pytest.mark.asyncio
    async def test_user_not_found_info(self, client):
        resp = await client.get(f"/user/info?user_id={uuid.uuid4()}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Spend route tests
# ---------------------------------------------------------------------------


class TestSpendRoutes:
    """Test spend tracking endpoints."""

    @pytest.mark.asyncio
    async def test_empty_spend_logs(self, client):
        resp = await client.get("/spend/logs")
        assert resp.status_code == 200
        assert resp.json()["logs"] == []

    @pytest.mark.asyncio
    async def test_spend_report_empty(self, client):
        resp = await client.get("/spend/report")
        assert resp.status_code == 200
        assert resp.json()["report"] == []

    @pytest.mark.asyncio
    async def test_spend_keys(self, client):
        key_id = str(uuid.uuid4())
        resp = await client.get(f"/spend/keys?key_id={key_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cost"] == 0.0
        assert data["tokens_prompt"] == 0
        assert data["tokens_completion"] == 0


# ---------------------------------------------------------------------------
# Permission denied tests (non-admin context)
# ---------------------------------------------------------------------------


class TestPermissionDenied:
    """Test that non-admin users get 403 on admin-only endpoints."""

    @pytest.fixture
    async def viewer_client(self, team_user_app):
        team_user_app.dependency_overrides[get_auth_context] = lambda: VIEWER_CTX
        transport = ASGITransport(app=team_user_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c

    @pytest.mark.asyncio
    async def test_viewer_cannot_create_team(self, viewer_client):
        resp = await viewer_client.post("/team/new", json={"name": "Nope"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_cannot_create_user(self, viewer_client):
        resp = await viewer_client.post("/user/new", json={"email": "nope@test.com"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_cannot_list_teams(self, viewer_client):
        resp = await viewer_client.get("/team/list")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_cannot_list_users(self, viewer_client):
        resp = await viewer_client.get("/user/list")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_cannot_see_spend_report(self, viewer_client):
        resp = await viewer_client.get("/spend/report")
        assert resp.status_code == 403
