"""Tests for the Anthropic provider."""

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
    CompletionResponseChunk,
    Message,
)
from routerbot.providers.anthropic.config import (
    ANTHROPIC_API_BASE,
    ANTHROPIC_VERSION,
    CHAT_MODELS,
    DEFAULT_MAX_TOKENS,
    FINISH_REASON_MAP,
)
from routerbot.providers.anthropic.provider import AnthropicProvider
from routerbot.providers.anthropic.transform import (
    anthropic_response_to_openai,
    anthropic_stream_event_to_delta,
    build_anthropic_request,
    openai_messages_to_anthropic,
    openai_tools_to_anthropic,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "anthropic"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _make_request(
    model: str = "claude-3-5-sonnet-20241022",
    content: str = "Hello",
    **kwargs: Any,
) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[Message(role="user", content=content)],
        **kwargs,
    )


def _sse_events(*events: tuple[str, dict[str, Any]]) -> str:
    """Build Anthropic SSE-formatted string from (event_type, data) pairs."""
    lines = []
    for event_type, data in events:
        lines.append(f"event: {event_type}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Config tests
# ═══════════════════════════════════════════════════════════════════════════


class TestConfig:
    def test_chat_models_not_empty(self):
        assert len(CHAT_MODELS) > 0

    def test_claude_sonnet_in_models(self):
        assert "claude-sonnet-3-5-20241022" in CHAT_MODELS

    def test_claude_haiku_in_models(self):
        assert "claude-haiku-3-5-20241022" in CHAT_MODELS

    def test_api_base(self):
        assert ANTHROPIC_API_BASE == "https://api.anthropic.com"

    def test_api_version(self):
        assert ANTHROPIC_VERSION == "2023-06-01"

    def test_default_max_tokens(self):
        assert DEFAULT_MAX_TOKENS > 0

    def test_finish_reason_map_end_turn(self):
        assert FINISH_REASON_MAP["end_turn"] == "stop"

    def test_finish_reason_map_max_tokens(self):
        assert FINISH_REASON_MAP["max_tokens"] == "length"

    def test_finish_reason_map_tool_use(self):
        assert FINISH_REASON_MAP["tool_use"] == "tool_calls"

    def test_finish_reason_map_stop_sequence(self):
        assert FINISH_REASON_MAP["stop_sequence"] == "stop"


# ═══════════════════════════════════════════════════════════════════════════
# Transform: openai_messages_to_anthropic
# ═══════════════════════════════════════════════════════════════════════════


class TestOpenAIMessagesToAnthropic:
    def test_simple_user_message(self):
        messages = [{"role": "user", "content": "Hello"}]
        system, anthropic_msgs = openai_messages_to_anthropic(messages)
        assert system is None
        assert len(anthropic_msgs) == 1
        assert anthropic_msgs[0]["role"] == "user"
        assert anthropic_msgs[0]["content"] == "Hello"

    def test_system_message_extracted(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        system, anthropic_msgs = openai_messages_to_anthropic(messages)
        assert system == "You are helpful."
        assert len(anthropic_msgs) == 1
        assert anthropic_msgs[0]["role"] == "user"

    def test_multiple_system_messages_joined(self):
        messages = [
            {"role": "system", "content": "Part 1."},
            {"role": "system", "content": "Part 2."},
            {"role": "user", "content": "Hi"},
        ]
        system, _ = openai_messages_to_anthropic(messages)
        assert system == "Part 1.\nPart 2."

    def test_developer_role_treated_as_system(self):
        messages = [
            {"role": "developer", "content": "Dev instructions."},
            {"role": "user", "content": "Hi"},
        ]
        system, anthropic_msgs = openai_messages_to_anthropic(messages)
        assert system == "Dev instructions."
        assert len(anthropic_msgs) == 1

    def test_assistant_message_converted(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        _, anthropic_msgs = openai_messages_to_anthropic(messages)
        assert anthropic_msgs[1]["role"] == "assistant"
        assert anthropic_msgs[1]["content"] == "Hello!"

    def test_tool_result_message(self):
        messages = [
            {"role": "tool", "tool_call_id": "call_abc123", "content": "72°F"},
        ]
        _, anthropic_msgs = openai_messages_to_anthropic(messages)
        assert anthropic_msgs[0]["role"] == "user"
        content = anthropic_msgs[0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "tool_result"
        assert content[0]["tool_use_id"] == "call_abc123"
        assert content[0]["content"] == "72°F"

    def test_assistant_with_tool_calls(self):
        messages = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_xyz",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location":"SF"}',
                        },
                    }
                ],
            }
        ]
        _, anthropic_msgs = openai_messages_to_anthropic(messages)
        assert anthropic_msgs[0]["role"] == "assistant"
        blocks = anthropic_msgs[0]["content"]
        assert isinstance(blocks, list)
        tool_block = blocks[0]
        assert tool_block["type"] == "tool_use"
        assert tool_block["id"] == "call_xyz"
        assert tool_block["name"] == "get_weather"
        assert tool_block["input"] == {"location": "SF"}

    def test_image_url_content_block(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/img.jpg"}},
                ],
            }
        ]
        _, anthropic_msgs = openai_messages_to_anthropic(messages)
        blocks = anthropic_msgs[0]["content"]
        assert blocks[0]["type"] == "text"
        assert blocks[1]["type"] == "image"
        assert blocks[1]["source"]["type"] == "url"

    def test_base64_image_content_block(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc123"},
                    }
                ],
            }
        ]
        _, anthropic_msgs = openai_messages_to_anthropic(messages)
        block = anthropic_msgs[0]["content"][0]
        assert block["type"] == "image"
        assert block["source"]["type"] == "base64"
        assert block["source"]["media_type"] == "image/png"
        assert block["source"]["data"] == "abc123"

    def test_no_system_returns_none(self):
        messages = [{"role": "user", "content": "Hello"}]
        system, _ = openai_messages_to_anthropic(messages)
        assert system is None


