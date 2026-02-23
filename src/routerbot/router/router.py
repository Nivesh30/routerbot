"""Main RouterBot router.

The :class:`Router` sits between the HTTP proxy layer and the provider
adapters. It:

1. Resolves a model name to one or more :class:`Deployment` instances.
2. Applies a load-balancing strategy to select which deployment to use.
3. Wraps the call with retry logic.
4. Falls back to alternative models on repeated failure.
5. Tracks latency and updates the cooldown manager.

The router is framework-agnostic — it has no FastAPI dependency and can
be tested independently.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from routerbot.core.config_models import RouterBotConfig
    from routerbot.core.types import (
        CompletionRequest,
        CompletionResponse,
        CompletionResponseChunk,
        EmbeddingRequest,
        EmbeddingResponse,
        ImageRequest,
        ImageResponse,
    )
    from routerbot.router.strategies import Strategy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deployment — a single configured model endpoint
# ---------------------------------------------------------------------------


@dataclass
class Deployment:
    """A single provider+model combination that the router can dispatch to.

    Attributes
    ----------
    name:
        Human-readable deployment name (same as ``model_name`` in config).
    provider_name:
        Provider key, e.g. ``"openai"`` or ``"anthropic"``.
    provider_model:
        Full provider/model string, e.g. ``"openai/gpt-4o"``.
    api_key:
        Resolved API key (None for providers that don't require one).
    api_base:
        Optional custom API base URL.
    extra_headers:
        Extra HTTP headers to pass to the provider.
    weight:
        Relative weight for the weighted strategy (default 1).
    active_requests:
        Number of in-flight requests to this deployment (for LeastConnections).
    avg_latency_ms:
        Rolling average response latency in ms (for LatencyBased).
    cost_per_token:
        Estimated input cost per token in USD (for CostBased).
    """

    name: str
    provider_name: str
    provider_model: str
    api_key: str | None = None
    api_base: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    weight: int = 1
    active_requests: int = 0
    avg_latency_ms: float = 0.0
    cost_per_token: float | None = None

    def _latency_alpha(self) -> float:
        """Smoothing factor for EMA latency (0 = no smoothing, 1 = instant)."""
        return 0.2

    def record_latency(self, latency_ms: float) -> None:
        """Update the rolling average latency using EMA."""
        alpha = self._latency_alpha()
        if self.avg_latency_ms == 0.0:
            self.avg_latency_ms = latency_ms
        else:
            self.avg_latency_ms = alpha * latency_ms + (1 - alpha) * self.avg_latency_ms


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class Router:
    """Intelligent routing layer for LLM API requests.

    Parameters
    ----------
    config:
        RouterBot configuration used to build the deployment registry.
    strategy:
        Load balancing strategy instance. Defaults to round-robin.
    max_retries:
        Maximum number of retry attempts on transient errors.
    retry_delay:
        Base delay in seconds before the first retry.
    fallbacks:
        Mapping of model name → list of fallback model names.
    allowed_fails:
        Consecutive failure threshold before entering cooldown.
    cooldown_seconds:
        Duration in seconds to keep a failing deployment in cooldown.
    """

    def __init__(
        self,
        config: RouterBotConfig | None = None,
        strategy: Strategy | None = None,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        fallbacks: dict[str, list[str]] | None = None,
        allowed_fails: int = 3,
        cooldown_seconds: int = 60,
    ) -> None:
        from routerbot.router.cooldown import CooldownManager
        from routerbot.router.strategies import RoundRobinStrategy

        self._strategy: Strategy = strategy or RoundRobinStrategy()
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._fallbacks: dict[str, list[str]] = fallbacks or {}
        self._cooldown = CooldownManager(
            allowed_fails=allowed_fails,
            cooldown_seconds=cooldown_seconds,
        )

        # Registry: model_name → list of deployments
        self._deployments: dict[str, list[Deployment]] = {}

        if config is not None:
            self._build_registry(config)

    # ------------------------------------------------------------------
    # Registry management
    # ------------------------------------------------------------------

    def _build_registry(self, config: RouterBotConfig) -> None:
        """Populate the deployment registry from a RouterBotConfig."""
        import os

        self._deployments.clear()

        for entry in config.model_list:
            provider_model = entry.provider_params.model
            if "/" not in provider_model:
                logger.warning(
                    "Skipping entry %r — provider_model %r has no '/' separator",
                    entry.model_name,
                    provider_model,
                )
                continue

            provider_name, _ = provider_model.split("/", 1)

            # Resolve env-var API key references
            api_key = entry.provider_params.api_key
            if api_key and api_key.startswith("os.environ/"):
                env_var = api_key.removeprefix("os.environ/")
                api_key = os.environ.get(env_var)

            deployment = Deployment(
                name=entry.model_name,
                provider_name=provider_name,
                provider_model=provider_model,
                api_key=api_key,
                api_base=entry.provider_params.api_base,
                extra_headers=entry.provider_params.extra_headers,
            )

            if entry.model_name not in self._deployments:
                self._deployments[entry.model_name] = []
            self._deployments[entry.model_name].append(deployment)

        # Merge fallbacks from config
        if config.router_settings and config.router_settings.fallbacks:
            for model, fb_list in config.router_settings.fallbacks.items():
                self._fallbacks.setdefault(model, []).extend(fb_list)

        logger.info(
            "Router registry built: %d model(s), %d deployment(s)",
            len(self._deployments),
            sum(len(v) for v in self._deployments.values()),
        )

    def get_deployments(self, model_name: str) -> list[Deployment]:
        """Return all (non-cooling) deployments for a model."""
        all_deps = self._deployments.get(model_name, [])
        return [d for d in all_deps if not self._cooldown.is_in_cooldown(d.name)]

    def list_models(self) -> list[str]:
        """Return the names of all registered model names."""
        return list(self._deployments.keys())

    # ------------------------------------------------------------------
    # Provider instantiation
    # ------------------------------------------------------------------

    def _make_provider(self, deployment: Deployment) -> Any:
        """Instantiate the provider for a deployment."""
        from routerbot.providers.registry import get_provider_class

        provider_cls = get_provider_class(deployment.provider_name)
        return provider_cls(
            api_key=deployment.api_key,
            api_base=deployment.api_base,
            custom_headers=deployment.extra_headers,
        )

    # ------------------------------------------------------------------
    # Dispatch helpers
    # ------------------------------------------------------------------

    def _select_deployment(self, model_name: str) -> Deployment:
        """Select and return a deployment for the given model.

        Raises
        ------
        ModelNotFoundError
            If the model is not registered or all deployments are cooling down.
        """
        from routerbot.core.exceptions import ModelNotFoundError

        if model_name not in self._deployments:
            raise ModelNotFoundError(model_name)

        available = self.get_deployments(model_name)
        if not available:
            raise ModelNotFoundError(model_name)

        selected = self._strategy.select(available)
        if selected is None:
            raise ModelNotFoundError(model_name)
        return selected

    async def _execute_with_retry(
        self,
        model_name: str,
        coro_fn: Any,
        request_id: str = "unknown",
    ) -> Any:
        """Wrap provider call with retry and cooldown tracking."""
        from routerbot.router.retry import RetryPolicy, with_retry

        policy = RetryPolicy(max_retries=self._max_retries, base_delay=self._retry_delay)

        async def attempt() -> Any:
            deployment = self._select_deployment(model_name)
            deployment.active_requests += 1
            start = time.monotonic()
            try:
                provider = self._make_provider(deployment)
                result = await coro_fn(provider)
                self._cooldown.record_success(deployment.name)
                return result
            except BaseException as exc:
                if policy.should_retry(exc):
                    self._cooldown.record_failure(deployment.name)
                raise
            finally:
                deployment.active_requests = max(0, deployment.active_requests - 1)
                elapsed_ms = (time.monotonic() - start) * 1000
                deployment.record_latency(elapsed_ms)

        return await with_retry(attempt, policy, request_id=request_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        request: CompletionRequest,
        request_id: str = "unknown",
    ) -> CompletionResponse:
        """Route a chat completion request.

        Applies retry logic and falls back through the configured fallback
        chain if all retry attempts on the primary model fail.
        """
        from routerbot.router.fallback import execute_with_fallbacks

        fallbacks = self._fallbacks.get(request.model, [])

        async def call_model(model_name: str) -> CompletionResponse:
            async def _call(provider: Any) -> Any:
                r = request.model_copy(update={"model": model_name})
                return await provider.chat_completion(r)

            return cast(
                "CompletionResponse",
                await self._execute_with_retry(model_name, _call, request_id),
            )

        return cast(
            "CompletionResponse",
            await execute_with_fallbacks(
                primary_model=request.model,
                fallback_models=fallbacks,
                provider_fn=call_model,
                request_id=request_id,
            ),
        )

    def chat_completion_stream(
        self,
        request: CompletionRequest,
        request_id: str = "unknown",
    ) -> AsyncIterator[CompletionResponseChunk]:
        """Route a streaming chat completion request.

        Returns an async iterator of :class:`CompletionResponseChunk`.
        Streaming does not support fallbacks (stream has already started
        by the time a failure would be detected).
        """
        return self._stream_completion(request, request_id)

    async def _stream_completion(
        self,
        request: CompletionRequest,
        request_id: str,
    ) -> AsyncIterator[CompletionResponseChunk]:
        """Internal generator for streaming completions."""
        deployment = self._select_deployment(request.model)
        deployment.active_requests += 1
        start = time.monotonic()
        try:
            provider = self._make_provider(deployment)
            async for chunk in provider.chat_completion_stream(request):
                yield chunk
            self._cooldown.record_success(deployment.name)
        except BaseException:
            self._cooldown.record_failure(deployment.name)
            raise
        finally:
            deployment.active_requests = max(0, deployment.active_requests - 1)
            elapsed_ms = (time.monotonic() - start) * 1000
            deployment.record_latency(elapsed_ms)

    async def embeddings(
        self,
        request: EmbeddingRequest,
        request_id: str = "unknown",
    ) -> EmbeddingResponse:
        """Route an embeddings request."""

        async def _call(provider: Any) -> Any:
            return await provider.embedding(request)

        return cast(
            "EmbeddingResponse",
            await self._execute_with_retry(request.model, _call, request_id),
        )

    async def image_generation(
        self,
        request: ImageRequest,
        request_id: str = "unknown",
    ) -> ImageResponse:
        """Route an image generation request."""

        async def _call(provider: Any) -> Any:
            return await provider.image_generation(request)

        return cast(
            "ImageResponse",
            await self._execute_with_retry(request.model, _call, request_id),
        )
