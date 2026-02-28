"""Unit tests for the database layer: engine, models, session, repositories.

Uses aiosqlite in-memory database — no external services needed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from routerbot.db.engine import _mask_url, create_session_factory
from routerbot.db.engine import create_engine as rb_create_engine
from routerbot.db.models import (
    AuditLog,
    Base,
    GuardrailPolicy,
    ModelConfig,
    SpendLog,
    Team,
    User,
    UserTeam,
    VirtualKey,
)
from routerbot.db.repositories.audit import AuditRepository
from routerbot.db.repositories.keys import KeyRepository
from routerbot.db.repositories.spend import SpendRepository
from routerbot.db.repositories.teams import TeamRepository
from routerbot.db.repositories.users import UserRepository
from routerbot.db.session import configure_session_factory, get_session_factory

# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture()
async def engine():
    """In-memory SQLite async engine for testing."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture()
async def session(engine):
    """A fresh async session for each test."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


# ═══════════════════════════════════════════════════════════════════════════════
# Engine & session factory
# ═══════════════════════════════════════════════════════════════════════════════


class TestEngine:
    def test_create_engine_returns_engine(self) -> None:
        engine = rb_create_engine("sqlite+aiosqlite:///:memory:")
        assert engine is not None

    def test_create_session_factory_returns_callable(self) -> None:
        engine = rb_create_engine("sqlite+aiosqlite:///:memory:")
        factory = create_session_factory(engine)
        assert callable(factory)

    def test_mask_url_with_credentials(self) -> None:
        assert _mask_url("postgresql+asyncpg://user:pass@host/db") == "postgresql+asyncpg://***@host/db"

    def test_mask_url_without_credentials(self) -> None:
        assert _mask_url("sqlite+aiosqlite:///:memory:") == "sqlite+aiosqlite:///:memory:"


class TestSessionManagement:
    def test_get_session_factory_raises_without_config(self) -> None:
        # Reset module state
        import routerbot.db.session as sess_mod

        old = sess_mod._session_factory
        sess_mod._session_factory = None
        try:
            with pytest.raises(RuntimeError, match="not initialised"):
                get_session_factory()
        finally:
            sess_mod._session_factory = old

    def test_configure_session_factory(self) -> None:
        import routerbot.db.session as sess_mod

        engine = rb_create_engine("sqlite+aiosqlite:///:memory:")
        factory = create_session_factory(engine)
        old = sess_mod._session_factory
        try:
            configure_session_factory(factory)
            assert get_session_factory() is factory
        finally:
            sess_mod._session_factory = old


# ═══════════════════════════════════════════════════════════════════════════════
# ORM model creation
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestModels:
    async def test_create_user(self, session: AsyncSession) -> None:
        user = User(email="test@example.com", role="admin")
        session.add(user)
        await session.flush()
        assert user.id is not None
        assert user.email == "test@example.com"
        assert user.role == "admin"
        assert user.spend == 0.0
        assert user.is_active is True

    async def test_create_team(self, session: AsyncSession) -> None:
        team = Team(name="Engineering", budget_limit=1000.0)
        session.add(team)
        await session.flush()
        assert team.id is not None
        assert team.name == "Engineering"
        assert team.spend == 0.0

    async def test_create_virtual_key(self, session: AsyncSession) -> None:
        user = User(email="key@example.com")
        session.add(user)
        await session.flush()

        key = VirtualKey(
            key_hash="abc123hash",
            key_prefix="rb-abc",
            user_id=user.id,
            models=["gpt-4o"],
            max_budget=100.0,
        )
        session.add(key)
        await session.flush()
        assert key.id is not None
        assert key.key_hash == "abc123hash"
        assert key.is_active is True

    async def test_create_spend_log(self, session: AsyncSession) -> None:
        log = SpendLog(
            model="gpt-4o",
            provider="openai",
            request_id="req-123",
            tokens_prompt=100,
            tokens_completion=50,
            cost=0.005,
        )
        session.add(log)
        await session.flush()
        assert log.id is not None

    async def test_create_audit_log(self, session: AsyncSession) -> None:
        log = AuditLog(
            action="key.create",
            actor_type="user",
            target_type="virtual_key",
            target_id=uuid.uuid4(),
        )
        session.add(log)
        await session.flush()
        assert log.id is not None

    async def test_user_team_association(self, session: AsyncSession) -> None:
        user = User(email="member@example.com")
        team = Team(name="Data Science")
        session.add_all([user, team])
        await session.flush()

        membership = UserTeam(user_id=user.id, team_id=team.id, role="admin")
        session.add(membership)
        await session.flush()
        assert membership.user_id == user.id
        assert membership.team_id == team.id

    async def test_model_config(self, session: AsyncSession) -> None:
        mc = ModelConfig(
            model_name="gpt-4-turbo",
            provider="openai",
            settings={"temperature": 0.7},
        )
        session.add(mc)
        await session.flush()
        assert mc.id is not None

    async def test_guardrail_policy(self, session: AsyncSession) -> None:
        gp = GuardrailPolicy(
            name="no-pii",
            type="content_filter",
            config={"patterns": ["SSN"]},
            enabled=True,
        )
        session.add(gp)
        await session.flush()
        assert gp.id is not None


# ═══════════════════════════════════════════════════════════════════════════════
# UserRepository
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestUserRepository:
    async def test_create_and_get(self, session: AsyncSession) -> None:
        repo = UserRepository(session)
        user = await repo.create(email="repo@example.com", role="editor")
        assert user.id is not None
        fetched = await repo.get_by_id(user.id)
        assert fetched is not None
        assert fetched.email == "repo@example.com"

    async def test_get_by_email(self, session: AsyncSession) -> None:
        repo = UserRepository(session)
        await repo.create(email="lookup@example.com")
        user = await repo.get_by_email("lookup@example.com")
        assert user is not None
        assert user.email == "lookup@example.com"

    async def test_get_by_email_not_found(self, session: AsyncSession) -> None:
        repo = UserRepository(session)
        user = await repo.get_by_email("missing@example.com")
        assert user is None

    async def test_get_by_sso_id(self, session: AsyncSession) -> None:
        repo = UserRepository(session)
        await repo.create(email="sso@example.com", sso_provider_id="google-12345")
        user = await repo.get_by_sso_id("google-12345")
        assert user is not None
        assert user.email == "sso@example.com"

    async def test_list_all(self, session: AsyncSession) -> None:
        repo = UserRepository(session)
        await repo.create(email="a@ex.com")
        await repo.create(email="b@ex.com")
        users = await repo.list_all()
        assert len(users) == 2

    async def test_list_active(self, session: AsyncSession) -> None:
        repo = UserRepository(session)
        u1 = await repo.create(email="active@ex.com")
        u2 = await repo.create(email="inactive@ex.com")
        await repo.deactivate(u2)
        active = await repo.list_active()
        assert len(active) == 1
        assert active[0].id == u1.id

    async def test_update(self, session: AsyncSession) -> None:
        repo = UserRepository(session)
        user = await repo.create(email="update@ex.com", role="viewer")
        await repo.update(user, role="admin")
        assert user.role == "admin"

    async def test_increment_spend(self, session: AsyncSession) -> None:
        repo = UserRepository(session)
        user = await repo.create(email="spend@ex.com")
        await repo.increment_spend(user, 5.50)
        assert user.spend == pytest.approx(5.50)
        await repo.increment_spend(user, 2.25)
        assert user.spend == pytest.approx(7.75)

    async def test_delete(self, session: AsyncSession) -> None:
        repo = UserRepository(session)
        user = await repo.create(email="delete@ex.com")
        uid = user.id
        await repo.delete(user)
        fetched = await repo.get_by_id(uid)
        assert fetched is None


# ═══════════════════════════════════════════════════════════════════════════════
# KeyRepository
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestKeyRepository:
    async def test_create_and_get_by_hash(self, session: AsyncSession) -> None:
        repo = KeyRepository(session)
        key = await repo.create(key_hash="hash123", key_prefix="rb-abc")
        found = await repo.get_by_hash("hash123")
        assert found is not None
        assert found.id == key.id

    async def test_get_by_hash_not_found(self, session: AsyncSession) -> None:
        repo = KeyRepository(session)
        assert await repo.get_by_hash("nonexistent") is None

    async def test_list_by_user(self, session: AsyncSession) -> None:
        user = User(email="keyuser@ex.com")
        session.add(user)
        await session.flush()

        repo = KeyRepository(session)
        await repo.create(key_hash="h1", key_prefix="rb-1", user_id=user.id)
        await repo.create(key_hash="h2", key_prefix="rb-2", user_id=user.id)

        keys = await repo.list_by_user(user.id)
        assert len(keys) == 2

    async def test_list_by_team(self, session: AsyncSession) -> None:
        team = Team(name="TeamKeyTest")
        session.add(team)
        await session.flush()

        repo = KeyRepository(session)
        await repo.create(key_hash="ht1", key_prefix="rb-t1", team_id=team.id)

        keys = await repo.list_by_team(team.id)
        assert len(keys) == 1

    async def test_deactivate(self, session: AsyncSession) -> None:
        repo = KeyRepository(session)
        key = await repo.create(key_hash="deact", key_prefix="rb-d")
        assert key.is_active is True
        await repo.deactivate(key)
        assert key.is_active is False

    async def test_list_active(self, session: AsyncSession) -> None:
        repo = KeyRepository(session)
        k1 = await repo.create(key_hash="a1", key_prefix="rb-a")
        k2 = await repo.create(key_hash="a2", key_prefix="rb-b")
        await repo.deactivate(k2)
        active = await repo.list_active()
        assert len(active) == 1
        assert active[0].id == k1.id

    async def test_increment_spend(self, session: AsyncSession) -> None:
        repo = KeyRepository(session)
        key = await repo.create(key_hash="sp1", key_prefix="rb-s", max_budget=100.0)
        await repo.increment_spend(key, 10.0)
        assert key.spend == pytest.approx(10.0)


# ═══════════════════════════════════════════════════════════════════════════════
# TeamRepository
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestTeamRepository:
    async def test_create_and_get(self, session: AsyncSession) -> None:
        repo = TeamRepository(session)
        team = await repo.create(name="Backend", budget_limit=5000.0)
        fetched = await repo.get_by_id(team.id)
        assert fetched is not None
        assert fetched.name == "Backend"

    async def test_get_by_name(self, session: AsyncSession) -> None:
        repo = TeamRepository(session)
        await repo.create(name="Frontend")
        team = await repo.get_by_name("Frontend")
        assert team is not None

    async def test_add_member(self, session: AsyncSession) -> None:
        user = User(email="tm@ex.com")
        team = Team(name="MemberTest")
        session.add_all([user, team])
        await session.flush()

        repo = TeamRepository(session)
        membership = await repo.add_member(team.id, user.id, role="admin")
        assert membership.role == "admin"

    async def test_remove_member(self, session: AsyncSession) -> None:
        user = User(email="rm@ex.com")
        team = Team(name="RemoveTest")
        session.add_all([user, team])
        await session.flush()

        repo = TeamRepository(session)
        await repo.add_member(team.id, user.id)
        removed = await repo.remove_member(team.id, user.id)
        assert removed is True

    async def test_remove_nonexistent_member(self, session: AsyncSession) -> None:
        repo = TeamRepository(session)
        team = await repo.create(name="EmptyTeam")
        removed = await repo.remove_member(team.id, uuid.uuid4())
        assert removed is False

    async def test_list_members(self, session: AsyncSession) -> None:
        u1 = User(email="m1@ex.com")
        u2 = User(email="m2@ex.com")
        team = Team(name="ListMembers")
        session.add_all([u1, u2, team])
        await session.flush()

        repo = TeamRepository(session)
        await repo.add_member(team.id, u1.id)
        await repo.add_member(team.id, u2.id)
        members = await repo.list_members(team.id)
        assert len(members) == 2

    async def test_get_membership(self, session: AsyncSession) -> None:
        user = User(email="gm@ex.com")
        team = Team(name="GetMembership")
        session.add_all([user, team])
        await session.flush()

        repo = TeamRepository(session)
        await repo.add_member(team.id, user.id, role="member")
        ms = await repo.get_membership(team.id, user.id)
        assert ms is not None
        assert ms.role == "member"

    async def test_increment_spend(self, session: AsyncSession) -> None:
        repo = TeamRepository(session)
        team = await repo.create(name="SpendTeam")
        await repo.increment_spend(team, 100.0)
        assert team.spend == pytest.approx(100.0)


# ═══════════════════════════════════════════════════════════════════════════════
# SpendRepository
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestSpendRepository:
    async def _create_log(self, session: AsyncSession, **kwargs) -> SpendLog:
        defaults = {
            "model": "gpt-4o",
            "provider": "openai",
            "request_id": f"req-{uuid.uuid4().hex[:8]}",
            "tokens_prompt": 100,
            "tokens_completion": 50,
            "cost": 0.01,
        }
        defaults.update(kwargs)
        log = SpendLog(**defaults)
        session.add(log)
        await session.flush()
        return log

    async def test_create_spend_log(self, session: AsyncSession) -> None:
        repo = SpendRepository(session)
        log = await repo.create(
            model="gpt-4o",
            provider="openai",
            request_id="req-test",
            tokens_prompt=100,
            tokens_completion=50,
            cost=0.005,
        )
        assert log.id is not None

    async def test_list_by_key(self, session: AsyncSession) -> None:
        key = VirtualKey(key_hash="spkey", key_prefix="rb-k")
        session.add(key)
        await session.flush()

        await self._create_log(session, key_id=key.id)
        await self._create_log(session, key_id=key.id)

        repo = SpendRepository(session)
        logs = await repo.list_by_key(key.id)
        assert len(logs) == 2

    async def test_list_by_user(self, session: AsyncSession) -> None:
        user = User(email="spu@ex.com")
        session.add(user)
        await session.flush()

        await self._create_log(session, user_id=user.id)

        repo = SpendRepository(session)
        logs = await repo.list_by_user(user.id)
        assert len(logs) == 1

    async def test_total_cost_by_key(self, session: AsyncSession) -> None:
        key = VirtualKey(key_hash="costkey", key_prefix="rb-c")
        session.add(key)
        await session.flush()

        await self._create_log(session, key_id=key.id, cost=1.50)
        await self._create_log(session, key_id=key.id, cost=2.50)

        repo = SpendRepository(session)
        total = await repo.total_cost_by_key(key.id)
        assert total == pytest.approx(4.0)

    async def test_total_cost_by_user(self, session: AsyncSession) -> None:
        user = User(email="costuser@ex.com")
        session.add(user)
        await session.flush()

        await self._create_log(session, user_id=user.id, cost=3.0)

        repo = SpendRepository(session)
        total = await repo.total_cost_by_user(user.id)
        assert total == pytest.approx(3.0)

    async def test_total_cost_by_team(self, session: AsyncSession) -> None:
        team = Team(name="CostTeam")
        session.add(team)
        await session.flush()

        await self._create_log(session, team_id=team.id, cost=7.0)

        repo = SpendRepository(session)
        total = await repo.total_cost_by_team(team.id)
        assert total == pytest.approx(7.0)

    async def test_cost_by_model(self, session: AsyncSession) -> None:
        await self._create_log(session, model="gpt-4o", cost=2.0)
        await self._create_log(session, model="gpt-4o", cost=3.0)
        await self._create_log(session, model="claude-3", cost=1.0)

        repo = SpendRepository(session)
        by_model = await repo.cost_by_model()
        costs = dict(by_model)
        assert costs["gpt-4o"] == pytest.approx(5.0)
        assert costs["claude-3"] == pytest.approx(1.0)

    async def test_token_totals(self, session: AsyncSession) -> None:
        await self._create_log(session, tokens_prompt=100, tokens_completion=50)
        await self._create_log(session, tokens_prompt=200, tokens_completion=100)

        repo = SpendRepository(session)
        prompt, completion = await repo.token_totals()
        assert prompt == 300
        assert completion == 150


# ═══════════════════════════════════════════════════════════════════════════════
# AuditRepository
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.anyio
class TestAuditRepository:
    async def test_create_audit_log(self, session: AsyncSession) -> None:
        repo = AuditRepository(session)
        log = await repo.create(
            action="user.create",
            actor_type="admin",
            target_type="user",
            target_id=uuid.uuid4(),
        )
        assert log.id is not None

    async def test_list_by_actor(self, session: AsyncSession) -> None:
        actor_id = uuid.uuid4()
        repo = AuditRepository(session)
        await repo.create(action="key.create", actor_id=actor_id, actor_type="user", target_type="key")
        await repo.create(action="key.delete", actor_id=actor_id, actor_type="user", target_type="key")

        logs = await repo.list_by_actor(actor_id)
        assert len(logs) == 2

    async def test_list_by_action(self, session: AsyncSession) -> None:
        repo = AuditRepository(session)
        await repo.create(action="config.reload", actor_type="system", target_type="config")
        await repo.create(action="config.reload", actor_type="system", target_type="config")

        logs = await repo.list_by_action("config.reload")
        assert len(logs) == 2

    async def test_list_by_target(self, session: AsyncSession) -> None:
        tid = uuid.uuid4()
        repo = AuditRepository(session)
        await repo.create(action="team.update", actor_type="admin", target_type="team", target_id=tid)

        logs = await repo.list_by_target("team", tid)
        assert len(logs) == 1

    async def test_delete_older_than(self, session: AsyncSession) -> None:
        repo = AuditRepository(session)
        # Create directly with old timestamp
        old = AuditLog(
            action="old.action",
            actor_type="system",
            target_type="test",
            created_at=datetime.now(UTC) - timedelta(days=100),
        )
        session.add(old)
        await session.flush()

        await repo.create(action="new.action", actor_type="system", target_type="test")

        cutoff = datetime.now(UTC) - timedelta(days=90)
        deleted = await repo.delete_older_than(cutoff)
        assert deleted == 1

        remaining = await repo.list_all()
        assert len(remaining) == 1
        assert remaining[0].action == "new.action"
