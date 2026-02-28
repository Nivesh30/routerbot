"""Regression detection for evaluation metrics.

Tracks historical scores per model/metric pair and raises alerts when
quality drops beyond configurable thresholds.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from routerbot.evaluation.models import (
    RegressionAlert,
    RegressionConfig,
    RegressionSeverity,
)


class RegressionDetector:
    """Detect quality regressions by comparing scores against baselines.

    Parameters
    ----------
    config:
        Thresholds and settings for regression detection.
    """

    def __init__(self, config: RegressionConfig | None = None) -> None:
        self.config = config or RegressionConfig()
        # model_id → metric_name → list of scores
        self._history: dict[str, dict[str, list[float]]] = {}
        self._alerts: list[RegressionAlert] = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, model_id: str, metric: str, score: float) -> None:
        """Record a score observation."""
        self._history.setdefault(model_id, {}).setdefault(metric, []).append(score)

    def record_batch(self, model_id: str, scores: dict[str, float]) -> None:
        """Record multiple metric scores at once."""
        for metric, score in scores.items():
            self.record(model_id, metric, score)

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def check(self, model_id: str, metric: str, current_score: float) -> RegressionAlert | None:
        """Check if *current_score* represents a regression from baseline.

        Returns an alert if the drop exceeds the configured threshold,
        or *None* if no regression is detected.
        """
        if not self.config.enabled:
            return None

        history = self._history.get(model_id, {}).get(metric, [])
        if len(history) < self.config.min_samples:
            return None

        baseline = sum(history) / len(history)

        if baseline == 0:
            return None

        delta = baseline - current_score
        delta_pct = abs(delta / baseline) if baseline != 0 else 0.0

        # Only flag drops (negative improvement)
        if delta <= 0:
            return None

        severity: RegressionSeverity | None = None
        if delta_pct >= self.config.critical_threshold:
            severity = RegressionSeverity.CRITICAL
        elif delta_pct >= self.config.warning_threshold:
            severity = RegressionSeverity.WARNING
        else:
            return None

        alert = RegressionAlert(
            alert_id=str(uuid.uuid4()),
            model_id=model_id,
            metric=metric,
            severity=severity,
            baseline_score=baseline,
            current_score=current_score,
            delta=delta,
            delta_percent=delta_pct,
            message=(
                f"{severity.value.upper()}: {model_id}/{metric} dropped "
                f"{delta_pct:.1%} (baseline={baseline:.4f}, current={current_score:.4f})"
            ),
            detected_at=datetime.now(tz=UTC),
        )
        self._alerts.append(alert)
        return alert

    def check_all(self, model_id: str, current_scores: dict[str, float]) -> list[RegressionAlert]:
        """Check multiple metrics for regressions at once."""
        alerts: list[RegressionAlert] = []
        for metric, score in current_scores.items():
            alert = self.check(model_id, metric, score)
            if alert is not None:
                alerts.append(alert)
        return alerts

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @property
    def alerts(self) -> list[RegressionAlert]:
        """All recorded alerts."""
        return list(self._alerts)

    def alerts_for_model(self, model_id: str) -> list[RegressionAlert]:
        """Alerts filtered by model ID."""
        return [a for a in self._alerts if a.model_id == model_id]

    def baseline(self, model_id: str, metric: str) -> float | None:
        """Return the average baseline for a model/metric, or None."""
        history = self._history.get(model_id, {}).get(metric, [])
        if not history:
            return None
        return sum(history) / len(history)

    def history_for(self, model_id: str, metric: str) -> list[float]:
        """Return raw score history for a model/metric."""
        return list(self._history.get(model_id, {}).get(metric, []))

    # ------------------------------------------------------------------
    # Management
    # ------------------------------------------------------------------

    def clear_history(self, model_id: str | None = None) -> None:
        """Clear history (optionally for a specific model)."""
        if model_id:
            self._history.pop(model_id, None)
        else:
            self._history.clear()

    def clear_alerts(self) -> None:
        """Clear all alerts."""
        self._alerts.clear()

    def stats(self) -> dict:
        """Return summary statistics."""
        total_observations = sum(
            len(scores) for model_metrics in self._history.values() for scores in model_metrics.values()
        )
        return {
            "models_tracked": len(self._history),
            "total_observations": total_observations,
            "total_alerts": len(self._alerts),
            "critical_alerts": sum(1 for a in self._alerts if a.severity == RegressionSeverity.CRITICAL),
            "warning_alerts": sum(1 for a in self._alerts if a.severity == RegressionSeverity.WARNING),
        }
