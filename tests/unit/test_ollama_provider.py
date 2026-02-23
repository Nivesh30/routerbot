"""Tests for the Ollama local LLM provider (Task 2.8)."""

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
    EmbeddingRequest,
    Message,
)
from routerbot.providers.ollama.provider import OLLAMA_DEFAULT_BASE_URL, OllamaProvider
from routerbot.providers.ollama.transform import (
    FINISH_REASON_MAP,
    ollama_chunk_to_openai,
    ollama_response_to_openai,
)
from routerbot.providers.registry import get_provider_class

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(provider: str, name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / provider / name).read_text())


def _make_request(
    model: str = "llama3.2",
    content: str = "Hello",
    **kwargs: Any,
) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[Message(role="user", content=content)],
        **kwargs,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Transform helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestOllamaTransform:
    def test_finish_reason_stop(self):
        assert FINISH_REASON_MAP["stop"].value == "stop"

    def test_finish_reason_length(self):
        assert FINISH_REASON_MAP["length"].value == "length"

    def test_finish_reason_load_maps_to_stop(self):
        assert FINISH_REASON_MAP["load"].value == "stop"

    def test_basic_response(self):
        fixture = _load_fixture("ollama", "chat_completion.json")
        result = ollama_response_to_openai(fixture, "llama3.2")
        assert isinstance(result, CompletionResponse)
        assert result.model == "llama3.2"
        assert result.choices[0].message.content == "Hello from Ollama!"
        assert result.choices[0].finish_reason == "stop"
        # Usage
        assert result.usage is not None
        assert result.usage.prompt_tokens == 26
        assert result.usage.completion_tokens == 8
        assert result.usage.total_tokens == 34

    def test_tool_call_response(self):
        fixture = _load_fixture("ollama", "chat_completion_tool_call.json")
        result = ollama_response_to_openai(fixture, "llama3.2")
        assert result.choices[0].message.tool_calls is not None
        tc = result.choices[0].message.tool_calls[0]
        assert tc.function.name == "get_weather"
        args = json.loads(tc.function.arguments)
        assert args["location"] == "London"

    def test_stream_chunk_with_content(self):
        data = {
            "model": "llama3.2",
            "message": {"role": "assistant", "content": "Hello"},
            "done": False,
        }
        chunk = ollama_chunk_to_openai(data, "llama3.2", "chatcmpl-test-id")
        assert isinstance(chunk, CompletionResponseChunk)
        assert chunk.choices[0].delta.content == "Hello"
        assert chunk.choices[0].finish_reason is None
        assert chunk.usage is None

    def test_stream_chunk_final_done(self):
        data = {
            "model": "llama3.2",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        chunk = ollama_chunk_to_openai(data, "llama3.2", "chatcmpl-test-id")
        assert chunk.choices[0].finish_reason == "stop"
        assert chunk.usage is not None
        assert chunk.usage.prompt_tokens == 10
        assert chunk.usage.completion_tokens == 5
        assert chunk.usage.total_tokens == 15

    def test_stream_chunk_length_finish(self):
        data = {
            "model": "llama3.2",
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "length",
            "prompt_eval_count": 100,
            "eval_count": 200,
        }
        chunk = ollama_chunk_to_openai(data, "llama3.2", "chatcmpl-test-id")
        assert chunk.choices[0].finish_reason == "length"

    def test_stream_chunk_empty_content_is_none(self):
        data = {
            "model": "llama3.2",
            "message": {"role": "assistant", "content": ""},
            "done": False,
        }
        chunk = ollama_chunk_to_openai(data, "llama3.2", "chatcmpl-id")
        # Empty string should map to None (no content delta)
        assert chunk.choices[0].delta.content is None


# ═══════════════════════════════════════════════════════════════════════════
# OllamaProvider
# ═══════════════════════════════════════════════════════════════════════════


class TestOllamaProvider:
    def test_provider_name(self):
        p = OllamaProvider()
        assert p.provider_name == "ollama"

    def test_default_base_url(self):
        p = OllamaProvider()
        assert p.api_base == OLLAMA_DEFAULT_BASE_URL

    def test_custom_base_url(self):
        p = OllamaProvider(api_base="http://remote-host:11434")
        assert p.api_base == "http://remote-host:11434"

    def test_no_auth_header_without_key(self):
        p = OllamaProvider()
        headers = p._build_headers()
        assert "Authorization" not in headers

    def test_bearer_auth_header_with_key(self):
        p = OllamaProvider(api_key="my-secret")
        headers = p._build_headers()
        assert headers.get("Authorization") == "Bearer my-secret"

    def test_no_api_key_required(self):
        # Ollama doesn't require an API key
        p = OllamaProvider()
        assert p.api_key is None

    # ------------------------------------------------------------------
    # Payload building
    # ------------------------------------------------------------------

    def test_build_chat_payload_basic(self):
        p = OllamaProvider()
        req = _make_request(model="llama3.2", content="hi")
        payload = p._build_chat_payload(req)
        assert payload["model"] == "llama3.2"
        assert payload["messages"][0]["role"] == "user"
        assert payload["messages"][0]["content"] == "hi"

    def test_build_chat_payload_with_options(self):
        p = OllamaProvider()
        req = _make_request(model="llama3.2", temperature=0.7, max_tokens=100, top_p=0.9)
        payload = p._build_chat_payload(req)
        assert payload["options"]["temperature"] == 0.7
        assert payload["options"]["num_predict"] == 100
        assert payload["options"]["top_p"] == 0.9

    def test_build_chat_payload_no_options_key_when_empty(self):
        p = OllamaProvider()
        req = _make_request(model="llama3.2")
        payload = p._build_chat_payload(req)
        assert "options" not in payload

    def test_build_chat_payload_stop_as_list(self):
        p = OllamaProvider()
        req = _make_request(model="llama3.2", stop=["</s>", "<|end|>"])
        payload = p._build_chat_payload(req)
        assert payload["options"]["stop"] == ["</s>", "<|end|>"]

    def test_build_chat_payload_stop_as_string(self):
        p = OllamaProvider()
        req = _make_request(model="llama3.2", stop="</s>")
        payload = p._build_chat_payload(req)
        assert payload["options"]["stop"] == ["</s>"]

    # ------------------------------------------------------------------
    # Chat completion (mocked)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_chat_completion(self, respx_mock):
        fixture = _load_fixture("ollama", "chat_completion.json")
        respx_mock.post("http://localhost:11434/api/chat").mock(return_value=httpx.Response(200, json=fixture))

        p = OllamaProvider()
        result = await p.chat_completion(_make_request(model="llama3.2"))

        assert isinstance(result, CompletionResponse)
        assert result.choices[0].message.content == "Hello from Ollama!"
        assert result.choices[0].finish_reason == "stop"
        assert result.usage is not None
        assert result.usage.total_tokens == 34
        await p.close()

    @pytest.mark.asyncio
    async def test_chat_completion_custom_base(self, respx_mock):
        fixture = _load_fixture("ollama", "chat_completion.json")
        respx_mock.post("http://remote:11434/api/chat").mock(return_value=httpx.Response(200, json=fixture))

        p = OllamaProvider(api_base="http://remote:11434")
        result = await p.chat_completion(_make_request(model="llama3.2"))
        assert isinstance(result, CompletionResponse)
        await p.close()

    @pytest.mark.asyncio
    async def test_tool_call_response(self, respx_mock):
        fixture = _load_fixture("ollama", "chat_completion_tool_call.json")
        respx_mock.post("http://localhost:11434/api/chat").mock(return_value=httpx.Response(200, json=fixture))

        p = OllamaProvider()
        result = await p.chat_completion(_make_request(model="llama3.2"))
        tc = result.choices[0].message.tool_calls
        assert tc is not None
        assert tc[0].function.name == "get_weather"
        await p.close()

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_chat_completion_stream(self, respx_mock):
        lines = [
            json.dumps({"model": "llama3.2", "message": {"role": "assistant", "content": "Hello"}, "done": False}),
            json.dumps({"model": "llama3.2", "message": {"role": "assistant", "content": " World"}, "done": False}),
            json.dumps(
                {
                    "model": "llama3.2",
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 5,
                    "eval_count": 3,
                }
            ),
        ]
        stream_body = "\n".join(lines)
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, text=stream_body, headers={"Content-Type": "application/x-ndjson"})
        )

        p = OllamaProvider()
        chunks = []
        async for chunk in p.chat_completion_stream(_make_request(model="llama3.2")):
            chunks.append(chunk)

        assert len(chunks) == 3
        assert chunks[0].choices[0].delta.content == "Hello"
        assert chunks[1].choices[0].delta.content == " World"
        assert chunks[2].choices[0].finish_reason == "stop"
        assert chunks[2].usage is not None
        assert chunks[2].usage.total_tokens == 8
        await p.close()

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_auth_error(self, respx_mock):
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(401, json={"error": "Unauthorized"})
        )
        p = OllamaProvider(api_key="wrong")
        with pytest.raises(AuthenticationError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, respx_mock):
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(429, json={"error": "Too many requests"})
        )
        p = OllamaProvider()
        with pytest.raises(RateLimitError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_server_error(self, respx_mock):
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(500, json={"error": "Internal server error"})
        )
        p = OllamaProvider()
        with pytest.raises(ServiceUnavailableError):
            await p.chat_completion(_make_request())
        await p.close()

    @pytest.mark.asyncio
    async def test_client_error(self, respx_mock):
        respx_mock.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(400, json={"error": "model not found"})
        )
        p = OllamaProvider()
        with pytest.raises(ProviderError):
            await p.chat_completion(_make_request(model="nonexistent"))
        await p.close()

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_embedding(self, respx_mock):
        fixture = _load_fixture("ollama", "embedding.json")
        respx_mock.post("http://localhost:11434/api/embed").mock(return_value=httpx.Response(200, json=fixture))

        p = OllamaProvider()
        req = EmbeddingRequest(model="nomic-embed-text", input=["hello", "world"])
        result = await p.embedding(req)

        assert len(result.data) == 2
        assert result.data[0].embedding == [0.1, 0.2, 0.3, 0.4, 0.5]
        assert result.data[1].embedding == [0.6, 0.7, 0.8, 0.9, 1.0]
        assert result.model == "nomic-embed-text"
        assert result.usage.total_tokens == 2
        await p.close()

    @pytest.mark.asyncio
    async def test_embedding_single_string(self, respx_mock):
        fixture = {"model": "nomic-embed-text", "embeddings": [[0.1, 0.2, 0.3]], "prompt_eval_count": 1}
        respx_mock.post("http://localhost:11434/api/embed").mock(return_value=httpx.Response(200, json=fixture))

        p = OllamaProvider()
        req = EmbeddingRequest(model="nomic-embed-text", input="hello")
        result = await p.embedding(req)
        assert len(result.data) == 1
        assert result.data[0].embedding == [0.1, 0.2, 0.3]
        await p.close()

    @pytest.mark.asyncio
    async def test_embedding_invalid_input_raises(self):
        p = OllamaProvider()
        req = EmbeddingRequest(model="nomic-embed-text", input=[[1, 2, 3]])
        with pytest.raises(ProviderError, match="list-of-string"):
            await p.embedding(req)
        await p.close()

    # ------------------------------------------------------------------
    # Unsupported endpoints
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_image_generation_raises(self):
        from routerbot.core.types import ImageRequest

        p = OllamaProvider()
        with pytest.raises(ProviderError, match="image generation"):
            await p.image_generation(ImageRequest(model="llama3.2", prompt="a cat"))
        await p.close()

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_health_check_success(self, respx_mock):
        respx_mock.get("http://localhost:11434/api/tags").mock(return_value=httpx.Response(200, json={"models": []}))
        p = OllamaProvider()
        result = await p.health_check()
        assert result is True
        await p.close()

    @pytest.mark.asyncio
    async def test_health_check_failure(self, respx_mock):
        respx_mock.get("http://localhost:11434/api/tags").mock(side_effect=httpx.ConnectError("Connection refused"))
        p = OllamaProvider()
        result = await p.health_check()
        assert result is False
        await p.close()

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def test_registers_in_registry(self):
        cls = get_provider_class("ollama")
        assert cls is OllamaProvider
