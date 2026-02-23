"""Retry logic with exponential backoff and jitter.

Provides a :class:`RetryPolicy` that controls how many times to retry
and which errors are retryable, plus a :func:`with_retry` decorator
that wraps async callables.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Errors that are considered transient / retryable
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class RetryPolicy:
    """Configuration for retry behaviour.

    Parameters
    ----------
    max_retries:
        Maximum number of retry attempts (0 = no retry).
    base_delay:
        Initial delay in seconds before the first retry.
    max_delay:
        Maximum delay between retries.
    exponential_base:
        Multiplier applied to delay on each retry.
    jitter:
        Whether to add random jitter to prevent thundering-herd.
    retryable_status_codes:
        Set of HTTP status codes that trigger a retry.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_status_codes: set[int] | None = None,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_status_codes = retryable_status_codes or _RETRYABLE_STATUS_CODES

    def delay_for(self, attempt: int) -> float:
        """Compute the sleep duration for a given attempt number (0-indexed)."""
        delay = min(self.base_delay * (self.exponential_base**attempt), self.max_delay)
        if self.jitter:
            # ±25% jitter
            delay *= 1 + random.uniform(-0.25, 0.25)  # noqa: S311
        return max(delay, 0.0)

    def should_retry(self, exc: BaseException) -> bool:
        """Determine whether an exception warrants a retry.

        Retries on:
        - ``RateLimitError`` (429)
        - ``ServiceUnavailableError`` (503)
        - ``ProviderError`` with retryable status code

        Never retries:
        - ``AuthenticationError``
        - ``BadRequestError``
        - ``ModelNotFoundError``
        """
        from routerbot.core.exceptions import (
            AuthenticationError,
            BadRequestError,
            ModelNotFoundError,
            ProviderError,
            RateLimitError,
            ServiceUnavailableError,
        )

        if isinstance(exc, (AuthenticationError, BadRequestError, ModelNotFoundError)):
            return False
        if isinstance(exc, (RateLimitError, ServiceUnavailableError)):
            return True
        if isinstance(exc, ProviderError):
            return exc.status_code in self.retryable_status_codes
        # Retry on generic network errors (timeouts, connection resets)
        import httpx

        return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))


async def with_retry(
    func: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    request_id: str = "unknown",
) -> T:
    """Execute an async callable with retry logic.

    Parameters
    ----------
    func:
        Zero-argument async callable to invoke.
    policy:
        The :class:`RetryPolicy` controlling retry behaviour.
    request_id:
        Used in log messages to correlate retries with requests.

    Returns
    -------
    T
        The return value of *func* on success.

    Raises
    ------
    Exception
        The last exception if all retries are exhausted.
    """
    last_exc: BaseException | None = None

    for attempt in range(policy.max_retries + 1):
        try:
            return await func()
        except BaseException as exc:
            last_exc = exc
            is_last = attempt >= policy.max_retries
            if is_last or not policy.should_retry(exc):
                raise

            delay = policy.delay_for(attempt)
            logger.warning(
                "Retrying after error (attempt %d/%d, delay=%.2fs, req=%s): %s",
                attempt + 1,
                policy.max_retries,
                delay,
                request_id,
                exc,
            )
            await asyncio.sleep(delay)

    # Should not reach here
    raise last_exc  # type: ignore[misc]
