from PyQt6.QtCore import QThread, QMutex, QObject,pyqtSignal
from snap7.util import *
from plc_manager import PLCManager

class DataBroker(QObject):
    # 定义信号（替代直接操作队列）
    data_ready = pyqtSignal(tuple)          # (db_name, data)
    # rack_status_data_ready = pyqtSignal(tuple) 
    def __init__(self, plc_manager: PLCManager):
        super().__init__()
        self.plc_manager = plc_manager
        self.data_cache = {}
        self.data_lock = QMutex()
       
        # 创建线程对象（但不立即启动）
        self.polling_thread = PollingThread(self)
        
  
    
    
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
        
    def set_bit_value(self, data, offset, bit_pos, value):
        """设置bool型控制位"""
        byte_val = data[offset]
        if value:
            byte_val |= 1 << bit_pos
        else:
            byte_val &= ~(1 << bit_pos)
        data[offset] = byte_val

    def get_bit_value(self, data, offset, bit_pos):
        """读取bool型控制位""" 
        return bool(data[offset] & (1 << bit_pos))

    def toggle_bit_value(self, data: bytearray, offset: int, bit_pos: int):
        """翻转bool型控制位"""
        if offset >= len(data):
            raise IndexError("Offset超出数据范围")
        if bit_pos < 0 or bit_pos > 7:
            raise ValueError("位位置必须在0-7之间")
        
        data[offset] ^= (1 << bit_pos)
        return bool(data[offset] & (1 << bit_pos))


class PollingThread(QThread):
    def __init__(self, broker: DataBroker):
        super().__init__()
        self.broker = broker
        self._interval = 0.2

    def set_interval(self, interval: float):
        self._interval = interval

    def run(self):
        """线程主循环"""
       
        while not self.isInterruptionRequested():
            # 处理页面切换事件
        
            self._read_and_emit(21,50,26, self.broker.data_ready, 'db21', timeout=2)

            self._read_and_emit(12,0,242+104, self.broker.data_ready, 'db12', timeout=2)

            self._read_and_emit(24,0,458, self.broker.data_ready, 'db24', timeout=2)

            self._read_and_emit(25,0,160, self.broker.data_ready, 'db25', timeout=2)

            self.msleep(int(self._interval * 1000))

    def _read_and_emit(self, db_number:int,start:int, size:int, signal:pyqtSignal, cache_key:str, timeout=1):
        """读取数据并发射信号"""
        data = self.broker.plc_manager.read_data(db_number=db_number, start=start, size=size)
        if data:
            
            signal.emit((cache_key, data))
