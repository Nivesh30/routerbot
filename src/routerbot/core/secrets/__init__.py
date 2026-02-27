"""Secret manager integrations for RouterBot.

Supports resolving secrets from external secret managers via URI-style
references in configuration values:

- ``os.environ/VAR_NAME`` — Environment variable (existing)
- ``aws_secret/secret-name`` — AWS Secrets Manager
- ``aws_secret/secret-name#key`` — AWS Secrets Manager (JSON key extraction)
- ``gcp_secret/project/secret-name`` — Google Cloud Secret Manager
- ``azure_keyvault/vault-name/secret-name`` — Azure Key Vault
- ``vault/path/to/secret`` — HashiCorp Vault KV v2
- ``vault/path/to/secret#key`` — HashiCorp Vault KV v2 (JSON key extraction)
"""

from routerbot.core.secrets.base import (
    SecretBackend,
    SecretCache,
    SecretResolver,
)

__all__ = [
    "SecretBackend",
    "SecretCache",
    "SecretResolver",
]
