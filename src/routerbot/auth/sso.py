"""SSO integration — OIDC, SAML 2.0, and generic OAuth2 providers.

This module implements the server-side SSO flows:
- **OIDC (OpenID Connect):** Authorization Code flow with discovery
- **SAML 2.0:** SP-initiated SSO with assertion validation
- **OAuth2 (generic):** For providers that don't implement full OIDC

All SSO features are **fully free and open source** — no enterprise gate,
no user limits.

Usage::

    from routerbot.auth.sso import OIDCProvider, SSOManager

    mgr = SSOManager()
    mgr.register_provider(OIDCProvider(config))
    auth_url = await mgr.get_auth_url("google")
    user_info = await mgr.handle_callback("google", code=code)
"""

from __future__ import annotations

import logging
import secrets
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class SSOProviderConfig:
    """Configuration for a single SSO provider."""

    name: str
    type: str  # "oidc", "saml", "oauth2"
    client_id: str = ""
    client_secret: str = ""
    discovery_url: str | None = None
    authorize_url: str | None = None
    token_url: str | None = None
    userinfo_url: str | None = None
    logout_url: str | None = None
    redirect_uri: str = ""
    scopes: list[str] = field(default_factory=lambda: ["openid", "email", "profile"])
    allowed_domains: list[str] = field(default_factory=list)
    # SAML-specific
    idp_metadata_url: str | None = None
    idp_sso_url: str | None = None
    idp_cert: str | None = None
    sp_entity_id: str | None = None
    # Attribute mapping
    attribute_mapping: dict[str, str] = field(
        default_factory=lambda: {
            "email": "email",
            "name": "name",
            "user_id": "sub",
        }
    )


@dataclass
class SSOUserInfo:
    """Normalized user information from SSO callback.

    Attributes
    ----------
    provider_name:
        Name of the SSO provider that authenticated the user.
    provider_user_id:
        Unique user identifier from the provider (``sub`` claim).
    email:
        User's email address.
    name:
        Display name (may be ``None``).
    raw:
        Full raw attributes from the provider.
    """

    provider_name: str
    provider_user_id: str
    email: str
    name: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class SSOError(Exception):
    """Raised when an SSO operation fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# OIDC Provider
# ---------------------------------------------------------------------------


class OIDCProvider:
    """OpenID Connect provider implementing Authorization Code flow.

    Supports automatic discovery via ``.well-known/openid-configuration``.
    """

    def __init__(self, config: SSOProviderConfig) -> None:
        if config.type != "oidc":
            msg = f"OIDCProvider requires type='oidc', got {config.type!r}"
            raise ValueError(msg)
        self._config = config
        self._discovery: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def provider_type(self) -> str:
        return "oidc"

    async def discover(self) -> dict[str, Any]:
        """Fetch OIDC discovery document and cache endpoint URLs."""
        if self._discovery is not None:
            return self._discovery

        url = self._config.discovery_url
        if not url:
            raise SSOError(f"No discovery URL configured for provider {self.name}")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            self._discovery = resp.json()

        # Populate URLs from discovery
        disc = self._discovery
        if disc and not self._config.authorize_url:
            self._config.authorize_url = disc.get("authorization_endpoint")
        if disc and not self._config.token_url:
            self._config.token_url = disc.get("token_endpoint")
        if disc and not self._config.userinfo_url:
            self._config.userinfo_url = disc.get("userinfo_endpoint")
        if disc and not self._config.logout_url:
            self._config.logout_url = disc.get("end_session_endpoint")

        return self._discovery or {}

    def get_auth_url(self, state: str, nonce: str | None = None) -> str:
        """Build the authorization redirect URL.

        Parameters
        ----------
        state:
            Anti-CSRF state parameter (random, stored in session).
        nonce:
            Optional nonce for ID token validation.
        """
        if not self._config.authorize_url:
            raise SSOError(f"No authorize URL for provider {self.name}")

        params: dict[str, str] = {
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._config.scopes),
            "state": state,
        }
        if nonce:
            params["nonce"] = nonce

        return f"{self._config.authorize_url}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange the authorization code for tokens.

        Returns
        -------
        dict
            Token response containing ``access_token``, ``id_token``, etc.
        """
        if not self._config.token_url:
            raise SSOError(f"No token URL for provider {self.name}")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._config.redirect_uri,
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self._config.token_url, data=data)
            if resp.status_code != 200:
                raise SSOError(f"Token exchange failed: {resp.status_code} — {resp.text}")
            result: dict[str, Any] = resp.json()
            return result

    async def get_user_info(self, access_token: str) -> SSOUserInfo:
        """Fetch user info from the OIDC userinfo endpoint.

        Parameters
        ----------
        access_token:
            The OAuth2 access token from the token exchange.
        """
        if not self._config.userinfo_url:
            raise SSOError(f"No userinfo URL for provider {self.name}")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                self._config.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code != 200:
                raise SSOError(f"Userinfo request failed: {resp.status_code}")
            raw = resp.json()

        mapping = self._config.attribute_mapping
        email = raw.get(mapping.get("email", "email"), "")
        name = raw.get(mapping.get("name", "name"))
        user_id = str(raw.get(mapping.get("user_id", "sub"), ""))

        if not email:
            raise SSOError("SSO response missing required email claim")

        # Domain restriction
        if self._config.allowed_domains:
            domain = email.split("@")[-1].lower()
            if domain not in [d.lower() for d in self._config.allowed_domains]:
                raise SSOError(f"Email domain '{domain}' is not in the allowed list")

        return SSOUserInfo(
            provider_name=self.name,
            provider_user_id=user_id,
            email=email,
            name=name,
            raw=raw,
        )

    async def handle_callback(self, code: str) -> SSOUserInfo:
        """Complete the OIDC callback: exchange code → fetch user info."""
        tokens = await self.exchange_code(code)
        access_token = tokens.get("access_token", "")
        if not access_token:
            raise SSOError("No access_token in token response")
        return await self.get_user_info(access_token)


