import copy

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QTreeWidget, QTreeWidgetItem, QStackedWidget, QLabel, QFrame,QScrollArea,
    QListWidget, QListWidgetItem, QPushButton, QGroupBox,QColorDialog,QCheckBox,
    QTextEdit, QStyleFactory,QLineEdit
)
from PyQt6.QtCore import Qt, QTimer, QEvent,QObject,QRegularExpression,QPointF,QPoint,QRect,pyqtSignal,QPropertyAnimation,QEasingCurve,QSize,QRectF,QSizeF

from math import sin,cos ,atan,pi,sqrt
from typing import overload,Union,List,Optional
from PyQt6.QtGui import QFont,QColor, QPainter, QTransform, QRegion,QAction, QRegularExpressionValidator, QPalette,QPen,QPainterPath,QFontMetrics,QPixmap
from .my_transform import Transform
import time
from .my_common import SceneMode

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

    geometryChangeToChild = pyqtSignal()#告知子图元位置已改变

    # geometryChangeToGroupParent = Signal()

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
        
        if self._Transform_last != self.sceneTransform():
         
            self.update_boundingRect()

       
        self._Transform_last  = self.sceneTransform()

        
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
        
    def handle_parent_move(self):
        """父图元位置变化"""
        # self.__check_position_change()
        self.update_boundingRect()

    def setRotation(self,ang):
        self.m_transform.rotate_around(ang,self.m_origin)
        # self.__check_position_change()
    
    def transform(self):
        """获取变换矩阵"""
        return self.m_transform
    
    def setTransform(self, transform):
        """设置变换矩阵"""
        self.m_transform = transform
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

    def Delete(self):

        if self.is_has_parent():
            return
        if not self.is_has_child():
            self.m_scene.shine_flag_change.disconnect(self.handle_shine_flag)
            self.m_scene_manager.delete_item_signal.emit(self)
        else:
            pass

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

            if isinstance(child,group_element):
                child.removeParentItem()
            else:
                if child.is_has_child():
                    child.removeChildsItem()
                else:
                    child.removeParentItem()
                
        print(f"已解除id{self.id()}下的子项")

    
        


    def itemTransform(self):
        """
        计算从图元局部坐标系到父坐标系的变换
    
        """
        # 创建基础变换
        t = Transform()
        t = t.translate(self.m_pos)
        # 2. 应用局部变换
        t = t*self.m_transform 
        return t
    
    def sceneTransform(self):
        """
        计算从图元局部坐标系到场景坐标系的变换
        
        如果存在父图形项，则组合父项的场景变换和本图元的项变换
        """
        if self.m_parent:
            # 组合变换: 父项的场景变换 × 本图元的项变换
            return self.m_parent.sceneTransform() * self.itemTransform()
        # 没有父项时，直接返回本图元的项变换
        return self.itemTransform()
    
    def mapToParent(self, point):
        """将点从局部坐标系映射到父坐标系"""
        return self.itemTransform().map(point)
    
    def mapToScene(self, point):
        """将点从局部坐标系映射到场景坐标系"""
        if self.__moving_flag:
            self.__is_moving = True
            return self.sceneTransform().map(point)
        else:
            self.__is_moving = False
            return self._Transform_last.map(point)
    
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
        if self.is_in_group() and not isinstance(self,group_element):
            return
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
        if self.m_scene_manager:
            if name not in self.m_scene_manager.m_name_items.keys():
                if self._name=="":
                    self._name =name
                    self.m_scene_manager.m_name_items[name] = self.id()
                else:
                    id = self.m_scene_manager.m_name_items.pop(self._name)
                    self._name =name
                    self.m_scene_manager.m_name_items[name] = id
            else:
                if self._name=="":
                    return False

            print(self.m_scene_manager.m_name_items)
            return True

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
            if self.is_in_group() or isinstance(self,group_element):
                self.m_scene.hover_sta_change.emit(self)
        self.__hover_last  = self.__hover
        
    def sceneBoundingRect(self):
        return self._sceneBoundingRect
    
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




