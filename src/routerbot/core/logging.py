"""Structured logging configuration for RouterBot.

Uses ``structlog`` for structured JSON logging in production and
human-readable coloured output in development. Provides request-scoped
context binding and automatic redaction of sensitive values.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import MutableMapping

# ---------------------------------------------------------------------------
# Sensitive key patterns — values matching these keys are redacted in logs
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "api-key",
        "authorization",
        "master_key",
        "master-key",
        "password",
        "secret",
        "token",
        "x-api-key",
        "database_url",
        "redis_url",
    }
)

_REDACTED = "***REDACTED***"


def _redact_sensitive(
    _logger: Any,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Structlog processor that redacts sensitive values from log events."""
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = _REDACTED
        elif isinstance(event_dict[key], str) and _looks_like_key(event_dict[key]):
            event_dict[key] = _mask_key_value(event_dict[key])
    return event_dict


def _looks_like_key(value: str) -> bool:
    """Heuristic: strings starting with sk-, rb-, key- are likely API keys."""
    prefixes = ("sk-", "rb-", "key-", "Bearer ")
    return any(value.startswith(p) for p in prefixes) and len(value) > 20


def _mask_key_value(value: str) -> str:
    """Mask a key-like value, showing only first 8 and last 4 characters."""
    if len(value) <= 16:
        return _REDACTED
    return f"{value[:8]}...{value[-4:]}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def setup_logging(
    *,
    level: str = "INFO",
    log_format: str = "json",
    force: bool = False,
) -> None:
    """Configure structlog and stdlib logging.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: ``"json"`` for production or ``"text"`` for development.
        force: Re-configure even if already set up.
    """
    if _is_configured() and not force:
        return

    log_level = getattr(logging, level.upper(), logging.INFO)

    # Shared processors run before the final renderer
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        _redact_sensitive,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if log_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure stdlib root logger to use structlog formatting
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)


def get_logger(name: str | None = None, **initial_context: Any) -> structlog.stdlib.BoundLogger:
    """Get a structlog bound logger with optional initial context.

    Args:
        name: Logger name (typically ``__name__``).
        **initial_context: Key-value pairs bound to every log entry.

    Returns:
        A bound structlog logger.
    """
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    if initial_context:
        logger = logger.bind(**initial_context)
    return logger


def bind_request_context(
    *,
    request_id: str | None = None,
    user_id: str | None = None,
    team_id: str | None = None,
    model: str | None = None,
    **extra: Any,
) -> None:
    """Bind request-scoped context variables to all subsequent log entries.

    Uses ``structlog.contextvars`` so context flows through async code.
    Call ``clear_request_context()`` at the end of each request.
    """
    ctx: dict[str, Any] = {}
    if request_id is not None:
        ctx["request_id"] = request_id
    if user_id is not None:
        ctx["user_id"] = user_id
    if team_id is not None:
        ctx["team_id"] = team_id
    if model is not None:
        ctx["model"] = model
    ctx.update(extra)
    structlog.contextvars.bind_contextvars(**ctx)


def clear_request_context() -> None:
    """Clear all request-scoped context variables."""
    structlog.contextvars.clear_contextvars()


def _is_configured() -> bool:
    """Check if structlog has already been configured."""
    root = logging.getLogger()
    return any(isinstance(h.formatter, structlog.stdlib.ProcessorFormatter) for h in root.handlers)
