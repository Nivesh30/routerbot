"""Tests for the AWS Bedrock provider."""

from __future__ import annotations

import json
import struct
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
    Message,
)
from routerbot.providers.bedrock.config import (
    ANTHROPIC_MODELS,
    BEDROCK_SERVICE,
    DEFAULT_REGION,
    FINISH_REASON_MAP,
    build_bedrock_base_url,
)
from routerbot.providers.bedrock.provider import BedrockProvider
from routerbot.providers.bedrock.sigv4 import (
    _canonical_querystring,
    _canonical_uri,
    sign_request,
)
from routerbot.providers.bedrock.transform import (
    build_converse_request,
    converse_response_to_openai,
    decode_event_stream,
    openai_to_converse_messages,
    openai_tools_to_converse,
    parse_converse_stream_event,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "bedrock"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _make_provider(**kwargs: Any) -> BedrockProvider:
    return BedrockProvider(
        access_key_id=kwargs.pop("access_key_id", "AKIATEST123456789"),
        secret_access_key=kwargs.pop("secret_access_key", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYtest"),
        **kwargs,
    )


def _make_request(
    model: str = "anthropic.claude-3-5-sonnet-20241022-v2:0",
    content: str = "Hello",
    **kwargs: Any,
) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[Message(role="user", content=content)],
        **kwargs,
    )


def _build_event_stream_message(payload_bytes: bytes) -> bytes:
    """Build a minimal AWS EventStream binary message."""
    headers_bytes = b""
    headers_len = len(headers_bytes)
    payload_len = len(payload_bytes)
    total_len = 12 + headers_len + payload_len + 4  # prelude + headers + payload + crc

    import zlib

    prelude = struct.pack(">II", total_len, headers_len)
    prelude_crc = struct.pack(">I", zlib.crc32(prelude) & 0xFFFFFFFF)

    message_without_crc = prelude + prelude_crc + headers_bytes + payload_bytes
    message_crc = struct.pack(">I", zlib.crc32(message_without_crc) & 0xFFFFFFFF)

    return message_without_crc + message_crc


# ═══════════════════════════════════════════════════════════════════════════
# Config tests
# ═══════════════════════════════════════════════════════════════════════════


class TestConfig:
    def test_default_region(self):
        assert DEFAULT_REGION == "us-east-1"

    def test_bedrock_service(self):
        assert BEDROCK_SERVICE == "bedrock-runtime"

    def test_build_base_url(self):
        url = build_bedrock_base_url("us-east-1")
        assert url == "https://bedrock-runtime.us-east-1.amazonaws.com"

    def test_build_base_url_different_region(self):
        url = build_bedrock_base_url("eu-west-1")
        assert "eu-west-1" in url

    def test_anthropic_models_not_empty(self):
        assert len(ANTHROPIC_MODELS) > 0

    def test_claude_model_in_anthropic(self):
        assert "anthropic.claude-3-5-sonnet-20241022-v2:0" in ANTHROPIC_MODELS

    def test_finish_reason_map_end_turn(self):
        assert FINISH_REASON_MAP["end_turn"] == "stop"

    def test_finish_reason_map_tool_use(self):
        assert FINISH_REASON_MAP["tool_use"] == "tool_calls"

    def test_finish_reason_map_max_tokens(self):
        assert FINISH_REASON_MAP["max_tokens"] == "length"


# ═══════════════════════════════════════════════════════════════════════════
# SigV4 tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSigV4:
    def test_canonical_uri_root(self):
        assert _canonical_uri("/") == "/"

    def test_canonical_uri_empty(self):
        assert _canonical_uri("") == "/"

    def test_canonical_uri_path(self):
        result = _canonical_uri("/model/my-model/converse")
        assert "/model/" in result

    def test_canonical_uri_encodes_spaces(self):
        result = _canonical_uri("/path/with spaces")
        assert " " not in result
        assert "%20" in result

    def test_canonical_querystring_empty(self):
        assert _canonical_querystring("") == ""

    def test_canonical_querystring_single(self):
        result = _canonical_querystring("foo=bar")
        assert "foo=bar" in result

    def test_canonical_querystring_sorted(self):
        result = _canonical_querystring("z=1&a=2")
        assert result.index("a=2") < result.index("z=1")

    def test_sign_request_returns_auth_header(self):
        result = sign_request(
            method="POST",
            url="https://bedrock-runtime.us-east-1.amazonaws.com/model/test/converse",
            payload=b'{"messages": []}',
            region="us-east-1",
            service="bedrock-runtime",
            access_key="AKIATEST123456789",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYtest",
        )
        assert "Authorization" in result
        assert result["Authorization"].startswith("AWS4-HMAC-SHA256")

    def test_sign_request_contains_x_amz_date(self):
        result = sign_request(
            method="POST",
            url="https://bedrock-runtime.us-east-1.amazonaws.com/model/test/converse",
            payload=b"",
            region="us-east-1",
            service="bedrock-runtime",
            access_key="AKIATEST",
            secret_key="secret",
        )
        assert "x-amz-date" in result
        assert len(result["x-amz-date"]) == 16  # YYYYMMDDTHHMMSSz

    def test_sign_request_with_session_token(self):
        result = sign_request(
            method="POST",
            url="https://bedrock-runtime.us-east-1.amazonaws.com/model/test/converse",
            payload=b"",
            region="us-east-1",
            service="bedrock-runtime",
            access_key="AKIATEST",
            secret_key="secret",
            session_token="test-session-token",
        )
        assert "x-amz-security-token" in result
        assert result["x-amz-security-token"] == "test-session-token"

    def test_sign_request_custom_timestamp(self):
        result = sign_request(
            method="POST",
            url="https://bedrock-runtime.us-east-1.amazonaws.com/model/test/converse",
            payload=b"",
            region="us-east-1",
            service="bedrock-runtime",
            access_key="AKIATEST",
            secret_key="secret",
            amz_date="20240101T120000Z",
        )
        assert result["x-amz-date"] == "20240101T120000Z"
        # Credential scope should include the date
        assert "20240101" in result["Authorization"]

    def test_sign_request_deterministic(self):
        """Same inputs must always produce the same signature."""
        kwargs = {
            "method": "POST",
            "url": "https://bedrock-runtime.us-east-1.amazonaws.com/model/test/converse",
            "payload": b"test",
            "region": "us-east-1",
            "service": "bedrock-runtime",
            "access_key": "AKIATEST",
            "secret_key": "secret",
            "amz_date": "20240101T120000Z",
        }
        r1 = sign_request(**kwargs)
        r2 = sign_request(**kwargs)
        assert r1["Authorization"] == r2["Authorization"]


# ═══════════════════════════════════════════════════════════════════════════
# Transform: openai_to_converse_messages
# ═══════════════════════════════════════════════════════════════════════════


class TestOpenAIToConverseMessages:
    def test_simple_user_message(self):
        msgs = [{"role": "user", "content": "Hello"}]
        system, converse = openai_to_converse_messages(msgs)
        assert system is None
        assert converse[0]["role"] == "user"
        assert converse[0]["content"][0]["text"] == "Hello"

    def test_system_extracted(self):
        msgs = [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hi"},
        ]
        system, converse = openai_to_converse_messages(msgs)
        assert system is not None
        assert system[0]["text"] == "Be helpful."
        assert len(converse) == 1

    def test_assistant_message(self):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        _, converse = openai_to_converse_messages(msgs)
        assert converse[1]["role"] == "assistant"
        assert converse[1]["content"][0]["text"] == "Hello!"

    def test_tool_result_message(self):
        msgs = [{"role": "tool", "tool_call_id": "tu_abc", "content": "72°F"}]
        _, converse = openai_to_converse_messages(msgs)
        assert converse[0]["role"] == "user"
        tool_result = converse[0]["content"][0]["toolResult"]
        assert tool_result["toolUseId"] == "tu_abc"
        assert "72°F" in tool_result["content"][0]["text"]

    def test_tool_calls_in_assistant(self):
        msgs = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "tc_abc",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"q":"cats"}'},
                    }
                ],
            }
        ]
        _, converse = openai_to_converse_messages(msgs)
        block = converse[0]["content"][0]
        assert "toolUse" in block
        assert block["toolUse"]["toolUseId"] == "tc_abc"
        assert block["toolUse"]["name"] == "search"
        assert block["toolUse"]["input"] == {"q": "cats"}

    def test_developer_role_treated_as_system(self):
        msgs = [
            {"role": "developer", "content": "Dev prompt."},
            {"role": "user", "content": "Hi"},
        ]
        system, _ = openai_to_converse_messages(msgs)
        assert system is not None
        assert system[0]["text"] == "Dev prompt."

    def test_multiple_system_messages(self):
        msgs = [
            {"role": "system", "content": "Part 1."},
            {"role": "system", "content": "Part 2."},
            {"role": "user", "content": "Hi"},
        ]
        system, _ = openai_to_converse_messages(msgs)
        assert system is not None
        assert len(system) == 2


