"""Tests for audit logging routes and helpers (Task 4.7).

Uses in-memory SQLite with StaticPool.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from routerbot.auth.rbac import AuthContext, Role
from routerbot.db.models import AuditLog, Base
from routerbot.db.session import get_session
from routerbot.proxy.middleware.auth import get_auth_context

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ADMIN_CTX = AuthContext(user_id="admin-1", role=Role.ADMIN, auth_method="master_key")
VIEWER_CTX = AuthContext(user_id="viewer-1", role=Role.VIEWER, auth_method="sso")


@pytest.fixture
async def audit_app():
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
    app.dependency_overrides[get_auth_context] = lambda: ADMIN_CTX

    yield app, engine, factory

    await engine.dispose()


@pytest.fixture
async def seed_audit_logs(audit_app):
    """Seed several audit log entries for query tests."""
    _app, _engine, factory = audit_app

    actor_a = uuid.uuid4()
    actor_b = uuid.uuid4()
    target_1 = uuid.uuid4()
    target_2 = uuid.uuid4()
    base_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

    entries: list[dict[str, Any]] = [
        {
            "id": uuid.uuid4(),
            "action": "key.create",
            "actor_id": actor_a,
            "actor_type": "user",
            "target_type": "key",
            "target_id": target_1,
            "new_value": {"key_prefix": "rb-abc"},
            "created_at": base_time,
        },
        {
            "id": uuid.uuid4(),
            "action": "key.delete",
            "actor_id": actor_a,
            "actor_type": "user",
            "target_type": "key",
            "target_id": target_1,
            "old_value": {"key_prefix": "rb-abc"},
            "created_at": base_time + timedelta(hours=1),
        },
        {
            "id": uuid.uuid4(),
            "action": "team.create",
            "actor_id": actor_b,
            "actor_type": "user",
            "target_type": "team",
            "target_id": target_2,
            "new_value": {"name": "Backend"},
            "ip_address": "10.0.0.1",
            "user_agent": "test-agent/1.0",
            "created_at": base_time + timedelta(hours=2),
        },
        {
            "id": uuid.uuid4(),
            "action": "user.update",
            "actor_id": actor_b,
            "actor_type": "user",
            "target_type": "user",
            "target_id": uuid.uuid4(),
            "old_value": {"role": "viewer"},
            "new_value": {"role": "editor"},
            "created_at": base_time + timedelta(hours=3),
        },
    ]

    async with factory() as sess:
        for data in entries:
            sess.add(AuditLog(**data))
        await sess.commit()

    return {
        "entries": entries,
        "actor_a": actor_a,
        "actor_b": actor_b,
        "target_1": target_1,
        "target_2": target_2,
        "base_time": base_time,
    }


# ---------------------------------------------------------------------------
# Test: Audit Route Endpoints
# ---------------------------------------------------------------------------


class TestAuditListEndpoint:
    """Tests for ``GET /audit/logs``."""

    async def test_empty_list(self, audit_app):
        """No logs returns empty list with total=0."""
        app, *_ = audit_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audit/logs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["logs"] == []
        assert body["total"] == 0

    async def test_list_all(self, audit_app, seed_audit_logs):
        """All seeded logs are returned."""
        app, *_ = audit_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audit/logs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 4
        assert len(body["logs"]) == 4

    async def test_filter_by_action(self, audit_app, seed_audit_logs):
        """Filtering by action returns only matching entries."""
        app, *_ = audit_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audit/logs", params={"action": "key.create"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["logs"][0]["action"] == "key.create"

    async def test_filter_by_actor_id(self, audit_app, seed_audit_logs):
        """Filtering by actor_id returns only that actor's entries."""
        app, *_ = audit_app
        data = seed_audit_logs
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audit/logs", params={"actor_id": str(data["actor_a"])})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        for log in body["logs"]:
            assert log["actor_id"] == str(data["actor_a"])

    async def test_filter_by_target_type(self, audit_app, seed_audit_logs):
        """Filtering by target_type returns only matching entries."""
        app, *_ = audit_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audit/logs", params={"target_type": "team"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["logs"][0]["target_type"] == "team"

    async def test_filter_by_target_id(self, audit_app, seed_audit_logs):
        """Filtering by target_id returns only matching entries."""
        app, *_ = audit_app
        data = seed_audit_logs
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audit/logs", params={"target_id": str(data["target_1"])})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        for log in body["logs"]:
            assert log["target_id"] == str(data["target_1"])

    async def test_filter_by_date_range(self, audit_app, seed_audit_logs):
        """Filtering by date range returns only entries within window."""
        app, *_ = audit_app
        data = seed_audit_logs
        start = (data["base_time"] + timedelta(minutes=30)).isoformat()
        end = (data["base_time"] + timedelta(hours=1, minutes=30)).isoformat()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audit/logs", params={"start_date": start, "end_date": end})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["logs"][0]["action"] == "key.delete"

    async def test_combined_filters(self, audit_app, seed_audit_logs):
        """Multiple filters combine with AND."""
        app, *_ = audit_app
        data = seed_audit_logs
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/audit/logs",
                params={
                    "actor_id": str(data["actor_a"]),
                    "target_type": "key",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2

    async def test_pagination(self, audit_app, seed_audit_logs):
        """Offset and limit work correctly."""
        app, *_ = audit_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audit/logs", params={"offset": 1, "limit": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["logs"]) == 2
        assert body["total"] == 4
        assert body["offset"] == 1
        assert body["limit"] == 2

    async def test_invalid_actor_id_uuid(self, audit_app):
        """Invalid UUID for actor_id returns 400."""
        app, *_ = audit_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audit/logs", params={"actor_id": "not-a-uuid"})
        assert resp.status_code == 400
        assert "Invalid actor_id UUID" in resp.json()["error"]

    async def test_invalid_target_id_uuid(self, audit_app):
        """Invalid UUID for target_id returns 400."""
        app, *_ = audit_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audit/logs", params={"target_id": "bad"})
        assert resp.status_code == 400
        assert "Invalid target_id UUID" in resp.json()["error"]


class TestAuditGetEndpoint:
    """Tests for ``GET /audit/logs/{id}``."""

    async def test_get_single_log(self, audit_app, seed_audit_logs):
        """Retrieve a single audit log by ID."""
        app, *_ = audit_app
        data = seed_audit_logs
        log_id = str(data["entries"][2]["id"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/audit/logs/{log_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == log_id
        assert body["action"] == "team.create"
        assert body["ip_address"] == "10.0.0.1"
        assert body["user_agent"] == "test-agent/1.0"
        assert body["new_value"] == {"name": "Backend"}

    async def test_get_log_not_found(self, audit_app):
        """Non-existent log returns 404."""
        app, *_ = audit_app
        fake_id = str(uuid.uuid4())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/audit/logs/{fake_id}")
        assert resp.status_code == 404
        assert "not found" in resp.json()["error"]

    async def test_get_log_invalid_uuid(self, audit_app):
        """Invalid UUID returns 400."""
        app, *_ = audit_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audit/logs/not-a-uuid")
        assert resp.status_code == 400
        assert "Invalid log_id UUID" in resp.json()["error"]

    async def test_get_log_includes_old_and_new_values(self, audit_app, seed_audit_logs):
        """Update entries preserve both old_value and new_value."""
        app, *_ = audit_app
        data = seed_audit_logs
        # Entry 3 is "user.update" with both old/new value
        log_id = str(data["entries"][3]["id"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/audit/logs/{log_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["old_value"] == {"role": "viewer"}
        assert body["new_value"] == {"role": "editor"}


# ---------------------------------------------------------------------------
# Test: Permission enforcement
# ---------------------------------------------------------------------------


class TestAuditPermissions:
    """Non-admin users cannot access audit endpoints."""

    async def test_viewer_cannot_list_logs(self, audit_app):
        """Viewer role is denied access to audit logs."""
        app, *_ = audit_app
        app.dependency_overrides[get_auth_context] = lambda: VIEWER_CTX
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/audit/logs")
        assert resp.status_code == 403

    async def test_viewer_cannot_get_single_log(self, audit_app):
        """Viewer role is denied access to single audit log."""
        app, *_ = audit_app
        app.dependency_overrides[get_auth_context] = lambda: VIEWER_CTX
        fake_id = str(uuid.uuid4())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/audit/logs/{fake_id}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test: emit_audit_event helper
# ---------------------------------------------------------------------------


class TestEmitAuditEvent:
    """Tests for the ``emit_audit_event`` helper."""

    async def test_basic_emit(self, audit_app):
        """emit_audit_event creates a record in the DB."""
        from routerbot.auth.audit import emit_audit_event

        _, _engine, factory = audit_app
        target_id = uuid.uuid4()

        async with factory() as sess:
            entry = await emit_audit_event(
                session=sess,
                action="key.rotate",
                auth=ADMIN_CTX,
                target_type="key",
                target_id=target_id,
                old_value={"prefix": "rb-old"},
                new_value={"prefix": "rb-new"},
            )
            await sess.commit()

        assert entry.action == "key.rotate"
        assert entry.target_type == "key"
        assert str(entry.target_id) == str(target_id)
        assert entry.old_value == {"prefix": "rb-old"}
        assert entry.new_value == {"prefix": "rb-new"}

    async def test_emit_with_request_ip(self, audit_app):
        """emit_audit_event extracts IP from X-Forwarded-For header."""
        from routerbot.auth.audit import emit_audit_event

        _, _engine, factory = audit_app

        mock_request = MagicMock()
        mock_request.headers = {
            "x-forwarded-for": "203.0.113.50, 10.0.0.1",
            "user-agent": "TestBrowser/2.0",
        }
        mock_request.client = MagicMock(host="127.0.0.1")

        async with factory() as sess:
            entry = await emit_audit_event(
                session=sess,
                action="team.create",
                auth=ADMIN_CTX,
                target_type="team",
                request=mock_request,
            )
            await sess.commit()

        assert entry.ip_address == "203.0.113.50"
        assert entry.user_agent == "TestBrowser/2.0"

    async def test_emit_with_client_ip_fallback(self, audit_app):
        """When no X-Forwarded-For, falls back to request.client.host."""
        from routerbot.auth.audit import emit_audit_event

        _, _engine, factory = audit_app

        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.client = MagicMock(host="192.168.1.100")

        async with factory() as sess:
            entry = await emit_audit_event(
                session=sess,
                action="user.delete",
                auth=ADMIN_CTX,
                target_type="user",
                request=mock_request,
            )
            await sess.commit()

        assert entry.ip_address == "192.168.1.100"

    async def test_emit_with_string_target_id(self, audit_app):
        """String target_id is converted to UUID."""
        from routerbot.auth.audit import emit_audit_event

        _, _engine, factory = audit_app
        tid = uuid.uuid4()

        async with factory() as sess:
            entry = await emit_audit_event(
                session=sess,
                action="config.update",
                auth=ADMIN_CTX,
                target_type="config",
                target_id=str(tid),
            )
            await sess.commit()

        assert str(entry.target_id) == str(tid)


# ---------------------------------------------------------------------------
# Test: Retention cleanup
# ---------------------------------------------------------------------------


class TestRetentionCleanup:
    """Tests for ``run_retention_cleanup``."""

    async def test_cleanup_deletes_old_entries(self, audit_app):
        """Entries older than retention period are deleted."""
        from routerbot.auth.audit import run_retention_cleanup

        _, _engine, factory = audit_app
        now = datetime.now(tz=UTC)

        async with factory() as sess:
            # Create old entry (100 days ago)
            sess.add(
                AuditLog(
                    action="old.action",
                    actor_type="user",
                    target_type="key",
                    created_at=now - timedelta(days=100),
                )
            )
            # Create recent entry (10 days ago)
            sess.add(
                AuditLog(
                    action="recent.action",
                    actor_type="user",
                    target_type="key",
                    created_at=now - timedelta(days=10),
                )
            )
            await sess.commit()

        async with factory() as sess:
            deleted = await run_retention_cleanup(sess, retention_days=90)
            await sess.commit()

        assert deleted == 1

        # Verify only recent entry remains
        from routerbot.db.repositories.audit import AuditRepository

        async with factory() as sess:
            repo = AuditRepository(sess)
            remaining = await repo.list_all()
            assert len(remaining) == 1
            assert remaining[0].action == "recent.action"

    async def test_cleanup_with_nothing_to_delete(self, audit_app):
        """Returns 0 when no old entries exist."""
        from routerbot.auth.audit import run_retention_cleanup

        _, _engine, factory = audit_app

        async with factory() as sess:
            deleted = await run_retention_cleanup(sess, retention_days=90)
            await sess.commit()

        assert deleted == 0

    async def test_cleanup_custom_retention_days(self, audit_app):
        """Custom retention_days parameter is honoured."""
        from routerbot.auth.audit import run_retention_cleanup

        _, _engine, factory = audit_app
        now = datetime.now(tz=UTC)

        async with factory() as sess:
            # 5 days old
            sess.add(
                AuditLog(
                    action="five_days_old",
                    actor_type="user",
                    target_type="key",
                    created_at=now - timedelta(days=5),
                )
            )
            # 2 days old
            sess.add(
                AuditLog(
                    action="two_days_old",
                    actor_type="user",
                    target_type="key",
                    created_at=now - timedelta(days=2),
                )
            )
            await sess.commit()

        # Retention of 3 days should only delete the 5-day-old entry
        async with factory() as sess:
            deleted = await run_retention_cleanup(sess, retention_days=3)
            await sess.commit()

        assert deleted == 1
