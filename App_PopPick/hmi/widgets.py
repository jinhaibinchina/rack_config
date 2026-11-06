"""PopPick HMI 页面通用控件。

这些控件最终通过 ``widget_element.set_widget_factory`` 挂进场景，外层是
``EmbeddedWidgetLayer`` 的透明 QGraphicsView + QGraphicsProxyWidget。有两条
约束必须遵守（见项目里 embedded_widget_layer 的验证记录）：

* 根控件要 ``setMinimumSize(1, 1)``，给 0,0 不生效，proxy 会被
  minimumSizeHint 卡住导致包围盒偏大、控件被裁；
* 根控件**不要** ``setFixedSize``，尺寸由 ``proxy.resize(w, h)`` 驱动，
  fix 之后包围盒不跟手。子控件的尺寸约束不受此限。

配色按工业 HMI 深色主题：底色 #0e1620，正常绿、报警红、警告橙、信息蓝。
所有"没数据"都显示 ``--`` 和灰灯，绝不把 None 当成 False/0 显示成正常态。
"""

from __future__ import annotations

import html
import time
from typing import Any, Sequence

from PySide6.QtCore import QSize, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTransform
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolTip,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .tag_catalog import TagRef, as_bool, clean_text, format_value

# ----------------------------------------------------------------------
# 主题
# ----------------------------------------------------------------------
BG = "#cad9eb"
CARD = "#162334"
BORDER = "#2b3d52"
TEXT = "#0C0C0C"
MUTED = "#8ba0b8"
ACCENT = "#48b8ff"
OK = "#36d08a"
WARN = "#ffb648"
ERR = "#ff5f6d"
UNKNOWN = "#4a5a6d"

HMI_QSS = f"""
QWidget {{ background-color: {BG}; color: {TEXT};
           font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif; font-size: 13px; }}
QScrollArea {{ border: none; background: transparent; }}
QGroupBox {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px;
    margin-top: 20px; padding: 10px 8px 8px 8px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px;
                    color: {ACCENT}; font-weight: bold; font-size: 14px; }}
QLabel {{ background: transparent; }}
QLabel#hmiTitle {{ font-size: 22px; font-weight: bold; color: #ffffff; }}
QLabel#hmiSubtitle {{ color: {MUTED}; font-size: 12px; }}
QLabel#hmiValue {{ font-family: Consolas, 'Courier New', monospace;
                   font-size: 15px; color: #ffffff; }}
QLabel#hmiBadge {{ color: {WARN}; font-size: 11px; }}
QLineEdit, QDoubleSpinBox {{
    background: #0b1420; border: 1px solid {BORDER}; border-radius: 3px;
    padding: 3px 6px; color: {TEXT}; selection-background-color: #24567c;
}}
QPushButton {{
    background: #1d3550; border: 1px solid #36577c;
    border-radius: 3px; padding: 5px 12px; color: {TEXT};
}}
QPushButton:hover {{ background: #2a4a70; }}
QPushButton:pressed {{ background: #35608f; }}
QPushButton:disabled {{ color: #5b6b7e; border-color: #2b3d52; background: #16202d; }}
QPushButton#hmiDanger {{ border-color: #8a3540; background: #3a1d25; }}
QPushButton#hmiDanger:hover {{ background: #552631; }}
QTableWidget {{
    background: #101c2a; alternate-background-color: #162434;
    gridline-color: {BORDER}; border: 1px solid {BORDER}; color: {TEXT};
}}
QTableWidget::item {{ padding: 3px 6px; }}
QHeaderView::section {{ background: #1b2d42; color: {ACCENT};
                        border: 0; border-right: 1px solid {BORDER}; padding: 5px; }}
QTextEdit {{ background: #0a1320; border: 1px solid {BORDER};
             color: #cfe0f0; font-family: Consolas, 'Courier New', monospace; }}
QScrollBar:vertical {{ background: #101c2a; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #33506f; border-radius: 5px; }}
QScrollBar:horizontal {{ background: #101c2a; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #33506f; border-radius: 5px; }}
"""


