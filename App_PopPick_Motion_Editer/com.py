import struct,time
from .complier import Instruction

from typing import List, Optional, Dict

from PySide6.QtCore import Signal, QObject, QThread

try:
    from pymodbus.client import ModbusTcpClient
    HAS_PYMUDOBUS = True
except ImportError:
    HAS_PYMUDOBUS = False

class ModbusClient:
    REG_PROGRAM_BASE = 41000
    REG_PROGRAM_MAX = 45000
    REG_POINT_BASE = 45100
    REG_POINT_STRIDE = 12
    REG_VAR_BASE = 46220
    DI_BASE = 46400
    DO_BASE = 46440
    REG_SYSTEM_IN_BASE = 46000
    REG_SYSTEM_OUT_BASE = 46100
    REG_TCP_POS_BASE = 46200      # 实时TCP坐标起始地址
    REG_TCP_POS_COUNT = 6         # x,y,z 各2个寄存器(float32)

    def __init__(self):
        self.client = None
        self.host = "192.168.1.88"
        self.port = 502
        self.unit = 1
        self._fail_count = 0

        self.program_test_lines = None

    def trans_program_texts(self,texts:List):

        self.program_test_lines = texts

    def connect(self, host, port=502, unit=1):
        if not HAS_PYMUDOBUS:
            return False
        self.host = host
        self.port = port
        self.unit = unit
        try:
            for kwargs in [
                {"host": host, "port": port, "timeout": 2, "unit": unit},
                {"host": host, "port": port, "timeout": 2, "unit_id": unit},
                {"host": host, "port": port, "timeout": 2, "slave": unit},
                {"host": host, "port": port, "timeout": 2},
            ]:
                try:
                    self.client = ModbusTcpClient(**kwargs)
                    break
                except TypeError:
                    continue
            else:
                self.client = ModbusTcpClient(host, port)
            for attr in ("unit_id", "slave", "unit"):
                if hasattr(self.client, attr):
                    try:
                        setattr(self.client, attr, unit)
                    except Exception:
                        pass
            ok = self.client.connect()
            if ok:
                self._fail_count = 0
            return ok
        except Exception as e:
            print(f"Modbus connect error: {e}")
            return False

    def disconnect(self):
        if self.client:
            self.client.close()
            self.client = None

    def is_connected(self):
        return self.client is not None and self.client.connected

    def check_and_reconnect(self):
        if not self.is_connected() and self.host:
            try:
                self.client = ModbusTcpClient(host=self.host, port=self.port, timeout=2)
                return self.client.connect()
            except Exception:
                return False
        return self.is_connected()

    @staticmethod
    def float32_to_regs(val):
        b = struct.pack(">f", val)
        return [int(b[0]) << 8 | int(b[1]), int(b[2]) << 8 | int(b[3])]

    @staticmethod
    def regs_to_float32(regs):
        if len(regs) < 2:
            return 0.0
        b = bytes([(regs[0] >> 8) & 0xFF, regs[0] & 0xFF, (regs[1] >> 8) & 0xFF, regs[1] & 0xFF])
        return struct.unpack(">f", b)[0]

    def _write_regs(self, address, values, slave_id):
        for kwargs in ({"slave": slave_id}, {"unit": slave_id}, {"unit_id": slave_id}, {}):
            try:
                return self.client.write_registers(address, values=values, **kwargs)
            except TypeError as e:
                msg = str(e).lower()
                if "unexpected keyword argument" in msg or "positional arguments" in msg:
                    continue
                raise
        raise RuntimeError("write_registers 调用失败，请检查 pymodbus 版本")

    def _read_regs(self, address, count, slave_id):
        for kwargs in ({"slave": slave_id}, {"unit": slave_id}, {"unit_id": slave_id}, {}):
            try:
                return self.client.read_holding_registers(address, count=count, **kwargs)
            except TypeError as e:
                msg = str(e).lower()
                if "unexpected keyword argument" in msg or "positional arguments" in msg:
                    continue
                raise
        raise RuntimeError("read_holding_registers 调用失败，请检查 pymodbus 版本")

    def write_program(self, program:List[Instruction]):
        if not self.is_connected():
            return False
        regs = []
        for inst in program:
            regs.extend(inst.to_regs())
        if len(regs) > (self.REG_PROGRAM_MAX - self.REG_PROGRAM_BASE):
            raise ValueError("程序过长")
        MAX_WRITE_COUNT = 120
        try:
            for i in range(0, len(regs), MAX_WRITE_COUNT):
                chunk = regs[i:i + MAX_WRITE_COUNT]
                addr = self.REG_PROGRAM_BASE + i
                resp = self._write_regs(addr, chunk, self.unit)
                if resp.isError():
                    print(f"Write chunk error at {addr}: {resp}")
                    return False
            resp = self._write_regs(45000, [len(program),1], self.unit)
            if resp.isError():
                print(f"Write len(program) error at 45000: {resp}")
                return False

            self.write_text_lines(self.program_test_lines)

            
            return True
        except Exception as e:
            print(f"Write program error: {e}")
            self._fail_count += 1
            return False

    def read_program(self, count):
        if not self.is_connected():
            return []
        total_regs = count * 9
        MAX_READ_COUNT = 120
        all_regs = []
        try:
            for i in range(0, total_regs, MAX_READ_COUNT):
                chunk_size = min(MAX_READ_COUNT, total_regs - i)
                addr = self.REG_PROGRAM_BASE + i
                resp = self._read_regs(addr, chunk_size, self.unit)
                if resp.isError():
                    print(f"Read chunk error at {addr}: {resp}")
                    return []
                all_regs.extend(resp.registers)
            program = []
            for i in range(0, len(all_regs), 9):
                chunk = all_regs[i:i+9]
                if len(chunk) < 9:
                    break
                program.append(Instruction.from_regs(chunk))
            return program
        except Exception as e:
            print(f"Read program error: {e}")
            return []

    def write_text_lines(self, lines: List[str], base_addr: int = 46500,
                         max_lines: int = 200, chars_per_line: int = 120) -> bool:
        """
        将字符串列表写入 PLC WSTRING 数组。
        
        汇川 AM521 WSTRING(150) 实际布局（从 Modbus 映射验证）：
        - 步长: 151 个寄存器 (302 字节)
        - reg0: CurLen (当前长度)
        - reg1~reg150: UTF-16-BE 字符数据
        - 无 MaxLen 字段
        """
        if not self.is_connected():
            return False

        stride = chars_per_line + 1          # 151
        # 地址溢出保护：Modbus 最大 65535
        max_possible = (65535 - base_addr) // stride
        if max_lines > max_possible:
            max_lines = max_possible

        lines = lines[:max_lines]
        all_regs = []

        for line in lines:
            line = line[:chars_per_line]
            encoded = line.encode('utf-16-be', errors='ignore')
            regs = []               

            for i in range(0, len(encoded), 2):
                if i + 1 < len(encoded):
                    val = (encoded[i] << 8) | encoded[i + 1]
                else:
                    val = encoded[i] << 8
                regs.append(val)

            while len(regs) < stride:        # 补零对齐
                regs.append(0)
            all_regs.extend(regs)

        # 剩余数组元素清零
        remaining = max_lines - len(lines)
        for _ in range(remaining):
            all_regs.extend([0] * stride)

        # 分批写入（120 个寄存器/包，避免报文过长）
        MAX_WRITE_COUNT = 120
        try:
            for i in range(0, len(all_regs), MAX_WRITE_COUNT):
                chunk = all_regs[i:i + MAX_WRITE_COUNT]
                addr = base_addr + i
                resp = self._write_regs(addr, chunk, self.unit)
                if resp.isError():
                    print(f"Write text chunk error at {addr}: {resp}")
                    return False
            return True
        except Exception as e:
            print(f"Write text lines error: {e}")
            return False

    def read_vars(self, count: int):
        """读取 V[0..count-1] 当前值，返回 list[float]；失败返回 None"""
        try:

            total_regs = count * 2
            all_regs = []
            MAX_READ_COUNT = 120
    
            try:
                for i in range(0, total_regs, MAX_READ_COUNT):
                    chunk_size = min(MAX_READ_COUNT, total_regs - i)
                    addr = self.REG_VAR_BASE + i
                    resp = self._read_regs(addr, chunk_size, self.unit)
                    
                    if resp.isError():
                        
                        return None
                    all_regs.extend(resp.registers)
            except Exception as e:
                print(f"Read text lines error: {e}")
                return None


            # 若 PLC 侧 V 寄存器为 float32（两个 16 位寄存器一个值）
            return [self.regs_to_float32(all_regs[i*2:i*2+2])
                    for i in range(count)]
            # 若 PLC 侧每寄存器直接存 int16（定点/放大整数），改为：
            # return [float(v) for v in rr.registers[:count]]
        except Exception:
            return None


    def read_dis(self, count: int):
        """读取 DI[0..count-1]，返回 list[int] (0/1)；失败返回 None"""
        try:
            rr = self._read_regs(self.DI_BASE, count, slave=self.unit)            
            if rr.isError():
                return None
            return [int(v) for v in rr[:count]]
        except Exception:
            return None

    def read_dos(self, count: int):
        """读取 DO[0..count-1]，返回 list[int] (0/1)；失败返回 None"""
        try:
            rr = self._read_regs(self.DO_BASE, count, slave=self.unit)
            if rr.isError():
                return None
            return [int(v) for v in rr[:count]]
        except Exception:
            return None

    def read_text_lines(self, base_addr: int = 46500, count: int = 200,
                        chars_per_line: int = 120) -> List[str]:
        """从 PLC 读取 WSTRING 数组，用于验证"""
        if not self.is_connected():
            return []

        stride = chars_per_line + 1
        total_regs = count * stride
        all_regs = []
        MAX_READ_COUNT = 120

        try:
            for i in range(0, total_regs, MAX_READ_COUNT):
                chunk_size = min(MAX_READ_COUNT, total_regs - i)
                addr = base_addr + i
                resp = self._read_regs(addr, chunk_size, self.unit)
                if resp.isError():
                    return []
                all_regs.extend(resp.registers)
        except Exception as e:
            print(f"Read text lines error: {e}")
            return []

        lines = []
        for i in range(count):
            offset = i * stride
            if offset >= len(all_regs):
                break
            cur_len = all_regs[offset]
            if cur_len <= 0 or cur_len > chars_per_line:
                lines.append("")
                continue

            chars = []
            for j in range(1, cur_len + 1):
                if offset + j < len(all_regs):
                    chars.append(chr(all_regs[offset + j]))
            lines.append("".join(chars))
        return lines
    
    def write_point(self, idx, pos):
        if not self.is_connected():
            return False
        addr = self.REG_POINT_BASE + idx * self.REG_POINT_STRIDE
        regs = []
        for key in ["x", "y", "z", "j1", "j2", "j3"]:
            regs.extend(self.float32_to_regs(float(pos.get(key, 0.0))))
        try:
            resp = self._write_regs(addr, regs, self.unit)
            return not resp.isError()
        except Exception as e:
            print(f"Write point error: {e}")
            return False

    def read_point(self, idx):
        if not self.is_connected():
            return None
        addr = self.REG_POINT_BASE + idx * self.REG_POINT_STRIDE
        try:
            resp = self._read_regs(addr, self.REG_POINT_STRIDE, self.unit)
            if resp.isError() or len(resp.registers) < self.REG_POINT_STRIDE:
                return None
            regs = resp.registers
            return {
                "x": self.regs_to_float32(regs[0:2]), "y": self.regs_to_float32(regs[2:4]),
                "z": self.regs_to_float32(regs[4:6]), "j1": self.regs_to_float32(regs[6:8]),
                "j2": self.regs_to_float32(regs[8:10]), "j3": self.regs_to_float32(regs[10:12]),
            }
        except Exception as e:
            print(f"Read point error: {e}")
            return None

    def read_system_in(self, offset, count):
        if not self.is_connected():
            return []
        try:
            resp = self._read_regs(self.REG_SYSTEM_IN_BASE + offset, count, self.unit)
            return resp.registers if not resp.isError() else []
        except Exception:
            return []

    def write_system_out(self, offset, values):
       
        if not self.is_connected():
            return False
        try:
            resp = self._write_regs(self.REG_SYSTEM_OUT_BASE + offset, values, self.unit)
            return not resp.isError()
        except Exception:
            return False

    def read_tcp_position(self, base_addr=None, use_float32=True):
        """读取 PLC 实时 TCP 坐标 (x,y,z)"""
        if not self.is_connected():
            return None
        if base_addr is None:
            base_addr = self.REG_TCP_POS_BASE
        try:
            if use_float32:
                resp = self._read_regs(base_addr, 6, self.unit)
                
                if resp and not resp.isError() and hasattr(resp, 'registers') and len(resp.registers) >= 6:
                    x = self.regs_to_float32(resp.registers[0:2])
                    y = self.regs_to_float32(resp.registers[2:4])
                    z = self.regs_to_float32(resp.registers[4:6])
                   
                    return (x, y, z)
            else:
                resp = self._read_regs(base_addr, 3, self.unit)
                if resp and not resp.isError() and hasattr(resp, 'registers') and len(resp.registers) >= 3:
                    def to_signed(v):
                        return v - 65536 if v > 32767 else v
                    x = to_signed(resp.registers[0])
                    y = to_signed(resp.registers[1])
                    z = to_signed(resp.registers[2])
                    return (float(x), float(y), float(z))
            
        except Exception as e:
            print(f"Read TCP position error: {e}")
        return None



