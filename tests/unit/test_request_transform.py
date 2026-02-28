"""Tests for Request Transformation Pipeline (Task 8C.2).

Covers:
- TransformConfig and model validation
- PromptInjector: prepend, append, replace modes + scope filtering
- RequestEnricher: static, header, metadata sources + scope filtering
- ResponsePostProcessor: strip_thinking, regex_replace, truncate, add_metadata
- RequestTransformPipeline: hook registration, stage execution, error handling
- Integration with completions route (mocked)
"""

from __future__ import annotations

from typing import Any

import pytest

from routerbot.core.transform.enricher import RequestEnricher
from routerbot.core.transform.models import (
    EnrichmentSource,
    PostProcessingRule,
    PromptTemplate,
    TransformConfig,
    TransformContext,
    TransformResult,
    TransformStage,
)
from routerbot.core.transform.pipeline import (
    RequestTransformPipeline,
    TransformHook,
)
from routerbot.core.transform.postprocessor import ResponsePostProcessor
from routerbot.core.transform.prompt_injector import PromptInjector

# ═══════════════════════════════════════════════════════════════════════════
# Model tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTransformStage:
    def test_values(self) -> None:
        assert TransformStage.PRE_REQUEST == "pre_request"
        assert TransformStage.POST_RESPONSE == "post_response"


class TestTransformContext:
    def test_defaults(self) -> None:
        ctx = TransformContext()
        assert ctx.model == ""
        assert ctx.team_id is None
        assert ctx.key_id is None
        assert ctx.metadata == {}

    def test_full(self) -> None:
        ctx = TransformContext(
            model="gpt-4o",
            team_id="team-1",
            key_id="key-1",
            user_id="user-1",
            request_id="req-1",
            metadata={"foo": "bar"},
        )
        assert ctx.model == "gpt-4o"
        assert ctx.metadata["foo"] == "bar"


class TestTransformResult:
    def test_defaults(self) -> None:
        r = TransformResult()
        assert r.modified is False
        assert r.metadata == {}


class TestTransformConfig:
    def test_defaults(self) -> None:
        cfg = TransformConfig()
        assert cfg.enabled is False
        assert cfg.prompt_templates == []
        assert cfg.enrichment_sources == []
        assert cfg.post_processing_rules == []
        assert cfg.log_full_content is False

    def test_full_config(self) -> None:
        cfg = TransformConfig(
            enabled=True,
            prompt_templates=[
                PromptTemplate(name="t1", content="Be helpful"),
            ],
            enrichment_sources=[
                EnrichmentSource(name="s1", source_type="static", content="Context here"),
            ],
            post_processing_rules=[
                PostProcessingRule(name="r1", action="strip_thinking"),
            ],
            log_full_content=True,
        )
        assert cfg.enabled is True
        assert len(cfg.prompt_templates) == 1
        assert len(cfg.enrichment_sources) == 1
        assert len(cfg.post_processing_rules) == 1


class TestPromptTemplate:
    def test_defaults(self) -> None:
        t = PromptTemplate(name="test", content="hello")
        assert t.position == "prepend"
        assert t.enabled is True
        assert t.priority == 0
        assert t.team_ids == []
        assert t.key_ids == []
        assert t.models == []


class TestEnrichmentSource:
    def test_defaults(self) -> None:
        s = EnrichmentSource(name="test")
        assert s.source_type == "static"
        assert s.enabled is True
        assert s.position == "prepend"


class TestPostProcessingRule:
    def test_defaults(self) -> None:
        r = PostProcessingRule(name="test", action="strip_thinking")
        assert r.enabled is True
        assert r.pattern is None
        assert r.metadata_pairs == {}


# ═══════════════════════════════════════════════════════════════════════════
# PromptInjector tests
# ═══════════════════════════════════════════════════════════════════════════


def _ctx(**kw: Any) -> TransformContext:
    return TransformContext(**kw)


class TestPromptInjectorPrepend:
    @pytest.mark.asyncio
    async def test_prepend_system_message(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="safety", content="You are a safe assistant."),
            ]
        )
        data: dict[str, Any] = {
            "messages": [
                {"role": "user", "content": "Hello"},
            ],
        }
        result = await injector.apply(data, _ctx())
        assert result.modified is True
        assert data["messages"][0]["role"] == "system"
        assert data["messages"][0]["content"] == "You are a safe assistant."
        assert data["messages"][1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_prepend_before_existing_system(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="safety", content="Injected"),
            ]
        )
        data: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": "Existing"},
                {"role": "user", "content": "Hello"},
            ],
        }
        await injector.apply(data, _ctx())
        assert data["messages"][0]["content"] == "Injected"
        assert data["messages"][1]["content"] == "Existing"


