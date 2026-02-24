"""Tests for the callback system (Task 5.1).

Covers:
- Callback registration and unregistration
- Event dispatching to all registered callbacks
- Error isolation (one failing callback doesn't affect others)
- All lifecycle event types
- Built-in ConsoleLogCallback and SpendLogCallback
- Data model construction
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routerbot.observability.callbacks import (
    BaseCallback,
    CallbackData,
    CallbackEvent,
    CallbackManager,
    ConsoleLogCallback,
    RequestEndData,
    RequestErrorData,
    RequestStartData,
    SpendLogCallback,
    StreamEventData,
)


# ---------------------------------------------------------------------------
# Test callback implementations
# ---------------------------------------------------------------------------


class RecordingCallback(BaseCallback):
    """Records every event + data for assertions."""

    def __init__(self, name: str = "RecordingCallback") -> None:
        self._name = name
        self.events: list[tuple[str, CallbackData]] = []

    @property
    def name(self) -> str:
        return self._name

    async def on_request_start(self, data: RequestStartData) -> None:
        self.events.append(("request_start", data))

    async def on_request_end(self, data: RequestEndData) -> None:
        self.events.append(("request_end", data))

    async def on_request_error(self, data: RequestErrorData) -> None:
        self.events.append(("request_error", data))

    async def on_stream_start(self, data: StreamEventData) -> None:
        self.events.append(("stream_start", data))

    async def on_stream_chunk(self, data: StreamEventData) -> None:
        self.events.append(("stream_chunk", data))

    async def on_stream_end(self, data: StreamEventData) -> None:
        self.events.append(("stream_end", data))


class FailingCallback(BaseCallback):
    """Always raises on every event."""

    async def on_request_start(self, data: RequestStartData) -> None:
        msg = "deliberate failure"
        raise RuntimeError(msg)

    async def on_request_end(self, data: RequestEndData) -> None:
        msg = "deliberate failure"
        raise RuntimeError(msg)

    async def on_request_error(self, data: RequestErrorData) -> None:
        msg = "deliberate failure"
        raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Test: Registration
# ---------------------------------------------------------------------------


class TestCallbackRegistration:
    """Register and unregister callbacks."""

    def test_register(self):
        mgr = CallbackManager()
        cb = RecordingCallback()
        mgr.register(cb)
        assert "RecordingCallback" in mgr.registered

    def test_register_replaces_same_name(self):
        mgr = CallbackManager()
        cb1 = RecordingCallback()
        cb2 = RecordingCallback()
        mgr.register(cb1)
        mgr.register(cb2)
        assert len(mgr.registered) == 1

    def test_unregister(self):
        mgr = CallbackManager()
        cb = RecordingCallback()
        mgr.register(cb)
        assert mgr.unregister("RecordingCallback") is True
        assert mgr.registered == []

    def test_unregister_nonexistent(self):
        mgr = CallbackManager()
        assert mgr.unregister("DoesNotExist") is False

    def test_registered_names(self):
        mgr = CallbackManager()
        mgr.register(RecordingCallback("A"))
        mgr.register(RecordingCallback("B"))
        assert set(mgr.registered) == {"A", "B"}


# ---------------------------------------------------------------------------
# Test: Dispatch
# ---------------------------------------------------------------------------


class TestCallbackDispatch:
    """Events are dispatched to all registered callbacks."""

    async def test_dispatch_request_start(self):
        mgr = CallbackManager()
        cb = RecordingCallback()
        mgr.register(cb)
        data = RequestStartData(request_id="r1", model="gpt-4")
        await mgr.dispatch(CallbackEvent.REQUEST_START, data)
        assert len(cb.events) == 1
        assert cb.events[0] == ("request_start", data)

    async def test_dispatch_request_end(self):
        mgr = CallbackManager()
        cb = RecordingCallback()
        mgr.register(cb)
        data = RequestEndData(
            request_id="r1",
            model="gpt-4",
            provider="openai",
            tokens_prompt=100,
            tokens_completion=50,
            cost=0.01,
            latency_ms=250.5,
        )
        await mgr.dispatch(CallbackEvent.REQUEST_END, data)
        assert cb.events[0][0] == "request_end"

    async def test_dispatch_request_error(self):
        mgr = CallbackManager()
        cb = RecordingCallback()
        mgr.register(cb)
        data = RequestErrorData(
            request_id="r1",
            model="gpt-4",
            error="timeout",
            error_type="TimeoutError",
        )
        await mgr.dispatch(CallbackEvent.REQUEST_ERROR, data)
        assert cb.events[0][0] == "request_error"

    async def test_dispatch_stream_events(self):
        mgr = CallbackManager()
        cb = RecordingCallback()
        mgr.register(cb)

        data = StreamEventData(request_id="r1", model="gpt-4")
        await mgr.dispatch(CallbackEvent.STREAM_START, data)
        await mgr.dispatch(CallbackEvent.STREAM_CHUNK, data)
        await mgr.dispatch(CallbackEvent.STREAM_END, data)

        assert [e[0] for e in cb.events] == ["stream_start", "stream_chunk", "stream_end"]

    async def test_dispatch_to_multiple_callbacks(self):
        mgr = CallbackManager()
        cb1 = RecordingCallback("A")
        cb2 = RecordingCallback("B")
        mgr.register(cb1)
        mgr.register(cb2)
        data = RequestStartData(request_id="r1", model="gpt-4")
        await mgr.dispatch(CallbackEvent.REQUEST_START, data)
        assert len(cb1.events) == 1
        assert len(cb2.events) == 1

    async def test_dispatch_no_callbacks(self):
        """Dispatch with no callbacks is a no-op."""
        mgr = CallbackManager()
        data = RequestStartData(request_id="r1", model="gpt-4")
        await mgr.dispatch(CallbackEvent.REQUEST_START, data)  # Should not raise


# ---------------------------------------------------------------------------
# Test: Error isolation
# ---------------------------------------------------------------------------


class TestCallbackErrorIsolation:
    """One callback failing must not affect others."""

    async def test_failing_callback_doesnt_break_others(self):
        mgr = CallbackManager()
        failing = FailingCallback()
        recording = RecordingCallback()
        mgr.register(failing)
        mgr.register(recording)
        data = RequestStartData(request_id="r1", model="gpt-4")
        await mgr.dispatch(CallbackEvent.REQUEST_START, data)
        # Recording callback still received the event
        assert len(recording.events) == 1

    async def test_failing_callback_logs_exception(self):
        mgr = CallbackManager()
        mgr.register(FailingCallback())
        data = RequestEndData(request_id="r1", model="gpt-4")
        with patch("routerbot.observability.callbacks.logger") as mock_logger:
            await mgr.dispatch(CallbackEvent.REQUEST_END, data)
            mock_logger.exception.assert_called_once()


# ---------------------------------------------------------------------------
# Test: Data models
# ---------------------------------------------------------------------------


class TestDataModels:
    """Data model fields and defaults."""

    def test_request_start_defaults(self):
        d = RequestStartData(request_id="r1", model="gpt-4")
        assert d.messages == []
        assert d.user_id is None
        assert d.team_id is None
        assert d.key_id is None
        assert d.timestamp > 0
        assert d.metadata == {}

    def test_request_end_defaults(self):
        d = RequestEndData(request_id="r1", model="gpt-4")
        assert d.tokens_prompt == 0
        assert d.tokens_completion == 0
        assert d.cost == 0.0
        assert d.latency_ms == 0.0
        assert d.provider == ""

    def test_request_error_fields(self):
        d = RequestErrorData(
            request_id="r1",
            model="gpt-4",
            error="connection reset",
            error_type="ConnectionError",
            provider="openai",
        )
        assert d.error == "connection reset"
        assert d.error_type == "ConnectionError"

    def test_stream_event_data(self):
        d = StreamEventData(
            request_id="r1",
            model="gpt-4",
            chunk={"delta": {"content": "hello"}},
            cumulative_tokens=42,
            is_final=True,
        )
        assert d.cumulative_tokens == 42
        assert d.is_final is True


# ---------------------------------------------------------------------------
# Test: ConsoleLogCallback
# ---------------------------------------------------------------------------


class TestConsoleLogCallback:
    """Built-in console logging callback."""

    async def test_request_start_logs(self):
        cb = ConsoleLogCallback()
        data = RequestStartData(request_id="r1", model="gpt-4", user_id="u1")
        with patch.object(cb, "_logger") as mock_log:
            await cb.on_request_start(data)
            mock_log.log.assert_called_once()

    async def test_request_end_logs(self):
        cb = ConsoleLogCallback()
        data = RequestEndData(
            request_id="r1",
            model="gpt-4",
            provider="openai",
            tokens_prompt=100,
            tokens_completion=50,
            cost=0.01,
            latency_ms=250.0,
        )
        with patch.object(cb, "_logger") as mock_log:
            await cb.on_request_end(data)
            mock_log.log.assert_called_once()

    async def test_request_error_logs_warning(self):
        cb = ConsoleLogCallback()
        data = RequestErrorData(request_id="r1", model="gpt-4", error="boom")
        with patch.object(cb, "_logger") as mock_log:
            await cb.on_request_error(data)
            mock_log.warning.assert_called_once()


# ---------------------------------------------------------------------------
# Test: SpendLogCallback
# ---------------------------------------------------------------------------


class TestSpendLogCallback:
    """Built-in spend log callback."""

    async def test_no_session_factory_is_noop(self):
        """Without session factory, on_request_end is a no-op."""
        cb = SpendLogCallback(session_factory=None)
        data = RequestEndData(request_id="r1", model="gpt-4")
        await cb.on_request_end(data)  # Should not raise

    async def test_request_start_is_noop(self):
        """on_request_start does nothing."""
        cb = SpendLogCallback()
        data = RequestStartData(request_id="r1", model="gpt-4")
        await cb.on_request_start(data)  # Should not raise

    async def test_request_error_is_noop(self):
        """on_request_error does nothing."""
        cb = SpendLogCallback()
        data = RequestErrorData(request_id="r1", model="gpt-4")
        await cb.on_request_error(data)  # Should not raise


# ---------------------------------------------------------------------------
# Test: CallbackEvent enum
# ---------------------------------------------------------------------------


class TestCallbackEvent:
    """Event enum coverage."""

    def test_all_events_have_handler_mapping(self):
        from routerbot.observability.callbacks import _EVENT_METHOD_MAP

        for event in CallbackEvent:
            assert event in _EVENT_METHOD_MAP, f"Missing mapping for {event}"

    def test_event_values(self):
        assert CallbackEvent.REQUEST_START == "request_start"
        assert CallbackEvent.REQUEST_END == "request_end"
        assert CallbackEvent.REQUEST_ERROR == "request_error"
        assert CallbackEvent.STREAM_START == "stream_start"
        assert CallbackEvent.STREAM_CHUNK == "stream_chunk"
        assert CallbackEvent.STREAM_END == "stream_end"
