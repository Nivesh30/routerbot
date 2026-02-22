# RouterBot — Agent Instructions

Instructions for all AI agents (Copilot, Claude, GPT-4, etc.) working on the RouterBot codebase. **Read this before touching any code.**

---

## You Are Working On

**RouterBot** — a fully open-source LLM gateway and proxy server. Every feature is free. Every feature is open source. Apache 2.0 license, forever.

Your job is to implement features cleanly, test them thoroughly, and ship production-ready code. You are a senior engineer here — no half-measures, no TODOs left behind.

---

## First Steps (Every Session)

Before writing a single line of code:

1. **Read the stage plan** you are assigned to (`docs/stages/STAGE_N_*.md`)
2. **Read [CODING_STANDARDS.md](CODING_STANDARDS.md)** — mandatory, non-negotiable
3. **Read [ARCHITECTURE.md](ARCHITECTURE.md)** — understand module boundaries
4. **Explore the existing codebase** — never write code without reading what's already there
5. **Pick the first unchecked task** in the stage plan and mark it as in-progress

---

## Non-Negotiable Rules

These rules apply to every agent, every PR, every commit. CI will enforce them.

### 1. Module Boundaries Are Sacred

```
core/       → ZERO external deps (only stdlib + pydantic)
providers/  → depends on core/ ONLY
router/     → depends on core/ + providers/ ONLY
proxy/      → FastAPI lives HERE and ONLY here
auth/       → depends on core/ + db/ ONLY
db/         → depends on core/ ONLY
cache/      → depends on core/ ONLY
observability/ → depends on core/ ONLY
utils/      → pure utility functions, ZERO business logic
```

**Importing FastAPI into `core/` is a critical violation.** Importing `db/` models into `router/` is a critical violation. Module boundaries exist for a reason — they keep the codebase testable and maintainable.

### 2. Type Safety Is Mandatory

```python
# ❌ WRONG — never do this
def process(data):
    return data["key"]

# ✅ CORRECT
def process(data: ModelRequest) -> ModelResponse:
    return ModelResponse(content=data.messages[-1].content)
```

- All function signatures must be fully typed
- No `Any` unless absolutely unavoidable (and you must leave a comment explaining why)
- `mypy --strict` must pass without errors

### 3. Never Hardcode Secrets

```python
# ❌ WILL BE REJECTED
api_key = "sk-abc123"
db_url = "postgresql://user:password@localhost/db"

# ✅ CORRECT
api_key = settings.openai_api_key  # Loaded from env via pydantic-settings
```

### 4. Async All the Way Down

```python
# ❌ WRONG — blocks the event loop
import requests
response = requests.get("https://api.openai.com/v1/...")

# ✅ CORRECT
import httpx
async with httpx.AsyncClient() as client:
    response = await client.get("https://api.openai.com/v1/...")
```

All I/O must be async. No `requests`, no `psycopg2` (use `asyncpg`), no blocking file reads in hot paths.

### 5. Every New Feature Gets Tests

```
Unit test:       tests/unit/
Integration test: tests/integration/
```

Minimum test coverage requirements per component:
- Core utilities: 90%+
- Provider adapters: 85%+ (with real API mocks)
- Proxy endpoints: 80%+ (integration tests)
- Auth/RBAC: 90%+ (security-critical)

Tests must pass before merging. `pytest tests/ --cov=routerbot --cov-fail-under=80` must succeed.

### 6. All Features Are Free, No Paywalls

RouterBot's core commitment is that **zero features are paywalled**. Never add:
- Feature flags that require a license key
- `if settings.enterprise_tier` checks
- Comments like "TODO: move to enterprise tier"
- Any pricing tiers, plan checks, or license validation

If you are building a feature that competitors gate behind enterprise plans — build it openly. That's the whole point.

### 7. Error Handling Is Not Optional

```python
# ❌ WRONG — swallows errors silently
try:
    result = await provider.complete(request)
except Exception:
    return None

# ✅ CORRECT
try:
    result = await provider.complete(request)
except ProviderRateLimitError as exc:
    logger.warning("rate_limit", provider=provider.name, retry_after=exc.retry_after)
    raise
except ProviderAuthError as exc:
    logger.error("auth_failed", provider=provider.name, detail=str(exc))
    raise RouterBotAuthError(f"Provider {provider.name} authentication failed") from exc
except Exception as exc:
    logger.exception("unexpected_provider_error", provider=provider.name)
    raise RouterBotInternalError("Unexpected provider error") from exc
```

