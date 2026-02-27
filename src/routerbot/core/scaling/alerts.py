"""Cost alerting.

Monitors spend against configurable thresholds and generates
alerts when limits are approached or exceeded.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from routerbot.core.scaling.models import (
    CostAlert,
    CostThreshold,
)

if TYPE_CHECKING:
    from routerbot.core.scaling.traffic import TrafficAnalyser

logger = logging.getLogger(__name__)

# Period name → hours lookup
_PERIOD_HOURS: dict[str, int] = {
    "daily": 24,
    "weekly": 168,
    "monthly": 720,
}


class CostAlertManager:
    """Checks spend against thresholds and produces :class:`CostAlert` objects.

    Thresholds can be global or per-model. The manager deduplicates
    alerts so the same threshold doesn't fire repeatedly within its
    period.
    """

    def __init__(
        self,
        analyser: TrafficAnalyser,
        thresholds: list[CostThreshold] | None = None,
    ) -> None:
        self._analyser = analyser
        self._thresholds = [t for t in (thresholds or []) if t.enabled]
        # Track which thresholds have already fired this period
        self._fired: dict[str, datetime] = {}

    @property
    def thresholds(self) -> list[CostThreshold]:
        return list(self._thresholds)

    def add_threshold(self, threshold: CostThreshold) -> None:
        """Register a new cost threshold."""
        if threshold.enabled:
            self._thresholds.append(threshold)

    def remove_threshold(self, name: str) -> bool:
        """Remove a threshold by name. Returns True if found."""
        before = len(self._thresholds)
        self._thresholds = [t for t in self._thresholds if t.name != name]
        return len(self._thresholds) < before

    # ── Check ────────────────────────────────────────────────────────

    def check(self) -> list[CostAlert]:
        """Evaluate all thresholds and return any triggered alerts."""
        alerts: list[CostAlert] = []
        now = datetime.now(tz=UTC)

        for threshold in self._thresholds:
            hours = _PERIOD_HOURS.get(threshold.period, 24)
            models = [threshold.model] if threshold.model else self._analyser.get_all_models()

            for model in models:
                spend = self._analyser.get_total_cost(model, hours=hours)
                if spend < threshold.amount:
                    continue

                # Deduplication: don't fire the same alert within the period
                dedup_key = f"{threshold.name}:{model}"
                last_fired = self._fired.get(dedup_key)
                if last_fired:
                    # Skip if fired within the current period window
                    from datetime import timedelta

                    if (now - last_fired) < timedelta(hours=hours):
                        continue

                alert = CostAlert(
                    severity=threshold.severity,
                    title=f"Cost threshold '{threshold.name}' exceeded for {model}",
                    description=(
                        f"Spend for {model} is ${spend:.2f} which exceeds the "
                        f"{threshold.period} threshold of ${threshold.amount:.2f}."
                    ),
                    model=model,
                    current_spend=round(spend, 4),
                    threshold=threshold.amount,
                    timestamp=now,
                    metadata={
                        "threshold_name": threshold.name,
                        "period": threshold.period,
                    },
                )
                alerts.append(alert)
                self._fired[dedup_key] = now

                logger.warning(
                    "Cost alert: %s — $%.2f exceeds $%.2f (%s)",
                    model,
                    spend,
                    threshold.amount,
                    threshold.period,
                )

        return alerts

    def clear_fired(self) -> None:
        """Reset the deduplication state so alerts can fire again."""
        self._fired.clear()
