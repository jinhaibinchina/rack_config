from PySide6.QtCore import QThread, Signal, QMutex, QObject
from queue import Queue
# import snap7
# from snap7.util import *

from PySide6.QtWidgets import QGroupBox,QWidget,QVBoxLayout,QHBoxLayout,QApplication
import time
from functools import wraps
from .my_plc_manager import PLCManager



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




class DataBroker(QObject):
    # 定义信号（替代直接操作队列）
    # 主电柜_data_ready = Signal(tuple)          # (db_name, data)
    # 维修区_data_ready = Signal(tuple)
    # 上架_data_ready   = Signal(tuple)
    # 拣选_data_ready   = Signal(tuple)
    # 安全门_data_ready = Signal(tuple)
    # 输送线_data_ready = Signal(tuple)
    data_ready         = Signal(tuple)
    station_data_ready = Signal(tuple)
    sys_status_data_ready  = Signal(tuple)
    ip_mac_data_ready   = Signal(tuple)
    device_query_data_ready = Signal(tuple)

    def __init__(self,parent=None, plc_manager: PLCManager=None):
        super().__init__(parent)
        self.plc_manager = plc_manager
        self.data_cache = {}
        self.data_lock = QMutex()
        self._command = {}
        
        pages = ("主电柜","维修区/安全门","上架X4","拣选X4","安全门X1","输送线X2","Q1P拣选/Q3P拣选","Q3P托盘X2","输送线X4")
        self.current_page_name = ""
        self.cabinet_num = 0
        self.cabinet_num_global = 0

        self.cabinet_is_selected = False
        
        self.__enable_station_query_flag = False
    
      

        # 创建线程对象（但不立即启动）
        self.polling_thread = PollingThread(self)

    def enable_station_query(self,enable):
        self.__enable_station_query_flag = enable
    def is_station_query_enabled(self):
        return self.__enable_station_query_flag

    def read_config_parameters(self):
        """   """
        data = self.plc_manager.read_data(801,13)
        return data
    
    def write_config_parameters(self,data)->bool:
        return self.plc_manager.write_data(851,data)
    
    def read_config_parameters_2(self):
        """   """
        data = self.plc_manager.read_data(1021,1)
        return data
    
    def write_config_parameters_2(self,data)->bool:
        return self.plc_manager.write_data(1022,data)
    
    def set_current_selected_type(self,type)->bool:
      
        self.cabinet_is_selected = type>0
        return self.plc_manager.write_data(400,type)
    def set_current_selected_num(self,num)->bool:
        return self.plc_manager.write_data(401,num)
    
    def regedit_callback(self, **kwargs):
        for key, value in kwargs.items():
            self._command[key] = value

    def _entry_para_page_event(self, key):
        callback = self._command.get(key)
        if callback:
            callback()

  
    
    def on_current_select_changed(self,name,num):
        """弃用"""
        self.current_page_name = name
        self.cabinet_num = num
      

    def start_data_polling(self, interval: float = 0.2):
        """启动数据采集线程"""
        self.polling_thread.set_interval(interval)
        self.polling_thread.start()

    def stop_data_polling(self):
        """停止数据采集线程"""
        self.polling_thread.requestInterruption()
        self.polling_thread.quit()
        self.polling_thread.wait()

   

    def get_cached_data(self, key: str):
        """获取缓存数据"""
        self.data_lock.lock()
        data = self.data_cache.get(key)
        self.data_lock.unlock()
        return data
        


class PollingThread(QThread):

    

    def __init__(self, broker: DataBroker):
        super().__init__()
        self.broker = broker
        self._interval = 0.1
        self._count    = 0

    def set_interval(self, interval: float):
        self._interval = interval

    def run(self):
        """线程主循环"""
       
        while not self.isInterruptionRequested():
            if self.broker.plc_manager.isConnected():
                # self._read_and_emit(900, 20, self.broker.data_ready, '电柜状态')
                # self._read_and_emit(200, 4,  self.broker.sys_status_data_ready, '系统状态')
                # self._read_and_emit(220, 20,  self.broker.ip_mac_data_ready, '地址状态')
                self._produce_normal_data()

                
                if self.broker.current_page_name == "":
                # if not self.cabinet_is_selected:
                    self.msleep(int(self._interval * 500))
                    continue
                # cabinet_num = self.broker.cabinet_num
                # # 根据当前页面读取不同数据
                # if self.broker.current_page_name ==   "主电柜":
                #     self._read_and_emit(300, 10, self.broker.station_data_ready, '主电柜')
                # elif self.broker.current_page_name == "维修区/安全门":
                #     #510 -540
                #     self._read_and_emit(310+(cabinet_num-1)*10, 10, self.broker.station_data_ready, '维修区/安全门')
                # elif self.broker.current_page_name == "上架X4" :
                #     #550 -580
                #     self._read_and_emit(410+(cabinet_num-1)*10, 10, self.broker.station_data_ready, '上架X4')
                # elif self.broker.current_page_name == "拣选X4":
                #     #590 -620
                #     self._read_and_emit(510+(cabinet_num-1)*10, 10, self.broker.station_data_ready, '拣选X4')
                # elif self.broker.current_page_name == "安全门X1":
                #     #630 -710
                #     self._read_and_emit(610+(cabinet_num-1)*10, 10, self.broker.station_data_ready, '安全门X1')
                # elif self.broker.current_page_name == "输送线X2":

                #     self._read_and_emit(710+(cabinet_num-1)*10, 10, self.broker.station_data_ready, '输送线X2')
                
                # self._read_and_emit(310, 10, self.broker.station_data_ready, self.broker.current_page_name)
                self._produce_special_data()

            self.msleep(int(self._interval * 1000))
    @time_it
    def _produce_normal_data(self):
      
        

        if self.broker.is_station_query_enabled():
            self._read_and_emit(210, 6,  self.broker.device_query_data_ready, '查询状态')

        if self._count%10 == 0:
            self._read_and_emit(220, 20,  self.broker.ip_mac_data_ready, '地址状态')
        else:
            self._read_and_emit(900, 20, self.broker.data_ready, '电柜状态')
            self._read_and_emit(200, 10,  self.broker.sys_status_data_ready, '系统状态')

        self._count += 1
    
    @time_it
    def _produce_special_data(self):
        self._read_and_emit(310, 14, self.broker.station_data_ready, self.broker.current_page_name)

    def _read_and_emit(self, address, count, signal, cache_key, timeout=1):
        """读取数据并发射信号"""
        try:
            data = self.broker.plc_manager.read_data(address,count)
        except Exception as e:
            print(f"读取PLC数据出错: {e}")
            return
        # print(cache_key,data)
        if data:
            self.broker.data_lock.lock()
            self.broker.data_cache[cache_key] = data
            self.broker.data_lock.unlock()
            signal.emit((cache_key, data))

if __name__ == "__main__":
    app = QApplication([])
    plc_manager = PLCManager(app,"192.168.1.2")
    plc_manager.start_heartbeat()
    data_broker = DataBroker(app,plc_manager)
    data_broker.start_data_polling()
    app.exec()
