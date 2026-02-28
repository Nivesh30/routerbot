"""Model benchmarking and Pareto-optimal comparison.

Runs evaluation suites across multiple models, aggregates results,
identifies cost-vs-quality Pareto-optimal models, and provides
recommendation rankings.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from routerbot.evaluation.metrics import compute_metric
from routerbot.evaluation.models import (
    EvalResult,
    EvalRun,
    EvalSample,
    EvalStatus,
    EvalSuite,
    EvalSummary,
    ParetoPoint,
)


class Benchmark:
    """Model benchmarking engine.

    Parameters
    ----------
    handler:
        An async callable ``(model, messages, **kwargs) -> str`` that sends
        a request to the LLM backend and returns the text response.
        If *None*, the benchmark runs in dry-run mode (no inference).
    cost_estimator:
        An optional callable ``(model_id, input_tokens, output_tokens) -> float``
        that estimates cost for a given request.  Defaults to zero cost.
    """

    def __init__(
        self,
        handler: Any = None,
        cost_estimator: Any = None,
    ) -> None:
        self._handler = handler
        self._cost_estimator = cost_estimator
        self._suites: dict[str, EvalSuite] = {}
        self._runs: dict[str, EvalRun] = {}

    # ------------------------------------------------------------------
    # Suite management
    # ------------------------------------------------------------------

    def create_suite(
        self,
        *,
        name: str,
        description: str = "",
        samples: list[EvalSample] | None = None,
        metrics: list[str] | None = None,
    ) -> EvalSuite:
        """Create a new evaluation suite."""
        from routerbot.evaluation.models import MetricType

        suite = EvalSuite(
            suite_id=str(uuid.uuid4()),
            name=name,
            description=description,
            samples=samples or [],
            metrics=[MetricType(m) for m in (metrics or ["bleu", "rouge_1"])],
            created_at=datetime.now(tz=UTC),
        )
        self._suites[suite.suite_id] = suite
        return suite

    def get_suite(self, suite_id: str) -> EvalSuite | None:
        return self._suites.get(suite_id)

    def list_suites(self) -> list[EvalSuite]:
        return list(self._suites.values())

    def delete_suite(self, suite_id: str) -> bool:
        return self._suites.pop(suite_id, None) is not None

    def add_samples(self, suite_id: str, samples: list[EvalSample]) -> int:
        """Add samples to a suite. Returns new sample count."""
        suite = self._suites.get(suite_id)
        if suite is None:
            msg = f"Suite not found: {suite_id}"
            raise KeyError(msg)
        suite.samples.extend(samples)
        return len(suite.samples)

    # ------------------------------------------------------------------
    # Benchmark execution
    # ------------------------------------------------------------------

    async def run(
        self,
        suite_id: str,
        model_ids: list[str],
    ) -> EvalRun:
        """Run a benchmark: evaluate all models on all samples in a suite.

        Returns an :class:`EvalRun` with aggregated results.
        """
        suite = self._suites.get(suite_id)
        if suite is None:
            msg = f"Suite not found: {suite_id}"
            raise KeyError(msg)

        run = EvalRun(
            run_id=str(uuid.uuid4()),
            suite_id=suite_id,
            model_ids=list(model_ids),
            status=EvalStatus.RUNNING,
            started_at=datetime.now(tz=UTC),
        )
        self._runs[run.run_id] = run

        try:
            for model_id in model_ids:
                for sample in suite.samples:
                    result = await self._evaluate_sample(
                        model_id=model_id,
                        sample=sample,
                        metrics=[m.value for m in suite.metrics],
                    )
                    run.results.append(result)

            run.status = EvalStatus.COMPLETED
        except Exception as exc:
            run.status = EvalStatus.FAILED
            run.metadata["error"] = str(exc)
        finally:
            run.completed_at = datetime.now(tz=UTC)

        # Build summary
        run.summary = self._build_summary(run)
        return run

    async def _evaluate_sample(
        self,
        *,
        model_id: str,
        sample: EvalSample,
        metrics: list[str],
    ) -> EvalResult:
        """Evaluate a single sample against a model."""
        result = EvalResult(
            sample_id=sample.sample_id,
            model_id=model_id,
        )

        # Get model response
        if self._handler is not None:
            messages = sample.input_messages or [{"role": "user", "content": sample.expected_output}]
            try:
                result.actual_output = await self._handler(model_id, messages)
            except Exception as exc:
                result.error = str(exc)
                return result
        else:
            # Dry-run mode: use expected output as actual (perfect score)
            result.actual_output = sample.expected_output

        # Compute metrics
        for metric_name in metrics:
            try:
                score = compute_metric(metric_name, sample.expected_output, result.actual_output)
                result.scores[metric_name] = score
            except ValueError:
                result.scores[metric_name] = 0.0

        # Estimate cost
        if self._cost_estimator is not None:
            result.cost = self._cost_estimator(model_id, result.input_tokens, result.output_tokens)

        return result

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary(run: EvalRun) -> dict[str, Any]:
        """Build per-model summary from run results."""
        summaries: dict[str, EvalSummary] = {}
        for r in run.results:
            if r.model_id not in summaries:
                summaries[r.model_id] = EvalSummary(model_id=r.model_id)
            s = summaries[r.model_id]
            s.sample_count += 1
            s.total_cost += r.cost
            s.average_latency_ms += r.latency_ms
            if r.error:
                s.error_count += 1
            for metric, score in r.scores.items():
                s.average_scores[metric] = s.average_scores.get(metric, 0.0) + score

        # Convert sums to averages
        for s in summaries.values():
            if s.sample_count > 0:
                s.average_latency_ms /= s.sample_count
                for m in s.average_scores:
                    s.average_scores[m] /= s.sample_count

        return {mid: s.model_dump() for mid, s in summaries.items()}

    def get_run(self, run_id: str) -> EvalRun | None:
        return self._runs.get(run_id)

    def list_runs(self, suite_id: str | None = None) -> list[EvalRun]:
        runs = list(self._runs.values())
        if suite_id:
            runs = [r for r in runs if r.suite_id == suite_id]
        return runs

    # ------------------------------------------------------------------
    # Pareto analysis
    # ------------------------------------------------------------------

    def pareto_frontier(
        self,
        run_id: str,
        quality_metric: str = "bleu",
    ) -> list[ParetoPoint]:
        """Compute the cost-vs-quality Pareto frontier for a completed run.

        Returns a list of :class:`ParetoPoint` objects, one per model,
        with ``is_pareto_optimal`` set for models on the frontier.
        """
        run = self._runs.get(run_id)
        if run is None:
            msg = f"Run not found: {run_id}"
            raise KeyError(msg)

        # Gather per-model quality & cost
        points: list[ParetoPoint] = []
        for model_id in run.model_ids:
            model_summary = run.summary.get(model_id, {})
            avg_scores = model_summary.get("average_scores", {})
            quality = avg_scores.get(quality_metric, 0.0)
            sample_count = model_summary.get("sample_count", 1) or 1
            cost = model_summary.get("total_cost", 0.0) / sample_count

            points.append(
                ParetoPoint(
                    model_id=model_id,
                    quality_score=quality,
                    cost_per_sample=cost,
                )
            )

        # Mark Pareto-optimal points (no other point dominates)
        for p in points:
            p.is_pareto_optimal = not any(
                other.quality_score >= p.quality_score
                and other.cost_per_sample <= p.cost_per_sample
                and (other.quality_score > p.quality_score or other.cost_per_sample < p.cost_per_sample)
                for other in points
                if other.model_id != p.model_id
            )

        return sorted(points, key=lambda p: p.quality_score, reverse=True)

    def recommend(
        self,
        run_id: str,
        quality_metric: str = "bleu",
        *,
        budget: float | None = None,
        min_quality: float | None = None,
    ) -> list[ParetoPoint]:
        """Recommend models, optionally filtered by budget or min quality.

        Returns Pareto-optimal models sorted by quality (descending).
        """
        frontier = self.pareto_frontier(run_id, quality_metric)
        recommendations = [p for p in frontier if p.is_pareto_optimal]

        if budget is not None:
            recommendations = [p for p in recommendations if p.cost_per_sample <= budget]
        if min_quality is not None:
            recommendations = [p for p in recommendations if p.quality_score >= min_quality]

        return sorted(recommendations, key=lambda p: p.quality_score, reverse=True)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "suites": len(self._suites),
            "runs": len(self._runs),
            "completed_runs": sum(1 for r in self._runs.values() if r.status == EvalStatus.COMPLETED),
        }
