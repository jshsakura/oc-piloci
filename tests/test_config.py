from piloci import config
from piloci.config import Settings, get_settings


def test_low_spec_mode_clamps_pi_runtime_knobs() -> None:
    settings = Settings(
        jwt_secret="x" * 32,
        session_secret="y" * 32,
        low_spec_mode=True,
        workers=4,
        embed_lru_size=1000,
        embed_executor_workers=4,
        embed_max_concurrency=4,
        ingest_queue_maxsize=128,
        analyze_queue_maxsize=128,
        profile_refresh_min_interval_sec=60,
        curator_queue_poll_timeout_sec=1.0,
        curator_profile_project_limit=200,
        curator_profile_pause_ms=0,
        curator_transcript_max_chars=8000,
        raw_session_retention_days=365,
        audit_log_retention_days=90,
        maintenance_interval_sec=60,
        distillation_temp_ceiling_c=70.0,
        distillation_load_ceiling_1m=3.0,
        distillation_max_pending_backlog=200,
        distillation_overflow_threshold=50,
    )

    assert settings.workers == 1
    assert settings.embed_lru_size == 256
    assert settings.embed_executor_workers == 1
    assert settings.embed_max_concurrency == 1
    assert settings.ingest_queue_maxsize == 64
    assert settings.analyze_queue_maxsize == 64
    assert settings.profile_refresh_min_interval_sec == 1800
    assert settings.curator_queue_poll_timeout_sec == 10.0
    assert settings.curator_profile_project_limit == 25
    assert settings.curator_profile_pause_ms == 250
    assert settings.curator_transcript_max_chars == 4000
    assert settings.raw_session_retention_days == 365
    assert settings.audit_log_retention_days == 30
    assert settings.maintenance_interval_sec == 900
    assert settings.distillation_temp_ceiling_c == 65.0
    assert settings.distillation_load_ceiling_1m == 2.0
    assert settings.distillation_max_pending_backlog == 100
    assert settings.distillation_overflow_threshold == 25


def test_low_spec_mode_preserves_already_tighter_values() -> None:
    settings = Settings(
        jwt_secret="x" * 32,
        session_secret="y" * 32,
        low_spec_mode=True,
        embed_lru_size=128,
        ingest_queue_maxsize=32,
        analyze_queue_maxsize=32,
        profile_refresh_min_interval_sec=3600,
        curator_queue_poll_timeout_sec=30.0,
        curator_profile_project_limit=10,
        curator_profile_pause_ms=500,
        curator_transcript_max_chars=2000,
        audit_log_retention_days=7,
        maintenance_interval_sec=1800,
        distillation_temp_ceiling_c=60.0,
        distillation_load_ceiling_1m=1.5,
        distillation_max_pending_backlog=50,
        distillation_overflow_threshold=10,
    )

    assert settings.embed_lru_size == 128
    assert settings.ingest_queue_maxsize == 32
    assert settings.analyze_queue_maxsize == 32
    assert settings.profile_refresh_min_interval_sec == 3600
    assert settings.curator_queue_poll_timeout_sec == 30.0
    assert settings.curator_profile_project_limit == 10
    assert settings.curator_profile_pause_ms == 500
    assert settings.curator_transcript_max_chars == 2000
    assert settings.audit_log_retention_days == 7
    assert settings.maintenance_interval_sec == 1800
    assert settings.distillation_temp_ceiling_c == 60.0
    assert settings.distillation_load_ceiling_1m == 1.5
    assert settings.distillation_max_pending_backlog == 50
    assert settings.distillation_overflow_threshold == 10


def test_low_spec_mode_disabled_leaves_runtime_knobs_unchanged() -> None:
    settings = Settings(
        jwt_secret="x" * 32,
        session_secret="y" * 32,
        low_spec_mode=False,
        workers=4,
        embed_lru_size=1000,
        embed_executor_workers=4,
        embed_max_concurrency=4,
    )

    assert settings.workers == 4
    assert settings.embed_lru_size == 1000
    assert settings.embed_executor_workers == 4
    assert settings.embed_max_concurrency == 4


def test_get_settings_caches_instance(monkeypatch) -> None:
    config._settings = None
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("SESSION_SECRET", "y" * 32)

    first = get_settings()
    second = get_settings()

    assert first is second
    config._settings = None
