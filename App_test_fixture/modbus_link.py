# -*- coding: utf-8 -*-
"""把 ``common/com/modbus`` 接到 :class:`~App_test_fixture.datasource.ModbusDataSource`。

``fixture_config.MODBUS_REGISTER_MAP`` 描述「点位 → 寄存器」，本模块负责
**地址换算、批量读、按类型编解码、控件回写**。业务侧仍然只认
``valuesChanged`` / ``write``，一行都不用改。

.. code-block:: python

    from App_test_fixture.modbus_link import ModbusLink

    src = ModbusDataSource(MODBUS_REGISTER_MAP)
    link = ModbusLink(ip="192.168.1.10")     # 或 cfg.MODBUS_IP
    if link.connect():
        link.attach(src)                    # 注入 reader / writer
    src.start()

也可以直接用 ``fixture_app --source modbus --ip 192.168.1.10``。

两条硬规则：

* **40001 是 4xxxx 编号，不是协议地址**。pymodbus 的
  ``read_holding_registers(address=...)`` 用 0-based，所以默认
  ``MODBUS_ADDRESS_MODE="4xxxx"`` 下 40001 → 0；若设备按编号寻址，
  把开关改成 ``"raw"``（详见 :func:`protocol_address`）。
* **一次读一整块，不逐点读**。43 个点位逐个请求会把 200ms 轮询打爆；
  这里按 offset 求最小/最大跨度，分块（每块 ≤120 字）批量读后本地切片解码。
"""

from __future__ import annotations

import struct
import sys
from collections import defaultdict
from typing import Any

from PySide6.QtCore import QObject

from . import fixture_config as cfg

from common.com.modbus import get_bool, set_bool, get_int, get_double, get_float
from common.com.modbus import set_int, set_float, set_double

# ---------------------------------------------------------------- 纯函数（可单测）
def protocol_address(offset: int, *, start: int | None = None,
                     mode: str | None = None) -> int:
    """「相对 40001 的字偏移」→ pymodbus 的 0-based 协议地址。

    ``"4xxxx"``：``offset + MODBUS_START - 40001``，即 40001 → 0；
    ``"raw"``　：``offset + MODBUS_START``，即 40001 → 40001。
    """
    base = int(cfg.MODBUS_START if start is None else start)
    m = cfg.MODBUS_ADDRESS_MODE if mode is None else mode
    if m == "4xxxx":
        return int(offset) + base - 40001
    if m == "raw":
        return int(offset) + base
    raise ValueError(f"未知 MODBUS_ADDRESS_MODE：{m!r}（可选 4xxxx / raw）")


def width(spec: dict) -> int:
    """该点位占几个 16 位字。"""
    kind = spec["type"]
    if kind in ("float32", "uint32", "int32"):
        return 2
    if kind == "double64":
        return 4          # struct 'd' = 8 字节 = 4 个 Modbus 字
    if kind == "string":
        return max(1, int(spec.get("words", 1)))
    return 1


def _word_order(spec: dict) -> str:
    return str(spec.get("word_order", cfg.MODBUS_FLOAT_WORD_ORDER))


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes", "是", "ok")
    return bool(value)


DEBUG_WRITE = False

PLC_MANAGER_HEARTBEAT_ADDRESS = 1000


def _byte_bit(spec: dict) -> int:
    """``byte`` 点位在 16 位字里的位掩码。

    现场把一个 BOOL 数组按 BYTE 打包：一个寄存器放两个 BOOL，
    ``byte=0`` 用低字节 bit0（0x0001），``byte=1`` 用高字节 bit8（0x0100）。
    注意每个字节只用最低位，不是整个 0xFF 字节。
    """
    if "byte" not in spec:
        raise ValueError("byte 类型必须指定 byte=0/1")
    index = int(spec["byte"])
    if index not in (0, 1):
        raise ValueError(f"byte 必须是 0 或 1，得到 {index}")
    return 1 << (index * 8)


