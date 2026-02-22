"""Exception hierarchy for RouterBot.

All exceptions map to the OpenAI error response format::

    {
        "error": {
            "message": "...",
            "type": "...",
            "param": null,
            "code": "..."
        }
    }

Every exception carries an HTTP ``status_code`` so the proxy layer can
return the correct status without inspecting exception types.
"""

from __future__ import annotations

from typing import Any


class RouterBotError(Exception):
    """Base exception for all RouterBot errors.

    Attributes:
        message: Human-readable error description.
        status_code: HTTP status code to return.
        type: OpenAI error type string.
        param: Optional parameter that caused the error.
        code: Optional machine-readable error code.
    """

    status_code: int = 500
    type: str = "internal_error"
    code: str | None = None

    def __init__(
        self,
        message: str = "An internal error occurred.",
        *,
        status_code: int | None = None,
        type: str | None = None,  # noqa: A002
        param: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if type is not None:
            self.type = type
        self.param = param
        if code is not None:
            self.code = code

    def to_openai_error(self) -> dict[str, Any]:
        """Serialize to OpenAI-compatible error response body."""
        return {
            "error": {
                "message": self.message,
                "type": self.type,
                "param": self.param,
                "code": self.code,
            }
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, status_code={self.status_code})"


# ---------------------------------------------------------------------------
# 4xx Client Errors
# ---------------------------------------------------------------------------


class BadRequestError(RouterBotError):
    """400 — The request was malformed or invalid."""

    status_code = 400
    type = "invalid_request_error"
    code = "bad_request"


class AuthenticationError(RouterBotError):
    """401 — Missing or invalid API key."""

    status_code = 401
    type = "authentication_error"
    code = "invalid_api_key"


class PermissionDeniedError(RouterBotError):
    """403 — The API key doesn't have permission for this action."""

    status_code = 403
    type = "permission_error"
    code = "permission_denied"


class NotFoundError(RouterBotError):
    """404 — The requested resource was not found."""

    status_code = 404
    type = "not_found_error"
    code = "not_found"


class ModelNotFoundError(NotFoundError):
    """404 — The requested model is not configured in RouterBot."""

    code = "model_not_found"

    def __init__(self, model: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Model '{model}' is not available. Check your RouterBot model_list configuration.",
            **kwargs,
        )
        self.model = model


class TimeoutError(RouterBotError):  # noqa: A001
    """408 — The request timed out."""

    status_code = 408
    type = "timeout_error"
    code = "request_timeout"


class RateLimitError(RouterBotError):
    """429 — Rate limit exceeded (either RouterBot or upstream provider)."""

    status_code = 429
    type = "rate_limit_error"
    code = "rate_limit_exceeded"

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please retry after a brief wait.",
        *,
        retry_after: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class BudgetExceededError(RateLimitError):
    """429 — The spending budget for a key or team has been exhausted."""

    code = "budget_exceeded"

    def __init__(
        self,
        message: str = "Budget limit exceeded. Contact your administrator.",
        *,
        budget_limit: float | None = None,
        current_spend: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.budget_limit = budget_limit
        self.current_spend = current_spend


class ContentPolicyError(BadRequestError):
    """400 — The request was rejected due to content policy violation."""

    code = "content_policy_violation"

    def __init__(
        self,
        message: str = "Your request was rejected as a result of our content policy.",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)


# ---------------------------------------------------------------------------
# 5xx Server Errors
# ---------------------------------------------------------------------------


class ConfigurationError(RouterBotError):
    """500 — RouterBot configuration is invalid or missing."""

    status_code = 500
    type = "configuration_error"
    code = "configuration_error"


class ProviderError(RouterBotError):
    """500 — An upstream provider returned an error.

    Wraps the original exception so callers can inspect both the
    RouterBot-level error and the underlying provider failure.
    """

    status_code = 500
    type = "provider_error"
    code = "provider_error"

    def __init__(
        self,
        message: str = "The upstream provider returned an error.",
        *,
        provider: str | None = None,
        model: str | None = None,
        original_error: BaseException | None = None,
        original_status_code: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.provider = provider
        self.model = model
        self.original_error = original_error
        self.original_status_code = original_status_code
        if original_error is not None:
            self.__cause__ = original_error

    def to_openai_error(self) -> dict[str, Any]:
        """Include provider context in the serialized error."""
        result = super().to_openai_error()
        if self.provider:
            result["error"]["provider"] = self.provider
        if self.model:
            result["error"]["model"] = self.model
        return result


class ServiceUnavailableError(RouterBotError):
    """503 — All deployments for the requested model are unavailable."""

    status_code = 503
    type = "service_unavailable_error"
    code = "service_unavailable"

    def __init__(
        self,
        message: str = "All model deployments are currently unavailable. Please try again later.",
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
