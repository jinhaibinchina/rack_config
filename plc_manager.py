import snap7
import threading
from typing import Optional, Dict

class PLCManager:
    def __init__(self, ip: str, rack: int, slot: int):
        self.ip = ip
        self.rack = rack
        self.slot = slot
        self.client: Optional[snap7.client.Client] = None
        self.lock = threading.Lock()
        self.connected = False
        self.thread = None
        self.heartbeat_active = False
        self.hmi_seq =0

    def connect(self) -> bool:
        """连接 PLC"""
        with self.lock:
            try:
                self.client = snap7.client.Client()
                self.client.connect(self.ip, self.rack, self.slot)
                
                self.connected = True
                
               
                return True
            except Exception as e:
                print(f"连接失败: {e}")
                return False

    def disconnect(self):
        """断开连接"""
        with self.lock:
            if self.client:
                self.client.disconnect()
                self.connected = False

    def isConnected(self):
        return self.connected

    def start_heartbeat(self, interval: int = 1):
        """启动心跳线程"""
        self.heartbeat_active = True
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, 
            args=(interval,),
            daemon=True
        )
        heartbeat_thread.start()
        self.thread = heartbeat_thread

    def stop_thread(self):
        self.heartbeat_active = False
        self.disconnect()
        print('断开连接')
        self.thread.join(1000)
        print('线程结束')

    def _heartbeat_loop(self, interval: int):
        """心跳循环（独立线程）"""
        while self.heartbeat_active:
            try:
                with self.lock:
                    if self.client:

                        # 发送心跳信号（示例：读取一个保持寄存器）
                        
                        self.hmi_seq = (self.hmi_seq + 1) % 256
                        data = bytearray(1)
                        data[0] = self.hmi_seq & 0xFF
                        self.client.db_write(21,0,data)

                if not self.connected:
                    self.reconnect()
            except Exception as e:
                print(f"心跳异常: {e}")
                self.connected = False
                self.reconnect()
            finally:
                threading.Event().wait(interval)

    def reconnect(self):
        """断线重连机制"""
        while not self.connected:
            print("尝试重连...")
            self.disconnect()
            if self.connect():
                break
            threading.Event().wait(5)

    def read_data(self, db_number: int, start: int, size: int) -> Optional[bytes]:
        """读取数据（线程安全）"""
        with self.lock:
            if not self.connected:
                return None
            try:
                #return self.client.read_area(area, db_number, start, size)
                return self.client.db_read(db_number, start, size)
            except Exception as e:
                print(f"读取数据失败: {e}")
                self.connected = False
                return None
            
    def write_data(self, db_number: int, start: int, data: bytearray) :
        """写入数据（线程安全）"""
        with self.lock:
            if not self.connected:
                return False
            try:                
                self.client.db_write(db_number, start, data)
                return True
            except Exception as e:
                print(f"写入数据失败: {e}")      
                self.connected = False
                
                return False
    
    def change_ip(self,ip:str)->bool:
        if ip == "...":
            return False
        self.ip = ip
        self.disconnect()
        return True

    
    def get_ip_address(self):
        return self.ip
    
    # def download(self,data,block_num):
        
    #     self.client.download(data=data,block_num=block_num)
    #     self.client.plc_hot_start()
    def stop_plc(self):
        print(self.client.plc_stop())
        print("stop plc")
    def start_plc(self):
        print(self.client.plc_hot_start())


