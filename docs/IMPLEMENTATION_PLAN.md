# RouterBot — Master Implementation Plan

**Project:** RouterBot — Open Source LLM Gateway  
**License:** Apache 2.0  
**Goal:** Build a fully open-source LLM gateway with zero feature paywalls — every capability available to everyone, forever.

---

## Overview

RouterBot is implemented in 8 sequential stages. Each stage produces a fully working, tested, and deployed artifact that the next stage builds upon. AI Agents execute each stage autonomously by reading the corresponding stage plan document.

---

## Stage Summary

| Stage | Name | Duration | Status | Owner Agents |
|-------|------|----------|--------|--------------|
| [Stage 1](stages/STAGE_1_CORE_FOUNDATION.md) | Core Foundation | 2-3 weeks | ✅ Complete | DevOps, Backend |
| [Stage 2](stages/STAGE_2_PROVIDER_INTEGRATION.md) | Provider Integration | 3-4 weeks | ✅ Complete | Backend |
| [Stage 3](stages/STAGE_3_PROXY_SERVER.md) | Proxy Server | 3-4 weeks | ✅ Complete | Backend, DevOps |
| [Stage 4](stages/STAGE_4_AUTH_MANAGEMENT.md) | Auth & Management | 3-4 weeks | ✅ Complete | Backend |
| [Stage 5](stages/STAGE_5_OBSERVABILITY.md) | Observability | 2-3 weeks | ✅ Complete | Backend, DevOps |
| [Stage 6](stages/STAGE_6_ADVANCED_FEATURES.md) | Advanced Features | 3-4 weeks | ✅ Complete | Backend |
| [Stage 7](stages/STAGE_7_DASHBOARD_UI.md) | Dashboard & UI | 4-5 weeks | ✅ Complete | Frontend, Backend |
| [Stage 8](stages/STAGE_8_FUTURE_ROADMAP.md) | Future Roadmap | Ongoing | 🔧 In Progress | Various |

**Total Estimated Duration:** ~23-30 weeks to Stage 7 completion

---

## Dependency Graph

```
Stage 1 (Foundation)
    └─► Stage 2 (Providers)
            └─► Stage 3 (Proxy)
                    └─► Stage 4 (Auth)
                            ├─► Stage 5 (Observability)
                            └─► Stage 6 (Advanced)
                                    └─► Stage 7 (Dashboard)
                                            └─► Stage 8 (Future — parallel tracks)
```

Each stage **must be fully complete** (all acceptance criteria passing, all tests green) before the next stage begins.

---

## Stage Details

### Stage 1: Core Foundation
**[Full Plan →](stages/STAGE_1_CORE_FOUNDATION.md)**

Establishes the entire project skeleton that all other stages build on.

**Key Deliverables:**
- Project scaffolding: `pyproject.toml`, `Makefile`, directory structure
- CI/CD pipeline via GitHub Actions
- Configuration system (`routerbot/core/config.py`) with environment variable loading
- Unified type system: `ModelRequest`, `ModelResponse`, `StreamChunk`, all exceptions
- Cost/token counting utilities and model pricing registry
- Docker Compose for local development (PostgreSQL + Redis)
- Database setup: SQLAlchemy async engine, Alembic migrations framework

**Definition of Done:**
```bash
make install-dev  # Works
make lint         # Passes
make type-check   # Passes
make test-unit    # Passes
docker compose up # PostgreSQL + Redis healthy
```

---

### Stage 2: Provider Integration
**[Full Plan →](stages/STAGE_2_PROVIDER_INTEGRATION.md)**

Implements all LLM provider adapters under a unified interface.

**Key Deliverables:**
- `BaseProvider` abstract class with standard interface
- Provider adapters: OpenAI, Anthropic, Azure OpenAI, Google Gemini, AWS Bedrock, Vertex AI, Groq, Ollama, vLLM, Cohere, Mistral, Together AI, Replicate, Perplexity, HuggingFace
- Streaming support (SSE parsing, chunk normalization) for all providers
- Embeddings, image generation, audio (TTS/STT), reranking support
- Provider-level retry logic with exponential backoff
- Top-level `completion()` / `acompletion()` SDK entrypoint

**Definition of Done:**
```bash
# Each provider passes its integration test suite
pytest tests/providers/ -v
# SDK works end-to-end
python -c "from routerbot import completion; completion('openai/gpt-4o', [...])"
```

---

### Stage 3: Proxy Server
**[Full Plan →](stages/STAGE_3_PROXY_SERVER.md)**

