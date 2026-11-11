"""运行态数据源抽象：业务只认 ``valuesChanged`` / ``write``，不认具体协议。

现在默认跑 :class:`DemoDataSource`（模拟值，能直接看画面）。
以后接 Modbus 只要二选一，业务代码、绑定和图元联动**一行都不用改**：

**轮询式**（pymodbus / 自写客户端定时读）::

    src = ModbusDataSource(MODBUS_REGISTER_MAP)
    src.set_reader(lambda mapping: my_client.read_all(mapping))
    src.set_writer(lambda key, value, spec: my_client.write_one(spec, value))
    src.start()

**推送式**（客户端自带订阅回调）::

    src = ModbusDataSource(MODBUS_REGISTER_MAP, auto_poll=False)
    my_client.on_data = lambda values: src.submit(values)
    src.start()             # 只上报连接状态，不起轮询定时器

未注入 reader 时 ``start()`` 会明确发一条 warning 并停在那里，
不会假装连上、也不会静默喂假数据。
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Iterable

from PySide6.QtCore import QObject, QTimer, Signal

from .fixture_config import (
    AXIS_STATUS_FIELDS, AXIS_VALUE_FIELDS, AXIS_WRITE_FIELDS,
    DEMO_AMPLITUDE_MM, DEMO_INTERVAL_MS, DEMO_PERIOD_MS,
    MODBUS_POLL_MS, PARAM_DEFAULTS, TAG,
    axis_command_keys, axis_manual_key, axis_status_key, known_keys,
)






class DataSource(QObject):  
    """所有数据源的最小契约。

    ``valuesChanged(dict)`` 的 key 用 :data:`fixture_config.TAG` 里的逻辑点位名，
    value 可以是 bool / int / float / str；运行时会按目标自行转换。
    """

    valuesChanged = Signal(dict)
    connectionChanged = Signal(bool, str)
    message = Signal(str, str)          # (文本, 级别 info|warn|error)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # 包含工装点位 + 伺服轴面板的全部点位（见 fixture_config.known_keys）
        self._keys: list[str] = list(known_keys())
        self._running = False

    def keys(self) -> list[str]:
        return list(self._keys)

    def is_running(self) -> bool:
        return self._running

    def start(self, keys: Iterable[str] | None = None) -> None:
        if keys is not None:
            self._keys = list(keys)
        self._running = True

    def write(self, key: str, value: Any) -> bool:
        """控件回写。默认只读，返回 False。"""
        return False

    def stop(self) -> None:
        self._running = False


class DemoDataSource(DataSource):
    """模拟一个轴在正负行程之间往复，三个光电按位置触发。

    参数类点位只在首帧推一次，之后仅当用户改 spinbox 时才变化，
    避免每个 tick 都把整页控件重灌一遍。
    """

    def __init__(self, parent: QObject | None = None,
                 *, interval_ms: int = DEMO_INTERVAL_MS,
                 amplitude: float = DEMO_AMPLITUDE_MM,
                 period_ms: float = DEMO_PERIOD_MS) -> None:
        super().__init__(parent)
        self._interval = max(16, int(interval_ms))
        self._amplitude = float(amplitude)
        self._period = max(100.0, float(period_ms))
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval)
        self._timer.timeout.connect(self._tick)
        self._t0 = time.perf_counter()
        self._params = dict(PARAM_DEFAULTS)
        # 面板上三组写入行的「当前值」；用户点「写」会改这里并回灌
        self._axis_params = {
            axis_manual_key(field): float(seed)
            for (_, field, _), seed in zip(AXIS_WRITE_FIELDS, (100.0, 10.0, 50.0))
        }
        # 两个新增 text 图元的模拟计数：过原点 +1 回零次数，每个 tick +1 总计数。
        # 真实值由 Modbus 的 40001+201 / 40001+202 提供，这里只让 demo 也能看到联动。
        self._home_count = 0
        self._total_count = 0
        self._was_home = False

    def _axis_initial(self) -> dict:
        """首帧给伺服面板灌一份静态模拟状态，之后只推会变的那几个点。"""
        status = {
            "xConnected": True, "xDriveReady": True, "xEnabled": True,
            "xHomeDone": True, "xMoving": False, "xStandStill": True,
            "xErr": False, "xErrStop": False,
            "xPosLimit": False, "xNegLimit": False, "xReference": True,
        }
        value = {
            "fPositionNow": 0.0, "fVelocityNow": 0.0, "fTorqueNow": 0.0,
            "fFollowErrValue": 0.02, "iState": 3,
            "sDriverErrorID": "0", "sErrNote": "",
            "bControlMode": "CSV", "xServoOPmode": "OP",
        }
        batch = {axis_status_key(k): v
                 for k, v in status.items()
                 if k in {f for _, f, _ in AXIS_STATUS_FIELDS}}
        batch.update({axis_status_key(k): v
                      for k, v in value.items()
                      if k in {f for _, f, _ in AXIS_VALUE_FIELDS}})
        batch.update(self._axis_params)
        return batch

    def start(self, keys: Iterable[str] | None = None) -> None:
        super().start(keys)
        self._t0 = time.perf_counter()
        self.connectionChanged.emit(True, "demo://local")
        self.message.emit("模拟数据源已启动（未连接 PLC）", "info")
        batch = {TAG[k]: v for k, v in self._params.items() if k in TAG}
        batch[TAG["position"]] = 0.0
        batch[TAG["home_count_now"]] = self._home_count
        batch[TAG["total_count"]] = self._total_count
        batch.update(self._axis_initial())
        self.valuesChanged.emit(batch)
        self._timer.start()

    def _tick(self) -> None:
        elapsed = (time.perf_counter() - self._t0) * 1000.0
        phase = 2.0 * math.pi * (elapsed % self._period) / self._period
        position = self._amplitude * math.sin(phase)
        velocity = (2.0 * math.pi * self._amplitude
                    / (self._period / 1000.0) * math.cos(phase))
        neg_mm = float(self._params.get("neg_pos", -100))
        pos_mm = float(self._params.get("pos_pos", 100))
        span = max(1e-6, pos_mm - neg_mm)
        near_neg = position <= neg_mm + span * 0.06
        near_pos = position >= pos_mm - span * 0.06
        near_home = abs(position) <= span * 0.04
        if near_home and not self._was_home:
            self._home_count += 1
        self._was_home = near_home
        self._total_count += 1
        self.valuesChanged.emit({
            TAG["home_count_now"]: self._home_count,
            TAG["total_count"]: self._total_count,
            TAG["position"]: round(position, 3),
            TAG["neg_limit"]: near_neg,
            TAG["home"]: near_home,
            TAG["pos_limit"]: near_pos,
            # 伺服面板：位置/速度与工装滑块同源，灯跟着运动状态走
            axis_status_key("fPositionNow"): round(position, 3),
            axis_status_key("fVelocityNow"): round(velocity, 2),
            axis_status_key("fTorqueNow"): round(abs(velocity) * 0.03, 2),
            axis_status_key("fFollowErrValue"): round(abs(velocity) * 0.001, 3),
            axis_status_key("xMoving"): abs(velocity) > 0.5,
            axis_status_key("xStandStill"): abs(velocity) <= 0.5,
            axis_status_key("xPosLimit"): near_pos,
            axis_status_key("xNegLimit"): near_neg,
            axis_status_key("xReference"): near_home,
        })

    def write(self, key: str, value: Any) -> bool:
        """回写：工装参数 / 面板写入行更新模拟值，命令按钮只回一条日志。"""
        for short, full in TAG.items():
            if full == key and short in self._params:
                self._params[short] = value
                self.valuesChanged.emit({key: value})
                self.message.emit(f"模拟写入 {key} = {value}", "info")
                return True
        if key in self._axis_params:
            self._axis_params[key] = value
            self.valuesChanged.emit({key: value})
            self.message.emit(f"模拟写入 {key} = {value}", "info")
            return True
        if key in set(axis_command_keys()):
            self.message.emit(f"模拟命令下发 {key} = {value}", "info")
            return True
        return False

    def stop(self) -> None:
        self._timer.stop()
        super().stop()
        self.connectionChanged.emit(False, "demo://local")




class ModbusDataSource(DataSource):
    """Modbus 接入骨架：协议客户端由外部注入，本类只负责合流与生命周期。

    ``set_reader(fn)`` —— ``fn(register_map) -> {点位名: 值}``，按 poll_ms 调用。
    ``set_writer(fn)`` —— ``fn(key, value, spec) -> bool``，控件回写时调用。
    ``submit(values)`` —— 推送式客户端直接在回调里灌值（与 reader 可同时用）。
    """

    def __init__(self, register_map: dict[str, dict] | None = None,
                 *, poll_ms: int = MODBUS_POLL_MS, auto_poll: bool = True,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.register_map = dict(register_map or {})
        self.auto_poll = bool(auto_poll)
        self._accepted = known_keys()
        self._reader: Callable[[dict], dict] | None = None
        self._writer: Callable[[str, Any, dict], bool] | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(max(16, int(poll_ms)))
        self._timer.timeout.connect(self._poll)

    def set_reader(self, fn: Callable[[dict], dict]) -> None:
        self._reader = fn

    def set_writer(self, fn: Callable[[str, Any, dict], bool]) -> None:
        self._writer = fn

    def start(self, keys: Iterable[str] | None = None) -> None:
        super().start(keys)
        if not self.register_map:
            self.connectionChanged.emit(False, "modbus://unconfigured")
            self.message.emit(
                "MODBUS_REGISTER_MAP 为空：请在 fixture_config 填点位→寄存器映射",
                "warn")
            return
        if self.auto_poll and self._reader is None:
            self.connectionChanged.emit(False, "modbus://no-reader")
            self.message.emit(
                "未注入 reader：调用 set_reader(fn) 或改用推送式 "
                "ModbusDataSource(..., auto_poll=False) + submit(values)",
                "warn")
            return
        self.connectionChanged.emit(True, "modbus://ready")
        self.message.emit(
            f"Modbus 数据源就绪（{len(self.register_map)} 个点位，"
            f"{'轮询' if self.auto_poll else '推送'}模式）", "info")
        if self.auto_poll:
            self._timer.start()
            self._poll()

    def _poll(self) -> None:
        if self._reader is None:
            return
        try:
            values = self._reader(self.register_map) or {}
        except Exception as exc:                       # 客户端异常不能打死 UI
            self.message.emit(f"Modbus 读取失败：{exc}", "error")
            self.connectionChanged.emit(False, "modbus://read-error")
            return
        self.submit(values)

    def submit(self, values: dict) -> None:
        """外部推送一批值（推送式接入的主入口）。"""
        clean = {str(k): v for k, v in (values or {}).items()
                 if str(k) in self._accepted}
        if clean:
            self.valuesChanged.emit(clean)

    def write(self, key: str, value: Any) -> bool:
        spec = self.register_map.get(key)
        # print(f"[modbus] 回写 {key}={value} spec={spec}")




        if self._writer is None or spec is None:
            self.message.emit(
                f"回写被忽略：{key} 无寄存器映射或未注入 writer", "warn")
            return False
        try:
            ok = bool(self._writer(key, value, spec))
           
        except Exception as exc:
            self.message.emit(f"Modbus 写入失败 {key}：{exc}", "error")
            return False
        if ok:
            self.message.emit(f"写入成功 {key} = {value}", "info")
        return ok

    def stop(self) -> None:
        self._timer.stop()
        super().stop()
        self.connectionChanged.emit(False, "modbus://stopped")


class NullDataSource(DataSource):
    """不产生数据，用于只检查画面 / 回归测试。"""

    def start(self, keys: Iterable[str] | None = None) -> None:
        super().start(keys)
        self.connectionChanged.emit(False, "none")
        self.message.emit("未启用数据源，画面为静态初始值", "info")


def make_source(kind: str = "demo", parent: QObject | None = None,
                **kwargs) -> DataSource:
    """按名字造数据源：``demo`` / ``none`` / ``modbus``。"""
    kind = (kind or "demo").lower()
    if kind == "demo":
        return DemoDataSource(parent, **kwargs)
    if kind == "none":
        return NullDataSource(parent)
    if kind == "modbus":
        from .fixture_config import MODBUS_REGISTER_MAP
        return ModbusDataSource(
            kwargs.pop("register_map", MODBUS_REGISTER_MAP),
            poll_ms=kwargs.pop("poll_ms", MODBUS_POLL_MS),
            auto_poll=kwargs.pop("auto_poll", True), parent=parent, **kwargs)
    raise ValueError(f"未知数据源：{kind!r}（可选 demo / none / modbus）")
