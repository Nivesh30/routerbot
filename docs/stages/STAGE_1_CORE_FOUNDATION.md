# Stage 1: Core Foundation

**Duration:** 2-3 weeks  
**Priority:** Critical — everything depends on this  
**Agents:** Backend Engineer, DevOps Engineer

---

## Objective

Establish the project skeleton, build system, CI pipeline, configuration system, core type definitions, and exception hierarchy. After this stage, any agent can clone the repo, run `make install-dev`, and start building features on a solid foundation.

---

## Prerequisites

- None (this is the starting point)

---

## Tasks

### 1.1 — Project Scaffolding

**Agent:** DevOps Engineer  
**Estimated effort:** 4-6 hours

Create the full directory structure and build system.

**Deliverables:**
- [ ] `pyproject.toml` with all metadata, dependencies, and tool configs (Ruff, MyPy, pytest)
- [ ] `Makefile` with targets: `install-dev`, `format`, `lint`, `type-check`, `test-unit`, `test-integration`, `test-all`, `run`, `build`, `clean`
- [ ] `src/routerbot/__init__.py` — package root with version
- [ ] `src/routerbot/py.typed` — PEP 561 marker
- [ ] Empty module directories with `__init__.py` for: `core/`, `providers/`, `router/`, `proxy/`, `auth/`, `db/`, `cache/`, `observability/`, `utils/`
- [ ] `.gitignore` (Python, Node, Docker, IDE files)
- [ ] `.editorconfig`
- [ ] `LICENSE` (Apache 2.0)
- [ ] `CONTRIBUTING.md` — basic contributing guide

**Acceptance Criteria:**
```bash
git clone <repo>
cd routerbot
make install-dev   # Installs all deps in virtual env
make lint          # Passes (empty project, no errors)
make type-check    # Passes
make test-unit     # Passes (0 tests collected is OK)
```

### 1.2 — CI/CD Pipeline

**Agent:** DevOps Engineer  
**Estimated effort:** 3-4 hours

Set up GitHub Actions for continuous integration.

**Deliverables:**
- [ ] `.github/workflows/ci.yml` — runs on every PR and push to `main`
  - Lint (Ruff)
  - Format check (Ruff)
  - Type check (MyPy)
  - Unit tests (pytest)
  - Integration tests (pytest with Docker services)
  - Dependency audit (pip-audit)
  - Circular import detection
- [ ] `.github/workflows/release.yml` — triggered on tag push
  - Build Python package
  - Build Docker image
  - Push to PyPI + GHCR
- [ ] `.github/dependabot.yml` — automated dependency updates
- [ ] `.github/PULL_REQUEST_TEMPLATE.md`
- [ ] `.github/ISSUE_TEMPLATE/` — bug report, feature request, stage task

**Acceptance Criteria:**
- Push a commit → CI runs and passes
- All checks listed in `CODING_STANDARDS.md` are automated

### 1.3 — Configuration System

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

Build the layered configuration system that supports YAML files, environment variables, and runtime overrides.

**Deliverables:**
- [ ] `src/routerbot/core/config.py` — Configuration loading and validation
  - Load from YAML file (default: `routerbot_config.yaml`)
  - Environment variable overrides with `ROUTERBOT_` prefix
  - Secret references: `os.environ/VAR_NAME` syntax
  - Deep merge of config layers
  - Pydantic models for all config sections
- [ ] `src/routerbot/core/config_models.py` — Pydantic config models
  - `RouterBotConfig` (top-level)
  - `GeneralSettings` (master_key, database_url, redis_url, etc.)
  - `RouterSettings` (routing_strategy, retries, fallbacks)
  - `ModelConfig` (model_name, provider, api_base, api_key, etc.)
  - `RouterBotSettings` (callbacks, cache, etc.)
- [ ] `routerbot_config.example.yaml` — documented example config
- [ ] Tests for config loading, env overrides, secret resolution, validation errors

**Config Model Example:**
```python
class GeneralSettings(BaseModel):
    master_key: str | None = None
    database_url: str = "sqlite+aiosqlite:///routerbot.db"
    redis_url: str | None = None
    port: int = 4000
    host: str = "0.0.0.0"
    num_workers: int = 1
    request_timeout: int = 600
    max_request_size_mb: float = 100.0
    max_response_size_mb: float = 100.0
    block_robots: bool = False

class ModelEntry(BaseModel):
    model_name: str
    provider_params: ModelParams
    model_info: ModelInfo | None = None

class ModelParams(BaseModel):
    model: str              # provider/model format
    api_key: str | None = None
    api_base: str | None = None
    max_tokens: int | None = None
    rpm: int | None = None  # requests per minute
    tpm: int | None = None  # tokens per minute
```

**Acceptance Criteria:**
- Load config from YAML → all fields parsed correctly
- Env var `ROUTERBOT_GENERAL_SETTINGS__PORT=8080` overrides `general_settings.port`
- `os.environ/OPENAI_API_KEY` is resolved from environment
- Invalid config raises clear validation error with field path
- 95%+ test coverage on config module

### 1.4 — Core Type Definitions

**Agent:** Backend Engineer  
**Estimated effort:** 4-6 hours

Define the Pydantic models for all request/response types, matching the OpenAI API format exactly.

