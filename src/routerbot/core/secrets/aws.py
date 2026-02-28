"""AWS Secrets Manager backend.

Resolves ``aws_secret/secret-name`` and ``aws_secret/secret-name#json_key``
references using the ``boto3`` library.

Optional region can be specified as ``aws_secret/region:secret-name``.
"""

from __future__ import annotations

import logging

from routerbot.core.secrets.base import SecretBackend, SecretResolutionError

logger = logging.getLogger(__name__)

try:
    import boto3

    _HAS_BOTO3 = True
except ImportError:  # pragma: no cover
    _HAS_BOTO3 = False


class AWSSecretsManagerBackend(SecretBackend):
    """Retrieve secrets from AWS Secrets Manager.

    Secret references::

        aws_secret/my-secret-name
        aws_secret/us-east-1:my-secret-name
        aws_secret/my-secret-name#json_key

    Args:
        region_name: Default AWS region. Can be overridden per-reference.
        profile_name: AWS credentials profile (for local dev).
        endpoint_url: Custom endpoint (for LocalStack / testing).
    """

    def __init__(
        self,
        *,
        region_name: str | None = None,
        profile_name: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        if not _HAS_BOTO3:
            msg = "boto3 is required for AWS Secrets Manager integration. Install it with: pip install boto3"
            raise ImportError(msg)

        session_kwargs: dict[str, str] = {}
        if region_name:
            session_kwargs["region_name"] = region_name
        if profile_name:
            session_kwargs["profile_name"] = profile_name

        session = boto3.Session(**session_kwargs)
        client_kwargs: dict[str, str] = {}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if region_name:
            client_kwargs["region_name"] = region_name

        self._client = session.client("secretsmanager", **client_kwargs)

    @property
    def prefix(self) -> str:
        return "aws_secret"

    def get_secret(self, path: str) -> str:
        """Retrieve secret value from AWS Secrets Manager.

        Path format: ``secret-name`` or ``region:secret-name``.
        """
        # Support region:name syntax
        if ":" in path:
            region, secret_id = path.split(":", 1)
            # Create a new client for the specified region
            client = boto3.client("secretsmanager", region_name=region)
        else:
            secret_id = path
            client = self._client

        try:
            response = client.get_secret_value(SecretId=secret_id)
        except Exception as exc:
            msg = f"Failed to retrieve AWS secret '{secret_id}': {exc}"
            raise SecretResolutionError(msg) from exc

        # AWS returns either SecretString or SecretBinary
        if "SecretString" in response:
            return response["SecretString"]

        msg = f"AWS secret '{secret_id}' is binary — only string secrets are supported"
        raise SecretResolutionError(msg)
