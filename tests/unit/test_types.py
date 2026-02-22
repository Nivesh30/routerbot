"""Tests for core type definitions (Task 1.4).

Validates serialization/deserialization round-trips with real OpenAI response
formats, extra-field passthrough, enum values, and edge cases.
"""

from __future__ import annotations

import json
import time

from routerbot.core.enums import (
    AudioResponseFormat,
    AudioVoice,
    CacheType,
    EmbeddingEncodingFormat,
    FinishReason,
    ImageQuality,
    ImageResponseFormat,
    ImageSize,
    ImageStyle,
    Provider,
    Role,
    RoutingStrategy,
)
from routerbot.core.types import (
    AudioSpeechRequest,
    AudioTranscriptionRequest,
    AudioTranscriptionResponse,
    Choice,
    ChoiceMessage,
    CompletionRequest,
    CompletionResponse,
    CompletionResponseChunk,
    CompletionTokensDetails,
    ContentPartImage,
    ContentPartInputAudio,
    ContentPartText,
    EmbeddingRequest,
    EmbeddingResponse,
    Function,
    FunctionCall,
    ImageData,
    ImageRequest,
    ImageResponse,
    ImageUrl,
    InputAudio,
    Message,
    ModelCard,
    ModelListResponse,
    PromptTokensDetails,
    RerankRequest,
    RerankResponse,
    RerankResult,
    ResponseFormatJsonObject,
    ResponseFormatJsonSchema,
    ResponseFormatText,
    StreamOptions,
    Tool,
    ToolCall,
    Usage,
)

# ---------------------------------------------------------------------------
# Fixtures: real-world JSON payloads
# ---------------------------------------------------------------------------

OPENAI_COMPLETION_RESPONSE_JSON = {
    "id": "chatcmpl-B9MBs8CjcvOU2jLn4n570S5qMJKcT",
    "object": "chat.completion",
    "created": 1741569952,
    "model": "gpt-4o-2024-08-06",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Hello! How can I assist you today?",
                "refusal": None,
                "annotations": [],
            },
            "logprobs": None,
            "finish_reason": "stop",
        }
    ],
    "usage": {
        "prompt_tokens": 19,
        "completion_tokens": 10,
        "total_tokens": 29,
        "prompt_tokens_details": {"cached_tokens": 0, "audio_tokens": 0},
        "completion_tokens_details": {
            "reasoning_tokens": 0,
            "audio_tokens": 0,
            "accepted_prediction_tokens": 0,
            "rejected_prediction_tokens": 0,
        },
    },
    "service_tier": "default",
    "system_fingerprint": "fp_a1b2c3d4e5",
}

OPENAI_STREAMING_CHUNK_JSON = {
    "id": "chatcmpl-abc123",
    "object": "chat.completion.chunk",
    "created": 1741569952,
    "model": "gpt-4o",
    "choices": [
        {
            "index": 0,
            "delta": {"role": "assistant", "content": "Hello"},
            "finish_reason": None,
        }
    ],
}

OPENAI_TOOL_CALL_RESPONSE_JSON = {
    "id": "chatcmpl-tool123",
    "object": "chat.completion",
    "created": 1741569952,
    "model": "gpt-4o",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "San Francisco"}',
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
}

OPENAI_EMBEDDING_RESPONSE_JSON = {
    "object": "list",
    "data": [{"object": "embedding", "index": 0, "embedding": [0.0023064255, -0.009327292, 0.015797086]}],
    "model": "text-embedding-3-small",
    "usage": {"prompt_tokens": 5, "total_tokens": 5},
}


# ===================================================================
# Enum tests
# ===================================================================


class TestProvider:
    """Provider enum values."""

    def test_all_providers_are_strings(self) -> None:
        for p in Provider:
            assert isinstance(p, str)
            assert isinstance(p.value, str)

    def test_known_providers(self) -> None:
        assert Provider.OPENAI == "openai"
        assert Provider.ANTHROPIC == "anthropic"
        assert Provider.AZURE == "azure"
        assert Provider.AWS_BEDROCK == "bedrock"
        assert Provider.VERTEX_AI == "vertex_ai"

    def test_provider_count(self) -> None:
        assert len(Provider) >= 15  # at least 15 providers defined


