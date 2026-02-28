"""Tests for the guardrail framework (Task 6.1).

Covers:
- GuardrailAction enum
- GuardrailResult dataclass
- GuardrailContext dataclass
- BaseGuardrail ABC
- GuardrailManager registration and ordering
- Request pipeline: ALLOW, BLOCK, MODIFY
- Response pipeline: ALLOW, BLOCK, MODIFY
- Error isolation (exception → ALLOW)
- Disabled guardrails
- Per-request skip via disabled set
- Priority ordering
- Multiple MODIFY in sequence
- GuardrailPipelineResult properties
"""

from __future__ import annotations

from typing import Any

import pytest

from routerbot.proxy.guardrails.base import (
    BaseGuardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
)
from routerbot.proxy.guardrails.manager import (
    GuardrailManager,
    GuardrailPipelineResult,
    _apply_modification,
)

# ---------------------------------------------------------------------------
# Test guardrail implementations
# ---------------------------------------------------------------------------


class AllowAllGuardrail(BaseGuardrail):
    """Always allows everything."""

    async def check_request(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> GuardrailResult:
        return GuardrailResult(action=GuardrailAction.ALLOW)


class BlockAllGuardrail(BaseGuardrail):
    """Always blocks everything."""

    async def check_request(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> GuardrailResult:
        return GuardrailResult(
            action=GuardrailAction.BLOCK,
            reason="Blocked by policy",
        )

    async def check_response(
        self,
        response: str,
        context: GuardrailContext,
    ) -> GuardrailResult:
        return GuardrailResult(
            action=GuardrailAction.BLOCK,
            reason="Response blocked",
        )


class UppercaseGuardrail(BaseGuardrail):
    """Modifies content to UPPERCASE."""

    async def check_request(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> GuardrailResult:
        import json

        modified = []
        for msg in messages:
            m = {**msg}
            if isinstance(m.get("content"), str):
                m["content"] = m["content"].upper()
            modified.append(m)
        return GuardrailResult(
            action=GuardrailAction.MODIFY,
            modified_content=json.dumps(modified),
        )

    async def check_response(
        self,
        response: str,
        context: GuardrailContext,
    ) -> GuardrailResult:
        return GuardrailResult(
            action=GuardrailAction.MODIFY,
            modified_content=response.upper(),
        )


class AppendGuardrail(BaseGuardrail):
    """Appends ' [checked]' to last user message content."""

    async def check_request(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> GuardrailResult:
        import json

        modified = []
        for i, msg in enumerate(messages):
            m = {**msg}
            if i == len(messages) - 1 and m.get("role") == "user":
                m["content"] = (m.get("content") or "") + " [checked]"
            modified.append(m)
        return GuardrailResult(
            action=GuardrailAction.MODIFY,
            modified_content=json.dumps(modified),
        )


class ExplodingGuardrail(BaseGuardrail):
    """Always raises an exception."""

    async def check_request(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> GuardrailResult:
        msg = "Guardrail crashed!"
        raise RuntimeError(msg)

    async def check_response(
        self,
        response: str,
        context: GuardrailContext,
    ) -> GuardrailResult:
        msg = "Guardrail crashed on response!"
        raise RuntimeError(msg)


class KeywordBlockGuardrail(BaseGuardrail):
    """Blocks requests containing specific keywords."""

    def __init__(self, keywords: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._keywords = [kw.lower() for kw in keywords]

    async def check_request(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> GuardrailResult:
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                for kw in self._keywords:
                    if kw in content.lower():
                        return GuardrailResult(
                            action=GuardrailAction.BLOCK,
                            reason=f"Banned keyword detected: {kw}",
                            details={"keyword": kw},
                        )
        return GuardrailResult(action=GuardrailAction.ALLOW)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager() -> GuardrailManager:
    """Fresh guardrail manager."""
    return GuardrailManager()


@pytest.fixture()
def context() -> GuardrailContext:
    """Sample request context."""
    return GuardrailContext(
        request_id="req-001",
        user_id="user-1",
        team_id="team-1",
        model="gpt-4",
    )


@pytest.fixture()
def sample_messages() -> list[dict[str, Any]]:
    """Sample conversation messages."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello, world!"},
    ]


# ===================================================================
# GuardrailAction Tests
# ===================================================================


class TestGuardrailAction:
    """Tests for the GuardrailAction enum."""

    def test_values(self) -> None:
        assert GuardrailAction.ALLOW == "allow"
        assert GuardrailAction.BLOCK == "block"
        assert GuardrailAction.MODIFY == "modify"

    def test_all_values(self) -> None:
        assert set(GuardrailAction) == {
            GuardrailAction.ALLOW,
            GuardrailAction.BLOCK,
            GuardrailAction.MODIFY,
        }


# ===================================================================
# GuardrailResult Tests
# ===================================================================


class TestGuardrailResult:
    """Tests for the GuardrailResult dataclass."""

    def test_allow_result(self) -> None:
        result = GuardrailResult(action=GuardrailAction.ALLOW)
        assert result.action == GuardrailAction.ALLOW
        assert result.modified_content is None
        assert result.reason is None
        assert result.guardrail_name == ""
        assert result.details == {}

    def test_block_result(self) -> None:
        result = GuardrailResult(
            action=GuardrailAction.BLOCK,
            reason="Toxic content detected",
            guardrail_name="content_mod",
        )
        assert result.action == GuardrailAction.BLOCK
        assert result.reason == "Toxic content detected"
        assert result.guardrail_name == "content_mod"

    def test_modify_result(self) -> None:
        result = GuardrailResult(
            action=GuardrailAction.MODIFY,
            modified_content="redacted message",
            details={"entities": ["email"]},
        )
        assert result.modified_content == "redacted message"
        assert result.details == {"entities": ["email"]}


# ===================================================================
# GuardrailContext Tests
# ===================================================================


class TestGuardrailContext:
    """Tests for the GuardrailContext dataclass."""

    def test_defaults(self) -> None:
        ctx = GuardrailContext()
        assert ctx.request_id == ""
        assert ctx.user_id is None
        assert ctx.team_id is None
        assert ctx.key_id is None
        assert ctx.model == ""
        assert ctx.metadata == {}

    def test_full_context(self) -> None:
        ctx = GuardrailContext(
            request_id="req-1",
            user_id="usr-1",
            team_id="team-1",
            key_id="key-1",
            model="gpt-4",
            metadata={"env": "prod"},
        )
        assert ctx.request_id == "req-1"
        assert ctx.metadata == {"env": "prod"}


# ===================================================================
# BaseGuardrail Tests
# ===================================================================


class TestBaseGuardrail:
    """Tests for the BaseGuardrail ABC."""

    def test_name_from_class(self) -> None:
        g = AllowAllGuardrail()
        assert g.name == "AllowAllGuardrail"

    def test_custom_name(self) -> None:
        g = AllowAllGuardrail(name="my_guardrail")
        assert g.name == "my_guardrail"

    def test_enabled_default(self) -> None:
        g = AllowAllGuardrail()
        assert g.enabled is True

    def test_disabled(self) -> None:
        g = AllowAllGuardrail(enabled=False)
        assert g.enabled is False

    def test_priority_default(self) -> None:
        g = AllowAllGuardrail()
        assert g.priority == 100

    def test_custom_priority(self) -> None:
        g = AllowAllGuardrail(priority=1)
        assert g.priority == 1

    @pytest.mark.asyncio()
    async def test_default_check_response_allows(self, context: GuardrailContext) -> None:
        """Default check_response returns ALLOW."""
        g = AllowAllGuardrail()
        result = await g.check_response("Some response text", context)
        assert result.action == GuardrailAction.ALLOW
        assert result.guardrail_name == "AllowAllGuardrail"


# ===================================================================
# GuardrailManager Registration Tests
# ===================================================================


class TestGuardrailManagerRegistration:
    """Tests for guardrail registration and ordering."""

    def test_register_single(self, manager: GuardrailManager) -> None:
        g = AllowAllGuardrail(name="g1")
        manager.register(g)
        assert manager.registered == ["g1"]

    def test_register_multiple_sorted_by_priority(self, manager: GuardrailManager) -> None:
        manager.register(AllowAllGuardrail(name="low", priority=10))
        manager.register(AllowAllGuardrail(name="high", priority=1))
        manager.register(AllowAllGuardrail(name="mid", priority=5))
        assert manager.registered == ["high", "mid", "low"]

    def test_unregister_existing(self, manager: GuardrailManager) -> None:
        manager.register(AllowAllGuardrail(name="g1"))
        assert manager.unregister("g1") is True
        assert manager.registered == []

    def test_unregister_nonexistent(self, manager: GuardrailManager) -> None:
        assert manager.unregister("nonexistent") is False

    def test_registered_empty(self, manager: GuardrailManager) -> None:
        assert manager.registered == []


# ===================================================================
# Request Pipeline Tests
# ===================================================================


class TestRequestPipelineAllow:
    """Tests for the ALLOW path through the request pipeline."""

    @pytest.mark.asyncio()
    async def test_empty_pipeline_allows(
        self,
        manager: GuardrailManager,
        sample_messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> None:
        """No guardrails → ALLOW with original messages."""
        result = await manager.run_request_guardrails(sample_messages, context)
        assert result.action == GuardrailAction.ALLOW
        assert result.modified_messages == sample_messages
        assert not result.blocked
        assert not result.modified
        assert result.results == []

    @pytest.mark.asyncio()
    async def test_all_allow(
        self,
        manager: GuardrailManager,
        sample_messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> None:
        """All guardrails ALLOW → pipeline ALLOW."""
        manager.register(AllowAllGuardrail(name="g1", priority=1))
        manager.register(AllowAllGuardrail(name="g2", priority=2))

        result = await manager.run_request_guardrails(sample_messages, context)
        assert result.action == GuardrailAction.ALLOW
        assert len(result.results) == 2
        assert all(r.action == GuardrailAction.ALLOW for r in result.results)


class TestRequestPipelineBlock:
    """Tests for the BLOCK path through the request pipeline."""

    @pytest.mark.asyncio()
    async def test_single_block(
        self,
        manager: GuardrailManager,
        sample_messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> None:
        """A BLOCK guardrail stops the pipeline."""
        manager.register(BlockAllGuardrail(name="blocker"))

        result = await manager.run_request_guardrails(sample_messages, context)
        assert result.blocked
        assert result.action == GuardrailAction.BLOCK
        assert result.blocking_result is not None
        assert result.blocking_result.reason == "Blocked by policy"
        assert result.blocking_result.guardrail_name == "blocker"

    @pytest.mark.asyncio()
    async def test_block_short_circuits(
        self,
        manager: GuardrailManager,
        sample_messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> None:
        """After a BLOCK, subsequent guardrails do NOT run."""
        manager.register(BlockAllGuardrail(name="blocker", priority=1))
        manager.register(AllowAllGuardrail(name="never_reached", priority=2))

        result = await manager.run_request_guardrails(sample_messages, context)
        assert result.blocked
        assert len(result.results) == 1  # only the blocker ran
        assert result.results[0].guardrail_name == "blocker"

    @pytest.mark.asyncio()
    async def test_allow_then_block(
        self,
        manager: GuardrailManager,
        sample_messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> None:
        """ALLOW first, then BLOCK → pipeline result is BLOCK."""
        manager.register(AllowAllGuardrail(name="allow", priority=1))
        manager.register(BlockAllGuardrail(name="block", priority=2))

        result = await manager.run_request_guardrails(sample_messages, context)
        assert result.blocked
        assert len(result.results) == 2

    @pytest.mark.asyncio()
    async def test_keyword_block(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        """Keyword block detects banned words."""
        manager.register(KeywordBlockGuardrail(["forbidden"], name="keywords", priority=1))

        messages = [{"role": "user", "content": "Tell me about forbidden topics"}]
        result = await manager.run_request_guardrails(messages, context)
        assert result.blocked
        assert "forbidden" in (result.blocking_result.reason or "")


class TestRequestPipelineModify:
    """Tests for the MODIFY path through the request pipeline."""

    @pytest.mark.asyncio()
    async def test_single_modify(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        """A MODIFY guardrail transforms the content."""
        manager.register(UppercaseGuardrail(name="upper"))

        messages = [{"role": "user", "content": "hello"}]
        result = await manager.run_request_guardrails(messages, context)
        assert result.modified
        assert result.action == GuardrailAction.MODIFY
        assert result.modified_messages is not None
        assert result.modified_messages[0]["content"] == "HELLO"

    @pytest.mark.asyncio()
    async def test_chained_modify(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        """Multiple MODIFY guardrails are applied in sequence."""
        manager.register(UppercaseGuardrail(name="upper", priority=1))
        manager.register(AppendGuardrail(name="append", priority=2))

        messages = [{"role": "user", "content": "hello"}]
        result = await manager.run_request_guardrails(messages, context)
        assert result.modified
        # First uppercase: "HELLO", then append: "HELLO [checked]"
        assert result.modified_messages is not None
        assert result.modified_messages[0]["content"] == "HELLO [checked]"

    @pytest.mark.asyncio()
    async def test_modify_then_block(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        """MODIFY followed by BLOCK → result is BLOCK."""
        manager.register(UppercaseGuardrail(name="upper", priority=1))
        manager.register(BlockAllGuardrail(name="block", priority=2))

        messages = [{"role": "user", "content": "hello"}]
        result = await manager.run_request_guardrails(messages, context)
        assert result.blocked
        assert result.modified_messages is None


# ===================================================================
# Response Pipeline Tests
# ===================================================================


class TestResponsePipeline:
    """Tests for the post-response guardrail pipeline."""

    @pytest.mark.asyncio()
    async def test_empty_pipeline_allows(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        result = await manager.run_response_guardrails("Hello!", context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_response_block(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        manager.register(BlockAllGuardrail(name="blocker"))

        result = await manager.run_response_guardrails("Bad content", context)
        assert result.blocked
        assert result.blocking_result is not None
        assert result.blocking_result.reason == "Response blocked"

    @pytest.mark.asyncio()
    async def test_response_modify(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        manager.register(UppercaseGuardrail(name="upper"))

        result = await manager.run_response_guardrails("hello world", context)
        assert result.modified
        assert result.modified_messages is not None
        assert result.modified_messages[0]["content"] == "HELLO WORLD"

    @pytest.mark.asyncio()
    async def test_response_allow(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        """AllowAllGuardrail defaults to ALLOW on response."""
        manager.register(AllowAllGuardrail(name="allow"))

        result = await manager.run_response_guardrails("ok", context)
        assert result.action == GuardrailAction.ALLOW


# ===================================================================
# Error Isolation Tests
# ===================================================================


class TestErrorIsolation:
    """Tests that guardrail exceptions don't break the pipeline."""

    @pytest.mark.asyncio()
    async def test_exception_treated_as_allow_request(
        self,
        manager: GuardrailManager,
        sample_messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> None:
        """A guardrail that raises is treated as ALLOW."""
        manager.register(ExplodingGuardrail(name="exploder", priority=1))
        manager.register(AllowAllGuardrail(name="allow", priority=2))

        result = await manager.run_request_guardrails(sample_messages, context)
        assert result.action == GuardrailAction.ALLOW
        assert len(result.results) == 2
        assert result.results[0].reason == "Guardrail error (treated as allow)"

    @pytest.mark.asyncio()
    async def test_exception_treated_as_allow_response(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        """An exception in response check is treated as ALLOW."""
        manager.register(ExplodingGuardrail(name="exploder"))

        result = await manager.run_response_guardrails("test", context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_exception_before_block(
        self,
        manager: GuardrailManager,
        sample_messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> None:
        """Exception in one guardrail doesn't prevent a later BLOCK."""
        manager.register(ExplodingGuardrail(name="exploder", priority=1))
        manager.register(BlockAllGuardrail(name="blocker", priority=2))

        result = await manager.run_request_guardrails(sample_messages, context)
        assert result.blocked
        assert len(result.results) == 2


# ===================================================================
# Disabled Guardrails Tests
# ===================================================================


class TestDisabledGuardrails:
    """Tests for disabled guardrails."""

    @pytest.mark.asyncio()
    async def test_disabled_guardrail_skipped(
        self,
        manager: GuardrailManager,
        sample_messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> None:
        """Disabled guardrails do not run."""
        manager.register(BlockAllGuardrail(name="block", enabled=False))
        manager.register(AllowAllGuardrail(name="allow", priority=200))

        result = await manager.run_request_guardrails(sample_messages, context)
        assert result.action == GuardrailAction.ALLOW
        assert len(result.results) == 1  # only the allow ran

    @pytest.mark.asyncio()
    async def test_per_request_disable(
        self,
        manager: GuardrailManager,
        sample_messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> None:
        """Per-request disabled set skips specific guardrails."""
        manager.register(BlockAllGuardrail(name="block", priority=1))
        manager.register(AllowAllGuardrail(name="allow", priority=2))

        result = await manager.run_request_guardrails(sample_messages, context, disabled={"block"})
        assert result.action == GuardrailAction.ALLOW
        assert len(result.results) == 1

    @pytest.mark.asyncio()
    async def test_per_request_disable_response(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        """Per-request disabled set works for response guardrails too."""
        manager.register(BlockAllGuardrail(name="block"))

        result = await manager.run_response_guardrails("test", context, disabled={"block"})
        assert result.action == GuardrailAction.ALLOW


# ===================================================================
# Priority Ordering Tests
# ===================================================================


class TestPriorityOrdering:
    """Tests for guardrail execution order."""

    @pytest.mark.asyncio()
    async def test_priority_determines_order(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        """Guardrails run in ascending priority order."""
        execution_order: list[str] = []

        class TrackingGuardrail(BaseGuardrail):
            async def check_request(
                self,
                messages: list[dict[str, Any]],
                context: GuardrailContext,
            ) -> GuardrailResult:
                execution_order.append(self.name)
                return GuardrailResult(action=GuardrailAction.ALLOW)

        manager.register(TrackingGuardrail(name="third", priority=30))
        manager.register(TrackingGuardrail(name="first", priority=10))
        manager.register(TrackingGuardrail(name="second", priority=20))

        messages = [{"role": "user", "content": "test"}]
        await manager.run_request_guardrails(messages, context)
        assert execution_order == ["first", "second", "third"]

    @pytest.mark.asyncio()
    async def test_same_priority_preserves_registration_order(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        """Guardrails with the same priority run in registration order."""
        execution_order: list[str] = []

        class TrackingGuardrail(BaseGuardrail):
            async def check_request(
                self,
                messages: list[dict[str, Any]],
                context: GuardrailContext,
            ) -> GuardrailResult:
                execution_order.append(self.name)
                return GuardrailResult(action=GuardrailAction.ALLOW)

        manager.register(TrackingGuardrail(name="a", priority=10))
        manager.register(TrackingGuardrail(name="b", priority=10))
        manager.register(TrackingGuardrail(name="c", priority=10))

        messages = [{"role": "user", "content": "test"}]
        await manager.run_request_guardrails(messages, context)
        assert execution_order == ["a", "b", "c"]


# ===================================================================
# GuardrailPipelineResult Tests
# ===================================================================


class TestGuardrailPipelineResult:
    """Tests for the pipeline result helper class."""

    def test_defaults(self) -> None:
        result = GuardrailPipelineResult()
        assert result.action == GuardrailAction.ALLOW
        assert result.modified_messages is None
        assert result.blocking_result is None
        assert result.results == []
        assert not result.blocked
        assert not result.modified

    def test_blocked_property(self) -> None:
        result = GuardrailPipelineResult()
        result.action = GuardrailAction.BLOCK
        assert result.blocked

    def test_modified_property(self) -> None:
        result = GuardrailPipelineResult()
        result.action = GuardrailAction.MODIFY
        assert result.modified


# ===================================================================
# _apply_modification Helper Tests
# ===================================================================


class TestApplyModification:
    """Tests for the _apply_modification helper."""

    def test_json_array_modification(self) -> None:
        """JSON-encoded message list replaces the entire messages."""
        import json

        messages = [{"role": "user", "content": "hello"}]
        new_messages = [{"role": "user", "content": "HELLO"}]
        result = _apply_modification(messages, json.dumps(new_messages))
        assert result == new_messages

    def test_plain_text_replaces_last_user(self) -> None:
        """Plain text replaces the content of the last user message."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "original"},
        ]
        result = _apply_modification(messages, "modified")
        assert result[0]["content"] == "sys"
        assert result[1]["content"] == "modified"

    def test_plain_text_multiple_user_messages(self) -> None:
        """With multiple user messages, only the LAST one is replaced."""
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "second"},
        ]
        result = _apply_modification(messages, "modified")
        assert result[0]["content"] == "first"
        assert result[1]["content"] == "response"
        assert result[2]["content"] == "modified"

    def test_no_user_message(self) -> None:
        """If no user message exists, return original messages unchanged."""
        messages = [{"role": "system", "content": "sys"}]
        result = _apply_modification(messages, "modified")
        assert result == messages

    def test_invalid_json(self) -> None:
        """Invalid JSON falls back to plain text replacement."""
        messages = [{"role": "user", "content": "hello"}]
        result = _apply_modification(messages, "not json {{{")
        assert result[0]["content"] == "not json {{{"

    def test_json_non_array(self) -> None:
        """JSON that's not an array falls back to plain text replacement."""
        messages = [{"role": "user", "content": "hello"}]
        result = _apply_modification(messages, '{"key": "value"}')
        assert result[0]["content"] == '{"key": "value"}'


# ===================================================================
# Complex Scenario Tests
# ===================================================================


class TestComplexScenarios:
    """End-to-end scenarios combining multiple guardrails."""

    @pytest.mark.asyncio()
    async def test_full_pipeline_allow_modify_allow(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        """ALLOW → MODIFY → ALLOW pipeline."""
        manager.register(AllowAllGuardrail(name="pre", priority=1))
        manager.register(UppercaseGuardrail(name="upper", priority=2))
        manager.register(AllowAllGuardrail(name="post", priority=3))

        messages = [{"role": "user", "content": "hello"}]
        result = await manager.run_request_guardrails(messages, context)
        assert result.modified
        assert len(result.results) == 3
        assert result.modified_messages[0]["content"] == "HELLO"

    @pytest.mark.asyncio()
    async def test_keyword_block_with_modify_first(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        """Modified content is checked by subsequent guardrails."""
        # Upper first, then keyword check on uppercase content
        manager.register(UppercaseGuardrail(name="upper", priority=1))
        manager.register(
            KeywordBlockGuardrail(["forbidden"], name="keywords", priority=2),
        )

        messages = [{"role": "user", "content": "FORBIDDEN topic"}]
        result = await manager.run_request_guardrails(messages, context)
        assert result.blocked
        assert "forbidden" in (result.blocking_result.reason or "").lower()

    @pytest.mark.asyncio()
    async def test_exploding_then_modify_then_allow(
        self,
        manager: GuardrailManager,
        context: GuardrailContext,
    ) -> None:
        """Exception → MODIFY → ALLOW works correctly."""
        manager.register(ExplodingGuardrail(name="boom", priority=1))
        manager.register(UppercaseGuardrail(name="upper", priority=2))
        manager.register(AllowAllGuardrail(name="ok", priority=3))

        messages = [{"role": "user", "content": "hello"}]
        result = await manager.run_request_guardrails(messages, context)
        assert result.modified
        assert result.modified_messages[0]["content"] == "HELLO"
        assert len(result.results) == 3

    @pytest.mark.asyncio()
    async def test_context_passed_to_guardrails(
        self,
        manager: GuardrailManager,
    ) -> None:
        """Guardrails receive the correct context."""
        received_ctx: list[GuardrailContext] = []

        class CapturingGuardrail(BaseGuardrail):
            async def check_request(
                self,
                messages: list[dict[str, Any]],
                ctx: GuardrailContext,
            ) -> GuardrailResult:
                received_ctx.append(ctx)
                return GuardrailResult(action=GuardrailAction.ALLOW)

        manager.register(CapturingGuardrail(name="capture"))

        ctx = GuardrailContext(
            request_id="req-42",
            user_id="user-x",
            team_id="team-y",
            model="claude-3",
        )
        messages = [{"role": "user", "content": "test"}]
        await manager.run_request_guardrails(messages, ctx)

        assert len(received_ctx) == 1
        assert received_ctx[0].request_id == "req-42"
        assert received_ctx[0].model == "claude-3"
