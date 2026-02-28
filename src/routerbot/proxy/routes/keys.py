"""Virtual API key management routes.

Endpoints for generating, updating, deleting, listing, and rotating
API keys.  All management endpoints require the master key in the
``Authorization: Bearer <master_key>`` header (or ``X-Master-Key``).

Endpoints:
    POST  /key/generate  — Generate a new API key
    POST  /key/update    — Update an existing key's settings
    POST  /key/delete    — Soft-delete (deactivate) a key
    GET   /key/info      — Get key details by key hash or key ID
    GET   /key/list      — List keys (optionally filtered by user/team)
    POST  /key/rotate    — Rotate a key (issue new, deactivate old)
"""

from __future__ import annotations

import logging
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002

from routerbot.auth.api_key import _build_key_info, generate_key, hash_key
from routerbot.db.repositories.keys import KeyRepository
from routerbot.db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/key", tags=["Key Management"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class KeyGenerateRequest(BaseModel):
    """Body for ``POST /key/generate``."""

    user_id: str | None = Field(default=None, description="Owner user ID (UUID)")
    team_id: str | None = Field(default=None, description="Owner team ID (UUID)")
    models: list[str] = Field(default_factory=list, description="Allowed model names (empty = all)")
    max_budget: float | None = Field(default=None, ge=0, description="Max spend in USD")
    rate_limit_rpm: int | None = Field(default=None, ge=1, description="Requests per minute limit")
    rate_limit_tpm: int | None = Field(default=None, ge=1, description="Tokens per minute limit")
    expires_at: str | None = Field(default=None, description="ISO-8601 expiration timestamp")
    permissions: dict[str, Any] = Field(default_factory=dict, description="Feature-flag permissions")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary key-value metadata")
    key_prefix: str = Field(default="rb", description="Key prefix (default: rb)")


class KeyUpdateRequest(BaseModel):
    """Body for ``POST /key/update``."""

    key: str | None = Field(default=None, description="Plaintext key (hashed for lookup)")
    key_id: str | None = Field(default=None, description="Key UUID (alternative to key)")
    models: list[str] | None = Field(default=None, description="Allowed models (null = no change)")
    max_budget: float | None = Field(default=None, ge=0, description="New budget limit")
    rate_limit_rpm: int | None = Field(default=None, ge=1)
    rate_limit_tpm: int | None = Field(default=None, ge=1)
    expires_at: str | None = Field(default=None, description="ISO-8601 expiration (null = no change)")
    permissions: dict[str, Any] | None = Field(default=None)
    metadata: dict[str, Any] | None = Field(default=None)


class KeyDeleteRequest(BaseModel):
    """Body for ``POST /key/delete``."""

    key: str | None = Field(default=None, description="Plaintext key")
    key_id: str | None = Field(default=None, description="Key UUID")


