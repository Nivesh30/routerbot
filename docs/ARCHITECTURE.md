# RouterBot — System Architecture

## Overview

RouterBot is a multi-layered LLM gateway built on a clean separation of concerns: SDK → Router → Proxy → Dashboard. Each layer can be used independently or composed together.

```
┌─────────────────────────────────────────────────────────────┐
│                     Admin Dashboard (React)                  │
│              Team Mgmt · Key Mgmt · Spend · Config           │
├─────────────────────────────────────────────────────────────┤
│                    Proxy Server (FastAPI)                     │
│         Auth · Rate Limit · Load Balance · Middleware         │
├─────────────────────────────────────────────────────────────┤
│                    Router Layer (Python)                      │
│          Retry · Fallback · Health Check · Routing            │
├─────────────────────────────────────────────────────────────┤
│                    Provider Adapters                          │
│    OpenAI · Anthropic · Azure · Bedrock · Vertex · ...       │
├─────────────────────────────────────────────────────────────┤
│                    Core SDK (Python)                          │
│   Unified I/O · Streaming · Exceptions · Cost Tracking       │
├─────────────────────────────────────────────────────────────┤
│                    Infrastructure                             │
│        PostgreSQL · Redis · Prometheus · Docker               │
└─────────────────────────────────────────────────────────────┘
```

---

## Layer Details

### 1. Core SDK (`routerbot/core/`)

The foundation layer that translates between the unified OpenAI-compatible format and provider-specific formats.

**Responsibilities:**
- Message format translation (OpenAI ↔ Provider)
- Streaming response normalization
- Exception mapping to OpenAI error types
- Token counting and cost calculation
- Model metadata and pricing registry

**Key Interfaces:**
```python
# Core completion interface
async def acompletion(model: str, messages: list, **kwargs) -> ModelResponse
def completion(model: str, messages: list, **kwargs) -> ModelResponse

# Streaming
async def acompletion(model: str, messages: list, stream=True, **kwargs) -> AsyncIterator[ModelResponseChunk]
```

### 2. Provider Adapters (`routerbot/providers/`)

Each provider has a self-contained adapter implementing the `BaseProvider` interface.

**Structure per provider:**
```
providers/
├── base.py              # Abstract base class
├── openai/
│   ├── __init__.py
│   ├── chat.py          # Chat completions
│   ├── embeddings.py    # Embeddings
│   ├── images.py        # Image generation
│   ├── audio.py         # Audio/TTS/STT
│   ├── transform.py     # Request/response transformation
│   └── config.py        # Provider-specific config
├── anthropic/
├── azure/
├── bedrock/
├── vertex_ai/
├── gemini/
├── groq/
├── ollama/
└── ...
```

**Provider Registration:**
Providers are registered via a plugin-like system. New providers can be added by:
1. Implementing `BaseProvider`
2. Adding a JSON config for OpenAI-compatible providers (zero-code path)
3. Registering via entry points for third-party extensions

### 3. Router Layer (`routerbot/router/`)

Intelligent request routing across multiple model deployments.

**Capabilities:**
- **Retry Logic**: Configurable retry with exponential backoff
- **Fallback Chains**: Automatic failover to backup models/providers
- **Load Balancing**: Round-robin, least-connections, weighted, latency-based
- **Health Checks**: Periodic provider health monitoring
- **Cooldown**: Automatic cooldown for failing deployments
- **Cost-Based Routing**: Route to cheapest available option

**Configuration:**
```yaml
router_settings:
  routing_strategy: "latency-based"  # or round-robin, least-connections, cost-based
  retry_policy:
    max_retries: 3
    retry_on: ["timeout", "rate_limit", "server_error"]
  fallback_models:
    gpt-4o: ["claude-sonnet-4-20250514", "gemini-pro"]
  cooldown_time: 60  # seconds
  health_check_interval: 30  # seconds
```

### 4. Proxy Server (`routerbot/proxy/`)

FastAPI-based API gateway providing the public-facing HTTP interface.

**Request Flow:**
```
Client Request
    → Authentication Middleware (API Key / JWT / SSO Token)
    → Rate Limiting Middleware
    → Request Validation & Size Check
    → Guardrails (Pre-request: PII detection, banned keywords, content moderation)
    → Request Transformation
    → Router (retry/fallback/load-balance)
    → Provider Adapter
    → Response Transformation
    → Guardrails (Post-response: content filtering)
    → Cost Tracking & Logging
    → Response to Client
```

