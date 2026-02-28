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
import pathlib
import time
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

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
# Dashboard static assets path (present only when frontend has been built)
# ---------------------------------------------------------------------------

# Resolve: src/routerbot/proxy/app.py → project root → ui/dashboard/dist
_DASHBOARD_DIST = (pathlib.Path(__file__).parent.parent.parent.parent / "ui" / "dashboard" / "dist").resolve()

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
    # Dashboard static files (mounted last so API routes take priority)
    # -----------------------------------------------------------------
    _register_dashboard_static(app)

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

    # Initialise MCP gateway (if configured)
    if state.config and state.config.mcp_servers:
        from routerbot.core.mcp.models import MCPServerConfig
        from routerbot.core.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry()
        configs = [MCPServerConfig(**s) for s in state.config.mcp_servers]
        await registry.register_from_config(configs)
        await registry.start_health_checks()
        state.mcp_registry = registry
        logger.info("MCP gateway initialised with %d server(s)", len(registry))

    # Initialise A2A agent gateway (if configured)
    if state.config and getattr(state.config, "a2a_agents", None):
        from routerbot.core.a2a.models import A2AAgentConfig
        from routerbot.core.a2a.registry import A2AAgentRegistry

        a2a_registry = A2AAgentRegistry()
        a2a_configs = [A2AAgentConfig(**a) for a in state.config.a2a_agents]
        await a2a_registry.register_from_config(a2a_configs)
        await a2a_registry.start_health_checks()
        state.a2a_registry = a2a_registry
        logger.info("A2A agent gateway initialised with %d agent(s)", len(a2a_registry))

    # Initialise semantic routing (if configured)
    if state.config and getattr(state.config, "semantic_routing", None):
        from routerbot.core.semantic.classifier import SemanticRouter
        from routerbot.core.semantic.models import SemanticRoutingConfig

        sr_config = SemanticRoutingConfig(**state.config.semantic_routing)
        if sr_config.enabled:
            state.semantic_router = SemanticRouter(sr_config)
            logger.info(
                "Semantic routing enabled: %d intent rules, %d pattern rules, %d A/B tests",
                len(sr_config.rules),
                len(sr_config.pattern_rules),
                len(sr_config.ab_tests),
            )

    # Initialise request transformation pipeline (if configured)
    if state.config and getattr(state.config, "request_transform", None):
        from routerbot.core.transform.enricher import RequestEnricher
        from routerbot.core.transform.models import TransformConfig
        from routerbot.core.transform.pipeline import RequestTransformPipeline
        from routerbot.core.transform.postprocessor import ResponsePostProcessor
        from routerbot.core.transform.prompt_injector import PromptInjector

        tf_config = TransformConfig(**state.config.request_transform)
        if tf_config.enabled:
            pipeline = RequestTransformPipeline(tf_config)
            if tf_config.prompt_templates:
                pipeline.register(PromptInjector(tf_config.prompt_templates))
            if tf_config.enrichment_sources:
                pipeline.register(RequestEnricher(tf_config.enrichment_sources))
            if tf_config.post_processing_rules:
                pipeline.register(ResponsePostProcessor(tf_config.post_processing_rules))
            state.transform_pipeline = pipeline
            logger.info(
                "Request transform pipeline enabled: %d hooks",
                len(pipeline.hooks),
            )

    # Initialise auto-scaling recommendation engine (if configured)
    if state.config and getattr(state.config, "scaling", None):
        from routerbot.core.scaling.engine import RecommendationEngine
        from routerbot.core.scaling.models import ScalingConfig

        sc_config = ScalingConfig(**state.config.scaling)
        if sc_config.enabled:
            state.recommendation_engine = RecommendationEngine(sc_config)
            logger.info("Auto-scaling recommendation engine enabled")

    # Initialise plugin system (if configured)
    if state.config and getattr(state.config, "plugins", None):
        from routerbot.core.plugins.manager import PluginManager
        from routerbot.core.plugins.models import PluginConfig

        pl_config = PluginConfig(**state.config.plugins)
        if pl_config.enabled:
            mgr = PluginManager(pl_config)
            loaded = await mgr.load_all()
            state.plugin_manager = mgr
            logger.info("Plugin system enabled: %d plugins loaded", len(loaded))

    # Initialise resilience layer (if configured)
    if state.config and getattr(state.config, "resilience", None):
        from routerbot.core.resilience.bulkhead import BulkheadManager
        from routerbot.core.resilience.circuit_breaker import CircuitBreakerRegistry
        from routerbot.core.resilience.degradation import DegradationManager
        from routerbot.core.resilience.models import ResilienceConfig
        from routerbot.core.resilience.region import RegionRouter
        from routerbot.core.resilience.request_queue import RequestQueueManager

        res_config = ResilienceConfig(**state.config.resilience)
        if res_config.enabled:
            state.circuit_breaker_registry = CircuitBreakerRegistry(res_config.circuit_breaker)
            state.request_queue_manager = RequestQueueManager(res_config.request_queue)
            state.bulkhead_manager = BulkheadManager(
                res_config.bulkhead_defaults,
                res_config.bulkhead_overrides,
            )
            state.region_router = RegionRouter(res_config.region_routing)
            state.degradation_manager = DegradationManager()
            logger.info(
                "Resilience layer enabled: circuit-breaker, queue, bulkhead, regions=%d",
                len(res_config.region_routing.regions),
            )

    # Initialise advanced auth (if configured)
    if state.config and getattr(state.config, "advanced_auth", None):
        from routerbot.auth.advanced.key_scoping import KeyScopeValidator
        from routerbot.auth.advanced.models import AdvancedAuthConfig
        from routerbot.auth.advanced.mtls import MTLSAuthenticator
        from routerbot.auth.advanced.permissions import PermissionManager
        from routerbot.auth.advanced.token_exchange import TokenExchanger
        from routerbot.auth.advanced.webhook_auth import WebhookAuthenticator

        aa_config = AdvancedAuthConfig(**state.config.advanced_auth)

        if aa_config.mtls.enabled:
            state.mtls_authenticator = MTLSAuthenticator(aa_config.mtls)
            logger.info("mTLS authentication enabled")

        if aa_config.webhook_auth.enabled:
            wh = WebhookAuthenticator(aa_config.webhook_auth)
            await wh.setup()
            state.webhook_authenticator = wh
            logger.info("Webhook authentication enabled")

        if aa_config.token_exchange.enabled:
            te = TokenExchanger(aa_config.token_exchange)
            await te.setup()
            state.token_exchanger = te
            logger.info("Token exchange enabled with %d providers", len(te.list_providers()))

        if aa_config.key_scopes:
            state.key_scope_validator = KeyScopeValidator(aa_config.key_scopes)
            logger.info("Key scoping enabled with %d scopes", len(aa_config.key_scopes))

        if aa_config.permission_sets:
            state.permission_manager = PermissionManager(aa_config.permission_sets)
            logger.info("Fine-grained permissions enabled with %d sets", len(aa_config.permission_sets))

    # -- Batch processing & async job queue ----------------------------------
    from routerbot.core.batch.batch_manager import BatchManager
    from routerbot.core.batch.job_queue import JobQueue
    from routerbot.core.batch.models import BatchConfig
    from routerbot.core.batch.worker_pool import WorkerPool

    batch_raw = config.batch if hasattr(config, "batch") else {}
    batch_cfg = BatchConfig(**batch_raw) if batch_raw else BatchConfig()

    if batch_cfg.enabled:
        jq = JobQueue(config=batch_cfg.queue)
        bm = BatchManager(config=batch_cfg.queue)
        wp = WorkerPool(queue=jq, config=batch_cfg.queue)
        await wp.start()
        state.job_queue = jq  # type: ignore[attr-defined]
        state.batch_manager = bm  # type: ignore[attr-defined]
        state.worker_pool = wp  # type: ignore[attr-defined]
        logger.info(
            "Batch processing enabled (workers=%d, max_pending=%d)",
            batch_cfg.queue.worker_count,
            batch_cfg.queue.max_pending_jobs,
        )

    app.state.routerbot = state
    logger.info("RouterBot ready ✓")