class line_element(base_element):
    
    count = 0
    def __init__(self,parent=None):
        super().__init__(parent=parent)
        self.parent= parent
        line_element.count+=1
        self.scene_size = QSizeF()
        self.length = 0
        self.type = "line"
        self.set_fill(False)
        self.set_actived( True)
        self.set_selected(False)
   
    def __del__(self):
        print(f"销毁line图元 id:{self.id()} name：{self.get_name()}")

    def update_boundingRect(self):
        super().update_boundingRect()
        self.prepareGeometryChange()
        
        rect=QRectF(self.mapToScene(self._head_pos),self.mapToScene(self._end_pos))

        w,h=rect.width(), rect.height()
        x,y= rect.topLeft().x(),rect.topLeft().y()
        if w<=0.0 and h<=0.0:
            rect = QRectF(x+w,y+ h,-w,-h)
        elif w<=0.0:
            rect = QRectF(x+w,y,-w,h)
        elif h<=0.0:
            rect = QRectF(x,y+h,w,-h)
        
        if abs(rect.width())<50.0 and abs(rect.height())>50.0:
            rect.setWidth(50.0)
            rect.setLeft(rect.left()-25)
        elif abs(rect.width())>50.0 and abs(rect.height())<50.0:
            rect.setHeight(50.0)
            rect.setTop(rect.top()-25)
        # rect_with_bound = QRectF(QPointF(rect.topLeft()-QPointF(bound_width,bound_width)),QPointF(rect.bottomRight()+QPointF(bound_width,bound_width)))
        new_w = rect.width()
        new_h = rect.height()
        new_x = rect.left()
        new_y = rect.top()  
      
        rect = QRectF(new_x,new_y,new_w,new_h)

        # self._select_sceneBoundingRect=rect

        # new_w = rect.width()*1.1
        # new_h = rect.height()*1.1
        # new_x = rect.left() - new_w*0.05
        # new_y = rect.top()  - new_h*0.05
      
        # rect = QRectF(new_x,new_y,new_w,new_h)

        self._sceneBoundingRect=rect
     
       

    def completed(self,construct_from_dict=False):
        if construct_from_dict:
            return super().completed(True)
        
        _center_pos = (self._end_pos + self._head_pos)/2.0
        self._end_pos  =   self._end_pos    - _center_pos
        self._head_pos =   self._head_pos   - _center_pos
    
        self.length = sqrt(  (self._end_pos.x() *self._end_pos.x()) +(self._end_pos.y() *self._end_pos.y()) )*2.0
        self._center_pos = QPointF(0,0)

        x_min =min(self._end_pos.x(),self._head_pos.x())
        y_min =min(self._end_pos.y(),self._head_pos.y())
        x_max =max(self._end_pos.x(),self._head_pos.x())
        y_max =max(self._end_pos.y(),self._head_pos.y())


        self._topLeft = QPointF(x_min,y_min)
        tmp_pos = self._topLeft 
        
        self._bottomRight = QPointF(x_max,y_max) - tmp_pos
        self._bottomLeft  = QPointF(x_min,y_max) - tmp_pos
        self._topRight    = QPointF(x_max,y_min) - tmp_pos
        self._head_pos   -= tmp_pos
        self._end_pos    -= tmp_pos
        self._center_pos -= tmp_pos
      
        self._topLeft     = QPointF(0,0)
        self.setSize(x_max-x_min ,y_max-y_min)
        
        self.m_pos_init = self.m_pos = tmp_pos + _center_pos
        self.setTransformOriginPoint(self._center_pos)
  
        super().completed()
    
    def transfer_head_pos(self,pos_start:QPointF):
        self._head_pos =pos_start

    def transfer_pos(self,pos:QPointF):
        self._end_pos =pos

    def transfer_end_pos(self,pos_end:QPointF):
        self._end_pos =pos_end
        self.completed()
    
    def change_head_pos(self,pos):
        if self.is_has_parent() or self.is_has_child():
            return
        self._head_pos = self.mapFromScene(pos)
        self._center_pos = (self._head_pos + self._end_pos)/2.0
        self.length =sqrt(  (self._end_pos.x() *self._end_pos.x()) +(self._end_pos.y() *self._end_pos.y()) )*2.0

        x_min             = min(self._end_pos.x(),self._head_pos.x())
        y_min             = min(self._end_pos.y(),self._head_pos.y())
        x_max             = max(self._end_pos.x(),self._head_pos.x())
        y_max             = max(self._end_pos.y(),self._head_pos.y())
        self._topLeft     = QPointF(x_min,y_min)
        self._bottomRight = QPointF(x_max,y_max)
        self._bottomLeft  = QPointF(x_min,y_max)
        self._topRight    = QPointF(x_max,y_min)
        self.setSize(x_max-x_min ,y_max-y_min)
        self.setTransformOriginPoint(self._center_pos)
        self.update_boundingRect()
       
    
    def change_end_pos(self,pos):
        if self.is_has_parent() or self.is_has_child():
            return
        self._end_pos = self.mapFromScene(pos)
        self._center_pos = (self._head_pos + self._end_pos)/2.0
        self.length =sqrt(  (self._end_pos.x() *self._end_pos.x()) +(self._end_pos.y() *self._end_pos.y()) )*2.0

        x_min             = min(self._end_pos.x(),self._head_pos.x())
        y_min             = min(self._end_pos.y(),self._head_pos.y())
        x_max             = max(self._end_pos.x(),self._head_pos.x())
        y_max             = max(self._end_pos.y(),self._head_pos.y())
        self._topLeft     = QPointF(x_min,y_min)
        self._bottomRight = QPointF(x_max,y_max)
        self._bottomLeft  = QPointF(x_min,y_max)
        self._topRight    = QPointF(x_max,y_min)
        self.setSize(x_max-x_min ,y_max-y_min)
        self.setTransformOriginPoint(self._center_pos)
        self.update_boundingRect()
    
    def change_position(self,pos):
        """"属性设置移动位置"""
        w ,h=self.getSize().width(),self.getSize().height()
   
        print(self.getSize())
        self._head_pos_last = self.mapToScene(self._topLeft)

        def identify_point(pos, points):
            for i, point in enumerate(points):
                if point == pos:  # QPointF已重载==运算符
                    if   i==0:
                        return "topLeft"
                    elif i==1:
                        return "bottomRight"
                    elif i==2:
                        return "topRight"
                    elif i==3:
                        return "bottomLeft"
            return "pos不在给定点集中"
        points = [self._topLeft  ,self._bottomRight, self._topRight  , self._bottomLeft ]


        topLeft_local    = self.mapFromScene(pos)
        bottomRight_local    = topLeft_local + QPointF(w,h)
        topRight_local   = topLeft_local + QPointF(w,0)
        bottomLeft_local = topLeft_local + QPointF(0,h)
        result = identify_point(self._head_pos,points)
        if result=="topLeft":
            self._head_pos = topLeft_local
        elif result=="bottomRight":
            self._head_pos = bottomRight_local
        elif result=="topRight":
            self._head_pos = topRight_local
        elif result=="bottomLeft":
            self._head_pos = bottomLeft_local
        else:
            print(result)
        
        result = identify_point(self._end_pos,points)
        if result=="topLeft":
            self._end_pos = topLeft_local
        elif result=="bottomRight":
            self._end_pos = bottomRight_local
        elif result=="topRight":
            self._end_pos = topRight_local
        elif result=="bottomLeft":
            self._end_pos = bottomLeft_local
        else:
            print(result)
        
        self._topLeft     = topLeft_local
        self._bottomRight = bottomRight_local
        self._topRight    = topRight_local
        self._bottomLeft  = bottomLeft_local



        self._center_pos = (self._head_pos + self._end_pos)/2.0

        self.setTransformOriginPoint(self._center_pos)
        
        self.update_boundingRect()

        if self.is_has_child():
            for child in self.childItems():
                dpos= child.get_scene_topLeft() + pos-self._head_pos_last
                child.change_position(dpos)
        else:
            return

    def change_size(self,w,h):
        """"属性设置改变尺寸"""
        self._scene_size_last =copy.copy(self.scene_size)
       
        def identify_point(pos, points):
            for i, point in enumerate(points):
                if point == pos:  # QPointF已重载==运算符
                    if   i==0:
                        return "topLeft"
                    elif i==1:
                        return "bottomRight"
                    elif i==2:
                        return "topRight"
                    elif i==3:
                        return "bottomLeft"
            return "pos不在给定点集中"
        points = [self._topLeft  ,self._bottomRight, self._topRight  , self._bottomLeft ]
        self.setSize(w,h)
        self._bottomRight  =   QPointF(w,h) + self._topLeft
        self._center_pos = (self._topLeft + self._bottomRight)/2.0
        self._topRight   = QPointF(w,0) + self._topLeft
        self._bottomLeft = QPointF(0,h) + self._topLeft

        result = identify_point(self._head_pos,points)
        if result=="topLeft":
            self._head_pos = self._topLeft
        elif result=="bottomRight":
            self._head_pos = self._bottomRight 
        elif result=="topRight":
            self._head_pos = self._topRight
        elif result=="bottomLeft":
            self._head_pos = self._bottomLeft
        else:
            print(result)
        
        result = identify_point(self._end_pos,points)
        if result=="topLeft":
            self._end_pos = self._topLeft
        elif result=="bottomRight":
            self._end_pos = self._bottomRight 
        elif result=="topRight":
            self._end_pos = self._topRight
        elif result=="bottomLeft":
            self._end_pos = self._bottomLeft
        else:
            print(result)
      
        self.setTransformOriginPoint(self._center_pos)
        
        self.update_boundingRect()

        if self.is_has_child():
            x_scale,y_scale = self.scene_size.width()/self._scene_size_last.width() , self.scene_size.height()/self._scene_size_last.height()
            for child in self.childItems():
                p1 =    child.get_scene_topLeft()                - self.get_scene_topLeft()
                dpos_head = QPointF(p1.x()*x_scale ,p1.y()*y_scale)   
                p2 =    child.get_scene_bottomRight()            - self.get_scene_topLeft()
                dpos_end  = QPointF(p2.x()*x_scale ,p2.y()*y_scale)
                p3 =    child.get_scene_topRight()               - self.get_scene_topLeft()
                dpos_topRight = QPointF(p3.x()*x_scale,p3.y()*y_scale) 

                a = dpos_topRight - dpos_head
                b = dpos_topRight - dpos_end
                w = sqrt(a.x()*a.x() + a.y()*a.y())
                h = sqrt(b.x()*b.x() + b.y()*b.y())
               
                child.change_position(dpos_head+ self.get_scene_topLeft())
                child.change_size(w,h)
        else:
            return
    


    def setSize(self,w,h):
        self.scene_size.setWidth(w)
        self.scene_size.setHeight(h)
    def getSize(self)->QSizeF:
        return self.scene_size
    

        

    def check_hover(self,mouse_pos:QPointF):
        if self.is_moving() or not self.get_selectable():
            
            self.set_hover(False)
            return False
        super().check_hover(mouse_pos)
        if (self._end_pos.x()-self._head_pos.x())!=0:
            k = (self._end_pos.y()-self._head_pos.y())/(self._end_pos.x()-self._head_pos.x())
            the =atan(k)
        else:
            the =pi/2.0
        a= pi/2.0-the
        angle = the*180.0/pi
        # print(angle)
        pos =  self.mapFromScene(mouse_pos)
        t   = Transform()
        t.translate(self._center_pos)
        t.rotate(angle) #
        
        # t.translate(self._center_pos)
        
        # print(self._head_pos,pos,self._end_pos)
        new_head_pos  =  t.map_inverse(self._head_pos)
        new_end_pos   =  t.map_inverse(self._end_pos)
        new_mouse_pos =  t.map_inverse(pos)
        # print(new_head_pos,new_mouse_pos,new_end_pos)
        # self.scene_size.setHeight(abs(new_head_pos.x()-new_end_pos.x()))
        # self.scene_size.setWidth(10)

        if  new_head_pos.x() <= new_mouse_pos.x() <= new_end_pos.x() or new_head_pos.x() >= new_mouse_pos.x() >= new_end_pos.x() :
            if abs(new_mouse_pos.y())<10:
                # self.hover = True
                self.set_hover(True)
                return True
        # self.hover = False
        self.set_hover(False)
        return False
    
    def set_visibility(self, enable):
        if self.is_has_child():
            for item in self.childItems():
                item.set_visibility(enable)
        return super().set_visibility(enable)

    def paint(self,painter:QPainter,shine_flag):
        
        if self.get_visibility()==False:
            super().paint(painter,shine_flag)
            return
        if not (self.m_veiw_dirty_region.intersects(self.viewBoundingRect().toRect())):
            super().paint(painter,shine_flag)
            return
        if self._head_pos is None:
            return
        painter.save()
        color = self._color
        
        if  self.get_hover() or  self.is_in_group() and self._is_group_in_hover:
            color = QColor(14,248,236)
        
        # self.m_display_color = color

            
        painter.setPen(QPen(color, self.get_line_width()))
        
        pos0=self.m_scene.sceneToView(self.get_scene_head_pos())
        pos1=self.m_scene.sceneToView(self.get_scene_end_pos())
        
        painter.drawLine(pos0,pos1)
        # if self.get_selected():
        #     def create_pen_style(color):
        #         # 创建基础画笔
        #         pen = QPen()
                
        #         # 设置画笔属性
        #         pen.setColor(color)  # 黑色钢笔
        #         pen.setWidth(1)                # 线宽3像素
                
        #         dash_pattern = [4, 4, 4, 4]  # 8像素实线 - 4像素空白 - 2像素点 - 4像素空白
                
        #         pen.setDashPattern(dash_pattern)  # 设置自定义虚线模式
        #         pen.setStyle(Qt.CustomDashLine)   # 必须设置为自定义虚线模式
                
        #         # 优化端点样式
        #         pen.setCapStyle(Qt.RoundCap)      # 圆角端点
        #         pen.setJoinStyle(Qt.RoundJoin)    # 圆角连接
                
        #         return pen
        #     pen = create_pen_style(color)
        #     painter.setPen(pen)
        #     rect_view = self.selectViewBoundingRect()
        #     painter.drawRect(rect_view)

        painter.restore()

        super().paint(painter,shine_flag)

    def clone(self):
        """深度克隆图元及其子图元"""

        # 创建当前图元的新实例（不复制父关系）
        cloned = line_element()
      
        # 复制核心属性
        cloned.m_pos = self.m_pos #值类型，赋值时自动创建独立副本（非引用）
        cloned.set_line_width(self.get_line_width())
        cloned.set_color(self.get_color())
        cloned.set_opacity(self.get_opacity())
   
        cloned.set_head_pos(self.get_head_pos())
        cloned.set_end_pos(self.get_end_pos())
        cloned.set_center_pos(self.get_center_pos())
        cloned.length       = self.length
        cloned._topRight   = self._topRight
        cloned._bottomLeft = self._bottomLeft
        cloned._topLeft   = self._topLeft
        cloned._bottomRight = self._bottomRight
        cloned.setSize(self.getSize().width(),self.getSize().height())
        cloned.setTransformOriginPoint(self.transformOriginPoint())
        cloned.setTransform(Transform(self.transform().m))
        cloned.m_angle      = self.m_angle
        cloned.m_angle_init = self.m_angle_init
        cloned.m_pos_init   = self.m_pos_init
        
        cloned.set_group_id(self.get_group_id())

        cloned.set_zValue(self.zValue())
        
        # 递归克隆子图元
        for child in self.childItems():
            child_clone = child.clone() 

            child_clone.m_parent = cloned
            cloned.m_children.add(child_clone)
            # cloned.geometryChangeToChild.connect(child_clone.handle_parent_move)

            # all_clones.extend(child_clones)  # 添加所有子克隆到列表
        
        return cloned


    def to_dict(self):
        """将图元转换为字典"""
        parent_id = self.m_parent.id() if self.m_parent else 0
        children_ids  =[]
        if self.m_children:
            for child in self.m_children:
                children_ids.append(child.id())
        angle = self.sceneTransform().get_rotation_angle()
        return {
            "id"   :self.id(),
            "name"   :self.get_name(),
            "type": self.type,
            "parent_id":parent_id,
            "children_ids":children_ids,
            "group_id":self._group_id,
            "head_pos": {"x": round(self.get_scene_head_pos().x(),3), "y": round(self.get_scene_head_pos().y(),3)},
            "end_pos" : {"x": round(self.get_scene_end_pos().x(),3), "y": round(self.get_scene_end_pos().y(),3)  },
            # "center_pos": {"x": round(self.get_scene_center_pos().x(),3), "y": round(self.get_scene_center_pos().y(),3)},
            "origin_pos": {"x": round(self.get_scene_OriginPoint().x(),3), "y": round(self.get_scene_OriginPoint().y(),3)},
            "style"   : {"stroke":color_to_str(self.get_color()),
                         "strokeWidth":self.get_line_width(),
                         "opacity":self.get_opacity()},
            "rotate" : angle,#图元角度而非直线角度
            "length" : self.length,
            "zValue": self.zValue()
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建图元"""
        scene_end_pos = QPointF(data["end_pos"]["x"],data["end_pos"]["y"])
        scene_head_pos = QPointF(data["head_pos"]["x"],data["head_pos"]["y"])
        scene_center_pos = (scene_end_pos+scene_head_pos)/2.0
        scene_origin_pos = QPointF(data["origin_pos"]["x"],data["origin_pos"]["y"])
        angle = data["rotate"]
        length = data["length"]
        item = cls()
        # item.set_head_pos(QPointF(data["head_pos"]["x"],data["head_pos"]["y"]))
        # item.set_end_pos(QPointF(data["end_pos"]["x"],data["end_pos"]["y"]))
        item.setID(data["id"])
        item._set_name(data["name"])
        item.m_parent_id = data["parent_id"]
        item.m_children_ids = set(data["children_ids"])
        item._group_id = data["group_id"]
        item.set_line_width(data["style"]["strokeWidth"])
        item.set_color(str_to_color( data["style"]["stroke"]) )
        item.set_opacity( data["style"]["opacity"] )
        item.m_angle_init = item.m_angle = angle
        item.length = length
        item.set_zValue(data["zValue"])

        
        t =Transform()
        t.translate(scene_center_pos)
        t.rotate(angle)

        item.m_origin   =t.map_inverse(scene_origin_pos)
        item._head_pos   =t.map_inverse(scene_head_pos)
        item._end_pos   =t.map_inverse(scene_end_pos)

        item.m_pos_init = item.m_pos = scene_center_pos
        
        item._center_pos   = QPointF(0,0)

        x_min             = min(item._end_pos.x(),item._head_pos.x())
        y_min             = min(item._end_pos.y(),item._head_pos.y())
        x_max             = max(item._end_pos.x(),item._head_pos.x())
        y_max             = max(item._end_pos.y(),item._head_pos.y())
        item._topLeft     = QPointF(x_min,y_min)
        item._bottomRight = QPointF(x_max,y_max)
        item._bottomLeft  = QPointF(x_min,y_max)
        item._topRight    = QPointF(x_max,y_min)
        item.setSize(x_max -x_min ,y_max-y_min)
      
       

        t =Transform()
        t.rotate(angle)
        item.setTransform(t)
        
        return item


   




    



class rect_element(base_element):
    count = 0

    @overload
    def __init__(self, parent: QObject = None): ...
    
    @overload
    def __init__(
        self,
        parent: QObject = None,
        width: float = 100.0,
        height: float = 100.0
       
    ): ...
    
    def __init__(self, *args, **kwargs):
        # 参数解析逻辑
        rect_element.count+=1
        parent = None
        width = 0.0
        height =0.0

        self.constructed_by_draw = True
       
        # 解析位置参数
        if args:
            if len(args) == 1 and isinstance(args[0], QObject):
                parent = args[0]
                
            elif len(args) >= 2:
                parent = args[0]
                # 通过第二个参数类型判定重载版本
                if isinstance(args[1], float):#
                    self.constructed_by_draw = False
                    
                    width  = args[1]
                    height = args[2] if len(args) > 2  else 100.0
                   
                    
        # 解析关键字参数（优先级高于位置参数）
        parent = kwargs.get('parent', parent)
        width =  kwargs.get('width', width)
        height = kwargs.get('height', height)
      
        if 'width' in kwargs.keys() or 'height' in kwargs.keys():
            self.constructed_by_draw = False
        
        super().__init__(parent)

        self.parent= parent
        self.type = "rect"
        
        # self._topRight   = None
        # self._bottomleft = None
      
       
        self.scene_size = QSizeF(width,height)
        
        self.set_fill(False)
        self.set_actived(True)
        self.set_selected(False)
       

        
        if self.constructed_by_draw:
            
            
            self.sence_rect =None
            self.sence_rect_left_top=None
        else:
            """给定了长 宽数据"""
            self._center_pos=QPointF(0,0)
            self.sence_rect = QRectF( self._center_pos.x()-self.scene_size.width()/2.0,
                                  self._center_pos.y()-self.scene_size.height()/2.0,self.scene_size.width(),self.scene_size.height())
            self.sence_rect_left_top= self.calc_sence_rect_pos(self.sence_rect.topLeft())
        
            self._head_pos  =self.sence_rect.topLeft()
            self._end_pos   =self.sence_rect.bottomRight()
           
    def __del__(self):
        print(f"销毁rect图元 id:{self.id()} name：{self.get_name()}")
       
    
    def update_boundingRect(self):
        super().update_boundingRect()
        
        self.prepareGeometryChange()

        def max_of_four(*args):
            max_value = args[0]
            for val in args:
                if max_value< val:
                    max_value = val
            return max_value
        def min_of_four(*args):
            min_value = args[0]
            for val in args:
                if min_value> val:
                    min_value = val
            return min_value

        

        new_topLeft    = self.mapToScene(self._head_pos)
        new_topRight   = self.mapToScene(self._topRight)
        new_bottomLeft = self.mapToScene(self._bottomLeft)
        new_bottomRight= self.mapToScene(self._end_pos)

        max_x = max_of_four(new_topLeft.x(),new_topRight.x(),new_bottomLeft.x(),new_bottomRight.x())
        max_y = max_of_four(new_topLeft.y(),new_topRight.y(),new_bottomLeft.y(),new_bottomRight.y())
        min_x = min_of_four(new_topLeft.x(),new_topRight.x(),new_bottomLeft.x(),new_bottomRight.x())
        min_y = min_of_four(new_topLeft.y(),new_topRight.y(),new_bottomLeft.y(),new_bottomRight.y())
        
        # w,h = (max_x-min_x)*1.1,(max_y-min_y)*1.1
        # left =min_x -  0.05*w
        # top = min_y -  0.05*h

        rect = QRectF(min_x,min_y,max_x-min_x,max_y-min_y)
        # rect = QRectF(left,top,w,h)
        
        self._sceneBoundingRect = rect

    def completed(self,construct_from_dict=False):
        if construct_from_dict:
            super().completed(True)
            return

        x_max =  max(self._head_pos.x(),self._end_pos.x())
        x_min =  min(self._head_pos.x(),self._end_pos.x())
        y_max =  max(self._head_pos.y(),self._end_pos.y())
        y_min =  min(self._head_pos.y(),self._end_pos.y())

        self._topLeft     =self._head_pos =QPointF(x_min,y_min)
        self._bottomRight =self._end_pos  =QPointF(x_max,y_max)
        self._center_pos  = (self._head_pos + self._end_pos)/2.0

     
        self.scene_size = QSizeF(x_max - x_min,y_max - y_min)

        self._topRight   =QPointF(x_min + self.scene_size.width(),y_min )
        self._bottomLeft =QPointF(x_min ,y_min + self.scene_size.height())


        tmp_pos = copy.deepcopy(self._center_pos)
        self._topLeft     =self._head_pos  = self._head_pos - tmp_pos
        self._bottomRight =self._end_pos  = self._end_pos - tmp_pos

        self._topRight  = self._topRight - tmp_pos
        self._bottomLeft  = self._bottomLeft - tmp_pos

        self._center_pos = QPointF(0,0)
        self.m_pos_init = self.m_pos = tmp_pos
        self.setTransformOriginPoint(0,0)
        super().completed()
    
 
    

    def check_hover(self,mouse_pos:QPointF):
        if self.is_moving() or not self.get_selectable():
            self.set_hover(False)
            return False
        super().check_hover(mouse_pos)
       
        pos =  self.mapFromScene(mouse_pos)
        if self.get_fill() or isinstance(self,group_element):
            if  self._head_pos.x() <= pos.x() <= self._topRight.x():
                if self._head_pos.y() <= pos.y() <= self._head_pos.y()+self.scene_size.height():
                    self.set_hover(True)
                    return True
            self.set_hover(False)
            return False
        else:
            
            if  self._head_pos.x() <= pos.x() <= self._topRight.x():
                if self._head_pos.y() <= pos.y() <= self._head_pos.y()+self.scene_size.height():
        
                    if  self._head_pos.x()+10 <= pos.x() <= self._topRight.x()-10:
                        if self._head_pos.y()+10 <= pos.y() <= self._head_pos.y()+self.scene_size.height()-20:
                            self.set_hover(False)
                            return False
                    self.set_hover(True)
                    return  True
            
            self.set_hover(False)
    def transfer_head_pos(self,pos_start:QPointF):
        self._topLeft =self._head_pos =pos_start
        

    def transfer_pos(self,pos:QPointF):
        if self._head_pos is None:
            return
        self._end_pos =pos
        self._center_pos = (self._head_pos+self._end_pos)/2.0
        self.scene_size.setWidth(abs(self._end_pos.x()-self._head_pos.x()))
        self.scene_size.setHeight(abs(self._end_pos.y()-self._head_pos.y()))
      
    def transfer_end_pos(self,pos_end:QPointF):
        self._bottomRight =self._end_pos =pos_end
        self._center_pos = (self._head_pos+self._end_pos)/2.0
        self.scene_size.setWidth(abs(self._end_pos.x()-self._head_pos.x()))
        self.scene_size.setHeight(abs(self._end_pos.y()-self._head_pos.y()))
        self.completed()

    def change_position(self,pos):
        w ,h=self.getSize().width(),self.getSize().height()
        self._head_pos_last = self.mapToScene(self._head_pos)
        self._head_pos      = pos
        head_pos_local      = self.mapFromScene(pos)
        end_pos_local       = head_pos_local + QPointF(w,h)
        topRight_local      = head_pos_local + QPointF(w,0)
        bottomLeft_local    = head_pos_local + QPointF(0,h)

        # self._topRight   = self.mapToScene(topRight_local)
        # self._bottomLeft = self.mapToScene(bottomLeft_local)
        # self._end_pos  = self.mapToScene(end_pos_local)
        
        self._topLeft     =self._head_pos  = head_pos_local
        self._bottomRight =self._end_pos   = end_pos_local
        self._topRight                     = topRight_local
        self._bottomLeft                   = bottomLeft_local
        self._center_pos  = (self._head_pos + self._end_pos)/2.0

        self.setTransformOriginPoint(self._center_pos)
        
        self.update_boundingRect()

        if self.is_has_child():
            for child in self.childItems():
                dpos= child.get_scene_topLeft() + pos - self._head_pos_last
                child.change_position(dpos)
        else:
            return

    def change_size(self,w,h):
        self._scene_size_last =copy.copy(self.scene_size)
        # self.scene_size.setWidth(w)
        # self.scene_size.setHeight(h)
        self.setSize(w,h)
        self._bottomRight =self._end_pos  =   QPointF(w,h) + self._head_pos
        self._center_pos = (self._head_pos + self._end_pos)/2.0
        self._topRight   = QPointF(w,0) + self._head_pos
        self._bottomLeft = QPointF(0,h) + self._head_pos

        # center_pos_scene = self.mapToScene(self._center_pos)
        # self.m_pos_init = self.m_pos = center_pos_scene
        self.setTransformOriginPoint(self._center_pos)
        
        self.update_boundingRect()

        if self.is_has_child():
            x_scale,y_scale = self.scene_size.width()/self._scene_size_last.width() , self.scene_size.height()/self._scene_size_last.height()
            for child in self.childItems():
                p1 =    child.get_scene_topLeft()               - self.get_scene_head_pos()
                dpos_head = QPointF(p1.x()*x_scale ,p1.y()*y_scale)   
                p2 =    child.get_scene_bottomRight()                - self.get_scene_head_pos()
                dpos_end  = QPointF(p2.x()*x_scale ,p2.y()*y_scale)
                p3 =    child.get_scene_topRight()               - self.get_scene_head_pos()
                dpos_topRight = QPointF(p3.x()*x_scale,p3.y()*y_scale) 

                a = dpos_topRight - dpos_head
                b = dpos_topRight - dpos_end
                w = sqrt(a.x()*a.x() + a.y()*a.y())
                h = sqrt(b.x()*b.x() + b.y()*b.y())
               
                child.change_position(dpos_head+ self.get_scene_head_pos())
                child.change_size(w,h)
        else:
            return
    




    def setSize(self,w,h):
        self.scene_size.setWidth(w)
        self.scene_size.setHeight(h)
        
    def getSize(self)->QSizeF:
        return self.scene_size
    
    
    def set_visibility(self, enable):
        if self.is_has_child():
            for item in self.childItems():
                item.set_visibility(enable)
        return super().set_visibility(enable)
    
    def paint(self,painter:QPainter,shine_flag):
        if self.get_visibility()==False:
            super().paint(painter,shine_flag)
            return

        if not (self.m_veiw_dirty_region.intersects(self.viewBoundingRect().toRect())):
            super().paint(painter,shine_flag)
            return
        if self._head_pos is None:
            return
        painter.save()
        color = self._color
        
        if  self.get_hover() or  self.is_in_group() and self._is_group_in_hover:
            color = QColor(14,248,236)
        center_pos_view=self.m_scene.sceneToView(self.get_scene_center_pos())
        h =            self.scene_size.width()  * (self.m_scene.grid_size ) / self.m_scene.scene_units_per_grid_x
        w =            self.scene_size.height() * (self.m_scene.grid_size ) / self.m_scene.scene_units_per_grid_y
        bg_rect =QRectF(-w/2.0 ,-h/2.0,w,h)
         # 应用视图变换
        painter.translate(center_pos_view)
        angle =    self.sceneTransform().get_rotation_angle()
        painter.rotate(-angle)

        fill_color = self._fill_color
        if self.get_fill():
            # 设置填充颜色（蓝色）
            painter.setBrush(fill_color)   
        if self.get_line_width()>0:
            painter.setPen(QPen(color, self.get_line_width()))
        else:
            painter.setPen(QPen(fill_color, 0))

        painter.drawRect(bg_rect)
      
        painter.restore()
        

        super().paint(painter,shine_flag)


    # def paint(self,painter:QPainter,shine_flag):
    #     if self._head_pos is None:
    #         return
    #     painter.save()

    #     color = self._color
    #     if self.get_hover() or  self.is_in_group() and self._is_group_in_hover:
    #         color = QColor(14,248,236)
           
    #     fill_color = self._fill_color
    #     pos1=self.m_scene.sceneToView(self.get_scene_head_pos())
    #     pos2=self.m_scene.sceneToView(self.get_scene_topRight())
    #     pos3=self.m_scene.sceneToView(self.get_scene_end_pos() )
    #     pos4=self.m_scene.sceneToView(self.get_scene_bottomleft())

    #     if self.get_fill():
    #         # 设置填充颜色（蓝色）
    #         painter.setBrush(fill_color)   
    #     if self.get_line_width()>0:
    #         painter.setPen(QPen(color, self.get_line_width()))
    #     else:
    #         painter.setPen(QPen(fill_color, 0))

    #     painter.drawPolygon([pos1,pos2,pos3,pos4])
    #     painter.restore()
    #     super().paint(painter,shine_flag)

    def clone(self):
        """深度克隆图元及其子图元"""

        # 创建当前图元的新实例（不复制父关系）
        cloned = rect_element()
       
        # 复制核心属性
        cloned.m_pos = self.m_pos #值类型，赋值时自动创建独立副本（非引用）
        cloned.set_line_width(self.get_line_width())
        cloned.set_color(self.get_color())
        cloned.set_fill(self.get_fill())
        cloned.set_fill_color(self.get_fill_color())
        cloned.set_opacity(self.get_opacity())
        cloned.set_head_pos(self.get_head_pos())
        cloned.set_end_pos(self.get_end_pos())
        cloned.set_center_pos(self.get_center_pos())
        cloned._topRight   = self._topRight
        cloned._bottomLeft = self._bottomLeft
        cloned._topLeft   = self._topLeft
        cloned._bottomRight = self._bottomRight
        cloned.setSize(self.getSize().width(),self.getSize().height())
        cloned.setTransformOriginPoint(self.transformOriginPoint())
        cloned.setTransform(Transform(self.transform().m))
        cloned.m_angle      = self.m_angle
        cloned.m_angle_init = self.m_angle_init
        cloned.m_pos_init   = self.m_pos_init

        cloned.set_group_id(self.get_group_id())

        cloned.set_zValue(self.zValue())
        # 递归克隆子图元
        for child in self.childItems():
            child_clone = child.clone() 
            child_clone.m_parent = cloned
            cloned.m_children.add(child_clone)
            # cloned.geometryChangeToChild.connect(child_clone.handle_parent_move)

        return cloned

    def to_dict(self):
        """将图元转换为字典"""
        parent_id = self.m_parent.id() if self.m_parent else 0
        children_ids  =[]
        if self.m_children:
            for child in self.m_children:
                children_ids.append(child.id())

        
        angle =    self.sceneTransform().get_rotation_angle()
        print(f"id:{self.id()}angle{angle}")
        return {
            "id"   :self.id(),
            "name"   :self.get_name(),
            "type": self.type,
            "parent_id":parent_id,
            "children_ids":children_ids,
            "group_id":self._group_id,
            "center_pos": {"x": round(self.get_scene_center_pos().x(),3), "y": round(self.get_scene_center_pos().y(),3)},
            "origin_pos": {"x": round(self.get_scene_OriginPoint().x(),3), "y": round(self.get_scene_OriginPoint().y(),3)},
            "width"  : self.scene_size.width(),
            "height" : self.scene_size.height(),
            "rotate" : angle,
            "style"   : {"stroke":color_to_str(self.get_color()),
                         "strokeWidth":self.get_line_width(),
                         "fill":self.get_fill(),
                         "fill_color" :color_to_str(self.get_fill_color()),
                         "opacity":self.get_opacity()},
            "zValue": self.zValue()
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建图元"""
        scene_center_pos = QPointF(data["center_pos"]["x"],data["center_pos"]["y"])
        scene_origin_pos = QPointF(data["origin_pos"]["x"],data["origin_pos"]["y"])
        angle = data["rotate"]
        w     = data["width" ]
        h     = data["height"]

        item = cls()
       
        item.setID(data["id"])
        item._set_name(data["name"])
        item.m_parent_id = data["parent_id"]
        item.m_children_ids = set(data["children_ids"])
        item._group_id = data["group_id"]
        item.set_fill(data["style"]["fill"])
        item.set_fill_color(str_to_color(data["style"]["fill_color"]))
        item.set_line_width(data["style"]["strokeWidth"])
        item.set_color(str_to_color( data["style"]["stroke"]) )
        item.set_opacity( data["style"]["opacity"] )
        item.setSize(w,h)
        item.m_angle_init = item.m_angle = angle
        item.set_zValue(data["zValue"])
        
        t =Transform()
        dpos =scene_origin_pos- scene_center_pos 
        t.translate(scene_center_pos)
      
        t.rotate(angle)

        item.m_origin =t.map_inverse(scene_origin_pos)

        item.m_pos_init = item.m_pos = scene_center_pos

        item._center_pos   = QPointF(0,0)

        item._head_pos   = QPointF(-w/2.0  ,-h/2.0)
        item._end_pos    = QPointF(w/2.0   ,h/2.0)
        item._topRight   = QPointF(w/2.0   ,-h/2.0)
        item._bottomLeft = QPointF(-w/2.0  ,h/2.0)
        item._topLeft    = item._head_pos
        item._bottomRight= item._end_pos 
       
        t =Transform()
       
        t.rotate(angle)
        
        item.setTransform(t)

        return item
        
    

class group_element(rect_element):
    count = 0
    def __init__(self,*args, parent: QObject = None):
        super().__init__(parent)
        group_element.count+=1
        self.type="group"
        self.members = []
        # self.child_group_id_group_name = {}
        
        for item in args:
            self.members.append(item)
       
    def __del__(self):
        print(f"销毁group id:{self.id()} name：{self.get_name()}")

    def initialize(self):
        def get_boundRect_of_member(item:base_element):
            rect =item.sceneBoundingRect()
            if item.is_has_child():
                for child in item.childItems():
                   
                    rect = rect.united( get_boundRect_of_member(child) )
                return rect
            else:
                return item.sceneBoundingRect()
        rect = self.members[0].sceneBoundingRect()
        # for item in self.members:
        #     rect = rect.united(item.sceneBoundingRect())

        for item in self.members:
            rect = rect.united(get_boundRect_of_member(item))
            
        # self._sceneBoundingRect = rect
        self._head_pos =  rect.topLeft()
        self._end_pos =   rect.bottomRight()
        self.transfer_head_pos(rect.topLeft())
        self.transfer_end_pos(rect.bottomRight())

        for item in self.members:
            self.setChildItem(item)
            item.set_group_id(self.id())
            item.set_selected(False)
          
        
        # self.set_hover(   True)
        self.set_selected(True)


    def __disassemble_group(self):
        """拆解1次group"""
        if not self.is_has_child():
            return
        print("开始拆解1次group")

        children_lst =   list( self.m_children)
        for child in children_lst:
            child.removeParentItem(True)
            print(f"移除了id:{child.id()}类型{child.type}的父图元")

    def free_group(self):

        self.members = []
        
        self.__disassemble_group()
        if self.m_parent:
            self.removeParentItem()
            self.m_parent.m_children.remove(self)
            print(f"移除组的父对象")
        self.Delete()
        print(f"移除{self.type}:id:{self.id()}")

    

    # def change_position(self,pos):
    #     """改变图元位置，属性编辑是使用"""

    #     w ,h=self.getSize().width(),self.getSize().height()
    #     self._head_pos_last = self.mapToScene(self._head_pos)
    #     self._head_pos   = pos  #场景坐标系
    #     head_pos_local   = self.mapFromScene(pos)
    #     end_pos_local    = head_pos_local + QPointF(w,h)
    #     topRight_local   = head_pos_local + QPointF(w,0)
    #     bottomleft_local = head_pos_local + QPointF(0,h)

    #     # self._topRight   = self.mapToScene(topRight_local)
    #     # self._bottomLeft = self.mapToScene(bottomleft_local)
    #     # self._end_pos    = self.mapToScene(end_pos_local)

    #     self._topLeft     =self._head_pos    = head_pos_local
    #     self._bottomRight =self._end_pos     = end_pos_local
        
    #     self._topRight    = topRight_local
    #     self._bottomLeft  = bottomleft_local
    #     self._center_pos  = (self._head_pos + self._end_pos)/2.0

    #     self.setTransformOriginPoint(self._center_pos)
    #     self.update_boundingRect()

    #     if self.is_has_child():
    #         for child in self.childItems():
    #             dpos= child.get_scene_topLeft() + pos-self._head_pos_last
    #             child.change_position(dpos)
    #     else:
    #         return

    # def change_size(self,w,h):
    #     self._scene_size_last =copy.copy(self.scene_size)
    #     self.setSize(w,h)
    #     # self.scene_size.setWidth(w)
    #     # self.scene_size.setHeight(h)
    #     self._bottomRight = self._end_pos  =   QPointF(w,h) + self._head_pos
    #     self._center_pos = (self._head_pos + self._end_pos)/2.0
    #     self._topRight   = QPointF(w,0) + self._head_pos
    #     self._bottomLeft = QPointF(0,h) + self._head_pos

    #     self.setTransformOriginPoint(self._center_pos)
    #     self.update_boundingRect()

    #     if self.is_has_child():
    #         x_scale,y_scale = self.scene_size.width()/self._scene_size_last.width() , self.scene_size.height()/self._scene_size_last.height()
    #         for child in self.childItems():
    #             p1 =    child.get_scene_topLeft()               - self.get_scene_head_pos()
    #             dpos_head = QPointF(p1.x()*x_scale ,p1.y()*y_scale)   
    #             p2 =    child.get_scene_bottomRight()                - self.get_scene_head_pos()
    #             dpos_end  = QPointF(p2.x()*x_scale ,p2.y()*y_scale)
    #             p3 =    child.get_scene_topRight()               - self.get_scene_head_pos()
    #             dpos_topRight = QPointF(p3.x()*x_scale,p3.y()*y_scale) 

    #             a = dpos_topRight - dpos_head
    #             b = dpos_topRight - dpos_end
    #             w = sqrt(a.x()*a.x() + a.y()*a.y())
    #             h = sqrt(b.x()*b.x() + b.y()*b.y())
               
    #             child.change_position(dpos_head+ self.get_scene_head_pos())
    #             child.change_size(w,h)
    #     else:
    #         return


    def set_visibility(self, enable):
        super().set_visibility(enable)
        if self.is_has_child():
            for item in self.childItems():
                item.set_visibility(enable)
        
    
    def set_selectable(self,enable):
        if self.is_has_child():
            for item in self.childItems():
                item.set_selectable(enable)
        return super().set_selectable(enable)
    
    def paint(self,painter:QPainter,shine_flag):
        
        if self.m_scene and self.m_scene.mode() == SceneMode.Run:
            return
        if self.get_visibility()==False :
            super().paint(painter,shine_flag)
            return
        painter.save()
        def create_pen_style(color):
            # 创建基础画笔
            pen = QPen()
            
            # 设置画笔属性
            pen.setColor(color)  # 黑色钢笔
            pen.setWidth(1)                # 线宽3像素
            
            # 格式: [实线长度, 空白长度, 点长度, 空白长度] 重复
            dash_pattern = [8, 4, 2, 4]  # 8像素实线 - 4像素空白 - 2像素点 - 4像素空白
            
            pen.setDashPattern(dash_pattern)  # 设置自定义虚线模式
            pen.setStyle(Qt.PenStyle.CustomDashLine)   # 必须设置为自定义虚线模式
            
            # 优化端点样式
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)      # 圆角端点
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)    # 圆角连接
            return pen
        
        color = self.get_color()
        if self.get_selected() and shine_flag or self.get_hover() or self._is_group_in_hover :
            color = QColor(14,248,236)

        pen = create_pen_style(color)
       
        painter.setPen(pen)
        
        pos1=self.m_scene.sceneToView(self.get_scene_head_pos())
        pos2=self.m_scene.sceneToView(self.get_scene_topRight())
        pos3=self.m_scene.sceneToView(self.get_scene_end_pos())
        pos4=self.m_scene.sceneToView(self.get_scene_bottomLeft())

        painter.drawPolygon([pos1,pos2,pos3,pos4])

        painter.restore()
        super(rect_element, self).paint(painter,shine_flag)

    def clone(self):
        """深度克隆图元及其子图元"""

        # 创建当前图元的新实例（不复制父关系）
        cloned = group_element()
       
        # 复制核心属性
        cloned.m_pos = self.m_pos #值类型，赋值时自动创建独立副本（非引用）
        cloned.set_line_width(self.get_line_width())
        cloned.set_color(self.get_color())
        cloned.set_fill(self.get_fill())
        cloned.set_head_pos(self.get_head_pos())
        cloned.set_end_pos(self.get_end_pos())
        cloned.set_center_pos(self.get_center_pos())
        cloned._topRight   = self._topRight
        cloned._bottomLeft = self._bottomLeft
        cloned._topLeft   = self._topLeft
        cloned._bottomRight = self._bottomRight
        cloned.setSize(self.getSize().width(),self.getSize().height())
        cloned.setTransformOriginPoint(self.transformOriginPoint())
        cloned.setTransform(Transform(self.transform().m))
        cloned.m_angle      = self.m_angle
        cloned.m_angle_init = self.m_angle_init
        cloned.m_pos_init   = self.m_pos_init
        cloned.set_group_id(self.get_group_id())
        cloned.set_zValue(self.zValue())
        
        # 递归克隆子图元
        for child in self.childItems():
            child_clone = child.clone() 
            child_clone.m_parent = cloned
            cloned.m_children.add(child_clone)
            # cloned.geometryChangeToChild.connect(child_clone.handle_parent_move)

        return cloned

        
       

