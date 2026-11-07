"""探针：顶点类（triangle / polygon / line / path）旋转时支点、中心、形状是否都对。

判据：
1. 默认支点旋转：中心与支点原地不动（这就是用户说的「旋转中心不能偏移」）；
2. 形状真的转了：转 30° 后的顶点 == 初始顶点绕中心转 30°；
3. 自定义支点旋转：支点不动，中心绕支点刚体转动，顶点绕支点刚体转动；
4. 存盘 → 重新加载：几何与支点都还在（烘焙不丢旋转）。
"""
from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from Designer.CoreQGraphics.g_element import rotate_xy  # noqa: E402
from Designer.CoreQGraphics.g_elements import ITEM_TYPES  # noqa: E402
from Designer.CoreQGraphics.g_scene import GraphicsScene  # noqa: E402

FAILS: list[str] = []


def check(name, ok, detail=""):
    if not ok:
        FAILS.append(name)
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def close(a, b, tol=1e-2):
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol


def draw(scene, kind, pts):
    scene.begin_draw_tool(kind)
    for p in pts:
        scene.draw_add_point(QPointF(*p))
    if kind in ("polygon", "path"):
        scene.finish_polygon()
    item = max(scene.all_items(), key=lambda it: it.item_id)
    item.setSelected(True)
    return item


def run(kind, pts):
    app = QApplication.instance() or QApplication(sys.argv)
    scene = GraphicsScene()
    scene.setSceneRect(0, 0, 4000, 3000)
    item = draw(scene, kind, pts)
    app.processEvents()
    print(f"\n--- {kind} 默认支点 ---")
    orig = item._live_page_points()
    c0, o0 = item.page_center(), item.page_origin()
    print(f"  初始 center={c0} pivot={o0} n={len(orig)}")
    for ang in (30.0, 60.0, 90.0, 30.0, 0.0):
        item.set_page_angle(ang)
        app.processEvents()
        rec = item.to_page_record()
        now = item._live_page_points()
        c = (rec["center_pos"]["x"], rec["center_pos"]["y"])
        o = (rec["origin_pos"]["x"], rec["origin_pos"]["y"])
        check(f"{kind} 转 {ang}° 后中心不动", close(c, c0, 1e-3), f"{c0} -> {c}")
        check(f"{kind} 转 {ang}° 后支点不动", close(o, o0, 1e-3), f"{o0} -> {o}")
        # 形状是否真的按角度转了：page 角度 +ang 即右手系逆时针
        want = [rotate_xy(x, y, c0[0], c0[1], ang) for x, y in orig]
        err = max(min(math.hypot(a[0] - b[0], a[1] - b[1]) for b in want)
                  for a in now)
        check(f"{kind} 转 {ang}° 顶点到位", err < 0.05, f"maxerr={err:.4f}")

    print(f"\n--- {kind} 自定义支点 ---")
    item.set_page_angle(0.0)
    app.processEvents()
    item.to_page_record()
    pivot = (c0[0] + 60.0, c0[1] + 40.0)
    item.set_page_origin(*pivot)
    app.processEvents()
    check(f"{kind} 设置支点后 center 不动", close(item.page_center(), c0, 1e-3),
          f"{item.page_center()}")
    before = item._live_page_points()
    for ang in (25.0, 70.0):
        item.set_page_angle(ang)
        app.processEvents()
        rec = item.to_page_record()
        o = (rec["origin_pos"]["x"], rec["origin_pos"]["y"])
        c = (rec["center_pos"]["x"], rec["center_pos"]["y"])
        check(f"{kind} 自定义支点转 {ang}° 支点不动", close(o, pivot, 1e-3),
              f"{pivot} -> {o}")
        want_c = rotate_xy(c0[0], c0[1], pivot[0], pivot[1], ang)
        check(f"{kind} 自定义支点转 {ang}° 中心绕支点刚体转", close(c, want_c, 2e-2),
              f"want={tuple(round(v, 3) for v in want_c)} got={c}")
        want = [rotate_xy(x, y, pivot[0], pivot[1], ang) for x, y in before]
        now = item._live_page_points()
        err = max(min(math.hypot(a[0] - b[0], a[1] - b[1]) for b in want) for a in now)
        check(f"{kind} 自定义支点转 {ang}° 顶点到位", err < 0.05, f"maxerr={err:.4f}")

    # 存盘 / 重新加载
    print(f"\n--- {kind} 重新加载 ---")
    rec = item.to_page_record()
    fresh = ITEM_TYPES[kind](rec, scene.projection)
    scene.addItem(fresh)
    app.processEvents()
    check(f"{kind} 重新加载后支点仍在", close(fresh.page_origin(), pivot, 0.05),
          f"{fresh.page_origin()} vs {pivot}")
    check(f"{kind} 重新加载后包围盒一致",
          close((fresh.page_bounding_rect().left(), fresh.page_bounding_rect().top()),
                (item.page_bounding_rect().left(), item.page_bounding_rect().top()),
                0.05),
          f"{fresh.page_bounding_rect()} vs {item.page_bounding_rect()}")
    scene.delete_items([item.item_id, fresh.item_id])
    app.processEvents()


def main() -> int:
    run("triangle", [(100, 100), (300, 100), (100, 260)])
    run("polygon", [(100, 100), (300, 100), (300, 220), (100, 220), (160, 160)])
    run("line", [(100, 100), (320, 240)])
    run("path", [(100, 100), (300, 100), (300, 260), (180, 200)])
    print("\n失败项：" if FAILS else "\n全部通过")
    for f in FAILS:
        print("  -", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
