"""Azure Key Vault backend.

Resolves ``azure_keyvault/vault-name/secret-name`` references using the
``azure-keyvault-secrets`` + ``azure-identity`` libraries.

Optionally specify a version:
``azure_keyvault/vault-name/secret-name/version``.
"""

from __future__ import annotations

import logging

from routerbot.core.secrets.base import SecretBackend, SecretResolutionError

logger = logging.getLogger(__name__)

try:
    from azure.identity import DefaultAzureCredential  # type: ignore[import-untyped]
    from azure.keyvault.secrets import SecretClient  # type: ignore[import-untyped]

    _HAS_AZURE = True
except ImportError:  # pragma: no cover
    _HAS_AZURE = False


class AzureKeyVaultBackend(SecretBackend):
    """Retrieve secrets from Azure Key Vault.

    Secret references::

        azure_keyvault/my-vault/my-secret
        azure_keyvault/my-vault/my-secret/version-id
        azure_keyvault/my-vault/my-secret#json_key

    Args:
        vault_url: Explicit vault URL. Overridden if the reference contains
            a vault name component.
        credential: Azure credential instance. Defaults to
            ``DefaultAzureCredential()``.
    """

    def __init__(
        self,
        *,
        vault_url: str | None = None,
        credential: object | None = None,
    ) -> None:
        if not _HAS_AZURE:
            msg = (
                "azure-keyvault-secrets and azure-identity are required for "
                "Azure Key Vault. Install with: "
                "pip install azure-keyvault-secrets azure-identity"
            )
            raise ImportError(msg)

        self._credential = credential or DefaultAzureCredential()
        self._default_vault_url = vault_url
        # Cache clients per vault URL to avoid re-creating
        self._clients: dict[str, SecretClient] = {}

    @property
    def prefix(self) -> str:
        return "azure_keyvault"

    def _get_client(self, vault_name: str) -> SecretClient:
        """Get or create a SecretClient for the given vault."""
        vault_url = f"https://{vault_name}.vault.azure.net"
        if vault_url not in self._clients:
            self._clients[vault_url] = SecretClient(vault_url=vault_url, credential=self._credential)
        return self._clients[vault_url]

    def get_secret(self, path: str) -> str:
        """Retrieve secret from Azure Key Vault.

        Path format: ``vault-name/secret-name`` or
        ``vault-name/secret-name/version``.
        """
        parts = path.split("/")
        if len(parts) == 2:
            vault_name, secret_name = parts
            version = None
        elif len(parts) == 3:
            vault_name, secret_name, version = parts
        else:
            msg = (
                f"Invalid Azure Key Vault path '{path}'. "
                "Expected: vault-name/secret-name or vault-name/secret-name/version"
            )
            raise SecretResolutionError(msg)

        client = self._get_client(vault_name)

        try:
            secret = client.get_secret(secret_name, version=version)
        except Exception as exc:
            msg = f"Failed to retrieve Azure secret '{vault_name}/{secret_name}': {exc}"
            raise SecretResolutionError(msg) from exc

        if secret.value is None:
            msg = f"Azure secret '{vault_name}/{secret_name}' has no value"
            raise SecretResolutionError(msg)

        return secret.value
