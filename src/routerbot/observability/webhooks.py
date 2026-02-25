"""Custom webhook callback for sending LLM events to external HTTP endpoints.

Delivers HTTP POST requests to a configurable URL on each LLM request
lifecycle event.  Supports:

- **Custom headers** (e.g. ``Authorization: Bearer …``)
- **Retry with exponential back-off** on transient failures
- **Batch mode** — accumulates events and flushes when a batch-size
  threshold or a flush-interval timer fires
- **HMAC signature** — optional ``X-RouterBot-Signature`` header using
  HMAC-SHA256 for payload verification

Configuration::

    routerbot_settings:
      callbacks: ["webhook"]
      webhook_url: "https://hooks.example.com/llm-events"
      webhook_headers:
        Authorization: "Bearer webhook-secret"
      webhook_batch_size: 10
      webhook_flush_interval_seconds: 30
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from routerbot.observability.callbacks import (
    BaseCallback,
    CallbackData,
    RequestEndData,
    RequestErrorData,
    RequestStartData,
    StreamEventData,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_BATCH_SIZE = 1  # send immediately by default
_DEFAULT_FLUSH_INTERVAL = 30.0  # seconds
_DEFAULT_TIMEOUT = 10.0  # per-request HTTP timeout
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0  # seconds
_MAX_BACKOFF = 30.0


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class WebhookEvent:
    """A single webhook event ready for delivery."""

    event_type: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class WebhookConfig:
    """Configuration for the webhook callback."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    secret: str | None = None
    batch_size: int = _DEFAULT_BATCH_SIZE
    flush_interval: float = _DEFAULT_FLUSH_INTERVAL
    timeout: float = _DEFAULT_TIMEOUT
    max_retries: int = _MAX_RETRIES
    events: list[str] | None = None  # None = all events


# ---------------------------------------------------------------------------
# Webhook delivery client
# ---------------------------------------------------------------------------


