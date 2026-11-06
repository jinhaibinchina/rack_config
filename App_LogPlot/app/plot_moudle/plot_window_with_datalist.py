import matplotlib
matplotlib.use('QtAgg')  # 在导入pyplot之前设置后端（Qt6 用 QtAgg，PySide6/PyQt6 通吃）

import matplotlib.pyplot as plt
import warnings
import matplotlib.style as mplstyle


mplstyle.use('fast')
# 忽略特定警告
warnings.filterwarnings("ignore", category=UserWarning, message="set_ticklabels.*")
warnings.filterwarnings("ignore", category=UserWarning, message=".*stylesheet.*")
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*libpng.*")
warnings.filterwarnings("ignore", category=UserWarning, module="PIL")
# 设置 matplotlib 支持中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']  # 支持中文的字体
plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号
# 设置刻度标签大小

# 全局设置字体大小
plt.rcParams.update({
    'font.size': 12,                    # 全局字体大小
    'axes.labelsize': 8,               # 坐标轴标签字体大小
    'xtick.labelsize': 8,              # x轴刻度标签字体大小
    'ytick.labelsize': 8,              # y轴刻度标签字体大小
    'legend.fontsize': 8,              # 图例字体大小
    'figure.titlesize': 10              # 图表标题字体大小
})
plt.tight_layout()


print("初始化配置matplotlib")
print(f"当前后端: {matplotlib.get_backend()}")
print(f"是否交互模式: {matplotlib.is_interactive()}")




import numpy as np
from PySide6.QtWidgets import  QMessageBox,QSlider,QLineEdit
                        
from PySide6.QtCore import Signal, Slot, Qt,QEvent,QObject, QPoint, Property,QTimer,QVariantAnimation
# Qt6 起 QShortcut 在 QtGui 下（PyQt5 时代在 QtWidgets）
from PySide6.QtGui import QKeySequence,QIcon,QCursor,QKeyEvent,QPalette,QColor,QShortcut

from .translater import rcd_translater
from .rcd_tr import RcdTr_for_polt_moudle
import time

from .data_map_panel import custom_panel, rcd_panel,combo_panel
from .load_ui import LoadWidget
from .polt_matrix import PlotMatrix
# from data_map_panel import PlotDataMapRef
from enum import Enum
from .tabbed_plot_widget import TabbedPlotWidget
from .common import xLabelFormat,datetime_from_timestamp,string_to_datetime
from .global_config import global_config,PlaySpeed
from .common import rcd_data_bridge,time_it
from .combo_plot_dialog import ComboPoltDataDialog
from .resource_manager import resource_manager as res_mng
from .work_thread import playerWorkerThread ,ThreadManager
from .logic_search_dialog import LogicScriptInputDialog
from .logical_data_generator import LogicalDataGenerator


class SliderEventFilter(QObject):
    """事件过滤器类（必须继承QObject）"""
    def __init__(self):
        super().__init__()
        self.is_user_interaction = False
    
    def eventFilter(self, obj, event):
        if isinstance(obj, QSlider):
            event_type = event.type()
            
            # 用户交互开始
            if event_type in [QEvent.MouseButtonPress, QEvent.KeyPress]:
                self.is_user_interaction = True
                print("检测到用户开始操作滑块")
            
            # 用户交互结束
            elif event_type in [QEvent.MouseButtonRelease, QEvent.KeyRelease]:
                self.is_user_interaction = False
                print("检测到用户结束操作滑块")
        
        # 返回False表示继续正常的事件处理
        return False