class KeyRotateRequest(BaseModel):
    """Body for ``POST /key/rotate``."""

    key: str | None = Field(default=None, description="Plaintext key to rotate out")
    key_id: str | None = Field(default=None, description="Key UUID to rotate out")
    key_prefix: str = Field(default="rb", description="Prefix for the new key")
    grace_period_seconds: int = Field(
        default=0,
        ge=0,
        description="Seconds the old key remains active after rotation (0 = immediate deactivation)",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_master_key(request: Request) -> None:
    """Assert that the caller provided a valid master key.

    Checks ``Authorization: Bearer <key>`` and ``X-Master-Key`` headers.
    Raises :class:`HTTPException` 401 when invalid.
    """
    state = getattr(request.app.state, "routerbot", None)
    master_key: str | None = None
    if state and state.config and state.config.general_settings:
        master_key = state.config.general_settings.master_key

    if not master_key:
        # No master key configured — allow unrestricted management
        return

    provided = request.headers.get("x-master-key") or request.headers.get("authorization", "").removeprefix("Bearer ")
    if not provided or provided != master_key:
        raise HTTPException(status_code=401, detail="Invalid or missing master key")


async def _resolve_key(
    repo: KeyRepository,
    *,
    key: str | None = None,
    key_id: str | None = None,
) -> Any:
    """Resolve a VirtualKey from either plaintext key or UUID.

    Returns the ORM entity or raises 404.
    """
    if key:
        found = await repo.get_by_hash(hash_key(key))
    elif key_id:
        found = await repo.get_by_id(_uuid.UUID(key_id))
    else:
        raise HTTPException(status_code=400, detail="Provide either 'key' or 'key_id'")

    if found is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return found


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/generate", summary="Generate a new API key")
async def key_generate(
    body: KeyGenerateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Generate a new virtual API key.

    The plaintext key is returned in the response body — this is the
    **only** time it will be visible.  Store it securely.
    """
    _require_master_key(request)

    plaintext, key_hash, display_prefix = generate_key(prefix=body.key_prefix)

    # Parse optional fields
    user_id = _uuid.UUID(body.user_id) if body.user_id else None
    team_id = _uuid.UUID(body.team_id) if body.team_id else None
    expires_at: datetime | None = None
    if body.expires_at:
        expires_at = datetime.fromisoformat(body.expires_at)

    repo = KeyRepository(session)
    vk = await repo.create(
        key_hash=key_hash,
        key_prefix=display_prefix,
        user_id=user_id,
        team_id=team_id,
        models=body.models,
        max_budget=body.max_budget,
        rate_limit_rpm=body.rate_limit_rpm,
        rate_limit_tpm=body.rate_limit_tpm,
        expires_at=expires_at,
        permissions=body.permissions,
        metadata_=body.metadata,
    )

    info = _build_key_info(vk)
    info["key"] = plaintext  # Only time plaintext is returned

    logger.info("Generated new API key %s for user=%s team=%s", display_prefix, user_id, team_id)

    return JSONResponse(content=info, status_code=201)


@router.post("/update", summary="Update key settings")
async def key_update(
    body: KeyUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Update an existing key's configuration.

    Only the fields provided (non-null) are updated.
    """
    _require_master_key(request)

    repo = KeyRepository(session)
    vk = await _resolve_key(repo, key=body.key, key_id=body.key_id)

    updates: dict[str, Any] = {}
    if body.models is not None:
        updates["models"] = body.models
    if body.max_budget is not None:
        updates["max_budget"] = body.max_budget
    if body.rate_limit_rpm is not None:
        updates["rate_limit_rpm"] = body.rate_limit_rpm
    if body.rate_limit_tpm is not None:
        updates["rate_limit_tpm"] = body.rate_limit_tpm
    if body.expires_at is not None:
        updates["expires_at"] = datetime.fromisoformat(body.expires_at)
    if body.permissions is not None:
        updates["permissions"] = body.permissions
    if body.metadata is not None:
        updates["metadata_"] = body.metadata

    if updates:
        vk = await repo.update(vk, **updates)

    logger.info("Updated key %s", vk.key_prefix)

    return JSONResponse(content=_build_key_info(vk))


@router.post("/delete", summary="Soft-delete (deactivate) a key")
async def key_delete(
    body: KeyDeleteRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Deactivate a key. The key record is preserved but can no longer authenticate."""
    _require_master_key(request)

    repo = KeyRepository(session)
    vk = await _resolve_key(repo, key=body.key, key_id=body.key_id)
    vk = await repo.deactivate(vk)

    logger.info("Deactivated key %s", vk.key_prefix)

    return JSONResponse(content={"status": "deactivated", **_build_key_info(vk)})


@router.get("/info", summary="Get key information")
async def key_info(
    request: Request,
    key: str | None = None,
    key_id: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Retrieve information about a specific key (by plaintext key or UUID)."""
    _require_master_key(request)

    repo = KeyRepository(session)
    vk = await _resolve_key(repo, key=key, key_id=key_id)

    return JSONResponse(content=_build_key_info(vk))


@router.get("/list", summary="List keys")
async def key_list(
    request: Request,
    user_id: str | None = None,
    team_id: str | None = None,
    active_only: bool = False,
    offset: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """List virtual API keys, optionally filtered by owner or status."""
    _require_master_key(request)

    repo = KeyRepository(session)

    if user_id:
        keys = await repo.list_by_user(_uuid.UUID(user_id), offset=offset, limit=limit)
    elif team_id:
        keys = await repo.list_by_team(_uuid.UUID(team_id), offset=offset, limit=limit)
    elif active_only:
        keys = await repo.list_active(offset=offset, limit=limit)
    else:
        keys = await repo.list_all(offset=offset, limit=limit)

    return JSONResponse(content={"keys": [_build_key_info(k) for k in keys], "count": len(keys)})


@router.post("/rotate", summary="Rotate an API key")
async def key_rotate(
    body: KeyRotateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Rotate a key by generating a new one and deactivating the old.

    If ``grace_period_seconds > 0`` the old key's expiration is set to
    *now + grace_period* instead of immediate deactivation, allowing a
    window where both keys work.
    """
    _require_master_key(request)

    repo = KeyRepository(session)
    old_key = await _resolve_key(repo, key=body.key, key_id=body.key_id)

    # Generate replacement key
    plaintext, new_hash, new_prefix = generate_key(prefix=body.key_prefix)

    new_key = await repo.create(
        key_hash=new_hash,
        key_prefix=new_prefix,
        user_id=old_key.user_id,
        team_id=old_key.team_id,
        models=old_key.models,
        max_budget=old_key.max_budget,
        rate_limit_rpm=old_key.rate_limit_rpm,
        rate_limit_tpm=old_key.rate_limit_tpm,
        expires_at=old_key.expires_at,
        permissions=old_key.permissions,
        metadata_=old_key.metadata_,
    )

    # Deactivate or set grace period on old key
    if body.grace_period_seconds > 0:
        from datetime import timedelta

        grace_expires = datetime.now(UTC) + timedelta(seconds=body.grace_period_seconds)
        await repo.update(old_key, expires_at=grace_expires)
    else:
        await repo.deactivate(old_key)

    new_info = _build_key_info(new_key)
    new_info["key"] = plaintext  # Only time new plaintext is shown

    logger.info("Rotated key %s → %s", old_key.key_prefix, new_prefix)

    return JSONResponse(
        content={
            "new_key": new_info,
            "old_key": _build_key_info(old_key),
            "grace_period_seconds": body.grace_period_seconds,
        },
        status_code=201,
    )
