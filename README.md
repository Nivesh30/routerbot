# 🚀 RouterBot — Open Source LLM Gateway

**Call 100+ LLMs through a single, unified API. No enterprise paywalls.**

RouterBot is a fully open-source LLM gateway and proxy server that provides a unified OpenAI-compatible API for routing requests to any LLM provider. Every feature — SSO, RBAC, guardrails, audit logs, advanced spend tracking — is free and open source. No enterprise tier, no license keys, no artificial limits.

---

## Why RouterBot?

Existing LLM gateways gate critical production features (SSO, audit logs, granular RBAC, guardrails, team-based logging, IP access control) behind expensive enterprise licenses. RouterBot provides **all** of these features to everyone:

| Feature | RouterBot | Others |
|---|---|---|
| SSO (SAML, OIDC, OAuth2) | ✅ Free | 🔒 Enterprise |
| Audit Logs with Retention | ✅ Free | 🔒 Enterprise |
| JWT Authentication | ✅ Free | 🔒 Enterprise |
| IP-Based Access Control | ✅ Free | 🔒 Enterprise |
| Team-Based Logging | ✅ Free | 🔒 Enterprise |
| Guardrails per Key/Team | ✅ Free | 🔒 Enterprise |
| Secret Detection/Redaction | ✅ Free | 🔒 Enterprise |
| Custom Branding | ✅ Free | 🔒 Enterprise |
| GDPR Team Logging Control | ✅ Free | 🔒 Enterprise |
| Spend Reports & Data Export | ✅ Free | 🔒 Enterprise |
| Key Rotation | ✅ Free | 🔒 Enterprise |
| Max Request/Response Size | ✅ Free | 🔒 Enterprise |

---

## Core Capabilities

- **Unified API**: OpenAI-compatible `/chat/completions`, `/responses`, `/embeddings`, `/images`, `/audio`, `/batches`, `/rerank` endpoints
- **100+ Providers**: OpenAI, Anthropic, Azure, Bedrock, Vertex AI, Gemini, Groq, Ollama, vLLM, and many more
- **AI Gateway (Proxy Server)**: Centralized LLM gateway with auth, rate limiting, load balancing, and cost tracking
- **Python SDK**: Direct library integration with retry/fallback routing
- **Admin Dashboard**: Full management UI for keys, models, teams, spend, and configuration
- **Container-First**: Production-ready Docker images with Helm charts for Kubernetes

---

## Quick Start

### Docker (Recommended)

```bash
docker compose up -d
```

### From Source

```bash
git clone https://github.com/your-org/routerbot.git
cd routerbot
make install-dev
make run
```

### Python SDK

```bash
pip install routerbot
```

```python
from routerbot import completion

response = completion(
    model="openai/gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### Proxy Server

```python
import openai

client = openai.OpenAI(api_key="rb-your-key", base_url="http://localhost:4000")
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

---

## Documentation

| Document | Description |
|---|---|
| [Implementation Plan](docs/IMPLEMENTATION_PLAN.md) | Master implementation roadmap |
| [Architecture](docs/ARCHITECTURE.md) | System architecture and design decisions |
| [Coding Standards](docs/CODING_STANDARDS.md) | Code style, conventions, and quality rules |
| [Container & Deployment](docs/CONTAINER.md) | Docker, Compose, Kubernetes deployment guide |
| [Agent Instructions](docs/AGENT_INSTRUCTIONS.md) | Instructions for AI agents working on this codebase |
| **Stage Plans** | |
| [Stage 1: Core Foundation](docs/stages/STAGE_1_CORE_FOUNDATION.md) | Project scaffolding, SDK structure, config system |
| [Stage 2: Provider Integration](docs/stages/STAGE_2_PROVIDER_INTEGRATION.md) | LLM provider adapters and unified interface |
| [Stage 3: Proxy Server](docs/stages/STAGE_3_PROXY_SERVER.md) | API gateway, routing, middleware |
| [Stage 4: Auth & Management](docs/stages/STAGE_4_AUTH_MANAGEMENT.md) | Virtual keys, RBAC, SSO, teams |
| [Stage 5: Observability](docs/stages/STAGE_5_OBSERVABILITY.md) | Logging, metrics, callbacks, tracing |
| [Stage 6: Advanced Features](docs/stages/STAGE_6_ADVANCED_FEATURES.md) | Guardrails, caching, rate limiting |
| [Stage 7: Dashboard & UI](docs/stages/STAGE_7_DASHBOARD_UI.md) | Admin dashboard, management UI |
| [Stage 8: Future Roadmap](docs/stages/STAGE_8_FUTURE_ROADMAP.md) | MCP, A2A, plugins, marketplace |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Web Framework | FastAPI + Uvicorn |
| Database | PostgreSQL (via SQLAlchemy + Alembic) |
| Cache | Redis |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Frontend | React + TypeScript + Tailwind CSS |
| Container | Docker + Docker Compose |
| Orchestration | Kubernetes + Helm |
| Metrics | Prometheus + Grafana |
| Testing | pytest + pytest-asyncio |
| Linting | Ruff + MyPy |
| Formatting | Ruff formatter |
| CI/CD | GitHub Actions |

---

## License

[Apache License 2.0](LICENSE) — Use it however you want. No enterprise keys. No paywalls. Ever.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines. All contributions welcome.
