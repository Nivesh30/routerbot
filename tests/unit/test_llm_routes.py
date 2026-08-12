"""Unit tests for Stage 3.2 LLM API routes.

Tests cover:
- POST /v1/chat/completions (sync + streaming)
- POST /v1/completions (legacy)
- POST /v1/embeddings
- POST /v1/images/generations
- POST /v1/audio/transcriptions
- POST /v1/audio/speech
- POST /v1/rerank
- POST /v1/batches + GET /v1/batches + GET /v1/batches/{id} + POST /v1/batches/{id}/cancel

All provider calls are mocked to avoid real API calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from routerbot.core.config_models import ModelEntry, ModelParams, RouterBotConfig
from routerbot.core.enums import FinishReason, Role
from routerbot.core.types import (
    Choice,
    ChoiceMessage,
    CompletionResponse,
    CompletionResponseChunk,
    EmbeddingData,
    EmbeddingResponse,
    EmbeddingUsage,
    ImageData,
    ImageResponse,
    RerankResponse,
    RerankResult,
    Usage,
)
from routerbot.proxy.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config() -> RouterBotConfig:
    """Build a minimal RouterBotConfig with test models."""
    config = RouterBotConfig()
    config.model_list = [
        ModelEntry(
            model_name="gpt-4o",
            provider_params=ModelParams(model="openai/gpt-4o", api_key="test-key"),
        ),
        ModelEntry(
            model_name="text-embedding-3-small",
            provider_params=ModelParams(model="openai/text-embedding-3-small", api_key="test-key"),
        ),
        ModelEntry(
            model_name="dall-e-3",
            provider_params=ModelParams(model="openai/dall-e-3", api_key="test-key"),
        ),
        ModelEntry(
            model_name="whisper-1",
            provider_params=ModelParams(model="openai/whisper-1", api_key="test-key"),
        ),
        ModelEntry(
            model_name="tts-1",
            provider_params=ModelParams(model="openai/tts-1", api_key="test-key"),
        ),
        ModelEntry(
            model_name="rerank-english-v3.0",
            provider_params=ModelParams(model="cohere/rerank-english-v3.0", api_key="test-key"),
        ),
    ]
    return config


def _make_completion_response() -> CompletionResponse:
    return CompletionResponse(
        model="gpt-4o",
        choices=[
            Choice(
                index=0,
                message=ChoiceMessage(role=Role.ASSISTANT, content="Hello!"),
                finish_reason=FinishReason.STOP,
            )
        ],
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _make_embedding_response() -> EmbeddingResponse:
    return EmbeddingResponse(
        model="text-embedding-3-small",
        data=[EmbeddingData(index=0, embedding=[0.1, 0.2, 0.3])],
        usage=EmbeddingUsage(prompt_tokens=5, total_tokens=5),
    )


def _make_image_response() -> ImageResponse:
    return ImageResponse(data=[ImageData(url="https://example.com/image.png", revised_prompt="a cat")])


def _make_rerank_response() -> RerankResponse:
    return RerankResponse(
        model="rerank-english-v3.0",
        results=[RerankResult(index=0, relevance_score=0.95)],
    )


async def _fake_stream() -> AsyncIterator[CompletionResponseChunk]:
    """Yield two fake SSE chunks."""
    from routerbot.core.enums import FinishReason, Role
    from routerbot.core.types import ChunkChoice, DeltaMessage

    yield CompletionResponseChunk(
        model="gpt-4o",
        choices=[
            ChunkChoice(
                index=0,
                delta=DeltaMessage(role=Role.ASSISTANT, content="Hello"),
            )
        ],
    )
    yield CompletionResponseChunk(
        model="gpt-4o",
        choices=[
            ChunkChoice(
                index=0,
                delta=DeltaMessage(content="!"),
                finish_reason=FinishReason.STOP,
            )
        ],
    )


@pytest_asyncio.fixture()
async def client() -> AsyncIterator[AsyncClient]:
    """Async test client with a mock provider."""
    config = _make_config()
    test_app = create_app(config=config)
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture()
async def batch_client() -> AsyncIterator[AsyncClient]:
    """Async test client with batch processing enabled and a mock provider.

    Real batch execution now calls providers for real (see
    ``proxy/completion_helper.handle_batch_request``), so the provider
    registry is patched for the lifetime of the client, same as the other
    per-test patches in this file. ``state.batch_manager`` is only created
    during the app's startup hook, and ``ASGITransport`` doesn't fire ASGI
    lifespan events, so ``_startup`` is invoked directly (same pattern as
    ``test_middleware.py::TestRouterIntegration``).
    """
    from routerbot.proxy.app import _shutdown, _startup

    config = _make_config()
    config.batch = {"enabled": True}
    test_app = create_app(config=config)
    state = test_app.state.routerbot
    mock_cls = _mock_provider_cls(chat_response=_make_completion_response())
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        await _startup(test_app, state, config)
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
            yield ac
        await _shutdown(test_app, state)


# ---------------------------------------------------------------------------
# Helper: mock provider class
# ---------------------------------------------------------------------------


def _mock_provider_cls(
    chat_response: CompletionResponse | None = None,
    embed_response: EmbeddingResponse | None = None,
    image_response: ImageResponse | None = None,
    rerank_response: RerankResponse | None = None,
    audio_bytes: bytes = b"fake-audio",
) -> type:
    """Return a mock provider class that returns preset responses."""

    class MockProvider:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def chat_completion(self, request: object) -> CompletionResponse:
            return chat_response or _make_completion_response()

        def chat_completion_stream(self, request: object) -> AsyncIterator[CompletionResponseChunk]:
            return _fake_stream()

        async def embedding(self, request: object) -> EmbeddingResponse:
            return embed_response or _make_embedding_response()

        async def image_generation(self, request: object) -> ImageResponse:
            return image_response or _make_image_response()

        async def rerank(self, request: object) -> RerankResponse:
            return rerank_response or _make_rerank_response()

        async def audio_speech(self, request: object) -> bytes:
            return audio_bytes

        async def audio_transcription(self, request: object, **kwargs: object) -> object:
            from routerbot.core.types import AudioTranscriptionResponse

            return AudioTranscriptionResponse(text="Hello world")

    return MockProvider


# ---------------------------------------------------------------------------
# Chat Completions — Sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completions_returns_200(client: AsyncClient) -> None:
    """POST /v1/chat/completions should return 200 for a known model."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_chat_completions_response_schema(client: AsyncClient) -> None:
    """Chat completions response should match OpenAI format."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
    data = resp.json()
    assert "id" in data
    assert data["object"] == "chat.completion"
    assert isinstance(data["choices"], list)
    assert len(data["choices"]) > 0
    assert "message" in data["choices"][0]


@pytest.mark.asyncio
async def test_chat_completions_includes_request_id_header(client: AsyncClient) -> None:
    """Chat completions should include X-Request-ID header."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert "x-request-id" in resp.headers


