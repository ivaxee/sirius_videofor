"""Выдача клипов: лимиты, доля золотых, приоритет клипов с малым числом голосов и расхождением."""

from __future__ import annotations

import random
import uuid
from datetime import timedelta

import psycopg

from .common import day_start, resolve_stop, today
from .config import settings
from .security import ip_hash
from .storage import signed_url

CLIP_COLUMNS = "c.id, c.duration_ms, c.width, c.height, c.bbox, c.storage_key"


def _limits(conn: psycopg.Connection, user_id: uuid.UUID, ip: str) -> bool:
    """True, если пользователь/устройство/IP упёрлись в лимит."""
    d = today()
    start = day_start(d)
    row = conn.execute(
        """
        SELECT count(*) FILTER (WHERE created_at >= %(start)s) AS today,
               count(*) FILTER (WHERE created_at >= now() - make_interval(mins => %(win)s)) AS session
        FROM answers WHERE user_id = %(uid)s AND created_at >= LEAST(%(start)s, now() - make_interval(mins => %(win)s))
        """,
        {"uid": user_id, "start": start, "win": settings.session_window_min},
    ).fetchone()
    if row["today"] >= settings.device_daily_limit or row["session"] >= settings.session_limit:
        return True
    ip_count = conn.execute(
        "SELECT count(*) AS n FROM answers WHERE ip_hash = %s AND created_at >= %s",
        (ip_hash(ip, d), start),
    ).fetchone()["n"]
    return ip_count >= settings.ip_daily_limit


def _pick_gold(conn, user_id, k: int) -> list[dict]:
    if k <= 0:
        return []
    return conn.execute(
        f"""
        SELECT {CLIP_COLUMNS}, true AS is_gold FROM clips c
        JOIN gold_clips g ON g.clip_id = c.id
        WHERE c.status = 'active'
          AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.clip_id = c.id AND a.user_id = %s)
        ORDER BY random() LIMIT %s
        """,
        (user_id, k),
    ).fetchall()


def _pick_regular(conn, user_id, k: int, region: str | None) -> list[dict]:
    if k <= 0:
        return []
    return conn.execute(
        f"""
        WITH inflight AS (
            SELECT clip_id, count(*) AS n FROM assignments
            WHERE answered_at IS NULL AND expires_at > now()
            GROUP BY clip_id
        )
        SELECT {CLIP_COLUMNS}, false AS is_gold FROM clips c
        LEFT JOIN inflight i ON i.clip_id = c.id
        WHERE c.status = 'active'
          AND c.label_state <> 'done'
          AND NOT EXISTS (SELECT 1 FROM gold_clips g WHERE g.clip_id = c.id)
          AND NOT EXISTS (SELECT 1 FROM assignments a WHERE a.clip_id = c.id AND a.user_id = %(uid)s)
        ORDER BY
          -- клипы, которые уже «добирают» голоса незавершёнными выдачами, — в конец
          (c.votes + coalesce(i.n, 0) >= CASE WHEN c.label_state = 'pending'
                                              THEN %(req)s ELSE %(maxv)s END),
          (c.label_state = 'pending') DESC,           -- мало голосов
          (%(region)s::text IS NOT NULL AND c.region = %(region)s) DESC,  -- контент «по месту»
          c.votes,
          random()
        LIMIT %(k)s
        """,
        {"uid": user_id, "req": settings.required_votes, "maxv": settings.max_votes, "region": region, "k": k},
    ).fetchall()


def _clip_payload(row: dict, assignment_id: uuid.UUID) -> dict:
    return {
        "assignment_id": str(assignment_id),
        "url": signed_url(row["storage_key"]),
        "duration_ms": row["duration_ms"],
        "width": row["width"],
        "height": row["height"],
        "bbox": row["bbox"],
    }


def next_clips(conn: psycopg.Connection, user_id: uuid.UUID, stop: str | None, n: int, ip: str) -> dict:
    n = max(1, min(n, settings.max_batch))
    user = conn.execute(
        """SELECT u.consent_at, s.is_blocked, s.gold_total FROM users u
           JOIN user_stats s ON s.user_id = u.id WHERE u.id = %s""",
        (user_id,),
    ).fetchone()
    if user is None:
        return {"error": "unknown_user"}
    if user["consent_at"] is None:
        return {"error": "no_consent"}
    conn.execute("UPDATE users SET last_seen_at = now() WHERE id = %s", (user_id,))

    if _limits(conn, user_id, ip):
        return {"clips": [], "limit_reached": True, "exhausted": False}

    stop_row = resolve_stop(conn, stop)

    # Сначала — уже выданные, но не отвеченные клипы (повторный заход, обрыв сети).
    # Это же не даёт «накапливать» выдачи и занимать очередь.
    pending = conn.execute(
        f"""SELECT a.id AS assignment_id, {CLIP_COLUMNS} FROM assignments a
            JOIN clips c ON c.id = a.clip_id
            WHERE a.user_id = %s AND a.answered_at IS NULL AND a.expires_at > now() AND c.status = 'active'
            ORDER BY a.issued_at LIMIT %s""",
        (user_id, n),
    ).fetchall()
    result = [_clip_payload(r, r["assignment_id"]) for r in pending]
    need = n - len(result)

    if need > 0:
        if user["is_blocked"]:
            n_gold = need  # очень низкая точность: только проверочные клипы, в датасет не попадают
        else:
            n_gold = sum(1 for _ in range(need) if random.random() < settings.gold_rate)
            if user["gold_total"] == 0 and n_gold == 0:
                seen_gold = conn.execute(
                    "SELECT 1 FROM assignments WHERE user_id = %s AND is_gold LIMIT 1", (user_id,)
                ).fetchone()
                if not seen_gold:
                    n_gold = 1  # новичку — один проверочный клип сразу, чтобы оценить точность
        gold = _pick_gold(conn, user_id, n_gold)
        regular = [] if user["is_blocked"] else _pick_regular(conn, user_id, need - len(gold), stop_row and stop_row["region"])
        picked = regular + gold
        random.shuffle(picked)
        expires = timedelta(seconds=settings.assignment_ttl)
        for row in picked:
            aid = conn.execute(
                """INSERT INTO assignments (user_id, clip_id, stop_id, is_gold, expires_at)
                   VALUES (%s, %s, %s, %s, now() + %s) RETURNING id""",
                (user_id, row["id"], stop_row and stop_row["id"], row["is_gold"], expires),
            ).fetchone()["id"]
            result.append(_clip_payload(row, aid))

    return {"clips": result, "limit_reached": False, "exhausted": not result}
