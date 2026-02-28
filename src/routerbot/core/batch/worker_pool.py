"""Background worker pool for processing async jobs.

Workers pull jobs from the queue, execute them via a handler,
and report results back.  Supports retry with exponential backoff,
callback webhooks on completion, and graceful shutdown.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from routerbot.core.batch.job_queue import JobQueue  # noqa: TC001
from routerbot.core.batch.models import AsyncJob, JobStatus, QueueConfig

logger = logging.getLogger(__name__)


class JobHandler(Protocol):
    """Protocol for job execution handlers."""

    async def __call__(self, job: AsyncJob) -> dict[str, Any]: ...


class WorkerPool:
    """Pool of async workers that process jobs from a queue.

    Parameters
    ----------
    queue:
        The job queue to pull work from.
    handler:
        Async callable that processes a job and returns a result dict.
    config:
        Queue configuration (worker count, retry settings).
    """

    def __init__(
        self,
        queue: JobQueue,
        handler: JobHandler | None = None,
        config: QueueConfig | None = None,
    ) -> None:
        self.queue = queue
        self._handler = handler or _default_handler
        self.config = config or QueueConfig()
        self._workers: list[asyncio.Task[None]] = []
        self._running = False
        self._http_client: httpx.AsyncClient | None = None
        self._poll_interval: float = 0.5

    async def start(self) -> None:
        """Start the worker pool."""
        if self._running:
            return
        self._running = True
        self._http_client = httpx.AsyncClient(timeout=30)
        for i in range(self.config.worker_count):
            task = asyncio.create_task(self._worker_loop(i))
            self._workers.append(task)
        logger.info("Worker pool started with %d workers", self.config.worker_count)

    async def stop(self) -> None:
        """Gracefully stop the worker pool."""
        self._running = False
        # Wait for workers to finish current iteration
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        logger.info("Worker pool stopped")

    @property
    def is_running(self) -> bool:
        """Whether the pool is currently running."""
        return self._running

    @property
    def worker_count(self) -> int:
        """Number of active workers."""
        return len(self._workers)

    async def _worker_loop(self, worker_id: int) -> None:
        """Main loop for a single worker."""
        logger.debug("Worker %d starting", worker_id)
        while self._running:
            job = await self.queue.take()
            if job is None:
                await asyncio.sleep(self._poll_interval)
                continue

            job.worker_id = f"worker-{worker_id}"
            try:
                result = await self._handler(job)
                self.queue.complete(job.job_id, result)
                # Fire callback if configured
                await self._fire_callback(job, result)
            except Exception as exc:
                error_msg = f"{type(exc).__name__}: {exc}"
                self.queue.fail(job.job_id, error_msg)
                # If re-queued for retry, add backoff delay
                updated_job = self.queue.get_job(job.job_id)
                if updated_job and updated_job.status == JobStatus.PENDING:
                    delay = self.config.retry_delay_seconds * (2 ** (updated_job.attempts - 1))
                    delay = min(delay, 60.0)  # Cap at 60s
                    await asyncio.sleep(delay)

        logger.debug("Worker %d stopped", worker_id)

    async def _fire_callback(self, job: AsyncJob, result: dict[str, Any]) -> None:
        """POST callback webhook when a job completes."""
        if not job.request.callback_url:
            return
        if self._http_client is None:
            return

        payload = {
            "job_id": job.job_id,
            "status": job.status.value,
            "result": result,
            "completed_at": datetime.now(tz=UTC).isoformat(),
        }
        try:
            resp = await self._http_client.post(job.request.callback_url, json=payload)
            logger.info(
                "Callback for job %s sent to %s (status=%d)",
                job.job_id,
                job.request.callback_url,
                resp.status_code,
            )
        except Exception:
            logger.warning(
                "Callback for job %s to %s failed",
                job.job_id,
                job.request.callback_url,
                exc_info=True,
            )

    async def process_one(self, job: AsyncJob) -> dict[str, Any]:
        """Process a single job synchronously (for testing)."""
        return await self._handler(job)


async def _default_handler(job: AsyncJob) -> dict[str, Any]:
    """Default no-op handler that echoes the request."""
    return {
        "job_id": job.job_id,
        "model": job.request.model,
        "response": "default handler - no real LLM call",
    }
