# -*- coding: utf-8 -*-
"""「电机监控窗口」widget 图元上挂载的伺服轴监控面板。

截图版式（``轴 1 ｜ asServoStatus[1] / asManualServo[1]``）：11 个状态灯
（6+5）、9 个实时值（5+4）、11 个命令按钮、3 组「当前值 / 新值 / 写」。
字段名、变量名与 ``App_test_fixture/pages.py`` 的 ``AxisMonitorPage`` 逐项
一致，但**不复用那套代码**：它是 750×1000 的 ``HmiPage`` 外壳
（PageHeader + ScrollBody + 内嵌 QGraphicsView），还依赖 ``data/`` 下并不
存在的 OPC UA 节点导出文件；而本图元给控件的逻辑尺寸只有 468×345。

这里是一块自包含、随图元尺寸自适应的普通 ``QWidget``，通过统一运行态的
:class:`~DesignerV2.CoreQGraphics.runtime.ControlProvider` 挂进 ``WidgetHost``：

.. code-block:: python

    from DesignerV2.CoreQGraphics.runtime import ControlProvider
    from App_test_fixture.servo_panel import ServoPanelProvider

    stage.set_mapping({"电机监控窗口": ServoPanelProvider()})
    stage.load()

数据链路（面板本身不认识任何协议）::

    DataSource.valuesChanged → TagBus → panel.set_values(dict)
    panel.commandRequested(key, value) → DataSource.write(key, value)

想挂**别的窗口**（例如已有的 C++/Qt 伺服面板）不用改本文件，换掉 provider
即可；``QWindow.fromWinId`` + ``QWidget.createWindowContainer`` 那条路也适用：

.. code-block:: python

    class ExternalPanelProvider(ControlProvider):
        def signature(self, element): return ("external", WIN_ID)
        def create(self, element, host=None):
            window = QWindow.fromWinId(WIN_ID)
            return QWidget.createWindowContainer(window)

    runtime = FixtureRuntime(panel_provider=ExternalPanelProvider())

两条来自旧 ``EmbeddedWidgetLayer`` 的硬约束在这里同样适用：

* 根控件 ``setMinimumSize(1, 1)``，否则 ``proxy.resize(w, h)`` 会被
  ``minimumSizeHint`` 顶住，控件被裁；
* 根控件不设 ``setFixedSize``，尺寸由 proxy 驱动；按钮的最小宽度按文字算，
  不然 Qt 默认 80px 会把 6 列按钮行撑爆。

确认条不用模态框：页面挂在 QGraphicsProxyWidget 里，模态对话框会弹出来
但内容空白、按钮点不动（旧 HMI 验证记录里的坑）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from Designer_V2.CoreQGraphics.runtime import ControlProvider

from . import fixture_config as cfg


# ---------------------------------------------------------------- 规格
@dataclass(frozen=True)
class PanelSpec:
    """面板的静态描述（标签 / 点位 / 版式），与控件实现分离。"""

    axis_index: int
    title: str
    status: tuple[tuple[str, str, bool], ...]
    values: tuple[tuple[str, str, str], ...]
    # (标签, 点位, 是否需要二次确认)——与 cfg.AXIS_MOMENTARY_FIELDS 同形，
    # 构造和消费必须都是 3 元组，否则 __init__ 解包会抛 ValueError。
    momentary: tuple[tuple[str, str, bool], ...]
    commands: tuple[tuple[str, str, bool], ...]
    writes: tuple[tuple[str, str, str], ...]
    font_px: int = cfg.PANEL_FONT_PX
    title_px: int = cfg.PANEL_TITLE_PX
    show_status: bool = cfg.PANEL_SHOW_STATUS
    confirm: bool = cfg.PANEL_CONFIRM

    @classmethod
    def from_config(cls, index: int | None = None) -> "PanelSpec":
        n = cfg.AXIS_INDEX if index is None else int(index)
        st = cfg.axis_status_key
        ma = cfg.axis_manual_key
        return cls(
            axis_index=n,
            title=(f"轴 {n}  ｜  {cfg.AXIS_STATUS_VAR.split('.')[-1]}[{n}]"
                   f" / {cfg.AXIS_MANUAL_VAR.split('.')[-1]}[{n}]"),
            status=tuple((lab, st(f), alarm)
                         for lab, f, alarm in cfg.AXIS_STATUS_FIELDS),
            values=tuple((lab, st(f), unit)
                         for lab, f, unit in cfg.AXIS_VALUE_FIELDS),
            momentary=tuple((lab, ma(f), confirm)
                            for lab, f, confirm in cfg.AXIS_MOMENTARY_FIELDS),
            commands=tuple((lab, ma(f), confirm)
                           for lab, f, confirm in cfg.AXIS_COMMAND_FIELDS),
            writes=tuple((lab, ma(f), unit)
                         for lab, f, unit in cfg.AXIS_WRITE_FIELDS),
        )

    @property
    def display_keys(self) -> tuple[str, ...]:
        return (tuple(k for _, k, _ in self.status)
                + tuple(k for _, k, _ in self.values)
                + tuple(k for _, k, _ in self.writes))


class ServoPanelProvider(ControlProvider):
    """按图元名注入面板；``signature`` 固定，换页/对齐时不会被误判重建。"""

    def __init__(self, spec: PanelSpec | None = None) -> None:
        super().__init__()
        self.spec = spec or PanelSpec.from_config()

    def signature(self, element) -> tuple:
        return ("servo-axis", self.spec.axis_index, self.spec.font_px,
                int(self.spec.confirm))

    def create(self, element, host: QWidget | None = None) -> QWidget:
        return ServoAxisPanel(self.spec)


# ---------------------------------------------------------------- 工具
def _font(widget: QWidget, px: int, *, mono: bool = False) -> None:
    font = QFont()
    font.setFamilies(["Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
                      "Segoe UI", "DejaVu Sans"] if not mono else
                     ["Consolas", "Courier New", "DejaVu Sans Mono"])
    font.setPixelSize(px)
    widget.setFont(font)


def _as_state(value: Any) -> bool | None:
    """三态：``None`` 无数据 / ``True`` / ``False``。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text == "":
            return None
        return text in ("1", "true", "on", "yes", "是", "ok")
    return None


