# -*- coding: utf-8 -*-
"""让「背景」widget 图元在任何缩放 / 窗口尺寸下都撑满整个视口。

问题
====
``page_9.json`` 里的「背景」是一张普通 widget 图元（id=15、z=-1），入口用
``stage.set_factory("背景", InkPondWidget)`` 给它挂了水墨控件。它在设计文件里
只有一份固定的 page 矩形（6336×9076），视图一缩放，这段矩形在屏幕上要么
缩成中间一块、要么被推出视口，四周就露出 ``backgroundColor`` 的底色。

做法
====
每次视口取景变化，把**当前视口对应的 page 矩形**算出来，用 element 自己的
两个几何接口把背景搬过去、放大到那么大：

* :meth:`BackgroundElement.change_pos` → ``RuntimeElement.change_position``
  （把 page 包围盒左上角移到目标点，内部只动 Qt 变换 + 承载控件对齐）；
* :meth:`BackgroundElement.change_size` → ``RuntimeElement.fit_widget_size``
  （按视图像素尺寸反算 page 宽高，内部 ``set_page_size`` + 承载控件对齐）。

承载层的 ``WidgetHost.align`` 会按图元新的 ``boundingRect()`` 自动
``proxy.resize(w,h)``，所以真实控件跟着铺满屏幕，不需要自己去碰 proxy。

坐标口径
========
视口像素 → ``view.mapToScene(viewport.rect())`` 得到视图坐标 AABB →
``SceneProjection.inverse_rect`` 反投影成 page 坐标 AABB（AGV 轴交换 / 符号
翻转都由它处理，别手算）。反过来，``change_size`` 的入参是 page 宽高，要先
用 ``proj.size()`` 换成 ``fit_widget_size`` 认识的视图像素尺寸。

零污染
======
``set_page_size`` 会写 ``_page["width"/"height"]``，``setPos`` 的
``itemChange`` 会把 ``_geo_dirty`` 置真——两者都会让 ``page_data()`` 与磁盘
JSON 不等。这里沿用 ``App_test_fixture.CleanVisuals`` 的口径：装载后先抓一份
``_page`` 快照，每次同步完把快照还原、``mark_clean()``、清 ``scene._modified``。
运行态的所有几何都读实时 Qt 变换（``sceneBoundingRect`` / ``boundingRect`` /
``mapToScene``），不依赖被还原的记录，所以画面和存盘数据互不干扰。

触发
====
视图变换没有统一的 Qt 信号，三重入口保证「不管怎么缩放」都跟得上：

1. ``RuntimeView.on_viewport_resized`` 包装（窗口 / 视口 resize，保留原来的
   快照预热回调）；
2. 两根滚动条的 ``valueChanged`` / ``rangeChanged`` + viewport 的
   ``Wheel`` / ``Resize`` 事件（滚轮缩放、拖动平移）；
3. 低频轮询（默认 50ms）比对视图状态签名，兜住 ``view.scale()`` /
   ``fitInView()`` / 外部窗口嵌入这类不发事件的变换。

所有入口都走 ``schedule()`` 合并到一次 ``sync()``；目标矩形没变就直接返回，
既不会抖动也不会自激（背景变大不会反过来改视口变换）。
"""

from __future__ import annotations

import copy
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QSizeF, QTimer

from . import pop_pick_config as cfg

try:
    _WHEEL = QEvent.Type.Wheel
    _RESIZE = QEvent.Type.Resize
    _MOUSE_RELEASE = QEvent.Type.MouseButtonRelease
    _SHOW = QEvent.Type.Show
except AttributeError:  # pragma: no cover - 旧式枚举别名
    _WHEEL, _RESIZE, _MOUSE_RELEASE, _SHOW = (
        QEvent.Wheel, QEvent.Resize, QEvent.MouseButtonRelease, QEvent.Show)


