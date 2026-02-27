"""Base classes and resolver for secret manager integration.

The ``SecretResolver`` is the main entry point. It recognises URI-prefixed
config values and delegates to the appropriate ``SecretBackend`` for
resolution, with an optional in-memory cache to avoid repeated remote calls.
"""

from __future__ import annotations

import abc
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns for matching secret references
# ---------------------------------------------------------------------------

# General pattern:  prefix/path  or  prefix/path#json_key
_SECRET_REF_PATTERN = re.compile(
    r"^(?P<prefix>aws_secret|gcp_secret|azure_keyvault|vault)"
    r"/(?P<path>[^#]+)"
    r"(?:#(?P<key>.+))?$"
)


# ---------------------------------------------------------------------------
# SecretBackend ABC
# ---------------------------------------------------------------------------


class SecretBackend(abc.ABC):
    """Abstract base class for a secret manager backend."""

    @property
    @abc.abstractmethod
    def prefix(self) -> str:
        """The URI prefix this backend handles (e.g. ``aws_secret``)."""

    @abc.abstractmethod
    def get_secret(self, path: str) -> str:
        """Retrieve a secret value by its path/name.

        Args:
            path: Provider-specific path (everything after ``prefix/``).

        Returns:
            The secret value as a string.

        Raises:
            SecretResolutionError: If the secret cannot be retrieved.
        """


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class SecretResolutionError(Exception):
    """Raised when a secret reference cannot be resolved."""


# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    value: str
    expires_at: float


@dataclass
class SecretCache:
    """Simple TTL cache for resolved secrets.

    Args:
        ttl_seconds: How long each entry is valid. 0 disables caching.
    """

    ttl_seconds: float = 300.0
    _store: dict[str, _CacheEntry] = field(default_factory=dict, repr=False)

    def get(self, key: str) -> str | None:
        """Return cached value or ``None`` if missing/expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            del self._store[key]
            return None
        return entry.value

    def put(self, key: str, value: str) -> None:
        """Store a value (respects TTL)."""
        if self.ttl_seconds <= 0:
            return
        self._store[key] = _CacheEntry(
            value=value,
            expires_at=time.monotonic() + self.ttl_seconds,
        )

    def clear(self) -> None:
        """Evict all cached entries."""
        self._store.clear()

    @property
    def size(self) -> int:
        """Number of cached entries (including potentially expired)."""
        return len(self._store)


# ---------------------------------------------------------------------------
# Resolver orchestrator
# ---------------------------------------------------------------------------


class SecretResolver:
    """Resolves ``prefix/path`` references to actual secret values.

    Register one or more :class:`SecretBackend` instances, then call
    :meth:`resolve` or :meth:`resolve_all` on config data.
    """

    def __init__(
        self,
        *,
        cache: SecretCache | None = None,
    ) -> None:
        self._backends: dict[str, SecretBackend] = {}
        self._cache = cache or SecretCache(ttl_seconds=0)

    # -- registration -------------------------------------------------------

    def register_backend(self, backend: SecretBackend) -> None:
        """Add a secret backend for the given prefix."""
        self._backends[backend.prefix] = backend
        logger.info("Registered secret backend: %s", backend.prefix)

    @property
    def registered_prefixes(self) -> list[str]:
        """Return the list of registered prefixes."""
        return list(self._backends.keys())

    # -- resolution ---------------------------------------------------------

    def resolve(self, value: str) -> str:
        """Resolve a single config value if it matches a secret reference.

        Non-matching values are returned unchanged.

        Args:
            value: A config string that may be a ``prefix/path`` reference.

        Returns:
            The resolved secret value **or** the original string.

        Raises:
            SecretResolutionError: If the reference matches but resolution fails.
        """
        match = _SECRET_REF_PATTERN.match(value)
        if not match:
            return value

        prefix = match.group("prefix")
        path = match.group("path")
        json_key = match.group("key")  # may be None

        backend = self._backends.get(prefix)
        if backend is None:
            msg = (
                f"No secret backend registered for prefix '{prefix}'. "
                f"Available: {list(self._backends.keys())}"
            )
            raise SecretResolutionError(msg)

        cache_key = f"{prefix}/{path}"

        # Check cache first
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Secret cache hit: %s", cache_key)
            raw_value = cached
        else:
            logger.debug("Resolving secret: %s", cache_key)
            try:
                raw_value = backend.get_secret(path)
            except SecretResolutionError:
                raise
            except Exception as exc:
                msg = f"Failed to resolve secret '{cache_key}': {exc}"
                raise SecretResolutionError(msg) from exc
            self._cache.put(cache_key, raw_value)

        # JSON key extraction
        if json_key is not None:
            return self._extract_json_key(raw_value, json_key, cache_key)

        return raw_value

    def resolve_all(self, data: Any) -> Any:
        """Recursively resolve all secret references in a config data tree.

        Walks dicts, lists, and string scalars. Non-string / non-matching
        values pass through unchanged.
        """
        if isinstance(data, dict):
            return {k: self.resolve_all(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self.resolve_all(item) for item in data]
        if isinstance(data, str):
            return self.resolve(data)
        return data

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def is_secret_ref(value: str) -> bool:
        """Return ``True`` if the string looks like a secret reference."""
        return _SECRET_REF_PATTERN.match(value) is not None

    @staticmethod
    def _extract_json_key(raw: str, key: str, ref: str) -> str:
        """Extract a key from a JSON-encoded secret value."""
        import json

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            msg = f"Secret '{ref}' is not valid JSON, cannot extract key '{key}'"
            raise SecretResolutionError(msg) from exc

        if not isinstance(data, dict):
            msg = f"Secret '{ref}' is not a JSON object, cannot extract key '{key}'"
            raise SecretResolutionError(msg)

        if key not in data:
            msg = f"Key '{key}' not found in secret '{ref}'. Available: {list(data.keys())}"
            raise SecretResolutionError(msg)

        return str(data[key])
