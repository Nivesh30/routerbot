"""Model catalogue and comparison engine.

Maintains a registry of available models with pricing, capabilities,
and provides side-by-side model comparison.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from routerbot.hub.models import (
    ComparisonRequest,
    ComparisonResponse,
    ComparisonResult,
    ModelCapability,
    ModelCatalogue,
    ModelInfo,
    ModelPricing,
)

logger = logging.getLogger(__name__)


class ModelHub:
    """Model catalogue and comparison engine.

    Parameters
    ----------
    handler:
        Async callable ``(model, messages, params) -> (response_text, input_tokens,
        output_tokens)`` for running inference.  If *None*, a stub handler is used.
    """

    def __init__(self, handler: Any = None) -> None:
        self._catalogue = ModelCatalogue()
        self._handler = handler or _default_handler

    # -- Catalogue management ------------------------------------------------

    def register_model(self, info: ModelInfo) -> None:
        """Register or update a model in the catalogue."""
        # Replace if already exists
        self._catalogue.models = [
            m for m in self._catalogue.models if m.model_id != info.model_id
        ]
        self._catalogue.models.append(info)
        self._catalogue.updated_at = datetime.now(tz=UTC)
        logger.info("Model %s registered", info.model_id)

    def unregister_model(self, model_id: str) -> bool:
        """Remove a model from the catalogue.  Returns True if removed."""
        before = len(self._catalogue.models)
        self._catalogue.models = [
            m for m in self._catalogue.models if m.model_id != model_id
        ]
        return len(self._catalogue.models) < before

    def get_model(self, model_id: str) -> ModelInfo | None:
        """Get a model by ID."""
        for m in self._catalogue.models:
            if m.model_id == model_id:
                return m
        return None

    def list_models(
        self,
        *,
        provider: str | None = None,
        capability: ModelCapability | None = None,
        available_only: bool = True,
    ) -> list[ModelInfo]:
        """List models with optional filters."""
        models = self._catalogue.models
        if available_only:
            models = [m for m in models if m.is_available]
        if provider:
            models = [m for m in models if m.provider == provider]
        if capability:
            models = [m for m in models if capability in m.capabilities]
        return models

    def get_catalogue(self) -> ModelCatalogue:
        """Return the full catalogue."""
        return self._catalogue

    def get_providers(self) -> list[str]:
        """Return the list of providers in the catalogue."""
        return self._catalogue.providers

    # -- Comparison engine ---------------------------------------------------

    async def compare(self, request: ComparisonRequest) -> ComparisonResponse:
        """Run an inference comparison across multiple models.

        Each model receives the same messages and parameters.
        Results are gathered concurrently.
        """
        request_id = f"cmp_{uuid.uuid4().hex[:12]}"

        async def _run_model(model_id: str) -> ComparisonResult:
            start = time.monotonic()
            try:
                response_text, in_tok, out_tok = await self._handler(
                    model_id, request.messages, request.parameters
                )
                latency = (time.monotonic() - start) * 1000

                # Estimate cost from catalogue
                model = self.get_model(model_id)
                cost = 0.0
                if model:
                    cost = (
                        in_tok * model.pricing.input_cost_per_1k / 1000
                        + out_tok * model.pricing.output_cost_per_1k / 1000
                    )

                return ComparisonResult(
                    model_id=model_id,
                    response=response_text,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    latency_ms=latency,
                    cost=cost,
                )
            except Exception as exc:
                latency = (time.monotonic() - start) * 1000
                return ComparisonResult(
                    model_id=model_id,
                    error=str(exc),
                    latency_ms=latency,
                )

        tasks = [_run_model(mid) for mid in request.models]
        results = await asyncio.gather(*tasks)

        return ComparisonResponse(
            request_id=request_id,
            results=list(results),
            created_at=datetime.now(tz=UTC),
        )

    # -- Bulk registration helpers -------------------------------------------

    def register_defaults(self) -> None:
        """Register a set of well-known default models."""
        defaults = [
            ModelInfo(
                model_id="openai/gpt-4o",
                provider="openai",
                display_name="GPT-4o",
                description="OpenAI GPT-4o flagship multimodal model",
                capabilities=[
                    ModelCapability.CHAT,
                    ModelCapability.VISION,
                    ModelCapability.FUNCTION_CALLING,
                    ModelCapability.STREAMING,
                    ModelCapability.JSON_MODE,
                ],
                pricing=ModelPricing(input_cost_per_1k=0.0025, output_cost_per_1k=0.01),
                context_window=128000,
                max_output_tokens=16384,
            ),
            ModelInfo(
                model_id="openai/gpt-4o-mini",
                provider="openai",
                display_name="GPT-4o Mini",
                description="Fast, affordable small model",
                capabilities=[
                    ModelCapability.CHAT,
                    ModelCapability.FUNCTION_CALLING,
                    ModelCapability.STREAMING,
                    ModelCapability.JSON_MODE,
                ],
                pricing=ModelPricing(input_cost_per_1k=0.00015, output_cost_per_1k=0.0006),
                context_window=128000,
                max_output_tokens=16384,
            ),
            ModelInfo(
                model_id="anthropic/claude-sonnet-4-20250514",
                provider="anthropic",
                display_name="Claude Sonnet 4",
                description="Anthropic Claude Sonnet 4",
                capabilities=[
                    ModelCapability.CHAT,
                    ModelCapability.VISION,
                    ModelCapability.FUNCTION_CALLING,
                    ModelCapability.STREAMING,
                ],
                pricing=ModelPricing(input_cost_per_1k=0.003, output_cost_per_1k=0.015),
                context_window=200000,
                max_output_tokens=8192,
            ),
            ModelInfo(
                model_id="google/gemini-2.0-flash",
                provider="google",
                display_name="Gemini 2.0 Flash",
                description="Google Gemini 2.0 Flash",
                capabilities=[
                    ModelCapability.CHAT,
                    ModelCapability.VISION,
                    ModelCapability.STREAMING,
                ],
                pricing=ModelPricing(input_cost_per_1k=0.0001, output_cost_per_1k=0.0004),
                context_window=1000000,
                max_output_tokens=8192,
            ),
        ]
        for m in defaults:
            self.register_model(m)


async def _default_handler(
    model_id: str, messages: list[dict[str, Any]], parameters: dict[str, Any]
) -> tuple[str, int, int]:
    """Default stub handler that returns a placeholder response."""
    content = messages[-1].get("content", "") if messages else ""
    return (
        f"[{model_id}] Response to: {content[:100]}",
        len(content) // 4,
        50,
    )