def overlap_conflicts(register_map: dict) -> dict[int, list[str]]:
    """返回同一寄存器被多个不同含义点位占用的地址。

    同一地址上多个 ``byte`` 点位、且 ``byte`` 值两两不同是合法的字节打包
    （两个 BOOL 共用一个字），不算冲突；其余重叠会让读值互相串、写命令
    覆盖状态字，必须报出来。
    """
    occ: dict[int, list[tuple[str, dict]]] = defaultdict(list)
    for key, spec in register_map.items():
        lo = int(spec["offset"])
        for addr in range(lo, lo + width(spec)):
            occ[addr].append((key, spec))
    bad: dict[int, list[str]] = {}
    for addr, entries in occ.items():
        if len(entries) < 2:
            continue
        packed = (all(s["type"] == "byte" for _, s in entries) and
                  len({int(s.get("byte", -1)) for _, s in entries}) == len(entries))
        if not packed:
            bad[addr] = [k for k, _ in entries]
    return dict(sorted(bad.items()))


def heartbeat_conflicts(register_map: dict,
                        *, enabled: bool | None = None) -> list[tuple[str, int]]:
    """返回与 PLCManager 心跳寄存器冲突的 ``(点位名, 协议地址)``。

    ``common/com/modbus/modbus_plc_manager.py`` 的心跳线程每 500ms 执行
    ``write_registers(1000, seq)``。若某点位占住协议地址 1000，它的值会被
    每秒覆盖两次——而且 double64 占 4 个字，被改的是最高 16 位，
    读数会变成极小值 / 0，很难一眼看出是心跳干的。
    """
    if enabled is None:
        enabled = bool(cfg.MODBUS_USE_PLC_MANAGER)
    if not enabled:
        return []
    hits: list[tuple[str, int]] = []
    for key, spec in register_map.items():
        lo = protocol_address(int(spec["offset"]))
        if lo <= PLC_MANAGER_HEARTBEAT_ADDRESS < lo + width(spec):
            hits.append((key, lo))
    return hits


def _ordered_words(words: list[int], spec: dict) -> list[int]:
    """在「PLC 寄存器顺序」和「IEEE754 大端字序」之间转换。

    现场实测 12.5 的 LREAL 占 4 个寄存器 ``[0, 0, 0, 0x4029]``：
    低字在前，但**字内字节仍是大端**（0x4029 不是 0x2940）。
    所以 little = 整个字列表反序，不是「两两交换」——float32 只有 2 字时
    两者恰好一样，double64 两两交换会解出 5.3e-315。
    反序是自逆运算，encode / decode 共用本函数即可保证严格互逆。
    """
    return list(reversed(words)) if _word_order(spec) == "little" else list(words)


def decode(spec: dict, words: list[int] | tuple[int, ...]) -> Any:
    """把读到的 16 位字列表解成逻辑值（不含地址换算）。"""
    w = [int(x) & 0xFFFF for x in words]
    kind = spec["type"]
    scale = float(spec.get("scale", 1.0))
    if kind == "bit":
        return bool(w[0] & (1 << int(spec["bit"])))
    if kind == "bool":
        return bool(w[0])
    
    if kind == "byte":
        # 非法 byte 索引由 _byte_bit 抛 ValueError，不要静默返回 False，
        # 否则配置写错时界面只会一直显示「灭」，极难定位。
        return bool(w[0] & _byte_bit(spec))
    
    if kind == "uint16":
        return w[0] 
    if kind == "int16":
        return struct.unpack(">h", struct.pack(">H", w[0]))[0] 

    if kind == "uint32":
        a, b = _ordered_words(w[:2], spec)
        return ((a << 16) | b) 
    
    if kind == "float32":
        a, b = _ordered_words(w[:2], spec)
        return struct.unpack(">f", struct.pack(">HH", a, b))[0] * scale

    if kind == "double64":
        a, b, c, d = _ordered_words(w[:4], spec)
        return struct.unpack(">d", struct.pack(">HHHH", a, b, c, d))[0] * scale

    if kind == "string":
        raw = b"".join(struct.pack(">H", x) for x in w)
        return raw.split(b"\x00", 1)[0].decode("ascii", "ignore")
    raise ValueError(f"未知寄存器类型：{kind!r}")





