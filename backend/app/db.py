"""Пул соединений PostgreSQL (psycopg 3) и применение схемы."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row, "autocommit": False},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def tx() -> Iterator[psycopg.Connection]:
    """Соединение в транзакции: commit при успехе, rollback при исключении."""
    with get_pool().connection() as conn:
        yield conn


def init_schema() -> None:
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        # Advisory lock: несколько реплик могут стартовать одновременно.
        conn.execute("SELECT pg_advisory_lock(424242)")
        try:
            conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
        finally:
            conn.execute("SELECT pg_advisory_unlock(424242)")
