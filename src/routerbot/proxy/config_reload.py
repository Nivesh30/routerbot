"""Configuration hot-reload for RouterBot.

Watches the config file for changes and triggers a reload without
requiring a server restart.  Also exposes a manual reload endpoint
helper.

Usage::

    from routerbot.proxy.config_reload import ConfigWatcher

    watcher = ConfigWatcher(config_path="routerbot_config.yaml", on_reload=callback)
    await watcher.start()
    ...
    await watcher.stop()
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from routerbot.core.config_models import RouterBotConfig

logger = logging.getLogger(__name__)


def _file_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's contents."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


class ConfigWatcher:
    """Asyncio-based file watcher that reloads config on change.

    Polls the config file every *poll_interval* seconds.  When a change
    is detected (via SHA-256 hash comparison), it:

    1. Loads and validates the new config.
    2. Calls *on_reload* with the validated config.
    3. On validation failure, logs an error and keeps the old config.

    Parameters
    ----------
    config_path:
        Path to ``routerbot_config.yaml``.
    on_reload:
        Async callback invoked with the validated :class:`RouterBotConfig`
        when a change is detected.
    poll_interval:
        How often (in seconds) to check the file for changes.  Defaults
        to 5 seconds.
    """

    def __init__(
        self,
        config_path: str | Path,
        on_reload: Callable[[RouterBotConfig], Awaitable[None]],
        poll_interval: float = 5.0,
    ) -> None:
        self._path = Path(config_path)
        self._on_reload = on_reload
        self._poll_interval = poll_interval
        self._last_hash: str = ""
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background file-watcher task."""
        if self._task is not None and not self._task.done():
            logger.debug("ConfigWatcher already running")
            return
        # Prime the initial hash so we don't immediately trigger on startup
        self._last_hash = _file_hash(self._path)
        self._task = asyncio.create_task(self._watch_loop(), name="routerbot-config-watcher")
        logger.info(
            "ConfigWatcher started (path=%s, interval=%.1fs)",
            self._path,
            self._poll_interval,
        )

    async def stop(self) -> None:
        """Cancel the background file-watcher task."""
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
        logger.info("ConfigWatcher stopped")

    @property
    def is_running(self) -> bool:
        """``True`` if the background task is alive."""
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _watch_loop(self) -> None:
        """Poll the config file for changes forever."""
        while True:
            await asyncio.sleep(self._poll_interval)
            try:
                current_hash = _file_hash(self._path)
                if current_hash and current_hash != self._last_hash:
                    logger.info("Config file changed (%s) — reloading…", self._path)
                    await self._reload(current_hash)
            except Exception:
                logger.exception("Error in ConfigWatcher poll loop — continuing")

    async def _reload(self, new_hash: str) -> None:
        """Load, validate, and apply the new config."""
        from routerbot.core.config import load_config

        try:
            new_config = load_config(self._path)
        except Exception as exc:
            logger.error("Config reload failed — validation error, keeping old config: %s", exc)
            return

        self._last_hash = new_hash
        try:
            await self._on_reload(new_config)
            logger.info("Config reloaded successfully")
        except Exception as exc:
            logger.error("Config reload callback raised: %s", exc)

    # ------------------------------------------------------------------
    # Manual reload
    # ------------------------------------------------------------------

    async def reload_now(self) -> RouterBotConfig:
        """Force an immediate reload of the config file.

        Returns
        -------
        RouterBotConfig
            The newly-loaded and validated configuration.

        Raises
        ------
        Exception
            If the config file cannot be loaded or is invalid.
        """
        from routerbot.core.config import load_config

        new_config = load_config(self._path)
        new_hash = _file_hash(self._path)
        self._last_hash = new_hash
        await self._on_reload(new_config)
        logger.info("Manual config reload triggered")
        return new_config


def compute_config_hash(config: RouterBotConfig) -> str:
    """Return a short hash fingerprint of a config for change detection.

    Parameters
    ----------
    config:
        The config to fingerprint.

    Returns
    -------
    str
        First 12 characters of the SHA-256 hash of the JSON representation.
    """
    config_json = config.model_dump_json()
    return hashlib.sha256(config_json.encode()).hexdigest()[:12]
