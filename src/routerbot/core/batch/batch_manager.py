"""Batch request manager.

Manages OpenAI-compatible batch jobs that group multiple requests
into a single batch for efficient processing.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from routerbot.core.batch.models import (
    Batch,
    BatchRequest,
    BatchRequestResult,
    BatchStatus,
    QueueConfig,
)

logger = logging.getLogger(__name__)


class BatchManager:
    """Manage batch processing of grouped requests.

    Parameters
    ----------
    config:
        Queue/batch configuration.
    handler:
        Async callable ``(method, url, body) -> (status_code, body)``
        that processes a single request from the batch.
    """

    def __init__(
        self,
        config: QueueConfig | None = None,
        handler: Any = None,
    ) -> None:
        self.config = config or QueueConfig()
        self._handler = handler or _default_handler
        self._batches: dict[str, Batch] = {}
        self._lock = asyncio.Lock()

    async def create_batch(
        self,
        requests: list[BatchRequest],
        *,
        metadata: dict[str, str] | None = None,
    ) -> Batch:
        """Create a new batch from a list of requests.

        Parameters
        ----------
        requests:
            The batch requests (OpenAI-compatible format).
        metadata:
            Optional metadata key-value pairs.

        Returns
        -------
        Batch
            The newly created batch object.

        Raises
        ------
        BatchValidationError
            If validation fails (empty, too large, duplicate custom_ids).
        """
        if not requests:
            raise BatchValidationError("Batch must contain at least one request")

        if len(requests) > self.config.max_batch_size:
            raise BatchValidationError(
                f"Batch too large: {len(requests)} > {self.config.max_batch_size}"
            )

        # Check for duplicate custom_ids
        custom_ids = [r.custom_id for r in requests]
        if len(custom_ids) != len(set(custom_ids)):
            raise BatchValidationError("Duplicate custom_id values in batch")

        batch_id = f"batch_{uuid.uuid4().hex[:16]}"
        now = datetime.now(tz=UTC)

        batch = Batch(
            batch_id=batch_id,
            status=BatchStatus.IN_PROGRESS,
            total_requests=len(requests),
            created_at=now,
            metadata=metadata or {},
            input_requests=requests,
        )

        async with self._lock:
            self._batches[batch_id] = batch

        logger.info("Batch %s created with %d requests", batch_id, len(requests))
        return batch

    async def execute_batch(self, batch_id: str, *, concurrency: int = 5) -> Batch:
        """Execute all requests in a batch.

        Parameters
        ----------
        batch_id:
            The batch to execute.
        concurrency:
            Maximum concurrent requests.

        Returns
        -------
        Batch
            The batch with updated results and status.

        Raises
        ------
        BatchNotFoundError
            If batch_id is not found.
        """
        batch = self._batches.get(batch_id)
        if batch is None:
            raise BatchNotFoundError(f"Batch {batch_id} not found")

        if batch.status not in (BatchStatus.IN_PROGRESS, BatchStatus.VALIDATING):
            return batch

        semaphore = asyncio.Semaphore(concurrency)

        async def _process_one(request: BatchRequest) -> BatchRequestResult:
            async with semaphore:
                try:
                    status_code, body = await self._handler(
                        request.method, request.url, request.body
                    )
                    return BatchRequestResult(
                        custom_id=request.custom_id,
                        status_code=status_code,
                        body=body,
                    )
                except Exception as exc:
                    return BatchRequestResult(
                        custom_id=request.custom_id,
                        status_code=500,
                        body={},
                        error=str(exc),
                    )

        tasks = [_process_one(r) for r in batch.input_requests]
        results = await asyncio.gather(*tasks)

        completed = 0
        failed = 0
        for res in results:
            batch.results.append(res)
            if res.error:
                failed += 1
                batch.errors.append(res.error)
            else:
                completed += 1

        batch.completed_requests = completed
        batch.failed_requests = failed
        batch.completed_at = datetime.now(tz=UTC)

        if failed == batch.total_requests:
            batch.status = BatchStatus.FAILED
        elif failed > 0:
            batch.status = BatchStatus.COMPLETED  # partial success
        else:
            batch.status = BatchStatus.COMPLETED

        logger.info(
            "Batch %s finished: %d completed, %d failed",
            batch_id,
            completed,
            failed,
        )
        return batch

    def get_batch(self, batch_id: str) -> Batch | None:
        """Retrieve a batch by ID."""
        return self._batches.get(batch_id)

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a batch.  Returns True if cancelled."""
        batch = self._batches.get(batch_id)
        if batch is None:
            return False
        if batch.status in (
            BatchStatus.COMPLETED,
            BatchStatus.FAILED,
            BatchStatus.CANCELLED,
        ):
            return False
        batch.status = BatchStatus.CANCELLED
        batch.completed_at = datetime.now(tz=UTC)
        return True

    def list_batches(
        self,
        *,
        status: BatchStatus | None = None,
        limit: int = 100,
    ) -> list[Batch]:
        """List batches, optionally filtered by status."""
        batches = list(self._batches.values())
        if status is not None:
            batches = [b for b in batches if b.status == status]
        # Sort newest first
        batches.sort(key=lambda b: b.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return batches[:limit]

    def stats(self) -> dict[str, Any]:
        """Return batch processing statistics."""
        counts: dict[str, int] = {s.value: 0 for s in BatchStatus}
        total_requests = 0
        completed_requests = 0
        failed_requests = 0

        for batch in self._batches.values():
            counts[batch.status.value] += 1
            total_requests += batch.total_requests
            completed_requests += batch.completed_requests
            failed_requests += batch.failed_requests

        return {
            "batches": counts,
            "total_batches": len(self._batches),
            "total_requests": total_requests,
            "completed_requests": completed_requests,
            "failed_requests": failed_requests,
        }


async def _default_handler(
    method: str, url: str, body: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    """Default no-op handler that returns 200 for all requests."""
    return 200, {"status": "ok", "method": method, "url": url}


class BatchValidationError(Exception):
    """Raised when batch validation fails."""


class BatchNotFoundError(Exception):
    """Raised when a batch is not found."""
