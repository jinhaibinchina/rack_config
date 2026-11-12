"""OPC UA 数据绑定 + 把 7 个页面挂进场景卡片。

设计要点
--------
* **一个客户端、一份订阅**：7 页共约 360 个点共用 ``OpcUaManager`` 的一条
  Subscription，服务端变化才推；断线重连由通信层负责，页面不用管线程。
* **订阅清单靠探针收集**：控件工厂是惰性调用的（承载层切到 Run 才建），
  挂载时页面实例可能一个都还没有。这里临时构造 7 个不显示的页面读出各自
  ``keys()``，删掉探针后拿到的清单就是完整订阅表。
* **工厂可被调用多次**：承载层重建控件时会再调工厂创建新页面。新实例用
  :meth:`HmiPage.replay` 重灌已经收到的值；旧实例被 Qt 销毁后，分发时按
  C++ 对象是否还有效自动清掉引用，避免 RuntimeError。
* **写入只走已验证节点**：推断出来的 ``GVL.*`` 候选一律拒写，避免在现场
  发一个 BadNodeIdUnknown 还以为命令下去了。
* **只刷新最前面两页**：``set_active_cards()`` 由窗口的
  ``front_page_changed`` 驱动。值仍全量缓存（切页可立刻重灌），但控件重绘
  与初始订阅只覆盖这两页；后台页不滚动、不追加日志。放大后掉帧的主因是
  363 个点 × 7 个控件树的重复重绘，不是网络推送。
* **卡片尺寸跟着页面走**：挂载后统一用 ``widget_element.fit_widget_size``
  把卡片校正到「正好容纳 ``page_size`` 像素的页面控件」，不再依赖场景 JSON
  里写死的宽高（见 :data:`PAGE_PIXEL_SIZE`）。

接入 ``PopPickWindow``（V2 已接好，见 ``pop_pick_runtime.install_hmi``）::

    from App_PopPick_V2.hmi import attach_hmi_pages
    self._hmi = attach_hmi_pages(
        stage.pages_manager,            # 只暴露 widget 卡片的旧 SceneManager 门面
        parent=self,
        static_policy=page_snapshots,   # 后台页位图交给业务侧策略
        auto_start=False,               # 先确定最前面两页再 start()
    )
    self._hmi.set_active_cards(window.front_pages())
    self._hmi.start()

并在关窗流程里调 ``self._hmi.shutdown()``（``PopPickRuntime.release`` 已包含）。
原本的 ``Page0_Model / Page1_Model / Page3_Model`` 会往 Page0/1/3 上设置
自己的控件工厂，二者只能留一个。
"""

from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtCore import QObject, QSize, QSizeF, QTimer, Signal
from PySide6.QtWidgets import QWidget

from common.com.opcua import OpcConfig, OpcUaManager, keep_alive_until_stopped

from .pages import HmiPage, make_page_specs
from .tag_catalog import TagCatalog, clean_text, format_value

#: 页面控件在屏幕上的设计尺寸（像素，``scale=1.0``）。
#:
#: 7 张卡片统一按这一个口径落到场景里：挂载完页面后调用
#: ``widget_element.fit_widget_size`` 把卡片的场景尺寸校正成「正好容纳这么大
#: 的控件」。页面内部是按 :data:`App_PopPick.hmi.widgets.PAGE_SIZE` 排的
#: **750×1000 竖版**，控件必须正好这么大，``ScrollBody`` 才会 1:1 呈现
#: （给 1000×750 会算成缩放 0.79，整页发虚）。
#:
#: 卡片中心 / 角度 / Z 值都不动（见 :meth:`HmiPagesHost._fit_card`），所以
#: 扇形位姿、槽位判定和 ``PageDeck`` 的动画全不受影响。AGV 90° 映射下
#: 750×1000 的控件对应 **1000×750** 的场景矩形（宽高互换）。
PAGE_PIXEL_SIZE = QSize(750, 1000)


def _as_pixel_size(value: Any) -> QSize | None:
    """归一化「页面像素尺寸」参数：``None`` / QSize / ``(w, h)`` / 有宽高的对象。"""
    if value is None:
        return None
    if isinstance(value, QSize):
        return QSize(value)
    if isinstance(value, (tuple, list)):
        if len(value) != 2:
            raise ValueError("页面尺寸需要 (width, height)")
        return QSize(int(value[0]), int(value[1]))
    if hasattr(value, "width") and hasattr(value, "height"):
        return QSize(int(value.width()), int(value.height()))
    raise TypeError("页面尺寸需要 QSize / (width, height) / None")


