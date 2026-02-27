"""HashiCorp Vault backend (KV v2).

Resolves ``vault/path/to/secret`` references using the ``hvac`` library.
Supports JSON key extraction via ``vault/path/to/secret#key``.
"""

from __future__ import annotations

import logging
import os

from routerbot.core.secrets.base import SecretBackend, SecretResolutionError

logger = logging.getLogger(__name__)

try:
    import hvac  # type: ignore[import-untyped]

    _HAS_HVAC = True
except ImportError:  # pragma: no cover
    _HAS_HVAC = False


class HashiCorpVaultBackend(SecretBackend):
    """Retrieve secrets from HashiCorp Vault KV v2 engine.

    Secret references::

        vault/secret/data/my-app       (returns JSON-encoded data)
        vault/my-app                    (shorthand: mount=secret, path=my-app)
        vault/my-app#api_key           (extract a specific key from data)

    Environment variables used when no explicit arguments are provided:

    - ``VAULT_ADDR`` — Vault server URL (default ``http://127.0.0.1:8200``)
    - ``VAULT_TOKEN`` — Vault authentication token

    Args:
        url: Vault server URL.
        token: Vault authentication token.
        mount_point: KV v2 mount point (default ``secret``).
        namespace: Vault namespace (Enterprise feature).
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        token: str | None = None,
        mount_point: str = "secret",
        namespace: str | None = None,
    ) -> None:
        if not _HAS_HVAC:
            msg = (
                "hvac is required for HashiCorp Vault integration. "
                "Install it with: pip install hvac"
            )
            raise ImportError(msg)

        vault_url = url or os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
        vault_token = token or os.environ.get("VAULT_TOKEN")

        kwargs: dict[str, str | None] = {"url": vault_url, "token": vault_token}
        if namespace:
            kwargs["namespace"] = namespace

        self._client = hvac.Client(**kwargs)
        self._mount_point = mount_point

    @property
    def prefix(self) -> str:
        return "vault"

    def get_secret(self, path: str) -> str:
        """Retrieve secret data from Vault KV v2.

        Returns the secret data as a JSON string. Use ``#key`` suffix for
        individual key extraction (handled by the resolver).

        Path format: ``path/to/secret`` — the mount point is prepended
        automatically.
        """
        import json

        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self._mount_point,
            )
        except Exception as exc:
            msg = f"Failed to retrieve Vault secret '{self._mount_point}/{path}': {exc}"
            raise SecretResolutionError(msg) from exc

        if response is None or "data" not in response:
            msg = f"Vault secret '{path}' returned no data"
            raise SecretResolutionError(msg)

        data = response["data"].get("data", {})
        if not data:
            msg = f"Vault secret '{path}' has empty data"
            raise SecretResolutionError(msg)

        # If there's only one key, return its value directly
        if len(data) == 1:
            return str(next(iter(data.values())))

        # Otherwise return as JSON for #key extraction
        return json.dumps(data)