class WebhookDelivery:
    """Handles reliable HTTP delivery of webhook payloads.

    Features:

    - **Retry with back-off** on 5xx / network errors (up to *max_retries*)
    - **Batch accumulation** — events are queued until the batch threshold
      or the flush timer fires
    - **HMAC-SHA256 signing** when *secret* is configured
    """

    def __init__(
        self,
        config: WebhookConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._queue: list[WebhookEvent] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        self._http: httpx.AsyncClient | None = http_client
        self._owns_client = http_client is None

        # Delivery statistics
        self.total_delivered: int = 0
        self.total_failed: int = 0
        self.total_retried: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the periodic flush loop (for batch mode)."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._config.timeout)
        if self._flush_task is None and self._config.batch_size > 1:
            self._flush_task = asyncio.create_task(self._periodic_flush())

    async def shutdown(self) -> None:
        """Cancel the flush loop, send remaining events, close client."""
        if self._flush_task is not None:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None

        await self.flush()

        if self._owns_client and self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    async def enqueue(self, event: WebhookEvent) -> None:
        """Add an event to the queue. Flushes when batch_size is reached."""
        async with self._lock:
            self._queue.append(event)
            should_flush = len(self._queue) >= self._config.batch_size

        if should_flush:
            await self.flush()

    async def flush(self) -> None:
        """Send all queued events immediately."""
        async with self._lock:
            if not self._queue:
                return
            batch = self._queue[:]
            self._queue.clear()

        payload = self._build_payload(batch)
        await self._deliver(payload)

    @property
    def pending_count(self) -> int:
        """Number of events in the queue awaiting delivery."""
        return len(self._queue)

    # ------------------------------------------------------------------
    # Payload construction
    # ------------------------------------------------------------------

    def _build_payload(self, events: list[WebhookEvent]) -> dict[str, Any]:
        """Build the delivery payload from a batch of events."""
        return {
            "events": [
                {
                    "event_id": ev.event_id,
                    "event_type": ev.event_type,
                    "timestamp": ev.timestamp,
                    "data": ev.data,
                }
                for ev in events
            ],
            "batch_size": len(events),
            "sent_at": time.time(),
        }

    # ------------------------------------------------------------------
    # HMAC signing
    # ------------------------------------------------------------------

    def _sign_payload(self, body: bytes) -> str:
        """Compute HMAC-SHA256 of *body* using the configured secret."""
        if not self._config.secret:
            return ""
        return hmac.new(
            self._config.secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()

    # ------------------------------------------------------------------
    # HTTP delivery with retry
    # ------------------------------------------------------------------

    async def _deliver(self, payload: dict[str, Any]) -> None:
        """POST the payload to the webhook URL with retry on failure."""
        if self._http is None:
            logger.warning("WebhookDelivery: no HTTP client; dropping %d events", len(payload.get("events", [])))
            return

        body = json.dumps(payload, default=str).encode()

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "RouterBot-Webhook/1.0",
            "X-RouterBot-Event-Count": str(payload.get("batch_size", 0)),
            **self._config.headers,
        }

        if self._config.secret:
            headers["X-RouterBot-Signature"] = f"sha256={self._sign_payload(body)}"

        backoff = _INITIAL_BACKOFF
        last_error: Exception | None = None

        for attempt in range(self._config.max_retries):
            try:
                resp = await self._http.post(
                    self._config.url,
                    content=body,
                    headers=headers,
                )

                if resp.status_code < 300:
                    self.total_delivered += len(payload.get("events", []))
                    logger.debug(
                        "Webhook delivered %d events (status=%d)",
                        len(payload.get("events", [])),
                        resp.status_code,
                    )
                    return

                # 4xx = client error → don't retry (except 429)
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    logger.warning(
                        "Webhook returned %d (client error, not retrying): %s",
                        resp.status_code,
                        resp.text[:200],
                    )
                    self.total_failed += len(payload.get("events", []))
                    return

                # 5xx or 429 → retry
                logger.warning(
                    "Webhook returned %d (attempt %d/%d): %s",
                    resp.status_code,
                    attempt + 1,
                    self._config.max_retries,
                    resp.text[:200],
                )

            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "Webhook delivery error (attempt %d/%d): %s",
                    attempt + 1,
                    self._config.max_retries,
                    exc,
                )

            self.total_retried += 1
            if attempt < self._config.max_retries - 1:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)

        event_count = len(payload.get("events", []))
        self.total_failed += event_count
        if last_error:
            logger.error(
                "Webhook delivery failed after %d attempts (%d events dropped): %s",
                self._config.max_retries,
                event_count,
                last_error,
            )
        else:
            logger.error(
                "Webhook delivery failed after %d attempts (%d events dropped)",
                self._config.max_retries,
                event_count,
            )

    async def _periodic_flush(self) -> None:
        """Background loop that flushes enqueued events on a timer."""
        while True:
            await asyncio.sleep(self._config.flush_interval)
            try:
                await self.flush()
            except Exception:
                logger.exception("WebhookDelivery: periodic flush error")


# ---------------------------------------------------------------------------
# Webhook callback
# ---------------------------------------------------------------------------


