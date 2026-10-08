"""Мелкие общие помощники."""

from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import psycopg

from .config import settings

STOP_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def tz() -> ZoneInfo:
    return ZoneInfo(settings.app_tz)


def today() -> date:
    return datetime.now(tz()).date()


def day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=tz())


def resolve_stop(conn: psycopg.Connection, stop: str | None) -> dict | None:
    """Только известные активные остановки: мусорные ?stop= не попадают в данные."""
    if not stop or not STOP_RE.match(stop):
        return None
    return conn.execute(
        "SELECT id, name, region FROM stops WHERE id = %s AND is_active", (stop,)
    ).fetchone()
