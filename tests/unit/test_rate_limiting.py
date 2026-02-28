"""Tests for the advanced rate limiting system (Task 6.7).

Covers:
- RateLimitConfig: basic configuration
- RateLimitResult: headers generation, retry_after
- InMemoryRateLimiter: RPM/TPM enforcement, multi-scope checking,
  sliding window, recording, per-key/user/team/model limits,
  hierarchical overrides, reset
"""

from __future__ import annotations

import time

from routerbot.proxy.middleware.rate_limit import (
    InMemoryRateLimiter,
    RateLimitConfig,
    RateLimitResult,
    RateLimitScope,
)

# ===================================================================
# RateLimitConfig Tests
# ===================================================================


class TestRateLimitConfig:
    """Tests for rate limit configuration."""

    def test_defaults(self) -> None:
        cfg = RateLimitConfig()
        assert cfg.rpm is None
        assert cfg.tpm is None

    def test_custom(self) -> None:
        cfg = RateLimitConfig(rpm=100, tpm=10000)
        assert cfg.rpm == 100
        assert cfg.tpm == 10000


# ===================================================================
# RateLimitResult Tests
# ===================================================================


class TestRateLimitResult:
    """Tests for rate limit result and headers."""

    def test_allowed_result(self) -> None:
        result = RateLimitResult(allowed=True)
        assert result.allowed is True
        assert result.retry_after is None

    def test_denied_result(self) -> None:
        result = RateLimitResult(
            allowed=False,
            scope=RateLimitScope.KEY,
            retry_after=5.0,
        )
        assert result.allowed is False
        assert result.scope == RateLimitScope.KEY

    def test_to_headers_full(self) -> None:
        result = RateLimitResult(
            allowed=True,
            limit_requests=100,
            remaining_requests=95,
            limit_tokens=10000,
            remaining_tokens=9500,
            reset_at=1700000060.0,
        )
        headers = result.to_headers()
        assert headers["X-RateLimit-Limit-Requests"] == "100"
        assert headers["X-RateLimit-Remaining-Requests"] == "95"
        assert headers["X-RateLimit-Limit-Tokens"] == "10000"
        assert headers["X-RateLimit-Remaining-Tokens"] == "9500"
        assert headers["X-RateLimit-Reset"] == "1700000060"

    def test_to_headers_denied_with_retry(self) -> None:
        result = RateLimitResult(
            allowed=False,
            retry_after=10.0,
        )
        headers = result.to_headers()
        assert "Retry-After" in headers
        assert int(headers["Retry-After"]) >= 11

    def test_to_headers_no_negative_remaining(self) -> None:
        result = RateLimitResult(
            allowed=False,
            limit_requests=5,
            remaining_requests=-3,
        )
        headers = result.to_headers()
        assert headers["X-RateLimit-Remaining-Requests"] == "0"

    def test_to_headers_empty_when_no_limits(self) -> None:
        result = RateLimitResult(allowed=True)
        headers = result.to_headers()
        assert "X-RateLimit-Limit-Requests" not in headers


# ===================================================================
# InMemoryRateLimiter — RPM Tests
# ===================================================================


class TestRPMLimiting:
    """Tests for requests-per-minute limiting."""

    def test_under_limit(self) -> None:
        limiter = InMemoryRateLimiter(global_config=RateLimitConfig(rpm=10))
        result = limiter.check_rate_limit()
        assert result.allowed is True
        assert result.remaining_requests == 10

    def test_at_limit_blocked(self) -> None:
        limiter = InMemoryRateLimiter(global_config=RateLimitConfig(rpm=3))
        for _ in range(3):
            limiter.record_request()

        result = limiter.check_rate_limit()
        assert result.allowed is False
        assert result.retry_after is not None
        assert result.retry_after >= 0

    def test_record_then_check(self) -> None:
        limiter = InMemoryRateLimiter(global_config=RateLimitConfig(rpm=5))
        for _ in range(3):
            limiter.record_request()
        result = limiter.check_rate_limit()
        assert result.allowed is True
        assert result.remaining_requests == 2


# ===================================================================
# InMemoryRateLimiter — TPM Tests
# ===================================================================


class TestTPMLimiting:
    """Tests for tokens-per-minute limiting."""

    def test_under_token_limit(self) -> None:
        limiter = InMemoryRateLimiter(global_config=RateLimitConfig(tpm=1000))
        limiter.record_request(tokens=500)
        result = limiter.check_rate_limit()
        assert result.allowed is True
        assert result.remaining_tokens == 500

    def test_over_token_limit(self) -> None:
        limiter = InMemoryRateLimiter(global_config=RateLimitConfig(tpm=1000))
        limiter.record_request(tokens=1000)
        result = limiter.check_rate_limit()
        assert result.allowed is False

    def test_combined_rpm_tpm(self) -> None:
        limiter = InMemoryRateLimiter(global_config=RateLimitConfig(rpm=10, tpm=1000))
        for _ in range(5):
            limiter.record_request(tokens=150)
        result = limiter.check_rate_limit()
        assert result.allowed is True
        assert result.remaining_requests == 5
        assert result.remaining_tokens == 250


