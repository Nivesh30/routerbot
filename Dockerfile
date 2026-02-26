# ──────────────────────────────────────────────────────────────────────────────
# Stage 1: Build the frontend dashboard
# ──────────────────────────────────────────────────────────────────────────────
FROM node:22-alpine AS frontend-builder

WORKDIR /app/ui/dashboard

# Enable pnpm via corepack (ships with Node 16.10+)
RUN corepack enable && corepack prepare pnpm@latest --activate

# Install dependencies first (layer-cached unless lockfile changes)
COPY ui/dashboard/package.json ui/dashboard/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy source and build
COPY ui/dashboard/ ./
RUN pnpm build

# ──────────────────────────────────────────────────────────────────────────────
# Stage 2: Production image
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS final

# System dependencies for Python packages (e.g. cryptography)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python dependencies (layer-cached unless pyproject.toml changes)
COPY pyproject.toml ./
RUN uv pip install --system --no-cache ".[all]" \
    # Install uvicorn + gunicorn for production serving
    && uv pip install --system --no-cache "uvicorn[standard]" "sqlalchemy[asyncio]" aiosqlite

# Copy application source
COPY src/ ./src/

# Copy built frontend from Stage 1
COPY --from=frontend-builder /app/ui/dashboard/dist ./ui/dashboard/dist

# Runtime configuration
ENV PYTHONUNBUFFERED=1
ENV ROUTERBOT_CONFIG=/config/routerbot_config.yaml

# Expose the API port
EXPOSE 8000

# Health check (polls /health every 30s)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Default startup command
# Override ROUTERBOT_CONFIG environment variable to point to your config file.
CMD ["uvicorn", "routerbot.proxy.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
