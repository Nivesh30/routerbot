"""LLM-as-judge evaluator.

Uses a configurable LLM to score candidate responses against a rubric.
The judge receives the input, (optional) reference, and candidate, then
returns per-criteria scores plus free-form reasoning.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from routerbot.evaluation.models import JudgeConfig, JudgeCriteria, JudgeVerdict


def _build_judge_prompt(
    *,
    criteria: list[JudgeCriteria],
    input_text: str,
    candidate: str,
    reference: str | None = None,
) -> str:
    """Construct the prompt sent to the judge model."""
    parts: list[str] = []
    parts.append("Evaluate the following response.\n")

    if reference:
        parts.append(f"## Reference answer\n{reference}\n")

    parts.append(f"## Input\n{input_text}\n")
    parts.append(f"## Candidate response\n{candidate}\n")

    parts.append("## Criteria - score each on the given scale\n")
    for c in criteria:
        parts.append(f"- **{c.name}** ({c.scale_min}-{c.scale_max}): {c.description}")

    parts.append('\nRespond with JSON: {"scores": {"<criteria_name>": <number>, ...}, "reasoning": "<text>"}')
    return "\n".join(parts)


def _parse_judge_response(raw: str, criteria: list[JudgeCriteria]) -> tuple[dict[str, float], str]:
    """Best-effort parse of the judge model response."""
    # Try to extract JSON from the response
    reasoning = ""
    scores: dict[str, float] = {}

    # Find JSON block (possibly wrapped in ```json ... ```)
    json_match = None
    for start_marker in ("{",):
        idx = raw.find(start_marker)
        if idx >= 0:
            # Find matching closing brace
            depth = 0
            for i in range(idx, len(raw)):
                if raw[i] == "{":
                    depth += 1
                elif raw[i] == "}":
                    depth -= 1
                    if depth == 0:
                        json_match = raw[idx : i + 1]
                        break
            if json_match:
                break

    if json_match:
        try:
            data = json.loads(json_match)
            raw_scores = data.get("scores", {})
            reasoning = data.get("reasoning", "")
            for c in criteria:
                if c.name in raw_scores:
                    score = float(raw_scores[c.name])
                    # Clamp to range
                    score = max(c.scale_min, min(c.scale_max, score))
                    scores[c.name] = score
        except (json.JSONDecodeError, ValueError, TypeError):
            reasoning = raw
    else:
        reasoning = raw

    return scores, reasoning


class LLMJudge:
    """Evaluate responses using an LLM-as-judge pattern.

    The judge sends the input + candidate (+ optional reference) to a
    configurable LLM model, which returns per-criteria scores and reasoning.

    Parameters
    ----------
    config:
        Judge configuration (model, criteria, system prompt, temperature).
    handler:
        An async callable ``(model, messages, **kwargs) -> str`` that sends
        the request to the LLM backend and returns the text response.
        If *None*, the judge will use a stub that returns empty scores.
    """

    def __init__(
        self,
        config: JudgeConfig | None = None,
        handler: Any = None,
    ) -> None:
        self.config = config or JudgeConfig()
        self._handler = handler
        self._history: list[JudgeVerdict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        *,
        sample_id: str = "",
        model_id: str = "",
        input_text: str,
        candidate: str,
        reference: str | None = None,
    ) -> JudgeVerdict:
        """Run the judge on a single candidate response."""
        prompt = _build_judge_prompt(
            criteria=self.config.criteria,
            input_text=input_text,
            candidate=candidate,
            reference=reference,
        )
        messages = [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": prompt},
        ]

        if self._handler is not None:
            raw_response = await self._handler(
                self.config.judge_model,
                messages,
                temperature=self.config.temperature,
            )
        else:
            raw_response = "{}"

        scores, reasoning = _parse_judge_response(raw_response, self.config.criteria)

        verdict = JudgeVerdict(
            sample_id=sample_id or str(uuid.uuid4()),
            model_id=model_id,
            scores=scores,
            reasoning=reasoning,
            judge_model=self.config.judge_model,
        )
        self._history.append(verdict)
        return verdict

    async def evaluate_batch(
        self,
        items: list[dict[str, Any]],
    ) -> list[JudgeVerdict]:
        """Evaluate multiple items sequentially.

        Each item dict should have keys: ``input_text``, ``candidate``,
        and optionally ``sample_id``, ``model_id``, ``reference``.
        """
        results: list[JudgeVerdict] = []
        for item in items:
            verdict = await self.evaluate(
                sample_id=item.get("sample_id", ""),
                model_id=item.get("model_id", ""),
                input_text=item["input_text"],
                candidate=item["candidate"],
                reference=item.get("reference"),
            )
            results.append(verdict)
        return results

    def weighted_score(self, verdict: JudgeVerdict) -> float:
        """Compute a weighted average score from a verdict."""
        total_weight = 0.0
        weighted_sum = 0.0
        for c in self.config.criteria:
            if c.name in verdict.scores:
                # Normalise to 0-1 range
                raw = verdict.scores[c.name]
                normalised = (raw - c.scale_min) / (c.scale_max - c.scale_min) if c.scale_max > c.scale_min else 0.0
                weighted_sum += normalised * c.weight
                total_weight += c.weight

        if total_weight == 0:
            return 0.0
        return weighted_sum / total_weight

    @property
    def history(self) -> list[JudgeVerdict]:
        """Return all historical verdicts."""
        return list(self._history)

    def clear_history(self) -> None:
        """Clear verdict history."""
        self._history.clear()
