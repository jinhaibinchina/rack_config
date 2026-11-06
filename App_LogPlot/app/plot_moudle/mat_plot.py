from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (QApplication, QWidget,  QVBoxLayout)
from PySide6.QtCore import Signal, Slot, Qt, QMimeData,QTimer,QEvent,QPoint
from PySide6.QtGui import QDragEnterEvent,QDragMoveEvent,QDropEvent
# Qt6 绑定统一走 backend_qtagg（backend_qt5agg 会强制去 import PyQt5）
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
from matplotlib.text import Text
from matplotlib.legend import Legend
from matplotlib.backend_bases import LocationEvent, MouseButton, MouseEvent,KeyEvent,PickEvent

from matplotlib.ticker import MaxNLocator
import matplotlib.ticker as ticker
from matplotlib.ticker import Locator, Formatter
from typing import Dict, Tuple, List,TYPE_CHECKING,Optional

from .global_config import global_config,PlaySpeed

import copy,time
from .common import xLabelFormat,datetime_from_timestamp,datetime_from_timestamp_for_xAxis,time_it
from .down_simple import average_downsample_simple
from .measure_tool import ToolSystem

if TYPE_CHECKING:
    from .polt_matrix import PlotMatrix

SAMPLE_COUNT_MOVING = 3000
SAMPLE_COUNT_STATIC = 6000

class FixedPositionLocator(Locator):
    """固定物理位置的刻度定位器"""
    
    def __init__(self, fixed_positions):
        """
        fixed_positions: 在图形坐标中的固定位置列表 [0.0, 0.25, 0.5, 0.75, 1.0]
                        0.0表示左/下边缘，1.0表示右/上边缘
        """
        self.fixed_positions = fixed_positions
        
    def __call__(self):
        """返回刻度位置（数据坐标）"""
        # 获取当前轴的范围
        vmin, vmax = self.axis.get_view_interval()
        
        # 将图形坐标转换为数据坐标
        positions = []
        for pos in self.fixed_positions:
            data_pos = vmin + pos * (vmax - vmin)
            positions.append(data_pos)
            
        return positions

class DynamicTickFormatter(Formatter):
    """动态刻度格式化器"""
    
    def __init__(self, axis_type='x'):
        self.axis_type = axis_type
        
    def __call__(self, x, pos=None):
        """格式化刻度标签"""
        if self.axis_type == 'x':
            return f'{x:.2f}'
        else:
            return f'{x:.2f}'


def get_display_width(text:str):
    """计算文本的显示宽度（中文算2个字符，英文算1个）"""
    width = 0
    for char in text:
        # 基本多文种平面（BMP）中的中文字符
        if '\u4e00' <= char <= '\u9fff':
            width += 2
        else:
            width += 1
    return width



