"""Region-aware routing and cross-region failover.

Provides geographic proximity-based provider selection with automatic
failover to the nearest healthy region when the primary is unavailable.

Uses the Haversine formula to compute distances between regions.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from routerbot.core.resilience.models import (
    ProviderRegion,
    Region,
    RegionRoutingConfig,
)

logger = logging.getLogger(__name__)

# Earth radius in kilometres
_EARTH_RADIUS_KM = 6371.0


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute the Haversine distance (km) between two lat/lon points."""
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


class RegionRouter:
    """Region-aware provider routing with failover.

    Parameters
    ----------
    config:
        Region definitions, provider-region mappings, and failover rules.
    """

    def __init__(self, config: RegionRoutingConfig | None = None) -> None:
        self.config = config or RegionRoutingConfig()
        self._regions: dict[str, Region] = {r.name: r for r in self.config.regions}
        self._provider_regions: list[ProviderRegion] = list(self.config.provider_regions)
        # Pre-compute region distances
        self._distances: dict[tuple[str, str], float] = self._compute_distances()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select_provider(
        self,
        provider_name: str,
        client_region: str | None = None,
    ) -> ProviderRegion | None:
        """Select the best deployment for *provider_name* based on proximity.

        Parameters
        ----------
        provider_name:
            Logical provider name (e.g. ``"openai/gpt-4o"``).
        client_region:
            The requesting client's region.  Falls back to ``default_region``.

        Returns
        -------
        ProviderRegion | None
            The selected deployment, or *None* if no healthy deployment found.
        """
        region = client_region or self.config.default_region
        candidates = [pr for pr in self._provider_regions if pr.provider == provider_name and pr.healthy]

        if not candidates:
            logger.warning("No healthy deployments for %s", provider_name)
            return None

        if not region or region not in self._regions:
            # No region context — return highest-weight candidate
            return max(candidates, key=lambda c: c.weight)

        # Sort by distance from client region
        ranked = self._rank_by_distance(candidates, region)
        return ranked[0] if ranked else None

    def failover(
        self,
        provider_name: str,
        failed_region: str,
        client_region: str | None = None,
    ) -> ProviderRegion | None:
        """Find the next-closest healthy deployment, excluding *failed_region*.

        Returns
        -------
        ProviderRegion | None
            Failover deployment or *None* if nothing available.
        """
        if not self.config.failover_enabled:
            return None

        region = client_region or self.config.default_region
        candidates = [
            pr
            for pr in self._provider_regions
            if pr.provider == provider_name and pr.healthy and pr.region != failed_region
        ]

        if not candidates:
            return None

        if not region or region not in self._regions:
            return max(candidates, key=lambda c: c.weight)

        ranked = self._rank_by_distance(candidates, region)

        # Apply max distance filter
        if self.config.max_failover_distance_km > 0 and ranked:
            ranked = [
                pr
                for pr in ranked
                if self._distance(region, pr.region) <= self.config.max_failover_distance_km
            ]

        return ranked[0] if ranked else None

    def mark_unhealthy(self, provider: str, region: str) -> None:
        """Mark a provider-region pair as unhealthy."""
        for pr in self._provider_regions:
            if pr.provider == provider and pr.region == region:
                pr.healthy = False
                logger.warning("Marked %s in %s as unhealthy", provider, region)
                return

    def mark_healthy(self, provider: str, region: str) -> None:
        """Mark a provider-region pair as healthy."""
        for pr in self._provider_regions:
            if pr.provider == provider and pr.region == region:
                pr.healthy = True
                logger.info("Marked %s in %s as healthy", provider, region)
                return

    def healthy_regions(self, provider: str) -> list[str]:
        """Return list of healthy region names for a provider."""
        return [pr.region for pr in self._provider_regions if pr.provider == provider and pr.healthy]

    def all_providers_in_region(self, region: str) -> list[ProviderRegion]:
        """Return all provider deployments in a region."""
        return [pr for pr in self._provider_regions if pr.region == region]

    def add_region(self, region: Region) -> None:
        """Dynamically add a region."""
        self._regions[region.name] = region
        self._distances = self._compute_distances()

    def add_provider_region(self, pr: ProviderRegion) -> None:
        """Dynamically add a provider-region mapping."""
        self._provider_regions.append(pr)

    def summary(self) -> dict[str, Any]:
        """Return a summary of regions and deployments."""
        return {
            "regions": list(self._regions.keys()),
            "deployments": len(self._provider_regions),
            "healthy": sum(1 for pr in self._provider_regions if pr.healthy),
            "unhealthy": sum(1 for pr in self._provider_regions if not pr.healthy),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _rank_by_distance(self, candidates: list[ProviderRegion], from_region: str) -> list[ProviderRegion]:
        """Sort candidates by distance from *from_region*, then by weight descending."""
        return sorted(
            candidates,
            key=lambda c: (self._distance(from_region, c.region), -c.weight),
        )

    def _distance(self, r1: str, r2: str) -> float:
        """Distance in km between two named regions."""
        if r1 == r2:
            return 0.0
        key = (min(r1, r2), max(r1, r2))
        return self._distances.get(key, float("inf"))

    def _compute_distances(self) -> dict[tuple[str, str], float]:
        """Pre-compute pairwise distances between all regions."""
        regions = list(self._regions.values())
        distances: dict[tuple[str, str], float] = {}
        for i, a in enumerate(regions):
            for b in regions[i + 1 :]:
                key = (min(a.name, b.name), max(a.name, b.name))
                distances[key] = haversine(a.latitude, a.longitude, b.latitude, b.longitude)
        return distances
