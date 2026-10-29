import math
import sys
from collections import defaultdict
from PySide6.QtCore import Qt, QPointF,QPoint, QRectF,Signal,QTimer,QObject
from PySide6.QtGui import QCursor,QPainter,QPen, QColor
import math

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
    def __init__(self,parent=None, threshold=10 ,map_scene_to_screen=None):
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
        self.intersection_cache = defaultdict(set)
        self.distance_when_found_snap_pos =0
        self.flag_when_found_snap_pos =False

        # self.timer = QTimer()
    
    def update_endpoints(self,poses):
        self.snap_points['endpoints'].clear()
        for pos in poses:
            self.snap_points['endpoints'].add(pos.toTuple())
    def update_midpoints(self,poses):
        self.snap_points['midpoints'].clear()
        for pos in poses:
            self.snap_points['midpoints'].add(pos.toTuple())




    def move_cursor_to_snaped_pos(self,snaped_pos,mouse_pos):
        def calc_distance(p1:QPointF,p2:QPointF):
            dx = p1.x() - p1.x()
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

    def move_cursor_to_snaped_pos_V2(self,snaped_pos,enable):
        if snaped_pos and enable :
            target_cursor_pos=self.mapToScreen(snaped_pos)#目标吸附点
            dpos = QCursor.pos() - target_cursor_pos
            distance = math.sqrt(dpos.x()*dpos.x() + dpos.y()*dpos.y())
            if distance>400.0:
                return
            warp_cursor(target_cursor_pos)
            print(f"发送{snaped_pos}")
            self.move_item_to_snap_pos.emit(QPointF(snaped_pos[0],snaped_pos[1]))
            
            
        
    def set_snap_threshold(self,threshold):
        self.snap_threshold = threshold

    def add_element(self, element):
        """添加几何元素（直线、圆等）"""
        self.geometric_elements.append(element)
        self.update_intersections(element)

    def update_intersections(self, new_element=None):
        """更新所有交点（可针对新元素优化计算）"""
        self.snap_points['intersections'].clear()
        
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
                    # 缓存交点对应的元素
                    self.intersection_cache[point].add(elem1)
                    self.intersection_cache[point].add(elem2)

    def calculate_intersection(self, elem1, elem2):
        """计算两条几何元素的交点（这里以直线为例）"""
        intersections = set()
        
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

    def snap_to_point(self, cursor_pos):
        """尝试捕捉到最近的捕捉点"""
        closest_point = None
        min_distance = float('inf')
        
        # 检查所有激活类型的捕捉点
        for snap_type in self.active_types:
            for point in self.snap_points[snap_type]:
                # 计算距离
                dx = point[0] - cursor_pos.x()
                dy = point[1] - cursor_pos.y()
                distance = math.sqrt(dx*dx + dy*dy)
                
                # 检查是否在阈值内且更近
                if distance < self.snap_threshold and distance < min_distance:
                    min_distance = distance
                    closest_point = (point, snap_type)
        
        # 更新当前捕捉点
        self.current_snap = closest_point
        self.current_snap_pos = closest_point[0] if closest_point is not None else None
        return closest_point[0] if closest_point else None


    def draw_snap_indicator(self, painter:QPainter, map_scene_to_view):
        """绘制捕捉指示器"""
        if self.current_snap:
            point, snap_type = self.current_snap
            x, y = point
            view_pos = map_scene_to_view(x,y)
            # 根据捕捉类型绘制不同的指示器
            if snap_type == 'grid':
                # 绘制十字交叉线
                painter.save()
                painter.setPen(QPen(QColor(255,0,0), 1))
                
                
                painter.drawLine(QPoint(view_pos.x()-10, view_pos.y()), QPoint(view_pos.x()+10, view_pos.y()))
                painter.drawLine(QPoint(view_pos.x(), view_pos.y()-10), QPoint(view_pos.x(), view_pos.y()+10))

                painter.restore()
                
                # 绘制小圆圈
                # canvas.draw_circle((x, y), radius=3, color='red', fill=False)
            else:
                painter.save()
                painter.setPen(QPen(QColor(255,0,0), 1))
                
                
                painter.drawLine(QPoint(view_pos.x()-10, view_pos.y()), QPoint(view_pos.x()+10, view_pos.y()))
                painter.drawLine(QPoint(view_pos.x(), view_pos.y()-10), QPoint(view_pos.x(), view_pos.y()+10))

                painter.restore()

    def get_snap_info(self):
        """获取当前捕捉点的详细信息"""
        if not self.current_snap:
            return None
        
        point, snap_type = self.current_snap
        info = {
            'point': point,
            'type': snap_type,
            'distance': math.dist(point, self.last_cursor_pos)
        }
        
        # 如果是交点，添加相关元素信息
        if snap_type == 'intersections':
            info['elements'] = list(self.intersection_cache.get(point, []))
        
        return info

    def update_grid(self, scene_area:QRectF):
        """更新网格点"""
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
        