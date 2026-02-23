"""Tests for Groq, Mistral, DeepSeek, and Cohere providers (Task 2.7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from routerbot.core.exceptions import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
    ServiceUnavailableError,
)
from routerbot.core.types import (
    CompletionRequest,
    CompletionResponse,
    EmbeddingRequest,
    Message,
)
from routerbot.providers.cohere.config import (
    COHERE_MODELS,
)
from routerbot.providers.cohere.config import (
    FINISH_REASON_MAP as COHERE_FINISH_REASON_MAP,
)
from routerbot.providers.cohere.provider import CohereProvider
from routerbot.providers.cohere.transform import cohere_response_to_openai
from routerbot.providers.deepseek.provider import DeepSeekProvider
from routerbot.providers.groq.provider import GROQ_BASE_URL, GroqProvider
from routerbot.providers.mistral.provider import MISTRAL_BASE_URL, MistralProvider

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(provider: str, name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / provider / name).read_text())


def _make_request(
    model: str = "test-model",
    content: str = "Hello",
    **kwargs: Any,
) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[Message(role="user", content=content)],
        **kwargs,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Groq Provider
# ═══════════════════════════════════════════════════════════════════════════


class TestGroqProvider:
    def test_default_base_url(self):
        p = GroqProvider(api_key="gsk_test")
        assert p.api_base == GROQ_BASE_URL

    def test_custom_base_url(self):
        p = GroqProvider(api_key="gsk_test", api_base="https://mock.groq.test/v1")
        assert p.api_base == "https://mock.groq.test/v1"

    def test_provider_name(self):
        p = GroqProvider(api_key="gsk_test")
        assert p.provider_name == "groq"

    def test_api_key_stored(self):
        p = GroqProvider(api_key="gsk_mykey")
        assert p.api_key == "gsk_mykey"

    def test_bearer_auth_header(self):
        p = GroqProvider(api_key="gsk_test", api_base="https://mock.groq.test/v1")
        h = p._build_headers()
        assert h.get("Authorization") == "Bearer gsk_test"

    @pytest.mark.asyncio
    async def test_chat_completion(self, respx_mock):
        fixture = _load_fixture("groq", "chat_completion.json")
        respx_mock.post("https://mock.groq.test/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        p = GroqProvider(api_key="gsk_test", api_base="https://mock.groq.test/v1")
        result = await p.chat_completion(_make_request(model="llama-3.3-70b-versatile"))

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hello from Groq!"
        assert result.choices[0].finish_reason == "stop"
        await p.close()

    @pytest.mark.asyncio
    async def test_auth_error(self, respx_mock):
        respx_mock.post("https://mock.groq.test/v1/chat/completions").mock(
            return_value=httpx.Response(401, json={"error": {"message": "Invalid key"}})
        )

        p = GroqProvider(api_key="bad_key", api_base="https://mock.groq.test/v1")
        with pytest.raises(AuthenticationError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, respx_mock):
        respx_mock.post("https://mock.groq.test/v1/chat/completions").mock(
            return_value=httpx.Response(429, json={"error": {"message": "Rate limited"}})
        )

        p = GroqProvider(api_key="key", api_base="https://mock.groq.test/v1")
        with pytest.raises(RateLimitError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_server_error(self, respx_mock):
        respx_mock.post("https://mock.groq.test/v1/chat/completions").mock(
            return_value=httpx.Response(500, json={"error": {"message": "Internal"}})
        )

        p = GroqProvider(api_key="key", api_base="https://mock.groq.test/v1")
        with pytest.raises(ServiceUnavailableError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_registers_in_registry(self):
        from routerbot.providers.registry import get_provider_class

        cls = get_provider_class("groq")
        assert cls is GroqProvider


# ═══════════════════════════════════════════════════════════════════════════
# Mistral Provider
# ═══════════════════════════════════════════════════════════════════════════


class TestMistralProvider:
    def test_default_base_url(self):
        p = MistralProvider(api_key="mistral_test")
        assert p.api_base == MISTRAL_BASE_URL

    def test_provider_name(self):
        p = MistralProvider(api_key="k")
        assert p.provider_name == "mistral"

    def test_bearer_auth_header(self):
        p = MistralProvider(api_key="sk_test", api_base="https://mock.mistral.test/v1")
        h = p._build_headers()
        assert "Bearer sk_test" in h.get("Authorization", "")

    @pytest.mark.asyncio
    async def test_chat_completion(self, respx_mock):
        fixture = _load_fixture("mistral", "chat_completion.json")
        respx_mock.post("https://mock.mistral.test/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        p = MistralProvider(api_key="sk_test", api_base="https://mock.mistral.test/v1")
        result = await p.chat_completion(_make_request(model="mistral-large-latest"))

        assert result.choices[0].message.content == "Hello from Mistral!"
        await p.close()

    @pytest.mark.asyncio
    async def test_registers_in_registry(self):
        from routerbot.providers.registry import get_provider_class

        cls = get_provider_class("mistral")
        assert cls is MistralProvider


# ═══════════════════════════════════════════════════════════════════════════
# DeepSeek Provider
# ═══════════════════════════════════════════════════════════════════════════


class TestDeepSeekProvider:
    def test_default_base_url(self):
        p = DeepSeekProvider(api_key="ds_test")
        assert "deepseek" in p.api_base

    def test_provider_name(self):
        p = DeepSeekProvider(api_key="k")
        assert p.provider_name == "deepseek"

    def test_bearer_auth_header(self):
        p = DeepSeekProvider(api_key="sk_ds_test", api_base="https://mock.deepseek.test/v1")
        h = p._build_headers()
        assert "Bearer sk_ds_test" in h.get("Authorization", "")

    @pytest.mark.asyncio
    async def test_chat_completion(self, respx_mock):
        fixture = _load_fixture("deepseek", "chat_completion.json")
        respx_mock.post("https://mock.deepseek.test/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        p = DeepSeekProvider(api_key="sk_test", api_base="https://mock.deepseek.test/v1")
        result = await p.chat_completion(_make_request(model="deepseek-chat"))

        assert result.choices[0].message.content == "Hello from DeepSeek!"
        await p.close()

    @pytest.mark.asyncio
    async def test_registers_in_registry(self):
        from routerbot.providers.registry import get_provider_class

        cls = get_provider_class("deepseek")
        assert cls is DeepSeekProvider


# ═══════════════════════════════════════════════════════════════════════════
# Cohere Transform
# ═══════════════════════════════════════════════════════════════════════════


class TestCohereTransform:
    def test_finish_reason_complete(self):
        assert COHERE_FINISH_REASON_MAP["COMPLETE"] == "stop"

    def test_finish_reason_max_tokens(self):
        assert COHERE_FINISH_REASON_MAP["MAX_TOKENS"] == "length"

    def test_finish_reason_tool_call(self):
        assert COHERE_FINISH_REASON_MAP["TOOL_CALL"] == "tool_calls"

    def test_cohere_response_basic(self):
        data = _load_fixture("cohere", "chat_completion.json")
        result = cohere_response_to_openai(data, "command-r-plus")

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hello from Cohere!"
        assert result.choices[0].finish_reason == "stop"
        assert result.usage.prompt_tokens == 6
        assert result.usage.completion_tokens == 8

    def test_cohere_response_tool_call(self):
        data = _load_fixture("cohere", "chat_completion_tool_use.json")
        result = cohere_response_to_openai(data, "command-r-plus")

        assert result.choices[0].finish_reason == "tool_calls"
        tc = result.choices[0].message.tool_calls
        assert tc is not None
        assert tc[0].function.name == "get_weather"
        args = json.loads(tc[0].function.arguments)
        assert args["location"] == "London"

    def test_cohere_models_not_empty(self):
        assert len(COHERE_MODELS) > 0
        assert "command-r-plus" in COHERE_MODELS


# ═══════════════════════════════════════════════════════════════════════════
# Cohere Provider
# ═══════════════════════════════════════════════════════════════════════════


class TestCohereProvider:
    def test_provider_name(self):
        p = CohereProvider(api_key="test")
        assert p.provider_name == "cohere"

    def test_default_base_url(self):
        p = CohereProvider(api_key="test")
        assert "cohere" in p.api_base.lower()

    def test_bearer_auth_header(self):
        p = CohereProvider(api_key="co_test", api_base="https://mock.cohere.test/v2")
        h = p._build_headers()
        assert h.get("Authorization") == "Bearer co_test"

    @pytest.mark.asyncio
    async def test_basic_completion(self, respx_mock):
        fixture = _load_fixture("cohere", "chat_completion.json")
        respx_mock.post("https://mock.cohere.test/v2/chat").mock(return_value=httpx.Response(200, json=fixture))

        p = CohereProvider(api_key="co_test", api_base="https://mock.cohere.test/v2")
        result = await p.chat_completion(_make_request(model="command-r-plus"))

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hello from Cohere!"
        assert result.choices[0].finish_reason == "stop"
        await p.close()

    @pytest.mark.asyncio
    async def test_tool_use_response(self, respx_mock):
        fixture = _load_fixture("cohere", "chat_completion_tool_use.json")
        respx_mock.post("https://mock.cohere.test/v2/chat").mock(return_value=httpx.Response(200, json=fixture))

        p = CohereProvider(api_key="co_test", api_base="https://mock.cohere.test/v2")
        result = await p.chat_completion(_make_request(model="command-r-plus"))

        assert result.choices[0].finish_reason == "tool_calls"
        tc = result.choices[0].message.tool_calls
        assert tc is not None
        assert tc[0].function.name == "get_weather"
        await p.close()

    @pytest.mark.asyncio
    async def test_auth_error(self, respx_mock):
        respx_mock.post("https://mock.cohere.test/v2/chat").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )

        p = CohereProvider(api_key="bad_key", api_base="https://mock.cohere.test/v2")
        with pytest.raises(AuthenticationError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, respx_mock):
        respx_mock.post("https://mock.cohere.test/v2/chat").mock(
            return_value=httpx.Response(429, json={"message": "Rate limited"})
        )

        p = CohereProvider(api_key="key", api_base="https://mock.cohere.test/v2")
        with pytest.raises(RateLimitError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_server_error(self, respx_mock):
        respx_mock.post("https://mock.cohere.test/v2/chat").mock(
            return_value=httpx.Response(500, json={"message": "Server error"})
        )

        p = CohereProvider(api_key="key", api_base="https://mock.cohere.test/v2")
        with pytest.raises(ServiceUnavailableError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_embedding(self, respx_mock):
        cohere_embed_response = {
            "id": "embed-test",
            "embeddings": {"float": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]},
            "texts": ["hello", "world"],
        }
        respx_mock.post("https://mock.cohere.test/v2/embed").mock(
            return_value=httpx.Response(200, json=cohere_embed_response)
        )

        p = CohereProvider(api_key="key", api_base="https://mock.cohere.test/v2")
        result = await p.embedding(EmbeddingRequest(model="embed-english-v3.0", input=["hello", "world"]))

        assert len(result.data) == 2
        assert result.data[0].embedding == [0.1, 0.2, 0.3]
        assert result.data[1].embedding == [0.4, 0.5, 0.6]
        await p.close()

    @pytest.mark.asyncio
    async def test_image_generation_raises(self):
        from routerbot.core.types import ImageRequest

        p = CohereProvider(api_key="key")
        with pytest.raises(ProviderError, match="image generation"):
            await p.image_generation(ImageRequest(model="any", prompt="a cat"))

    @pytest.mark.asyncio
    async def test_registers_in_registry(self):
        from routerbot.providers.registry import get_provider_class

        cls = get_provider_class("cohere")
        assert cls is CohereProvider
