"""Генератор синтетических демо-клипов для локального запуска.

Рисует простые сцены у остановки (numpy) и кодирует их ffmpeg в H.264 MP4 без звука.
Лица и номер машины закрыты мозаикой — так же, как это делает настоящий пайплайн.

    pip install numpy && python seed/generate_clips.py

Результат: seed/clips/*.mp4, seed/manifest.json и пример для онбординга
frontend/public/example.mp4. Готовые файлы уже лежат в репозитории.
"""

from __future__ import annotations

import json
import math
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

W, H, FPS = 640, 480, 15
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "clips"
EXAMPLE = ROOT.parent.parent / "frontend" / "public" / "example.mp4"


# --- примитивы ---------------------------------------------------------------

def _paint(img, y0, y1, x0, x1, m, color):
    if m is None or y0 >= y1 or x0 >= x1:
        return
    c = np.asarray(color, dtype=np.float32)
    region = img[y0:y1, x0:x1]
    region *= 1 - m[..., None]
    region += c * m[..., None]


def _box(cx, cy, rx, ry):
    return max(0, int(cy - ry - 2)), min(H, int(cy + ry + 3)), max(0, int(cx - rx - 2)), min(W, int(cx + rx + 3))


def circle(img, cx, cy, r, color, alpha=1.0, soft=0.0):
    y0, y1, x0, x1 = _box(cx, cy, r + soft, r + soft)
    if y0 >= y1 or x0 >= x1:
        return
    yy, xx = np.ogrid[y0:y1, x0:x1]
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    m = np.clip((r - d) / soft, 0, 1) if soft else np.clip(r - d + 0.5, 0, 1)
    _paint(img, y0, y1, x0, x1, (m * alpha).astype(np.float32), color)


def capsule(img, p, q, r, color, alpha=1.0):
    (ax, ay), (bx, by) = p, q
    y0, y1 = max(0, int(min(ay, by) - r - 2)), min(H, int(max(ay, by) + r + 3))
    x0, x1 = max(0, int(min(ax, bx) - r - 2)), min(W, int(max(ax, bx) + r + 3))
    if y0 >= y1 or x0 >= x1:
        return
    yy, xx = np.ogrid[y0:y1, x0:x1]
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy or 1e-6
    t = np.clip(((xx - ax) * dx + (yy - ay) * dy) / L2, 0, 1)
    d = np.sqrt((xx - ax - t * dx) ** 2 + (yy - ay - t * dy) ** 2)
    _paint(img, y0, y1, x0, x1, (np.clip(r - d + 0.5, 0, 1) * alpha).astype(np.float32), color)


def rect(img, x0, y0, x1, y1, color, alpha=1.0):
    x0, x1 = max(0, int(x0)), min(W, int(x1))
    y0, y1 = max(0, int(y0)), min(H, int(y1))
    if x0 < x1 and y0 < y1:
        _paint(img, y0, y1, x0, x1, np.full((y1 - y0, x1 - x0), alpha, np.float32), color)


def mosaic(img, x0, y0, x1, y1, block):
    """Размытие лица/номера: крупная мозаика."""
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(W, int(x1)), min(H, int(y1))
    block = max(3, int(block))
    for by in range(y0, y1, block):
        for bx in range(x0, x1, block):
            cell = img[by:min(by + block, y1), bx:min(bx + block, x1)]
            cell[...] = cell.reshape(-1, 3).mean(axis=0)


# --- сцена -----------------------------------------------------------------

@dataclass
class Scene:
    cold: bool = False
    dark: bool = False


