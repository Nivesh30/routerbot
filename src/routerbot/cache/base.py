"""Cache backend protocol and entry types.

Defines the :class:`CacheBackend` protocol that all cache implementations
must satisfy, along with the :class:`CacheEntry` data structure used to
store and retrieve cached LLM responses.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Cache Entry
# ---------------------------------------------------------------------------


@dataclass
class CacheEntry:
    """A cached response entry.

    Parameters
    ----------
    key:
        The cache key that identifies this entry.
    response_data:
        Serialised response (typically a JSON-compatible dict).
    model:
        The model that produced this response.
    created_at:
        Unix timestamp when this entry was created.
    ttl:
        Time-to-live in seconds.  ``None`` means no expiry.
    metadata:
        Arbitrary extra metadata (e.g. token counts, cost).
    """

    key: str
    response_data: dict[str, Any]
    model: str = ""
    created_at: float = 0.0
    ttl: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.created_at == 0.0:
            self.created_at = time.time()

    @property
    def is_expired(self) -> bool:
        """Check whether this cache entry has expired."""
        if self.ttl is None:
            return False
        return (time.time() - self.created_at) > self.ttl


# ---------------------------------------------------------------------------
# Cache Backend Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class CacheBackend(Protocol):
    """Protocol that all cache backend implementations must satisfy."""

    async def get(self, key: str) -> CacheEntry | None:
        """Retrieve a cached entry, or ``None`` if missing/expired."""
        ...

    async def set(self, key: str, value: CacheEntry, ttl: int | None = None) -> None:
        """Store a cache entry. *ttl* overrides the entry's own TTL."""
        ...

    async def delete(self, key: str) -> None:
        """Delete a specific cache entry."""
        ...

    async def clear(self) -> None:
        """Clear all entries from this backend."""
        ...


# ---------------------------------------------------------------------------
# Cache Key Builder
# ---------------------------------------------------------------------------


def build_cache_key(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    namespace: str = "routerbot",
    extra: dict[str, Any] | None = None,
) -> str:
    """Build a deterministic cache key from request parameters.

    Parameters are sorted and hashed so that identical requests always
    produce the same key regardless of dict ordering.
    """
    key_parts: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if temperature is not None:
        key_parts["temperature"] = temperature
    if top_p is not None:
        key_parts["top_p"] = top_p
    if max_tokens is not None:
        key_parts["max_tokens"] = max_tokens
    if tools is not None:
        key_parts["tools"] = tools
    if extra:
        key_parts["extra"] = extra

    serialised = json.dumps(key_parts, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialised.encode()).hexdigest()
    return f"{namespace}:cache:{digest}"
