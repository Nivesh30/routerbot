"""AI Hub & Playground routes — /v1/hub/*.

Minimal route surface over ``state.model_hub`` and ``state.playground``
(wired up with real provider handlers in ``proxy/app.py`` — see
``proxy/completion_helper.py``). Both are opt-in via ``hub.enabled: true``
in config; routes return 503 when not configured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from routerbot.hub.models import (  # noqa: TC001 - needed at runtime for FastAPI request/response models
    ComparisonRequest,
    ComparisonResponse,
    ModelInfo,
    PlaygroundRequest,
    PlaygroundResponse,
    PlaygroundSession,
)
from routerbot.hub.playground import PlaygroundCapacityError, PlaygroundSessionError

if TYPE_CHECKING:
    from routerbot.hub.model_hub import ModelHub
    from routerbot.hub.playground import Playground

router = APIRouter(prefix="/hub", tags=["AI Hub & Playground"])


class CreateSessionRequest(BaseModel):
    """Request body for ``POST /v1/hub/playground/sessions``."""

    model_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


def _get_model_hub(request: Request) -> ModelHub:
    state = getattr(request.app.state, "routerbot", None)
    hub: ModelHub | None = getattr(state, "model_hub", None) if state else None
    if hub is None:
        raise HTTPException(status_code=503, detail="AI Hub is not enabled (set hub.enabled: true in config).")
    return hub


def _get_playground(request: Request) -> Playground:
    state = getattr(request.app.state, "routerbot", None)
    pg: Playground | None = getattr(state, "playground", None) if state else None
    if pg is None:
        raise HTTPException(status_code=503, detail="Playground is not enabled (set hub.enabled: true in config).")
    return pg


@router.get("/models", summary="List models in the Hub catalogue")
async def list_hub_models(raw_request: Request) -> list[ModelInfo]:
    hub = _get_model_hub(raw_request)
    return hub.list_models()


@router.post("/compare", summary="Compare multiple models on the same prompt")
async def compare_models(body: ComparisonRequest, raw_request: Request) -> ComparisonResponse:
    hub = _get_model_hub(raw_request)
    return await hub.compare(body)


@router.post("/playground/sessions", summary="Create a playground session")
async def create_playground_session(body: CreateSessionRequest, raw_request: Request) -> PlaygroundSession:
    playground = _get_playground(raw_request)
    try:
        return playground.create_session(body.model_id, parameters=body.parameters)
    except PlaygroundCapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@router.get("/playground/sessions/{session_id}", summary="Get a playground session")
async def get_playground_session(session_id: str, raw_request: Request) -> PlaygroundSession:
    playground = _get_playground(raw_request)
    session = playground.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Playground session '{session_id}' not found.")
    return session


@router.post("/playground/messages", summary="Send a message in a playground session")
async def send_playground_message(body: PlaygroundRequest, raw_request: Request) -> PlaygroundResponse:
    playground = _get_playground(raw_request)
    try:
        return await playground.send_message(body)
    except PlaygroundSessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PlaygroundCapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