All exceptions must be:
- Caught at the appropriate layer
- Logged with structured context
- Re-raised as the appropriate RouterBot exception type
- Never silently swallowed

---

## Working With the Stage Plans

Each stage plan in `docs/stages/STAGE_N_*.md` contains tasks in this format:

```markdown
### N.M — Task Name

**Agent:** [Agent Type]
**Estimated effort:** X hours

**Deliverables:**
- [ ] File or feature to create

**Acceptance Criteria:**
- [ ] Verifiable check that proves it works
```

**Your workflow for each task:**

1. Read the full task including acceptance criteria
2. Explore existing code before writing anything new
3. Implement the deliverables
4. Verify all acceptance criteria are met (run the commands if provided)
5. Write/update tests
6. Mark the checkbox: change `- [ ]` to `- [x]` in the stage plan
7. Commit with the format: `feat(stage-N): implement task N.M — description`
8. Move to the next unchecked task

---

## Code Patterns to Follow

### Pydantic Models

```python
from pydantic import BaseModel, Field
from typing import Literal

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None

class ChatCompletionRequest(BaseModel):
    model: str = Field(..., description="Model identifier, e.g. 'openai/gpt-4o'")
    messages: list[ChatMessage] = Field(..., min_length=1)
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    stream: bool = False

    model_config = {"extra": "forbid"}
```

### Provider Adapter Pattern

```python
from routerbot.core.types import ModelRequest, ModelResponse
from routerbot.providers.base import BaseProvider

class OpenAIProvider(BaseProvider):
    name = "openai"
    
    async def acompletion(self, request: ModelRequest) -> ModelResponse:
        payload = self._transform_request(request)
        async with self._client() as client:
            raw = await client.post("/chat/completions", json=payload)
            raw.raise_for_status()
        return self._transform_response(raw.json())
    
    def _transform_request(self, request: ModelRequest) -> dict:
        # Map from unified format to OpenAI format
        ...
    
    def _transform_response(self, raw: dict) -> ModelResponse:
        # Map from OpenAI format to unified format
        ...
```

### FastAPI Endpoint Pattern

```python
from fastapi import APIRouter, Depends, HTTPException, status
from routerbot.proxy.deps import get_current_key, get_db
from routerbot.core.types import ChatCompletionRequest, ChatCompletionResponse

router = APIRouter(prefix="/v1", tags=["chat"])

@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    key: VirtualKey = Depends(get_current_key),
    db: AsyncSession = Depends(get_db),
) -> ChatCompletionResponse:
    """OpenAI-compatible chat completions endpoint."""
    # 1. Validate key has access to requested model
    # 2. Apply rate limiting
    # 3. Route through router
    # 4. Log request/response
    # 5. Return response
    ...
```

### Database Repository Pattern

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from routerbot.db.models import VirtualKey

class VirtualKeyRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_hash(self, key_hash: str) -> VirtualKey | None:
        stmt = select(VirtualKey).where(VirtualKey.key_hash == key_hash)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, key: VirtualKey) -> VirtualKey:
        self._db.add(key)
        await self._db.flush()
        await self._db.refresh(key)
        return key
```

### Structured Logging

```python
import structlog

logger = structlog.get_logger(__name__)

# Always log with context, never with f-strings in the message
logger.info(
    "request_completed",
    model=request.model,
    provider="openai",
    latency_ms=elapsed_ms,
    input_tokens=usage.prompt_tokens,
    output_tokens=usage.completion_tokens,
    cost_usd=cost,
    key_id=str(key.id),
)
```

---

## Testing Patterns

### Unit Test Structure

```python
import pytest
from routerbot.core.cost import calculate_cost

class TestCalculateCost:
    def test_gpt4o_cost(self) -> None:
        cost = calculate_cost("openai/gpt-4o", input_tokens=1000, output_tokens=500)
        assert cost == pytest.approx(0.005 + 0.0075, rel=1e-3)

    def test_unknown_model_returns_zero(self) -> None:
        cost = calculate_cost("unknown/model", input_tokens=100, output_tokens=50)
        assert cost == 0.0

    def test_zero_tokens_costs_nothing(self) -> None:
        cost = calculate_cost("openai/gpt-4o", input_tokens=0, output_tokens=0)
        assert cost == 0.0
```

### Integration Test Structure

```python
import pytest
from httpx import AsyncClient
from routerbot.proxy.main import app

