"""Tests for the Google Gemini and Vertex AI providers."""

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
from routerbot.providers.gemini.config import (
    FINISH_REASON_MAP,
    GEMINI_MODELS,
    build_vertex_base_url,
)
from routerbot.providers.gemini.provider import GeminiProvider
from routerbot.providers.gemini.transform import (
    build_gemini_request,
    gemini_response_to_openai,
    gemini_sse_chunk_to_openai,
    openai_to_gemini_contents,
    openai_tools_to_gemini,
)
from routerbot.providers.vertex_ai.provider import VertexAIProvider

FIXTURES = Path(__file__).parent.parent / "fixtures" / "gemini"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def _make_gemini(**kwargs: Any) -> GeminiProvider:
    return GeminiProvider(
        api_key=kwargs.pop("api_key", "test-api-key"),
        api_base=kwargs.pop("api_base", "https://generativelanguage.googleapis.com"),
        **kwargs,
    )


def _make_vertex(**kwargs: Any) -> VertexAIProvider:
    return VertexAIProvider(
        project_id=kwargs.pop("project_id", "my-project"),
        access_token=kwargs.pop("access_token", "ya29.test-token"),
        **kwargs,
    )


def _make_request(
    model: str = "gemini-2.0-flash",
    content: str = "Hello",
    **kwargs: Any,
) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[Message(role="user", content=content)],
        **kwargs,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Config tests
# ═══════════════════════════════════════════════════════════════════════════


class TestConfig:
    def test_finish_reason_stop(self):
        assert FINISH_REASON_MAP["STOP"] == "stop"

    def test_finish_reason_max_tokens(self):
        assert FINISH_REASON_MAP["MAX_TOKENS"] == "length"

    def test_finish_reason_safety(self):
        assert FINISH_REASON_MAP["SAFETY"] == "content_filter"

    def test_gemini_models_not_empty(self):
        assert len(GEMINI_MODELS) > 0

    def test_gemini_flash_in_models(self):
        assert "gemini-2.0-flash" in GEMINI_MODELS

    def test_build_vertex_base_url(self):
        url = build_vertex_base_url("my-project", "us-central1")
        assert "us-central1" in url
        assert "my-project" in url
        assert "aiplatform.googleapis.com" in url

    def test_build_vertex_url_region(self):
        url = build_vertex_base_url("proj", "eu-west4")
        assert url.startswith("https://eu-west4-aiplatform.googleapis.com")


# ═══════════════════════════════════════════════════════════════════════════
# Transform: openai_to_gemini_contents
# ═══════════════════════════════════════════════════════════════════════════


class TestOpenAIToGeminiContents:
    def test_simple_user_message(self):
        msgs = [{"role": "user", "content": "Hello"}]
        system, contents = openai_to_gemini_contents(msgs)
        assert system is None
        assert contents[0]["role"] == "user"
        assert {"text": "Hello"} in contents[0]["parts"]

    def test_system_extracted(self):
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        system, contents = openai_to_gemini_contents(msgs)
        assert system is not None
        assert system["parts"][0]["text"] == "You are helpful."
        assert len(contents) == 1

    def test_assistant_role_mapped_to_model(self):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        _, contents = openai_to_gemini_contents(msgs)
        assert contents[1]["role"] == "model"
        assert {"text": "Hello!"} in contents[1]["parts"]

    def test_tool_result_becomes_function_response(self):
        msgs = [{"role": "tool", "tool_call_id": "call_abc", "content": '{"temp": 72}'}]
        _, contents = openai_to_gemini_contents(msgs)
        assert contents[0]["role"] == "user"
        part = contents[0]["parts"][0]
        assert "functionResponse" in part
        assert part["functionResponse"]["response"] == {"temp": 72}

    def test_tool_result_plain_text(self):
        msgs = [{"role": "tool", "tool_call_id": "call_abc", "content": "72°F"}]
        _, contents = openai_to_gemini_contents(msgs)
        fr = contents[0]["parts"][0]["functionResponse"]
        assert fr["response"] == {"result": "72°F"}

    def test_tool_calls_in_assistant(self):
        msgs = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_xyz",
                        "type": "function",
                        "function": {"name": "search", "arguments": '{"q": "cats"}'},
                    }
                ],
            }
        ]
        _, contents = openai_to_gemini_contents(msgs)
        assert contents[0]["role"] == "model"
        fc = contents[0]["parts"][0]["functionCall"]
        assert fc["name"] == "search"
        assert fc["args"] == {"q": "cats"}

    def test_image_base64_content(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,/9j/AAAA"},
                    },
                ],
            }
        ]
        _, contents = openai_to_gemini_contents(msgs)
        parts = contents[0]["parts"]
        assert any("text" in p for p in parts)
        assert any("inlineData" in p for p in parts)
        inline = next(p for p in parts if "inlineData" in p)
        assert inline["inlineData"]["mimeType"] == "image/jpeg"
        assert inline["inlineData"]["data"] == "/9j/AAAA"

    def test_developer_role_treated_as_system(self):
        msgs = [
            {"role": "developer", "content": "Dev system prompt."},
            {"role": "user", "content": "Hi"},
        ]
        system, _ = openai_to_gemini_contents(msgs)
        assert system is not None
        assert system["parts"][0]["text"] == "Dev system prompt."

    def test_multiple_system_parts(self):
        msgs = [
            {"role": "system", "content": "Part 1."},
            {"role": "system", "content": "Part 2."},
            {"role": "user", "content": "Hi"},
        ]
        system, _ = openai_to_gemini_contents(msgs)
        assert system is not None
        assert len(system["parts"]) == 2


