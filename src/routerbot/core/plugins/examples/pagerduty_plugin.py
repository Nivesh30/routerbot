"""PagerDuty incident creation callback plugin.

Creates PagerDuty incidents when critical errors or sustained failures
are detected. Uses the PagerDuty Events API v2.

Configuration example::

    plugins:
      enabled: true
      plugins:
        - name: pagerduty-alerts
          module: routerbot.core.plugins.examples.pagerduty_plugin
          class: PagerDutyCallbackHook
          config:
            routing_key: "os.environ/PAGERDUTY_ROUTING_KEY"
            severity: "error"          # info | warning | error | critical
            error_threshold: 10        # consecutive errors before incident
            source: "routerbot"
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from routerbot.core.plugins.hooks import CallbackHook

logger = logging.getLogger(__name__)

_EVENTS_API_V2 = "https://events.pagerduty.com/v2/enqueue"


class PagerDutyCallbackHook(CallbackHook):
    """Creates PagerDuty incidents via Events API v2."""

    name = "pagerduty-alerts"
    version = "1.0.0"
    description = "Create PagerDuty incidents for critical LLM errors"
    author = "RouterBot"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._routing_key = self._config.get("routing_key", "")
        self._severity = self._config.get("severity", "error")
        self._error_threshold = int(self._config.get("error_threshold", 10))
        self._source = self._config.get("source", "routerbot")
        self._client: httpx.AsyncClient | None = None
        self._consecutive_errors: int = 0
        self._dedup_key: str | None = None

    async def setup(self) -> None:
        """Create an HTTP client for PagerDuty API."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        )
        logger.info("PagerDuty plugin ready: source=%s", self._source)

    async def teardown(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def on_request_start(self, data: dict[str, Any]) -> None:
        """No-op for request start."""

    async def on_request_end(self, data: dict[str, Any]) -> None:
        """Resolve incident if errors have stopped."""
        status = data.get("status", "success")
        if status == "success" and self._dedup_key:
            await self._resolve_incident()
            self._consecutive_errors = 0
            self._dedup_key = None

    async def on_error(self, data: dict[str, Any]) -> None:
        """Track errors and create PagerDuty incident at threshold."""
        self._consecutive_errors += 1
        if self._consecutive_errors >= self._error_threshold:
            await self._trigger_incident(data)
            self._consecutive_errors = 0

    async def _trigger_incident(self, data: dict[str, Any]) -> None:
        """Create a PagerDuty incident."""
        if not self._client or not self._routing_key:
            return

        model = data.get("model", "unknown")
        error = str(data.get("error", "Unknown error"))[:255]
        ts = datetime.now(tz=UTC).isoformat()

        self._dedup_key = f"routerbot-{model}-{ts[:13]}"

        payload = {
            "routing_key": self._routing_key,
            "event_action": "trigger",
            "dedup_key": self._dedup_key,
            "payload": {
                "summary": f"RouterBot: {self._error_threshold} consecutive errors on {model}",
                "source": self._source,
                "severity": self._severity,
                "timestamp": ts,
                "component": model,
                "custom_details": {
                    "model": model,
                    "consecutive_errors": self._error_threshold,
                    "last_error": error,
                },
            },
        }

        try:
            resp = await self._client.post(_EVENTS_API_V2, json=payload)
            if resp.status_code == 202:
                logger.info("PagerDuty incident triggered for %s", model)
            else:
                logger.debug("PagerDuty returned %d", resp.status_code)
        except httpx.HTTPError:
            logger.debug("Failed to create PagerDuty incident")

    async def _resolve_incident(self) -> None:
        """Resolve a previously triggered PagerDuty incident."""
        if not self._client or not self._routing_key or not self._dedup_key:
            return

        payload = {
            "routing_key": self._routing_key,
            "event_action": "resolve",
            "dedup_key": self._dedup_key,
        }

        try:
            resp = await self._client.post(_EVENTS_API_V2, json=payload)
            if resp.status_code == 202:
                logger.info("PagerDuty incident resolved: %s", self._dedup_key)
            else:
                logger.debug("PagerDuty resolve returned %d", resp.status_code)
        except httpx.HTTPError:
            logger.debug("Failed to resolve PagerDuty incident")
