from PySide6.QtCore import QThread, QMutex, QObject, Qt, Signal
from snap7.util import *
from App_RackConfig.plc_manager import PLCManager

class DataBroker(QObject):
    # 定义信号（替代直接操作队列）
    data_ready = Signal(tuple)          # (db_name, data)
    # rack_status_data_ready = Signal(tuple) 
    def __init__(self, plc_manager: PLCManager, parent=None):
        super().__init__(parent)
        self.plc_manager = plc_manager
        self.data_cache = {}
        self.data_lock = QMutex()
       
        # 创建线程对象（但不立即启动）
        self.polling_thread = PollingThread(self)
        
  
    
    
    def start_data_polling(self, interval: float = 0.2):
        """启动数据采集线程"""
        if self.polling_thread.isRunning():
            return
        self.polling_thread.set_interval(interval)
        self.polling_thread.start()

    def stop_data_polling(self, wait_ms: int = 5000):
        """停止数据采集线程。

        QThread 析构时若仍在运行会触发
        "QThread: Destroyed while thread is still running" 并可能崩溃，
        所以这里必须确保线程真正结束（等待有上限，避免 exit 时卡死）。
        """
        thread = self.polling_thread
        if thread is None:
            return
        thread.requestInterruption()
        if thread.isRunning():
            thread.wait(wait_ms)

    def shutdown(self):
        """线程安全退出，可直接放在 closeEvent 里调用。"""
        self.stop_data_polling()
        if self.plc_manager is not None:
            self.plc_manager.stop_thread()

   
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
    # 断开时轮询的等待间隔（毫秒），避免空转占 CPU
    OFFLINE_INTERVAL_MS = 500

    def __init__(self, broker: DataBroker):
        super().__init__()
        self.broker = broker
        self._interval = 0.1

    def set_interval(self, interval: float):
        self._interval = interval

    def run(self):
        """线程主循环"""
        plc = self.broker.plc_manager
        while not self.isInterruptionRequested():
            # 断线时不发请求：PLC 失联时每次 db_read 都要等超时，
            # 5 个 DB 串起来会让一个轮询周期长达 10 秒。
            if not plc.isConnected():
                self.msleep(self.OFFLINE_INTERVAL_MS)
                continue

            self._read_and_emit(21,50,26, self.broker.data_ready, 'db21', timeout=2)

            self._read_and_emit(12,0,242+104 +2, self.broker.data_ready, 'db12', timeout=2)

            self._read_and_emit(24,0,458, self.broker.data_ready, 'db24', timeout=2)

            self._read_and_emit(25,0,160, self.broker.data_ready, 'db25', timeout=2)

            self._read_and_emit(31,650,240, self.broker.data_ready, 'db31', timeout=2)

            self.msleep(int(self._interval * 1000))

    def _read_and_emit(self, db_number:int,start:int, size:int, signal:Signal, cache_key:str, timeout=1):
        """读取数据并发射信号；读到一半断线就不再继续读剩下的 DB。"""
        data = self.broker.plc_manager.read_data(db_number=db_number, start=start, size=size)
        if data:
            signal.emit((cache_key, data))
