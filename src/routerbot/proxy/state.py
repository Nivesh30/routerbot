"""Application state container for RouterBot.

Holds the singleton objects that are shared across all requests:
router, config, and optional Redis/DB connections.  Exposed to
FastAPI routes via ``Depends(get_*)``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from routerbot.core.config_models import RouterBotConfig


class AppState:
    """Mutable application-wide state attached to ``app.state``."""

    def __init__(self) -> None:
        self.config: RouterBotConfig | None = None
        self._router: Any = None  # Will be RouterBot router (Stage 3.3)
        self._redis: Any = None
        self._db: Any = None

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def router(self) -> Any:
        return self._router

    @router.setter
    def router(self, value: Any) -> None:
        self._router = value

    @property
    def redis(self) -> Any:
        return self._redis

    @redis.setter
    def redis(self, value: Any) -> None:
        self._redis = value

    @property
    def db(self) -> Any:
        return self._db

    @db.setter
    def db(self, value: Any) -> None:
        self._db = value

    def is_ready(self) -> bool:
        """Return True when the application is fully initialized."""
        return self.config is not None
