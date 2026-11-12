"""绘制态 T 吸附专项门禁（CoreQGraphics）。

覆盖用户现场报障的完整链路：

* 刚创建 / 刚放下的图元只广播 ``structureChanged``（点表置脏），绘制过程中
  十字必须自己刷新点表，不能只落在格点上；
* 绘制态不能把「已选中图元」的特征点排除掉（刚画完的图元默认选中，
  从它的角上起画新线是最常见的用法）；
* 按 T 之后**真正落下**的第一个点、以及后续点，必须与可见红十字一致，
  而不是只把系统光标 warp 过去、落点仍用原始坐标；
* 工具箱按钮在 Dock 里，激活绘制工具后焦点要回到画布，T 才送得到视图；
* 门控关闭时自由绘制语义不变，非绘制态仍排除选中项自身点。

用法：``QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tools/verify_core_qgraphics_draw_snap.py``
"""

from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from Designer.CoreQGraphics.g_scene import GraphicsScene  # noqa: E402
from Designer.CoreQGraphics.g_view import GraphicsView  # noqa: E402

SOURCE_PAGE = "Designer/Core/data.json/datas/design/pages/page_1.json"
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILURES.append(name)
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def close_pt(a, b, tol: float = 1e-3) -> bool:
    return (a is not None and b is not None
            and math.hypot(a.x() - b.x(), a.y() - b.y()) <= tol)


app = QApplication.instance() or QApplication([])


def new_pair():
    scene = GraphicsScene()
    view = GraphicsView(scene)
    view.resize(900, 600)
    view.show()
    app.processEvents()
    # 模拟首屏 showEvent -> fit_content 已经建过点表
    view.refresh_snap_points()
    return scene, view


def add_rect(scene, view):
    """创建一个矩形并让视图对准它；``create_item`` 只把点表标脏。"""
    rect = scene.create_item("rect", center=(1000.0, 1000.0))
    rect.set_page_size(200.0, 120.0)
    view.centerOn(scene.projection.point(1000.0, 1000.0))
    app.processEvents()
    return rect


def off_grid_target(view, item):
    """找一个不压在格点上的真实端点，避免「吸到格点」假绿。"""
    ends, _mids = item.snap_points()
    for p in ends:
        gx, gy = view.snap.nearest_grid(p)
        if math.hypot(p.x() - gx, p.y() - gy) > 1e-3:
            return QPointF(p)
    return QPointF(ends[0])


def hover_near(view, target, factor: float = 0.35):
    """在捕捉阈值内、但不等于捕捉点的光标位置（视图场景坐标 + 视口像素）。"""
    off = min(view.snap.threshold * factor, 5.0 / view._view_scale())
    hov = QPointF(target.x() + off, target.y() + off)
    vp = QPoint(int(view.mapFromScene(hov).x()),
                int(view.mapFromScene(hov).y()))
    return hov, vp


def first_point_scene(scene) -> QPointF | None:
    state = scene.draw_preview_state()
    pts = state[1] if state is not None else None
    if not pts:
        return None
    return scene.projection.point(pts[0].x(), pts[0].y())


print("=== 1. 绘制态能识别已有图元特征点（点表只置脏 / 选中态不排除） ===")
scene, view = new_pair()
rect = add_rect(scene, view)
target = off_grid_target(view, rect)
print("  dirty after create =", view._snap_full_dirty)

view.set_draw_tool("line")
hov, vp = hover_near(view, target)
view._set_hover(hov)
app.processEvents()
marker, active = view._hover_marker()
check("激活绘制工具即补全点表（无需显式 refresh）",
      (target.x(), target.y()) in view.snap.all_points(),
      f"table={view.snap.count()} dirty={view._snap_full_dirty}")
check("绘制第一点之前十字落在已有图元端点",
      close_pt(marker, target), f"marker={marker} target={target}")
check("十字是 element 点而非退格点",
      view.snap.aim(view.mapToScene(vp),
                    exclude=view._snap_scan_exclude(), always=True)[1] == "element")

