"""Tests for structured logging and key hashing utilities (Task 1.7)."""

from __future__ import annotations

import logging
import re

import structlog

from routerbot.core.logging import (
    _REDACTED,
    _looks_like_key,
    _mask_key_value,
    _redact_sensitive,
    bind_request_context,
    clear_request_context,
    get_logger,
    setup_logging,
)
from routerbot.utils.hashing import generate_key, generate_short_id, hash_key, mask_key

# ===================================================================
# Logging setup
# ===================================================================


class TestSetupLogging:
    """setup_logging function."""

    def setup_method(self) -> None:
        """Reset root logger before each test."""
        root = logging.getLogger()
        root.handlers.clear()

    def test_json_format(self, capsys: object) -> None:
        setup_logging(level="DEBUG", log_format="json", force=True)
        logger = get_logger("test.json")
        logger.info("hello", key="value")
        # Logger is configured — just verify no exception

    def test_text_format(self) -> None:
        setup_logging(level="INFO", log_format="text", force=True)
        logger = get_logger("test.text")
        logger.info("hello text mode")

    def test_idempotent_without_force(self) -> None:
        setup_logging(level="INFO", log_format="json", force=True)
        root = logging.getLogger()
        handler_count = len(root.handlers)
        # Calling again without force should not add handlers
        setup_logging(level="INFO", log_format="json")
        assert len(root.handlers) == handler_count

    def test_force_reconfigure(self) -> None:
        setup_logging(level="INFO", log_format="json", force=True)
        setup_logging(level="DEBUG", log_format="text", force=True)
        root = logging.getLogger()
        assert root.level == logging.DEBUG


# ===================================================================
# Sensitive data redaction
# ===================================================================


class TestRedaction:
    """Sensitive key redaction in logs."""

    def test_api_key_redacted(self) -> None:
        event = {"event": "request", "api_key": "sk-secret123456"}
        result = _redact_sensitive(None, "", event)
        assert result["api_key"] == _REDACTED

    def test_authorization_redacted(self) -> None:
        event = {"event": "auth", "authorization": "Bearer sk-abc123"}
        result = _redact_sensitive(None, "", event)
        assert result["authorization"] == _REDACTED

    def test_password_redacted(self) -> None:
        event = {"event": "connect", "password": "mypassword"}
        result = _redact_sensitive(None, "", event)
        assert result["password"] == _REDACTED

    def test_database_url_redacted(self) -> None:
        event = {"event": "init", "database_url": "postgres://user:pass@host/db"}
        result = _redact_sensitive(None, "", event)
        assert result["database_url"] == _REDACTED

    def test_non_sensitive_preserved(self) -> None:
        event = {"event": "request", "model": "gpt-4o", "tokens": 100}
        result = _redact_sensitive(None, "", event)
        assert result["model"] == "gpt-4o"
        assert result["tokens"] == 100

    def test_key_like_value_masked(self) -> None:
        event = {"event": "test", "some_field": "sk-proj-abc123def456ghi789jkl012mno"}
        result = _redact_sensitive(None, "", event)
        # Should be masked (first 8...last 4)
        assert result["some_field"] != "sk-proj-abc123def456ghi789jkl012mno"
        assert "..." in result["some_field"]

    def test_short_value_not_masked(self) -> None:
        event = {"event": "test", "label": "hello"}
        result = _redact_sensitive(None, "", event)
        assert result["label"] == "hello"


class TestLooksLikeKey:
    """_looks_like_key heuristic."""

    def test_openai_key(self) -> None:
        assert _looks_like_key("sk-proj-abc123def456ghi789jkl012mno") is True

    def test_routerbot_key(self) -> None:
        assert _looks_like_key("rb-" + "a" * 64) is True

    def test_bearer_token(self) -> None:
        assert _looks_like_key("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9") is True

    def test_normal_string(self) -> None:
        assert _looks_like_key("hello world") is False

    def test_short_key(self) -> None:
        assert _looks_like_key("sk-abc") is False  # too short


class TestMaskKeyValue:
    """_mask_key_value function."""

    def test_long_key(self) -> None:
        result = _mask_key_value("sk-proj-abc123def456ghi789jkl012mno")
        assert result == "sk-proj-...2mno"

    def test_short_key(self) -> None:
        result = _mask_key_value("sk-short")
        assert result == _REDACTED


