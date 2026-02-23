"""Transformation helpers for the Ollama provider.

Ollama's ``/api/chat`` response differs from OpenAI's format:
- Non-streaming: a single JSON object with ``message`` (not ``choices``)
- Streaming: one JSON object per line, each with ``message.content`` delta
  and a final object with ``done: true`` carrying usage counts

Reference: https://github.com/ollama/ollama/blob/main/docs/api.md
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from routerbot.core.enums import FinishReason, Role
from routerbot.core.types import (
    Choice,
    ChoiceMessage,
    ChunkChoice,
    CompletionResponse,
    CompletionResponseChunk,
    DeltaMessage,
    Usage,
)

# Ollama done_reason -> OpenAI finish_reason
FINISH_REASON_MAP: dict[str, FinishReason] = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "load": FinishReason.STOP,  # model loaded, treat as stop
}


def ollama_response_to_openai(data: dict[str, Any], model: str) -> CompletionResponse:
    """Convert an Ollama non-streaming response to OpenAI format.

    Parameters
    ----------
    data:
        Parsed JSON response body from ``POST /api/chat``.
    model:
        Model name to populate in the response.

    Returns
    -------
    CompletionResponse
        Normalised OpenAI-compatible response.
    """
    msg = data.get("message", {})
    role_str: str = msg.get("role", "assistant")
    content: str | None = msg.get("content")

    # Tool calls — Ollama returns tool_calls inside message (same shape as OpenAI)
    raw_tool_calls = msg.get("tool_calls")
    import json as _json

    from routerbot.core.types import FunctionCall, ToolCall

    tool_calls = None
    if raw_tool_calls:
        tool_calls = []
        for i, tc in enumerate(raw_tool_calls):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            args_str = _json.dumps(args) if isinstance(args, dict) else str(args)
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", f"call_{uuid.uuid4().hex[:8]}_{i}"),
                    function=FunctionCall(
                        name=fn.get("name", ""),
                        arguments=args_str,
                    ),
                )
            )

    done_reason: str = data.get("done_reason", "stop")
    finish_reason = FINISH_REASON_MAP.get(done_reason, FinishReason.STOP)

    # Usage: Ollama returns prompt_eval_count and eval_count
    prompt_tokens: int = data.get("prompt_eval_count", 0)
    completion_tokens: int = data.get("eval_count", 0)

    try:
        role = Role(role_str)
    except ValueError:
        role = Role.ASSISTANT

    return CompletionResponse(
        model=model,
        choices=[
            Choice(
                index=0,
                message=ChoiceMessage(
                    role=role,
                    content=content,
                    tool_calls=tool_calls,
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def ollama_chunk_to_openai(
    data: dict[str, Any],
    model: str,
    chunk_id: str,
) -> CompletionResponseChunk:
    """Convert a single Ollama streaming line to an OpenAI chunk.

    Parameters
    ----------
    data:
        Parsed JSON from a single streamed line.
    model:
        Model name for the chunk.
    chunk_id:
        Shared ID for all chunks in this response.

    Returns
    -------
    CompletionResponseChunk
        OpenAI-compatible streaming chunk.
    """
    msg = data.get("message", {})
    content: str | None = msg.get("content") or None

    done: bool = data.get("done", False)

    finish_reason: FinishReason | None = None
    usage: Usage | None = None

    if done:
        done_reason: str = data.get("done_reason", "stop")
        finish_reason = FINISH_REASON_MAP.get(done_reason, FinishReason.STOP)

        prompt_tokens: int = data.get("prompt_eval_count", 0)
        completion_tokens: int = data.get("eval_count", 0)
        if prompt_tokens or completion_tokens:
            usage = Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            )

    return CompletionResponseChunk(
        id=chunk_id,
        created=int(time.time()),
        model=model,
        choices=[
            ChunkChoice(
                index=0,
                delta=DeltaMessage(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )
