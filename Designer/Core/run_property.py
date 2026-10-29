# from my_elements_v2 import rect_element, line_element, circle_element, base_element, group_element, text_element
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QTreeWidget, QTreeWidgetItem, QStackedWidget, QLabel, QFrame,QScrollArea,QFileDialog,
    QListWidget, QListWidgetItem, QPushButton, QGroupBox,QColorDialog,QCheckBox,
    QTextEdit, QStyleFactory,QLineEdit,QSpinBox,QSpacerItem,QSizePolicy,QComboBox
)
from PySide6.QtGui import QFont,QColor
from PySide6.QtCore import Qt,QObject,Property,QPointF,QSizeF,Signal
# from my_elements_v2 import base_element,text_element,line_element,rect_element,image_element

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


class CabinetPropertyItem(QObject):
    """文本属性窗口 - 优化布局"""
    
    def __init__(self, parent=None,item:group_element=None):
        super().__init__(parent=parent)
        self.navi = None
        self.item = item
    
    
    
         
    def add_navigation_items(self,navigation):
        # 添加顶级项
        if "维修区/安全门" in self.item.get_name():
            categories = [
                ("选择", "select", [
                
                    ("维修区工作站", "maintain_station"),
                    ("安全门工作站", "safedoor_station")
                ])
            ]
        elif "上架X4" in self.item.get_name():
            categories = [
                ("选择", "select", [
                
                    ("上架工作站1", "shangjia_station1"),
                    ("上架工作站2", "shangjia_station2"),
                    ("上架工作站3", "shangjia_station3"),
                    ("上架工作站4", "shangjia_station4")
                ])
            ]
        elif "拣选X4" in self.item.get_name():
            categories = [
                ("选择", "select", [
                
                    ("Q1P拣选工作站1", "jianxuan_station1"),
                    ("Q1P拣选工作站2", "jianxuan_station2"),
                    ("Q1P拣选工作站3", "jianxuan_station3"),
                    ("Q1P拣选工作站4", "jianxuan_station4")
                ])
            ]
        elif "安全门X1" in self.item.get_name():
            categories = [
                ("选择", "select", [
                
                    ("安全门工作站", "safedoor_station")
                    
                ])
            ]
        
        elif "输送线X2" in self.item.get_name():
            categories = [
                ("选择", "select", [
                
                    ("输送线工作站1", "convey_station1"),
                    ("输送线工作站2", "convey_station2")
                    
                ])
            ]
        
        elif "Q1P拣选/Q3P拣选" in self.item.get_name():
            categories = [
                ("选择", "select", [
                
                    ("Q1P拣选工作站", "q1p_jianxuan_station"),
                    ("Q3P拣选工作站", "q3p_jianxuan_station")
                    
                ])
            ]
        
        elif "Q3P托盘X2" in self.item.get_name():
            categories = [
                ("选择", "select", [
                
                    ("Q3P托盘工作站1", "q3p_tuopan_station1"),
                    ("Q3P托盘工作站2", "q3p_tuopan_station2")
                    
                ])
            ]

        elif "输送线X4" in self.item.get_name():
            categories = [
                ("选择", "select", [
                
                    ("输送线工作站1", "convey_station1"),
                    ("输送线工作站2", "convey_station2"),
                    ("输送线工作站3", "convey_station3"),
                    ("输送线工作站4", "convey_station4")
                    
                ])
            ]

        elif "主电柜" in self.item.get_name():
            categories = [
                ("选择", "select", [
                
                    ("主电柜工作站", "main_station")
                    
                ])
            ]
        else:
            print("未选择电柜")
            return
        for category, icon, items in categories:
            category_item = QTreeWidgetItem([category])
            category_item.setData(0, Qt.UserRole, f"category_{icon}")
            navigation.navigation_tree.addTopLevelItem(category_item)
            
            for item_name, item_key in items:
                item = QTreeWidgetItem([item_name])
                item.setData(0, Qt.UserRole, item_key)
                item.setFlags(item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                print(f"创建项目: {item_name}, flags: {item.flags()}")
                category_item.addChild(item)
        
        # 展开所有顶级项
        for i in range(navigation.navigation_tree.topLevelItemCount()):
            navigation.navigation_tree.topLevelItem(i).setExpanded(True)
            # 创建内容页面
        self.create_content_pages(navigation)
        self.navi = navigation
        
        # 设置选择行为
        navigation.navigation_tree.setSelectionMode(QTreeWidget.SingleSelection)
        navigation.navigation_tree.setSelectionBehavior(QTreeWidget.SelectItems)
        navigation.navigation_tree.setFocusPolicy(Qt.StrongFocus)
        
        # 必须重写mousePressEvent以确保正确触发selectionChanged信号
        # 可能是由于Qt内部事件处理或项目视图的默认行为问题
        navigation.navigation_tree.mousePressEvent = self.debug_mousePressEvent
        
        print("尝试连接itemSelectionChanged信号")
        connected = navigation.navigation_tree.itemSelectionChanged.connect(self.handle_itemSelectionChanged)
        print(f"信号连接结果: {connected is not None}")
        
        # 打印树控件信息
        print(f"树控件选择模式: {navigation.navigation_tree.selectionMode()}")
        print(f"树控件焦点策略: {navigation.navigation_tree.focusPolicy()}")
        
        navigation.select_preferred_page()
        
        navigation.destory_current.connect(self.on_destory_current)
        
        self.handle_itemSelectionChanged()

    def debug_mousePressEvent(self, event):
        """调试鼠标按下事件"""
        print(f"\n鼠标按下事件: {event.pos()}")
        item = self.navi.navigation_tree.itemAt(event.pos())
        if item:
            print(f"点击的项目: {item.text(0)}, 选中状态: {item.isSelected()}")
        else:
            print("未点击到项目")
        # 调用原始事件处理
        QTreeWidget.mousePressEvent(self.navi.navigation_tree, event)

    def handle_itemSelectionChanged(self):
        print("\n--- handle_itemSelectionChanged被调用 ---")
        if not hasattr(self, 'navi') or not self.navi:
            print("错误: navi对象不存在")
            return
        if not hasattr(self, 'item') or not self.item:
            print("错误: item对象不存在")
            return
            
        # 打印所有项目状态
        for i in range(self.navi.navigation_tree.topLevelItemCount()):
            top_item = self.navi.navigation_tree.topLevelItem(i)
            print(f"顶级项目: {top_item.text(0)}, flags: {top_item.flags()}")
            for j in range(top_item.childCount()):
                child = top_item.child(j)
                print(f"  - 子项目: {child.text(0)}, flags: {child.flags()}, 选中: {child.isSelected()}")
            
        # 打印当前选中项和选择状态
        print(f"当前焦点项: {self.navi.navigation_tree.currentItem()}")
        print(f"选中项列表: {self.navi.navigation_tree.selectedItems()}")
       
            
        current_item = self.navi.navigation_tree.currentItem()
        if not current_item:
            print("警告: 没有选中的项")
            return
            
        text = current_item.text(0)
        print(f"选中项文本: {text}")
        
        if hasattr(self.item, 'm_scene'):
            self.item.m_scene.run_mode_station_change.emit(text)
        else:
            print("错误: item没有m_scene属性")
          
        # print(self.navi.navigation_tree.currentItem().columnCount())
                
    def on_destory_current(self):
        self.item =None
        self.navi.destory_current.disconnect(self.on_destory_current)

    def create_content_pages(self,navi):
        # 创建内容页面
        if   "维修区/安全门" in self.item.get_name():
            navi.add_page("maintain_station",     "维修区工作站"    , self.create_page_maintain()    )
            navi.add_page("safedoor_station",     "安全门工作站"    , self.create_page_safedoor()    )
        elif "上架X4" in self.item.get_name():
            navi.add_page("shangjia_station1",     "上架工作站1"    , self.create_page_shangjia()    )
            navi.add_page("shangjia_station2",     "上架工作站2"    , self.create_page_shangjia()    )
            navi.add_page("shangjia_station3",     "上架工作站3"    , self.create_page_shangjia()    )
            navi.add_page("shangjia_station4",     "上架工作站4"    , self.create_page_shangjia()    )
        elif "拣选X4" in self.item.get_name():
            navi.add_page("jianxuan_station1",     "Q1P拣选工作站1"    , self.create_page_jianxuan()    )
            navi.add_page("jianxuan_station2",     "Q1P拣选工作站2"    , self.create_page_jianxuan()    )
            navi.add_page("jianxuan_station3",     "Q1P拣选工作站3"    , self.create_page_jianxuan()    )
            navi.add_page("jianxuan_station4",     "Q1P拣选工作站4"    , self.create_page_jianxuan()    )
        elif "安全门X1" in self.item.get_name():
            navi.add_page("safedoor_station",     "安全门工作站"    , self.create_page_safedoor()    )
        elif "输送线X2" in self.item.get_name():
            navi.add_page("convey_station1",     "输送线工作站1"    , self.create_page_convey()    )
            navi.add_page("convey_station2",     "输送线工作站2"    , self.create_page_convey()    )

        elif "Q1P拣选/Q3P拣选" in self.item.get_name():
            navi.add_page("q1p_jianxuan_station",     "Q1P拣选工作站"    , self.create_page_jianxuan()    )
            navi.add_page("q3p_jianxuan_station",     "Q3P拣选工作站"    , self.create_page_q3p_jianxuan()    )
        elif "Q3P托盘X2" in self.item.get_name():
            navi.add_page("q3p_tuopan_station1",     "Q3P托盘工作站1"    , self.create_page_q3p_tuopan()    )
            navi.add_page("q3p_tuopan_station2",     "Q3P托盘工作站2"    , self.create_page_q3p_tuopan()    )
        elif "输送线X4" in self.item.get_name():
            navi.add_page("convey_station1",     "输送线工作站1"    , self.create_page_convey()    )
            navi.add_page("convey_station2",     "输送线工作站2"    , self.create_page_convey()    )
            navi.add_page("convey_station3",     "输送线工作站3"    , self.create_page_convey()    )
            navi.add_page("convey_station4",     "输送线工作站4"    , self.create_page_convey()    )
        
        elif "主电柜" in self.item.get_name():
            navi.add_page("main_station",     "主电柜工作站"        , self.create_page_main()    )
    def create_page_maintain(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        tips_group=QGroupBox("维修区工作站逻辑说明")
        group_layout =QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setPlainText(
                                "1.急停拍下或者光栅启用的情况下触发光栅，则进入安全触发状态\n" \
                                "2.门锁开时启用光栅，门锁关时禁用光栅\n"\
                                "3.钥匙旋到开锁档，锁失电开锁\n"\
                                "4.钥匙旋到关锁档，一定时间内未监测到上锁信号，则进入安全触发状态\n"\
                                "5.安全触发状态下，若未触发急停，按下复位解除安全触发状态\n"\
                                "6.红灯/蜂鸣：安全触发状态 ，绿灯：正常状态 ，黄灯：未使用\n"
                                )  # 设置纯文本
        text_edit.setReadOnly(True)
        group_layout.addWidget(text_edit)
        tips_group.setLayout(group_layout)
        layout.addWidget(tips_group)
        return page
    
    def create_page_safedoor(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        tips_group=QGroupBox("安全门工作站逻辑说明")
        group_layout =QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setPlainText(
                                "1.急停拍下，则进入安全触发状态\n" \
                                "2.安全触发状态下，旋转钥匙，可以开锁\n"\
                                "3.钥匙旋到关锁档，一定时间内未监测到上锁信号，则进入安全模式\n"\
                                "4.安全模式下，若未触发急停，按下复位解除安全模式\n"\
                                "5.如果启用了火警信号，火警信号出发时，会强制开锁\n"\
                                "6.红灯/蜂鸣：安全触发状态 ，绿灯：正常状态 ，黄灯：未使用\n"
                                )  # 设置纯文本
        text_edit.setReadOnly(True)
        group_layout.addWidget(text_edit)
        tips_group.setLayout(group_layout)
        layout.addWidget(tips_group)
        return page
    
    def create_page_shangjia(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        tips_group=QGroupBox("上架工作站逻辑说明")
        group_layout =QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setPlainText(
                                "1.急停拍下或者光栅启用的情况下触发光栅，则进入安全模式\n" \
                                "2.光电1光电2检测进箱，光电3，4检测辊筒上是否有箱子\n"
                                "3.进箱模式：500ms内同时触发光电1和光电2，屏蔽光栅\n"\
                                "4.进箱模式：屏蔽光栅的情况下，光栅在2s内未被遮挡，启用光栅\n"\
                                "5.出箱模式：光电4检测到箱子被放上辊筒后，延时2s，屏蔽光栅\n"\
                                "6.出箱模式：箱子取出，辊筒上光电未检测到箱子，光栅未被遮挡，2s后，启用光栅\n"\
                                "7.出箱模式：光电4检测到箱子被放上辊筒后，延时2s，屏蔽光栅\n"\
                                "8.安全触发状态下，若未触发急停且光栅未遮挡，按下复位解除安全触发状态\n"\
                                "9.红灯/蜂鸣：安全触发状态 ，绿灯：正常状态，光栅启用 ，黄灯：光栅禁用\n"
                                )  # 设置纯文本
        text_edit.setReadOnly(True)
        group_layout.addWidget(text_edit)
        tips_group.setLayout(group_layout)
        layout.addWidget(tips_group)
        return page
    
    def create_page_jianxuan(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        tips_group=QGroupBox("拣选工作站逻辑说明")
        group_layout =QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setPlainText(
                                "1.急停拍下或者光栅启用的情况下触发光栅，则进入安全模式\n" \
                                "2.两个光电都监测到物体并且持续1s时，则禁用光栅，否则光栅将被启用\n"\
                                "3.安全触发状态下，若未触发急停且光栅未遮挡，按下复位解除安全触发状态\n"\
                                "4.红灯/蜂鸣：安全触发状态 ，绿灯：正常状态，光栅启用 ，黄灯：光栅禁用\n"
                                
                                )  # 设置纯文本
        text_edit.setReadOnly(True)
        group_layout.addWidget(text_edit)
        tips_group.setLayout(group_layout)
        layout.addWidget(tips_group)
        return page
    
    def create_page_convey(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        tips_group=QGroupBox("输送线工作站逻辑说明")
        group_layout =QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setPlainText(
                                "1.急停拍下或者光栅启用的情况下触发光栅，则进入安全模式\n"\
                                "2.光电1光电2检测进箱\n"\
                                "3.进箱模式:500ms内同时触发光电1和光电2,屏蔽光栅\n"\
                                "4.进箱模式:屏蔽光栅的情况下,光栅在2s内未被遮挡,启用光栅\n" \
                                "5.安全触发状态下，若未触发急停且光栅未遮挡，按下复位解除安全触发状态\n"\
                                "6.红灯/蜂鸣:安全触发状态 ，绿灯：正常状态，光栅启用 ，黄灯：光栅禁用\n"
                                )  # 设置纯文本
        text_edit.setReadOnly(True)
        group_layout.addWidget(text_edit)
        tips_group.setLayout(group_layout)
        layout.addWidget(tips_group)
        return page
    

    def create_page_q3p_jianxuan(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        tips_group=QGroupBox("q3p拣选工作站逻辑说明")
        group_layout =QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setPlainText(
                                "1.急停拍下或者光栅启用的情况下触发光栅，则进入安全模式\n"\
                                
                                )  # 设置纯文本
        text_edit.setReadOnly(True)
        group_layout.addWidget(text_edit)
        tips_group.setLayout(group_layout)
        layout.addWidget(tips_group)
        return page
    
    def create_page_q3p_tuopan(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        tips_group=QGroupBox("q3p托盘工作站逻辑说明")
        group_layout =QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setPlainText(
                                "1.急停拍下或者光栅启用的情况下触发光栅，则进入安全模式\n"\
                                
                                )  # 设置纯文本
        text_edit.setReadOnly(True)
        group_layout.addWidget(text_edit)
        tips_group.setLayout(group_layout)
        layout.addWidget(tips_group)
        return page


    def create_page_main(self):
        page = QWidget()
        layout  = QVBoxLayout(page)
        tips_group=QGroupBox("主电柜工作台逻辑说明")
        group_layout =QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setPlainText(
                                "1.急停拍下，则进入安全模式\n" \
                                "2.使能复位按钮按下的情况下，复位按钮信号有效，工作台复位信号可作为所有站点的复位信号\n"\
                                "3.红灯/蜂鸣：安全触发状态/火警信号触发 ，绿灯：正常状态 ，黄灯：未使用\n"
                                )  # 设置纯文本
        text_edit.setReadOnly(True)
        group_layout.addWidget(text_edit)
        tips_group.setLayout(group_layout)
        layout.addWidget(tips_group)
        return page