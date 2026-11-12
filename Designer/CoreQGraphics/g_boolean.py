"""基本图元的面域布尔运算。

计算在 QGraphicsScene 的视图坐标里进行，结果再反投影为 page 绝对坐标。
投影是可逆仿射变换，因此并 / 交 / 差 / 异或与在 page 坐标直接计算等价；
统一走视图坐标还能直接复用图元的实时 ``sceneTransform``，未存盘的拖动和
旋转也会参与本次运算。
"""

from __future__ import annotations

import copy

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath

from .g_path import (
    PATH_FILL_RULE_KEY,
    PATH_SEGMENTS_KEY,
    fill_rule_name,
    fill_rule_value,
    map_path,
    path_to_segments,
    path_to_vertices,
)

BOOL_UNION = "union"
BOOL_INTERSECT = "intersect"
BOOL_SUBTRACT = "subtract"
BOOL_XOR = "xor"
BOOLEAN_OPERATIONS = (BOOL_UNION, BOOL_INTERSECT, BOOL_SUBTRACT, BOOL_XOR)
BOOLEAN_TYPES = frozenset(("rect", "circle", "triangle", "polygon", "path"))
BOOLEAN_LABELS = {
    BOOL_UNION: "并集",
    BOOL_INTERSECT: "交集",
    BOOL_SUBTRACT: "差集",
    BOOL_XOR: "异或",
}


def supports_boolean(item) -> bool:
    return getattr(item, "TYPE", "") in BOOLEAN_TYPES


def item_scene_path(item) -> QPainterPath:
    """图元当前实时面域（视图场景坐标），保留圆角、椭圆和贝塞尔曲线。"""
    if not supports_boolean(item):
        return QPainterPath()
    kind = item.TYPE
    local = QPainterPath()
    if kind == "rect":
        rect = QRectF(item._local_rect)
        radius = float(item._style.corner_radius)
        if radius > 0.0:
            rx = min(radius * item._proj.ky, rect.width() / 2.0)
            ry = min(radius * item._proj.kx, rect.height() / 2.0)
            local.addRoundedRect(rect, rx, ry)
        else:
            local.addRect(rect)
    elif kind == "circle":
        local.addEllipse(item._local_rect)
    elif kind in ("triangle", "polygon"):
        points = list(item._points_local)
        if len(points) < 3:
            return QPainterPath()
        local.moveTo(points[0])
        for point in points[1:]:
            local.lineTo(point)
        local.closeSubpath()
    elif kind == "path":
        if item._path_local is None:
            return QPainterPath()
        local = QPainterPath(item._path_local)
    return item.sceneTransform().map(local)


def boolean_path(items, operation: str) -> QPainterPath:
    """按给定顺序折叠计算；差集是「第一个图元依次减去其余图元」。"""
    if operation not in BOOLEAN_OPERATIONS:
        raise ValueError(f"不支持的布尔运算类型: {operation}")
    if len(items) < 2:
        raise ValueError("布尔运算至少需要 2 个闭合基本图元")
    paths = [item_scene_path(item) for item in items]
    if any(path.isEmpty() for path in paths):
        raise ValueError("选区包含没有有效面域的图元")
    result = QPainterPath(paths[0])
    for path in paths[1:]:
        if operation == BOOL_UNION:
            result = result.united(path)
        elif operation == BOOL_INTERSECT:
            result = result.intersected(path)
        elif operation == BOOL_SUBTRACT:
            result = result.subtracted(path)
        else:
            # Qt 没有 xored()：异或 = 并集 - 交集，等价于 (A-B) ∪ (B-A)。
            overlap = result.intersected(path)
            result = result.united(path).subtracted(overlap)
    if result.isEmpty():
        raise ValueError("布尔运算结果为空，源图元未改动")
    return result


def page_path_for_result(result: QPainterPath, projection) -> QPainterPath:
    """把视图场景路径反投影成 page 绝对坐标路径。"""
    def inverse(point: QPointF) -> QPointF:
        return QPointF(*projection.inverse_point(point.x(), point.y()))

    return map_path(result, inverse)


def make_boolean_record(items, operation: str, projection, item_id: int,
                        z_value: float) -> dict:
    """生成可直接交给 ``GraphicsScene._spawn`` 的 path 记录。"""
    result = boolean_path(items, operation)
    page_path = page_path_for_result(result, projection)
    bounds = page_path.boundingRect()
    if bounds.isEmpty():
        raise ValueError("布尔运算结果不是有效面域，源图元未改动")
    cx, cy = bounds.center().x(), bounds.center().y()
    first = items[0]
    return {
        "id": int(item_id),
        "name": f"布尔{BOOLEAN_LABELS[operation]}_{int(item_id)}",
        "type": "path",
        "parent_id": 0,
        "children_ids": [],
        "group_id": 0,
        "center_pos": {"x": round(cx, 3), "y": round(cy, 3)},
        "origin_pos": {"x": round(cx, 3), "y": round(cy, 3)},
        "width": round(bounds.width(), 3),
        "height": round(bounds.height(), 3),
        "rotate": 0.0,
        "style": copy.deepcopy(first.to_page_record().get("style") or {}),
        "zValue": float(z_value),
        # 新引擎读精确曲线；旧 Core 读这份折线，模板仍可与旧工程共用。
        PATH_SEGMENTS_KEY: path_to_segments(page_path),
        PATH_FILL_RULE_KEY: fill_rule_name(page_path.fillRule()),
        "vertices": path_to_vertices(page_path),
    }


def record_page_path(record: dict) -> QPainterPath:
    """读取布尔 / 精确路径记录；供几何回归和模板缩略图复用。"""
    from .g_path import segments_to_path

    return segments_to_path(
        record.get(PATH_SEGMENTS_KEY) or (),
        fill_rule=fill_rule_value(record.get(PATH_FILL_RULE_KEY)),
    )
