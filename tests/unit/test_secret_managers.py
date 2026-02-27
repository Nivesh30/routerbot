"""Tests for secret manager integration (Task 8F.1).

Covers:
- SecretCache: TTL, expiry, clear
- SecretResolver: pattern matching, backend dispatch, JSON key extraction, caching
- AWSSecretsManagerBackend: mock boto3 usage
- GCPSecretManagerBackend: mock google-cloud usage
- AzureKeyVaultBackend: mock azure usage
- HashiCorpVaultBackend: mock hvac usage
- Config integration: secret refs resolved during load_config
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from routerbot.core.secrets.base import (
    SecretBackend,
    SecretCache,
    SecretResolutionError,
    SecretResolver,
)

# ── Helpers ───────────────────────────────────────────────────────────────


class FakeBackend(SecretBackend):
    """In-memory secret backend for testing."""

    def __init__(self, prefix_name: str = "aws_secret", secrets: dict[str, str] | None = None) -> None:
        self._prefix = prefix_name
        self._secrets = secrets or {}

    @property
    def prefix(self) -> str:
        return self._prefix

    def get_secret(self, path: str) -> str:
        if path in self._secrets:
            return self._secrets[path]
        raise SecretResolutionError(f"Secret not found: {path}")


# ═══════════════════════════════════════════════════════════════════════════
# SecretCache tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSecretCache:
    def test_put_and_get(self) -> None:
        cache = SecretCache(ttl_seconds=60)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing_returns_none(self) -> None:
        cache = SecretCache(ttl_seconds=60)
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self) -> None:
        cache = SecretCache(ttl_seconds=0.01)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"
        time.sleep(0.02)
        assert cache.get("key1") is None

    def test_disabled_cache_ttl_zero(self) -> None:
        cache = SecretCache(ttl_seconds=0)
        cache.put("key1", "value1")
        # With ttl=0, put is a no-op
        assert cache.get("key1") is None

    def test_clear(self) -> None:
        cache = SecretCache(ttl_seconds=60)
        cache.put("a", "1")
        cache.put("b", "2")
        assert cache.size == 2
        cache.clear()
        assert cache.size == 0
        assert cache.get("a") is None

    def test_size(self) -> None:
        cache = SecretCache(ttl_seconds=60)
        assert cache.size == 0
        cache.put("a", "1")
        assert cache.size == 1


# ═══════════════════════════════════════════════════════════════════════════
# SecretResolver tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSecretResolver:
    def test_register_backend(self) -> None:
        resolver = SecretResolver()
        backend = FakeBackend("aws_secret")
        resolver.register_backend(backend)
        assert "aws_secret" in resolver.registered_prefixes

    def test_resolve_non_matching_passthrough(self) -> None:
        resolver = SecretResolver()
        assert resolver.resolve("regular_value") == "regular_value"
        assert resolver.resolve("os.environ/FOO") == "os.environ/FOO"
        assert resolver.resolve("123") == "123"

    def test_resolve_simple(self) -> None:
        resolver = SecretResolver()
        resolver.register_backend(FakeBackend("aws_secret", {"my-key": "sk-abc123"}))
        result = resolver.resolve("aws_secret/my-key")
        assert result == "sk-abc123"

    def test_resolve_json_key(self) -> None:
        resolver = SecretResolver()
        secrets = {"multi": json.dumps({"api_key": "sk-123", "org": "org-456"})}
        resolver.register_backend(FakeBackend("aws_secret", secrets))
        assert resolver.resolve("aws_secret/multi#api_key") == "sk-123"
        assert resolver.resolve("aws_secret/multi#org") == "org-456"

    def test_resolve_json_key_missing(self) -> None:
        resolver = SecretResolver()
        secrets = {"multi": json.dumps({"api_key": "sk-123"})}
        resolver.register_backend(FakeBackend("aws_secret", secrets))
        with pytest.raises(SecretResolutionError, match="Key 'missing' not found"):
            resolver.resolve("aws_secret/multi#missing")

    def test_resolve_json_key_not_json(self) -> None:
        resolver = SecretResolver()
        resolver.register_backend(FakeBackend("aws_secret", {"plain": "not-json"}))
        with pytest.raises(SecretResolutionError, match="not valid JSON"):
            resolver.resolve("aws_secret/plain#key")

    def test_resolve_json_key_not_object(self) -> None:
        resolver = SecretResolver()
        resolver.register_backend(FakeBackend("aws_secret", {"arr": "[1,2,3]"}))
        with pytest.raises(SecretResolutionError, match="not a JSON object"):
            resolver.resolve("aws_secret/arr#key")

    def test_resolve_no_backend_registered(self) -> None:
        resolver = SecretResolver()
        with pytest.raises(SecretResolutionError, match="No secret backend registered"):
            resolver.resolve("aws_secret/my-key")

    def test_resolve_backend_error(self) -> None:
        resolver = SecretResolver()
        resolver.register_backend(FakeBackend("aws_secret", {}))
        with pytest.raises(SecretResolutionError, match="Secret not found"):
            resolver.resolve("aws_secret/nope")

    def test_resolve_backend_unexpected_error(self) -> None:
        resolver = SecretResolver()
        backend = FakeBackend("aws_secret")
        backend.get_secret = MagicMock(side_effect=RuntimeError("connection failed"))  # type: ignore[assignment]
        resolver.register_backend(backend)
        with pytest.raises(SecretResolutionError, match="Failed to resolve"):
            resolver.resolve("aws_secret/any")

    def test_resolve_with_caching(self) -> None:
        cache = SecretCache(ttl_seconds=60)
        resolver = SecretResolver(cache=cache)
        backend = FakeBackend("aws_secret", {"key": "val"})
        backend.get_secret = MagicMock(return_value="val")  # type: ignore[assignment]
        resolver.register_backend(backend)

        # First call hits backend
        assert resolver.resolve("aws_secret/key") == "val"
        assert backend.get_secret.call_count == 1

        # Second call hits cache
        assert resolver.resolve("aws_secret/key") == "val"
        assert backend.get_secret.call_count == 1

    def test_resolve_all_dict(self) -> None:
        resolver = SecretResolver()
        resolver.register_backend(FakeBackend("aws_secret", {"k1": "v1", "k2": "v2"}))
        data = {"a": "aws_secret/k1", "b": "plain", "c": {"nested": "aws_secret/k2"}}
        result = resolver.resolve_all(data)
        assert result == {"a": "v1", "b": "plain", "c": {"nested": "v2"}}

    def test_resolve_all_list(self) -> None:
        resolver = SecretResolver()
        resolver.register_backend(FakeBackend("aws_secret", {"k": "v"}))
        data = ["aws_secret/k", "regular"]
        result = resolver.resolve_all(data)
        assert result == ["v", "regular"]

    def test_resolve_all_non_string_passthrough(self) -> None:
        resolver = SecretResolver()
        data: dict[str, Any] = {"num": 42, "flag": True, "nothing": None}
        result = resolver.resolve_all(data)
        assert result == data

    def test_is_secret_ref(self) -> None:
        assert SecretResolver.is_secret_ref("aws_secret/my-key") is True
        assert SecretResolver.is_secret_ref("gcp_secret/proj/secret") is True
        assert SecretResolver.is_secret_ref("azure_keyvault/vault/name") is True
        assert SecretResolver.is_secret_ref("vault/path/to/secret") is True
        assert SecretResolver.is_secret_ref("vault/path#key") is True
        assert SecretResolver.is_secret_ref("os.environ/FOO") is False
        assert SecretResolver.is_secret_ref("plain_value") is False

    def test_multiple_backends(self) -> None:
        resolver = SecretResolver()
        resolver.register_backend(FakeBackend("aws_secret", {"a": "from_aws"}))
        resolver.register_backend(FakeBackend("vault", {"b": "from_vault"}))
        assert resolver.resolve("aws_secret/a") == "from_aws"
        assert resolver.resolve("vault/b") == "from_vault"


# ═══════════════════════════════════════════════════════════════════════════
# AWS Secrets Manager backend tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAWSSecretsManagerBackend:
    def test_import_error_without_boto3(self) -> None:
        with patch.dict("sys.modules", {"boto3": None, "botocore": None, "botocore.exceptions": None}):
            # Re-import to trigger import error check
            from routerbot.core.secrets import aws as aws_mod

            original = aws_mod._HAS_BOTO3
            aws_mod._HAS_BOTO3 = False
            try:
                with pytest.raises(ImportError, match="boto3 is required"):
                    aws_mod.AWSSecretsManagerBackend()
            finally:
                aws_mod._HAS_BOTO3 = original

    def test_prefix(self) -> None:
        with patch("routerbot.core.secrets.aws.boto3", create=True) as mock_boto3:
            mock_boto3.Session.return_value.client.return_value = MagicMock()
            from routerbot.core.secrets import aws as aws_mod
            from routerbot.core.secrets.aws import AWSSecretsManagerBackend

            original = aws_mod._HAS_BOTO3
            aws_mod._HAS_BOTO3 = True
            try:
                backend = AWSSecretsManagerBackend()
                assert backend.prefix == "aws_secret"
            finally:
                aws_mod._HAS_BOTO3 = original

    def test_get_secret_string(self) -> None:
        with patch("routerbot.core.secrets.aws.boto3", create=True) as mock_boto3:
            mock_client = MagicMock()
            mock_client.get_secret_value.return_value = {"SecretString": "my-secret-value"}
            mock_boto3.Session.return_value.client.return_value = mock_client
            from routerbot.core.secrets import aws as aws_mod
            from routerbot.core.secrets.aws import AWSSecretsManagerBackend

            original = aws_mod._HAS_BOTO3
            aws_mod._HAS_BOTO3 = True
            try:
                backend = AWSSecretsManagerBackend()
                result = backend.get_secret("my-secret")
                assert result == "my-secret-value"
                mock_client.get_secret_value.assert_called_once_with(SecretId="my-secret")
            finally:
                aws_mod._HAS_BOTO3 = original

    def test_get_secret_with_region_prefix(self) -> None:
        with patch("routerbot.core.secrets.aws.boto3", create=True) as mock_boto3:
            mock_session_client = MagicMock()
            mock_session_client.get_secret_value.return_value = {"SecretString": "val"}
            mock_boto3.Session.return_value.client.return_value = mock_session_client

            mock_regional_client = MagicMock()
            mock_regional_client.get_secret_value.return_value = {"SecretString": "regional-val"}
            mock_boto3.client.return_value = mock_regional_client

            from routerbot.core.secrets import aws as aws_mod
            from routerbot.core.secrets.aws import AWSSecretsManagerBackend

            original = aws_mod._HAS_BOTO3
            aws_mod._HAS_BOTO3 = True
            try:
                backend = AWSSecretsManagerBackend()
                result = backend.get_secret("eu-west-1:my-secret")
                assert result == "regional-val"
                mock_boto3.client.assert_called_once_with("secretsmanager", region_name="eu-west-1")
            finally:
                aws_mod._HAS_BOTO3 = original

    def test_get_secret_binary_raises(self) -> None:
        with patch("routerbot.core.secrets.aws.boto3", create=True) as mock_boto3:
            mock_client = MagicMock()
            mock_client.get_secret_value.return_value = {"SecretBinary": b"\x00\x01"}
            mock_boto3.Session.return_value.client.return_value = mock_client
            from routerbot.core.secrets import aws as aws_mod
            from routerbot.core.secrets.aws import AWSSecretsManagerBackend

            original = aws_mod._HAS_BOTO3
            aws_mod._HAS_BOTO3 = True
            try:
                backend = AWSSecretsManagerBackend()
                with pytest.raises(SecretResolutionError, match="binary"):
                    backend.get_secret("binary-secret")
            finally:
                aws_mod._HAS_BOTO3 = original

    def test_get_secret_client_error(self) -> None:
        with patch("routerbot.core.secrets.aws.boto3", create=True) as mock_boto3:
            mock_client = MagicMock()
            mock_client.get_secret_value.side_effect = Exception("Access denied")
            mock_boto3.Session.return_value.client.return_value = mock_client
            from routerbot.core.secrets import aws as aws_mod
            from routerbot.core.secrets.aws import AWSSecretsManagerBackend

            original = aws_mod._HAS_BOTO3
            aws_mod._HAS_BOTO3 = True
            try:
                backend = AWSSecretsManagerBackend()
                with pytest.raises(SecretResolutionError, match="Failed to retrieve"):
                    backend.get_secret("forbidden-secret")
            finally:
                aws_mod._HAS_BOTO3 = original


# ═══════════════════════════════════════════════════════════════════════════
# GCP Secret Manager backend tests
# ═══════════════════════════════════════════════════════════════════════════


class TestGCPSecretManagerBackend:
    def test_import_error_without_gcp(self) -> None:
        from routerbot.core.secrets import gcp as gcp_mod

        original = gcp_mod._HAS_GCP
        gcp_mod._HAS_GCP = False
        try:
            with pytest.raises(ImportError, match="google-cloud-secret-manager"):
                gcp_mod.GCPSecretManagerBackend()
        finally:
            gcp_mod._HAS_GCP = original

    def test_prefix(self) -> None:
        with patch("routerbot.core.secrets.gcp.secretmanager", create=True) as mock_sm:
            mock_sm.SecretManagerServiceClient.return_value = MagicMock()
            from routerbot.core.secrets.gcp import GCPSecretManagerBackend

            gcp_mod = __import__("routerbot.core.secrets.gcp", fromlist=["_HAS_GCP"])
            original = gcp_mod._HAS_GCP
            gcp_mod._HAS_GCP = True
            try:
                backend = GCPSecretManagerBackend()
                assert backend.prefix == "gcp_secret"
            finally:
                gcp_mod._HAS_GCP = original

    def test_get_secret_two_part_path(self) -> None:
        with patch("routerbot.core.secrets.gcp.secretmanager", create=True) as mock_sm:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.payload.data = b"my-gcp-secret"
            mock_client.access_secret_version.return_value = mock_response
            mock_sm.SecretManagerServiceClient.return_value = mock_client

            gcp_mod = __import__("routerbot.core.secrets.gcp", fromlist=["_HAS_GCP"])
            original = gcp_mod._HAS_GCP
            gcp_mod._HAS_GCP = True
            try:
                from routerbot.core.secrets.gcp import GCPSecretManagerBackend

                backend = GCPSecretManagerBackend()
                result = backend.get_secret("my-project/my-secret")
                assert result == "my-gcp-secret"
                mock_client.access_secret_version.assert_called_once_with(
                    request={"name": "projects/my-project/secrets/my-secret/versions/latest"}
                )
            finally:
                gcp_mod._HAS_GCP = original

    def test_get_secret_three_part_path_with_version(self) -> None:
        with patch("routerbot.core.secrets.gcp.secretmanager", create=True) as mock_sm:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.payload.data = b"versioned-secret"
            mock_client.access_secret_version.return_value = mock_response
            mock_sm.SecretManagerServiceClient.return_value = mock_client

            gcp_mod = __import__("routerbot.core.secrets.gcp", fromlist=["_HAS_GCP"])
            original = gcp_mod._HAS_GCP
            gcp_mod._HAS_GCP = True
            try:
                from routerbot.core.secrets.gcp import GCPSecretManagerBackend

                backend = GCPSecretManagerBackend()
                result = backend.get_secret("my-project/my-secret/3")
                assert result == "versioned-secret"
                mock_client.access_secret_version.assert_called_once_with(
                    request={"name": "projects/my-project/secrets/my-secret/versions/3"}
                )
            finally:
                gcp_mod._HAS_GCP = original

    def test_get_secret_invalid_path(self) -> None:
        with patch("routerbot.core.secrets.gcp.secretmanager", create=True) as mock_sm:
            mock_sm.SecretManagerServiceClient.return_value = MagicMock()
            gcp_mod = __import__("routerbot.core.secrets.gcp", fromlist=["_HAS_GCP"])
            original = gcp_mod._HAS_GCP
            gcp_mod._HAS_GCP = True
            try:
                from routerbot.core.secrets.gcp import GCPSecretManagerBackend

                backend = GCPSecretManagerBackend()
                with pytest.raises(SecretResolutionError, match="Invalid GCP secret path"):
                    backend.get_secret("only-one-part")
            finally:
                gcp_mod._HAS_GCP = original

    def test_get_secret_api_error(self) -> None:
        with patch("routerbot.core.secrets.gcp.secretmanager", create=True) as mock_sm:
            mock_client = MagicMock()
            mock_client.access_secret_version.side_effect = Exception("Permission denied")
            mock_sm.SecretManagerServiceClient.return_value = mock_client

            gcp_mod = __import__("routerbot.core.secrets.gcp", fromlist=["_HAS_GCP"])
            original = gcp_mod._HAS_GCP
            gcp_mod._HAS_GCP = True
            try:
                from routerbot.core.secrets.gcp import GCPSecretManagerBackend

                backend = GCPSecretManagerBackend()
                with pytest.raises(SecretResolutionError, match="Failed to retrieve"):
                    backend.get_secret("project/secret")
            finally:
                gcp_mod._HAS_GCP = original


# ═══════════════════════════════════════════════════════════════════════════
# Azure Key Vault backend tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAzureKeyVaultBackend:
    def test_import_error_without_azure(self) -> None:
        from routerbot.core.secrets import azure as azure_mod

        original = azure_mod._HAS_AZURE
        azure_mod._HAS_AZURE = False
        try:
            with pytest.raises(ImportError, match="azure-keyvault-secrets"):
                azure_mod.AzureKeyVaultBackend()
        finally:
            azure_mod._HAS_AZURE = original

    def test_prefix(self) -> None:
        with (
            patch("routerbot.core.secrets.azure.DefaultAzureCredential", create=True) as mock_cred,
            patch("routerbot.core.secrets.azure.SecretClient", create=True),
        ):
            mock_cred.return_value = MagicMock()
            azure_mod = __import__("routerbot.core.secrets.azure", fromlist=["_HAS_AZURE"])
            original = azure_mod._HAS_AZURE
            azure_mod._HAS_AZURE = True
            try:
                from routerbot.core.secrets.azure import AzureKeyVaultBackend

                backend = AzureKeyVaultBackend()
                assert backend.prefix == "azure_keyvault"
            finally:
                azure_mod._HAS_AZURE = original

    def test_get_secret_two_part(self) -> None:
        with (
            patch("routerbot.core.secrets.azure.DefaultAzureCredential", create=True) as mock_cred,
            patch("routerbot.core.secrets.azure.SecretClient", create=True) as mock_sc_cls,
        ):
            mock_cred.return_value = MagicMock()
            mock_client = MagicMock()
            mock_secret = MagicMock()
            mock_secret.value = "azure-secret-value"
            mock_client.get_secret.return_value = mock_secret
            mock_sc_cls.return_value = mock_client

            azure_mod = __import__("routerbot.core.secrets.azure", fromlist=["_HAS_AZURE"])
            original = azure_mod._HAS_AZURE
            azure_mod._HAS_AZURE = True
            try:
                from routerbot.core.secrets.azure import AzureKeyVaultBackend

                backend = AzureKeyVaultBackend()
                result = backend.get_secret("my-vault/my-secret")
                assert result == "azure-secret-value"
                mock_client.get_secret.assert_called_once_with("my-secret", version=None)
            finally:
                azure_mod._HAS_AZURE = original

    def test_get_secret_three_part_with_version(self) -> None:
        with (
            patch("routerbot.core.secrets.azure.DefaultAzureCredential", create=True) as mock_cred,
            patch("routerbot.core.secrets.azure.SecretClient", create=True) as mock_sc_cls,
        ):
            mock_cred.return_value = MagicMock()
            mock_client = MagicMock()
            mock_secret = MagicMock()
            mock_secret.value = "versioned-azure"
            mock_client.get_secret.return_value = mock_secret
            mock_sc_cls.return_value = mock_client

            azure_mod = __import__("routerbot.core.secrets.azure", fromlist=["_HAS_AZURE"])
            original = azure_mod._HAS_AZURE
            azure_mod._HAS_AZURE = True
            try:
                from routerbot.core.secrets.azure import AzureKeyVaultBackend

                backend = AzureKeyVaultBackend()
                result = backend.get_secret("my-vault/my-secret/v1")
                assert result == "versioned-azure"
                mock_client.get_secret.assert_called_once_with("my-secret", version="v1")
            finally:
                azure_mod._HAS_AZURE = original

    def test_get_secret_invalid_path(self) -> None:
        with (
            patch("routerbot.core.secrets.azure.DefaultAzureCredential", create=True) as mock_cred,
            patch("routerbot.core.secrets.azure.SecretClient", create=True),
        ):
            mock_cred.return_value = MagicMock()
            azure_mod = __import__("routerbot.core.secrets.azure", fromlist=["_HAS_AZURE"])
            original = azure_mod._HAS_AZURE
            azure_mod._HAS_AZURE = True
            try:
                from routerbot.core.secrets.azure import AzureKeyVaultBackend

                backend = AzureKeyVaultBackend()
                with pytest.raises(SecretResolutionError, match="Invalid Azure Key Vault path"):
                    backend.get_secret("only-one")
            finally:
                azure_mod._HAS_AZURE = original

    def test_get_secret_none_value_raises(self) -> None:
        with (
            patch("routerbot.core.secrets.azure.DefaultAzureCredential", create=True) as mock_cred,
            patch("routerbot.core.secrets.azure.SecretClient", create=True) as mock_sc_cls,
        ):
            mock_cred.return_value = MagicMock()
            mock_client = MagicMock()
            mock_secret = MagicMock()
            mock_secret.value = None
            mock_client.get_secret.return_value = mock_secret
            mock_sc_cls.return_value = mock_client

            azure_mod = __import__("routerbot.core.secrets.azure", fromlist=["_HAS_AZURE"])
            original = azure_mod._HAS_AZURE
            azure_mod._HAS_AZURE = True
            try:
                from routerbot.core.secrets.azure import AzureKeyVaultBackend

                backend = AzureKeyVaultBackend()
                with pytest.raises(SecretResolutionError, match="has no value"):
                    backend.get_secret("vault/secret")
            finally:
                azure_mod._HAS_AZURE = original


# ═══════════════════════════════════════════════════════════════════════════
# HashiCorp Vault backend tests
# ═══════════════════════════════════════════════════════════════════════════


class TestHashiCorpVaultBackend:
    def test_import_error_without_hvac(self) -> None:
        from routerbot.core.secrets import vault as vault_mod

        original = vault_mod._HAS_HVAC
        vault_mod._HAS_HVAC = False
        try:
            with pytest.raises(ImportError, match="hvac is required"):
                vault_mod.HashiCorpVaultBackend()
        finally:
            vault_mod._HAS_HVAC = original

    def test_prefix(self) -> None:
        with patch("routerbot.core.secrets.vault.hvac", create=True) as mock_hvac:
            mock_hvac.Client.return_value = MagicMock()
            vault_mod = __import__("routerbot.core.secrets.vault", fromlist=["_HAS_HVAC"])
            original = vault_mod._HAS_HVAC
            vault_mod._HAS_HVAC = True
            try:
                from routerbot.core.secrets.vault import HashiCorpVaultBackend

                backend = HashiCorpVaultBackend(token="test-token")
                assert backend.prefix == "vault"
            finally:
                vault_mod._HAS_HVAC = original

    def test_get_secret_single_key(self) -> None:
        with patch("routerbot.core.secrets.vault.hvac", create=True) as mock_hvac:
            mock_client = MagicMock()
            mock_client.secrets.kv.v2.read_secret_version.return_value = {
                "data": {"data": {"api_key": "sk-from-vault"}}
            }
            mock_hvac.Client.return_value = mock_client

            vault_mod = __import__("routerbot.core.secrets.vault", fromlist=["_HAS_HVAC"])
            original = vault_mod._HAS_HVAC
            vault_mod._HAS_HVAC = True
            try:
                from routerbot.core.secrets.vault import HashiCorpVaultBackend

                backend = HashiCorpVaultBackend(token="test-token")
                result = backend.get_secret("my-app")
                # Single key -> returns value directly
                assert result == "sk-from-vault"
            finally:
                vault_mod._HAS_HVAC = original

    def test_get_secret_multi_key_returns_json(self) -> None:
        with patch("routerbot.core.secrets.vault.hvac", create=True) as mock_hvac:
            mock_client = MagicMock()
            mock_client.secrets.kv.v2.read_secret_version.return_value = {
                "data": {"data": {"key1": "v1", "key2": "v2"}}
            }
            mock_hvac.Client.return_value = mock_client

            vault_mod = __import__("routerbot.core.secrets.vault", fromlist=["_HAS_HVAC"])
            original = vault_mod._HAS_HVAC
            vault_mod._HAS_HVAC = True
            try:
                from routerbot.core.secrets.vault import HashiCorpVaultBackend

                backend = HashiCorpVaultBackend(token="test-token")
                result = backend.get_secret("multi-key")
                parsed = json.loads(result)
                assert parsed == {"key1": "v1", "key2": "v2"}
            finally:
                vault_mod._HAS_HVAC = original

    def test_get_secret_no_data_raises(self) -> None:
        with patch("routerbot.core.secrets.vault.hvac", create=True) as mock_hvac:
            mock_client = MagicMock()
            mock_client.secrets.kv.v2.read_secret_version.return_value = None
            mock_hvac.Client.return_value = mock_client

            vault_mod = __import__("routerbot.core.secrets.vault", fromlist=["_HAS_HVAC"])
            original = vault_mod._HAS_HVAC
            vault_mod._HAS_HVAC = True
            try:
                from routerbot.core.secrets.vault import HashiCorpVaultBackend

                backend = HashiCorpVaultBackend(token="test-token")
                with pytest.raises(SecretResolutionError, match="returned no data"):
                    backend.get_secret("empty")
            finally:
                vault_mod._HAS_HVAC = original

    def test_get_secret_empty_data_raises(self) -> None:
        with patch("routerbot.core.secrets.vault.hvac", create=True) as mock_hvac:
            mock_client = MagicMock()
            mock_client.secrets.kv.v2.read_secret_version.return_value = {
                "data": {"data": {}}
            }
            mock_hvac.Client.return_value = mock_client

            vault_mod = __import__("routerbot.core.secrets.vault", fromlist=["_HAS_HVAC"])
            original = vault_mod._HAS_HVAC
            vault_mod._HAS_HVAC = True
            try:
                from routerbot.core.secrets.vault import HashiCorpVaultBackend

                backend = HashiCorpVaultBackend(token="test-token")
                with pytest.raises(SecretResolutionError, match="empty data"):
                    backend.get_secret("empty-data")
            finally:
                vault_mod._HAS_HVAC = original

    def test_get_secret_api_error(self) -> None:
        with patch("routerbot.core.secrets.vault.hvac", create=True) as mock_hvac:
            mock_client = MagicMock()
            mock_client.secrets.kv.v2.read_secret_version.side_effect = Exception("Vault sealed")
            mock_hvac.Client.return_value = mock_client

            vault_mod = __import__("routerbot.core.secrets.vault", fromlist=["_HAS_HVAC"])
            original = vault_mod._HAS_HVAC
            vault_mod._HAS_HVAC = True
            try:
                from routerbot.core.secrets.vault import HashiCorpVaultBackend

                backend = HashiCorpVaultBackend(token="test-token")
                with pytest.raises(SecretResolutionError, match="Failed to retrieve"):
                    backend.get_secret("sealed-secret")
            finally:
                vault_mod._HAS_HVAC = original

    def test_env_var_defaults(self) -> None:
        with patch("routerbot.core.secrets.vault.hvac", create=True) as mock_hvac:
            mock_hvac.Client.return_value = MagicMock()
            vault_mod = __import__("routerbot.core.secrets.vault", fromlist=["_HAS_HVAC"])
            original = vault_mod._HAS_HVAC
            vault_mod._HAS_HVAC = True
            try:
                from routerbot.core.secrets.vault import HashiCorpVaultBackend

                with patch.dict("os.environ", {"VAULT_ADDR": "http://vault:8200", "VAULT_TOKEN": "s.test"}):
                    backend = HashiCorpVaultBackend()
                    assert backend.prefix == "vault"
                    mock_hvac.Client.assert_called_with(
                        url="http://vault:8200", token="s.test"
                    )
            finally:
                vault_mod._HAS_HVAC = original


# ═══════════════════════════════════════════════════════════════════════════
# Config integration tests
# ═══════════════════════════════════════════════════════════════════════════


class TestConfigIntegration:
    """Test that secret references are resolved during load_config."""

    def test_secret_refs_resolved_during_load_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from routerbot.core import config as config_mod

        monkeypatch.setenv("ROUTERBOT_MASTER_KEY", "test-master-key")

        resolver = SecretResolver()
        resolver.register_backend(FakeBackend("aws_secret", {"openai-key": "sk-from-aws"}))

        config_mod.configure_secret_resolver(resolver)
        try:
            cfg = config_mod.load_config(config_data={
                "model_list": [
                    {
                        "model_name": "gpt-4o",
                        "provider_params": {
                            "model": "openai/gpt-4o",
                            "api_key": "aws_secret/openai-key",
                        },
                    }
                ],
                "general_settings": {"master_key": "test-master-key"},
            })
            assert cfg.model_list[0].provider_params.api_key == "sk-from-aws"
        finally:
            config_mod.reset_secret_resolver()

    def test_no_resolver_passthrough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without a resolver, secret refs pass through as plain strings."""
        from routerbot.core import config as config_mod

        config_mod.reset_secret_resolver()
        monkeypatch.setenv("ROUTERBOT_MASTER_KEY", "key")
        cfg = config_mod.load_config(config_data={
            "model_list": [
                {
                    "model_name": "test",
                    "provider_params": {
                        "model": "openai/test",
                        "api_key": "aws_secret/some-key",
                    },
                }
            ],
            "general_settings": {"master_key": "key"},
        })
        # Without resolver, the string passes through unchanged
        assert cfg.model_list[0].provider_params.api_key == "aws_secret/some-key"

    def test_mixed_env_and_secret_refs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Both os.environ/ and aws_secret/ refs in the same config."""
        from routerbot.core import config as config_mod

        monkeypatch.setenv("MY_KEY", "env-value")
        monkeypatch.setenv("ROUTERBOT_MASTER_KEY", "m")

        resolver = SecretResolver()
        resolver.register_backend(FakeBackend("aws_secret", {"other": "secret-value"}))
        config_mod.configure_secret_resolver(resolver)
        try:
            cfg = config_mod.load_config(config_data={
                "model_list": [
                    {
                        "model_name": "m1",
                        "provider_params": {"model": "openai/a", "api_key": "aws_secret/other"},
                    },
                    {
                        "model_name": "m2",
                        "provider_params": {"model": "openai/b", "api_key": "os.environ/MY_KEY"},
                    },
                ],
                "general_settings": {"master_key": "m"},
            })
            assert cfg.model_list[0].provider_params.api_key == "secret-value"
            assert cfg.model_list[1].provider_params.api_key == "env-value"
        finally:
            config_mod.reset_secret_resolver()

    def test_reset_secret_resolver(self) -> None:
        from routerbot.core import config as config_mod

        resolver = SecretResolver()
        config_mod.configure_secret_resolver(resolver)
        assert config_mod._secret_resolver is resolver
        config_mod.reset_secret_resolver()
        assert config_mod._secret_resolver is None
