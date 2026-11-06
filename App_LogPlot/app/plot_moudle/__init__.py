'''
RCD 多功能绘图模块


'''
import os as _os

# matplotlib 的 Qt 后端会自动探测已安装的绑定，探测顺序是 PyQt6 → PyQt5 →
# PySide6。只要机器上同时装着 PyQt6/PyQt5，它就会抢先绑定到 PyQt 上，跟本
# 项目的 PySide6 混用会直接报 "destroy the QApplication singleton"。
# 这里在任何 matplotlib 导入之前钉死绑定，必须放在本文件最前面。
_os.environ.setdefault("QT_API", "pyside6")

__version__ ='1.0.0'
__author__  ='jinhaibin'

from .plot_window_with_datalist import plot_window
from .common import rcd_data_bridge

# from .interfaces import IChartRenderer,IDataProvider,MultiMeta
from .log_generator import LogDataGenerator


# __all__ =["plot_window","rcd_data_bridge","IChartRenderer","IDataProvider","MultiMeta","LogDataGenerator"]

__all__ =["plot_window","rcd_data_bridge","LogDataGenerator"]

