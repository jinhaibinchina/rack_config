"""场景热路径的零依赖加速层（Stage 0）。

只做两件**不改变渲染语义**的事：

1. 复用 ``QPen`` / ``QBrush`` / ``QFont``。这些对象原本在图元 ``paint()``
   里每帧每图元新建；Qt 的 ``QPainter::setPen/setBrush/setFont`` 是值拷贝，
   共享只读实例是安全的（调用方拿到后不得修改，本项目所有调用点都直接
   交给 painter，没有二次 setColor/setWidth）。
2. 提供总开关，便于 A/B 对拍和线上回滚：``RACK_SCENE_FAST=0`` 或
   ``scene_fast.set_enabled(False)`` 会退回「每次新建对象」的旧行为。

缓存按 (ARGB, 线宽, 样式) 索引，颜色量有限；超过 _MAX_ENTRIES 直接整表
清空，避免用户自定义色无限增长。全部只在 GUI 线程调用，无需加锁。
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPen

ENABLED = os.environ.get("RACK_SCENE_FAST", "1") != "0"

_MAX_ENTRIES = 512
_PEN_CACHE: dict[tuple, QPen] = {}
_BRUSH_CACHE: dict[int, QBrush] = {}
_DASH_CACHE: dict[int, QPen] = {}
_FONT_CACHE: dict[tuple, QFont] = {}


def set_enabled(enable: bool) -> None:
    """运行时开关，供基准脚本在同一进程里做 A/B 对拍。"""
    global ENABLED
    ENABLED = bool(enable)


def clear_cache() -> None:
    _PEN_CACHE.clear()
    _BRUSH_CACHE.clear()
    _DASH_CACHE.clear()
    _FONT_CACHE.clear()


def _color_key(color) -> int:
    """QColor / Qt.GlobalColor / '#rrggbb' / int -> ARGB 整数。"""
    if isinstance(color, QColor):
        return int(color.rgba())
    if isinstance(color, int):
        return color
    return int(QColor(color).rgba())


def pen_for(color, width: float = 1.0, style=Qt.SolidLine) -> QPen:
    """等价于 ``QPen(color, width, style)``，但同一参数只构造一次。"""
    if not ENABLED:
        return QPen(color, width, style)
    key = (_color_key(color), float(width), style)
    pen = _PEN_CACHE.get(key)
    if pen is None:
        if len(_PEN_CACHE) >= _MAX_ENTRIES:
            _PEN_CACHE.clear()
        pen = QPen(color, width, style)
        _PEN_CACHE[key] = pen
    return pen


def brush_for(color) -> QBrush:
    """等价于 ``QBrush(color)``；也替代 ``setBrush(QColor)`` 的隐式构造。"""
    if not ENABLED:
        return QBrush(color)
    key = _color_key(color)
    brush = _BRUSH_CACHE.get(key)
    if brush is None:
        if len(_BRUSH_CACHE) >= _MAX_ENTRIES:
            _BRUSH_CACHE.clear()
        brush = QBrush(color)
        _BRUSH_CACHE[key] = brush
    return brush


def dashed_pen_for(color) -> QPen:
    """组/多边形选中框用的自定义虚线画笔（原来每次 paint 现场搭一遍）。"""
    if not ENABLED:
        return _new_dashed_pen(color)
    key = _color_key(color)
    pen = _DASH_CACHE.get(key)
    if pen is None:
        if len(_DASH_CACHE) >= _MAX_ENTRIES:
            _DASH_CACHE.clear()
        pen = _new_dashed_pen(color)
        _DASH_CACHE[key] = pen
    return pen


def _new_dashed_pen(color) -> QPen:
    pen = QPen()
    pen.setColor(color)
    pen.setWidth(1)
    pen.setDashPattern([8, 4, 2, 4])
    pen.setStyle(Qt.CustomDashLine)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def font_for(family: str, size: float, bold: bool = False) -> QFont:
    """等价于 ``QFont(family, size)`` + ``setBold(bold)``。"""
    if not ENABLED:
        font = QFont(family, size)
        font.setBold(bold)
        return font
    key = (family, float(size), bool(bold))
    font = _FONT_CACHE.get(key)
    if font is None:
        if len(_FONT_CACHE) >= _MAX_ENTRIES:
            _FONT_CACHE.clear()
        font = QFont(family, size)
        font.setBold(bold)
        _FONT_CACHE[key] = font
    return font
