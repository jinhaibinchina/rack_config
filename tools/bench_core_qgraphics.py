# -*- coding: utf-8 -*-
"""CoreQGraphics 关键路径基准（离屏，可复现）。

    .venv/Scripts/python.exe tools/bench_core_qgraphics.py
    .venv/Scripts/python.exe tools/bench_core_qgraphics.py --page page_9.json --repeat 5
    .venv/Scripts/python.exe tools/bench_core_qgraphics.py --markdown

用途：给设计文档 / 优化验收提供同一口径的数字。全部在 ``QT_QPA_PLATFORM=offscreen``
下跑，不写任何页面文件。默认只跑 ``page_1.json``（1618 图元，最重的存量页面）。

口径说明：
* 每项取 ``repeat`` 次里的最小值（排除首次冷缓存的干扰）；``load_page`` 额外单列
  冷态首次值，因为真实「打开页面」就是冷态。
* ``history.commit`` 已含 ``snapshot()`` + ``deepcopy``，与主窗口 ``_after_edit()``
  里的实际调用一致。
* ``moveBy`` 取**最大子树**的根图元挪 1 个场景单位，衡量父移动传播成本。
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

PAGE_DIR = os.path.join("Designer", "Core", "data.json", "datas", "design", "pages")


def best_ms(fn, repeat: int) -> float:
    best = float("inf")
    for _ in range(max(1, repeat)):
        start = time.perf_counter()
        fn()
        best = min(best, (time.perf_counter() - start) * 1000.0)
    return best


def bench(page: str, repeat: int) -> dict:
    from Designer.CoreQGraphics import GraphicsScene, GraphicsView, load_page
    from Designer.CoreQGraphics.ui.history import PageHistory
    from Designer.CoreQGraphics.ui.layer_tree import LayerTreeDock

    path = os.path.join(PAGE_DIR, page)
    if not os.path.exists(path):
        raise SystemExit(f"页面不存在：{path}")

    cold = time.perf_counter()
    scene = load_page(path)
    cold_ms = (time.perf_counter() - cold) * 1000.0
    keep = [scene]          # 不让 Python 侧引用先于 C++ 对象消失

    items = len(scene.all_items())
    view = GraphicsView(scene)
    view.resize(1600, 900)
    view.snap.clear()
    view.refresh_snap_points()
    ends, mids = view.snap.count()

    tree = LayerTreeDock()
    tree.set_scene(scene)
    history = PageHistory(scene)
    data = scene.snapshot()

    root, biggest = None, 0
    for it in scene.all_items():
        count = len(scene.index.descendants(it.item_id))
        if count > biggest:
            root, biggest = it, count

    rows = [
        ("load_page（冷态首次）", cold_ms),
        ("page_data", best_ms(lambda: scene.page_data(), repeat)),
        ("snapshot", best_ms(lambda: scene.snapshot(), repeat)),
        ("deepcopy(snapshot)", best_ms(lambda: copy.deepcopy(data), repeat)),
        ("history.commit", best_ms(history.commit, repeat)),
        # 全量 vs 增量放在同一进程里量，避免跨次运行的 ±50% 波动
        ("refresh_snap_points（全量）", best_ms(view.refresh_snap_points, repeat)),
        ("sync_snap_points（表已同步）",
         best_ms(view.sync_snap_points, repeat)),
        ("refresh_snap_owners（1 个 owner）", best_ms(
            lambda: view.refresh_snap_owners(
                [scene.all_items()[3].item_id]), repeat)),
        ("scene.snap_points", best_ms(scene.snap_points, repeat)),
        ("LayerTreeDock.refresh（全量）", best_ms(tree.refresh, repeat)),
        ("LayerTreeDock.update_items（1 行）", best_ms(
            lambda: tree.update_items([scene.all_items()[3].item_id]), repeat)),
        ("select_all_items", best_ms(scene.select_all_items, repeat)),
        # 属性提交走「单选」口径（真实编辑场景）；全选时 property_panel 走汇总页。
        # 这条会经 itemChanged 广播，实际只做 1 个 owner + 1 行的增量刷新。
        ("notify_edit（单选，端到端）", best_ms(
            lambda: (scene.clearSelection(),
                     scene.all_items()[3].setSelected(True),
                     scene.notify_edit(None)), repeat)),
        (f"moveBy（最大子树 {biggest}）",
         best_ms(lambda: root.moveBy(1.0, 0.0), repeat) if root else 0.0),
        # 下面三项会重建全部图元（旧 wrapper 悬空），所以放在最后。
        # 不传 owners 的 update_points 会把吸附表降级成「无归属」，也放最后。
        ("load_page（热）", best_ms(lambda: scene.load_page(path), repeat)),
        ("restore（撤销一步）", best_ms(
            lambda: scene.restore(copy.deepcopy(data)), repeat)),
        ("snap.update_points（无 owners）", best_ms(
            lambda: view.snap.update_points(*scene.snap_points()), repeat)),
    ]
    return {
        "page": page, "items": items, "max_subtree": biggest,
        "snap_points": ends + mids, "rows": rows,
        "tree": tree, "scene": keep,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="CoreQGraphics 关键路径基准")
    parser.add_argument("--page", default="page_1.json", help="页面文件名")
    parser.add_argument("--repeat", type=int, default=5, help="每项重复次数（取最小）")
    parser.add_argument("--markdown", action="store_true", help="输出 Markdown 表格")
    args = parser.parse_args()

    app = QApplication([])
    result = bench(args.page, args.repeat)

    head = f"== {result['page']}  items={result['items']}  " \
           f"max_subtree={result['max_subtree']}  snap_points={result['snap_points']}"
    print(head)
    if args.markdown:
        print("| 操作 | 耗时 (ms) |")
        print("| --- | ---: |")
        for name, ms in result["rows"]:
            print(f"| {name} | {ms:.2f} |")
    else:
        for name, ms in result["rows"]:
            print(f"   {name:<26}{ms:9.2f} ms")

    # 显式断开场景信号，避免退出时槽仍持有已析构的 C++ 场景
    result["tree"].set_scene(None)
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
