"""Чистые функции качества данных: веса, агрегация меток, уровни, согласованность.

Без обращений к БД — легко тестировать и переиспользовать в экспорте.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import combinations
from typing import Iterable

ANSWERS = ("cig", "vape", "no", "unsure")
SUB_ANSWERS = ("scratch", "eat", "phone", "mask", "other")
GOLD_ANSWERS = ("cig", "vape", "no")

# Байесовское сглаживание точности: априорно 2 верных из 3.
PRIOR_CORRECT = 2
PRIOR_TOTAL = 3
CHANCE_FLOOR = 0.3
MIN_WEIGHT = 0.05

BLOCK_MIN_GOLD = 6
BLOCK_BELOW = 0.4
UNBLOCK_FROM = 0.5


def smoothed_accuracy(correct: int, total: int) -> float:
    return (correct + PRIOR_CORRECT) / (total + PRIOR_TOTAL)


def user_weight(correct: int, total: int) -> float:
    acc = smoothed_accuracy(correct, total)
    return round(max(MIN_WEIGHT, min(1.0, (acc - CHANCE_FLOOR) / (1 - CHANCE_FLOOR))), 4)


def should_block(correct: int, total: int, currently_blocked: bool) -> bool:
    """Очень низкая точность на золотых → пользователь не получает новых клипов."""
    if total < BLOCK_MIN_GOLD:
        return False
    raw = correct / total
    if currently_blocked:
        return raw < UNBLOCK_FROM
    return raw < BLOCK_BELOW


@dataclass(frozen=True)
class Aggregate:
    votes: int
    label_state: str           # pending | disputed | done
    final_label: str | None
    confidence: float | None
    scores: dict[str, float]


def aggregate(votes: Iterable[tuple[str, float]], *, required: int, consensus: float, max_votes: int) -> Aggregate:
    """Взвешенное большинство по ответам (answer, weight)."""
    scores = {a: 0.0 for a in ANSWERS}
    n = 0
    for answer, weight in votes:
        scores[answer] += weight
        n += 1
    total = sum(scores.values())
    if n == 0 or total <= 0:
        return Aggregate(n, "pending", None, None, scores)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (top, top_score), (_, second_score) = ranked[0], ranked[1]
    tie = abs(top_score - second_score) < 1e-9
    confidence = round(top_score / total, 4)
    label = "unsure" if tie else top

    if n < required:
        state = "pending"
    elif confidence >= consensus and not tie:
        state = "done"
    elif n >= max_votes:
        state = "done"
    else:
        state = "disputed"
    return Aggregate(n, state, label, confidence, {k: round(v, 4) for k, v in scores.items()})


# --- Уровни -----------------------------------------------------------------

LEVELS = (
    {"key": "novice", "answers": 0, "accuracy": 0.0, "min_gold": 0},
    {"key": "observer", "answers": 25, "accuracy": 0.70, "min_gold": 3},
    {"key": "expert", "answers": 100, "accuracy": 0.85, "min_gold": 10},
)


def level_for(answers: int, gold_correct: int, gold_total: int) -> dict:
    """Уровень открывается и числом ответов, и точностью — скорость ничего не даёт."""
    accuracy = gold_correct / gold_total if gold_total else None
    idx = 0
    for i, lvl in enumerate(LEVELS):
        if i == 0:
            continue
        if answers >= lvl["answers"] and gold_total >= lvl["min_gold"] and (accuracy or 0) >= lvl["accuracy"]:
            idx = i
    nxt = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    cur = LEVELS[idx]
    progress = 1.0
    if nxt:
        span = nxt["answers"] - cur["answers"]
        progress = max(0.0, min(1.0, (answers - cur["answers"]) / span))
    return {
        "key": cur["key"],
        "index": idx,
        "next": nxt and {
            "key": nxt["key"],
            "answers_needed": max(0, nxt["answers"] - answers),
            "accuracy_needed": nxt["accuracy"],
            "gold_needed": max(0, nxt["min_gold"] - gold_total),
        },
        "progress": round(progress, 4),
        "accuracy": None if accuracy is None else round(accuracy, 4),
    }


def next_streak(last_day: date | None, streak: int, today: date) -> int:
    if last_day == today:
        return max(streak, 1)
    if last_day == today - timedelta(days=1):
        return streak + 1
    return 1


def current_streak(last_day: date | None, streak: int, today: date) -> int:
    """Серия «живая», если последний активный день — сегодня или вчера."""
    if last_day is None or last_day < today - timedelta(days=1):
        return 0
    return streak


# --- Согласованность -------------------------------------------------------

def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe >= 1.0:
        return 1.0 if po == 1.0 else None
    return (po - pe) / (1 - pe)


def pairwise_kappa(by_clip: dict[str, dict[str, str]], min_shared: int = 5) -> dict:
    """Средний Cohen's kappa по парам разметчиков с ≥ min_shared общими клипами."""
    pairs: dict[tuple[str, str], tuple[list[str], list[str]]] = defaultdict(lambda: ([], []))
    for answers in by_clip.values():
        for u, v in combinations(sorted(answers), 2):
            la, lb = pairs[(u, v)]
            la.append(answers[u])
            lb.append(answers[v])
    kappas = []
    for la, lb in pairs.values():
        if len(la) >= min_shared:
            k = cohen_kappa(la, lb)
            if k is not None:
                kappas.append(k)
    kappas.sort()
    return {
        "pairs": len(kappas),
        "mean": round(sum(kappas) / len(kappas), 4) if kappas else None,
        "median": round(kappas[len(kappas) // 2], 4) if kappas else None,
        "min_shared": min_shared,
    }


def fleiss_kappa(by_clip: dict[str, dict[str, str]], categories: Iterable[str] = ANSWERS) -> float | None:
    """Fleiss' kappa с переменным числом оценщиков на клип (только клипы с ≥ 2 ответами)."""
    cats = list(categories)
    items = [Counter(a.values()) for a in by_clip.values() if len(a) >= 2]
    if not items:
        return None
    totals = Counter()
    n_total = 0
    p_sum = 0.0
    for counts in items:
        n_i = sum(counts.values())
        n_total += n_i
        totals.update(counts)
        p_sum += (sum(c * c for c in counts.values()) - n_i) / (n_i * (n_i - 1))
    p_bar = p_sum / len(items)
    pe = sum((totals[c] / n_total) ** 2 for c in cats)
    if pe >= 1.0:
        return None
    return round((p_bar - pe) / (1 - pe), 4)
