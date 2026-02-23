"""Integration tests for the Azure OpenAI provider.

These tests require:
- ``AZURE_OPENAI_API_KEY``
- ``AZURE_OPENAI_ENDPOINT`` (e.g. https://myresource.openai.azure.com)
- ``AZURE_OPENAI_DEPLOYMENT`` (optional, defaults to gpt-4o-mini)

Run with:
    AZURE_OPENAI_API_KEY=... AZURE_OPENAI_ENDPOINT=https://... \\
        pytest tests/integration/providers/test_azure_integration.py -v -m integration
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from routerbot.core.types import CompletionRequest, EmbeddingRequest, Message
from routerbot.providers.azure.provider import AzureOpenAIProvider

from .conftest import assert_valid_chat_response, assert_valid_embedding_response, rate_limit

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = pytest.mark.integration


@pytest.fixture
async def provider(
    azure_api_key: str, azure_endpoint: str, azure_deployment: str
) -> AsyncGenerator[AzureOpenAIProvider, None]:
    p = AzureOpenAIProvider(
        api_key=azure_api_key,
        azure_endpoint=azure_endpoint,
        api_version="2024-05-01-preview",
    )
    yield p
    await p.close()


@pytest.mark.asyncio
async def test_chat_completion(provider: AzureOpenAIProvider, azure_deployment: str) -> None:
    """Non-streaming chat completion via Azure returns a valid response."""
    request = CompletionRequest(
        model=azure_deployment,
        messages=[Message(role="user", content="Say 'hello' and nothing else.")],
        max_tokens=20,
        temperature=0,
    )
    result = await provider.chat_completion(request)
    data = result.model_dump()
    assert_valid_chat_response(data)
    assert result.usage is not None
    await rate_limit()


@pytest.mark.asyncio
async def test_chat_completion_streaming(provider: AzureOpenAIProvider, azure_deployment: str) -> None:
    """Streaming chat completion via Azure yields chunks."""
    request = CompletionRequest(
        model=azure_deployment,
        messages=[Message(role="user", content="Count to 3.")],
        max_tokens=30,
        temperature=0,
    )
    chunks = []
    async for chunk in provider.chat_completion_stream(request):
        chunks.append(chunk)

    assert len(chunks) > 0
    content = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert len(content) > 0
    await rate_limit()


@pytest.mark.asyncio
async def test_embedding(provider: AzureOpenAIProvider) -> None:
    """Azure OpenAI embedding returns a non-empty float vector."""
    embed_deployment = "text-embedding-ada-002"
    request = EmbeddingRequest(
        model=embed_deployment,
        input=["Hello, world!"],
    )
    result = await provider.embedding(request)
    data = result.model_dump()
    assert_valid_embedding_response(data)
    await rate_limit()
