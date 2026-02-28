"""Tests for the AI Hub & Playground module (Task 8H)."""

from __future__ import annotations

import random
from typing import Any

import pytest

from routerbot.hub.model_hub import ModelHub
from routerbot.hub.models import (
    ComparisonRequest,
    ComparisonResponse,
    ComparisonResult,
    HubConfig,
    ModelCapability,
    ModelCatalogue,
    ModelInfo,
    ModelPricing,
    PlaygroundMessage,
    PlaygroundRequest,
    PlaygroundResponse,
    PlaygroundSession,
    PlaygroundStatus,
    PromptABTest,
    PromptAnalytics,
    PromptStatus,
    PromptTemplate,
    PromptVariable,
    PromptVersion,
)
from routerbot.hub.playground import (
    Playground,
    PlaygroundCapacityError,
    PlaygroundSessionError,
)
from routerbot.hub.prompt_manager import (
    PromptCapacityError,
    PromptManager,
    PromptNotFoundError,
    PromptRenderError,
)

# ── Model tests ──────────────────────────────────────────────────────────


class TestModels:
    """Tests for hub Pydantic models."""

    def test_model_capability_values(self) -> None:
        assert ModelCapability.CHAT == "chat"
        assert ModelCapability.VISION == "vision"
        assert ModelCapability.CODE == "code"
        assert ModelCapability.FUNCTION_CALLING == "function_calling"

    def test_playground_status_values(self) -> None:
        assert PlaygroundStatus.ACTIVE == "active"
        assert PlaygroundStatus.COMPLETED == "completed"
        assert PlaygroundStatus.FAILED == "failed"

    def test_prompt_status_values(self) -> None:
        assert PromptStatus.DRAFT == "draft"
        assert PromptStatus.ACTIVE == "active"
        assert PromptStatus.ARCHIVED == "archived"

    def test_model_pricing_defaults(self) -> None:
        p = ModelPricing()
        assert p.input_cost_per_1k == 0.0
        assert p.output_cost_per_1k == 0.0
        assert p.currency == "USD"

    def test_model_info(self) -> None:
        info = ModelInfo(
            model_id="openai/gpt-4o",
            provider="openai",
            display_name="GPT-4o",
            capabilities=[ModelCapability.CHAT, ModelCapability.VISION],
            pricing=ModelPricing(input_cost_per_1k=0.0025, output_cost_per_1k=0.01),
            context_window=128000,
        )
        assert info.model_id == "openai/gpt-4o"
        assert info.is_available is True
        assert len(info.capabilities) == 2

    def test_model_catalogue_properties(self) -> None:
        cat = ModelCatalogue(
            models=[
                ModelInfo(model_id="m1", provider="p1", is_available=True),
                ModelInfo(model_id="m2", provider="p2", is_available=False),
                ModelInfo(model_id="m3", provider="p1", is_available=True),
            ]
        )
        assert len(cat.available_models) == 2
        assert cat.providers == ["p1", "p2"]

    def test_comparison_request(self) -> None:
        req = ComparisonRequest(
            models=["m1", "m2"],
            messages=[{"role": "user", "content": "hi"}],
        )
        assert len(req.models) == 2

    def test_comparison_result(self) -> None:
        res = ComparisonResult(model_id="m1", response="hello", latency_ms=50.0)
        assert res.error == ""

    def test_comparison_response(self) -> None:
        resp = ComparisonResponse(
            request_id="cmp_123",
            results=[ComparisonResult(model_id="m1")],
        )
        assert len(resp.results) == 1

    def test_playground_message(self) -> None:
        msg = PlaygroundMessage(role="user", content="test")
        assert msg.tokens == 0

    def test_playground_session_defaults(self) -> None:
        s = PlaygroundSession(session_id="s1", model_id="m1")
        assert s.status == PlaygroundStatus.ACTIVE
        assert s.total_tokens == 0

    def test_playground_request(self) -> None:
        req = PlaygroundRequest(model_id="m1", message="hello")
        assert req.session_id == ""

    def test_playground_response(self) -> None:
        resp = PlaygroundResponse(session_id="s1", response="hi", model_id="m1")
        assert resp.cost == 0.0

    def test_prompt_variable(self) -> None:
        v = PromptVariable(name="topic")
        assert v.required is True
        assert v.default_value == ""

    def test_prompt_template_defaults(self) -> None:
        t = PromptTemplate(template_id="pt1", name="test")
        assert t.version == 1
        assert t.status == PromptStatus.DRAFT

    def test_prompt_version(self) -> None:
        v = PromptVersion(template_id="pt1", version=2, content="test")
        assert v.version == 2

    def test_prompt_ab_test(self) -> None:
        t = PromptABTest(
            test_id="ab1",
            template_id="pt1",
            variant_a_version=1,
            variant_b_version=2,
        )
        assert t.traffic_split == 0.5
        assert t.total_requests == 0

    def test_prompt_analytics(self) -> None:
        a = PromptAnalytics(template_id="pt1", version=1)
        assert a.total_uses == 0
        assert a.success_rate == 0.0

    def test_hub_config_defaults(self) -> None:
        cfg = HubConfig()
        assert cfg.enabled is False
        assert cfg.playground_enabled is True
        assert cfg.prompt_management_enabled is True
        assert cfg.max_playground_sessions == 100