# ═══════════════════════════════════════════════════════════════════════════
# Transform: openai_tools_to_converse
# ═══════════════════════════════════════════════════════════════════════════


class TestOpenAIToolsToConverse:
    def test_none_returns_none(self):
        assert openai_tools_to_converse(None) is None

    def test_empty_returns_none(self):
        assert openai_tools_to_converse([]) is None

    def test_converts_tool(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather info",
                    "parameters": {"type": "object", "properties": {"loc": {"type": "string"}}},
                },
            }
        ]
        result = openai_tools_to_converse(tools)
        assert result is not None
        assert "tools" in result
        spec = result["tools"][0]["toolSpec"]
        assert spec["name"] == "get_weather"
        assert "inputSchema" in spec
        assert "json" in spec["inputSchema"]


# ═══════════════════════════════════════════════════════════════════════════
# Transform: converse_response_to_openai
# ═══════════════════════════════════════════════════════════════════════════


class TestConverseResponseToOpenAI:
    def test_simple_chat_response(self):
        data = _load_fixture("chat_completion.json")
        result = converse_response_to_openai(data, "anthropic.claude-3-5-sonnet-20241022-v2:0")

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hello! How can I help you today?"
        assert result.choices[0].finish_reason == "stop"
        assert result.usage.prompt_tokens == 12
        assert result.usage.completion_tokens == 9
        assert result.usage.total_tokens == 21

    def test_tool_use_response(self):
        data = _load_fixture("chat_completion_tool_use.json")
        result = converse_response_to_openai(data, "anthropic.claude-3-5-sonnet-20241022-v2:0")

        assert result.choices[0].finish_reason == "tool_calls"
        tool_calls = result.choices[0].message.tool_calls
        assert tool_calls is not None
        assert tool_calls[0].function.name == "get_weather"
        args = json.loads(tool_calls[0].function.arguments)
        assert args["location"] == "San Francisco, CA"

    def test_text_preserved_with_tool(self):
        data = _load_fixture("chat_completion_tool_use.json")
        result = converse_response_to_openai(data, "model")
        assert result.choices[0].message.content == "I'll look up the weather for you."


