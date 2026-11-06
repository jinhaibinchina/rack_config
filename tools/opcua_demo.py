"""OPC UA 通信 demo（自带模拟服务器，无需真实 PLC 即可跑）。

演示四件事：

1. **订阅推送** —— 服务端值一变，界面立刻更新，本地不做任何轮询；
2. **同步读写** —— ``read`` / ``write`` 长得和 snap7 的 ``read_data`` /
   ``write_data`` 一样，UI 代码不用改成 asyncio 思维；
3. **自动重连** —— 点「停服务器」模拟 PLC 掉电，再点「起服务器」，
   观察状态灯自己恢复、订阅自己重建；
4. **类型正确** —— Boolean / Int16 / String 写入时按节点 DataType 收敛，
   不会因为写个 int 到 Int16 节点被服务端回 BadTypeMismatch。

跑法::

    # 自带模拟服务器（推荐先跑这个）
    .venv/Scripts/python.exe tools/opcua_demo.py

    # 连真实 PLC / KEPServerEX，自己填 endpoint
    .venv/Scripts/python.exe tools/opcua_demo.py --no-server ^
        --endpoint opc.tcp://192.168.1.10:4840

真实设备上要改的只有两处：``--endpoint``，以及 ``NODE_IDS`` 里的节点地址
（用 UaExpert 拖一个节点进去就能看到它真实的 NodeId）。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from common.com.opcua import OpcConfig, OpcUaManager, keep_alive_until_stopped
from tools.opcua_mock_server import MockOpcUaServer

#: 业务 key -> NodeId 字符串。
#:
#: 接真实 PLC 时把右边换成 UaExpert 里看到的地址即可，key 不用动——
#: 界面代码只认 key。Siemens S7-1500 自带的 OPC UA Server 一般是
#: ``ns=3;s="DB_Rack"."Lamp01"`` 这种带引号的形式。
NODE_IDS = {
    "lamp01": "ns=2;s=Lamp01",
    "lamp02": "ns=2;s=Lamp02",
    "lamp03": "ns=2;s=Lamp03",
    "lamp04": "ns=2;s=Lamp04",
    "fullcount": "ns=2;s=FullCount",
    "message": "ns=2;s=Message",
    "heartbeat": "ns=2;s=Heartbeat",
}


class LampIndicator(QWidget):
    """一个工业指示灯：圆点 + 名字。亮=绿，灭=灰。"""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._dot = QLabel()
        self._dot.setFixedSize(18, 18)
        self._title = QLabel(title)
        layout.addWidget(self._dot)
        layout.addWidget(self._title)
        layout.addStretch(1)
        self.set_state(False)

    def set_state(self, on: bool) -> None:
        color = "#22c55e" if on else "#374151"
        border = "#16a34a" if on else "#4b5563"
        self._dot.setStyleSheet(
            f"background:{color}; border:1px solid {border}; border-radius:9px;"
        )


class DemoWindow(QMainWindow):
    def __init__(self, endpoint: str, own_server: MockOpcUaServer | None) -> None:
        super().__init__()
        self.setWindowTitle("OPC UA Demo — AppsManagers")
        self.resize(760, 560)

        self._server = own_server
        self._mgr = OpcUaManager(
            OpcConfig(endpoint=endpoint),
            parent=self,
        )
        self._mgr.connected_changed.connect(self._on_connected)
        self._mgr.node_changed.connect(self._on_node_changed)
        self._mgr.node_error.connect(self._on_node_error)
        self._mgr.state_message.connect(self._log)

        self._lamps: dict[str, LampIndicator] = {}
        self._build_ui(endpoint)
        self._log(f"端点: {endpoint}")

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self, endpoint: str) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        # -- 连接 --
        conn_box = QGroupBox("连接")
        conn_row = QHBoxLayout(conn_box)
        self._endpoint_edit = QLineEdit(endpoint)
        self._connect_btn = QPushButton("连接")
        self._connect_btn.setFixedWidth(88)
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(14, 14)
        self._status_text = QLabel("未连接")
        connect_row = conn_row
        connect_row.addWidget(QLabel("端点"))
        connect_row.addWidget(self._endpoint_edit, 1)
        connect_row.addWidget(self._connect_btn)
        connect_row.addSpacing(10)
        connect_row.addWidget(self._status_dot)
        connect_row.addWidget(self._status_text)
        self._connect_btn.clicked.connect(self._toggle_connection)
        outer.addWidget(conn_box)

        # -- 订阅数据 --
        data_box = QGroupBox("订阅数据（服务端变化才推送，本地不轮询）")
        data_grid = QGridLayout(data_box)
        data_grid.setHorizontalSpacing(24)
        data_grid.setVerticalSpacing(6)
        for i in range(4):
            key = f"lamp0{i + 1}"
            lamp = LampIndicator(f"Lamp0{i + 1}")
            self._lamps[key] = lamp
            data_grid.addWidget(lamp, i // 2, i % 2)

        self._count_label = QLabel("--")
        self._count_label.setFont(QFont("Consolas", 20, QFont.Weight.Bold))
        self._hb_label = QLabel("--")
        self._hb_label.setFont(QFont("Consolas", 14))
        self._msg_label = QLabel("--")
        data_grid.addWidget(QLabel("满料计数"), 0, 2)
        data_grid.addWidget(self._count_label, 1, 2)
        data_grid.addWidget(QLabel("心跳（服务器每 500ms 自增）"), 2, 2)
        data_grid.addWidget(self._hb_label, 3, 2)
        data_grid.addWidget(QLabel("提示文本"), 4, 0)
        data_grid.addWidget(self._msg_label, 4, 1, 1, 2)
        outer.addWidget(data_box)

        # -- 写入 --
        toggle_btn = QPushButton("翻转 Lamp01")
        toggle_btn.clicked.connect(self._toggle_lamp)
        all_off_btn = QPushButton("全部熄灭")
        all_off_btn.clicked.connect(self._all_off)
        self._count_spin = QSpinBox()
        self._count_spin.setRange(-32768, 32767)
        self._count_spin.setValue(42)
        count_btn = QPushButton("写计数")
        count_btn.clicked.connect(lambda: self._write("fullcount", self._count_spin.value()))
        self._msg_edit = QLineEdit("hello opcua")
        msg_btn = QPushButton("写文本")
        msg_btn.clicked.connect(lambda: self._write("message", self._msg_edit.text()))
        server_btn = QPushButton("停服务器 / 起服务器")
        server_btn.setEnabled(self._server is not None)
        server_btn.clicked.connect(self._toggle_server)

        write_box = QGroupBox("写入（同步调用，返回 True/False）")
        write_outer = QVBoxLayout(write_box)
        write_outer.setSpacing(8)

        row1 = QHBoxLayout()
        row1.addWidget(toggle_btn)
        row1.addWidget(all_off_btn)
        row1.addStretch(1)
        row1.addWidget(server_btn)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("计数"))
        row2.addWidget(self._count_spin)
        row2.addWidget(count_btn)
        row2.addSpacing(18)
        row2.addWidget(QLabel("文本"))
        row2.addWidget(self._msg_edit, 1)
        row2.addWidget(msg_btn)

        write_outer.addLayout(row1)
        write_outer.addLayout(row2)
        outer.addWidget(write_box)

        # -- 日志 --
        log_box = QGroupBox("日志")
        log_layout = QVBoxLayout(log_box)
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(500)
        self._log_view.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self._log_view)
        outer.addWidget(log_box, 1)

        self._apply_status(False)

    # ------------------------------------------------------------------
    # 连接控制
    # ------------------------------------------------------------------
    def _toggle_connection(self) -> None:
        if self._mgr.is_connected() or self._mgr._thread is not None:
            self._log("主动断开…")
            stopped = self._mgr.stop(wait_ms=1500)
            if not stopped:
                # 线程没停住时绝不能让它随窗口销毁，否则 emit 就是段错误
                keep_alive_until_stopped(self._mgr)
                self._log("后台线程未及时退出，已摘出保活")
            self._apply_status(False)
            self._connect_btn.setText("连接")
            return
        endpoint = self._endpoint_edit.text().strip()
        if self._server is not None and endpoint != self._server.endpoint:
            self._log(f"注意：模拟服务器在 {self._server.endpoint}，当前端点对不上")
        self._mgr.subscribe(NODE_IDS)
        self._mgr.start()
        self._connect_btn.setText("断开")
        self._log(f"连接中：{endpoint}")

    def _toggle_server(self) -> None:
        if self._server is None:
            return
        if self._server._thread is None:
            try:
                self._server.start()
                self._log("模拟服务器已启动")
            except Exception as exc:  # noqa: BLE001
                self._log(f"启动失败: {exc}")
        else:
            self._server.stop()
            self._log("模拟服务器已停止（观察状态灯：应自动转红并开始重连）")

    def _on_connected(self, connected: bool) -> None:
        self._apply_status(connected)

    def _apply_status(self, connected: bool) -> None:
        color = "#22c55e" if connected else "#ef4444"
        self._status_dot.setStyleSheet(
            f"background:{color}; border-radius:7px;"
        )
        self._status_text.setText("已连接" if connected else "未连接 / 重连中")

    # ------------------------------------------------------------------
    # 数据回调
    # ------------------------------------------------------------------
    def _on_node_changed(self, key: str, value) -> None:
        if key in self._lamps:
            self._lamps[key].set_state(bool(value))
        elif key == "fullcount":
            self._count_label.setText(str(value))
        elif key == "heartbeat":
            self._hb_label.setText(str(value))
        elif key == "message":
            self._msg_label.setText(str(value))

    def _on_node_error(self, key: str, message: str) -> None:
        self._log(f"[{key}] {message}")

    def _write(self, key: str, value) -> None:
        ok = self._mgr.write(key, value)
        self._log(f"写 {key} = {value!r} -> {'成功' if ok else '失败'}")

    def _toggle_lamp(self) -> None:
        current = self._lamps["lamp01"]
        # 从界面反推当前值不如直接读一次，这里用节点真值，避免界面与设备失步
        value = self._mgr.read("lamp01")
        self._write("lamp01", not bool(value) if value is not None else True)

    def _all_off(self) -> None:
        for i in range(1, 5):
            self._write(f"lamp0{i}", False)

    # ------------------------------------------------------------------
    def _log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self._log_view.appendPlainText(f"[{stamp}] {message}")

    def closeEvent(self, event) -> None:
        stopped = self._mgr.stop(wait_ms=1500)
        if not stopped:
            keep_alive_until_stopped(self._mgr)
        if self._server is not None:
            self._server.stop()
        super().closeEvent(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="OPC UA demo")
    parser.add_argument(
        "--endpoint", default="opc.tcp://127.0.0.1:48400", help="OPC UA 端点"
    )
    parser.add_argument(
        "--no-server", action="store_true", help="不启动内置模拟服务器（连真实 PLC 时用）"
    )
    parser.add_argument(
        "--autoclose", type=float, default=0.0, help="N 秒后自动关闭（无人值守冒烟用）"
    )
    args = parser.parse_args()

    server = None
    if not args.no_server:
        server = MockOpcUaServer(args.endpoint)
        try:
            server.start()
        except Exception as exc:  # noqa: BLE001
            print(f"模拟服务器启动失败: {exc}", file=sys.stderr)
            return 2
        print(f"模拟 OPC UA 服务器: {args.endpoint}")

    app = QApplication(sys.argv[:1])
    win = DemoWindow(args.endpoint, server)
    win.show()

    if args.autoclose > 0:
        QTimer.singleShot(int(args.autoclose * 1000), win.close)
    code = app.exec()
    if server is not None:
        server.stop()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
