"""Google Cloud Secret Manager backend.

Resolves ``gcp_secret/project-id/secret-name`` references using the
``google-cloud-secret-manager`` library.

Optionally specify a version: ``gcp_secret/project-id/secret-name/version``.
Defaults to ``latest``.
"""

from __future__ import annotations

import logging

from routerbot.core.secrets.base import SecretBackend, SecretResolutionError

logger = logging.getLogger(__name__)

try:
    from google.cloud import secretmanager  # type: ignore[import-untyped]

    _HAS_GCP = True
except ImportError:  # pragma: no cover
    _HAS_GCP = False


class GCPSecretManagerBackend(SecretBackend):
    """Retrieve secrets from Google Cloud Secret Manager.

    Secret references::

        gcp_secret/my-project/my-secret
        gcp_secret/my-project/my-secret/2        (specific version)
        gcp_secret/my-project/my-secret#json_key  (JSON key extraction)

    Args:
        project: Default GCP project. Overridden if the reference includes one.
    """

    def __init__(self, *, project: str | None = None) -> None:
        if not _HAS_GCP:
            msg = (
                "google-cloud-secret-manager is required for GCP Secret Manager. "
                "Install it with: pip install google-cloud-secret-manager"
            )
            raise ImportError(msg)

        self._client = secretmanager.SecretManagerServiceClient()
        self._default_project = project

    @property
    def prefix(self) -> str:
        return "gcp_secret"

    def get_secret(self, path: str) -> str:
        """Retrieve secret from GCP Secret Manager.

        Path format: ``project/secret-name`` or ``project/secret-name/version``.
        """
        parts = path.split("/")
        if len(parts) == 2:
            project_id, secret_id = parts
            version = "latest"
        elif len(parts) == 3:
            project_id, secret_id, version = parts
        else:
            msg = (
                f"Invalid GCP secret path '{path}'. "
                "Expected: project-id/secret-name or project-id/secret-name/version"
            )
            raise SecretResolutionError(msg)

        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version}"

        try:
            response = self._client.access_secret_version(request={"name": name})
        except Exception as exc:
            msg = f"Failed to retrieve GCP secret '{name}': {exc}"
            raise SecretResolutionError(msg) from exc

        payload = response.payload.data
        if isinstance(payload, bytes):
            return payload.decode("utf-8")
        return str(payload)
