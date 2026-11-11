# -*- coding: utf-8 -*-
"""CoreQGraphics 增量刷新回归：吸附点按 owner / 图层树按行 == 全量重建。

    .venv/Scripts/python.exe tools/verify_core_qgraphics_incremental.py

对应设计文档 P0-2 / P0-3。核心红线（INV）：任何编辑之后，增量维护出来的
吸附点表（点集、坐标->owner 归属、空间哈希、owner 反向表）必须与「从头
全量重建」逐项一致；图层树按行更新后的行文本 / 显隐灰字必须与全量刷新
一致。否则按 T 抓起的图元、可见的红色十字、图层树显示都会静默跑偏。

离屏运行，不写任何页面文件。
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

PAGE_DIR = os.path.join("Designer", "Core", "data.json", "datas", "design", "pages")
FAILURES: list[str] = []


def check(label, cond, detail=""):
    if cond:
        print(f"  [OK] {label}" + (f"  {detail}" if detail else ""))
    else:
        print(f"  [FAIL] {label}  {detail}")
        FAILURES.append(label)


def state(snap):
    """与顺序无关的可比快照。"""
    return (
        frozenset(snap.points["endpoints"]),
        frozenset(snap.points["midpoints"]),
        frozenset((k, tuple(v)) for k, v in snap._owners.items()),
        frozenset((k, tuple(sorted(b))) for k, b in snap._index.items()),
        frozenset((k, tuple(sorted(v))) for k, v in snap._by_owner.items()),
        frozenset((k, tuple(sorted(v))) for k, v in snap._entry_owners.items()),
    )


def full_state(scene, cls):
    s = cls()
    ends, mids, owners = scene.snap_points_with_owners()
    s.update_points(ends, mids, owners)
    return state(s)


def compare(label, snap, scene, cls):
    a, b = state(snap), full_state(scene, cls)
    if a == b:
        check(label, True, f"points={snap.count()} owners={len(snap._owners)}")
        return
    detail = []
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            sx, sy = set(x), set(y)
            detail.append(f"part{i}: only-inc={list(sx - sy)[:3]} "
                          f"only-full={list(sy - sx)[:3]}")
    check(label, False, "; ".join(detail))


def pts_of(it):
    """图元当前捕捉点坐标（用于确认「确实改动了几何」，别空操作对空操作）。"""
    e, m = it.snap_points()
    return tuple((round(p.x(), 4), round(p.y(), 4)) for p in e + m)


def main() -> int:
    from Designer.CoreQGraphics import GraphicsScene, GraphicsView, load_page
    from Designer.CoreQGraphics.g_snap import SnapSystem
    from Designer.CoreQGraphics.ui.layer_tree import LayerTreeDock

    app = QApplication([])
    path = os.path.join(PAGE_DIR, "page_1.json")
    scene = load_page(path)
    view = GraphicsView(scene)
    view.refresh_snap_points()
    snap = view.snap
    items = scene.all_items()
    print(f"=== 1. 初始全量表（{len(items)} 图元 / {sum(snap.count())} 捕捉点）===")
    compare("初始全量表 == 独立全量重建", snap, scene, SnapSystem)
    check("全量表带 owner 归属（可增量）", snap.is_incremental)

    print("\n=== 2. 单图元 / 连续多次增量 ===")
    # 用 moveBy（真实拖动链路）：set_page_center 对带父图元会被
    # translate_locked() 拒绝，那样测出来的是「空操作对空操作」的假绿。
    it = items[7]
    before = pts_of(it)
    it.moveBy(137.0, -89.0)
    check("单图元位移确实改变了捕捉点", pts_of(it) != before)
    scene.notify_edit(it)
    compare("单个图元位移后 == 全量", snap, scene, SnapSystem)

    changed = 0
    for k, (dx, dy) in ((31, (51.0, 22.0)), (122, (-77.0, 8.0)),
                        (400, (13.0, -41.0)), (900, (-211.0, 63.0))):
        j = items[k]
        b = pts_of(j)
        j.moveBy(dx, dy)
        changed += pts_of(j) != b
        scene.notify_edit(j)
    check("连续 4 次位移都真实生效", changed == 4, f"changed={changed}/4")
    compare("连续 4 次增量后 == 全量", snap, scene, SnapSystem)

    # 顶层图元走属性面板的 set_page_center 路径（translate_locked 放行）
    top = next(x for x in items if not x.parent_id
               and not scene.index.descendants(x.item_id)
               and x.item_id != it.item_id)
    b = pts_of(top)
    c = top.page_center()
    ok = top.set_page_center(c[0] + 91.0, c[1] - 37.0)
    check("顶层图元 set_page_center 生效", bool(ok) and pts_of(top) != b)
    scene.notify_edit(top)
    compare("属性面板改位置后 == 全量", snap, scene, SnapSystem)

    print("\n=== 3. 父图元移动带动后代（owner 扩展）===")
    parent = next((x for x in items if scene.index.descendants(x.item_id)), None)
    if parent is None:
        check("找到带后代的父图元", False)
    else:
        kids = scene.index.descendants(parent.item_id)
        before = kids[0].pos()
        parent.moveBy(73.0, -46.0)
        moved = (kids[0].pos() - before).manhattanLength() > 1e-6
        check("父 moveBy 确实刚体带动了子图元", moved, f"kids={len(kids)}")
        scene.notify_edit(parent)
        compare("父 + 后代的捕捉点增量 == 全量", snap, scene, SnapSystem)

    print("\n=== 4. 共享坐标 / 隐藏 / 恢复 ===")
    a = scene.create_item("rect", center=(12000.0, 12000.0))
    b = scene.create_item("rect", center=(12000.0, 12000.0))
    a.set_page_size(200.0, 100.0)
    b.set_page_size(200.0, 100.0)
    view.sync_snap_points()             # 结构变化标脏 -> 全量
    shared = [c for c, v in snap._owners.items() if len(v) > 1]
    check("存在多 owner 共享坐标（对拍有效）", len(shared) > 0,
          f"shared={len(shared)}")
    c = a.page_center()
    a.moveBy(500.0, 500.0)
    scene.notify_edit(a)
    compare("移走一个 owner 后 == 全量", snap, scene, SnapSystem)
    b.set_visibility(False)
    scene.notify_edit(b)
    compare("隐藏图元后 == 全量", snap, scene, SnapSystem)
    b.set_visibility(True)
    scene.notify_edit(b)
    compare("恢复显示后 == 全量", snap, scene, SnapSystem)

    print("\n=== 5. 结构变化走全量 / 空 ids 不惊动表 ===")
    scene.delete_items([a, b])
    view.sync_snap_points()
    compare("删除后全量同步 == 全量", snap, scene, SnapSystem)
    before = state(snap)
    scene.emit_items_changed([])        # 页面级改动：只发粗信号
    check("空 ids 不改动吸附点表", state(snap) == before)

    print("\n=== 6. 图层树按行更新 ===")
    tree = LayerTreeDock()
    tree.set_scene(scene)
    n0 = tree.tree.topLevelItemCount()

    def labels():
        return [tree.tree.topLevelItem(i).text(0)
                for i in range(tree.tree.topLevelItemCount())]

    target = items[3]
    target.set_name("增量回归改名_XYZ")
    scene.notify_edit(target)
    check("按行更新不重建树（行数不变）",
          tree.tree.topLevelItemCount() == n0, f"rows={n0}")
    check("改名后行文本已更新",
          any("增量回归改名_XYZ" in s for s in labels()))
    tree.refresh()
    check("按行更新文本 == 全量重建文本",
          any("增量回归改名_XYZ" in s for s in labels()))

    target.set_visibility(False)
    scene.notify_edit(target)
    hidden = labels()
    check("隐藏态行文本带灰字标记",
          any("增量回归改名_XYZ" in s and "隐藏" in s for s in hidden))
    tree.refresh()
    check("显隐灰字 == 全量重建", hidden == labels())

    target.set_visibility(True)
    scene.notify_edit(target)
    tree.refresh()
    check("恢复显示后清掉灰字",
          any("增量回归改名_XYZ" in s and "隐藏" not in s
              for s in labels()))

    # 有过滤时安全退化全量；新增 / 删除 id 也退化全量
    tree.filter_edit.setText("增量回归")
    scene.notify_edit(target)
    check("过滤状态下退化全量（无异常）",
          tree.tree.topLevelItemCount() >= 1)
    tree.filter_edit.clear()
    tree.refresh()
    scene.emit_items_changed([99999999])
    check("未知 id 安全退化全量", tree.tree.topLevelItemCount() == n0)

    print("\n=== 7. 换场景解绑（D-6）===")
    other = GraphicsScene()
    tree.set_scene(other)
    check("换场景后树跟随新场景", tree.tree.topLevelItemCount() == 0)
    tree.set_scene(scene)
    check("换回原场景后树恢复", tree.tree.topLevelItemCount() == n0)

    print("\n=== 8. 同进程 A/B 计时（量级，不作硬断言）===")
    # 挑无父无子的顶层图元，moveBy 不触发刚体传播，量的才是纯 UI 刷新成本
    t = next(x for x in items if not x.parent_id
             and not scene.index.descendants(x.item_id))
    t0 = time.perf_counter()
    for _ in range(20):
        t.moveBy(0.01, 0.0)
        scene.notify_edit(t)
    inc_ms = (time.perf_counter() - t0) / 20 * 1000
    t0 = time.perf_counter()
    for _ in range(5):
        view.refresh_snap_points()
    full_ms = (time.perf_counter() - t0) / 5 * 1000
    print(f"  单次属性编辑（增量全链路）  {inc_ms:8.2f} ms")
    print(f"  refresh_snap_points（全量）  {full_ms:8.2f} ms")
    print(f"  倍率 ~{full_ms / max(inc_ms, 1e-6):.1f}x")
    check("增量明显快于全量", inc_ms < full_ms / 2,
          f"{inc_ms:.2f} vs {full_ms:.2f} ms")

    tree.set_scene(None)
    view.setScene(None)
    print(f"\n失败 {len(FAILURES)} 项" +
          (": " + ", ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
