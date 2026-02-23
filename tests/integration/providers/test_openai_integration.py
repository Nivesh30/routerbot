"""Integration tests for the OpenAI provider.

These tests make real HTTP calls to api.openai.com and are skipped when
``OPENAI_API_KEY`` is not set.

Run with:
    OPENAI_API_KEY=sk-... pytest tests/integration/providers/test_openai_integration.py -v -m integration
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from routerbot.core.types import CompletionRequest, EmbeddingRequest, Message
from routerbot.providers.openai.provider import OpenAIProvider

from .conftest import assert_valid_chat_response, assert_valid_embedding_response, rate_limit

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = pytest.mark.integration


@pytest.fixture
async def provider(openai_api_key: str) -> AsyncGenerator[OpenAIProvider, None]:
    p = OpenAIProvider(api_key=openai_api_key)
    yield p
    await p.close()


@pytest.mark.asyncio
async def test_chat_completion(provider: OpenAIProvider) -> None:
    """Non-streaming chat completion returns a valid response."""
    request = CompletionRequest(
        model="gpt-4o-mini",
        messages=[Message(role="user", content="Say 'hello' and nothing else.")],
        max_tokens=20,
        temperature=0,
    )
    result = await provider.chat_completion(request)
    data = result.model_dump()
    assert_valid_chat_response(data)
    assert result.usage is not None
    assert result.usage.total_tokens > 0
    await rate_limit()


@pytest.mark.asyncio
async def test_chat_completion_streaming(provider: OpenAIProvider) -> None:
    """Streaming chat completion yields chunks with content."""
    request = CompletionRequest(
        model="gpt-4o-mini",
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
async def test_embedding(provider: OpenAIProvider) -> None:
    """Embedding returns a non-empty float vector."""
    request = EmbeddingRequest(
        model="text-embedding-3-small",
        input=["Hello, world!"],
    )
    result = await provider.embedding(request)
    data = result.model_dump()
    assert_valid_embedding_response(data)
    assert len(result.data[0].embedding) == 1536  # text-embedding-3-small default
    await rate_limit()


@pytest.mark.asyncio
async def test_health_check(provider: OpenAIProvider) -> None:
    """Health check returns True for a valid API key."""
    result = await provider.health_check()
    assert result is True
    await rate_limit()