@pytest.mark.asyncio
async def test_chat_completions_unknown_model_returns_404(client: AsyncClient) -> None:
    """POST /v1/chat/completions with unknown model should return 404."""
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "nonexistent-model", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 404
    assert "error" in resp.json()


@pytest.mark.asyncio
async def test_chat_completions_propagates_request_id(client: AsyncClient) -> None:
    """X-Request-ID header from request should be echoed in response."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Request-ID": "test-req-abc"},
        )
    assert resp.headers["x-request-id"] == "test-req-abc"


# ---------------------------------------------------------------------------
# Chat Completions — Streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completions_streaming_content_type(client: AsyncClient) -> None:
    """Streaming chat completions should return text/event-stream content type."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_chat_completions_streaming_sse_format(client: AsyncClient) -> None:
    """Streaming response should be in SSE format (data: {...}\\n\\n)."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
    content = resp.text
    # Each data line must start with "data: "
    data_lines = [line for line in content.split("\n") if line.startswith("data:")]
    assert len(data_lines) >= 1
    # Last data line must be [DONE]
    assert any(line.strip() == "data: [DONE]" for line in data_lines)


@pytest.mark.asyncio
async def test_chat_completions_streaming_includes_request_id(client: AsyncClient) -> None:
    """Streaming response should include X-Request-ID header."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
    assert "x-request-id" in resp.headers


