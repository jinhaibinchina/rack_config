from PySide6.QtCore import QThread, QMutex, QObject, Qt, Signal
from shiboken6 import isValid
from snap7.util import *
from .snap7_plc_manager import PLCManager

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

    def stop_data_polling(self, wait_ms: int = 5000) -> bool:
        """停止数据采集线程，返回**线程是否真的已经结束**。

        QThread 析构时若仍在运行会触发
        "QThread: Destroyed while thread is still running" 并可能崩溃，
        所以这里必须确保线程真正结束（等待有上限，避免 exit 时卡死）。

        返回 False 表示等超时了、线程还在跑：调用方**不能**让这个 broker
        随宿主窗口一起销毁，否则线程下一轮就会去读已释放的 QObject。
        """
        thread = self.polling_thread
        if thread is None:
            return True
        thread.requestInterruption()
        if not thread.isRunning():
            return True
        return bool(thread.wait(wait_ms))

    def shutdown(self):
        """线程安全退出，可直接放在 closeEvent 里调用。"""
        self.stop_data_polling()
        if self.plc_manager is not None:
            self.plc_manager.stop_thread()


# 轮询线程还没停、但已经不能随宿主销毁的 broker（见 keep_alive_until_stopped）
_ORPHANS: list = []


def keep_alive_until_stopped(broker: "DataBroker") -> None:
    """把 broker 从宿主对象上摘下来保活，直到它的轮询线程真正退出。

    宿主窗口关闭时，轮询线程可能正卡在 ``db_read`` 里（PLC 掉线时单次能等
    2 秒），等不到中断标志。这时 broker 一旦随窗口销毁，线程下一轮去摸
    ``broker.data_ready`` 就是访问已释放的 C++ 对象，进程直接段错误——
    屏幕上表现为"窗口在，但点什么都没反应"。

    摘下来挂在模块级列表里，线程 ``run()`` 结束时会把自己移除，之后
    broker 才真正被回收。
    """
    try:
        broker.setParent(None)
    except RuntimeError:
        return
    if broker not in _ORPHANS:
        _ORPHANS.append(broker)


def _release_orphan(broker: "DataBroker") -> None:
    try:
        _ORPHANS.remove(broker)
    except ValueError:
        pass

   
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
    # 断开时轮询的等待间隔（毫秒），避免空转占 CPU。
    # 这个值同时决定了 stop_data_polling 要等多久——线程是在 msleep 里
    # 醒来看 isInterruptionRequested 的，睡 500ms 就意味着关窗最多卡 500ms。
    # 100ms 的唤醒开销可以忽略（醒来只判一次 isConnected 就继续睡）。
    OFFLINE_INTERVAL_MS = 100

    def __init__(self, broker: DataBroker):
        super().__init__()
        self.broker = broker
        self._interval = 0.1

    def set_interval(self, interval: float):
        self._interval = interval

    def run(self):
        """线程主循环"""
        # 全程只认这一个局部引用：`self.broker` 每轮重新求值没有意义，
        # 而且万一它被换掉/删掉，反而多一次踩空的机会。
        broker = self.broker
        plc = broker.plc_manager
        try:
            while not self.isInterruptionRequested():
                # 宿主窗口关掉时，DataBroker 的 **C++ 对象** 会先随父对象销毁，
                # 而 Python 包装还活着。这时再去摸 broker.data_ready 就是访问
                # 已释放内存：Windows 抛 access violation，整个进程段错误——
                # 界面上表现为"窗口还在，但点什么都没反应"。
                if not isValid(broker):
                    return
                # 断线时不发请求：PLC 失联时每次 db_read 都要等超时，
                # 5 个 DB 串起来会让一个轮询周期长达 10 秒。
                if not plc.isConnected():
                    self.msleep(self.OFFLINE_INTERVAL_MS)
                    continue

                self._read_and_emit(broker, 21, 50, 26, 'db21')

                self._read_and_emit(broker, 12, 0, 242 + 104 + 2, 'db12')

                self._read_and_emit(broker, 24, 0, 458, 'db24')

                self._read_and_emit(broker, 25, 0, 160, 'db25')

                self._read_and_emit(broker, 31, 650, 240, 'db31')

                self.msleep(int(self._interval * 1000))
        finally:
            _release_orphan(broker)

    def _read_and_emit(self, broker, db_number: int, start: int, size: int, cache_key: str, timeout=1):
        """读取数据并发射信号；读到一半断线就不再继续读剩下的 DB。"""
        data = broker.plc_manager.read_data(db_number=db_number, start=start, size=size)
        if data and isValid(broker):
            broker.data_ready.emit((cache_key, data))