class TestRole:
    """Role enum values."""

    def test_standard_roles(self) -> None:
        assert Role.SYSTEM == "system"
        assert Role.USER == "user"
        assert Role.ASSISTANT == "assistant"
        assert Role.TOOL == "tool"

    def test_developer_role(self) -> None:
        assert Role.DEVELOPER == "developer"

    def test_deprecated_function_role(self) -> None:
        assert Role.FUNCTION == "function"


class TestFinishReason:
    """FinishReason enum values."""

    def test_values(self) -> None:
        assert FinishReason.STOP == "stop"
        assert FinishReason.LENGTH == "length"
        assert FinishReason.TOOL_CALLS == "tool_calls"
        assert FinishReason.CONTENT_FILTER == "content_filter"


class TestRoutingStrategy:
    """RoutingStrategy enum values."""

    def test_values(self) -> None:
        assert RoutingStrategy.ROUND_ROBIN == "round-robin"
        assert RoutingStrategy.COST_BASED == "cost-based"
        assert RoutingStrategy.LEAST_LATENCY == "latency-based"


class TestImageEnums:
    """Image-related enum values."""

    def test_sizes(self) -> None:
        assert ImageSize.S_1024 == "1024x1024"
        assert ImageSize.S_1792_1024 == "1792x1024"

    def test_quality(self) -> None:
        assert ImageQuality.HD == "hd"
        assert ImageQuality.STANDARD == "standard"

    def test_style(self) -> None:
        assert ImageStyle.VIVID == "vivid"
        assert ImageStyle.NATURAL == "natural"

    def test_response_format(self) -> None:
        assert ImageResponseFormat.URL == "url"
        assert ImageResponseFormat.B64_JSON == "b64_json"


class TestAudioEnums:
    """Audio-related enum values."""

    def test_voices(self) -> None:
        assert AudioVoice.ALLOY == "alloy"
        assert len(AudioVoice) == 6

    def test_formats(self) -> None:
        assert AudioResponseFormat.MP3 == "mp3"
        assert AudioResponseFormat.OPUS == "opus"


class TestMiscEnums:
    """Other enum types."""

    def test_cache_type(self) -> None:
        assert CacheType.REDIS == "redis"
        assert CacheType.NONE == "none"

    def test_embedding_encoding(self) -> None:
        assert EmbeddingEncodingFormat.FLOAT == "float"
        assert EmbeddingEncodingFormat.BASE64 == "base64"


# ===================================================================
# Message types
# ===================================================================


class TestMessage:
    """Message model."""

    def test_simple_text_message(self) -> None:
        msg = Message(role=Role.USER, content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.tool_calls is None

    def test_multimodal_message(self) -> None:
        msg = Message(
            role=Role.USER,
            content=[
                ContentPartText(text="What's in this image?"),
                ContentPartImage(image_url=ImageUrl(url="https://example.com/img.png", detail="high")),
            ],
        )
        assert isinstance(msg.content, list)
        assert len(msg.content) == 2
        assert msg.content[0].type == "text"
        assert msg.content[1].type == "image_url"

    def test_audio_content(self) -> None:
        msg = Message(
            role=Role.USER,
            content=[ContentPartInputAudio(input_audio=InputAudio(data="base64data", format="wav"))],
        )
        assert msg.content[0].type == "input_audio"  # type: ignore[union-attr,index]

    def test_assistant_with_tool_calls(self) -> None:
        msg = Message(
            role=Role.ASSISTANT,
            content=None,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    function=FunctionCall(name="get_weather", arguments='{"city": "NYC"}'),
                )
            ],
        )
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].function.name == "get_weather"

    def test_tool_response_message(self) -> None:
        msg = Message(role=Role.TOOL, content='{"temp": 72}', tool_call_id="call_1")
        assert msg.role == "tool"
        assert msg.tool_call_id == "call_1"

    def test_extra_fields_allowed(self) -> None:
        msg = Message(role=Role.USER, content="Hi", custom_field="test")
        assert msg.model_extra is not None
        assert msg.model_extra["custom_field"] == "test"


# ===================================================================
# Completion Request
# ===================================================================