# ---------------------------------------------------------------------------
# Legacy /v1/completions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_completions_returns_200(client: AsyncClient) -> None:
    """POST /v1/completions (legacy) should return 200."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embeddings_returns_200(client: AsyncClient) -> None:
    """POST /v1/embeddings should return 200."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/embeddings",
            json={"model": "text-embedding-3-small", "input": "Hello world"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_embeddings_response_schema(client: AsyncClient) -> None:
    """Embeddings response should match OpenAI format."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/embeddings",
            json={"model": "text-embedding-3-small", "input": "Hello"},
        )
    data = resp.json()
    assert data["object"] == "list"
    assert isinstance(data["data"], list)
    assert len(data["data"]) > 0
    assert "embedding" in data["data"][0]


@pytest.mark.asyncio
async def test_embeddings_unknown_model_returns_404(client: AsyncClient) -> None:
    """POST /v1/embeddings with unknown model should return 404."""
    resp = await client.post(
        "/v1/embeddings",
        json={"model": "nonexistent-embed", "input": "Hello"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_embeddings_includes_request_id_header(client: AsyncClient) -> None:
    """Embeddings response should include X-Request-ID header."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/embeddings",
            json={"model": "text-embedding-3-small", "input": "Hi"},
        )
    assert "x-request-id" in resp.headers


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_images_generations_returns_200(client: AsyncClient) -> None:
    """POST /v1/images/generations should return 200."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/images/generations",
            json={"model": "dall-e-3", "prompt": "a cat on a mat"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_images_response_schema(client: AsyncClient) -> None:
    """Image generation response should include 'data' list."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/images/generations",
            json={"model": "dall-e-3", "prompt": "a cat"},
        )
    data = resp.json()
    assert "data" in data
    assert isinstance(data["data"], list)


