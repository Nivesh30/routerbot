"""Tests for team-based logging configuration and callback routing.

Covers:
- TeamLoggingConfig parsing from team settings dict
- TeamCallbackManager dispatch with global fallback
- GDPR disable_logging suppresses all callbacks
- Per-team callback list overrides global
- Team without config uses global callbacks
- No team_id uses global callbacks
- Missing named callback logs warning
- set_team_config / remove_team_config management
"""

from __future__ import annotations

import pytest

from routerbot.observability.callbacks import (
    BaseCallback,
    CallbackEvent,
    CallbackManager,
    RequestEndData,
    RequestErrorData,
    RequestStartData,
)
from routerbot.observability.team_logging import (
    TeamCallbackManager,
    TeamLoggingConfig,
    parse_team_logging_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class StubCallback(BaseCallback):
    """Test callback that records calls."""

    def __init__(self, cb_name: str = "StubCallback") -> None:
        self._cb_name = cb_name
        self.start_calls: list = []
        self.end_calls: list = []
        self.error_calls: list = []

    @property
    def name(self) -> str:
        return self._cb_name

    async def on_request_start(self, data: RequestStartData) -> None:
        self.start_calls.append(data)

    async def on_request_end(self, data: RequestEndData) -> None:
        self.end_calls.append(data)

    async def on_request_error(self, data: RequestErrorData) -> None:
        self.error_calls.append(data)


@pytest.fixture()
def cb_spend() -> StubCallback:
    return StubCallback("spend_log")


@pytest.fixture()
def cb_langfuse() -> StubCallback:
    return StubCallback("langfuse")


@pytest.fixture()
def cb_webhook() -> StubCallback:
    return StubCallback("webhook")


@pytest.fixture()
def global_manager(cb_spend: StubCallback, cb_langfuse: StubCallback, cb_webhook: StubCallback) -> CallbackManager:
    mgr = CallbackManager()
    mgr.register(cb_spend)
    mgr.register(cb_langfuse)
    mgr.register(cb_webhook)
    return mgr


@pytest.fixture()
def start_data() -> RequestStartData:
    return RequestStartData(
        request_id="req-001",
        model="gpt-4o",
        user_id="user-1",
        team_id="team-a",
    )


@pytest.fixture()
def end_data() -> RequestEndData:
    return RequestEndData(
        request_id="req-001",
        model="gpt-4o",
        provider="openai",
        tokens_prompt=10,
        tokens_completion=5,
        cost=0.001,
        user_id="user-1",
        team_id="team-a",
    )


# ===================================================================
# parse_team_logging_config tests
# ===================================================================


class TestParseTeamLoggingConfig:
    def test_none_settings(self) -> None:
        config = parse_team_logging_config(None)
        assert config.disable_logging is False
        assert config.callbacks is None

    def test_empty_settings(self) -> None:
        config = parse_team_logging_config({})
        assert config.disable_logging is False
        assert config.callbacks is None

    def test_disable_logging(self) -> None:
        config = parse_team_logging_config({"disable_logging": True})
        assert config.disable_logging is True

    def test_callbacks_list(self) -> None:
        config = parse_team_logging_config({"callbacks": ["langfuse", "webhook"]})
        assert config.callbacks == ["langfuse", "webhook"]

    def test_langfuse_credentials(self) -> None:
        config = parse_team_logging_config(
            {
                "langfuse_public_key": "pk-123",
                "langfuse_secret_key": "sk-456",
                "langfuse_host": "https://my-langfuse.com",
            }
        )
        assert config.langfuse_public_key == "pk-123"
        assert config.langfuse_secret_key == "sk-456"
        assert config.langfuse_host == "https://my-langfuse.com"

    def test_webhook_config(self) -> None:
        config = parse_team_logging_config(
            {
                "webhook_url": "https://hooks.example.com/logs",
                "webhook_headers": {"Authorization": "Bearer tok"},
            }
        )
        assert config.webhook_url == "https://hooks.example.com/logs"
        assert config.webhook_headers == {"Authorization": "Bearer tok"}

    def test_extra_keys_preserved(self) -> None:
        config = parse_team_logging_config(
            {
                "callbacks": ["langfuse"],
                "custom_key": "custom_value",
                "another": 42,
            }
        )
        assert config.extra == {"custom_key": "custom_value", "another": 42}

    def test_full_config(self) -> None:
        config = parse_team_logging_config(
            {
                "disable_logging": False,
                "callbacks": ["spend_log"],
                "langfuse_public_key": "pk",
                "langfuse_secret_key": "sk",
                "langfuse_host": "https://lf.example.com",
                "webhook_url": "https://wh.example.com",
                "webhook_headers": {"X-Token": "secret"},
            }
        )
        assert config.disable_logging is False
        assert config.callbacks == ["spend_log"]
        assert config.langfuse_public_key == "pk"
        assert config.webhook_url == "https://wh.example.com"
        assert config.extra == {}


# ===================================================================
# TeamCallbackManager tests
# ===================================================================


class TestTeamCallbackManager:
    @pytest.mark.asyncio()
    async def test_no_team_id_uses_global(
        self,
        global_manager: CallbackManager,
        cb_spend: StubCallback,
        start_data: RequestStartData,
    ) -> None:
        """When no team_id provided, all global callbacks fire."""
        tcm = TeamCallbackManager(global_manager)
        await tcm.dispatch(CallbackEvent.REQUEST_START, start_data, team_id=None)
        assert len(cb_spend.start_calls) == 1

    @pytest.mark.asyncio()
    async def test_team_without_config_uses_global(
        self,
        global_manager: CallbackManager,
        cb_spend: StubCallback,
        cb_langfuse: StubCallback,
        start_data: RequestStartData,
    ) -> None:
        """Team with no config override uses global callbacks."""
        tcm = TeamCallbackManager(global_manager)
        await tcm.dispatch(CallbackEvent.REQUEST_START, start_data, team_id="team-unknown")
        assert len(cb_spend.start_calls) == 1
        assert len(cb_langfuse.start_calls) == 1

    @pytest.mark.asyncio()
    async def test_disable_logging_suppresses_all(
        self,
        global_manager: CallbackManager,
        cb_spend: StubCallback,
        cb_langfuse: StubCallback,
        cb_webhook: StubCallback,
        start_data: RequestStartData,
    ) -> None:
        """GDPR mode: disable_logging=True suppresses all callbacks."""
        tcm = TeamCallbackManager(
            global_manager,
            team_configs={
                "team-a": TeamLoggingConfig(disable_logging=True),
            },
        )
        await tcm.dispatch(CallbackEvent.REQUEST_START, start_data, team_id="team-a")
        assert len(cb_spend.start_calls) == 0
        assert len(cb_langfuse.start_calls) == 0
        assert len(cb_webhook.start_calls) == 0

    @pytest.mark.asyncio()
    async def test_team_specific_callbacks(
        self,
        global_manager: CallbackManager,
        cb_spend: StubCallback,
        cb_langfuse: StubCallback,
        cb_webhook: StubCallback,
        start_data: RequestStartData,
    ) -> None:
        """Team with callbacks list only fires those, not all global."""
        tcm = TeamCallbackManager(
            global_manager,
            team_configs={
                "team-a": TeamLoggingConfig(callbacks=["langfuse"]),
            },
        )
        await tcm.dispatch(CallbackEvent.REQUEST_START, start_data, team_id="team-a")
        # Only langfuse should fire
        assert len(cb_langfuse.start_calls) == 1
        assert len(cb_spend.start_calls) == 0
        assert len(cb_webhook.start_calls) == 0

    @pytest.mark.asyncio()
    async def test_team_multiple_callbacks(
        self,
        global_manager: CallbackManager,
        cb_spend: StubCallback,
        cb_langfuse: StubCallback,
        cb_webhook: StubCallback,
        start_data: RequestStartData,
    ) -> None:
        """Team with multiple callbacks fires exactly those."""
        tcm = TeamCallbackManager(
            global_manager,
            team_configs={
                "team-a": TeamLoggingConfig(callbacks=["spend_log", "webhook"]),
            },
        )
        await tcm.dispatch(CallbackEvent.REQUEST_START, start_data, team_id="team-a")
        assert len(cb_spend.start_calls) == 1
        assert len(cb_webhook.start_calls) == 1
        assert len(cb_langfuse.start_calls) == 0

    @pytest.mark.asyncio()
    async def test_team_empty_callbacks_list_fires_nothing(
        self,
        global_manager: CallbackManager,
        cb_spend: StubCallback,
        start_data: RequestStartData,
    ) -> None:
        """Empty callbacks list overrides global to fire nothing."""
        tcm = TeamCallbackManager(
            global_manager,
            team_configs={
                "team-a": TeamLoggingConfig(callbacks=[]),
            },
        )
        await tcm.dispatch(CallbackEvent.REQUEST_START, start_data, team_id="team-a")
        assert len(cb_spend.start_calls) == 0

    @pytest.mark.asyncio()
    async def test_missing_named_callback_skipped(
        self,
        global_manager: CallbackManager,
        cb_langfuse: StubCallback,
        start_data: RequestStartData,
    ) -> None:
        """Callback name not registered globally is skipped with a warning."""
        tcm = TeamCallbackManager(
            global_manager,
            team_configs={
                "team-a": TeamLoggingConfig(callbacks=["nonexistent", "langfuse"]),
            },
        )
        await tcm.dispatch(CallbackEvent.REQUEST_START, start_data, team_id="team-a")
        # langfuse fires, nonexistent is just skipped
        assert len(cb_langfuse.start_calls) == 1

    @pytest.mark.asyncio()
    async def test_request_end_event(
        self,
        global_manager: CallbackManager,
        cb_spend: StubCallback,
        end_data: RequestEndData,
    ) -> None:
        """Other event types (REQUEST_END) dispatch correctly."""
        tcm = TeamCallbackManager(
            global_manager,
            team_configs={
                "team-a": TeamLoggingConfig(callbacks=["spend_log"]),
            },
        )
        await tcm.dispatch(CallbackEvent.REQUEST_END, end_data, team_id="team-a")
        assert len(cb_spend.end_calls) == 1

    @pytest.mark.asyncio()
    async def test_request_error_event(
        self,
        global_manager: CallbackManager,
        cb_spend: StubCallback,
    ) -> None:
        tcm = TeamCallbackManager(
            global_manager,
            team_configs={
                "team-a": TeamLoggingConfig(callbacks=["spend_log"]),
            },
        )
        error_data = RequestErrorData(
            request_id="req-e",
            model="gpt-4o",
            error="fail",
            error_type="TestError",
        )
        await tcm.dispatch(CallbackEvent.REQUEST_ERROR, error_data, team_id="team-a")
        assert len(cb_spend.error_calls) == 1


# ===================================================================
# Config management tests
# ===================================================================


class TestTeamConfigManagement:
    def test_set_team_config(self, global_manager: CallbackManager) -> None:
        tcm = TeamCallbackManager(global_manager)
        config = TeamLoggingConfig(callbacks=["langfuse"])
        tcm.set_team_config("team-x", config)
        assert tcm.get_team_config("team-x") is config

    def test_remove_team_config(self, global_manager: CallbackManager) -> None:
        tcm = TeamCallbackManager(global_manager)
        tcm.set_team_config("team-x", TeamLoggingConfig())
        assert tcm.remove_team_config("team-x") is True
        assert tcm.get_team_config("team-x") is None

    def test_remove_nonexistent(self, global_manager: CallbackManager) -> None:
        tcm = TeamCallbackManager(global_manager)
        assert tcm.remove_team_config("no-such-team") is False

    def test_get_nonexistent(self, global_manager: CallbackManager) -> None:
        tcm = TeamCallbackManager(global_manager)
        assert tcm.get_team_config("no-such-team") is None

    @pytest.mark.asyncio()
    async def test_update_config_changes_behavior(
        self,
        global_manager: CallbackManager,
        cb_spend: StubCallback,
        cb_langfuse: StubCallback,
        start_data: RequestStartData,
    ) -> None:
        """Updating team config changes which callbacks fire."""
        tcm = TeamCallbackManager(global_manager)

        # Initially no config — global fires
        await tcm.dispatch(CallbackEvent.REQUEST_START, start_data, team_id="team-a")
        assert len(cb_spend.start_calls) == 1
        assert len(cb_langfuse.start_calls) == 1

        # Now disable logging
        tcm.set_team_config("team-a", TeamLoggingConfig(disable_logging=True))
        await tcm.dispatch(CallbackEvent.REQUEST_START, start_data, team_id="team-a")
        assert len(cb_spend.start_calls) == 1  # no new calls
        assert len(cb_langfuse.start_calls) == 1

        # Now restrict to langfuse only
        tcm.set_team_config("team-a", TeamLoggingConfig(callbacks=["langfuse"]))
        await tcm.dispatch(CallbackEvent.REQUEST_START, start_data, team_id="team-a")
        assert len(cb_spend.start_calls) == 1  # still no new
        assert len(cb_langfuse.start_calls) == 2  # one more

        # Remove override — back to global
        tcm.remove_team_config("team-a")
        await tcm.dispatch(CallbackEvent.REQUEST_START, start_data, team_id="team-a")
        assert len(cb_spend.start_calls) == 2
        assert len(cb_langfuse.start_calls) == 3


# ===================================================================
# TeamLoggingConfig dataclass tests
# ===================================================================


class TestTeamLoggingConfigDefaults:
    def test_defaults(self) -> None:
        config = TeamLoggingConfig()
        assert config.disable_logging is False
        assert config.callbacks is None
        assert config.langfuse_public_key is None
        assert config.langfuse_secret_key is None
        assert config.langfuse_host is None
        assert config.webhook_url is None
        assert config.webhook_headers == {}
        assert config.extra == {}

    def test_custom_values(self) -> None:
        config = TeamLoggingConfig(
            disable_logging=True,
            callbacks=["spend_log"],
            langfuse_public_key="pk",
            webhook_url="https://x.com",
            webhook_headers={"X-Key": "val"},
            extra={"foo": "bar"},
        )
        assert config.disable_logging is True
        assert config.callbacks == ["spend_log"]
        assert config.extra == {"foo": "bar"}
