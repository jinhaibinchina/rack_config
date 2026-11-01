"""最小验证：自绘场景里能不能用「overlay QGraphicsView + QGraphicsProxyWidget」
承载真实 QWidget，并且同时支持 旋转 / 缩放 / 焦点 / 输入法。

结论要验证四件事：
1. 旋转 30° 之后，点击命中由 QGraphicsView 自己算，不需要手写逆变换派发；
2. 缩放时控件里的文字跟着一起缩放（ProxyWidget 走 painter 变换渲染）；
3. QLineEdit 能拿到真实焦点（focusInEvent 触发）；
4. 中文输入法的 inputMethodEvent 能进来（候选窗正常弹出）。

跑法：
    .venv/Scripts/python.exe tools/overlay_widget_probe.py
    .venv/Scripts/python.exe tools/overlay_widget_probe.py --shot build/probe_shots

--shot 只做离屏抓图（自动切几种角度/缩放存 PNG 后退出），用于回归。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# ----------------------------------------------------------------------
# 被承载的控件：把焦点 / 输入法事件打出来，作为验证证据
# ----------------------------------------------------------------------
class ProbeLineEdit(QLineEdit):
    def __init__(self, log, parent=None):
        super().__init__(parent)
        self._log = log
        self.setPlaceholderText("点我，然后用中文输入法打字")
        self.setText("输入测试 ABC 123")

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._log("[控件] focusInEvent  —— 拿到真实焦点")

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._log("[控件] focusOutEvent")

    def inputMethodEvent(self, event):
        super().inputMethodEvent(event)
        self._log(
            "[控件] inputMethodEvent preedit=%r commit=%r"
            % (event.preeditString(), event.commitString())
        )


# ----------------------------------------------------------------------
# overlay 层：一个真实控件 = 一个透明 QGraphicsView
# ----------------------------------------------------------------------
class EmbeddedWidgetLayer:
    """把 ``widget`` 挂到 ``host`` 上，位置/缩放/旋转由外部同步。

    几何约定（与 Designer/Core/elements.py 的 widget_element 对齐）：
    - ``widget`` 保持设计尺寸（scale=1.0 时的像素尺寸）；
    - 缩放交给 ``QGraphicsView.setTransform``，这样文字是矢量缩放，不会糊；
    - 旋转交给 proxy item，绕控件中心转；
    - 视图的 geometry 取「旋转后包围盒 × scale」，以 ``center`` 为中心。
    """

    def __init__(self, host: QWidget, widget: QWidget, log, name: str = "layer"):
        self.name = name
        self._log = log
        self.widget = widget

        view = QGraphicsView(host)
        view.setObjectName("embeddedWidgetView")
        view.setFrameShape(QFrame.NoFrame)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # 视图本身不进 Tab 链，但里面的控件仍然能被点击取得焦点。
        view.setFocusPolicy(Qt.NoFocus)
        view.setStyleSheet(
            "QGraphicsView { background: transparent; border: none; }"
        )
        view.viewport().setAutoFillBackground(False)
        view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        view.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        # 控件自己会重绘（光标闪烁），整屏刷新最省心。
        view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        view.setOptimizationFlag(
            QGraphicsView.OptimizationFlag.DontSavePainterState, True
        )
        self.view = view

        self.inner_scene = QGraphicsScene(view)
        view.setScene(self.inner_scene)

        self.proxy = self.inner_scene.addWidget(widget)
        # NoCache：每次重绘都真渲染，缩放大时文字更锐。
        self.proxy.setCacheMode(QGraphicsItem.CacheMode.NoCache)
        self.proxy.setTransformOriginPoint(
            widget.width() / 2.0, widget.height() / 2.0
        )

        self._scale = 1.0
        self._angle = 0.0
        self._center = QPointF(0.0, 0.0)
        self.apply()

    # -- 外部接口 ------------------------------------------------------
    def set_center(self, point: QPointF):
        if self._center != point:
            self._center = QPointF(point)
            self.apply()

    def set_scale(self, scale: float):
        scale = max(0.2, min(float(scale), 4.0))
        if abs(self._scale - scale) > 1e-6:
            self._scale = scale
            self.apply()

    def set_angle(self, angle: float):
        if abs(self._angle - float(angle)) > 1e-6:
            self._angle = float(angle)
            self.apply()

    def set_layer_visible(self, visible: bool):
        self.view.setVisible(bool(visible))

    # -- 几何同步 ------------------------------------------------------
    def apply(self):
        widget = self.widget
        # 旋转绕控件中心，所以 item 的 bbox 中心仍是 (w/2, h/2)。
        self.proxy.setRotation(self._angle)
        self.view.setTransform(QTransform().scale(self._scale, self._scale))

        bbox = self.proxy.mapToScene(self.proxy.boundingRect()).boundingRect()
        self.view.setSceneRect(bbox)

        size = bbox.size() * self._scale
        geo = QRect(
            int(round(self._center.x() - size.width() / 2.0)),
            int(round(self._center.y() - size.height() / 2.0)),
            max(1, int(round(size.width()))),
            max(1, int(round(size.height()))),
        )
        self.view.setGeometry(geo)


# ----------------------------------------------------------------------
# 假的自绘场景：只画网格 + 占位框，缩放/平移口径与项目里一致
# ----------------------------------------------------------------------
class SceneCanvas(QWidget):
    def __init__(self, log, parent=None):
        super().__init__(parent)
        self._log = log
        self.scale_factor = 1.0
        self.offset = QPointF(0.0, 0.0)
        self.element_center = QPointF(0.0, 0.0)   # 场景坐标
        self.element_size = QSizeF(280.0, 48.0)   # 场景单位（= scale 1.0 的像素）
        self.angle = 0.0
        self.layers: list[EmbeddedWidgetLayer] = []

        self._centered = False
        self._pan_origin = None
        self._pan_offset = None

        self.setMinimumSize(560, 420)
        self.setFocusPolicy(Qt.StrongFocus)

    # -- 坐标换算 ------------------------------------------------------
    def scene_to_view(self, point: QPointF) -> QPointF:
        return QPointF(
            point.x() * self.scale_factor + self.offset.x(),
            point.y() * self.scale_factor + self.offset.y(),
        )

    def view_to_scene(self, point: QPointF) -> QPointF:
        return QPointF(
            (point.x() - self.offset.x()) / self.scale_factor,
            (point.y() - self.offset.y()) / self.scale_factor,
        )

    def sync_layers(self):
        center = self.scene_to_view(self.element_center)
        for layer in self.layers:
            layer.set_center(center)
            layer.set_scale(self.scale_factor)
            layer.set_angle(self.angle)

    def set_scale(self, scale: float):
        self.scale_factor = max(0.2, min(float(scale), 4.0))
        self.sync_layers()
        self.update()

    def set_angle(self, angle: float):
        self.angle = float(angle)
        self.sync_layers()
        self.update()

    # -- 绘制 ----------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        if not self._centered:
            self._centered = True
            self.offset = QPointF(self.width() / 2.0, self.height() / 2.0)
            self.sync_layers()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._centered:
            self.offset = QPointF(self.width() / 2.0, self.height() / 2.0)
        self.sync_layers()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111827"))

        # 网格（跟着缩放走，和项目里一样）
        step = max(8.0, 40.0 * self.scale_factor)
        pen = QPen(QColor("#1f2937"), 1)
        painter.setPen(pen)
        x = self.offset.x() % step
        while x < self.width():
            painter.drawLine(int(x), 0, int(x), self.height())
            x += step
        y = self.offset.y() % step
        while y < self.height():
            painter.drawLine(0, int(y), self.width(), int(y))
            y += step

        # 图元占位框（旋转后），与 overlay 的包围盒应当严丝合缝
        center = self.scene_to_view(self.element_center)
        w = self.element_size.width() * self.scale_factor
        h = self.element_size.height() * self.scale_factor

        painter.save()
        painter.translate(center)
        painter.rotate(self.angle)
        rect = QRectF(-w / 2.0, -h / 2.0, w, h)
        painter.setPen(QPen(QColor("#22d3ee"), 1.5, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)
        painter.restore()

        # 提示文字（不进 overlay 区域）
        painter.setPen(QPen(QColor("#6b7280"), 1))
        font = QFont()
        font.setPointSizeF(9.0)
        painter.setFont(font)
        painter.drawText(
            QRect(int(center.x() - 200), int(center.y() + h), 400, 40),
            Qt.AlignHCenter | Qt.AlignTop,
            "虚线 = 图元占位框；里面的输入框是 overlay QGraphicsView",
        )
        painter.end()

    # -- 交互：Ctrl+滚轮缩放、中键平移 ---------------------------------
    def wheelEvent(self, event):
        if not (event.modifiers() & Qt.ControlModifier):
            return super().wheelEvent(event)
        pos = event.position()
        before = self.view_to_scene(pos)
        factor = 1.1 ** (event.angleDelta().y() / 120.0)
        self.scale_factor = max(0.2, min(self.scale_factor * factor, 4.0))
        self.offset = pos - before * self.scale_factor
        self.sync_layers()
        self.update()
        self._log("[场景] 缩放 %.2fx" % self.scale_factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._pan_origin = event.position()
            self._pan_offset = QPointF(self.offset)
            return
        # 走到这里说明点击没有落在 overlay 上：证明控件外不挡主场景。
        if event.button() == Qt.LeftButton:
            self._log("[场景] 主场景收到左键（控件外区域）")
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_origin is not None and event.buttons() & Qt.MiddleButton:
            self.offset = self._pan_offset + (event.position() - self._pan_origin)
            self.sync_layers()
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._pan_origin = None
            self._pan_offset = None
            return
        super().mouseReleaseEvent(event)


# ----------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------
class ProbeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("嵌入式 QWidget 验证：旋转 / 缩放 / 焦点 / 输入法")
        self.resize(1120, 700)

        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)

        self.canvas = SceneCanvas(self.log, self)

        self.lineedit = ProbeLineEdit(self.log)
        self.lineedit.setFixedSize(280, 48)
        self.layer = EmbeddedWidgetLayer(self.canvas, self.lineedit, self.log)
        self.canvas.layers.append(self.layer)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.canvas, 1)
        row.addWidget(self._build_panel())

        self.canvas.sync_layers()

    # -- 右侧控制面板 --------------------------------------------------
    def _build_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setFixedWidth(300)
        panel.setStyleSheet("QWidget { background: #0b1220; color: #e5e7eb; }")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("旋转", panel)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)
        angle_row = QHBoxLayout()
        for angle in (0, 15, 30, 45, 90):
            button = QPushButton(f"{angle}°", panel)
            button.clicked.connect(
                lambda checked=False, a=angle: self._on_angle(a)
            )
            angle_row.addWidget(button)
        layout.addLayout(angle_row)

        title = QLabel("缩放", panel)
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)
        zoom_row = QHBoxLayout()
        for scale in (0.5, 1.0, 1.5, 2.0):
            button = QPushButton(f"{scale:g}x", panel)
            button.clicked.connect(
                lambda checked=False, s=scale: self._on_scale(s)
            )
            zoom_row.addWidget(button)
        layout.addLayout(zoom_row)

        self.show_checkbox = QCheckBox("显示真实控件（关闭=设计模式只看占位框）", panel)
        self.show_checkbox.setChecked(True)
        self.show_checkbox.toggled.connect(self._on_toggle_layer)
        layout.addWidget(self.show_checkbox)

        focus_button = QPushButton("把焦点给输入框", panel)
        focus_button.clicked.connect(self._focus_widget)
        layout.addWidget(focus_button)

        hint = QLabel(
            "验证步骤：\n"
            "1. 点输入框 → 日志出现 focusInEvent；\n"
            "2. 切中文输入法打拼音 → 日志出现 inputMethodEvent（preedit）；\n"
            "3. 拖到 30° 后继续点字/选中 → 命中由 Qt 自己算；\n"
            "4. 点虚线外 → 日志出现「主场景收到左键」。",
            panel,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9ca3af;")
        layout.addWidget(hint)

        layout.addWidget(QLabel("事件日志", panel))
        layout.addWidget(self.log_view, 1)
        return panel

    # -- 槽 ------------------------------------------------------------
    def log(self, text: str):
        self.log_view.appendPlainText(text)

    def _on_angle(self, angle: int):
        self.canvas.set_angle(angle)
        self.log("[面板] 角度 = %d°" % angle)

    def _on_scale(self, scale: float):
        self.canvas.set_scale(scale)
        self.log("[面板] 缩放 = %.2fx" % scale)

    def _on_toggle_layer(self, checked: bool):
        self.layer.set_layer_visible(checked)
        self.log("[面板] 真实控件 %s" % ("显示" if checked else "隐藏"))

    def _focus_widget(self):
        self.lineedit.setFocus()
        self.log("[面板] setFocus() 已调用")


# ----------------------------------------------------------------------
def _run_shots(app: QApplication, window: ProbeWindow, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    states = [
        ("angle0_scale1", 0, 1.0),
        ("angle30_scale1", 30, 1.0),
        ("angle0_scale2", 0, 2.0),
        ("angle30_scale05", 30, 0.5),
    ]

    def step(index: int = 0):
        if index >= len(states):
            app.quit()
            return
        name, angle, scale = states[index]
        window._on_angle(angle)
        window._on_scale(scale)
        app.processEvents()
        window.grab().save(str(out_dir / f"{name}.png"))
        QTimer.singleShot(120, lambda: step(index + 1))

    QTimer.singleShot(250, step)


def _run_selftest(app: QApplication, window: ProbeWindow) -> None:
    """无人工干预地验证：命中路由、焦点、包围盒空白角吞点击。

    结论直接打到 stdout，跑完自动退出，可作为回归检查。
    """
    from PySide6.QtTest import QTest

    window._on_angle(30)
    window._on_scale(1.0)
    app.processEvents()
    QTest.qWait(80)

    layer = window.layer
    view = layer.view

    def window_point_of(local: QPointF) -> QPointF:
        """控件局部坐标 → 主窗口坐标。"""
        view_point = view.mapFromScene(layer.proxy.mapToScene(local))
        return QPointF(view.geometry().topLeft()) + QPointF(view_point)

    def report(title: str, window_point: QPointF) -> None:
        child = window.childAt(window_point.toPoint())
        names = []
        while child is not None and child is not window:
            names.append(type(child).__name__)
            child = child.parentWidget()
        print(f"{title:<28} childAt -> {'/'.join(names) if names else '(主场景)'}")

    center_local = QPointF(window.lineedit.width() / 2.0, window.lineedit.height() / 2.0)
    text_point = window_point_of(center_local)
    report("旋转中心（应命中控件）", text_point)

    # 包围盒的左上角：在 view 矩形内，但在旋转后的控件外。
    corner_point = QPointF(view.geometry().topLeft()) + QPointF(2, 2)
    report("包围盒空白角（预期被吞）", corner_point)

    # 真正点一下旋转后的中心，看焦点是否落到 QLineEdit。
    view_point = view.mapFromScene(layer.proxy.mapToScene(center_local))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, view_point)
    app.processEvents()
    print(
        "鼠标左键点击旋转后的控件中心 -> QLineEdit.hasFocus() =",
        window.lineedit.hasFocus(),
    )
    print(
        "光标位置 cursorPosition =",
        window.lineedit.cursorPosition(),
        "（>0 说明命中和光标定位由 Qt 自己算对了）",
    )

    # 键盘输入是否真的进控件
    before = window.lineedit.text()
    QTest.keyClicks(window.lineedit, "AB")
    app.processEvents()
    print("键盘输入: %r -> %r" % (before, window.lineedit.text()))

    # 输入法事件通道：这里只能验证「控件肯接收 QInputMethodEvent」，
    # 系统候选窗是否弹出必须人工用中文输入法试一次。
    from PySide6.QtGui import QInputMethodEvent

    ime_event = QInputMethodEvent()
    ime_event.setCommitString("中文")
    QApplication.sendEvent(window.lineedit, ime_event)
    app.processEvents()
    print("注入 IME commit 后文本 = %r" % window.lineedit.text())

    print("\n--- 事件日志 ---")
    print(window.log_view.toPlainText())
    app.quit()


def main(argv) -> int:
    app = QApplication(argv)
    window = ProbeWindow()
    window.show()

    if "--shot" in argv:
        index = argv.index("--shot")
        out_dir = Path(argv[index + 1]) if index + 1 < len(argv) else Path("build/probe_shots")
        _run_shots(app, window, out_dir)
    elif "--selftest" in argv:
        QTimer.singleShot(300, lambda: _run_selftest(app, window))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
