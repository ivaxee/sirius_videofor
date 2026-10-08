"""Публичная статистика: общий вклад и табло остановок (без личных данных)."""

from __future__ import annotations

import threading
import time

import psycopg

from .common import day_start, resolve_stop, today

_total_cache: dict = {"value": 0, "at": 0.0}
_total_lock = threading.Lock()
TOTAL_TTL = 15.0


def total_answers(conn: psycopg.Connection) -> int:
    with _total_lock:
        if time.monotonic() - _total_cache["at"] < TOTAL_TTL:
            return _total_cache["value"]
    n = conn.execute("SELECT count(*) AS n FROM answers WHERE status = 'accepted'").fetchone()["n"]
    with _total_lock:
        _total_cache.update(value=n, at=time.monotonic())
    return n


def invalidate_total() -> None:
    with _total_lock:
        _total_cache["at"] = 0.0


def stop_stats(conn: psycopg.Connection, stop: str | None, board_size: int = 5) -> dict:
    stop_row = resolve_stop(conn, stop)
    region = stop_row["region"] if stop_row else None
    rows = conn.execute(
        """
        SELECT s.id, s.name, count(a.id) AS n
        FROM stops s
        LEFT JOIN answers a ON a.stop_id = s.id AND a.status = 'accepted' AND a.created_at >= %(start)s
        WHERE s.is_active AND (%(region)s::text IS NULL OR s.region = %(region)s)
        GROUP BY s.id, s.name
        ORDER BY n DESC, s.name
        """,
        {"start": day_start(today()), "region": region},
    ).fetchall()
    board = [{"stop_id": r["id"], "name": r["name"], "today": r["n"], "rank": i + 1} for i, r in enumerate(rows)]
    current = next((b for b in board if stop_row and b["stop_id"] == stop_row["id"]), None)
    return {
        "total_answers": total_answers(conn),
        "stop": current and {**current, "of": len(board), "region": region},
        "board": [b for b in board if b["today"] > 0][:board_size],
    }
