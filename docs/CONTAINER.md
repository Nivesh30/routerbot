# RouterBot — Container & Deployment Guide

Complete guide for running RouterBot in containers: local development, staging, and production Kubernetes.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Local Development with Docker Compose](#local-development-with-docker-compose)
- [Environment Variables Reference](#environment-variables-reference)
- [Docker Images](#docker-images)
- [Production Docker Compose](#production-docker-compose)
- [Kubernetes with Helm](#kubernetes-with-helm)
- [Database Migrations](#database-migrations)
- [Health Checks](#health-checks)
- [Scaling](#scaling)
- [Monitoring Stack](#monitoring-stack)
- [Security Hardening](#security-hardening)
- [Multi-Region Deployment](#multi-region-deployment)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Tool | Minimum Version | Purpose |
|------|-----------------|---------|
| Docker | 24.0+ | Container runtime |
| Docker Compose | v2.20+ | Local orchestration |
| kubectl | 1.28+ | Kubernetes CLI |
| helm | 3.13+ | Kubernetes package manager |
| make | Any | Build automation |

---

## Local Development with Docker Compose

### Quick Start

```bash
# Clone and configure
git clone https://github.com/Nivesh30/routerbot.git
cd routerbot
cp .env.example .env
# Edit .env with your provider API keys

# Start core services (routerbot + postgres + redis)
docker compose up -d

# Start with monitoring (adds Prometheus + Grafana)
docker compose --profile monitoring up -d

# Verify everything is healthy
docker compose ps
curl http://localhost:8000/health
```

### Services Started

| Service | Port | Profile | Description |
|---------|------|---------|-------------|
| `routerbot` | `8000` | default | Proxy API server |
| `postgres` | `5432` | default | PostgreSQL database |
| `redis` | `6379` | default | Redis cache |
| `dashboard` | `8000/ui/` | default | Admin UI (served by proxy) |
| `prometheus` | `9090` | monitoring | Metrics scraping |
| `grafana` | `3000` | monitoring | Dashboards (admin/routerbot) |

### `docker-compose.yml` (Development)

```yaml
version: "3.9"

services:
  routerbot:
    build:
      context: .
      dockerfile: Dockerfile
      target: development
    ports:
      - "4000:4000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://routerbot:routerbot@postgres:5432/routerbot
      - REDIS_URL=redis://redis:6379/0
      - MASTER_KEY=${MASTER_KEY:-sk-routerbot-master}
      - LOG_LEVEL=DEBUG
    env_file:
      - .env
    volumes:
      - ./src:/app/src:ro          # Live reload in dev
      - ./config:/app/config:ro
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: routerbot
      POSTGRES_PASSWORD: routerbot
      POSTGRES_DB: routerbot
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U routerbot -d routerbot"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./deploy/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--storage.tsdb.retention.time=30d'
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_PATHS_PROVISIONING=/etc/grafana/provisioning
    volumes:
      - ./deploy/grafana/provisioning:/etc/grafana/provisioning:ro
      - grafana_data:/var/lib/grafana
    depends_on:
      - prometheus
    restart: unless-stopped

volumes:
  postgres_data:
  redis_data:
  prometheus_data:
  grafana_data:
```

---

## Environment Variables Reference

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string (async) | `postgresql+asyncpg://user:pass@host:5432/db` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `MASTER_KEY` | Master API key for admin operations | `sk-routerbot-CHANGE-THIS` |

### Provider API Keys (set the ones you use)

| Variable | Provider |
|----------|---------|
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI |
| `AWS_ACCESS_KEY_ID` | AWS Bedrock |
| `AWS_SECRET_ACCESS_KEY` | AWS Bedrock |
| `AWS_REGION` | AWS Bedrock |
| `GEMINI_API_KEY` | Google Gemini |
| `VERTEX_PROJECT` | Google Vertex AI |
| `VERTEX_LOCATION` | Google Vertex AI |
| `GROQ_API_KEY` | Groq |
| `COHERE_API_KEY` | Cohere |
| `MISTRAL_API_KEY` | Mistral |
| `TOGETHER_API_KEY` | Together AI |
| `PERPLEXITY_API_KEY` | Perplexity |

### Optional Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_FORMAT` | `json` | Log format (`json` or `text`) |
| `PORT` | `4000` | HTTP server port |
| `HOST` | `0.0.0.0` | HTTP server bind address |
| `WORKERS` | `1` | Uvicorn worker count (use 1 for single-process with async) |
| `MAX_CONNECTIONS` | `1000` | Max concurrent HTTP connections |
| `REQUEST_TIMEOUT` | `600` | Request timeout in seconds |
| `DB_POOL_SIZE` | `20` | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | `10` | SQLAlchemy pool overflow |
| `CACHE_TTL` | `3600` | Default cache TTL in seconds |
| `JWT_SECRET_KEY` | — | JWT signing secret (required if using JWT auth) |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_EXPIRY` | `86400` | JWT token expiry in seconds |
| `SSO_PROVIDER` | `none` | SSO type: `okta`, `google`, `github`, `saml`, `oidc` |
| `SSO_CLIENT_ID` | — | OAuth2 client ID |
| `SSO_CLIENT_SECRET` | — | OAuth2 client secret |
| `SAML_IDP_METADATA_URL` | — | SAML IdP metadata URL |
| `PROMETHEUS_ENABLED` | `true` | Expose `/metrics` endpoint |
| `OTEL_ENABLED` | `false` | Enable OpenTelemetry tracing |
| `OTEL_ENDPOINT` | — | OTLP exporter endpoint |
| `SLACK_WEBHOOK_URL` | — | Alerts webhook |
| `STORE_MODEL_RESPONSES` | `true` | Persist responses to DB |
| `RESPONSE_RETENTION_DAYS` | `30` | Days to retain response logs |
| `MAX_REQUEST_SIZE_MB` | `10` | Max incoming request body size |
| `MAX_RESPONSE_SIZE_MB` | `50` | Max response size for logging |
| `SEMANTIC_CACHE_ENABLED` | `false` | Enable semantic caching |
| `SEMANTIC_CACHE_SIMILARITY` | `0.95` | Cosine similarity threshold |

---

## Docker Images

### Dockerfile (Multi-Stage)

```dockerfile
# syntax=docker/dockerfile:1

# ─── Base ──────────────────────────────────────────────
FROM python:3.11-slim AS base
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency installation
RUN pip install uv

# ─── Dependencies ──────────────────────────────────────
FROM base AS dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ─── Development ───────────────────────────────────────
FROM base AS development
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen  # Includes dev deps
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
EXPOSE 4000
ENV PYTHONPATH=/app/src
CMD ["uv", "run", "uvicorn", "routerbot.proxy.main:app", \
     "--host", "0.0.0.0", "--port", "4000", "--reload"]

# ─── Builder (compile UI assets) ───────────────────────
FROM node:20-alpine AS ui-builder
WORKDIR /ui
COPY ui/dashboard/package.json ui/dashboard/pnpm-lock.yaml ./
RUN npm install -g pnpm && pnpm install --frozen-lockfile
COPY ui/dashboard/ .
RUN pnpm build

# ─── Production ────────────────────────────────────────
FROM dependencies AS production
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY --from=ui-builder /ui/dist /app/src/routerbot/proxy/static/dashboard

ENV PYTHONPATH=/app/src
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Non-root user
RUN groupadd --gid 1001 routerbot && \
    useradd --uid 1001 --gid routerbot --shell /bin/sh --create-home routerbot
USER routerbot

EXPOSE 4000
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:4000/health || exit 1

CMD ["uv", "run", "uvicorn", "routerbot.proxy.main:app", \
     "--host", "0.0.0.0", "--port", "4000", \
     "--workers", "1", \
     "--log-config", "/app/src/routerbot/log_config.json"]
```

### Building Images

```bash
# Development image
docker build --target development -t routerbot:dev .

# Production image
docker build --target production -t routerbot:latest .

# With version tag
docker build --target production \
  --build-arg VERSION=$(git describe --tags) \
  -t routerbot:$(git describe --tags) .
```

### Published Images

```bash
# Pull from GitHub Container Registry (once published)
docker pull ghcr.io/your-org/routerbot:latest
docker pull ghcr.io/your-org/routerbot:v1.2.3
```

---

## Production Docker Compose

For production single-host deployments (small scale):

```yaml
version: "3.9"

services:
  routerbot:
    image: ghcr.io/your-org/routerbot:latest
    restart: always
    ports:
      - "4000:4000"
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
      MASTER_KEY: ${MASTER_KEY}
      LOG_LEVEL: INFO
      WORKERS: 1
    env_file: .env.production
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 1g
          cpus: "1.0"

  # Run migrations before starting the main service
  migrate:
    image: ghcr.io/your-org/routerbot:latest
    command: uv run alembic upgrade head
    environment:
      DATABASE_URL: ${DATABASE_URL}
    env_file: .env.production
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: postgres:16-alpine
    restart: always
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    restart: always
    command: >
      redis-server
      --requirepass ${REDIS_PASSWORD}
      --appendonly yes
      --maxmemory 1gb
      --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  nginx:
    image: nginx:alpine
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./deploy/nginx/ssl:/etc/nginx/ssl:ro
    depends_on:
      - routerbot

volumes:
  postgres_data:
  redis_data:
```

---

## Kubernetes with Helm

### Directory Structure

```
deploy/helm/routerbot/
├── Chart.yaml
├── values.yaml           # Default values
├── values.prod.yaml      # Production overrides
├── templates/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── hpa.yaml          # Horizontal Pod Autoscaler
│   ├── pdb.yaml          # Pod Disruption Budget
│   ├── serviceaccount.yaml
│   ├── migration-job.yaml
│   └── NOTES.txt
└── charts/               # Sub-charts (postgres, redis via Bitnami)
```

### `Chart.yaml`

```yaml
apiVersion: v2
name: routerbot
description: Open Source LLM Gateway — RouterBot
type: application
version: 0.1.0
appVersion: "1.0.0"
dependencies:
  - name: postgresql
    version: "13.x.x"
    repository: oci://registry-1.docker.io/bitnamicharts
    condition: postgresql.enabled
  - name: redis
    version: "18.x.x"
    repository: oci://registry-1.docker.io/bitnamicharts
    condition: redis.enabled
```

### `values.yaml` (Key Sections)

```yaml
replicaCount: 2

image:
  repository: ghcr.io/your-org/routerbot
  tag: latest
  pullPolicy: IfNotPresent

service:
  type: ClusterIP
  port: 4000

ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: routerbot.your-domain.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: routerbot-tls
      hosts:
        - routerbot.your-domain.com

resources:
  requests:
    memory: 256Mi
    cpu: 250m
  limits:
    memory: 1Gi
    cpu: 1000m

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80

config:
  logLevel: INFO
  port: 4000
  workers: 1
  storeModelResponses: true
  responseRetentionDays: 30
  prometheusEnabled: true

postgresql:
  enabled: true
  auth:
    username: routerbot
    database: routerbot
    existingSecret: routerbot-postgres-secret

redis:
  enabled: true
  auth:
    existingSecret: routerbot-redis-secret

migrations:
  enabled: true
  runOnUpgrade: true
```

### Deploy to Kubernetes

```bash
# Add Bitnami repo for PostgreSQL and Redis
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Update chart dependencies
helm dependency update deploy/helm/routerbot/

# Create namespace
kubectl create namespace routerbot

# Create secrets (never commit these)
kubectl create secret generic routerbot-secrets \
  --namespace routerbot \
  --from-literal=MASTER_KEY="sk-prod-CHANGE-THIS" \
  --from-literal=OPENAI_API_KEY="${OPENAI_API_KEY}" \
  --from-literal=ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}"

kubectl create secret generic routerbot-postgres-secret \
  --namespace routerbot \
  --from-literal=password="${POSTGRES_PASSWORD}"

kubectl create secret generic routerbot-redis-secret \
  --namespace routerbot \
  --from-literal=password="${REDIS_PASSWORD}"

# Install
helm install routerbot deploy/helm/routerbot/ \
  --namespace routerbot \
  --values deploy/helm/routerbot/values.prod.yaml \
  --set image.tag=v1.0.0

# Upgrade
helm upgrade routerbot deploy/helm/routerbot/ \
  --namespace routerbot \
  --values deploy/helm/routerbot/values.prod.yaml \
  --set image.tag=v1.1.0

# Status
helm status routerbot --namespace routerbot
kubectl get pods --namespace routerbot
kubectl logs -l app=routerbot --namespace routerbot -f
```

---

## Database Migrations

RouterBot uses [Alembic](https://alembic.sqlalchemy.org/) for schema migrations.

### Running Migrations

```bash
# In development (via Compose)
docker compose exec routerbot uv run alembic upgrade head

# Apply specific migration
docker compose exec routerbot uv run alembic upgrade +1

# Check current revision
docker compose exec routerbot uv run alembic current

# View migration history
docker compose exec routerbot uv run alembic history --verbose

# Rollback one step
docker compose exec routerbot uv run alembic downgrade -1
```

### Creating New Migrations

```bash
# Auto-generate from model changes
docker compose exec routerbot uv run alembic revision \
  --autogenerate -m "add_guardrails_table"

# Create blank migration
docker compose exec routerbot uv run alembic revision \
  -m "backfill_team_spend"
```

### Migration in Production

Migrations run automatically as a Kubernetes Job before the main deployment in Helm (`migrations.runOnUpgrade: true`). In Docker Compose production, the `migrate` service runs first.

**Never run migrations against production without**:
1. A database backup
2. Testing the migration on a staging environment
3. Verifying the downgrade migration works

---

## Health Checks

RouterBot exposes three health endpoints:

| Endpoint | Purpose | Used By |
|----------|---------|---------|
| `GET /health` | Basic liveness check | Docker `HEALTHCHECK` |
| `GET /health/readiness` | Ready to serve traffic (DB + Redis connected) | Kubernetes readiness probe |
| `GET /health/liveness` | Process is alive and not deadlocked | Kubernetes liveness probe |

### Response Format

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "checks": {
    "database": "healthy",
    "redis": "healthy",
    "providers": {
      "openai": "healthy",
      "anthropic": "healthy"
    }
  },
  "uptime_seconds": 3600
}
```

### Kubernetes Probe Configuration

```yaml
readinessProbe:
  httpGet:
    path: /health/readiness
    port: 4000
  initialDelaySeconds: 20
  periodSeconds: 10
  failureThreshold: 3

livenessProbe:
  httpGet:
    path: /health/liveness
    port: 4000
  initialDelaySeconds: 40
  periodSeconds: 30
  failureThreshold: 3
```

---

## Scaling

### Horizontal Scaling Considerations

RouterBot is designed to be horizontally scalable:

- **Stateless process**: All state lives in PostgreSQL and Redis
- **Redis-backed caching**: Shared cache across instances
- **Redis-backed rate limiting**: Consistent enforcement across pods
- **Async-first**: Single worker handles high concurrency via async I/O

### Recommended Sizing

| Traffic | Replicas | CPU/Instance | Memory/Instance |
|---------|----------|--------------|-----------------|
| Low (<100 req/min) | 1–2 | 250m–500m | 256Mi–512Mi |
| Medium (<1000 req/min) | 2–4 | 500m–1000m | 512Mi–1Gi |
| High (<10000 req/min) | 4–10 | 1000m | 1Gi |
| Very High (>10000 req/min) | 10+ + HPA | 1000m | 1Gi |

### Database Scaling

For high traffic, use a managed PostgreSQL service (RDS, Cloud SQL, Supabase) with:
- Read replica for analytics/reporting queries
- Connection pooling via PgBouncer
- Regular VACUUM and index maintenance

---

## Monitoring Stack

### Prometheus Configuration

```yaml
# deploy/prometheus/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: routerbot
    static_configs:
      - targets: ["routerbot:4000"]
    metrics_path: /metrics
    scrape_interval: 15s
```

### Key Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `routerbot_requests_total` | Counter | Total API requests by model, status |
| `routerbot_request_duration_seconds` | Histogram | Request latency by model, provider |
| `routerbot_tokens_total` | Counter | Tokens consumed by model, type |
| `routerbot_spend_usd_total` | Counter | Cumulative spend by model, team |
| `routerbot_provider_errors_total` | Counter | Provider errors by provider, error type |
| `routerbot_cache_hits_total` | Counter | Cache hits/misses |
| `routerbot_active_keys` | Gauge | Number of active virtual keys |
| `routerbot_rate_limit_hits_total` | Counter | Rate limit violations by key |

### Grafana Dashboards

Pre-built dashboards are provisioned automatically in `deploy/grafana/provisioning/`:

- **RouterBot Overview** — request rate, latency p50/p95/p99, error rate
- **Spend Analytics** — cost over time, by model, by team
- **Provider Health** — per-provider error rates and latency
- **Rate Limiting** — who's hitting limits and how often

---

## Security Hardening

### Secrets Management

Never put secrets in `docker-compose.yml` or `values.yaml`. Use:

```bash
# Docker: use .env file (gitignored) or Docker secrets
echo "MASTER_KEY=sk-prod-xxxxx" >> .env.production

# Kubernetes: use Secrets (or external secrets manager)
kubectl create secret generic routerbot-secrets --from-env-file=.env.production

# Recommended: Use external secrets manager
# - AWS Secrets Manager + External Secrets Operator
# - Vault + Vault Agent Injector
# - Azure Key Vault + CSI driver
```

### Network Policy (Kubernetes)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: routerbot-network-policy
spec:
  podSelector:
    matchLabels:
      app: routerbot
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              role: ingress-controller
      ports:
        - port: 4000
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: postgresql
      ports:
        - port: 5432
    - to:
        - podSelector:
            matchLabels:
              app: redis
      ports:
        - port: 6379
    - to: []   # Allow outbound to LLM providers (internet)
      ports:
        - port: 443
```

### TLS/SSL

All production deployments must use TLS:

```bash
# via cert-manager in Kubernetes
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# ClusterIssuer for Let's Encrypt
kubectl apply -f deploy/k8s/cluster-issuer.yaml
```

---

## Multi-Region Deployment

For global deployments with low latency:

1. Deploy RouterBot instances in multiple regions (us-east-1, eu-west-1, ap-southeast-1)
2. Use a global PostgreSQL (Neon, CockroachDB, or PlanetScale for MySQL variant) with regional read replicas
3. Use Redis Cluster or Redis Sentinel per-region for caching/rate-limiting
4. Route traffic with a global load balancer (Cloudflare, AWS Global Accelerator)
5. Set `REGION` env var per instance for metrics labeling

Rate limiting per-key must be enforced at the region level or via a central Redis — choose based on your consistency requirements.

---

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose logs routerbot

# Common causes:
# 1. DATABASE_URL not set or wrong format
# 2. PostgreSQL not ready yet (check startup order)
# 3. Migrations not run
docker compose exec routerbot uv run alembic upgrade head
```

### 500 errors on all requests

```bash
# Check database connection
docker compose exec routerbot python -c \
  "from routerbot.db.session import check_connection; import asyncio; asyncio.run(check_connection())"

# Check Redis connection
docker compose exec redis redis-cli ping
```

### High memory usage

```bash
# Check for connection leaks
docker compose exec routerbot python -c \
  "from routerbot.db.session import get_pool_status; print(get_pool_status())"

# Restart with clean state
docker compose restart routerbot
```

### Provider errors

```bash
# Test provider connectivity
curl http://localhost:4000/v1/provider/health

# Check API key validity
curl http://localhost:4000/v1/provider/test \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{"provider": "openai"}'
```

### Database migration failures

```bash
# Check current state
docker compose exec routerbot uv run alembic current

# Force to specific revision (DANGEROUS — use only if you know what you're doing)
docker compose exec routerbot uv run alembic stamp <revision>

# Check migration conflicts
docker compose exec routerbot uv run alembic branches
```
