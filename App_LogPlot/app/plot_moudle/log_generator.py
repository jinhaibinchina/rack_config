from typing import List, Dict, Any,Callable
from datetime import datetime, timedelta

# from plot_moudle import IDataProvider,MultiMeta
from .interface import IChartRenderer,IDataProvider,MultiMeta
import numpy as np
from PySide6.QtCore import QObject, Signal,Slot
import copy

from ..rcd_log_importer import RcdLogImporter

def generate_datetime_series():
    """
    生成时间序列，格式为"2024-12-04-20:30:45.123"
    时间跨度100秒，间隔50毫秒
    """
    # 起始时间
    start_time = datetime(2024, 12, 4, 20, 30, 45, 123000)
    
    # 时间跨度100秒，间隔50毫秒
    duration_seconds = 500
    interval_milliseconds = 50
    
    # 计算总点数
    total_points = int(duration_seconds * 1000 / interval_milliseconds) + 1
    
    # 生成时间序列
    datetime_series = []
    for i in range(total_points):
        # 计算当前时间点
        current_time = start_time + timedelta(milliseconds=i * interval_milliseconds)
        
        # 格式化为指定格式
        formatted_time = current_time.strftime("%Y-%m-%d-%H:%M:%S.%f")[:-3]  # 保留3位毫秒
        datetime_series.append(formatted_time)
    
    return datetime_series

