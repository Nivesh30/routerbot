"""Tests for example plugins (Task 8D.2)."""

from __future__ import annotations

import json
import socket
from unittest.mock import AsyncMock, MagicMock

import httpx

from routerbot.core.plugins.examples.datadog_plugin import DatadogCallbackHook
from routerbot.core.plugins.examples.pagerduty_plugin import PagerDutyCallbackHook
from routerbot.core.plugins.examples.slack_plugin import SlackCallbackHook
from routerbot.core.plugins.examples.splunk_plugin import SplunkCallbackHook
from routerbot.core.plugins.hooks import CallbackHook
from routerbot.core.plugins.manager import PluginManager
from routerbot.core.plugins.models import PluginConfig, PluginStatus, PluginType

# ── Datadog plugin tests ────────────────────────────────────────────


class TestDatadogPlugin:
    """Test the Datadog DogStatsD callback plugin."""

    def test_is_callback_hook(self) -> None:
        hook = DatadogCallbackHook()
        assert isinstance(hook, CallbackHook)

    def test_default_config(self) -> None:
        hook = DatadogCallbackHook()
        assert hook.name == "datadog-metrics"
        assert hook.version == "1.0.0"
        assert hook._host == "127.0.0.1"
        assert hook._port == 8125
        assert hook._prefix == "routerbot"
        assert hook._tags == []

    def test_custom_config(self) -> None:
        hook = DatadogCallbackHook(config={
            "host": "dd.example.com",
            "port": 9999,
            "prefix": "myapp",
            "tags": ["env:test", "team:ml"],
        })
        assert hook._host == "dd.example.com"
        assert hook._port == 9999
        assert hook._prefix == "myapp"
        assert hook._tags == ["env:test", "team:ml"]

    async def test_setup_creates_socket(self) -> None:
        hook = DatadogCallbackHook()
        await hook.setup()
        assert hook._sock is not None
        assert hook._sock.type == socket.SOCK_DGRAM
        await hook.teardown()

    async def test_teardown_closes_socket(self) -> None:
        hook = DatadogCallbackHook()
        await hook.setup()
        await hook.teardown()
        assert hook._sock is None

    async def test_on_request_start(self) -> None:
        hook = DatadogCallbackHook()
        await hook.setup()
        hook._sock = MagicMock(spec=socket.socket)

        await hook.on_request_start({"model": "gpt-4"})
        hook._sock.sendto.assert_called_once()

        payload = hook._sock.sendto.call_args[0][0].decode()
        assert "routerbot.request.start" in payload
        assert "model:gpt-4" in payload
        await hook.teardown()

    async def test_on_request_end_with_metrics(self) -> None:
        hook = DatadogCallbackHook(config={"tags": ["env:test"]})
        hook._sock = MagicMock(spec=socket.socket)

        await hook.on_request_end({
            "model": "gpt-4",
            "status": "success",
            "latency_ms": 250,
            "total_tokens": 500,
            "cost": 0.05,
        })

        # Should send latency, tokens, cost, and end counter = 4 calls
        assert hook._sock.sendto.call_count == 4

    async def test_on_request_end_no_metrics(self) -> None:
        hook = DatadogCallbackHook()
        hook._sock = MagicMock(spec=socket.socket)

        await hook.on_request_end({"model": "gpt-4", "status": "success"})
        # Only the end counter
        assert hook._sock.sendto.call_count == 1

    async def test_on_error(self) -> None:
        hook = DatadogCallbackHook()
        hook._sock = MagicMock(spec=socket.socket)

        await hook.on_error({"model": "gpt-4", "error_type": "timeout"})
        hook._sock.sendto.assert_called_once()

        payload = hook._sock.sendto.call_args[0][0].decode()
        assert "routerbot.error" in payload
        assert "error_type:timeout" in payload

    async def test_send_metric_no_socket(self) -> None:
        hook = DatadogCallbackHook()
        # Should not raise when socket is None
        hook._send_metric("increment", "test.metric")

    async def test_send_metric_os_error(self) -> None:
        hook = DatadogCallbackHook()
        hook._sock = MagicMock(spec=socket.socket)
        hook._sock.sendto.side_effect = OSError("unreachable")
        # Should not raise
        hook._send_metric("increment", "test.metric")


