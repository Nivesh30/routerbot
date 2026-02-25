"""Local filesystem log exporter.

Writes log files to the local filesystem using :mod:`aiofiles` for
async I/O.  Falls back to synchronous writes if ``aiofiles`` is not
installed.

Configuration::

    observability:
      log_export:
        enabled: true
        backend: "local"
        prefix: "logs"
        format: "jsonl"
"""

from __future__ import annotations

import logging
from pathlib import Path

from routerbot.observability.exporters.base import BaseLogExporter, ExportConfig

logger = logging.getLogger(__name__)


class LocalExporter(BaseLogExporter):
    """Export logs to the local filesystem.

    Parameters
    ----------
    root_dir:
        Base directory for log files.  Sub-directories are created
        automatically following the date-partition scheme.
    config:
        Export configuration.
    """

    def __init__(
        self,
        root_dir: str | Path = ".",
        config: ExportConfig | None = None,
    ) -> None:
        super().__init__(config)
        self._root = Path(root_dir)

    async def _write_bytes(self, key: str, data: bytes) -> None:
        """Write data to a local file."""
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import aiofiles

            async with aiofiles.open(path, "ab") as f:
                await f.write(data)
        except ImportError:
            # Fallback to synchronous write
            with open(path, "ab") as f:  # noqa: ASYNC230
                f.write(data)
