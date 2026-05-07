from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_sub: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_status: Mapped[str] = mapped_column(
        Text, default="pending"
    )  # pending | approved | rejected
    reviewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    quota_bytes: Mapped[int] = mapped_column(Integer, default=1073741824)

    __table_args__ = (UniqueConstraint("oauth_provider", "oauth_sub"),)

    projects: Mapped[list[Project]] = relationship(
        "Project", back_populates="user", cascade="all, delete-orphan"
    )
    api_tokens: Mapped[list[ApiToken]] = relationship(
        "ApiToken", back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[list[PasswordResetToken]] = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list[AuditLog]] = relationship("AuditLog", back_populates="user")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="password_reset_tokens")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_data: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)  # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    user: Mapped[User | None] = relationship("User", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_user", "user_id"),
        Index("idx_audit_action", "action"),
        Index("idx_audit_created", "created_at"),
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    memory_count: Mapped[int] = mapped_column(Integer, default=0)
    bytes_used: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "slug"),
        Index("idx_projects_user", "user_id"),
    )

    user: Mapped[User] = relationship("User", back_populates="projects")
    api_tokens: Mapped[list[ApiToken]] = relationship(
        "ApiToken", back_populates="project", cascade="all, delete-orphan"
    )


class ApiToken(Base):
    __tablename__ = "api_tokens"

    token_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="project")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    installed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    client_kinds: Mapped[str | None] = mapped_column(Text, nullable=True)
    hostname: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "idx_api_tokens_user",
            "user_id",
            sqlite_where=text("revoked = 0"),
        ),
        Index(
            "idx_api_tokens_project",
            "project_id",
            sqlite_where=text("revoked = 0"),
        ),
    )

    user: Mapped[User] = relationship("User", back_populates="api_tokens")
    project: Mapped[Project | None] = relationship("Project", back_populates="api_tokens")


class RawSession(Base):
    """Raw transcript dump from Stop hooks, awaiting Gemma curation."""

    __tablename__ = "raw_sessions"

    ingest_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    client: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    memories_extracted: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index(
            "idx_raw_unprocessed",
            "processed_at",
            sqlite_where=text("processed_at IS NULL"),
        ),
        Index("idx_raw_user_project", "user_id", "project_id"),
    )


class LLMProvider(Base):
    """User-managed external LLM endpoint used as fallback when Gemma is busy.

    OpenAI-compatible only — provider exposes ``POST {base_url}/chat/completions``
    or ``{base_url}/v1/chat/completions``. ``api_key`` is encrypted at rest
    using ``auth.crypto.encrypt_token``.
    """

    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("idx_llm_providers_user", "user_id", "enabled", "priority"),)


class RawAnalysis(Base):
    """Raw transcript dump from Stop hooks, awaiting Gemma instinct extraction.

    Persisted so analyze can ack the client immediately (HTTP 202) and process
    in the background — escapes Cloudflare's 100s origin timeout for synchronous
    requests. Restart-safe: on startup, rows with processed_at IS NULL are
    re-queued so nothing is lost if the worker dies mid-flight.
    """

    __tablename__ = "raw_analyses"

    analyze_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    instincts_extracted: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index(
            "idx_raw_analyses_unprocessed",
            "processed_at",
            sqlite_where=text("processed_at IS NULL"),
        ),
        Index("idx_raw_analyses_user_project", "user_id", "project_id"),
    )


class UserProfile(Base):
    """Gemma-generated profile summary per (user, project). Exposed via Resource."""

    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    profile_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
