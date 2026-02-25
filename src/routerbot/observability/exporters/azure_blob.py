"""Azure Blob Storage log exporter.

Requires ``azure-storage-blob``::

    pip install azure-storage-blob

Configuration::

    observability:
      log_export:
        enabled: true
        backend: "azure_blob"
        azure_container: "llm-logs"
        azure_connection_string: "DefaultEndpointsProtocol=..."
        prefix: "routerbot/"
        format: "jsonl"
"""

from __future__ import annotations

import logging

from routerbot.observability.exporters.base import BaseLogExporter, ExportConfig

logger = logging.getLogger(__name__)


class AzureBlobExporter(BaseLogExporter):
    """Export logs to Azure Blob Storage.

    Parameters
    ----------
    container_name:
        Azure Blob container name.
    connection_string:
        Azure Storage connection string.
    config:
        Export configuration.
    blob_service_client:
        Pre-configured ``BlobServiceClient`` (optional; useful for tests).
    """

    def __init__(
        self,
        container_name: str,
        connection_string: str | None = None,
        config: ExportConfig | None = None,
        *,
        blob_service_client: object | None = None,
    ) -> None:
        super().__init__(config)
        self._container_name = container_name
        self._connection_string = connection_string
        self._blob_service_client = blob_service_client
        self._container_client: object | None = None

    def _get_container_client(self) -> object:
        """Lazily initialise the container client."""
        if self._container_client is not None:
            return self._container_client

        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError as exc:
            msg = "azure-storage-blob is required for Azure export. Install with: pip install azure-storage-blob"
            raise ImportError(msg) from exc

        if self._blob_service_client is not None:
            client = self._blob_service_client
        elif self._connection_string:
            client = BlobServiceClient.from_connection_string(self._connection_string)
        else:
            msg = "Either connection_string or blob_service_client must be provided"
            raise ValueError(msg)

        self._container_client = client.get_container_client(self._container_name)  # type: ignore[union-attr]
        return self._container_client

    async def _write_bytes(self, key: str, data: bytes) -> None:
        """Upload data to Azure Blob Storage."""
        import asyncio

        container = self._get_container_client()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: container.upload_blob(name=key, data=data, overwrite=True),  # type: ignore[union-attr]
        )