# ═══════════════════════════════════════════════════════════════════════════
# Transform: build_converse_request
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildConverseRequest:
    def test_basic_payload(self):
        msgs = [{"role": "user", "content": [{"text": "hello"}]}]
        payload = build_converse_request("model", msgs, None, max_tokens=1024)
        assert payload["messages"] == msgs
        assert payload["inferenceConfig"]["maxTokens"] == 1024

    def test_system_included(self):
        msgs = [{"role": "user", "content": [{"text": "hi"}]}]
        system = [{"text": "Be helpful"}]
        payload = build_converse_request("model", msgs, system, max_tokens=512)
        assert payload["system"] == system

    def test_temperature_in_inference_config(self):
        msgs = [{"role": "user", "content": [{"text": "hi"}]}]
        payload = build_converse_request("model", msgs, None, max_tokens=512, temperature=0.7)
        assert payload["inferenceConfig"]["temperature"] == 0.7

    def test_stop_sequences(self):
        msgs = [{"role": "user", "content": [{"text": "hi"}]}]
        payload = build_converse_request("model", msgs, None, max_tokens=512, stop=["STOP"])
        assert payload["inferenceConfig"]["stopSequences"] == ["STOP"]

    def test_tool_config_included(self):
        msgs = [{"role": "user", "content": [{"text": "hi"}]}]
        tool_config = {"tools": [{"toolSpec": {"name": "test", "description": ""}}]}
        payload = build_converse_request("model", msgs, None, max_tokens=512, tool_config=tool_config)
        assert payload["toolConfig"] == tool_config


# ═══════════════════════════════════════════════════════════════════════════
# Transform: parse_converse_stream_event
# ═══════════════════════════════════════════════════════════════════════════


