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
from routerbot.auth.rbac import (
    ROLE_PERMISSIONS,
    AuthContext,
    Permission,
    Role,
    require_admin,
    require_authenticated,
    require_owner_or_admin,
    require_permission,
    require_team_member_or_admin,
)
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
    "ROLE_PERMISSIONS",
    "AuthContext",
    "InMemorySessionStore",
    "JWTAuthError",
    "JWTAuthenticator",
    "JWTClaims",
    "JWTConfig",
    "KeyValidationResult",
    "OAuth2Provider",
    "OIDCProvider",
    "Permission",
    "Role",
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
    "require_admin",
    "require_authenticated",
    "require_owner_or_admin",
    "require_permission",
    "require_team_member_or_admin",
    "validate_key",
]
