"""嵌入式 QWidget（widget_element）承载层的回归校验。

校验内容：
1. 设计模式不创建承载层（不白建 QGraphicsView）；
2. 切运行模式后真实控件出现，几何 = 图元中心 ± 设计尺寸 × scale；
3. 缩放只改变 view 变换与像素几何，控件自身尺寸保持设计尺寸（文字矢量缩放）；
4. 旋转 30° 后，view 几何 = 旋转后包围盒，且控件跟着转；
5. 删除图元时承载层被回收（不留幽灵窗口）。

用法::

    .venv/Scripts/python.exe tools/verify_embedded_widget.py
    .venv/Scripts/python.exe tools/verify_embedded_widget.py --shot build/widget_shots
"""

from __future__ import annotations

import argparse
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTextEdit

from Designer.Core.elements import widget_element
from Designer.Core.my_common import SceneMode
from tools.bench_scene import DEFAULT_PAGE, build_scene

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "OK  " if condition else "FAIL"
    print(f"[{status}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        FAILURES.append(name)


def expected_geometry(item, scene, scale: float, angle: float) -> QRectF:
    """按承载层的约定推算 view 应有的窗口几何。"""
    w = item.scene_size.height() * scene.grid_size / scene.scene_units_per_grid_y
    h = item.scene_size.width() * scene.grid_size / scene.scene_units_per_grid_x
    center = scene.pos_viewToWindow(scene.sceneToView(item.get_scene_center_pos()))

    theta = math.radians(angle)
    bbox_w = abs(w * math.cos(theta)) + abs(h * math.sin(theta))
    bbox_h = abs(w * math.sin(theta)) + abs(h * math.cos(theta))
    bbox_w *= scale
    bbox_h *= scale
    return QRectF(
        center.x() - bbox_w / 2.0,
        center.y() - bbox_h / 2.0,
        bbox_w,
        bbox_h,
    )


def close_rect(actual: QRectF, expected: QRectF, tol: float = 2.5) -> bool:
    return (
        abs(actual.x() - expected.x()) <= tol
        and abs(actual.y() - expected.y()) <= tol
        and abs(actual.width() - expected.width()) <= tol
        and abs(actual.height() - expected.height()) <= tol
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shot", default="", help="把关键状态截图存到该目录")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    scene = build_scene(DEFAULT_PAGE)
    scene.resize(900, 560)
    manager = scene.scene_manager

    item = manager.createItem(widget_element)
    origin = QPointF(0.0, 0.0)
    item.transfer_head_pos(origin)
    item.transfer_end_pos(origin + QPointF(160.0, 160.0))

    def center_element() -> None:
        """把图元中心拉到窗口中心（只改视图原点，便于截图观察）。"""
        center_view = scene.sceneToView(item.get_scene_center_pos())
        scene.view_x0 = center_view.x() - 450.0 / scene.scale_factor
        scene.view_y0 = center_view.y() - 280.0 / scene.scale_factor
        scene.offset = QPointF(
            -scene.view_x0 * scene.scale_factor, -scene.view_y0 * scene.scale_factor
        )

    scene.scale_factor = 1.0
    center_element()

    # --- 1. 设计模式：也加载承载层，但只读展示（鼠标穿透） ----------
    scene.set_scene_mode(SceneMode.Design)
    check("设计模式创建承载层", item._layer is not None and item._layer.is_active())
    check("设计模式控件只读穿透",
          item._layer is not None
          and item._layer.widget is not None
          and item._layer.widget.testAttribute(Qt.WA_TransparentForMouseEvents))

    design_children = [
        child for child in scene.children() if type(child).__name__ == "QGraphicsView"
    ]
    check("设计模式场景下存在 QGraphicsView（承载层）", bool(design_children),
          f"发现 {len(design_children)} 个")

    # --- 2. 运行模式：控件出现且几何正确 -----------------------------
    scene.scale_factor = 1.0
    scene.set_scene_mode(SceneMode.Run)
    layer = item._layer
    check("运行模式创建承载层", layer is not None and layer.is_active())
    check("承载视图可见", layer is not None and layer.view.isVisible())
    check("承载控件是 QTextEdit", isinstance(layer.widget, QTextEdit),
          type(layer.widget).__name__ if layer.widget else "None")

    design_size = item._view_design_size()
    # AGV 场景里场景 x ↔ 视图 y 是交换的，所以 160x40 的场景矩形在视图里是
    # 10x40；直接用 viewBoundingRect（0° 时即未旋转的视图尺寸）做基准。
    view_size = item.viewBoundingRect().size()
    check("设计尺寸与 viewBoundingRect 一致",
          abs(design_size.width() - view_size.width()) < 0.5
          and abs(design_size.height() - view_size.height()) < 0.5,
          f"{design_size.width():.1f}x{design_size.height():.1f} "
          f"vs {view_size.width():.1f}x{view_size.height():.1f}")
    check("控件自身尺寸 = 设计尺寸",
          layer.widget.size().width() == int(round(design_size.width()))
          and layer.widget.size().height() == int(round(design_size.height())),
          f"{layer.widget.width()}x{layer.widget.height()}")

    geo_1x = QRectF(layer.view.geometry())
    check("1.0x 几何正确", close_rect(geo_1x, expected_geometry(item, scene, 1.0, 0.0)),
          f"{geo_1x.x():.0f},{geo_1x.y():.0f} {geo_1x.width():.0f}x{geo_1x.height():.0f}")

    # --- 2b. 焦点与键盘输入 ------------------------------------------
    # 回归点：承载 view 曾经是 Qt.NoFocus，点击后只有"逻辑焦点"
    # （widget.hasFocus() 为 True），系统焦点仍在主场景，按键全被主场景吃掉，
    # 表现为"点得进去但打不了字"。这里用真实点击 + 真实按键复现整条链路。
    view = layer.view
    viewport = view.viewport()
    QTest.mouseClick(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(viewport.width() // 2, viewport.height() // 2),
    )
    app.processEvents()
    focus_widget = app.focusWidget()
    check("承载视图获得真实键盘焦点", view.hasFocus(),
          f"app.focusWidget={type(focus_widget).__name__ if focus_widget else None}")
    check("点击命中被承载控件", layer.widget.hasFocus(),
          f"view.hasFocus={view.hasFocus()}")

    target = focus_widget if focus_widget is not None else view
    # 默认控件 QTextEdit 是只读的，键盘输入回归前先放开只读。
    if isinstance(layer.widget, QTextEdit):
        layer.widget.setReadOnly(False)
    layer.widget.setPlainText("")
    QTest.keyClicks(target, "AB")
    app.processEvents()
    check("键盘输入进入控件", layer.widget.toPlainText() == "AB",
          repr(layer.widget.toPlainText()))

    layer.widget.clearFocus()
    scene.setFocus()
    app.processEvents()

    # --- 2c. 在控件上拖动 = 平移画布 ---------------------------------
    # 场景的平移是 offset += 鼠标位移，但控件矩形上的事件被 overlay 视图接走，
    # 所以承载层要把"拖动"识别出来交回场景。这里直接构造鼠标事件序列，
    # 验证位移量与视图跟随（真实点击路径由 2b 覆盖）。
    def send_mouse(etype, global_pos, button, buttons):
        local = viewport.mapFromGlobal(global_pos)
        ev = QMouseEvent(
            etype,
            QPointF(local),
            QPointF(global_pos),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(viewport, ev)

    center = QPoint(viewport.width() // 2, viewport.height() // 2)
    offset_before = QPointF(scene.offset)
    geo_before = QPointF(layer.view.geometry().topLeft())
    start_global = viewport.mapToGlobal(center)

    send_mouse(QEvent.Type.MouseButtonPress, start_global,
               Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    for step in range(1, 5):
        send_mouse(
            QEvent.Type.MouseMove,
            QPoint(start_global.x() + step * 10, start_global.y() + step * 5),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
    send_mouse(
        QEvent.Type.MouseButtonRelease,
        QPoint(start_global.x() + 40, start_global.y() + 20),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
    )
    app.processEvents()

    drag_delta = scene.offset - offset_before
    geo_delta = QPointF(layer.view.geometry().topLeft()) - geo_before
    check("控件上左键拖动可平移画布",
          abs(drag_delta.x() - 40.0) <= 1.5 and abs(drag_delta.y() - 20.0) <= 1.5,
          f"offset 位移 {drag_delta.x():.0f},{drag_delta.y():.0f}（期望 40,20）")
    check("平移时承载视图跟着移动",
          abs(geo_delta.x() - drag_delta.x()) <= 1.5
          and abs(geo_delta.y() - drag_delta.y()) <= 1.5,
          f"view 位移 {geo_delta.x():.0f},{geo_delta.y():.0f}")

    # 微动（小于拖动阈值）不能触发平移，仍按点击处理
    offset_after_drag = QPointF(scene.offset)
    tap_global = viewport.mapToGlobal(center)
    send_mouse(QEvent.Type.MouseButtonPress, tap_global,
               Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    send_mouse(QEvent.Type.MouseMove, QPoint(tap_global.x() + 2, tap_global.y() + 1),
               Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    send_mouse(QEvent.Type.MouseButtonRelease, QPoint(tap_global.x() + 2, tap_global.y() + 1),
               Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    app.processEvents()
    check("微动不超过阈值时不平移", scene.offset == offset_after_drag,
          f"offset={scene.offset.x():.0f},{scene.offset.y():.0f}")
    check("微动按点击处理（控件获焦）", layer.widget.hasFocus())

    # 还原平移，避免影响后面的几何断言
    scene.offset = offset_before
    scene.update_coordinate()
    scene._sync_embedded_widgets_geometry()
    layer.widget.clearFocus()
    scene.setFocus()
    app.processEvents()

    # --- 3. 缩放：只改 view 变换与像素几何 ---------------------------
    scene.scale_factor = 2.0
    scene._sync_embedded_widgets_geometry()
    geo_2x = QRectF(layer.view.geometry())
    check("2.0x 几何 = 1.0x 的两倍",
          abs(geo_2x.width() - geo_1x.width() * 2) <= 3
          and abs(geo_2x.height() - geo_1x.height() * 2) <= 3,
          f"{geo_2x.width():.0f}x{geo_2x.height():.0f}")
    check("缩放不改控件自身尺寸",
          layer.widget.width() == int(round(design_size.width())))
    check("视图变换缩放 = scale_factor",
          abs(layer.view.transform().m11() - 2.0) < 1e-6,
          f"m11={layer.view.transform().m11():.3f}")

    scene.scale_factor = 0.5
    scene._sync_embedded_widgets_geometry()
    geo_05 = QRectF(layer.view.geometry())
    check("0.5x 几何 = 1.0x 的一半",
          abs(geo_05.width() - geo_1x.width() * 0.5) <= 3,
          f"{geo_05.width():.0f}")

    # --- 4. 旋转 -----------------------------------------------------
    scene.scale_factor = 1.0
    scene._sync_embedded_widgets_geometry()
    item.rotate_to_ang(30)
    scene._sync_embedded_widgets_geometry()
    angle = item.sceneTransform().get_rotation_angle()
    check("图元角度 = 30°", abs(angle - 30.0) < 0.5, f"{angle:.2f}")

    geo_rot = QRectF(layer.view.geometry())
    check("旋转后包围盒正确", close_rect(geo_rot, expected_geometry(item, scene, 1.0, angle), 3.5),
          f"{geo_rot.width():.0f}x{geo_rot.height():.0f} "
          f"(预期 {expected_geometry(item, scene, 1.0, angle).width():.0f}x"
          f"{expected_geometry(item, scene, 1.0, angle).height():.0f})")
    check("proxy 旋转与 painter 同向", abs(layer.proxy.rotation() + angle) < 0.5,
          f"proxy.rotation={layer.proxy.rotation():.2f}")
    check("proxy 真正接管了控件", layer.proxy.widget() is layer.widget)

    # 缩放 + 旋转同时生效
    scene.scale_factor = 2.0
    scene._sync_embedded_widgets_geometry()
    geo_mix = QRectF(layer.view.geometry())
    check("2.0x + 30° 包围盒正确",
          close_rect(geo_mix, expected_geometry(item, scene, 2.0, angle), 4.5),
          f"{geo_mix.width():.0f}x{geo_mix.height():.0f}")
    scene.scale_factor = 1.0
    scene._sync_embedded_widgets_geometry()

    # --- 4b. 自定义工厂重建 ------------------------------------------
    from PySide6.QtWidgets import QPushButton

    item.set_widget_factory(lambda host: QPushButton("确定", host))
    check("自定义工厂生效（QPushButton）", isinstance(layer.widget, QPushButton),
          type(layer.widget).__name__ if layer.widget else "None")
    check("重建后 proxy 仍接管控件", layer.proxy.widget() is layer.widget)
    geo_re = QRectF(layer.view.geometry())
    exp_re = expected_geometry(item, scene, 1.0, angle)
    check("重建后几何仍正确", close_rect(geo_re, exp_re, 3.5),
          f"{geo_re.x():.0f},{geo_re.y():.0f} {geo_re.width():.0f}x{geo_re.height():.0f} "
          f"vs 预期 {exp_re.x():.0f},{exp_re.y():.0f} {exp_re.width():.0f}x{exp_re.height():.0f}")

    if args.shot:
        out_dir = args.shot
        os.makedirs(out_dir, exist_ok=True)
        scene.grab().save(os.path.join(out_dir, "run_angle30.png"))
        scene.set_scene_mode(SceneMode.Design)
        scene.grab().save(os.path.join(out_dir, "design_angle30.png"))
        scene.set_scene_mode(SceneMode.Run)
        scene.scale_factor = 2.0
        scene._sync_embedded_widgets_geometry()
        scene.scale_factor = 2.0
        center_element()
        scene._sync_embedded_widgets_geometry()
        scene.grab().save(os.path.join(out_dir, "run_angle30_scale2.png"))
        print(f"截图已保存到 {out_dir}")

    # --- 5. 删除回收 -------------------------------------------------
    view = layer.view
    item.Delete()
    check("删除后承载层已释放", item._layer is None)
    check("删除后视图随之销毁", not view.isVisible())

    print()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项: {FAILURES}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
