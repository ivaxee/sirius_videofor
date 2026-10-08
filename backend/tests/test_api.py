import time

import psycopg
import pytest

from app.config import settings


def new_user(client, consent=True):
    r = client.post("/api/session", json={"consent": consent})
    if not consent:
        assert r.status_code == 400
        return None
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def answer(client, h, aid, ans="no", sub=None, rt=2500):
    return client.post("/api/answers", headers=h, json={
        "assignment_id": aid, "answer": ans, "sub_answer": sub, "response_time_ms": rt})


def db():
    return psycopg.connect(settings.database_url, autocommit=True)


def assign(h_user_id, clip_external_id, stop="1284", gold=False):
    """Выдать пользователю конкретный клип (минуя случайный выбор)."""
    with db() as conn:
        return str(conn.execute(
            """INSERT INTO assignments (user_id, clip_id, stop_id, is_gold, expires_at)
               SELECT %s, id, %s, %s, now() + interval '15 min' FROM clips WHERE external_id = %s
               ON CONFLICT (user_id, clip_id) DO UPDATE SET answered_at = NULL RETURNING id""",
            (h_user_id, stop, gold, clip_external_id),
        ).fetchone()[0])


def uid_of(h):
    return h["Authorization"].split()[1].split(".")[0]


def test_session_requires_consent(client):
    new_user(client, consent=False)
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer 00000000-0000-0000-0000-000000000000.bad"}).status_code == 401


