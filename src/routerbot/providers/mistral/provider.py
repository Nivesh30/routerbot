"""Mistral AI provider — OpenAI-compatible wrapper with minor differences.

Mistral's API is largely OpenAI-compatible with a few quirks:

* ``safe_prompt`` parameter (Mistral-specific)
* Different ``finish_reason`` for tool calls (Mistral uses ``"tool_calls"``
  which matches OpenAI, so no translation needed)
* Model names differ (``mistral-large-latest``, ``mistral-small-latest``, etc.)
"""

from __future__ import annotations

from typing import Any

from routerbot.providers.openai.provider import OpenAIProvider
from routerbot.providers.registry import register_provider

MISTRAL_BASE_URL = "https://api.mistral.ai/v1"

MISTRAL_MODELS: frozenset[str] = frozenset(
    {
        "mistral-large-latest",
        "mistral-large-2411",
        "mistral-medium-latest",
        "mistral-small-latest",
        "mistral-small-2402",
        "open-mistral-nemo",
        "open-mistral-7b",
        "open-mixtral-8x7b",
        "open-mixtral-8x22b",
        "codestral-latest",
        "codestral-mamba-latest",
        "mistral-embed",
    }
)


class MistralProvider(OpenAIProvider):
    """Provider for Mistral AI.

    Mistral implements a largely OpenAI-compatible API. The main
    differences are the base URL and model names.

    Parameters
    ----------
    api_key:
        Mistral API key (from ``https://console.mistral.ai/``).
    api_base:
        Override the default Mistral base URL (useful for testing).
    """

    provider_name: str = "mistral"

    def __init__(
        self,
        api_key: str,
        *,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_base=api_base or MISTRAL_BASE_URL,
            **kwargs,
        )


register_provider("mistral", MistralProvider)
