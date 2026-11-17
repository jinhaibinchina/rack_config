"""QPainterPath 的可序列化表示与坐标映射。

``vertices`` 是旧 Core 已认识的折线格式；``path_segments`` 是本模块新增的
精确表示，保留三次贝塞尔曲线。布尔结果同时写两份：旧设计器读取折线兜底，
CoreQGraphics 读取精确段，复制、模板、换页与再次布尔都不丢曲线。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath

PATH_SEGMENTS_KEY = "path_segments"
PATH_FILL_RULE_KEY = "path_fill_rule"


def map_path(path: QPainterPath, point_map) -> QPainterPath:
    """逐元素映射路径，曲线控制点与端点走同一个映射。"""
    out = QPainterPath()
    out.setFillRule(path.fillRule())
    index = 0
    while index < path.elementCount():
        element = path.elementAt(index)
        point = point_map(QPointF(element.x, element.y))
        if element.isMoveTo():
            out.moveTo(point)
            index += 1
        elif element.isLineTo():
            out.lineTo(point)
            index += 1
        elif element.isCurveTo() and index + 2 < path.elementCount():
            second = path.elementAt(index + 1)
            third = path.elementAt(index + 2)
            out.cubicTo(
                point,
                point_map(QPointF(second.x, second.y)),
                point_map(QPointF(third.x, third.y)),
            )
            index += 3
        else:
            # 非法 / 手工拼出的 CurveToData 不静默丢点，退成线段保留轮廓。
            out.lineTo(point)
            index += 1
    return out


def path_to_segments(path: QPainterPath, point_map=None, digits: int = 3) -> list[dict]:
    """导出 move / line / curve 段；坐标默认按 page JSON 口径保留 3 位。"""
    if point_map is None:
        point_map = lambda point: point

    def number(value: float) -> float:
        value = round(float(value), digits)
        return 0.0 if abs(value) < 0.5 * 10 ** (-digits) else value

    def put(target: dict, prefix: str, point: QPointF) -> None:
        target[f"{prefix}x"] = number(point.x())
        target[f"{prefix}y"] = number(point.y())

    segments: list[dict] = []
    index = 0
    while index < path.elementCount():
        element = path.elementAt(index)
        point = point_map(QPointF(element.x, element.y))
        if element.isMoveTo():
            segment = {"kind": "move"}
            put(segment, "", point)
            segments.append(segment)
            index += 1
        elif element.isLineTo():
            segment = {"kind": "line"}
            put(segment, "", point)
            segments.append(segment)
            index += 1
        elif element.isCurveTo() and index + 2 < path.elementCount():
            second = path.elementAt(index + 1)
            third = path.elementAt(index + 2)
            segment = {"kind": "curve"}
            put(segment, "c1", point)
            put(segment, "c2", point_map(QPointF(second.x, second.y)))
            put(segment, "", point_map(QPointF(third.x, third.y)))
            segments.append(segment)
            index += 3
        else:
            segment = {"kind": "line"}
            put(segment, "", point)
            segments.append(segment)
            index += 1
    return segments


def segments_to_path(segments, point_map=None, fill_rule=Qt.OddEvenFill) -> QPainterPath:
    """从 ``path_segments`` 重建路径；无效段由调用方按数据异常处理。"""
    if point_map is None:
        point_map = lambda point: point
    out = QPainterPath()
    out.setFillRule(fill_rule)
    for segment in segments or ():
        kind = segment.get("kind")
        point = point_map(QPointF(float(segment["x"]), float(segment["y"])))
        if kind == "move":
            out.moveTo(point)
        elif kind == "line":
            out.lineTo(point)
        elif kind == "curve":
            c1 = point_map(QPointF(float(segment["c1x"]), float(segment["c1y"])))
            c2 = point_map(QPointF(float(segment["c2x"]), float(segment["c2y"])))
            out.cubicTo(c1, c2, point)
    return out


def path_to_vertices(path: QPainterPath, digits: int = 3) -> list[dict]:
    """旧 Core 兼容的折线兜底；每个子路径首点带 ``move``，孔洞不丢。"""
    vertices: list[dict] = []
    for polygon in path.toSubpathPolygons():
        points = list(polygon)
        if len(points) > 1 and _same_point(points[0], points[-1]):
            points.pop()
        for index, point in enumerate(points):
            item = {
                "x": _round_zero(point.x(), digits),
                "y": _round_zero(point.y(), digits),
            }
            if index == 0:
                item["move"] = True
            vertices.append(item)
    return vertices


def transform_segments(segments, point_map, digits: int = 6) -> list[dict]:
    """平移 / 旋转 / 缩放记录里的全部几何点，保留段类型。"""
    out: list[dict] = []
    for source in segments or ():
        segment = dict(source)
        for prefix in ("c1", "c2", ""):
            x_key, y_key = f"{prefix}x", f"{prefix}y"
            if x_key not in segment or y_key not in segment:
                continue
            point = point_map(QPointF(float(segment[x_key]), float(segment[y_key])))
            segment[x_key] = _round_zero(point.x(), digits)
            segment[y_key] = _round_zero(point.y(), digits)
        out.append(segment)
    return out


def shift_segments(segments, dx: float, dy: float, digits: int = 3) -> None:
    """原地平移精确段，供复制和模板捕获共用。"""
    for segment in segments or ():
        for prefix in ("c1", "c2", ""):
            x_key, y_key = f"{prefix}x", f"{prefix}y"
            if x_key in segment and y_key in segment:
                segment[x_key] = _round_zero(float(segment[x_key]) + dx, digits)
                segment[y_key] = _round_zero(float(segment[y_key]) + dy, digits)


def fill_rule_name(rule) -> str:
    return "winding" if rule == Qt.WindingFill else "odd_even"


def fill_rule_value(name) -> Qt.FillRule:
    return Qt.WindingFill if name == "winding" else Qt.OddEvenFill


def _round_zero(value: float, digits: int) -> float:
    value = round(float(value), digits)
    return 0.0 if math.isclose(value, 0.0, abs_tol=0.5 * 10 ** (-digits)) else value


def _same_point(a: QPointF, b: QPointF) -> bool:
    return abs(a.x() - b.x()) < 1e-9 and abs(a.y() - b.y()) < 1e-9
