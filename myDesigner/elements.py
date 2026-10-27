import os

from .element import*

# 图元析构时的调试输出。默认关闭：一次场景加载会产生上千行日志，
# 需要排查时可设置环境变量 RACK_DEBUG_DESTROY=1 打开。
_DEBUG_DESTROY = os.environ.get("RACK_DEBUG_DESTROY", "") == "1"


def _log_destroy(kind: str, item) -> None:
    if _DEBUG_DESTROY:
        print(f"销毁{kind} id:{item.id()} name：{item.get_name()}")



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
        _log_destroy("line", self)

    def update_boundingRect(self):
        super().update_boundingRect()
        self.prepareGeometryChange()
        
        rect=QRectF(self.mapToScene(self._head_pos),self.mapToScene(self._end_pos))

        w,h=rect.width(), rect.height()
        x,y= rect.topLeft().toTuple()
        if w<=0.0 and h<=0.0:
            rect = QRectF(x+w,y+ h,-w,-h)
        elif w<=0.0:
            rect = QRectF(x+w,y,-w,h)
        elif h<=0.0:
            rect = QRectF(x,y+h,w,-h)
        
        if abs(rect.width())<6.0 and abs(rect.height())>6.0:
            rect.setWidth(60.0)
            rect.setLeft(rect.left()-30.0)
        elif abs(rect.width())>6.0 and abs(rect.height())<6.0:
            rect.setHeight(60.0)
            rect.setTop(rect.top()-30.0)
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

    def change_end_pos_to_target_scenePos(self,pos):
        pass
    


    def change_position(self,pos):
        """"属性设置移动位置"""
        w ,h=self.getSize().width(),self.getSize().height()
   
        # print(self.getSize())
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

        self.setTransformOriginPoint(self.mapFromScene(self.get_scene_transformOriginPoint() + pos - self._head_pos_last))

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

        # self.setTransformOriginPoint(self._center_pos)
        
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
        # 复制名称：复制/粘贴时据此保留成员名，只替换组名前缀
        cloned._name = self._name
      
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

        # 圆角半径，单位为场景坐标（与 width/height 一致），0 表示直角
        self._corner_radius = 0.0
        
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
        _log_destroy("rect", self)
       
    
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

    def change_position(self,pos:QPointF):
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
  
        
        self.setTransformOriginPoint(self.mapFromScene(self.get_scene_transformOriginPoint() + pos - self._head_pos_last))

        self._topLeft     =self._head_pos  = head_pos_local
        self._bottomRight =self._end_pos   = end_pos_local
        self._topRight                     = topRight_local
        self._bottomLeft                   = bottomLeft_local
        self._center_pos  = (self._head_pos + self._end_pos)/2.0

        
        
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
    
    def get_corner_radius(self) -> float:
        """圆角半径，单位为场景坐标（与宽高一致），0 表示直角。"""
        return self._corner_radius

    def set_corner_radius(self, radius: float):
        try:
            radius = float(radius)
        except (TypeError, ValueError):
            return
        radius = max(0.0, radius)
        if self._corner_radius != radius:
            self._corner_radius = radius
            self.prepareDirtyChange()

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

        radius = self.get_corner_radius()
        if radius > 0:
            # 圆角半径与宽高使用同一场景单位；视图使用 AGV 地图的坐标约定，
            # 场景 x 对应画笔 y、场景 y 对应画笔 x，换算后需分别限制在短边一半内
            radius_x = radius * self.m_scene.grid_size / self.m_scene.scene_units_per_grid_y
            radius_y = radius * self.m_scene.grid_size / self.m_scene.scene_units_per_grid_x
            radius_x = min(radius_x, w / 2.0)
            radius_y = min(radius_y, h / 2.0)
            painter.drawRoundedRect(bg_rect, radius_x, radius_y)
        else:
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
        # 复制名称：复制/粘贴时据此保留成员名，只替换组名前缀
        cloned._name = self._name
       
        # 复制核心属性
        cloned.m_pos = self.m_pos #值类型，赋值时自动创建独立副本（非引用）
        cloned.set_line_width(self.get_line_width())
        cloned.set_color(self.get_color())
        cloned.set_fill(self.get_fill())
        cloned.set_fill_color(self.get_fill_color())
        cloned.set_opacity(self.get_opacity())
        cloned.set_corner_radius(self.get_corner_radius())
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

        # print(f"id:{self.id()}angle{angle}")

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
                         "opacity":self.get_opacity(),
                         "cornerRadius":self.get_corner_radius()},
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
        item.set_corner_radius( data["style"].get("cornerRadius", 0.0) )
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
        _log_destroy("group", self)

    # ------------------------------------------------------------------
    # Member names follow the group name
    #
    # A group prefixes its own name plus ``_`` onto every member name.  Nested
    # groups are prefixed too, which also prefixes their members, so the full
    # name of a nested element reads like ``组_1_组_2_矩形_3``.  Dissolving a
    # group strips exactly one prefix level again.
    # ------------------------------------------------------------------
    def _member_name_prefix(self) -> str:
        name = str(self.get_name() or "")
        return f"{name}_" if name else ""

    @staticmethod
    def _replace_name_prefix(item, old_prefix: str, new_prefix: str) -> None:
        """Rewrite ``old_prefix`` in every name of ``item``'s subtree."""

        name = str(item.get_name() or "")
        if old_prefix and name.startswith(old_prefix):
            new_name = new_prefix + name[len(old_prefix):]
            if new_name:
                item._rename_item(new_name)
        for child in list(item.m_children):
            group_element._replace_name_prefix(child, old_prefix, new_prefix)

    @staticmethod
    def _prefix_name_subtree(item, prefix: str) -> None:
        """Prepend ``prefix`` to every name of ``item``'s subtree."""

        name = str(item.get_name() or "")
        if not name.startswith(prefix):
            item._rename_item(prefix + name)
        for child in list(item.m_children):
            group_element._prefix_name_subtree(child, prefix)

    def apply_member_name_prefix(self) -> None:
        """Prefix ``<group name>_`` onto all members and nested members."""

        prefix = self._member_name_prefix()
        if not prefix:
            return
        for child in list(self.m_children):
            self._prefix_name_subtree(child, prefix)

    def _remove_member_name_prefix(self) -> None:
        """Restore the member names when the group is dissolved."""

        prefix = self._member_name_prefix()
        if not prefix:
            return
        for child in list(self.m_children):
            self._replace_name_prefix(child, prefix, "")

    def set_name(self, name) -> bool:
        """Rename the group and carry the new prefix over to its members."""

        old_name = self.get_name()
        if not super().set_name(name):
            return False
        new_name = self.get_name()
        if old_name and new_name and new_name != old_name and self.m_children:
            old_prefix = f"{old_name}_"
            new_prefix = f"{new_name}_"
            for child in list(self.m_children):
                self._replace_name_prefix(child, old_prefix, new_prefix)
        return True

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

        # Members (and nested members) carry the group name as prefix.
        self.apply_member_name_prefix()


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

        # Restore the member names before the group loses its children.
        self._remove_member_name_prefix()

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
            # 运行态分组不绘制虚线框，但必须像其他图元一样在每帧绘制时清掉
            # 变换缓存标记，否则 is_moving() 恒为 True，check_hover() 会跳过
            # 该分组，鼠标点击电柜等分组时永远选不中。
            self._reset_moving_flag()
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
            pen.setStyle(Qt.CustomDashLine)   # 必须设置为自定义虚线模式
            
            # 优化端点样式
            pen.setCapStyle(Qt.RoundCap)      # 圆角端点
            pen.setJoinStyle(Qt.RoundJoin)    # 圆角连接
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
        # 复制名称：复制/粘贴时据此保留组名与成员名，只替换组名前缀
        cloned._name = self._name
       
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
        _log_destroy("circle", self)

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
        
        self.setTransformOriginPoint(self.mapFromScene(self.get_scene_transformOriginPoint() + pos - self._head_pos_last))
        self._head_pos    = self._topLeft     = topLeft_local
        self._end_pos     = self._bottomRight = bottomRight_local
        self._topRight    = topRight_local
        self._bottomLeft  = bottomLeft_local
        self._center_pos = (self._head_pos + self._end_pos)/2.0

        # self.setTransformOriginPoint(self._center_pos)
        
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
        # 复制名称：复制/粘贴时据此保留成员名，只替换组名前缀
        cloned._name = self._name
      
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
    #: 内容变化时是否把文本框左侧钉住（False 恢复成左右对称扩展的老行为）
    keep_left_on_context_change = True
    contextChanged = Signal(str)
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

    @Property(str, notify=contextChanged)
    def context(self):
        return self._context
        
    @context.setter
    def context(self, str):
        new_str = " " + str + " "
        if self._context != new_str:
            self._context = new_str
            self.contextChanged.emit(new_str)

    def __del__(self):
        _log_destroy("text", self)

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


        
    def anchor_left_edge(self, old_height, new_height):
        """内容长度变化后，让屏幕上左侧那条边保持不动，只向右（或向左）伸缩。

        文本的长度方向是局部 y（不是局部 x）：
        ``is_use_for_agv_map`` 为 True 时局部 +y 映射到视图左侧，
        普通模式下局部 +y 映射到视图上方。所以先用 ``sceneToView`` 判断
        两条候选边哪条在屏幕上更靠左，再把 ``_center_pos`` 沿局部 y 平移
        半个长度差。全程在局部坐标里算，图元转过多少度都成立。
        """
        if not self.keep_left_on_context_change:
            return
        if not old_height or abs(new_height - old_height) < 1e-9:
            return

        half_old = old_height / 2.0
        half_new = new_height / 2.0

        try:
            plus_view  = self.m_scene.sceneToView(self.mapToScene(QPointF(0, half_old)))
            minus_view = self.m_scene.sceneToView(self.mapToScene(QPointF(0, -half_old)))
            sign = 1.0 if plus_view.x() <= minus_view.x() else -1.0
        except AttributeError:
            # 没有场景（单元测试里裸建图元）时按 agv 地图的约定：局部 +y 在左侧
            sign = 1.0

        # 钉住局部 y = center_y + sign*half 这条边：center_y' = center_y + sign*(half_old-half_new)
        delta = sign * (half_old - half_new)
        self._center_pos = QPointF(self._center_pos.x(), self._center_pos.y() + delta)

    def handle_context_change(self):
        old_height = self._scene_size.height()
        self.width  =self.getSize().width()
        text_height_view =  self.width* self.m_scene.grid_size  / self.m_scene.scene_units_per_grid_x
        text_width_view  =  self.calc_font_size(text_height_view,self._context)
        self.height       =  text_width_view *self.m_scene.scene_units_per_grid_x/self.m_scene.grid_size 
        # 内容变了：左侧钉住，不要左右对称撑开
        self.anchor_left_edge(old_height, self.height)
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
        
        self.setTransformOriginPoint(self.mapFromScene(self.get_scene_transformOriginPoint() + pos - self._head_pos_last))
        self._head_pos = self._topLeft = topLeft_local
        self._end_pos  = self._bottomRight = bottomRight_local
        self._topRight   = topRight_local
        self._bottomLeft = bottomLeft_local
        self._center_pos = (self._head_pos + self._end_pos)/2.0

    
        # self.setTransformOriginPoint(self._center_pos)
        
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
       
        if  self._topLeft.x() <= pos.x() <= self._topRight.x():
            if self._topLeft.y() <= pos.y() <= self._bottomRight.y():
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
        # 复制名称：复制/粘贴时据此保留成员名，只替换组名前缀
        cloned._name = self._name
       
        
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
        # print(f"id:{self.id()}angle{angle}")
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
        
        # 获取正确的图片路径
        if getattr(sys, 'frozen', False):
            # 打包后的可执行文件路径（如 PyInstaller）
            base_dir = os.path.dirname(sys.executable)
        else:
            # 脚本文件所在路径
            base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 构建正确的图片路径
        
        self.img_path = os.path.join(base_dir, "res", "H7.png")
        
        self.set_actived( True)
        self.set_selected(False)
           
    def __del__(self):
        _log_destroy("image", self)
    
    def image_path(self):
        # return self.img_path
        if getattr(sys, 'frozen', False):
           

            # 打包后的可执行文件路径（如 PyInstaller）
            base_dir = os.path.dirname(sys.executable)
        else:
            # 脚本文件所在路径
            base_dir = os.path.dirname(os.path.abspath(__file__))
        # 统一为正斜杠，保证在 macOS/Linux 下也能打开 Windows 保存的工程
        return os.path.relpath(self.img_path,base_dir).replace(os.sep, "/") #相对路径

    def set_image_path(self,path):
        """传入相对路径"""
        if getattr(sys, 'frozen', False):

            try:
            # PyInstaller 创建的临时文件夹，包含所有添加的资源文件
                base_dir = sys._MEIPASS
            except AttributeError:
                # 如果 _MEIPASS 不存在，回退到可执行文件目录
                base_dir = os.path.dirname(sys.executable)
            # 打包后的可执行文件路径（如 PyInstaller）
            # base_dir = os.path.dirname(sys.executable)
        else:
            # 脚本文件所在路径
            base_dir = os.path.dirname(os.path.abspath(__file__))

        if path:
            # JSON 中的路径可能带 Windows 反斜杠，先统一为正斜杠再拼接
            path = path.replace("\\", "/")
            self.img_path = os.path.normpath(os.path.join(base_dir, path))
    
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
        
        self.setTransformOriginPoint(self.mapFromScene(self.get_scene_transformOriginPoint() + pos - self._head_pos_last))
        self._topLeft     =self._head_pos  = head_pos_local
        self._bottomRight =self._end_pos   = end_pos_local
        self._topRight                     = topRight_local
        self._bottomLeft                   = bottomLeft_local
        self._center_pos  = (self._head_pos + self._end_pos)/2.0

        # self.setTransformOriginPoint(self._center_pos)
        
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
        # 关键：启用渲染提示以提高绘制质量
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
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
        # 获取Pixmap的高DPI版本（如果系统支持）
        pixmap.setDevicePixelRatio(2.0)  # 设置设备像素比率
        # scaled = pixmap.scaled(
        #     int(pixmap_rect.width()), 
        #     int(pixmap_rect.height()),
        #     Qt.KeepAspectRatio,
        #     Qt.SmoothTransformation
        # )
        if not pixmap.isNull():
            # 在目标矩形内绘制图片（保持原始比例）
            painter.drawPixmap(pixmap_rect, pixmap)

        painter.restore()
        

        super().paint(painter,shine_flag)



    def clone(self):
        """深度克隆图元及其子图元"""

        # 创建当前图元的新实例（不复制父关系）
        cloned = image_element()
        # 复制名称：复制/粘贴时据此保留成员名，只替换组名前缀
        cloned._name = self._name
       
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
        # print(f"id:{self.id()}angle{angle}")
        return {
            "id"   :self.id(),
            "name"   :self.get_name(),
            "type": self.type,
            "image_path":self.image_path(),
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
        # item.img_path = data["image_path"]
        item.set_image_path(data["image_path"])
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




class triangle_element(rect_element):
    """三角形图元。

    包围盒、变换、属性与序列化完全复用 ``rect_element``，只在绘制和命中
    测试时使用三角形轮廓。局部坐标以中心为原点，默认形状为顶点朝上的
    等腰三角形（场景 y 轴在视图中向上）：

        apex  = ( 0,      h/2)
        left  = (-w/2,   -h/2)
        right = ( w/2,   -h/2)

    包围盒仍然保持为矩形。
    """

    count = 0

    def __init__(self, *args, **kwargs):
        triangle_element.count += 1
        super().__init__(*args, **kwargs)
        self.type = "triangle"
        self._vertices_local: List[QPointF] = []
        self._draft_scene_vertices: List[QPointF] = []
        if not self.constructed_by_draw:
            self._vertices_local = self._default_local_vertices(
                self.scene_size.width(), self.scene_size.height()
            )
            self._refresh_local_bounds()

    def __del__(self):
        _log_destroy("triangle", self)

    def _default_local_vertices(self, width, height) -> List[QPointF]:
        """Return the legacy apex-up triangle fitted into ``width``/``height``."""
        width = float(width)
        height = float(height)
        return [
            QPointF(0.0, height / 2.0),
            QPointF(-width / 2.0, -height / 2.0),
            QPointF(width / 2.0, -height / 2.0),
        ]

    @staticmethod
    def _parse_scene_vertices(value) -> List[QPointF]:
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            return []
        vertices = []
        for point in value:
            if not isinstance(point, dict):
                return []
            try:
                vertices.append(QPointF(float(point["x"]), float(point["y"])))
            except (KeyError, TypeError, ValueError):
                return []
        return vertices

    @staticmethod
    def _bounding_rect(points: List[QPointF]) -> QRectF:
        if not points:
            return QRectF()
        xs = [point.x() for point in points]
        ys = [point.y() for point in points]
        return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def _local_bounding_rect(self) -> QRectF:
        return self._bounding_rect(self._vertices_local)

    def _refresh_local_bounds(self):
        """Keep the rect-compatible bbox fields in sync with the vertices."""
        rect = self._local_bounding_rect()
        if self._vertices_local:
            self._head_pos = rect.topLeft()
            self._end_pos = rect.bottomRight()
            self._topLeft = self._head_pos
            self._bottomRight = self._end_pos
            self._topRight = QPointF(rect.right(), rect.top())
            self._bottomLeft = QPointF(rect.left(), rect.bottom())
            self._center_pos = rect.center()
            self.scene_size = QSizeF(rect.width(), rect.height())
        else:
            self._head_pos = None
            self._end_pos = None
            self._topLeft = None
            self._bottomRight = None
            self._topRight = None
            self._bottomLeft = None
            self._center_pos = None
            self.scene_size = QSizeF(0.0, 0.0)

    def _apply_scene_vertices(self, scene_vertices: List[QPointF], angle: float = 0.0,
                              origin_scene: Optional[QPointF] = None):
        """Define the triangle from three scene points.

        The local origin is normalised to the centre of the local bounding
        box so the inherited position/rotation helpers keep working.  When
        the triangle already owns vertices its current local transform is
        kept, otherwise a fresh rotation by ``angle`` is used.  Keeping the
        transform matters for triangles that live inside a rotated group:
        the group supplies its own rotation and the child must only adopt
        the requested parent-space points.
        """
        points = [QPointF(point) for point in scene_vertices]
        if len(points) != 3:
            return False

        parent = self.m_parent
        if parent is not None:
            parent_points = [parent.mapFromScene(point) for point in points]
        else:
            parent_points = points
        if self._vertices_local:
            transform = self.m_transform
        else:
            transform = Transform()
            transform.rotate(angle)

        local_points = [transform.map_inverse(point) for point in parent_points]
        local_center = self._bounding_rect(local_points).center()
        self._vertices_local = [point - local_center for point in local_points]

        # Solve Q = m_pos + transform(vertex) for m_pos.  Using the first
        # vertex keeps this correct even when the transform contains a
        # translation (rotating around a custom origin produces one).
        self.m_pos_init = self.m_pos = parent_points[0] - transform.map(
            self._vertices_local[0]
        )
        self.m_angle_init = self.m_angle = angle
        self.m_transform = transform
        # 直接赋值 m_transform 绕过了 setTransform()，这里手动让变换缓存失效
        self.invalidate_transform_cache(mark_dirty=False)

        if origin_scene is not None:
            origin_parent = (
                parent.mapFromScene(origin_scene) if parent is not None else origin_scene
            )
            self.m_origin = transform.map_inverse(origin_parent - self.m_pos)
        else:
            self.m_origin = QPointF(0.0, 0.0)

        self._draft_scene_vertices = []
        self._refresh_local_bounds()
        self.update_boundingRect()
        return True

    def get_scene_vertices(self) -> List[QPointF]:
        # Use the live transform instead of the cached ``mapToScene`` path so
        # serialization and group/property edits never depend on whether a
        # paint pass has already refreshed ``_Transform_last``.
        transform = self.sceneTransform()
        return [transform.map(point) for point in self._vertices_local]

    def get_local_vertices(self) -> List[QPointF]:
        return [QPointF(point) for point in self._vertices_local]

    def set_scene_vertices(self, scene_vertices: List[QPointF]) -> bool:
        """Replace the three vertices while preserving the current angle."""
        origin_scene = self.get_scene_OriginPoint() if self._vertices_local else None
        return self._apply_scene_vertices(
            scene_vertices, angle=self.m_angle, origin_scene=origin_scene
        )

    def set_default_geometry(self, top_left: QPointF, width: float, height: float):
        """Create the legacy apex-up triangle inside an axis aligned rect."""
        center = QPointF(
            float(top_left.x()) + float(width) / 2.0,
            float(top_left.y()) + float(height) / 2.0,
        )
        local_vertices = self._default_local_vertices(width, height)
        scene_vertices = [center + point for point in local_vertices]
        self._apply_scene_vertices(scene_vertices, angle=0.0)
        self.completed()

    def get_draw_vertices(self) -> List[QPointF]:
        return [QPointF(point) for point in self._draft_scene_vertices]

    def add_draw_vertex(self, scene_pos: QPointF) -> bool:
        """Append one click-position; the third click finishes the triangle."""
        if not self.get_actived() or len(self._draft_scene_vertices) >= 3:
            return False

        self._draft_scene_vertices.append(QPointF(scene_pos))
        if len(self._draft_scene_vertices) == 3:
            self._apply_scene_vertices(self._draft_scene_vertices, angle=0.0)
            self.completed()
        return True

    def transfer_head_pos(self, pos: QPointF):
        self.add_draw_vertex(pos)

    def transfer_end_pos(self, pos: QPointF):
        self.add_draw_vertex(pos)

    def update_boundingRect(self):
        base_element.update_boundingRect(self)
        self.prepareGeometryChange()

        points = self.get_scene_vertices()
        if not points:
            self._sceneBoundingRect = QRectF()
            return

        xs = [point.x() for point in points]
        ys = [point.y() for point in points]
        self._sceneBoundingRect = QRectF(
            min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        )

    def completed(self, construct_from_dict=False):
        if construct_from_dict:
            base_element.completed(self, True)
            return True
        if not self._vertices_local:
            return False
        base_element.completed(self, False)
        return True

    def change_position(self, pos: QPointF):
        """Move the whole triangle so its bbox top-left follows the property box."""
        if not self._vertices_local:
            return
        old_head = self.get_scene_head_pos()
        if self.m_parent is not None:
            delta = self.m_parent.mapFromScene(pos) - self.m_parent.mapFromScene(old_head)
        else:
            delta = QPointF(pos) - old_head
        self.m_pos = self.m_pos + delta
        self.m_pos_init = self.m_pos_init + delta
        self.update_boundingRect()

    def change_size(self, width, height):
        """Scale the vertices so their bbox matches the requested size.

        The scale is anchored at the local bounding-box top-left, matching
        ``rect_element.change_size`` semantics: group resizing first moves a
        child to its scaled top-left and then calls ``change_size``.  Scaling
        around the local origin (the bbox centre) would move the top-left and
        make triangles drift/look wrong inside a resized group.
        """
        rect = self._local_bounding_rect()
        if rect.width() <= 0.0 or rect.height() <= 0.0:
            return
        width = float(width)
        height = float(height)
        if width <= 0.0 or height <= 0.0:
            return

        sx = width / rect.width()
        sy = height / rect.height()
        anchor = rect.topLeft()

        def scale_point(point: QPointF) -> QPointF:
            return QPointF(
                anchor.x() + (point.x() - anchor.x()) * sx,
                anchor.y() + (point.y() - anchor.y()) * sy,
            )

        self._vertices_local = [scale_point(point) for point in self._vertices_local]
        # Keep the rotation origin at the same relative place inside the
        # triangle so later rotations still pivot around the same point.
        self.m_origin = scale_point(self.m_origin)
        self._refresh_local_bounds()
        self.update_boundingRect()

        for child in list(self.childItems()):
            local_head = self.mapFromScene(child.get_scene_head_pos())
            new_head = self.mapToScene(scale_point(local_head))
            child.change_position(new_head)
            child.change_size(
                child.getSize().width() * sx, child.getSize().height() * sy
            )

    def _triangle_path(self) -> QPainterPath:
        """Local-coordinate triangle outline built from the three vertices."""
        path = QPainterPath()
        if not self._vertices_local:
            return path
        path.moveTo(self._vertices_local[0])
        for point in self._vertices_local[1:]:
            path.lineTo(point)
        path.closeSubpath()
        return path

    def check_hover(self, mouse_pos: QPointF):
        if self.is_moving() or not self.get_selectable() or not self._vertices_local:
            self.set_hover(False)
            return False

        base_element.check_hover(self, mouse_pos)

        pos = self.mapFromScene(mouse_pos)
        path = self._triangle_path()
        if self.get_fill():
            hovered = path.contains(pos)
        else:
            # Match rect_element's 10-unit hover margin while following the
            # triangle outline instead of the rectangular bounding box.
            stroker = QPainterPathStroker()
            stroker.setWidth(max(10.0, float(self.get_line_width())))
            hovered = stroker.createStroke(path).contains(pos)

        self.set_hover(bool(hovered))
        return bool(hovered)

    def paint(self, painter: QPainter, shine_flag):
        if self.get_visibility() == False:
            base_element.paint(self, painter, shine_flag)
            return

        if not (self.m_veiw_dirty_region.intersects(self.viewBoundingRect().toRect())):
            base_element.paint(self, painter, shine_flag)
            return
        if not self._vertices_local:
            base_element.paint(self, painter, shine_flag)
            return

        painter.save()
        color = self._color
        if self.get_hover() or self.is_in_group() and self._is_group_in_hover:
            color = QColor(14, 248, 236)

        view_points = [
            self.m_scene.sceneToView(point) for point in self.get_scene_vertices()
        ]
        path = QPainterPath(view_points[0])
        for point in view_points[1:]:
            path.lineTo(point)
        path.closeSubpath()

        fill_color = self._fill_color
        painter.setBrush(fill_color if self.get_fill() else Qt.NoBrush)
        if self.get_line_width() > 0:
            painter.setPen(QPen(color, self.get_line_width()))
        else:
            painter.setPen(QPen(fill_color, 0))
        painter.drawPath(path)
        painter.restore()

        base_element.paint(self, painter, shine_flag)

    def clone(self):
        """深度克隆图元及其子图元"""
        cloned = triangle_element()
        # 复制名称：复制/粘贴时据此保留成员名，只替换组名前缀
        cloned._name = self._name

        cloned.m_pos = self.m_pos
        cloned.set_line_width(self.get_line_width())
        cloned.set_color(self.get_color())
        cloned.set_fill(self.get_fill())
        cloned.set_fill_color(self.get_fill_color())
        cloned.set_opacity(self.get_opacity())
        cloned._vertices_local = [QPointF(point) for point in self._vertices_local]
        cloned._draft_scene_vertices = []
        cloned.setTransformOriginPoint(self.transformOriginPoint())
        cloned.setTransform(Transform(self.transform().m))
        cloned.m_angle      = self.m_angle
        cloned.m_angle_init = self.m_angle_init
        cloned.m_pos_init   = self.m_pos_init
        cloned._refresh_local_bounds()

        cloned.set_group_id(self.get_group_id())
        cloned.set_zValue(self.zValue())

        for child in self.childItems():
            child_clone = child.clone()
            child_clone.m_parent = cloned
            cloned.m_children.add(child_clone)

        return cloned

    def to_dict(self):
        """Serialize the three vertices in scene coordinates."""
        data = super().to_dict()
        transform = self.sceneTransform()
        center = transform.map(self._center_pos)
        origin = transform.map(self.m_origin)
        data["center_pos"] = {
            "x": round(center.x(), 3),
            "y": round(center.y(), 3),
        }
        data["origin_pos"] = {
            "x": round(origin.x(), 3),
            "y": round(origin.y(), 3),
        }
        data["vertices"] = [
            {"x": round(point.x(), 3), "y": round(point.y(), 3)}
            for point in self.get_scene_vertices()
        ]
        return data

    @classmethod
    def from_dict(cls, data):
        """Restore the triangle from its vertices, with a bbox fallback for old files."""
        item = super().from_dict(data)
        vertices = cls._parse_scene_vertices(data.get("vertices"))
        if len(vertices) == 3:
            origin_data = data.get("origin_pos") or {}
            try:
                origin_scene = QPointF(
                    float(origin_data["x"]), float(origin_data["y"])
                )
            except (KeyError, TypeError, ValueError):
                origin_scene = None
            try:
                angle = float(data.get("rotate", 0.0))
            except (TypeError, ValueError):
                angle = 0.0
            item._apply_scene_vertices(vertices, angle=angle, origin_scene=origin_scene)
        else:
            item._vertices_local = item._default_local_vertices(
                item.scene_size.width(), item.scene_size.height()
            )
            item._draft_scene_vertices = []
            item._refresh_local_bounds()
            item.update_boundingRect()
        return item
