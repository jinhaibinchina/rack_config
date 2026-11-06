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

from PySide6.QtCore import QRectF, QSize, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QTransform
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QToolTip,
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

#: 页面设计尺寸（像素，1:1 不缩放）。场景卡片的控件尺寸也按这个值校正，
#: 见 ``App_PopPick/hmi/binding.py`` 的 ``PAGE_PIXEL_SIZE``。
PAGE_SIZE = QSize(750, 1000)
#: 页头高度：内容区 = 1000 - 52 = 948（见 :data:`BODY_SIZE`）
HEADER_HEIGHT = 52
BODY_SIZE = QSize(PAGE_SIZE.width(), PAGE_SIZE.height() - HEADER_HEIGHT)

HMI_QSS = f"""
QWidget {{ background-color: {BG}; color: {TEXT};
           font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif; }}
QScrollArea {{ border: none; background: transparent; }}
QGroupBox {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 5px;
    margin-top: 15px; padding: 6px 6px 5px 6px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px;
                    color: {ACCENT}; font-weight: bold; font-size: 12px; }}
QLabel {{ background: transparent; }}
QLabel#hmiTitle {{ font-size: 16px; font-weight: bold; color: #ffffff; }}
QLabel#hmiSubtitle {{ color: {MUTED}; font-size: 10px; }}
QLabel#hmiValue {{ font-family: Consolas, 'Courier New', monospace;
                   font-size: 12px; color: #ffffff; }}
QLabel#hmiBadge {{ color: {WARN}; font-size: 9px; }}
QLineEdit, QDoubleSpinBox {{
    background: #0b1420; border: 1px solid {BORDER}; border-radius: 3px;
    padding: 1px 4px; color: {TEXT}; selection-background-color: #24567c;
    font-size: 11px;
}}
QPushButton {{
    background: #1d3550; border: 1px solid #36577c;
    border-radius: 3px; padding: 3px 8px; color: {TEXT}; font-size: 11px;
}}
QPushButton:hover {{ background: #2a4a70; }}
QPushButton:pressed {{ background: #35608f; }}
QPushButton:disabled {{ color: #5b6b7e; border-color: #2b3d52; background: #16202d; }}
QPushButton#hmiDanger {{ border-color: #8a3540; background: #3a1d25; }}
QPushButton#hmiDanger:hover {{ background: #552631; }}
QTableWidget {{
    background: #101c2a; alternate-background-color: #162434;
    gridline-color: {BORDER}; border: 1px solid {BORDER}; color: {TEXT};
    font-size: 11px;
}}
QTableWidget::item {{ padding: 1px 4px; }}
QHeaderView::section {{ background: #1b2d42; color: {ACCENT};
                        border: 0; border-right: 1px solid {BORDER};
                        padding: 2px 4px; font-size: 11px; }}
QTextEdit {{ background: #0a1320; border: 1px solid {BORDER};
             color: #cfe0f0; font-family: Consolas, 'Courier New', monospace;
             font-size: 11px; }}
QScrollBar:vertical {{ background: #101c2a; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #33506f; border-radius: 4px; }}
QScrollBar:horizontal {{ background: #101c2a; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #33506f; border-radius: 4px; }}
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
    # 基础字号走 QFont（12px）而不是 QSS：QSS 的 ``QWidget {{ font-size }}``
    # 是类型选择器，会盖掉子控件自己 setFont 的小字号，导致 11px 的名字
    # 按 12px 排版、48px 宽的标签只放得下 3 个字。
    font.setPixelSize(12)
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


def _pixel_font(widget: QWidget, pixel_size: int) -> None:
    """按像素设置字号。

    不要用 ``widget.setStyleSheet("font-size: 11px")``：页面根上的
    ``QWidget { font-size: 12px; }`` 是类型选择器，优先级高于控件自带样式表的
    通用选择器，结果 11px 根本不生效——名字一律按 12px 排版，48px 只够放 3 个字，
    "绝对距离" 就被省略成 "绝"。这里直接改 QFont，绕开级联。
    """
    font = widget.font()
    font.setPixelSize(pixel_size)
    widget.setFont(font)


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


class ElidedLabel(QLabel):
    """会省略号的标签：**长度不参与最小宽度，但宽度要参与布局**。

    750×1000 的页面里每列只有 200 多像素，长副标题 / 端点地址一旦按整段文字
    算 ``minimumSizeHint``，整页最小宽度就会被顶到 1200+，ScrollBody 只能把
    内容整体缩小——字号立刻糊掉。所以：

    * ``minimumSizeHint`` 只给 ``minimumWidth()``（默认 0），文字再长也能压；
    * ``sizeHint`` 给「文字实际宽度」，超过 ``maximumWidth()`` 就截断——这样
      端点/统计这种"有内容就该显示"的标签才拿得到宽度；
    * 真正画的时候再按当前宽度补省略号。

    注意**不能**用 ``QSizePolicy.Ignored`` 来实现上面第一条：Ignored 会让布局项
    的 ``sizeHint`` 恒为 0，同一行的后续控件全被排到同一个 x 上（只剩
    ``minimumWidth`` 被 ``setGeometry`` clamp 上去），结果是标签和输入框**叠**
    在一起——写入行曾经整行显示成「速 64.000」就是这个原因。
    """

    def __init__(self, text: str = "", parent: QWidget | None = None, *,
                 name: str = "") -> None:
        super().__init__(text, parent)
        self._full = text
        if name:
            self.setObjectName(name)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self._elide()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt 命名
        self._full = text
        self.setToolTip(text)
        self.updateGeometry()       # 宽度可能随文字变，让布局再问一次
        self._elide()

    def text(self) -> str:  # noqa: N802 - Qt 命名
        return self._full

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        text_height = self.fontMetrics().height()
        return QSize(self.minimumWidth(), text_height)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        fm = self.fontMetrics()
        width = fm.horizontalAdvance(self._full) + 2
        width = max(width, self.minimumWidth())
        width = min(width, self.maximumWidth())
        return QSize(width, fm.height())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(0, self.width())
        if width <= 0:
            super().setText(self._full)
            return
        fm = self.fontMetrics()
        super().setText(fm.elidedText(self._full, Qt.ElideRight, width))


# ----------------------------------------------------------------------
# 页头
# ----------------------------------------------------------------------
class PageHeader(QFrame):
    """标题 + 连接状态 + 时钟 + 已接入/未接入点统计。

    整体高度锁死在 :data:`HEADER_HEIGHT`（52px）：页面按 750×1000 设计，页头
    每多占 10px 就是内容区少 10px。副标题 / 端点 / 统计都用
    :class:`ElidedLabel`，宁可省略也不撑宽布局。
    """

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _root(self)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedHeight(HEADER_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(0)
        title_lab = QLabel(title)
        title_lab.setObjectName("hmiTitle")
        title_lab.setFixedHeight(20)
        left.addWidget(title_lab)
        left.addWidget(ElidedLabel(subtitle, name="hmiSubtitle"))
        layout.addLayout(left, 1)

        self._lamp = Lamp("OPC UA")
        self._lamp.setMinimumWidth(62)
        layout.addWidget(self._lamp)
        self._endpoint = ElidedLabel("")
        self._endpoint.setMaximumWidth(120)
        layout.addWidget(self._endpoint)
        self._stats = ElidedLabel("")
        self._stats.setMaximumWidth(104)
        layout.addWidget(self._stats)
        self._clock = QLabel("")
        self._clock.setStyleSheet(f"color: {TEXT}; font-family: Consolas; font-size: 12px;")
        self._clock.setFixedWidth(124)
        self._clock.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
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
            text += f" ｜待接入 {pending}"
        self._stats.setText(text)
        self._stats.setToolTip(text)

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
        # 按 7px/字 估宽（12px 字体差不多就这个数）：用 8px 会把 750 宽的页面
        # 里 6 列的灯阵顶成两倍宽，整页只能缩小显示。
        return QSize(max(40, 17 + 7 * len(self._text)), 22)

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
        # 圆点 10~14px：40px 宽的紧凑灯格里，点太大就没有文字的位置了。
        radius = max(4.0, min(7.0, (self.height() - 8) / 2))
        center_y = self.height() / 2
        left = 2.0
        painter.setBrush(self._color())
        painter.setPen(QPen(QColor("#0a111b"), 1))
        painter.drawEllipse(QRectF(left, center_y - radius, radius * 2, radius * 2))
        text_left = int(left + radius * 2 + 4)
        painter.setPen(QColor(TEXT if self._state is not None else MUTED))
        painter.drawText(text_left, 0, max(0, self.width() - text_left), self.height(),
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
        self.grid.setContentsMargins(5, 3, 5, 4)
        self.grid.setHorizontalSpacing(6)
        self.grid.setVerticalSpacing(3)
        self._row = 0
        self._col = 0
        self._finished = False

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

    def finish(self) -> None:
        """在卡片末尾补一根竖直弹簧，把富余高度留在底部。

        页面是 750×1000 固定画布，内容少的卡片会被布局拉高；如果没有这根
        弹簧，多出来的高度会被平均分给每一行——数值行之间出现 20~30px 的
        大缝，看着像排版坏了。加了之后行距保持设计值，空余留在卡片底部
        （行分隔线也不会飘在行中间）。

        卡里有会自己长大的控件（表格 / 日志 / 输入区）时不要加，否则会把
        本该给它的空间吃掉。

        注意：**不能用 ``grid.setRowStretch(self._row, 1)``**。Qt6 里对
        "当前行数之外"的行设 stretch 不生效（实测那根弹簧被忽略，多出的高度
        照样摊到第 0 行），必须真的塞一个竖直 Expanding 的 spacer 进去。
        """
        if self._finished:
            return
        for index in range(self.grid.count()):
            child = self.grid.itemAt(index).widget()
            if child is None:
                continue
            policy = child.sizePolicy().verticalPolicy()
            if policy in (QSizePolicy.Expanding, QSizePolicy.MinimumExpanding):
                return
        self.grid.addItem(
            QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding),
            self._row, 0, 1, 1,
        )
        self._finished = True

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
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(4)
        self._label = ElidedLabel(label)
        self._label.setStyleSheet(f"color: {MUTED};")
        _pixel_font(self._label, 11)
        # 名字给一个"够读"的最小宽度：PLC 的字符串值常常很长（版本号/时间戳），
        # 若名字的最小宽度是 0，布局会把整行都让给值，最后只剩数字没有名字。
        self._label.setMinimumWidth(self._label_min_width(label))
        layout.addWidget(self._label, 1)
        self._badge = QLabel("")
        self._badge.setObjectName("hmiBadge")
        layout.addWidget(self._badge)
        self._value = ElidedLabel("--")
        self._value.setObjectName("hmiValue")
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value.setMinimumWidth(44)
        layout.addWidget(self._value, 2)
        # 当前文字颜色（"" = 用样式表默认色）；用于跳过重复的 setStyleSheet
        self._color = ""
        if ref is not None:
            self.apply_ref(ref)

    @staticmethod
    def _label_min_width(label: str) -> int:
        """按 11px 字体估一个"够读"的名字宽度（中文约 11px/字，ASCII 约 6px）。

        只在 40~60 之间取值：太窄名字会被值吃掉（只剩数字），太宽半屏卡片
        里两列数值就排不下。
        """
        width = 0
        for ch in label:
            width += 11 if ord(ch) > 0x2E80 else 6
        return max(40, min(60, width + 6))

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
                 writable: bool = False, compact: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _root(self)
        self.rows, self.cols = rows, cols
        self.prefix = prefix
        self.compact = bool(compact)
        self._lamps: list[Lamp] = []
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2 if self.compact else 4)
        cell_w, cell_h = (40, 20) if self.compact else (48, 22)
        for r in range(rows):
            for c in range(cols):
                index = r * cols + c
                text = (labels[index] if labels and index < len(labels)
                        else f"{prefix}{index}")
                lamp = Lamp(text)
                # 灯阵常被塞进紧凑分区；给每格一个硬下限，避免 QGridLayout
                # 把 6×8 的格子压到十几像素高、相邻两行文字画到一起。
                lamp.setMinimumSize(cell_w, cell_h)
                _pixel_font(lamp, 10 if self.compact else 11)
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
        self.setMinimumHeight(26)
        self.ref = ref
        self._current: Any = None
        self._touched = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(6)
        self._label = ElidedLabel(label)
        self._label.setStyleSheet(f"color: {MUTED};")
        _pixel_font(self._label, 11)
        self._label.setMinimumWidth(TagValue._label_min_width(label))
        layout.addWidget(self._label, 0)
        self._value = ElidedLabel("--")
        self._value.setObjectName("hmiValue")
        self._value.setMinimumWidth(36)
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._value, 0)

        numeric = (ref.variable_type or "").upper() in (
            "INT", "UINT", "UDINT", "DINT", "BYTE", "WORD", "DWORD",
            "REAL", "LREAL", "FLOAT", "DOUBLE",
        )
        if numeric:
            self._editor = QDoubleSpinBox()
            self._editor.setDecimals(3)
            self._editor.setRange(-1e9, 1e9)
            self._editor.setButtonSymbols(QDoubleSpinBox.NoButtons)
            self._editor.setMinimumWidth(56)
        else:
            self._editor = QLineEdit()
            self._editor.setPlaceholderText("新值")
            self._editor.setMinimumWidth(56)
        self._editor.setMaximumWidth(72)
        layout.addWidget(self._editor, 0)
        # 写按钮推到最右：宽卡片里不要挤在标签旁边
        layout.addStretch(1)
        signal = (self._editor.valueChanged if isinstance(self._editor, QDoubleSpinBox)
                  else self._editor.textChanged)
        signal.connect(self._mark_touched)

        self._button = QPushButton("写")
        self._button.setFixedWidth(30)
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


def _button_min_hint(button: "QPushButton") -> QSize:
    """按钮的最小尺寸按文字宽度算。

    Qt 自带样式给 ``QPushButton`` 的 ``minimumSizeHint`` 是 80×24（与文字无关），
    4 个一排就要 320px，把半屏宽的轴卡撑到 366px、整页刚好顶死 750。这里按
    实际文字宽度 + 内边距兜底，''故障确认'' 这种 4 字按钮也只要 64px。
    """
    fm = button.fontMetrics()
    return QSize(max(40, fm.horizontalAdvance(button.text()) + 16),
                 button.minimumHeight())


class MomentaryButton(QPushButton):
    """按住写 True、松开写 False 的点动按钮（PLC 侧不自复位的 BOOL）。"""

    write_requested = Signal(str, object)

    def __init__(self, text: str, ref: TagRef, *, danger: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        _root(self)
        self.setMinimumHeight(26)
        self.ref = ref
        if danger:
            self.setObjectName("hmiDanger")
        self.setEnabled(ref.connected)
        self.setToolTip(f"变量: {ref.expr}\n状态: {ref.status}")
        if ref.connected and ref.key:
            key = ref.key
            self.pressed.connect(lambda: self.write_requested.emit(key, True))
            self.released.connect(lambda: self.write_requested.emit(key, False))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        return _button_min_hint(self)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        return _button_min_hint(self)


class PulseButton(QPushButton):
    """点一下写 True（PLC 程序自复位的命令按钮）。"""

    write_requested = Signal(str, object)
    confirm_requested = Signal(str, str, str, str, str, object)

    def __init__(self, text: str, ref: TagRef, *, danger: bool = False,
                 confirm: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        _root(self)
        self.setMinimumHeight(26)
        self.ref = ref
        self.confirm = confirm
        if danger:
            self.setObjectName("hmiDanger")
        self.setEnabled(ref.connected)
        self.setToolTip(f"变量: {ref.expr}\n状态: {ref.status}")
        if ref.connected and ref.key:
            self.clicked.connect(self._on_click)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        return _button_min_hint(self)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        # 网格/盒式布局分列时会参考 sizeHint（Qt 默认给 80px），这里跟最小
        # 尺寸对齐，按钮再多也不会把卡片撑宽。
        return _button_min_hint(self)

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
    """只读表格，支持高亮一行（例如当前执行行 / 当前报警）。

    750 宽的页面里列不能按内容撑开（8 列表格一撑就出横向滚动条），统一用
    ``Stretch`` 平均分配；行高收到 18px，16 行的寄存器表也只占 310px。
    """

    def __init__(self, headers: Sequence[str], rows: int = 0,
                 parent: QWidget | None = None, *, row_height: int = 18) -> None:
        super().__init__(rows, len(headers), parent)
        _root(self)
        self.setHorizontalHeaderLabels(list(headers))
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(row_height)
        # 行高铺满整张表：10 行报警放在 300px 高的卡片里时，行拉开比
        # "上面 10 行、下面一片空白" 好看得多。
        # 行高不合适时**调卡片的竖向权重**，别指望 setMaximumSectionSize：
        # Qt 只在 Interactive/Fixed 模式下遵守它，Stretch 模式下会被忽略。
        self.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.horizontalHeader().setFixedHeight(20)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.horizontalHeader().setMinimumSectionSize(22)
        # 表格的 minimumSizeHint 是按表头文字算的，8 列表格能顶到 430px，
        # 把半屏宽的卡片撑爆。这里显式给一个下限，宽度交给布局分配。
        self.setMinimumWidth(60)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setVerticalScrollMode(QTableWidget.ScrollPerPixel)

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
    """页面内容区：画布**固定**为 750×948，1:1 呈现，没有滚动条也不缩放。

    设计目标变了：以前是按内容 ``minimumSizeHint`` 定画布、再整体缩放塞进
    视口，结果 7 页内容宽度 1015~1770 不等，缩到 750 宽时字号只剩 0.42~0.73
    倍。现在页面就是 750×1000（``PAGE_SIZE``），内容区 750×948，布局必须
    在这个画布里排得下——不再偷偷缩小字号。

    超出画布时**不会被缩小**，而是让 :meth:`overflow` 报出来：验证脚本会
    断言 ``overflow() <= 0``，这样"某天多加一行把底部裁掉"能立刻发现，而不是
    悄悄把整页字号缩小 10%。

    焦点：内嵌 view 与 viewport 都必须 ``StrongFocus``，否则输入框点得进去
    却收不到键盘事件（项目里验证过的坑）。
    """

    def __init__(self, design: QSize | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _root(self)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: transparent; border: none;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
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
        self.vbox.setContentsMargins(6, 4, 6, 6)
        self.vbox.setSpacing(6)
        # addWidget 前不能先 setParent；尺寸由 proxy.resize 驱动，
        # 不要给 content 设 setFixedSize / minimumSize(1,1)。
        self.proxy = scene.addWidget(self.content)
        self._design = QSizeF(design or BODY_SIZE)
        self._need = QSizeF(0, 0)
        self.proxy.resize(self._design.width(), self._design.height())
        self.setSceneRect(0, 0, self._design.width(), self._design.height())
        self._sync_retries = 0

    # ------------------------------------------------------------------
    # 设计画布
    # ------------------------------------------------------------------
    def set_design_size(self, size: QSize | QSizeF) -> None:
        self._design = QSizeF(size)
        self.proxy.resize(self._design.width(), self._design.height())
        self.setSceneRect(0, 0, self._design.width(), self._design.height())
        self._refit()

    def design_size(self) -> QSizeF:
        return QSizeF(self._design)

    def overflow(self) -> QSizeF:
        """内容比设计画布大出的部分（宽/高，<=0 表示装得下）。"""
        self._measure()
        return QSizeF(self._need.width() - self._design.width(),
                      self._need.height() - self._design.height())

    def content_minimum(self) -> QSizeF:
        self._measure()
        return QSizeF(self._need)

    def finalize(self) -> None:
        """``build()`` 后调用一次；真正可靠的测量在 :meth:`resizeEvent`。

        画布尺寸不再随内容变化，这里只是把内容的最小尺寸量出来，量不到就
        排到下一轮事件循环重试。
        """
        self._measure()
        self._refit()

    def _measured(self) -> QSize:
        """当前布局的最小尺寸；布局还没被激活时返回 (0, 0)。"""
        if self.vbox.count() == 0:
            return QSize(0, 0)
        self.vbox.invalidate()
        self.vbox.activate()
        return self.vbox.minimumSize()

    def _measure(self) -> None:
        need = self._measured()
        # 布局第一次被激活之前（页面还没 show），``minimumSize()`` 只有边距
        # （12×10），不能当成"内容很小"缓存下来——排到下一轮事件循环重试。
        if need.width() <= 20 or need.height() <= 20:
            if self._sync_retries < 20:
                self._sync_retries += 1
                QTimer.singleShot(0, self._measure)
            return
        self._sync_retries = 0
        self._need = QSizeF(need)
        # 画布固定，内容超出就让它超出：调用方用 overflow() 判定，
        # 绝不因为"多了一行"就把整页缩成 0.9 倍字。

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        # show 之后布局才算得准；每次尺寸变化都重新量一次。
        self._measure()
        self._refit()

    def _refit(self) -> None:
        """把设计画布放进视口；画布正好等于视口时缩放严格为 1.0。

        用 ``fitInView`` 而不是手写 ``setTransform``：后者只改变换矩阵，
        QGraphicsView 仍按未缩放的 sceneRect 做对齐/裁剪，结果就是内容
        右侧被切掉一块。不放大超过 1.0：页面就是 750×1000，视口更大时
        留白，字号不变。
        """
        rect = self.sceneRect()
        if rect.isEmpty():
            return
        self.fitInView(rect, Qt.KeepAspectRatio)
        scale = self.transform().m11()
        # 视口和画布一样大时 fitInView 会算出 0.995 这种浮点误差（frame 边），
        # 差一点点也会让整页轻微模糊；误差在 1% 内直接吸附成 1:1。
        if abs(scale - 1.0) < 0.01 or scale > 1.0:
            self.setTransform(QTransform().scale(1.0, 1.0))
            self.centerOn(rect.center())

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.vbox.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout, stretch: int = 0) -> None:
        self.vbox.addLayout(layout, stretch)

    def stretch(self) -> None:
        self.vbox.addStretch(1)
