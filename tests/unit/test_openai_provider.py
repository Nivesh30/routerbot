"""Tests for the OpenAI provider."""

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
    AudioTranscriptionRequest,
    AudioTranscriptionResponse,
    CompletionRequest,
    CompletionResponse,
    CompletionResponseChunk,
    EmbeddingRequest,
    EmbeddingResponse,
    ImageRequest,
    ImageResponse,
    Message,
)
from routerbot.providers.openai.config import (
    CHAT_MODELS,
    EMBEDDING_MODELS,
    IMAGE_MODELS,
    O_SERIES_MODELS,
)
from routerbot.providers.openai.provider import OpenAIProvider
from routerbot.providers.openai.transform import (
    _base_model_name,
    _convert_system_to_developer,
    prepare_chat_payload,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "openai"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _make_request(
    model: str = "gpt-4o",
    content: str = "Hello",
    **kwargs: Any,
) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[Message(role="user", content=content)],
        **kwargs,
    )


def _sse_lines(*data_items: str | dict[str, Any]) -> str:
    """Build SSE-formatted string from data items."""
    lines = []
    for item in data_items:
        if isinstance(item, dict):
            lines.append(f"data: {json.dumps(item)}")
        else:
            lines.append(f"data: {item}")
    return "\n\n".join(lines) + "\n\n"


# ═══════════════════════════════════════════════════════════════════════════
# Config tests
# ═══════════════════════════════════════════════════════════════════════════


class TestConfig:
    def test_chat_models_not_empty(self):
        assert len(CHAT_MODELS) > 10

    def test_gpt4o_in_models(self):
        assert "gpt-4o" in CHAT_MODELS

    def test_embedding_models(self):
        assert "text-embedding-3-small" in EMBEDDING_MODELS

    def test_image_models(self):
        assert "dall-e-3" in IMAGE_MODELS

    def test_o_series_models(self):
        assert "o1" in O_SERIES_MODELS
        assert "o3" in O_SERIES_MODELS


# ═══════════════════════════════════════════════════════════════════════════
# Transform tests
# ═══════════════════════════════════════════════════════════════════════════


class TestBaseModelName:
    def test_no_date(self):
        assert _base_model_name("gpt-4o") == "gpt-4o"

    def test_with_date(self):
        assert _base_model_name("gpt-4o-2024-11-20") == "gpt-4o"

    def test_o1_with_date(self):
        assert _base_model_name("o1-2024-12-17") == "o1"

    def test_o4_mini_with_date(self):
        assert _base_model_name("o4-mini-2025-04-16") == "o4-mini"

    def test_simple_model(self):
        assert _base_model_name("o1") == "o1"


class TestConvertSystemToDeveloper:
    def test_converts_system(self):
        payload = {
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hi"},
            ]
        }
        result = _convert_system_to_developer(payload)
        assert result["messages"][0]["role"] == "developer"
        assert result["messages"][1]["role"] == "user"

    def test_preserves_non_system(self):
        payload = {
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ]
        }
        result = _convert_system_to_developer(payload)
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][1]["role"] == "assistant"


class TestPrepareChatPayload:
    def test_basic_request(self):
        req = _make_request()
        payload = prepare_chat_payload(req)
        assert payload["model"] == "gpt-4o"
        assert len(payload["messages"]) == 1

    def test_o_series_converts_system(self):
        req = CompletionRequest(
            model="o1",
            messages=[
                Message(role="system", content="Be helpful."),
                Message(role="user", content="Hi"),
            ],
        )
        payload = prepare_chat_payload(req)
        assert payload["messages"][0]["role"] == "developer"

    def test_o_series_strips_temperature(self):
        req = CompletionRequest(
            model="o1",
            messages=[Message(role="user", content="Hi")],
            temperature=0.7,
            top_p=0.9,
        )
        payload = prepare_chat_payload(req)
        assert "temperature" not in payload
        assert "top_p" not in payload

    def test_o_series_max_tokens_to_max_completion_tokens(self):
        req = CompletionRequest(
            model="o3",
            messages=[Message(role="user", content="Hi")],
            max_tokens=100,
        )
        payload = prepare_chat_payload(req)
        assert "max_tokens" not in payload
        assert payload["max_completion_tokens"] == 100

    def test_normal_model_keeps_temperature(self):
        req = CompletionRequest(
            model="gpt-4o",
            messages=[Message(role="user", content="Hi")],
            temperature=0.7,
        )
        payload = prepare_chat_payload(req)
        assert payload["temperature"] == 0.7