# ── Splunk plugin tests ─────────────────────────────────────────────


class TestSplunkPlugin:
    """Test the Splunk HEC callback plugin."""

    def test_is_callback_hook(self) -> None:
        hook = SplunkCallbackHook()
        assert isinstance(hook, CallbackHook)

    def test_default_config(self) -> None:
        hook = SplunkCallbackHook()
        assert hook.name == "splunk-logs"
        assert hook._source == "routerbot"
        assert hook._sourcetype == "llm_gateway"
        assert hook._index == "main"

    def test_custom_config(self) -> None:
        hook = SplunkCallbackHook(config={
            "hec_url": "https://splunk:8088/services/collector/event",
            "hec_token": "abc123",
            "source": "myapp",
            "sourcetype": "custom",
            "index": "llm",
        })
        assert hook._hec_url == "https://splunk:8088/services/collector/event"
        assert hook._hec_token == "abc123"
        assert hook._source == "myapp"

    async def test_setup_creates_client(self) -> None:
        hook = SplunkCallbackHook(config={"hec_token": "tok"})
        await hook.setup()
        assert hook._client is not None
        await hook.teardown()

    async def test_teardown_closes_client(self) -> None:
        hook = SplunkCallbackHook()
        await hook.setup()
        await hook.teardown()
        assert hook._client is None

    async def test_on_request_start(self) -> None:
        hook = SplunkCallbackHook(config={
            "hec_url": "https://splunk:8088/services/collector/event",
            "hec_token": "tok",
        })
        await hook.setup()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        hook._client.post = AsyncMock(return_value=mock_resp)

        await hook.on_request_start({"model": "gpt-4"})
        hook._client.post.assert_called_once()

        call_args = hook._client.post.call_args
        assert "splunk" in call_args[0][0]
        # Check payload
        payload = json.loads(call_args[1]["content"])
        assert payload["event"]["event_type"] == "request_start"

    async def test_on_request_end(self) -> None:
        hook = SplunkCallbackHook(config={
            "hec_url": "https://splunk:8088/services/collector/event",
        })
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        hook._client.post = AsyncMock(return_value=mock_resp)

        await hook.on_request_end({"model": "gpt-4", "latency_ms": 200})
        hook._client.post.assert_called_once()

    async def test_on_error(self) -> None:
        hook = SplunkCallbackHook(config={
            "hec_url": "https://splunk:8088/services/collector/event",
        })
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        hook._client.post = AsyncMock(return_value=mock_resp)

        await hook.on_error({"error": "timeout"})
        hook._client.post.assert_called_once()

    async def test_send_event_no_client(self) -> None:
        hook = SplunkCallbackHook()
        # Should not raise
        await hook._send_event("test", {})

    async def test_send_event_http_error(self) -> None:
        hook = SplunkCallbackHook(config={"hec_url": "https://splunk:8088/event"})
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        hook._client.post = AsyncMock(side_effect=httpx.HTTPError("fail"))

        # Should not raise
        await hook._send_event("test", {})


# ── Slack plugin tests ──────────────────────────────────────────────


