from PySide6.QtWidgets import QMainWindow, QApplication
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QApplication,QWidget,QVBoxLayout, QFrame,QSpacerItem,QSizePolicy,QSplitter,QScrollArea,QToolTip,
                             QHBoxLayout, QLabel)
from PySide6.QtCore import Qt, QPointF, QRectF,QPoint,QObject,Signal,QTimer,QSize,QSizeF,QRect,QEvent,QPropertyAnimation,QEasingCurve,Property
from PySide6.QtWidgets import ( QToolTip)
from PySide6.QtGui import QPainter, QPen, QColor,QBrush,QPolygonF , QPixmap,QFont,QMouseEvent,QKeyEvent,QRegion

from typing import List
from collections import deque
import math

from datetime import datetime
import weakref

import json,sys,os

# 图元级调试输出总开关。默认关闭：一次场景加载会产生上万行日志，
# 需要排查时设置环境变量 RACK_DEBUG_SCENE=1 打开。
DEBUG_SCENE = os.environ.get("RACK_DEBUG_SCENE", "") == "1"


def debug_log(*args, **kwargs) -> None:
    if DEBUG_SCENE:
        print(*args, **kwargs)
from .elements import (
    base_element,
    circle_element,
    group_element,
    image_element,
    line_element,
    rect_element,
    text_element,
    triangle_element,
)
# from my_elements_v2 import rect_element,line_element,circle_element ,base_element,group_element,text_element,image_element,triangle_element
from .mySnapSystem import SnapSystem
import copy
from .my_common import SceneMode

# Default page background colour, stored as ``#aarrggbb`` in the page JSON.
DEFAULT_BACKGROUND_COLOR = "#BEE1F59B"


class AxisLine(QObject):
    """Qt版本的坐标轴线条"""
    needs_redraw = Signal()  # 需要重绘信号
    
    def __init__(self, parent: QWidget, place_way: str = "horizontal", 
                 x: int = 0, y: int = 0, color: QColor = Qt.gray):
        super().__init__(parent)
        self.parent_widget = parent
        self.place_way = place_way
        self.color = color
        self.visible = True
        self.scale_factor = 1.0
        
        # 初始化线条位置
        self.x = x
        self.y = y
        self.update_position()
        
    def update_position(self):
        """更新线条位置"""
        width = self.parent_widget.width()
        height = self.parent_widget.height()
        
        if self.place_way == "horizontal":
            self.start = QPoint(0, self.y)
            self.end = QPoint(width, self.y)
        else:  # vertical
            self.start = QPoint(self.x, 0)
            self.end = QPoint(self.x, height)
            
    def set_scale(self, factor: float):
        """设置缩放因子并更新可见性"""
        self.scale_factor = factor
        self.visible = factor >= 0.3
        self.needs_redraw.emit()
        
    def move_to(self, x: int = None, y: int = None):
        """移动线条位置"""
        if x is not None:
            self.x = x
        if y is not None:
            self.y = y
        self.update_position()
        self.needs_redraw.emit()
        
    def draw(self, painter: QPainter):
        """绘制线条"""
        if not self.visible:
            return
            
        pen = QPen(self.grid_color, 1, Qt.SolidLine)
        painter.setPen(pen)
        painter.drawLine(self.start, self.end)

class ArrowWidget(QWidget):
    def __init__(self, parent = None, place_way="V"):
        super().__init__(parent)
        if place_way=="v":
            start=QPointF(50, 50)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # 抗锯齿

        # 设置画笔和填充
        painter.setPen(QPen(Qt.black, 2))
        painter.setBrush(QBrush(Qt.black))  # 填充箭头

        # 调用绘制箭头函数
        self.draw_arrow(painter, QPointF(50, 50), QPointF(200, 100), arrow_size=10)

    def draw_arrow(self, painter, start, end, arrow_size=10):
        """绘制箭头线"""
        # 1. 画线段
        painter.drawLine(start, end)

        # 2. 计算角度（弧度）
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())

        # 3. 计算箭头的两个侧点
        arrow_p1 = end - QPointF(
            arrow_size * math.cos(angle + math.pi / 6),
            arrow_size * math.sin(angle + math.pi / 6)
        )
        arrow_p2 = end - QPointF(
            arrow_size * math.cos(angle - math.pi / 6),
            arrow_size * math.sin(angle - math.pi / 6)
        )

        # 4. 画箭头（填充三角形）
        arrow_head = QPolygonF([end, arrow_p1, arrow_p2])
        painter.drawPolygon(arrow_head)

