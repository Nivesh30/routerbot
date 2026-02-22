# Stage 6: Advanced Features (Guardrails, Caching, Rate Limiting)

**Duration:** 3-4 weeks  
**Priority:** High — differentiating features  
**Depends on:** Stage 1-4  
**Agents:** Backend Engineer

---

## Objective

Build the advanced features that make RouterBot production-ready: guardrails (content moderation, PII detection, secret detection, banned keywords), response caching, advanced rate limiting, blocked user lists, and request enforcement. All features configurable per-key and per-team — and all are FREE.

---

## Prerequisites

- Stage 1-3 complete: core, providers, proxy
- Stage 4 (at minimum): key and team models, auth middleware

---

## Tasks

### 6.1 — Guardrail Framework

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

Build the extensible guardrail system that can intercept requests and responses.

**Deliverables:**
- [ ] `src/routerbot/proxy/guardrails/base.py` — Guardrail base
  ```python
  class GuardrailAction(StrEnum):
      ALLOW = "allow"
      BLOCK = "block"
      MODIFY = "modify"  # e.g., redact PII
  
  @dataclass
  class GuardrailResult:
      action: GuardrailAction
      modified_content: str | None = None
      reason: str | None = None
      guardrail_name: str = ""
  
  class BaseGuardrail(ABC):
      name: str
      
      @abstractmethod
      async def check_request(self, messages: list[Message], context: GuardrailContext) -> GuardrailResult: ...
      
      async def check_response(self, response: str, context: GuardrailContext) -> GuardrailResult:
          return GuardrailResult(action=GuardrailAction.ALLOW)
  ```

- [ ] `src/routerbot/proxy/guardrails/manager.py` — Guardrail pipeline
  - Run guardrails in priority order
  - Short-circuit on first BLOCK
  - Apply all MODIFY actions in sequence
  - Support pre-request and post-response guardrails
  - Per-key and per-team guardrail configuration
  - Enable/disable guardrails per request via metadata

- [ ] Guardrail configuration:
  ```yaml
  guardrails:
    - name: secret_detection
      type: secret_detection
      enabled: true
      mode: "redact"  # or "block"
      priority: 1
    - name: banned_keywords
      type: banned_keywords
      enabled: true
      keywords: ["forbidden_word"]
      mode: "block"
      priority: 2
    - name: pii_detection
      type: pii_detection
      enabled: true
      mode: "redact"
      entity_types: ["email", "phone", "ssn", "credit_card"]
      priority: 3
  ```

- [ ] Tests for guardrail pipeline execution and ordering

**Acceptance Criteria:**
- Guardrails execute in priority order
- BLOCK stops request with 400 error
- MODIFY transforms content before sending to provider
- Per-key/per-team overrides work
- One guardrail failure doesn't break others
- 90%+ coverage

### 6.2 — Secret Detection & Redaction

**Agent:** Backend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] `src/routerbot/proxy/guardrails/secret_detection.py`
  - Detect common secret patterns:
    - API keys (OpenAI, Anthropic, AWS, GCP, Azure, Stripe, etc.)
    - Private keys (RSA, SSH, PGP)
    - Tokens (JWT, OAuth)
    - Connection strings (database URLs, Redis URLs)
    - Generic high-entropy strings
  - Two modes:
    - `redact` — replace with `[REDACTED]` and forward
    - `block` — reject request entirely
  - Configurable patterns (regex-based)
  - Per-key enable/disable via permissions
  
- [ ] Tests with various secret formats

**Acceptance Criteria:**
- Detects OpenAI, Anthropic, AWS keys in message content
- Redact mode replaces secrets with `[REDACTED]`
- Block mode returns 400 with descriptive error
- Custom patterns can be added via config
- Per-key toggle works
- 90%+ coverage

