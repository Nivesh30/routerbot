"""Core request-transformation pipeline.

Implements a simple hook-based pipeline that runs a sequence of
:class:`TransformHook` objects over the request (pre) and response (post).
"""

from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from routerbot.core.transform.models import (
        TransformConfig,
        TransformContext,
        TransformResult,
        TransformStage,
    )

logger = logging.getLogger(__name__)


class TransformHook(abc.ABC):
    """Abstract base for a single transformation step.

    Sub-classes must implement :meth:`apply` and declare the ``stage``
    they belong to.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:  # pragma: no cover
        ...

    @property
    @abc.abstractmethod
    def stage(self) -> TransformStage:  # pragma: no cover
        ...

    @abc.abstractmethod
    async def apply(
        self,
        data: dict[str, Any],
        context: TransformContext,
    ) -> TransformResult:  # pragma: no cover
        """Mutate *data* in place and return a result describing what changed."""
        ...


class RequestTransformPipeline:
    """Orchestrates an ordered list of :class:`TransformHook` instances.

    Hooks are executed in registration order.  If a hook raises, it is
    logged and skipped (fail-open so the request is never blocked by a
    buggy transform).
    """

    def __init__(self, config: TransformConfig) -> None:
        self._config = config
        self._hooks: list[TransformHook] = []

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def config(self) -> TransformConfig:
        return self._config

    # ── Hook management ──────────────────────────────────────────────

    def register(self, hook: TransformHook) -> None:
        """Add a hook to the pipeline."""
        self._hooks.append(hook)
        logger.debug("Registered transform hook: %s (stage=%s)", hook.name, hook.stage)

    def unregister(self, name: str) -> bool:
        """Remove a hook by name. Returns True if found."""
        before = len(self._hooks)
        self._hooks = [h for h in self._hooks if h.name != name]
        return len(self._hooks) < before

    @property
    def hooks(self) -> list[TransformHook]:
        return list(self._hooks)

    # ── Execution ────────────────────────────────────────────────────

    async def run_pre_request(
        self,
        request_data: dict[str, Any],
        context: TransformContext,
    ) -> list[TransformResult]:
        """Run all ``PRE_REQUEST`` hooks over *request_data* (mutated in place)."""
        from routerbot.core.transform.models import TransformStage

        return await self._run_stage(TransformStage.PRE_REQUEST, request_data, context)

    async def run_post_response(
        self,
        response_data: dict[str, Any],
        context: TransformContext,
    ) -> list[TransformResult]:
        """Run all ``POST_RESPONSE`` hooks over *response_data* (mutated in place)."""
        from routerbot.core.transform.models import TransformStage

        return await self._run_stage(TransformStage.POST_RESPONSE, response_data, context)

    async def _run_stage(
        self,
        stage: TransformStage,
        data: dict[str, Any],
        context: TransformContext,
    ) -> list[TransformResult]:
        """Execute all hooks matching *stage*, returning their results."""
        from routerbot.core.transform.models import TransformResult

        results: list[TransformResult] = []
        for hook in self._hooks:
            if hook.stage != stage:
                continue
            try:
                result = await hook.apply(data, context)
                results.append(result)
                if result.modified:
                    logger.debug("Transform hook '%s' modified data", hook.name)
            except Exception:
                logger.exception("Transform hook '%s' failed — skipping", hook.name)
                results.append(TransformResult(modified=False, metadata={"error": "hook failed"}))
        return results
