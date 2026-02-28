"""Tests for the provider budget routing system (Task 6.8).

Covers:
- BudgetPeriod: period enum and seconds calculation
- BudgetConfig: configuration dataclass
- BudgetCheckResult: result fields
- ProviderBudgetManager: provider budgets, tag budgets, spend recording,
  budget checking, available providers filtering, period resets,
  runtime config, status queries
"""

from __future__ import annotations

import time

from routerbot.router.budget import (
    BudgetCheckResult,
    BudgetConfig,
    BudgetPeriod,
    ProviderBudgetManager,
)

# ===================================================================
# BudgetPeriod Tests
# ===================================================================


class TestBudgetPeriod:
    """Tests for budget period enum."""

    def test_daily_seconds(self) -> None:
        assert BudgetPeriod.DAILY.seconds() == 86400.0

    def test_weekly_seconds(self) -> None:
        assert BudgetPeriod.WEEKLY.seconds() == 604800.0

    def test_monthly_seconds(self) -> None:
        assert BudgetPeriod.MONTHLY.seconds() == 2592000.0

    def test_unlimited_seconds(self) -> None:
        assert BudgetPeriod.UNLIMITED.seconds() == float("inf")

    def test_values(self) -> None:
        assert BudgetPeriod.DAILY == "daily"
        assert BudgetPeriod.WEEKLY == "weekly"
        assert BudgetPeriod.MONTHLY == "monthly"
        assert BudgetPeriod.UNLIMITED == "unlimited"


# ===================================================================
# BudgetConfig Tests
# ===================================================================


class TestBudgetConfig:
    """Tests for budget configuration."""

    def test_defaults(self) -> None:
        cfg = BudgetConfig(max_budget=100.0)
        assert cfg.max_budget == 100.0
        assert cfg.budget_period == BudgetPeriod.MONTHLY

    def test_custom_period(self) -> None:
        cfg = BudgetConfig(max_budget=50.0, budget_period=BudgetPeriod.DAILY)
        assert cfg.budget_period == BudgetPeriod.DAILY


# ===================================================================
# BudgetCheckResult Tests
# ===================================================================


class TestBudgetCheckResult:
    """Tests for budget check result."""

    def test_allowed(self) -> None:
        r = BudgetCheckResult(
            allowed=True,
            provider="openai",
            current_spend=50.0,
            max_budget=100.0,
            remaining=50.0,
        )
        assert r.allowed is True
        assert r.remaining == 50.0

    def test_exceeded(self) -> None:
        r = BudgetCheckResult(
            allowed=False,
            provider="openai",
            current_spend=120.0,
            max_budget=100.0,
            remaining=0.0,
            exceeded_by=20.0,
        )
        assert r.allowed is False
        assert r.exceeded_by == 20.0


# ===================================================================
# ProviderBudgetManager — Provider Budget Tests
# ===================================================================


class TestProviderBudgets:
    """Tests for provider budget tracking."""

    def test_no_budget_always_allowed(self) -> None:
        mgr = ProviderBudgetManager()
        result = mgr.check_provider_budget("openai")
        assert result.allowed is True

    def test_under_budget(self) -> None:
        mgr = ProviderBudgetManager(provider_budgets={"openai": BudgetConfig(max_budget=100.0)})
        mgr.record_spend(provider="openai", cost=50.0)
        result = mgr.check_provider_budget("openai")
        assert result.allowed is True
        assert result.remaining == 50.0
        assert result.current_spend == 50.0

    def test_over_budget(self) -> None:
        mgr = ProviderBudgetManager(provider_budgets={"openai": BudgetConfig(max_budget=100.0)})
        mgr.record_spend(provider="openai", cost=100.0)
        result = mgr.check_provider_budget("openai")
        assert result.allowed is False
        assert result.remaining == 0.0

    def test_exceeded_by(self) -> None:
        mgr = ProviderBudgetManager(provider_budgets={"openai": BudgetConfig(max_budget=100.0)})
        mgr.record_spend(provider="openai", cost=120.0)
        result = mgr.check_provider_budget("openai")
        assert result.allowed is False
        assert result.exceeded_by == 20.0

    def test_multiple_providers(self) -> None:
        mgr = ProviderBudgetManager(
            provider_budgets={
                "openai": BudgetConfig(max_budget=100.0),
                "anthropic": BudgetConfig(max_budget=200.0),
            }
        )
        mgr.record_spend(provider="openai", cost=100.0)
        mgr.record_spend(provider="anthropic", cost=50.0)

        assert mgr.check_provider_budget("openai").allowed is False
        assert mgr.check_provider_budget("anthropic").allowed is True

    def test_zero_cost_ignored(self) -> None:
        mgr = ProviderBudgetManager(provider_budgets={"openai": BudgetConfig(max_budget=100.0)})
        mgr.record_spend(provider="openai", cost=0)
        mgr.record_spend(provider="openai", cost=-5)
        assert mgr.get_provider_spend("openai") == 0.0

    def test_incremental_spend(self) -> None:
        mgr = ProviderBudgetManager(provider_budgets={"openai": BudgetConfig(max_budget=100.0)})
        mgr.record_spend(provider="openai", cost=30.0)
        mgr.record_spend(provider="openai", cost=30.0)
        mgr.record_spend(provider="openai", cost=30.0)
        assert mgr.get_provider_spend("openai") == 90.0
        assert mgr.check_provider_budget("openai").allowed is True


