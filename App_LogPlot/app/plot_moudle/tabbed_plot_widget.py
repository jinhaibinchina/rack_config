from __future__ import annotations
from PySide6.QtWidgets import (QApplication, QWidget, QTabWidget, QVBoxLayout, QSizePolicy,
                            QHBoxLayout, QPushButton, QMenu, QMessageBox, QDialog,QSpacerItem,
                            QInputDialog)
from PySide6.QtCore import Signal, Slot, Qt,QObject
# Qt6 起 QAction / QShortcut 在 QtGui 下（PyQt5 时代在 QtWidgets）
from PySide6.QtGui import QCloseEvent,QIcon,QContextMenuEvent,QKeySequence,QAction,QShortcut
from PySide6.QtXml import QDomDocument, QDomElement
from typing import Dict, Optional
from .polt_matrix import PlotMatrix
from .plotMatrixWithViceAxis import PlotMatrixWithVice
from .translater import rcd_translater
from .common import rcd_data_bridge
from .global_config import global_config,global_config


class scroll_manager(QObject):
    def __init__(self,btn_scroll,btn_scrollX,btn_scrollY,parent=None) -> None:
        super().__init__(parent)
        self._btn_scroll:QPushButton =  btn_scroll
        self._btn_scrollX:QPushButton =  btn_scrollX
        self._btn_scrollY:QPushButton =  btn_scrollY

        self._btn_scroll.clicked.connect(self.enable_full_scroll)
        self._btn_scrollX.clicked.connect(self.enable_scrollX)
        self._btn_scrollY.clicked.connect(self.enable_scrollY)

        global_config.scroll_mode_change.connect(self.on_scroll_mode_change)
        self.enable_scrollX()

    def enable_full_scroll(self):

        global_config.scroll_x_enable = True
        global_config.scroll_y_enable = True
        self._btn_scroll.setStyleSheet("background-color: green;")
        self._btn_scrollX.setStyleSheet("background-color: rgb(134,183,200);")
        self._btn_scrollY.setStyleSheet("background-color: rgb(134,183,200);")

    def enable_scrollX(self):

        global_config.scroll_x_enable = True
        global_config.scroll_y_enable = False
        self._btn_scroll.setStyleSheet("background-color: rgb(134,183,200);")
        self._btn_scrollX.setStyleSheet("background-color: green;")
        self._btn_scrollY.setStyleSheet("background-color: rgb(134,183,200);")

    def enable_scrollY(self):

        global_config.scroll_x_enable = False
        global_config.scroll_y_enable = True
        self._btn_scroll.setStyleSheet("background-color: rgb(134,183,200);")
        self._btn_scrollX.setStyleSheet("background-color: rgb(134,183,200);")
        self._btn_scrollY.setStyleSheet("background-color: green;")
    
    def on_scroll_mode_change(self):
        if global_config.scroll_x_enable and global_config.scroll_y_enable:
            self._btn_scroll.setStyleSheet("background-color: green;")
            self._btn_scrollX.setStyleSheet("background-color: rgb(134,183,200);")
            self._btn_scrollY.setStyleSheet("background-color: rgb(134,183,200);")
        elif global_config.scroll_x_enable:
            self._btn_scroll.setStyleSheet("background-color: rgb(134,183,200);")
            self._btn_scrollX.setStyleSheet("background-color: green;")
            self._btn_scrollY.setStyleSheet("background-color: rgb(134,183,200);")
        elif global_config.scroll_y_enable:
            self._btn_scroll.setStyleSheet("background-color: rgb(134,183,200);")
            self._btn_scrollX.setStyleSheet("background-color: rgb(134,183,200);")
            self._btn_scrollY.setStyleSheet("background-color: green;")

