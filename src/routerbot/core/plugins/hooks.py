"""Plugin hook interfaces.

Each hook type defines the contract that plugins must implement.
Hooks are abstract base classes with well-defined lifecycle methods.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class PluginHook:
    """Base class for all plugin hooks.

    Every plugin must expose a concrete subclass of one of the hook
    types. The hook carries its own metadata and configuration, and
    defines ``setup`` / ``teardown`` lifecycle methods.
    """

    #: Human-readable name for this plugin instance.
    name: str = "unnamed-plugin"

    #: Semver string.
    version: str = "0.0.0"

    #: Short description.
    description: str = ""

    #: Author or maintainer.
    author: str = ""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    @property
    def config(self) -> dict[str, Any]:
        """Return the plugin configuration dict."""
        return dict(self._config)

    async def setup(self) -> None:
        """Initialise resources (called once after loading).

        Override to open connections, load caches, etc.
        """

    async def teardown(self) -> None:
        """Release resources (called on shutdown).

        Override to close connections, flush buffers, etc.
        """

    def get_info(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary of this plugin."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "hook_type": type(self).__name__,
        }


# ── Concrete hook types ──────────────────────────────────────────────


class ProviderHook(PluginHook, ABC):
    """Hook for plugins that provide new LLM provider adapters.

    Implementations must return a mapping of provider-name to class
    that can be fed into the provider registry.
    """

    @abstractmethod
    def get_provider_classes(self) -> dict[str, type]:
        """Return ``{name: ProviderClass}`` for registration."""
        ...


class GuardrailHook(PluginHook, ABC):
    """Hook for plugins that add custom guardrail checks.

    The ``check`` method receives the raw messages and can block or
    modify the request.
    """

    @abstractmethod
    async def check(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the guardrail check.

        Return a dict with at least ``{"passed": bool}``.
        If ``passed`` is False, include ``"reason"`` and optionally
        ``"modified_messages"`` for redaction.
        """
        ...


class CallbackHook(PluginHook, ABC):
    """Hook for plugins that add custom logging / callback destinations."""

    @abstractmethod
    async def on_request_start(self, data: dict[str, Any]) -> None:
        """Called when a request begins processing."""
        ...

    @abstractmethod
    async def on_request_end(self, data: dict[str, Any]) -> None:
        """Called when a request completes (success or failure)."""
        ...

    async def on_error(self, data: dict[str, Any]) -> None:
        """Called on request error (optional override)."""


class AuthHook(PluginHook, ABC):
    """Hook for plugins that add custom authentication methods."""

    @abstractmethod
    async def authenticate(
        self,
        headers: dict[str, str],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Authenticate a request.

        Return a dict with ``{"authenticated": bool, "identity": ...}``.
        """
        ...


class MiddlewareHook(PluginHook):
    """Hook for plugins that add custom request/response processing.

    Middleware hooks run in priority order and can modify the request
    before it reaches the provider and/or the response before it's
    sent to the client.
    """

    #: Lower priority runs first (default 100).
    priority: int = 100

    async def before_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Transform the request dict before provider dispatch.

        Return the (possibly modified) request dict.
        """
        return request

    async def after_response(self, response: dict[str, Any]) -> dict[str, Any]:
        """Transform the response dict before sending to the client.

        Return the (possibly modified) response dict.
        """
        return response
