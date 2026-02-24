"""Custom OpenAPI schema generation for RouterBot.

Provides:
- Custom ``/openapi.json`` schema with RouterBot branding
- Helper to configure FastAPI's Swagger UI and ReDoc
- Environment-variable-driven title / description overrides

Usage::

    from routerbot.proxy.openapi import configure_openapi

    configure_openapi(app)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

_DEFAULT_TITLE = "RouterBot"
_DEFAULT_DESCRIPTION = """
## RouterBot — Open Source LLM Gateway

Unified **OpenAI-compatible** API for 100+ language models.

### Features

- **Provider-agnostic** — OpenAI, Anthropic, Google Gemini, AWS Bedrock, Azure, and more
- **Intelligent routing** — round-robin, latency-based, cost-based, weighted strategies
- **Resilience** — automatic retry, fallback chains, cooldown management
- **Observability** — structured logging, request tracing via `X-Request-ID`

### Authentication

Pass your key via the `Authorization` header:

```
Authorization: Bearer $ROUTERBOT_MASTER_KEY
```

### Quick-start

```bash
curl http://localhost:4000/v1/chat/completions \\
  -H 'Authorization: Bearer sk-your-key' \\
  -H 'Content-Type: application/json' \\
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello!"}]}'
```
"""

_DEFAULT_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_openapi(app: FastAPI) -> None:
    """Attach a custom ``openapi()`` method to *app*.

    Environment variable overrides:
    - ``ROUTERBOT_API_TITLE`` — Swagger UI title
    - ``ROUTERBOT_API_DESCRIPTION`` — Swagger UI description
    - ``ROUTERBOT_API_VERSION`` — API version string

    Parameters
    ----------
    app:
        The FastAPI application to configure.
    """
    title = os.environ.get("ROUTERBOT_API_TITLE", _DEFAULT_TITLE)
    description = os.environ.get("ROUTERBOT_API_DESCRIPTION", _DEFAULT_DESCRIPTION).strip()
    version = os.environ.get("ROUTERBOT_API_VERSION", _DEFAULT_VERSION)

    # Update the app metadata used by FastAPI for schema generation
    app.title = title
    app.description = description
    app.version = version

    # Patch the openapi() method to inject extra fields
    original_openapi = app.openapi

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = original_openapi()

        # Inject contact and license info
        schema.setdefault("info", {}).update(
            {
                "contact": {
                    "name": "RouterBot",
                    "url": "https://github.com/Nivesh30/routerbot",
                },
                "license": {
                    "name": "MIT",
                    "url": "https://opensource.org/licenses/MIT",
                },
            }
        )

        # Add servers block
        schema["servers"] = [
            {"url": "/", "description": "Current server"},
        ]

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
