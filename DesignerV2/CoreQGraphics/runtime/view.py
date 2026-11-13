"""统一运行态：场景点击路由 :class:`RuntimeScene` 与视图 :class:`RuntimeView`。

三套旧实现的视图层做的事其实一模一样，只是各写了一份：

* 关掉设计网格 / 捕捉标记 / 选中框 / 滚动条 / 1px 边框；
* 把 viewport 的 ``QPalette.Base`` 改成 ``Window``（页面背景带 alpha 时，
  QGraphicsView 默认按白色合成，与旧自绘 QWidget 差 4~8 级像素值）；
* 导航默认全关，右键吞掉，键盘只放行空格（且仅在导航开启时）；
* 按 page JSON 保存的 ``sceneRect`` 等比取景，**允许放大**。

差异只有两处，做成显式选项而不强行合并：

``fit_mode``
  ``"fit"`` —— 每次视口变化按 ``sceneRect`` 重算缩放（rack 总览页口径）；
  ``"pin"`` —— 基类 ``setResizeAnchor(NoAnchor)`` 已钉住视口左上角场景点，
  resize 不动变换（safety 口径，底部 dock 展开时画面不上移）；
  ``"none"`` —— 完全交给调用方。

坐标换算
  ``window_to_page`` / ``sceneToView`` / ``viewToScene`` 仍提供旧 API，
  但场景坐标 = page 坐标，不再做任何投影。

另外保留了一组旧 API 别名（``refresh_embedded_widgets`` /
``release_embedded_widgets`` / ``delete_all_elements`` / ``load_scene_file`` /
``set_scene_mode`` / ``scene_manager`` / ``double_clicked_without_group``），
让既有窗口代码可以先原样接进来，再逐步迁到 :class:`~.stage.RuntimeStage`。
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPalette
from PySide6.QtWidgets import QFrame, QGraphicsItem, QGraphicsView, QWidget

try:
    _ITEM_MOVABLE = QGraphicsItem.GraphicsItemFlag.ItemIsMovable
except AttributeError:  # pragma: no cover - 旧式枚举别名
    _ITEM_MOVABLE = QGraphicsItem.ItemIsMovable

if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

if __package__ in (None, ""):
    from DesignerV2.CoreQGraphics import GraphicsScene, GraphicsView  # noqa: E402
else:
    from .. import GraphicsScene, GraphicsView  # noqa: E402

try:
    _KEEP_RATIO = Qt.AspectRatioMode.KeepAspectRatio
    _NO_BUTTONS = Qt.MouseButton.NoButton
    _ALL_BUTTONS = Qt.MouseButton.AllButtons
except AttributeError:  # pragma: no cover - 旧式枚举别名
    _KEEP_RATIO = Qt.KeepAspectRatio
    _NO_BUTTONS = Qt.NoButton
    _ALL_BUTTONS = Qt.AllButtons


class RuntimeScene(GraphicsScene):
    """在核心场景上只加一层运行态点击路由。

    命中按 z 倒序取最上层可交互图元；按下记锚点、释放时仍在图元内才算一次
    点击（旧 ``_find_event_group_at`` + ``handle_mouse_release(inside)`` 时序，
    避免「按下后拖出去松手」误触发）。命中用的是 ``event.scenePos()``，
    即 Qt 场景坐标，与 page 坐标同源。
    """

    doubleClickedEmpty = Signal()
    elementClicked = Signal(object)          # RuntimeElement

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.registry = None
        self._pressed = None
        self.hit_types: tuple[str, ...] | None = None
        self.interactive_only = True

    def attach_registry(self, registry) -> None:
        self.registry = registry

    def hit_element(self, scene_pos: QPointF):
        if self.registry is None or not self.is_run_mode:
            return None
        for element in reversed(self.registry.sorted()):
            if self.hit_types and element.TYPE not in self.hit_types:
                continue
            if self.interactive_only and not element.is_interactive():
                continue
            if not element.effective_visibility():
                continue
            if element.contains_view_pos(scene_pos):
                return element
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        super().mousePressEvent(event)
        self._pressed = None
        if event.button() == Qt.LeftButton and self.is_run_mode:
            self._pressed = self.hit_element(event.scenePos())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        pressed, self._pressed = self._pressed, None
        if event.button() != Qt.LeftButton or pressed is None:
            return
        if pressed.contains_view_pos(event.scenePos()):
            # 只发一次：handle_mouse_release(True) 内部也会 emit clicked
            pressed.clicked.emit()
            self.elementClicked.emit(pressed)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.LeftButton and self.is_run_mode:
            if self.hit_element(event.scenePos()) is None:
                self.doubleClickedEmpty.emit()


class RuntimeView(GraphicsView):
    """运行态视图：只读显示 + 取景 + 坐标换算 + 旧 API 兼容门面。"""

    double_clicked_without_group = Signal()

    def __init__(self, scene: RuntimeScene | None = None, parent=None, *,
                 fit_mode: str = "fit", navigation: bool = False,
                 stage=None) -> None:
        if fit_mode not in ("fit", "pin", "none"):
            raise ValueError("fit_mode 必须是 fit / pin / none")
        super().__init__(scene or RuntimeScene(), parent)
        self.stage = stage
        self.fit_mode = fit_mode
        self.scene_manager = None
        self.update_callback = None       # 旧入口会显式清空它
        self.on_viewport_resized = None   # 外部想接管取景时挂这里
        self.setDragMode(GraphicsView.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.StrongFocus)
        # 页面背景 alpha 按 Base 合成；旧自绘 QWidget 的底色是 Window
        palette = self.viewport().palette()
        palette.setColor(QPalette.Base, palette.color(QPalette.Window))
        self.viewport().setPalette(palette)
        self.show_grid = False
        self.show_ids = False
        self.snap.show_markers = False
        if hasattr(self.snap, "grid_enabled"):
            self.snap.grid_enabled = False
        self.set_canvas_navigation_enabled(bool(navigation))
        scene_obj = self.scene()
        if hasattr(scene_obj, "doubleClickedEmpty"):
            scene_obj.doubleClickedEmpty.connect(
                self.double_clicked_without_group)

    # -- 取景 -----------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if callable(self.on_viewport_resized):
            self.on_viewport_resized()
        elif self.fit_mode == "fit":
            self.fit_scene()

    def fit_scene(self) -> bool:
        """按 page JSON 的 ``sceneRect`` 等比铺满视口（允许放大，rack 口径）。"""
        scene = self.scene()
        if scene is None:
            return False
        rect = scene.view_scene_rect()
        avail = self.viewport().rect()
        if avail.width() < 8 or avail.height() < 8:
            return False          # 布局还没跑完，别按极小视口算缩放
        if rect.isEmpty() or rect.width() <= 0 or rect.height() <= 0:
            # sceneRect 没保存（旧场景常见）：退回所有图元包围盒并集。
            target = scene.fit_rect()
        else:
            # sceneRect 保存值就是 Qt 场景坐标，直接取景。
            target = QRectF(rect)
        if target.width() <= 0 or target.height() <= 0:
            return False
        scale = min(avail.width() / target.width(),
                    avail.height() / target.height())
        self.resetTransform()
        self.scale(scale, scale)
        self.centerOn(target.center())
        self.refresh_embedded_widgets()
        return True

    def set_view_scene_rect(self, rect: QRectF) -> bool:
        """PopPick 口径：把一段场景坐标矩形铺满视口。"""
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            return False
        self.fitInView(rect, _KEEP_RATIO)
        self.refresh_embedded_widgets()
        return True

    def fit_content(self) -> None:  # noqa: N802
        super().fit_content()
        self.refresh_embedded_widgets()

    # -- 坐标换算（场景坐标 = page 坐标，旧 API 保留为恒等） ----------------
    def sceneToView(self, point: QPointF) -> QPointF:  # noqa: N802
        return QPointF(point)

    def viewToScene(self, point: QPointF) -> QPointF:  # noqa: N802
        return QPointF(point)

    def window_to_page(self, window_pos: QPointF) -> QPointF:
        """视口像素 → page 场景坐标（保留小数，避免放大时累积偏差）。"""
        x, y = float(window_pos.x()), float(window_pos.y())
        ip = QPoint(int(round(x)), int(round(y)))
        scene_pt = QPointF(self.mapToScene(ip))
        inv, ok = self.transform().inverted()
        if ok:
            origin = inv.map(QPointF(0.0, 0.0))
            delta = inv.map(QPointF(x - ip.x(), y - ip.y())) - origin
            scene_pt = QPointF(scene_pt.x() + delta.x(),
                               scene_pt.y() + delta.y())
        return QPointF(scene_pt)

    # -- 输入门控 -------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            event.accept()
            return
        if self.is_pan_event(event):
            GraphicsView.mousePressEvent(self, event)
            return
        QGraphicsView.mousePressEvent(self, event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if getattr(self, "_panning", False):
            GraphicsView.mouseMoveEvent(self, event)
            return
        QGraphicsView.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            event.accept()
            return
        if getattr(self, "_panning", False):
            GraphicsView.mouseReleaseEvent(self, event)
            return
        QGraphicsView.mouseReleaseEvent(self, event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        QGraphicsView.mouseDoubleClickEvent(self, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space and self.is_pan_enabled():
            GraphicsView.keyPressEvent(self, event)
            return
        # proxy 里的输入框要能打字：焦点项存在时直通 QGraphicsView，
        # 刻意绕开 GraphicsView（设计器快捷键都挂在它上面）。
        scene = self.scene()
        if scene is not None and scene.focusItem() is not None:
            QGraphicsView.keyPressEvent(self, event)
            return
        event.ignore()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space and self.is_pan_enabled():
            GraphicsView.keyReleaseEvent(self, event)
            return
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        event.accept()

    # -- 承载控件 / 旧 API ----------------------------------------------
    def refresh_embedded_widgets(self) -> None:
        if self.stage is not None:
            self.stage.widgets.align_all()
        self.viewport().update()

    def _sync_embedded_widgets_geometry(self) -> None:
        self.refresh_embedded_widgets()

    def release_embedded_widgets(self, trace=None) -> None:
        if self.stage is not None:
            self.stage.widgets.release()

    def set_exact_repaint(self, enable: bool) -> None:
        """兼容钩子：本模板不做「动画期吞掉整窗 update」的优化。"""
        self._exact_repaint = bool(enable)

    def delete_all_elements(self) -> None:
        if self.stage is not None:
            self.stage.widgets.release()
        self.scene().clear_page()

    def load_scene_file(self, path: str) -> int:
        if self.stage is not None:
            return self.stage.load(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"场景文件不存在: {path}")
        self.scene().clear_page()
        return self.scene().load_page(path)

    def set_scene_mode(self, run: bool) -> None:
        if self.stage is not None:
            self.stage.enter_run_mode(bool(run))
        else:
            self.scene().is_run_mode = bool(run)

    # -- 运行态模式切换（由 stage 调用） ---------------------------------
    def apply_run_mode(self, run: bool) -> None:
        """关门控但不碰核心的内置 widget layer（避免两套 proxy 抢图元）。"""
        scene = self.scene()
        scene.is_run_mode = bool(run)
        scene.clearSelection()
        for item in scene.all_items():
            item.set_selectable(not run)
            item.setFlag(_ITEM_MOVABLE, False)
            item.setAcceptHoverEvents(not run)
        self.show_grid = False
        self.snap.show_markers = False
        if hasattr(self.snap, "grid_enabled"):
            self.snap.grid_enabled = False
        self.refresh_embedded_widgets()
