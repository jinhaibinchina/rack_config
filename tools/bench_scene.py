"""组态引擎鼠标热路径基准脚本。

用真实设计页数据（默认 ``page_1.json``，1600+ 图元）量化两件事：

1. ``on_mouse_move`` —— 每次鼠标移动都会执行，是交互卡顿的直接来源；
2. 四叉树结构健康度 —— 存储条目数远大于图元数说明同一图元被重复挂载。

用法::

    .venv/Scripts/python.exe tools/bench_scene.py
    .venv/Scripts/python.exe tools/bench_scene.py --page <path> --moves 200
"""

from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

from Designer.Core.elements import base_element
from Designer.Core.myQuadTreeScene import QuadTreeScene, SceneManager

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


def measure_moves(scene: QuadTreeScene, moves: int) -> float:
    """返回每次 on_mouse_move 的平均耗时（毫秒）。"""

    scene.on_mouse_move(QPointF(0.0, 0.0))  # 预热
    start = time.perf_counter()
    for step in range(moves):
        scene.on_mouse_move(QPointF(100.0 + step * 3.0, 100.0 + step * 2.0))
    elapsed = time.perf_counter() - start
    return elapsed / moves * 1000.0


def measure_find_children(scene: QuadTreeScene, rounds: int = 20) -> float:
    """返回一次 findChildren(base_element) 的平均耗时（毫秒）。"""

    scene.findChildren(base_element)  # 预热
    start = time.perf_counter()
    for _ in range(rounds):
        scene.findChildren(base_element)
    return (time.perf_counter() - start) / rounds * 1000.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", default=DEFAULT_PAGE)
    parser.add_argument("--moves", type=int, default=100)
    args = parser.parse_args()

    QApplication.instance() or QApplication([])

    start = time.perf_counter()
    scene = build_scene(args.page)
    build_ms = (time.perf_counter() - start) * 1000.0

    item_count = len(scene.scene_manager.m_items)
    nodes, depth, entries = quadtree_stats(scene)
    per_move = measure_moves(scene, args.moves)
    per_find = measure_find_children(scene)

    print(f"page             : {os.path.basename(args.page)}")
    print(f"items            : {item_count}")
    print(f"load time        : {build_ms:.1f} ms")
    print(f"quadtree nodes   : {nodes}")
    print(f"quadtree depth   : {depth}")
    print(f"quadtree entries : {entries}  (duplication x{entries / max(item_count, 1):.2f})")
    print(f"findChildren     : {per_find:.3f} ms/call")
    print(f"on_mouse_move    : {per_move:.3f} ms/call")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