### 6.3 — PII Detection & Redaction

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] `src/routerbot/proxy/guardrails/pii_detection.py`
  - Detection using regex patterns (no external API dependency for basic mode)
  - Entity types:
    - Email addresses
    - Phone numbers (US, international)
    - Social Security Numbers
    - Credit card numbers (Luhn check)
    - IP addresses
    - Physical addresses (basic)
    - Names (optional, via NER — requires model)
  - Modes:
    - `redact` — replace with `[<ENTITY_TYPE>]` (e.g., `[EMAIL]`)
    - `block` — reject request
    - `hash` — replace with deterministic hash (allows correlation without exposing PII)
  - Optional: enhanced detection via external service (Presidio, Google DLP)
  
- [ ] Configuration:
  ```yaml
  guardrails:
    - name: pii_detection
      type: pii_detection
      mode: redact
      entity_types: ["email", "phone", "ssn", "credit_card"]
      # Optional: use Presidio for enhanced detection
      presidio_endpoint: "http://presidio:5002"
  ```

- [ ] Tests

**Acceptance Criteria:**
- Emails, phones, SSNs, credit cards detected and redacted
- Redaction placeholder identifies entity type
- Hash mode produces consistent hashes for same input
- No false positives on common text (e.g., "me@example.com" in code examples)
- 90%+ coverage

### 6.4 — Content Moderation

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] `src/routerbot/proxy/guardrails/content_moderation.py`
  - Support multiple moderation backends:
    - **OpenAI Moderation API** — uses `POST /v1/moderations`
    - **LLM-based** — send content to a configured LLM for moderation
    - **Google Text Moderation** — uses Google NLP API
    - **LlamaGuard** — local model-based moderation
    - **Custom** — user-defined moderation endpoint
  - Configurable categories and thresholds
  - Pre-request moderation (check user messages)
  - Post-response moderation (check model output)
  - Per-category confidence thresholds

- [ ] Configuration:
  ```yaml
  guardrails:
    - name: content_moderation
      type: content_moderation
      backend: "openai"  # or "llm", "google", "llamaguard", "custom"
      mode: "block"
      categories:
        hate: 0.8
        sexual: 0.8
        violence: 0.6
        self_harm: 0.5
      check_response: true  # also moderate model output
  ```

- [ ] Tests with sample moderation responses

**Acceptance Criteria:**
- OpenAI moderation API integration works
- LLM-based moderation works with configurable model
- Per-category thresholds respected
- Both request and response moderation
- 85%+ coverage

### 6.5 — Banned Keywords & Blocked Users

**Agent:** Backend Engineer  
**Estimated effort:** 3-4 hours

**Deliverables:**
- [ ] `src/routerbot/proxy/guardrails/banned_keywords.py`
  - Case-insensitive keyword matching
  - Configurable from config file, text file, or API
  - Block request if any banned keyword found in messages
  
- [ ] `src/routerbot/proxy/guardrails/blocked_users.py`
  - Block all requests from specified user IDs
  - Configurable from config file, text file, or API
  - API endpoints:
    - `POST /user/block` — block user(s)
    - `POST /user/unblock` — unblock user(s)
    - `GET /user/blocked` — list blocked users

- [ ] Tests

**Acceptance Criteria:**
- Banned keywords block requests with descriptive error
- Blocked users get 403 on any request
- Block/unblock via API works immediately
- 90%+ coverage

### 6.6 — Response Caching

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] `src/routerbot/cache/base.py` — Cache interface
  ```python
  class CacheBackend(Protocol):
      async def get(self, key: str) -> CacheEntry | None: ...
      async def set(self, key: str, value: CacheEntry, ttl: int | None = None) -> None: ...
      async def delete(self, key: str) -> None: ...
      async def clear(self) -> None: ...
  ```

- [ ] `src/routerbot/cache/redis.py` — Redis cache backend
  - Async Redis client
  - Configurable TTL (default: 1 hour)
  - Cache key: hash of (model, messages, temperature, other relevant params)
  - Stores full response including usage metadata
  - Namespace support for cache isolation

- [ ] `src/routerbot/cache/memory.py` — In-memory cache (LRU)
  - For development/single-instance deployments
  - Configurable max size
  - TTL support

- [ ] Cache integration in router:
  - Check cache before provider call
  - Store response in cache after successful call
  - Skip cache for streaming requests (configurable)
  - Skip cache when `cache_control: no-cache` in request

