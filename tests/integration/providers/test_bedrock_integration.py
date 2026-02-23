"""Integration tests for the AWS Bedrock provider.

These tests require:
- ``AWS_ACCESS_KEY_ID``
- ``AWS_SECRET_ACCESS_KEY``
- ``AWS_DEFAULT_REGION`` (optional, defaults to us-east-1)

Run with:
    AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \\
        pytest tests/integration/providers/test_bedrock_integration.py -v -m integration
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from routerbot.core.types import CompletionRequest, Message
from routerbot.providers.bedrock.provider import BedrockProvider

from .conftest import assert_valid_chat_response, rate_limit

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

pytestmark = pytest.mark.integration


@pytest.fixture
async def provider(
    bedrock_access_key: str, bedrock_secret_key: str, bedrock_region: str
) -> AsyncGenerator[BedrockProvider, None]:
    p = BedrockProvider(
        aws_access_key_id=bedrock_access_key,
        aws_secret_access_key=bedrock_secret_key,
        aws_region=bedrock_region,
    )
    yield p
    await p.close()


@pytest.mark.asyncio
async def test_chat_completion_claude(provider: BedrockProvider) -> None:
    """Non-streaming chat completion via Bedrock Converse API."""
    request = CompletionRequest(
        model="anthropic.claude-3-haiku-20240307-v1:0",
        messages=[Message(role="user", content="Say 'hello' and nothing else.")],
        max_tokens=20,
        temperature=0,
    )
    result = await provider.chat_completion(request)
    data = result.model_dump()
    assert_valid_chat_response(data)
    assert result.usage is not None
    await rate_limit(delay=2.0)  # Bedrock throttles more aggressively


@pytest.mark.asyncio
async def test_chat_completion_streaming(provider: BedrockProvider) -> None:
    """Streaming chat completion via Bedrock EventStream."""
    request = CompletionRequest(
        model="anthropic.claude-3-haiku-20240307-v1:0",
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
    await rate_limit(delay=2.0)