class TestCompletionRequest:
    """CompletionRequest model."""

    def test_minimal_request(self) -> None:
        req = CompletionRequest(
            model="gpt-4o",
            messages=[Message(role=Role.USER, content="Hello")],
        )
        assert req.model == "gpt-4o"
        assert len(req.messages) == 1
        assert req.temperature is None
        assert req.stream is None

    def test_full_request(self) -> None:
        req = CompletionRequest(
            model="gpt-4o",
            messages=[
                Message(role=Role.SYSTEM, content="You are helpful."),
                Message(role=Role.USER, content="Hi"),
            ],
            temperature=0.7,
            top_p=0.9,
            n=1,
            stream=False,
            max_completion_tokens=1000,
            presence_penalty=0.1,
            frequency_penalty=0.2,
            seed=42,
            user="user-123",
        )
        assert req.temperature == 0.7
        assert req.max_completion_tokens == 1000
        assert req.seed == 42

    def test_with_tools(self) -> None:
        req = CompletionRequest(
            model="gpt-4o",
            messages=[Message(role=Role.USER, content="Weather?")],
            tools=[
                Tool(
                    function=Function(
                        name="get_weather",
                        description="Get weather",
                        parameters={"type": "object", "properties": {"city": {"type": "string"}}},
                    )
                )
            ],
            tool_choice="auto",
        )
        assert req.tools is not None
        assert len(req.tools) == 1
        assert req.tool_choice == "auto"

    def test_response_format_json_schema(self) -> None:
        req = CompletionRequest(
            model="gpt-4o",
            messages=[Message(role=Role.USER, content="Respond in JSON")],
            response_format=ResponseFormatJsonSchema(json_schema={"name": "response", "schema": {"type": "object"}}),
        )
        assert req.response_format is not None
        assert req.response_format.type == "json_schema"

    def test_response_format_json_object(self) -> None:
        req = CompletionRequest(
            model="gpt-4o",
            messages=[Message(role=Role.USER, content="JSON")],
            response_format=ResponseFormatJsonObject(),
        )
        assert req.response_format.type == "json_object"  # type: ignore[union-attr]

    def test_response_format_text(self) -> None:
        req = CompletionRequest(
            model="gpt-4o",
            messages=[Message(role=Role.USER, content="Hi")],
            response_format=ResponseFormatText(),
        )
        assert req.response_format.type == "text"  # type: ignore[union-attr]

    def test_stream_options(self) -> None:
        req = CompletionRequest(
            model="gpt-4o",
            messages=[Message(role=Role.USER, content="Hi")],
            stream=True,
            stream_options=StreamOptions(include_usage=True),
        )
        assert req.stream_options is not None
        assert req.stream_options.include_usage is True

    def test_extra_fields_passthrough(self) -> None:
        """Provider-specific fields should pass through."""
        req = CompletionRequest(
            model="gpt-4o",
            messages=[Message(role=Role.USER, content="Hi")],
            custom_provider_field="value",
        )
        data = req.model_dump()
        assert data["custom_provider_field"] == "value"

    def test_serialization_roundtrip(self) -> None:
        req = CompletionRequest(
            model="gpt-4o",
            messages=[
                Message(role=Role.USER, content="Hello"),
            ],
            temperature=0.5,
            max_completion_tokens=100,
        )
        json_str = req.model_dump_json()
        restored = CompletionRequest.model_validate_json(json_str)
        assert restored.model == req.model
        assert restored.temperature == req.temperature
        assert restored.messages[0].content == "Hello"


# ===================================================================
# Completion Response — deserialize real OpenAI JSON
# ===================================================================


