"""Request transformation pipeline.

Provides a pluggable pipeline for modifying requests before they hit
the LLM provider and responses after they come back.  Transformations
include system-prompt injection, request enrichment, and response
post-processing hooks.
"""

from __future__ import annotations

__all__ = [
    "PromptInjector",
    "RequestEnricher",
    "RequestTransformPipeline",
    "ResponsePostProcessor",
    "TransformConfig",
    "TransformContext",
    "TransformHook",
    "TransformResult",
    "TransformStage",
]

from routerbot.core.transform.enricher import RequestEnricher
from routerbot.core.transform.models import (
    TransformConfig,
    TransformContext,
    TransformResult,
    TransformStage,
)
from routerbot.core.transform.pipeline import (
    RequestTransformPipeline,
    TransformHook,
)
from routerbot.core.transform.postprocessor import ResponsePostProcessor
from routerbot.core.transform.prompt_injector import PromptInjector
