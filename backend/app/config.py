"""Настройки из переменных окружения. Значения по умолчанию подходят для локальной разработки."""

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "postgresql://pz:pz@localhost:5432/pokazhdu"))
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", "dev-secret-change-me"))
    admin_token: str = field(default_factory=lambda: _env("ADMIN_TOKEN", "dev-admin-token"))
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:5173,http://localhost:8080"))
    trust_proxy: bool = field(default_factory=lambda: _bool("TRUST_PROXY", False))
    app_tz: str = field(default_factory=lambda: _env("APP_TZ", "Europe/Moscow"))

    # Хранилище клипов
    storage_backend: str = field(default_factory=lambda: _env("STORAGE_BACKEND", "local"))  # local | s3
    media_dir: str = field(default_factory=lambda: _env("MEDIA_DIR", "./media"))
    s3_endpoint: str = field(default_factory=lambda: _env("S3_ENDPOINT", "http://localhost:9000"))
    s3_public_endpoint: str = field(default_factory=lambda: _env("S3_PUBLIC_ENDPOINT", "http://localhost:9000"))
    s3_bucket: str = field(default_factory=lambda: _env("S3_BUCKET", "clips"))
    s3_access_key: str = field(default_factory=lambda: _env("S3_ACCESS_KEY", "minioadmin"))
    s3_secret_key: str = field(default_factory=lambda: _env("S3_SECRET_KEY", "minioadmin"))
    s3_region: str = field(default_factory=lambda: _env("S3_REGION", "us-east-1"))
    clip_url_ttl: int = field(default_factory=lambda: _int("CLIP_URL_TTL", 600))

    # Качество разметки
    required_votes: int = field(default_factory=lambda: _int("REQUIRED_VOTES", 3))
    max_votes: int = field(default_factory=lambda: _int("MAX_VOTES", 7))
    consensus: float = field(default_factory=lambda: _float("CONSENSUS", 0.7))
    gold_rate: float = field(default_factory=lambda: _float("GOLD_RATE", 0.12))
    assignment_ttl: int = field(default_factory=lambda: _int("ASSIGNMENT_TTL", 900))
    max_batch: int = field(default_factory=lambda: _int("MAX_BATCH", 5))

    # Антиспам
    min_response_ms: int = field(default_factory=lambda: _int("MIN_RESPONSE_MS", 1000))
    burst_gap_ms: int = field(default_factory=lambda: _int("BURST_GAP_MS", 300))
    same_answer_run_limit: int = field(default_factory=lambda: _int("SAME_ANSWER_RUN_LIMIT", 12))
    device_daily_limit: int = field(default_factory=lambda: _int("DEVICE_DAILY_LIMIT", 60))
    session_limit: int = field(default_factory=lambda: _int("SESSION_LIMIT", 30))
    session_window_min: int = field(default_factory=lambda: _int("SESSION_WINDOW_MIN", 30))
    ip_daily_limit: int = field(default_factory=lambda: _int("IP_DAILY_LIMIT", 400))
    requests_per_minute: int = field(default_factory=lambda: _int("REQUESTS_PER_MINUTE", 120))
    report_hide_threshold: int = field(default_factory=lambda: _int("REPORT_HIDE_THRESHOLD", 2))
    reports_daily_limit: int = field(default_factory=lambda: _int("REPORTS_DAILY_LIMIT", 10))


settings = Settings()
