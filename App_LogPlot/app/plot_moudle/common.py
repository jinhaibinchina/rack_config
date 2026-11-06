from enum import Enum
from datetime import datetime,timezone,timedelta
import numpy as np
from numpy.typing import NDArray
from .interface import IChartRenderer, IDataProvider
import json
import time
from functools import wraps
from .resource_manager import resource_manager as res_mng
from typing import List, Dict,Union, Any,Callable,Optional,Tuple
# from pympler import asizeof
import pandas as pd



def string_to_datetime(time_str):
    """字符串转datetime对象（带UTC时区）"""
    return datetime.strptime(time_str, "%Y-%m-%d-%H:%M:%S.%f").replace(tzinfo=timezone.utc)

def datetime_from_timestamp(timestamp,part:bool=True):
    """datetime对象转字符串（保持原格式）"""
    dt_from_timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    full_str = dt_from_timestamp.strftime("%Y-%m-%d-%H:%M:%S.%f")
    # time_str = full_str[5+9:22] if part else full_str[:23]
    time_str = full_str[5+9-3:23] if part else full_str[:23]
    return time_str

def datetime_from_timestamp_for_xAxis(timestamp):
    """datetime对象转字符串（保持原格式）"""
    if timestamp<0:
        return
    dt_from_timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    time_str = dt_from_timestamp.strftime("%Y-%m-%d-%H:%M:%S.%f")[11:19]
    # time_str = dt_from_timestamp.strftime("%Y-%m-%d-%H:%M:%S.%f")[8:19]
   
    return time_str




class xLabelFormat(Enum):
        DT = 0
        SEC = 1
        
class PlotDataMapRef:
    def __init__(self):
        self.data :Dict[str,Tuple[NDArray,NDArray]] = {}
        self._base_timestamp_ms = 0 
        
    def add_data(self, key:str, x_data:NDArray, y_data:NDArray):

        self.data[key] = (x_data, y_data)
        
        
    def get_data(self, key:str)->Tuple[NDArray,NDArray]|None:

        return self.data.get(key, None)
    
    def get_xdata(self):
        for key in self.data:
            return self.data[key][0]
    
    def get_keys(self):
        return self.data.keys()
    
    def set_base_timestamp_ms(self,val:int):
        self._base_timestamp_ms =val

    def base_timestamp_ms(self):
        return self._base_timestamp_ms
    
    def clear(self):
        self.data = {}
        self._base_timestamp_ms = 0 
    
    def isEmpty(self):
        return bool(self.data)==False

    def memory_useage(self):
        # from pympler import asizeof
        # return asizeof.asizeof(self.data)
        return None