def background(rnd: random.Random, scene: Scene) -> np.ndarray:
    img = np.zeros((H, W, 3), np.float32)
    top = np.array([150, 170, 190] if not scene.cold else [190, 200, 215], np.float32)
    bot = np.array([200, 205, 210] if not scene.cold else [225, 230, 238], np.float32)
    for y in range(240):
        img[y] = top + (bot - top) * (y / 240)
    x = 0
    while x < W:  # дома
        bw = rnd.randint(70, 150)
        bh = rnd.randint(120, 220)
        tone = rnd.randint(95, 150)
        col = (tone, tone - 5, tone - 12)
        rect(img, x, 240 - bh, x + bw, 250, col)
        for wy in range(240 - bh + 12, 236, 24):
            for wx in range(x + 8, x + bw - 14, 20):
                lit = rnd.random() < 0.25
                rect(img, wx, wy, wx + 10, wy + 14, (230, 210, 150) if lit else (70, 80, 92))
        x += bw + rnd.randint(0, 8)
    rect(img, 0, 250, W, 300, (78, 80, 84))      # дорога
    for lx in range(0, W, 60):
        rect(img, lx, 274, lx + 30, 277, (210, 210, 200))
    rect(img, 0, 300, W, H, (150, 148, 142) if not scene.cold else (225, 228, 235))  # тротуар
    for y in range(300, H, 26):
        rect(img, 0, y, W, y + 1, (130, 128, 122) if not scene.cold else (205, 210, 220))
    # павильон остановки
    sx = rnd.choice([30, 380])
    rect(img, sx, 150, sx + 230, 160, (60, 70, 82))
    rect(img, sx + 4, 160, sx + 10, 330, (60, 70, 82))
    rect(img, sx + 220, 160, sx + 226, 330, (60, 70, 82))
    rect(img, sx + 10, 165, sx + 220, 300, (170, 200, 220), alpha=0.25)
    rect(img, sx + 150, 175, sx + 210, 255, (240, 240, 235))  # табличка расписания
    if scene.cold:
        flakes = np.random.default_rng(rnd.randint(0, 9999))
        ys, xs = flakes.integers(0, H, 400), flakes.integers(0, W, 400)
        img[ys, xs] = (245, 248, 255)
    return img


@dataclass
class Person:
    cx: float
    feet: float
    s: float
    coat: tuple
    pants: tuple = (45, 48, 55)
    skin: tuple = (205, 165, 140)
    hair: tuple = (55, 45, 40)
    walk: float = 0.0  # пикселей в секунду

    def pos(self, t):
        return self.cx + self.walk * t + 3 * self.s * math.sin(t * 1.3), self.feet

    def head(self, t):
        cx, f = self.pos(t)
        return cx, f - 212 * self.s, 20 * self.s

    def mouth(self, t):
        hx, hy, r = self.head(t)
        return hx + 0.55 * r, hy + 0.45 * r

    def bbox(self, t):
        cx, f = self.pos(t)
        s = self.s
        return (cx - 46 * s, f - 240 * s, cx + 52 * s, f + 4 * s)


def draw_person(img, p: Person, t: float, raise_: float = 0.0, hand_target=None):
    """raise_ 0..1 — рука от пояса к лицу. Возвращает координаты кисти."""
    cx, f = p.pos(t)
    s = p.s
    step = math.sin(t * 6) * 6 * s if p.walk else 0
    capsule(img, (cx - 10 * s, f - 100 * s), (cx - 10 * s + step, f), 8 * s, p.pants)
    capsule(img, (cx + 10 * s, f - 100 * s), (cx + 10 * s - step, f), 8 * s, p.pants)
    rect(img, cx - 32 * s, f - 192 * s, cx + 32 * s, f - 92 * s, p.coat)
    circle(img, cx - 32 * s + 6 * s, f - 186 * s, 6 * s, p.coat)
    circle(img, cx + 32 * s - 6 * s, f - 186 * s, 6 * s, p.coat)
    rect(img, cx - 6 * s, f - 200 * s, cx + 6 * s, f - 190 * s, p.skin)
    hx, hy, r = p.head(t)
    circle(img, hx, hy, r, p.skin)
    circle(img, hx, hy - 0.45 * r, r * 0.92, p.hair)
    circle(img, hx, hy + 0.15 * r, r * 0.85, p.skin)
    # левая рука висит
    capsule(img, (cx - 28 * s, f - 182 * s), (cx - 36 * s, f - 108 * s), 7 * s, p.coat)
    circle(img, cx - 36 * s, f - 104 * s, 6 * s, p.skin)
    # правая рука: от пояса к лицу
    sh = (cx + 28 * s, f - 182 * s)
    rest = (cx + 36 * s, f - 106 * s)
    target = hand_target or p.mouth(t)
    k = 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, raise_)))
    hand = (rest[0] + (target[0] + 4 * s - rest[0]) * k, rest[1] + (target[1] + 4 * s - rest[1]) * k)
    elbow = ((sh[0] + hand[0]) / 2 + 16 * s * k + 4 * s, (sh[1] + hand[1]) / 2 + 22 * s * k)
    capsule(img, sh, elbow, 7 * s, p.coat)
    capsule(img, elbow, hand, 6.5 * s, p.coat)
    circle(img, hand[0], hand[1], 6 * s, p.skin)
    return hand


