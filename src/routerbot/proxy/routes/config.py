"""Configuration management routes.

Exposes admin-only endpoints for configuration inspection, hot-reload, and update.

Endpoints:
    GET   /config           — Return current config hash and summary
    POST  /config/reload    — Trigger immediate config reload (admin only)
    POST  /config/update    — Update general/router settings and persist to YAML
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from routerbot.proxy.config_reload import compute_config_hash

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Config"])


@router.get("/config", summary="Get current config summary")
async def get_config_summary(request: Request) -> JSONResponse:
    """Return a summary of the currently loaded configuration.

    Returns the config hash, model count, and all editable general/router/cache
    settings — but **not** secrets (master_key, database_url, API keys).
    """
    state = getattr(request.app.state, "routerbot", None)
    if state is None or state.config is None:
        raise HTTPException(status_code=503, detail="Configuration not loaded")

    cfg = state.config
    config_hash = compute_config_hash(cfg)

    gs = cfg.general_settings
    rs = cfg.router_settings
    rbs = cfg.routerbot_settings

    return JSONResponse(
        content={
            "config_hash": config_hash,
            "model_count": len(cfg.model_list),
            "models": [entry.model_name for entry in cfg.model_list],
            # General settings (non-sensitive)
            "log_level": gs.log_level,
            "request_timeout": gs.request_timeout,
            "max_request_size_mb": gs.max_request_size_mb,
            "max_response_size_mb": gs.max_response_size_mb,
            "cors_allow_origins": gs.cors_allow_origins,
            "block_robots": gs.block_robots,
            # Router settings
            "routing_strategy": rs.routing_strategy,
            "num_retries": rs.num_retries,
            "retry_delay": rs.retry_delay,
            "timeout": rs.timeout,
            "cooldown_time": rs.cooldown_time,
            "allowed_fails": rs.allowed_fails,
            "fallbacks": rs.fallbacks,
            "enable_health_check": rs.enable_health_check,
            "health_check_interval": rs.health_check_interval,
            # Cache settings
            "cache_enabled": rbs.cache,
            "cache_type": rbs.cache_params.type if rbs.cache_params else "none",
            "cache_ttl": rbs.cache_params.ttl if rbs.cache_params else 3600,
        }
    )


@router.post("/config/reload", summary="Trigger config hot-reload")
async def reload_config(request: Request) -> JSONResponse:
    """Reload the configuration from disk without restarting the server.

    This endpoint is admin-only (requires the ``X-Master-Key`` header to
    match the configured ``general_settings.master_key``).  When no
    master key is configured, any caller can trigger a reload.
    """
    state = getattr(request.app.state, "routerbot", None)
    if state is None:
        raise HTTPException(status_code=503, detail="Application state not available")

    # Check master key if configured
    master_key = None
    if state.config and state.config.general_settings:
        master_key = state.config.general_settings.master_key

    if master_key:
        provided = request.headers.get("x-master-key") or request.headers.get("authorization", "").removeprefix(
            "Bearer "
        )
        if not provided or provided != master_key:
            raise HTTPException(status_code=401, detail="Invalid or missing master key")

    # Check if we have a config watcher available
    config_watcher = getattr(state, "config_watcher", None)
    if config_watcher is None:
        # Perform a one-shot reload directly
        try:
            import os
            from pathlib import Path

            from routerbot.core.config import load_config

            config_path_env = os.environ.get("ROUTERBOT_CONFIG", "routerbot_config.yaml")
            new_config = load_config(Path(config_path_env))
        except Exception as exc:
            logger.error("Config reload failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Config reload failed: {exc}") from exc

        # Apply to state
        old_hash = compute_config_hash(state.config) if state.config else "none"
        state.config = new_config
        new_hash = compute_config_hash(new_config)

        return JSONResponse(
            content={
                "status": "reloaded",
                "old_hash": old_hash,
                "new_hash": new_hash,
                "model_count": len(new_config.model_list),
            }
        )

    # Use the watcher's reload_now()
    try:
        old_hash = compute_config_hash(state.config) if state.config else "none"
        new_config = await config_watcher.reload_now()
        new_hash = compute_config_hash(new_config)
    except Exception as exc:
        logger.error("Config reload via watcher failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Config reload failed: {exc}") from exc

    return JSONResponse(
        content={
            "status": "reloaded",
            "old_hash": old_hash,
            "new_hash": new_hash,
            "model_count": len(new_config.model_list),
        }
    )


# ---------------------------------------------------------------------------
# Config update
# ---------------------------------------------------------------------------


class GeneralSettingsUpdate(BaseModel):
    """Partial update model for general settings."""

    log_level: str | None = None
    request_timeout: int | None = None
    max_request_size_mb: float | None = None
    max_response_size_mb: float | None = None
    cors_allow_origins: list[str] | None = None
    block_robots: bool | None = None


class RouterSettingsUpdate(BaseModel):
    """Partial update model for router settings."""

    routing_strategy: str | None = None
    num_retries: int | None = None
    retry_delay: float | None = None
    timeout: int | None = None
    cooldown_time: int | None = None
    allowed_fails: int | None = None
    enable_health_check: bool | None = None
    health_check_interval: int | None = None
    fallbacks: dict[str, list[str]] | None = None


class CacheSettingsUpdate(BaseModel):
    """Partial update model for cache settings."""

    enabled: bool | None = None
    type: str | None = None
    ttl: int | None = None


class ConfigUpdateRequest(BaseModel):
    """Request body for ``POST /config/update``."""

    general_settings: GeneralSettingsUpdate | None = None
    router_settings: RouterSettingsUpdate | None = None
    cache_settings: CacheSettingsUpdate | None = None


def _check_master_key(request: Request, state: object) -> None:
    """Raise 401 if the request doesn't carry a valid master key."""
    config = getattr(state, "config", None)
    master_key = None
    if config and config.general_settings:
        master_key = config.general_settings.master_key
    if master_key:
        provided = request.headers.get("x-master-key") or request.headers.get("authorization", "").removeprefix(
            "Bearer "
        )
        if not provided or provided != master_key:
            raise HTTPException(status_code=401, detail="Invalid or missing master key")


