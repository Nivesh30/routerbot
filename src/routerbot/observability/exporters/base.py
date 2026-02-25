"""Base log exporter interface and shared utilities.

All log exporters inherit from :class:`BaseLogExporter` and implement
the ``write`` and ``close`` methods.  Records are serialised as JSON
Lines (``*.jsonl``) or CSV, and exported to date-partitioned paths::

    logs/2026/02/22/requests_001.jsonl

Export modes:

- **Real-time** — each log record is written immediately.
- **Batch** — records are buffered and flushed on a schedule.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums / config
# ---------------------------------------------------------------------------


class ExportFormat(StrEnum):
    """Supported export file formats."""

    JSONL = "jsonl"
    CSV = "csv"


class ExportMode(StrEnum):
    """How log records are written to storage."""

    REALTIME = "realtime"
    BATCH = "batch"


@dataclass
class ExportConfig:
    """Configuration for a log exporter."""

    enabled: bool = True
    format: ExportFormat = ExportFormat.JSONL
    mode: ExportMode = ExportMode.BATCH
    prefix: str = "logs"
    flush_interval_seconds: float = 300.0  # 5 minutes
    max_buffer_size: int = 1000


# ---------------------------------------------------------------------------
# Record type
# ---------------------------------------------------------------------------


@dataclass
class LogRecord:
    """A single log record to export."""

    request_id: str
    model: str
    provider: str = ""
    tokens_prompt: int = 0
    tokens_completion: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    status: str = "success"  # "success" | "error"
    error: str | None = None
    user_id: str | None = None
    team_id: str | None = None
    key_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a flat dictionary for serialisation."""
        return {
            "request_id": self.request_id,
            "model": self.model,
            "provider": self.provider,
            "tokens_prompt": self.tokens_prompt,
            "tokens_completion": self.tokens_completion,
            "cost": self.cost,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "error": self.error,
            "user_id": self.user_id,
            "team_id": self.team_id,
            "key_id": self.key_id,
            "timestamp": self.timestamp,
            **self.metadata,
        }

    def to_jsonl(self) -> str:
        """Serialise as a single JSON line (no trailing newline)."""
        return json.dumps(self.to_dict(), default=str)

    def to_csv_row(self, fields: list[str] | None = None) -> str:
        """Serialise as a CSV row."""
        import csv
        import io

        data = self.to_dict()
        cols = fields or list(data.keys())
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([str(data.get(c, "")) for c in cols])
        return buf.getvalue().rstrip("\r\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def date_partition(epoch: float) -> str:
    """Return a date-partitioned path component like ``2026/02/22``."""
    return time.strftime("%Y/%m/%d", time.gmtime(epoch))


def build_key(prefix: str, epoch: float, suffix: str, seq: int = 1) -> str:
    """Build a storage key like ``logs/2026/02/22/requests_001.jsonl``."""
    partition = date_partition(epoch)
    return f"{prefix.rstrip('/')}/{partition}/requests_{seq:03d}.{suffix}"


# ---------------------------------------------------------------------------
# Base exporter
# ---------------------------------------------------------------------------


class BaseLogExporter(ABC):
    """Abstract base for log storage backends.

    Subclasses implement ``_write_bytes`` to send data to their
    storage backend.  The base class handles buffering, batching,
    serialisation, and date-partitioned key generation.
    """

    def __init__(self, config: ExportConfig | None = None) -> None:
        self._config = config or ExportConfig()
        self._buffer: list[LogRecord] = []
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        self._seq = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background flush loop (batch mode only)."""
        if self._config.mode == ExportMode.BATCH and self._flush_task is None:
            self._flush_task = asyncio.create_task(self._periodic_flush())

    async def write(self, record: LogRecord) -> None:
        """Write a log record.

        In **realtime** mode the record is written immediately.
        In **batch** mode it is buffered until the next flush.
        """
        if not self._config.enabled:
            return

        if self._config.mode == ExportMode.REALTIME:
            content = self._serialise([record])
            key = self._next_key(record.timestamp)
            await self._safe_write(key, content)
        else:
            async with self._lock:
                self._buffer.append(record)
                if len(self._buffer) >= self._config.max_buffer_size:
                    await self._flush_buffer()

    async def flush(self) -> None:
        """Force-flush the buffer."""
        async with self._lock:
            await self._flush_buffer()

    async def close(self) -> None:
        """Flush remaining records and shut down."""
        if self._flush_task is not None:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None
        await self.flush()

    # ------------------------------------------------------------------
    # Abstract
    # ------------------------------------------------------------------

    @abstractmethod
    async def _write_bytes(self, key: str, data: bytes) -> None:
        """Write raw bytes to storage at the given key/path."""

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _flush_buffer(self) -> None:
        """Flush buffered records (must be called under Lock)."""
        if not self._buffer:
            return
        records = self._buffer[:]
        self._buffer.clear()
        content = self._serialise(records)
        key = self._next_key(records[0].timestamp)
        await self._safe_write(key, content)

    async def _safe_write(self, key: str, data: bytes) -> None:
        """Write with error isolation."""
        try:
            await self._write_bytes(key, data)
            logger.debug("Exported %d bytes to %s", len(data), key)
        except Exception:
            logger.exception("Log export failed for key=%s", key)

    def _serialise(self, records: list[LogRecord]) -> bytes:
        """Serialise records according to config format."""
        if self._config.format == ExportFormat.JSONL:
            lines = [r.to_jsonl() for r in records]
            return ("\n".join(lines) + "\n").encode()

        # CSV
        if records:
            fields = list(records[0].to_dict().keys())
            import csv
            import io

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(fields)
            for r in records:
                d = r.to_dict()
                writer.writerow([str(d.get(f, "")) for f in fields])
            return buf.getvalue().encode()

        return b""

    def _next_key(self, epoch: float) -> str:
        """Generate the next storage key."""
        self._seq += 1
        suffix = self._config.format.value
        return build_key(self._config.prefix, epoch, suffix, self._seq)

    async def _periodic_flush(self) -> None:
        """Background flush loop."""
        while True:
            await asyncio.sleep(self._config.flush_interval_seconds)
            try:
                await self.flush()
            except Exception:
                logger.exception("Periodic log export flush error")