async def _shutdown(app: FastAPI, state: AppState) -> None:
    """Clean up resources on application shutdown."""
    logger.info("RouterBot shutting down…")

    # Stop config watcher if running
    config_watcher = getattr(state, "config_watcher", None)
    if config_watcher is not None:
        await config_watcher.stop()

    # Shut down MCP registry
    mcp_registry = getattr(state, "mcp_registry", None)
    if mcp_registry is not None:
        await mcp_registry.shutdown()

    # Shut down A2A registry
    a2a_registry = getattr(state, "a2a_registry", None)
    if a2a_registry is not None:
        await a2a_registry.shutdown()

    # Shut down plugin manager
    plugin_manager = getattr(state, "plugin_manager", None)
    if plugin_manager is not None:
        await plugin_manager.shutdown()

    # Shut down worker pool
    worker_pool = getattr(state, "worker_pool", None)
    if worker_pool is not None:
        await worker_pool.stop()

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
    from routerbot.proxy.routes.a2a import router as a2a_router
    from routerbot.proxy.routes.audio import router as audio_router
    from routerbot.proxy.routes.audit import router as audit_router
    from routerbot.proxy.routes.auth import router as auth_router
    from routerbot.proxy.routes.batches import router as batches_router
    from routerbot.proxy.routes.completions import router as completions_router
    from routerbot.proxy.routes.config import router as config_router
    from routerbot.proxy.routes.dashboard import router as dashboard_router
    from routerbot.proxy.routes.embeddings import router as embeddings_router
    from routerbot.proxy.routes.health import router as health_router
    from routerbot.proxy.routes.images import router as images_router
    from routerbot.proxy.routes.keys import router as keys_router
    from routerbot.proxy.routes.mcp import router as mcp_router
    from routerbot.proxy.routes.metrics import router as metrics_router
    from routerbot.proxy.routes.model_management import router as model_mgmt_router
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

    # Model management routes (admin CRUD)
    app.include_router(model_mgmt_router)

    # SSO routes
    app.include_router(sso_router)

    # Team management routes
    app.include_router(teams_router)

    # User management routes
    app.include_router(users_router)

    # Spend tracking routes
    app.include_router(spend_router)

    # Dashboard stats
    app.include_router(dashboard_router)

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
    app.include_router(mcp_router, prefix="/v1")
    app.include_router(a2a_router, prefix="/v1")

    # Register an OpenAI-compatible models fallback at root too
    @app.get("/", include_in_schema=False, response_model=None)
    async def root() -> JSONResponse | RedirectResponse:
        if _DASHBOARD_DIST.exists():
            return RedirectResponse(url="/ui/")
        return JSONResponse(
            content={
                "name": "RouterBot",
                "version": "0.1.0",
                "description": "Open Source LLM Gateway",
                "status": "running",
            }
        )


