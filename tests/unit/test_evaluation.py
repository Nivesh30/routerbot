"""Unit tests for the evaluation module (Task 8I).

Covers: models, metrics, LLM-as-judge, regression detection, benchmarking & Pareto.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    """Pydantic model validation tests."""

    def test_metric_type_values(self) -> None:
        from routerbot.evaluation.models import MetricType

        assert MetricType.BLEU == "bleu"
        assert MetricType.ROUGE_1 == "rouge_1"
        assert MetricType.LLM_JUDGE == "llm_judge"

    def test_eval_status_values(self) -> None:
        from routerbot.evaluation.models import EvalStatus

        assert EvalStatus.PENDING == "pending"
        assert EvalStatus.COMPLETED == "completed"

    def test_regression_severity_values(self) -> None:
        from routerbot.evaluation.models import RegressionSeverity

        assert RegressionSeverity.INFO == "info"
        assert RegressionSeverity.CRITICAL == "critical"

    def test_eval_sample_defaults(self) -> None:
        from routerbot.evaluation.models import EvalSample

        s = EvalSample()
        assert s.sample_id == ""
        assert s.input_messages == []
        assert s.expected_output == ""
        assert s.tags == []

    def test_eval_result_defaults(self) -> None:
        from routerbot.evaluation.models import EvalResult

        r = EvalResult()
        assert r.scores == {}
        assert r.latency_ms == 0.0
        assert r.error == ""

    def test_eval_suite_defaults(self) -> None:
        from routerbot.evaluation.models import EvalSuite

        s = EvalSuite()
        assert s.suite_id == ""
        assert s.samples == []
        assert s.metrics == []
        assert s.created_at is None

    def test_eval_run_defaults(self) -> None:
        from routerbot.evaluation.models import EvalRun, EvalStatus

        r = EvalRun()
        assert r.status == EvalStatus.PENDING
        assert r.results == []
        assert r.summary == {}

    def test_eval_summary_defaults(self) -> None:
        from routerbot.evaluation.models import EvalSummary

        s = EvalSummary()
        assert s.model_id == ""
        assert s.average_scores == {}
        assert s.total_cost == 0.0

    def test_judge_criteria_required_name(self) -> None:
        from routerbot.evaluation.models import JudgeCriteria

        c = JudgeCriteria(name="helpfulness")
        assert c.name == "helpfulness"
        assert c.scale_min == 1.0
        assert c.scale_max == 5.0
        assert c.weight == 1.0

    def test_judge_criteria_weight_must_be_positive(self) -> None:
        from pydantic import ValidationError

        from routerbot.evaluation.models import JudgeCriteria

        with pytest.raises(ValidationError):
            JudgeCriteria(name="bad", weight=0)

    def test_judge_config_defaults(self) -> None:
        from routerbot.evaluation.models import JudgeConfig

        cfg = JudgeConfig()
        assert cfg.judge_model == "openai/gpt-4o"
        assert cfg.temperature == 0.0
        assert cfg.criteria == []

    def test_judge_verdict_defaults(self) -> None:
        from routerbot.evaluation.models import JudgeVerdict

        v = JudgeVerdict()
        assert v.scores == {}
        assert v.reasoning == ""

    def test_regression_alert_defaults(self) -> None:
        from routerbot.evaluation.models import RegressionAlert, RegressionSeverity

        a = RegressionAlert()
        assert a.severity == RegressionSeverity.WARNING
        assert a.delta == 0.0

    def test_regression_config_defaults(self) -> None:
        from routerbot.evaluation.models import RegressionConfig

        cfg = RegressionConfig()
        assert cfg.enabled is True
        assert cfg.warning_threshold == 0.05
        assert cfg.critical_threshold == 0.15
        assert cfg.min_samples == 10

    def test_benchmark_result_defaults(self) -> None:
        from routerbot.evaluation.models import BenchmarkResult

        b = BenchmarkResult()
        assert b.model_id == ""
        assert b.cost_per_sample == 0.0

    def test_pareto_point_defaults(self) -> None:
        from routerbot.evaluation.models import ParetoPoint

        p = ParetoPoint()
        assert p.is_pareto_optimal is False

    def test_eval_config_defaults(self) -> None:
        from routerbot.evaluation.models import EvalConfig

        cfg = EvalConfig()
        assert cfg.enabled is False
        assert cfg.max_suites == 100
        assert cfg.max_samples_per_suite == 1000


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    """Built-in metric tests."""

    def test_bleu_identical(self) -> None:
        from routerbot.evaluation.metrics import bleu_score

        score = bleu_score("the cat sat on the mat", "the cat sat on the mat")
        assert score == pytest.approx(1.0)

    def test_bleu_empty_candidate(self) -> None:
        from routerbot.evaluation.metrics import bleu_score

        assert bleu_score("hello world", "") == 0.0

    def test_bleu_empty_reference(self) -> None:
        from routerbot.evaluation.metrics import bleu_score

        assert bleu_score("", "hello world") == 0.0

    def test_bleu_partial_overlap(self) -> None:
        from routerbot.evaluation.metrics import bleu_score

        score = bleu_score("the cat sat on the mat", "the cat is on the mat")
        assert 0.0 < score < 1.0

    def test_bleu_no_brevity_penalty(self) -> None:
        from routerbot.evaluation.metrics import bleu_score

        short = "cat"
        ref = "the cat sat on the mat"
        with_bp = bleu_score(ref, short, brevity_penalty=True)
        without_bp = bleu_score(ref, short, brevity_penalty=False)
        assert without_bp >= with_bp

    def test_rouge1_identical(self) -> None:
        from routerbot.evaluation.metrics import rouge_score

        result = rouge_score("hello world", "hello world", variant="rouge_1")
        assert result["f1"] == pytest.approx(1.0)
        assert result["precision"] == pytest.approx(1.0)
        assert result["recall"] == pytest.approx(1.0)

    def test_rouge2_identical(self) -> None:
        from routerbot.evaluation.metrics import rouge_score

        result = rouge_score("hello beautiful world", "hello beautiful world", variant="rouge_2")
        assert result["f1"] == pytest.approx(1.0)

    def test_rouge_l_identical(self) -> None:
        from routerbot.evaluation.metrics import rouge_score

        result = rouge_score("the quick brown fox", "the quick brown fox", variant="rouge_l")
        assert result["f1"] == pytest.approx(1.0)

    def test_rouge_l_partial(self) -> None:
        from routerbot.evaluation.metrics import rouge_score

        result = rouge_score("the quick brown fox", "the slow brown fox", variant="rouge_l")
        assert 0.0 < result["f1"] < 1.0

    def test_rouge_empty(self) -> None:
        from routerbot.evaluation.metrics import rouge_score

        result = rouge_score("hello", "", variant="rouge_1")
        assert result["f1"] == 0.0

    def test_rouge_unknown_variant(self) -> None:
        from routerbot.evaluation.metrics import rouge_score

        with pytest.raises(ValueError, match="Unknown ROUGE variant"):
            rouge_score("a", "b", variant="rouge_99")

    def test_cosine_similarity_identical(self) -> None:
        from routerbot.evaluation.metrics import cosine_similarity

        assert cosine_similarity("hello world", "hello world") == pytest.approx(1.0)

    def test_cosine_similarity_empty(self) -> None:
        from routerbot.evaluation.metrics import cosine_similarity

        assert cosine_similarity("", "hello") == 0.0

    def test_cosine_similarity_no_overlap(self) -> None:
        from routerbot.evaluation.metrics import cosine_similarity

        assert cosine_similarity("cat dog", "apple banana") == 0.0

    def test_cosine_similarity_partial(self) -> None:
        from routerbot.evaluation.metrics import cosine_similarity

        score = cosine_similarity("the cat sat", "the dog sat")
        assert 0.0 < score < 1.0

    def test_exact_match_true(self) -> None:
        from routerbot.evaluation.metrics import exact_match

        assert exact_match("Hello", "hello") == 1.0

    def test_exact_match_case_sensitive(self) -> None:
        from routerbot.evaluation.metrics import exact_match

        assert exact_match("Hello", "hello", case_sensitive=True) == 0.0
        assert exact_match("Hello", "Hello", case_sensitive=True) == 1.0

    def test_contains_match_true(self) -> None:
        from routerbot.evaluation.metrics import contains_match

        assert contains_match("world", "hello world") == 1.0

    def test_contains_match_false(self) -> None:
        from routerbot.evaluation.metrics import contains_match

        assert contains_match("xyz", "hello world") == 0.0

    def test_compute_metric_bleu(self) -> None:
        from routerbot.evaluation.metrics import compute_metric

        score = compute_metric("bleu", "hello world", "hello world")
        assert score == pytest.approx(1.0)

    def test_compute_metric_rouge_1(self) -> None:
        from routerbot.evaluation.metrics import compute_metric

        score = compute_metric("rouge_1", "hello world", "hello world")
        assert score == pytest.approx(1.0)

    def test_compute_metric_exact_match(self) -> None:
        from routerbot.evaluation.metrics import compute_metric

        assert compute_metric("exact_match", "test", "test") == 1.0
        assert compute_metric("exact_match", "test", "other") == 0.0

    def test_compute_metric_contains(self) -> None:
        from routerbot.evaluation.metrics import compute_metric

        assert compute_metric("contains", "test", "this is a test") == 1.0

    def test_compute_metric_similarity(self) -> None:
        from routerbot.evaluation.metrics import compute_metric

        score = compute_metric("similarity", "hello world", "hello world")
        assert score == pytest.approx(1.0)

    def test_compute_metric_unknown(self) -> None:
        from routerbot.evaluation.metrics import compute_metric

        with pytest.raises(ValueError, match="Unknown metric"):
            compute_metric("nonexistent", "a", "b")


# ---------------------------------------------------------------------------
# LLM Judge
# ---------------------------------------------------------------------------


class TestLLMJudge:
    """LLM-as-judge evaluator tests."""

    async def test_evaluate_no_handler(self) -> None:
        from routerbot.evaluation.llm_judge import LLMJudge
        from routerbot.evaluation.models import JudgeConfig

        judge = LLMJudge(config=JudgeConfig())
        verdict = await judge.evaluate(input_text="hi", candidate="hello")
        assert verdict.judge_model == "openai/gpt-4o"
        assert verdict.scores == {}

    async def test_evaluate_with_handler(self) -> None:
        from routerbot.evaluation.llm_judge import LLMJudge
        from routerbot.evaluation.models import JudgeConfig, JudgeCriteria

        async def mock_handler(model: str, messages: list, **kwargs: object) -> str:
            return '{"scores": {"helpfulness": 4.5}, "reasoning": "Good answer"}'

        config = JudgeConfig(
            criteria=[JudgeCriteria(name="helpfulness")],
        )
        judge = LLMJudge(config=config, handler=mock_handler)
        verdict = await judge.evaluate(
            sample_id="s1",
            model_id="m1",
            input_text="question",
            candidate="answer",
            reference="expected",
        )
        assert verdict.scores["helpfulness"] == pytest.approx(4.5)
        assert verdict.reasoning == "Good answer"
        assert verdict.sample_id == "s1"
        assert verdict.model_id == "m1"

    async def test_evaluate_clamps_scores(self) -> None:
        from routerbot.evaluation.llm_judge import LLMJudge
        from routerbot.evaluation.models import JudgeConfig, JudgeCriteria

        async def mock_handler(model: str, messages: list, **kwargs: object) -> str:
            return '{"scores": {"quality": 10.0}, "reasoning": "Over max"}'

        config = JudgeConfig(
            criteria=[JudgeCriteria(name="quality", scale_min=1.0, scale_max=5.0)],
        )
        judge = LLMJudge(config=config, handler=mock_handler)
        verdict = await judge.evaluate(input_text="q", candidate="a")
        assert verdict.scores["quality"] == 5.0  # Clamped to max

    async def test_evaluate_bad_json(self) -> None:
        from routerbot.evaluation.llm_judge import LLMJudge
        from routerbot.evaluation.models import JudgeConfig, JudgeCriteria

        async def mock_handler(model: str, messages: list, **kwargs: object) -> str:
            return "This is not JSON at all"

        config = JudgeConfig(
            criteria=[JudgeCriteria(name="quality")],
        )
        judge = LLMJudge(config=config, handler=mock_handler)
        verdict = await judge.evaluate(input_text="q", candidate="a")
        assert verdict.scores == {}
        assert "not JSON" in verdict.reasoning

    async def test_evaluate_batch(self) -> None:
        from routerbot.evaluation.llm_judge import LLMJudge
        from routerbot.evaluation.models import JudgeConfig, JudgeCriteria

        async def mock_handler(model: str, messages: list, **kwargs: object) -> str:
            return '{"scores": {"quality": 3.0}, "reasoning": "ok"}'

        config = JudgeConfig(criteria=[JudgeCriteria(name="quality")])
        judge = LLMJudge(config=config, handler=mock_handler)
        items = [
            {"input_text": "q1", "candidate": "a1", "sample_id": "s1"},
            {"input_text": "q2", "candidate": "a2", "sample_id": "s2"},
        ]
        results = await judge.evaluate_batch(items)
        assert len(results) == 2
        assert results[0].sample_id == "s1"
        assert results[1].sample_id == "s2"

    async def test_weighted_score(self) -> None:
        from routerbot.evaluation.llm_judge import LLMJudge
        from routerbot.evaluation.models import JudgeConfig, JudgeCriteria

        config = JudgeConfig(
            criteria=[
                JudgeCriteria(name="a", scale_min=0.0, scale_max=10.0, weight=2.0),
                JudgeCriteria(name="b", scale_min=0.0, scale_max=10.0, weight=1.0),
            ],
        )
        judge = LLMJudge(config=config)

        from routerbot.evaluation.models import JudgeVerdict

        # a=10 (normalized 1.0), b=5 (normalized 0.5)
        # weighted = (1.0*2 + 0.5*1) / 3 = 2.5 / 3 ≈ 0.833
        verdict = JudgeVerdict(scores={"a": 10.0, "b": 5.0})
        score = judge.weighted_score(verdict)
        assert score == pytest.approx(2.5 / 3.0)

    async def test_weighted_score_empty(self) -> None:
        from routerbot.evaluation.llm_judge import LLMJudge

        judge = LLMJudge()

        from routerbot.evaluation.models import JudgeVerdict

        verdict = JudgeVerdict()
        assert judge.weighted_score(verdict) == 0.0

    async def test_history(self) -> None:
        from routerbot.evaluation.llm_judge import LLMJudge

        judge = LLMJudge()
        await judge.evaluate(input_text="q", candidate="a")
        assert len(judge.history) == 1
        judge.clear_history()
        assert len(judge.history) == 0

    async def test_evaluate_with_reference(self) -> None:
        """Ensure reference text is included in the judge prompt."""
        from routerbot.evaluation.llm_judge import LLMJudge
        from routerbot.evaluation.models import JudgeConfig

        captured: list[list] = []

        async def mock_handler(model: str, messages: list, **kwargs: object) -> str:
            captured.append(messages)
            return "{}"

        judge = LLMJudge(config=JudgeConfig(), handler=mock_handler)
        await judge.evaluate(
            input_text="question",
            candidate="answer",
            reference="golden answer",
        )
        assert len(captured) == 1
        user_msg = captured[0][1]["content"]
        assert "golden answer" in user_msg


# ---------------------------------------------------------------------------
# Regression Detector
# ---------------------------------------------------------------------------


class TestRegressionDetector:
    """Regression detection tests."""

    def test_no_alert_below_min_samples(self) -> None:
        from routerbot.evaluation.regression import RegressionDetector

        detector = RegressionDetector()
        # min_samples=10, only add 5
        for _ in range(5):
            detector.record("m1", "bleu", 0.9)
        alert = detector.check("m1", "bleu", 0.5)
        assert alert is None

    def test_no_alert_when_disabled(self) -> None:
        from routerbot.evaluation.models import RegressionConfig
        from routerbot.evaluation.regression import RegressionDetector

        cfg = RegressionConfig(enabled=False)
        detector = RegressionDetector(config=cfg)
        for _ in range(20):
            detector.record("m1", "bleu", 0.9)
        alert = detector.check("m1", "bleu", 0.1)
        assert alert is None

    def test_no_alert_when_score_improves(self) -> None:
        from routerbot.evaluation.models import RegressionConfig
        from routerbot.evaluation.regression import RegressionDetector

        cfg = RegressionConfig(min_samples=3)
        detector = RegressionDetector(config=cfg)
        for _ in range(5):
            detector.record("m1", "bleu", 0.5)
        alert = detector.check("m1", "bleu", 0.9)  # Better than baseline
        assert alert is None

    def test_warning_alert(self) -> None:
        from routerbot.evaluation.models import RegressionConfig, RegressionSeverity
        from routerbot.evaluation.regression import RegressionDetector

        cfg = RegressionConfig(
            min_samples=3,
            warning_threshold=0.05,
            critical_threshold=0.15,
        )
        detector = RegressionDetector(config=cfg)
        for _ in range(5):
            detector.record("m1", "bleu", 1.0)
        # Drop of 10% → warning
        alert = detector.check("m1", "bleu", 0.9)
        assert alert is not None
        assert alert.severity == RegressionSeverity.WARNING
        assert alert.baseline_score == pytest.approx(1.0)
        assert alert.current_score == pytest.approx(0.9)

    def test_critical_alert(self) -> None:
        from routerbot.evaluation.models import RegressionConfig, RegressionSeverity
        from routerbot.evaluation.regression import RegressionDetector

        cfg = RegressionConfig(min_samples=3, critical_threshold=0.15)
        detector = RegressionDetector(config=cfg)
        for _ in range(5):
            detector.record("m1", "bleu", 1.0)
        # Drop of 30% → critical
        alert = detector.check("m1", "bleu", 0.7)
        assert alert is not None
        assert alert.severity == RegressionSeverity.CRITICAL

    def test_no_alert_within_threshold(self) -> None:
        from routerbot.evaluation.models import RegressionConfig
        from routerbot.evaluation.regression import RegressionDetector

        cfg = RegressionConfig(min_samples=3, warning_threshold=0.05)
        detector = RegressionDetector(config=cfg)
        for _ in range(5):
            detector.record("m1", "bleu", 1.0)
        # Drop of 2% → below warning threshold
        alert = detector.check("m1", "bleu", 0.98)
        assert alert is None

    def test_check_all(self) -> None:
        from routerbot.evaluation.models import RegressionConfig
        from routerbot.evaluation.regression import RegressionDetector

        cfg = RegressionConfig(min_samples=3, warning_threshold=0.05)
        detector = RegressionDetector(config=cfg)
        for _ in range(5):
            detector.record_batch("m1", {"bleu": 1.0, "rouge_1": 0.8})
        alerts = detector.check_all("m1", {"bleu": 0.5, "rouge_1": 0.7})
        # bleu dropped 50% → alert, rouge_1 dropped 12.5% → alert
        assert len(alerts) == 2

    def test_record_batch(self) -> None:
        from routerbot.evaluation.regression import RegressionDetector

        detector = RegressionDetector()
        detector.record_batch("m1", {"bleu": 0.9, "rouge_1": 0.8})
        assert detector.history_for("m1", "bleu") == [0.9]
        assert detector.history_for("m1", "rouge_1") == [0.8]

    def test_baseline(self) -> None:
        from routerbot.evaluation.regression import RegressionDetector

        detector = RegressionDetector()
        detector.record("m1", "bleu", 0.8)
        detector.record("m1", "bleu", 1.0)
        assert detector.baseline("m1", "bleu") == pytest.approx(0.9)
        assert detector.baseline("m1", "unknown") is None
        assert detector.baseline("unknown", "bleu") is None

    def test_alerts_for_model(self) -> None:
        from routerbot.evaluation.models import RegressionConfig
        from routerbot.evaluation.regression import RegressionDetector

        cfg = RegressionConfig(min_samples=2, warning_threshold=0.05)
        detector = RegressionDetector(config=cfg)
        for _ in range(3):
            detector.record("m1", "bleu", 1.0)
            detector.record("m2", "bleu", 1.0)
        detector.check("m1", "bleu", 0.5)
        detector.check("m2", "bleu", 0.5)
        assert len(detector.alerts_for_model("m1")) == 1
        assert len(detector.alerts_for_model("m2")) == 1

    def test_clear_history(self) -> None:
        from routerbot.evaluation.regression import RegressionDetector

        detector = RegressionDetector()
        detector.record("m1", "bleu", 0.9)
        detector.record("m2", "bleu", 0.8)
        detector.clear_history("m1")
        assert detector.history_for("m1", "bleu") == []
        assert detector.history_for("m2", "bleu") == [0.8]
        detector.clear_history()
        assert detector.history_for("m2", "bleu") == []

    def test_clear_alerts(self) -> None:
        from routerbot.evaluation.models import RegressionConfig
        from routerbot.evaluation.regression import RegressionDetector

        cfg = RegressionConfig(min_samples=2, warning_threshold=0.05)
        detector = RegressionDetector(config=cfg)
        for _ in range(3):
            detector.record("m1", "bleu", 1.0)
        detector.check("m1", "bleu", 0.5)
        assert len(detector.alerts) == 1
        detector.clear_alerts()
        assert len(detector.alerts) == 0

    def test_stats(self) -> None:
        from routerbot.evaluation.models import RegressionConfig
        from routerbot.evaluation.regression import RegressionDetector

        cfg = RegressionConfig(min_samples=2, warning_threshold=0.05)
        detector = RegressionDetector(config=cfg)
        for _ in range(3):
            detector.record("m1", "bleu", 1.0)
        detector.check("m1", "bleu", 0.5)
        s = detector.stats()
        assert s["models_tracked"] == 1
        assert s["total_observations"] == 3
        assert s["total_alerts"] == 1

    def test_baseline_zero_no_alert(self) -> None:
        from routerbot.evaluation.models import RegressionConfig
        from routerbot.evaluation.regression import RegressionDetector

        cfg = RegressionConfig(min_samples=2)
        detector = RegressionDetector(config=cfg)
        for _ in range(3):
            detector.record("m1", "bleu", 0.0)
        alert = detector.check("m1", "bleu", 0.0)
        assert alert is None


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


class TestBenchmark:
    """Benchmarking and Pareto analysis tests."""

    def test_create_suite(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark

        bench = Benchmark()
        suite = bench.create_suite(name="test", description="A test suite")
        assert suite.name == "test"
        assert suite.suite_id != ""
        assert len(suite.metrics) == 2  # default: bleu + rouge_1

    def test_create_suite_custom_metrics(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark

        bench = Benchmark()
        suite = bench.create_suite(name="custom", metrics=["exact_match", "contains"])
        assert len(suite.metrics) == 2

    def test_get_suite(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark

        bench = Benchmark()
        suite = bench.create_suite(name="test")
        assert bench.get_suite(suite.suite_id) is suite
        assert bench.get_suite("nonexistent") is None

    def test_list_suites(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark

        bench = Benchmark()
        bench.create_suite(name="a")
        bench.create_suite(name="b")
        assert len(bench.list_suites()) == 2

    def test_delete_suite(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark

        bench = Benchmark()
        suite = bench.create_suite(name="test")
        assert bench.delete_suite(suite.suite_id) is True
        assert bench.delete_suite(suite.suite_id) is False

    def test_add_samples(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark
        from routerbot.evaluation.models import EvalSample

        bench = Benchmark()
        suite = bench.create_suite(name="test")
        samples = [EvalSample(sample_id="s1", expected_output="hello")]
        count = bench.add_samples(suite.suite_id, samples)
        assert count == 1

    def test_add_samples_missing_suite(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark
        from routerbot.evaluation.models import EvalSample

        bench = Benchmark()
        with pytest.raises(KeyError, match="Suite not found"):
            bench.add_samples("bad_id", [EvalSample()])

    async def test_run_dry_mode(self) -> None:
        """Dry-run: no handler → actual_output = expected_output → perfect scores."""
        from routerbot.evaluation.benchmark import Benchmark
        from routerbot.evaluation.models import EvalSample, EvalStatus

        bench = Benchmark()
        suite = bench.create_suite(name="dry")
        bench.add_samples(
            suite.suite_id,
            [
                EvalSample(sample_id="s1", expected_output="the cat sat on the mat"),
                EvalSample(sample_id="s2", expected_output="hello world"),
            ],
        )
        run = await bench.run(suite.suite_id, ["model_a"])
        assert run.status == EvalStatus.COMPLETED
        assert len(run.results) == 2
        # Dry-run copies expected → actual, so BLEU should be 1.0
        for r in run.results:
            assert r.scores["bleu"] == pytest.approx(1.0)

    async def test_run_with_handler(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark
        from routerbot.evaluation.models import EvalSample, EvalStatus

        async def handler(model: str, messages: list, **kw: object) -> str:
            return "the cat sat on the mat"

        bench = Benchmark(handler=handler)
        suite = bench.create_suite(name="test")
        bench.add_samples(
            suite.suite_id,
            [
                EvalSample(sample_id="s1", expected_output="the cat sat on the mat"),
            ],
        )
        run = await bench.run(suite.suite_id, ["m1"])
        assert run.status == EvalStatus.COMPLETED
        assert run.results[0].scores["bleu"] == pytest.approx(1.0)

    async def test_run_handler_error(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark
        from routerbot.evaluation.models import EvalSample, EvalStatus

        async def handler(model: str, messages: list, **kw: object) -> str:
            msg = "API error"
            raise RuntimeError(msg)

        bench = Benchmark(handler=handler)
        suite = bench.create_suite(name="test")
        bench.add_samples(
            suite.suite_id,
            [
                EvalSample(sample_id="s1", expected_output="hello"),
            ],
        )
        run = await bench.run(suite.suite_id, ["m1"])
        # Errors are captured per-sample, run still completes
        assert run.status == EvalStatus.COMPLETED
        assert run.results[0].error == "API error"

    async def test_run_missing_suite(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark

        bench = Benchmark()
        with pytest.raises(KeyError, match="Suite not found"):
            await bench.run("bad_id", ["m1"])

    async def test_get_and_list_runs(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark
        from routerbot.evaluation.models import EvalSample

        bench = Benchmark()
        suite = bench.create_suite(name="test")
        bench.add_samples(
            suite.suite_id,
            [
                EvalSample(sample_id="s1", expected_output="hello"),
            ],
        )
        run = await bench.run(suite.suite_id, ["m1"])
        assert bench.get_run(run.run_id) is run
        assert len(bench.list_runs()) == 1
        assert len(bench.list_runs(suite_id=suite.suite_id)) == 1
        assert len(bench.list_runs(suite_id="other")) == 0

    async def test_summary_has_model_scores(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark
        from routerbot.evaluation.models import EvalSample

        bench = Benchmark()
        suite = bench.create_suite(name="test")
        bench.add_samples(
            suite.suite_id,
            [
                EvalSample(sample_id="s1", expected_output="hello world"),
            ],
        )
        run = await bench.run(suite.suite_id, ["m1", "m2"])
        assert "m1" in run.summary
        assert "m2" in run.summary
        assert run.summary["m1"]["average_scores"]["bleu"] == pytest.approx(1.0)

    async def test_pareto_frontier(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark
        from routerbot.evaluation.models import EvalSample

        def cost_est(model_id: str, inp: int, out: int) -> float:
            costs = {"cheap": 0.001, "expensive": 0.01}
            return costs.get(model_id, 0.005)

        bench = Benchmark(cost_estimator=cost_est)
        suite = bench.create_suite(name="pareto")
        bench.add_samples(
            suite.suite_id,
            [
                EvalSample(sample_id="s1", expected_output="hello world"),
            ],
        )
        run = await bench.run(suite.suite_id, ["cheap", "expensive"])
        frontier = bench.pareto_frontier(run.run_id, quality_metric="bleu")
        assert len(frontier) == 2
        # Both have same quality (dry-run perfect), so cheaper one is Pareto optimal
        for p in frontier:
            if p.model_id == "cheap":
                assert p.is_pareto_optimal is True

    async def test_pareto_missing_run(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark

        bench = Benchmark()
        with pytest.raises(KeyError, match="Run not found"):
            bench.pareto_frontier("bad_id")

    async def test_recommend_with_budget(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark
        from routerbot.evaluation.models import EvalSample

        def cost_est(model_id: str, inp: int, out: int) -> float:
            return {"cheap": 0.001, "expensive": 1.0}.get(model_id, 0.5)

        bench = Benchmark(cost_estimator=cost_est)
        suite = bench.create_suite(name="rec")
        bench.add_samples(
            suite.suite_id,
            [
                EvalSample(sample_id="s1", expected_output="hello"),
            ],
        )
        run = await bench.run(suite.suite_id, ["cheap", "expensive"])
        recs = bench.recommend(run.run_id, budget=0.01)
        # Only cheap model is within budget
        model_ids = [r.model_id for r in recs]
        assert "cheap" in model_ids
        assert "expensive" not in model_ids

    async def test_recommend_with_min_quality(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark
        from routerbot.evaluation.models import EvalSample

        bench = Benchmark()
        suite = bench.create_suite(name="rec")
        bench.add_samples(
            suite.suite_id,
            [
                EvalSample(sample_id="s1", expected_output="hello"),
            ],
        )
        run = await bench.run(suite.suite_id, ["m1"])
        recs = bench.recommend(run.run_id, min_quality=0.5)
        # Dry-run → perfect score = 1.0 → should pass min_quality=0.5
        assert len(recs) == 1

    def test_stats(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark

        bench = Benchmark()
        bench.create_suite(name="a")
        s = bench.stats()
        assert s["suites"] == 1
        assert s["runs"] == 0

    async def test_run_multiple_models(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark
        from routerbot.evaluation.models import EvalSample

        bench = Benchmark()
        suite = bench.create_suite(name="multi")
        bench.add_samples(
            suite.suite_id,
            [
                EvalSample(sample_id="s1", expected_output="hello"),
                EvalSample(sample_id="s2", expected_output="world"),
            ],
        )
        run = await bench.run(suite.suite_id, ["m1", "m2", "m3"])
        # 3 models x 2 samples = 6 results
        assert len(run.results) == 6

    async def test_cost_estimator(self) -> None:
        from routerbot.evaluation.benchmark import Benchmark
        from routerbot.evaluation.models import EvalSample

        def cost_est(model_id: str, inp: int, out: int) -> float:
            return 0.05

        bench = Benchmark(cost_estimator=cost_est)
        suite = bench.create_suite(name="cost")
        bench.add_samples(
            suite.suite_id,
            [
                EvalSample(sample_id="s1", expected_output="hello"),
            ],
        )
        run = await bench.run(suite.suite_id, ["m1"])
        assert run.results[0].cost == pytest.approx(0.05)
        assert run.summary["m1"]["total_cost"] == pytest.approx(0.05)
