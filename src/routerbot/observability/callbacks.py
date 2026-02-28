"""Extensible callback system for LLM request lifecycle events.

Fires asynchronous callbacks on request lifecycle events (start, end,
error, stream events).  All callbacks are dispatched in parallel via
:func:`asyncio.gather` and individually error-isolated — one failing
callback never blocks the response or affects others.

Usage::

    from routerbot.observability.callbacks import CallbackManager, CallbackEvent

    manager = CallbackManager()
    manager.register(SpendLogCallback())
    manager.register(ConsoleLogCallback())

    await manager.dispatch(CallbackEvent.REQUEST_END, data)
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class CallbackEvent(enum.StrEnum):
    """Lifecycle events that trigger callbacks."""

    REQUEST_START = "request_start"
    REQUEST_END = "request_end"
    REQUEST_ERROR = "request_error"
    STREAM_START = "stream_start"
    STREAM_CHUNK = "stream_chunk"
    STREAM_END = "stream_end"


# ---------------------------------------------------------------------------
# Callback data models
# ---------------------------------------------------------------------------


@dataclass
class RequestStartData:
    """Dispatched when a request begins processing."""

    request_id: str
    model: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    user_id: str | None = None
    team_id: str | None = None
    key_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RequestEndData:
    """Dispatched when a request completes successfully."""

    request_id: str
    model: str
    provider: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    response: dict[str, Any] = field(default_factory=dict)
    tokens_prompt: int = 0
    tokens_completion: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    user_id: str | None = None
    team_id: str | None = None
    key_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RequestErrorData:
    """Dispatched when a request fails with an error."""

    request_id: str
    model: str
    error: str = ""
    error_type: str = ""
    provider: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    user_id: str | None = None
    team_id: str | None = None
    key_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamEventData:
    """Dispatched on stream lifecycle events (start, chunk, end)."""

    request_id: str
    model: str
    chunk: dict[str, Any] = field(default_factory=dict)
    cumulative_tokens: int = 0
    is_final: bool = False
    provider: str = ""
    user_id: str | None = None
    team_id: str | None = None
    key_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


# Type alias for any callback data
CallbackData = RequestStartData | RequestEndData | RequestErrorData | StreamEventData


# ---------------------------------------------------------------------------
# Base callback ABC
# ---------------------------------------------------------------------------


class BaseCallback(ABC):
    """Abstract base for all callbacks.

    Subclasses must implement at least the three core lifecycle methods.
    Stream methods have no-op defaults since not every callback cares
    about individual chunks.
    """

    @property
    def name(self) -> str:
        """Return the callback name (used for logging and unregister)."""
        return self.__class__.__name__

    @abstractmethod
    async def on_request_start(self, data: RequestStartData) -> None:
        """Called when a request begins."""

    @abstractmethod
    async def on_request_end(self, data: RequestEndData) -> None:
        """Called when a request completes successfully."""

    @abstractmethod
    async def on_request_error(self, data: RequestErrorData) -> None:
        """Called when a request fails."""

    async def on_stream_start(self, data: StreamEventData) -> None:  # noqa: B027
        """Called when a stream begins (optional)."""

    async def on_stream_chunk(self, data: StreamEventData) -> None:  # noqa: B027
        """Called on each stream chunk (optional)."""

    async def on_stream_end(self, data: StreamEventData) -> None:  # noqa: B027
        """Called when a stream completes (optional)."""


# ---------------------------------------------------------------------------
# Callback Manager
# ---------------------------------------------------------------------------


# Mapping from event enum to the handler method name on BaseCallback
_EVENT_METHOD_MAP: dict[CallbackEvent, str] = {
    CallbackEvent.REQUEST_START: "on_request_start",
    CallbackEvent.REQUEST_END: "on_request_end",
    CallbackEvent.REQUEST_ERROR: "on_request_error",
    CallbackEvent.STREAM_START: "on_stream_start",
    CallbackEvent.STREAM_CHUNK: "on_stream_chunk",
    CallbackEvent.STREAM_END: "on_stream_end",
}


class CallbackManager:
    """Manages registration and dispatching of callbacks.

    Callbacks are invoked concurrently via :func:`asyncio.gather` with
    ``return_exceptions=True`` so that a failure in one never impacts
    the others or the main request.
    """

    def __init__(self) -> None:
        self._callbacks: dict[str, BaseCallback] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, callback: BaseCallback) -> None:
        """Register a callback instance.

        If a callback with the same name is already registered it will
        be replaced.
        """
        self._callbacks[callback.name] = callback
        logger.info("Registered callback: %s", callback.name)

    def unregister(self, name: str) -> bool:
        """Remove a callback by name.

        Returns ``True`` if the callback existed and was removed.
        """
        if name in self._callbacks:
            del self._callbacks[name]
            logger.info("Unregistered callback: %s", name)
            return True
        return False

    @property
    def registered(self) -> list[str]:
        """Return names of all registered callbacks."""
        return list(self._callbacks)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, event: CallbackEvent, data: CallbackData) -> None:
        """Dispatch *event* to all registered callbacks.

        Each callback runs concurrently.  Exceptions are caught and
        logged — they never propagate to the caller.
        """
        if not self._callbacks:
            return

        method_name = _EVENT_METHOD_MAP.get(event)
        if method_name is None:
            logger.warning("Unknown callback event: %s", event)
            return

        tasks: list[asyncio.Task[None]] = []
        for cb in self._callbacks.values():
            handler = getattr(cb, method_name, None)
            if handler is not None:
                tasks.append(asyncio.create_task(self._safe_call(cb.name, event, handler, data)))

        if tasks:
            await asyncio.gather(*tasks)

    @staticmethod
    async def _safe_call(
        name: str,
        event: CallbackEvent,
        handler: Any,
        data: CallbackData,
    ) -> None:
        """Invoke a single callback handler with error isolation."""
        try:
            await handler(data)
        except Exception:
            logger.exception("Callback '%s' failed on event '%s'", name, event)


# ---------------------------------------------------------------------------
# Built-in: Console log callback
# ---------------------------------------------------------------------------


class ConsoleLogCallback(BaseCallback):
    """Logs request lifecycle events to the console (structured logging)."""

    def __init__(self, log_level: int = logging.INFO) -> None:
        self._log_level = log_level
        self._logger = logging.getLogger("routerbot.callbacks.console")

    async def on_request_start(self, data: RequestStartData) -> None:
        self._logger.log(
            self._log_level,
            "Request started: request_id=%s model=%s user=%s",
            data.request_id,
            data.model,
            data.user_id or "-",
        )

    async def on_request_end(self, data: RequestEndData) -> None:
        self._logger.log(
            self._log_level,
            "Request completed: request_id=%s model=%s provider=%s tokens=%d/%d cost=%.6f latency=%.1fms",
            data.request_id,
            data.model,
            data.provider,
            data.tokens_prompt,
            data.tokens_completion,
            data.cost,
            data.latency_ms,
        )

    async def on_request_error(self, data: RequestErrorData) -> None:
        self._logger.warning(
            "Request error: request_id=%s model=%s provider=%s error=%s",
            data.request_id,
            data.model,
            data.provider,
            data.error,
        )


# ---------------------------------------------------------------------------
# Built-in: Spend log callback (writes to DB)
# ---------------------------------------------------------------------------


class SpendLogCallback(BaseCallback):
    """Records request cost and token usage to the ``spend_logs`` table.

    This callback requires an async session factory.  If the session
    factory is not set, the callback silently skips writes.
    """

    def __init__(self, session_factory: Any | None = None) -> None:
        self._session_factory = session_factory

    async def on_request_start(self, data: RequestStartData) -> None:
        """No-op — spend is only recorded on completion."""

    async def on_request_end(self, data: RequestEndData) -> None:
        """Write a spend log row."""
        if self._session_factory is None:
            return

        try:
            from routerbot.db.repositories.spend import SpendRepository

            async with self._session_factory() as session:
                repo = SpendRepository(session)
                await repo.create(
                    model=data.model,
                    provider=data.provider,
                    request_id=data.request_id,
                    tokens_prompt=data.tokens_prompt,
                    tokens_completion=data.tokens_completion,
                    cost=data.cost,
                )
                await session.commit()
        except Exception:
            logger.exception("SpendLogCallback: failed to write spend log")

    async def on_request_error(self, data: RequestErrorData) -> None:
        """No-op — errors don't incur cost."""