class grid_map_window(QWidget):
    animation_done =Signal()
    # 添加属性声明
    def get_animation_progress(self):
        return self._animation_progress

    def set_animation_progress(self, value):
        self._animation_progress = value
        self.update()  # 值变化时触发重绘

    animation_progress = Property(int, get_animation_progress, set_animation_progress)

    def __init__(self, parent=None,is_use_for_agv_map = False,is_x_time=True,redraw_when_mouse_move=True):
        super().__init__()
        self.setMouseTracking(True)
        self.setToolTipDuration(1000)  # 设置提示显示时间
        self.is_x_time = is_x_time
        self.if_show_axis_icon = True
        self.__redraw_when_mouse_move = redraw_when_mouse_move

        self.__bg_color = QColor(DEFAULT_BACKGROUND_COLOR)
        self.__show_grid=True

        self.is_animating = False
        self.animation = None
        self._animation_progress = 0
        self.scale_factor_old = 1.0
        # Target of the animated "调整视图" (see restore_saved_view).
        self._view_animation_start = None
        self._view_animation_target = None
        # 场景坐标系参数
        self.scene_origin = QPointF(0, 0)  # 场景原点在视图中的位置
        self.scene_scale = 1.0  # 场景缩放比例
      
        self.scene_units_per_grid_x = 50.0  # 每个网格代表的场景单位数
        self.scene_units_per_grid_y = 50.0  # 每个网格代表的场景单位数

        self.view_x0 =0.0
        self.view_y0 =0.0
        self.view_x1 =0.0
        self.view_y1 =0.0

        self.sence_x0 =0.0
        self.sence_y0 =0.0
        self.sence_x1 =0.0
        self.sence_y1 =0.0

        self.is_use_for_agv_map = is_use_for_agv_map
        
        # 网格参数
        self.grid_size = 50
        self.grid_color = Qt.gray
        self.base_grid_size = 50
        
        # 视图变换参数
        self.scale_factor = 1.0
        self.offset = QPointF(0, 0)
        self.last_pos = QPoint()
        # 鼠标状态
        self.panning = False
        self.painter = None

        self.sence_pos_mouse = QPointF(0,0)

        self.hide_tool_tip_flag =False
        self.cursor_inside_flag = False

        # 设置窗口属性以实现透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        # 创建双缓冲区
        self.backing_store  = QPixmap(self.size())
        self.dynamic_buffer = QPixmap(self.size())
        self.backing_store.fill(Qt.transparent)
        self.dynamic_buffer.fill(Qt.transparent)

        self.update_coordinate()

    def start_animation(self):
        self._start_animation(self.animation_to_sence_origin)

    def _start_animation(self, on_progress):
        """Drive ``animation_progress`` 0 -> 100, calling ``on_progress``.

        The 1s OutQuad curve is shared by every view animation so "调整视图"
        keeps the same feel whichever range it restores.
        """
        self._stop_animation()
        self.is_animating = True
        self._animation_progress = 0
        self.animation = QPropertyAnimation(self, b"animation_progress")
        self.animation.setDuration(1000)
        self.animation.setEasingCurve(QEasingCurve.OutQuad)
        self.animation.setStartValue(0)
        self.animation.setEndValue(100)
        self.animation.valueChanged.connect(on_progress)
        self.animation.finished.connect(self.animation_finished)
        self.animation.start()

    def _stop_animation(self):
        """Abort a running view animation without emitting ``animation_done``."""
        animation = getattr(self, "animation", None)
        self.animation = None
        if animation is None:
            return
        try:
            # Disconnect first: a stopped animation must not call
            # animation_finished() for a target that is being replaced.
            animation.valueChanged.disconnect()
            animation.finished.disconnect()
            animation.stop()
        except (RuntimeError, TypeError):
            pass
        animation.deleteLater()
        self.is_animating = False
        self._animation_progress = 0
        # Forget the pending animated restore: the next animation (for example
        # goto_sence_origin) must not snap to a stale target when it finishes.
        self._view_animation_start = None
        self._view_animation_target = None

    def animation_finished(self):
        
        self.is_animating = False
        self._animation_progress = 0
        # Snap to the exact target range so float rounding of the last frame
        # does not leave the view a pixel off.
        target = self._view_animation_target
        self._view_animation_start = None
        self._view_animation_target = None
        if target is not None:
            (center_x, center_y), scale = target
            self._apply_view_state(center_x, center_y, scale)
        self.update()
        self.animation_done.emit()
    
    def animation_to_sence_origin(self):

        progress = self._animation_progress 
        pos_start = QPointF((self.view_x0+self.view_x1)/2.0,(self.view_y0+self.view_y1)/2.0)
        pos_end   = self.sceneToView(0,0)
        d = (pos_start-pos_end) * progress/100.0
        
        self.move_chart((d)*self.scale_factor)

    def animation_to_view_target(self):
        """Step of the animated restore started by :meth:`restore_saved_view`."""
        if self._view_animation_start is None or self._view_animation_target is None:
            return
        progress = self._animation_progress / 100.0
        (start_x, start_y), start_scale = self._view_animation_start
        (target_x, target_y), target_scale = self._view_animation_target
        scale = start_scale + (target_scale - start_scale) * progress
        if scale <= 0:
            return
        center_x = start_x + (target_x - start_x) * progress
        center_y = start_y + (target_y - start_y) * progress
        self._apply_view_state(center_x, center_y, scale)

    def goto_sence_origin(self):
        self.scale_factor_old =self.scale_factor
        self.start_animation()

    def move_chart(self,offset:QPoint):
        self.offset += offset
       
        old_pos = (QPointF(self.rect().width()/2.0,self.rect().height()/2.0) - self.offset) / self.scale_factor
        # 缩放控制
        progress = self._animation_progress 

        self.scale_factor =self.scale_factor_old+(1.0-self.scale_factor_old) * progress/100.0

        # 计算缩放后的偏移量，保持鼠标位置不变
        self.offset = QPointF(self.rect().width()/2.0,self.rect().height()/2.0) - old_pos * self.scale_factor
       
        self.update_coordinate()
        self.update()

    def set_bg_color(self,color:QColor):
        """Set the page background colour and repaint immediately."""
        if not isinstance(color, QColor):
            color = QColor(color)
        if not color.isValid():
            return
        self.__bg_color = color
        # The background is filled from scratch on every repaint, so a plain
        # update() is enough to show the new colour right away.
        self.update()
    def get_bg_color(self):
        return  self.__bg_color 
    def is_show_grid(self):
        return self.__show_grid
    def show_grid(self,enable):
        if enable != self.__show_grid:
            self.__show_grid = enable 
            self.update()

    def resizeEvent(self, event):
        """窗口大小改变时调整缓冲区"""
        self.update_coordinate()
        self.backing_store  = QPixmap(self.size())
        self.dynamic_buffer = QPixmap(self.size())
        self.backing_store.fill(Qt.transparent)
        self.dynamic_buffer.fill(Qt.transparent)
        self.update()

    def update_background_buffer(self,repaint_view:QRegion):
        """初始化背景缓冲区，只包含网格背景"""
        
        # self.backing_store = QPixmap(self.size())
        
        # 在背景缓冲区上绘制网格
        bg_painter = QPainter(self.backing_store)

        self.draw_bg(bg_painter,repaint_view)
        if self.__show_grid:
            self.draw_grid(bg_painter,repaint_view)
        bg_painter.end()
    
    def update_coordinate(self):
        rect = self.rect()
        inv_scale = 1.0 / self.scale_factor

        
        # 计算世界坐标范围
        self.view_x0 = (-self.offset.x()) * inv_scale
        self.view_y0 = (-self.offset.y()) * inv_scale
        self.view_x1 = self.view_x0 + (rect.width())  * inv_scale
        self.view_y1 = self.view_y0 + (rect.height()) * inv_scale
        self.sence_x0 =                self.viewToScene(self.view_x0,self.view_y0).x() 
        self.sence_y0 =                self.viewToScene(self.view_x0,self.view_y0).y()
        self.sence_x1 =                self.viewToScene(self.view_x1,self.view_y1).x()
        self.sence_y1 =                self.viewToScene(self.view_x1,self.view_y1).y()
    def draw_bg(self, painter,repaint_view:QRegion):
        painter = QPainter(self)

        painter.setBrush(self.__bg_color )
        # painter.drawRect(self.rect())
        painter.fillRect(self.rect(),self.__bg_color)

        painter.end()
    def draw_grid(self, painter,repaint_view:QRegion):
        """绘制网格背景"""
        painter = QPainter(self)

        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.grid_color, 1))
        
        
        
        # 应用视图变换
        painter.translate(self.offset)
        painter.scale(self.scale_factor, self.scale_factor)
       
        painter.setClipRegion(repaint_view)
        painter.setClipping(True)  # 显式启用裁剪
        # # 计算可见区域
        # rect = self.rect()
        # inv_scale = 1.0 / self.scale_factor

        
        # # 计算世界坐标范围
        # self.view_x0 = (-self.offset.x()) * inv_scale
        # self.view_y0 = (-self.offset.y()) * inv_scale
        # self.view_x1 = self.view_x0 + (rect.width())  * inv_scale
        # self.view_y1 = self.view_y0 + (rect.height()) * inv_scale
        # self.sence_x0 =                self.viewToScene(self.view_x0,self.view_y0).x() 
        # self.sence_y0 =                self.viewToScene(self.view_x0,self.view_y0).y()
        # self.sence_x1 =                self.viewToScene(self.view_x1,self.view_y1).x()
        # self.sence_y1 =                self.viewToScene(self.view_x1,self.view_y1).y()


        view_left   = self.view_x0 - self.grid_size
        view_top    =  self.view_y0 - self.grid_size
        view_right  = self.view_x1 +  self.grid_size
        view_bottom = self.view_y1+ self.grid_size
        #对齐到网格
        left   =  int(view_left / self.grid_size) * self.grid_size
        top    =   int(view_top / self.grid_size) * self.grid_size
        right  = int(view_right / self.grid_size) * self.grid_size + self.grid_size
        bottom = int(view_bottom / self.grid_size) * self.grid_size + self.grid_size
        if self.is_use_for_agv_map:
            xx,yy = self.sceneToView(0,0).toTuple()

            x = xx
            while x <= right:
                painter.drawLine(x , top, x, bottom)
                x += self.grid_size
            
            x = xx-self.grid_size
            while x >= left:
                painter.drawLine(x , top, x, bottom)
                x -= self.grid_size
                
            y = yy
            while y <= bottom:
                painter.drawLine(left, y, right, y)
                y += self.grid_size
            y = yy-self.grid_size
            while y >= top:
                painter.drawLine(left, y, right, y)
                y -= self.grid_size
        
            painter.drawEllipse(self.scene_origin, 3, 3)
        else:
            
            # 绘制网格线
            x = left
            while x <= right:
                painter.drawLine(x, top, x, bottom)
                x += self.grid_size
                
            y = top
            while y <= bottom:
                painter.drawLine(left, y, right, y)
                y += self.grid_size

    
        

        # if self.if_show_axis_icon:
        #     # 恢复变换并重置所有变换
        #     painter.resetTransform()

        #     painter.setRenderHint(QPainter.Antialiasing)  # 抗锯齿
        #     # 设置画笔和填充
        #     painter.setPen(QPen(Qt.black, 2))
        #     painter.setBrush(QBrush(Qt.black))  # 填充箭头
        #     if not self.is_use_for_agv_map:
        #         painter.drawText(QPointF(70, self.height() - 25), "X")
        #         painter.drawText(QPointF(25, self.height() - 90), "Y")
        #         self.draw_arrow(painter, QPointF(15, self.height() - 20), QPointF(95, self.height() - 20), arrow_size=10)#x
        #         self.draw_arrow(painter, QPointF(15, self.height() - 20), QPointF(15, self.height() - 100), arrow_size=10)
        #     else:
        #         painter.drawText(QPointF(self.width()-80, self.height() - 25), "Y")
        #         painter.drawText(QPointF(self.width()-30, self.height() - 90), "X")
        #         self.draw_arrow(painter, QPointF(self.width()-15, self.height() - 20), QPointF(self.width()-95, self.height() - 20), arrow_size=10)#x
        #         self.draw_arrow(painter, QPointF(self.width()-15, self.height() - 20), QPointF(self.width()-15, self.height() - 100), arrow_size=10)

        
        painter.end()

    def wheelEvent(self, event):
        # 获取鼠标位置
        mouse_pos = event.position()
        # 计算缩放前的坐标
        old_pos = (mouse_pos - self.offset) / self.scale_factor
        
        # 缩放控制
        zoom_in = event.angleDelta().y() > 0
        factor = 1.1 if zoom_in else 0.9
        self.scale_factor *= factor
        self.scale_factor = max(0.1, min(self.scale_factor, 10.0))  # 限制缩放范围
        
        # 计算缩放后的偏移量，保持鼠标位置不变
        self.offset = mouse_pos - old_pos * self.scale_factor

        self.update_coordinate()
        if self.__redraw_when_mouse_move:
            # self.update()
            pass
        
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event:QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.panning = True
            self.last_pos = event.position().toPoint()
            
    def mouseMoveEvent(self, event):
        # return
        if self.panning:
            delta = event.position().toPoint() - self.last_pos
            self.offset += delta
            self.last_pos = event.position().toPoint()


            self.update_coordinate()
            if self.__redraw_when_mouse_move:
                pass
                # self.update()
           
        else:
            
            # 获取鼠标位置并转换为场景坐标
            window_pos = event.position() #窗口坐标
            w=self.rect().width()
            h=self.rect().height()
            self.cursor_inside_flag=True if 20<window_pos.toPoint().x()<w-20 and 20<window_pos.toPoint().y()<h-20 else False



            dx = (window_pos.x())/self.scale_factor
            dy = (window_pos.y())/self.scale_factor
            view_pos = QPointF(dx+self.view_x0,dy+self.view_y0)

            scene_pos = self.viewToScene(view_pos)
            self.sence_pos_mouse = scene_pos
            # if self.hide_tool_tip_flag:
            #     return
            # if self.is_x_time:#rcd
            #     text = f"Y: {scene_pos.y():.2f}"
            # else:
            #     text = f"X: {scene_pos.x():.2f}\nY: {scene_pos.y():.2f}"
            
            # # 显示坐标提示
            # QToolTip.showText(
            #     event.globalPosition().toPoint(),
            #     text,
            #     self
            # )

    def map_scene_to_screen(self,pos):
        view_pos = self.sceneToView(pos[0],pos[1])
        dx =view_pos.x() - self.view_x0
        dy =view_pos.y() - self.view_y0
        
        p=QPointF(dx*self.scale_factor,dy*self.scale_factor).toPoint()
        return self.mapToGlobal(p)
    

    def hide_tool_tip(self,enable):
        self.hide_tool_tip_flag =enable

    
            
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.panning = False
            
    def viewToScene(self, *args):
        """视图坐标转场景坐标
        支持两种调用方式:
        1. viewToScene(x, y) 
        2. viewToScene(QPointF)
        """
        if len(args) == 1:  # QPoint输入
            view_pos = args[0]
            x = view_pos.x()
            y = view_pos.y()
        elif len(args) == 2:  # x,y坐标输入
            x, y = args
        else:
            raise ValueError("参数必须是(x,y)或QPointF")
        # if not self.is_x_invert:    
        #     scene_x = (x - self.scene_origin.x())  / (self.grid_size * self.scene_scale) * self.scene_units_per_grid_x
        # else:
        #     scene_x = -(x - self.scene_origin.x()) / (self.grid_size * self.scene_scale) * self.scene_units_per_grid_x
        # scene_y = - (y - self.scene_origin.y())    / (self.grid_size * self.scene_scale) * self.scene_units_per_grid_y
        # return QPointF(scene_x, scene_y)
    
        if not self.is_use_for_agv_map:    
            scene_x = (x - self.scene_origin.x())  / (self.grid_size ) * self.scene_units_per_grid_x
            scene_y = - (y - self.scene_origin.y())    / (self.grid_size ) * self.scene_units_per_grid_y
        else:
            scene_y = - (x - self.scene_origin.x()) / (self.grid_size ) * self.scene_units_per_grid_x
            scene_x = - (y - self.scene_origin.y()) / (self.grid_size ) * self.scene_units_per_grid_y




        return QPointF(scene_x, scene_y)
        
    def sceneToView(self, *args):
        """场景坐标转视图坐标"""
        if len(args) == 1:  # QPoint输入
            scene_pos = args[0]
            x = scene_pos.x()
            y = scene_pos.y()
        elif len(args) == 2:  # x,y坐标输入
            x, y = args
        else:
            raise ValueError("参数必须是(x,y)或QPointF")
        # if not self.is_x_invert:    
        #     view_x =  x * (self.grid_size * self.scene_scale) / self.scene_units_per_grid_x + self.scene_origin.x()
        # else:
        #     view_x = -x * (self.grid_size * self.scene_scale) / self.scene_units_per_grid_x + self.scene_origin.x()
        # view_y = -y * (self.grid_size * self.scene_scale) / self.scene_units_per_grid_y + self.scene_origin.y()


        if not self.is_use_for_agv_map:    
            view_x =      x * (self.grid_size ) / self.scene_units_per_grid_x + self.scene_origin.x()
            view_y =     -y * (self.grid_size ) / self.scene_units_per_grid_y + self.scene_origin.y()
        else:
            view_x =     -y*(self.grid_size ) / self.scene_units_per_grid_x  + self.scene_origin.x()
            view_y =     -x*(self.grid_size ) / self.scene_units_per_grid_y  + self.scene_origin.y()


        return QPointF(view_x, view_y)
    
    def screenToScene_factor(self):
        x=self.scene_units_per_grid_y/self.grid_size/self.scale_factor
        y=self.scene_units_per_grid_x/self.grid_size/self.scale_factor
        return (x,y)

    def rect_sceneToView(self, rect:QRectF):
        # a= 20* self.scale_factor if self.scale_factor>=1.0 else 20
        # topLeft = self.sceneToView((rect.topLeft() - rect.bottomRight())/10.0+rect.topLeft())
        # bottomRight = self.sceneToView((-rect.topLeft() + rect.bottomRight())/10.0+rect.bottomRight())

        topLeft = self.sceneToView(rect.bottomRight())
        w = rect.height() * (self.grid_size ) / self.scene_units_per_grid_y    
        h = rect.width() * (self.grid_size )  / self.scene_units_per_grid_x    
        return QRectF(topLeft.x(),topLeft.y(),w,h)
        # return QRectF(topLeft,bottomRight)
    
    def rect_viewToWindow(self,rect:QRectF):
        topLeft = (rect.topLeft() - QPointF(self.view_x0,self.view_y0))*self.scale_factor
        w       = rect.width() *self.scale_factor
        h       = rect.height()*self.scale_factor
        return QRectF(topLeft.x(),topLeft.y(),w,h)
    
    def pos_viewToWindow(self,pos:QPointF):
        return (pos - QPointF(self.view_x0,self.view_y0))*self.scale_factor

    def rect_windowToView(self,window_rect:QRect):
        rect    = window_rect.toRectF()
        topLeft = rect.topLeft()/self.scale_factor + QPointF(self.view_x0,self.view_y0)
        w       = rect.width()  /self.scale_factor
        h       = rect.height() /self.scale_factor
        return QRectF(topLeft.x(),topLeft.y(),w,h).toRect()
  
        
    def setSceneOrigin(self, view_pos):
        """设置场景原点在视图中的位置"""
        self.scene_origin = view_pos
        self.update()
        
    def setSceneScale(self, scale):
        """设置场景缩放比例"""
        self.scale_factor = scale
        self.update()
        
    def setSceneUnitsPerGrid(self, x_units,y_units):
        """设置每个网格代表的场景单位数"""
        self.scene_units_per_grid_x = x_units
        self.scene_units_per_grid_y = y_units
        self.update()
    def setGridSize(self, units):
        """设置每个网格占据像素点"""
        self.grid_size = units
      
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        # 绘制场景原点标记  场景原点在视图中坐标
        self.scene_origin = QPoint(self.width()//2,self.height()//2)


    def paintEvent(self, event):
        pass

        
       
    def show_axis_icon(self,state):
        self.if_show_axis_icon = state

    def draw_arrow(self, painter, start, end, arrow_size=10):
        """绘制箭头线"""
        # 1. 画线段
        painter.drawLine(start, end)

        # 2. 计算角度（弧度）
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())

        # 3. 计算箭头的两个侧点
        arrow_p1 = end - QPointF(
            arrow_size * math.cos(angle + math.pi / 6),
            arrow_size * math.sin(angle + math.pi / 6)
        )
        arrow_p2 = end - QPointF(
            arrow_size * math.cos(angle - math.pi / 6),
            arrow_size * math.sin(angle - math.pi / 6)
        )

        # 4. 画箭头（填充三角形）
        arrow_head = QPolygonF([end, arrow_p1, arrow_p2])
        painter.drawPolygon(arrow_head)




