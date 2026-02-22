"""Tests for the exception hierarchy (Task 1.5).

Validates OpenAI error format serialization, status codes, inheritance,
and special exception attributes.
"""

from __future__ import annotations

from typing import ClassVar

from routerbot.core.exceptions import (
    AuthenticationError,
    BadRequestError,
    BudgetExceededError,
    ConfigurationError,
    ContentPolicyError,
    ModelNotFoundError,
    NotFoundError,
    PermissionDeniedError,
    ProviderError,
    RateLimitError,
    RouterBotError,
    ServiceUnavailableError,
    TimeoutError,  # noqa: A004
)

# ===================================================================
# Base exception
# ===================================================================


class TestRouterBotError:
    """RouterBotError base class."""

    def test_default_values(self) -> None:
        err = RouterBotError()
        assert err.message == "An internal error occurred."
        assert err.status_code == 500
        assert err.type == "internal_error"
        assert err.param is None
        assert err.code is None

    def test_custom_values(self) -> None:
        err = RouterBotError(
            "Custom message",
            status_code=418,
            type="teapot_error",
            param="brew",
            code="short_and_stout",
        )
        assert err.message == "Custom message"
        assert err.status_code == 418
        assert err.type == "teapot_error"
        assert err.param == "brew"
        assert err.code == "short_and_stout"

    def test_to_openai_error(self) -> None:
        err = RouterBotError("Something went wrong", param="model", code="server_error")
        result = err.to_openai_error()
        assert result == {
            "error": {
                "message": "Something went wrong",
                "type": "internal_error",
                "param": "model",
                "code": "server_error",
            }
        }

    def test_str_is_message(self) -> None:
        err = RouterBotError("hello")
        assert str(err) == "hello"

    def test_repr(self) -> None:
        err = RouterBotError("test")
        assert "RouterBotError" in repr(err)
        assert "500" in repr(err)

    def test_is_exception(self) -> None:
        err = RouterBotError("test")
        assert isinstance(err, Exception)


# ===================================================================
# 4xx Client Errors
# ===================================================================


class TestBadRequestError:
    """BadRequestError (400)."""

    def test_defaults(self) -> None:
        err = BadRequestError("Invalid JSON body")
        assert err.status_code == 400
        assert err.type == "invalid_request_error"
        assert err.code == "bad_request"

    def test_serialization(self) -> None:
        err = BadRequestError("Missing 'messages' field", param="messages")
        result = err.to_openai_error()
        assert result["error"]["message"] == "Missing 'messages' field"
        assert result["error"]["param"] == "messages"

    def test_inheritance(self) -> None:
        err = BadRequestError("test")
        assert isinstance(err, RouterBotError)


class TestAuthenticationError:
    """AuthenticationError (401)."""

    def test_defaults(self) -> None:
        err = AuthenticationError("Invalid API key")
        assert err.status_code == 401
        assert err.type == "authentication_error"
        assert err.code == "invalid_api_key"

    def test_serialization(self) -> None:
        result = AuthenticationError("Bad key").to_openai_error()
        assert result["error"]["type"] == "authentication_error"


class TestPermissionDeniedError:
    """PermissionDeniedError (403)."""

    def test_defaults(self) -> None:
        err = PermissionDeniedError("Not allowed")
        assert err.status_code == 403
        assert err.type == "permission_error"
        assert err.code == "permission_denied"


class TestNotFoundError:
    """NotFoundError (404)."""

    def test_defaults(self) -> None:
        err = NotFoundError("Resource not found")
        assert err.status_code == 404
        assert err.type == "not_found_error"
        assert err.code == "not_found"


class TestModelNotFoundError:
    """ModelNotFoundError (404) — specialized."""

    def test_model_name_in_message(self) -> None:
        err = ModelNotFoundError("gpt-5-ultra")
        assert "gpt-5-ultra" in err.message
        assert err.status_code == 404
        assert err.code == "model_not_found"
        assert err.model == "gpt-5-ultra"

    def test_inherits_not_found(self) -> None:
        err = ModelNotFoundError("test-model")
        assert isinstance(err, NotFoundError)
        assert isinstance(err, RouterBotError)

    def test_serialization(self) -> None:
        result = ModelNotFoundError("gpt-4o").to_openai_error()
        assert "gpt-4o" in result["error"]["message"]
        assert result["error"]["code"] == "model_not_found"


class TestTimeoutError:
    """TimeoutError (408)."""

    def test_defaults(self) -> None:
        err = TimeoutError("Request timed out")
        assert err.status_code == 408
        assert err.type == "timeout_error"
        assert err.code == "request_timeout"


class TestRateLimitError:
    """RateLimitError (429)."""

    def test_defaults(self) -> None:
        err = RateLimitError()
        assert err.status_code == 429
        assert err.type == "rate_limit_error"
        assert err.code == "rate_limit_exceeded"
        assert err.retry_after is None

    def test_with_retry_after(self) -> None:
        err = RateLimitError("Too many requests", retry_after=30.0)
        assert err.retry_after == 30.0

    def test_serialization(self) -> None:
        result = RateLimitError().to_openai_error()
        assert result["error"]["code"] == "rate_limit_exceeded"


