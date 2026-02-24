"""Database layer — SQLAlchemy models, engine setup, and repositories.

Depends on core/ only.
"""

from routerbot.db.engine import create_engine, create_session_factory
from routerbot.db.models import (
    AuditLog,
    Base,
    GuardrailPolicy,
    ModelConfig,
    SpendLog,
    Team,
    User,
    UserTeam,
    VirtualKey,
)
from routerbot.db.session import configure_session_factory, get_session, get_session_factory

__all__ = [
    "AuditLog",
    "Base",
    "GuardrailPolicy",
    "ModelConfig",
    "SpendLog",
    "Team",
    "User",
    "UserTeam",
    "VirtualKey",
    "configure_session_factory",
    "create_engine",
    "create_session_factory",
    "get_session",
    "get_session_factory",
]