def _format(value: Any, unit: str = "") -> str:
    if value is None:
        return "--"
    if isinstance(value, bool):
        text = "ON" if value else "OFF"
    elif isinstance(value, float):
        text = f"{value:.2f}"
    elif isinstance(value, str):
        # 空字符串（错误说明 / 未上电时的模式字）也显示占位符，
        # 否则界面上会出现一块看起来像控件没加载的空白。
        text = value or "--"
    else:
        text = str(value)
    return f"{text} {unit}".strip() if unit else text


def _panel_qss() -> str:
    return f"""
QGroupBox#servoPanel {{
    background: {cfg.PANEL_BG}; border: 1px solid {cfg.PANEL_BORDER};
    border-radius: 8px; margin-top: 13px; padding: 4px 2px 2px 2px;
}}
QGroupBox#servoPanel::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 5px;
    color: {cfg.PANEL_TEXT}; font-weight: bold;
}}
QLabel {{ background: transparent; color: {cfg.PANEL_TEXT}; }}
QLabel#servoMuted {{ color: {cfg.PANEL_MUTED}; }}
QLabel#servoValue {{ font-family: Consolas, 'Courier New', monospace; }}
QPushButton#servoCmd {{
    background: {cfg.PANEL_BTN_BG}; color: {cfg.PANEL_TEXT};
    border: 1px solid #b9c8da; border-radius: 4px; padding: 2px 5px;
}}
QPushButton#servoCmd:hover {{ background: #ffffff; }}
QPushButton#servoCmd:pressed {{ background: #c8d8ec; }}
QLineEdit#servoEdit {{
    background: #ffffff; color: {cfg.PANEL_TEXT};
    border: none; border-bottom: 1px solid #93a6bd; padding: 0 2px;
}}
QFrame#servoSep {{ color: #b9c8da; }}
QFrame#servoConfirm {{
    background: #1b3350; border: 1px solid #48b8ff; border-radius: 4px;
}}
QFrame#servoConfirm QLabel {{ color: #ffffff; }}
QFrame#servoConfirm QPushButton {{
    background: #eef3fa; color: #1b3350; border: none;
    border-radius: 3px; padding: 2px 8px;
}}
"""


