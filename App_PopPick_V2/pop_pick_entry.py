"""PopPick 运行态窗口：加载设计页，点左侧页签与右侧当前页互换。

本模块只是**一层薄壳**：画面装配全部在
:class:`App_PopPick_V2.pop_pick_runtime.PopPickRuntime` 里，这里只做四件
窗口级的事——工具栏、鼠标手势、状态栏、关闭流程。与
``App_test_fixture/fixture_app.py`` 的分工完全一致。

装配链（旧 ``qgraphics_runtime.py`` 已删除）::

    PopPickWindow
      ├─ PopPickRuntime           stage + 位图顶替 + HMI 数据
      │    ├─ RuntimeStage        （Designer.CoreQGraphics.runtime）
      │    ├─ PageSnapshots       动画期 / 后台页位图
      │    └─ HmiPagesHost        7 个页面 + OPC UA 订阅
      └─ PageDeck                 卡片堆叠交互（接 stage.pages_manager）

运行态把场景切到只读显示，卡片上的真实控件设为鼠标穿透，点击落到视图，
再由 :class:`PageDeck` 做命中测试与交换动画。

例外是「最大窗口」视图与「左侧已收起」这两种状态：那时画面上只剩两页正对着
看（右侧当前页 + 左侧堆叠最上层），它们会放开交互，页内按钮可以正常操作；
同时左侧最上层不再响应点击切换——见 :meth:`_sync_card_readonly` 与
:meth:`_unswappable_card`。

「最大窗口」的取景是按当时的窗口尺寸反算出来的，所以窗口尺寸一变就要重算
（``resizeEvent`` → 合并 ``MAXIMIZE_REFIT_MS`` → :meth:`_refit_maximized`），
否则两页会缩在中间或溢出边界。重算只改缩放，不改状态。

「最前面两页」变化时对外发 :attr:`PopPickWindow.front_page_changed`：交换、
重置布局、收起/展开都会改变这两页的身份，外部只接这一条信号即可；初值用
:meth:`PopPickWindow.front_pages` 直接读。

运行方式::

    python -m App_PopPick_V2
    python -m App_PopPick_V2.pop_pick_entry --page page_9
    python App_PopPick_V2/pop_pick_entry.py --scene <绝对路径>.json
    python -m App_PopPick_V2 --no-plc --seconds 5      # 离屏自测

页面文件查找顺序：``--scene`` 指定 → 设计工程 ``pages/page_9.json``（源码
运行，设计器改完直接生效）→ ``res/myDesigner/scene/pop_pick_scene.json``
（打包后的运行态快照）。
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from typing import Optional, Sequence

if sys.platform == "win32":
    # 只用来在 nativeEvent 里读 MSG 结构（见 _is_native_window_close）
    import ctypes
    from ctypes import wintypes

# 项目根加进 sys.path：单独跑本文件时 Designer / App_PopPick_V2 才 import 得到
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

# 用绝对导入而不是 ``from .xxx``：本文件也支持被当脚本跑
# （``python App_PopPick_V2/pop_pick_entry.py``），那时没有包上下文。
from App_PopPick_V2 import pop_pick_config as cfg
from App_PopPick_V2.page_deck import PageDeck, find_page_cards
from App_PopPick_V2.pop_pick_runtime import PopPickRuntime

APP_TITLE = cfg.APP_TITLE
DEFAULT_PAGE = cfg.DEFAULT_PAGE
DEFAULT_PLC_IP = cfg.DEFAULT_PLC_IP
MAXIMIZE_REFIT_MS = cfg.MAXIMIZE_REFIT_MS

# 关窗排查：写进和 main.py 同一个 trace 文件，用来定位"关掉 PopPick 后
# 工具页不出现"到底卡在 closeEvent 的哪一步。
_CLOSE_TRACE_FILE = os.path.join(
    os.environ.get("TEMP") or os.environ.get("TMP") or ".", "apps_launcher_trace.log"
)


def _close_trace(message: str) -> None:
    import time

    line = f"[{time.strftime('%H:%M:%S')}] [pp-close] {message}"
    try:
        with open(_CLOSE_TRACE_FILE, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    print(line, file=sys.stderr, flush=True)


_WM_CLOSE = 0x0010


def _is_native_window_close(event_type, message) -> bool:
    """原生消息是不是 WM_CLOSE（非 Windows 一律 False）。"""
    if sys.platform != "win32":
        return False
    try:
        if bytes(event_type) not in (
            b"windows_generic_MSG",
            b"windows_dispatcher_MSG",
        ):
            return False
        msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
    except Exception:  # noqa: BLE001
        return False
    return msg.message == _WM_CLOSE


class _DeferredNativeClose:
    """把原生 WM_CLOSE 推迟到下一轮事件循环，再走正常的 ``close()``。

    实测（Windows + 本窗口）：点标题栏的 × 时进程直接段错误（exit 139），
    trace 停在 ``收到活动窗口 Close`` 之后、``[pp-close] closeEvent 进入``
    之前——也就是说 Qt 在处理原生 WM_CLOSE 的过程中就崩了，Python 的
    ``closeEvent`` 一次都没进来。同一次关闭改用程序内 ``window.close()``
    则完全正常（exit 0，closeEvent 全程走完）。

    差别在于原生消息是在窗口过程里**同步**派发的，而本窗口上挂着 7 个
    ``QGraphicsProxyWidget`` 与若干 OPC UA 后台线程。拦截之后只排一个
    ``singleShot(0)``，让关闭动作回到事件循环里执行，行为与 ``close()`` 一致。

    注意：拦截后必须自己调 ``close()``，否则点 × 关不掉窗口。
    """

    def nativeEvent(self, event_type, message):  # noqa: N802 - Qt 命名
        if _is_native_window_close(event_type, message):
            _close_trace("拦截原生 WM_CLOSE，延后一轮再关")
            QTimer.singleShot(0, self.close)
            return True, 0
        return super().nativeEvent(event_type, message)


def _page_file_candidates(page: str) -> list[str]:
    """页面文件的候选路径（源码运行 → 打包后的运行态场景副本）。"""
    candidates = [
        os.path.join(
            cfg.PROJECT_ROOT, "Designer", "Core", "data.json", "datas", "design",
            "pages", f"{page}.json",
        )
    ]
    if getattr(sys, "frozen", False):
        # 打包后设计工程不一定跟着走，退到 res 下的运行态场景副本。
        try:
            from res.designer_resource_manager import resource_manager as res_mng

            path = res_mng.get_json_path("pop_pick_scene.json")
            if path and os.path.isfile(path):
                candidates.append(path)
        except Exception:  # noqa: BLE001 - 资源包缺失时按"没找到"处理
            pass
    return candidates


def resolve_page_file(page: str) -> str:
    for path in _page_file_candidates(page):
        if path and os.path.isfile(path):
            return path
    tried = "\n".join(_page_file_candidates(page))
    raise FileNotFoundError(f"找不到页面文件「{page}」，已尝试：\n{tried}")


class PopPickWindow(_DeferredNativeClose, QMainWindow):
    """运行态主窗口：一张舞台 + 一个页面堆叠交互。"""

    # 画面上「最前面」的两页变了就发一次：``(当前页名, 左侧堆叠最上层页名)``。
    #
    # 外部只接这一条信号就够了，不用分别去接 deck 的 ``swap_finished`` /
    # ``fold_changed``：交换、重置布局、收起/展开这些路径都会改变"正对着看的
    # 是哪两页"，逐个订阅一定会漏（重置布局就不发 swap_finished）。
    # 只在**身份真的变了**时发：放大到最大视图、重算取景这类只改缩放的操作不触发。
    # 初值不发信号，需要的话直接读 :meth:`front_pages`。
    front_page_changed = Signal(str, str)

    def __init__(
        self,
        *,
        page: str = DEFAULT_PAGE,
        scene_path: Optional[str] = None,
        plc_ip: str = DEFAULT_PLC_IP,
        enable_plc: bool = True,
        hmi_demo: bool = False,
        hmi_endpoint: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.plc_ip = plc_ip
        self.enable_plc = enable_plc
        # 统一入口的 --no-plc 走 enable_plc=False，等价于「不连 OPC UA、用模拟数据」
        self.hmi_demo = bool(hmi_demo or not enable_plc)
        self.hmi_endpoint = hmi_endpoint
        self.scene_path: Optional[str] = None
        self.deck: Optional[PageDeck] = None

        self._press_pos: Optional[QPointF] = None
        self._dragged = False
        # 「最大窗口」视图下锁定左侧最上层那一页，防止看着看着把正对着
        # 的那页点跑了。任何重新取景的动作（适应窗口/重置/滚轮缩放）都会
        # 解除锁定，见 _set_maximized 的调用点。
        self._maximized = False
        # 窗口尺寸变化后重算最大视图取景用的合并定时器（见 resizeEvent）
        self._maximize_refit_timer: Optional[QTimer] = None
        # 上一次发信号时「最前面两页」的身份，用来只在真的换人时发一次
        self._front_pages: tuple = ()

        self.setObjectName("popPickWindow")
        self.setWindowTitle(APP_TITLE)
        self.resize(*cfg.WINDOW_SIZE)
        self.statusBar().showMessage("正在加载场景…")

        # ---- 画面装配：全部交给运行时 --------------------------------
        self.runtime = PopPickRuntime(parent=self)
        self.stage = self.runtime.stage
        #: 旧名字保留：PageDeck / 事件过滤 / 取景都把它当"场景"用
        self.scene = self.stage.view
        #: 旧名字保留：页面卡片视图（只暴露 widget 图元）
        self.scene_manager = self.stage.pages_manager
        self.scene.setObjectName("popPickScene")
        self.setCentralWidget(self.scene)
        # QGraphicsView 的鼠标事件先进 viewport，事件过滤必须装在那里；
        # 装在 view 上收不到 MouseButtonPress / Wheel 这些视口事件。
        self.scene.viewport().installEventFilter(self)

        self._load_scene(scene_path or resolve_page_file(page))
        self._install_deck()
        self._build_actions()

        from .ink_pond_widget import InkPondWidget
        self.stage.set_factory(cfg.BACKGROUND_NAME,
                               lambda host: InkPondWidget(host))
        # 7 个 HMI 页面统一由 HmiPagesHost 挂载：按卡片名 set_widget_factory，
        # 一个 OpcUaManager 共享一条订阅，断线重连/关窗停机都由它负责。
        self._hmi = self.runtime.install_hmi(
            demo=self.hmi_demo,
            endpoint=self.hmi_endpoint,
            active_only=True,
        )
        self._hmi.connection_changed.connect(self._on_hmi_connection)
        self.front_page_changed.connect(self._on_front_page_changed)
        # front_page_changed 不发初值，构造时手动对齐一次
        self._hmi.set_active_cards(self.front_pages())
        self.runtime.start()

        self.statusBar().showMessage(
            "点击左侧任意页面与右侧当前页互换 ｜ 拖动可平移画布 ｜ "
            "双击空白背景收起/展开左侧页面"
        )
        # 记下初始的「最前面两页」但不发信号：构造期间没有谁接得上，
        # 外部要初值直接读 front_pages()。
        self._front_pages = self.front_pages()

    # ------------------------------------------------------------------
    # 场景
    # ------------------------------------------------------------------
    def _load_scene(self, path: str) -> None:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"场景文件不存在: {path}")
        self.scene_path = path
        count = self.runtime.load(path)
        if not count:
            raise RuntimeError(
                f"场景装载失败（{os.path.basename(path)}）："
                f"{self.stage.load_error}")
        # 取景由窗口驱动（fit_mode="none"）：布局收敛后按「最前面两页」定画面，
        # 见 showEvent / resizeEvent。

    # ------------------------------------------------------------------
    # 页面堆叠
    # ------------------------------------------------------------------
    def _install_deck(self) -> None:
        cards = find_page_cards(self.scene_manager.m_sorted_items)
        if len(cards) < 2:
            raise RuntimeError(
                f"页面「{os.path.basename(str(self.scene_path))}」里只有 "
                f"{len(cards)} 张卡片图元，无法做页面互换"
            )
        for card in cards:
            # 只读 → 承载控件设 WA_TransparentForMouseEvents，点击才能穿透到
            # 视图（否则一下点就被页内的输入框自己吃掉）。
            card.set_widget_readonly(True)

        self.deck = PageDeck(self.scene, cards, parent=self)
        self.deck.swap_finished.connect(self._on_swap_finished)
        # 收起/展开会改变"画面上正对着看的是哪两页"，可交互集合要跟着走。
        # 接信号而不是只在 _toggle_fold 里同步：reset()、滚轮缩放前的展开
        # 等路径都会改变折叠状态，逐个补调用一定会漏。
        self.deck.fold_changed.connect(self._on_fold_changed)
        # 渲染策略（位图顶替 + 动画期整窗重绘门控）由运行时提供
        self.runtime.bind_deck(self.deck)
        # 卡片布局依赖窗口尺寸（视图坐标），布局收敛后再对一次视图
        self.scene.refresh_embedded_widgets()

    def _on_swap_finished(self, entered: str, left: str) -> None:
        self.statusBar().showMessage(f"已切换到「{entered}」，「{left}」已放回左侧", 4000)
        # 交换后 Z 值互换过，「堆叠最上层」可能换人 → 最大视图下放开交互的
        # 那张卡得跟着走，否则用户点着的是新最上层却还是只读。
        self._sync_card_readonly()

    # ------------------------------------------------------------------
    # 「最前面两页」及其变化通知
    # ------------------------------------------------------------------
    def front_pages(self) -> tuple:
        """画面上正对着看的那两页：``(当前页名, 左侧堆叠最上层页名)``。

        没有卡片时返回 ``("", "")``。放在这里而不是 :class:`PageDeck` 里：
        "最前面"是**视图状态**的一部分（收起后左侧只剩封面、最大视图下只有
        这两页在放大），只有窗口同时掌握折叠与取景信息。
        """
        if self.deck is None:
            return ("", "")
        slot = self.deck.slot_card()
        stack = self.deck.stack_cards()
        return (
            slot.get_name() if slot is not None else "",
            stack[0].get_name() if stack else "",
        )

    def _refresh_front_pages(self) -> None:
        """核对「最前面两页」是否换人，变了就发 :attr:`front_page_changed`。

        读当前状态比监听事件可靠：交换、重置布局、收起/展开都会改变这两页
        的身份，而它们分散在 ``swap_finished`` / ``fold_changed`` / ``reset()``
        三处，逐个订阅必漏。这里只做一次"快照比较"，可以放心挂在
        :meth:`_sync_card_readonly` 后面。
        """
        current = self.front_pages()
        if current == self._front_pages:
            return
        self._front_pages = current
        self.front_page_changed.emit(*current)

    # ------------------------------------------------------------------
    # 卡片只读 / 可交互
    # ------------------------------------------------------------------
    def _on_fold_changed(self, folded: bool) -> None:
        """收拢状态变化后重算"哪些卡可交互"。"""
        self._sync_card_readonly()

    def _set_maximized(self, maximized: bool) -> None:
        """切换「最大视图」状态，并同步各卡片的只读标志。"""
        self._maximized = bool(maximized)
        self._sync_card_readonly()

    def _sync_card_readonly(self) -> None:
        """按当前视图状态刷新每张卡的只读标志。

        常规视图：全部只读。承载控件设 ``WA_TransparentForMouseEvents``，
        鼠标穿透到视图，一次点击就是一次页面交换；控件自己要吃事件的话
        （``QTextEdit`` 一按下就抢走）交换就永远点不动了。

        最大视图 / 左侧已收起：**画面上正对着看的那两页恢复可交互**（右侧
        当前页 + 左侧堆叠最上层）。这时它们已经不会再被一次点击点走，此时
        还让它们鼠标穿透，等于页内按钮也点不动——同一块像素上"点击=交换"
        和"按钮可点"互斥，这两种状态正好把冲突解掉。其余卡片保持只读，
        点击照旧落到视图。
        """
        if self.deck is None:
            return
        interactive = self._interactive_cards()
        for card in self.deck.cards():
            # 用身份比较而不是 in：图元是 Qt 对象，命中的必须是同一个实例
            readonly = not any(card is other for other in interactive)
            # 状态没变就别碰：set_widget_readonly 会顺带跑一次控件树遍历。
            if card.widget_readonly() != readonly:
                card.set_widget_readonly(readonly)
        # 只读刷完，顺手核对「最前面两页」是否换人：交换（Z 互换）、收起/
        # 展开、重置布局都会走到这里，是唯一一个覆盖全的状态变化点。
        self._refresh_front_pages()

    def _interactive_cards(self) -> tuple:
        """放开交互的卡片——画面上正对着看、撑得最开的那两页。

        返回 ``(右侧当前页, 左侧堆叠最上层)``；常规视图返回空元组（全只读）。
        两侧都放开：一边是"当前页"，一边是"正在看的那页"，只放开一半会让
        用户点右边那页时毫无反应。
        """
        if self.deck is None:
            return ()
        if not (self._maximized or self.deck.is_folded()):
            return ()
        front = []
        slot = self.deck.slot_card()
        if slot is not None:
            front.append(slot)
        stack = self.deck.stack_cards()
        if stack:
            front.append(stack[0])
        return tuple(front)

    def _unswappable_card(self):
        """不允许再被点走的那一张：左侧堆叠最上层。

        最大视图与收起状态都算——这两种状态里它就是"用户正看着的封面"，
        一点就跑掉等于把画面换了个样子。锁定只针对它：右侧是槽位，点了
        本来也不交换。每次现算，不缓存引用：交换之后最上层会换人。
        """
        if self.deck is None:
            return None
        if not (self._maximized or self.deck.is_folded()):
            return None
        stack = self.deck.stack_cards()
        return stack[0] if stack else None

    # ------------------------------------------------------------------
    # 工具栏
    # ------------------------------------------------------------------
    def _build_actions(self) -> None:
        toolbar = self.addToolBar("页面")
        toolbar.setObjectName("pop_pick_toolbar")
        toolbar.setMovable(False)

        reset_action = QAction("重置布局", self)
        reset_action.setToolTip("把卡片放回页面文件里记录的初始位姿与 Z 值")
        reset_action.triggered.connect(self._reset_layout)
        toolbar.addAction(reset_action)

        fit_action = QAction("适应窗口", self)
        fit_action.setToolTip("缩放到能看全所有卡片")
        fit_action.triggered.connect(self._fit_view)
        toolbar.addAction(fit_action)

        maximize_action = QAction("最大窗口", self)
        maximize_action.setToolTip("把最前面的两页放大到撑满窗口")
        maximize_action.triggered.connect(self._maximize_view)
        toolbar.addAction(maximize_action)

        self.plc_status_action = QAction(
            "OPC UA：离线演示" if self.hmi_demo else "OPC UA：连接中…", self
        )
        self.plc_status_action.setEnabled(False)
        self.plc_status_action.setToolTip(
            "7 个 HMI 页面共用一条 OPC UA 订阅；端点取自变量表映射，"
            "可用 --hmi-endpoint 覆盖"
        )
        toolbar.addAction(self.plc_status_action)

    def _on_front_page_changed(self, current: str, stacked: str) -> None:
        """「最前面两页」换人：只让这两页继续收数据和重绘。

        交换 / 重置 / 收起展开都会走到这里（窗口只发这一条信号），
        不需要分别订阅 deck 的各个事件。
        """
        if getattr(self, "_hmi", None) is not None:
            self._hmi.set_active_cards((current, stacked))

    def _on_hmi_connection(self, connected: bool) -> None:
        """HmiPagesHost 广播的连接状态 → 工具栏 + 状态栏。"""
        text = "OPC UA：已连接" if connected else "OPC UA：未连接（自动重连中）"
        self.plc_status_action.setText(text)
        self.plc_status_action.setToolTip(
            f"端点 {self._hmi.endpoint}｜"
            f"{len(self._hmi.subscribe_keys)} 个订阅点"
        )
        self.statusBar().showMessage(text, 4000)

    def _reset_layout(self) -> None:
        if self.deck is None:
            return
        self.deck.reset()
        self._set_maximized(False)
        self.statusBar().showMessage("已恢复初始布局", 2500)

    def _fit_view(self) -> None:
        # 收拢时左侧卡片在视口左侧之外，把它们算进包围盒会把缩放拉爆；
        # 「重新取景」本来就意味着回到全貌，先展开再取景。
        self._unfold_if_folded()
        rect = QRectF()
        for item in self.scene_manager.m_sorted_items:
            if not item.get_visibility():
                continue
            # 背景已经铺满当前视口，把它算进包围盒只会让「适应窗口」越缩越小
            # （背景放大 → 包围盒变大 → 再 fit → 背景再放大）。
            if self.runtime.background.is_background(item):
                continue
            bound = item.sceneBoundingRect()
            rect = bound if rect.isNull() else rect.united(bound)
        # 留一圈边距，卡片边框和旋转后的尖角不贴边
        if self._show_scene_rect(rect, cfg.FIT_MARGIN_RATIO):
            self._set_maximized(False)

    def _maximize_view(self, *, announce: bool = True, unfold: bool = True) -> None:
        """把当前正在展示的两页放大到撑满窗口。

        「最前面的两页」不是 Z 前两名——扇形里 Z 最高的两张是相邻的，
        后一张被前一张整片盖住，取这两张的结果是**只有一张**卡撑满画面，
        右侧当前页反而被裁掉一半。真正「两页」指的是画面上各自完整呈现
        内容的那两张：右侧槽位上的当前页 + 左侧堆叠里最上面的一页。

        ``announce=False`` 用于窗口尺寸变化后的重算：取景要跟手，但不必
        每次都往状态栏里再播报一遍。

        ``unfold=False`` 同理——最大视图与「左侧已收起」可以同时成立，
        窗口变化时重算取景不该顺手把那摞卡摊开。
        """
        if self.deck is None:
            return
        if unfold:
            self._unfold_if_folded()
        front = []
        slot = self.deck.slot_card()
        if slot is not None:
            front.append(slot)
        stack = self.deck.stack_cards()
        if stack:
            front.append(stack[0])
        if not front:
            return

        rect = QRectF()
        for card in front:
            bound = card.sceneBoundingRect()
            rect = bound if rect.isNull() else rect.united(bound)

        # 边距比「适应窗口」紧一档：这个动作用途就是尽量放大。
        if not self._show_scene_rect(rect, cfg.MAXIMIZE_MARGIN_RATIO):
            return
        # 锁定：最大视图是"专注看这两页"的状态，左侧最上层那张占满左半屏，
        # 最容易顺手点掉。这里把它锁住，退出该状态才恢复交换——同时把它的
        # 交互打开（_set_maximized → _sync_card_readonly），页内按钮照常能点。
        self._set_maximized(True)
        if not announce:
            return
        names = "、".join(f"「{card.get_name()}」" for card in front)
        self.statusBar().showMessage(
            f"已放大到最前面两页：{names} ｜ "
            "两页均可直接操作，左侧最上层不再响应点击切换",
            4000,
        )

    def _show_scene_rect(self, rect: QRectF, margin_ratio: float) -> bool:
        """把一段 page 矩形铺满视口（``RuntimeView.set_view_scene_rect``）。"""
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            return False
        margin = max(rect.width(), rect.height()) * margin_ratio
        self.scene.set_view_scene_rect(
            rect.adjusted(-margin, -margin, margin, margin)
        )
        # proxy 是场景项，视图缩放由 Qt 自动跟随；这里补一次对齐，确保同一帧
        # 里位姿刚变过的卡片不会晚一帧才跟上（位图分辨率也随之标脏重烘）。
        self.scene.refresh_embedded_widgets()
        self.runtime.snapshots.schedule_prewarm()
        # 取景刚变，背景必须同帧跟上（等轮询会晚一帧，切换视图时能看到露边）。
        self.runtime.background.sync()
        return True

    # ------------------------------------------------------------------
    # 收起 / 展开左侧页面（双击空白处）
    # ------------------------------------------------------------------
    def _unfold_if_folded(self) -> None:
        """重新取景前把收拢的左侧页面展开（无动画，取景本身才是主角）。"""
        if self.deck is not None and self.deck.is_folded():
            self.deck.unfold(immediate=True)

    def _toggle_fold(self) -> None:
        """双击空白背景触发的收起 / 展开。"""
        if self.deck is None or self.deck.is_busy():
            return
        if self.deck.is_folded():
            if self.deck.unfold():
                self.statusBar().showMessage("左侧页面已展开", 2500)
            return
        if self.deck.fold():
            # 最大视图**不解除**：收起/展开只是把左边那一摞挪一挪，取景没变。
            if self._maximized:
                self.statusBar().showMessage(
                    "左侧页面已收起，仍在最大视图：最前页不可交换，双击空白背景展开",
                    3000,
                )
            else:
                self.statusBar().showMessage(
                    "左侧页面已收起：两页均可直接操作，双击空白背景展开", 3000
                )

    # ------------------------------------------------------------------
    # 窗口尺寸变化：最大视图的取景跟着重算
    # ------------------------------------------------------------------
    def showEvent(self, event):  # noqa: N802 - Qt 命名
        super().showEvent(event)
        # 首次显示时视口才有真实尺寸，取景要等这一刻；resizeEvent 在
        # centralWidget 布局完成前就会到，单靠它会算在极小视口上。
        self._schedule_maximize_refit()
        self.runtime.background.sync()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        # 最大视图的缩放/平移是按"当时的窗口尺寸"反算出来的，窗口一变，那两页
        # 就缩在中间或溢出边界。这里只重算、不改状态。
        self._schedule_maximize_refit()

    def _schedule_maximize_refit(self) -> None:
        """合并连续 resize 事件，等拖动停下再重算一次取景。

        逐次重算会跟着每个像素的 resize 走一遍全场景几何同步，拖大窗口时
        明显掉帧；而且每次都会引发一轮承载层重排，视觉上是抖的。
        """
        timer = self._maximize_refit_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(MAXIMIZE_REFIT_MS)
            timer.timeout.connect(self._refit_maximized)
            self._maximize_refit_timer = timer
        timer.start()

    def _refit_maximized(self) -> None:
        """按新窗口尺寸重算取景（不播报、不展开收起中的页面）。"""
        if self.deck is None:
            return
        self._maximize_view(announce=False, unfold=False)

    # ------------------------------------------------------------------
    # 鼠标：把"点一下卡片"翻译成一次交换
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
        if obj is not self.scene.viewport():
            return super().eventFilter(obj, event)

        kind = event.type()
        if kind == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            # 双击**空白背景**才是收起/展开的开关。双击卡片不算：收起状态下
            # 那两页已经放开交互，双击落在页内控件上（文本框选词、按钮连点），
            # 顺手把整摞展开等于在用户操作页面时抢走他的画面。
            if self.deck is not None and not self.deck.is_busy():
                on_card = (
                    self.deck.card_at(self._window_to_scene(QPointF(event.position())))
                    is not None
                )
                if not on_card:
                    self._toggle_fold()
        elif kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._press_pos = QPointF(event.position())
            self._dragged = False
        elif kind == QEvent.MouseMove and self._press_pos is not None:
            distance = (QPointF(event.position()) - self._press_pos).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self._dragged = True
        elif kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            press, dragged = self._press_pos, self._dragged
            self._press_pos = None
            self._dragged = False
            # 拖动是"平移画布"（视图自己处理），只有原地按放才算点击
            if press is not None and not dragged:
                self._handle_click(QPointF(event.position()))
        elif kind == QEvent.Wheel:
            if not self.scene.is_canvas_navigation_enabled():
                return super().eventFilter(obj, event)
            # 滚轮缩放等于重新取景，最大视图状态随之失效，锁定一并解除；
            # 否则用户缩回全貌后会发现最上面那页点不动。
            self._set_maximized(False)
        return super().eventFilter(obj, event)

    def _handle_click(self, window_pos: QPointF) -> None:
        if self.deck is None or self.deck.is_busy():
            return
        card = self.deck.card_at(self._window_to_scene(window_pos))
        if card is None:
            return
        if self.deck.is_folded():
            # 收起状态下左侧只剩"封面"那一张，交换没有意义；而且它已经放开
            # 交互（点击落在页内控件里），正常情况下走不到这儿，留作兜底。
            self.statusBar().showMessage(
                "左侧页面已收起，双击空白背景展开后再切换页面", 3000
            )
            return
        if card is self.deck.slot_card():
            self.statusBar().showMessage("这是当前页，点左侧任意页面进行互换", 2500)
            return
        if self._is_locked_card(card):
            self.statusBar().showMessage(
                "这一页已锁定（页内按钮可正常操作），"
                "点「适应窗口」退出最大视图后可继续交换",
                3000,
            )
            return
        self.deck.swap_with_slot(card)

    def _is_locked_card(self, card) -> bool:
        """``card`` 是否是不允许再被点走的那一张。

        注意和 :meth:`_interactive_cards` 的区别：那个返回"放开交互的两页"
        （含右侧槽位），这里只判左侧最上层——右边点了本来也不交换，不需要拦。
        """
        return card is not None and card is self._unswappable_card()

    def _window_to_scene(self, window_pos: QPointF) -> QPointF:
        """窗口像素 → page 场景坐标（``RuntimeView.window_to_page``）。"""
        return self.scene.window_to_page(window_pos)

    # ------------------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802 - Qt 命名
        _close_trace("closeEvent 进入")
        # 先让窗口消失：后面的清理（停 OPC UA 线程、回收 7 个承载控件）实测
        # 要 100~500ms，OPC UA 停机最坏还会等 3s，卡多久屏幕就空白多久。
        self.hide()
        _close_trace("窗口已 hide")
        if self._maximize_refit_timer is not None:
            self._maximize_refit_timer.stop()
        # runtime.release() 里依次：deck.stop → hmi.shutdown → snapshots.release
        # → stage.release（回收 proxy 与控件、清场景）。proxy 必须在宿主销毁前
        # 回收：QGraphicsProxyWidget 析构只把控件 setParent(None)，不 hide 也不
        # 删，页内控件会变成无父顶层窗口留在屏幕上（盖住工具选择页）。
        self.runtime.release()
        _close_trace("运行时已释放（HMI / 位图 / 承载控件 / 场景）")
        self.deck = None
        super().closeEvent(event)
        _close_trace("closeEvent 结束")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="pop_pick_entry.py", description=APP_TITLE)
    parser.add_argument(
        "--page", default=DEFAULT_PAGE, help=f"设计工程里的页面 id（默认 {DEFAULT_PAGE}）"
    )
    parser.add_argument("--scene", default=None, help="直接指定页面 JSON 的绝对路径")
    parser.add_argument("--plc-ip", default=DEFAULT_PLC_IP,
                        help="预留的 PLC 地址（HMI 已改走 OPC UA，当前仅作记录）")
    parser.add_argument("--no-plc", action="store_true",
                        help="离线模式：HMI 页面用模拟数据，不连 OPC UA")
    parser.add_argument("--hmi-demo", action="store_true",
                        help="同 --no-plc：不连 PLC，只看 7 个页面的版式")
    parser.add_argument("--hmi-endpoint", default="",
                        help="覆盖变量表映射里的 OPC UA 端点，如 opc.tcp://192.168.1.88:4840")
    parser.add_argument("--seconds", type=float, default=0.0,
                        help="大于 0 时自动退出（自测 / 截图用）")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication([sys.argv[0]])

    try:
        window = PopPickWindow(
            page=args.page,
            scene_path=args.scene,
            plc_ip=args.plc_ip,
            enable_plc=not args.no_plc,
            hmi_demo=args.hmi_demo or args.no_plc,
            hmi_endpoint=args.hmi_endpoint,
        )
    except Exception as exc:  # noqa: BLE001 - 启动失败要给出可读原因
        traceback.print_exc()
        if owns_app:
            QMessageBox.critical(None, "启动失败", f"{type(exc).__name__}: {exc}")
        return 2

    window.show()
    print(window.runtime.report())
    if args.seconds > 0:
        QTimer.singleShot(int(args.seconds * 1000), app.quit)
    if owns_app:
        return app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
