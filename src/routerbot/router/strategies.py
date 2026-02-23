"""Load balancing strategies for the RouterBot router.

Each strategy selects a deployment from a list of available deployments
for a given model. All strategies implement the ``Strategy`` protocol.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from routerbot.router.router import Deployment


class Strategy(Protocol):
    """Protocol for routing strategies."""

    def select(self, deployments: list[Deployment]) -> Deployment | None:
        """Select a deployment from the available list.

        Parameters
        ----------
        deployments:
            List of healthy, available deployments.

        Returns
        -------
        Deployment | None
            The selected deployment, or None if no deployments are available.
        """
        ...


class RoundRobinStrategy:
    """Rotate through deployments in order.

    Each call increments the internal counter, distributing requests
    evenly across all available deployments.
    """

    def __init__(self) -> None:
        self._counter = 0

    def select(self, deployments: list[Deployment]) -> Deployment | None:
        if not deployments:
            return None
        deployment = deployments[self._counter % len(deployments)]
        self._counter += 1
        return deployment


class LeastConnectionsStrategy:
    """Route to the deployment with the fewest active requests."""

    def select(self, deployments: list[Deployment]) -> Deployment | None:
        if not deployments:
            return None
        return min(deployments, key=lambda d: d.active_requests)


class LatencyBasedStrategy:
    """Route to the deployment with the lowest rolling average latency."""

    def select(self, deployments: list[Deployment]) -> Deployment | None:
        if not deployments:
            return None
        # Deployments with no latency data get priority (prefer untested ones)
        return min(
            deployments,
            key=lambda d: d.avg_latency_ms if d.avg_latency_ms > 0 else float("inf"),
        )


class CostBasedStrategy:
    """Route to the cheapest deployment (by input cost per token)."""

    def select(self, deployments: list[Deployment]) -> Deployment | None:
        if not deployments:
            return None
        # Fall back to round-robin if no cost info is available
        with_cost = [d for d in deployments if d.cost_per_token is not None]
        if not with_cost:
            return random.choice(deployments)  # noqa: S311
        return min(with_cost, key=lambda d: d.cost_per_token or 0.0)


class WeightedStrategy:
    """Weighted random selection across deployments.

    Each deployment's ``weight`` field determines its probability of
    being selected relative to other deployments.
    """

    def select(self, deployments: list[Deployment]) -> Deployment | None:
        if not deployments:
            return None
        weights = [max(d.weight, 1) for d in deployments]
        return random.choices(deployments, weights=weights, k=1)[0]  # noqa: S311


def get_strategy(name: str) -> Strategy:
    """Return a strategy instance by name.

    Parameters
    ----------
    name:
        Strategy name. One of: ``round-robin``, ``least-connections``,
        ``latency-based``, ``cost-based``, ``weighted``.

    Returns
    -------
    Strategy
        An instance of the appropriate strategy class.

    Raises
    ------
    ValueError
        If the strategy name is not recognized.
    """
    strategies: dict[str, Strategy] = {
        "round-robin": RoundRobinStrategy(),
        "least-connections": LeastConnectionsStrategy(),
        "latency-based": LatencyBasedStrategy(),
        "cost-based": CostBasedStrategy(),
        "weighted": WeightedStrategy(),
    }
    if name not in strategies:
        valid = ", ".join(sorted(strategies.keys()))
        raise ValueError(f"Unknown routing strategy {name!r}. Valid options: {valid}")
    return strategies[name]
