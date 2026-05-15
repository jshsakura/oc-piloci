from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import override


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8314
    base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("BASE_URL", "PILOCI_PUBLIC_URL"),
    )
    debug: bool = False
    reload: bool = False
    workers: int = 1
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "text"
    low_spec_mode: bool = False

    # LanceDB (vector store)
    lancedb_path: Path = Path("~/app/piloci/lancedb").expanduser()
    lancedb_index_type: Literal["NONE", "IVF_PQ"] = "IVF_PQ"
    lancedb_index_threshold: int = 10_000

    # Embedding
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_cache_dir: str | None = None
    embed_lru_size: int = 1000
    embed_executor_workers: int = 1
    embed_max_concurrency: int = max(1, min(2, os.cpu_count() or 1))

    # Gemma curator (local LLM for auto-distillation)
    gemma_endpoint: str = "http://localhost:9090/v1/chat/completions"
    gemma_model: str = "gemma"

    # Chat (RAG over memories) — provider-neutral
    chat_provider: Literal["gemma_local", "openai_compat", "anthropic"] = "gemma_local"
    chat_max_memory_chars: int = 400  # per-snippet cap before truncation
    chat_max_context_chars: int = 3500  # total budget across all snippets in prompt
    # Optional remote providers (only used when chat_provider matches)
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5"
    openai_compat_endpoint: str | None = None
    openai_compat_api_key: str | None = None
    openai_compat_model: str = "gpt-4o-mini"

    curator_enabled: bool = True
    profile_refresh_min_interval_sec: int = 600  # 10 min debounce
    curator_queue_poll_timeout_sec: float = 5.0
    curator_profile_project_limit: int = 200
    curator_profile_pause_ms: int = 0
    curator_transcript_max_chars: int = 8000
    ingest_queue_maxsize: int = 128
    ingest_retry_after_sec: int = 5
    analyze_queue_maxsize: int = 128
    analyze_retry_after_sec: int = 5

    # System-wide LLM fallback — applied after any user-defined providers in the
    # chain. Used so a deployment can wire e.g. Z.AI as a backup without each
    # user needing to register it individually. All three must be set together
    # to take effect.
    external_llm_endpoint: str | None = None
    external_llm_model: str | None = None
    external_llm_api_key: str | None = None
    external_llm_label: str = "system-fallback"
    allow_private_llm_provider_urls: bool = False

    # Lazy distillation pipeline — replaces the eager curator + analyzer.
    # The defaults here are server-wide; per-user UserPreferences rows
    # override individual fields when set.
    distillation_enabled: bool = True
    # Default idle window in local time, "HH:MM-HH:MM". Distillation runs
    # aggressively in this window regardless of temperature. None disables.
    distillation_idle_window: str | None = "02:00-07:00"
    # Outside the idle window, the worker holds when SoC ≥ this temp or
    # 1-min loadavg ≥ this load. Tuned for Pi 5 — drop both for headroom.
    distillation_temp_ceiling_c: float = 70.0
    distillation_load_ceiling_1m: float = 3.0
    # Pending-row count above which normal-hours work routes to external LLM
    # if the user has providers + budget. Backlog beyond max_pending_backlog
    # gets the oldest rows archived (FIFO drop) at ingest time.
    distillation_overflow_threshold: int = 50
    distillation_max_pending_backlog: int = 200
    # Poll cadence in seconds for the lazy worker — how often it asks the
    # scheduler "should I run now?". Idle window polls fast; held polls slow.
    distillation_poll_interval_normal_sec: float = 60.0
    distillation_poll_interval_idle_sec: float = 5.0
    distillation_poll_interval_held_sec: float = 120.0
    # Attempts per RawSession row before it's stamped 'failed'.
    distillation_max_attempts: int = 3
    # Server-wide default monthly budget for external LLM (USD). Per-user
    # UserPreferences override. None = no cap.
    distillation_default_budget_monthly_usd: float | None = None

    # Database (SQLite, M2+)
    database_url: str = "sqlite+aiosqlite:////data/piloci.db"
    sqlite_busy_timeout_ms: int = 5000
    sqlite_synchronous: Literal["NORMAL", "FULL"] = "NORMAL"

    # Ops / retention
    audit_log_retention_days: int = 90
    raw_session_retention_days: int = 90
    maintenance_interval_sec: int = 3600
    export_dir: Path = Path("/data/exports")
    vault_dir: Path = Path("/data/vaults")
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_min_duration_sec: int = 300
    telegram_min_memory_ops: int = 3
    telegram_timeout_sec: float = 5.0

    # Device health monitor — opt-in. Polls Pi 5 vitals + distillation backlog
    # and sends a Telegram alert when sustained breaches occur. Recovery
    # message follows on the back edge so the user knows when to relax.
    health_monitor_enabled: bool = False
    health_check_interval_sec: int = 60
    # A breach must persist across this many consecutive polls before firing.
    # With the default 60s interval, 3 means alerts only after 3 minutes.
    health_alert_consecutive: int = 3
    # Per-alert-kind cooldown — prevents re-firing the same alert too often
    # if state oscillates around the threshold.
    health_alert_cooldown_min: int = 30
    health_temp_alert_c: float = 75.0
    health_load_alert_1m: float = 4.0
    health_swap_alert_pct: float = 0.85
    # Backlog is "stuck" when pending rows exist and nothing has been
    # distilled in this many minutes — flags both worker hangs and a
    # device too hot to ever pass the scheduler gate.
    health_backlog_stuck_min: int = 60

    # Periodic heartbeat — independent of threshold alerts. Sends a single
    # short status snapshot every N minutes so the user can confirm progress
    # without opening the dashboard. Off by default; flip on during the
    # stabilization window after a deploy.
    health_periodic_report_enabled: bool = False
    health_periodic_report_interval_min: int = 60
    # Local-clock window during which heartbeats fire. Outside this window the
    # heartbeat suppresses (preserves the user's sleep). Format "HH:MM-HH:MM",
    # wraparound supported. None = always-on.
    health_periodic_report_active_window: str | None = "07:00-21:00"

    # Redis (M2+)
    redis_url: str = "redis://localhost:6379/0"

    # JWT (M2+)
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 90

    # Session (M2+)
    session_secret: str = Field(min_length=32)
    session_expire_days: int = 14
    session_max_per_user: int = 10
    ingest_max_body_bytes: int = 10 * 1024 * 1024
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8314"])

    # SMTP (optional, M4)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@piloci.local"

    # Google OAuth (optional, M4)
    google_client_id: str | None = None
    google_client_secret: str | None = None

    # Kakao OAuth (optional)
    kakao_client_id: str | None = None
    kakao_client_secret: str | None = None
    kakao_admin_key: str | None = None

    # Naver OAuth (optional)
    naver_client_id: str | None = None
    naver_client_secret: str | None = None

    # GitHub OAuth (optional)
    github_client_id: str | None = None
    github_client_secret: str | None = None

    @override
    def model_post_init(self, __context: object) -> None:
        self._apply_low_spec_mode()

    def _apply_low_spec_mode(self) -> None:
        if not self.low_spec_mode:
            return

        self.workers = 1
        self.embed_lru_size = min(self.embed_lru_size, 256)
        self.embed_executor_workers = 1
        self.embed_max_concurrency = 1
        self.ingest_queue_maxsize = min(self.ingest_queue_maxsize, 64)
        self.analyze_queue_maxsize = min(self.analyze_queue_maxsize, 64)
        self.profile_refresh_min_interval_sec = max(self.profile_refresh_min_interval_sec, 1800)
        self.curator_queue_poll_timeout_sec = max(self.curator_queue_poll_timeout_sec, 10.0)
        self.curator_profile_project_limit = min(self.curator_profile_project_limit, 25)
        self.curator_profile_pause_ms = max(self.curator_profile_pause_ms, 250)
        self.curator_transcript_max_chars = min(self.curator_transcript_max_chars, 4000)
        # raw_session_retention is a hard user preference (env override drives
        # the dashboard look-back window) — don't clamp it from low_spec_mode.
        self.audit_log_retention_days = min(self.audit_log_retention_days, 30)
        self.maintenance_interval_sec = max(self.maintenance_interval_sec, 900)
        # Lazy distillation: lower ceilings + tighter backlog on small devices.
        self.distillation_temp_ceiling_c = min(self.distillation_temp_ceiling_c, 65.0)
        self.distillation_load_ceiling_1m = min(self.distillation_load_ceiling_1m, 2.0)
        self.distillation_max_pending_backlog = min(self.distillation_max_pending_backlog, 100)
        self.distillation_overflow_threshold = min(self.distillation_overflow_threshold, 25)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
