# Stage 3: Proxy Server (API Gateway)

**Duration:** 3-4 weeks  
**Priority:** Critical — the central deployment mode  
**Depends on:** Stage 1 (Core Foundation), Stage 2 (Provider Integration)  
**Agents:** Backend Engineer

---

## Objective

Build the FastAPI-based proxy server that acts as an AI gateway. It receives OpenAI-compatible HTTP requests, authenticates them, routes them through the provider system, and returns normalized responses. This stage covers the server skeleton, routing, middleware pipeline, and CLI — but NOT authentication (Stage 4) or guardrails (Stage 6).

---

## Prerequisites

- Stage 1 complete: config, types, exceptions
- Stage 2 complete (at minimum: OpenAI + Anthropic providers)

---

## Tasks

### 3.1 — FastAPI Application Factory

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] `src/routerbot/proxy/app.py` — Application factory
  ```python
  def create_app(config: RouterBotConfig | None = None) -> FastAPI:
      """Create and configure the FastAPI application."""
  ```
  - Lifecycle management (startup/shutdown events)
  - Provider initialization on startup
  - Database connection pool on startup
  - Redis connection on startup
  - Graceful shutdown with connection draining
  - CORS middleware (configurable origins)
  - Request ID middleware (generates UUID per request)
  - Exception handlers mapping RouterBot exceptions to OpenAI error format
  - OpenAPI customization (title, description, version)
  
- [ ] `src/routerbot/proxy/cli.py` — CLI entry point
  - `routerbot --config config.yaml --port 4000 --host 0.0.0.0`
  - `routerbot --model openai/gpt-4o` (quick start, single model)
  - `--workers` flag for multi-process
  - `--detailed-debug` for verbose logging
  - Uses `click` for CLI argument parsing
  - Calls `uvicorn.run()` with the app factory

- [ ] `src/routerbot/proxy/state.py` — Application state management
  - Singleton holding the router, config, DB engine, Redis
  - Dependency injection via FastAPI `Depends()`
  
- [ ] Tests for app creation, lifecycle, error handling

**Acceptance Criteria:**
- `routerbot --config routerbot_config.yaml` starts the server
- Server responds to `GET /health` with `{"status": "healthy"}`
- Invalid requests return OpenAI-format errors
- Server gracefully shuts down when sent SIGTERM
- 85%+ coverage

### 3.2 — LLM API Routes

**Agent:** Backend Engineer  
**Estimated effort:** 10-12 hours

Implement all OpenAI-compatible LLM endpoints.

**Deliverables:**
- [ ] `src/routerbot/proxy/routes/completions.py`
  - `POST /v1/chat/completions` — chat completions (sync + streaming)
  - `POST /v1/completions` — legacy text completions
  - Streaming via `StreamingResponse` with SSE format
  - `X-Request-ID` response header
  - Spend tracking after response (async background task)
  
- [ ] `src/routerbot/proxy/routes/responses.py`
  - `POST /v1/responses` — OpenAI Responses API format
  
- [ ] `src/routerbot/proxy/routes/embeddings.py`
  - `POST /v1/embeddings` — embedding generation
  
- [ ] `src/routerbot/proxy/routes/images.py`
  - `POST /v1/images/generations` — image generation
  - `POST /v1/images/edits` — image editing
  
- [ ] `src/routerbot/proxy/routes/audio.py`
  - `POST /v1/audio/transcriptions` — speech-to-text
  - `POST /v1/audio/speech` — text-to-speech
  
- [ ] `src/routerbot/proxy/routes/models.py`
  - `GET /v1/models` — list available models
  - `GET /v1/models/{model}` — get model details
  
- [ ] `src/routerbot/proxy/routes/batches.py`
  - `POST /v1/batches` — create batch
  - `GET /v1/batches/{batch_id}` — get batch status
  - `GET /v1/batches` — list batches
  
- [ ] `src/routerbot/proxy/routes/rerank.py`
  - `POST /v1/rerank` — reranking
  
