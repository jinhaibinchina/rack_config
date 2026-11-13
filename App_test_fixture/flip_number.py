# -*- coding: utf-8 -*-
"""翻页动画式「多位整数」显示器。

参考 ``flip_clock.py`` 的上下半页翻转手法，但**不改动原文件**：
``App_RackConfig/plc_window.py`` 现场在用 ``FlipDigit_Time_display`` 显示
PLC 时间，那份实现还有三处不适合直接拿来做计数器：

* 把 ``self.width`` / ``self.height`` 当整数属性，覆盖了 ``QWidget.width()``；
* 动画由 top→bottom 两段 ``QPropertyAnimation`` 串联，只能 ``+1`` 循环，
  ``FlipDigit`` 本身没有 ``set_value``，无法跳到任意数字；
* ``max_value`` / 6 位布局 / 冒号分隔都绑死在 ``HH:MM:SS`` 上。

本模块提供两个类：

===========================  ============================================
``FlipDigitWidget``           单个数字位，一条动画完成「收上半→展下半」
``FlipNumberDisplay``         N 位整数容器，``set_value(12345)`` 逐位比对，
                              只有变化的位翻页
===========================  ============================================

.. code-block:: python

    from App_test_fixture.flip_number import FlipNumberDisplay

    display = FlipNumberDisplay(digits=6)       # 000000
    display.set_value(12345)                   # 翻成 012345，只有变化的位动
    display.set_value(12345)                   # 无变化，不触发动画
    display.set_value(-7, animate=False)        # 立即落值，不播动画

    # 运行态 widget 图元里挂它（不改框架代码）：
    #   provider = FlipNumberProvider(digits=6)
    #   stage.set_mapping({"计数翻牌": provider})
    #   stage.load()
    #   provider.set_value(12345)          # 数据源推值时转发，逐位翻页

可选口径：``leading_zeros``（高位补零 / 熄灭）、``signed``（负号）、
``size_factor`` / ``digit_size``（尺寸）、``duration_ms``（动画时长）、
``bg`` / ``fg``（配色）。所有动画只改 Qt 属性，不写任何设计数据。

挂运行态 widget 图元时，``FlipNumberProvider`` 默认按**图元的设计态包围盒**
反推卡片尺寸（``fit_to_size``），保证运行态与设计态占位框一致；传
``FlipNumberProvider(..., fit_to_element=False)`` 可退回 ``size_factor`` 口径。

.. code-block:: bash

    .venv/Scripts/python.exe -m App_test_fixture.flip_number          # demo 窗口
    .venv/Scripts/python.exe -m App_test_fixture.flip_number --seconds 1
"""
from __future__ import annotations

import math
import sys
from typing import Any

from PySide6.QtCore import (
    Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout,
    QWidget, QApplication,
)

from DesignerV2.CoreQGraphics.runtime import ControlProvider

# 一位的默认尺寸（宽 × 高）。6 位 ≈ 6*64 + 5*4 = 404px，可塞进 468 宽的图元。
BASE_DIGIT_W = 64
BASE_DIGIT_H = 92
BASE_GAP = 4
DEFAULT_BG = "#20293a"
DEFAULT_FG = "#f4f7ff"


def _color(value: Any) -> QColor:
    return value if isinstance(value, QColor) else QColor(str(value))


