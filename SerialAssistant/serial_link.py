"""串口链路层：把 ``QSerialPort`` 收成一个有明确契约的小类。

约定
----
* 只负责端口配置、打开/关闭、字节收发，不碰任何 UI 控件。
* 所有 IO 都是 Qt 信号驱动的异步操作，调用 ``write()`` 立即返回。
* ``open()`` 用 ``(bool, str)`` 返回结果，不用异常传递用户可见错误；
  运行期异常统一走 ``failed`` 信号。
* 端口枚举返回 ``(端口名, 展示文本)``，展示文本带描述/厂商便于区分多个同款设备。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QIODevice, QObject, Signal
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo

# 常用波特率；波特率下拉框可编辑，非标准值也能填。
BAUD_RATES = (
    1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200,
    230400, 460800, 921600,
)
DATA_BITS = (5, 6, 7, 8)

# (界面文案, 内部 key)
PARITY_CHOICES = (
    ("无校验 (N)", "N"),
    ("偶校验 (E)", "E"),
    ("奇校验 (O)", "O"),
    ("空校验 (S)", "S"),
    ("标志校验 (M)", "M"),
)
STOP_BITS = (
    ("1", 1.0),
    ("1.5", 1.5),
    ("2", 2.0),
)
FLOW_CHOICES = (
    ("无", "none"),
    ("硬件 RTS/CTS", "hardware"),
    ("软件 XON/XOFF", "software"),
)

_DATA_BITS_MAP = {
    5: QSerialPort.DataBits.Data5,
    6: QSerialPort.DataBits.Data6,
    7: QSerialPort.DataBits.Data7,
    8: QSerialPort.DataBits.Data8,
}
_PARITY_MAP = {
    "N": QSerialPort.Parity.NoParity,
    "E": QSerialPort.Parity.EvenParity,
    "O": QSerialPort.Parity.OddParity,
    "S": QSerialPort.Parity.SpaceParity,
    "M": QSerialPort.Parity.MarkParity,
}
_STOP_BITS_MAP = {
    1.0: QSerialPort.StopBits.OneStop,
    1.5: QSerialPort.StopBits.OneAndHalfStop,
    2.0: QSerialPort.StopBits.TwoStop,
}
_FLOW_MAP = {
    "none": QSerialPort.FlowControl.NoFlowControl,
    "hardware": QSerialPort.FlowControl.HardwareControl,
    "software": QSerialPort.FlowControl.SoftwareControl,
}

# 出现这些错误说明设备已经不可用了，链路自动关闭，避免界面停在「已打开」的假状态。
_FATAL_ERRORS = frozenset(
    e for e in (
        getattr(QSerialPort.SerialPortError, "DeviceNotFoundError", None),
        getattr(QSerialPort.SerialPortError, "ResourceError", None),
        getattr(QSerialPort.SerialPortError, "PermissionError", None),
    ) if e is not None
)


@dataclass(frozen=True)
class PortConfig:
    """一次打开串口所需的全部参数。"""

    port_name: str = ""
    baud_rate: int = 115200
    data_bits: int = 8
    parity: str = "N"
    stop_bits: float = 1.0
    flow_control: str = "none"

    def describe(self) -> str:
        parity_label = {key: label for label, key in PARITY_CHOICES}.get(self.parity, self.parity)
        flow_label = {key: label for label, key in FLOW_CHOICES}.get(self.flow_control, self.flow_control)
        return (f"{self.port_name}  {self.baud_rate} bps, {self.data_bits}{self.parity}"
                f"{self.stop_bits:g}, {parity_label}, 流控 {flow_label}")

    def apply_to(self, port: QSerialPort) -> str:
        """把配置写进 QSerialPort，返回空串表示成功，否则返回原因。"""
        port.setPortName(self.port_name)
        if not port.setBaudRate(self.baud_rate):
            return f"设备不支持波特率 {self.baud_rate}"
        port.setDataBits(_DATA_BITS_MAP.get(self.data_bits, QSerialPort.DataBits.Data8))
        port.setParity(_PARITY_MAP.get(self.parity, QSerialPort.Parity.NoParity))
        port.setStopBits(_STOP_BITS_MAP.get(self.stop_bits, QSerialPort.StopBits.OneStop))
        port.setFlowControl(_FLOW_MAP.get(self.flow_control, QSerialPort.FlowControl.NoFlowControl))
        return ""


class SerialLink(QObject):
    """异步串口链路。上层只需要接 4 个信号 + 调 3 个方法。

    信号：
        opened(str)       已打开，参数是配置摘要
        closed()          已关闭（正常关闭 / 设备被拔出后自动关闭）
        dataReceived(bytes)  收到一包数据
        bytesSent(int)    实际写到设备上的字节数
        failed(str)       错误说明（含打开失败以外的运行期异常）
    """

    opened = Signal(str)
    closed = Signal()
    dataReceived = Signal(bytes)
    bytesSent = Signal(int)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._port = QSerialPort(self)
        self._port.setReadBufferSize(0)  # 0 = 不限制，由上层决定显示上限
        self._closing = False
        self._port.readyRead.connect(self._on_ready_read)
        self._port.bytesWritten.connect(self._on_bytes_written)
        self._port.errorOccurred.connect(self._on_error)

    @property
    def is_open(self) -> bool:
        return self._port.isOpen()

    @property
    def port_name(self) -> str:
        return self._port.portName()

    @staticmethod
    def list_ports() -> list[tuple[str, str]]:
        """枚举当前系统串口，返回 ``[(端口名, 展示文本), ...]``。"""
        ports: list[tuple[str, str]] = []
        for info in QSerialPortInfo.availablePorts():
            name = info.portName()
            detail = " | ".join(
                part for part in (info.description().strip(), info.manufacturer().strip())
                if part
            )
            label = f"{name}  —  {detail}" if detail else name
            ports.append((name, label))
        return ports

    def open(self, cfg: PortConfig) -> tuple[bool, str]:
        """打开串口；返回 ``(是否成功, 提示文本)``，失败时不会留下半开状态。"""
        if not cfg.port_name:
            return False, "请先选择串口"
        if self.is_open:
            self.close()

        reason = cfg.apply_to(self._port)
        if reason:
            return False, reason
        if not self._port.open(QIODevice.OpenModeFlag.ReadWrite):
            err = self._port.errorString() or "未知错误"
            return False, f"打开 {cfg.port_name} 失败：{err}"

        summary = cfg.describe()
        self.opened.emit(summary)
        return True, f"已打开 {summary}"

    def close(self) -> None:
        """关闭串口；无论如何都会发出 ``closed``（仅当确实曾打开时）。"""
        if not self._port.isOpen():
            return
        self._closing = True
        try:
            self._port.close()
        finally:
            self._closing = False
        self.closed.emit()

    def write(self, data: bytes) -> tuple[int, str]:
        """写入字节，返回 ``(写入缓冲区的字节数, 错误文本)``。

        实际发出数量由 ``bytesSent`` 信号上报，统计发送字节请用它，
        不要用这里的返回值累加。
        """
        if not self._port.isOpen():
            return 0, "串口未打开"
        if not data:
            return 0, "发送内容为空"
        written = self._port.write(data)
        if written < 0:
            return 0, f"写入失败：{self._port.errorString() or '未知错误'}"
        return int(written), ""

    # ------------------------------------------------------------------ 内部槽

    def _on_ready_read(self) -> None:
        chunk = self._port.readAll()
        if chunk.size():
            self.dataReceived.emit(bytes(chunk))

    def _on_bytes_written(self, count: int) -> None:
        self.bytesSent.emit(int(count))

    def _on_error(self, error: QSerialPort.SerialPortError) -> None:
        if self._closing or error == QSerialPort.SerialPortError.NoError:
            return
        # 打开失败由 open() 的返回值负责提示，这里不重复弹一次。
        if not self._port.isOpen():
            return
        message = self._port.errorString() or str(error)
        if error in _FATAL_ERRORS:
            self.close()
            self.failed.emit(f"串口异常：{message}（已自动关闭，请检查设备是否被拔出）")
        else:
            self.failed.emit(f"串口异常：{message}")
