"""OpenTelemetry tracing callback for LLM request observability.

Produces distributed traces that can be exported to any
OpenTelemetry-compatible backend (Jaeger, Zipkin, Datadog, Grafana
Tempo, etc.) via the OTLP HTTP exporter.

Features:

- **Span per request** — a root span is created when a request starts
  and finished when it ends (or errors).
- **Child spans for provider calls** — the generation/provider call
  is recorded as a nested child span.
- **W3C trace-context propagation** — trace and span IDs follow the
  W3C ``traceparent`` / ``tracestate`` headers.
- **Configurable sampling** — control the percentage of requests
  traced to manage overhead.
- **Rich attributes** — model, provider, tokens, cost, user, team,
  latency, and error details.

Configuration::

    observability:
      opentelemetry:
        enabled: true
        endpoint: "http://localhost:4318"
        service_name: "routerbot"
        sampling_rate: 0.1
        export_format: "otlp"
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    TraceIdRatioBased,
)
from opentelemetry.trace import StatusCode

from routerbot.observability.callbacks import (
    BaseCallback,
    RequestEndData,
    RequestErrorData,
    RequestStartData,
    StreamEventData,
)

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import Span

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def create_tracer_provider(
    *,
    service_name: str = "routerbot",
    endpoint: str = "http://localhost:4318",
    sampling_rate: float = 1.0,
    exporter: SpanExporter | None = None,
    use_batch_processor: bool = True,
) -> TracerProvider:
    """Create and configure an OpenTelemetry :class:`TracerProvider`.

    Parameters
    ----------
    service_name:
        The ``service.name`` resource attribute.
    endpoint:
        OTLP HTTP endpoint for the collector.
    sampling_rate:
        Fraction of requests to sample (0.0-1.0).
        ``1.0`` means sample everything; ``0.0`` means sample nothing.
    exporter:
        An explicit :class:`SpanExporter` instance (useful for tests).
        When ``None``, the OTLP HTTP exporter targeting *endpoint* is
        created automatically.
    use_batch_processor:
        When ``True`` (default), a :class:`BatchSpanProcessor` is used
        for production performance.  Set to ``False`` for tests where
        immediate export is desired.
    """
    # Sampler
    if sampling_rate >= 1.0:
        sampler = ALWAYS_ON
    elif sampling_rate <= 0.0:
        sampler = ALWAYS_OFF
    else:
        sampler = TraceIdRatioBased(sampling_rate)

    resource = Resource.create({"service.name": service_name})

    provider = TracerProvider(resource=resource, sampler=sampler)

    # Exporter
    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")

    if use_batch_processor:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        provider.add_span_processor(SimpleSpanProcessor(exporter))

    return provider


# ---------------------------------------------------------------------------
# OpenTelemetry Callback
# ---------------------------------------------------------------------------


class OpenTelemetryCallback(BaseCallback):
    """Callback that creates OpenTelemetry traces for LLM requests.

    Each request starts a **root span** at ``on_request_start``.  When
    the request completes (``on_request_end``) or fails
    (``on_request_error``), the span is enriched with attributes and
    finished.  A child **generation span** is created on completion to
    represent the LLM provider call.

    Parameters
    ----------
    tracer_provider:
        A configured :class:`TracerProvider`.  If ``None``, the global
        provider is used.
    tracer_name:
        Instrumentation library name (defaults to ``"routerbot"``).
    """

    def __init__(
        self,
        tracer_provider: TracerProvider | None = None,
        *,
        tracer_name: str = "routerbot",
    ) -> None:
        self._provider = tracer_provider
        self._tracer = tracer_provider.get_tracer(tracer_name) if tracer_provider else trace.get_tracer(tracer_name)
        # Active spans keyed by request_id
        self._spans: dict[str, Span] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Shut down the tracer provider flushing pending spans."""
        if self._provider is not None:
            self._provider.shutdown()

    # ------------------------------------------------------------------
    # Callback methods
    # ------------------------------------------------------------------

    async def on_request_start(self, data: RequestStartData) -> None:
        """Start a root span for the LLM request."""
        span = self._tracer.start_span(
            name=f"llm.request {data.model}",
            attributes={
                "llm.request_id": data.request_id,
                "llm.model": data.model,
                "llm.user_id": data.user_id or "",
                "llm.team_id": data.team_id or "",
                "llm.key_id": data.key_id or "",
            },
        )
        self._spans[data.request_id] = span

    async def on_request_end(self, data: RequestEndData) -> None:
        """Finish the root span and create a child generation span."""
        root_span = self._spans.pop(data.request_id, None)

        # Create a generation child span (under root context)
        ctx = trace.set_span_in_context(root_span) if root_span is not None else None

        total_tokens = data.tokens_prompt + data.tokens_completion
        gen_attrs: dict[str, Any] = {
            "llm.request_id": data.request_id,
            "llm.model": data.model,
            "llm.provider": data.provider,
            "llm.tokens.prompt": data.tokens_prompt,
            "llm.tokens.completion": data.tokens_completion,
            "llm.tokens.total": total_tokens,
            "llm.cost": data.cost,
            "llm.latency_ms": data.latency_ms,
        }

        gen_span = self._tracer.start_span(
            name=f"llm.generation {data.model}",
            context=ctx,
            attributes=gen_attrs,
        )
        gen_span.set_status(StatusCode.OK)
        gen_span.end()

        # Finish root span
        if root_span is not None:
            root_span.set_attribute("llm.provider", data.provider)
            root_span.set_attribute("llm.tokens.prompt", data.tokens_prompt)
            root_span.set_attribute("llm.tokens.completion", data.tokens_completion)
            root_span.set_attribute("llm.tokens.total", total_tokens)
            root_span.set_attribute("llm.cost", data.cost)
            root_span.set_attribute("llm.latency_ms", data.latency_ms)
            root_span.set_status(StatusCode.OK)
            root_span.end()

    async def on_request_error(self, data: RequestErrorData) -> None:
        """Finish the root span with an error status."""
        root_span = self._spans.pop(data.request_id, None)

        # Create an error generation span
        ctx = trace.set_span_in_context(root_span) if root_span is not None else None

        gen_attrs: dict[str, Any] = {
            "llm.request_id": data.request_id,
            "llm.model": data.model,
            "llm.provider": data.provider,
            "llm.error": data.error,
            "llm.error_type": data.error_type,
        }

        gen_span = self._tracer.start_span(
            name=f"llm.generation {data.model}",
            context=ctx,
            attributes=gen_attrs,
        )
        gen_span.set_status(StatusCode.ERROR, data.error)
        gen_span.record_exception(Exception(data.error))
        gen_span.end()

        # Finish root span with error
        if root_span is not None:
            root_span.set_attribute("llm.provider", data.provider)
            root_span.set_attribute("llm.error", data.error)
            root_span.set_attribute("llm.error_type", data.error_type)
            root_span.set_status(StatusCode.ERROR, data.error)
            root_span.record_exception(Exception(data.error))
            root_span.end()

    async def on_stream_start(self, data: StreamEventData) -> None:
        """No-op - stream events don't create separate OTEL spans."""

    async def on_stream_end(self, data: StreamEventData) -> None:
        """Record cumulative stream tokens on the root span."""
        span = self._spans.get(data.request_id)
        if span is not None:
            span.set_attribute("llm.stream.cumulative_tokens", data.cumulative_tokens)


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def create_otel_callback(
    *,
    service_name: str = "routerbot",
    endpoint: str = "http://localhost:4318",
    sampling_rate: float = 1.0,
    exporter: SpanExporter | None = None,
    use_batch_processor: bool = True,
) -> OpenTelemetryCallback:
    """Create an :class:`OpenTelemetryCallback` with a fresh provider.

    This is the recommended entry point for production use.
    """
    provider = create_tracer_provider(
        service_name=service_name,
        endpoint=endpoint,
        sampling_rate=sampling_rate,
        exporter=exporter,
        use_batch_processor=use_batch_processor,
    )
    return OpenTelemetryCallback(tracer_provider=provider)
