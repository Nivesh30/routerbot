"""Circuit-breaker implementation for provider fault isolation.

Three-state machine:

    CLOSED  ──(failure_threshold reached)──▶  OPEN
    OPEN    ──(recovery_timeout elapsed)───▶  HALF_OPEN
    HALF_OPEN ──(success_threshold met)────▶  CLOSED
    HALF_OPEN ──(any failure)──────────────▶  OPEN

Thread-safety is provided via :class:`asyncio.Lock`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from routerbot.core.resilience.models import (
    CircuitBreakerConfig,
    CircuitBreakerSnapshot,
    CircuitState,
)

UTC = UTC
logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Per-provider circuit breaker.

    Parameters
    ----------
    name:
        Identifier (typically the provider/deployment name).
    config:
        Thresholds and timing configuration.
    """

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None) -> None:
        self.name = name
        self.config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0

        self._last_failure_time: float | None = None
        self._last_success_time: float | None = None
        self._opened_at: float | None = None
        self._half_opened_at: float | None = None

        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Return the current state, transitioning OPEN → HALF_OPEN if timeout elapsed."""
        if (
            self._state == CircuitState.OPEN
            and self._opened_at is not None
            and time.monotonic() - self._opened_at >= self.config.recovery_timeout
        ):
            self._transition_to_half_open()
        return self._state

    async def allow_request(self) -> bool:
        """Return ``True`` if a request is allowed through the circuit."""
        async with self._lock:
            current = self.state
            if current == CircuitState.CLOSED:
                return True
            if current == CircuitState.OPEN:
                return False
            # HALF_OPEN — allow limited probes
            if self._half_open_calls < self.config.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False

    async def record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            self._last_success_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._transition_to_closed()
            else:
                # CLOSED — reset failure counter
                self._failure_count = 0

    async def record_failure(self, exc: BaseException | None = None) -> None:
        """Record a failed call, potentially opening the circuit."""
        async with self._lock:
            # Check excluded exceptions
            if exc and type(exc).__name__ in self.config.excluded_exceptions:
                return

            self._last_failure_time = time.monotonic()
            self._failure_count += 1

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open re-opens immediately
                self._transition_to_open()
            elif self._state == CircuitState.CLOSED and self._failure_count >= self.config.failure_threshold:
                self._transition_to_open()

    async def reset(self) -> None:
        """Force the circuit back to CLOSED."""
        async with self._lock:
            self._transition_to_closed()

    def snapshot(self) -> CircuitBreakerSnapshot:
        """Return a point-in-time snapshot."""
        return CircuitBreakerSnapshot(
            name=self.name,
            state=self.state,
            failure_count=self._failure_count,
            success_count=self._success_count,
            last_failure_time=_mono_to_dt(self._last_failure_time),
            last_success_time=_mono_to_dt(self._last_success_time),
            opened_at=_mono_to_dt(self._opened_at),
            half_opened_at=_mono_to_dt(self._half_opened_at),
        )

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _transition_to_open(self) -> None:
        logger.warning(
            "Circuit %r OPEN after %d failures",
            self.name,
            self._failure_count,
        )
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()
        self._success_count = 0
        self._half_open_calls = 0

    def _transition_to_half_open(self) -> None:
        logger.info("Circuit %r → HALF_OPEN (recovery probe)", self.name)
        self._state = CircuitState.HALF_OPEN
        self._half_opened_at = time.monotonic()
        self._success_count = 0
        self._half_open_calls = 0

    def _transition_to_closed(self) -> None:
        logger.info("Circuit %r → CLOSED", self.name)
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._opened_at = None
        self._half_opened_at = None


class CircuitBreakerRegistry:
    """Manages named circuit breakers for multiple providers."""

    def __init__(self, default_config: CircuitBreakerConfig | None = None) -> None:
        self._default_config = default_config or CircuitBreakerConfig()
        self._breakers: dict[str, CircuitBreaker] = {}
        self._overrides: dict[str, CircuitBreakerConfig] = {}

    def register(self, name: str, config: CircuitBreakerConfig | None = None) -> CircuitBreaker:
        """Register or return an existing breaker."""
        if name not in self._breakers:
            cfg = config or self._overrides.get(name, self._default_config)
            self._breakers[name] = CircuitBreaker(name, cfg)
        return self._breakers[name]

    def get(self, name: str) -> CircuitBreaker:
        """Get an existing breaker or create one with defaults."""
        return self.register(name)

    def set_override(self, name: str, config: CircuitBreakerConfig) -> None:
        """Set a per-provider config override (applied on next register)."""
        self._overrides[name] = config

    def all_snapshots(self) -> list[CircuitBreakerSnapshot]:
        """Return snapshots for every registered breaker."""
        return [b.snapshot() for b in self._breakers.values()]

    def all_open(self) -> list[str]:
        """Return names of all breakers currently in OPEN state."""
        return [n for n, b in self._breakers.items() if b.state == CircuitState.OPEN]

    def summary(self) -> dict[str, Any]:
        """Return a summary dict."""
        states: dict[str, int] = {}
        for b in self._breakers.values():
            s = b.state.value
            states[s] = states.get(s, 0) + 1
        return {
            "total": len(self._breakers),
            "states": states,
            "open": self.all_open(),
        }

    async def reset_all(self) -> None:
        """Reset all breakers to CLOSED."""
        for b in self._breakers.values():
            await b.reset()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BOOT_MONO = time.monotonic()
_BOOT_DT = datetime.now(tz=UTC)


def _mono_to_dt(mono: float | None) -> datetime | None:
    """Convert a monotonic timestamp to a datetime (approximate)."""
    if mono is None:
        return None
    offset = mono - _BOOT_MONO
    return _BOOT_DT.replace(tzinfo=UTC) + __import__("datetime").timedelta(seconds=offset)
