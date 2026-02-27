"""Auto-scaling recommendations and cost optimisation.

Analyses traffic patterns, provider usage, and cost data to generate
actionable recommendations for optimising LLM spend and scaling.
"""

from __future__ import annotations

__all__ = [
    "CostAlert",
    "CostAlertManager",
    "CostOptimiser",
    "RecommendationEngine",
    "ScalingConfig",
    "TrafficAnalyser",
    "TrafficSnapshot",
    "UsageRecommendation",
]

from routerbot.core.scaling.alerts import CostAlertManager
from routerbot.core.scaling.engine import RecommendationEngine
from routerbot.core.scaling.models import (
    CostAlert,
    ScalingConfig,
    TrafficSnapshot,
    UsageRecommendation,
)
from routerbot.core.scaling.optimiser import CostOptimiser
from routerbot.core.scaling.traffic import TrafficAnalyser