**Deliverables:**
- [ ] `src/routerbot/core/types.py` — Core data types
  - `Message` (role, content, name, tool_calls, etc.)
  - `CompletionRequest` — matches OpenAI `/chat/completions` input
  - `CompletionResponse` — matches OpenAI `/chat/completions` output
  - `CompletionResponseChunk` — streaming chunk format
  - `EmbeddingRequest` / `EmbeddingResponse`
  - `ImageRequest` / `ImageResponse`
  - `AudioRequest` / `AudioResponse`
  - `RerankRequest` / `RerankResponse`
  - `Usage` (prompt_tokens, completion_tokens, total_tokens)
  - `Choice`, `Delta`, `ToolCall`, `FunctionCall`
  - `ModelInfo` — model metadata (pricing, context window, capabilities)
- [ ] `src/routerbot/core/enums.py` — Enumerations
  - `Provider` (openai, anthropic, azure, bedrock, vertex_ai, etc.)
  - `FinishReason` (stop, length, tool_calls, content_filter)
  - `Role` (system, user, assistant, tool)
  - `RoutingStrategy` (round_robin, least_connections, latency_based, cost_based)
- [ ] Tests validating serialization/deserialization roundtrip with real OpenAI responses

**Acceptance Criteria:**
- A real OpenAI response JSON can be parsed into `CompletionResponse` and serialized back to matching JSON
- All fields from the OpenAI spec are represented
- `extra="allow"` on request models for provider-specific passthrough
- 90%+ test coverage

### 1.5 — Exception Hierarchy

**Agent:** Backend Engineer  
**Estimated effort:** 2-3 hours

Build the exception system that maps to OpenAI error format.

**Deliverables:**
- [ ] `src/routerbot/core/exceptions.py`
  - `RouterBotError` (base)
  - `AuthenticationError` (401)
  - `PermissionDeniedError` (403)
  - `NotFoundError` (404)
  - `BadRequestError` (400)
  - `RateLimitError` (429)
  - `ProviderError` (500, wraps upstream errors)
  - `ModelNotFoundError` (404)
  - `BudgetExceededError` (429)
  - `ContentPolicyError` (400)
  - `ConfigurationError` (500)
  - `TimeoutError` (408)
  - `ServiceUnavailableError` (503)
- [ ] Each exception has `status_code`, `message`, `type`, `param`, `code` matching OpenAI error format
- [ ] `to_openai_error()` method that serializes to `{"error": {"message": ..., "type": ..., "param": ..., "code": ...}}`
- [ ] Tests for all exception types and serialization

**Acceptance Criteria:**
- Every exception serializes to valid OpenAI error format
- `ProviderError` correctly wraps upstream exceptions
- 95%+ coverage

### 1.6 — Token Counting & Cost Calculation

**Agent:** Backend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] `src/routerbot/core/tokens.py` — Token counting
  - Count tokens for any message list using `tiktoken` (for OpenAI models) or provider-specific counting
  - Fallback estimation for unknown models
- [ ] `src/routerbot/core/cost.py` — Cost calculation
  - `model_prices.json` — pricing database (input/output per 1K tokens)
  - `calculate_cost(model, usage)` → `float` (USD)
  - Support for image, audio, embedding pricing
- [ ] `src/routerbot/core/model_registry.py` — Model metadata
  - Load from `model_prices.json`
  - Lookup context window, pricing, capabilities per model
  - Support custom model additions via config
- [ ] `model_prices.json` — initial pricing data for top 50 models
- [ ] Tests for token counting accuracy and cost calculation

**Acceptance Criteria:**
- Token count for GPT-4o matches OpenAI's `tiktoken` exactly
- Cost calculation for a 1000-token request/500-token response is correct for GPT-4o, Claude, Gemini
- Unknown models use reasonable token estimation
- 90%+ coverage

### 1.7 — Structured Logging

**Agent:** Backend Engineer  
**Estimated effort:** 2-3 hours

**Deliverables:**
- [ ] `src/routerbot/core/logging.py` — Logging setup
  - `structlog` configuration with JSON output
  - Request-scoped context (request_id, user_id, team_id, model)
  - Log levels configurable via env/config
  - Sensitive data redaction in logs (API keys, tokens)
  - Console format for development, JSON for production
- [ ] `src/routerbot/utils/hashing.py` — Key hashing utilities
  - `hash_key(key: str) -> str` — SHA-256 hash for storage
  - `generate_key(prefix: str = "rb") -> str` — generate virtual API key
  - `mask_key(key: str) -> str` — show first 8 / last 4 chars
- [ ] Tests

**Acceptance Criteria:**
- All logs are structured JSON in production mode
- API keys never appear in logs (verified by test)
- Request ID flows through all log entries for a given request
- 90%+ coverage

---

## Definition of Done (Stage 1)

- [ ] All 1.1–1.7 tasks completed and merged
- [ ] `make install-dev && make lint && make type-check && make test-unit` all pass
- [ ] CI pipeline is green
- [ ] Config can be loaded from YAML + env vars
- [ ] All core types serialize to/from OpenAI format
- [ ] Exception hierarchy complete with OpenAI error format
- [ ] Token counting works for OpenAI models
- [ ] Cost calculation works with model_prices.json
- [ ] Structured logging with request context
- [ ] No circular imports
- [ ] All code meets CODING_STANDARDS.md

---

## Notes for Agents

- Read `docs/CODING_STANDARDS.md` before writing any code
- Read `docs/ARCHITECTURE.md` for module boundary rules
- The `core/` module must have ZERO dependencies on FastAPI, SQLAlchemy, or Redis
- Use `|` union syntax (Python 3.11+), not `Optional[]`
- All new files must have module-level docstrings
- Run `make lint && make type-check` before every commit