class TestSlackPlugin:
    """Test the Slack alerts callback plugin."""

    def test_is_callback_hook(self) -> None:
        hook = SlackCallbackHook()
        assert isinstance(hook, CallbackHook)

    def test_default_config(self) -> None:
        hook = SlackCallbackHook()
        assert hook.name == "slack-alerts"
        assert hook._channel == "#llm-alerts"
        assert hook._notify_on_error is True
        assert hook._notify_on_budget is True
        assert hook._error_threshold == 5

    def test_custom_config(self) -> None:
        hook = SlackCallbackHook(config={
            "webhook_url": "https://hooks.slack.com/xxx",
            "channel": "#test",
            "error_threshold": 3,
        })
        assert hook._webhook_url == "https://hooks.slack.com/xxx"
        assert hook._channel == "#test"
        assert hook._error_threshold == 3

    async def test_setup_creates_client(self) -> None:
        hook = SlackCallbackHook()
        await hook.setup()
        assert hook._client is not None
        await hook.teardown()

    async def test_error_threshold_triggers_alert(self) -> None:
        hook = SlackCallbackHook(config={
            "webhook_url": "https://hooks.slack.com/xxx",
            "error_threshold": 3,
        })
        await hook.setup()
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        hook._client.post = AsyncMock(return_value=mock_resp)

        # First 2 errors should not trigger
        for _ in range(2):
            await hook.on_error({"model": "gpt-4", "error": "timeout"})
        hook._client.post.assert_not_called()

        # 3rd error should trigger
        await hook.on_error({"model": "gpt-4", "error": "timeout"})
        hook._client.post.assert_called_once()

    async def test_success_resets_error_counter(self) -> None:
        hook = SlackCallbackHook(config={
            "webhook_url": "https://hooks.slack.com/xxx",
            "error_threshold": 3,
        })
        hook._consecutive_errors = 2
        await hook.on_request_end({"status": "success"})
        assert hook._consecutive_errors == 0

    async def test_budget_alert(self) -> None:
        hook = SlackCallbackHook(config={
            "webhook_url": "https://hooks.slack.com/xxx",
        })
        await hook.setup()
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        hook._client.post = AsyncMock(return_value=mock_resp)

        await hook.on_request_end({
            "status": "success",
            "budget_alert": {
                "model": "gpt-4",
                "current_spend": 150.0,
                "threshold": 100.0,
                "severity": "warning",
            },
        })
        hook._client.post.assert_called_once()

    async def test_no_alert_when_disabled(self) -> None:
        hook = SlackCallbackHook(config={
            "webhook_url": "https://hooks.slack.com/xxx",
            "notify_on_error": False,
        })
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        hook._client.post = AsyncMock()

        for _ in range(10):
            await hook.on_error({"model": "gpt-4"})
        hook._client.post.assert_not_called()

    async def test_send_message_no_client(self) -> None:
        hook = SlackCallbackHook()
        # Should not raise
        await hook._send_message([])

    async def test_send_message_http_error(self) -> None:
        hook = SlackCallbackHook(config={"webhook_url": "https://hooks.slack.com/xxx"})
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        hook._client.post = AsyncMock(side_effect=httpx.HTTPError("fail"))

        # Should not raise
        await hook._send_message([{"type": "section", "text": {"type": "mrkdwn", "text": "hi"}}])


# ── PagerDuty plugin tests ──────────────────────────────────────────