- [ ] Configuration:
  ```yaml
  routerbot_settings:
    cache: true
    cache_params:
      type: "redis"  # or "memory"
      ttl: 3600
      namespace: "routerbot"
      # Redis-specific
      redis_url: os.environ/REDIS_URL
  ```

- [ ] Cache hit/miss Prometheus metrics
- [ ] Tests

**Acceptance Criteria:**
- Identical requests return cached response
- Cache miss goes to provider and caches result
- TTL expiration works
- Cache bypass works via header
- Different temperatures produce different cache keys
- 90%+ coverage

### 6.7 — Advanced Rate Limiting

**Agent:** Backend Engineer  
**Estimated effort:** 6-8 hours

**Deliverables:**
- [ ] `src/routerbot/proxy/middleware/rate_limit.py` — Rate limiter
  - **Algorithm**: Sliding window with Redis
  - **Rate limit scopes**:
    - Per API key (RPM and TPM)
    - Per user
    - Per team
    - Per model (global)
    - Global server limit
  - **Multiple windows**: per-minute, per-hour, per-day
  - **Token-based limiting**: track tokens per minute (TPM)
  - **Configurable limits** at key, team, and global level
  - **Response headers**:
    - `X-RateLimit-Limit-Requests`: requests per period
    - `X-RateLimit-Remaining-Requests`: remaining requests
    - `X-RateLimit-Limit-Tokens`: tokens per period
    - `X-RateLimit-Remaining-Tokens`: remaining tokens
    - `X-RateLimit-Reset`: reset time
    - `Retry-After`: seconds until next allowed request (on 429)

- [ ] Fallback: in-memory rate limiting when Redis unavailable
- [ ] Tests

**Acceptance Criteria:**
- RPM and TPM limits enforced
- Rate limit headers present in all responses
- 429 responses include `Retry-After` header
- Sliding window algorithm works correctly
- Hierarchical limits (key limit overrides team limit)
- 90%+ coverage

### 6.8 — Provider Budget Routing

**Agent:** Backend Engineer  
**Estimated effort:** 4-6 hours

**Deliverables:**
- [ ] Budget-aware routing in the router
  - Set max spend per provider (e.g., max $100/day on OpenAI)
  - When provider budget exceeded, route to fallback
  - Per-tag budgets (set spend limit for a tag like "production")
  - Budget tracking in Redis (fast) with periodic sync to DB
  
- [ ] Configuration:
  ```yaml
  router_settings:
    provider_budgets:
      openai:
        max_budget: 100.0
        budget_period: "daily"
      anthropic:
        max_budget: 200.0
        budget_period: "monthly"
    tag_budgets:
      production:
        max_budget: 500.0
        budget_period: "monthly"
  ```

- [ ] Tests

**Acceptance Criteria:**
- Routes to fallback when provider budget exceeded
- Tag budgets enforced
- Budget resets correctly at period boundaries
- 85%+ coverage

---

## Definition of Done (Stage 6)

- [ ] All 6.1–6.8 tasks completed and merged
- [ ] Guardrail pipeline works with priority ordering
- [ ] Secret detection catches common API key patterns
- [ ] PII detection catches emails, phones, SSNs, credit cards
- [ ] Content moderation integrates with OpenAI moderation API
- [ ] Banned keywords and blocked users work
- [ ] Response caching works with Redis and in-memory backends
- [ ] Rate limiting works with sliding window and proper headers
- [ ] Provider budget routing works
- [ ] All features configurable per-key and per-team
- [ ] All features FREE — no enterprise gates
- [ ] All tests pass, 85%+ coverage

---

## Notes for Agents

- Guardrails must not add significant latency — use async patterns
- PII detection patterns should have low false-positive rate
- Cache keys must be deterministic — same input always produces same key
- Rate limiting must work correctly across multiple RouterBot instances (use Redis)
- Test guardrails with adversarial inputs (encoded secrets, obfuscated PII)
- Provider budget tracking in Redis must be atomic (use INCR commands)
