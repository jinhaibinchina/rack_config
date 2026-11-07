"""路线 C 量化基准：原生 QGraphicsScene vs 当前自绘管线。

每个 phase 独占一个进程、只持有一个场景，避免同进程多场景互相污染绝对值。
必须在项目根目录用 .venv 运行：

    .venv/Scripts/python.exe tools/bench_qgraphics_scene.py --phase dump
    .venv/Scripts/python.exe tools/bench_qgraphics_scene.py --phase self
    .venv/Scripts/python.exe tools/bench_qgraphics_scene.py --phase qgs --kind native
    .venv/Scripts/python.exe tools/bench_qgraphics_scene.py --phase qgs --kind pypaint
    .venv/Scripts/python.exe tools/bench_qgraphics_scene.py --phase qgs --kind cache

口径同 tools/bench_scene.py：逐次计时取最小值、多轮交错并轮转顺序。
跨进程绝对值仍有 ±30% 的 CPU 调频噪声，**结论以同进程比值为主**
（可用 --phase qgs 与 --phase self 的结果两两相除复核）。

注意：QGS 侧用矩形近似全部 1618 个图元，而当前自绘 paint 含旋转、文本、
图片、widget、选中框，故 QGS 数字是理想化下限；评估迁移收益时应看
`pypaint`（保留 Python 绘制回调）一列，且仍需为复杂图元再打折。
"""
import argparse
import gc
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QGraphicsScene, QGraphicsRectItem, QGraphicsItem,
)
from PySide6.QtCore import Qt, QRectF, QPointF  # noqa: E402
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QBrush  # noqa: E402

app = QApplication([])
PAGE = "Designer/Core/data.json/datas/design/pages/page_1.json"
DUMP = "build/qgs_rects.json"
W, H = 1440, 900

PEN = QPen(QColor(0, 180, 0), 2)
BRUSH = QBrush(QColor(230, 230, 230))

ap = argparse.ArgumentParser()
ap.add_argument("--phase", choices=("dump", "qgs", "self", "ab"), default="qgs")
ap.add_argument("--kind", choices=("native", "pypaint", "cache"), default="native")
args = ap.parse_args()


class PyItem(QGraphicsItem):
    """保留 Python paint 回调，模拟「只换框架不换图元」。"""

    def __init__(self, r):
        super().__init__()
        self._r = QRectF(0, 0, max(1.0, r.width()), max(1.0, r.height()))
        self.setPos(r.topLeft())
        self._pen = QPen(PEN)
        self._brush = QBrush(BRUSH)

    def boundingRect(self):
        return self._r

    def paint(self, painter, option, widget=None):
        painter.setPen(self._pen)
        painter.setBrush(self._brush)
        painter.drawRect(self._r)


if args.phase == "dump":
    from Designer.Core.myQuadTreeScene import QuadTreeScene, SceneManager
    s = QuadTreeScene()
    s.resize(W, H)
    s.setSceneRect(QRectF(QPointF(-50000, -50000), QPointF(50000, 50000)))
    s.set_scene_manager(SceneManager(s))
    s.show()
    s.load_element_info(PAGE)
    out = []
    for it in s.scene_manager.m_sorted_items:
        b = it.sceneBoundingRect()
        if b.isNull() or b.isEmpty():
            continue
        v = s.rect_sceneToView(b)
        if v.isNull() or v.isEmpty():
            continue
        out.append([v.left(), v.top(), v.width(), v.height()])
    with open(DUMP, "w", encoding="utf-8") as f:
        json.dump({"rects": out, "items": len(s.scene_manager.m_sorted_items)}, f)
    print(f"dumped {len(out)} rects -> {DUMP}")
    raise SystemExit(0)

