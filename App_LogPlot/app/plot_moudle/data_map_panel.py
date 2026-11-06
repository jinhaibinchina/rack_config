from PySide6.QtWidgets import QMainWindow, QApplication,QMenu,QDialog,QTreeWidget,QTreeWidgetItem,QStyledItemDelegate,QStyle
from PySide6.QtWidgets import ( QApplication,QWidget,QVBoxLayout, QFrame,QSplitter,QListWidget,
                             QHBoxLayout, QLabel,QLineEdit,QToolTip,QCheckBox, QPushButton,QMessageBox,QToolButton)
from PySide6.QtCore import Signal, Qt, QMimeData,QPoint, Slot,QEvent,QObject,QTimer,QStringListModel,QRect
from PySide6.QtGui import QDrag,QPixmap,QMouseEvent,QFont,QColor,QFontMetrics

from .common import rcd_data_bridge,PlotDataMapRef
from .data_transformer import DataTransformer
from .script_dialog import ScriptInputDialog

import json
from .resource_manager import resource_manager as res_mng
from .translater import rcd_translater
from .global_config import global_config
import numpy as np
import pandas as pd
from typing import Dict



def text_to_pixmap_v1(text, width=200, height=30, font_size=10, bg_color="#FFFFFF", text_color="#000000"):
    """使用QLabel生成带样式的文本框pixmap"""
    # 创建临时的QLabel
    label = QLabel()
    label.setText(text)
    label.setAlignment(Qt.AlignCenter)
    label.setFixedSize(width, height)
    # font =QFont()
    # font.setPixelSize(16)

    # 设置样式
    label.setStyleSheet(f"""
        QLabel {{
            background-color: {bg_color};
            color: {text_color};
            border: 2px solid #CCCCCC;
            border-radius: 5px;
            font-size: {font_size}px;
            font-family: Arial, sans-serif;
            padding: 5px;
        }}
    """)

    # 生成pixmap
    return label.grab()

class ClickableQLabel(QLabel):
    """可点击的QLabel"""
    
    # 定义点击信号
    clicked = Signal()
    doubleClicked = Signal()
    rightClicked = Signal()
    
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(18)
        # 设置样式
        self.setStyleSheet(f"""
            QLabel {{
                
                border: 1px solid #CCCCCC;
                
                font-size: {12}px;
                font-family: Arial, sans-serif;
                padding: 3px;
            }}
        """)

    
    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        elif event.button() == Qt.RightButton:
            self.rightClicked.emit()
        super().mousePressEvent(event)
    
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """鼠标双击事件"""
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

class rcd_panel_filter(QFrame):
    def __init__(self,rcd_label:ClickableQLabel,tool_btn:QToolButton, parent=None):
        super().__init__( parent)
        layout = QHBoxLayout(self)
        
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        layout.addWidget(rcd_label)
        self.edit = QLineEdit()
              # 设置样式
        self.setStyleSheet(f"""
            QLineEdit {{
                background-color: #FFFFFF;
                color: #212121;
                border: 1px solid #E0E0E0;
                border-radius: 3px;
                padding: 1px;
                font-size: 8px;
                    }}
        """)
        
        self.edit.setPlaceholderText("输入以过滤")
        layout.addWidget(self.edit)
        layout.addWidget(tool_btn)

        hot_words = ["linear","wheel","motor"]
        self.setupCompleter(hot_words)
    def setupCompleter(self, word_list):
        from PySide6.QtWidgets import QCompleter
        
        # 创建补全器
        self.completer = QCompleter()
        
        # 创建字符串列表模型
        model = QStringListModel(word_list)
        self.completer.setModel(model)
        
        # 设置补全模式
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        # PySide6 对枚举参数是强类型的，PyQt5 时代传 False 也能被吞下去
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)  # 不区分大小写
        self.completer.setFilterMode(Qt.MatchContains)  # 包含匹配
        self.edit.mousePressEvent = self.customMousePressEvent
        # 设置弹出框样式
        self.completer.popup().setStyleSheet("""
            QListView {
                background-color: white;
                border: 1px solid #ccc;
                font-size: 12px;
                outline: none;
            }
            QListView::item {
                padding: 5px 10px;
                border-bottom: 1px solid #f0f0f0;
            }
            QListView::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
            }
            QListView::item:hover {
                background-color: #f5f5f5;
            }
        """)
        # 关联到 QLineEdit
        self.edit.setCompleter(self.completer)
        # 连接选择信号
        self.completer.activated.connect(self.on_completion_selected)

    def on_completion_selected(self,text):
        print(f"选择了{text} ")

    def customMousePressEvent(self, event):
        """自定义鼠标点击事件，点击时显示补全列表"""
        # 调用原始的鼠标点击事件
        QLineEdit.mousePressEvent(self.edit, event)
        
        # 延迟显示补全列表，确保焦点已经获得
        QTimer.singleShot(50, self.show_completer_popup)
    
    def show_completer_popup(self):
        """显示补全弹出框"""
        if self.edit.hasFocus():
            # 设置一个空字符串来触发显示所有选项
            self.completer.setCompletionPrefix("")
            self.completer.complete()
			
