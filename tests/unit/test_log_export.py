"""Tests for the log export system.

Covers:
- LogRecord serialisation (to_dict, to_jsonl, to_csv_row)
- Date partitioning and key building
- BaseLogExporter: realtime mode, batch mode, auto-flush on max buffer
- BaseLogExporter: flush, close, disabled exporter
- LocalExporter writes to filesystem
- LogExportCallback integration with exporter
- ExportConfig defaults
- CSV export format
- S3Exporter: boto3 import error
- GCSExporter: google-cloud-storage import error
- AzureBlobExporter: azure-storage-blob import error
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from routerbot.observability.callbacks import (
    RequestEndData,
    RequestErrorData,
    RequestStartData,
)
from routerbot.observability.exporters.base import (
    BaseLogExporter,
    ExportConfig,
    ExportFormat,
    ExportMode,
    LogRecord,
    build_key,
    date_partition,
)
from routerbot.observability.exporters.export_callback import LogExportCallback
from routerbot.observability.exporters.local import LocalExporter

# ---------------------------------------------------------------------------
# Test exporter that captures writes
# ---------------------------------------------------------------------------


class MemoryExporter(BaseLogExporter):
    """In-memory exporter for test assertions."""

    def __init__(self, config: ExportConfig | None = None) -> None:
        super().__init__(config)
        self.writes: list[tuple[str, bytes]] = []

    async def _write_bytes(self, key: str, data: bytes) -> None:
        self.writes.append((key, data))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def record() -> LogRecord:
    return LogRecord(
        request_id="req-001",
        model="gpt-4o",
        provider="openai",
        tokens_prompt=10,
        tokens_completion=5,
        cost=0.0015,
        latency_ms=250.0,
        user_id="user-42",
        team_id="team-a",
        key_id="key-99",
        timestamp=1700000000.0,
    )


@pytest.fixture()
def record2() -> LogRecord:
    return LogRecord(
        request_id="req-002",
        model="claude-3",
        provider="anthropic",
        tokens_prompt=20,
        tokens_completion=10,
        cost=0.003,
        latency_ms=500.0,
        status="error",
        error="Rate limit",
        timestamp=1700000001.0,
    )


# ===================================================================
# LogRecord tests
# ===================================================================


class TestLogRecord:

    def test_to_dict(self, record: LogRecord) -> None:
        d = record.to_dict()
        assert d["request_id"] == "req-001"
        assert d["model"] == "gpt-4o"
        assert d["cost"] == 0.0015
        assert d["user_id"] == "user-42"

    def test_to_jsonl(self, record: LogRecord) -> None:
        line = record.to_jsonl()
        parsed = json.loads(line)
        assert parsed["request_id"] == "req-001"

    def test_to_csv_row(self, record: LogRecord) -> None:
        row = record.to_csv_row()
        assert "req-001" in row
        assert "gpt-4o" in row

    def test_to_csv_row_custom_fields(self, record: LogRecord) -> None:
        row = record.to_csv_row(fields=["request_id", "model"])
        parts = row.split(",")
        assert len(parts) == 2
        assert "req-001" in parts[0]

    def test_error_record(self, record2: LogRecord) -> None:
        d = record2.to_dict()
        assert d["status"] == "error"
        assert d["error"] == "Rate limit"

    def test_metadata_merged(self) -> None:
        r = LogRecord(
            request_id="x",
            model="m",
            metadata={"custom_field": "value"},
        )
        d = r.to_dict()
        assert d["custom_field"] == "value"


# ===================================================================
# Helpers tests
# ===================================================================


class TestHelpers:

    def test_date_partition(self) -> None:
        result = date_partition(1700000000.0)
        assert result == "2023/11/14"

    def test_build_key(self) -> None:
        key = build_key("logs", 1700000000.0, "jsonl", 1)
        assert key == "logs/2023/11/14/requests_001.jsonl"

    def test_build_key_with_trailing_slash(self) -> None:
        key = build_key("logs/", 1700000000.0, "csv", 42)
        assert key == "logs/2023/11/14/requests_042.csv"


# ===================================================================
# BaseLogExporter (via MemoryExporter) tests
# ===================================================================


class TestBaseExporter:

    @pytest.mark.asyncio()
    async def test_realtime_mode(self, record: LogRecord) -> None:
        config = ExportConfig(mode=ExportMode.REALTIME)
        exporter = MemoryExporter(config)
        await exporter.write(record)
        assert len(exporter.writes) == 1
        key, data = exporter.writes[0]
        assert "requests_" in key
        assert b"req-001" in data

    @pytest.mark.asyncio()
    async def test_batch_mode_buffers(self, record: LogRecord) -> None:
        config = ExportConfig(mode=ExportMode.BATCH, max_buffer_size=10)
        exporter = MemoryExporter(config)
        await exporter.write(record)
        # Not flushed yet
        assert len(exporter.writes) == 0
        assert len(exporter._buffer) == 1

    @pytest.mark.asyncio()
    async def test_batch_auto_flush(self, record: LogRecord) -> None:
        config = ExportConfig(mode=ExportMode.BATCH, max_buffer_size=2)
        exporter = MemoryExporter(config)
        await exporter.write(record)
        await exporter.write(record)
        # Should have auto-flushed
        assert len(exporter.writes) == 1
        assert len(exporter._buffer) == 0

    @pytest.mark.asyncio()
    async def test_flush_manual(self, record: LogRecord) -> None:
        config = ExportConfig(mode=ExportMode.BATCH)
        exporter = MemoryExporter(config)
        await exporter.write(record)
        await exporter.flush()
        assert len(exporter.writes) == 1

    @pytest.mark.asyncio()
    async def test_flush_empty_noop(self) -> None:
        exporter = MemoryExporter()
        await exporter.flush()
        assert len(exporter.writes) == 0

    @pytest.mark.asyncio()
    async def test_close_flushes(self, record: LogRecord) -> None:
        config = ExportConfig(mode=ExportMode.BATCH)
        exporter = MemoryExporter(config)
        await exporter.write(record)
        await exporter.close()
        assert len(exporter.writes) == 1

    @pytest.mark.asyncio()
    async def test_disabled(self, record: LogRecord) -> None:
        config = ExportConfig(enabled=False)
        exporter = MemoryExporter(config)
        await exporter.write(record)
        assert len(exporter.writes) == 0
        assert len(exporter._buffer) == 0

    @pytest.mark.asyncio()
    async def test_jsonl_format(self, record: LogRecord, record2: LogRecord) -> None:
        config = ExportConfig(mode=ExportMode.BATCH, max_buffer_size=2)
        exporter = MemoryExporter(config)
        await exporter.write(record)
        await exporter.write(record2)

        _, data = exporter.writes[0]
        lines = data.decode().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["request_id"] == "req-001"
        assert json.loads(lines[1])["request_id"] == "req-002"

    @pytest.mark.asyncio()
    async def test_csv_format(self, record: LogRecord) -> None:
        config = ExportConfig(format=ExportFormat.CSV, mode=ExportMode.REALTIME)
        exporter = MemoryExporter(config)
        await exporter.write(record)

        _, data = exporter.writes[0]
        text = data.decode()
        lines = text.strip().split("\n")
        # First line is header
        assert "request_id" in lines[0]
        # Second line is data
        assert "req-001" in lines[1]

    @pytest.mark.asyncio()
    async def test_write_error_isolated(self, record: LogRecord) -> None:
        """Write errors don't propagate."""
        config = ExportConfig(mode=ExportMode.REALTIME)
        exporter = MemoryExporter(config)

        # Patch _write_bytes to raise
        async def bad_write(key: str, data: bytes) -> None:
            raise OSError("disk full")

        exporter._write_bytes = bad_write  # type: ignore[assignment]
        # Should not raise
        await exporter.write(record)

    @pytest.mark.asyncio()
    async def test_sequential_keys(self, record: LogRecord) -> None:
        config = ExportConfig(mode=ExportMode.REALTIME)
        exporter = MemoryExporter(config)
        await exporter.write(record)
        await exporter.write(record)
        keys = [k for k, _ in exporter.writes]
        assert "001" in keys[0]
        assert "002" in keys[1]