class watch_dog(QTimer):
    def __init__(self, parent=None,timeout_callback=None):
        super().__init__(parent=parent)
        self.callback = timeout_callback
        self.timeout.connect(self.handle_timeout)
        
    def feed(self):
        self.start_watch()
    def start_watch(self):
        self.start(1000)
        
    def handle_timeout(self):
        print("watchdog 超时")
        self.stop()
        self.callback()


class DirtyRegionManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.dirtyRegion = QRegion()

    def markDirty(self,rect:QRect):
        self.dirtyRegion += rect

    def region(self):
        return self.dirtyRegion
    
    def set(self,region):
        self.dirtyRegion =region

    def reset(self):
        self.dirtyRegion = QRegion()

    def isEmpty(self):
        return self.dirtyRegion.isEmpty()

class FrameSelect(QObject):
    def __init__(self,parent=None):
        super().__init__(parent=parent)
        self.start_pos=None
        self.end_pos  =None
        self.select_rect     =None
        self.select_rect_scene    =None
        self.__done = False
        self.parent = parent

        self.__processing = False
    def receive_start_pos(self,pos):
        if self.parent._mode == SceneMode.Run:
            return
        if not self.__processing:
            self.start_pos= pos
            self.__processing = True
    def receive_end_pos(self,pos):
        if self.__processing:
            self.end_pos= pos
            self.select_rect_scene = QRectF(self.end_pos,self.start_pos)
            self.select_rect     =self.parent.rect_sceneToView(self.select_rect_scene)
            self.parent.update()
            
    def finish(self):
        if self.end_pos is None:
            self.__processing = False
            self.start_pos=None
            self.__done =False
            return
        if self.__processing:
            if self.parent.items_in_area:
                items=self.parent.items_in_area(self.select_rect_scene)
                for item in items:
                    if self.select_rect_scene.contains(item.sceneBoundingRect()):
                        item.set_selected(True)
           
            # self.select_rect     =self.parent.rect_sceneToView(QRectF(self.end_pos,self.start_pos))
        
            QTimer.singleShot(100,lambda:self.parent.update())
            self.__processing = False
            self.start_pos=None
            self.end_pos  =None
            self.select_rect = None
    def isProcessing(self):
        return bool(self.__processing)
    
    def paint(self,painter:QPainter):
        if not self.__processing or self.select_rect is None:
            
                
            return
        painter.save()
        def create_pen_style(color):
            # 创建基础画笔
            pen = QPen()
            
            # 设置画笔属性
            pen.setColor(color)  # 黑色钢笔
            pen.setWidth(1)                # 线宽3像素
            
            # 格式: [实线长度, 空白长度, 点长度, 空白长度] 重复
            dash_pattern = [4, 4]  # 8像素实线 - 4像素空白 - 2像素点 - 4像素空白
            
            pen.setDashPattern(dash_pattern)  # 设置自定义虚线模式
            pen.setStyle(Qt.CustomDashLine)   # 必须设置为自定义虚线模式
            
            # 优化端点样式
            pen.setCapStyle(Qt.RoundCap)      # 圆角端点
            pen.setJoinStyle(Qt.RoundJoin)    # 圆角连接
            return pen
        
        color = QColor(0,0,0)

        pen = create_pen_style(color)
       
        painter.setPen(pen)
       
        painter.drawRect(self.select_rect)

        painter.restore()

