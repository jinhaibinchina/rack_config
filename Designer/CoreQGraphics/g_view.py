"""QGraphicsView 视图与交互层。

Core 没有独立 view 类（自绘 QWidget 兼视图），这里补一层：
框选 / 平移 / 缩放 / 旋转 / 分组解组 / T 门控吸附 / 红色十字标记。

视图变换保持 Qt 默认（y 向下、无镜像）；AGV 轴交换已在加载时投影进
item 几何，所以文字不会被镜像，画面朝向仍与旧实现一致。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QFontMetrics, QKeyEvent, QMouseEvent, QPainter,
    QPainterPath, QPen, QWheelEvent,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsView, QMenu, QRubberBand

from .g_snap import GRID_MAJOR_EVERY, SnapSystem

ELEMENT_MIME_TYPE = "application/x-coreqg-element"

# 选中图元 ID 标注（固定屏幕像素，不随视图缩放变形）
_MAX_ID_LABELS = 200           # 选中项超过此数不再标注，避免刷屏与掉帧
_ID_FONT_PX = 11
_ID_DOT_RADIUS = 3.0
_ID_DOT_COLOR = QColor(214, 51, 46)
# 旋转支点标记（蓝色十字圆环，固定屏幕像素）
_ORIGIN_COLOR = QColor(22, 119, 255)
_ORIGIN_RING_RADIUS = 5.0

# 背景网格（画在场景坐标里，步长与 SnapSystem.grid_step 共用同一份）
_GRID_MINOR = QColor(90, 120, 150, 48)
_GRID_MAJOR = QColor(90, 120, 150, 110)

# 鼠标附近吸附标记：小于这个屏幕像素的偏移不吸附，避免抖动
_SNAP_MIN_PX = 2.0


class GraphicsView(QGraphicsView):
    """交互视图。``scene()`` 应为 :class:`GraphicsScene`。"""

    elementDropped = Signal(str, QPointF)   # (type_key, 视图场景坐标)
    actionTriggered = Signal(str)           # 右键菜单的统一命令名

    def __init__(self, scene=None, parent=None) -> None:
        super().__init__(parent)
        # 状态先就位：setScene() 里要用到 snap / show_grid
        self.snap = SnapSystem()
        self._panning = False
        self._pan_start = QPoint()
        self._space_held = False
        self._ctrl_held = False
        self.show_grid = True
        self.show_ids = True
        # 拖动中的吸附偏移：已经叠加到选中图元上的额外位移（场景单位）。
        # 每帧用「目标偏移 - 已叠加偏移」求增量，鼠标继续走时图元钉在格点上，
        # 离开阈值后自动回退，不会越推越远（等价 Core 的 sence_pos_mouse_save 同步）。
        self._snap_offset = QPointF(0.0, 0.0)
        # 最后一次落在画布上的光标位置：光标移出画布（leaveEvent 会清 snap.hover）
        # 后按 T 仍能按上一次位置吸附，不必先把鼠标挪回来
        self._last_hover: QPointF | None = None
        # 本次按下是否拖的是图元（按空白处是框选，不能被吸附推走）
        self._drag_items_active = False
        self._press_positions: dict[int, QPointF] = {}
        # 绘制模式（CAD 式分点）：激活工具后图元跟随鼠标，点击画布落点
        self._draw_type = ""
        # 右键位置（page 场景坐标）：供「旋转中心设到此处」使用
        self._context_page: QPointF | None = None
        # 子图元拖动代理：(根父对象, 上次视口点)；拖动子图元 = 拖动它的根父对象
        self._proxy_drag: tuple[object, QPoint] | None = None
        self._press_modified = False
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.IntersectsItemShape)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        if scene is not None:
            self.setScene(scene)

    # ------------------------------------------------------------------
    # 视图
    # ------------------------------------------------------------------
    def setScene(self, scene) -> None:
        old = self.scene()
        if old is not None:
            try:
                old.selectionChanged.disconnect(self._on_scene_selection_changed)
            except (RuntimeError, TypeError):
                pass
        super().setScene(scene)
        if scene is not None:
            scene.selectionChanged.connect(self._on_scene_selection_changed)
            self._sync_grid_origin()
        self._sync_view_metrics()

    def _sync_grid_origin(self) -> None:
        """网格基准点对齐到场景原点（AGV 投影下即 ``sceneToView(0, 0)``）。

        与旧 ``Core`` 的 ``draw_grid`` 一致：AGV 图从 ``sceneToView(0,0)``
        起向两侧铺格，页面原点因此落在某个格点上。
        """
        scene = self.scene()
        proj = getattr(scene, "projection", None)
        if proj is None:
            return
        origin = proj.point(0.0, 0.0)
        self.snap.grid_origin = (origin.x(), origin.y())

    def _sync_view_metrics(self) -> None:
        """视图缩放变化后同步网格步长与吸附阈值（阈值按屏幕像素恒定）。"""
        scale = abs(self.transform().m11())
        if scale <= 1e-9:
            scale = 1.0
        self.snap.adapt_grid_to_scale(scale)
        self.snap.threshold = self.snap.pixel_threshold / scale

    def _on_scene_selection_changed(self) -> None:
        """选中集合变化时整屏重绘：ID 标注只覆盖选中项，局部更新会留残影。"""
        if getattr(self, "show_ids", True):
            self.viewport().update()

    def fit_content(self) -> None:
        scene = self.scene()
        if scene is not None and hasattr(scene, "fit_rect"):
            self.fitInView(scene.fit_rect(), Qt.KeepAspectRatio)
            self.refresh_snap_points()
            self._sync_view_metrics()

    def fit_saved_rect(self) -> None:
        """按 page JSON 保存的 ``sceneRect`` 恢复视图范围。

        该字段是「上次保存时的可见视图范围」，不是图元包围盒；与
        ``fit_content()`` 语义不同，两者都保留供用户切换。
        """
        scene = self.scene()
        rect = scene.view_scene_rect() if hasattr(scene, "view_scene_rect") else None
        if rect is not None and rect.width() > 0 and rect.height() > 0:
            self.fitInView(rect, Qt.KeepAspectRatio)
            self.refresh_snap_points()
            self._sync_view_metrics()
        else:
            self.fit_content()

    def refresh_snap_points(self) -> None:
        scene = self.scene()
        if scene is not None and hasattr(scene, "snap_points"):
            ends, mids = scene.snap_points()
            self.snap.update_points(ends, mids)

    # ------------------------------------------------------------------
    # 绘制模式：激活工具后点击画布落点（矩形/线/圆两击，三角三击，
    # 多边形多击 + 右键闭合，文本/图片/复选框等单击）。参考 Core 的绘制流程。
    # ------------------------------------------------------------------
    def set_draw_tool(self, type_key: str | None) -> None:
        """激活/取消绘制工具。空值取消，恢复框选与默认光标。"""
        scene = self.scene()
        if type_key and getattr(scene, "is_run_mode", False):
            type_key = None
        if not type_key:
            self._draw_type = ""
            self.setDragMode(QGraphicsView.RubberBandDrag)
            self.unsetCursor()
            self.viewport().update()
            return
        self._draw_type = type_key
        self.setDragMode(QGraphicsView.NoDrag)
        self.setCursor(Qt.CrossCursor)
        self.viewport().update()

    # ------------------------------------------------------------------
    # 鼠标：平移 / 缩放 / 释放后吸附
    # ------------------------------------------------------------------
    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)
        # 缩放后网格密度与吸附半径都按屏幕口径重算
        self._sync_view_metrics()
        self.viewport().update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MiddleButton or self._space_held:
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if self._draw_type:
            scene = self.scene()
            if scene is not None and hasattr(scene, "begin_draw_tool"):
                pos_scene = self.mapToScene(event.position().toPoint())
                cx, cy = scene.projection.inverse_point(pos_scene.x(), pos_scene.y())
                page_pt = QPointF(cx, cy)
                # 多边形 / 路径：右键闭合
                if event.button() == Qt.RightButton and scene.drawing_polygon():
                    scene.finish_polygon(page_pt)
                elif event.button() == Qt.LeftButton:
                    if not scene.drawing_active():
                        scene.begin_draw_tool(self._draw_type)
                    scene.draw_add_point(page_pt)
                event.accept()
                self.viewport().update()
                return
        if event.button() == Qt.RightButton:
            # Qt 的 QGraphicsView 在右键按下时会清空选中（实测裸视图同样如此），
            # 导致右键菜单/属性面板拿不到目标图元。这里自己接管，不改选中。
            scene = self.scene()
            if scene is not None:
                scene_pt = self.mapToScene(event.position().toPoint())
                self._context_page = QPointF(
                    *scene.projection.inverse_point(scene_pt.x(), scene_pt.y())
                )
            self._prepare_context_target(event)
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            scene = self.scene()
            if scene is not None:
                self._press_modified = bool(
                    getattr(scene, "is_modified", lambda: False)())
            # 只有按在可选图元上才算「拖动图元」；按空白处是框选，不该被吸附推走
            hit = scene.itemAt(self.mapToScene(event.position().toPoint()),
                               self.transform()) if scene is not None else None
            self._drag_items_active = bool(
                hit is not None
                and (hit.flags() & QGraphicsItem.ItemIsSelectable)
                and not getattr(scene, "is_run_mode", False))
            # 子图元不能单独拖（位姿由父对象决定），这里改成拖它的根父对象，
            # 免得「拖不动」被误当成卡死。
            root = self._child_root_under(event.position().toPoint())
            if root is not None:
                scene = self.scene()
                scene.clearSelection()
                root.setSelected(True)
                self._proxy_drag = (root, event.position().toPoint())
                self._drag_items_active = True
                self._snap_offset = QPointF(0.0, 0.0)
                self._press_positions = {root.item_id: QPointF(root.scenePos())}
                self.setCursor(Qt.ClosedHandCursor)
                self.actionTriggered.emit("drag_child")
                event.accept()
                return
        super().mousePressEvent(event)
        # 记录按下时的位置：松手时据此判断「这次到底有没有真的拖动」，
        # 没拖动（比如未按 CTRL、被闸门锁住）就不做吸附位移。
        self._remember_press_positions()

    def context_page_point(self) -> QPointF | None:
        """最近一次右键点击处的 page 场景坐标。"""
        return self._context_page

    def _remember_press_positions(self) -> None:
        """记录本次按下时的图元位置，并把吸附偏移基准归零。"""
        scene = self.scene()
        self._press_positions = {}
        self._snap_offset = QPointF(0.0, 0.0)
        if scene is None or not hasattr(scene, "selected_items"):
            return
        for it in scene.selected_items():
            self._press_positions[it.item_id] = QPointF(it.scenePos())

    def _items_moved_since_press(self) -> bool:
        """按下到现在，选中图元里有没有真的被拖动过。"""
        scene = self.scene()
        if scene is None or not self._press_positions:
            return False
        for it in scene.selected_items():
            start = self._press_positions.get(it.item_id)
            if start is None:
                continue
            if (it.scenePos() - start).manhattanLength() > 1e-9:
                return True
        return False

    def _child_root_under(self, viewport_pos: QPoint):
        """光标下的图元若有父对象，返回它最顶层的父对象（否则 None）。"""
        scene = self.scene()
        if scene is None or getattr(scene, "is_run_mode", False):
            return None
        if not getattr(scene, "_movable_gate", False) or self._draw_type:
            return None
        for it in scene.items(self.mapToScene(viewport_pos)):
            if getattr(it, "item_id", None) is None or not it.isVisible():
                continue
            if not getattr(it, "parent_id", 0):
                return None
            root = it.root_parent()
            return None if root is it else root
        return None

    def _prepare_context_target(self, event: QMouseEvent) -> None:
        """右键不改动既有选中，只保证「点到的图元」成为选中目标。

        * 点在**未选中**的图元上 → 清空后只选中它（属性面板切到该图元）；
        * 点在**已选中**图元或空白处 → 保持现有选中，右键菜单照常作用于它。
        """
        scene = self.scene()
        if scene is None or getattr(scene, "is_run_mode", False):
            return
        pos = self.mapToScene(event.position().toPoint())
        for it in scene.items(pos):
            if getattr(it, "item_id", None) is None or not it.isVisible():
                continue
            if not (it.flags() & QGraphicsItem.ItemIsSelectable):
                continue
            if not it.isSelected():
                scene.clearSelection()
                it.setSelected(True)
            break

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # 鼠标位置先记下来：吸附目标、附近标记都基于它
        self._set_hover(self.mapToScene(event.position().toPoint()))
        if self._proxy_drag is not None:
            root, last = self._proxy_drag
            now = event.position().toPoint()
            delta = self.mapToScene(now) - self.mapToScene(last)
            self._proxy_drag = (root, now)
            root.setPos(root.scenePos() + delta)   # 子图元在 on_item_moved 里随之位姿
            self._apply_snap_follow()              # 拖子图元 = 拖根父，一样要吸附
            event.accept()
            return
        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
            return
        if self._draw_type and self.scene() is not None:
            scene = self.scene()
            if hasattr(scene, "draw_preview"):
                pos_scene = self.mapToScene(event.position().toPoint())
                cx, cy = scene.projection.inverse_point(pos_scene.x(), pos_scene.y())
                scene.draw_preview(QPointF(cx, cy))
                event.accept()
                self.viewport().update()
                return
        super().mouseMoveEvent(event)
        # 拖动中不在这里 moveBy：Qt 对可拖图元用「按下点 + 鼠标位移」的**绝对**
        # 定位，下一次 mouseMove 会覆盖掉我们叠加的偏移（实测只剩零头）。
        # 实时的「钉住」效果交给光标下的标记展示，位移在松手 / 按 T 时一次性补。
        if self._drag_items_active and (event.buttons() & Qt.LeftButton):
            self.viewport().update()

    def leaveEvent(self, event) -> None:
        self._set_hover(None)
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_view_metrics()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.RightButton:
            # 右键按下未转给基类（见 mousePressEvent），抬起同样不转
            event.accept()
            return
        if self._proxy_drag is not None:
            self._proxy_drag = None
            self._drag_items_active = False
            self.unsetCursor()
            scene = self.scene()
            if scene is not None and hasattr(scene, "mark_modified"):
                scene.mark_modified()
            if self.snap.enabled:
                self._apply_snap_follow()
            self.refresh_snap_points()
            self._notify_drag_done()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        dragged = self._drag_items_active and self._items_moved_since_press()
        self._drag_items_active = False
        if self._panning:
            self._panning = False
            self.unsetCursor()
        elif self.snap.enabled and event.button() == Qt.LeftButton and dragged:
            # 松手时按「光标相对捕捉点的偏移」整体平移选中图元：
            # 光标吸了多少，图元就移动多少（require_movable=False 是因为
            # 用户可能先松开了 CTRL，但拖动确实发生过）。
            self._apply_snap_follow(require_movable=False)
        self._notify_drag_done()

    def _notify_drag_done(self) -> None:
        """一次拖拽结束：本次按下期间确实把页面改脏了才通知主窗口记撤销。"""
        scene = self.scene()
        if scene is None:
            return
        now = bool(getattr(scene, "is_modified", lambda: False)())
        if now and not self._press_modified:
            self.actionTriggered.emit("drag_done")
        self._press_modified = now

    # ------------------------------------------------------------------
    # 键盘：T 门控 + 常用编辑
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        scene = self.scene()
        key = event.key()
        if key == Qt.Key_Escape and self._draw_type:
            scene = self.scene()
            if scene is not None and getattr(scene, "drawing_active", lambda: False)():
                scene.cancel_draw()
            else:
                self.set_draw_tool(None)
            event.accept()
            return
        if key == Qt.Key_Space:
            self._space_held = True
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        if key == Qt.Key_Control:
            if not self._ctrl_held:
                self._ctrl_held = True
                scene = self.scene()
                if scene is not None and hasattr(scene, "set_movable_gate"):
                    scene.set_movable_gate(True)
            event.accept()
            return
        if key == Qt.Key_T:
            self.snap.enabled = not self.snap.enabled
            self.refresh_snap_points()
            # 门控打开后立刻按「光标当前所在位置」吸附过去：鼠标吸了多少偏移，
            # 选中的图元就移动多少。_snap_offset 不清零 —— 它记的是「已经叠加
            # 到图元上的额外位移」，清掉会让再次开 T 时又推一次。
            if self.snap.enabled:
                # 光标刚移出画布（去点了属性面板 / 图层树）时 snap.hover 已被
                # 清空，退回最后一次画布位置，免得「按 T 没反应」
                if self.snap.hover is None and self._last_hover is not None:
                    self.snap.hover = QPointF(self._last_hover)
                moved = self._apply_snap_follow(allow_release=False,
                                                require_movable=False)
                # 光标不在画布上就别去挪系统光标，只把图元吸过去
                if self.viewport().underMouse():
                    self._warp_cursor_to_snap()
                if moved:
                    # 吸附真的挪了图元：记一个撤销点（拖动路径靠 release 记）
                    self.actionTriggered.emit("drag_done")
            self.viewport().update()
            event.accept()
            return
        sel = scene.selected_items() if hasattr(scene, "selected_items") else []
        if key in (Qt.Key_Plus, Qt.Key_Equal):
            for it in sel:
                it.resize_by(1.1)
        elif key == Qt.Key_Minus:
            for it in sel:
                it.resize_by(1.0 / 1.1)
        elif key == Qt.Key_BracketLeft:
            for it in sel:
                it.rotate_by(-5.0)
        elif key == Qt.Key_BracketRight:
            for it in sel:
                it.rotate_by(5.0)
        elif key == Qt.Key_G:
            if hasattr(scene, "group_selected"):
                scene.group_selected()
        elif key == Qt.Key_U:
            if hasattr(scene, "ungroup_selected"):
                scene.ungroup_selected()
        elif key == Qt.Key_0:
            self.fit_content()
        elif key == Qt.Key_R:
            if scene is not None:
                scene.is_run_mode = not getattr(scene, "is_run_mode", False)
                self.viewport().update()
        elif key == Qt.Key_Delete:
            if hasattr(scene, "delete_items"):
                scene.delete_items(sel)
            else:
                for it in sel:
                    scene.removeItem(it)
        elif key == Qt.Key_S and (event.modifiers() & Qt.ControlModifier):
            if hasattr(scene, "save_page"):
                scene.save_page()
        else:
            super().keyPressEvent(event)
            return
        self.refresh_snap_points()
        self.viewport().update()
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Space:
            self._space_held = False
            if not self._panning:
                self.unsetCursor()
        elif event.key() == Qt.Key_Control:
            self._ctrl_held = False
            scene = self.scene()
            if scene is not None and hasattr(scene, "set_movable_gate"):
                scene.set_movable_gate(False)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        # 焦点丢失（如切到别的窗口仍按住 CTRL）时复位移动门控，避免卡在可拖动态
        self._proxy_drag = None
        if self._ctrl_held:
            self._ctrl_held = False
            scene = self.scene()
            if scene is not None and hasattr(scene, "set_movable_gate"):
                scene.set_movable_gate(False)
        super().focusOutEvent(event)

    # ------------------------------------------------------------------
    # 吸附：以**鼠标位置**为基准，鼠标吸了多少偏移，选中图元就移动多少
    # ------------------------------------------------------------------
    def _selection_own_points(self) -> set:
        """选中项自身的捕捉点：拖动自己时不能吸到自己身上。"""
        scene = self.scene()
        own: set = set()
        if scene is None or not hasattr(scene, "selected_items"):
            return own
        for it in scene.selected_items():
            e, m = it.snap_points()
            for p in e + m:
                own.add((p.x(), p.y()))
        return own

    def _view_scale(self) -> float:
        scale = abs(self.transform().m11())
        return scale if scale > 1e-9 else 1.0

    def _warp_cursor_to_snap(self) -> None:
        """把系统光标也挪到捕捉点上（旧 Core ``warp_cursor`` 的等价物）。

        图元与光标走的是同一个偏移，所以挪完仍然对位。挪完必须把 ``hover`` 与
        「已叠加偏移」一起归位：光标已经在捕捉点上了，相对偏移就是 0；否则下一次
        ``mouseMoveEvent`` 会按新光标位置算出 ``offset = 0``，再把图元推回原处。

        光标不在画布上时 ``snap.hover`` 已被 ``leaveEvent`` 清空，这里自然跳过，
        不会把鼠标从别的窗口劫走。
        """
        target, _active = self._hover_marker()
        if target is None:
            return
        vp = self.mapFromScene(target)
        QCursor.setPos(self.viewport().mapToGlobal(vp))
        self.snap.hover = QPointF(target)
        self._snap_offset = QPointF(0.0, 0.0)

    def _apply_snap_follow(self, allow_release: bool = True,
                           require_movable: bool = True) -> bool:
        """把光标吸附偏移叠加到选中图元上，返回本次是否真的移动了。

        ``_snap_offset`` 记录「已经叠加过的总偏移」，每帧只补差量，所以：

        * 吸附期间鼠标继续移动 → 图元钉在捕捉点附近不跟着跑（磁性效果）；
        * 鼠标移出阈值 → 差量自动抵消，图元回到跟手位置（``allow_release``）；
        * 同一位置反复按 T → 偏移不变、增量为 0，不会越推越远。

        ``allow_release=False`` 用于 T 键：只做一次正向吸附，鼠标没指到
        任何捕捉点时保持图元不动，避免把之前吸过的偏移又撤回。
        ``require_movable`` 用于拖动：没按 CTRL（图形项不可拖）时不能靠
        吸附把图元偷偷挪走，否则「拖不动」的契约就被绕过了。

        吸附目标用 ``always=True`` 取「最近的捕捉点」：附近有端点 / 中点就吸它，
        没有就吸最近的格子交汇点。因此**每个图元类型**（含顶点类、文本、图片、
        成组）按 T 都能动，不会出现「有的图元按 T 没反应」。
        """
        scene = self.scene()
        hover = self.snap.hover if self.snap.hover is not None else self._last_hover
        if scene is None or hover is None or not hasattr(scene, "selected_items"):
            return False
        sel = [it for it in scene.selected_items() if not getattr(it, "parent_id", 0)]
        if require_movable:
            sel = [it for it in sel
                   if it.flags() & QGraphicsItem.ItemIsMovable]
        if not sel:
            return False

        target, _kind = self.snap.aim(hover, exclude=self._selection_own_points(),
                                      always=True)
        if target is None:
            if not allow_release:
                self._snap_offset = QPointF(0.0, 0.0)
                return False
            offset = QPointF(0.0, 0.0)
        else:
            offset = target - hover
            # 屏幕上不足 2px 的偏移不吸，避免阈值边缘抖动
            if math.hypot(offset.x(), offset.y()) * self._view_scale() < _SNAP_MIN_PX:
                offset = QPointF(0.0, 0.0)

        delta = offset - self._snap_offset
        if abs(delta.x()) < 1e-9 and abs(delta.y()) < 1e-9:
            self._snap_offset = offset
            return False
        for it in sel:
            # 有父对象的图元位姿由父对象带动，吸附不能单独挪它
            it.moveBy(delta.x(), delta.y())
        self._snap_offset = offset
        return True

    # 兼容旧调用点
    def _apply_snap_to_selection(self) -> None:
        self._apply_snap_follow()

    # ------------------------------------------------------------------
    # 设计网格（由主窗口开关控制，默认关）
    # ------------------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect) -> None:
        super().drawBackground(painter, rect)
        if not self.show_grid or not self.snap.grid_enabled:
            return
        self._draw_grid(painter, rect)

    def _draw_grid(self, painter: QPainter, rect) -> None:
        """背景网格：细线每格、粗线每 ``GRID_MAJOR_EVERY`` 格。

        步长取自 :class:`SnapSystem`（随缩放自适应），所以画出来的每个
        交汇点都正好是能吸的网格点，视觉与捕捉粒度不会错位。
        """
        step = self.snap.grid_step
        if step <= 0:
            return
        ox, oy = self.snap.grid_origin
        left = ox + math.floor((rect.left() - ox) / step) * step
        top = oy + math.floor((rect.top() - oy) / step) * step
        cols = min(2000, int((rect.right() - left) / step) + 1)
        rows = min(2000, int((rect.bottom() - top) / step) + 1)
        i0 = int(round((left - ox) / step))
        j0 = int(round((top - oy) / step))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        minor = QPen(_GRID_MINOR, 0.0)
        major = QPen(_GRID_MAJOR, 0.0)
        for i in range(cols):
            x = left + i * step
            painter.setPen(major if (i0 + i) % GRID_MAJOR_EVERY == 0 else minor)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        for j in range(rows):
            y = top + j * step
            painter.setPen(major if (j0 + j) % GRID_MAJOR_EVERY == 0 else minor)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.restore()

    # ------------------------------------------------------------------
    # 红色十字标记（固定屏幕像素大小，不随缩放变形）
    # ------------------------------------------------------------------
    def drawForeground(self, painter: QPainter, rect) -> None:
        super().drawForeground(painter, rect)
        scene = self.scene()
        # 设计模式下：选中图元标注中心点小圆点 + ID（画在最上层）
        if self.show_ids and scene is not None and not getattr(scene, "is_run_mode", False):
            self._draw_origin_markers(painter)
            self._draw_selection_ids(painter)
        # 手动绘制预览层：落点标记 + 定义段（box/circle/line）或顶点连线（poly）
        if self._draw_type:
            if scene is not None and hasattr(scene, "draw_preview_state"):
                state = scene.draw_preview_state()
                if state is not None:
                    self._draw_preview_overlay(painter, state)
        # 光标处的那一个捕捉点：始终跟随鼠标显示（门控只决定是否真的吸过去）
        if self.snap.show_markers and not getattr(scene, "is_run_mode", False):
            self._draw_hover_snap_points(painter)

    def _hover_marker(self) -> tuple[QPointF | None, bool]:
        """光标处该显示的那**一个**捕捉点，以及它此刻是否真的会吸附。

        ``always=True``：附近没端点 / 中点时退到最近的格子交汇点，保证「光标
        附近始终只有一个十字」——大图元内部（自己的点被排除）也有标记可吸。
        """
        hover = self.snap.hover
        if hover is None:
            return None, False
        target, _kind = self.snap.aim(hover, exclude=self._selection_own_points(),
                                      always=True)
        return target, bool(self.snap.enabled)

    def _draw_hover_snap_points(self, painter: QPainter) -> None:
        """只画**最近的那一个**捕捉点（固定屏幕像素）。

        把附近所有候选点都画出来时，端点 / 中点 / 格点在同一小片区域里会挤成
        一片十字，反而看不出「松手会吸到哪」。``aim()`` 已经按「图元点优先、
        格点严格更近才顶替」排出了最近点，直接画它：门控打开时加粗 + 套圆环
        （表示按 T / 松手会吸过去），门控关闭时只画细十字当预告。
        """
        target, active = self._hover_marker()
        if target is None:
            return
        vp = QPointF(self.mapFromScene(target))
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, True)
        if active:
            painter.setPen(QPen(QColor(255, 130, 0, 255), 1.8))
            half = 5.0
        else:
            painter.setPen(QPen(QColor(255, 150, 0, 190), 1.0))
            half = 3.5
        painter.drawLine(QPointF(vp.x() - half, vp.y()),
                         QPointF(vp.x() + half, vp.y()))
        painter.drawLine(QPointF(vp.x(), vp.y() - half),
                         QPointF(vp.x(), vp.y() + half))
        if active:
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(vp, 8.0, 8.0)
        painter.restore()

    def _set_hover(self, scene_pt: QPointF | None) -> None:
        """更新光标场景坐标，并只重绘「旧位置 + 新位置」两小块区域。"""
        old = self.snap.hover
        self.snap.hover = QPointF(scene_pt) if scene_pt is not None else None
        if scene_pt is not None:
            self._last_hover = QPointF(scene_pt)
        if not self.snap.show_markers:
            return
        for p in (old, self.snap.hover):
            if p is None:
                continue
            vp = self.mapFromScene(p)
            self.viewport().update(QRect(vp.x() - 48, vp.y() - 48, 96, 96))

    # ------------------------------------------------------------------
    # 选中图元标注：中心点小圆点 + ID（仅设计模式，固定屏幕像素）
    # ------------------------------------------------------------------
    def _draw_origin_markers(self, painter: QPainter) -> None:
        """选中图元的旋转支点：中心→支点虚线 + 蓝色十字圆环。

        只在设过自定义支点时画，默认「绕中心转」的图元不受影响；固定屏幕像素，
        不随视图缩放变形。判据用 ``has_custom_origin()`` 而不是
        ``transformOriginPoint``：顶点类图元把旋转烘焙进顶点后 Qt 旋转归零，
        变换原点不再是支点的载体（会被重置成 (0,0)）。
        """
        scene = self.scene()
        if scene is None or not hasattr(scene, "selected_items"):
            return
        items = [it for it in scene.selected_items()
                 if it.has_custom_origin()][:_MAX_ID_LABELS]
        if not items:
            return
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, True)
        ring = QPen(_ORIGIN_COLOR, 1.4)
        link = QPen(QColor(_ORIGIN_COLOR.red(), _ORIGIN_COLOR.green(),
                           _ORIGIN_COLOR.blue(), 150), 1.0, Qt.DashLine)
        for it in items:
            # 支点位置取记录口径（投影后的 page_origin），不依赖 Qt 变换原点
            ov = QPointF(self.mapFromScene(it.pivot_scene_point()))
            cv = QPointF(self.mapFromScene(it.center_scene_point()))
            painter.setPen(link)
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(cv, ov)
            painter.setPen(ring)
            painter.drawEllipse(ov, _ORIGIN_RING_RADIUS, _ORIGIN_RING_RADIUS)
            painter.drawLine(QPointF(ov.x() - 8, ov.y()), QPointF(ov.x() + 8, ov.y()))
            painter.drawLine(QPointF(ov.x(), ov.y() - 8), QPointF(ov.x(), ov.y() + 8))
        painter.restore()

    def _draw_selection_ids(self, painter: QPainter) -> None:
        """选中图元标注：红色小圆点 + ID 标签，位置在**旋转中心**（支点）。

        默认「绕中心转」的图元支点即几何中心，视觉上与旧版一致；用右键
        「旋转中心设到此处」改过支点后，标识跟着挪到支点上。
        """
        scene = self.scene()
        if scene is None or not hasattr(scene, "selected_items"):
            return
        items = scene.selected_items()
        if not items or len(items) > _MAX_ID_LABELS:
            return

        font = QFont(self.font())
        font.setPixelSize(_ID_FONT_PX)
        font.setBold(True)
        metrics = QFontMetrics(font)
        font_h = float(metrics.height())

        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setFont(font)
        border_pen = QPen(QColor(120, 132, 148, 170), 1.0)
        text_color = QColor(22, 28, 36)
        dot_pen = QPen(QColor(255, 255, 255, 230), 1.5)
        dot_brush = QBrush(_ID_DOT_COLOR)

        for it in items:
            # 中心点标识标在「旋转中心」处：默认绕中心转时与几何中心重合，
            # 设过自定义支点后跟着支点走（与蓝色支点环同一位置）。
            getter = getattr(it, "pivot_scene_point", None)
            if getter is None:
                getter = getattr(it, "center_scene_point", None)
            scene_pt = getter() if getter is not None else it.scenePos()
            vp = self.mapFromScene(scene_pt)
            x, y = float(vp.x()), float(vp.y())

            text = str(int(getattr(it, "item_id", 0) or 0))
            tw = float(metrics.horizontalAdvance(text)) + 10.0
            th = font_h + 2.0
            # 默认标在中心点右上方；贴近视口上沿时翻到下方，避免被裁掉
            ty = y - th - 6.0
            if ty < 1.0:
                ty = y + 6.0
            tx = x + 6.0
            if tx + tw > self.viewport().width() - 1:
                tx = x - tw - 6.0
            tag = QRectF(tx, ty, tw, th)

            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255, 225)))
            painter.drawRoundedRect(tag, 3.0, 3.0)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(border_pen)
            painter.drawRoundedRect(tag, 3.0, 3.0)
            painter.setPen(text_color)
            painter.drawText(tag, Qt.AlignCenter, text)

            # 中心点小圆点（画在文字之上，保证不被标签压住）
            painter.setPen(dot_pen)
            painter.setBrush(dot_brush)
            painter.drawEllipse(QPointF(x, y), _ID_DOT_RADIUS, _ID_DOT_RADIUS)
        painter.restore()

    def _draw_preview_overlay(self, painter: QPainter, state) -> None:
        type_key, points_page, preview_page, is_poly = state
        proj = self.scene().projection
        pts_view = [proj.point(p.x(), p.y()) for p in points_page]
        prev_view = (
            proj.point(preview_page.x(), preview_page.y())
            if preview_page is not None else None
        )
        painter.save()
        pen = QPen(QColor(0, 120, 215), 0, Qt.DashLine)
        painter.setPen(pen)
        # 落点标记（小十字）
        for pv in pts_view:
            painter.drawLine(QPointF(pv.x() - 5, pv.y()), QPointF(pv.x() + 5, pv.y()))
            painter.drawLine(QPointF(pv.x(), pv.y() - 5), QPointF(pv.x(), pv.y() + 5))
        if not pts_view:
            painter.restore()
            return
        if is_poly:
            path = QPainterPath(pts_view[0])
            for pv in pts_view[1:]:
                path.lineTo(pv)
            if prev_view is not None:
                path.lineTo(prev_view)
            painter.drawPath(path)
        elif prev_view is not None:
            painter.drawLine(pts_view[0], prev_view)
            if type_key == "rect":
                r = QRectF(pts_view[0], prev_view).normalized()
                painter.drawRect(r)
            elif type_key == "circle":
                rx = abs(prev_view.x() - pts_view[0].x())
                ry = abs(prev_view.y() - pts_view[0].y())
                r = math.hypot(rx, ry)
                painter.drawEllipse(pts_view[0], r, r)
        painter.restore()

    # ------------------------------------------------------------------
    # 工具箱拖放
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(ELEMENT_MIME_TYPE):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(ELEMENT_MIME_TYPE):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(ELEMENT_MIME_TYPE):
            super().dropEvent(event)
            return
        raw = bytes(event.mimeData().data(ELEMENT_MIME_TYPE)).decode("utf-8", "ignore")
        scene_pt = QPointF(self.mapToScene(event.position().toPoint()))
        event.setDropAction(Qt.CopyAction)
        event.accept()
        if raw:
            self.elementDropped.emit(raw, scene_pt)

    # ------------------------------------------------------------------
    # 右键菜单：只发命令名，动作由主窗口统一分发（菜单/工具栏/右键共用）
    # ------------------------------------------------------------------
    _CONTEXT_ENTRIES = (
        ("属性…", "property"),
        (None, None),
        ("旋转中心设到此处", "origin_here"),
        ("旋转中心复位到图元中心", "origin_center"),
        (None, None),
        ("移到最前", "z_front"), ("上移一层", "z_raise"),
        ("下移一层", "z_lower"), ("移到最后", "z_back"),
        (None, None),
        ("左对齐", "align_left"), ("右对齐", "align_right"),
        ("顶对齐", "align_top"), ("底对齐", "align_bottom"),
        ("水平居中", "align_hcenter"), ("垂直居中", "align_vcenter"),
        (None, None),
        ("水平等距", "distribute_h"), ("垂直等距", "distribute_v"),
        (None, None),
        ("成组", "group"), ("解组", "ungroup"), ("复制", "duplicate"),
        ("删除", "delete"),
        (None, None),
        ("全选", "select_all"), ("适应内容", "fit"),
    )

    def build_context_menu(self) -> QMenu:
        menu = QMenu(self)
        for label, key in self._CONTEXT_ENTRIES:
            if label is None:
                menu.addSeparator()
                continue
            action = menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, k=key: self.actionTriggered.emit(k)
            )
        return menu

    def contextMenuEvent(self, event) -> None:
        scene = self.scene()
        if scene is not None and getattr(scene, "is_run_mode", False):
            return
        self.build_context_menu().exec(event.globalPos())