# ═══════════════════════════════════════════════════════════════════════════
# Provider tests
# ═══════════════════════════════════════════════════════════════════════════


class TestOpenAIProviderInit:
    def test_default_base_url(self):
        p = OpenAIProvider(api_key="sk-test")
        assert "api.openai.com" in p.api_base

    def test_custom_base_url(self):
        p = OpenAIProvider(api_key="sk-test", api_base="https://custom.openai.com/v1")
        assert p.api_base == "https://custom.openai.com/v1"

    def test_organization_header(self):
        p = OpenAIProvider(api_key="sk-test", organization="org-123")
        headers = p._build_headers()
        assert headers["OpenAI-Organization"] == "org-123"

    def test_project_header(self):
        p = OpenAIProvider(api_key="sk-test", project="proj-abc")
        headers = p._build_headers()
        assert headers["OpenAI-Project"] == "proj-abc"

    def test_no_org_header_when_none(self):
        p = OpenAIProvider(api_key="sk-test")
        headers = p._build_headers()
        assert "OpenAI-Organization" not in headers


class TestOpenAIChatCompletion:
    @pytest.mark.asyncio
    async def test_basic_completion(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        provider = OpenAIProvider(api_key="sk-test")
        result = await provider.chat_completion(_make_request())

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hello! How can I help you today?"
        assert result.usage.total_tokens == 21
        assert result.model == "gpt-4o-2024-11-20"
        await provider.close()

    @pytest.mark.asyncio
    async def test_tool_call_response(self, respx_mock):
        fixture = _load_fixture("chat_completion_tool_call.json")
        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        provider = OpenAIProvider(api_key="sk-test")
        result = await provider.chat_completion(_make_request())

        assert result.choices[0].finish_reason == "tool_calls"
        tool_calls = result.choices[0].message.tool_calls
        assert tool_calls is not None
        assert len(tool_calls) == 1
        assert tool_calls[0].function.name == "get_weather"
        args = json.loads(tool_calls[0].function.arguments)
        assert args["location"] == "San Francisco"
        await provider.close()

    @pytest.mark.asyncio
    async def test_stream(self, respx_mock):
        chunk1 = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-4o",
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}],
        }
        chunk2 = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-4o",
            "choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}],
        }
        chunk3 = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-4o",
            "choices": [{"index": 0, "delta": {"content": " there!"}, "finish_reason": None}],
        }
        chunk4 = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "gpt-4o",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }

        sse = _sse_lines(chunk1, chunk2, chunk3, chunk4, "[DONE]")
        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=sse.encode(),
                headers={"Content-Type": "text/event-stream"},
            )
        )

        provider = OpenAIProvider(api_key="sk-test")
        chunks: list[CompletionResponseChunk] = []
        async for chunk in provider.chat_completion_stream(_make_request()):
            chunks.append(chunk)

        assert len(chunks) == 4
        assert chunks[1].choices[0].delta.content == "Hello"
        assert chunks[2].choices[0].delta.content == " there!"
        assert chunks[3].choices[0].finish_reason == "stop"
        await provider.close()


class TestOpenAIEmbedding:
    @pytest.mark.asyncio
    async def test_embedding(self, respx_mock):
        fixture = _load_fixture("embedding.json")
        respx_mock.post("https://api.openai.com/v1/embeddings").mock(return_value=httpx.Response(200, json=fixture))

        provider = OpenAIProvider(api_key="sk-test")
        req = EmbeddingRequest(model="text-embedding-3-small", input="Hello world")
        result = await provider.embedding(req)

        assert isinstance(result, EmbeddingResponse)
        assert len(result.data) == 1
        assert len(result.data[0].embedding) == 8
        assert result.usage.prompt_tokens == 5
        await provider.close()


