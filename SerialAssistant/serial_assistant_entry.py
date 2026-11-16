"""串口调试助手界面与入口。

.. code-block:: bash

    # 在 AppsManagers 项目根目录下运行（使用项目自带的 .venv）
    .venv/Scripts/python.exe -m SerialAssistant
    .venv/Scripts/python.exe serial_assistant_main.py
    .venv/Scripts/python.exe -m SerialAssistant --seconds 3          # 自测：3 秒后自动退出
    .venv/Scripts/python.exe -m SerialAssistant --screenshot shot.png # 离屏回归截图

设计取舍
--------
* 串口层是 :class:`~SerialAssistant.serial_link.SerialLink`，UI 不直接碰 QSerialPort。
* 接收用增量解码器，UTF-8/GBK 多字节字符被分包到达时不会变成乱码。
* 界面只保留最近 ``MAX_BLOCKS`` 行；需要长期留档请用「保存日志」。
* 发送字节数以 ``bytesWritten`` 实际写出的数量为准，不是 ``write()`` 的缓冲写入量。
"""

from __future__ import annotations

import argparse
import codecs
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QTime
from PySide6.QtGui import QFontDatabase, QIntValidator, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy,
    QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from .serial_link import (
    BAUD_RATES, DATA_BITS, FLOW_CHOICES, PARITY_CHOICES, STOP_BITS,
    PortConfig, SerialLink,
)

ENCODINGS = ("UTF-8", "GBK", "ASCII", "Latin-1", "UTF-16LE")
LINE_ENDINGS = (
    ("不追加", ""),
    ("CR+LF  \\r\\n", "\r\n"),
    ("LF  \\n", "\n"),
    ("CR  \\r", "\r"),
)
MAX_BLOCKS = 5000            # 接收区最多保留的文本行数
TIMESTAMP_GAP_MS = 600      # 静默超过该时长后重新打时间戳
PORT_SCAN_INTERVAL_MS = 2000

_QSS = """
QWidget { color: #243044; font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif; font-size: 12px; }
QGroupBox { border: 1px solid #d8dde6; border-radius: 6px; margin-top: 12px;
            padding: 12px 10px 10px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #33445c; }
QComboBox, QSpinBox, QLineEdit { padding: 3px 6px; border: 1px solid #c9d2df;
                                 border-radius: 4px; background: #ffffff; }
QPlainTextEdit { border: 1px solid #d8dde6; border-radius: 4px; background: #ffffff;
                 font-family: Consolas, 'Cascadia Mono', 'Microsoft YaHei', monospace;
                 font-size: 12px; selection-background-color: #b9d7ff; }
QPushButton { padding: 5px 12px; border: 1px solid #c9d2df; border-radius: 4px;
              background: #f7f9fc; }
QPushButton:hover { background: #eaf2ff; border-color: #8fb4ea; }
QPushButton:pressed { background: #dbe9ff; }
QCheckBox { spacing: 4px; }
QLabel#hint { color: #788498; font-weight: 400; }
QLabel#state { padding: 6px; border-radius: 4px; background: #f1f4f9; font-weight: 400; }
QLabel#statusBar { padding: 5px 10px; background: #f1f4f9; border-top: 1px solid #d8dde6;
                   color: #44546b; }
QSplitter::handle { background: #e3e8f0; }
"""


# --------------------------------------------------------------------------- 纯函数

def parse_hex_text(text: str) -> tuple[bytes, str]:
    """把 ``"01 02 0xAB"`` / ``"0102AB"`` 解析为字节串，返回 ``(数据, 错误文本)``。

    允许空格、逗号、分号、连字符、换行作为分隔；每个 token 必须是偶数位十六进制。
    """
    cleaned = re.sub(r"0[xX]", "", text)
    tokens = [t for t in re.split(r"[\s,;:\-]+", cleaned.strip()) if t]
    if not tokens:
        return b"", "HEX 内容为空"
    out = bytearray()
    for token in tokens:
        if not re.fullmatch(r"[0-9a-fA-F]+", token) or len(token) % 2:
            return b"", f"非法 HEX 字节：{token!r}（需要 1~2 位一组的十六进制，如 0A 或 0A1B）"
        out.extend(bytes.fromhex(token))
    return bytes(out), ""


