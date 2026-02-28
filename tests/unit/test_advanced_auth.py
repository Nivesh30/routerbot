"""Tests for the advanced auth module (Task 8F.2).

Covers: mTLS authentication, API key scoping, webhook auth,
token exchange, and fine-grained permissions.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from routerbot.auth.advanced.key_scoping import KeyScopeValidator
from routerbot.auth.advanced.models import (
    AdvancedAuthConfig,
    ExchangeProviderConfig,
    KeyScope,
    KeyScopeValidation,
    MTLSConfig,
    MTLSIdentity,
    PermissionCheckResult,
    PermissionSet,
    TokenExchangeConfig,
    TokenExchangeProvider,
    TokenExchangeRequest,
    TokenExchangeResult,
    WebhookAuthConfig,
    WebhookAuthResult,
)
from routerbot.auth.advanced.mtls import (
    MTLSAuthenticator,
    MTLSAuthError,
    _parse_datetime,
    _split_cert_fields,
)
from routerbot.auth.advanced.permissions import PermissionManager
from routerbot.auth.advanced.token_exchange import TokenExchanger
from routerbot.auth.advanced.webhook_auth import WebhookAuthenticator

# ============================================================================
# Models
# ============================================================================


class TestModels:
    """Test Pydantic model construction and defaults."""

    def test_mtls_config_defaults(self) -> None:
        cfg = MTLSConfig()
        assert cfg.enabled is False
        assert cfg.ca_cert_path == ""
        assert cfg.require_client_cert is True
        assert cfg.allowed_cn_patterns == []
        assert cfg.allowed_sans == []
        assert cfg.cert_header == "X-Client-Cert"

    def test_mtls_identity_defaults(self) -> None:
        ident = MTLSIdentity()
        assert ident.common_name == ""
        assert ident.verified is False
        assert ident.san_dns == []
        assert ident.san_emails == []

    def test_key_scope_defaults(self) -> None:
        scope = KeyScope()
        assert scope.allowed_endpoints == []
        assert scope.allowed_models == []
        assert scope.allowed_methods == []
        assert scope.max_requests_per_hour is None
        assert scope.max_tokens_per_request is None
        assert scope.expires_at is None

    def test_key_scope_validation_defaults(self) -> None:
        v = KeyScopeValidation()
        assert v.allowed is True
        assert v.key_id == ""

    def test_webhook_auth_config_defaults(self) -> None:
        cfg = WebhookAuthConfig()
        assert cfg.enabled is False
        assert cfg.method == "POST"
        assert cfg.timeout_seconds == 5.0
        assert cfg.cache_ttl_seconds == 300
        assert cfg.success_status_codes == [200]
        assert "Authorization" in cfg.forward_headers

    def test_webhook_auth_result_defaults(self) -> None:
        r = WebhookAuthResult()
        assert r.authenticated is False
        assert r.user_id == ""

    def test_token_exchange_provider_values(self) -> None:
        assert TokenExchangeProvider.GOOGLE == "google"
        assert TokenExchangeProvider.GITHUB == "github"
        assert TokenExchangeProvider.AZURE_AD == "azure_ad"
        assert TokenExchangeProvider.CUSTOM == "custom"

    def test_exchange_provider_config(self) -> None:
        cfg = ExchangeProviderConfig(name="test")
        assert cfg.provider_type == TokenExchangeProvider.CUSTOM
        assert "user_id" in cfg.claim_mappings

    def test_token_exchange_config_defaults(self) -> None:
        cfg = TokenExchangeConfig()
        assert cfg.enabled is False
        assert cfg.default_role == "api_user"
        assert cfg.default_ttl_seconds == 3600

    def test_token_exchange_request(self) -> None:
        req = TokenExchangeRequest(external_token="tok", provider="google")
        assert req.external_token == "tok"
        assert req.provider == "google"

    def test_token_exchange_result_defaults(self) -> None:
        r = TokenExchangeResult()
        assert r.success is False
        assert r.routerbot_token == ""

    def test_permission_set(self) -> None:
        ps = PermissionSet(name="admin", permissions=["llm:access", "models:create"])
        assert ps.name == "admin"
        assert len(ps.permissions) == 2
        assert ps.inherit_from == []

    def test_permission_check_result_defaults(self) -> None:
        r = PermissionCheckResult()
        assert r.allowed is True
        assert r.permission == ""

    def test_advanced_auth_config_full(self) -> None:
        cfg = AdvancedAuthConfig()
        assert isinstance(cfg.mtls, MTLSConfig)
        assert isinstance(cfg.webhook_auth, WebhookAuthConfig)
        assert isinstance(cfg.token_exchange, TokenExchangeConfig)
        assert cfg.key_scopes == {}
        assert cfg.permission_sets == []

    def test_advanced_auth_config_from_dict(self) -> None:
        cfg = AdvancedAuthConfig(
            mtls={"enabled": True, "ca_cert_path": "/etc/certs/ca.pem"},
            webhook_auth={"enabled": True, "url": "https://auth.example.com/check"},
            key_scopes={"limited": {"allowed_models": ["gpt-4o"]}},
        )
        assert cfg.mtls.enabled is True
        assert cfg.mtls.ca_cert_path == "/etc/certs/ca.pem"
        assert cfg.webhook_auth.url == "https://auth.example.com/check"
        assert "limited" in cfg.key_scopes
        assert cfg.key_scopes["limited"].allowed_models == ["gpt-4o"]


# ============================================================================
# mTLS Authenticator
# ============================================================================


class TestMTLSAuthenticator:
    """Test the mTLS authentication flow."""

    def test_authenticate_no_cert_required(self) -> None:
        """Missing cert when required raises error."""
        auth = MTLSAuthenticator(MTLSConfig(require_client_cert=True))
        with pytest.raises(MTLSAuthError, match="Client certificate required"):
            auth.authenticate({})

    def test_authenticate_no_cert_optional(self) -> None:
        """Missing cert when optional returns unverified identity."""
        auth = MTLSAuthenticator(MTLSConfig(require_client_cert=False))
        identity = auth.authenticate({})
        assert identity.verified is False

    def test_authenticate_valid_cert(self) -> None:
        """Valid cert header returns verified identity."""
        auth = MTLSAuthenticator(MTLSConfig(require_client_cert=True))
        headers = {
            "X-Client-Cert": "CN=test-service;Subject=CN=test-service,O=TestOrg;Serial=12345",
        }
        identity = auth.authenticate(headers)
        assert identity.verified is True
        assert identity.common_name == "test-service"
        assert identity.serial_number == "12345"

    def test_authenticate_cn_pattern_match(self) -> None:
        """CN matching allowed patterns passes."""
        auth = MTLSAuthenticator(
            MTLSConfig(allowed_cn_patterns=["^service-.*$"])
        )
        headers = {
            "X-Client-Cert": "CN=service-alpha;Serial=100",
        }
        identity = auth.authenticate(headers)
        assert identity.verified is True
        assert identity.common_name == "service-alpha"

    def test_authenticate_cn_pattern_reject(self) -> None:
        """CN not matching any allowed pattern raises error."""
        auth = MTLSAuthenticator(
            MTLSConfig(allowed_cn_patterns=["^service-.*$"])
        )
        headers = {
            "X-Client-Cert": "CN=unknown-service;Serial=100",
        }
        with pytest.raises(MTLSAuthError, match="does not match"):
            auth.authenticate(headers)

    def test_authenticate_san_allowed(self) -> None:
        """SAN DNS in allowed list passes."""
        auth = MTLSAuthenticator(
            MTLSConfig(allowed_sans=["api.example.com"])
        )
        headers = {
            "X-Client-Cert": "CN=test;SAN_DNS=api.example.com",
        }
        identity = auth.authenticate(headers)
        assert identity.verified is True
        assert "api.example.com" in identity.san_dns

    def test_authenticate_san_rejected(self) -> None:
        """SAN DNS not in allowed list raises error."""
        auth = MTLSAuthenticator(
            MTLSConfig(allowed_sans=["api.example.com"])
        )
        headers = {
            "X-Client-Cert": "CN=test;SAN_DNS=evil.example.com",
        }
        with pytest.raises(MTLSAuthError, match="SAN not in allowed"):
            auth.authenticate(headers)

    def test_authenticate_expired_cert(self) -> None:
        """Expired cert raises error."""
        past = (datetime.now(tz=UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        auth = MTLSAuthenticator(MTLSConfig())
        headers = {
            "X-Client-Cert": f"CN=test;Not_After={past}",
        }
        with pytest.raises(MTLSAuthError, match="expired"):
            auth.authenticate(headers)

    def test_authenticate_not_yet_valid(self) -> None:
        """Cert not yet valid raises error."""
        future = (datetime.now(tz=UTC) + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
        auth = MTLSAuthenticator(MTLSConfig())
        headers = {
            "X-Client-Cert": f"CN=test;Not_Before={future}",
        }
        with pytest.raises(MTLSAuthError, match="not yet valid"):
            auth.authenticate(headers)

    def test_authenticate_case_insensitive_header(self) -> None:
        """Header lookup is case-insensitive."""
        auth = MTLSAuthenticator(MTLSConfig(cert_header="X-Client-Cert"))
        headers = {"x-client-cert": "CN=test"}
        identity = auth.authenticate(headers)
        assert identity.verified is True

    def test_fingerprint_computed(self) -> None:
        """Fingerprint is SHA256 of header value."""
        auth = MTLSAuthenticator(MTLSConfig())
        headers = {"X-Client-Cert": "CN=test;Serial=1"}
        identity = auth.authenticate(headers)
        expected = hashlib.sha256(b"CN=test;Serial=1").hexdigest()
        assert identity.fingerprint_sha256 == expected

    def test_subject_auto_populated(self) -> None:
        """Subject defaults to CN=<common_name> if not provided."""
        auth = MTLSAuthenticator(MTLSConfig())
        headers = {"X-Client-Cert": "CN=myservice"}
        identity = auth.authenticate(headers)
        assert identity.subject == "CN=myservice"

    def test_san_email_parsing(self) -> None:
        """SAN emails are parsed correctly."""
        auth = MTLSAuthenticator(MTLSConfig())
        headers = {
            "X-Client-Cert": "CN=test;SAN_Email=admin@example.com, ops@example.com",
        }
        identity = auth.authenticate(headers)
        assert "admin@example.com" in identity.san_emails
        assert "ops@example.com" in identity.san_emails

    def test_issuer_parsing(self) -> None:
        """Issuer is extracted from cert header."""
        auth = MTLSAuthenticator(MTLSConfig())
        headers = {
            "X-Client-Cert": "CN=test;Issuer=CN=RootCA,O=Acme",
        }
        identity = auth.authenticate(headers)
        assert identity.issuer == "CN=RootCA,O=Acme"


class TestCertHelpers:
    """Test mTLS helper functions."""

    def test_split_cert_fields(self) -> None:
        result = _split_cert_fields("CN=test;Serial=123;Issuer=CA")
        assert result["CN"] == "test"
        assert result["Serial"] == "123"
        assert result["Issuer"] == "CA"

    def test_split_cert_fields_empty(self) -> None:
        result = _split_cert_fields("")
        assert result == {}

    def test_split_cert_fields_no_equals(self) -> None:
        result = _split_cert_fields("nopair;alsonopair")
        assert result == {}

    def test_parse_datetime_iso(self) -> None:
        dt = _parse_datetime("2025-06-15T12:30:00Z")
        assert dt is not None
        assert dt.year == 2025
        assert dt.month == 6
        assert dt.tzinfo is not None

    def test_parse_datetime_space(self) -> None:
        dt = _parse_datetime("2025-06-15 12:30:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_parse_datetime_with_tz(self) -> None:
        dt = _parse_datetime("2025-06-15T12:30:00+00:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_parse_datetime_invalid(self) -> None:
        result = _parse_datetime("not-a-date")
        assert result is None


# ============================================================================
# Key Scoping
# ============================================================================


class TestKeyScopeValidator:
    """Test API key scope validation."""

    def test_register_and_get_scope(self) -> None:
        v = KeyScopeValidator()
        scope = KeyScope(allowed_models=["gpt-4o"])
        v.register_scope("limited", scope)
        assert v.get_scope("limited") is scope

    def test_remove_scope(self) -> None:
        v = KeyScopeValidator()
        v.register_scope("test", KeyScope())
        v.remove_scope("test")
        assert v.get_scope("test") is None

    def test_remove_scope_nonexistent(self) -> None:
        v = KeyScopeValidator()
        v.remove_scope("nope")  # no error

    def test_validate_unknown_scope(self) -> None:
        v = KeyScopeValidator()
        result = v.validate("unknown")
        assert result.allowed is False
        assert "Unknown scope" in result.reason

    def test_validate_all_allowed(self) -> None:
        """Empty restrictions allow everything."""
        v = KeyScopeValidator({"open": KeyScope()})
        result = v.validate("open", endpoint="/v1/chat", model="gpt-4o", method="POST")
        assert result.allowed is True

    def test_validate_endpoint_allowed(self) -> None:
        scope = KeyScope(allowed_endpoints=["/v1/chat/*"])
        v = KeyScopeValidator({"chat": scope})
        result = v.validate("chat", endpoint="/v1/chat/completions")
        assert result.allowed is True

    def test_validate_endpoint_denied(self) -> None:
        scope = KeyScope(allowed_endpoints=["/v1/chat/*"])
        v = KeyScopeValidator({"chat": scope})
        result = v.validate("chat", endpoint="/v1/embeddings")
        assert result.allowed is False
        assert "Endpoint" in result.reason

    def test_validate_model_allowed(self) -> None:
        scope = KeyScope(allowed_models=["openai/gpt-*"])
        v = KeyScopeValidator({"gpt": scope})
        result = v.validate("gpt", model="openai/gpt-4o")
        assert result.allowed is True

    def test_validate_model_denied(self) -> None:
        scope = KeyScope(allowed_models=["openai/gpt-*"])
        v = KeyScopeValidator({"gpt": scope})
        result = v.validate("gpt", model="anthropic/claude-3.5")
        assert result.allowed is False
        assert "Model" in result.reason

    def test_validate_method_allowed(self) -> None:
        scope = KeyScope(allowed_methods=["POST", "GET"])
        v = KeyScopeValidator({"rw": scope})
        result = v.validate("rw", method="post")
        assert result.allowed is True

    def test_validate_method_denied(self) -> None:
        scope = KeyScope(allowed_methods=["GET"])
        v = KeyScopeValidator({"readonly": scope})
        result = v.validate("readonly", method="DELETE")
        assert result.allowed is False
        assert "Method" in result.reason

    def test_validate_expired_scope(self) -> None:
        scope = KeyScope(expires_at=datetime.now(tz=UTC) - timedelta(hours=1))
        v = KeyScopeValidator({"expired": scope})
        result = v.validate("expired")
        assert result.allowed is False
        assert "expired" in result.reason.lower()

    def test_validate_not_expired(self) -> None:
        scope = KeyScope(expires_at=datetime.now(tz=UTC) + timedelta(hours=1))
        v = KeyScopeValidator({"valid": scope})
        result = v.validate("valid")
        assert result.allowed is True

    def test_validate_key_id_propagated(self) -> None:
        v = KeyScopeValidator({"open": KeyScope()})
        result = v.validate("open", key_id="key-123")
        assert result.key_id == "key-123"

    def test_validate_matched_scope_set(self) -> None:
        scope = KeyScope(allowed_models=["*"])
        v = KeyScopeValidator({"all": scope})
        result = v.validate("all", model="anything")
        assert result.matched_scope is scope

    def test_list_scopes(self) -> None:
        v = KeyScopeValidator({"a": KeyScope(), "b": KeyScope()})
        names = v.list_scopes()
        assert set(names) == {"a", "b"}

    def test_summary(self) -> None:
        v = KeyScopeValidator(
            {
                "a": KeyScope(allowed_endpoints=["/v1/*"]),
                "b": KeyScope(allowed_models=["gpt-4o"], expires_at=datetime.now(tz=UTC)),
            }
        )
        s = v.summary()
        assert s["total"] == 2
        assert s["with_endpoint_restrictions"] == 1
        assert s["with_model_restrictions"] == 1
        assert s["with_expiration"] == 1

    def test_validate_empty_endpoint_skips_check(self) -> None:
        """Empty endpoint string skips endpoint check even with restrictions."""
        scope = KeyScope(allowed_endpoints=["/v1/chat/*"])
        v = KeyScopeValidator({"chat": scope})
        result = v.validate("chat", endpoint="")
        assert result.allowed is True

    def test_validate_empty_model_skips_check(self) -> None:
        """Empty model string skips model check even with restrictions."""
        scope = KeyScope(allowed_models=["gpt-*"])
        v = KeyScopeValidator({"gpt": scope})
        result = v.validate("gpt", model="")
        assert result.allowed is True


# ============================================================================
# Webhook Authenticator
# ============================================================================


class TestWebhookAuthenticator:
    """Test webhook-based authentication."""

    async def test_disabled_returns_error(self) -> None:
        """Disabled config returns unauthenticated."""
        auth = WebhookAuthenticator(WebhookAuthConfig(enabled=False))
        result = await auth.authenticate({})
        assert result.authenticated is False
        assert "not configured" in result.error

    async def test_no_url_returns_error(self) -> None:
        auth = WebhookAuthenticator(WebhookAuthConfig(enabled=True, url=""))
        result = await auth.authenticate({})
        assert result.authenticated is False

    async def test_successful_auth(self) -> None:
        """Successful webhook POST returns authenticated result."""
        config = WebhookAuthConfig(
            enabled=True,
            url="https://auth.example.com/check",
        )
        auth = WebhookAuthenticator(config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "user_id": "user-42",
            "role": "admin",
            "team_id": "team-1",
            "permissions": ["llm:access"],
        }

        auth._client = AsyncMock(spec=httpx.AsyncClient)
        auth._client.post = AsyncMock(return_value=mock_resp)

        result = await auth.authenticate(
            headers={"Authorization": "Bearer tok"},
            request_path="/v1/chat",
            request_method="POST",
        )

        assert result.authenticated is True
        assert result.user_id == "user-42"
        assert result.role == "admin"
        assert result.team_id == "team-1"
        assert "llm:access" in result.permissions

    async def test_failed_auth_wrong_status(self) -> None:
        """Non-success status returns unauthenticated."""
        config = WebhookAuthConfig(enabled=True, url="https://auth.example.com/check")
        auth = WebhookAuthenticator(config)

        mock_resp = MagicMock()
        mock_resp.status_code = 403

        auth._client = AsyncMock(spec=httpx.AsyncClient)
        auth._client.post = AsyncMock(return_value=mock_resp)

        result = await auth.authenticate(headers={"Authorization": "Bearer bad"})
        assert result.authenticated is False
        assert "403" in result.error

    async def test_http_error_handled(self) -> None:
        """HTTP errors are caught gracefully."""
        config = WebhookAuthConfig(enabled=True, url="https://auth.example.com/check")
        auth = WebhookAuthenticator(config)

        auth._client = AsyncMock(spec=httpx.AsyncClient)
        auth._client.post = AsyncMock(side_effect=httpx.ConnectError("timeout"))

        result = await auth.authenticate(headers={"Authorization": "Bearer tok"})
        assert result.authenticated is False
        assert "timeout" in result.error

    async def test_cache_hit(self) -> None:
        """Cached result is returned without calling webhook."""
        config = WebhookAuthConfig(
            enabled=True,
            url="https://auth.example.com/check",
            cache_ttl_seconds=60,
        )
        auth = WebhookAuthenticator(config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"user_id": "user-1", "role": "admin"}

        auth._client = AsyncMock(spec=httpx.AsyncClient)
        auth._client.post = AsyncMock(return_value=mock_resp)

        # First call populates cache
        result1 = await auth.authenticate(headers={"Authorization": "Bearer tok1"})
        assert result1.authenticated is True

        # Second call should use cache (no new HTTP call)
        auth._client.post.reset_mock()
        result2 = await auth.authenticate(headers={"Authorization": "Bearer tok1"})
        assert result2.authenticated is True
        auth._client.post.assert_not_called()

    async def test_cache_expired(self) -> None:
        """Expired cache entry is not used."""
        config = WebhookAuthConfig(
            enabled=True,
            url="https://auth.example.com/check",
            cache_ttl_seconds=1,
        )
        auth = WebhookAuthenticator(config)

        # Manually inject an expired cache entry
        cache_key = auth._build_cache_key({"Authorization": "Bearer tok"})
        expired_result = WebhookAuthResult(authenticated=True, user_id="old")
        auth._cache[cache_key] = (expired_result, time.monotonic() - 10)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"user_id": "new", "role": "user"}

        auth._client = AsyncMock(spec=httpx.AsyncClient)
        auth._client.post = AsyncMock(return_value=mock_resp)

        result = await auth.authenticate(headers={"Authorization": "Bearer tok"})
        assert result.authenticated is True
        assert result.user_id == "new"
        auth._client.post.assert_called_once()

    async def test_clear_cache(self) -> None:
        """clear_cache removes all entries."""
        config = WebhookAuthConfig(enabled=True, url="https://x.com")
        auth = WebhookAuthenticator(config)
        auth._cache["k1"] = (WebhookAuthResult(), time.monotonic())
        auth._cache["k2"] = (WebhookAuthResult(), time.monotonic())
        count = auth.clear_cache()
        assert count == 2
        assert len(auth._cache) == 0

    async def test_get_method(self) -> None:
        """GET method uses get instead of post."""
        config = WebhookAuthConfig(
            enabled=True,
            url="https://auth.example.com/check",
            method="GET",
        )
        auth = WebhookAuthenticator(config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"user_id": "user-get"}

        auth._client = AsyncMock(spec=httpx.AsyncClient)
        auth._client.get = AsyncMock(return_value=mock_resp)

        result = await auth.authenticate(headers={}, request_path="/test")
        assert result.authenticated is True
        auth._client.get.assert_called_once()

    async def test_forward_headers(self) -> None:
        """Only configured forward_headers are sent."""
        config = WebhookAuthConfig(
            enabled=True,
            url="https://auth.example.com/check",
            forward_headers=["Authorization"],
        )
        auth = WebhookAuthenticator(config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"user_id": "u1"}

        auth._client = AsyncMock(spec=httpx.AsyncClient)
        auth._client.post = AsyncMock(return_value=mock_resp)

        await auth.authenticate(
            headers={"Authorization": "Bearer tok", "X-Custom": "secret"}
        )
        call_kwargs = auth._client.post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        assert "Authorization" in payload["headers"]
        assert "X-Custom" not in payload["headers"]

    async def test_setup_teardown(self) -> None:
        """setup/teardown lifecycle works."""
        auth = WebhookAuthenticator()
        assert auth._client is None
        await auth.setup()
        assert auth._client is not None
        await auth.teardown()
        assert auth._client is None

    async def test_cache_no_caching_when_ttl_zero(self) -> None:
        """cache_ttl_seconds=0 disables caching."""
        config = WebhookAuthConfig(
            enabled=True,
            url="https://auth.example.com/check",
            cache_ttl_seconds=0,
        )
        auth = WebhookAuthenticator(config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"user_id": "u"}

        auth._client = AsyncMock(spec=httpx.AsyncClient)
        auth._client.post = AsyncMock(return_value=mock_resp)

        await auth.authenticate(headers={"Authorization": "Bearer tok"})
        await auth.authenticate(headers={"Authorization": "Bearer tok"})
        assert auth._client.post.call_count == 2  # both calls hit webhook

    def test_build_cache_key_deterministic(self) -> None:
        """Same headers produce the same cache key."""
        config = WebhookAuthConfig(forward_headers=["Authorization"])
        auth = WebhookAuthenticator(config)
        key1 = auth._build_cache_key({"Authorization": "Bearer abc"})
        key2 = auth._build_cache_key({"Authorization": "Bearer abc"})
        assert key1 == key2

    def test_build_cache_key_different_tokens(self) -> None:
        """Different tokens produce different cache keys."""
        config = WebhookAuthConfig(forward_headers=["Authorization"])
        auth = WebhookAuthenticator(config)
        key1 = auth._build_cache_key({"Authorization": "Bearer abc"})
        key2 = auth._build_cache_key({"Authorization": "Bearer xyz"})
        assert key1 != key2


# ============================================================================
# Token Exchange
# ============================================================================


class TestTokenExchanger:
    """Test token exchange with external identity providers."""

    async def test_disabled_returns_error(self) -> None:
        """Disabled config returns failure."""
        exchanger = TokenExchanger(TokenExchangeConfig(enabled=False))
        req = TokenExchangeRequest(external_token="tok", provider="google")
        result = await exchanger.exchange(req)
        assert result.success is False
        assert "not enabled" in result.error

    async def test_unknown_provider(self) -> None:
        """Unknown provider returns failure."""
        exchanger = TokenExchanger(TokenExchangeConfig(enabled=True))
        req = TokenExchangeRequest(external_token="tok", provider="unknown")
        result = await exchanger.exchange(req)
        assert result.success is False
        assert "Unknown provider" in result.error

    async def test_successful_exchange(self) -> None:
        """Successful token exchange returns RouterBot token."""
        provider = ExchangeProviderConfig(
            name="google",
            provider_type=TokenExchangeProvider.GOOGLE,
        )
        config = TokenExchangeConfig(enabled=True, providers=[provider])
        exchanger = TokenExchanger(config, jwt_secret="test-secret")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "sub": "google-user-123",
            "email": "user@example.com",
            "name": "Test User",
        }

        exchanger._client = AsyncMock(spec=httpx.AsyncClient)
        exchanger._client.get = AsyncMock(return_value=mock_resp)

        req = TokenExchangeRequest(external_token="google-token", provider="google")
        result = await exchanger.exchange(req)

        assert result.success is True
        assert result.user_id == "google-user-123"
        assert result.role == "api_user"  # default
        assert result.routerbot_token.startswith("rb_")
        assert result.expires_in == 3600

    async def test_failed_userinfo_fetch(self) -> None:
        """Failed userinfo fetch returns failure."""
        provider = ExchangeProviderConfig(
            name="google",
            provider_type=TokenExchangeProvider.GOOGLE,
        )
        config = TokenExchangeConfig(enabled=True, providers=[provider])
        exchanger = TokenExchanger(config)

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        exchanger._client = AsyncMock(spec=httpx.AsyncClient)
        exchanger._client.get = AsyncMock(return_value=mock_resp)

        req = TokenExchangeRequest(external_token="bad-token", provider="google")
        result = await exchanger.exchange(req)
        assert result.success is False
        assert "Failed to validate" in result.error

    async def test_domain_filtering_allowed(self) -> None:
        """Email from allowed domain passes."""
        provider = ExchangeProviderConfig(
            name="corp",
            provider_type=TokenExchangeProvider.CUSTOM,
            userinfo_url="https://idp.example.com/userinfo",
            allowed_domains=["example.com"],
        )
        config = TokenExchangeConfig(enabled=True, providers=[provider])
        exchanger = TokenExchanger(config, jwt_secret="s")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "sub": "u1",
            "email": "user@example.com",
        }

        exchanger._client = AsyncMock(spec=httpx.AsyncClient)
        exchanger._client.get = AsyncMock(return_value=mock_resp)

        req = TokenExchangeRequest(external_token="tok", provider="corp")
        result = await exchanger.exchange(req)
        assert result.success is True

    async def test_domain_filtering_rejected(self) -> None:
        """Email from disallowed domain is rejected."""
        provider = ExchangeProviderConfig(
            name="corp",
            provider_type=TokenExchangeProvider.CUSTOM,
            userinfo_url="https://idp.example.com/userinfo",
            allowed_domains=["example.com"],
        )
        config = TokenExchangeConfig(enabled=True, providers=[provider])
        exchanger = TokenExchanger(config, jwt_secret="s")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "sub": "u1",
            "email": "user@evil.com",
        }

        exchanger._client = AsyncMock(spec=httpx.AsyncClient)
        exchanger._client.get = AsyncMock(return_value=mock_resp)

        req = TokenExchangeRequest(external_token="tok", provider="corp")
        result = await exchanger.exchange(req)
        assert result.success is False
        assert "not allowed" in result.error

    async def test_role_mapping(self) -> None:
        """External roles are mapped to RouterBot roles."""
        provider = ExchangeProviderConfig(
            name="corp",
            provider_type=TokenExchangeProvider.CUSTOM,
            userinfo_url="https://idp.example.com/userinfo",
            role_mapping={"external_admin": "admin", "external_user": "viewer"},
        )
        config = TokenExchangeConfig(
            enabled=True,
            providers=[provider],
            default_role="default_role",
        )
        exchanger = TokenExchanger(config, jwt_secret="s")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "sub": "u1",
            "email": "user@example.com",
            "roles": ["external_admin"],
        }

        exchanger._client = AsyncMock(spec=httpx.AsyncClient)
        exchanger._client.get = AsyncMock(return_value=mock_resp)

        req = TokenExchangeRequest(external_token="tok", provider="corp")
        result = await exchanger.exchange(req)
        assert result.success is True
        assert result.role == "admin"

    async def test_no_user_id_fails(self) -> None:
        """Missing user_id in claims fails."""
        provider = ExchangeProviderConfig(
            name="broken",
            provider_type=TokenExchangeProvider.CUSTOM,
            userinfo_url="https://idp.example.com/userinfo",
        )
        config = TokenExchangeConfig(enabled=True, providers=[provider])
        exchanger = TokenExchanger(config)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"email": "user@example.com"}  # no "sub"

        exchanger._client = AsyncMock(spec=httpx.AsyncClient)
        exchanger._client.get = AsyncMock(return_value=mock_resp)

        req = TokenExchangeRequest(external_token="tok", provider="broken")
        result = await exchanger.exchange(req)
        assert result.success is False
        assert "user_id" in result.error

    async def test_http_error_during_userinfo(self) -> None:
        """Network error during userinfo fetch handled gracefully."""
        provider = ExchangeProviderConfig(
            name="google",
            provider_type=TokenExchangeProvider.GOOGLE,
        )
        config = TokenExchangeConfig(enabled=True, providers=[provider])
        exchanger = TokenExchanger(config)

        exchanger._client = AsyncMock(spec=httpx.AsyncClient)
        exchanger._client.get = AsyncMock(side_effect=httpx.ConnectError("network"))

        req = TokenExchangeRequest(external_token="tok", provider="google")
        result = await exchanger.exchange(req)
        assert result.success is False

    def test_list_providers(self) -> None:
        provider = ExchangeProviderConfig(name="google", provider_type=TokenExchangeProvider.GOOGLE)
        config = TokenExchangeConfig(providers=[provider])
        exchanger = TokenExchanger(config)
        assert exchanger.list_providers() == ["google"]

    def test_get_provider(self) -> None:
        provider = ExchangeProviderConfig(name="github", provider_type=TokenExchangeProvider.GITHUB)
        config = TokenExchangeConfig(providers=[provider])
        exchanger = TokenExchanger(config)
        assert exchanger.get_provider("github") is provider
        assert exchanger.get_provider("unknown") is None

    async def test_setup_teardown(self) -> None:
        exchanger = TokenExchanger()
        assert exchanger._client is None
        await exchanger.setup()
        assert exchanger._client is not None
        await exchanger.teardown()
        assert exchanger._client is None

    def test_generate_token_format(self) -> None:
        """Generated token has expected format."""
        exchanger = TokenExchanger(jwt_secret="secret")
        token = exchanger._generate_token("uid", "admin", "e@x.com", 3600)
        assert token.startswith("rb_")
        assert "uid" in token
        assert "admin" in token

    async def test_github_provider_uses_well_known_url(self) -> None:
        """GitHub provider uses well-known userinfo URL."""
        provider = ExchangeProviderConfig(
            name="github",
            provider_type=TokenExchangeProvider.GITHUB,
        )
        config = TokenExchangeConfig(enabled=True, providers=[provider])
        exchanger = TokenExchanger(config, jwt_secret="s")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"sub": "gh-user", "email": "u@gh.com"}

        exchanger._client = AsyncMock(spec=httpx.AsyncClient)
        exchanger._client.get = AsyncMock(return_value=mock_resp)

        req = TokenExchangeRequest(external_token="ghp_xxx", provider="github")
        result = await exchanger.exchange(req)
        assert result.success is True

        call_args = exchanger._client.get.call_args
        assert "api.github.com" in call_args[0][0]

    async def test_custom_provider_no_userinfo_url(self) -> None:
        """Custom provider with no userinfo URL fails gracefully."""
        provider = ExchangeProviderConfig(
            name="nope",
            provider_type=TokenExchangeProvider.CUSTOM,
            # no userinfo_url
        )
        config = TokenExchangeConfig(enabled=True, providers=[provider])
        exchanger = TokenExchanger(config)

        exchanger._client = AsyncMock(spec=httpx.AsyncClient)

        req = TokenExchangeRequest(external_token="tok", provider="nope")
        result = await exchanger.exchange(req)
        assert result.success is False


# ============================================================================
# Permissions
# ============================================================================


class TestPermissionManager:
    """Test fine-grained permission system."""

    def test_register_and_get(self) -> None:
        pm = PermissionManager()
        ps = PermissionSet(name="admin", permissions=["llm:access", "models:create"])
        pm.register(ps)
        assert pm.get("admin") is ps

    def test_remove(self) -> None:
        pm = PermissionManager()
        pm.register(PermissionSet(name="x"))
        pm.remove("x")
        assert pm.get("x") is None

    def test_remove_nonexistent(self) -> None:
        pm = PermissionManager()
        pm.remove("nope")  # no error

    def test_resolve_direct_permissions(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="viewer", permissions=["llm:access", "models:read"]),
        ])
        perms = pm.resolve_permissions("viewer")
        assert perms == {"llm:access", "models:read"}

    def test_resolve_with_inheritance(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="viewer", permissions=["llm:access"]),
            PermissionSet(name="editor", permissions=["models:create"], inherit_from=["viewer"]),
        ])
        perms = pm.resolve_permissions("editor")
        assert "llm:access" in perms
        assert "models:create" in perms

    def test_resolve_deep_inheritance(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="base", permissions=["a"]),
            PermissionSet(name="mid", permissions=["b"], inherit_from=["base"]),
            PermissionSet(name="top", permissions=["c"], inherit_from=["mid"]),
        ])
        perms = pm.resolve_permissions("top")
        assert perms == {"a", "b", "c"}

    def test_resolve_circular_inheritance(self) -> None:
        """Circular inheritance is detected and doesn't loop."""
        pm = PermissionManager([
            PermissionSet(name="a", permissions=["x"], inherit_from=["b"]),
            PermissionSet(name="b", permissions=["y"], inherit_from=["a"]),
        ])
        perms = pm.resolve_permissions("a")
        assert "x" in perms
        assert "y" in perms

    def test_resolve_unknown_set(self) -> None:
        pm = PermissionManager()
        perms = pm.resolve_permissions("unknown")
        assert perms == set()

    def test_resolve_unknown_parent(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="child", permissions=["a"], inherit_from=["missing"]),
        ])
        perms = pm.resolve_permissions("child")
        assert perms == {"a"}

    def test_check_permission_allowed(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="admin", permissions=["models:create", "llm:access"]),
        ])
        result = pm.check_permission("models:create", ["admin"])
        assert result.allowed is True
        assert result.permission == "models:create"

    def test_check_permission_denied(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="viewer", permissions=["models:read"]),
        ])
        result = pm.check_permission("models:create", ["viewer"])
        assert result.allowed is False
        assert "not found" in result.reason

    def test_check_permission_multiple_sets(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="a", permissions=["x"]),
            PermissionSet(name="b", permissions=["y"]),
        ])
        result = pm.check_permission("y", ["a", "b"])
        assert result.allowed is True
        assert "b" in result.checked_sets

    def test_check_permission_via_inheritance(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="base", permissions=["perm1"]),
            PermissionSet(name="derived", permissions=["perm2"], inherit_from=["base"]),
        ])
        result = pm.check_permission("perm1", ["derived"])
        assert result.allowed is True

    def test_check_any_permission_one_match(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="user", permissions=["read"]),
        ])
        result = pm.check_any_permission(["write", "read"], ["user"])
        assert result.allowed is True

    def test_check_any_permission_none_match(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="user", permissions=["read"]),
        ])
        result = pm.check_any_permission(["write", "delete"], ["user"])
        assert result.allowed is False

    def test_check_all_permissions_all_match(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="admin", permissions=["read", "write", "delete"]),
        ])
        result = pm.check_all_permissions(["read", "write"], ["admin"])
        assert result.allowed is True

    def test_check_all_permissions_partial_match(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="editor", permissions=["read", "write"]),
        ])
        result = pm.check_all_permissions(["read", "delete"], ["editor"])
        assert result.allowed is False

    def test_list_sets(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="a"),
            PermissionSet(name="b"),
        ])
        assert set(pm.list_sets()) == {"a", "b"}

    def test_summary(self) -> None:
        pm = PermissionManager([
            PermissionSet(name="x", permissions=["a", "b"], inherit_from=["y"]),
            PermissionSet(name="y", permissions=["c"]),
        ])
        s = pm.summary()
        assert s["total_sets"] == 2
        assert s["sets"]["x"]["permissions"] == 2
        assert s["sets"]["x"]["inherits_from"] == ["y"]
        assert s["sets"]["y"]["permissions"] == 1

    def test_init_with_permission_sets(self) -> None:
        """Constructor accepts initial permission sets."""
        sets = [
            PermissionSet(name="a", permissions=["x"]),
            PermissionSet(name="b", permissions=["y"]),
        ]
        pm = PermissionManager(sets)
        assert pm.get("a").permissions == ["x"]
        assert pm.get("b").permissions == ["y"]

    def test_check_permission_empty_user_sets(self) -> None:
        """No user sets means permission denied."""
        pm = PermissionManager([PermissionSet(name="admin", permissions=["x"])])
        result = pm.check_permission("x", [])
        assert result.allowed is False

    def test_register_overwrites(self) -> None:
        """Re-registering a set overwrites it."""
        pm = PermissionManager()
        pm.register(PermissionSet(name="x", permissions=["a"]))
        pm.register(PermissionSet(name="x", permissions=["b"]))
        assert pm.get("x").permissions == ["b"]
