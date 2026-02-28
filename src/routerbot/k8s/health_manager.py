"""Health-based pod management for RouterBot Kubernetes resources.

Monitors pod health, tracks readiness, and triggers remediation actions
like pod restarts when health degrades beyond thresholds.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from routerbot.k8s.models import (
    HealthStatus,
    LLMGateway,
    PodHealth,
    ReconcileEvent,
    ResourcePhase,
)

logger = logging.getLogger(__name__)


class HealthManager:
    """Health-based pod management for LLMGateway deployments.

    Tracks pod-level health metrics, determines overall gateway health,
    and provides remediation recommendations.
    """

    def __init__(
        self,
        *,
        unhealthy_threshold: int = 3,
        restart_threshold: int = 5,
        cpu_degraded_threshold: float = 90.0,
        memory_degraded_threshold: float = 85.0,
    ) -> None:
        self._unhealthy_threshold = unhealthy_threshold
        self._restart_threshold = restart_threshold
        self._cpu_degraded = cpu_degraded_threshold
        self._memory_degraded = memory_degraded_threshold

        # gateway_key -> list of PodHealth
        self._pod_states: dict[str, list[PodHealth]] = {}
        self._events: list[ReconcileEvent] = []

    # ------------------------------------------------------------------
    # Pod health reporting
    # ------------------------------------------------------------------

    def report_pod_health(
        self,
        gateway_name: str,
        namespace: str,
        pods: list[PodHealth],
    ) -> None:
        """Update health state for all pods in a gateway."""
        key = f"{namespace}/{gateway_name}"
        self._pod_states[key] = list(pods)

    def get_pod_health(
        self,
        gateway_name: str,
        namespace: str = "default",
    ) -> list[PodHealth]:
        """Get current pod health for a gateway."""
        key = f"{namespace}/{gateway_name}"
        return list(self._pod_states.get(key, []))

    # ------------------------------------------------------------------
    # Health evaluation
    # ------------------------------------------------------------------

    def evaluate_gateway_health(
        self,
        gateway: LLMGateway,
    ) -> HealthStatus:
        """Evaluate overall health of a gateway based on pod states."""
        key = f"{gateway.metadata.namespace}/{gateway.metadata.name}"
        pods = self._pod_states.get(key, [])

        if not pods:
            return HealthStatus.UNKNOWN

        healthy_count = 0
        degraded_count = 0
        unhealthy_count = 0

        for pod in pods:
            pod_status = self._classify_pod(pod)
            if pod_status == HealthStatus.HEALTHY:
                healthy_count += 1
            elif pod_status == HealthStatus.DEGRADED:
                degraded_count += 1
            else:
                unhealthy_count += 1

        total = len(pods)
        if unhealthy_count > 0 and unhealthy_count >= total // 2:
            return HealthStatus.UNHEALTHY
        if degraded_count > 0 or unhealthy_count > 0:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    def _classify_pod(self, pod: PodHealth) -> HealthStatus:
        """Classify a single pod's health."""
        if not pod.ready:
            return HealthStatus.UNHEALTHY
        if pod.restarts >= self._restart_threshold:
            return HealthStatus.UNHEALTHY
        if pod.cpu_percent >= self._cpu_degraded or pod.memory_percent >= self._memory_degraded:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    # ------------------------------------------------------------------
    # Remediation
    # ------------------------------------------------------------------

    def check_and_remediate(
        self,
        gateway: LLMGateway,
    ) -> list[str]:
        """Check health and return list of remediation actions taken.

        Returns a list of action descriptions (e.g. "restart pod-xyz").
        In a real operator these would be Kubernetes API calls.
        """
        key = f"{gateway.metadata.namespace}/{gateway.metadata.name}"
        pods = self._pod_states.get(key, [])
        actions: list[str] = []

        for pod in pods:
            status = self._classify_pod(pod)

            if status == HealthStatus.UNHEALTHY:
                if pod.restarts >= self._restart_threshold:
                    actions.append(f"evict {pod.pod_name} (restarts={pod.restarts})")
                    self._emit(
                        kind="LLMGateway",
                        name=gateway.metadata.name,
                        ns=gateway.metadata.namespace,
                        action="PodEvicted",
                        message=f"Pod {pod.pod_name} evicted: {pod.restarts} restarts",
                    )
                elif not pod.ready:
                    actions.append(f"restart {pod.pod_name} (not ready)")
                    self._emit(
                        kind="LLMGateway",
                        name=gateway.metadata.name,
                        ns=gateway.metadata.namespace,
                        action="PodRestarted",
                        message=f"Pod {pod.pod_name} restarted: not ready",
                    )

            elif status == HealthStatus.DEGRADED:
                reasons: list[str] = []
                if pod.cpu_percent >= self._cpu_degraded:
                    reasons.append(f"cpu={pod.cpu_percent:.0f}%")
                if pod.memory_percent >= self._memory_degraded:
                    reasons.append(f"mem={pod.memory_percent:.0f}%")
                if reasons:
                    actions.append(f"warn {pod.pod_name} ({', '.join(reasons)})")

        # Update gateway phase based on health
        overall = self.evaluate_gateway_health(gateway)
        if overall == HealthStatus.UNHEALTHY:
            gateway.status.phase = ResourcePhase.FAILED
        elif overall == HealthStatus.DEGRADED:
            gateway.status.phase = ResourcePhase.RUNNING  # Still running, just degraded

        return actions

    # ------------------------------------------------------------------
    # Ready replicas tracking
    # ------------------------------------------------------------------

    def count_ready_pods(
        self,
        gateway_name: str,
        namespace: str = "default",
    ) -> int:
        """Count how many pods are ready for a gateway."""
        key = f"{namespace}/{gateway_name}"
        pods = self._pod_states.get(key, [])
        return sum(1 for p in pods if p.ready)

    # ------------------------------------------------------------------
    # Events and stats
    # ------------------------------------------------------------------

    @property
    def events(self) -> list[ReconcileEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    def stats(self) -> dict[str, Any]:
        total_pods = sum(len(pods) for pods in self._pod_states.values())
        healthy_pods = sum(
            1
            for pods in self._pod_states.values()
            for p in pods
            if self._classify_pod(p) == HealthStatus.HEALTHY
        )
        return {
            "gateways_monitored": len(self._pod_states),
            "total_pods": total_pods,
            "healthy_pods": healthy_pods,
            "events": len(self._events),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit(
        self,
        *,
        kind: str,
        name: str,
        ns: str,
        action: str,
        message: str,
    ) -> None:
        self._events.append(
            ReconcileEvent(
                resource_kind=kind,
                resource_name=name,
                namespace=ns,
                action=action,
                message=message,
                timestamp=datetime.now(tz=UTC),
            ),
        )
