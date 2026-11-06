from PySide6.QtCore import Signal,QObject
from .common import xLabelFormat
from typing import Tuple, Optional

from enum import Enum

class PlaySpeed(Enum):
    STEP=0
    NORMAL=1


class GlobalConfigSingleton(QObject):
    _instance = None
    askSliderChange = Signal(int,tuple,int) 
    play_mode_change = Signal(bool)
    translate_mode_change = Signal(bool)
    update_rcd_panel_data = Signal(int)
    logic_search_result_display  = Signal(int)
    off_row_data_read    = Signal()
    on_off_row_data_read    = Signal(bool)
    rcdPanelValueShowSignalChange = Signal()
    measure_ruler_mode_off = Signal()
    measure_ruler_done = Signal()
    scroll_mode_change =  Signal()
    # 主副轴合并图里「主」「副」按钮切换时发出，窗口据此批量显隐两组曲线
    axis_visibility_change = Signal()
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        # 配置项
        self.xData_format = xLabelFormat.DT
        self.show_grid    = True
        self.multi_label = False
        self.multi_label_last = False
        self.show_rcd_helping_text_on_panel = True
        self.is_playing = False
        self.play_speed =PlaySpeed.STEP
        self.show_rcd_panel_values_en = False
        self.measure_ruler_mode = False

        self.scroll_x_enable = True
        self.scroll_y_enable = True
        self.sync_x_axis     = False

        self.major_axis_en = True
        self.vice_axis_en  = True

        self.mouse_data:Optional[Tuple[float,float]] = None

    def enable_play_mode(self,enable):
        self.is_playing = enable
        self.play_mode_change.emit(enable)
        print(f"isPlaying = {self.is_playing}")
        
    def set_xData_format(self,format:xLabelFormat):
        self.xData_format = format
    def show_grid_enable(self,enable:bool):
        self.show_grid    = enable
    def enable_multi_label(self,enable:bool):
        self.multi_label_last = self.multi_label
        self.multi_label    = enable
        
    def change_tr_mode(self):
        self.show_rcd_helping_text_on_panel = not self.show_rcd_helping_text_on_panel
        self.translate_mode_change.emit(self.show_rcd_helping_text_on_panel)

    def ask_slider_change(self,x_val:int,idx:int,plot_location:Tuple[int,int],click_type:int=0):
        """click_type  0：  2：mouse   1：key"""
        self.askSliderChange.emit(x_val,plot_location,click_type)
        self.update_rcd_panel_data.emit(idx)
        self.logic_search_result_display.emit(idx)
        
    def update_panel_data(self,idx):
        self.update_rcd_panel_data.emit(idx)
    
    def change_play_speed(self):
        self.play_speed = PlaySpeed.NORMAL if self.play_speed==PlaySpeed.STEP else PlaySpeed.STEP
    
    def measure_ruler_en(self,enable):
        self.measure_ruler_mode = enable
        if not enable:
            #关闭的时候若是没有画完第2个点需要清除第1个点
            self.measure_ruler_mode_off.emit()
    
    def sync_x_axis_en(self,enable):
        self.sync_x_axis = enable
        if not enable:
            pass
    def enable_show_rcd_panel_values(self,en:bool):
        self.show_rcd_panel_values_en = en
        self.rcdPanelValueShowSignalChange.emit()
        if not self.show_rcd_panel_values_en:
            self.off_row_data_read.emit()
        self.on_off_row_data_read.emit(en)
        print(f"是否开启rcd数据列表数据展示{"√" if self.show_rcd_panel_values_en else "×"}")
    

    def change_scroll_mode(self,x_en,y_en):
        
        if self.scroll_x_enable!=x_en or self.scroll_y_enable!=y_en:
            self.scroll_x_enable = x_en
            self.scroll_y_enable = y_en
            self.scroll_mode_change.emit()

    def set_axis_visible(self, major: bool, vice: bool):
        """设置主/副轴曲线是否可见，并通知所有主副轴合并窗口刷新。"""
        self.major_axis_en = bool(major)
        self.vice_axis_en = bool(vice)
        self.axis_visibility_change.emit()

    
# 创建全局单例实例
global_config = GlobalConfigSingleton()

