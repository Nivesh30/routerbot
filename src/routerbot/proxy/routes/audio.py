"""Audio routes — POST /v1/audio/transcriptions, POST /v1/audio/speech.

Implements the OpenAI-compatible audio API. Requests are dispatched
through the :class:`~routerbot.router.router.Router`
(``proxy/completion_helper.get_router``).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from routerbot.core.types import AudioSpeechRequest, AudioTranscriptionRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Audio"])


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
    from routerbot.proxy.completion_helper import get_router

    request_id = getattr(raw_request.state, "request_id", None) or "unknown"
    state = getattr(raw_request.app.state, "routerbot", None)

    transcription_request = AudioTranscriptionRequest(
        model=model,
        language=language,
        prompt=prompt,
        response_format=response_format,
        temperature=temperature,
    )

    llm_router = get_router(state)
    response = await llm_router.audio_transcription(transcription_request, file, request_id=request_id)

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
    from routerbot.proxy.completion_helper import get_router

    request_id = getattr(raw_request.state, "request_id", None) or "unknown"
    state = getattr(raw_request.app.state, "routerbot", None)

    llm_router = get_router(state)
    audio_bytes: bytes = await llm_router.audio_speech(body, request_id=request_id)

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