class ComboPoltDialog(QDialog):
    """脚本输入对话框"""
    MultiLabels_mode_change =Signal()
    def __init__(self,parent:Optional[TabbedPlotWidget]=None,plot_matrix:PlotMatrixWithVice=None):
        super().__init__(parent)
       

        self.setup_ui(plot_matrix)
        self.setWindowTitle("主副轴绘制")
        self.resize(1800, 1000)

    # def showEvent(self, event):
    #     """重写showEvent以确保对话框获得焦点"""
    #     super().showEvent(event)
    #     # 确保对话框获得焦点
    #     self.activateWindow()
    #     self.setFocus()

    def setup_ui(self,widget:PlotMatrixWithVice):
        """设置UI界面"""
        main_layout = QVBoxLayout()

        self.btn_major_en = QPushButton()
        self.btn_vice_en = QPushButton()
        self.btn_scroll = QPushButton()
        self.btn_scrollX= QPushButton()
        self.btn_scrollY= QPushButton()

        self.PlotMatrix = widget
        self.btn_zoom_max  = QPushButton()
       
        from .resource_manager import resource_manager as res_mng
       
        self.btn_major_en.setText("主")
        self.btn_vice_en.setText("副")
        self.btn_scroll.setIcon(     QIcon(res_mng.get_icon_path( "zoom_max.svg"    ) ))
        self.btn_scrollX.setIcon(     QIcon(res_mng.get_icon_path("zoom_horizontal.svg"  )))
        self.btn_scrollY.setIcon(     QIcon(res_mng.get_icon_path("zoom_vertical.svg")))
        self.btn_zoom_max.setIcon(     QIcon(res_mng.get_icon_path("ratio.svg")))

        self.btn_major_en.clicked.connect(self.on_btn_major_en_click)
        self.btn_vice_en.clicked.connect(self.on_btn_vice_en_click)
        self.btn_scroll.clicked.connect(self.on_btn_scroll_click)
        self.btn_scrollX.clicked.connect(self.on_btn_scrollX_click)
        self.btn_scrollY.clicked.connect(self.on_btn_scrollY_click)
        self.btn_zoom_max.clicked.connect(widget.on_Zoom_max)
        # 启用键盘焦点
        self.setFocusPolicy(Qt.StrongFocus)
        QShortcut(QKeySequence(Qt.Key.Key_D), self).activated.connect(self.move_time_line_forward_1_step)
        QShortcut(QKeySequence(Qt.Key.Key_A), self).activated.connect(self.move_time_line_backward_1_step)
        QShortcut(QKeySequence(Qt.Key.Key_P), self).activated.connect(self.ask_MultiLabels_mode_change)
        
        
      
        self.btn_scrollX.setToolTip("缩放X轴")
        self.btn_scrollY.setToolTip("缩放Y轴")
        self.btn_zoom_max.setToolTip("回到初始缩放比例,快捷键H")

        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(4)
        corner_widget.setMaximumHeight(28)
        
        # 添加控制按钮到右上角
        corner_layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        corner_layout.addWidget(self.btn_major_en)
        corner_layout.addWidget(self.btn_vice_en)
        corner_layout.addWidget(self.btn_scroll)
        corner_layout.addWidget(self.btn_scrollX)
        corner_layout.addWidget(self.btn_scrollY)
        corner_layout.addWidget(self.btn_zoom_max)

        self.btn_major_en.setStyleSheet("background-color: green;")
        self.btn_vice_en.setStyleSheet("background-color: green;")
        # 每次打开都从「主/副全开」开始，并让刚建好的合并窗口同步一次
        global_config.set_axis_visible(True, True)
        
        main_layout.addWidget(corner_widget)
        main_layout.addWidget(widget)
        self.setLayout(main_layout)
        self.on_btn_scrollX_click()
       
    def _sync_axis_visibility(self):
        """把按钮改过的全局开关广播给合并窗口，让曲线真正显隐。"""
        global_config.set_axis_visible(
            global_config.major_axis_en, global_config.vice_axis_en
        )

    def closeEvent(self, event):
        # 合并窗口随对话框一起销毁，这里只把全局开关复位，避免污染后续图表
        global_config.major_axis_en = True
        global_config.vice_axis_en = True
        return super().closeEvent(event)

    def on_btn_major_en_click(self):
        if global_config.major_axis_en and global_config.vice_axis_en:
            global_config.major_axis_en = False
            self.btn_major_en.setStyleSheet("background-color: rgb(134,183,200);")
        else:
            # 原来是 elif vice_axis_en：主轴关掉后走进死分支，点按钮毫无反应。
            # 两个按钮统一按「全开时关自己一根轴，否则恢复全开」处理。
            global_config.major_axis_en = True
            global_config.vice_axis_en  = True
            self.btn_major_en.setStyleSheet("background-color: green;")
            self.btn_vice_en.setStyleSheet("background-color: green;")
        self._sync_axis_visibility()
        

    def on_btn_vice_en_click(self):
        if global_config.major_axis_en and global_config.vice_axis_en:
            global_config.vice_axis_en = False
            self.btn_vice_en.setStyleSheet("background-color: rgb(134,183,200);")
        else:
            global_config.major_axis_en = True
            global_config.vice_axis_en  = True
            self.btn_major_en.setStyleSheet("background-color: green;")
            self.btn_vice_en.setStyleSheet("background-color: green;")
        self._sync_axis_visibility()

    def on_btn_scroll_click(self):
        global_config.change_scroll_mode(True,True)
        self.btn_scroll.setStyleSheet("background-color: green;")
        self.btn_scrollX.setStyleSheet("background-color: rgb(134,183,200);")
        self.btn_scrollY.setStyleSheet("background-color: rgb(134,183,200);")
    def on_btn_scrollX_click(self):
        global_config.change_scroll_mode(True,False)
        self.btn_scrollX.setStyleSheet("background-color: green;")
        self.btn_scroll.setStyleSheet("background-color: rgb(134,183,200);")
        self.btn_scrollY.setStyleSheet("background-color: rgb(134,183,200);")
    def on_btn_scrollY_click(self):
        global_config.change_scroll_mode(False,True)
        self.btn_scrollY.setStyleSheet("background-color: green;")
        self.btn_scroll.setStyleSheet("background-color: rgb(134,183,200);")
        self.btn_scrollX.setStyleSheet("background-color: rgb(134,183,200);")
    
    def move_time_line_forward_1_step(self):
        plot = self.PlotMatrix.plotAt(0,0)
        if not plot:
            return
        plot.move_forward_1_step()
    def move_time_line_backward_1_step(self):
        plot = self.PlotMatrix.plotAt(0,0)
        if not plot:
            return
        plot.move_backward_1_step()


    def clear_labels(self):
        plot = self.PlotMatrix.plotAt(0,0)
        if not plot:
            return
        plot.clear_labels()
    def ask_MultiLabels_mode_change(self):
        self.MultiLabels_mode_change.emit()
        self.clear_labels()

