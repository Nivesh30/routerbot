"""Banned keywords guardrail.

Blocks requests containing any of a configured set of keywords or phrases.
Supports case-insensitive matching, word-boundary matching, and regex patterns.

Configuration::

    guardrails:
      - name: banned_keywords
        type: banned_keywords
        enabled: true
        mode: "block"
        priority: 2
        keywords: ["forbidden_word", "bad_phrase"]
        case_sensitive: false
        word_boundary: false
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from routerbot.proxy.guardrails.base import (
    BaseGuardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Match result
# ---------------------------------------------------------------------------


@dataclass
class KeywordMatch:
    """A single keyword match in content."""

    keyword: str
    matched_text: str
    start: int
    end: int


# ---------------------------------------------------------------------------
# Banned Keywords Guardrail
# ---------------------------------------------------------------------------


class BannedKeywordsGuardrail(BaseGuardrail):
    """Guardrail that blocks requests containing banned keywords.

    Parameters
    ----------
    keywords:
        List of keywords or phrases to block.
    case_sensitive:
        Whether matching is case-sensitive.
    word_boundary:
        Whether to match whole words only (uses ``\\b`` regex boundaries).
    check_response_content:
        Also check model responses for banned keywords.
    kwargs:
        Passed to :class:`BaseGuardrail` (name, enabled, priority).
    """

    def __init__(
        self,
        *,
        keywords: list[str] | None = None,
        case_sensitive: bool = False,
        word_boundary: bool = False,
        check_response_content: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._keywords = list(keywords) if keywords else []
        self._case_sensitive = case_sensitive
        self._word_boundary = word_boundary
        self._check_response = check_response_content
        self._patterns: list[tuple[str, re.Pattern[str]]] = []
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile keyword patterns for efficient matching."""
        flags = 0 if self._case_sensitive else re.IGNORECASE
        for kw in self._keywords:
            escaped = re.escape(kw)
            pattern_str = rf"\b{escaped}\b" if self._word_boundary else escaped
            self._patterns.append((kw, re.compile(pattern_str, flags)))

    @property
    def keywords(self) -> list[str]:
        """Return the current keyword list."""
        return list(self._keywords)

    def add_keyword(self, keyword: str) -> None:
        """Add a keyword at runtime."""
        if keyword not in self._keywords:
            self._keywords.append(keyword)
            flags = 0 if self._case_sensitive else re.IGNORECASE
            escaped = re.escape(keyword)
            pattern_str = rf"\b{escaped}\b" if self._word_boundary else escaped
            self._patterns.append((keyword, re.compile(pattern_str, flags)))

    def remove_keyword(self, keyword: str) -> None:
        """Remove a keyword at runtime."""
        self._keywords = [k for k in self._keywords if k != keyword]
        self._patterns = [(k, p) for k, p in self._patterns if k != keyword]

    def _scan(self, text: str) -> list[KeywordMatch]:
        """Scan text for banned keywords."""
        matches: list[KeywordMatch] = []
        for keyword, pattern in self._patterns:
            for m in pattern.finditer(text):
                matches.append(
                    KeywordMatch(
                        keyword=keyword,
                        matched_text=m.group(),
                        start=m.start(),
                        end=m.end(),
                    )
                )
        return matches

    # ------------------------------------------------------------------
    # Request check
    # ------------------------------------------------------------------

    async def check_request(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> GuardrailResult:
        """Check all message content for banned keywords."""
        all_matches: list[KeywordMatch] = []

        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str) or not content:
                continue
            matches = self._scan(content)
            if matches:
                all_matches.extend(matches)

        if all_matches:
            found_keywords = sorted({m.keyword for m in all_matches})
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason=f"Banned keyword(s) detected: {', '.join(found_keywords)}",
                guardrail_name=self.name,
                details={
                    "matched_keywords": found_keywords,
                    "match_count": len(all_matches),
                },
            )

        return GuardrailResult(
            action=GuardrailAction.ALLOW,
            guardrail_name=self.name,
        )

    # ------------------------------------------------------------------
    # Response check
    # ------------------------------------------------------------------

    async def check_response(
        self,
        response: str,
        context: GuardrailContext,
    ) -> GuardrailResult:
        """Optionally check model responses for banned keywords."""
        if not self._check_response:
            return GuardrailResult(
                action=GuardrailAction.ALLOW,
                guardrail_name=self.name,
            )

        matches = self._scan(response)
        if matches:
            found_keywords = sorted({m.keyword for m in matches})
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason=f"Banned keyword(s) in response: {', '.join(found_keywords)}",
                guardrail_name=self.name,
                details={
                    "matched_keywords": found_keywords,
                    "match_count": len(matches),
                },
            )

        return GuardrailResult(
            action=GuardrailAction.ALLOW,
            guardrail_name=self.name,
        )


# ---------------------------------------------------------------------------
# Blocked Users Guardrail
# ---------------------------------------------------------------------------


class BlockedUsersGuardrail(BaseGuardrail):
    """Guardrail that blocks requests from specific user IDs.

    Parameters
    ----------
    blocked_user_ids:
        Initial set of blocked user IDs.
    blocked_team_ids:
        Initial set of blocked team IDs.
    kwargs:
        Passed to :class:`BaseGuardrail` (name, enabled, priority).
    """

    def __init__(
        self,
        *,
        blocked_user_ids: set[str] | None = None,
        blocked_team_ids: set[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._blocked_users: set[str] = set(blocked_user_ids) if blocked_user_ids else set()
        self._blocked_teams: set[str] = set(blocked_team_ids) if blocked_team_ids else set()

    @property
    def blocked_users(self) -> set[str]:
        """Return current blocked user IDs."""
        return set(self._blocked_users)

    @property
    def blocked_teams(self) -> set[str]:
        """Return current blocked team IDs."""
        return set(self._blocked_teams)

    def block_user(self, user_id: str) -> None:
        """Block a user."""
        self._blocked_users.add(user_id)

    def unblock_user(self, user_id: str) -> None:
        """Unblock a user."""
        self._blocked_users.discard(user_id)

    def block_team(self, team_id: str) -> None:
        """Block a team."""
        self._blocked_teams.add(team_id)

    def unblock_team(self, team_id: str) -> None:
        """Unblock a team."""
        self._blocked_teams.discard(team_id)

    def is_blocked(self, *, user_id: str | None = None, team_id: str | None = None) -> bool:
        """Check whether a user or team is blocked."""
        if user_id and user_id in self._blocked_users:
            return True
        return bool(team_id and team_id in self._blocked_teams)

    # ------------------------------------------------------------------
    # Request check
    # ------------------------------------------------------------------

    async def check_request(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> GuardrailResult:
        """Block requests from blocked users or teams."""
        blocked_reason_parts: list[str] = []

        if context.user_id and context.user_id in self._blocked_users:
            blocked_reason_parts.append(f"User '{context.user_id}' is blocked")

        if context.team_id and context.team_id in self._blocked_teams:
            blocked_reason_parts.append(f"Team '{context.team_id}' is blocked")

        if blocked_reason_parts:
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason="; ".join(blocked_reason_parts),
                guardrail_name=self.name,
                details={
                    "blocked_user": context.user_id in self._blocked_users if context.user_id else False,
                    "blocked_team": context.team_id in self._blocked_teams if context.team_id else False,
                },
            )

        return GuardrailResult(
            action=GuardrailAction.ALLOW,
            guardrail_name=self.name,
        )
