"""change_size 锚点回归：无父图元改尺寸时旋转中心保持场景位置不变。

背景：``change_size``（属性面板改宽/高）以前一律以左上角（head_pos）为基准，
图元转过角度之后再改尺寸就会沿着旋转方向滑动，旋转中心也跟着跳到新包围盒
中心。现在无父图元时以旋转中心（变换原点 m_origin）为锚点等比缩放；有父图元
（组内子图元）时保持原来的左上角语义，由父图元的子图元缩放逻辑驱动。

用法：.venv/Scripts/python.exe tools/verify_resize_anchor.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QObject, QPointF, QSizeF, Signal
from PySide6.QtWidgets import QApplication

results: list[tuple[str, bool, str]] = []

EPS = 1e-6


class StubScene(QObject):
    """text_element 只用到 grid_size / 网格换算与两个脏区域信号。"""

    shine_flag_change = Signal()
    item_DirtyChange = Signal(object)
    item_GeometryChange = Signal(object)

    scene_units_per_grid_x = 10.0
    scene_units_per_grid_y = 10.0
    grid_size = 10.0
    scale_factor = 1.0

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def near(a: QPointF, b: QPointF, eps: float = EPS) -> bool:
    return abs(a.x() - b.x()) <= eps and abs(a.y() - b.y()) <= eps


def fmt(p: QPointF) -> str:
    return f"({p.x():.4f}, {p.y():.4f})"


def make_rect(width: float = 100.0, height: float = 60.0):
    """按 completed() 的约定手工铺一套几何：局部中心在原点，m_pos 是世界中心。"""
    from Designer.Core.elements import rect_element

    item = rect_element()
    item.set_actived(False)
    item.setSize(width, height)
    half_w = width / 2.0
    half_h = height / 2.0
    item._head_pos = QPointF(-half_w, -half_h)
    item._end_pos = QPointF(half_w, half_h)
    item._topLeft = QPointF(-half_w, -half_h)
    item._bottomRight = QPointF(half_w, half_h)
    item._topRight = QPointF(half_w, -half_h)
    item._bottomLeft = QPointF(-half_w, half_h)
    item._center_pos = QPointF(0.0, 0.0)
    item.setTransformOriginPoint(QPointF(0.0, 0.0))
    item.m_pos = QPointF(0.0, 0.0)
    item.m_pos_init = QPointF(0.0, 0.0)
    return item


def make_text():
    """按 text_element.completed() 的约定铺几何：左上角在局部 (0,0)，中心是旋转中心。"""
    from Designer.Core.elements import text_element

    item = text_element()
    item.set_scene_ref(StubScene())
    item.set_actived(False)
    width, height = 100.0, 50.0
    item.setSize(width, height)
    item.width = width
    item.height = height
    item._scene_size = QSizeF(width, height)
    item._head_pos = QPointF(0.0, 0.0)
    item._end_pos = QPointF(width, height)
    item._topLeft = QPointF(0.0, 0.0)
    item._bottomRight = QPointF(width, height)
    item._topRight = QPointF(width, 0.0)
    item._bottomLeft = QPointF(0.0, height)
    item._center_pos = QPointF(width / 2.0, height / 2.0)
    item.setTransformOriginPoint(QPointF(width / 2.0, height / 2.0))
    item.m_pos = QPointF(800.0, 600.0)
    item.m_pos_init = QPointF(800.0, 600.0)
    item.setRotation(-25.0)
    return item


def make_triangle(width: float = 100.0, height: float = 60.0):
    """三角形：局部坐标以中心为原点，旋转中心默认也在中心。"""
    from Designer.Core.elements import triangle_element

    item = triangle_element()
    item.set_actived(False)
    item._vertices_local = item._default_local_vertices(width, height)
    item._refresh_local_bounds()
    item.setTransformOriginPoint(QPointF(0.0, 0.0))
    item.m_pos = QPointF(600.0, 500.0)
    item.m_pos_init = QPointF(600.0, 500.0)
    item.setRotation(35.0)
    return item


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841
    from Designer.Core.elements import circle_element

    # ---- 1. 未旋转、旋转中心=图元中心：绕中心等比缩放 ----
    item = make_rect()
    item.m_pos = QPointF(500.0, 400.0)
    pivot_before = item.get_scene_transformOriginPoint()
    center_before = item.get_scene_center_pos()
    item.change_size(200.0, 120.0)
    check("未旋转：尺寸已更新",
          (item.getSize().width(), item.getSize().height()) == (200.0, 120.0),
          f"{item.getSize().width()}x{item.getSize().height()}")
    check("未旋转：旋转中心场景位置不变",
          near(item.get_scene_transformOriginPoint(), pivot_before),
          f"{fmt(pivot_before)} -> {fmt(item.get_scene_transformOriginPoint())}")
    check("未旋转：中心仍与旋转中心重合",
          near(item.get_scene_center_pos(), center_before),
          f"{fmt(center_before)} -> {fmt(item.get_scene_center_pos())}")

    # ---- 2. 旋转 30°、旋转中心=中心：锚点仍是中心，不是左上角 ----
    item = make_rect()
    item.m_pos = QPointF(500.0, 400.0)
    item.setRotation(30.0)
    pivot_before = item.get_scene_transformOriginPoint()
    head_before = item.get_scene_head_pos()
    item.change_size(200.0, 120.0)
    check("旋转 30°：旋转中心场景位置不变",
          near(item.get_scene_transformOriginPoint(), pivot_before),
          f"{fmt(pivot_before)} -> {fmt(item.get_scene_transformOriginPoint())}")
    check("旋转 30°：左上角不再是锚点（会跟着缩放移动）",
          not near(item.get_scene_head_pos(), head_before),
          f"{fmt(head_before)} -> {fmt(item.get_scene_head_pos())}")
    item.rotate_to_ang(90.0)
    check("改尺寸后再旋转，仍绕同一个场景点",
          near(item.get_scene_transformOriginPoint(), pivot_before),
          f"{fmt(pivot_before)} -> {fmt(item.get_scene_transformOriginPoint())}")

    # ---- 3. 旋转 + 偏移的旋转中心（右键设置的基点）：基点锚定 ----
    item = make_rect()
    item.m_pos = QPointF(500.0, 400.0)
    item.setTransformOriginPoint(QPointF(-30.0, -15.0))
    item.setRotation(30.0)
    pivot_before = item.get_scene_transformOriginPoint()
    head_local_before = QPointF(item.get_head_pos().x(), item.get_head_pos().y())
    item.change_size(200.0, 120.0)
    check("偏移基点：旋转中心场景位置不变",
          near(item.get_scene_transformOriginPoint(), pivot_before),
          f"{fmt(pivot_before)} -> {fmt(item.get_scene_transformOriginPoint())}")
    check("偏移基点：基点没有被重置成新中心",
          near(QPointF(item.transformOriginPoint().x(), item.transformOriginPoint().y()),
               QPointF(-30.0, -15.0)),
          fmt(item.transformOriginPoint()))
    expect_head = QPointF(-30.0 + (head_local_before.x() + 30.0) * 2.0,
                          -15.0 + (head_local_before.y() + 15.0) * 2.0)
    check("偏移基点：局部几何按锚点等比缩放",
          near(QPointF(item.get_head_pos().x(), item.get_head_pos().y()), expect_head),
          f"{fmt(item.get_head_pos())} expect {fmt(expect_head)}")

    # ---- 4. 连续改尺寸：锚点保持稳定 ----
    pivot_now = item.get_scene_transformOriginPoint()
    item.change_size(120.0, 90.0)
    item.change_size(300.0, 200.0)
    check("连续改尺寸：旋转中心仍不放跑",
          near(item.get_scene_transformOriginPoint(), pivot_now),
          f"{fmt(pivot_now)} -> {fmt(item.get_scene_transformOriginPoint())}")

    # ---- 5. 有父图元：保持原语义（左上角锚定 + 中心重置） ----
    parent = make_rect(width=200.0, height=200.0)
    parent.m_pos = QPointF(300.0, 300.0)
    child = make_rect(width=50.0, height=50.0)
    child.m_parent = parent
    parent.m_children.add(child)
    child.setRotation(20.0)
    head_before = child.get_scene_head_pos()
    child.change_size(100.0, 100.0)
    check("组内子图元：左上角仍是锚点",
          near(child.get_scene_head_pos(), head_before),
          f"{fmt(head_before)} -> {fmt(child.get_scene_head_pos())}")
    check("组内子图元：旋转中心按旧语义重置为包围盒中心",
          near(QPointF(child.transformOriginPoint().x(), child.transformOriginPoint().y()),
               QPointF(child.get_center_pos().x(), child.get_center_pos().y())),
          f"origin={fmt(child.transformOriginPoint())} center={fmt(child.get_center_pos())}")

    # ---- 6. 顶层父图元改尺寸：子图元跟着绕同一个锚点缩放 ----
    parent = make_rect(width=200.0, height=200.0)
    parent.m_pos = QPointF(300.0, 300.0)
    child = make_rect(width=50.0, height=50.0)
    child.m_parent = parent
    parent.m_children.add(child)
    pivot_parent = parent.get_scene_transformOriginPoint()
    parent.change_size(400.0, 400.0)
    check("顶层父图元：旋转中心场景位置不变",
          near(parent.get_scene_transformOriginPoint(), pivot_parent),
          f"{fmt(pivot_parent)} -> {fmt(parent.get_scene_transformOriginPoint())}")
    check("顶层父图元：子图元尺寸同比放大",
          (child.getSize().width(), child.getSize().height()) == (100.0, 100.0),
          f"{child.getSize().width()}x{child.getSize().height()}")
    check("顶层父图元：子图元中心仍压在锚点上",
          near(child.get_scene_center_pos(), pivot_parent),
          f"{fmt(child.get_scene_center_pos())} expect {fmt(pivot_parent)}")

    # ---- 7. 圆（椭圆）图元按 center 保持 ----
    circle = circle_element()
    circle.setSize(100.0, 100.0)
    circle.set_head_pos(QPointF(0.0, 0.0))
    circle.set_end_pos(QPointF(100.0, 100.0))
    circle.set_center_pos(QPointF(50.0, 50.0))
    circle._topLeft = QPointF(0.0, 0.0)
    circle._bottomRight = QPointF(100.0, 100.0)
    circle._topRight = QPointF(100.0, 0.0)
    circle._bottomLeft = QPointF(0.0, 100.0)
    circle.setTransformOriginPoint(QPointF(50.0, 50.0))
    circle.m_pos = QPointF(200.0, 200.0)
    circle.setRotation(45.0)
    pivot_before = circle.get_scene_transformOriginPoint()
    circle.change_size(300.0, 300.0)
    check("圆：旋转中心场景位置不变",
          near(circle.get_scene_transformOriginPoint(), pivot_before),
          f"{fmt(pivot_before)} -> {fmt(circle.get_scene_transformOriginPoint())}")
    check("圆：半径已更新",
          (circle.getSize().width(), circle.getSize().height()) == (300.0, 300.0),
          f"{circle.getSize().width()}x{circle.getSize().height()}")

    # ---- 8. 文本图元（左上角局部坐标 + 中心为旋转中心）同样锚定中心 ----
    text = make_text()
    pivot_before = text.get_scene_transformOriginPoint()
    text.change_size(400.0, 0.0)
    check("文本：旋转中心场景位置不变",
          near(text.get_scene_transformOriginPoint(), pivot_before),
          f"{fmt(pivot_before)} -> {fmt(text.get_scene_transformOriginPoint())}")
    check("文本：宽度已生效",
          abs(text.getSize().width() - 400.0) < EPS,
          f"{text.getSize().width()}")
    check("文本：包围盒中心仍与旋转中心重合",
          near(QPointF(text.get_center_pos().x(), text.get_center_pos().y()),
               QPointF(text.transformOriginPoint().x(),
                       text.transformOriginPoint().y())),
          f"center={fmt(text.get_center_pos())} origin={fmt(text.transformOriginPoint())}")

    # ---- 9. 三角形（顶点缩放）同样锚定旋转中心 ----
    tri = make_triangle()
    pivot_before = tri.get_scene_transformOriginPoint()
    tri.change_size(200.0, 120.0)
    check("三角形：旋转中心场景位置不变",
          near(tri.get_scene_transformOriginPoint(), pivot_before),
          f"{fmt(pivot_before)} -> {fmt(tri.get_scene_transformOriginPoint())}")
    check("三角形：包围盒已更新",
          (round(tri.getSize().width(), 6), round(tri.getSize().height(), 6)) == (200.0, 120.0),
          f"{tri.getSize().width()}x{tri.getSize().height()}")
    check("三角形：顶点绕锚点等比放大",
          near(tri._vertices_local[0], QPointF(0.0, 60.0)),
          fmt(tri._vertices_local[0]))

    return _report()


def _report() -> int:
    failed = 0
    for name, ok, detail in results:
        if not ok:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