class BackgroundElement:
    """「背景」图元的一对几何接口：``change_pos`` / ``change_size``。

    门面只记名字、每次现查 :class:`RuntimeElement`（换页后 id 可能变，复用
    同一个门面不会持有已析构的 Qt 对象）。几何改动一律委托给 element 的
    ``change_position`` / ``fit_widget_size``，承载控件由它们顺带对齐。
    """

    def __init__(self, stage, name: str = cfg.BACKGROUND_NAME) -> None:
        self._stage = stage
        self._name = str(name)

    @property
    def name(self) -> str:
        return self._name

    def element(self):
        return self._stage.element_of(self._name)

    def item(self):
        element = self.element()
        return element.item() if element is not None else None

    def item_id(self) -> Optional[int]:
        element = self.element()
        return element.item_id if element is not None else None

    def rect(self) -> QRectF:
        """当前 page 包围盒（实时 Qt 变换，不是 ``_page`` 里的旧记录）。"""
        element = self.element()
        return element.sceneBoundingRect() if element is not None else QRectF()

    def change_pos(self, top_left: QPointF) -> None:
        """把背景左上角挪到 ``top_left``（page 坐标）。"""
        element = self.element()
        if element is not None:
            element.change_position(QPointF(top_left))

    def change_size(self, width: float, height: float) -> None:
        """把背景尺寸改成 ``width×height``（page 坐标）。

        DesignerV2 起 page 坐标 == 场景坐标（SceneProjection 已删除），
        ``fit_widget_size`` 收的像素尺寸就是 page 宽高本身，不用再换算。
        """
        element = self.element()
        it = self.item()
        if element is None or it is None:
            return
        element.fit_widget_size(QSizeF(float(width), float(height)))


