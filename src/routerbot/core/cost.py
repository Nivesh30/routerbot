"""Cost calculation for LLM API requests.

Computes the dollar cost of a request based on token usage and the
model pricing database (``model_prices.json``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from routerbot.core.model_registry import get_model_info

if TYPE_CHECKING:
    from routerbot.core.types import Usage

logger = logging.getLogger(__name__)


def calculate_cost(
    model: str,
    usage: Usage,
    *,
    custom_input_cost: float | None = None,
    custom_output_cost: float | None = None,
) -> float:
    """Calculate the USD cost for a completion request.

    Args:
        model: The model name (e.g. ``"gpt-4o"``).
        usage: Token usage from the response.
        custom_input_cost: Override input cost per token (USD).
        custom_output_cost: Override output cost per token (USD).

    Returns:
        Total cost in USD.  Returns ``0.0`` if pricing is unknown.
    """
    info = get_model_info(model)

    input_cost_per_token = custom_input_cost
    output_cost_per_token = custom_output_cost

    if input_cost_per_token is None and info:
        input_cost_per_token = info.get("input_cost_per_token")
    if output_cost_per_token is None and info:
        output_cost_per_token = info.get("output_cost_per_token")

    if input_cost_per_token is None or output_cost_per_token is None:
        logger.warning("No pricing data for model '%s'. Returning cost 0.0.", model)
        return 0.0

    prompt_cost = usage.prompt_tokens * input_cost_per_token
    completion_cost = usage.completion_tokens * output_cost_per_token
    return round(prompt_cost + completion_cost, 10)


def calculate_image_cost(model: str, size: str = "1024x1024", n: int = 1) -> float:
    """Calculate cost for image generation.

    Args:
        model: Image model name (e.g. ``"dall-e-3"``).
        size: Image size string.
        n: Number of images.

    Returns:
        Total cost in USD.
    """
    info = get_model_info(model)
    if not info:
        return 0.0

    cost_map = info.get("input_cost_per_image")
    if isinstance(cost_map, dict):
        per_image: float = float(cost_map.get(size, 0.0))
        return round(per_image * n, 10)

    return 0.0


def calculate_embedding_cost(model: str, total_tokens: int) -> float:
    """Calculate cost for an embedding request.

    Args:
        model: Embedding model name.
        total_tokens: Total tokens in the input.

    Returns:
        Total cost in USD.
    """
    info = get_model_info(model)
    if not info:
        return 0.0

    input_cost = info.get("input_cost_per_token")
    if input_cost is None:
        return 0.0

    return round(total_tokens * float(input_cost), 10)
