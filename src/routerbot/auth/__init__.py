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
from routerbot.auth.session import (
    InMemorySessionStore,
    SessionConfig,
    SessionCookie,
    SessionDeleteCookie,
    SessionManager,
)
from routerbot.auth.sso import (
    OAuth2Provider,
    OIDCProvider,
    SSOError,
    SSOManager,
    SSOProviderConfig,
    SSOUserInfo,
)

__all__ = [
    "InMemorySessionStore",
    "JWTAuthError",
    "JWTAuthenticator",
    "JWTClaims",
    "JWTConfig",
    "KeyValidationResult",
    "OAuth2Provider",
    "OIDCProvider",
    "SSOError",
    "SSOManager",
    "SSOProviderConfig",
    "SSOUserInfo",
    "SessionConfig",
    "SessionCookie",
    "SessionDeleteCookie",
    "SessionManager",
    "generate_key",
    "hash_key",
    "validate_key",
]