# ===================================================================
# Request context
# ===================================================================


class TestRequestContext:
    """Request-scoped context binding."""

    def setup_method(self) -> None:
        clear_request_context()

    def test_bind_and_clear(self) -> None:
        bind_request_context(request_id="req-123", model="gpt-4o")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["request_id"] == "req-123"
        assert ctx["model"] == "gpt-4o"

        clear_request_context()
        ctx = structlog.contextvars.get_contextvars()
        assert "request_id" not in ctx

    def test_partial_context(self) -> None:
        bind_request_context(request_id="req-456")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["request_id"] == "req-456"
        assert "user_id" not in ctx

    def test_extra_kwargs(self) -> None:
        bind_request_context(request_id="req-789", custom="value")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["custom"] == "value"


# ===================================================================
# get_logger
# ===================================================================


class TestGetLogger:
    """get_logger function."""

    def test_returns_bound_logger(self) -> None:
        setup_logging(force=True)
        logger = get_logger("test")
        assert logger is not None

    def test_with_initial_context(self) -> None:
        setup_logging(force=True)
        logger = get_logger("test", service="routerbot")
        # The logger should have the context bound — we just verify no error
        assert logger is not None


# ===================================================================
# Key hashing utilities
# ===================================================================


class TestHashKey:
    """hash_key function."""

    def test_deterministic(self) -> None:
        h1 = hash_key("my-api-key")
        h2 = hash_key("my-api-key")
        assert h1 == h2

    def test_different_keys_different_hashes(self) -> None:
        h1 = hash_key("key-a")
        h2 = hash_key("key-b")
        assert h1 != h2

    def test_hex_format(self) -> None:
        h = hash_key("test")
        assert len(h) == 64  # SHA-256 = 64 hex chars
        assert all(c in "0123456789abcdef" for c in h)


class TestGenerateKey:
    """generate_key function."""

    def test_default_prefix(self) -> None:
        key = generate_key()
        assert key.startswith("rb-")
        assert len(key) == 3 + 64  # "rb-" + 64 hex chars

    def test_custom_prefix(self) -> None:
        key = generate_key("sk")
        assert key.startswith("sk-")

    def test_unique(self) -> None:
        keys = {generate_key() for _ in range(100)}
        assert len(keys) == 100  # all unique


class TestGenerateShortId:
    """generate_short_id function."""

    def test_default_length(self) -> None:
        sid = generate_short_id()
        assert len(sid) == 12

    def test_custom_length(self) -> None:
        sid = generate_short_id(20)
        assert len(sid) == 20

    def test_alphanumeric(self) -> None:
        sid = generate_short_id()
        assert re.match(r"^[a-z0-9]+$", sid)


class TestMaskKey:
    """mask_key function."""

    def test_long_key(self) -> None:
        result = mask_key("rb-abc123def456ghi789jkl012mno345pqr")
        assert result == "rb-abc12...5pqr"

    def test_short_key(self) -> None:
        result = mask_key("short")
        assert result == "***"

    def test_medium_key(self) -> None:
        result = mask_key("exactly12chr")
        assert result == "***"

    def test_just_over_threshold(self) -> None:
        result = mask_key("1234567890123")  # 13 chars
        assert result == "12345678...0123"


# ===================================================================
# Integration: API keys never appear in structured logs
# ===================================================================


class TestApiKeysNeverInLogs:
    """Verify that API keys are redacted in log output."""

    def setup_method(self) -> None:
        root = logging.getLogger()
        root.handlers.clear()

    def test_api_key_not_in_json_output(self, capsys: object) -> None:
        """Log an event with an API key and verify it's not in output."""
        setup_logging(level="DEBUG", log_format="json", force=True)
        logger = get_logger("security_test")

        # Capture stderr output
        import io

        captured = io.StringIO()
        handler = logging.StreamHandler(captured)
        handler.setFormatter(logging.getLogger().handlers[0].formatter)
        logging.getLogger().addHandler(handler)

        logger.info("auth_check", api_key="sk-my-super-secret-key-12345678")

        output = captured.getvalue()
        # The raw key must NOT appear in the output
        assert "sk-my-super-secret-key-12345678" not in output
        # The redaction marker should appear
        assert _REDACTED in output