class TestPromptInjectorAppend:
    @pytest.mark.asyncio
    async def test_append_after_system_message(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="context", content="Extra context", position="append"),
            ]
        )
        data: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": "Main system prompt"},
                {"role": "user", "content": "Hello"},
            ],
        }
        await injector.apply(data, _ctx())
        assert data["messages"][0]["content"] == "Main system prompt"
        assert data["messages"][1]["content"] == "Extra context"
        assert data["messages"][2]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_append_with_no_system_inserts_at_start(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="ctx", content="Context", position="append"),
            ]
        )
        data: dict[str, Any] = {
            "messages": [{"role": "user", "content": "Hello"}],
        }
        await injector.apply(data, _ctx())
        assert data["messages"][0]["content"] == "Context"


class TestPromptInjectorReplace:
    @pytest.mark.asyncio
    async def test_replace_existing_system_messages(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="override", content="New system prompt", position="replace"),
            ]
        )
        data: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": "Old prompt 1"},
                {"role": "system", "content": "Old prompt 2"},
                {"role": "user", "content": "Hello"},
            ],
        }
        await injector.apply(data, _ctx())
        system_msgs = [m for m in data["messages"] if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "New system prompt"


class TestPromptInjectorScoping:
    @pytest.mark.asyncio
    async def test_team_scope_match(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="team", content="Team prompt", team_ids=["team-a"]),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hi"}]}
        result = await injector.apply(data, _ctx(team_id="team-a"))
        assert result.modified is True

    @pytest.mark.asyncio
    async def test_team_scope_no_match(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="team", content="Team prompt", team_ids=["team-a"]),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hi"}]}
        result = await injector.apply(data, _ctx(team_id="team-b"))
        assert result.modified is False

    @pytest.mark.asyncio
    async def test_key_scope_match(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="key", content="Key prompt", key_ids=["key-1"]),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hi"}]}
        result = await injector.apply(data, _ctx(key_id="key-1"))
        assert result.modified is True

    @pytest.mark.asyncio
    async def test_model_scope_match(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="model", content="Model prompt", models=["gpt-4o"]),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hi"}]}
        result = await injector.apply(data, _ctx(model="gpt-4o"))
        assert result.modified is True

    @pytest.mark.asyncio
    async def test_model_scope_no_match(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="model", content="Model prompt", models=["gpt-4o"]),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hi"}]}
        result = await injector.apply(data, _ctx(model="claude-3"))
        assert result.modified is False

    @pytest.mark.asyncio
    async def test_disabled_template(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="off", content="Disabled", enabled=False),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hi"}]}
        result = await injector.apply(data, _ctx())
        assert result.modified is False

    @pytest.mark.asyncio
    async def test_global_scope(self) -> None:
        """Templates with no scope filters apply to everything."""
        injector = PromptInjector(
            [
                PromptTemplate(name="global", content="Global prompt"),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hi"}]}
        result = await injector.apply(data, _ctx(team_id="any", model="any"))
        assert result.modified is True


class TestPromptInjectorPriority:
    @pytest.mark.asyncio
    async def test_higher_priority_first(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="low", content="Low", priority=10),
                PromptTemplate(name="high", content="High", priority=100),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hi"}]}
        await injector.apply(data, _ctx())
        # High priority prepends first (index 0), then low prepends before it
        assert data["messages"][0]["content"] == "Low"
        assert data["messages"][1]["content"] == "High"


class TestPromptInjectorEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_messages(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="t", content="test"),
            ]
        )
        data: dict[str, Any] = {"messages": []}
        result = await injector.apply(data, _ctx())
        assert result.modified is False

    @pytest.mark.asyncio
    async def test_no_messages_key(self) -> None:
        injector = PromptInjector(
            [
                PromptTemplate(name="t", content="test"),
            ]
        )
        data: dict[str, Any] = {}
        result = await injector.apply(data, _ctx())
        assert result.modified is False

    def test_templates_property(self) -> None:
        templates = [PromptTemplate(name="a", content="x")]
        injector = PromptInjector(templates)
        assert len(injector.templates) == 1


# ═══════════════════════════════════════════════════════════════════════════
# RequestEnricher tests
# ═══════════════════════════════════════════════════════════════════════════


class TestRequestEnricherStatic:
    @pytest.mark.asyncio
    async def test_static_prepend(self) -> None:
        enricher = RequestEnricher(
            [
                EnrichmentSource(name="ctx", source_type="static", content="Extra context"),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hello"}]}
        result = await enricher.apply(data, _ctx())
        assert result.modified is True
        assert data["messages"][0]["role"] == "system"
        assert data["messages"][0]["content"] == "Extra context"

    @pytest.mark.asyncio
    async def test_static_append(self) -> None:
        enricher = RequestEnricher(
            [
                EnrichmentSource(
                    name="ctx",
                    source_type="static",
                    content="Extra",
                    position="append",
                ),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hello"}]}
        result = await enricher.apply(data, _ctx())
        assert result.modified is True
        assert data["messages"][-1]["content"] == "Extra"

    @pytest.mark.asyncio
    async def test_static_none_content_skipped(self) -> None:
        enricher = RequestEnricher(
            [
                EnrichmentSource(name="empty", source_type="static", content=None),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hello"}]}
        result = await enricher.apply(data, _ctx())
        assert result.modified is False


class TestRequestEnricherHeader:
    @pytest.mark.asyncio
    async def test_header_source(self) -> None:
        enricher = RequestEnricher(
            [
                EnrichmentSource(
                    name="hdr",
                    source_type="header",
                    header_name="X-Custom-Context",
                ),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hello"}]}
        ctx = _ctx(metadata={"headers": {"X-Custom-Context": "Custom context value"}})
        result = await enricher.apply(data, ctx)
        assert result.modified is True
        assert data["messages"][0]["content"] == "Custom context value"

    @pytest.mark.asyncio
    async def test_header_missing(self) -> None:
        enricher = RequestEnricher(
            [
                EnrichmentSource(name="hdr", source_type="header", header_name="X-Missing"),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hello"}]}
        result = await enricher.apply(data, _ctx(metadata={"headers": {}}))
        assert result.modified is False


class TestRequestEnricherMetadata:
    @pytest.mark.asyncio
    async def test_metadata_source(self) -> None:
        enricher = RequestEnricher(
            [
                EnrichmentSource(name="meta", source_type="metadata", metadata_key="org_context"),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hello"}]}
        ctx = _ctx(metadata={"org_context": "We are an e-commerce company."})
        result = await enricher.apply(data, ctx)
        assert result.modified is True
        assert data["messages"][0]["content"] == "We are an e-commerce company."


class TestRequestEnricherScoping:
    @pytest.mark.asyncio
    async def test_team_scope_match(self) -> None:
        enricher = RequestEnricher(
            [
                EnrichmentSource(
                    name="team-ctx",
                    source_type="static",
                    content="Team info",
                    team_ids=["team-a"],
                ),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hi"}]}
        result = await enricher.apply(data, _ctx(team_id="team-a"))
        assert result.modified is True

    @pytest.mark.asyncio
    async def test_team_scope_no_match(self) -> None:
        enricher = RequestEnricher(
            [
                EnrichmentSource(
                    name="team-ctx",
                    source_type="static",
                    content="Team info",
                    team_ids=["team-a"],
                ),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hi"}]}
        result = await enricher.apply(data, _ctx(team_id="team-b"))
        assert result.modified is False

    @pytest.mark.asyncio
    async def test_disabled_source_filtered(self) -> None:
        enricher = RequestEnricher(
            [
                EnrichmentSource(name="off", source_type="static", content="x", enabled=False),
            ]
        )
        data: dict[str, Any] = {"messages": [{"role": "user", "content": "Hi"}]}
        result = await enricher.apply(data, _ctx())
        assert result.modified is False

    def test_sources_property(self) -> None:
        enricher = RequestEnricher(
            [
                EnrichmentSource(name="a", source_type="static", content="x"),
                EnrichmentSource(name="b", source_type="static", content="y", enabled=False),
            ]
        )
        assert len(enricher.sources) == 1  # disabled one filtered out


# ═══════════════════════════════════════════════════════════════════════════
# ResponsePostProcessor tests
# ═══════════════════════════════════════════════════════════════════════════


class TestPostProcessorStripThinking:
    @pytest.mark.asyncio
    async def test_strip_thinking_blocks(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(name="strip", action="strip_thinking"),
            ]
        )
        data: dict[str, Any] = {
            "choices": [
                {
                    "message": {
                        "content": "<thinking>Internal reasoning here</thinking>The answer is 42.",
                    },
                }
            ],
        }
        result = await pp.apply(data, _ctx())
        assert result.modified is True
        assert data["choices"][0]["message"]["content"] == "The answer is 42."

    @pytest.mark.asyncio
    async def test_strip_thinking_multiline(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(name="strip", action="strip_thinking"),
            ]
        )
        data: dict[str, Any] = {
            "choices": [
                {
                    "message": {
                        "content": "<thinking>\nLine 1\nLine 2\n</thinking>\nResult here.",
                    },
                }
            ],
        }
        await pp.apply(data, _ctx())
        assert data["choices"][0]["message"]["content"] == "Result here."

    @pytest.mark.asyncio
    async def test_strip_thinking_no_blocks(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(name="strip", action="strip_thinking"),
            ]
        )
        data: dict[str, Any] = {
            "choices": [{"message": {"content": "No thinking blocks"}}],
        }
        result = await pp.apply(data, _ctx())
        assert result.modified is False


class TestPostProcessorRegexReplace:
    @pytest.mark.asyncio
    async def test_regex_replace(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(
                    name="redact",
                    action="regex_replace",
                    pattern=r"\b\d{3}-\d{2}-\d{4}\b",
                    replacement="[REDACTED]",
                ),
            ]
        )
        data: dict[str, Any] = {
            "choices": [{"message": {"content": "SSN: 123-45-6789"}}],
        }
        result = await pp.apply(data, _ctx())
        assert result.modified is True
        assert data["choices"][0]["message"]["content"] == "SSN: [REDACTED]"

    @pytest.mark.asyncio
    async def test_regex_replace_no_match(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(
                    name="redact",
                    action="regex_replace",
                    pattern=r"ZZZZZ",
                    replacement="X",
                ),
            ]
        )
        data: dict[str, Any] = {
            "choices": [{"message": {"content": "Nothing to replace"}}],
        }
        result = await pp.apply(data, _ctx())
        assert result.modified is False

    @pytest.mark.asyncio
    async def test_regex_replace_no_pattern(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(name="bad", action="regex_replace"),
            ]
        )
        data: dict[str, Any] = {
            "choices": [{"message": {"content": "Hello"}}],
        }
        result = await pp.apply(data, _ctx())
        assert result.modified is False


class TestPostProcessorTruncate:
    @pytest.mark.asyncio
    async def test_truncate(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(name="trunc", action="truncate", max_chars=10),
            ]
        )
        data: dict[str, Any] = {
            "choices": [{"message": {"content": "A" * 100}}],
        }
        result = await pp.apply(data, _ctx())
        assert result.modified is True
        assert len(data["choices"][0]["message"]["content"]) == 10

    @pytest.mark.asyncio
    async def test_truncate_short_content(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(name="trunc", action="truncate", max_chars=100),
            ]
        )
        data: dict[str, Any] = {
            "choices": [{"message": {"content": "Short"}}],
        }
        result = await pp.apply(data, _ctx())
        assert result.modified is False

    @pytest.mark.asyncio
    async def test_truncate_no_max_chars(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(name="trunc", action="truncate"),
            ]
        )
        data: dict[str, Any] = {
            "choices": [{"message": {"content": "A" * 1000}}],
        }
        result = await pp.apply(data, _ctx())
        assert result.modified is False


class TestPostProcessorAddMetadata:
    @pytest.mark.asyncio
    async def test_add_metadata(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(
                    name="meta",
                    action="add_metadata",
                    metadata_pairs={"version": "1.0", "processed": "true"},
                ),
            ]
        )
        data: dict[str, Any] = {"choices": []}
        result = await pp.apply(data, _ctx())
        assert result.modified is True
        assert data["metadata"]["version"] == "1.0"
        assert data["metadata"]["processed"] == "true"

    @pytest.mark.asyncio
    async def test_add_metadata_empty_pairs(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(name="meta", action="add_metadata"),
            ]
        )
        data: dict[str, Any] = {"choices": []}
        result = await pp.apply(data, _ctx())
        assert result.modified is False


class TestPostProcessorScoping:
    @pytest.mark.asyncio
    async def test_team_scope_match(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(
                    name="team-strip",
                    action="strip_thinking",
                    team_ids=["team-a"],
                ),
            ]
        )
        data: dict[str, Any] = {
            "choices": [{"message": {"content": "<thinking>x</thinking>y"}}],
        }
        result = await pp.apply(data, _ctx(team_id="team-a"))
        assert result.modified is True

    @pytest.mark.asyncio
    async def test_team_scope_no_match(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(
                    name="team-strip",
                    action="strip_thinking",
                    team_ids=["team-a"],
                ),
            ]
        )
        data: dict[str, Any] = {
            "choices": [{"message": {"content": "<thinking>x</thinking>y"}}],
        }
        result = await pp.apply(data, _ctx(team_id="team-b"))
        assert result.modified is False

    def test_rules_property(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(name="a", action="strip_thinking"),
                PostProcessingRule(name="b", action="truncate", enabled=False),
            ]
        )
        assert len(pp.rules) == 1  # disabled one filtered


class TestPostProcessorUnknownAction:
    @pytest.mark.asyncio
    async def test_unknown_action(self) -> None:
        pp = ResponsePostProcessor(
            [
                PostProcessingRule(name="x", action="unknown_action"),
            ]
        )
        data: dict[str, Any] = {"choices": []}
        result = await pp.apply(data, _ctx())
        assert result.modified is False


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline tests
# ═══════════════════════════════════════════════════════════════════════════


class _DummyPreHook(TransformHook):
    def __init__(self, hook_name: str = "dummy_pre") -> None:
        self._name = hook_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def stage(self) -> TransformStage:
        return TransformStage.PRE_REQUEST

    async def apply(
        self,
        data: dict[str, Any],
        context: TransformContext,
    ) -> TransformResult:
        data["modified_by_pre"] = True
        return TransformResult(modified=True, metadata={"hook": self._name})


class _DummyPostHook(TransformHook):
    @property
    def name(self) -> str:
        return "dummy_post"

    @property
    def stage(self) -> TransformStage:
        return TransformStage.POST_RESPONSE

    async def apply(
        self,
        data: dict[str, Any],
        context: TransformContext,
    ) -> TransformResult:
        data["modified_by_post"] = True
        return TransformResult(modified=True)


class _FailingHook(TransformHook):
    @property
    def name(self) -> str:
        return "failing_hook"

    @property
    def stage(self) -> TransformStage:
        return TransformStage.PRE_REQUEST

    async def apply(
        self,
        data: dict[str, Any],
        context: TransformContext,
    ) -> TransformResult:
        msg = "Hook exploded"
        raise RuntimeError(msg)


class TestPipelineRegistration:
    def test_register_hook(self) -> None:
        cfg = TransformConfig(enabled=True)
        pipeline = RequestTransformPipeline(cfg)
        hook = _DummyPreHook()
        pipeline.register(hook)
        assert len(pipeline.hooks) == 1
        assert pipeline.hooks[0].name == "dummy_pre"

    def test_unregister_hook(self) -> None:
        cfg = TransformConfig(enabled=True)
        pipeline = RequestTransformPipeline(cfg)
        pipeline.register(_DummyPreHook())
        removed = pipeline.unregister("dummy_pre")
        assert removed is True
        assert len(pipeline.hooks) == 0

    def test_unregister_nonexistent(self) -> None:
        cfg = TransformConfig(enabled=True)
        pipeline = RequestTransformPipeline(cfg)
        removed = pipeline.unregister("nonexistent")
        assert removed is False

    def test_config_property(self) -> None:
        cfg = TransformConfig(enabled=True)
        pipeline = RequestTransformPipeline(cfg)
        assert pipeline.config is cfg

    def test_enabled_property(self) -> None:
        assert RequestTransformPipeline(TransformConfig(enabled=True)).enabled is True
        assert RequestTransformPipeline(TransformConfig(enabled=False)).enabled is False


class TestPipelineExecution:
    @pytest.mark.asyncio
    async def test_run_pre_request(self) -> None:
        cfg = TransformConfig(enabled=True)
        pipeline = RequestTransformPipeline(cfg)
        pipeline.register(_DummyPreHook())
        pipeline.register(_DummyPostHook())

        data: dict[str, Any] = {}
        results = await pipeline.run_pre_request(data, _ctx())
        assert len(results) == 1
        assert results[0].modified is True
        assert data.get("modified_by_pre") is True
        assert data.get("modified_by_post") is None  # Post hook not run

    @pytest.mark.asyncio
    async def test_run_post_response(self) -> None:
        cfg = TransformConfig(enabled=True)
        pipeline = RequestTransformPipeline(cfg)
        pipeline.register(_DummyPreHook())
        pipeline.register(_DummyPostHook())

        data: dict[str, Any] = {}
        results = await pipeline.run_post_response(data, _ctx())
        assert len(results) == 1
        assert data.get("modified_by_post") is True
        assert data.get("modified_by_pre") is None  # Pre hook not run

    @pytest.mark.asyncio
    async def test_failing_hook_skipped(self) -> None:
        cfg = TransformConfig(enabled=True)
        pipeline = RequestTransformPipeline(cfg)
        pipeline.register(_FailingHook())
        pipeline.register(_DummyPreHook())

        data: dict[str, Any] = {}
        results = await pipeline.run_pre_request(data, _ctx())
        assert len(results) == 2
        # First hook failed
        assert results[0].modified is False
        assert "error" in results[0].metadata
        # Second hook still ran
        assert results[1].modified is True
        assert data.get("modified_by_pre") is True

    @pytest.mark.asyncio
    async def test_no_hooks_empty_results(self) -> None:
        cfg = TransformConfig(enabled=True)
        pipeline = RequestTransformPipeline(cfg)
        results = await pipeline.run_pre_request({}, _ctx())
        assert results == []

    @pytest.mark.asyncio
    async def test_multiple_hooks_ordered(self) -> None:
        cfg = TransformConfig(enabled=True)
        pipeline = RequestTransformPipeline(cfg)
        pipeline.register(_DummyPreHook("first"))
        pipeline.register(_DummyPreHook("second"))

        data: dict[str, Any] = {}
        results = await pipeline.run_pre_request(data, _ctx())
        assert len(results) == 2
        assert results[0].metadata["hook"] == "first"
        assert results[1].metadata["hook"] == "second"


# ═══════════════════════════════════════════════════════════════════════════
# Full pipeline integration tests
# ═══════════════════════════════════════════════════════════════════════════


class TestFullPipelineIntegration:
    @pytest.mark.asyncio
    async def test_prompt_injection_and_enrichment(self) -> None:
        """Test that prompt injection and enrichment work together."""
        cfg = TransformConfig(
            enabled=True,
            prompt_templates=[
                PromptTemplate(name="safety", content="Be careful with PII."),
            ],
            enrichment_sources=[
                EnrichmentSource(
                    name="org",
                    source_type="static",
                    content="Company: Acme Corp",
                    position="append",
                ),
            ],
        )
        pipeline = RequestTransformPipeline(cfg)
        pipeline.register(PromptInjector(cfg.prompt_templates))
        pipeline.register(RequestEnricher(cfg.enrichment_sources))

        data: dict[str, Any] = {
            "messages": [{"role": "user", "content": "Hello"}],
        }
        await pipeline.run_pre_request(data, _ctx())
        # Safety prompt prepended, then enrichment appended
        assert data["messages"][0]["content"] == "Be careful with PII."
        assert data["messages"][-1]["content"] == "Company: Acme Corp"
        assert any(m["content"] == "Hello" for m in data["messages"])

    @pytest.mark.asyncio
    async def test_post_processing_pipeline(self) -> None:
        """Test multiple post-processing rules in sequence."""
        cfg = TransformConfig(
            enabled=True,
            post_processing_rules=[
                PostProcessingRule(name="strip", action="strip_thinking"),
                PostProcessingRule(
                    name="meta",
                    action="add_metadata",
                    metadata_pairs={"processed": "true"},
                ),
            ],
        )
        pipeline = RequestTransformPipeline(cfg)
        pipeline.register(ResponsePostProcessor(cfg.post_processing_rules))

        data: dict[str, Any] = {
            "choices": [
                {
                    "message": {"content": "<thinking>Hmm</thinking>Answer"},
                }
            ],
        }
        await pipeline.run_post_response(data, _ctx())
        assert data["choices"][0]["message"]["content"] == "Answer"
        assert data["metadata"]["processed"] == "true"

    def test_config_from_dict(self) -> None:
        """Verify TransformConfig can be constructed from dict (as in app.py)."""
        config_dict = {
            "enabled": True,
            "prompt_templates": [
                {"name": "safety", "content": "Be safe", "position": "prepend"},
            ],
            "enrichment_sources": [
                {"name": "ctx", "source_type": "static", "content": "Context"},
            ],
            "post_processing_rules": [
                {"name": "strip", "action": "strip_thinking"},
            ],
            "log_full_content": True,
        }
        cfg = TransformConfig(**config_dict)
        assert cfg.enabled is True
        assert len(cfg.prompt_templates) == 1
        assert len(cfg.enrichment_sources) == 1
        assert len(cfg.post_processing_rules) == 1
        assert cfg.log_full_content is True

    def test_empty_config_dict(self) -> None:
        cfg = TransformConfig(**{})
        assert cfg.enabled is False
        pipeline = RequestTransformPipeline(cfg)
        assert pipeline.enabled is False
