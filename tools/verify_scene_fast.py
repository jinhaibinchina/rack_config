"""Stage 0 加速层回归校验（离屏）。

覆盖新增的四处语义敏感改动：

1. ``Transform.map_many`` 与逐个 ``map`` 数值一致（含 w≈0 / None）；
2. ``scene_fast`` 的 pen/brush/dashed/font 缓存命中、参数正确、
   ``set_enabled(False)`` 能退回「每次新建」；
3. ``viewBoundingRect()`` 缓存在「视图映射参数变了 / 包围盒对象换了」时
   必须失效，且 FAST=0 时逐次重算；
4. ``on_mouse_move`` 在 FAST=0 / FAST=1 下产出**完全相同**的吸附点集合，
   ``SnapSystem`` 同时接受 QPointF 与 (x, y) 元组。

用法::

    .venv/Scripts/python.exe tools/verify_scene_fast.py
"""

from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from Designer.Core import scene_fast  # noqa: E402
from Designer.Core.my_transform_v2 import Transform  # noqa: E402
from Designer.Core.mySnapSystem import SnapSystem  # noqa: E402
from tools.bench_scene import DEFAULT_PAGE, build_scene  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "OK  " if condition else "FAIL"
    print(f"[{status}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        FAILURES.append(name)


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol or (math.isnan(a) and math.isnan(b))


def test_map_many() -> None:
    t = Transform()
    t.translate(120.0, -35.0)
    t.rotate(23.0)
    t.translate(11.0, 7.0)
    pts = [QPointF(1, 2), QPointF(-30, 44.5), QPointF(0, 0), (7.5, -2.25)]
    mapped = t.map_many(pts)
    check("map_many 返回点数一致", len(mapped) == len(pts))
    for p, (x, y) in zip(pts, mapped):
        q = t.map(p if isinstance(p, QPointF) else QPointF(*p))
        check(
            f"map_many 与 map 一致 {p}",
            close(x, q.x()) and close(y, q.y()),
            f"{x:.6f},{y:.6f} vs {q.x():.6f},{q.y():.6f}",
        )

    # 投影矩阵：w = x + 1；x = -1 时 w≈0 必须返回 nan
    proj = Transform([[1.0, 0.0, 1.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    q = proj.map(QPointF(-1.0, 5.0))
    x, y = proj.map_many([QPointF(-1.0, 5.0)])[0]
    check("w≈0 返回 nan", math.isnan(q.x()) and math.isnan(x) and math.isnan(y))
    q2 = proj.map(QPointF(2.0, 5.0))
    x2, y2 = proj.map_many([(2.0, 5.0)])[0]
    check(
        "w≠0 正常归一化",
        close(x2, q2.x()) and close(y2, q2.y()),
        f"{x2},{y2} vs {q2.x()},{q2.y()}",
    )
    nan_x, nan_y = proj.map_many([None])[0]
    check("None 点不抛异常且返回 nan", math.isnan(nan_x) and math.isnan(nan_y))


def test_paint_cache() -> None:
    scene_fast.set_enabled(True)
    c = QColor(14, 248, 236, 255)
    p1 = scene_fast.pen_for(c, 2.0)
    p2 = scene_fast.pen_for(QColor(14, 248, 236, 255), 2.0)
    check("同一 (色, 宽) 命中缓存", p1 is p2)
    check("缓存画笔参数正确", p1.color().rgba() == c.rgba() and p1.widthF() == 2.0)
    p3 = scene_fast.pen_for(c, 3.0)
    check("不同线宽不串用", p3 is not p1 and p3.widthF() == 3.0)
    b1 = scene_fast.brush_for(c)
    check("画刷命中缓存", b1 is scene_fast.brush_for(QColor(14, 248, 236, 255)))
    check("画刷颜色正确", b1.color().rgba() == c.rgba())
    d = scene_fast.dashed_pen_for(c)
    check(
        "虚线画笔样式正确",
        d.style() == Qt.CustomDashLine and d.capStyle() == Qt.RoundCap
        and d.joinStyle() == Qt.RoundJoin and len(d.dashPattern()) == 4,
    )
    f = scene_fast.font_for("Arial", 12.0, True)
    check("字体缓存与粗体正确", f is scene_fast.font_for("Arial", 12.0, True) and f.bold())

    scene_fast.set_enabled(False)
    p4 = scene_fast.pen_for(c, 2.0)
    check("FAST=0 退回每次新建", p4 is not p1 and p4.color().rgba() == c.rgba())
    scene_fast.set_enabled(True)


def test_view_bbox_cache() -> None:
    scene = build_scene(DEFAULT_PAGE)
    item = next(
        (it for it in scene.scene_manager.m_sorted_items
         if not it.sceneBoundingRect().isNull()),
        None,
    )
    check("取到有包围盒的图元", item is not None)
    if item is None:
        return

    scene_fast.set_enabled(True)
    v0 = item.viewBoundingRect()
    check("同参数命中缓存（返回同一对象）", item.viewBoundingRect() is v0)
    expect0 = scene.rect_sceneToView(item._sceneBoundingRect)
    check("缓存值与直接换算一致", v0 == expect0)

    old_origin = QPointF(scene.scene_origin)
    scene.scene_origin = QPointF(old_origin.x() + 137.0, old_origin.y() - 61.0)
    v1 = item.viewBoundingRect()
    check("scene_origin 变化后缓存失效", v1 != v0 and v1 == scene.rect_sceneToView(item._sceneBoundingRect))
    scene.scene_origin = old_origin

    old_grid = scene.grid_size
    scene.grid_size = old_grid * 1.5
    v2 = item.viewBoundingRect()
    check("grid_size 变化后缓存失效", v2 != v1 and v2 == scene.rect_sceneToView(item._sceneBoundingRect))
    scene.grid_size = old_grid

    old_units = scene.scene_units_per_grid_x
    scene.scene_units_per_grid_x = old_units * 2.0
    v3 = item.viewBoundingRect()
    check("units_per_grid 变化后缓存失效", v3 != v2 and v3 == scene.rect_sceneToView(item._sceneBoundingRect))
    scene.scene_units_per_grid_x = old_units

    old_agv = scene.is_use_for_agv_map
    scene.is_use_for_agv_map = not old_agv
    v4 = item.viewBoundingRect()
    check("AGV 坐标约定变化后缓存失效", v4 != v3 and v4 == scene.rect_sceneToView(item._sceneBoundingRect))
    scene.is_use_for_agv_map = old_agv

    old_rect = item._sceneBoundingRect
    item._sceneBoundingRect = QRectF(10.0, 20.0, 30.0, 40.0)
    v5 = item.viewBoundingRect()
    check("包围盒对象替换后缓存失效", v5 != v4 and v5 == scene.rect_sceneToView(item._sceneBoundingRect))
    item._sceneBoundingRect = old_rect

    scene_fast.set_enabled(False)
    check("FAST=0 逐次重算（不返回缓存对象）", item.viewBoundingRect() is not v5)
    scene_fast.set_enabled(True)


def test_snap_equivalence() -> None:
    scene = build_scene(DEFAULT_PAGE)
    pos = QPointF(180.0, 140.0)

    scene_fast.set_enabled(False)
    scene.on_mouse_move(pos)
    off_e = set(scene.snapSys.snap_points["endpoints"])
    off_m = set(scene.snapSys.snap_points["midpoints"])

    scene_fast.set_enabled(True)
    scene.on_mouse_move(pos)
    on_e = set(scene.snapSys.snap_points["endpoints"])
    on_m = set(scene.snapSys.snap_points["midpoints"])

    check("端点集合与旧路径完全一致", off_e == on_e, f"{len(off_e)} vs {len(on_e)}")
    check("中点集合与旧路径完全一致", off_m == on_m, f"{len(off_m)} vs {len(on_m)}")
    check("端点集合非空（用例有效）", len(on_e) > 0)

    snap = SnapSystem()
    snap.update_endpoints([(1.0, 2.0), QPointF(3.0, 4.0)])
    snap.update_midpoints([(5.0, 6.0)])
    check(
        "SnapSystem 同时接受元组与 QPointF",
        (1.0, 2.0) in snap.snap_points["endpoints"]
        and (3.0, 4.0) in snap.snap_points["endpoints"]
        and (5.0, 6.0) in snap.snap_points["midpoints"],
    )


def test_pixel_equivalence() -> None:
    """同一场景在 FAST=0 / FAST=1 下逐像素一致（含平移与缩放）。"""
    scene = build_scene(DEFAULT_PAGE)
    scene.resize(860, 545)
    scene.update_coordinate()

    states = [(0.0, 0.0, 1.0), (250.0, -180.0, 0.7), (-400.0, 320.0, 1.3)]
    for offset_x, offset_y, scale in states:
        scene.scale_factor = scale
        scene.offset = QPointF(offset_x, offset_y)
        scene.update_coordinate()

        scene_fast.set_enabled(False)
        scene.update()
        QApplication.processEvents()
        img_off = scene.grab().toImage().copy()

        scene_fast.set_enabled(True)
        scene.update()
        QApplication.processEvents()
        img_on = scene.grab().toImage().copy()

        diff = 0
        if img_off.size() == img_on.size():
            for y in range(img_off.height()):
                for x in range(img_off.width()):
                    if img_off.pixel(x, y) != img_on.pixel(x, y):
                        diff += 1
        else:
            diff = -1
        check(
            f"逐像素一致 offset=({offset_x},{offset_y}) scale={scale}",
            diff == 0,
            f"diff={diff}",
        )


def main() -> int:
    app = QApplication.instance() or QApplication([])  # noqa: F841
    print("=== 1. Transform.map_many ===")
    test_map_many()
    print("\n=== 2. 画笔/画刷/字体缓存 ===")
    test_paint_cache()
    print("\n=== 3. viewBoundingRect 缓存失效 ===")
    test_view_bbox_cache()
    print("\n=== 4. 吸附点 A/B 等价 + SnapSystem 输入 ===")
    test_snap_equivalence()
    print("\n=== 5. 渲染逐像素 A/B ===")
    test_pixel_equivalence()

    print(f"\n失败 {len(FAILURES)} 项")
    for name in FAILURES:
        print(f"  - {name}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
