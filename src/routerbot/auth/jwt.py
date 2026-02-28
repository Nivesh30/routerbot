"""JWT authentication — verify tokens, extract claims, map to RouterBot permissions.

Supports RS256 and HS256 algorithms. Can optionally fetch public keys from a
JWKS endpoint for RS256 verification.

Usage::

    from routerbot.auth.jwt import JWTAuthenticator

    authn = JWTAuthenticator(
        secret_or_jwks_uri="https://auth.example.com/.well-known/jwks.json",
        issuer="https://auth.example.com",
        audience="routerbot",
    )
    claims = await authn.verify_token(token_string)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

DEFAULT_ALGORITHMS = ["RS256", "HS256"]
JWKS_REFRESH_INTERVAL = 3600  # seconds


@dataclass
class JWTConfig:
    """JWT authentication configuration."""

    enabled: bool = False
    secret: str | None = None
    jwks_uri: str | None = None
    issuer: str | None = None
    audience: str | None = None
    algorithms: list[str] = field(default_factory=lambda: list(DEFAULT_ALGORITHMS))
    claim_mapping: dict[str, str] = field(
        default_factory=lambda: {
            "user_id": "sub",
            "email": "email",
            "team_id": "org_id",
            "role": "routerbot_role",
        }
    )
    cache_ttl: int = 300  # seconds — how long to cache verified tokens


# ---------------------------------------------------------------------------
# Claim result
# ---------------------------------------------------------------------------


@dataclass
class JWTClaims:
    """Extracted and mapped claims from a verified JWT token.

    Attributes
    ----------
    user_id:
        Subject identifier (from ``sub`` claim by default).
    email:
        Email address (may be ``None``).
    team_id:
        Team / organization identifier (may be ``None``).
    role:
        RouterBot role (``admin``, ``editor``, ``viewer``, ``api_user``).
    raw:
        The full decoded JWT payload.
    """

    user_id: str
    email: str | None = None
    team_id: str | None = None
    role: str = "api_user"
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Authenticator
# ---------------------------------------------------------------------------


class JWTAuthenticator:
    """Stateful JWT authenticator with JWKS caching and token result caching.

    Parameters
    ----------
    config:
        A :class:`JWTConfig` with issuer, audience, and either ``secret``
        (for HS256) or ``jwks_uri`` (for RS256).
    """

    def __init__(self, config: JWTConfig) -> None:
        self._config = config
        # JWKS key cache: {kid: key_dict}
        self._jwks_keys: dict[str, dict[str, Any]] = {}
        self._jwks_last_refresh: float = 0.0
        # Token verification cache: {token_hash: (claims, expiry_ts)}
        self._token_cache: dict[str, tuple[JWTClaims, float]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def verify_token(self, token: str) -> JWTClaims:
        """Verify a JWT token and return mapped claims.

        Raises
        ------
        JWTAuthError
            If the token is invalid, expired, or claims don't match.
        """
        # Check cache first
        cached = self._get_cached(token)
        if cached is not None:
            return cached

        # Decode header to determine algorithm
        try:
            unverified_header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise JWTAuthError("Invalid JWT header") from exc

        algorithm = unverified_header.get("alg", "RS256")
        kid = unverified_header.get("kid")

        # Get the signing key
        key = await self._get_signing_key(algorithm, kid)

        # Verify and decode
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=self._config.algorithms,
                issuer=self._config.issuer,
                audience=self._config.audience,
                options={
                    "verify_iss": self._config.issuer is not None,
                    "verify_aud": self._config.audience is not None,
                },
            )
        except ExpiredSignatureError as exc:
            raise JWTAuthError("Token has expired") from exc
        except JWTClaimsError as exc:
            raise JWTAuthError(f"Invalid token claims: {exc}") from exc
        except JWTError as exc:
            raise JWTAuthError(f"Token verification failed: {exc}") from exc

        # Map claims
        claims = self._map_claims(payload)

        # Cache the result
        self._put_cached(token, claims)

        return claims

    # ------------------------------------------------------------------
    # JWKS management
    # ------------------------------------------------------------------

    async def _get_signing_key(self, algorithm: str, kid: str | None) -> Any:
        """Resolve the signing key.

        For HS256: returns the configured secret.
        For RS256: fetches JWKS and finds the key by ``kid``.
        """
        if algorithm == "HS256":
            if not self._config.secret:
                raise JWTAuthError("HS256 algorithm requires a configured secret")
            return self._config.secret

        # RS256 / RS384 / RS512 — need JWKS
        if not self._config.jwks_uri:
            if self._config.secret:
                return self._config.secret
            raise JWTAuthError("RS256 algorithm requires a JWKS URI or secret")

        # Try current cache
        if kid and kid in self._jwks_keys:
            return self._jwks_keys[kid]

        # Refresh JWKS if cache miss or stale
        await self._refresh_jwks()

        if kid and kid in self._jwks_keys:
            return self._jwks_keys[kid]

        # If no kid, return all keys (jose will try each)
        if not kid and self._jwks_keys:
            return {"keys": list(self._jwks_keys.values())}

        raise JWTAuthError(f"No matching key found for kid={kid!r}")

    async def _refresh_jwks(self) -> None:
        """Fetch JWKS from the configured URI and update the key cache."""
        now = time.monotonic()
        if now - self._jwks_last_refresh < JWKS_REFRESH_INTERVAL:
            return  # Recently refreshed

        if not self._config.jwks_uri:
            return

        logger.debug("Refreshing JWKS from %s", self._config.jwks_uri)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._config.jwks_uri)
                resp.raise_for_status()
                jwks = resp.json()

            keys: dict[str, dict[str, Any]] = {}
            for key_data in jwks.get("keys", []):
                k_id = key_data.get("kid")
                if k_id:
                    keys[k_id] = key_data
            self._jwks_keys = keys
            self._jwks_last_refresh = now
            logger.info("JWKS refreshed: %d key(s) loaded", len(keys))
        except Exception:
            logger.exception("Failed to refresh JWKS from %s", self._config.jwks_uri)
            # Keep stale keys rather than clearing

    async def force_refresh_jwks(self) -> None:
        """Force an immediate JWKS refresh (used on unknown kid)."""
        self._jwks_last_refresh = 0.0
        await self._refresh_jwks()

    # ------------------------------------------------------------------
    # Token cache
    # ------------------------------------------------------------------

    def _get_cached(self, token: str) -> JWTClaims | None:
        """Return cached claims if still valid."""
        import hashlib

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        entry = self._token_cache.get(token_hash)
        if entry is None:
            return None
        claims, expires_at = entry
        if time.monotonic() > expires_at:
            del self._token_cache[token_hash]
            return None
        return claims

    def _put_cached(self, token: str, claims: JWTClaims) -> None:
        """Store claims in the token cache."""
        import hashlib

        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = time.monotonic() + self._config.cache_ttl
        self._token_cache[token_hash] = (claims, expires_at)

    def clear_cache(self) -> None:
        """Clear the token verification cache."""
        self._token_cache.clear()

    # ------------------------------------------------------------------
    # Claim mapping
    # ------------------------------------------------------------------

    def _map_claims(self, payload: dict[str, Any]) -> JWTClaims:
        """Map JWT payload claims to a :class:`JWTClaims` using the configured mapping."""
        mapping = self._config.claim_mapping

        user_id = str(payload.get(mapping.get("user_id", "sub"), ""))
        if not user_id:
            raise JWTAuthError("Token is missing required 'sub' (user_id) claim")

        email = payload.get(mapping.get("email", "email"))
        team_id_raw = payload.get(mapping.get("team_id", "org_id"))
        role = payload.get(mapping.get("role", "routerbot_role"), "api_user")

        return JWTClaims(
            user_id=user_id,
            email=str(email) if email else None,
            team_id=str(team_id_raw) if team_id_raw else None,
            role=str(role),
            raw=payload,
        )


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class JWTAuthError(Exception):
    """Raised when JWT authentication fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
