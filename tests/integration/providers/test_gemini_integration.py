"""Integration tests for the Gemini provider.

These tests make real HTTP calls to generativelanguage.googleapis.com and are
skipped when ``GEMINI_API_KEY`` is not set.

Run with:
    GEMINI_API_KEY=... pytest tests/integration/providers/test_gemini_integration.py -v -m integration
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from routerbot.core.types import CompletionRequest, EmbeddingRequest, Message
from routerbot.providers.gemini.provider import GeminiProvider

from .conftest import assert_valid_chat_response, assert_valid_embedding_response, rate_limit

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = pytest.mark.integration


@pytest.fixture
async def provider(gemini_api_key: str) -> AsyncGenerator[GeminiProvider, None]:
    p = GeminiProvider(api_key=gemini_api_key)
    yield p
    await p.close()


@pytest.mark.asyncio
async def test_chat_completion(provider: GeminiProvider) -> None:
    """Non-streaming chat completion returns a valid response."""
    request = CompletionRequest(
        model="gemini-1.5-flash",
        messages=[Message(role="user", content="Say 'hello' and nothing else.")],
        max_tokens=20,
        temperature=0,
    )
    result = await provider.chat_completion(request)
    data = result.model_dump()
    assert_valid_chat_response(data)
    await rate_limit()


@pytest.mark.asyncio
async def test_chat_completion_streaming(provider: GeminiProvider) -> None:
    """Streaming chat completion yields chunks with content."""
    request = CompletionRequest(
        model="gemini-1.5-flash",
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
async def test_embedding(provider: GeminiProvider) -> None:
    """Text embedding returns a non-empty float vector."""
    request = EmbeddingRequest(
        model="text-embedding-004",
        input=["Hello, world!"],
    )
    result = await provider.embedding(request)
    data = result.model_dump()
    assert_valid_embedding_response(data)
    assert len(result.data[0].embedding) > 0
    await rate_limit()