class rcd_data_bridge(IChartRenderer):
    """数据中转，将LogDataGenerator生成的数据 搬运到plot_window"""
    @staticmethod
    def is_numeric(value):
        """判断值是否为数值（整数或浮点数）"""
        if pd.isna(value):
            return False
        try:
            float(value)
            return True
        except (ValueError, TypeError):
            return False
    @staticmethod
    def get_first_item(iterable, default=None):
        """安全获取第一项，如果为空返回默认值"""
        try:
            iterator = iter(iterable)
            return next(iterator)
        except StopIteration:
            return default
    
    def __init__(self,name: str = "数据桥梁"):
        self.name = name
        self.version = "1.0"
        self.__xdata_src= None
        self.__xdata    = None
        self.__row_data = None
        self.__base_timestamp =0
        self.datamap = PlotDataMapRef()
        self.cfg = None
        self.__head_datas = None
        self.__rcd_provider :Optional[IDataProvider] =None
        self.__idx_count = 0
        self.__total_tims_ms = 0

        self._observers: List[Callable] = []  # 观察者列表
    

    def add_observer(self, observer: Callable):
        """添加观察者（图表绘制模块）"""
        if observer not in self._observers:
            self._observers.append(observer)
            print(f"已添加观察者: {observer.__name__ if hasattr(observer, '__name__') else '匿名函数'}")

    def _notify_observers(self):
        """通知所有观察者"""
        if self._observers:
            print(f"通知 {len(self._observers)} 个观察者数据已准备就绪...")
            for observer in self._observers:
                try:
                    observer()  # 将自身作为参数传递给观察者
                except Exception as e:
                    print(f"{self.name}通知观察者时出错: {e}")
        else:
            print("警告: 没有注册的观察者")        
    


    def on_data_ready(self, rcd_provider: IDataProvider):
        """实现接口方法：数据准备完成时的回调"""
        print(f"{self.name} 接收到数据准备就绪通知")
        if not self.datamap.isEmpty():
            self.datamap.clear()
            self.__head_datas:Optional[List[str]] = None
            self.__base_timestamp =0
            self.__xdata_src:Optional[List[str]] = None
            self.__xdata    :Optional[NDArray]    = None
            self.__row_data = None
            print("data bridge 清空原有数据")
        
        self.__rcd_provider = rcd_provider
        if self.cfg is None:
            flie_path = res_mng.get_config_path("head_name_map.json")
            with open(flie_path, 'r', encoding='utf-8') as file:
                self.cfg= json.load(file)
        try:
            # 通过接口获取数据
            
            data_head_lst = rcd_provider.get_data_head()
            print("data bridge 获取到数据表头") 
            self.__head_datas = data_head_lst
            self.__xdata_src = rcd_provider.get_data("timestamp")

            print("data bridge 获取到时间戳列表")                  
            dt = string_to_datetime(self.__xdata_src[0])
            base_timestamp_ms = int(dt.timestamp() * 1000.0)
            self.__base_timestamp = base_timestamp_ms
            xdata:List[int] =[]
            for data in self.__xdata_src:
                dt = datetime.strptime(data, "%Y-%m-%d-%H:%M:%S.%f").replace(tzinfo=timezone.utc)
                timestamp = int(dt.timestamp() * 1000)
                timestamp_ms = timestamp-base_timestamp_ms  #  
                xdata.append(timestamp_ms)
            self.__xdata = np.array(xdata)
            print("data bridge 将时间戳列表转换成x轴数据列表")    
            
            # self.__row_data = self.request_data_by_idx(1)
            
            self.datamap.set_base_timestamp_ms(base_timestamp_ms)
            
            self.__idx_count = len(self.__xdata)
            self.__total_tims_ms = self.__xdata[-1] - self.__xdata[0]
            if self.__xdata[-1] < self.__xdata[0]:
                print(f"头{self.__xdata_src[0]} 尾{self.__xdata_src[-1]}")
            print(f"RCD idx_count： {self.__idx_count} RCD时间跨度： {self.__total_tims_ms}ms")
            

            self._notify_observers()
            
            
        except Exception as e:
            print(f"处理数据时出错: {e}")

    def idx_count(self):
        return self.__idx_count
    
    def total_time_ms(self):
        return self.__total_tims_ms
    
    def base_timestamp(self):
        return self.__base_timestamp
    
    def head_names(self):
        return self.__head_datas
    
    def request_data_by_head_name(self,head_name:str):
        if self.__is_request_head_name_in_datamap(head_name):
            return self.get_one_data_saved_in_bridge(head_name)
        
        ydata_lst = self.__rcd_provider.get_data(head_name)
        if  ydata_lst is None:
            return None
        first_y = rcd_data_bridge.get_first_item(ydata_lst)

        if not rcd_data_bridge.is_numeric(first_y):
            print("申请RCD数据失败")
            return None
        ydata =np.array(ydata_lst)
        self.datamap.add_data(head_name, self.__xdata, ydata)
        return self.get_one_data_saved_in_bridge(head_name)

    def request_datas_by_head_names(self,head_names:List[str]):
        
        if self.__is_all_request_head_name_in_datamap(head_names):

            return self.get_datas_saved_in_bridge(head_names)
        
        ydatas_lst = self.__rcd_provider.get_datas(head_names) 
        
        if  ydatas_lst is None:
            print("申请RCD数据失败")
            return None
      
        for ydata_lst in ydatas_lst:

            first_y = rcd_data_bridge.get_first_item(ydata_lst)
            if not rcd_data_bridge.is_numeric(first_y):
                return None

        for i, ydata_lst in enumerate(ydatas_lst):

            ydata =np.array(ydata_lst)
            # keys_list = copy.deepcopy(self.datamap.get_keys()) 字典不能copy
            keys_list = list(self.datamap.get_keys())  # Convert dict_keys to list
            
            self.datamap.add_data(head_names[i], self.__xdata, ydata)        
        
        return self.get_datas_saved_in_bridge(head_names)

    def request_data_by_idx(self,idx:int):

        self.__row_data = self.__rcd_provider.get_row_data(idx)
        return self.__row_data

    def keys(self)->List[str]:

        return self.datamap.get_keys()

    def __is_request_head_name_in_datamap(self,key):

        return key in self.datamap.get_keys()

    def __is_all_request_head_name_in_datamap(self,keys):
        return set(keys).issubset(set(self.datamap.get_keys()))

    def xdata_rcd(self):
        return self.__xdata
    
    def row_data(self):
        """最近一次读到的行数据"""
        return self.__row_data
    
    def get_all_data_save_in_bridge(self):
        return self.datamap.data
    
    def get_one_data_saved_in_bridge(self,key:str):

        return self.datamap.get_data(key)
    
    def get_datas_saved_in_bridge(self,keys):
        return [self.datamap.get_data(key) for key in keys]
    
    def xlim(self)->Tuple|None:
        if self.__xdata is None:
            return None
        first_element = self.__xdata[0]      # 首位
        last_element  = self.__xdata[-1]      # 末位
        return first_element,last_element

    def x_data_step(self)->int:
        return self.__xdata[1]-self.__xdata[0]
    
    def memory_useage_of_data(self):
        return self.datamap.memory_useage()
    
    
def time_it(func):
    """计算函数执行时间的装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()  # 高精度计时
        result = func(*args, **kwargs)    # 执行原函数
        end_time = time.perf_counter()
        elapsed_time = end_time - start_time
        
        # 格式化输出时间（根据时长自动选择合适的单位）
        if elapsed_time < 1e-6:
            time_str = f"{elapsed_time * 1e9:.3f} ns"
        elif elapsed_time < 1e-3:
            time_str = f"{elapsed_time * 1e6:.3f} μs"
        elif elapsed_time < 1:
            time_str = f"{elapsed_time * 1e3:.3f} ms"
        else:
            time_str = f"{elapsed_time:.3f} s"
        
        print(f"[{func.__name__}] 执行时间: {time_str}")
        return result
    return wrapper