class MplPlotWidget(QWidget):
    # 在接收端解码
    @staticmethod
    def decode_mime_data(mime_data):
        if mime_data.hasFormat("application/data-keys"):
            import json
            byte_data = mime_data.data("application/data-keys")
            json_str = byte_data.data().decode('utf-8')
            data_heads = json.loads(json_str)
            return data_heads
        return None
    
    
    @staticmethod
    def contact_context(head:str,tail:str,maxlen:int):
        space_len = maxlen-get_display_width(head)-get_display_width(tail)+5
        middle = "-"*(space_len-2) +"> " 
        return head + middle +tail
    @staticmethod
    def to_hex_string(number, precision=0):
        """
        将数字转换为0x格式的16进制字符串
        
        Args:
            number: 输入的数字（整数或浮点数）
            precision: 对于浮点数，小数点后保留的位数（默认取整）
        
        Returns:
            0x格式的16进制字符串
        """
        if isinstance(number, int) or isinstance(number, np.int64):
            return f"0x{number:x}"
        elif isinstance(number, float) or isinstance(number, np.float64):
            # 根据精度处理浮点数
            if precision > 0:
                scaled = int(number * (10 ** precision))
                return f"0x{scaled:x}"
            else:
                return f"0x{round(number):x}"
        else:
            print(type(number))
            raise ValueError("输入必须是整数或浮点数")


    xlim_changed =Signal(tuple)

    def __init__(self, name: str,location:Tuple[int,int], parent:PlotMatrix,ax_vice_en=False):
        super().__init__(parent)
        self._name = name
        # 创建 Matplotlib 图形和画布 - 使用更大的默认尺寸
        self.figure = Figure(figsize=(10, 8), dpi=100)
        self.canvas = FigureCanvas(self.figure)

        # 启用拖放功能
        self.setAcceptDrops(True)
        # 启用鼠标跟踪和滚轮缩放
        self.setMouseTracking(True)

        self.canvas.setFocusPolicy(Qt.StrongFocus)
       
        # 创建主绘图区域
        self.ax = self.figure.add_subplot(111)
        # 设置布局 - 使用固定边距让图表尽可能大
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)  # 固定边距
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        
        self._location = location
        # 初始化数据
        self.background = None

        self.lines :List[Line2D]                             = []
        self.lines_visionable_flag :List[bool]               = []
        self.lineKeys_lineColors:List[Tuple[str,str]]        = []
        # 与 self.lines 一一对应：该曲线画在主轴还是副轴（twinx）。
        # 只有 ax_vice_en=True 的窗口（主副轴合并图）才会出现 True。
        self.lines_on_vice :List[bool]                       = []

        self.__is_has_usr_define_line = False#是否加入了自定义曲线

        # 存储交点标记
        self.intersection_points:List[Line2D] = []
       
        self._plot_muiti_lines_flag = False  #是否正在绘制多条曲线,若是，则不马上更新x坐标标签
       
        self.vertical_line:Optional[Line2D]              = None  # 竖直红线
        self.vertical_lines_store:Optional[List[Line2D]] = []  # 竖直红线
        self.vertical_lines_position:List[float]         = []

        self.intersection_textbox_now: Optional[Text] = None
        self.intersection_textboxs_store:List[Text]   = []
        self.label_infos:List[Tuple[float,float,str]] = []
        

        self.__current_x_position = 0  # 当前红线位置

        self._rcd_data_bridge = parent.data_bridge() 
        self._rcd_translater  = parent.translater()
        
        self.ax_vice_en = ax_vice_en
        self.ax_vice = None

        if ax_vice_en :
            self.ax_vice = self.ax.twinx()
            self.ax_vice.spines['right'].set_position(('axes', 1.0))  # 让第二个子图的坐标轴在右边显示

        self.set_grid()
        
        # 设置坐标轴边距
        self.figure.subplots_adjust(left=0.06, right=0.99, top=0.98, bottom=0.03)
        
        
        self.connect_events()
          # 设置画布可以接收焦点
        
        self.zoom_factor = 1.5  # 缩放因子
        self.last_event_info =""
        # 框选放大相关变量
        self.zoom_rect:Optional[ Rectangle]  = None
        self.zoom_start:Optional[ Tuple[float,float]] = None
        self.zoom_end :Optional[ Tuple[float,float]]  = None
        self.is_zooming = False
        self.is_zooming_by_right_mouse = False
        self.xlim_when_zoom_start:Optional[ Tuple[float,float]] = None
        self.ylim_when_zoom_start:Optional[ Tuple[float,float]] = None
        self.zoom_by_right_mouse_start:Optional[ Tuple[float,float]] = None #数据坐标
        self.zoom_by_right_mouse_start_cursor:Optional[QPoint] = None
        self.check_mouse_move_Timer = QTimer(self)
        self.check_mouse_move_Timer.timeout.connect(self.check_mouse_move)

        self.is_scrolling = False
        self.check_scroll_timer = QTimer(self)
        self.check_scroll_timer.timeout.connect(self.check_scrolling)

        self.CTRL_pressed =False
        self.SHIFT_pressed =False
        self.mouse_right_pressed = False

        self._mouse_data:Optional[ Tuple[float,float]]  =  None

        # 平移相关变量
        self.is_panning = False
        self.pan_start:Optional[ Tuple[float,float]] = None
        self.pan_start_xlim:Optional[ Tuple[float,float]] = None
        self.pan_start_ylim:Optional[ Tuple[float,float]] = None
        self.last_pan_position:Optional[ Tuple[float,float]] = None

        

        self.color_index =0

        self.__sample_count =SAMPLE_COUNT_STATIC
        
        self.update_initial_lim()

        self.fontsize = 8

        self._draw_flag = False

        self.__idx_min = 0
        self.__idx_max = self._rcd_data_bridge.idx_count()
        # self.setup_true_fixed_ticks()
        # self.connect_events()

        self.ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.1f'))
        self.ax.xaxis.set_major_locator(MaxNLocator(nbins=10))
        # 连接图例点击事件
        self.canvas.mpl_connect('pick_event', self._on_legend_click)

        self.measure_tool = ToolSystem(self)
        global_config.measure_ruler_mode_off.connect(self.on_measure_ruler_mode_off)

        self.measure_tool.measure_done.connect(lambda:global_config.measure_ruler_done.emit())
   
    def adjust_subplots(self,top=0.98,bottom=0.03):
        # 设置坐标轴边距
        self.figure.subplots_adjust(left=0.06, right=0.99, top=top, bottom=bottom)

    def idx_min(self):
        return self.__idx_min
    def idx_max(self):
        return self.__idx_max
    
    def resizeEvent(self, event):
        """重写缩放事件处理"""
        # 获取新的窗口尺寸
        self.on_leave_zooming()
        self.replot()
        self.background = None

        
        # 调用父类方法确保正常处理
        super().resizeEvent(event)

    def reduce_font_size(self):
        self.fontsize = 8
        legend = self.ax.get_legend()
        if legend:
            self.update_legend_texts_colors()
        if self.intersection_textbox_now:
            self.intersection_textbox_now.set_fontsize(self.fontsize)
        for textbox in self.intersection_textboxs_store:
            textbox.set_fontsize(self.fontsize)
        self.ax.tick_params(axis='y', labelsize=self.fontsize)


        self.replot_idle()


    def update_partly(self,enable:bool=True,is_single_click:bool=False):
        """高效更新动态元素,垂直线移动时"""
        self.measure_tool.check_if_show_labels() 
        if not enable:
            self.background = None
            return
        if self.is_paning_or_scrolling_or_zooming():
            return
        
        if self.background is None:
            print("生成背景")
            if self.vertical_line:
                self.vertical_line.set_visible(False)
            if self.intersection_textbox_now:
                self.intersection_textbox_now.set_visible(False)
            for box in self.intersection_textboxs_store:
                box.set_visible(False)
            for point in self.intersection_points:
                point.set_visible(False)
            for line in self.vertical_lines_store:
                line.set_visible(False)
            self.replot()
            # 保存背景（包含所有静态元素）
            self.background = self.canvas.copy_from_bbox(self.ax.bbox)


            if self.vertical_line:
                self.vertical_line.set_visible(True)
            if self.intersection_textbox_now:
                self.intersection_textbox_now.set_visible(True)
            for box in self.intersection_textboxs_store:
                box.set_visible(True)
            for line in self.vertical_lines_store:
                line.set_visible(True)
            for point in self.intersection_points:
                point.set_visible(True)
        
        if self.background:
            # 1. 恢复背景（不重绘静态元素）
            self.canvas.restore_region(self.background)

            if self.vertical_line:
                self.ax.draw_artist(self.vertical_line)
            for line in self.vertical_lines_store:
                self.ax.draw_artist(line)
            for point in self.intersection_points:
                self.ax.draw_artist(point)
            #对于单次点击事件需要更新legend使得竖直线显示于legend之后
            if is_single_click:
                legend = self.ax.get_legend()
                if legend:
                  
                    # Use a safer approach to draw legend without causing recursion
                    try:
                        self.ax.draw_artist(legend)
                    except RecursionError:
                        # Fallback: skip legend drawing to avoid recursion
                        pass

            for  head_point in  self.measure_tool.measure_marks['headpoints']:
                self.ax.draw_artist(head_point)
            for  end_point in  self.measure_tool.measure_marks['endpoints']:
                self.ax.draw_artist(end_point)
            for  line in  self.measure_tool.measure_marks['marklines_x']:
                if line:
                    self.ax.draw_artist(line)
            for  line in  self.measure_tool.measure_marks['marklines_y']:
                if line:
                    self.ax.draw_artist(line)
            for  textbox in self.measure_tool.measure_marks['marktexts_x']:
                if textbox:
                    self.ax.draw_artist(textbox)
            for  textbox in  self.measure_tool.measure_marks['marktexts_y']:
                if textbox:
                    self.ax.draw_artist(textbox)
            

            
            if self.intersection_textbox_now:
                self.ax.draw_artist(self.intersection_textbox_now)
            for box in self.intersection_textboxs_store:
                self.ax.draw_artist(box)
            
            # 4. 只更新变化的部分到屏幕
            self.canvas.blit(self.ax.bbox)
            self.canvas.flush_events()


    def on_view_change(self,event):
        """视图变化回调"""
        self.reset_lines_data()

    def on_view_x_change(self,event):
        """视图x变化回调"""
        pass
    
    def replot_when_quit_view_change(self):
        """退出平移和缩放时"""
        if self.is_panning :
            self.is_panning = False
        if self.is_scrolling:
            self.is_scrolling = False
            self.on_leave_zooming()
        if self.is_zooming_by_right_mouse:
            self.is_zooming_by_right_mouse = False
            self.on_leave_zooming()
        
        self.__sample_count = SAMPLE_COUNT_STATIC
        self.set_grid()
        self.reset_lines_data()
        if self.intersection_textbox_now:
            self.intersection_textbox_now.set_visible(True)
        for box in self.intersection_textboxs_store:
            box.set_visible(True)
        self.replot()

    def do_when_entry_view_change(self):
        self.__sample_count = SAMPLE_COUNT_MOVING
        self.hide_grid()
        if self.intersection_textbox_now:
            self.intersection_textbox_now.set_visible(False)
        for box in self.intersection_textboxs_store:
            box.set_visible(False)
            
    def reset_lines_data(self):
        """1. xlim 变化时调用   2."""
        xmin ,xmax = self.get_xlim()
        d = (xmax -xmin)*0.1
        xmin = xmin -d
        xmax = xmax +d
        xdata = self._rcd_data_bridge.xdata_rcd()
        if xdata is None:
            return
        idx_min = np.argmin(np.abs(xdata - xmin))
        idx_max = np.argmin(np.abs(xdata - xmax))
       
        xdata_new = xdata[idx_min:idx_max+1]
        data_map = self._rcd_data_bridge.get_all_data_save_in_bridge()
        
        self.__idx_min,self.__idx_max =idx_min,idx_max

     
        for line in self.lines:
            key = line.get_label()
            # _,ydata = self._rcd_data_bridge.get_one_data_saved_in_bridge(key)
            _,ydata = data_map[key]
           
            new_xdatas,new_ydatas = average_downsample_simple(xdata_new,ydata[idx_min:idx_max+1],self.__sample_count)
            # line.set_data(xdata_new,ydata[idx_min:idx_max+1])
            line.set_data(new_xdatas,new_ydatas)

    def connect_events(self):
        """连接事件"""
        self.canvas.mpl_connect('scroll_event', self.on_scroll)
        self.canvas.mpl_connect('button_press_event', self.on_button_press)
        self.canvas.mpl_connect('button_release_event', self.on_button_release)
        self.canvas.mpl_connect('key_press_event', self.on_key_press)
        self.canvas.mpl_connect('key_release_event', self.on_key_release)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion_notify)
        self.ax.callbacks.connect('xlim_changed', self.on_view_change)
        self.ax.callbacks.connect('xlim_changed', self.on_view_x_change)
        # self.ax.callbacks.connect('ylim_changed', self.on_view_change)
        # self.canvas.mpl_connect('draw_event', self.on_draw)
        self.canvas.mpl_connect('axes_leave_event', self.on_axes_leave)
        self.canvas.mpl_connect('axes_enter_event', self.on_axes_enter)
       
    def check_mouse_move(self):
        
        if not self.is_zooming_by_right_mouse:
            self.check_mouse_move_Timer.stop()
            return
        self.handle_zooming_by_right_mouse(False)
        

    def on_axes_leave(self,event:LocationEvent):
        # print("鼠标离开画布")
        if self.is_zooming_by_right_mouse:
            self.check_mouse_move_Timer.start(50)
        self.CTRL_pressed = self.SHIFT_pressed = False
    
    def on_axes_enter(self,event:LocationEvent):
        modifiers = QApplication.keyboardModifiers()
        if modifiers == Qt.ControlModifier:
            self.CTRL_pressed = True
        
        self.canvas.setFocus()

    def current_x_position(self):
        return self.__current_x_position   
    
    def current_x_idx(self):
        xdatas = self._rcd_data_bridge.xdata_rcd()
        if xdatas is None:
            return 0
        idx = np.argmin(np.abs(xdatas - self.__current_x_position))
        return idx
        
    def target_x_position(self,forword:bool):
        b,f =self._rcd_data_bridge.xlim()
        if forword :
            return f
        return b
    
    def target_x_idx(self,forword:bool=True):
        xdatas = self._rcd_data_bridge.xdata_rcd()
        if xdatas is None:
            return 0
        idx = np.argmin(np.abs(xdatas - self.target_x_position(forword)))
        return idx
    
    def x_step(self):
        return  self._rcd_data_bridge.x_data_step()    
    
    @Slot(int)
    def move_slider_by_idx(self,idx:int):
        
        current_time = time.time()
        if hasattr(self, '_last_slider_move_time'):
            if current_time - self._last_slider_move_time < 0.02:  # 50ms防抖，20fps
                return
        self._last_slider_move_time = current_time

        x_data = self._rcd_data_bridge.xdata_rcd()

        global_config.ask_slider_change(x_data[idx],idx ,self._location)


    def set_grid(self):
        if global_config.show_grid:
            self.ax.grid(True, alpha=0.3)
            # self.ax.grid(True, which='minor', linestyle=':', alpha=0.4)  # 次网格（虚线）
        else:
            self.ax.grid(False)

    def hide_grid(self):
         # Use a more direct approach to hide grid without triggering recursive events
        if hasattr(self.ax, '_gridOnMajorX') or hasattr(self.ax, '_gridOnMajorY'):
            # If using newer matplotlib version with direct grid control
            self.ax.grid(False, which='both')
        # self.ax.grid(False)
        self.ax.xaxis.grid(False)
        self.ax.yaxis.grid(False)

    def data_head_names_without_usr_data_lst(self):
        """返回rcd曲线 数据表头名称列表"""
        if self.__is_has_usr_define_line or not self.lineKeys_lineColors:
            return None
       
        return  [x[0] for  x in self.lineKeys_lineColors]
    
    def data_head_names_lst(self):
        """返回rcd曲线 数据表头名称列表"""
        if  not self.lineKeys_lineColors:
            return None
       
        return  [x[0] for  x in self.lineKeys_lineColors]   
    
    def update_initial_lim(self):

        self.initial_xlim = self.get_xlim()
        self.initial_ylim = self.get_ylim()
        if self.ax_vice is not None:
            self.initial_ylim_vice = self.ax_vice.get_ylim()

        print(f"initial_xlim={self.initial_xlim}&",f"initial_ylim={self.initial_ylim}")

    def restore_initial_lim(self):
        self.set_xlim_and_draw(self.initial_xlim[0],self.initial_xlim[1])
        self.set_ylim_and_draw(self.initial_ylim[0],self.initial_ylim[1])
        if self.ax_vice is not None and hasattr(self, "initial_ylim_vice"):
            self.ax_vice.set_ylim(self.initial_ylim_vice)
        self.change_xaxis_labels_by_format()
        self.on_leave_zooming()
        self.update_partly(False)
        self.replot_idle()

    def restore_initial_ylim(self):
        
        self.set_ylim_and_draw(self.initial_ylim[0],self.initial_ylim[1])
       
        self.on_leave_zooming()
        self.update_partly(False)
        self.replot_idle()


    @time_it    
    def plot(self, x_data, y_data, label=None, color=None, linewidth=0.5, ax_vice_en=False):
        """绘制数据。ax_vice_en=True 时画在右侧副轴上（需窗口以 ax_vice_en=True 创建）。"""
        #line,解包拿到第一个元素
        target_ax = self.ax_vice if (ax_vice_en and self.ax_vice is not None) else self.ax
        line, = target_ax.plot(x_data, y_data, label=label, color=color, linewidth=linewidth,zorder=1)
        self.lines.append(line)
        self.lines_visionable_flag.append(True)
        self.lineKeys_lineColors.append((label,color))
        self.lines_on_vice.append(target_ax is self.ax_vice)
       
        # 重新设置样式
        self.set_grid()
        
        if label:
            # 更新图例，设置所有标签的颜色
            self.update_legend_texts_colors()
        
        # 自动调整坐标轴范围以显示所有曲线
        self._auto_scale_to_fit_all_curves(line)
        
        self.change_xaxis_labels_by_format()

        
    
    def set_axis_visible(self, major: bool, vice: bool):
        """按主轴 / 副轴批量显隐曲线。

        只作用于以 ax_vice_en=True 创建的主副轴合并窗口；普通窗口直接忽略，
        避免「主」「副」按钮影响别的图表。
        """
        if self.ax_vice is None:
            return
        for i, line in enumerate(self.lines):
            on_vice = self.lines_on_vice[i] if i < len(self.lines_on_vice) else False
            visible = bool(vice if on_vice else major)
            line.set_visible(visible)
            if i < len(self.lines_visionable_flag):
                self.lines_visionable_flag[i] = visible
        if self.lines:
            # 重建图例，让半透明 / 虚线的隐藏态跟曲线一致
            self.update_legend_texts_colors()
        self.update_partly(False)
        self.replot_idle()

    def get_line(self, line_name: str):
        """根据线名获取线实例"""
        for i, line in enumerate(self.lines):
            if line.get_label() == line_name:
                return line,i
        return None
    
    def del_line(self,line_name:str):

        line,index = self.get_line(line_name)
        if line is None:
            return
        line.remove()
        del self.lines[index]
        del self.lines_visionable_flag[index]
        del self.lineKeys_lineColors[index]
        if index < len(self.lines_on_vice):
            del self.lines_on_vice[index]

        self.update_legend_texts_colors()
        self.replot_idle()
        self.update_partly(False)
    
    def del_hidden_lines(self):
        line_names  = [line.get_label() for line in self.lines]
        for i,visionable in enumerate(self.lines_visionable_flag.copy()):
            if visionable == False:
                self.del_line(line_names[i])
    
    def is_already_has_this_line(self, line_name: str):
        """当前绘图窗口是否已经放入某曲线"""
        for line in self.lines:
            if line.get_label() == line_name:
                return True
        
        return False

    def is_already_add_line(self):

        return len(self.lines) > 0

    def update_legend_texts_colors(self):
        """更新图例中所有标签的颜色"""
        
        # 清除现有图例
        if self.ax.get_legend():
            self.ax.get_legend().remove()
        
        # 重新创建图例
        # 普通窗口沿用 matplotlib 自动收集；主副轴窗口需要显式给出 handles，
        # 否则 self.ax.legend() 看不到画在 twinx 上的副轴曲线。按 self.lines
        # 的顺序传入，保证 legend.get_lines()[i] 与 self.lines[i] 仍然对齐
        # （_setup_legend_click_events / _on_legend_click 依赖这个下标）。
        if self.ax_vice is not None and self.lines:
            legend = self.ax.legend(
                self.lines,
                [line.get_label() for line in self.lines],
                loc='upper left',
                fontsize=self.fontsize,
            )
        else:
            legend = self.ax.legend(loc='upper left',fontsize=self.fontsize)
        
        # legend.get_frame().set_zorder(2)  # 设置很高的 zorder
        legend.set_zorder(2)
        # 设置每个标签的颜色
        if legend:
            for i, text in enumerate(legend.get_texts()):
                if i < len(self.lineKeys_lineColors):
                    label, color = self.lineKeys_lineColors[i]
                    if global_config.show_rcd_helping_text_on_panel:
                        
                        tr_label =self._rcd_translater.translate_title(label)
                        
                        if tr_label:                       
                            text.set_text(tr_label)
                    else:
                       
                        text.set_text(label)

                    if color is not None:
                        text.set_color(color)

            # 为图例添加点击事件处理
            self._setup_legend_click_events(legend)

            self.replot_idle()
    
    def _setup_legend_click_events(self, legend:Legend):
        """设置图例点击事件"""
        # 为图例中的每个条目设置点击事件
        for i, legend_line in enumerate(legend.get_lines()):
            legend_line.set_visible(True)
            if not self.lines[i].get_visible():
                legend_line.set_alpha(0.3)
                legend_line.set_linestyle('--')
            legend_line.set_picker(True)  # 启用拾取
            legend_line.set_pickradius(5)  # 设置拾取半径
        
        
    
    def _on_legend_click(self, event:PickEvent):
        """图例点击事件处理"""
     
        if event.artist in self.ax.get_legend().get_lines():
            # 获取点击的图例索引
            legend = self.ax.get_legend()
            clicked_index = list(legend.get_lines()).index(event.artist)
            # 确保索引在有效范围内
            if clicked_index < len(self.lines):
                # 切换对应曲线的可见性
                line =  self.lines[clicked_index]
                line.set_visible(not line.get_visible())
                if not line.get_visible():
                    self.lines_visionable_flag[clicked_index] =False
                else:
                    self.lines_visionable_flag[clicked_index] =True
                # 更新图例的视觉状态
                legend_line = legend.get_lines()[clicked_index]
                if line.get_visible():
                    # 曲线可见时，恢复图例线条的原始样式
                    legend_line.set_alpha(1.0)
                    legend_line.set_linestyle('-')
                else:
                    # 曲线隐藏时，将图例线条设置为半透明和虚线
                    legend_line.set_alpha(0.3)
                    legend_line.set_linestyle('--')
                    
                self._update_initial_lim_when_hide_unhide_line()
                # 重绘图表
                self.replot()

    def _auto_scale_to_fit_all_curves(self,new_line:Line2D):
        # 主副轴窗口里两种曲线的量纲常常差好几个数量级，混在一起算 y 范围
        # 会把两组都压成直线。只跟「和 new_line 同一根轴」的曲线合并范围。
        on_vice = self.ax_vice is not None and new_line.axes is self.ax_vice

        x_data = new_line.get_xdata()
        y_data = new_line.get_ydata()
        
        # 确保数据是数值类型
        try:
            x_min, x_max = x_data.min(), x_data.max()
            y_min, y_max = y_data.min(), y_data.max()
        except (TypeError, ValueError):
            # 如果数据包含非数值类型，跳过自动缩放
            print("警告: 数据包含非数值类型，跳过自动缩放")
            print(x_data,y_data)
            return

        for line, line_on_vice in zip(self.lines, self.lines_on_vice):
            if line_on_vice != on_vice:
                continue

            key = line.get_label()
            x_data,y_data = self._rcd_data_bridge.get_one_data_saved_in_bridge(key)
            # 确保数据是数值类型
            try:
                # 计算数据范围
                x_range = (x_data.min(), x_data.max())
                y_range = (y_data.min(), y_data.max())
                
                if x_min > x_range[0]:
                    x_min = x_range[0]
                if x_max < x_range[1]:
                    x_max = x_range[1]
                if y_min > y_range[0]:
                    y_min = y_range[0]
                if y_max < y_range[1]:
                    y_max = y_range[1]
            except (TypeError, ValueError):
                # 跳过包含非数值数据的曲线
                print(f"警告: 跳过包含非数值数据的曲线: {line.get_label()}")
                continue
                
        h = (y_max - y_min)* 0.1
        # self.set_xlim_and_draw(x_min ,x_max)
        if on_vice:
            self.ax_vice.set_ylim(y_min-h, y_max+h)
            self.replot_idle()
        else:
            self.set_ylim_and_draw(y_min-h ,y_max+h)
        self.update_initial_lim()
        self.initial_xlim = (x_min,x_max)

    def _update_initial_lim_when_hide_unhide_line(self):
        """当隐藏显示曲线时调整初始视窗位置值保存"""
        y_min ,y_max= self.get_ylim()
        for  line  in self.lines:
            if line.get_visible():

                y_min ,y_max= line.get_ydata().min(),line.get_ydata().max()
                break


        for line  in self.lines:
            if line.get_visible():
            
                y_data = line.get_ydata()  # 获取y轴数据
                # 计算数据范围
               
                y_range = (y_data.min(), y_data.max())
               
                if y_min>y_range[0]:
                    y_min = y_range[0]
                if y_max<y_range[1]:
                    y_max = y_range[1]

        h = (y_max - y_min)* 0.1
       
        self.initial_ylim = (y_min-h ,y_max+h)

        self.restore_initial_lim()


    def clear(self):
        """清除图形"""
        
        self.ax.clear()
        if self.ax_vice is not None:
            self.ax_vice.clear()
            self.ax_vice.spines['right'].set_position(('axes', 1.0))
        self.lines.clear()
        self.lines_visionable_flag.clear()
        self.lineKeys_lineColors.clear()
        self.lines_on_vice.clear()
        self.intersection_points.clear()
        self.label_infos.clear()
        self.intersection_textboxs_store.clear()
        
        self.vertical_lines_store.clear()
        self.vertical_lines_position.clear()

        self.intersection_textbox_now=None
        self.vertical_line =None
        self.background = None
        self.__is_has_usr_define_line =False
        self.set_grid()
        self.update_initial_lim()

        self.measure_tool.clear()
        
        self.ax.callbacks.connect('xlim_changed', self.on_view_change)

        self.replot()
        
    def set_xlim_and_draw(self, xmin:float, xmax:float):
        """设置X轴范围"""
        self.ax.set_xlim(xmin, xmax)
        self.replot()

    def set_xlim(self, xlim:Tuple):
        """设置X轴范围"""
        xmin, xmax = xlim

        self.ax.set_xlim(xmin, xmax)

        if global_config.sync_x_axis:

            self.xlim_changed.emit((self._location,self.get_xlim()))


    def set_ylim_and_draw(self, ymin:float, ymax:float):
        """设置Y轴范围"""
        self.ax.set_ylim(ymin, ymax)
        self.replot()
    
    def set_ylim(self, ylim:Tuple[float,float]):
        """设置Y轴范围"""
        ymin, ymax = ylim
        self.ax.set_ylim(ymin, ymax)
        
    def set_title(self, title:str):
        """设置标题"""
        self.ax.set_title(title)
        self.replot()

    # @time_it
    def replot(self):
        """重绘"""
        self.canvas.draw()
    
    # @time_it
    def replot_idle(self):
        """重绘"""
        self.canvas.draw_idle()
        
    def get_xlim(self):
        """获取X轴范围"""
        return self.ax.get_xlim()
        
    def get_ylim(self):
        """获取Y轴范围"""
        return self.ax.get_ylim()
        
    def name(self):
        return self._name
    

    def set_vertical_line(self, x_position:int,click_type:int):
        """设置竖直红线位置  click_type  0:play  2:mouse  1:key  """
        
        self._draw_flag = True
        if  self.__current_x_position == x_position:
            return
        self.__current_x_position = x_position
        # 如果红线不存在，创建它
        if self.vertical_line is None:
            # ylim = self.get_ylim()
            self.vertical_line = self.ax.axvline(x=x_position, color='red', linewidth=0.4, linestyle='--',zorder=1)
            
        else:
            # 更新现有红线位置
            self.vertical_line.set_xdata([x_position, x_position])
        
        # 重绘图表
        self.update_vertical_line()
        self._handle_intersection_points_text(click_type)

        # if  global_config.multi_label:
        #     if self.intersection_textbox_now:
                
        #         context = copy.deepcopy(self.intersection_textbox_now.get_text())
        #         x,y = self.intersection_textbox_now.get_position()
        #         self.label_infos.append((x,y,context))
        #         # [int, int]
        #         x = self.vertical_line.get_xdata()[0]
        #         self.vertical_lines_position.append(x)
                 
        #         if len(self.label_infos) <2:
        #             self.update_partly()
        #             # self.replot_idle()
        #             return   
        #         x,y,text =    self.label_infos[-2]  #[ , ,_, ,]
        #         textbox = self.ax.text(x, y, text, 
        #                     bbox=dict(boxstyle="round,pad=0.3", 
        #                             facecolor="lightyellow", 
        #                             alpha=0.8, 
        #                             edgecolor="black"),
        #                     fontsize=self.fontsize,
        #                     verticalalignment='center',
        #                     weight='bold',zorder=3, clip_on=True)
                
        #         self.intersection_textboxs_store.append(textbox)
        #         textbox.set_visible(True)

        #         x_position = self.vertical_lines_position[-2]
        #         line = self.ax.axvline(x=x_position, color='red', linewidth=0.4, linestyle='--',zorder=1)
        #         self.vertical_lines_store.append(line)
        #         line.set_visible(True)

        #         if len(self.label_infos)>3:
        #             self.intersection_textboxs_store[0].remove()
        #             self.intersection_textboxs_store.pop(0)
        #             self.label_infos.pop(0)
        #         if len(self.vertical_lines_position)>3:
        #             self.vertical_lines_store[0].remove()
        #             self.vertical_lines_store.pop(0)
        #             self.vertical_lines_position.pop(0)
        # else:
        #     if len(self.intersection_textboxs_store)>0:
        #         for textbox in self.intersection_textboxs_store:
        #             textbox.remove()
        #         self.label_infos.clear()
        #         self.intersection_textboxs_store.clear()
        #     if len(self.vertical_lines_store)>0:
        #         for line in self.vertical_lines_store:
        #             line.remove()
        #         self.vertical_lines_position.clear()
        #         self.vertical_lines_store.clear()
        
        # self.replot_idle()
        self._draw_flag = False

        self.update_partly(is_single_click = click_type>0)

   
    def _handle_intersection_points_text(self,click_type:int):
        xlim = self.ax.get_xlim()
        if self.__current_x_position < xlim[0] or self.__current_x_position > xlim[1]:
            self.__hide_intersection_points()
        else:
            self.__draw_intersection_points(click_type)

    def update_vertical_line(self):
        """更新竖直红线（当坐标轴范围变化时调用）"""
        if self.vertical_line is not None:
            # 确保红线在当前视图范围内可见
            xlim = self.ax.get_xlim()
            if self.__current_x_position < xlim[0] or self.__current_x_position > xlim[1]:
                # 如果红线超出当前视图范围，暂时隐藏它
                self.vertical_line.set_visible(False)
            else:
                self.vertical_line.set_visible(True)
     
    
    def dragEnterEvent(self, event:QDragEnterEvent):
        """处理拖拽进入事件"""
        if event.mimeData().hasText() and (event.mimeData().hasFormat("application/data-key") or event.mimeData().hasFormat("application/data-usrkey")):
            event.acceptProposedAction()
        else:
            event.ignore()
        super().dragEnterEvent(event)
    
    def dragMoveEvent(self, event:QDragMoveEvent):
        """处理拖拽移动事件"""
        if event.mimeData().hasText() and (event.mimeData().hasFormat("application/data-key") or event.mimeData().hasFormat("application/data-usrkey")):
            event.acceptProposedAction()
        else:
            event.ignore()
        super().dragMoveEvent(event)


    def dropEvent(self, event:QDropEvent):
        """处理拖拽释放事件"""
        if event.mimeData().hasFormat("application/data-key")  :
            # 从MIME数据中获取数据键
            data_key = event.mimeData().data("application/data-key").data().decode('utf-8')

            if self.is_already_has_this_line(data_key):
                print(f"数据 {data_key} 已拖入")
                return

            self._plot_by_data_key(data_key)
            
        elif event.mimeData().hasFormat("application/data-usrkey"):

            data_key = event.mimeData().data("application/data-usrkey").data().decode('utf-8')
            if self.is_already_has_this_line(data_key):
                print(f"数据 {data_key} 已拖入")
                return
            self._plot_by_data_key(data_key)
            self.__is_has_usr_define_line =  True

        elif event.mimeData().hasFormat("application/data-keys"):
            data_keys = MplPlotWidget.decode_mime_data(event.mimeData())
            for data_key in data_keys:
                if self.is_already_has_this_line(data_key):
                    print(f"数据 {data_key} 已拖入")
                    return
            self._plot_by_data_keys(data_keys)
            
        elif event.mimeData().hasText():
            data_name = event.mimeData().text()
            print(f"接收到文本数据: {data_name}")
        else:
            print("不支持的数据格式")
        
        event.acceptProposedAction()

        super().dropEvent(event)


    def _plot_by_data_key(self,data_key:str):
        
        result =self._rcd_data_bridge.request_data_by_head_name(data_key)
        if result is None:
            return print(f"数据 {data_key} 获取失败")

        x_data, y_data = result
        # 从数据映射中获取数据

        if len(x_data) > 0 and len(y_data) > 0:
            
            color = self.select_color()
            head_data_name = data_key
            # 绘制数据
            self.plot(x_data, y_data, label=head_data_name, color=color)
            self.move_slider_by_idx(0)
            self.replot_idle()
            self.update_partly(False)
            print(f"成功将数据 {head_data_name} 拖拽到图表 {self._name}")
        else:
            print(f"数据 {head_data_name} 为空")
        

    def _plot_by_data_keys(self, data_keys, ax_vice_en: bool = False):
        """按表头批量绘图。ax_vice_en=True 时整批画在右侧副轴（主副轴合并图用）。"""
       
        result =self._rcd_data_bridge.request_datas_by_head_names(data_keys)
        if result is None:
            return print(f"数据 {data_keys} 获取失败")
       
        self._plot_muiti_lines_flag = True
        for i,xy_data in enumerate(result):
            x_data, y_data = xy_data
            data_key = data_keys[i]
            # 从数据映射中获取数据
            if i == len(result)-1:
                self._plot_muiti_lines_flag = False

            if len(x_data) > 0 and len(y_data) > 0:
                
                color = self.select_color()
                head_data_name = data_key
                # 绘制数据
                self.plot(x_data, y_data, label=head_data_name, color=color,
                          ax_vice_en=ax_vice_en)
                print(f"成功将数据 {head_data_name} 拖拽到图表 {self._name}")
            else:
                print(f"数据 {head_data_name} 为空")
            
        self.move_slider_by_idx(0)
        self.replot_idle()
        self.update_partly(False)
    
    def check_scrolling(self):
        """没有检测到滚轮滚动时调用"""
        self.change_xaxis_labels_by_format()#播放状态下内部不执行
        self.check_scroll_timer.stop()
        QTimer.singleShot(100, self.replot_when_quit_view_change)
    

    def on_scroll(self, event:MouseEvent):
        """处理滚轮事件，实现以鼠标所在点为中心的缩放"""
        if not event.inaxes:
            return
        self.check_scroll_timer.stop()
        self.check_scroll_timer.start(200)
        self.is_scrolling =True
        #停止静态背景更新模式
        self.update_partly(False)
        self.do_when_entry_view_change()
        

        # 添加防抖机制，避免频繁更新
        if hasattr(self, '_last_scroll_change_time'):
            current_time = time.time()
            if current_time - self._last_scroll_change_time < 0.01:  # 10ms防抖
               
                return
            self._last_scroll_change_time = current_time
        else:
            setattr(self,'_last_scroll_change_time',time.time())


        # 获取当前坐标轴范围
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()
      
        
        # 获取鼠标在数据坐标中的位置
        xdata = event.xdata
        ydata = event.ydata
        
        if xdata is None or ydata is None:
            return

        if event.button == 'up':
            # 滚轮上滚 - 放大
            scale_factor = 1.0 / self.zoom_factor
            
        elif event.button == 'down':
            # 滚轮下滚 - 缩小
            
            if  (global_config.scroll_x_enable and global_config.scroll_y_enable):
                
                if self.initial_xlim[0]>=xlim[0] or self.initial_xlim[1]<=xlim[1] or \
                    self.initial_ylim[0]>=ylim[0] or self.initial_ylim[1]<=ylim[1]:
            
                    self.restore_initial_lim()
                    return
            scale_factor = self.zoom_factor
        else:
            return
        
        # 正确的以鼠标位置为中心的缩放算法
        # 计算鼠标位置相对于当前视图的比例
        # 以鼠标位置为中心计算新的边界
        # 设置新的坐标轴范围
        # 计算新的坐标轴范围
        if global_config.scroll_y_enable:
            y_frac = (ydata - ylim[0]) / (ylim[1] - ylim[0])
            y_range = ylim[1] - ylim[0]
            new_y_range = y_range * scale_factor
            new_ylim = (ydata - y_frac * new_y_range, ydata + (1 - y_frac) * new_y_range)
           
            self.set_ylim(new_ylim)

       
        if global_config.scroll_x_enable :
            x_frac = (xdata - xlim[0]) / (xlim[1] - xlim[0])
            x_range = xlim[1] - xlim[0]
            new_x_range = x_range * scale_factor
            new_xlim = (xdata - x_frac * new_x_range, xdata + (1 - x_frac) * new_x_range)
            
            self.set_xlim(new_xlim)
                       
        # 更新竖直红线
        self.update_vertical_line()
    
        # 重绘图表
        self.replot_idle()

    def sync_x_axis_with_other_plot(self,new_xlim):
        if  not global_config.sync_x_axis:
            return
       
        self._mouse_data = None
        global_config.mouse_data = None
        
        self.check_scroll_timer.stop()
        self.check_scroll_timer.start(200)
        self.is_scrolling =True
        #停止静态背景更新模式
        self.update_partly(False)
        self.do_when_entry_view_change()

        self.ax.set_xlim(new_xlim)
       
        self.update_vertical_line()
    
        # 重绘图表
        self.replot_idle()

   
    def select_color(self):
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', 
                        '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        color = colors[self.color_index]
        self.color_index+=1
        if self.color_index>9:
            self.color_index=0
        return color
    

    def on_key_press(self, event:KeyEvent):
        """键盘事件处理"""
        if event.key  == 'control':
            self.CTRL_pressed =True
           
            # global_config.change_scroll_mode(True,False)
        elif event.key  == 'shift':
            self.SHIFT_pressed = True

            if global_config.scroll_x_enable and global_config.scroll_y_enable:
                global_config.change_scroll_mode(True,False)
            elif global_config.scroll_x_enable:
                global_config.change_scroll_mode(False,True)
            elif global_config.scroll_y_enable:
                global_config.change_scroll_mode(True,True)
       
            
    def on_key_release(self, event:KeyEvent):
        
        if event.key  == 'control':
            self.CTRL_pressed =False
          
        elif event.key  == 'shift':
            self.SHIFT_pressed = False
                  
        
    def on_measure_ruler_mode_off(self):
        if not self.measure_tool.add_success():
            self.measure_tool.remove_current_head_point()

    def on_button_press(self, event:MouseEvent):
        """鼠标按下事件 - 开始框选或平移"""
        if event.button == MouseButton.LEFT and event.inaxes:  # 左键按下且在坐标轴内
            if global_config.measure_ruler_mode:
                if self.background is None:
                    self.update_partly()
                if self.measure_tool.add_success():
                    self.measure_tool.add_headpoint(event.xdata,event.ydata)
                    print("add head")
                else:
                    self.measure_tool.add_endpoint(event.xdata,event.ydata)
                    print("add end")
                self.update_partly()
            else:
                # 检查是否按下了CTRL键 - 使用Qt的键盘状态检查
                modifiers = QApplication.keyboardModifiers()
                if modifiers == Qt.ControlModifier:
                    # 开始框选
                    self.zoom_start = (event.xdata, event.ydata)
                    self.is_zooming = True
                    
                    self.update_partly(False)
                else:
                    # 开始平移
                    self.is_panning = True
                    self.update_partly(False)
                    self.do_when_entry_view_change()
                    self.pan_start = (event.x, event.y)
                    self.last_pan_position = (event.x, event.y)
                    self.pan_start_xlim = self.get_xlim()
                    self.pan_start_ylim = self.get_ylim()

        elif event.button == MouseButton.RIGHT and event.inaxes:  # 右键按下且在坐标轴内
            """右键缩放功能"""
            self.mouse_right_pressed = True
            QTimer.singleShot(300, lambda :self.check_right_button(event.xdata,event.ydata))
            

    def check_right_button(self,x:float,y:float):

        if self.mouse_right_pressed:
            
            self.zoom_by_right_mouse_start = (x, y)
            self.zoom_by_right_mouse_start_cursor = self.cursor().pos()
            self.xlim_when_zoom_start = self.get_xlim()
            self.ylim_when_zoom_start = self.get_ylim()
            self.is_zooming_by_right_mouse = True
            # self.update_partly(False)
    
    def on_button_release(self, event:MouseEvent):
        """鼠标释放事件 - 结束框选或平移"""
        if event.button == MouseButton.LEFT:
            if self.is_zooming and event.inaxes:
                self.zoom_end = (event.xdata, event.ydata)
                self.is_zooming = False
               
                # 清除框选矩形
                if self.zoom_rect:
                    self.zoom_rect.remove()
                    self.zoom_rect = None
                
                # 计算框选区域
                x1, y1 = self.zoom_start
                x2, y2 = self.zoom_end

                # 确保坐标正确（左上角到右下角）
                xmin = min(x1, x2)

                xmax = max(x1, x2)
                ymin = min(y1, y2)
                ymax = max(y1, y2)
                
                # 只有当框选区域足够大时才应用缩放
                if abs(xmax - xmin) > 0.01 and abs(ymax - ymin) > 0.01:
                  
                    self.set_xlim((xmin, xmax))
                    self.set_ylim((ymin, ymax))
                    self.update_vertical_line()

                    self.change_xaxis_labels_by_format()
                    self.replot()
                else:
                    self.update_vertical_line()
                    self.replot()
                
                self.on_leave_zooming()

            elif self.is_panning:
                # 结束平移
                self.pan_start = None
                self.pan_start_xlim = None
                self.pan_start_ylim = None
                if not self.is_zooming and not self.is_scrolling and not self.is_zooming_by_right_mouse:
                    self.change_xaxis_labels_by_format()
                
                QTimer.singleShot(100, self.replot_when_quit_view_change)


        elif event.button == MouseButton.RIGHT:#鼠标右击
            self.mouse_right_pressed = False
            if not self.is_zooming_by_right_mouse:
                if self.CTRL_pressed:
                    
                    x,_ = self.intersection_textbox_now.get_position()
                    y   = event.ydata
                    self.intersection_textbox_now.set_position((x,y))
                    if len(self.label_infos)>0:
                        x,_,label= self.label_infos[-1]
                        self.label_infos[-1] =(x,y,label)
                    
                    self.replot_idle()
                    self.update_partly(False)
                    return
                x_data = self._rcd_data_bridge.xdata_rcd()
              
                if x_data is None:
                    return
                if x_data.any() and event.xdata:
                    pos = (event.x, event.y)
                    # 将像素差值转换为数据坐标
                    trans = self.ax.transData.inverted()
                    mouse_data = trans.transform(pos)
                    idx = np.argmin(np.abs(x_data - int(mouse_data[0])))
                    global_config.ask_slider_change(x_data[idx],idx,self._location,2)
            else:
                if self.is_zooming_by_right_mouse:
                  
                    self.zoom_by_right_mouse_start = None
                    self.zoom_by_right_mouse_start_cursor = None
                    self.xlim_when_zoom_start = None
                    self.ylim_when_zoom_start = None
                if not self.is_zooming and not self.is_scrolling and not self.is_panning:
                    self.change_xaxis_labels_by_format()
                QTimer.singleShot(100, self.replot_when_quit_view_change)


    def handle_zooming_by_right_mouse(self,is_in_canvas = True):
        if is_in_canvas:
            self.check_mouse_move_Timer.stop()

        self.update_partly(False)
        self.do_when_entry_view_change()

        if self.zoom_by_right_mouse_start_cursor:
            dpos =     self.cursor().pos() - self.zoom_by_right_mouse_start_cursor
        else:
            return
        dx_pixel =  -dpos.x()
        dy_pixel =   dpos.y()
       
        if dx_pixel  >0:
            x_frac = min(10,dx_pixel/30 +1)
        elif dx_pixel<0:
            x_frac =  max(0.01,(300 +dx_pixel)/300 if dx_pixel > -300 else 0.01)
        else:
            x_frac = 1

        if dy_pixel  >0:
            y_frac = min(10,dy_pixel/30 +1)
        elif dy_pixel<0:
            y_frac =   max(0.01,(300 +dy_pixel)/300 if dy_pixel> -300  else 0.01)
        else:
            y_frac = 1


        new_xlim=( self.zoom_by_right_mouse_start[0]- (self.zoom_by_right_mouse_start[0]-self.xlim_when_zoom_start[0])* x_frac,
                  self.zoom_by_right_mouse_start[0]+ (-self.zoom_by_right_mouse_start[0]+self.xlim_when_zoom_start[1])* x_frac)
        new_ylim=( self.zoom_by_right_mouse_start[1]- (self.zoom_by_right_mouse_start[1]-self.ylim_when_zoom_start[0])* y_frac,
                  self.zoom_by_right_mouse_start[1]+ (-self.zoom_by_right_mouse_start[1]+self.ylim_when_zoom_start[1])* y_frac)


        self.set_xlim(new_xlim)
        self.set_ylim(new_ylim)
        self.replot_idle()


    def move_forward_1_step(self):
        if not self.lines :
            return
        x_data = self._rcd_data_bridge.xdata_rcd()
        current = self.current_x_idx()
        target_max = self.target_x_idx()
        target = current + 1 if global_config.play_speed == PlaySpeed.STEP else current + 100
        if target>target_max:
            target = current
        global_config.ask_slider_change(x_data[target],target,self._location,1)

    def move_backward_1_step(self):
        if not self.lines :
            return
        x_data = self._rcd_data_bridge.xdata_rcd()
        current = self.current_x_idx()
        target_min = self.target_x_idx(False)
        target = current - 1 if global_config.play_speed == PlaySpeed.STEP else current - 100
        if target<target_min:
            target = current
        global_config.ask_slider_change(x_data[target],target,self._location,1)

    def move_to_next_search_point(self,logic_search_result_datas:List[int]):
        
        current = self.current_x_idx()
        x_data = self._rcd_data_bridge.xdata_rcd()
        if current< len(logic_search_result_datas)-1:
            data_last = logic_search_result_datas[current+1]
        else:
            return
       
        for idx ,data in enumerate(logic_search_result_datas[current+1:]):
            if data == 1 and data_last==0:
                target = idx + current+1
                return global_config.ask_slider_change(x_data[target],target,self._location,1)
            if data == 0 and data_last==1:
                target = idx-1 + current+1
                return global_config.ask_slider_change(x_data[target],target,self._location,1)
            data_last = data


    def on_motion_notify(self, event:MouseEvent):
        """鼠标移动事件 - 绘制框选矩形或处理平移"""
        if event.inaxes :
            
            self._mouse_data =(event.xdata, event.ydata)
            global_config.mouse_data = (event.x, event.y )

            if event.button == 1 and not self.SHIFT_pressed:
                # 添加防抖机制，避免频繁更新
                if hasattr(self, '_last_zoom_pan_change_time'):
                    current_time = time.time()
                    if current_time - self._last_zoom_pan_change_time < 0.01:  # 50ms防抖
                        return
                    self._last_zoom_pan_change_time = current_time
                else:
                    setattr(self,'_last_zoom_pan_change_time',time.time())
                if self.is_zooming :
                    # 清除之前的矩形
                    if self.zoom_rect:
                        self.zoom_rect.remove()
                        self.zoom_rect = None
                    
                    # 计算矩形位置和大小
                    x1, y1 = self.zoom_start
                    x2, y2 = event.xdata, event.ydata
                    
                    width = abs(x2 - x1)
                    height = abs(y2 - y1)
                    x = min(x1, x2)
                    y = min(y1, y2)
                    
                    # 绘制新的矩形
                    self.zoom_rect = Rectangle((x, y), width, height, 
                                            fill=False, edgecolor='black', linewidth=1, linestyle='--')
                    self.ax.add_patch(self.zoom_rect)

                    # 更新竖直红线
                    self.update_vertical_line()
                    self.replot_idle()
                

                elif self.is_panning :
                    # 处理平移
                    if self.pan_start and self.pan_start_xlim and self.pan_start_ylim:
                        # 使用基于像素坐标的平移方法，避免抖动
                        if self.last_pan_position:
                            # 计算像素坐标的差值
                            dx_pixel = self.last_pan_position[0] - event.x
                            dy_pixel = self.last_pan_position[1] - event.y
                        else:
                            # 第一次移动，使用起始位置计算
                            dx_pixel = self.pan_start[0] - event.x
                            dy_pixel = self.pan_start[1] - event.y
                        
                        # 更新上一次位置（使用像素坐标）
                        self.last_pan_position = (event.x, event.y)
                        
                        # 获取当前坐标轴范围
                        current_xlim = self.get_xlim()
                        current_ylim = self.get_ylim()
                        
                        # 将像素差值转换为数据坐标差值
                        # 使用坐标轴变换来计算数据坐标的偏移量
                        trans = self.ax.transData.inverted()
                        point1 = trans.transform((0, 0))
                        point2 = trans.transform((dx_pixel, dy_pixel))
                        
                        dx_data = point2[0] - point1[0]
                        dy_data = point2[1] - point1[1]
                        
                        # 计算新的坐标轴范围
                        new_xlim = (current_xlim[0] + dx_data, current_xlim[1] + dx_data)
                        new_ylim = (current_ylim[0] + dy_data, current_ylim[1] + dy_data)
                        

                        self.set_xlim(new_xlim)
                        self.set_ylim(new_ylim)
                        
                        # 更新竖直红线
                        self.update_partly(False)
                        self.update_vertical_line()
                        
                        self.replot_idle()
            elif event.button == 3:
                if self.is_zooming_by_right_mouse:
                    self.handle_zooming_by_right_mouse()
            
    
    def __draw_intersection_points(self,click_type:int):
        """绘制竖直红线与曲线的交点"""
       
        self.__hide_intersection_points()
        
        # 存储交点y值
        intersection_point_info:List[Tuple[float,str,str]] = []

        x_data = self._rcd_data_bridge.xdata_rcd()[self.__idx_min:self.__idx_max+1]
        # 计算每条曲线与竖直红线的交点
        for i, line in enumerate(self.lines):
            if self.lines_visionable_flag[i] == False:
                continue
             
            line_name ,color= self.lineKeys_lineColors[i]
            y_data = self._rcd_data_bridge.get_one_data_saved_in_bridge(line_name)[1][self.__idx_min:self.__idx_max+1]
            y_min,y_max = self.get_ylim()
        
            # 找到最接近竖直红线位置的x值
            idx = np.argmin(np.abs(x_data - self.__current_x_position))
       

            # 如果找到的交点在数据范围内
            if 0 <= idx < len(x_data):
                x_intersect = x_data[idx]
                y_intersect = y_data[idx]
                if  y_min<y_intersect<y_max:
                    # 绘制交点标记
                    point = self.ax.plot(x_intersect, y_intersect, 'ro', markersize=3, 
                                    markeredgecolor=color, markerfacecolor='yellow')[0]
                    self.intersection_points.append(point)
                    intersection_point_info.append((y_intersect,line_name,color))
           
        # 如果有交点，显示文本框
        if intersection_point_info:
            if  global_config.is_playing :
                self.__show_intersection_textbox(intersection_point_info,0)
            else:
                self.__show_intersection_textbox(sorted(intersection_point_info, key=lambda x: x[0], reverse=True),click_type )
        else:
            self.__hide_intersection_textbox()

    def __show_intersection_textbox(self, info:List[Tuple[float,str,str]], click_type:int): #info--->(交点y值，曲线名,颜色)
        """显示交点y值的文本框"""
        # 清除之前的文本框
        
        self.__hide_intersection_textbox()
        # 计算文本框位置
        x_position = self.__current_x_position
        if global_config.is_playing:
            y_min, y_max = self.get_ylim()
            
        else:
            y_min = min(map(lambda x: x[0], info))
            y_max = max(map(lambda x: x[0], info))
       
        if click_type <= 1 :
            text_posi_y = (y_min + y_max) / 2
        else:
            # if self._mouse_data:
            #     text_posi_y = self._mouse_data[1]
            # else:
            #     text_posi_y = (y_min + y_max) / 2
            if click_type == 2:
                if self._mouse_data:
                    text_posi_y = self._mouse_data[1]
                else:
                    text_posi_y = (y_min + y_max) / 2
            elif  click_type == 3:
                if global_config.mouse_data:
                    trans = self.ax.transData.inverted()
                    point =trans.transform(global_config.mouse_data)
                    text_posi_y =  point[1]
                else:
                    text_posi_y = (y_min + y_max) / 2

        # 设置文本框的x位置在竖直线右侧
        xlim = self.ax.get_xlim()
        text_posi_x = x_position + (xlim[1] - xlim[0]) * 0.02  # 竖直线右侧2%的位置

        current_x_data = self.__current_x_position
        if global_config.xData_format == xLabelFormat.DT:
            #元素数据是毫秒时间戳  int
            timestamp = current_x_data + self._rcd_data_bridge.base_timestamp()  #  
            current_x_data_str =  datetime_from_timestamp(float(timestamp)/1000.0)
        else:
            # current_x_data_str =  str(float(current_x_data)/1000.0) + "s"
            current_x_data_str =  f'{(float(current_x_data)/1000.0):.3f}s'

        context =current_x_data_str+"\n"
        title_var:List[Tuple[str,str]] = []
        for i, _info in enumerate(info):
            title_tr = self._rcd_translater.translate_title(_info[1])
            if title_tr: 
                title =_info[1] + "(" + title_tr +")" 
            else:
                title =_info[1]
            
            var_tr = self._rcd_translater.translate_data(_info[1],_info[0])
            if  var_tr:
                var = var_tr + "(" + MplPlotWidget.to_hex_string(_info[0]) +")"
            else:
                var_str = str(_info[0]) if isinstance(_info[0],np.int64) else f"{_info[0]:.2f}"
                var = var_str + "(" + MplPlotWidget.to_hex_string(_info[0]) +")"
           
            title_var.append((title,var))

        max_text_len = 0
        for title_var_turple in title_var:
            length =get_display_width(title_var_turple[0])+get_display_width(title_var_turple[1])
            if length>max_text_len:
                max_text_len = length

        for i, title_var_turple in enumerate(title_var):
            head,tail = title_var_turple
            if i< len(title_var)-1:
                context += MplPlotWidget.contact_context(head,tail,max_text_len)+"\n"
            else:
                context += MplPlotWidget.contact_context(head,tail,max_text_len)

        textbox = self.ax.text(text_posi_x, text_posi_y, context, 
                            bbox=dict(boxstyle="round,pad=0.3", 
                                    facecolor="lightyellow", 
                                    alpha=0.8, 
                                    edgecolor="black"),
                                    fontsize=self.fontsize,
                                    verticalalignment='center',
                                    weight='bold',zorder=3, clip_on=True)
        self.intersection_textbox_now = textbox

        # 获取文本框的渲染器来计算宽度
        renderer = self.canvas.get_renderer()
        bbox = textbox.get_window_extent(renderer)
        # box_width = bbox.width / self.figure.dpi  # 转换为英寸
        # 将像素宽度转换为数据坐标宽度
        trans = self.ax.transData.inverted()
        point1 = trans.transform((0, 0))
        point2 = trans.transform((bbox.width, 0))
        box_width_data = point2[0] - point1[0]
        
        if text_posi_x + box_width_data > xlim[1]:
            text_posi_x = x_position - (xlim[1] - xlim[0]) * 0.02 - box_width_data
            textbox.set_position((text_posi_x,text_posi_y))
        textbox.set_visible(True)
        
    
    def __hide_intersection_textbox(self):
        """隐藏交点文本框"""
        if self.intersection_textbox_now is not None:
            self.intersection_textbox_now.remove()
            self.intersection_textbox_now  = None

    def __hide_multi_textboxs(self):
        if len(self.intersection_textboxs_store)>0:
            for textbox in self.intersection_textboxs_store:
                textbox.remove()
            self.label_infos.clear()
            self.intersection_textboxs_store.clear()    

    def __hide_intersection_points(self):
        """隐藏交点标记"""
        if hasattr(self, 'intersection_points'):
            for point in self.intersection_points:
                point.remove()
            self.intersection_points = []
    
    def __hide_multi_vertical_lines(self):
        if len(self.vertical_lines_store)>0:
            for line in self.vertical_lines_store:
                line.remove()
            self.vertical_lines_position.clear()
            self.vertical_lines_store.clear()

    def save_latest_textbox(self):
        if self.intersection_textbox_now:
            context = copy.deepcopy(self.intersection_textbox_now.get_text())
            x,y = self.intersection_textbox_now.get_position()
            self.label_infos.append((x,y,context))
            # [int, int]
            x = self.vertical_line.get_xdata()[0]
            self.vertical_lines_position.append(x)
                
            
            x,y,text =    self.label_infos[-1]  #[ , ,_, ,]
            textbox = self.ax.text(x, y, text, 
                        bbox=dict(boxstyle="round,pad=0.3", 
                                facecolor="lightyellow", 
                                alpha=0.8, 
                                edgecolor="black"),
                        fontsize=self.fontsize,
                        verticalalignment='center',
                        weight='bold',zorder=3, clip_on=True)
            
            self.intersection_textboxs_store.append(textbox)
            textbox.set_visible(True)

            x_position = self.vertical_lines_position[-1]
            line = self.ax.axvline(x=x_position, color='red', linewidth=0.4, linestyle='--',zorder=1)
            self.vertical_lines_store.append(line)
            line.set_visible(True)

            self.__hide_intersection_textbox()        
    
    def on_leave_zooming(self):
        """退出缩放时调整textbox的位置"""
        xlim = self.get_xlim()
        if self.intersection_textbox_now:
            _,y= self.intersection_textbox_now.get_position()
            text_posi_x = self.__current_x_position + (xlim[1] - xlim[0]) * 0.02  # 竖直线右侧2%的位置
            self.intersection_textbox_now.set_position((text_posi_x,y))
        for i, textbox in  enumerate(self.intersection_textboxs_store):# [tb2,tb1]
            x = self.vertical_lines_position[i]                               #   [p2 ,p1 ,p0]
            _,y= textbox.get_position()
            text_posi_x = x + (xlim[1] - xlim[0]) * 0.02  
            textbox.set_position((text_posi_x,y))
    

    def set_xaxis_label_rotation(self, rotation=0):
        """设置X轴标签旋转角度
        
        Args:
            rotation: 旋转角度（度）
        """
        # 设置x轴标签旋转
        for label in self.ax.get_xticklabels():
            label.set_rotation(rotation)
        
    
    # @time_it
    def change_xaxis_labels_by_format(self,draw_rignt_now:bool=False):
        """根据格式改变X坐标的标签"""

        if not self.lines or self._plot_muiti_lines_flag:
            return
        if global_config.is_playing:
            return
            
        xticks_labels_format = global_config.xData_format
        xticks = self.ax.get_xticks()
        base_timestamp = self._rcd_data_bridge.base_timestamp()
        if xticks.min()+base_timestamp<0:
            return
        
        # 缓存机制：如果刻度没有变化，跳过更新
        if hasattr(self, '_last_xticks') and np.array_equal(xticks, self._last_xticks):
            if hasattr(self, '_last_format') and self._last_format == xticks_labels_format:
                return

        self._last_xticks = xticks.copy()
        self._last_format = xticks_labels_format
        # setattr(self,"_last_xticks",xticks.copy())
        
        if xticks_labels_format == xLabelFormat.DT:
            # 使用列表推导式替代 np.vectorize，性能更好
            # base_timestamp = self._rcd_data_bridge.base_timestamp()
            xticks_labels = [datetime_from_timestamp_for_xAxis((x + base_timestamp) / 1000.0) for x in xticks]
           
            rotation = 5
        else:
            # 使用更高效的格式化方法
            xticks_labels = [f"{x/1000.0:.2f}" for x in xticks]
            rotation = 0
        
        # 批量设置刻度标签
        self.ax.set_xticklabels(xticks_labels)
        self.set_xaxis_label_rotation(rotation)
        if draw_rignt_now:
            self.replot()
    
    def clear_labels(self):
        """切换标签模式后清除标签"""
        self.__hide_intersection_textbox()
        self.__hide_multi_textboxs()
        self.__hide_intersection_points()
        self.__hide_multi_vertical_lines()
        
        self.replot()
        self.update_partly(False)
    

    def set_if_show_grid(self):
        # 重新设置样式
        self.set_grid()
        self.replot_idle()
        self.update_partly(False)
        
    def is_paning_or_scrolling(self):
        return self.is_panning or self.is_scrolling
    
    def is_paning_or_scrolling_or_zooming(self):
        return self.is_panning or self.is_scrolling or self.is_zooming

    def timestamp_to_datetime(self,ms_stamp):
        # xdata = self._map_datas.get_xdata()
        timestamp = ms_stamp + self._rcd_data_bridge.base_timestamp()  #  
        return datetime_from_timestamp(float(timestamp)/1000.0)
    
    def timestamp_to_datetime_for_xAxis(self,ms_stamp):
        timestamp = ms_stamp + self._rcd_data_bridge.base_timestamp()  #  
        return datetime_from_timestamp_for_xAxis(float(timestamp)/1000.0)


