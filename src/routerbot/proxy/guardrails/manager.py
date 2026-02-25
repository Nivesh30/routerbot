"""Guardrail pipeline manager.

Orchestrates execution of guardrails in priority order for both
pre-request and post-response checks.

Pipeline semantics:

1. Guardrails execute in ascending **priority** order (lower = first).
2. On the first ``BLOCK`` result the pipeline short-circuits and
   returns that result immediately — no further guardrails run.
3. ``MODIFY`` results are applied cumulatively — each subsequent
   guardrail sees the already-modified content.
4. ``ALLOW`` simply lets the content pass to the next guardrail.
5. A guardrail raising an exception is caught, logged, and treated as
   ``ALLOW`` so that one broken guardrail never blocks all traffic.

Configuration supports per-key and per-team overrides so that teams
can opt-in to stricter (or relaxed) guardrail policies.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from routerbot.proxy.guardrails.base import (
    BaseGuardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------


class GuardrailPipelineResult:
    """Aggregated result of running the full guardrail pipeline.

    Attributes
    ----------
    action:
        Final action (``ALLOW``, ``BLOCK``, or ``MODIFY``) aggregated
        across all guardrails.
    modified_messages:
        The (possibly modified) messages after all guardrails ran.
        ``None`` when the action is ``BLOCK``.
    blocking_result:
        The :class:`GuardrailResult` that triggered a ``BLOCK``
        (if any).
    results:
        Ordered list of every individual guardrail result.
    """

    def __init__(self) -> None:
        self.action: GuardrailAction = GuardrailAction.ALLOW
        self.modified_messages: list[dict[str, Any]] | None = None
        self.blocking_result: GuardrailResult | None = None
        self.results: list[GuardrailResult] = []

    @property
    def blocked(self) -> bool:
        """``True`` when the pipeline short-circuited on a BLOCK."""
        return self.action == GuardrailAction.BLOCK

    @property
    def modified(self) -> bool:
        """``True`` when at least one guardrail modified content."""
        return self.action == GuardrailAction.MODIFY


# ---------------------------------------------------------------------------
# GuardrailManager
# ---------------------------------------------------------------------------


class GuardrailManager:
    """Manages registration and ordered execution of guardrails.

    Usage::

        manager = GuardrailManager()
        manager.register(SecretDetectionGuardrail(...))
        manager.register(PIIDetectionGuardrail(...))

        result = await manager.run_request_guardrails(messages, context)
        if result.blocked:
            return error_response(result.blocking_result.reason)
    """

    def __init__(self) -> None:
        self._guardrails: list[BaseGuardrail] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, guardrail: BaseGuardrail) -> None:
        """Add a guardrail and maintain priority sort order."""
        self._guardrails.append(guardrail)
        self._guardrails.sort(key=lambda g: g.priority)
        logger.info("Registered guardrail '%s' (priority=%d)", guardrail.name, guardrail.priority)

    def unregister(self, name: str) -> bool:
        """Remove a guardrail by name. Returns ``True`` if found."""
        before = len(self._guardrails)
        self._guardrails = [g for g in self._guardrails if g.name != name]
        removed = len(self._guardrails) < before
        if removed:
            logger.info("Unregistered guardrail '%s'", name)
        return removed

    @property
    def registered(self) -> list[str]:
        """Names of currently registered guardrails (in priority order)."""
        return [g.name for g in self._guardrails]

    # ------------------------------------------------------------------
    # Request guardrails
    # ------------------------------------------------------------------

    async def run_request_guardrails(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
        *,
        disabled: set[str] | None = None,
    ) -> GuardrailPipelineResult:
        """Run pre-request guardrails on *messages*.

        Parameters
        ----------
        messages:
            Conversation messages (plain dicts).
        context:
            Request metadata.
        disabled:
            Set of guardrail names to skip for this request.

        Returns
        -------
        GuardrailPipelineResult
        """
        pipeline_result = GuardrailPipelineResult()
        current_messages = messages  # may be mutated by MODIFY actions
        had_modification = False

        for guardrail in self._guardrails:
            if not guardrail.enabled:
                continue
            if disabled and guardrail.name in disabled:
                continue

            try:
                result = await guardrail.check_request(current_messages, context)
                result.guardrail_name = guardrail.name
            except Exception:
                logger.exception(
                    "Guardrail '%s' raised an exception during request check; treating as ALLOW",
                    guardrail.name,
                )
                result = GuardrailResult(
                    action=GuardrailAction.ALLOW,
                    guardrail_name=guardrail.name,
                    reason="Guardrail error (treated as allow)",
                )

            pipeline_result.results.append(result)

            if result.action == GuardrailAction.BLOCK:
                pipeline_result.action = GuardrailAction.BLOCK
                pipeline_result.blocking_result = result
                logger.warning(
                    "Guardrail '%s' BLOCKED request %s: %s",
                    guardrail.name,
                    context.request_id,
                    result.reason,
                )
                return pipeline_result

            if result.action == GuardrailAction.MODIFY and result.modified_content is not None:
                had_modification = True
                current_messages = _apply_modification(current_messages, result.modified_content)
                logger.info(
                    "Guardrail '%s' MODIFIED request %s",
                    guardrail.name,
                    context.request_id,
                )

        if had_modification:
            pipeline_result.action = GuardrailAction.MODIFY
        pipeline_result.modified_messages = current_messages
        return pipeline_result

    # ------------------------------------------------------------------
    # Response guardrails
    # ------------------------------------------------------------------

    async def run_response_guardrails(
        self,
        response: str,
        context: GuardrailContext,
        *,
        disabled: set[str] | None = None,
    ) -> GuardrailPipelineResult:
        """Run post-response guardrails on *response*.

        Parameters
        ----------
        response:
            The model's response text.
        context:
            Request metadata.
        disabled:
            Set of guardrail names to skip for this request.

        Returns
        -------
        GuardrailPipelineResult
        """
        pipeline_result = GuardrailPipelineResult()
        current_response = response
        had_modification = False

        for guardrail in self._guardrails:
            if not guardrail.enabled:
                continue
            if disabled and guardrail.name in disabled:
                continue

            try:
                result = await guardrail.check_response(current_response, context)
                result.guardrail_name = guardrail.name
            except Exception:
                logger.exception(
                    "Guardrail '%s' raised an exception during response check; treating as ALLOW",
                    guardrail.name,
                )
                result = GuardrailResult(
                    action=GuardrailAction.ALLOW,
                    guardrail_name=guardrail.name,
                    reason="Guardrail error (treated as allow)",
                )

            pipeline_result.results.append(result)

            if result.action == GuardrailAction.BLOCK:
                pipeline_result.action = GuardrailAction.BLOCK
                pipeline_result.blocking_result = result
                logger.warning(
                    "Guardrail '%s' BLOCKED response for request %s: %s",
                    guardrail.name,
                    context.request_id,
                    result.reason,
                )
                return pipeline_result

            if result.action == GuardrailAction.MODIFY and result.modified_content is not None:
                had_modification = True
                current_response = result.modified_content
                logger.info(
                    "Guardrail '%s' MODIFIED response for request %s",
                    guardrail.name,
                    context.request_id,
                )

        if had_modification:
            pipeline_result.action = GuardrailAction.MODIFY
        # Store modified response as a single-message list for consistency
        pipeline_result.modified_messages = [{"role": "assistant", "content": current_response}]
        return pipeline_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_modification(
    messages: list[dict[str, Any]],
    modified_content: str,
) -> list[dict[str, Any]]:
    """Apply a MODIFY result to the message list.

    The *modified_content* is expected to be a JSON-encoded list of
    messages.  If parsing fails, we fall back to replacing the content
    of the last user message.
    """
    try:
        parsed = json.loads(modified_content)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: replace last user message content
    updated: list[dict[str, Any]] = []
    replaced = False
    for msg in reversed(messages):
        if not replaced and msg.get("role") == "user":
            updated.append({**msg, "content": modified_content})
            replaced = True
        else:
            updated.append(msg)
    updated.reverse()

    if not replaced:
        # No user message found — append the modified content
        return [*messages]

    return updated
