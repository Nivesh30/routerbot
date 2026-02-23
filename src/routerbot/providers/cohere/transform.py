"""OpenAI ↔ Cohere v2 Chat API format transformation.

Cohere's v2 Chat API is OpenAI-compatible at the message level, but differs in:
- Finish reason naming (``COMPLETE`` → ``stop``, ``TOOL_CALL`` → ``tool_calls``)
- Embeddings input format (``{"texts": [...], "model": "...", "input_type": "..."}`` )
- Response shape for embeddings (``embeddings.float[]``)
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
