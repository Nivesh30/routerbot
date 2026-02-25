"""Tests for the webhook callback system (Task 5.7).

Covers:
- WebhookConfig creation
- WebhookEvent creation
- WebhookDelivery batching, flushing, retry, HMAC signing
- WebhookCallback event dispatch and filtering
- create_webhook_callback factory
- Error isolation and graceful degradation
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from routerbot.observability.callbacks import (
    RequestEndData,
    RequestErrorData,
    RequestStartData,
    StreamEventData,
)
from routerbot.observability.webhooks import (
    WebhookCallback,
    WebhookConfig,
    WebhookDelivery,
    WebhookEvent,
    _callback_data_to_dict,
    create_webhook_callback,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

WEBHOOK_URL = "https://hooks.example.com/events"


@pytest.fixture()
def webhook_config() -> WebhookConfig:
    """Minimal webhook config."""
    return WebhookConfig(url=WEBHOOK_URL)


@pytest.fixture()
def signed_config() -> WebhookConfig:
    """Config with HMAC signing enabled."""
    return WebhookConfig(
        url=WEBHOOK_URL,
        secret="test-webhook-secret",
        headers={"Authorization": "Bearer test-token"},
    )


@pytest.fixture()
def batch_config() -> WebhookConfig:
    """Config with batch mode enabled."""
    return WebhookConfig(
        url=WEBHOOK_URL,
        batch_size=5,
        flush_interval=60.0,  # long interval so timer doesn't fire
    )


@pytest.fixture()
def filtered_config() -> WebhookConfig:
    """Config with event filtering."""
    return WebhookConfig(
        url=WEBHOOK_URL,
        events=["request.completed", "request.failed"],
    )


def _make_start_data(**kwargs: Any) -> RequestStartData:
    return RequestStartData(
        request_id=kwargs.get("request_id", "req-001"),
        model=kwargs.get("model", "gpt-4"),
        messages=kwargs.get("messages", [{"role": "user", "content": "hello"}]),
        user_id=kwargs.get("user_id", "user-1"),
        team_id=kwargs.get("team_id", "team-1"),
    )


def _make_end_data(**kwargs: Any) -> RequestEndData:
    return RequestEndData(
        request_id=kwargs.get("request_id", "req-001"),
        model=kwargs.get("model", "gpt-4"),
        provider=kwargs.get("provider", "openai"),
        tokens_prompt=kwargs.get("tokens_prompt", 10),
        tokens_completion=kwargs.get("tokens_completion", 20),
        cost=kwargs.get("cost", 0.001),
        latency_ms=kwargs.get("latency_ms", 150.0),
    )


def _make_error_data(**kwargs: Any) -> RequestErrorData:
    return RequestErrorData(
        request_id=kwargs.get("request_id", "req-001"),
        model=kwargs.get("model", "gpt-4"),
        error=kwargs.get("error", "Rate limit exceeded"),
        error_type=kwargs.get("error_type", "RateLimitError"),
        provider=kwargs.get("provider", "openai"),
    )


def _make_stream_data(**kwargs: Any) -> StreamEventData:
    return StreamEventData(
        request_id=kwargs.get("request_id", "req-001"),
        model=kwargs.get("model", "gpt-4"),
        chunk=kwargs.get("chunk", {"content": "hi"}),
        cumulative_tokens=kwargs.get("cumulative_tokens", 5),
        provider=kwargs.get("provider", "openai"),
    )


# ===================================================================
# WebhookConfig Tests
# ===================================================================


class TestWebhookConfig:
    """Tests for WebhookConfig dataclass."""

    def test_minimal_config(self) -> None:
        config = WebhookConfig(url="https://example.com/hook")
        assert config.url == "https://example.com/hook"
        assert config.headers == {}
        assert config.secret is None
        assert config.batch_size == 1
        assert config.max_retries == 3
        assert config.events is None

    def test_full_config(self) -> None:
        config = WebhookConfig(
            url="https://example.com/hook",
            headers={"X-Custom": "value"},
            secret="my-secret",
            batch_size=10,
            flush_interval=15.0,
            timeout=5.0,
            max_retries=5,
            events=["request.completed"],
        )
        assert config.secret == "my-secret"
        assert config.batch_size == 10
        assert config.flush_interval == 15.0
        assert config.events == ["request.completed"]


# ===================================================================
# WebhookEvent Tests
# ===================================================================


class TestWebhookEvent:
    """Tests for WebhookEvent dataclass."""

    def test_defaults(self) -> None:
        ev = WebhookEvent(event_type="request.completed")
        assert ev.event_type == "request.completed"
        assert ev.event_id  # UUID generated
        assert ev.timestamp > 0
        assert ev.data == {}

    def test_custom_data(self) -> None:
        ev = WebhookEvent(
            event_type="request.failed",
            event_id="custom-id",
            data={"error": "timeout"},
        )
        assert ev.event_id == "custom-id"
        assert ev.data == {"error": "timeout"}


# ===================================================================
# WebhookDelivery Tests
# ===================================================================


class TestWebhookDelivery:
    """Tests for the delivery engine."""

    @respx.mock
    @pytest.mark.asyncio()
    async def test_successful_delivery(self, webhook_config: WebhookConfig) -> None:
        """Events are delivered via HTTP POST."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(webhook_config)
        await delivery.start()

        event = WebhookEvent(event_type="request.completed", data={"model": "gpt-4"})
        await delivery.enqueue(event)

        # batch_size=1 → immediate flush
        assert route.called
        assert delivery.total_delivered == 1
        assert delivery.total_failed == 0

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_payload_structure(self, webhook_config: WebhookConfig) -> None:
        """Verify the JSON payload structure sent to the webhook."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(webhook_config)
        await delivery.start()

        event = WebhookEvent(
            event_type="request.completed",
            event_id="evt-123",
            timestamp=1700000000.0,
            data={"model": "gpt-4"},
        )
        await delivery.enqueue(event)

        body = json.loads(route.calls.last.request.content)
        assert "events" in body
        assert len(body["events"]) == 1
        assert body["events"][0]["event_type"] == "request.completed"
        assert body["events"][0]["event_id"] == "evt-123"
        assert body["batch_size"] == 1
        assert "sent_at" in body

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_custom_headers(self) -> None:
        """Custom headers are included in the request."""
        config = WebhookConfig(
            url=WEBHOOK_URL,
            headers={"Authorization": "Bearer secret-token", "X-Team": "frontend"},
        )
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(config)
        await delivery.start()

        await delivery.enqueue(WebhookEvent(event_type="test"))

        req = route.calls.last.request
        assert req.headers["Authorization"] == "Bearer secret-token"
        assert req.headers["X-Team"] == "frontend"
        assert req.headers["Content-Type"] == "application/json"
        assert req.headers["User-Agent"] == "RouterBot-Webhook/1.0"

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_hmac_signature(self, signed_config: WebhookConfig) -> None:
        """HMAC-SHA256 signature header is sent when secret is configured."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(signed_config)
        await delivery.start()

        await delivery.enqueue(WebhookEvent(event_type="request.completed"))

        req = route.calls.last.request
        sig_header = req.headers.get("X-RouterBot-Signature", "")
        assert sig_header.startswith("sha256=")

        # Verify the signature
        expected = hmac.new(
            signed_config.secret.encode(),
            req.content,
            hashlib.sha256,
        ).hexdigest()
        assert sig_header == f"sha256={expected}"

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_no_signature_without_secret(self, webhook_config: WebhookConfig) -> None:
        """No signature header when no secret is configured."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(webhook_config)
        await delivery.start()

        await delivery.enqueue(WebhookEvent(event_type="test"))

        req = route.calls.last.request
        assert "X-RouterBot-Signature" not in req.headers

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_batch_mode(self, batch_config: WebhookConfig) -> None:
        """Events accumulate until batch_size is reached."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(batch_config)
        await delivery.start()

        # Add 4 events (below batch_size=5)
        for i in range(4):
            await delivery.enqueue(WebhookEvent(event_type="test", event_id=f"evt-{i}"))

        assert not route.called
        assert delivery.pending_count == 4

        # Add 5th event → triggers flush
        await delivery.enqueue(WebhookEvent(event_type="test", event_id="evt-4"))

        assert route.called
        body = json.loads(route.calls.last.request.content)
        assert body["batch_size"] == 5
        assert len(body["events"]) == 5
        assert delivery.total_delivered == 5

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_manual_flush(self, batch_config: WebhookConfig) -> None:
        """Manual flush sends enqueued events regardless of batch size."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(batch_config)
        await delivery.start()

        await delivery.enqueue(WebhookEvent(event_type="test"))
        await delivery.enqueue(WebhookEvent(event_type="test"))
        assert not route.called

        await delivery.flush()
        assert route.called
        body = json.loads(route.calls.last.request.content)
        assert body["batch_size"] == 2

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_flush_empty_queue_noop(self, webhook_config: WebhookConfig) -> None:
        """Flushing an empty queue does nothing."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(webhook_config)
        await delivery.start()

        await delivery.flush()
        assert not route.called

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_retry_on_server_error(self) -> None:
        """5xx errors trigger retries with back-off."""
        config = WebhookConfig(url=WEBHOOK_URL, max_retries=3)
        route = respx.post(WEBHOOK_URL).mock(
            side_effect=[
                httpx.Response(500, text="Internal Server Error"),
                httpx.Response(502, text="Bad Gateway"),
                httpx.Response(200),
            ]
        )

        delivery = WebhookDelivery(config)
        await delivery.start()

        with patch("routerbot.observability.webhooks.asyncio.sleep", new_callable=AsyncMock):
            await delivery.enqueue(WebhookEvent(event_type="test"))

        assert route.call_count == 3
        assert delivery.total_delivered == 1
        assert delivery.total_retried == 2

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_retry_on_429(self) -> None:
        """429 Too Many Requests triggers retries."""
        config = WebhookConfig(url=WEBHOOK_URL, max_retries=2)
        route = respx.post(WEBHOOK_URL).mock(
            side_effect=[
                httpx.Response(429, text="Rate limited"),
                httpx.Response(200),
            ]
        )

        delivery = WebhookDelivery(config)
        await delivery.start()

        with patch("routerbot.observability.webhooks.asyncio.sleep", new_callable=AsyncMock):
            await delivery.enqueue(WebhookEvent(event_type="test"))

        assert route.call_count == 2
        assert delivery.total_delivered == 1

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_no_retry_on_client_error(self) -> None:
        """4xx errors (except 429) do NOT trigger retries."""
        config = WebhookConfig(url=WEBHOOK_URL, max_retries=3)
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(400, text="Bad Request"))

        delivery = WebhookDelivery(config)
        await delivery.start()

        await delivery.enqueue(WebhookEvent(event_type="test"))

        assert route.call_count == 1  # no retries
        assert delivery.total_failed == 1

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_no_retry_on_404(self) -> None:
        """404 is a client error — no retry."""
        config = WebhookConfig(url=WEBHOOK_URL, max_retries=3)
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(404, text="Not Found"))

        delivery = WebhookDelivery(config)
        await delivery.start()

        await delivery.enqueue(WebhookEvent(event_type="test"))

        assert route.call_count == 1
        assert delivery.total_failed == 1

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_max_retries_exhausted(self) -> None:
        """After exhausting retries, events are dropped and counted as failed."""
        config = WebhookConfig(url=WEBHOOK_URL, max_retries=2)
        respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(500, text="Error"))

        delivery = WebhookDelivery(config)
        await delivery.start()

        with patch("routerbot.observability.webhooks.asyncio.sleep", new_callable=AsyncMock):
            await delivery.enqueue(WebhookEvent(event_type="test"))

        assert delivery.total_failed == 1
        assert delivery.total_delivered == 0

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_retry_on_network_error(self) -> None:
        """Network errors trigger retries."""
        config = WebhookConfig(url=WEBHOOK_URL, max_retries=2)
        respx.post(WEBHOOK_URL).mock(
            side_effect=[
                httpx.ConnectError("Connection refused"),
                httpx.Response(200),
            ]
        )

        delivery = WebhookDelivery(config)
        await delivery.start()

        with patch("routerbot.observability.webhooks.asyncio.sleep", new_callable=AsyncMock):
            await delivery.enqueue(WebhookEvent(event_type="test"))

        assert delivery.total_delivered == 1
        assert delivery.total_retried == 1

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_network_error_all_retries_fail(self) -> None:
        """If all retries fail with network errors, events are dropped."""
        config = WebhookConfig(url=WEBHOOK_URL, max_retries=2)
        respx.post(WEBHOOK_URL).mock(side_effect=httpx.ConnectError("Connection refused"))

        delivery = WebhookDelivery(config)
        await delivery.start()

        with patch("routerbot.observability.webhooks.asyncio.sleep", new_callable=AsyncMock):
            await delivery.enqueue(WebhookEvent(event_type="test"))

        assert delivery.total_failed == 1
        assert delivery.total_retried == 2

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_shutdown_flushes_remaining(self, batch_config: WebhookConfig) -> None:
        """Shutdown flushes any remaining events in the queue."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(batch_config)
        await delivery.start()

        await delivery.enqueue(WebhookEvent(event_type="test"))
        await delivery.enqueue(WebhookEvent(event_type="test"))
        assert not route.called

        await delivery.shutdown()
        assert route.called
        assert delivery.total_delivered == 2

    @pytest.mark.asyncio()
    async def test_no_http_client_drops_events(self, webhook_config: WebhookConfig) -> None:
        """When no HTTP client is available, events are silently dropped."""
        delivery = WebhookDelivery(webhook_config)
        # Don't call start() → no HTTP client

        await delivery.enqueue(WebhookEvent(event_type="test"))
        # Should not raise — just logs a warning

    @respx.mock
    @pytest.mark.asyncio()
    async def test_exponential_backoff(self) -> None:
        """Verify back-off doubles between retries."""
        config = WebhookConfig(url=WEBHOOK_URL, max_retries=3)
        respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(500, text="Error"))

        delivery = WebhookDelivery(config)
        await delivery.start()

        sleep_calls: list[float] = []

        async def mock_sleep(duration: float) -> None:
            sleep_calls.append(duration)

        with patch("routerbot.observability.webhooks.asyncio.sleep", side_effect=mock_sleep):
            await delivery.enqueue(WebhookEvent(event_type="test"))

        # Initial backoff=1.0, then 2.0
        assert len(sleep_calls) == 2
        assert sleep_calls[0] == 1.0
        assert sleep_calls[1] == 2.0

        await delivery.shutdown()


# ===================================================================
# WebhookCallback Tests
# ===================================================================


class TestWebhookCallback:
    """Tests for the WebhookCallback BaseCallback implementation."""

    @respx.mock
    @pytest.mark.asyncio()
    async def test_on_request_start(self, webhook_config: WebhookConfig) -> None:
        """request.start events are delivered."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(webhook_config)

        await cb.on_request_start(_make_start_data())

        body = json.loads(route.calls.last.request.content)
        event = body["events"][0]
        assert event["event_type"] == "request.start"
        assert event["data"]["request_id"] == "req-001"
        assert event["data"]["model"] == "gpt-4"

        await cb.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_on_request_end(self, webhook_config: WebhookConfig) -> None:
        """request.completed events are delivered."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(webhook_config)

        await cb.on_request_end(_make_end_data())

        body = json.loads(route.calls.last.request.content)
        event = body["events"][0]
        assert event["event_type"] == "request.completed"
        assert event["data"]["provider"] == "openai"
        assert event["data"]["cost"] == 0.001

        await cb.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_on_request_error(self, webhook_config: WebhookConfig) -> None:
        """request.failed events are delivered."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(webhook_config)

        await cb.on_request_error(_make_error_data())

        body = json.loads(route.calls.last.request.content)
        event = body["events"][0]
        assert event["event_type"] == "request.failed"
        assert event["data"]["error"] == "Rate limit exceeded"

        await cb.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_on_stream_start(self, webhook_config: WebhookConfig) -> None:
        """stream.start events are delivered."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(webhook_config)

        await cb.on_stream_start(_make_stream_data())

        body = json.loads(route.calls.last.request.content)
        assert body["events"][0]["event_type"] == "stream.start"

        await cb.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_on_stream_chunk(self, webhook_config: WebhookConfig) -> None:
        """stream.chunk events are delivered when not filtered."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(webhook_config)

        await cb.on_stream_chunk(_make_stream_data())

        body = json.loads(route.calls.last.request.content)
        assert body["events"][0]["event_type"] == "stream.chunk"

        await cb.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_on_stream_end(self, webhook_config: WebhookConfig) -> None:
        """stream.end events are delivered."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(webhook_config)

        await cb.on_stream_end(_make_stream_data(is_final=True))

        body = json.loads(route.calls.last.request.content)
        assert body["events"][0]["event_type"] == "stream.end"

        await cb.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_event_filtering_allows(self, filtered_config: WebhookConfig) -> None:
        """Only configured event types are sent."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(filtered_config)

        # request.completed is in the filter → should send
        await cb.on_request_end(_make_end_data())
        assert route.called

        await cb.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_event_filtering_blocks(self, filtered_config: WebhookConfig) -> None:
        """Filtered-out event types are not sent."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(filtered_config)

        # request.start is NOT in the filter → should NOT send
        await cb.on_request_start(_make_start_data())
        assert not route.called

        # stream events are NOT in the filter → should NOT send
        await cb.on_stream_start(_make_stream_data())
        assert not route.called

        await cb.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_no_filter_sends_all(self, webhook_config: WebhookConfig) -> None:
        """When events=None, all event types are sent."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(webhook_config)

        await cb.on_request_start(_make_start_data())
        await cb.on_request_end(_make_end_data())
        await cb.on_request_error(_make_error_data())

        assert route.call_count == 3

        await cb.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_lazy_start(self, webhook_config: WebhookConfig) -> None:
        """Delivery client is started on first event."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(webhook_config)

        assert not cb._started
        await cb.on_request_end(_make_end_data())
        assert cb._started
        assert route.called

        await cb.shutdown()
        assert not cb._started

    @respx.mock
    @pytest.mark.asyncio()
    async def test_callback_name(self, webhook_config: WebhookConfig) -> None:
        """Callback name is 'WebhookCallback'."""
        cb = WebhookCallback(webhook_config)
        assert cb.name == "WebhookCallback"

    @respx.mock
    @pytest.mark.asyncio()
    async def test_delivery_stats_accessible(self, webhook_config: WebhookConfig) -> None:
        """Delivery statistics are accessible via .delivery property."""
        respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(webhook_config)

        await cb.on_request_end(_make_end_data())
        assert cb.delivery.total_delivered == 1
        assert cb.delivery.total_failed == 0

        await cb.shutdown()


# ===================================================================
# Integration with CallbackManager Tests
# ===================================================================


class TestWebhookWithCallbackManager:
    """Test that WebhookCallback integrates with the CallbackManager."""

    @respx.mock
    @pytest.mark.asyncio()
    async def test_register_and_dispatch(self, webhook_config: WebhookConfig) -> None:
        """WebhookCallback works when dispatched via CallbackManager."""
        from routerbot.observability.callbacks import CallbackEvent, CallbackManager

        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        manager = CallbackManager()
        cb = WebhookCallback(webhook_config)
        manager.register(cb)

        data = _make_end_data()
        await manager.dispatch(CallbackEvent.REQUEST_END, data)

        assert route.called
        body = json.loads(route.calls.last.request.content)
        assert body["events"][0]["event_type"] == "request.completed"

        await cb.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_error_isolation(self, webhook_config: WebhookConfig) -> None:
        """Webhook failure doesn't affect other callbacks."""
        from routerbot.observability.callbacks import (
            CallbackEvent,
            CallbackManager,
            ConsoleLogCallback,
        )

        # Webhook that fails
        respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(500))

        manager = CallbackManager()
        failing_cb = WebhookCallback(
            WebhookConfig(url=WEBHOOK_URL, max_retries=1),
        )
        console_cb = ConsoleLogCallback()
        manager.register(failing_cb)
        manager.register(console_cb)

        # Should not raise
        with patch("routerbot.observability.webhooks.asyncio.sleep", new_callable=AsyncMock):
            await manager.dispatch(CallbackEvent.REQUEST_END, _make_end_data())

        await failing_cb.shutdown()


# ===================================================================
# HMAC Signature Verification Tests
# ===================================================================


class TestHMACSignature:
    """Detailed tests for HMAC signing behavior."""

    @respx.mock
    @pytest.mark.asyncio()
    async def test_signature_verifiable(self) -> None:
        """A receiver can verify the signature using the shared secret."""
        secret = "my-webhook-secret"
        config = WebhookConfig(url=WEBHOOK_URL, secret=secret)
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))

        delivery = WebhookDelivery(config)
        await delivery.start()
        await delivery.enqueue(WebhookEvent(event_type="test", data={"key": "value"}))

        req = route.calls.last.request
        sig = req.headers["X-RouterBot-Signature"]
        assert sig.startswith("sha256=")

        # Receiver-side verification
        raw_body = req.content
        expected_sig = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        assert sig == f"sha256={expected_sig}"

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_different_secrets_different_signatures(self) -> None:
        """Different secrets produce different signatures for the same payload."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))

        sigs: list[str] = []
        for secret in ("secret-a", "secret-b"):
            config = WebhookConfig(url=WEBHOOK_URL, secret=secret)
            delivery = WebhookDelivery(config)
            await delivery.start()
            await delivery.enqueue(
                WebhookEvent(event_type="test", event_id="same-id", timestamp=1700000000.0)
            )
            sigs.append(route.calls.last.request.headers["X-RouterBot-Signature"])
            await delivery.shutdown()

        assert sigs[0] != sigs[1]


# ===================================================================
# Batch Mode Tests
# ===================================================================


class TestBatchMode:
    """Tests for batch accumulation behavior."""

    @respx.mock
    @pytest.mark.asyncio()
    async def test_events_below_threshold_stay_queued(self) -> None:
        """Events below batch_size stay in queue."""
        config = WebhookConfig(url=WEBHOOK_URL, batch_size=10, flush_interval=60.0)
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(config)
        await delivery.start()

        for i in range(9):
            await delivery.enqueue(WebhookEvent(event_type="test", event_id=f"evt-{i}"))

        assert not route.called
        assert delivery.pending_count == 9

        await delivery.shutdown()  # flush on shutdown
        assert route.called

    @respx.mock
    @pytest.mark.asyncio()
    async def test_multiple_batches(self) -> None:
        """Multiple batch flushes work correctly."""
        config = WebhookConfig(url=WEBHOOK_URL, batch_size=3, flush_interval=60.0)
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(config)
        await delivery.start()

        # Send 7 events → 2 auto-flushes (at 3 and 6) + 1 remaining
        for i in range(7):
            await delivery.enqueue(WebhookEvent(event_type="test", event_id=f"evt-{i}"))

        assert route.call_count == 2
        assert delivery.pending_count == 1

        await delivery.shutdown()  # flush remaining 1
        assert route.call_count == 3
        assert delivery.total_delivered == 7

    @respx.mock
    @pytest.mark.asyncio()
    async def test_periodic_flush_fires(self) -> None:
        """The periodic flush timer fires and delivers queued events."""
        config = WebhookConfig(url=WEBHOOK_URL, batch_size=100, flush_interval=0.1)
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(config)
        await delivery.start()

        await delivery.enqueue(WebhookEvent(event_type="test"))

        # Wait for the periodic flush
        await asyncio.sleep(0.3)

        assert route.called
        assert delivery.total_delivered == 1

        await delivery.shutdown()


# ===================================================================
# Factory Function Tests
# ===================================================================


class TestCreateWebhookCallback:
    """Tests for the create_webhook_callback factory."""

    def test_minimal(self) -> None:
        cb = create_webhook_callback(url="https://example.com/hook")
        assert isinstance(cb, WebhookCallback)
        assert cb._config.url == "https://example.com/hook"

    def test_full_config(self) -> None:
        cb = create_webhook_callback(
            url="https://example.com/hook",
            headers={"X-Custom": "val"},
            secret="hmac-secret",
            batch_size=10,
            flush_interval=15.0,
            timeout=5.0,
            max_retries=5,
            events=["request.completed", "request.failed"],
        )
        config = cb._config
        assert config.url == "https://example.com/hook"
        assert config.headers == {"X-Custom": "val"}
        assert config.secret == "hmac-secret"
        assert config.batch_size == 10
        assert config.flush_interval == 15.0
        assert config.timeout == 5.0
        assert config.max_retries == 5
        assert config.events == ["request.completed", "request.failed"]

    @respx.mock
    @pytest.mark.asyncio()
    async def test_factory_with_http_client(self) -> None:
        """Factory-created callback works with a shared HTTP client."""
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))

        async with httpx.AsyncClient() as client:
            cb = create_webhook_callback(
                url=WEBHOOK_URL,
                http_client=client,
            )
            await cb.on_request_end(_make_end_data())
            assert route.called

            await cb.shutdown()


# ===================================================================
# Data Conversion Tests
# ===================================================================


class TestCallbackDataToDict:
    """Tests for the _callback_data_to_dict helper."""

    def test_request_start_data(self) -> None:
        data = _make_start_data()
        result = _callback_data_to_dict(data)
        assert result["request_id"] == "req-001"
        assert result["model"] == "gpt-4"
        assert result["user_id"] == "user-1"
        assert result["team_id"] == "team-1"

    def test_request_end_data(self) -> None:
        data = _make_end_data()
        result = _callback_data_to_dict(data)
        assert result["provider"] == "openai"
        assert result["cost"] == 0.001
        assert result["tokens_prompt"] == 10
        assert result["tokens_completion"] == 20

    def test_request_error_data(self) -> None:
        data = _make_error_data()
        result = _callback_data_to_dict(data)
        assert result["error"] == "Rate limit exceeded"
        assert result["error_type"] == "RateLimitError"

    def test_stream_event_data(self) -> None:
        data = _make_stream_data()
        result = _callback_data_to_dict(data)
        assert result["chunk"] == {"content": "hi"}
        assert result["cumulative_tokens"] == 5


# ===================================================================
# Edge Cases
# ===================================================================


class TestEdgeCases:
    """Edge cases and error scenarios."""

    @respx.mock
    @pytest.mark.asyncio()
    async def test_shutdown_without_start(self) -> None:
        """Shutdown before start is a no-op."""
        config = WebhookConfig(url=WEBHOOK_URL)
        cb = WebhookCallback(config)
        await cb.shutdown()  # should not raise

    @respx.mock
    @pytest.mark.asyncio()
    async def test_double_shutdown(self) -> None:
        """Double shutdown is safe."""
        config = WebhookConfig(url=WEBHOOK_URL)
        respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(config)

        await cb.on_request_end(_make_end_data())
        await cb.shutdown()
        await cb.shutdown()  # should not raise

    @respx.mock
    @pytest.mark.asyncio()
    async def test_restart_after_shutdown(self) -> None:
        """Callback can be restarted after shutdown."""
        config = WebhookConfig(url=WEBHOOK_URL)
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(config)

        await cb.on_request_end(_make_end_data())
        await cb.shutdown()

        # Start again
        await cb.on_request_end(_make_end_data())
        assert route.call_count == 2

        await cb.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_large_payload(self) -> None:
        """Large payloads are sent correctly."""
        config = WebhookConfig(url=WEBHOOK_URL)
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        cb = WebhookCallback(config)

        data = _make_end_data()
        data.response = {"content": "x" * 10000}  # large response
        await cb.on_request_end(data)

        body = json.loads(route.calls.last.request.content)
        assert len(body["events"][0]["data"]["response"]["content"]) == 10000

        await cb.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_event_count_header(self) -> None:
        """X-RouterBot-Event-Count header reflects the batch size."""
        config = WebhookConfig(url=WEBHOOK_URL, batch_size=3, flush_interval=60.0)
        route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(config)
        await delivery.start()

        for _ in range(3):
            await delivery.enqueue(WebhookEvent(event_type="test"))

        req = route.calls.last.request
        assert req.headers["X-RouterBot-Event-Count"] == "3"

        await delivery.shutdown()

    @respx.mock
    @pytest.mark.asyncio()
    async def test_concurrent_enqueue(self) -> None:
        """Concurrent enqueue calls are thread-safe."""
        config = WebhookConfig(url=WEBHOOK_URL)
        respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200))
        delivery = WebhookDelivery(config)
        await delivery.start()

        # Fire 20 concurrent enqueues
        tasks = [
            delivery.enqueue(WebhookEvent(event_type="test", event_id=f"evt-{i}"))
            for i in range(20)
        ]
        await asyncio.gather(*tasks)

        assert delivery.total_delivered == 20

        await delivery.shutdown()
