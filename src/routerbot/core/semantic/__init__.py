"""Semantic routing package.

Provides intelligent request routing based on content analysis:
- Intent classification (simple → cheap model, complex → powerful model)
- Keyword/pattern matching for model capability routing
- A/B testing framework for traffic splitting
"""

from routerbot.core.semantic.classifier import IntentClassifier, SemanticRouter
from routerbot.core.semantic.models import (
    ABTestConfig,
    IntentRule,
    PatternRule,
    SemanticRoutingConfig,
)

__all__ = [
    "ABTestConfig",
    "IntentClassifier",
    "IntentRule",
    "PatternRule",
    "SemanticRouter",
    "SemanticRoutingConfig",
]
