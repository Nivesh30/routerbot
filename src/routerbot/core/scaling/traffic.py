"""Traffic pattern analysis.

Collects traffic snapshots and computes metrics like peak RPM,
average latency, and usage trends that feed into the recommendation
engine.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from routerbot.core.scaling.models import TrafficSnapshot

logger = logging.getLogger(__name__)


class TrafficAnalyser:
    """Collects and analyses traffic snapshots per model.

    Snapshots are stored in a bounded ring buffer. The analyser exposes
    aggregate metrics and trend detection for the recommendation engine.
    """

    def __init__(self, max_snapshots: int = 1440) -> None:
        self._max_snapshots = max_snapshots
        self._snapshots: dict[str, list[TrafficSnapshot]] = defaultdict(list)
        # Running counters for recording
        self._request_counts: dict[str, int] = defaultdict(int)
        self._token_counts: dict[str, int] = defaultdict(int)
        self._cost_totals: dict[str, float] = defaultdict(float)
        self._latencies: dict[str, list[float]] = defaultdict(list)
        self._error_counts: dict[str, int] = defaultdict(int)

    # ── Recording ────────────────────────────────────────────────────

    def record_request(
        self,
        model: str,
        tokens: int = 0,
        cost: float = 0.0,
        latency_ms: float = 0.0,
        *,
        is_error: bool = False,
    ) -> None:
        """Record a single request for the given model."""
        self._request_counts[model] += 1
        self._token_counts[model] += tokens
        self._cost_totals[model] += cost
        if latency_ms > 0:
            self._latencies[model].append(latency_ms)
        if is_error:
            self._error_counts[model] += 1

    def take_snapshot(self, model: str | None = None) -> list[TrafficSnapshot]:
        """Capture a snapshot of current metrics and reset counters.

        If *model* is given, only snapshot that model; otherwise all
        models with recorded traffic.
        """
        models = [model] if model else list(self._request_counts.keys())
        snapshots: list[TrafficSnapshot] = []

        now = datetime.now(tz=UTC)
        for m in models:
            req_count = self._request_counts.get(m, 0)
            tok_count = self._token_counts.get(m, 0)
            latencies = self._latencies.get(m, [])
            err_count = self._error_counts.get(m, 0)

            error_rate = err_count / req_count if req_count > 0 else 0.0
            avg_lat = statistics.mean(latencies) if latencies else 0.0

            snap = TrafficSnapshot(
                model=m,
                timestamp=now,
                requests_per_minute=float(req_count),  # per snapshot interval
                tokens_per_minute=float(tok_count),
                avg_latency_ms=avg_lat,
                error_rate=error_rate,
                total_cost=self._cost_totals.get(m, 0.0),
                total_requests=req_count,
                total_tokens=tok_count,
            )
            snapshots.append(snap)
            self._snapshots[m].append(snap)

            # Trim to max
            if len(self._snapshots[m]) > self._max_snapshots:
                self._snapshots[m] = self._snapshots[m][-self._max_snapshots :]

        # Reset running counters
        for m in models:
            self._request_counts[m] = 0
            self._token_counts[m] = 0
            self._cost_totals[m] = 0.0
            self._latencies[m] = []
            self._error_counts[m] = 0

        return snapshots

    # ── Analysis ─────────────────────────────────────────────────────

    def get_snapshots(
        self,
        model: str,
        since: datetime | None = None,
    ) -> list[TrafficSnapshot]:
        """Return stored snapshots for a model, optionally filtered by time."""
        snaps = self._snapshots.get(model, [])
        if since:
            snaps = [s for s in snaps if s.timestamp >= since]
        return snaps

    def get_peak_rpm(self, model: str, hours: int = 1) -> float:
        """Return peak requests-per-minute for the model in the last N hours."""
        since = datetime.now(tz=UTC) - timedelta(hours=hours)
        snaps = self.get_snapshots(model, since=since)
        if not snaps:
            return 0.0
        return max(s.requests_per_minute for s in snaps)

    def get_avg_latency(self, model: str, hours: int = 1) -> float:
        """Return average latency across snapshots in the last N hours."""
        since = datetime.now(tz=UTC) - timedelta(hours=hours)
        snaps = self.get_snapshots(model, since=since)
        latencies = [s.avg_latency_ms for s in snaps if s.avg_latency_ms > 0]
        return statistics.mean(latencies) if latencies else 0.0

    def get_total_cost(self, model: str, hours: int = 24) -> float:
        """Return total cost for the model in the last N hours."""
        since = datetime.now(tz=UTC) - timedelta(hours=hours)
        snaps = self.get_snapshots(model, since=since)
        return sum(s.total_cost for s in snaps)

    def get_error_rate(self, model: str, hours: int = 1) -> float:
        """Return average error rate in the last N hours."""
        since = datetime.now(tz=UTC) - timedelta(hours=hours)
        snaps = self.get_snapshots(model, since=since)
        rates = [s.error_rate for s in snaps if s.total_requests > 0]
        return statistics.mean(rates) if rates else 0.0

    def get_all_models(self) -> list[str]:
        """Return a list of all models with recorded traffic."""
        return list(self._snapshots.keys())

    def get_traffic_summary(self) -> list[dict[str, Any]]:
        """Return a summary of recent traffic for all models."""
        summary = []
        for model in self.get_all_models():
            snaps = self._snapshots[model]
            if not snaps:
                continue
            latest = snaps[-1]
            summary.append(
                {
                    "model": model,
                    "total_snapshots": len(snaps),
                    "latest_rpm": latest.requests_per_minute,
                    "latest_tpm": latest.tokens_per_minute,
                    "latest_latency_ms": latest.avg_latency_ms,
                    "latest_error_rate": latest.error_rate,
                    "total_cost_24h": self.get_total_cost(model, hours=24),
                }
            )
        return summary

    def clear(self, model: str | None = None) -> None:
        """Clear stored snapshots and counters."""
        if model:
            self._snapshots.pop(model, None)
            self._request_counts.pop(model, None)
            self._token_counts.pop(model, None)
            self._cost_totals.pop(model, None)
            self._latencies.pop(model, None)
            self._error_counts.pop(model, None)
        else:
            self._snapshots.clear()
            self._request_counts.clear()
            self._token_counts.clear()
            self._cost_totals.clear()
            self._latencies.clear()
            self._error_counts.clear()
