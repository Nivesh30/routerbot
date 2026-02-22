"""Model registry — loads and serves model metadata from ``model_prices.json``.

Provides a lookup table for model pricing, context windows, capabilities,
and tokenizer information. Supports adding custom models at runtime via
configuration overrides.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MODEL_REGISTRY: dict[str, dict[str, Any]] = {}
_LOADED = False


def _load_registry() -> None:
    """Load model_prices.json into the in-memory registry."""
    global _LOADED
    if _LOADED:
        return

    prices_path = Path(__file__).parent / "model_prices.json"
    if not prices_path.exists():
        logger.warning("model_prices.json not found at %s", prices_path)
        _LOADED = True
        return

    with prices_path.open() as f:
        data = json.load(f)

    for key, value in data.items():
        if key.startswith("_"):
            continue  # skip metadata keys like _comment
        if isinstance(value, dict):
            _MODEL_REGISTRY[key] = value

    _LOADED = True
    logger.debug("Loaded %d models from model_prices.json", len(_MODEL_REGISTRY))


def get_model_info(model: str) -> dict[str, Any] | None:
    """Look up model metadata by name.

    Tries exact match first, then prefix matching to handle versioned
    model names like ``gpt-4o-2024-08-06``.

    Args:
        model: Model name to look up.

    Returns:
        Dict of model metadata, or ``None`` if not found.
    """
    _load_registry()

    # Strip provider prefix if present (e.g., "openai/gpt-4o" → "gpt-4o")
    if "/" in model:
        model = model.split("/", 1)[1]

    # Exact match
    if model in _MODEL_REGISTRY:
        return _MODEL_REGISTRY[model]

    # Prefix match (e.g., "gpt-4o-2024-08-06" matches "gpt-4o")
    for key in sorted(_MODEL_REGISTRY.keys(), key=len, reverse=True):
        if model.startswith(key):
            return _MODEL_REGISTRY[key]

    return None


def get_all_models() -> dict[str, dict[str, Any]]:
    """Return a copy of the full model registry."""
    _load_registry()
    return dict(_MODEL_REGISTRY)


def register_custom_model(model_name: str, info: dict[str, Any]) -> None:
    """Add or update a custom model in the registry.

    Args:
        model_name: Model name to register.
        info: Model metadata dict (pricing, context window, etc.).
    """
    _load_registry()
    _MODEL_REGISTRY[model_name] = info
    logger.info("Registered custom model: %s", model_name)


def reset_registry() -> None:
    """Reset the registry (for testing)."""
    global _LOADED
    _MODEL_REGISTRY.clear()
    _LOADED = False
