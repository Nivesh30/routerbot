"""Shared transformation utilities for provider adapters.

Functions in this module help convert between OpenAI-compatible formats
and the various native provider formats.  They are deliberately
stateless and operate purely on dictionaries / Pydantic models.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from routerbot.core.enums import FinishReason, Role
from routerbot.core.types import (
    Choice,
    ChoiceMessage,
    CompletionResponse,
    Message,
    Usage,
)

# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------


def normalize_role(role: str) -> str:
    """Map arbitrary role strings to one of the OpenAI-standard roles.

    Unknown roles are returned as-is so that provider-specific roles
    (e.g. ``"ipython"``) are preserved.
    """
    mapping: dict[str, str] = {
        "human": Role.USER,
        "ai": Role.ASSISTANT,
        "bot": Role.ASSISTANT,
        "model": Role.ASSISTANT,
        "developer": Role.DEVELOPER,
    }
    return mapping.get(role.lower(), role.lower())


def normalize_finish_reason(reason: str | None) -> str | None:
    """Map provider-specific stop reasons to OpenAI ``finish_reason`` values."""
    if reason is None:
        return None

    mapping: dict[str, str] = {
        # Anthropic
        "end_turn": FinishReason.STOP,
        "max_tokens": FinishReason.LENGTH,
        "tool_use": FinishReason.TOOL_CALLS,
        # Google
        "STOP": FinishReason.STOP,
        "MAX_TOKENS": FinishReason.LENGTH,
        "SAFETY": FinishReason.CONTENT_FILTER,
        "RECITATION": FinishReason.CONTENT_FILTER,
        # Cohere
        "COMPLETE": FinishReason.STOP,
        "MAX_TOKENS_REACHED": FinishReason.LENGTH,
    }
    return mapping.get(reason, reason)


# ---------------------------------------------------------------------------
# Response construction helpers
# ---------------------------------------------------------------------------


def build_completion_response(
    *,
    model: str,
    content: str,
    role: str = Role.ASSISTANT,
    finish_reason: str = FinishReason.STOP,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    system_fingerprint: str | None = None,
    extra_choice_fields: dict[str, Any] | None = None,
) -> CompletionResponse:
    """Construct a standard :class:`CompletionResponse` from primitives.

    This is a convenience helper for providers that return data in
    non-OpenAI formats and need to assemble the response manually.
    """
    choice_data: dict[str, Any] = {
        "index": 0,
        "message": ChoiceMessage(role=Role(role), content=content),
        "finish_reason": finish_reason,
    }
    if extra_choice_fields:
        choice_data.update(extra_choice_fields)

    return CompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:29]}",
        object="chat.completion",
        created=int(time.time()),
        model=model,
        choices=[Choice(**choice_data)],
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        system_fingerprint=system_fingerprint,
    )


def messages_to_dicts(messages: list[Message]) -> list[dict[str, Any]]:
    """Serialise a list of :class:`Message` to plain dicts (exclude None)."""
    return [m.model_dump(exclude_none=True) for m in messages]


def extract_system_message(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Split the system message from the rest (for Anthropic-style APIs).

    Returns ``(system_text, remaining_messages)``.
    """
    system_text: str | None = None
    remaining: list[dict[str, Any]] = []

    for msg in messages:
        if msg.get("role") == Role.SYSTEM:
            # Concatenate multiple system messages
            content = msg.get("content", "")
            if system_text is None:
                system_text = content
            else:
                system_text += "\n" + content
        else:
            remaining.append(msg)

    return system_text, remaining
