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

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from Designer.Core.elements import rect_element, widget_element
from Designer.Core.embedded_widget_layer import EmbeddedWidgetLayer
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

    # --- 0b. 命中范围：整块矩形都可命中（不是只有边框） --------------
    #
    # 回归点：``rect_element.check_hover`` 对无填充矩形只认"边框往里 10px /
    # 往外 10~20px"那条带，中间挖空（空心框整块可点会挡住下面的图元）。
    # widget_element 继承了它 → 设计态点控件中间毫无反应，只能贴边点中。
    hover_item = manager.createItem(widget_element)
    hover_item.transfer_head_pos(QPointF(0.0, 0.0))
    hover_item.transfer_end_pos(QPointF(160.0, 400.0))
    hover_item.completed()
    # completed() 之后仍在"移动中"，正常由 paint 里的 _reset_moving_flag 清掉
    hover_item._reset_moving_flag()
    hover_tf = hover_item.sceneTransform()

    def hover_at(local: QPointF) -> bool:
        hit = hover_item.check_hover(hover_tf.map(local))
        hover_item.set_hover(False)
        return bool(hit)

    check("控件图元中心可命中", hover_at(QPointF(0.0, 0.0)))
    check("控件图元靠近边可命中", hover_at(QPointF(70.0, 70.0)) and hover_at(QPointF(0.0, 190.0)))
    check("控件图元外部不命中", not hover_at(QPointF(90.0, 0.0)))
    check("控件图元纵向外部不命中", not hover_at(QPointF(0.0, 300.0)))
    # 对照：父类规则下同一位置（中心）判不中，说明这层覆写是必需的
    check(
        "对照：rect_element 旧规则中心不命中",
        not rect_element.check_hover(hover_item, hover_tf.map(QPointF(0.0, 0.0))),
    )
    # 选中链路：single_select_handle 只认 get_hover()，中心命中必须能落到选中
    hover_item.check_hover(hover_tf.map(QPointF(0.0, 0.0)))
    check(
        "点中间能被单选选中",
        scene.single_select_handle() and hover_item.get_selected(),
    )
    hover_item.set_selected(False)
    hover_item.Delete()

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

    # --- 2c. 拖动：非交互区域 = 平移画布，按住语义控件 = 直通 ----------
    # 承载层对左键做"延迟派发"：按下先扣住，超过阈值判为拖动画布，没超阈值
    # 判为点击。但按在按钮 / 输入框 / 表格 / 文本区这类控件上必须**立刻直通**
    # ——否则按住期间控件收不到 press，点动按钮会在松手那一刻才补发
    # press+release，业务上看到的就是"按下即抬起"。
    def send_mouse(etype, global_pos, button, buttons, target=None):
        widget = target if target is not None else viewport
        local = widget.mapFromGlobal(global_pos)
        ev = QMouseEvent(
            etype,
            QPointF(local),
            QPointF(global_pos),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(widget, ev)

    center = QPoint(viewport.width() // 2, viewport.height() // 2)

    # (a) 文本区上按住：必须立刻直通，控件自己吃掉整个手势
    offset_before = QPointF(scene.offset)
    start_global = viewport.mapToGlobal(center)
    send_mouse(QEvent.Type.MouseButtonPress, start_global,
               Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    app.processEvents()
    check("文本区按住立刻直通（press 不被扣住）",
          layer._press_pending is False,
          f"_press_pending={layer._press_pending}")
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
    check("文本区上拖动不平移画布", scene.offset == offset_before,
          f"offset={scene.offset.x():.0f},{scene.offset.y():.0f}")

    # (b) 另建一个承载「容器 + 标签」的层：按在卡片空白处仍能拖画布
    canvas_layer = EmbeddedWidgetLayer(scene)
    canvas_holder = QWidget()
    canvas_holder.setMinimumSize(1, 1)
    canvas_lay = QVBoxLayout(canvas_holder)
    canvas_lay.setContentsMargins(0, 0, 0, 0)
    canvas_lay.addWidget(QLabel("空白区域"))
    canvas_layer.set_widget(canvas_holder)
    canvas_layer.apply(QPointF(140.0, 120.0), QSizeF(160.0, 120.0), 1.0, 0.0)
    canvas_layer.set_visible(True)
    app.processEvents()

    canvas_viewport = canvas_layer._viewport
    canvas_center = QPoint(canvas_viewport.width() // 2, canvas_viewport.height() // 2)
    offset_before = QPointF(scene.offset)
    geo_before = QPointF(layer.view.geometry().topLeft())
    start_global = canvas_viewport.mapToGlobal(canvas_center)

    send_mouse(QEvent.Type.MouseButtonPress, start_global,
               Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
               canvas_viewport)
    for step in range(1, 5):
        send_mouse(
            QEvent.Type.MouseMove,
            QPoint(start_global.x() + step * 10, start_global.y() + step * 5),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            canvas_viewport,
        )
    send_mouse(
        QEvent.Type.MouseButtonRelease,
        QPoint(start_global.x() + 40, start_global.y() + 20),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        canvas_viewport,
    )
    app.processEvents()

    drag_delta = scene.offset - offset_before
    geo_delta = QPointF(layer.view.geometry().topLeft()) - geo_before
    check("非交互区域上拖动可平移画布",
          abs(drag_delta.x() - 40.0) <= 1.5 and abs(drag_delta.y() - 20.0) <= 1.5,
          f"offset 位移 {drag_delta.x():.0f},{drag_delta.y():.0f}（期望 40,20）")
    check("平移时承载视图跟着移动",
          abs(geo_delta.x() - drag_delta.x()) <= 1.5
          and abs(geo_delta.y() - drag_delta.y()) <= 1.5,
          f"view 位移 {geo_delta.x():.0f},{geo_delta.y():.0f}")

    # 微动（小于拖动阈值）不能触发平移
    offset_after_drag = QPointF(scene.offset)
    tap_global = canvas_viewport.mapToGlobal(canvas_center)
    send_mouse(QEvent.Type.MouseButtonPress, tap_global,
               Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
               canvas_viewport)
    send_mouse(QEvent.Type.MouseMove, QPoint(tap_global.x() + 2, tap_global.y() + 1),
               Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
               canvas_viewport)
    send_mouse(QEvent.Type.MouseButtonRelease, QPoint(tap_global.x() + 2, tap_global.y() + 1),
               Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
               canvas_viewport)
    app.processEvents()
    check("微动不超过阈值时不平移", scene.offset == offset_after_drag,
          f"offset={scene.offset.x():.0f},{scene.offset.y():.0f}")

    canvas_layer.dispose()
    app.processEvents()

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

    # --- 4c. fit_widget_size：按控件像素尺寸反推图元尺寸 ---------------
    #
    # 回归点：``fit_widget_size(w, h)`` 走 ``change_size`` 改图元尺寸，换算口径
    # 必须和 ``_view_design_size`` 互逆 —— 改完以后控件自己的像素尺寸就应该
    # 正好等于传进来的 (w, h)，既不拉伸也不裁切；同时旋转中心（当前 30°）不能
    # 被顶跑。
    center_before_fit = item.get_scene_center_pos()
    pivot_before_fit = item.get_scene_transformOriginPoint()
    fitted = item.fit_widget_size(420, 260)
    scene._sync_embedded_widgets_geometry()
    check("fit_widget_size 返回换算后的场景尺寸",
          abs(fitted.width() - 260.0 * scene.scene_units_per_grid_x / scene.grid_size) <= 0.5
          and abs(fitted.height() - 420.0 * scene.scene_units_per_grid_y / scene.grid_size) <= 0.5,
          f"{fitted.width():.1f}x{fitted.height():.1f}")
    check("fit_widget_size 后控件自身像素尺寸 = 传入尺寸",
          abs(layer.widget.width() - 420) <= 1 and abs(layer.widget.height() - 260) <= 1,
          f"{layer.widget.width()}x{layer.widget.height()} (期望 420x260)")
    check("fit_widget_size 与 widget_pixel_size 互逆",
          abs(item.widget_pixel_size().width() - 420.0) <= 0.5
          and abs(item.widget_pixel_size().height() - 260.0) <= 0.5,
          f"{item.widget_pixel_size().width():.1f}x{item.widget_pixel_size().height():.1f}")
    check("fit_widget_size 后几何与旋转包围盒一致",
          close_rect(QRectF(layer.view.geometry()),
                     expected_geometry(item, scene, 1.0, item.sceneTransform().get_rotation_angle()),
                     3.5),
          f"{layer.view.geometry().width()}x{layer.view.geometry().height()}")
    check("fit_widget_size 不移动控件中心",
          abs(item.get_scene_center_pos().x() - center_before_fit.x()) <= 0.5
          and abs(item.get_scene_center_pos().y() - center_before_fit.y()) <= 0.5,
          f"({center_before_fit.x():.1f},{center_before_fit.y():.1f}) -> "
          f"({item.get_scene_center_pos().x():.1f},{item.get_scene_center_pos().y():.1f})")
    check("fit_widget_size 不动旋转中心",
          abs(item.get_scene_transformOriginPoint().x() - pivot_before_fit.x()) <= 0.5
          and abs(item.get_scene_transformOriginPoint().y() - pivot_before_fit.y()) <= 0.5,
          f"({pivot_before_fit.x():.1f},{pivot_before_fit.y():.1f}) -> "
          f"({item.get_scene_transformOriginPoint().x():.1f},"
          f"{item.get_scene_transformOriginPoint().y():.1f})")

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
