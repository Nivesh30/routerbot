"""AWS S3 log exporter.

Requires the ``boto3`` package (``pip install boto3``).

Configuration::

    observability:
      log_export:
        enabled: true
        backend: "s3"
        s3_bucket: "my-llm-logs"
        s3_prefix: "routerbot/"
        format: "jsonl"
"""

from __future__ import annotations

import logging

from routerbot.observability.exporters.base import BaseLogExporter, ExportConfig

logger = logging.getLogger(__name__)


class S3Exporter(BaseLogExporter):
    """Export logs to AWS S3.

    Parameters
    ----------
    bucket:
        S3 bucket name.
    config:
        Export configuration.
    region:
        AWS region name (optional).
    boto3_session:
        Pre-configured ``boto3.Session`` (optional; useful for tests).
    """

    def __init__(
        self,
        bucket: str,
        config: ExportConfig | None = None,
        *,
        region: str | None = None,
        boto3_session: object | None = None,
    ) -> None:
        super().__init__(config)
        self._bucket = bucket
        self._region = region
        self._boto3_session = boto3_session
        self._client: object | None = None

    def _get_client(self) -> object:
        """Lazily create the S3 client."""
        if self._client is not None:
            return self._client

        try:
            import boto3
        except ImportError as exc:
            msg = "boto3 is required for S3 export. Install with: pip install boto3"
            raise ImportError(msg) from exc

        session = self._boto3_session or boto3.Session(region_name=self._region)
        self._client = session.client("s3")  # type: ignore[union-attr]
        return self._client

    async def _write_bytes(self, key: str, data: bytes) -> None:
        """Upload data to S3."""
        import asyncio

        client = self._get_client()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: client.put_object(Bucket=self._bucket, Key=key, Body=data),  # type: ignore[union-attr]
        )