# ---------------------------------------------------------------------------
# Dashboard static file serving
# ---------------------------------------------------------------------------


def _register_dashboard_static(app: FastAPI) -> None:
    """Mount the built dashboard at ``/ui/`` (production only).

    Uses a hybrid approach:
    - ``/ui/assets/`` is served directly via StaticFiles (for caching headers)
    - All other ``/ui/*`` paths serve ``index.html`` for React Router (SPA routing)
    """
    if not _DASHBOARD_DIST.exists():
        logger.debug(
            "Dashboard dist not found at %s; skipping static file serving",
            _DASHBOARD_DIST,
        )
        return

    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles

    assets_dir = _DASHBOARD_DIST / "assets"
    index_path = _DASHBOARD_DIST / "index.html"

    if not index_path.exists():
        logger.warning("Dashboard index.html not found at %s", index_path)
        return

    # Mount /ui/assets/ for optimised static file delivery (JS/CSS chunks)
    if assets_dir.exists():
        app.mount("/ui/assets", StaticFiles(directory=str(assets_dir)), name="vite-assets")

    # Serve individual root-level files (favicon, manifest, robots, etc.)
    @app.get("/ui/{filename}", include_in_schema=False)
    async def ui_root_file(filename: str) -> FileResponse | HTMLResponse:
        file_path = _DASHBOARD_DIST / filename
        if file_path.is_file():
            return FileResponse(str(file_path))
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))

    # Catch-all SPA handler: /ui/ and /ui/<any nested path>
    @app.get("/ui/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> HTMLResponse:
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))

    # Redirect /ui (no trailing slash) → /ui/
    @app.get("/ui", include_in_schema=False)
    async def ui_redirect() -> FileResponse | HTMLResponse:
        from fastapi.responses import RedirectResponse as _RedirectResponse

        return _RedirectResponse(url="/ui/")  # type: ignore[return-value]

    logger.info("Dashboard UI serving at /ui (dist: %s)", _DASHBOARD_DIST)


# ---------------------------------------------------------------------------
# Default app instance (for development only — use create_app() in production)
# ---------------------------------------------------------------------------

app = create_app()
