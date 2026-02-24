"""Configuration management routes.

Exposes admin-only endpoints for configuration inspection and hot-reload.

Endpoints:
    GET   /config           — Return current config hash and summary
    POST  /config/reload    — Trigger immediate config reload (admin only)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from routerbot.proxy.config_reload import compute_config_hash

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Config"])


@router.get("/config", summary="Get current config summary")
async def get_config_summary(request: Request) -> JSONResponse:
    """Return a summary of the currently loaded configuration.

    Returns the config hash, model count, routing strategy, and
    general settings — but **not** raw API keys.
    """
    state = getattr(request.app.state, "routerbot", None)
    if state is None or state.config is None:
        raise HTTPException(status_code=503, detail="Configuration not loaded")

    cfg = state.config
    config_hash = compute_config_hash(cfg)

    return JSONResponse(
        content={
            "config_hash": config_hash,
            "model_count": len(cfg.model_list),
            "models": [entry.model_name for entry in cfg.model_list],
            "routing_strategy": cfg.router_settings.routing_strategy,
            "num_retries": cfg.router_settings.num_retries,
            "fallbacks": cfg.router_settings.fallbacks,
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
