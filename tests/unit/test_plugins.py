"""Tests for the plugin architecture (Task 8D.1)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from routerbot.core.plugins.hooks import (
    AuthHook,
    CallbackHook,
    GuardrailHook,
    MiddlewareHook,
    PluginHook,
    ProviderHook,
)
from routerbot.core.plugins.manager import PluginManager, _resolve_hook_type
from routerbot.core.plugins.models import (
    PluginConfig,
    PluginInfo,
    PluginStatus,
    PluginType,
)
from routerbot.core.plugins.registry import PluginRegistry


# ── Sample concrete hooks for testing ───────────────────────────────


class SampleProviderHook(ProviderHook):
    name = "sample-provider"
    version = "1.0.0"
    description = "Test provider plugin"
    author = "test"

    def get_provider_classes(self) -> dict[str, type]:
        return {"sample": object}


class SampleGuardrailHook(GuardrailHook):
    name = "sample-guardrail"
    version = "1.0.0"
    description = "Test guardrail plugin"

    async def check(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"passed": True}


class SampleCallbackHook(CallbackHook):
    name = "sample-callback"
    version = "1.0.0"

    async def on_request_start(self, data: dict[str, Any]) -> None:
        pass

    async def on_request_end(self, data: dict[str, Any]) -> None:
        pass


class SampleAuthHook(AuthHook):
    name = "sample-auth"
    version = "1.0.0"

    async def authenticate(
        self,
        headers: dict[str, str],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"authenticated": True, "identity": "test-user"}


class SampleMiddlewareHook(MiddlewareHook):
    name = "sample-middleware"
    version = "1.0.0"
    priority = 50

    async def before_request(self, request: dict[str, Any]) -> dict[str, Any]:
        request["modified"] = True
        return request

    async def after_response(self, response: dict[str, Any]) -> dict[str, Any]:
        response["post_processed"] = True
        return response


class FailingSetupHook(MiddlewareHook):
    """A plugin whose setup() raises an exception."""

    name = "failing-plugin"
    version = "0.1.0"

    async def setup(self) -> None:
        msg = "Intentional setup failure"
        raise RuntimeError(msg)

    async def before_request(self, request: dict[str, Any]) -> dict[str, Any]:
        return request

    async def after_response(self, response: dict[str, Any]) -> dict[str, Any]:
        return response


# ── Model tests ──────────────────────────────────────────────────────


class TestModels:
    """Validate plugin models and enums."""

    def test_plugin_type_values(self) -> None:
        assert PluginType.PROVIDER == "provider"
        assert PluginType.GUARDRAIL == "guardrail"
        assert PluginType.CALLBACK == "callback"
        assert PluginType.AUTH == "auth"
        assert PluginType.MIDDLEWARE == "middleware"

    def test_plugin_status_values(self) -> None:
        assert PluginStatus.DISCOVERED == "discovered"
        assert PluginStatus.LOADED == "loaded"
        assert PluginStatus.ACTIVE == "active"
        assert PluginStatus.ERROR == "error"
        assert PluginStatus.DISABLED == "disabled"

    def test_plugin_info_defaults(self) -> None:
        info = PluginInfo(name="test", plugin_type=PluginType.PROVIDER)
        assert info.name == "test"
        assert info.version == "0.0.0"
        assert info.status == PluginStatus.DISCOVERED
        assert info.error_message is None
        assert info.loaded_at is None
        assert info.config == {}

    def test_plugin_info_activate(self) -> None:
        info = PluginInfo(name="test", plugin_type=PluginType.PROVIDER)
        info.activate()
        assert info.status == PluginStatus.ACTIVE
        assert info.loaded_at is not None

    def test_plugin_info_fail(self) -> None:
        info = PluginInfo(name="test", plugin_type=PluginType.PROVIDER)
        info.fail("something went wrong")
        assert info.status == PluginStatus.ERROR
        assert info.error_message == "something went wrong"

    def test_plugin_config_defaults(self) -> None:
        cfg = PluginConfig()
        assert cfg.enabled is False
        assert cfg.auto_discover is True
        assert cfg.entry_point_group == "routerbot.plugins"
        assert cfg.plugins == []
        assert cfg.disabled_plugins == []

    def test_plugin_config_from_dict(self) -> None:
        cfg = PluginConfig(
            **{
                "enabled": True,
                "auto_discover": False,
                "disabled_plugins": ["bad-plugin"],
                "plugins": [
                    {
                        "name": "custom",
                        "module": "mymodule",
                        "class": "MyHook",
                    },
                ],
            }
        )
        assert cfg.enabled is True
        assert cfg.auto_discover is False
        assert len(cfg.plugins) == 1
        assert cfg.disabled_plugins == ["bad-plugin"]


# ── PluginHook tests ────────────────────────────────────────────────


class TestPluginHook:
    """Test the base PluginHook class and concrete hook types."""

    def test_base_hook_config(self) -> None:
        hook = SampleMiddlewareHook(config={"key": "value"})
        assert hook.config == {"key": "value"}

    def test_base_hook_default_config(self) -> None:
        hook = SampleMiddlewareHook()
        assert hook.config == {}

    def test_get_info(self) -> None:
        hook = SampleProviderHook()
        info = hook.get_info()
        assert info["name"] == "sample-provider"
        assert info["version"] == "1.0.0"
        assert info["hook_type"] == "SampleProviderHook"

    async def test_setup_teardown_default(self) -> None:
        hook = SampleMiddlewareHook()
        # Default setup/teardown should not raise
        await hook.setup()
        await hook.teardown()

    def test_provider_hook_get_classes(self) -> None:
        hook = SampleProviderHook()
        classes = hook.get_provider_classes()
        assert "sample" in classes

    async def test_guardrail_hook_check(self) -> None:
        hook = SampleGuardrailHook()
        result = await hook.check([{"role": "user", "content": "test"}])
        assert result["passed"] is True

    async def test_callback_hook(self) -> None:
        hook = SampleCallbackHook()
        await hook.on_request_start({"test": True})
        await hook.on_request_end({"test": True})
        # on_error is optional — should not raise
        await hook.on_error({"test": True})

    async def test_auth_hook(self) -> None:
        hook = SampleAuthHook()
        result = await hook.authenticate({"Authorization": "Bearer xyz"})
        assert result["authenticated"] is True
        assert result["identity"] == "test-user"

    async def test_middleware_hook(self) -> None:
        hook = SampleMiddlewareHook()
        req = await hook.before_request({"model": "gpt-4"})
        assert req["modified"] is True

        resp = await hook.after_response({"content": "hello"})
        assert resp["post_processed"] is True

    def test_middleware_priority(self) -> None:
        hook = SampleMiddlewareHook()
        assert hook.priority == 50


# ── PluginRegistry tests ────────────────────────────────────────────


class TestPluginRegistry:
    """Test the PluginRegistry class."""

    def test_register_and_get(self) -> None:
        reg = PluginRegistry()
        hook = SampleProviderHook()
        info = PluginInfo(
            name="sample-provider",
            plugin_type=PluginType.PROVIDER,
            status=PluginStatus.ACTIVE,
        )
        reg.register(hook, info)

        assert reg.get("sample-provider") is hook
        assert reg.get_info("sample-provider") is info
        assert reg.count == 1

    def test_unregister(self) -> None:
        reg = PluginRegistry()
        hook = SampleGuardrailHook()
        info = PluginInfo(name="sample-guardrail", plugin_type=PluginType.GUARDRAIL)
        reg.register(hook, info)

        assert reg.unregister("sample-guardrail") is True
        assert reg.get("sample-guardrail") is None
        assert reg.count == 0

    def test_unregister_nonexistent(self) -> None:
        reg = PluginRegistry()
        assert reg.unregister("nonexistent") is False

    def test_list_plugins(self) -> None:
        reg = PluginRegistry()
        for name, ptype in [
            ("p1", PluginType.PROVIDER),
            ("p2", PluginType.GUARDRAIL),
            ("p3", PluginType.PROVIDER),
        ]:
            hook = SampleProviderHook() if ptype == PluginType.PROVIDER else SampleGuardrailHook()
            info = PluginInfo(name=name, plugin_type=ptype)
            reg.register(hook, info)

        all_plugins = reg.list_plugins()
        assert len(all_plugins) == 3

        providers = reg.list_plugins(plugin_type=PluginType.PROVIDER)
        assert len(providers) == 2

    def test_list_plugins_by_status(self) -> None:
        reg = PluginRegistry()
        info1 = PluginInfo(name="active", plugin_type=PluginType.PROVIDER, status=PluginStatus.ACTIVE)
        info2 = PluginInfo(name="error", plugin_type=PluginType.PROVIDER, status=PluginStatus.ERROR)
        reg.register(SampleProviderHook(), info1)
        reg.register(SampleProviderHook(), info2)

        active = reg.list_plugins(status=PluginStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].name == "active"

    def test_get_hooks_by_type(self) -> None:
        reg = PluginRegistry()
        hook = SampleGuardrailHook()
        info = PluginInfo(
            name="guardrail",
            plugin_type=PluginType.GUARDRAIL,
            status=PluginStatus.ACTIVE,
        )
        reg.register(hook, info)

        hooks = reg.get_hooks_by_type(PluginType.GUARDRAIL)
        assert len(hooks) == 1
        assert hooks[0] is hook

        # Inactive hooks should not be returned
        empty = reg.get_hooks_by_type(PluginType.PROVIDER)
        assert empty == []

    def test_all_names(self) -> None:
        reg = PluginRegistry()
        reg.register(
            SampleProviderHook(),
            PluginInfo(name="a", plugin_type=PluginType.PROVIDER),
        )
        reg.register(
            SampleCallbackHook(),
            PluginInfo(name="b", plugin_type=PluginType.CALLBACK),
        )
        assert set(reg.all_names) == {"a", "b"}

    def test_summary(self) -> None:
        reg = PluginRegistry()
        info = PluginInfo(name="test", plugin_type=PluginType.AUTH)
        reg.register(SampleAuthHook(), info)

        summary = reg.summary()
        assert len(summary) == 1
        assert summary[0]["name"] == "test"

    def test_clear(self) -> None:
        reg = PluginRegistry()
        reg.register(
            SampleProviderHook(),
            PluginInfo(name="a", plugin_type=PluginType.PROVIDER),
        )
        reg.clear()
        assert reg.count == 0

    def test_replace_existing(self) -> None:
        reg = PluginRegistry()
        hook1 = SampleProviderHook()
        hook2 = SampleProviderHook()
        info = PluginInfo(name="same", plugin_type=PluginType.PROVIDER)

        reg.register(hook1, info)
        reg.register(hook2, info)

        assert reg.get("same") is hook2
        assert reg.count == 1


# ── PluginManager tests ─────────────────────────────────────────────


class TestPluginManager:
    """Test the PluginManager class."""

    def test_default_config(self) -> None:
        mgr = PluginManager()
        assert mgr.config.enabled is False
        assert mgr.config.auto_discover is True

    def test_custom_config(self) -> None:
        cfg = PluginConfig(enabled=True, auto_discover=False)
        mgr = PluginManager(cfg)
        assert mgr.config.enabled is True
        assert mgr.config.auto_discover is False

    async def test_register_hook(self) -> None:
        mgr = PluginManager(PluginConfig(enabled=True, auto_discover=False))
        hook = SampleGuardrailHook()
        info = await mgr.register_hook(hook)

        assert info.name == "sample-guardrail"
        assert info.status == PluginStatus.ACTIVE
        assert info.plugin_type == PluginType.GUARDRAIL
        assert mgr.registry.count == 1

    async def test_register_hook_no_auto_setup(self) -> None:
        mgr = PluginManager(PluginConfig(enabled=True, auto_discover=False))
        hook = SampleCallbackHook()
        info = await mgr.register_hook(hook, auto_setup=False)

        assert info.status == PluginStatus.LOADED

    async def test_register_failing_hook(self) -> None:
        mgr = PluginManager(PluginConfig(enabled=True, auto_discover=False))
        hook = FailingSetupHook()
        info = await mgr.register_hook(hook)

        assert info.status == PluginStatus.ERROR
        assert "setup() failed" in (info.error_message or "")

    async def test_load_all_no_discover(self) -> None:
        cfg = PluginConfig(enabled=True, auto_discover=False)
        mgr = PluginManager(cfg)
        loaded = await mgr.load_all()
        assert loaded == []

    async def test_load_config_plugins(self) -> None:
        cfg = PluginConfig(
            enabled=True,
            auto_discover=False,
            plugins=[
                {
                    "name": "sample-middleware",
                    "module": "tests.unit.test_plugins",
                    "class": "SampleMiddlewareHook",
                },
            ],
        )
        mgr = PluginManager(cfg)
        loaded = await mgr.load_all()

        assert len(loaded) == 1
        assert loaded[0].name == "sample-middleware"
        assert loaded[0].status == PluginStatus.ACTIVE

    async def test_load_config_plugin_with_config(self) -> None:
        cfg = PluginConfig(
            enabled=True,
            auto_discover=False,
            plugins=[
                {
                    "name": "configured",
                    "module": "tests.unit.test_plugins",
                    "class": "SampleMiddlewareHook",
                    "config": {"key": "value"},
                },
            ],
        )
        mgr = PluginManager(cfg)
        loaded = await mgr.load_all()

        hook = mgr.registry.get("sample-middleware")
        assert hook is not None
        assert hook.config == {"key": "value"}

    async def test_skip_disabled_plugins(self) -> None:
        cfg = PluginConfig(
            enabled=True,
            auto_discover=False,
            disabled_plugins=["sample-disabled"],
            plugins=[
                {
                    "name": "sample-disabled",
                    "module": "tests.unit.test_plugins",
                    "class": "SampleMiddlewareHook",
                },
            ],
        )
        mgr = PluginManager(cfg)
        loaded = await mgr.load_all()
        assert loaded == []

    async def test_missing_module_gracefully_handled(self) -> None:
        cfg = PluginConfig(
            enabled=True,
            auto_discover=False,
            plugins=[
                {
                    "name": "bad-import",
                    "module": "nonexistent.module",
                    "class": "FakeHook",
                },
            ],
        )
        mgr = PluginManager(cfg)
        loaded = await mgr.load_all()
        # Should not crash, just skip
        assert loaded == []

    async def test_invalid_class_gracefully_handled(self) -> None:
        cfg = PluginConfig(
            enabled=True,
            auto_discover=False,
            plugins=[
                {
                    "name": "bad-class",
                    "module": "tests.unit.test_plugins",
                    "class": "NonExistentClass",
                },
            ],
        )
        mgr = PluginManager(cfg)
        loaded = await mgr.load_all()
        assert loaded == []

    async def test_skip_plugin_missing_name(self) -> None:
        cfg = PluginConfig(
            enabled=True,
            auto_discover=False,
            plugins=[{"module": "test", "class": "Test"}],
        )
        mgr = PluginManager(cfg)
        loaded = await mgr.load_all()
        assert loaded == []

    async def test_skip_plugin_missing_module(self) -> None:
        cfg = PluginConfig(
            enabled=True,
            auto_discover=False,
            plugins=[{"name": "test", "class": "Test"}],
        )
        mgr = PluginManager(cfg)
        loaded = await mgr.load_all()
        assert loaded == []

    async def test_shutdown(self) -> None:
        mgr = PluginManager(PluginConfig(enabled=True, auto_discover=False))
        hook = SampleMiddlewareHook()
        hook.teardown = AsyncMock()  # type: ignore[method-assign]
        await mgr.register_hook(hook)

        await mgr.shutdown()
        hook.teardown.assert_called_once()

    async def test_shutdown_handles_errors(self) -> None:
        mgr = PluginManager(PluginConfig(enabled=True, auto_discover=False))
        hook = SampleMiddlewareHook()
        hook.teardown = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        await mgr.register_hook(hook)

        # Should not raise
        await mgr.shutdown()

    async def test_entry_point_discovery(self) -> None:
        """Test that entry-point discovery works (mocked)."""
        from importlib.metadata import EntryPoint

        mock_ep = EntryPoint(
            name="mock-plugin",
            value="tests.unit.test_plugins:SampleMiddlewareHook",
            group="routerbot.plugins",
        )

        cfg = PluginConfig(enabled=True, auto_discover=True)
        mgr = PluginManager(cfg)

        # Mock entry_points to return our test entry point
        class MockSelectableGroups:
            def select(self, group: str) -> list:
                if group == "routerbot.plugins":
                    return [mock_ep]
                return []

        with patch(
            "routerbot.core.plugins.manager.entry_points",
            return_value=MockSelectableGroups(),
        ):
            loaded = await mgr.load_all()

        assert len(loaded) >= 1
        names = [p.name for p in loaded]
        assert "sample-middleware" in names

    async def test_entry_point_disabled_plugin_skipped(self) -> None:
        """Disabled plugins should be skipped during entry-point discovery."""
        from importlib.metadata import EntryPoint

        mock_ep = EntryPoint(
            name="disabled-ep",
            value="tests.unit.test_plugins:SampleMiddlewareHook",
            group="routerbot.plugins",
        )

        cfg = PluginConfig(
            enabled=True,
            auto_discover=True,
            disabled_plugins=["disabled-ep"],
        )
        mgr = PluginManager(cfg)

        class MockSelectableGroups:
            def select(self, group: str) -> list:
                return [mock_ep] if group == "routerbot.plugins" else []

        with patch(
            "routerbot.core.plugins.manager.entry_points",
            return_value=MockSelectableGroups(),
        ):
            loaded = await mgr.load_all()

        assert loaded == []


# ── _resolve_hook_type tests ─────────────────────────────────────────


class TestResolveHookType:
    def test_provider(self) -> None:
        assert _resolve_hook_type(SampleProviderHook()) == PluginType.PROVIDER

    def test_guardrail(self) -> None:
        assert _resolve_hook_type(SampleGuardrailHook()) == PluginType.GUARDRAIL

    def test_callback(self) -> None:
        assert _resolve_hook_type(SampleCallbackHook()) == PluginType.CALLBACK

    def test_auth(self) -> None:
        assert _resolve_hook_type(SampleAuthHook()) == PluginType.AUTH

    def test_middleware(self) -> None:
        assert _resolve_hook_type(SampleMiddlewareHook()) == PluginType.MIDDLEWARE

    def test_unknown_type_raises(self) -> None:
        hook = PluginHook()
        with pytest.raises(TypeError, match="Unknown hook type"):
            _resolve_hook_type(hook)


# ── Integration tests ────────────────────────────────────────────────


class TestPluginIntegration:
    """End-to-end plugin lifecycle tests."""

    async def test_full_lifecycle(self) -> None:
        """Test discover → load → use → shutdown."""
        cfg = PluginConfig(
            enabled=True,
            auto_discover=False,
            plugins=[
                {
                    "name": "test-guardrail",
                    "module": "tests.unit.test_plugins",
                    "class": "SampleGuardrailHook",
                },
                {
                    "name": "test-middleware",
                    "module": "tests.unit.test_plugins",
                    "class": "SampleMiddlewareHook",
                },
            ],
        )
        mgr = PluginManager(cfg)
        loaded = await mgr.load_all()

        assert len(loaded) == 2
        assert all(p.status == PluginStatus.ACTIVE for p in loaded)

        # Query by type
        guardrails = mgr.registry.get_hooks_by_type(PluginType.GUARDRAIL)
        assert len(guardrails) == 1

        middlewares = mgr.registry.get_hooks_by_type(PluginType.MIDDLEWARE)
        assert len(middlewares) == 1

        # Use the guardrail
        result = await guardrails[0].check([{"role": "user", "content": "hi"}])  # type: ignore[attr-defined]
        assert result["passed"] is True

        # Use the middleware
        req = await middlewares[0].before_request({"model": "gpt-4"})  # type: ignore[attr-defined]
        assert req["modified"] is True

        # Shutdown
        await mgr.shutdown()

    async def test_multiple_hooks_same_type(self) -> None:
        mgr = PluginManager(PluginConfig(enabled=True, auto_discover=False))

        hook1 = SampleGuardrailHook()
        hook1.name = "guard-1"
        hook2 = SampleGuardrailHook()
        hook2.name = "guard-2"

        await mgr.register_hook(hook1)
        await mgr.register_hook(hook2)

        guards = mgr.registry.get_hooks_by_type(PluginType.GUARDRAIL)
        assert len(guards) == 2

    async def test_config_dict_construction(self) -> None:
        """Test constructing PluginConfig from a dict (as done in app.py)."""
        config_dict = {
            "enabled": True,
            "auto_discover": False,
            "plugins": [
                {
                    "name": "test",
                    "module": "tests.unit.test_plugins",
                    "class": "SampleProviderHook",
                },
            ],
        }
        cfg = PluginConfig(**config_dict)
        mgr = PluginManager(cfg)
        loaded = await mgr.load_all()

        assert len(loaded) == 1
        assert loaded[0].plugin_type == PluginType.PROVIDER

    async def test_summary_output(self) -> None:
        mgr = PluginManager(PluginConfig(enabled=True, auto_discover=False))
        await mgr.register_hook(SampleAuthHook())

        summary = mgr.registry.summary()
        assert len(summary) == 1
        assert summary[0]["name"] == "sample-auth"
        assert summary[0]["plugin_type"] == "auth"
