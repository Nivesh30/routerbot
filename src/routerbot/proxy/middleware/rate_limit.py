"""Advanced rate limiting middleware and helpers.

Implements sliding-window rate limiting with multiple scopes (API key, user,
team, model, global), dual RPM+TPM tracking, configurable per-scope limits,
hierarchical limit overrides, and proper ``X-RateLimit-*`` response headers.

Supports two backends:
- **In-memory** (default) — suitable for single-instance deployments.
- **Redis** — for multi-instance deployments (requires ``redis`` package).

Configuration example::

    general_settings:
      rate_limit:
        enabled: true
        backend: "memory"  # or "redis"
        global_rpm: 1000
        global_tpm: 100000
        default_key_rpm: 100
        default_key_tpm: 10000
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rate Limit Scope
# ---------------------------------------------------------------------------


class RateLimitScope(StrEnum):
    """Identifies what entity a rate limit applies to."""

    GLOBAL = "global"
    KEY = "key"
    USER = "user"
    TEAM = "team"
    MODEL = "model"


# ---------------------------------------------------------------------------
# Rate Limit Config / Result
# ---------------------------------------------------------------------------


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a single scope.

    Parameters
    ----------
    rpm:
        Requests per minute limit.  ``None`` means unlimited.
    tpm:
        Tokens per minute limit.  ``None`` means unlimited.
    rpm_per_hour:
        Requests per hour limit.  ``None`` means unlimited.
    tpm_per_hour:
        Tokens per hour limit.  ``None`` means unlimited.
    """

    rpm: int | None = None
    tpm: int | None = None
    rpm_per_hour: int | None = None
    tpm_per_hour: int | None = None


@dataclass
class RateLimitResult:
    """The outcome of a rate-limit check.

    Parameters
    ----------
    allowed:
        Whether the request is within limits.
    scope:
        Which scope triggered the limit (if denied).
    limit_requests:
        The maximum number of requests in the current window.
    remaining_requests:
        How many requests are left in the current window.
    limit_tokens:
        The maximum number of tokens in the current window.
    remaining_tokens:
        How many tokens are left in the current window.
    reset_at:
        Unix timestamp when the window resets.
    retry_after:
        Seconds until the next request would be allowed (only on deny).
    """

    allowed: bool = True
    scope: RateLimitScope | None = None
    limit_requests: int | None = None
    remaining_requests: int | None = None
    limit_tokens: int | None = None
    remaining_tokens: int | None = None
    reset_at: float | None = None
    retry_after: float | None = None

    def to_headers(self) -> dict[str, str]:
        """Return ``X-RateLimit-*`` headers suitable for an HTTP response."""
        headers: dict[str, str] = {}
        if self.limit_requests is not None:
            headers["X-RateLimit-Limit-Requests"] = str(self.limit_requests)
        if self.remaining_requests is not None:
            headers["X-RateLimit-Remaining-Requests"] = str(max(0, self.remaining_requests))
        if self.limit_tokens is not None:
            headers["X-RateLimit-Limit-Tokens"] = str(self.limit_tokens)
        if self.remaining_tokens is not None:
            headers["X-RateLimit-Remaining-Tokens"] = str(max(0, self.remaining_tokens))
        if self.reset_at is not None:
            headers["X-RateLimit-Reset"] = str(int(self.reset_at))
        if not self.allowed and self.retry_after is not None:
            headers["Retry-After"] = str(int(self.retry_after) + 1)
        return headers


# ---------------------------------------------------------------------------
# Sliding Window Counter (in-memory)
# ---------------------------------------------------------------------------


@dataclass
class _WindowEntry:
    """Tracks request/token counts in a sliding window."""

    timestamps: list[float] = field(default_factory=list)
    token_records: list[tuple[float, int]] = field(default_factory=list)

    def _prune(self, window_seconds: float) -> None:
        """Remove entries older than the window."""
        cutoff = time.time() - window_seconds
        self.timestamps = [t for t in self.timestamps if t > cutoff]
        self.token_records = [(t, n) for t, n in self.token_records if t > cutoff]

    def request_count(self, window_seconds: float) -> int:
        """Count requests in the current window."""
        self._prune(window_seconds)
        return len(self.timestamps)

    def token_count(self, window_seconds: float) -> int:
        """Sum tokens in the current window."""
        self._prune(window_seconds)
        return sum(n for _, n in self.token_records)

    def record_request(self) -> None:
        """Record a new request."""
        self.timestamps.append(time.time())

    def record_tokens(self, tokens: int) -> None:
        """Record token usage."""
        if tokens > 0:
            self.token_records.append((time.time(), tokens))


