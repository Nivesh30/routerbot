"""Prompt injection transform.

Injects system-prompt templates into completion requests based on
team, key, and model scope filters.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from routerbot.core.transform.pipeline import TransformHook

if TYPE_CHECKING:
    from routerbot.core.transform.models import (
        PromptTemplate,
        TransformContext,
        TransformResult,
        TransformStage,
    )

logger = logging.getLogger(__name__)


class PromptInjector(TransformHook):
    """Injects configured system-prompt templates into requests.

    For each :class:`PromptTemplate` that matches the current context
    (team, key, model), the template's ``content`` is added to the
    messages list according to its ``position``:

    * **prepend** — insert a ``system`` message at the start
    * **append** — insert a ``system`` message after existing system messages
    * **replace** — overwrite the existing system message(s)
    """

    def __init__(self, templates: list[PromptTemplate]) -> None:
        # Sort by priority descending (highest first)
        self._templates = sorted(templates, key=lambda t: -t.priority)

    @property
    def name(self) -> str:
        return "prompt_injector"

    @property
    def stage(self) -> TransformStage:
        from routerbot.core.transform.models import TransformStage

        return TransformStage.PRE_REQUEST

    @property
    def templates(self) -> list[PromptTemplate]:
        return list(self._templates)

    # ── Core logic ──────────────────────────────────────────────────

    async def apply(
        self,
        data: dict[str, Any],
        context: TransformContext,
    ) -> TransformResult:
        from routerbot.core.transform.models import TransformResult

        messages: list[dict[str, Any]] = data.get("messages", [])
        if not messages:
            return TransformResult(modified=False)

        modified = False
        applied: list[str] = []

        for template in self._templates:
            if not self._matches(template, context):
                continue

            if template.position == "prepend":
                messages.insert(0, {"role": "system", "content": template.content})
                modified = True
                applied.append(template.name)

            elif template.position == "append":
                # Insert after the last system message (or at start if none)
                idx = self._last_system_index(messages) + 1
                messages.insert(idx, {"role": "system", "content": template.content})
                modified = True
                applied.append(template.name)

            elif template.position == "replace":
                # Remove all existing system messages, prepend this one
                data["messages"] = [m for m in messages if m.get("role") != "system"]
                data["messages"].insert(0, {"role": "system", "content": template.content})
                messages = data["messages"]
                modified = True
                applied.append(template.name)

        if modified:
            data["messages"] = messages

        return TransformResult(
            modified=modified,
            metadata={"applied_templates": applied} if applied else {},
        )

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _matches(template: PromptTemplate, context: TransformContext) -> bool:
        """Check whether *template* should apply in the given *context*."""
        if not template.enabled:
            return False

        # If scope lists are non-empty, the context must match at least one
        if template.team_ids and (context.team_id not in template.team_ids):
            return False
        if template.key_ids and (context.key_id not in template.key_ids):
            return False
        return not (template.models and (context.model not in template.models))

    @staticmethod
    def _last_system_index(messages: list[dict[str, Any]]) -> int:
        """Return the index of the last ``system`` message, or -1."""
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "system":
                return i
        return -1
