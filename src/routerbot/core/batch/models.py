"""Pydantic models for the batch processing module."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Job & Batch status enums
# ---------------------------------------------------------------------------


class JobStatus(StrEnum):
    """Status of an individual async job."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class BatchStatus(StrEnum):
    """Status of a batch of jobs."""

    VALIDATING = "validating"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Priority(StrEnum):
    """Job priority levels."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ---------------------------------------------------------------------------
# Async Job models
# ---------------------------------------------------------------------------


class AsyncJobRequest(BaseModel):
    """A request submitted for async processing."""

    model: str = Field(..., description="Model identifier (e.g. 'openai/gpt-4o')")
    messages: list[dict[str, Any]] = Field(default_factory=list, description="Chat messages")
    parameters: dict[str, Any] = Field(default_factory=dict, description="Extra model parameters")
    priority: Priority = Field(default=Priority.MEDIUM, description="Job priority")
    callback_url: str | None = Field(default=None, description="Webhook to call when complete")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")
    ttl_seconds: int = Field(default=3600, gt=0, description="Time-to-live before expiry")


class AsyncJob(BaseModel):
    """An async job with full status tracking."""

    job_id: str = Field(..., description="Unique job identifier")
    status: JobStatus = Field(default=JobStatus.PENDING)
    request: AsyncJobRequest = Field(...)
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str = ""
    attempts: int = 0
    max_attempts: int = 3
    worker_id: str = ""


class AsyncJobResult(BaseModel):
    """Result returned when polling for a job."""

    job_id: str = ""
    status: JobStatus = JobStatus.PENDING
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: datetime | None = None
    completed_at: datetime | None = None
    progress: float = 0.0


# ---------------------------------------------------------------------------
# Batch API models (OpenAI-compatible)
# ---------------------------------------------------------------------------


class BatchRequest(BaseModel):
    """A single request within a batch (OpenAI Batch API format)."""

    custom_id: str = Field(..., description="User-provided identifier for this request")
    method: str = Field(default="POST")
    url: str = Field(default="/v1/chat/completions")
    body: dict[str, Any] = Field(default_factory=dict, description="Request body")


class BatchRequestResult(BaseModel):
    """Result for a single request in a batch."""

    custom_id: str = ""
    status_code: int = 200
    body: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class Batch(BaseModel):
    """A batch of requests with progress tracking."""

    batch_id: str = Field(..., description="Unique batch identifier")
    status: BatchStatus = Field(default=BatchStatus.VALIDATING)
    total_requests: int = 0
    completed_requests: int = 0
    failed_requests: int = 0
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    results: list[BatchRequestResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    input_requests: list[BatchRequest] = Field(default_factory=list)

    @property
    def progress(self) -> float:
        """Return completion progress as a fraction 0.0-1.0."""
        if self.total_requests == 0:
            return 0.0
        return (self.completed_requests + self.failed_requests) / self.total_requests


# ---------------------------------------------------------------------------
# Queue & Worker configuration
# ---------------------------------------------------------------------------


class QueueConfig(BaseModel):
    """Configuration for the async job queue."""

    max_pending_jobs: int = Field(default=10000, ge=1, description="Max pending jobs in queue")
    max_batch_size: int = Field(default=1000, ge=1, description="Max requests per batch")
    worker_count: int = Field(default=4, ge=1, description="Number of background workers")
    job_ttl_seconds: int = Field(default=3600, gt=0, description="Default TTL for jobs")
    retry_max_attempts: int = Field(default=3, ge=1, description="Max retry attempts per job")
    retry_delay_seconds: float = Field(default=1.0, gt=0, description="Base delay between retries")
    priority_weights: dict[str, int] = Field(
        default_factory=lambda: {"high": 3, "medium": 2, "low": 1},
        description="Scheduling weight per priority.",
    )


class BatchConfig(BaseModel):
    """Top-level batch processing configuration."""

    enabled: bool = Field(default=False)
    queue: QueueConfig = Field(default_factory=QueueConfig)