# ── ModelHub tests ───────────────────────────────────────────────────────


class TestModelHub:
    """Tests for the model catalogue and comparison engine."""

    @pytest.fixture()
    def hub(self) -> ModelHub:
        return ModelHub()

    @pytest.fixture()
    def sample_model(self) -> ModelInfo:
        return ModelInfo(
            model_id="test/model-1",
            provider="test",
            display_name="Test Model 1",
            capabilities=[ModelCapability.CHAT],
            pricing=ModelPricing(input_cost_per_1k=0.001, output_cost_per_1k=0.002),
            context_window=4096,
        )

    def test_register_model(self, hub: ModelHub, sample_model: ModelInfo) -> None:
        hub.register_model(sample_model)
        assert hub.get_model("test/model-1") is not None
        assert len(hub.list_models()) == 1

    def test_register_model_replaces(self, hub: ModelHub, sample_model: ModelInfo) -> None:
        hub.register_model(sample_model)
        updated = sample_model.model_copy(update={"display_name": "Updated"})
        hub.register_model(updated)
        assert len(hub.list_models()) == 1
        assert hub.get_model("test/model-1") is not None
        assert hub.get_model("test/model-1").display_name == "Updated"  # type: ignore[union-attr]

    def test_unregister_model(self, hub: ModelHub, sample_model: ModelInfo) -> None:
        hub.register_model(sample_model)
        assert hub.unregister_model("test/model-1") is True
        assert hub.get_model("test/model-1") is None

    def test_unregister_nonexistent(self, hub: ModelHub) -> None:
        assert hub.unregister_model("nope") is False

    def test_get_model_nonexistent(self, hub: ModelHub) -> None:
        assert hub.get_model("nope") is None

    def test_list_models_filter_provider(self, hub: ModelHub) -> None:
        hub.register_model(ModelInfo(model_id="a/m1", provider="a"))
        hub.register_model(ModelInfo(model_id="b/m2", provider="b"))
        result = hub.list_models(provider="a")
        assert len(result) == 1
        assert result[0].model_id == "a/m1"

    def test_list_models_filter_capability(self, hub: ModelHub) -> None:
        hub.register_model(ModelInfo(model_id="m1", capabilities=[ModelCapability.CHAT]))
        hub.register_model(ModelInfo(model_id="m2", capabilities=[ModelCapability.VISION]))
        result = hub.list_models(capability=ModelCapability.VISION)
        assert len(result) == 1
        assert result[0].model_id == "m2"

    def test_list_models_available_only(self, hub: ModelHub) -> None:
        hub.register_model(ModelInfo(model_id="m1", is_available=True))
        hub.register_model(ModelInfo(model_id="m2", is_available=False))
        assert len(hub.list_models(available_only=True)) == 1
        assert len(hub.list_models(available_only=False)) == 2

    def test_get_catalogue(self, hub: ModelHub, sample_model: ModelInfo) -> None:
        hub.register_model(sample_model)
        cat = hub.get_catalogue()
        assert len(cat.models) == 1

    def test_get_providers(self, hub: ModelHub) -> None:
        hub.register_model(ModelInfo(model_id="m1", provider="openai"))
        hub.register_model(ModelInfo(model_id="m2", provider="anthropic"))
        providers = hub.get_providers()
        assert "openai" in providers
        assert "anthropic" in providers

    def test_register_defaults(self, hub: ModelHub) -> None:
        hub.register_defaults()
        models = hub.list_models()
        assert len(models) == 4
        ids = {m.model_id for m in models}
        assert "openai/gpt-4o" in ids
        assert "anthropic/claude-sonnet-4-20250514" in ids

    async def test_compare(self, hub: ModelHub) -> None:
        hub.register_model(
            ModelInfo(
                model_id="m1",
                pricing=ModelPricing(input_cost_per_1k=0.001, output_cost_per_1k=0.002),
            )
        )
        hub.register_model(ModelInfo(model_id="m2"))

        req = ComparisonRequest(
            models=["m1", "m2"],
            messages=[{"role": "user", "content": "hello"}],
        )
        resp = await hub.compare(req)
        assert resp.request_id.startswith("cmp_")
        assert len(resp.results) == 2
        assert all(r.error == "" for r in resp.results)

    async def test_compare_with_failure(self, hub: ModelHub) -> None:
        async def failing_handler(
            model_id: str, messages: list[dict[str, Any]], params: dict[str, Any]
        ) -> tuple[str, int, int]:
            if model_id == "bad":
                raise ValueError("Model failed")
            return "ok", 10, 5

        hub_with_handler = ModelHub(handler=failing_handler)
        req = ComparisonRequest(
            models=["good", "bad"],
            messages=[{"role": "user", "content": "test"}],
        )
        resp = await hub_with_handler.compare(req)
        results = {r.model_id: r for r in resp.results}
        assert results["good"].error == ""
        assert "Model failed" in results["bad"].error

    async def test_compare_cost_calculation(self, hub: ModelHub) -> None:
        async def fixed_handler(
            model_id: str, messages: list[dict[str, Any]], params: dict[str, Any]
        ) -> tuple[str, int, int]:
            return "response", 1000, 500

        h = ModelHub(handler=fixed_handler)
        h.register_model(
            ModelInfo(
                model_id="m1",
                pricing=ModelPricing(input_cost_per_1k=0.01, output_cost_per_1k=0.03),
            )
        )
        req = ComparisonRequest(
            models=["m1", "m1"],
            messages=[{"role": "user", "content": "x"}],
        )
        resp = await h.compare(req)
        # 1000 * 0.01/1000 + 500 * 0.03/1000 = 0.01 + 0.015 = 0.025
        assert resp.results[0].cost == pytest.approx(0.025)


