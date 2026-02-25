"""Provider budget routing.

Tracks per-provider and per-tag spend with configurable budget limits and
period-based resets.  When a provider's budget is exceeded, the router
can skip it and fall back to an alternative provider.

Configuration example::

    router_settings:
      provider_budgets:
        openai:
          max_budget: 100.0
          budget_period: "daily"
        anthropic:
          max_budget: 200.0
          budget_period: "monthly"
      tag_budgets:
        production:
          max_budget: 500.0
          budget_period: "monthly"
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Budget Period
# ---------------------------------------------------------------------------


class BudgetPeriod(StrEnum):
    """Time period for budget resets."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    UNLIMITED = "unlimited"

    def seconds(self) -> float:
        """Return the period length in seconds (approximate)."""
        if self == BudgetPeriod.DAILY:
            return 86400.0
        if self == BudgetPeriod.WEEKLY:
            return 604800.0
        if self == BudgetPeriod.MONTHLY:
            return 2592000.0  # 30 days
        return float("inf")


# ---------------------------------------------------------------------------
# Budget Config
# ---------------------------------------------------------------------------


@dataclass
class BudgetConfig:
    """Budget configuration for a provider or tag.

    Parameters
    ----------
    max_budget:
        Maximum spend in USD for the given period.
    budget_period:
        How often the budget resets.
    """

    max_budget: float
    budget_period: BudgetPeriod = BudgetPeriod.MONTHLY


# ---------------------------------------------------------------------------
# Budget State
# ---------------------------------------------------------------------------


@dataclass
class _BudgetState:
    """Internal tracking for a single budget."""

    current_spend: float = 0.0
    period_start: float = field(default_factory=time.time)

    def should_reset(self, period: BudgetPeriod) -> bool:
        """Check whether the current period has elapsed."""
        if period == BudgetPeriod.UNLIMITED:
            return False
        return (time.time() - self.period_start) >= period.seconds()

    def reset(self) -> None:
        """Reset spend for a new period."""
        self.current_spend = 0.0
        self.period_start = time.time()


# ---------------------------------------------------------------------------
# Budget Check Result
# ---------------------------------------------------------------------------


@dataclass
class BudgetCheckResult:
    """Result of a budget check.

    Parameters
    ----------
    allowed:
        Whether the request is allowed.
    provider:
        The provider that was checked.
    current_spend:
        Current spend in the period.
    max_budget:
        Maximum allowed budget.
    remaining:
        Remaining budget.
    exceeded_by:
        How much the budget is exceeded (0 if not exceeded).
    """

    allowed: bool = True
    provider: str = ""
    current_spend: float = 0.0
    max_budget: float = 0.0
    remaining: float = 0.0
    exceeded_by: float = 0.0


# ---------------------------------------------------------------------------
# Provider Budget Manager
# ---------------------------------------------------------------------------


