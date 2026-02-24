"""Authentication and authorization.

Depends on core/ and db/ only. Auth logic independent of HTTP framework.
"""

from routerbot.auth.api_key import (
    KeyValidationResult,
    generate_key,
    hash_key,
    validate_key,
)

__all__ = [
    "KeyValidationResult",
    "generate_key",
    "hash_key",
    "validate_key",
]
