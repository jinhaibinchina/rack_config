"""widget 图元的控件变体：字段口径、解析、真实 Qt 控件与占位自绘。

对照 ``Designer/Core/elements.py::widget_element``（约 1257-2063 行）：
旧实现把「变体」做成 ``widgetType`` 一个字符串 → 7 个 Qt 类的一层分发，
``widgetText`` 再按控件类型重新解释，序列化只有 5 个**顶层**字段：

    widgetType / widgetText / widgetFontSize / widgetColor / widgetBackground

旧 Core 的 ``paint`` 完全不区分变体（只画矩形 + "Widget"），不同外观来自
``EmbeddedWidgetLayer`` 挂载的真实 QWidget。重写版是平铺 QGraphicsItem，
因此这里补齐两件事：

* **变体化自绘**：设计态按每种控件画可辨识的占位外观（下拉三角、微调箭头、
  勾选框、按钮立体边等），不依赖真实控件就能看出变体。
* **运行态真实控件**：``GraphicsScene.set_scene_mode(True)`` 时用
  ``QGraphicsProxyWidget`` 挂载真实 QWidget（独立顶层 item、不进索引、
  不参与 page JSON），设计态不创建，保证 page_1 对拍与渲染确定性。

字段口径与默认値逐字对齐旧 Core，缺字段的老页面按默认值补全但**不回写**，
以保证 JSON round-trip 零改动。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTextEdit, QWidget,
)

# 顺序与旧 Core ``WIDGET_CONTROL_TYPES`` 一致；``textedit`` 是默认 / 兜底项
WIDGET_VARIANTS: tuple[str, ...] = (
    "textedit", "lineedit", "checkbox", "combobox",
    "pushbutton", "label", "spinbox",
)
WIDGET_VARIANT_LABELS: dict[str, str] = {
    "textedit": "多行文本", "lineedit": "输入框", "checkbox": "勾选框",
    "combobox": "下拉框", "pushbutton": "按钮", "label": "标签",
    "spinbox": "数字输入",
}
WIDGET_DEFAULTS: dict[str, object] = {
    "widgetType": "textedit",
    "widgetText": "",
    "widgetFontSize": 12,
    "widgetColor": "#000000",
    "widgetBackground": "#ffffff",
}
# 旧 Core ``_apply_text``：这三类空文本时显示默认标题
DEFAULT_TITLES: dict[str, str] = {
    "checkbox": "选项", "pushbutton": "按钮", "label": "标签",
}
WIDGET_FIELD_KEYS = tuple(WIDGET_DEFAULTS)


def normalize_variant(key) -> str:
    """未知 / 缺失的 ``widgetType`` 一律退化成 ``textedit``（旧 Core 兜底）。"""
    k = str(key or "")
    return k if k in WIDGET_VARIANTS else "textedit"


def widget_field(record: dict, key: str):
    """读一个 widget 专属顶层字段；缺字段时返回旧 Core 默认值，但不写回。"""
    return record.get(key, WIDGET_DEFAULTS[key])


def widget_variant(record: dict) -> str:
    return normalize_variant(widget_field(record, "widgetType"))


def widget_text(record: dict) -> str:
    return str(widget_field(record, "widgetText") or "")


def widget_options(text: str) -> list[str]:
    """combobox：``widgetText`` 按行拆选项，去空白行；空则 ``["选项 1"]``。"""
    items = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return items or ["选项 1"]


def widget_spin_config(text: str) -> tuple[int, int, int]:
    """spinbox：``widgetText`` 的 ``min=/max=/value=`` 逐行解析。

    缺省取 Qt ``QSpinBox`` 默认 0 / 99，value 缺省取 min；``min > max``
    自动交换，value 被 clamp 到 [min, max]。与旧 Core ``_apply_spinbox`` 一致。
    """
    cfg: dict[str, int] = {}
    for line in str(text or "").splitlines():
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        key = key.strip().lower()
        if key not in ("min", "max", "value"):
            continue
        try:
            cfg[key] = int(float(raw.strip()))
        except (TypeError, ValueError):
            continue
    mn, mx = cfg.get("min", 0), cfg.get("max", 99)
    if mn > mx:
        mn, mx = mx, mn
    value = max(mn, min(cfg.get("value", mn), mx))
    return mn, mx, value


def widget_display_text(variant: str, text: str) -> str:
    """占位自绘 / 真实控件上要显示的文本（按变体解释 ``widgetText``）。"""
    variant = normalize_variant(variant)
    text = str(text or "")
    if variant == "combobox":
        return widget_options(text)[0]
    if variant == "spinbox":
        return str(widget_spin_config(text)[2])
    return text or DEFAULT_TITLES.get(variant, "")


def _css_color(record: dict, key: str, fallback: str) -> str:
    raw = str(widget_field(record, key) or "")
    color = QColor(raw)
    return color.name() if color.isValid() else fallback


def widget_style_sheet(record: dict) -> str:
    """旧 Core ``_apply_style``：颜色非法回退黑 / 白，字号 pt。"""
    try:
        fs = int(float(widget_field(record, "widgetFontSize")))
    except (TypeError, ValueError):
        fs = 12
    return (
        f"color: {_css_color(record, 'widgetColor', '#000000')};"
        f"background-color: {_css_color(record, 'widgetBackground', '#ffffff')};"
        f"font-size: {max(1, fs)}pt;"
    )


def create_control(record: dict, host: QWidget | None = None) -> QWidget:
    """按变体创建真实 Qt 控件并灌入 ``widgetText`` / 样式。

    ``host`` 一般留 ``None``：``QGraphicsProxyWidget.addWidget`` 要求控件没有
    parent（旧 Core 那套裸 QWidget overlay 才需要传 viewport）。
    """
    variant = widget_variant(record)
    text = widget_text(record)

    if variant == "lineedit":
        w: QWidget = QLineEdit(host) if host is not None else QLineEdit()
        w.setText(text)
    elif variant == "checkbox":
        w = QCheckBox(host) if host is not None else QCheckBox()
        w.setText(text or DEFAULT_TITLES["checkbox"])
    elif variant == "combobox":
        w = QComboBox(host) if host is not None else QComboBox()

        
        w.addItems(widget_options(text))

    elif variant == "pushbutton":
        w = QPushButton(host) if host is not None else QPushButton()
        w.setText(text or DEFAULT_TITLES["pushbutton"])
    elif variant == "label":
        w = QLabel(host) if host is not None else QLabel()
        w.setText(text or DEFAULT_TITLES["label"])
    elif variant == "spinbox":
        w = QSpinBox(host) if host is not None else QSpinBox()
        mn, mx, value = widget_spin_config(text)
        w.setRange(mn, mx)
        w.setValue(value)
    else:  # textedit（含未知变体退化）
        w = QTextEdit(host) if host is not None else QTextEdit()
        w.setReadOnly(True)
        w.setPlaceholderText("只读多行文本…")
        w.setPlainText(text)
    # QGraphicsProxyWidget.resize(w,h) 会被控件自身的 minimumSizeHint 撑大
    # （QComboBox 默认 114×22、QLineEdit 20 高），小尺寸图元会连位置一起偏。
    # 与旧 Core EmbeddedWidgetLayer 一致先松绑最小尺寸，尺寸完全由图元决定。
    w.setMinimumSize(1, 1)
    w.setStyleSheet(widget_style_sheet(record))
    return w


# ----------------------------------------------------------------------
# 设计态占位自绘：旧 Core 无变体差异，重写版补上，便于不看运行态也能分辨
# ----------------------------------------------------------------------

def _widget_font(record: dict) -> QFont:
    """设计态占位字体：与运行态真实控件**同族同字号**。

    刻意不再按框高缩小：运行态 ``create_control`` 用
    ``font-size: {widgetFontSize}pt`` 原值渲染，设计态若偷偷压到框高的
    42%，两态会差近一倍（实测 12pt 被压到 6.2pt），用户就会看到
    「运行态字体被放大」。字太大属于图元尺寸与字号不匹配，应由用户在
    属性面板调小字号 / 加大控件，设计态如实预览（超框和真实控件一样裁切）。
    """
    try:
        fs = float(widget_field(record, "widgetFontSize"))
    except (TypeError, ValueError):
        fs = 12.0
    font = QFont()          # 应用默认字体，与运行态真实控件继承的字体同族
    font.setPointSizeF(max(4.0, fs))
    return font


def _tri(painter: QPainter, cx: float, cy: float, half: float, up: bool) -> None:
    """画一个实心小三角（combobox 下拉 / spinbox 上下箭头）。"""
    s = 1.0 if up else -1.0
    pts = [
        QPointF(cx - half, cy + s * half * 0.55),
        QPointF(cx + half, cy + s * half * 0.55),
        QPointF(cx, cy - s * half * 0.55),
    ]
    painter.drawPolygon(pts)


def paint_variant(painter: QPainter, r: QRectF, record: dict) -> None:
    """在 ``_local_rect``（view 坐标、中心在原点）里画变体化占位外观。

    只画不改几何，``boundingRect`` / ``page_bounding_rect`` 完全不变，因此对拍
    与 JSON round-trip 不受影响。颜色、字号取自 5 个顶层字段。
    """
    if r.width() < 8.0 or r.height() < 8.0:
        return
    variant = widget_variant(record)
    text = widget_display_text(variant, widget_text(record))
    fg = QColor(str(widget_field(record, "widgetColor") or ""))
    if not fg.isValid():
        fg = QColor("#000000")
    bg = QColor(str(widget_field(record, "widgetBackground") or ""))
    if not bg.isValid():
        bg = QColor("#ffffff")

    painter.save()
    painter.setClipRect(r)
    font = _widget_font(record)
    painter.setFont(font)
    pen = QPen(fg, max(1.0, min(r.width(), r.height()) * 0.035))
    painter.setPen(pen)
    inner = r.adjusted(2.0, 2.0, -2.0, -2.0)
    pad = max(3.0, r.height() * 0.16)

    if variant == "label":
        # 标签：无边框（只保留父类描边），铺 widgetBackground、文字左对齐。
        # QLabel 默认几乎没有左右内边距；这里若再按 pad 缩进，短框会把最后
        # 一个字裁掉（运行态却完整），与「设计即所得」冲突。
        painter.fillRect(inner, bg)
        painter.drawText(inner, Qt.AlignLeft | Qt.AlignVCenter
                         | Qt.TextSingleLine, text)
    elif variant == "pushbutton":
        # 按钮：底色 + 上左高亮 / 下右阴影的立体边 + 居中文字
        painter.fillRect(inner, bg)
        painter.setPen(QPen(bg.lighter(145), max(1.0, pen.widthF())))
        painter.drawLine(inner.topLeft(), inner.topRight())
        painter.drawLine(inner.topLeft(), inner.bottomLeft())
        painter.setPen(QPen(bg.darker(145), max(1.0, pen.widthF())))
        painter.drawLine(inner.bottomLeft(), inner.bottomRight())
        painter.drawLine(inner.topRight(), inner.bottomRight())
        painter.setPen(pen)
        painter.drawText(inner.adjusted(pad, 0, -pad, 0),
                         Qt.AlignCenter | Qt.TextSingleLine, text)
    elif variant == "checkbox":
        # 勾选框：铺底色 + 左侧方框 + 勾 + 文本
        painter.fillRect(inner, bg)
        side = min(r.height() * 0.55, r.width() * 0.28, 22.0)
        box = QRectF(inner.left() + pad, r.center().y() - side / 2.0, side, side)
        painter.fillRect(box, bg)
        painter.drawRect(box)
        painter.setPen(QPen(fg, max(1.4, pen.widthF() * 1.3)))
        k = side * 0.22
        painter.drawLine(QPointF(box.left() + k, box.center().y()),
                         QPointF(box.center().x(), box.bottom() - k))
        painter.drawLine(QPointF(box.center().x(), box.bottom() - k),
                         QPointF(box.right() - k, box.top() + k))
        painter.setPen(pen)
        painter.drawText(QRectF(box.right() + pad, inner.top(),
                                max(0.0, inner.right() - box.right() - 2 * pad),
                                inner.height()),
                         Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, text)
    else:
        # 输入类（textedit / lineedit / combobox / spinbox）共用白底输入区
        painter.fillRect(inner, bg)
        painter.drawRect(inner)
        zone = inner.adjusted(pad, 0, -pad, 0)
        if variant == "textedit":
            # 多行：左对齐自动换行 + 右下角 resize grip
            painter.drawText(zone, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                             text or "只读多行文本…")
            g = min(r.width(), r.height()) * 0.12
            painter.setPen(QPen(fg.lighter(160), 1.0))
            for i in range(3):
                off = i * g * 0.5
                painter.drawLine(
                    QPointF(inner.right() - off, inner.bottom() - g),
                    QPointF(inner.right() - g, inner.bottom() - off))
        elif variant == "lineedit":
            painter.drawText(zone, Qt.AlignLeft | Qt.AlignVCenter
                             | Qt.TextSingleLine, text)
            # 左侧细竖线：输入光标
            painter.setPen(QPen(fg, max(1.0, pen.widthF() * 0.7)))
            painter.drawLine(QPointF(zone.left() + 1, inner.top() + pad),
                             QPointF(zone.left() + 1, inner.bottom() - pad))
        else:
            # combobox / spinbox：右侧按钮区 + 文本
            btn_w = min(max(12.0, r.height() * 0.9), r.width() * 0.28)
            split = inner.right() - btn_w
            painter.setPen(QPen(fg.lighter(170), 1.0))
            painter.drawLine(QPointF(split, inner.top()),
                             QPointF(split, inner.bottom()))
            painter.setPen(pen)
            painter.drawText(
                QRectF(zone.left(), inner.top(),
                       max(0.0, split - zone.left() - 2.0), inner.height()),
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, text)
            cx = (split + inner.right()) / 2.0
            cy = r.center().y()
            arrow = min(btn_w * 0.28, r.height() * 0.14)
            painter.setBrush(QBrush(fg))
            if variant == "combobox":
                _tri(painter, cx, cy, arrow, up=False)
            else:
                _tri(painter, cx, cy - arrow * 0.85, arrow * 0.8, up=True)
                _tri(painter, cx, cy + arrow * 0.85, arrow * 0.8, up=False)
    painter.restore()