def apply_theme(widget: QWidget) -> None:
    """把 HMI 样式挂到页面根控件（子控件自动继承）。

    字体族显式列几个中文字体：现场触摸机可能没装雅黑，Qt 的字体回退在
    纯英文默认字体下不一定挑得到 CJK 字体，中文会变成方块。
    """
    font = QFont()
    font.setFamilies([
        "Microsoft YaHei", "Microsoft YaHei UI", "SimHei",
        "Noto Sans CJK SC", "WenQuanYi Micro Hei", "DejaVu Sans",
    ])
    font.setPointSize(9)
    widget.setFont(font)
    widget.setStyleSheet(HMI_QSS)


def _root(widget: QWidget) -> None:
    """内部子控件保留 Qt 自己的 minimumSizeHint，**不要**设 (1,1)。

    ``setMinimumSize(1, 1)`` 是 ``EmbeddedWidgetLayer.set_widget`` 对被承载
    的**顶层页面**的要求（越过 sizeHint 让 proxy.resize 生效），承载层自己
    也会再设一遍。若连每个子控件都设成 (1,1)，父 QGridLayout 就认为一行
    可以压到 1 像素，密集页面的数值行会挤成一条模糊的线。
    页面根由 :class:`HmiPage` 单独设置。
    """
    return None


def _same_state(a: Any, b: Any) -> bool:
    """状态去重：``True`` / ``1`` 视为同一态，``None`` 与字符串按原值比较。

    PLC 经常「值没变也推一次」，而代理控件上任何一次 update() 都等于重画
    整张页面，所以重复状态必须在这里挡掉。
    """
    if a is None or b is None:
        return a is b
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    return a == b


def small_label(text: str, *, color: str = MUTED, name: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(f"color: {color};")
    if name:
        lab.setObjectName(name)
    return lab


# ----------------------------------------------------------------------
# 页头
# ----------------------------------------------------------------------
class PageHeader(QFrame):
    """标题 + 连接状态 + 时钟 + 已接入/未接入点统计。"""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _root(self)
        self.setFrameShape(QFrame.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)

        left = QVBoxLayout()
        title_lab = QLabel(title)
        title_lab.setObjectName("hmiTitle")
        left.addWidget(title_lab)
        left.addWidget(small_label(subtitle, name="hmiSubtitle"))
        layout.addLayout(left, 1)

        self._lamp = Lamp("OPC UA")
        layout.addWidget(self._lamp)
        self._endpoint = small_label("")
        layout.addWidget(self._endpoint)
        self._stats = small_label("")
        layout.addWidget(self._stats)
        self._clock = QLabel("")
        self._clock.setStyleSheet(f"color: {TEXT}; font-family: Consolas; font-size: 14px;")
        layout.addWidget(self._clock)

        # 时钟**默认不自带定时器**：页面被 QGraphicsProxyWidget 接管后，改一个
        # 标签的字就会重画整张页面，而 7 个页面各挂一个 1s 定时器时，每秒会
        # 触发 7 次整页重绘（实测把事件循环拖到每秒只能跑 2 轮）。主程序里由
        # HmiPagesHost 用**一条**定时器只驱动最前面那一页；独立预览窗口可调
        # start_clock() 自己驱动。
        self._timer: QTimer | None = None
        self.tick_clock()
        self.set_connection(False, "")

    def tick_clock(self) -> None:
        """刷新页头时间；文字没变就什么都不做（省掉一次整页重绘）。"""
        text = time.strftime("%Y-%m-%d  %H:%M:%S")
        if text != self._clock.text():
            self._clock.setText(text)

    def start_clock(self, interval_ms: int = 1000) -> None:
        """独立驱动时钟（预览窗口 / 单页调试用）。

        主程序不要为 7 个页面各调一次，见 :class:`HmiPagesHost` 的统一时钟。
        """
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.tick_clock)
        self._timer.setInterval(interval_ms)
        self._timer.start()

    def set_connection(self, connected: bool, endpoint: str) -> None:
        self._lamp.set_state(connected)
        self._lamp.set_text("已连接" if connected else "未连接")
        self._endpoint.setText(clean_text(endpoint) if endpoint else "离线模式")
        self._endpoint.setToolTip(clean_text(endpoint))

    def set_stats(self, connected: int, total: int, pending: int = 0) -> None:
        text = f"点位 {connected}/{total}"
        if pending:
            text += f" ｜ 待接入 {pending}"
        self._stats.setText(text)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()


