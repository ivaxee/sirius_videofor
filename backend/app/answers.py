"""Приём ответов (антиспам, золотые клипы, веса), жалобы, профиль пользователя."""

from __future__ import annotations

import uuid
from datetime import timedelta

import psycopg

from . import quality
from .common import day_start, today
from .config import settings
from .security import ip_hash


class ApiError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def recompute_clip(conn: psycopg.Connection, clip_id) -> quality.Aggregate:
    rows = conn.execute(
        """SELECT a.answer, s.weight FROM answers a
           JOIN user_stats s ON s.user_id = a.user_id
           WHERE a.clip_id = %s AND a.status = 'accepted' AND NOT a.is_gold""",
        (clip_id,),
    ).fetchall()
    agg = quality.aggregate(
        ((r["answer"], r["weight"]) for r in rows),
        required=settings.required_votes, consensus=settings.consensus, max_votes=settings.max_votes,
    )
    conn.execute(
        "UPDATE clips SET votes = %s, label_state = %s, final_label = %s, confidence = %s WHERE id = %s",
        (agg.votes, agg.label_state, agg.final_label, agg.confidence, clip_id),
    )
    return agg


def _reject_reason(stats: dict, answer: str, rt_ms: int, gap_ms: float | None) -> str | None:
    if rt_ms < settings.min_response_ms:
        return "too_fast"
    if gap_ms is not None and gap_ms < settings.burst_gap_ms:
        return "burst"
    run = stats["same_answer_run"] + 1 if stats["last_answer"] == answer else 1
    if run >= settings.same_answer_run_limit:
        return "same_answer_run"
    return None


