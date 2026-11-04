"""嵌入式 QWidget 的承载层：overlay ``QGraphicsView`` + ``QGraphicsProxyWidget``。

为什么需要这一层
----------------
场景是纯自绘 ``QWidget``（不是 ``QGraphicsView``），真实控件只能作为子窗口挂在
场景上。裸 ``QWidget`` 做宿主有两个绕不过的限制：

1. **文字不跟随缩放**：``setGeometry`` 只改像素宽高，字号是绝对量（9pt 恒定为
   9pt），缩放到 2x 就是"框大字小"；
2. **无法旋转**：``QWidget`` 不支持任意角度变换，只能水平摆放。

把每个控件包进一个透明 ``QGraphicsView``（内部一个 ``QGraphicsProxyWidget``）
可以一次解决这两点：

- 缩放交给 ``QGraphicsView.setTransform``，控件由 painter 变换渲染，文字是矢量
  缩放的，放大后依然锐利；
- 旋转交给 proxy item（绕控件中心）；
- 命中测试、光标定位、文本选中、隐式 grab、双击识别、焦点、输入法全部由 Qt
  原生完成——**不需要手写逆变换派发**。

验证记录（含旋转 30° 命中、光标定位、键盘输入、IME 事件、包围盒空白角透传）
见 ``tools/overlay_widget_probe.py``。

几何约定
--------
- ``design_size``：scale=1.0 时的像素尺寸（场景视图单位），控件本体始终按这个
  尺寸摆放，不随缩放变形；
- ``scale``：交给 view 的变换，等于场景的 ``scale_factor``；
- ``angle``：度，与 ``painter.rotate(-angle)`` 同向（Qt 里正角度为顺时针）；
- ``center``：控件中心在**宿主窗口**坐标系里的位置，view 的 geometry 取"旋转
  后包围盒 × scale"并以该点为中心。
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QSizeF, Qt
from PySide6.QtGui import QMouseEvent, QPainter, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsItem,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)


class EmbeddedWidgetLayer(QObject):
    """一个真实 ``QWidget`` 的透明视图载体。

    除了承载控件，还负责一件事：**把"在控件上按住左键拖动画布"这件事还给
    场景**。场景的平移是 ``offset += 鼠标位移``（见 ``myGraphicsScene`` 的
    ``mousePressEvent``/``mouseMoveEvent``），但控件矩形上的鼠标事件被这个
    overlay 视图整体接走了，场景收不到，于是"空白处能拖、控件上拖不动"。

    这里的处理是"延迟派发"：

    - 左键按下先扣住不转发；
    - 移动距离超过 ``QApplication.startDragDistance()`` → 判定为拖动画布，
      把位移交给场景的 ``offset``，press 永不派发，控件不会先选中一次文本；
    - 松开时若没超过阈值 → 判定为点击，补发 press + release 给视图，控件
      照常获得焦点 / 响应点击。

    滚轮不拦（让 QGraphicsView 自己 ignore 后冒泡给场景缩放）。
    """

    # 承载层可能被 dispose() 回收，以下 Qt 对象在回收后为 None，
    # 使用处统一按 Optional 处理。
    view: QGraphicsView | None
    inner_scene: QGraphicsScene | None
    proxy: QGraphicsProxyWidget | None
    widget: QWidget | None

    _host: QWidget
    _center: QPointF
    _design: QSizeF
    _scale: float
    _angle: float
    _visible: bool
    _interactive: bool
    _viewport: QWidget | None
    _press_pos: QPoint | None
    _press_global: QPoint | None
    _press_pending: bool
    _panning: bool
    _pan_last: QPoint | None
    _injecting: bool
    _last_click_ms: float
    _last_click_pos: QPoint | None

    def __init__(self, host: QWidget) -> None:
        # 不挂 parent：层由图元显式 dispose() 回收（parent=host 时 scene 销毁
        # 会在 C++ 侧提前删掉本对象，Python 侧对 self.view 的访问就会炸）。
        super().__init__()
        self._host = host

        self._center = QPointF(0.0, 0.0)
        self._design = QSizeF(1.0, 1.0)
        self._scale = 1.0
        self._angle = 0.0
        self._visible = False
        # 只读模式：设计态下控件只作展示，鼠标事件穿透给场景，保证图元仍可
        # 选中/拖动/缩放。运行时置 False 恢复可交互。
        self._interactive = True

        view = QGraphicsView(host)
        view.setObjectName("embeddedWidgetView")
        view.setFrameShape(QFrame.NoFrame)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # 必须是可聚焦的：QGraphicsView 的键盘事件入口就是它自己，只有 view 拿到
        # 真实（系统级）焦点，keyPressEvent 才会经 view → inner_scene → proxy
        # 转发进被承载的控件。设成 NoFocus 时点击只会给 proxy 一个"逻辑焦点"
        # （widget.hasFocus() 为 True），系统焦点仍留在主场景，按键全被主场景吃掉，
        # 表现为"点进去但打不了字"。
        # 点击取焦（ClickFocus）+ Tab 取焦（StrongFocus 的超集）；这里用
        # StrongFocus 是因为部分控件（如 QLineEdit）需要 Tab 在 proxy 内部传递。
        view.setFocusPolicy(Qt.StrongFocus)
        view.viewport().setFocusPolicy(Qt.StrongFocus)
        view.setStyleSheet(
            "QGraphicsView { background: transparent; border: none; }"
        )
        view.viewport().setAutoFillBackground(False)
        view.setAttribute(Qt.WA_TranslucentBackground, True)
        view.setRenderHints(
            QPainter.Antialiasing
            | QPainter.TextAntialiasing
            | QPainter.SmoothPixmapTransform
        )
        # 控件自己会重绘（光标闪烁等），整屏刷新最省心。
        view.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        view.setOptimizationFlag(QGraphicsView.DontSavePainterState, True)
        view.hide()
        self.view = view

        self.inner_scene = QGraphicsScene(view)
        view.setScene(self.inner_scene)

        self.proxy = None
        self.widget = None

        # --- 左键拖动平移相关状态 -------------------------------------
        self._viewport = view.viewport()
        self._viewport.installEventFilter(self)
        self._press_pos: QPoint | None = None      # 按下点（viewport 坐标）
        self._press_global: QPoint | None = None   # 按下点（全局坐标）
        self._press_pending = False                # 已按下、未决定是点击还是拖动
        self._panning = False                      # 已进入拖动画布状态
        self._pan_last: QPoint | None = None       # 上一次的宿主坐标
        self._injecting = False                    # 正在补发合成事件，避免自拦截
        self._last_click_ms = 0                    # 上次合成点击的时间戳
        self._last_click_pos: QPoint | None = None # 上次合成点击的位置

    # ------------------------------------------------------------------
    # 控件
    # ------------------------------------------------------------------
    def set_widget(self, widget: QWidget | None) -> None:
        """替换被承载的控件（工厂重建时调用）。"""
        self.clear_widget()
        if widget is None:
            return
        # 关键：proxy 只接管「无父」控件。若先把控件 setParent 到 viewport，
        # addWidget 会静默失败（proxy.widget() 为 None），控件退化成一个普通
        # 子窗口——不受 proxy 的旋转/缩放变换影响，看起来就是"控件不转"。
        widget.setParent(None)
        # 放开控件自身的尺寸约束。多数控件带有 minimumSizeHint（QPushButton
        # 的宽度就是 80），proxy.resize 遇到未显式设置 minimumSize 的控件会
        # 按 sizeHint 撑开包围盒，结果设计尺寸比实际大、控件被裁一角。
        # 显式给 (1,1) 即可越过 sizeHint 的限制（给 (0,0) 无效）。
        widget.setMinimumSize(1, 1)
        widget.setMaximumSize(16777215, 16777215)
        proxy = self.inner_scene.addWidget(widget)
        if proxy.widget() is not widget:
            # 兜底：真接管失败时至少不让控件游离在场景外。
            widget.setParent(self.view.viewport())
        # NoCache：每次重绘都真渲染，放大时文字更锐。
        proxy.setCacheMode(QGraphicsItem.NoCache)
        proxy.setTransformOriginPoint(
            widget.width() / 2.0, widget.height() / 2.0
        )
        self.proxy = proxy
        self.widget = widget
        self._apply_transform()
        self._apply_interactive()

    def clear_widget(self) -> None:
        proxy = self.proxy
        self.proxy = None
        if proxy is None:
            self.widget = None
            return
        try:
            # setWidget(None) 让 proxy 放弃对控件的所有权（内部走 deleteLater），
            # 之后 removeItem 归还 proxy 的所有权给 Python 侧，可安全回收。
            proxy.setWidget(None)
        except RuntimeError:
            pass
        try:
            self.inner_scene.removeItem(proxy)
        except RuntimeError:
            pass
        self.widget = None

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------
    def apply(
        self,
        center: QPointF,
        design_size: QSizeF,
        scale: float,
        angle: float,
    ) -> None:
        """同步中心点 / 设计尺寸 / 缩放 / 角度。"""
        self._center = QPointF(center)
        self._design = QSizeF(max(1.0, design_size.width()),
                              max(1.0, design_size.height()))
        self._scale = max(0.05, float(scale))
        self._angle = float(angle)
        self._apply_transform()

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        view = self._require_view()
        if self.proxy is None:
            view.hide()
            return
        if self._visible:
            view.show()
            view.raise_()
        else:
            view.hide()

    def set_interactive(self, interactive: bool) -> None:
        """控制控件是否可交互。

        只读（``interactive=False``）时，视图与控件都设
        ``WA_TransparentForMouseEvents``，鼠标事件穿透到场景，控件仅作展示；
        同时关闭 eventFilter 的"左键拖动画布"延迟派发。切回可交互时恢复。
        """
        self._interactive = bool(interactive)
        self._apply_interactive()

    def _apply_interactive(self) -> None:
        view = self.view
        if view is not None:
            view.setAttribute(Qt.WA_TransparentForMouseEvents, not self._interactive)
            viewport = view.viewport()
            if viewport is not None:
                viewport.setAttribute(
                    Qt.WA_TransparentForMouseEvents, not self._interactive
                )
        widget = self.widget
        if widget is not None:
            widget.setAttribute(
                Qt.WA_TransparentForMouseEvents, not self._interactive
            )
            # 只读态再关掉键盘焦点策略，避免 Tab 焦点误入一个"看起来可交互"的控件。
            widget.setFocusPolicy(
                Qt.FocusPolicy.StrongFocus
                if self._interactive
                else Qt.FocusPolicy.NoFocus
            )

    def raise_view(self) -> None:
        view = self.view
        if view is not None and view.isVisible():
            view.raise_()

    def is_active(self) -> bool:
        return self.proxy is not None and self.widget is not None

    def is_visible(self) -> bool:
        """当前是否处于"要求显示"状态（供宿主在几何修正后补回显示）。"""
        return self._visible

    # ------------------------------------------------------------------
    # 鼠标：点一下进控件，拖一下平移画布
    # ------------------------------------------------------------------
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is not self._viewport or self._injecting:
            return False
        # 只读态（设计模式展示）：不拦截任何事件，让场景照常处理选中/拖动。
        if not self._interactive:
            return False
        # 下面只关心鼠标事件（上面已按 QEvent.Type 过滤），这里收窄类型。
        if not isinstance(event, QMouseEvent):
            return False

        etype = event.type()

        if (
            etype == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            # 先扣住：此刻还不知道是"点控件"还是"拖画布"，等松开或超阈值再定。
            self._press_pos = event.position().toPoint()
            self._press_global = event.globalPosition().toPoint()
            self._press_pending = True
            self._panning = False
            return True

        if etype == QEvent.Type.MouseMove and self._press_pending:
            if (
                not self._panning
                and self._press_pos is not None
                and self._press_global is not None
            ):
                # 不看 event.buttons()：press 已经被这里扣下，按键状态的唯一
                # 真值就是 _press_pending（合成 / 测试事件里的 buttons 未必带上）。
                moved = (
                    event.position().toPoint() - self._press_pos
                ).manhattanLength()
                if moved >= QApplication.startDragDistance():
                    self._start_pan(self._press_global)
            if self._panning:
                self._move_pan(event.globalPosition().toPoint())
            return True

        if (
            etype == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            if not self._press_pending:
                return False
            self._press_pending = False
            if self._panning:
                self._panning = False
                self._end_pan()
                return True
            if self._press_pos is not None:
                self._dispatch_click(self._press_pos)
            return True

        return False

    def _start_pan(self, global_pos: QPoint) -> None:
        """进入拖动画布状态，复用场景自己的 ``panning`` / ``offset`` 约定。"""
        host = self._host
        # 宿主（场景）可能禁止手动平移（运行态钉死视图时常见）。禁用时保持
        # 未进入 pan 状态，按键仍按"点击控件"处理，release 时照常派发点击。
        pan_checker = getattr(host, "is_pan_enabled", None)
        if callable(pan_checker) and not pan_checker():
            return
        self._panning = True
        # 拖动过就不该再和上一次点击凑成双击。
        self._last_click_pos = None
        self._last_click_ms = 0
        self._pan_last = self._host.mapFromGlobal(global_pos)
        if hasattr(self._host, "panning"):
            setattr(self._host, "panning", True)
        viewport = self._viewport
        if viewport is not None:
            try:
                viewport.setCursor(Qt.CursorShape.ClosedHandCursor)
            except RuntimeError:
                pass

    def _move_pan(self, global_pos: QPoint) -> None:
        host = self._host
        pos = host.mapFromGlobal(global_pos)
        if self._pan_last is None:
            self._pan_last = pos
            return
        delta = pos - self._pan_last
        if delta.isNull():
            return
        self._pan_last = pos

        offset = getattr(host, "offset", None)
        if offset is None:  # 宿主不是场景，放弃平移
            return
        # 宿主是场景类，offset/panning/last_pos 不属于 QWidget 接口，
        # 用 setattr 显式写入，避免把宿主类型扩成 Any。
        setattr(host, "offset", offset + QPointF(delta))
        if hasattr(host, "last_pos"):
            setattr(host, "last_pos", pos)
        if hasattr(host, "update_coordinate"):
            host.update_coordinate()
        host.update()

        # 所有承载视图的像素几何都跟着 offset 变，必须逐个重算，
        # 否则拖动画布时控件会钉在原地。
        sync = getattr(host, "_sync_embedded_widgets_geometry", None)
        if callable(sync):
            sync()

    def _end_pan(self) -> None:
        if hasattr(self._host, "panning"):
            setattr(self._host, "panning", False)
        self._pan_last = None
        viewport = self._viewport
        if viewport is not None:
            try:
                viewport.unsetCursor()
            except RuntimeError:
                pass

    def _dispatch_click(self, pos: QPoint) -> None:
        """把被扣住的左键补成一次完整点击，交给视图去派发给控件。

        只发 press + release：QGraphicsView 自己会做命中测试、设焦点项、
        光标定位，所以不需要手写逆变换。
        """
        viewport = self._viewport
        view = self.view
        assert viewport is not None, "承载层已 dispose，viewport 不可用"
        self._injecting = True
        try:
            # 真实点击时窗口系统会先给 view 取焦；这里是自己补发事件，得手动
            # 补上，否则 QGraphicsScene 的焦点项落不到 proxy 里的控件上
            # （表现为点进去了但打不了字）。
            if view is not None and not view.hasFocus():
                view.setFocus(Qt.FocusReason.MouseFocusReason)
            widget = self.widget
            if (
                widget is not None
                and widget.focusPolicy() != Qt.FocusPolicy.NoFocus
                and not widget.hasFocus()
            ):
                # 先给控件焦点再派发 press：QGraphicsProxyWidget 处理 press 时
                # 会按 scene 的焦点项重新同步一次焦点，事后再设容易被它覆盖。
                widget.setFocus(Qt.FocusReason.MouseFocusReason)

            sequence = [(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton)]
            now = time.monotonic()
            interval = QApplication.styleHints().mouseDoubleClickInterval() / 1000.0
            if (
                self._last_click_pos is not None
                and (now - self._last_click_ms) <= interval
                and (pos - self._last_click_pos).manhattanLength() <= 4
            ):
                # 第二次点击要补一个双击事件：真实双击在窗口系统层就被这里
                # 扣下了，不补的话 QLineEdit 双击选词、列表 doubleClicked 都会丢。
                sequence.append(
                    (QEvent.Type.MouseButtonDblClick, Qt.MouseButton.LeftButton)
                )
                self._last_click_pos = None
                self._last_click_ms = 0
            else:
                self._last_click_pos = QPoint(pos)
                self._last_click_ms = now
            sequence.append((QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton))

            for etype, buttons in sequence:
                synthesized = QMouseEvent(
                    etype,
                    QPointF(pos),
                    QPointF(viewport.mapToGlobal(pos)),
                    Qt.MouseButton.LeftButton,
                    buttons,
                    Qt.KeyboardModifier.NoModifier,
                )
                QApplication.sendEvent(viewport, synthesized)
        finally:
            self._injecting = False
        self._ensure_widget_focus()

    def _ensure_widget_focus(self) -> None:
        """补发点击后，把焦点真正落到控件本体上。

        proxy 成为 scene 的焦点项（``focusItem() == proxy``）时，Qt 并不总会
        同步 ``widget.setFocus()``；而键盘事件要进控件，靠的正是控件自身的
        焦点。这一步只补"proxy 已在焦点、控件还没焦点"的情况，不强行改
        控件的焦点策略。
        """
        widget = self.widget
        proxy = self.proxy
        if widget is None or proxy is None:
            return
        if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
            return
        try:
            if proxy.hasFocus() and not widget.hasFocus():
                widget.setFocus(Qt.FocusReason.MouseFocusReason)
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _apply_transform(self) -> None:
        width = self._design.width()
        height = self._design.height()

        widget = self.widget
        proxy = self.proxy
        if proxy is not None:
            # proxy.resize 会同步推进控件 geometry 与自身的 boundingRect；
            # 只改 widget 尺寸的话，proxy 要等一轮事件循环才更新包围盒，
            # 几何计算会拿到旧尺寸。
            proxy.resize(width, height)
            proxy.setTransformOriginPoint(width / 2.0, height / 2.0)
            # 与 rect_element / painter.rotate(-angle) 同向：Qt 里正角度为顺时针。
            proxy.setRotation(-self._angle)

        self._require_view().setTransform(
            QTransform().scale(self._scale, self._scale)
        )
        self._update_geometry()

    def _update_geometry(self) -> None:
        proxy = self.proxy
        view = self._require_view()
        if proxy is None:
            view.hide()
            return
        bbox = proxy.mapToScene(proxy.boundingRect()).boundingRect()
        view.setSceneRect(bbox)

        size = bbox.size() * self._scale
        geo = QRect(
            int(round(self._center.x() - size.width() / 2.0)),
            int(round(self._center.y() - size.height() / 2.0)),
            max(1, int(round(size.width()))),
            max(1, int(round(size.height()))),
        )
        view.setGeometry(geo)
        if self._visible:
            view.show()

    def _require_view(self) -> QGraphicsView:
        """取承载视图；已 dispose 时视为编码错误，显式失败而不是静默。"""
        view = self.view
        if view is None:
            raise RuntimeError("EmbeddedWidgetLayer 已 dispose，view 不可用")
        return view

    # ------------------------------------------------------------------
    # 回收
    # ------------------------------------------------------------------
    def dispose(self) -> None:
        """销毁视图与内部场景（图元删除 / 页面切换 / 程序退出时调用）。"""
        self.clear_widget()
        viewport = self._viewport
        self._viewport = None
        if viewport is not None:
            try:
                viewport.removeEventFilter(self)
            except RuntimeError:
                pass
        view = self.view
        self.view = None
        if view is None:
            return
        try:
            view.setScene(None)
            self.inner_scene.deleteLater()
            view.setParent(None)
            view.deleteLater()
        except RuntimeError:
            pass
        self.inner_scene = None
        self.deleteLater()