def encode(spec: dict, value: Any) -> list[int]:
    """把逻辑值编成要写回的 16 位字列表（不含地址换算）。"""
    kind = spec["type"]
    scale = float(spec.get("scale", 1.0)) or 1.0
    if kind in ("bool", "bit"):
        return [1 if _truthy(value) else 0]
    
    if kind == "byte":
        # 只产出「目标位」的字，不含寄存器里其它位；实际写入由
        # ModbusLink.write() 读-改-写合并，保留同一字里的另一个字节。
        return [_byte_bit(spec) if _truthy(value) else 0]
    
    if kind in ("int16", "uint16"):
        n = int(round(float(value)))
        n = (max(-32768, min(32767, n)) if kind == "int16"
             else max(0, min(65535, n)))
        return [n & 0xFFFF]

    if kind in ("int32", "uint32"):
        n = int(round(float(value) ))
        n = (max(-2147483648, min(2147483647, n)) if kind == "int32"
             else max(0, min(4294967295, n)))
        words = [(n >> 16) & 0xFFFF, n & 0xFFFF]
        return _ordered_words(words, spec)
    
    if kind == "float32":
        # '>d' 是 8 字节 double，用 '>HH' 解 4 字节会抛 struct.error；
        # float32 必须用 '>f'（4 字节 / 2 个 Modbus 字）。
        words = list(struct.unpack(
            ">HH", struct.pack(">f", float(value) / scale)))
        return _ordered_words(words, spec)

    if kind == "double64":
        # 现场 PLC 的 LREAL 是低字在前（12.5 = [0,0,0,0x4029]），
        # 但字内字节仍是大端。common.set_double() 的 [0,0,0,0x2940]
        # 连字内字节都反了，不能用；这里统一 '>d' 编码再按字序反排。
        words = list(struct.unpack(
            ">HHHH", struct.pack(">d", float(value) / scale)))
        return _ordered_words(words, spec)
    
    if kind == "string":
        n = width(spec) * 2
        data = str(value).encode("ascii", "ignore")[:n]
        data += b"\x00" * (n - len(data))
        return list(struct.unpack(">" + "H" * width(spec), data))
    raise ValueError(f"未知寄存器类型：{kind!r}")


# ---------------------------------------------------------------- 客户端适配
class _PLCManagerClient:
    """把 ``PLCManager.read_data/write_data`` 适配成 ``ModbusClient`` 的接口。

    ``PLCManager`` 额外提供心跳与断线重连；心跳会周期写寄存器 1000，
    确认该地址不与现场数据区冲突再启用 ``MODBUS_USE_PLC_MANAGER``。
    """

    def __init__(self, manager) -> None:
        self.manager = manager
        self.connected = False

    def connect(self, ip: str, port: int = 502, timeout: float = 1.0) -> bool:
        self.connected = bool(self.manager.connect_to_plc())
        return self.connected

    def disconnect(self) -> None:
        try:
            self.manager.stop_heartbeat()
            self.manager.disconnect()
        finally:
            self.connected = False

    def read_holding_registers(self, address: int, count: int = 1, unit: int = 1):
        return self.manager.read_data(address, count)

    def write_registers(self, address: int, values, unit: int = 1) -> bool:
        return bool(self.manager.write_data(address, values))


