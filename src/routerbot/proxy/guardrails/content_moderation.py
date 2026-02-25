"""Content moderation guardrail.

Evaluates message content for policy violations using pluggable
moderation backends.  Supports:

- **OpenAI Moderation API** — calls ``POST /v1/moderations``
- **Custom HTTP backend** — sends content to a user-defined endpoint
- **Keyword-based** — local pattern matching for categories

The guardrail can operate in ``block`` or ``flag`` mode:

- ``block`` — reject the request if any category exceeds its threshold
- ``flag`` — allow but tag the request with moderation metadata

Configuration::

    guardrails:
      - name: content_moderation
        type: content_moderation
        enabled: true
        backend: "openai"      # or "custom", "keyword"
        mode: "block"          # or "flag"
        priority: 5
        categories:
          hate: 0.8
          sexual: 0.8
          violence: 0.6
          self_harm: 0.5
        check_response: true
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from routerbot.proxy.guardrails.base import (
    BaseGuardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Moderation result types
# ---------------------------------------------------------------------------

# Standard categories aligned with OpenAI's moderation categories
STANDARD_CATEGORIES: list[str] = [
    "hate",
    "hate/threatening",
    "harassment",
    "harassment/threatening",
    "self-harm",
    "self-harm/intent",
    "self-harm/instructions",
    "sexual",
    "sexual/minors",
    "violence",
    "violence/graphic",
]


@dataclass
class ModerationScore:
    """A moderation score for a single category."""

    category: str
    score: float
    flagged: bool


@dataclass
class ModerationResult:
    """Result from a moderation backend check."""

    flagged: bool
    scores: list[ModerationScore] = field(default_factory=list)
    raw_response: dict[str, Any] = field(default_factory=dict)

    @property
    def flagged_categories(self) -> list[str]:
        """Return names of categories that were flagged."""
        return [s.category for s in self.scores if s.flagged]


# ---------------------------------------------------------------------------
# Moderation backend protocol
# ---------------------------------------------------------------------------


class ModerationBackend(ABC):
    """Abstract base class for moderation backends."""

    @abstractmethod
    async def check(self, content: str) -> ModerationResult:
        """Check content against moderation policies."""
        ...


# ---------------------------------------------------------------------------
# OpenAI Moderation Backend
# ---------------------------------------------------------------------------


class OpenAIModerationBackend(ModerationBackend):
    """Uses the OpenAI Moderation API (``POST /v1/moderations``).

    Parameters
    ----------
    api_key:
        OpenAI API key.
    base_url:
        Override the base URL (default: ``https://api.openai.com``).
    model:
        Moderation model (default: ``omni-moderation-latest``).
    """

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str = "https://api.openai.com",
        model: str = "omni-moderation-latest",
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def check(self, content: str) -> ModerationResult:
        """Call OpenAI moderation endpoint."""
        import httpx

        url = f"{self._base_url}/v1/moderations"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        payload = {"input": content, "model": self._model}

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=30.0)
            response.raise_for_status()
            data = response.json()

        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> ModerationResult:
        """Parse OpenAI moderation API response."""
        results = data.get("results", [])
        if not results:
            return ModerationResult(flagged=False, raw_response=data)

        result = results[0]
        categories = result.get("categories", {})
        category_scores = result.get("category_scores", {})
        flagged = result.get("flagged", False)

        scores: list[ModerationScore] = []
        for cat_name in categories:
            scores.append(
                ModerationScore(
                    category=cat_name,
                    score=category_scores.get(cat_name, 0.0),
                    flagged=categories.get(cat_name, False),
                )
            )

        return ModerationResult(
            flagged=flagged,
            scores=scores,
            raw_response=data,
        )


# ---------------------------------------------------------------------------
# Custom HTTP Moderation Backend
# ---------------------------------------------------------------------------


class CustomHTTPModerationBackend(ModerationBackend):
    """Sends content to a user-defined HTTP endpoint.

    The endpoint should return JSON with at minimum::

        {
            "flagged": bool,
            "categories": {"category_name": {"score": float, "flagged": bool}}
        }

    Parameters
    ----------
    endpoint:
        URL to send moderation requests to.
    headers:
        Additional HTTP headers.
    timeout:
        Request timeout in seconds.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._endpoint = endpoint
        self._headers = headers or {}
        self._timeout = timeout

    async def check(self, content: str) -> ModerationResult:
        """Call custom moderation endpoint."""
        import httpx

        payload = {"content": content}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._endpoint,
                json=payload,
                headers=self._headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()

        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> ModerationResult:
        """Parse custom endpoint response."""
        flagged = data.get("flagged", False)
        categories = data.get("categories", {})

        scores: list[ModerationScore] = []
        for cat_name, cat_data in categories.items():
            if isinstance(cat_data, dict):
                scores.append(
                    ModerationScore(
                        category=cat_name,
                        score=cat_data.get("score", 0.0),
                        flagged=cat_data.get("flagged", False),
                    )
                )
            elif isinstance(cat_data, (int, float)):
                scores.append(
                    ModerationScore(
                        category=cat_name,
                        score=float(cat_data),
                        flagged=flagged,
                    )
                )

        return ModerationResult(
            flagged=flagged,
            scores=scores,
            raw_response=data,
        )


# ---------------------------------------------------------------------------
# Keyword-based Moderation Backend
# ---------------------------------------------------------------------------


class KeywordModerationBackend(ModerationBackend):
    """Simple keyword-based moderation using pattern matching.

    Useful for basic content filtering without external API dependencies.

    Parameters
    ----------
    category_keywords:
        Mapping of category name to list of keywords/phrases.
    case_sensitive:
        Whether keyword matching is case-sensitive.
    """

    def __init__(
        self,
        *,
        category_keywords: dict[str, list[str]] | None = None,
        case_sensitive: bool = False,
    ) -> None:
        self._case_sensitive = case_sensitive
        self._category_keywords: dict[str, list[str]] = {}

        if category_keywords:
            for cat, keywords in category_keywords.items():
                if case_sensitive:
                    self._category_keywords[cat] = keywords
                else:
                    self._category_keywords[cat] = [kw.lower() for kw in keywords]

    async def check(self, content: str) -> ModerationResult:
        """Check content against keyword lists."""
        check_content = content if self._case_sensitive else content.lower()

        scores: list[ModerationScore] = []
        any_flagged = False

        for category, keywords in self._category_keywords.items():
            found = any(kw in check_content for kw in keywords)
            if found:
                any_flagged = True
            scores.append(
                ModerationScore(
                    category=category,
                    score=1.0 if found else 0.0,
                    flagged=found,
                )
            )

        return ModerationResult(
            flagged=any_flagged,
            scores=scores,
        )


# ---------------------------------------------------------------------------
# Content Moderation Guardrail
# ---------------------------------------------------------------------------


class ContentModerationGuardrail(BaseGuardrail):
    """Guardrail that moderates content using configurable backends.

    Parameters
    ----------
    backend:
        A :class:`ModerationBackend` instance.
    mode:
        ``"block"`` — reject flagged content.
        ``"flag"`` — allow but include moderation metadata.
    thresholds:
        Per-category score thresholds.  Only categories exceeding their
        threshold are considered flagged.  If ``None``, uses the backend's
        native flagging.
    check_response_content:
        Also moderate model responses.
    kwargs:
        Passed to :class:`BaseGuardrail` (name, enabled, priority).
    """

    def __init__(
        self,
        *,
        backend: ModerationBackend,
        mode: str = "block",
        thresholds: dict[str, float] | None = None,
        check_response_content: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._backend = backend
        self._mode = mode
        self._thresholds = thresholds or {}
        self._check_response = check_response_content

    @property
    def mode(self) -> str:
        """Return the current operating mode."""
        return self._mode

    @property
    def backend(self) -> ModerationBackend:
        """Return the moderation backend."""
        return self._backend

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_thresholds(self, result: ModerationResult) -> ModerationResult:
        """Re-evaluate flagging based on custom thresholds.

        If thresholds are configured, override the backend's native flags
        on a per-category basis.
        """
        if not self._thresholds:
            return result

        any_flagged = False
        new_scores: list[ModerationScore] = []

        for score in result.scores:
            threshold = self._thresholds.get(score.category)
            flagged = score.score >= threshold if threshold is not None else score.flagged

            if flagged:
                any_flagged = True

            new_scores.append(
                ModerationScore(
                    category=score.category,
                    score=score.score,
                    flagged=flagged,
                )
            )

        return ModerationResult(
            flagged=any_flagged,
            scores=new_scores,
            raw_response=result.raw_response,
        )

    def _build_result(
        self,
        mod_result: ModerationResult,
        *,
        context_label: str = "message",
    ) -> GuardrailResult:
        """Convert a moderation result to a guardrail result."""
        if not mod_result.flagged:
            return GuardrailResult(
                action=GuardrailAction.ALLOW,
                guardrail_name=self.name,
            )

        flagged_cats = mod_result.flagged_categories

        if self._mode == "block":
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason=f"Content moderation violated in {context_label}: {', '.join(flagged_cats)}",
                guardrail_name=self.name,
                details={
                    "flagged_categories": flagged_cats,
                    "scores": {s.category: s.score for s in mod_result.scores if s.flagged},
                },
            )

        # Flag mode — allow but include metadata
        return GuardrailResult(
            action=GuardrailAction.ALLOW,
            reason=f"Content flagged (allowed): {', '.join(flagged_cats)}",
            guardrail_name=self.name,
            details={
                "moderation_flagged": True,
                "flagged_categories": flagged_cats,
                "scores": {s.category: s.score for s in mod_result.scores},
            },
        )

    # ------------------------------------------------------------------
    # Request check
    # ------------------------------------------------------------------

    async def check_request(
        self,
        messages: list[dict[str, Any]],
        context: GuardrailContext,
    ) -> GuardrailResult:
        """Moderate all user message content."""
        # Combine all user/system message text for moderation
        text_parts: list[str] = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                text_parts.append(content)

        if not text_parts:
            return GuardrailResult(
                action=GuardrailAction.ALLOW,
                guardrail_name=self.name,
            )

        combined_text = "\n".join(text_parts)

        try:
            mod_result = await self._backend.check(combined_text)
        except Exception:
            logger.exception("Content moderation backend error")
            # On backend failure, allow the request (fail-open)
            return GuardrailResult(
                action=GuardrailAction.ALLOW,
                reason="Moderation backend error — request allowed",
                guardrail_name=self.name,
                details={"error": True},
            )

        mod_result = self._apply_thresholds(mod_result)
        return self._build_result(mod_result, context_label="request")

    # ------------------------------------------------------------------
    # Response check
    # ------------------------------------------------------------------

    async def check_response(
        self,
        response: str,
        context: GuardrailContext,
    ) -> GuardrailResult:
        """Optionally moderate model responses."""
        if not self._check_response:
            return GuardrailResult(
                action=GuardrailAction.ALLOW,
                guardrail_name=self.name,
            )

        if not response:
            return GuardrailResult(
                action=GuardrailAction.ALLOW,
                guardrail_name=self.name,
            )

        try:
            mod_result = await self._backend.check(response)
        except Exception:
            logger.exception("Content moderation backend error (response)")
            return GuardrailResult(
                action=GuardrailAction.ALLOW,
                reason="Moderation backend error — response allowed",
                guardrail_name=self.name,
                details={"error": True},
            )

        mod_result = self._apply_thresholds(mod_result)
        return self._build_result(mod_result, context_label="response")


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def create_openai_moderation_backend(
    *,
    api_key: str = "",
    base_url: str = "https://api.openai.com",
    model: str = "omni-moderation-latest",
) -> OpenAIModerationBackend:
    """Create an OpenAI moderation backend."""
    return OpenAIModerationBackend(api_key=api_key, base_url=base_url, model=model)


def create_keyword_moderation_backend(
    *,
    category_keywords: dict[str, list[str]],
    case_sensitive: bool = False,
) -> KeywordModerationBackend:
    """Create a keyword-based moderation backend."""
    return KeywordModerationBackend(
        category_keywords=category_keywords,
        case_sensitive=case_sensitive,
    )


def create_custom_moderation_backend(
    *,
    endpoint: str,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> CustomHTTPModerationBackend:
    """Create a custom HTTP moderation backend."""
    return CustomHTTPModerationBackend(
        endpoint=endpoint,
        headers=headers,
        timeout=timeout,
    )
