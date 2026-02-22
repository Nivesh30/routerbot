# Stage 5: Observability & Monitoring

**Duration:** 2-3 weeks  
**Priority:** High — essential for production operations  
**Depends on:** Stage 1, Stage 3 (Proxy Server)  
**Agents:** Backend Engineer, DevOps Engineer

---

## Objective

Build a comprehensive observability stack: callback system for logging to external services, Prometheus metrics, OpenTelemetry tracing, log export to cloud storage, and team-based logging controls. All features are fully open source — team-based logging and log export are NOT gated behind an enterprise license.

---

## Prerequisites

- Stage 1 complete: core types, config, logging
- Stage 3 complete: proxy server with middleware pipeline
- Stage 4 started (at minimum: key/user/team models in DB)

---

## Tasks

### 5.1 — Callback System

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

Build the extensible callback system that fires on LLM request lifecycle events.

**Deliverables:**
- [ ] `src/routerbot/observability/callbacks.py` — Callback manager
  ```python
  class CallbackEvent(StrEnum):
      REQUEST_START = "request_start"
      REQUEST_END = "request_end"
      REQUEST_ERROR = "request_error"
      STREAM_START = "stream_start"
      STREAM_CHUNK = "stream_chunk"
      STREAM_END = "stream_end"
  
  class BaseCallback(ABC):
      @abstractmethod
      async def on_request_start(self, data: RequestStartData) -> None: ...
      @abstractmethod
      async def on_request_end(self, data: RequestEndData) -> None: ...
      @abstractmethod
      async def on_request_error(self, data: RequestErrorData) -> None: ...
  
  class CallbackManager:
      """Manages and dispatches to registered callbacks."""
      def register(self, callback: BaseCallback) -> None: ...
      def unregister(self, callback_name: str) -> None: ...
      async def dispatch(self, event: CallbackEvent, data: Any) -> None: ...
  ```

- [ ] Callback data models:
  - `RequestStartData` — model, messages, user_id, team_id, key_id, request_id, timestamp
  - `RequestEndData` — response, usage, cost, latency_ms, provider, all of above
  - `RequestErrorData` — error, all of above
  - `StreamEventData` — chunk data, cumulative tokens

- [ ] Built-in callbacks:
  - `SpendLogCallback` — writes to SpendLog table in DB
  - `ConsoleLogCallback` — structured console logging
  - `CustomCallback` — user-defined Python callback class

- [ ] Callback configuration:
  ```yaml
  routerbot_settings:
    callbacks: ["spend_log", "prometheus", "langfuse"]
    success_callback: ["spend_log", "langfuse"]
    failure_callback: ["spend_log", "alerting"]
  ```

- [ ] Tests for callback registration, dispatch, error isolation (one callback failing doesn't break others)

**Acceptance Criteria:**
- Callbacks fire asynchronously (don't block the response)
- One callback failing doesn't affect others
- All lifecycle events dispatch correctly
- Custom callbacks work via config
- 90%+ coverage

### 5.2 — Prometheus Metrics

**Agent:** Backend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] `src/routerbot/observability/prometheus.py` — Prometheus callback
  - `routerbot_request_total` — Counter: total requests (labels: model, provider, status, user_id, team_id)
  - `routerbot_request_duration_seconds` — Histogram: request latency (labels: model, provider, endpoint)
  - `routerbot_tokens_total` — Counter: tokens used (labels: model, provider, type [prompt/completion])
  - `routerbot_cost_total` — Counter: total cost in USD (labels: model, provider, team_id)
  - `routerbot_errors_total` — Counter: errors (labels: model, provider, error_type)
  - `routerbot_active_requests` — Gauge: currently in-progress requests
  - `routerbot_cache_hits_total` — Counter: cache hits/misses
  - `routerbot_rate_limit_hits_total` — Counter: rate limit rejections
  - `routerbot_provider_health` — Gauge: provider health status (1=healthy, 0=unhealthy)
  - `routerbot_budget_remaining` — Gauge: remaining budget per key/team
  
- [ ] `GET /metrics` — Prometheus scrape endpoint
  - Protected by separate metrics auth token (optional)

- [ ] `prometheus.yml` — Example Prometheus config
- [ ] `grafana/` — Pre-built Grafana dashboards
  - Overview dashboard (requests, latency, errors, cost)
  - Provider health dashboard
  - Spend tracking dashboard
  - Per-team/per-user dashboard

- [ ] Tests

**Acceptance Criteria:**
- All metrics collected and exposed at `/metrics`
- Prometheus can scrape successfully
- Grafana dashboards render with sample data
- Labels are consistent and useful
- 85%+ coverage

### 5.3 — Langfuse Integration

**Agent:** Backend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] `src/routerbot/observability/langfuse.py` — Langfuse callback
  - Send traces to Langfuse on every request
  - Include: model, messages, response, tokens, cost, latency, metadata
  - Support for Langfuse v2 API
  - Batch sending (non-blocking)
  - Team-specific Langfuse projects (different keys per team)

- [ ] Configuration:
  ```yaml
  routerbot_settings:
    callbacks: ["langfuse"]
  
  # Global Langfuse config
  environment_variables:
    LANGFUSE_PUBLIC_KEY: "pk-..."
    LANGFUSE_SECRET_KEY: "sk-..."
    LANGFUSE_HOST: "https://cloud.langfuse.com"
  
  # Per-team override
  team_settings:
    team-frontend:
      langfuse_public_key: "pk-team-frontend-..."
      langfuse_secret_key: "sk-team-frontend-..."
  ```

