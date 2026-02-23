"""Cohere provider constants."""

from __future__ import annotations

COHERE_BASE_URL = "https://api.cohere.com/v2"

COHERE_MODELS: frozenset[str] = frozenset(
    {
        "command-r-plus-08-2024",
        "command-r-plus",
        "command-r-08-2024",
        "command-r",
        "command",
        "command-light",
        "command-nightly",
        "command-r7b-12-2024",
        "c4ai-aya-expanse-8b",
        "c4ai-aya-expanse-32b",
    }
)

EMBEDDING_MODELS: frozenset[str] = frozenset(
    {
        "embed-english-v3.0",
        "embed-multilingual-v3.0",
        "embed-english-light-v3.0",
        "embed-multilingual-light-v3.0",
        "embed-english-v2.0",
    }
)

FINISH_REASON_MAP: dict[str, str] = {
    "COMPLETE": "stop",
    "STOP_SEQUENCE": "stop",
    "MAX_TOKENS": "length",
    "ERROR": "stop",
    "ERROR_TOXIC": "content_filter",
    "ERROR_LIMIT": "length",
    "USER_CANCEL": "stop",
    "TOOL_CALL": "tool_calls",
}
