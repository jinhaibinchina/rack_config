from __future__ import annotations

import math
import sys
from collections import defaultdict
from typing import Any, Callable, Iterable, TypedDict

from PySide6.QtCore import Qt, QPointF,QPoint, QRectF,Signal,QTimer,QObject
from PySide6.QtGui import QCursor,QPainter,QPen, QColor

# 吸附点统一用 (x, y) 浮点元组表示（可哈希，直接进 set）
SnapPointTuple = tuple[float, float]
# 参与交点计算的几何元素描述，例如 {"type": "line", "start": (x, y), "end": (x, y)}
GeometricElement = dict[str, Any]


class SnapInfo(TypedDict, total=False):
    """get_snap_info() 的返回结构；交点类型会额外带 elements 字段。"""

    point: SnapPointTuple
    type: str
    distance: float
    elements: list[GeometricElement]


# 吸附调试输出开关，与场景的 DEBUG_SCENE 保持同样的用法。
DEBUG_SNAP = False


def debug_log(*args: object, **kwargs: object) -> None:
    if DEBUG_SNAP:
        print(*args, **kwargs)


# On macOS, ``QCursor.setPos()`` is silently ignored in some PySide6/Cocoa
# setups (the call returns normally, but the cursor never moves).  Warping the
# cursor through CoreGraphics works reliably, so use it when available and
# keep ``QCursor.setPos()`` as the cross-platform fallback.
_CG_WARP_CURSOR = None
_CG_POINT = None
if sys.platform == "darwin":
    try:
        import ctypes
        import ctypes.util

        class _CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        _cg_path = ctypes.util.find_library("CoreGraphics")
        if _cg_path:
            _cg = ctypes.CDLL(_cg_path)
            _cg.CGWarpMouseCursorPosition.argtypes = [_CGPoint]
            _cg.CGWarpMouseCursorPosition.restype = ctypes.c_int32
            _CG_WARP_CURSOR = _cg.CGWarpMouseCursorPosition
            _CG_POINT = _CGPoint
    except Exception:
        _CG_WARP_CURSOR = None
        _CG_POINT = None


def warp_cursor(pos: QPoint) -> None:
    """Move the system cursor, working around macOS' ignored setPos()."""
    if _CG_WARP_CURSOR is not None and _CG_POINT is not None:
        try:
            if _CG_WARP_CURSOR(_CG_POINT(float(pos.x()), float(pos.y()))) == 0:
                return
        except Exception:
            pass
    QCursor.setPos(pos)