# ═══════════════════════════════════════════════════════════════════════════
# Transform: openai_tools_to_gemini
# ═══════════════════════════════════════════════════════════════════════════


class TestOpenAIToolsToGemini:
    def test_none_returns_none(self):
        assert openai_tools_to_gemini(None) is None

    def test_empty_returns_none(self):
        assert openai_tools_to_gemini([]) is None

    def test_converts_function_declaration(self):
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
        result = openai_tools_to_gemini(tools)
        assert result is not None
        decl = result[0]["functionDeclarations"][0]
        assert decl["name"] == "get_weather"
        assert decl["description"] == "Get weather"
        assert "parameters" in decl


# ═══════════════════════════════════════════════════════════════════════════
# Transform: build_gemini_request
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildGeminiRequest:
    def test_basic_payload(self):
        msgs = [{"role": "user", "parts": [{"text": "Hi"}]}]
        payload = build_gemini_request(msgs, None, max_tokens=1024)
        assert payload["contents"] == msgs
        assert payload["generationConfig"]["maxOutputTokens"] == 1024

    def test_system_instruction_included(self):
        msgs = [{"role": "user", "parts": [{"text": "Hi"}]}]
        system = {"parts": [{"text": "Be helpful"}]}
        payload = build_gemini_request(msgs, system, max_tokens=512)
        assert payload["systemInstruction"] == system

    def test_temperature_in_generation_config(self):
        msgs = [{"role": "user", "parts": [{"text": "Hi"}]}]
        payload = build_gemini_request(msgs, None, max_tokens=512, temperature=0.8)
        assert payload["generationConfig"]["temperature"] == 0.8

    def test_stop_sequences(self):
        msgs = [{"role": "user", "parts": [{"text": "Hi"}]}]
        payload = build_gemini_request(msgs, None, max_tokens=512, stop=["STOP"])
        assert payload["generationConfig"]["stopSequences"] == ["STOP"]

    def test_tools_included(self):
        msgs = [{"role": "user", "parts": [{"text": "Hi"}]}]
        tools = [{"functionDeclarations": [{"name": "test", "description": ""}]}]
        payload = build_gemini_request(msgs, None, max_tokens=512, tools=tools)
        assert payload["tools"] == tools

    def test_no_generation_config_when_empty(self):
        msgs = [{"role": "user", "parts": [{"text": "Hi"}]}]
        payload = build_gemini_request(msgs, None)
        assert "generationConfig" not in payload


# ═══════════════════════════════════════════════════════════════════════════
# Transform: gemini_response_to_openai
# ═══════════════════════════════════════════════════════════════════════════


