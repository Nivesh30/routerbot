"""Fallback chain execution for the RouterBot router.

When a primary model fails, the fallback chain tries each configured
fallback model in sequence, stopping at the first success.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


async def execute_with_fallbacks(
    primary_model: str,
    fallback_models: list[str],
    provider_fn: Callable[[str], Awaitable[Any]],
    request_id: str = "unknown",
) -> Any:
    """Try the primary model, then fall back through the chain on failure.

    Parameters
    ----------
    primary_model:
        Name of the primary (first-choice) model.
    fallback_models:
        Ordered list of fallback model names to try on failure.
    provider_fn:
        Async callable accepting a model name that performs the actual
        LLM call and returns the response.
    request_id:
        Used in log messages to correlate attempts.

    Returns
    -------
    Any
        The response from the first successful model.

    Raises
    ------
    Exception
        The last exception if all models in the chain fail.
    """
    from routerbot.core.exceptions import AuthenticationError, BadRequestError, ModelNotFoundError

    # Build the full chain: primary + fallbacks
    models_to_try = [primary_model, *list(fallback_models)]
    last_exc: BaseException | None = None

    for i, model_name in enumerate(models_to_try):
        is_fallback = i > 0
        if is_fallback:
            logger.info(
                "Fallback: trying model %r (fallback #%d, req=%s)",
                model_name,
                i,
                request_id,
            )
        try:
            result = await provider_fn(model_name)
            if is_fallback:
                logger.info(
                    "Fallback succeeded with model %r (req=%s)",
                    model_name,
                    request_id,
                )
            return result
        except (AuthenticationError, BadRequestError, ModelNotFoundError):
            # Non-retryable errors — don't try fallbacks
            raise
        except BaseException as exc:
            last_exc = exc
            if not is_fallback:
                logger.warning(
                    "Primary model %r failed, trying fallbacks (req=%s): %s",
                    model_name,
                    request_id,
                    exc,
                )
            else:
                logger.warning(
                    "Fallback model %r also failed (req=%s): %s",
                    model_name,
                    request_id,
                    exc,
                )

    # All attempts exhausted
    if last_exc is not None:
        raise last_exc

    # Unreachable
    from routerbot.core.exceptions import ServiceUnavailableError

    raise ServiceUnavailableError("All models in fallback chain failed")
