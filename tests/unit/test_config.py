"""Tests for the configuration system."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

from routerbot.core.config import (
    _coerce_value,
    _deep_merge,
    _resolve_env_refs,
    load_config,
    reset_config,
)
from routerbot.core.config_models import (
    CacheType,
    RouterBotConfig,
    RoutingStrategy,
)


@pytest.fixture(autouse=True)
def _reset_config() -> None:
    """Reset config singleton before each test."""
    reset_config()


# ─── Config Model Tests ──────────────────────────────────────


class TestRouterBotConfig:
    """Test configuration model validation."""

    def test_default_config(self) -> None:
        """Default config should have sensible defaults."""
        config = RouterBotConfig()
        assert config.general_settings.port == 4000
        assert config.general_settings.host == "0.0.0.0"  # noqa: S104
        assert config.general_settings.num_workers == 1
        assert config.general_settings.request_timeout == 600
        assert config.router_settings.routing_strategy == RoutingStrategy.ROUND_ROBIN
        assert config.router_settings.num_retries == 3
        assert config.routerbot_settings.cache is False
        assert config.model_list == []

    def test_custom_general_settings(self) -> None:
        """Custom general settings should be parsed correctly."""
        config = RouterBotConfig(
            general_settings={
                "port": 8080,
                "host": "127.0.0.1",
                "log_level": "DEBUG",
                "master_key": "sk-test-key",
            }
        )
        assert config.general_settings.port == 8080
        assert config.general_settings.host == "127.0.0.1"
        assert config.general_settings.log_level == "DEBUG"
        assert config.general_settings.master_key == "sk-test-key"

    def test_model_entry_parsing(self) -> None:
        """Model entries should be parsed correctly."""
        config = RouterBotConfig(
            model_list=[
                {
                    "model_name": "gpt-4o",
                    "provider_params": {
                        "model": "openai/gpt-4o",
                        "api_key": "sk-test",
                        "rpm": 100,
                    },
                    "model_info": {
                        "max_input_tokens": 128000,
                        "input_cost_per_token": 0.0000025,
                    },
                }
            ]
        )
        assert len(config.model_list) == 1
        entry = config.model_list[0]
        assert entry.model_name == "gpt-4o"
        assert entry.provider_params.model == "openai/gpt-4o"
        assert entry.provider_params.api_key == "sk-test"
        assert entry.provider_params.rpm == 100
        assert entry.model_info is not None
        assert entry.model_info.max_input_tokens == 128000

    def test_router_settings(self) -> None:
        """Router settings should be parsed correctly."""
        config = RouterBotConfig(
            router_settings={
                "routing_strategy": "latency-based",
                "num_retries": 5,
                "fallbacks": {"gpt-4o": ["gpt-4o-mini", "claude-sonnet"]},
            }
        )
        assert config.router_settings.routing_strategy == RoutingStrategy.LEAST_LATENCY
        assert config.router_settings.num_retries == 5
        assert config.router_settings.fallbacks == {"gpt-4o": ["gpt-4o-mini", "claude-sonnet"]}

    def test_invalid_port_raises(self) -> None:
        """Invalid port should raise validation error."""
        with pytest.raises(Exception):  # noqa: B017
            RouterBotConfig(general_settings={"port": 99999})

    def test_cache_settings(self) -> None:
        """Cache settings should parse cache type enum."""
        config = RouterBotConfig(
            routerbot_settings={
                "cache": True,
                "cache_params": {
                    "type": "redis",
                    "ttl": 7200,
                    "namespace": "myapp",
                },
            }
        )
        assert config.routerbot_settings.cache is True
        assert config.routerbot_settings.cache_params.type == CacheType.REDIS
        assert config.routerbot_settings.cache_params.ttl == 7200


# ─── YAML Loading Tests ─────────────────────────────────────


class TestLoadConfig:
    """Test config loading from YAML files."""

    def _write_yaml(self, data: dict[str, Any], path: Path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

    def test_load_from_yaml(self, tmp_path: Path) -> None:
        """Config should load from a YAML file."""
        config_file = tmp_path / "routerbot_config.yaml"
        self._write_yaml(
            {
                "general_settings": {"port": 9090, "log_level": "DEBUG"},
                "model_list": [
                    {
                        "model_name": "test-model",
                        "provider_params": {"model": "openai/gpt-4o", "api_key": "sk-test"},
                    }
                ],
            },
            config_file,
        )

        config = load_config(config_path=config_file)
        assert config.general_settings.port == 9090
        assert config.general_settings.log_level == "DEBUG"
        assert len(config.model_list) == 1
        assert config.model_list[0].model_name == "test-model"

    def test_load_missing_file_raises(self) -> None:
        """Loading a nonexistent file should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(config_path="/nonexistent/config.yaml")

    def test_load_empty_yaml(self, tmp_path: Path) -> None:
        """Empty YAML file should return default config."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("", encoding="utf-8")
        config = load_config(config_path=config_file)
        assert config.general_settings.port == 4000

    def test_load_from_dict(self) -> None:
        """Config should load from a provided dict."""
        config = load_config(config_data={"general_settings": {"port": 5555}})
        assert config.general_settings.port == 5555

    def test_default_paths_no_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no config file exists, defaults should be used."""
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert config.general_settings.port == 4000


