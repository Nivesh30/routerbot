"""Tests for the Azure OpenAI provider."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from routerbot.core.exceptions import AuthenticationError
from routerbot.core.types import (
    CompletionRequest,
    CompletionResponse,
    CompletionResponseChunk,
    EmbeddingRequest,
    EmbeddingResponse,
    Message,
)
from routerbot.providers.azure.config import (
    DEFAULT_API_VERSION,
    SUPPORTED_API_VERSIONS,
    build_azure_base_url,
)
from routerbot.providers.azure.provider import AzureOpenAIProvider

FIXTURES = Path(__file__).parent.parent / "fixtures" / "openai"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _make_provider(
    resource: str = "my-resource",
    deployment: str = "my-gpt4o",
    api_key: str = "test-key",
    **kwargs: Any,
) -> AzureOpenAIProvider:
    return AzureOpenAIProvider(
        resource_name=resource,
        deployment_name=deployment,
        api_key=api_key,
        **kwargs,
    )


def _make_request(
    model: str = "gpt-4o",
    content: str = "Hello",
    **kwargs: Any,
) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[Message(role="user", content=content)],
        **kwargs,
    )


def _sse_lines(*data_items: str | dict[str, Any]) -> str:
    lines = []
    for item in data_items:
        if isinstance(item, dict):
            lines.append(f"data: {json.dumps(item)}")
        else:
            lines.append(f"data: {item}")
    return "\n\n".join(lines) + "\n\n"


# ═══════════════════════════════════════════════════════════════════════════
# Config tests
# ═══════════════════════════════════════════════════════════════════════════


class TestConfig:
    def test_default_api_version(self):
        assert DEFAULT_API_VERSION in SUPPORTED_API_VERSIONS

    def test_supported_api_versions_not_empty(self):
        assert len(SUPPORTED_API_VERSIONS) > 5

    def test_build_azure_base_url_basic(self):
        url = build_azure_base_url("myresource", "my-gpt4o")
        assert url == "https://myresource.openai.azure.com/openai/deployments/my-gpt4o"

    def test_build_azure_base_url_strips_slashes(self):
        url = build_azure_base_url("myresource/", "/my-gpt4o/")
        assert "//openai/deployments" not in url
        assert "my-gpt4o" in url

    def test_build_azure_base_url_format(self):
        url = build_azure_base_url("contoso", "gpt-4-turbo")
        assert url.startswith("https://contoso.openai.azure.com")
        assert "gpt-4-turbo" in url


# ═══════════════════════════════════════════════════════════════════════════
# Provider instantiation
# ═══════════════════════════════════════════════════════════════════════════


class TestAzureProviderInit:
    def test_correct_api_base(self):
        p = _make_provider()
        assert "my-resource.openai.azure.com" in p.api_base
        assert "my-gpt4o" in p.api_base

    def test_api_version_stored(self):
        p = _make_provider(api_version="2024-02-01")
        assert p.api_version == "2024-02-01"

    def test_default_api_version(self):
        p = _make_provider()
        assert p.api_version == DEFAULT_API_VERSION

    def test_api_key_stored(self):
        p = _make_provider(api_key="my-key")
        assert p.api_key == "my-key"

    def test_azure_ad_token_stored(self):
        p = AzureOpenAIProvider(
            resource_name="r",
            deployment_name="d",
            azure_ad_token="my-token",
        )
        assert p.azure_ad_token == "my-token"

    def test_requires_auth(self):
        with pytest.raises(ValueError, match="api_key or azure_ad_token"):
            AzureOpenAIProvider(resource_name="r", deployment_name="d")

    def test_custom_api_base_override(self):
        p = AzureOpenAIProvider(
            resource_name="r",
            deployment_name="d",
            api_key="key",
            api_base="https://custom.endpoint.com/openai/deployments/custom",
        )
        assert p.api_base == "https://custom.endpoint.com/openai/deployments/custom"

    def test_resource_name_stored(self):
        p = _make_provider(resource="contoso")
        assert p.resource_name == "contoso"

    def test_deployment_name_stored(self):
        p = _make_provider(deployment="gpt-4o-deploy")
        assert p.deployment_name == "gpt-4o-deploy"


# ═══════════════════════════════════════════════════════════════════════════
# Header tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAzureHeaders:
    def test_api_key_header(self):
        p = _make_provider(api_key="my-azure-key")
        headers = p._build_headers()
        assert headers.get("api-key") == "my-azure-key"

    def test_no_authorization_bearer_with_api_key(self):
        p = _make_provider(api_key="my-azure-key")
        headers = p._build_headers()
        # Must NOT have Authorization: Bearer for API key auth
        auth = headers.get("Authorization", "")
        assert not auth.startswith("Bearer") or auth == ""

    def test_azure_ad_token_header(self):
        p = AzureOpenAIProvider(
            resource_name="r",
            deployment_name="d",
            azure_ad_token="my-ad-token",
        )
        headers = p._build_headers()
        assert headers.get("Authorization") == "Bearer my-ad-token"
        assert "api-key" not in headers

    def test_no_api_key_header_for_ad_auth(self):
        p = AzureOpenAIProvider(
            resource_name="r",
            deployment_name="d",
            azure_ad_token="my-ad-token",
        )
        headers = p._build_headers()
        assert "api-key" not in headers

    def test_custom_headers_included(self):
        p = AzureOpenAIProvider(
            resource_name="r",
            deployment_name="d",
            api_key="key",
            custom_headers={"X-Custom": "value"},
        )
        headers = p._build_headers()
        assert headers["X-Custom"] == "value"


# ═══════════════════════════════════════════════════════════════════════════
# HTTP client: api-version query param
# ═══════════════════════════════════════════════════════════════════════════


class TestAzureClientParams:
    def test_client_has_api_version_param(self):
        p = _make_provider(api_version="2024-02-01")
        client = p.client
        # httpx stores default params in _merged_params
        # We can verify by checking the client's params
        assert "api-version" in dict(client.params)
        assert dict(client.params)["api-version"] == "2024-02-01"

    def test_client_reused(self):
        p = _make_provider()
        c1 = p.client
        c2 = p.client
        assert c1 is c2


# ═══════════════════════════════════════════════════════════════════════════
# Chat completion
# ═══════════════════════════════════════════════════════════════════════════


class TestAzureChatCompletion:
    @pytest.mark.asyncio
    async def test_chat_completion(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")

        base_url = build_azure_base_url("my-resource", "my-gpt4o")
        respx_mock.post(f"{base_url}/chat/completions").mock(return_value=httpx.Response(200, json=fixture))

        p = _make_provider()
        result = await p.chat_completion(_make_request())

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hello! How can I help you today?"
        await p.close()

    @pytest.mark.asyncio
    async def test_api_version_in_request(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        captured_urls: list[str] = []

        def capture(request: httpx.Request) -> httpx.Response:
            captured_urls.append(str(request.url))
            return httpx.Response(200, json=fixture)

        base_url = build_azure_base_url("my-resource", "my-gpt4o")
        respx_mock.post(f"{base_url}/chat/completions").mock(side_effect=capture)

        p = _make_provider(api_version="2024-02-01")
        await p.chat_completion(_make_request())

        assert len(captured_urls) == 1
        assert "api-version=2024-02-01" in captured_urls[0]
        await p.close()

    @pytest.mark.asyncio
    async def test_api_key_sent_as_header(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        captured_headers: list[dict[str, str]] = []

        def capture(request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            return httpx.Response(200, json=fixture)

        base_url = build_azure_base_url("my-resource", "my-gpt4o")
        respx_mock.post(f"{base_url}/chat/completions").mock(side_effect=capture)

        p = _make_provider(api_key="az-key-123")
        await p.chat_completion(_make_request())

        assert len(captured_headers) == 1
        assert captured_headers[0].get("api-key") == "az-key-123"
        assert "authorization" not in captured_headers[0] or not captured_headers[0]["authorization"].startswith(
            "Bearer az"
        )
        await p.close()

    @pytest.mark.asyncio
    async def test_auth_error(self, respx_mock):
        base_url = build_azure_base_url("my-resource", "my-gpt4o")
        respx_mock.post(f"{base_url}/chat/completions").mock(
            return_value=httpx.Response(
                401,
                json={"error": {"message": "Invalid API key", "type": "authentication_error"}},
            )
        )

        p = _make_provider()
        with pytest.raises(AuthenticationError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_stream(self, respx_mock):
        chunk1 = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-4o",
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
        }
        chunk2 = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-4o",
            "choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": None}],
        }
        chunk3 = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-4o",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }

        sse = _sse_lines(chunk1, chunk2, chunk3, "[DONE]")
        base_url = build_azure_base_url("my-resource", "my-gpt4o")
        respx_mock.post(f"{base_url}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=sse.encode(),
                headers={"Content-Type": "text/event-stream"},
            )
        )

        p = _make_provider()
        chunks: list[CompletionResponseChunk] = []
        async for chunk in p.chat_completion_stream(_make_request()):
            chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[1].choices[0].delta.content == "Hi"
        assert chunks[2].choices[0].finish_reason == "stop"
        await p.close()


# ═══════════════════════════════════════════════════════════════════════════
# Embeddings
# ═══════════════════════════════════════════════════════════════════════════


class TestAzureEmbeddings:
    @pytest.mark.asyncio
    async def test_embedding(self, respx_mock):
        fixture = _load_fixture("embedding.json")
        base_url = build_azure_base_url("my-resource", "my-gpt4o")
        respx_mock.post(f"{base_url}/embeddings").mock(return_value=httpx.Response(200, json=fixture))

        p = _make_provider()
        req = EmbeddingRequest(model="text-embedding-3-small", input="Hello")
        result = await p.embedding(req)

        assert isinstance(result, EmbeddingResponse)
        assert len(result.data) == 1
        await p.close()


# ═══════════════════════════════════════════════════════════════════════════
# Azure AD authentication
# ═══════════════════════════════════════════════════════════════════════════


class TestAzureADAuth:
    @pytest.mark.asyncio
    async def test_ad_token_sent_as_bearer(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        captured_headers: list[dict[str, str]] = []

        def capture(request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            return httpx.Response(200, json=fixture)

        base_url = build_azure_base_url("my-resource", "my-gpt4o")
        respx_mock.post(f"{base_url}/chat/completions").mock(side_effect=capture)

        p = AzureOpenAIProvider(
            resource_name="my-resource",
            deployment_name="my-gpt4o",
            azure_ad_token="ad-bearer-token-xyz",
        )
        await p.chat_completion(_make_request())

        assert len(captured_headers) == 1
        auth = captured_headers[0].get("authorization", "")
        assert auth == "Bearer ad-bearer-token-xyz"
        assert "api-key" not in captured_headers[0]
        await p.close()

    def test_ad_auth_no_api_key_required(self):
        p = AzureOpenAIProvider(
            resource_name="r",
            deployment_name="d",
            azure_ad_token="token",
        )
        assert p.azure_ad_token == "token"
        assert p.api_key is None


# ═══════════════════════════════════════════════════════════════════════════
# Provider inherits OpenAI behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestAzureInheritsOpenAI:
    def test_provider_name(self):
        p = _make_provider()
        assert p.provider_name == "azure"

    @pytest.mark.asyncio
    async def test_image_generation(self, respx_mock):
        from routerbot.core.types import ImageRequest, ImageResponse

        fixture = _load_fixture("image_generation.json")
        base_url = build_azure_base_url("my-resource", "my-gpt4o")
        respx_mock.post(f"{base_url}/images/generations").mock(return_value=httpx.Response(200, json=fixture))

        p = _make_provider()
        req = ImageRequest(model="dall-e-3", prompt="A cat")
        result = await p.image_generation(req)

        assert isinstance(result, ImageResponse)
        await p.close()