# ---------------------------------------------------------------- 基础控件
class StatusLamp(QWidget):
    """自绘圆点 + 文字；无数据 / False 都是深灰，报警位 True 用红色。"""

    def __init__(self, label: str, *, alarm: bool = False, font_px: int = 11,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self.alarm = alarm
        self._state: bool | None = None
        self.setObjectName("servoLamp")
        self.setMinimumHeight(20)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        _font(self, font_px)
        self.setToolTip(label)

    @property
    def state(self) -> bool | None:
        return self._state

    def set_state(self, value: Any) -> None:
        state = _as_state(value)
        if state == self._state:
            return
        self._state = state
        self.update()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 20)

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self.font())
        return QSize(18 + fm.horizontalAdvance(self.label), 20)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r = 6.0
        cy = self.height() / 2.0
        if self._state is None:
            color = QColor(cfg.PANEL_LAMP_OFF)
        elif self._state:
            color = QColor(cfg.PANEL_LAMP_ALARM if self.alarm
                           else cfg.PANEL_LAMP_ON)
        else:
            color = QColor(cfg.PANEL_LAMP_OFF)
        painter.setBrush(color)
        painter.setPen(QPen(QColor("#26364a"), 1))
        painter.drawEllipse(QRectF(1.0, cy - r, r * 2, r * 2))
        left = int(r * 2 + 5)
        painter.setPen(QColor(cfg.PANEL_MUTED if self._state is None
                              else cfg.PANEL_TEXT))
        painter.setFont(self.font())
        text = QFontMetrics(self.font()).elidedText(
            self.label, Qt.ElideRight, max(0, self.width() - left))
        painter.drawText(left, 0, max(0, self.width() - left), self.height(),
                         Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.end()


class _ValueLabel(QLabel):
    """右对齐数值标签：宽度不够时自动缩字号，**绝不从左侧裁字**。

    QLabel 右对齐且分配宽度小于文字宽度时，Qt 直接把超出的左半截裁掉，
    既没有省略号也不缩小字号。现场出现过 ``1174.74 mm/s`` 被显示成
    ``174.74 mm/s``（首位 1 被削成一条竖线），``100.00`` 被显示成 ``1.00``。
    这里在文本变化 / 尺寸变化时按 QFontMetrics 找到能放下全文的最大字号，
    下限 ``min_px``；字号可升可降，宽度恢复后会自动回到基础字号。

    只改字号、不动 minimumWidth，因此不会顶住 ``proxy.resize`` 把面板
    压到图元尺寸的硬约束。
    """

    def __init__(self, px: int, *, min_px: int = 7,
                 parent: QWidget | None = None) -> None:
        super().__init__("--", parent)
        self._base_px = max(int(px), min_px)
        self._min_px = min_px
        self._applied_px = self._base_px

    def setText(self, text: str) -> None:  # noqa: N802 - Qt 命名
        super().setText(text)
        self._fit()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        text = self.text()
        if not text:
            return
        avail = max(1, self.width() - 2)     # 2px 余量，抵消 QSS 字体差异
        base = self.font()
        target = self._min_px
        for px in range(self._base_px, self._min_px - 1, -1):
            probe = QFont(base)
            probe.setPixelSize(px)
            if QFontMetrics(probe).horizontalAdvance(text) <= avail:
                target = px
                break
        if target != self._applied_px:
            fitted = QFont(base)
            fitted.setPixelSize(target)
            self.setFont(fitted)
            self._applied_px = target


class ValueCell(QWidget):
    """一行「名称 : 值」，无数据显示 ``--``。

    名称按 ``sizeHint`` 拿刚好的宽度，数值拿剩余空间（不再五五开），
    再由 :class:`_ValueLabel` 兜底保证任何宽度下都完整显示。
    """

    def __init__(self, label: str, unit: str = "", *, font_px: int = 11,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self.unit = unit
        self.setMinimumWidth(0)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(3)
        self._name = QLabel(label)
        self._name.setObjectName("servoMuted")
        self._name.setMinimumWidth(0)
        self._name.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        _font(self._name, font_px)
        layout.addWidget(self._name, 0)
        self._value = _ValueLabel(font_px)
        self._value.setObjectName("servoValue")
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value.setMinimumWidth(26)
        self._value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        _font(self._value, font_px, mono=True)
        layout.addWidget(self._value, 1)
        self.setToolTip(label)

    def set_value(self, value: Any) -> None:
        text = _format(value, self.unit)
        if self._value.text() != text:
            self._value.setText(text)
        self._value.setToolTip(text)

    def current_text(self) -> str:
        return self._value.text()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 20)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(96, 20)


class CmdButton(QPushButton):
    """最小宽度按文字算，避免 Qt 默认 80px 把按钮行撑出容器。"""

    def __init__(self, text: str, *, font_px: int = 11,
                 parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("servoCmd")
        self.setMinimumHeight(24)
        _font(self, font_px)

    def _hint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(max(38, fm.horizontalAdvance(self.text()) + 14), 24)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self._hint()

    def sizeHint(self) -> QSize:  # noqa: N802
        return self._hint()


class MomentaryButton(CmdButton):
    """按住写 True、松开写 False（PLC 侧不自复位的 BOOL）。

    ``confirm=True`` 时按下先弹页面内确认条，确认后发一个 ``True → False``
    脉冲：定位执行 / 速度执行 / 回零这类是自复位命令，确认时鼠标早已松开，
    既不能让 PLC 停在 True，也不能因为误按就直接下发。
    """

    triggered = Signal(str, object)
    confirmRequested = Signal(str, str, object)   # (key, 标签, 值)

    def __init__(self, text: str, key: str, *, confirm: bool = False, font_px: int = 11,
                 parent: QWidget | None = None) -> None:
        super().__init__(text, font_px=font_px, parent=parent)
        self.key = key
        self.confirm = confirm
        self.setToolTip(f"{key}\n按住 = True，松开 = False"
                        + ("（需确认）" if confirm else ""))
        self.pressed.connect(self._on_pressed)
        self.released.connect(self._on_released)

    def _on_pressed(self) -> None:
        if self.confirm:
            self.confirmRequested.emit(self.key, self.text(), True)
        else:
            self.triggered.emit(self.key, True)

    def _on_released(self) -> None:
        if not self.confirm:
            self.triggered.emit(self.key, False)


class PulseButton(CmdButton):
    """点一下写 True（PLC 自复位）；``confirm=True`` 先走页面内确认条。"""

    triggered = Signal(str, object)
    confirmRequested = Signal(str, str, object)   # (key, 标签, 值)

    def __init__(self, text: str, key: str, *, confirm: bool = False,
                 font_px: int = 11, parent: QWidget | None = None) -> None:
        super().__init__(text, font_px=font_px, parent=parent)
        self.key = key
        self.confirm = confirm
        self.setToolTip(f"{key}\n点按写 True" + ("（需确认）" if confirm else ""))
        self.clicked.connect(self._on_click)

    def _on_click(self) -> None:
        if self.confirm:
            self.confirmRequested.emit(self.key, self.text(), True)
        else:
            self.triggered.emit(self.key, True)

class ToggleButton(CmdButton):
    """点一下写 True / False 交替（PLC 自复位）。"""

    triggered = Signal(str, object)
    confirmRequested = Signal(str, str, object)   # (key, 标签, 值)

    def __init__(self, text: str, key: str, *, confirm: bool = False, font_px: int = 11,
                 parent: QWidget | None = None) -> None:
        super().__init__(text, font_px=font_px, parent=parent)
        self.key = key
        self.confirm = confirm
        self._state: bool = False
        self.setToolTip(f"{key}\n点按切换 True / False"
                        + ("（需确认）" if confirm else ""))
        self.clicked.connect(self._on_click)

    def _on_click(self) -> None:
        if self.confirm:
            self.confirmRequested.emit(self.key, self.text(), True)
        else:
            self._state = not self._state
            self.triggered.emit(self.key, self._state)


class WriteRow(QWidget):
    """「标签 + 当前值」在上、「新值输入 + 写」在下。

    图元只有 468 逻辑像素宽，三组写入横排时每组约 156px；把四个部件
    全塞进一行会把值和输入框压成几条线（实测 "99.47 mm/s" 被裁成
    ".47 mm/s"）。上下两行后 156px 绰绰有余，仍保持截图那种三组并排。
    """

    writeRequested = Signal(str, object)

    def __init__(self, label: str, key: str, unit: str = "", *,
                 font_px: int = 11, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.label = label
        self.key = key
        self.unit = unit
        self.setMinimumWidth(0)
        self.setToolTip(key)
        # 两边各用一条独立的 QHBoxLayout：QGridLayout 会让第二行的输入框
        # 参与第一列宽度计算，把「当前值」挤到只剩 40px（100.00 → 1.00）。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(3, 1, 3, 1)
        outer.setSpacing(1)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)
        name = QLabel(label)
        name.setObjectName("servoMuted")
        name.setMinimumWidth(0)
        _font(name, font_px)
        top.addWidget(name, 0)
        self._current = _ValueLabel(font_px)
        self._current.setObjectName("servoValue")
        self._current.setMinimumWidth(52)
        self._current.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._current.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        _font(self._current, font_px, mono=True)
        top.addWidget(self._current, 1)
        outer.addLayout(top)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(4)
        self._edit = QLineEdit()
        self._edit.setObjectName("servoEdit")
        self._edit.setPlaceholderText("新值")
        self._edit.setMinimumWidth(36)
        self._edit.setMaximumWidth(120)
        _font(self._edit, font_px)
        bottom.addWidget(self._edit, 1)
        btn = CmdButton("写", font_px=font_px)
        btn.setFixedWidth(30)
        btn.clicked.connect(self._emit)
        bottom.addWidget(btn, 0)
        outer.addLayout(bottom)

    def set_current(self, value: Any) -> None:
        text = _format(value, self.unit)
        if self._current.text() != text:
            self._current.setText(text)
        self._current.setToolTip(text)

    def current_text(self) -> str:
        return self._current.text()

    def new_value(self) -> str:
        return self._edit.text()

    def set_new_value(self, text: str) -> None:
        self._edit.setText(text)

    def _emit(self) -> None:
        raw = self._edit.text().strip()
        if not raw:
            return
        try:
            value: Any = float(raw)
            if value.is_integer():
                value = int(value)
        except ValueError:
            value = raw
        self.writeRequested.emit(self.key, value)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 44)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(150, 44)


class ConfirmBanner(QFrame):
    """页面内确认条（不用模态框），浮在面板顶部，不占布局高度。"""

    accepted = Signal(str, object)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("servoConfirm")
        self._key: str | None = None
        self._value: Any = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 6, 2)
        layout.setSpacing(6)
        self._label = QLabel("")
        _font(self._label, 11)
        layout.addWidget(self._label, 1)
        ok = QPushButton("确认")
        cancel = QPushButton("取消")
        for button in (ok, cancel):
            button.setFixedWidth(46)
            _font(button, 11)
            layout.addWidget(button, 0)
        ok.clicked.connect(self._accept)
        cancel.clicked.connect(self.hide)
        self.hide()

    def request(self, label: str, key: str, value: Any) -> None:
        self._key, self._value = key, value
        self._label.setText(f"确认执行「{label}」？  {key} ← True")
        self.show()
        self.raise_()

    def _accept(self) -> None:
        key, value = self._key, self._value
        self._key, self._value = None, None
        self.hide()
        if key is not None:
            self.accepted.emit(key, value)


