"""IP-based access control middleware.

Supports:
- Global IP allowlist/blocklist via config
- CIDR notation (e.g. ``10.0.0.0/8``, ``192.168.1.0/24``)
- ``X-Forwarded-For`` header handling for reverse proxies
- Per-request IP tracking on ``request.state.client_ip``

Configuration::

    general_settings:
      allowed_ips: ["10.0.0.0/8", "192.168.1.0/24"]
      blocked_ips: ["1.2.3.4"]
      trust_proxy_headers: true
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request  # noqa: TC002
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


def _parse_networks(raw: list[str]) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse a list of IP/CIDR strings into network objects.

    Single IPs (no prefix) are converted to /32 (v4) or /128 (v6).
    Invalid entries are logged and skipped.
    """
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in raw:
        try:
            networks.append(ipaddress.ip_network(entry.strip(), strict=False))
        except ValueError:
            logger.warning("Invalid IP/CIDR entry ignored: %s", entry)
    return networks


def _ip_in_networks(
    ip_str: str,
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """Check if *ip_str* is contained in any of the *networks*."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def get_client_ip(request: Request, *, trust_proxy: bool = False) -> str:
    """Extract the real client IP from the request.

    When *trust_proxy* is ``True``, the first entry of the
    ``X-Forwarded-For`` header is used (standard reverse-proxy pattern).
    Otherwise, falls back to ``request.client.host``.
    """
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "0.0.0.0"  # noqa: S104


class IPFilterMiddleware(BaseHTTPMiddleware):
    """Reject requests from blocked IPs or IPs not in the allowlist.

    Parameters
    ----------
    app:
        The ASGI application.
    allowed_ips:
        Optional list of IP/CIDR strings.  When non-empty, **only** IPs
        matching this list are allowed through.
    blocked_ips:
        Optional list of IP/CIDR strings.  IPs matching this list are
        always rejected (checked **before** the allowlist).
    trust_proxy_headers:
        If ``True``, use ``X-Forwarded-For`` to determine client IP.
    """

    def __init__(
        self,
        app: Any,
        *,
        allowed_ips: list[str] | None = None,
        blocked_ips: list[str] | None = None,
        trust_proxy_headers: bool = False,
    ) -> None:
        super().__init__(app)
        self._allowed = _parse_networks(allowed_ips or [])
        self._blocked = _parse_networks(blocked_ips or [])
        self._trust_proxy = trust_proxy_headers
        self._enabled = bool(self._allowed or self._blocked)

        if self._allowed:
            logger.info("IP allowlist active: %d network(s)", len(self._allowed))
        if self._blocked:
            logger.info("IP blocklist active: %d network(s)", len(self._blocked))

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        """Check the client IP against allow/block lists."""
        client_ip = get_client_ip(request, trust_proxy=self._trust_proxy)

        # Always store the resolved client IP for downstream use
        request.state.client_ip = client_ip

        if not self._enabled:
            return await call_next(request)

        # Blocklist takes precedence
        if self._blocked and _ip_in_networks(client_ip, self._blocked):
            logger.warning("Blocked request from IP: %s (path: %s)", client_ip, request.url.path)
            return JSONResponse(
                status_code=403,
                content={"error": f"Access denied for IP: {client_ip}"},
            )

        # If allowlist is configured, IP must be in it
        if self._allowed and not _ip_in_networks(client_ip, self._allowed):
            logger.warning("Denied request from IP not in allowlist: %s (path: %s)", client_ip, request.url.path)
            return JSONResponse(
                status_code=403,
                content={"error": f"Access denied for IP: {client_ip}"},
            )

        return await call_next(request)