class FlipDigitWidget(QWidget):
    """一位 0~9 的翻页数字。

    一条 ``QPropertyAnimation(flipProgress, 0→100)`` 覆盖整个过程：
    前 50% 把「旧值上半」按 ``cos`` 压扁到中线，后 50% 把「新值下半」
    按 ``sin`` 从中线展开。静态时上下都显示当前值。
    """

    flipStarted = Signal(int)
    flipFinished = Signal(int)

    def __init__(self, *, digit_size: tuple[int, int] | None = None,
                 bg: Any = DEFAULT_BG, fg: Any = DEFAULT_FG,
                 duration_ms: int = 320, radius: float = 6.0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._w, self._h = digit_size or (BASE_DIGIT_W, BASE_DIGIT_H)
        self._bg = _color(bg)
        self._fg = _color(fg)
        self._duration_ms = max(1, int(duration_ms))
        self._radius = float(radius)

        self._value = 0
        self._next = 0
        self._progress = 0.0            # 0..1
        self._blank = False             # 高位熄灭：只画卡片不画数字
        self._pending: int | None = None
        self._anim: QPropertyAnimation | None = None
        self._cache: dict[tuple[int, str, bool], QPixmap] = {}
        self._font: QFont | None = None

        self.setFixedSize(self._w, self._h)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    # -- Qt 动画属性（int 0..100，避免 double 属性在 PySide6 的插值坑） ----
    def _get_progress(self) -> int:
        return int(round(self._progress * 100))

    def _set_progress(self, value: int) -> None:
        self._progress = max(0.0, min(1.0, float(value) / 100.0))
        self.update()

    flipProgress = Property(int, _get_progress, _set_progress)

    # -- 对外 API ---------------------------------------------------------
    def value(self) -> int:
        return self._value

    def is_animating(self) -> bool:
        return self._anim is not None

    def set_blank(self, blank: bool) -> None:
        blank = bool(blank)
        if blank == self._blank:
            return
        self._blank = blank
        self._cache.clear()
        self.update()

    def set_duration(self, ms: int) -> None:
        self._duration_ms = max(1, int(ms))

    def set_colors(self, bg: Any = None, fg: Any = None) -> None:
        if bg is not None:
            self._bg = _color(bg)
        if fg is not None:
            self._fg = _color(fg)
        self._cache.clear()
        self.update()

    def set_value(self, value: int, *, animate: bool = True) -> None:
        """翻到 ``value``（0..9）。动画中再来新值会排队，不丢最终值。"""
        target = int(value)
        if not 0 <= target <= 9:
            raise ValueError(f"单个数字位只能是 0..9，得到 {target}")
        if self._anim is not None:
            if target != self._next:
                self._pending = target
            return
        if target == self._value:
            self._next = target
            self._pending = None
            return
        # 不碰 _blank：熄灭位由 FlipNumberDisplay._apply 显式管理，
        # 这里若强行置 False，高位归零时会把「熄灭」状态冲掉。
        self._cache.clear()
        if not animate:
            self._value = self._next = target
            self._progress = 0.0
            self.update()
            return
        self._next = target
        self._start_animation()

    def _start_animation(self) -> None:
        self._progress = 0.0
        anim = QPropertyAnimation(self, b"flipProgress")
        anim.setDuration(self._duration_ms)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.setStartValue(0)
        anim.setEndValue(100)
        anim.finished.connect(self._on_finished)
        self._anim = anim
        self.flipStarted.emit(self._next)
        anim.start()

    def _on_finished(self) -> None:
        self._value = self._next
        self._progress = 0.0
        self._anim = None
        self.update()
        self.flipFinished.emit(self._value)
        pending = self._pending
        self._pending = None
        if pending is not None and pending != self._value:
            self._next = pending
            self._start_animation()

    # -- 绘制 -------------------------------------------------------------
    def _fit_font(self) -> QFont:
        """按卡片高度找最大字号；字型对齐 ``flip_clock.py`` 的 Arial Bold。

        曾经用 Consolas 等等宽族，结果翻牌数字和现场原有的翻页钟外观不一致。
        Arial 的数字本身是 tabular（0~9 等宽，见 verify_flip_number 断言），
        换数字不会左右跳动，没有必要再上等宽族。

        整个 font 对象要缓存：只缓存 pixelSize 再拿 ``painter.font()`` 重建，
        会退回 QWidget 默认字体族，Arial 就没了。
        """
        if self._font is not None:
            return QFont(self._font)
        font = QFont("Arial")
        font.setBold(True)
        target = self._h * 0.86
        lo, hi = 4, min(400, self._h * 2)
        best = lo
        while lo <= hi:
            mid = (lo + hi) // 2
            font.setPixelSize(mid)
            fm = QFontMetrics(font)
            if (fm.ascent() - fm.descent() <= target
                    and fm.horizontalAdvance("0") <= self._w * 0.92):
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        font.setPixelSize(best)
        self._font = QFont(font)
        return font

    def _half_pixmap(self, digit: int, half: str, blank: bool) -> QPixmap:
        """渲染「完整数字」被裁到上半 / 下半后的纸片。

        用离屏 pixmap 而不是 painter 变换 + clip：Qt 的 clip 会跟着后续
        ``scale`` 一起变形，压缩翻页片时很容易把裁切区域也压掉。
        """
        key = (digit, half, blank)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        mid = self._h // 2
        top = half == "top"
        y0 = 0 if top else mid
        hh = mid if top else self._h - mid
        pm = QPixmap(self._w, hh)
        pm.fill(Qt.GlobalColor.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 卡片渐变：上半亮 → 中线暗；下半中线暗 → 底部略亮
        grad = QLinearGradient(0, 0, 0, self._h)
        grad.setColorAt(0.0, self._bg.lighter(122))
        grad.setColorAt(0.5, self._bg.darker(118))
        grad.setColorAt(1.0, self._bg.lighter(108))
        p.fillRect(QRectF(0, 0, self._w, hh), grad)
        if not blank:
            p.translate(0, -y0)            # 回到「完整卡片」坐标系
            p.setFont(self._fit_font())
            p.setPen(self._fg)
            fm = p.fontMetrics()
            text = str(digit)
            x = (self._w - fm.horizontalAdvance(text)) / 2.0
            y = (self._h + fm.ascent() - fm.descent()) / 2.0
            p.drawText(QPointF(x, y), text)
        p.end()
        self._cache[key] = pm
        return pm

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        mid = h // 2
        bottom_h = h - mid
        blank = self._blank

        # 静态：上半 = 新值，下半 = 旧值；非动画时两者相同。
        painter.drawPixmap(QRectF(0, 0, w, mid),
                           self._half_pixmap(self._next, "top", blank),
                           QRectF(0, 0, w, mid))
        painter.drawPixmap(QRectF(0, mid, w, bottom_h),
                           self._half_pixmap(self._value, "bottom", blank),
                           QRectF(0, 0, w, bottom_h))

        if self._anim is not None:
            p = self._progress
            if p <= 0.5:
                # 旧值上半向下翻：从中线为轴压扁到 0。
                s = math.cos(math.pi * p)
                if s > 0.001:
                    dst = QRectF(0, mid - s * mid, w, s * mid)
                    painter.drawPixmap(
                        dst, self._half_pixmap(self._value, "top", blank),
                        QRectF(0, 0, w, mid))
            else:
                # 新值下半从中线向下展开。
                s = math.sin(math.pi * (p - 0.5))
                if s > 0.001:
                    dst = QRectF(0, mid, w, s * bottom_h)
                    painter.drawPixmap(
                        dst, self._half_pixmap(self._next, "bottom", blank),
                        QRectF(0, 0, w, bottom_h))

        # 中线缝 + 圆角描边
        painter.setPen(QPen(QColor(0, 0, 0, 150), 1.2))
        painter.drawLine(QPointF(0, mid), QPointF(w, mid))
        painter.setPen(QPen(self._bg.darker(160), 1.0))
        painter.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1),
                                self._radius, self._radius)
        painter.end()