# ---------------------------------------------------------------- 面板
class ServoAxisPanel(QGroupBox):
    """一块可挂进任意 widget 图元的伺服轴监控卡片。

    ``commandRequested(key, value)`` 统一出口：点动 / 脉冲 / 参数写入都走它，
    由 :class:`~App_test_fixture.fixture_runtime.FixtureRuntime` 转给
    ``DataSource.write``。面板本身不持有数据源，也不写任何设计数据。
    """

    commandRequested = Signal(str, object)

    def __init__(self, spec: PanelSpec | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spec = spec or PanelSpec.from_config()
        s = self.spec
        self.setObjectName("servoPanel")
        self.setTitle(s.title)
        self.setStyleSheet(_panel_qss())
        _font(self, s.title_px)

        root = QVBoxLayout(self)
        root.setContentsMargins(7, 2, 7, 4)
        root.setSpacing(3)

        # -- 状态灯 / 数值 / 按钮 / 写入，四段各自独立网格，列宽互不牵连
        self.lamps: dict[str, StatusLamp] = {}
        self.cells: dict[str, ValueCell] = {}
        self.buttons: dict[str, CmdButton] = {}
        self.writes: dict[str, WriteRow] = {}

        self._lamp_host, self._lamp_grid = self._block()
        for label, key, alarm in s.status:
            lamp = StatusLamp(label, alarm=alarm, font_px=s.font_px)
            lamp.set_state(None)
            self.lamps[key] = lamp
            self._lamp_grid.addWidget(lamp, 0, 0)     # 位置由 _relayout 统一排

        self._value_host, self._value_grid = self._block(spacing=7)
        for label, key, unit in s.values:
            cell = ValueCell(label, unit, font_px=s.font_px)
            self.cells[key] = cell
            self._value_grid.addWidget(cell, 0, 0)

        sep = QFrame()
        sep.setObjectName("servoSep")
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)

        self._cmd_host, self._cmd_grid = self._block(spacing=3)
        for label, key, confirm in s.momentary:
            button = MomentaryButton(label, key,
                                     confirm=confirm and s.confirm,
                                     font_px=s.font_px)
            button.triggered.connect(self.commandRequested.emit)
            button.confirmRequested.connect(self._request_confirm)
            self.buttons[key] = button
            self._cmd_grid.addWidget(button, 0, 0)
        for label, key, confirm in s.commands:
            button = ToggleButton(label, key,
                                 confirm=confirm and s.confirm,
                                 font_px=s.font_px)
            button.triggered.connect(self.commandRequested.emit)
            button.confirmRequested.connect(self._request_confirm)
            self.buttons[key] = button
            self._cmd_grid.addWidget(button, 0, 0)

        self._write_host, self._write_grid = self._block(spacing=5)
        for label, key, unit in s.writes:
            row = WriteRow(label, key, unit, font_px=s.font_px)
            row.writeRequested.connect(self.commandRequested.emit)
            self.writes[key] = row
            self._write_grid.addWidget(row, 0, 0)

        root.addWidget(self._lamp_host, 2)
        root.addWidget(self._value_host, 2)
        root.addWidget(sep, 0)
        root.addWidget(self._cmd_host, 2)
        root.addWidget(self._write_host, 1)

        self._status: QLabel | None = None
        if s.show_status:
            self._status = QLabel("等待数据…")
            self._status.setObjectName("servoMuted")
            self._status.setFixedHeight(16)
            _font(self._status, max(9, s.font_px - 1))
            root.addWidget(self._status, 0)

        self.confirm = ConfirmBanner(self)
        self._confirm_source: CmdButton | None = None
        self.confirm.accepted.connect(self._on_confirm_accepted)
        self._cols: tuple[int, int, int, int] | None = None
        # 硬约束：proxy.resize 必须能压到图元尺寸，别让布局最小尺寸顶住
        for host in (self._lamp_host, self._value_host,
                     self._cmd_host, self._write_host):
            host.setMinimumSize(1, 1)
        self.setMinimumSize(1, 1)
        self._relayout(self.width() or 468)

    @staticmethod
    def _block(*, spacing: int = 2) -> tuple[QWidget, QGridLayout]:
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(spacing)
        grid.setVerticalSpacing(2)
        return host, grid

    # -- 响应式 ---------------------------------------------------------
    @staticmethod
    def columns_for(width: int) -> tuple[int, int, int, int]:
        """(灯列, 数值列, 按钮列, 写入列)。

        灯 6 列 / 按钮 6 列与截图一致；数值在 468 宽下按 5 列会把
        "99.47 mm/s" 裁成 ".47 mm/s"，所以收成 3 列（详见 WriteRow）。
        """
        if width >= 430:
            return (6, 3, 6, 3)
        if width >= 320:
            return (4, 2, 4, 2)
        return (3, 2, 3, 1)

    def _relayout(self, width: int) -> None:
        cols = self.columns_for(max(1, int(width)))
        if cols == self._cols:
            return
        self._cols = cols
        for grid, widgets, count in (
                (self._lamp_grid, list(self.lamps.values()), cols[0]),
                (self._value_grid, list(self.cells.values()), cols[1]),
                (self._cmd_grid, list(self.buttons.values()), cols[2]),
                (self._write_grid, list(self.writes.values()), cols[3])):
            for widget in widgets:
                grid.removeWidget(widget)
            for index, widget in enumerate(widgets):
                grid.addWidget(widget, index // count, index % count)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self._relayout(self.width())
        self._place_confirm()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        self._relayout(self.width())
        self._place_confirm()

    def _place_confirm(self) -> None:
        self.confirm.setGeometry(8, 4, max(160, self.width() - 16), 30)

    def _request_confirm(self, key: str, label: str, value: Any) -> None:
        sender = self.sender()
        self._confirm_source = sender if isinstance(sender, CmdButton) else None
        self.confirm.request(label, key, value)

    def _on_confirm_accepted(self, key: str, value: Any) -> None:
        source, self._confirm_source = self._confirm_source, None
        self.commandRequested.emit(key, value)
        if isinstance(source, MomentaryButton):
            # 确认时鼠标已松开，补一个 False 收尾，避免 PLC 一直保持 True。
            self.commandRequested.emit(key, False)

    # -- 数据 -----------------------------------------------------------
    def set_values(self, values: dict) -> int:
        """按点位名更新灯 / 数值 / 写入行当前值；返回实际更新的控件数。"""
        if not values:
            return 0
        updated = 0
        for key, lamp in self.lamps.items():
            if key in values:
                lamp.set_state(values[key])
                updated += 1
        for key, cell in self.cells.items():
            if key in values:
                cell.set_value(values[key])
                updated += 1
        for key, row in self.writes.items():
            if key in values:
                row.set_current(values[key])
                updated += 1
        return updated

    def set_status(self, text: str, level: str = "info") -> None:
        if self._status is None:
            return
        color = {"warn": "#b26b00", "error": "#c0392b",
                 "ok": "#1c7a4b"}.get(level, cfg.PANEL_MUTED)
        self._status.setStyleSheet(f"color: {color};")
        self._status.setText(text)
        self._status.setToolTip(text)

    def state_snapshot(self) -> dict:
        """回归 / 对拍用：把面板当前显示收敛成纯 Python 字典。"""
        return {
            "title": self.title(),
            "lamps": {k: v.state for k, v in self.lamps.items()},
            "values": {k: v.current_text() for k, v in self.cells.items()},
            "writes": {k: v.current_text() for k, v in self.writes.items()},
            "buttons": len(self.buttons),
            "columns": self._cols,
        }


def make_panel_provider(spec: PanelSpec | None = None) -> ServoPanelProvider:
    """便捷入口：``stage.set_mapping({name: make_panel_provider()})``。"""
    return ServoPanelProvider(spec)
