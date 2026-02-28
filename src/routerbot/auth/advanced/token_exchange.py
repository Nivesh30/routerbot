"""Token exchange - swap external identity provider tokens for RouterBot tokens.

Supports exchanging tokens from Google, GitHub, Azure AD, Okta, Auth0,
and custom OIDC providers for short-lived RouterBot JWT tokens.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import UTC
from typing import Any

import httpx

from routerbot.auth.advanced.models import (
    ExchangeProviderConfig,
    TokenExchangeConfig,
    TokenExchangeRequest,
    TokenExchangeResult,
)

UTC = UTC
logger = logging.getLogger(__name__)

# Well-known userinfo endpoints for standard providers
_WELL_KNOWN_USERINFO: dict[str, str] = {
    "google": "https://www.googleapis.com/oauth2/v3/userinfo",
    "github": "https://api.github.com/user",
    "azure_ad": "https://graph.microsoft.com/v1.0/me",
}


class TokenExchanger:
    """Exchange external identity tokens for RouterBot tokens.

    Parameters
    ----------
    config:
        Token exchange configuration with provider definitions.
    jwt_secret:
        Secret key used to sign the RouterBot JWT tokens.
    """

    def __init__(self, config: TokenExchangeConfig | None = None, jwt_secret: str = "") -> None:
        self.config = config or TokenExchangeConfig()
        self._jwt_secret = jwt_secret
        self._providers: dict[str, ExchangeProviderConfig] = {
            p.name: p for p in self.config.providers
        }
        self._client: httpx.AsyncClient | None = None

    async def setup(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(timeout=10.0)

    async def teardown(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def exchange(self, request: TokenExchangeRequest) -> TokenExchangeResult:
        """Exchange an external token for a RouterBot token.

        Parameters
        ----------
        request:
            The exchange request with external token and provider name.

        Returns
        -------
        TokenExchangeResult
            Success with a new RouterBot token, or failure with error.
        """
        if not self.config.enabled:
            return TokenExchangeResult(success=False, error="Token exchange is not enabled")

        provider = self._providers.get(request.provider)
        if provider is None:
            return TokenExchangeResult(
                success=False,
                error=f"Unknown provider: {request.provider}",
            )

        # Validate the external token by calling the userinfo endpoint
        user_info = await self._fetch_user_info(provider, request.external_token)
        if user_info is None:
            return TokenExchangeResult(
                success=False,
                error="Failed to validate external token",
            )

        # Extract user identity from claims
        user_id = user_info.get(provider.claim_mappings.get("user_id", "sub"), "")
        email = user_info.get(provider.claim_mappings.get("email", "email"), "")

        if not user_id:
            return TokenExchangeResult(
                success=False,
                error="Could not extract user_id from token claims",
            )

        # Check allowed domains
        if provider.allowed_domains and email:
            domain = email.split("@")[-1] if "@" in email else ""
            if domain not in provider.allowed_domains:
                return TokenExchangeResult(
                    success=False,
                    error=f"Email domain {domain!r} not allowed",
                )

        # Map role
        role = self.config.default_role
        external_roles = user_info.get("roles", [])
        if isinstance(external_roles, list):
            for ext_role in external_roles:
                if ext_role in provider.role_mapping:
                    role = provider.role_mapping[ext_role]
                    break

        # Generate a RouterBot token
        ttl = self.config.default_ttl_seconds
        token = self._generate_token(user_id, role, email, ttl)

        return TokenExchangeResult(
            success=True,
            routerbot_token=token,
            expires_in=ttl,
            user_id=user_id,
            role=role,
        )

    async def _fetch_user_info(
        self,
        provider: ExchangeProviderConfig,
        token: str,
    ) -> dict[str, Any] | None:
        """Fetch user info from the identity provider."""
        url = provider.userinfo_url
        if not url:
            url = _WELL_KNOWN_USERINFO.get(provider.provider_type.value, "")
        if not url:
            logger.warning("No userinfo URL for provider %s", provider.name)
            return None

        try:
            if self._client is None:
                await self.setup()

            assert self._client is not None

            resp = await self._client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )

            if resp.status_code == 200:
                return resp.json()

            logger.warning(
                "UserInfo request failed for %s: status=%d",
                provider.name,
                resp.status_code,
            )
        except httpx.HTTPError as exc:
            logger.warning("UserInfo request error for %s: %s", provider.name, exc)

        return None

    def _generate_token(self, user_id: str, role: str, email: str, ttl: int) -> str:
        """Generate a simple signed token.

        In production, this would use proper JWT signing (HS256/RS256).
        Here we use a hash-based approach for simplicity.
        """
        now = int(time.time())
        payload = f"{user_id}:{role}:{email}:{now}:{ttl}"
        signature = hashlib.sha256(f"{payload}:{self._jwt_secret}".encode()).hexdigest()[:32]
        return f"rb_{payload}_{signature}"

    def list_providers(self) -> list[str]:
        """Return names of all configured providers."""
        return list(self._providers.keys())

    def get_provider(self, name: str) -> ExchangeProviderConfig | None:
        """Return config for a specific provider."""
        return self._providers.get(name)
