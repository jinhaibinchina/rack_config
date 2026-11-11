"""test_fixture 运行态入口。

.. code-block:: bash

    .venv/Scripts/python.exe -m App_test_fixture.fixture_app --source demo
    .venv/Scripts/python.exe -m App_test_fixture.fixture_app --source none
    .venv/Scripts/python.exe -m App_test_fixture.fixture_app --source modbus
    .venv/Scripts/python.exe -m App_test_fixture.fixture_app --source modbus --ip 192.168.1.10
    .venv/Scripts/python.exe -m App_test_fixture.fixture_app --seconds 5   # 自测

``--source modbus`` 只有在填了 ``cfg.MODBUS_IP`` 或传 ``--ip`` 时才会真正连接
设备（走 ``common/com/modbus``）；否则给出明确提示并保持静态画面，
不会静默连假数据。寄存器映射见 ``fixture_config.MODBUS_REGISTER_MAP``，
协议适配见 :mod:`App_test_fixture.modbus_link`。

目录里空的 ``test_fixture_entry.py`` 是从旧工程留下的占位，按「原样保留旧文件」
的约定没有改动；要把它当入口用，加一行 ``from .fixture_app import main`` 即可。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from . import fixture_config as cfg
from .datasource import make_source
from .fixture_runtime import FixtureRuntime


class FixtureWindow(QWidget):
    """一层极薄的壳：状态条 + stage.view，业务全在 FixtureRuntime 里。"""

    def __init__(self, runtime: FixtureRuntime,
                 *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.runtime = runtime
        self.setWindowTitle(cfg.WINDOW_TITLE)
        w, h = cfg.WINDOW_SIZE
        self.resize(w, h)

        self.status = QLabel("初始化…")
        self.status.setStyleSheet("padding: 4px 8px;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(6, 2, 6, 2)
        bar.addWidget(self.status, 1)
        layout.addLayout(bar)
        runtime.stage.attach(layout)

        runtime.connectionChanged.connect(self._on_connection)
        runtime.message.connect(self._on_message)
        self._refresh_status()

    def _on_connection(self, connected: bool, endpoint: str) -> None:
        self._endpoint = endpoint
        self._connected = connected
        self._refresh_status()

    def _on_message(self, text: str, level: str) -> None:
        self.status.setText(f"[{level}] {text}")

    def _refresh_status(self) -> None:
        connected = getattr(self, "_connected", False)
        endpoint = getattr(self, "_endpoint", "未启动")
        mark = "● 已连接" if connected else "○ 未连接"
        self.status.setText(f"{mark}  {endpoint}   |   {self.runtime.report()}")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self.runtime.release()
        super().closeEvent(event)


def ensure_cjk_fonts() -> int:
    """离屏 QPA 不会加载系统字体，中文会全部渲染成方块（□□□）。

    只在这种情况下手动补载雅黑 / 黑体；正常 windows 平台下字体库非空，
    一行都不会执行。回归截图、``--seconds`` 自测都靠它拿到可读的中文。
    """
    if QFontDatabase.families():
        return 0
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    loaded = 0
    for name in ("msyh.ttc", "simhei.ttf"):
        path = fonts / name
        if path.is_file() and QFontDatabase.addApplicationFont(str(path)) >= 0:
            loaded += 1
    return loaded


def build(source_kind: str = "demo", page_path: str | None = None,
          *, parent: QWidget | None = None,
          modbus_ip: str | None = None, modbus_port: int | None = None,
          modbus_unit: int | None = None) -> tuple[FixtureRuntime, FixtureWindow]:
    """造一个完整可跑的画面，返回 (runtime, window)，调用方负责持有引用。"""
    ensure_cjk_fonts()
    source = make_source(source_kind)
    if (source_kind or "demo").lower() == "modbus":
        ip = cfg.MODBUS_IP if modbus_ip is None else modbus_ip
        if ip:
            from .modbus_link import ModbusLink
            link = ModbusLink(ip=ip, port=modbus_port, unit=modbus_unit)
            # 挂到 source 上保活，FixtureRuntime.release() 会负责 close()
            source._modbus_link = link
            if link.connect():
                link.attach(source)
            else:
                print(f"[modbus] 连接失败 {ip}:{link.port}", file=sys.stderr)
        else:
            print("[modbus] 未指定设备 IP：填 cfg.MODBUS_IP 或传 --ip 才会连接",
                  file=sys.stderr)
    runtime = FixtureRuntime(page_path=page_path, source=source)
    count = runtime.load()
    if not count:
        raise RuntimeError(f"场景装载失败：{runtime.stage.load_error}")
    window = FixtureWindow(runtime, parent=parent)
    runtime.start()
    return runtime, window


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="test_fixture 统一运行态")
    parser.add_argument("--source", default="demo",
                        choices=("demo", "none", "modbus"))
    parser.add_argument("--page", default=None, help="覆盖场景 JSON 路径")
    parser.add_argument("--ip", default=None,
                        help="Modbus TCP 设备 IP（--source modbus 时覆盖 cfg.MODBUS_IP）")
    parser.add_argument("--port", type=int, default=None, help="Modbus TCP 端口")
    parser.add_argument("--unit", type=int, default=None, help="Modbus 从站号")
    parser.add_argument("--seconds", type=float, default=0.0,
                        help="大于 0 时自动退出（自测 / 截图用）")
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv)
    runtime, window = build(args.source, args.page, modbus_ip=args.ip,
                            modbus_port=args.port, modbus_unit=args.unit)
    window.show()
    print(runtime.report())
    if args.seconds > 0:
        QTimer.singleShot(int(args.seconds * 1000), app.quit)
    rc = app.exec()
    runtime.release()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