# ---------------- phase self（独立进程，与 qgs 同口径） ----------------
if args.phase == "self":
    from PySide6.QtGui import QRegion
    from Designer.Core.myQuadTreeScene import QuadTreeScene, SceneManager
    s = QuadTreeScene()
    s.resize(W, H)
    s.setSceneRect(QRectF(QPointF(-50000, -50000), QPointF(50000, 50000)))
    s.set_scene_manager(SceneManager(s))
    s.show()
    s.load_element_info(PAGE)
    self_sizes = [
        ("全屏1440x900", QRectF(0, 0, W, H)),
        ("中400x300", QRectF(400, 260, 400, 300)),
        ("小240x180", QRectF(400, 300, 240, 180)),
        ("微80x60", QRectF(500, 350, 80, 60)),
    ]
    self_cases = {}
    for tag, r in self_sizes:
        rg = QRegion(int(r.left()), int(r.top()), int(r.width()), int(r.height()))
        self_cases[f"refresh·{tag}"] = lambda rg=rg: s.refresh_dynamic_buffer(rg)
    sc_rect = s._scene_rect_for_region(QRegion(400, 300, 240, 180))
    its = list(s.scene_manager.m_sorted_items)
    self_cases["线性命中·小240x180"] = lambda: [
        it for it in its if it.sceneBoundingRect().intersects(sc_rect)
    ]
    self_cases["sceneTransform walk"] = lambda: [
        it.sceneTransform().map(QPointF(0.0, 0.0)) for it in its
    ]
    for _ in range(5):
        for fn in self_cases.values():
            fn()
    names = list(self_cases)
    best = {k: float("inf") for k in names}
    for rnd in range(20):
        order = names[rnd % len(names):] + names[:rnd % len(names)]
        for name in order:
            t = time.perf_counter()
            self_cases[name]()
            dt = (time.perf_counter() - t) * 1000.0
            if dt < best[name]:
                best[name] = dt
    print(f"items={len(its)}  min-of-20 (ms)")
    for name, v in best.items():
        print(f"  {name:28s} {v:8.3f}")
    raise SystemExit(0)

