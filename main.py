"""统一入口：一个进程承载多个 App 工具。

用法::

    python main.py                 # 工具选择页
    python main.py --app rack      # 直接进「料架 PLC 配置工具」
    python main.py --app safety    # 直接进「大小车安全 PLC 客户端」
    python main.py --no-plc        # 离线模式，不连 PLC（无设备时调试用）

``rack_config_main.py`` / ``safety_car_main.py`` 保留为薄壳，转发到本模块的
:func:`run`，旧的快捷方式、spec 与同事的使用习惯不受影响。

设计要点：

* 两个工具窗口的依赖都很重（场景反序列化、snap7 的 dll、UI 资源），因此
  **点击时才 import**，保证选择页秒开；
* 工具窗口关闭后一律销毁重建（``RackConfigWindow`` 关窗要停后台线程、
  ``SafetyCarWindow`` 关窗要断 PLC），不做隐藏复用；
* 直接 ``--app`` 启动时不建选择页，``quitOnLastWindowClosed`` 保持默认 True，
  与原来的两个独立入口行为完全一致。
"""

from __future__ import annotations

import argparse
import sys
import traceback
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from PySide6.QtCore import Qt, QEvent, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

APP_ORG = "AppsManagers"
APP_NAME = "AppsManagers"
LAUNCHER_TITLE = "工具平台"

# 各工具的默认 PLC 地址。料架取自 App_RackConfig.rack_config_main.DEFAULT_PLC_IP，
# 安全车沿用原 safety_car_main.main() 里写死的地址。
RACK_PLC_IP = "192.168.1.100"
SAFETY_PLC_IP = "192.168.1.150"
POPPICK_PLC_IP = "192.168.1.88"

# ----------------------------------------------------------------------
# 工具注册表
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Tool:
    key: str
    title: str
    subtitle: str
    badge: str
    factory: Callable[[bool, Optional[str]], QMainWindow]


def _make_rack(enable_plc: bool, plc_ip: Optional[str]) -> QMainWindow:
    from App_RackConfig import RackConfigWindow

    return RackConfigWindow(plc_ip=plc_ip or RACK_PLC_IP, enable_plc=enable_plc)


def _make_safety(enable_plc: bool, plc_ip: Optional[str]) -> QMainWindow:
    from App_SafetyCar import SafetyCarWindow

    return SafetyCarWindow(plc_ip=plc_ip or SAFETY_PLC_IP, enable_plc=enable_plc)


def _make_pop_pick(enable_plc: bool, plc_ip: Optional[str]) -> QMainWindow:
    from App_PopPick import PopPickWindow

    return PopPickWindow(plc_ip=plc_ip or POPPICK_PLC_IP, enable_plc=enable_plc)


TOOLS: tuple[Tool, ...] = (
    Tool(
        key="rack",
        title="料架 PLC 配置工具",
        subtitle="料架仓位、IO 通道、全局参数与运行态调试",
        badge="RACK",
        factory=_make_rack,
    ),
    Tool(
        key="safety",
        title="大小车安全 PLC 客户端",
        subtitle="安全点位、站点状态查询与运行态场景查看",
        badge="SAFETY",
        factory=_make_safety,
    ),
    Tool(
        key="PopPick",
        title="PopPick PLC 客户端",
        subtitle="高密度货架拣选工作站：页面卡片点击互换",
        badge="POPPICK",
        factory=_make_pop_pick,
    ),
)


def _tool(key: str) -> Tool:
    for tool in TOOLS:
        if tool.key == key:
            return tool
    raise KeyError(f"未注册的工具: {key!r}")


