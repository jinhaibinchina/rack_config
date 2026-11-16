"""后台页 / 动画期的**位图顶替层**：PopPick 唯一的渲染优化。

为什么需要它
============
7 张卡片承载的都是 750×1000 的真实 HMI 页面（``QGraphicsProxyWidget``）。
一次重绘里，同一可见区域下的**每张** proxy 都要把整页控件从头渲染一遍：

* 动画期：卡片一带旋转，``QGraphicsProxyWidget::paint`` 立刻整页重渲。
  实测单卡 ~14ms，7 卡一帧 100ms —— 520ms 的交换动画只剩 9 帧。
* 静态期：PLC 10Hz 刷新时后台 5 页也在跟着重画（它们根本没变），
  单核 65% 里有一大半花在这上面。

对策与旧 ``qgraphics_runtime.RuntimeWidgetLayer`` 完全一致：把控件
``grab()`` 成位图，用一张 ``QGraphicsPixmapItem`` 顶替它显示；控件与 proxy
同时隐藏，不再产生绘制。

与框架的分工
============
``DesignerV2/CoreQGraphics/runtime`` 的 :class:`~.widgets.WidgetHost` 只管
「造控件 / 对齐 proxy / 回收」，**不含位图缓存**（见设计文档 §9「未覆盖能力」）。
本模块就是文档里说的业务侧 ``SnapshotPolicy``：它不碰 proxy 的位姿计算，
只读 proxy 已经落好的 ``pos / rotation / zValue`` 再抄给位图，因此
几何口径只有一个来源（``WidgetHost.align``），不会出现两套算法打架。

三本账（必须分开记，否则必定错乱）
==================================
===============  ==========================================================
``_animating``   PageDeck 的动画窗口。窗口内**全部**卡片位图化：脏区会盖住
                 旁边的堆叠卡，留一张真实控件就得多渲染一整页。
``_static``      **长期意图**：哪些卡平时就该是位图（后台页）。只有槽位上的
                 两张前台页是实时控件。动画窗口内不得改写它——早期实现用
                 「动画前的分布」当恢复依据，结果动画结束后的
                 ``apply_static_pages`` 被旧分布覆盖，槽位大卡永久停在陈旧
                 位图上，画面看起来就是「换页了但内容还是另一页」。
``_items``       实际存在的那张位图（惰性生成，就地更新，item 只建一次）。
===============  ==========================================================

``_showing(iid)`` = 「长期意图或动画窗口」**且**位图确实有像素，是
「这一张现在由谁显示」的唯一真值。烘不出图就老实显示真实控件，绝不留一张
空白位图。

位姿跟随
========
动画每帧会改卡片的中心 / 角度 / Z，位图必须同帧跟上，否则画面会看到
「内容领先轮廓」的重影。跟随点只有 :meth:`follow`：PageDeck 每帧对动到的那
两张卡各调一次（见 ``page_deck.PageDeck._apply_pose``），其余时刻由
``set_animating`` / ``set_static`` 收尾各调一次。**不做**定时轮询，也不
监听场景信号——位姿变化的唯一源头是 deck，跟着它就够了。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QPointF, Qt, QTimer
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QWidget

from . import pop_pick_config as cfg


def _enum(enum_name: str):
    """取 ``QGraphicsItem.<flag>``，兼容 ``GraphicsItemFlag`` 命名空间形式。"""
    flags = getattr(QGraphicsItem, "GraphicsItemFlag", None)
    if flags is not None and hasattr(flags, enum_name):
        return getattr(flags, enum_name)
    return getattr(QGraphicsItem, enum_name)


try:
    _ITEM_SELECTABLE = _enum("ItemIsSelectable")
    _ITEM_MOVABLE = _enum("ItemIsMovable")
    _SMOOTH = Qt.TransformationMode.SmoothTransformation
except AttributeError:  # pragma: no cover - 旧式枚举别名
    _ITEM_SELECTABLE = QGraphicsItem.ItemIsSelectable
    _ITEM_MOVABLE = QGraphicsItem.ItemIsMovable
    _SMOOTH = Qt.SmoothTransformation


class PageSnapshots(QObject):
    """把 widget 图元的真实控件烘成位图并在需要时顶替它。

    :param stage: :class:`DesignerV2.CoreQGraphics.runtime.RuntimeStage`；
    :param enabled: ``False`` 时所有方法退化为空操作（等价于关闭优化）。
    """

    def __init__(self, stage, parent: Optional[QObject] = None, *,
                 enabled: bool = cfg.SNAPSHOT_ENABLED) -> None:
        super().__init__(parent or stage)
        self._stage = stage
        self._host = stage.widgets
        self._scene = stage.scene
        self._enabled = bool(enabled)

        self._items: dict[int, QGraphicsPixmapItem] = {}
        #: 长期意图：这一张平时是不是位图（后台页）
        self._static: dict[int, bool] = {}
        #: PageDeck 的动画窗口
        self._animating = False
        #: 需要重烘、可等空闲再做的卡
        self._dirty: set[int] = set()
        self._dirty_timer: Optional[QTimer] = None
        self._prewarm_timer: Optional[QTimer] = None
        self._released = False

        # 换页会连 proxy 一起重建：旧位图必须跟着丢，否则会留下上一页的内容。
        sig = getattr(stage, "pageAboutToLoad", None)
        if sig is not None:
            sig.connect(self.clear)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def enabled(self) -> bool:
        return self._enabled

    def animating(self) -> bool:
        return self._animating

    def snapshot_count(self) -> int:
        return len(self._items)

    def static_ids(self) -> list[int]:
        return [iid for iid, on in self._static.items() if on]

    def _cards(self) -> list:
        """当前页面里挂了真实控件的**页面卡片**（背景除外）。

        「背景」也是 widget 图元，但它的尺寸由 ``BackgroundFitter`` 随视口
        实时改写：烘成位图后窗口一缩放，位图还是旧分辨率，边缘会露底；而且
        水墨是逐帧动画，位图会把鱼冻住。所以它永远留在真实控件上，既不进
        ``_static`` 也不进动画期的位图集合。
        """
        return [e for e in self._stage.registry.widgets()
                if self._host.proxy_of(e.item_id) is not None
                and e.get_name() != cfg.BACKGROUND_NAME]

    def _showing(self, iid: int) -> bool:
        """这一张现在是不是由位图显示（唯一真值）。"""
        if not (self._animating or self._static.get(iid)):
            return False
        item = self._items.get(iid)
        return item is not None and not item.pixmap().isNull()

    def suppresses_full_repaint(self) -> bool:
        """动画期由 ``follow`` 精确跟位，整窗 ``update()`` 可以省掉。

        PageDeck 每帧末尾都会 ``scene.update()``；旧 Core 里 scene 是 QWidget，
        那是局部重绘；换成 ``QGraphicsView`` 之后等于「整个视口重画一遍」。
        动画期全部是位图，省掉它每帧能少一次全窗合成。
        """
        return self._animating

    def is_static(self, element) -> bool:
        return bool(self._static.get(getattr(element, "item_id", -1), False))

    # ------------------------------------------------------------------
    # 开关
    # ------------------------------------------------------------------
    def set_animating(self, active: bool) -> None:
        """PageDeck 的动画窗口开关。

        进入：7 张全切成位图（已有位图直接复用，缺的才烘）。
        退出：按**退出这一刻**的长期意图还原——不是「动画前」的分布。
        """
        active = bool(active)
        if not self._enabled or active == self._animating:
            return
        self._animating = active
        for element in self._cards():
            iid = element.item_id
            want = active or bool(self._static.get(iid))
            if want and iid not in self._items and self._rebuild(element) is None:
                continue      # 烘不出图就老实显示真实控件
            if want and iid not in self._items:
                continue
            self.follow(element)

    def set_static(self, element, active: bool) -> bool:
        """长期意图：这张卡平时是否用位图（``HmiPagesHost`` 的后台页）。"""
        iid = getattr(element, "item_id", None)
        if iid is None:
            return False
        active = bool(active)
        changed = self._static.get(iid, False) != active
        self._static[iid] = active
        if not self._enabled or self._host.proxy_of(iid) is None:
            return changed
        if active and iid not in self._items:
            self._rebuild(element)
            # 首次烘图时控件可能还没走完首次布局（启动时就是这个时机），
            # 抓出来会是一张白图；先显示着，空闲时补一版真的。
            self._mark_dirty(iid)
        elif not active:
            # 实时卡自己的备用位图也顺手追平：下次动画要拿它顶上，
            # 不追就会在动画里闪一下几分钟前的旧数值。
            self._mark_dirty(iid)
        self.follow(element)
        return changed

    # ------------------------------------------------------------------
    # 位姿跟随
    # ------------------------------------------------------------------
    def follow(self, element) -> None:
        """把位图的位姿 / 显隐抄成 proxy 的当前值。

        调用点只有三个（deck 每帧、两个开关收尾），开销是几个 setPos，
        比"检测位姿变了没"再省一次查询还便宜，所以不做去重。
        """
        iid = getattr(element, "item_id", None)
        if iid is None:
            return
        proxy = self._host.proxy_of(iid)
        if proxy is None:
            return
        visible = bool(getattr(element, "effective_visibility",
                               element.get_visibility)())
        item = self._items.get(iid)
        showing = self._showing(iid)
        if item is not None:
            item.setPos(proxy.pos())
            item.setRotation(proxy.rotation())
            item.setZValue(proxy.zValue())
            item.setVisible(showing and visible)
        # 顶替期间 proxy 必须彻底不画，否则位图和控件双画，画面会「重影」。
        proxy.setVisible(visible and not showing)

    # ------------------------------------------------------------------
    # 位图生成
    # ------------------------------------------------------------------
    def _rebuild(self, element) -> Optional[QGraphicsPixmapItem]:
        """把控件当前画面烘到位图上（就地更新，item 只建一次）。"""
        if not self._enabled or self._released:
            return None
        iid = getattr(element, "item_id", None)
        if iid is None:
            return None
        proxy = self._host.proxy_of(iid)
        widget: Optional[QWidget] = proxy.widget() if proxy is not None else None
        if widget is None:
            return None
        pixmap = widget.grab()
        if pixmap.isNull():
            return None
        pixmap = self._fit_to_view(pixmap)
        item = self._items.get(iid)
        if item is None:
            item = QGraphicsPixmapItem()
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            item.setFlag(_ITEM_SELECTABLE, False)
            item.setFlag(_ITEM_MOVABLE, False)
            item.setTransformationMode(_SMOOTH)
            self._scene.addItem(item)
            self._items[iid] = item
        item.setPixmap(pixmap)
        # 位图局部原点是左上角；proxy 绕自身中心转，位图也得把支点挪到中心，
        # 否则旋转帧会看到位图绕着左上角甩。
        dpr = float(pixmap.devicePixelRatio() or 1.0)
        item.setTransformOriginPoint(
            QPointF(pixmap.width() / dpr / 2.0, pixmap.height() / dpr / 2.0))
        if not self._showing(iid):
            item.setVisible(False)     # 预热出来的只是备用图
        return item

    def _fit_to_view(self, pixmap):
        """按「动画期实际显示的物理像素」缩位图，省掉每帧一次大图降采样。

        ``grab()`` 回来的是 750×1000×DPR；卡片在屏幕上只占
        ``750 × 视图缩放 × DPR`` 个设备像素。按 1:1 存会让每帧都做一次
        大图缩放（~15ms），按显示尺寸存基本是 1:1 贴图。
        """
        dpr = float(pixmap.devicePixelRatio() or 1.0)
        logical_w = pixmap.width() / dpr
        scale = self._display_scale()
        if not (0.05 < scale < 0.999) or logical_w <= 1.0:
            return pixmap                      # 放大显示时保持原图
        target = max(16, int(round(logical_w * scale)))
        if target >= pixmap.width():
            return pixmap
        scaled = pixmap.scaledToWidth(target, _SMOOTH)
        # 逻辑尺寸必须还是控件原尺寸：QGraphicsPixmapItem 用 size/DPR 当
        # boundingRect，反算 DPR 就等于「物理宽 / 逻辑宽」。
        scaled.setDevicePixelRatio(target / logical_w)
        return scaled

    def _display_scale(self) -> float:
        view = self._stage.view
        scale = float(view.transform().m11() or 0.0)
        if scale <= 0.0:
            return 1.0
        try:
            return scale * float(view.devicePixelRatioF() or 1.0)
        except (AttributeError, RuntimeError):
            return scale

    def _needs_rescale(self, iid: int) -> bool:
        item = self._items.get(iid)
        if item is None:
            return True
        pixmap = item.pixmap()
        if pixmap.isNull():
            return True
        dpr = float(pixmap.devicePixelRatio() or 1.0)
        logical_w = pixmap.width() / dpr
        scale = self._display_scale()
        if not (0.05 < scale < 0.999):
            return False
        expected = logical_w * scale
        if expected <= 1.0 or pixmap.width() <= 1:
            return False
        return abs(pixmap.width() - expected) / expected > cfg.SNAPSHOT_RESCALE_TOLERANCE

    # ------------------------------------------------------------------
    # 预热 / 补烘
    # ------------------------------------------------------------------
    def schedule_prewarm(self, delay_ms: Optional[int] = None) -> None:
        """视图变换稳定后再预热（fit 之前烘出来的是 1:1 大图，白费）。"""
        if not self._enabled or self._released:
            return
        delay = cfg.SNAPSHOT_PREWARM_MS if delay_ms is None else int(delay_ms)
        if self._prewarm_timer is None:
            self._prewarm_timer = QTimer(self)
            self._prewarm_timer.setSingleShot(True)
            self._prewarm_timer.timeout.connect(self.prewarm)
        self._prewarm_timer.start(max(0, delay))

    def prewarm(self) -> None:
        """空闲时把缺的位图补齐、分辨率不对的标脏。

        前台两页是实时控件、没有位图，第一次点击才临时 grab 两张要 ~70ms，
        肉眼就是「点下去先愣一下」，所以这里必须提前烘。
        """
        if not self._enabled or self._released or self._animating:
            return
        for element in self._cards():
            iid = element.item_id
            if iid not in self._items:
                if self._rebuild(element) is not None:
                    self._mark_dirty(iid)   # 补一版布局完成后的真图
                self.follow(element)
            elif self._needs_rescale(iid):
                self._mark_dirty(iid)

    def _mark_dirty(self, iid: int) -> None:
        if not self._enabled or self._released:
            return
        self._dirty.add(int(iid))
        if self._dirty_timer is None:
            self._dirty_timer = QTimer(self)
            self._dirty_timer.setSingleShot(True)
            self._dirty_timer.timeout.connect(self._flush_dirty)
        self._dirty_timer.start(cfg.SNAPSHOT_REFRESH_MS)

    def _flush_dirty(self) -> None:
        """分片补烘：每次事件循环只做一小批，避免整段顿挫。"""
        if self._released:
            self._dirty.clear()
            return
        if self._animating:
            # 位图正在当画面用，挪不得；等这一轮动画结束再说
            if self._dirty:
                self._dirty_timer.start(cfg.SNAPSHOT_REFRESH_MS)
            return
        pending = sorted(self._dirty)
        done = 0
        while pending and done < cfg.SNAPSHOT_REFRESH_BATCH:
            iid = pending.pop(0)
            self._dirty.discard(iid)
            done += 1
            element = self._stage.registry.find(iid)
            if element is None or self._host.proxy_of(iid) is None:
                continue
            if iid not in self._items:
                if not self._static.get(iid):
                    continue        # 只是备用图，没建过就别建了
            self._rebuild(element)
            if self._showing(iid):
                self.follow(element)     # 位姿没变但内容变了，重落一遍上线
        if self._dirty:
            self._dirty_timer.start(cfg.SNAPSHOT_REFRESH_MS)

    # ------------------------------------------------------------------
    # 回收
    # ------------------------------------------------------------------
    def clear(self) -> None:
        """丢弃全部位图（换页时用，proxy 会被 ``WidgetHost.reset`` 一起重建）。"""
        self._dirty.clear()
        for iid in list(self._items):
            self._drop(iid)
        self._items.clear()
        self._static.clear()
        self._animating = False

    def _drop(self, iid: int) -> None:
        item = self._items.pop(int(iid), None)
        if item is None:
            return
        try:
            self._scene.removeItem(item)
        except RuntimeError:
            pass

    def release(self) -> None:
        """关窗：停定时器 + 删掉所有位图（可重复调用）。"""
        for timer in (self._dirty_timer, self._prewarm_timer):
            if timer is not None:
                timer.stop()
        self.clear()
        self._released = True

    def report(self) -> str:
        return (f"snapshots={len(self._items)} "
                f"static={len(self.static_ids())} "
                f"animating={self._animating} dirty={len(self._dirty)} "
                f"enabled={self._enabled}")
