"""Groq provider — OpenAI-compatible wrapper."""

from __future__ import annotations

from typing import Any

from routerbot.providers.openai.provider import OpenAIProvider
from routerbot.providers.registry import register_provider

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Current Groq model list (fast inference)
GROQ_MODELS: frozenset[str] = frozenset(
    {
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "llama-3.1-8b-instant",
        "llama-3.2-1b-preview",
        "llama-3.2-3b-preview",
        "llama-3.2-11b-vision-preview",
        "llama-3.2-90b-vision-preview",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
        "gemma-7b-it",
    }
)


class GroqProvider(OpenAIProvider):
    """Provider for Groq Cloud (ultra-fast LLM inference).

    Groq implements the OpenAI REST API. The only differences are:
    - Different base URL (``https://api.groq.com/openai/v1``)
    - A Groq-issued API key

    Parameters
    ----------
    api_key:
        Groq API key (from ``https://console.groq.com/``).
    api_base:
        Override the default Groq base URL (useful for testing).
    """

    provider_name: str = "groq"

    def __init__(
        self,
        api_key: str,
        *,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_base=api_base or GROQ_BASE_URL,
            **kwargs,
        )


register_provider("groq", GroqProvider)
