"""OpenAI ↔ AWS Bedrock Converse API format transformation.

The Bedrock Converse API has similar concepts to OpenAI but with different
naming and structure:

  OpenAI                   Bedrock Converse
  ──────────────────────   ───────────────────────────────────────────
  messages (role+content)  messages (role + content[{text|toolUse|…}])
  tools[].function         toolConfig.tools[].toolSpec (inputSchema.json)
  system msg in messages   system: [{text: "…"}]
  temperature, max_tokens  inferenceConfig.{temperature,maxTokens,…}
  finish_reason "stop"     stopReason "end_turn"
  finish_reason "length"   stopReason "max_tokens"
  finish_reason "tool_calls" stopReason "tool_use"
"""

from __future__ import annotations

import json
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
from routerbot.providers.bedrock.config import FINISH_REASON_MAP

# ---------------------------------------------------------------------------
# OpenAI → Bedrock Converse
# ---------------------------------------------------------------------------


def openai_to_converse_messages(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]]]:
    """Convert OpenAI messages to Bedrock Converse format.

    Returns ``(system_blocks, converse_messages)`` where ``system_blocks``
    is a list of ``{"text": "..."}`` dicts or ``None``.
    """
    system_parts: list[str] = []
    converse_messages: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        if role in ("system", "developer"):
            if isinstance(content, str):
                system_parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        system_parts.append(part.get("text", ""))
            continue

        if role == Role.TOOL:
            converse_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": msg.get("tool_call_id", ""),
                                "content": [{"text": content if isinstance(content, str) else json.dumps(content)}],
                            }
                        }
                    ],
                }
            )
            continue

        converse_role = "user" if role == Role.USER else "assistant"
        content_blocks = _build_content_blocks(msg)
        converse_messages.append({"role": converse_role, "content": content_blocks})

    system = [{"text": part} for part in system_parts] if system_parts else None
    return system, converse_messages


