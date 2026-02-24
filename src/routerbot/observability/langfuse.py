"""Langfuse tracing callback for LLM request observability.

Sends traces and generations to `Langfuse <https://langfuse.com>`_ on
every LLM request.  Supports the Langfuse v2 batch ingestion API so
that trace submission never blocks the response path.

Features:

- **Batch ingestion** — events are queued in memory and flushed
  periodically or when a batch-size threshold is reached.
- **Per-team Langfuse projects** — each team can have its own
  Langfuse public/secret key pair so traces land in separate projects.
- **Graceful degradation** — network failures are logged and retried
  once; they never propagate to the caller.

Configuration (global)::

    environment_variables:
      LANGFUSE_PUBLIC_KEY: "pk-..."
      LANGFUSE_SECRET_KEY: "sk-..."
      LANGFUSE_HOST: "https://cloud.langfuse.com"

    routerbot_settings:
      callbacks: ["langfuse"]

Configuration (per-team override)::

    team_settings:
      team-frontend:
        langfuse_public_key: "pk-team-..."
        langfuse_secret_key: "sk-team-..."
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from routerbot.observability.callbacks import (
    BaseCallback,
    RequestEndData,
    RequestErrorData,
    RequestStartData,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Langfuse API client
# ---------------------------------------------------------------------------

_DEFAULT_HOST = "https://cloud.langfuse.com"
_INGESTION_PATH = "/api/public/ingestion"
_FLUSH_INTERVAL_SECONDS = 5.0
_MAX_BATCH_SIZE = 50
_REQUEST_TIMEOUT = 10.0


@dataclass
class LangfuseCredentials:
    """Credentials for a single Langfuse project."""

    public_key: str
    secret_key: str
    host: str = _DEFAULT_HOST

    @property
    def auth_header(self) -> str:
        """Return ``Basic <b64(public:secret)>`` header value."""
        pair = f"{self.public_key}:{self.secret_key}"
        return "Basic " + base64.b64encode(pair.encode()).decode()


@dataclass
class _IngestionEvent:
    """A single event destined for the Langfuse batch ingestion API."""

    body: dict[str, Any]
    event_type: str  # "trace-create", "generation-create", etc.
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()))


class LangfuseClient:
    """Low-level async HTTP client for the Langfuse v2 batch ingestion API.

    Events are accumulated in an internal queue and flushed either when
    the queue reaches *max_batch_size* events or when :meth:`flush` is
    called explicitly (typically on a timer).
    """

    def __init__(
        self,
        credentials: LangfuseCredentials,
        *,
        max_batch_size: int = _MAX_BATCH_SIZE,
        flush_interval: float = _FLUSH_INTERVAL_SECONDS,
        timeout: float = _REQUEST_TIMEOUT,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._credentials = credentials
        self._max_batch_size = max_batch_size
        self._flush_interval = flush_interval
        self._timeout = timeout
        self._queue: list[_IngestionEvent] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        self._http: httpx.AsyncClient | None = http_client
        self._owns_client = http_client is None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background flush loop."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._periodic_flush())

    async def shutdown(self) -> None:
        """Final flush and clean up resources."""
        if self._flush_task is not None:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None

        # Final flush
        await self.flush()

        if self._owns_client and self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    async def enqueue(self, event: _IngestionEvent) -> None:
        """Add an event to the batch queue.

        If the queue reaches *max_batch_size*, a flush is triggered
        automatically.
        """
        async with self._lock:
            self._queue.append(event)
            should_flush = len(self._queue) >= self._max_batch_size

        if should_flush:
            await self.flush()

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    async def flush(self) -> None:
        """Send all queued events to Langfuse in a single batch request."""
        async with self._lock:
            if not self._queue:
                return
            batch = self._queue[:]
            self._queue.clear()

        payload = {
            "batch": [
                {
                    "id": ev.event_id,
                    "type": ev.event_type,
                    "timestamp": ev.timestamp,
                    "body": ev.body,
                }
                for ev in batch
            ],
        }

        await self._send(payload)

    async def _send(self, payload: dict[str, Any]) -> None:
        """POST the batch payload to the ingestion endpoint with one retry."""
        if self._http is None:
            logger.warning("LangfuseClient: no HTTP client; dropping %d events", len(payload.get("batch", [])))
            return

        url = self._credentials.host.rstrip("/") + _INGESTION_PATH
        headers = {
            "Authorization": self._credentials.auth_header,
            "Content-Type": "application/json",
        }

        for attempt in range(2):
            try:
                resp = await self._http.post(url, json=payload, headers=headers)
                if resp.status_code < 300:
                    logger.debug(
                        "Langfuse ingestion OK (%d events, status=%d)",
                        len(payload.get("batch", [])),
                        resp.status_code,
                    )
                    return
                logger.warning(
                    "Langfuse ingestion returned %d: %s (attempt %d)",
                    resp.status_code,
                    resp.text[:200],
                    attempt + 1,
                )
            except httpx.HTTPError:
                logger.exception("Langfuse ingestion HTTP error (attempt %d)", attempt + 1)

            if attempt == 0:
                await asyncio.sleep(1.0)

        logger.error("Langfuse ingestion failed after 2 attempts; dropping batch")

    async def _periodic_flush(self) -> None:
        """Background loop that flushes the queue on a timer."""
        while True:
            await asyncio.sleep(self._flush_interval)
            try:
                await self.flush()
            except Exception:
                logger.exception("LangfuseClient: periodic flush error")


# ---------------------------------------------------------------------------
# Langfuse Callback
# ---------------------------------------------------------------------------


class LangfuseCallback(BaseCallback):
    """Callback that sends LLM traces to Langfuse.

    Each request produces:

    1. A **trace** — top-level container with request metadata.
    2. A **generation** — nested under the trace with model I/O,
       token counts, cost, and latency.

    Parameters
    ----------
    credentials:
        Default :class:`LangfuseCredentials` used when the request does
        not belong to a team with its own credentials.
    team_credentials:
        Mapping of ``team_id`` → :class:`LangfuseCredentials` for
        per-team Langfuse project routing.
    max_batch_size:
        Events to accumulate before an automatic flush.
    flush_interval:
        Seconds between periodic background flushes.
    http_client:
        Shared :class:`httpx.AsyncClient` (useful for tests).
    """

    def __init__(
        self,
        credentials: LangfuseCredentials,
        *,
        team_credentials: dict[str, LangfuseCredentials] | None = None,
        max_batch_size: int = _MAX_BATCH_SIZE,
        flush_interval: float = _FLUSH_INTERVAL_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._default_creds = credentials
        self._team_creds = team_credentials or {}
        self._max_batch_size = max_batch_size
        self._flush_interval = flush_interval
        self._http_client = http_client

        # One LangfuseClient per unique credential set (lazy-created)
        self._clients: dict[str, LangfuseClient] = {}

    # ------------------------------------------------------------------
    # Client management
    # ------------------------------------------------------------------

    def _client_key(self, creds: LangfuseCredentials) -> str:
        """Deterministic key for a credential set."""
        return f"{creds.host}|{creds.public_key}"

    async def _get_client(self, team_id: str | None) -> LangfuseClient:
        """Return (and lazily start) the correct client for the team."""
        creds = self._team_creds.get(team_id, self._default_creds) if team_id else self._default_creds
        key = self._client_key(creds)

        if key not in self._clients:
            client = LangfuseClient(
                creds,
                max_batch_size=self._max_batch_size,
                flush_interval=self._flush_interval,
                http_client=self._http_client,
            )
            await client.start()
            self._clients[key] = client

        return self._clients[key]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Flush all clients and release resources."""
        for client in self._clients.values():
            try:
                await client.shutdown()
            except Exception:
                logger.exception("Error shutting down Langfuse client")
        self._clients.clear()

    # ------------------------------------------------------------------
    # Callback methods
    # ------------------------------------------------------------------

    async def on_request_start(self, data: RequestStartData) -> None:
        """Create a trace event when a request begins."""
        client = await self._get_client(data.team_id)

        trace_body: dict[str, Any] = {
            "id": data.request_id,
            "name": f"routerbot-{data.model}",
            "input": {"messages": data.messages} if data.messages else None,
            "metadata": {
                "model": data.model,
                "user_id": data.user_id,
                "team_id": data.team_id,
                "key_id": data.key_id,
                **(data.metadata or {}),
            },
        }
        if data.user_id:
            trace_body["userId"] = data.user_id

        event = _IngestionEvent(body=trace_body, event_type="trace-create")
        await client.enqueue(event)

    async def on_request_end(self, data: RequestEndData) -> None:
        """Update the trace and create a generation on success."""
        client = await self._get_client(data.team_id)

        # Calculate usage
        total_tokens = data.tokens_prompt + data.tokens_completion
        usage: dict[str, Any] = {
            "input": data.tokens_prompt,
            "output": data.tokens_completion,
            "total": total_tokens,
            "unit": "TOKENS",
        }
        if data.cost > 0:
            usage["inputCost"] = data.cost * (data.tokens_prompt / total_tokens) if total_tokens > 0 else 0
            usage["outputCost"] = data.cost * (data.tokens_completion / total_tokens) if total_tokens > 0 else 0
            usage["totalCost"] = data.cost

        # Generation event (nested under the trace)
        generation_id = str(uuid.uuid4())
        gen_body: dict[str, Any] = {
            "id": generation_id,
            "traceId": data.request_id,
            "name": f"llm-{data.model}",
            "model": data.model,
            "input": {"messages": data.messages} if data.messages else None,
            "output": data.response if data.response else None,
            "usage": usage,
            "metadata": {
                "provider": data.provider,
                "latency_ms": data.latency_ms,
                "team_id": data.team_id,
                "key_id": data.key_id,
                **(data.metadata or {}),
            },
            "startTime": _epoch_to_iso(data.timestamp - data.latency_ms / 1000.0),
            "completionStartTime": _epoch_to_iso(data.timestamp),
            "endTime": _epoch_to_iso(data.timestamp),
            "level": "DEFAULT",
        }

        gen_event = _IngestionEvent(body=gen_body, event_type="generation-create")
        await client.enqueue(gen_event)

        # Update trace with output and status
        trace_update: dict[str, Any] = {
            "id": data.request_id,
            "output": data.response if data.response else None,
            "metadata": {
                "provider": data.provider,
                "tokens_prompt": data.tokens_prompt,
                "tokens_completion": data.tokens_completion,
                "cost": data.cost,
                "latency_ms": data.latency_ms,
            },
        }
        trace_event = _IngestionEvent(body=trace_update, event_type="trace-create")
        await client.enqueue(trace_event)

    async def on_request_error(self, data: RequestErrorData) -> None:
        """Record the error on the trace and create a failed generation."""
        client = await self._get_client(data.team_id)

        # Generation with error
        generation_id = str(uuid.uuid4())
        gen_body: dict[str, Any] = {
            "id": generation_id,
            "traceId": data.request_id,
            "name": f"llm-{data.model}",
            "model": data.model,
            "input": {"messages": data.messages} if data.messages else None,
            "output": None,
            "metadata": {
                "provider": data.provider,
                "error": data.error,
                "error_type": data.error_type,
                "team_id": data.team_id,
                "key_id": data.key_id,
                **(data.metadata or {}),
            },
            "level": "ERROR",
            "statusMessage": data.error,
            "endTime": _epoch_to_iso(data.timestamp),
        }

        gen_event = _IngestionEvent(body=gen_body, event_type="generation-create")
        await client.enqueue(gen_event)

        # Update trace with error
        trace_update: dict[str, Any] = {
            "id": data.request_id,
            "metadata": {
                "error": data.error,
                "error_type": data.error_type,
                "provider": data.provider,
            },
        }
        trace_event = _IngestionEvent(body=trace_update, event_type="trace-create")
        await client.enqueue(trace_event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _epoch_to_iso(epoch: float) -> str:
    """Convert a Unix timestamp to an ISO-8601 datetime string."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch)) + f".{int(epoch * 1000) % 1000:03d}Z"


def create_langfuse_callback(
    *,
    public_key: str,
    secret_key: str,
    host: str = _DEFAULT_HOST,
    team_credentials: dict[str, LangfuseCredentials] | None = None,
    max_batch_size: int = _MAX_BATCH_SIZE,
    flush_interval: float = _FLUSH_INTERVAL_SECONDS,
    http_client: httpx.AsyncClient | None = None,
) -> LangfuseCallback:
    """Convenience factory for creating a :class:`LangfuseCallback`.

    Parameters
    ----------
    public_key:
        Langfuse public key.
    secret_key:
        Langfuse secret key.
    host:
        Langfuse API host (default: ``https://cloud.langfuse.com``).
    team_credentials:
        Per-team credential overrides.
    max_batch_size:
        Events before auto-flush.
    flush_interval:
        Seconds between periodic flushes.
    http_client:
        Optional shared HTTP client.
    """
    creds = LangfuseCredentials(public_key=public_key, secret_key=secret_key, host=host)
    return LangfuseCallback(
        creds,
        team_credentials=team_credentials,
        max_batch_size=max_batch_size,
        flush_interval=flush_interval,
        http_client=http_client,
    )
