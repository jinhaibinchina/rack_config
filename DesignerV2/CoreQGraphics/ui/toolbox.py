"""图元工具箱 Dock：13 类图元 + 9 种 widget 变体 + 可复用模板。

矩形/线/圆=两击，三角=三击，贝塞尔=四击（起点+两控制点+终点），
多边形/路径=多击+右键闭合，折线=多击+右键结束（不闭合），其余=单击放置。
单图元 / 组合模板按钮点一下插到视图中心、拖到画布落在指定位置，右键可重命名 / 删除。

对齐 ``Designer/Core/ui/element_toolbox_dock.py`` 的分组与交互（缩略图也是
代码自绘，无资源文件依赖）。两种拖放 MIME 分开：
``application/x-coreqg-element`` 带图元类型、``application/x-design-template``
带模板 id，落点换算都在 ``GraphicsView.dropEvent``。
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QDrag, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QGroupBox, QLabel, QMenu, QPushButton,
    QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from ..g_scene import TYPE_LABELS, WIDGET_TOOL_KEYS, WIDGET_TOOL_LABELS
from ..g_view import ELEMENT_MIME_TYPE, TEMPLATE_MIME_TYPE
from .template_store import ToolboxTemplate

CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("基本图元", ("rect", "circle", "line", "triangle", "polygon", "polyline",
                 "bezier")),
    ("文本与素材", ("text", "image")),
    ("功能控件", ( "widget", "group")),
    ("控件变体", WIDGET_TOOL_KEYS),
)
ICON_SIZE = 28

# 模板按钮与「保存为模板」按钮的轻量配色（只作用于本 Dock，不影响主窗口）
TEMPLATE_QSS = """
QToolButton#coreQgTemplateButton {
    border: 1px solid #b5d4f4; border-radius: 4px;
    background: #e6f1fb; padding: 2px 4px;
}
QToolButton#coreQgTemplateButton:hover { background: #d2e6fb; }
QToolButton#coreQgTemplateButton:pressed { background: #b9d8f5; }
QPushButton#coreQgTemplateCapture {
    border: 1px solid #185fa5; border-radius: 4px;
    background: #2563eb; color: white; padding: 5px;
}
QPushButton#coreQgTemplateCapture:hover { background: #1d4ed8; }
QPushButton#coreQgTemplateCapture:disabled {
    background: #cbd5e1; border-color: #aab6c4; color: #6b7280;
}
QLabel#coreQgTemplateHint { color: #6b7280; font-size: 11px; }
"""


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
    if key == "polyline":
        # 开放折线：一段一段的折点，首尾不相连（与 polygon 的闭合轮廓区分）
        pts = [QPointF(4, 21), QPointF(10, 7), QPointF(16, 17), QPointF(24, 5)]
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)
        p.setBrush(QColor("#3d5a80"))
        for pt in pts:
            p.drawEllipse(pt, 1.3, 1.3)
        p.setBrush(Qt.NoBrush)
    if key in ("polygon", "path"):
        pts = [QPointF(5, 12), QPointF(14, 4), QPointF(24, 10),
               QPointF(21, 24), QPointF(8, 23)]
        if key == "polygon":
            p.drawPolygon(pts)
        else:
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
    if key == "bezier":
        curve = QPainterPath(QPointF(4, 22))
        curve.cubicTo(QPointF(9, 3), QPointF(19, 3), QPointF(24, 22))
        p.setPen(QPen(QColor("#3d5a80"), 1.8))
        p.drawPath(curve)
        p.setPen(QPen(QColor("#2a9d8f"), 1.4))
        p.setBrush(QColor("#2a9d8f"))
        p.drawEllipse(QPointF(4, 22), 1.8, 1.8)
        p.drawEllipse(QPointF(24, 22), 1.8, 1.8)
        p.setBrush(Qt.NoBrush)
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
        elif v == "progressbar":
            p.drawRect(6, 10, 16, 8)
            p.fillRect(7, 11, 9, 6, QColor("#3d5a80"))
        elif v == "slider":
            p.drawLine(6, 14, 22, 14)
            p.fillRect(12, 10, 5, 9, QColor("#3d5a80"))
            p.drawLine(7, 19, 7, 21)
            p.drawLine(21, 19, 21, 21)
    p.end()
    return QIcon(pix)


def _icon_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _icon_point(value):
    if not isinstance(value, dict):
        return None
    try:
        return float(value["x"]), float(value["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _template_bounds(items):
    """所有成员的形状包围盒（忽略旋转），用来把缩略图缩放到 28×28。"""
    points = []
    for data in items:
        kind = str(data.get("type", ""))
        if kind == "line":
            for key in ("head_pos", "end_pos"):
                pt = _icon_point(data.get(key))
                if pt is not None:
                    points.append(pt)
            continue
        if kind in ("triangle", "polygon", "polyline", "path"):
            verts = data.get("vertices")
            if isinstance(verts, list):
                got = [_icon_point(v) for v in verts]
                if got and all(v is not None for v in got):
                    points.extend(got)
                    continue
        center = _icon_point(data.get("center_pos")) or _icon_point(data.get("origin_pos"))
        if center is None:
            continue
        cx, cy = center
        if kind == "circle":
            rw = _icon_float(data.get("radius_w"))
            rh = _icon_float(data.get("radius_h"))
            points.extend([(cx - rw, cy - rh), (cx + rw, cy + rh)])
        else:
            w = _icon_float(data.get("width")) / 2.0
            h = _icon_float(data.get("height")) / 2.0
            points.extend([(cx - w, cy - h), (cx + w, cy + h)])
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _template_icon(template: ToolboxTemplate) -> QIcon:
    """按模板成员画一张缩略图（与旧工具箱同一套画法）。"""
    size = ICON_SIZE
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)

    bounds = _template_bounds(template.items)
    if bounds is None:
        pen = QPen(QColor("#2563eb"), 1.0, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(3, 3, size - 6, size - 6))
        painter.end()
        return QIcon(pix)

    x1, y1, x2, y2 = bounds
    width = max(x2 - x1, 1e-6)
    height = max(y2 - y1, 1e-6)
    margin = 3.0
    scale = min((size - 2 * margin) / width, (size - 2 * margin) / height)
    ox = (size - width * scale) / 2.0
    oy = (size - height * scale) / 2.0

    def at(x, y) -> QPointF:
        return QPointF(ox + (x - x1) * scale, oy + (y - y1) * scale)

    painter.setPen(QPen(QColor("#2563eb"), 1.0, Qt.SolidLine, Qt.RoundCap,
                        Qt.RoundJoin))
    # 大模板（料架 1 有 154 个成员）没必要把 28px 图标画满，取前 160 个即可
    for data in template.items[:160]:
        kind = str(data.get("type", ""))
        if kind == "group":
            continue
        style = data.get("style") or {}
        filled = bool(style.get("fill", False)) and kind in (
            "rect", "triangle", "circle", "text")
        painter.setBrush(QColor(191, 219, 254, 190) if filled else Qt.NoBrush)

        if kind == "line":
            head = _icon_point(data.get("head_pos"))
            end = _icon_point(data.get("end_pos"))
            if head and end:
                painter.drawLine(at(*head), at(*end))
            continue

        verts = data.get("vertices")
        if kind in ("triangle", "polygon", "polyline", "path") and isinstance(verts, list):
            got = [_icon_point(v) for v in verts]
            if got and all(v is not None for v in got):
                path = QPainterPath(at(*got[0]))
                for v in got[1:]:
                    path.lineTo(at(*v))
                if kind in ("triangle", "polygon"):
                    path.closeSubpath()
                painter.drawPath(path)
                continue

        center = _icon_point(data.get("center_pos")) or _icon_point(data.get("origin_pos"))
        if center is None:
            continue
        cx, cy = center
        if kind == "circle":
            rw = _icon_float(data.get("radius_w"))
            rh = _icon_float(data.get("radius_h"))
            tl = at(cx - rw, cy - rh)
            painter.drawEllipse(QRectF(tl.x(), tl.y(),
                                       rw * 2.0 * scale, rh * 2.0 * scale))
            continue
        w = _icon_float(data.get("width"))
        h = _icon_float(data.get("height"))
        tl = at(cx - w / 2.0, cy - h / 2.0)
        rect = QRectF(tl.x(), tl.y(), w * scale, h * scale)
        if kind == "triangle":
            path = QPainterPath()
            path.moveTo(rect.center().x(), rect.top())
            path.lineTo(rect.left(), rect.bottom())
            path.lineTo(rect.right(), rect.bottom())
            path.closeSubpath()
            painter.drawPath(path)
        else:
            painter.drawRect(rect)
        if kind == "text":
            font = painter.font()
            font.setBold(True)
            font.setPointSizeF(6.5)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, "T")
    painter.end()
    return QIcon(pix)


class ToolButton(QToolButton):
    """点击 = 发 toolActivated；拖动 = 发 QDrag。

    ``MIME_TYPE`` / ``drag_data()`` 留给模板按钮覆写，两种拖放共用一套手势。
    """

    MIME_TYPE = ELEMENT_MIME_TYPE

    def __init__(self, key: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        label = WIDGET_TOOL_LABELS.get(key, TYPE_LABELS.get(key, key))
        self.setText(label)
        self.setIcon(_icon(key))
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setFixedHeight(34)
        self.setToolTip(f"{label}：点击后在画布上分点落子（矩形/线/圆两击、三角三击、"
                        "折线/多边形多击，折线右键结束、多边形右键闭合，其余单击）")
        self._press_pos = QPoint()

    def drag_data(self) -> bytes:
        return self.key.encode("utf-8")

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
        mime.setData(self.MIME_TYPE, self.drag_data())
        drag.setMimeData(mime)
        drag.setPixmap(self.icon().pixmap(ICON_SIZE, ICON_SIZE))
        drag.exec(Qt.CopyAction)


class TemplateToolButton(ToolButton):
    """一个可复用组合模板：点击插到视图中心，拖动落到光标处。"""

    MIME_TYPE = TEMPLATE_MIME_TYPE

    def __init__(self, template: ToolboxTemplate, parent=None) -> None:
        super().__init__(f"template:{template.id}", parent)
        self.template = template
        self.setObjectName("coreQgTemplateButton")
        self.setText(template.name)
        self.setIcon(_template_icon(template))
        self.setToolTip(
            f"{template.name}\n"
            f"可复用模板 · {template.node_count} 个图元\n"
            "拖拽到画布，或点击添加到视图中心\n"
            "右键可重命名或删除"
        )

    def drag_data(self) -> bytes:
        return self.template.id.encode("utf-8")


class ElementToolboxDock(QDockWidget):
    toolActivated = Signal(str)
    templateActivated = Signal(str)
    captureGroupRequested = Signal()
    templateRenameRequested = Signal(str)
    templateDeleteRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__("图元工具箱", parent)
        self.setObjectName("coreQgToolbox")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setStyleSheet(TEMPLATE_QSS)
        self.buttons: list[ToolButton] = []
        self._template_buttons: list[TemplateToolButton] = []
        self._capture_button: QPushButton | None = None

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
        self._build_template_group(holder, column)
        column.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll)
        self.setWidget(content)
        self.setMinimumWidth(190)

    def _build_template_group(self, holder: QWidget, column: QVBoxLayout) -> None:
        group = QGroupBox("图元 / 组合模板", holder)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 10, 6, 6)
        layout.setSpacing(4)

        self._template_hint = QLabel(
            "选中一个图元或组，保存后即可在这里重复使用。", group)
        self._template_hint.setObjectName("coreQgTemplateHint")
        self._template_hint.setWordWrap(True)
        layout.addWidget(self._template_hint)

        self._template_container = QWidget(group)
        self._template_layout = QVBoxLayout(self._template_container)
        self._template_layout.setContentsMargins(0, 0, 0, 0)
        self._template_layout.setSpacing(3)
        layout.addWidget(self._template_container)

        self._capture_button = QPushButton("将所选图元存为模板", group)
        self._capture_button.setObjectName("coreQgTemplateCapture")
        self._capture_button.setEnabled(False)
        self._capture_button.setToolTip("选中一个图元或组后即可保存；布尔结果可直接保存")
        self._capture_button.clicked.connect(
            lambda checked=False: self.captureGroupRequested.emit()
        )
        layout.addWidget(self._capture_button)
        column.addWidget(group)

    # ------------------------------------------------------------------
    # 组合模板
    # ------------------------------------------------------------------
    def set_templates(self, templates) -> None:
        for button in self._template_buttons:
            self._template_layout.removeWidget(button)
            # 必须脱离对象树：deleteLater 是延迟删除，旧按钮会继续被
            # findChildren() 命中，导致自动化拿到错误的按钮。
            button.setParent(None)
            button.deleteLater()
        self._template_buttons.clear()

        for template in templates:
            button = TemplateToolButton(template, self._template_container)
            button.clicked.connect(
                lambda checked=False, tid=template.id:
                    self.templateActivated.emit(tid)
            )
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda pos, target=button: self._show_template_menu(target, pos)
            )
            self._template_layout.addWidget(button)
            self._template_buttons.append(button)

        self._template_hint.setText(
            "点击模板添加到视图中心，或拖拽到画布指定位置。" if templates
            else "在画布上选中一个图元或组，保存后即可在这里重复使用。"
        )

    def set_capture_enabled(self, enabled: bool) -> None:
        if self._capture_button is not None:
            self._capture_button.setEnabled(bool(enabled))

    def _show_template_menu(self, button: TemplateToolButton, pos) -> None:
        menu = QMenu(self)
        rename_action = menu.addAction("重命名模板…")
        delete_action = menu.addAction("删除模板")
        picked = menu.exec(button.mapToGlobal(pos))
        if picked == rename_action:
            self.templateRenameRequested.emit(button.template.id)
        elif picked == delete_action:
            self.templateDeleteRequested.emit(button.template.id)
