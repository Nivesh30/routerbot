"""Anthropic-specific configuration constants."""

from __future__ import annotations

ANTHROPIC_API_BASE = "https://api.anthropic.com"

# Required API version header
ANTHROPIC_VERSION = "2023-06-01"

# Current supported models
CHAT_MODELS = frozenset(
    {
        "claude-opus-4-20250514",
        "claude-opus-4-5",
        "claude-sonnet-4-20250514",
        "claude-sonnet-4-5",
        "claude-sonnet-3-5-20241022",
        "claude-sonnet-3-5-20240620",
        "claude-haiku-3-5-20241022",
        "claude-haiku-3-20240307",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        # Aliases
        "claude-opus-4",
        "claude-sonnet-4",
        "claude-haiku-3-5",
    }
)

# Models supporting extended thinking
EXTENDED_THINKING_MODELS = frozenset(
    {
        "claude-opus-4-20250514",
        "claude-opus-4-5",
        "claude-sonnet-4-20250514",
        "claude-sonnet-4-5",
        "claude-sonnet-3-5-20241022",
    }
)

# Finish reason mapping: Anthropic → OpenAI
FINISH_REASON_MAP: dict[str, str] = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
    "pause_turn": "stop",
    "refusal": "stop",
}

# Maximum tokens per model
MAX_TOKENS: dict[str, int] = {
    "claude-opus-4-20250514": 32000,
    "claude-opus-4-5": 32000,
    "claude-sonnet-4-20250514": 64000,
    "claude-sonnet-4-5": 64000,
    "claude-sonnet-3-5-20241022": 8192,
    "claude-sonnet-3-5-20240620": 8192,
    "claude-haiku-3-5-20241022": 8192,
    "claude-haiku-3-20240307": 4096,
    "claude-3-opus-20240229": 4096,
    "claude-3-sonnet-20240229": 4096,
}

DEFAULT_MAX_TOKENS = 4096
