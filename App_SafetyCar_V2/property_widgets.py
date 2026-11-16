"""属性面板的共享控件与样式。

设计模式的属性 dock 由 :class:`NavigationContentWidget` 承载，具体分页由
``myPropertyForElement`` 里的各个 ``*PropertyItem`` 生成。两边都只使用本模块
的控件，因此整套面板的间距、行高、配色、输入行为完全一致。

排版约定：
- 一个 ``SectionCard`` = 一个语义分组（基本 / 变换 / 外观 / 事件…）；
- 卡片内是 4 列网格（标签·值·标签·值），一行最多放两对属性，
  底部 dock 横向空间富余时不会把半屏留给空白；
- 所有可编辑字段固定 24px 高，标签列固定宽度，纵向对齐。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


# 标签列宽与字段行高，所有卡片共用
LABEL_WIDTH = 74
FIELD_HEIGHT = 24


def _fit_policy(widget: QWidget, minimum_width: int = 90) -> QWidget:
    """让字段完全服从布局给它的宽度。

    不这么做的话，``QGridLayout`` 会以各控件的 ``sizeHint`` 作为列宽基准，
    “描边色（色块 + 长输入框）”那列永远比“线宽”那列宽，两列属性就会错位。
    水平策略设为 ``Ignored`` 后，列宽只由 stretch 决定，两列严格等宽。
    """

    widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    widget.setMinimumWidth(minimum_width)
    return widget


PROPERTY_PANEL_QSS = """
QWidget {
    font-family: "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif;
}
QWidget#designPropertyPanel {
    background: #f3f4f6;
}
QScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #d1d5db;
    border-radius: 5px;
    min-height: 26px;
}
QScrollBar::handle:vertical:hover {
    background: #9ca3af;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #d1d5db;
    border-radius: 5px;
    min-width: 26px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
}
QWidget#propHeader {
    background: #ffffff;
    border-bottom: 1px solid #e5e7eb;
}
QLabel#propHeaderBadge {
    background: #dbeafe;
    color: #1d4ed8;
    border-radius: 6px;
    font-size: 15px;
    font-weight: 600;
}
QLabel#propHeaderTitle {
    color: #111827;
    font-size: 13px;
    font-weight: 600;
}
QLabel#propHeaderMeta {
    color: #6b7280;
    font-size: 11px;
}
QLabel#propEmptyTitle {
    color: #374151;
    font-size: 13px;
    font-weight: 600;
}
QLabel#propEmptyHint {
    color: #9ca3af;
    font-size: 11px;
}
QTreeWidget#propNavTree {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 4px;
    outline: 0;
}
QTreeWidget#propNavTree::item {
    height: 24px;
    border-radius: 4px;
    color: #374151;
}
QTreeWidget#propNavTree::item:hover {
    background: #eff6ff;
}
QTreeWidget#propNavTree::item:selected {
    background: #dbeafe;
    color: #1d4ed8;
}

QScrollArea#propPageScroll {
    background: transparent;
    border: none;
}
QWidget#propPage {
    background: transparent;
}

QFrame#propSection {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
}
QWidget#propSectionHeader {
    background: transparent;
}
QLabel#propSectionTitle {
    color: #374151;
    font-size: 12px;
    font-weight: 600;
}
QLabel#propSectionBadge {
    background: #dcfce7;
    color: #15803d;
    border-radius: 7px;
    padding: 0 6px;
    font-size: 10px;
}
QToolButton#propSectionArrow {
    border: none;
    background: transparent;
    color: #9ca3af;
    font-size: 11px;
}
QToolButton#propSectionArrow:hover {
    color: #2563eb;
}

QLabel#propLabel {
    color: #6b7280;
    font-size: 11px;
}
QLabel#propValue {
    color: #111827;
    font-size: 12px;
}
QLabel#propHint {
    color: #9ca3af;
    font-size: 11px;
}

