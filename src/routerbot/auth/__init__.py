"""Authentication and authorization.

Depends on core/ and db/ only. Auth logic independent of HTTP framework.
"""

from routerbot.auth.api_key import (
    KeyValidationResult,
    generate_key,
    hash_key,
    validate_key,
)
from routerbot.auth.jwt import JWTAuthenticator, JWTAuthError, JWTClaims, JWTConfig

__all__ = [
    "JWTAuthError",
    "JWTAuthenticator",
    "JWTClaims",
    "JWTConfig",
    "KeyValidationResult",
    "generate_key",
    "hash_key",
    "validate_key",
]
