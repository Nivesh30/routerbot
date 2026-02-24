"""Role-Based Access Control (RBAC) system.

Defines roles (``admin``, ``editor``, ``viewer``, ``api_user``), a
permission matrix, and an ``AuthContext`` that middleware resolves from
incoming requests.

All RBAC features are **fully free and open source** — no enterprise gate.

Usage::

    from routerbot.auth.rbac import AuthContext, Permission, Role, require_permission

    ctx = AuthContext(user_id="u1", role=Role.ADMIN)
    require_permission(ctx, Permission.KEYS_MANAGE_ALL)  # passes for admin
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any

from routerbot.core.exceptions import AuthenticationError, PermissionDeniedError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role(enum.StrEnum):
    """User roles (from most-privileged to least-privileged)."""

    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"
    API_USER = "api_user"

    @classmethod
    def from_str(cls, value: str) -> Role:
        """Parse a role string (case-insensitive).

        Raises
        ------
        ValueError
            If *value* is not a recognised role.
        """
        try:
            return cls(value.lower())
        except ValueError:
            valid = ", ".join(r.value for r in cls)
            msg = f"Invalid role '{value}'. Must be one of: {valid}"
            raise ValueError(msg) from None


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


class Permission(enum.StrEnum):
    """Fine-grained permissions checked by route handlers."""

    # LLM endpoints
    LLM_ACCESS = "llm:access"

    # Key management
    KEYS_MANAGE_OWN = "keys:manage_own"
    KEYS_MANAGE_TEAM = "keys:manage_team"
    KEYS_MANAGE_ALL = "keys:manage_all"

    # Team management
    TEAMS_MANAGE = "teams:manage"

    # User management
    USERS_MANAGE = "users:manage"

    # Model management
    MODELS_MANAGE = "models:manage"

    # Spend / reporting
    SPEND_VIEW_OWN = "spend:view_own"
    SPEND_VIEW_ALL = "spend:view_all"

    # Settings
    SETTINGS_MANAGE = "settings:manage"

    # Audit
    AUDIT_VIEW = "audit:view"

    # Guardrails
    GUARDRAILS_MANAGE_TEAM = "guardrails:manage_team"
    GUARDRAILS_MANAGE_ALL = "guardrails:manage_all"


# Permission matrix per role.
# Each role maps to a frozenset of permissions.
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),  # admin gets everything
    Role.EDITOR: frozenset({
        Permission.LLM_ACCESS,
        Permission.KEYS_MANAGE_OWN,
        Permission.KEYS_MANAGE_TEAM,
        Permission.MODELS_MANAGE,
        Permission.SPEND_VIEW_OWN,
        Permission.GUARDRAILS_MANAGE_TEAM,
    }),
    Role.VIEWER: frozenset({
        Permission.SPEND_VIEW_OWN,
    }),
    Role.API_USER: frozenset({
        Permission.LLM_ACCESS,
    }),
}


# ---------------------------------------------------------------------------
# Auth Context
# ---------------------------------------------------------------------------


@dataclass
class AuthContext:
    """Resolved identity and permissions for the current request.

    Populated by the auth middleware and made available to route handlers
    via ``request.state.auth_context`` or ``Depends(get_auth_context)``.
    """

    # Identity
    user_id: str | None = None
    email: str | None = None
    team_id: str | None = None
    role: Role = Role.API_USER

    # Auth method that was used
    auth_method: str = "none"  # "api_key", "jwt", "sso", "master_key"

    # The raw key/token for reference (never logged)
    key_id: str | None = None

    # Extra data from the auth source
    extra: dict[str, Any] = field(default_factory=dict)

    # Allowed models from key permissions (empty = all)
    allowed_models: list[str] = field(default_factory=list)

    # Budget info
    max_budget: float | None = None
    current_spend: float = 0.0

    @property
    def permissions(self) -> frozenset[Permission]:
        """Return the set of permissions for this context's role."""
        return ROLE_PERMISSIONS.get(self.role, frozenset())

    def has_permission(self, perm: Permission) -> bool:
        """Check whether this context has a specific permission."""
        return perm in self.permissions

    @property
    def is_admin(self) -> bool:
        """Return ``True`` if the user has the admin role."""
        return self.role == Role.ADMIN

    @property
    def is_authenticated(self) -> bool:
        """Return ``True`` if the request was authenticated."""
        return self.auth_method != "none"


# ---------------------------------------------------------------------------
# Permission checking helpers
# ---------------------------------------------------------------------------


def require_permission(ctx: AuthContext, perm: Permission) -> None:
    """Raise :class:`PermissionDeniedError` if the context lacks *perm*.

    Parameters
    ----------
    ctx:
        The resolved auth context for the current request.
    perm:
        The permission to check.

    Raises
    ------
    PermissionDeniedError
        If the context does not have the required permission.
    """
    if not ctx.has_permission(perm):
        raise PermissionDeniedError(
            message=f"Permission denied: '{perm.value}' required (role={ctx.role.value})",
        )


def require_authenticated(ctx: AuthContext) -> None:
    """Raise :class:`AuthenticationError` if the request is not authenticated.

    Raises
    ------
    AuthenticationError
        If ``ctx.auth_method`` is ``"none"``.
    """
    if not ctx.is_authenticated:
        raise AuthenticationError(
            message="Authentication required. Provide a valid API key, JWT token, or SSO session.",
        )


def require_admin(ctx: AuthContext) -> None:
    """Raise :class:`PermissionDeniedError` if the user is not an admin.

    Raises
    ------
    PermissionDeniedError
        If the user's role is not ``admin``.
    """
    if not ctx.is_admin:
        raise PermissionDeniedError(
            message="Admin access required.",
        )


def require_owner_or_admin(ctx: AuthContext, resource_user_id: str | None) -> None:
    """Allow access if the user is the resource owner or an admin.

    Parameters
    ----------
    ctx:
        Current auth context.
    resource_user_id:
        The user ID that owns the resource.

    Raises
    ------
    PermissionDeniedError
        If the user is neither the owner nor an admin.
    """
    if ctx.is_admin:
        return
    if ctx.user_id and ctx.user_id == resource_user_id:
        return
    raise PermissionDeniedError(
        message="You do not have permission to access this resource.",
    )


def require_team_member_or_admin(ctx: AuthContext, resource_team_id: str | None) -> None:
    """Allow access if the user is on the resource's team or is an admin.

    Parameters
    ----------
    ctx:
        Current auth context.
    resource_team_id:
        The team that owns the resource.

    Raises
    ------
    PermissionDeniedError
        If the user is not on the team and not an admin.
    """
    if ctx.is_admin:
        return
    if ctx.team_id and ctx.team_id == resource_team_id:
        return
    raise PermissionDeniedError(
        message="Team membership or admin access required.",
    )
