"""组态引擎场景热路径基准脚本。

用真实设计页数据（默认 ``page_1.json``，1600+ 图元）量化：

1. ``on_mouse_move`` —— 每次鼠标移动都会执行，是交互卡顿的直接来源；
2. 四叉树结构健康度 —— 存储条目数远大于图元数说明同一图元被重复挂载；
3. ``--breakdown`` —— 把一帧拆成「Python 簿记 / 逐图元 paint / 光栅化地板」，
   作为后续 C 化的对照组基线。

``--ab`` 在**同一进程、同一场景**里交替开关 ``RACK_SCENE_FAST`` 做 A/B。
Windows 上 CPU 调频/后台负载会让两段测量整体漂移（实测控件指标都能差
40%），所以每个指标都按 off/on 交错取样、各取最快值，而不是整段跑完再比。

用法::

    .venv/Scripts/python.exe tools/bench_scene.py
    .venv/Scripts/python.exe tools/bench_scene.py --page <path> --moves 200
    .venv/Scripts/python.exe tools/bench_scene.py --breakdown --save build/bench_before.json
    .venv/Scripts/python.exe tools/bench_scene.py --ab --save build/bench_ab.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPen, QRegion  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from Designer.Core import scene_fast  # noqa: E402
from Designer.Core.elements import base_element  # noqa: E402
from Designer.Core.myQuadTreeScene import QuadTreeScene, SceneManager  # noqa: E402

DEFAULT_PAGE = os.path.join(
    _PROJECT_ROOT, "Designer", "Core", "data.json", "datas", "design", "pages", "page_1.json"
)


def build_scene(page_path: str) -> QuadTreeScene:
    scene = QuadTreeScene()
    scene.resize(1440, 900)
    scene.setSceneRect(QRectF(QPointF(-50000.0, -50000.0), QPointF(50000.0, 50000.0)))
    manager = SceneManager(scene)
    scene.set_scene_manager(manager)
    scene.show()
    scene.load_element_info(page_path)
    return scene


def quadtree_stats(scene: QuadTreeScene) -> tuple:
    """返回 (节点数, 最大深度, 存储条目数)。"""

    if not scene.quadtree:
        return 0, 0, 0

    nodes = 0
    max_depth = 0
    entries = 0
    stack = [(scene.quadtree, 0)]
    while stack:
        node, depth = stack.pop()
        nodes += 1
        max_depth = max(max_depth, depth)
        entries += len(node.items)
        if node.divided:
            for child in (node.nw, node.ne, node.sw, node.se):
                if child is not None:
                    stack.append((child, depth + 1))
    return nodes, max_depth, entries


# --- 计时 -------------------------------------------------------------------
# 逐次计时取最小值：代表「无干扰时这段代码本身要多久」，比均值稳定得多。

def _once_ms(fn) -> float:
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000.0


def bench(fn, n: int = 10) -> float:
    return min(_once_ms(fn) for _ in range(n))


def bench_ab(fn, n: int = 8) -> tuple[float, float]:
    """交错测量 FAST=0/1，返回各自最快值。"""
    off = on = float("inf")
    for i in range(n):
        order = (False, True) if i % 2 == 0 else (True, False)
        for flag in order:
            scene_fast.set_enabled(flag)
            dt = _once_ms(fn)
            if flag:
                on = min(on, dt)
            else:
                off = min(off, dt)
    return off, on


def measure_moves(scene: QuadTreeScene, moves: int) -> float:
    scene.on_mouse_move(QPointF(0.0, 0.0))  # 预热
    best = float("inf")
    for step in range(moves):
        dt = _once_ms(lambda: scene.on_mouse_move(QPointF(100.0 + step * 3.0, 100.0 + step * 2.0)))
        best = min(best, dt)
    return best


def measure_moves_ab(scene: QuadTreeScene, n: int = 40) -> tuple[float, float]:
    scene.on_mouse_move(QPointF(0.0, 0.0))
    off = on = float("inf")
    for i in range(n):
        order = (False, True) if i % 2 == 0 else (True, False)
        for flag in order:
            scene_fast.set_enabled(flag)
            dt = _once_ms(lambda: scene.on_mouse_move(QPointF(100.0 + i * 3.0, 100.0 + i * 2.0)))
            if flag:
                on = min(on, dt)
            else:
                off = min(off, dt)
    return off, on


def measure_find_children(scene: QuadTreeScene, rounds: int = 20) -> float:
    scene.findChildren(base_element)  # 预热
    return min(_once_ms(lambda: scene.findChildren(base_element)) for _ in range(rounds))


# --- 分层用例 ---------------------------------------------------------------

@contextmanager
def _stub_paint(classes):
    """临时把所有图元 paint 换成空函数，测「纯簿记」那一段。"""
    saved = {cls: cls.__dict__.get("paint") for cls in classes}
    try:
        for cls in classes:
            cls.paint = lambda self, painter, shine_flag: None
        yield
    finally:
        for cls, own in saved.items():
            if own is None:
                if "paint" in cls.__dict__:
                    delattr(cls, "paint")
            else:
                cls.paint = own


def breakdown_cases(scene: QuadTreeScene) -> tuple[dict, dict]:
    """构造各项待测函数；返回 (cases, meta)。

    ``bookkeeping`` 用例自带 paint 置空的上下文，因此可以和其它用例一样
    被 ``bench`` / ``bench_ab`` 反复交错调用。
    """
    region = QRegion(0, 0, scene.width(), scene.height())
    for _ in range(3):  # 预热：字体/图片/位图缓冲区首帧特别慢
        scene.refresh_dynamic_buffer(region)

    classes = {type(item) for item in scene.scene_manager.m_sorted_items}
    items = list(scene.scene_manager.m_sorted_items)

    def frame_full() -> None:
        scene.refresh_dynamic_buffer(region)

    def bookkeeping() -> None:
        with _stub_paint(classes):
            scene.refresh_dynamic_buffer(region)

    def bbox_loop() -> None:
        scene_rect = scene._scene_rect_for_region(region)
        for child in items:
            child.set_dirty_region(region)
            bound = child.sceneBoundingRect()
            if not bound.isNull() and not bound.intersects(scene_rect):
                continue

    rect_count = sum(1 for item in items if type(item).__name__ == "rect_element") or 1200
    rects = [
        QRectF(10 + (i % 40) * 34, 10 + (i // 40) * 28, 30, 24)
        for i in range(rect_count)
    ]
    dyn = scene.dynamic_buffer

    def raster_batch() -> None:
        p = QPainter(dyn)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(0, 180, 0), 2))
        p.setBrush(QColor(230, 230, 230))
        p.drawRects(rects)
        p.end()

    def raster_per_item_pen() -> None:
        p = QPainter(dyn)
        p.setRenderHint(QPainter.Antialiasing)
        for r in rects:
            p.setPen(QPen(QColor(0, 180, 0), 2))
            p.setBrush(QColor(230, 230, 230))
            p.drawRect(r)
        p.end()

    def transform_walk() -> None:
        for item in items:
            item.sceneTransform().map(QPointF(0.0, 0.0))

    cases = {
        "frame_full_ms": frame_full,
        "bookkeeping_ms": bookkeeping,
        "bbox_loop_ms": bbox_loop,
        "raster_floor_ms": raster_batch,
        "raster_per_item_pen_ms": raster_per_item_pen,
        "transform_walk_ms": transform_walk,
    }
    meta = {"rect_count": rect_count, "transform_walk_items": len(items)}
    return cases, meta


def _finalize(values: dict, meta: dict) -> dict:
    out = dict(values)
    out.update(meta)
    out["paint_net_ms"] = max(0.0, out["frame_full_ms"] - out["bookkeeping_ms"])
    return out


def breakdown(scene: QuadTreeScene) -> dict:
    cases, meta = breakdown_cases(scene)
    return _finalize({k: bench(fn) for k, fn in cases.items()}, meta)


def breakdown_ab(scene: QuadTreeScene) -> tuple[dict, dict]:
    cases, meta = breakdown_cases(scene)
    pairs = {k: bench_ab(fn) for k, fn in cases.items()}
    return (
        _finalize({k: v[0] for k, v in pairs.items()}, meta),
        _finalize({k: v[1] for k, v in pairs.items()}, meta),
    )


def print_breakdown(b: dict) -> None:
    print("\n--- 分层基线（同一进程、同一场景）---")
    print(f"一帧 refresh_dynamic_buffer    : {b['frame_full_ms']:7.2f} ms")
    print(f"  ├ 纯 Python 簿记（paint 置空） : {b['bookkeeping_ms']:7.2f} ms")
    print(f"  └ 图元 paint 净耗时           : {b['paint_net_ms']:7.2f} ms")
    print(f"  其中仅 bbox 剔除循环          : {b['bbox_loop_ms']:7.2f} ms")
    print(f"光栅化地板（{b['rect_count']} 矩形批量 drawRects） : {b['raster_floor_ms']:7.2f} ms")
    print(f"逐图元 new QPen/QColor 的对照   : {b['raster_per_item_pen_ms']:7.2f} ms")
    print(
        f"变换链 walk（{b['transform_walk_items']} 图元各 1 次）   : "
        f"{b['transform_walk_ms']:7.2f} ms  "
        f"({b['transform_walk_ms'] / max(b['transform_walk_items'], 1) * 1000:.2f} us/item)"
    )


def print_ab(off: dict, on: dict, move_pair: tuple[float, float]) -> None:
    rows = [
        ("on_mouse_move (ms/次)", *move_pair),
        ("一帧 refresh_dynamic_buffer", off["frame_full_ms"], on["frame_full_ms"]),
        ("  ├ Python 簿记", off["bookkeeping_ms"], on["bookkeeping_ms"]),
        ("  └ 图元 paint 净耗时", off["paint_net_ms"], on["paint_net_ms"]),
        ("  bbox 剔除循环", off["bbox_loop_ms"], on["bbox_loop_ms"]),
        ("[对照] 光栅化地板", off["raster_floor_ms"], on["raster_floor_ms"]),
        ("[对照] 变换链 walk", off["transform_walk_ms"], on["transform_walk_ms"]),
    ]
    print("\n--- A/B（同一进程、同一场景，off/on 交错取样各取最快）---")
    print(f"{'指标':<30}{'FAST=0':>10}{'FAST=1':>10}{'变化':>10}")
    for name, a, b in rows:
        delta = (b - a) / a * 100.0 if a else 0.0
        print(f"{name:<30}{a:>10.2f}{b:>10.2f}{delta:>9.1f}%")
    print("[对照] 两行与开关无关，越接近 0% 说明本次测量噪声越小。")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", default=DEFAULT_PAGE)
    parser.add_argument("--moves", type=int, default=100)
    parser.add_argument("--breakdown", action="store_true", help="输出分层耗时基线")
    parser.add_argument("--ab", action="store_true", help="同进程交错 A/B 对比 RACK_SCENE_FAST")
    parser.add_argument("--save", default="", help="把结果保存成 JSON")
    args = parser.parse_args()

    QApplication.instance() or QApplication([])

    start = time.perf_counter()
    scene = build_scene(args.page)
    build_ms = (time.perf_counter() - start) * 1000.0

    item_count = len(scene.scene_manager.m_items)
    nodes, depth, entries = quadtree_stats(scene)

    data = {
        "page": os.path.basename(args.page),
        "items": item_count,
        "load_ms": build_ms,
        "quadtree_nodes": nodes,
        "quadtree_depth": depth,
        "quadtree_entries": entries,
        "quadtree_duplication": entries / max(item_count, 1),
        "moves": args.moves,
        "fast_enabled": bool(scene_fast.ENABLED),
    }

    print(f"page             : {data['page']}")
    print(f"items            : {item_count}")
    print(f"load time        : {build_ms:.1f} ms")
    print(f"quadtree nodes   : {nodes}")
    print(f"quadtree depth   : {depth}")
    print(f"quadtree entries : {entries}  (duplication x{data['quadtree_duplication']:.2f})")

    if args.ab:
        move_pair = measure_moves_ab(scene)
        off, on = breakdown_ab(scene)
        scene_fast.set_enabled(True)
        data["find_children_ms"] = measure_find_children(scene)
        data["on_mouse_move_ms"] = move_pair[1]
        print(f"findChildren     : {data['find_children_ms']:.3f} ms/call")
        print(f"on_mouse_move    : {move_pair[1]:.3f} ms/call (FAST=1)")
        print_breakdown(on)
        print_ab(off, on, move_pair)
        data["ab"] = {"fast_off": off, "fast_on": on, "on_mouse_move": list(move_pair)}
    else:
        data["find_children_ms"] = measure_find_children(scene)
        data["on_mouse_move_ms"] = measure_moves(scene, args.moves)
        print(f"findChildren     : {data['find_children_ms']:.3f} ms/call")
        print(f"on_mouse_move    : {data['on_mouse_move_ms']:.3f} ms/call")
        if args.breakdown:
            data["breakdown"] = breakdown(scene)
            print_breakdown(data["breakdown"])

    if args.save:
        out_dir = os.path.dirname(os.path.abspath(args.save))
        os.makedirs(out_dir, exist_ok=True)
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\nsaved            : {args.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
