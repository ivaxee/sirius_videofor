"""Админка: статистика по классам, согласованность (kappa), экспорт итоговой разметки, модерация."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter, defaultdict

import psycopg

from . import quality
from .answers import recompute_clip
from .common import day_start, today
from .config import settings


def summary(conn: psycopg.Connection) -> dict:
    def grouped(sql: str, params=()) -> dict:
        return {r["k"] if r["k"] is not None else "none": r["n"] for r in conn.execute(sql, params).fetchall()}

    users = conn.execute(
        """SELECT count(*) AS total,
                  count(*) FILTER (WHERE u.last_seen_at >= %s) AS active_today,
                  count(*) FILTER (WHERE s.is_blocked) AS blocked,
                  avg(s.weight) AS avg_weight,
                  sum(s.gold_correct)::float / nullif(sum(s.gold_total), 0) AS gold_accuracy
           FROM users u JOIN user_stats s ON s.user_id = u.id""",
        (day_start(today()),),
    ).fetchone()
    rt = conn.execute(
        """SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY response_time_ms) AS median
           FROM answers WHERE status = 'accepted'"""
    ).fetchone()
    return {
        "clips": {
            "total": conn.execute("SELECT count(*) AS n FROM clips").fetchone()["n"],
            "gold": conn.execute("SELECT count(*) AS n FROM gold_clips").fetchone()["n"],
            "by_status": grouped("SELECT status AS k, count(*) AS n FROM clips GROUP BY 1"),
            "by_state": grouped(
                """SELECT label_state AS k, count(*) AS n FROM clips c
                   WHERE NOT EXISTS (SELECT 1 FROM gold_clips g WHERE g.clip_id = c.id) GROUP BY 1"""
            ),
            "final_labels": grouped(
                """SELECT final_label AS k, count(*) AS n FROM clips c WHERE label_state = 'done'
                   AND NOT EXISTS (SELECT 1 FROM gold_clips g WHERE g.clip_id = c.id) GROUP BY 1"""
            ),
        },
        "answers": {
            "by_answer": grouped("SELECT answer AS k, count(*) AS n FROM answers WHERE status = 'accepted' GROUP BY 1"),
            "by_sub_answer": grouped(
                "SELECT sub_answer AS k, count(*) AS n FROM answers WHERE status = 'accepted' AND answer = 'no' GROUP BY 1"
            ),
            "rejected": grouped("SELECT reject_reason AS k, count(*) AS n FROM answers WHERE status = 'rejected' GROUP BY 1"),
            "today": conn.execute(
                "SELECT count(*) AS n FROM answers WHERE status = 'accepted' AND created_at >= %s",
                (day_start(today()),),
            ).fetchone()["n"],
            "median_response_ms": rt["median"],
        },
        "users": {
            "total": users["total"],
            "active_today": users["active_today"],
            "blocked": users["blocked"],
            "avg_weight": users["avg_weight"] and round(users["avg_weight"], 3),
            "gold_accuracy": users["gold_accuracy"] and round(users["gold_accuracy"], 3),
        },
        "reports_open": conn.execute("SELECT count(*) AS n FROM clip_reports WHERE resolved_at IS NULL").fetchone()["n"],
        "config": {
            "required_votes": settings.required_votes, "max_votes": settings.max_votes,
            "consensus": settings.consensus, "gold_rate": settings.gold_rate,
        },
    }


def _anon(user_id) -> str:
    # Короткий необратимый идентификатор для отчёта — без связи с токеном.
    return "r_" + hashlib.sha256(f"{settings.secret_key}:{user_id}".encode()).hexdigest()[:8]


def agreement(conn: psycopg.Connection, min_shared: int = 5) -> dict:
    rows = conn.execute(
        """SELECT a.clip_id, a.user_id, a.answer FROM answers a
           WHERE a.status = 'accepted' AND NOT a.is_gold"""
    ).fetchall()
    by_clip: dict[str, dict[str, str]] = defaultdict(dict)
    for r in rows:
        by_clip[str(r["clip_id"])][str(r["user_id"])] = r["answer"]

    finals = {
        str(r["id"]): r["final_label"]
        for r in conn.execute("SELECT id, final_label FROM clips WHERE label_state = 'done'").fetchall()
    }
    per_user: dict[str, tuple[list[str], list[str]]] = defaultdict(lambda: ([], []))
    for clip_id, answers in by_clip.items():
        final = finals.get(clip_id)
        if final is None:
            continue
        for uid, ans in answers.items():
            mine, cons = per_user[uid]
            mine.append(ans)
            cons.append(final)
    annotators = []
    for uid, (mine, cons) in per_user.items():
        if len(mine) >= min_shared:
            k = quality.cohen_kappa(mine, cons)
            agree = sum(1 for x, y in zip(mine, cons) if x == y) / len(mine)
            annotators.append({
                "annotator": _anon(uid), "clips": len(mine),
                "kappa_vs_consensus": None if k is None else round(k, 4), "agreement": round(agree, 4),
            })
    annotators.sort(key=lambda x: -x["clips"])
    vs = [a["kappa_vs_consensus"] for a in annotators if a["kappa_vs_consensus"] is not None]

    gold = conn.execute(
        """SELECT gold_total, gold_correct FROM user_stats WHERE gold_total > 0"""
    ).fetchall()
    buckets = Counter()
    for g in gold:
        acc = g["gold_correct"] / g["gold_total"]
        buckets[min(9, int(acc * 10))] += 1

    return {
        "pairwise_cohen": quality.pairwise_kappa(by_clip, min_shared=min_shared),
        "fleiss": quality.fleiss_kappa(by_clip),
        "vs_consensus_mean": round(sum(vs) / len(vs), 4) if vs else None,
        "annotators": annotators[:30],
        "gold_accuracy_hist": [{"from": i / 10, "to": (i + 1) / 10, "users": buckets.get(i, 0)} for i in range(10)],
        "clips_with_2plus": sum(1 for a in by_clip.values() if len(a) >= 2),
    }


EXPORT_FIELDS = ["clip_id", "final_label", "votes", "confidence", "label_state", "is_gold",
                 "score_cig", "score_vape", "score_no", "score_unsure", "top_no_reason", "duration_ms", "bbox"]


def export_rows(conn: psycopg.Connection, state: str | None = None, min_confidence: float | None = None) -> list[dict]:
    # Пересчитываем все метки по текущим весам: точность разметчиков уточняется со временем.
    for r in conn.execute("SELECT id FROM clips c WHERE NOT EXISTS (SELECT 1 FROM gold_clips g WHERE g.clip_id = c.id)").fetchall():
        recompute_clip(conn, r["id"])

    weights = conn.execute(
        """SELECT a.clip_id, a.answer, a.sub_answer, s.weight FROM answers a
           JOIN user_stats s ON s.user_id = a.user_id
           WHERE a.status = 'accepted' AND NOT a.is_gold"""
    ).fetchall()
    scores: dict = defaultdict(lambda: {k: 0.0 for k in quality.ANSWERS})
    subs: dict = defaultdict(Counter)
    for w in weights:
        scores[w["clip_id"]][w["answer"]] += w["weight"]
        if w["sub_answer"]:
            subs[w["clip_id"]][w["sub_answer"]] += 1

    clips = conn.execute(
        """SELECT c.id, c.external_id, c.bbox, c.duration_ms, c.votes, c.label_state, c.final_label,
                  c.confidence, g.answer AS gold_answer
           FROM clips c LEFT JOIN gold_clips g ON g.clip_id = c.id
           WHERE c.status <> 'hidden' ORDER BY c.created_at, c.id"""
    ).fetchall()
    out = []
    for c in clips:
        is_gold = c["gold_answer"] is not None
        row = {
            "clip_id": c["external_id"] or str(c["id"]),
            "final_label": c["gold_answer"] if is_gold else c["final_label"],
            "votes": c["votes"],
            "confidence": 1.0 if is_gold else c["confidence"],
            "label_state": "gold" if is_gold else c["label_state"],
            "is_gold": is_gold,
            **{f"score_{k}": round(v, 4) for k, v in scores[c["id"]].items()},
            "top_no_reason": subs[c["id"]].most_common(1)[0][0] if subs[c["id"]] else None,
            "duration_ms": c["duration_ms"],
            "bbox": c["bbox"],
        }
        if state and row["label_state"] != state:
            continue
        if min_confidence is not None and (row["confidence"] or 0) < min_confidence:
            continue
        out.append(row)
    return out


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS)
    w.writeheader()
    for r in rows:
        w.writerow({**r, "bbox": json.dumps(r["bbox"], separators=(",", ":"))})
    return buf.getvalue()


def reports(conn: psycopg.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT c.id, c.external_id, c.status, c.reports_count,
                  array_agg(r.reason ORDER BY r.created_at) AS reasons, max(r.created_at) AS last_at
           FROM clip_reports r JOIN clips c ON c.id = r.clip_id
           WHERE r.resolved_at IS NULL
           GROUP BY c.id ORDER BY last_at DESC LIMIT 200"""
    ).fetchall()
    return [{**r, "id": str(r["id"]), "last_at": r["last_at"].isoformat()} for r in rows]


def set_clip_status(conn: psycopg.Connection, clip_id, status: str) -> bool:
    row = conn.execute("UPDATE clips SET status = %s WHERE id = %s RETURNING id", (status, clip_id)).fetchone()
    if row is None:
        return False
    conn.execute(
        "UPDATE clip_reports SET resolved_at = now(), resolution = %s WHERE clip_id = %s AND resolved_at IS NULL",
        ("restored" if status == "active" else "removed", clip_id),
    )
    return True
