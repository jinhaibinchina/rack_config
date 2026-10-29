# import snap7
from . import my_modbus
from typing import Optional,List,Union

from PySide6.QtCore import QThread, QObject, Signal, Qt, Slot, QMutex
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QApplication


class PLCManager(QObject):

    connected_state_changed = Signal(bool)


    def __init__(self,parent=None, ip: str=""):
        super().__init__(parent)
        self.ip = ip
        self.client: Optional[my_modbus.ModbusClient] = None
        self.lock = QMutex()
        self.connected = False
        
        self.heartbeat_active = False
        self.hmi_seq =0

       
  
    def connect_to_plc(self) -> bool:
        """连接 PLC"""
        self.lock.lock()
        try:
            if self.client is None:
                self.client = my_modbus.ModbusClient()
            if self.client.connect(self.ip):
                self.setConnected(True)
               
                print("连接成功")
            else:
                print(f"连接失败")
                self.client.disconnect()
                return False
            if not self.heartbeat_active:
                self.start_heartbeat()  # 连接成功后自动启动心跳线程
            return True
        except Exception as e:
            print(f"连接失败: {e}")
            return False
        finally:
            self.lock.unlock()

    def disconnect(self):
        """断开连接"""
        self.lock.lock()
        try:
            # self.heartbeat_active = False  # 停止心跳线程
            if self.client:
                try:
                    self.client.disconnect()
                except Exception as e:
                    print(f"断开连接出错: {e}")
                finally:
                    self.setConnected(False)
        finally:
            self.lock.unlock()
                    

    def __del__(self):
        """析构函数确保资源释放"""
        print("PLCManager 析构函数被调用")
        try:
            self.disconnect()
        except RuntimeError:
            # 解释器退出阶段 Qt 对象可能已销毁，此时无需再断开连接
            pass
        self.client = None
        print("del plc_manager")

    def isConnected(self):
        return self.connected
    def setConnected(self,state):
        self.connected = state
        self.connected_state_changed.emit(state)

    class HeartbeatThread(QThread):
        def __init__(self, manager, interval):
            super().__init__()
            self.manager = manager
            self.interval = interval
            self.running = True

        def run(self):
            while self.running and self.manager.heartbeat_active:
                # 先检查连接状态，不加锁
                if not self.manager.connected:
                    self.manager.reconnect()
                    # self.msleep(self.interval * 1000)
                    continue
                    
                # 准备数据时不加锁
                seq = (self.manager.hmi_seq + 1) % 256
                data = seq & 0xFFFF
                
                # 只在必要时加锁进行写操作
                self.manager.lock.lock()
                try:
                    if self.manager.client and self.manager.connected:
                        if False == self.manager.client.write_registers(1000, data):
                            self.manager.setConnected(False)
                           
                        self.manager.hmi_seq = seq
                finally:
                    self.manager.lock.unlock()
                
                # self.msleep(self.interval * 500)
                QThread.msleep(self.interval * 500)

        def stop(self):
            self.running = False
            self.wait(3000)

    def start_heartbeat(self, interval: int = 1):
        """启动心跳线程"""
        if self.heartbeat_active:
            return  # 如果心跳线程已经在运行，则不再创建
            
        self.heartbeat_active = True
        self.heartbeat_thread = self.HeartbeatThread(self, interval)
        print(f"启动心跳线程: {self.heartbeat_thread.objectName()}")
        self.heartbeat_thread.start()

    def reconnect(self):
        """断线重连机制"""
        # heartbeat_active 为 False 时立即退出，关闭窗口不会卡在重连循环里。
        while not self.connected and self.heartbeat_active:
            print("尝试重连...")
            self.disconnect()
            if self.connect_to_plc():
                break
            # 分片休眠，便于 stop_heartbeat() 及时打断重连
            for _ in range(50):
                if not self.heartbeat_active:
                    return
                QThread.msleep(100)

    def stop_heartbeat(self):
        """停止心跳线程（含断线重连循环），返回线程是否已退出。"""
        self.heartbeat_active = False
        thread = getattr(self, "heartbeat_thread", None)
        if thread is not None and thread.isRunning():
            thread.running = False
            return thread.wait(3000)
        return True

    def read_data(self, address: int, count: int) -> list:
        """读取数据（线程安全）"""
        self.lock.lock()
        try:
            if not self.connected:
                return None
            try:
                return self.client.read_holding_registers(address, count)
            except Exception as e:
                print(f"读取数据失败: {e}")
               
                self.setConnected(False)
                
                return None
        finally:
            self.lock.unlock()
            
    def write_data(self, db_address: int, data:  Union[List[int], int])->bool :
        """写入数据（线程安全）"""
        self.lock.lock()
        try:
            if not self.connected:
                return False
            try:                
                self.client.write_registers(db_address, data)
                return True
            except Exception as e:
                print(f"写入数据失败: {e}")      
                self.setConnected(False)
                return False
        finally:
            self.lock.unlock()
    
    def change_ip(self,ip:str)->bool:
        if ip == "...":
            return False
        self.disconnect()
        self.ip = ip
        return True

    
    def get_ip_address(self):
        return self.ip
    
    

if __name__ == "__main__":
    app = QApplication([])
    window = QWidget()
    window.setFixedSize(200,200)
    
    
    plc_manager = PLCManager(window,"192.168.3.233")
    
    plc_manager.start_heartbeat()
    
    window.show()
    app.exec()