class TestGeminiResponseToOpenAI:
    def test_simple_chat_response(self):
        data = _load_fixture("chat_completion.json")
        result = gemini_response_to_openai(data, "gemini-2.0-flash")

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hello! How can I help you today?"
        assert result.choices[0].finish_reason == "stop"
        assert result.usage.prompt_tokens == 4
        assert result.usage.completion_tokens == 9
        assert result.usage.total_tokens == 13

    def test_model_version_from_response(self):
        data = _load_fixture("chat_completion.json")
        result = gemini_response_to_openai(data, "gemini-2.0-flash")
        assert result.model == "gemini-2.0-flash-001"

    def test_tool_call_response(self):
        data = _load_fixture("chat_completion_tool_call.json")
        result = gemini_response_to_openai(data, "gemini-2.0-flash")

        assert result.choices[0].finish_reason == "tool_calls"
        tool_calls = result.choices[0].message.tool_calls
        assert tool_calls is not None
        assert tool_calls[0].function.name == "get_weather"
        args = json.loads(tool_calls[0].function.arguments)
        assert args["location"] == "San Francisco, CA"

    def test_max_tokens_finish_reason(self):
        data = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "..."}], "role": "model"},
                    "finishReason": "MAX_TOKENS",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 5,
                "candidatesTokenCount": 100,
                "totalTokenCount": 105,
            },
        }
        result = gemini_response_to_openai(data, "model")
        assert result.choices[0].finish_reason == "length"


# ═══════════════════════════════════════════════════════════════════════════
# Transform: gemini_sse_chunk_to_openai
# ═══════════════════════════════════════════════════════════════════════════


class TestGeminiSseChunkToOpenAI:
    def test_text_chunk(self):
        state: dict[str, Any] = {}
        data = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello"}],
                        "role": "model",
                    },
                    "finishReason": "",
                }
            ]
        }
        chunk = gemini_sse_chunk_to_openai(data, "gemini-2.0-flash", "id-1", state)
        assert chunk is not None
        assert chunk.choices[0].delta.content == "Hello"
        assert chunk.choices[0].finish_reason is None

    def test_final_chunk_with_finish_reason(self):
        state: dict[str, Any] = {}
        data = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Done."}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ]
        }
        chunk = gemini_sse_chunk_to_openai(data, "model", "id-1", state)
        assert chunk is not None
        assert chunk.choices[0].finish_reason == "stop"
        assert state.get("done") is True

    def test_tool_call_chunk(self):
        state: dict[str, Any] = {}
        data = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"functionCall": {"name": "get_weather", "args": {"loc": "NYC"}}}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ]
        }
        chunk = gemini_sse_chunk_to_openai(data, "model", "id-1", state)
        assert chunk is not None
        assert chunk.choices[0].finish_reason == "tool_calls"
        tc = chunk.choices[0].delta.tool_calls
        assert tc is not None
        assert tc[0].function.name == "get_weather"

    def test_empty_candidates_returns_none(self):
        state: dict[str, Any] = {}
        chunk = gemini_sse_chunk_to_openai({}, "model", "id-1", state)
        assert chunk is None

    def test_usage_metadata_stored(self):
        state: dict[str, Any] = {}
        gemini_sse_chunk_to_openai(
            {
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 5,
                }
            },
            "model",
            "id-1",
            state,
        )
        assert state["prompt_tokens"] == 10
        assert state["completion_tokens"] == 5


# ═══════════════════════════════════════════════════════════════════════════
# GeminiProvider instantiation
# ═══════════════════════════════════════════════════════════════════════════


class TestGeminiProviderInit:
    def test_api_key_stored(self):
        p = _make_gemini(api_key="my-key")
        assert p.api_key == "my-key"

    def test_default_base_url(self):
        p = GeminiProvider(api_key="k")
        assert "generativelanguage.googleapis.com" in p.api_base

    def test_custom_base_url(self):
        p = GeminiProvider(api_key="k", api_base="https://mock.gemini.test")
        assert p.api_base == "https://mock.gemini.test"

    def test_headers_no_authorization(self):
        p = _make_gemini()
        h = p._build_headers()
        assert "Authorization" not in h
        assert "Content-Type" in h

    def test_base_params_has_key(self):
        p = _make_gemini(api_key="mykey")
        assert p._base_params() == {"key": "mykey"}

    def test_chat_path_format(self):
        p = _make_gemini()
        assert "gemini-2.0-flash" in p._chat_path("gemini-2.0-flash")
        assert "generateContent" in p._chat_path("gemini-2.0-flash")

    def test_streaming_path_format(self):
        p = _make_gemini()
        assert "streamGenerateContent" in p._chat_path("gemini-2.0-flash", streaming=True)


# ═══════════════════════════════════════════════════════════════════════════
# GeminiProvider: chat_completion
# ═══════════════════════════════════════════════════════════════════════════


