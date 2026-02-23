"""OpenAI ↔ Anthropic format transformation.

Anthropic's Messages API differs from OpenAI in several key ways:
- System message is a top-level field, not in the messages array
- Content can be a list of "content blocks" (text, tool_use, tool_result)
- Stop reasons use different names (end_turn, max_tokens, tool_use)
- Streaming uses different event types (message_start, content_block_delta, …)
- Tool calls use different structure (tool_use block vs function call)
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
from routerbot.providers.anthropic.config import FINISH_REASON_MAP

# ---------------------------------------------------------------------------
# OpenAI → Anthropic
# ---------------------------------------------------------------------------


def openai_messages_to_anthropic(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert OpenAI messages to Anthropic format.

    Returns ``(system_text, anthropic_messages)``.

    Key differences handled:
    - System messages extracted to top-level ``system`` field
    - Tool call messages converted to tool_use content blocks
    - Tool result messages converted to tool_result content blocks
    - Image content converted to Anthropic vision format
    """
    system_parts: list[str] = []
    anthropic_messages: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        if role == Role.SYSTEM or role == "developer":
            # Accumulate all system messages as one block
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        system_parts.append(part.get("text", ""))
            continue

        if role == Role.TOOL:
            # Tool result from client — maps to user message with tool_result block
            anthropic_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id", ""),
                            "content": content if isinstance(content, str) else str(content),
                        }
                    ],
                }
            )
            continue

        if role == Role.ASSISTANT and msg.get("tool_calls"):
            # Assistant wants to call tools — build content blocks
            content_blocks: list[dict[str, Any]] = []

            if content:
                content_blocks.append({"type": "text", "text": content})

            for tc in msg.get("tool_calls", []):
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:24]}"),
                        "name": tc.get("function", {}).get("name", ""),
                        "input": _safe_json_loads(tc.get("function", {}).get("arguments", "{}")),
                    }
                )
            anthropic_messages.append({"role": "assistant", "content": content_blocks})
            continue

        # Regular user/assistant message
        anthropic_role = "user" if role == Role.USER else "assistant"
        anthropic_content = _convert_content(content)
        anthropic_messages.append({"role": anthropic_role, "content": anthropic_content})

    return "\n".join(system_parts) or None, anthropic_messages


def _convert_content(content: Any) -> Any:
    """Convert OpenAI content to Anthropic content blocks."""
    if isinstance(content, str):
        return content  # Anthropic accepts plain strings too

    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type", "")
            if part_type == "text":
                blocks.append({"type": "text", "text": part.get("text", "")})
            elif part_type == "image_url":
                url_obj = part.get("image_url", {})
                url = url_obj.get("url", "") if isinstance(url_obj, dict) else str(url_obj)
                if url.startswith("data:"):
                    # Base64 encoded image
                    media_type, _, b64_data = url.partition(";base64,")
                    media_type = media_type[5:]  # strip "data:"
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64_data,
                            },
                        }
                    )
                else:
                    # URL reference
                    blocks.append(
                        {
                            "type": "image",
                            "source": {"type": "url", "url": url},
                        }
                    )
        return blocks

    return content


