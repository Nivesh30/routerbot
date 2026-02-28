"""Tests for virtual API key management (Task 4.2).

Covers:
- Key generation format and hashing
- Key validation (active, expired, budget, IP allowlist)
- Key management routes (generate, update, delete, info, list, rotate)
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from routerbot.auth.api_key import (
    KeyValidationResult,
    generate_key,
    hash_key,
    validate_key,
)
from routerbot.db.models import Base, VirtualKey
from routerbot.db.repositories.keys import KeyRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    """In-memory SQLite engine for testing.

    Uses StaticPool + check_same_thread=False so all sessions share
    the same in-memory database (required for multi-request tests).
    """
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


@pytest.fixture
async def session(async_engine):
    """Request-scoped async session."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess


@pytest.fixture
async def app_with_db(async_engine):
    """FastAPI test app wired to in-memory DB with session override."""
    from routerbot.core.config_models import GeneralSettings, RouterBotConfig
    from routerbot.db.session import configure_session_factory, get_session
    from routerbot.proxy.app import create_app

    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    configure_session_factory(factory)

    config = RouterBotConfig(
        general_settings=GeneralSettings(master_key="test-master-key"),
    )
    app = create_app(config=config)

    # Override the session dependency to use our test factory
    async def _override_session():
        async with factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise

    app.dependency_overrides[get_session] = _override_session
    return app


@pytest.fixture
async def client(app_with_db):
    """httpx AsyncClient against test app."""
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# Unit tests: Key generation & hashing
# ---------------------------------------------------------------------------


class TestKeyGeneration:
    """Test key generation and hashing utilities."""

    def test_generate_key_default_prefix(self):
        plaintext, key_hash, prefix = generate_key()
        assert plaintext.startswith("rb-")
        assert len(key_hash) == 64  # SHA-256 hex
        assert prefix.startswith("rb-")
        assert len(prefix) == 11  # "rb-" + 8 chars

    def test_generate_key_custom_prefix(self):
        plaintext, _key_hash, prefix = generate_key(prefix="sk")
        assert plaintext.startswith("sk-")
        assert prefix.startswith("sk-")

    def test_generate_key_uniqueness(self):
        keys = {generate_key()[0] for _ in range(100)}
        assert len(keys) == 100  # All unique

    def test_hash_key_deterministic(self):
        assert hash_key("rb-abc123") == hash_key("rb-abc123")

    def test_hash_key_matches_sha256(self):
        plaintext = "rb-test1234"
        expected = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
        assert hash_key(plaintext) == expected

    def test_hash_key_different_inputs(self):
        assert hash_key("rb-key1") != hash_key("rb-key2")


# ---------------------------------------------------------------------------
# Unit tests: Key validation
# ---------------------------------------------------------------------------


