"""Shared fixtures and helpers for provider integration tests.

These tests make **real** HTTP calls to provider APIs and are skipped
automatically when the required environment variables are not set.

Running integration tests locally:
    OPENAI_API_KEY=sk-... make test-integration
    # or select a specific provider:
    ANTHROPIC_API_KEY=sk-ant-... pytest tests/integration -k anthropic -v

All integration tests are tagged with ``@pytest.mark.integration`` and are
excluded from the default ``pytest`` run. They require real API keys and
may incur costs.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Rate-limiting helpers
# ---------------------------------------------------------------------------

# Minimum delay between API calls (seconds) to avoid 429s during test runs.
_DEFAULT_RATE_LIMIT_DELAY = float(os.getenv("INTEGRATION_RATE_LIMIT_DELAY", "1.0"))


async def rate_limit(delay: float = _DEFAULT_RATE_LIMIT_DELAY) -> None:
    """Sleep for ``delay`` seconds between API calls."""
    await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# Environment variable helpers
# ---------------------------------------------------------------------------


def _require_env(var: str) -> str:
    """Return the value of *var* or skip the test if it is not set."""
    value = os.getenv(var)
    if not value:
        pytest.skip(f"Environment variable {var!r} is not set — skipping integration test")
    return value


# ---------------------------------------------------------------------------
# Shared pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def openai_api_key() -> str:
    """OpenAI API key — skips all OpenAI integration tests if not set."""
    return _require_env("OPENAI_API_KEY")


@pytest.fixture(scope="session")
def anthropic_api_key() -> str:
    """Anthropic API key — skips all Anthropic integration tests if not set."""
    return _require_env("ANTHROPIC_API_KEY")


@pytest.fixture(scope="session")
def azure_api_key() -> str:
    """Azure OpenAI API key — skips Azure tests if not set."""
    return _require_env("AZURE_OPENAI_API_KEY")


@pytest.fixture(scope="session")
def azure_endpoint() -> str:
    """Azure OpenAI endpoint URL — skips Azure tests if not set."""
    return _require_env("AZURE_OPENAI_ENDPOINT")


@pytest.fixture(scope="session")
def azure_deployment() -> str:
    """Azure OpenAI deployment name (model alias)."""
    return os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")


@pytest.fixture(scope="session")
def bedrock_access_key() -> str:
    """AWS access key ID for Bedrock — skips Bedrock tests if not set."""
    return _require_env("AWS_ACCESS_KEY_ID")


@pytest.fixture(scope="session")
def bedrock_secret_key() -> str:
    """AWS secret access key for Bedrock."""
    return _require_env("AWS_SECRET_ACCESS_KEY")


@pytest.fixture(scope="session")
def bedrock_region() -> str:
    """AWS region for Bedrock (defaults to us-east-1)."""
    return os.getenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(scope="session")
def gemini_api_key() -> str:
    """Google Gemini API key — skips Gemini tests if not set."""
    return _require_env("GEMINI_API_KEY")


@pytest.fixture(scope="session")
def groq_api_key() -> str:
    """Groq API key — skips Groq tests if not set."""
    return _require_env("GROQ_API_KEY")


@pytest.fixture(scope="session")
def mistral_api_key() -> str:
    """Mistral API key — skips Mistral tests if not set."""
    return _require_env("MISTRAL_API_KEY")


@pytest.fixture(scope="session")
def cohere_api_key() -> str:
    """Cohere API key — skips Cohere tests if not set."""
    return _require_env("COHERE_API_KEY")


@pytest.fixture(scope="session")
def deepseek_api_key() -> str:
    """DeepSeek API key — skips DeepSeek tests if not set."""
    return _require_env("DEEPSEEK_API_KEY")


@pytest.fixture(scope="session")
def ollama_base_url() -> str:
    """Ollama server base URL (defaults to localhost)."""
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


# ---------------------------------------------------------------------------
# Common request payloads
# ---------------------------------------------------------------------------


def make_simple_chat_request_dict(model: str) -> dict[str, Any]:
    """Return a minimal chat completion request payload."""
    return {
        "model": model,
        "messages": [{"role": "user", "content": "Say 'hello' and nothing else."}],
        "max_tokens": 20,
        "temperature": 0,
    }


def make_simple_embedding_request_dict(model: str) -> dict[str, Any]:
    """Return a minimal embedding request payload."""
    return {
        "model": model,
        "input": ["Hello, world!"],
    }


# ---------------------------------------------------------------------------
# Response validators
# ---------------------------------------------------------------------------


def assert_valid_chat_response(data: dict[str, Any]) -> None:
    """Assert that *data* looks like a valid OpenAI chat completion response."""
    assert data.get("object") == "chat.completion", f"Expected object='chat.completion', got {data.get('object')!r}"
    assert "choices" in data, "Response missing 'choices'"
    assert len(data["choices"]) > 0, "Response has empty 'choices'"
    choice = data["choices"][0]
    assert "message" in choice, "Choice missing 'message'"
    message = choice["message"]
    assert message.get("role") == "assistant", f"Expected role='assistant', got {message.get('role')!r}"
    assert isinstance(message.get("content"), str), "message.content is not a string"
    assert choice.get("finish_reason") in ("stop", "length", "tool_calls", "content_filter", None)


def assert_valid_streaming_chunks(chunks: list[dict[str, Any]]) -> None:
    """Assert that *chunks* form a valid sequence of OpenAI streaming chunks."""
    assert len(chunks) > 0, "Expected at least one streaming chunk"
    # All intermediate chunks should have object = chat.completion.chunk
    for chunk in chunks:
        assert chunk.get("object") == "chat.completion.chunk", (
            f"Expected 'chat.completion.chunk', got {chunk.get('object')!r}"
        )
    # Last meaningful chunk should have a finish_reason
    finish_reasons = [c["choices"][0].get("finish_reason") for c in chunks if c.get("choices")]
    assert any(r is not None for r in finish_reasons), "No chunk had a non-None finish_reason"


def assert_valid_embedding_response(data: dict[str, Any]) -> None:
    """Assert that *data* looks like a valid OpenAI embedding response."""
    assert data.get("object") == "list", f"Expected object='list', got {data.get('object')!r}"
    assert "data" in data, "Response missing 'data'"
    assert len(data["data"]) > 0, "Response has empty 'data'"
    item = data["data"][0]
    assert item.get("object") == "embedding", f"Expected object='embedding', got {item.get('object')!r}"
    assert isinstance(item.get("embedding"), list), "embedding is not a list"
    assert len(item["embedding"]) > 0, "embedding vector is empty"


# ---------------------------------------------------------------------------
# Timing utilities
# ---------------------------------------------------------------------------


class Timer:
    """Simple context manager for timing code blocks."""

    def __init__(self) -> None:
        self.elapsed: float = 0.0
        self._start: float = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: object) -> None:
        self.elapsed = time.perf_counter() - self._start