# ═══════════════════════════════════════════════════════════════════════════
# Transform: openai_tools_to_anthropic
# ═══════════════════════════════════════════════════════════════════════════


class TestOpenAIToolsToAnthropic:
    def test_none_returns_none(self):
        assert openai_tools_to_anthropic(None) is None

    def test_empty_returns_none(self):
        assert openai_tools_to_anthropic([]) is None

    def test_converts_function_tool(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                    },
                },
            }
        ]
        result = openai_tools_to_anthropic(tools)
        assert result is not None
        assert len(result) == 1
        t = result[0]
        assert t["name"] == "get_weather"
        assert t["description"] == "Get weather"
        assert "input_schema" in t
        assert t["input_schema"]["type"] == "object"

    def test_missing_parameters_defaults_to_empty_schema(self):
        tools = [{"type": "function", "function": {"name": "noop"}}]
        result = openai_tools_to_anthropic(tools)
        assert result is not None
        assert result[0]["input_schema"] == {"type": "object", "properties": {}}


# ═══════════════════════════════════════════════════════════════════════════
# Transform: anthropic_response_to_openai
# ═══════════════════════════════════════════════════════════════════════════


class TestAnthropicResponseToOpenAI:
    def test_simple_text_response(self):
        data = _load_fixture("chat_completion.json")
        result = anthropic_response_to_openai(data, "claude-3-5-sonnet-20241022")

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hello! How can I help you today?"
        assert result.choices[0].finish_reason == "stop"
        assert result.usage.prompt_tokens == 12
        assert result.usage.completion_tokens == 9
        assert result.usage.total_tokens == 21

    def test_tool_use_response(self):
        data = _load_fixture("chat_completion_tool_use.json")
        result = anthropic_response_to_openai(data, "claude-3-5-sonnet-20241022")

        assert result.choices[0].finish_reason == "tool_calls"
        tool_calls = result.choices[0].message.tool_calls
        assert tool_calls is not None
        assert len(tool_calls) == 1
        assert tool_calls[0].function.name == "get_weather"
        args = json.loads(tool_calls[0].function.arguments)
        assert args["location"] == "San Francisco, CA"

    def test_text_preserved_with_tool_use(self):
        data = _load_fixture("chat_completion_tool_use.json")
        result = anthropic_response_to_openai(data, "claude-3-5-sonnet-20241022")
        # Should include text AND tool calls
        assert result.choices[0].message.content == "I'll look up the weather for you."

    def test_response_id_preserved(self):
        data = _load_fixture("chat_completion.json")
        result = anthropic_response_to_openai(data, "claude-3-5-sonnet-20241022")
        assert result.id == "msg_01XFDUDYJgAACzvnptvVoYEL"

    def test_model_preserved(self):
        data = _load_fixture("chat_completion.json")
        result = anthropic_response_to_openai(data, "claude-3-5-sonnet-20241022")
        assert "claude" in result.model