def _build_content_blocks(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a single message's content to Bedrock content blocks."""
    content = msg.get("content")
    tool_calls = msg.get("tool_calls")
    blocks: list[dict[str, Any]] = []

    if isinstance(content, str) and content:
        blocks.append({"text": content})
    elif isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                blocks.append({"text": part.get("text", "")})
            elif part.get("type") == "image_url":
                url_obj = part.get("image_url", {})
                url = url_obj.get("url", "") if isinstance(url_obj, dict) else str(url_obj)
                if url.startswith("data:"):
                    media_type, _, b64 = url.partition(";base64,")
                    media_type = media_type[5:]
                    blocks.append(
                        {
                            "image": {
                                "format": media_type.split("/")[-1],
                                "source": {"bytes": b64},
                            }
                        }
                    )

    if tool_calls:
        for tc in tool_calls:
            blocks.append(
                {
                    "toolUse": {
                        "toolUseId": tc.get("id", f"tooluse_{uuid.uuid4().hex[:20]}"),
                        "name": tc.get("function", {}).get("name", ""),
                        "input": _safe_json_loads(tc.get("function", {}).get("arguments", "{}")),
                    }
                }
            )

    return blocks or [{"text": ""}]


def openai_tools_to_converse(
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Convert OpenAI tools to Bedrock Converse ``toolConfig`` format."""
    if not tools:
        return None

    converse_tools = []
    for tool in tools:
        fn = tool.get("function", {})
        converse_tools.append(
            {
                "toolSpec": {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "inputSchema": {
                        "json": fn.get("parameters") or {"type": "object", "properties": {}},
                    },
                }
            }
        )
    return {"tools": converse_tools}


def build_converse_request(
    model: str,
    messages: list[dict[str, Any]],
    system: list[dict[str, Any]] | None,
    *,
    max_tokens: int = 4096,
    temperature: float | None = None,
    top_p: float | None = None,
    stop: list[str] | str | None = None,
    tool_config: dict[str, Any] | None = None,
    additional_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Bedrock Converse API request payload."""
    inference_config: dict[str, Any] = {"maxTokens": max_tokens}
    if temperature is not None:
        inference_config["temperature"] = temperature
    if top_p is not None:
        inference_config["topP"] = top_p
    if stop:
        inference_config["stopSequences"] = [stop] if isinstance(stop, str) else list(stop)

    payload: dict[str, Any] = {
        "messages": messages,
        "inferenceConfig": inference_config,
    }
    if system:
        payload["system"] = system
    if tool_config:
        payload["toolConfig"] = tool_config
    if additional_fields:
        payload.update(additional_fields)

    return payload


# ---------------------------------------------------------------------------
# Bedrock Converse → OpenAI
# ---------------------------------------------------------------------------


def converse_response_to_openai(
    data: dict[str, Any],
    model: str,
) -> CompletionResponse:
    """Convert a Bedrock Converse API response to OpenAI format."""
    output = data.get("output", {})
    message = output.get("message", {})
    content_blocks = message.get("content", [])

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for block in content_blocks:
        if "text" in block:
            text_parts.append(block["text"])
        elif "toolUse" in block:
            tu = block["toolUse"]
            tool_calls.append(
                ToolCall(
                    id=tu.get("toolUseId", f"call_{uuid.uuid4().hex[:24]}"),
                    type="function",
                    function=FunctionCall(
                        name=tu.get("name", ""),
                        arguments=json.dumps(tu.get("input", {})),
                    ),
                )
            )

    text = "".join(text_parts) or None
    stop_reason = data.get("stopReason", "end_turn")
    finish_reason_str = FINISH_REASON_MAP.get(stop_reason, "stop")
    finish_reason = FinishReason(finish_reason_str)

    usage_data = data.get("usage", {})
    prompt_tokens = usage_data.get("inputTokens", 0)
    completion_tokens = usage_data.get("outputTokens", 0)

    choice_msg = ChoiceMessage(
        role=Role.ASSISTANT,
        content=text,
        tool_calls=tool_calls if tool_calls else None,
    )

    return CompletionResponse(
        id=f"msg_{uuid.uuid4().hex[:29]}",
        object="chat.completion",
        created=int(time.time()),
        model=model,
        choices=[
            Choice(
                index=0,
                message=choice_msg,
                finish_reason=finish_reason,
            )
        ],
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


# ---------------------------------------------------------------------------
# Streaming event parsing
# ---------------------------------------------------------------------------


def parse_converse_stream_event(
    event: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any] | None:
    """Parse a Bedrock ConverseStream event to an OpenAI-compatible delta dict.

    Events come from the parsed AWS EventStream payload.
    Modifies ``state`` to track streaming state.

    Returns a partial delta dict or None if the event should be skipped.
    """
    if "messageStart" in event:
        state["role"] = event["messageStart"].get("role", "assistant")
        return None

    if "contentBlockStart" in event:
        idx = event.get("contentBlockIndex", 0)
        start = event["contentBlockStart"].get("start", {})
        if "toolUse" in start:
            state.setdefault("tool_calls", {})[idx] = {
                "id": start["toolUse"].get("toolUseId", f"call_{uuid.uuid4().hex[:24]}"),
                "name": start["toolUse"].get("name", ""),
                "arguments": "",
            }
        return None

    if "contentBlockDelta" in event:
        delta = event["contentBlockDelta"].get("delta", {})
        idx = event.get("contentBlockIndex", 0)

        if "text" in delta:
            return {"content": delta["text"], "role": "assistant"}

        if "toolUse" in delta:
            tc = state.get("tool_calls", {}).get(idx)
            if tc:
                partial = delta["toolUse"].get("input", "")
                tc["arguments"] += partial
                return {
                    "tool_calls": [
                        {
                            "index": idx,
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": partial},
                        }
                    ]
                }
        return None

    if "messageStop" in event:
        stop_reason = event["messageStop"].get("stopReason", "end_turn")
        state["finish_reason"] = FINISH_REASON_MAP.get(stop_reason, "stop")
        state["done"] = True
        return None

    if "metadata" in event:
        usage = event["metadata"].get("usage", {})
        state["prompt_tokens"] = usage.get("inputTokens", 0)
        state["completion_tokens"] = usage.get("outputTokens", 0)
        return None

    return None


# ---------------------------------------------------------------------------
# AWS EventStream binary decoder
# ---------------------------------------------------------------------------


def decode_event_stream(data: bytes) -> list[dict[str, Any]]:
    """Decode AWS EventStream-encoded bytes into a list of JSON event dicts.

    Each event in the stream has the structure:
      [4-byte total_len][4-byte headers_len][4-byte prelude_crc]
      [headers_bytes][payload_bytes][4-byte message_crc]

    Headers contain event type metadata (e.g. ``:event-type``).
    The payload is the JSON event body.
    """
    import struct

    events: list[dict[str, Any]] = []
    offset = 0

    while offset < len(data):
        if offset + 12 > len(data):
            break  # Not enough bytes for prelude

        total_len = struct.unpack_from(">I", data, offset)[0]
        headers_len = struct.unpack_from(">I", data, offset + 4)[0]
        # prelude_crc at offset + 8 (4 bytes) — we skip CRC verification

        if offset + total_len > len(data):
            break  # Incomplete message

        # Headers are at offset + 12
        headers_end = offset + 12 + headers_len
        # Payload is between headers_end and (total_len - 4)
        payload_start = headers_end
        payload_end = offset + total_len - 4  # last 4 bytes are message CRC

        payload_bytes = data[payload_start:payload_end]

        try:
            if payload_bytes:
                event = json.loads(payload_bytes.decode("utf-8"))
                events.append(event)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        offset += total_len

    return events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_json_loads(s: str) -> Any:
    """Parse JSON string, returning empty dict on failure."""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return {}
