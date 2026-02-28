"""Tests for SSO and session management (Task 4.4).

Covers:
- OIDC provider: discovery, auth URL, code exchange, user info, domain restriction
- OAuth2 provider: auth URL, code exchange, user info
- SSOManager: provider registration, state generation/validation, callback flow
- SessionManager: create, get, delete, renew, CSRF, expiry, cleanup
- InMemorySessionStore: set, get, delete, cleanup
- SSO routes: /sso/providers, /sso/login, /sso/callback, /sso/logout
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from routerbot.auth.session import (
    InMemorySessionStore,
    SessionConfig,
    SessionCookie,
    SessionDeleteCookie,
    SessionManager,
)
from routerbot.auth.sso import (
    OAuth2Provider,
    OIDCProvider,
    SSOError,
    SSOManager,
    SSOProviderConfig,
    SSOUserInfo,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _oidc_config(**overrides: Any) -> SSOProviderConfig:
    defaults: dict[str, Any] = {
        "name": "test-oidc",
        "type": "oidc",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "discovery_url": "https://auth.example.com/.well-known/openid-configuration",
        "redirect_uri": "http://localhost:4000/sso/callback",
    }
    defaults.update(overrides)
    return SSOProviderConfig(**defaults)


def _oauth2_config(**overrides: Any) -> SSOProviderConfig:
    defaults: dict[str, Any] = {
        "name": "test-oauth2",
        "type": "oauth2",
        "client_id": "oauth2-client-id",
        "client_secret": "oauth2-client-secret",
        "authorize_url": "https://oauth2.example.com/authorize",
        "token_url": "https://oauth2.example.com/token",
        "userinfo_url": "https://oauth2.example.com/userinfo",
        "redirect_uri": "http://localhost:4000/sso/callback",
    }
    defaults.update(overrides)
    return SSOProviderConfig(**defaults)


_DISCOVERY_RESPONSE = {
    "authorization_endpoint": "https://auth.example.com/authorize",
    "token_endpoint": "https://auth.example.com/token",
    "userinfo_endpoint": "https://auth.example.com/userinfo",
    "end_session_endpoint": "https://auth.example.com/logout",
}

_USERINFO_RESPONSE = {
    "sub": "user-001",
    "email": "alice@example.com",
    "name": "Alice Smith",
}


# ---------------------------------------------------------------------------
# OIDC Provider tests
# ---------------------------------------------------------------------------


class TestOIDCProvider:
    """Test OpenID Connect provider."""

    def test_wrong_type_raises(self):
        with pytest.raises(ValueError, match="type='oidc'"):
            OIDCProvider(SSOProviderConfig(name="x", type="oauth2"))

    @pytest.mark.asyncio
    async def test_discover(self):
        config = _oidc_config()
        provider = OIDCProvider(config)

        mock_resp = Mock()
        mock_resp.json.return_value = _DISCOVERY_RESPONSE
        mock_resp.raise_for_status = Mock()

        with patch("routerbot.auth.sso.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            disc = await provider.discover()

        assert disc["authorization_endpoint"] == "https://auth.example.com/authorize"
        assert config.authorize_url == "https://auth.example.com/authorize"
        assert config.token_url == "https://auth.example.com/token"

    @pytest.mark.asyncio
    async def test_discover_no_url_raises(self):
        config = _oidc_config(discovery_url=None)
        provider = OIDCProvider(config)

        with pytest.raises(SSOError, match="No discovery URL"):
            await provider.discover()

    def test_get_auth_url(self):
        config = _oidc_config(authorize_url="https://auth.example.com/authorize")
        provider = OIDCProvider(config)

        url = provider.get_auth_url("test-state", nonce="test-nonce")

        assert "client_id=test-client-id" in url
        assert "state=test-state" in url
        assert "nonce=test-nonce" in url
        assert "response_type=code" in url

    def test_get_auth_url_no_endpoint_raises(self):
        config = _oidc_config(authorize_url=None)
        provider = OIDCProvider(config)

        with pytest.raises(SSOError, match="No authorize URL"):
            provider.get_auth_url("state")

    @pytest.mark.asyncio
    async def test_exchange_code(self):
        config = _oidc_config(token_url="https://auth.example.com/token")
        provider = OIDCProvider(config)

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "test-access-token", "id_token": "test-id"}
        mock_resp.text = ""

        with patch("routerbot.auth.sso.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            tokens = await provider.exchange_code("auth-code-123")

        assert tokens["access_token"] == "test-access-token"

    @pytest.mark.asyncio
    async def test_exchange_code_no_url_raises(self):
        config = _oidc_config(token_url=None)
        provider = OIDCProvider(config)

        with pytest.raises(SSOError, match="No token URL"):
            await provider.exchange_code("code")

    @pytest.mark.asyncio
    async def test_get_user_info(self):
        config = _oidc_config(userinfo_url="https://auth.example.com/userinfo")
        provider = OIDCProvider(config)

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _USERINFO_RESPONSE

        with patch("routerbot.auth.sso.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            info = await provider.get_user_info("access-token")

        assert info.email == "alice@example.com"
        assert info.name == "Alice Smith"
        assert info.provider_user_id == "user-001"
        assert info.provider_name == "test-oidc"

    @pytest.mark.asyncio
    async def test_get_user_info_domain_restriction(self):
        config = _oidc_config(
            userinfo_url="https://auth.example.com/userinfo",
            allowed_domains=["allowed.com"],
        )
        provider = OIDCProvider(config)

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"sub": "u1", "email": "user@blocked.com", "name": "X"}

        with patch("routerbot.auth.sso.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            with pytest.raises(SSOError, match="not in the allowed list"):
                await provider.get_user_info("token")

    @pytest.mark.asyncio
    async def test_get_user_info_missing_email(self):
        config = _oidc_config(userinfo_url="https://auth.example.com/userinfo")
        provider = OIDCProvider(config)

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"sub": "u1"}

        with patch("routerbot.auth.sso.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            with pytest.raises(SSOError, match="missing required email"):
                await provider.get_user_info("token")

    @pytest.mark.asyncio
    async def test_handle_callback(self):
        config = _oidc_config(
            token_url="https://auth.example.com/token",
            userinfo_url="https://auth.example.com/userinfo",
        )
        provider = OIDCProvider(config)

        token_resp = Mock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"access_token": "at-123"}
        token_resp.text = ""

        userinfo_resp = Mock()
        userinfo_resp.status_code = 200
        userinfo_resp.json.return_value = _USERINFO_RESPONSE

        with patch("routerbot.auth.sso.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            # First call = token exchange (post), second = userinfo (get)
            mock_client.post = AsyncMock(return_value=token_resp)
            mock_client.get = AsyncMock(return_value=userinfo_resp)
            mock_client_cls.return_value = mock_client

            info = await provider.handle_callback("auth-code")

        assert info.email == "alice@example.com"


# ---------------------------------------------------------------------------
# OAuth2 Provider tests
# ---------------------------------------------------------------------------


class TestOAuth2Provider:
    """Test generic OAuth2 provider."""

    def test_wrong_type_raises(self):
        with pytest.raises(ValueError, match="type='oauth2'"):
            OAuth2Provider(SSOProviderConfig(name="x", type="oidc"))

    def test_get_auth_url(self):
        config = _oauth2_config()
        provider = OAuth2Provider(config)

        url = provider.get_auth_url("test-state")

        assert "client_id=oauth2-client-id" in url
        assert "state=test-state" in url

    @pytest.mark.asyncio
    async def test_handle_callback(self):
        config = _oauth2_config()
        provider = OAuth2Provider(config)

        token_resp = Mock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"access_token": "oauth2-at"}
        token_resp.text = ""

        userinfo_resp = Mock()
        userinfo_resp.status_code = 200
        userinfo_resp.json.return_value = {"sub": "o-1", "email": "bob@ex.com", "name": "Bob"}

        with patch("routerbot.auth.sso.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=token_resp)
            mock_client.get = AsyncMock(return_value=userinfo_resp)
            mock_client_cls.return_value = mock_client

            info = await provider.handle_callback("code-123")

        assert info.email == "bob@ex.com"
        assert info.provider_name == "test-oauth2"


# ---------------------------------------------------------------------------
# SSO Manager tests
# ---------------------------------------------------------------------------


class TestSSOManager:
    """Test the SSOManager registry."""

    def test_register_and_list(self):
        mgr = SSOManager()
        p1 = OIDCProvider(_oidc_config(name="google"))
        p2 = OAuth2Provider(_oauth2_config(name="github"))
        mgr.register_provider(p1)
        mgr.register_provider(p2)

        providers = mgr.list_providers()
        names = [p["name"] for p in providers]
        assert "google" in names
        assert "github" in names

    def test_get_provider(self):
        mgr = SSOManager()
        mgr.register_provider(OIDCProvider(_oidc_config(name="okta")))
        p = mgr.get_provider("okta")
        assert p.name == "okta"

    def test_get_provider_not_found(self):
        mgr = SSOManager()
        with pytest.raises(SSOError, match="not found"):
            mgr.get_provider("nonexistent")

    def test_state_generation_and_validation(self):
        mgr = SSOManager()
        mgr.register_provider(OIDCProvider(_oidc_config()))

        state = mgr.generate_state("test-oidc")
        assert len(state) > 20

        # Validate should return provider name and consume the token
        name = mgr.validate_state(state)
        assert name == "test-oidc"

        # Second validation should fail
        with pytest.raises(SSOError, match="Invalid or expired"):
            mgr.validate_state(state)

    def test_invalid_state(self):
        mgr = SSOManager()
        with pytest.raises(SSOError, match="Invalid or expired"):
            mgr.validate_state("bad-state")

    @pytest.mark.asyncio
    async def test_get_auth_url(self):
        mgr = SSOManager()
        config = _oidc_config(authorize_url="https://auth.example.com/authorize")
        provider = OIDCProvider(config)
        # Pre-populate discovery to avoid HTTP call
        provider._discovery = _DISCOVERY_RESPONSE
        mgr.register_provider(provider)

        url, state = await mgr.get_auth_url("test-oidc")
        assert "client_id=" in url
        assert len(state) > 20

    @pytest.mark.asyncio
    async def test_handle_callback(self):
        mgr = SSOManager()
        config = _oidc_config(
            token_url="https://auth.example.com/token",
            userinfo_url="https://auth.example.com/userinfo",
        )
        provider = OIDCProvider(config)
        mgr.register_provider(provider)

        state = mgr.generate_state("test-oidc")

        token_resp = Mock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"access_token": "at-cb"}
        token_resp.text = ""

        userinfo_resp = Mock()
        userinfo_resp.status_code = 200
        userinfo_resp.json.return_value = _USERINFO_RESPONSE

        with patch("routerbot.auth.sso.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=token_resp)
            mock_client.get = AsyncMock(return_value=userinfo_resp)
            mock_client_cls.return_value = mock_client

            info = await mgr.handle_callback(state=state, code="code-abc")

        assert info.email == "alice@example.com"


# ---------------------------------------------------------------------------
# Session Manager tests
# ---------------------------------------------------------------------------


class TestInMemorySessionStore:
    """Test the in-memory session store."""

    def test_set_and_get(self):
        store = InMemorySessionStore()
        store.set("s1", {"user": "alice"}, ttl=60)
        assert store.get("s1") == {"user": "alice"}

    def test_get_nonexistent(self):
        store = InMemorySessionStore()
        assert store.get("nope") is None

    def test_expiry(self):
        store = InMemorySessionStore()
        store.set("s1", {"user": "alice"}, ttl=60)
        # Manually expire
        store._sessions["s1"] = ({"user": "alice"}, time.monotonic() - 1)
        assert store.get("s1") is None

    def test_delete(self):
        store = InMemorySessionStore()
        store.set("s1", {"user": "alice"}, ttl=60)
        assert store.delete("s1") is True
        assert store.delete("s1") is False
        assert store.get("s1") is None

    def test_cleanup_expired(self):
        store = InMemorySessionStore()
        store.set("s1", {}, ttl=60)
        store.set("s2", {}, ttl=60)
        # Expire s2
        store._sessions["s2"] = ({}, time.monotonic() - 1)

        removed = store.cleanup_expired()
        assert removed == 1
        assert store.count == 1

    def test_count(self):
        store = InMemorySessionStore()
        assert store.count == 0
        store.set("s1", {}, ttl=60)
        assert store.count == 1


class TestSessionManager:
    """Test the session manager."""

    def test_create_and_get(self):
        mgr = SessionManager(SessionConfig(secret_key="test-key"))
        session_id, cookie = mgr.create_session({"user": "alice"})

        assert len(session_id) > 20
        assert isinstance(cookie, SessionCookie)
        assert cookie.value == session_id
        assert cookie.httponly is True

        data = mgr.get_session(session_id)
        assert data is not None
        assert data["user"] == "alice"
        assert "_created_at" in data

    def test_get_nonexistent(self):
        mgr = SessionManager()
        assert mgr.get_session("nonexistent") is None

    def test_delete(self):
        mgr = SessionManager(SessionConfig(secret_key="test"))
        session_id, _ = mgr.create_session({"user": "alice"})

        delete_cookie = mgr.delete_session(session_id)
        assert isinstance(delete_cookie, SessionDeleteCookie)
        assert mgr.get_session(session_id) is None

    def test_renew(self):
        mgr = SessionManager(SessionConfig(secret_key="test"))
        session_id, _ = mgr.create_session({"user": "alice"})

        cookie = mgr.renew_session(session_id)
        assert cookie is not None
        assert cookie.value == session_id

    def test_renew_nonexistent(self):
        mgr = SessionManager()
        assert mgr.renew_session("nope") is None

    def test_csrf_token(self):
        mgr = SessionManager(SessionConfig(secret_key="test-key"))
        session_id, _ = mgr.create_session({})

        csrf = mgr.generate_csrf_token(session_id)
        assert len(csrf) == 64  # SHA-256 hex

        assert mgr.validate_csrf_token(session_id, csrf) is True
        assert mgr.validate_csrf_token(session_id, "wrong") is False

    def test_cleanup(self):
        mgr = SessionManager(SessionConfig(secret_key="test"))
        sid1, _ = mgr.create_session({"a": 1})
        sid2, _ = mgr.create_session({"b": 2})

        # Expire sid1
        mgr._store._sessions[sid1] = ({"a": 1}, time.monotonic() - 1)

        removed = mgr.cleanup()
        assert removed == 1
        assert mgr.get_session(sid1) is None
        assert mgr.get_session(sid2) is not None

    def test_cookie_as_dict(self):
        cookie = SessionCookie(
            key="sess",
            value="abc",
            max_age=3600,
            secure=True,
            httponly=True,
            samesite="strict",
            path="/app",
        )
        d = cookie.as_dict()
        assert d["key"] == "sess"
        assert d["value"] == "abc"
        assert d["max_age"] == 3600

    def test_delete_cookie_as_dict(self):
        dc = SessionDeleteCookie(key="sess", path="/")
        d = dc.as_dict()
        assert d["key"] == "sess"
        assert d["path"] == "/"


# ---------------------------------------------------------------------------
# SSO Route tests
# ---------------------------------------------------------------------------


@pytest.fixture
def sso_app():
    """Create a test app with SSO and session managers configured."""
    from routerbot.core.config_models import RouterBotConfig
    from routerbot.proxy.app import create_app

    config = RouterBotConfig()
    app = create_app(config=config)

    # Set up SSO manager with a mock OIDC provider
    sso_mgr = SSOManager()
    oidc_config = _oidc_config(
        authorize_url="https://auth.example.com/authorize",
        token_url="https://auth.example.com/token",
        userinfo_url="https://auth.example.com/userinfo",
    )
    provider = OIDCProvider(oidc_config)
    provider._discovery = _DISCOVERY_RESPONSE
    sso_mgr.register_provider(provider)

    session_mgr = SessionManager(SessionConfig(secret_key="test-secret"))

    app.state.routerbot.sso_manager = sso_mgr
    app.state.routerbot.session_manager = session_mgr

    return app


@pytest.fixture
async def sso_client(sso_app):
    transport = ASGITransport(app=sso_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


class TestSSORoutes:
    """Test SSO HTTP endpoints."""

    @pytest.mark.asyncio
    async def test_list_providers(self, sso_client):
        resp = await sso_client.get("/sso/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["providers"]) == 1
        assert data["providers"][0]["name"] == "test-oidc"

    @pytest.mark.asyncio
    async def test_login_redirect(self, sso_client):
        resp = await sso_client.get(
            "/sso/login",
            params={"provider": "test-oidc"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "auth.example.com/authorize" in location

    @pytest.mark.asyncio
    async def test_login_unknown_provider(self, sso_client):
        resp = await sso_client.get(
            "/sso/login",
            params={"provider": "nonexistent"},
            follow_redirects=False,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_missing_params(self, sso_client):
        resp = await sso_client.get("/sso/callback")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_error_from_provider(self, sso_client):
        resp = await sso_client.get(
            "/sso/callback",
            params={"error": "access_denied"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_success(self, sso_client, sso_app):
        sso_mgr = sso_app.state.routerbot.sso_manager

        # Generate a valid state
        state = sso_mgr.generate_state("test-oidc")

        token_resp = Mock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"access_token": "at-route"}
        token_resp.text = ""

        userinfo_resp = Mock()
        userinfo_resp.status_code = 200
        userinfo_resp.json.return_value = _USERINFO_RESPONSE

        with patch("routerbot.auth.sso.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=token_resp)
            mock_client.get = AsyncMock(return_value=userinfo_resp)
            mock_client_cls.return_value = mock_client

            resp = await sso_client.get(
                "/sso/callback",
                params={"state": state, "code": "code-xyz"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "authenticated"
        assert data["email"] == "alice@example.com"
        # Should set session cookie
        assert "routerbot_session" in resp.headers.get("set-cookie", "")

    @pytest.mark.asyncio
    async def test_callback_invalid_state(self, sso_client):
        resp = await sso_client.get(
            "/sso/callback",
            params={"state": "invalid-state", "code": "code"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_no_session(self, sso_client):
        resp = await sso_client.post("/sso/logout")
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_session"

    @pytest.mark.asyncio
    async def test_logout_with_session(self, sso_client, sso_app):
        session_mgr = sso_app.state.routerbot.session_manager
        session_id, _cookie = session_mgr.create_session({"user": "test"})

        resp = await sso_client.post(
            "/sso/logout",
            cookies={"routerbot_session": session_id},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "logged_out"
        assert session_mgr.get_session(session_id) is None


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestSSODataClasses:
    """Test SSO data classes."""

    def test_sso_user_info(self):
        info = SSOUserInfo(
            provider_name="google",
            provider_user_id="123",
            email="test@test.com",
            name="Test",
            raw={"sub": "123"},
        )
        assert info.provider_name == "google"
        assert info.email == "test@test.com"

    def test_sso_error(self):
        err = SSOError("test error")
        assert err.message == "test error"
        assert str(err) == "test error"

    def test_sso_provider_config_defaults(self):
        config = SSOProviderConfig(name="test", type="oidc")
        assert config.scopes == ["openid", "email", "profile"]
        assert config.allowed_domains == []
