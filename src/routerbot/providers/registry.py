"""Provider registry — maps provider names to provider classes.

The registry is responsible for:
- Registering built-in and custom provider classes
- Resolving ``"provider/model"`` strings to provider instances
- Supporting OpenAI-compatible providers via configuration (no code needed)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from routerbot.core.enums import Provider
from routerbot.core.exceptions import ConfigurationError, ModelNotFoundError

if TYPE_CHECKING:
    from routerbot.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider class registry
# ---------------------------------------------------------------------------

# Maps provider name (str) → factory callable
_PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {}

# Cache of instantiated providers keyed by (provider_name, api_base, api_key_hash)
_PROVIDER_INSTANCES: dict[tuple[str, str, str], BaseProvider] = {}

# Maps provider names to their default API base URLs
_DEFAULT_API_BASES: dict[str, str] = {
    Provider.OPENAI: "https://api.openai.com/v1",
    Provider.ANTHROPIC: "https://api.anthropic.com",
    Provider.GROQ: "https://api.groq.com/openai/v1",
    Provider.MISTRAL: "https://api.mistral.ai/v1",
    Provider.COHERE: "https://api.cohere.com/v2",
    Provider.DEEPSEEK: "https://api.deepseek.com/v1",
    Provider.OLLAMA: "http://localhost:11434",
    Provider.TOGETHER: "https://api.together.xyz/v1",
    Provider.FIREWORKS: "https://api.fireworks.ai/inference/v1",
}


def register_provider(name: str, provider_class: type[BaseProvider]) -> None:
    """Register a provider class.

    Parameters
    ----------
    name:
        The canonical provider name (e.g. ``"openai"``).
    provider_class:
        The provider class to register. Must subclass :class:`BaseProvider`.
    """
    from routerbot.providers.base import BaseProvider as _BaseProvider

    if not (isinstance(provider_class, type) and issubclass(provider_class, _BaseProvider)):
        msg = f"Provider class must subclass BaseProvider, got {provider_class}"
        raise TypeError(msg)

    _PROVIDER_CLASSES[name] = provider_class
    logger.debug("Registered provider %s → %s", name, provider_class.__name__)


def _discover_builtin_providers() -> None:
    """Import built-in provider modules to trigger registration.

    This is called lazily on first ``get_provider`` call.
    """
    # Import each built-in provider module. Each module registers itself
    # via ``register_provider`` at import time.
    _provider_modules = [
        "routerbot.providers.openai_compat",
    ]
    for mod_name in _provider_modules:
        try:
            __import__(mod_name)
        except ImportError:
            logger.debug("Optional provider module %s not available", mod_name)


_discovered = False


def _ensure_discovered() -> None:
    global _discovered
    if not _discovered:
        _discover_builtin_providers()
        _discovered = True


def parse_model_string(model_string: str) -> tuple[str, str]:
    """Parse a ``"provider/model"`` string into ``(provider_name, model_name)``.

    If no ``/`` is present, the provider is inferred as ``"openai"`` by default.

    Examples
    --------
    >>> parse_model_string("openai/gpt-4o")
    ('openai', 'gpt-4o')
    >>> parse_model_string("anthropic/claude-sonnet-4-20250514")
    ('anthropic', 'claude-sonnet-4-20250514')
    >>> parse_model_string("gpt-4o")
    ('openai', 'gpt-4o')
    """
    if "/" in model_string:
        provider, _, model = model_string.partition("/")
        return provider.lower().strip(), model.strip()
    return "openai", model_string.strip()


def get_provider_class(provider_name: str) -> type[BaseProvider]:
    """Look up the provider class by name.

    Falls back to :class:`OpenAICompatibleProvider` for unknown providers.

    Raises
    ------
    ModelNotFoundError
        If the provider is not registered and no compatible fallback exists.
    """
    _ensure_discovered()

    name = provider_name.lower()
    if name in _PROVIDER_CLASSES:
        return _PROVIDER_CLASSES[name]

    # Try the OpenAI-compatible fallback
    if "openai_compat" in _PROVIDER_CLASSES:
        return _PROVIDER_CLASSES["openai_compat"]

    raise ModelNotFoundError(model=provider_name)


def get_provider(
    model_string: str,
    *,
    api_key: str | None = None,
    api_base: str | None = None,
    **kwargs: Any,
) -> BaseProvider:
    """Resolve a ``"provider/model"`` string and return a configured provider instance.

    Provider instances are cached by ``(provider_name, api_base, api_key_hash)``
    so the same configuration always returns the same instance.

    Parameters
    ----------
    model_string:
        A string like ``"openai/gpt-4o"`` or ``"anthropic/claude-sonnet-4-20250514"``.
    api_key:
        Override API key (otherwise from config/env).
    api_base:
        Override API base URL.
    **kwargs:
        Extra provider-specific parameters.

    Returns
    -------
    BaseProvider
        A configured provider instance.
    """
    provider_name, _model = parse_model_string(model_string)
    cls = get_provider_class(provider_name)

    # Determine effective api_base
    effective_base = api_base or _DEFAULT_API_BASES.get(provider_name, "")

    # Cache key uses a hash of the api_key to avoid storing secrets in memory as keys
    import hashlib

    key_hash = hashlib.sha256((api_key or "").encode()).hexdigest()[:16]
    cache_key = (provider_name, effective_base, key_hash)

    if cache_key in _PROVIDER_INSTANCES:
        return _PROVIDER_INSTANCES[cache_key]

    try:
        instance = cls(
            api_key=api_key,
            api_base=effective_base,
            **kwargs,
        )
    except Exception as exc:
        msg = f"Failed to create provider '{provider_name}': {exc}"
        raise ConfigurationError(message=msg) from exc

    _PROVIDER_INSTANCES[cache_key] = instance
    return instance


def list_providers() -> list[str]:
    """Return the names of all registered providers."""
    _ensure_discovered()
    return sorted(_PROVIDER_CLASSES.keys())


async def close_all_providers() -> None:
    """Gracefully close all cached provider instances."""
    for instance in _PROVIDER_INSTANCES.values():
        try:
            await instance.close()
        except Exception:
            logger.warning("Error closing provider %s", instance.provider_name, exc_info=True)
    _PROVIDER_INSTANCES.clear()


def reset_registry() -> None:
    """Reset the registry to its initial state (for testing)."""
    global _discovered
    _PROVIDER_CLASSES.clear()
    _PROVIDER_INSTANCES.clear()
    _discovered = False