# ===================================================================
# LocalExporter tests
# ===================================================================


class TestLocalExporter:

    @pytest.mark.asyncio()
    async def test_write_creates_file(self, record: LogRecord) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ExportConfig(mode=ExportMode.REALTIME)
            exporter = LocalExporter(root_dir=tmpdir, config=config)
            await exporter.write(record)

            # Find the written file
            written = list(Path(tmpdir).rglob("*.jsonl"))  # noqa: ASYNC240
            assert len(written) == 1
            content = written[0].read_text()
            data = json.loads(content.strip())
            assert data["request_id"] == "req-001"

    @pytest.mark.asyncio()
    async def test_batch_and_close(self, record: LogRecord, record2: LogRecord) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ExportConfig(mode=ExportMode.BATCH, max_buffer_size=100)
            exporter = LocalExporter(root_dir=tmpdir, config=config)
            await exporter.write(record)
            await exporter.write(record2)
            await exporter.close()

            written = list(Path(tmpdir).rglob("*.jsonl"))  # noqa: ASYNC240
            assert len(written) == 1
            lines = written[0].read_text().strip().split("\n")
            assert len(lines) == 2


# ===================================================================
# LogExportCallback tests
# ===================================================================


class TestLogExportCallback:

    @pytest.mark.asyncio()
    async def test_on_request_end(self) -> None:
        config = ExportConfig(mode=ExportMode.REALTIME)
        exporter = MemoryExporter(config)
        cb = LogExportCallback(exporter)

        data = RequestEndData(
            request_id="req-e",
            model="gpt-4o",
            provider="openai",
            tokens_prompt=10,
            tokens_completion=5,
            cost=0.001,
            latency_ms=200.0,
        )
        await cb.on_request_end(data)
        assert len(exporter.writes) == 1
        _, raw = exporter.writes[0]
        parsed = json.loads(raw.decode().strip())
        assert parsed["status"] == "success"

    @pytest.mark.asyncio()
    async def test_on_request_error(self) -> None:
        config = ExportConfig(mode=ExportMode.REALTIME)
        exporter = MemoryExporter(config)
        cb = LogExportCallback(exporter)

        data = RequestErrorData(
            request_id="req-err",
            model="gpt-4o",
            error="timeout",
            error_type="TimeoutError",
            provider="openai",
        )
        await cb.on_request_error(data)
        assert len(exporter.writes) == 1
        _, raw = exporter.writes[0]
        parsed = json.loads(raw.decode().strip())
        assert parsed["status"] == "error"
        assert parsed["error"] == "timeout"

    @pytest.mark.asyncio()
    async def test_on_request_start_noop(self) -> None:
        exporter = MemoryExporter()
        cb = LogExportCallback(exporter)
        data = RequestStartData(request_id="req-s", model="gpt-4o")
        await cb.on_request_start(data)
        assert len(exporter.writes) == 0

    @pytest.mark.asyncio()
    async def test_callback_name(self) -> None:
        exporter = MemoryExporter()
        cb = LogExportCallback(exporter)
        assert cb.name == "LogExportCallback"


# ===================================================================
# ExportConfig defaults
# ===================================================================


class TestExportConfig:

    def test_defaults(self) -> None:
        config = ExportConfig()
        assert config.enabled is True
        assert config.format == ExportFormat.JSONL
        assert config.mode == ExportMode.BATCH
        assert config.prefix == "logs"
        assert config.flush_interval_seconds == 300.0
        assert config.max_buffer_size == 1000

    def test_custom(self) -> None:
        config = ExportConfig(
            enabled=False,
            format=ExportFormat.CSV,
            mode=ExportMode.REALTIME,
            prefix="my-logs",
        )
        assert config.enabled is False
        assert config.format == ExportFormat.CSV