class FlipNumberDisplay(QWidget):
    """N 位整数翻页显示器。

    ``set_value`` 把整数格式化成固定位数后逐位比对，**只有变化的位**才播
    翻页动画（例如 012345 → 012346 只动最后一位）。超出位数会夹到最大值，
    非法输入保持原显示不变。
    """

    valueChanged = Signal(int)
    flipFinished = Signal(int)

    def __init__(self, digits: int = 6, *, size_factor: float = 1.0,
                 digit_size: tuple[int, int] | None = None,
                 gap: int = BASE_GAP, leading_zeros: bool = True,
                 signed: bool = False, duration_ms: int = 920,
                 bg: Any = DEFAULT_BG, fg: Any = DEFAULT_FG,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        factor = size_factor if 0.05 <= size_factor <= 8.0 else 1.0
        self._digit_size = (digit_size or
                            (max(16, int(BASE_DIGIT_W * factor)),
                             max(24, int(BASE_DIGIT_H * factor))))
        self._gap = max(0, int(gap))
        self._leading_zeros = bool(leading_zeros)
        self._signed = bool(signed)
        self._duration_ms = int(duration_ms)
        self._bg, self._fg = _color(bg), _color(fg)
        self._value = 0
        self._digits: list[FlipDigitWidget] = []

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(self._gap)
        self._layout.addStretch(1)

        self._sign: QLabel | None = None
        if self._signed:
            self._sign = QLabel(" ")
            self._sign.setAlignment(Qt.AlignmentFlag.AlignCenter)
            font = QFont("Arial")            # 与翻牌数字保持同一字型
            font.setBold(True)
            font.setPixelSize(max(10, self._digit_size[1] // 2))
            self._sign.setFont(font)
            self._sign.setStyleSheet(f"color: {self._fg.name()}; background: transparent;")
            self._sign.setFixedWidth(max(10, self._digit_size[0] // 2))
            self._layout.insertWidget(0, self._sign)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_digits(digits)

    # -- 组装 -------------------------------------------------------------
    def digit_count(self) -> int:
        return len(self._digits)

    def set_digits(self, count: int) -> None:
        """重建位数；保留当前值（超范围会被夹住）。"""
        count = max(1, min(32, int(count)))
        for d in self._digits:
            self._layout.removeWidget(d)
            d.setParent(None)
            d.deleteLater()
        self._digits = []
        insert_at = 1 if self._sign is not None else 0
        for i in range(count):
            d = FlipDigitWidget(digit_size=self._digit_size,
                                bg=self._bg, fg=self._fg,
                                duration_ms=self._duration_ms)
            d.flipFinished.connect(self._on_digit_finished)
            self._layout.insertWidget(insert_at + i, d)
            self._digits.append(d)
        self._apply(self._value, animate=False)
        self._refresh_size()

    def _refresh_size(self) -> None:
        w, h = self._digit_size
        total_w = len(self._digits) * w + max(0, len(self._digits) - 1) * self._gap
        if self._sign is not None:
            total_w += self._sign.width()
        self.setFixedSize(total_w, h)

    def fit_to_size(self, width: float, height: float) -> tuple[int, int]:
        """按 widget 图元的设计态尺寸重排卡片，让数字铺满占位框。

        ``WidgetHost._ensure()`` 把控件塞进 ``QGraphicsProxyWidget``，随后
        ``align()`` 调 ``proxy.resize(图元宽, 图元高)``。本控件是
        ``QSizePolicy.Fixed`` + ``setFixedSize``，proxy 会把 fixed size 当成
        maximumSize：只要它比图元框小，``resize`` 就被**直接拒绝**，运行态
        表现为「左上角对齐、右下角往里缩一圈」。位数改过或 size_factor 调过
        都会踩这个坑。所以卡片尺寸必须由**图元框反推**，不能由控件自己定。

        余量摊进卡片间距，避免右侧留一条明显空白；最后把 fixed size 钉成
        图元框尺寸，proxy 初始 geometry 就与 align 的目标一致。

        返回实际采用的 ``(digit_w, digit_h)``；尺寸非法时原样不动。
        """
        try:
            w, h = float(width), float(height)
        except (TypeError, ValueError):
            return self._digit_size
        if not (math.isfinite(w) and math.isfinite(h)) or w < 16 or h < 16:
            return self._digit_size

        n = max(1, len(self._digits))
        target_w = max(n * 8, int(round(w)))
        target_h = max(24, int(round(h)))
        sign_w = (self._sign.minimumWidth() if self._sign is not None else 0)
        avail = max(n * 8, target_w - sign_w)

        gap = max(0, self._gap)
        dw = max(8, (avail - (n - 1) * gap) // n)
        if n > 1:
            gap += max(0, (avail - (n * dw + (n - 1) * gap)) // (n - 1))

        self._digit_size = (dw, target_h)
        self._gap = gap
        self._layout.setSpacing(gap)
        if self._sign is not None:
            sign_font = QFont(self._sign.font())
            sign_font.setPixelSize(max(10, target_h // 2))
            self._sign.setFont(sign_font)
        self.set_digits(n)                       # 内部 _refresh_size → setFixedSize
        self.setFixedSize(target_w, target_h)   # 覆盖成图元框，resize 才不被拒
        return self._digit_size

    # -- 对外 API ---------------------------------------------------------
    def value(self) -> int:
        return self._value

    def is_animating(self) -> bool:
        return any(d.is_animating() for d in self._digits)

    def set_duration(self, ms: int) -> None:
        self._duration_ms = max(1, int(ms))
        for d in self._digits:
            d.set_duration(self._duration_ms)

    def set_colors(self, bg: Any = None, fg: Any = None) -> None:
        if bg is not None:
            self._bg = _color(bg)
        if fg is not None:
            self._fg = _color(fg)
        for d in self._digits:
            d.set_colors(self._bg, self._fg)
        if self._sign is not None:
            self._sign.setStyleSheet(f"color: {self._fg.name()}; background: transparent;")

    def set_value(self, value: Any, *, animate: bool = True) -> bool:
        """设置整数；成功返回 True，非法输入返回 False 且显示不变。"""
        try:
            if isinstance(value, bool):
                number = int(value)
            elif isinstance(value, (bytes, bytearray)):
                number = int(value.decode("ascii", "ignore").strip() or "0")
            else:
                number = int(float(value))
        except (TypeError, ValueError, OverflowError):
            return False
        if not self._signed and number < 0:
            number = 0
        limit = 10 ** len(self._digits) - 1
        number = max(-limit, min(limit, number))
        changed = number != self._value
        self._apply(number, animate=animate)
        self._value = number
        if changed:
            self.valueChanged.emit(number)
        return True

    def _apply(self, number: int, *, animate: bool) -> None:
        limit = 10 ** len(self._digits) - 1
        magnitude = min(abs(int(number)), limit)
        text = str(magnitude).zfill(len(self._digits))
        if not self._leading_zeros:
            first = len(self._digits) - len(str(magnitude))
            first = min(first, len(self._digits) - 1)   # 0 至少留最后一位
        else:
            first = 0
        for i, d in enumerate(self._digits):
            if i < first:
                d.set_blank(True)
                d.set_value(0, animate=False)
            else:
                d.set_blank(False)
                d.set_value(int(text[i]), animate=animate)
        if self._sign is not None:
            self._sign.setText("-" if number < 0 else " ")

    def _on_digit_finished(self, _digit: int) -> None:
        # 所有位的动画都结束后才发一次，供自动化 / 截图等待。
        if not self.is_animating():
            self.flipFinished.emit(self._value)

    def digits(self) -> tuple[FlipDigitWidget, ...]:
        return tuple(self._digits)


def _element_frame_size(element) -> tuple[float, float] | None:
    """从运行态门面安全取设计态图元宽高；取不到返回 ``None``。

    独立使用 / 单元测试里的 element 可能是简化桩对象，没有 ``item()``，
    这时必须静默退回 ``size_factor`` 口径，不能让控件创建失败。
    """
    get_item = getattr(element, "item", None)
    if not callable(get_item):
        return None
    try:
        item = get_item()
        rect = item.boundingRect() if item is not None else None
        return None if rect is None else (float(rect.width()),
                                         float(rect.height()))
    except (RuntimeError, AttributeError, TypeError, ValueError):
        return None


class FlipNumberProvider(ControlProvider):
    """把 :class:`FlipNumberDisplay` 挂进统一运行态的 widget 图元。

    必须继承 ``ControlProvider``：``MappingProvider._provider`` 用
    ``isinstance`` 判定，否则会被当成 callable 工厂调用而报 TypeError。
        这里额外提供 ``set_value`` 转发：数据源推值后直接调 provider，
        不用去场景里捞控件。换页重建控件时 ``destroyed`` 自动清引用，
        不会留悬空指针。

        ``create`` 收到 ``element`` 时按图元包围盒 ``fit_to_size()``，
        让运行态占位框和设计态一致；这是控件侧适配，不改 ``WidgetHost``。
        ``signature`` 仍固定：图元几何变化由 ``align()`` 负责，重新
        ``load()`` 换页时会重新 ``create`` 并按新尺寸重排，不必因浮点
        抖动反复重建控件。

    .. code-block:: python

        provider = FlipNumberProvider(digits=6, size_factor=1.2)
        stage.set_mapping({"计数翻牌": provider})   # 必须在 load() 之前
        stage.load()
        provider.set_value(12345)
    """

    def __init__(self, **kwargs) -> None:
        self._kwargs = dict(kwargs)
        # fit_to_element 是 provider 自己的开关，不能透传给 FlipNumberDisplay。
        self._fit = bool(self._kwargs.pop("fit_to_element", True))
        self._digits = int(self._kwargs.get("digits", 6))
        self._factor = float(self._kwargs.get("size_factor", 1.2))
        self._signed = bool(self._kwargs.get("signed", False))
        self.display: FlipNumberDisplay | None = None
        self._latest: Any = 0

    def signature(self, element) -> tuple:
        # 固定标量，别把 QColor / dict 塞进来；signature 决定控件是否重建。
        return ("flip_number", self._digits, self._factor, self._signed)

    def create(self, element, host: QWidget | None = None) -> QWidget:
        widget = FlipNumberDisplay(**self._kwargs)
        if self._fit:
            frame = _element_frame_size(element)
            if frame is not None:
                widget.fit_to_size(*frame)
        widget.set_value(self._latest, animate=False)
        widget.destroyed.connect(self._on_destroyed)
        self.display = widget
        return widget

    def _on_destroyed(self, *_args) -> None:
        self.display = None

    def set_value(self, value: Any, *, animate: bool = True) -> bool:
        self._latest = value
        if self.display is None:
            return False
        return self.display.set_value(value, animate=animate)


# ---------------------------------------------------------------- demo
def _demo(seconds: float = 0.0) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("翻页多位整数 · demo")
    root = QVBoxLayout(window)
    root.setSpacing(12)

    display = FlipNumberDisplay(digits=6, signed=True, size_factor=1.6)
    display.set_value(12345, animate=False)
    root.addWidget(display, 0, Qt.AlignmentFlag.AlignCenter)

    controls = QHBoxLayout()
    spin = QSpinBox()
    spin.setRange(-999999, 999999)
    spin.setValue(12345)
    controls.addWidget(spin)
    apply_btn = QPushButton("设置")
    apply_btn.clicked.connect(lambda: display.set_value(spin.value()))
    controls.addWidget(apply_btn)
    root.addLayout(controls)

    timer = QTimer(window)
    timer.timeout.connect(lambda: (spin.setValue((spin.value() + 1) % 1000000),
                                   display.set_value(spin.value())))
    auto = QPushButton("自动 +1：关")
    auto.setCheckable(True)
    auto.toggled.connect(lambda on: (timer.start(900) if on else timer.stop(),
                                     auto.setText(f"自动 +1：{'开' if on else '关'}")))
    root.addWidget(auto)

    window.resize(760, 260)
    window.show()
    if seconds > 0:                      # 离屏自测 / 截图用
        QTimer.singleShot(int(seconds * 1000), app.quit)
    return app.exec()


if __name__ == "__main__":
    argv = sys.argv[1:]
    secs = 0.0
    if "--seconds" in argv:
        try:
            secs = float(argv[argv.index("--seconds") + 1])
        except (IndexError, ValueError):
            secs = 0.0
    raise SystemExit(_demo(secs))
