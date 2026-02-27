"""Datadog metrics callback plugin.

Sends request metrics (latency, tokens, cost, errors) to Datadog
via the DogStatsD protocol over UDP. Requires a local ``datadog-agent``
or a StatsD-compatible collector.

Configuration example::

    plugins:
      enabled: true
      plugins:
        - name: datadog-metrics
          module: routerbot.core.plugins.examples.datadog_plugin
          class: DatadogCallbackHook
          config:
            host: "127.0.0.1"
            port: 8125
            prefix: "routerbot"
            tags:
              - "env:production"
"""

from __future__ import annotations

import logging
import socket
from typing import Any

from routerbot.core.plugins.hooks import CallbackHook

logger = logging.getLogger(__name__)


class DatadogCallbackHook(CallbackHook):
    """Sends request metrics to Datadog via DogStatsD (UDP)."""

    name = "datadog-metrics"
    version = "1.0.0"
    description = "Send LLM request metrics to Datadog DogStatsD"
    author = "RouterBot"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._host = self._config.get("host", "127.0.0.1")
        self._port = int(self._config.get("port", 8125))
        self._prefix = self._config.get("prefix", "routerbot")
        self._tags: list[str] = list(self._config.get("tags", []))
        self._sock: socket.socket | None = None

    async def setup(self) -> None:
        """Open a UDP socket for DogStatsD."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        logger.info(
            "Datadog plugin ready: %s:%d prefix=%s",
            self._host,
            self._port,
            self._prefix,
        )

    async def teardown(self) -> None:
        """Close the UDP socket."""
        if self._sock:
            self._sock.close()
            self._sock = None

    async def on_request_start(self, data: dict[str, Any]) -> None:
        """Increment the request counter."""
        model = data.get("model", "unknown")
        self._send_metric(
            "increment",
            f"{self._prefix}.request.start",
            tags=[f"model:{model}", *self._tags],
        )

    async def on_request_end(self, data: dict[str, Any]) -> None:
        """Send latency, token, and cost metrics."""
        model = data.get("model", "unknown")
        tags = [f"model:{model}", *self._tags]
        status = data.get("status", "success")
        tags.append(f"status:{status}")

        latency_ms = data.get("latency_ms", 0)
        if latency_ms > 0:
            self._send_metric("timing", f"{self._prefix}.latency", latency_ms, tags=tags)

        tokens = data.get("total_tokens", 0)
        if tokens > 0:
            self._send_metric("gauge", f"{self._prefix}.tokens", tokens, tags=tags)

        cost = data.get("cost", 0.0)
        if cost > 0:
            self._send_metric("gauge", f"{self._prefix}.cost", cost, tags=tags)

        self._send_metric("increment", f"{self._prefix}.request.end", tags=tags)

    async def on_error(self, data: dict[str, Any]) -> None:
        """Increment the error counter."""
        model = data.get("model", "unknown")
        error_type = data.get("error_type", "unknown")
        self._send_metric(
            "increment",
            f"{self._prefix}.error",
            tags=[f"model:{model}", f"error_type:{error_type}", *self._tags],
        )

    def _send_metric(
        self,
        metric_type: str,
        name: str,
        value: float | int = 1,
        *,
        tags: list[str] | None = None,
    ) -> None:
        """Send a single metric via DogStatsD protocol."""
        if not self._sock:
            return

        type_char = {"increment": "c", "gauge": "g", "timing": "ms"}.get(metric_type, "c")
        tag_str = "|#" + ",".join(tags) if tags else ""
        payload = f"{name}:{value}|{type_char}{tag_str}"

        try:
            self._sock.sendto(payload.encode(), (self._host, self._port))
        except OSError:
            logger.debug("Failed to send metric to Datadog: %s", name)
