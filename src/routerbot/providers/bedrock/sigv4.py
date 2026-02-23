"""AWS Signature Version 4 (SigV4) request signing.

Implements the SigV4 signing process without any AWS SDK dependencies.
Reference: https://docs.aws.amazon.com/general/latest/gr/sigv4-create-canonical-request.html
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from urllib.parse import quote


def _sha256_hex(data: bytes | str) -> str:
    """Return the hex-encoded SHA-256 hash of data."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    """Return HMAC-SHA256 of msg under key."""
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(
    secret_access_key: str,
    datestamp: str,
    region: str,
    service: str,
) -> bytes:
    """Derive the SigV4 signing key from the secret access key."""
    k_date = _hmac_sha256(("AWS4" + secret_access_key).encode("utf-8"), datestamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "aws4_request")


def sign_request(
    *,
    method: str,
    url: str,
    payload: bytes,
    region: str,
    service: str,
    access_key: str,
    secret_key: str,
    session_token: str | None = None,
    headers: dict[str, str] | None = None,
    amz_date: str | None = None,
) -> dict[str, str]:
    """Compute SigV4 Authorization and required headers.

    Parameters
    ----------
    method:
        HTTP method (``"POST"``, ``"GET"``, …).
    url:
        Full request URL including query string.
    payload:
        Raw request body bytes (empty ``b""`` for GET requests).
    region:
        AWS region string, e.g. ``"us-east-1"``.
    service:
        AWS service identifier, e.g. ``"bedrock-runtime"``.
    access_key:
        AWS access key ID.
    secret_key:
        AWS secret access key.
    session_token:
        Optional STS session token.
    headers:
        Additional headers to include in the canonical request (will be
        merged with mandatory ``host`` / ``x-amz-date`` headers).
    amz_date:
        Override timestamp (format: ``YYYYMMDDTHHMMSSZ``).  Defaults to
        the current UTC time.

    Returns
    -------
    dict[str, str]
        Headers to add to the request:
        ``x-amz-date``, optionally ``x-amz-security-token``,
        and ``Authorization``.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.netloc
    canonical_uri = _canonical_uri(parsed.path or "/")
    canonical_querystring = _canonical_querystring(parsed.query)

    now = datetime.now(tz=UTC)
    amz_date = amz_date or now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = amz_date[:8]

    # Build canonical / signed headers
    all_headers: dict[str, str] = {}
    if headers:
        for k, v in headers.items():
            all_headers[k.lower()] = v.strip()
    all_headers["host"] = host
    all_headers["x-amz-date"] = amz_date
    if session_token:
        all_headers["x-amz-security-token"] = session_token

    # Canonical header string: sorted lowercase key: value\n
    signed_header_keys = sorted(all_headers)
    canonical_headers = "".join(f"{k}:{all_headers[k]}\n" for k in signed_header_keys)
    signed_headers = ";".join(signed_header_keys)

    payload_hash = _sha256_hex(payload)

    canonical_request = "\n".join(
        [
            method.upper(),
            canonical_uri,
            canonical_querystring,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    # String to sign
    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            _sha256_hex(canonical_request),
        ]
    )

    # Calculate signature
    signing_key = _signing_key(secret_key, datestamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    # Build Authorization header
    authorization = (
        f"AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    result: dict[str, str] = {
        "x-amz-date": amz_date,
        "Authorization": authorization,
    }
    if session_token:
        result["x-amz-security-token"] = session_token

    return result


def _canonical_uri(path: str) -> str:
    """Encode URI path per SigV4 spec (each segment double-encoded)."""
    if not path:
        return "/"
    # Quote each path segment individually, then rejoin
    segments = path.split("/")
    return "/".join(quote(seg, safe="") for seg in segments)


def _canonical_querystring(query: str) -> str:
    """Sort and encode query parameters per SigV4 spec."""
    if not query:
        return ""
    pairs = []
    for part in query.split("&"):
        if "=" in part:
            k, _, v = part.partition("=")
            pairs.append((quote(k, safe=""), quote(v, safe="")))
        elif part:
            pairs.append((quote(part, safe=""), ""))
    pairs.sort(key=lambda x: x[0])
    return "&".join(f"{k}={v}" for k, v in pairs)
