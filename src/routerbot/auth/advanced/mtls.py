"""Mutual TLS (mTLS) client certificate authentication.

Extracts and validates client certificate information forwarded by
a reverse proxy (e.g. Nginx, Envoy, Traefik) via HTTP headers.

In production, the TLS termination happens at the proxy layer, which
forwards the client certificate as a PEM-encoded header.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime

from routerbot.auth.advanced.models import MTLSConfig, MTLSIdentity

UTC = UTC
logger = logging.getLogger(__name__)


class MTLSAuthenticator:
    """Authenticate requests via client certificates.

    Parameters
    ----------
    config:
        mTLS configuration with CA trust, CN patterns, etc.
    """

    def __init__(self, config: MTLSConfig | None = None) -> None:
        self.config = config or MTLSConfig()
        self._cn_patterns = [re.compile(p) for p in self.config.allowed_cn_patterns]

    def authenticate(self, headers: dict[str, str]) -> MTLSIdentity:
        """Extract and validate a client certificate from request headers.

        Parameters
        ----------
        headers:
            HTTP headers (case-insensitive lookup).

        Returns
        -------
        MTLSIdentity
            Extracted identity, with ``verified=True`` if validation passes.

        Raises
        ------
        MTLSAuthError
            If a certificate is required but not present, or validation fails.
        """
        cert_header = self._get_header(headers, self.config.cert_header)

        if not cert_header:
            if self.config.require_client_cert:
                raise MTLSAuthError("Client certificate required but not provided")
            return MTLSIdentity(verified=False)

        identity = self._parse_cert_header(cert_header)

        # Validate CN patterns
        if self._cn_patterns and identity.common_name and not any(
            p.match(identity.common_name) for p in self._cn_patterns
        ):
                raise MTLSAuthError(
                    f"Client CN '{identity.common_name}' does not match any allowed pattern"
                )

        # Validate SANs
        if self.config.allowed_sans:
            all_sans = identity.san_dns + identity.san_emails
            if not any(san in self.config.allowed_sans for san in all_sans):
                raise MTLSAuthError("Client certificate SAN not in allowed list")

        # Check expiration
        now = datetime.now(tz=UTC)
        if identity.not_after and identity.not_after < now:
            raise MTLSAuthError("Client certificate has expired")
        if identity.not_before and identity.not_before > now:
            raise MTLSAuthError("Client certificate is not yet valid")

        identity.verified = True
        logger.info("mTLS auth successful for CN=%s", identity.common_name)
        return identity

    def _parse_cert_header(self, header_value: str) -> MTLSIdentity:
        """Parse a certificate header value.

        Supports two formats:
        1. URL-encoded PEM (Nginx ``$ssl_client_escaped_cert``)
        2. Base64-encoded DER (some proxies)
        3. Comma-separated key=value fields (simplified format)

        For simplicity, we parse the simplified format here. Real mTLS
        implementations would use ``cryptography`` to parse X.509.
        """
        identity = MTLSIdentity()

        # Compute fingerprint from raw header for dedup
        identity.fingerprint_sha256 = hashlib.sha256(header_value.encode()).hexdigest()

        # Try to extract fields from structured header
        # Format: CN=name,O=org,OU=unit;SAN:dns=host;Serial=xxx
        parts = _split_cert_fields(header_value)

        for key, value in parts.items():
            key_lower = key.lower()
            if key_lower == "cn":
                identity.common_name = value
            elif key_lower == "subject":
                identity.subject = value
            elif key_lower == "issuer":
                identity.issuer = value
            elif key_lower == "serial":
                identity.serial_number = value
            elif key_lower == "san_dns":
                identity.san_dns = [v.strip() for v in value.split(",")]
            elif key_lower == "san_email":
                identity.san_emails = [v.strip() for v in value.split(",")]
            elif key_lower == "not_before":
                identity.not_before = _parse_datetime(value)
            elif key_lower == "not_after":
                identity.not_after = _parse_datetime(value)

        if not identity.subject and identity.common_name:
            identity.subject = f"CN={identity.common_name}"

        return identity

    @staticmethod
    def _get_header(headers: dict[str, str], name: str) -> str:
        """Case-insensitive header lookup."""
        for k, v in headers.items():
            if k.lower() == name.lower():
                return v
        return ""


class MTLSAuthError(Exception):
    """Raised when mTLS authentication fails."""


def _split_cert_fields(header: str) -> dict[str, str]:
    """Parse a semicolon-separated cert header into key=value pairs."""
    result: dict[str, str] = {}
    for segment in header.split(";"):
        segment = segment.strip()
        if "=" in segment:
            key, _, value = segment.partition("=")
            result[key.strip()] = value.strip()
    return result


def _parse_datetime(value: str) -> datetime | None:
    """Try to parse a datetime string."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(value, fmt)  # noqa: DTZ007
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue
    return None