QLineEdit#propField, QLineEdit#propFieldReadonly,
QSpinBox#propField, QDoubleSpinBox#propField {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    padding: 1px 5px;
    color: #111827;
    font-size: 12px;
    selection-background-color: #bfdbfe;
    selection-color: #111827;
}
QLineEdit#propField:hover, QSpinBox#propField:hover, QDoubleSpinBox#propField:hover {
    border-color: #9ca3af;
}
QLineEdit#propField:focus, QSpinBox#propField:focus, QDoubleSpinBox#propField:focus {
    border-color: #2563eb;
}
QLineEdit#propFieldReadonly {
    background: #f9fafb;
    color: #4b5563;
}
QLineEdit#propField:disabled, QSpinBox#propField:disabled,
QDoubleSpinBox#propField:disabled {
    background: #f3f4f6;
    color: #9ca3af;
    border-color: #e5e7eb;
}
QSpinBox#propField::up-button, QDoubleSpinBox#propField::up-button,
QSpinBox#propField::down-button, QDoubleSpinBox#propField::down-button {
    width: 13px;
    background: #f3f4f6;
    border-left: 1px solid #e5e7eb;
}
QSpinBox#propField::up-button:hover, QDoubleSpinBox#propField::up-button:hover,
QSpinBox#propField::down-button:hover, QDoubleSpinBox#propField::down-button:hover {
    background: #e0f2fe;
}

QPushButton#propSwatch {
    border: 1px solid #cbd5e1;
    border-radius: 4px;
}
QSlider#propSlider::groove:horizontal {
    height: 4px;
    background: #e5e7eb;
    border-radius: 2px;
}
QSlider#propSlider::sub-page:horizontal {
    background: #93c5fd;
    border-radius: 2px;
}
QSlider#propSlider::handle:horizontal {
    background: #2563eb;
    width: 10px;
    margin: -4px 0;
    border-radius: 5px;
}

