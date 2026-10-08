"""Командная строка: схема БД, импорт клипов, демо-данные.

    python -m app.cli init-db
    python -m app.cli import-clips path/to/manifest.json
    python -m app.cli seed [--demo-answers]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

from psycopg.types.json import Jsonb

from . import quality
from .answers import recompute_clip
from .common import STOP_RE, today
from .db import close_pool, init_schema, tx
from .security import ip_hash
from .storage import put_file

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
MAX_CLIP_BYTES = 1_000_000


def _validate_bbox(track) -> None:
    if not isinstance(track, list) or not track:
        raise ValueError("bbox: нужен непустой список ключевых кадров")
    for kf in track:
        for k in ("t", "x", "y", "w", "h"):
            if not isinstance(kf.get(k), (int, float)):
                raise ValueError(f"bbox: поле {k} обязательно")
        if not (0 <= kf["x"] <= 1 and 0 <= kf["y"] <= 1 and 0 < kf["w"] <= 1 and 0 < kf["h"] <= 1):
            raise ValueError("bbox: координаты должны быть в долях кадра 0..1")


def import_manifest(path: Path) -> int:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    n = 0
    with tx() as conn:
        for s in manifest.get("stops", []):
            if not STOP_RE.match(s["id"]):
                raise ValueError(f"Некорректный id остановки: {s['id']}")
            conn.execute(
                """INSERT INTO stops (id, name, region) VALUES (%s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, region = EXCLUDED.region""",
                (s["id"], s["name"], s.get("region")),
            )
        for c in manifest.get("clips", []):
            src = base / c["file"]
            size = src.stat().st_size
            if size > MAX_CLIP_BYTES:
                print(f"! {c['external_id']}: {size} байт > 1 МБ — пережмите клип", file=sys.stderr)
            _validate_bbox(c["bbox"])
            key = f"clips/{c['external_id']}.mp4"
            put_file(src, key)
            clip_id = conn.execute(
                """INSERT INTO clips (external_id, storage_key, duration_ms, width, height, size_bytes, bbox, region)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (external_id) DO UPDATE SET storage_key = EXCLUDED.storage_key,
                       duration_ms = EXCLUDED.duration_ms, width = EXCLUDED.width, height = EXCLUDED.height,
                       size_bytes = EXCLUDED.size_bytes, bbox = EXCLUDED.bbox, region = EXCLUDED.region
                   RETURNING id""",
                (c["external_id"], key, c["duration_ms"], c.get("width"), c.get("height"), size,
                 Jsonb(c["bbox"]), c.get("region")),
            ).fetchone()["id"]
            gold = c.get("gold")
            if gold:
                conn.execute(
                    """INSERT INTO gold_clips (clip_id, answer, explanation) VALUES (%s, %s, %s)
                       ON CONFLICT (clip_id) DO UPDATE SET answer = EXCLUDED.answer, explanation = EXCLUDED.explanation""",
                    (clip_id, gold["answer"], Jsonb(gold["explanation"])),
                )
            n += 1
    return n


def demo_answers(users: int = 40, seed: int = 7) -> None:
    """Имитация разметчиков разной точности — чтобы в админке были kappa, табло и экспорт.
    Пишет напрямую в БД, минуя антиспам."""
    rnd = random.Random(seed)
    manifest = json.loads((SEED_DIR / "manifest.json").read_text(encoding="utf-8"))
    truth = {c["external_id"]: c["truth"] for c in manifest["clips"]}
    d = today()
    with tx() as conn:
        if conn.execute("SELECT 1 FROM answers LIMIT 1").fetchone():
            print("Ответы уже есть — имитация пропущена")
            return
        clips = conn.execute(
            """SELECT c.id, c.external_id, (g.clip_id IS NOT NULL) AS is_gold FROM clips c
               LEFT JOIN gold_clips g ON g.clip_id = c.id WHERE c.status = 'active'"""
        ).fetchall()
        regular = [c for c in clips if not c["is_gold"] and c["external_id"] in truth]
        golds = [c for c in clips if c["is_gold"] and c["external_id"] in truth]
        stops = [r["id"] for r in conn.execute("SELECT id FROM stops").fetchall()]
        # Оставляем часть клипов без ответов, чтобы демо-пользователю было что размечать.
        pool = rnd.sample(regular, k=max(1, len(regular) * 2 // 3))
        for _ in range(users):
            acc = rnd.uniform(0.55, 0.97)
            uid = conn.execute("INSERT INTO users (consent_at, locale) VALUES (now(), 'ru') RETURNING id").fetchone()["id"]
            conn.execute("INSERT INTO user_stats (user_id) VALUES (%s)", (uid,))
            stop = rnd.choice(stops) if stops else None
            picked = rnd.sample(pool, k=min(len(pool), rnd.randint(2, 6))) + rnd.sample(golds, k=min(len(golds), 1))
            gt = gc = 0
            for c in picked:
                true = truth[c["external_id"]]
                ans = true if rnd.random() < acc else rnd.choice([a for a in quality.ANSWERS if a != true])
                sub = rnd.choice([None, *quality.SUB_ANSWERS]) if ans == "no" else None
                match = None
                if c["is_gold"] and ans != "unsure":
                    match = ans == true
                    gt += 1
                    gc += int(match)
                ago = timedelta(minutes=rnd.randint(0, 600))
                aid = conn.execute(
                    """INSERT INTO assignments (user_id, clip_id, stop_id, is_gold, issued_at, expires_at, answered_at)
                       VALUES (%s, %s, %s, %s, now() - %s, now(), now() - %s) RETURNING id""",
                    (uid, c["id"], stop, c["is_gold"], ago, ago),
                ).fetchone()["id"]
                conn.execute(
                    """INSERT INTO answers (assignment_id, clip_id, user_id, answer, sub_answer, response_time_ms,
                                            stop_id, is_gold, gold_match, ip_hash, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now() - %s)""",
                    (aid, c["id"], uid, ans, sub, rnd.randint(1800, 9000), stop, c["is_gold"], match,
                     ip_hash(f"demo-{uid}", d), ago),
                )
            conn.execute(
                """UPDATE user_stats SET answers_total = %s, gold_total = %s, gold_correct = %s, weight = %s,
                       streak_days = 1, last_active_day = %s WHERE user_id = %s""",
                (len(picked), gt, gc, quality.user_weight(gc, gt), d, uid),
            )
        for c in regular:
            recompute_clip(conn, c["id"])


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="создать/обновить схему")
    imp = sub.add_parser("import-clips", help="импорт клипов по manifest.json")
    imp.add_argument("manifest", type=Path)
    seed = sub.add_parser("seed", help="схема + демо-остановки + демо-клипы + золотые примеры")
    seed.add_argument("--demo-answers", action="store_true", help="добавить ответы имитированных разметчиков")
    args = p.parse_args(argv)

    init_schema()
    try:
        if args.cmd == "import-clips":
            print(f"Импортировано клипов: {import_manifest(args.manifest)}")
        elif args.cmd == "seed":
            print(f"Демо-клипов: {import_manifest(SEED_DIR / 'manifest.json')}")
            if args.demo_answers:
                demo_answers()
                print("Добавлены ответы имитированных разметчиков")
        else:
            print("Схема применена")
    finally:
        close_pool()


if __name__ == "__main__":
    main()
