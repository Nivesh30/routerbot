"""Plugin discovery and loading logic.

Discovers plugins from:
1. Python entry-point groups (``importlib.metadata``)
2. Explicit declarations in the YAML configuration
3. Programmatic registration at runtime
"""

from __future__ import annotations

import importlib
import logging
from importlib.metadata import entry_points
from typing import Any

from routerbot.core.plugins.hooks import (
    AuthHook,
    CallbackHook,
    GuardrailHook,
    MiddlewareHook,
    PluginHook,
    ProviderHook,
)
from routerbot.core.plugins.models import (
    PluginConfig,
    PluginInfo,
    PluginStatus,
    PluginType,
)
from routerbot.core.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)

# Map hook classes to PluginType
_HOOK_TYPE_MAP: dict[type, PluginType] = {
    ProviderHook: PluginType.PROVIDER,
    GuardrailHook: PluginType.GUARDRAIL,
    CallbackHook: PluginType.CALLBACK,
    AuthHook: PluginType.AUTH,
    MiddlewareHook: PluginType.MIDDLEWARE,
}


def _resolve_hook_type(hook: PluginHook) -> PluginType:
    """Determine the :class:`PluginType` from a hook instance."""
    for cls, ptype in _HOOK_TYPE_MAP.items():
        if isinstance(hook, cls):
            return ptype
    msg = f"Unknown hook type: {type(hook).__name__}"
    raise TypeError(msg)


class PluginManager:
    """Orchestrates plugin discovery, loading, and lifecycle.

    Typical usage::

        mgr = PluginManager(config)
        await mgr.load_all()         # discover + setup
        mgr.registry.get_hooks_by_type(PluginType.GUARDRAIL)
        ...
        await mgr.shutdown()         # teardown all
    """

    def __init__(self, config: PluginConfig | None = None) -> None:
        self._config = config or PluginConfig()
        self._registry = PluginRegistry()

    @property
    def config(self) -> PluginConfig:
        return self._config

    @property
    def registry(self) -> PluginRegistry:
        return self._registry

    # ── High-level lifecycle ─────────────────────────────────────────

    async def load_all(self) -> list[PluginInfo]:
        """Discover and load all plugins.

        1. Discover entry-point plugins (if ``auto_discover`` is True).
        2. Load explicit plugins from config.
        3. Run ``setup()`` on each loaded hook.

        Returns the list of :class:`PluginInfo` for all loaded plugins.
        """
        loaded: list[PluginInfo] = []

        if self._config.auto_discover:
            loaded.extend(self._discover_entry_points())

        loaded.extend(self._load_config_plugins())

        # Run setup on all newly-loaded plugins
        for info in loaded:
            hook = self._registry.get(info.name)
            if hook is None:
                continue
            try:
                await hook.setup()
                info.activate()
                logger.info("Plugin '%s' activated", info.name)
            except Exception:
                info.fail(f"setup() failed for {info.name}")
                logger.exception("Failed to setup plugin '%s'", info.name)

        return loaded

    async def shutdown(self) -> None:
        """Teardown all active plugins."""
        for info in self._registry.list_plugins(status=PluginStatus.ACTIVE):
            hook = self._registry.get(info.name)
            if hook is None:
                continue
            try:
                await hook.teardown()
                logger.info("Plugin '%s' torn down", info.name)
            except Exception:
                logger.exception("Error tearing down plugin '%s'", info.name)

    # ── Programmatic registration ────────────────────────────────────

    async def register_hook(
        self,
        hook: PluginHook,
        *,
        auto_setup: bool = True,
    ) -> PluginInfo:
        """Register and optionally set up a single hook at runtime."""
        plugin_type = _resolve_hook_type(hook)
        info = PluginInfo(
            name=hook.name,
            version=hook.version,
            description=hook.description,
            author=hook.author,
            plugin_type=plugin_type,
            status=PluginStatus.LOADED,
        )

        self._registry.register(hook, info)

        if auto_setup:
            try:
                await hook.setup()
                info.activate()
            except Exception:
                info.fail(f"setup() failed for {hook.name}")
                logger.exception("Failed to setup plugin '%s'", hook.name)

        return info

    # ── Discovery ────────────────────────────────────────────────────

    def _discover_entry_points(self) -> list[PluginInfo]:
        """Scan Python entry-point groups for plugins."""
        discovered: list[PluginInfo] = []
        group = self._config.entry_point_group

        eps = entry_points()
        # Python 3.12+: entry_points() returns SelectableGroups
        group_eps = eps.select(group=group) if hasattr(eps, "select") else eps.get(group, [])

        for ep in group_eps:
            if ep.name in self._config.disabled_plugins:
                logger.debug("Skipping disabled plugin '%s'", ep.name)
                continue

            try:
                hook_cls = ep.load()
                if not (isinstance(hook_cls, type) and issubclass(hook_cls, PluginHook)):
                    logger.warning(
                        "Entry point '%s' is not a PluginHook subclass — skipping",
                        ep.name,
                    )
                    continue

                hook = hook_cls()
                plugin_type = _resolve_hook_type(hook)

                info = PluginInfo(
                    name=hook.name or ep.name,
                    version=hook.version,
                    description=hook.description,
                    author=hook.author,
                    plugin_type=plugin_type,
                    status=PluginStatus.LOADED,
                    entry_point=f"{group}:{ep.name}",
                )
                self._registry.register(hook, info)
                discovered.append(info)
                logger.info(
                    "Discovered plugin '%s' from entry point %s:%s",
                    info.name,
                    group,
                    ep.name,
                )
            except Exception:
                logger.exception("Failed to load entry point '%s'", ep.name)

        return discovered

    def _load_config_plugins(self) -> list[PluginInfo]:
        """Load plugins declared explicitly in configuration."""
        loaded: list[PluginInfo] = []

        for plugin_decl in self._config.plugins:
            name = plugin_decl.get("name", "")
            if not name:
                logger.warning("Plugin declaration missing 'name' — skipping")
                continue

            if name in self._config.disabled_plugins:
                logger.debug("Skipping disabled plugin '%s'", name)
                continue

            module_path = plugin_decl.get("module", "")
            class_name = plugin_decl.get("class", "")
            if not module_path or not class_name:
                logger.warning(
                    "Plugin '%s' missing 'module' or 'class' — skipping", name,
                )
                continue

            try:
                hook = self._import_hook(module_path, class_name, plugin_decl.get("config"))
                plugin_type = _resolve_hook_type(hook)

                info = PluginInfo(
                    name=hook.name or name,
                    version=hook.version,
                    description=hook.description,
                    author=hook.author,
                    plugin_type=plugin_type,
                    status=PluginStatus.LOADED,
                    config=plugin_decl.get("config", {}),
                )
                self._registry.register(hook, info)
                loaded.append(info)
            except Exception:
                logger.exception("Failed to load plugin '%s'", name)

        return loaded

    @staticmethod
    def _import_hook(
        module_path: str,
        class_name: str,
        config: dict[str, Any] | None = None,
    ) -> PluginHook:
        """Import a module and instantiate the hook class."""
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        if not (isinstance(cls, type) and issubclass(cls, PluginHook)):
            msg = f"{module_path}.{class_name} is not a PluginHook subclass"
            raise TypeError(msg)
        return cls(config=config)
