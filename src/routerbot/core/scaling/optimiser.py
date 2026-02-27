"""Cost optimisation analysis.

Compares model usage against alternative models to produce
cost-saving recommendations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from routerbot.core.scaling.models import (
    ModelCostProfile,
    RecommendationType,
    UsageRecommendation,
)

if TYPE_CHECKING:
    from routerbot.core.scaling.traffic import TrafficAnalyser

logger = logging.getLogger(__name__)


class CostOptimiser:
    """Analyses current spend and suggests cheaper model alternatives.

    Given a :class:`TrafficAnalyser` with historical snapshots and a
    catalogue of alternative models, the optimiser calculates potential
    savings and generates recommendations ranked by impact.
    """

    def __init__(
        self,
        analyser: TrafficAnalyser,
        alternatives: list[ModelCostProfile] | None = None,
    ) -> None:
        self._analyser = analyser
        self._alternatives: dict[str, ModelCostProfile] = {}
        for alt in alternatives or []:
            self._alternatives[alt.model] = alt

    @property
    def alternatives(self) -> dict[str, ModelCostProfile]:
        return dict(self._alternatives)

    def add_alternative(self, profile: ModelCostProfile) -> None:
        """Register a model as a potential alternative."""
        self._alternatives[profile.model] = profile

    def remove_alternative(self, model: str) -> bool:
        """Remove an alternative model. Returns True if found."""
        return self._alternatives.pop(model, None) is not None

    # ── Analysis ─────────────────────────────────────────────────────

    def analyse(self, hours: int = 24) -> list[UsageRecommendation]:
        """Generate cost-saving recommendations by comparing models.

        For each active model, checks if a cheaper alternative exists
        that could handle the workload with acceptable quality.
        """
        recs: list[UsageRecommendation] = []

        for model in self._analyser.get_all_models():
            cost_24h = self._analyser.get_total_cost(model, hours=hours)
            if cost_24h <= 0:
                continue

            # Find cheaper alternatives
            for alt_model, alt_profile in self._alternatives.items():
                if alt_model == model:
                    continue

                # Estimate savings based on per-token cost ratios
                saving = self._estimate_savings(model, alt_profile, hours)
                if saving and saving > 0:
                    pct = (saving / cost_24h) * 100 if cost_24h > 0 else 0

                    recs.append(
                        UsageRecommendation(
                            rec_type=RecommendationType.MODEL_SWITCH,
                            title=f"Switch {model} to {alt_model}",
                            description=(
                                f"Switching from {model} to {alt_model} could save "
                                f"~${saving:.2f}/day ({pct:.0f}%). "
                                f"Quality score: {alt_profile.quality_score:.1f}/1.0."
                            ),
                            model=model,
                            suggested_model=alt_model,
                            estimated_savings_pct=round(pct, 1),
                            estimated_savings_usd=round(saving, 4),
                            confidence=alt_profile.quality_score,
                            metadata={
                                "current_cost_24h": round(cost_24h, 4),
                                "alt_avg_latency_ms": alt_profile.avg_latency_ms,
                            },
                        )
                    )

        # Sort by savings descending
        recs.sort(key=lambda r: -r.estimated_savings_usd)
        return recs

    def _estimate_savings(
        self,
        current_model: str,
        alt_profile: ModelCostProfile,
        hours: int,
    ) -> float | None:
        """Estimate dollar savings from switching to *alt_profile*."""
        current_cost = self._analyser.get_total_cost(current_model, hours=hours)
        if current_cost <= 0:
            return None

        # Get total tokens to estimate alt cost
        snaps = self._analyser.get_snapshots(current_model)
        total_tokens = sum(s.total_tokens for s in snaps)
        if total_tokens <= 0:
            return None

        # Rough estimate: assume 70% input, 30% output tokens
        input_tokens = int(total_tokens * 0.7)
        output_tokens = total_tokens - input_tokens

        alt_cost = (
            input_tokens * alt_profile.input_cost_per_token
            + output_tokens * alt_profile.output_cost_per_token
        )

        return current_cost - alt_cost