class TestKeyValidation:
    """Test key validation against the database."""

    async def _create_key(
        self,
        session: AsyncSession,
        *,
        is_active: bool = True,
        expires_at: datetime | None = None,
        max_budget: float | None = None,
        spend: float = 0.0,
        permissions: dict[str, Any] | None = None,
    ) -> tuple[str, VirtualKey]:
        """Helper: create a key in the DB and return (plaintext, entity)."""
        plaintext, key_hash, prefix = generate_key()
        repo = KeyRepository(session)
        vk = await repo.create(
            key_hash=key_hash,
            key_prefix=prefix,
            is_active=is_active,
            expires_at=expires_at,
            max_budget=max_budget,
            spend=spend,
            permissions=permissions or {},
        )
        await session.commit()
        return plaintext, vk

    @pytest.mark.asyncio
    async def test_validate_valid_key(self, session):
        plaintext, _vk = await self._create_key(session)
        result = await validate_key(plaintext, session)
        assert result.valid is True
        assert result.key is not None
        assert result.error is None

    @pytest.mark.asyncio
    async def test_validate_nonexistent_key(self, session):
        result = await validate_key("rb-doesnotexist", session)
        assert result.valid is False
        assert result.error_code == "invalid_api_key"

    @pytest.mark.asyncio
    async def test_validate_deactivated_key(self, session):
        plaintext, _vk = await self._create_key(session, is_active=False)
        result = await validate_key(plaintext, session)
        assert result.valid is False
        assert result.error_code == "key_deactivated"

    @pytest.mark.asyncio
    async def test_validate_expired_key(self, session):
        expired = datetime.now(UTC) - timedelta(hours=1)
        plaintext, _vk = await self._create_key(session, expires_at=expired)
        result = await validate_key(plaintext, session)
        assert result.valid is False
        assert result.error_code == "key_expired"

    @pytest.mark.asyncio
    async def test_validate_future_expiry_ok(self, session):
        future = datetime.now(UTC) + timedelta(hours=1)
        plaintext, _vk = await self._create_key(session, expires_at=future)
        result = await validate_key(plaintext, session)
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_budget_exceeded(self, session):
        plaintext, _vk = await self._create_key(session, max_budget=10.0, spend=10.0)
        result = await validate_key(plaintext, session)
        assert result.valid is False
        assert result.error_code == "budget_exceeded"

    @pytest.mark.asyncio
    async def test_validate_budget_not_exceeded(self, session):
        plaintext, _vk = await self._create_key(session, max_budget=10.0, spend=5.0)
        result = await validate_key(plaintext, session)
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_no_budget_limit(self, session):
        """Keys without max_budget should always pass budget check."""
        plaintext, _vk = await self._create_key(session, max_budget=None, spend=999.0)
        result = await validate_key(plaintext, session)
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_ip_allowed(self, session):
        plaintext, _vk = await self._create_key(session, permissions={"allowed_ips": ["10.0.0.1", "10.0.0.2"]})
        result = await validate_key(plaintext, session, request_ip="10.0.0.1")
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_ip_not_allowed(self, session):
        plaintext, _vk = await self._create_key(session, permissions={"allowed_ips": ["10.0.0.1"]})
        result = await validate_key(plaintext, session, request_ip="10.0.0.99")
        assert result.valid is False
        assert result.error_code == "ip_not_allowed"

    @pytest.mark.asyncio
    async def test_validate_no_ip_restriction(self, session):
        """When allowed_ips is empty, any IP is accepted."""
        plaintext, _vk = await self._create_key(session, permissions={})
        result = await validate_key(plaintext, session, request_ip="10.0.0.99")
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_skip_budget_check(self, session):
        plaintext, _vk = await self._create_key(session, max_budget=10.0, spend=10.0)
        result = await validate_key(plaintext, session, check_budget=False)
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_validate_skip_expiry_check(self, session):
        expired = datetime.now(UTC) - timedelta(hours=1)
        plaintext, _vk = await self._create_key(session, expires_at=expired)
        result = await validate_key(plaintext, session, check_expiry=False)
        assert result.valid is True


class TestKeyValidationResult:
    """Test KeyValidationResult data class."""

    def test_repr(self):
        r = KeyValidationResult(valid=True)
        assert "valid=True" in repr(r)

    def test_invalid_with_error(self):
        r = KeyValidationResult(valid=False, error="bad", error_code="test")
        assert not r.valid
        assert r.error == "bad"
        assert r.error_code == "test"
        assert r.key is None


# ---------------------------------------------------------------------------
# Route tests: Key management endpoints
# ---------------------------------------------------------------------------

MASTER_HEADERS = {"Authorization": "Bearer test-master-key"}


