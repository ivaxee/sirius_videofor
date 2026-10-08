import os
import tempfile

# Настройки читаются при импорте app.config — задаём окружение до импорта приложения.
# Тесты пересоздают схему, поэтому всегда работают только с отдельной БД из TEST_DATABASE_URL.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql://pz:pz@localhost:5432/pokazhdu_test")
os.environ["STORAGE_BACKEND"] = "local"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp(prefix="pz-media-")
os.environ["GOLD_RATE"] = "0"
os.environ["REQUESTS_PER_MINUTE"] = "100000"

import psycopg  # noqa: E402
import pytest  # noqa: E402

from app.config import settings  # noqa: E402


def _db_available() -> bool:
    try:
        with psycopg.connect(settings.database_url, connect_timeout=2):
            return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def db_ready():
    if not _db_available():
        pytest.skip("PostgreSQL недоступен (TEST_DATABASE_URL)")
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    from app.cli import SEED_DIR, import_manifest
    from app.db import init_schema

    init_schema()
    import_manifest(SEED_DIR / "manifest.json")
    yield


@pytest.fixture
def patch_settings():
    """Временная подмена параметров (Settings — frozen dataclass)."""
    saved = {}

    def apply(**kw):
        for k, v in kw.items():
            saved.setdefault(k, getattr(settings, k))
            object.__setattr__(settings, k, v)

    yield apply
    for k, v in saved.items():
        object.__setattr__(settings, k, v)


@pytest.fixture
def client(db_ready, patch_settings):
    from fastapi.testclient import TestClient

    from app.main import app

    patch_settings(burst_gap_ms=0)
    with TestClient(app) as c:
        yield c
