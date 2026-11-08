"""图元工具箱 Dock：12 类图元 + 7 种 widget 控件变体，点击进入「绘制模式」。
矩形/线/圆=两击，三角=三击，多边形/路径=多击+右键闭合，其余=单击放置。

对齐 ``Designer/modes/design/element_toolbox_dock.py`` 的分组与交互，
图标同样是代码自绘（无资源文件依赖）。拖放 MIME 为
``application/x-coreqg-element``，落点由 ``GraphicsView.dropEvent`` 换算。
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QGroupBox, QScrollArea, QToolButton,
    QVBoxLayout, QWidget,
)

from ..g_scene import TYPE_LABELS, WIDGET_TOOL_KEYS, WIDGET_TOOL_LABELS
from ..g_view import ELEMENT_MIME_TYPE

CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("基本图元", ("rect", "circle", "line", "triangle", "polygon", "path")),
    ("文本与素材", ("text", "image")),
    ("功能控件", ("checkbox", "widget", "group")),
    ("控件变体", WIDGET_TOOL_KEYS),
)
ICON_SIZE = 28


def _icon(key: str) -> QIcon:
    """按类型画一个 28x28 的线稿图标（与旧工具箱同思路）。"""
    pix = QPixmap(ICON_SIZE, ICON_SIZE)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(QColor("#3d5a80"), 1.8))
    r = (4, 4, 20, 20)
    if (key == "widget" or key.startswith("widget:")
            or key in ("rect", "image", "text", "checkbox", "group")):
        p.drawRect(*r)
    if key == "circle":
        p.drawEllipse(*r)
    if key == "line":
        p.drawLine(4, 24, 24, 4)
    if key == "triangle":
        p.drawPolygon([QPointF(14, 4), QPointF(25, 24), QPointF(3, 24)])
    if key in ("polygon", "path"):
        pts = [QPointF(5, 12), QPointF(14, 4), QPointF(24, 10),
               QPointF(21, 24), QPointF(8, 23)]
        if key == "polygon":
            p.drawPolygon(pts)
        else:
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
    if key == "text":
        p.drawLine(8, 14, 20, 14)
        p.drawLine(8, 18, 17, 18)
    if key == "checkbox":
        p.setPen(QPen(QColor("#2a9d8f"), 2.2))
        p.drawLine(8, 14, 12, 19)
        p.drawLine(12, 19, 21, 9)
    if key == "image":
        p.drawEllipse(8, 8, 4, 4)
        p.drawLine(6, 22, 13, 15)
        p.drawLine(13, 15, 22, 22)
    if key == "group":
        p.setPen(QPen(QColor("#888888"), 1.0, Qt.DashLine))
        p.drawRect(7, 7, 16, 16)
    if key.startswith("widget:"):
        v = key.split(":", 1)[1]
        if v == "textedit":
            for y in (10, 14, 18):
                p.drawLine(8, y, 20, y)
        elif v == "label":
            p.drawLine(8, 12, 20, 12)
            p.drawLine(8, 17, 16, 17)
        elif v == "lineedit":
            p.drawLine(8, 14, 20, 14)
            p.drawLine(8, 10, 8, 18)
        elif v == "checkbox":
            p.drawRect(8, 11, 8, 8)
            p.drawLine(9, 15, 11, 17)
            p.drawLine(11, 17, 15, 12)
        elif v == "combobox":
            p.drawLine(8, 14, 17, 14)
            p.drawLine(18, 9, 18, 21)
            p.drawPolygon([QPointF(20, 12), QPointF(24, 12), QPointF(22, 16)])
        elif v == "spinbox":
            p.drawLine(8, 14, 17, 14)
            p.drawLine(18, 9, 18, 21)
            p.drawPolygon([QPointF(20, 11), QPointF(24, 11), QPointF(22, 8)])
            p.drawPolygon([QPointF(20, 19), QPointF(24, 19), QPointF(22, 22)])
        elif v == "pushbutton":
            p.drawRect(6, 7, 16, 14)
    p.end()
    return QIcon(pix)


class ToolButton(QToolButton):
    """点击 = 发 toolActivated；拖动 = 发 QDrag。"""

    def __init__(self, key: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        label = WIDGET_TOOL_LABELS.get(key, TYPE_LABELS.get(key, key))
        self.setText(label)
        self.setIcon(_icon(key))
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setFixedHeight(34)
        self.setToolTip(f"{label}：点击后在画布上分点落子（矩形/线/圆两击、三角三击、多边形多击+右键闭合，其余单击）")
        self._press_pos = QPoint()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.position().toPoint() - self._press_pos).manhattanLength() < \
                QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(ELEMENT_MIME_TYPE, self.key.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self.icon().pixmap(ICON_SIZE, ICON_SIZE))
        drag.exec(Qt.CopyAction)


class ElementToolboxDock(QDockWidget):
    toolActivated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__("图元工具箱", parent)
        self.setObjectName("coreQgToolbox")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.buttons: list[ToolButton] = []

        content = QWidget(self)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(4, 4, 4, 4)
        scroll = QScrollArea(content)
        scroll.setWidgetResizable(True)
        holder = QWidget(scroll)
        column = QVBoxLayout(holder)
        column.setContentsMargins(4, 4, 4, 4)
        column.setSpacing(8)
        for title, keys in CATEGORIES:
            group = QGroupBox(title, holder)
            layout = QVBoxLayout(group)
            layout.setSpacing(3)
            for key in keys:
                button = ToolButton(key, group)
                button.clicked.connect(
                    lambda checked=False, k=key: self.toolActivated.emit(k)
                )
                self.buttons.append(button)
                layout.addWidget(button)
            column.addWidget(group)
        column.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll)
        self.setWidget(content)
        self.setMinimumWidth(190)
