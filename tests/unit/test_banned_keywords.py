"""Tests for the banned keywords and blocked users guardrails (Task 6.5).

Covers:
- BannedKeywordsGuardrail: keyword matching, case sensitivity, word
  boundary, add/remove keywords, response checking
- BlockedUsersGuardrail: user/team blocking, block/unblock API,
  is_blocked helper
- Integration with GuardrailManager pipeline
"""

from __future__ import annotations

import pytest

from routerbot.proxy.guardrails.banned_keywords import (
    BannedKeywordsGuardrail,
    BlockedUsersGuardrail,
    KeywordMatch,
)
from routerbot.proxy.guardrails.base import (
    GuardrailAction,
    GuardrailContext,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def context() -> GuardrailContext:
    return GuardrailContext(request_id="req-ban-001", model="gpt-4")


@pytest.fixture()
def user_context() -> GuardrailContext:
    return GuardrailContext(
        request_id="req-ban-002",
        model="gpt-4",
        user_id="user-123",
        team_id="team-abc",
    )


@pytest.fixture()
def kw_guardrail() -> BannedKeywordsGuardrail:
    return BannedKeywordsGuardrail(
        keywords=["forbidden", "banned phrase", "secret_word"],
        name="banned_kw",
    )


@pytest.fixture()
def blocked_guardrail() -> BlockedUsersGuardrail:
    return BlockedUsersGuardrail(
        blocked_user_ids={"blocked-user-1", "blocked-user-2"},
        blocked_team_ids={"blocked-team-1"},
        name="blocked_users",
    )


# ===================================================================
# KeywordMatch Tests
# ===================================================================


class TestKeywordMatch:
    """Tests for KeywordMatch dataclass."""

    def test_create(self) -> None:
        m = KeywordMatch(keyword="bad", matched_text="Bad", start=0, end=3)
        assert m.keyword == "bad"
        assert m.matched_text == "Bad"


# ===================================================================
# BannedKeywordsGuardrail — Basic Tests
# ===================================================================


class TestBannedKeywordsBasic:
    """Tests for basic keyword matching."""

    @pytest.mark.asyncio()
    async def test_no_keywords_no_block(
        self, kw_guardrail: BannedKeywordsGuardrail, context: GuardrailContext
    ) -> None:
        messages = [{"role": "user", "content": "Hello, how are you?"}]
        result = await kw_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_keyword_detected(
        self, kw_guardrail: BannedKeywordsGuardrail, context: GuardrailContext
    ) -> None:
        messages = [{"role": "user", "content": "This is forbidden content"}]
        result = await kw_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK
        assert "forbidden" in (result.reason or "")

    @pytest.mark.asyncio()
    async def test_phrase_detected(
        self, kw_guardrail: BannedKeywordsGuardrail, context: GuardrailContext
    ) -> None:
        messages = [{"role": "user", "content": "This is a banned phrase here"}]
        result = await kw_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK
        assert "banned phrase" in (result.reason or "")

    @pytest.mark.asyncio()
    async def test_multiple_keywords(
        self, kw_guardrail: BannedKeywordsGuardrail, context: GuardrailContext
    ) -> None:
        messages = [
            {"role": "user", "content": "forbidden and secret_word in one message"}
        ]
        result = await kw_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK
        assert result.details["match_count"] >= 2

    @pytest.mark.asyncio()
    async def test_across_messages(
        self, kw_guardrail: BannedKeywordsGuardrail, context: GuardrailContext
    ) -> None:
        messages = [
            {"role": "system", "content": "normal system prompt"},
            {"role": "user", "content": "this is forbidden"},
        ]
        result = await kw_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK

    @pytest.mark.asyncio()
    async def test_non_string_content_ignored(
        self, kw_guardrail: BannedKeywordsGuardrail, context: GuardrailContext
    ) -> None:
        messages = [{"role": "user", "content": [{"type": "text"}]}]
        result = await kw_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_empty_keywords_list(self, context: GuardrailContext) -> None:
        guardrail = BannedKeywordsGuardrail(keywords=[])
        messages = [{"role": "user", "content": "anything"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_none_keywords(self, context: GuardrailContext) -> None:
        guardrail = BannedKeywordsGuardrail()
        messages = [{"role": "user", "content": "anything"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW


# ===================================================================
# Case Sensitivity Tests
# ===================================================================


class TestCaseSensitivity:
    """Tests for case-sensitive and insensitive matching."""

    @pytest.mark.asyncio()
    async def test_case_insensitive_default(
        self, context: GuardrailContext
    ) -> None:
        guardrail = BannedKeywordsGuardrail(keywords=["BadWord"])
        messages = [{"role": "user", "content": "This has BADWORD in it"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK

    @pytest.mark.asyncio()
    async def test_case_sensitive(self, context: GuardrailContext) -> None:
        guardrail = BannedKeywordsGuardrail(
            keywords=["BadWord"], case_sensitive=True
        )
        # Lowercase should not match
        messages = [{"role": "user", "content": "This has badword in it"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

        # Exact case should match
        messages2 = [{"role": "user", "content": "This has BadWord in it"}]
        result2 = await guardrail.check_request(messages2, context)
        assert result2.action == GuardrailAction.BLOCK


# ===================================================================
# Word Boundary Tests
# ===================================================================


class TestWordBoundary:
    """Tests for word boundary matching."""

    @pytest.mark.asyncio()
    async def test_without_boundary_matches_substring(
        self, context: GuardrailContext
    ) -> None:
        guardrail = BannedKeywordsGuardrail(
            keywords=["ban"], word_boundary=False
        )
        messages = [{"role": "user", "content": "This is banned"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK

    @pytest.mark.asyncio()
    async def test_with_boundary_rejects_substring(
        self, context: GuardrailContext
    ) -> None:
        guardrail = BannedKeywordsGuardrail(
            keywords=["ban"], word_boundary=True
        )
        messages = [{"role": "user", "content": "This is banned"}]
        result = await guardrail.check_request(messages, context)
        # "ban" in "banned" — not a whole word match
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_with_boundary_matches_whole_word(
        self, context: GuardrailContext
    ) -> None:
        guardrail = BannedKeywordsGuardrail(
            keywords=["ban"], word_boundary=True
        )
        messages = [{"role": "user", "content": "I will ban this"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK


# ===================================================================
# Dynamic Keyword Management Tests
# ===================================================================


class TestDynamicKeywords:
    """Tests for add/remove keywords at runtime."""

    @pytest.mark.asyncio()
    async def test_add_keyword(self, context: GuardrailContext) -> None:
        guardrail = BannedKeywordsGuardrail(keywords=["existing"])
        guardrail.add_keyword("new_banned")
        assert "new_banned" in guardrail.keywords

        messages = [{"role": "user", "content": "This has new_banned word"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.BLOCK

    @pytest.mark.asyncio()
    async def test_add_duplicate_keyword(self, context: GuardrailContext) -> None:
        guardrail = BannedKeywordsGuardrail(keywords=["word"])
        guardrail.add_keyword("word")  # duplicate
        assert guardrail.keywords.count("word") == 1

    @pytest.mark.asyncio()
    async def test_remove_keyword(self, context: GuardrailContext) -> None:
        guardrail = BannedKeywordsGuardrail(keywords=["keep", "remove_me"])
        guardrail.remove_keyword("remove_me")
        assert "remove_me" not in guardrail.keywords

        messages = [{"role": "user", "content": "This has remove_me"}]
        result = await guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW


# ===================================================================
# Response Checking Tests
# ===================================================================


class TestResponseChecking:
    """Tests for banned keyword response checking."""

    @pytest.mark.asyncio()
    async def test_disabled_by_default(self, context: GuardrailContext) -> None:
        guardrail = BannedKeywordsGuardrail(keywords=["bad"])
        result = await guardrail.check_response("This is bad", context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_response_blocked(self, context: GuardrailContext) -> None:
        guardrail = BannedKeywordsGuardrail(
            keywords=["bad"], check_response_content=True
        )
        result = await guardrail.check_response("This is bad", context)
        assert result.action == GuardrailAction.BLOCK

    @pytest.mark.asyncio()
    async def test_response_clean(self, context: GuardrailContext) -> None:
        guardrail = BannedKeywordsGuardrail(
            keywords=["bad"], check_response_content=True
        )
        result = await guardrail.check_response("This is fine", context)
        assert result.action == GuardrailAction.ALLOW


# ===================================================================
# BlockedUsersGuardrail Tests
# ===================================================================


class TestBlockedUsers:
    """Tests for user/team blocking."""

    @pytest.mark.asyncio()
    async def test_unblocked_user_allowed(
        self,
        blocked_guardrail: BlockedUsersGuardrail,
        context: GuardrailContext,
    ) -> None:
        """Context without user_id should be allowed."""
        messages = [{"role": "user", "content": "Hello"}]
        result = await blocked_guardrail.check_request(messages, context)
        assert result.action == GuardrailAction.ALLOW

    @pytest.mark.asyncio()
    async def test_blocked_user(
        self,
        blocked_guardrail: BlockedUsersGuardrail,
    ) -> None:
        ctx = GuardrailContext(
            request_id="req-1", model="gpt-4", user_id="blocked-user-1"
        )
        messages = [{"role": "user", "content": "Hello"}]
        result = await blocked_guardrail.check_request(messages, ctx)
        assert result.action == GuardrailAction.BLOCK
        assert "blocked-user-1" in (result.reason or "")

    @pytest.mark.asyncio()
    async def test_blocked_team(
        self,
        blocked_guardrail: BlockedUsersGuardrail,
    ) -> None:
        ctx = GuardrailContext(
            request_id="req-1", model="gpt-4", team_id="blocked-team-1"
        )
        messages = [{"role": "user", "content": "Hello"}]
        result = await blocked_guardrail.check_request(messages, ctx)
        assert result.action == GuardrailAction.BLOCK
        assert "blocked-team-1" in (result.reason or "")

    @pytest.mark.asyncio()
    async def test_allowed_user(
        self,
        blocked_guardrail: BlockedUsersGuardrail,
    ) -> None:
        ctx = GuardrailContext(
            request_id="req-1", model="gpt-4", user_id="good-user"
        )
        messages = [{"role": "user", "content": "Hello"}]
        result = await blocked_guardrail.check_request(messages, ctx)
        assert result.action == GuardrailAction.ALLOW


# ===================================================================
# Block/Unblock API Tests
# ===================================================================


class TestBlockUnblock:
    """Tests for runtime block/unblock operations."""

    def test_block_user(self) -> None:
        g = BlockedUsersGuardrail()
        g.block_user("user-x")
        assert "user-x" in g.blocked_users

    def test_unblock_user(self) -> None:
        g = BlockedUsersGuardrail(blocked_user_ids={"user-x"})
        g.unblock_user("user-x")
        assert "user-x" not in g.blocked_users

    def test_unblock_nonexistent(self) -> None:
        g = BlockedUsersGuardrail()
        g.unblock_user("nobody")  # Should not raise
        assert "nobody" not in g.blocked_users

    def test_block_team(self) -> None:
        g = BlockedUsersGuardrail()
        g.block_team("team-y")
        assert "team-y" in g.blocked_teams

    def test_unblock_team(self) -> None:
        g = BlockedUsersGuardrail(blocked_team_ids={"team-y"})
        g.unblock_team("team-y")
        assert "team-y" not in g.blocked_teams

    def test_is_blocked_user(self) -> None:
        g = BlockedUsersGuardrail(blocked_user_ids={"user-a"})
        assert g.is_blocked(user_id="user-a") is True
        assert g.is_blocked(user_id="user-b") is False

    def test_is_blocked_team(self) -> None:
        g = BlockedUsersGuardrail(blocked_team_ids={"team-a"})
        assert g.is_blocked(team_id="team-a") is True
        assert g.is_blocked(team_id="team-b") is False

    @pytest.mark.asyncio()
    async def test_runtime_block_takes_effect(self) -> None:
        g = BlockedUsersGuardrail(name="blocklist")
        ctx = GuardrailContext(
            request_id="req-1", model="gpt-4", user_id="user-new"
        )
        messages = [{"role": "user", "content": "Hello"}]

        # Initially allowed
        result = await g.check_request(messages, ctx)
        assert result.action == GuardrailAction.ALLOW

        # Block user
        g.block_user("user-new")
        result2 = await g.check_request(messages, ctx)
        assert result2.action == GuardrailAction.BLOCK

        # Unblock
        g.unblock_user("user-new")
        result3 = await g.check_request(messages, ctx)
        assert result3.action == GuardrailAction.ALLOW


# ===================================================================
# Integration with GuardrailManager Tests
# ===================================================================


class TestIntegrationWithManager:
    """Test guardrails within the pipeline."""

    @pytest.mark.asyncio()
    async def test_keyword_block_in_pipeline(
        self, context: GuardrailContext
    ) -> None:
        from routerbot.proxy.guardrails.manager import GuardrailManager

        manager = GuardrailManager()
        manager.register(
            BannedKeywordsGuardrail(
                keywords=["blocked_word"], name="kw", priority=1
            )
        )
        messages = [{"role": "user", "content": "has blocked_word here"}]
        result = await manager.run_request_guardrails(messages, context)
        assert result.blocked

    @pytest.mark.asyncio()
    async def test_blocked_user_in_pipeline(self) -> None:
        from routerbot.proxy.guardrails.manager import GuardrailManager

        ctx = GuardrailContext(
            request_id="req-1", model="gpt-4", user_id="bad-user"
        )
        manager = GuardrailManager()
        manager.register(
            BlockedUsersGuardrail(
                blocked_user_ids={"bad-user"}, name="blocklist", priority=0
            )
        )
        messages = [{"role": "user", "content": "Hello"}]
        result = await manager.run_request_guardrails(messages, ctx)
        assert result.blocked


# ===================================================================
# Properties Tests
# ===================================================================


class TestProperties:
    """Tests for guardrail configuration."""

    def test_kw_name_default(self) -> None:
        g = BannedKeywordsGuardrail()
        assert g.name == "BannedKeywordsGuardrail"

    def test_kw_keywords_property(self) -> None:
        g = BannedKeywordsGuardrail(keywords=["a", "b"])
        assert g.keywords == ["a", "b"]

    def test_blocked_name_default(self) -> None:
        g = BlockedUsersGuardrail()
        assert g.name == "BlockedUsersGuardrail"

    def test_blocked_empty_default(self) -> None:
        g = BlockedUsersGuardrail()
        assert g.blocked_users == set()
        assert g.blocked_teams == set()
