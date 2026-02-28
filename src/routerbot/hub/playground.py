"""Interactive playground for testing models.

Manages playground sessions with conversation history, parameter tuning,
cost tracking, and optional sharing.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from routerbot.hub.models import (
    HubConfig,
    PlaygroundMessage,
    PlaygroundRequest,
    PlaygroundResponse,
    PlaygroundSession,
    PlaygroundStatus,
)

logger = logging.getLogger(__name__)


class Playground:
    """Interactive model testing playground.

    Parameters
    ----------
    handler:
        Async callable ``(model, messages, params) -> (response_text,
        input_tokens, output_tokens)`` for inference.
    config:
        Hub configuration.
    """

    def __init__(self, handler: Any = None, config: HubConfig | None = None) -> None:
        self._handler = handler or _default_handler
        self.config = config or HubConfig()
        self._sessions: dict[str, PlaygroundSession] = {}

    def create_session(
        self,
        model_id: str,
        *,
        parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PlaygroundSession:
        """Create a new playground session."""
        if len(self._sessions) >= self.config.max_playground_sessions:
            raise PlaygroundCapacityError(f"Max sessions reached: {self.config.max_playground_sessions}")

        session_id = f"pg_{uuid.uuid4().hex[:12]}"
        now = datetime.now(tz=UTC)

        session = PlaygroundSession(
            session_id=session_id,
            model_id=model_id,
            parameters=parameters or {},
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        self._sessions[session_id] = session
        logger.info("Playground session %s created (model=%s)", session_id, model_id)
        return session

    async def send_message(self, request: PlaygroundRequest) -> PlaygroundResponse:
        """Send a message in a playground session.

        If ``request.session_id`` is empty, a new session is created.
        """
        session = self._sessions.get(request.session_id)
        if session is None:
            session = self.create_session(
                request.model_id or "default",
                parameters=request.parameters,
            )

        if session.status != PlaygroundStatus.ACTIVE:
            raise PlaygroundSessionError(f"Session {session.session_id} is {session.status}")

        model_id = request.model_id or session.model_id

        # Add user message
        user_msg = PlaygroundMessage(role="user", content=request.message)
        session.messages.append(user_msg)

        # Build message list for the handler
        msgs = [{"role": m.role, "content": m.content} for m in session.messages]
        params = {**session.parameters, **request.parameters}

        start = time.monotonic()
        try:
            response_text, in_tok, out_tok = await self._handler(model_id, msgs, params)
        except Exception as exc:
            session.status = PlaygroundStatus.FAILED
            raise PlaygroundSessionError(f"Inference failed: {exc}") from exc

        latency = (time.monotonic() - start) * 1000

        # Add assistant message
        assistant_msg = PlaygroundMessage(
            role="assistant",
            content=response_text,
            model_id=model_id,
            tokens=out_tok,
            latency_ms=latency,
        )
        session.messages.append(assistant_msg)

        session.total_tokens += in_tok + out_tok
        session.updated_at = datetime.now(tz=UTC)

        return PlaygroundResponse(
            session_id=session.session_id,
            response=response_text,
            model_id=model_id,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency,
        )

    def get_session(self, session_id: str) -> PlaygroundSession | None:
        """Retrieve a session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(
        self,
        *,
        status: PlaygroundStatus | None = None,
        limit: int = 100,
    ) -> list[PlaygroundSession]:
        """List sessions, optionally filtered by status."""
        sessions = list(self._sessions.values())
        if status:
            sessions = [s for s in sessions if s.status == status]
        sessions.sort(
            key=lambda s: s.updated_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return sessions[:limit]

    def close_session(self, session_id: str) -> bool:
        """Close (complete) a playground session."""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if session.status != PlaygroundStatus.ACTIVE:
            return False
        session.status = PlaygroundStatus.COMPLETED
        session.updated_at = datetime.now(tz=UTC)
        return True

    def delete_session(self, session_id: str) -> bool:
        """Delete a session entirely."""
        return self._sessions.pop(session_id, None) is not None

    def stats(self) -> dict[str, Any]:
        """Return playground statistics."""
        counts: dict[str, int] = {s.value: 0 for s in PlaygroundStatus}
        total_tokens = 0
        for s in self._sessions.values():
            counts[s.status.value] += 1
            total_tokens += s.total_tokens
        return {
            "sessions": counts,
            "total_sessions": len(self._sessions),
            "total_tokens": total_tokens,
        }


async def _default_handler(
    model_id: str, messages: list[dict[str, Any]], parameters: dict[str, Any]
) -> tuple[str, int, int]:
    """Default stub handler."""
    content = messages[-1].get("content", "") if messages else ""
    return f"[{model_id}] Echo: {content[:200]}", len(content) // 4, 30


class PlaygroundCapacityError(Exception):
    """Raised when playground sessions have reached capacity."""


class PlaygroundSessionError(Exception):
    """Raised when a playground session operation fails."""
