"""Graceful degradation manager.

Coordinates service degradation policies when providers become unhealthy.
Works with the circuit breaker, request queue, and bulkhead components
to implement higher-level degradation strategies:

* **NORMAL** — all systems operational
* **DEGRADED** — some providers unhealthy; enable request queuing
* **LIMITED** — many providers down; restrict to cheap/fast models only
* **EMERGENCY** — most providers down; reject new requests or serve cached only
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from routerbot.core.resilience.models import (
    DegradationLevel,
    DegradationPolicy,
    DegradationStatus,
)

UTC = UTC
logger = logging.getLogger(__name__)

# Default policies when none are configured
_DEFAULT_POLICIES: dict[str, DegradationPolicy] = {
    DegradationLevel.NORMAL: DegradationPolicy(
        level=DegradationLevel.NORMAL,
        description="All systems operational",
    ),
    DegradationLevel.DEGRADED: DegradationPolicy(
        level=DegradationLevel.DEGRADED,
        description="Some providers unhealthy — request queuing enabled",
        queue_requests=True,
    ),
    DegradationLevel.LIMITED: DegradationPolicy(
        level=DegradationLevel.LIMITED,
        description="Service limited — reduced model selection, lower token limits",
        queue_requests=True,
        max_tokens_override=1000,
        disable_streaming=True,
    ),
    DegradationLevel.EMERGENCY: DegradationPolicy(
        level=DegradationLevel.EMERGENCY,
        description="Emergency — rejecting new requests",
        reject_new_requests=True,
    ),
}


class DegradationManager:
    """Manages global and per-provider degradation levels.

    Parameters
    ----------
    policies:
        Named degradation policies.  If ``None``, defaults are used.
    auto_escalate_thresholds:
        Tuple of (degraded_pct, limited_pct, emergency_pct) representing
        the percentage of unhealthy providers that triggers each level.
    """

    def __init__(
        self,
        policies: dict[str, DegradationPolicy] | None = None,
        auto_escalate_thresholds: tuple[float, float, float] = (0.2, 0.5, 0.8),
    ) -> None:
        self._policies = policies or dict(_DEFAULT_POLICIES)
        self._thresholds = auto_escalate_thresholds
        self._global_status = DegradationStatus(provider="global", level=DegradationLevel.NORMAL)
        self._provider_status: dict[str, DegradationStatus] = {}

    # ------------------------------------------------------------------
    # Global status
    # ------------------------------------------------------------------

    @property
    def global_level(self) -> DegradationLevel:
        return self._global_status.level

    @property
    def global_status(self) -> DegradationStatus:
        return self._global_status

    def set_global_level(self, level: DegradationLevel, reason: str = "") -> None:
        """Manually set the global degradation level."""
        if level != self._global_status.level:
            logger.warning("Global degradation: %s → %s (%s)", self._global_status.level, level, reason)
            self._global_status = DegradationStatus(
                provider="global",
                level=level,
                reason=reason,
                since=datetime.now(tz=UTC),
            )

    def get_policy(self, level: DegradationLevel | None = None) -> DegradationPolicy:
        """Return the active policy for the given (or current global) level."""
        target = level or self._global_status.level
        return self._policies.get(
            target,
            DegradationPolicy(level=target),
        )

    # ------------------------------------------------------------------
    # Per-provider status
    # ------------------------------------------------------------------

    def set_provider_level(self, provider: str, level: DegradationLevel, reason: str = "") -> None:
        """Set degradation level for a specific provider."""
        prev = self._provider_status.get(provider)
        if prev is None or prev.level != level:
            logger.info("Provider %s degradation: %s → %s", provider, prev.level if prev else "none", level)
            self._provider_status[provider] = DegradationStatus(
                provider=provider,
                level=level,
                reason=reason,
                since=datetime.now(tz=UTC),
            )

    def get_provider_level(self, provider: str) -> DegradationLevel:
        s = self._provider_status.get(provider)
        return s.level if s else DegradationLevel.NORMAL

    def clear_provider(self, provider: str) -> None:
        """Reset a provider to NORMAL."""
        self._provider_status.pop(provider, None)

    # ------------------------------------------------------------------
    # Auto-escalation
    # ------------------------------------------------------------------

    def auto_escalate(self, total_providers: int, unhealthy_count: int) -> DegradationLevel:
        """Compute the appropriate global level based on unhealthy ratio.

        Parameters
        ----------
        total_providers:
            Total number of provider deployments.
        unhealthy_count:
            Number currently unhealthy (circuit open).

        Returns
        -------
        DegradationLevel
            The recommended level after escalation.
        """
        if total_providers <= 0:
            return DegradationLevel.NORMAL

        ratio = unhealthy_count / total_providers
        degraded_t, limited_t, emergency_t = self._thresholds

        if ratio >= emergency_t:
            level = DegradationLevel.EMERGENCY
        elif ratio >= limited_t:
            level = DegradationLevel.LIMITED
        elif ratio >= degraded_t:
            level = DegradationLevel.DEGRADED
        else:
            level = DegradationLevel.NORMAL

        self.set_global_level(level, reason=f"{unhealthy_count}/{total_providers} providers unhealthy")
        return level

    # ------------------------------------------------------------------
    # Request filtering
    # ------------------------------------------------------------------

    def should_reject(self, provider: str | None = None) -> bool:
        """Return True if requests should be rejected under current policy."""
        policy = self.get_policy()
        if policy.reject_new_requests:
            return True
        if provider:
            plevel = self.get_provider_level(provider)
            ppolicy = self.get_policy(plevel)
            return ppolicy.reject_new_requests
        return False

    def should_queue(self, provider: str | None = None) -> bool:
        """Return True if requests should be queued."""
        policy = self.get_policy()
        if policy.queue_requests:
            return True
        if provider:
            plevel = self.get_provider_level(provider)
            ppolicy = self.get_policy(plevel)
            return ppolicy.queue_requests
        return False

    def effective_max_tokens(self) -> int | None:
        """Return the effective max_tokens override, or ``None`` for unlimited."""
        policy = self.get_policy()
        return policy.max_tokens_override

    def is_model_allowed(self, model: str) -> bool:
        """Check whether *model* is allowed under the current policy."""
        policy = self.get_policy()
        if not policy.allowed_models:
            return True
        return model in policy.allowed_models

    def is_streaming_allowed(self) -> bool:
        policy = self.get_policy()
        return not policy.disable_streaming

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        provider_levels: dict[str, int] = {}
        for s in self._provider_status.values():
            provider_levels[s.level.value] = provider_levels.get(s.level.value, 0) + 1

        return {
            "global_level": self._global_status.level.value,
            "global_reason": self._global_status.reason,
            "provider_count": len(self._provider_status),
            "provider_levels": provider_levels,
            "policy": {
                "reject": self.get_policy().reject_new_requests,
                "queue": self.get_policy().queue_requests,
                "max_tokens": self.get_policy().max_tokens_override,
                "streaming": self.is_streaming_allowed(),
            },
        }
