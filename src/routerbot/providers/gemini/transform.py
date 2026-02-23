"""OpenAI ↔ Google Gemini API format transformation.

Gemini uses a different request/response format compared to OpenAI:

  OpenAI                      Gemini
  ──────────────────────      ──────────────────────────────────────────
  messages[]                  contents[] (role: "user"|"model")
  system message              systemInstruction: {parts: [{text}]}
  content (string)            parts: [{text: "..."}]
  tool_calls in assistant     parts: [{functionCall: {name, args}}]
  tool result (role: tool)    user message with functionResponse part
  finish_reason "stop"        finishReason "STOP"
  finish_reason "length"      finishReason "MAX_TOKENS"
  finish_reason "tool_calls"  finishReason "STOP" + functionCall parts
  usage.prompt_tokens         usageMetadata.promptTokenCount
  usage.completion_tokens     usageMetadata.candidatesTokenCount
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
    ChunkChoice,
    CompletionResponse,
    CompletionResponseChunk,
    DeltaMessage,
    FunctionCall,
    ToolCall,
    Usage,
)
from routerbot.providers.gemini.config import FINISH_REASON_MAP

# ---------------------------------------------------------------------------
# OpenAI → Gemini
# ---------------------------------------------------------------------------


def openai_to_gemini_contents(
    messages: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Convert OpenAI messages to Gemini ``contents`` format.

    Returns ``(system_instruction, contents)`` where ``system_instruction``
    is ``{"parts": [{"text": "..."}]}`` or ``None``.
    """
    system_parts: list[dict[str, Any]] = []
    contents: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        if role in ("system", "developer"):
            text = _extract_text(content)
            if text:
                system_parts.append({"text": text})
            continue

        if role == Role.TOOL:
            # Tool result: wrap in user message with functionResponse part
            tool_call_id = msg.get("tool_call_id", "unknown")
            raw = content
            if isinstance(raw, str):
                try:
                    response_data: Any = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    response_data = {"result": raw}
            else:
                response_data = raw or {}

            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": tool_call_id,  # best effort — name not available
                                "response": response_data,
                            }
                        }
                    ],
                }
            )
            continue

        # user / assistant messages
        gemini_role = "model" if role == Role.ASSISTANT else "user"
        parts = _build_parts(msg)
        if parts:
            contents.append({"role": gemini_role, "parts": parts})

    system_instruction = {"parts": system_parts} if system_parts else None
    return system_instruction, contents


def _extract_text(content: Any) -> str:
    """Extract plain text from a content field (string or list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(part.get("text", ""))
        return " ".join(texts)
    return ""


def _build_parts(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """Build Gemini ``parts`` from an OpenAI message."""
    parts: list[dict[str, Any]] = []
    content = msg.get("content")
    tool_calls = msg.get("tool_calls")

    if isinstance(content, str) and content:
        parts.append({"text": content})
    elif isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "text":
                parts.append({"text": item.get("text", "")})
            elif item_type == "image_url":
                url_obj = item.get("image_url", {})
                url = url_obj.get("url", "") if isinstance(url_obj, dict) else str(url_obj)
                if url.startswith("data:"):
                    # data:{mime};base64,{data}
                    mime_part, _, b64_data = url.partition(";base64,")
                    mime_type = mime_part[5:]  # strip "data:"
                    parts.append(
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": b64_data,
                            }
                        }
                    )
                # URL-based images are not directly supported; skip

    if tool_calls:
        for tc in tool_calls:
            fn = tc.get("function", {})
            args = fn.get("arguments", "{}")
            try:
                args_dict: Any = json.loads(args)
            except (json.JSONDecodeError, ValueError):
                args_dict = {}
            parts.append(
                {
                    "functionCall": {
                        "name": fn.get("name", ""),
                        "args": args_dict,
                    }
                }
            )

    return parts


def openai_tools_to_gemini(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Convert OpenAI tools to Gemini ``tools`` format."""
    if not tools:
        return None

    function_declarations = []
    for tool in tools:
        fn = tool.get("function", {})
        decl: dict[str, Any] = {
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
        }
        params = fn.get("parameters")
        if params:
            decl["parameters"] = params
        function_declarations.append(decl)

    return [{"functionDeclarations": function_declarations}]


