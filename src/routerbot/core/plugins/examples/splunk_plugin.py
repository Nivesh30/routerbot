"""Splunk log export callback plugin.

Sends request logs to a Splunk HTTP Event Collector (HEC) endpoint.
Requires a Splunk HEC token and endpoint URL.

Configuration example::

    plugins:
      enabled: true
      plugins:
        - name: splunk-logs
          module: routerbot.core.plugins.examples.splunk_plugin
          class: SplunkCallbackHook
          config:
            hec_url: "https://splunk.example.com:8088/services/collector/event"
            hec_token: "os.environ/SPLUNK_HEC_TOKEN"
            source: "routerbot"
            sourcetype: "llm_gateway"
            index: "main"
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from routerbot.core.plugins.hooks import CallbackHook

logger = logging.getLogger(__name__)


class SplunkCallbackHook(CallbackHook):
    """Sends request events to Splunk via HTTP Event Collector."""

    name = "splunk-logs"
    version = "1.0.0"
    description = "Send LLM request logs to Splunk HEC"
    author = "RouterBot"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._hec_url = self._config.get("hec_url", "")
        self._hec_token = self._config.get("hec_token", "")
        self._source = self._config.get("source", "routerbot")
        self._sourcetype = self._config.get("sourcetype", "llm_gateway")
        self._index = self._config.get("index", "main")
        self._client: httpx.AsyncClient | None = None

    async def setup(self) -> None:
        """Create an HTTP client for Splunk HEC."""
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Splunk {self._hec_token}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        )
        logger.info("Splunk plugin ready: %s", self._hec_url)

    async def teardown(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def on_request_start(self, data: dict[str, Any]) -> None:
        """Log request start event to Splunk."""
        await self._send_event("request_start", data)

    async def on_request_end(self, data: dict[str, Any]) -> None:
        """Log request end event to Splunk."""
        await self._send_event("request_end", data)

    async def on_error(self, data: dict[str, Any]) -> None:
        """Log error event to Splunk."""
        await self._send_event("error", data)

    async def _send_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Send a single event to Splunk HEC."""
        if not self._client or not self._hec_url:
            return

        payload = {
            "time": datetime.now(tz=UTC).timestamp(),
            "source": self._source,
            "sourcetype": self._sourcetype,
            "index": self._index,
            "event": {
                "event_type": event_type,
                **data,
            },
        }

        try:
            resp = await self._client.post(self._hec_url, content=json.dumps(payload))
            if resp.status_code != 200:
                logger.debug(
                    "Splunk HEC returned %d for %s",
                    resp.status_code,
                    event_type,
                )
        except httpx.HTTPError:
            logger.debug("Failed to send event to Splunk: %s", event_type)