class LogDataGenerator(IDataProvider, QObject, metaclass=MultiMeta):
#     def __init__(self):
#         # 必须显式调用两个父类的__init__
#         QObject.__init__(self)
#         IDataProvider.__init__(self)
# class LogDataGenerator(IDataProvider):
    """日志数据生成器,对接rcd_log_import模块"""
    @staticmethod
    def convert_date_format(date_str):
        """
        将 'YYYY-MM-DD HH:MM:SS.sss' 格式转换为 'YYYY-MM-DD-HH:MM:SS.sss' 格式
        
        Args:
            date_str: 输入日期字符串，格式如 '2025-11-27 16:28:11.285'
        
        Returns:
            转换后的日期字符串，格式如 '2025-11-27-16:28:11.285'
        """
        # 将空格替换为 -
        return date_str.replace(' ', '-')
    def __init__(self, name: str = "默认日志生成器",log_importer:RcdLogImporter = None):
        # PySide6 不允许同一个 QObject 被初始化两次（PyQt5 只会静默容忍）。
        # MRO 是 LogDataGenerator → IDataProvider → ABC → QObject，
        # IDataProvider.__init__ 里的 super() 会顺着 MRO 走到 QObject.__init__，
        # 所以这里**只能**调一次，不能再显式 QObject.__init__(self)。
        IDataProvider.__init__(self)
        self.name = name
        self.version = "1.0"
        self._data_ready = False
        # self._data_head = []#表头 包含time 表头
        self.__head_datas = None
        self._xdata =[]

        self._generated_data = {}
        self._observers: List[Callable] = []  # 观察者列表

        self._log_importer = log_importer
        self._log_importer.logs_imported.connect(self.on_log_import_done)
    def add_observer(self, observer: Callable):
        """添加观察者（图表绘制模块）"""
        if observer not in self._observers:
            self._observers.append(observer)
            print(f"已添加观察者: {observer.__name__ if hasattr(observer, '__name__') else '匿名函数'}")
    
    def remove_observer(self, observer: Callable):
        """移除观察者"""
        if observer in self._observers:
            self._observers.remove(observer)

    @Slot(bool)
    def on_log_import_done(self,success):
        if not success:
            return
        time_list =   self._log_importer.get_time_list()
        
        xData =list(map(LogDataGenerator.convert_date_format,time_list))
       
        self._xdata = xData

        data_head = self._log_importer.get_headers()
        self.__head_datas = [x for x in data_head if x!="date_time" and x!="time_ts"] 

        self._data_ready = True
        print(f"数据生成完成")
        
        # 通知所有观察者数据已准备就绪
        self._notify_observers()
    
    def get_xData(self):
        return self._xdata
	
    def generate_sample_data(self):
        """生成示例日志数据"""
        print(f"{self.name} 开始生成日志数据...")
        # self._data_head =["date_time","ctu_io_s00_i02_n02_b008_g00_p00_a0","ctu_io_s01_i02_n02_b008_g00_p0"]
        xData = generate_datetime_series()
        length=len(xData)
        # sine_array = np.sin(np.linspace(0, 2*np.pi, length))
        # cose_array = np.cos(np.linspace(0, 2*np.pi, length))
        import math
        self._generated_data = {
            "date_time":xData
                            ,
            "ctu_io_s00_i02_n02_b008_g00_p00_a0":[x-1000 for x in range(length)],
            "ctu_io_s01_i02_n02_b008_g00_p0"    :[math.sin(x%360*np.pi/180.0) for x in range(length)],
            "flc_sta_err_code"    :[8 for x in range(length)],
            "flc_sta_running_sm"    :[5 for x in range(length)],
            "flc_in_obv0_tag"    :[2 for x in range(length)],
            "flc_out_nobv_th"    :[3 for x in range(length)],
            "wheel_0_motor[0].status_word": [5 for x in range(length)]
        }
        
        
        self._data_ready = True
        print(f"数据生成完成")
        
        # 通知所有观察者数据已准备就绪
        self._notify_observers()

    def generate_sample_data_2(self):
        """生成示例日志数据"""
        print(f"{self.name} 开始生成日志数据...")
        # self._data_head =["date_time","ctu_io_s00_i02_n02_b008_g00_p00_a0","ctu_io_s01_i02_n02_b008_g00_p0"]
        xData = generate_datetime_series()
        length=len(xData)
        # sine_array = np.sin(np.linspace(0, 2*np.pi, length))
        # cose_array = np.cos(np.linspace(0, 2*np.pi, length))
        self._generated_data = {
            "date_time":xData
                            ,
            
            "flc_in_obv0_tag"    :[2 for x in range(length)],
            "flc_out_nobv_th"    :[3 for x in range(length)],
            "wheel_0_motor[0].status_word": [5 for x in range(length)]
        }
        
        
        self._data_ready = True
        print(f"数据生成完成")
        
        # 通知所有观察者数据已准备就绪
        self._notify_observers()
    
    def _notify_observers(self):
        """通知所有观察者"""
        if self._observers:
            print(f"通知 {len(self._observers)} 个观察者数据已准备就绪...")
            for observer in self._observers:
                try:
                    observer(self)  # 将自身作为参数传递给观察者
                except Exception as e:
                    print(f"{self.name}通知观察者时出错: {e}")
        else:
            print("警告: 没有注册的观察者")
    def is_data_ready(self) -> bool:
        """检查数据是否准备就绪"""
        return self._data_ready

    def get_data(self,head_name) -> List[Any]|None:
        """实现接口方法：获取日志数据"""
        if not self._data_ready:
            return None
        if head_name=="timestamp":
            return self._xdata
        result = self._log_importer.get_column_data(head_name)
        return result[head_name].tolist() if not result.empty else None
        # return result.copy() if result else None

    def get_datas(self,head_names) -> List[Any]|None:
        """根据表头名称获取数据"""
        if not self._data_ready:
            return None
        # if head_names=="timestamp":
        #     return self._xdata
        result = self._log_importer.get_column_data(head_names)
        # print(f"读取多列{result}")
        if result.empty:
            return None
        # for head_name in head_names:
        #     print(result[head_name].tolist())
        #     print([result[head_name].tolist() for head_name in head_names])

        return   [result[head_name].tolist() for head_name in head_names]
        
    def get_data_head(self) -> List[str]|None:
        """实现接口方法：获取数据表头列表"""
        if not self._data_ready:
            return None
        return self.__head_datas
    
    def get_row_data(self,idx) -> Dict[str,List[Any]]|None:
        """实现接口方法：获取日志数据"""
        if not self._data_ready:
            return None
        # if head_name=="timestamp":
        #     return self._xdata
        result = {}
        row_df = self._log_importer.get_row_data(idx)
        # return result[idx].tolist() if not result.empty else None
        if row_df is None or row_df.empty:
            return None
        data = row_df.iloc[0].tolist()
        data_copy = copy.deepcopy(data)

        result = dict(zip(self.__head_datas,data_copy[2:]))# 获取第一行（也是唯一一行）的所有值并转换为列表
        
        return result