def build_gemini_request(
    messages: list[dict[str, Any]],
    system_instruction: dict[str, Any] | None,
    *,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    stop: list[str] | str | None = None,
    tools: list[dict[str, Any]] | None = None,
    additional_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Gemini ``generateContent`` request payload."""
    generation_config: dict[str, Any] = {}
    if max_tokens is not None:
        generation_config["maxOutputTokens"] = max_tokens
    if temperature is not None:
        generation_config["temperature"] = temperature
    if top_p is not None:
        generation_config["topP"] = top_p
    if stop:
        generation_config["stopSequences"] = [stop] if isinstance(stop, str) else list(stop)

    payload: dict[str, Any] = {"contents": messages}

    if system_instruction:
        payload["systemInstruction"] = system_instruction
    if generation_config:
        payload["generationConfig"] = generation_config
    if tools:
        payload["tools"] = tools
    if additional_fields:
        payload.update(additional_fields)

    return payload


# ---------------------------------------------------------------------------
# Gemini → OpenAI
# ---------------------------------------------------------------------------


def gemini_response_to_openai(
    data: dict[str, Any],
    model: str,
) -> CompletionResponse:
    """Convert a Gemini ``generateContent`` response to OpenAI format."""
    candidates = data.get("candidates", [])
    candidate = candidates[0] if candidates else {}

    content_obj = candidate.get("content", {})
    parts = content_obj.get("parts", [])

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    for part in parts:
        if "text" in part:
            text_parts.append(part["text"])
        elif "functionCall" in part:
            fc = part["functionCall"]
            tool_calls.append(
                ToolCall(
                    id=f"call_{uuid.uuid4().hex[:24]}",
                    type="function",
                    function=FunctionCall(
                        name=fc.get("name", ""),
                        arguments=json.dumps(fc.get("args", {})),
                    ),
                )
            )

    text = "".join(text_parts) or None

    gemini_finish = candidate.get("finishReason", "STOP")
    # If there are function calls, force tool_calls finish reason
    if tool_calls and gemini_finish == "STOP":
        finish_reason_str = "tool_calls"
    else:
        finish_reason_str = FINISH_REASON_MAP.get(gemini_finish, "stop")

    finish_reason = FinishReason(finish_reason_str)

    usage_data = data.get("usageMetadata", {})
    prompt_tokens = usage_data.get("promptTokenCount", 0)
    completion_tokens = usage_data.get("candidatesTokenCount", 0)
    total_tokens = usage_data.get("totalTokenCount", prompt_tokens + completion_tokens)

    choice_msg = ChoiceMessage(
        role=Role.ASSISTANT,
        content=text,
        tool_calls=tool_calls if tool_calls else None,
    )

    return CompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:29]}",
        object="chat.completion",
        created=int(time.time()),
        model=data.get("modelVersion", model),
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
            total_tokens=total_tokens,
        ),
    )


def gemini_sse_chunk_to_openai(
    data: dict[str, Any],
    model: str,
    chunk_id: str,
    state: dict[str, Any],
) -> CompletionResponseChunk | None:
    """Convert a Gemini SSE streaming chunk to an OpenAI-format chunk.

    Modifies ``state`` to track accumulated tool calls across chunks.
    Returns ``None`` for non-content events (e.g. empty candidates).
    """
    candidates = data.get("candidates", [])
    if not candidates:
        # May contain only usageMetadata
        usage = data.get("usageMetadata", {})
        if usage:
            state["prompt_tokens"] = usage.get("promptTokenCount", 0)
            state["completion_tokens"] = usage.get("candidatesTokenCount", 0)
        return None

    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    gemini_finish = candidate.get("finishReason")

    delta_dict: dict[str, Any] = {"role": "assistant"}
    tool_call_deltas: list[dict[str, Any]] = []

    for part in parts:
        if "text" in part:
            delta_dict["content"] = part["text"]
        elif "functionCall" in part:
            fc = part["functionCall"]
            idx = state.get("tool_call_index", 0)
            state["tool_call_index"] = idx + 1
            tool_call_deltas.append(
                {
                    "index": idx,
                    "id": f"call_{uuid.uuid4().hex[:24]}",
                    "type": "function",
                    "function": {
                        "name": fc.get("name", ""),
                        "arguments": json.dumps(fc.get("args", {})),
                    },
                }
            )

    if tool_call_deltas:
        delta_dict["tool_calls"] = tool_call_deltas

    finish_reason: FinishReason | None = None
    if gemini_finish and gemini_finish not in (
        "FINISH_REASON_UNSPECIFIED",
        "",
    ):
        fr_str = "tool_calls" if tool_call_deltas else FINISH_REASON_MAP.get(gemini_finish, "stop")
        finish_reason = FinishReason(fr_str)
        state["done"] = True

    if "content" not in delta_dict and not tool_call_deltas and finish_reason is None:
        return None

    return CompletionResponseChunk(
        id=chunk_id,
        object="chat.completion.chunk",
        created=int(time.time()),
        model=model,
        choices=[
            ChunkChoice(
                index=0,
                delta=DeltaMessage.model_validate(delta_dict),
                finish_reason=finish_reason,
            )
        ],
    )