# ===================================================================
# Per-Key Rate Limiting
# ===================================================================


class TestPerKeyLimiting:
    """Tests for per-API-key rate limiting."""

    def test_default_key_config(self) -> None:
        limiter = InMemoryRateLimiter(
            default_key_config=RateLimitConfig(rpm=5),
        )
        for _ in range(5):
            limiter.record_request(key_id="key-1")
        result = limiter.check_rate_limit(key_id="key-1")
        assert result.allowed is False

    def test_key_specific_override(self) -> None:
        limiter = InMemoryRateLimiter(
            default_key_config=RateLimitConfig(rpm=5),
            key_configs={"premium-key": RateLimitConfig(rpm=100)},
        )
        for _ in range(10):
            limiter.record_request(key_id="premium-key")
        result = limiter.check_rate_limit(key_id="premium-key")
        assert result.allowed is True  # has 100 RPM

    def test_set_key_config(self) -> None:
        limiter = InMemoryRateLimiter(
            default_key_config=RateLimitConfig(rpm=5),
        )
        limiter.set_key_config("key-x", RateLimitConfig(rpm=50))
        for _ in range(10):
            limiter.record_request(key_id="key-x")
        result = limiter.check_rate_limit(key_id="key-x")
        assert result.allowed is True


# ===================================================================
# Per-User Rate Limiting
# ===================================================================


class TestPerUserLimiting:
    """Tests for per-user rate limiting."""

    def test_user_limit(self) -> None:
        limiter = InMemoryRateLimiter(
            user_configs={"user-1": RateLimitConfig(rpm=3)},
        )
        for _ in range(3):
            limiter.record_request(user_id="user-1")
        result = limiter.check_rate_limit(user_id="user-1")
        assert result.allowed is False

    def test_different_users_isolated(self) -> None:
        limiter = InMemoryRateLimiter(
            user_configs={
                "user-1": RateLimitConfig(rpm=3),
                "user-2": RateLimitConfig(rpm=3),
            },
        )
        for _ in range(3):
            limiter.record_request(user_id="user-1")
        result = limiter.check_rate_limit(user_id="user-2")
        assert result.allowed is True  # user-2 hasn't made requests


# ===================================================================
# Per-Team Rate Limiting
# ===================================================================


class TestPerTeamLimiting:
    """Tests for per-team rate limiting."""

    def test_team_limit(self) -> None:
        limiter = InMemoryRateLimiter(
            team_configs={"team-a": RateLimitConfig(rpm=5)},
        )
        for _ in range(5):
            limiter.record_request(team_id="team-a")
        result = limiter.check_rate_limit(team_id="team-a")
        assert result.allowed is False


# ===================================================================
# Per-Model Rate Limiting
# ===================================================================


class TestPerModelLimiting:
    """Tests for per-model rate limiting."""

    def test_model_limit(self) -> None:
        limiter = InMemoryRateLimiter(
            model_configs={"gpt-4": RateLimitConfig(rpm=5)},
        )
        for _ in range(5):
            limiter.record_request(model="gpt-4")
        result = limiter.check_rate_limit(model="gpt-4")
        assert result.allowed is False

    def test_different_models_isolated(self) -> None:
        limiter = InMemoryRateLimiter(
            model_configs={"gpt-4": RateLimitConfig(rpm=5)},
        )
        for _ in range(5):
            limiter.record_request(model="gpt-4")
        result = limiter.check_rate_limit(model="gpt-3.5-turbo")
        # gpt-3.5-turbo has no model config → unlimited
        assert result.allowed is True


# ===================================================================
# Hierarchical Scoping
# ===================================================================


class TestHierarchicalScoping:
    """Tests for hierarchical scope precedence."""

    def test_global_blocks_even_if_key_ok(self) -> None:
        limiter = InMemoryRateLimiter(
            global_config=RateLimitConfig(rpm=3),
            default_key_config=RateLimitConfig(rpm=100),
        )
        for _ in range(3):
            limiter.record_request(key_id="key-1")
        result = limiter.check_rate_limit(key_id="key-1")
        assert result.allowed is False
        assert result.scope == RateLimitScope.GLOBAL

    def test_key_blocks_even_if_global_ok(self) -> None:
        limiter = InMemoryRateLimiter(
            global_config=RateLimitConfig(rpm=100),
            default_key_config=RateLimitConfig(rpm=2),
        )
        for _ in range(2):
            limiter.record_request(key_id="key-1")
        result = limiter.check_rate_limit(key_id="key-1")
        assert result.allowed is False
        assert result.scope == RateLimitScope.KEY

    def test_all_scopes_checked(self) -> None:
        """All scopes are checked when identifiers are provided."""
        limiter = InMemoryRateLimiter(
            global_config=RateLimitConfig(rpm=100),
            default_key_config=RateLimitConfig(rpm=100),
            user_configs={"user-1": RateLimitConfig(rpm=2)},
        )
        for _ in range(2):
            limiter.record_request(key_id="key-1", user_id="user-1", team_id="team-a")
        result = limiter.check_rate_limit(key_id="key-1", user_id="user-1", team_id="team-a")
        assert result.allowed is False
        assert result.scope == RateLimitScope.USER