# ----------------------------------------------------------------------
# 状态灯
# ----------------------------------------------------------------------
class Lamp(QWidget):
    """自绘圆点 + 文字。三态：True(绿) / False(灰) / None(未知，暗灰)。

    ``set_state`` 也接受 ``"warn"`` / ``"err"`` / ``"info"`` 字符串，用来表达
    报警等级这类不是布尔的状态。
    """

    toggled = Signal(bool)

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _root(self)
        self._state: Any = None
        self._text = text
        self._clickable = False
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumHeight(22)

    def set_text(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text
        self.update()

    def set_state(self, state: Any) -> None:
        # 状态没变就不要触发重绘：一次 update() 在代理里等于重画整张页面，
        # 而 PLC 推送里大量点位是「值没变也推」的。
        if _same_state(self._state, state):
            return
        self._state = state
        self.update()

    def set_clickable(self, enabled: bool) -> None:
        self._clickable = enabled
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        return QSize(max(48, 22 + 8 * len(self._text)), 22)

    def _color(self) -> QColor:
        state = self._state
        if state is None:
            return QColor(UNKNOWN)
        if state == "err":
            return QColor(ERR)
        if state == "warn":
            return QColor(WARN)
        if state == "info":
            return QColor(ACCENT)
        value = as_bool(state)
        if value is None:
            return QColor(UNKNOWN)
        return QColor(OK) if value else QColor("#3c4a5c")

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        radius = min(8, (self.height() - 6) / 2)
        center_y = self.height() / 2
        painter.setBrush(self._color())
        painter.setPen(QPen(QColor("#0a111b"), 1))
        painter.drawEllipse(self.rect().left() + radius / 2 + 2,
                            center_y - radius, radius * 2, radius * 2)
        painter.setPen(QColor(TEXT if self._state is not None else MUTED))
        painter.drawText(int(radius * 2 + 10), 0,
                         self.width() - int(radius * 2) - 10, self.height(),
                         Qt.AlignVCenter | Qt.AlignLeft, clean_text(self._text))
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self._clickable and event.button() == Qt.LeftButton:
            new = not bool(as_bool(self._state))
            self.set_state(new)
            self.toggled.emit(new)
        super().mousePressEvent(event)


# ----------------------------------------------------------------------
# 分区卡片
# ----------------------------------------------------------------------
class Card(QGroupBox):
    """带标题的分区，内部是 QGridLayout，页面按行列往里塞控件。"""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        _root(self)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(8, 6, 8, 6)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(6)
        self._row = 0
        self._col = 0

    def add(self, widget: QWidget, *, row: int | None = None, col: int | None = None,
            span: int = 1) -> QWidget:
        r = self._row if row is None else row
        c = self._col if col is None else col
        self.grid.addWidget(widget, r, c, 1, span)
        if row is None:
            self._col += span
        else:
            # 显式定位后把游标推到这一行之后：页面里常先摆几个固定行、再
            # 用 fill_row / addLayout 续接，游标不动会把后续控件叠回旧行。
            self._row = max(self._row, r + 1)
            self._col = 0
        return widget

    def add_row(self, *widgets: QWidget) -> None:
        for index, widget in enumerate(widgets):
            self.grid.addWidget(widget, self._row, index)
        self._row += 1
        self._col = 0

    def newline(self) -> None:
        self._row += 1
        self._col = 0

    def fill_row(self, items: Sequence[QWidget], columns: int = 4) -> None:
        for index, widget in enumerate(items):
            self.grid.addWidget(widget, self._row + index // columns, index % columns)
        self._row += (len(items) + columns - 1) // columns
        self._col = 0


# ----------------------------------------------------------------------
# 数值显示
# ----------------------------------------------------------------------
class TagValue(QWidget):
    """一行「名称 : 值」，带节点来源 tooltip 与未接入标记。"""

    clicked = Signal()

    def __init__(self, label: str, ref: TagRef | None = None, *,
                 unit: str = "", precision: int = 2,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _root(self)
        self.setMinimumHeight(22)
        self.ref = ref
        self.unit = unit or (ref.unit if ref else "")
        self.precision = precision
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)
        self._label = QLabel(label)
        self._label.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(self._label, 1)
        self._badge = QLabel("")
        self._badge.setObjectName("hmiBadge")
        layout.addWidget(self._badge)
        self._value = QLabel("--")
        self._value.setObjectName("hmiValue")
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value.setMinimumWidth(76)
        layout.addWidget(self._value)
        # 当前文字颜色（"" = 用样式表默认色）；用于跳过重复的 setStyleSheet
        self._color = ""
        if ref is not None:
            self.apply_ref(ref)

    def apply_ref(self, ref: TagRef) -> None:
        self.ref = ref
        tip = (f"变量: {ref.expr}\n状态: {ref.status}\n"
               f"类型: {ref.variable_type or '未知'}\n"
               f"NodeId: {clean_text(ref.node_id) if ref.node_id else '（无）'}")
        if ref.note:
            tip += f"\n说明: {ref.note}"
        self.setToolTip(tip)
        if not ref.connected:
            self._badge.setText("未接入")
            self._color = WARN
            self._value.setStyleSheet(f"color: {WARN};")
            self._value.setText("--")
        else:
            self._badge.setText("")
            self._color = ""
            self._value.setStyleSheet("")

    def set_value(self, value: Any, *, level: str = "") -> None:
        if self.ref is not None and not self.ref.connected:
            return
        text = format_value(value, unit=self.unit, precision=self.precision)
        # setText 与 setStyleSheet 都会标脏整张页面：值没变就别动，
        # 颜色没变也别重设样式表（重设会触发样式重新解析）。
        if text != self._value.text():
            self._value.setText(text)
        color = {"err": ERR, "warn": WARN, "ok": OK, "info": ACCENT}.get(level, "")
        if color != self._color:
            self._color = color
            self._value.setStyleSheet(f"color: {color};" if color else "")

    def current_text(self) -> str:
        return self._value.text()


# ----------------------------------------------------------------------
# 灯阵
# ----------------------------------------------------------------------
class IndicatorGrid(QWidget):
    """按 rows × cols 排列的灯阵，用于 IO 点 / 输送带 / 任务位。

    ``set_values`` 接受数组整体节点推回来的值（list / bytes / 标量都行），
    页面不用关心服务端把 BOOL 数组打包成什么形态。
    """

    cell_toggled = Signal(int, bool)

    def __init__(self, rows: int = 1, cols: int = 8, *,
                 prefix: str = "", labels: Sequence[str] | None = None,
                 writable: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _root(self)
        self.rows, self.cols = rows, cols
        self.prefix = prefix
        self._lamps: list[Lamp] = []
        layout = QGridLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        for r in range(rows):
            for c in range(cols):
                index = r * cols + c
                text = (labels[index] if labels and index < len(labels)
                        else f"{prefix}{index}")
                lamp = Lamp(text)
                # 灯阵常被塞进紧凑分区；给每格一个硬下限，避免 QGridLayout
                # 把 6×8 的格子压到十几像素高、相邻两行文字画到一起。
                lamp.setMinimumSize(58, 22)
                lamp.set_clickable(writable)
                lamp.toggled.connect(
                    lambda state, i=index: self.cell_toggled.emit(i, state)
                )
                layout.addWidget(lamp, r, c)
                self._lamps.append(lamp)

    def set_values(self, value: Any) -> None:
        from .tag_catalog import array_items

        items = array_items(value, len(self._lamps))
        for lamp, item in zip(self._lamps, items):
            lamp.set_state(item)

    def set_item(self, index: int, value: Any) -> None:
        if 0 <= index < len(self._lamps):
            self._lamps[index].set_state(value)

    def clear(self) -> None:
        for lamp in self._lamps:
            lamp.set_state(None)

    def set_writable(self, writable: bool) -> None:
        for lamp in self._lamps:
            lamp.set_clickable(writable)


# ----------------------------------------------------------------------
# 可写控件
# ----------------------------------------------------------------------
def _coerce(raw: str, var_type: str) -> Any:
    typ = (var_type or "").upper()
    text = raw.strip()
    if typ in ("BOOL", "BYTE", "WORD", "DWORD", "INT", "UINT", "UDINT", "SINT", "USINT"):
        if typ == "BOOL":
            return text.lower() in ("1", "true", "on", "yes", "是")
        # 编辑框是 QDoubleSpinBox 时会给出 "24.0"，int("24.0", 0) 直接抛错
        return int(float(text))
    if typ in ("REAL", "LREAL", "FLOAT", "DOUBLE"):
        return float(text)
    return text


class ConfirmBar(QFrame):
    """页面内嵌的写入确认条，**不用模态 QMessageBox**。

    页面被挂在 ``QGraphicsProxyWidget`` 里（外面还套了一层内容视图），
    模态对话框在这个层级里会弹出来但内容渲染空白、按钮点不动——现场
    表现为「确认框卡住」。这里改成页面内一条可点的横幅：列出变量、
    当前值、拟写入值、NodeId，点「确认写入」才真正下发。
    """

    accepted = Signal(str, object)  # (业务 key, 值)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _root(self)
        self.setObjectName("hmiConfirmBar")
        self.setStyleSheet(
            f"QFrame#hmiConfirmBar {{ background: #1b3350; "
            f"border: 2px solid {ACCENT}; border-radius: 5px; }}"
            f"QLabel {{ color: {TEXT}; background: transparent; }}"
        )
        self._key: str | None = None
        self._value: Any = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        self._label = QLabel("")
        layout.addWidget(self._label, 1)
        self._ok = QPushButton("确认写入")
        self._cancel = QPushButton("取消")
        layout.addWidget(self._ok)
        layout.addWidget(self._cancel)
        self._ok.clicked.connect(self._accept)
        self._cancel.clicked.connect(self.hide)
        self.hide()

    def request(self, label: str, old: str, new: str, node: str,
                key: str, value: Any) -> None:
        self._key, self._value = key, value
        self._label.setText(
            f"确认写入 <b>{html.escape(label)}</b>　"
            f"{html.escape(old)} → <b>{html.escape(new)}</b>　"
            f"<span style=\"color:{MUTED}\">{html.escape(node)}</span>"
        )
        self.show()
        self.raise_()

    def _accept(self) -> None:
        key, value = self._key, self._value
        self._key, self._value = None, None
        self.hide()
        if key is not None:
            self.accepted.emit(key, value)


class WritableValue(QWidget):
    """数值/文本写入行：当前值 + 输入框 + 写入按钮。

    点「写入」不会直接下发，而是交给页面的 :class:`ConfirmBar` 显示
    变量名 / 当前值 / 拟写入值 / NodeId，确认后才写。未接入的点按钮禁用。
    """

    write_requested = Signal(str, object)       # 保留兼容（不再由此控件发出）
    confirm_requested = Signal(str, str, str, str, str, object)  # label/old/new/node/key/value

    def __init__(self, label: str, ref: TagRef, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _root(self)
        self.setMinimumHeight(30)
        self.ref = ref
        self._current: Any = None
        self._touched = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        self._label = QLabel(label)
        self._label.setStyleSheet(f"color: {MUTED};")
        self._label.setMinimumWidth(110)
        layout.addWidget(self._label)
        self._value = QLabel("--")
        self._value.setObjectName("hmiValue")
        self._value.setMinimumWidth(90)
        layout.addWidget(self._value)

        numeric = (ref.variable_type or "").upper() in (
            "INT", "UINT", "UDINT", "DINT", "BYTE", "WORD", "DWORD",
            "REAL", "LREAL", "FLOAT", "DOUBLE",
        )
        if numeric:
            self._editor = QDoubleSpinBox()
            self._editor.setDecimals(3)
            self._editor.setRange(-1e9, 1e9)
            self._editor.setMinimumWidth(110)
        else:
            self._editor = QLineEdit()
            self._editor.setPlaceholderText("新值")
            self._editor.setMinimumWidth(110)
        layout.addWidget(self._editor)
        signal = (self._editor.valueChanged if isinstance(self._editor, QDoubleSpinBox)
                  else self._editor.textChanged)
        signal.connect(self._mark_touched)

        self._button = QPushButton("写入")
        self._button.setMaximumWidth(70)
        self._button.clicked.connect(self._on_write)
        layout.addWidget(self._button)
        self._badge = QLabel("" if ref.connected else "未接入")
        self._badge.setObjectName("hmiBadge")
        layout.addWidget(self._badge)
        self._button.setEnabled(ref.connected)
        self._editor.setEnabled(ref.connected)
        self.setToolTip(
            f"变量: {ref.expr}\n状态: {ref.status}\n"
            f"NodeId: {clean_text(ref.node_id) if ref.node_id else '（无）'}"
        )

    def _editor_value(self) -> Any:
        if isinstance(self._editor, QDoubleSpinBox):
            raw = str(self._editor.value())
        else:
            raw = self._editor.text()
        return _coerce(raw, self.ref.variable_type)

    def _mark_touched(self, *_args) -> None:
        self._touched = True

    def set_value(self, value: Any) -> None:
        self._current = value
        self._value.setText(format_value(value, unit=self.ref.unit))
        # 用户还没动过输入框时，把 PLC 当前值带进去：改参数时不用先查再抄一遍。
        # 一旦用户开始编辑就不再覆盖，否则订阅推送会把正在输入的内容冲掉。
        if self._touched or value is None:
            return
        self._editor.blockSignals(True)
        try:
            if isinstance(self._editor, QDoubleSpinBox):
                try:
                    self._editor.setValue(float(value))
                except (TypeError, ValueError):
                    pass
            else:
                self._editor.setText(clean_text(value) if isinstance(value, str)
                                     else format_value(value))
        finally:
            self._editor.blockSignals(False)

    def _on_write(self) -> None:
        if not self.ref.connected or self.ref.key is None:
            return
        try:
            value = self._editor_value()
        except ValueError:
            # 非模态提示：模态框在承载层里点不动，气泡提示不会抢事件循环
            QToolTip.showText(
                self.mapToGlobal(self.rect().center()),
                f"输入无效：无法把输入解析成 {self.ref.variable_type}",
            )
            return
        old = format_value(self._current, unit=self.ref.unit)
        new = format_value(value, unit=self.ref.unit)
        self.confirm_requested.emit(
            self.ref.label, old, new,
            clean_text(self.ref.node_id) if self.ref.node_id else "（无）",
            self.ref.key, value,
        )


class MomentaryButton(QPushButton):
    """按住写 True、松开写 False 的点动按钮（PLC 侧不自复位的 BOOL）。"""

    write_requested = Signal(str, object)

    def __init__(self, text: str, ref: TagRef, *, danger: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        _root(self)
        self.setMinimumHeight(28)
        self.ref = ref
        if danger:
            self.setObjectName("hmiDanger")
        self.setEnabled(ref.connected)
        self.setToolTip(f"变量: {ref.expr}\n状态: {ref.status}")
        if ref.connected and ref.key:
            key = ref.key
            self.pressed.connect(lambda: self.write_requested.emit(key, True))
            self.released.connect(lambda: self.write_requested.emit(key, False))


class PulseButton(QPushButton):
    """点一下写 True（PLC 程序自复位的命令按钮）。"""

    write_requested = Signal(str, object)
    confirm_requested = Signal(str, str, str, str, str, object)

    def __init__(self, text: str, ref: TagRef, *, danger: bool = False,
                 confirm: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        _root(self)
        self.setMinimumHeight(28)
        self.ref = ref
        self.confirm = confirm
        if danger:
            self.setObjectName("hmiDanger")
        self.setEnabled(ref.connected)
        self.setToolTip(f"变量: {ref.expr}\n状态: {ref.status}")
        if ref.connected and ref.key:
            self.clicked.connect(self._on_click)

    def _on_click(self) -> None:
        if self.ref.key is None:
            return
        if self.confirm:
            # 危险/关键命令走页面内的确认条，不弹模态框
            self.confirm_requested.emit(
                self.text(), "—", "True",
                clean_text(self.ref.node_id) if self.ref.node_id else "（无）",
                self.ref.key, True,
            )
        else:
            self.write_requested.emit(self.ref.key, True)


# ----------------------------------------------------------------------
# 表格 / 日志
# ----------------------------------------------------------------------
class DataTable(QTableWidget):
    """只读表格，支持高亮一行（例如当前执行行 / 当前报警）。"""

    def __init__(self, headers: Sequence[str], rows: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(rows, len(headers), parent)
        _root(self)
        self.setHorizontalHeaderLabels(list(headers))
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_rows(self, rows: Sequence[Sequence[Any]], *, highlight: int = -1) -> None:
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                text = clean_text(value) if isinstance(value, str) else format_value(value)
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if r == highlight:
                    item.setBackground(QColor("#284e6d"))
                    item.setForeground(QColor("#ffffff"))
                self.setItem(r, c, item)
        self.resizeColumnsToContents()


class LogView(QTextEdit):
    """带行号的文本区；既能显示 PLC 推来的字符串数组，也能追加本地日志。"""

    LEVEL_COLORS = {"info": "#bcd2e8", "ok": OK, "warn": WARN, "err": ERR}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _root(self)
        self.setReadOnly(True)
        self._lines: list[str] = []

    def set_lines(self, lines: Sequence[Any], *, highlight: int = -1) -> None:
        self._lines = [clean_text(x) if isinstance(x, str) else format_value(x)
                       for x in lines]
        parts = []
        for index, text in enumerate(self._lines):
            bg = "#284e6d" if index == highlight else ("#111e2d" if index % 2 else "#0d1826")
            marker = "▶" if index == highlight else " "
            parts.append(
                f'<div style="background:{bg};padding:1px 6px;white-space:pre;">'
                f'<span style="color:#6c89a8;">{index:02d}</span> '
                f'<span style="color:#5fc8ff;">{marker}</span> '
                f'<span style="color:#dbe7f4;">{html.escape(text)}</span></div>'
            )
        self.setHtml("".join(parts) or '<div style="color:#6c89a8;">（无记录）</div>')

    def append_line(self, text: str, level: str = "info") -> None:
        color = self.LEVEL_COLORS.get(level, "#bcd2e8")
        stamp = time.strftime("%H:%M:%S")
        self.append(
            f'<div style="white-space:pre;"><span style="color:#6c89a8;">[{stamp}]</span> '
            f'<span style="color:{color};">{html.escape(clean_text(text))}</span></div>'
        )

    def clear_log(self) -> None:
        self.clear()
        self._lines = []


# ----------------------------------------------------------------------
# 页面外壳
# ----------------------------------------------------------------------
class ScrollBody(QGraphicsView):
    """页面内容区：按内容自身尺寸**整体缩放**铺进视口，没有滚动条。

    QScrollArea 的两条路都不合现场要求：压缩内容会把密集页面的行压成糊字，
    放滚动条又明确不要。这里改用与 ``EmbeddedWidgetLayer`` 同一套
    ``QGraphicsScene + QGraphicsProxyWidget``：内容按 ``minimumSizeHint``
    的原始尺寸排一次（不压缩、不重叠、信息不丢），再由 view 的 transform
    整体缩放到视口。字号随缩放矢量变小，放大到「最大窗口」仍然清晰。

    焦点：内嵌 view 与 viewport 都必须 ``StrongFocus``，否则输入框点得进去
    却收不到键盘事件（项目里验证过的坑）。
    """

    MIN_DESIGN_W = 320
    MIN_DESIGN_H = 240

    MIN_DESIGN_W = 240
    MIN_DESIGN_H = 320

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _root(self)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: transparent; border: none;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setFocusPolicy(Qt.StrongFocus)
        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.TextAntialiasing
            | QPainter.SmoothPixmapTransform
        )
        # 代理内容改一次就重画一次，尽量少做无用功：只重画脏区域，
        # 且不为每个 item 保存/恢复 painter 状态。
        self.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)
        self.setOptimizationFlags(QGraphicsView.DontSavePainterState)

        scene = QGraphicsScene(self)
        self.setScene(scene)
        self.content = QWidget()
        self.content.setStyleSheet(f"background: {BG};")
        self.vbox = QVBoxLayout(self.content)
        self.vbox.setContentsMargins(12, 6, 12, 12)
        self.vbox.setSpacing(10)
        # addWidget 前不能先 setParent；尺寸由 proxy.resize 驱动，
        # 不要给 content 设 setFixedSize / minimumSize(1,1)。
        self.proxy = scene.addWidget(self.content)
        self._design = QSizeF(self.MIN_DESIGN_W, self.MIN_DESIGN_H)
        self.proxy.resize(self.MIN_DESIGN_W, self.MIN_DESIGN_H)
        self.setSceneRect(0, 0, self.MIN_DESIGN_W, self.MIN_DESIGN_H)
        self._sync_retries = 0

    def finalize(self) -> None:
        """``build()`` 后调用一次；真正可靠的同步在 :meth:`resizeEvent`。

        构造期布局可能还没 polish，``minimumSize()`` 接近 0，所以这里只做
        一次尝试，之后每次 view resize 都会用 :meth:`_sync_design` 校正。
        """
        self._sync_design()
        self._refit()

    def _sync_design(self) -> None:
        """用布局的当前最小尺寸刷新设计画布（幂等，尺寸没变就不动）。"""
        self.content.ensurePolished()
        self.vbox.activate()
        need = self.vbox.minimumSize()
        # 首个页面在 polish 前可能给出「很小但非 0」的尺寸（例如 100×100），
        # 只判 <=0 会把它当成合法值 clamp 成 320×240，之后不再重试。
        if need.width() < self.MIN_DESIGN_W or need.height() <= 0:
            # 首帧还没 polish，布局暂时算不出尺寸；排到下一轮事件循环再试，
            # 否则第一个页面会永远停在 320×240、右侧整片被裁。
            if self._sync_retries < 5:
                self._sync_retries += 1
                QTimer.singleShot(0, self._sync_and_refit)
            return
        self._sync_retries = 0
        width = max(int(need.width()), self.MIN_DESIGN_W)
        height = max(int(need.height()), self.MIN_DESIGN_H)
        if (abs(width - self._design.width()) < 2
                and abs(height - self._design.height()) < 2):
            return
        self._design = QSizeF(width, height)
        self.proxy.resize(width, height)
        self.setSceneRect(0, 0, width, height)

    def _sync_and_refit(self) -> None:
        self._sync_design()
        self._refit()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        # show 之后布局才算得准；每次尺寸变化都校正一次，第一页也不会
        # 永远卡在 320×240。
        self._sync_design()
        self._refit()

    def _refit(self) -> None:
        """把整张设计画布等比放进视口。

        用 ``fitInView`` 而不是手写 ``setTransform``：后者只改变换矩阵，
        QGraphicsView 仍按未缩放的 sceneRect 做对齐/裁剪，结果就是内容
        右侧被切掉一块。fitInView 会同时算好变换和可见区域，保证
        sceneRect 完整落在视口内。不放大超过 1.0，避免空白页字号失控。
        """
        rect = self.sceneRect()
        if rect.isEmpty():
            return
        self.fitInView(rect, Qt.KeepAspectRatio)
        if self.transform().m11() > 1.0:
            self.setTransform(QTransform().scale(1.0, 1.0))

    def add(self, widget: QWidget) -> QWidget:
        self.vbox.addWidget(widget)
        return widget

    def add_layout(self, layout, stretch: int = 0) -> None:
        self.vbox.addLayout(layout, stretch)

    def stretch(self) -> None:
        self.vbox.addStretch(1)
