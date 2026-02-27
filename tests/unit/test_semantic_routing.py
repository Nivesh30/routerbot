"""Tests for Semantic Routing (Task 8C.1).

Covers:
- SemanticRoutingConfig and model validation
- IntentCategory enum
- PatternRule / IntentRule / ABTestConfig models
- IntentClassifier: local classification, caching, LLM fallback
- SemanticRouter: pattern rules, A/B tests, intent routing, defaults
- Text extraction from messages and multimodal content
- A/B test stats reporting
- Completions route integration (mocked)
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from routerbot.core.semantic.classifier import IntentClassifier, SemanticRouter
from routerbot.core.semantic.models import (
    ABTestConfig,
    IntentCategory,
    IntentRule,
    PatternRule,
    SemanticRoutingConfig,
)

# ═══════════════════════════════════════════════════════════════════════════
# Model tests
# ═══════════════════════════════════════════════════════════════════════════


class TestIntentCategory:
    def test_all_categories_exist(self) -> None:
        expected = {
            "simple_qa",
            "complex_reasoning",
            "code_generation",
            "code_review",
            "creative_writing",
            "translation",
            "summarisation",
            "math",
            "vision",
            "general",
        }
        assert {c.value for c in IntentCategory} == expected

    def test_string_values(self) -> None:
        assert IntentCategory.CODE_GENERATION == "code_generation"
        assert IntentCategory.SIMPLE_QA == "simple_qa"
        assert IntentCategory.GENERAL == "general"


class TestPatternRule:
    def test_basic_pattern(self) -> None:
        rule = PatternRule(pattern=r"\bSQL\b", route_to="gpt-4o")
        assert rule.priority == 0
        # Verify the pattern compiles
        assert re.search(rule.pattern, "Write SQL query", re.IGNORECASE)

    def test_priority(self) -> None:
        rule = PatternRule(pattern="test", route_to="m1", priority=999)
        assert rule.priority == 999


class TestIntentRule:
    def test_basic_rule(self) -> None:
        rule = IntentRule(intent="code_generation", route_to="gpt-4o")
        assert rule.priority == 0

    def test_custom_priority(self) -> None:
        rule = IntentRule(intent="math", route_to="claude-3-opus", priority=200)
        assert rule.priority == 200


class TestABTestConfig:
    def test_defaults(self) -> None:
        ab = ABTestConfig(name="t1", model_a="gpt-4o", model_b="claude-3-opus")
        assert ab.traffic_split == 0.5
        assert ab.enabled is True
        assert ab.metadata == {}

    def test_custom_split(self) -> None:
        ab = ABTestConfig(
            name="cost-test",
            model_a="gpt-4o",
            model_b="gpt-4o-mini",
            traffic_split=0.8,
            enabled=False,
            metadata={"owner": "platform"},
        )
        assert ab.traffic_split == 0.8
        assert ab.enabled is False
        assert ab.metadata["owner"] == "platform"

    def test_traffic_split_bounds(self) -> None:
        # Valid boundary values
        ab_low = ABTestConfig(name="t", model_a="a", model_b="b", traffic_split=0.0)
        assert ab_low.traffic_split == 0.0
        ab_high = ABTestConfig(name="t", model_a="a", model_b="b", traffic_split=1.0)
        assert ab_high.traffic_split == 1.0


class TestSemanticRoutingConfig:
    def test_defaults(self) -> None:
        cfg = SemanticRoutingConfig()
        assert cfg.enabled is False
        assert cfg.rules == []
        assert cfg.pattern_rules == []
        assert cfg.ab_tests == []
        assert cfg.default_model is None
        assert cfg.cache_classifications is True
        assert cfg.classification_timeout == 5.0

    def test_full_config(self) -> None:
        cfg = SemanticRoutingConfig(
            enabled=True,
            classifier_model="gpt-4o-mini",
            rules=[IntentRule(intent="code_generation", route_to="gpt-4o")],
            pattern_rules=[PatternRule(pattern=r"\bSQL\b", route_to="gpt-4o")],
            ab_tests=[ABTestConfig(name="t1", model_a="a", model_b="b")],
            default_model="gpt-3.5-turbo",
            cache_classifications=False,
            classification_timeout=10.0,
        )
        assert cfg.enabled is True
        assert len(cfg.rules) == 1
        assert len(cfg.pattern_rules) == 1
        assert len(cfg.ab_tests) == 1
        assert cfg.classifier_model == "gpt-4o-mini"


# ═══════════════════════════════════════════════════════════════════════════
# IntentClassifier tests
# ═══════════════════════════════════════════════════════════════════════════


def _make_config(**overrides: Any) -> SemanticRoutingConfig:
    """Helper to create a config with sensible defaults."""
    defaults: dict[str, Any] = {
        "enabled": True,
        "cache_classifications": True,
    }
    defaults.update(overrides)
    return SemanticRoutingConfig(**defaults)


class TestIntentClassifierLocal:
    """Tests for local keyword-based classification."""

    def test_code_generation(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("Write a Python function for sorting") == "code_generation"

    def test_code_review(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("Review this code for bugs") == "code_review"

    def test_complex_reasoning(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("Explain why this approach doesn't work") == "complex_reasoning"

    def test_creative_writing(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("Write a short story about space") == "creative_writing"

    def test_translation(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("Translate this to French") == "translation"

    def test_summarisation(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("Summarise this article for me") == "summarisation"

    def test_math(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("Calculate the derivative of x^2") == "math"

    def test_math_expression(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("What is 42 + 58?") == "math"

    def test_vision(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("Describe what's in this image") == "vision"

    def test_simple_qa(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("What is the capital of France?") == "simple_qa"

    def test_no_match_returns_none(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("asdfghjkl random gibberish") is None

    def test_empty_text_returns_none(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("") is None

    def test_code_block_detection(self) -> None:
        clf = IntentClassifier(_make_config())
        assert clf.classify_local("```python\ndef foo():\n  pass\n```") == "code_generation"


class TestIntentClassifierCache:
    """Tests for classification caching."""

    def test_cache_stores_result(self) -> None:
        clf = IntentClassifier(_make_config(cache_classifications=True))
        result = clf.classify_local("Translate this to French")
        assert result == "translation"
        assert len(clf._cache) == 1

    def test_cache_disabled(self) -> None:
        clf = IntentClassifier(_make_config(cache_classifications=False))
        clf.classify_local("Translate this to French")
        assert len(clf._cache) == 0

    def test_cache_hit(self) -> None:
        clf = IntentClassifier(_make_config(cache_classifications=True))
        # First call populates cache
        clf.classify_local("Translate this to French")
        # Second call should hit cache (verify by checking it still works)
        result = clf.classify_local("Translate this to French")
        assert result == "translation"

    def test_clear_cache(self) -> None:
        clf = IntentClassifier(_make_config(cache_classifications=True))
        clf.classify_local("Translate this to French")
        assert len(clf._cache) == 1
        clf.clear_cache()
        assert len(clf._cache) == 0

    def test_cache_key_deterministic(self) -> None:
        key1 = IntentClassifier._make_cache_key("hello world")
        key2 = IntentClassifier._make_cache_key("hello world")
        assert key1 == key2

    def test_cache_key_different_for_different_text(self) -> None:
        key1 = IntentClassifier._make_cache_key("hello")
        key2 = IntentClassifier._make_cache_key("world")
        assert key1 != key2


class TestIntentClassifierAsync:
    """Tests for async classify method."""

    @pytest.mark.asyncio
    async def test_local_match_skips_llm(self) -> None:
        clf = IntentClassifier(_make_config())
        result = await clf.classify("Translate this to French")
        assert result == "translation"

    @pytest.mark.asyncio
    async def test_no_local_match_no_classifier_model_returns_general(self) -> None:
        clf = IntentClassifier(_make_config(classifier_model=None))
        result = await clf.classify("foobar baz quux nope")
        assert result == "general"

    @pytest.mark.asyncio
    async def test_llm_classification_success(self) -> None:
        cfg = _make_config(
            classifier_model="gpt-4o-mini",
            rules=[IntentRule(intent="code_generation", route_to="gpt-4o")],
        )
        clf = IntentClassifier(cfg)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "code_generation"}}],
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await clf.classify("foobar baz quux nope")
            assert result == "code_generation"

    @pytest.mark.asyncio
    async def test_llm_classification_failure_returns_general(self) -> None:
        cfg = _make_config(classifier_model="gpt-4o-mini")
        clf = IntentClassifier(cfg)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await clf.classify("foobar baz quux nope")
            assert result == "general"

    @pytest.mark.asyncio
    async def test_llm_returns_unknown_intent_falls_to_general(self) -> None:
        cfg = _make_config(
            classifier_model="gpt-4o-mini",
            rules=[IntentRule(intent="code_generation", route_to="gpt-4o")],
        )
        clf = IntentClassifier(cfg)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "unknown_category"}}],
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await clf.classify("foobar baz quux nope")
            assert result == "general"


# ═══════════════════════════════════════════════════════════════════════════
# SemanticRouter tests
# ═══════════════════════════════════════════════════════════════════════════


def _make_router(**overrides: Any) -> SemanticRouter:
    """Helper to create a SemanticRouter with defaults."""
    cfg = _make_config(**overrides)
    return SemanticRouter(cfg)


class TestSemanticRouterEnabled:
    def test_disabled_returns_original_model(self) -> None:
        router = _make_router(enabled=False)
        assert router.enabled is False

    @pytest.mark.asyncio
    async def test_disabled_passthrough(self) -> None:
        router = _make_router(enabled=False)
        result = await router.route("gpt-4o", messages=[{"role": "user", "content": "hello"}])
        assert result == "gpt-4o"


class TestSemanticRouterPatternRules:
    @pytest.mark.asyncio
    async def test_pattern_match(self) -> None:
        router = _make_router(
            pattern_rules=[PatternRule(pattern=r"\bSQL\b", route_to="gpt-4o")],
        )
        result = await router.route(
            "gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Write a SQL query"}],
        )
        assert result == "gpt-4o"

    @pytest.mark.asyncio
    async def test_pattern_no_match(self) -> None:
        router = _make_router(
            pattern_rules=[PatternRule(pattern=r"\bSQL\b", route_to="gpt-4o")],
            default_model="default-model",
        )
        result = await router.route(
            "gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Tell me a joke"}],
        )
        # Should fall through to default
        assert result == "default-model"

    @pytest.mark.asyncio
    async def test_pattern_priority_order(self) -> None:
        router = _make_router(
            pattern_rules=[
                PatternRule(pattern=r"\bcode\b", route_to="low-priority", priority=10),
                PatternRule(pattern=r"\bcode\b", route_to="high-priority", priority=200),
            ],
        )
        result = await router.route(
            "base",
            messages=[{"role": "user", "content": "Write some code"}],
        )
        assert result == "high-priority"


class TestSemanticRouterABTests:
    @pytest.mark.asyncio
    async def test_ab_test_routes_to_one_of_two_models(self) -> None:
        router = _make_router(
            ab_tests=[
                ABTestConfig(name="t1", model_a="gpt-4o", model_b="claude-3-opus"),
            ],
        )
        results = set()
        for _ in range(100):
            result = await router.route(
                "gpt-4o",
                messages=[{"role": "user", "content": "hello world test abc"}],
            )
            results.add(result)
        # With 50/50 split and 100 trials, should see both
        assert results == {"gpt-4o", "claude-3-opus"}

    @pytest.mark.asyncio
    async def test_ab_test_traffic_split_100_percent(self) -> None:
        router = _make_router(
            ab_tests=[
                ABTestConfig(name="all-a", model_a="model-a", model_b="model-b", traffic_split=1.0),
            ],
        )
        results = set()
        for _ in range(20):
            result = await router.route(
                "model-a",
                messages=[{"role": "user", "content": "test request"}],
            )
            results.add(result)
        assert results == {"model-a"}

    @pytest.mark.asyncio
    async def test_ab_test_disabled(self) -> None:
        router = _make_router(
            ab_tests=[
                ABTestConfig(
                    name="disabled", model_a="gpt-4o", model_b="claude-3-opus", enabled=False,
                ),
            ],
            default_model="fallback",
        )
        result = await router.route(
            "gpt-4o",
            messages=[{"role": "user", "content": "test something with no keywords matching"}],
        )
        # Disabled A/B test should not trigger, falls to default
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_ab_test_unrelated_model_ignored(self) -> None:
        router = _make_router(
            ab_tests=[
                ABTestConfig(name="t1", model_a="gpt-4o", model_b="claude-3"),
            ],
            default_model="fallback",
        )
        result = await router.route(
            "totally-different-model",
            messages=[{"role": "user", "content": "random unmatched text input"}],
        )
        # A/B test is for gpt-4o/claude-3, not for totally-different-model
        assert result == "fallback"


class TestSemanticRouterIntentRouting:
    @pytest.mark.asyncio
    async def test_intent_routes_to_model(self) -> None:
        router = _make_router(
            rules=[IntentRule(intent="code_generation", route_to="gpt-4o")],
        )
        result = await router.route(
            "base-model",
            messages=[{"role": "user", "content": "Write a Python function that sorts a list"}],
        )
        assert result == "gpt-4o"

    @pytest.mark.asyncio
    async def test_intent_priority(self) -> None:
        router = _make_router(
            rules=[
                IntentRule(intent="translation", route_to="low-pri", priority=10),
                IntentRule(intent="translation", route_to="high-pri", priority=200),
            ],
        )
        result = await router.route(
            "base",
            messages=[{"role": "user", "content": "Translate this to French"}],
        )
        assert result == "high-pri"

    @pytest.mark.asyncio
    async def test_no_matching_rule_uses_default(self) -> None:
        router = _make_router(
            rules=[IntentRule(intent="code_generation", route_to="gpt-4o")],
            default_model="fallback",
        )
        result = await router.route(
            "base",
            messages=[{"role": "user", "content": "Translate this to French"}],
        )
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_no_matching_rule_no_default_returns_original(self) -> None:
        router = _make_router(
            rules=[IntentRule(intent="code_generation", route_to="gpt-4o")],
        )
        result = await router.route(
            "original-model",
            messages=[{"role": "user", "content": "Translate this to French"}],
        )
        # No intent rule for translation, no default → returns original
        assert result == "original-model"


class TestSemanticRouterTextExtraction:
    def test_extract_from_prompt(self) -> None:
        result = SemanticRouter._extract_text(None, "hello world")
        assert result == "hello world"

    def test_extract_from_messages(self) -> None:
        messages = [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "What is 2+2?"},
        ]
        result = SemanticRouter._extract_text(messages, None)
        assert result == "What is 2+2?"

    def test_extract_last_user_message(self) -> None:
        messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "Answer"},
            {"role": "user", "content": "Follow-up question"},
        ]
        result = SemanticRouter._extract_text(messages, None)
        assert result == "Follow-up question"

    def test_extract_multimodal_content(self) -> None:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
                ],
            },
        ]
        result = SemanticRouter._extract_text(messages, None)
        assert result == "Describe this"

    def test_extract_empty_messages(self) -> None:
        result = SemanticRouter._extract_text([], None)
        assert result is None

    def test_extract_none_messages_none_prompt(self) -> None:
        result = SemanticRouter._extract_text(None, None)
        assert result is None

    def test_extract_no_user_message(self) -> None:
        messages = [
            {"role": "system", "content": "Be helpful"},
            {"role": "assistant", "content": "Hello!"},
        ]
        result = SemanticRouter._extract_text(messages, None)
        assert result is None

    def test_prompt_takes_precedence(self) -> None:
        messages = [{"role": "user", "content": "from messages"}]
        result = SemanticRouter._extract_text(messages, "from prompt")
        assert result == "from prompt"

    @pytest.mark.asyncio
    async def test_empty_text_returns_original_model(self) -> None:
        router = _make_router(
            rules=[IntentRule(intent="code_generation", route_to="gpt-4o")],
        )
        result = await router.route("base", messages=[])
        assert result == "base"


class TestSemanticRouterPipelineOrder:
    """Verify pipeline order: pattern → A/B → intent → default."""

    @pytest.mark.asyncio
    async def test_pattern_beats_ab_test(self) -> None:
        router = _make_router(
            pattern_rules=[PatternRule(pattern=r"\bSQL\b", route_to="pattern-model")],
            ab_tests=[
                ABTestConfig(name="t1", model_a="ab-model-a", model_b="ab-model-b"),
            ],
        )
        result = await router.route(
            "ab-model-a",
            messages=[{"role": "user", "content": "Write a SQL query"}],
        )
        assert result == "pattern-model"

    @pytest.mark.asyncio
    async def test_ab_test_beats_intent(self) -> None:
        router = _make_router(
            ab_tests=[
                ABTestConfig(
                    name="t1", model_a="gpt-4o", model_b="alternate", traffic_split=0.0,
                ),
            ],
            rules=[IntentRule(intent="code_generation", route_to="intent-model")],
        )
        # traffic_split=0.0 means all traffic goes to model_b
        result = await router.route(
            "gpt-4o",
            messages=[{"role": "user", "content": "Write a Python function to sort"}],
        )
        assert result == "alternate"

    @pytest.mark.asyncio
    async def test_intent_beats_default(self) -> None:
        router = _make_router(
            rules=[IntentRule(intent="translation", route_to="intent-model")],
            default_model="default-model",
        )
        result = await router.route(
            "base",
            messages=[{"role": "user", "content": "Translate this to French"}],
        )
        assert result == "intent-model"


class TestSemanticRouterABTestStats:
    def test_stats_empty(self) -> None:
        router = _make_router()
        assert router.get_ab_test_stats() == []

    def test_stats_returns_all_tests(self) -> None:
        router = _make_router(
            ab_tests=[
                ABTestConfig(name="t1", model_a="a", model_b="b", traffic_split=0.7),
                ABTestConfig(
                    name="t2", model_a="c", model_b="d", enabled=False, metadata={"owner": "team-x"},
                ),
            ],
        )
        stats = router.get_ab_test_stats()
        assert len(stats) == 2
        assert stats[0]["name"] == "t1"
        assert stats[0]["traffic_split"] == 0.7
        assert stats[1]["name"] == "t2"
        assert stats[1]["enabled"] is False
        assert stats[1]["owner"] == "team-x"


class TestSemanticRouterConfig:
    def test_config_property(self) -> None:
        cfg = _make_config(enabled=True, default_model="gpt-4o")
        router = SemanticRouter(cfg)
        assert router.config is cfg

    def test_classifier_property(self) -> None:
        router = _make_router()
        assert isinstance(router.classifier, IntentClassifier)


# ═══════════════════════════════════════════════════════════════════════════
# App startup integration tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAppStartupIntegration:
    """Test that semantic router is initialised correctly during app startup."""

    def test_semantic_router_init_from_config_dict(self) -> None:
        """Verify SemanticRoutingConfig can be constructed from dict (as in app.py)."""
        config_dict = {
            "enabled": True,
            "classifier_model": "gpt-4o-mini",
            "rules": [{"intent": "code_generation", "route_to": "gpt-4o"}],
            "pattern_rules": [{"pattern": r"\bSQL\b", "route_to": "gpt-4o"}],
            "ab_tests": [{"name": "t1", "model_a": "gpt-4o", "model_b": "claude-3"}],
            "default_model": "gpt-3.5-turbo",
        }
        cfg = SemanticRoutingConfig(**config_dict)
        assert cfg.enabled is True
        assert len(cfg.rules) == 1
        assert len(cfg.pattern_rules) == 1
        assert len(cfg.ab_tests) == 1

        router = SemanticRouter(cfg)
        assert router.enabled is True

    def test_empty_config_dict(self) -> None:
        cfg = SemanticRoutingConfig(**{})
        assert cfg.enabled is False
        router = SemanticRouter(cfg)
        assert router.enabled is False