class TestCompletionResponse:
    """CompletionResponse model."""

    def test_parse_real_openai_response(self) -> None:
        resp = CompletionResponse.model_validate(OPENAI_COMPLETION_RESPONSE_JSON)
        assert resp.id == "chatcmpl-B9MBs8CjcvOU2jLn4n570S5qMJKcT"
        assert resp.object == "chat.completion"
        assert resp.model == "gpt-4o-2024-08-06"
        assert len(resp.choices) == 1
        assert resp.choices[0].message.content == "Hello! How can I assist you today?"
        assert resp.choices[0].finish_reason == FinishReason.STOP
        assert resp.usage is not None
        assert resp.usage.prompt_tokens == 19
        assert resp.usage.completion_tokens == 10
        assert resp.usage.total_tokens == 29
        assert resp.service_tier == "default"

    def test_usage_details(self) -> None:
        resp = CompletionResponse.model_validate(OPENAI_COMPLETION_RESPONSE_JSON)
        assert resp.usage is not None
        assert resp.usage.prompt_tokens_details is not None
        assert resp.usage.prompt_tokens_details.cached_tokens == 0
        assert resp.usage.completion_tokens_details is not None
        assert resp.usage.completion_tokens_details.reasoning_tokens == 0

    def test_tool_call_response(self) -> None:
        resp = CompletionResponse.model_validate(OPENAI_TOOL_CALL_RESPONSE_JSON)
        choice = resp.choices[0]
        assert choice.finish_reason == FinishReason.TOOL_CALLS
        assert choice.message.tool_calls is not None
        assert len(choice.message.tool_calls) == 1
        tc = choice.message.tool_calls[0]
        assert tc.id == "call_abc123"
        assert tc.function.name == "get_weather"
        args = json.loads(tc.function.arguments)
        assert args["location"] == "San Francisco"

    def test_serialization_roundtrip(self) -> None:
        resp = CompletionResponse.model_validate(OPENAI_COMPLETION_RESPONSE_JSON)
        json_str = resp.model_dump_json()
        restored = CompletionResponse.model_validate_json(json_str)
        assert restored.id == resp.id
        assert restored.choices[0].message.content == resp.choices[0].message.content

    def test_auto_generated_id_and_created(self) -> None:
        resp = CompletionResponse(
            model="gpt-4o",
            choices=[Choice(message=ChoiceMessage(content="Hi"))],
        )
        assert resp.id.startswith("chatcmpl-")
        assert resp.created > 0
        assert abs(resp.created - int(time.time())) < 5

    def test_logprobs(self) -> None:
        resp_json = {
            "id": "chatcmpl-logprob",
            "object": "chat.completion",
            "created": 1741569952,
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hi"},
                    "finish_reason": "stop",
                    "logprobs": {
                        "content": [
                            {
                                "token": "Hi",
                                "logprob": -0.5,
                                "bytes": [72, 105],
                                "top_logprobs": [
                                    {"token": "Hi", "logprob": -0.5, "bytes": [72, 105]},
                                    {"token": "Hello", "logprob": -1.2, "bytes": None},
                                ],
                            }
                        ]
                    },
                }
            ],
        }
        resp = CompletionResponse.model_validate(resp_json)
        lp = resp.choices[0].logprobs
        assert lp is not None
        assert lp.content is not None
        assert len(lp.content) == 1
        assert lp.content[0].token == "Hi"
        assert len(lp.content[0].top_logprobs) == 2


# ===================================================================
# Streaming chunks
# ===================================================================