**Endpoints:**
```
POST   /v1/chat/completions      # Chat completions (OpenAI format)
POST   /v1/responses              # Responses API
POST   /v1/embeddings             # Embeddings
POST   /v1/images/generations     # Image generation
POST   /v1/audio/transcriptions   # Audio transcription
POST   /v1/audio/speech           # Text-to-speech
POST   /v1/batches                # Batch API
POST   /v1/rerank                 # Reranking
GET    /v1/models                 # List available models

POST   /key/generate              # Generate virtual API key
POST   /key/update                # Update key settings
POST   /key/delete                # Delete key
GET    /key/info                  # Get key info

POST   /team/new                  # Create team
POST   /team/update               # Update team
GET    /team/list                 # List teams

POST   /user/new                  # Create user
POST   /user/update               # Update user
GET    /user/info                 # User info

GET    /spend/logs                # Spend logs
GET    /spend/tags                # Spend by tag
GET    /spend/report              # Spend report

GET    /model/info                # Model information
POST   /model/new                 # Add model
POST   /model/update              # Update model

GET    /health                    # Health check
GET    /health/liveliness         # Liveness probe
GET    /health/readiness          # Readiness probe
```

### 5. Admin Dashboard (`ui/dashboard/`)

React + TypeScript SPA for managing the proxy.

**Pages:**
- **Dashboard**: Overview of requests, spend, latency, errors
- **Models**: Add/edit/remove model configurations
- **Virtual Keys**: Generate and manage API keys with budgets
- **Teams**: Team management with per-team settings
- **Users**: User management with roles (Admin, Editor, Viewer)
- **Spend**: Detailed spend analytics with exports
- **Guardrails**: Configure content moderation, PII detection
- **Settings**: SSO, general config, branding
- **Logs**: Request/response audit logs
- **Router**: Fallback/retry configuration

### 6. Infrastructure Layer

**PostgreSQL** — Primary data store for:
- Virtual keys, teams, users
- Spend logs and analytics
- Audit logs
- Model configurations
- Guardrail policies

**Redis** — Used for:
- Rate limiting (sliding window)
- Response caching
- Session storage
- Health check state
- Distributed locking

**Prometheus + Grafana** — Metrics:
- Request count, latency histograms
- Token usage per model/provider
- Error rates by provider
- Spend tracking
- Cache hit rates

---

## Data Model (PostgreSQL)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    Users     │────<│  UserTeams  │>────│    Teams     │
├─────────────┤     ├─────────────┤     ├─────────────┤
│ id           │     │ user_id      │     │ id           │
│ email        │     │ team_id      │     │ name         │
│ role         │     │ role         │     │ budget_limit │
│ max_budget   │     └─────────────┘     │ spend        │
│ spend        │                         │ settings     │
│ sso_id       │                         └──────┬───────┘
└──────┬───────┘                                │
       │                                        │
       │         ┌─────────────┐               │
       └────────<│ VirtualKeys │>──────────────┘
                 ├─────────────┤
                 │ id           │
                 │ key_hash     │
                 │ user_id      │
                 │ team_id      │
                 │ models[]     │
                 │ max_budget   │
                 │ spend        │
                 │ rate_limit   │
                 │ expires_at   │
                 │ permissions  │
                 │ metadata     │
                 └──────┬───────┘
                        │
              ┌─────────┴──────────┐
              │                    │
     ┌────────┴────┐    ┌─────────┴─────┐
     │  SpendLogs  │    │  AuditLogs    │
     ├─────────────┤    ├───────────────┤
     │ id           │    │ id             │
     │ key_id       │    │ action         │
     │ model        │    │ actor_id       │
     │ provider     │    │ target_type    │
     │ tokens_used  │    │ target_id      │
     │ cost         │    │ old_value      │
     │ request_id   │    │ new_value      │
     │ tags[]       │    │ ip_address     │
     │ created_at   │    │ created_at     │
     └──────────────┘    └───────────────┘

     ┌──────────────┐    ┌───────────────┐
     │ ModelConfig  │    │ GuardrailRule │
     ├──────────────┤    ├───────────────┤
     │ id            │    │ id             │
     │ model_name    │    │ name           │
     │ provider      │    │ type           │
     │ api_base      │    │ config         │
     │ api_key_ref   │    │ team_id        │
     │ max_tokens    │    │ key_id         │
     │ rpm_limit     │    │ enabled        │
     │ tpm_limit     │    │ priority       │
     └──────────────┘    └───────────────┘