class TabManager(QObject):
    rename_current_tab_signal =Signal()
    combo_plot_signal         =Signal(int)
    def __init__(self, tab_widget,parent=None):
        super().__init__(parent)
        self.tab_widget:QTabWidget = tab_widget
        # 安装事件过滤器
        self.tab_widget.tabBar().installEventFilter(self)
    
    def eventFilter(self, obj, event):
        """事件过滤器"""
        if obj == self.tab_widget.tabBar() and event.type() == QContextMenuEvent.ContextMenu:
            # 处理右键菜单事件
            tab_index = self.tab_widget.tabBar().tabAt(event.pos())
            if self.tab_widget.currentIndex() != tab_index:
                return False
            self.show_tab_context_menu(event.globalPos())
            return True  # 事件已处理
        return False  # 事件继续传递
    

    def show_tab_context_menu(self, pos):
        """显示选项卡右键菜单"""
        menu = QMenu()
        
        rename_action = QAction("修改选项卡名称", self.tab_widget)
        rename_action.triggered.connect(lambda:self.rename_current_tab_signal.emit())

        combo_action_row0 = QAction("第一行双图合并", self.tab_widget)
        combo_action_row0.triggered.connect(lambda:self.combo_plot_signal.emit(1))
        combo_action_row1 = QAction("第二行双图合并", self.tab_widget)
        combo_action_row1.triggered.connect(lambda:self.combo_plot_signal.emit(2))
        combo_action_col0 = QAction("第一列双图合并", self.tab_widget)
        combo_action_col0.triggered.connect(lambda:self.combo_plot_signal.emit(3))
        combo_action_col1 = QAction("第二列双图合并", self.tab_widget)
        combo_action_col1.triggered.connect(lambda:self.combo_plot_signal.emit(4))
        
        menu.addAction(rename_action)
        menu.addAction(combo_action_row0)
        menu.addAction(combo_action_row1)
        menu.addAction(combo_action_col0)
        menu.addAction(combo_action_col1)
       
     
        menu.exec(pos)
    
    

