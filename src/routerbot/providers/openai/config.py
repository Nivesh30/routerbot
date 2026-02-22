"""OpenAI-specific configuration constants and helpers."""

from __future__ import annotations

# Default API base URL
OPENAI_API_BASE = "https://api.openai.com/v1"

# Supported models (non-exhaustive)
CHAT_MODELS = frozenset(
    {
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4o-2024-11-20",
        "gpt-4o-2024-08-06",
        "gpt-4o-2024-05-13",
        "gpt-4o-mini-2024-07-18",
        "gpt-4-turbo",
        "gpt-4-turbo-2024-04-09",
        "gpt-4-turbo-preview",
        "gpt-4-0125-preview",
        "gpt-4-1106-preview",
        "gpt-4",
        "gpt-4-0613",
        "gpt-3.5-turbo",
        "gpt-3.5-turbo-0125",
        "gpt-3.5-turbo-1106",
        "o1",
        "o1-2024-12-17",
        "o1-mini",
        "o1-mini-2024-09-12",
        "o1-preview",
        "o1-preview-2024-09-12",
        "o3",
        "o3-mini",
        "o4-mini",
        "o4-mini-2025-04-16",
        "chatgpt-4o-latest",
    }
)

EMBEDDING_MODELS = frozenset(
    {
        "text-embedding-3-small",
        "text-embedding-3-large",
        "text-embedding-ada-002",
    }
)

IMAGE_MODELS = frozenset(
    {
        "dall-e-3",
        "dall-e-2",
        "gpt-image-1",
    }
)

TTS_MODELS = frozenset(
    {
        "tts-1",
        "tts-1-hd",
        "tts-1-1106",
        "tts-1-hd-1106",
    }
)

STT_MODELS = frozenset(
    {
        "whisper-1",
    }
)

# Models that do NOT support system messages in the usual way
O_SERIES_MODELS = frozenset(
    {
        "o1",
        "o1-mini",
        "o1-preview",
        "o3",
        "o3-mini",
        "o4-mini",
    }
)

# Models that support structured outputs / JSON mode
JSON_MODE_MODELS = frozenset(
    {
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4-turbo-preview",
        "gpt-4-0125-preview",
        "gpt-3.5-turbo-0125",
        "gpt-3.5-turbo-1106",
    }
)