class TestBudgetExceededError:
    """BudgetExceededError (429)."""

    def test_defaults(self) -> None:
        err = BudgetExceededError()
        assert err.status_code == 429
        assert err.code == "budget_exceeded"
        assert err.budget_limit is None
        assert err.current_spend is None

    def test_with_amounts(self) -> None:
        err = BudgetExceededError(
            "Over budget",
            budget_limit=100.0,
            current_spend=105.50,
        )
        assert err.budget_limit == 100.0
        assert err.current_spend == 105.50

    def test_inherits_rate_limit(self) -> None:
        err = BudgetExceededError()
        assert isinstance(err, RateLimitError)
        assert isinstance(err, RouterBotError)


class TestContentPolicyError:
    """ContentPolicyError (400)."""

    def test_defaults(self) -> None:
        err = ContentPolicyError()
        assert err.status_code == 400
        assert err.code == "content_policy_violation"
        assert "content policy" in err.message.lower()

    def test_inherits_bad_request(self) -> None:
        err = ContentPolicyError()
        assert isinstance(err, BadRequestError)


# ===================================================================
# 5xx Server Errors
# ===================================================================


class TestConfigurationError:
    """ConfigurationError (500)."""

    def test_defaults(self) -> None:
        err = ConfigurationError("Missing database_url")
        assert err.status_code == 500
        assert err.type == "configuration_error"
        assert err.code == "configuration_error"


class TestProviderError:
    """ProviderError (500) — wraps upstream errors."""

    def test_defaults(self) -> None:
        err = ProviderError("OpenAI API error")
        assert err.status_code == 500
        assert err.type == "provider_error"
        assert err.provider is None
        assert err.model is None
        assert err.original_error is None

    def test_with_provider_context(self) -> None:
        original = ValueError("Connection refused")
        err = ProviderError(
            "Upstream failure",
            provider="openai",
            model="gpt-4o",
            original_error=original,
            original_status_code=502,
        )
        assert err.provider == "openai"
        assert err.model == "gpt-4o"
        assert err.original_error is original
        assert err.original_status_code == 502
        assert err.__cause__ is original

    def test_serialization_includes_provider(self) -> None:
        err = ProviderError("Fail", provider="anthropic", model="claude-3")
        result = err.to_openai_error()
        assert result["error"]["provider"] == "anthropic"
        assert result["error"]["model"] == "claude-3"
        assert result["error"]["code"] == "provider_error"

    def test_serialization_without_provider(self) -> None:
        err = ProviderError("Generic fail")
        result = err.to_openai_error()
        assert "provider" not in result["error"]

    def test_inherits_router_bot_error(self) -> None:
        err = ProviderError()
        assert isinstance(err, RouterBotError)


class TestServiceUnavailableError:
    """ServiceUnavailableError (503)."""

    def test_defaults(self) -> None:
        err = ServiceUnavailableError()
        assert err.status_code == 503
        assert err.type == "service_unavailable_error"
        assert err.code == "service_unavailable"
        assert "unavailable" in err.message.lower()

    def test_custom_message(self) -> None:
        err = ServiceUnavailableError("All OpenAI endpoints are down")
        assert err.message == "All OpenAI endpoints are down"


# ===================================================================
# Cross-cutting tests
# ===================================================================


class TestAllExceptions:
    """Verify all exception types serialize correctly."""

    ALL_EXCEPTIONS: ClassVar[list[RouterBotError]] = [
        RouterBotError("base"),
        BadRequestError("bad"),
        AuthenticationError("auth"),
        PermissionDeniedError("perm"),
        NotFoundError("nf"),
        ModelNotFoundError("gpt-4o"),
        TimeoutError("timeout"),
        RateLimitError("rate"),
        BudgetExceededError("budget"),
        ContentPolicyError("policy"),
        ConfigurationError("config"),
        ProviderError("provider"),
        ServiceUnavailableError("unavailable"),
    ]

    def test_all_have_openai_error_format(self) -> None:
        for exc in self.ALL_EXCEPTIONS:
            result = exc.to_openai_error()
            assert "error" in result
            error = result["error"]
            assert "message" in error
            assert "type" in error
            assert "param" in error
            assert "code" in error

    def test_all_are_catchable_as_base(self) -> None:
        for exc in self.ALL_EXCEPTIONS:
            assert isinstance(exc, RouterBotError)
            assert isinstance(exc, Exception)

    def test_status_codes_in_valid_range(self) -> None:
        for exc in self.ALL_EXCEPTIONS:
            assert 400 <= exc.status_code <= 599, f"{exc.__class__.__name__} has invalid status_code"

    def test_all_have_type_string(self) -> None:
        for exc in self.ALL_EXCEPTIONS:
            assert isinstance(exc.type, str)
            assert len(exc.type) > 0