- [ ] `src/routerbot/proxy/routes/health.py`
  - `GET /health` — basic health
  - `GET /health/liveliness` — liveness probe (Kubernetes)
  - `GET /health/readiness` — readiness probe (all providers reachable)
  
- [ ] Tests for each route (request validation, response format, error cases)

**Streaming Implementation:**
```python
@router.post("/v1/chat/completions")
async def chat_completions(request: CompletionRequest, ...):
    if request.stream:
        return StreamingResponse(
            stream_completion(request),
            media_type="text/event-stream",
            headers={"X-Request-ID": request_id},
        )
    response = await router.complete(request)
    return JSONResponse(content=response.model_dump(), headers={"X-Request-ID": request_id})

async def stream_completion(request: CompletionRequest):
    async for chunk in router.complete_stream(request):
        yield f"data: {chunk.model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"
```

**Acceptance Criteria:**
- All endpoints match OpenAI API spec
- Streaming works with SSE format (`data: {...}\n\n`)
- `GET /v1/models` returns all configured models
- Health endpoints return correct status
- OpenAPI docs at `/docs` show all endpoints
- 85%+ coverage

### 3.3 — Router Integration

**Agent:** Backend Engineer  
**Estimated effort:** 10-12 hours

Build the intelligent routing layer that sits between the proxy routes and providers.

**Deliverables:**
- [ ] `src/routerbot/router/router.py` — Main router
  - Model name → provider resolution
  - Multiple deployments per model name (e.g., GPT-4o on OpenAI + Azure)
  - Retry logic with configurable policy
  - Fallback chain execution
  - Request timeout management
  - Context propagation (request_id, user_id, team_id)
  
- [ ] `src/routerbot/router/strategies.py` — Load balancing strategies
  - `RoundRobinStrategy` — simple rotation
  - `LeastConnectionsStrategy` — route to least-busy deployment
  - `LatencyBasedStrategy` — route to fastest deployment (rolling average)
  - `CostBasedStrategy` — route to cheapest deployment
  - `WeightedStrategy` — weighted random selection
  - All strategies implement `Strategy` protocol
  
- [ ] `src/routerbot/router/retry.py` — Retry logic
  - Exponential backoff with jitter
  - Configurable retry conditions (timeout, rate_limit, 5xx)
  - Max retries per request
  - Different retry behavior for streaming vs non-streaming
  
- [ ] `src/routerbot/router/fallback.py` — Fallback chains
  - `model_a → model_b → model_c` fallback sequence
  - Fallback triggered on: timeout, provider error, rate limit
  - Configurable per model via config file
  
- [ ] `src/routerbot/router/health.py` — Health checking
  - Periodic health checks (configurable interval)
  - Mark unhealthy deployments as unavailable
  - Automatic recovery when deployment comes back
  - Health status exposed via API
  
- [ ] `src/routerbot/router/cooldown.py` — Cooldown management
  - Track failure count per deployment
  - After N failures, put deployment in cooldown for configurable duration
  - Cooldown state in Redis (shared across instances) or in-memory
  
- [ ] Tests for all strategies, retry logic, fallback chains, health checking

**Router Configuration:**
```yaml
router_settings:
  routing_strategy: "latency-based"
  num_retries: 3
  timeout: 600
  retry_after: 0.5  # seconds before first retry
  allowed_fails: 3  # failures before cooldown
  cooldown_time: 60  # seconds
  
  fallbacks:
    - gpt-4o: ["claude-sonnet", "gemini-pro"]
    - claude-sonnet: ["gpt-4o"]
```

**Acceptance Criteria:**
- Requests correctly routed to configured providers
- Round-robin distributes evenly across deployments
- Latency-based routes to fastest deployment
- Retry on transient errors with exponential backoff
- Fallback chain executes on provider failure
- Health checks mark/unmark deployments correctly
- Cooldown prevents repeated calls to failing deployment
- 90%+ coverage

### 3.4 — Request/Response Middleware Pipeline

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

Build the middleware system for cross-cutting concerns.