# ==================== 信号桥接 ====================
class SignalBridge(QObject):
    position_updated = Signal(float, float, float)
    robot_sys_status_ipc_updated = Signal(int, int)

    log_message = Signal(str)
    status_changed = Signal(str)


# ==================== TCP 坐标读取工作线程 ====================
class TcpPositionWorker(QThread):
    def __init__(self, bridge: SignalBridge, modbus_client: ModbusClient, config: dict):
        super().__init__()
        self.bridge = bridge
        self.client = modbus_client
        self.cfg = config
        self.running = False
        self._last_pos = (0.0, 0.0, 0.0)

    def run(self):
        self.running = True
        self.bridge.status_changed.emit("TCP坐标读取中")
        while self.running:
            if self.client and self.client.is_connected():
                try:
                    pos = self.client.read_tcp_position(
                        self.cfg.get("reg_base"),
                        self.cfg.get("use_float32", True)
                    )
                    if pos:
                        x, y, z = pos
                        self._last_pos = (x, y, z)
                        self.bridge.position_updated.emit(x, y, z)
                except Exception as e:
                    self.bridge.log_message.emit(f"[TCP读取错误] {e}")

                try:
                    ipc_status = self.client.read_system_in(
                        2,
                        2)
                    
                    if ipc_status:
                        self.bridge.robot_sys_status_ipc_updated.emit(ipc_status[1],ipc_status[0])
                  
                except Exception as e:
                    self.bridge.log_message.emit(f"[TCP读取错误] {e}")
                
            time.sleep(self.cfg.get("interval", 200) / 1000.0)
        self.bridge.status_changed.emit("TCP坐标读取停止")

    def stop(self):
        self.running = False
        self.wait(2000)

    def get_last_pos(self):
        return self._last_pos