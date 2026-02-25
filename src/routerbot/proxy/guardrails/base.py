"""Base classes for the guardrail system.

Every guardrail inherits from :class:`BaseGuardrail` and implements
at least :meth:`check_request`.  The optional :meth:`check_response`
defaults to :data:`GuardrailAction.ALLOW`.

Guardrail results communicate one of three actions:

- **ALLOW** — let the request / response through unchanged.
- **BLOCK** — reject with a descriptive reason.
- **MODIFY** — transform the content (e.g. redact PII) before
  forwarding.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GuardrailAction(enum.StrEnum):
    """Action the guardrail instructs the pipeline to take."""

    ALLOW = "allow"
    BLOCK = "block"
    MODIFY = "modify"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class GuardrailResult:
    """Outcome of a single guardrail check.

    Attributes
    ----------
    action:
        ``ALLOW``, ``BLOCK``, or ``MODIFY``.
    modified_content:
        When *action* is ``MODIFY``, holds the transformed content.
        ``None`` for ``ALLOW`` and ``BLOCK``.
    reason:
        Human-readable explanation (used in error responses for
        ``BLOCK`` or audit logs).
    guardrail_name:
        Name of the guardrail that produced this result.
    details:
        Arbitrary extra data (e.g. list of detected entities).
    """

    action: GuardrailAction
    modified_content: str | None = None
    reason: str | None = None
    guardrail_name: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Context passed to guardrails
# ---------------------------------------------------------------------------


@dataclass
class GuardrailContext:
    """Contextual information available to guardrails during a check.

    Populated by the proxy layer before the guardrail pipeline runs.
    """

    request_id: str = ""
    user_id: str | None = None
    team_id: str | None = None
    key_id: str | None = None
    model: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract base guardrail
# ---------------------------------------------------------------------------


class BaseGuardrail(ABC):
    """Base class for all guardrails.

    Subclasses must implement :meth:`check_request`.  Override
    :meth:`check_response` to also guard model output.

    Parameters
    ----------
    name:
        Display / config name for this guardrail.
    enabled:
        Whether this guardrail is active.
    priority:
        Execution order — lower values run first.
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        enabled: bool = True,
        priority: int = 100,
    ) -> None:
        self._name = name or self.__class__.__name__
        self.enabled = enabled
        self.priority = priority

    @property
    def name(self) -> str:
        """Return the guardrail's display name."""
        return self._name

    @abstractmethod
    async def check_request(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> GuardrailResult:
        """Inspect (and optionally modify) the request messages.

        Parameters
        ----------
        messages:
            The conversation messages as plain dictionaries.
        context:
            Request metadata (user, team, model, etc.).

        Returns
        -------
        GuardrailResult
            ``ALLOW``, ``BLOCK``, or ``MODIFY`` with transformed content.
        """

    async def check_response(
        self,
        response: str,
        context: GuardrailContext,
    ) -> GuardrailResult:
        """Inspect (and optionally modify) the model's response.

        The default implementation allows all responses.
        """
        return GuardrailResult(action=GuardrailAction.ALLOW, guardrail_name=self.name)