def submit_answer(
    conn: psycopg.Connection, user_id: uuid.UUID, assignment_id: uuid.UUID,
    answer: str, sub_answer: str | None, response_time_ms: int, ip: str, locale: str,
) -> dict:
    a = conn.execute(
        "SELECT * FROM assignments WHERE id = %s AND user_id = %s FOR UPDATE",
        (assignment_id, user_id),
    ).fetchone()
    if a is None:
        raise ApiError(404, "unknown_assignment")
    if a["answered_at"] is not None:
        raise ApiError(409, "already_answered")

    user = conn.execute("SELECT consent_at FROM users WHERE id = %s", (user_id,)).fetchone()
    if user is None or user["consent_at"] is None:
        raise ApiError(403, "no_consent")

    stats = conn.execute(
        "SELECT *, now() AS db_now FROM user_stats WHERE user_id = %s FOR UPDATE", (user_id,)
    ).fetchone()
    now = stats["db_now"]
    gap_ms = None
    if stats["last_answer_at"] is not None:
        gap_ms = (now - stats["last_answer_at"]).total_seconds() * 1000

    if answer != "no":
        sub_answer = None
    reason = _reject_reason(stats, answer, response_time_ms, gap_ms)
    accepted = reason is None

    gold = None
    gold_match = None
    if a["is_gold"]:
        gold = conn.execute("SELECT answer, explanation FROM gold_clips WHERE clip_id = %s", (a["clip_id"],)).fetchone()
        if gold and answer != "unsure":  # «Не уверен» — честный ответ, не ошибка
            gold_match = answer == gold["answer"]

    d = today()
    conn.execute(
        """INSERT INTO answers (assignment_id, clip_id, user_id, answer, sub_answer, response_time_ms,
                                stop_id, is_gold, gold_match, status, reject_reason, ip_hash)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (assignment_id, a["clip_id"], user_id, answer, sub_answer, response_time_ms, a["stop_id"],
         a["is_gold"], gold_match, "accepted" if accepted else "rejected", reason, ip_hash(ip, d)),
    )
    conn.execute("UPDATE assignments SET answered_at = now() WHERE id = %s", (assignment_id,))

    run = stats["same_answer_run"] + 1 if stats["last_answer"] == answer else 1
    upd = {
        "answers_total": stats["answers_total"],
        "answers_rejected": stats["answers_rejected"],
        "gold_total": stats["gold_total"],
        "gold_correct": stats["gold_correct"],
        "weight": stats["weight"],
        "is_blocked": stats["is_blocked"],
        "streak_days": stats["streak_days"],
        "last_active_day": stats["last_active_day"],
    }
    if accepted:
        upd["answers_total"] += 1
        if gold_match is not None:
            upd["gold_total"] += 1
            upd["gold_correct"] += int(gold_match)
            upd["weight"] = quality.user_weight(upd["gold_correct"], upd["gold_total"])
            upd["is_blocked"] = quality.should_block(upd["gold_correct"], upd["gold_total"], stats["is_blocked"])
        upd["streak_days"] = quality.next_streak(stats["last_active_day"], stats["streak_days"], d)
        upd["last_active_day"] = d
    else:
        upd["answers_rejected"] += 1

    conn.execute(
        """UPDATE user_stats SET answers_total = %(answers_total)s, answers_rejected = %(answers_rejected)s,
               gold_total = %(gold_total)s, gold_correct = %(gold_correct)s, weight = %(weight)s,
               is_blocked = %(is_blocked)s, streak_days = %(streak_days)s, last_active_day = %(last_active_day)s,
               last_answer = %(last_answer)s, same_answer_run = %(run)s, last_answer_at = now(), updated_at = now()
           WHERE user_id = %(uid)s""",
        {**upd, "last_answer": answer, "run": run, "uid": user_id},
    )

    if accepted and not a["is_gold"]:
        recompute_clip(conn, a["clip_id"])

    result: dict = {"accepted": accepted, "reason": reason}
    if accepted and gold is not None:
        expl = gold["explanation"] or {}
        result["gold"] = {
            "match": gold_match,
            "expert_answer": gold["answer"],
            "explanation": expl.get(locale) or expl.get("ru") or "",
        }
    result["me"] = me(conn, user_id)
    return result


REPORT_REASONS = ("inappropriate", "privacy", "broken", "other")
IMMEDIATE_HIDE = ("inappropriate", "privacy")


def report_clip(conn: psycopg.Connection, user_id: uuid.UUID, assignment_id: uuid.UUID, reason: str) -> dict:
    a = conn.execute(
        "SELECT clip_id FROM assignments WHERE id = %s AND user_id = %s FOR UPDATE", (assignment_id, user_id)
    ).fetchone()
    if a is None:
        raise ApiError(404, "unknown_assignment")
    n_today = conn.execute(
        "SELECT count(*) AS n FROM clip_reports WHERE user_id = %s AND created_at >= %s",
        (user_id, day_start(today())),
    ).fetchone()["n"]
    if n_today >= settings.reports_daily_limit:
        raise ApiError(429, "report_limit")

    inserted = conn.execute(
        """INSERT INTO clip_reports (clip_id, user_id, reason) VALUES (%s, %s, %s)
           ON CONFLICT (clip_id, user_id) DO NOTHING RETURNING id""",
        (a["clip_id"], user_id, reason),
    ).fetchone()
    # Клип сразу пропадает из выдачи этого пользователя: выдача закрыта.
    conn.execute("UPDATE assignments SET answered_at = coalesce(answered_at, now()) WHERE id = %s", (assignment_id,))
    if inserted:
        open_reports = conn.execute(
            """UPDATE clips SET reports_count = reports_count + 1 WHERE id = %s
               RETURNING (SELECT count(*) FROM clip_reports r WHERE r.clip_id = clips.id AND r.resolved_at IS NULL) AS n""",
            (a["clip_id"],),
        ).fetchone()["n"]
        threshold = 1 if reason in IMMEDIATE_HIDE else settings.report_hide_threshold
        if open_reports >= threshold:
            conn.execute("UPDATE clips SET status = 'hidden' WHERE id = %s AND status = 'active'", (a["clip_id"],))
    return {"ok": True}


def me(conn: psycopg.Connection, user_id: uuid.UUID) -> dict:
    s = conn.execute(
        """SELECT s.*, u.consent_at FROM user_stats s JOIN users u ON u.id = s.user_id WHERE s.user_id = %s""",
        (user_id,),
    ).fetchone()
    if s is None:
        raise ApiError(401, "unknown_user")
    d = today()
    monday = d - timedelta(days=d.weekday())
    days = conn.execute(
        """SELECT DISTINCT (created_at AT TIME ZONE %s)::date AS day FROM answers
           WHERE user_id = %s AND status = 'accepted' AND created_at >= %s""",
        (settings.app_tz, user_id, day_start(monday)),
    ).fetchall()
    active = {r["day"] for r in days}
    return {
        "user_id": str(user_id),
        "consent": s["consent_at"] is not None,
        "answers_total": s["answers_total"],
        "gold_total": s["gold_total"],
        "gold_correct": s["gold_correct"],
        "level": quality.level_for(s["answers_total"], s["gold_correct"], s["gold_total"]),
        "streak": quality.current_streak(s["last_active_day"], s["streak_days"], d),
        "week": [(monday + timedelta(days=i)) in active for i in range(7)],
        "paused": s["is_blocked"],
    }


def set_consent(conn: psycopg.Connection, user_id: uuid.UUID, consent: bool) -> dict:
    conn.execute(
        "UPDATE users SET consent_at = CASE WHEN %s THEN coalesce(consent_at, now()) ELSE NULL END WHERE id = %s",
        (consent, user_id),
    )
    return me(conn, user_id)


def delete_user(conn: psycopg.Connection, user_id: uuid.UUID) -> None:
    clips = conn.execute(
        "SELECT DISTINCT clip_id FROM answers WHERE user_id = %s AND NOT is_gold", (user_id,)
    ).fetchall()
    conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
    for r in clips:
        recompute_clip(conn, r["clip_id"])


def create_user(conn: psycopg.Connection, locale: str | None) -> uuid.UUID:
    uid = conn.execute(
        "INSERT INTO users (consent_at, locale) VALUES (now(), %s) RETURNING id", (locale,)
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO user_stats (user_id, weight) VALUES (%s, %s)", (uid, quality.user_weight(0, 0))
    )
    return uid