@pytest.mark.asyncio
async def test_images_unknown_model_returns_404(client: AsyncClient) -> None:
    """POST /v1/images/generations with unknown model should return 404."""
    resp = await client.post(
        "/v1/images/generations",
        json={"model": "nonexistent-image-model", "prompt": "a cat"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audio_speech_returns_200(client: AsyncClient) -> None:
    """POST /v1/audio/speech should return 200 with audio bytes."""
    mock_cls = _mock_provider_cls(audio_bytes=b"\xff\xfb\x90\x00fake-audio")
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/audio/speech",
            json={"model": "tts-1", "input": "Hello there", "voice": "alloy"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_audio_speech_unknown_model_returns_404(client: AsyncClient) -> None:
    """POST /v1/audio/speech with unknown model should return 404."""
    resp = await client.post(
        "/v1/audio/speech",
        json={"model": "nonexistent-tts", "input": "Hello", "voice": "alloy"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_audio_transcription_unknown_model_returns_404(client: AsyncClient) -> None:
    """POST /v1/audio/transcriptions with unknown model should return 404."""
    import io

    resp = await client.post(
        "/v1/audio/transcriptions",
        data={"model": "nonexistent-whisper"},
        files={"file": ("test.mp3", io.BytesIO(b"fake"), "audio/mpeg")},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Rerank
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rerank_returns_200(client: AsyncClient) -> None:
    """POST /v1/rerank should return 200."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/rerank",
            json={
                "model": "rerank-english-v3.0",
                "query": "What is AI?",
                "documents": ["doc1", "doc2"],
            },
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rerank_response_schema(client: AsyncClient) -> None:
    """Rerank response should have 'results' list."""
    mock_cls = _mock_provider_cls()
    with patch("routerbot.providers.registry.get_provider_class", return_value=mock_cls):
        resp = await client.post(
            "/v1/rerank",
            json={
                "model": "rerank-english-v3.0",
                "query": "AI",
                "documents": ["doc1"],
            },
        )
    data = resp.json()
    assert "results" in data


@pytest.mark.asyncio
async def test_rerank_unknown_model_returns_404(client: AsyncClient) -> None:
    """POST /v1/rerank with unknown model should return 404."""
    resp = await client.post(
        "/v1/rerank",
        json={"model": "nonexistent-rerank", "query": "q", "documents": ["d"]},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

_BATCH_REQUEST_BODY = {
    "requests": [
        {
            "custom_id": "req-1",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        }
    ]
}


@pytest.mark.asyncio
async def test_batches_503_when_not_enabled(client: AsyncClient) -> None:
    """Batch routes should 503 when batch.enabled is not set (the `client` fixture)."""
    resp = await client.post("/v1/batches", json=_BATCH_REQUEST_BODY)
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_create_batch_returns_200(batch_client: AsyncClient) -> None:
    """POST /v1/batches should return 200, create a batch, and run it for real."""
    resp = await batch_client.post("/v1/batches", json=_BATCH_REQUEST_BODY)
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "batch"
    assert data["id"].startswith("batch_")
    assert data["request_counts"]["total"] == 1
    assert data["status"] in ("validating", "in_progress")

    # Execution happens in a background task — poll until it's done.
    import asyncio

    for _ in range(50):
        poll = (await batch_client.get(f"/v1/batches/{data['id']}")).json()
        if poll["status"] == "completed":
            break
        await asyncio.sleep(0.05)
    else:
        pytest.fail("Batch did not complete in time")

    assert poll["results"] and poll["results"][0]["custom_id"] == "req-1"
    assert poll["results"][0]["status_code"] == 200


@pytest.mark.asyncio
async def test_create_batch_empty_requests_returns_400(batch_client: AsyncClient) -> None:
    """POST /v1/batches with no requests should return a 400 validation error."""
    resp = await batch_client.post("/v1/batches", json={"requests": []})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_batches_returns_200(batch_client: AsyncClient) -> None:
    """GET /v1/batches should return 200 with list object."""
    await batch_client.post("/v1/batches", json=_BATCH_REQUEST_BODY)
    resp = await batch_client.get("/v1/batches")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert isinstance(data["data"], list)
    assert len(data["data"]) == 1


@pytest.mark.asyncio
async def test_get_batch_returns_200_for_known_batch(batch_client: AsyncClient) -> None:
    """GET /v1/batches/{id} should return 200 for a created batch."""
    create_resp = await batch_client.post("/v1/batches", json=_BATCH_REQUEST_BODY)
    batch_id = create_resp.json()["id"]

    get_resp = await batch_client.get(f"/v1/batches/{batch_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == batch_id


@pytest.mark.asyncio
async def test_get_batch_returns_404_for_unknown(batch_client: AsyncClient) -> None:
    """GET /v1/batches/{id} should return 404 for unknown batch."""
    resp = await batch_client.get("/v1/batches/nonexistent-batch")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_batch_returns_200(batch_client: AsyncClient) -> None:
    """POST /v1/batches/{id}/cancel should return 200 and mark as cancelled.

    Execution is stubbed out here so the batch stays cancellable (with the
    real handler, the mock provider resolves fast enough that the batch is
    typically already "completed" by the time cancel is called).
    """
    from routerbot.core.batch.batch_manager import BatchManager

    with patch.object(BatchManager, "execute_batch", new=AsyncMock()):
        create_resp = await batch_client.post("/v1/batches", json=_BATCH_REQUEST_BODY)
        batch_id = create_resp.json()["id"]

        cancel_resp = await batch_client.post(f"/v1/batches/{batch_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_unknown_batch_returns_404(batch_client: AsyncClient) -> None:
    """POST /v1/batches/{id}/cancel should return 404 for unknown batch."""
    resp = await batch_client.post("/v1/batches/unknown-batch/cancel")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Helper: Provider dispatch lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_dispatch_env_key_resolution(client: AsyncClient) -> None:
    """API keys referencing os.environ/ should be resolved from environment."""
    import os

    os.environ["TEST_API_KEY"] = "resolved-key"

    config = RouterBotConfig()
    config.model_list = [
        ModelEntry(
            model_name="gpt-env",
            provider_params=ModelParams(model="openai/gpt-4o", api_key="os.environ/TEST_API_KEY"),
        )
    ]

    test_app = create_app(config=config)

    class CapturingProvider:
        captured_key: str | None = None

        def __init__(self, **kwargs: object) -> None:
            CapturingProvider.captured_key = str(kwargs.get("api_key"))

        async def chat_completion(self, req: object) -> CompletionResponse:
            return _make_completion_response()

    with patch("routerbot.providers.registry.get_provider_class", return_value=CapturingProvider):
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
            await ac.post(
                "/v1/chat/completions",
                json={"model": "gpt-env", "messages": [{"role": "user", "content": "hi"}]},
            )

    assert CapturingProvider.captured_key == "resolved-key"
    del os.environ["TEST_API_KEY"]