# ----------------------------------------------------------------------
# 样式
# ----------------------------------------------------------------------
LAUNCHER_QSS = """
QWidget#launcherRoot {
    background: #F5F5F5;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
}
QLabel#launcherTitle {
    font-size: 24px;
    font-weight: 600;
    color: #212121;
}
QLabel#launcherSubtitle {
    font-size: 13px;
    color: #6B6B6B;
}
QLabel#launcherFooter {
    font-size: 12px;
    color: #8A8A8A;
}
QFrame#toolCard {
    background: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-radius: 8px;
}
QFrame#toolCard:hover {
    background: #FAFCFF;
    border: 1px solid #3C80B1;
}
QFrame#toolCard[pressed="true"] {
    background: #EEF5FA;
    border: 1px solid #3C80B1;
}
QLabel#cardBadge {
    font-size: 11px;
    font-weight: 600;
    color: #3C80B1;
    letter-spacing: 1px;
}
QLabel#cardTitle {
    font-size: 16px;
    font-weight: 600;
    color: #212121;
}
QLabel#cardDesc {
    font-size: 12px;
    color: #6B6B6B;
}
QPushButton#quitButton {
    background: transparent;
    border: 1px solid #D0D0D0;
    border-radius: 4px;
    padding: 6px 18px;
    font-size: 12px;
    color: #555555;
}
QPushButton#quitButton:hover {
    border: 1px solid #3C80B1;
    color: #3C80B1;
}
"""


