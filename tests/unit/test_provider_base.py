"""Tests for provider base framework: base class, registry, compat adapter, transforms."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from routerbot.core.enums import FinishReason
from routerbot.core.exceptions import (
    AuthenticationError,
    ModelNotFoundError,
    ProviderError,
    RateLimitError,
    ServiceUnavailableError,
)
from routerbot.core.types import (
    CompletionRequest,
    CompletionResponse,
    CompletionResponseChunk,
    EmbeddingRequest,
    EmbeddingResponse,
    Message,
)
from routerbot.providers.base import BaseProvider
from routerbot.providers.openai_compat import OpenAICompatibleProvider
from routerbot.providers.registry import (
    close_all_providers,
    get_provider,
    get_provider_class,
    list_providers,
    parse_model_string,
    register_provider,
    reset_registry,
)
from routerbot.providers.transform import (
    build_completion_response,
    extract_system_message,
    messages_to_dicts,
    normalize_finish_reason,
    normalize_role,
)

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset the provider registry between tests."""
    reset_registry()
    yield
    reset_registry()


def _make_request(model: str = "gpt-4o", content: str = "Hello") -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[Message(role="user", content=content)],
    )


def _make_response_json(model: str = "gpt-4o", content: str = "Hi there!") -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }


def _make_chunk_json(content: str = "Hi", finish_reason: str | None = None) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if content:
        delta["content"] = content
    if finish_reason:
        delta["role"] = "assistant"
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "gpt-4o",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


# ═══════════════════════════════════════════════════════════════════════════
# BaseProvider tests
# ═══════════════════════════════════════════════════════════════════════════


