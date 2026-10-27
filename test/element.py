from __future__ import annotations

import copy
import json
import os,sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QTreeWidget, QTreeWidgetItem, QStackedWidget, QLabel, QFrame,QScrollArea,
    QListWidget, QListWidgetItem, QPushButton, QGroupBox,QColorDialog,QCheckBox,
    QTextEdit, QStyleFactory,QLineEdit
)
from PySide6.QtCore import Qt, QTimer, QEvent,QObject,QRegularExpression,QPointF,QPoint,QRect,Signal,QPropertyAnimation,QEasingCurve,Property,QSize,QRectF,QSizeF

from math import sin,cos ,atan,pi,sqrt
from typing import overload,Union,List,Optional,TYPE_CHECKING
from PySide6.QtGui import QFont,QColor, QPainter, QTransform, QRegion,QAction, QRegularExpressionValidator, QPalette,QPen,QPainterPath,QPainterPathStroker,QFontMetrics,QPixmap
from my_transform_v2 import Transform
import time
from my_common import SceneMode
if TYPE_CHECKING:
    from elements import group_element

def is_group_element(item) -> bool:
    """判断图元是否为 group_element

    element 与 elements 之间存在循环导入（elements 依赖 element），
    因此 group_element 只能在运行时延迟导入，不能放在模块顶层。
    """
    from elements import group_element
    return isinstance(item, group_element)

def color_to_str(color: QColor, format: str = 'hex') -> str:
    if   format == 'hex':
        return color.name()
    elif format == 'rgb':
        return f"{color.red()},{color.green()},{color.blue()}"
    elif format == 'rgba':
        return f"{color.red()},{color.green()},{color.blue()},{color.alpha()}"
    return ""

def str_to_color(color_str: str) -> QColor:
            if color_str.startswith('#'):  # 十六进制格式
                return QColor(color_str)
            elif ',' in color_str:         # RGB/RGBA格式
                parts = list(map(int, color_str.split(',')))
                if len(parts) == 3:
                    return QColor(*parts)
                elif len(parts) == 4:
                    return QColor(parts[0], parts[1], parts[2], parts[3])
            else:                          # 颜色名称
                return QColor(color_str)
            return QColor()  # 无效颜色

# class CloneableItem:
#     """可克隆图元接口"""
#     def clone(self, offset=QPointF(10, 10)):
#         """克隆图元并应用位置偏移"""
#         raise NotImplementedError("Subclasses must implement clone()")