def test_next_clips_and_signed_media(client):
    h = new_user(client)
    r = client.get("/api/next-clips?stop=1284&n=3", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert len(body["clips"]) == 3 and not body["limit_reached"]
    clip = body["clips"][0]
    assert set(clip) == {"assignment_id", "url", "duration_ms", "width", "height", "bbox"}
    assert "demo_" not in clip["url"] or "sig=" in clip["url"]
    media = client.get(clip["url"])
    assert media.status_code == 200 and media.headers["content-type"] == "video/mp4"
    assert client.get(clip["url"].replace("sig=", "sig=x")).status_code == 403
    # Повторный запрос возвращает те же невыполненные выдачи — нельзя «копить» клипы.
    again = client.get("/api/next-clips?stop=1284&n=3", headers=h).json()
    assert {c["assignment_id"] for c in again["clips"]} == {c["assignment_id"] for c in body["clips"]}


def test_unknown_stop_is_ignored(client):
    h = new_user(client)
    assert client.get("/api/next-clips?stop=<script>", headers=h).status_code == 422
    r = client.get("/api/next-clips?stop=nope&n=1", headers=h)
    aid = r.json()["clips"][0]["assignment_id"]
    with db() as conn:
        assert conn.execute("SELECT stop_id FROM assignments WHERE id = %s", (aid,)).fetchone()[0] is None


def test_answer_validation_and_antispam(client):
    h = new_user(client)
    clips = client.get("/api/next-clips?n=3", headers=h).json()["clips"]
    a0, a1, a2 = (c["assignment_id"] for c in clips)
    assert client.post("/api/answers", headers=h, json={"assignment_id": a0, "answer": "maybe", "response_time_ms": 2000}).status_code == 422
    r = answer(client, h, a0, "cig", rt=300)
    assert r.status_code == 200 and r.json() == {**r.json(), "accepted": False, "reason": "too_fast"}
    assert answer(client, h, a0, "cig").status_code == 409  # повтор
    other = new_user(client)
    assert answer(client, other, a1, "cig").status_code == 404  # чужая выдача
    r = answer(client, h, a1, "no", sub="phone")
    assert r.json()["accepted"] and r.json()["me"]["answers_total"] == 1
    r = answer(client, h, a2, "cig", sub="phone")  # sub_answer только для «Не курит»
    assert r.json()["accepted"]
    with db() as conn:
        rows = conn.execute(
            """SELECT answer, sub_answer, status, reject_reason, response_time_ms, stop_id, ip_hash
               FROM answers WHERE user_id = %s ORDER BY id""", (uid_of(h),)).fetchall()
    assert [r[2] for r in rows] == ["rejected", "accepted", "accepted"]
    assert rows[1][1] == "phone" and rows[2][1] is None
    assert all(r[6] and "." not in r[6] for r in rows)  # IP в открытом виде не хранится


def test_burst_detection(client, patch_settings):
    patch_settings(burst_gap_ms=5000)
    h = new_user(client)
    a, b = (c["assignment_id"] for c in client.get("/api/next-clips?n=2", headers=h).json()["clips"])
    assert answer(client, h, a, "cig").json()["accepted"]
    assert answer(client, h, b, "cig").json()["reason"] == "burst"


def test_same_answer_run(client, patch_settings):
    patch_settings(same_answer_run_limit=3)
    h = new_user(client)
    clips = client.get("/api/next-clips?n=4", headers=h).json()["clips"]
    results = [answer(client, h, c["assignment_id"], "no").json() for c in clips]
    assert [r["accepted"] for r in results] == [True, True, False, False]
    assert results[2]["reason"] == "same_answer_run"


def test_three_votes_give_final_label(client):
    with db() as conn:  # клип мог случайно попасть в выдачу в предыдущих тестах
        conn.execute("DELETE FROM assignments WHERE clip_id = (SELECT id FROM clips WHERE external_id = 'demo_009')")
        conn.execute("UPDATE clips SET votes = 0, label_state = 'pending', final_label = NULL WHERE external_id = 'demo_009'")
    users = [new_user(client) for _ in range(3)]
    for h, ans in zip(users, ["vape", "vape", "cig"]):
        aid = assign(uid_of(h), "demo_009")
        assert answer(client, h, aid, ans).json()["accepted"]
    with db() as conn:
        votes, state, label, conf = conn.execute(
            "SELECT votes, label_state, final_label, confidence FROM clips WHERE external_id = 'demo_009'").fetchone()
    # равные веса новичков: 2/3 < 0.7 → спорный, клип снова в выдаче
    assert (votes, state, label) == (3, "disputed", "vape") and abs(conf - 2 / 3) < 1e-3
    h4 = new_user(client)
    assert answer(client, h4, assign(uid_of(h4), "demo_009"), "vape").json()["accepted"]
    with db() as conn:
        assert conn.execute("SELECT label_state FROM clips WHERE external_id = 'demo_009'").fetchone()[0] == "done"
    # done-клип больше не выдаётся
    h5 = new_user(client)
    with db() as conn:
        clip_id = conn.execute("SELECT id FROM clips WHERE external_id = 'demo_009'").fetchone()[0]
    for _ in range(5):
        for c in client.get("/api/next-clips?n=5", headers=h5).json()["clips"]:
            with db() as conn:
                got = conn.execute("SELECT clip_id FROM assignments WHERE id = %s", (c["assignment_id"],)).fetchone()[0]
            assert got != clip_id
            answer(client, h5, c["assignment_id"], "unsure")


def test_gold_feedback_and_accuracy(client):
    h = new_user(client)
    aid = assign(uid_of(h), "demo_024", gold=True)  # пар на морозе → «Не курит»
    r = answer(client, h, aid, "cig").json()
    assert r["gold"]["match"] is False and r["gold"]["expert_answer"] == "no"
    assert "мороз" in r["gold"]["explanation"]
    aid = assign(uid_of(h), "demo_001", gold=True)
    r = answer(client, h, aid, "cig").json()
    assert r["gold"]["match"] is True
    aid = assign(uid_of(h), "demo_008", gold=True)
    r = answer(client, h, aid, "unsure").json()  # «Не уверен» не портит точность
    assert r["gold"]["match"] is None
    me = client.get("/api/me", headers=h).json()
    assert (me["gold_total"], me["gold_correct"], me["answers_total"]) == (2, 1, 3)
    assert me["streak"] == 1 and sum(me["week"]) == 1


def test_low_accuracy_user_gets_only_gold(client):
    h = new_user(client)
    with db() as conn:
        conn.execute("UPDATE user_stats SET gold_total = 10, gold_correct = 1, is_blocked = true WHERE user_id = %s", (uid_of(h),))
        gold_ids = {r[0] for r in conn.execute("SELECT clip_id FROM gold_clips").fetchall()}
    clips = client.get("/api/next-clips?n=3", headers=h).json()["clips"]
    with db() as conn:
        for c in clips:
            assert conn.execute("SELECT clip_id FROM assignments WHERE id = %s", (c["assignment_id"],)).fetchone()[0] in gold_ids


def test_report_hides_clip(client):
    h = new_user(client)
    aid = assign(uid_of(h), "demo_030")
    assert client.post("/api/reports", headers=h, json={"assignment_id": aid, "reason": "privacy"}).status_code == 200
    with db() as conn:
        assert conn.execute("SELECT status FROM clips WHERE external_id = 'demo_030'").fetchone()[0] == "hidden"
    assert answer(client, h, aid, "no").status_code == 409  # выдача закрыта
    # админ восстанавливает клип
    reports = client.get("/api/admin/reports", headers={"Authorization": f"Bearer {settings.admin_token}"}).json()
    rep = next(r for r in reports if r["external_id"] == "demo_030")
    r = client.post(f"/api/admin/clips/{rep['id']}/status", json={"status": "active"},
                    headers={"Authorization": f"Bearer {settings.admin_token}"})
    assert r.status_code == 200


def test_daily_limit(client, patch_settings):
    patch_settings(device_daily_limit=2)
    h = new_user(client)
    clips = client.get("/api/next-clips?n=2", headers=h).json()["clips"]
    for c in clips:
        answer(client, h, c["assignment_id"], "no")
    r = client.get("/api/next-clips?n=2", headers=h).json()
    assert r["limit_reached"] and r["clips"] == []


def test_consent_revoke_and_delete(client):
    h = new_user(client)
    aid = client.get("/api/next-clips?n=1", headers=h).json()["clips"][0]["assignment_id"]
    assert client.post("/api/me/consent", headers=h, json={"consent": False}).json()["consent"] is False
    assert answer(client, h, aid, "no").status_code == 403
    assert client.get("/api/next-clips", headers=h).status_code == 403
    client.post("/api/me/consent", headers=h, json={"consent": True})
    assert answer(client, h, aid, "no").json()["accepted"]
    assert client.delete("/api/me", headers=h).json() == {"ok": True}
    assert client.get("/api/me", headers=h).status_code == 401
    with db() as conn:
        assert conn.execute("SELECT count(*) FROM answers WHERE user_id = %s", (uid_of(h),)).fetchone()[0] == 0


def test_stats_board(client):
    h = new_user(client)
    aid = client.get("/api/next-clips?stop=3310&n=1", headers=h).json()["clips"][0]["assignment_id"]
    answer(client, h, aid, "no")
    s = client.get("/api/stats?stop=3310").json()
    assert s["total_answers"] >= 1
    assert s["stop"]["stop_id"] == "3310" and s["stop"]["today"] >= 1 and s["stop"]["region"] == "north"
    assert all(set(b) == {"stop_id", "name", "today", "rank"} for b in s["board"])
    assert client.get("/api/stats").json()["stop"] is None


def test_admin(client):
    assert client.get("/api/admin/summary").status_code == 401
    assert client.get("/api/admin/summary", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ah = {"Authorization": f"Bearer {settings.admin_token}"}
    s = client.get("/api/admin/summary", headers=ah).json()
    assert s["clips"]["total"] == 30 and s["clips"]["gold"] == 6
    ag = client.get("/api/admin/agreement?min_shared=2", headers=ah).json()
    assert {"pairwise_cohen", "fleiss", "annotators", "gold_accuracy_hist"} <= set(ag)
    rows = client.get("/api/admin/export?format=json", headers=ah).json()
    row = next(r for r in rows if r["clip_id"] == "demo_009")
    assert row["final_label"] == "vape" and row["votes"] == 4 and row["bbox"][0]["w"] > 0
    gold = next(r for r in rows if r["clip_id"] == "demo_001")
    assert gold["is_gold"] and gold["final_label"] == "cig"
    csv = client.get("/api/admin/export?format=csv&state=done", headers=ah)
    assert csv.headers["content-type"].startswith("text/csv")
    lines = csv.text.strip().splitlines()
    assert lines[0].startswith("clip_id,final_label,votes,confidence") and len(lines) >= 2


def test_security_headers(client):
    r = client.get("/api/stats")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in r.headers["content-security-policy"]


@pytest.mark.parametrize("n", [0, 11])
def test_batch_bounds(client, n):
    h = new_user(client)
    assert client.get(f"/api/next-clips?n={n}", headers=h).status_code == 422


def test_media_expired(client):
    from app.security import sign_media

    exp = int(time.time()) - 1
    assert client.get(f"/api/media/clips/demo_001.mp4?exp={exp}&sig={sign_media('clips/demo_001.mp4', exp)}").status_code == 403
    exp = int(time.time()) + 60
    assert client.get(f"/api/media/../../etc/passwd?exp={exp}&sig={sign_media('../../etc/passwd', exp)}").status_code in (403, 404)
