# from my_elements_v2 import rect_element, triangle_element, line_element, circle_element, base_element, group_element, text_element
import json
import os
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QTreeWidget, QTreeWidgetItem, QStackedWidget, QLabel, QFrame,QScrollArea,QFileDialog,
    QListWidget, QListWidgetItem, QPushButton, QGroupBox,QColorDialog,QCheckBox,
    QTextEdit, QStyleFactory,QLineEdit,QSpinBox,QSpacerItem,QSizePolicy,QComboBox
)
from PySide6.QtGui import QFont,QColor
from PySide6.QtCore import Qt,QObject,Property,QPointF,QSizeF
# from my_elements_v2 import base_element,text_element,line_element,rect_element,triangle_element,image_element
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

class PropertyItem(QObject):
    """文本属性窗口 - 优化布局"""
    def __init__(self, parent=None,item:base_element=None):
        super().__init__()
        self.item = item
    
    @Property(float)
    def sizeHeight(self):
        return self.item.getSize().height()
    @sizeHeight.setter
    def sizeHeight(self, val):
        if self.item.getSize().height() != val:
            w = self.item.getSize().width()
            self.item.change_size(w,val)

    @Property(float)
    def sizeWidth(self):
        return self.item.getSize().width()
    @sizeWidth.setter
    def sizeWidth(self, val):
        if self.item.getSize().width() != val:
            h = self.item.getSize().height()
            self.item.change_size(val,h)

    @Property(QSizeF)
    def size(self):
        return self.item.getSize()
    @size.setter
    def size(self, size):  # 接收一个QSizeF对象
        if self.item.getSize() != size:  # 直接比较QSizeF对象
            self.item.change_size(size.width(), size.height())

    @Property(float)
    def posX(self):
        return self.item.pos().x()
    @posX.setter
    def posX(self, val):
        if self.item.pos().x() != val:
            y = self.item.pos().y()
            self.item.setPos(val,y)
    
    @Property(float)
    def posY(self):
        return self.item.pos().y()
    @posY.setter
    def posY(self, val):
        if self.item.pos().y() != val:
            x = self.item.pos().x()
            self.item.setPos(x,val)
         
    @Property(int)
    def lineWidth(self):
        return self.item.get_line_width()
    @lineWidth.setter
    def lineWidth(self, val):
        if self.item.get_line_width() != val:
            self.item.set_line_width(val)
    
    @Property(int)
    def opacity(self):
        return self.item.get_opacity()
    @opacity.setter
    def opacity(self, val):
        if self.item.get_opacity() != val:
            self.item.set_opacity(val)

    @Property(str)
    def name(self):
        return self.item.get_name()
    @name.setter
    def name(self, str):
        self.item.set_name(str)

    def apply_name_edit(self, name_edit) -> bool:
        """把输入框里的名字应用到图元，失败时恢复显示。

        名字全局唯一，``set_name`` 遇到已被别的图元占用的名字会返回 False。
        这时要把输入框恢复成当前名字，否则面板上会显示一个并没有生效的名字，
        看起来就像“名字改不了”。
        """

        requested = name_edit.text()
        if self.item.set_name(requested):
            return True

        current = self.item.get_name()
        owner = None
        manager = getattr(self.item, "m_scene_manager", None)
        if manager is not None:
            owner = manager.findItem(manager.m_name_items.get(requested, 0))
        if owner is not None:
            kind = getattr(owner, "type", "")
            message = f"名称“{requested}”已被图元 {owner.id()}（{kind}）占用"
        else:
            message = f"名称“{requested}”不可用"
        print(f"{message}，保持“{current}”")
        name_edit.setText(current)
        scene = getattr(self.item, "m_scene", None)
        status_bar = getattr(scene, "statusBar", None) if scene is not None else None
        if status_bar is not None:
            status_bar.showMessage(f"{message}，仍为“{current}”", 4000)
        return False