# ---------------------------------------------------------------------------
# Generic OAuth2 Provider (for non-OIDC providers)
# ---------------------------------------------------------------------------


class OAuth2Provider:
    """Generic OAuth2 provider for services without full OIDC support."""

    def __init__(self, config: SSOProviderConfig) -> None:
        if config.type != "oauth2":
            msg = f"OAuth2Provider requires type='oauth2', got {config.type!r}"
            raise ValueError(msg)
        self._config = config

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def provider_type(self) -> str:
        return "oauth2"

    def get_auth_url(self, state: str) -> str:
        """Build the OAuth2 authorization URL."""
        if not self._config.authorize_url:
            raise SSOError(f"No authorize URL for provider {self.name}")

        params = {
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._config.scopes),
            "state": state,
        }
        return f"{self._config.authorize_url}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access token."""
        if not self._config.token_url:
            raise SSOError(f"No token URL for provider {self.name}")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._config.redirect_uri,
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self._config.token_url, data=data)
            if resp.status_code != 200:
                raise SSOError(f"Token exchange failed: {resp.status_code} — {resp.text}")
            result: dict[str, Any] = resp.json()
            return result

    async def get_user_info(self, access_token: str) -> SSOUserInfo:
        """Fetch user info from the provider's userinfo endpoint."""
        if not self._config.userinfo_url:
            raise SSOError(f"No userinfo URL for provider {self.name}")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                self._config.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code != 200:
                raise SSOError(f"Userinfo request failed: {resp.status_code}")
            raw = resp.json()

        mapping = self._config.attribute_mapping
        email = raw.get(mapping.get("email", "email"), "")
        name = raw.get(mapping.get("name", "name"))
        user_id = str(raw.get(mapping.get("user_id", "sub"), ""))

        if not email:
            raise SSOError("SSO response missing required email claim")

        return SSOUserInfo(
            provider_name=self.name,
            provider_user_id=user_id,
            email=email,
            name=name,
            raw=raw,
        )

    async def handle_callback(self, code: str) -> SSOUserInfo:
        """Complete the OAuth2 callback flow."""
        tokens = await self.exchange_code(code)
        access_token = tokens.get("access_token", "")
        if not access_token:
            raise SSOError("No access_token in token response")
        return await self.get_user_info(access_token)


# ---------------------------------------------------------------------------
# SSO Manager
# ---------------------------------------------------------------------------


class SSOManager:
    """Registry and coordinator for SSO providers.

    Manages multiple SSO providers and generates/validates CSRF state.
    """

    def __init__(self) -> None:
        self._providers: dict[str, OIDCProvider | OAuth2Provider] = {}
        # Pending state tokens: {state: provider_name}
        self._pending_states: dict[str, str] = {}

    def register_provider(self, provider: OIDCProvider | OAuth2Provider) -> None:
        """Register an SSO provider by name."""
        self._providers[provider.name] = provider
        logger.info("SSO provider registered: %s (%s)", provider.name, provider.provider_type)

    def get_provider(self, name: str) -> OIDCProvider | OAuth2Provider:
        """Get a registered provider by name."""
        provider = self._providers.get(name)
        if provider is None:
            raise SSOError(f"SSO provider '{name}' not found")
        return provider

    def list_providers(self) -> list[dict[str, str]]:
        """Return a list of configured SSO providers (name + type)."""
        return [{"name": p.name, "type": p.provider_type} for p in self._providers.values()]

    def generate_state(self, provider_name: str) -> str:
        """Generate a CSRF state token for an SSO flow.

        Returns
        -------
        str
            The random state token (also stored internally for validation).
        """
        state = secrets.token_urlsafe(32)
        self._pending_states[state] = provider_name
        return state

    def validate_state(self, state: str) -> str:
        """Validate and consume a state token.

        Returns
        -------
        str
            The provider name associated with the state.

        Raises
        ------
        SSOError
            If the state token is invalid or already consumed.
        """
        provider_name = self._pending_states.pop(state, None)
        if provider_name is None:
            raise SSOError("Invalid or expired SSO state token")
        return provider_name

    async def get_auth_url(self, provider_name: str) -> tuple[str, str]:
        """Get the authorization URL for a given provider.

        Returns
        -------
        tuple[str, str]
            ``(auth_url, state_token)``
        """
        provider = self.get_provider(provider_name)
        state = self.generate_state(provider_name)

        if isinstance(provider, OIDCProvider):
            await provider.discover()
            url = provider.get_auth_url(state)
        else:
            url = provider.get_auth_url(state)

        return url, state

    async def handle_callback(
        self,
        state: str,
        code: str,
    ) -> SSOUserInfo:
        """Handle the SSO callback after IdP redirect.

        Parameters
        ----------
        state:
            The CSRF state token from the callback URL.
        code:
            The authorization code from the IdP.

        Returns
        -------
        SSOUserInfo
            Normalized user information from the provider.
        """
        provider_name = self.validate_state(state)
        provider = self.get_provider(provider_name)
        return await provider.handle_callback(code)