# ─── Environment Variable Override Tests ─────────────────────


class TestEnvOverrides:
    """Test environment variable overrides with ROUTERBOT_ prefix."""

    def test_env_override_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ROUTERBOT_GENERAL_SETTINGS__PORT should override port."""
        monkeypatch.setenv("ROUTERBOT_GENERAL_SETTINGS__PORT", "8080")
        config = load_config(config_data={})
        assert config.general_settings.port == 8080

    def test_env_override_log_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ROUTERBOT_GENERAL_SETTINGS__LOG_LEVEL should override log_level."""
        monkeypatch.setenv("ROUTERBOT_GENERAL_SETTINGS__LOG_LEVEL", "DEBUG")
        config = load_config(config_data={})
        assert config.general_settings.log_level == "DEBUG"

    def test_env_override_nested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nested env overrides should work."""
        monkeypatch.setenv("ROUTERBOT_ROUTER_SETTINGS__NUM_RETRIES", "5")
        config = load_config(config_data={})
        assert config.router_settings.num_retries == 5


# ─── Secret Resolution Tests ─────────────────────────────────


class TestSecretResolution:
    """Test os.environ/VAR_NAME resolution."""

    def test_resolve_env_ref(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """os.environ/VAR_NAME should be resolved from environment."""
        monkeypatch.setenv("MY_API_KEY", "sk-secret-123")
        result = _resolve_env_refs("os.environ/MY_API_KEY")
        assert result == "sk-secret-123"

    def test_resolve_env_ref_in_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env refs in nested dicts should be resolved."""
        monkeypatch.setenv("MY_KEY", "resolved-value")
        data = {"outer": {"inner": "os.environ/MY_KEY", "static": "unchanged"}}
        result = _resolve_env_refs(data)
        assert result == {"outer": {"inner": "resolved-value", "static": "unchanged"}}

    def test_resolve_env_ref_in_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env refs in lists should be resolved."""
        monkeypatch.setenv("ITEM_KEY", "resolved")
        data = ["os.environ/ITEM_KEY", "static"]
        result = _resolve_env_refs(data)
        assert result == ["resolved", "static"]

    def test_missing_env_ref_raises(self) -> None:
        """Missing env ref should raise ValueError."""
        # Ensure the var is NOT set
        os.environ.pop("NONEXISTENT_VAR_12345", None)
        with pytest.raises(ValueError, match="Environment variable 'NONEXISTENT_VAR_12345'"):
            _resolve_env_refs("os.environ/NONEXISTENT_VAR_12345")

    def test_non_env_ref_string_unchanged(self) -> None:
        """Regular strings should not be affected."""
        assert _resolve_env_refs("just a normal string") == "just a normal string"

    def test_full_config_with_env_refs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Full config loading should resolve env refs in model entries."""
        monkeypatch.setenv("TEST_OPENAI_KEY", "sk-resolved")
        config = load_config(
            config_data={
                "model_list": [
                    {
                        "model_name": "gpt-4o",
                        "provider_params": {
                            "model": "openai/gpt-4o",
                            "api_key": "os.environ/TEST_OPENAI_KEY",
                        },
                    }
                ]
            }
        )
        assert config.model_list[0].provider_params.api_key == "sk-resolved"


# ─── Helper Function Tests ────────────────────────────────────


class TestDeepMerge:
    """Test deep merge utility."""

    def test_simple_merge(self) -> None:
        """Simple dict merge should work."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        assert _deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        """Nested dicts should be merged recursively."""
        base = {"outer": {"a": 1, "b": 2}}
        override = {"outer": {"b": 3, "c": 4}}
        assert _deep_merge(base, override) == {"outer": {"a": 1, "b": 3, "c": 4}}

    def test_override_replaces_non_dict(self) -> None:
        """Non-dict values should be replaced entirely."""
        base = {"a": [1, 2, 3]}
        override = {"a": [4, 5]}
        assert _deep_merge(base, override) == {"a": [4, 5]}


class TestCoerceValue:
    """Test value coercion from strings."""

    def test_coerce_true(self) -> None:
        assert _coerce_value("true") is True
        assert _coerce_value("True") is True
        assert _coerce_value("yes") is True
        assert _coerce_value("1") == 1  # int takes precedence

    def test_coerce_false(self) -> None:
        assert _coerce_value("false") is False
        assert _coerce_value("False") is False
        assert _coerce_value("no") is False
        assert _coerce_value("0") == 0  # int takes precedence

    def test_coerce_int(self) -> None:
        assert _coerce_value("42") == 42
        assert _coerce_value("-5") == -5

    def test_coerce_float(self) -> None:
        assert _coerce_value("3.14") == pytest.approx(3.14)

    def test_coerce_string(self) -> None:
        assert _coerce_value("hello") == "hello"
        assert _coerce_value("some value with spaces") == "some value with spaces"