class TestCompletionResponseChunk:
    """CompletionResponseChunk model."""

    def test_parse_streaming_chunk(self) -> None:
        chunk = CompletionResponseChunk.model_validate(OPENAI_STREAMING_CHUNK_JSON)
        assert chunk.object == "chat.completion.chunk"
        assert len(chunk.choices) == 1
        assert chunk.choices[0].delta.content == "Hello"
        assert chunk.choices[0].delta.role == Role.ASSISTANT

    def test_empty_delta(self) -> None:
        chunk_json = {
            "id": "chatcmpl-abc",
            "object": "chat.completion.chunk",
            "created": 1741569952,
            "model": "gpt-4o",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        chunk = CompletionResponseChunk.model_validate(chunk_json)
        assert chunk.choices[0].delta.content is None
        assert chunk.choices[0].finish_reason == FinishReason.STOP

    def test_chunk_with_usage(self) -> None:
        chunk_json = {
            "id": "chatcmpl-abc",
            "object": "chat.completion.chunk",
            "created": 1741569952,
            "model": "gpt-4o",
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        chunk = CompletionResponseChunk.model_validate(chunk_json)
        assert chunk.usage is not None
        assert chunk.usage.total_tokens == 15

    def test_serialization_roundtrip(self) -> None:
        chunk = CompletionResponseChunk.model_validate(OPENAI_STREAMING_CHUNK_JSON)
        json_str = chunk.model_dump_json()
        restored = CompletionResponseChunk.model_validate_json(json_str)
        assert restored.id == chunk.id


# ===================================================================
# Embeddings
# ===================================================================


class TestEmbeddingRequest:
    """EmbeddingRequest model."""

    def test_string_input(self) -> None:
        req = EmbeddingRequest(model="text-embedding-3-small", input="Hello world")
        assert req.input == "Hello world"

    def test_list_input(self) -> None:
        req = EmbeddingRequest(model="text-embedding-3-small", input=["Hello", "World"])
        assert len(req.input) == 2

    def test_with_dimensions(self) -> None:
        req = EmbeddingRequest(model="text-embedding-3-small", input="Hello", dimensions=256)
        assert req.dimensions == 256

    def test_encoding_format(self) -> None:
        req = EmbeddingRequest(
            model="text-embedding-3-small",
            input="Hello",
            encoding_format=EmbeddingEncodingFormat.BASE64,
        )
        assert req.encoding_format == "base64"


class TestEmbeddingResponse:
    """EmbeddingResponse model."""

    def test_parse_real_response(self) -> None:
        resp = EmbeddingResponse.model_validate(OPENAI_EMBEDDING_RESPONSE_JSON)
        assert resp.object == "list"
        assert len(resp.data) == 1
        assert resp.data[0].index == 0
        assert isinstance(resp.data[0].embedding, list)
        assert len(resp.data[0].embedding) == 3
        assert resp.usage.prompt_tokens == 5

    def test_serialization_roundtrip(self) -> None:
        resp = EmbeddingResponse.model_validate(OPENAI_EMBEDDING_RESPONSE_JSON)
        json_str = resp.model_dump_json()
        restored = EmbeddingResponse.model_validate_json(json_str)
        assert restored.data[0].embedding == resp.data[0].embedding


# ===================================================================
# Images
# ===================================================================


class TestImageRequest:
    """ImageRequest model."""

    def test_minimal(self) -> None:
        req = ImageRequest(prompt="A sunset over mountains")
        assert req.model == "dall-e-3"
        assert req.n == 1

    def test_full(self) -> None:
        req = ImageRequest(
            model="dall-e-3",
            prompt="A cat",
            n=2,
            size=ImageSize.S_1024,
            quality=ImageQuality.HD,
            style=ImageStyle.NATURAL,
            response_format=ImageResponseFormat.B64_JSON,
        )
        assert req.size == "1024x1024"
        assert req.quality == "hd"


class TestImageResponse:
    """ImageResponse model."""

    def test_url_response(self) -> None:
        resp = ImageResponse(data=[ImageData(url="https://example.com/img.png", revised_prompt="A beautiful sunset")])
        assert len(resp.data) == 1
        assert resp.data[0].url is not None

    def test_b64_response(self) -> None:
        resp = ImageResponse(data=[ImageData(b64_json="base64data==")])
        assert resp.data[0].b64_json == "base64data=="


# ===================================================================
# Audio
# ===================================================================


class TestAudioSpeechRequest:
    """AudioSpeechRequest model."""

    def test_defaults(self) -> None:
        req = AudioSpeechRequest(input="Hello world")
        assert req.model == "tts-1"
        assert req.voice == AudioVoice.ALLOY

    def test_all_fields(self) -> None:
        req = AudioSpeechRequest(
            model="tts-1-hd",
            input="Hello",
            voice=AudioVoice.NOVA,
            response_format=AudioResponseFormat.OPUS,
            speed=1.5,
        )
        assert req.speed == 1.5


class TestAudioTranscription:
    """AudioTranscription models."""

    def test_request_defaults(self) -> None:
        req = AudioTranscriptionRequest()
        assert req.model == "whisper-1"

    def test_response(self) -> None:
        resp = AudioTranscriptionResponse(text="Hello, this is a transcription.")
        assert resp.text == "Hello, this is a transcription."


# ===================================================================
# Rerank
# ===================================================================


class TestRerankRequest:
    """RerankRequest model."""

    def test_string_documents(self) -> None:
        req = RerankRequest(
            model="rerank-english-v3.0",
            query="What is Python?",
            documents=["Python is a language", "Java is a language"],
            top_n=2,
        )
        assert len(req.documents) == 2

    def test_dict_documents(self) -> None:
        req = RerankRequest(
            model="rerank-english-v3.0",
            query="What is Python?",
            documents=[{"text": "Python is a language"}],
        )
        assert isinstance(req.documents[0], dict)


class TestRerankResponse:
    """RerankResponse model."""

    def test_response(self) -> None:
        resp = RerankResponse(
            model="rerank-english-v3.0",
            results=[
                RerankResult(index=0, relevance_score=0.99, document={"text": "Python is a language"}),
                RerankResult(index=1, relevance_score=0.45),
            ],
        )
        assert len(resp.results) == 2
        assert resp.results[0].relevance_score == 0.99
        assert resp.results[1].document is None
        assert resp.id.startswith("rerank-")


# ===================================================================
# Model Card / Model List
# ===================================================================


class TestModelCard:
    """ModelCard model."""

    def test_model_card(self) -> None:
        card = ModelCard(
            id="gpt-4o",
            owned_by="openai",
            max_input_tokens=128000,
            max_output_tokens=16384,
            input_cost_per_token=2.5e-6,
            output_cost_per_token=10.0e-6,
            supports_vision=True,
            supports_function_calling=True,
            context_window=128000,
        )
        assert card.id == "gpt-4o"
        assert card.object == "model"
        assert card.supports_vision is True


class TestModelListResponse:
    """ModelListResponse model."""

    def test_model_list(self) -> None:
        resp = ModelListResponse(
            data=[
                ModelCard(id="gpt-4o"),
                ModelCard(id="gpt-4o-mini"),
            ]
        )
        assert resp.object == "list"
        assert len(resp.data) == 2


# ===================================================================
# Building-block types
# ===================================================================


class TestToolCall:
    """ToolCall model."""

    def test_auto_id(self) -> None:
        tc = ToolCall(function=FunctionCall(name="test", arguments="{}"))
        assert tc.id.startswith("call_")
        assert tc.type == "function"

    def test_explicit_id(self) -> None:
        tc = ToolCall(id="call_custom", function=FunctionCall(name="test", arguments="{}"))
        assert tc.id == "call_custom"


class TestTool:
    """Tool model."""

    def test_function_tool(self) -> None:
        tool = Tool(
            function=Function(
                name="get_weather",
                description="Get weather for a city",
                parameters={"type": "object", "properties": {"city": {"type": "string"}}},
            )
        )
        assert tool.type == "function"
        assert tool.function.name == "get_weather"
        assert tool.function.strict is None


class TestUsage:
    """Usage model."""

    def test_defaults(self) -> None:
        usage = Usage()
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_with_details(self) -> None:
        usage = Usage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            prompt_tokens_details=PromptTokensDetails(cached_tokens=20),
            completion_tokens_details=CompletionTokensDetails(reasoning_tokens=10),
        )
        assert usage.prompt_tokens_details is not None
        assert usage.prompt_tokens_details.cached_tokens == 20
        assert usage.completion_tokens_details is not None
        assert usage.completion_tokens_details.reasoning_tokens == 10


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    """Edge cases and data integrity checks."""

    def test_completion_response_extra_fields(self) -> None:
        """Unknown fields should be preserved (extra=allow)."""
        resp_json = {
            **OPENAI_COMPLETION_RESPONSE_JSON,
            "custom_field": "custom_value",
        }
        resp = CompletionResponse.model_validate(resp_json)
        assert resp.model_extra is not None
        assert resp.model_extra["custom_field"] == "custom_value"

    def test_completion_request_from_json_string(self) -> None:
        """Parse a request from a raw JSON string."""
        raw = json.dumps(
            {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "Hi"}],
                "temperature": 0.5,
            }
        )
        req = CompletionRequest.model_validate_json(raw)
        assert req.model == "gpt-4o"
        assert req.temperature == 0.5

    def test_none_content_message(self) -> None:
        """Assistant messages with tool calls may have null content."""
        msg = Message(role=Role.ASSISTANT, content=None)
        assert msg.content is None

    def test_empty_choices(self) -> None:
        """A response with empty choices is valid (e.g., final streaming chunk)."""
        resp = CompletionResponse(model="gpt-4o", choices=[])
        assert len(resp.choices) == 0

    def test_multiple_choices(self) -> None:
        """Response with n>1 generates multiple choices."""
        resp = CompletionResponse(
            model="gpt-4o",
            choices=[
                Choice(index=0, message=ChoiceMessage(content="A"), finish_reason=FinishReason.STOP),
                Choice(index=1, message=ChoiceMessage(content="B"), finish_reason=FinishReason.STOP),
            ],
        )
        assert len(resp.choices) == 2
        assert resp.choices[1].index == 1

    def test_stop_as_string_or_list(self) -> None:
        """stop can be a single string or a list."""
        req1 = CompletionRequest(
            model="gpt-4o",
            messages=[Message(role=Role.USER, content="Hi")],
            stop="END",
        )
        assert req1.stop == "END"

        req2 = CompletionRequest(
            model="gpt-4o",
            messages=[Message(role=Role.USER, content="Hi")],
            stop=["END", "STOP"],
        )
        assert isinstance(req2.stop, list)
        assert len(req2.stop) == 2
