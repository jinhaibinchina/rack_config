"""Right dock: draggable toolbox for the scene element types."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDrag,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFrame,
    QGroupBox,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .element_factory import (
    ELEMENT_MIME_TYPE,
    TOOL_CATEGORIES,
    ToolDefinition,
    tools_in_category,
)
from .template_store import TEMPLATE_MIME_TYPE, ToolboxTemplate


class ElementToolButton(QPushButton):
    """A toolbox button that starts a drag after the normal drag threshold."""

    def __init__(self, definition: ToolDefinition, parent=None):
        super().__init__(definition.label, parent)
        self.definition = definition
        self.setObjectName("ElementToolButton")
        self.setCursor(Qt.OpenHandCursor)
        self.setMinimumHeight(42)
        self.setIconSize(QSize(26, 26))
        self.setIcon(_create_tool_icon(definition.key))
        self.setToolTip(definition.description)
        self._press_pos = None
        self._dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._press_pos is not None
            and event.buttons() & Qt.LeftButton
            and not self._dragging
            and (event.position().toPoint() - self._press_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._dragging = True
            self._start_drag()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self._press_pos = None
            self.setDown(False)
            event.accept()
            return
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def _start_drag(self) -> None:
        self._start_drag_with(ELEMENT_MIME_TYPE, self.definition.key)

    def _start_drag_with(self, mime_type: str, payload: str) -> None:
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setData(mime_type, payload.encode("utf-8"))
        drag.setMimeData(mime_data)

        source = self.grab()
        preview = QPixmap(source.size())
        preview.fill(Qt.transparent)
        painter = QPainter(preview)
        painter.setOpacity(0.75)
        painter.drawPixmap(0, 0, source)
        painter.end()
        drag.setPixmap(preview)
        drag.setHotSpot(QPoint(preview.width() // 2, preview.height() // 2))

        drag.exec(Qt.CopyAction)
        self.setDown(False)
        self._press_pos = None



class TemplateToolButton(ElementToolButton):
    """Toolbox button for a reusable group template."""

    def __init__(self, template: ToolboxTemplate, parent=None):
        definition = ToolDefinition(
            key=f"template:{template.id}",
            label=template.name,
            category="组合模板",
            element_class=object,
            default_width=template.width,
            default_height=template.height,
            description=f"组合模板，共 {template.node_count} 个图元",
        )
        super().__init__(definition, parent)
        self.template = template
        self.setObjectName("TemplateToolButton")
        self.setMinimumHeight(44)
        self.setIconSize(QSize(28, 28))
        self.setIcon(_create_template_icon(template))
        self.setToolTip(
            f"{template.name}\n"
            f"组合模板 · {template.node_count} 个图元\n"
            "拖拽到画布，或点击添加到视图中心\n"
            "右键可重命名或删除"
        )

    def _start_drag(self) -> None:
        self._start_drag_with(TEMPLATE_MIME_TYPE, self.template.id)



class ElementToolboxDock(QDockWidget):
    """Toolbox dock. ``toolActivated`` starts click-to-draw as well as drag."""

    toolActivated = Signal(str)
    templateActivated = Signal(str)
    captureGroupRequested = Signal()
    templateRenameRequested = Signal(str)
    templateDeleteRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__("控件工具箱", parent)
        self.setObjectName("elementToolboxDock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.setMinimumWidth(190)
        self._buttons = []
        self._template_buttons = []
        self._capture_button = None
        self._build_ui()

    def _build_ui(self) -> None:
        container = QWidget(self)
        container.setObjectName("toolboxContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("场景元素", container)
        title.setObjectName("dockSectionTitle")
        layout.addWidget(title)

        hint = QLabel("拖拽元素到画布指定位置；或单击工具后在画布上绘制", container)
        hint.setObjectName("dockHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        separator = QFrame(container)
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        scroll_area = QScrollArea(container)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget(scroll_area)
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)

        for category in TOOL_CATEGORIES:
            group = QGroupBox(category, scroll_content)
            group.setObjectName("toolboxGroup")
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(8, 12, 8, 8)
            group_layout.setSpacing(5)
            for definition in tools_in_category(category):
                button = ElementToolButton(definition, group)
                button.clicked.connect(
                    lambda checked=False, key=definition.key: self.toolActivated.emit(key)
                )
                self._buttons.append(button)
                group_layout.addWidget(button)
            scroll_layout.addWidget(group)

        self._template_group = QGroupBox("组合模板", scroll_content)
        self._template_group.setObjectName("toolboxGroup")
        template_group_layout = QVBoxLayout(self._template_group)
        template_group_layout.setContentsMargins(8, 12, 8, 8)
        template_group_layout.setSpacing(6)

        self._template_hint = QLabel(
            "在画布上选中一个组，保存后即可在这里重复使用。", self._template_group
        )
        self._template_hint.setObjectName("templateHint")
        self._template_hint.setWordWrap(True)
        template_group_layout.addWidget(self._template_hint)

        self._template_container = QWidget(self._template_group)
        self._template_layout = QVBoxLayout(self._template_container)
        self._template_layout.setContentsMargins(0, 0, 0, 0)
        self._template_layout.setSpacing(5)
        template_group_layout.addWidget(self._template_container)

        self._capture_button = QPushButton("将所选组保存为模板", self._template_group)
        self._capture_button.setObjectName("TemplateCaptureButton")
        self._capture_button.setCursor(Qt.PointingHandCursor)
        self._capture_button.setEnabled(False)
        self._capture_button.setToolTip("选中画布上的一个组后即可保存为模板")
        self._capture_button.clicked.connect(
            lambda checked=False: self.captureGroupRequested.emit()
        )
        template_group_layout.addWidget(self._capture_button)
        scroll_layout.addWidget(self._template_group)

        scroll_layout.addStretch(1)
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area, 1)
        self.setWidget(container)

    # ------------------------------------------------------------------
    # Group templates
    # ------------------------------------------------------------------
    def set_templates(self, templates) -> None:
        for button in self._template_buttons:
            self._template_layout.removeWidget(button)
            button.deleteLater()
        self._template_buttons.clear()

        for template in templates:
            button = TemplateToolButton(template, self._template_container)
            button.clicked.connect(
                lambda checked=False, template_id=template.id: self.templateActivated.emit(
                    template_id
                )
            )
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda pos, target=button: self._show_template_menu(target, pos)
            )
            self._template_layout.addWidget(button)
            self._template_buttons.append(button)

        if templates:
            self._template_hint.setText(
                "点击模板添加到视图中心，或拖拽到画布指定位置。"
            )
        else:
            self._template_hint.setText(
                "在画布上选中一个组，保存后即可在这里重复使用。"
            )

    def set_capture_enabled(self, enabled: bool) -> None:
        if self._capture_button is not None:
            self._capture_button.setEnabled(bool(enabled))

    def _show_template_menu(self, button: TemplateToolButton, pos) -> None:
        menu = QMenu(self)
        rename_action = menu.addAction("重命名模板…")
        delete_action = menu.addAction("删除模板")
        selected = menu.exec(button.mapToGlobal(pos))
        if selected == rename_action:
            self.templateRenameRequested.emit(button.template.id)
        elif selected == delete_action:
            self.templateDeleteRequested.emit(button.template.id)


def _create_tool_icon(key: str) -> QIcon:
    """Draw a small, theme-consistent icon without external image assets."""

    size = 28
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#2563eb"))
    pen.setWidth(2)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    if key == "rect":
        painter.drawRect(QRectF(4, 7, 20, 14))
    elif key == "triangle":
        path = QPainterPath()
        path.moveTo(14, 4)
        path.lineTo(25, 23)
        path.lineTo(3, 23)
        path.closeSubpath()
        painter.drawPath(path)
    elif key == "line":
        painter.drawLine(4, 22, 24, 6)
    elif key == "circle":
        painter.drawEllipse(QRectF(5, 5, 18, 18))
    elif key == "text":
        font = painter.font()
        font.setBold(True)
        font.setPointSize(15)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "T")
    elif key == "image":
        painter.drawRect(QRectF(4, 6, 20, 16))
        painter.drawLine(6, 19, 12, 12)
        painter.drawLine(12, 12, 17, 18)
        painter.drawLine(17, 18, 21, 14)
        painter.drawEllipse(QRectF(18, 9, 3, 3))

    painter.end()
    return QIcon(pixmap)




def _template_bounds(items):
    """Return ``(x1, y1, x2, y2)`` of all template shapes, ignoring rotation."""

    points = []
    for data in items:
        item_type = str(data.get("type", ""))
        if item_type == "line":
            for key in ("head_pos", "end_pos"):
                point = _dict_point(data.get(key))
                if point is not None:
                    points.append(point)
            continue

        if item_type == "triangle":
            raw_vertices = data.get("vertices")
            if isinstance(raw_vertices, list):
                vertices = [_dict_point(point) for point in raw_vertices]
                if len(vertices) == 3 and all(
                    point is not None for point in vertices
                ):
                    points.extend(vertices)
                    continue

        center = _dict_point(data.get("center_pos"))
        if center is None:
            center = _dict_point(data.get("origin_pos"))
        if center is None:
            continue
        cx, cy = center
        if item_type == "circle":
            radius_w = _safe_float(data.get("radius_w"), 0.0)
            radius_h = _safe_float(data.get("radius_h"), 0.0)
            points.extend(
                [(cx - radius_w, cy - radius_h), (cx + radius_w, cy + radius_h)]
            )
        else:
            width = _safe_float(data.get("width"), 0.0)
            height = _safe_float(data.get("height"), 0.0)
            points.extend(
                [
                    (cx - width / 2.0, cy - height / 2.0),
                    (cx + width / 2.0, cy + height / 2.0),
                ]
            )

    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _create_template_icon(template: ToolboxTemplate) -> QIcon:
    """Draw a miniature preview of the saved group."""

    size = 28
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    bounds = _template_bounds(template.items)
    if bounds is None:
        pen = QPen(QColor("#2563eb"))
        pen.setWidth(1)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(3, 3, size - 6, size - 6))
        painter.end()
        return QIcon(pixmap)

    x1, y1, x2, y2 = bounds
    width = max(x2 - x1, 1e-6)
    height = max(y2 - y1, 1e-6)
    margin = 3.0
    scale = min((size - 2 * margin) / width, (size - 2 * margin) / height)
    offset_x = (size - width * scale) / 2.0
    offset_y = (size - height * scale) / 2.0

    def to_icon(x, y):
        return QPointF(offset_x + (x - x1) * scale, offset_y + (y - y1) * scale)

    pen = QPen(QColor("#2563eb"))
    pen.setWidthF(1.2)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)

    drawn = 0
    for data in template.items:
        item_type = str(data.get("type", ""))
        if item_type == "group":
            continue

        style = data.get("style") or {}
        fill = bool(style.get("fill", False)) and item_type in (
            "rect",
            "triangle",
            "circle",
            "text",
        )
        painter.setBrush(QColor(191, 219, 254, 190) if fill else Qt.NoBrush)

        if item_type == "line":
            head = _dict_point(data.get("head_pos"))
            end = _dict_point(data.get("end_pos"))
            if head is None or end is None:
                continue
            painter.drawLine(to_icon(*head), to_icon(*end))
            drawn += 1
            continue

        if item_type == "triangle":
            raw_vertices = data.get("vertices")
            if isinstance(raw_vertices, list):
                vertices = [_dict_point(point) for point in raw_vertices]
                if len(vertices) == 3 and all(
                    point is not None for point in vertices
                ):
                    path = QPainterPath(to_icon(*vertices[0]))
                    path.lineTo(to_icon(*vertices[1]))
                    path.lineTo(to_icon(*vertices[2]))
                    path.closeSubpath()
                    painter.drawPath(path)
                    drawn += 1
                    continue

        center = _dict_point(data.get("center_pos"))
        if center is None:
            center = _dict_point(data.get("origin_pos"))
        if center is None:
            continue
        cx, cy = center

        if item_type == "circle":
            radius_w_value = _safe_float(data.get("radius_w"), 0.0)
            radius_h_value = _safe_float(data.get("radius_h"), 0.0)
            top_left = to_icon(cx - radius_w_value, cy - radius_h_value)
            painter.drawEllipse(
                QRectF(
                    top_left.x(),
                    top_left.y(),
                    radius_w_value * 2.0 * scale,
                    radius_h_value * 2.0 * scale,
                )
            )
            drawn += 1
            continue

        width_value = _safe_float(data.get("width"), 0.0)
        height_value = _safe_float(data.get("height"), 0.0)
        top_left = to_icon(cx - width_value / 2.0, cy - height_value / 2.0)
        rect = QRectF(
            top_left.x(),
            top_left.y(),
            width_value * scale,
            height_value * scale,
        )

        if item_type == "triangle":
            path = QPainterPath()
            path.moveTo(rect.center().x(), rect.top())
            path.lineTo(rect.left(), rect.bottom())
            path.lineTo(rect.right(), rect.bottom())
            path.closeSubpath()
            painter.drawPath(path)
        else:
            painter.drawRect(rect)
        drawn += 1

        if item_type == "text":
            font = painter.font()
            font.setBold(True)
            font.setPointSizeF(6.5)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, "T")
        elif item_type == "image":
            painter.drawLine(
                QPointF(rect.left() + 2, rect.bottom() - 2),
                QPointF(rect.center().x(), rect.top() + 2),
            )
            painter.drawLine(
                QPointF(rect.center().x(), rect.top() + 2),
                QPointF(rect.right() - 2, rect.bottom() - 2),
            )

    if drawn == 0:
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(3, 3, size - 6, size - 6))

    painter.end()
    return QIcon(pixmap)


def _dict_point(value):
    if not isinstance(value, dict):
        return None
    try:
        return float(value["x"]), float(value["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _safe_float(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
