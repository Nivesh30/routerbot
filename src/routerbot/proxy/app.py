"""FastAPI application factory for RouterBot.

Usage::

    from routerbot.proxy.app import create_app

    app = create_app()  # uses default config
    # or
    app = create_app(config=my_config)

The application is intentionally kept thin here — routes, middleware,
and the router layer are registered in separate modules.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from routerbot.core.exceptions import (
    AuthenticationError,
    BadRequestError,
    ModelNotFoundError,
    ProviderError,
    RateLimitError,
    RouterBotError,
    ServiceUnavailableError,
)
from routerbot.proxy.error_handlers import (
    authentication_error_handler,
    bad_request_handler,
    model_not_found_handler,
    provider_error_handler,
    rate_limit_error_handler,
    routerbot_error_handler,
    service_unavailable_handler,
    unhandled_exception_handler,
)
from routerbot.proxy.state import AppState

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from routerbot.core.config_models import RouterBotConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(config: RouterBotConfig | None = None) -> FastAPI:
    """Create and configure the RouterBot FastAPI application.

    Parameters
    ----------
    config:
        Optional pre-loaded :class:`~routerbot.core.config_models.RouterBotConfig`.
        If not provided, the app will attempt to load from the config file
        at startup (via the ``ROUTERBOT_CONFIG`` environment variable or
        a default path).

    Returns
    -------
    FastAPI
        The configured FastAPI application.
    """
    state = AppState()
    if config is not None:
        state.config = config

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Manage application startup and shutdown."""
        await _startup(app, state, config)
        yield
        await _shutdown(app, state)

    app = FastAPI(
        title="RouterBot",
        description="Open Source LLM Gateway — unified OpenAI-compatible API for 100+ models.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Store state on the app
    app.state.routerbot = state

    # -----------------------------------------------------------------
    # Middleware stack (outermost first ← LIFO registration order)
    # -----------------------------------------------------------------

    # CORS
    cors_origins = ["*"]
    cors_credentials = True
    if config and config.general_settings:
        cors_origins = config.general_settings.cors_allow_origins
        cors_credentials = config.general_settings.cors_allow_credentials

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Robots.txt (before request logging so crawl probes are handled early)
    block_robots = False
    if config and config.general_settings:
        block_robots = config.general_settings.block_robots

    from routerbot.proxy.middleware.robots import RobotsTxtMiddleware

    app.add_middleware(RobotsTxtMiddleware, enabled=block_robots)

    # Request body size limit
    max_mb = 100.0
    if config and config.general_settings:
        max_mb = config.general_settings.max_request_size_mb

    from routerbot.proxy.middleware.size_limit import RequestSizeLimitMiddleware

    app.add_middleware(RequestSizeLimitMiddleware, max_request_body_mb=max_mb)

    # Structured request logging
    from routerbot.proxy.middleware.logging_mw import RequestLoggingMiddleware

    app.add_middleware(RequestLoggingMiddleware)

    # IP-based access control (before auth — reject early)
    allowed_ips: list[str] = []
    blocked_ips: list[str] = []
    trust_proxy_headers = False
    if config and config.general_settings:
        allowed_ips = config.general_settings.allowed_ips
        blocked_ips = config.general_settings.blocked_ips
        trust_proxy_headers = config.general_settings.trust_proxy_headers

    from routerbot.proxy.middleware.ip_filter import IPFilterMiddleware

    app.add_middleware(
        IPFilterMiddleware,
        allowed_ips=allowed_ips,
        blocked_ips=blocked_ips,
        trust_proxy_headers=trust_proxy_headers,
    )

    # Authentication (resolves AuthContext from Bearer tokens / SSO cookies)
    from routerbot.proxy.middleware.auth import AuthMiddleware

    app.add_middleware(AuthMiddleware)

    # Request ID + response time (innermost — runs first on request, last on response)
    @app.middleware("http")
    async def add_request_id(request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex[:16]}"
        request.state.request_id = request_id
        start_time = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
        return response

    # -----------------------------------------------------------------
    # Exception handlers (registered most-specific first)
    # -----------------------------------------------------------------
    app.add_exception_handler(ModelNotFoundError, model_not_found_handler)  # type: ignore[arg-type]
    app.add_exception_handler(AuthenticationError, authentication_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RateLimitError, rate_limit_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(BadRequestError, bad_request_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ServiceUnavailableError, service_unavailable_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ProviderError, provider_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RouterBotError, routerbot_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # -----------------------------------------------------------------
    # Routes
    # -----------------------------------------------------------------
    _register_routes(app)

    # -----------------------------------------------------------------
    # OpenAPI customization
    # -----------------------------------------------------------------
    from routerbot.proxy.openapi import configure_openapi

    configure_openapi(app)

    return app


# ---------------------------------------------------------------------------
# Startup / Shutdown hooks
# ---------------------------------------------------------------------------


async def _startup(app: FastAPI, state: AppState, config: RouterBotConfig | None) -> None:
    """Initialize providers, DB, and Redis on application startup."""
    logger.info("RouterBot starting up…")

    if config is None and state.config is None:
        # Attempt to load config from standard locations
        try:
            from routerbot.core.config import load_config

            loaded = load_config()
            state.config = loaded
            logger.info("Loaded config from default location")
        except Exception as exc:
            logger.warning("Could not load config file: %s — running with defaults", exc)
            from routerbot.core.config_models import RouterBotConfig

            state.config = RouterBotConfig()

    # Initialise the router layer
    from routerbot.router.router import Router

    state.router = Router(config=state.config)
    logger.info("Router initialised with %d model(s)", len(state.router.list_models()))

    app.state.routerbot = state
    logger.info("RouterBot ready ✓")


async def _shutdown(app: FastAPI, state: AppState) -> None:
    """Clean up resources on application shutdown."""
    logger.info("RouterBot shutting down…")

    # Stop config watcher if running
    config_watcher = getattr(state, "config_watcher", None)
    if config_watcher is not None:
        await config_watcher.stop()

    # Close any open Redis connections
    if state.redis is not None:
        import contextlib

        with contextlib.suppress(Exception):
            await state.redis.aclose()

    logger.info("RouterBot shutdown complete ✓")


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def _register_routes(app: FastAPI) -> None:
    """Register all route modules on the application."""
    from routerbot.proxy.routes.audio import router as audio_router
    from routerbot.proxy.routes.audit import router as audit_router
    from routerbot.proxy.routes.auth import router as auth_router
    from routerbot.proxy.routes.batches import router as batches_router
    from routerbot.proxy.routes.completions import router as completions_router
    from routerbot.proxy.routes.config import router as config_router
    from routerbot.proxy.routes.embeddings import router as embeddings_router
    from routerbot.proxy.routes.health import router as health_router
    from routerbot.proxy.routes.images import router as images_router
    from routerbot.proxy.routes.keys import router as keys_router
    from routerbot.proxy.routes.metrics import router as metrics_router
    from routerbot.proxy.routes.models import router as models_router
    from routerbot.proxy.routes.rerank import router as rerank_router
    from routerbot.proxy.routes.spend import router as spend_router
    from routerbot.proxy.routes.sso import router as sso_router
    from routerbot.proxy.routes.teams import router as teams_router
    from routerbot.proxy.routes.users import router as users_router

    # Health routes (no prefix — /health, /health/liveness, /health/readiness)
    app.include_router(health_router)

    # Auth routes (login, me)
    app.include_router(auth_router)

    # Config management routes
    app.include_router(config_router)

    # Key management routes
    app.include_router(keys_router)

    # SSO routes
    app.include_router(sso_router)

    # Team management routes
    app.include_router(teams_router)

    # User management routes
    app.include_router(users_router)

    # Spend tracking routes
    app.include_router(spend_router)

    # Audit logging routes
    app.include_router(audit_router)

    # Prometheus metrics endpoint
    app.include_router(metrics_router)

    # All v1 API routes
    app.include_router(completions_router, prefix="/v1")
    app.include_router(embeddings_router, prefix="/v1")
    app.include_router(images_router, prefix="/v1")
    app.include_router(audio_router, prefix="/v1")
    app.include_router(rerank_router, prefix="/v1")
    app.include_router(batches_router, prefix="/v1")
    app.include_router(models_router, prefix="/v1")

    # Register an OpenAI-compatible models fallback at root too
    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse(
            content={
                "name": "RouterBot",
                "version": "0.1.0",
                "description": "Open Source LLM Gateway",
                "status": "running",
            }
        )


# ---------------------------------------------------------------------------
# Default app instance (for development only — use create_app() in production)
# ---------------------------------------------------------------------------

app = create_app()
