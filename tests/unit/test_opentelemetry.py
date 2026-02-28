"""Tests for the OpenTelemetry tracing callback.

Covers:
- TracerProvider creation with various sampling rates
- OpenTelemetryCallback on_request_start / end / error
- Root span + child generation span relationship
- Span attributes (model, provider, tokens, cost, latency, error)
- Error recording with exception events
- Stream event handling
- Shutdown behaviour
- create_otel_callback factory
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from opentelemetry.sdk.trace.export import (
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    TraceIdRatioBased,
)
from opentelemetry.trace import StatusCode

from routerbot.observability.callbacks import (
    RequestEndData,
    RequestErrorData,
    RequestStartData,
    StreamEventData,
)
from routerbot.observability.opentelemetry import (
    OpenTelemetryCallback,
    create_otel_callback,
    create_tracer_provider,
)

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider


# ---------------------------------------------------------------------------
# In-memory exporter for tests
# ---------------------------------------------------------------------------


class InMemorySpanExporter(SpanExporter):
    """Simple in-memory exporter for tests (not in newer OTEL SDK versions)."""

    def __init__(self) -> None:
        self._spans: list = []
        self._stopped = False

    def export(self, spans):  # type: ignore[override]
        if self._stopped:
            return SpanExportResult.FAILURE
        self._spans.extend(spans)
        return SpanExportResult.SUCCESS

    def get_finished_spans(self) -> list:
        return list(self._spans)

    def clear(self) -> None:
        self._spans.clear()

    def shutdown(self) -> None:
        self._stopped = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture()
def provider(exporter: InMemorySpanExporter) -> TracerProvider:
    """TracerProvider with in-memory exporter for test assertions."""
    prov = create_tracer_provider(
        service_name="test-routerbot",
        sampling_rate=1.0,
        exporter=exporter,
        use_batch_processor=False,  # immediate export
    )
    return prov


@pytest.fixture()
def callback(provider: TracerProvider) -> OpenTelemetryCallback:
    return OpenTelemetryCallback(tracer_provider=provider)


@pytest.fixture()
def start_data() -> RequestStartData:
    return RequestStartData(
        request_id="req-001",
        model="gpt-4o",
        messages=[{"role": "user", "content": "hello"}],
        user_id="user-42",
        team_id="team-alpha",
        key_id="key-99",
        timestamp=1700000000.0,
    )


@pytest.fixture()
def end_data() -> RequestEndData:
    return RequestEndData(
        request_id="req-001",
        model="gpt-4o",
        provider="openai",
        messages=[{"role": "user", "content": "hello"}],
        response={"choices": [{"message": {"content": "hi"}}]},
        tokens_prompt=10,
        tokens_completion=5,
        cost=0.0015,
        latency_ms=250.0,
        user_id="user-42",
        team_id="team-alpha",
        key_id="key-99",
        timestamp=1700000000.25,
    )


@pytest.fixture()
def error_data() -> RequestErrorData:
    return RequestErrorData(
        request_id="req-002",
        model="gpt-4o",
        error="Rate limit exceeded",
        error_type="RateLimitError",
        provider="openai",
        messages=[{"role": "user", "content": "hello"}],
        user_id="user-42",
        team_id="team-beta",
        key_id="key-99",
        timestamp=1700000001.0,
    )


# ===================================================================
# TracerProvider creation
# ===================================================================


class TestCreateTracerProvider:
    def test_default_always_on(self, exporter: InMemorySpanExporter) -> None:
        prov = create_tracer_provider(sampling_rate=1.0, exporter=exporter, use_batch_processor=False)
        assert prov.sampler is ALWAYS_ON

    def test_always_off(self, exporter: InMemorySpanExporter) -> None:
        prov = create_tracer_provider(sampling_rate=0.0, exporter=exporter, use_batch_processor=False)
        assert prov.sampler is ALWAYS_OFF

    def test_ratio_based(self, exporter: InMemorySpanExporter) -> None:
        prov = create_tracer_provider(sampling_rate=0.5, exporter=exporter, use_batch_processor=False)
        assert isinstance(prov.sampler, TraceIdRatioBased)

    def test_resource_service_name(self, exporter: InMemorySpanExporter) -> None:
        prov = create_tracer_provider(
            service_name="my-service",
            exporter=exporter,
            use_batch_processor=False,
        )
        attrs = dict(prov.resource.attributes)
        assert attrs["service.name"] == "my-service"

    def test_auto_creates_otlp_exporter_when_none(self) -> None:
        """When no exporter given, OTLP HTTP exporter is created."""
        prov = create_tracer_provider(
            endpoint="http://collector:4318",
            use_batch_processor=False,
        )
        # Should have one processor added
        assert len(prov._active_span_processor._span_processors) > 0
        prov.shutdown()


# ===================================================================
# OpenTelemetryCallback tests
# ===================================================================


class TestOpenTelemetryCallback:
    @pytest.mark.asyncio()
    async def test_request_start_creates_span(
        self,
        callback: OpenTelemetryCallback,
        exporter: InMemorySpanExporter,
        start_data: RequestStartData,
    ) -> None:
        await callback.on_request_start(start_data)
        # Span is stored but not ended yet
        assert "req-001" in callback._spans
        # Nothing exported yet (span not ended)
        assert len(exporter.get_finished_spans()) == 0

    @pytest.mark.asyncio()
    async def test_request_end_creates_generation_and_finishes_root(
        self,
        callback: OpenTelemetryCallback,
        exporter: InMemorySpanExporter,
        start_data: RequestStartData,
        end_data: RequestEndData,
    ) -> None:
        await callback.on_request_start(start_data)
        await callback.on_request_end(end_data)

        spans = exporter.get_finished_spans()
        # Should have 2 spans: generation (child) + root
        assert len(spans) == 2

        gen_span = next(s for s in spans if "generation" in s.name)
        root_span = next(s for s in spans if "request" in s.name)

        # Generation is a child of root
        assert gen_span.parent is not None
        assert gen_span.parent.span_id == root_span.context.span_id

    @pytest.mark.asyncio()
    async def test_request_end_span_attributes(
        self,
        callback: OpenTelemetryCallback,
        exporter: InMemorySpanExporter,
        start_data: RequestStartData,
        end_data: RequestEndData,
    ) -> None:
        await callback.on_request_start(start_data)
        await callback.on_request_end(end_data)

        spans = exporter.get_finished_spans()
        gen_span = next(s for s in spans if "generation" in s.name)
        root_span = next(s for s in spans if "request" in s.name)

        # Generation attributes
        assert gen_span.attributes["llm.model"] == "gpt-4o"
        assert gen_span.attributes["llm.provider"] == "openai"
        assert gen_span.attributes["llm.tokens.prompt"] == 10
        assert gen_span.attributes["llm.tokens.completion"] == 5
        assert gen_span.attributes["llm.tokens.total"] == 15
        assert gen_span.attributes["llm.cost"] == 0.0015
        assert gen_span.attributes["llm.latency_ms"] == 250.0
        assert gen_span.status.status_code == StatusCode.OK

        # Root span attributes
        assert root_span.attributes["llm.model"] == "gpt-4o"
        assert root_span.attributes["llm.provider"] == "openai"
        assert root_span.attributes["llm.cost"] == 0.0015
        assert root_span.status.status_code == StatusCode.OK

    @pytest.mark.asyncio()
    async def test_request_start_attributes(
        self,
        callback: OpenTelemetryCallback,
        exporter: InMemorySpanExporter,
        start_data: RequestStartData,
        end_data: RequestEndData,
    ) -> None:
        await callback.on_request_start(start_data)
        await callback.on_request_end(end_data)

        spans = exporter.get_finished_spans()
        root_span = next(s for s in spans if "request" in s.name)
        assert root_span.attributes["llm.request_id"] == "req-001"
        assert root_span.attributes["llm.user_id"] == "user-42"
        assert root_span.attributes["llm.team_id"] == "team-alpha"
        assert root_span.attributes["llm.key_id"] == "key-99"

    @pytest.mark.asyncio()
    async def test_request_error_creates_error_spans(
        self,
        callback: OpenTelemetryCallback,
        exporter: InMemorySpanExporter,
        error_data: RequestErrorData,
    ) -> None:
        # Start a request first
        start = RequestStartData(
            request_id="req-002",
            model="gpt-4o",
            user_id="user-42",
            team_id="team-beta",
        )
        await callback.on_request_start(start)
        await callback.on_request_error(error_data)

        spans = exporter.get_finished_spans()
        assert len(spans) == 2

        gen_span = next(s for s in spans if "generation" in s.name)
        root_span = next(s for s in spans if "request" in s.name)

        # Both should have ERROR status
        assert gen_span.status.status_code == StatusCode.ERROR
        assert root_span.status.status_code == StatusCode.ERROR

        # Error attributes
        assert gen_span.attributes["llm.error"] == "Rate limit exceeded"
        assert gen_span.attributes["llm.error_type"] == "RateLimitError"
        assert root_span.attributes["llm.error"] == "Rate limit exceeded"

    @pytest.mark.asyncio()
    async def test_error_span_has_exception_event(
        self,
        callback: OpenTelemetryCallback,
        exporter: InMemorySpanExporter,
        error_data: RequestErrorData,
    ) -> None:
        start = RequestStartData(request_id="req-002", model="gpt-4o")
        await callback.on_request_start(start)
        await callback.on_request_error(error_data)

        spans = exporter.get_finished_spans()
        gen_span = next(s for s in spans if "generation" in s.name)
        root_span = next(s for s in spans if "request" in s.name)

        # Both spans should have an exception event recorded
        gen_events = [e for e in gen_span.events if e.name == "exception"]
        root_events = [e for e in root_span.events if e.name == "exception"]
        assert len(gen_events) == 1
        assert len(root_events) == 1

    @pytest.mark.asyncio()
    async def test_request_end_without_start(
        self,
        callback: OpenTelemetryCallback,
        exporter: InMemorySpanExporter,
        end_data: RequestEndData,
    ) -> None:
        """on_request_end without on_request_start still creates a generation span."""
        await callback.on_request_end(end_data)
        spans = exporter.get_finished_spans()
        # At least the generation span
        assert len(spans) >= 1
        gen_span = next(s for s in spans if "generation" in s.name)
        assert gen_span.attributes["llm.model"] == "gpt-4o"

    @pytest.mark.asyncio()
    async def test_request_error_without_start(
        self,
        callback: OpenTelemetryCallback,
        exporter: InMemorySpanExporter,
        error_data: RequestErrorData,
    ) -> None:
        """on_request_error without on_request_start still creates error span."""
        await callback.on_request_error(error_data)
        spans = exporter.get_finished_spans()
        assert len(spans) >= 1
        gen_span = next(s for s in spans if "generation" in s.name)
        assert gen_span.status.status_code == StatusCode.ERROR

    @pytest.mark.asyncio()
    async def test_stream_end_updates_span(
        self,
        callback: OpenTelemetryCallback,
        exporter: InMemorySpanExporter,
    ) -> None:
        start = RequestStartData(request_id="req-003", model="gpt-4o")
        await callback.on_request_start(start)

        stream_data = StreamEventData(
            request_id="req-003",
            model="gpt-4o",
            cumulative_tokens=42,
        )
        await callback.on_stream_end(stream_data)

        # Span still open — end it via request_end
        end = RequestEndData(
            request_id="req-003",
            model="gpt-4o",
            tokens_prompt=30,
            tokens_completion=12,
        )
        await callback.on_request_end(end)

        spans = exporter.get_finished_spans()
        root_span = next(s for s in spans if "request" in s.name)
        assert root_span.attributes["llm.stream.cumulative_tokens"] == 42

    @pytest.mark.asyncio()
    async def test_stream_end_no_active_span(
        self,
        callback: OpenTelemetryCallback,
    ) -> None:
        """stream_end for unknown request_id is a no-op."""
        stream_data = StreamEventData(
            request_id="req-nonexistent",
            model="gpt-4o",
            cumulative_tokens=10,
        )
        # Should not raise
        await callback.on_stream_end(stream_data)

    @pytest.mark.asyncio()
    async def test_stream_start_noop(
        self,
        callback: OpenTelemetryCallback,
        exporter: InMemorySpanExporter,
    ) -> None:
        """on_stream_start is a no-op."""
        stream_data = StreamEventData(request_id="req-x", model="gpt-4o")
        await callback.on_stream_start(stream_data)
        assert len(exporter.get_finished_spans()) == 0

    @pytest.mark.asyncio()
    async def test_callback_name(self, callback: OpenTelemetryCallback) -> None:
        assert callback.name == "OpenTelemetryCallback"

    @pytest.mark.asyncio()
    async def test_shutdown(self, callback: OpenTelemetryCallback) -> None:
        """Shutdown should not raise."""
        await callback.shutdown()

    @pytest.mark.asyncio()
    async def test_shutdown_without_provider(self) -> None:
        """Callback without explicit provider (uses global) shuts down cleanly."""
        cb = OpenTelemetryCallback(tracer_provider=None)
        await cb.shutdown()  # should not raise

    @pytest.mark.asyncio()
    async def test_span_names(
        self,
        callback: OpenTelemetryCallback,
        exporter: InMemorySpanExporter,
        start_data: RequestStartData,
        end_data: RequestEndData,
    ) -> None:
        await callback.on_request_start(start_data)
        await callback.on_request_end(end_data)

        spans = exporter.get_finished_spans()
        names = {s.name for s in spans}
        assert "llm.request gpt-4o" in names
        assert "llm.generation gpt-4o" in names

    @pytest.mark.asyncio()
    async def test_root_span_removed_after_end(
        self,
        callback: OpenTelemetryCallback,
        start_data: RequestStartData,
        end_data: RequestEndData,
    ) -> None:
        await callback.on_request_start(start_data)
        assert "req-001" in callback._spans
        await callback.on_request_end(end_data)
        assert "req-001" not in callback._spans


# ===================================================================
# Factory function tests
# ===================================================================


class TestCreateOtelCallback:
    def test_creates_callback_with_provider(self) -> None:
        cb = create_otel_callback(
            service_name="test-svc",
            endpoint="http://localhost:4318",
            sampling_rate=0.5,
            use_batch_processor=False,
            exporter=InMemorySpanExporter(),
        )
        assert isinstance(cb, OpenTelemetryCallback)
        assert cb._provider is not None
        cb._provider.shutdown()

    def test_default_params(self) -> None:
        exporter = InMemorySpanExporter()
        cb = create_otel_callback(exporter=exporter, use_batch_processor=False)
        assert isinstance(cb, OpenTelemetryCallback)
        cb._provider.shutdown()
