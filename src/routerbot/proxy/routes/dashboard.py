"""Dashboard statistics endpoint.

Provides a single aggregated endpoint for the admin dashboard,
combining data from spend logs, key/user/team counts, Prometheus
metrics, and model configuration.

Endpoints:
    GET  /dashboard/stats  — Aggregated dashboard metrics
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from routerbot.auth.rbac import Permission, require_permission
from routerbot.db.repositories.keys import KeyRepository
from routerbot.db.repositories.spend import SpendRepository
from routerbot.db.repositories.teams import TeamRepository
from routerbot.db.repositories.users import UserRepository
from routerbot.db.session import get_session
from routerbot.proxy.middleware.auth import get_auth_context

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from routerbot.auth.rbac import AuthContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ---------------------------------------------------------------------------
# Prometheus metric reading helpers
# ---------------------------------------------------------------------------


def _read_prometheus_counter(name: str) -> float:
    """Read the current total value of a Prometheus Counter.

    Sums across all label combinations. Returns 0.0 if not found.
    """
    try:
        from prometheus_client import REGISTRY

        for metric in REGISTRY.collect():
            if metric.name == name:
                total = 0.0
                for sample in metric.samples:
                    if sample.name.endswith("_total") or sample.name == name:
                        total += sample.value
                return total
    except Exception:
        logger.debug("Could not read Prometheus counter %s", name)
    return 0.0


def _read_prometheus_counter_by_label(
    name: str,
    label_name: str,
    *,
    label_filter: dict[str, str] | None = None,
) -> dict[str, float]:
    """Read a Prometheus Counter grouped by a specific label.

    Returns a dict of {label_value: total_value}.
    """
    result: dict[str, float] = {}
    try:
        from prometheus_client import REGISTRY

        for metric in REGISTRY.collect():
            if metric.name == name:
                for sample in metric.samples:
                    if not (sample.name.endswith("_total") or sample.name == name):
                        continue
                    if label_filter and not all(sample.labels.get(k) == v for k, v in label_filter.items()):
                        continue
                    label_val = sample.labels.get(label_name, "unknown")
                    result[label_val] = result.get(label_val, 0.0) + sample.value
    except Exception:
        logger.debug("Could not read Prometheus counter %s by %s", name, label_name)
    return result


def _read_prometheus_histogram_percentiles(name: str) -> dict[str, float]:
    """Approximate latency percentiles from a Prometheus Histogram.

    Returns p50, p95, p99 in milliseconds.
    """
    try:
        from prometheus_client import REGISTRY

        buckets: list[tuple[float, float]] = []
        total_count = 0.0

        for metric in REGISTRY.collect():
            if metric.name == name:
                for sample in metric.samples:
                    if sample.name == f"{name}_bucket":
                        le = float(sample.labels.get("le", "inf"))
                        buckets.append((le, sample.value))
                    elif sample.name == f"{name}_count":
                        total_count += sample.value

        if not buckets or total_count == 0:
            return {"p50": 0, "p95": 0, "p99": 0}

        # Sort by boundary
        buckets.sort(key=lambda x: x[0])

        # Merge across label combinations — take max count per bucket boundary
        merged: dict[float, float] = {}
        for le, count in buckets:
            merged[le] = merged.get(le, 0.0) + count

        sorted_buckets = sorted(merged.items())
        percentiles = {}
        for pct_name, target in [("p50", 0.5), ("p95", 0.95), ("p99", 0.99)]:
            target_count = total_count * target
            for le, count in sorted_buckets:
                if count >= target_count:
                    percentiles[pct_name] = round(le * 1000, 1)  # seconds → ms
                    break
            else:
                percentiles[pct_name] = 0

        return percentiles

    except Exception:
        logger.debug("Could not read Prometheus histogram %s", name)
    return {"p50": 0, "p95": 0, "p99": 0}


def _read_provider_health() -> dict[str, dict[str, Any]]:
    """Read provider health gauges from Prometheus.

    Returns {provider: {status: "healthy"|"unhealthy", value: float}}.
    """
    result: dict[str, dict[str, Any]] = {}
    try:
        from prometheus_client import REGISTRY

        for metric in REGISTRY.collect():
            if metric.name == "routerbot_provider_health":
                for sample in metric.samples:
                    provider = sample.labels.get("provider", "unknown")
                    healthy = sample.value >= 1.0
                    result[provider] = {
                        "status": "healthy" if healthy else "unhealthy",
                        "value": sample.value,
                    }
    except Exception:
        logger.debug("Could not read provider health metrics")
    return result


# ---------------------------------------------------------------------------
# Time-series helpers
# ---------------------------------------------------------------------------


def _bucket_spend_logs_hourly(
    logs: list[Any],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Bucket spend logs into hourly time-series points.

    Returns [{timestamp, requests, spend, tokens}] for each hour.
    """
    # Build empty buckets
    current = start.replace(minute=0, second=0, microsecond=0)
    buckets: dict[str, dict[str, float]] = {}
    while current <= end:
        key = current.isoformat()
        buckets[key] = {"requests": 0, "spend": 0.0, "tokens": 0}
        current += timedelta(hours=1)

    # Fill from logs
    for log in logs:
        ts = log.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        bucket_key = ts.replace(minute=0, second=0, microsecond=0).isoformat()
        if bucket_key in buckets:
            buckets[bucket_key]["requests"] += 1
            buckets[bucket_key]["spend"] += log.cost
            buckets[bucket_key]["tokens"] += log.tokens_prompt + log.tokens_completion

    return [
        {
            "timestamp": ts,
            "requests": int(data["requests"]),
            "spend": round(data["spend"], 6),
            "tokens": int(data["tokens"]),
        }
        for ts, data in sorted(buckets.items())
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/stats", summary="Dashboard statistics")
async def dashboard_stats(
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_session),
    period: str = "24h",
) -> JSONResponse:
    """Return aggregated dashboard statistics.

    Parameters
    ----------
    period:
        Time period for metrics. One of ``1h``, ``24h``, ``7d``, ``30d``.
        Defaults to ``24h``.
    """
    require_permission(ctx, Permission.SPEND_VIEW_ALL)

    # Parse period
    period_map = {"1h": 1, "24h": 24, "7d": 168, "30d": 720}
    hours = period_map.get(period, 24)
    now = datetime.now(tz=UTC)
    start = now - timedelta(hours=hours)

    # -- DB queries --
    spend_repo = SpendRepository(session)
    key_repo = KeyRepository(session)
    team_repo = TeamRepository(session)
    user_repo = UserRepository(session)

    # Get spend logs for the period
    logs = await spend_repo.list_by_date_range(
        start=start,
        end=now,
        offset=0,
        limit=10000,
    )

    # Get counts
    active_keys = await key_repo.list_active(offset=0, limit=10000)
    all_teams = await team_repo.list_all(offset=0, limit=10000)
    all_users = await user_repo.list_all(offset=0, limit=10000)

    # Get model count from config
    state = getattr(request.app.state, "routerbot", None)
    model_count = 0
    model_names: list[str] = []
    if state and state.config:
        model_count = len(state.config.model_list)
        model_names = [m.model_name for m in state.config.model_list]

    # -- Aggregate spend data --
    total_spend = sum(log.cost for log in logs)
    total_requests = len(logs)
    total_tokens = sum(log.tokens_prompt + log.tokens_completion for log in logs)

    # Spend by model
    spend_by_model: dict[str, float] = {}
    requests_by_model: dict[str, int] = {}
    for log in logs:
        spend_by_model[log.model] = spend_by_model.get(log.model, 0.0) + log.cost
        requests_by_model[log.model] = requests_by_model.get(log.model, 0) + 1

    # Top models (by request count)
    top_models = sorted(
        [
            {
                "model": model,
                "requests": requests_by_model.get(model, 0),
                "spend": round(spend_by_model.get(model, 0.0), 6),
            }
            for model in set(list(spend_by_model.keys()) + model_names)
        ],
        key=lambda x: x["requests"],
        reverse=True,
    )[:10]

    # Error rate from Prometheus
    total_success = _read_prometheus_counter_by_label(
        "routerbot_request",
        "status",
        label_filter={"status": "success"},
    )
    total_errors = _read_prometheus_counter_by_label(
        "routerbot_request",
        "status",
        label_filter={"status": "error"},
    )
    success_count = sum(total_success.values())
    error_count = sum(total_errors.values())
    total_prom_requests = success_count + error_count
    error_rate = error_count / total_prom_requests if total_prom_requests > 0 else 0.0

    # Latency from Prometheus histogram
    latency = _read_prometheus_histogram_percentiles("routerbot_request_duration_seconds")

    # Provider health
    provider_health = _read_provider_health()

    # Time series
    time_series = _bucket_spend_logs_hourly(logs, start, now)

    # Recent errors (from Prometheus labels — we'll show model/provider combos)
    recent_errors: list[dict[str, str]] = []
    error_by_model = _read_prometheus_counter_by_label(
        "routerbot_errors",
        "model",
    )
    for model, count in sorted(error_by_model.items(), key=lambda x: -x[1])[:10]:
        recent_errors.append(
            {
                "model": model,
                "error_count": str(int(count)),
                "timestamp": now.isoformat(),
            }
        )

    # Uptime
    health_start = getattr(
        __import__("routerbot.proxy.routes.health", fromlist=["_START_TIME"]),
        "_START_TIME",
        time.time(),
    )
    uptime = round(time.time() - health_start, 1)

    return JSONResponse(
        content={
            "period": period,
            "period_start": start.isoformat(),
            "period_end": now.isoformat(),
            # KPIs
            "total_requests": total_requests,
            "total_spend": round(total_spend, 6),
            "total_tokens": total_tokens,
            "active_keys": len(active_keys),
            "active_models": model_count,
            "active_teams": len(all_teams),
            "active_users": len(all_users),
            "error_rate": round(error_rate, 6),
            # Latency
            "latency_p50": latency.get("p50", 0),
            "latency_p95": latency.get("p95", 0),
            "latency_p99": latency.get("p99", 0),
            # Breakdowns
            "spend_by_model": {k: round(v, 6) for k, v in spend_by_model.items()},
            "requests_by_model": requests_by_model,
            "top_models": top_models,
            # Time series
            "time_series": time_series,
            # Health
            "provider_health": provider_health,
            "uptime_seconds": uptime,
            # Errors
            "recent_errors": recent_errors,
        }
    )