# ---------------- phase ab（同进程交错，结论以此为准） ----------------
if args.phase == "ab":
    from PySide6.QtGui import QRegion
    from Designer.Core.myQuadTreeScene import QuadTreeScene, SceneManager

    with open(DUMP, encoding="utf-8") as f:
        _d = json.load(f)
    _rects = [QRectF(*r) for r in _d["rects"]]

    s = QuadTreeScene()
    s.resize(W, H)
    s.setSceneRect(QRectF(QPointF(-50000, -50000), QPointF(50000, 50000)))
    s.set_scene_manager(SceneManager(s))
    s.show()
    s.load_element_info(PAGE)

    gs = QGraphicsScene()
    gs.setItemIndexMethod(QGraphicsScene.BspTreeIndex)
    for r in _rects:
        if args.kind == "pypaint":
            it = PyItem(r)
        else:
            it = QGraphicsRectItem(QRectF(0, 0, max(1.0, r.width()), max(1.0, r.height())))
            it.setPos(r.topLeft())
            it.setPen(QPen(PEN))
            it.setBrush(QBrush(BRUSH))
            if args.kind == "cache":
                it.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        gs.addItem(it)

    def _render(source):
        target = QRectF(0, 0, source.width(), source.height())
        img = QImage(int(source.width()), int(source.height()),
                     QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.white)

        def fn():
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            gs.render(p, target, source)
            p.end()

        return fn

    ab_sizes = [
        ("全屏1440x900", QRectF(0, 0, W, H)),
        ("中400x300", QRectF(400, 260, 400, 300)),
        ("小240x180", QRectF(400, 300, 240, 180)),
        ("微80x60", QRectF(500, 350, 80, 60)),
    ]
    ab_cases = {}
    for tag, r in ab_sizes:
        rg = QRegion(int(r.left()), int(r.top()), int(r.width()), int(r.height()))
        ab_cases[f"self·{tag}"] = lambda rg=rg: s.refresh_dynamic_buffer(rg)
        ab_cases[f"qgs·{tag}"] = _render(r)

    # 同轮地板：用于确认 CPU 状态漂移，不参与比值计算
    floor_img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    floor_rects = [QRectF(10 + (i % 40) * 34, 10 + (i // 40) * 28, 30, 24)
                   for i in range(1205)]

    def floor():
        p = QPainter(floor_img)
        p.setPen(QPen(QColor(0, 180, 0), 2))
        p.setBrush(QColor(230, 230, 230))
        p.drawRects(floor_rects)
        p.end()

    ab_cases["floor"] = floor

    for _ in range(5):
        for fn in ab_cases.values():
            fn()
    names = list(ab_cases)
    best = {k: float("inf") for k in names}
    for rnd in range(20):
        order = names[rnd % len(names):] + names[:rnd % len(names)]
        for name in order:
            t = time.perf_counter()
            ab_cases[name]()
            dt = (time.perf_counter() - t) * 1000.0
            if dt < best[name]:
                best[name] = dt

    print(f"同进程交错 min-of-20, kind={args.kind}  floor={best['floor']:.3f} ms")
    print(f"{'脏区':16s} {'自绘(ms)':>10s} {'QGS(ms)':>10s} {'QGS/自绘':>10s} {'降幅':>8s}")
    for tag, _ in ab_sizes:
        a, b = best[f"self·{tag}"], best[f"qgs·{tag}"]
        print(f"{tag:16s} {a:10.3f} {b:10.3f} {b / a * 100:9.1f}% {(1 - b / a) * 100:7.0f}%")
    raise SystemExit(0)

# ---------------- phase qgs ----------------
with open(DUMP, encoding="utf-8") as f:
    data = json.load(f)
rects = [QRectF(*r) for r in data["rects"]]
visible = sum(1 for r in rects if r.intersects(QRectF(0, 0, W, H)))
print(f"items={data['items']}  rects={len(rects)}  视口内={visible}  kind={args.kind}")


gs = QGraphicsScene()
gs.setItemIndexMethod(QGraphicsScene.BspTreeIndex)
for r in rects:
    if args.kind == "pypaint":
        it = PyItem(r)
    else:
        it = QGraphicsRectItem(QRectF(0, 0, max(1.0, r.width()), max(1.0, r.height())))
        it.setPos(r.topLeft())
        it.setPen(QPen(PEN))
        it.setBrush(QBrush(BRUSH))
        if args.kind == "cache":
            it.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
    gs.addItem(it)

SIZES = [
    ("全屏1440x900", QRectF(0, 0, W, H)),
    ("中400x300", QRectF(400, 260, 400, 300)),
    ("小240x180", QRectF(400, 300, 240, 180)),
    ("微80x60", QRectF(500, 350, 80, 60)),
]


def make_render(source):
    target = QRectF(0, 0, source.width(), source.height())
    img = QImage(int(source.width()), int(source.height()),
                 QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.white)

    def fn():
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        gs.render(p, target, source)
        p.end()

    return fn


cases = {}
for tag, rect in SIZES:
    cases[f"render·{tag}"] = make_render(rect)
cases["BSP命中·小240x180"] = lambda: gs.items(
    SIZES[2][1], Qt.IntersectsItemBoundingRect)

moved = gs.items()[len(gs.items()) // 2]
mid_render = cases["render·中400x300"]


def move_and_render():
    moved.moveBy(1.0, 1.0)
    mid_render()


cases["移动1项+中400x300重绘"] = move_and_render

for _ in range(5):
    for fn in cases.values():
        fn()

ROUNDS = 20
names = list(cases)
best = {k: float("inf") for k in names}
for rnd in range(ROUNDS):
    order = names[rnd % len(names):] + names[:rnd % len(names)]
    for name in order:
        t = time.perf_counter()
        cases[name]()
        dt = (time.perf_counter() - t) * 1000.0
        if dt < best[name]:
            best[name] = dt

print(f"min-of-{ROUNDS} (ms)")
for name, v in best.items():
    print(f"  {name:28s} {v:8.3f}")

# 像素抽样确认确实画了内容
img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
img.fill(Qt.white)
p = QPainter(img)
gs.render(p, QRectF(0, 0, W, H), QRectF(0, 0, W, H))
p.end()
white = QColor(Qt.white)
nonwhite = sum(1 for y in range(0, H, 4) for x in range(0, W, 4)
               if img.pixelColor(x, y) != white)
print(f"非白采样点 {nonwhite}/{(H // 4) * (W // 4)}")
for tag, rect in SIZES:
    print(f"  BSP命中数 {tag:12s}: {len(gs.items(rect, Qt.IntersectsItemBoundingRect))}")
del gs
gc.collect()
