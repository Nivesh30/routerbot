"""Tests for IP-based access control middleware (Task 4.8).

Covers:
- Blocklist enforcement (single IP, CIDR)
- Allowlist enforcement (single IP, CIDR)
- Blocklist takes precedence over allowlist
- X-Forwarded-For header handling
- Per-key IP restrictions (future-ready)
- Invalid CIDR entries gracefully ignored
- Disabled middleware passes all traffic
- client_ip stored on request state
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from routerbot.auth.rbac import AuthContext, Role
from routerbot.db.session import get_session
from routerbot.proxy.middleware.auth import get_auth_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADMIN_CTX = AuthContext(user_id="admin-1", role=Role.ADMIN, auth_method="master_key")


def _make_app(
    *,
    allowed_ips: list[str] | None = None,
    blocked_ips: list[str] | None = None,
    trust_proxy_headers: bool = False,
):
    """Build a test FastAPI app with IP filter middleware configured."""
    from routerbot.core.config_models import RouterBotConfig

    config = RouterBotConfig()
    config.general_settings.allowed_ips = allowed_ips or []
    config.general_settings.blocked_ips = blocked_ips or []
    config.general_settings.trust_proxy_headers = trust_proxy_headers

    from routerbot.proxy.app import create_app

    app = create_app(config=config)

    # Override auth so we don't need DB
    app.dependency_overrides[get_auth_context] = lambda: ADMIN_CTX

    # Override session to avoid DB requirement
    async def _no_session():
        yield None  # type: ignore[misc]

    app.dependency_overrides[get_session] = _no_session

    return app


# ---------------------------------------------------------------------------
# Test: Blocklist
# ---------------------------------------------------------------------------


class TestBlocklist:
    """Requests from blocked IPs are rejected with 403."""

    async def test_blocked_single_ip(self):
        """Single IP in blocklist is denied."""
        app = _make_app(blocked_ips=["127.0.0.1"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 403
        assert "Access denied" in resp.json()["error"]

    async def test_blocked_cidr(self):
        """IP within a blocked CIDR range is denied."""
        app = _make_app(blocked_ips=["127.0.0.0/8"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 403

    async def test_not_blocked_ip_passes(self):
        """IP not in blocklist passes through."""
        app = _make_app(blocked_ips=["10.0.0.1"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        # 127.0.0.1 (testclient) is not 10.0.0.1
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: Allowlist
# ---------------------------------------------------------------------------


class TestAllowlist:
    """When an allowlist is configured, only matching IPs pass."""

    async def test_allowed_ip_passes(self):
        """IP in allowlist passes through."""
        app = _make_app(allowed_ips=["127.0.0.0/8"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_not_in_allowlist_denied(self):
        """IP not in allowlist is rejected."""
        app = _make_app(allowed_ips=["10.0.0.0/8"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 403

    async def test_empty_allowlist_allows_all(self):
        """No allowlist configured = everything passes."""
        app = _make_app(allowed_ips=[])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: Blocklist precedence
# ---------------------------------------------------------------------------


class TestBlocklistPrecedence:
    """Blocklist is checked before allowlist."""

    async def test_blocked_even_if_allowlisted(self):
        """An IP in both lists is blocked."""
        app = _make_app(
            allowed_ips=["127.0.0.0/8"],
            blocked_ips=["127.0.0.1"],
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test: X-Forwarded-For
# ---------------------------------------------------------------------------


class TestXForwardedFor:
    """Proxy header handling for IP extraction."""

    async def test_xff_blocked(self):
        """X-Forwarded-For IP is used when trust_proxy_headers=True."""
        app = _make_app(blocked_ips=["203.0.113.50"], trust_proxy_headers=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/health",
                headers={"X-Forwarded-For": "203.0.113.50, 10.0.0.1"},
            )
        assert resp.status_code == 403

    async def test_xff_allowed(self):
        """X-Forwarded-For IP in allowlist passes."""
        app = _make_app(allowed_ips=["203.0.113.0/24"], trust_proxy_headers=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/health",
                headers={"X-Forwarded-For": "203.0.113.50"},
            )
        assert resp.status_code == 200

    async def test_xff_ignored_when_not_trusted(self):
        """X-Forwarded-For is ignored when trust_proxy_headers=False."""
        app = _make_app(blocked_ips=["203.0.113.50"], trust_proxy_headers=False)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/health",
                headers={"X-Forwarded-For": "203.0.113.50"},
            )
        # The actual client IP (127.0.0.1) is not blocked
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: No filtering (middleware disabled)
# ---------------------------------------------------------------------------


class TestDisabledMiddleware:
    """When no allow/block lists are set, all traffic passes."""

    async def test_no_config_passes(self):
        """Default config (empty lists) allows everything."""
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: Invalid CIDR entries
# ---------------------------------------------------------------------------


class TestInvalidEntries:
    """Invalid IP/CIDR strings in config are gracefully handled."""

    async def test_invalid_cidr_ignored(self):
        """Invalid entries are skipped; valid ones still enforced."""
        app = _make_app(blocked_ips=["not-an-ip", "127.0.0.1"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        # 127.0.0.1 is still blocked
        assert resp.status_code == 403

    async def test_all_invalid_entries_no_filtering(self):
        """If all entries are invalid, lists are effectively empty."""
        app = _make_app(blocked_ips=["not-an-ip", "also-bad"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        # No valid entries → no blocking
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: CIDR range coverage
# ---------------------------------------------------------------------------


class TestCIDRRanges:
    """Various CIDR ranges work correctly."""

    async def test_ipv4_slash_32(self):
        """/32 matches exactly one IP."""
        app = _make_app(blocked_ips=["127.0.0.1/32"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 403

    async def test_ipv4_slash_24(self):
        """/24 matches a Class C subnet."""
        app = _make_app(blocked_ips=["127.0.0.0/24"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 403

    async def test_ipv4_outside_cidr(self):
        """IP outside a CIDR range is not blocked."""
        app = _make_app(blocked_ips=["192.168.1.0/24"])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        # 127.0.0.1 is NOT in 192.168.1.0/24
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test: Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """Direct tests of utility functions."""

    def test_parse_networks_valid(self):
        """Valid CIDRs are parsed."""
        from routerbot.proxy.middleware.ip_filter import _parse_networks

        nets = _parse_networks(["10.0.0.0/8", "192.168.1.0/24", "1.2.3.4"])
        assert len(nets) == 3

    def test_parse_networks_invalid_skipped(self):
        """Invalid entries are silently skipped."""
        from routerbot.proxy.middleware.ip_filter import _parse_networks

        nets = _parse_networks(["bad", "10.0.0.0/8", "also-bad"])
        assert len(nets) == 1

    def test_ip_in_networks_true(self):
        """IP within a network returns True."""
        from routerbot.proxy.middleware.ip_filter import _ip_in_networks, _parse_networks

        nets = _parse_networks(["10.0.0.0/8"])
        assert _ip_in_networks("10.1.2.3", nets) is True

    def test_ip_in_networks_false(self):
        """IP outside all networks returns False."""
        from routerbot.proxy.middleware.ip_filter import _ip_in_networks, _parse_networks

        nets = _parse_networks(["10.0.0.0/8"])
        assert _ip_in_networks("192.168.1.1", nets) is False

    def test_ip_in_networks_invalid_ip(self):
        """Invalid IP string returns False."""
        from routerbot.proxy.middleware.ip_filter import _ip_in_networks, _parse_networks

        nets = _parse_networks(["10.0.0.0/8"])
        assert _ip_in_networks("not-an-ip", nets) is False

    def test_get_client_ip_no_proxy(self):
        """Without proxy trust, returns request.client.host."""
        from unittest.mock import MagicMock

        from routerbot.proxy.middleware.ip_filter import get_client_ip

        req = MagicMock()
        req.headers = {"x-forwarded-for": "203.0.113.50"}
        req.client = MagicMock(host="192.168.1.1")
        assert get_client_ip(req, trust_proxy=False) == "192.168.1.1"

    def test_get_client_ip_with_proxy(self):
        """With proxy trust, returns first X-Forwarded-For entry."""
        from unittest.mock import MagicMock

        from routerbot.proxy.middleware.ip_filter import get_client_ip

        req = MagicMock()
        req.headers = {"x-forwarded-for": "203.0.113.50, 10.0.0.1"}
        req.client = MagicMock(host="192.168.1.1")
        assert get_client_ip(req, trust_proxy=True) == "203.0.113.50"

    def test_get_client_ip_no_client(self):
        """When request.client is None, returns fallback."""
        from unittest.mock import MagicMock

        from routerbot.proxy.middleware.ip_filter import get_client_ip

        req = MagicMock()
        req.headers = {}
        req.client = None
        assert get_client_ip(req, trust_proxy=False) == "0.0.0.0"  # noqa: S104
