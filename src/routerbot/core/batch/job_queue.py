"""Priority-aware async job queue.

Manages job lifecycle from submission through completion, with
priority scheduling, TTL expiration, and capacity limits.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from routerbot.core.batch.models import (
    AsyncJob,
    AsyncJobRequest,
    AsyncJobResult,
    JobStatus,
    Priority,
    QueueConfig,
)

logger = logging.getLogger(__name__)

# Priority ordering: HIGH < MEDIUM < LOW (lower = higher priority)
_PRIORITY_ORDER: dict[Priority, int] = {
    Priority.HIGH: 0,
    Priority.MEDIUM: 1,
    Priority.LOW: 2,
}


class JobQueue:
    """Priority-aware async job queue.

    Jobs are stored in-memory and scheduled by priority.  A real
    deployment would back this with Redis or a database.

    Parameters
    ----------
    config:
        Queue configuration.
    """

    def __init__(self, config: QueueConfig | None = None) -> None:
        self.config = config or QueueConfig()
        self._jobs: dict[str, AsyncJob] = {}
        self._pending: asyncio.PriorityQueue[tuple[int, float, str]] = asyncio.PriorityQueue()
        self._lock = asyncio.Lock()

    async def submit(self, request: AsyncJobRequest) -> AsyncJob:
        """Submit a new job to the queue.

        Parameters
        ----------
        request:
            The async job request.

        Returns
        -------
        AsyncJob
            The created job with a unique ID and PENDING status.

        Raises
        ------
        QueueFullError
            If the queue has reached its maximum pending capacity.
        """
        async with self._lock:
            pending_count = sum(
                1 for j in self._jobs.values() if j.status == JobStatus.PENDING
            )
            if pending_count >= self.config.max_pending_jobs:
                raise QueueFullError(
                    f"Queue full: {pending_count}/{self.config.max_pending_jobs} pending jobs"
                )

            job_id = f"job_{uuid.uuid4().hex[:16]}"
            now = datetime.now(tz=UTC)

            job = AsyncJob(
                job_id=job_id,
                status=JobStatus.PENDING,
                request=request,
                created_at=now,
                max_attempts=self.config.retry_max_attempts,
            )
            self._jobs[job_id] = job

            priority_order = _PRIORITY_ORDER.get(request.priority, 1)
            await self._pending.put((priority_order, now.timestamp(), job_id))

            logger.info("Job %s submitted (priority=%s)", job_id, request.priority)
            return job

    async def take(self) -> AsyncJob | None:
        """Take the next job from the queue for processing.

        Returns the highest-priority pending job, or None if the
        queue is empty.
        """
        try:
            _, _, job_id = self._pending.get_nowait()
        except asyncio.QueueEmpty:
            return None

        job = self._jobs.get(job_id)
        if job is None or job.status != JobStatus.PENDING:
            return None

        job.status = JobStatus.IN_PROGRESS
        job.started_at = datetime.now(tz=UTC)
        job.attempts += 1
        return job

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        """Mark a job as completed with a result."""
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.status = JobStatus.COMPLETED
        job.result = result
        job.completed_at = datetime.now(tz=UTC)
        logger.info("Job %s completed", job_id)

    def fail(self, job_id: str, error: str) -> None:
        """Mark a job as failed.

        If the job has remaining retry attempts, it is re-queued as
        PENDING instead of being marked as FAILED.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return

        if job.attempts < job.max_attempts:
            # Re-queue for retry
            job.status = JobStatus.PENDING
            job.error = error
            priority_order = _PRIORITY_ORDER.get(job.request.priority, 1)
            now = datetime.now(tz=UTC).timestamp()
            try:
                self._pending.put_nowait((priority_order, now, job_id))
            except asyncio.QueueFull:
                job.status = JobStatus.FAILED
                job.error = error
            logger.info("Job %s retry %d/%d", job_id, job.attempts, job.max_attempts)
        else:
            job.status = JobStatus.FAILED
            job.error = error
            job.completed_at = datetime.now(tz=UTC)
            logger.warning("Job %s failed after %d attempts: %s", job_id, job.attempts, error)

    def cancel(self, job_id: str) -> bool:
        """Cancel a job.  Returns True if cancelled, False if not found or already done."""
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return False
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now(tz=UTC)
        return True

    def get_job(self, job_id: str) -> AsyncJob | None:
        """Retrieve a job by ID."""
        return self._jobs.get(job_id)

    def get_result(self, job_id: str) -> AsyncJobResult | None:
        """Get a poll-friendly result for a job."""
        job = self._jobs.get(job_id)
        if job is None:
            return None
        progress = 1.0 if job.status in (JobStatus.COMPLETED, JobStatus.FAILED) else 0.0
        if job.status == JobStatus.IN_PROGRESS:
            progress = 0.5
        return AsyncJobResult(
            job_id=job.job_id,
            status=job.status,
            result=job.result,
            error=job.error,
            created_at=job.created_at,
            completed_at=job.completed_at,
            progress=progress,
        )

    def expire_stale_jobs(self) -> int:
        """Expire jobs that have exceeded their TTL.

        Returns the number of jobs expired.
        """
        now = datetime.now(tz=UTC)
        expired = 0
        for job in self._jobs.values():
            if job.status not in (JobStatus.PENDING, JobStatus.IN_PROGRESS):
                continue
            if job.created_at is None:
                continue
            age = (now - job.created_at).total_seconds()
            if age > job.request.ttl_seconds:
                job.status = JobStatus.EXPIRED
                job.completed_at = now
                job.error = "Job expired (TTL exceeded)"
                expired += 1
        return expired

    def stats(self) -> dict[str, int]:
        """Return queue statistics."""
        counts: dict[str, int] = {s.value: 0 for s in JobStatus}
        for job in self._jobs.values():
            counts[job.status.value] += 1
        counts["total"] = len(self._jobs)
        return counts

    def clear(self) -> int:
        """Remove all jobs.  Returns number removed."""
        count = len(self._jobs)
        self._jobs.clear()
        # Drain the priority queue
        while not self._pending.empty():
            try:
                self._pending.get_nowait()
            except asyncio.QueueEmpty:
                break
        return count


class QueueFullError(Exception):
    """Raised when the job queue has reached capacity."""