class circle_element(base_element):
    count = 0

    @overload
    def __init__(self,parent=None)->None:...

    @overload
    def __init__(self,parent=None,pos:QPointF=(0,0),radius:float=0.0,color:QColor=(0,0,0),isFill:bool=False)->None:...
        
    
    def __init__(self,
                arg1:Optional[QObject]=None,
                arg2:Optional[QPointF]=None,
                arg3:Optional[float]=None,
                arg4:Optional[QColor]=None,
                arg5:Optional[bool]=None
               
                 )->None:
        if  not (isinstance(arg2,QPointF) and isinstance(arg3,float) and isinstance(arg4,QColor) and isinstance(arg5,bool)):
            super().__init__(parent=arg1)
           
            self.radius = 0
            self.radius_w = 0
            self.radius_h = 0
            self.scene_size =QSizeF(0,0)
            self.set_color(QColor(0,0,0))
            self.set_fill(False)
           

            
            self.set_actived(True)
            self.set_selected(False)
        else:
            super().__init__(parent=arg1)
            self._center_pos = arg2
            self.radius = arg3
            self.set_color(arg4)
            self.set_fill(arg5)

            self.scene_size = QSizeF(self.radius_w,self.radius_h)
            

            
            self.set_actived(False)
            self.set_selected(False)
        
        self.type = "circle"
        circle_element.count += 1
    
    def __del__(self):
        print(f"销毁circle图元 id:{self.id()} name：{self.get_name()}")

    def update_boundingRect(self):
        super().update_boundingRect()
        
        self.prepareGeometryChange()

        def max_of_four(*args):
            max_value = args[0]
            for val in args:
                if max_value< val:
                    max_value = val
            return max_value
        def min_of_four(*args):
            min_value = args[0]
            for val in args:
                if min_value> val:
                    min_value = val
            return min_value
        
        new_topLeft    = self.mapToScene(self._head_pos)
        new_topRight   = self.mapToScene(self._topRight)
        new_bottomLeft = self.mapToScene(self._bottomLeft)
        new_bottomRight= self.mapToScene(self._end_pos)

        max_x = max_of_four(new_topLeft.x(),new_topRight.x(),new_bottomLeft.x(),new_bottomRight.x())
        max_y = max_of_four(new_topLeft.y(),new_topRight.y(),new_bottomLeft.y(),new_bottomRight.y())
        min_x = min_of_four(new_topLeft.x(),new_topRight.x(),new_bottomLeft.x(),new_bottomRight.x())
        min_y = min_of_four(new_topLeft.y(),new_topRight.y(),new_bottomLeft.y(),new_bottomRight.y())
        
        # w,h = (max_x-min_x)*1.1,(max_y-min_y)*1.1
        # left =min_x -  0.05*w
        # top = min_y -  0.05*h

        rect = QRectF(min_x,min_y,max_x-min_x,max_y-min_y)
        # rect = QRectF(left,top,w,h)
        self._sceneBoundingRect = rect


    def completed(self,construct_from_dict=False):
        if construct_from_dict:
            return super().completed(True)
        
       
        self._head_pos   =  self._center_pos - QPointF(self.radius_w,self.radius_h)
        tmp_pos     = self._head_pos
        self._end_pos    = self._center_pos + QPointF(self.radius_w,self.radius_h)
        self._topLeft    = self._head_pos
        self._bottomRight= self._end_pos
        self._topRight   = self._center_pos + QPointF(self.radius_w,-self.radius_h)
        self._bottomLeft = self._center_pos + QPointF(-self.radius_w,self.radius_h)
        
        self._bottomRight=self._bottomRight - self._topLeft
        self._end_pos    =self._bottomRight
        self._topRight   =self._topRight   - self._topLeft
        self._bottomLeft =self._bottomLeft - self._topLeft
        self._center_pos =self._center_pos - self._topLeft
        self._topLeft    =self._head_pos = QPointF(0,0)

        self.m_pos       = tmp_pos
        
        self.setTransformOriginPoint(self._center_pos)
        self.m_pos_init = tmp_pos

        super().completed()
           
 
    
    def transfer_head_pos(self,pos_start:QPointF):
        self._head_pos  =pos_start
        self._center_pos =pos_start


    def transfer_pos(self,pos:QPointF):
        if isinstance(pos,QPointF):
            self._end_pos =pos
            a=(self._end_pos-self._center_pos)
            self.radius = sqrt(a.x()*a.x()+ a.y()*a.y())
            self.radius_w = self.radius_h = self.radius 
            w=h = self.radius*2.0
            self.scene_size = QSizeF(w,h)

    def transfer_end_pos(self,pos_end:QPointF):
        self._end_pos =pos_end
        a=(self._end_pos-self._center_pos)
        self.radius = sqrt(a.x()*a.x()+ a.y()*a.y())
        self.radius_w = self.radius_h = self.radius 
        w=h = self.radius*2.0
        self.scene_size = QSizeF(w,h)
        self.completed()
    def set_center_pos(self,pos):
        self._center_pos = pos
    
    def setSize(self,w,h):
       
        self.scene_size.setWidth(w)
        self.scene_size.setHeight(h)
        self.radius_h =h/2.0
        self.radius_w =w/2.0
        
    def getSize(self)->QSizeF:
        return self.scene_size
    
    # def change_center_pos(self,pos):
    #     # w ,h=self.getSize().width(),self.getSize().height()
    #     center_pos_local = self.mapFromScene(pos)
    #     self._center_pos =center_pos_local
    #     self._head_pos  =center_pos_local + QPointF(self.radius,0)
    #     self._end_pos   =center_pos_local + QPointF(-self.radius,0)
    #     self.setTransformOriginPoint(self._center_pos)
        
    #     self.update_boundingRect()

    # def change_radius(self,r):
    #     self.radius = r
    #     self._end_pos   =self._head_pos  =self._center_pos + QPointF(self.radius,0)
    #     self.setTransformOriginPoint(self._center_pos)
    #     self.update_boundingRect()

    
    def change_position(self,pos):
        w ,h=self.getSize().width(),self.getSize().height()
        self._head_pos_last = self.mapToScene(self._topLeft)
        # self._head_pos =pos
        topLeft_local = self.mapFromScene(pos)
        bottomRight_local  =  topLeft_local + QPointF(w,h)
        topRight_local     =  topLeft_local + QPointF(w,0)
        bottomLeft_local   =  topLeft_local + QPointF(0,h)
        
        self._head_pos    = self._topLeft     = topLeft_local
        self._end_pos     = self._bottomRight = bottomRight_local
        self._topRight    = topRight_local
        self._bottomLeft  = bottomLeft_local
        self._center_pos = (self._head_pos + self._end_pos)/2.0

        self.setTransformOriginPoint(self._center_pos)
        
        self.update_boundingRect()

        if self.is_has_child():
            for child in self.childItems():
                dpos= child.get_scene_topLeft() + pos-self._head_pos_last
                child.change_position(dpos)
        else:
            return

    def change_size(self,w,h):
        self._scene_size_last =copy.copy(self.scene_size)
        self.setSize(w,h)
        
        self._bottomRight = self._end_pos  =   QPointF(w,h) + self._topLeft
        self._center_pos = (self._topLeft + self._end_pos)/2.0
        self._topRight   = QPointF(w,0) + self._topLeft
        self._bottomLeft = QPointF(0,h) + self._topLeft



        self.setTransformOriginPoint(self._center_pos)
        
        self.update_boundingRect()

        if self.is_has_child():
            x_scale,y_scale = self.scene_size.width()/self._scene_size_last.width() , self.scene_size.height()/self._scene_size_last.height()
            for child in self.childItems():
                p1 =    child.get_scene_topLeft()               - self.get_scene_topLeft()
                dpos_head = QPointF(p1.x()*x_scale ,p1.y()*y_scale)   
                p2 =    child.get_scene_bottomRight()                - self.get_scene_topLeft()
                dpos_end  = QPointF(p2.x()*x_scale ,p2.y()*y_scale)
                p3 =    child.get_scene_topRight()               - self.get_scene_topLeft()
                dpos_topRight = QPointF(p3.x()*x_scale,p3.y()*y_scale) 

                a = dpos_topRight - dpos_head
                b = dpos_topRight - dpos_end
                w = sqrt(a.x()*a.x() + a.y()*a.y())
                h = sqrt(b.x()*b.x() + b.y()*b.y())
               
                child.change_position(dpos_head+ self.get_scene_topLeft())
                child.change_size(w,h)
        else:
            return
    


    def check_hover(self,mouse_pos:QPointF):
        """((x - x0)² / a²) + ((y - y0)² / b²) ≤ 1"""
        if self.is_moving() or not self.get_selectable():
            self.set_hover(False)
            return False
        super().check_hover(mouse_pos)
        pos =  self.mapFromScene(mouse_pos)

        radius_w_max =self.radius_w+5.0
        radius_h_max =self.radius_h+5.0
        radius_w_min =self.radius_w-5.0
        radius_h_min =self.radius_h-5.0

        x ,y  = pos.x(),pos.y()
        x0,y0 = self._center_pos.x(),self._center_pos.y()
        result_max = (x - x0)*(x - x0)/(radius_w_max*radius_w_max)  +(y - y0)*(y - y0)/(radius_h_max*radius_h_max)<=1
        result_min = (x - x0)*(x - x0)/(radius_w_min*radius_w_min)  +(y - y0)*(y - y0)/(radius_h_min*radius_h_min)>=1

        if self.get_fill():
            # self.hover = d <= self.radius
            self.set_hover(result_max)
        else:
            # self.hover = d <= self.radius+10.0 and d >= self.radius-10.0
            self.set_hover( result_max and result_min)
        return self.get_hover()

    def set_visibility(self, enable):
        if self.is_has_child():
            for item in self.childItems():
                item.set_visibility(enable)
        return super().set_visibility(enable)

    def paint(self,painter:QPainter,shine_flag):
        if self.get_visibility()==False:
            super().paint(painter,shine_flag)
            return
        if self._center_pos is None:
            return
        painter.save()
        color = self._color
        if  self.get_hover() or  self.is_in_group() and self._is_group_in_hover:
            color = QColor(14,248,236)
        
        fill_color = self._fill_color
      
        if self.get_fill():
            # 设置填充颜色（蓝色）
            painter.setBrush(fill_color)    
        if self.get_line_width()>0:
            painter.setPen(QPen(color, self.get_line_width()))
        else:
            painter.setPen(QPen(fill_color, 0))

        center_pos_view=self.m_scene.sceneToView(self.get_scene_center_pos())
        # view_r = self.radius* (self.m_scene.grid_size ) / self.m_scene.scene_units_per_grid_x
        view_r_h = self.radius_w* (self.m_scene.grid_size ) / self.m_scene.scene_units_per_grid_x
        view_r_w = self.radius_h* (self.m_scene.grid_size ) / self.m_scene.scene_units_per_grid_y

        rect =QRectF(-view_r_w ,-view_r_h,view_r_w*2.0,view_r_h*2.0)
       
         # 应用视图变换
        painter.translate(center_pos_view)
        angle =    self.sceneTransform().get_rotation_angle()
        painter.rotate(-angle)

        

        # painter.drawEllipse(pos0,view_r,view_r)
        painter.drawEllipse(rect)
   
        painter.restore()
        super().paint(painter,shine_flag)

    def clone(self):
        """深度克隆图元及其子图元"""

        # 创建当前图元的新实例（不复制父关系）
        cloned = circle_element()
      
        # 复制核心属性
        cloned.m_pos = self.m_pos #值类型，赋值时自动创建独立副本（非引用）
        cloned.set_line_width(self.get_line_width())
        cloned.set_color(self.get_color())
        cloned.set_fill(self.get_fill())
        cloned.set_fill_color(self.get_fill_color())
        cloned.set_opacity(self.get_opacity())
   
        cloned.set_head_pos(self.get_head_pos())
        cloned.set_end_pos(self.get_end_pos())
        cloned.set_center_pos(self.get_center_pos())
        cloned._topRight   = self._topRight
        cloned._bottomLeft = self._bottomLeft
        cloned._topLeft   = self._topLeft
        cloned._bottomRight = self._bottomRight
        cloned.radius_w   =      self.radius_w
        cloned.radius_h   =      self.radius_h
        cloned.scene_size =      copy.copy(self.scene_size)  
      
        cloned.setTransformOriginPoint(self.transformOriginPoint())
        cloned.setTransform(Transform(self.transform().m))
        cloned.m_angle      = self.m_angle
        cloned.m_angle_init = self.m_angle_init
        cloned.m_pos_init   = self.m_pos_init
        cloned.set_group_id(self.get_group_id())
        cloned.set_zValue(self.zValue())
        
        # 递归克隆子图元
        for child in self.childItems():
            child_clone = child.clone() 

            child_clone.m_parent = cloned
            cloned.m_children.add(child_clone)
            # cloned.geometryChangeToChild.connect(child_clone.handle_parent_move)

            # all_clones.extend(child_clones)  # 添加所有子克隆到列表
        
        return cloned


    def to_dict(self):
        """将图元转换为字典"""
        parent_id = self.m_parent.id() if self.m_parent else 0
        children_ids  =[]
        if self.m_children:
            for child in self.m_children:
                children_ids.append(child.id())
        angle =    self.sceneTransform().get_rotation_angle()
        return {
            "id"   :self.id(),
            "name"   :self.get_name(),
            "type": self.type,
            "parent_id":parent_id,
            "children_ids":children_ids,
            "group_id":self._group_id,
            "center_pos": {"x": round(self.get_scene_center_pos().x(),3), "y": round(self.get_scene_center_pos().y(),3)},
            "origin_pos": {"x": round(self.get_scene_OriginPoint().x(),3), "y": round(self.get_scene_OriginPoint().y(),3)},
            "rotate" : angle,
            # "radius" : self.radius,
            "radius_w" : self.radius_w,
            "radius_h" : self.radius_h,
            "style"   : {"stroke":color_to_str(self.get_color()),
                         "strokeWidth":self.get_line_width(),
                         "fill":self.get_fill(),
                         "fill_color" :color_to_str(self.get_fill_color()),
                         "opacity":self.get_opacity()},
            "zValue": self.zValue()
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建图元"""
        scene_center_pos = QPointF(data["center_pos"]["x"],data["center_pos"]["y"])
        scenr_origin_pos = QPointF(data["origin_pos"]["x"],data["origin_pos"]["y"])
        angle =data["rotate"]
        item = cls()
        item.set_center_pos(QPointF(data["center_pos"]["x"],data["center_pos"]["y"]))
        # item.radius  = data["radius"]
        item.radius_w  = data["radius_w"]
        item.radius_h  = data["radius_h"]
        w,h= item.radius_w*2.0,   item.radius_h*2.0
        item.setSize(w,h)
        item.setID(data["id"])
        item._set_name(data["name"])
        item.m_parent_id = data["parent_id"]
        item.m_children_ids = set(data["children_ids"])
        item._group_id = data["group_id"]
        item.set_fill(data["style"]["fill"])
        item.set_fill_color(str_to_color(data["style"]["fill_color"]))
        item.set_line_width(data["style"]["strokeWidth"])
        item.set_color(str_to_color( data["style"]["stroke"]) )
        item.set_opacity( data["style"]["opacity"] )
        item.m_angle_init = item.m_angle = angle
        item.set_zValue(data["zValue"])

        t =Transform()
        t.translate(scene_center_pos)
        t.rotate(angle)

        item.m_origin =t.map_inverse(scenr_origin_pos)

        item.m_pos_init = item.m_pos = scene_center_pos
        
        item._center_pos   = QPointF(0,0)

        item._head_pos   = QPointF(-w/2.0  ,-h/2.0)
        item._end_pos    = QPointF(w/2.0   ,h/2.0)
        item._topRight   = QPointF(w/2.0   ,-h/2.0)
        item._bottomLeft = QPointF(-w/2.0  ,h/2.0)
        item._topLeft    = item._head_pos
        item._bottomRight= item._end_pos 
        
        t =Transform()
        t.rotate(angle)
        item.setTransform(t)

        return item

    
    # def construct(self,**kwargs):
    #     group_id = kwargs.get('group_id')
    #     if group_id>-1:
    #         self.set_group_id(group_id)
    #     else:
    #         self.set_group_id(None)

    #     group_name = kwargs.get('group_name')
    #     self.set_group_name(group_name)

    #     group_pos =  QPointF( kwargs.get('group_pos')["x"],kwargs.get('group_pos')["y"])
    #     center_pos = QPointF(kwargs.get('center_pos')["x"],kwargs.get('center_pos')["y"])
    #     radius     = kwargs.get('radius')
    #     isFill =     kwargs.get('isFill')
    #     if 'line_width' in   kwargs.keys():
    #         line_width = kwargs.get('line_width')   
    #         self.set_line_width(line_width)
    #     color =      kwargs.get('color')
    #     self.set_color(color)
        
    #     self.set_fill(isFill)
    #     self.group_pos_save = group_pos
    #     self.group_pos = group_pos
    #     self.center_pos = center_pos
    #     self.radius = radius

    #     self.completed()
    
class text_element(base_element):
    count = 0
    contextChanged = pyqtSignal(str)
    def __init__(self,parent=None,text_height=100,bg_color=QColor(0,255,0,50)):
        super().__init__(parent=parent)
        self.parent= parent
        text_element.count += 1
        self._scene_size = QSizeF()
        self.width = text_height
        self.height  = 0
       
        self.type    = "text"
        self._context = " 文本标签 "
        self._topRight   = None
        self._bottomleft = None
        
        self.font_size = 10
        self.set_fill_color(bg_color)
       
        
        self.set_actived( True)
        self.set_selected(False)
        self.contextChanged.connect(self.handle_context_change)

    # @Property(str, notify=contextChanged)
    @property
    def context(self):
        return self._context
        
    @context.setter
    def context(self, str):
        new_str = " " + str + " "
        if self._context != new_str:
            self._context = new_str
            self.contextChanged.emit(new_str)

    def __del__(self):
        print(f"销毁text图元 id:{self.id()} name：{self.get_name()}")

    def calc_font_size(self, target_height, text) -> float:
        # 创建临时绘图设备
        pixmap = QPixmap(100, 100)
        painter = QPainter(pixmap)
        font = painter.font()
        
        # 精确计算字体大小
        current_font_size = 1
        best_size = current_font_size
        best_height = 0
        
        # 逐步增加字体大小直到达到目标高度
        for size in range(1, 500):
            font.setPointSize(size)
            painter.setFont(font)
            rect = painter.boundingRect(pixmap.rect(), Qt.AlignCenter, text)
            
            # 记录最接近目标高度但不超过的大小
            if rect.height() <= target_height:
                best_size = size
                best_height = rect.height()
            else:
                break
        
        # 保存最佳字体大小
        self.font_size = best_size
        
        # 重新计算最终边界框
        font.setPointSize(self.font_size)
        painter.setFont(font)
        final_rect = painter.boundingRect(pixmap.rect(), Qt.AlignCenter, text)
        
        painter.end()
        return final_rect.width()
    # def calc_font_size(self, text_height, text) -> float:
    #     # 创建一个临时的 QPixmap 作为绘图设备
    #     pixmap = QPixmap(1, 1)
    #     painter = QPainter(pixmap)
        
    #     font = painter.font()
    #     metrics = painter.fontMetrics()
        
    #     # 计算最佳字体大小
    #     target_height = text_height
        
    #     # 初始字体大小
    #     current_font_size = 10
        
    #     # 数字特有的高度计算（忽略descent）
    #     while True:
    #         font.setPointSize(current_font_size)
    #         painter.setFont(font)
    #         metrics = painter.fontMetrics()
            
    #         # 只考虑ascent部分（基线以上部分）
    #         if metrics.ascent() >= target_height:
    #             break
                
    #         current_font_size += 1
    #         if current_font_size > 500:
    #             break
        
    #     # 微调确保不超出
    #     while metrics.ascent() > target_height and current_font_size > 1:
    #         current_font_size -= 1
    #         font.setPointSize(current_font_size)
    #         painter.setFont(font)
    #         metrics = painter.fontMetrics()
        
    #     # 计算文本宽度（不需要乘以字符串长度）
    #     text_width = metrics.horizontalAdvance(text)
        
    #     painter.end()
        
    #     # 保存计算出的字体大小（如果需要）
    #     self.font_size = current_font_size
        
    #     return text_width

        # rect.setWidth(text_width)
        # x = (rect.width() - text_width) // 2+rect.left()
        # y = rect.height() +rect.top()# 基线在容器底部

    def update_boundingRect(self):
        super().update_boundingRect()
        
        self.prepareGeometryChange()

        def max_of_four(*args):
            max_value = args[0]
            for val in args:
                if max_value< val:
                    max_value = val
            return max_value
        def min_of_four(*args):
            min_value = args[0]
            for val in args:
                if min_value> val:
                    min_value = val
            return min_value

       

        new_topLeft    = self.mapToScene(self._head_pos)
        new_topRight   = self.mapToScene(self._topRight)
        new_bottomLeft = self.mapToScene(self._bottomLeft)
        new_bottomRight= self.mapToScene(self._end_pos)

        max_x = max_of_four(new_topLeft.x(),new_topRight.x(),new_bottomLeft.x(),new_bottomRight.x())
        max_y = max_of_four(new_topLeft.y(),new_topRight.y(),new_bottomLeft.y(),new_bottomRight.y())
        min_x = min_of_four(new_topLeft.x(),new_topRight.x(),new_bottomLeft.x(),new_bottomRight.x())
        min_y = min_of_four(new_topLeft.y(),new_topRight.y(),new_bottomLeft.y(),new_bottomRight.y())
        
        # w,h = (max_x-min_x)*1.1,(max_y-min_y)*1.1
        # left =min_x -  0.05*w
        # top = min_y -  0.05*h

        rect = QRectF(min_x,min_y,max_x-min_x,max_y-min_y)
        # rect = QRectF(left,top,w,h)
        
        self._sceneBoundingRect = rect

     
       

    def completed(self,construct_from_dict=False):
        if construct_from_dict:
            return super().completed(True)
       
        # tmp_pos         = self._center_pos
        # self._head_pos  = self._head_pos - tmp_pos
        # self._end_pos   = self._end_pos - tmp_pos
        # self._topRight  = self._topRight - tmp_pos
        # self._bottomleft  = self._bottomleft - tmp_pos
        # self._center_pos = QPointF(0,0)
        # self.m_pos_init = self.m_pos = tmp_pos
        # self.setTransformOriginPoint(0,0)


        self._head_pos = self._center_pos   - QPointF(self.getSize().width()/2.0,self.getSize().height()/2.0)
        tmp_pos     = self._head_pos
        self._end_pos    = self._center_pos + QPointF(self.getSize().width()/2.0,self.getSize().height()/2.0)
        self._topLeft    = self._head_pos
        self._bottomRight= self._end_pos
        self._topRight   = self._center_pos + QPointF(self.getSize().width()/2.0,-self.getSize().height()/2.0)
        self._bottomLeft = self._center_pos + QPointF(-self.getSize().width()/2.0,self.getSize().height()/2.0)
        
        self._bottomRight=self._bottomRight - self._topLeft
        self._end_pos    =self._bottomRight
        self._topRight   =self._topRight   - self._topLeft
        self._bottomLeft =self._bottomLeft - self._topLeft
        self._center_pos =self._center_pos - self._topLeft
        self._topLeft    =self._head_pos = QPointF(0,0)

        self.m_pos_init = self.m_pos       = tmp_pos
        
        self.setTransformOriginPoint(self._center_pos)
       


        super().completed()
    

    
    def setSize(self,w,h):
        self._scene_size.setWidth(w)
        self._scene_size.setHeight(h)
    def getSize(self)->QSizeF:
        return self._scene_size

    

    def transfer_pos(self,pos:QPointF):
        """鼠标移动时位置更新"""
        self._center_pos =  pos
        text_height_view =  self.width* self.m_scene.grid_size  / self.m_scene.scene_units_per_grid_x
        text_width_view  =  self.calc_font_size(text_height_view,self._context)
        self.height       =  text_width_view *self.m_scene.scene_units_per_grid_x/self.m_scene.grid_size 
        self._head_pos = self._center_pos - QPointF(self.width/2.0,self.height/2.0)
        self._end_pos  = self._center_pos + QPointF(self.width/2.0,self.height/2.0)
        self._scene_size.setWidth(abs(self._end_pos.x()-self._head_pos.x()))
        self._scene_size.setHeight(abs(self._end_pos.y()-self._head_pos.y()))
        self._topRight   =self._center_pos + QPointF(self.width/2.0,-self.height/2.0)
        self._bottomLeft =self._center_pos + QPointF(-self.width/2.0,self.height/2.0)


        
    def handle_context_change(self):
        self.width  =self.getSize().width()
        text_height_view =  self.width* self.m_scene.grid_size  / self.m_scene.scene_units_per_grid_x
        text_width_view  =  self.calc_font_size(text_height_view,self._context)
        self.height       =  text_width_view *self.m_scene.scene_units_per_grid_x/self.m_scene.grid_size 
        self._head_pos = self._center_pos - QPointF(self.width/2.0,self.height/2.0)
        self._end_pos  = self._center_pos + QPointF(self.width/2.0,self.height/2.0)
        self._scene_size.setWidth(abs(self._end_pos.x()-self._head_pos.x()))
        self._scene_size.setHeight(abs(self._end_pos.y()-self._head_pos.y()))
        self._topRight   =self._center_pos + QPointF(self.width/2.0,-self.height/2.0)
        self._bottomLeft =self._center_pos + QPointF(-self.width/2.0,self.height/2.0)    
        self._topLeft    =self._head_pos
        self._bottomRight=self._end_pos
        self.update_boundingRect()

    def transfer_head_pos(self,pos:QPointF):
        self._center_pos =  pos
        text_height_view =  self.width* self.m_scene.grid_size  / self.m_scene.scene_units_per_grid_x
        text_width_view  =  self.calc_font_size(text_height_view,self._context)
        self.height       =  text_width_view *self.m_scene.scene_units_per_grid_x/self.m_scene.grid_size 
        self._head_pos = self._center_pos - QPointF(self.width/2.0,self.height/2.0)
        self._end_pos  = self._center_pos + QPointF(self.width/2.0,self.height/2.0)
        self._scene_size.setWidth(abs(self._end_pos.x()-self._head_pos.x()))
        self._scene_size.setHeight(abs(self._end_pos.y()-self._head_pos.y()))
        self._topRight   =self._center_pos + QPointF(self.width/2.0,-self.height/2.0)
        self._bottomLeft =self._center_pos + QPointF(-self.width/2.0,self.height/2.0)
       
        self.completed()
        
    

    def change_position(self,pos):
        w ,h=self.getSize().width(),self.getSize().height()
        self._head_pos_last = self.mapToScene(self._topLeft)
    
        topLeft_local = self.mapFromScene(pos)
        bottomRight_local  =topLeft_local + QPointF(w,h)
        topRight_local =topLeft_local + QPointF(w,0)
        bottomLeft_local =topLeft_local + QPointF(0,h)

        # self._topRight   = self.mapToScene(topRight_local)
        # self._bottomLeft = self.mapToScene(bottomLeft_local)
        # self._end_pos  = self.mapToScene(end_pos_local)
        
        self._head_pos = self._topLeft = topLeft_local
        self._end_pos  = self._bottomRight = bottomRight_local
        self._topRight   = topRight_local
        self._bottomLeft = bottomLeft_local
        self._center_pos = (self._head_pos + self._end_pos)/2.0

    
        self.setTransformOriginPoint(self._center_pos)
        
        self.update_boundingRect()

        if self.is_has_child():
            for child in self.childItems():
                dpos= child.get_scene_topLeft() + pos-self._head_pos_last
                child.change_position(dpos)
        else:
            return

    def change_size(self,w,h):
    
        self.setSize(w,h)
        self.width = w
        text_height_view =  self.width* self.m_scene.grid_size  / self.m_scene.scene_units_per_grid_x
        text_width_view  =  self.calc_font_size(text_height_view,self._context)
        self.height       =  text_width_view *self.m_scene.scene_units_per_grid_x/self.m_scene.grid_size 

        self._end_pos  = self._head_pos + QPointF(self.width,self.height)
    
        self._center_pos = (self._head_pos + self._end_pos)/2.0
        self._topRight   = QPointF(self.width,0) + self._head_pos
        self._bottomLeft = QPointF(0,self.height) + self._head_pos
        self._scene_size.setWidth(abs(self._end_pos.x()-self._head_pos.x()))
        self._scene_size.setHeight(abs(self._end_pos.y()-self._head_pos.y()))
        self.width  =self.getSize().width()


        self._topLeft  = self._head_pos
        self._bottomRight = self._end_pos

        self.setTransformOriginPoint(self._center_pos)
        
        self.update_boundingRect()

        if self.is_has_child():
            x_scale,y_scale = self.scene_size.width()/self._scene_size_last.width() , self.scene_size.height()/self._scene_size_last.height()
            for child in self.childItems():
                p1 =    child.get_scene_topLeft()               - self.get_scene_topLeft()
                dpos_head = QPointF(p1.x()*x_scale ,p1.y()*y_scale)   
                p2 =    child.get_scene_bottomRight()                - self.get_scene_topLeft()
                dpos_end  = QPointF(p2.x()*x_scale ,p2.y()*y_scale)
                p3 =    child.get_scene_topRight()               - self.get_scene_topLeft()
                dpos_topRight = QPointF(p3.x()*x_scale,p3.y()*y_scale) 

                a = dpos_topRight - dpos_head
                b = dpos_topRight - dpos_end
                w = sqrt(a.x()*a.x() + a.y()*a.y())
                h = sqrt(b.x()*b.x() + b.y()*b.y())
               
                child.change_position(dpos_head+ self.get_scene_topLeft())
                child.change_size(w,h)
        else:
            return
    

    def check_hover(self,mouse_pos:QPointF):
        if self.is_moving() or not self.get_selectable():
            self.set_hover(False)
            return False
        super().check_hover(mouse_pos)
       
        pos =  self.mapFromScene(mouse_pos)
       
        if  self._head_pos.x() <= pos.x() <= self._topRight.x():
            if self._head_pos.y() <= pos.y() <= self._head_pos.y()+self._scene_size.height():
                self.set_hover(True)
                return True
        self.set_hover(False)
        return False
        
    
    def set_visibility(self, enable):
        if self.is_has_child():
            for item in self.childItems():
                item.set_visibility(enable)
        return super().set_visibility(enable)
    
    def paint(self,painter:QPainter,shine_flag):
        if self.get_visibility()==False:
            super().paint(painter,shine_flag)
            return

        if not (self.m_veiw_dirty_region.intersects(self.viewBoundingRect().toRect())):
            super().paint(painter,shine_flag)
            return
        if self._head_pos is None:
            return
        painter.save()
        color = self._color
        
        if  self.get_hover() or  self.is_in_group() and self._is_group_in_hover:
            color = QColor(14,248,236)
        
        center_pos_view=self.m_scene.sceneToView(self.get_scene_center_pos())
        # origin_pos_view=self.m_scene.sceneToView(self.get_scene_OriginPoint())
        h =            self._scene_size.width()  * (self.m_scene.grid_size ) / self.m_scene.scene_units_per_grid_x
        w =            self._scene_size.height() * (self.m_scene.grid_size ) / self.m_scene.scene_units_per_grid_y
        # text_pos = center_pos_view +QPointF(-w/2.0,h/2.0)
        # topleft =center_pos_view-QPointF(w/2.0,h/2.0)
        # bg_rect = QRectF(topleft.x(),topleft.y(),w,h)
        bg_rect =QRectF(-w/2.0 ,-h/2.0,w,h)
        # 设置大号字体
        font = QFont("Arial", self.font_size)  # 使用固定大字号
        font.setBold(True)
        painter.setFont(font)
       
         # 应用视图变换
        painter.translate(center_pos_view)
        angle =    self.sceneTransform().get_rotation_angle()
        painter.rotate(-angle)

        if self.get_line_width()>0:
            painter.setPen(QPen(color, self.get_line_width()))
            if self.get_fill():
                painter.setBrush(self._fill_color)
            painter.drawRect(bg_rect)
        else:
            painter.setPen(QPen(color, 1))
            if self.get_fill():
                painter.fillRect(bg_rect, self._fill_color)
            painter.setPen(QPen(color, self.get_line_width()))


        # 绘制背景
        # painter.fillRect(bg_rect, self.get_fill_color())
        
        # painter.drawText(text_pos, self.context)

        # 获取文本的精确边界框
        text_rect = painter.boundingRect(bg_rect, Qt.AlignCenter, self._context)
    
        # 直接绘制在计算好的位置
        painter.drawText(text_rect, Qt.AlignCenter, self._context)

        painter.restore()
        

        super().paint(painter,shine_flag)

    def clone(self):
        """深度克隆图元及其子图元"""

        # 创建当前图元的新实例（不复制父关系）
        cloned = text_element()
       
        
        # 复制核心属性
        cloned.m_pos = self.m_pos #值类型，赋值时自动创建独立副本（非引用）
        cloned.set_line_width(self.get_line_width())
        cloned.set_color(self.get_color())
        cloned.set_fill(self.get_fill())
        cloned.set_head_pos(self.get_head_pos())
        cloned.set_end_pos(self.get_end_pos())
        cloned.set_center_pos(self.get_center_pos())
        cloned._topRight   = self._topRight
        cloned._bottomLeft = self._bottomLeft
        cloned._topLeft   = self._topLeft
        cloned._bottomRight = self._bottomRight

        cloned.setSize(self.getSize().width(),self.getSize().height())

        cloned.setTransformOriginPoint(self.transformOriginPoint())
        cloned.setTransform(Transform(self.transform().m))
        cloned.m_angle      = self.m_angle
        cloned.m_angle_init = self.m_angle_init
        cloned.m_pos_init   = self.m_pos_init
        cloned.font_size    = self.font_size
        cloned._context      = self._context
        cloned.set_group_id(self.get_group_id())
        cloned.set_zValue(self.zValue())
        cloned.set_opacity(self.get_opacity())
     
        
        # 递归克隆子图元
        for child in self.childItems():
            child_clone = child.clone() 
            child_clone.m_parent = cloned
            cloned.m_children.add(child_clone)
            # cloned.geometryChangeToChild.connect(child_clone.handle_parent_move)

        return cloned

    def to_dict(self):
        """将图元转换为字典"""
        parent_id = self.m_parent.id() if self.m_parent else 0
        children_ids  =[]
        if self.m_children:
            for child in self.m_children:
                children_ids.append(child.id())

        
        angle =    self.sceneTransform().get_rotation_angle()
        print(f"id:{self.id()}angle{angle}")
        return {
            "id"   :self.id(),
            "name"   :self.get_name(),
            "type": self.type,
            "parent_id":parent_id,
            "children_ids":children_ids,
            "group_id":self._group_id,
            "center_pos": {"x": round(self.get_scene_center_pos().x(),3), "y": round(self.get_scene_center_pos().y(),3)},
            "origin_pos": {"x": round(self.get_scene_OriginPoint().x(),3), "y": round(self.get_scene_OriginPoint().y(),3)},
            "width"  : self._scene_size.width(),
            "height" : self._scene_size.height(),
            "rotate" : angle,
            "style"   : {
                         "stroke"     :color_to_str(self.get_color()),
                         "strokeWidth":self.get_line_width(),
                         "fill"       :self.get_fill(),
                         "fill_color" :color_to_str(self.get_fill_color()),
                         "font_size"  :self.font_size,
                         "opacity"    :self.get_opacity()
                         },
            "context":self._context,
            
            "zValue": self.zValue()
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建图元"""
        scene_center_pos = QPointF(data["center_pos"]["x"],data["center_pos"]["y"])
        scenr_origin_pos = QPointF(data["origin_pos"]["x"],data["origin_pos"]["y"])
        angle = data["rotate"]
        w = data["width"]
        h = data["height"]

        item = cls()
        
        item.setID(data["id"])
        item._set_name(data["name"])
        item.m_parent_id = data["parent_id"]
        item.m_children_ids = set(data["children_ids"])
        item._group_id = data["group_id"]
        item.set_fill(data["style"]["fill"])
        item.set_line_width(data["style"]["strokeWidth"])
        item.set_color(str_to_color( data["style"]["stroke"]) )
        item.setSize(w,h)
        item.set_fill_color(str_to_color(data["style"]["fill_color"]))
        item.set_opacity( data["style"]["opacity"] )
        item.m_angle_init = item.m_angle = angle
        item.font_size = data["style"]["font_size"]
        item._context   = data["context"]
        item.set_zValue(data["zValue"])
        
        
        t =Transform()
        dpos =scenr_origin_pos- scene_center_pos 
        t.translate(scene_center_pos)
      
        t.rotate(angle)
       
        item.m_origin =t.map_inverse(scenr_origin_pos)

        item.m_pos_init = item.m_pos = scene_center_pos
        

        item._center_pos   = QPointF(0,0)

        
        item._head_pos   = QPointF(-w/2.0  ,-h/2.0)
        item._end_pos    = QPointF(w/2.0   ,h/2.0)
        item._topRight   = QPointF(w/2.0   ,-h/2.0)
        item._bottomLeft = QPointF(-w/2.0  ,h/2.0)
        item._topLeft    = item._head_pos
        item._bottomRight= item._end_pos 

        t =Transform()
        t.rotate(angle)
    
        item.setTransform(t)
        return item



class image_element(base_element):
    count = 0

    def __init__(self,parent=None):
        super().__init__(parent=parent)
        self.parent= parent
        image_element.count += 1
        self.scene_size = QSizeF(400,400)
        self.type = "image"
        self.img_path = "res/H7.png"
        self.set_actived( True)
        self.set_selected(False)
           
    def __del__(self):
        print(f"销毁image图元 id:{self.id()} name：{self.get_name()}")
    
    def image_path(self):
        return self.img_path
    def set_image_path(self,path):
        if path:
            self.img_path = path
    
    def update_boundingRect(self):
        super().update_boundingRect()
        
        self.prepareGeometryChange()

        def max_of_four(*args):
            max_value = args[0]
            for val in args:
                if max_value< val:
                    max_value = val
            return max_value
        def min_of_four(*args):
            min_value = args[0]
            for val in args:
                if min_value> val:
                    min_value = val
            return min_value

        new_topLeft    = self.mapToScene(self._head_pos)
        new_topRight   = self.mapToScene(self._topRight)
        new_bottomLeft = self.mapToScene(self._bottomLeft)
        new_bottomRight= self.mapToScene(self._end_pos)

        max_x = max_of_four(new_topLeft.x(),new_topRight.x(),new_bottomLeft.x(),new_bottomRight.x())
        max_y = max_of_four(new_topLeft.y(),new_topRight.y(),new_bottomLeft.y(),new_bottomRight.y())
        min_x = min_of_four(new_topLeft.x(),new_topRight.x(),new_bottomLeft.x(),new_bottomRight.x())
        min_y = min_of_four(new_topLeft.y(),new_topRight.y(),new_bottomLeft.y(),new_bottomRight.y())
        


        rect = QRectF(min_x,min_y,max_x-min_x,max_y-min_y)

        self._sceneBoundingRect = rect

    def completed(self,construct_from_dict=False):
        if construct_from_dict:
            super().completed(True)
            return

        x_max =  max(self._head_pos.x(),self._end_pos.x())
        x_min =  min(self._head_pos.x(),self._end_pos.x())
        y_max =  max(self._head_pos.y(),self._end_pos.y())
        y_min =  min(self._head_pos.y(),self._end_pos.y())

        self._topLeft     =self._head_pos =QPointF(x_min,y_min)
        self._bottomRight =self._end_pos  =QPointF(x_max,y_max)
        self._center_pos  = (self._head_pos + self._end_pos)/2.0

     
        self.scene_size = QSizeF(x_max - x_min,y_max - y_min)

        self._topRight   =QPointF(x_min + self.scene_size.width(),y_min )
        self._bottomLeft =QPointF(x_min ,y_min + self.scene_size.height())


        tmp_pos = copy.deepcopy(self._center_pos)
        self._topLeft     =self._head_pos  = self._head_pos - tmp_pos
        self._bottomRight =self._end_pos  = self._end_pos - tmp_pos

        self._topRight  = self._topRight - tmp_pos
        self._bottomLeft  = self._bottomLeft - tmp_pos

        self._center_pos = QPointF(0,0)
        self.m_pos_init = self.m_pos = tmp_pos
        self.setTransformOriginPoint(0,0)
        super().completed()
    
 
    

    def check_hover(self,mouse_pos:QPointF):
        if self.is_moving() or not self.get_selectable():
            self.set_hover(False)
            return False
        super().check_hover(mouse_pos)
        pos =  self.mapFromScene(mouse_pos)
        if  self._head_pos.x() <= pos.x() <= self._topRight.x():
            if self._head_pos.y() <= pos.y() <= self._head_pos.y()+self.scene_size.height():
                self.set_hover(True)
                return True
        self.set_hover(False)
        return False


    def transfer_pos(self,pos:QPointF):
        
        self._head_pos  =pos
        w,h=self.scene_size.width(),self.scene_size.height()
        self._end_pos   = pos + QPointF(w,h)
        self._center_pos = (self._head_pos+self._end_pos)/2.0
    
    def transfer_end_pos(self,pos_end:QPointF):
        self._head_pos  =pos_end
        w,h=self.scene_size.width(),self.scene_size.height()
        self._end_pos   = pos_end + QPointF(w,h)
        self._center_pos = (self._head_pos+self._end_pos)/2.0
        self.completed()

    def change_position(self,pos):
        w ,h=self.getSize().width(),self.getSize().height()
        self._head_pos_last = self.mapToScene(self._head_pos)
        self._head_pos      = pos
        head_pos_local      = self.mapFromScene(pos)
        end_pos_local       = head_pos_local + QPointF(w,h)
        topRight_local      = head_pos_local + QPointF(w,0)
        bottomLeft_local    = head_pos_local + QPointF(0,h)
        
        self._topLeft     =self._head_pos  = head_pos_local
        self._bottomRight =self._end_pos   = end_pos_local
        self._topRight                     = topRight_local
        self._bottomLeft                   = bottomLeft_local
        self._center_pos  = (self._head_pos + self._end_pos)/2.0

        self.setTransformOriginPoint(self._center_pos)
        
        self.update_boundingRect()

        if self.is_has_child():
            for child in self.childItems():
                dpos= child.get_scene_topLeft() + pos - self._head_pos_last
                child.change_position(dpos)
        else:
            return

    def change_size(self,w,h):
        self._scene_size_last =copy.copy(self.scene_size)
        self.setSize(w,h)
        self._bottomRight =self._end_pos  =   QPointF(w,h) + self._head_pos
        self._center_pos = (self._head_pos + self._end_pos)/2.0
        self._topRight   = QPointF(w,0) + self._head_pos
        self._bottomLeft = QPointF(0,h) + self._head_pos

        self.setTransformOriginPoint(self._center_pos)
        
        self.update_boundingRect()

        if self.is_has_child():
            x_scale,y_scale = self.scene_size.width()/self._scene_size_last.width() , self.scene_size.height()/self._scene_size_last.height()
            for child in self.childItems():
                p1 =    child.get_scene_topLeft()               - self.get_scene_head_pos()
                dpos_head = QPointF(p1.x()*x_scale ,p1.y()*y_scale)   
                p2 =    child.get_scene_bottomRight()                - self.get_scene_head_pos()
                dpos_end  = QPointF(p2.x()*x_scale ,p2.y()*y_scale)
                p3 =    child.get_scene_topRight()               - self.get_scene_head_pos()
                dpos_topRight = QPointF(p3.x()*x_scale,p3.y()*y_scale) 

                a = dpos_topRight - dpos_head
                b = dpos_topRight - dpos_end
                w = sqrt(a.x()*a.x() + a.y()*a.y())
                h = sqrt(b.x()*b.x() + b.y()*b.y())
               
                child.change_position(dpos_head+ self.get_scene_head_pos())
                child.change_size(w,h)
        else:
            return
    




    def setSize(self,w,h):
        self.scene_size.setWidth(w)
        self.scene_size.setHeight(h)
        
    def getSize(self)->QSizeF:
        return self.scene_size
    
    
    def set_visibility(self, enable):
        if self.is_has_child():
            for item in self.childItems():
                item.set_visibility(enable)
        return super().set_visibility(enable)
    
    def paint(self,painter:QPainter,shine_flag):
        if self.get_visibility()==False:
            super().paint(painter,shine_flag)
            return

        if not (self.m_veiw_dirty_region.intersects(self.viewBoundingRect().toRect())):
            super().paint(painter,shine_flag)
            return
        if self._head_pos is None:
            return
        painter.save()

        def create_pen_style(color):
            # 创建基础画笔
            pen = QPen()
            
            # 设置画笔属性
            pen.setColor(color)  # 黑色钢笔
            pen.setWidth(1)                # 线宽3像素
            
            # 格式: [实线长度, 空白长度, 点长度, 空白长度] 重复
            dash_pattern = [8, 4, 2, 4]  # 8像素实线 - 4像素空白 - 2像素点 - 4像素空白
            
            pen.setDashPattern(dash_pattern)  # 设置自定义虚线模式
            pen.setStyle(Qt.CustomDashLine)   # 必须设置为自定义虚线模式
            
            # 优化端点样式
            pen.setCapStyle(Qt.RoundCap)      # 圆角端点
            pen.setJoinStyle(Qt.RoundJoin)    # 圆角连接
            return pen
        
        color = self.get_color()
        if self.get_selected()  or self.get_hover() or self._is_group_in_hover :
            color = QColor(14,248,236)

        pen = create_pen_style(color)
       
        painter.setPen(pen)

        
        center_pos_view=self.m_scene.sceneToView(self.get_scene_center_pos())
        h =            self.scene_size.width()  * (self.m_scene.grid_size ) / self.m_scene.scene_units_per_grid_x
        w =            self.scene_size.height() * (self.m_scene.grid_size ) / self.m_scene.scene_units_per_grid_y
        bg_rect =QRectF(-w/2.0 ,-h/2.0,w,h)
         # 应用视图变换
        painter.translate(center_pos_view)
        angle =    self.sceneTransform().get_rotation_angle()
        painter.rotate(-angle)

        
        if self.get_selected()  or self.get_hover() or self._is_group_in_hover :
            painter.drawRect(bg_rect)
      
        pixmap_rect  = bg_rect.toRect()
     
        pixmap = QPixmap(self.img_path)  # 加载图片
        if not pixmap.isNull():
            # 在目标矩形内绘制图片（保持原始比例）
            painter.drawPixmap(pixmap_rect, pixmap)

        painter.restore()
        

        super().paint(painter,shine_flag)



    def clone(self):
        """深度克隆图元及其子图元"""

        # 创建当前图元的新实例（不复制父关系）
        cloned = image_element()
       
        # 复制核心属性
        cloned.m_pos = self.m_pos #值类型，赋值时自动创建独立副本（非引用）
        cloned.set_line_width(self.get_line_width())
        cloned.set_color(self.get_color())
        cloned.set_fill(self.get_fill())
        cloned.set_fill_color(self.get_fill_color())
        cloned.set_opacity(self.get_opacity())
        cloned.set_head_pos(self.get_head_pos())
        cloned.set_end_pos(self.get_end_pos())
        cloned.set_center_pos(self.get_center_pos())
        cloned.set_image_path(self.image_path())
        cloned._topRight   = self._topRight
        cloned._bottomLeft = self._bottomLeft
        cloned._topLeft   = self._topLeft
        cloned._bottomRight = self._bottomRight
        cloned.setSize(self.getSize().width(),self.getSize().height())
        cloned.setTransformOriginPoint(self.transformOriginPoint())
        cloned.setTransform(Transform(self.transform().m))
        cloned.m_angle      = self.m_angle
        cloned.m_angle_init = self.m_angle_init
        cloned.m_pos_init   = self.m_pos_init

        cloned.set_group_id(self.get_group_id())

        cloned.set_zValue(self.zValue())
        # 递归克隆子图元
        for child in self.childItems():
            child_clone = child.clone() 
            child_clone.m_parent = cloned
            cloned.m_children.add(child_clone)
            # cloned.geometryChangeToChild.connect(child_clone.handle_parent_move)

        return cloned

    def to_dict(self):
        """将图元转换为字典"""
        parent_id = self.m_parent.id() if self.m_parent else 0
        children_ids  =[]
        if self.m_children:
            for child in self.m_children:
                children_ids.append(child.id())

        
        angle =    self.sceneTransform().get_rotation_angle()
        print(f"id:{self.id()}angle{angle}")
        return {
            "id"   :self.id(),
            "name"   :self.get_name(),
            "type": self.type,
            "image_path":self.img_path,
            "parent_id":parent_id,
            "children_ids":children_ids,
            "group_id":self._group_id,
            "center_pos": {"x": round(self.get_scene_center_pos().x(),3), "y": round(self.get_scene_center_pos().y(),3)},
            "origin_pos": {"x": round(self.get_scene_OriginPoint().x(),3), "y": round(self.get_scene_OriginPoint().y(),3)},
            "width"  : self.scene_size.width(),
            "height" : self.scene_size.height(),
            "rotate" : angle,
            "style"   : {"stroke":color_to_str(self.get_color()),
                         "strokeWidth":self.get_line_width(),
                         "fill":self.get_fill(),
                         "fill_color" :color_to_str(self.get_fill_color()),
                         "opacity":self.get_opacity()},
            "zValue": self.zValue()
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建图元"""
        scene_center_pos = QPointF(data["center_pos"]["x"],data["center_pos"]["y"])
        scene_origin_pos = QPointF(data["origin_pos"]["x"],data["origin_pos"]["y"])
        angle = data["rotate"]
        w     = data["width" ]
        h     = data["height"]

        item = cls()
       
        item.setID(data["id"])
        item._set_name(data["name"])
        item.img_path =data["image_path"]
        item.m_parent_id = data["parent_id"]
        item.m_children_ids = set(data["children_ids"])
        item._group_id = data["group_id"]
        item.set_fill(data["style"]["fill"])
        item.set_fill_color(str_to_color(data["style"]["fill_color"]))
        item.set_line_width(data["style"]["strokeWidth"])
        item.set_color(str_to_color( data["style"]["stroke"]) )
        item.set_opacity( data["style"]["opacity"] )
        item.setSize(w,h)
        item.m_angle_init = item.m_angle = angle
        item.set_zValue(data["zValue"])
        
        t =Transform()
        dpos =scene_origin_pos- scene_center_pos 
        t.translate(scene_center_pos)
      
        t.rotate(angle)

        item.m_origin =t.map_inverse(scene_origin_pos)

        item.m_pos_init = item.m_pos = scene_center_pos

        item._center_pos   = QPointF(0,0)

        item._head_pos   = QPointF(-w/2.0  ,-h/2.0)
        item._end_pos    = QPointF(w/2.0   ,h/2.0)
        item._topRight   = QPointF(w/2.0   ,-h/2.0)
        item._bottomLeft = QPointF(-w/2.0  ,h/2.0)
        item._topLeft    = item._head_pos
        item._bottomRight= item._end_pos 
       
        t =Transform()
       
        t.rotate(angle)
        
        item.setTransform(t)

        return item
        