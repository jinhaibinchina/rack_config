"""PopPick 运行态装配：一个 :class:`RuntimeStage` + 位图顶替 + HMI 数据。

参照 ``App_test_fixture/fixture_runtime.py`` 的分工，把「谁负责什么」定死：

.. code-block:: text

    PopPickRuntime                 ← 本模块：装配 / 数据 / 生命周期
      ├─ RuntimeStage              （Designer.CoreQGraphics.runtime）
      │    ├─ RuntimeScene/RuntimeView   画面与取景
      │    ├─ RuntimeRegistry            图元门面（卡片就是 RuntimeElement）
      │    ├─ WidgetHost                 卡片 → QGraphicsProxyWidget
      │    └─ TagBus                     数据合流（本项目由 HmiPagesHost 自带）
      ├─ PageSnapshots             动画期 / 后台页的位图顶替
      └─ HmiPagesHost              7 个 HMI 页面 + OPC UA 订阅（可选 demo）

装配顺序（:meth:`PopPickRuntime.load`）固定：

1. ``stage.load()`` —— 装载页面、切运行态、建 registry、建 proxy 集合；
2. ``schedule_prewarm()`` —— 视图变换稳定后再烘位图（fit 之前烘的是大图）；
3. ``install_hmi()`` —— 逐张卡片 ``set_widget_factory`` 挂整页控件，
   并把卡片尺寸校正到 750×1000（``HmiPagesHost`` 内部完成）。

**卡片工厂必须先于 HMI 才有意义**：``WidgetHost`` 只给「mapping 里登记过的
图元」造控件；本项目用 :class:`NoControlProvider` 兜底返回 ``None``，所以
没有挂页面的 widget 图元不会像旧路径那样被核心造出一个 QTextEdit。

与旧 ``qgraphics_runtime.py`` 的对应关系
========================================
============================  ======================================
旧实现                         现在
============================  ======================================
``create_runtime_scene()``     ``PopPickRuntime(...)``（stage.view 即 centralWidget）
``RuntimeWidgetLayer``         ``WidgetHost``（框架）+ ``PageSnapshots``（业务）
``RuntimeCard``                ``RuntimeElement``（框架，方法集已对齐）
``RuntimeSceneManager``        ``stage.pages_manager``
``RuntimeView``                ``RuntimeView``（框架，含 sceneToView / window_to_page）
============================  ======================================

``PageDeck`` 与 ``HmiPagesHost`` 的调用面（``get_scene_center_pos`` /
``set_angle`` / ``setPos`` / ``getSize`` / ``mapFromScene`` / ``set_zValue`` /
``fit_widget_size`` / ``m_sorted_items`` / ``findItemByName``）在
``RuntimeElement`` 与 ``LegacyManager`` 上都有同名实现，所以这两个文件
本轮只加了「渲染策略」这一个钩子，其余一行未改。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from Designer.CoreQGraphics.runtime import RuntimeStage
from Designer.CoreQGraphics.runtime.widgets import ControlProvider

from . import pop_pick_config as cfg
from .background_fitter import BackgroundFitter
from .page_snapshots import PageSnapshots


class NoControlProvider(ControlProvider):
    """不造任何控件的兜底 provider。

    ``RuntimeStage`` 默认用 :class:`DefaultControlProvider`，它会按
    ``widgetType`` 造 QLineEdit / QTextEdit。PopPick 的每张卡都必须是外部
    工厂造的整页 HMI，多造一个文本框就会有一层控件盖在页面上。
    """

    def signature(self, element) -> tuple:
        return ()

    def create(self, element, host=None):
        return None


class PopPickRuntime(QObject):
    """一套可独立运行的 PopPick 画面（舞台 + 位图 + HMI 数据链路）。"""

    message = Signal(str, str)
    connectionChanged = Signal(bool)

    def __init__(self, page_path: str | Path | None = None,
                 parent: QObject | None = None, *,
                 snapshots_enabled: bool = cfg.SNAPSHOT_ENABLED) -> None:
        super().__init__(parent)
        self.page_path = Path(page_path) if page_path else None
        self.stage = RuntimeStage(
            page_path=str(self.page_path or ""),
            widget_mode=cfg.WIDGET_MODE,
            fit_mode=cfg.FIT_MODE,
            geometry_profile=cfg.GEOMETRY_PROFILE,
            flush_ms=cfg.FLUSH_MS,
            provider=NoControlProvider(),
        )
        

        self.snapshots = PageSnapshots(self.stage, self,
                                       enabled=snapshots_enabled)
        self.hmi = None
        self.deck = None
        self._deck_bound = False
        # 视图每次变换（fit / 最大视图 refit / resize）后重新对齐位图分辨率。
        # fit_mode="none" 时框架不会自动 fit，取景由窗口驱动，这里只挂预热。
        self.stage.view.on_viewport_resized = self.snapshots.schedule_prewarm
        # 背景图元跟着视口铺满：它会包装上面的回调（保留预热），并额外监听
        # 滚动条 / 滚轮 / 视图变换。必须在 load() 之前建好，才能抓到设计期
        # 的 _page 快照。
        self.background = BackgroundFitter(self.stage, self)
        self.stage.pageFailed.connect(
            lambda text: self._log(text, "err"))

    # -- 装配 -----------------------------------------------------------
    def load(self, page_path: str | Path | None = None) -> int:
        """装载页面；失败返回 0，原因在 ``stage.load_error``。

        路径必须显式传给 ``stage.load()``：``RuntimeStage`` 构造时收的是
        字符串（本类允许先建 stage 再决定装哪一页），空路径直接报
        「未指定页面路径」。
        """
        if page_path is not None:
            self.page_path = Path(page_path)
        if self.page_path is None:
            self.stage.load_error = "未指定页面路径"
            return 0
        count = self.stage.load(str(self.page_path))
        if not count:
            return count
        # 换页要重抓设计期 _page 快照：之后每次背景同步都会还原它，
        # page_data() 始终等于磁盘 JSON。这里**不**立刻 sync —— 装载期的
        # 视口还没布局完，而且「runtime.load() 后与旧适配层对拍」要求所有
        # 图元仍是设计几何；首次显示由窗口 showEvent / 取景 / 轮询触发同步。
        self.background.capture()
        self.snapshots.schedule_prewarm()
        return count

    def install_hmi(self, *, demo: bool = False, endpoint: str = "",
                    active_only: bool = True,
                    static_background: bool = True):
        """挂 7 个 HMI 页面（每张卡一个整页控件）。

        ``auto_start=False``：窗口要先算出「最前面两页」再 ``start()``，
        初始订阅才只覆盖这两页。活跃页由窗口的 ``front_page_changed`` 驱动。
        """
        from .hmi import attach_hmi_pages

        self.hmi = attach_hmi_pages(
            self.stage.pages_manager,
            parent=self,
            endpoint=endpoint,
            demo=demo,
            active_only=active_only,
            static_background=static_background,
            # 后台页的位图顶替交给业务侧策略，不再走 card.set_motion_cache
            static_policy=self.snapshots,
            auto_start=False,
        )
        self.hmi.connection_changed.connect(self.connectionChanged)
        # ``WidgetHost.set_factory`` 只登记工厂、**不立刻造控件**（它默认
        # 等到下一次 rebuild）。7 张卡是逐张登记的，所以这里必须补一次
        # rebuild，否则一张控件都不会挂上——现象是画面全白、位图也烘不出来。
        # 顺序也不能反：``_fit_card`` 已经把卡片尺寸校正到 750×1000，
        # rebuild 造出来的 proxy 才是最终尺寸。
        self.stage.widgets.rebuild()
        self.bind_deck(self.deck)
        return self.hmi

    def bind_deck(self, deck) -> None:
        """接上页面堆叠：渲染策略 + 动画收尾的后台页快照恢复。

        窗口在 ``_install_deck`` 里已经接过一次，``install_hmi`` 再调一次是为了
        「先装 HMI 后装 deck」的调用顺序也能成立；重复接同一个 deck 不重复
        连信号（否则 ``_on_deck_busy`` 每次动画结束跑两遍）。
        """
        if deck is None:
            return
        if deck is self.deck and self._deck_bound:
            return
        self.deck = deck
        deck.set_render_policy(self.snapshots)
        deck.busy_changed.connect(self._on_deck_busy)
        self._deck_bound = True

    def _on_deck_busy(self, busy: bool) -> None:
        """动画结束后恢复「后台页走位图、前台页用真实控件」的分配。

        动画期间全部卡都被临时位图化了（见 ``PageSnapshots.set_animating``）；
        退出窗口时它按**当时的**长期意图还原，这里再把意图本身按当前最前面
        两页刷一遍，避免刚落位的槽位卡继续停在位图上。
        """
        if not busy and self.hmi is not None:
            self.hmi.apply_static_pages()
        if not busy:
            self.snapshots.schedule_prewarm()

    # -- 数据 -----------------------------------------------------------
    def start(self) -> None:
        if self.hmi is not None:
            self.hmi.start()

    def push(self, key: str, value: Any) -> None:
        """手动灌一个点位值（回归脚本 / 联调用）。"""
        self.stage.tags.update(key, value)
        self.stage.tags.flush_now()

    # -- 生命周期 -------------------------------------------------------
    def report(self) -> str:
        hmi = self.hmi
        return (f"PopPickRuntime({self.stage.report()}, "
                f"{self.snapshots.report()}, "
                f"{self.background.report()}, "
                f"hmi={'on' if hmi is not None else 'off'}"
                f"{'/' + str(len(hmi.subscribe_keys)) + '点' if hmi else ''})")

    def release(self) -> None:
        if self.deck is not None:
            self.deck.stop()
            self.deck = None
        if self.hmi is not None:
            self.hmi.shutdown()
            self.hmi = None
        self.snapshots.release()
        self.background.release()
        self.stage.release()

    def _log(self, text: str, level: str = "info") -> None:
        self.message.emit(f"[{time.strftime('%H:%M:%S')}] {text}", level)


def cards_of(runtime: PopPickRuntime) -> list:
    """当前页面里的页面卡片（按绘制顺序）。"""
    return list(runtime.stage.pages_manager.m_sorted_items)


def find_card(runtime: PopPickRuntime, name: str):
    return runtime.stage.pages_manager.findItemByName(name)
