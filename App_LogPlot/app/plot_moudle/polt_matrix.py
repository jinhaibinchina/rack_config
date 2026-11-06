from __future__ import annotations
from PySide6.QtWidgets import ( QWidget, 
                            QGridLayout)
from PySide6.QtCore import Signal, Slot

from .common import rcd_data_bridge
from .mat_plot import MplPlotWidget
from typing import Dict, Optional, List,Tuple,TYPE_CHECKING
from .translater import rcd_translater
if TYPE_CHECKING:
    from .tabbed_plot_widget import TabbedPlotWidget

class PlotMatrix(QWidget):
    """矩阵化图表"""
    plotAdded = Signal(object)
    undoableChange = Signal()
    @staticmethod
    def decode_mime_data(mime_data):
        if mime_data.hasFormat("application/combo-datas"):
            import json
            byte_data = mime_data.data("application/combo-datas")
            json_str = byte_data.data().decode('utf-8')
            data_heads = json.loads(json_str)
            return data_heads
        return None
    def __init__(self, name: str, data_bridge:rcd_data_bridge,rcd_translater:rcd_translater, parent:TabbedPlotWidget=None):
        super().__init__(parent)
        self._name = name
        # self._mapped_data = datamap
        self._data_bridge = data_bridge
        self._rcd_translater = rcd_translater
        self._current_row = 0
        self._current_col = 0

        # 创建网格布局
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(2)
        self.grid_layout.setContentsMargins(2, 2, 2, 2)
        
        # 存储绘图组件的二维列表
        self._plot_widgets: List[List[Optional[MplPlotWidget]]] = [[]]
        
        # 创建初始绘图区域
        self._plot_widgets[0].append(self.addPlotWidget(0, 0))
        self.grid_layout.addWidget(self._plot_widgets[0][0], 0, 0)
        self.setLayout(self.grid_layout)

        # 启用拖放功能
        self.setAcceptDrops(True)
   

    # def map_datas(self):
    #     return self._mapped_data
        
    def data_bridge(self):
        return self._data_bridge
    def translater(self):
        return self._rcd_translater

    def addPlotWidget(self, row: int, col: int) -> MplPlotWidget:
        """添加绘图组件"""
        plot_name = f"{self._name}_plot_{row}_{col}"
        location = (row,col)
        plot = MplPlotWidget(plot_name,location, self)
        plot.setMinimumSize(300, 200)
        plot.xlim_changed.connect(self.on_sync_x_update)
        return plot

    @Slot(tuple)
    def on_sync_x_update(self,val):
        location ,xlim =val
        r,w = location
        
        for row in range(self.rowsCount()):
            for col in range(self.colsCount()):
                if row == r and col == w:
                    continue
                plot = self.plotAt(row, col)
                if plot:
                    plot.sync_x_axis_with_other_plot(xlim)


    def addRow(self):
        """添加新行"""
        if self._current_row>=1:
            return
        self._current_row+=1
        new_row = len(self._plot_widgets)
        self._plot_widgets.append([])
        
        # 为新行添加列
        num_cols = len(self._plot_widgets[0]) if self._plot_widgets else 1
        for col in range(num_cols):
            plot = self.addPlotWidget(new_row, col)
            self._plot_widgets[new_row].append(plot)
            self.grid_layout.addWidget(plot, new_row, col)
        
        for row in range(self.rowsCount()):
            for col in range(self.colsCount()):
                plot = self.plotAt(row, col)
                if row == 1:
                    plot.adjust_subplots(0.995,0.06)
                else:
                    plot.adjust_subplots(bottom=0.06)

        if self.is_has_two_plot_window_in_cols():
            
            for row in range(self.rowsCount()):
                for col in range(self.colsCount()):
                    plot = self.plotAt(row, col)
                    if plot:
                        plot.reduce_font_size()
        self.undoableChange.emit()
        
    def addColumn(self):
        """添加新列"""
        if self._current_col>=1:
            return
        self._current_col+=1
        new_col = len(self._plot_widgets[0]) if self._plot_widgets else 0
        
        # 为每行添加新列
        for row in range(len(self._plot_widgets)):
            if len(self._plot_widgets[row]) <= new_col:
                self._plot_widgets[row].extend([None] * (new_col - len(self._plot_widgets[row]) + 1))
            
            plot = self.addPlotWidget(row, new_col)
            self._plot_widgets[row][new_col] = plot
            self.grid_layout.addWidget(plot, row, new_col)
        
        if self.is_has_two_plot_window_in_rows():
            for row in range(self.rowsCount()):
                for col in range(self.colsCount()):
                    plot = self.plotAt(row, col)
                    if row == 1:
                        plot.adjust_subplots(0.995,0.06)
                    else:
                        plot.adjust_subplots(bottom=0.06)

        for row in range(self.rowsCount()):
            for col in range(self.colsCount()):
                plot = self.plotAt(row, col)
                if plot:
                    plot.reduce_font_size()
        self.undoableChange.emit()

    def plotAt(self, row: int, col: int) -> Optional[MplPlotWidget]:
        """获取指定位置的绘图组件"""
        if row < len(self._plot_widgets) and col < len(self._plot_widgets[row]):
            return self._plot_widgets[row][col]
        return None
        
    def plot_data(self, row: int, col: int, x_data, y_data, label=None, color=None):
        """在指定位置绘图"""
        plot = self.plotAt(row, col)
        if plot:
            plot.plot(x_data, y_data, label=label, color=color)
            
    def clear_all(self)->bool:
        """清除所有图形"""
        
                
        
        for row in self._plot_widgets:
            for plot in row:
                if plot:
                    plot.clear()
       
                    
    def name(self):
        return self._name
        
    def rowsCount(self):
        return len(self._plot_widgets)
        
    def colsCount(self):
        """[[p,p],[p,p]]"""
        return len(self._plot_widgets[0]) if self._plot_widgets else 0
    
    def _is_only_one_plot_window(self):
        return self.rowsCount()==1 and self.colsCount()==1
    def is_plot_window_less_or_equl_than_two(self):
        return self.rowsCount()==1 or self.colsCount()==1
    
    def is_has_two_plot_window_in_cols(self):
        return self.colsCount()==2
    def is_has_two_plot_window_in_rows(self):
        return self.rowsCount()==2
    
    def is_plot_window_operating(self):
        """判断图表是否在被操作，如果是，需要退出播放模式"""
        for row in range(self.rowsCount()):
            for col in range(self.colsCount()):
                plot = self.plotAt(row, col)
                if plot:
                    if  plot.is_paning_or_scrolling_or_zooming():
                        return True
        return False


    def head_names_in_solo_plot_window(self):
        if not self._is_only_one_plot_window():
            return None
        plot = self._plot_widgets[0][0]
        return plot.data_head_names_without_usr_data_lst() 
    
    def get_head_names_without_usr_data_in_plot(self,row:int,col:int):
        plot = self.plotAt(row,col)
        if not plot:
            return None
        return plot.data_head_names_without_usr_data_lst()
    
    def get_head_names_in_plot(self,row:int,col:int):
        plot = self.plotAt(row,col)
        if not plot:
            return None
        return plot.data_head_names_lst()
    
    def solo_plot_widget(self):
        if self._is_only_one_plot_window():
            return self._plot_widgets[0][0]
        return None

    def first_plot_widget(self):
        return self._plot_widgets[0][0]

    def mouseMoveEvent(self, event):
        """鼠标移动事件处理"""
    
        super().enterEvent(event)


    def set_if_show_grid(self):
        for row in range(self.rowsCount()):
            for col in range(self.colsCount()):
                plot = self.plotAt(row, col)
                if plot:
                    plot.set_if_show_grid()

    def delete_lines(self, row=None, col=None):
        if row is not None and col is not None:
            # 应用到指定位置的绘图组件
            plot = self.plotAt(row, col)
            if plot:
                plot.clear()
        elif row is not None:
            # 应用到指定行的所有绘图组件
            for col in range(self.colsCount()):
                plot = self.plotAt(row, col)
                if plot:
                    plot.clear()
        elif col is not None:
            # 应用到指定列的所有绘图组件
            for row in range(self.rowsCount()):
                plot = self.plotAt(row, col)
                if plot:
                    plot.clear()
        else:
            # 应用到所有绘图组件
            for row in range(self.rowsCount()):
                for col in range(self.colsCount()):
                    plot = self.plotAt(row, col)
                    if plot:
                        plot.clear()

    def clear_tip_labels(self):
        for row in range(self.rowsCount()):
            for col in range(self.colsCount()):
                plot = self.plotAt(row, col)
                if plot:
                    plot.clear_labels()
    

    def set_xaxis_labels_by_format(self, row=None, col=None):
        if row is not None and col is not None:
            # 应用到指定位置的绘图组件
            plot = self.plotAt(row, col)
            if plot:
                plot.change_xaxis_labels_by_format(True)
                
        elif row is not None:
            # 应用到指定行的所有绘图组件
            for col in range(self.colsCount()):
                plot = self.plotAt(row, col)
                if plot:
                    plot.change_xaxis_labels_by_format(True)
        elif col is not None:
            # 应用到指定列的所有绘图组件
            for row in range(self.rowsCount()):
                plot = self.plotAt(row, col)
                if plot:
                    plot.change_xaxis_labels_by_format(True)
        else:
            # 应用到所有绘图组件
            for row in range(self.rowsCount()):
                for col in range(self.colsCount()):
                    plot = self.plotAt(row, col)
                    if plot:
                        plot.change_xaxis_labels_by_format(True)

    def set_xaxis_label_rotation(self, rotation=0, row=None, col=None):
        """设置X轴标签旋转角度
        
        Args:
            rotation: 旋转角度（度）
            row: 指定行索引（可选），如果不提供则应用到所有行
            col: 指定列索引（可选），如果不提供则应用到所有列
        """
        if row is not None and col is not None:
            # 应用到指定位置的绘图组件
            plot = self.plotAt(row, col)
            if plot:
                plot.set_xaxis_label_rotation(rotation)
        elif row is not None:
            # 应用到指定行的所有绘图组件
            for col in range(self.colsCount()):
                plot = self.plotAt(row, col)
                if plot:
                    plot.set_xaxis_label_rotation(rotation)
        elif col is not None:
            # 应用到指定列的所有绘图组件
            for row in range(self.rowsCount()):
                plot = self.plotAt(row, col)
                if plot:
                    plot.set_xaxis_label_rotation(rotation)
        else:
            # 应用到所有绘图组件
            for row in range(self.rowsCount()):
                for col in range(self.colsCount()):
                    plot = self.plotAt(row, col)
                    if plot:
                        plot.set_xaxis_label_rotation(rotation)
    
    


    def dragEnterEvent(self, event):
        """处理拖拽进入事件"""
        if event.mimeData().hasText() and event.mimeData().hasFormat("application/combo-datas"):
            event.acceptProposedAction()
        else:
            event.ignore()
    
    def dragMoveEvent(self, event):
        """处理拖拽移动事件"""
        if event.mimeData().hasText() and event.mimeData().hasFormat("application/combo-datas"):
            event.acceptProposedAction()
        else:
            event.ignore()


    def dropEvent(self, event):
        if not self._is_only_one_plot_window():
            print("需要在空的单窗口拖入组合项数据")
            return
        plot = self.first_plot_widget()
        # print(plot.is_already_add_line())
        if plot and not plot.is_already_add_line():

            if event.mimeData().hasFormat("application/combo-datas"):
                combo_context_dic = PlotMatrix.decode_mime_data(event.mimeData())
                # print(combo_context_dic)
                plot_type = combo_context_dic.get("plot_type",None)
                plot_info = combo_context_dic.get("plot_info",None) 
                if plot_type is None or plot_info is None:
                    return
                # 0-> 00    1-> 00,01     2->00,10       3-> 00,01,10,11
                if  plot_type == "1":
                    self.addColumn()
                elif plot_type == "2":
                    self.addRow()
                elif plot_type == "3":
                    self.addColumn()
                    self.addRow()
                
                for info in plot_info:
                    location   = info["location"]
                    head_names = info["items"]
                    
                    if location == "00":
                        target_plot = self.plotAt(0,0)
                    elif location == "01":
                        target_plot = self.plotAt(0,1)
                    elif location == "10":
                        target_plot = self.plotAt(1,0)
                    elif location == "11":
                        target_plot = self.plotAt(1,1)
                    # print(location,head_names)
                    target_plot._plot_by_data_keys(head_names)


    def handle_double_click_from_rcd_panel(self, data_name:str):

        plot = self.first_plot_widget()

        if plot.is_already_has_this_line(data_name):
            return
        
        plot._plot_by_data_key(data_name)

    def del_hidden_lines(self):

        for row in range(self.rowsCount()):
            for col in range(self.colsCount()):
                plot = self.plotAt(row,col)
                if plot:
                    plot.del_hidden_lines()