class SplitterAnimator(QObject):
    """QSplitter 动画包装器 - 使用QTimer实现"""
    
    def __init__(self, splitter, parent=None):
        super().__init__(parent)
        self.splitter = splitter
        self.timer = QTimer()
        self.timer.timeout.connect(self.animate_step)
        self.duration = 400
        self.step_interval = 16  # ~60fps
        self.current_step = 0
        self.total_steps = 0
        self.start_sizes = []
        self.target_sizes = []
    
    def animate_to(self, target_sizes):
        """动画到目标大小"""
        self.start_sizes = self.splitter.sizes()
        self.target_sizes = target_sizes
        self.current_step = 0
        self.total_steps = self.duration // self.step_interval
        
        if self.total_steps > 0:
            self.timer.start(self.step_interval)
    
    def animate_step(self):
        """动画步骤"""
        if self.current_step >= self.total_steps:
            self.timer.stop()
            self.splitter.setSizes(self.target_sizes)
            return
    
        # 使用缓动函数使动画更平滑
        progress = self.current_step / self.total_steps
      
        eased_progress = 1 - (1 - progress) ** 3
        
        current_sizes = []
        for i in range(len(self.start_sizes)):
            start_val = self.start_sizes[i]
            target_val = self.target_sizes[i]
            current_val = start_val + (target_val - start_val) * eased_progress
            current_sizes.append(int(current_val))
        
        self.splitter.setSizes(current_sizes)
        self.current_step += 1