class base_element(QObject):

    geometryChangeToChild = Signal()#告知子图元位置已改变

    # Interactive signals.  They are declared on the base class so every
    # element (and therefore every group instance) can be driven by the same
    # event-binding machinery.
    clicked  = Signal()
    pressed  = Signal()
    released = Signal()
    toggled  = Signal(bool)

    # geometryChangeToGroupParent = Signal()

    EVENT_ATTACH   = "attach"
    EVENT_CLICK    = "click"
    EVENT_PRESSED  = "pressed"
    EVENT_RELEASED = "released"
    EVENT_TOGGLE   = "toggle"
    EVENT_NAMES    = (
        EVENT_ATTACH,
        EVENT_PRESSED,
        EVENT_RELEASED,
        EVENT_CLICK,
        EVENT_TOGGLE,
    )

    def __init__(self,parent=None):
        super().__init__(parent=parent)
        self.__active = False
        self.__hover  = False
        self.__hover_last  = False
        self.__selected=False
        self.__fill  =False
        self.__opacity = 255
        self.__zValue  = 0   
        self.__done =False
        self.__moving_flag = False
        self.__is_moving = False
        self.__invisible = True #是否可见
        self.__selectable = True
        self.__selectable_last=True

        # Event bindings: {event_name: {"variable": str, "value": optional,
        # "handler": str, "args": dict}}.  ``value`` is omitted when the
        # event's own payload should be written (pressed=True, released=False,
        # click=True, toggle=current state).  A non-empty ``handler`` calls a
        # registered Python function instead of writing ``variable``.
        self._event_bindings = {}
        self._toggle_enabled = False
        self._checked = False
        self._pressed = False

        # self.m_items = items_map           # ID->图元映射字典
        self.type =None
        self.__width = 2
        self._color = QColor(0,0,0,255)
        # self.m_display_color = QColor(0,0,0)
        self._fill_color = QColor(0,255,0,255)
        self.last_update_time=0
        self.last_update_time_2=0
        self.update_interval =16
        #----------------------------------------------------------------------------------------
        self._group_id = 0  # 0表示无效ID
        self._m_id = 0  # 0表示无效ID
        self._name = ""
        # self._parent_id =0
        # self._children_ids=set()
        #----------------------------------------------------------------------------------------
        self._head_pos    = None
        self._end_pos     = None

        self._topLeft      = None
        self._bottomRight  = None
        self._topRight     = None
        self._bottomLeft   = None

        self._center_pos  = None

        self.scene_size = None
        #----------------------------------------------------------------------------------------
        self._head_pos_last =None
        self._scene_size_last =None

        #----------------------------------------------------------------------------------------
        self.m_pos        = QPointF(0,0)  #在父坐标系的位置
        self.m_transform  = Transform()   #
        self.m_origin     = QPointF(0,0)  #变换原点
        self.m_parent     = None          #父图元的引用
        self.m_children   = set()
        self.m_parent_id      = 0          
        self.m_children_ids   = set()
        self.m_angle          = 0   #全局角度
        self.not_normalize_angle = 0
        self.m_dirty_flag        = False
        #-----------------------------------------------------------------------------------------
        self.m_pos_init        = QPointF(0,0)  #在父坐标系的位置
        self.m_angle_init      =0  #记录构建图元时的初始角度

        #-----------------------------------------------------------------------------------------
        self._head_pos_last_scene        = QPointF(0,0)  #在父坐标系的位置
        self._end_pos_last_scene        = QPointF(0,0)  #在父坐标系的位置
        # self._m_pos_last                 =None
        self._Transform_last             =Transform()
        #-----------------------------------------------------------------------------------------
        # 变换缓存：m_pos/m_transform/父链不变时直接复用，避免每帧重算纯 Python 矩阵
        self._tf_self_epoch   = 0      # 自身几何版本号（m_transform 变化时 +1）
        self._tf_item_cache   = None   # itemTransform() 缓存
        self._tf_item_key     = None   # (m_pos.x, m_pos.y, _tf_self_epoch)
        self._tf_scene_cache  = None   # sceneTransform() 缓存
        self._tf_scene_parent = None   # 生成该缓存时父项返回的变换对象
        self._tf_scene_own    = None   # 生成该缓存时自身的 itemTransform 对象
        #-----------------------------------------------------------------------------------------
        self._is_group_in_hover =False
       
        self._sceneBoundingRect = QRectF()
        self._select_sceneBoundingRect = QRectF()

        self.m_scene =None#场景引用
        self.m_scene_manager =None#场景管理器引用
        self.m_this_frame_flag = False
        self.m_this_frame_flag_2 = False
        self.m_veiw_dirty_region =QRegion()

    def set_dirty_region(self,dirty_region):
        self.m_veiw_dirty_region = dirty_region
  
    def set_group_in_hover(self,enable):
        if self.__selectable == False:
            self._is_group_in_hover = False
            return
        self._is_group_in_hover = enable

    def get_scene_head_pos(self):
        return self.mapToScene(self._head_pos)
    def get_scene_end_pos(self):
        return self.mapToScene(self._end_pos )
    def get_scene_center_pos(self):
        return self.mapToScene(self._center_pos)
    def get_scene_OriginPoint(self):
        return self.mapToScene(self.m_origin)

    def prepareGeometryChange(self):
        """图元边界变化前调用"""
        if self.m_scene :
            if not self.m_this_frame_flag :
                self.m_scene.item_GeometryChange.emit(self)

                self.m_this_frame_flag =True
    
    def prepareDirtyChange(self):
        if self.m_scene :
            if not self.m_this_frame_flag_2 :
                self.m_scene.item_DirtyChange.emit(self)
                self.m_this_frame_flag_2 =True

    def set_scene_ref(self,scene):
        self.m_scene =scene
        self.m_scene.shine_flag_change.connect(self.handle_shine_flag)
        # print(self.m_scene)
    def handle_shine_flag(self):
        current_time = time.time()*1000
        if self.__selected:
            
            # print(current_time -self.last_update_time_2)
            if current_time -self.last_update_time_2 > 1000:
                self.prepareDirtyChange()
          

    def set_scene_manager_ref(self,scene_manager):
        self.m_scene_manager =scene_manager
        # print(self.m_scene_manager)

    def get_angle(self):
        return self.m_angle
    
    def set_angle(self,ang):
        self.m_angle =ang

    def set_angle_init(self,ang):
        self.m_angle_init =ang

    def get_angle_init(self):
        return self.m_angle_init
    
    def get_angle_to_init(self):
        return self.m_angle-self.m_angle_init
    
    def set_m_pos_init(self,pos):
        self.m_pos_init =pos

    def get_m_pos_init(self):
        return self.m_pos_init
    
    def is_has_child(self):
        return len(self.m_children )>0
    
    def is_has_parent(self):
        return self.m_parent is not None
    
    def parentItem(self):
        return self.m_parent
    def childItems(self):
        return self.m_children

    def _reset_moving_flag(self):
        self.__moving_flag = False
    def is_moving(self):
        return self.__is_moving
    
    def update_boundingRect(self):
        """子类实现 ,钩子"""
        self.__moving_flag = True

        self.prepareDirtyChange()
        current_time = time.time()*1000

        self.last_update_time_2 = current_time
       
   
    
    def __check_position_change(self):#__check_local_geometry_change

        current_transform = self.sceneTransform()
        # 缓存命中时是同一个对象，先用身份判断短路，避免 9 次浮点比较
        if self._Transform_last is not current_transform and self._Transform_last != current_transform:

            self.update_boundingRect()

        self._Transform_last  = current_transform

    def pos(self)->QPointF:
        """获取位置"""
        return self.m_pos
    
    def setPos(self, *args):
        """设置位置"""
        pos = QPointF()
        if   len(args) == 1:  # QPoint输入
            # pos = args[0]
            x, y = args[0].x(),args[0].y()
            pos.setX(x) 
            pos.setY(y) 
        elif len(args) == 2:  # x,y坐标输入
            x, y = args
            pos.setX(x) 
            pos.setY(y) 
        else:
            raise ValueError("参数必须是(x,y)或QPointF")
        
        if not self.m_parent and not self.is_in_group():
            # self.__check_position_change()
            pass
        else:
            return
        self.m_pos =pos
        self.invalidate_transform_cache()

    def handle_parent_move(self):
        """父图元位置变化"""
        # self.__check_position_change()
        self.update_boundingRect()

    def setRotation(self,ang):
        self.m_transform.rotate_around(ang,self.m_origin)
        # m_transform 是原地修改，必须让变换缓存与下一帧重绘生效
        self.invalidate_transform_cache()
        # self.__check_position_change()
    
    def transform(self):
        """获取变换矩阵"""
        return self.m_transform
    
    def setTransform(self, transform):
        """设置变换矩阵"""
        self.m_transform = transform
        self.invalidate_transform_cache()
        if not self.m_parent and self.__active==False:
            self.__check_position_change()
    
    def transformOriginPoint(self):
        """获取变换原点"""
        return  QPointF(self.m_origin)
    def get_scene_transformOriginPoint(self):
        return self.mapToScene(self.m_origin)
    
    def setTransformOriginPoint(self,  *args):
        """设置变换原点"""
        pos = QPointF()
        if len(args) == 1:    # QPoint输入
            pos = args[0]
        elif len(args) == 2:  # x,y坐标输入
            x, y = args
            pos.setX(x) 
            pos.setY(y) 
        else:
            raise ValueError("参数必须是(x,y)或QPointF")
        
        self.m_origin =pos
        
        # print(f"设置初始的转中心{pos}")
   
    def reSetTransformOriginPoint(self,  *args):#group变动之后执行会出错
        """设置变换原点"""
        if self.m_parent is not None :
            print("图元已存在父图元")
            return
        pos = QPointF()
        if len(args)   == 1:    # QPoint输入
            pos = args[0]
        elif len(args) == 2:    # x,y坐标输入
            x, y = args
            pos.setX(x) 
            pos.setY(y) 
        else:
            raise ValueError("参数必须是(x,y)或QPointF")
        
        self.m_origin = self.mapFromScene(pos)
        self.m_angle_init = self.m_angle 
        print(f"设置新的转中心 {self.m_origin}")


    def parentItem(self):
        """获取父图形项"""
        return self.m_parent
    
    
    def __check_generation(self, parent_id):
        if self.is_has_child():
            for child in self.m_children:
                if child.id() == parent_id:
                    print("不能将子孙图元设成父图元")
                    return True
                if child.__check_generation(parent_id):
                    return True
        return False
    def setParentItem(self, parent):
        """设置父图形项 后继承变换
        +pos_scene x M独  = Tr独
        M独 =(-pos_scene)x Tr全 =((-pos_scene)xTr父)xTr子
        """
        
        if self.m_parent:
            print("图元已存在父对象")
            return
        # if self.is_has_child():
        #     for child in self.m_children:
        #         if child.id()== parent.id():
        #             print("不能将子图元设成父图元")
        #             return
        if True==self.__check_generation(parent.id()):
            return
            
        A = Transform().translate(-self.m_pos) * self.sceneTransform() #M独

        
        self.m_parent = parent
        m_pos_in_parent  = self.m_parent.mapFromScene(self.m_pos)
        # self._parent_id = parent.id()
        # parent.add_child_id(self.id())
        parent.m_children.add(self)

        parent_transform  = parent.sceneTransform()
       
        B = (Transform().translate(-self.m_pos))*parent_transform
        t = B.inverted() *A
        t = Transform().translate(-m_pos_in_parent)*t
        
        # t= parent_transform*A
        # t = Transform().translate(-m_pos_in_parent)*t
        self.setTransform(t)
        self.m_pos      = m_pos_in_parent
        self.m_pos_init =copy.deepcopy(self.m_pos)
        self.invalidate_transform_cache()

        print("设置父对象")
        
        # print(self.m_pos,m_pos_in_parent)
       

        # self.m_parent.geometryChangeToChild.connect(self.handle_parent_move)
        # if isinstance(self.m_parent)
        # if self.m_parent.type=="group":
        # self.m_parent.group_positon_change_signal.connect(self.handle_parent_move)



        print(parent.id(),parent.m_children)

    def removeParentItem(self, force=False):
        """移除父图元后继承变换
        
        （-pos_scene）x Tr全 = M独
        """
        if self.m_parent is None :
            return   
        if self.is_in_group() and force==False:
            return
        
        # self.m_parent.geometryChangeToChild.disconnect(self.handle_parent_move)

        global_transform  = self.sceneTransform()#子全变换
        m_pos_on_scene    = self.mapToScene(self.m_pos)

        t = Transform().translate(-m_pos_on_scene)

        t = t*(global_transform)#全局变换 = 
        self.setTransform(t)

        self.m_pos      = m_pos_on_scene
        self.m_pos_init = copy.deepcopy(self.m_pos)
       
        self._group_id  = 0
      
        self.m_parent.m_children.remove(self)
        self.m_parent   = None
        self.invalidate_transform_cache()

    def Delete(self):
        """Remove this element, together with everything it owns, from the scene.

        Elements that still had children used to be skipped entirely, so a
        selected group could not be deleted at all (right-click → 删除 did
        nothing).  Members are detached first so every one of them takes the
        regular manager-aware delete path; nested groups recurse.
        """

        if self.is_has_parent():
            return
        manager = self.m_scene_manager
        if manager is not None and self.id() not in manager.m_items:
            # Already removed: a group deletes its members before the caller
            # finishes walking over the selection.
            return

        if self.is_has_child():
            for child in list(self.m_children):
                child.removeParentItem(True)
                child.set_selected(False)
                child.Delete()
            self.m_children.clear()

        try:
            self.m_scene.shine_flag_change.disconnect(self.handle_shine_flag)
        except (RuntimeError, TypeError):
            pass
        self.m_scene_manager.delete_item_signal.emit(self)

    def setChildItem(self,child):
        child.setParentItem(self)
    
    def removeChildItem(self,child,force=False):
        child.removeParentItem(force)

    def removeChildsItem(self):
        """解除父子关系，force=True时包含group"""
        if not self.is_has_child():
            return
        
        
        children_lst =   list( self.m_children)
        for child in children_lst:

            if is_group_element(child):
                child.removeParentItem()
            else:
                if child.is_has_child():
                    child.removeChildsItem()
                else:
                    child.removeParentItem()
                
        print(f"已解除id{self.id()}下的子项")

    
        


    def invalidate_transform_cache(self, mark_dirty=True):
        """几何变化后调用：丢弃变换缓存，并让 mapToScene / 下一帧绘制使用新变换。

        位置(m_pos)本身由 itemTransform() 的取值校验覆盖，任何直接给 m_pos
        赋值的代码无需通知；本方法主要处理 m_transform 的原地修改（旋转）、
        父链变化以及“必须立刻重绘”的场合。

        mark_dirty=False 用于紧跟着还会调用 update_boundingRect() 的赋值，
        避免重复发脏区域信号。
        """
        self._tf_self_epoch += 1
        self._tf_item_cache = None
        self._tf_item_key = None
        self.__moving_flag = True
        if mark_dirty:
            self.prepareDirtyChange()

    def itemTransform(self):
        """
        计算从图元局部坐标系到父坐标系的变换（带缓存）

        m_pos 用坐标值做键，所以任何直接给 m_pos 赋值的代码（move_by、
        change_position 等）都能被正确感知；m_transform 的原地修改需要
        调用 invalidate_transform_cache()。
        """
        pos = self.m_pos
        key = (pos.x(), pos.y(), self._tf_self_epoch)
        if self._tf_item_key != key:
            # 创建基础变换
            t = Transform()
            t = t.translate(pos)
            # 2. 应用局部变换
            t = t*self.m_transform 
            self._tf_item_cache = t
            self._tf_item_key = key
        return self._tf_item_cache
    
    def sceneTransform(self):
        """
        计算从图元局部坐标系到场景坐标系的变换（带缓存）

        失效依据是“父项返回的变换对象”和“自身的 itemTransform 对象”的身份：
        itemTransform() 自身变化时会返回新对象，父项的父链变化时父项也会重算，
        因此子图元无需任何显式通知即可惰性刷新（直接改 m_pos 也能被感知）。
        """
        own_transform = self.itemTransform()
        parent = self.m_parent
        if parent is None:
            # 没有父项时，场景变换就是本图元的项变换
            if self._tf_scene_cache is not own_transform:
                self._tf_scene_cache = own_transform
            return self._tf_scene_cache

        # 先让父项校验它自己是否需要重算
        parent_transform = parent.sceneTransform()
        if self._tf_scene_parent is not parent_transform or self._tf_scene_own is not own_transform:
            # 组合变换: 父项的场景变换 × 本图元的项变换
            self._tf_scene_cache = parent_transform * own_transform
            self._tf_scene_parent = parent_transform
            self._tf_scene_own = own_transform
        return self._tf_scene_cache
    
    def mapToParent(self, point):
        """将点从局部坐标系映射到父坐标系"""
        return self.itemTransform().map(point)
    
    def mapToScene(self, point):
        """将点从局部坐标系映射到场景坐标系

        sceneTransform() 自带缓存且会按 m_pos 校验，因此这里总是用实时变换，
        不再依赖 _Transform_last 这个“上一帧快照”（轮询取消后它可能滞后）。
        """
        self.__is_moving = self.__moving_flag
        return self.sceneTransform().map(point)
    
    def mapFromParent(self, point):
        """将点从父坐标系映射到局部坐标系"""
        # 计算逆变换
        inv_transform = self.itemTransform().inverted()
        return inv_transform.map(point)
    
    def mapFromScene(self, point):
        """将点从场景坐标系映射到局部坐标系"""
        # 计算逆变换
        inv_transform = self.sceneTransform().inverted()
        return inv_transform.map(point)
    
    def __str__(self):
        """字符串表示"""
        return (f"MyGraphicsItem(\n"
                f"  Position: ({self.m_pos.x():.2f}, {self.m_pos.y():.2f})\n"
                f"  Origin: ({self.m_origin.x():.2f}, {self.m_origin.y():.2f})\n"
                f"  Transform: {self.m_transform}\n"
                # f"  Parent: {self.m_parent.id()}\n"
                # f"  children:{self.m_children}\n"
                f"  type:{self.type}"
                ")\n")
    def completed(self,construct_from_dict=False):
       
        self.update_boundingRect()
      
        print(f"图元{self.id()}构建完成,bound{self._sceneBoundingRect}")

        
        self.m_scene_manager.completed_item_signal.emit(self,construct_from_dict)
        self.set_actived(False)
        
      
        

    def move_by(self,*args):
        pos = QPointF()
        if len(args) == 1:  # QPoint输入
            pos = args[0]
        elif len(args) == 2:  # x,y坐标输入
            x, y = args
            pos.setX(x) 
            pos.setY(y) 
        else:
            raise ValueError("参数必须是(x,y)或QPointF")
        self.m_pos = self.m_pos + pos
        # 拖动/成组移动只改 m_pos，必须自己发脏区域，不能再依赖渲染定时器轮询
        self.invalidate_transform_cache()

    def move_to_pos(self,*args):
        pos = QPointF()
        if len(args) == 1:  # QPoint输入
            pos = args[0]
        elif len(args) == 2:  # x,y坐标输入
            x, y = args
            pos.setX(x) 
            pos.setY(y) 
        else:
            raise ValueError("参数必须是(x,y)或QPointF")
        offset =  self.m_pos_init + pos
        self.setPos(offset)

    @classmethod
    def normalize_angle(cls,angle: float) -> float:
        """将任意浮点数规范化为[0.0, 360.0)的角度值"""
        return angle % 360.0

    def rotate_to_ang(self,ang):
        # if self.is_in_group() and not isinstance(self,group_element):
        #     return
        target_ang  = base_element.normalize_angle(ang+self.m_angle_init)
        # normalize_ang=        base_element.normalize_angle(ang)+self.m_angle_init

        offset = target_ang  - self.m_angle
        if  not target_ang==self.m_angle:
            self.setRotation(offset)
            # self.__check_position_change()
        self.m_angle = target_ang
        
       
    # # 查找图元
    # def findItem(self, id):
    #     return self.m_items.get(id, None)
    
    def id(self):
        return self._m_id

    # 反序列化专用（禁止普通创建调用）
    def setID(self, id):
        assert self._m_id == 0, "ID can only be set once"
        self._m_id = id
        self.setObjectName(self.type + str(id))

    def get_head_pos(self):
        return self._head_pos
    def get_end_pos(self):
        return self._end_pos
    def get_center_pos(self):
        return self._center_pos
    def set_head_pos(self,pos:QPointF):
        self._head_pos =pos
    def set_center_pos(self,pos:QPointF):
        self._center_pos =pos
    def set_end_pos(self,pos:QPointF):
        self._end_pos =pos

    def get_scene_head_pos(self):
        return self.mapToScene(self._head_pos)
    def get_scene_end_pos(self):
        return self.mapToScene(self._end_pos)
    def get_scene_center_pos(self):
        return self.mapToScene(self._center_pos)
    
    def get_scene_topRight(self):
        return self.mapToScene(self._topRight)
    def get_scene_bottomLeft(self):
        return self.mapToScene(self._bottomLeft)
    def get_scene_topLeft(self):
        return self.mapToScene(self._topLeft)
    def get_scene_bottomRight(self):
        return self.mapToScene(self._bottomRight)
    
    def get_min_x(self):
        points = []
        points.append(self.get_scene_topRight())
        points.append(self.get_scene_bottomLeft())
        points.append(self.get_scene_topLeft())
        points.append(self.get_scene_bottomRight())
        a =points[0].x()
        for pos in points:
            if a > pos.x():
                a = pos.x()
        return a

    def get_max_x(self):
        points = []
        points.append(self.get_scene_topRight())
        points.append(self.get_scene_bottomLeft())
        points.append(self.get_scene_topLeft())
        points.append(self.get_scene_bottomRight())
        a =points[0].x()
        for pos in points:
            if a < pos.x():
                a = pos.x()
        return a
    
    def get_min_y(self):
        points = []
        points.append(self.get_scene_topRight())
        points.append(self.get_scene_bottomLeft())
        points.append(self.get_scene_topLeft())
        points.append(self.get_scene_bottomRight())
        a =points[0].y()
        for pos in points:
            if a > pos.y():
                a = pos.y()
        return a

    def get_max_y(self):
        points = []
        points.append(self.get_scene_topRight())
        points.append(self.get_scene_bottomLeft())
        points.append(self.get_scene_topLeft())
        points.append(self.get_scene_bottomRight())
        a =points[0].y()
        for pos in points:
            if a < pos.y():
                a = pos.y()
        return a
    
    def get_name(self):
        return self._name
    def _set_name(self,name)->bool:
        """反序列化使用"""
        self._name =name
        # self.m_scene_manager.m_name_items[name] = self.id()
    def construct_name_items(self):
        self.m_scene_manager.m_name_items[self._name] = self.id()
           
    def set_name(self,name)->bool:
        """重命名图元并同步 ``m_name_items``。

        名字是名字表的全局键，所以重名（属于别的图元）或空名字都会被拒绝。
        以前遇到重名时不改名却返回 True，界面上看起来就是“名字改不了”，
        现在返回 False，让属性面板能提示并恢复原来的名字。
        """
        name = str(name)

        manager = self.m_scene_manager
        if manager is None:
            self._name = name
            return True

        if not name:
            return False

        if name == self._name:
            return True

        owner = manager.m_name_items.get(name)
        if owner is not None and owner != self.id():
            return False

        manager.m_name_items.pop(self._name, None)
        self._name = name
        manager.m_name_items[name] = self.id()
        return True

    def _rename_item(self, name) -> bool:
        """Rename the element and keep ``m_name_items`` in sync.

        Group bookkeeping renames members when a group is created, renamed or
        dissolved.  It uses this helper instead of :meth:`set_name` because it
        must not trigger subclass hooks and because a name that is already
        taken is resolved with a numeric suffix instead of silently keeping
        the old name.
        """

        name = str(name)
        manager = self.m_scene_manager
        if manager is None:
            self._name = name
            return True

        if name == self._name:
            return True

        candidate = name
        index = 1
        while (
            candidate in manager.m_name_items
            and manager.m_name_items[candidate] != self.id()
        ):
            candidate = f"{name}_{index}"
            index += 1

        if self._name:
            manager.m_name_items.pop(self._name, None)
        self._name = candidate
        manager.m_name_items[candidate] = self.id()
        return True

    # ------------------------------------------------------------------
    # Event bindings
    # ------------------------------------------------------------------
    @classmethod
    def normalize_event_name(cls, event):
        """Return the canonical event key, or ``None`` for an unknown event."""
        key = str(event or "").strip().lower()
        aliases = {
            "attach": cls.EVENT_ATTACH,
            "init": cls.EVENT_ATTACH,
            "initial": cls.EVENT_ATTACH,
            "click": cls.EVENT_CLICK,
            "clicked": cls.EVENT_CLICK,
            "press": cls.EVENT_PRESSED,
            "pressed": cls.EVENT_PRESSED,
            "release": cls.EVENT_RELEASED,
            "released": cls.EVENT_RELEASED,
            "toggle": cls.EVENT_TOGGLE,
            "toggled": cls.EVENT_TOGGLE,
        }
        return aliases.get(key)

    def set_event_binding(
        self, event, variable, value=None, handler="", args=None
    ):
        """Bind ``event`` to a variable write or a registered handler.

        An empty variable and handler removes the binding.  When ``value`` is
        empty the event payload is written: pressed=True, released=False,
        click=True, toggle=the new checked state.

        ``handler`` names a function registered by the run-mode host.  When it
        is present the function runs instead of writing ``variable``; ``args``
        is the JSON object passed to it.  Page files therefore never contain
        executable Python, only a handler name and data.
        """
        event_name = self.normalize_event_name(event)
        if event_name is None:
            raise ValueError(f"不支持的事件: {event!r}")

        variable = str(variable or "").strip()
        handler = str(handler or "").strip()
        if not variable and not handler:
            self._event_bindings.pop(event_name, None)
            return False

        binding = {}
        if variable:
            binding["variable"] = variable
        if handler:
            binding["handler"] = handler
        if value is not None and str(value).strip() != "":
            binding["value"] = value
        if handler and args is not None:
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = None
            if isinstance(args, dict) and args:
                binding["args"] = copy.deepcopy(args)

        self._event_bindings[event_name] = binding
        if event_name == self.EVENT_TOGGLE:
            # Binding a toggle event is only useful when clicks actually
            # flip the state, so enable it as part of the binding.
            self._toggle_enabled = True
        return True

    def get_event_binding(self, event):
        event_name = self.normalize_event_name(event)
        binding = self._event_bindings.get(event_name)
        return copy.deepcopy(binding) if binding is not None else None

    def get_event_bindings(self):
        return copy.deepcopy(self._event_bindings)

    def clear_event_binding(self, event):
        event_name = self.normalize_event_name(event)
        if event_name is not None:
            self._event_bindings.pop(event_name, None)

    def apply_event_bindings(self, data):
        """Restore bindings from serialized JSON data."""
        self._event_bindings.clear()
        if not isinstance(data, dict):
            return
        for event, binding in data.items():
            try:
                if isinstance(binding, dict):
                    self.set_event_binding(
                        event,
                        binding.get("variable"),
                        binding.get("value"),
                        binding.get("handler", ""),
                        binding.get("args"),
                    )
                elif isinstance(binding, str):
                    self.set_event_binding(event, binding)
            except ValueError:
                # Ignore future/unknown events instead of breaking page load.
                continue

    def event_bindings_to_dict(self):
        return copy.deepcopy(self._event_bindings)

    def has_event_bindings(self):
        return bool(self._event_bindings)

    def set_toggle_enabled(self, enable):
        self._toggle_enabled = bool(enable)

    def is_toggle_enabled(self):
        return self._toggle_enabled

    def set_checked(self, checked):
        checked = bool(checked)
        if self._checked != checked:
            self._checked = checked
            self.prepareDirtyChange()

    def is_checked(self):
        return self._checked

    def is_pressed(self):
        return self._pressed

    @staticmethod
    def parse_event_value(raw):
        """Convert the text stored by the property panel into a runtime value."""
        if isinstance(raw, (bool, int, float)):
            return raw
        text = str(raw).strip()
        lowered = text.lower()
        if lowered in {"true", "1", "on", "yes"}:
            return True
        if lowered in {"false", "0", "off", "no"}:
            return False
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            return text

    def _dispatch_event_binding(self, event, event_value):
        event_name = self.normalize_event_name(event)
        binding = self._event_bindings.get(event_name)
        if not binding:
            return

        handler = str(binding.get("handler", "")).strip()
        if handler:
            scene = self.m_scene
            invoker = (
                getattr(scene, "invoke_event_handler", None)
                if scene is not None
                else None
            )
            if callable(invoker):
                invoker(
                    handler,
                    self,
                    event_name,
                    binding.get("args") or {},
                    event_value,
                )
            else:
                print(f"[事件绑定] 场景未安装事件处理函数解析器: {handler}")
            return

        variable = str(binding.get("variable", "")).strip()
        if not variable:
            return

        raw_value = binding.get("value")
        if raw_value is None or str(raw_value).strip() == "":
            value = event_value
        else:
            value = self.parse_event_value(raw_value)

        scene = self.m_scene
        writer = getattr(scene, "write_variable", None) if scene is not None else None
        if callable(writer):
            writer(variable, value, self, event_name)

    def _emit_event(self, event, event_value):
        event_name = self.normalize_event_name(event)
        if event_name == self.EVENT_CLICK:
            self.clicked.emit()
        elif event_name == self.EVENT_PRESSED:
            self.pressed.emit()
        elif event_name == self.EVENT_RELEASED:
            self.released.emit()
        elif event_name == self.EVENT_TOGGLE:
            self.toggled.emit(bool(event_value))
        self._dispatch_event_binding(event_name, event_value)

    def handle_mouse_press(self):
        if self._pressed:
            return
        self._pressed = True
        self._emit_event(self.EVENT_PRESSED, True)

    def cancel_mouse_press(self):
        """Drop a pressed state without emitting release/click events."""
        self._pressed = False

    def _next_toggle_state(self):
        """Flip the bound runtime variable when possible, else the local state."""
        binding = self._event_bindings.get(self.EVENT_TOGGLE)
        if binding:
            variable = str(binding.get("variable", "")).strip()
            scene = self.m_scene
            reader = getattr(scene, "read_variable", None) if scene else None
            if variable and callable(reader):
                current = reader(variable, self._checked)
                if isinstance(current, str):
                    current = self.parse_event_value(current)
                return not bool(current)
        return not self._checked

    def toggle(self):
        """Programmatically toggle the checked state (when enabled)."""
        if not self._toggle_enabled:
            return
        self.set_checked(self._next_toggle_state())
        self._emit_event(self.EVENT_TOGGLE, self._checked)

    def handle_mouse_release(self, inside=True):
        if not self._pressed:
            return
        self._pressed = False
        # A released event always represents the "not pressed" value.  The
        # ``inside`` flag only decides whether click/toggle also fire.
        self._emit_event(self.EVENT_RELEASED, False)
        if not inside:
            return
        self._emit_event(self.EVENT_CLICK, True)
        self.toggle()

    def get_line_width(self):
        return  int(self.__width)
    def set_line_width(self, val):
        if val!=self.__width:
            self.__width =val
            self.prepareDirtyChange()

    def set_color(self,color):
        c = QColor(color.red(),color.green(),color.blue(),self.__opacity)
        if self._color!=c:
            self._color = c
            self.prepareDirtyChange()

    def get_color(self):
        color = QColor(self._color.red(),self._color.green(),self._color.blue())
        return  color
    
    def set_fill_color(self,color):
        c = QColor(color.red(),color.green(),color.blue(),self.__opacity)
        if self._fill_color!=c:
            self._fill_color = c
            self.prepareDirtyChange()
     
    def get_fill_color(self):
        color = QColor(self._fill_color.red(),self._fill_color.green(),self._fill_color.blue())
        return  color
    
    def is_in_group(self):
        if self._group_id>0:
            return True
        return False
    
    def is_done(self):
        return self.__done==True
    
    def set_group_id(self,val):
        self._group_id = val

    def get_group_id(self):
        return self._group_id
    
    def get_group_name(self):
        return self._group_name
    def set_group_name(self,str):
        self._group_name =str

    def get_opacity(self):
        return self.__opacity
    def set_opacity(self,val):
        if 0<val<=255:
            self.__opacity =val
            self._color.setAlpha(self.__opacity)
            self._fill_color.setAlpha(self.__opacity)

    def set_selected_anyway(self,child,state):
        self.__selected =  state

    def set_selected(self,state):
        if self.__selectable:
            self.__selected =  state

        # if self.is_has_child():
        #     for child in self.m_children:
        #         child.set_selected(state)
              
    def get_selected(self):
        return self.__selected==True
    
    def set_actived(self,state):
        self.__active = state

    def get_actived(self):
        return self.__active==True

    def set_fill(self,state):
        if state != self.__fill:
            self.__fill = state
            self.prepareDirtyChange()
    
    def get_fill(self):
        return self.__fill==True
    
    def set_hover(self,state):
        if self.__hover!=state:
            self.__hover = state
    def get_hover(self):
        return self.__hover==True
    
    def zValue(self):
        return self.__zValue
    def set_zValue(self,value):
        self.__zValue = value
        if self.__active==False:
            self.m_scene_manager.sort_items_by_zValue()

    def get_visibility(self):
        return self.__invisible
    
    def set_visibility(self,enable):
        if self.is_has_parent() and self.m_parent.get_visibility() == False and enable:
            return
       
        if self.__invisible != enable:
            self.prepareDirtyChange()
            self.__invisible = enable
            if not enable:
                self.__selectable_last = self.__selectable
                self.__selectable=False
            else:
                self.__selectable = self.__selectable_last

    def get_selectable(self):       
        return self.__selectable

    def set_selectable(self,enable):
        if enable != self.__selectable:
            self.__selectable_last=self.__selectable=enable
    
    def check_hover(self,mouse_pos:QPointF):
        if self.__hover_last!=self.__hover:
            if self.is_in_group() or is_group_element(self):
                self.m_scene.hover_sta_change.emit(self)
        self.__hover_last  = self.__hover
        
    def sceneBoundingRect(self):
        return self._sceneBoundingRect

    def contains_scene_pos(self, scene_pos):
        """Return whether ``scene_pos`` is inside this element.

        Run-mode group click handling uses this instead of Qt's
        ``QGraphicsItem.contains`` because the custom elements do not derive
        from ``QGraphicsItem``.  The cached scene bounding rect is enough for
        groups and is refreshed by ``update_boundingRect`` after moves.
        """

        if scene_pos is None or not self.get_visibility():
            return False

        rect = self._sceneBoundingRect
        if isinstance(rect, QRectF) and rect.contains(scene_pos):
            return True

        # Fallback for an element whose cached scene rect is stale: convert
        # the point into local coordinates and test the element geometry.
        if self.scene_size is None:
            return False
        if self._head_pos is None or self._end_pos is None:
            return False
        try:
            local_pos = self.mapFromScene(scene_pos)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        local_rect = QRectF(self._head_pos, self._end_pos).normalized()
        return local_rect.contains(local_pos)

    def viewBoundingRect(self):
        return self.m_scene.rect_sceneToView(self._sceneBoundingRect)
    def selectViewBoundingRect(self):
        return self.m_scene.rect_sceneToView(self._select_sceneBoundingRect)

    def windowBoundingRect(self):
        return self.m_scene.rect_viewToWindow( self.viewBoundingRect() )
    
    def check_moving(self):
        self._reset_moving_flag()
        self.__check_position_change()
    def paint(self,painter:QPainter,shine_flag:bool):
        # if self.__selected and (not self.is_in_group() or isinstance(self,group_element)):
        if self.__selected and self.__invisible:
            font = QFont("Arial", 10)  # 使用固定大字号
            font.setBold(True)
            sence_pos = self.get_scene_transformOriginPoint()

            text_pos = self.m_scene.sceneToView(sence_pos)
            painter.setFont(font)
            painter.setPen(QColor(255,0,0))
            parent_id = self.m_parent.id() if self.m_parent else 0
            painter.drawText(text_pos, str(self.id()) +"["+str(parent_id)+"]")
            painter.drawEllipse(text_pos,2,2)

        self._reset_moving_flag()
        self.__check_position_change()
        self.m_this_frame_flag   =False
        self.m_this_frame_flag_2 =False
        
    def clone(self):
        pass
