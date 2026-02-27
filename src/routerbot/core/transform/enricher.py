"""Request enrichment transform.

Enriches completion requests with extra context pulled from static
strings, HTTP headers, or key/team metadata.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from routerbot.core.transform.pipeline import TransformHook

if TYPE_CHECKING:
    from routerbot.core.transform.models import (
        EnrichmentSource,
        TransformContext,
        TransformResult,
        TransformStage,
    )

logger = logging.getLogger(__name__)


class RequestEnricher(TransformHook):
    """Enriches requests with additional context from configured sources.

    Supported source types:

    * **static** — injects a fixed string as a system message
    * **header** — reads a value from ``context.metadata["headers"]``
    * **metadata** — reads a value from ``context.metadata``
    """

    def __init__(self, sources: list[EnrichmentSource]) -> None:
        self._sources = [s for s in sources if s.enabled]

    @property
    def name(self) -> str:
        return "request_enricher"

    @property
    def stage(self) -> TransformStage:
        from routerbot.core.transform.models import TransformStage

        return TransformStage.PRE_REQUEST

    @property
    def sources(self) -> list[EnrichmentSource]:
        return list(self._sources)

    # ── Core logic ──────────────────────────────────────────────────

    async def apply(
        self,
        data: dict[str, Any],
        context: TransformContext,
    ) -> TransformResult:
        from routerbot.core.transform.models import TransformResult

        messages: list[dict[str, Any]] = data.get("messages", [])
        modified = False
        applied: list[str] = []

        for source in self._sources:
            if not self._matches(source, context):
                continue

            content = self._resolve_content(source, context)
            if not content:
                continue

            msg = {"role": "system", "content": content}

            if source.position == "prepend":
                messages.insert(0, msg)
            else:
                messages.append(msg)

            modified = True
            applied.append(source.name)

        if modified:
            data["messages"] = messages

        return TransformResult(
            modified=modified,
            metadata={"applied_sources": applied} if applied else {},
        )

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _matches(source: EnrichmentSource, context: TransformContext) -> bool:
        """Check if source should apply for the current context."""
        if source.team_ids and (context.team_id not in source.team_ids):
            return False
        return not (source.models and (context.model not in source.models))

    @staticmethod
    def _resolve_content(source: EnrichmentSource, context: TransformContext) -> str | None:
        """Resolve the enrichment content from the appropriate source."""
        if source.source_type == "static":
            return source.content

        if source.source_type == "header":
            headers = context.metadata.get("headers", {})
            return headers.get(source.header_name) if source.header_name else None

        if source.source_type == "metadata":
            return str(context.metadata.get(source.metadata_key, "")) if source.metadata_key else None

        logger.warning("Unknown enrichment source type: %s", source.source_type)
        return None
