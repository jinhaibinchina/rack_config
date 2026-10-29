import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QCheckBox,QSpinBox,
    QTreeWidget, QTreeWidgetItem, QStackedWidget, QLabel, QFrame,QScrollArea,
    QListWidget, QListWidgetItem, QPushButton, QGroupBox,QColorDialog,
    QTextEdit, QStyleFactory
)
from PySide6.QtGui import QFont,QColor
from PySide6.QtCore import Qt,Signal
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
# from my_elements_v2 import rect_element, triangle_element, line_element, circle_element, base_element, group_element, text_element,image_element
from .myGraphicsScene import myGraphicsScene

from .myPropertyForElement import TextPropertyItem,LinePropertyItem,RectPropertyItem,TrianglePropertyItem,CirclePropertyItem,GroupPropertyItem,ImagePropertyItem
from .run_property import CabinetPropertyItem
from .my_common import SceneMode

class NavigationContentWidget(QWidget):
    destory_current =Signal()
    def create_navigation_scroll(self):
        """创建带滚动条的导航区域"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        # 创建容器
        container = QWidget()
        scroll_area.setWidget(container)
        
        # 导航树布局
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.navigation_tree = self.create_navigation_tree()
        layout.addWidget(self.navigation_tree)
        
        return scroll_area
    
    def create_content_scroll(self):
        """创建带滚动条的内容区域"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        # 创建容器
        self.content_container = QWidget()
        scroll_area.setWidget(self.content_container)
        
        # 内容布局
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建内容堆栈
        self.content_stack = QStackedWidget()
        self.content_layout.addWidget(self.content_stack)
        
        return scroll_area
    
    def apply_style(self):
        # 应用现代样式
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        
        # 基础样式
        base_style = """
            QWidget {
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
            }
            QSplitter::handle {
                background-color: #e0e0e0;
                width: 3px;
            }
            QScrollArea {
                background-color: #ffffff;
                border: none;
            }
        """
        
        # 导航树样式
        tree_style = """
            QTreeWidget {
                background-color: #f5f5f5;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                padding: 5px;
            }
            QTreeWidget::item {
                height: 28px;
                padding: 5px;
            }
            QTreeWidget::item:selected {
                background-color: #e0f0ff;
                color: #0066cc;
                font-weight: bold;
            }
            QTreeWidget::item:hover {
                background-color: #e8f4ff;
            }
        """
        
        # 内容区样式
        content_style = """
            QGroupBox {
                font-weight: bold;
                font-size: 14px;
                padding-top: 10px;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                margin-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 5px;
                background-color: transparent;
            }
            QTextEdit {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                padding: 10px;
            }
            QListWidget {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 8px;
            }
            QListWidget::item:selected {
                background-color: #e0f0ff;
                color: #0066cc;
            }
            QPushButton {
                background-color: #4a86e8;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #3a76d8;
            }
            QPushButton:pressed {
                background-color: #2a66c8;
            }
        """
        
        self.setStyleSheet(base_style + tree_style + content_style)
    
    def create_navigation_tree(self):
        tree = QTreeWidget()
        tree.setHeaderLabel("导航菜单")
        tree.setColumnCount(1)
        tree.header().setVisible(False)
        
        # 连接选择变更信号
        tree.currentItemChanged.connect(self.on_navigation_changed)

        return tree
    
    
    def __init__(self, parent=None,scene=None):
        super().__init__(parent)
        self.property_items = {}  # 存储属性项的字典
        self._last_page_key = None  # 记录上一次停留的导航页
        self.setWindowTitle("树状导航与内容视图")
        # self.setMinimumSize(800, 600)
   
        # 主布局
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # 创建分割器
        self.splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.splitter)
        
        # 创建左侧导航树（带滚动条）
        self.navigation_scroll = self.create_navigation_scroll()
        self.splitter.addWidget(self.navigation_scroll)
        
        # 创建右侧内容堆栈（带滚动条）
        self.content_scroll = self.create_content_scroll()
        self.splitter.addWidget(self.content_scroll)
        
        # 设置分割器初始比例 (30:70)
        self.splitter.setSizes([300, 700])

        self.item = scene
        self.scene = scene
        # 添加导航项和对应内容页
        self.add_navigation_items()
        
        # 设置样式
        self.apply_style()

        # # 连接场景管理器的删除信号
        # if hasattr(scene, 'scene_manager'):
        #     scene.scene_manager.delete_item_signal.connect(self.on_item_deleted)

    # def on_item_deleted(self, item):
    #     """当元素被删除时清理对应的属性项"""
    #     item_id = item.id()
    #     if item_id in self.property_items.keys():
    #         prop_item = self.property_items.pop(item_id)
    #         if hasattr(prop_item, 'deleteLater'):
    #             prop_item.deleteLater()

    def update_for_selected(self,selected_obj):
        self.navigation_tree.clear()
        self.clear_stacked_widget()
      
        # # 清理之前的属性项
        # for item in self.property_items.values():
        #     if hasattr(item, 'deleteLater'):
        #         item.deleteLater()
        # self.property_items.clear()
        if self.scene.mode() == SceneMode.Design:
            if isinstance(selected_obj,myGraphicsScene):
                self.item = selected_obj
                self.add_navigation_items()
            elif isinstance(selected_obj,text_element):
                TextPropertyItem(item=selected_obj).add_navigation_items(self)
            
            elif isinstance(selected_obj,line_element):
                LinePropertyItem(item=selected_obj).add_navigation_items(self)
                
            elif isinstance(selected_obj,group_element):
                GroupPropertyItem(item=selected_obj).add_navigation_items(self)
            
            elif isinstance(selected_obj,triangle_element):
                TrianglePropertyItem(item=selected_obj).add_navigation_items(self)

            elif isinstance(selected_obj,rect_element):
                RectPropertyItem(item=selected_obj).add_navigation_items(self)
            
            elif isinstance(selected_obj,circle_element):
                CirclePropertyItem(item=selected_obj).add_navigation_items(self)
            
            elif isinstance(selected_obj,image_element):
                ImagePropertyItem(item=selected_obj).add_navigation_items(self)
        else:
            if isinstance(selected_obj,group_element):
                CabinetPropertyItem(item=selected_obj).add_navigation_items(self)
            # elif isinstance(selected_obj,myGraphicsScene):
            #     self.item = selected_obj
            #     self.add_navigation_items()
        
        

    def add_navigation_items(self):
        
        # 添加顶级项
        categories = [
            ("属性", "property", [
                ("外观", "appearance"),
                ("布局", "layout")
            ])
        ]
        
        for category, icon, items in categories:
            category_item = QTreeWidgetItem([category])
            category_item.setData(0, Qt.UserRole, f"category_{icon}")
            self.navigation_tree.addTopLevelItem(category_item)
            
            for item_name, item_key in items:
                item = QTreeWidgetItem([item_name])
                item.setData(0, Qt.UserRole, item_key)
                category_item.addChild(item)
        
        # 展开所有顶级项
        for i in range(self.navigation_tree.topLevelItemCount()):
            self.navigation_tree.topLevelItem(i).setExpanded(True)
        
   
        
    
        
        # 创建内容页面
        self.create_content_pages()
      
        self.select_preferred_page()
    
    def create_content_pages(self):
 
        self.add_page("appearance", "外观", self.create_appearance_page())
        
    def add_page(self, page_id, title, widget):
        # 为每个页面添加滚动支持
        scroll_widget = QScrollArea()
        scroll_widget.setWidget(widget)
        scroll_widget.setWidgetResizable(True)
        scroll_widget.setObjectName(page_id)
        
        self.content_stack.addWidget(scroll_widget)

    def clear_stacked_widget(self):
        # 方法1：逐个移除并删除（推荐）
        while self.content_stack.count() > 0:
            widget = self.content_stack.widget(0)  # 获取第一个widget
            self.content_stack.removeWidget(widget)  # 从stackedWidget移除
            widget.deleteLater()  # 安全删除widget
        self.destory_current.emit()
    
    def on_navigation_changed(self, current, previous):
        if current is not None:
            page_id = current.data(0, Qt.UserRole)
            if page_id:
                # 查找对应页面
                for i in range(self.content_stack.count()):
                    if self.content_stack.widget(i).objectName() == page_id:
                        self.content_stack.setCurrentIndex(i)
                        # 记录用户停留的页面，切换图元时恢复
                        if not str(page_id).startswith("category_"):
                            self._last_page_key = page_id
                        return

    def select_preferred_page(self):
        """选中上一次停留的导航页，不存在时回退到第一项。"""
        if self._last_page_key and self._select_navigation_key(self._last_page_key):
            return
        tree = self.navigation_tree
        if tree.topLevelItemCount() == 0:
            return
        first_category = tree.topLevelItem(0)
        if first_category.childCount() > 0:
            tree.setCurrentItem(first_category.child(0))
        else:
            tree.setCurrentItem(first_category)

    def _select_navigation_key(self, page_key):
        """在导航树中按页面标识定位并选中节点。

        只有已经创建了对应内容页的节点才会被选中，避免树上的高亮
        与右侧内容不一致（例如背景场景没有“布局”页）。
        """
        tree = self.navigation_tree
        for i in range(tree.topLevelItemCount()):
            category_item = tree.topLevelItem(i)
            if category_item.data(0, Qt.UserRole) == page_key and self._has_page(page_key):
                tree.setCurrentItem(category_item)
                return True
            for j in range(category_item.childCount()):
                child = category_item.child(j)
                if child.data(0, Qt.UserRole) == page_key and self._has_page(page_key):
                    tree.setCurrentItem(child)
                    return True
        return False

    def _has_page(self, page_key):
        """判断内容堆栈中是否已存在对应的页面。"""
        for i in range(self.content_stack.count()):
            if self.content_stack.widget(i).objectName() == page_key:
                return True
        return False
                    
    # 以下是各内容页面的创建函数
    def create_appearance_page(self):
        page   = QWidget()
        layout = QVBoxLayout(page)
        bg_color_layout   = QHBoxLayout()
        appearance        = QGroupBox("外观")
        appearance_layout = QVBoxLayout()

        bg_color_layout.addWidget(QLabel("背景颜色"))
        

        self.bg_color_btn   = self.create_color_button(self.item.get_bg_color())
        self.bg_color_btn.clicked.connect(lambda: self.select_bg_color(page))
        bg_color_layout.addWidget(self.bg_color_btn)

        if self.item:
            self.update_bg_color_ui()
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
    
    def update_bg_color_ui(self):
        """从对象更新字体颜色UI"""
        color = self.item.get_bg_color()
        color_code = color.name() if isinstance(color, QColor) else "#000000"
        self.bg_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
        
          
    def select_bg_color(self,parent):
        current_color = self.item.get_bg_color()
        color = QColorDialog.getColor(current_color, parent)
        if color.isValid():
            self.item.set_bg_color(color) 
            color_code = color.name() if isinstance(color, QColor) else "#000000"
            self.bg_color_btn.setStyleSheet(f"background-color: {color_code}; border: 1px solid #adb5bd; border-radius: 4px;")
                
    

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NavigationContentWidget()
    window.show()
    sys.exit(app.exec())