class HmiClient(QObject):
    """``OpcUaManager`` 的页面侧包装：把节点变化转成业务 key 的信号。"""

    tag_changed = Signal(str, object)
    connection_changed = Signal(bool)
    message = Signal(str, str)

    def __init__(self, catalog: TagCatalog, *, endpoint: str = "",
                 user: str = "", password: str = "",
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.endpoint = endpoint or catalog.endpoint
        self._mgr = OpcUaManager(
            OpcConfig(endpoint=self.endpoint, user=user, password=password),
            parent=self,
        )
        self._mgr.node_changed.connect(self.tag_changed)
        self._mgr.connected_changed.connect(self.connection_changed)
        self._mgr.state_message.connect(lambda text: self.message.emit(text, "info"))
        self._mgr.node_error.connect(
            lambda key, text: self.message.emit(f"{key}: {text}", "err")
        )
        self._subscribed: set[str] = set()

    def start(self, keys: Iterable[str]) -> None:
        items = self.catalog.subscribe_items(keys)
        self._subscribed.update(items)
        self.message.emit(f"订阅 {len(items)} 个点（端点 {clean_text(self.endpoint)}）", "info")
        self._mgr.subscribe(items)
        self._mgr.start()

    def subscribe_more(self, keys: Iterable[str]) -> int:
        """页面切到最前面时增量补订阅；已订阅的点不重复下发。

        只加不删：`OpcUaManager` 没有单键退订接口，重建整条 Subscription
        会在切页时丢数据。切过的页会留在订阅表里，但界面重绘仍然只发生
        在当前最前面两页（真正导致卡顿的是控件重绘，不是网络推送）。
        """
        items = {k: v for k, v in self.catalog.subscribe_items(keys).items()
                 if k not in self._subscribed}
        if not items:
            return 0
        self._subscribed.update(items)
        self._mgr.subscribe(items)
        self.message.emit(f"追加订阅 {len(items)} 个点", "info")
        return len(items)

    def write(self, key: str, value: Any) -> bool:
        if key not in self.catalog.verified:
            self.message.emit(f"拒绝写入 {key}：节点未经浏览验证", "err")
            return False
        ok = self._mgr.write(self.catalog.node_id_of(key), value)
        level = "ok" if ok else "err"
        self.message.emit(
            f"写入 {key} = {format_value(value)} → {'成功' if ok else '失败'}", level
        )
        return ok

    def read(self, key: str) -> Any:
        if key not in self.catalog.verified:
            return None
        return self._mgr.read(self.catalog.node_id_of(key))

    def stop(self) -> None:
        if not self._mgr.stop(wait_ms=3000):
            # 线程没停住时绝不能让它随窗口销毁，worker 醒来 emit 会段错误
            keep_alive_until_stopped(self._mgr)


class HmiPagesHost(QObject):
    """持有客户端、页面实例和卡片工厂；对外只有 start / shutdown / report。"""

    #: 连接状态变化，窗口工具栏/状态栏可以只接这一条（内部已分发给各页面）
    connection_changed = Signal(bool)

    def __init__(self, scene_manager, *, mapping: dict[str, str] | None = None,
                 catalog: TagCatalog | None = None, endpoint: str = "",
                 user: str = "", password: str = "", demo: bool = False,
                 active_only: bool = True, flush_ms: int = 100,
                 static_background: bool = True,
                 page_size: Any = PAGE_PIXEL_SIZE,
                 static_policy: Any = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.catalog = catalog or TagCatalog()
        self._scene = scene_manager
        self._mapping = mapping or {}
        self._demo = bool(demo)
        self.active_only = bool(active_only)
        self._specs = make_page_specs()
        self._pages: dict[str, list[HmiPage]] = {}
        self._values: dict[str, Any] = {}
        # 客户端事件缓存：后台页不追加日志，切到前台时补最近若干条
        self._messages: list[tuple[str, str]] = []
        self._missing: list[tuple[str, str]] = []
        self._connected = False
        self._started = False
        # 空集合 = 尚未设置，「全量刷新」；set_active_cards() 之后只刷新前两页
        self._active_page_ids: set[str] = set()
        #: 后台页改用位图快照渲染（见 :meth:`apply_static_pages`）
        self.static_background = bool(static_background)
        #: 位图顶替的承接方。给一个带 ``set_static`` / ``is_static`` 的策略
        #: （App_PopPick_V2 传 ``PageSnapshots``）时走业务侧实现；不给就退回
        #: 图元自带的 ``set_motion_cache`` 兼容钩子。
        self._static_policy = static_policy
        #: 页面控件的目标像素尺寸；``None`` 表示不校正卡片（沿用场景 JSON）
        self.page_pixel_size = _as_pixel_size(page_size)
        self._card_to_page: dict[str, str] = {
            self.card_of(spec.page_id): spec.page_id for spec in self._specs
        }
        self.endpoint = endpoint or self.catalog.endpoint
        self._client: HmiClient | None = None
        if not demo:
            self._client = HmiClient(self.catalog, endpoint=endpoint,
                                     user=user, password=password, parent=self)
            self._client.tag_changed.connect(self._on_tag)
            self._client.connection_changed.connect(self._on_connection)
            self._client.message.connect(self._on_message)

        # 推送合流：PLC 逐点到达的值先进这里，由一条定时器每 flush_ms
        # 统一灌进控件。页面控件被 QGraphicsProxyWidget 接管后，**改一个
        # 标签就要重画整张页面**，逐点直刷会变成「每来一个点重画一页」。
        self._pending: dict[str, Any] = {}
        self._flush_ms = max(16, int(flush_ms))
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(self._flush_ms)
        self._flush_timer.timeout.connect(self._flush)

        # 时钟只驱动「最前面那一页」：7 个页面各自 1s 定时器时，每秒会有
        # 7 次整页重绘，实测能把事件循环拖到每秒 2 轮（见 profile_hmi.py）。
        self._clock_page_ids: set[str] = set()
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)

        self._page_keys = self._collect_keys()
        self.subscribe_keys = sorted({k for keys in self._page_keys.values()
                                      for k in keys})
        self._install()

    # ------------------------------------------------------------------
    # 订阅清单 / 挂载
    # ------------------------------------------------------------------
    def _collect_keys(self) -> dict[str, list[str]]:
        """``{页面 id: 该页订阅的业务 key}``；探针页面只用来读清单。"""
        per_page: dict[str, list[str]] = {}
        for spec in self._specs:
            probe = spec.factory(self.catalog)
            per_page[spec.page_id] = probe.keys()
            probe.shutdown()
            probe.deleteLater()
        return per_page

    def active_keys(self) -> list[str]:
        """当前最前面两页的订阅点；没设置过活跃页时返回全表。"""
        targets = self._active_page_ids or set(self._page_keys)
        return sorted({k for pid in targets for k in self._page_keys.get(pid, ())})

    def set_active_cards(self, cards) -> None:
        """由 ``PopPickWindow.front_page_changed`` 驱动：只刷新最前面两页。

        卡片名 → 页面 id；新进入的页面立刻用缓存值重灌，并增量补订阅，
        避免切过去时先看到一屏 ``--``。
        """
        names = [name for name in cards if name]
        ids = {self._card_to_page.get(name) for name in names}
        ids.discard(None)
        if not ids:
            return
        # 时钟只服务槽位那一页：每多驱动一页，就多一次整页重绘/秒
        first = self._card_to_page.get(names[0]) if names else None
        self._clock_page_ids = {first} if first else set()
        self._tick_clock()
        entering = ids - self._active_page_ids
        self._active_page_ids = ids
        # 先把「谁实时、谁快照」定下来，再做重灌：重灌要改标签，若此时
        # 还在快照态，改的是隐藏的控件，画面不会更新。
        self.apply_static_pages()
        for page_id in entering:
            for page in self._pages.get(page_id, ()):
                page.replay(self._values)
                self._replay_messages(page)
            if self._client is not None and self._started:
                self._client.subscribe_more(self._page_keys.get(page_id, ()))

    def apply_static_pages(self) -> None:
        """把**非活跃页**切成位图快照，只让最前面两页保持真实控件。

        为什么
        ------
        ``QGraphicsProxyWidget`` 里每张卡都要整页重渲染，窗口一脏同一区域下
        **所有** proxy 都会被重画。实测 7 页全实时时，一次刷新要重渲 6 个页面
        （每页 6ms 上下），10Hz 刷新就是 36ms/拍、单核 65%。后台页本来就不刷新
        数据，把它们烘成位图后同样一次刷新只剩 2 个页面，CPU 降到 14%，画面
        像素差 0.3/765（肉眼无差）。

        谁来顶替
        --------
        传了 ``static_policy`` 时交给它（App_PopPick_V2 是
        :class:`~App_PopPick_V2.page_snapshots.PageSnapshots`：位图由业务侧
        统一管理，动画窗口 / 长期意图两本账分开记）。没传则退回图元自带的
        ``set_motion_cache`` 兼容钩子——那是统一运行态模板里的**空实现**，
        只记账不切位图，等价于"不做静态化"。
        """
        if not self.static_background or not self._active_page_ids:
            return                      # 还没确定活跃页时别把所有页冻住
        changed = False
        policy = self._static_policy
        for spec in self._specs:
            card = self._scene.findItemByName(self.card_of(spec.page_id))
            if card is None:
                continue
            want = spec.page_id not in self._active_page_ids
            if policy is not None:
                try:
                    if policy.is_static(card) == want:
                        continue
                    changed = policy.set_static(card, want) or changed
                except RuntimeError:    # 卡片已被销毁（重建场景）
                    continue
                continue
            setter = getattr(card, "set_motion_cache", None)
            if not callable(setter):
                continue
            probe = getattr(card, "is_motion_cache", None)
            if callable(probe):
                try:
                    if bool(probe()) == want:
                        continue
                except RuntimeError:    # 卡片已被销毁（重建场景）
                    continue
            try:
                setter(want)
            except RuntimeError:
                continue
            changed = True
        if changed:
            # 位图替换 proxy 之后承载层要按新状态重新对位：**不补这一次**，
            # 交换完成时切到前台的那张卡会停在原地，画面上就是"换了页但内容
            # 还是另一页"（实测 axis 的那张留在槽位上）。
            scene = getattr(self._scene, "m_scene", None)
            sync = getattr(scene, "_sync_embedded_widgets_geometry", None)
            if callable(sync):
                sync()

    def _replay_messages(self, page: HmiPage) -> None:
        for text, level in self._messages[-50:]:
            page.on_client_message(text, level)

    def _make_factory(self, spec):
        def factory(host: QWidget) -> QWidget:
            page = spec.factory(self.catalog, parent=host)
            self._pages.setdefault(spec.page_id, []).append(page)
            page.write_requested.connect(self._on_write)
            page.set_connection(self._connected, self.endpoint)
            if spec.page_id in self._clock_page_ids:
                page.header.tick_clock()
            if self._demo:
                page.seed_demo()
            else:
                page.replay(self._values)
            self._replay_messages(page)
            self._on_message(f"页面「{spec.title}」已挂载到卡片 {self.card_of(spec.page_id)}", "ok")
            return page
        return factory

    def card_of(self, page_id: str) -> str:
        spec = next((s for s in self._specs if s.page_id == page_id), None)
        base = spec.card if spec else page_id
        return self._mapping.get(page_id, base)

    def _install(self) -> None:
        for spec in self._specs:
            name = self.card_of(spec.page_id)
            card = self._scene.findItemByName(name)
            if card is None or not hasattr(card, "set_widget_factory"):
                self._missing.append((spec.page_id, name))
                continue
            # 必须在场景切到 Run 之后设置；承载层若已存在会立即重建控件
            card.set_widget_factory(self._make_factory(spec))
            # 控件建好后按页面像素尺寸校正卡片：场景 JSON 里写的是 3000×4000
            # （旧的 6 卡快照是 4000×3000），靠这一步统一到同一观感。
            self._fit_card(card)

    def _fit_card(self, card) -> None:
        """把卡片场景尺寸校正成「正好容纳 :attr:`page_pixel_size` 的控件」。

        用 ``widget_element.fit_widget_size`` 做换算（AGV 90° 映射下控件宽对应
        场景高），只改尺寸，**不动位姿**：``change_size`` 是绕旋转中心缩放的，
        卡片的 ``m_origin`` 可能是扇形支点而不是包围盒中心，缩放后中心会漂；
        这里记下缩放前的场景中心，再把中心推回去，``PageDeck`` 读到的
        center/angle/Z 与设计文件一致，扇形和槽位判定都不受影响。
        """
        size = self.page_pixel_size
        if size is None or size.isEmpty():
            return
        fitter = getattr(card, "fit_widget_size", None)
        if not callable(fitter):
            return                      # 普通矩形卡片（不是 widget 图元）不碰
        try:
            before = QSizeF(card.getSize())
            center = card.get_scene_center_pos()
            fitter(size)
            after = QSizeF(card.getSize())
            shift = center - card.get_scene_center_pos()
            if abs(shift.x()) > 0.5 or abs(shift.y()) > 0.5:
                # setPos 对 widget_element 会顺带同步承载控件的几何
                card.setPos(card.pos() + shift)
            name = card.get_name()
        except RuntimeError:
            # 卡片 / 承载视图在关窗流程里被 C++ 侧提前销毁
            return
        if (abs(before.width() - after.width()) < 1.0
                and abs(before.height() - after.height()) < 1.0):
            return
        self._on_message(
            f"卡片 {name} 尺寸 {before.width():.0f}×{before.height():.0f}"
            f" → {after.width():.0f}×{after.height():.0f}"
            f"（适配 {size.width()}×{size.height()} 像素控件）", "info")

    def refit_cards(self) -> None:
        """按 :attr:`page_pixel_size` 重新校正所有卡片尺寸。

        ``_install()`` 已经调过一次；场景被重新反序列化（卡片按 JSON 重建、
        尺寸回到写死值）或运行时改了 ``page_pixel_size`` 之后需要再调一次。
        """
        for spec in self._specs:
            card = self._scene.findItemByName(self.card_of(spec.page_id))
            if card is not None:
                self._fit_card(card)

    # ------------------------------------------------------------------
    # 运行
    # ------------------------------------------------------------------
    def start(self, keys: Iterable[str] | None = None) -> None:
        """启动订阅；``demo=True`` 时改为灌模拟数据，不连 PLC。

        ``active_only`` 且已设置活跃页时，初始只订阅最前面两页的点；
        切页时由 :meth:`set_active_cards` 增量补订阅。
        """
        if self._demo:
            # 模拟数据只灌一次，没有持续重绘开销，7 页都灌满方便离线查看
            for page in self._iter_pages():
                page.seed_demo()
            self._on_message("离线演示模式：数据为模拟值，未连接 PLC", "warn")
            self._started = True
            self._clock_timer.start()
            return
        if self._client is not None:
            targets = (list(keys) if keys is not None
                       else (self.active_keys() if self.active_only
                             else self.subscribe_keys))
            self._client.start(targets)
            self._started = True
        self._clock_timer.start()

    def shutdown(self) -> None:
        """关窗必须调：停后台线程、停页面时钟。"""
        self._flush_timer.stop()
        self._clock_timer.stop()
        self._pending.clear()
        if self._client is not None:
            self._client.stop()
            self._client = None
        for page in self._iter_pages():
            page.shutdown()

    def write(self, key: str, value: Any) -> bool:
        if self._client is None:
            self._on_message(f"离线模式下不写入 PLC（{key}）", "warn")
            return False
        return self._client.write(key, value)

    # ------------------------------------------------------------------
    # 信号分发
    # ------------------------------------------------------------------
    def _iter_pages(self):
        """跳过已被 Qt 销毁的页面实例（承载层重建控件时会出现）。"""
        for page_id, pages in list(self._pages.items()):
            alive = []
            for page in pages:
                try:
                    page.objectName()
                    alive.append(page)
                except RuntimeError:
                    continue
            self._pages[page_id] = alive
            yield from alive

    def _on_tag(self, key: str, value: Any) -> None:
        # 先入缓存（切页重灌用），再把重绘合流到下一拍。PLC 逐点推送时
        # 「每来一个点重画一整页」是放大后卡顿的主因之一。
        self._values[key] = value
        self._pending[key] = value
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush(self) -> None:
        """把这一拍收到的值一次性灌进活跃页。

        一批值在同一轮事件循环里改完，Qt 只会合并出一次整页重绘；
        逐点直刷则是每点一次。
        """
        batch = self._pending
        self._pending = {}
        if not batch:
            return
        targets = self._active_page_ids if self.active_only else set()
        for page in self._iter_pages():
            if targets and page.PAGE_ID not in targets:
                continue
            sinks = page._sinks
            for key, value in batch.items():
                if key in sinks:
                    page.on_tag(key, value)

    def flush_now(self) -> None:
        """立刻把待刷值灌进去（测试 / 截图前用）。"""
        self._flush_timer.stop()
        self._flush()

    def _tick_clock(self) -> None:
        """只刷新槽位页的页头时间。"""
        if not self._clock_page_ids:
            return
        for page in self._iter_pages():
            if page.PAGE_ID in self._clock_page_ids:
                page.header.tick_clock()

    def _on_connection(self, connected: bool) -> None:
        self._connected = connected
        self.connection_changed.emit(connected)
        for page in self._iter_pages():
            page.set_connection(connected, self.endpoint)

    def _on_message(self, text: str, level: str = "info") -> None:
        self._messages.append((text, level))
        if len(self._messages) > 200:
            del self._messages[:-200]
        targets = self._active_page_ids if self.active_only else set()
        for page in self._iter_pages():
            if targets and page.PAGE_ID not in targets:
                continue
            page.on_client_message(text, level)

    def _on_write(self, key: str, value: Any) -> None:
        self.write(key, value)

    # ------------------------------------------------------------------
    # 诊断
    # ------------------------------------------------------------------
    def report(self) -> str:
        size = self.page_pixel_size
        size_line = ("页面尺寸: 未校正（沿用场景 JSON）" if size is None
                     else f"页面尺寸: {size.width()}×{size.height()} 像素（卡片按此校正）")
        lines = [
            f"端点: {self.endpoint}",
            f"页面: {len(self._specs)} 个，全表订阅点: {len(self.subscribe_keys)} 个",
            f"已挂载卡片: {len(self._specs) - len(self._missing)}/{len(self._specs)}",
            f"刷新范围: {'最前面两页 ' + ', '.join(sorted(self._active_page_ids)) if self._active_page_ids else '全部页面（尚未设置活跃页）'}"
            f"｜当前订阅 {len(self.active_keys()) if self.active_only else len(self.subscribe_keys)} 点",
            size_line,
        ]
        if self._missing:
            lines.append("未挂载: " + "、".join(
                f"{pid}→{card}（场景里没有这张卡片）" for pid, card in self._missing
            ))
            lines.append("提示: 运行 tools/gen_hmi_scene.py 生成带第 7 张卡片的场景，"
                         "或用 mapping 把页面指到已有卡片")
        pending = sorted({line for page in self._iter_pages()
                          for line in page.pending_report()})
        if pending:
            lines.append(f"待接入点（推断节点，未订阅/不写入）: {len(pending)} 个")
        return "\n".join(lines)


def attach_hmi_pages(scene_manager, *, parent: QObject | None = None,
                     mapping: dict[str, str] | None = None,
                     catalog: TagCatalog | None = None, endpoint: str = "",
                     user: str = "", password: str = "", demo: bool = False,
                     active_only: bool = True, flush_ms: int = 100,
                     static_background: bool = True,
                     page_size: Any = PAGE_PIXEL_SIZE,
                     static_policy: Any = None,
                     auto_start: bool = True) -> HmiPagesHost:
    """把 7 个页面挂到场景卡片上，返回宿主对象（窗口要自己持有引用）。

    只刷新前两页时建议 ``auto_start=False``：先
    ``host.set_active_cards(window.front_pages())`` 再 ``host.start()``，
    初始订阅就只覆盖这两页。

    ``page_size`` 是页面控件在屏幕上的目标像素尺寸（默认
    :data:`PAGE_PIXEL_SIZE` = 750×1000，与页面设计尺寸一致）。挂载时用
    ``widget_element.fit_widget_size`` 把卡片场景尺寸校正成正好容纳这个尺寸，
    所以场景 JSON 里写多少（当前快照是 3000×4000）都会被拉回同一套观感；
    传 ``None`` 则不校正、完全沿用场景文件。

    ``flush_ms`` 是数值刷新的合流间隔：PLC 推送先攒起来，每 ``flush_ms``
    毫秒统一灌进控件一次（默认 100ms = 10Hz）。页面控件在
    ``QGraphicsProxyWidget`` 里，改一个标签就要重画整页，所以宁可牺牲
    一点刷新率，也不要一格点一次重绘。

    ``static_background`` 让后台页改用位图快照（见
    :meth:`HmiPagesHost.apply_static_pages`）：一次刷新从 6 页降到 2 页，
    实测单核占用 65% → 14%。卡片进入最前面两页时自动恢复真实控件；
    ``static_policy`` 决定位图由谁管理（不传则不做静态化）。
    """
    host = HmiPagesHost(
        scene_manager, parent=parent, mapping=mapping, catalog=catalog,
        endpoint=endpoint, user=user, password=password, demo=demo,
        active_only=active_only, flush_ms=flush_ms,
        static_background=static_background, page_size=page_size,
        static_policy=static_policy,
    )
    if auto_start:
        host.start()
    return host