class myGraphicsScene(grid_map_window):
    mouse_not_move_signal =Signal()
    shine_flag_change     =Signal()
    selectionChanged      =Signal()
    def __init__(self, parent=None,auto_redraw_when_mouse_move=False):
        super().__init__(parent=parent,is_use_for_agv_map=True,is_x_time=False,redraw_when_mouse_move=auto_redraw_when_mouse_move)
        self.setFocusPolicy(Qt.StrongFocus)  # 确保能接收键盘事件
        
        self.setSceneUnitsPerGrid(200,200)
        self.setSceneScale(1.0)
        self.show_axis_icon(True)
        self.__sceneRect =None
        # Scene-coordinate view range restored from JSON.  It is kept until
        # the widget is visible with its final size, then applied once.
        self._pending_view_rect = None
        # Last range loaded from the page file.  "调整视图" restores this
        # instead of always jumping back to the coordinate origin.
        self._saved_view_rect = None
        self._view_initialized = False
        self.items = []           # 存储的图形项
        
        self.last_update_time=0
        self.update_interval =16

        #框选功能
        self.frame_select =FrameSelect(self)

        self._mode        =SceneMode.Design

        # 使用高精度定时器
        self.render_timer = QTimer()
        self.render_timer.setTimerType(Qt.PreciseTimer)  # 高精度模式
        
        self.render_timer.start(16)  # ~60 FPS
        self.needs_redraw = False

        self.current_element_id = 0
        self.current_element  =None
        self.element_data_info = []
        self.json_path = None
        # self.agv = agv_element(self)
        self.rect_params = None
        self.show_bg_map = False
        self.is_setting_group_pos = False
        self.is_setting_father =    False
        self.is_setting_base_pos =    False
        self.selected_items = []           # 存储的图形项

        self.timer1 = QTimer(self)
        self.timer2 = QTimer(self)
        self.shine_flag = False
        self.timer1.timeout.connect(self.tm1_time_out_handle)
        self.timer2.timeout.connect(self.tm2_time_out_handle)
        self.timer1.start(500)

        self.wheel_event_watcher = watch_dog(self,timeout_callback=self.wheel_watch_time_out)
        self.CTRL_wheel_rolling  =False #CTRL+鼠标滚轮标志
        self.ctrl_wheel_ang_diff =0
        self.mouse_move_event_watcher = watch_dog(self,timeout_callback=self.mouse_move_watch_time_out)
        self.mouse_moving_flag     =  False
        self.mouse_wheeling_flag   =  False

        self.CTRL_pressed_flag   =  False #ctrl按下标志
        self.__cousor_pos_locked  = False

        self.roll_dog_need_feed = False
        self.move_dog_need_feed = False

        self.has_child_hover_in_group = False
        self.hover_group = None

        self.scene_manager  = None
        self.__snap_sys_ref = None

        self.__show_coordinate = True
    
        self.dirtyRegion_manager = DirtyRegionManager(self)

        self._allow_update_data = False # 允许更新图元坐标
      
        # # 创建缓冲图像（初始大小与窗口相同）
        # self.buffer = QPixmap(self.size())
        # self.buffer.fill(Qt.transparent)  # 初始化为透明背景
        self._ready_for_update = False

        self.icons_dir = "widget_icons"
        os.makedirs(self.icons_dir,exist_ok=True)
        self.json_file = "toolbox_items.json"
        self.current_widget_to_save = None

        self.current_selected = self
        # self.load_element_info()
    
    def is_show_coordinate(self):
        return self.__show_coordinate
    def show_coordinate(self,enable):
        if enable != self.__show_coordinate:
            self.__show_coordinate = enable 
            self.update()

    def allow_items_move(self):
        return self._allow_update_data 
    
    def set_snap_sys_ref(self,snapSys:SnapSystem):
        self.__snap_sys_ref = snapSys

    def get_pos_from_mouse(self)->QPointF:
        """获取当前鼠标场景点,如锁定中，用捕捉点替代"""
        if self.__cousor_pos_locked:
            if self.__snap_sys_ref:
                pos = self.__snap_sys_ref.current_snap_pos
                return QPointF(pos[0],pos[1]) if pos else self.sence_pos_mouse
            else:
                return self.sence_pos_mouse
        else:
            return self.sence_pos_mouse

    def set_scene_manager(self,manager):
        self.scene_manager=manager
    
    def setSceneRect(self, rect: QRectF):
        self.__sceneRect = rect

    # ------------------------------------------------------------------
    # Visible view range persistence
    # ------------------------------------------------------------------
    def get_view_scene_rect(self) -> QRectF:
        """Return the scene-coordinate rectangle currently visible.

        The scene uses a custom view transform (``view_x0`` ... ``view_y1``)
        instead of ``QGraphicsView`` scrolling, so map both view corners back
        to scene coordinates and normalise them into one rectangle.  For the
        AGV coordinate system the axes are inverted, hence the normalisation.
        """

        if not self._view_initialized:
            # A loaded page may be saved again before its first show; keep the
            # range that came from disk instead of overwriting it with zeros.
            if self._pending_view_rect is not None:
                return QRectF(self._pending_view_rect)
            return QRectF()

        self.update_coordinate()
        top_left = self.viewToScene(self.view_x0, self.view_y0)
        bottom_right = self.viewToScene(self.view_x1, self.view_y1)
        return QRectF(top_left, bottom_right).normalized()

    def set_view_scene_rect(self, rect: QRectF) -> None:
        """Restore a scene-coordinate view range.

        Pages/dialogs are loaded before they are shown, so the request may be
        deferred until ``showEvent``/``resizeEvent`` provides the final widget
        size.
        """

        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            return
        self._saved_view_rect = QRectF(rect)
        self._pending_view_rect = QRectF(rect)
        self._apply_pending_view_rect()

    def set_saved_view_scene_rect(self, rect: QRectF) -> None:
        """Record the range stored in the page file without moving the view.

        The serializer writes the *currently visible* range into
        ``sceneRect``, so after every save this record has to follow the file.
        Otherwise "调整视图" would keep restoring the range the page was
        opened with instead of the one actually written to disk.
        """

        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            return
        self._saved_view_rect = QRectF(rect)

    def get_saved_view_scene_rect(self) -> QRectF:
        """Return the view range recorded in the page's ``sceneRect``."""

        if self._saved_view_rect is None:
            return QRectF()
        return QRectF(self._saved_view_rect)

    def restore_saved_view(self, animate: bool = True) -> bool:
        """Restore the view range recorded in the page's ``sceneRect``.

        With ``animate`` (the default, used by the "调整视图" menu entry) the
        view glides to the recorded range with the same 1s easing as
        :meth:`goto_sence_origin`; the range itself is not modified.  Returns
        ``False`` when the page has no usable record yet (a brand new page), so
        callers can fall back to the default origin view.
        """

        rect = self.get_saved_view_scene_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return False
        if (
            not animate
            or not self.isVisible()
            or self.width() <= 1
            or self.height() <= 1
        ):
            # Nothing to animate yet: defer to the regular restore path, which
            # also handles a widget that has not been shown.
            self.set_view_scene_rect(rect)
            return True

        target = self._view_state_for_scene_rect(rect)
        if target is None:
            return False
        self._pending_view_rect = None
        self._view_initialized = True
        # Animate from the centre of the currently visible range, expressed in
        # the same grid/view frame as ``sceneToView`` (that is what keeps the
        # motion straight while the scale changes).
        self.update_coordinate()
        start = (
            (
                (self.view_x0 + self.view_x1) / 2.0,
                (self.view_y0 + self.view_y1) / 2.0,
            ),
            self.scale_factor,
        )
        self.scale_factor_old = self.scale_factor
        self._start_animation(self.animation_to_view_target)
        self._view_animation_start = start
        self._view_animation_target = target
        return True

    def _view_state_for_scene_rect(self, rect: QRectF):
        """Return ``((center_x, center_y), scale)`` that shows ``rect``.

        ``center_x``/``center_y`` are view coordinates, i.e. the frame used by
        :meth:`sceneToView`, so callers can apply them directly or animate
        towards them.
        """

        top_left = self.sceneToView(rect.topLeft())
        bottom_right = self.sceneToView(rect.bottomRight())
        view_rect = QRectF(top_left, bottom_right).normalized()
        if view_rect.width() <= 0 or view_rect.height() <= 0:
            return None

        # A single scale factor drives both axes.  Use the smaller one so the
        # whole saved range remains visible if the window aspect has changed.
        target_scale = min(
            self.width() / view_rect.width(),
            self.height() / view_rect.height(),
        )
        if not math.isfinite(target_scale) or target_scale <= 0:
            return None
        # Interactive zoom stops at 0.1, but a page recorded from a larger
        # window (or a hand-written sceneRect) may need a smaller factor to be
        # shown completely.  The floor only guards against absurd values.
        scale = max(0.01, min(10.0, target_scale))
        center = view_rect.center()
        return (center.x(), center.y()), scale

    def _apply_view_state(self, center_x: float, center_y: float, scale: float) -> None:
        """Center view coordinate ``(center_x, center_y)`` at ``scale``."""
        self.scale_factor = scale
        self.offset = QPointF(
            self.width() / 2.0 - center_x * scale,
            self.height() / 2.0 - center_y * scale,
        )
        self.update_coordinate()
        self.update()

    def _apply_pending_view_rect(self) -> None:
        if self._pending_view_rect is None:
            return
        if not self.isVisible() or self.width() <= 1 or self.height() <= 1:
            return

        target = self._pending_view_rect
        self._pending_view_rect = None
        # Keep the custom coordinate frame centred, matching showEvent(), so
        # the saved and restored ranges use the same reference point.
        self.scene_origin = QPointF(self.width() / 2.0, self.height() / 2.0)
        state = self._view_state_for_scene_rect(target)
        if state is None:
            return
        (center_x, center_y), scale = state
        self._view_initialized = True
        self._apply_view_state(center_x, center_y, scale)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_pending_view_rect()
        if self._pending_view_rect is None:
            self._view_initialized = True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_pending_view_rect()

    def addItem(self, item:base_element )-> bool:
       
        if  self.__sceneRect.intersects(item.sceneBoundingRect()):
            item.setParent(self)
            debug_log("添加进场景")
            return True
        
        item.setParent(None)
        item.deleteLater()
        debug_log("新增的图形在场景之外，因此移除了")
        return False
        
    def removeItem(self, item:base_element ):
        item.setParent(None)
       
    def deleteItem(self, item:base_element ):
        item.setParent(None)
        item.deleteLater()
        self.current_selected = self


    


    def tm1_time_out_handle(self):
        self.shine_flag = True
        self.shine_flag_change.emit()
        self.timer1.stop()
        self.timer2.start(300)
        self.needs_redraw=True
        # self.update()
        self.roll_dog_need_feed = True
        self.move_dog_need_feed = True
    def tm2_time_out_handle(self):
        self.shine_flag = False
        self.shine_flag_change.emit()
        self.timer2.stop()
        self.timer1.start(300)
        self.needs_redraw=True
        # self.update()
        self.roll_dog_need_feed = True
        self.move_dog_need_feed = True
    def wheel_event_time_out_handle(self):
        pass

    def get_scale_factor(self):
        return self.scale_factor

    # def draw_snap_on_scene(self,painter:QPainter,):


    @staticmethod
    def preview_pen(color=QColor(0,0,0),lineWidth=None,dashed:bool=False)->QPen:
        """返回绘制过程中使用的预览画笔。

        虚线样式与 ``draw_triangle_draft_on_sence`` 保持一致，使所有图元
        在未完成绘制时都显示同样的虚线参考轮廓。
        """
        pen = QPen(color) if lineWidth is None else QPen(color, lineWidth)
        if dashed:
            pen.setStyle(Qt.DashLine)
        return pen

    def draw_circle_on_sence(self,painter:QPainter,head_pos:QPointF,radius:float,color=QColor(0,0,0),isFill=False,lineWidth=2,dashed:bool=False):
        painter.save()
        painter.setPen(self.preview_pen(color, lineWidth, dashed))
        if isFill:
            # 设置填充颜色（蓝色）
            painter.setBrush(color)
        posO=self.sceneToView(head_pos)
        view_r = radius* (self.grid_size ) / self.scene_units_per_grid_x
      
        painter.drawEllipse(posO,view_r,view_r)
        painter.restore()

    
    def draw_line_on_sence(self,painter:QPainter,head_pos:QPointF,end_pos:QPointF,color=QColor(0,0,0),lineWidth=2,dashed:bool=False):
        painter.save()
        painter.setPen(self.preview_pen(color, lineWidth, dashed))
        pos0=self.sceneToView(head_pos)
        pos1=self.sceneToView(end_pos)
        
        painter.drawLine(pos0,pos1)
        painter.restore()

    def draw_triangle_draft_on_sence(self,painter:QPainter,points,preview_pos:QPointF=None,color=QColor(0,0,0),lineWidth=2):
        """Draw the in-progress triangle while the user is still clicking.

        ``points`` holds the already collected scene vertices, while
        ``preview_pos`` is the current (possibly snapped) mouse position.
        """
        scene_points = [QPointF(point) for point in points]
        if preview_pos is not None:
            scene_points.append(QPointF(preview_pos))
        if not scene_points:
            return

        view_points = [self.sceneToView(point) for point in scene_points]

        painter.save()
        pen = self.preview_pen(color, lineWidth, True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if len(view_points) >= 2:
            painter.drawPolyline(QPolygonF(view_points))
        if len(view_points) >= 3:
            # Close the preview so the user sees the upcoming triangle.
            painter.drawLine(view_points[-1], view_points[0])

        painter.setPen(QPen(color, 1))
        painter.setBrush(color)
        for point in view_points:
            painter.drawEllipse(point, 3, 3)
        painter.restore()

    

    def draw_group_on_sence(self,painter:QPainter,leftTop:QPointF,rightTop:QPointF,bottomleft:QPointF,bottmRight:QPointF,angle:float,color=QColor(0,0,0),lineWidth=1):
        painter.save()

        def create_pen_style(color):
            # 创建基础画笔
            pen = QPen()
            
            # 设置画笔属性
            pen.setColor(color)  # 黑色钢笔
            pen.setWidth(1)                # 线宽3像素
            
            # 定义点划线模式：实线-空白-点-空白
            # 格式: [实线长度, 空白长度, 点长度, 空白长度] 重复
            dash_pattern = [8, 4, 2, 4]  # 8像素实线 - 4像素空白 - 2像素点 - 4像素空白
            
            pen.setDashPattern(dash_pattern)  # 设置自定义虚线模式
            pen.setStyle(Qt.CustomDashLine)   # 必须设置为自定义虚线模式
            
            # 优化端点样式
            pen.setCapStyle(Qt.RoundCap)      # 圆角端点
            pen.setJoinStyle(Qt.RoundJoin)    # 圆角连接
            
            return pen
        pen = create_pen_style(color)
        painter.setPen(pen)
        
        pos1=self.sceneToView(leftTop)
        pos2=self.sceneToView(rightTop)
        pos3=self.sceneToView(bottomleft)
        pos4=self.sceneToView(bottmRight)

        painter.drawPolygon([pos1,pos2,pos3,pos4])

        painter.restore()

    # def draw_group_on_sence(self,painter:QPainter,rect:QRectF,color=QColor(255,0,0)):
    #     painter.save()
    #     def create_pen_style(color):
    #         # 创建基础画笔
    #         pen = QPen()
            
    #         # 设置画笔属性
    #         pen.setColor(color)  # 黑色钢笔
    #         pen.setWidth(1)                # 线宽3像素
            
    #         # 定义点划线模式：实线-空白-点-空白
    #         # 格式: [实线长度, 空白长度, 点长度, 空白长度] 重复
    #         dash_pattern = [8, 4, 2, 4]  # 8像素实线 - 4像素空白 - 2像素点 - 4像素空白
            
    #         pen.setDashPattern(dash_pattern)  # 设置自定义虚线模式
    #         pen.setStyle(Qt.CustomDashLine)   # 必须设置为自定义虚线模式
            
    #         # 优化端点样式
    #         pen.setCapStyle(Qt.RoundCap)      # 圆角端点
    #         pen.setJoinStyle(Qt.RoundJoin)    # 圆角连接
            
    #         return pen
    #     pen = create_pen_style(color)
    #     painter.setPen(pen)

        
    #     topLeft    =self.sceneToView(rect.topLeft())
    #     bottomRight=self.sceneToView(rect.bottomRight())
    #     w= bottomRight.x() - topLeft.x()
    #     h= bottomRight.y() - topLeft.y()
        
    #     painter.drawRect(topLeft.x(),topLeft.y(),w,h)
    #     painter.restore()


    def draw_rect_on_sence(self,painter:QPainter,center_pos:QPointF,size:QSize,angle:float,color=QColor(0,0,0),isFill=False,lineWidth=2,dashed:bool=False):
        painter.save()
        painter.setPen(self.preview_pen(color, lineWidth, dashed))
        if isFill:
            # 设置填充颜色（蓝色）
            painter.setBrush(color)
        pos=self.sceneToView(center_pos)
       
        h =            size.width()* (self.grid_size ) / self.scene_units_per_grid_x
        w =            size.height()* (self.grid_size ) / self.scene_units_per_grid_y
     
        rect = QRectF(-w/2.0 ,-h/2.0,w,h)
        # 应用视图变换
        painter.translate(pos)
        painter.rotate(-angle)
        painter.drawRect(rect)

        painter.restore()

    def draw_text_on_sence(self,painter:QPainter,center_pos:QPointF,size:QSize,context:str,font_size:int,dashed:bool=False):
        painter.save()
        color = QColor(0,0,0)
        center_pos_view=self.sceneToView(center_pos)
      
        h =            size.width()  * (self.grid_size ) / self.scene_units_per_grid_x
        w =            size.height() * (self.grid_size ) / self.scene_units_per_grid_y
      
        bg_rect =QRectF(-w/2.0 ,-h/2.0,w,h)
        # 设置大号字体
        font = QFont("Arial", font_size)  # 使用固定大字号
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(color)
        
         # 应用视图变换
        painter.translate(center_pos_view)
       

        # 绘制背景
        painter.fillRect(bg_rect, QColor(0,255,0))
        if dashed:
            # 未完成绘制时用虚线框标出文本将要占据的区域
            painter.setPen(self.preview_pen(color, None, True))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(bg_rect)
            painter.setPen(color)

        # 获取文本的精确边界框
        text_rect = painter.boundingRect(bg_rect, Qt.AlignCenter, context)
    
        # 直接绘制在计算好的位置
        painter.drawText(text_rect, Qt.AlignCenter, context)
 
        painter.restore()
    
    def draw_image_on_sence(self,painter:QPainter,center_pos:QPointF,size:QSize,dashed:bool=False):
        painter.save()
        color = QColor(0,0,0)
        center_pos_view=self.sceneToView(center_pos)
      
        h =            size.width()  * (self.grid_size ) / self.scene_units_per_grid_x
        w =            size.height() * (self.grid_size ) / self.scene_units_per_grid_y
      
        bg_rect =QRectF(-w/2.0 ,-h/2.0,w,h)
    
        painter.setPen(self.preview_pen(color, None, dashed))
        
         # 应用视图变换
        painter.translate(center_pos_view)
       

        # 绘制背景
        painter.drawRect(bg_rect)

       
 
        painter.restore()
    
    def draw_rect_on_sence_V2(self,painter:QPainter,leftTop:QPointF,rightTop:QPointF,bottomleft:QPointF,bottmRight:QPointF,angle:float,color=QColor(0,0,0),isFill=False,lineWidth=2):
        painter.save()
        painter.setPen(QPen(color, lineWidth))
        if isFill:
            # 设置填充颜色（蓝色）
            painter.setBrush(color)
        pos1=self.sceneToView(leftTop)
        pos2=self.sceneToView(rightTop)
        pos3=self.sceneToView(bottomleft)
        pos4=self.sceneToView(bottmRight)

        
        # rect = QRectF(pos)
       
    
        # 应用视图变换
        # painter.translate(pos)
        # painter.rotate(-angle)
        # painter.drawRect(rect)
        painter.drawPolygon([pos1,pos2,pos3,pos4])

        painter.restore()


    def draw_agv_on_sence(self,painter:QPainter,center_pos:QPointF,size:QSize,angle:float,color=QColor(0,0,0)):
        painter.save()
        painter.setPen(QPen(color, 2))
        pos=self.sceneToView(center_pos)
       

        h =            size.height()* (self.grid_size ) / self.scene_units_per_grid_x
        w =            size.width()* (self.grid_size ) / self.scene_units_per_grid_y
        # rect = QRectF(pos.x()-view_size.height()/2.0 ,pos.y()-view_size.width()/2.0,view_size.height(),view_size.width())
        rect = QRectF(-w/2.0 ,-h/2.0,w,h)
        # 应用视图变换
        painter.translate(pos)
        painter.rotate(-angle+90)

        painter.drawRoundedRect(rect,10,10)
        painter.restore()

    # def set_dirty_region(self,dirty_region:QRegion):
    #     def serialize_region(region: QRegion) -> list:
    #         """将 QRegion 转换为可序列化的矩形列表"""
    #         return [(rect.x(), rect.y(), rect.width(), rect.height()) 
    #                 for rect in region]

    #     def deserialize_region(data: list) -> QRegion:
    #         """从序列化数据重建 QRegion"""
    #         region = QRegion()
    #         for rect_data in data:
    #             x, y, w, h = rect_data
    #             region += QRegion(x, y, w, h)
    #         return region
        
    #     s=serialize_region(dirty_region)
    #     self.__dirtyRegion = deserialize_region(s)
  
    def refresh_dynamic_buffer(self, repaint_view:QRegion):
        """刷新动态缓冲区，只包含图元"""
        
        # self.dynamic_buffer = QPixmap(self.size())
        # self.dynamic_buffer.fill(Qt.transparent)
        
        dyn_painter = QPainter(self.dynamic_buffer)
        dyn_painter.setRenderHint(QPainter.Antialiasing)
        # 应用视图变换
        dyn_painter.translate(self.offset)
        dyn_painter.scale(self.scale_factor, self.scale_factor)

        dyn_painter.setClipRegion(repaint_view)
        dyn_painter.setClipping(True)  # 显式启用裁剪
        
        for child in  self.scene_manager.m_sorted_items:
            # child.check_hover(self.sence_pos_mouse)
            child.set_dirty_region(repaint_view)
            # child.paint(dyn_painter,self.shine_flag)
            child.paint(dyn_painter,True)
        dyn_painter.end()
    
    def restore_background_for_shape(self, repaint_area:QRegion):
        """恢复图元所在位置的背景"""
        # 创建临时绘制器
        dyn_painter = QPainter(self.dynamic_buffer)
        
        # 应用视图变换
        dyn_painter.translate(self.offset)
        dyn_painter.scale(self.scale_factor, self.scale_factor)

        # 1. 先清除整个动态缓冲区
        dyn_painter.setCompositionMode(QPainter.CompositionMode_Clear)
        dyn_painter.eraseRect(repaint_area.boundingRect())
        dyn_painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        
        # 2. 从背景缓冲区精确复制需要恢复的区域
        for restore_rect in repaint_area:
            # 计算视图坐标系下的矩形
            view_rect = restore_rect
            # 确保矩形在有效范围内
            if not view_rect.isEmpty():
                dyn_painter.drawPixmap(view_rect, self.backing_store, view_rect)
            
        dyn_painter.end()

    def restore_pixmap(self,item):

        rect    = self.rect_sceneToView(item.sceneBoundingRect())
        pixmap  = QPixmap(rect.size().toSize())
        painter = QPainter(pixmap)
        painter.translate(self.offset)
        painter.scale(self.scale_factor, self.scale_factor)
        painter.drawPixmap(QPointF(0,0), self.dynamic_buffer, rect)
        painter.end()

        widget_name = f"widget_text"
        icon_path = os.path.join(self.icons_dir,"context.png")
        pixmap.save(icon_path)
        #添加到工具箱

        #保存到json
        self.save_to_json(widget_name,icon_path,rect)
        item = None

    def save_to_json(self,name,icon_path,rect):
        data=[]
        if os.path.exists(self.json_file):
            with open(self.json_file,"r") as f:
                data = json.load(f)
        data.append(
            {
                "name"  : name,
                "icon"  : icon_path,
                "type"  : "text",
                "width" : rect.width(),
                "height": rect.height(),
                # "elements":self.
            }   
        )


    def paintEvent(self, event):
        self._allow_update_data = False
        # super().paintEvent(event)
    
        if event.region().isEmpty():
            print("不重绘")
            return

        update_region_view = QRegion()
        for rect in event.region():
            update_region_view += self.rect_windowToView(rect) 

        #视图坐标系下的重绘区域
        toRepaint_view = self.dirtyRegion_manager.region().united( update_region_view )
        # print(toRepaint_view)
        # painter = QPainter(self)
        # if not self.dirtyRegion_manager.isEmpty():
        #     window_rect = QRectF(QPointF(self.view_x0,self.view_y0),QPointF(self.view_x1,self.view_y1)).toRect()
        #     painter.fillRect(window_rect, QColor("blue"))
        # painter.end() 
        
        # print(toRepaint_view)
        self.update_background_buffer(toRepaint_view)
      
        self.restore_background_for_shape(toRepaint_view)

        self.refresh_dynamic_buffer(toRepaint_view)

        if self.current_widget_to_save:
            self.restore_pixmap(self.current_widget_to_save)
        # self.dirtyRegion_manager.reset()
        # self.dirtyRegion = QRegion()
        # # 创建屏幕绘制器
        # painter = QPainter(self)
        
       
        

       

       

        # painter = QPainter(self)
        # try:
        #     painter.setRenderHint(QPainter.Antialiasing)
        #     painter.setPen(QPen(self.grid_color, 1))
            
            
        #     # 应用视图变换
        #     painter.translate(self.offset)
        #     painter.scale(self.scale_factor, self.scale_factor)
        #     window_rect = QRectF(QPointF(self.view_x0,self.view_y0),QPointF(self.view_x1,self.view_y1)).toRect()
        #     # painter.fillRect(window_rect, QColor("green"))
        #     if event.region().isEmpty():
        #         return

        #     update_region_view = QRegion()
        #     for rect in event.region():
        #         update_region_view += self.rect_windowToView(rect)

        #     toRepaint = self.dirtyRegion_manager.region().united( update_region_view)
        

            

        #     painter.setClipRegion(toRepaint)
        #     painter.setClipping(True)  # 显式启用裁剪
        #     # if not self.dirtyRegion_manager.isEmpty():
        #     #     painter.fillRect(window_rect, QColor("blue"))
            
           
        #     self.dirtyRegion_manager.reset()
        #     self.dirtyRegion = QRegion()
        #     # painter.save()
        #     # 绘制所有rect_element对象
        #     # 检查图片是否存在
            
        #     if self.show_bg_map:
        #         sence_left_top = self.sceneToView(5700*2*(self.grid_size  / self.scene_units_per_grid_x),13100*2*(self.grid_size  / self.scene_units_per_grid_x))
        #         target_rect = QRect(sence_left_top.x(), sence_left_top.y(), 13100*2*(self.grid_size  / self.scene_units_per_grid_x), 5700*2*(self.grid_size  / self.scene_units_per_grid_x))
        #         img_path = "res/map.png"

        #         if os.path.exists(img_path):
        #             pixmap = QPixmap(img_path)  # 加载图片
        #             if not pixmap.isNull():
        #                 # 在目标矩形内绘制图片（保持原始比例）
        #                 painter.drawPixmap(target_rect, pixmap)
        #             else:
        #                 print(f"图片加载失败: {img_path}")
        #         else:
        #             print(f"图片文件不存在: {img_path}")

            
            
        #     for child in  self.findChildren(base_element):
        #         child.check_hover(self.sence_pos_mouse)
        #         child.paint(painter,self.shine_flag)
           
        # painter.setClipping(False)  # 绘制完成后禁用裁剪

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # 恢复变换并重置所有变换
        painter.resetTransform()
        # 1. 绘制背景缓冲区
        painter.drawPixmap(0, 0, self.backing_store)
        # 2. 绘制动态缓冲区（图元）
        painter.drawPixmap(0, 0, self.dynamic_buffer)


        # painter = QPainter(self)
        # painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.grid_color, 1))
        # 应用视图变换
        painter.translate(self.offset)
        painter.scale(self.scale_factor, self.scale_factor)

        # if hasattr(self,"area") and  self.area:
        #     painter.drawRect(self.area)


        self.frame_select.paint(painter)

        #显示捕捉点
        if self.is_show_grid():
            self.__snap_sys_ref.draw_snap_indicator(painter,self.sceneToView)
        # painter.restore()

        #  建立时
        

        
        if self.current_element_id>0:
            child =self.current_element
            if isinstance(child, triangle_element):
                if child.get_actived():
                    self.draw_triangle_draft_on_sence(
                        painter,
                        child.get_draw_vertices(),
                        self.get_pos_from_mouse(),
                        child.get_color(),
                        child.get_line_width(),
                    )
            elif isinstance(child, circle_element):
                if  child.get_actived():
                    color = QColor(0,0,0)
                    if child.get_center_pos() is not None:
                        child.transfer_pos(self.sence_pos_mouse)
                        self.draw_line_on_sence(painter,child.get_center_pos(),self.sence_pos_mouse, dashed=True)
                        self.draw_circle_on_sence(painter,child.get_center_pos(),child.radius,color,child.get_fill(), dashed=True)
            elif isinstance(child, rect_element):
                if child.get_actived():
                    if child.constructed_by_draw:
                            child.transfer_pos(self.sence_pos_mouse)
                            color = child.get_color()
                    else:
                        child.move_to_pos(self.sence_pos_mouse.x(),self.sence_pos_mouse.y())
                        color = child.get_color()
                    if child.get_head_pos() is not None:
                        self.draw_rect_on_sence(painter, child.get_center_pos(), child.scene_size,child.m_angle,color,child.get_fill(),child.get_line_width(), dashed=True)
            elif isinstance(child, line_element):
                
                if child.get_actived():
                    color = QColor(0,0,0)
                    child.transfer_pos(self.sence_pos_mouse)
                    if child.get_head_pos() is not None:
                        head_pos = child.mapToScene(child.get_head_pos())
                        end_pos  = child.mapToScene(child.get_end_pos())
                        self.draw_line_on_sence(painter,head_pos,end_pos,color,child.get_line_width(), dashed=True)
                        # child.paint(painter,self.shine_flag)
            elif isinstance(child, text_element):
                
                if child.get_actived():                    
                    child.transfer_pos(self.sence_pos_mouse)
                    if child.get_center_pos() is not None:
                        center_pos = child.get_center_pos()
                        size       = child.getSize()
                        self.draw_text_on_sence(painter,center_pos,size,child.context,child.font_size, dashed=True)
            
            elif isinstance(child, image_element):
                
                if child.get_actived():                    
                    child.transfer_pos(self.sence_pos_mouse)
                    if child.get_center_pos() is not None:
                        center_pos = child.get_center_pos()
                        size       = child.getSize()
                        self.draw_image_on_sence(painter,center_pos,size, dashed=True)
        
        if self.__show_coordinate:
            # 恢复变换并重置所有变换
            painter.resetTransform()
            
            # 设置文本属性
            text_pen = QPen(Qt.black, 1)
            painter.setPen(text_pen)
            font = painter.font()
            font.setPixelSize(12)
            painter.setFont(font)
                
            # 绘制坐标轴标签
            left_edge =   self.viewToScene(self.view_x0,self.view_y0).x()
            right_edge =  self.viewToScene(self.view_x1,self.view_y1).x()
            top_edge =    self.viewToScene(self.view_x0,self.view_y0).y()
            bottom_edge = self.viewToScene(self.view_x1,self.view_y1).y()
            a=(right_edge-left_edge)/6.0
            b=(top_edge-bottom_edge)/6.0
            
            for i in range(5):
                painter.drawLine(0, self.height()//6*(i+1), 10, self.height()//6*(i+1))
                painter.drawText(QPointF(15, self.height()//6*(i+1)), f"{(left_edge+a*(i+1)):.1f}")
                
            for i in range(5):
                painter.drawLine(self.width()//6*(i+1), self.height(), self.width()//6*(i+1), self.height()-10)
                painter.drawText(QPointF(self.width()//6*(i+1), self.height() - 15), f"{(top_edge-b*(i+1)):.1f}")


            painter.setRenderHint(QPainter.Antialiasing)  # 抗锯齿
            # 设置画笔和填充
            painter.setPen(QPen(Qt.black, 2))
            painter.setBrush(QBrush(Qt.black))  # 填充箭头
            if not self.is_use_for_agv_map:
                painter.drawText(QPointF(70, self.height() - 25), "X")
                painter.drawText(QPointF(25, self.height() - 90), "Y")
                self.draw_arrow(painter, QPointF(15, self.height() - 20), QPointF(95, self.height() - 20), arrow_size=10)#x
                self.draw_arrow(painter, QPointF(15, self.height() - 20), QPointF(15, self.height() - 100), arrow_size=10)
            else:
                painter.drawText(QPointF(self.width()-80, self.height() - 25), "Y")
                painter.drawText(QPointF(self.width()-30, self.height() - 90), "X")
                self.draw_arrow(painter, QPointF(self.width()-15, self.height() - 20), QPointF(self.width()-95, self.height() - 20), arrow_size=10)#x
                self.draw_arrow(painter, QPointF(self.width()-15, self.height() - 20), QPointF(self.width()-15, self.height() - 100), arrow_size=10)

        painter.end()

        self._allow_update_data = True
        self._ready_for_update = True

    def show_element_id_when_select(self,painter:QPainter):
        painter.save()
        # children_id = set()
        for child in self.findChildren(base_element):
           

            # if child.get_selected() and (not child.is_in_group() or isinstance(child,group_element)):
            if child.get_selected():
                font = QFont("Arial", 10)  # 使用固定大字号
                font.setBold(True)
                sence_pos = child.get_scene_transformOriginPoint()

                text_pos = self.sceneToView(sence_pos)
                painter.setFont(font)
                painter.setPen(QColor(255,0,0))
                parent_id = child.m_parent.id() if child.m_parent else 0
                painter.drawText(text_pos, str(child.id()) +"["+str(parent_id)+"]")
                painter.drawEllipse(text_pos,2,2)

                # break
        painter.restore()

    def set_current_select_item(self,item_selected):
        if item_selected != self.current_selected:
            self.current_selected = item_selected
            self.selectionChanged.emit()

    def single_select_handle(self)->bool:
        """                """
        for item in self.findChildren(base_element):
            if item.get_selected() :
                item.set_selected(False)
        
        for item in self.scene_manager.m_sorted_items[::-1]:#从Z值最大处搜索
            if item.get_hover() and not item.is_in_group():
                item.set_selected(True)
                self.set_current_select_item(item)
                return True
        return False

    def double_click_select_handle(self)->bool:
        """                """
        if not hasattr(self,"select_flag"):
            setattr(self,"select_flag",False)
        else:
            self.select_flag = not self.select_flag
        item_record =None
        if self.select_flag:
            for item in self.scene_manager.m_sorted_items[::-1]:
                if item.get_selected() and item.get_hover():
                    item_record = item
                    break
            for item in self.scene_manager.m_sorted_items:
                if not item.get_selected() and item.get_hover():
                    item_record.set_selected(False)
                    item.set_selected(True)
                    self.set_current_select_item(item)   
                    return True
        else:
            for item in self.scene_manager.m_sorted_items:
                if item.get_selected() and item.get_hover():
                    item_record = item
                    break
            for item in self.scene_manager.m_sorted_items[::-1]:
                if not item.get_selected() and item.get_hover():
                    item_record.set_selected(False)
                    item.set_selected(True)
                    self.set_current_select_item(item)   
                    return True
        return False     if item_record is None else True

    def multi_select_handle(self):
        """                """
        for item in self.findChildren(base_element):
            if item.get_hover():
                item.set_selected(True)
                self.set_current_select_item(item)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """鼠标双击事件"""
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.LeftButton :
            if self._mode == SceneMode.Design:
                if False==self.double_click_select_handle():
                    self.set_current_select_item(self)#如果什么都没选中，则选中背景
        
        

    def mousePressEvent(self, event:QMouseEvent):
        """鼠标单击事件"""
        if event.modifiers() & Qt.ControlModifier:
            if event.button() == Qt.LeftButton:
                for child in self.findChildren(QObject):
                    if isinstance(child, base_element) :
                        if child.get_selected() and not child.is_has_parent():
                            child.set_m_pos_init(child.pos())
                if not hasattr(self,"sence_pos_mouse_save") :
                    setattr(self,"sence_pos_mouse_save",self.sence_pos_mouse) 
                else:
                    self.sence_pos_mouse_save =self.sence_pos_mouse
                if not hasattr(self,"move_flag"):
                    setattr(self,"move_flag",True) 
                else:
                    self.move_flag =True
            

            if self.current_selected is self:
                self.frame_select.receive_start_pos(self.sence_pos_mouse)

            return
       
        super().mousePressEvent( event)
        if event.button() == Qt.LeftButton:
            if event.modifiers() & Qt.ShiftModifier:
                self.multi_select_handle()
            else:
                if False== self.single_select_handle():
                    self.set_current_select_item(self)#如果什么都没选中，则选中背景
            # for child in self.findChildren(QObject):
            #     if isinstance(child, base_element) :
            #         # print(child.id(),child.get_actived(),child.get_hover(),child.is_in_group())
            #         if child.get_actived()==False and child.get_hover() and not child.is_in_group() :
            #             child.set_selected(not child.get_selected())
            

            # child=self.findChild(QObject,str(self.current_element_id))
            child = self.current_element if self.current_element_id>0 else None
            
            if isinstance(child, triangle_element):
                if child.get_actived():
                    points = child.get_draw_vertices()
                    if len(points) < 3:
                        child.add_draw_vertex(self.get_pos_from_mouse())
                        print(f"获得第{len(points) + 1}个点{self.get_pos_from_mouse()}")
                        self.update()

            elif isinstance(child, rect_element):
                if child.constructed_by_draw ==False:
                    print(child.constructed_by_draw)
                    child.set_actived(False)
                    child.completed()
                  
                else:
                    if child.get_actived():
                        if child.get_head_pos() is None:
                            #当吸附到捕捉点时，应用捕捉点
                            child.transfer_head_pos(self.get_pos_from_mouse()) 
                            print(f"获得第1个点{self.get_pos_from_mouse()}")
                        else:
                            print(f"获取第2个点{self.get_pos_from_mouse()}")
                            child.transfer_end_pos(self.get_pos_from_mouse())
                            

            elif isinstance(child, line_element):
                if child.get_actived():
                    if child.get_head_pos() is None:
                        child.transfer_head_pos(self.get_pos_from_mouse())
                        print(f"获得第1个点{self.get_pos_from_mouse()}")
                    else:
                        print(f"获取第2个点{self.get_pos_from_mouse()}")
                        child.transfer_end_pos(self.get_pos_from_mouse())
               
            elif isinstance(child, circle_element):
                if child.get_actived():
                    if child.get_center_pos() is None:
                        child.transfer_head_pos(self.get_pos_from_mouse())
                        print(f"获得第1个点{self.get_pos_from_mouse()}")
                    else:
                        print(f"获取第2个点{self.get_pos_from_mouse()}")
                        child.transfer_end_pos(self.get_pos_from_mouse())

            elif isinstance(child, text_element):
                if child.get_actived():
                    # if child.get_center_pos() is None:
                    child.transfer_head_pos(self.get_pos_from_mouse())
                    print(f"获得第1个点{self.get_pos_from_mouse()}")


            elif isinstance(child, image_element):
                if child.get_actived():
                    # if child.get_center_pos() is None:
                    child.transfer_end_pos(self.get_pos_from_mouse())
                    print(f"获得第1个点{self.get_pos_from_mouse()}")  

        elif event.button() == Qt.RightButton:
            if self.is_setting_group_pos:
                pass
               
            elif self.is_setting_father:
                for child in self.findChildren(QObject):
                    if isinstance(child, base_element) :
                        if child.get_hover() and not child.get_selected() and not child.is_in_group():
                            for item in self.selected_items:
                                item.setParentItem(child)
                                print("已设置父图元")
                            break

            elif self.is_setting_base_pos:
                for child in self.findChildren(QObject):
                    if isinstance(child, base_element) :
                        if  child.get_selected() and not child.is_in_group():
                            p = child.mapFromScene(self.sence_pos_mouse)
                            # print(p)
                            child.reSetTransformOriginPoint(self.sence_pos_mouse)
                            print("已设置基点")
                          
    def keyPressEvent(self, event: QKeyEvent):
        # print(f"Key pressed: {event.key()}, modifiers: {event.modifiers()}")
        
        # 检测 Ctrl 键是否按下
        if event.modifiers() & Qt.ControlModifier:
            self.CTRL_pressed_flag = True
            print("CTRL pressed")
        else:
            self.CTRL_pressed_flag = False
            # 处理其他按键
            if event.key() == Qt.Key_Escape:
                print("ESC pressed - clearing selection")
                self.clearSelection()
            elif event.key() == Qt.Key_Delete:
                print("Delete pressed - deleting selected items")
                self.deleteSelectedItems()
        
        event.accept()  # 明确接受事件
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        print(f"Key released: {event.key()}, modifiers: {event.modifiers()}")
        
        # 检测 Ctrl 键是否释放
        if event.key() == Qt.Key_Control:
            self.CTRL_pressed_flag = False
            self.frame_select.finish()
            print("CTRL released")
        
        event.accept()
        super().keyReleaseEvent(event)
   


    def clearSelection(self):
        """清除所有选中项"""
        for child in self.findChildren(QObject):
            if isinstance(child, base_element):
                child.set_selected(False)
        self.update()
        
    def deleteSelectedItems(self):
        """删除所有选中项""" 
        for child in self.findChildren(QObject):
            if isinstance(child, base_element) and child.get_selected():
                self.deleteItem(child)
        self.update()

        
    def mouseReleaseEvent(self, event):
        if not hasattr(self,"move_flag"):
            self.move_flag =False
        else:
            self.move_flag =False
        if not hasattr(self,"rotate_flag"):
            self.rotate_flag =False
        else:
            self.rotate_flag =False
        for child in self.findChildren(QObject):
            if isinstance(child, base_element) :
                if child.get_selected() and not child.is_has_parent():
                    child.set_m_pos_init(child.pos())


        if event.button() == Qt.LeftButton:
            print("松开鼠标左键")
            self.frame_select.finish()
        
        super().mouseReleaseEvent( event)
        
    def move_item_to_snap_pos(self,pos):
        """拖拽图元时能吸附到捕捉点"""
        for child in self.findChildren(base_element):
            if child.get_selected() and not child.is_has_parent() and self.CTRL_pressed_flag and self.move_flag:
                dpos = pos- self.sence_pos_mouse_save
                child.move_to_pos(dpos)
    
    def handle_mouse_move(self,event):
        if self._mode == SceneMode.Design:
            if event.modifiers() & Qt.ControlModifier and hasattr(self,"move_flag") and self.move_flag:
                for child in self.findChildren(QObject):
                    if isinstance(child, base_element) :
                        if child.get_selected() and not child.is_has_parent():
                            dpos = self.sence_pos_mouse - self.sence_pos_mouse_save
                            child.move_to_pos(dpos)

        super().mouseMoveEvent( event)
        if not self.CTRL_pressed_flag:
            
            self.update()
        else:
            self.frame_select.receive_end_pos(self.sence_pos_mouse)
        # self.update()

    def mouseMoveEvent(self, event):
        self.handle_mouse_move(event)
        self.mouse_moving_flag         =True
        self.__cousor_pos_locked  =     False
        if self.move_dog_need_feed:
            self.mouse_move_event_watcher.feed()
            self.move_dog_need_feed =False
        # current_time = time.time()*1000
        # if current_time -self.last_update_time>self.update_interval:
        #     self.last_update_time = current_time
        #     self.handle_mouse_move(event)
    
    def handle_mouse_wheel(self,event):
        super().wheelEvent(event)
        self.on_mouse_move(self.sence_pos_mouse)

    def wheel_watch_time_out(self):
        """滚轮不再活动"""
        self.CTRL_wheel_rolling   = False
        self.mouse_wheeling_flag  = False
        # self.ctrl_wheel_ang_diff =0 if hasattr(self,"ctrl_wheel_ang_diff") else setattr(self,"ctrl_wheel_ang_diff",0)
        # self.ctrl_wheel_ang_diff=0
        # print(f"watch dog timeout{self.ang_diff} ")
        # for child in self.findChildren(QObject):
        #     if isinstance(child, base_element) :
        #         if child.get_selected() and not child.is_has_parent():
        #             child.set_angle_init(child.get_angle())

    def mouse_move_watch_time_out(self):
        self.mouse_moving_flag   =False
        self.__cousor_pos_locked  = True
        self.mouse_not_move_signal.emit()

    def wheelEvent(self, event):
        self.mouse_wheeling_flag   = True
        if self.roll_dog_need_feed:
                self.wheel_event_watcher.feed()
                self.roll_dog_need_feed =False
        if event.modifiers() & Qt.ControlModifier:
            self.CTRL_wheel_rolling = True
            

            # if self.wheel_event_watcher.remainingTime()<100:
            if self._mode == SceneMode.Run:
                return
         
            
            for child in self.findChildren(QObject):
                if isinstance(child, base_element) :
                    if child.get_selected() and not child.is_in_group():
                        wheel_val = 0.5 if event.angleDelta().y() > 0 else -0.5
                        
                        # if hasattr(self,"ctrl_wheel_ang_diff") and self.ang_diff is not None:
                        #     self.ctrl_wheel_ang_diff = self.ctrl_wheel_ang_diff + wheel_val
                        
                        child.rotate_to_ang(wheel_val + child.get_angle_to_init() )
                
            return
        self.handle_mouse_wheel(event)
        if not self.CTRL_pressed_flag:
            self.update()


    


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("test")
        self.resize(1200, 800)
        self.test_window = myGraphicsScene(auto_redraw_when_mouse_move=True)
        
        self.setCentralWidget(self.test_window)
        self.test_window.setFocus()  # 确保场景获得焦点
        
    


if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow()
    window.show()
    window.move(100, 100)  # 确保窗口显示在可见位置
    app.exec()
