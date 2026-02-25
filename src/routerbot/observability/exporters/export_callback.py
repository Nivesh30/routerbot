"""Log export callback that writes to a :class:`BaseLogExporter`.

Bridges the callback system with the exporter backends so that each
completed LLM request is automatically exported.
"""

from __future__ import annotations

import logging

from routerbot.observability.callbacks import (
    BaseCallback,
    RequestEndData,
    RequestErrorData,
    RequestStartData,
)
from routerbot.observability.exporters.base import BaseLogExporter, LogRecord

logger = logging.getLogger(__name__)


class LogExportCallback(BaseCallback):
    """Callback that exports request logs to a storage backend.

    Usage::

        from routerbot.observability.exporters.local import LocalExporter
        from routerbot.observability.exporters.export_callback import LogExportCallback

        exporter = LocalExporter(root_dir="/var/log/routerbot")
        await exporter.start()

        callback = LogExportCallback(exporter)
        manager.register(callback)
    """

    def __init__(self, exporter: BaseLogExporter) -> None:
        self._exporter = exporter

    async def on_request_start(self, data: RequestStartData) -> None:
        """No-op — logs are only exported on completion or error."""

    async def on_request_end(self, data: RequestEndData) -> None:
        """Export a success log record."""
        record = LogRecord(
            request_id=data.request_id,
            model=data.model,
            provider=data.provider,
            tokens_prompt=data.tokens_prompt,
            tokens_completion=data.tokens_completion,
            cost=data.cost,
            latency_ms=data.latency_ms,
            status="success",
            user_id=data.user_id,
            team_id=data.team_id,
            key_id=data.key_id,
            timestamp=data.timestamp,
            metadata=data.metadata,
        )
        await self._exporter.write(record)

    async def on_request_error(self, data: RequestErrorData) -> None:
        """Export an error log record."""
        record = LogRecord(
            request_id=data.request_id,
            model=data.model,
            provider=data.provider,
            status="error",
            error=data.error,
            user_id=data.user_id,
            team_id=data.team_id,
            key_id=data.key_id,
            timestamp=data.timestamp,
            metadata=data.metadata,
        )
        await self._exporter.write(record)
