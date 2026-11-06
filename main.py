"""统一入口：一个进程承载多个 App 工具。

用法::

    python main.py                 # 工具选择页
    python main.py --app rack      # 直接进「料架 PLC 配置工具」
    python main.py --app safety    # 直接进「大小车安全 PLC 客户端」
    python main.py --app logplot   # 直接进「RCD 日志解析工具」
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
import faulthandler
import os

# 日志绘图工具会拉起 matplotlib 的 Qt 后端；后端默认按 PyQt6 → PyQt5 →
# PySide6 挑绑定，机器上同时装着 PyQt 时会抢到 PyQt 上、与本进程混用直接崩。
# 必须在任何 Qt / matplotlib 导入之前钉死。
os.environ.setdefault("QT_API", "pyside6")

import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from PySide6.QtCore import Qt, QEvent, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
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

# 排查「关掉工具后选择页没回来」用：默认把打开 / 关闭 / 回落的关键节点
# 追加写到 %TEMP%/apps_launcher_trace.log（同时打 stderr）。
# APPS_LAUNCHER_TRACE=0 可以关掉。
_TRACE = os.environ.get("APPS_LAUNCHER_TRACE") != "0"
_TRACE_FILE = os.path.join(tempfile.gettempdir(), "apps_launcher_trace.log")

# 进程直接崩掉（段错误）时，Python 层一行日志都来不及打，"界面卡死"和
# "崩溃"在屏幕上看起来是一样的。faulthandler 能在信号处理里落一份带 C 帧
# 的栈，落到单独的文件里，用来区分这两种情况。
_FAULT_FILE = None
try:
    _FAULT_FILE = open(  # noqa: SIM115 - 进程生命周期内一直开着
        os.path.join(tempfile.gettempdir(), "apps_launcher_fault.log"),
        "a",
        buffering=1,
        encoding="utf-8",
    )
    faulthandler.enable(file=_FAULT_FILE, all_threads=True)
except Exception:  # noqa: BLE001
    _FAULT_FILE = None


def _trace(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    try:
        # 这个文件是常年追加的，超过 256KB 就重开，避免无限涨。
        if os.path.getsize(_TRACE_FILE) > 256 * 1024:
            os.remove(_TRACE_FILE)
    except OSError:
        pass
    try:
        with open(_TRACE_FILE, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    if _TRACE:
        print(f"[工具平台] {message}", file=sys.stderr, flush=True)


def _thread_stacks(reason: str) -> None:
    """把所有线程的调用栈追加到 trace 文件。

    只在主线程心跳停转时调用：这时界面上只能看到"卡死"，分不清是卡在
    Python 代码里、卡在等 GIL、还是卡在 Qt 的窗口调用里。抓一次栈就能落到
    具体函数，比继续猜快得多。
    """
    try:
        with open(_TRACE_FILE, "a", encoding="utf-8") as handle:
            handle.write(f"[{time.strftime('%H:%M:%S')}] !!! 主线程停转：{reason}\n")
            try:
                # faulthandler 连 C/C++ 层的帧一起 dump，能看出是不是卡在
                # show()/raise() 这类 Qt 调用里（纯 Python traceback 看不到）。
                faulthandler.dump_traceback(file=handle, all_threads=True)
            except Exception:  # noqa: BLE001
                pass
            main_frame = sys._current_frames().get(threading.main_thread().ident)
            if main_frame is not None:
                handle.write("--- 主线程 Python 栈（带源码行）---\n")
                handle.write("".join(traceback.format_stack(main_frame)))
            handle.flush()
    except OSError:
        pass


class _MainThreadWatchdog(threading.Thread):
    """主线程心跳监控：停转超过 stall_seconds 就抓一次栈。

    心跳由主线程上的 QTimer 递增；本线程只读计数，不碰 Qt。主线程如果卡在
    C++ 调用里（GIL 已释放）或死等 GIL，本线程都还能跑，因此观测有效。
    """

    def __init__(self, beat: Callable[[], int], stall_seconds: float = 3.0) -> None:
        super().__init__(name="launcher-watchdog", daemon=True)
        self._beat = beat
        self._stall_seconds = stall_seconds
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # noqa: D102 - Thread 接口
        last = self._beat()
        changed_at = time.monotonic()
        while not self._stop.wait(0.25):
            current = self._beat()
            if current != last:
                last = current
                changed_at = time.monotonic()
                continue
            stalled = time.monotonic() - changed_at
            if stalled >= self._stall_seconds:
                _thread_stacks(f"心跳 {stalled:.1f}s 未推进")
                return


def _force_foreground(widget: QWidget) -> None:
    """Windows：把窗口从最小化恢复并提到最前，绕开前台窗口限制。

    Qt 的 ``raise_()`` / ``activateWindow()`` 最终会落到 ``SetForegroundWindow``，
    但系统只允许"当前拥有前台的进程"或"刚失去前台的进程"调用它。工具窗口
    刚关闭时前台归属常被系统判给别的进程，此时 ``activateWindow()`` 静默失败，
    表现就是"选择页已经 show 了，但还压在别的窗口后面 / 只在任务栏闪"。
    ``ShowWindow(SW_RESTORE) + BringWindowToTop`` 是同一进程内的窗口操作，
    不受这条限制。
    """
    try:
        import ctypes

        hwnd = int(widget.winId())
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001 - 提权失败不影响主流程
        pass



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


def _make_log_plot(enable_plc: bool, plc_ip: Optional[str]) -> QMainWindow:
    """RCD 日志解析工具（不涉及 PLC，后两个参数只是对齐工厂签名）。

    ``log_plot_main`` 的绘图模块在 import 时会初始化 matplotlib 的 Qt 后端，
    必须等本进程的 QApplication 建好再导入；``run()`` 满足这个顺序，
    这里也因此在点击卡片时才 import。
    """
    from App_LogPlot.log_plot_entry import MainWidget

    return MainWidget()


def _make_designer(enable_plc: bool, plc_ip: Optional[str]) -> QMainWindow:

    from Designer import DesignWindow

    return DesignWindow()

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
    Tool(
        key="logplot",
        title="RCD 日志解析工具",
        subtitle="日志导入、曲线绘制、主副轴组合图与数据播放",
        badge="LOGPLOT",
        factory=_make_log_plot,
    ),
    Tool(
        key="Designer",
        title="场景设计器",
        subtitle="设计页面，导出Json文件",
        badge="DESIGNER",
        factory=_make_designer,
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
        # 与 _active 配对的认领令牌（见 _on_window_destroyed）
        self._active_token: Optional[object] = None
        self._quitting = False
        # 关闭工具后的状态采样器：关窗后每 500ms 记一行窗口状态，共 12 行。
        # 排查"关掉工具后选择页不出现"时，这 12 行能直接看出到底卡在哪一步
        # （没 show / show 了但最小化 / 在屏幕外 / show 了但被别的窗口盖住）。
        self._diag_timer: Optional[QTimer] = None
        self._diag_left = 0
        # 主线程心跳 + 看门狗：界面卡死时自动把调用栈写进 trace 文件，
        # 不用再靠"卡了几秒"猜是哪一步（见 _MainThreadWatchdog）。
        self._beat = 0
        self._beat_timer: Optional[QTimer] = None
        self._watchdog: Optional[_MainThreadWatchdog] = None

        self.setObjectName("launcherRoot")
        self.setWindowTitle(LAUNCHER_TITLE)
        self.setStyleSheet(LAUNCHER_QSS)
        self.setMinimumSize(760, 400)
        self._build()
        self._start_watchdog()

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

        # 两列网格：工具数增加到 4 个后，单行横排会把窗口撑到屏幕外
        cards = QGridLayout()
        cards.setSpacing(18)
        cards.setColumnStretch(2, 1)  # 右侧留白吃掉多余宽度
        for index, tool in enumerate(TOOLS):
            card = ToolCard(tool)
            card.clicked.connect(self._open)
            cards.addWidget(card, index // 2, index % 2)
        root.addLayout(cards)
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

        # 各工具的 closeEvent 都会做真实清理（停线程 / 断 PLC / 停播放任务），
        # 因此关闭即销毁，不缓存实例复用。
        window.setAttribute(Qt.WA_DeleteOnClose, True)
        window.installEventFilter(self)
        # Close 之外的第二条兜底路径：窗口被销毁（deleteLater / C++ 侧直接
        # 删除 / 没走 closeEvent）时不保证有 QEvent.Close 经过 eventFilter，
        # 但 destroyed 一定会发。用 token 认领，避免上一个窗口迟到的
        # destroyed 把新开的窗口误判成已关闭。
        token = object()
        self._active_token = token
        window.destroyed.connect(lambda *_: self._on_window_destroyed(token))
        self._active = window
        _trace(f"打开 {tool.key}: {type(window).__name__}")

        window.show()
        window.raise_()
        window.activateWindow()
        self.hide()
        _trace(f"选择页已隐藏，等待 {tool.key} 关闭")

    def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
        if event.type() == QEvent.Close and obj is self._active:
            _trace("收到活动窗口 Close")
            self._active = None
            self._active_token = None
            if not self._quitting:
                try:
                    self._start_launcher_diag()
                except Exception as exc:  # noqa: BLE001
                    _trace(f"启动采样失败: {exc!r}")
                # **立刻**回落，不再等工具窗口的 closeEvent 跑完。
                # closeEvent 里要做停 PLC 线程、回收承载控件这些清理，实测
                # 会花 100~500ms；万一哪一步卡住，排在事件循环里的
                # singleShot(0) 就永远不会执行，屏幕上一直空着——现象就是
                # "工具页没恢复"。先 show 出来，后面清理卡多久都不影响可见性。
                try:
                    self._back_to_launcher()
                except Exception as exc:  # noqa: BLE001
                    # 这里一旦把异常抛出去，Close 事件就没派发下去，
                    # 工具窗口的 closeEvent 也不会跑，窗口会留在屏幕上。
                    _trace(f"回落失败: {exc!r}")
        return super().eventFilter(obj, event)

    def _on_window_destroyed(self, token: object) -> None:
        """窗口被销毁时的兜底：没收到 Close 也要回到选择页。

        只认领"当前这个"窗口的销毁通知：destroyed 走 DeferredDelete，可能
        晚一轮才到，那时用户也许已经启动了另一个工具，不能把选择页抢到前面。
        """
        if self._quitting or getattr(self, "_active_token", None) is not token:
            return
        _trace("窗口 destroyed（未收到 Close）")
        self._active = None
        self._active_token = None
        QTimer.singleShot(0, self._back_to_launcher)

    def _start_watchdog(self) -> None:
        timer = QTimer(self)
        timer.setInterval(200)
        timer.timeout.connect(self._on_beat)
        timer.start()
        self._beat_timer = timer
        watchdog = _MainThreadWatchdog(lambda: self._beat)
        watchdog.start()
        self._watchdog = watchdog

    def _on_beat(self) -> None:
        self._beat += 1

    def _start_launcher_diag(self) -> None:
        """关闭工具后采样 6 秒窗口状态（12 行），写进 trace 文件。

        只看一个时间点的状态分不清"没 show"、"show 了但被最小化"、
        "show 了但在屏幕外"、"show 了但被别的顶层窗口盖住"这几种情况，
        连续采样才能看出回落是没发生、还是发生了又被打回去。
        """
        timer = self._diag_timer
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(500)
            timer.timeout.connect(self._sample_launcher)
            self._diag_timer = timer
        self._diag_left = 12
        timer.start()

    def _sample_launcher(self) -> None:
        if self._diag_left <= 0:
            if self._diag_timer is not None:
                self._diag_timer.stop()
            return
        self._diag_left -= 1
        geom = self.frameGeometry()
        screen = self.screen()
        tops = [
            w for w in QApplication.topLevelWidgets()
            if w.isVisible() and w.parent() is None
        ]
        _trace(
            f"diag#{12 - self._diag_left:02d} visible={self.isVisible()} "
            f"minimized={self.isMinimized()} state={self.windowState().value} "
            f"geom=({geom.x()},{geom.y()},{geom.width()},{geom.height()}) "
            f"active={type(self._active).__name__ if self._active else None} "
            f"screen={screen.name() if screen else None} tops={len(tops)}"
            + ("" if not tops else " " + ",".join(type(w).__name__ for w in tops))
        )

    def _back_to_launcher(self) -> None:
        if self._quitting:
            return
        # 兜底路径可能在用户已经又启动了别的工具之后才到（destroyed 走
        # DeferredDelete，晚一轮），这时不能把选择页又拽到前面去。
        if self._active is not None:
            return

        # 先判"是否真的正常可见"。注意 **最小化的窗口 isVisible() 依然是 True**：
        # 早期版本这里是 `if self.isVisible(): raise_(); return` 的快退，结果
        # "窗口被最小化"——也就是最符合现象的那条（任务栏有图标、屏幕上没窗口）
        # ——永远走不到下面的纠正代码，showNormal / 强制前台全成了死代码。
        minimized = self.isMinimized() or bool(self.windowState() & Qt.WindowMinimized)
        offscreen = not self._is_on_screen()
        if self.isVisible() and not minimized and not offscreen:
            # Close 与 destroyed 两条路都会调到这里，已经正常可见就只抬一下。
            # 同样不能在本栈里抢前台（见本函数末尾的说明），排到下一轮。
            _trace("选择页本就可见，仅抬升")
            QTimer.singleShot(0, self._raise_launcher)
            return

        _trace(
            f"回到选择页（visible={self.isVisible()} minimized={minimized} "
            f"offscreen={offscreen} state={self.windowState().value} "
            f"geom={self.frameGeometry().getRect()}）"
        )
        # 下面三步都是为了"进程还在、窗口却看不见"这几种情况：
        # 1) 位置落在所有屏幕之外（拔过副屏 / 改过分辨率）；
        # 2) 之前被最小化过，show() 出来仍然是 minimized；
        # 3) Windows 把前台交给刚关闭的窗口后，拒绝再给选择页。
        # 每一步单独打点：这三步都是同步的窗口系统调用，卡死的话日志会停在
        # 某个"前/后"之间，下次就不用再猜。
        try:
            _trace("屏外纠正 前")
            self._restore_on_screen()
            _trace("屏外纠正 后")
        except Exception as exc:  # noqa: BLE001
            _trace(f"屏外纠正失败: {exc!r}")
        try:
            if minimized:
                self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
            _trace("showNormal 前")
            self.showNormal()
            _trace("showNormal 后")
        except Exception as exc:  # noqa: BLE001
            _trace(f"显示选择页失败: {exc!r}")
        # raise_ / activateWindow / SetForegroundWindow **不能**放在这里。
        # 本函数是从工具栏窗口的 Close 事件里同步调过来的：那一刻 Windows
        # 正在处理 WM_CLOSE，如果在这条栈里把前台抢给同一进程的另一个顶层
        # 窗口，系统会同步和"正在关闭的那个窗口"握手，两边互等 —— 表现就是
        # 选择页出来了，但整个界面卡死、点什么都没反应。
        # 只做"让它可见"，抢前台留给下一轮事件循环。
        QTimer.singleShot(0, self._raise_launcher)

    def _is_on_screen(self) -> bool:
        """窗口是否与任意一块屏幕的可视区域相交。"""
        screens = QGuiApplication.screens()
        if not screens:
            return True
        frame = self.frameGeometry()
        return any(screen.availableGeometry().intersects(frame) for screen in screens)

    def _restore_on_screen(self) -> None:
        """窗口若完全落在所有屏幕之外，挪回主屏中央。"""
        screens = QGuiApplication.screens()
        if not screens:
            return
        frame = self.frameGeometry()
        for screen in screens:
            if screen.availableGeometry().intersects(frame):
                return
        primary = QGuiApplication.primaryScreen() or screens[0]
        available = primary.availableGeometry()
        _trace(f"窗口在屏幕外 {frame.getRect()}，移回主屏")
        self.move(
            available.center().x() - frame.width() // 2,
            available.center().y() - frame.height() // 2,
        )

    def _raise_launcher(self) -> None:
        if self._quitting or not self.isVisible():
            return
        # 最小化的窗口 isVisible() 也是 True，这里必须先恢复再抬升
        try:
            _trace("抬升 前")
            if self.isMinimized():
                self.showNormal()
            self.raise_()
            _trace("raise 后")
            self.activateWindow()
            _trace("activateWindow 后")
            if sys.platform == "win32":
                _force_foreground(self)
                _trace("强制前台 后")
        except Exception as exc:  # noqa: BLE001
            _trace(f"抬升选择页失败: {exc!r}")

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

    :param app_key: ``TOOLS`` 里注册的 key（``rack`` / ``safety`` /
        ``PopPick`` / ``logplot``）直接启动对应工具；为空或 ``"launcher"``
        时显示选择页。
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
    _trace(f"{'=' * 20} 启动 app={app_key or 'launcher'} plc={enable_plc}")

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