def blur_face(img, p: Person, t: float):
    hx, hy, r = p.head(t)
    mosaic(img, hx - r * 1.1, hy - r * 1.2, hx + r * 1.1, hy + r * 1.1, block=r * 0.55)


class Puffs:
    def __init__(self):
        self.items = []  # [x, y, r, alpha, vx, vy, grow, fade]

    def emit(self, x, y, r, alpha, vx, vy, grow, fade):
        self.items.append([x, y, r, alpha, vx, vy, grow, fade])

    def step(self, img, dt):
        alive = []
        for it in self.items:
            x, y, r, a, vx, vy, g, fd = it
            circle(img, x, y, r, (235, 236, 238), alpha=max(0.0, a), soft=r * 0.8)
            it[0] += vx * dt
            it[1] += vy * dt
            it[2] += g * dt
            it[3] -= fd * dt
            if it[3] > 0.02:
                alive.append(it)
        self.items = alive


def raise_curve(t, period, hold, offset=0.0):
    """Периодически подносит руку ко рту: 0 → 1 → удержание → 0."""
    ph = ((t + offset) % period) / period
    up, down = 0.18, 0.18
    h = hold / period
    if ph < up:
        return ph / up
    if ph < up + h:
        return 1.0
    if ph < up + h + down:
        return 1 - (ph - up - h) / down
    return 0.0


# --- сценарии --------------------------------------------------------------

COATS = [(120, 60, 55), (60, 85, 120), (70, 95, 70), (150, 120, 70), (90, 90, 95), (130, 100, 130), (40, 45, 60)]


