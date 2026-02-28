"""Pydantic models for the evaluation module."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MetricType(StrEnum):
    """Built-in evaluation metric types."""

    BLEU = "bleu"
    ROUGE_1 = "rouge_1"
    ROUGE_2 = "rouge_2"
    ROUGE_L = "rouge_l"
    EXACT_MATCH = "exact_match"
    CONTAINS = "contains"
    SIMILARITY = "similarity"
    LLM_JUDGE = "llm_judge"
    CUSTOM = "custom"


class EvalStatus(StrEnum):
    """Status of an evaluation run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RegressionSeverity(StrEnum):
    """Severity level of a detected regression."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Evaluation data
# ---------------------------------------------------------------------------


class EvalSample(BaseModel):
    """A single evaluation sample (input + expected output)."""

    sample_id: str = Field(default="")
    input_messages: list[dict[str, Any]] = Field(default_factory=list)
    expected_output: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class EvalResult(BaseModel):
    """Result of evaluating one sample against one model."""

    sample_id: str = ""
    model_id: str = ""
    actual_output: str = ""
    scores: dict[str, float] = Field(default_factory=dict, description="metric_name → score")
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    error: str = ""


class EvalSuite(BaseModel):
    """A collection of evaluation samples (benchmark suite)."""

    suite_id: str = Field(default="")
    name: str = Field(default="")
    description: str = Field(default="")
    samples: list[EvalSample] = Field(default_factory=list)
    metrics: list[MetricType] = Field(default_factory=list)
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalRun(BaseModel):
    """A complete evaluation run (suite x models)."""

    run_id: str = Field(default="")
    suite_id: str = Field(default="")
    model_ids: list[str] = Field(default_factory=list)
    status: EvalStatus = Field(default=EvalStatus.PENDING)
    results: list[EvalResult] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalSummary(BaseModel):
    """Aggregated scores for one model in an evaluation run."""

    model_id: str = ""
    sample_count: int = 0
    average_scores: dict[str, float] = Field(default_factory=dict)
    average_latency_ms: float = 0.0
    total_cost: float = 0.0
    error_count: int = 0


# ---------------------------------------------------------------------------
# LLM-as-Judge
# ---------------------------------------------------------------------------


class JudgeCriteria(BaseModel):
    """Criteria for LLM-as-judge evaluation."""

    name: str = Field(..., description="Criteria name (e.g. 'helpfulness')")
    description: str = Field(default="")
    scale_min: float = Field(default=1.0)
    scale_max: float = Field(default=5.0)
    weight: float = Field(default=1.0, gt=0)


class JudgeConfig(BaseModel):
    """Configuration for LLM-as-judge evaluation."""

    judge_model: str = Field(default="openai/gpt-4o", description="Model to use as judge")
    criteria: list[JudgeCriteria] = Field(default_factory=list)
    system_prompt: str = Field(
        default="You are an impartial evaluator. Score the response on a 1-5 scale.",
    )
    temperature: float = Field(default=0.0)


class JudgeVerdict(BaseModel):
    """Verdict from an LLM-as-judge evaluation."""

    sample_id: str = ""
    model_id: str = ""
    scores: dict[str, float] = Field(default_factory=dict, description="criteria_name → score")
    reasoning: str = ""
    judge_model: str = ""


# ---------------------------------------------------------------------------
# Regression detection
# ---------------------------------------------------------------------------


class RegressionAlert(BaseModel):
    """Alert for a detected quality regression."""

    alert_id: str = ""
    model_id: str = ""
    metric: str = ""
    severity: RegressionSeverity = RegressionSeverity.WARNING
    baseline_score: float = 0.0
    current_score: float = 0.0
    delta: float = 0.0
    delta_percent: float = 0.0
    message: str = ""
    detected_at: datetime | None = None


class RegressionConfig(BaseModel):
    """Configuration for regression detection."""

    enabled: bool = Field(default=True)
    warning_threshold: float = Field(default=0.05, ge=0, description="Score drop % to trigger warning")
    critical_threshold: float = Field(default=0.15, ge=0, description="Score drop % to trigger critical alert")
    min_samples: int = Field(default=10, ge=1, description="Min samples before alerting")


# ---------------------------------------------------------------------------
# Model comparison
# ---------------------------------------------------------------------------


class BenchmarkResult(BaseModel):
    """Result of benchmarking a model on a suite."""

    model_id: str = ""
    suite_id: str = ""
    average_scores: dict[str, float] = Field(default_factory=dict)
    average_latency_ms: float = 0.0
    total_cost: float = 0.0
    sample_count: int = 0
    cost_per_sample: float = 0.0


class ParetoPoint(BaseModel):
    """A point on the cost-quality Pareto frontier."""

    model_id: str = ""
    quality_score: float = 0.0
    cost_per_sample: float = 0.0
    is_pareto_optimal: bool = False


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class EvalConfig(BaseModel):
    """Top-level evaluation configuration."""

    enabled: bool = Field(default=False)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    regression: RegressionConfig = Field(default_factory=RegressionConfig)
    max_suites: int = Field(default=100, ge=1)
    max_samples_per_suite: int = Field(default=1000, ge=1)
