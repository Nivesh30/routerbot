"""Tests for RBAC system and auth middleware (Task 4.5).

Covers:
- Role enum parsing and validation
- Permission enum and role-permission matrix
- AuthContext properties and permission checks
- require_* helper functions
- AuthMiddleware: public paths, master key, SSO session, JWT, anon
- get_auth_context dependency
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from routerbot.auth.rbac import (
    AuthContext,
    Permission,
    Role,
    ROLE_PERMISSIONS,
    require_admin,
    require_authenticated,
    require_owner_or_admin,
    require_permission,
    require_team_member_or_admin,
)
from routerbot.core.exceptions import AuthenticationError, PermissionDeniedError


# ---------------------------------------------------------------------------
# Role tests
# ---------------------------------------------------------------------------


class TestRole:
    """Test Role enum."""

    def test_role_values(self):
        assert Role.ADMIN == "admin"
        assert Role.EDITOR == "editor"
        assert Role.VIEWER == "viewer"
        assert Role.API_USER == "api_user"

    def test_from_str_valid(self):
        assert Role.from_str("admin") == Role.ADMIN
        assert Role.from_str("ADMIN") == Role.ADMIN
        assert Role.from_str("Editor") == Role.EDITOR

    def test_from_str_invalid(self):
        with pytest.raises(ValueError, match="Invalid role"):
            Role.from_str("superuser")


# ---------------------------------------------------------------------------
# Permission tests
# ---------------------------------------------------------------------------


class TestPermission:
    """Test Permission enum."""

    def test_permission_values(self):
        assert Permission.LLM_ACCESS == "llm:access"
        assert Permission.KEYS_MANAGE_ALL == "keys:manage_all"
        assert Permission.AUDIT_VIEW == "audit:view"

    def test_admin_has_all_permissions(self):
        admin_perms = ROLE_PERMISSIONS[Role.ADMIN]
        for perm in Permission:
            assert perm in admin_perms

    def test_editor_has_llm_access(self):
        assert Permission.LLM_ACCESS in ROLE_PERMISSIONS[Role.EDITOR]

    def test_editor_no_admin_perms(self):
        editor = ROLE_PERMISSIONS[Role.EDITOR]
        assert Permission.KEYS_MANAGE_ALL not in editor
        assert Permission.TEAMS_MANAGE not in editor
        assert Permission.USERS_MANAGE not in editor
        assert Permission.SETTINGS_MANAGE not in editor
        assert Permission.AUDIT_VIEW not in editor

    def test_viewer_has_only_spend_own(self):
        viewer = ROLE_PERMISSIONS[Role.VIEWER]
        assert Permission.SPEND_VIEW_OWN in viewer
        assert len(viewer) == 1

    def test_api_user_has_only_llm(self):
        api = ROLE_PERMISSIONS[Role.API_USER]
        assert Permission.LLM_ACCESS in api
        assert len(api) == 1


# ---------------------------------------------------------------------------
# AuthContext tests
# ---------------------------------------------------------------------------


class TestAuthContext:
    """Test AuthContext dataclass."""

    def test_default_context(self):
        ctx = AuthContext()
        assert ctx.role == Role.API_USER
        assert ctx.auth_method == "none"
        assert ctx.user_id is None
        assert not ctx.is_admin
        assert not ctx.is_authenticated

    def test_admin_context(self):
        ctx = AuthContext(user_id="u1", role=Role.ADMIN, auth_method="master_key")
        assert ctx.is_admin
        assert ctx.is_authenticated
        assert ctx.has_permission(Permission.KEYS_MANAGE_ALL)
        assert ctx.has_permission(Permission.AUDIT_VIEW)

    def test_editor_permissions(self):
        ctx = AuthContext(role=Role.EDITOR, auth_method="jwt")
        assert ctx.has_permission(Permission.LLM_ACCESS)
        assert ctx.has_permission(Permission.KEYS_MANAGE_OWN)
        assert not ctx.has_permission(Permission.KEYS_MANAGE_ALL)
        assert not ctx.has_permission(Permission.AUDIT_VIEW)

    def test_viewer_permissions(self):
        ctx = AuthContext(role=Role.VIEWER, auth_method="sso")
        assert ctx.has_permission(Permission.SPEND_VIEW_OWN)
        assert not ctx.has_permission(Permission.LLM_ACCESS)

    def test_api_user_permissions(self):
        ctx = AuthContext(role=Role.API_USER, auth_method="api_key")
        assert ctx.has_permission(Permission.LLM_ACCESS)
        assert not ctx.has_permission(Permission.KEYS_MANAGE_OWN)

    def test_permissions_property(self):
        ctx = AuthContext(role=Role.ADMIN)
        assert ctx.permissions == ROLE_PERMISSIONS[Role.ADMIN]


# ---------------------------------------------------------------------------
# require_* helper tests
# ---------------------------------------------------------------------------


class TestRequirePermission:
    """Test require_permission helper."""

    def test_passes_for_admin(self):
        ctx = AuthContext(role=Role.ADMIN, auth_method="master_key")
        require_permission(ctx, Permission.AUDIT_VIEW)  # no exception

    def test_fails_for_viewer(self):
        ctx = AuthContext(role=Role.VIEWER, auth_method="sso")
        with pytest.raises(PermissionDeniedError, match="audit:view"):
            require_permission(ctx, Permission.AUDIT_VIEW)


class TestRequireAuthenticated:
    """Test require_authenticated helper."""

    def test_passes_when_authenticated(self):
        ctx = AuthContext(auth_method="jwt")
        require_authenticated(ctx)  # no exception

    def test_fails_when_anonymous(self):
        ctx = AuthContext(auth_method="none")
        with pytest.raises(AuthenticationError, match="Authentication required"):
            require_authenticated(ctx)


class TestRequireAdmin:
    """Test require_admin helper."""

    def test_passes_for_admin(self):
        ctx = AuthContext(role=Role.ADMIN, auth_method="master_key")
        require_admin(ctx)  # no exception

    def test_fails_for_editor(self):
        ctx = AuthContext(role=Role.EDITOR, auth_method="jwt")
        with pytest.raises(PermissionDeniedError, match="Admin access required"):
            require_admin(ctx)


class TestRequireOwnerOrAdmin:
    """Test require_owner_or_admin helper."""

    def test_admin_passes(self):
        ctx = AuthContext(role=Role.ADMIN, auth_method="master_key")
        require_owner_or_admin(ctx, "u-other")

    def test_owner_passes(self):
        ctx = AuthContext(user_id="u-1", role=Role.EDITOR, auth_method="jwt")
        require_owner_or_admin(ctx, "u-1")

    def test_non_owner_non_admin_fails(self):
        ctx = AuthContext(user_id="u-1", role=Role.EDITOR, auth_method="jwt")
        with pytest.raises(PermissionDeniedError, match="permission"):
            require_owner_or_admin(ctx, "u-other")


class TestRequireTeamMemberOrAdmin:
    """Test require_team_member_or_admin helper."""

    def test_admin_passes(self):
        ctx = AuthContext(role=Role.ADMIN, auth_method="master_key")
        require_team_member_or_admin(ctx, "team-other")

    def test_team_member_passes(self):
        ctx = AuthContext(team_id="t-1", role=Role.EDITOR, auth_method="jwt")
        require_team_member_or_admin(ctx, "t-1")

    def test_non_team_member_fails(self):
        ctx = AuthContext(team_id="t-1", role=Role.EDITOR, auth_method="jwt")
        with pytest.raises(PermissionDeniedError, match="Team membership"):
            require_team_member_or_admin(ctx, "t-other")


# ---------------------------------------------------------------------------
# Auth Middleware tests
# ---------------------------------------------------------------------------


@pytest.fixture
def rbac_app():
    """Create a test app with RBAC middleware."""
    from routerbot.core.config_models import GeneralSettings, RouterBotConfig
    from routerbot.proxy.app import create_app

    config = RouterBotConfig(
        general_settings=GeneralSettings(master_key="test-master-key"),
    )
    app = create_app(config=config)
    return app


@pytest.fixture
async def rbac_client(rbac_app):
    transport = ASGITransport(app=rbac_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


class TestAuthMiddleware:
    """Test the AuthMiddleware."""

    @pytest.mark.asyncio
    async def test_public_path_no_auth(self, rbac_client):
        """Public paths should work without authentication."""
        resp = await rbac_client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_public_path_root(self, rbac_client):
        """Root path should be publicly accessible (no auth required)."""
        resp = await rbac_client.get("/", follow_redirects=False)
        # Root returns 200 (JSON info) or 307 redirect to /ui/ if dashboard is built
        assert resp.status_code in (200, 307, 308), f"Unexpected status {resp.status_code}"

    @pytest.mark.asyncio
    async def test_master_key_via_bearer(self, rbac_client, rbac_app):
        """Master key in Bearer header should grant admin."""
        # Hit the models endpoint which requires auth
        resp = await rbac_client.get(
            "/v1/models",
            headers={"Authorization": "Bearer test-master-key"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_master_key_via_x_header(self, rbac_client, rbac_app):
        """Master key in X-Master-Key header should also work."""
        resp = await rbac_client.get(
            "/v1/models",
            headers={"X-Master-Key": "test-master-key"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_no_auth_still_resolves_context(self, rbac_client):
        """Unauthenticated requests should get anonymous context."""
        # The models endpoint should respond (it doesn't require auth by itself)
        resp = await rbac_client.get("/v1/models")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_sso_session_auth(self, rbac_app):
        """SSO session cookie should resolve to authenticated context."""
        from routerbot.auth.session import SessionConfig, SessionManager

        session_mgr = SessionManager(SessionConfig(secret_key="test"))
        session_id, _ = session_mgr.create_session({
            "email": "test@example.com",
            "provider_user_id": "u-sso-1",
            "role": "editor",
        })
        rbac_app.state.routerbot.session_manager = session_mgr

        transport = ASGITransport(app=rbac_app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get(
                "/v1/models",
                cookies={"routerbot_session": session_id},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# get_auth_context dependency test
# ---------------------------------------------------------------------------


class TestGetAuthContext:
    """Test the get_auth_context dependency."""

    def test_returns_context_from_state(self):
        from routerbot.proxy.middleware.auth import get_auth_context

        mock_request = Mock()
        mock_request.state.auth_context = AuthContext(
            user_id="u-1",
            role=Role.ADMIN,
            auth_method="master_key",
        )
        ctx = get_auth_context(mock_request)
        assert ctx.user_id == "u-1"
        assert ctx.is_admin

    def test_returns_anonymous_when_missing(self):
        from routerbot.proxy.middleware.auth import get_auth_context

        mock_request = Mock()
        mock_request.state.auth_context = None
        ctx = get_auth_context(mock_request)
        assert ctx.auth_method == "none"

    def test_returns_anonymous_no_attr(self):
        from routerbot.proxy.middleware.auth import get_auth_context

        mock_request = Mock(spec=[])
        mock_request.state = Mock(spec=[])
        ctx = get_auth_context(mock_request)
        assert ctx.auth_method == "none"