class rcd_panel_tips(QFrame):

    ValueShowSignalChange =Signal(bool)
    def __init__(self, parent=None):
        super().__init__( parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self._label =QLabel("...")
        self._label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._check_box =QCheckBox("Values")
        layout.addWidget(self._label)
        layout.addWidget(self._check_box)
        layout.setStretch(0,2)
        layout.setStretch(1,1)
        self.setLayout(layout)

        self._check_box.setEnabled(False)
        self._check_box.setChecked(False)
        self._check_box.clicked.connect(lambda checked:self.ValueShowSignalChange.emit(checked))
        
    def set_tips(self,text:str):
        self._label.setText(text)

class TreeWigdetEventFilter(QObject):
    """事件过滤器类（必须继承QObject）"""
    def __init__(self,data_bridge:rcd_data_bridge,translater:rcd_translater):
        super().__init__()
        self._data_bridge = data_bridge
        self._translater = translater


    
    def eventFilter(self, obj, event):
        tree_widget = obj.parent()
        if isinstance(tree_widget, QTreeWidget):
            if event.type() == QEvent.ToolTip :
                index = tree_widget.indexAt(event.pos())
                if index.isValid():
                    item = tree_widget.itemFromIndex(index)
                    if item.parent() :
                    # 实时从 item 获取数据生成 Tooltip
                        tooltip_text = self.generateDynamicTooltip(item)
                        if tooltip_text:
                            QToolTip.showText(event.globalPos(), tooltip_text)
                            QTimer.singleShot(1000, QToolTip.hideText)
                        

                        return True
                    
        return super().eventFilter(obj, event)
    def generateDynamicTooltip(self, item:QTreeWidgetItem):
        """实时生成 Tooltip 内容"""
        # 获取基础文本数据
        headname =  item.data(0, Qt.UserRole)
        row_data = self._data_bridge.row_data()
        if global_config.show_rcd_helping_text_on_panel:
            head_str = headname
        else:
            tr = self._translater.translate_title(headname)
            head_str = tr if tr else headname
        if row_data is None:
            return head_str
        value =self._data_bridge.row_data()[headname]

        value_str = self._translater.translate_data(headname,value) if rcd_data_bridge.is_numeric(value) else None
        result_tr = head_str +":" + value_str if value_str else head_str
        
        return result_tr

class rcd_panel(QFrame):
    # 定义拖拽信号
    data_dragged = Signal(str, object)  # 信号：数据名称，数据内容

    data_name_clicked = Signal(str)
    @staticmethod
    def data_handle(src_data):
        if pd.isna(src_data):
            return "NAN"
        try:
            if isinstance(src_data, np.int64):
                result = str(src_data)
            else:
                result =  f"{src_data:.2f}"
        except:
            result = src_data
        return result
    @staticmethod
    def data_head_to_root_name(head_name:str,root_name_map:dict):
        father_root_names =  root_name_map.keys()   #["flc_sta","ctu_io",...]
        for names in father_root_names:# "flc_sta"...
            # if head_name.startswith(names+"_"):
            #     return names+"/" + head_name[len(names)+1:]
            if head_name.startswith(names):
                return names+"/" + head_name[len(names):]
        return "others"+"/" + head_name

    @staticmethod
    def root_name_to_data_head(key_name:str):
        return key_name.replace('/', '_')
    
    @staticmethod
    def split_by_separator(text, separator="/"):
        """
        获取分隔符前后的字符串（静态方法）
        
        Args:
            text: 要分割的字符串
            separator: 分隔符，默认为"@"
        
        Returns:
            tuple: (分隔符前的字符串, 分隔符后的字符串)
        """
        if not isinstance(text, str):
            raise ValueError("输入必须是字符串")
        
        if separator in text:
            parts = text.split(separator, 1)  # 只分割一次
            return parts[0], parts[1]
        else:
            return text, ""
	
    def __init__(self,dataBridge: rcd_data_bridge,translater:rcd_translater=None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Box)
        self.setContentsMargins(5, 5, 5, 5)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(1)
        # 添加简单的标签说明
        
        label = ClickableQLabel("RCD数据")
        self.hide_btn =QToolButton()
        self.hide_btn.setArrowType(Qt.ArrowType.LeftArrow)
        filter_frame =rcd_panel_filter(label,self.hide_btn,self)
        
        # self._filter.setMaximumHeight(label.height())
        filter_frame.edit.textChanged.connect(lambda:self.on_filter_text_edited(filter_frame.edit.text()))

        self.tips_frame =rcd_panel_tips(self)
        global_config.update_rcd_panel_data.connect(self.on_update_panel_data)
        global_config.rcdPanelValueShowSignalChange.connect(self.on_show_panel_values_change)
        
        self.__translater = translater
      
        self.__rcd_data_bridge = dataBridge
      
        self.drag_start_position = None
        
        self.father_roots = {}
        self.child_roots = {}  
        self.item_selected =  QTreeWidgetItem|None
        # self.item_selected.

        # 构建新生成的数据结构
        self.father_root_map_cfg = None
        
        
        
        self.tree_widget = QTreeWidget()

        # self.tree_widget = NumberTreeWidget()

        self.tree_widget.setHeaderHidden(True)
        # self.tree_widget.setColumnCount(2)
        self.tree_widget.setColumnCount(2)
        self.tree_widget.setColumnWidth(0, 290)  # 第1列宽度300像素
        # self.tree_widget.setColumnWidth(1, 2)  # 第2列宽度50像素
        self.tree_widget.setColumnWidth(1, 80)  # 第3列宽度200像素

        self.apply_light_theme()
        
                
        self._selected_item =None
        self._in_collect_area = False
        
        
        self._show_values_flag = True
        self._row_index_last   = 0
        self._max_data_item_count =0


        self.tree_widget.itemClicked.connect(self.on_item_clicked)
        self.tree_widget.itemDoubleClicked.connect(self.on_item_DoubleClicked)
        label.clicked.connect(self.change_tree_expand_status)

        
        main_layout.addWidget(filter_frame)    
        main_layout.addWidget(self.tips_frame)   
        main_layout.addWidget(self.tree_widget)

        # 启用拖拽功能
        self.tree_widget.setDragEnabled(True)
        self.tree_widget.viewport().setMouseTracking(True)
        self.tree_widget.mousePressEvent = self.tree_mouse_press_event
        self.tree_widget.mouseMoveEvent = self.tree_mouse_move_event

        self.event_filter = TreeWigdetEventFilter(self.__rcd_data_bridge,self.__translater)
        # 安装事件过滤器
        self.tree_widget.viewport().installEventFilter(self.event_filter)
        # self.tree_widget.installEventFilter()
        
        self.setLayout(main_layout)
	
    def clear_tree_list(self):
        self.father_roots.clear()
        self.child_roots.clear()
        self.tree_widget.clear()
    
    def on_update_panel_data(self,row_index):
        """current idx changed"""
        self._row_index_last   = row_index
        if not global_config.show_rcd_panel_values_en:
            return
        rowdata =self.__rcd_data_bridge.request_data_by_idx(row_index)

        if rowdata is not None:
        
            for i in range(self.tree_widget.topLevelItemCount()):
                parentItem = self.tree_widget.topLevelItem(i)
                for i in range(parentItem.childCount()):
                    child  = parentItem.child(i)
                    head_name = child.data(0, Qt.UserRole)
                    new_data_to_set = rowdata[head_name]
                    new_data_str =  rcd_panel.data_handle(new_data_to_set)
                    child.setText(1, new_data_str) 
	
    @Slot()
    def on_show_panel_values_change(self):
        """是否显示values checkbox changed"""
        if global_config.show_rcd_panel_values_en:
           
            rowdata =self.__rcd_data_bridge.request_data_by_idx(self._row_index_last)
            if  rowdata is None:
                return
            for i in range(self.tree_widget.topLevelItemCount()):
                parentItem = self.tree_widget.topLevelItem(i)
                for i in range(parentItem.childCount()):
                    child  = parentItem.child(i)
                    head_name = child.data(0, Qt.UserRole)
                    new_data_to_set = rowdata[head_name]
                    new_data_str =  rcd_panel.data_handle(new_data_to_set)
                    child.setText(1, new_data_str) 
        else:
            
            for i in range(self.tree_widget.topLevelItemCount()):
                parentItem = self.tree_widget.topLevelItem(i)
                for i in range(parentItem.childCount()):
                    child  = parentItem.child(i)
                    child.setText(1, "") 
	
    def on_rcd_data_update(self):
        """每次导入日志后执行"""
        self.clear_tree_list()
        self.father_root_map_cfg = self.__rcd_data_bridge.cfg
        
       
        for data_head in self.__rcd_data_bridge.head_names():
            
            root_name = rcd_panel.data_head_to_root_name(data_head,self.father_root_map_cfg)
            father_root, child_root = rcd_panel.split_by_separator(root_name)
            if father_root in self.father_roots.keys():
                self.child_roots[father_root][child_root] = None
            else:
                self.father_roots[father_root] = {}
                self.child_roots[father_root] = {}
                self.child_roots[father_root][child_root] = None
        
        for root_name, root_value in self.child_roots.items():
            root = QTreeWidgetItem(self.tree_widget)
            tip_root_name = self.father_root_map_cfg[root_name]
            root.setText(0, tip_root_name)
            self.father_roots[root_name] = root
            
            for child_name, _ in root_value.items():
                child = QTreeWidgetItem(root)
                if "others" != root_name:
                    # head_name = root_name + "_" +child_name
                    head_name = root_name + child_name
                else:
                    head_name = child_name
                child.setData(0, Qt.UserRole, head_name)
                show_name  =  self.get_child_item_name_for_show(head_name)
                child.setText(0, show_name) 
                
                root_value[child_name] = child
        count = None
		
        for i in range(self.tree_widget.topLevelItemCount()):
            if self.tree_widget.topLevelItem(i).text(0) == "未分类":
                # item2move = self.tree_widget.topLevelItem(i)
                count = i
                break
        if count:
            item = self.tree_widget.takeTopLevelItem(count)
            self.tree_widget.addTopLevelItem(item)

        collect = QTreeWidgetItem()    
        collect.setText(0,"收藏夹")

        font = QFont()
        font.setPointSize(9)
        # font.setPixelSize(10)
        # Qt6 的 setWeight 只收 QFont.Weight 枚举，且刻度从 Qt5 的 0~99 改成
        # 100~900；Qt5 的 60 相当于 Qt6 的 DemiBold(600)。
        font.setWeight(QFont.DemiBold)
        collect.setFont(0,font)
        collect.setForeground(0,QColor(0,150,200))

        self.tree_widget.insertTopLevelItem(0,collect)
                

        for i in range(self.tree_widget.topLevelItemCount()):
            self.tree_widget.topLevelItem(i).setExpanded(True)
        
        self.tips_frame._check_box.setChecked(False)
        self.tips_frame._check_box.setEnabled(True)
        global_config.enable_show_rcd_panel_values(False)
        self._max_data_item_count = len(self.__rcd_data_bridge.head_names())
        count_str = str(self._max_data_item_count)

        self.tips_frame.set_tips(count_str +" of "+count_str)

    def get_child_item_name_for_show(self,src_name:str):
        if not global_config.show_rcd_helping_text_on_panel:
            return src_name
        tr_name = self.__translater.translate_title(src_name)
        if tr_name:
            return tr_name
        return src_name

    def on_filter_text_edited(self,context:str):
        """搜索功能实现"""
        if ""== context:
            
            for i in range(self.tree_widget.topLevelItemCount()):
                parentItem = self.tree_widget.topLevelItem(i)
                for i in range(parentItem.childCount()):
                    child  = parentItem.child(i)
                    if child.isHidden():
                        child.setHidden(False)

            for i in range(self.tree_widget.topLevelItemCount()):
                parentItem = self.tree_widget.topLevelItem(i)   
                parentItem.setHidden(False)

            count = 0
            for i in range(self.tree_widget.topLevelItemCount()):
                parentItem = self.tree_widget.topLevelItem(i)
                for i in range(parentItem.childCount()):
                    child  = parentItem.child(i)
                    if not child.isHidden():
                        count+=1
            self._max_data_item_count = count
            self.tips_frame.set_tips(str(count) +" of "+str(count))
            return
        for i in range(self.tree_widget.topLevelItemCount()):
            parentItem = self.tree_widget.topLevelItem(i)
            for i in range(parentItem.childCount()):
                child  = parentItem.child(i)
                search_items = []#包含headnames 和 tr names
                head_name = child.data(0, Qt.UserRole)
                tr_name = self.__translater.translate_title(head_name)
                
                search_items.extend([head_name,tr_name]) if tr_name else search_items.append(head_name)
                
                found = False
                for item_text in search_items:
                    if all(item in item_text for item in context.split()):
                        found = True
                        break
                child.setHidden(not found)
               

        
        for i in range(self.tree_widget.topLevelItemCount()):
            parentItem = self.tree_widget.topLevelItem(i)
            any_child_visible = False
            for i in range(parentItem.childCount()):
                child  = parentItem.child(i)
                if not child.isHidden():
                    any_child_visible =True
                    # parentItem.setHidden(not any_child_visible)
                    break
            parentItem.setHidden(not any_child_visible)
        
        count = 0
        for i in range(self.tree_widget.topLevelItemCount()):
            parentItem = self.tree_widget.topLevelItem(i)
            for i in range(parentItem.childCount()):
                child  = parentItem.child(i)
                if not child.isHidden():
                    count+=1
        self.tips_frame.set_tips(str(count)+" of "+str(self._max_data_item_count))

    def update_tree_item_name(self):
        if global_config.show_rcd_helping_text_on_panel:
            for i in range(self.tree_widget.topLevelItemCount()):
                parentItem = self.tree_widget.topLevelItem(i)
                for i in range(parentItem.childCount()):
                    child  = parentItem.child(i)
                    head_data = child.data(0, Qt.UserRole)
                    tr_data = self.__translater.translate_title(head_data)
                    if tr_data:
                        child.setText(0,tr_data)  
        else:
            for i in range(self.tree_widget.topLevelItemCount()):
                parentItem = self.tree_widget.topLevelItem(i)
                for i in range(parentItem.childCount()):
                    child  = parentItem.child(i)
                    head_data = child.data(0, Qt.UserRole)
                    child.setText(0,head_data) 
        


    def change_tree_expand_status(self):
        # all_Expanded = True
        any_Expanded = False  #任何一项展开，则收拢
        all_unExpanded = True
        for i in range(self.tree_widget.topLevelItemCount()):
            if  self.tree_widget.topLevelItem(i).isExpanded():
                any_Expanded = True
                
                break
        if not any_Expanded:
            for i in range(self.tree_widget.topLevelItemCount()):
                if self.tree_widget.topLevelItem(i).isExpanded():
                    all_unExpanded = False
                    break
        if  any_Expanded:
            for i in range(self.tree_widget.topLevelItemCount()):
                self.tree_widget.topLevelItem(i).setExpanded(False)
        elif all_unExpanded:
            for i in range(self.tree_widget.topLevelItemCount()):
                self.tree_widget.topLevelItem(i).setExpanded(True)

    def tree_mouse_press_event(self, event):
        """处理树形控件的鼠标按下事件"""
        if event.button() == Qt.LeftButton:
                # 创建拖拽图像（避免空pixmap）
            
            self.drag_start_position = event.pos()
        elif event.button() == Qt.RightButton:
            item = self.tree_widget.itemAt(event.pos())
           
            if not item or  not item.parent():
                # event.accept()  # 
                item =None
                self.setContextMenuPolicy(Qt.NoContextMenu)  # 完全禁用默认右键菜单
            else:
                self.setContextMenuPolicy(Qt.DefaultContextMenu)  # 
                if item.parent() == self.tree_widget.topLevelItem(0):
                    self._in_collect_area = True
                else:
                    self._in_collect_area = False
            self._selected_item =item
        super(QTreeWidget, self.tree_widget).mousePressEvent(event)
	
    def contextMenuEvent(self, event):
        """鼠标右键按下时（默认行为）：
            当用户按下并释放鼠标右键后，若未在 mousePressEvent 或 mouseReleaseEvent 中拦截事件，系统会自动触发 contextMenuEvent。
            显式请求上下文菜单时：
            通过代码调用 QWidget::customContextMenuRequested() 信号或 QMenu::exec() 手动触发。"""        
        menu = QMenu(self)
        # # 方法1：监听关闭信号
        # menu.aboutToHide.connect(self.on_menu_closed)
        if self._in_collect_area:
            action_del         = menu.addAction("删除")
            selected_action       = menu.exec(event.globalPos())
            if selected_action == action_del:
                item = self._selected_item
                parent = item.parent()
                parent.removeChild(item)

        else:
            action_collect         = menu.addAction("收藏")
            selected_action       = menu.exec(event.globalPos())
            if selected_action == action_collect:
                item = self._selected_item
                if not item:
                    print("item 没选择")
                    return
                head_name = item.data(0, Qt.UserRole)
                var  = item.text(1)
                collect_parent_item = self.tree_widget.topLevelItem(0)
                
                for i in range(collect_parent_item.childCount()):
                    child  = collect_parent_item.child(i)
                    if child.data(0, Qt.UserRole) == head_name:
                        return
                child =QTreeWidgetItem(self.tree_widget.topLevelItem(0))
                child.setData(0, Qt.UserRole, head_name)
                show_name  =  self.get_child_item_name_for_show(head_name)
                child.setText(0, show_name) 
                child.setText(1, var) 
	
    def tree_mouse_move_event(self, event):
        """处理树形控件的鼠标移动事件，实现拖拽"""
        if not (event.buttons() & Qt.LeftButton):
            return
            
        if self.drag_start_position is None:
            return
            
        # 检查是否移动了足够的距离才开始拖拽
        if (event.pos() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return

        # 获取当前选中的项目
        item = self.tree_widget.itemAt(self.drag_start_position)
        if not item or not item.parent():
            return  # 只允许拖拽子项目

        # 获取数据信息
        parent = item.parent()
        child_name = item.text(0)
        father_name = parent.text(0)
        head_data_name   =   item.data(0, Qt.UserRole)
        
        key =head_data_name
        
        
        drag = QDrag(self.tree_widget)
        pixmap =  text_to_pixmap_v1(item.text(0))
        # pixmap = self.getItemPixmap(self.item_selected)
            
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
           
            hotspot = QPoint(0 , 0)
            drag.setHotSpot(hotspot)
        else:
            
            return

        # 创建拖拽操作
        
        mime_data = QMimeData()
        
        # 设置MIME数据
        mime_data.setText(head_data_name)
        mime_data.setData("application/data-key", key.encode('utf-8'))
        
        drag.setMimeData(mime_data)
        # drag.setHotSpot(event.pos() - self.tree_widget.rect().topLeft())
        
        # 开始拖拽
        drag.exec(Qt.CopyAction)
		
    def get_xlim(self):
        return self.__rcd_data_bridge.xlim()
    
    def get_xdata(self):
        return self.__rcd_data_bridge.xdata_rcd()

    def on_item_clicked(self, item: QTreeWidgetItem):
        self.item_selected = item
        return 
    def on_item_DoubleClicked(self,item: QTreeWidgetItem):

        if item.childCount()==0:
            head_data_name   =   item.data(0, Qt.ItemDataRole.UserRole)

            self.data_name_clicked.emit(head_data_name)

    def apply_light_theme(self):
        """应用浅色主题样式表"""
        style = """
        /* ===== 浅色主题样式 ===== */
        QTreeWidget {
            background-color: #ffffff;
            border: 2px solid #e1e5e9;
            border-radius: 5px;
            font-family: "Segoe UI", "PingFang SC", sans-serif;
            font-size: 12px;
            color: #2c3e50;
        }
        
        QTreeWidget::item {
            height: 13px;
            border-bottom: 1px solid #f0f3f5;
            padding: 4px 4px;
        }
        
        QTreeWidget::item:first {
            border-top: none;
        }
        
        QTreeWidget::item:last {
            border-bottom: none;
        }
        
        /* ===== 选中状态 ===== */
        QTreeWidget::item:selected {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #f8f9fa, stop:1 #f8f9fa);
            color: green;
            border: 1px solid #3498db;
            border-radius: 2px;
        }
        
        /* ===== 悬停状态 ===== */
        QTreeWidget::item:hover {
            background-color: #f8f9fa;
            border-radius: 2px;
        }
        
        QTreeWidget::item:hover:!selected {
            background-color: #e9ecef;
        }
        
        /* ===== 交替行颜色 ===== */
        QTreeWidget::item:alternate {
            background-color: #fafbfc;
        }
        
        /* ===== 表头样式 ===== */
        QHeaderView::section {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #f8f9fa, stop:1 #e9ecef);
            color: #495057;
            padding: 10px 12px;
            border: 1px solid #dee2e6;
            font-weight: 600;
            font-size: 10px;
        }
		
		QHeaderView::section:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #e9ecef, stop:1 #dee2e6);
        }
        
        /* ===== 滚动条样式 ===== */
        QScrollBar:vertical {
            background-color: #f8f9fa;
            width: 10px;
            border-radius: 6px;
        }
        
        QScrollBar::handle:vertical {
            background-color: #adb5bd;
            border-radius: 6px;
            min-height: 30px;
        }
        
        QScrollBar::handle:vertical:hover {
            background-color: #6c757d;
        }
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        
        QTreeWidget::branch:hover {
            background-color: #e9ecef;
            border-radius: 3px;
        }
        """
        
        self.tree_widget.setStyleSheet(style)



class combo_panel(QFrame):
    """组合数据绘制管理面板"""
    @staticmethod
    def all_in_set(a,b):
        return set(a).issubset(set(b))
    

    # 定义拖拽信号
    data_dragged = Signal(str, object)  # 信号：数据名称，数据内容
    
    def __init__(self,dataBridge: rcd_data_bridge, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Box)
        self.setContentsMargins(5, 5, 5, 5)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(1)

        # self._json_file_path = "./cfg/combo_data.json"
        self._json_file_path = res_mng.get_data_path("combo_data.json")
        self._combo_map ={}
        self._selected_item =None
        # 添加简单的标签说明
        label = QLabel("组合绘制")
        label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(label)
        

        self.selected_data_item = None
        self.selected_data_name = None
        self.drag_start_position = None

        self.listWidget = QListWidget()
        
        # 启用拖拽功能
        self.listWidget.setDragEnabled(True)
        self.listWidget.viewport().setMouseTracking(True)
        self.listWidget.mousePressEvent = self.list_mouse_press_event
        self.listWidget.mouseMoveEvent = self.list_mouse_move_event
        # self.listWidget.itemClicked.connect(self.handle_item_click)
        main_layout.addWidget(self.listWidget)
        
       


        self.rcd_data_bridge = dataBridge

        self.new_datamap      = PlotDataMapRef()
      
        
        # 初始化列表显示
        self.update_list_widget()

        self.setLayout(main_layout)
	
    def list_mouse_press_event(self, event):
        """处理列表控件的鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.pos()
        elif event.button() == Qt.RightButton:
            item = self.listWidget.itemAt(event.pos())
            if not item:
                # event.accept()  # 
                self.setContextMenuPolicy(Qt.NoContextMenu)  # 完全禁用默认右键菜单
            else:
                self.setContextMenuPolicy(Qt.DefaultContextMenu)  # 
            self._selected_item =item
               
        super(QListWidget, self.listWidget).mousePressEvent(event)

    def contextMenuEvent(self, event):
        """鼠标右键按下时（默认行为）：
            当用户按下并释放鼠标右键后，若未在 mousePressEvent 或 mouseReleaseEvent 中拦截事件，系统会自动触发 contextMenuEvent。
            显式请求上下文菜单时：
            通过代码调用 QWidget::customContextMenuRequested() 信号或 QMenu::exec() 手动触发。"""        
        menu = QMenu(self)
        # # 方法1：监听关闭信号
        # menu.aboutToHide.connect(self.on_menu_closed)
        action_del         = menu.addAction("删除")
        selected_action       = menu.exec(event.globalPos())
        if selected_action == action_del:
           
            item = self._selected_item
            if not item:
                print("item 没选择")
                return
            try:
                del self._combo_map[item.text()]
            except KeyError as e:
                print(f"键不存在: {e}")

                # 写入 JSON 文件
            # json_path = get_json_path(self._json_file_path)
            json_path = self._json_file_path
            try:
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(self._combo_map, f, ensure_ascii=False, indent=4)
                
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")
                return
        self.update_list_widget()

    def list_mouse_move_event(self, event):
        """处理树形控件的鼠标移动事件，实现拖拽"""
        if not (event.buttons() & Qt.LeftButton):
            return
            
        if self.drag_start_position is None:
            return
            
        # 检查是否移动了足够的距离才开始拖拽
        if (event.pos() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return

        # 获取当前选中的项目
        item = self.listWidget.itemAt(self.drag_start_position)
       

        # 获取当前选中的项目
        item = self.listWidget.itemAt(self.drag_start_position)
        if not item:
            return
        
        combo_name = item.text()
        
        # data_heads     = self._combo_map[combo_name]
        
        combo_context_dic  = self._combo_map[combo_name]

        combo_context_lst = combo_context_dic.get("plot_info",None)
        if combo_context_lst is None:
            return
        data_heads = []
        for info in combo_context_lst:
            names = info.get("items",None)
            if names is None:
                return
            data_heads.extend(names)
        data_heads = list(set(data_heads))
        
        rcd_data_heads = self.rcd_data_bridge.head_names()
        if rcd_data_heads is None:
            return
			
        if not combo_panel.all_in_set(data_heads,rcd_data_heads):
            print("组合数据项不存在与rcd中")
            return

        
        drag = QDrag(self.listWidget)
        pixmap =  text_to_pixmap_v1(combo_name)
      
            
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
           
            hotspot = QPoint(0 , 0)
            drag.setHotSpot(hotspot)
        else:
            return

        # 创建拖拽操作
        
        mime_data = QMimeData()
        
        # 设置MIME数据
        mime_data.setText(combo_name)
        
        json_data = json.dumps(combo_context_dic)
        mime_data.setData("application/combo-datas", json_data.encode('utf-8'))

        drag.setMimeData(mime_data)
        # drag.setHotSpot(event.pos() - self.tree_widget.rect().topLeft())
        
        # 开始拖拽
        drag.exec(Qt.CopyAction)
	
    def update_list_widget(self):
        """更新列表控件显示脚本生成的新数据"""
        # 清空列表
        self.listWidget.clear()
        
        # json_path = get_json_path(self._json_file_path)
        json_path = self._json_file_path
        if not json_path:
            return
        
        # 读取现有数据
        
        try:
            with open(json_path, 'r', encoding='utf-8') as file:
                json_data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            # 如果文件不存在或格式错误，创建新的空字典
            json_data = {}
        # 获取所有数据键
        self._combo_map = json_data
        # all_data_keys = list(self.data_provider.datamap.data.keys())
        
        # 只显示脚本生成的新数据（不包含fatherX/dataX格式的数据）
        if self._combo_map:
            for key in self._combo_map.keys():
                # 过滤掉原始数据（fatherX/dataX格式），只显示自定义数据
                self.listWidget.addItem(key)

class custom_panel(QFrame):
    """基础导航面板，不包含新生成数据和脚本功能"""
    
    # 定义拖拽信号
    # data_dragged = Signal(str, object)  # 信号：数据名称，数据内容
    
    def __init__(self,dataBridge: rcd_data_bridge, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Box)
        self.setContentsMargins(5, 5, 5, 5)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(1)
        # 添加简单的标签说明
        label = QLabel("自定义数据")
        label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(label)
        
        self._dialog = None
        self.selected_data_item = None
        self.selected_data_name = None
        self.drag_start_position = None

        self.listWidget = QListWidget()
        
        # 启用拖拽功能
        self.listWidget.setDragEnabled(True)
        self.listWidget.viewport().setMouseTracking(True)
        self.listWidget.mousePressEvent = self.list_mouse_press_event
        self.listWidget.mouseMoveEvent = self.list_mouse_move_event
        
        main_layout.addWidget(self.listWidget)
        
        # 添加脚本转换按钮
        script_button_layout = QHBoxLayout()
        self.script_button = QPushButton("脚本转换数据")
        self.script_button.clicked.connect(self.open_script_dialog)
        script_button_layout.addWidget(self.script_button)
        main_layout.addLayout(script_button_layout)


        self.rcd_data_bridge = dataBridge

        self.new_datamap      = PlotDataMapRef()
        # 初始化数据转换器
        self.data_transformer = DataTransformer(self.rcd_data_bridge.datamap)
        

        self.setLayout(main_layout)

    def list_mouse_press_event(self, event):
        """处理列表控件的鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.pos()
        super(QListWidget, self.listWidget).mousePressEvent(event)

    def list_mouse_move_event(self, event):
        """处理列表控件的鼠标移动事件，实现拖拽"""
        if not (event.buttons() & Qt.LeftButton):
            return
            
        if self.drag_start_position is None:
            return
            
        # 检查是否移动了足够的距离才开始拖拽
        if (event.pos() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return

        # 获取当前选中的项目
        item = self.listWidget.itemAt(self.drag_start_position)
        if not item:
            return

        # 获取数据信息
        data_name = item.text()
        data_item = self.rcd_data_bridge.get_one_data_saved_in_bridge(data_name)
        
        if data_item is None:
            return

        drag = QDrag(self.listWidget)
        pixmap =  text_to_pixmap_v1(data_name)
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
           
            hotspot = QPoint(0 , 0)
            drag.setHotSpot(hotspot)
        else:
            return
        mime_data = QMimeData()
	
        mime_data.setText(data_name)
        mime_data.setData("application/data-usrkey", data_name.encode('utf-8'))
        
        drag.setMimeData(mime_data)
        drag.setHotSpot(event.pos() - self.listWidget.rect().topLeft())
        
        # 开始拖拽
        drag.exec(Qt.CopyAction)
        
        # 发射拖拽信号
        # self.data_dragged.emit(data_name, data_item)

    def open_script_dialog(self):
        """打开脚本输入对话框"""
        self._dialog = ScriptInputDialog(self.data_transformer, self)
        self._dialog.script_executed.connect(self.on_script_executed)
        self._dialog.exec()
    
    def on_script_executed(self, new_data_name):
        """处理脚本执行完成信号"""
        self.update_list_widget()
    
    def update_list_widget(self):
        """更新列表控件显示脚本生成的新数据"""
        # 清空列表
        self.listWidget.clear()
        # 只显示脚本生成的新数据（不包含fatherX/dataX格式的数据）
        for key in self._dialog.new_data_key():
            # 过滤掉原始数据（fatherX/dataX格式），只显示自定义数据
            self.listWidget.addItem(key)


        