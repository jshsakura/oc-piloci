from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
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
    # Filesystem path the project was initialized from. Disambiguates two
    # projects whose folder names slugify the same (e.g. ~/code/foo vs
    # ~/work/foo). NULL on legacy rows — resolution falls back to slug.
    cwd: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    memory_count: Mapped[int] = mapped_column(Integer, default=0)
    instinct_count: Mapped[int] = mapped_column(Integer, default=0)
    bytes_used: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "slug"),
        Index("idx_projects_user", "user_id"),
        Index("idx_projects_user_cwd", "user_id", "cwd"),
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
    """Raw transcript dump. Single source of truth for all session captures
    awaiting (or having undergone) lazy distillation.

    distillation_state state machine:
      pending   → not yet processed, eligible for worker pickup
      distilled → LLM extraction completed, memories+instincts saved
      filtered  → prefilter heuristic rejected (trivial session); no LLM call
      failed    → LLM call failed after all retries; error column populated
      archived  → slid out of distillation window; raw kept but won't be processed
    """

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
    instincts_extracted: Mapped[int] = mapped_column(Integer, default=0)

    distillation_state: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_path: Mapped[str | None] = mapped_column(Text, nullable=True)  # local|external
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filter_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index(
            "idx_raw_unprocessed",
            "processed_at",
            sqlite_where=text("processed_at IS NULL"),
        ),
        Index("idx_raw_user_project", "user_id", "project_id"),
        Index(
            "idx_raw_pending",
            "distillation_state",
            "priority",
            "created_at",
            sqlite_where=text("distillation_state = 'pending'"),
        ),
        Index("idx_raw_user_state", "user_id", "distillation_state"),
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


class UserPreferences(Base):
    """Per-user runtime preferences for the lazy distillation pipeline.

    Stored typed (vs. JSON blob) so the scheduler and worker can read columns
    directly without parsing on every poll. NULL on any field means 'use the
    server-wide default from Settings' — a fresh user has no row at all and
    inherits all defaults.
    """

    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # "HH:MM-HH:MM" — local clock; wraparound supported (e.g. 22:00-06:00).
    distillation_idle_window: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SoC °C ceiling for normal-hours local distillation. Idle window ignores it.
    distillation_temp_ceiling_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    distillation_load_ceiling_1m: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Pending-row count above which normal-hours work routes to external LLM.
    distillation_overflow_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # USD spent on external LLM per calendar month before the overflow path
    # locks itself out. NULL = no cap.
    external_budget_monthly_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class WeeklyDigest(Base):
    """Private weekly retrospective per user.

    Generated once per completed week by the lazy digest worker. Aggregates the
    user's raw_session activity together with the *private* signals that the
    MCP recall surface intentionally hides — feedback memories and reaction
    instincts. This is the surface where "이번주에 얼마나 힘들었고 뭔 작업이었는지"
    lives: never exposed to team workspaces, never returned by recall, only
    rendered for the owner on their dashboard.
    """

    __tablename__ = "weekly_digests"

    digest_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Monday (UTC) of the week the digest covers — Mon..Sun inclusive.
    week_start: Mapped[datetime] = mapped_column(Date, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON: { sessions, feedback_count, reaction_count, top_projects, ... }
    stats_json: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "week_start", name="uq_weekly_digest_user_week"),
        Index("idx_weekly_digests_user_week", "user_id", "week_start"),
    )


class ExternalLLMUsage(Base):
    """One row per external LLM call made by the distillation pipeline.

    Used by :mod:`piloci.curator.budget` to enforce monthly caps and to power
    the /api/budget/usage observability endpoint. Token counts are best-effort
    (some providers don't return usage stats) — callers store 0 in that case
    and rely on ``estimated_cost_usd`` set from per-provider pricing.
    """

    __tablename__ = "external_llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True
    )
    provider_label: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("idx_external_llm_usage_user_time", "user_id", "created_at"),)


# ---------------------------------------------------------------------------
# Team models
# ---------------------------------------------------------------------------


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("idx_teams_owner", "owner_id"),)

    members: Mapped[list[TeamMember]] = relationship(
        "TeamMember", back_populates="team", cascade="all, delete-orphan"
    )
    invites: Mapped[list[TeamInvite]] = relationship(
        "TeamInvite", back_populates="team", cascade="all, delete-orphan"
    )
    documents: Mapped[list[TeamDocument]] = relationship(
        "TeamDocument", back_populates="team", cascade="all, delete-orphan"
    )


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id: Mapped[str] = mapped_column(
        Text, ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False, default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("idx_team_members_user", "user_id"),)

    team: Mapped[Team] = relationship("Team", back_populates="members")


class TeamInvite(Base):
    __tablename__ = "team_invites"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    team_id: Mapped[str] = mapped_column(
        Text, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    inviter_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    invitee_email: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (Index("idx_team_invites_team", "team_id"),)

    team: Mapped[Team] = relationship("Team", back_populates="invites")


class TeamDocument(Base):
    __tablename__ = "team_documents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    team_id: Mapped[str] = mapped_column(
        Text, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[str] = mapped_column(
        Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("idx_team_docs_team", "team_id"),
        Index(
            "idx_team_docs_unique_path",
            "team_id",
            "path",
            unique=True,
            sqlite_where=text("is_deleted = 0"),
        ),
    )

    team: Mapped[Team] = relationship("Team", back_populates="documents")