# ===================================================================
# Sliding Window Behaviour
# ===================================================================


class TestSlidingWindow:
    """Tests for sliding window expiration."""

    def test_old_requests_expire(self) -> None:
        limiter = InMemoryRateLimiter(global_config=RateLimitConfig(rpm=3))
        # Manually inject old timestamps
        entry = limiter._windows[("global", "global")]
        old_time = time.time() - 120  # 2 minutes ago
        entry.timestamps = [old_time, old_time, old_time]

        # These should have expired from the 60s window
        result = limiter.check_rate_limit()
        assert result.allowed is True
        assert result.remaining_requests == 3

    def test_token_records_expire(self) -> None:
        limiter = InMemoryRateLimiter(global_config=RateLimitConfig(tpm=1000))
        entry = limiter._windows[("global", "global")]
        old_time = time.time() - 120
        entry.token_records = [(old_time, 900)]

        result = limiter.check_rate_limit()
        assert result.allowed is True
        assert result.remaining_tokens == 1000


# ===================================================================
# Reset and Runtime Config
# ===================================================================


class TestResetAndConfig:
    """Tests for reset and runtime configuration updates."""

    def test_reset(self) -> None:
        limiter = InMemoryRateLimiter(global_config=RateLimitConfig(rpm=3))
        for _ in range(3):
            limiter.record_request()
        limiter.reset()
        result = limiter.check_rate_limit()
        assert result.allowed is True

    def test_set_user_config(self) -> None:
        limiter = InMemoryRateLimiter()
        limiter.set_user_config("user-x", RateLimitConfig(rpm=2))
        limiter.record_request(user_id="user-x")
        limiter.record_request(user_id="user-x")
        result = limiter.check_rate_limit(user_id="user-x")
        assert result.allowed is False

    def test_set_team_config(self) -> None:
        limiter = InMemoryRateLimiter()
        limiter.set_team_config("team-x", RateLimitConfig(rpm=2))
        limiter.record_request(team_id="team-x")
        limiter.record_request(team_id="team-x")
        result = limiter.check_rate_limit(team_id="team-x")
        assert result.allowed is False

    def test_set_model_config(self) -> None:
        limiter = InMemoryRateLimiter()
        limiter.set_model_config("gpt-4", RateLimitConfig(rpm=2))
        limiter.record_request(model="gpt-4")
        limiter.record_request(model="gpt-4")
        result = limiter.check_rate_limit(model="gpt-4")
        assert result.allowed is False


# ===================================================================
# No Limits Set
# ===================================================================


class TestNoLimits:
    """Tests when no limits are configured."""

    def test_unlimited_allowed(self) -> None:
        limiter = InMemoryRateLimiter()
        for _ in range(1000):
            limiter.record_request()
        result = limiter.check_rate_limit()
        assert result.allowed is True

    def test_no_headers_when_unlimited(self) -> None:
        limiter = InMemoryRateLimiter()
        result = limiter.check_rate_limit()
        headers = result.to_headers()
        assert "X-RateLimit-Limit-Requests" not in headers


# ===================================================================
# RateLimitScope Tests
# ===================================================================


class TestRateLimitScope:
    """Tests for scope enum."""

    def test_scope_values(self) -> None:
        assert RateLimitScope.GLOBAL == "global"
        assert RateLimitScope.KEY == "key"
        assert RateLimitScope.USER == "user"
        assert RateLimitScope.TEAM == "team"
        assert RateLimitScope.MODEL == "model"


# ===================================================================
# Headers Integration Test
# ===================================================================


class TestHeadersIntegration:
    """Tests for rate limit headers with limiter."""

    def test_headers_from_check(self) -> None:
        limiter = InMemoryRateLimiter(global_config=RateLimitConfig(rpm=10, tpm=5000))
        for _ in range(3):
            limiter.record_request(tokens=100)
        result = limiter.check_rate_limit()
        headers = result.to_headers()
        assert headers["X-RateLimit-Limit-Requests"] == "10"
        assert headers["X-RateLimit-Remaining-Requests"] == "7"
        assert headers["X-RateLimit-Limit-Tokens"] == "5000"
        assert headers["X-RateLimit-Remaining-Tokens"] == "4700"
        assert "X-RateLimit-Reset" in headers