```

---

## Configuration System

RouterBot uses a layered configuration approach:

1. **Default Config** — Built-in sensible defaults
2. **Config File** (`routerbot_config.yaml`) — Primary configuration
3. **Environment Variables** — Override any config value (`ROUTERBOT_*` prefix)
4. **Database** — Runtime-mutable settings (models, keys, teams)
5. **API** — Dynamic configuration via management endpoints

```yaml
# routerbot_config.yaml
model_list:
  - model_name: gpt-4o
    provider_params:
      model: openai/gpt-4o
      api_key: os.environ/OPENAI_API_KEY
  - model_name: claude-sonnet
    provider_params:
      model: anthropic/claude-sonnet-4-20250514
      api_key: os.environ/ANTHROPIC_API_KEY

general_settings:
  master_key: os.environ/ROUTERBOT_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  redis_url: os.environ/REDIS_URL

router_settings:
  routing_strategy: latency-based
  num_retries: 3
  fallbacks:
    - gpt-4o: [claude-sonnet]

routerbot_settings:
  callbacks: [langfuse, prometheus]
  cache: true
  cache_params:
    type: redis
```

---

## Security Architecture

### Authentication Chain
```
Request → Header Extraction
       → API Key Auth (Bearer token → hash → DB lookup)
       → JWT Auth (verify signature → extract claims)
       → SSO Token Auth (OIDC/SAML → session validation)
       → Permission Check (RBAC: admin, editor, viewer)
       → Rate Limit Check (per-key, per-user, per-team)
       → IP Allowlist Check
       → Request Processing
```

### Key Storage
- API keys are stored as SHA-256 hashes (never plaintext)
- Master key is read from env/secret manager
- Provider API keys support secret manager references (`os.environ/`, `aws_secret/`, `gcp_secret/`, `azure_vault/`)

### RBAC Roles
| Role | Capabilities |
|---|---|
| `admin` | Full access: manage users, teams, keys, models, settings |
| `editor` | Manage own team's keys, view spend, configure models |
| `viewer` | Read-only access to dashboard, own spend |
| `api_user` | API access only (no dashboard) |

---

## Deployment Topologies

### Single Container (Development / Small Scale)
```
┌────────────────────────┐
│     RouterBot          │
│  (API + Dashboard)     │
│         +              │
│      SQLite            │
└────────────────────────┘
```

### Standard (Production)
```
┌──────────┐  ┌──────────┐  ┌──────────┐
│RouterBot │  │RouterBot │  │RouterBot │
│ Instance │  │ Instance │  │ Instance │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │             │             │
     └──────┬──────┘─────────────┘
            │
     ┌──────┴──────┐  ┌──────────┐
     │  PostgreSQL  │  │  Redis   │
     └─────────────┘  └──────────┘