# ===================================================================
# Tag Budget Tests
# ===================================================================


class TestTagBudgets:
    """Tests for tag budget tracking."""

    def test_no_tag_budget_allowed(self) -> None:
        mgr = ProviderBudgetManager()
        result = mgr.check_tag_budget("production")
        assert result.allowed is True

    def test_tag_under_budget(self) -> None:
        mgr = ProviderBudgetManager(tag_budgets={"production": BudgetConfig(max_budget=500.0)})
        mgr.record_spend(provider="openai", cost=100.0, tags=["production"])
        result = mgr.check_tag_budget("production")
        assert result.allowed is True
        assert result.remaining == 400.0

    def test_tag_over_budget(self) -> None:
        mgr = ProviderBudgetManager(tag_budgets={"production": BudgetConfig(max_budget=500.0)})
        mgr.record_spend(provider="openai", cost=500.0, tags=["production"])
        result = mgr.check_tag_budget("production")
        assert result.allowed is False

    def test_multiple_tags(self) -> None:
        mgr = ProviderBudgetManager(
            tag_budgets={
                "production": BudgetConfig(max_budget=500.0),
                "staging": BudgetConfig(max_budget=100.0),
            }
        )
        mgr.record_spend(provider="openai", cost=50.0, tags=["production", "staging"])
        assert mgr.get_tag_spend("production") == 50.0
        assert mgr.get_tag_spend("staging") == 50.0

    def test_provider_and_tag_tracked(self) -> None:
        mgr = ProviderBudgetManager(
            provider_budgets={"openai": BudgetConfig(max_budget=100.0)},
            tag_budgets={"prod": BudgetConfig(max_budget=500.0)},
        )
        mgr.record_spend(provider="openai", cost=80.0, tags=["prod"])
        assert mgr.get_provider_spend("openai") == 80.0
        assert mgr.get_tag_spend("prod") == 80.0


# ===================================================================
# Available Providers Filtering
# ===================================================================


class TestAvailableProviders:
    """Tests for filtering providers by budget."""

    def test_all_available(self) -> None:
        mgr = ProviderBudgetManager(
            provider_budgets={
                "openai": BudgetConfig(max_budget=100.0),
                "anthropic": BudgetConfig(max_budget=200.0),
            }
        )
        available = mgr.get_available_providers(["openai", "anthropic"])
        assert available == ["openai", "anthropic"]

    def test_some_exceeded(self) -> None:
        mgr = ProviderBudgetManager(
            provider_budgets={
                "openai": BudgetConfig(max_budget=100.0),
                "anthropic": BudgetConfig(max_budget=200.0),
            }
        )
        mgr.record_spend(provider="openai", cost=100.0)
        available = mgr.get_available_providers(["openai", "anthropic"])
        assert available == ["anthropic"]

    def test_unconfigured_always_included(self) -> None:
        mgr = ProviderBudgetManager(provider_budgets={"openai": BudgetConfig(max_budget=100.0)})
        mgr.record_spend(provider="openai", cost=100.0)
        available = mgr.get_available_providers(["openai", "anthropic", "gemini"])
        assert "anthropic" in available
        assert "gemini" in available
        assert "openai" not in available

    def test_empty_input(self) -> None:
        mgr = ProviderBudgetManager()
        assert mgr.get_available_providers([]) == []


# ===================================================================
# Period Reset Tests
# ===================================================================


class TestPeriodReset:
    """Tests for automatic period-based resets."""

    def test_daily_reset(self) -> None:
        mgr = ProviderBudgetManager(
            provider_budgets={"openai": BudgetConfig(max_budget=100.0, budget_period=BudgetPeriod.DAILY)}
        )
        mgr.record_spend(provider="openai", cost=100.0)
        assert mgr.check_provider_budget("openai").allowed is False

        # Manually set period_start to yesterday
        state = mgr._provider_states["openai"]
        state.period_start = time.time() - 90000  # > 24h ago

        result = mgr.check_provider_budget("openai")
        assert result.allowed is True
        assert result.current_spend == 0.0

    def test_unlimited_never_resets(self) -> None:
        mgr = ProviderBudgetManager(
            provider_budgets={
                "openai": BudgetConfig(
                    max_budget=100.0,
                    budget_period=BudgetPeriod.UNLIMITED,
                )
            }
        )
        mgr.record_spend(provider="openai", cost=100.0)
        # Even with very old period_start, unlimited doesn't reset
        state = mgr._provider_states["openai"]
        state.period_start = time.time() - 10000000

        result = mgr.check_provider_budget("openai")
        assert result.allowed is False

    def test_tag_period_reset(self) -> None:
        mgr = ProviderBudgetManager(
            tag_budgets={"prod": BudgetConfig(max_budget=500.0, budget_period=BudgetPeriod.DAILY)}
        )
        mgr.record_spend(provider="openai", cost=500.0, tags=["prod"])
        assert mgr.check_tag_budget("prod").allowed is False

        state = mgr._tag_states["prod"]
        state.period_start = time.time() - 90000

        result = mgr.check_tag_budget("prod")
        assert result.allowed is True


