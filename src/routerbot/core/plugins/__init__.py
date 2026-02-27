"""Plugin system for RouterBot.

Allows third-party extensions via well-defined hook interfaces,
Python entry-point discovery, and YAML-based configuration.
"""

from routerbot.core.plugins.hooks import (
    AuthHook,
    CallbackHook,
    GuardrailHook,
    MiddlewareHook,
    PluginHook,
    ProviderHook,
)
from routerbot.core.plugins.manager import PluginManager
from routerbot.core.plugins.models import (
    PluginConfig,
    PluginInfo,
    PluginStatus,
    PluginType,
)
from routerbot.core.plugins.registry import PluginRegistry

__all__ = [
    "AuthHook",
    "CallbackHook",
    "GuardrailHook",
    "MiddlewareHook",
    "PluginConfig",
    "PluginHook",
    "PluginInfo",
    "PluginManager",
    "PluginRegistry",
    "PluginStatus",
    "PluginType",
    "ProviderHook",
]
