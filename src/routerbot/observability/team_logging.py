"""Team-based logging configuration and callback routing.

Allows each team to have its own set of callbacks, override global
logging destinations (e.g. team-specific Langfuse projects), or
disable logging entirely for GDPR compliance.

Configuration is stored in the team's ``settings`` JSON column::

    team.settings = {
        "callbacks": ["langfuse", "webhook"],
        "disable_logging": False,
        "langfuse_public_key": "pk-team-...",
        "langfuse_secret_key": "sk-team-...",
        "langfuse_host": "https://cloud.langfuse.com",
        "webhook_url": "https://hooks.example.com/llm-logs",
        "webhook_headers": {"Authorization": "Bearer ..."},
    }

When ``disable_logging`` is ``True``, **no** callbacks fire for that
team's requests (GDPR mode).

When ``callbacks`` is set, **only** those named callbacks fire (the
global callback list is replaced, not merged).

When neither is set, the global callbacks fire as normal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from routerbot.observability.callbacks import (
    CallbackData,
    CallbackEvent,
    CallbackManager,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Team logging config model
# ---------------------------------------------------------------------------


@dataclass
class TeamLoggingConfig:
    """Parsed logging configuration for a single team.

    Attributes
    ----------
    disable_logging:
        When ``True``, no callbacks fire for this team.
    callbacks:
        Optional list of callback names to use instead of global.
        ``None`` means "use global callbacks".
    langfuse_public_key / langfuse_secret_key / langfuse_host:
        Per-team Langfuse credentials (overrides global).
    webhook_url / webhook_headers:
        Per-team webhook destination.
    extra:
        Any additional team-specific settings.
    """

    disable_logging: bool = False
    callbacks: list[str] | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    webhook_url: str | None = None
    webhook_headers: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


def parse_team_logging_config(settings: dict[str, Any] | None) -> TeamLoggingConfig:
    """Extract logging-related config from a team's ``settings`` JSON.

    Keys not recognised as logging config are placed into ``extra``.
    """
    if not settings:
        return TeamLoggingConfig()

    known_keys = {
        "disable_logging",
        "callbacks",
        "langfuse_public_key",
        "langfuse_secret_key",
        "langfuse_host",
        "webhook_url",
        "webhook_headers",
    }

    return TeamLoggingConfig(
        disable_logging=bool(settings.get("disable_logging", False)),
        callbacks=settings.get("callbacks"),
        langfuse_public_key=settings.get("langfuse_public_key"),
        langfuse_secret_key=settings.get("langfuse_secret_key"),
        langfuse_host=settings.get("langfuse_host"),
        webhook_url=settings.get("webhook_url"),
        webhook_headers=settings.get("webhook_headers", {}),
        extra={k: v for k, v in settings.items() if k not in known_keys},
    )


# ---------------------------------------------------------------------------
# Team-aware callback manager
# ---------------------------------------------------------------------------


class TeamCallbackManager:
    """Wraps a :class:`CallbackManager` with per-team routing logic.

    The global :class:`CallbackManager` holds all registered callback
    instances keyed by name.  This manager decides *which* of those
    callbacks to fire for a given team's request.

    Team logging config is fetched lazily from a resolver function
    (typically a DB lookup).  The resolver is called once per dispatch
    and results can be cached externally.
    """

    def __init__(
        self,
        global_manager: CallbackManager,
        *,
        team_configs: dict[str, TeamLoggingConfig] | None = None,
    ) -> None:
        self._global = global_manager
        self._team_configs: dict[str, TeamLoggingConfig] = team_configs or {}

    # ------------------------------------------------------------------
    # Config management
    # ------------------------------------------------------------------

    def set_team_config(self, team_id: str, config: TeamLoggingConfig) -> None:
        """Set or update the logging config for a team."""
        self._team_configs[team_id] = config

    def remove_team_config(self, team_id: str) -> bool:
        """Remove a team's logging config. Returns True if it existed."""
        if team_id in self._team_configs:
            del self._team_configs[team_id]
            return True
        return False

    def get_team_config(self, team_id: str) -> TeamLoggingConfig | None:
        """Get the logging config for a team (None if no override)."""
        return self._team_configs.get(team_id)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(
        self,
        event: CallbackEvent,
        data: CallbackData,
        *,
        team_id: str | None = None,
    ) -> None:
        """Dispatch a callback event respecting team-level overrides.

        Logic:
        1. If no ``team_id`` ➜ use global callbacks.
        2. If team has ``disable_logging=True`` ➜ skip all callbacks.
        3. If team has a ``callbacks`` list ➜ dispatch only those.
        4. Otherwise ➜ use global callbacks.
        """
        if team_id is None:
            await self._global.dispatch(event, data)
            return

        config = self._team_configs.get(team_id)

        # No override — fall through to global
        if config is None:
            await self._global.dispatch(event, data)
            return

        # GDPR: disable all logging
        if config.disable_logging:
            logger.debug("Logging disabled for team %s — skipping callbacks", team_id)
            return

        # Team-specific callback list
        if config.callbacks is not None:
            await self._dispatch_named(event, data, config.callbacks)
            return

        # Default: global callbacks
        await self._global.dispatch(event, data)

    async def _dispatch_named(
        self,
        event: CallbackEvent,
        data: CallbackData,
        callback_names: list[str],
    ) -> None:
        """Dispatch only to named callbacks that exist in the global manager."""
        import asyncio

        from routerbot.observability.callbacks import _EVENT_METHOD_MAP

        method_name = _EVENT_METHOD_MAP.get(event)
        if method_name is None:
            return

        tasks: list[asyncio.Task[None]] = []
        for name in callback_names:
            cb = self._global._callbacks.get(name)
            if cb is None:
                logger.warning("Team callback '%s' not registered globally", name)
                continue
            handler = getattr(cb, method_name, None)
            if handler is not None:
                tasks.append(asyncio.create_task(CallbackManager._safe_call(name, event, handler, data)))

        if tasks:
            await asyncio.gather(*tasks)
