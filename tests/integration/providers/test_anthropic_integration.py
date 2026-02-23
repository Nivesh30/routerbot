"""Integration tests for the Anthropic provider.

These tests make real HTTP calls to api.anthropic.com and are skipped when
``ANTHROPIC_API_KEY`` is not set.

Run with:
    ANTHROPIC_API_KEY=sk-ant-... pytest tests/integration/providers/test_anthropic_integration.py -v -m integration
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from routerbot.core.types import CompletionRequest, Message
from routerbot.providers.anthropic.provider import AnthropicProvider

from .conftest import assert_valid_chat_response, rate_limit

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = pytest.mark.integration


@pytest.fixture
async def provider(anthropic_api_key: str) -> AsyncGenerator[AnthropicProvider, None]:
    p = AnthropicProvider(api_key=anthropic_api_key)
    yield p
    await p.close()


@pytest.mark.asyncio
async def test_chat_completion(provider: AnthropicProvider) -> None:
    """Non-streaming chat completion returns a valid OpenAI-compatible response."""
    request = CompletionRequest(
        model="claude-3-haiku-20240307",
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
async def test_chat_completion_streaming(provider: AnthropicProvider) -> None:
    """Streaming chat completion yields chunks with content."""
    request = CompletionRequest(
        model="claude-3-haiku-20240307",
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
async def test_health_check(provider: AnthropicProvider) -> None:
    """Health check returns True for a valid API key."""
    result = await provider.health_check()
    assert result is True
    await rate_limit()