The FastAPI gateway that wraps the SDK as a deployable HTTP service.

**Key Deliverables:**
- OpenAI-compatible endpoints: `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `/v1/images/generations`, `/v1/audio/*`, `/v1/models`, `/v1/responses`
- Request/response middleware pipeline
- Model alias routing (`gpt-4` → `openai/gpt-4o`)
- Load balancer with weighted round-robin, least-latency, and cost-optimized strategies
- Retry and fallback routing (model groups)
- Health check endpoints (`/health`, `/health/readiness`, `/health/liveness`)
- OpenAPI documentation auto-generation

**Definition of Done:**
```bash
docker compose up
curl http://localhost:4000/health  # 200 OK
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-test" \
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}]}'
# Returns valid OpenAI-format response
```

---

### Stage 4: Auth & Management
**[Full Plan →](stages/STAGE_4_AUTH_MANAGEMENT.md)**

Full authentication, authorization, and management API — all free, no enterprise gates.

**Key Deliverables:**
- Virtual API key system (create, rotate, revoke, scope)
- JWT authentication with configurable secret
- SSO: SAML 2.0, OIDC, OAuth2 (GitHub, Google, Microsoft) — **free, no paywall**
- Role-Based Access Control: `admin`, `org_admin`, `proxy_admin`, `proxy_viewer`, `team_admin`, `team_member`, `internal_user`
- Team management: create teams, assign members, set spend limits
- Organization management: multi-org support
- IP allowlist/denylist per key and per team — **free, no paywall**
- Key rotation with configurable schedules — **free, no paywall**
- Spend limits: per-key, per-team, per-user, per-model
- Audit log system with full request history — **free, no paywall**
- GDPR-compliant team logging controls — **free, no paywall**
- Model access control: allowlist/denylist per key/team

**Definition of Done:**
```bash
# Create a virtual key
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"models":["gpt-4o"],"max_budget":10.0}'
# Use that key
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $VIRTUAL_KEY" \
  -d '{"model":"gpt-4o","messages":[...]}'
# SSO login flow works
# Audit log captures both requests
```

---

### Stage 5: Observability
**[Full Plan →](stages/STAGE_5_OBSERVABILITY.md)**

Full-stack observability: logging, metrics, tracing, and callback integrations.

**Key Deliverables:**
- Structured JSON request/response logging to PostgreSQL
- Prometheus metrics: latency, token counts, spend, error rates, provider health
- Grafana dashboard provisioning (pre-built dashboards)
- OpenTelemetry tracing with configurable exporters (Jaeger, OTLP)
- Callback system: LangSmith, LangFuse, Helicone, custom webhook callbacks
- Slack/PagerDuty/email alerting for budget thresholds and error spikes
- Spend analytics API: per-key, per-team, per-model aggregations
- Data export: CSV/JSON spend reports — **free, no paywall**

**Definition of Done:**
```bash
# Prometheus scrapes RouterBot metrics
curl http://localhost:9090/metrics | grep routerbot_
# Grafana dashboards load
open http://localhost:3000
# LangFuse receives traces when configured
```

---

### Stage 6: Advanced Features
**[Full Plan →](stages/STAGE_6_ADVANCED_FEATURES.md)**

Production hardening features — all open source.

**Key Deliverables:**
- Semantic caching with Redis (embedding-based similarity matching)
- Guardrails system: input/output content moderation — **free per key/team, no paywall**
- Secret detection and PII redaction in prompts — **free, no paywall**
- Max request/response size controls per key/team — **free, no paywall**
- LLM translation layer (OpenAI ↔ Anthropic ↔ Bedrock format bridging)
- Request batching for supported providers
- Prompt management API (store/version/retrieve prompts)
- Webhook support for async request notifications
- Custom provider support (BYO provider adapter)
- Background budget refresh tasks

**Definition of Done:**
```bash
# Cache hit demonstrated
# Guardrail blocks unsafe content
# Secret redacted from logs
# Custom provider registered and routes correctly
```

---

### Stage 7: Admin Dashboard
**[Full Plan →](stages/STAGE_7_DASHBOARD_UI.md)**

React SPA providing full management UI for all RouterBot features.

**Key Deliverables:**
- Dashboard layout with sidebar navigation and responsive design
- Model management: virtual model CRUD, provider config, health status
- API key management: create/view/rotate/revoke keys, usage graphs
- Team management: teams, members, spend limits, notifications
- Spend analytics: charts, breakdowns by model/team/key, export
- Guardrails configuration UI
- SSO configuration wizard
- System settings: general config, alerting, connection health
- Custom branding: logo, colors, instance name — **free, no paywall**
- Dark/light mode

**Definition of Done:**
```bash
open http://localhost:4000/dashboard
# All CRUD operations work
# Charts render with real spend data
# SSO login completes successfully
# Mobile layout is usable
```

---

### Stage 8: Future Roadmap
**[Full Plan →](stages/STAGE_8_FUTURE_ROADMAP.md)**

Long-term platform extensions, executed in parallel tracks post Stage 7.

| Phase | Feature | Timeline |
|-------|---------|----------|
| 8A | MCP Gateway (connect MCP servers to LLMs) | Month 1-2 |
| 8B | A2A (Agent-to-Agent) Protocol | Month 2-3 |
| 8C | Plugin System (3rd party extensions) | Month 3-4 |
| 8D | AI Gateway Analytics Platform | Month 4-5 |
| 8E | Marketplace (provider/plugin registry) | Month 5-6 |
| 8F | Multi-region & HA deployments | Month 6-8 |
| 8G | Evaluation Framework | Month 6-8 |
| 8H | LLM Workflows (orchestration DSL) | Month 8-10 |

---

## What Is Always Free

RouterBot maintains an **absolute no-paywall commitment**. The following features that are enterprise-only in competing products will always be free in RouterBot:

| Feature | RouterBot | Others |
|---------|-----------|--------|
| SSO (SAML, OIDC, OAuth2) | ✅ Free | 🔒 Enterprise |
| Audit Logs + Retention Controls | ✅ Free | 🔒 Enterprise |
| JWT Authentication | ✅ Free | 🔒 Enterprise |
| IP-Based Access Control | ✅ Free | 🔒 Enterprise |
| Team-Based Logging | ✅ Free | 🔒 Enterprise |
| Guardrails per Key/Team | ✅ Free | 🔒 Enterprise |
| Secret Detection & Redaction | ✅ Free | 🔒 Enterprise |
| Custom Branding/Logo | ✅ Free | 🔒 Enterprise |
| GDPR Team Logging Controls | ✅ Free | 🔒 Enterprise |
| Spend Reports & CSV Export | ✅ Free | 🔒 Enterprise |
| Key Rotation Schedules | ✅ Free | 🔒 Enterprise |
| Max Request/Response Size | ✅ Free | 🔒 Enterprise |
| Custom Roles & RBAC | ✅ Free | 🔒 Enterprise |
| Prometheus / Grafana Metrics | ✅ Free | 🔒 Enterprise |

---

## Tech Stack Reference

| Layer | Technology | Version |
|-------|------------|---------|
| Language | Python | 3.11+ |
| Web Framework | FastAPI + Uvicorn | Latest stable |
| ORM | SQLAlchemy (async) | 2.0+ |
| Migrations | Alembic | Latest |
| Database | PostgreSQL | 15+ |
| Cache | Redis | 7+ |
| Frontend | React + TypeScript | React 18+ |
| UI Build | Vite | Latest |
| Styling | Tailwind CSS | v3 |
| State | TanStack Query + Zustand | Latest |
| Container | Docker + Compose | Latest |
| Orchestration | Kubernetes + Helm | Latest |
| Metrics | Prometheus + Grafana | Latest |
| Tracing | OpenTelemetry | Latest |
| Linting | Ruff + MyPy | Latest |
| Testing | pytest + pytest-asyncio | Latest |
| CI/CD | GitHub Actions | — |

---

## Key Documents

| Document | Purpose |
|----------|---------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, module structure, data flow diagrams |
| [CODING_STANDARDS.md](CODING_STANDARDS.md) | Mandatory code style, patterns, and quality rules |
| [CONTAINER.md](CONTAINER.md) | Docker, Compose, Kubernetes deployment guide |
| [AGENT_INSTRUCTIONS.md](AGENT_INSTRUCTIONS.md) | How AI agents should work on this codebase |

---

## Getting Started (for Agents)

1. Read [AGENT_INSTRUCTIONS.md](AGENT_INSTRUCTIONS.md) first
2. Read [CODING_STANDARDS.md](CODING_STANDARDS.md) — mandatory
3. Read [ARCHITECTURE.md](ARCHITECTURE.md) — understand the system
4. Read the current stage plan in `docs/stages/`
5. Pick the next unchecked task in the stage plan
6. Implement, test, commit following the standards
7. Mark the task complete in the stage plan
