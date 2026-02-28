"""Webhook-based custom authentication.

Delegates authentication decisions to an external HTTP endpoint.
The external service receives request metadata and returns an auth
decision with user identity and permissions.

Supports caching to avoid hitting the webhook on every request.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import httpx

from routerbot.auth.advanced.models import WebhookAuthConfig, WebhookAuthResult

logger = logging.getLogger(__name__)


class WebhookAuthenticator:
    """Authenticate requests via an external webhook.

    Parameters
    ----------
    config:
        Webhook URL, timeout, headers, and caching configuration.
    """

    def __init__(self, config: WebhookAuthConfig | None = None) -> None:
        self.config = config or WebhookAuthConfig()
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[str, tuple[WebhookAuthResult, float]] = {}

    async def setup(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            headers=self.config.headers,
        )

    async def teardown(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def authenticate(
        self,
        headers: dict[str, str],
        request_path: str = "",
        request_method: str = "",
        client_ip: str = "",
    ) -> WebhookAuthResult:
        """Authenticate a request by calling the external webhook.

        Parameters
        ----------
        headers:
            The incoming request headers.
        request_path:
            The request URL path.
        request_method:
            The HTTP method.
        client_ip:
            The client IP address.

        Returns
        -------
        WebhookAuthResult
            Authentication result from the webhook.
        """
        if not self.config.enabled or not self.config.url:
            return WebhookAuthResult(authenticated=False, error="Webhook auth not configured")

        # Build cache key from forwarded headers
        cache_key = self._build_cache_key(headers)

        # Check cache
        if self.config.cache_ttl_seconds > 0:
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached

        # Forward selected headers
        forwarded: dict[str, str] = {}
        for h in self.config.forward_headers:
            for k, v in headers.items():
                if k.lower() == h.lower():
                    forwarded[k] = v

        # Build payload
        payload: dict[str, Any] = {
            "headers": forwarded,
            "path": request_path,
            "method": request_method,
            "client_ip": client_ip,
        }

        try:
            if self._client is None:
                await self.setup()

            assert self._client is not None

            if self.config.method.upper() == "GET":
                resp = await self._client.get(self.config.url, params={"path": request_path})
            else:
                resp = await self._client.post(self.config.url, json=payload)

            if resp.status_code in self.config.success_status_codes:
                data = resp.json()
                result = WebhookAuthResult(
                    authenticated=True,
                    user_id=data.get("user_id", ""),
                    role=data.get("role", ""),
                    team_id=data.get("team_id", ""),
                    permissions=data.get("permissions", []),
                    metadata=data.get("metadata", {}),
                    cache_key=cache_key,
                )
            else:
                result = WebhookAuthResult(
                    authenticated=False,
                    error=f"Webhook returned status {resp.status_code}",
                    cache_key=cache_key,
                )
        except httpx.HTTPError as exc:
            logger.warning("Webhook auth failed: %s", exc)
            result = WebhookAuthResult(
                authenticated=False,
                error=str(exc),
            )

        # Cache successful results
        if result.authenticated and self.config.cache_ttl_seconds > 0:
            self._cache[cache_key] = (result, time.monotonic())

        return result

    def clear_cache(self) -> int:
        """Clear the auth cache, returning the number of entries cleared."""
        count = len(self._cache)
        self._cache.clear()
        return count

    def _build_cache_key(self, headers: dict[str, str]) -> str:
        """Build a cache key from forwarded headers."""
        parts: list[str] = []
        for h in sorted(self.config.forward_headers):
            for k, v in headers.items():
                if k.lower() == h.lower():
                    parts.append(f"{h}={v}")
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _get_cached(self, key: str) -> WebhookAuthResult | None:
        """Return a cached result if still valid."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        result, cached_at = entry
        if time.monotonic() - cached_at > self.config.cache_ttl_seconds:
            del self._cache[key]
            return None
        return result