class TestPagerDutyPlugin:
    """Test the PagerDuty Events API callback plugin."""

    def test_is_callback_hook(self) -> None:
        hook = PagerDutyCallbackHook()
        assert isinstance(hook, CallbackHook)

    def test_default_config(self) -> None:
        hook = PagerDutyCallbackHook()
        assert hook.name == "pagerduty-alerts"
        assert hook._severity == "error"
        assert hook._error_threshold == 10
        assert hook._source == "routerbot"

    def test_custom_config(self) -> None:
        hook = PagerDutyCallbackHook(config={
            "routing_key": "key123",
            "severity": "critical",
            "error_threshold": 5,
            "source": "myapp",
        })
        assert hook._routing_key == "key123"
        assert hook._severity == "critical"
        assert hook._error_threshold == 5

    async def test_setup_creates_client(self) -> None:
        hook = PagerDutyCallbackHook()
        await hook.setup()
        assert hook._client is not None
        await hook.teardown()

    async def test_error_threshold_triggers_incident(self) -> None:
        hook = PagerDutyCallbackHook(config={
            "routing_key": "key123",
            "error_threshold": 3,
        })
        await hook.setup()
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        hook._client.post = AsyncMock(return_value=mock_resp)

        # First 2 errors
        for _ in range(2):
            await hook.on_error({"model": "gpt-4", "error": "timeout"})
        hook._client.post.assert_not_called()

        # 3rd error triggers
        await hook.on_error({"model": "gpt-4", "error": "timeout"})
        hook._client.post.assert_called_once()

        # Verify it was a trigger action
        call_args = hook._client.post.call_args
        payload = call_args[1]["json"]
        assert payload["event_action"] == "trigger"

    async def test_success_resolves_incident(self) -> None:
        hook = PagerDutyCallbackHook(config={
            "routing_key": "key123",
            "error_threshold": 2,
        })
        await hook.setup()
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        hook._client.post = AsyncMock(return_value=mock_resp)

        # Trigger incident
        await hook.on_error({"model": "gpt-4", "error": "err"})
        await hook.on_error({"model": "gpt-4", "error": "err"})
        assert hook._dedup_key is not None

        # Success resolves
        await hook.on_request_end({"status": "success"})
        assert hook._client.post.call_count == 2  # trigger + resolve

        last_call = hook._client.post.call_args
        assert last_call[1]["json"]["event_action"] == "resolve"
        assert hook._dedup_key is None

    async def test_no_resolve_without_incident(self) -> None:
        hook = PagerDutyCallbackHook(config={"routing_key": "key123"})
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        hook._client.post = AsyncMock()

        await hook.on_request_end({"status": "success"})
        hook._client.post.assert_not_called()

    async def test_trigger_no_client(self) -> None:
        hook = PagerDutyCallbackHook()
        # Should not raise
        await hook._trigger_incident({"model": "gpt-4"})

    async def test_trigger_http_error(self) -> None:
        hook = PagerDutyCallbackHook(config={"routing_key": "key123"})
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        hook._client.post = AsyncMock(side_effect=httpx.HTTPError("fail"))
        # Should not raise
        await hook._trigger_incident({"model": "gpt-4"})

    async def test_resolve_http_error(self) -> None:
        hook = PagerDutyCallbackHook(config={"routing_key": "key123"})
        hook._client = AsyncMock(spec=httpx.AsyncClient)
        hook._client.post = AsyncMock(side_effect=httpx.HTTPError("fail"))
        hook._dedup_key = "test-key"
        # Should not raise
        await hook._resolve_incident()


# ── Plugin manager integration ──────────────────────────────────────


class TestExamplePluginIntegration:
    """Test loading example plugins through the plugin manager."""

    async def test_load_datadog_plugin(self) -> None:
        cfg = PluginConfig(
            enabled=True,
            auto_discover=False,
            plugins=[{
                "name": "datadog",
                "module": "routerbot.core.plugins.examples.datadog_plugin",
                "class": "DatadogCallbackHook",
                "config": {"prefix": "test"},
            }],
        )
        mgr = PluginManager(cfg)
        loaded = await mgr.load_all()
        assert len(loaded) == 1
        assert loaded[0].status == PluginStatus.ACTIVE
        assert loaded[0].plugin_type == PluginType.CALLBACK
        await mgr.shutdown()

    async def test_load_all_example_plugins(self) -> None:
        cfg = PluginConfig(
            enabled=True,
            auto_discover=False,
            plugins=[
                {
                    "name": "dd",
                    "module": "routerbot.core.plugins.examples.datadog_plugin",
                    "class": "DatadogCallbackHook",
                },
                {
                    "name": "splunk",
                    "module": "routerbot.core.plugins.examples.splunk_plugin",
                    "class": "SplunkCallbackHook",
                },
                {
                    "name": "slack",
                    "module": "routerbot.core.plugins.examples.slack_plugin",
                    "class": "SlackCallbackHook",
                },
                {
                    "name": "pd",
                    "module": "routerbot.core.plugins.examples.pagerduty_plugin",
                    "class": "PagerDutyCallbackHook",
                },
            ],
        )
        mgr = PluginManager(cfg)
        loaded = await mgr.load_all()
        assert len(loaded) == 4
        assert all(p.status == PluginStatus.ACTIVE for p in loaded)

        callbacks = mgr.registry.get_hooks_by_type(PluginType.CALLBACK)
        assert len(callbacks) == 4
        await mgr.shutdown()