# ═══════════════════════════════════════════════════════════════════════════
# Transform: build_anthropic_request
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildAnthropicRequest:
    def test_basic_payload(self):
        messages = [{"role": "user", "content": "Hi"}]
        payload = build_anthropic_request("claude-3-5-sonnet-20241022", messages, None, max_tokens=1024)
        assert payload["model"] == "claude-3-5-sonnet-20241022"
        assert payload["messages"] == messages
        assert payload["max_tokens"] == 1024
        assert payload["stream"] is False

    def test_system_included_when_present(self):
        messages = [{"role": "user", "content": "Hi"}]
        payload = build_anthropic_request("claude-3-5-sonnet-20241022", messages, "Be helpful", max_tokens=1024)
        assert payload["system"] == "Be helpful"

    def test_system_not_included_when_none(self):
        messages = [{"role": "user", "content": "Hi"}]
        payload = build_anthropic_request("claude-3-5-sonnet-20241022", messages, None, max_tokens=1024)
        assert "system" not in payload

    def test_stop_sequences_string(self):
        messages = [{"role": "user", "content": "Hi"}]
        payload = build_anthropic_request(
            "claude-3-5-sonnet-20241022",
            messages,
            None,
            max_tokens=1024,
            stop="STOP",
        )
        assert payload["stop_sequences"] == ["STOP"]

    def test_stop_sequences_list(self):
        messages = [{"role": "user", "content": "Hi"}]
        payload = build_anthropic_request(
            "claude-3-5-sonnet-20241022",
            messages,
            None,
            max_tokens=1024,
            stop=["STOP", "END"],
        )
        assert payload["stop_sequences"] == ["STOP", "END"]

    def test_stream_flag(self):
        messages = [{"role": "user", "content": "Hi"}]
        payload = build_anthropic_request("claude-3-5-sonnet-20241022", messages, None, max_tokens=1024, stream=True)
        assert payload["stream"] is True

    def test_temperature_included(self):
        messages = [{"role": "user", "content": "Hi"}]
        payload = build_anthropic_request(
            "claude-3-5-sonnet-20241022",
            messages,
            None,
            max_tokens=1024,
            temperature=0.7,
        )
        assert payload["temperature"] == 0.7

    def test_extra_fields_merged(self):
        messages = [{"role": "user", "content": "Hi"}]
        payload = build_anthropic_request(
            "claude-3-5-sonnet-20241022",
            messages,
            None,
            max_tokens=1024,
            extra={"metadata": {"user_id": "u123"}},
        )
        assert payload["metadata"] == {"user_id": "u123"}


# ═══════════════════════════════════════════════════════════════════════════
# Transform: anthropic_stream_event_to_delta
# ═══════════════════════════════════════════════════════════════════════════