class TestGeminiChatCompletion:
    @pytest.mark.asyncio
    async def test_basic_completion(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        model = "gemini-2.0-flash"
        base = "https://generativelanguage.googleapis.com"
        respx_mock.post(url__regex=rf"{base}/v1beta/models/{model}:generateContent.*").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        p = _make_gemini()
        result = await p.chat_completion(_make_request(model=model))

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hello! How can I help you today?"
        assert result.usage.total_tokens == 13
        await p.close()

    @pytest.mark.asyncio
    async def test_api_key_in_query_params(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        model = "gemini-2.0-flash"
        captured: list[httpx.Request] = []

        def capture(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json=fixture)

        respx_mock.post(url__regex=r".*generateContent.*").mock(side_effect=capture)

        p = _make_gemini(api_key="myapikey")
        await p.chat_completion(_make_request(model=model))

        assert len(captured) == 1
        assert "myapikey" in str(captured[0].url)
        await p.close()

    @pytest.mark.asyncio
    async def test_tool_call_response(self, respx_mock):
        fixture = _load_fixture("chat_completion_tool_call.json")
        model = "gemini-2.0-flash"
        respx_mock.post(url__regex=r".*generateContent.*").mock(return_value=httpx.Response(200, json=fixture))

        p = _make_gemini()
        result = await p.chat_completion(_make_request(model=model))

        assert result.choices[0].finish_reason == "tool_calls"
        assert result.choices[0].message.tool_calls is not None
        await p.close()

    @pytest.mark.asyncio
    async def test_system_message_in_payload(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        captured_bodies: list[bytes] = []

        def capture(req: httpx.Request) -> httpx.Response:
            captured_bodies.append(req.content)
            return httpx.Response(200, json=fixture)

        respx_mock.post(url__regex=r".*generateContent.*").mock(side_effect=capture)

        p = _make_gemini()
        request = CompletionRequest(
            model="gemini-2.0-flash",
            messages=[
                Message(role="system", content="Be concise."),
                Message(role="user", content="Hello"),
            ],
        )
        await p.chat_completion(request)

        body = json.loads(captured_bodies[0])
        assert "systemInstruction" in body
        assert body["systemInstruction"]["parts"][0]["text"] == "Be concise."
        for msg in body["contents"]:
            assert msg.get("role") not in ("system",)
        await p.close()

    @pytest.mark.asyncio
    async def test_auth_error_401(self, respx_mock):
        respx_mock.post(url__regex=r".*generateContent.*").mock(
            return_value=httpx.Response(401, json={"error": {"message": "API key invalid", "code": 401}})
        )
        p = _make_gemini()
        with pytest.raises(AuthenticationError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_auth_error_403(self, respx_mock):
        respx_mock.post(url__regex=r".*generateContent.*").mock(
            return_value=httpx.Response(403, json={"error": {"message": "Permission denied"}})
        )
        p = _make_gemini()
        with pytest.raises(AuthenticationError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, respx_mock):
        respx_mock.post(url__regex=r".*generateContent.*").mock(
            return_value=httpx.Response(429, json={"error": {"message": "Resource exhausted"}})
        )
        p = _make_gemini()
        with pytest.raises(RateLimitError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_server_error(self, respx_mock):
        respx_mock.post(url__regex=r".*generateContent.*").mock(
            return_value=httpx.Response(500, json={"error": {"message": "Internal"}})
        )
        p = _make_gemini()
        with pytest.raises(ServiceUnavailableError):
            await p.chat_completion(_make_request())
        await p.close()


# ═══════════════════════════════════════════════════════════════════════════
# GeminiProvider: streaming
# ═══════════════════════════════════════════════════════════════════════════


class TestGeminiChatStream:
    @pytest.mark.asyncio
    async def test_streaming_yields_content(self, respx_mock):
        sse_body = (
            'data: {"candidates": [{"content": {"parts": [{"text": "Hello"}], "role": "model"}, "finishReason": ""}]}\n'
            'data: {"candidates": [{"content": {"parts": [{"text": " world"}], "role": "model"}, "finishReason": "STOP"}]}\n'
        )
        respx_mock.post(url__regex=r".*streamGenerateContent.*").mock(return_value=httpx.Response(200, text=sse_body))

        p = _make_gemini()
        chunks = []
        async for chunk in p.chat_completion_stream(_make_request()):
            chunks.append(chunk)

        assert len(chunks) >= 1
        contents = [c.choices[0].delta.content for c in chunks if c.choices[0].delta.content]
        assert "Hello" in contents or any("Hello" in str(c) for c in contents)
        await p.close()


# ═══════════════════════════════════════════════════════════════════════════
# GeminiProvider: embeddings
# ═══════════════════════════════════════════════════════════════════════════


class TestGeminiEmbeddings:
    @pytest.mark.asyncio
    async def test_basic_embedding(self, respx_mock):
        fixture = _load_fixture("embedding.json")
        respx_mock.post(url__regex=r".*embedContent.*").mock(return_value=httpx.Response(200, json=fixture))

        p = _make_gemini()
        result = await p.embedding(EmbeddingRequest(model="text-embedding-004", input="Hello world"))

        assert len(result.data) == 1
        assert len(result.data[0].embedding) == 8
        await p.close()

    @pytest.mark.asyncio
    async def test_list_input_batch(self, respx_mock):
        fixture = _load_fixture("embedding.json")
        respx_mock.post(url__regex=r".*embedContent.*").mock(return_value=httpx.Response(200, json=fixture))

        p = _make_gemini()
        result = await p.embedding(EmbeddingRequest(model="text-embedding-004", input=["text 1", "text 2"]))

        assert len(result.data) == 2
        await p.close()


# ═══════════════════════════════════════════════════════════════════════════
# GeminiProvider: unsupported ops
# ═══════════════════════════════════════════════════════════════════════════


class TestGeminiUnsupported:
    @pytest.mark.asyncio
    async def test_image_generation_raises(self):
        from routerbot.core.types import ImageRequest

        p = _make_gemini()
        with pytest.raises(ProviderError, match="image generation"):
            await p.image_generation(ImageRequest(model="any", prompt="A cat"))

    @pytest.mark.asyncio
    async def test_audio_transcription_raises(self):
        from routerbot.core.types import AudioTranscriptionRequest

        p = _make_gemini()
        with pytest.raises(ProviderError, match="transcription"):
            await p.audio_transcription(AudioTranscriptionRequest(model="any"))


# ═══════════════════════════════════════════════════════════════════════════
# VertexAIProvider
# ═══════════════════════════════════════════════════════════════════════════


class TestVertexAIProvider:
    def test_init_stores_project(self):
        p = _make_vertex(project_id="my-proj")
        assert p.project_id == "my-proj"

    def test_init_stores_region(self):
        p = _make_vertex(region="eu-west4")
        assert p.region == "eu-west4"

    def test_api_base_contains_project(self):
        p = _make_vertex(project_id="test-project")
        assert "test-project" in p.api_base

    def test_api_base_contains_region(self):
        p = _make_vertex(region="asia-east1")
        assert "asia-east1" in p.api_base

    def test_headers_include_bearer(self):
        p = _make_vertex(access_token="ya29.abc123")
        headers = p._build_headers()
        assert headers.get("Authorization") == "Bearer ya29.abc123"

    def test_base_params_empty(self):
        """Vertex AI uses Bearer auth, no query params needed."""
        p = _make_vertex()
        assert p._base_params() == {}

    def test_chat_path_no_api_version_prefix(self):
        p = _make_vertex()
        path = p._chat_path("gemini-2.0-flash")
        assert "models/gemini-2.0-flash" in path
        assert "generateContent" in path

    def test_custom_api_base(self):
        p = VertexAIProvider(
            project_id="proj",
            access_token="token",
            api_base="https://mock.vertex.test",
        )
        assert p.api_base == "https://mock.vertex.test"

    @pytest.mark.asyncio
    async def test_vertex_completion(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        project = "my-project"
        region = "us-central1"
        base = build_vertex_base_url(project, region)

        escaped_base = base.replace(".", "\\.")
        respx_mock.post(url__regex=f"{escaped_base}.*generateContent.*").mock(
            return_value=httpx.Response(200, json=fixture)
        )

        p = _make_vertex(project_id=project, region=region)
        result = await p.chat_completion(_make_request(model="gemini-2.0-flash"))

        assert isinstance(result, CompletionResponse)
        await p.close()

    @pytest.mark.asyncio
    async def test_vertex_request_has_bearer_token(self, respx_mock):
        fixture = _load_fixture("chat_completion.json")
        captured: list[httpx.Request] = []

        def capture(req: httpx.Request) -> httpx.Response:
            captured.append(req)
            return httpx.Response(200, json=fixture)

        respx_mock.post(url__regex=r".*generateContent.*").mock(side_effect=capture)

        p = _make_vertex(access_token="ya29.mytoken")
        await p.chat_completion(_make_request())

        assert len(captured) == 1
        auth_header = captured[0].headers.get("authorization", "")
        assert auth_header == "Bearer ya29.mytoken"
        # API key should NOT appear in URL
        assert "key=" not in str(captured[0].url)
        await p.close()