def openai_tools_to_anthropic(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Convert OpenAI tool definitions to Anthropic tools format."""
    if not tools:
        return None

    anthropic_tools: list[dict[str, Any]] = []
    for tool in tools:
        fn = tool.get("function", {})
        anthropic_tools.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return anthropic_tools


def build_anthropic_request(
    model: str,
    messages: list[dict[str, Any]],
    system: str | None,
    *,
    max_tokens: int = 4096,
    temperature: float | None = None,
    top_p: float | None = None,
    stop: list[str] | str | None = None,
    tools: list[dict[str, Any]] | None = None,
    stream: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Anthropic API request payload."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": stream,
    }

    if system:
        payload["system"] = system
    if temperature is not None:
        payload["temperature"] = temperature
    if top_p is not None:
        payload["top_p"] = top_p
    if stop:
        payload["stop_sequences"] = [stop] if isinstance(stop, str) else list(stop)
    if tools:
        payload["tools"] = tools

    if extra:
        payload.update(extra)

    return payload


# ---------------------------------------------------------------------------
# Anthropic → OpenAI
# ---------------------------------------------------------------------------


def anthropic_response_to_openai(
    data: dict[str, Any],
    model: str,
) -> CompletionResponse:
    """Convert an Anthropic Messages API response to OpenAI format."""
    content_blocks = data.get("content", [])
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for block in content_blocks:
        btype = block.get("type", "")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            import json

            tool_calls.append(
                ToolCall(
                    id=block.get("id", f"call_{uuid.uuid4().hex[:24]}"),
                    type="function",
                    function=FunctionCall(
                        name=block.get("name", ""),
                        arguments=json.dumps(block.get("input", {})),
                    ),
                )
            )

    text = "".join(text_parts) or None
    finish_reason_str = FINISH_REASON_MAP.get(data.get("stop_reason", "end_turn"), "stop")
    finish_reason = FinishReason(finish_reason_str)

    usage_data = data.get("usage", {})
    input_tokens = usage_data.get("input_tokens", 0)
    output_tokens = usage_data.get("output_tokens", 0)

    choice_msg = ChoiceMessage(
        role=Role.ASSISTANT,
        content=text,
        tool_calls=tool_calls if tool_calls else None,
    )

    return CompletionResponse(
        id=data.get("id", f"msg_{uuid.uuid4().hex[:29]}"),
        object="chat.completion",
        created=int(time.time()),
        model=data.get("model", model),
        choices=[
            Choice(
                index=0,
                message=choice_msg,
                finish_reason=finish_reason,
            )
        ],
        usage=Usage(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )


def anthropic_stream_event_to_delta(
    event_type: str,
    event_data: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any] | None:
    """Convert an Anthropic SSE event to an OpenAI-compatible chunk dict.

    Modifies ``state`` in-place to track streaming state across events.

    Returns a partial chunk dict or None if the event should be skipped.
    """
    if event_type == "message_start":
        msg = event_data.get("message", {})
        state["id"] = msg.get("id", f"msg_{uuid.uuid4().hex[:29]}")
        state["model"] = msg.get("model", "")
        usage = msg.get("usage", {})
        state["prompt_tokens"] = usage.get("input_tokens", 0)
        return None

    if event_type == "content_block_start":
        block = event_data.get("content_block", {})
        idx = event_data.get("index", 0)
        state.setdefault("blocks", {})[idx] = block
        if block.get("type") == "tool_use":
            # Start a new tool call
            state.setdefault("tool_calls", {})[idx] = {
                "id": block.get("id", f"call_{uuid.uuid4().hex[:24]}"),
                "name": block.get("name", ""),
                "arguments": "",
            }
        return None

    if event_type == "content_block_delta":
        delta = event_data.get("delta", {})
        idx = event_data.get("index", 0)
        delta_type = delta.get("type", "")

        if delta_type == "text_delta":
            return {"content": delta.get("text", ""), "role": "assistant"}

        if delta_type == "input_json_delta":
            # Accumulate tool call arguments
            tc = state.get("tool_calls", {}).get(idx)
            if tc:
                tc["arguments"] += delta.get("partial_json", "")
                return {
                    "tool_calls": [
                        {
                            "index": idx,
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": delta.get("partial_json", ""),
                            },
                        }
                    ]
                }
        return None

    if event_type == "message_delta":
        delta = event_data.get("delta", {})
        stop_reason = delta.get("stop_reason")
        usage = event_data.get("usage", {})
        state["completion_tokens"] = usage.get("output_tokens", 0)
        if stop_reason:
            state["finish_reason"] = FINISH_REASON_MAP.get(stop_reason, "stop")
        return None

    if event_type == "message_stop":
        state["done"] = True
        return None

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_json_loads(s: str) -> Any:
    """Parse JSON string, returning empty dict on failure."""
    import json

    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return {}