class BackgroundFitter(QObject):
    """把 :class:`BackgroundElement` 的实时矩形钉在「当前可见 page 矩形」上。

    :param stage: ``RuntimeStage``；构造时页面可以还没装载。
    """

    def __init__(self, stage, parent: Optional[QObject] = None, *,
                 name: str = cfg.BACKGROUND_NAME,
                 overscan: float = cfg.BACKGROUND_OVERSCAN,
                 poll_ms: int = cfg.BACKGROUND_POLL_MS) -> None:
        super().__init__(parent or stage)
        self._stage = stage
        self._bg = BackgroundElement(stage, name)
        self._overscan = max(0.0, float(overscan))
        self._snapshot: Optional[dict] = None
        self._last_rect = QRectF()
        self._last_state: Optional[tuple] = None
        self._syncing = False
        self._released = False

        view = stage.view
        #: 保留原有回调（PopPick 挂的是 PageSnapshots.schedule_prewarm）
        self._prev_resized = view.on_viewport_resized

        def on_resized():
            if callable(self._prev_resized):
                self._prev_resized()
            self.schedule()

        self._on_resized = on_resized
        view.on_viewport_resized = on_resized

        self._bars = (view.horizontalScrollBar(), view.verticalScrollBar())
        for bar in self._bars:
            bar.valueChanged.connect(self._on_view_changed)
            bar.rangeChanged.connect(self._on_view_changed)
        self._filter_targets = (view, view.viewport())
        for obj in self._filter_targets:
            obj.installEventFilter(self)

        self._sync_timer: Optional[QTimer] = None
        self._poll = QTimer(self)
        self._poll.setInterval(max(10, int(poll_ms)))
        self._poll.timeout.connect(self._check_view)
        self._poll.start()

    # -- 查询 -----------------------------------------------------------
    @property
    def element(self) -> BackgroundElement:
        return self._bg

    def is_background(self, item) -> bool:
        """给窗口的「适应窗口」包围盒用：背景不参与取景，否则自激变小。"""
        if item is None:
            return False
        element = self._bg.element()
        return element is not None and item is element

    def visible_page_rect(self) -> QRectF:
        """当前视口在 page 坐标下覆盖的矩形（未含 overscan）。"""
        view = self._stage.view
        vp = view.viewport().rect()
        if vp.width() < 8 or vp.height() < 8:
            return QRectF()
        # DesignerV2 没有投影层，``mapToScene`` 出来的就是 page 坐标。
        return QRectF(view.mapToScene(vp).boundingRect())

    def target_rect(self) -> QRectF:
        """本次同步的目标矩形（可见矩形外扩一圈，防亚像素露边）。"""
        visible = self.visible_page_rect()
        if visible.isEmpty():
            return QRectF()
        margin = max(visible.width(), visible.height()) * self._overscan
        return visible.adjusted(-margin, -margin, margin, margin)

    def last_rect(self) -> QRectF:
        return QRectF(self._last_rect)

    # -- 快照（零污染） --------------------------------------------------
    def capture(self) -> bool:
        """换页 / 首次装载后抓一份设计期 ``_page`` 快照。"""
        it = self._bg.item()
        if it is None:
            return False
        self._snapshot = copy.deepcopy(dict(it._page))
        self._last_rect = QRectF()
        return True

    def _restore(self) -> None:
        """把 ``set_page_size`` / ``setPos`` 写进 ``_page`` 的痕迹抹掉。"""
        it = self._bg.item()
        if it is None:
            return
        if self._snapshot is not None:
            it._page.clear()
            it._page.update(copy.deepcopy(self._snapshot))
        it.mark_clean()
        scene = self._stage.scene
        if hasattr(scene, "_modified"):
            scene._modified = False

    # -- 同步 -----------------------------------------------------------
    def schedule(self) -> None:
        """合并连续变化到下一轮事件循环，避免拖动时逐像素重算。"""
        if self._released:
            return
        if self._sync_timer is None:
            self._sync_timer = QTimer(self)
            self._sync_timer.setSingleShot(True)
            self._sync_timer.timeout.connect(self.sync)
        self._sync_timer.start(cfg.BACKGROUND_SYNC_MS)

    def sync(self) -> bool:
        """按当前取景重设背景的位置与尺寸；目标没变则直接返回。

        顺序不能反：``change_size`` 绕中心缩放，会改变左上角；先定尺寸再把
        左上角挪到目标点，最终矩形才正好是 ``target_rect()``。
        """
        if self._syncing or self._released:
            return False
        it = self._bg.item()
        if it is None:
            return False
        target = self.target_rect()
        if target.isEmpty():
            return False
        if self._same_rect(self._last_rect, target):
            return False
        if self._snapshot is None and not self.capture():
            return False

        self._syncing = True
        try:
            self._bg.change_size(target.width(), target.height())
            self._bg.change_pos(target.topLeft())
            self._restore()
            self._last_rect = QRectF(target)
        finally:
            self._syncing = False
        return True

    @staticmethod
    def _same_rect(a: QRectF, b: QRectF) -> bool:
        if a.isEmpty():
            return False
        tol = max(0.25, 1e-4 * max(abs(b.width()), abs(b.height())))
        return (abs(a.left() - b.left()) <= tol
                and abs(a.top() - b.top()) <= tol
                and abs(a.width() - b.width()) <= tol
                and abs(a.height() - b.height()) <= tol)

    # -- 变化检测 -------------------------------------------------------
    def _on_view_changed(self, *_args) -> None:
        self.schedule()

    def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
        if event.type() in (_WHEEL, _RESIZE, _MOUSE_RELEASE, _SHOW):
            self.schedule()
        return False        # 只观察，不吞事件

    def _view_state(self) -> tuple:
        """视图变换签名：便宜、能覆盖 scale / fitInView / 平移 / resize。"""
        view = self._stage.view
        try:
            t = view.transform()
            vp = view.viewport().rect()
            origin = view.mapToScene(QPoint(0, 0))
            h, v = self._bars
            return (
                vp.width(), vp.height(),
                round(t.m11(), 6), round(t.m12(), 6),
                round(t.m21(), 6), round(t.m22(), 6),
                round(t.dx(), 3), round(t.dy(), 3),
                round(origin.x(), 3), round(origin.y(), 3),
                h.value(), h.minimum(), h.maximum(),
                v.value(), v.minimum(), v.maximum(),
            )
        except RuntimeError:
            return ()

    def _check_view(self) -> None:
        if self._released:
            return
        state = self._view_state()
        if state and state != self._last_state:
            self._last_state = state
            self.schedule()

    # -- 生命周期 -------------------------------------------------------
    def release(self) -> None:
        """关窗：停定时器、摘过滤器、断开信号、还原视图回调。"""
        if self._released:
            return
        self._released = True
        self._poll.stop()
        if self._sync_timer is not None:
            self._sync_timer.stop()
        for obj in self._filter_targets:
            try:
                obj.removeEventFilter(self)
            except RuntimeError:
                pass
        for bar in self._bars:
            for sig in (bar.valueChanged, bar.rangeChanged):
                try:
                    sig.disconnect(self._on_view_changed)
                except (RuntimeError, TypeError):
                    pass
        view = self._stage.view
        if view.on_viewport_resized is self._on_resized:
            view.on_viewport_resized = self._prev_resized

    def report(self) -> str:
        r = self._last_rect
        return (f"BackgroundFitter(name={self._bg.name!r}, "
                f"rect=({r.x():.1f},{r.y():.1f},{r.width():.1f}x{r.height():.1f}), "
                f"clean={self._snapshot is not None})")