def format_hex_bytes(data: bytes) -> str:
    """字节串格式化为带尾随空格的 HEX 文本，便于流式拼接。"""
    return "".join(f"{b:02X} " for b in data)


def apply_line_ending(text: str, eol: str) -> str:
    """统一输入框里的换行为 ``eol``，并保证末尾恰好带一个行结束符。"""
    if not eol:
        return text
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    body = normalized.replace("\n", eol)
    if not body.endswith(eol):
        body += eol
    return body


def ensure_cjk_fonts() -> int:
    """离屏 QPA 不加载系统字体，中文会渲染成方块；此时手动补载雅黑/黑体。"""
    if QFontDatabase.families():
        return 0
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    loaded = 0
    for name in ("msyh.ttc", "simhei.ttf"):
        path = fonts / name
        if path.is_file() and QFontDatabase.addApplicationFont(str(path)) >= 0:
            loaded += 1
    return loaded


# --------------------------------------------------------------------------- 主窗口

class SerialAssistantWindow(QWidget):
    """串口调试助手主窗口。"""

    def __init__(self, *, parent: QWidget | None = None,
                 persist: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle("串口调试助手  —  SerialAssistant")
        self.setStyleSheet(_QSS)
        self.resize(1080, 720)

        self.link = SerialLink(self)
        self.settings = QSettings("AppsManagers", "SerialAssistant") if persist else None
        self._rx_bytes = 0
        self._tx_bytes = 0
        self._last_stamp_ms: int | None = None
        self._decoder: codecs.IncrementalDecoder | None = None

        self._build_ui()

        # 两个定时器要先建好：下面的信号连接和 _apply_connected_state 会用到。
        self._port_timer = QTimer(self)
        self._port_timer.setInterval(PORT_SCAN_INTERVAL_MS)
        self._port_timer.timeout.connect(self._refresh_ports)

        self._send_timer = QTimer(self)
        self._send_timer.setInterval(self.interval_spin.value())
        self._send_timer.timeout.connect(self._on_send_clicked)

        self._connect_signals()
        self._load_settings()
        self._reset_decoder()
        self._refresh_ports()
        self._apply_connected_state(False)
        self._notify("就绪：选择端口后点「打开串口」")

    # ------------------------------------------------------------------ 构建界面

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 0)
        root.setSpacing(8)

        content = QHBoxLayout()
        content.setSpacing(10)
        content.addWidget(self._build_port_panel(), 0)
        content.addWidget(self._build_io_panel(), 1)
        root.addLayout(content, 1)

        # 提示消息与统计分开，避免「打开失败」的提示被下一个字节计数刷掉。
        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.message_label = QLabel("就绪")
        self.message_label.setObjectName("statusBar")
        # 中间用弹性留白撑开：两侧 QLabel 各按内容宽度摆放，互不挤压。
        self.message_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        self.message_label.setMinimumWidth(120)
        self.message_label.setMaximumWidth(520)
        self.status_bar = QLabel("")
        self.status_bar.setObjectName("statusBar")
        # Minimum：统计串按自身 sizeHint 完整占位，空间不足时压缩左边的提示消息。
        self.status_bar.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred
        )
        status_row.addWidget(self.message_label, 0)
        status_row.addStretch(1)
        status_row.addWidget(self.status_bar, 0)
        root.addLayout(status_row, 0)

    def _build_port_panel(self) -> QWidget:
        box = QGroupBox("串口设置")
        box.setFixedWidth(292)
        form = QFormLayout(box)
        form.setContentsMargins(10, 4, 10, 8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(9)

        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(120)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setToolTip("重新枚举系统串口（未打开时每 2 秒自动刷新）")
        port_row = QHBoxLayout()
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_btn, 0)
        form.addRow("端口", port_row)

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems([str(b) for b in BAUD_RATES])
        self.baud_combo.lineEdit().setValidator(QIntValidator(1, 10_000_000, self.baud_combo))
        form.addRow("波特率", self.baud_combo)

        self.data_combo = QComboBox()
        self.data_combo.addItems([str(b) for b in DATA_BITS])
        form.addRow("数据位", self.data_combo)

        self.parity_combo = QComboBox()
        for label, key in PARITY_CHOICES:
            self.parity_combo.addItem(label, key)
        form.addRow("校验位", self.parity_combo)

        self.stop_combo = QComboBox()
        for label, value in STOP_BITS:
            self.stop_combo.addItem(label, value)
        form.addRow("停止位", self.stop_combo)

        self.flow_combo = QComboBox()
        for label, key in FLOW_CHOICES:
            self.flow_combo.addItem(label, key)
        form.addRow("流控", self.flow_combo)

        self.open_btn = QPushButton("打开串口")
        self.open_btn.setMinimumHeight(32)
        form.addRow(self.open_btn)

        self.state_label = QLabel("○ 未打开")
        self.state_label.setObjectName("state")
        self.state_label.setWordWrap(True)
        form.addRow(self.state_label)

        hint = QLabel("端口即插即拔会自动刷新；\n设备被拔出时会自动关闭串口。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        form.addRow(hint)
        return box

    def _build_io_panel(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_rx_panel())
        splitter.addWidget(self._build_tx_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        return splitter

    def _build_rx_panel(self) -> QWidget:
        box = QGroupBox("接收区")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 4, 10, 8)
        layout.setSpacing(6)

        opts = QHBoxLayout()
        self.hex_view = QCheckBox("HEX 显示")
        self.timestamp_cb = QCheckBox("时间戳")
        self.echo_tx_cb = QCheckBox("回显发送")
        self.wrap_cb = QCheckBox("自动换行")
        self.wrap_cb.setChecked(True)
        self.pause_cb = QCheckBox("暂停显示")
        for widget in (self.hex_view, self.timestamp_cb, self.echo_tx_cb,
                       self.wrap_cb, self.pause_cb):
            opts.addWidget(widget)
        opts.addStretch(1)
        layout.addLayout(opts)

        self.rx_view = QPlainTextEdit()
        self.rx_view.setReadOnly(True)
        self.rx_view.setMaximumBlockCount(MAX_BLOCKS)
        self.rx_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.rx_view, 1)

        actions = QHBoxLayout()
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(ENCODINGS)
        self.encoding_combo.setToolTip("接收文本的解码编码（HEX 显示时不影响）")
        actions.addWidget(QLabel("编码"))
        actions.addWidget(self.encoding_combo)
        actions.addStretch(1)
        self.clear_rx_btn = QPushButton("清空接收")
        self.save_log_btn = QPushButton("保存日志")
        self.reset_count_btn = QPushButton("计数清零")
        for widget in (self.clear_rx_btn, self.save_log_btn, self.reset_count_btn):
            actions.addWidget(widget)
        layout.addLayout(actions)
        return box

    def _build_tx_panel(self) -> QWidget:
        box = QGroupBox("发送区")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 4, 10, 8)
        layout.setSpacing(6)

        opts = QHBoxLayout()
        self.hex_send_cb = QCheckBox("HEX 发送")
        self.hex_send_cb.setToolTip("输入 01 0A FF 或 010AFF；非法字符会拒绝发送并提示")
        self.hex_send_cb.setFixedWidth(90)
        self.line_end_combo = QComboBox()
        for label, value in LINE_ENDINGS:
            self.line_end_combo.addItem(label, value)
        self.auto_send_cb = QCheckBox("定时发送")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(10, 600_000)
        self.interval_spin.setValue(1000)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.setFixedWidth(122)
        opts.addWidget(QLabel("换行符"))
        opts.addWidget(self.line_end_combo)
        opts.addStretch(1)
        opts.addWidget(self.hex_send_cb)
        opts.addWidget(self.auto_send_cb)
        opts.addWidget(self.interval_spin)
        opts.addSpacing(4)
        layout.addLayout(opts)

        self.tx_view = QPlainTextEdit()
        self.tx_view.setPlaceholderText("输入要发送的内容；HEX 发送时写成 01 0A FF 或 010AFF")
        self.tx_view.setMinimumHeight(70)
        layout.addWidget(self.tx_view, 1)

        actions = QHBoxLayout()
        self.char_count_label = QLabel("0 字符")
        self.char_count_label.setObjectName("hint")
        actions.addWidget(self.char_count_label)
        actions.addStretch(1)
        self.clear_tx_btn = QPushButton("清空输入")
        self.send_btn = QPushButton("发送")
        self.send_btn.setMinimumWidth(90)
        self.send_btn.setStyleSheet("background: #1f6feb; color: white; border-color: #1f6feb;")
        actions.addWidget(self.clear_tx_btn)
        actions.addWidget(self.send_btn)
        layout.addLayout(actions)
        return box

    # ------------------------------------------------------------------ 信号连接

    def _connect_signals(self) -> None:
        self.open_btn.clicked.connect(self._on_open_clicked)
        self.refresh_btn.clicked.connect(self._refresh_ports)
        self.clear_rx_btn.clicked.connect(self._clear_rx)
        self.save_log_btn.clicked.connect(self._save_log)
        self.reset_count_btn.clicked.connect(self._reset_counts)
        self.clear_tx_btn.clicked.connect(self.tx_view.clear)
        self.send_btn.clicked.connect(self._on_send_clicked)
        self.tx_view.textChanged.connect(self._on_tx_changed)

        self.hex_view.toggled.connect(self._on_display_mode_changed)
        self.wrap_cb.toggled.connect(self._on_wrap_changed)
        self.encoding_combo.currentTextChanged.connect(self._on_encoding_changed)
        self.encoding_combo.currentTextChanged.connect(self._on_tx_changed)
        self.line_end_combo.currentIndexChanged.connect(self._on_tx_changed)
        self.port_combo.currentIndexChanged.connect(self._update_port_tooltip)
        self.auto_send_cb.toggled.connect(self._on_auto_send_toggled)
        self.interval_spin.valueChanged.connect(self._send_timer.setInterval)
        self.hex_send_cb.toggled.connect(self._on_tx_changed)

        self.link.opened.connect(self._on_link_opened)
        self.link.closed.connect(self._on_link_closed)
        self.link.dataReceived.connect(self._on_data_received)
        self.link.bytesSent.connect(self._on_bytes_sent)
        self.link.failed.connect(self._on_link_failed)

    # ------------------------------------------------------------------ 串口操作

    def _on_open_clicked(self) -> None:
        if self.link.is_open:
            self.link.close()
            self._notify("串口已关闭")
            return
        cfg = self._collect_config()
        if cfg is None:
            return
        ok, message = self.link.open(cfg)
        self._notify(message, ok)
        if not ok:
            self._refresh_ports()

    def _collect_config(self) -> PortConfig | None:
        if not self.port_combo.currentData():
            self._notify("没有可用串口：请插入设备后点「刷新」", False)
            return None
        raw_baud = self.baud_combo.currentText().strip()
        try:
            baud = int(raw_baud)
        except ValueError:
            baud = 0
        if baud <= 0:
            self._notify(f"波特率非法：{raw_baud!r}", False)
            return None
        return PortConfig(
            port_name=str(self.port_combo.currentData()),
            baud_rate=baud,
            data_bits=int(self.data_combo.currentText()),
            parity=str(self.parity_combo.currentData()),
            stop_bits=float(self.stop_combo.currentData()),
            flow_control=str(self.flow_combo.currentData()),
        )

    def _on_link_opened(self, summary: str) -> None:
        self._apply_connected_state(True, summary)
        self._settings_set("cfg/last_port", self.link.port_name)

    def _on_link_closed(self, reason: str = "") -> None:
        if self.auto_send_cb.isChecked():
            self.auto_send_cb.setChecked(False)
        self._apply_connected_state(False, reason)

    def _on_link_failed(self, message: str) -> None:
        # 先收拾连接状态（可能连带关掉定时发送），最后再显示错误，避免被覆盖。
        if not self.link.is_open:
            self._on_link_closed()
        self._notify(message, False)

    def _apply_connected_state(self, connected: bool, detail: str = "") -> None:
        self.open_btn.setText("关闭串口" if connected else "打开串口")
        self.open_btn.setStyleSheet(
            "background: #d9534f; color: white; border-color: #d9534f;" if connected
            else "background: #1f6feb; color: white; border-color: #1f6feb;"
        )
        for widget in (self.port_combo, self.refresh_btn, self.baud_combo,
                       self.data_combo, self.parity_combo, self.stop_combo,
                       self.flow_combo):
            widget.setEnabled(not connected)
        self.state_label.setText(
            f"● 已打开\n{detail}" if connected else f"○ 未打开{detail and '  —  ' + detail}"
        )
        # 打开期间停止扫描端口，避免下拉框内容变化打断操作。
        if connected:
            self._port_timer.stop()
        else:
            self._port_timer.start()
        self._update_status()

    def _refresh_ports(self) -> None:
        if self.link.is_open:
            return
        current = (self.port_combo.currentData()
                   or getattr(self, "_saved_port", "")
                   or self.port_combo.currentText())
        ports = SerialLink.list_ports()
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for name, label in ports:
            self.port_combo.addItem(label, name)
        if current:
            index = self.port_combo.findData(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        if not ports:
            self.port_combo.addItem("（未发现串口）", "")
        self.port_combo.blockSignals(False)
        self._update_port_tooltip()

    def _update_port_tooltip(self, *_args) -> None:
        # 下拉框宽度有限，完整描述（含厂商 / VID 信息）放在悬停提示里。
        self.port_combo.setToolTip(self.port_combo.currentText())

    # ------------------------------------------------------------------ 接收

    def _on_data_received(self, data: bytes) -> None:
        self._rx_bytes += len(data)
        if not self.pause_cb.isChecked():
            self._append_rx(self._format_rx(data))
        self._update_status()

    def _format_rx(self, data: bytes) -> str:
        stamp = self._stamp_prefix()
        if self.hex_view.isChecked():
            return stamp + format_hex_bytes(data)
        if self._decoder is None:
            self._reset_decoder()
        assert self._decoder is not None
        text = self._decoder.decode(data)  # 不完整的多字节字符留在解码器里等下一包
        if stamp and text:
            return stamp + text
        return text

    def _stamp_prefix(self) -> str:
        if not self.timestamp_cb.isChecked():
            return ""
        now_ms = QTime.currentTime().msecsSinceStartOfDay()
        fresh = (self._last_stamp_ms is None
                 or now_ms - self._last_stamp_ms > TIMESTAMP_GAP_MS
                 or self.rx_view.document().isEmpty())
        self._last_stamp_ms = now_ms
        if fresh:
            # 上一段数据没以换行结束时另起一行，时间戳才不会粘在半行数据后面。
            last_block = self.rx_view.document().lastBlock().text()
            lead = "\n" if last_block else ""
            return f"{lead}[{QTime.currentTime().toString('HH:mm:ss.zzz')}] "
        return ""

    def _append_rx(self, text: str) -> None:
        if not text:
            return
        self.rx_view.moveCursor(QTextCursor.MoveOperation.End)
        self.rx_view.insertPlainText(text)
        self.rx_view.ensureCursorVisible()

    def _echo_sent(self, text: str, data: bytes) -> None:
        if not self.echo_tx_cb.isChecked() or self.pause_cb.isChecked():
            return
        body = format_hex_bytes(data) if self.hex_view.isChecked() else text
        self._append_rx(f"\n[发送] {body}\n")

    def _clear_rx(self) -> None:
        self.rx_view.clear()
        self._last_stamp_ms = None
        self._reset_decoder()
        self._update_status()

    def _save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "保存接收日志", f"serial_{QTime.currentTime().toString('HHmmss')}.txt",
            "文本文件 (*.txt);;所有文件 (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(self.rx_view.toPlainText(), encoding="utf-8")
            self._notify(f"日志已保存：{path}", True)
        except OSError as exc:
            self._notify(f"保存失败：{exc}", False)

    def _reset_counts(self) -> None:
        self._rx_bytes = 0
        self._tx_bytes = 0
        self._update_status()

    def _reset_decoder(self) -> None:
        self._decoder = codecs.getincrementaldecoder(self._encoding())("replace")

    def _encoding(self) -> str:
        return self.encoding_combo.currentText() or "UTF-8"

    def _on_encoding_changed(self, _text: str) -> None:
        self._reset_decoder()
        self._update_status()

    def _on_display_mode_changed(self, _checked: bool) -> None:
        # HEX / 文本切换时丢掉解码器里未闭合的半个字符，避免两种显示串味。
        self._reset_decoder()
        self._last_stamp_ms = None

    def _on_wrap_changed(self, checked: bool) -> None:
        self.rx_view.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if checked
            else QPlainTextEdit.LineWrapMode.NoWrap
        )

    # ------------------------------------------------------------------ 发送

    def _on_tx_changed(self, *_args) -> None:
        # 同时接 textChanged()（无参）和 hex_send.toggled(bool)，参数个数不同。
        text = self.tx_view.toPlainText()
        if self.hex_send_cb.isChecked():
            data, error = parse_hex_text(text)
            self.char_count_label.setText(
                f"{len(data)} 字节 (HEX)" if not error else error
            )
        else:
            eol = str(self.line_end_combo.currentData() or "")
            payload = apply_line_ending(text, eol) if text else ""
            try:
                size = len(payload.encode(self._encoding(), errors="replace"))
            except LookupError:
                size = len(payload.encode("utf-8", errors="replace"))
            self.char_count_label.setText(f"{len(text)} 字符 / {size} 字节")

    def _on_send_clicked(self) -> None:
        if not self.link.is_open:
            self._notify("串口未打开，无法发送", False)
            if self.auto_send_cb.isChecked():
                self.auto_send_cb.setChecked(False)
            return
        text = self.tx_view.toPlainText()
        if not text.strip():
            self._notify("发送内容为空", False)
            return
        if self.hex_send_cb.isChecked():
            data, error = parse_hex_text(text)
            if error:
                self._notify(error, False)
                return
            display = format_hex_bytes(data).strip()
        else:
            eol = str(self.line_end_combo.currentData() or "")
            payload = apply_line_ending(text, eol)
            try:
                data = payload.encode(self._encoding(), errors="replace")
            except LookupError as exc:
                self._notify(f"编码不可用：{exc}", False)
                return
            display = payload.replace("\r", "\\r").replace("\n", "\\n")
        if not data:
            self._notify("发送内容为空", False)
            return
        _written, error = self.link.write(data)
        if error:
            self._notify(error, False)
            return
        self._echo_sent(display, data)

    def _on_bytes_sent(self, count: int) -> None:
        self._tx_bytes += count
        self._update_status()

    def _on_auto_send_toggled(self, checked: bool) -> None:
        if checked:
            if not self.link.is_open:
                # 静默复位，否则 toggled(False) 会把这条错误提示覆盖成「已停止」。
                self.auto_send_cb.blockSignals(True)
                self.auto_send_cb.setChecked(False)
                self.auto_send_cb.blockSignals(False)
                self._send_timer.stop()
                self._notify("请先打开串口再启用定时发送", False)
                return
            self._send_timer.setInterval(self.interval_spin.value())
            self._send_timer.start()
            self._notify(f"定时发送已启用：每 {self.interval_spin.value()} ms", True)
        else:
            self._send_timer.stop()
            self._notify("定时发送已停止", True)

    # ------------------------------------------------------------------ 状态与配置

    def _notify(self, message: str, ok: bool = True) -> None:
        color = "#1b7a3d" if ok else "#c0392b"
        self.message_label.setStyleSheet(f"color: {color};")
        self.message_label.setText(("✓ " if ok else "✗ ") + message)
        self.message_label.setToolTip(message)

    def _update_status(self) -> None:
        state = "● 已连接" if self.link.is_open else "○ 未打开"
        port = self.link.port_name if self.link.is_open else (
            str(self.port_combo.currentData() or "无端口")
        )
        self.status_bar.setText(
            f"{state} {port}  |  RX {self._rx_bytes} B  TX {self._tx_bytes} B"
            f"  |  {self._encoding()}"
            f"  |  {'HEX' if self.hex_view.isChecked() else '文本'}"
            f"{'  |  ⏸ 暂停' if self.pause_cb.isChecked() else ''}"
        )

    def _settings_set(self, key: str, value: object) -> None:
        if self.settings is not None:
            self.settings.setValue(key, value)

    def _load_settings(self) -> None:
        if self.settings is None:
            # 无配置时的默认值
            self.baud_combo.setCurrentText("115200")
            self.data_combo.setCurrentText("8")
            self.stop_combo.setCurrentIndex(0)
            self.line_end_combo.setCurrentIndex(1)  # 默认追加 CRLF
            return
        s = self.settings
        self._saved_port = s.value("cfg/last_port", "", type=str)
        self.baud_combo.setCurrentText(str(s.value("cfg/baud", 115200)))
        self.data_combo.setCurrentText(str(s.value("cfg/data_bits", 8)))
        self._set_combo_data(self.parity_combo, s.value("cfg/parity", "N", type=str))
        stop_raw = s.value("cfg/stop_bits", 1.0)
        self._set_combo_data(self.stop_combo, float(stop_raw))
        self._set_combo_data(self.flow_combo, s.value("cfg/flow", "none", type=str))
        for key, widget in (
            ("ui/hex_view", self.hex_view), ("ui/timestamp", self.timestamp_cb),
            ("ui/echo_tx", self.echo_tx_cb), ("ui/wrap", self.wrap_cb),
            ("ui/hex_send", self.hex_send_cb),
        ):
            widget.setChecked(s.value(key, widget.isChecked(), type=bool))
        self.encoding_combo.setCurrentText(s.value("ui/encoding", "UTF-8", type=str))
        self._set_combo_data(self.line_end_combo, s.value("ui/line_end", "\r\n", type=str))
        self.interval_spin.setValue(s.value("ui/interval", 1000, type=int))
        self.tx_view.setPlainText(s.value("ui/send_text", "", type=str))
        geometry = s.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _save_settings(self) -> None:
        if self.settings is None:
            return
        s = self.settings
        s.setValue("cfg/last_port", self.port_combo.currentData() or "")
        s.setValue("cfg/baud", self.baud_combo.currentText())
        s.setValue("cfg/data_bits", self.data_combo.currentText())
        s.setValue("cfg/parity", self.parity_combo.currentData())
        s.setValue("cfg/stop_bits", self.stop_combo.currentData())
        s.setValue("cfg/flow", self.flow_combo.currentData())
        for key, widget in (
            ("ui/hex_view", self.hex_view), ("ui/timestamp", self.timestamp_cb),
            ("ui/echo_tx", self.echo_tx_cb), ("ui/wrap", self.wrap_cb),
            ("ui/hex_send", self.hex_send_cb),
        ):
            s.setValue(key, widget.isChecked())
        s.setValue("ui/encoding", self.encoding_combo.currentText())
        s.setValue("ui/line_end", self.line_end_combo.currentData())
        s.setValue("ui/interval", self.interval_spin.value())
        s.setValue("ui/send_text", self.tx_view.toPlainText())
        s.setValue("window/geometry", self.saveGeometry())
        s.sync()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._send_timer.stop()
        self._port_timer.stop()
        self.link.close()
        self._save_settings()
        super().closeEvent(event)


# --------------------------------------------------------------------------- 入口

def build(*, parent: QWidget | None = None,
          persist: bool = True) -> SerialAssistantWindow:
    """造一个完整窗口，返回给调用方持有引用（离屏自测也走这里）。"""
    ensure_cjk_fonts()
    return SerialAssistantWindow(parent=parent, persist=persist)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PySide6 串口调试助手")
    parser.add_argument("--seconds", type=float, default=0.0,
                        help="大于 0 时自动退出（自测 / 截图用）")
    parser.add_argument("--screenshot", default=None,
                        help="窗口显示后把画面保存为 PNG")
    parser.add_argument("--no-save", action="store_true",
                        help="不读写本机 QSettings 配置（自测用）")
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv)
    window = build(persist=not args.no_save)
    window.show()

    if args.screenshot:
        path = str(Path(args.screenshot).resolve())
        QTimer.singleShot(400, lambda: window.grab().save(path, "PNG"))
    if args.seconds > 0:
        QTimer.singleShot(int(args.seconds * 1000), app.quit)

    rc = app.exec()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