- [ ] Tests with mocked Langfuse API

**Acceptance Criteria:**
- Traces appear in Langfuse after requests
- Per-team Langfuse routing works
- Batch sending doesn't block responses
- Handles Langfuse unavailability gracefully
- 85%+ coverage

### 5.4 — OpenTelemetry Integration

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] `src/routerbot/observability/opentelemetry.py` — OTEL integration
  - Tracing: span per request, child spans for provider calls
  - Attributes: model, provider, tokens, cost, user_id, team_id
  - Propagation: W3C trace-context headers
  - Export to any OTEL-compatible backend (Jaeger, Zipkin, Datadog, etc.)
  - Configurable sampling rate

- [ ] Configuration:
  ```yaml
  observability:
    opentelemetry:
      enabled: true
      endpoint: "http://localhost:4318"  # OTEL collector
      service_name: "routerbot"
      sampling_rate: 0.1  # 10% of requests
      export_format: "otlp"  # or "jaeger", "zipkin"
  ```

- [ ] Tests

**Acceptance Criteria:**
- Traces exported to OTEL collector
- Spans correctly nested (request → provider call)
- Trace context propagated to downstream services
- Sampling works correctly
- 85%+ coverage

### 5.5 — Team-Based Logging — FREE, No Enterprise Gate

**Agent:** Backend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] Per-team callback configuration
  - Each team can have its own set of callbacks
  - Team can override global logging destination (e.g., own Langfuse project)
  - Teams can disable logging entirely (GDPR compliance)
  
- [ ] Configuration:
  ```yaml
  team_settings:
    team-frontend:
      callbacks: ["langfuse"]
      langfuse_public_key: "pk-frontend-..."
      langfuse_secret_key: "sk-frontend-..."
    team-backend:
      callbacks: ["custom_webhook"]
      custom_webhook_url: "https://hooks.example.com/llm-logs"
    team-pii-sensitive:
      disable_logging: true  # GDPR — no logs stored
  ```

- [ ] API for managing team logging:
  - `POST /team/update` — include logging config
  - `GET /team/info` — show current logging config

- [ ] Tests

**Acceptance Criteria:**
- Team A's requests log to Team A's Langfuse project
- Team B's requests log to Team B's custom webhook
- Team C's requests produce no logs at all
- Global callbacks still fire unless team explicitly disables
- 90%+ coverage

### 5.6 — Log Export to Cloud Storage — FREE

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] `src/routerbot/observability/exporters/` — Log export backends
  - `gcs.py` — Export to Google Cloud Storage
  - `s3.py` — Export to AWS S3
  - `azure_blob.py` — Export to Azure Blob Storage
  - `local.py` — Export to local filesystem
  
- [ ] Export modes:
  - **Real-time**: Stream logs as they happen (via callback)
  - **Batch**: Periodic export (every N minutes or N records)
  - **On-demand**: Via API endpoint
  
- [ ] Export format:
  - JSON Lines (`.jsonl`) — one record per line
  - CSV option
  - Partitioned by date: `logs/2026/02/22/requests_001.jsonl`

- [ ] Configuration:
  ```yaml
  observability:
    log_export:
      enabled: true
      backend: "s3"
      s3_bucket: "my-llm-logs"
      s3_prefix: "routerbot/"
      export_interval_minutes: 5
      format: "jsonl"
  ```

- [ ] Tests

**Acceptance Criteria:**
- Logs export to configured cloud storage
- Batch export runs on schedule
- Files are correctly partitioned by date
- Export handles cloud API errors gracefully
- 85%+ coverage

### 5.7 — Custom Webhook Callbacks

**Agent:** Backend Engineer  
**Estimated effort:** 3-4 hours

**Deliverables:**
- [ ] `src/routerbot/observability/webhook.py` — Webhook callback
  - Send HTTP POST to configurable URL on request events
  - Configurable payload format
  - Retry on failure (with backoff)
  - Support for custom headers (auth tokens)
  - Batch mode (aggregate N events before sending)

- [ ] Configuration:
  ```yaml
  routerbot_settings:
    callbacks: ["webhook"]
    webhook_url: "https://hooks.example.com/llm-events"
    webhook_headers:
      Authorization: "Bearer webhook-secret"
    webhook_batch_size: 10
    webhook_flush_interval_seconds: 30
  ```

- [ ] Tests

**Acceptance Criteria:**
- Webhook fires on every LLM request
- Retries on failure
- Batch mode works correctly
- Custom headers sent
- 85%+ coverage

---

## Definition of Done (Stage 5)

- [ ] All 5.1–5.7 tasks completed and merged
- [ ] Callback system fires on all request lifecycle events
- [ ] Prometheus metrics exposed and scrapable
- [ ] Grafana dashboards included and functional
- [ ] Langfuse integration works (global + per-team)
- [ ] OpenTelemetry traces export correctly
- [ ] Team-based logging allows per-team callback config
- [ ] Team logging can be fully disabled (GDPR)
- [ ] Log export to S3/GCS/Azure works
- [ ] Webhook callbacks fire and retry
- [ ] All features are FREE — no license gates
- [ ] All tests pass, 85%+ coverage

---

## Notes for Agents

- All callbacks must be non-blocking (use `asyncio.create_task()` or background tasks)
- One callback failure must never affect others or the main request
- Use `try/except` around every callback dispatch
- Sensitive data (API keys) must never appear in logs/callbacks
- Test with callback that raises exceptions to verify isolation
- Prometheus metrics must not have unbounded cardinality (no user_id in high-cardinality labels)
- Use `request_id` to correlate logs across callbacks
