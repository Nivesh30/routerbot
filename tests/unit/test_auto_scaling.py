"""Tests for the auto-scaling recommendations module (Task 8C.3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from routerbot.core.scaling.alerts import CostAlertManager
from routerbot.core.scaling.engine import RecommendationEngine
from routerbot.core.scaling.models import (
    AlertSeverity,
    CostAlert,
    CostThreshold,
    ModelCostProfile,
    RecommendationType,
    ScalingConfig,
    TrafficSnapshot,
    UsageRecommendation,
)
from routerbot.core.scaling.optimiser import CostOptimiser
from routerbot.core.scaling.traffic import TrafficAnalyser


# ── Model tests ──────────────────────────────────────────────────────


class TestModels:
    """Validate pydantic models and enums."""

    def test_alert_severity_values(self) -> None:
        assert AlertSeverity.INFO == "info"
        assert AlertSeverity.WARNING == "warning"
        assert AlertSeverity.CRITICAL == "critical"

    def test_recommendation_type_values(self) -> None:
        assert RecommendationType.COST_SAVING == "cost_saving"
        assert RecommendationType.PERFORMANCE == "performance"
        assert RecommendationType.SCALING == "scaling"
        assert RecommendationType.MODEL_SWITCH == "model_switch"

    def test_traffic_snapshot_defaults(self) -> None:
        snap = TrafficSnapshot(model="gpt-4")
        assert snap.model == "gpt-4"
        assert snap.requests_per_minute == 0.0
        assert snap.tokens_per_minute == 0.0
        assert snap.avg_latency_ms == 0.0
        assert snap.error_rate == 0.0
        assert snap.total_cost == 0.0
        assert snap.total_requests == 0
        assert snap.total_tokens == 0
        assert snap.timestamp is not None

    def test_traffic_snapshot_with_values(self) -> None:
        ts = datetime(2025, 1, 1, tzinfo=UTC)
        snap = TrafficSnapshot(
            model="gpt-4",
            timestamp=ts,
            requests_per_minute=120.0,
            tokens_per_minute=50000.0,
            avg_latency_ms=450.0,
            error_rate=0.02,
            total_cost=5.50,
            total_requests=120,
            total_tokens=50000,
        )
        assert snap.requests_per_minute == 120.0
        assert snap.total_cost == 5.50
        assert snap.timestamp == ts

    def test_usage_recommendation_defaults(self) -> None:
        rec = UsageRecommendation(
            rec_type=RecommendationType.COST_SAVING,
            title="Test",
            description="Test desc",
        )
        assert rec.model is None
        assert rec.suggested_model is None
        assert rec.estimated_savings_pct == 0.0
        assert rec.estimated_savings_usd == 0.0
        assert rec.confidence == 0.5
        assert rec.metadata == {}

    def test_usage_recommendation_confidence_bounds(self) -> None:
        rec = UsageRecommendation(
            rec_type=RecommendationType.COST_SAVING,
            title="T",
            description="D",
            confidence=1.0,
        )
        assert rec.confidence == 1.0

        with pytest.raises(Exception):
            UsageRecommendation(
                rec_type=RecommendationType.COST_SAVING,
                title="T",
                description="D",
                confidence=1.5,
            )

    def test_cost_alert_defaults(self) -> None:
        alert = CostAlert(
            severity=AlertSeverity.WARNING,
            title="Threshold hit",
            description="Desc",
        )
        assert alert.model is None
        assert alert.current_spend == 0.0
        assert alert.threshold == 0.0
        assert alert.timestamp is not None

    def test_model_cost_profile(self) -> None:
        profile = ModelCostProfile(
            model="gpt-3.5-turbo",
            provider="openai",
            input_cost_per_token=0.0000005,
            output_cost_per_token=0.0000015,
            avg_latency_ms=200.0,
            quality_score=0.7,
        )
        assert profile.model == "gpt-3.5-turbo"
        assert profile.quality_score == 0.7

    def test_model_cost_profile_quality_score_bounds(self) -> None:
        with pytest.raises(Exception):
            ModelCostProfile(model="x", quality_score=1.1)

    def test_cost_threshold_defaults(self) -> None:
        t = CostThreshold(name="daily-limit", amount=100.0)
        assert t.period == "daily"
        assert t.severity == AlertSeverity.WARNING
        assert t.model is None
        assert t.enabled is True

    def test_cost_threshold_per_model(self) -> None:
        t = CostThreshold(
            name="gpt4-limit",
            amount=50.0,
            period="weekly",
            severity=AlertSeverity.CRITICAL,
            model="gpt-4",
        )
        assert t.model == "gpt-4"
        assert t.period == "weekly"
        assert t.severity == AlertSeverity.CRITICAL

    def test_scaling_config_defaults(self) -> None:
        cfg = ScalingConfig()
        assert cfg.enabled is False
        assert cfg.snapshot_interval_seconds == 60
        assert cfg.max_snapshots == 1440
        assert cfg.cost_thresholds == []
        assert cfg.alternative_models == []
        assert cfg.enable_cost_alerts is True
        assert cfg.enable_recommendations is True

    def test_scaling_config_from_dict(self) -> None:
        """Simulate config loading from YAML (dict)."""
        cfg = ScalingConfig(
            **{
                "enabled": True,
                "snapshot_interval_seconds": 30,
                "max_snapshots": 100,
                "cost_thresholds": [
                    {"name": "daily", "amount": 100.0},
                ],
                "alternative_models": [
                    {
                        "model": "gpt-3.5-turbo",
                        "provider": "openai",
                        "input_cost_per_token": 0.0000005,
                        "output_cost_per_token": 0.0000015,
                    },
                ],
            }
        )
        assert cfg.enabled is True
        assert cfg.snapshot_interval_seconds == 30
        assert len(cfg.cost_thresholds) == 1
        assert len(cfg.alternative_models) == 1


# ── TrafficAnalyser tests ───────────────────────────────────────────


class TestTrafficAnalyser:
    """Test the TrafficAnalyser class."""

    def test_record_and_snapshot(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", tokens=100, cost=0.01, latency_ms=200.0)
        ta.record_request("gpt-4", tokens=150, cost=0.02, latency_ms=300.0)

        snaps = ta.take_snapshot("gpt-4")
        assert len(snaps) == 1
        snap = snaps[0]
        assert snap.model == "gpt-4"
        assert snap.total_requests == 2
        assert snap.total_tokens == 250
        assert snap.total_cost == pytest.approx(0.03)
        assert snap.avg_latency_ms == pytest.approx(250.0)
        assert snap.error_rate == 0.0

    def test_record_errors(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", is_error=True)
        ta.record_request("gpt-4")
        ta.record_request("gpt-4", is_error=True)

        snaps = ta.take_snapshot("gpt-4")
        assert snaps[0].error_rate == pytest.approx(2 / 3)

    def test_snapshot_resets_counters(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", tokens=100, cost=0.01)
        ta.take_snapshot("gpt-4")

        # After snapshot, counters should be reset
        snaps = ta.take_snapshot("gpt-4")
        assert snaps[0].total_requests == 0
        assert snaps[0].total_tokens == 0
        assert snaps[0].total_cost == 0.0

    def test_snapshot_all_models(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", tokens=100)
        ta.record_request("gpt-3.5-turbo", tokens=50)

        snaps = ta.take_snapshot()
        assert len(snaps) == 2
        models = {s.model for s in snaps}
        assert models == {"gpt-4", "gpt-3.5-turbo"}

    def test_max_snapshots_trimming(self) -> None:
        ta = TrafficAnalyser(max_snapshots=3)
        for _ in range(5):
            ta.record_request("gpt-4", tokens=10)
            ta.take_snapshot("gpt-4")

        stored = ta.get_snapshots("gpt-4")
        assert len(stored) == 3

    def test_get_snapshots_with_since(self) -> None:
        ta = TrafficAnalyser()
        old_ts = datetime(2020, 1, 1, tzinfo=UTC)
        new_ts = datetime.now(tz=UTC)

        # Inject snapshots directly
        ta._snapshots["gpt-4"].append(
            TrafficSnapshot(model="gpt-4", timestamp=old_ts, total_requests=1)
        )
        ta._snapshots["gpt-4"].append(
            TrafficSnapshot(model="gpt-4", timestamp=new_ts, total_requests=2)
        )

        recent = ta.get_snapshots("gpt-4", since=datetime.now(tz=UTC) - timedelta(hours=1))
        assert len(recent) == 1
        assert recent[0].total_requests == 2

    def test_get_peak_rpm(self) -> None:
        ta = TrafficAnalyser()
        # Create two snapshots with different RPMs
        ta.record_request("gpt-4", tokens=100)
        ta.take_snapshot("gpt-4")
        for _ in range(10):
            ta.record_request("gpt-4", tokens=10)
        ta.take_snapshot("gpt-4")

        peak = ta.get_peak_rpm("gpt-4", hours=1)
        assert peak == 10.0

    def test_get_avg_latency(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", latency_ms=200.0)
        ta.take_snapshot("gpt-4")
        ta.record_request("gpt-4", latency_ms=400.0)
        ta.take_snapshot("gpt-4")

        avg = ta.get_avg_latency("gpt-4", hours=1)
        assert avg == pytest.approx(300.0)

    def test_get_total_cost(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", cost=1.50)
        ta.take_snapshot("gpt-4")
        ta.record_request("gpt-4", cost=2.00)
        ta.take_snapshot("gpt-4")

        total = ta.get_total_cost("gpt-4", hours=24)
        assert total == pytest.approx(3.50)

    def test_get_error_rate(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", is_error=True)
        ta.record_request("gpt-4")
        ta.take_snapshot("gpt-4")

        rate = ta.get_error_rate("gpt-4", hours=1)
        assert rate == pytest.approx(0.5)

    def test_get_error_rate_empty(self) -> None:
        ta = TrafficAnalyser()
        assert ta.get_error_rate("nonexistent", hours=1) == 0.0

    def test_get_all_models(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", tokens=10)
        ta.take_snapshot("gpt-4")
        ta.record_request("claude-3", tokens=10)
        ta.take_snapshot("claude-3")

        models = ta.get_all_models()
        assert set(models) == {"gpt-4", "claude-3"}

    def test_get_traffic_summary(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", tokens=100, cost=0.5, latency_ms=200.0)
        ta.take_snapshot("gpt-4")

        summary = ta.get_traffic_summary()
        assert len(summary) == 1
        assert summary[0]["model"] == "gpt-4"
        assert summary[0]["total_snapshots"] == 1
        assert summary[0]["latest_rpm"] == 1.0

    def test_clear_model(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", tokens=100)
        ta.take_snapshot("gpt-4")
        ta.record_request("claude-3", tokens=50)
        ta.take_snapshot("claude-3")

        ta.clear("gpt-4")
        assert ta.get_all_models() == ["claude-3"]

    def test_clear_all(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", tokens=100)
        ta.take_snapshot("gpt-4")

        ta.clear()
        assert ta.get_all_models() == []

    def test_get_peak_rpm_empty(self) -> None:
        ta = TrafficAnalyser()
        assert ta.get_peak_rpm("nomodel") == 0.0

    def test_get_avg_latency_empty(self) -> None:
        ta = TrafficAnalyser()
        assert ta.get_avg_latency("nomodel") == 0.0

    def test_zero_latency_excluded(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4")  # no latency
        ta.take_snapshot("gpt-4")
        assert ta.get_avg_latency("gpt-4") == 0.0


# ── CostOptimiser tests ─────────────────────────────────────────────


class TestCostOptimiser:
    """Test the CostOptimiser class."""

    def _make_analyser_with_data(self) -> TrafficAnalyser:
        ta = TrafficAnalyser()
        # Record gpt-4 usage: 1000 tokens, $5.00
        for _ in range(10):
            ta.record_request("gpt-4", tokens=100, cost=0.50, latency_ms=300.0)
        ta.take_snapshot("gpt-4")
        return ta

    def test_analyse_with_cheaper_alternative(self) -> None:
        ta = self._make_analyser_with_data()
        alt = ModelCostProfile(
            model="gpt-3.5-turbo",
            provider="openai",
            input_cost_per_token=0.0000005,
            output_cost_per_token=0.0000015,
            quality_score=0.7,
        )
        opt = CostOptimiser(ta, alternatives=[alt])

        recs = opt.analyse(hours=24)
        assert len(recs) == 1
        assert recs[0].rec_type == RecommendationType.MODEL_SWITCH
        assert recs[0].model == "gpt-4"
        assert recs[0].suggested_model == "gpt-3.5-turbo"
        assert recs[0].estimated_savings_usd > 0

    def test_analyse_no_alternatives(self) -> None:
        ta = self._make_analyser_with_data()
        opt = CostOptimiser(ta)

        recs = opt.analyse()
        assert recs == []

    def test_analyse_no_usage(self) -> None:
        ta = TrafficAnalyser()
        alt = ModelCostProfile(
            model="cheap-model",
            input_cost_per_token=0.0000001,
            output_cost_per_token=0.0000001,
        )
        opt = CostOptimiser(ta, alternatives=[alt])

        recs = opt.analyse()
        assert recs == []

    def test_add_remove_alternative(self) -> None:
        ta = TrafficAnalyser()
        opt = CostOptimiser(ta)

        alt = ModelCostProfile(model="new-model", input_cost_per_token=0.001)
        opt.add_alternative(alt)
        assert "new-model" in opt.alternatives

        removed = opt.remove_alternative("new-model")
        assert removed is True
        assert "new-model" not in opt.alternatives

        not_found = opt.remove_alternative("nonexistent")
        assert not_found is False

    def test_analyse_skips_same_model(self) -> None:
        """Optimiser should not recommend switching a model to itself."""
        ta = TrafficAnalyser()
        for _ in range(5):
            ta.record_request("gpt-4", tokens=100, cost=0.50)
        ta.take_snapshot("gpt-4")

        alt = ModelCostProfile(
            model="gpt-4",
            input_cost_per_token=0.00003,
            output_cost_per_token=0.00006,
        )
        opt = CostOptimiser(ta, alternatives=[alt])
        recs = opt.analyse()
        assert recs == []

    def test_analyse_sorted_by_savings(self) -> None:
        ta = TrafficAnalyser()
        for _ in range(10):
            ta.record_request("gpt-4", tokens=100, cost=0.50, latency_ms=300.0)
        ta.take_snapshot("gpt-4")

        alts = [
            ModelCostProfile(
                model="cheap-a",
                input_cost_per_token=0.0000001,
                output_cost_per_token=0.0000001,
                quality_score=0.6,
            ),
            ModelCostProfile(
                model="cheap-b",
                input_cost_per_token=0.0000002,
                output_cost_per_token=0.0000002,
                quality_score=0.7,
            ),
        ]
        opt = CostOptimiser(ta, alternatives=alts)
        recs = opt.analyse()
        assert len(recs) == 2
        assert recs[0].estimated_savings_usd >= recs[1].estimated_savings_usd

    def test_estimate_savings_no_cost(self) -> None:
        ta = TrafficAnalyser()
        # Record tokens but no cost
        ta.record_request("gpt-4", tokens=100, cost=0.0)
        ta.take_snapshot("gpt-4")

        alt = ModelCostProfile(model="cheap", input_cost_per_token=0.001)
        opt = CostOptimiser(ta, alternatives=[alt])

        recs = opt.analyse()
        assert recs == []


# ── CostAlertManager tests ──────────────────────────────────────────


class TestCostAlertManager:
    """Test the CostAlertManager class."""

    def _make_analyser_with_spend(self, model: str, cost: float) -> TrafficAnalyser:
        ta = TrafficAnalyser()
        ta.record_request(model, cost=cost)
        ta.take_snapshot(model)
        return ta

    def test_threshold_exceeded(self) -> None:
        ta = self._make_analyser_with_spend("gpt-4", 150.0)
        threshold = CostThreshold(name="daily-limit", amount=100.0, period="daily")
        mgr = CostAlertManager(ta, thresholds=[threshold])

        alerts = mgr.check()
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.WARNING
        assert "gpt-4" in alerts[0].title
        assert alerts[0].current_spend == pytest.approx(150.0)
        assert alerts[0].threshold == 100.0

    def test_threshold_not_exceeded(self) -> None:
        ta = self._make_analyser_with_spend("gpt-4", 50.0)
        threshold = CostThreshold(name="daily-limit", amount=100.0)
        mgr = CostAlertManager(ta, thresholds=[threshold])

        alerts = mgr.check()
        assert alerts == []

    def test_per_model_threshold(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", cost=200.0)
        ta.record_request("gpt-3.5-turbo", cost=10.0)
        ta.take_snapshot()

        threshold = CostThreshold(
            name="gpt4-limit",
            amount=100.0,
            model="gpt-4",
            severity=AlertSeverity.CRITICAL,
        )
        mgr = CostAlertManager(ta, thresholds=[threshold])

        alerts = mgr.check()
        assert len(alerts) == 1
        assert alerts[0].model == "gpt-4"
        assert alerts[0].severity == AlertSeverity.CRITICAL

    def test_deduplication(self) -> None:
        ta = self._make_analyser_with_spend("gpt-4", 150.0)
        threshold = CostThreshold(name="daily-limit", amount=100.0)
        mgr = CostAlertManager(ta, thresholds=[threshold])

        alerts1 = mgr.check()
        assert len(alerts1) == 1

        # Same check should NOT fire again (dedup)
        alerts2 = mgr.check()
        assert alerts2 == []

    def test_clear_fired_allows_re_fire(self) -> None:
        ta = self._make_analyser_with_spend("gpt-4", 150.0)
        threshold = CostThreshold(name="daily-limit", amount=100.0)
        mgr = CostAlertManager(ta, thresholds=[threshold])

        mgr.check()
        mgr.clear_fired()

        alerts = mgr.check()
        assert len(alerts) == 1

    def test_disabled_threshold_ignored(self) -> None:
        ta = self._make_analyser_with_spend("gpt-4", 500.0)
        threshold = CostThreshold(name="disabled", amount=10.0, enabled=False)
        mgr = CostAlertManager(ta, thresholds=[threshold])

        alerts = mgr.check()
        assert alerts == []

    def test_add_remove_threshold(self) -> None:
        ta = TrafficAnalyser()
        mgr = CostAlertManager(ta)

        t = CostThreshold(name="new", amount=50.0)
        mgr.add_threshold(t)
        assert len(mgr.thresholds) == 1

        removed = mgr.remove_threshold("new")
        assert removed is True
        assert mgr.thresholds == []

        not_found = mgr.remove_threshold("nonexistent")
        assert not_found is False

    def test_multiple_thresholds_multiple_models(self) -> None:
        ta = TrafficAnalyser()
        ta.record_request("gpt-4", cost=200.0)
        ta.record_request("claude-3", cost=300.0)
        ta.take_snapshot()

        thresholds = [
            CostThreshold(name="low-limit", amount=100.0, severity=AlertSeverity.WARNING),
            CostThreshold(name="high-limit", amount=250.0, severity=AlertSeverity.CRITICAL),
        ]
        mgr = CostAlertManager(ta, thresholds=thresholds)

        alerts = mgr.check()
        # Both models exceed low-limit, only claude-3 exceeds high-limit
        assert len(alerts) == 3
        critical_alerts = [a for a in alerts if a.severity == AlertSeverity.CRITICAL]
        assert len(critical_alerts) == 1
        assert critical_alerts[0].model == "claude-3"

    def test_weekly_threshold(self) -> None:
        ta = self._make_analyser_with_spend("gpt-4", 500.0)
        threshold = CostThreshold(name="weekly-limit", amount=400.0, period="weekly")
        mgr = CostAlertManager(ta, thresholds=[threshold])

        alerts = mgr.check()
        assert len(alerts) == 1
        assert alerts[0].metadata["period"] == "weekly"


# ── RecommendationEngine tests ──────────────────────────────────────


class TestRecommendationEngine:
    """Test the RecommendationEngine orchestrator."""

    @pytest.fixture()
    def engine(self) -> RecommendationEngine:
        config = ScalingConfig(
            enabled=True,
            enable_cost_alerts=True,
            enable_recommendations=True,
            cost_thresholds=[
                CostThreshold(name="daily-limit", amount=100.0),
            ],
            alternative_models=[
                ModelCostProfile(
                    model="gpt-3.5-turbo",
                    input_cost_per_token=0.0000005,
                    output_cost_per_token=0.0000015,
                    quality_score=0.7,
                ),
            ],
        )
        return RecommendationEngine(config)

    def test_enabled_property(self, engine: RecommendationEngine) -> None:
        assert engine.enabled is True

    def test_config_property(self, engine: RecommendationEngine) -> None:
        assert engine.config.enabled is True

    def test_sub_components_accessible(self, engine: RecommendationEngine) -> None:
        assert engine.analyser is not None
        assert engine.optimiser is not None
        assert engine.alert_manager is not None

    def test_record_and_snapshot(self, engine: RecommendationEngine) -> None:
        engine.record_request("gpt-4", tokens=100, cost=0.01, latency_ms=200.0)
        engine.take_snapshots()

        summary = engine.analyser.get_traffic_summary()
        assert len(summary) == 1
        assert summary[0]["model"] == "gpt-4"

    def test_get_recommendations_cost(self, engine: RecommendationEngine) -> None:
        for _ in range(10):
            engine.record_request("gpt-4", tokens=100, cost=0.50, latency_ms=300.0)
        engine.take_snapshots()

        recs = engine.get_recommendations()
        cost_recs = [r for r in recs if r.rec_type == RecommendationType.MODEL_SWITCH]
        assert len(cost_recs) >= 1
        assert cost_recs[0].suggested_model == "gpt-3.5-turbo"

    def test_get_recommendations_performance(self, engine: RecommendationEngine) -> None:
        """High latency should generate a performance recommendation."""
        for _ in range(5):
            engine.record_request("gpt-4", tokens=100, cost=0.10, latency_ms=6000.0)
        engine.take_snapshots()

        recs = engine.get_recommendations()
        perf_recs = [r for r in recs if r.rec_type == RecommendationType.PERFORMANCE]
        assert len(perf_recs) == 1
        assert "latency" in perf_recs[0].description.lower()

    def test_get_recommendations_scaling(self, engine: RecommendationEngine) -> None:
        """High error rate should generate a scaling recommendation."""
        for _ in range(10):
            engine.record_request("gpt-4", tokens=50, cost=0.10, is_error=True)
        for _ in range(5):
            engine.record_request("gpt-4", tokens=50, cost=0.10)
        engine.take_snapshots()

        recs = engine.get_recommendations()
        scaling_recs = [r for r in recs if r.rec_type == RecommendationType.SCALING]
        assert len(scaling_recs) == 1
        assert "error rate" in scaling_recs[0].description.lower()

    def test_get_recommendations_disabled(self) -> None:
        config = ScalingConfig(enabled=True, enable_recommendations=False)
        eng = RecommendationEngine(config)
        eng.record_request("gpt-4", tokens=100, cost=5.00, latency_ms=6000.0)
        eng.take_snapshots()

        recs = eng.get_recommendations()
        assert recs == []

    def test_get_alerts(self, engine: RecommendationEngine) -> None:
        engine.record_request("gpt-4", cost=150.0)
        engine.take_snapshots()

        alerts = engine.get_alerts()
        assert len(alerts) == 1
        assert "daily-limit" in alerts[0].title

    def test_get_alerts_disabled(self) -> None:
        config = ScalingConfig(enabled=True, enable_cost_alerts=False)
        eng = RecommendationEngine(config)
        eng.record_request("gpt-4", cost=999.0)
        eng.take_snapshots()

        alerts = eng.get_alerts()
        assert alerts == []

    def test_get_dashboard_data(self, engine: RecommendationEngine) -> None:
        engine.record_request("gpt-4", tokens=100, cost=150.0, latency_ms=200.0)
        engine.take_snapshots()

        data = engine.get_dashboard_data()
        assert "traffic_summary" in data
        assert "recommendations" in data
        assert "alerts" in data
        assert "active_models" in data
        assert "gpt-4" in data["active_models"]
        assert len(data["alerts"]) == 1

    def test_disabled_engine(self) -> None:
        config = ScalingConfig(enabled=False)
        eng = RecommendationEngine(config)
        assert eng.enabled is False

    def test_record_error(self, engine: RecommendationEngine) -> None:
        engine.record_request("gpt-4", is_error=True)
        engine.take_snapshots()

        snaps = engine.analyser.get_snapshots("gpt-4")
        assert snaps[0].error_rate == 1.0

    def test_no_performance_rec_under_threshold(self, engine: RecommendationEngine) -> None:
        """Low latency should not generate performance recommendations."""
        engine.record_request("gpt-4", tokens=100, cost=0.10, latency_ms=200.0)
        engine.take_snapshots()

        recs = engine.get_recommendations()
        perf_recs = [r for r in recs if r.rec_type == RecommendationType.PERFORMANCE]
        assert perf_recs == []

    def test_no_scaling_rec_under_threshold(self, engine: RecommendationEngine) -> None:
        """Low error rate should not generate scaling recommendations."""
        engine.record_request("gpt-4", tokens=100, cost=0.10, is_error=False)
        engine.take_snapshots()

        recs = engine.get_recommendations()
        scaling_recs = [r for r in recs if r.rec_type == RecommendationType.SCALING]
        assert scaling_recs == []

    def test_multiple_models(self, engine: RecommendationEngine) -> None:
        engine.record_request("gpt-4", tokens=100, cost=0.50)
        engine.record_request("claude-3", tokens=50, cost=0.20)
        engine.take_snapshots()

        models = engine.analyser.get_all_models()
        assert set(models) == {"gpt-4", "claude-3"}

    def test_engine_from_config_dict(self) -> None:
        """Test creating engine from dict (as done in app.py startup)."""
        config_dict = {
            "enabled": True,
            "max_snapshots": 100,
            "cost_thresholds": [{"name": "test", "amount": 50.0}],
            "alternative_models": [
                {"model": "cheap", "input_cost_per_token": 0.0001},
            ],
        }
        config = ScalingConfig(**config_dict)
        eng = RecommendationEngine(config)
        assert eng.enabled is True
        assert len(eng.alert_manager.thresholds) == 1
        assert len(eng.optimiser.alternatives) == 1