class SnapSystem(QObject):
    move_item_to_snap_pos =Signal(QPointF)

    snap_points: dict[str, set[SnapPointTuple]]
    mapToScreen: Callable[[SnapPointTuple], QPoint] | None
    snap_threshold: float
    active_types: list[str]
    current_snap: tuple[SnapPointTuple, str] | None
    current_snap_pos: SnapPointTuple | None
    snap_indicator: object | None
    show_grid: bool
    grid_size: float
    geometric_elements: list[GeometricElement]
    intersection_cache: defaultdict[SnapPointTuple, list[GeometricElement]]
    distance_when_found_snap_pos: float
    flag_when_found_snap_pos: bool
    last_cursor_pos: QPointF | None

    def __init__(
        self,
        parent: QObject | None = None,
        threshold: float = 10,
        map_scene_to_screen: Callable[[SnapPointTuple], QPoint] | None = None,
    ) -> None:
        super().__init__(parent=parent)
        # 捕捉点集合
        self.snap_points = {
            'endpoints': set(),    # 端点
            'midpoints': set(),    # 中点
            'intersections': set(),# 交点
            'centers': set(),      # 中心点
            'grid': set()          # 网格点
        }
        self.mapToScreen = map_scene_to_screen
        # 捕捉参数
        self.snap_threshold = threshold  # 像素阈值
        self.active_types = ['endpoints', 'midpoints', 'intersections','grid']  # 激活的捕捉类型
        self.current_snap = None  # 当前捕捉点 (point, type)
        self.current_snap_pos = None  # 当前捕捉点 point
        self.snap_indicator = None  # 视觉指示器
        
        self.show_grid =True
        self.grid_size = 200.0
        
        # 存储所有几何元素（用于交点计算）
        self.geometric_elements = []
        
        # 交点计算缓存
        self.intersection_cache = defaultdict(list)
        self.distance_when_found_snap_pos =0
        self.flag_when_found_snap_pos =False
        # 最近一次参与捕捉判定时的光标场景坐标，供 get_snap_info() 计算距离。
        self.last_cursor_pos = None

        # self.timer = QTimer()
    
    def update_endpoints(self, poses: Iterable[QPointF]) -> None:
        self.snap_points['endpoints'].clear()
        for pos in poses:
            self.snap_points['endpoints'].add(pos.toTuple())

    def update_midpoints(self, poses: Iterable[QPointF]) -> None:
        self.snap_points['midpoints'].clear()
        for pos in poses:
            self.snap_points['midpoints'].add(pos.toTuple())




    def move_cursor_to_snaped_pos(
        self,
        snaped_pos: SnapPointTuple | None,
        mouse_pos: QPointF,
    ) -> None:
        def calc_distance(p1: QPointF, p2: QPointF) -> float:
            dx = p1.x() - p2.x()
            dy = p1.y() - p2.y()
            return math.sqrt(dx*dx + dy*dy)
        if snaped_pos:
            distance = calc_distance(QPointF(snaped_pos[0],snaped_pos[1]),mouse_pos)
           
            if distance<self.distance_when_found_snap_pos:
                target_cursor_pos=self.mapToScreen(snaped_pos)#目标吸附点
                warp_cursor(target_cursor_pos)
                QTimer.singleShot(1000,lambda:setattr(self,"distance_when_found_snap_pos",0.0))
                
            # 计算距离
            if not self.flag_when_found_snap_pos:
                self.distance_when_found_snap_pos = calc_distance(QPointF(snaped_pos[0],snaped_pos[1]),mouse_pos)
            self.flag_when_found_snap_pos = True
        else:
            self.flag_when_found_snap_pos = False    
            self.distance_when_found_snap_pos = 0.0

    def move_cursor_to_snaped_pos_V2(
        self,
        snaped_pos: SnapPointTuple | None,
        enable: bool,
    ) -> None:
        if snaped_pos and enable :
            target_cursor_pos=self.mapToScreen(snaped_pos)#目标吸附点
            dpos = QCursor.pos() - target_cursor_pos
            distance = math.sqrt(dpos.x()*dpos.x() + dpos.y()*dpos.y())
            if distance>400.0:
                return
            warp_cursor(target_cursor_pos)
            debug_log(f"发送{snaped_pos}")
            self.move_item_to_snap_pos.emit(QPointF(snaped_pos[0],snaped_pos[1]))
            
            
        
    def set_snap_threshold(self, threshold: float) -> None:
        self.snap_threshold = threshold

    def add_element(self, element: GeometricElement) -> None:
        """添加几何元素（直线、圆等）"""
        if element in self.geometric_elements:
            return
        self.geometric_elements.append(element)
        self.update_intersections(element)

    def remove_element(self, element: GeometricElement) -> None:
        """删除几何元素，并清掉它参与的所有交点。

        旧实现只增不减：图元被删掉后仍留在 ``geometric_elements`` 中，
        既让交点计算越算越慢，也会产出已经不存在的交点。
        """
        try:
            self.geometric_elements.remove(element)
        except ValueError:
            return
        self.update_intersections()

    def clear_elements(self) -> None:
        """清空几何元素与交点缓存（切换页面/清空场景时调用）。"""
        self.geometric_elements.clear()
        self.intersection_cache.clear()
        self.snap_points['intersections'].clear()

    def update_intersections(self, new_element: GeometricElement | None = None) -> None:
        """更新所有交点（可针对新元素优化计算）"""
        self.snap_points['intersections'].clear()
        # 交点缓存与点集必须同步失效，否则缓存会随元素增删无限增长。
        self.intersection_cache.clear()
        
        # 计算所有可能的交点
        for i, elem1 in enumerate(self.geometric_elements):
            for j, elem2 in enumerate(self.geometric_elements):
                if i >= j:  # 避免重复计算
                    continue
                    
                # 如果指定了新元素，只计算与新元素的交点
                if new_element and elem1 != new_element and elem2 != new_element:
                    continue
                    
                # 计算两条几何元素的交点
                intersections = self.calculate_intersection(elem1, elem2)
                for point in intersections:
                    self.snap_points['intersections'].add(point)
                    # 缓存交点对应的元素。几何元素可能是 dict（不可哈希），
                    # 因此这里用列表并在写入前去重，而不是放进 set。
                    bucket = self.intersection_cache[point]
                    if elem1 not in bucket:
                        bucket.append(elem1)
                    if elem2 not in bucket:
                        bucket.append(elem2)

    def calculate_intersection(
        self,
        elem1: GeometricElement,
        elem2: GeometricElement,
    ) -> set[SnapPointTuple]:
        """计算两条几何元素的交点（这里以直线为例）"""
        intersections: set[SnapPointTuple] = set()
        
        # 直线-直线交点计算
        if elem1['type'] == 'line' and elem2['type'] == 'line':
            x1, y1 = elem1['start']
            x2, y2 = elem1['end']
            x3, y3 = elem2['start']
            x4, y4 = elem2['end']
            
            # 计算两条直线的交点公式
            denom = (y4 - y3) * (x2 - x1) - (x4 - x3) * (y2 - y1)
            if denom != 0:  # 避免平行线
                ua = ((x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)) / denom
                ub = ((x2 - x1) * (y1 - y3) - (y2 - y1) * (x1 - x3)) / denom
                
                # 检查交点是否在线段上
                if 0 <= ua <= 1 and 0 <= ub <= 1:
                    x = x1 + ua * (x2 - x1)
                    y = y1 + ua * (y2 - y1)
                    intersections.add((round(x, 2), round(y, 2)))
        
        # 可以添加其他几何元素的交点计算（如直线-圆、圆-圆等）
        return intersections

    def get_nearest_grid_point(self, cursor_pos: QPointF) -> SnapPointTuple:
        """返回离光标最近的网格交点。

        网格是规则点阵，最近交点可以直接算出来，不需要先枚举整片区域。
        """
        gx = round(cursor_pos.x() / self.grid_size) * self.grid_size
        gy = round(cursor_pos.y() / self.grid_size) * self.grid_size
        return (gx, gy)

    def snap_to_point(self, cursor_pos: QPointF) -> SnapPointTuple | None:
        """尝试捕捉到最近的捕捉点。

        网格点不再依赖 ``update_grid`` 预先枚举：视口放大到 20000x10000 时
        那会产生上万个点，每次鼠标移动都要重建集合并线性扫描。这里改为
        直接算出最近的网格交点，其余类型（端点/中点/中心/交点）只来自
        鼠标附近区域的图元，规模很小。
        """
        closest_point: tuple[SnapPointTuple, str] | None = None
        self.last_cursor_pos = cursor_pos
        # 用平方距离比较，省掉每次开方。
        min_distance_sq = self.snap_threshold * self.snap_threshold

        # 先比较图元上的捕捉点（端点/中点/中心/交点），它们的优先级高于
        # 网格：同距离时网格不得覆盖图元捕捉点（与旧的 active_types 顺序一致）。
        for snap_type in self.active_types:
            if snap_type == 'grid':
                continue
            for point in self.snap_points.get(snap_type, ()):
                dx = point[0] - cursor_pos.x()
                dy = point[1] - cursor_pos.y()
                distance_sq = dx * dx + dy * dy
                if distance_sq < min_distance_sq:
                    min_distance_sq = distance_sq
                    closest_point = (point, snap_type)

        # 网格最后比较：只在比已找到的捕捉点更近时才取代它。
        if 'grid' in self.active_types and self.show_grid:
            point = self.get_nearest_grid_point(cursor_pos)
            dx = point[0] - cursor_pos.x()
            dy = point[1] - cursor_pos.y()
            distance_sq = dx * dx + dy * dy
            if distance_sq < min_distance_sq:
                closest_point = (point, 'grid')

        # 更新当前捕捉点
        self.current_snap = closest_point
        self.current_snap_pos = closest_point[0] if closest_point is not None else None
        return closest_point[0] if closest_point else None


    def draw_snap_indicator(
        self,
        painter: QPainter,
        map_scene_to_view: Callable[[float, float], QPointF],
    ) -> None:
        """绘制捕捉指示器（红色十字）。

        各捕捉类型统一用同一个红色十字，避免两套完全相同的绘制分支。
        """
        if not self.current_snap:
            return

        point, _snap_type = self.current_snap
        x, y = point
        view_pos = map_scene_to_view(x, y)

        painter.save()
        painter.setPen(QPen(QColor(255, 0, 0), 1))
        painter.drawLine(
            QPoint(view_pos.x() - 10, view_pos.y()),
            QPoint(view_pos.x() + 10, view_pos.y()),
        )
        painter.drawLine(
            QPoint(view_pos.x(), view_pos.y() - 10),
            QPoint(view_pos.x(), view_pos.y() + 10),
        )
        painter.restore()

    def get_snap_info(self) -> SnapInfo | None:
        """获取当前捕捉点的详细信息"""
        if not self.current_snap:
            return None

        point, snap_type = self.current_snap
        cursor = self.last_cursor_pos
        distance = 0.0
        if cursor is not None:
            distance = math.hypot(point[0] - cursor.x(), point[1] - cursor.y())

        info = SnapInfo(
            point=point,
            type=snap_type,
            distance=distance,
        )
        
        # 如果是交点，添加相关元素信息
        if snap_type == 'intersections':
            info['elements'] = list(self.intersection_cache.get(point, []))
        
        return info

    def update_grid(self, scene_area: QRectF) -> None:
        """枚举可见区域内的所有网格点（保留 API，热路径已不再调用）。

        ``snap_to_point`` 现在直接计算最近的网格交点，因此鼠标移动时无需
        再枚举整片区域。此方法仅留给需要完整网格点集的离线场景使用；
        视口很大时点数会非常可观，不要放在每帧执行的回调里。
        """
        if not self.show_grid:
            return
            
        self.snap_points['grid'].clear()

        # The scene may use swapped/inverted axes (``is_use_for_agv_map``),
        # in which case a QRectF built from two points can have negative
        # width/height.  Normalize before reading left/right/top/bottom.
        scene_area = scene_area.normalized()

        # Collect every grid intersection that touches the visible scene
        # area.  The old code used the right/bottom edge as the range start
        # and the left/top edge as the end, so ``range`` was always empty and
        # no grid snap point was ever generated.
        x_min = math.floor(scene_area.left() / self.grid_size)
        x_max = math.ceil(scene_area.right() / self.grid_size)
        y_min = math.floor(scene_area.top() / self.grid_size)
        y_max = math.ceil(scene_area.bottom() / self.grid_size)

        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                self.snap_points['grid'].add((x*self.grid_size, y*self.grid_size))
        

        
        # print(self.snap_points)

        
        # # 生成网格点
        