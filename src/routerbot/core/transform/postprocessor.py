"""Response post-processing transform.

Applies post-processing rules to model responses before they are
returned to the caller.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from routerbot.core.transform.pipeline import TransformHook

if TYPE_CHECKING:
    from routerbot.core.transform.models import (
        PostProcessingRule,
        TransformContext,
        TransformResult,
        TransformStage,
    )

logger = logging.getLogger(__name__)


class ResponsePostProcessor(TransformHook):
    """Applies post-processing rules to completion responses.

    Supported actions:

    * **strip_thinking** — remove ``<thinking>…</thinking>`` blocks
    * **regex_replace**  — apply a regex substitution
    * **truncate**       — limit output to *max_chars* characters
    * **add_metadata**   — attach extra key-value pairs to the response
    """

    def __init__(self, rules: list[PostProcessingRule]) -> None:
        self._rules = [r for r in rules if r.enabled]

    @property
    def name(self) -> str:
        return "response_postprocessor"

    @property
    def stage(self) -> TransformStage:
        from routerbot.core.transform.models import TransformStage

        return TransformStage.POST_RESPONSE

    @property
    def rules(self) -> list[PostProcessingRule]:
        return list(self._rules)

    # ── Core logic ──────────────────────────────────────────────────

    async def apply(
        self,
        data: dict[str, Any],
        context: TransformContext,
    ) -> TransformResult:
        from routerbot.core.transform.models import TransformResult

        modified = False
        applied: list[str] = []

        for rule in self._rules:
            if not self._matches(rule, context):
                continue

            changed = self._apply_rule(rule, data)
            if changed:
                modified = True
                applied.append(rule.name)

        return TransformResult(
            modified=modified,
            metadata={"applied_rules": applied} if applied else {},
        )

    # ── Rule dispatch ───────────────────────────────────────────────

    def _apply_rule(self, rule: PostProcessingRule, data: dict[str, Any]) -> bool:
        """Apply a single rule. Returns True if data was modified."""
        if rule.action == "strip_thinking":
            return self._strip_thinking(data)
        if rule.action == "regex_replace":
            return self._regex_replace(data, rule.pattern, rule.replacement)
        if rule.action == "truncate":
            return self._truncate(data, rule.max_chars)
        if rule.action == "add_metadata":
            return self._add_metadata(data, rule.metadata_pairs)

        logger.warning("Unknown post-processing action: %s", rule.action)
        return False

    # ── Concrete actions ────────────────────────────────────────────

    @staticmethod
    def _strip_thinking(data: dict[str, Any]) -> bool:
        """Remove ``<thinking>…</thinking>`` blocks from all choice contents."""
        choices = data.get("choices", [])
        modified = False
        thinking_re = re.compile(r"<thinking>.*?</thinking>", re.DOTALL)

        for choice in choices:
            msg = choice.get("message", {})
            content = msg.get("content")
            if content and thinking_re.search(content):
                msg["content"] = thinking_re.sub("", content).strip()
                modified = True

        return modified

    @staticmethod
    def _regex_replace(
        data: dict[str, Any],
        pattern: str | None,
        replacement: str | None,
    ) -> bool:
        """Apply regex substitution to all choice contents."""
        if not pattern:
            return False
        replacement = replacement or ""

        choices = data.get("choices", [])
        modified = False
        compiled = re.compile(pattern, re.DOTALL)

        for choice in choices:
            msg = choice.get("message", {})
            content = msg.get("content")
            if content:
                new_content = compiled.sub(replacement, content)
                if new_content != content:
                    msg["content"] = new_content
                    modified = True

        return modified

    @staticmethod
    def _truncate(data: dict[str, Any], max_chars: int | None) -> bool:
        """Truncate choice contents to *max_chars*."""
        if not max_chars or max_chars <= 0:
            return False

        choices = data.get("choices", [])
        modified = False

        for choice in choices:
            msg = choice.get("message", {})
            content = msg.get("content")
            if content and len(content) > max_chars:
                msg["content"] = content[:max_chars]
                modified = True

        return modified

    @staticmethod
    def _add_metadata(data: dict[str, Any], pairs: dict[str, str]) -> bool:
        """Add metadata key-value pairs to the response."""
        if not pairs:
            return False

        if "metadata" not in data:
            data["metadata"] = {}
        data["metadata"].update(pairs)
        return True

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _matches(rule: PostProcessingRule, context: TransformContext) -> bool:
        """Check if rule should apply for the current context."""
        if rule.team_ids and (context.team_id not in rule.team_ids):
            return False
        return not (rule.models and (context.model not in rule.models))
