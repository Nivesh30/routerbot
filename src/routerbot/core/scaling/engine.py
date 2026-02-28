"""Recommendation engine.

Orchestrates traffic analysis, cost optimisation, and alerting into
a unified interface that the dashboard and API can consume.
"""

from __future__ import annotations

import logging
from typing import Any

from routerbot.core.scaling.alerts import CostAlertManager
from routerbot.core.scaling.models import (
    CostAlert,
    RecommendationType,
    ScalingConfig,
    UsageRecommendation,
)
from routerbot.core.scaling.optimiser import CostOptimiser
from routerbot.core.scaling.traffic import TrafficAnalyser

logger = logging.getLogger(__name__)


class RecommendationEngine:
    """Top-level engine that ties together all scaling subsystems.

    Provides a single entry point for:
    - Recording traffic events
    - Taking periodic snapshots
    - Generating recommendations (cost + performance + scaling)
    - Checking cost alerts

    Intended to be instantiated once at startup and stored on app state.
    """

    def __init__(self, config: ScalingConfig) -> None:
        self._config = config
        self._analyser = TrafficAnalyser(max_snapshots=config.max_snapshots)
        self._optimiser = CostOptimiser(
            self._analyser,
            alternatives=config.alternative_models,
        )
        self._alert_manager = CostAlertManager(
            self._analyser,
            thresholds=config.cost_thresholds,
        )

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def config(self) -> ScalingConfig:
        return self._config

    @property
    def analyser(self) -> TrafficAnalyser:
        return self._analyser

    @property
    def optimiser(self) -> CostOptimiser:
        return self._optimiser

    @property
    def alert_manager(self) -> CostAlertManager:
        return self._alert_manager

    # ── Recording (delegates to analyser) ────────────────────────────

    def record_request(
        self,
        model: str,
        tokens: int = 0,
        cost: float = 0.0,
        latency_ms: float = 0.0,
        *,
        is_error: bool = False,
    ) -> None:
        """Record a single request event."""
        self._analyser.record_request(
            model,
            tokens=tokens,
            cost=cost,
            latency_ms=latency_ms,
            is_error=is_error,
        )

    def take_snapshots(self) -> None:
        """Capture a traffic snapshot for all active models."""
        self._analyser.take_snapshot()

    # ── Recommendations ──────────────────────────────────────────────

    def get_recommendations(self, hours: int = 24) -> list[UsageRecommendation]:
        """Generate all recommendations: cost savings + performance + scaling."""
        recs: list[UsageRecommendation] = []

        if self._config.enable_recommendations:
            # Cost optimisation recommendations
            recs.extend(self._optimiser.analyse(hours=hours))

            # Performance recommendations (high latency)
            recs.extend(self._get_performance_recs(hours=hours))

            # Scaling recommendations (high error rate)
            recs.extend(self._get_scaling_recs(hours=hours))

        return recs

    def get_alerts(self) -> list[CostAlert]:
        """Check cost thresholds and return any triggered alerts."""
        if not self._config.enable_cost_alerts:
            return []
        return self._alert_manager.check()

    def get_dashboard_data(self) -> dict[str, Any]:
        """Return a summary suitable for the recommendations dashboard."""
        return {
            "traffic_summary": self._analyser.get_traffic_summary(),
            "recommendations": [r.model_dump() for r in self.get_recommendations()],
            "alerts": [a.model_dump() for a in self.get_alerts()],
            "active_models": self._analyser.get_all_models(),
        }

    # ── Internal recommendation generators ───────────────────────────

    def _get_performance_recs(self, hours: int = 24) -> list[UsageRecommendation]:
        """Generate recommendations for models with high latency."""
        recs: list[UsageRecommendation] = []
        high_latency_threshold_ms = 5000  # 5 seconds

        for model in self._analyser.get_all_models():
            avg_latency = self._analyser.get_avg_latency(model, hours=hours)
            if avg_latency > high_latency_threshold_ms:
                recs.append(
                    UsageRecommendation(
                        rec_type=RecommendationType.PERFORMANCE,
                        title=f"High latency on {model}",
                        description=(
                            f"Average latency for {model} is {avg_latency:.0f}ms "
                            f"(>{high_latency_threshold_ms}ms). Consider a faster "
                            f"provider or a smaller model variant."
                        ),
                        model=model,
                        confidence=0.7,
                        metadata={"avg_latency_ms": round(avg_latency, 1)},
                    )
                )

        return recs

    def _get_scaling_recs(self, hours: int = 24) -> list[UsageRecommendation]:
        """Generate recommendations for models with high error rates."""
        recs: list[UsageRecommendation] = []
        error_rate_threshold = 0.05  # 5%

        for model in self._analyser.get_all_models():
            error_rate = self._analyser.get_error_rate(model, hours=hours)
            if error_rate > error_rate_threshold:
                recs.append(
                    UsageRecommendation(
                        rec_type=RecommendationType.SCALING,
                        title=f"High error rate on {model}",
                        description=(
                            f"Error rate for {model} is {error_rate * 100:.1f}% "
                            f"(>{error_rate_threshold * 100:.0f}%). This may indicate "
                            f"rate limiting or capacity issues. Consider adding "
                            f"fallback models or increasing rate limits."
                        ),
                        model=model,
                        confidence=0.8,
                        metadata={"error_rate": round(error_rate, 4)},
                    )
                )

        return recs