class ProviderBudgetManager:
    """Tracks per-provider and per-tag spend with budget enforcement.

    Parameters
    ----------
    provider_budgets:
        Budget configs keyed by provider name.
    tag_budgets:
        Budget configs keyed by tag name.
    """

    def __init__(
        self,
        *,
        provider_budgets: dict[str, BudgetConfig] | None = None,
        tag_budgets: dict[str, BudgetConfig] | None = None,
    ) -> None:
        self._provider_budgets = dict(provider_budgets) if provider_budgets else {}
        self._tag_budgets = dict(tag_budgets) if tag_budgets else {}
        self._provider_states: dict[str, _BudgetState] = {}
        self._tag_states: dict[str, _BudgetState] = {}

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_provider_budget(
        self, provider: str, config: BudgetConfig
    ) -> None:
        """Set or update budget for a provider."""
        self._provider_budgets[provider] = config

    def remove_provider_budget(self, provider: str) -> None:
        """Remove budget tracking for a provider."""
        self._provider_budgets.pop(provider, None)
        self._provider_states.pop(provider, None)

    def set_tag_budget(self, tag: str, config: BudgetConfig) -> None:
        """Set or update budget for a tag."""
        self._tag_budgets[tag] = config

    def remove_tag_budget(self, tag: str) -> None:
        """Remove budget tracking for a tag."""
        self._tag_budgets.pop(tag, None)
        self._tag_states.pop(tag, None)

    # ------------------------------------------------------------------
    # Spend Recording
    # ------------------------------------------------------------------

    def record_spend(
        self,
        *,
        provider: str,
        cost: float,
        tags: list[str] | None = None,
    ) -> None:
        """Record spend for a provider and optional tags.

        Automatically resets period counters when a period has elapsed.
        """
        if cost <= 0:
            return

        # Provider spend
        if provider in self._provider_budgets:
            state = self._get_provider_state(provider)
            config = self._provider_budgets[provider]
            if state.should_reset(config.budget_period):
                state.reset()
            state.current_spend += cost

        # Tag spend
        for tag in tags or []:
            if tag in self._tag_budgets:
                state = self._get_tag_state(tag)
                config = self._tag_budgets[tag]
                if state.should_reset(config.budget_period):
                    state.reset()
                state.current_spend += cost

    # ------------------------------------------------------------------
    # Budget Checking
    # ------------------------------------------------------------------

    def check_provider_budget(self, provider: str) -> BudgetCheckResult:
        """Check whether a provider is within its budget.

        If no budget is configured for the provider, always returns allowed.
        """
        if provider not in self._provider_budgets:
            return BudgetCheckResult(allowed=True, provider=provider)

        config = self._provider_budgets[provider]
        state = self._get_provider_state(provider)

        if state.should_reset(config.budget_period):
            state.reset()

        remaining = config.max_budget - state.current_spend
        exceeded = max(0.0, -remaining)

        return BudgetCheckResult(
            allowed=remaining > 0,
            provider=provider,
            current_spend=state.current_spend,
            max_budget=config.max_budget,
            remaining=max(0.0, remaining),
            exceeded_by=exceeded,
        )

    def check_tag_budget(self, tag: str) -> BudgetCheckResult:
        """Check whether a tag is within its budget."""
        if tag not in self._tag_budgets:
            return BudgetCheckResult(allowed=True, provider=tag)

        config = self._tag_budgets[tag]
        state = self._get_tag_state(tag)

        if state.should_reset(config.budget_period):
            state.reset()

        remaining = config.max_budget - state.current_spend
        exceeded = max(0.0, -remaining)

        return BudgetCheckResult(
            allowed=remaining > 0,
            provider=tag,
            current_spend=state.current_spend,
            max_budget=config.max_budget,
            remaining=max(0.0, remaining),
            exceeded_by=exceeded,
        )

    def get_available_providers(
        self, providers: list[str]
    ) -> list[str]:
        """Filter a list of providers to only those within budget.

        Providers without configured budgets are always included.
        """
        available = []
        for provider in providers:
            result = self.check_provider_budget(provider)
            if result.allowed:
                available.append(provider)
        return available

    # ------------------------------------------------------------------
    # Status Queries
    # ------------------------------------------------------------------

    def get_provider_spend(self, provider: str) -> float:
        """Return current spend for a provider."""
        if provider not in self._provider_budgets:
            return 0.0
        state = self._get_provider_state(provider)
        config = self._provider_budgets[provider]
        if state.should_reset(config.budget_period):
            state.reset()
        return state.current_spend

    def get_tag_spend(self, tag: str) -> float:
        """Return current spend for a tag."""
        if tag not in self._tag_budgets:
            return 0.0
        state = self._get_tag_state(tag)
        config = self._tag_budgets[tag]
        if state.should_reset(config.budget_period):
            state.reset()
        return state.current_spend

    def get_all_provider_status(self) -> dict[str, BudgetCheckResult]:
        """Return budget status for all configured providers."""
        return {
            provider: self.check_provider_budget(provider)
            for provider in self._provider_budgets
        }

    def get_all_tag_status(self) -> dict[str, BudgetCheckResult]:
        """Return budget status for all configured tags."""
        return {tag: self.check_tag_budget(tag) for tag in self._tag_budgets}

    def reset_provider(self, provider: str) -> None:
        """Manually reset budget for a provider."""
        if provider in self._provider_states:
            self._provider_states[provider].reset()

    def reset_tag(self, tag: str) -> None:
        """Manually reset budget for a tag."""
        if tag in self._tag_states:
            self._tag_states[tag].reset()

    def reset_all(self) -> None:
        """Reset all budgets."""
        for state in self._provider_states.values():
            state.reset()
        for state in self._tag_states.values():
            state.reset()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_provider_state(self, provider: str) -> _BudgetState:
        """Get or create state tracker for a provider."""
        if provider not in self._provider_states:
            self._provider_states[provider] = _BudgetState()
        return self._provider_states[provider]

    def _get_tag_state(self, tag: str) -> _BudgetState:
        """Get or create state tracker for a tag."""
        if tag not in self._tag_states:
            self._tag_states[tag] = _BudgetState()
        return self._tag_states[tag]
