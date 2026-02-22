.PHONY: install-dev format lint type-check test-unit test-integration test-all run build clean check help

# Default target
.DEFAULT_GOAL := help

# ─── Installation ──────────────────────────────────────────
install-dev: ## Install all dependencies (dev + proxy)
	uv sync --all-extras
	@echo "✅ Development environment ready"

install: ## Install production dependencies only
	uv sync
	@echo "✅ Production environment ready"

# ─── Code Quality ──────────────────────────────────────────
format: ## Format code with Ruff
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/
	@echo "✅ Code formatted"

lint: ## Lint code with Ruff
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/
	@echo "✅ Lint passed"

type-check: ## Run MyPy type checking
	uv run mypy src/routerbot/
	@echo "✅ Type check passed"

# ─── Testing ───────────────────────────────────────────────
test-unit: ## Run unit tests
	uv run pytest tests/unit/ -v --cov=routerbot --cov-report=term-missing -m "not integration and not slow"

test-integration: ## Run integration tests (requires Docker services)
	uv run pytest tests/integration/ -v --cov=routerbot --cov-report=term-missing -m "integration"

test-all: ## Run all tests
	uv run pytest tests/ -v --cov=routerbot --cov-report=term-missing --cov-report=html

# ─── Run ───────────────────────────────────────────────────
run: ## Start the RouterBot proxy server
	uv run uvicorn routerbot.proxy.main:app --host 0.0.0.0 --port 4000 --reload

# ─── Build ─────────────────────────────────────────────────
build: ## Build Python package
	uv build
	@echo "✅ Package built"

# ─── Database ──────────────────────────────────────────────
db-migrate: ## Run database migrations
	uv run alembic upgrade head
	@echo "✅ Migrations applied"

db-revision: ## Create a new migration (usage: make db-revision MSG="description")
	uv run alembic revision --autogenerate -m "$(MSG)"

db-downgrade: ## Rollback one migration
	uv run alembic downgrade -1

# ─── Docker ────────────────────────────────────────────────
docker-up: ## Start all Docker services
	docker compose up -d
	@echo "✅ Services started"

docker-down: ## Stop all Docker services
	docker compose down
	@echo "✅ Services stopped"

docker-build: ## Build the RouterBot Docker image
	docker build --target production -t routerbot:latest .

# ─── Utilities ─────────────────────────────────────────────
clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov/ .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleaned"

check: lint type-check test-unit ## Run all checks (lint + types + tests)
	@echo "✅ All checks passed"

# ─── Help ──────────────────────────────────────────────────
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