```

### Enterprise Scale (Kubernetes)
```
┌─────────────────────────────────────────┐
│              Kubernetes Cluster          │
│                                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │ RB Pod  │ │ RB Pod  │ │ RB Pod  │  │
│  └────┬────┘ └────┬────┘ └────┬────┘  │
│       │           │           │        │
│  ┌────┴───────────┴───────────┴────┐   │
│  │        Kubernetes Service        │   │
│  └──────────────┬──────────────────┘   │
│                 │                       │
│  ┌──────────┐  │  ┌──────────┐         │
│  │ PG Pool  │──┘──│  Redis   │         │
│  │ (PgBouncer)│    │ Sentinel │         │
│  └──────────┘     └──────────┘         │
│                                         │
│  ┌──────────────────────────────┐      │
│  │  Prometheus + Grafana Stack  │      │
│  └──────────────────────────────┘      │
└─────────────────────────────────────────┘
```

---

## Directory Structure

```
routerbot/
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── pyproject.toml
├── Makefile
├── Dockerfile
├── docker-compose.yml
├── docker-compose.prod.yml
├── routerbot_config.yaml          # Example config
├── alembic.ini
├── docs/
│   ├── IMPLEMENTATION_PLAN.md
│   ├── ARCHITECTURE.md
│   ├── CODING_STANDARDS.md
│   ├── CONTAINER.md
│   ├── AGENT_INSTRUCTIONS.md
│   └── stages/
│       ├── STAGE_1_CORE_FOUNDATION.md
│       ├── STAGE_2_PROVIDER_INTEGRATION.md
│       ├── STAGE_3_PROXY_SERVER.md
│       ├── STAGE_4_AUTH_MANAGEMENT.md
│       ├── STAGE_5_OBSERVABILITY.md
│       ├── STAGE_6_ADVANCED_FEATURES.md
│       ├── STAGE_7_DASHBOARD_UI.md
│       └── STAGE_8_FUTURE_ROADMAP.md
├── src/
│   └── routerbot/
│       ├── __init__.py
│       ├── py.typed
│       ├── core/
│       │   ├── __init__.py
│       │   ├── completion.py      # Main completion interface
│       │   ├── streaming.py       # Streaming handler
│       │   ├── embeddings.py      # Embeddings interface
│       │   ├── images.py          # Image generation
│       │   ├── audio.py           # Audio endpoints
│       │   ├── rerank.py          # Reranking
│       │   ├── batches.py         # Batch processing
│       │   ├── exceptions.py      # Exception hierarchy
│       │   ├── types.py           # Pydantic models (request/response)
│       │   ├── cost.py            # Cost calculation
│       │   ├── tokens.py          # Token counting
│       │   └── config.py          # Config loading
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── base.py            # Abstract provider base
│       │   ├── registry.py        # Provider registration
│       │   ├── openai/
│       │   ├── anthropic/
│       │   ├── azure/
│       │   ├── bedrock/
│       │   ├── vertex_ai/
│       │   ├── gemini/
│       │   ├── groq/
│       │   ├── ollama/
│       │   ├── mistral/
│       │   ├── cohere/
│       │   ├── deepseek/
│       │   └── openai_compatible/  # Generic OpenAI-compat adapter
│       ├── router/
│       │   ├── __init__.py
│       │   ├── router.py          # Main router
│       │   ├── strategies.py      # Load balancing strategies
│       │   ├── retry.py           # Retry logic
│       │   ├── fallback.py        # Fallback chains
│       │   ├── health.py          # Health checking
│       │   └── cooldown.py        # Cooldown management
│       ├── proxy/
│       │   ├── __init__.py
│       │   ├── app.py             # FastAPI app factory
│       │   ├── cli.py             # CLI entry point
│       │   ├── config.py          # Proxy config
│       │   ├── middleware/
│       │   │   ├── auth.py        # Authentication
│       │   │   ├── rate_limit.py  # Rate limiting
│       │   │   ├── ip_filter.py   # IP allowlist/blocklist
│       │   │   ├── size_limit.py  # Request/response size limits
│       │   │   └── logging.py     # Request logging
│       │   ├── routes/
│       │   │   ├── completions.py
│       │   │   ├── embeddings.py
│       │   │   ├── images.py
│       │   │   ├── audio.py
│       │   │   ├── models.py
│       │   │   ├── keys.py
│       │   │   ├── teams.py
│       │   │   ├── users.py
│       │   │   ├── spend.py
│       │   │   ├── health.py
│       │   │   └── config.py
│       │   └── guardrails/
│       │       ├── __init__.py
│       │       ├── base.py
│       │       ├── pii_detection.py
│       │       ├── content_moderation.py
│       │       ├── banned_keywords.py
│       │       ├── secret_detection.py
│       │       └── custom.py
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── api_key.py         # API key auth
│       │   ├── jwt.py             # JWT auth
│       │   ├── sso.py             # SSO (OIDC/SAML)
│       │   ├── rbac.py            # Role-based access control
│       │   └── session.py         # Session management
│       ├── db/
│       │   ├── __init__.py
│       │   ├── engine.py          # SQLAlchemy engine
│       │   ├── models.py          # ORM models
│       │   ├── repositories/      # Data access layer
│       │   │   ├── keys.py
│       │   │   ├── teams.py
│       │   │   ├── users.py
│       │   │   ├── spend.py
│       │   │   └── audit.py
│       │   └── migrations/        # Alembic migrations
│       ├── cache/
│       │   ├── __init__.py
│       │   ├── redis.py           # Redis cache backend
│       │   ├── memory.py          # In-memory cache
│       │   └── base.py            # Cache interface
│       ├── observability/
│       │   ├── __init__.py
│       │   ├── callbacks.py       # Callback system
│       │   ├── prometheus.py      # Prometheus metrics
│       │   ├── langfuse.py        # Langfuse integration
│       │   ├── opentelemetry.py   # OpenTelemetry
│       │   └── exporters/         # Log exporters (GCS, S3, etc.)
│       └── utils/
│           ├── __init__.py
│           ├── hashing.py         # Key hashing
│           ├── encoding.py        # Token encoding
│           └── secrets.py         # Secret manager integrations
├── ui/
│   └── dashboard/
│       ├── package.json
│       ├── tsconfig.json
│       ├── src/
│       │   ├── App.tsx
│       │   ├── pages/
│       │   ├── components/
│       │   └── api/
│       └── public/
├── tests/
│   ├── conftest.py
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── deploy/
│   ├── helm/
│   │   └── routerbot/
│   └── terraform/
└── scripts/
    ├── migrate.py
    └── seed.py
```