# 主窗口类
class TabbedPlotWidget(QWidget):
    # 静态实例映射
    _instances: Dict[str, 'TabbedPlotWidget'] = {}
    
    # 信号定义
    created = Signal()
    undoableChangeHappened = Signal()
    matrixAdded = Signal(object)
    sendTabToNewWindow = Signal(object)
    tabWidget_currentChanged = Signal()  #用于关闭播放器

    ask_MultiLabels_mode_change = Signal()
    class LabelStatus:
        LEFT = 0
        RIGHT = 1
        HIDDEN = 2

    def __init__(self, name: str,  first_tab: PlotMatrix, 
                 data_bridge: rcd_data_bridge,rcd_translater:rcd_translater, parent: QWidget):
        super().__init__(parent)
        self._name = name
       
        self._rcd_data_bridge = data_bridge
        self._rcd_translater = rcd_translater
        self._horizontal_link = False
        # self._parent_type = ""
        self._labels_status = self.LabelStatus.HIDDEN

        # self.plot_window_ref = parent  #
        
        # 启用鼠标跟踪
        self.setMouseTracking(True)
        
        # 创建标签页控件
        self.tab_widget = QTabWidget()
        # self.tab_widget =CustomTabWidget()
        self.tab_manager = TabManager(self.tab_widget,self)
        self.tab_manager.rename_current_tab_signal.connect(self.on_renameCurrentTab)
        self.tab_manager.combo_plot_signal.connect(self.open_ComboPolt_dialog)
        self.tab_widget.setTabsClosable(True)
        

        # 动作和菜单初始化
        self._action_renameTab = QAction("重命名标签", self)
        self._action_savePlots = QAction("保存图表", self)
        self._tab_menu = QMenu(self)
        
        # 创建控制按钮并添加到选项卡栏右侧
        self._createControlButtons()
        
        # 创建右上角按钮容器
        self.corner_widget = QWidget()
        corner_layout = QHBoxLayout(self.corner_widget)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(4)
        
        # 添加控制按钮到右上角
        corner_layout.addWidget(self.btn_scroll)
        corner_layout.addWidget(self.btn_scrollX)
        corner_layout.addWidget(self.btn_scrollY)
        corner_layout.addWidget(self.btn_add_ruler)
        corner_layout.addWidget(self.btn_link)
        corner_layout.addWidget(self.btn_add_row)
        corner_layout.addWidget(self.btn_add_col)
        corner_layout.addWidget(self.btn_add_tab)
        corner_layout.addWidget(self.btn_zoom_max)
        corner_layout.addWidget(self.btn_clear)
        
        # 将按钮容器设置为选项卡栏的右上角部件
        self.tab_widget.setCornerWidget(self.corner_widget, Qt.TopRightCorner)

        self._scroll_manager =scroll_manager(self.btn_scroll,self.btn_scrollX,self.btn_scrollY)

        # 设置主布局
        layout = QVBoxLayout()
        layout.addWidget(self.tab_widget)
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
       
        
        # 添加初始标签页
        if first_tab:
            self.addTab(first_tab)
        else:
            self.addTab()
        
        # 连接信号槽
        self._setup_connections()
        
        # 注册实例
        TabbedPlotWidget._instances[name] = self
        
        
        self.created.emit()


    @Slot(int)
    def open_ComboPolt_dialog(self,plot_num):
        """把当前选项卡里相邻的两幅图合并成一个主副轴窗口。

        plot_num: 1/2 = 第一/第二行双图，3/4 = 第一/第二列双图。
        元组里前一个位置画主轴，后一个位置画右侧副轴。
        """
        locations = {
            1: ((0, 0), (0, 1)),
            2: ((1, 0), (1, 1)),
            3: ((0, 0), (1, 0)),
            4: ((0, 1), (1, 1)),
        }.get(plot_num)
        if locations is None:
            return

        current_tab = self.currentTab()
        if current_tab is None:
            return
        major_plot = current_tab.plotAt(*locations[0])
        vice_plot = current_tab.plotAt(*locations[1])
        if not major_plot or not vice_plot:
            return

        matrix = PlotMatrixWithVice("图表1", self._rcd_data_bridge,self._rcd_translater)
        if self._rcd_data_bridge.keys():
            matrix.set_xaxis_labels_by_format()
        plot = matrix.plotAt(0,0)
        # 空图（data_head_names_lst 返回 None）不再让整个对话框崩掉
        major_keys = major_plot.data_head_names_lst() or []
        vice_keys = vice_plot.data_head_names_lst() or []
        if major_keys:
            plot._plot_by_data_keys(major_keys)
        if vice_keys:
            plot._plot_by_data_keys(vice_keys, True)

        dialog = ComboPoltDialog(self,matrix)
        dialog.MultiLabels_mode_change.connect(lambda:self.ask_MultiLabels_mode_change.emit())
        # dialog.script_executed.connect(self.on_script_executed)
        dialog.exec()

    def _createControlButtons(self):
        """创建控制按钮"""
        # 行列操作按钮
        self.btn_scroll = QPushButton()
        self.btn_scrollX= QPushButton()
        self.btn_scrollY= QPushButton()

        self.btn_add_ruler = QPushButton()
        self.btn_link      = QPushButton()
        self.btn_add_row   = QPushButton()
        self.btn_add_col   = QPushButton()
        self.btn_add_tab   = QPushButton()
        self.btn_zoom_max  = QPushButton()
        self.btn_clear = QPushButton()
        from .resource_manager import resource_manager as res_mng

        self.btn_scroll.setIcon(     QIcon(res_mng.get_icon_path( "zoom_max.svg"    ) ))
        # self.btn_scrollX.setIcon(     QIcon(res_mng.get_icon_path("x_scroll_en.png"  )))
        # self.btn_scrollY.setIcon(     QIcon(res_mng.get_icon_path("ax_scroll_en.png")))
        self.btn_scrollX.setIcon(     QIcon(res_mng.get_icon_path("zoom_horizontal.svg"  )))
        self.btn_scrollY.setIcon(     QIcon(res_mng.get_icon_path("zoom_vertical.svg")))


        self.btn_add_ruler.setIcon(     QIcon(res_mng.get_icon_path("ruler.png")))
        self.btn_link.setIcon(     QIcon(res_mng.get_icon_path("link.png")))
        self.btn_add_row.setIcon(     QIcon(res_mng.get_icon_path("add_row.svg")))
        self.btn_add_col.setIcon(     QIcon(res_mng.get_icon_path("add_column.svg")))
        self.btn_add_tab.setIcon(     QIcon(res_mng.get_icon_path("add_tab.svg")))
        self.btn_zoom_max.setIcon(     QIcon(res_mng.get_icon_path("ratio.svg")))
        self.btn_clear.setIcon(     QIcon(res_mng.get_icon_path("remove.svg")))


        self.btn_link.setToolTip("多图模式下同步时间轴")
        self.btn_scrollX.setToolTip("缩放X轴")
        self.btn_scrollY.setToolTip("缩放Y轴")
        self.btn_zoom_max.setToolTip("回到初始缩放比例,快捷键H")
        self.btn_clear.setToolTip("清空当前页的图表")
        self.btn_add_ruler.setToolTip("测量工具，快捷键M")
        self.on_btn_link_click()


    def _setup_connections(self):
        """初始化信号槽连接"""
        self.tab_widget.currentChanged.connect(self.on_tabWidget_currentChanged)
        self.tab_widget.tabCloseRequested.connect(self.on_tabWidget_tabCloseRequested)
        
        self.btn_add_row.clicked.connect(self.on_pushAddRow_pressed)
        self.btn_add_col.clicked.connect(self.on_pushAddColumn_pressed)
        self.btn_add_tab.clicked.connect(self.on_addTabButton_pressed)
        self.btn_zoom_max.clicked.connect(self.on_pushButtonZoomMax_pressed)
        self.btn_add_ruler.clicked.connect(self.on_btn_add_ruler_click)
        self.btn_link.clicked.connect(self.on_btn_link_click)
        # self.btn_clear.clicked.connect(self.on_clearPlots)
        global_config.measure_ruler_done.connect(self.on_btn_add_ruler_click)


        QShortcut(QKeySequence(Qt.Key.Key_M), self).activated.connect(self.on_btn_add_ruler_click)


    def on_btn_add_ruler_click(self):
        # return
        if not global_config.measure_ruler_mode:
            global_config.measure_ruler_en(True)
            self.btn_add_ruler.setStyleSheet("background-color: green;")
        else:
            global_config.measure_ruler_en(False)
            self.btn_add_ruler.setStyleSheet("background-color: rgb(134,183,200);")

    def on_btn_link_click(self):
        
        if not global_config.sync_x_axis:
            global_config.sync_x_axis_en(True)
            self.btn_link.setStyleSheet("background-color: green;")
        else:
            global_config.sync_x_axis_en(False)
            self.btn_link.setStyleSheet("background-color: rgb(134,183,200);")
        
    
    def currentTab(self) -> Optional[PlotMatrix]:
        """获取当前标签页"""
        current_widget = self.tab_widget.currentWidget()
        return current_widget if isinstance(current_widget, PlotMatrix) else None
    
    def allTab(self) -> Optional[PlotMatrix]:
        
        PlotMatrix_list = []
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            PlotMatrix_list.append(widget)
        return PlotMatrix_list


    def tabWidget(self) -> QTabWidget:
        return self.tab_widget

    def addTab(self, tab: Optional[PlotMatrix] = None):
        """添加新标签页"""
        if tab is None:
            tab_name = f"图表 {self.tab_widget.count() + 1}"
            tab = PlotMatrix(tab_name, self._rcd_data_bridge,self._rcd_translater)
        
        index = self.tab_widget.addTab(tab, tab.name())
        self.tab_widget.setCurrentIndex(index)
        self.matrixAdded.emit(tab)

       

    def xmlSaveState(self, doc: QDomDocument) -> QDomElement:
        """XML保存状态"""
        element = doc.createElement("TabbedPlotWidget")
        element.setAttribute("name", self._name)
        element.setAttribute("tab_count", str(self.tab_widget.count()))
        return element

    def xmlLoadState(self, tabbed_area: QDomElement) -> bool:
        """XML加载状态"""
        try:
            name = tabbed_area.attribute("name", self._name)
            self._name = name
            return True
        except:
            return False

    def name(self) -> str:
        return self._name


    @classmethod
    def instances(cls) -> Dict[str, 'TabbedPlotWidget']:
        return cls._instances.copy()

    @classmethod
    def instance(cls, key: str) -> Optional['TabbedPlotWidget']:
        return cls._instances.get(key)

    def setControlsVisible(self, visible: bool):
        """设置控件可见性"""
        self.corner_widget.setVisible(visible)

    @Slot(bool)
    def setStreamingMode(self, streaming_mode: bool):
        """设置流模式"""
        pass

    @staticmethod
    def saveTabImage(fileName: str, matrix: PlotMatrix):
        """保存标签页图像"""
        pass

    @Slot(str)
    def on_stylesheetChanged(self, style_dir: str):
        """样式表改变"""
        pass

    @Slot()
    def on_renameCurrentTab(self):
        """重命名当前标签页"""
        current_index = self.tab_widget.currentIndex()
        if current_index >= 0:
            new_name, ok = QInputDialog.getText(self, "重命名标签", "输入新名称:", 
                                              text=self.tab_widget.tabText(current_index))
            if ok and new_name:
                self.tab_widget.setTabText(current_index, new_name)


    @Slot()
    def on_savePlotsToFile(self):
        """保存图表到文件"""
        QMessageBox.information(self, "保存图表", "保存图表功能")

    @Slot()
    def on_pushAddColumn_pressed(self):
        """添加列"""
        current_tab = self.currentTab()
        if current_tab:
            current_tab.addColumn()
            self.undoableChangeHappened.emit()

          

    @Slot()
    def on_pushAddRow_pressed(self):
        """添加行"""
        current_tab = self.currentTab()
        if current_tab:
            current_tab.addRow()
            self.undoableChangeHappened.emit()

          

    @Slot()
    def on_addTabButton_pressed(self):
        """添加标签页"""
        self.addTab()
        self.undoableChangeHappened.emit()

    @Slot()
    def on_pushButtonZoomMax_pressed(self):
        """最大化缩放"""
        current_tab = self.currentTab()
        if current_tab:
            # 这里可以添加具体的缩放逻辑
           
            for row in range(current_tab.rowsCount()):
                for col in range(current_tab.colsCount()):
                    plot_widget = current_tab.plotAt(row, col)
                    if plot_widget:
                        plot_widget.restore_initial_lim()
            # QMessageBox.information(self, "缩放", "最大化缩放功能")

    @Slot()
    def on_translate_change(self):
        """最大化缩放"""
        current_tab = self.currentTab()
        if current_tab:
            # 这里可以添加具体的缩放逻辑
           
            for row in range(current_tab.rowsCount()):
                for col in range(current_tab.colsCount()):
                    plot_widget = current_tab.plotAt(row, col)
                    if plot_widget:
                        plot_widget.update_legend_texts_colors()


    @Slot()
    def on_clearPlots(self):
        """清除当前tab所有图表"""
        current_tab = self.currentTab()
        

        if current_tab:
            is_already_add_line = False
            for row in range(current_tab.rowsCount()):
                for col in range(current_tab.colsCount()):
                    plot_widget = current_tab.plotAt(row, col)
                    if plot_widget.is_already_add_line():
                        is_already_add_line =True
                        break
            

            if is_already_add_line:            
                current_tab.clear_all()
            else:
                self.removeRowsCols()
            self.undoableChangeHappened.emit()
    
    @Slot()
    def on_clearPlots_all(self): 
        for tab in self.allTab():
            tab.clear_all()


    def removeRowsCols(self):
        """移除行列，恢复为1x1布局"""
        current_tab = self.currentTab()
        if current_tab:
            # 保存当前标签页的名称
            tab_name = current_tab.name()
            
            # 获取当前标签页的索引
            current_index = self.tab_widget.currentIndex()
            
            # 创建新的1x1 PlotMatrix
            new_tab = PlotMatrix(tab_name, self._rcd_data_bridge,self._rcd_translater)
            
            # 替换当前标签页
            self.tab_widget.removeTab(current_index)
            self.tab_widget.insertTab(current_index, new_tab, tab_name)
            self.tab_widget.setCurrentIndex(current_index)
            
            self.undoableChangeHappened.emit()

   

    @Slot(int)
    def on_tabWidget_currentChanged(self, index: int):
        """标签页切换"""
        self.tabWidget_currentChanged.emit()

    @Slot(int)
    def on_tabWidget_tabCloseRequested(self, index: int):
        """关闭标签页请求"""
        if self.tab_widget.count() > 1:
            self.tab_widget.removeTab(index)
        else:
            # QMessageBox.warning(self, "警告", "至少保留一个标签页")
            self.removeRowsCols()


    def closeEvent(self, event: QCloseEvent):
        """关闭事件"""
        if self._name in TabbedPlotWidget._instances:
            del TabbedPlotWidget._instances[self._name]
        super().closeEvent(event)
    
    
    @Slot()
    def on_xdata_format_change(self):
        self.set_xaxis_labels_by_format()
    @Slot()
    def on_show_grid_change(self):
        self.set_if_show_grid()
    @Slot()
    def on_delete_data(self):
        self.delete_lines()
    @Slot()
    def on_delete_hidden_lines(self):
        self.delete_hidden_lines()

    def delete_lines(self, row=None, col=None):
        current_tab = self.currentTab()
        if current_tab:
            current_tab.delete_lines(row, col)

    def delete_hidden_lines(self):
        current_tab = self.currentTab()
        if current_tab:
            current_tab.del_hidden_lines()

    def check_operating_current_tab(self)->bool:
        
        current_tab = self.currentTab()
        return current_tab.is_plot_window_operating()

    def set_xaxis_labels_by_format(self, row=None, col=None):
        """设置当前标签页的自定义X轴标签
        
        Args:
            labels: 标签列表，可以是字符串列表
            positions: 标签位置列表（可选），如果不提供则使用默认位置
            row: 指定行索引（可选），如果不提供则应用到所有行
            col: 指定列索引（可选），如果不提供则应用到所有列
        """
        
        for tab in self.allTab():
            tab.set_xaxis_labels_by_format( row, col)
        
    def clear_labels(self):
        for tab in self.allTab():
            tab.clear_tip_labels()
    
    def set_xaxis_label_rotation(self, rotation=0, row=None, col=None):
        """设置当前标签页的X轴标签旋转角度
        
        Args:
            rotation: 旋转角度（度）
            row: 指定行索引（可选），如果不提供则应用到所有行
            col: 指定列索引（可选），如果不提供则应用到所有列
        """
        for tab in self.allTab():
            tab.set_xaxis_label_rotation(rotation, row, col)

    
    def set_if_show_grid(self):
        for tab in self.allTab():
            tab.set_if_show_grid()


    @Slot(dict)
    def handle_double_click_from_combo_panel(self,combo_context_dict):
        current_tab = self.currentTab()
        if not current_tab._is_only_one_plot_window() or current_tab._is_only_one_plot_window() and current_tab.first_plot_widget().is_already_add_line():
            self.addTab()
            current_tab = self.currentTab()
        # print(combo_context_dict)

        current_tab.handle_double_click_from_combo_panel(combo_context_dict)
    

    @Slot(str)
    def handle_double_click_from_rcd_panel(self,data_name:str):

        current_tab = self.currentTab()
        current_tab.handle_double_click_from_rcd_panel(data_name)