@router.post("/config/update", summary="Update settings and persist to YAML")
async def update_config(body: ConfigUpdateRequest, request: Request) -> JSONResponse:
    """Update general and/or router settings at runtime, then persist to the YAML file.

    Only fields present in the request body are updated (partial merge).
    Requires a valid master key.
    """
    state = getattr(request.app.state, "routerbot", None)
    if state is None or state.config is None:
        raise HTTPException(status_code=503, detail="Configuration not loaded")

    _check_master_key(request, state)

    import os

    import anyio
    import yaml

    cfg = state.config
    old_hash = compute_config_hash(cfg)

    # Apply changes to live config objects
    if body.general_settings:
        for field, value in body.general_settings.model_dump(exclude_none=True).items():
            setattr(cfg.general_settings, field, value)

    if body.router_settings:
        for field, value in body.router_settings.model_dump(exclude_none=True).items():
            setattr(cfg.router_settings, field, value)

    if body.cache_settings:
        cache_data = body.cache_settings.model_dump(exclude_none=True)
        if "enabled" in cache_data:
            cfg.routerbot_settings.cache = cache_data.pop("enabled")
        for field, value in cache_data.items():
            setattr(cfg.routerbot_settings.cache_params, field, value)

    # Persist to YAML file
    config_path = anyio.Path(os.environ.get("ROUTERBOT_CONFIG", "routerbot_config.yaml"))
    try:
        # Read existing YAML to preserve structure (comments are lost by re-serialization)
        raw: dict[str, Any] = {}
        if await config_path.exists():
            raw = yaml.safe_load(await config_path.read_text(encoding="utf-8")) or {}

        if body.general_settings:
            gs = raw.setdefault("general_settings", {})
            gs.update(body.general_settings.model_dump(exclude_none=True))

        if body.router_settings:
            rs = raw.setdefault("router_settings", {})
            rs.update(body.router_settings.model_dump(exclude_none=True))

        if body.cache_settings:
            rbs = raw.setdefault("routerbot_settings", {})
            cache_data = body.cache_settings.model_dump(exclude_none=True)
            if "enabled" in cache_data:
                rbs["cache"] = cache_data.pop("enabled")
            if cache_data:
                cp = rbs.setdefault("cache_params", {})
                cp.update(cache_data)

        await config_path.write_text(yaml.safe_dump(raw, default_flow_style=False, sort_keys=False), encoding="utf-8")
        logger.info("Config persisted to %s", config_path)
    except Exception as exc:
        logger.error("Failed to persist config: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Settings applied to live config but failed to persist: {exc}",
        ) from exc

    new_hash = compute_config_hash(cfg)

    return JSONResponse(
        content={
            "status": "updated",
            "old_hash": old_hash,
            "new_hash": new_hash,
            "general_settings": cfg.general_settings.model_dump(),
            "router_settings": cfg.router_settings.model_dump(),
        }
    )