class WebhookCallback(BaseCallback):
    """Callback that POSTs LLM lifecycle events to a webhook URL.

    Parameters
    ----------
    config:
        :class:`WebhookConfig` with the target URL, headers, and
        delivery settings.
    http_client:
        Optional shared :class:`httpx.AsyncClient` (useful for tests).
    """

    def __init__(
        self,
        config: WebhookConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._delivery = WebhookDelivery(config, http_client=http_client)
        self._started = False

    @property
    def delivery(self) -> WebhookDelivery:
        """Expose the delivery client for inspection / testing."""
        return self._delivery

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _ensure_started(self) -> None:
        """Lazily start the delivery client on first use."""
        if not self._started:
            await self._delivery.start()
            self._started = True

    async def shutdown(self) -> None:
        """Flush pending events and close underlying resources."""
        if self._started:
            await self._delivery.shutdown()
            self._started = False

    # ------------------------------------------------------------------
    # Event filtering
    # ------------------------------------------------------------------

    def _should_send(self, event_type: str) -> bool:
        """Return True if this event type should be sent to the webhook."""
        if self._config.events is None:
            return True
        return event_type in self._config.events

    # ------------------------------------------------------------------
    # Callback methods
    # ------------------------------------------------------------------

    async def on_request_start(self, data: RequestStartData) -> None:
        """Enqueue a request.start event."""
        if not self._should_send("request.start"):
            return
        await self._ensure_started()
        event = WebhookEvent(
            event_type="request.start",
            data=_callback_data_to_dict(data),
        )
        await self._delivery.enqueue(event)

    async def on_request_end(self, data: RequestEndData) -> None:
        """Enqueue a request.completed event."""
        if not self._should_send("request.completed"):
            return
        await self._ensure_started()
        event = WebhookEvent(
            event_type="request.completed",
            data=_callback_data_to_dict(data),
        )
        await self._delivery.enqueue(event)

    async def on_request_error(self, data: RequestErrorData) -> None:
        """Enqueue a request.failed event."""
        if not self._should_send("request.failed"):
            return
        await self._ensure_started()
        event = WebhookEvent(
            event_type="request.failed",
            data=_callback_data_to_dict(data),
        )
        await self._delivery.enqueue(event)

    async def on_stream_start(self, data: StreamEventData) -> None:
        """Enqueue a stream.start event."""
        if not self._should_send("stream.start"):
            return
        await self._ensure_started()
        event = WebhookEvent(
            event_type="stream.start",
            data=_callback_data_to_dict(data),
        )
        await self._delivery.enqueue(event)

    async def on_stream_chunk(self, data: StreamEventData) -> None:
        """Enqueue a stream.chunk event (disabled by default for volume)."""
        if not self._should_send("stream.chunk"):
            return
        await self._ensure_started()
        event = WebhookEvent(
            event_type="stream.chunk",
            data=_callback_data_to_dict(data),
        )
        await self._delivery.enqueue(event)

    async def on_stream_end(self, data: StreamEventData) -> None:
        """Enqueue a stream.end event."""
        if not self._should_send("stream.end"):
            return
        await self._ensure_started()
        event = WebhookEvent(
            event_type="stream.end",
            data=_callback_data_to_dict(data),
        )
        await self._delivery.enqueue(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _callback_data_to_dict(data: CallbackData) -> dict[str, Any]:
    """Convert a callback data object to a plain dictionary."""
    return asdict(data)


def create_webhook_callback(
    *,
    url: str,
    headers: dict[str, str] | None = None,
    secret: str | None = None,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    flush_interval: float = _DEFAULT_FLUSH_INTERVAL,
    timeout: float = _DEFAULT_TIMEOUT,
    max_retries: int = _MAX_RETRIES,
    events: list[str] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> WebhookCallback:
    """Convenience factory for creating a :class:`WebhookCallback`.

    Parameters
    ----------
    url:
        Target webhook URL.
    headers:
        Extra HTTP headers (e.g. auth tokens).
    secret:
        HMAC-SHA256 secret for payload signing.
    batch_size:
        Events to accumulate before auto-flush (1 = immediate).
    flush_interval:
        Seconds between periodic background flushes.
    timeout:
        Per-request HTTP timeout seconds.
    max_retries:
        Max delivery attempts per batch.
    events:
        List of event types to send (``None`` = all).
    http_client:
        Shared HTTP client instance.
    """
    config = WebhookConfig(
        url=url,
        headers=headers or {},
        secret=secret,
        batch_size=batch_size,
        flush_interval=flush_interval,
        timeout=timeout,
        max_retries=max_retries,
        events=events,
    )
    return WebhookCallback(config, http_client=http_client)
