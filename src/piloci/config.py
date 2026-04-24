from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import override


DEFAULT_JWT_SECRET_FILE = Path("/run/secrets/jwt_secret")
DEFAULT_SESSION_SECRET_FILE = Path("/run/secrets/session_secret")


def _read_secret_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _looks_like_placeholder(value: str) -> bool:
    return value in {
        "dev-secret-change-me",
        "change-me-generate-with-secrets-token-hex-32",
    }


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8314
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
    curator_enabled: bool = True
    profile_refresh_min_interval_sec: int = 600  # 10 min debounce
    curator_queue_poll_timeout_sec: float = 5.0
    curator_profile_project_limit: int = 200
    curator_profile_pause_ms: int = 0
    curator_transcript_max_chars: int = 8000
    ingest_queue_maxsize: int = 128
    ingest_retry_after_sec: int = 5

    # Database (SQLite, M2+)
    database_url: str = "sqlite+aiosqlite:////data/piloci.db"
    sqlite_busy_timeout_ms: int = 5000
    sqlite_synchronous: Literal["NORMAL", "FULL"] = "NORMAL"

    # Ops / retention
    audit_log_retention_days: int = 90
    raw_session_retention_days: int = 14
    maintenance_interval_sec: int = 3600

    # Redis (M2+)
    redis_url: str = "redis://localhost:6379/0"

    # JWT (M2+)
    jwt_secret: str = Field(default="dev-secret-change-me", min_length=32)
    jwt_secret_file: Path | None = None
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 90

    # Session (M2+)
    session_secret: str = Field(default="dev-secret-change-me", min_length=32)
    session_secret_file: Path | None = None
    session_expire_days: int = 14
    session_max_per_user: int = 10

    # SMTP (optional, M4)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@piloci.local"

    # Google OAuth (optional, M4)
    google_client_id: str | None = None
    google_client_secret: str | None = None

    @override
    def model_post_init(self, __context: object) -> None:
        self.jwt_secret = self._resolve_secret(
            secret_name="JWT_SECRET",
            current_value=self.jwt_secret,
            configured_file=self.jwt_secret_file,
            default_file=DEFAULT_JWT_SECRET_FILE,
        )
        self.session_secret = self._resolve_secret(
            secret_name="SESSION_SECRET",
            current_value=self.session_secret,
            configured_file=self.session_secret_file,
            default_file=DEFAULT_SESSION_SECRET_FILE,
        )
        self._apply_low_spec_mode()

    def _apply_low_spec_mode(self) -> None:
        if not self.low_spec_mode:
            return

        self.workers = 1
        self.embed_lru_size = min(self.embed_lru_size, 256)
        self.embed_executor_workers = 1
        self.embed_max_concurrency = 1
        self.ingest_queue_maxsize = min(self.ingest_queue_maxsize, 64)
        self.profile_refresh_min_interval_sec = max(self.profile_refresh_min_interval_sec, 1800)
        self.curator_queue_poll_timeout_sec = max(self.curator_queue_poll_timeout_sec, 10.0)
        self.curator_profile_project_limit = min(self.curator_profile_project_limit, 25)
        self.curator_profile_pause_ms = max(self.curator_profile_pause_ms, 250)
        self.curator_transcript_max_chars = min(self.curator_transcript_max_chars, 4000)
        self.raw_session_retention_days = min(self.raw_session_retention_days, 7)
        self.audit_log_retention_days = min(self.audit_log_retention_days, 30)
        self.maintenance_interval_sec = max(self.maintenance_interval_sec, 900)

    @staticmethod
    def _resolve_secret(
        *,
        secret_name: str,
        current_value: str,
        configured_file: Path | None,
        default_file: Path,
    ) -> str:
        if configured_file is not None:
            if not configured_file.is_file():
                raise FileNotFoundError(f"{secret_name}_FILE points to missing file: {configured_file}")
            return _read_secret_file(configured_file)

        if not _looks_like_placeholder(current_value):
            return current_value

        if default_file.is_file():
            return _read_secret_file(default_file)

        return current_value


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