class ToolCard(QFrame):
    """一张工具卡片。用 QFrame 而不是 QPushButton，避免按钮自绘把子控件盖住。"""

    clicked = Signal(str)

    def __init__(self, tool: Tool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.tool = tool
        self.setObjectName("toolCard")
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(320, 150)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)

        badge = QLabel(tool.badge)
        badge.setObjectName("cardBadge")
        title = QLabel(tool.title)
        title.setObjectName("cardTitle")
        desc = QLabel(tool.subtitle)
        desc.setObjectName("cardDesc")
        desc.setWordWrap(True)

        layout.addStretch(1)
        for label in (badge, title, desc):
            # 子控件吃掉鼠标事件，卡片点不动，必须让它穿透
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            layout.addWidget(label)
        layout.addStretch(1)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._set_pressed(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._set_pressed(False)
        if event.button() == Qt.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit(self.tool.key)
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_pressed(False)
        super().leaveEvent(event)

    def _set_pressed(self, value: bool) -> None:
        if self.property("pressed") == value:
            return
        self.setProperty("pressed", value)
        self.style().unpolish(self)
        self.style().polish(self)


class ToolLauncher(QWidget):
    """工具选择页：点卡片进工具，工具窗口关掉自动回到这里。"""

    def __init__(
        self,
        *,
        enable_plc: bool = True,
        plc_ip: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.enable_plc = enable_plc
        self.plc_ip = plc_ip
        self._active: Optional[QMainWindow] = None
        self._quitting = False

        self.setObjectName("launcherRoot")
        self.setWindowTitle(LAUNCHER_TITLE)
        self.setStyleSheet(LAUNCHER_QSS)
        self.setMinimumSize(760, 400)
        self._build()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 36, 40, 28)
        root.setSpacing(4)

        title = QLabel("工具平台")
        title.setObjectName("launcherTitle")
        subtitle = QLabel("选择一个工具启动")
        subtitle.setObjectName("launcherSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addSpacing(24)

        row = QHBoxLayout()
        row.setSpacing(18)
        for tool in TOOLS:
            card = ToolCard(tool)
            card.clicked.connect(self._open)
            row.addWidget(card)
        row.addStretch(1)
        root.addLayout(row)
        root.addStretch(1)

        footer = QHBoxLayout()
        mode_text = "PLC：离线模式" if not self.enable_plc else "PLC：按工具配置连接"
        hint = QLabel(mode_text + "　·　关闭工具窗口即可返回本页")
        hint.setObjectName("launcherFooter")
        footer.addWidget(hint)
        footer.addStretch(1)

        quit_btn = QPushButton("退出")
        quit_btn.setObjectName("quitButton")
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.clicked.connect(self._quit)
        footer.addWidget(quit_btn)
        root.addLayout(footer)

    # ------------------------------------------------------------------
    # 工具窗口生命周期
    # ------------------------------------------------------------------
    def _open(self, key: str) -> None:
        if self._active is not None:
            self._active.raise_()
            self._active.activateWindow()
            return

        tool = _tool(key)
        try:
            window = tool.factory(self.enable_plc, self.plc_ip)
        except Exception as exc:  # noqa: BLE001 - 启动失败要给可读提示
            traceback.print_exc()
            print(f"[启动失败] {tool.title}: {type(exc).__name__}: {exc}", file=sys.stderr)
            QMessageBox.critical(
                self, "启动失败", f"{tool.title}\n\n{type(exc).__name__}: {exc}"
            )
            return

        # 两个工具的 closeEvent 都会做真实清理（停线程 / 断 PLC），
        # 因此关闭即销毁，不缓存实例复用。
        window.setAttribute(Qt.WA_DeleteOnClose, True)
        window.installEventFilter(self)
        self._active = window

        window.show()
        window.raise_()
        window.activateWindow()
        self.hide()

    def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
        if event.type() == QEvent.Close and obj is self._active:
            self._active = None
            if not self._quitting:
                # Close 事件里还不能显示自己，等窗口真正关掉再回来
                QTimer.singleShot(0, self._back_to_launcher)
        return super().eventFilter(obj, event)

    def _back_to_launcher(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._quitting = True
        if self._active is not None:
            self._active.close()
        QApplication.instance().quit()

    def closeEvent(self, event):  # noqa: N802 - Qt 命名
        self._quitting = True
        QApplication.instance().quit()
        super().closeEvent(event)


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------
def run(
    app_key: Optional[str] = None,
    *,
    enable_plc: bool = True,
    plc_ip: Optional[str] = None,
    argv: Optional[Sequence[str]] = None,
) -> int:
    """启动工具或选择页。

    :param app_key: ``"rack"`` / ``"safety"`` 直接启动对应工具；
        为空或 ``"launcher"`` 时显示选择页。
    :param argv: 传给 ``QApplication`` 的参数，默认只用程序名，
        避免 Qt 去解析本模块的 ``--app`` 等自定义参数。
    """
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(list(argv) if argv else sys.argv[:1])

    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    if owns_app:
        app.setStyle("Fusion")

    if app_key and app_key != "launcher":
        # 与原来的独立入口一致：关掉窗口就退出进程
        app.setQuitOnLastWindowClosed(True)
        return _start_single(app, app_key, enable_plc, plc_ip, owns_app)

    # 选择页模式下「最后一个窗口关闭」不能直接退出：工具窗口关闭时
    # 选择页正处于隐藏状态，靠 ToolLauncher.closeEvent 显式 quit。
    app.setQuitOnLastWindowClosed(False)
    launcher = ToolLauncher(enable_plc=enable_plc, plc_ip=plc_ip)
    launcher.show()

    if owns_app:
        return app.exec()
    return 0


def _start_single(
    app: QApplication,
    app_key: str,
    enable_plc: bool,
    plc_ip: Optional[str],
    owns_app: bool,
) -> int:
    tool = _tool(app_key)
    try:
        window = tool.factory(enable_plc, plc_ip)
    except Exception as exc:  # noqa: BLE001 - 启动失败要给可读提示
        traceback.print_exc()
        print(f"[启动失败] {tool.title}: {type(exc).__name__}: {exc}", file=sys.stderr)
        if owns_app:
            QMessageBox.critical(
                None, "启动失败", f"{tool.title}\n\n{type(exc).__name__}: {exc}"
            )
        return 2

    window.show()
    if owns_app:
        return app.exec()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="main.py", description="AppsManagers 统一入口"
    )
    parser.add_argument(
        "--app",
        default="launcher",
        choices=["launcher"] + [tool.key for tool in TOOLS],
        help="要启动的工具，默认显示选择页",
    )
    parser.add_argument(
        "--no-plc", action="store_true", help="离线模式：不连接 PLC"
    )
    parser.add_argument(
        "--plc-ip", default=None, help="覆盖当前工具的 PLC 地址"
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    return run(
        None if args.app == "launcher" else args.app,
        enable_plc=not args.no_plc,
        plc_ip=args.plc_ip,
    )


if __name__ == "__main__":
    raise SystemExit(main())