def render(kind: str, rnd: random.Random, dur: float, path: Path) -> list[dict]:
    scene = Scene(cold=kind == "breath", dark=kind == "dark")
    bg = background(rnd, scene)
    s = rnd.uniform(0.95, 1.2) if kind != "dark" else 0.62
    target = Person(cx=rnd.uniform(200, 440), feet=rnd.uniform(400, 440) if kind != "dark" else 350,
                    s=s, coat=rnd.choice(COATS), walk=rnd.choice([0, 0, 0, rnd.uniform(-10, 10)]))
    if kind == "breath":
        target.coat = rnd.choice([(40, 45, 60), (110, 40, 40)])
    others = []
    for _ in range(rnd.randint(1, 2)):
        x0 = rnd.choice([-40, W + 40])
        others.append(Person(cx=x0, feet=rnd.uniform(320, 345), s=0.55, coat=rnd.choice(COATS),
                             walk=rnd.uniform(35, 60) * (1 if x0 < 0 else -1)))
    neighbor = None
    if kind == "neighbor":
        side = 1 if target.cx < W / 2 else -1
        neighbor = Person(cx=target.cx + side * 150, feet=target.feet - 15, s=target.s * 0.95, coat=rnd.choice(COATS))
    car_dir = rnd.choice([1, -1])
    car_speed = rnd.uniform(120, 200)
    car_x0 = -220 if car_dir > 0 else W + 20
    car_col = rnd.choice([(170, 40, 40), (40, 60, 120), (200, 200, 200), (30, 30, 30)])
    puffs = Puffs()
    period = rnd.uniform(2.6, 3.4)
    offset = rnd.uniform(0, 1.2)
    noise_rng = np.random.default_rng(rnd.randint(0, 99999))

    proc = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "31",
         "-profile:v", "main", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)],
        stdin=subprocess.PIPE,
    )
    track = []
    frames = int(round(dur * FPS))
    prev_raise = 0.0
    for i in range(frames):
        t = i / FPS
        img = bg.copy()
        # машина с размытым номером
        cxp = car_x0 + car_dir * car_speed * t
        rect(img, cxp, 232, cxp + 200, 270, car_col)
        rect(img, cxp + 40, 212, cxp + 150, 236, car_col)
        rect(img, cxp + 50, 216, cxp + 140, 232, (150, 180, 200))
        circle(img, cxp + 40, 272, 13, (25, 25, 25))
        circle(img, cxp + 160, 272, 13, (25, 25, 25))
        plate_x = cxp + (180 if car_dir > 0 else 5)
        rect(img, plate_x, 254, plate_x + 18, 262, (240, 240, 240))
        rect(img, plate_x + 3, 256, plate_x + 15, 260, (20, 20, 20))
        mosaic(img, plate_x - 2, 252, plate_x + 20, 264, 6)

        for o in others:
            draw_person(img, o, t)
            blur_face(img, o, t)

        hand_target = None
        r = 0.0
        if kind in ("cig", "vape", "drink"):
            r = raise_curve(t, period, 0.6 if kind == "cig" else 0.8, offset)
        elif kind == "phone":
            r = min(1.0, 0.3 + t / 0.6)
            hx, hy, hr = target.head(t)
            hand_target = (hx + hr * 0.9, hy)
        elif kind == "scratch":
            r = raise_curve(t, period * 1.2, 1.2, offset)
            hx, hy, hr = target.head(t)
            hand_target = (hx + hr * 0.8 + 3 * math.sin(t * 25), hy - hr * 0.1)
        elif kind == "dark":
            r = raise_curve(t, period, 0.7, offset) * 0.85

        hand = draw_person(img, target, t, r, hand_target)
        s = target.s
        mx, my = target.mouth(t)
        if kind == "cig":
            tip = (hand[0] + 13 * s, hand[1] - 3 * s)
            capsule(img, (hand[0] + 2 * s, hand[1] - 1 * s), tip, 1.6 * s, (245, 242, 235))
            glow = 1.0 if r > 0.95 else 0.55
            circle(img, tip[0], tip[1], 2.2 * s, (255, int(120 + 60 * glow), 40), alpha=0.9)
            if i % 3 == 0:
                puffs.emit(tip[0], tip[1] - 2, 2.5 * s, 0.35, rnd.uniform(-4, 4), -22, 6, 0.25)
            if prev_raise > 0.9 and r < prev_raise:  # выдох после затяжки
                for _ in range(3):
                    puffs.emit(mx + 6 * s, my, rnd.uniform(4, 7) * s, 0.55, rnd.uniform(14, 26), rnd.uniform(-14, -4), 10 * s, 0.45)
        elif kind == "vape":
            rect(img, hand[0] - 3 * s, hand[1] - 12 * s, hand[0] + 4 * s, hand[1] + 4 * s, (35, 35, 40))
            circle(img, hand[0], hand[1] - 11 * s, 1.5 * s, (90, 160, 255), alpha=0.9 if r > 0.9 else 0.3)
            if prev_raise > 0.9 and r < prev_raise:
                for _ in range(6):
                    puffs.emit(mx + 6 * s, my, rnd.uniform(8, 13) * s, 0.75, rnd.uniform(20, 45), rnd.uniform(-20, 5), 30 * s, 0.7)
        elif kind == "phone":
            rect(img, hand[0] - 4 * s, hand[1] - 14 * s, hand[0] + 5 * s, hand[1] + 6 * s, (25, 25, 30))
        elif kind == "drink":
            rect(img, hand[0] - 5 * s, hand[1] - 16 * s, hand[0] + 6 * s, hand[1] + 2 * s, (240, 238, 230))
            rect(img, hand[0] - 5 * s, hand[1] - 16 * s, hand[0] + 6 * s, hand[1] - 12 * s, (90, 60, 40))
        elif kind == "breath" and i % 18 == 0:
            for _ in range(2):
                puffs.emit(mx + 4 * s, my, rnd.uniform(3, 5) * s, 0.5, rnd.uniform(8, 16), rnd.uniform(-6, 0), 9 * s, 0.9)
        if neighbor is not None:
            nr = raise_curve(t, 2.8, 0.6, 0.4)
            nh = draw_person(img, neighbor, t, nr)
            tip = (nh[0] + 12 * neighbor.s, nh[1] - 3 * neighbor.s)
            capsule(img, (nh[0] + 2, nh[1] - 1), tip, 1.5 * neighbor.s, (245, 242, 235))
            circle(img, tip[0], tip[1], 2 * neighbor.s, (255, 150, 40))
            if i % 3 == 0:
                puffs.emit(tip[0], tip[1] - 2, 2.5, 0.35, rnd.uniform(-4, 4), -22, 6, 0.25)
            blur_face(img, neighbor, t)
        prev_raise = r
        puffs.step(img, 1 / FPS)
        blur_face(img, target, t)

        if scene.dark:
            img *= 0.32
            img += noise_rng.normal(0, 7, img.shape).astype(np.float32)
        else:
            img += noise_rng.normal(0, 2, img.shape).astype(np.float32)
        proc.stdin.write(np.clip(img, 0, 255).astype(np.uint8).tobytes())

        if i % (FPS // 3) == 0 or i == frames - 1:
            x0, y0, x1, y1 = target.bbox(t)
            x0, y0 = max(0.0, x0 / W), max(0.0, y0 / H)
            x1, y1 = min(1.0, x1 / W), min(1.0, y1 / H)
            track.append({"t": round(t, 3), "x": round(x0, 4), "y": round(y0, 4),
                          "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)})
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for {path}")
    return track


TRUTH = {"cig": "cig", "vape": "vape", "phone": "no", "scratch": "no", "drink": "no",
         "breath": "no", "neighbor": "no", "dark": "unsure"}

GOLD = {
    "cig": {"ru": "У рта видна тонкая светлая сигарета с тлеющим кончиком, после затяжки — дым.",
            "en": "A thin light cigarette with a glowing tip is visible at the mouth; smoke after the drag."},
    "vape": {"ru": "В руке небольшое тёмное устройство, после затяжки — густое облако, которое быстро тает. Это вейп.",
             "en": "A small dark device in the hand and a thick cloud that quickly fades. That is a vape."},
    "phone": {"ru": "Человек держит у уха телефон. Предмет крупный и прямоугольный, дыма нет.",
              "en": "The person holds a phone to the ear. The object is large and rectangular, no smoke."},
    "breath": {"ru": "Это пар от дыхания на морозе: у рта нет никакого предмета. Такие случаи — «Не курит».",
               "en": "This is breath vapour in the cold: there is no object at the mouth. Answer “Not smoking”."},
    "neighbor": {"ru": "Курит сосед, а человек в рамке — нет. Отвечай только про человека в рамке.",
                 "en": "The neighbour smokes, the person in the box does not. Answer only about the boxed person."},
}

PLAN = (
    [("cig", True), ("cig", True)] + [("cig", False)] * 5
    + [("vape", True)] + [("vape", False)] * 5
    + [("phone", True)] + [("phone", False)] * 3
    + [("scratch", False)] * 3 + [("drink", False)] * 3
    + [("breath", True)] + [("breath", False)] * 2
    + [("neighbor", True)] + [("neighbor", False)]
    + [("dark", False)] * 2
)

STOPS = [
    {"id": "1284", "name": "Парк Победы", "region": "central"},
    {"id": "0917", "name": "Площадь Мира", "region": "central"},
    {"id": "2041", "name": "Университет", "region": "central"},
    {"id": "3310", "name": "Речной вокзал", "region": "north"},
    {"id": "3315", "name": "Улица Гагарина", "region": "north"},
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(2024)
    clips = []
    for i, (kind, is_gold) in enumerate(PLAN, 1):
        ext = f"demo_{i:03d}"
        dur = rnd.choice([3.0, 3.5, 4.0, 4.5, 5.0])
        path = OUT / f"{ext}.mp4"
        track = render(kind, rnd, dur, path)
        entry = {
            "external_id": ext, "file": f"clips/{ext}.mp4", "duration_ms": int(dur * 1000),
            "width": W, "height": H, "bbox": track, "region": rnd.choice([None, "central", "north"]),
            "truth": TRUTH[kind], "scenario": kind,
        }
        if is_gold:
            entry["gold"] = {"answer": TRUTH[kind], "explanation": GOLD[kind]}
        clips.append(entry)
        print(f"{ext} {kind:9s} gold={is_gold!s:5s} {path.stat().st_size // 1024} КБ")
    (ROOT / "manifest.json").write_text(
        json.dumps({"stops": STOPS, "clips": clips}, ensure_ascii=False, indent=1), encoding="utf-8")

    EXAMPLE.parent.mkdir(parents=True, exist_ok=True)
    track = render("cig", random.Random(99), 4.0, EXAMPLE)
    (ROOT.parent.parent / "frontend" / "src" / "example-clip.json").write_text(json.dumps({"duration_ms": 4000, "width": W, "height": H, "bbox": track}))
    print(f"example.mp4 {EXAMPLE.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()
