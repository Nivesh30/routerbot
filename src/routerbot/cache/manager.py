"""Response cache manager.

Provides a single :class:`ResponseCacheManager` that the proxy / router
layer can use to check-before-call and store-after-call, with metrics
tracking and configurable bypass.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from routerbot.cache.base import CacheEntry, build_cache_key

logger = logging.getLogger(__name__)


class ResponseCacheManager:
    """High-level cache manager for LLM responses.

    Wraps a :class:`CacheBackend` and provides convenience methods for
    the router layer:

    * :meth:`lookup` — check cache before calling the provider.
    * :meth:`store` — store a response after a successful provider call.

    Parameters
    ----------
    backend:
        Any object satisfying the :class:`CacheBackend` protocol.
    default_ttl:
        Default TTL used when the backend's own TTL is not set.
    namespace:
        Namespace for cache key generation.
    skip_streaming:
        If ``True`` (default), skip caching for streaming requests.
    """

    def __init__(
        self,
        backend: Any,
        *,
        default_ttl: int = 3600,
        namespace: str = "routerbot",
        skip_streaming: bool = True,
    ) -> None:
        self._backend = backend
        self._default_ttl = default_ttl
        self._namespace = namespace
        self._skip_streaming = skip_streaming
        self._enabled = True

    @property
    def enabled(self) -> bool:
        """Whether caching is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    @property
    def backend(self) -> Any:
        """The underlying cache backend."""
        return self._backend

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    async def lookup(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        cache_control: str | None = None,
    ) -> CacheEntry | None:
        """Check the cache for a matching response.

        Returns ``None`` (cache miss) when:
        * Caching is disabled.
        * ``stream=True`` and ``skip_streaming`` is set.
        * ``cache_control`` is ``"no-cache"``.
        * No matching entry exists / entry is expired.
        """
        if not self._enabled:
            return None

        if stream and self._skip_streaming:
            return None

        if cache_control and cache_control.lower() == "no-cache":
            return None

        key = build_cache_key(
            model=model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            tools=tools,
            namespace=self._namespace,
        )

        entry = await self._backend.get(key)
        if entry is not None:
            logger.debug("Cache HIT for model=%s key=%s", model, key[:32])
        else:
            logger.debug("Cache MISS for model=%s key=%s", model, key[:32])
        return entry

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    async def store(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        response_data: dict[str, Any],
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        ttl: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a response in the cache.

        Parameters
        ----------
        model:
            The model that produced the response.
        messages:
            The request messages (used for cache key generation).
        response_data:
            The full response as a JSON-compatible dict.
        ttl:
            Override TTL.  Falls back to the manager's default.
        metadata:
            Extra metadata to store with the entry (e.g. usage info).
        """
        if not self._enabled:
            return

        key = build_cache_key(
            model=model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            tools=tools,
            namespace=self._namespace,
        )

        entry = CacheEntry(
            key=key,
            response_data=response_data,
            model=model,
            created_at=time.time(),
            ttl=ttl or self._default_ttl,
            metadata=metadata or {},
        )

        await self._backend.set(key, entry, ttl=entry.ttl)
        logger.debug("Cached response for model=%s key=%s", model, key[:32])

    # ------------------------------------------------------------------
    # Invalidation helpers
    # ------------------------------------------------------------------

    async def invalidate(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        """Remove a specific entry from the cache."""
        key = build_cache_key(
            model=model,
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            tools=tools,
            namespace=self._namespace,
        )
        await self._backend.delete(key)

    async def clear(self) -> None:
        """Clear all cached responses."""
        await self._backend.clear()
