"""Tests for JWT authentication (Task 4.3).

Covers:
- Token verification (HS256, RS256-with-mock-JWKS)
- Claim extraction and mapping
- Expired / invalid tokens
- Token caching
- JWKS refresh logic
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from jose import jwt as jose_jwt

from routerbot.auth.jwt import (
    JWTAuthenticator,
    JWTAuthError,
    JWTClaims,
    JWTConfig,
)

# ---------------------------------------------------------------------------
# Test secrets and payloads
# ---------------------------------------------------------------------------

HS256_SECRET = "super-secret-test-key-for-hs256-testing"

_BASE_PAYLOAD: dict[str, Any] = {
    "sub": "user-123",
    "email": "user@example.com",
    "org_id": "team-456",
    "routerbot_role": "editor",
    "iss": "https://auth.example.com",
    "aud": "routerbot",
}


def _make_token(
    payload: dict[str, Any] | None = None,
    *,
    secret: str = HS256_SECRET,
    algorithm: str = "HS256",
    expire_in: int = 3600,
) -> str:
    """Helper to create a signed JWT token for testing."""
    import copy

    p = copy.deepcopy(payload or _BASE_PAYLOAD)
    p.setdefault("iat", int(time.time()))
    p.setdefault("exp", int(time.time()) + expire_in)
    return jose_jwt.encode(p, secret, algorithm=algorithm)


def _make_config(**overrides: Any) -> JWTConfig:
    """Build a JWTConfig with sensible test defaults."""
    defaults: dict[str, Any] = {
        "enabled": True,
        "secret": HS256_SECRET,
        "issuer": "https://auth.example.com",
        "audience": "routerbot",
        "algorithms": ["HS256"],
    }
    defaults.update(overrides)
    return JWTConfig(**defaults)


# ---------------------------------------------------------------------------
# Token verification — HS256
# ---------------------------------------------------------------------------


class TestHS256Verification:
    """Test JWT verification with HS256 symmetric key."""

    @pytest.mark.asyncio
    async def test_verify_valid_token(self):
        config = _make_config()
        authn = JWTAuthenticator(config)
        token = _make_token()

        claims = await authn.verify_token(token)

        assert claims.user_id == "user-123"
        assert claims.email == "user@example.com"
        assert claims.team_id == "team-456"
        assert claims.role == "editor"

    @pytest.mark.asyncio
    async def test_verify_expired_token(self):
        config = _make_config()
        authn = JWTAuthenticator(config)
        token = _make_token(expire_in=-100)  # Already expired

        with pytest.raises(JWTAuthError, match="expired"):
            await authn.verify_token(token)

    @pytest.mark.asyncio
    async def test_verify_wrong_secret(self):
        config = _make_config()
        authn = JWTAuthenticator(config)
        token = _make_token(secret="wrong-secret")

        with pytest.raises(JWTAuthError, match="verification failed"):
            await authn.verify_token(token)

    @pytest.mark.asyncio
    async def test_verify_invalid_issuer(self):
        config = _make_config(issuer="https://other-issuer.com")
        authn = JWTAuthenticator(config)
        token = _make_token()  # iss = https://auth.example.com

        with pytest.raises(JWTAuthError, match="claims"):
            await authn.verify_token(token)

    @pytest.mark.asyncio
    async def test_verify_invalid_audience(self):
        config = _make_config(audience="other-audience")
        authn = JWTAuthenticator(config)
        token = _make_token()  # aud = routerbot

        with pytest.raises(JWTAuthError, match="claims"):
            await authn.verify_token(token)

    @pytest.mark.asyncio
    async def test_verify_no_issuer_check(self):
        """When issuer is None, skip issuer validation."""
        config = _make_config(issuer=None)
        authn = JWTAuthenticator(config)
        token = _make_token()

        claims = await authn.verify_token(token)
        assert claims.user_id == "user-123"

    @pytest.mark.asyncio
    async def test_verify_no_audience_check(self):
        """When audience is None, skip audience validation."""
        config = _make_config(audience=None)
        authn = JWTAuthenticator(config)
        token = _make_token()

        claims = await authn.verify_token(token)
        assert claims.user_id == "user-123"

    @pytest.mark.asyncio
    async def test_verify_garbage_token(self):
        config = _make_config()
        authn = JWTAuthenticator(config)

        with pytest.raises(JWTAuthError, match="Invalid JWT header"):
            await authn.verify_token("not-a-jwt")

    @pytest.mark.asyncio
    async def test_verify_missing_sub(self):
        """Token without 'sub' claim should fail."""
        config = _make_config()
        authn = JWTAuthenticator(config)
        payload = {
            "email": "user@example.com",
            "iss": "https://auth.example.com",
            "aud": "routerbot",
        }
        token = _make_token(payload)

        with pytest.raises(JWTAuthError, match="missing required"):
            await authn.verify_token(token)


# ---------------------------------------------------------------------------
# Claim mapping
# ---------------------------------------------------------------------------


class TestClaimMapping:
    """Test custom claim mapping."""

    @pytest.mark.asyncio
    async def test_custom_claim_mapping(self):
        config = _make_config(
            claim_mapping={
                "user_id": "user_id",
                "email": "mail",
                "team_id": "tenant",
                "role": "rb_role",
            }
        )
        authn = JWTAuthenticator(config)
        payload = {
            "user_id": "custom-user",
            "mail": "custom@test.com",
            "tenant": "custom-team",
            "rb_role": "admin",
            "iss": "https://auth.example.com",
            "aud": "routerbot",
        }
        token = _make_token(payload)
        claims = await authn.verify_token(token)

        assert claims.user_id == "custom-user"
        assert claims.email == "custom@test.com"
        assert claims.team_id == "custom-team"
        assert claims.role == "admin"

    @pytest.mark.asyncio
    async def test_default_role(self):
        """When role claim is missing, default to 'api_user'."""
        config = _make_config()
        authn = JWTAuthenticator(config)
        payload = {
            "sub": "user-no-role",
            "iss": "https://auth.example.com",
            "aud": "routerbot",
        }
        token = _make_token(payload)
        claims = await authn.verify_token(token)
        assert claims.role == "api_user"

    @pytest.mark.asyncio
    async def test_raw_claims_preserved(self):
        """The full decoded payload should be in claims.raw."""
        config = _make_config()
        authn = JWTAuthenticator(config)
        token = _make_token()
        claims = await authn.verify_token(token)

        assert claims.raw["sub"] == "user-123"
        assert "iat" in claims.raw
        assert "exp" in claims.raw

    @pytest.mark.asyncio
    async def test_optional_claims_none(self):
        """Missing optional claims should be None."""
        config = _make_config()
        authn = JWTAuthenticator(config)
        payload = {
            "sub": "user-minimal",
            "iss": "https://auth.example.com",
            "aud": "routerbot",
        }
        token = _make_token(payload)
        claims = await authn.verify_token(token)

        assert claims.email is None
        assert claims.team_id is None


# ---------------------------------------------------------------------------
# Token caching
# ---------------------------------------------------------------------------


class TestTokenCaching:
    """Test token verification result caching."""

    @pytest.mark.asyncio
    async def test_cached_on_second_call(self):
        config = _make_config(cache_ttl=60)
        authn = JWTAuthenticator(config)
        token = _make_token()

        claims1 = await authn.verify_token(token)
        claims2 = await authn.verify_token(token)

        assert claims1.user_id == claims2.user_id
        # Should have one cached entry
        assert len(authn._token_cache) == 1

    @pytest.mark.asyncio
    async def test_cache_expiry(self):
        config = _make_config(cache_ttl=1)
        authn = JWTAuthenticator(config)
        token = _make_token()

        await authn.verify_token(token)
        assert len(authn._token_cache) == 1

        # Simulate cache expiry by manipulating the stored timestamp
        for k in authn._token_cache:
            claims, _ts = authn._token_cache[k]
            authn._token_cache[k] = (claims, time.monotonic() - 10)

        # Next call should re-verify
        result = authn._get_cached(token)
        assert result is None

    def test_clear_cache(self):
        config = _make_config()
        authn = JWTAuthenticator(config)
        # Manually insert a cache entry
        authn._token_cache["test"] = (JWTClaims(user_id="x"), time.monotonic() + 999)
        assert len(authn._token_cache) == 1

        authn.clear_cache()
        assert len(authn._token_cache) == 0


# ---------------------------------------------------------------------------
# JWKS management (mocked HTTP)
# ---------------------------------------------------------------------------

_MOCK_JWKS_RESPONSE = {
    "keys": [
        {
            "kid": "test-key-1",
            "kty": "RSA",
            "alg": "RS256",
            "n": "test-n-value",
            "e": "AQAB",
        },
        {
            "kid": "test-key-2",
            "kty": "RSA",
            "alg": "RS256",
            "n": "test-n-value-2",
            "e": "AQAB",
        },
    ]
}


class TestJWKS:
    """Test JWKS fetching and key resolution."""

    @pytest.mark.asyncio
    async def test_jwks_refresh(self):
        """Test that JWKS keys are fetched and cached."""
        config = _make_config(
            jwks_uri="https://auth.example.com/.well-known/jwks.json",
            algorithms=["RS256", "HS256"],
        )
        authn = JWTAuthenticator(config)

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _MOCK_JWKS_RESPONSE
        mock_resp.raise_for_status = Mock()

        with patch("routerbot.auth.jwt.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            await authn._refresh_jwks()

        assert len(authn._jwks_keys) == 2
        assert "test-key-1" in authn._jwks_keys
        assert "test-key-2" in authn._jwks_keys

    @pytest.mark.asyncio
    async def test_jwks_key_lookup_by_kid(self):
        """Test that _get_signing_key returns the correct key by kid."""
        config = _make_config(
            jwks_uri="https://auth.example.com/.well-known/jwks.json",
            algorithms=["RS256", "HS256"],
        )
        authn = JWTAuthenticator(config)
        # Pre-populate cache
        authn._jwks_keys = {
            "key-1": {"kid": "key-1", "kty": "RSA"},
            "key-2": {"kid": "key-2", "kty": "RSA"},
        }
        authn._jwks_last_refresh = time.monotonic()

        key = await authn._get_signing_key("RS256", "key-1")
        assert key["kid"] == "key-1"

    @pytest.mark.asyncio
    async def test_hs256_uses_secret(self):
        """HS256 should use the configured secret, not JWKS."""
        config = _make_config()
        authn = JWTAuthenticator(config)

        key = await authn._get_signing_key("HS256", None)
        assert key == HS256_SECRET

    @pytest.mark.asyncio
    async def test_hs256_no_secret_raises(self):
        config = _make_config(secret=None)
        authn = JWTAuthenticator(config)

        with pytest.raises(JWTAuthError, match="requires a configured secret"):
            await authn._get_signing_key("HS256", None)

    @pytest.mark.asyncio
    async def test_rs256_no_jwks_uri_uses_secret(self):
        """RS256 without JWKS URI falls back to secret."""
        config = _make_config(jwks_uri=None, algorithms=["RS256", "HS256"])
        authn = JWTAuthenticator(config)

        key = await authn._get_signing_key("RS256", None)
        assert key == HS256_SECRET

    @pytest.mark.asyncio
    async def test_rs256_no_jwks_uri_no_secret_raises(self):
        config = _make_config(secret=None, jwks_uri=None, algorithms=["RS256"])
        authn = JWTAuthenticator(config)

        with pytest.raises(JWTAuthError, match="requires a JWKS URI"):
            await authn._get_signing_key("RS256", None)

    @pytest.mark.asyncio
    async def test_unknown_kid_triggers_refresh(self):
        """When kid not found in cache, trigger JWKS refresh."""
        config = _make_config(
            jwks_uri="https://auth.example.com/.well-known/jwks.json",
            algorithms=["RS256", "HS256"],
        )
        authn = JWTAuthenticator(config)
        authn._jwks_keys = {}  # Empty cache

        mock_resp = Mock()
        mock_resp.json.return_value = {"keys": [{"kid": "new-key", "kty": "RSA", "n": "n", "e": "AQAB"}]}
        mock_resp.raise_for_status = Mock()

        with patch("routerbot.auth.jwt.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            key = await authn._get_signing_key("RS256", "new-key")

        assert key["kid"] == "new-key"

    @pytest.mark.asyncio
    async def test_force_refresh_resets_interval(self):
        config = _make_config(
            jwks_uri="https://auth.example.com/.well-known/jwks.json",
        )
        authn = JWTAuthenticator(config)
        authn._jwks_last_refresh = time.monotonic()  # Recently refreshed

        # Force refresh should reset the timer
        mock_resp = Mock()
        mock_resp.json.return_value = {"keys": []}
        mock_resp.raise_for_status = Mock()

        with patch("routerbot.auth.jwt.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            await authn.force_refresh_jwks()
            # Should have actually fetched since we reset the timer
            mock_client.get.assert_called_once()


# ---------------------------------------------------------------------------
# JWTClaims dataclass
# ---------------------------------------------------------------------------


class TestJWTClaims:
    """Test the JWTClaims data class."""

    def test_defaults(self):
        claims = JWTClaims(user_id="u1")
        assert claims.email is None
        assert claims.team_id is None
        assert claims.role == "api_user"
        assert claims.raw == {}

    def test_full_claims(self):
        claims = JWTClaims(
            user_id="u1",
            email="a@b.com",
            team_id="t1",
            role="admin",
            raw={"sub": "u1"},
        )
        assert claims.user_id == "u1"
        assert claims.email == "a@b.com"
        assert claims.team_id == "t1"
        assert claims.role == "admin"


class TestJWTAuthError:
    """Test the JWTAuthError exception."""

    def test_message(self):
        err = JWTAuthError("test error")
        assert err.message == "test error"
        assert str(err) == "test error"
