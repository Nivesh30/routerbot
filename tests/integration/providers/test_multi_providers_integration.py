"""Integration tests for Groq, Mistral, DeepSeek, and Cohere providers.

These tests make real HTTP calls to each provider's API and are skipped when
the corresponding API keys are not set.

Run with:
    GROQ_API_KEY=... pytest tests/integration/providers/test_multi_providers_integration.py -v -m integration -k groq
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from routerbot.core.types import CompletionRequest, EmbeddingRequest, Message
from routerbot.providers.cohere.provider import CohereProvider
from routerbot.providers.deepseek.provider import DeepSeekProvider
from routerbot.providers.groq.provider import GroqProvider
from routerbot.providers.mistral.provider import MistralProvider

from .conftest import assert_valid_chat_response, rate_limit

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = pytest.mark.integration


# ═══════════════════════════════════════════════════════════════════════════
# Groq
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
async def groq_provider(groq_api_key: str) -> AsyncGenerator[GroqProvider, None]:
    p = GroqProvider(api_key=groq_api_key)
    yield p
    await p.close()


@pytest.mark.asyncio
async def test_groq_chat_completion(groq_provider: GroqProvider) -> None:
    """Groq non-streaming chat completion returns a valid response."""
    request = CompletionRequest(
        model="llama-3.1-8b-instant",
        messages=[Message(role="user", content="Say 'hello' and nothing else.")],
        max_tokens=20,
        temperature=0,
    )
    result = await groq_provider.chat_completion(request)
    data = result.model_dump()
    assert_valid_chat_response(data)
    assert result.usage is not None
    await rate_limit()


@pytest.mark.asyncio
async def test_groq_streaming(groq_provider: GroqProvider) -> None:
    """Groq streaming yields chunks."""
    request = CompletionRequest(
        model="llama-3.1-8b-instant",
        messages=[Message(role="user", content="Count to 3.")],
        max_tokens=30,
        temperature=0,
    )
    chunks = []
    async for chunk in groq_provider.chat_completion_stream(request):
        chunks.append(chunk)

    assert len(chunks) > 0
    content = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert len(content) > 0
    await rate_limit()


# ═══════════════════════════════════════════════════════════════════════════
# Mistral
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
async def mistral_provider(mistral_api_key: str) -> AsyncGenerator[MistralProvider, None]:
    p = MistralProvider(api_key=mistral_api_key)
    yield p
    await p.close()


@pytest.mark.asyncio
async def test_mistral_chat_completion(mistral_provider: MistralProvider) -> None:
    """Mistral non-streaming chat completion returns a valid response."""
    request = CompletionRequest(
        model="open-mistral-7b",
        messages=[Message(role="user", content="Say 'hello' and nothing else.")],
        max_tokens=20,
        temperature=0,
    )
    result = await mistral_provider.chat_completion(request)
    data = result.model_dump()
    assert_valid_chat_response(data)
    await rate_limit()


@pytest.mark.asyncio
async def test_mistral_streaming(mistral_provider: MistralProvider) -> None:
    """Mistral streaming yields chunks."""
    request = CompletionRequest(
        model="open-mistral-7b",
        messages=[Message(role="user", content="Count to 3.")],
        max_tokens=30,
        temperature=0,
    )
    chunks = []
    async for chunk in mistral_provider.chat_completion_stream(request):
        chunks.append(chunk)

    assert len(chunks) > 0
    content = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert len(content) > 0
    await rate_limit()


# ═══════════════════════════════════════════════════════════════════════════
# DeepSeek
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
async def deepseek_provider(deepseek_api_key: str) -> AsyncGenerator[DeepSeekProvider, None]:
    p = DeepSeekProvider(api_key=deepseek_api_key)
    yield p
    await p.close()


@pytest.mark.asyncio
async def test_deepseek_chat_completion(deepseek_provider: DeepSeekProvider) -> None:
    """DeepSeek non-streaming chat completion returns a valid response."""
    request = CompletionRequest(
        model="deepseek-chat",
        messages=[Message(role="user", content="Say 'hello' and nothing else.")],
        max_tokens=20,
        temperature=0,
    )
    result = await deepseek_provider.chat_completion(request)
    data = result.model_dump()
    assert_valid_chat_response(data)
    await rate_limit()


@pytest.mark.asyncio
async def test_deepseek_streaming(deepseek_provider: DeepSeekProvider) -> None:
    """DeepSeek streaming yields chunks."""
    request = CompletionRequest(
        model="deepseek-chat",
        messages=[Message(role="user", content="Count to 3.")],
        max_tokens=30,
        temperature=0,
    )
    chunks = []
    async for chunk in deepseek_provider.chat_completion_stream(request):
        chunks.append(chunk)

    assert len(chunks) > 0
    content = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert len(content) > 0
    await rate_limit()


# ═══════════════════════════════════════════════════════════════════════════
# Cohere
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
async def cohere_provider(cohere_api_key: str) -> AsyncGenerator[CohereProvider, None]:
    p = CohereProvider(api_key=cohere_api_key)
    yield p
    await p.close()


@pytest.mark.asyncio
async def test_cohere_chat_completion(cohere_provider: CohereProvider) -> None:
    """Cohere non-streaming chat completion returns a valid response."""
    request = CompletionRequest(
        model="command-r",
        messages=[Message(role="user", content="Say 'hello' and nothing else.")],
        max_tokens=20,
        temperature=0,
    )
    result = await cohere_provider.chat_completion(request)
    data = result.model_dump()
    assert_valid_chat_response(data)
    await rate_limit()


@pytest.mark.asyncio
async def test_cohere_embedding(cohere_provider: CohereProvider) -> None:
    """Cohere embedding returns a non-empty float vector."""
    request = EmbeddingRequest(
        model="embed-english-v3.0",
        input=["Hello, world!"],
    )
    result = await cohere_provider.embedding(request)
    assert len(result.data) == 1
    assert len(result.data[0].embedding) > 0
    await rate_limit()
