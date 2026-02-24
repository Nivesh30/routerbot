"""Virtual API key generation, hashing, and validation.

Key format: ``rb-<random_hex>`` (prefix configurable).
Keys are stored as SHA-256 hashes — the plaintext key is returned
**only once** at generation time.

Usage::

    from routerbot.auth.api_key import generate_key, hash_key, validate_key

    plaintext, key_hash, prefix = generate_key()
    # store key_hash in DB, return plaintext to user

    # later, on an incoming request:
    result = await validate_key(bearer_token, session)
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from routerbot.db.models import VirtualKey

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PREFIX = "rb"
KEY_BYTE_LENGTH = 32  # 256-bit random → 64 hex chars
PREFIX_DISPLAY_LENGTH = 8  # e.g. "rb-a1b2c3d4..."


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


def generate_key(*, prefix: str = DEFAULT_PREFIX) -> tuple[str, str, str]:
    """Generate a new API key.

    Returns
    -------
    tuple[str, str, str]
        ``(plaintext_key, sha256_hash, display_prefix)``

        * ``plaintext_key`` — e.g. ``rb-a1b2c3d4…`` (shown once)
        * ``sha256_hash`` — hex-encoded SHA-256 of the plaintext key
        * ``display_prefix`` — first 8 chars after the dash for UI display
    """
    random_part = secrets.token_hex(KEY_BYTE_LENGTH)
    plaintext = f"{prefix}-{random_part}"
    key_hash = hash_key(plaintext)
    display_prefix = f"{prefix}-{random_part[:PREFIX_DISPLAY_LENGTH]}"
    return plaintext, key_hash, display_prefix


def hash_key(plaintext: str) -> str:
    """Return the SHA-256 hex digest of a plaintext API key."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Key validation
# ---------------------------------------------------------------------------


class KeyValidationResult:
    """Result of validating an API key against the database.

    Attributes
    ----------
    valid : bool
        Whether the key is valid and may proceed.
    key : VirtualKey | None
        The resolved database entity (``None`` when invalid).
    error : str | None
        Human-readable reason when ``valid`` is ``False``.
    error_code : str | None
        Machine-readable error code (maps to exception types).
    """

    __slots__ = ("error", "error_code", "key", "valid")

    def __init__(
        self,
        *,
        valid: bool,
        key: VirtualKey | None = None,
        error: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self.valid = valid
        self.key = key
        self.error = error
        self.error_code = error_code

    def __repr__(self) -> str:
        return f"KeyValidationResult(valid={self.valid}, error_code={self.error_code!r})"


async def validate_key(
    bearer_token: str,
    session: AsyncSession,
    *,
    check_budget: bool = True,
    check_expiry: bool = True,
    request_ip: str | None = None,
) -> KeyValidationResult:
    """Validate an incoming API key against the database.

    Performs the following checks (in order):

    1. Hash lookup — key must exist.
    2. Active — ``is_active`` must be ``True``.
    3. Expiry — ``expires_at`` must be in the future (if set).
    4. Budget — ``spend < max_budget`` (if ``max_budget`` is set).
    5. IP allowlist — if the key defines ``permissions.allowed_ips``,
       the request IP must be in the list.

    Parameters
    ----------
    bearer_token:
        The raw API key from the ``Authorization: Bearer <key>`` header.
    session:
        An active async session.
    check_budget:
        Whether to enforce budget limits. Defaults to ``True``.
    check_expiry:
        Whether to enforce expiry. Defaults to ``True``.
    request_ip:
        The client's IP address (for IP allowlist checking).

    Returns
    -------
    KeyValidationResult
    """
    from routerbot.db.repositories.keys import KeyRepository

    key_hash = hash_key(bearer_token)
    repo = KeyRepository(session)

    key = await repo.get_by_hash(key_hash)
    if key is None:
        return KeyValidationResult(valid=False, error="Invalid API key", error_code="invalid_api_key")

    # Active check
    if not key.is_active:
        return KeyValidationResult(
            valid=False,
            key=key,
            error="API key has been deactivated",
            error_code="key_deactivated",
        )

    # Expiry check
    if check_expiry and key.expires_at is not None:
        now = datetime.now(UTC)
        # Handle both timezone-aware and naive datetimes
        expires = key.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if now >= expires:
            return KeyValidationResult(
                valid=False,
                key=key,
                error="API key has expired",
                error_code="key_expired",
            )

    # Budget check
    if check_budget and key.max_budget is not None and key.spend >= key.max_budget:
        return KeyValidationResult(
            valid=False,
            key=key,
            error=f"Budget limit exceeded (${key.spend:.4f} / ${key.max_budget:.4f})",
            error_code="budget_exceeded",
        )

    # IP allowlist check
    if request_ip is not None:
        allowed_ips: list[str] = key.permissions.get("allowed_ips", [])
        if allowed_ips and request_ip not in allowed_ips:
            return KeyValidationResult(
                valid=False,
                key=key,
                error=f"Request IP {request_ip} is not in the key's allowlist",
                error_code="ip_not_allowed",
            )

    return KeyValidationResult(valid=True, key=key)


# ---------------------------------------------------------------------------
# Helpers for route layer
# ---------------------------------------------------------------------------


def _build_key_info(key: VirtualKey) -> dict[str, Any]:
    """Serialize a VirtualKey to a safe JSON-friendly dict (no secrets)."""
    return {
        "id": str(key.id),
        "key_prefix": key.key_prefix,
        "user_id": str(key.user_id) if key.user_id else None,
        "team_id": str(key.team_id) if key.team_id else None,
        "models": key.models,
        "max_budget": key.max_budget,
        "spend": key.spend,
        "rate_limit_rpm": key.rate_limit_rpm,
        "rate_limit_tpm": key.rate_limit_tpm,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "permissions": key.permissions,
        "metadata": key.metadata_,
        "is_active": key.is_active,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "updated_at": key.updated_at.isoformat() if key.updated_at else None,
    }