QCheckBox#propCheck {
    color: #374151;
    font-size: 12px;
    spacing: 6px;
}
QCheckBox#propCheck::indicator {
    width: 13px;
    height: 13px;
    border: 1px solid #9ca3af;
    border-radius: 3px;
    background: #ffffff;
}
QCheckBox#propCheck::indicator:checked {
    background: #2563eb;
    border-color: #2563eb;
}
QTextEdit#propTextArea, QPlainTextEdit#propTextArea {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    padding: 4px;
    color: #111827;
    font-size: 12px;
    selection-background-color: #bfdbfe;
    selection-color: #111827;
}
QTextEdit#propTextArea:focus, QPlainTextEdit#propTextArea:focus {
    border-color: #2563eb;
}
QListWidget#propMemberList {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    font-size: 12px;
    color: #374151;
}
QListWidget#propMemberList::item {
    padding: 2px 6px;
}
QListWidget#propMemberList::item:selected {
    background: #dbeafe;
    color: #1d4ed8;
}
QComboBox#propField {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    padding: 1px 6px;
    color: #111827;
    font-size: 12px;
}
QComboBox#propField:hover { border-color: #9ca3af; }
QComboBox#propField:focus { border-color: #2563eb; }
QComboBox#propField::drop-down {
    width: 16px;
    border-left: 1px solid #e5e7eb;
}
"""


# ----------------------------------------------------------------------
# 基础字段
# ----------------------------------------------------------------------
def make_label(text: str) -> QLabel:
    """属性行左侧的字段名。右对齐，紧贴自己的字段，便于看清分组。"""

    label = QLabel(text)
    label.setObjectName("propLabel")
    label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return label


def make_value_label(text: str) -> QLabel:
    """只读值展示（ID、类型这类不可改也不该像输入框的字段）。"""

    label = QLabel(str(text))
    label.setObjectName("propValue")
    label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return _fit_policy(label, 60)


def make_line(
    text: str = "",
    read_only: bool = False,
    placeholder: str = "",
    tooltip: str = "",
    max_width: int = 340,
) -> QLineEdit:
    edit = QLineEdit(str(text))
    edit.setObjectName("propFieldReadonly" if read_only else "propField")
    edit.setFixedHeight(FIELD_HEIGHT)
    edit.setReadOnly(read_only)
    edit.setPlaceholderText(placeholder)
    if max_width:
        edit.setMaximumWidth(max_width)
    if tooltip:
        edit.setToolTip(tooltip)
    return _fit_policy(edit, 110)


def make_double(
    value: float,
    minimum: float = -1.0e6,
    maximum: float = 1.0e6,
    step: float = 1.0,
    decimals: int = 1,
    suffix: str = "",
    tooltip: str = "",
) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setObjectName("propField")
    box.setFixedHeight(FIELD_HEIGHT)
    box.setMaximumWidth(160)
    box.setDecimals(decimals)
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setKeyboardTracking(False)
    if suffix:
        box.setSuffix(suffix)
    if tooltip:
        box.setToolTip(tooltip)
    box.setValue(float(value))
    return _fit_policy(box, 90)


def make_int(
    value: int,
    minimum: int = 0,
    maximum: int = 9999,
    step: int = 1,
    suffix: str = "",
    tooltip: str = "",
) -> QSpinBox:
    box = QSpinBox()
    box.setObjectName("propField")
    box.setFixedHeight(FIELD_HEIGHT)
    box.setMaximumWidth(160)
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setKeyboardTracking(False)
    if suffix:
        box.setSuffix(suffix)
    if tooltip:
        box.setToolTip(tooltip)
    box.setValue(int(value))
    return _fit_policy(box, 90)


def make_check(text: str, checked: bool, tooltip: str = "") -> QCheckBox:
    box = QCheckBox(text)
    box.setObjectName("propCheck")
    box.setChecked(bool(checked))
    if tooltip:
        box.setToolTip(tooltip)
    return _fit_policy(box, 60)


def make_hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("propHint")
    label.setWordWrap(True)
    return label


def make_textarea(
    text: str = "",
    placeholder: str = "",
    tooltip: str = "",
    min_height: int = 64,
    max_height: int = 160,
) -> QPlainTextEdit:
    """多行纯文本编辑框，用于需要换行的内容（如控件的多行文本）。

    与单行字段不同，这里不套 ``_fit_policy``（那会把垂直策略锁成 Fixed，
    高度无法随内容撑开）；改为水平 Expanding、垂直在 min/max 高度之间自适应。
    """

    edit = QPlainTextEdit(str(text))
    edit.setObjectName("propTextArea")
    edit.setPlaceholderText(placeholder)
    edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    edit.setMinimumHeight(min_height)
    edit.setMaximumHeight(max_height)
    if tooltip:
        edit.setToolTip(tooltip)
    return edit


# ----------------------------------------------------------------------
# 复合字段
# ----------------------------------------------------------------------
class ColorField(QWidget):
    """色块 + 十六进制文本，两条输入路径写同一个颜色。"""

    colorChanged = Signal(QColor)

    def __init__(
        self,
        color: Optional[QColor] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setMaximumWidth(300)
        _fit_policy(self, 150)
        self._color = QColor(color) if color is not None else QColor("#000000")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._swatch = QPushButton(self)
        self._swatch.setObjectName("propSwatch")
        self._swatch.setFixedSize(26, FIELD_HEIGHT)
        self._swatch.setCursor(Qt.PointingHandCursor)
        self._swatch.setToolTip("点击选择颜色")
        self._swatch.clicked.connect(self._pick_color)

        self._edit = QLineEdit(self)
        self._edit.setObjectName("propField")
        self._edit.setFixedHeight(FIELD_HEIGHT)
        self._edit.setMinimumWidth(88)
        self._edit.setMaxLength(9)
        self._edit.setPlaceholderText("#RRGGBB")
        self._edit.editingFinished.connect(self._commit_text)

        layout.addWidget(self._swatch)
        layout.addWidget(self._edit, 1)

        self.set_color(self._color, notify=False)

    # -- public -------------------------------------------------------
    def color(self) -> QColor:
        return QColor(self._color)

    def set_color(self, color: QColor, notify: bool = False) -> None:
        if not isinstance(color, QColor) or not color.isValid():
            color = QColor("#000000")
        self._color = QColor(color)
        self._refresh_swatch()
        self._edit.blockSignals(True)
        self._edit.setText(self._color.name().upper())
        self._edit.blockSignals(False)
        if notify:
            self.colorChanged.emit(self.color())

    # -- internals ----------------------------------------------------
    def _refresh_swatch(self) -> None:
        self._swatch.setStyleSheet(
            "QPushButton#propSwatch {"
            f" background-color: {self._color.name()};"
            " border: 1px solid #cbd5e1; border-radius: 4px; }"
            "QPushButton#propSwatch:hover { border: 1px solid #2563eb; }"
        )

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(self._color, self.window(), "选择颜色")
        if chosen.isValid():
            self.set_color(chosen, notify=True)

    def _commit_text(self) -> None:
        text = self._edit.text().strip()
        candidate = QColor(text)
        if candidate.isValid():
            if candidate.name() != self._color.name():
                self.set_color(candidate, notify=True)
            else:
                self.set_color(candidate)
            return
        # 非法输入：回退到当前颜色，避免面板显示一个没生效的值
        self.set_color(self._color)


class OpacityField(QWidget):
    """0-255 的透明度，界面用 0-100% 表达（更符合直觉且不易输错）。"""

    valueChanged = Signal(int)

    def __init__(self, value: int = 255, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMaximumWidth(380)
        _fit_policy(self, 160)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._slider = QSlider(Qt.Horizontal, self)
        self._slider.setObjectName("propSlider")
        self._slider.setRange(0, 100)
        self._slider.setFixedHeight(FIELD_HEIGHT)
        self._slider.setToolTip("0% 全透明，100% 完全不透明")

        self._spin = QSpinBox(self)
        self._spin.setObjectName("propField")
        self._spin.setFixedHeight(FIELD_HEIGHT)
        self._spin.setFixedWidth(58)
        self._spin.setRange(0, 100)
        self._spin.setSuffix("%")
        self._spin.setKeyboardTracking(False)

        layout.addWidget(self._slider, 1)
        layout.addWidget(self._spin)

        self.set_value(value)
        self._slider.valueChanged.connect(self._on_slider)
        self._spin.valueChanged.connect(self._on_spin)

    # -- public -------------------------------------------------------
    def value(self) -> int:
        return int(round(self._slider.value() * 255 / 100))

    def set_value(self, value: int, notify: bool = False) -> None:
        percent = max(0, min(100, int(round(int(value) * 100 / 255))))
        for widget in (self._slider, self._spin):
            widget.blockSignals(True)
            widget.setValue(percent)
            widget.blockSignals(False)
        if notify:
            self.valueChanged.emit(self.value())

    # -- internals ----------------------------------------------------
    def _on_slider(self, percent: int) -> None:
        self._spin.blockSignals(True)
        self._spin.setValue(percent)
        self._spin.blockSignals(False)
        self.valueChanged.emit(self.value())

    def _on_spin(self, percent: int) -> None:
        self._slider.blockSignals(True)
        self._slider.setValue(percent)
        self._slider.blockSignals(False)
        self.valueChanged.emit(self.value())


# ----------------------------------------------------------------------
# 分组卡片
# ----------------------------------------------------------------------
class SectionCard(QFrame):
    """可折叠的属性分组卡片。

    卡片内部是 4 列网格：``label | value | label | value``。一行放一对属性时
    值控件横跨三列，放两对时各占一列，因此同一张卡片里两种排布都对齐。
    """

    def __init__(
        self,
        title: str,
        parent: Optional[QWidget] = None,
        expanded: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("propSection")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = QWidget(self)
        self._header.setObjectName("propSectionHeader")
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.installEventFilter(self)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        header_layout.setSpacing(6)

        self._arrow = QToolButton(self._header)
        self._arrow.setObjectName("propSectionArrow")
        self._arrow.setAutoRaise(True)
        self._arrow.setFixedSize(14, 14)
        self._arrow.setFocusPolicy(Qt.NoFocus)

        self._title = QLabel(title, self._header)
        self._title.setObjectName("propSectionTitle")

        self._badge = QLabel("", self._header)
        self._badge.setObjectName("propSectionBadge")
        self._badge.hide()

        header_layout.addWidget(self._arrow)
        header_layout.addWidget(self._title)
        header_layout.addStretch(1)
        header_layout.addWidget(self._badge)
        outer.addWidget(self._header)

        self._body = QWidget(self)
        self._body.setObjectName("propSectionBody")
        # 底部 dock 往往很宽；限制表单区的最大宽度，避免数值框被拉成一条横条。
        # 默认 Preferred 策略不会吃掉多余空间，这里显式声明横向 Expanding，
        # 表单才会真的长到 780px 再把剩余空间留在卡片右侧。
        self._body.setMaximumWidth(780)
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(10, 4, 10, 9)
        self._layout.setSpacing(6)
        outer.addWidget(self._body)

        self._arrow.clicked.connect(self.toggle)
        self._expanded = bool(expanded)
        self._apply_expanded()

    # -- public -------------------------------------------------------
    def body(self) -> QWidget:
        return self._body

    def add_row(self, *pairs: Optional[tuple[str, QWidget]]) -> None:
        """一行放 1 或 2 组 ``(标签, 控件)``。

        字段的水平策略是 ``Ignored``，所以每行两个字段按 stretch 严格等分
        剩余宽度；只放一对时右侧补一个同宽的占位，第一列字段宽度与两列
        行完全一致，整张卡片的标签和字段都落在同一条竖线上。
        """

        items = [pair for pair in pairs if pair is not None][:2]
        if not items:
            return

        row = QWidget(self._body)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        for index, (label, widget) in enumerate(items):
            if index:
                layout.addSpacing(6)
            name_label = make_label(label)
            name_label.setFixedWidth(LABEL_WIDTH)
            layout.addWidget(name_label)
            layout.addWidget(widget, 1)
        if len(items) == 1:
            layout.addSpacing(LABEL_WIDTH + 12)
            layout.addStretch(1)
        self._layout.addWidget(row)

    def add_widget(self, widget: QWidget, tooltip: str = "") -> None:
        if tooltip:
            widget.setToolTip(tooltip)
        self._layout.addWidget(widget)

    def add_hint(self, text: str) -> None:
        self._layout.addWidget(make_hint(text))

    def set_badge(self, text: str) -> None:
        self._badge.setText(text)
        self._badge.setVisible(bool(text))

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._apply_expanded()

    # -- internals ----------------------------------------------------
    def _apply_expanded(self) -> None:
        self._arrow.setText("\u25be" if self._expanded else "\u25b8")
        self._body.setVisible(self._expanded)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._header and event.type() == event.Type.MouseButtonRelease:
            self.toggle()
            return True
        return super().eventFilter(obj, event)


class ObjectHeader(QWidget):
    """属性面板顶部的当前对象摘要。

    左侧是类型字牌，右侧两行：名称（主）与 ``类型 · ID · 所属组``（次）。
    设计时一眼就能确认“我改的是哪个图元”，不必回到画布上找。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("propHeader")
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self._badge = QLabel("—", self)
        self._badge.setObjectName("propHeaderBadge")
        self._badge.setFixedSize(32, 32)
        self._badge.setAlignment(Qt.AlignCenter)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(1)
        self._title = QLabel("未选择图元", self)
        self._title.setObjectName("propHeaderTitle")
        self._meta = QLabel("", self)
        self._meta.setObjectName("propHeaderMeta")
        text_box.addWidget(self._title)
        text_box.addWidget(self._meta)

        layout.addWidget(self._badge)
        layout.addLayout(text_box, 1)

    def set_object(self, glyph: str, title: str, meta: str) -> None:
        self._badge.setText(glyph or "—")
        self._title.setText(title or "未选择图元")
        self._meta.setText(meta or "")
        self._meta.setVisible(bool(meta))


class EmptyState(QWidget):
    """没有可编辑对象时占位，顺带给出画布上的常用操作。"""

    def __init__(
        self,
        title: str,
        hint: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("propPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 24, 16, 16)
        layout.setSpacing(6)

        title_label = QLabel(title, self)
        title_label.setObjectName("propEmptyTitle")
        title_label.setAlignment(Qt.AlignCenter)
        hint_label = QLabel(hint, self)
        hint_label.setObjectName("propEmptyHint")
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(hint_label)
        layout.addStretch(1)


class PropertyPage(QWidget):
    """一个导航页的容器：纵向堆叠卡片 + 末尾留白。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("propPage")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)

    def add(self, widget: Optional[QWidget]) -> Optional[QWidget]:
        if widget is None:
            return None
        self._layout.insertWidget(self._layout.count() - 1, widget)
        return widget

    def add_card(self, card: Optional[SectionCard]) -> Optional[SectionCard]:
        self.add(card)
        return card