rect.setSelected(True)
view._invalidate_own_points()
marker_sel, _ = view._hover_marker()
check("已选中图元的特征点不再被排除（从角上起画）",
      (target.x(), target.y()) not in view._snap_scan_exclude(),
      f"exclude={sorted(view._snap_scan_exclude())[:3]}")
check("选中态下绘制十字仍落在图元端点",
      close_pt(marker_sel, target), f"marker={marker_sel}")

view.set_draw_tool(None)
check("非绘制态仍排除选中项自身点（旧语义不回归）",
      (target.x(), target.y()) in view._snap_scan_exclude(),
      f"exclude={sorted(view._snap_scan_exclude())[:3]}")
active_before = view.snap.enabled
check("T 门控默认关闭时绘制取点不受影响", active_before is False,
      f"enabled={active_before}")

scene.clearSelection()
view.close()
app.processEvents()

print("\n=== 2. 门控关闭：自由落点保持原始光标 ===")
scene, view = new_pair()
rect = add_rect(scene, view)
target = off_grid_target(view, rect)
view.snap.enabled = False
view.set_draw_tool("line")
hov, vp = hover_near(view, target)
QTest.mouseMove(view.viewport(), vp)
app.processEvents()
QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=vp)
app.processEvents()
raw = view.mapToScene(vp)
check("未开吸附时第一点 = 原始光标（自由绘制不变）",
      close_pt(first_point_scene(scene), raw, 1.0),
      f"landed={first_point_scene(scene)} raw={raw} target={target}")
scene.cancel_draw()
view.set_draw_tool(None)
view.close()
app.processEvents()

print("\n=== 3. 按 T 后第一个点 / 后续点都落在可见红十字 ===")
scene, view = new_pair()
rect = add_rect(scene, view)
rect.setSelected(True)               # 复现「刚画完的图元处于选中态」
ends, _ = rect.snap_points()
corners = [QPointF(p) for p in ends
           if math.hypot(p.x() - view.snap.nearest_grid(p)[0],
                         p.y() - view.snap.nearest_grid(p)[1]) > 1e-3]
t1 = corners[0]
t2 = next((p for p in corners if not close_pt(p, t1, 1.0)), corners[-1])
view.snap.enabled = False
view.set_draw_tool("line")

hov1, vp1 = hover_near(view, t1)
QTest.mouseMove(view.viewport(), vp1)
app.processEvents()
# QTest 内部按「全局光标位置」去重：前一组用例在同一视口像素点落过鼠标，
# 换一个窗口后发到同一坐标的 mouseMove 会被吞掉（真机不会）。这里补一次
# hover，落点仍走真实 QTest.mouseClick，不受该测试桩行为影响。
if view.snap.hover is None:
    view._set_hover(view.mapToScene(vp1))
cross1, _ = view._hover_marker()
check("第一点之前红十字指向已有图元端点", close_pt(cross1, t1),
      f"cross={cross1} t1={t1}")
QTest.keyClick(view, Qt.Key_T)
app.processEvents()
check("按 T 打开吸附门控", view.snap.enabled)
expected1, kind1 = view.snap.aim(
    view.mapToScene(vp1), exclude=view._snap_scan_exclude(), always=True)
QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=vp1)
app.processEvents()
landed1 = first_point_scene(scene)
check("第一点精确落在按 T 吸到的红十字上",
      close_pt(landed1, expected1, 1.0) and kind1 == "element",
      f"landed={landed1} cross={expected1} kind={kind1}")
check("第一点不再是未吸附的原始光标",
      not close_pt(landed1, view.mapToScene(vp1), 1e-3),
      f"raw={view.mapToScene(vp1)}")
check("第一点落定后仍处于绘制中", scene.drawing_active())

draw_item = scene._draw_item
check("临时图元自身点不残留在吸附归属表（无幽灵端点）",
      draw_item is not None
      and draw_item.item_id not in view.snap._by_owner,
      f"draw_id={draw_item.item_id if draw_item else None} "
      f"owners={len(view.snap._by_owner)}")