@pytest.mark.asyncio
class TestChatCompletions:
    async def test_valid_request_returns_200(
        self, client: AsyncClient, test_api_key: str
    ) -> None:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {test_api_key}"},
            json={
                "model": "test/echo",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "choices" in data
        assert data["choices"][0]["message"]["role"] == "assistant"

    async def test_invalid_key_returns_401(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-invalid"},
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 401
```

---

## Git & Commit Standards

### Branch Naming

```
feat/stage-N-short-description      # New features
fix/describe-the-bug                # Bug fixes
refactor/what-is-changing           # Refactors
test/what-is-being-tested           # Test additions
docs/what-is-being-documented       # Documentation
chore/what-is-being-done            # Maintenance
```

### Commit Message Format

```
<type>(scope): <short summary>

[optional body explaining WHY, not WHAT]

[optional footer: Closes #123]
```

**Types:** `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `ci`

**Examples:**
```
feat(providers): implement Anthropic streaming support

fix(auth): prevent key hash timing attack using constant-time comparison

Closes #47

test(core): add edge cases for cost calculation with zero tokens

chore(ci): upgrade Python to 3.12 in CI matrix
```

### PR Checklist

Before marking a PR ready for review:

- [ ] All acceptance criteria from the stage plan are met
- [ ] All new code has tests
- [ ] `make lint` passes
- [ ] `make type-check` passes
- [ ] `make test-unit` passes
- [ ] `make test-integration` passes (if applicable)
- [ ] Stage plan checkboxes are updated (`- [ ]` → `- [x]`)
- [ ] No secrets or hardcoded values
- [ ] No enterprise feature flags or paywall checks
- [ ] PR description explains what changed and why

---

## What Each Agent Does

| Agent | Scope |
|-------|-------|
| **Backend Engineer** | APIs, database models, service layer, provider adapters |
| **Frontend Engineer** | React dashboard, TypeScript, UI components |
| **DevOps Engineer** | CI/CD, Docker, Kubernetes, Helm, GitHub Actions |
| **QA Engineer** | Test suites, test fixtures, coverage improvements |
| **Code Reviewer** | PR review, standards enforcement, security review |
| **Bug Fixer** | Diagnose and fix reported bugs with regression tests |
| **Orchestrator** | Coordinate multi-agent work across a stage |

---

## Running the Project Locally

```bash
# Install dependencies
make install-dev

# Start infrastructure
docker compose up postgres redis -d

# Run migrations
make db-migrate

# Start the server
make run

# Run tests
make test-unit
make test-integration

# Full check (lint + types + tests)
make check
```

---

## Where Things Live

| What | Where |
|------|-------|
| Core types and interfaces | `src/routerbot/core/types.py` |
| Configuration loading | `src/routerbot/core/config.py` |
| Exception hierarchy | `src/routerbot/core/exceptions.py` |
| Cost/token utilities | `src/routerbot/core/cost.py` |
| Provider base class | `src/routerbot/providers/base.py` |
| Each provider | `src/routerbot/providers/<name>/` |
| Router logic | `src/routerbot/router/` |
| FastAPI app | `src/routerbot/proxy/main.py` |
| FastAPI routes | `src/routerbot/proxy/routes/` |
| Middleware | `src/routerbot/proxy/middleware/` |
| Auth logic | `src/routerbot/auth/` |
| Database models | `src/routerbot/db/models/` |
| Migrations | `alembic/versions/` |
| Cache backends | `src/routerbot/cache/` |
| Observability | `src/routerbot/observability/` |
| Unit tests | `tests/unit/` |
| Integration tests | `tests/integration/` |
| Stage plans | `docs/stages/` |
| Container config | `docs/CONTAINER.md` |
| Architecture | `docs/ARCHITECTURE.md` |
| Coding standards | `docs/CODING_STANDARDS.md` |

---

## Questions to Ask Before Implementing

1. **Which module does this belong in?** (Check module boundaries)
2. **Does something similar already exist?** (Search the codebase first)
3. **Is this a provider-specific thing or a universal thing?** (Put it in the right layer)
4. **Could this introduce a paywall or enterprise restriction?** (If yes: don't)
5. **What breaks if this fails?** (Add the right error handling)
6. **How will I test this?** (Plan tests before writing code)
7. **Does this need a database migration?** (Don't forget Alembic)
8. **Does this need a config setting?** (Add it to `Config` with a sensible default)
