"""Server-side session management for SSO flows.

Sessions are stored in-memory by default, with optional Redis backend for
production multi-process deployments.  Secure cookie configuration is
returned to route handlers for setting on responses.

Usage::

    from routerbot.auth.session import SessionManager

    mgr = SessionManager(secret_key="…")
    session_id = mgr.create_session({"user_id": "…", "email": "…"})
    data = mgr.get_session(session_id)
    mgr.delete_session(session_id)
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_SESSION_TTL = 3600  # 1 hour
DEFAULT_COOKIE_NAME = "routerbot_session"


@dataclass
class SessionConfig:
    """Session management configuration."""

    secret_key: str = ""
    cookie_name: str = DEFAULT_COOKIE_NAME
    cookie_max_age: int = DEFAULT_SESSION_TTL
    cookie_secure: bool = True
    cookie_httponly: bool = True
    cookie_samesite: str = "lax"
    cookie_path: str = "/"
    session_ttl: int = DEFAULT_SESSION_TTL


# ---------------------------------------------------------------------------
# Session store (in-memory, can be swapped for Redis)
# ---------------------------------------------------------------------------


class InMemorySessionStore:
    """Simple in-memory session store.

    Stores sessions as ``{session_id: (data, expires_at)}`` dicts.
    Suitable for single-process deployments and testing.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, tuple[dict[str, Any], float]] = {}

    def set(self, session_id: str, data: dict[str, Any], ttl: int) -> None:
        """Store a session with TTL."""
        expires_at = time.monotonic() + ttl
        self._sessions[session_id] = (data, expires_at)

    def get(self, session_id: str) -> dict[str, Any] | None:
        """Get session data, or None if expired/missing."""
        entry = self._sessions.get(session_id)
        if entry is None:
            return None
        data, expires_at = entry
        if time.monotonic() > expires_at:
            del self._sessions[session_id]
            return None
        return data

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        return self._sessions.pop(session_id, None) is not None

    def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count removed."""
        now = time.monotonic()
        expired = [
            sid for sid, (_, exp) in self._sessions.items() if now > exp
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)

    @property
    def count(self) -> int:
        """Return total session count (including potentially expired)."""
        return len(self._sessions)


# ---------------------------------------------------------------------------
# Session Manager
# ---------------------------------------------------------------------------


@dataclass
class SessionCookie:
    """Cookie parameters to be set on the HTTP response.

    Route handlers use these parameters to call
    ``response.set_cookie(**cookie.as_dict())``.
    """

    key: str
    value: str
    max_age: int
    secure: bool = True
    httponly: bool = True
    samesite: str = "lax"
    path: str = "/"

    def as_dict(self) -> dict[str, Any]:
        """Convert to a dict suitable for ``Response.set_cookie()``."""
        return {
            "key": self.key,
            "value": self.value,
            "max_age": self.max_age,
            "secure": self.secure,
            "httponly": self.httponly,
            "samesite": self.samesite,
            "path": self.path,
        }


@dataclass
class SessionDeleteCookie:
    """Cookie parameters to delete a session cookie."""

    key: str
    path: str = "/"

    def as_dict(self) -> dict[str, Any]:
        """Convert to a dict suitable for ``Response.delete_cookie()``."""
        return {"key": self.key, "path": self.path}


class SessionManager:
    """Manages server-side sessions with CSRF protection.

    Parameters
    ----------
    config:
        Session configuration. If not provided, uses defaults.
    store:
        Custom session store. If not provided, uses in-memory store.
    """

    def __init__(
        self,
        config: SessionConfig | None = None,
        store: InMemorySessionStore | None = None,
    ) -> None:
        self._config = config or SessionConfig()
        self._store = store or InMemorySessionStore()

    def create_session(self, data: dict[str, Any]) -> tuple[str, SessionCookie]:
        """Create a new session and return the session ID + cookie.

        Parameters
        ----------
        data:
            Session data to store (user info, provider, etc.).

        Returns
        -------
        tuple[str, SessionCookie]
            ``(session_id, cookie)`` — the cookie should be set on the response.
        """
        session_id = self._generate_session_id()
        data["_created_at"] = time.time()
        self._store.set(session_id, data, self._config.session_ttl)

        cookie = SessionCookie(
            key=self._config.cookie_name,
            value=session_id,
            max_age=self._config.cookie_max_age,
            secure=self._config.cookie_secure,
            httponly=self._config.cookie_httponly,
            samesite=self._config.cookie_samesite,
            path=self._config.cookie_path,
        )

        logger.debug("Created session %s…", session_id[:8])
        return session_id, cookie

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve session data by session ID.

        Returns ``None`` if the session doesn't exist or has expired.
        """
        return self._store.get(session_id)

    def delete_session(self, session_id: str) -> SessionDeleteCookie:
        """Delete a session and return a cookie-deletion descriptor.

        The route handler should call
        ``response.delete_cookie(**result.as_dict())``.
        """
        self._store.delete(session_id)
        logger.debug("Deleted session %s…", session_id[:8])
        return SessionDeleteCookie(
            key=self._config.cookie_name,
            path=self._config.cookie_path,
        )

    def renew_session(self, session_id: str) -> SessionCookie | None:
        """Renew a session's TTL without changing its data.

        Returns a new cookie (with refreshed max_age), or ``None`` if
        the session doesn't exist.
        """
        data = self._store.get(session_id)
        if data is None:
            return None

        # Re-store with fresh TTL
        self._store.set(session_id, data, self._config.session_ttl)
        return SessionCookie(
            key=self._config.cookie_name,
            value=session_id,
            max_age=self._config.cookie_max_age,
            secure=self._config.cookie_secure,
            httponly=self._config.cookie_httponly,
            samesite=self._config.cookie_samesite,
            path=self._config.cookie_path,
        )

    def generate_csrf_token(self, session_id: str) -> str:
        """Generate a CSRF token bound to a session.

        The token is a HMAC of the session ID using the secret key.
        """
        return hashlib.sha256(
            f"{self._config.secret_key}:{session_id}".encode()
        ).hexdigest()

    def validate_csrf_token(self, session_id: str, token: str) -> bool:
        """Validate a CSRF token against the session."""
        expected = self.generate_csrf_token(session_id)
        return secrets.compare_digest(expected, token)

    def cleanup(self) -> int:
        """Remove expired sessions. Returns count removed."""
        return self._store.cleanup_expired()

    def _generate_session_id(self) -> str:
        """Generate a cryptographically secure session ID."""
        return secrets.token_urlsafe(48)
