"""Configuration loading and validation for RouterBot.

Supports layered configuration from multiple sources:
1. Default values (defined in config models)
2. YAML config file (routerbot_config.yaml)
3. Environment variable overrides (ROUTERBOT_ prefix)

Secret references like ``os.environ/VAR_NAME`` are resolved at load time.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from routerbot.core.config_models import RouterBotConfig

# Pattern to match os.environ/VAR_NAME references in config values
_ENV_REF_PATTERN = re.compile(r"^os\.environ/(\w+)$")

# Default config file paths to search (in order)
_DEFAULT_CONFIG_PATHS = [
    "routerbot_config.yaml",
    "routerbot_config.yml",
    "config.yaml",
    "config.yml",
]


def _resolve_env_refs(data: Any) -> Any:
    """Recursively resolve ``os.environ/VAR_NAME`` references in config values.

    Args:
        data: Config data (dict, list, or scalar).

    Returns:
        Data with all environment variable references resolved.

    Raises:
        ValueError: If a referenced environment variable is not set.
    """
    if isinstance(data, dict):
        return {key: _resolve_env_refs(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_resolve_env_refs(item) for item in data]
    if isinstance(data, str):
        match = _ENV_REF_PATTERN.match(data)
        if match:
            var_name = match.group(1)
            value = os.environ.get(var_name)
            if value is None:
                msg = f"Environment variable '{var_name}' referenced in config is not set"
                raise ValueError(msg)
            return value
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries. Override values take precedence.

    Args:
        base: Base dictionary.
        override: Override dictionary (values take precedence).

    Returns:
        Merged dictionary.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides with ROUTERBOT_ prefix.

    Environment variables are mapped to config paths using double underscores
    as separators. For example::

        ROUTERBOT_GENERAL_SETTINGS__PORT=8080

    maps to ``general_settings.port = 8080``.

    Args:
        data: Current config data.

    Returns:
        Config data with environment overrides applied.
    """
    prefix = "ROUTERBOT_"
    result = data.copy()

    for env_key, env_value in os.environ.items():
        if not env_key.startswith(prefix):
            continue

        # Strip prefix and convert to lowercase path
        config_path = env_key[len(prefix) :].lower()
        parts = config_path.split("__")

        # Navigate/create nested dict path
        current = result
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            if isinstance(current[part], dict):
                current = current[part]
            else:
                break
        else:
            # Set the value, attempting type coercion
            final_key = parts[-1]
            current[final_key] = _coerce_value(env_value)

    return result


def _coerce_value(value: str) -> Any:
    """Coerce a string environment variable value to the appropriate Python type.

    Args:
        value: String value from environment.

    Returns:
        Coerced value (int, float, bool, or str).
    """
    # Booleans
    if value.lower() in ("true", "yes", "1", "on"):
        return True
    if value.lower() in ("false", "no", "0", "off"):
        return False

    # Integers
    try:
        return int(value)
    except ValueError:
        pass

    # Floats
    try:
        return float(value)
    except ValueError:
        pass

    return value


def load_config(
    config_path: str | Path | None = None,
    config_data: dict[str, Any] | None = None,
) -> RouterBotConfig:
    """Load and validate RouterBot configuration.

    Configuration is loaded from the following sources in order of precedence
    (later sources override earlier ones):

    1. Default values from config models
    2. YAML config file
    3. Environment variable overrides (``ROUTERBOT_`` prefix)

    **Secret resolution:** Values matching ``os.environ/VAR_NAME`` are resolved
    from the environment at load time.

    Args:
        config_path: Explicit path to YAML config file. If None, searches
            default paths.
        config_data: Pre-loaded config dict (for testing). Skips file loading
            if provided.

    Returns:
        Validated RouterBotConfig instance.

    Raises:
        FileNotFoundError: If an explicit config_path is provided but does not exist.
        ValueError: If config validation fails or env references are unresolvable.
    """
    data: dict[str, Any] = {}

    if config_data is not None:
        # Use provided data directly (for testing)
        data = config_data
    elif config_path is not None:
        # Load from explicit path
        path = Path(config_path)
        if not path.exists():
            msg = f"Config file not found: {path}"
            raise FileNotFoundError(msg)
        data = _load_yaml(path)
    else:
        # Search default paths
        for default_path in _DEFAULT_CONFIG_PATHS:
            path = Path(default_path)
            if path.exists():
                data = _load_yaml(path)
                break

    # Apply environment variable overrides
    data = _apply_env_overrides(data)

    # Resolve os.environ/ references
    data = _resolve_env_refs(data)

    # Set environment variables from config
    env_vars = data.get("environment_variables", {})
    for key, value in env_vars.items():
        os.environ[key] = str(value)

    # Validate and return
    return RouterBotConfig.model_validate(data)


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dict.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed YAML as a dictionary.
    """
    with open(path, encoding="utf-8") as f:
        content = yaml.safe_load(f)

    if content is None:
        return {}
    if not isinstance(content, dict):
        msg = f"Config file must be a YAML mapping, got {type(content).__name__}"
        raise ValueError(msg)

    return content


# Module-level singleton (lazily initialized)
_config: RouterBotConfig | None = None


def get_config() -> RouterBotConfig:
    """Get the global RouterBot configuration singleton.

    Loads config on first access. Subsequent calls return the cached instance.

    Returns:
        The global RouterBotConfig instance.
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset the global config singleton. Primarily for testing."""
    global _config
    _config = None
