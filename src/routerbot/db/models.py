"""SQLAlchemy ORM models for RouterBot.

All database tables are defined here.  Uses UUID primary keys and
follows the schema described in ``docs/stages/STAGE_4_AUTH_MANAGEMENT.md``.
"""

from __future__ import annotations

import uuid
from datetime import datetime  # noqa: TC003 — SQLAlchemy evaluates Mapped[datetime] at runtime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Declarative base for all RouterBot ORM models."""

    type_annotation_map: ClassVar[dict[type, type]] = {
        dict[str, Any]: JSON,
    }


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------


class TimestampMixin:
    """Add ``created_at`` / ``updated_at`` columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class User(TimestampMixin, Base):
    """A human or service account user."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="api_user")
    max_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    spend: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sso_provider_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    keys: Mapped[list[VirtualKey]] = relationship("VirtualKey", back_populates="user", lazy="selectin")
    team_memberships: Mapped[list[UserTeam]] = relationship("UserTeam", back_populates="user", lazy="selectin")

    __table_args__ = (
        Index("ix_users_sso_provider_id", "sso_provider_id"),
    )


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------


class Team(TimestampMixin, Base):
    """A group of users sharing a budget and configuration."""

    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    budget_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    spend: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_budget_per_member: Mapped[float | None] = mapped_column(Float, nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relationships
    members: Mapped[list[UserTeam]] = relationship("UserTeam", back_populates="team", lazy="selectin")
    keys: Mapped[list[VirtualKey]] = relationship("VirtualKey", back_populates="team", lazy="selectin")


# ---------------------------------------------------------------------------
# UserTeam (association)
# ---------------------------------------------------------------------------


class UserTeam(Base):
    """Many-to-many association between User and Team with a role."""

    __tablename__ = "user_teams"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="team_memberships")
    team: Mapped[Team] = relationship("Team", back_populates="members")


# ---------------------------------------------------------------------------
# VirtualKey
# ---------------------------------------------------------------------------


class VirtualKey(TimestampMixin, Base):
    """An API key issued to a user or team for LLM access."""

    __tablename__ = "virtual_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    models: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    max_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    spend: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rate_limit_rpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_tpm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    permissions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    user: Mapped[User | None] = relationship("User", back_populates="keys")
    team: Mapped[Team | None] = relationship("Team", back_populates="keys")

    __table_args__ = (
        Index("ix_virtual_keys_user_team", "user_id", "team_id"),
    )


# ---------------------------------------------------------------------------
# SpendLog
# ---------------------------------------------------------------------------


class SpendLog(Base):
    """Per-request cost/token ledger entry."""

    __tablename__ = "spend_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("virtual_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tokens_prompt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_completion: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_spend_logs_created_model", "created_at", "model"),
        Index("ix_spend_logs_user_team", "user_id", "team_id"),
    )


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------


class AuditLog(Base):
    """Immutable audit trail for admin actions."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_audit_logs_actor_action", "actor_id", "action"),
    )


# ---------------------------------------------------------------------------
# ModelConfig
# ---------------------------------------------------------------------------


class ModelConfig(TimestampMixin, Base):
    """A dynamically-managed model deployment (alternative to YAML config)."""

    __tablename__ = "model_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    model_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    api_base: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# GuardrailPolicy
# ---------------------------------------------------------------------------


class GuardrailPolicy(TimestampMixin, Base):
    """A content-filtering or safety policy applied to requests."""

    __tablename__ = "guardrail_policies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    key_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("virtual_keys.id", ondelete="CASCADE"), nullable=True, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
