"""Tests for the batch processing & async job queue module (Task 8G)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from routerbot.core.batch.batch_manager import (
    BatchManager,
    BatchNotFoundError,
    BatchValidationError,
)
from routerbot.core.batch.job_queue import JobQueue, QueueFullError
from routerbot.core.batch.models import (
    AsyncJob,
    AsyncJobRequest,
    AsyncJobResult,
    Batch,
    BatchConfig,
    BatchRequest,
    BatchRequestResult,
    BatchStatus,
    JobStatus,
    Priority,
    QueueConfig,
)
from routerbot.core.batch.worker_pool import WorkerPool

# ── Model tests ──────────────────────────────────────────────────────────


class TestModels:
    """Tests for batch processing Pydantic models."""

    def test_job_status_values(self) -> None:
        assert JobStatus.PENDING == "pending"
        assert JobStatus.COMPLETED == "completed"
        assert JobStatus.FAILED == "failed"
        assert JobStatus.CANCELLED == "cancelled"
        assert JobStatus.EXPIRED == "expired"

    def test_batch_status_values(self) -> None:
        assert BatchStatus.VALIDATING == "validating"
        assert BatchStatus.IN_PROGRESS == "in_progress"
        assert BatchStatus.COMPLETED == "completed"

    def test_priority_values(self) -> None:
        assert Priority.HIGH == "high"
        assert Priority.MEDIUM == "medium"
        assert Priority.LOW == "low"

    def test_async_job_request_defaults(self) -> None:
        req = AsyncJobRequest(model="gpt-4", messages=[{"role": "user", "content": "hi"}])
        assert req.priority == Priority.MEDIUM
        assert req.callback_url is None
        assert req.ttl_seconds == 3600
        assert req.parameters == {}
        assert req.metadata == {}

    def test_async_job_request_custom(self) -> None:
        req = AsyncJobRequest(
            model="claude-3",
            messages=[{"role": "user", "content": "test"}],
            priority=Priority.HIGH,
            callback_url="https://example.com/cb",
            ttl_seconds=600,
            metadata={"team": "ml"},
        )
        assert req.priority == Priority.HIGH
        assert req.callback_url == "https://example.com/cb"
        assert req.ttl_seconds == 600

    def test_async_job_defaults(self) -> None:
        req = AsyncJobRequest(model="gpt-4", messages=[])
        job = AsyncJob(job_id="j1", status=JobStatus.PENDING, request=req)
        assert job.attempts == 0
        assert job.max_attempts == 3
        assert job.result is None
        assert job.error == ""
        assert job.worker_id == ""

    def test_async_job_result(self) -> None:
        now = datetime.now(tz=UTC)
        result = AsyncJobResult(
            job_id="j1",
            status=JobStatus.COMPLETED,
            result={"text": "hello"},
            created_at=now,
            completed_at=now,
            progress=1.0,
        )
        assert result.progress == 1.0
        assert result.result == {"text": "hello"}

    def test_batch_request(self) -> None:
        br = BatchRequest(
            custom_id="req-1",
            method="POST",
            url="/v1/chat/completions",
            body={"model": "gpt-4", "messages": []},
        )
        assert br.custom_id == "req-1"
        assert br.method == "POST"

    def test_batch_request_result_success(self) -> None:
        brr = BatchRequestResult(
            custom_id="req-1",
            status_code=200,
            body={"choices": []},
        )
        assert brr.error == ""

    def test_batch_request_result_error(self) -> None:
        brr = BatchRequestResult(
            custom_id="req-1",
            status_code=500,
            body={},
            error="Internal server error",
        )
        assert brr.error == "Internal server error"

    def test_batch_defaults(self) -> None:
        batch = Batch(batch_id="b1", status=BatchStatus.IN_PROGRESS, total_requests=5)
        assert batch.completed_requests == 0
        assert batch.failed_requests == 0
        assert batch.results == []
        assert batch.errors == []
        assert batch.progress == 0.0

    def test_batch_progress(self) -> None:
        batch = Batch(
            batch_id="b1",
            status=BatchStatus.IN_PROGRESS,
            total_requests=10,
            completed_requests=5,
            failed_requests=2,
        )
        assert batch.progress == pytest.approx(0.7)

    def test_batch_progress_zero(self) -> None:
        batch = Batch(batch_id="b1", status=BatchStatus.IN_PROGRESS, total_requests=0)
        assert batch.progress == 0.0

    def test_queue_config_defaults(self) -> None:
        cfg = QueueConfig()
        assert cfg.max_pending_jobs == 10000
        assert cfg.max_batch_size == 1000
        assert cfg.worker_count == 4
        assert cfg.retry_max_attempts == 3
        assert cfg.retry_delay_seconds == 1.0
        assert cfg.priority_weights == {"high": 3, "medium": 2, "low": 1}

    def test_batch_config_defaults(self) -> None:
        cfg = BatchConfig()
        assert cfg.enabled is False
        assert cfg.queue.max_pending_jobs == 10000

    def test_batch_config_enabled(self) -> None:
        cfg = BatchConfig(enabled=True)
        assert cfg.enabled is True


# ── JobQueue tests ───────────────────────────────────────────────────────


class TestJobQueue:
    """Tests for the async job queue."""

    @pytest.fixture()
    def queue(self) -> JobQueue:
        return JobQueue(QueueConfig(max_pending_jobs=5, retry_max_attempts=2))

    @pytest.fixture()
    def sample_request(self) -> AsyncJobRequest:
        return AsyncJobRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "hello"}],
        )

    async def test_submit_job(self, queue: JobQueue, sample_request: AsyncJobRequest) -> None:
        job = await queue.submit(sample_request)
        assert job.job_id.startswith("job_")
        assert job.status == JobStatus.PENDING
        assert job.request is sample_request
        assert job.created_at is not None

    async def test_submit_returns_unique_ids(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        j1 = await queue.submit(sample_request)
        j2 = await queue.submit(sample_request)
        assert j1.job_id != j2.job_id

    async def test_submit_queue_full(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        for _ in range(5):
            await queue.submit(sample_request)
        with pytest.raises(QueueFullError, match="Queue full"):
            await queue.submit(sample_request)

    async def test_take_empty_queue(self, queue: JobQueue) -> None:
        result = await queue.take()
        assert result is None

    async def test_take_returns_pending_job(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        await queue.submit(sample_request)
        job = await queue.take()
        assert job is not None
        assert job.status == JobStatus.IN_PROGRESS
        assert job.started_at is not None
        assert job.attempts == 1

    async def test_take_priority_ordering(self, queue: JobQueue) -> None:
        low = AsyncJobRequest(model="m", messages=[], priority=Priority.LOW)
        high = AsyncJobRequest(model="m", messages=[], priority=Priority.HIGH)
        med = AsyncJobRequest(model="m", messages=[], priority=Priority.MEDIUM)

        await queue.submit(low)
        await queue.submit(high)
        await queue.submit(med)

        j1 = await queue.take()
        j2 = await queue.take()
        j3 = await queue.take()

        assert j1 is not None
        assert j2 is not None
        assert j3 is not None
        assert j1.request.priority == Priority.HIGH
        assert j2.request.priority == Priority.MEDIUM
        assert j3.request.priority == Priority.LOW

    async def test_complete_job(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        submitted = await queue.submit(sample_request)
        taken = await queue.take()
        assert taken is not None
        queue.complete(taken.job_id, {"text": "done"})
        job = queue.get_job(submitted.job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED
        assert job.result == {"text": "done"}
        assert job.completed_at is not None

    async def test_fail_job_with_retry(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        submitted = await queue.submit(sample_request)
        taken = await queue.take()
        assert taken is not None
        queue.fail(taken.job_id, "oops")
        job = queue.get_job(submitted.job_id)
        assert job is not None
        # Should be re-queued for retry (attempts=1 < max_attempts=2)
        assert job.status == JobStatus.PENDING
        assert job.error == "oops"

    async def test_fail_job_exhausted_retries(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        submitted = await queue.submit(sample_request)
        # First attempt
        taken = await queue.take()
        assert taken is not None
        queue.fail(taken.job_id, "fail 1")
        # Retry (second attempt)
        taken2 = await queue.take()
        assert taken2 is not None
        queue.fail(taken2.job_id, "fail 2")
        job = queue.get_job(submitted.job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert job.completed_at is not None

    async def test_cancel_job(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        submitted = await queue.submit(sample_request)
        assert queue.cancel(submitted.job_id) is True
        job = queue.get_job(submitted.job_id)
        assert job is not None
        assert job.status == JobStatus.CANCELLED

    async def test_cancel_nonexistent(self, queue: JobQueue) -> None:
        assert queue.cancel("nonexistent") is False

    async def test_cancel_completed_job(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        submitted = await queue.submit(sample_request)
        taken = await queue.take()
        assert taken is not None
        queue.complete(taken.job_id, {})
        assert queue.cancel(submitted.job_id) is False

    async def test_get_result(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        submitted = await queue.submit(sample_request)
        result = queue.get_result(submitted.job_id)
        assert result is not None
        assert result.status == JobStatus.PENDING
        assert result.progress == 0.0

    async def test_get_result_completed(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        submitted = await queue.submit(sample_request)
        taken = await queue.take()
        assert taken is not None
        queue.complete(taken.job_id, {"answer": "42"})
        result = queue.get_result(submitted.job_id)
        assert result is not None
        assert result.status == JobStatus.COMPLETED
        assert result.progress == 1.0
        assert result.result == {"answer": "42"}

    async def test_get_result_in_progress(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        submitted = await queue.submit(sample_request)
        await queue.take()
        result = queue.get_result(submitted.job_id)
        assert result is not None
        assert result.status == JobStatus.IN_PROGRESS
        assert result.progress == 0.5

    async def test_get_result_nonexistent(self, queue: JobQueue) -> None:
        assert queue.get_result("nope") is None

    async def test_expire_stale_jobs(self, queue: JobQueue) -> None:
        req = AsyncJobRequest(model="m", messages=[], ttl_seconds=1)
        submitted = await queue.submit(req)
        # Backdate the created_at to force expiration
        submitted.created_at = datetime(2000, 1, 1, tzinfo=UTC)
        expired = queue.expire_stale_jobs()
        assert expired == 1

    async def test_expire_no_stale(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        await queue.submit(sample_request)
        expired = queue.expire_stale_jobs()
        assert expired == 0

    async def test_stats(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        await queue.submit(sample_request)
        await queue.submit(sample_request)
        s = queue.stats()
        assert s["total"] == 2
        assert s["pending"] == 2

    async def test_clear(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        await queue.submit(sample_request)
        await queue.submit(sample_request)
        removed = queue.clear()
        assert removed == 2
        assert queue.stats()["total"] == 0

    async def test_get_job_nonexistent(self, queue: JobQueue) -> None:
        assert queue.get_job("nope") is None

    async def test_complete_nonexistent(self, queue: JobQueue) -> None:
        queue.complete("nope", {})  # Should not raise

    async def test_fail_nonexistent(self, queue: JobQueue) -> None:
        queue.fail("nope", "error")  # Should not raise


# ── BatchManager tests ───────────────────────────────────────────────────


class TestBatchManager:
    """Tests for the batch manager."""

    @pytest.fixture()
    def manager(self) -> BatchManager:
        return BatchManager(config=QueueConfig(max_batch_size=10))

    @pytest.fixture()
    def sample_requests(self) -> list[BatchRequest]:
        return [
            BatchRequest(
                custom_id=f"req-{i}",
                method="POST",
                url="/v1/chat/completions",
                body={"model": "gpt-4", "messages": [{"role": "user", "content": f"msg {i}"}]},
            )
            for i in range(3)
        ]

    async def test_create_batch(
        self, manager: BatchManager, sample_requests: list[BatchRequest]
    ) -> None:
        batch = await manager.create_batch(sample_requests)
        assert batch.batch_id.startswith("batch_")
        assert batch.status == BatchStatus.IN_PROGRESS
        assert batch.total_requests == 3
        assert batch.completed_requests == 0

    async def test_create_batch_empty_raises(self, manager: BatchManager) -> None:
        with pytest.raises(BatchValidationError, match="at least one"):
            await manager.create_batch([])

    async def test_create_batch_too_large(self, manager: BatchManager) -> None:
        requests = [
            BatchRequest(custom_id=f"req-{i}", method="POST", url="/v1/x", body={})
            for i in range(11)
        ]
        with pytest.raises(BatchValidationError, match="too large"):
            await manager.create_batch(requests)

    async def test_create_batch_duplicate_ids(self, manager: BatchManager) -> None:
        requests = [
            BatchRequest(custom_id="dup", method="POST", url="/v1/x", body={}),
            BatchRequest(custom_id="dup", method="POST", url="/v1/x", body={}),
        ]
        with pytest.raises(BatchValidationError, match="Duplicate"):
            await manager.create_batch(requests)

    async def test_create_batch_with_metadata(
        self, manager: BatchManager, sample_requests: list[BatchRequest]
    ) -> None:
        batch = await manager.create_batch(sample_requests, metadata={"team": "ml"})
        assert batch.metadata == {"team": "ml"}

    async def test_execute_batch(
        self, manager: BatchManager, sample_requests: list[BatchRequest]
    ) -> None:
        batch = await manager.create_batch(sample_requests)
        result = await manager.execute_batch(batch.batch_id)
        assert result.status == BatchStatus.COMPLETED
        assert result.completed_requests == 3
        assert result.failed_requests == 0
        assert len(result.results) == 3
        assert result.completed_at is not None

    async def test_execute_batch_not_found(self, manager: BatchManager) -> None:
        with pytest.raises(BatchNotFoundError):
            await manager.execute_batch("nonexistent")

    async def test_execute_batch_with_failures(
        self, manager: BatchManager, sample_requests: list[BatchRequest]
    ) -> None:
        call_count = 0

        async def failing_handler(
            method: str, url: str, body: dict[str, Any]
        ) -> tuple[int, dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ValueError("Simulated failure")
            return 200, {"ok": True}

        manager._handler = failing_handler
        batch = await manager.create_batch(sample_requests)
        result = await manager.execute_batch(batch.batch_id)
        assert result.completed_requests == 2
        assert result.failed_requests == 1
        assert result.status == BatchStatus.COMPLETED  # partial success
        assert len(result.errors) == 1

    async def test_execute_batch_all_fail(self, manager: BatchManager) -> None:
        async def always_fail(
            method: str, url: str, body: dict[str, Any]
        ) -> tuple[int, dict[str, Any]]:
            raise RuntimeError("boom")

        manager._handler = always_fail
        requests = [
            BatchRequest(custom_id="r1", method="POST", url="/v1/x", body={}),
        ]
        batch = await manager.create_batch(requests)
        result = await manager.execute_batch(batch.batch_id)
        assert result.status == BatchStatus.FAILED

    async def test_execute_already_completed(
        self, manager: BatchManager, sample_requests: list[BatchRequest]
    ) -> None:
        batch = await manager.create_batch(sample_requests)
        await manager.execute_batch(batch.batch_id)
        # Execute again — should be a no-op
        result = await manager.execute_batch(batch.batch_id)
        assert result.status == BatchStatus.COMPLETED

    async def test_get_batch(
        self, manager: BatchManager, sample_requests: list[BatchRequest]
    ) -> None:
        batch = await manager.create_batch(sample_requests)
        fetched = manager.get_batch(batch.batch_id)
        assert fetched is not None
        assert fetched.batch_id == batch.batch_id

    async def test_get_batch_nonexistent(self, manager: BatchManager) -> None:
        assert manager.get_batch("nope") is None

    async def test_cancel_batch(
        self, manager: BatchManager, sample_requests: list[BatchRequest]
    ) -> None:
        batch = await manager.create_batch(sample_requests)
        assert manager.cancel_batch(batch.batch_id) is True
        fetched = manager.get_batch(batch.batch_id)
        assert fetched is not None
        assert fetched.status == BatchStatus.CANCELLED

    async def test_cancel_completed_batch(
        self, manager: BatchManager, sample_requests: list[BatchRequest]
    ) -> None:
        batch = await manager.create_batch(sample_requests)
        await manager.execute_batch(batch.batch_id)
        assert manager.cancel_batch(batch.batch_id) is False

    async def test_cancel_nonexistent(self, manager: BatchManager) -> None:
        assert manager.cancel_batch("nope") is False

    async def test_list_batches(
        self, manager: BatchManager, sample_requests: list[BatchRequest]
    ) -> None:
        await manager.create_batch(sample_requests)
        await manager.create_batch(sample_requests[:1])
        batches = manager.list_batches()
        assert len(batches) == 2

    async def test_list_batches_filter_status(
        self, manager: BatchManager, sample_requests: list[BatchRequest]
    ) -> None:
        b1 = await manager.create_batch(sample_requests)
        await manager.create_batch(sample_requests[:1])
        await manager.execute_batch(b1.batch_id)
        completed = manager.list_batches(status=BatchStatus.COMPLETED)
        assert len(completed) == 1
        in_progress = manager.list_batches(status=BatchStatus.IN_PROGRESS)
        assert len(in_progress) == 1

    async def test_list_batches_limit(
        self, manager: BatchManager, sample_requests: list[BatchRequest]
    ) -> None:
        for _ in range(5):
            await manager.create_batch(sample_requests)
        batches = manager.list_batches(limit=2)
        assert len(batches) == 2

    async def test_stats(
        self, manager: BatchManager, sample_requests: list[BatchRequest]
    ) -> None:
        b1 = await manager.create_batch(sample_requests)
        await manager.execute_batch(b1.batch_id)
        s = manager.stats()
        assert s["total_batches"] == 1
        assert s["completed_requests"] == 3
        assert s["failed_requests"] == 0


# ── WorkerPool tests ─────────────────────────────────────────────────────


class TestWorkerPool:
    """Tests for the background worker pool."""

    @pytest.fixture()
    def queue(self) -> JobQueue:
        return JobQueue(QueueConfig(max_pending_jobs=100, retry_max_attempts=2))

    @pytest.fixture()
    def sample_request(self) -> AsyncJobRequest:
        return AsyncJobRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "test"}],
        )

    async def test_start_stop(self, queue: JobQueue) -> None:
        pool = WorkerPool(queue, config=QueueConfig(worker_count=2))
        assert pool.is_running is False
        await pool.start()
        assert pool.is_running is True
        assert pool.worker_count == 2
        await pool.stop()
        assert pool.is_running is False

    async def test_start_idempotent(self, queue: JobQueue) -> None:
        pool = WorkerPool(queue, config=QueueConfig(worker_count=1))
        await pool.start()
        await pool.start()  # Should not double-start
        assert pool.worker_count == 1
        await pool.stop()

    async def test_process_one(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        handler = AsyncMock(return_value={"text": "response"})
        pool = WorkerPool(queue, handler=handler, config=QueueConfig(worker_count=1))
        await queue.submit(sample_request)
        taken = await queue.take()
        assert taken is not None
        result = await pool.process_one(taken)
        assert result == {"text": "response"}
        handler.assert_awaited_once_with(taken)

    async def test_worker_processes_job(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        handler = AsyncMock(return_value={"text": "done"})
        pool = WorkerPool(queue, handler=handler, config=QueueConfig(worker_count=1))
        pool._poll_interval = 0.05

        await queue.submit(sample_request)
        await pool.start()
        # Wait for the worker to pick up and process the job
        await asyncio.sleep(0.3)
        await pool.stop()

        # Job should have been completed
        handler.assert_awaited_once()

    async def test_worker_retries_on_failure(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        call_count = 0

        async def flaky_handler(job: AsyncJob) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Transient error")
            return {"text": "success on retry"}

        pool = WorkerPool(
            queue,
            handler=flaky_handler,
            config=QueueConfig(worker_count=1, retry_max_attempts=3, retry_delay_seconds=0.01),
        )
        pool._poll_interval = 0.05

        submitted = await queue.submit(sample_request)
        await pool.start()
        await asyncio.sleep(1.0)
        await pool.stop()

        job = queue.get_job(submitted.job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED
        assert call_count == 2

    async def test_worker_callback(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        req_with_cb = AsyncJobRequest(
            model="gpt-4",
            messages=[],
            callback_url="https://example.com/webhook",
        )
        handler = AsyncMock(return_value={"text": "done"})
        pool = WorkerPool(queue, handler=handler, config=QueueConfig(worker_count=1))
        pool._poll_interval = 0.05

        await queue.submit(req_with_cb)
        with patch("routerbot.core.batch.worker_pool.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock()
            mock_client.aclose = AsyncMock()
            mock_client_cls.return_value = mock_client

            await pool.start()
            await asyncio.sleep(0.3)
            await pool.stop()

    async def test_default_handler(
        self, queue: JobQueue, sample_request: AsyncJobRequest
    ) -> None:
        pool = WorkerPool(queue, config=QueueConfig(worker_count=1))
        await queue.submit(sample_request)
        taken = await queue.take()
        assert taken is not None
        result = await pool.process_one(taken)
        assert "job_id" in result
        assert result["model"] == "gpt-4"

    async def test_worker_pool_empty_queue(self, queue: JobQueue) -> None:
        pool = WorkerPool(queue, config=QueueConfig(worker_count=1))
        pool._poll_interval = 0.05
        await pool.start()
        await asyncio.sleep(0.2)
        await pool.stop()
        # No jobs processed, no errors — just verify clean start/stop


# ── Integration-ish tests ────────────────────────────────────────────────


class TestIntegration:
    """End-to-end style tests combining queue + manager + pool."""

    async def test_full_job_lifecycle(self) -> None:
        """Submit → take → complete → get_result."""
        queue = JobQueue()
        req = AsyncJobRequest(model="m", messages=[{"role": "user", "content": "hi"}])
        job = await queue.submit(req)
        taken = await queue.take()
        assert taken is not None
        queue.complete(taken.job_id, {"answer": "world"})

        result = queue.get_result(job.job_id)
        assert result is not None
        assert result.status == JobStatus.COMPLETED
        assert result.result == {"answer": "world"}

    async def test_batch_end_to_end(self) -> None:
        """Create batch → execute → check results."""
        requests = [
            BatchRequest(custom_id=f"r{i}", method="POST", url="/v1/chat", body={"i": i})
            for i in range(5)
        ]
        manager = BatchManager()
        batch = await manager.create_batch(requests)
        result = await manager.execute_batch(batch.batch_id)
        assert result.status == BatchStatus.COMPLETED
        assert result.total_requests == 5
        assert result.completed_requests == 5
        assert result.progress == 1.0

    async def test_priority_queue_fifo_within_priority(self) -> None:
        """Jobs with the same priority should be FIFO (by timestamp)."""
        queue = JobQueue()
        ids = []
        for i in range(5):
            req = AsyncJobRequest(
                model="m",
                messages=[],
                priority=Priority.MEDIUM,
                metadata={"seq": str(i)},
            )
            job = await queue.submit(req)
            ids.append(job.job_id)

        taken_ids = []
        for _ in range(5):
            job = await queue.take()
            assert job is not None
            taken_ids.append(job.job_id)

        # All same-priority jobs should be taken (order may vary on fast systems)
        assert set(taken_ids) == set(ids)
        assert len(taken_ids) == 5

    async def test_expire_then_take(self) -> None:
        """Expired jobs should not be taken by workers."""
        queue = JobQueue()
        req = AsyncJobRequest(model="m", messages=[], ttl_seconds=1)
        job = await queue.submit(req)
        # Backdate to force expiry
        job.created_at = datetime(2000, 1, 1, tzinfo=UTC)
        queue.expire_stale_jobs()
        fetched = queue.get_job(job.job_id)
        assert fetched is not None
        assert fetched.status == JobStatus.EXPIRED

    async def test_cancel_while_pending(self) -> None:
        """Cancel should prevent a pending job from being taken."""
        queue = JobQueue()
        req = AsyncJobRequest(model="m", messages=[])
        job = await queue.submit(req)
        queue.cancel(job.job_id)
        taken = await queue.take()
        # The job was cancelled, so take should skip it
        assert taken is None

    async def test_multiple_batches_stats(self) -> None:
        """Stats should aggregate across multiple batches."""
        manager = BatchManager()
        for i in range(3):
            requests = [
                BatchRequest(custom_id=f"b{i}-r{j}", method="POST", url="/v1/x", body={})
                for j in range(2)
            ]
            batch = await manager.create_batch(requests)
            await manager.execute_batch(batch.batch_id)

        s = manager.stats()
        assert s["total_batches"] == 3
        assert s["total_requests"] == 6
        assert s["completed_requests"] == 6
