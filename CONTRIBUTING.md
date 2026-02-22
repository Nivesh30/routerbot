# Contributing to RouterBot

Thank you for your interest in contributing to RouterBot! Every contribution matters — from bug fixes to new features to documentation improvements.

## Code of Conduct

Be respectful. Be constructive. We're building open source software for everyone.

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) — Python package manager
- Docker & Docker Compose (for integration tests)
- Node.js 20+ and pnpm (for dashboard development only)

### Setup

```bash
git clone https://github.com/Nivesh30/routerbot.git
cd routerbot
make install-dev
make check  # Should pass — lint, types, tests
```

## Development Workflow

1. **Fork the repo** and create a feature branch:
   ```bash
   git checkout -b feat/your-feature
   ```

2. **Read the standards** before writing code:
   - [Coding Standards](docs/CODING_STANDARDS.md) — mandatory
   - [Architecture](docs/ARCHITECTURE.md) — module boundaries

3. **Make your changes** following the coding standards

4. **Run checks** before committing:
   ```bash
   make format    # Auto-format
   make check     # Lint + types + tests
   ```

5. **Commit** with conventional commit messages:
   ```
   feat(providers): add Mistral streaming support
   fix(auth): prevent timing attack on key comparison
   test(core): add edge cases for cost calculation
   ```

6. **Open a PR** against `master`

## Pull Request Requirements

- [ ] All existing tests still pass
- [ ] New code has tests (80%+ coverage)
- [ ] `make lint` passes
- [ ] `make type-check` passes
- [ ] PR description explains what changed and why
- [ ] Commit messages follow conventional format

## What to Work On

Check the [Implementation Plan](docs/IMPLEMENTATION_PLAN.md) and the [Stage Plans](docs/stages/) for current priorities. Issues labeled `good first issue` are great starting points.

## Module Boundaries

Before adding code, understand where it belongs:

| Module | Rule |
|--------|------|
| `core/` | Zero external deps (stdlib + pydantic only) |
| `providers/` | Depends on `core/` only |
| `router/` | Depends on `core/` + `providers/` only |
| `proxy/` | FastAPI lives here ONLY |
| `auth/` | Depends on `core/` + `db/` only |
| `db/` | Depends on `core/` only |
| `utils/` | Pure functions, zero business logic |

## Reporting Bugs

Use the [Bug Report template](https://github.com/Nivesh30/routerbot/issues/new?template=bug_report.md) and include:
- Steps to reproduce
- Expected behavior
- Actual behavior
- RouterBot version and environment

## Feature Requests

Use the [Feature Request template](https://github.com/Nivesh30/routerbot/issues/new?template=feature_request.md) and explain:
- The problem you're trying to solve
- Your proposed solution
- Alternatives you considered

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
