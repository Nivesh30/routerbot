"""Audio routes — POST /v1/audio/transcriptions, POST /v1/audio/speech.

Implements the OpenAI-compatible audio API.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from routerbot.core.exceptions import BadRequestError, ModelNotFoundError
from routerbot.core.types import AudioSpeechRequest, AudioTranscriptionRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Audio"])


async def _get_provider_for_model(request: Request, model_name: str) -> Any:
    """Resolve a provider for the given model name."""
    state = getattr(request.app.state, "routerbot", None)
    config = state.config if state else None

    if config is None:
        raise ModelNotFoundError(model_name)

    entry = next((m for m in config.model_list if m.model_name == model_name), None)
    if entry is None:
        raise ModelNotFoundError(model_name)

    provider_model = entry.provider_params.model
    if "/" not in provider_model:
        raise BadRequestError(f"Invalid provider/model format: {provider_model!r}")

    provider_name, _ = provider_model.split("/", 1)

    from routerbot.providers.registry import get_provider_class

    provider_cls = get_provider_class(provider_name)

    api_key = entry.provider_params.api_key
    if api_key and api_key.startswith("os.environ/"):
        import os

        env_var = api_key.removeprefix("os.environ/")
        api_key = os.environ.get(env_var)

    return provider_cls(
        api_key=api_key,
        api_base=entry.provider_params.api_base,
        custom_headers=entry.provider_params.extra_headers,
    )


@router.post("/audio/transcriptions", summary="Transcribe audio to text")
async def audio_transcriptions(
    raw_request: Request,
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),
    language: str | None = Form(None),
    prompt: str | None = Form(None),
    response_format: str | None = Form(None),
    temperature: float | None = Form(None),
) -> JSONResponse:
    """Transcribe audio to text using a speech-to-text model.

    Accepts multipart/form-data with an audio file upload.
    """
    request_id = getattr(raw_request.state, "request_id", None) or "unknown"

    provider = await _get_provider_for_model(raw_request, model)

    transcription_request = AudioTranscriptionRequest(
        model=model,
        language=language,
        prompt=prompt,
        response_format=response_format,
        temperature=temperature,
    )

    response = await provider.audio_transcription(transcription_request, file=file)

    return JSONResponse(
        content=response.model_dump(),
        headers={"X-Request-ID": request_id},
    )


@router.post("/audio/speech", summary="Generate speech from text (TTS)")
async def audio_speech(
    body: AudioSpeechRequest,
    raw_request: Request,
) -> Response:
    """Generate speech audio from a text input.

    Returns the audio as binary data with the appropriate content type.
    """
    request_id = getattr(raw_request.state, "request_id", None) or "unknown"

    provider = await _get_provider_for_model(raw_request, body.model)

    audio_bytes: bytes = await provider.audio_speech(body)

    # Determine content type from format
    fmt = body.response_format
    content_type_map = {
        "mp3": "audio/mpeg",
        "opus": "audio/ogg",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }
    content_type = content_type_map.get(str(fmt), "audio/mpeg") if fmt else "audio/mpeg"

    return Response(
        content=audio_bytes,
        media_type=content_type,
        headers={"X-Request-ID": request_id},
    )
