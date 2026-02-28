"""Intent classifier and semantic router.

Classifies user prompts into intent categories and resolves them
to specific models via the configured routing rules.
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from routerbot.core.semantic.models import (
        ABTestConfig,
        PatternRule,
        SemanticRoutingConfig,
    )

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Intent classifier
# ═══════════════════════════════════════════════════════════════════════════


class IntentClassifier:
    """Classify user messages into intent categories.

    Supports two modes:
    1. **Local keyword-based** classification (fast, no external calls)
    2. **LLM-based** classification (slower, more accurate)

    The local classifier always runs first as a fast path. If a local
    pattern or keyword matches with high confidence, the LLM is skipped.
    """

    # Built-in keyword → intent mappings for local classification
    KEYWORD_MAP: ClassVar[dict[str, list[str]]] = {
        "code_generation": [
            r"\b(write|create|implement|build|generate|code)\b.*(function|class|module|script|program|api|endpoint)",
            r"\b(python|javascript|typescript|rust|go|java|c\+\+|sql|html|css)\b.*\b(code|script|program|function)\b",
            r"```",
        ],
        "code_review": [
            r"\b(review|analyse|analyze|check|audit|improve)\b.*\b(code|function|class|method|implementation)\b",
            r"\b(refactor|optimise|optimize|clean up)\b",
            r"\b(bug|issue|error|fix)\b.*\b(in|with|this)\b.*\bcode\b",
        ],
        "complex_reasoning": [
            r"\b(explain|why|how does|what causes|reason|analyse|analyze|evaluate)\b.*\b(work|happen|cause|mean|imply)\b",
            r"\b(compare|contrast|pros and cons|trade-?offs?|advantages|disadvantages)\b",
            r"\b(step by step|chain of thought|think through|reasoning)\b",
        ],
        "creative_writing": [
            r"\b(write|compose|draft|create)\b.*\b(story|poem|essay|article|blog|letter|email|narrative|fiction)\b",
            r"\b(creative|imaginative|engaging|compelling)\b",
        ],
        "translation": [
            r"\b(translate|translation|translated)\b",
            r"\b(from|to)\b\s+\b(english|spanish|french|german|chinese|japanese|korean|arabic|hindi|portuguese)\b",
        ],
        "summarisation": [
            r"\b(summarise|summarize|summary|tldr|tl;dr|brief|condense|shorten)\b",
            r"\b(key points|main ideas|highlights|overview|gist)\b",
        ],
        "math": [
            r"\b(calculate|compute|solve|equation|integral|derivative|proof|mathematical)\b",
            r"\b(algebra|calculus|statistics|probability|geometry|trigonometry)\b",
            r"[0-9]+\s*[\+\-\*\/\^]\s*[0-9]+",
        ],
        "vision": [
            r"\b(image|picture|photo|screenshot|diagram|chart|graph)\b",
            r"\b(describe|what'?s? in|look at|see|show)\b.*\b(image|picture|photo)\b",
        ],
        "simple_qa": [
            r"^(what|who|when|where|which|how many|how much|is|are|was|were|do|does|did|can|will)\b.{5,80}\??$",
            r"\b(define|definition|meaning of)\b",
        ],
    }

    def __init__(self, config: SemanticRoutingConfig) -> None:
        self._config = config
        self._cache: dict[str, str] = {}
        self._compiled_patterns: dict[str, list[re.Pattern[str]]] = {}

        # Pre-compile keyword patterns
        for intent, patterns in self.KEYWORD_MAP.items():
            self._compiled_patterns[intent] = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns]

    def classify_local(self, text: str) -> str | None:
        """Classify text using local keyword matching.

        Returns the best-matching intent or None if nothing matches.
        """
        if not text:
            return None

        # Check cache
        cache_key = self._make_cache_key(text)
        if self._config.cache_classifications and cache_key in self._cache:
            return self._cache[cache_key]

        scores: dict[str, int] = {}
        for intent, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(text):
                    scores[intent] = scores.get(intent, 0) + 1

        if not scores:
            return None

        best = max(scores, key=lambda k: scores[k])

        if self._config.cache_classifications:
            self._cache[cache_key] = best

        return best

    async def classify(self, text: str) -> str:
        """Classify text — tries local first, falls back to LLM.

        Returns the intent category string. Falls back to 'general'
        if no classification is possible.
        """
        # Try local classification first
        local_result = self.classify_local(text)
        if local_result is not None:
            return local_result

        # Fall back to LLM-based classification if configured
        if self._config.classifier_model:
            try:
                return await self._classify_with_llm(text)
            except Exception:
                logger.warning("LLM classification failed, falling back to 'general'")

        return "general"

    async def _classify_with_llm(self, text: str) -> str:
        """Classify using an LLM call.

        Sends the text to the configured classifier model and extracts
        the intent category from the response.
        """
        # Get available intents from configured rules
        available_intents = {r.intent for r in self._config.rules}
        if not available_intents:
            available_intents = set(self.KEYWORD_MAP.keys())

        intents_list = ", ".join(sorted(available_intents))

        prompt = (
            f"Classify the following user message into exactly ONE of these categories: "
            f"{intents_list}\n\n"
            f"User message: {text}\n\n"
            f"Respond with ONLY the category name, nothing else."
        )

        # Use httpx for a lightweight call to avoid circular imports
        import httpx

        # The classifier model calls through our own proxy (loopback)
        async with httpx.AsyncClient(timeout=self._config.classification_timeout) as client:
            resp = await client.post(
                "http://localhost:4000/v1/chat/completions",
                json={
                    "model": self._config.classifier_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 20,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip().lower()

            # Validate it's a known intent
            if content in available_intents:
                # Cache the result
                if self._config.cache_classifications:
                    cache_key = self._make_cache_key(text)
                    self._cache[cache_key] = content
                return content

        return "general"

    def clear_cache(self) -> None:
        """Clear the classification cache."""
        self._cache.clear()

    @staticmethod
    def _make_cache_key(text: str) -> str:
        """Create a cache key from text (truncated hash for memory)."""
        return hashlib.sha256(text[:500].encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════════
# Semantic router
# ═══════════════════════════════════════════════════════════════════════════


class SemanticRouter:
    """Routes requests to models based on semantic analysis.

    Processing order:
    1. Pattern rules (regex match on prompt) — highest priority
    2. A/B tests (traffic splitting)
    3. Intent classification → intent rules
    4. Default model fallback
    """

    def __init__(self, config: SemanticRoutingConfig) -> None:
        self._config = config
        self._classifier = IntentClassifier(config)
        self._compiled_patterns: list[tuple[re.Pattern[str], PatternRule]] = []
        self._intent_rules: dict[str, str] = {}
        self._ab_tests: dict[str, ABTestConfig] = {}

        # Sort and compile pattern rules
        sorted_patterns = sorted(config.pattern_rules, key=lambda r: -r.priority)
        for rule in sorted_patterns:
            compiled = re.compile(rule.pattern, re.IGNORECASE | re.DOTALL)
            self._compiled_patterns.append((compiled, rule))

        # Index intent rules by priority (highest first)
        sorted_intents = sorted(config.rules, key=lambda r: -r.priority)
        for rule in sorted_intents:
            if rule.intent not in self._intent_rules:
                self._intent_rules[rule.intent] = rule.route_to

        # Index active A/B tests
        for test in config.ab_tests:
            if test.enabled:
                self._ab_tests[test.name] = test

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def config(self) -> SemanticRoutingConfig:
        return self._config

    @property
    def classifier(self) -> IntentClassifier:
        return self._classifier

    async def route(
        self,
        model: str,
        messages: list[dict[str, Any]] | None = None,
        prompt: str | None = None,
    ) -> str:
        """Determine the best model for the request.

        Args:
            model: The originally requested model name.
            messages: Chat messages (extracts last user message).
            prompt: Direct prompt text for completion requests.

        Returns:
            The model name to actually route to (may be the original).
        """
        if not self._config.enabled:
            return model

        # Extract text from messages or prompt
        text = self._extract_text(messages, prompt)
        if not text:
            return model

        # 1. Check pattern rules
        pattern_model = self._match_pattern(text)
        if pattern_model:
            logger.debug("Pattern rule matched → %s", pattern_model)
            return pattern_model

        # 2. Check A/B tests for the requested model
        ab_model = self._resolve_ab_test(model)
        if ab_model and ab_model != model:
            logger.debug("A/B test → %s", ab_model)
            return ab_model

        # 3. Intent classification → intent rules
        intent = await self._classifier.classify(text)
        intent_model = self._intent_rules.get(intent)
        if intent_model:
            logger.debug("Intent '%s' → %s", intent, intent_model)
            return intent_model

        # 4. Default model fallback
        if self._config.default_model:
            return self._config.default_model

        return model

    def _match_pattern(self, text: str) -> str | None:
        """Check pattern rules against the text."""
        for pattern, rule in self._compiled_patterns:
            if pattern.search(text):
                return rule.route_to
        return None

    def _resolve_ab_test(self, model: str) -> str | None:
        """Apply A/B test traffic splitting for the model.

        Uses deterministic random for consistency — the same request
        within a session will always get the same variant.
        """
        for test in self._ab_tests.values():
            if model in (test.model_a, test.model_b):
                if random.random() < test.traffic_split:  # noqa: S311
                    return test.model_a
                return test.model_b
        return None

    @staticmethod
    def _extract_text(
        messages: list[dict[str, Any]] | None,
        prompt: str | None,
    ) -> str | None:
        """Extract the user's text from messages or prompt."""
        if prompt:
            return prompt

        if not messages:
            return None

        # Find the last user message
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                # Handle multimodal content (list of parts)
                if isinstance(content, list):
                    text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                    return " ".join(text_parts) if text_parts else None
        return None

    def get_ab_test_stats(self) -> list[dict[str, Any]]:
        """Return A/B test configurations for reporting."""
        return [
            {
                "name": test.name,
                "model_a": test.model_a,
                "model_b": test.model_b,
                "traffic_split": test.traffic_split,
                "enabled": test.enabled,
                **test.metadata,
            }
            for test in self._config.ab_tests
        ]