class TestParseConverseStreamEvent:
    def test_message_start(self):
        state: dict[str, Any] = {}
        result = parse_converse_stream_event({"messageStart": {"role": "assistant"}}, state)
        assert result is None
        assert state["role"] == "assistant"

    def test_text_delta(self):
        state: dict[str, Any] = {}
        result = parse_converse_stream_event(
            {"contentBlockDelta": {"delta": {"text": "Hello"}}, "contentBlockIndex": 0},
            state,
        )
        assert result is not None
        assert result["content"] == "Hello"

    def test_tool_use_start(self):
        state: dict[str, Any] = {}
        result = parse_converse_stream_event(
            {
                "contentBlockStart": {"start": {"toolUse": {"toolUseId": "tu_abc", "name": "search"}}},
                "contentBlockIndex": 0,
            },
            state,
        )
        assert result is None
        assert state["tool_calls"][0]["name"] == "search"

    def test_tool_input_delta(self):
        state: dict[str, Any] = {"tool_calls": {0: {"id": "tu_abc", "name": "search", "arguments": ""}}}
        result = parse_converse_stream_event(
            {
                "contentBlockDelta": {"delta": {"toolUse": {"input": '{"q"'}}},
                "contentBlockIndex": 0,
            },
            state,
        )
        assert result is not None
        assert state["tool_calls"][0]["arguments"] == '{"q"'

    def test_message_stop_sets_finish_reason(self):
        state: dict[str, Any] = {}
        result = parse_converse_stream_event({"messageStop": {"stopReason": "end_turn"}}, state)
        assert result is None
        assert state["finish_reason"] == "stop"
        assert state["done"] is True

    def test_metadata_event(self):
        state: dict[str, Any] = {}
        result = parse_converse_stream_event({"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5}}}, state)
        assert result is None
        assert state["prompt_tokens"] == 10
        assert state["completion_tokens"] == 5

    def test_unknown_event_returns_none(self):
        state: dict[str, Any] = {}
        result = parse_converse_stream_event({"unknownEvent": {}}, state)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# EventStream decoder
# ═══════════════════════════════════════════════════════════════════════════


class TestDecodeEventStream:
    def test_empty_bytes(self):
        assert decode_event_stream(b"") == []

    def test_single_event(self):
        payload = json.dumps({"messageStart": {"role": "assistant"}}).encode()
        binary = _build_event_stream_message(payload)
        events = decode_event_stream(binary)
        assert len(events) == 1
        assert events[0] == {"messageStart": {"role": "assistant"}}

    def test_multiple_events(self):
        payloads = [
            {"messageStart": {"role": "assistant"}},
            {"contentBlockDelta": {"delta": {"text": "Hi"}, "contentBlockIndex": 0}},
            {"messageStop": {"stopReason": "end_turn"}},
        ]
        binary = b"".join(_build_event_stream_message(json.dumps(p).encode()) for p in payloads)
        events = decode_event_stream(binary)
        assert len(events) == 3
        assert events[1]["contentBlockDelta"]["delta"]["text"] == "Hi"


# ═══════════════════════════════════════════════════════════════════════════
# Provider instantiation
# ═══════════════════════════════════════════════════════════════════════════


class TestBedrockProviderInit:
    def test_default_region(self):
        p = _make_provider()
        assert p.region == DEFAULT_REGION

    def test_custom_region(self):
        p = _make_provider(region="eu-west-1")
        assert p.region == "eu-west-1"
        assert "eu-west-1" in p.api_base

    def test_credentials_stored(self):
        p = _make_provider(access_key_id="AKIA123", secret_access_key="my-secret")
        assert p.access_key_id == "AKIA123"
        assert p.secret_access_key == "my-secret"

    def test_session_token_stored(self):
        p = _make_provider(session_token="my-token")
        assert p.session_token == "my-token"

    def test_custom_api_base(self):
        p = BedrockProvider(
            access_key_id="key",
            secret_access_key="secret",
            api_base="https://mock.bedrock.test",
        )
        assert p.api_base == "https://mock.bedrock.test"

    def test_headers_no_auth_bearer(self):
        p = _make_provider()
        headers = p._build_headers()
        assert "Authorization" not in headers
        assert "Content-Type" in headers


# ═══════════════════════════════════════════════════════════════════════════
# Provider: chat_completion
# ═══════════════════════════════════════════════════════════════════════════


class TestBedrockChatCompletion:
    @pytest.mark.asyncio
    async def test_basic_completion(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        base = build_bedrock_base_url()
        respx_mock.post(f"{base}/model/{model}/converse").mock(return_value=httpx.Response(200, json=fixture))

        p = _make_provider()
        result = await p.chat_completion(_make_request(model=model))

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hello! How can I help you today?"
        assert result.usage.total_tokens == 21
        await p.close()

    @pytest.mark.asyncio
    async def test_tool_use_response(self, respx_mock):
        fixture = _load_fixture("chat_completion_tool_use.json")
        model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        base = build_bedrock_base_url()
        respx_mock.post(f"{base}/model/{model}/converse").mock(return_value=httpx.Response(200, json=fixture))

        p = _make_provider()
        result = await p.chat_completion(_make_request(model=model))

        assert result.choices[0].finish_reason == "tool_calls"
        assert result.choices[0].message.tool_calls is not None
        await p.close()

    @pytest.mark.asyncio
    async def test_auth_error(self, respx_mock):
        model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        base = build_bedrock_base_url()
        respx_mock.post(f"{base}/model/{model}/converse").mock(
            return_value=httpx.Response(
                401,
                json={"message": "Invalid credentials", "__type": "UnrecognizedClientException"},
            )
        )

        p = _make_provider()
        with pytest.raises(AuthenticationError):
            await p.chat_completion(_make_request(model=model))
        await p.close()

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, respx_mock):
        model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        base = build_bedrock_base_url()
        respx_mock.post(f"{base}/model/{model}/converse").mock(
            return_value=httpx.Response(
                429,
                json={"message": "Too many requests", "__type": "TooManyRequestsException"},
            )
        )

        p = _make_provider()
        with pytest.raises(RateLimitError):
            await p.chat_completion(_make_request(model=model))
        await p.close()

    @pytest.mark.asyncio
    async def test_server_error(self, respx_mock):
        model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        base = build_bedrock_base_url()
        respx_mock.post(f"{base}/model/{model}/converse").mock(
            return_value=httpx.Response(
                500,
                json={"message": "Internal error"},
            )
        )

        p = _make_provider()
        with pytest.raises(ServiceUnavailableError):
            await p.chat_completion(_make_request(model=model))
        await p.close()

    @pytest.mark.asyncio
    async def test_request_has_sigv4_headers(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        base = build_bedrock_base_url()
        captured_headers: list[dict[str, str]] = []

        def capture(request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            return httpx.Response(200, json=fixture)

        respx_mock.post(f"{base}/model/{model}/converse").mock(side_effect=capture)

        p = _make_provider()
        await p.chat_completion(_make_request(model=model))

        assert len(captured_headers) == 1
        h = captured_headers[0]
        assert "authorization" in h
        assert h["authorization"].startswith("AWS4-HMAC-SHA256")
        assert "x-amz-date" in h
        await p.close()

    @pytest.mark.asyncio
    async def test_system_message_in_body(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        base = build_bedrock_base_url()
        captured_bodies: list[bytes] = []

        def capture(request: httpx.Request) -> httpx.Response:
            captured_bodies.append(request.content)
            return httpx.Response(200, json=fixture)

        respx_mock.post(f"{base}/model/{model}/converse").mock(side_effect=capture)

        p = _make_provider()
        request = CompletionRequest(
            model=model,
            messages=[
                Message(role="system", content="Be concise."),
                Message(role="user", content="Hello"),
            ],
        )
        await p.chat_completion(request)

        body = json.loads(captured_bodies[0])
        assert "system" in body
        assert body["system"][0]["text"] == "Be concise."
        for msg in body["messages"]:
            assert msg.get("role") != "system"
        await p.close()

    @pytest.mark.asyncio
    async def test_session_token_in_headers(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        base = build_bedrock_base_url()
        captured_headers: list[dict[str, str]] = []

        def capture(request: httpx.Request) -> httpx.Response:
            captured_headers.append(dict(request.headers))
            return httpx.Response(200, json=fixture)

        respx_mock.post(f"{base}/model/{model}/converse").mock(side_effect=capture)

        p = _make_provider(session_token="sts-token-xyz")
        await p.chat_completion(_make_request(model=model))

        h = captured_headers[0]
        assert h.get("x-amz-security-token") == "sts-token-xyz"
        await p.close()


# ═══════════════════════════════════════════════════════════════════════════
# Provider: unsupported ops
# ═══════════════════════════════════════════════════════════════════════════


class TestBedrockUnsupportedOps:
    @pytest.mark.asyncio
    async def test_embedding_raises(self):
        from routerbot.core.types import EmbeddingRequest

        p = _make_provider()
        with pytest.raises(ProviderError, match="embeddings"):
            await p.embedding(EmbeddingRequest(model="any", input="text"))

    @pytest.mark.asyncio
    async def test_image_generation_raises(self):
        from routerbot.core.types import ImageRequest

        p = _make_provider()
        with pytest.raises(ProviderError, match="image generation"):
            await p.image_generation(ImageRequest(model="any", prompt="A cat"))

    @pytest.mark.asyncio
    async def test_transcription_raises(self):
        from routerbot.core.types import AudioTranscriptionRequest

        p = _make_provider()
        with pytest.raises(ProviderError, match="transcription"):
            await p.audio_transcription(AudioTranscriptionRequest(model="any"))
