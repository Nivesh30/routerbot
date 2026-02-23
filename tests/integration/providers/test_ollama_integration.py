"""Integration tests for the Ollama provider.

These tests require a running Ollama instance. Set ``OLLAMA_BASE_URL``
(defaults to ``http://localhost:11434``) to point to your server.

Ensure you have pulled a model first:
    ollama pull llama3.2

Run with:
    pytest tests/integration/providers/test_ollama_integration.py -v -m integration
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from routerbot.core.types import CompletionRequest, EmbeddingRequest, Message
from routerbot.providers.ollama.provider import OllamaProvider

from .conftest import assert_valid_chat_response, rate_limit

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = pytest.mark.integration

# Model to use for integration tests — override via OLLAMA_TEST_MODEL env var
OLLAMA_TEST_MODEL = os.getenv("OLLAMA_TEST_MODEL", "llama3.2")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")


@pytest.fixture
async def provider(ollama_base_url: str) -> AsyncGenerator[OllamaProvider, None]:
    p = OllamaProvider(api_base=ollama_base_url)
    # Check server is reachable — skip if not
    reachable = await p.health_check()
    if not reachable:
        await p.close()
        pytest.skip(f"Ollama server at {ollama_base_url!r} is not reachable")
    yield p
    await p.close()


@pytest.mark.asyncio
async def test_health_check(ollama_base_url: str) -> None:
    """Health check returns True when Ollama is running."""
    p = OllamaProvider(api_base=ollama_base_url)
    result = await p.health_check()
    if not result:
        pytest.skip("Ollama not reachable")
    assert result is True
    await p.close()


@pytest.mark.asyncio
async def test_chat_completion(provider: OllamaProvider) -> None:
    """Non-streaming chat completion returns a valid OpenAI-compatible response."""
    request = CompletionRequest(
        model=OLLAMA_TEST_MODEL,
        messages=[Message(role="user", content="Say 'hello' and nothing else.")],
        max_tokens=20,
        temperature=0,
    )
    result = await provider.chat_completion(request)
    data = result.model_dump()
    assert_valid_chat_response(data)
    assert result.usage is not None
    assert result.usage.total_tokens > 0
    await rate_limit(delay=0.5)


@pytest.mark.asyncio
async def test_chat_completion_streaming(provider: OllamaProvider) -> None:
    """Streaming chat completion yields chunks with content."""
    request = CompletionRequest(
        model=OLLAMA_TEST_MODEL,
        messages=[Message(role="user", content="Count to 3.")],
        max_tokens=40,
        temperature=0,
    )
    chunks = []
    async for chunk in provider.chat_completion_stream(request):
        chunks.append(chunk)

    assert len(chunks) > 0
    content = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert len(content) > 0
    # Last chunk should have finish_reason and usage
    last = chunks[-1]
    assert last.choices[0].finish_reason is not None
    await rate_limit(delay=0.5)


@pytest.mark.asyncio
async def test_embedding(provider: OllamaProvider) -> None:
    """Embedding returns a non-empty float vector for each input."""
    request = EmbeddingRequest(
        model=OLLAMA_EMBED_MODEL,
        input=["Hello, world!", "Goodbye, world!"],
    )
    result = await provider.embedding(request)
    assert len(result.data) == 2
    for item in result.data:
        assert len(item.embedding) > 0
    await rate_limit(delay=0.5)
