"""App_PopPick 的 ``CoreQGraphics`` 运行态后端。

为什么需要这一层
================
``App_PopPick`` 原先跑在 ``Designer/Core`` 的自绘 ``QuadTreeScene`` 上：场景
本身是 QWidget，7 张页面卡片是 ``widget_element``，真实 HMI 页面由
``EmbeddedWidgetLayer``（每张卡一个透明 QGraphicsView 子窗口 + proxy）承载。
``Designer/CoreQGraphics`` 是标准 ``QGraphicsScene / QGraphicsView`` 的平行实现，
几何与 page JSON 完全等价（实测 7 张卡 ``page_bounding_rect()`` 与旧
``sceneBoundingRect()`` 逐位相同），但它的运行态只有「按 widgetType 造一个
QLineEdit/QTextEdit」的预览能力，挂不上 App_PopPick 的页面工厂。

本模块把新场景**补齐成运行态**，同时对上旧场景的 API 口径，于是
``page_deck.py`` / ``hmi/binding.py`` 一行都不用改：

* :class:`RuntimeWidgetLayer` —— 每张卡一个独立顶层 ``QGraphicsProxyWidget``，
  由外部 ``factory(host)`` 创建真实 QWidget。不注册进 ``SceneIndex``、不参与
  ``page_data()``，所以不影响设计器的对拍 / round-trip。proxy 不做图元 Qt 子项
  （会把 ``sceneBoundingRect`` 撑大），按图元可视中心 + 旋转 + view 尺寸手工对齐，
  与 ``GraphicsScene._sync_widget_proxies`` 的既定取舍一致。
* :class:`RuntimeCard` —— 把 ``WidgetItem`` 包成旧 ``widget_element`` 的接口
  （``get_scene_center_pos`` / ``set_angle`` / ``set_zValue`` / ``set_motion_cache``
  / ``set_widget_factory`` …）。位姿统一按「绝对角度 + 绝对中心」落地，绕开旧
  Core「绕支点转一段弧再补平移」的实现细节，净位姿与 PageDeck 的契约一致。
* :class:`RuntimeView` —— 继承 ``GraphicsView``，补出旧 ``QuadTreeScene`` 的
  运行态接口（运行模式、画布导航开关、按场景矩形取景、承载控件同步/回收）以及
  ``sceneToView`` / ``viewToScene``。
* :class:`RuntimeSceneManager` —— 补出旧 ``SceneManager`` 的
  ``m_sorted_items`` / ``findItemByName`` / ``m_scene``。

坐标口径（已用真实 JSON 对拍验证）
================================
旧场景 ``sceneToView`` == ``SceneProjection.point``（AGV 轴交换 + 双轴取反），
``viewToScene`` == ``inverse_point``；新场景的 ``QGraphicsScene`` 内部就是投影后
的「视图坐标」。因此：

* ``RuntimeCard.sceneBoundingRect()`` 返回 **page 坐标** AABB
  （``WidgetItem.page_bounding_rect()``，等价旧 ``base_element.sceneBoundingRect``）；
* ``RuntimeView.set_view_scene_rect()`` 收 page 矩形，投影成视图矩形后 ``fitInView``；
* 窗口像素 → page 坐标：``view.mapToScene()`` → ``projection.inverse_point()``；
* PageDeck 在「视图坐标」里做弧线插值，``sceneToView`` / ``viewToScene`` 严格互逆。

``CoreQGraphics`` 源码保持零改动：本模块只用它的公开类，不 monkey patch、不侵入
设计器行为，设计器的几何回归不受影响。

运行方式
========
``create_runtime_scene(parent)`` 返回 ``(view, manager)``；``view`` 就是可以直接
塞进 ``QMainWindow.setCentralWidget`` 的 QWidget。
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsProxyWidget,
    QGraphicsView,
    QWidget,
)

from Designer.CoreQGraphics import GraphicsScene, GraphicsView, SceneProjection

# PySide6/Qt6 的枚举既能写成 Qt.Foo 也能写成 Qt.Enum.Foo；两种发行版都兼容
try:
    _NO_BUTTONS = Qt.MouseButton.NoButton
    _ALL_BUTTONS = Qt.MouseButton.AllButtons
    _WA_TRANSPARENT = Qt.WidgetAttribute.WA_TransparentForMouseEvents
    _KEEP_RATIO = Qt.AspectRatioMode.KeepAspectRatio
except AttributeError:  # pragma: no cover - 兼容旧式枚举别名
    _NO_BUTTONS = Qt.NoButton
    _ALL_BUTTONS = Qt.AllButtons
    _WA_TRANSPARENT = Qt.WA_TransparentForMouseEvents
    _KEEP_RATIO = Qt.KeepAspectRatio

try:
    _NO_DRAG = QGraphicsView.DragMode.NoDrag
    _SCROLLBAR_OFF = Qt.ScrollBarPolicy.ScrollBarAlwaysOff
except AttributeError:  # pragma: no cover
    _NO_DRAG = QGraphicsView.NoDrag
    _SCROLLBAR_OFF = Qt.ScrollBarAlwaysOff

try:
    _NO_CACHE = QGraphicsItem.CacheMode.NoCache
except AttributeError:  # pragma: no cover
    _NO_CACHE = QGraphicsItem.NoCache

try:
    _SMOOTH_PIXMAP = Qt.TransformationMode.SmoothTransformation
except AttributeError:  # pragma: no cover
    _SMOOTH_PIXMAP = Qt.SmoothTransformation

#: 静态位图「空闲刷新」延迟：交换结束会要求后台页重新烘一版（数据已变），
#: 但那一刻动画刚停、用户还在看画面，同步 grab 5 张 750×1000 会卡 ~50ms。
#: 已有位图就先接着用，等这么久没新动作再补，人眼分辨不出后台页的旧值。
_SNAPSHOT_REFRESH_MS = 180
#: 每次事件循环最多补烘几张。7 张一次性做完是 ~60ms 的顿挫，拆成几拍之后
#: 单次停留 <20ms，全部位图仍在一个节奏内追平。
_SNAPSHOT_REFRESH_BATCH = 2


def _norm_deg(angle: float) -> float:
    value = float(angle) % 360.0
    return 0.0 if value < 1e-9 or 360.0 - value < 1e-9 else value


def _trace(trace, message: str) -> None:
    if callable(trace):
        try:
            trace(message)
        except Exception:  # noqa: BLE001 - 关窗跟踪不能反过来打断关窗
            pass


# ----------------------------------------------------------------------
# 真实控件承载层
# ----------------------------------------------------------------------
class RuntimeWidgetLayer(QObject):
    """每张卡片一个顶层 ``QGraphicsProxyWidget``，负责创建 / 对齐 / 回收。

    不复用 ``GraphicsScene.set_scene_mode(True)`` 自带的预览控件：那一条路径按
    ``widgetType`` 造 QLineEdit / QTextEdit，无法挂 App_PopPick 的 HMI 页面。
    这里保持 ``scene._widget_layer_on = False``，自己管理 proxy。
    """

    def __init__(self, scene: GraphicsScene, view: "RuntimeView") -> None:
        super().__init__(view)
        self._scene = scene
        self._view = view
        self._cards: dict[int, RuntimeCard] = {}
        self._proxies: dict[int, QGraphicsProxyWidget] = {}
        self._factories: dict[int, Callable] = {}
        self._readonly: dict[int, bool] = {}
        #: **当前**用位图显示（而不是真实控件）的卡。动画期由 layer 临时置真，
        #: 退出动画时按 :attr:`_static` 还原——两者必须分开记账，见
        #: :meth:`set_motion_cache` 的说明。
        self._cached: dict[int, bool] = {}
        #: 调用方（``HmiPagesHost.apply_static_pages``）要求的**长期**静态位图。
        #: 只有槽位上的两张前台页是实时控件，其余后台页长期用位图。
        #: 动画期的批量位图化不得写这里，否则动画结束会把「动画前的分布」
        #: 当成真值，槽位大卡就永远停在一张陈旧位图上（画面看起来错乱）。
        self._static: dict[int, bool] = {}
        #: 动画期顶替真实控件的位图（惰性生成，见 :meth:`_rebuild_snapshot`）
        self._snapshots: dict[int, QGraphicsPixmapItem] = {}
        #: 上一次真正落到 proxy 上的位姿，用来跳过无变化的重复写入
        self._pose_state: dict[int, tuple] = {}
        #: 是否处于 PageDeck 的动画窗口（由 ``set_widget_fast_paint`` 门控）。
        #: 动画期复用已烘好的位图；非动画期（apply_static_pages）才重烘，
        #: 这样每轮点击的起手不再是 7×grab ≈ 40ms。
        self._animating = False
        #: 需要重烘、但可以等到空闲再做的卡（见 :meth:`_flush_dirty_snapshots`）
        self._dirty: set[int] = set()
        self._dirty_timer: Optional[QTimer] = None
        self._released = False

    # -- 生命周期 -----------------------------------------------------
    def rebuild(self) -> None:
        """page 重新加载后按新图元重建卡片包装。"""
        self.release()
        self._released = False
        self._dirty.clear()
        self._cards = {}
        for item in self._scene.index.sorted_items():
            if item.TYPE == "widget":
                self._cards[item.item_id] = RuntimeCard(item, self)
        self.sync_all()

    def cards(self) -> list["RuntimeCard"]:
        return list(self._cards.values())

    def cards_in_draw_order(self) -> list["RuntimeCard"]:
        """按当前 Z 稳定排序（与旧 ``SceneManager.m_sorted_items`` 口径一致）。

        次键取 ``SceneIndex.order``（page JSON 的插入顺序），不是当前已排过序
        的 ``sorted_items``，否则相同 Z 时的相对次序会随上一次排序漂移。
        """
        order = {iid: index for index, iid in enumerate(self._scene.index.order)}
        return sorted(self._cards.values(),
                      key=lambda card: (card.zValue(),
                                        order.get(card.item_id, 0)))

    def card_for(self, item) -> Optional["RuntimeCard"]:
        return self._cards.get(item.item_id)

    def proxies(self) -> dict[int, QGraphicsProxyWidget]:
        return dict(self._proxies)

    def view(self) -> "RuntimeView":
        return self._view

    # -- 控件工厂 -----------------------------------------------------
    def set_factory(self, card: "RuntimeCard", factory: Callable) -> None:
        iid = card.item_id
        self._factories[iid] = factory
        self._drop_proxy(iid)
        self._ensure_proxy(card)

    def _ensure_proxy(self, card: "RuntimeCard") -> None:
        if self._released:
            return
        iid = card.item_id
        factory = self._factories.get(iid)
        if factory is None or iid in self._proxies:
            return
        # HmiPage 的构造是 (catalog, parent=None)：传 None 得到无父 QWidget，
        # QGraphicsProxyWidget.setWidget() 要求 widget 没有 parent。
        widget = factory(None)
        if widget is None:
            return
        if widget.parent() is not None:
            widget.setParent(None)
        proxy = QGraphicsProxyWidget()
        proxy.setFlag(QGraphicsItem.ItemIsSelectable, False)
        proxy.setFlag(QGraphicsItem.ItemIsMovable, False)
        proxy.setAcceptedMouseButtons(_ALL_BUTTONS)
        self._scene.addItem(proxy)
        proxy.setWidget(widget)
        self._proxies[iid] = proxy
        # 真实控件是不透明的，占位框永远看不见；让图元不产出任何像素，
        # 省掉 7 张 750×1000 白底 + 黑边每帧重画的成本（实测约占一帧 10ms）。
        card.item.setFlag(QGraphicsItem.ItemHasNoContents, True)
        self._apply_readonly(iid)
        self._apply_cache(iid)
        self._pose_state.pop(iid, None)
        self.sync_card(card)

    def _drop_proxy(self, iid: int) -> None:
        self._drop_snapshot(iid)
        self._dirty.discard(iid)
        self._pose_state.pop(iid, None)
        proxy = self._proxies.pop(iid, None)
        if proxy is None:
            return
        card = self._cards.get(iid)
        if card is not None:
            card.item.setFlag(QGraphicsItem.ItemHasNoContents, False)
        widget = proxy.widget()
        try:
            proxy.setWidget(None)
        except RuntimeError:
            pass
        try:
            self._scene.removeItem(proxy)
        except RuntimeError:
            pass
        self._dispose_widget(widget)

    @staticmethod
    def _dispose_widget(widget: Optional[QWidget]) -> None:
        if widget is None:
            return
        try:
            # setWidget(None) 会把控件变成无父顶层窗口；不 hide/deleteLater
            # 就会留下盖住工具页的「幽灵控件」（旧场景 release_embedded_widgets
            # 存在的唯一理由）。
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        except RuntimeError:
            pass

    # -- 几何 / 层级 --------------------------------------------------
    def sync_all(self) -> None:
        for card in self._cards.values():
            self.sync_card(card)
        self._view.viewport().update()

    def sync_card(self, card: "RuntimeCard") -> None:
        proxy = self._proxies.get(card.item_id)
        if proxy is None:
            return
        iid = card.item_id
        item = card.item
        rect = item.boundingRect()
        w, h = rect.width(), rect.height()
        # QGraphicsProxyWidget 继承 QGraphicsWidget：geometry.topLeft() 就是
        # 它的局部原点（等价于 pos），控件实际画在 [pos, pos+size]。所以不能
        # 写成 ``setGeometry(-w/2,-h/2,w,h)`` 再 ``setPos(center)`` ——那会让
        # 整页以「卡片中心」为左上角，露出占位白框、内容溢出到右下。
        # 正确做法：pos 落在 center-半尺寸，旋转支点显式挪到几何中心。
        center = item.mapToScene(QPointF(0.0, 0.0))
        pos = center - QPointF(w / 2.0, h / 2.0)
        rotation = item.rotation()
        z = item.zValue() + 0.5
        visible = bool(item.get_visibility())

        # 动画每帧会 sync 全部卡（PageDeck._restack / _flush_pose）。位姿没变
        # 就一个调用都不发：无差别 setPos / update 会把 7 张 750×1000 页面
        # 全部标脏重绘，一帧 100ms 起，这才是「点几下就卡」的真正来源。
        state = (w, h, pos.x(), pos.y(), rotation, z, visible)
        if self._pose_state.get(iid) == state:
            return
        self._pose_state[iid] = state

        if proxy.size().width() != w or proxy.size().height() != h:
            proxy.resize(w, h)
            proxy.setTransformOriginPoint(QPointF(w / 2.0, h / 2.0))
        proxy.setPos(pos)
        proxy.setRotation(rotation)
        proxy.setZValue(z)

        # 当前这一张是否由位图顶替（_cached 是「谁在显示」的唯一真值）
        snapshot = self._snapshots.get(iid) if self._cached.get(iid) else None
        if snapshot is not None:
            proxy.setVisible(False)
            snapshot.setPos(pos)
            snapshot.setRotation(rotation)
            snapshot.setZValue(z)
            snapshot.setVisible(visible)
        else:
            proxy.setVisible(visible)
            stale = self._snapshots.get(iid)
            if stale is not None:
                stale.setVisible(False)

    # -- 只读 / 静态标记 ----------------------------------------------
    def set_readonly(self, card: "RuntimeCard", readonly: bool) -> None:
        self._readonly[card.item_id] = bool(readonly)
        self._apply_readonly(card.item_id)

    def readonly(self, card: "RuntimeCard") -> bool:
        return bool(self._readonly.get(card.item_id, False))

    def _apply_readonly(self, iid: int) -> None:
        proxy = self._proxies.get(iid)
        if proxy is None:
            return
        readonly = bool(self._readonly.get(iid, False))
        # proxy 不吃鼠标 → 点击落到场景/窗口的 eventFilter，用于页面交换；
        # 放开交互时把按钮交还给页面 QWidget。
        proxy.setAcceptedMouseButtons(_NO_BUTTONS if readonly else _ALL_BUTTONS)
        widget = proxy.widget()
        if widget is not None:
            self._set_tree_transparent(widget, readonly)

    @staticmethod
    def _set_tree_transparent(widget: QWidget, value: bool) -> None:
        # WA_TransparentForMouseEvents 不自动传给子控件，页内按钮/文本框
        # 会自己把按下事件吃掉（旧代码里 QTextEdit 就这样让交换点不动）。
        for node in [widget, *widget.findChildren(QWidget)]:
            try:
                node.setAttribute(_WA_TRANSPARENT, value)
            except RuntimeError:
                pass

    def set_motion_cache(self, card: "RuntimeCard", active: bool) -> None:
        """把这一张卡换成位图顶替真实控件（旧 ``set_motion_cache``）。

        旧 Core 的卡片是独立顶层子窗口，动画只移动窗口、不重绘页面内容，
        所以流畅；``QGraphicsProxyWidget`` 没有这条路——每次 setPos/setRotation
        都会让 750×1000 的 HMI 页面整页重渲染，实测单卡 ~14ms、7 卡一帧 100ms。
        这里回到旧 Core 的等价做法：把控件 grab 成位图，动画期只画位图。

        **两种调用方语义必须分开**：

        - ``PageDeck._set_fast_render``：动画期对**全部**卡开关一次，属于
          临时位图化。动画期不写 :attr:`_static`，退出时统一还原。
        - ``HmiPagesHost.apply_static_pages``：长期意图（槽位 2 张实时、
          后台 5 张静态）。动画期之外的调用才写 :attr:`_static`。

        早期实现用「动画前的 ``_cached`` 快照」做恢复依据，结果动画结束后的
        ``apply_static_pages``（它刚把新槽位卡改成实时）被那份旧分布覆盖，
        槽位大卡永久停在动画期的陈旧位图上——画面看起来就是"位置/内容错乱"。

        另外这里**不做同步重烘**（除首次没有位图可显示）：交换结束那一刻会
        对 5 张后台页调一次 ``True``，一张 grab ≈10ms，5 张一起就是一次 50ms
        的顿挫，正好落在用户刚放手的时候。改成「先复用旧图 + 标脏」，由
        :meth:`_flush_dirty_snapshots` 分片补新的。
        """
        iid = card.item_id
        active = bool(active)
        if self._animating:
            # 动画窗口内一律位图化，且不动长期意图
            want = True
        else:
            self._static[iid] = active
            want = active
        if want and iid not in self._snapshots:
            # 没有位图就没东西可显示（proxy 已隐藏），只能当场烘。但此刻控件
            # 可能还没走完首次布局/首绘（启动时 apply_static_pages 就是这种
            # 情况），抓出来是一张白图；所以照样标脏，空闲时补一版真的。
            self._rebuild_snapshot(card)
            self._mark_snapshot_dirty(iid)
        elif want and not self._animating:
            # 有图就先复用：此刻多半是交换刚结束、动画刚停，同步 grab 会卡帧。
            # 标脏后由空闲定时器补一版新的（见 _flush_dirty_snapshots）。
            self._mark_snapshot_dirty(iid)
        elif not want and iid in self._snapshots and not self._animating:
            # 实时卡自己的「备用位图」也顺手追平：它下次要动画时才用得上，
            # 不追就会在动画里闪一下几分钟前的旧数值。
            self._mark_snapshot_dirty(iid)
        if want and iid not in self._snapshots:
            want = False               # 烘图失败就老实显示控件，别留一张空白位图
        self._cached[iid] = want
        # 「谁在显示」变了，位姿本身没变也必须重落一遍：否则 proxy 会继续
        # 可见、与位图双画；或反过来停在位图上不刷新。
        self._pose_state.pop(iid, None)
        self.sync_card(card)

    def set_animating(self, active: bool) -> None:
        """PageDeck 的动画窗口开关：全部卡位图化 + 精确标脏。

        进入：把 7 张全切成位图（脏区会盖住旁边的堆叠卡，留一张真实控件
        就得多渲染一整页）；已有位图直接复用，缺的才烘。
        退出：按 :attr:`_static` 还原成调用方要的分布——注意是**退出这一刻**
        的长期意图，不是"动画前"的旧分布，否则刚落位的槽位卡会继续用位图。
        """
        active = bool(active)
        if active == self._animating:
            return
        self._animating = active
        self._view.set_exact_repaint(active)
        for iid, card in list(self._cards.items()):
            want = True if active else bool(self._static.get(iid, False))
            if want and iid not in self._snapshots:
                self._rebuild_snapshot(card)
            if want and iid not in self._snapshots:
                want = False
            self._cached[iid] = want
            self._pose_state.pop(iid, None)
            self.sync_card(card)

    def is_motion_cache(self, card: "RuntimeCard") -> bool:
        return bool(self._cached.get(card.item_id, False))

    def _mark_snapshot_dirty(self, iid: int) -> None:
        """记下「这张的位图过期了」，等空闲时统一补烘。"""
        if self._released:
            return
        self._dirty.add(iid)
        if self._dirty_timer is None:
            self._dirty_timer = QTimer(self)
            self._dirty_timer.setSingleShot(True)
            self._dirty_timer.timeout.connect(self._flush_dirty_snapshots)
        self._dirty_timer.start(_SNAPSHOT_REFRESH_MS)

    def _flush_dirty_snapshots(self) -> None:
        """空闲刷新过期的静态位图：每次事件循环只做一小批，避免整段顿挫。"""
        if self._released:
            self._dirty.clear()
            return
        if self._animating:
            # 动画期位图正在当画面用，挪不得；等这一轮结束再说
            if self._dirty and self._dirty_timer is not None:
                self._dirty_timer.start(_SNAPSHOT_REFRESH_MS)
            return
        pending = sorted(self._dirty)
        done = 0
        while pending and done < _SNAPSHOT_REFRESH_BATCH:
            iid = pending.pop(0)
            self._dirty.discard(iid)
            done += 1
            card = self._cards.get(iid)
            if card is None or iid not in self._proxies:
                continue
            if iid not in self._snapshots:
                continue
            self._rebuild_snapshot(card)
            if self._cached.get(iid):
                # 位图正在显示：位姿没变但内容变了，重落一遍让新图上线
                self._pose_state.pop(iid, None)
                self.sync_card(card)
        if self._dirty and self._dirty_timer is not None:
            self._dirty_timer.start(_SNAPSHOT_REFRESH_MS)

    def _rebuild_snapshot(self, card: "RuntimeCard") -> Optional[QGraphicsPixmapItem]:
        """把真实控件当前画面烘到位图上（就地更新，item 只建一次）。

        位图按「动画期实际显示的像素尺寸」烘，不按控件的 1:1 尺寸：卡片被
        视图缩到 ~0.73、屏幕 DPR 1.25，750×1000 的页面最终只占 685×913 个
        物理像素。按 1:1 烘会让每帧都做一次大图降采样（15ms），按显示尺寸
        烘则基本是 1:1 贴图（9.6ms），视觉上没有区别——动画结束就换回真实
        控件，静止画面依然是矢量清晰版。
        """
        iid = card.item_id
        proxy = self._proxies.get(iid)
        if proxy is None:
            return None
        widget = proxy.widget()
        if widget is None:
            return None
        pixmap: QPixmap = widget.grab()
        if pixmap.isNull():
            return None
        pixmap = self._fit_pixmap_to_view(pixmap)
        snapshot = self._snapshots.get(iid)
        if snapshot is None:
            snapshot = QGraphicsPixmapItem()
            snapshot.setAcceptedMouseButtons(_NO_BUTTONS)
            snapshot.setFlag(QGraphicsItem.ItemIsSelectable, False)
            snapshot.setFlag(QGraphicsItem.ItemIsMovable, False)
            snapshot.setTransformationMode(_SMOOTH_PIXMAP)
            self._scene.addItem(snapshot)
            self._snapshots[iid] = snapshot
        snapshot.setPixmap(pixmap)
        # 位图的局部原点是左上角，旋转支点要显式挪到中心，才和 proxy 的
        # 「绕控件中心转」完全一致。
        dpr = float(pixmap.devicePixelRatio() or 1.0)
        snapshot.setTransformOriginPoint(
            QPointF(pixmap.width() / dpr / 2.0, pixmap.height() / dpr / 2.0)
        )
        if not self._cached.get(iid):
            # 预热出来的位图只是备用，这会儿该显示的是真实控件
            snapshot.setVisible(False)
        return snapshot

    def _fit_pixmap_to_view(self, pixmap: QPixmap) -> QPixmap:
        """把位图缩放到「动画期实际显示的分辨率」，避免每帧大图降采样。

        算的是**物理像素**：``grab()`` 回来的是 938×1250（DPR 1.25 的 750×1000），
        而卡片在屏幕上只占 ``750 × 0.729 × 1.25 ≈ 683`` 个设备像素。按物理像素
        定标才不会多烘一档——早期版本拿已乘过 DPR 的宽再乘一次缩放，烘出 855px，
        每帧仍要做一次 0.8 倍降采样，白花 25% 的填充量。
        """
        dpr = float(pixmap.devicePixelRatio() or 1.0)
        logical_w = pixmap.width() / dpr
        scale = self._display_scale()          # 逻辑像素 → 屏幕物理像素
        # 放大显示（scale >= 1）时保持原图；过小的 scale 兜个底
        if not (0.05 < scale < 0.999) or logical_w <= 1.0:
            return pixmap
        target = max(16, int(round(logical_w * scale)))
        if target >= pixmap.width():
            return pixmap
        scaled = pixmap.scaledToWidth(target, _SMOOTH_PIXMAP)
        # 逻辑尺寸必须还是控件原尺寸：QGraphicsPixmapItem 用 size/DPR 当
        # boundingRect，反算 DPR 就等于「物理宽 / 逻辑宽」，恒保持 750×1000。
        scaled.setDevicePixelRatio(target / logical_w)
        return scaled

    def _display_scale(self) -> float:
        """逻辑像素 → 屏幕物理像素的倍率（视图缩放 × 屏幕 DPR）。"""
        scale = float(self._view.transform().m11() or 0.0)
        if scale <= 0.0:
            return 1.0
        try:
            screen_dpr = float(self._view.devicePixelRatioF() or 1.0)
        except (AttributeError, RuntimeError):
            screen_dpr = 1.0
        return scale * screen_dpr

    def prewarm(self) -> None:
        """空闲时把位图烘好（分辨率跟当前视图缩放对齐）。

        启动后 ``apply_static_pages`` 只烘了后台页（它们本来就要静态位图），
        前台那两页是实时控件、没有位图，第一次点击才临时 grab（DPR 1.25 下
        两张要 ~70ms，肉眼就是"点下去先愣一下"）。另外视图 fit 之前烘出来
        的是 1:1 大图，动画期每帧都要降采样，所以这里顺带校正分辨率。
        """
        if self._released or self._animating:
            return
        for iid, card in self._cards.items():
            if self._proxies.get(iid) is None:
                continue
            snapshot = self._snapshots.get(iid)
            if snapshot is None:
                # 没有备用位图的（就是前台两页实时控件）必须现烘，否则第一次
                # 点击时临时 grab 两张 DPR 1.25 的页面要 ~70ms，肉眼就是"愣一下"。
                self._rebuild_snapshot(card)
                continue
            if self._snapshot_needs_rescale(snapshot):
                # 只是分辨率没跟上视图缩放：交给分片空闲刷新，别在这儿一次
                # 做掉 5 张 grab（~50ms，启动/缩放时会有明显顿挫）。
                self._mark_snapshot_dirty(iid)

    def _snapshot_needs_rescale(self, snapshot: QGraphicsPixmapItem) -> bool:
        """已有位图的物理像素是否和「当前显示分辨率」差得太多（>15%）。

        口径必须和 :meth:`_fit_pixmap_to_view` 一致：比的是物理宽 vs
        ``逻辑宽 × 显示倍率``。别用位图自己的 DPR 去推期望值——那个 DPR 正是
        上一轮缩放算出来的，自比永远相等（或永远不等），会退化成反复重烘。
        """
        pixmap = snapshot.pixmap()
        if pixmap.isNull():
            return True
        dpr = float(pixmap.devicePixelRatio() or 1.0)
        logical_w = pixmap.width() / dpr
        scale = self._display_scale()
        if not (0.05 < scale < 0.999):
            return False                    # 这种倍率下本来就不缩放，无需对齐
        expected = logical_w * scale
        if expected <= 1.0 or pixmap.width() <= 1:
            return False
        return abs(pixmap.width() - expected) / expected > 0.15

    def _drop_snapshot(self, iid: int) -> None:
        snapshot = self._snapshots.pop(iid, None)
        if snapshot is None:
            return
        try:
            self._scene.removeItem(snapshot)
        except RuntimeError:
            pass

    def _apply_cache(self, iid: int) -> None:
        proxy = self._proxies.get(iid)
        if proxy is None:
            return
        # 刻意不用 Qt 的 ItemCoordinateCache：它按 boundingRect 分配缓存位图，
        # 而 proxy 每帧都在改 pos / rotation / transformOriginPoint，缓存的
        # deviceTransform 跟不上，真实 GUI 下连点几次会留下错位轮廓与斜线残影。
        # 动画期的位图由 :meth:`_ensure_snapshot` 自己烘，完全可控。
        proxy.setCacheMode(_NO_CACHE)

    # -- 关窗回收 -----------------------------------------------------
    def release(self, trace=None) -> None:
        if self._released and not self._proxies:
            return
        _trace(trace, f"回收 {len(self._proxies)} 个 QGraphicsProxyWidget")
        if self._dirty_timer is not None:
            self._dirty_timer.stop()
        self._dirty.clear()
        for iid in list(self._proxies):
            self._drop_proxy(iid)
        self._proxies.clear()
        self._snapshots.clear()
        self._pose_state.clear()
        self._factories.clear()
        self._cards.clear()
        self._released = True


# ----------------------------------------------------------------------
# 卡片图元适配（旧 widget_element 的接口）
# ----------------------------------------------------------------------
class RuntimeCard:
    """把 ``WidgetItem`` 包成旧 ``widget_element`` 的鸭子类型接口。

    PageDeck 的位姿契约只有两个数：场景中心 + 记账角度。旧 Core 用
    ``setRotation(delta)`` 绕支点转出一段弧、再 ``setPos`` 把中心补回来；
    这里直接按「绝对角度 → 绝对中心」落地（:meth:`_flush_pose`），净效果
    完全一致，还避免了自定义支点 ``origin_pos`` 在动画里逐帧漂移。
    """

    TYPE = "widget"

    def __init__(self, item, layer: RuntimeWidgetLayer) -> None:
        self._item = item
        self._layer = layer
        self._center = QPointF(*item.page_center())
        self._angle = _norm_deg(item.page_angle())

    @property
    def item(self):
        return self._item

    @property
    def item_id(self) -> int:
        return self._item.item_id

    # -- 旧 API：名字 / 可见性 / Z --------------------------------------
    def get_name(self) -> str:
        return self._item.get_name()

    def get_visibility(self) -> bool:
        return self._item.get_visibility()

    def zValue(self):
        # 旧 Core 的 zValue 是 int（Qt QGraphicsItem 是 qreal）。运行态的 Z
        # 永远是整数，规整回 int 才能和 ``range()``、Z 值断言这类旧口径兼容。
        value = float(self._item.zValue())
        return int(value) if value.is_integer() else value

    def set_zValue(self, value: float) -> None:
        self._item.setZValue(float(value))
        self._layer.sync_card(self)

    # -- 旧 API：位姿 --------------------------------------------------
    def get_scene_center_pos(self) -> QPointF:
        return QPointF(self._center)

    def get_angle(self) -> float:
        return self._angle

    def pos(self) -> QPointF:
        """旧 Core 的 ``pos()`` 是 page 场景坐标，``setPos(pos()+shift)`` 靠它自洽。"""
        return QPointF(self._center)

    def set_angle(self, angle: float) -> None:
        self._angle = _norm_deg(angle)
        self._flush_pose()

    def setRotation(self, delta: float) -> None:
        """PageDeck 紧接着会 ``set_angle`` + ``setPos`` 给出绝对位姿，无需增量旋转。

        保留空实现是为了让 ``_apply_pose`` 原样运行：绕支点转出来的那段中心弧
        本来就会被后面的 ``setPos`` 补偿掉。
        """

    def setPos(self, pos: QPointF) -> None:
        self._center = QPointF(pos)
        self._flush_pose()

    def _flush_pose(self) -> None:
        # set_page_angle 绕支点转，可视中心会跟着偏；set_page_center 再把它
        # 精确拉回账本值。顺序不能反，否则纯旋转帧会留下中心漂移。
        self._item.set_page_angle(self._angle)
        self._item.set_page_center(self._center.x(), self._center.y())
        # 只同步这一张：动画每帧只动两张卡，没动的卡不需要重新落一遍位姿
        # （sync_all 会顺带把 7 张 750×1000 页面全部标脏）。
        self._layer.sync_card(self)

    # -- 旧 API：命中测试 ----------------------------------------------
    def getSize(self) -> QSizeF:
        return QSizeF(*self._item.page_size())

    def get_center_pos(self) -> QPointF:
        w, h = self._item.page_size()
        return QPointF(w / 2.0, h / 2.0)

    def mapFromScene(self, scene_pos: QPointF) -> QPointF:
        """page 场景点 → ``_local_rect``（QRectF(0,0,w,h)）里的局部点。

        先用 Qt 的 ``item.mapFromScene`` 复用它已有的旋转 / 自定义支点变换，
        再把得到的「视图局部向量」线性反投影回 page 局部向量 —— 这样不用自己
        推角度符号，AGV 轴交换也只出现一次。
        """
        proj = self._item._proj
        view_pt = proj.point(scene_pos.x(), scene_pos.y())
        local = self._item.mapFromScene(view_pt)
        if proj.agv:
            px, py = -local.y() / proj.ky, -local.x() / proj.kx
        else:
            px, py = local.x() / proj.kx, -local.y() / proj.ky
        w, h = self._item.page_size()
        return QPointF(px + w / 2.0, py + h / 2.0)

    def sceneBoundingRect(self) -> QRectF:
        """page 坐标 AABB，等价旧 ``base_element.sceneBoundingRect()``。"""
        return self._item.page_bounding_rect()

    # -- 旧 API：承载控件 ----------------------------------------------
    def update_boundingRect(self) -> None:
        # QGraphicsItem 自动管理包围盒；这里承担旧实现「顺带同步控件几何」的职责
        self._layer.sync_all()

    def sync_widget_geometry(self) -> None:
        self._layer.sync_card(self)

    def raise_widget_view(self) -> None:
        self._layer.sync_card(self)

    def set_widget_factory(self, factory: Callable) -> None:
        self._layer.set_factory(self, factory)

    def set_widget_readonly(self, readonly: bool) -> None:
        self._layer.set_readonly(self, readonly)

    def widget_readonly(self) -> bool:
        return self._layer.readonly(self)

    def set_motion_cache(self, active: bool) -> None:
        self._layer.set_motion_cache(self, active)

    def is_motion_cache(self) -> bool:
        return self._layer.is_motion_cache(self)

    def set_widget_fast_paint(self, active: bool) -> None:
        """PageDeck 动画期开关：进入 / 退出快速渲染窗口。

        旧 Core 里占位框就是卡片的可见边框（控件是透明的独立子窗口），
        所以那时只描边不填底。新后端相反：真实控件不透明地盖满整张卡，
        占位框永远看不见（``_ensure_proxy`` 已让图元不产出像素），因此这里
        不再动绘制内容，只负责：动画期复用常驻位图 + 关掉 ``scene.update()``
        的整窗重绘。
        """
        self._layer.set_animating(bool(active))

    def widget_pixel_size(self) -> QSizeF:
        return QSizeF(self._item.boundingRect().size())

    def has_widget_layer(self) -> bool:
        return self.item_id in self._layer.proxies()

    def fit_widget_size(self, size) -> None:
        """把 page 尺寸校正成「正好容纳 ``size`` 像素的控件」。

        AGV 下 view 宽对应 page 高、view 高对应 page 宽，交给
        ``SceneProjection.inverse_size`` 换算，别手工除 kx。
        """
        proj = self._item._proj
        w, h = proj.inverse_size(float(size.width()), float(size.height()))
        if w <= 0 or h <= 0:
            return
        self._item.set_page_size(w, h)
        # set_page_size 不改位姿，但为重入安全仍把中心对齐到账本值
        self._item.set_page_center(self._center.x(), self._center.y())
        self._layer.sync_card(self)


# ----------------------------------------------------------------------
# 场景管理器适配（旧 SceneManager 的接口）
# ----------------------------------------------------------------------
class RuntimeSceneManager(QObject):
    def __init__(self, view: "RuntimeView", layer: RuntimeWidgetLayer) -> None:
        super().__init__(view)
        self._view = view
        self._layer = layer
        self.m_scene = view

    @property
    def m_sorted_items(self) -> list[RuntimeCard]:
        return self._layer.cards_in_draw_order()

    def findItemByName(self, name: str):  # noqa: N802 - 旧 API 命名
        for card in self._layer.cards():
            if card.get_name() == name:
                return card
        return None

    def all_items(self) -> list[RuntimeCard]:
        return self._layer.cards()


# ----------------------------------------------------------------------
# 视图 / 场景适配（旧 QuadTreeScene 的运行态接口）
# ----------------------------------------------------------------------
class RuntimeView(GraphicsView):
    """既是 centralWidget，也是 PageDeck 眼里的「scene」。"""

    # 旧入口会显式清空它；保留同名属性避免 AttributeError
    update_callback = None

    def __init__(self, scene: GraphicsScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.scene_manager: Optional[RuntimeSceneManager] = None
        self._layer: Optional[RuntimeWidgetLayer] = None
        self._run_mode = False
        # 导航门控交给 GraphicsView（set_pan_enabled / set_zoom_enabled）：
        # 运行态默认全关，需要看细节时调 set_canvas_navigation_enabled(True)。
        self.set_canvas_navigation_enabled(False)
        #: 动画期由 layer 精确标脏，忽略 PageDeck 每帧的整窗 ``update()``
        self._exact_repaint = False
        #: 视图变换稳定后再烘位图（fit 之前烘出来的是 1:1 大图，白费）
        self._prewarm_timer: Optional[QTimer] = None
        # 运行态不要设计器的网格 / 选中标记 / 框选 / 滚动条
        self.show_grid = False
        self.show_ids = False
        self.snap.show_markers = False
        self.setDragMode(_NO_DRAG)
        self.setHorizontalScrollBarPolicy(_SCROLLBAR_OFF)
        self.setVerticalScrollBarPolicy(_SCROLLBAR_OFF)
        # 只重绘真正变化的那块：动画期一张卡动起来只是它自己的 AABB（含
        # 旋转后的旧/新位置）需要重画，整窗重绘会把 7 张 750×1000 页面
        # 全部重新渲染一遍。Qt 对 item 的 sceneTransform 变化会同时标脏
        # 旧的与新的 AABB，不会漏擦。
        self.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)
        if hasattr(self.snap, "grid_enabled"):
            self.snap.grid_enabled = False

    # -- 装配 ----------------------------------------------------------
    def _attach_layer(self, layer: RuntimeWidgetLayer) -> None:
        self._layer = layer

    def set_exact_repaint(self, enable: bool) -> None:
        self._exact_repaint = bool(enable)

    def update(self, *args, **kwargs):  # noqa: A003 - QWidget 命名
        """动画期吞掉 PageDeck 的整窗 ``update()``，改由精确标脏负责。

        PageDeck 每帧末尾都会 ``self._scene.update()``。旧 Core 里 ``scene``
        是 QWidget，那是局部重绘，很便宜；换成 QGraphicsView 之后它等于
        「整个视口重绘一遍」，7 张 750×1000 页面全部重画 = 一帧 100ms。
        动画期间每张卡自己标脏自己就够（``RuntimeWidgetLayer.sync_card``）。
        """
        if self._exact_repaint:
            return
        self.viewport().update()

    def set_scene_manager(self, manager: RuntimeSceneManager) -> None:
        self.scene_manager = manager

    # -- 加载 ----------------------------------------------------------
    def delete_all_elements(self) -> None:
        if self._layer is not None:
            self._layer.release()
        self.scene().clear_page()

    def load_scene_file(self, path: str) -> int:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"场景文件不存在: {path}")
        self.delete_all_elements()
        count = self.scene().load_page(path)
        if self._layer is not None:
            self._layer.rebuild()
        return count

    def set_scene_mode(self, run) -> None:
        """切运行态。刻意不调 ``scene.set_scene_mode(True)``。

        那条路径会给每个 widget 造一个默认 QLineEdit/QTextEdit 预览控件，
        和 App_PopPick 的页面工厂抢同一批卡片；这里只做门控，控件由
        :class:`RuntimeWidgetLayer` 自己挂。
        """
        self._run_mode = True
        scene = self.scene()
        scene.is_run_mode = True
        scene._widget_layer_on = False
        scene.clearSelection()
        for item in scene.all_items():
            item.set_selectable(False)
            item.setFlag(QGraphicsItem.ItemIsMovable, False)
            # 设计器的 hover 高亮（BaseItem.stroke_color 返回 HOVER_COLOR）
            # 是编辑反馈，运行态鼠标划过卡片不该把边框染成绿色。
            item.setAcceptHoverEvents(False)
        self.show_grid = False
        if self._layer is not None:
            self._layer.sync_all()
            self._schedule_prewarm()

    # -- 位图预热 ------------------------------------------------------
    def _schedule_prewarm(self) -> None:
        """视图变换稳定 350ms 后再烘位图（fit 之前烘的是 1:1 大图，白费）。"""
        if self._layer is None:
            return
        if self._prewarm_timer is None:
            self._prewarm_timer = QTimer(self)
            self._prewarm_timer.setSingleShot(True)
            self._prewarm_timer.timeout.connect(self._run_prewarm)
        self._prewarm_timer.start(350)

    def _run_prewarm(self) -> None:
        if self._layer is not None:
            self._layer.prewarm()

    # -- 画布导航 ------------------------------------------------------
    # 开关本体在 GraphicsView（set_pan_enabled / set_zoom_enabled /
    # set_canvas_navigation_enabled），这里不再另存一份状态，避免两套布尔值
    # 打架。下面三个鼠标事件只在「正在平移」时才交给 GraphicsView，其余情况
    # 直通 QGraphicsView —— 绕开设计器的框选 / CTRL 拖动 / 右键菜单 / 跟手。

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.is_pan_event(event):
            GraphicsView.mousePressEvent(self, event)
            return
        QGraphicsView.mousePressEvent(self, event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            GraphicsView.mouseMoveEvent(self, event)
            return
        QGraphicsView.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            GraphicsView.mouseReleaseEvent(self, event)
            return
        QGraphicsView.mouseReleaseEvent(self, event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        QGraphicsView.mouseDoubleClickEvent(self, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # 运行态不响应设计器的 Ctrl+C/V、R、T 等快捷键；只放行空格，
        # 它在中键之外提供第二种平移手势（_pan_enabled 为假时基类会再挡一层）。
        if event.key() == Qt.Key_Space and self.is_pan_enabled():
            GraphicsView.keyPressEvent(self, event)
            return
        event.ignore()

    # -- 坐标换算 ------------------------------------------------------
    @property
    def projection(self) -> SceneProjection:
        return self.scene().projection

    def sceneToView(self, point: QPointF) -> QPointF:
        """page 场景坐标 → 投影后视图坐标（== 旧 ``sceneToView``）。"""
        return self.projection.point(point.x(), point.y())

    def viewToScene(self, point: QPointF) -> QPointF:
        """投影后视图坐标 → page 场景坐标（== 旧 ``viewToScene``）。"""
        return QPointF(*self.projection.inverse_point(point.x(), point.y()))

    def window_to_page(self, window_pos: QPointF) -> QPointF:
        """窗口/视口像素 → page 场景坐标。

        旧实现是 ``(window_pos - offset) / scale`` → ``viewToScene``；新场景由
        ``QGraphicsView.mapToScene`` 承担视图变换，再反投影回 page 坐标。
        Qt6 的 ``mapToScene`` 只收整数 ``QPoint``，这里用视图逆变换把小数部分
        补回来，避免放大时累积到几个场景单位的偏差。
        """
        x, y = float(window_pos.x()), float(window_pos.y())
        ip = QPoint(int(round(x)), int(round(y)))
        scene_pt = QPointF(self.mapToScene(ip))
        inv, ok = self.transform().inverted()
        if ok:
            origin = inv.map(QPointF(0.0, 0.0))
            delta = inv.map(QPointF(x - ip.x(), y - ip.y())) - origin
            scene_pt = QPointF(scene_pt.x() + delta.x(), scene_pt.y() + delta.y())
        return QPointF(*self.projection.inverse_point(scene_pt.x(), scene_pt.y()))

    # -- 取景 ----------------------------------------------------------
    def set_view_scene_rect(self, rect: QRectF) -> bool:
        """把一段 **page 坐标** 矩形铺满视口（等价旧 ``set_view_scene_rect``）。

        新场景同名方法只把 rect 写进 JSON header 供设计器保存，不动视图；
        这里投影成视图矩形后走 ``fitInView``。
        """
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            return False
        self.fitInView(self.projection.rect(rect), _KEEP_RATIO)
        self.refresh_embedded_widgets()
        # 缩放变了，之前烘的位图分辨率不再匹配，重烘一次
        self._schedule_prewarm()
        return True

    def fit_content(self) -> None:
        # 设计器的 fit_content 用 scene.fit_rect()（视图坐标），运行态沿用即可
        super().fit_content()
        self.refresh_embedded_widgets()
        self._schedule_prewarm()

    # -- 承载控件 ------------------------------------------------------
    def refresh_embedded_widgets(self) -> None:
        if self._layer is not None:
            self._layer.sync_all()
        else:
            self.viewport().update()

    def _sync_embedded_widgets_geometry(self) -> None:
        """旧 PageDeck._restack / HmiPagesHost.apply_static_pages 会调它。"""
        self.refresh_embedded_widgets()

    def release_embedded_widgets(self, trace=None) -> None:
        if self._layer is not None:
            self._layer.release(trace=trace)


# ----------------------------------------------------------------------
def create_runtime_scene(parent=None) -> tuple[RuntimeView, RuntimeSceneManager]:
    """建一套可塞进 QMainWindow 的运行态场景。

    返回 ``(view, manager)``：``view`` 是 centralWidget 兼事件过滤宿主；
    ``manager`` 传给 ``attach_hmi_pages`` / ``find_page_cards``。
    """
    scene = GraphicsScene(SceneProjection())
    scene.setObjectName("popPickGraphicsScene")
    view = RuntimeView(scene, parent)
    layer = RuntimeWidgetLayer(scene, view)
    view._attach_layer(layer)
    manager = RuntimeSceneManager(view, layer)
    view.set_scene_manager(manager)
    return view, manager