class TextPropertyItem(PropertyItem):
    """文本属性窗口 - 优化布局"""

    @Property(float)
    def head_posX(self):
        return self.item.get_scene_head_pos().x()
    @head_posX.setter
    def head_posX(self, val):
        if self.item.get_scene_head_pos().x() != val:
            y = self.item.get_scene_head_pos().y()
            self.item.change_position(QPointF(val,y))
    
    @Property(float)
    def head_posY(self):
        return self.item.get_scene_head_pos().y()
    @head_posY.setter
    def head_posY(self, val):
        if self.item.get_scene_head_pos().y() != val:
            x = self.item.get_scene_head_pos().x()
            self.item.change_position(QPointF(x,val))
    
    def __init__(self, parent=None,item:text_element=None):
        super().__init__(item=item)
        self.navi = None
     
    def add_navigation_items(self,navigation):
        # 添加顶级项
        categories = [
            ("常规", "normal", [
                ("文本", "context")
            ]),
            ("属性", "property", [
                ("外观", "appearance"),
                ("布局", "layout"),
                ("其它", "others")
            ])
        ]
        for category, icon, items in categories:
            category_item = QTreeWidgetItem([category])
            category_item.setData(0, Qt.UserRole, f"category_{icon}")
            navigation.navigation_tree.addTopLevelItem(category_item)
            
            for item_name, item_key in items:
                item = QTreeWidgetItem([item_name])
                item.setData(0, Qt.UserRole, item_key)
                category_item.addChild(item)
        
        # 展开所有顶级项
        for i in range(navigation.navigation_tree.topLevelItemCount()):
            navigation.navigation_tree.topLevelItem(i).setExpanded(True)
            # 创建内容页面
        self.create_content_pages(navigation)
        navigation.select_preferred_page()
        navigation.destory_current.connect(self.on_destory_current)
        self.navi = navigation

        
    def on_destory_current(self):
        self.item =None
        self.navi.destory_current.disconnect(self.on_destory_current)
    
    def create_content_pages(self,navi):
        # 创建内容页面
        navi.add_page("context", "文本"   , self.create_context_page()   )
        navi.add_page("appearance", "外观", self.create_appearance_page())
        navi.add_page("layout", "布局"    , self.create_layout_page()    )
        navi.add_page("others",     "其它"    , self.create_others_page()    )
    
        
    
    def create_context_page(self):
        
        page = QWidget()
        layout = QVBoxLayout(page)
        
        # 目录
        toc = QGroupBox("文本")
        toc_layout = QVBoxLayout()
        detail = QTextEdit()
        detail.setText(self.item.context)
        detail.textChanged.connect(lambda:setattr(self.item,"context" ,detail.toPlainText()) )
        toc_layout.addWidget(detail)
        toc.setLayout(toc_layout)
        layout.addWidget(toc)
        return page
    
    def create_appearance_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        
        appearance        = QGroupBox("外观")
        appearance_layout = QVBoxLayout()
        text_color_layout = QHBoxLayout()
        bg_color_layout   = QHBoxLayout()
        fill_checkbox     = QCheckBox(parent=page,text="是否填充")
        fill_checkbox.setChecked(self.item.get_fill())
        fill_checkbox.clicked.connect(lambda:self.item.set_fill(fill_checkbox.isChecked()))
        text_color_layout.addWidget(QLabel("文本颜色"))
        bg_color_layout.addWidget(QLabel("背景颜色"))
        # 字体颜色
        self.font_color_btn = self.create_color_button(self.item.get_color())
        self.font_color_btn.clicked.connect(lambda: self.select_font_color(page,False))
        self.bg_color_btn   = self.create_color_button(self.item.get_color())
        self.bg_color_btn.clicked.connect(lambda: self.select_font_color(page,True))
        self.update_font_color_ui(False)
        self.update_font_color_ui(True)

        # self.add_property_row("字体颜色", self.font_color_btn)

        self.line_width_spinBox     = QSpinBox()
        self.line_width_spinBox.valueChanged.connect(lambda:setattr(self,"lineWidth" ,self.line_width_spinBox.value()) )
        self.line_width_spinBox.setValue(self.lineWidth)

        text_color_layout.addWidget(self.font_color_btn)
        text_color_layout.addWidget(QLabel("线宽："))
        text_color_layout.addWidget(self.line_width_spinBox)

        self.opacity_spinBox     = QSpinBox()
        self.opacity_spinBox.setRange(0,255)
        self.opacity_spinBox.valueChanged.connect(lambda:setattr(self,"opacity" ,self.opacity_spinBox.value()) )
        self.opacity_spinBox.setValue(self.opacity)
        bg_color_layout.addWidget(self.bg_color_btn)
        bg_color_layout.addWidget(QLabel("透明度："))
        bg_color_layout.addWidget(self.opacity_spinBox)
        appearance_layout.addWidget(fill_checkbox)
        appearance_layout.addLayout(text_color_layout)
        appearance_layout.addLayout(bg_color_layout)

        appearance.setLayout(appearance_layout)
        layout.addWidget(appearance)
        
        return page

    def create_color_button(self, color):
        """创建颜色选择按钮"""
        btn = QPushButton()
        btn.setFixedSize(30, 30)
        
        # 确保 color 是 QColor 类型
        if isinstance(color, str):
            color = QColor(color)
        elif isinstance(color, int):
            color = QColor(color)
        elif not isinstance(color, QColor):
            color = QColor("#000000")  # 默认黑色
            
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color.name()};
                border: 1px solid #adb5bd;
                border-radius: 4px;
            }}
        """)
        return btn
    
    def update_font_color_ui(self,is_bg_color):
        """从对象更新字体颜色UI"""
        if not is_bg_color:
            color = self.item.get_color() 
            color_code = color.name() if isinstance(color, QColor) else "#000000"
            self.font_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
        else:
            color = self.item.get_fill_color()
            color_code = color.name() if isinstance(color, QColor) else "#000000"
            self.bg_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
        
        
        
    def select_font_color(self,parent,is_bg_color):
        current_color = self.item.get_color()
        color = QColorDialog.getColor(current_color, parent)
        if color.isValid():
            self.item.set_color(color) if not is_bg_color else self.item.set_fill_color(color)
            if not is_bg_color:
                color_code = color.name() if isinstance(color, QColor) else "#000000"
                self.font_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
            else:
                color_code = color.name() if isinstance(color, QColor) else "#000000"
                self.bg_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
    
    def create_layout_page(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        layout1 = QHBoxLayout()
       
        # 目录
        position_GroupBox = QGroupBox("位置")
        position_layout = QVBoxLayout(position_GroupBox)
        positionX_layout = QHBoxLayout()
        positionX_layout.addWidget(QLabel("X:"))
        positionX = QLineEdit()
        positionX_layout.addWidget(positionX)
        positionY_layout = QHBoxLayout()
        positionY_layout.addWidget(QLabel("Y:"))
        positionY = QLineEdit()
        positionY_layout.addWidget(positionY)
        position_layout.addLayout(positionX_layout)
        position_layout.addLayout(positionY_layout)
        size_GroupBox = QGroupBox("尺寸")
        size_layout = QVBoxLayout(size_GroupBox)
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("W:"))
        width = QLineEdit()
        width_layout.addWidget(width)
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("H:"))
        height = QLineEdit()
        height_layout.addWidget(height)
        size_layout.addLayout(width_layout)
        size_layout.addLayout(height_layout)
        layout1.addWidget(position_GroupBox)
        layout1.addWidget(size_GroupBox)
        layout.addLayout(layout1)

        # positionX.setText( f"{self.item.pos().x():.1f}")
        # positionY.setText( f"{self.item.pos().y():.1f}")
        # positionX.editingFinished.connect(lambda:setattr(self,"posX" , float(positionX.text())) )
        # positionY.editingFinished.connect(lambda:setattr(self,"posY" , float(positionY.text())) )
        positionX.setText( f"{self.item.get_scene_head_pos().x():.1f}")
        positionY.setText( f"{self.item.get_scene_head_pos().y():.1f}")
        positionX.editingFinished.connect(lambda:setattr(self,"head_posX" , float(positionX.text())) )
        positionY.editingFinished.connect(lambda:setattr(self,"head_posY" , float(positionY.text())) )

        width.setText( f"{self.sizeWidth:.1f}")
        height.setText( f"{self.sizeHeight:.1f}")
        height.setEnabled(False)

        width.editingFinished.connect(lambda:setattr(self,"sizeWidth" , float(width.text())) )
        
        # height.editingFinished.connect(lambda:setattr(self,"sizeHeight" , float(height.text())) )

        

        return page

    def create_others_page(self):
        page    = QWidget()
        layout  = QVBoxLayout(page)
        layout_row1 = QHBoxLayout()

        others_GroupBox = QGroupBox("其它")
        others_layout  = QVBoxLayout(others_GroupBox)

        group_layout_row1 = QHBoxLayout()
        group_layout_row1.addWidget(QLabel("Z值："))
        self.zValue_spinBox  = QSpinBox()
        self.zValue_spinBox.setRange(0,9999)
        group_layout_row1.addWidget(self.zValue_spinBox)
        self.zValue_spinBox.setEnabled(False)
        self.zValue_spinBox.setValue(self.item.zValue())

        group_layout_row2 = QHBoxLayout()
        group_layout_row2.addWidget(QLabel("id："))
        self.id_spinBox  = QSpinBox()
        self.id_spinBox.setRange(0,9999)
        group_layout_row2.addWidget(self.id_spinBox)
        self.id_spinBox.setEnabled(False)
        self.id_spinBox.setValue(self.item.id())

        group_layout_row3 = QHBoxLayout()
        group_layout_row3.addWidget(QLabel("名称："))
        name_edit  = QLineEdit()
        group_layout_row3.addWidget(name_edit)
        name_edit.setText(self.item.get_name())
        name_edit.editingFinished.connect(lambda: self.apply_name_edit(name_edit))

        others_layout.addLayout(group_layout_row1)
        others_layout.addLayout(group_layout_row2)
        others_layout.addLayout(group_layout_row3)

        layout_row1.addWidget(others_GroupBox)

        h_spacer = QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Preferred)
        v_spacer = QSpacerItem(20, 20, QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout_row1.addSpacerItem(h_spacer)

        layout.addLayout(layout_row1)

        layout.addSpacerItem(v_spacer)
        return page




class LinePropertyItem(PropertyItem):
    """文本属性窗口 - 优化布局"""
    def __init__(self, parent=None,item:line_element=None):
        super().__init__(item=item)
        self.navi =None
      
    @Property(float)
    def head_posX(self):
        return self.item.get_scene_head_pos().x()
    @head_posX.setter
    def head_posX(self, val):
        if self.item.get_scene_head_pos().x() != val:
            y = self.item.get_scene_head_pos().y()
            self.item.change_head_pos(QPointF(val,y))
    
    @Property(float)
    def head_posY(self):
        return self.item.get_scene_head_pos().y()
    @head_posY.setter
    def head_posY(self, val):
        if self.item.get_scene_head_pos().y() != val:
            x = self.item.get_scene_head_pos().x()
            self.item.change_head_pos(QPointF(x,val))
    
    @Property(float)
    def end_posX(self):
        return self.item.get_scene_head_pos().x()
    @end_posX.setter
    def end_posX(self, val):
        if self.item.get_scene_end_pos().x() != val:
            y = self.item.get_scene_end_pos().y()
            self.item.change_end_pos(QPointF(val,y))
    
    @Property(float)
    def end_posY(self):
        return self.item.get_scene_end_pos().y()
    @end_posY.setter
    def end_posY(self, val):
        if self.item.get_scene_end_pos().y() != val:
            x = self.item.get_scene_end_pos().x()
            self.item.change_end_pos(QPointF(x,val))
         
    def add_navigation_items(self,navigation):
        # 添加顶级项
        categories = [
            ("属性", "property", [
                ("外观", "appearance"),
                ("布局", "layout"),
                ("其它", "others")
            ])
        ]
        for category, icon, items in categories:
            category_item = QTreeWidgetItem([category])
            category_item.setData(0, Qt.UserRole, f"category_{icon}")
            navigation.navigation_tree.addTopLevelItem(category_item)
            
            for item_name, item_key in items:
                item = QTreeWidgetItem([item_name])
                item.setData(0, Qt.UserRole, item_key)
                category_item.addChild(item)
        
        # 展开所有顶级项
        for i in range(navigation.navigation_tree.topLevelItemCount()):
            navigation.navigation_tree.topLevelItem(i).setExpanded(True)
            # 创建内容页面
        self.create_content_pages(navigation)
        navigation.select_preferred_page()
        navigation.destory_current.connect(self.on_destory_current)
        self.navi = navigation

        
    def on_destory_current(self):
        self.item =None
        self.navi.destory_current.disconnect(self.on_destory_current)
    
    def create_content_pages(self,navi):
        # 创建内容页面
        navi.add_page("appearance", "外观", self.create_appearance_page())
        navi.add_page("layout",     "布局"    , self.create_layout_page())
        navi.add_page("others",     "其它"    , self.create_others_page()    )
    
    
    def create_appearance_page(self):
        page   = QWidget()
        layout = QVBoxLayout(page)
        appearance        = QGroupBox("外观")
        appearance_layout = QVBoxLayout()
        
        line_color_layout = QHBoxLayout()
        line_color_layout.addWidget(QLabel("颜色："))
        # 字体颜色
        self.line_color_btn = self.create_color_button(self.item.get_color())
        self.line_color_btn.clicked.connect(lambda: self.select_line_color(page,False))
        self.update_line_color_ui(False)

        self.line_width_spinBox     = QSpinBox()
        self.line_width_spinBox.valueChanged.connect(lambda:setattr(self,"lineWidth" ,self.line_width_spinBox.value()) )
        self.line_width_spinBox.setValue(self.lineWidth)
        self.opacity_spinBox     = QSpinBox()
        self.opacity_spinBox.setRange(0,255)
        self.opacity_spinBox.valueChanged.connect(lambda:setattr(self,"opacity" ,self.opacity_spinBox.value()) )
        self.opacity_spinBox.setValue(self.opacity)

        line_color_layout.addWidget(self.line_color_btn)
        line_color_layout.addWidget(QLabel("线宽："))
        line_color_layout.addWidget(self.line_width_spinBox)

        line_color_layout.addWidget(QLabel("透明度："))
        line_color_layout.addWidget(self.opacity_spinBox)


        appearance_layout.addLayout(line_color_layout)
        appearance.setLayout(appearance_layout)
        layout.addWidget(appearance)
        
        return page

    def create_color_button(self, color):
        """创建颜色选择按钮"""
        btn = QPushButton()
        btn.setFixedSize(30, 30)
        
        # 确保 color 是 QColor 类型
        if isinstance(color, str):
            color = QColor(color)
        elif isinstance(color, int):
            color = QColor(color)
        elif not isinstance(color, QColor):
            color = QColor("#000000")  # 默认黑色
            
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color.name()};
                border: 1px solid #adb5bd;
                border-radius: 4px;
            }}
        """)
        return btn
    
    def update_line_color_ui(self,is_bg_color):
        """从对象更新字体颜色UI"""
        if not is_bg_color:
            color = self.item.get_color() 
            color_code = color.name() if isinstance(color, QColor) else "#000000"
            self.line_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
        
    def select_line_color(self,parent,is_bg_color):
        current_color = self.item.get_color()
        color = QColorDialog.getColor(current_color, parent)
        if color.isValid():
            self.item.set_color(color) 
            if not is_bg_color:
                color_code = color.name() if isinstance(color, QColor) else "#000000"
                self.line_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
           
    
    def create_layout_page(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        layout1 = QHBoxLayout()
        # 目录
        start_position_GroupBox = QGroupBox("起始点")
        start_position_layout  = QVBoxLayout(start_position_GroupBox)
        start_positionX_layout = QHBoxLayout()
        start_positionX_layout.addWidget(QLabel("X:"))
        start_positionX = QLineEdit()
        start_positionX_layout.addWidget(start_positionX)
        start_positionY_layout = QHBoxLayout()
        start_positionY_layout.addWidget(QLabel("Y:"))
        start_positionY = QLineEdit()
        start_positionY_layout.addWidget(start_positionY)
        start_position_layout.addLayout(start_positionX_layout)
        start_position_layout.addLayout(start_positionY_layout)

        end_position_GroupBox = QGroupBox("结束点")
        end_position_layout  = QVBoxLayout(end_position_GroupBox)
        end_positionX_layout = QHBoxLayout()
        end_positionX_layout.addWidget(QLabel("X:"))
        end_positionX = QLineEdit()
        end_positionX_layout.addWidget(end_positionX)
        end_positionY_layout = QHBoxLayout()
        end_positionY_layout.addWidget(QLabel("Y:"))
        end_positionY = QLineEdit()
        end_positionY_layout.addWidget(end_positionY)
        end_position_layout.addLayout(end_positionX_layout)
        end_position_layout.addLayout(end_positionY_layout)
        
        layout1.addWidget(start_position_GroupBox)
        layout1.addWidget(end_position_GroupBox)
        layout.addLayout(layout1)

        start_positionX.setText( f"{self.item.get_scene_head_pos().x():.1f}")
        start_positionY.setText( f"{self.item.get_scene_head_pos().y():.1f}")
        start_positionX.editingFinished.connect(lambda:setattr(self,"head_posX" , float(start_positionX.text())) )
        start_positionY.editingFinished.connect(lambda:setattr(self,"head_posY" , float(start_positionY.text())) )

        end_positionX.setText( f"{self.item.get_scene_end_pos().x():.1f}")
        end_positionY.setText( f"{self.item.get_scene_end_pos().y():.1f}")
        end_positionX.editingFinished.connect(lambda:setattr(self,"end_posX" , float(end_positionX.text())) )
        end_positionY.editingFinished.connect(lambda:setattr(self,"end_posY" , float(end_positionY.text())) )
        return page
    def create_others_page(self):
        page    = QWidget()
        layout  = QVBoxLayout(page)
        layout_row1 = QHBoxLayout()

        others_GroupBox = QGroupBox("其它")
        others_layout  = QVBoxLayout(others_GroupBox)

        group_layout_row1 = QHBoxLayout()
        group_layout_row1.addWidget(QLabel("Z值："))
        self.zValue_spinBox  = QSpinBox()
        self.zValue_spinBox.setRange(0,9999)
        group_layout_row1.addWidget(self.zValue_spinBox)
        self.zValue_spinBox.setEnabled(False)
        self.zValue_spinBox.setValue(self.item.zValue())

        group_layout_row2 = QHBoxLayout()
        group_layout_row2.addWidget(QLabel("id："))
        self.id_spinBox  = QSpinBox()
        self.id_spinBox.setRange(0,9999)
        group_layout_row2.addWidget(self.id_spinBox)
        self.id_spinBox.setEnabled(False)
        self.id_spinBox.setValue(self.item.id())

        group_layout_row3 = QHBoxLayout()
        group_layout_row3.addWidget(QLabel("名称："))
        name_edit  = QLineEdit()
        group_layout_row3.addWidget(name_edit)
        name_edit.setText(self.item.get_name())
        name_edit.editingFinished.connect(lambda: self.apply_name_edit(name_edit))

        others_layout.addLayout(group_layout_row1)
        others_layout.addLayout(group_layout_row2)
        others_layout.addLayout(group_layout_row3)

        layout_row1.addWidget(others_GroupBox)

        h_spacer = QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Preferred)
        v_spacer = QSpacerItem(20, 20, QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout_row1.addSpacerItem(h_spacer)

        layout.addLayout(layout_row1)

        layout.addSpacerItem(v_spacer)
        return page


class RectPropertyItem(PropertyItem):
    """文本属性窗口 - 优化布局"""
    def __init__(self, parent=None,item:rect_element=None):
        super().__init__(item=item)
        self.navi = None

    @Property(float)
    def cornerRadius(self):
        return self.item.get_corner_radius()

    @cornerRadius.setter
    def cornerRadius(self, val):
        if self.item.get_corner_radius() != val:
            self.item.set_corner_radius(val)
      
    @Property(float)
    def head_posX(self):
        return self.item.get_scene_head_pos().x()
    @head_posX.setter
    def head_posX(self, val):
        if self.item.get_scene_head_pos().x() != val:
            y = self.item.get_scene_head_pos().y()
            self.item.change_position(QPointF(val,y))
    
    @Property(float)
    def head_posY(self):
        return self.item.get_scene_head_pos().y()
    @head_posY.setter
    def head_posY(self, val):
        if self.item.get_scene_head_pos().y() != val:
            x = self.item.get_scene_head_pos().x()
            self.item.change_position(QPointF(x,val))
    
    
         
    def add_navigation_items(self,navigation):
        # 添加顶级项
        categories = [
            ("属性", "property", [
                ("外观", "appearance"),
                ("布局", "layout"),
                ("其它", "others")
            ])
        ]
        for category, icon, items in categories:
            category_item = QTreeWidgetItem([category])
            category_item.setData(0, Qt.UserRole, f"category_{icon}")
            navigation.navigation_tree.addTopLevelItem(category_item)
            
            for item_name, item_key in items:
                item = QTreeWidgetItem([item_name])
                item.setData(0, Qt.UserRole, item_key)
                category_item.addChild(item)
        
        # 展开所有顶级项
        for i in range(navigation.navigation_tree.topLevelItemCount()):
            navigation.navigation_tree.topLevelItem(i).setExpanded(True)
            # 创建内容页面
        self.create_content_pages(navigation)
        navigation.select_preferred_page()
        navigation.destory_current.connect(self.on_destory_current)
        self.navi = navigation


    def on_destory_current(self):
        self.item =None
        self.navi.destory_current.disconnect(self.on_destory_current)

    def create_content_pages(self,navi):
        # 创建内容页面
        navi.add_page("appearance", "外观"    , self.create_appearance_page())
        navi.add_page("layout",     "布局"    , self.create_layout_page()    )
        navi.add_page("others",     "其它"    , self.create_others_page()    )
    

    
    def create_appearance_page(self):
        page   = QWidget()
        layout = QVBoxLayout(page)
        bg_color_layout   = QHBoxLayout()
        appearance        = QGroupBox("外观")
        appearance_layout = QVBoxLayout()
        line_color_layout = QHBoxLayout()
        line_color_layout.addWidget(QLabel("颜色："))
        fill_checkbox     = QCheckBox(parent=page,text="是否填充")
        fill_checkbox.setChecked(self.item.get_fill())
        fill_checkbox.clicked.connect(lambda:self.item.set_fill(fill_checkbox.isChecked()))
        # 字体颜色
        self.line_color_btn = self.create_color_button(self.item.get_color())
        self.line_color_btn.clicked.connect(lambda: self.select_line_color(page,False))
        bg_color_layout.addWidget(QLabel("背景颜色"))
        self.update_line_color_ui(False)

        self.bg_color_btn   = self.create_color_button(self.item.get_fill_color())
        self.bg_color_btn.clicked.connect(lambda: self.select_line_color(page,True))

        self.line_width_spinBox     = QSpinBox()
        self.line_width_spinBox.valueChanged.connect(lambda:setattr(self,"lineWidth" ,self.line_width_spinBox.value()) )
        self.line_width_spinBox.setValue(self.lineWidth)

        line_color_layout.addWidget(self.line_color_btn)
        line_color_layout.addWidget(QLabel("线宽："))
        line_color_layout.addWidget(self.line_width_spinBox)
        bg_color_layout.addWidget(self.bg_color_btn)

        self.opacity_spinBox     = QSpinBox()
        self.opacity_spinBox.setRange(0,255)
        self.opacity_spinBox.valueChanged.connect(lambda:setattr(self,"opacity" ,self.opacity_spinBox.value()) )
        
        self.opacity_spinBox.setValue(self.opacity)
        
        bg_color_layout.addWidget(QLabel("透明度："))
        bg_color_layout.addWidget(self.opacity_spinBox)

        if not isinstance(self.item, triangle_element):
            corner_layout = QHBoxLayout()
            corner_layout.addWidget(QLabel("圆角："))
            self.corner_radius_spinBox = QSpinBox()
            max_radius = int(min(self.item.getSize().width(), self.item.getSize().height()) / 2.0)
            self.corner_radius_spinBox.setRange(0, max(0, max_radius))
            self.corner_radius_spinBox.setToolTip("圆角半径，单位与图元宽高一致；最大为短边的一半")
            self.corner_radius_spinBox.setValue(int(round(self.item.get_corner_radius())))
            self.corner_radius_spinBox.valueChanged.connect(
                lambda: setattr(self, "cornerRadius", float(self.corner_radius_spinBox.value()))
            )
            corner_layout.addWidget(self.corner_radius_spinBox)
            appearance_layout.addLayout(corner_layout)

        appearance_layout.addWidget(fill_checkbox)
        appearance_layout.addLayout(line_color_layout)
        appearance_layout.addLayout(bg_color_layout)
        appearance.setLayout(appearance_layout)
        layout.addWidget(appearance)
        
        return page

    def create_color_button(self, color):
        """创建颜色选择按钮"""
        btn = QPushButton()
        btn.setFixedSize(30, 30)
        
        # 确保 color 是 QColor 类型
        if isinstance(color, str):
            color = QColor(color)
        elif isinstance(color, int):
            color = QColor(color)
        elif not isinstance(color, QColor):
            color = QColor("#000000")  # 默认黑色
            
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color.name()};
                border: 1px solid #adb5bd;
                border-radius: 4px;
            }}
        """)
        return btn
    
    def update_line_color_ui(self,is_bg_color):
        """从对象更新字体颜色UI"""
        if not is_bg_color:
            color = self.item.get_color() 
            color_code = color.name() if isinstance(color, QColor) else "#000000"
            self.line_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
        else:
            color = self.item.get_fill_color()
            color_code = color.name() if isinstance(color, QColor) else "#000000"
            self.bg_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
        
        
        
    def select_line_color(self,parent,is_bg_color):
        current_color = self.item.get_color()
        color = QColorDialog.getColor(current_color, parent)
        if color.isValid():
            self.item.set_color(color) if not is_bg_color else self.item.set_fill_color(color)
            if not is_bg_color:
                color_code = color.name() if isinstance(color, QColor) else "#000000"
                self.line_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
            else:
                color_code = color.name() if isinstance(color, QColor) else "#000000"
                self.bg_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
    
    def create_layout_page(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        layout1 = QHBoxLayout()
        # 目录
        start_position_GroupBox = QGroupBox("位置")
        start_position_layout  = QVBoxLayout(start_position_GroupBox)
        start_positionX_layout = QHBoxLayout()
        start_positionX_layout.addWidget(QLabel("X:"))
        start_positionX = QLineEdit()
        start_positionX_layout.addWidget(start_positionX)
        start_positionY_layout = QHBoxLayout()
        start_positionY_layout.addWidget(QLabel("Y:"))
        start_positionY = QLineEdit()
        start_positionY_layout.addWidget(start_positionY)
        start_position_layout.addLayout(start_positionX_layout)
        start_position_layout.addLayout(start_positionY_layout)

        size_GroupBox = QGroupBox("尺寸")
        size_layout = QVBoxLayout(size_GroupBox)
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("W:"))
        width = QLineEdit()
        width_layout.addWidget(width)
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("H:"))
        height = QLineEdit()
        height_layout.addWidget(height)
        size_layout.addLayout(width_layout)
        size_layout.addLayout(height_layout)
        
        layout1.addWidget(start_position_GroupBox)
        layout1.addWidget(size_GroupBox)
       
        layout.addLayout(layout1)
        start_positionX.setText( f"{self.item.get_scene_head_pos().x():.1f}")
        start_positionY.setText( f"{self.item.get_scene_head_pos().y():.1f}")
        start_positionX.editingFinished.connect(lambda:setattr(self,"head_posX" , float(start_positionX.text())) )
        start_positionY.editingFinished.connect(lambda:setattr(self,"head_posY" , float(start_positionY.text())) )

        width.setText( f"{self.sizeWidth:.1f}")
        height.setText( f"{self.sizeHeight:.1f}")
       

        width.editingFinished.connect(lambda:setattr(self,"sizeWidth" , float(width.text())) )
        
        height.editingFinished.connect(lambda:setattr(self,"sizeHeight" , float(height.text())) )


        
        return page

    def create_others_page(self):
        page    = QWidget()
        layout  = QVBoxLayout(page)
        layout_row1 = QHBoxLayout()

        others_GroupBox = QGroupBox("其它")
        others_layout  = QVBoxLayout(others_GroupBox)

        group_layout_row1 = QHBoxLayout()
        group_layout_row1.addWidget(QLabel("Z值："))
        self.zValue_spinBox  = QSpinBox()
        self.zValue_spinBox.setRange(0,9999)
        group_layout_row1.addWidget(self.zValue_spinBox)
        self.zValue_spinBox.setEnabled(False)
        self.zValue_spinBox.setValue(self.item.zValue())

        group_layout_row2 = QHBoxLayout()
        group_layout_row2.addWidget(QLabel("id："))
        self.id_spinBox  = QSpinBox()
        group_layout_row2.addWidget(self.id_spinBox)
        self.id_spinBox.setEnabled(False)
        self.id_spinBox.setValue(self.item.id())

        group_layout_row3 = QHBoxLayout()
        group_layout_row3.addWidget(QLabel("名称："))
        name_edit  = QLineEdit()
        group_layout_row3.addWidget(name_edit)
        name_edit.setText(self.item.get_name())
        name_edit.editingFinished.connect(lambda: self.apply_name_edit(name_edit))

        others_layout.addLayout(group_layout_row1)
        others_layout.addLayout(group_layout_row2)
        others_layout.addLayout(group_layout_row3)

        layout_row1.addWidget(others_GroupBox)

        h_spacer = QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Preferred)
        v_spacer = QSpacerItem(20, 20, QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout_row1.addSpacerItem(h_spacer)

        layout.addLayout(layout_row1)

        layout.addSpacerItem(v_spacer)
        return page


class TrianglePropertyItem(RectPropertyItem):
    """三角形属性项，编辑位置和三个顶点坐标。"""

    def __init__(self, parent=None, item: triangle_element=None):
        super().__init__(parent=parent, item=item)

    def _apply_vertex(self, index, x_edit, y_edit):
        try:
            x = float(x_edit.text())
            y = float(y_edit.text())
        except (TypeError, ValueError):
            return
        vertices = self.item.get_scene_vertices()
        if len(vertices) != 3:
            return
        vertices[index] = QPointF(x, y)
        self.item.set_scene_vertices(vertices)

    def create_layout_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        position_GroupBox = QGroupBox("位置")
        position_layout = QVBoxLayout(position_GroupBox)
        positionX_layout = QHBoxLayout()
        positionX_layout.addWidget(QLabel("X:"))
        positionX = QLineEdit()
        positionX_layout.addWidget(positionX)
        positionY_layout = QHBoxLayout()
        positionY_layout.addWidget(QLabel("Y:"))
        positionY = QLineEdit()
        positionY_layout.addWidget(positionY)
        position_layout.addLayout(positionX_layout)
        position_layout.addLayout(positionY_layout)

        vertices_GroupBox = QGroupBox("顶点")
        vertices_layout = QVBoxLayout(vertices_GroupBox)
        vertices = self.item.get_scene_vertices()
        for index, label in enumerate(("A", "B", "C")):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{label} X:"))
            x_edit = QLineEdit()
            row.addWidget(x_edit)
            row.addWidget(QLabel("Y:"))
            y_edit = QLineEdit()
            row.addWidget(y_edit)
            if index < len(vertices):
                point = vertices[index]
                x_edit.setText(f"{point.x():.1f}")
                y_edit.setText(f"{point.y():.1f}")
            x_edit.editingFinished.connect(
                lambda i=index, xe=x_edit, ye=y_edit: self._apply_vertex(i, xe, ye)
            )
            y_edit.editingFinished.connect(
                lambda i=index, xe=x_edit, ye=y_edit: self._apply_vertex(i, xe, ye)
            )
            vertices_layout.addLayout(row)

        head_pos = self.item.get_scene_head_pos()
        if head_pos is not None:
            positionX.setText(f"{head_pos.x():.1f}")
            positionY.setText(f"{head_pos.y():.1f}")
        positionX.editingFinished.connect(
            lambda: setattr(self, "head_posX", float(positionX.text()))
        )
        positionY.editingFinished.connect(
            lambda: setattr(self, "head_posY", float(positionY.text()))
        )

        layout.addWidget(position_GroupBox)
        layout.addWidget(vertices_GroupBox)
        layout.addSpacerItem(
            QSpacerItem(20, 20, QSizePolicy.Preferred, QSizePolicy.Expanding)
        )
        return page


class GroupPropertyItem(PropertyItem):
    """文本属性窗口 - 优化布局"""
    def __init__(self, parent=None,item:group_element=None):
        super().__init__(item=item)
        self.navi = None
      
    @Property(float)
    def head_posX(self):
        return self.item.get_scene_head_pos().x()
    @head_posX.setter
    def head_posX(self, val):
        if self.item.get_scene_head_pos().x() != val:
            y = self.item.get_scene_head_pos().y()
            self.item.change_position(QPointF(val,y))
    
    @Property(float)
    def head_posY(self):
        return self.item.get_scene_head_pos().y()
    @head_posY.setter
    def head_posY(self, val):
        if self.item.get_scene_head_pos().y() != val:
            x = self.item.get_scene_head_pos().x()
            self.item.change_position(QPointF(x,val))
    
    
         
    def add_navigation_items(self,navigation):
        # 添加顶级项
        categories = [
            ("交互", "interaction", [
                ("事件绑定", "events")
            ]),
            ("属性", "property", [
                ("布局", "layout"),
                ("其它", "others")
            ])
        ]
        for category, icon, items in categories:
            category_item = QTreeWidgetItem([category])
            category_item.setData(0, Qt.UserRole, f"category_{icon}")
            navigation.navigation_tree.addTopLevelItem(category_item)
            
            for item_name, item_key in items:
                item = QTreeWidgetItem([item_name])
                item.setData(0, Qt.UserRole, item_key)
                category_item.addChild(item)
        
        # 展开所有顶级项
        for i in range(navigation.navigation_tree.topLevelItemCount()):
            navigation.navigation_tree.topLevelItem(i).setExpanded(True)
            # 创建内容页面
        self.create_content_pages(navigation)
        navigation.select_preferred_page()
        navigation.destory_current.connect(self.on_destory_current)
        self.navi = navigation


    def on_destory_current(self):
        self.item =None
        self.navi.destory_current.disconnect(self.on_destory_current)

    def create_content_pages(self,navi):
        # 创建内容页面
    
        navi.add_page("events",     "事件绑定", self.create_events_page()    )
        navi.add_page("layout",     "布局"    , self.create_layout_page()    )
        navi.add_page("others",     "其它"    , self.create_others_page()    )

    def create_events_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        event_group = QGroupBox("事件绑定")
        event_layout = QVBoxLayout(event_group)

        hint = QLabel(
            "事件触发时优先调用“处理函数”（运行态已注册的 Python 函数），"
            "参数使用 JSON 对象；处理函数留空时才把“变量”写入运行态变量表。"
            "值留空时：pressed 写 true、released 写 false、click 写 true、"
            "toggle 写当前选中状态。attach 仅在进入运行态时执行一次，"
            "适合初始化图元状态。"
        )
        hint.setWordWrap(True)
        event_layout.addWidget(hint)

        self.toggle_enabled_checkbox = QCheckBox("启用 toggle（点击后切换选中状态）")
        self.toggle_enabled_checkbox.setChecked(self.item.is_toggle_enabled())
        event_layout.addWidget(self.toggle_enabled_checkbox)

        self.toggle_checked_checkbox = QCheckBox("初始为选中状态")
        self.toggle_checked_checkbox.setChecked(self.item.is_checked())
        self.toggle_checked_checkbox.setEnabled(self.item.is_toggle_enabled())
        event_layout.addWidget(self.toggle_checked_checkbox)

        self.toggle_enabled_checkbox.toggled.connect(self.handle_toggle_enabled_change)
        self.toggle_checked_checkbox.toggled.connect(self.handle_toggle_checked_change)

        event_specs = (
            ("attach",   "初始化 attach"),
            ("pressed",  "按下 pressed"),
            ("released", "松开 released"),
            ("click",    "点击 clicked"),
            ("toggle",   "切换 toggled"),
        )
        for event_name, label in event_specs:
            binding = self.item.get_event_binding(event_name) or {}

            handler_row = QHBoxLayout()
            title = QLabel(label)
            title.setMinimumWidth(100)
            handler_row.addWidget(title)

            handler_edit = QLineEdit()
            handler_edit.setPlaceholderText("处理函数名（如 safety_door.toggle）")
            handler_edit.setText(str(binding.get("handler", "")))
            handler_row.addWidget(handler_edit, 2)

            args_edit = QLineEdit()
            args_edit.setPlaceholderText('参数 JSON（如 {"door": "4"}）')
            raw_args = binding.get("args")
            if raw_args:
                args_edit.setText(json.dumps(raw_args, ensure_ascii=False))
            handler_row.addWidget(args_edit, 2)
            event_layout.addLayout(handler_row)

            target_row = QHBoxLayout()
            target_row.addSpacing(100)
            variable_edit = QLineEdit()
            variable_edit.setPlaceholderText("变量名（处理函数为空时使用）")
            variable_edit.setText(str(binding.get("variable", "")))
            target_row.addWidget(variable_edit, 2)

            value_edit = QLineEdit()
            value_edit.setPlaceholderText("值（留空=事件值）")
            value_edit.setText(str(binding.get("value", "")))
            target_row.addWidget(value_edit, 1)
            event_layout.addLayout(target_row)

            for edit in (handler_edit, args_edit, variable_edit, value_edit):
                edit.editingFinished.connect(
                    lambda e=event_name, h=handler_edit, a=args_edit,
                    v=variable_edit, val=value_edit:
                    self.save_event_binding(e, v, val, h, a)
                )

        layout.addWidget(event_group)
        layout.addStretch(1)
        return page

    def save_event_binding(
        self, event_name, variable_edit, value_edit, handler_edit=None, args_edit=None
    ):
        handler = handler_edit.text().strip() if handler_edit is not None else ""
        args = None
        args_text = args_edit.text().strip() if args_edit is not None else ""
        if handler and args_text:
            try:
                args = json.loads(args_text)
            except ValueError as exc:
                print(f"事件参数不是合法 JSON，未保存 {event_name}: {exc}")
                if args_edit is not None:
                    args_edit.setStyleSheet("border: 1px solid #ff3b30")
                    args_edit.setToolTip("参数必须是 JSON 对象，例如 {\"door\": \"4\"}")
                return
            if not isinstance(args, dict):
                print(f"事件参数必须是 JSON 对象，未保存 {event_name}: {args_text!r}")
                if args_edit is not None:
                    args_edit.setStyleSheet("border: 1px solid #ff3b30")
                    args_edit.setToolTip('参数必须是 JSON 对象，例如 {"door": "4"}')
                return
        if args_edit is not None:
            args_edit.setStyleSheet("")
            args_edit.setToolTip("")

        self.item.set_event_binding(
            event_name,
            variable_edit.text(),
            value_edit.text(),
            handler,
            args,
        )
        if event_name == "toggle" and (variable_edit.text().strip() or handler):
            # Binding the toggle event is the common case; enable the state
            # machine automatically so the event can actually fire.
            self.toggle_enabled_checkbox.setChecked(True)

    def handle_toggle_enabled_change(self, checked):
        self.item.set_toggle_enabled(checked)
        self.toggle_checked_checkbox.setEnabled(checked)

    def handle_toggle_checked_change(self, checked):
        self.item.set_checked(checked)
    

    def create_layout_page(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        layout1 = QHBoxLayout()
        # 目录
        start_position_GroupBox = QGroupBox("位置")
        start_position_layout  = QVBoxLayout(start_position_GroupBox)
        start_positionX_layout = QHBoxLayout()
        start_positionX_layout.addWidget(QLabel("X:"))
        start_positionX = QLineEdit()
        start_positionX_layout.addWidget(start_positionX)
        start_positionY_layout = QHBoxLayout()
        start_positionY_layout.addWidget(QLabel("Y:"))
        start_positionY = QLineEdit()
        start_positionY_layout.addWidget(start_positionY)
        start_position_layout.addLayout(start_positionX_layout)
        start_position_layout.addLayout(start_positionY_layout)

        size_GroupBox = QGroupBox("尺寸")
        size_layout = QVBoxLayout(size_GroupBox)
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("W:"))
        self.width = QLineEdit()
        width_layout.addWidget(self.width)
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("H:"))
        self.height = QLineEdit()
        height_layout.addWidget(self.height)
        size_layout.addLayout(width_layout)
        size_layout.addLayout(height_layout)
        
        layout1.addWidget(start_position_GroupBox)
        layout1.addWidget(size_GroupBox)
       
        layout.addLayout(layout1)
        start_positionX.setText( f"{self.item.get_scene_head_pos().x():.1f}")
        start_positionY.setText( f"{self.item.get_scene_head_pos().y():.1f}")
        start_positionX.editingFinished.connect(lambda:setattr(self,"head_posX" , float(start_positionX.text())) )
        start_positionY.editingFinished.connect(lambda:setattr(self,"head_posY" , float(start_positionY.text())) )

        self.width.setText( f"{self.sizeWidth:.1f}")
        self.height.setText( f"{self.sizeHeight:.1f}")

        self.width.editingFinished.connect(self.on_width_edit_done)
        self.height.editingFinished.connect(self.on_height_edit_done )
        
        return page


    def on_width_edit_done(self):
        scale =  float(self.width.text())/self.sizeWidth
        self.height.setText( f"{(scale*self.sizeHeight):.1f}")
        w = float(self.width.text())
        h = float(self.height.text())
        self.size = QSizeF(w,h)
            
    def on_height_edit_done(self):
        scale =  float(self.height.text())/self.sizeHeight
        self.width.setText( f"{(scale*self.sizeWidth):.1f}")
        w = float(self.width.text())
        h = float(self.height.text())
        self.size = QSizeF(w,h)


    def create_others_page(self):
        page    = QWidget()
        layout  = QVBoxLayout(page)
        layout_row1 = QHBoxLayout()

        others_GroupBox = QGroupBox("其它")
        others_layout  = QVBoxLayout(others_GroupBox)
        members_GroupBox = QGroupBox("组员")
        members_layout  = QVBoxLayout(members_GroupBox)

        group_layout_row1 = QHBoxLayout()
        group_layout_row1.addWidget(QLabel("Z值："))
        self.zValue_spinBox  = QSpinBox()
        self.zValue_spinBox.setRange(0,9999)
        group_layout_row1.addWidget(self.zValue_spinBox)
        self.zValue_spinBox.setEnabled(False)
        self.zValue_spinBox.setValue(self.item.zValue())

        group_layout_row2 = QHBoxLayout()
        group_layout_row2.addWidget(QLabel("id："))
        self.id_spinBox  = QSpinBox()
        self.id_spinBox.setRange(0,9999)
        group_layout_row2.addWidget(self.id_spinBox)
        self.id_spinBox.setEnabled(False)
        self.id_spinBox.setValue(self.item.id())

        group_layout_row3 = QHBoxLayout()
        group_layout_row3.addWidget(QLabel("名称："))
        name_edit  = QLineEdit()
        group_layout_row3.addWidget(name_edit)
        name_edit.setText(self.item.get_name())
        name_edit.editingFinished.connect(lambda: self.apply_name_edit(name_edit))
        name_edit.editingFinished.connect(self.refresh_member_name_text)

        others_layout.addLayout(group_layout_row1)
        others_layout.addLayout(group_layout_row2)
        others_layout.addLayout(group_layout_row3)



        layout_row1.addWidget(others_GroupBox)

        members_group_layout_row1 = QHBoxLayout()
        members_group_layout_row2 = QHBoxLayout()
        members_group_layout_row3 = QHBoxLayout()
        members_group_layout_row1.addWidget(QLabel("成员id："))
        members_id_combox   =QComboBox()
        for item in self.item.childItems():
            members_id_combox.addItem(str(item.id()))
        # for id in self.item.childItems
        
        members_group_layout_row1.addWidget(members_id_combox)
        members_group_layout_row2.addWidget(QLabel("名称："))
        members_name_edit  = QLineEdit()
        # 组员名称随组名自动变化（组名_成员名），此处只读显示，不能单独修改。
        members_name_edit.setReadOnly(True)
        members_name_edit.setToolTip("组员名称随组名自动变化（组名_成员名），不能单独修改")
        # current_member_name = self.item.m_scene_manager.findItem(int(members_id_combox.currentText())).get_name()
        current_member_item =  self.item.m_scene_manager.findItem(int(members_id_combox.currentText()))
        members_name_edit.setText(current_member_item.get_name())
        self.members_name_edit = members_name_edit
        self.members_id_combox = members_id_combox
        members_group_layout_row2.addWidget(members_name_edit)

        members_id_combox.currentTextChanged.connect(lambda e:members_name_edit.setText(self.item.m_scene_manager.findItem(int(e)).get_name()))
        


        self.visibility_checkbox     = QCheckBox(parent=page,text="是否可见")
        self.visibility_checkbox.setChecked(current_member_item.get_visibility())
        self.visibility_checkbox.clicked.connect(self.handle_member_visibility_change)
        members_id_combox.currentTextChanged.connect(lambda e:self.visibility_checkbox.setChecked(self.item.m_scene_manager.findItem(int(e)).get_visibility()))

        members_group_layout_row3.addWidget(self.visibility_checkbox)

        members_layout.addLayout(members_group_layout_row1)
        members_layout.addLayout(members_group_layout_row2)
        members_layout.addLayout(members_group_layout_row3)
        layout_row1.addWidget(members_GroupBox)

        
        
        h_spacer = QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Preferred)
        v_spacer = QSpacerItem(20, 20, QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout_row1.addSpacerItem(h_spacer)

        layout.addLayout(layout_row1)

        layout.addSpacerItem(v_spacer)
        return page

    def refresh_member_name_text(self):
        """组名改变后刷新只读的组员名称显示。"""

        if not hasattr(self, "members_name_edit"):
            return
        member_id = self.members_id_combox.currentText().strip()
        if not member_id:
            return
        member = self.item.m_scene_manager.findItem(int(member_id))
        if member is not None:
            self.members_name_edit.setText(member.get_name())

    def handle_member_visibility_change(self):
        item2set =  self.item.m_scene_manager.findItem(int(self.members_id_combox.currentText()))
        item2set.set_visibility(self.visibility_checkbox.isChecked())



class CirclePropertyItem(PropertyItem):
    """文本属性窗口 - 优化布局"""
    def __init__(self, parent=None,item:circle_element=None):
        super().__init__(item=item)
        self.navi = None
    
    @Property(float)
    def head_posX(self):
        return self.item.get_scene_head_pos().x()
    @head_posX.setter
    def head_posX(self, val):
        if self.item.get_scene_head_pos().x() != val:
            y = self.item.get_scene_head_pos().y()
            self.item.change_position(QPointF(val,y))
    
    @Property(float)
    def head_posY(self):
        return self.item.get_scene_head_pos().y()
    @head_posY.setter
    def head_posY(self, val):
        if self.item.get_scene_head_pos().y() != val:
            x = self.item.get_scene_head_pos().x()
            self.item.change_position(QPointF(x,val))
    
    # @Property(float)
    # def radius(self):
    #     return self.item.radius
    # @radius.setter
    # def radius(self, val):
    #     if self.item.radius != val:
    #         self.item.change_radius(val)
           
    def add_navigation_items(self,navigation):
        # 添加顶级项
        categories = [
            ("属性", "property", [
                ("外观", "appearance"),
                ("布局", "layout"),
                ("其它", "others")
            ])
        ]
        for category, icon, items in categories:
            category_item = QTreeWidgetItem([category])
            category_item.setData(0, Qt.UserRole, f"category_{icon}")
            navigation.navigation_tree.addTopLevelItem(category_item)
            
            for item_name, item_key in items:
                item = QTreeWidgetItem([item_name])
                item.setData(0, Qt.UserRole, item_key)
                category_item.addChild(item)
        
        # 展开所有顶级项
        for i in range(navigation.navigation_tree.topLevelItemCount()):
            navigation.navigation_tree.topLevelItem(i).setExpanded(True)
            # 创建内容页面
        self.create_content_pages(navigation)
        navigation.select_preferred_page()
        navigation.destory_current.connect(self.on_destory_current)
        self.navi = navigation

        
    def on_destory_current(self):
        self.item =None
        self.navi.destory_current.disconnect(self.on_destory_current)
    
    def create_content_pages(self,navi):
        # 创建内容页面
        navi.add_page("appearance", "外观", self.create_appearance_page())
        navi.add_page("layout",     "布局"    , self.create_layout_page())
        navi.add_page("others",     "其它"    , self.create_others_page()    )
    
    
    def create_appearance_page(self):
        page   = QWidget()
        layout = QVBoxLayout(page)
        bg_color_layout   = QHBoxLayout()
        appearance        = QGroupBox("外观")
        appearance_layout = QVBoxLayout()
        line_color_layout = QHBoxLayout()
        line_color_layout.addWidget(QLabel("颜色："))
        fill_checkbox     = QCheckBox(parent=page,text="是否填充")
        fill_checkbox.setChecked(self.item.get_fill())
        fill_checkbox.clicked.connect(lambda:self.item.set_fill(fill_checkbox.isChecked()))
        # 字体颜色
        self.line_color_btn = self.create_color_button(self.item.get_color())
        self.line_color_btn.clicked.connect(lambda: self.select_line_color(page,False))
        bg_color_layout.addWidget(QLabel("背景颜色"))
        self.update_line_color_ui(False)

        self.bg_color_btn   = self.create_color_button(self.item.get_fill_color())
        self.bg_color_btn.clicked.connect(lambda: self.select_line_color(page,True))

        self.line_width_spinBox     = QSpinBox()
        self.line_width_spinBox.valueChanged.connect(lambda:setattr(self,"lineWidth" ,self.line_width_spinBox.value()) )
        self.line_width_spinBox.setValue(self.lineWidth)

        self.opacity_spinBox     = QSpinBox()
        self.opacity_spinBox.setRange(0,255)
        self.opacity_spinBox.valueChanged.connect(lambda:setattr(self,"opacity" ,self.opacity_spinBox.value()) )
        self.opacity_spinBox.setValue(self.opacity)

        line_color_layout.addWidget(self.line_color_btn)
        line_color_layout.addWidget(QLabel("线宽："))
        line_color_layout.addWidget(self.line_width_spinBox)

        
        bg_color_layout.addWidget(self.bg_color_btn)
        bg_color_layout.addWidget(QLabel("透明度："))
        bg_color_layout.addWidget(self.opacity_spinBox)

        appearance_layout.addWidget(fill_checkbox)
        appearance_layout.addLayout(line_color_layout)
        appearance_layout.addLayout(bg_color_layout)
        appearance.setLayout(appearance_layout)
        layout.addWidget(appearance)
        
        return page

    def create_color_button(self, color):
        """创建颜色选择按钮"""
        btn = QPushButton()
        btn.setFixedSize(30, 30)
        
        # 确保 color 是 QColor 类型
        if isinstance(color, str):
            color = QColor(color)
        elif isinstance(color, int):
            color = QColor(color)
        elif not isinstance(color, QColor):
            color = QColor("#000000")  # 默认黑色
            
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color.name()};
                border: 1px solid #adb5bd;
                border-radius: 4px;
            }}
        """)
        return btn
    
    def update_line_color_ui(self,is_bg_color):
        """从对象更新字体颜色UI"""
        if not is_bg_color:
            color = self.item.get_color() 
            color_code = color.name() if isinstance(color, QColor) else "#000000"
            self.line_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
        else:
            color = self.item.get_fill_color()
            color_code = color.name() if isinstance(color, QColor) else "#000000"
            self.bg_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
          
    def select_line_color(self,parent,is_bg_color):
        current_color = self.item.get_color()
        color = QColorDialog.getColor(current_color, parent)
        if color.isValid():
            self.item.set_color(color) if not is_bg_color else self.item.set_fill_color(color)
            if not is_bg_color:
                color_code = color.name() if isinstance(color, QColor) else "#000000"
                self.line_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
            else:
                color_code = color.name() if isinstance(color, QColor) else "#000000"
                self.bg_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
    
    def create_layout_page(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        layout1 = QHBoxLayout()
        # 目录
        start_position_GroupBox = QGroupBox("位置")
        start_position_layout  = QVBoxLayout(start_position_GroupBox)
        start_positionX_layout = QHBoxLayout()
        start_positionX_layout.addWidget(QLabel("X:"))
        start_positionX = QLineEdit()
        start_positionX_layout.addWidget(start_positionX)
        start_positionY_layout = QHBoxLayout()
        start_positionY_layout.addWidget(QLabel("Y:"))
        start_positionY = QLineEdit()
        start_positionY_layout.addWidget(start_positionY)
        start_position_layout.addLayout(start_positionX_layout)
        start_position_layout.addLayout(start_positionY_layout)

        size_GroupBox = QGroupBox("尺寸")
        size_layout = QVBoxLayout(size_GroupBox)
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("W:"))
        width = QLineEdit()
        width_layout.addWidget(width)
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("H:"))
        height = QLineEdit()
        height_layout.addWidget(height)
        size_layout.addLayout(width_layout)
        size_layout.addLayout(height_layout)
        
        layout1.addWidget(start_position_GroupBox)
        layout1.addWidget(size_GroupBox)
       
        layout.addLayout(layout1)
        start_positionX.setText( f"{self.item.get_scene_head_pos().x():.1f}")
        start_positionY.setText( f"{self.item.get_scene_head_pos().y():.1f}")
        start_positionX.editingFinished.connect(lambda:setattr(self,"head_posX" , float(start_positionX.text())) )
        start_positionY.editingFinished.connect(lambda:setattr(self,"head_posY" , float(start_positionY.text())) )

        width.setText( f"{self.sizeWidth:.1f}")
        height.setText( f"{self.sizeHeight:.1f}")
       

        width.editingFinished.connect(lambda:setattr(self,"sizeWidth" , float(width.text())) )
        
        height.editingFinished.connect(lambda:setattr(self,"sizeHeight" , float(height.text())) )


        
        return page
    # def create_layout_page(self):
        
    #     page = QWidget()
    #     layout  = QVBoxLayout(page)
    #     layout1 = QHBoxLayout()
    #     # 目录
    #     start_position_GroupBox = QGroupBox("位置")
    #     start_position_layout  = QVBoxLayout(start_position_GroupBox)
    #     start_positionX_layout = QHBoxLayout()
    #     start_positionX_layout.addWidget(QLabel("X:"))
    #     start_positionX = QLineEdit()
    #     start_positionX_layout.addWidget(start_positionX)
    #     start_positionY_layout = QHBoxLayout()
    #     start_positionY_layout.addWidget(QLabel("Y:"))
    #     start_positionY = QLineEdit()
    #     start_positionY_layout.addWidget(start_positionY)
    #     start_position_layout.addLayout(start_positionX_layout)
    #     start_position_layout.addLayout(start_positionY_layout)

    #     radius_GroupBox = QGroupBox("半径")

    #     radius_GroupBox_layout  = QVBoxLayout(radius_GroupBox)
    #     radius_layout   =QHBoxLayout()
    #     radius_layout.addWidget(QLabel("r:"))
    #     radius = QLineEdit()
    #     radius_layout.addWidget(radius)
        
    #     radius_GroupBox_layout.addLayout(radius_layout )
    #     layout1.addWidget(start_position_GroupBox)
    #     layout1.addWidget(radius_GroupBox)
       
    #     layout.addLayout(layout1)
    #     start_positionX.setText( f"{self.item.get_scene_center_pos().x():.1f}")
    #     start_positionY.setText( f"{self.item.get_scene_center_pos().y():.1f}")
    #     start_positionX.editingFinished.connect(lambda:setattr(self,"center_posX" , float(start_positionX.text())) )
    #     start_positionY.editingFinished.connect(lambda:setattr(self,"center_posY" , float(start_positionY.text())) )

    #     radius.setText( f"{self.radius:.1f}")
      

    #     radius.editingFinished.connect(lambda:setattr(self,"radius" , float(radius.text())) )
       
    #     return page

    def create_others_page(self):
       
        page    = QWidget()
        layout  = QVBoxLayout(page)
        layout_row1 = QHBoxLayout()

        others_GroupBox = QGroupBox("其它")
        others_layout  = QVBoxLayout(others_GroupBox)

        group_layout_row1 = QHBoxLayout()
        group_layout_row1.addWidget(QLabel("Z值："))
        self.zValue_spinBox  = QSpinBox()
        self.zValue_spinBox.setRange(0,9999)
        group_layout_row1.addWidget(self.zValue_spinBox)
        self.zValue_spinBox.setEnabled(False)
        self.zValue_spinBox.setValue(self.item.zValue())

        group_layout_row2 = QHBoxLayout()
        group_layout_row2.addWidget(QLabel("id："))
        self.id_spinBox  = QSpinBox()
        self.id_spinBox.setRange(0,9999)
        group_layout_row2.addWidget(self.id_spinBox)
        self.id_spinBox.setEnabled(False)
        self.id_spinBox.setValue(self.item.id())

        group_layout_row3 = QHBoxLayout()
        group_layout_row3.addWidget(QLabel("名称："))
        name_edit  = QLineEdit()
        group_layout_row3.addWidget(name_edit)
        name_edit.setText(self.item.get_name())
        name_edit.editingFinished.connect(lambda: self.apply_name_edit(name_edit))

        others_layout.addLayout(group_layout_row1)
        others_layout.addLayout(group_layout_row2)
        others_layout.addLayout(group_layout_row3)

        layout_row1.addWidget(others_GroupBox)

        h_spacer = QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Preferred)
        v_spacer = QSpacerItem(20, 20, QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout_row1.addSpacerItem(h_spacer)

        layout.addLayout(layout_row1)

        layout.addSpacerItem(v_spacer)
        return page


class ImagePropertyItem(PropertyItem):
    """文本属性窗口 - 优化布局"""
    def __init__(self, parent=None,item:image_element=None):
        super().__init__(item=item)
        self.navi = None
      
    @Property(float)
    def head_posX(self):
        return self.item.get_scene_head_pos().x()
    @head_posX.setter
    def head_posX(self, val):
        if self.item.get_scene_head_pos().x() != val:
            y = self.item.get_scene_head_pos().y()
            self.item.change_position(QPointF(val,y))
    
    @Property(float)
    def head_posY(self):
        return self.item.get_scene_head_pos().y()
    @head_posY.setter
    def head_posY(self, val):
        if self.item.get_scene_head_pos().y() != val:
            x = self.item.get_scene_head_pos().x()
            self.item.change_position(QPointF(x,val))
    
    
         
    def add_navigation_items(self,navigation):
        # 添加顶级项
        categories = [
            ("属性", "property", [
                ("外观", "appearance"),
                ("布局", "layout"),
                ("其它", "others")
            ])
        ]
        for category, icon, items in categories:
            category_item = QTreeWidgetItem([category])
            category_item.setData(0, Qt.UserRole, f"category_{icon}")
            navigation.navigation_tree.addTopLevelItem(category_item)
            
            for item_name, item_key in items:
                item = QTreeWidgetItem([item_name])
                item.setData(0, Qt.UserRole, item_key)
                category_item.addChild(item)
        
        # 展开所有顶级项
        for i in range(navigation.navigation_tree.topLevelItemCount()):
            navigation.navigation_tree.topLevelItem(i).setExpanded(True)
            # 创建内容页面
        self.create_content_pages(navigation)
        navigation.select_preferred_page()
        navigation.destory_current.connect(self.on_destory_current)
        self.navi = navigation


    def on_destory_current(self):
        self.item =None
        self.navi.destory_current.disconnect(self.on_destory_current)

    def create_content_pages(self,navi):
        # 创建内容页面
        navi.add_page("appearance", "外观", self.create_appearance_page())
        navi.add_page("layout",     "布局"    , self.create_layout_page())
        navi.add_page("others",     "其它"    , self.create_others_page()    )
    
    
    def create_appearance_page(self):
        page   = QWidget()
        layout = QVBoxLayout(page)
        bg_color_layout   = QHBoxLayout()
        appearance        = QGroupBox("外观")
        appearance_layout = QVBoxLayout()
        row1_layout       = QHBoxLayout()
      
        fill_checkbox     = QCheckBox(parent=page,text="是否填充")
        fill_checkbox.setChecked(self.item.get_fill())
        fill_checkbox.clicked.connect(lambda:self.item.set_fill(fill_checkbox.isChecked()))

        btn_select_image = QPushButton(text="选择图片")
        btn_select_image.setFixedSize(30, 25)
        btn_select_image.clicked.connect(self.select_image)
        self.image_path_show = QLineEdit()
        self.image_path_show.setEnabled(False)
        self.image_path_show.setText(self.item.image_path())
        
        bg_color_layout.addWidget(QLabel("背景颜色"))
       

        self.bg_color_btn   = self.create_color_button(self.item.get_fill_color())
        self.bg_color_btn.clicked.connect(lambda: self.select_line_color(page,True))

       
        self.opacity_spinBox     = QSpinBox()
        self.opacity_spinBox.setRange(0,255)
        self.opacity_spinBox.valueChanged.connect(lambda:setattr(self,"opacity" ,self.opacity_spinBox.value()) )
        self.opacity_spinBox.setValue(self.opacity)

       

        
        bg_color_layout.addWidget(self.bg_color_btn)
        bg_color_layout.addWidget(QLabel("透明度："))
        bg_color_layout.addWidget(self.opacity_spinBox)

        row1_layout.addWidget(fill_checkbox)
        row1_layout.addWidget(self.image_path_show)
        row1_layout.addWidget(btn_select_image)
        appearance_layout.addLayout(row1_layout)

        appearance_layout.addLayout(bg_color_layout)
        appearance.setLayout(appearance_layout)
        layout.addWidget(appearance)
        
        return page

    def create_color_button(self, color):
        """创建颜色选择按钮"""
        btn = QPushButton()
        btn.setFixedSize(30, 30)
        
        # 确保 color 是 QColor 类型
        if isinstance(color, str):
            color = QColor(color)
        elif isinstance(color, int):
            color = QColor(color)
        elif not isinstance(color, QColor):
            color = QColor("#000000")  # 默认黑色
            
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color.name()};
                border: 1px solid #adb5bd;
                border-radius: 4px;
            }}
        """)
        return btn
    
    def update_line_color_ui(self,is_bg_color):
        """从对象更新字体颜色UI"""
        if not is_bg_color:
            color = self.item.get_color() 
            color_code = color.name() if isinstance(color, QColor) else "#000000"
            self.line_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
        else:
            color = self.item.get_fill_color()
            color_code = color.name() if isinstance(color, QColor) else "#000000"
            self.bg_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
          
    def select_line_color(self,parent,is_bg_color):
        current_color = self.item.get_color()
        color = QColorDialog.getColor(current_color, parent)
        if color.isValid():
            self.item.set_color(color) if not is_bg_color else self.item.set_fill_color(color)
            if not is_bg_color:
                color_code = color.name() if isinstance(color, QColor) else "#000000"
                self.line_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
            else:
                color_code = color.name() if isinstance(color, QColor) else "#000000"
                self.bg_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
    

    def select_image(self):
        import sys
        parent = self.navi if self.navi else None
        file_path, _ = QFileDialog.getOpenFileName(
            parent,
            "选择图片", 
            "", 
            "图片文件 (*.png);;所有文件 (*)"
        )
        if getattr(sys, 'frozen', False):
            # 打包后的可执行文件路径（如 PyInstaller）
            base_dir = os.path.dirname(sys.executable)
        else:
            # 脚本文件所在路径
            base_dir = os.path.dirname(os.path.abspath(__file__))
        print(base_dir)
        if file_path:
            # 转换为相对于项目根目录的相对路径
            rel_path = os.path.relpath(file_path, base_dir)
            self.item.set_image_path(rel_path)
            self.image_path_show.setText(rel_path)
            return
    
    
    def create_layout_page(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        layout1 = QHBoxLayout()
        # 目录
        start_position_GroupBox = QGroupBox("位置")
        start_position_layout  = QVBoxLayout(start_position_GroupBox)
        start_positionX_layout = QHBoxLayout()
        start_positionX_layout.addWidget(QLabel("X:"))
        start_positionX = QLineEdit()
        start_positionX_layout.addWidget(start_positionX)
        start_positionY_layout = QHBoxLayout()
        start_positionY_layout.addWidget(QLabel("Y:"))
        start_positionY = QLineEdit()
        start_positionY_layout.addWidget(start_positionY)
        start_position_layout.addLayout(start_positionX_layout)
        start_position_layout.addLayout(start_positionY_layout)

        size_GroupBox = QGroupBox("尺寸")
        size_layout = QVBoxLayout(size_GroupBox)
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("W:"))
        width = QLineEdit()
        width_layout.addWidget(width)
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("H:"))
        height = QLineEdit()
        height_layout.addWidget(height)
        size_layout.addLayout(width_layout)
        size_layout.addLayout(height_layout)
        
        layout1.addWidget(start_position_GroupBox)
        layout1.addWidget(size_GroupBox)
       
        layout.addLayout(layout1)
        start_positionX.setText( f"{self.item.get_scene_head_pos().x():.1f}")
        start_positionY.setText( f"{self.item.get_scene_head_pos().y():.1f}")
        start_positionX.editingFinished.connect(lambda:setattr(self,"head_posX" , float(start_positionX.text())) )
        start_positionY.editingFinished.connect(lambda:setattr(self,"head_posY" , float(start_positionY.text())) )

        width.setText( f"{self.sizeWidth:.1f}")
        height.setText( f"{self.sizeHeight:.1f}")
       

        width.editingFinished.connect(lambda:setattr(self,"sizeWidth" , float(width.text())) )
        
        height.editingFinished.connect(lambda:setattr(self,"sizeHeight" , float(height.text())) )


        
        return page

    def create_others_page(self):
        page    = QWidget()
        layout  = QVBoxLayout(page)
        layout_row1 = QHBoxLayout()

        others_GroupBox = QGroupBox("其它")
        others_layout  = QVBoxLayout(others_GroupBox)

        group_layout_row1 = QHBoxLayout()
        group_layout_row1.addWidget(QLabel("Z值："))
        self.zValue_spinBox  = QSpinBox()
        self.zValue_spinBox.setRange(0,9999)
        group_layout_row1.addWidget(self.zValue_spinBox)
        self.zValue_spinBox.setEnabled(False)
        self.zValue_spinBox.setValue(self.item.zValue())

        group_layout_row2 = QHBoxLayout()
        group_layout_row2.addWidget(QLabel("id："))
        self.id_spinBox  = QSpinBox()
        group_layout_row2.addWidget(self.id_spinBox)
        self.id_spinBox.setEnabled(False)
        self.id_spinBox.setValue(self.item.id())

        group_layout_row3 = QHBoxLayout()
        group_layout_row3.addWidget(QLabel("名称："))
        name_edit  = QLineEdit()
        group_layout_row3.addWidget(name_edit)
        name_edit.setText(self.item.get_name())
        name_edit.editingFinished.connect(lambda: self.apply_name_edit(name_edit))

        others_layout.addLayout(group_layout_row1)
        others_layout.addLayout(group_layout_row2)
        others_layout.addLayout(group_layout_row3)

        layout_row1.addWidget(others_GroupBox)

        h_spacer = QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Preferred)
        v_spacer = QSpacerItem(20, 20, QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout_row1.addSpacerItem(h_spacer)

        layout.addLayout(layout_row1)

        layout.addSpacerItem(v_spacer)
        return page
