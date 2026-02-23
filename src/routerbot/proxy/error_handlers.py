"""FastAPI exception handlers for RouterBot.

Maps RouterBot exceptions to OpenAI-compatible HTTP error responses.

Response format::

    HTTP/1.1 400 Bad Request
    Content-Type: application/json

    {
      "error": {
        "message": "...",
        "type": "invalid_request_error",
        "param": null,
        "code": null
      }
    }
"""

from __future__ import annotations

import logging

from fastapi import Request  # noqa: TC002
from fastapi.responses import JSONResponse

from routerbot.core.exceptions import (  # noqa: TC001
    AuthenticationError,
    BadRequestError,
    ModelNotFoundError,
    ProviderError,
    RateLimitError,
    RouterBotError,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)


def _error_response(exc: RouterBotError) -> JSONResponse:
    """Build a JSONResponse from a RouterBotError."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_openai_error(),
    )


async def routerbot_error_handler(request: Request, exc: RouterBotError) -> JSONResponse:
    """Handle all RouterBotError subclasses."""
    logger.warning(
        "RouterBot error: %s (status=%d)",
        exc.message,
        exc.status_code,
        extra={"exception_type": type(exc).__name__},
    )
    return _error_response(exc)


async def authentication_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
    """Handle authentication errors."""
    return _error_response(exc)


async def rate_limit_error_handler(request: Request, exc: RateLimitError) -> JSONResponse:
    """Handle rate limit errors."""
    return _error_response(exc)


async def bad_request_handler(request: Request, exc: BadRequestError) -> JSONResponse:
    """Handle bad request / invalid request errors."""
    return _error_response(exc)


async def model_not_found_handler(request: Request, exc: ModelNotFoundError) -> JSONResponse:
    """Handle model-not-found errors."""
    return _error_response(exc)


async def service_unavailable_handler(request: Request, exc: ServiceUnavailableError) -> JSONResponse:
    """Handle service unavailable errors."""
    return _error_response(exc)


async def provider_error_handler(request: Request, exc: ProviderError) -> JSONResponse:
    """Handle provider errors."""
    return _error_response(exc)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unexpected exceptions — return 500."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "message": "An internal server error occurred.",
                "type": "internal_error",
                "param": None,
                "code": None,
            }
        },
    )
