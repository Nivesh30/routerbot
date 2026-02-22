"""Key hashing and generation utilities.

Provides secure hashing for API key storage, virtual key generation,
and key masking for safe display in logs and UI.
"""

from __future__ import annotations

import hashlib
import secrets
import string


def hash_key(key: str) -> str:
    """Hash an API key using SHA-256 for secure storage.

    Args:
        key: The raw API key to hash.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(key.encode()).hexdigest()


def generate_key(prefix: str = "rb") -> str:
    """Generate a new virtual API key.

    Format: ``{prefix}-{random_hex}`` where the random part is 32 bytes
    (64 hex characters), giving 256 bits of entropy.

    Args:
        prefix: Key prefix (default ``"rb"``).

    Returns:
        A new virtual API key string.
    """
    random_part = secrets.token_hex(32)
    return f"{prefix}-{random_part}"


def generate_short_id(length: int = 12) -> str:
    """Generate a short random ID suitable for request IDs.

    Args:
        length: Number of characters (default 12).

    Returns:
        A random alphanumeric string.
    """
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def mask_key(key: str) -> str:
    """Mask an API key for safe display, showing first 8 and last 4 chars.

    Args:
        key: The API key to mask.

    Returns:
        Masked key string. Short keys are fully masked.
    """
    if len(key) <= 12:
        return "***"
    return f"{key[:8]}...{key[-4:]}"
