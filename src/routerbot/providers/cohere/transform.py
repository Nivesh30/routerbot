"""OpenAI ↔ Cohere v2 Chat API format transformation.

Cohere's v2 Chat API is OpenAI-compatible at the message level, but differs in:
- Finish reason naming (``COMPLETE`` → ``stop``, ``TOOL_CALL`` → ``tool_calls``)
- Embeddings input format (``{"texts": [...], "model": "...", "input_type": "..."}`` )
- Response shape for embeddings (``embeddings.float[]``)
- Streaming: Cohere v2 ``/chat`` streaming emits its own SSE event schema
  (``message-start``, ``content-delta``, ``message-end``, etc.), *not*
  OpenAI-format chunks — see :func:`parse_cohere_stream_event`.
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
    FunctionCall,
    ToolCall,
    Usage,
)
from routerbot.providers.cohere.config import FINISH_REASON_MAP


def cohere_response_to_openai(data: dict[str, Any], model: str) -> CompletionResponse:
    """Convert a Cohere v2 ``/chat`` response to OpenAI format."""
    msg = data.get("message", {})
    content_parts = msg.get("content", [])
    tool_calls_raw = msg.get("tool_calls") or []

    text_parts: list[str] = []
    for block in content_parts:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif isinstance(block, str):
            text_parts.append(block)

    text = "".join(text_parts) or None

    tool_calls: list[ToolCall] = []
    for tc in tool_calls_raw:
        tool_calls.append(
            ToolCall(
                id=tc.get("id", f"call_{uuid.uuid4().hex[:24]}"),
                type="function",
                function=FunctionCall(
                    name=tc.get("function", {}).get("name", ""),
                    arguments=tc.get("function", {}).get("arguments", "{}"),
                ),
            )
        )

    usage_data = data.get("usage", {})
    billed = usage_data.get("billed_units", {})
    tokens = usage_data.get("tokens", {})
    prompt_tokens = billed.get("input_tokens") or tokens.get("input_tokens", 0)
    completion_tokens = billed.get("output_tokens") or tokens.get("output_tokens", 0)

    raw_fr = data.get("finish_reason", "COMPLETE")
    fr_str = FINISH_REASON_MAP.get(raw_fr, "stop")
    if tool_calls and fr_str != "tool_calls":
        fr_str = "tool_calls"

    return CompletionResponse(
        id=data.get("id", f"chatcmpl-{uuid.uuid4().hex[:29]}"),
        object="chat.completion",
        created=int(time.time()),
        model=model,
        choices=[
            Choice(
                index=0,
                message=ChoiceMessage(
                    role=Role.ASSISTANT,
                    content=text,
                    tool_calls=tool_calls if tool_calls else None,
                ),
                finish_reason=FinishReason(fr_str),
            )
        ],
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def parse_cohere_stream_event(data: dict[str, Any], model: str) -> CompletionResponseChunk | None:
    """Convert one Cohere v2 ``/chat`` SSE event into an OpenAI-format chunk.

    Cohere's streaming events (per ``type``):
    - ``message-start`` — stream begins; emits the assistant role delta.
    - ``content-start`` / ``content-end`` — text block boundaries; no
      OpenAI equivalent, so no chunk is emitted.
    - ``content-delta`` — incremental text; maps to a ``delta.content`` chunk.
    - ``message-end`` — stream ends; carries ``finish_reason`` and usage.
    - ``tool-*`` events (tool-call streaming) — not yet mapped; skipped
      rather than raising, so a tool-call response falls back to silently
      omitting tool_call deltas instead of erroring the whole stream.

    Returns ``None`` for event types that don't correspond to an OpenAI
    chunk (the caller should just continue to the next SSE line).
    """
    event_type = data.get("type")

    if event_type == "message-start":
        return CompletionResponseChunk(
            model=model,
            choices=[ChunkChoice(index=0, delta=DeltaMessage(role=Role.ASSISTANT))],
        )

    if event_type == "content-delta":
        text = data.get("delta", {}).get("message", {}).get("content", {}).get("text", "")
        if not text:
            return None
        return CompletionResponseChunk(
            model=model,
            choices=[ChunkChoice(index=0, delta=DeltaMessage(content=text))],
        )

    if event_type == "message-end":
        delta = data.get("delta", {})
        raw_finish = delta.get("finish_reason")
        finish_reason = FinishReason(FINISH_REASON_MAP.get(raw_finish, "stop")) if raw_finish else None

        usage_data = delta.get("usage", {})
        billed = usage_data.get("billed_units", {})
        tokens = usage_data.get("tokens", {})
        prompt_tokens = billed.get("input_tokens") or tokens.get("input_tokens", 0)
        completion_tokens = billed.get("output_tokens") or tokens.get("output_tokens", 0)

        return CompletionResponseChunk(
            model=model,
            choices=[ChunkChoice(index=0, delta=DeltaMessage(), finish_reason=finish_reason)],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            )
            if (prompt_tokens or completion_tokens)
            else None,
        )

    # content-start, content-end, tool-plan-delta, tool-call-start,
    # tool-call-delta, tool-call-end, and any unrecognized event type.
    return None