# ── Playground tests ─────────────────────────────────────────────────────


class TestPlayground:
    """Tests for the interactive playground."""

    @pytest.fixture()
    def pg(self) -> Playground:
        return Playground(config=HubConfig(max_playground_sessions=5))

    def test_create_session(self, pg: Playground) -> None:
        s = pg.create_session("gpt-4o")
        assert s.session_id.startswith("pg_")
        assert s.model_id == "gpt-4o"
        assert s.status == PlaygroundStatus.ACTIVE

    def test_create_session_with_params(self, pg: Playground) -> None:
        s = pg.create_session("m1", parameters={"temperature": 0.7}, metadata={"key": "val"})
        assert s.parameters == {"temperature": 0.7}
        assert s.metadata == {"key": "val"}

    def test_create_session_capacity(self, pg: Playground) -> None:
        for i in range(5):
            pg.create_session(f"m{i}")
        with pytest.raises(PlaygroundCapacityError, match="Max sessions"):
            pg.create_session("m6")

    def test_get_session(self, pg: Playground) -> None:
        s = pg.create_session("m1")
        assert pg.get_session(s.session_id) is s

    def test_get_session_nonexistent(self, pg: Playground) -> None:
        assert pg.get_session("nope") is None

    async def test_send_message(self, pg: Playground) -> None:
        s = pg.create_session("m1")
        req = PlaygroundRequest(session_id=s.session_id, message="hello")
        resp = await pg.send_message(req)
        assert resp.session_id == s.session_id
        assert resp.response != ""
        assert len(s.messages) == 2  # user + assistant

    async def test_send_message_creates_session(self, pg: Playground) -> None:
        req = PlaygroundRequest(model_id="m1", message="hi")
        resp = await pg.send_message(req)
        assert resp.session_id.startswith("pg_")
        assert pg.get_session(resp.session_id) is not None

    async def test_send_message_updates_tokens(self, pg: Playground) -> None:
        s = pg.create_session("m1")
        req = PlaygroundRequest(session_id=s.session_id, message="hello world")
        await pg.send_message(req)
        assert s.total_tokens > 0

    async def test_send_message_to_closed_session(self, pg: Playground) -> None:
        s = pg.create_session("m1")
        pg.close_session(s.session_id)
        req = PlaygroundRequest(session_id=s.session_id, message="hi")
        with pytest.raises(PlaygroundSessionError, match="completed"):
            await pg.send_message(req)

    async def test_send_message_handler_failure(self, pg: Playground) -> None:
        async def fail_handler(
            model_id: str, messages: list[dict[str, Any]], params: dict[str, Any]
        ) -> tuple[str, int, int]:
            raise RuntimeError("boom")

        failing_pg = Playground(handler=fail_handler, config=HubConfig(max_playground_sessions=5))
        s = failing_pg.create_session("m1")
        req = PlaygroundRequest(session_id=s.session_id, message="hi")
        with pytest.raises(PlaygroundSessionError, match="Inference failed"):
            await failing_pg.send_message(req)
        assert s.status == PlaygroundStatus.FAILED

    def test_list_sessions(self, pg: Playground) -> None:
        pg.create_session("m1")
        pg.create_session("m2")
        assert len(pg.list_sessions()) == 2

    def test_list_sessions_filter_status(self, pg: Playground) -> None:
        s1 = pg.create_session("m1")
        pg.create_session("m2")
        pg.close_session(s1.session_id)
        assert len(pg.list_sessions(status=PlaygroundStatus.COMPLETED)) == 1
        assert len(pg.list_sessions(status=PlaygroundStatus.ACTIVE)) == 1

    def test_close_session(self, pg: Playground) -> None:
        s = pg.create_session("m1")
        assert pg.close_session(s.session_id) is True
        assert s.status == PlaygroundStatus.COMPLETED

    def test_close_already_closed(self, pg: Playground) -> None:
        s = pg.create_session("m1")
        pg.close_session(s.session_id)
        assert pg.close_session(s.session_id) is False

    def test_close_nonexistent(self, pg: Playground) -> None:
        assert pg.close_session("nope") is False

    def test_delete_session(self, pg: Playground) -> None:
        s = pg.create_session("m1")
        assert pg.delete_session(s.session_id) is True
        assert pg.get_session(s.session_id) is None

    def test_delete_nonexistent(self, pg: Playground) -> None:
        assert pg.delete_session("nope") is False

    def test_stats(self, pg: Playground) -> None:
        pg.create_session("m1")
        s2 = pg.create_session("m2")
        pg.close_session(s2.session_id)
        s = pg.stats()
        assert s["total_sessions"] == 2
        assert s["sessions"]["active"] == 1
        assert s["sessions"]["completed"] == 1


# ── PromptManager tests ─────────────────────────────────────────────────


class TestPromptManager:
    """Tests for prompt template management."""

    @pytest.fixture()
    def pm(self) -> PromptManager:
        return PromptManager(config=HubConfig(max_prompt_templates=10))

    def test_create_template(self, pm: PromptManager) -> None:
        t = pm.create_template("greet", "Hello {{name}}, welcome to {{place}}!")
        assert t.template_id.startswith("pt_")
        assert t.name == "greet"
        assert t.version == 1
        assert t.status == PromptStatus.DRAFT
        assert len(t.variables) == 2
        var_names = {v.name for v in t.variables}
        assert "name" in var_names
        assert "place" in var_names

    def test_create_template_with_explicit_vars(self, pm: PromptManager) -> None:
        vars_ = [PromptVariable(name="x", description="The X value")]
        t = pm.create_template("test", "Value: {{x}}", variables=vars_)
        assert len(t.variables) == 1
        assert t.variables[0].description == "The X value"

    def test_create_template_capacity(self, pm: PromptManager) -> None:
        for i in range(10):
            pm.create_template(f"t{i}", f"content {i}")
        with pytest.raises(PromptCapacityError):
            pm.create_template("overflow", "too many")

    def test_get_template(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "content")
        assert pm.get_template(t.template_id) is t

    def test_get_template_nonexistent(self, pm: PromptManager) -> None:
        assert pm.get_template("nope") is None

    def test_update_template(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "v1: {{a}}")
        updated = pm.update_template(t.template_id, "v2: {{a}} {{b}}")
        assert updated is not None
        assert updated.version == 2
        assert updated.content == "v2: {{a}} {{b}}"
        assert len(updated.variables) == 2

    def test_update_nonexistent(self, pm: PromptManager) -> None:
        assert pm.update_template("nope", "content") is None

    def test_delete_template(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "content")
        assert pm.delete_template(t.template_id) is True
        assert pm.get_template(t.template_id) is None

    def test_delete_nonexistent(self, pm: PromptManager) -> None:
        assert pm.delete_template("nope") is False

    def test_list_templates(self, pm: PromptManager) -> None:
        pm.create_template("t1", "c1")
        pm.create_template("t2", "c2")
        assert len(pm.list_templates()) == 2

    def test_list_templates_filter_status(self, pm: PromptManager) -> None:
        t1 = pm.create_template("t1", "c1")
        pm.create_template("t2", "c2")
        pm.activate_template(t1.template_id)
        active = pm.list_templates(status=PromptStatus.ACTIVE)
        assert len(active) == 1

    def test_list_templates_filter_tag(self, pm: PromptManager) -> None:
        pm.create_template("t1", "c1", tags=["urgent"])
        pm.create_template("t2", "c2", tags=["normal"])
        assert len(pm.list_templates(tag="urgent")) == 1

    def test_activate_template(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "content")
        assert pm.activate_template(t.template_id) is True
        assert t.status == PromptStatus.ACTIVE

    def test_activate_nonexistent(self, pm: PromptManager) -> None:
        assert pm.activate_template("nope") is False

    def test_archive_template(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "content")
        assert pm.archive_template(t.template_id) is True
        assert t.status == PromptStatus.ARCHIVED

    def test_archive_nonexistent(self, pm: PromptManager) -> None:
        assert pm.archive_template("nope") is False

    # -- Versioning --

    def test_get_versions(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "v1")
        pm.update_template(t.template_id, "v2")
        versions = pm.get_versions(t.template_id)
        assert len(versions) == 2
        assert versions[0].version == 1
        assert versions[1].version == 2

    def test_get_version_specific(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "v1 content")
        pm.update_template(t.template_id, "v2 content")
        v1 = pm.get_version(t.template_id, 1)
        assert v1 is not None
        assert v1.content == "v1 content"

    def test_get_version_nonexistent(self, pm: PromptManager) -> None:
        assert pm.get_version("nope", 1) is None

    # -- Rendering --

    def test_render(self, pm: PromptManager) -> None:
        t = pm.create_template("greet", "Hello {{name}}, welcome to {{place}}!")
        result = pm.render(t.template_id, {"name": "Alice", "place": "Wonderland"})
        assert result == "Hello Alice, welcome to Wonderland!"

    def test_render_with_defaults(self, pm: PromptManager) -> None:
        vars_ = [
            PromptVariable(name="name", required=True),
            PromptVariable(name="lang", default_value="Python", required=False),
        ]
        t = pm.create_template("test", "{{name}} uses {{lang}}", variables=vars_)
        result = pm.render(t.template_id, {"name": "Bob"})
        assert result == "Bob uses Python"

    def test_render_specific_version(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "V1: {{x}}")
        pm.update_template(t.template_id, "V2: {{x}}")
        result = pm.render(t.template_id, {"x": "val"}, version=1)
        assert result == "V1: val"

    def test_render_missing_required(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "{{required_var}}")
        with pytest.raises(PromptRenderError, match="Missing required"):
            pm.render(t.template_id, {})

    def test_render_nonexistent_template(self, pm: PromptManager) -> None:
        with pytest.raises(PromptNotFoundError):
            pm.render("nope", {})

    def test_render_nonexistent_version(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "content")
        with pytest.raises(PromptNotFoundError, match="Version"):
            pm.render(t.template_id, {}, version=99)

    # -- A/B Testing --

    def test_create_ab_test(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "v1")
        pm.update_template(t.template_id, "v2")
        ab = pm.create_ab_test(t.template_id, 1, 2)
        assert ab.test_id.startswith("ab_")
        assert ab.variant_a_version == 1
        assert ab.variant_b_version == 2

    def test_create_ab_test_nonexistent(self, pm: PromptManager) -> None:
        with pytest.raises(PromptNotFoundError):
            pm.create_ab_test("nope", 1, 2)

    def test_pick_ab_variant(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "v1")
        pm.update_template(t.template_id, "v2")
        ab = pm.create_ab_test(t.template_id, 1, 2, traffic_split=0.5)

        random.seed(42)
        versions = [pm.pick_ab_variant(ab.test_id) for _ in range(100)]
        assert 1 in versions
        assert 2 in versions
        assert ab.total_requests == 100

    def test_pick_ab_variant_nonexistent(self, pm: PromptManager) -> None:
        with pytest.raises(PromptNotFoundError):
            pm.pick_ab_variant("nope")

    def test_get_ab_test(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "v1")
        pm.update_template(t.template_id, "v2")
        ab = pm.create_ab_test(t.template_id, 1, 2)
        assert pm.get_ab_test(ab.test_id) is ab

    def test_list_ab_tests(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "v1")
        pm.update_template(t.template_id, "v2")
        pm.create_ab_test(t.template_id, 1, 2)
        assert len(pm.list_ab_tests()) == 1
        assert len(pm.list_ab_tests(template_id=t.template_id)) == 1
        assert len(pm.list_ab_tests(template_id="other")) == 0

    # -- Analytics --

    def test_record_usage(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "content")
        pm.record_usage(t.template_id, 1, latency_ms=100.0, cost=0.01, tokens=50, success=True)
        analytics = pm.get_analytics(t.template_id, 1)
        assert len(analytics) == 1
        assert analytics[0].total_uses == 1
        assert analytics[0].average_latency_ms == 100.0
        assert analytics[0].success_rate == 1.0

    def test_record_usage_multiple(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "content")
        pm.record_usage(t.template_id, 1, latency_ms=100.0, cost=0.01, tokens=50)
        pm.record_usage(t.template_id, 1, latency_ms=200.0, cost=0.02, tokens=100)
        analytics = pm.get_analytics(t.template_id, 1)
        assert analytics[0].total_uses == 2
        assert analytics[0].average_latency_ms == pytest.approx(150.0)

    def test_record_usage_failure(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "content")
        pm.record_usage(t.template_id, 1, success=True)
        pm.record_usage(t.template_id, 1, success=False)
        analytics = pm.get_analytics(t.template_id, 1)
        assert analytics[0].success_rate == pytest.approx(0.5)

    def test_get_analytics_all_versions(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "v1")
        pm.update_template(t.template_id, "v2")
        pm.record_usage(t.template_id, 1)
        pm.record_usage(t.template_id, 2)
        analytics = pm.get_analytics(t.template_id)
        assert len(analytics) == 2

    def test_get_analytics_empty(self, pm: PromptManager) -> None:
        assert pm.get_analytics("nope") == []

    def test_delete_cleans_analytics(self, pm: PromptManager) -> None:
        t = pm.create_template("test", "content")
        pm.record_usage(t.template_id, 1)
        pm.delete_template(t.template_id)
        assert pm.get_analytics(t.template_id) == []

    # -- Stats --

    def test_stats(self, pm: PromptManager) -> None:
        t1 = pm.create_template("t1", "c1")
        pm.create_template("t2", "c2")
        pm.update_template(t1.template_id, "c1v2")
        pm.create_ab_test(t1.template_id, 1, 2)
        s = pm.stats()
        assert s["total_templates"] == 2
        assert s["total_versions"] == 3  # t1 has 2, t2 has 1
        assert s["active_ab_tests"] == 1
