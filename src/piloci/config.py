from __future__ import annotations
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server
    host: str = "0.0.0.0"
    port: int = 8314
    debug: bool = False
    reload: bool = False
    workers: int = 1
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "text"

    # LanceDB (vector store)
    lancedb_path: Path = Path("~/app/piloci/lancedb").expanduser()
    lancedb_index_type: Literal["NONE", "IVF_PQ"] = "IVF_PQ"
    lancedb_index_threshold: int = 10_000

    # Embedding
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_cache_dir: str | None = None
    embed_lru_size: int = 1000

    # Gemma curator (local LLM for auto-distillation)
    gemma_endpoint: str = "http://localhost:9090/v1/chat/completions"
    gemma_model: str = "gemma"
    curator_enabled: bool = True
    profile_refresh_min_interval_sec: int = 600  # 10 min debounce

    # Database (SQLite, M2+)
    database_url: str = "sqlite+aiosqlite:////data/piloci.db"

    # Redis (M2+)
    redis_url: str = "redis://localhost:6379/0"

    # JWT (M2+)
    jwt_secret: str = Field(default="dev-secret-change-me", min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 90

    # Session (M2+)
    session_secret: str = Field(default="dev-secret-change-me", min_length=32)
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


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
