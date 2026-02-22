"""Request/response transformation for the OpenAI provider.

Since RouterBot's internal format IS the OpenAI format, most transforms
are identity operations. This module handles edge cases like o-series
model quirks and ensures clean serialization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from routerbot.providers.openai.config import O_SERIES_MODELS

if TYPE_CHECKING:
    from routerbot.core.types import CompletionRequest


def prepare_chat_payload(request: CompletionRequest) -> dict[str, Any]:
    """Convert a :class:`CompletionRequest` to the dict sent to the OpenAI API.

    Handles edge cases:
    - o-series models: convert ``system`` messages to ``developer`` role
    - Strips ``None`` values for cleaner payloads
    """
    payload = request.model_dump(exclude_none=True)
    model = payload.get("model", "")

    # o-series models (o1, o3, etc.) use 'developer' instead of 'system'
    base_model = _base_model_name(model)
    if base_model in O_SERIES_MODELS:
        payload = _convert_system_to_developer(payload)
        # o-series models don't support temperature/top_p
        payload.pop("temperature", None)
        payload.pop("top_p", None)
        # max_tokens → max_completion_tokens for o-series
        if "max_tokens" in payload and "max_completion_tokens" not in payload:
            payload["max_completion_tokens"] = payload.pop("max_tokens")

    return payload


def _base_model_name(model: str) -> str:
    """Extract base model name (strip date suffixes).

    ``"o1-2024-12-17"`` → ``"o1"``
    ``"gpt-4o-2024-11-20"`` → ``"gpt-4o"``
    ``"gpt-4o"`` → ``"gpt-4o"``
    """
    # Common patterns: model-YYYY-MM-DD
    parts = model.split("-")
    # Check if last 3 parts are a date (YYYY, MM, DD)
    if len(parts) >= 4 and len(parts[-3]) == 4 and parts[-3].isdigit():
        return "-".join(parts[:-3])
    return model


def _convert_system_to_developer(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert system messages to developer role for o-series models."""
    messages = payload.get("messages", [])
    converted = []
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            converted.append({**msg, "role": "developer"})
        else:
            converted.append(msg)
    payload["messages"] = converted
    return payload