class TestAnthropicStreamEventToDelta:
    def test_message_start_updates_state(self):
        state: dict[str, Any] = {}
        result = anthropic_stream_event_to_delta(
            "message_start",
            {
                "message": {
                    "id": "msg_abc",
                    "model": "claude-3-5-sonnet-20241022",
                    "usage": {"input_tokens": 10},
                }
            },
            state,
        )
        assert result is None
        assert state["id"] == "msg_abc"
        assert state["model"] == "claude-3-5-sonnet-20241022"
        assert state["prompt_tokens"] == 10

    def test_text_delta_returns_content(self):
        state: dict[str, Any] = {}
        result = anthropic_stream_event_to_delta(
            "content_block_delta",
            {"index": 0, "delta": {"type": "text_delta", "text": "Hello"}},
            state,
        )
        assert result is not None
        assert result["content"] == "Hello"

    def test_input_json_delta_accumulates(self):
        state: dict[str, Any] = {"tool_calls": {0: {"id": "toolu_abc", "name": "get_weather", "arguments": ""}}}
        result = anthropic_stream_event_to_delta(
            "content_block_delta",
            {"index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"loc'}},
            state,
        )
        assert result is not None
        tc = result["tool_calls"][0]
        assert tc["function"]["name"] == "get_weather"
        assert state["tool_calls"][0]["arguments"] == '{"loc'

    def test_message_delta_sets_finish_reason(self):
        state: dict[str, Any] = {}
        result = anthropic_stream_event_to_delta(
            "message_delta",
            {
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 15},
            },
            state,
        )
        assert result is None
        assert state["finish_reason"] == "stop"
        assert state["completion_tokens"] == 15

    def test_message_stop_sets_done(self):
        state: dict[str, Any] = {}
        result = anthropic_stream_event_to_delta("message_stop", {}, state)
        assert result is None
        assert state.get("done") is True

    def test_content_block_start_tool_use(self):
        state: dict[str, Any] = {}
        result = anthropic_stream_event_to_delta(
            "content_block_start",
            {
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_xyz",
                    "name": "search",
                },
            },
            state,
        )
        assert result is None
        tc = state["tool_calls"][0]
        assert tc["id"] == "toolu_xyz"
        assert tc["name"] == "search"

    def test_unknown_event_returns_none(self):
        state: dict[str, Any] = {}
        result = anthropic_stream_event_to_delta("ping", {}, state)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# Provider: instantiation
# ═══════════════════════════════════════════════════════════════════════════


class TestAnthropicProviderInit:
    def test_default_api_base(self):
        p = AnthropicProvider(api_key="sk-ant-test")
        assert p.api_base == ANTHROPIC_API_BASE
        assert p.api_key == "sk-ant-test"

    def test_custom_api_base(self):
        p = AnthropicProvider(api_key="sk-ant-test", api_base="https://custom.anthropic.com")
        assert p.api_base == "https://custom.anthropic.com"

    def test_headers_contain_api_key(self):
        p = AnthropicProvider(api_key="sk-ant-test")
        assert p._headers["x-api-key"] == "sk-ant-test"

    def test_headers_contain_version(self):
        p = AnthropicProvider(api_key="sk-ant-test")
        assert p._headers["anthropic-version"] == ANTHROPIC_VERSION

    def test_headers_content_type(self):
        p = AnthropicProvider(api_key="sk-ant-test")
        assert p._headers["content-type"] == "application/json"


# ═══════════════════════════════════════════════════════════════════════════
# Provider: chat_completion
# ═══════════════════════════════════════════════════════════════════════════


