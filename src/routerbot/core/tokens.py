"""Token counting utilities.

Uses ``tiktoken`` for OpenAI models and falls back to a character-based
estimate (~4 characters per token) for unknown tokenizers. The module is
designed so that a missing ``tiktoken`` installation degrades gracefully.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from routerbot.core.types import Message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# tiktoken lazy-loading
# ---------------------------------------------------------------------------

_TIKTOKEN_ENCODINGS: dict[str, object] = {}

# Map model families → tiktoken encoding names
_TIKTOKEN_MODEL_MAP: dict[str, str] = {
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "o1": "o200k_base",
    "o1-mini": "o200k_base",
    "o3": "o200k_base",
    "o3-mini": "o200k_base",
    "o4-mini": "o200k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-4-32k": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "text-embedding-3-small": "cl100k_base",
    "text-embedding-3-large": "cl100k_base",
    "text-embedding-ada-002": "cl100k_base",
}

# Encoding name → tiktoken encoding name (from model_prices.json tokenizer field)
_TOKENIZER_ENCODING_MAP: dict[str, str] = {
    "o200k_base": "o200k_base",
    "cl100k_base": "cl100k_base",
}

# Fallback: approximate tokens per character for unknown models
_CHARS_PER_TOKEN_ESTIMATE = 4.0


def _get_tiktoken_encoding(encoding_name: str) -> object | None:
    """Get or cache a tiktoken encoding. Returns None if tiktoken unavailable."""
    if encoding_name in _TIKTOKEN_ENCODINGS:
        return _TIKTOKEN_ENCODINGS[encoding_name]

    try:
        import tiktoken

        enc = tiktoken.get_encoding(encoding_name)
        _TIKTOKEN_ENCODINGS[encoding_name] = enc
        return enc
    except (ImportError, Exception):
        logger.debug("tiktoken not available or encoding %s not found", encoding_name)
        return None


def _resolve_encoding_name(model: str) -> str | None:
    """Resolve a model name to a tiktoken encoding name."""
    # Exact match first
    if model in _TIKTOKEN_MODEL_MAP:
        return _TIKTOKEN_MODEL_MAP[model]

    # Try prefix matching (e.g., "gpt-4o-2024-08-06" → "gpt-4o")
    for prefix, encoding in _TIKTOKEN_MODEL_MAP.items():
        if model.startswith(prefix):
            return encoding

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """Count tokens in a text string.

    Args:
        text: The text to tokenize.
        model: Model name used to select the tokenizer.

    Returns:
        Exact token count if tiktoken is available for this model,
        otherwise an approximate count.
    """
    encoding_name = _resolve_encoding_name(model)
    if encoding_name:
        enc = _get_tiktoken_encoding(encoding_name)
        if enc is not None:
            return len(enc.encode(text))  # type: ignore[attr-defined]

    # Fallback estimation
    return _estimate_tokens(text)


def count_message_tokens(messages: list[Message], model: str = "gpt-4o") -> int:
    """Count tokens for a list of chat messages.

    Follows the OpenAI token counting convention:
    - Each message adds overhead tokens (role, delimiters)
    - The reply priming adds 3 tokens

    Args:
        messages: List of Message objects.
        model: Model name for tokenizer selection.

    Returns:
        Total token count across all messages.
    """
    # Per OpenAI docs: each message has ~4 tokens of overhead
    # (role, delimiters, etc.), and the reply is primed with 3 tokens.
    tokens_per_message = 4
    tokens_per_name = -1  # if name is present, role is omitted (saves 1 token)

    total = 0
    for msg in messages:
        total += tokens_per_message

        # Count content tokens
        if isinstance(msg.content, str):
            total += count_tokens(msg.content, model)
        elif isinstance(msg.content, list):
            for part in msg.content:
                if hasattr(part, "text"):
                    total += count_tokens(part.text, model)
                # Image/audio parts: use a fixed estimate
                elif hasattr(part, "image_url"):
                    total += 85  # base image token cost (low detail)
                elif hasattr(part, "input_audio"):
                    total += 100  # rough audio token estimate

        # Role
        total += count_tokens(str(msg.role), model)

        # Name (if present)
        if msg.name:
            total += count_tokens(msg.name, model) + tokens_per_name

        # Tool calls
        if msg.tool_calls:
            for tc in msg.tool_calls:
                total += count_tokens(tc.function.name, model)
                total += count_tokens(tc.function.arguments, model)
                total += 3  # tool call overhead

    total += 3  # reply priming
    return total


def _estimate_tokens(text: str) -> int:
    """Estimate token count using character-based heuristic.

    Uses ~4 characters per token, which is a reasonable average for
    English text across most tokenizers.
    """
    return max(1, int(len(text) / _CHARS_PER_TOKEN_ESTIMATE))