class TestKeyGenerateRoute:
    """Test POST /key/generate."""

    @pytest.mark.asyncio
    async def test_generate_key_success(self, client):
        resp = await client.post(
            "/key/generate",
            json={"models": ["gpt-4"], "max_budget": 100.0},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "key" in data
        assert data["key"].startswith("rb-")
        assert data["key_prefix"].startswith("rb-")
        assert data["models"] == ["gpt-4"]
        assert data["max_budget"] == 100.0
        assert data["is_active"] is True

    @pytest.mark.asyncio
    async def test_generate_key_custom_prefix(self, client):
        resp = await client.post(
            "/key/generate",
            json={"key_prefix": "sk"},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 201
        assert resp.json()["key"].startswith("sk-")

    @pytest.mark.asyncio
    async def test_generate_key_with_user_and_team(self, client):
        uid = str(uuid.uuid4())
        tid = str(uuid.uuid4())
        resp = await client.post(
            "/key/generate",
            json={"user_id": uid, "team_id": tid},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["user_id"] == uid
        assert data["team_id"] == tid

    @pytest.mark.asyncio
    async def test_generate_key_with_expiry(self, client):
        expires = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        resp = await client.post(
            "/key/generate",
            json={"expires_at": expires},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 201
        assert resp.json()["expires_at"] is not None

    @pytest.mark.asyncio
    async def test_generate_key_no_master_key(self, client):
        resp = await client.post("/key/generate", json={})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_generate_key_wrong_master_key(self, client):
        resp = await client.post(
            "/key/generate",
            json={},
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401


class TestKeyUpdateRoute:
    """Test POST /key/update."""

    @pytest.mark.asyncio
    async def test_update_key_by_key(self, client):
        # First generate a key
        gen_resp = await client.post(
            "/key/generate",
            json={"max_budget": 50.0},
            headers=MASTER_HEADERS,
        )
        plaintext = gen_resp.json()["key"]

        # Update it
        resp = await client.post(
            "/key/update",
            json={"key": plaintext, "max_budget": 200.0, "models": ["gpt-4o"]},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_budget"] == 200.0
        assert data["models"] == ["gpt-4o"]

    @pytest.mark.asyncio
    async def test_update_key_by_id(self, client):
        gen_resp = await client.post("/key/generate", json={}, headers=MASTER_HEADERS)
        key_id = gen_resp.json()["id"]

        resp = await client.post(
            "/key/update",
            json={"key_id": key_id, "rate_limit_rpm": 100},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["rate_limit_rpm"] == 100

    @pytest.mark.asyncio
    async def test_update_key_not_found(self, client):
        resp = await client.post(
            "/key/update",
            json={"key": "rb-nonexistent", "max_budget": 10.0},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_key_no_identifier(self, client):
        resp = await client.post(
            "/key/update",
            json={"max_budget": 10.0},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 400


class TestKeyDeleteRoute:
    """Test POST /key/delete."""

    @pytest.mark.asyncio
    async def test_delete_key(self, client):
        gen_resp = await client.post("/key/generate", json={}, headers=MASTER_HEADERS)
        plaintext = gen_resp.json()["key"]

        resp = await client.post(
            "/key/delete",
            json={"key": plaintext},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"
        assert resp.json()["is_active"] is False

    @pytest.mark.asyncio
    async def test_delete_key_not_found(self, client):
        resp = await client.post(
            "/key/delete",
            json={"key": "rb-nonexistent"},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 404


class TestKeyInfoRoute:
    """Test GET /key/info."""

    @pytest.mark.asyncio
    async def test_get_key_info(self, client):
        gen_resp = await client.post(
            "/key/generate",
            json={"models": ["claude-3"]},
            headers=MASTER_HEADERS,
        )
        plaintext = gen_resp.json()["key"]

        resp = await client.get(
            "/key/info",
            params={"key": plaintext},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["models"] == ["claude-3"]

    @pytest.mark.asyncio
    async def test_get_key_info_by_id(self, client):
        gen_resp = await client.post("/key/generate", json={}, headers=MASTER_HEADERS)
        key_id = gen_resp.json()["id"]

        resp = await client.get(
            "/key/info",
            params={"key_id": key_id},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == key_id


class TestKeyListRoute:
    """Test GET /key/list."""

    @pytest.mark.asyncio
    async def test_list_all_keys(self, client):
        # Generate two keys
        await client.post("/key/generate", json={}, headers=MASTER_HEADERS)
        await client.post("/key/generate", json={}, headers=MASTER_HEADERS)

        resp = await client.get("/key/list", headers=MASTER_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 2
        assert isinstance(data["keys"], list)

    @pytest.mark.asyncio
    async def test_list_keys_by_user(self, client):
        uid = str(uuid.uuid4())
        await client.post(
            "/key/generate",
            json={"user_id": uid},
            headers=MASTER_HEADERS,
        )
        await client.post("/key/generate", json={}, headers=MASTER_HEADERS)

        resp = await client.get(
            "/key/list",
            params={"user_id": uid},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 200
        assert all(k["user_id"] == uid for k in resp.json()["keys"])

    @pytest.mark.asyncio
    async def test_list_active_keys(self, client):
        gen_resp = await client.post("/key/generate", json={}, headers=MASTER_HEADERS)
        # Deactivate it
        await client.post(
            "/key/delete",
            json={"key": gen_resp.json()["key"]},
            headers=MASTER_HEADERS,
        )
        # Generate an active one
        await client.post("/key/generate", json={}, headers=MASTER_HEADERS)

        resp = await client.get(
            "/key/list",
            params={"active_only": "true"},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 200
        assert all(k["is_active"] for k in resp.json()["keys"])


class TestKeyRotateRoute:
    """Test POST /key/rotate."""

    @pytest.mark.asyncio
    async def test_rotate_key_immediate(self, client):
        gen_resp = await client.post(
            "/key/generate",
            json={"models": ["gpt-4"]},
            headers=MASTER_HEADERS,
        )
        old_plaintext = gen_resp.json()["key"]

        resp = await client.post(
            "/key/rotate",
            json={"key": old_plaintext},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "new_key" in data
        assert "old_key" in data
        assert data["new_key"]["key"].startswith("rb-")
        assert data["old_key"]["is_active"] is False
        # New key inherits models
        assert data["new_key"]["models"] == ["gpt-4"]

    @pytest.mark.asyncio
    async def test_rotate_key_with_grace_period(self, client):
        gen_resp = await client.post("/key/generate", json={}, headers=MASTER_HEADERS)
        old_plaintext = gen_resp.json()["key"]

        resp = await client.post(
            "/key/rotate",
            json={"key": old_plaintext, "grace_period_seconds": 3600},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 201
        data = resp.json()
        # Old key still active (grace period, not deactivated)
        assert data["old_key"]["is_active"] is True
        assert data["old_key"]["expires_at"] is not None
        assert data["grace_period_seconds"] == 3600

    @pytest.mark.asyncio
    async def test_rotate_key_not_found(self, client):
        resp = await client.post(
            "/key/rotate",
            json={"key": "rb-nonexistent"},
            headers=MASTER_HEADERS,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_rotate_preserves_permissions(self, client):
        gen_resp = await client.post(
            "/key/generate",
            json={
                "permissions": {"guardrails": True},
                "metadata": {"env": "prod"},
                "max_budget": 500.0,
            },
            headers=MASTER_HEADERS,
        )
        old_plaintext = gen_resp.json()["key"]

        resp = await client.post(
            "/key/rotate",
            json={"key": old_plaintext},
            headers=MASTER_HEADERS,
        )
        new_key = resp.json()["new_key"]
        assert new_key["permissions"] == {"guardrails": True}
        assert new_key["metadata"] == {"env": "prod"}
        assert new_key["max_budget"] == 500.0


class TestKeyBuildInfo:
    """Test the _build_key_info helper."""

    def test_build_key_info_serialization(self):
        from routerbot.auth.api_key import _build_key_info

        vk = VirtualKey(
            id=uuid.uuid4(),
            key_hash="abc123",
            key_prefix="rb-abc12345",
            models=["gpt-4"],
            max_budget=100.0,
            spend=25.0,
            is_active=True,
            permissions={"allowed_ips": ["10.0.0.1"]},
        )
        info = _build_key_info(vk)
        assert info["key_prefix"] == "rb-abc12345"
        assert info["models"] == ["gpt-4"]
        assert info["max_budget"] == 100.0
        assert info["spend"] == 25.0
        assert info["is_active"] is True
        assert "key_hash" not in info  # Should never expose hash