class TestAnthropicChatCompletion:
    @pytest.mark.asyncio
    async def test_basic_completion(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        respx_mock.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(200, json=fixture))

        provider = AnthropicProvider(api_key="sk-ant-test")
        result = await provider.chat_completion(_make_request())

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hello! How can I help you today?"
        assert result.usage.total_tokens == 21
        await provider.close()

    @pytest.mark.asyncio
    async def test_tool_use_response(self, respx_mock):
        fixture = _load_fixture("chat_completion_tool_use.json")
        respx_mock.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(200, json=fixture))

        provider = AnthropicProvider(api_key="sk-ant-test")
        result = await provider.chat_completion(_make_request())

        assert result.choices[0].finish_reason == "tool_calls"
        tool_calls = result.choices[0].message.tool_calls
        assert tool_calls is not None
        assert tool_calls[0].function.name == "get_weather"
        await provider.close()

    @pytest.mark.asyncio
    async def test_auth_error(self, respx_mock):
        respx_mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                401,
                json={"type": "error", "error": {"type": "authentication_error", "message": "Invalid API key"}},
            )
        )

        provider = AnthropicProvider(api_key="bad-key")
        with pytest.raises(AuthenticationError):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, respx_mock):
        respx_mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                429,
                json={"type": "error", "error": {"type": "rate_limit_error", "message": "Rate limited"}},
            )
        )

        provider = AnthropicProvider(api_key="sk-ant-test")
        with pytest.raises(RateLimitError):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_server_error(self, respx_mock):
        respx_mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                500,
                json={"type": "error", "error": {"type": "api_error", "message": "Internal error"}},
            )
        )

        provider = AnthropicProvider(api_key="sk-ant-test")
        with pytest.raises(ServiceUnavailableError):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_generic_provider_error(self, respx_mock):
        respx_mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                400,
                json={"type": "error", "error": {"type": "invalid_request_error", "message": "Bad request"}},
            )
        )

        provider = AnthropicProvider(api_key="sk-ant-test")
        with pytest.raises(ProviderError):
            await provider.chat_completion(_make_request())
        await provider.close()

    @pytest.mark.asyncio
    async def test_with_system_message(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        captured_body: list[bytes] = []

        def capture_request(request: httpx.Request) -> httpx.Response:
            captured_body.append(request.content)
            return httpx.Response(200, json=fixture)

        respx_mock.post("https://api.anthropic.com/v1/messages").mock(side_effect=capture_request)

        provider = AnthropicProvider(api_key="sk-ant-test")
        request = CompletionRequest(
            model="claude-3-5-sonnet-20241022",
            messages=[
                Message(role="system", content="Be concise."),
                Message(role="user", content="Hello"),
            ],
        )
        await provider.chat_completion(request)

        body = json.loads(captured_body[0])
        assert body.get("system") == "Be concise."
        # system message should NOT appear in messages array
        for msg in body["messages"]:
            assert msg.get("role") != "system"
        await provider.close()

    @pytest.mark.asyncio
    async def test_max_tokens_defaults(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        captured_body: list[bytes] = []

        def capture_request(request: httpx.Request) -> httpx.Response:
            captured_body.append(request.content)
            return httpx.Response(200, json=fixture)

        respx_mock.post("https://api.anthropic.com/v1/messages").mock(side_effect=capture_request)

        provider = AnthropicProvider(api_key="sk-ant-test")
        await provider.chat_completion(_make_request())

        body = json.loads(captured_body[0])
        assert "max_tokens" in body
        assert body["max_tokens"] > 0
        await provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Provider: streaming
# ═══════════════════════════════════════════════════════════════════════════


class TestAnthropicChatCompletionStream:
    @pytest.mark.asyncio
    async def test_basic_stream(self, respx_mock):
        sse = _sse_events(
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_stream1",
                        "model": "claude-3-5-sonnet-20241022",
                        "usage": {"input_tokens": 10},
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello"},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": " there!"},
                },
            ),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 5},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        )

        respx_mock.post("https://api.anthropic.com/v1/messages").mock(
            return_value=httpx.Response(
                200,
                content=sse.encode(),
                headers={"Content-Type": "text/event-stream"},
            )
        )

        provider = AnthropicProvider(api_key="sk-ant-test")
        chunks: list[CompletionResponseChunk] = []
        async for chunk in provider.chat_completion_stream(_make_request()):
            chunks.append(chunk)

        assert len(chunks) >= 2
        contents = [c.choices[0].delta.content for c in chunks if c.choices[0].delta.content]
        assert "Hello" in contents
        assert " there!" in contents
        await provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Provider: unsupported operations
# ═══════════════════════════════════════════════════════════════════════════


class TestAnthropicUnsupportedOps:
    @pytest.mark.asyncio
    async def test_embedding_raises(self):
        from routerbot.core.types import EmbeddingRequest

        provider = AnthropicProvider(api_key="sk-ant-test")
        with pytest.raises(ProviderError, match="embeddings"):
            await provider.embedding(EmbeddingRequest(model="any", input="text"))

    @pytest.mark.asyncio
    async def test_image_generation_raises(self):
        from routerbot.core.types import ImageRequest

        provider = AnthropicProvider(api_key="sk-ant-test")
        req = ImageRequest(model="any", prompt="A cat")
        with pytest.raises(ProviderError, match="image generation"):
            await provider.image_generation(req)

    @pytest.mark.asyncio
    async def test_tts_raises(self):
        from routerbot.core.types import AudioSpeechRequest

        provider = AnthropicProvider(api_key="sk-ant-test")
        req = AudioSpeechRequest(model="any", input="Hello", voice="alloy")
        with pytest.raises(ProviderError, match="text-to-speech"):
            await provider.text_to_speech(req)

    @pytest.mark.asyncio
    async def test_transcription_raises(self):
        from routerbot.core.types import AudioTranscriptionRequest

        provider = AnthropicProvider(api_key="sk-ant-test")
        req = AudioTranscriptionRequest(model="any")
        with pytest.raises(ProviderError, match="transcription"):
            await provider.audio_transcription(req)