# ---------------------------------------------------------------------------
# In-Memory Rate Limiter
# ---------------------------------------------------------------------------


class InMemoryRateLimiter:
    """Sliding-window rate limiter backed by in-memory counters.

    Parameters
    ----------
    global_config:
        Global rate limits.
    default_key_config:
        Default per-key limits (used when no key-specific override is set).
    key_configs:
        Per-key limit overrides, keyed by key_id.
    user_configs:
        Per-user limit overrides, keyed by user_id.
    team_configs:
        Per-team limit overrides, keyed by team_id.
    model_configs:
        Per-model limit overrides, keyed by model name.
    """

    def __init__(
        self,
        *,
        global_config: RateLimitConfig | None = None,
        default_key_config: RateLimitConfig | None = None,
        key_configs: dict[str, RateLimitConfig] | None = None,
        user_configs: dict[str, RateLimitConfig] | None = None,
        team_configs: dict[str, RateLimitConfig] | None = None,
        model_configs: dict[str, RateLimitConfig] | None = None,
    ) -> None:
        self._global_config = global_config or RateLimitConfig()
        self._default_key_config = default_key_config or RateLimitConfig()
        self._key_configs = dict(key_configs) if key_configs else {}
        self._user_configs = dict(user_configs) if user_configs else {}
        self._team_configs = dict(team_configs) if team_configs else {}
        self._model_configs = dict(model_configs) if model_configs else {}

        # Sliding window state keyed by (scope, identifier)
        self._windows: dict[tuple[str, str], _WindowEntry] = defaultdict(_WindowEntry)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_rate_limit(
        self,
        *,
        key_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        model: str | None = None,
    ) -> RateLimitResult:
        """Check whether a request is allowed under current rate limits.

        Checks scopes in order: global → model → team → key → user.
        The first scope that is exceeded triggers a deny.  The response
        always includes headers for the tightest limit.

        Does **not** record the request — call :meth:`record_request`
        after the request succeeds.
        """
        now = time.time()
        minute = 60.0
        tightest = RateLimitResult(allowed=True)

        # --- Global ---
        result = self._check_scope(RateLimitScope.GLOBAL, "global", self._global_config, minute, now)
        if not result.allowed:
            return result
        tightest = self._merge_tightest(tightest, result)

        # --- Model ---
        if model:
            cfg = self._model_configs.get(model, RateLimitConfig())
            result = self._check_scope(RateLimitScope.MODEL, model, cfg, minute, now)
            if not result.allowed:
                return result
            tightest = self._merge_tightest(tightest, result)

        # --- Team ---
        if team_id:
            cfg = self._team_configs.get(team_id, RateLimitConfig())
            result = self._check_scope(RateLimitScope.TEAM, team_id, cfg, minute, now)
            if not result.allowed:
                return result
            tightest = self._merge_tightest(tightest, result)

        # --- Key ---
        if key_id:
            cfg = self._key_configs.get(key_id, self._default_key_config)
            result = self._check_scope(RateLimitScope.KEY, key_id, cfg, minute, now)
            if not result.allowed:
                return result
            tightest = self._merge_tightest(tightest, result)

        # --- User ---
        if user_id:
            cfg = self._user_configs.get(user_id, RateLimitConfig())
            result = self._check_scope(RateLimitScope.USER, user_id, cfg, minute, now)
            if not result.allowed:
                return result
            tightest = self._merge_tightest(tightest, result)

        return tightest

    def record_request(
        self,
        *,
        key_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        model: str | None = None,
        tokens: int = 0,
    ) -> None:
        """Record a request and its token usage across all applicable scopes."""
        self._record_scope("global", "global", tokens)
        if model:
            self._record_scope(RateLimitScope.MODEL, model, tokens)
        if team_id:
            self._record_scope(RateLimitScope.TEAM, team_id, tokens)
        if key_id:
            self._record_scope(RateLimitScope.KEY, key_id, tokens)
        if user_id:
            self._record_scope(RateLimitScope.USER, user_id, tokens)

    def set_key_config(self, key_id: str, config: RateLimitConfig) -> None:
        """Set or update rate limits for a specific API key."""
        self._key_configs[key_id] = config

    def set_user_config(self, user_id: str, config: RateLimitConfig) -> None:
        """Set or update rate limits for a specific user."""
        self._user_configs[user_id] = config

    def set_team_config(self, team_id: str, config: RateLimitConfig) -> None:
        """Set or update rate limits for a specific team."""
        self._team_configs[team_id] = config

    def set_model_config(self, model: str, config: RateLimitConfig) -> None:
        """Set or update rate limits for a specific model."""
        self._model_configs[model] = config

    def reset(self) -> None:
        """Clear all sliding window state."""
        self._windows.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_scope(
        self,
        scope: RateLimitScope | str,
        identifier: str,
        config: RateLimitConfig,
        window: float,
        now: float,
    ) -> RateLimitResult:
        """Check rate limits for one scope."""
        entry = self._windows[(str(scope), identifier)]
        req_count = entry.request_count(window)
        tok_count = entry.token_count(window)
        reset_at = now + window

        result = RateLimitResult(
            allowed=True,
            scope=RateLimitScope(scope)
            if isinstance(scope, str) and scope in {s.value for s in RateLimitScope}
            else None,
            reset_at=reset_at,
        )

        # RPM check
        if config.rpm is not None:
            result.limit_requests = config.rpm
            result.remaining_requests = config.rpm - req_count
            if req_count >= config.rpm:
                result.allowed = False
                result.retry_after = self._time_until_slot(entry.timestamps, window)
                result.scope = (
                    RateLimitScope(scope)
                    if isinstance(scope, str) and scope in {s.value for s in RateLimitScope}
                    else None
                )
                return result

        # TPM check
        if config.tpm is not None:
            result.limit_tokens = config.tpm
            result.remaining_tokens = config.tpm - tok_count
            if tok_count >= config.tpm:
                result.allowed = False
                result.retry_after = self._time_until_token_slot(entry.token_records, window)
                result.scope = (
                    RateLimitScope(scope)
                    if isinstance(scope, str) and scope in {s.value for s in RateLimitScope}
                    else None
                )
                return result

        return result

    @staticmethod
    def _time_until_slot(timestamps: list[float], window: float) -> float:
        """Calculate seconds until the oldest request exits the window."""
        if not timestamps:
            return 0.0
        oldest = min(timestamps)
        return max(0.0, (oldest + window) - time.time())

    @staticmethod
    def _time_until_token_slot(records: list[tuple[float, int]], window: float) -> float:
        """Calculate seconds until token count drops below the limit."""
        if not records:
            return 0.0
        oldest = min(t for t, _ in records)
        return max(0.0, (oldest + window) - time.time())

    def _record_scope(self, scope: RateLimitScope | str, identifier: str, tokens: int) -> None:
        """Record a request+tokens for a given scope/identifier."""
        entry = self._windows[(str(scope), identifier)]
        entry.record_request()
        if tokens > 0:
            entry.record_tokens(tokens)

    @staticmethod
    def _merge_tightest(current: RateLimitResult, candidate: RateLimitResult) -> RateLimitResult:
        """Merge two results keeping the tightest limits."""
        # Pick the one with fewer remaining requests
        if candidate.remaining_requests is not None and (
            current.remaining_requests is None or candidate.remaining_requests < current.remaining_requests
        ):
            current.limit_requests = candidate.limit_requests
            current.remaining_requests = candidate.remaining_requests

        if candidate.remaining_tokens is not None and (
            current.remaining_tokens is None or candidate.remaining_tokens < current.remaining_tokens
        ):
            current.limit_tokens = candidate.limit_tokens
            current.remaining_tokens = candidate.remaining_tokens

        if candidate.reset_at is not None and (current.reset_at is None or candidate.reset_at < current.reset_at):
            current.reset_at = candidate.reset_at

        return current