# ===================================================================
# Runtime Configuration
# ===================================================================


class TestRuntimeConfig:
    """Tests for runtime budget configuration."""

    def test_set_provider_budget(self) -> None:
        mgr = ProviderBudgetManager()
        mgr.set_provider_budget("openai", BudgetConfig(max_budget=50.0))
        mgr.record_spend(provider="openai", cost=50.0)
        assert mgr.check_provider_budget("openai").allowed is False

    def test_remove_provider_budget(self) -> None:
        mgr = ProviderBudgetManager(provider_budgets={"openai": BudgetConfig(max_budget=100.0)})
        mgr.remove_provider_budget("openai")
        assert mgr.check_provider_budget("openai").allowed is True

    def test_set_tag_budget(self) -> None:
        mgr = ProviderBudgetManager()
        mgr.set_tag_budget("prod", BudgetConfig(max_budget=100.0))
        mgr.record_spend(provider="openai", cost=100.0, tags=["prod"])
        assert mgr.check_tag_budget("prod").allowed is False

    def test_remove_tag_budget(self) -> None:
        mgr = ProviderBudgetManager(tag_budgets={"prod": BudgetConfig(max_budget=100.0)})
        mgr.remove_tag_budget("prod")
        assert mgr.check_tag_budget("prod").allowed is True


# ===================================================================
# Manual Reset Tests
# ===================================================================


class TestManualReset:
    """Tests for manual budget resets."""

    def test_reset_provider(self) -> None:
        mgr = ProviderBudgetManager(provider_budgets={"openai": BudgetConfig(max_budget=100.0)})
        mgr.record_spend(provider="openai", cost=100.0)
        assert mgr.check_provider_budget("openai").allowed is False

        mgr.reset_provider("openai")
        assert mgr.check_provider_budget("openai").allowed is True

    def test_reset_tag(self) -> None:
        mgr = ProviderBudgetManager(tag_budgets={"prod": BudgetConfig(max_budget=100.0)})
        mgr.record_spend(provider="openai", cost=100.0, tags=["prod"])
        mgr.reset_tag("prod")
        assert mgr.check_tag_budget("prod").allowed is True

    def test_reset_all(self) -> None:
        mgr = ProviderBudgetManager(
            provider_budgets={
                "openai": BudgetConfig(max_budget=100.0),
                "anthropic": BudgetConfig(max_budget=100.0),
            },
            tag_budgets={"prod": BudgetConfig(max_budget=100.0)},
        )
        mgr.record_spend(provider="openai", cost=100.0, tags=["prod"])
        mgr.record_spend(provider="anthropic", cost=100.0)
        mgr.reset_all()
        assert mgr.check_provider_budget("openai").allowed is True
        assert mgr.check_provider_budget("anthropic").allowed is True
        assert mgr.check_tag_budget("prod").allowed is True

    def test_reset_nonexistent(self) -> None:
        mgr = ProviderBudgetManager()
        # Should not raise
        mgr.reset_provider("nope")
        mgr.reset_tag("nope")


# ===================================================================
# Status Query Tests
# ===================================================================


class TestStatusQueries:
    """Tests for status/spend queries."""

    def test_get_provider_spend(self) -> None:
        mgr = ProviderBudgetManager(provider_budgets={"openai": BudgetConfig(max_budget=100.0)})
        mgr.record_spend(provider="openai", cost=42.5)
        assert mgr.get_provider_spend("openai") == 42.5

    def test_get_provider_spend_unconfigured(self) -> None:
        mgr = ProviderBudgetManager()
        assert mgr.get_provider_spend("openai") == 0.0

    def test_get_tag_spend(self) -> None:
        mgr = ProviderBudgetManager(tag_budgets={"prod": BudgetConfig(max_budget=500.0)})
        mgr.record_spend(provider="openai", cost=75.0, tags=["prod"])
        assert mgr.get_tag_spend("prod") == 75.0

    def test_get_all_provider_status(self) -> None:
        mgr = ProviderBudgetManager(
            provider_budgets={
                "openai": BudgetConfig(max_budget=100.0),
                "anthropic": BudgetConfig(max_budget=200.0),
            }
        )
        mgr.record_spend(provider="openai", cost=60.0)
        status = mgr.get_all_provider_status()
        assert len(status) == 2
        assert status["openai"].current_spend == 60.0
        assert status["anthropic"].current_spend == 0.0

    def test_get_all_tag_status(self) -> None:
        mgr = ProviderBudgetManager(
            tag_budgets={
                "prod": BudgetConfig(max_budget=500.0),
                "dev": BudgetConfig(max_budget=100.0),
            }
        )
        mgr.record_spend(provider="openai", cost=50.0, tags=["prod"])
        status = mgr.get_all_tag_status()
        assert len(status) == 2
        assert status["prod"].current_spend == 50.0
        assert status["dev"].current_spend == 0.0