**Deliverables:**
- [ ] `src/routerbot/proxy/middleware/base.py` — Middleware base class
  ```python
  class Middleware(ABC):
      @abstractmethod
      async def process_request(self, request: Request, call_next: Callable) -> Response: ...
  ```
  
- [ ] `src/routerbot/proxy/middleware/request_id.py` — Request ID
  - Generate UUID for every request
  - Add to request state and response headers
  - Thread through logging context
  
- [ ] `src/routerbot/proxy/middleware/size_limit.py` — Request/response size limits
  - Configurable max request body size
  - Configurable max response body size
  - Return 400 with clear error message when exceeded
  
- [ ] `src/routerbot/proxy/middleware/logging_mw.py` — Request logging
  - Log request start (method, path, model, user_id)
  - Log request end (status_code, latency_ms, tokens, cost)
  - Structured JSON logging
  
- [ ] `src/routerbot/proxy/middleware/cors.py` — CORS wrapper
  - Configurable allowed origins, methods, headers
  - Default: restrictive (no wildcard)
  
- [ ] `src/routerbot/proxy/middleware/robots.py` — Block web crawlers
  - `GET /robots.txt` returns `Disallow: /` when enabled
  
- [ ] Tests for each middleware

**Acceptance Criteria:**
- Every response has `X-Request-ID` header
- Oversized requests are rejected with clear error
- Request log includes latency, model, tokens, cost
- CORS headers correct
- 85%+ coverage

### 3.5 — Configuration Hot-Reload

**Agent:** Backend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] File watcher on `routerbot_config.yaml`
  - Detect changes and reload config without restart
  - Validate new config before applying
  - Rollback to previous config on validation failure
  - Log config changes
  
- [ ] `POST /config/reload` — API endpoint for manual reload
  - Admin-only (requires master key)
  - Returns new config hash + diff summary
  
- [ ] Model list hot-reload
  - Add/remove models without restart
  - New provider connections initialized
  - Old provider connections cleaned up
  
- [ ] Tests

**Acceptance Criteria:**
- Edit config file → models list updates within 5 seconds
- Invalid config change is rejected (old config preserved)
- `POST /config/reload` triggers immediate reload
- 85%+ coverage

### 3.6 — OpenAPI Documentation & Swagger

**Agent:** Backend Engineer  
**Estimated effort:** 3-4 hours

**Deliverables:**
- [ ] Custom Swagger UI at `/docs`
  - Configurable title and description (via config/env)
  - Filtered routes option (hide admin routes from end users)
  - Custom branding support (logo, colors — via config)
  
- [ ] OpenAPI spec at `/openapi.json`
  - Accurate request/response schemas
  - Authentication documentation
  - Example requests for each endpoint
  
- [ ] ReDoc at `/redoc` as alternative
- [ ] Tests for schema generation

**Acceptance Criteria:**
- Swagger UI loads at `/docs`
- All endpoints documented with examples
- Configurable title/description via env vars
- Route filtering works when `DOCS_FILTERED=true`

---

## Definition of Done (Stage 3)

- [ ] All 3.1–3.6 tasks completed and merged
- [ ] `routerbot --config routerbot_config.yaml` starts and serves requests
- [ ] `POST /v1/chat/completions` works for all Stage 2 providers
- [ ] Streaming works via SSE
- [ ] Router correctly performs retry, fallback, load balancing
- [ ] Health endpoints work for Kubernetes
- [ ] Config hot-reload works
- [ ] Swagger docs accessible and accurate
- [ ] All middleware functional (request ID, size limit, logging, CORS)
- [ ] All tests pass, 85%+ coverage
- [ ] No memory leaks on sustained load (basic load test)

---

## Notes for Agents

- FastAPI is only used in `proxy/` — the router and providers must remain framework-agnostic
- Always use `async def` for route handlers
- Use `Depends()` for dependency injection (auth context, rate limiter, etc.)
- Streaming must use `StreamingResponse` with `text/event-stream` content type
- Every route must accept `Authorization: Bearer <key>` header
- Background tasks (spend logging) should use FastAPI `BackgroundTasks`
- Test the proxy using `httpx.AsyncClient` with the app (no real server needed)