check("已存在图元的端点仍留在点表（撤 owner 没误删共享点）",
      (t1.x(), t1.y()) in view.snap.all_points(),
      f"table={view.snap.count()}")

hov2, vp2 = hover_near(view, t2)
QTest.mouseMove(view.viewport(), vp2)
app.processEvents()
expected2, kind2 = view.snap.aim(
    view.mapToScene(vp2), exclude=view._snap_scan_exclude(), always=True)
QTest.keyClick(view, Qt.Key_T)
app.processEvents()
QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=vp2)
app.processEvents()
lines = [it for it in scene.all_items() if it.TYPE == "line"]
check("第二个点也吸附，两点完成直线",
      len(lines) == 1 and not scene.drawing_active(),
      f"lines={len(lines)} active={scene.drawing_active()}")
if lines:
    rec = lines[0].page_record()
    head = rec.get("head_pos") or {}
    end = rec.get("end_pos") or {}
    p1 = scene.projection.inverse_point(expected1.x(), expected1.y())
    p2 = scene.projection.inverse_point(expected2.x(), expected2.y())
    check("线段首尾 = 两次吸附点的 page 坐标",
          math.hypot(head.get("x", 0) - p1[0], head.get("y", 0) - p1[1]) < 1.0
          and math.hypot(end.get("x", 0) - p2[0],
                         end.get("y", 0) - p2[1]) < 1.0,
          f"head={head} end={end} expect=({p1},{p2})")
check("预览与落点共用同一入口（绘制工具未被抢走）",
      view._draw_type == "line" and not view.is_following())
scene.clearSelection()
view.close()
app.processEvents()

print("\n=== 4. 工具箱激活绘制后 T 键能到达画布（真机焦点链路） ===")
from Designer.CoreQGraphics.ui.design_window import DesignerWindow  # noqa: E402

window = DesignerWindow(SOURCE_PAGE)
window.show()
app.processEvents()
wv = window.view
wv.snap.enabled = False
button = next((b for b in window.toolbox.buttons if b.key == "line"), None)
check("工具箱含直线按钮", button is not None)
if button is not None:
    QTest.mouseClick(button, Qt.LeftButton)
    app.processEvents()
    check("点击工具箱按钮后焦点回到画布",
          QApplication.focusWidget() is wv,
          f"focus={QApplication.focusWidget()}")
    check("工具箱真实激活了绘制工具", wv._draw_type == "line")
    QTest.keyClick(QApplication.focusWidget(), Qt.Key_T)
    app.processEvents()
    check("按 T 真实打开吸附门控（不再被 Dock 吃掉）", wv.snap.enabled,
          f"enabled={wv.snap.enabled}")
    check("激活绘制时点表已建好（page_1 全部图元）",
          sum(view_count for view_count in wv.snap.count()) > 1000,
          f"table={wv.snap.count()}")
window.scene.mark_saved()
window.close()
app.processEvents()

print("\n=== 5. 光标尚未进画布时按 T 不报错，门控仍生效 ===")
scene, view = new_pair()
rect = add_rect(scene, view)
view.snap.enabled = False
view.set_draw_tool("line")
view._set_hover(None)
view._last_hover = None
QTest.keyClick(view, Qt.Key_T)
app.processEvents()
check("无 hover 时按 T 安全打开门控、绘制态不中断",
      view.snap.enabled and view._draw_type == "line"
      and not view.is_snap_grabbing(),
      f"enabled={view.snap.enabled} hover={view.snap.hover}")
scene.clearSelection()
view.close()
app.processEvents()

print("\n" + "=" * 60)
if FAILURES:
    print(f"FAILED: {len(FAILURES)} 项")
    for name in FAILURES:
        print("  -", name)
    sys.exit(1)
print("ALL PASS：绘制态 T 吸附全链路通过")
