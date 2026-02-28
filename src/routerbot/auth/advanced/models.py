"""Pydantic models for the advanced auth module."""

from __future__ import annotations

from datetime import UTC, datetime  # noqa: TC003
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

UTC = UTC


# ---------------------------------------------------------------------------
# mTLS
# ---------------------------------------------------------------------------


class MTLSConfig(BaseModel):
    """Configuration for mutual TLS authentication."""

    enabled: bool = Field(default=False)
    ca_cert_path: str = Field(default="", description="Path to trusted CA certificate (PEM)")
    require_client_cert: bool = Field(default=True, description="Reject connections without a client cert")
    allowed_cn_patterns: list[str] = Field(
        default_factory=list,
        description="Allowed common name patterns (regex). Empty = allow all valid certs.",
    )
    allowed_sans: list[str] = Field(
        default_factory=list,
        description="Allowed Subject Alternative Names. Empty = allow all.",
    )
    cert_header: str = Field(
        default="X-Client-Cert",
        description="Header name where the reverse proxy forwards the client certificate",
    )


class MTLSIdentity(BaseModel):
    """Identity extracted from a client certificate."""

    common_name: str = ""
    subject: str = ""
    issuer: str = ""
    serial_number: str = ""
    san_dns: list[str] = Field(default_factory=list)
    san_emails: list[str] = Field(default_factory=list)
    not_before: datetime | None = None
    not_after: datetime | None = None
    fingerprint_sha256: str = ""
    verified: bool = False


# ---------------------------------------------------------------------------
# API Key Scoping
# ---------------------------------------------------------------------------


class KeyScope(BaseModel):
    """Scope restrictions for an API key."""

    allowed_endpoints: list[str] = Field(
        default_factory=list,
        description="URL path patterns this key can access (e.g. '/v1/chat/*'). Empty = all.",
    )
    allowed_models: list[str] = Field(
        default_factory=list,
        description="Model names this key can use (e.g. 'openai/gpt-4o'). Empty = all.",
    )
    allowed_methods: list[str] = Field(
        default_factory=list,
        description="HTTP methods allowed (e.g. 'POST'). Empty = all.",
    )
    max_requests_per_hour: int | None = Field(default=None, ge=1, description="Per-key rate limit")
    max_tokens_per_request: int | None = Field(default=None, ge=1, description="Max tokens per request")
    expires_at: datetime | None = Field(default=None, description="Key expiration timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")


class KeyScopeValidation(BaseModel):
    """Result of validating a request against key scopes."""

    allowed: bool = True
    reason: str = ""
    key_id: str = ""
    matched_scope: KeyScope | None = None


# ---------------------------------------------------------------------------
# Webhook Auth
# ---------------------------------------------------------------------------


class WebhookAuthConfig(BaseModel):
    """Configuration for webhook-based authentication."""

    enabled: bool = Field(default=False)
    url: str = Field(default="", description="Webhook endpoint URL")
    method: str = Field(default="POST", description="HTTP method for the webhook call")
    timeout_seconds: float = Field(default=5.0, gt=0, description="Webhook call timeout")
    headers: dict[str, str] = Field(default_factory=dict, description="Extra headers to send")
    cache_ttl_seconds: int = Field(default=300, ge=0, description="Cache successful auth results (0=no cache)")
    forward_headers: list[str] = Field(
        default_factory=lambda: ["Authorization", "X-API-Key"],
        description="Request headers to forward to the webhook",
    )
    success_status_codes: list[int] = Field(
        default_factory=lambda: [200],
        description="HTTP status codes that indicate successful auth",
    )


class WebhookAuthResult(BaseModel):
    """Result returned from the webhook auth endpoint."""

    authenticated: bool = False
    user_id: str = ""
    role: str = ""
    team_id: str = ""
    permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    cache_key: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Token Exchange
# ---------------------------------------------------------------------------


class TokenExchangeProvider(StrEnum):
    """Supported external identity providers for token exchange."""

    GOOGLE = "google"
    GITHUB = "github"
    AZURE_AD = "azure_ad"
    OKTA = "okta"
    AUTH0 = "auth0"
    CUSTOM = "custom"


class TokenExchangeConfig(BaseModel):
    """Configuration for token exchange."""

    enabled: bool = Field(default=False)
    providers: list[ExchangeProviderConfig] = Field(default_factory=list)
    default_role: str = Field(default="api_user", description="Default role for exchanged tokens")
    default_ttl_seconds: int = Field(default=3600, gt=0, description="Default RouterBot token TTL")


class ExchangeProviderConfig(BaseModel):
    """Configuration for a single external identity provider."""

    name: str = Field(..., description="Provider identifier")
    provider_type: TokenExchangeProvider = Field(default=TokenExchangeProvider.CUSTOM)
    issuer: str = Field(default="", description="Expected token issuer (iss claim)")
    audience: str = Field(default="", description="Expected token audience (aud claim)")
    jwks_url: str = Field(default="", description="JWKS endpoint for token verification")
    userinfo_url: str = Field(default="", description="UserInfo endpoint URL")
    client_id: str = Field(default="", description="OAuth2 client ID for verification")
    claim_mappings: dict[str, str] = Field(
        default_factory=lambda: {
            "user_id": "sub",
            "email": "email",
            "name": "name",
        },
        description="Map external claims to RouterBot fields",
    )
    allowed_domains: list[str] = Field(
        default_factory=list,
        description="Allowed email domains (empty = all)",
    )
    role_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Map external roles/groups to RouterBot roles",
    )


class TokenExchangeRequest(BaseModel):
    """A request to exchange an external token."""

    external_token: str = Field(..., description="The external provider token")
    provider: str = Field(..., description="Provider name from config")
    requested_scopes: list[str] = Field(default_factory=list, description="Optional scope restrictions")


class TokenExchangeResult(BaseModel):
    """Result of a token exchange."""

    success: bool = False
    routerbot_token: str = ""
    expires_in: int = 3600
    user_id: str = ""
    role: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Fine-grained Permissions
# ---------------------------------------------------------------------------


class PermissionSet(BaseModel):
    """A named set of fine-grained permissions."""

    name: str = Field(..., description="Permission set identifier")
    description: str = Field(default="")
    permissions: list[str] = Field(default_factory=list, description="List of permission strings")
    inherit_from: list[str] = Field(
        default_factory=list,
        description="Other permission set names to inherit from",
    )


class PermissionCheckResult(BaseModel):
    """Result of checking a permission."""

    allowed: bool = True
    permission: str = ""
    reason: str = ""
    checked_sets: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level advanced auth config
# ---------------------------------------------------------------------------


class AdvancedAuthConfig(BaseModel):
    """Top-level configuration for all advanced auth features."""

    mtls: MTLSConfig = Field(default_factory=MTLSConfig)
    webhook_auth: WebhookAuthConfig = Field(default_factory=WebhookAuthConfig)
    token_exchange: TokenExchangeConfig = Field(default_factory=TokenExchangeConfig)
    key_scopes: dict[str, KeyScope] = Field(
        default_factory=dict,
        description="Named key scope definitions keyed by scope name",
    )
    permission_sets: list[PermissionSet] = Field(
        default_factory=list,
        description="Custom permission set definitions",
    )
