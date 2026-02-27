"""Slack alerts callback plugin.

Sends alerts to a Slack channel via incoming webhooks when errors,
budget thresholds, or notable events occur.

Configuration example::

    plugins:
      enabled: true
      plugins:
        - name: slack-alerts
          module: routerbot.core.plugins.examples.slack_plugin
          class: SlackCallbackHook
          config:
            webhook_url: "os.environ/SLACK_WEBHOOK_URL"
            channel: "#llm-alerts"
            notify_on_error: true
            notify_on_budget: true
            error_threshold: 5        # consecutive errors before alert
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from routerbot.core.plugins.hooks import CallbackHook

logger = logging.getLogger(__name__)


class SlackCallbackHook(CallbackHook):
    """Sends alerts to Slack via incoming webhook."""

    name = "slack-alerts"
    version = "1.0.0"
    description = "Send error and budget alerts to Slack"
    author = "RouterBot"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._webhook_url = self._config.get("webhook_url", "")
        self._channel = self._config.get("channel", "#llm-alerts")
        self._notify_on_error = self._config.get("notify_on_error", True)
        self._notify_on_budget = self._config.get("notify_on_budget", True)
        self._error_threshold = int(self._config.get("error_threshold", 5))
        self._client: httpx.AsyncClient | None = None
        self._consecutive_errors: int = 0

    async def setup(self) -> None:
        """Create an HTTP client for Slack webhooks."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        )
        logger.info("Slack plugin ready: channel=%s", self._channel)

    async def teardown(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def on_request_start(self, data: dict[str, Any]) -> None:
        """No-op for request start (Slack is for alerts only)."""

    async def on_request_end(self, data: dict[str, Any]) -> None:
        """Reset consecutive error counter on success."""
        status = data.get("status", "success")
        if status == "success":
            self._consecutive_errors = 0

        # Check for budget alerts
        if self._notify_on_budget:
            budget_alert = data.get("budget_alert")
            if budget_alert:
                await self._send_budget_alert(budget_alert)

    async def on_error(self, data: dict[str, Any]) -> None:
        """Track errors and send alert when threshold is reached."""
        if not self._notify_on_error:
            return

        self._consecutive_errors += 1
        if self._consecutive_errors >= self._error_threshold:
            await self._send_error_alert(data)
            self._consecutive_errors = 0

    async def _send_error_alert(self, data: dict[str, Any]) -> None:
        """Send an error alert to Slack."""
        model = data.get("model", "unknown")
        error = data.get("error", "Unknown error")
        ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":rotating_light: RouterBot Error Alert",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Model:* `{model}`"},
                    {"type": "mrkdwn", "text": f"*Time:* {ts}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Consecutive Errors:* {self._error_threshold}",
                    },
                    {"type": "mrkdwn", "text": f"*Error:* {error!s:.200}"},
                ],
            },
        ]

        await self._send_message(blocks)

    async def _send_budget_alert(self, alert: dict[str, Any]) -> None:
        """Send a budget alert to Slack."""
        model = alert.get("model", "unknown")
        spend = alert.get("current_spend", 0.0)
        threshold = alert.get("threshold", 0.0)
        severity = alert.get("severity", "warning")

        emoji = {
            "info": ":information_source:",
            "warning": ":warning:",
            "critical": ":fire:",
        }.get(severity, ":warning:")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} RouterBot Budget Alert",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Model:* `{model}`"},
                    {"type": "mrkdwn", "text": f"*Severity:* {severity}"},
                    {"type": "mrkdwn", "text": f"*Current Spend:* ${spend:.2f}"},
                    {"type": "mrkdwn", "text": f"*Threshold:* ${threshold:.2f}"},
                ],
            },
        ]

        await self._send_message(blocks)

    async def _send_message(self, blocks: list[dict[str, Any]]) -> None:
        """Post a block-kit message to Slack."""
        if not self._client or not self._webhook_url:
            return

        payload = {"channel": self._channel, "blocks": blocks}

        try:
            resp = await self._client.post(self._webhook_url, json=payload)
            if resp.status_code != 200:
                logger.debug("Slack webhook returned %d", resp.status_code)
        except httpx.HTTPError:
            logger.debug("Failed to send Slack message")
