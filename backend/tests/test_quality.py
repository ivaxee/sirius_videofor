from datetime import date

from app import quality as q


def test_weight_grows_with_accuracy():
    assert q.user_weight(0, 0) == q.user_weight(0, 0)
    newbie = q.user_weight(0, 0)
    assert 0.4 < newbie < 0.6
    assert q.user_weight(20, 20) > 0.9
    assert q.user_weight(2, 20) == q.MIN_WEIGHT


def test_block_and_unblock():
    assert not q.should_block(0, 5, False)          # мало данных
    assert q.should_block(2, 6, False)              # 33% < 40%
    assert not q.should_block(3, 6, False)
    assert q.should_block(4, 9, True)               # 44% — ещё не реабилитирован
    assert not q.should_block(5, 10, True)


def agg(votes):
    return q.aggregate(votes, required=3, consensus=0.7, max_votes=7)


def test_aggregate_states():
    assert agg([]).label_state == "pending"
    a = agg([("cig", 1), ("cig", 1)])
    assert a.label_state == "pending" and a.final_label == "cig"
    a = agg([("cig", 1), ("cig", 1), ("cig", 0.5)])
    assert (a.label_state, a.final_label, a.confidence) == ("done", "cig", 1.0)
    a = agg([("cig", 1), ("no", 1), ("vape", 1)])
    assert a.label_state == "disputed" and a.final_label == "unsure"  # ничья
    a = agg([("cig", 1), ("no", 0.1), ("no", 0.1)])
    assert a.final_label == "cig" and a.label_state == "done"  # вес решает, а не число голосов
    a = agg([("cig", 1)] * 4 + [("no", 1)] * 3)
    assert a.label_state == "done" and a.confidence < 0.7  # исчерпан MAX_VOTES


def test_levels_need_accuracy_not_speed():
    assert q.level_for(500, 0, 0)["key"] == "novice"           # много ответов, но точность неизвестна
    assert q.level_for(30, 3, 4)["key"] == "observer"
    assert q.level_for(30, 2, 4)["key"] == "novice"            # 50% < 70%
    assert q.level_for(120, 9, 10)["key"] == "expert"
    lvl = q.level_for(10, 1, 1)
    assert lvl["next"]["key"] == "observer" and lvl["next"]["answers_needed"] == 15
    assert lvl["progress"] == 0.4


def test_streak():
    d = date(2026, 10, 8)
    assert q.next_streak(None, 0, d) == 1
    assert q.next_streak(date(2026, 10, 7), 3, d) == 4
    assert q.next_streak(d, 4, d) == 4
    assert q.next_streak(date(2026, 10, 5), 4, d) == 1
    assert q.current_streak(date(2026, 10, 6), 4, d) == 0


def test_kappa():
    a = ["cig", "no", "no", "vape", "no", "cig"]
    assert q.cohen_kappa(a, a) == 1.0
    assert abs(q.cohen_kappa(["cig", "no"] * 5, ["no", "cig"] * 5) + 1.0) < 1e-9
    by_clip = {str(i): {"u1": x, "u2": x, "u3": x} for i, x in enumerate(a)}
    assert q.pairwise_kappa(by_clip, min_shared=5)["mean"] == 1.0
    assert q.fleiss_kappa(by_clip) == 1.0
    # Классический пример Fleiss (Wikipedia, 10 объектов × 14 оценщиков) — κ ≈ 0.210
    table = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
             [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]
    cats = ["a", "b", "c", "d", "e"]
    items = {}
    for i, row in enumerate(table):
        labels = [c for c, n in zip(cats, row) for _ in range(n)]
        items[str(i)] = {f"r{j}": lab for j, lab in enumerate(labels)}
    assert abs(q.fleiss_kappa(items, cats) - 0.210) < 0.001
