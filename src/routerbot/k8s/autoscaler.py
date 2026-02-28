"""Auto-scaler for RouterBot Kubernetes deployments.

Implements Horizontal Pod Autoscaler (HPA) logic based on CPU, memory,
and custom request-per-second metrics. Supports cooldown periods and
scale-up/scale-down policies.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from routerbot.k8s.models import (
    AutoscalingSpec,
    LLMGateway,
    ScalingDirection,
    ScalingEvent,
)

logger = logging.getLogger(__name__)


class Autoscaler:
    """Horizontal Pod Autoscaler for LLMGateway resources.

    Evaluates current metrics against target thresholds and computes
    the desired replica count, respecting min/max bounds and cooldowns.
    """

    def __init__(self) -> None:
        self._last_scale_up: dict[str, datetime] = {}
        self._last_scale_down: dict[str, datetime] = {}
        self._events: list[ScalingEvent] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        gateway: LLMGateway,
        metrics: dict[str, float],
    ) -> ScalingEvent:
        """Evaluate scaling for a gateway given current metrics.

        Parameters
        ----------
        gateway:
            The LLMGateway resource to evaluate.
        metrics:
            Current metric values. Expected keys:
            ``cpu_percent``, ``memory_percent``, ``rps`` (optional).

        Returns
        -------
        ScalingEvent:
            The scaling decision (direction may be ``none``).
        """
        spec = gateway.spec.autoscaling
        if spec is None or not spec.enabled:
            return ScalingEvent(
                gateway_name=gateway.metadata.name,
                direction=ScalingDirection.NONE,
                from_replicas=gateway.status.replicas,
                to_replicas=gateway.status.replicas,
                reason="Autoscaling disabled",
                metrics=metrics,
                timestamp=datetime.now(tz=UTC),
            )

        current = gateway.status.replicas or gateway.spec.replicas
        desired = self._compute_desired(spec, current, metrics)

        # Clamp
        desired = max(spec.min_replicas, min(spec.max_replicas, desired))

        gw_key = f"{gateway.metadata.namespace}/{gateway.metadata.name}"

        if desired > current:
            direction = ScalingDirection.UP
            reason = self._build_reason(spec, metrics, "scale-up")
            if not self._cooldown_ok(gw_key, direction, spec):
                return self._no_scale_event(gateway, metrics, "Cooldown active (scale-up)")
        elif desired < current:
            direction = ScalingDirection.DOWN
            reason = self._build_reason(spec, metrics, "scale-down")
            if not self._cooldown_ok(gw_key, direction, spec):
                return self._no_scale_event(gateway, metrics, "Cooldown active (scale-down)")
        else:
            return self._no_scale_event(gateway, metrics, "No scaling needed")

        # Record cooldown timestamp
        now = datetime.now(tz=UTC)
        if direction == ScalingDirection.UP:
            self._last_scale_up[gw_key] = now
        else:
            self._last_scale_down[gw_key] = now

        event = ScalingEvent(
            gateway_name=gateway.metadata.name,
            direction=direction,
            from_replicas=current,
            to_replicas=desired,
            reason=reason,
            metrics=metrics,
            timestamp=now,
        )
        self._events.append(event)
        return event

    def apply_scaling(self, gateway: LLMGateway, event: ScalingEvent) -> LLMGateway:
        """Apply a scaling decision to a gateway (mutates in place)."""
        if event.direction == ScalingDirection.NONE:
            return gateway

        gateway.spec.replicas = event.to_replicas
        gateway.status.replicas = event.to_replicas
        gateway.status.ready_replicas = event.to_replicas
        gateway.status.available_replicas = event.to_replicas
        gateway.status.last_updated = datetime.now(tz=UTC)
        return gateway

    @property
    def events(self) -> list[ScalingEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    def stats(self) -> dict[str, Any]:
        scale_ups = sum(1 for e in self._events if e.direction == ScalingDirection.UP)
        scale_downs = sum(1 for e in self._events if e.direction == ScalingDirection.DOWN)
        return {
            "total_events": len(self._events),
            "scale_ups": scale_ups,
            "scale_downs": scale_downs,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_desired(
        spec: AutoscalingSpec,
        current: int,
        metrics: dict[str, float],
    ) -> int:
        """Compute desired replica count from metrics."""
        ratios: list[float] = []

        cpu = metrics.get("cpu_percent")
        if cpu is not None and spec.target_cpu_percent:
            ratios.append(cpu / spec.target_cpu_percent)

        mem = metrics.get("memory_percent")
        if mem is not None and spec.target_memory_percent:
            ratios.append(mem / spec.target_memory_percent)

        rps = metrics.get("rps")
        if rps is not None and spec.target_rps is not None:
            ratios.append(rps / spec.target_rps)

        if not ratios:
            return current

        # Use the maximum ratio to determine scaling (most constrained resource)
        max_ratio = max(ratios)
        import math

        return math.ceil(current * max_ratio)

    @staticmethod
    def _build_reason(
        spec: AutoscalingSpec,
        metrics: dict[str, float],
        action: str,
    ) -> str:
        parts: list[str] = [f"{action}:"]
        cpu = metrics.get("cpu_percent")
        if cpu is not None:
            parts.append(f"CPU={cpu:.0f}% (target={spec.target_cpu_percent}%)")
        mem = metrics.get("memory_percent")
        if mem is not None:
            parts.append(f"Memory={mem:.0f}% (target={spec.target_memory_percent}%)")
        rps = metrics.get("rps")
        if rps is not None and spec.target_rps is not None:
            parts.append(f"RPS={rps:.0f} (target={spec.target_rps})")
        return " ".join(parts)

    def _cooldown_ok(
        self,
        gw_key: str,
        direction: ScalingDirection,
        spec: AutoscalingSpec,
    ) -> bool:
        """Check if enough time has passed since the last scaling event."""
        now = datetime.now(tz=UTC)
        if direction == ScalingDirection.UP:
            last = self._last_scale_up.get(gw_key)
            cooldown = spec.scale_up_cooldown_seconds
        else:
            last = self._last_scale_down.get(gw_key)
            cooldown = spec.scale_down_cooldown_seconds

        if last is None:
            return True
        return (now - last).total_seconds() >= cooldown

    @staticmethod
    def _no_scale_event(
        gateway: LLMGateway,
        metrics: dict[str, float],
        reason: str,
    ) -> ScalingEvent:
        return ScalingEvent(
            gateway_name=gateway.metadata.name,
            direction=ScalingDirection.NONE,
            from_replicas=gateway.status.replicas,
            to_replicas=gateway.status.replicas,
            reason=reason,
            metrics=metrics,
            timestamp=datetime.now(tz=UTC),
        )