class ModbusLink(QObject):
    """轮询式接入：``attach(source)`` 会注入 reader / writer 并保活自身。

    ``client`` 可注入任意实现了 ``connect / disconnect /
    read_holding_registers / write_registers`` 的对象（回归测试用假客户端）。
    """

    def __init__(self, *, ip: str | None = None, port: int | None = None,
                 unit: int | None = None, timeout: float | None = None,
                 client=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.ip = str(ip if ip is not None else cfg.MODBUS_IP)
        self.port = int(port if port is not None else cfg.MODBUS_PORT)
        self.unit = int(unit if unit is not None else cfg.MODBUS_UNIT)
        self.timeout = float(timeout if timeout is not None else cfg.MODBUS_TIMEOUT)
        self._client = client

    # -- 生命周期 -------------------------------------------------------
    def _make_client(self):
        if cfg.MODBUS_USE_PLC_MANAGER:
            from common.com.modbus import PLCManager
            return _PLCManagerClient(PLCManager(None, self.ip))
        from common.com.modbus.modbus import ModbusClient
        return ModbusClient()

    def connect(self) -> bool:
        if not self.ip:
            return False
        hits = heartbeat_conflicts(cfg.MODBUS_REGISTER_MAP)
        if hits:
            names = ", ".join(k for k, _ in hits)
            print(f"[modbus] 警告：PLCManager 心跳每 500ms 写寄存器 1000，"
                  f"与点位 {names} 冲突；建议设 "
                  f"MODBUS_USE_PLC_MANAGER=False 或把该点位挪到别的地址",
                  file=sys.stderr)
        overlaps = overlap_conflicts(cfg.MODBUS_REGISTER_MAP)
        if overlaps:
            preview = "; ".join(
                f"{a}:" + ",".join(k.rsplit(".", 1)[-1] for k in names[:4])
                for a, names in list(overlaps.items())[:4])
            print(f"[modbus] 警告：{len(overlaps)} 个寄存器被不同点位重叠占用 "
                  f"({preview} ...)；写命令会覆盖同地址的状态/数值",
                  file=sys.stderr)
        if self._client is None:
            self._client = self._make_client()
        return bool(self._client.connect(self.ip, self.port, self.timeout))

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
        self._client = None

    def is_connected(self) -> bool:
        return bool(self._client is not None and
                    getattr(self._client, "connected", True))

    def attach(self, source) -> None:
        """接上 ``ModbusDataSource``；挂到 source 上避免被 GC。"""
        source.set_reader(self.read)
        source.set_writer(self.write)
        source._modbus_link = self
        self.setParent(source)

    # -- 读：一次读整块，本地切片 ---------------------------------------
    def _read_block(self, offset: int, count: int) -> list[int] | None:
        out: list[int] = []
        for rel in range(0, count, 120):      # pymodbus 单次最多 125 字
            n = min(120, count - rel)
            chunk = self._client.read_holding_registers(
                protocol_address(offset + rel), count=n, unit=self.unit)
            if chunk is None or len(chunk) < n:
                return None
            out.extend(int(v) & 0xFFFF for v in chunk[:n])
        return out

    def read(self, register_map: dict) -> dict:
        """``set_reader`` 的回调：``fn(register_map) -> {点位名: 值}``。"""
        if not self.is_connected():
            return {}
        readable = [(key, spec) for key, spec in register_map.items()
                    if "r" in str(spec.get("access", "r"))]
        if not readable:
            return {}
        lo = min(int(spec["offset"]) for _, spec in readable)
        hi = max(int(spec["offset"]) + width(spec) for _, spec in readable)
        words = self._read_block(lo, hi - lo)
        if words is None:
            return {}
        values: dict[str, Any] = {}
        for key, spec in readable:
            start = int(spec["offset"]) - lo
            chunk = words[start:start + width(spec)]
            if len(chunk) < width(spec):
                continue
            try:
                values[key] = decode(spec, chunk)
                

            except (ValueError, IndexError, struct.error):
                continue
        return values

    # -- 写：控件回写 ---------------------------------------------------
    def write(self, key: str, value: Any, spec: dict) -> bool:
        """``set_writer`` 的回调：``fn(key, value, spec) -> bool``。"""
        if not self.is_connected():
            return False
        if "w" not in str(spec.get("access", "r")):
            return False                       # 只读点位不允许写
        address = protocol_address(int(spec["offset"]))
        unit = int(spec.get("unit", self.unit))
        kind = spec["type"]
        try:
            if kind in ("bit", "byte"):
                # 位 / 字节写要保留同一字里的其它位：读-改-写。
                # 掩码先算好再读，非法配置不会白跑一次请求。
                mask = ((1 << int(spec["bit"])) if kind == "bit"
                        else _byte_bit(spec))
                current = self._client.read_holding_registers(
                    address, count=1, unit=unit)
                if current is None or not len(current):
                    return False
                word = int(current[0]) & 0xFFFF
                # 位或 / 位与：幂等、不进位、不产生负数，另一字节原样保留。
                # 原来的 += / -= 会进位污染、重复写累加；且 byte=0 时
                # index_value=0，低字节根本写不进去。
                word = ((word | mask) if _truthy(value)
                        else (word & ~mask)) & 0xFFFF
                values = [word]
            else:
                values = encode(spec, value)
        except (ValueError, TypeError, KeyError, struct.error):
            return False
        if DEBUG_WRITE:
            print(f"[modbus] 写 {key}={value} → {values} @ {address}")
        return bool(self._client.write_registers(address, values, unit=unit))
