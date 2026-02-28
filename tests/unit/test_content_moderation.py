"""Tests for the content moderation guardrail (Task 6.4).

Covers:
- ModerationScore, ModerationResult dataclasses
- KeywordModerationBackend
- OpenAIModerationBackend._parse_response (unit test without HTTP)
- CustomHTTPModerationBackend._parse_response (unit test without HTTP)
- ContentModerationGuardrail in block and flag modes
- Threshold override logic
- Response checking
- Backend error handling (fail-open)
- Integration with GuardrailManager
"""

from __future__ import annotations

import pytest

from routerbot.proxy.guardrails.base import (
    GuardrailAction,
    GuardrailContext,
)
from routerbot.proxy.guardrails.content_moderation import (
    ContentModerationGuardrail,
    CustomHTTPModerationBackend,
    KeywordModerationBackend,
    ModerationBackend,
    ModerationResult,
    ModerationScore,
    OpenAIModerationBackend,
    create_keyword_moderation_backend,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def context() -> GuardrailContext:
    return GuardrailContext(request_id="req-mod-001", model="gpt-4")


@pytest.fixture()
def keyword_backend() -> KeywordModerationBackend:
    return KeywordModerationBackend(
        category_keywords={
            "hate": ["hate speech", "slur"],
            "violence": ["kill", "attack", "murder"],
            "sexual": ["explicit content"],
        }
    )


class MockBackend(ModerationBackend):
    """A mock moderation backend for testing."""

    def __init__(self, result: ModerationResult | None = None) -> None:
        self._result = result or ModerationResult(flagged=False)

    async def check(self, content: str) -> ModerationResult:
        return self._result


class FailingBackend(ModerationBackend):
    """Backend that always raises an exception."""

    async def check(self, content: str) -> ModerationResult:
        msg = "Backend unavailable"
        raise ConnectionError(msg)


# ===================================================================
# ModerationScore / ModerationResult Tests
# ===================================================================


class TestModerationResult:
    """Tests for moderation data classes."""

    def test_not_flagged(self) -> None:
        result = ModerationResult(flagged=False)
        assert result.flagged is False
        assert result.flagged_categories == []

    def test_flagged_categories(self) -> None:
        scores = [
            ModerationScore(category="hate", score=0.9, flagged=True),
            ModerationScore(category="violence", score=0.3, flagged=False),
            ModerationScore(category="sexual", score=0.95, flagged=True),
        ]
        result = ModerationResult(flagged=True, scores=scores)
        assert result.flagged is True
        assert set(result.flagged_categories) == {"hate", "sexual"}


# ===================================================================
# KeywordModerationBackend Tests
# ===================================================================


class TestKeywordBackend:
    """Tests for the keyword-based moderation backend."""

    @pytest.mark.asyncio()
    async def test_no_keywords_matched(self, keyword_backend: KeywordModerationBackend) -> None:
        result = await keyword_backend.check("This is a normal message")
        assert result.flagged is False

    @pytest.mark.asyncio()
    async def test_hate_keyword(self, keyword_backend: KeywordModerationBackend) -> None:
        result = await keyword_backend.check("This contains hate speech")
        assert result.flagged is True
        assert "hate" in result.flagged_categories

    @pytest.mark.asyncio()
    async def test_violence_keyword(self, keyword_backend: KeywordModerationBackend) -> None:
        result = await keyword_backend.check("Plans to attack the server")
        assert result.flagged is True
        assert "violence" in result.flagged_categories

    @pytest.mark.asyncio()
    async def test_multiple_categories(self, keyword_backend: KeywordModerationBackend) -> None:
        result = await keyword_backend.check("hate speech and kill")
        assert result.flagged is True
        assert "hate" in result.flagged_categories
        assert "violence" in result.flagged_categories

    @pytest.mark.asyncio()
    async def test_case_insensitive(self) -> None:
        backend = KeywordModerationBackend(
            category_keywords={"hate": ["BADWORD"]},
            case_sensitive=False,
        )
        result = await backend.check("contains badword here")
        assert result.flagged is True

    @pytest.mark.asyncio()
    async def test_case_sensitive(self) -> None:
        backend = KeywordModerationBackend(
            category_keywords={"hate": ["BADWORD"]},
            case_sensitive=True,
        )
        # Lowercase should not match
        result = await backend.check("contains badword here")
        assert result.flagged is False

        # Uppercase should match
        result2 = await backend.check("contains BADWORD here")
        assert result2.flagged is True

    @pytest.mark.asyncio()
    async def test_score_values(self, keyword_backend: KeywordModerationBackend) -> None:
        result = await keyword_backend.check("hate speech")
        hate_score = next(s for s in result.scores if s.category == "hate")
        assert hate_score.score == 1.0
        assert hate_score.flagged is True

        violence_score = next(s for s in result.scores if s.category == "violence")
        assert violence_score.score == 0.0
        assert violence_score.flagged is False

    @pytest.mark.asyncio()
    async def test_empty_keywords(self) -> None:
        backend = KeywordModerationBackend()
        result = await backend.check("anything")
        assert result.flagged is False
        assert result.scores == []


# ===================================================================
# OpenAIModerationBackend Parse Tests
# ===================================================================


class TestOpenAIBackendParse:
    """Tests for OpenAI moderation response parsing (no HTTP calls)."""

    def test_parse_flagged(self) -> None:
        backend = OpenAIModerationBackend()
        data = {
            "results": [
                {
                    "flagged": True,
                    "categories": {"hate": True, "violence": False},
                    "category_scores": {"hate": 0.92, "violence": 0.1},
                }
            ]
        }
        result = backend._parse_response(data)
        assert result.flagged is True
        assert "hate" in result.flagged_categories
        assert "violence" not in result.flagged_categories

    def test_parse_not_flagged(self) -> None:
        backend = OpenAIModerationBackend()
        data = {
            "results": [
                {
                    "flagged": False,
                    "categories": {"hate": False},
                    "category_scores": {"hate": 0.01},
                }
            ]
        }
        result = backend._parse_response(data)
        assert result.flagged is False

    def test_parse_empty_results(self) -> None:
        backend = OpenAIModerationBackend()
        data = {"results": []}
        result = backend._parse_response(data)
        assert result.flagged is False

    def test_parse_multiple_categories(self) -> None:
        backend = OpenAIModerationBackend()
        data = {
            "results": [
                {
                    "flagged": True,
                    "categories": {
                        "hate": True,
                        "sexual": True,
                        "violence": False,
                    },
                    "category_scores": {
                        "hate": 0.85,
                        "sexual": 0.92,
                        "violence": 0.05,
                    },
                }
            ]
        }
        result = backend._parse_response(data)
        assert len(result.scores) == 3
        flagged = {s.category for s in result.scores if s.flagged}
        assert flagged == {"hate", "sexual"}


# ===================================================================
# CustomHTTPModerationBackend Parse Tests
# ===================================================================


class TestCustomBackendParse:
    """Tests for custom HTTP backend response parsing."""

    def test_parse_dict_categories(self) -> None:
        backend = CustomHTTPModerationBackend(endpoint="http://localhost")
        data = {
            "flagged": True,
            "categories": {
                "hate": {"score": 0.9, "flagged": True},
                "safe": {"score": 0.1, "flagged": False},
            },
        }
        result = backend._parse_response(data)
        assert result.flagged is True
        assert len(result.scores) == 2

    def test_parse_numeric_categories(self) -> None:
        backend = CustomHTTPModerationBackend(endpoint="http://localhost")
        data = {
            "flagged": True,
            "categories": {"hate": 0.9, "safe": 0.1},
        }
        result = backend._parse_response(data)
        assert len(result.scores) == 2
        hate = next(s for s in result.scores if s.category == "hate")
        assert hate.score == 0.9

    def test_parse_not_flagged(self) -> None:
        backend = CustomHTTPModerationBackend(endpoint="http://localhost")
        data = {"flagged": False, "categories": {}}
        result = backend._parse_response(data)
        assert result.flagged is False


# ===================================================================
# ContentModerationGuardrail — Block Mode Tests
# ===================================================================


class TestBlockMode:
    """Tests for the guardrail in block mode."""

    @pytest.mark.asyncio()
    async def test_safe_content_allows(self, context: GuardrailContext) -> None:
        backend = MockBackend(ModerationResult(flagged=False))
        guardrail = ContentModerationGuardrail(backend=backend, mode="block", name="mod")
        messages = [{"role": "user", "content": "Hello!"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_flagged_content_blocks(self, context: GuardrailContext) -> None:
        scores = [ModerationScore(category="hate", score=0.95, flagged=True)]
        backend = MockBackend(ModerationResult(flagged=True, scores=scores))
        guardrail = ContentModerationGuardrail(backend=backend, mode="block", name="mod")
        messages = [{"role": "user", "content": "bad content"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK
        assert "hate" in (result.reason or "")

    @pytest.mark.asyncio()
    async def test_block_details(self, context: GuardrailContext) -> None:
        scores = [
            ModerationScore(category="hate", score=0.95, flagged=True),
            ModerationScore(category="violence", score=0.8, flagged=True),
        ]
        backend = MockBackend(ModerationResult(flagged=True, scores=scores))
        guardrail = ContentModerationGuardrail(backend=backend, mode="block", name="mod")
        messages = [{"role": "user", "content": "bad"}]
        result = await guardrail.check_request(messages, context)
        assert "flagged_categories" in result.details
        assert "hate" in result.details["flagged_categories"]

    @pytest.mark.asyncio()
    async def test_empty_messages(self, context: GuardrailContext) -> None:
        backend = MockBackend()
        guardrail = ContentModerationGuardrail(backend=backend, mode="block", name="mod")
        messages = [{"role": "user", "content": ""}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_non_string_content(self, context: GuardrailContext) -> None:
        backend = MockBackend()
        guardrail = ContentModerationGuardrail(backend=backend, mode="block", name="mod")
        messages = [{"role": "user", "content": [{"type": "text"}]}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW


# ===================================================================
# ContentModerationGuardrail — Flag Mode Tests
# ===================================================================


class TestFlagMode:
    """Tests for the guardrail in flag mode."""

    @pytest.mark.asyncio()
    async def test_flagged_content_allows(self, context: GuardrailContext) -> None:
        scores = [ModerationScore(category="hate", score=0.9, flagged=True)]
        backend = MockBackend(ModerationResult(flagged=True, scores=scores))
        guardrail = ContentModerationGuardrail(backend=backend, mode="flag", name="mod")
        messages = [{"role": "user", "content": "some content"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW
        assert result.details.get("moderation_flagged") is True

    @pytest.mark.asyncio()
    async def test_safe_content_no_flag(self, context: GuardrailContext) -> None:
        backend = MockBackend(ModerationResult(flagged=False))
        guardrail = ContentModerationGuardrail(backend=backend, mode="flag", name="mod")
        messages = [{"role": "user", "content": "Hello"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW
        assert result.details.get("moderation_flagged") is None


# ===================================================================
# Threshold Override Tests
# ===================================================================


class TestThresholds:
    """Tests for per-category threshold overrides."""

    @pytest.mark.asyncio()
    async def test_threshold_overrides_flag(self, context: GuardrailContext) -> None:
        """Score below custom threshold should NOT be flagged."""
        scores = [
            ModerationScore(category="hate", score=0.5, flagged=True),
        ]
        backend = MockBackend(ModerationResult(flagged=True, scores=scores))
        guardrail = ContentModerationGuardrail(
            backend=backend,
            mode="block",
            thresholds={"hate": 0.8},
            name="mod",
        )
        messages = [{"role": "user", "content": "test"}]
        result = await guardrail.check_request(messages, context)
        # Score 0.5 < threshold 0.8 → should not block
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_threshold_exceeds_blocks(self, context: GuardrailContext) -> None:
        """Score at or above threshold should be flagged."""
        scores = [
            ModerationScore(category="hate", score=0.85, flagged=False),
        ]
        backend = MockBackend(ModerationResult(flagged=False, scores=scores))
        guardrail = ContentModerationGuardrail(
            backend=backend,
            mode="block",
            thresholds={"hate": 0.8},
            name="mod",
        )
        messages = [{"role": "user", "content": "test"}]
        result = await guardrail.check_request(messages, context)
        # Score 0.85 >= threshold 0.8 → should block
        assert result.action == GuardrailAction.BLOCK

    @pytest.mark.asyncio()
    async def test_threshold_mixed_categories(self, context: GuardrailContext) -> None:
        scores = [
            ModerationScore(category="hate", score=0.3, flagged=True),
            ModerationScore(category="violence", score=0.7, flagged=True),
        ]
        backend = MockBackend(ModerationResult(flagged=True, scores=scores))
        guardrail = ContentModerationGuardrail(
            backend=backend,
            mode="block",
            thresholds={"hate": 0.5, "violence": 0.6},
            name="mod",
        )
        messages = [{"role": "user", "content": "test"}]
        result = await guardrail.check_request(messages, context)
        # hate 0.3 < 0.5 (not flagged), violence 0.7 >= 0.6 (flagged)
        assert result.action == GuardrailAction.BLOCK
        assert "violence" in result.details["flagged_categories"]
        assert "hate" not in result.details["flagged_categories"]

    @pytest.mark.asyncio()
    async def test_no_threshold_uses_backend_flags(self, context: GuardrailContext) -> None:
        """Without thresholds, backend's native flags are used."""
        scores = [
            ModerationScore(category="hate", score=0.1, flagged=True),
        ]
        backend = MockBackend(ModerationResult(flagged=True, scores=scores))
        guardrail = ContentModerationGuardrail(backend=backend, mode="block", name="mod")
        messages = [{"role": "user", "content": "test"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK


# ===================================================================
# Backend Error Handling Tests
# ===================================================================


class TestBackendErrors:
    """Tests for fail-open behavior on backend errors."""

    @pytest.mark.asyncio()
    async def test_backend_error_allows_request(self, context: GuardrailContext) -> None:
        guardrail = ContentModerationGuardrail(backend=FailingBackend(), mode="block", name="mod")
        messages = [{"role": "user", "content": "test"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW
        assert result.details.get("error") is True

    @pytest.mark.asyncio()
    async def test_backend_error_allows_response(self, context: GuardrailContext) -> None:
        guardrail = ContentModerationGuardrail(
            backend=FailingBackend(),
            mode="block",
            check_response_content=True,
            name="mod",
        )
        result = await guardrail.check_response("test", context)
        assert result.action == GuardrailAction.ALLOW
        assert result.details.get("error") is True


# ===================================================================
# Response Checking Tests
# ===================================================================


class TestResponseChecking:
    """Tests for checking model responses."""

    @pytest.mark.asyncio()
    async def test_disabled_by_default(self, context: GuardrailContext) -> None:
        backend = MockBackend()
        guardrail = ContentModerationGuardrail(backend=backend, mode="block", name="mod")
        result = await guardrail.check_response("anything", context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_response_blocked(self, context: GuardrailContext) -> None:
        scores = [ModerationScore(category="hate", score=0.9, flagged=True)]
        backend = MockBackend(ModerationResult(flagged=True, scores=scores))
        guardrail = ContentModerationGuardrail(
            backend=backend,
            mode="block",
            check_response_content=True,
            name="mod",
        )
        result = await guardrail.check_response("bad response", context)
        assert result.action == GuardrailAction.BLOCK

    @pytest.mark.asyncio()
    async def test_response_flagged(self, context: GuardrailContext) -> None:
        scores = [ModerationScore(category="hate", score=0.9, flagged=True)]
        backend = MockBackend(ModerationResult(flagged=True, scores=scores))
        guardrail = ContentModerationGuardrail(
            backend=backend,
            mode="flag",
            check_response_content=True,
            name="mod",
        )
        result = await guardrail.check_response("flagged response", context)
        assert result.action == GuardrailAction.ALLOW
        assert result.details.get("moderation_flagged") is True

    @pytest.mark.asyncio()
    async def test_empty_response(self, context: GuardrailContext) -> None:
        backend = MockBackend()
        guardrail = ContentModerationGuardrail(
            backend=backend,
            mode="block",
            check_response_content=True,
            name="mod",
        )
        result = await guardrail.check_response("", context)
        assert result.action == GuardrailAction.ALLOW


# ===================================================================
# Keyword Backend Integration Tests
# ===================================================================


class TestKeywordIntegration:
    """End-to-end tests with keyword backend."""

    @pytest.mark.asyncio()
    async def test_keyword_block(self, context: GuardrailContext) -> None:
        backend = create_keyword_moderation_backend(category_keywords={"hate": ["harmful content"]})
        guardrail = ContentModerationGuardrail(backend=backend, mode="block", name="mod")
        messages = [{"role": "user", "content": "This has harmful content"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK

    @pytest.mark.asyncio()
    async def test_keyword_safe(self, context: GuardrailContext) -> None:
        backend = create_keyword_moderation_backend(category_keywords={"hate": ["harmful"]})
        guardrail = ContentModerationGuardrail(backend=backend, mode="block", name="mod")
        messages = [{"role": "user", "content": "A perfectly fine message"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW


# ===================================================================
# Integration with GuardrailManager Tests
# ===================================================================


class TestIntegrationWithManager:
    """Test content moderation within guardrail pipeline."""

    @pytest.mark.asyncio()
    async def test_block_in_pipeline(self, context: GuardrailContext) -> None:
        from routerbot.proxy.guardrails.manager import GuardrailManager

        scores = [ModerationScore(category="hate", score=0.9, flagged=True)]
        backend = MockBackend(ModerationResult(flagged=True, scores=scores))
        manager = GuardrailManager()
        manager.register(ContentModerationGuardrail(backend=backend, mode="block", name="mod", priority=1))

        messages = [{"role": "user", "content": "bad content"}]
        result = await manager.run_request_guardrails(messages, context)
        assert result.blocked

    @pytest.mark.asyncio()
    async def test_allow_in_pipeline(self, context: GuardrailContext) -> None:
        from routerbot.proxy.guardrails.manager import GuardrailManager

        backend = MockBackend(ModerationResult(flagged=False))
        manager = GuardrailManager()
        manager.register(ContentModerationGuardrail(backend=backend, mode="block", name="mod", priority=1))

        messages = [{"role": "user", "content": "hello"}]
        result = await manager.run_request_guardrails(messages, context)
        assert not result.blocked


# ===================================================================
# Properties Tests
# ===================================================================


class TestProperties:
    """Tests for guardrail configuration properties."""

    def test_mode_property(self) -> None:
        g = ContentModerationGuardrail(backend=MockBackend(), mode="flag")
        assert g.mode == "flag"

    def test_backend_property(self) -> None:
        backend = MockBackend()
        g = ContentModerationGuardrail(backend=backend)
        assert g.backend is backend

    def test_name_default(self) -> None:
        g = ContentModerationGuardrail(backend=MockBackend())
        assert g.name == "ContentModerationGuardrail"

    def test_priority(self) -> None:
        g = ContentModerationGuardrail(backend=MockBackend(), priority=5)
        assert g.priority == 5
