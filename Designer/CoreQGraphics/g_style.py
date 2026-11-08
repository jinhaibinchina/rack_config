"""样式解析与 QPen / QBrush / QFont 复用缓存。

对齐 ``Designer/Core/element.py`` 的 ``str_to_color`` / ``set_opacity`` 语义，
以及 ``Designer/Core/scene_fast.py`` 的按 (ARGB, 线宽, 样式) 复用策略。
``painter.setPen/setBrush`` 是值拷贝，共享只读实例安全。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPen

# 文本图元：边框 / 背景在文字度量之外预留的视图像素
TEXT_PAD_X = 8.0
TEXT_PAD_Y = 4.0

_CACHE_LIMIT = 512
_pen_cache: dict[tuple, QPen] = {}
_brush_cache: dict[int, QBrush] = {}
_dash_cache: dict[int, QPen] = {}
_font_cache: dict[tuple, QFont] = {}

HOVER_COLOR = QColor(14, 248, 236)
SELECT_COLOR = QColor(255, 0, 0)


def parse_color(value, default: str = "#000000") -> QColor:
    """支持 ``#rrggbb`` / ``#aarrggbb`` / ``r,g,b[,a]`` / 颜色名。"""
    if isinstance(value, QColor):
        return QColor(value)
    if not isinstance(value, str) or not value.strip():
        return QColor(default)
    text = value.strip()
    if text.startswith("#"):
        c = QColor(text)
        return c if c.isValid() else QColor(default)
    parts = [p.strip() for p in text.split(",")]
    if len(parts) in (3, 4) and all(p.lstrip("-").isdigit() for p in parts):
        nums = [int(p) for p in parts]
        c = QColor(*nums) if len(nums) == 4 else QColor(nums[0], nums[1], nums[2])
        return c if c.isValid() else QColor(default)
    c = QColor(text)
    return c if c.isValid() else QColor(default)


def color_str(c: QColor) -> str:
    """``QColor.name()`` 的 ``#rrggbb``，与 Core 的 ``color_to_str`` 一致。"""
    return c.name(QColor.HexRgb)


def _guard(cache: dict) -> None:
    if len(cache) > _CACHE_LIMIT:
        cache.clear()


def pen_for(color: QColor, width: float = 1.0, style=Qt.SolidLine) -> QPen:
    # PySide6 6.10 的 Qt.SolidLine 是 PenStyle 枚举，int(enum) 会抛
    # TypeError；而该异常若发生在 QGraphicsScene.render 的 C++ 绘制回调里，
    # 不会被传播，直接变成 access violation。枚举本身可哈希，直接用。
    key = (color.rgba(), float(width), style)
    pen = _pen_cache.get(key)
    if pen is None:
        pen = QPen(QColor(color), float(width), style)
        _guard(_pen_cache)
        _pen_cache[key] = pen
    return pen


def brush_for(color: QColor) -> QBrush:
    key = color.rgba()
    brush = _brush_cache.get(key)
    if brush is None:
        brush = QBrush(QColor(color))
        _guard(_brush_cache)
        _brush_cache[key] = brush
    return brush


def dashed_pen_for(color: QColor) -> QPen:
    """Core 的 ``create_pen_style``：宽 1、[8,4,2,4]、圆角端点。"""
    key = color.rgba()
    pen = _dash_cache.get(key)
    if pen is None:
        pen = QPen()
        pen.setColor(QColor(color))
        pen.setWidth(1)
        pen.setDashPattern([8, 4, 2, 4])
        pen.setStyle(Qt.CustomDashLine)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        _guard(_dash_cache)
        _dash_cache[key] = pen
    return pen


def font_for(family: str, size: float, bold: bool = False) -> QFont:
    key = (family, float(size), bool(bold))
    font = _font_cache.get(key)
    if font is None:
        font = QFont(family, int(size))
        font.setBold(bold)
        _guard(_font_cache)
        _font_cache[key] = font
    return font


def text_metrics(text: str, font_size: float) -> tuple[float, float]:
    """量出文字在**视图像素**下的 (宽, 高)，供边框背景自适应使用。

    必须与 ``TextItem.paint`` 用同一份 ``font_for`` 字体，否则字号改完边框会
    和文字差一两像素。多行文本按行累加行高、取最宽的一行；空串按一个空格量，
    避免得到 0 尺寸导致 ``set_page_size`` 直接拒绝。
    ``QFontMetricsF`` 与 QPainter 共享 QGuiApplication 的逻辑 DPI，离屏回归和
    真实窗口口径一致。
    """
    fm = QFontMetricsF(font_for("Arial", font_size, True))
    lines = str(text if text else " ").split("\n")
    width = max((fm.horizontalAdvance(line) for line in lines), default=0.0)
    # QPainter.drawText 多行的行距是 lineSpacing，只有最后一行用 height：
    # 实测 40pt 三行是 61*2 + 53 = 175，直接 height*n 会少 16px 把字裁掉。
    height = fm.height() + fm.lineSpacing() * (len(lines) - 1)
    return max(float(width), 1.0), max(float(height), 1.0)


@dataclass
class Style:
    """一条 item 的 ``style`` 字段解析结果。"""

    stroke: QColor
    stroke_width: float
    fill: bool
    fill_color: QColor
    opacity: int
    corner_radius: float
    font_size: float

    @classmethod
    def from_dict(cls, data: dict | None) -> "Style":
        d = data or {}
        opacity = int(d.get("opacity", 255))
        stroke = parse_color(d.get("stroke", "#000000"))
        fill_color = parse_color(d.get("fill_color", "#ffffff"))
        # Core 的 set_opacity 把 alpha 写进两个颜色，而不是 painter.setOpacity()
        if 0 < opacity <= 255:
            stroke.setAlpha(opacity)
            fill_color.setAlpha(opacity)
        return cls(
            stroke=stroke,
            stroke_width=float(d.get("strokeWidth", 2)),
            fill=bool(d.get("fill", False)),
            fill_color=fill_color,
            opacity=opacity,
            corner_radius=max(0.0, float(d.get("cornerRadius", 0.0) or 0.0)),
            font_size=float(d.get("font_size", 10)),
        )

    def pen(self, color: QColor | None = None, width: float | None = None) -> QPen:
        if width is None:
            # strokeWidth == 0 时 Core 用填充色作笔色、宽 0
            w = self.stroke_width
            c = (color or self.stroke) if w > 0 else self.fill_color
        else:
            w, c = width, (color or self.stroke)
        return pen_for(c, w)

    def brush(self):
        return brush_for(self.fill_color) if self.fill else QBrush(Qt.NoBrush)