class TestBaseProvider:
    """Tests for the abstract BaseProvider."""

    def test_cannot_instantiate_directly(self):
        """BaseProvider is abstract — cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseProvider()  # type: ignore[abstract]

    def test_concrete_subclass(self):
        """A subclass implementing abstract methods can be instantiated."""

        class DummyProvider(BaseProvider):
            provider_name = "dummy"

            async def chat_completion(self, request, **kwargs):
                return NotImplemented

            async def chat_completion_stream(self, request, **kwargs):
                yield NotImplemented  # pragma: no cover

        p = DummyProvider(api_key="sk-test", api_base="https://example.com")
        assert p.provider_name == "dummy"
        assert p.api_key == "sk-test"
        assert p.api_base == "https://example.com"

    def test_default_headers_with_key(self):
        """_build_headers includes Authorization when api_key set."""

        class DummyProvider(BaseProvider):
            provider_name = "dummy"

            async def chat_completion(self, request, **kwargs):
                return NotImplemented

            async def chat_completion_stream(self, request, **kwargs):
                yield NotImplemented  # pragma: no cover

        p = DummyProvider(api_key="sk-test")
        headers = p._build_headers()
        assert headers["Authorization"] == "Bearer sk-test"
        assert "User-Agent" in headers

    def test_default_headers_without_key(self):
        class DummyProvider(BaseProvider):
            provider_name = "dummy"

            async def chat_completion(self, request, **kwargs):
                return NotImplemented

            async def chat_completion_stream(self, request, **kwargs):
                yield NotImplemented  # pragma: no cover

        p = DummyProvider()
        headers = p._build_headers()
        assert "Authorization" not in headers

    def test_custom_headers(self):
        class DummyProvider(BaseProvider):
            provider_name = "dummy"

            async def chat_completion(self, request, **kwargs):
                return NotImplemented

            async def chat_completion_stream(self, request, **kwargs):
                yield NotImplemented  # pragma: no cover

        p = DummyProvider(custom_headers={"X-Custom": "value"})
        headers = p._build_headers()
        assert headers["X-Custom"] == "value"

    def test_repr(self):
        class DummyProvider(BaseProvider):
            provider_name = "dummy"

            async def chat_completion(self, request, **kwargs):
                return NotImplemented

            async def chat_completion_stream(self, request, **kwargs):
                yield NotImplemented  # pragma: no cover

        p = DummyProvider(api_base="https://example.com")
        assert "DummyProvider" in repr(p)
        assert "dummy" in repr(p)

    @pytest.mark.asyncio
    async def test_optional_methods_raise(self):
        """Unimplemented optional methods raise NotImplementedError."""

        class DummyProvider(BaseProvider):
            provider_name = "dummy"

            async def chat_completion(self, request, **kwargs):
                return NotImplemented

            async def chat_completion_stream(self, request, **kwargs):
                yield NotImplemented  # pragma: no cover

        p = DummyProvider()
        req = _make_request()
        with pytest.raises(NotImplementedError, match="dummy"):
            await p.embedding(req)  # type: ignore[arg-type]
        with pytest.raises(NotImplementedError, match="image"):
            await p.image_generation(req)  # type: ignore[arg-type]
        with pytest.raises(NotImplementedError, match="speech"):
            await p.audio_speech(req)  # type: ignore[arg-type]
        with pytest.raises(NotImplementedError, match="transcription"):
            await p.audio_transcription(req)  # type: ignore[arg-type]
        with pytest.raises(NotImplementedError, match="rerank"):
            await p.rerank(req)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_close(self):
        class DummyProvider(BaseProvider):
            provider_name = "dummy"

            async def chat_completion(self, request, **kwargs):
                return NotImplemented

            async def chat_completion_stream(self, request, **kwargs):
                yield NotImplemented  # pragma: no cover

        p = DummyProvider(api_base="https://example.com")
        _ = p.client  # force creation
        assert p._client is not None
        await p.close()
        assert p._client is None

    @pytest.mark.asyncio
    async def test_context_manager(self):
        class DummyProvider(BaseProvider):
            provider_name = "dummy"

            async def chat_completion(self, request, **kwargs):
                return NotImplemented

            async def chat_completion_stream(self, request, **kwargs):
                yield NotImplemented  # pragma: no cover

        async with DummyProvider(api_base="https://example.com") as p:
            _ = p.client
        assert p._client is None


# ═══════════════════════════════════════════════════════════════════════════
# Registry tests
# ═══════════════════════════════════════════════════════════════════════════


class TestParseModelString:
    def test_with_provider(self):
        assert parse_model_string("openai/gpt-4o") == ("openai", "gpt-4o")

    def test_with_anthropic(self):
        assert parse_model_string("anthropic/claude-sonnet-4-20250514") == (
            "anthropic",
            "claude-sonnet-4-20250514",
        )

    def test_without_provider(self):
        assert parse_model_string("gpt-4o") == ("openai", "gpt-4o")

    def test_with_whitespace(self):
        assert parse_model_string(" openai / gpt-4o ") == ("openai", "gpt-4o")

    def test_lowercase(self):
        assert parse_model_string("OPENAI/GPT-4o") == ("openai", "GPT-4o")


class TestRegistration:
    def test_register_valid(self):
        register_provider("openai_compat", OpenAICompatibleProvider)
        assert "openai_compat" in list_providers()

    def test_register_invalid_class(self):
        with pytest.raises(TypeError, match="must subclass BaseProvider"):
            register_provider("bad", str)  # type: ignore[arg-type]

    def test_get_provider_class_registered(self):
        register_provider("openai_compat", OpenAICompatibleProvider)
        cls = get_provider_class("openai_compat")
        assert cls is OpenAICompatibleProvider

    def test_get_provider_class_fallback(self):
        """Unknown provider falls back to openai_compat."""
        register_provider("openai_compat", OpenAICompatibleProvider)
        cls = get_provider_class("some_unknown")
        assert cls is OpenAICompatibleProvider

    def test_get_provider_class_not_found(self):
        """No compat fallback registered → ModelNotFoundError."""
        with pytest.raises(ModelNotFoundError):
            get_provider_class("nonexistent")

    def test_get_provider(self):
        register_provider("openai_compat", OpenAICompatibleProvider)
        provider = get_provider("openai_compat/gpt-4o", api_key="sk-test")
        assert isinstance(provider, OpenAICompatibleProvider)

    def test_get_provider_cached(self):
        register_provider("openai_compat", OpenAICompatibleProvider)
        p1 = get_provider("openai_compat/gpt-4o", api_key="sk-test")
        p2 = get_provider("openai_compat/gpt-4o", api_key="sk-test")
        assert p1 is p2

    def test_get_provider_different_keys(self):
        register_provider("openai_compat", OpenAICompatibleProvider)
        p1 = get_provider("openai_compat/gpt-4o", api_key="sk-a")
        p2 = get_provider("openai_compat/gpt-4o", api_key="sk-b")
        assert p1 is not p2

    def test_list_providers(self):
        register_provider("openai_compat", OpenAICompatibleProvider)
        providers = list_providers()
        assert "openai_compat" in providers

    @pytest.mark.asyncio
    async def test_close_all(self):
        register_provider("openai_compat", OpenAICompatibleProvider)
        p = get_provider("openai_compat/test", api_key="sk-test")
        _ = p.client
        await close_all_providers()


# ═══════════════════════════════════════════════════════════════════════════
# OpenAICompatibleProvider tests
# ═══════════════════════════════════════════════════════════════════════════


class TestOpenAICompatible:
    """Tests for the generic OpenAI-compatible provider."""

    @pytest.mark.asyncio
    async def test_chat_completion(self, respx_mock):
        """Non-streaming chat completion works."""
        respx_mock.post("https://api.test.com/chat/completions").mock(
            return_value=httpx.Response(200, json=_make_response_json())
        )

        provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.test.com")
        result = await provider.chat_completion(_make_request())

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hi there!"
        assert result.usage.total_tokens == 8
        await provider.close()

    @pytest.mark.asyncio
    async def test_chat_completion_stream(self, respx_mock):
        """Streaming yields CompletionResponseChunk objects."""
        import json

        chunks = [
            f"data: {json.dumps(_make_chunk_json('Hello'))}",
            f"data: {json.dumps(_make_chunk_json(' world'))}",
            "data: [DONE]",
        ]
        sse_content = "\n\n".join(chunks) + "\n\n"

        respx_mock.post("https://api.test.com/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=sse_content.encode(),
                headers={"Content-Type": "text/event-stream"},
            )
        )

        provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.test.com")
        collected: list[CompletionResponseChunk] = []
        async for chunk in provider.chat_completion_stream(_make_request()):
            collected.append(chunk)

        assert len(collected) == 2
        assert collected[0].choices[0].delta.content == "Hello"
        assert collected[1].choices[0].delta.content == " world"
        await provider.close()

    @pytest.mark.asyncio
    async def test_embedding(self, respx_mock):
        emb_resp = {
            "object": "list",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }
        respx_mock.post("https://api.test.com/embeddings").mock(return_value=httpx.Response(200, json=emb_resp))

        provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.test.com")
        req = EmbeddingRequest(model="text-embedding-3-small", input="Hello")
        result = await provider.embedding(req)

        assert isinstance(result, EmbeddingResponse)
        assert len(result.data) == 1
        await provider.close()

    @pytest.mark.asyncio
    async def test_auth_error(self, respx_mock):
        respx_mock.post("https://api.test.com/chat/completions").mock(
            return_value=httpx.Response(
                401,
                json={"error": {"message": "Invalid API key"}},
            )
        )

        provider = OpenAICompatibleProvider(api_key="bad", api_base="https://api.test.com")
        with pytest.raises(AuthenticationError):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, respx_mock):
        respx_mock.post("https://api.test.com/chat/completions").mock(
            return_value=httpx.Response(
                429,
                json={"error": {"message": "Rate limited"}},
            )
        )

        provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.test.com")
        with pytest.raises(RateLimitError):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_server_error(self, respx_mock):
        respx_mock.post("https://api.test.com/chat/completions").mock(
            return_value=httpx.Response(500, json={"error": {"message": "Internal server error"}})
        )

        provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.test.com")
        with pytest.raises(ServiceUnavailableError):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_generic_error(self, respx_mock):
        respx_mock.post("https://api.test.com/chat/completions").mock(
            return_value=httpx.Response(400, json={"error": {"message": "Bad request"}})
        )

        provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.test.com")
        with pytest.raises(ProviderError):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_timeout_error(self, respx_mock):
        respx_mock.post("https://api.test.com/chat/completions").mock(side_effect=httpx.ReadTimeout("read timed out"))

        provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.test.com")
        with pytest.raises(ProviderError, match="timed out"):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_health_check_ok(self, respx_mock):
        respx_mock.get("https://api.test.com/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))

        provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.test.com")
        assert await provider.health_check() is True
        await provider.close()

    @pytest.mark.asyncio
    async def test_health_check_fail(self, respx_mock):
        respx_mock.get("https://api.test.com/v1/models").mock(side_effect=httpx.ConnectError("Connection refused"))

        provider = OpenAICompatibleProvider(api_key="sk-test", api_base="https://api.test.com")
        assert await provider.health_check() is False
        await provider.close()

    def test_provider_label(self):
        p = OpenAICompatibleProvider(provider_label="my_custom")
        assert p.provider_name == "my_custom"


# ═══════════════════════════════════════════════════════════════════════════
# Transform tests
# ═══════════════════════════════════════════════════════════════════════════


class TestNormalizeRole:
    def test_standard_roles(self):
        assert normalize_role("user") == "user"
        assert normalize_role("assistant") == "assistant"
        assert normalize_role("system") == "system"

    def test_mapped_roles(self):
        assert normalize_role("human") == "user"
        assert normalize_role("ai") == "assistant"
        assert normalize_role("bot") == "assistant"
        assert normalize_role("model") == "assistant"
        assert normalize_role("developer") == "developer"

    def test_unknown_passthrough(self):
        assert normalize_role("ipython") == "ipython"

    def test_case_insensitive(self):
        assert normalize_role("HUMAN") == "user"
        assert normalize_role("AI") == "assistant"


class TestNormalizeFinishReason:
    def test_none(self):
        assert normalize_finish_reason(None) is None

    def test_anthropic(self):
        assert normalize_finish_reason("end_turn") == FinishReason.STOP
        assert normalize_finish_reason("max_tokens") == FinishReason.LENGTH
        assert normalize_finish_reason("tool_use") == FinishReason.TOOL_CALLS

    def test_google(self):
        assert normalize_finish_reason("STOP") == FinishReason.STOP
        assert normalize_finish_reason("MAX_TOKENS") == FinishReason.LENGTH
        assert normalize_finish_reason("SAFETY") == FinishReason.CONTENT_FILTER

    def test_cohere(self):
        assert normalize_finish_reason("COMPLETE") == FinishReason.STOP

    def test_openai_passthrough(self):
        assert normalize_finish_reason("stop") == "stop"
        assert normalize_finish_reason("length") == "length"

    def test_unknown_passthrough(self):
        assert normalize_finish_reason("custom_reason") == "custom_reason"


class TestBuildCompletionResponse:
    def test_basic(self):
        resp = build_completion_response(
            model="gpt-4o",
            content="Hello!",
            prompt_tokens=5,
            completion_tokens=2,
        )
        assert isinstance(resp, CompletionResponse)
        assert resp.model == "gpt-4o"
        assert resp.choices[0].message.content == "Hello!"
        assert resp.usage.total_tokens == 7
        assert resp.id.startswith("chatcmpl-")

    def test_custom_role_and_reason(self):
        resp = build_completion_response(
            model="test",
            content="Done",
            role="system",
            finish_reason=FinishReason.LENGTH,
        )
        assert resp.choices[0].message.role == "system"
        assert resp.choices[0].finish_reason == FinishReason.LENGTH


class TestMessagesToDicts:
    def test_basic(self):
        msgs = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi"),
        ]
        result = messages_to_dicts(msgs)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"

    def test_excludes_none(self):
        msgs = [Message(role="user", content="Hi")]
        result = messages_to_dicts(msgs)
        assert "name" not in result[0]
        assert "tool_calls" not in result[0]


class TestExtractSystemMessage:
    def test_with_system(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        system, remaining = extract_system_message(messages)
        assert system == "You are helpful."
        assert len(remaining) == 1
        assert remaining[0]["role"] == "user"

    def test_without_system(self):
        messages = [{"role": "user", "content": "Hi"}]
        system, remaining = extract_system_message(messages)
        assert system is None
        assert len(remaining) == 1

    def test_multiple_system(self):
        messages = [
            {"role": "system", "content": "First."},
            {"role": "system", "content": "Second."},
            {"role": "user", "content": "Hi"},
        ]
        system, remaining = extract_system_message(messages)
        assert system == "First.\nSecond."
        assert len(remaining) == 1

    def test_empty(self):
        system, remaining = extract_system_message([])
        assert system is None
        assert remaining == []
