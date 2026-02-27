"""Plugin data models and enumerations."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PluginType(StrEnum):
    """Category of plugin hook."""

    PROVIDER = "provider"
    GUARDRAIL = "guardrail"
    CALLBACK = "callback"
    AUTH = "auth"
    MIDDLEWARE = "middleware"


class PluginStatus(StrEnum):
    """Lifecycle state of a loaded plugin."""

    DISCOVERED = "discovered"
    LOADED = "loaded"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


class PluginInfo(BaseModel):
    """Metadata describing a loaded plugin."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    plugin_type: PluginType
    status: PluginStatus = PluginStatus.DISCOVERED
    entry_point: str = ""
    error_message: str | None = None
    loaded_at: datetime | None = None
    config: dict[str, Any] = Field(default_factory=dict)

    def activate(self) -> None:
        """Mark the plugin as active."""
        self.status = PluginStatus.ACTIVE
        self.loaded_at = datetime.now(tz=UTC)

    def fail(self, message: str) -> None:
        """Mark the plugin as errored."""
        self.status = PluginStatus.ERROR
        self.error_message = message


class PluginConfig(BaseModel):
    """Configuration for the plugin subsystem."""

    enabled: bool = False
    auto_discover: bool = True
    entry_point_group: str = Field(
        default="routerbot.plugins",
        description="Python entry-point group to scan for plugins.",
    )
    plugins: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Explicit plugin declarations from config YAML.",
    )
    disabled_plugins: list[str] = Field(
        default_factory=list,
        description="Plugin names to skip during loading.",
    )