class plot_window(LoadWidget):
    """多功能绘图窗口"""
    xLabelFormatChange = Signal()
    grid_show_change   = Signal()
    translate_mode_change = Signal()
    off_row_data_read    = Signal()
    on_off_row_data_read    = Signal(bool)

    class xLabelFormat(Enum):
        DT = 0
        SEC = 1
    
    @staticmethod
    def initial_matlibplot():
        # import matplotlib
        # matplotlib.use('QtAgg')  # 在导入pyplot之前设置后端
        import matplotlib.pyplot as plt
        import warnings
        import matplotlib.style as mplstyle

        mplstyle.use('fast')
        # 忽略特定警告
        warnings.filterwarnings("ignore", category=UserWarning, message="set_ticklabels.*")
        warnings.filterwarnings("ignore", category=UserWarning, message=".*stylesheet.*")
        warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*libpng.*")
        warnings.filterwarnings("ignore", category=UserWarning, module="PIL")
        # 设置 matplotlib 支持中文字体
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']  # 支持中文的字体
        plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号
        # 设置刻度标签大小
       
        # 全局设置字体大小
        plt.rcParams.update({
            'font.size': 12,                    # 全局字体大小
            'axes.labelsize': 8,               # 坐标轴标签字体大小
            'xtick.labelsize': 8,              # x轴刻度标签字体大小
            'ytick.labelsize': 8,              # y轴刻度标签字体大小
            'legend.fontsize': 8,              # 图例字体大小
            'figure.titlesize': 10              # 图表标题字体大小
        })
        plt.tight_layout()


    def showEvent(self, event):
        """窗口显示事件"""
        super().showEvent(event)
        
        if not self.initialized:
            self.initialize_after_show()
            self.initialized = True
    
    def initialize_after_show(self):
        """显示后初始化"""
        target_sizes = [400, self.ui.splitter.width() - 400]
        self.splitter.setSizes(target_sizes)

        self.animation = SplitterAnimator(self.ui.splitter)
        self.is_left_hidden = False
        self.hover_timer = QTimer()
        self.hover_timer.timeout.connect(self.check_hover)
        self.hover_timer.start(100)

    def __init__(self,dataBridge:rcd_data_bridge,translater=None, qss_file=None):

        

        # script_dir = os.path.dirname(os.path.abspath(__file__))
        # ui_file_path = os.path.join(script_dir, 'ui', 'rcd_plot.ui')


        ui_file_path = res_mng.get_ui_path('rcd_plot.ui')
        qss_file     = res_mng.get_ui_path('rcd.qss')
        super().__init__(ui_file_path, qss_file)

        self.setContentsMargins(0, 0, 0, 0)
        self.initialized =False
        

        self.logic_search_result = None


        self._translater_inter = RcdTr_for_polt_moudle(translater)

        if translater:
            self.__translater = self._translater_inter
        else:
            self.__translater = rcd_translater()

        # self.data_provider = data_provider() 
        self.rcd_data_bridge =  dataBridge

        self.rcd_data_panel    = rcd_panel(self.rcd_data_bridge,self.__translater,self.ui.leftFrame)
        self.custom_data_panel = custom_panel(self.rcd_data_bridge,self.ui.leftFrame)
        self.combo_data_panel = combo_panel(self.rcd_data_bridge,self.ui.leftFrame)
        self.translate_mode_change.connect(self.rcd_data_panel.update_tree_item_name)
        
        self.rcd_data_panel.hide_btn.clicked.connect(self.hide_left_panel)
        self.rcd_data_panel.tips_frame.ValueShowSignalChange.connect(global_config.enable_show_rcd_panel_values)

        self.ui.leftLayout.insertWidget(0, self.rcd_data_panel, 7)
        self.ui.leftLayout.insertWidget(1, self.combo_data_panel, 2)
        self.ui.leftLayout.insertWidget(2, self.custom_data_panel, 1)
        self.rcd_data_panel.setMinimumWidth(200)
        self.combo_data_panel.setMinimumHeight(200)
        self.custom_data_panel.setMinimumHeight(100)
        
        # 创建初始的PlotMatrix
        initial_tab = PlotMatrix("图表1", self.rcd_data_bridge,self.__translater)
        
        # 创建TabbedPlotWidget
        self.tabbed_widget = TabbedPlotWidget("plotWindow", initial_tab, self.rcd_data_bridge,self.__translater, self)
        self.translate_mode_change.connect(self.tabbed_widget.on_translate_change)
        self.xLabelFormatChange.connect(self.tabbed_widget.on_xdata_format_change)
        self.xLabelFormatChange.connect(self.handle_displayTime_text)
        self.grid_show_change.connect(self.tabbed_widget.on_show_grid_change)


        self.tabbed_widget.btn_clear.clicked.connect(self.on_tab_window_clear)
        self.tabbed_widget.btn_clear.clicked.connect(self.tabbed_widget.on_clearPlots)

        self.tabbed_widget.tabWidget_currentChanged.connect(self.on_tab_window_clear)
        self.tabbed_widget.tabWidget_currentChanged.connect(self.clear_logic_search_result)
        self.tabbed_widget.ask_MultiLabels_mode_change.connect(self.handle_pushButtonMultiLabels_click)

        self.rcd_data_panel.data_name_clicked.connect(self.tabbed_widget.handle_double_click_from_rcd_panel)

        self.rcd_data_bridge.add_observer(self.tabbed_widget.on_clearPlots_all)
       
        self.xData_format = xLabelFormat.DT
        
        self.thread_manager = ThreadManager(self)
        
        layout = self.ui.plottingArea.layout()
       
        #条件搜索相关
        self.data_transformer = LogicalDataGenerator(self.rcd_data_bridge.datamap)
     
        layout.addWidget(self.tabbed_widget)

        self.ui.plottingLayout.insertWidget(0, self.tabbed_widget, 1)
      

        self.ui.splitter.setCollapsible(0, True)  # 索引0（左半边）可折叠

        self.ui.widgetOptions.hide()
        self.ui.pushButtonOptions.clicked.connect(self.handle_pushButtonOptions_click)
        # 当前随包发布的 ui/rcd_plot.ui 里没有 pushButtonMultiLabels 这个按钮
        # （本地 .ui 与代码不同步）。有按钮就接上，没有就只保留 P 快捷键，
        # 其余功能不受影响。
        btn_multilabels = getattr(self.ui, "pushButtonMultiLabels", None)
        if btn_multilabels is not None:
            btn_multilabels.clicked.connect(self.handle_pushButtonMultiLabels_click)
        QShortcut(QKeySequence(Qt.Key.Key_P), self).activated.connect(self.handle_pushButtonMultiLabels_click)
        self.ui.pushButtonRatio.clicked.connect(self.handle_pushButtonRatio_click)
        QShortcut(QKeySequence(Qt.Key.Key_H), self).activated.connect(self.handle_pushButtonRatio_click)
        self.ui.pushButtonUseDateTime.clicked.connect(self.pushButtonUseDateTime_click)
        QShortcut(QKeySequence(Qt.Key.Key_T), self).activated.connect(self.pushButtonUseDateTime_click)
        
     

        self.ui.pushButtonActivateGrid.clicked.connect(self.handle_pushButtonActivateGrid_click)
        QShortcut(QKeySequence(Qt.Key.Key_G), self).activated.connect(self.handle_pushButtonActivateGrid_click)

        self.ui.pushButtonComboPlot.clicked.connect(self.handle_pushButtonComboPlot_click)
        self.ui.pushButtonTranslate.clicked.connect(self.handle_translate_change)
        self.ui.pushButtonTimeTracker.clicked.connect(self.start_task_player)
        self.ui.pushButtonTimeTrackerSpeed.clicked.connect(self.play_speed_switch)
        QShortcut(QKeySequence(Qt.Key.Key_S), self).activated.connect(self.play_speed_switch)

        global_config.play_mode_change.connect(self.on_play_mode_change)
        global_config.translate_mode_change.connect(self.on_translate_mode_change)
        self.ui.pushButtonBackward_1_step.clicked.connect(self.move_time_line_backward_1_step)
        QShortcut(QKeySequence(Qt.Key.Key_A), self).activated.connect(self.move_time_line_backward_1_step)
        self.ui.pushButtonForward_1_step.clicked.connect(self.move_time_line_forward_1_step)
        QShortcut(QKeySequence(Qt.Key.Key_D), self).activated.connect(self.move_time_line_forward_1_step)
        self.ui.pushButtonLogicSearch.clicked.connect(self.open_script_dialog)
        self.ui.pushButtonToFindPos.clicked.connect(self.handle_pushButtonToFindPos_click)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self).activated.connect(self.handle_pushButtonToFindPos_click)

        self.ui.playbackStep.valueChanged.connect(self.set_player_fps)

        QShortcut(QKeySequence(Qt.Key.Key_Delete),self).activated.connect(self.handle_delete_lines)
        # res_mng.get_icon_path("settings_cog.svg")
        self.ui.pushButtonOptions.setIcon(     QIcon(res_mng.get_icon_path("settings_cog.svg")))
        self.ui.pushButtonUseDateTime.setIcon( QIcon(res_mng.get_icon_path("datetime.png")))
        self.ui.pushButtonActivateGrid.setIcon(QIcon(res_mng.get_icon_path("grid.png")))
        self.ui.pushButtonRatio.setIcon(       QIcon(res_mng.get_icon_path("ratio.svg")))
        self.ui.pushButtonComboPlot.setIcon(       QIcon(res_mng.get_icon_path("colored_charts.svg")))


        self.ui.pushButtonRatio.setIcon(       QIcon(res_mng.get_icon_path("ratio.svg")))

        self.ui.pushButtonTimeTracker.setIcon(       QIcon(res_mng.get_icon_path("play_arrow.svg")))
        self.ui.pushButtonTranslate.setText("转\n原文")
        self.ui.pushButtonBackward_1_step.setText("后退\n1步")
        self.ui.pushButtonForward_1_step.setText("前移\n1步")
        self.ui.pushButtonTimeTrackerSpeed.setText("常速")
        self.ui.pushButtonLogicSearch.setText("条件\n搜索")
        self.ui.pushButtonToFindPos.setText("至搜\n索点")

        # self.ui.pushButtonSaveLastTip.setIcon( QIcon(res_mng.get_icon_path("text_add.png")))
        # self.ui.pushButtonClearTips.setIcon( QIcon(res_mng.get_icon_path("text_del.png")))
        # self.ui.pushButtonParaSetUp.setIcon(     QIcon(res_mng.get_icon_path("settings_cog.svg")))

        self.ui.pushButtonClearTips.clicked.connect(self.on_pushButtonClearTips_click)
        self.ui.pushButtonSaveLastTip.clicked.connect(self.on_pushButtonSaveTip_click)

        self._apply_multilabel_btn_bg("red")
        # 设置timeSlider的范围并连接信号
        self.ui.timeSlider.setRange(0, 1000)  # 假设数据范围是0-1000
        self.ui.timeSlider.valueChanged.connect(self.on_time_slider_changed)

        # 创建事件过滤器实例
        self.event_filter = SliderEventFilter()
        # 为滑块安装事件过滤器
        self.ui.timeSlider.installEventFilter(self.event_filter)

        global_config.askSliderChange.connect(self.update_slider_val)
        global_config.logic_search_result_display.connect(self.handle_logic_search_display)

        self.update_all_vertical_lines(0,(0,0))
    
        self.rcd_data_bridge.add_observer(self.rcd_data_panel.on_rcd_data_update)

        global_config.off_row_data_read.connect(lambda:self.off_row_data_read.emit())
        global_config.on_off_row_data_read.connect(lambda e:self.on_off_row_data_read.emit(e))

        # 启用键盘焦点
        self.setFocusPolicy(Qt.StrongFocus)
        # self._scroll_manager =scroll_manager(self)
        

    def play_speed_switch(self):
        global_config.change_play_speed()
        text = "常速" if global_config.play_speed==PlaySpeed.NORMAL else "逐点"
        self.ui.pushButtonTimeTrackerSpeed.setText(text)

    def on_play_mode_change(self,mode):
        icon = QIcon(res_mng.get_icon_path("pause.svg")) if mode else QIcon(res_mng.get_icon_path("play_arrow.svg"))
        self.ui.pushButtonTimeTracker.setIcon(    icon   )

    def on_translate_mode_change(self,mode):
        text = "转\n原文" if mode else "转\n译文"
        self.ui.pushButtonTranslate.setText(text)

    def move_time_line_backward_1_step(self):
        current_tab = self.tabbed_widget.currentTab()
        plot = current_tab.first_plot_widget()
        if not plot:
            return
        plot.move_backward_1_step()
    def move_time_line_forward_1_step(self):
        current_tab = self.tabbed_widget.currentTab()
        plot = current_tab.first_plot_widget()
        if not plot:
            return
        plot.move_forward_1_step()
        

    @Slot(int)
    # @time_it
    def on_time_slider_changed(self, value):
        """处理timeSlider值变化"""
        # 添加防抖机制，避免频繁更新
        if hasattr(self, '_last_slider_change_time'):
            current_time = time.time()
            if current_time - self._last_slider_change_time < 0.1:  # 10ms防抖
               
                return
            self._last_slider_change_time = current_time
        else:
            setattr(self,'_last_slider_change_time',time.time())

        xlim = self.rcd_data_panel.get_xlim()
        if xlim is None:
            return
        x_min,x_max = self.rcd_data_panel.get_xlim()
        x_position = value * (x_max-x_min) / 1000 + x_min
        x_data= self.rcd_data_panel.get_xdata()
        idx = np.argmin(np.abs(x_data - x_position))

        if self.event_filter.is_user_interaction:
            trigger_type = "用户主动触发"
            self.update_all_vertical_lines(x_data[idx],(100,100))
            global_config.update_panel_data(idx) #滑动slider时更新rcd_panel的values
        else:
            trigger_type = "代码被动触发"

        current_x_data = x_data[idx]
        if global_config.xData_format == xLabelFormat.DT:
            #元素数据是毫秒时间戳  int
            timestamp = current_x_data + self.rcd_data_bridge.base_timestamp()  #  
            current_x_data_str =  datetime_from_timestamp(float(timestamp)/1000.0,False)
        else:
            current_x_data_str =  str(float(current_x_data)/1000.0) + "s"
        self.ui.displayTime.setText(current_x_data_str)
    


    @Slot()
    def handle_displayTime_text(self):
        displayTime:QLineEdit = self.ui.displayTime
        text = displayTime.text()
        if text == "":
            return
        if global_config.xData_format == xLabelFormat.SEC:
            dt = string_to_datetime(text)
            timestamp_ms = int(dt.timestamp() * 1000.0)
            time_s   = float(timestamp_ms-self.rcd_data_bridge.base_timestamp())/1000.0
            displayTime.setText(f"{time_s:.3f}s")
        else:
            timestamp_ms =int( float(text[:-1])*1000.0)+self.rcd_data_bridge.base_timestamp()
            displayTime.setText(datetime_from_timestamp(float(timestamp_ms)/1000.0,False))

    @Slot(int,tuple,int)
    # @time_it
    def update_slider_val(self,val,location,click_type):

        x_min,x_max = self.rcd_data_panel.get_xlim()
       
        v = (val-x_min)*1000/(x_max-x_min)

        self.update_all_vertical_lines(val,location,click_type)

        self.ui.timeSlider.setValue(int(v))

        current_x_data = val
        if global_config.xData_format == xLabelFormat.DT:
            #元素数据是毫秒时间戳  int
            timestamp = current_x_data + self.rcd_data_bridge.base_timestamp()  #  
            current_x_data_str =  datetime_from_timestamp(float(timestamp)/1000.0,False)
        else:
            current_x_data_str =  f"{(float(current_x_data)/1000.0):.3f}s"
            
        self.ui.displayTime.setText(current_x_data_str)

    @Slot(int)
    def handle_logic_search_display(self,idx):
        if self.logic_search_result is None:
            return
        
        if self.logic_search_result[1][idx]:
            self.ui.displayTime.setStyleSheet("background-color: yellow;")
        else:
            self.ui.displayTime.setStyleSheet("background-color: white;")
    
    def clear_logic_search_result(self):
        self.logic_search_result = None
        self.ui.displayTime.setStyleSheet("background-color: white;")

    def on_pushButtonClearTips_click(self):
        print("clear labels")
        current_tab = self.tabbed_widget.currentTab()
        if current_tab:
            for row in range(current_tab.rowsCount()):
                for col in range(current_tab.colsCount()):
                    plot_widget = current_tab.plotAt(row, col)
                    if plot_widget:
                        plot_widget.clear_labels()

    def on_pushButtonSaveTip_click(self):
        current_tab = self.tabbed_widget.currentTab()
        if current_tab:
            for row in range(current_tab.rowsCount()):
                for col in range(current_tab.colsCount()):
                    plot_widget = current_tab.plotAt(row, col)
                    if plot_widget:
                        plot_widget.save_latest_textbox()    

    def _apply_multilabel_btn_bg(self, bg_color: str) -> None:
        """给「多标签」按钮换底色。

        按钮不在当前 .ui 里时直接跳过（见 __init__ 里的说明），
        这样即使资源与代码不同步也不会在启动/快捷键里抛 AttributeError。
        """
        btn = getattr(self.ui, "pushButtonMultiLabels", None)
        if btn is None:
            return
        btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {bg_color};
                            color: white;
                            border: 2px solid darkred;
                            border-radius: 5px;
                            padding: 5px;
                        }}
                        QPushButton:hover {{
                            background-color: darkred;
                        }}
                        QPushButton:pressed {{
                            background-color: #8B0000;
                        }}
                    """)

    def handle_pushButtonMultiLabels_click(self):
       
        current_tab = self.tabbed_widget.currentTab()
        if current_tab:
            for row in range(current_tab.rowsCount()):
                for col in range(current_tab.colsCount()):
                    plot_widget = current_tab.plotAt(row, col)
                    if plot_widget:
                        plot_widget.clear_labels()

        if global_config.multi_label:
            global_config.enable_multi_label(False)
            self._apply_multilabel_btn_bg("red")

        else:
            global_config.enable_multi_label(True)
            self._apply_multilabel_btn_bg("rgb(134,183,200)")

    def pushButtonUseDateTime_click(self):
        """"""
        if global_config.xData_format== xLabelFormat.DT:
            global_config.set_xData_format(xLabelFormat.SEC)
        else:
            global_config.set_xData_format(xLabelFormat.DT)
        
        self.xLabelFormatChange.emit()
        

    def handle_pushButtonOptions_click(self):
        if self.ui.widgetOptions.isVisible():
            self.ui.widgetOptions.hide()
        else:
            self.ui.widgetOptions.show()
            
    def handle_pushButtonRatio_click(self):
        current_tab = self.tabbed_widget.currentTab()
        if current_tab:
            for row in range(current_tab.rowsCount()):
                for col in range(current_tab.colsCount()):
                    plot_widget = current_tab.plotAt(row, col)
                    if plot_widget:
                        plot_widget.restore_initial_lim()
   

    def handle_pushButtonActivateGrid_click(self):
        global_config.show_grid_enable(False) if global_config.show_grid else global_config.show_grid_enable(True)
        self.grid_show_change.emit()
    
    

    def update_all_vertical_lines(self, x_position:int,location,click_type:int=0):
        """更新所有图表中的竖直红线"""
        r ,c = location
        current_tab = self.tabbed_widget.currentTab()
        if current_tab:
            for row in range(current_tab.rowsCount()):
                for col in range(current_tab.colsCount()):
                    plot_widget = current_tab.plotAt(row, col)
                    if plot_widget:
                        if c==col and r==row:
                            plot_widget.set_vertical_line(x_position,click_type)
                        else:
                            type = click_type if click_type<2 else 3
                            plot_widget.set_vertical_line(x_position,type)
        

    def handle_pushButtonComboPlot_click(self):
        current_tab = self.tabbed_widget.currentTab()
        info = []
        for row in range(current_tab.rowsCount()):
            for col in range(current_tab.colsCount()):
                info_item = {}
                location = str(row) +str(col)
                head_names = current_tab.get_head_names_without_usr_data_in_plot(row,col)
                if head_names is None:
                    continue
                info_item["location"]  = location
                info_item["items"]     = head_names
                info.append(info_item)
        if not info:
            return
        # head_names = current_tab.head_names_in_solo_plot_window()
        # if head_names is None:
        #     return
        translater = self.__translater
        self.open_ComboPolt_dialog(info,translater)

    def open_ComboPolt_dialog(self,info,translater):
        """打开脚本输入对话框"""
        dialog = ComboPoltDataDialog(info,translater, self)
        dialog.data_updated.connect(self.combo_data_panel.update_list_widget)
        # dialog.script_executed.connect(self.on_script_executed)
        dialog.exec()
    
    def handle_translate_change(self):

        global_config.change_tr_mode()
        self.translate_mode_change.emit()

    def query_target_time_point(self):
        current_tab = self.tabbed_widget.currentTab()
        plot = current_tab.solo_plot_widget()
        if not plot:
            return
        print("--------passed--------------")
        # self.start_task_player(plot)



    def start_task_player(self):
        """启动任务"""
        current_tab = self.tabbed_widget.currentTab()
        # if not current_tab.is_plot_window_less_or_equl_than_two():
        #     return
        plot = current_tab.first_plot_widget()
        check_operation_callback  = self.tabbed_widget.check_operating_current_tab
        if not plot:
            return
        
        task_running = False
        id = None
        for thread_id, info in self.thread_manager.threads.items():
            if info['name']=="数据播放任务":
                if "running"==self.thread_manager.get_thread_status(thread_id):
                    task_running = True
                    id = thread_id
                    break


        if task_running:
            self.thread_manager.stop_thread(id)
        else:
            task_id = self.thread_manager.start_thread("数据播放任务", plot,self.rcd_data_bridge,check_operation_callback)
            self.thread_manager.get_thread_by_id(task_id).reset_fps(self.ui.playbackStep.value())
        # self.append_text(f"启动任务 ID: {task_id}")
            
    def set_player_fps(self,val):
        for thread_id, info in self.thread_manager.threads.items():
            if info['name']=="数据播放任务":
                self.thread_manager.get_thread_by_id(thread_id).reset_fps(val)


    def on_tab_window_clear(self):
        task_running = False
        id = None
        for thread_id, info in self.thread_manager.threads.items():
            if info['name']=="数据播放任务":
                if "running"==self.thread_manager.get_thread_status(thread_id):
                    task_running = True
                    id = thread_id
                    break


        if task_running:
            self.thread_manager.stop_thread(id)
    
    def stop_all_tasks(self):
        """停止所有任务"""
        self.thread_manager.stop_all_threads()
        # self.append_text("已停止所有任务")
    def stop_task_by_name(self,name:str):
        for thread_id, info in self.thread_manager.threads.items():
            if info['name']=="数据播放任务":
                self.thread_manager.stop_thread(thread_id)
                
    
    def show_status(self):
        """显示状态"""
        status_text = "当前线程状态:\n"

        for thread_id, info in self.thread_manager.threads.items():
            status_text += f"线程 {thread_id} ({info['name']}): {info['status']}\n"


    def open_script_dialog(self):
        """打开脚本输入对话框"""
        current_tab = self.tabbed_widget.currentTab()
        
        # head_names = current_tab.head_names_in_solo_plot_window()
        # if head_names is None:
        #     return
        head_names = []
        for row in range(current_tab.rowsCount()):
            for col in range(current_tab.colsCount()):
                head_names_in_plot = current_tab.get_head_names_in_plot(row,col)
                if head_names_in_plot is None:
                    continue
                head_names.extend(head_names_in_plot)
        unique_head_names = list(set(head_names))
        # self.logic_search_result = None
        self._dialog = LogicScriptInputDialog(self.data_transformer,self.rcd_data_bridge,unique_head_names, self)
        self._dialog.script_executed.connect(self.get_logic_search_result)
       
        self._dialog.exec()


    @Slot(tuple)
    def get_logic_search_result(self,result):

        self.logic_search_result = result

    
    def handle_pushButtonToFindPos_click(self):
        if self.logic_search_result is None:
            return
        current_tab = self.tabbed_widget.currentTab()
        plot = current_tab.first_plot_widget()
        if not plot:
            return
        plot.move_to_next_search_point(self.logic_search_result[1])


    def toggle_left_panel(self):
        """切换左半边显示/隐藏"""
        if self.ui.leftFrame.isVisible():
            self.ui.leftFrame.hide()
        else:
            self.ui.leftFrame.show()


    def show_left_panel(self):
        """显示左面板"""
        target_sizes = [400, self.ui.splitter.width() - 400]
        self.animation.animate_to(target_sizes)
        self.is_left_hidden = False
    
    def hide_left_panel(self):
        """隐藏左面板"""
        target_sizes = [0, self.ui.splitter.width()]
        self.animation.animate_to(target_sizes)
        self.is_left_hidden = True

    def handle_delete_lines(self):
        self.tabbed_widget.delete_hidden_lines()

    def check_hover(self):
        """检查鼠标悬停"""
        if self.is_left_hidden:
            mouse_pos = QCursor.pos()
            splitter_global_pos = self.ui.splitter.mapToGlobal(QPoint(0, 0))
            relative_mouse_x = mouse_pos.x() - splitter_global_pos.x()
            # print(mouse_pos.x(),splitter_global_pos.x())
            if (0 <= relative_mouse_x <= 15 and 
                self.underMouse()):
               
                self.show_left_panel()
    def closeEvent(self, event):
        """窗口关闭事件"""
        self.thread_manager.stop_all_threads()
        event.accept()
    
    
    
    def showAbout(self):
        """显示关于信息"""
        QMessageBox.about(self, "操作说明", 
                        
                         "支持功能：\n"
                         "- 多标签页管理\n"
                         "- 行列分裂窗口\n"
                         "- 动态添加/删除标签页\n\n"
                         "使用方法：\n"
                         "1. 滚轮缩放\n"
                         "2. CTRL+滚轮  Y轴缩放\n"
                         "2. CTRL+鼠标左键  框选放大\n"
                         "3. 鼠标左键拖拽平移")

