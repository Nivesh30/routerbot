"""DeepSeek provider — OpenAI-compatible wrapper."""

from __future__ import annotations

from typing import Any

from routerbot.providers.openai.provider import OpenAIProvider
from routerbot.providers.registry import register_provider

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

DEEPSEEK_MODELS: frozenset[str] = frozenset(
    {
        "deepseek-chat",
        "deepseek-coder",
        "deepseek-reasoner",
        "deepseek-r1",
        "deepseek-r1-distill-llama-70b",
        "deepseek-r1-distill-qwen-32b",
    }
)


class DeepSeekProvider(OpenAIProvider):
    """Provider for DeepSeek AI.

    DeepSeek implements the OpenAI REST API at a different base URL.

    Parameters
    ----------
    api_key:
        DeepSeek API key (from ``https://platform.deepseek.com/``).
    api_base:
        Override the default DeepSeek base URL (useful for testing).
    """

    provider_name: str = "deepseek"

    def __init__(
        self,
        api_key: str,
        *,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            api_key=api_key,
            api_base=api_base or DEEPSEEK_BASE_URL,
            **kwargs,
        )


register_provider("deepseek", DeepSeekProvider)
