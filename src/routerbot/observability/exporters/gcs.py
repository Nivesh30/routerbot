"""Google Cloud Storage log exporter.

Requires the ``google-cloud-storage`` package::

    pip install google-cloud-storage

Configuration::

    observability:
      log_export:
        enabled: true
        backend: "gcs"
        gcs_bucket: "my-llm-logs"
        prefix: "routerbot/"
        format: "jsonl"
"""

from __future__ import annotations

import logging

from routerbot.observability.exporters.base import BaseLogExporter, ExportConfig

logger = logging.getLogger(__name__)


class GCSExporter(BaseLogExporter):
    """Export logs to Google Cloud Storage.

    Parameters
    ----------
    bucket_name:
        GCS bucket name.
    config:
        Export configuration.
    storage_client:
        Pre-configured ``google.cloud.storage.Client`` (optional).
    """

    def __init__(
        self,
        bucket_name: str,
        config: ExportConfig | None = None,
        *,
        storage_client: object | None = None,
    ) -> None:
        super().__init__(config)
        self._bucket_name = bucket_name
        self._storage_client = storage_client
        self._bucket: object | None = None

    def _get_bucket(self) -> object:
        """Lazily initialise the GCS bucket handle."""
        if self._bucket is not None:
            return self._bucket

        try:
            from google.cloud import storage
        except ImportError as exc:
            msg = "google-cloud-storage is required for GCS export. Install with: pip install google-cloud-storage"
            raise ImportError(msg) from exc

        client = self._storage_client or storage.Client()
        self._bucket = client.bucket(self._bucket_name)  # type: ignore[union-attr]
        return self._bucket

    async def _write_bytes(self, key: str, data: bytes) -> None:
        """Upload data to GCS."""
        import asyncio

        bucket = self._get_bucket()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: bucket.blob(key).upload_from_string(data),  # type: ignore[union-attr]
        )
