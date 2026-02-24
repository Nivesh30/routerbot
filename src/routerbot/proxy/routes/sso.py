"""SSO login/callback/logout routes.

Endpoints:
    GET   /sso/login      — Redirect to IdP authorization URL
    GET   /sso/callback    — Handle IdP callback (code exchange)
    POST  /sso/logout      — Logout and invalidate session
    GET   /sso/providers   — List configured SSO providers
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sso", tags=["SSO"])


def _get_sso_manager(request: Request) -> Any:
    """Retrieve the SSOManager from app state."""
    state = getattr(request.app.state, "routerbot", None)
    mgr = getattr(state, "sso_manager", None) if state else None
    if mgr is None:
        raise HTTPException(status_code=503, detail="SSO is not configured")
    return mgr


def _get_session_manager(request: Request) -> Any:
    """Retrieve the SessionManager from app state."""
    state = getattr(request.app.state, "routerbot", None)
    mgr = getattr(state, "session_manager", None) if state else None
    if mgr is None:
        raise HTTPException(status_code=503, detail="Session management is not configured")
    return mgr


@router.get("/providers", summary="List configured SSO providers")
async def list_sso_providers(request: Request) -> JSONResponse:
    """Return the list of available SSO providers."""
    sso_mgr = _get_sso_manager(request)
    return JSONResponse(content={"providers": sso_mgr.list_providers()})


@router.get("/login", summary="Redirect to SSO provider")
async def sso_login(request: Request, provider: str) -> RedirectResponse:
    """Begin the SSO login flow by redirecting to the identity provider.

    Query Parameters
    ----------------
    provider : str
        Name of the SSO provider to use (must match a registered provider).
    """
    sso_mgr = _get_sso_manager(request)

    try:
        auth_url, _state = await sso_mgr.get_auth_url(provider)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/callback", summary="Handle SSO callback")
async def sso_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> JSONResponse:
    """Handle the IdP callback after user authenticates.

    The IdP redirects back here with ``code`` and ``state`` query parameters.
    """
    if error:
        raise HTTPException(status_code=400, detail=f"SSO error from provider: {error}")

    if not state or not code:
        raise HTTPException(status_code=400, detail="Missing 'state' or 'code' parameter")

    sso_mgr = _get_sso_manager(request)
    session_mgr = _get_session_manager(request)

    try:
        user_info = await sso_mgr.handle_callback(state=state, code=code)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    # Create a server-side session
    session_data = {
        "provider": user_info.provider_name,
        "provider_user_id": user_info.provider_user_id,
        "email": user_info.email,
        "name": user_info.name,
    }
    session_id, cookie = session_mgr.create_session(session_data)

    response = JSONResponse(
        content={
            "status": "authenticated",
            "email": user_info.email,
            "name": user_info.name,
            "provider": user_info.provider_name,
            "session_id": session_id,
        }
    )
    response.set_cookie(**cookie.as_dict())
    return response


@router.post("/logout", summary="Logout and invalidate session")
async def sso_logout(request: Request) -> JSONResponse:
    """Invalidate the current session and clear the session cookie."""
    session_mgr = _get_session_manager(request)

    # Get session ID from cookie
    session_id = request.cookies.get(session_mgr._config.cookie_name)
    if not session_id:
        return JSONResponse(content={"status": "no_session"})

    delete_cookie = session_mgr.delete_session(session_id)

    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie(**delete_cookie.as_dict())
    return response