class TestOpenAIImageGeneration:
    @pytest.mark.asyncio
    async def test_image_generation(self, respx_mock):
        fixture = _load_fixture("image_generation.json")
        respx_mock.post("https://api.openai.com/v1/images/generations").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        provider = OpenAIProvider(api_key="sk-test")
        req = ImageRequest(model="dall-e-3", prompt="A cute baby sea otter")
        result = await provider.image_generation(req)

        assert isinstance(result, ImageResponse)
        assert len(result.data) == 1
        assert "otter" in (result.data[0].revised_prompt or "")
        await provider.close()


class TestOpenAIAudioTranscription:
    @pytest.mark.asyncio
    async def test_transcription(self, respx_mock):
        fixture = _load_fixture("audio_transcription.json")
        respx_mock.post("https://api.openai.com/v1/audio/transcriptions").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        provider = OpenAIProvider(api_key="sk-test")
        req = AudioTranscriptionRequest(model="whisper-1")
        result = await provider.audio_transcription(req, file=b"fake-audio-bytes")

        assert isinstance(result, AudioTranscriptionResponse)
        assert "test transcription" in result.text
        await provider.close()


class TestOpenAIAudioSpeech:
    @pytest.mark.asyncio
    async def test_speech(self, respx_mock):
        audio_bytes = b"\x00\x01\x02\x03" * 100
        respx_mock.post("https://api.openai.com/v1/audio/speech").mock(
            return_value=httpx.Response(200, content=audio_bytes)
        )

        from routerbot.core.types import AudioSpeechRequest

        provider = OpenAIProvider(api_key="sk-test")
        req = AudioSpeechRequest(model="tts-1", input="Hello world", voice="alloy")
        result = await provider.audio_speech(req)

        assert isinstance(result, bytes)
        assert len(result) == 400
        await provider.close()


class TestOpenAIErrors:
    @pytest.mark.asyncio
    async def test_auth_error(self, respx_mock):
        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(401, json={"error": {"message": "Incorrect API key provided"}})
        )
        provider = OpenAIProvider(api_key="bad-key")
        with pytest.raises(AuthenticationError, match="Incorrect API key"):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_rate_limit(self, respx_mock):
        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}})
        )
        provider = OpenAIProvider(api_key="sk-test")
        with pytest.raises(RateLimitError):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_server_error(self, respx_mock):
        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(500, json={"error": {"message": "Server error"}})
        )
        provider = OpenAIProvider(api_key="sk-test")
        with pytest.raises(ServiceUnavailableError):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_timeout(self, respx_mock):
        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(side_effect=httpx.ReadTimeout("timed out"))
        provider = OpenAIProvider(api_key="sk-test")
        with pytest.raises(ProviderError, match="timed out"):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_generic_provider_error(self, respx_mock):
        respx_mock.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(400, json={"error": {"message": "Invalid request"}})
        )
        provider = OpenAIProvider(api_key="sk-test")
        with pytest.raises(ProviderError):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_tts_http_error(self, respx_mock):
        respx_mock.post("https://api.openai.com/v1/audio/speech").mock(
            side_effect=httpx.ConnectError("connection failed")
        )
        from routerbot.core.types import AudioSpeechRequest

        provider = OpenAIProvider(api_key="sk-test")
        req = AudioSpeechRequest(model="tts-1", input="Hello", voice="alloy")
        with pytest.raises(ProviderError, match="TTS error"):
            await provider.audio_speech(req)
        await provider.close()


class TestOpenAIHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy(self, respx_mock):
        respx_mock.get("https://api.openai.com/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
        provider = OpenAIProvider(api_key="sk-test")
        assert await provider.health_check() is True
        await provider.close()

    @pytest.mark.asyncio
    async def test_unhealthy(self, respx_mock):
        respx_mock.get("https://api.openai.com/v1/models").mock(side_effect=httpx.ConnectError("connection refused"))
        provider = OpenAIProvider(api_key="sk-test")
        assert await provider.health_check() is False
        await provider.close()
