"""Plugin registry — stores and queries loaded plugins.

The registry is the central index of all discovered and loaded
plugins. It supports querying by type, name, and status.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from routerbot.core.plugins.models import PluginInfo, PluginStatus, PluginType

if TYPE_CHECKING:
    from routerbot.core.plugins.hooks import PluginHook

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Thread-safe registry of loaded plugin hooks.

    Stores both the :class:`PluginInfo` metadata and the live
    :class:`PluginHook` instance for each plugin.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginHook] = {}
        self._info: dict[str, PluginInfo] = {}

    # ── Registration ─────────────────────────────────────────────────

    def register(self, hook: PluginHook, info: PluginInfo) -> None:
        """Register a plugin hook and its metadata."""
        if info.name in self._plugins:
            logger.warning("Plugin '%s' already registered — replacing", info.name)
        self._plugins[info.name] = hook
        self._info[info.name] = info
        logger.info("Registered plugin '%s' (type=%s)", info.name, info.plugin_type)

    def unregister(self, name: str) -> bool:
        """Remove a plugin by name. Returns True if found."""
        removed = self._plugins.pop(name, None) is not None
        self._info.pop(name, None)
        if removed:
            logger.info("Unregistered plugin '%s'", name)
        return removed

    # ── Queries ──────────────────────────────────────────────────────

    def get(self, name: str) -> PluginHook | None:
        """Return the hook instance for *name*, or None."""
        return self._plugins.get(name)

    def get_info(self, name: str) -> PluginInfo | None:
        """Return the metadata for *name*, or None."""
        return self._info.get(name)

    def list_plugins(
        self,
        *,
        plugin_type: PluginType | None = None,
        status: PluginStatus | None = None,
    ) -> list[PluginInfo]:
        """Return plugin metadata, optionally filtered by type and status."""
        results = list(self._info.values())
        if plugin_type is not None:
            results = [p for p in results if p.plugin_type == plugin_type]
        if status is not None:
            results = [p for p in results if p.status == status]
        return results

    def get_hooks_by_type(self, plugin_type: PluginType) -> list[PluginHook]:
        """Return all active hooks of a given type."""
        return [
            self._plugins[info.name]
            for info in self._info.values()
            if info.plugin_type == plugin_type and info.status == PluginStatus.ACTIVE
        ]

    @property
    def all_names(self) -> list[str]:
        """Return names of all registered plugins."""
        return list(self._plugins.keys())

    @property
    def count(self) -> int:
        """Total number of registered plugins."""
        return len(self._plugins)

    def summary(self) -> list[dict[str, Any]]:
        """Return a JSON-serialisable summary of all plugins."""
        return [info.model_dump() for info in self._info.values()]

    def clear(self) -> None:
        """Remove all plugins (used in testing)."""
        self._plugins.clear()
        self._info.clear()
