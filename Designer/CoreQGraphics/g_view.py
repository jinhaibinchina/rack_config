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
    QBrush, QColor, QCursor, QKeyEvent, QMouseEvent, QPainter,
    QPainterPath, QPen, QWheelEvent,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsView, QMenu, QRubberBand

from .g_snap import GRID_MAJOR_EVERY, SnapSystem

ELEMENT_MIME_TYPE = "application/x-coreqg-element"

# 选中图元的旋转中心标记（固定屏幕像素，不随视图缩放变形）。
# 只画红点，不再画旁边的 ID 数字标签：多选时一串数字既挡画面又没信息量。
_MAX_SELECTION_MARKS = 200     # 选中项超过此数不再标注，避免刷屏与掉帧
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

# 拖角改尺寸手柄（固定屏幕像素，仅设计模式 + 单选时显示）
_HANDLE_HALF = 4.0            # 方块半边长
_HANDLE_HIT_PX = 8.0          # 命中半径（曼哈顿距离）
_HANDLE_MIN_SPAN = 28.0       # 四角屏幕跨度下限：太小的图元不画手柄，
                              # 否则四个手柄挤在中心会抢走「拖动」按下
_HANDLE_MIN_SCALE = 0.02      # 缩到 2% 停住，防止翻转 / 零尺寸
_HANDLE_COLOR = QColor(22, 119, 255)
_HANDLE_EDGE = QColor(12, 70, 160)
# item.snap_points() 的端点顺序：[左上, 右上, 左下, 右下]
_CORNER_INDEX = {"nw": 0, "ne": 1, "sw": 2, "se": 3}
_OPPOSITE_INDEX = {"nw": "se", "ne": "sw", "sw": "ne", "se": "nw"}


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
        # 画布导航门控：设计态恒开，运行态由子类一次性关掉。
        # 平移与缩放分开两个字段，是因为有的运行窗口只想放开滚轮看细节，
        # 不想让用户把画面拖走（反之亦然）。
        self._pan_enabled = True
        self._zoom_enabled = True
        self.show_grid = True
        # 历史名沿用 show_ids：现在只控制「选中图元的红色旋转中心点」，
        # ID 文字标签已移除；视图菜单 Ctrl+Shift+I 切换的就是这个红点。
        self.show_ids = True
        # 吸附偏移：已经叠加到选中图元上的额外位移（场景单位）。每帧用
        # 「目标偏移 - 已叠加偏移」求增量，鼠标继续走时图元钉在格点上，
        # 离开阈值后自动回退，不会越推越远（等价 Core 的 sence_pos_mouse_save 同步）。
        self._snap_offset = QPointF(0.0, 0.0)
        # 最后一次落在画布上的光标位置：光标移出画布（leaveEvent 会清 snap.hover）
        # 后按 T 仍能按上一次位置吸附，不必先把鼠标挪回来
        self._last_hover: QPointF | None = None
        # 绘制模式（CAD 式分点）：激活工具后图元跟随鼠标，点击画布落点
        self._draw_type = ""
        # 右键位置（page 场景坐标）：供「旋转中心设到此处」使用
        self._context_page: QPointF | None = None
        # 拖角改尺寸：按下时冻结的逆变换 / 固定对角 / 上一次的总缩放比例
        self._resize_state: dict | None = None
        self._press_modified = False
        # 双击「跟手」：双击图元后图元钉在光标上随鼠标走（左键拖动已取消，
        # 这是鼠标移动图元的唯一入口），
        # 左键点击落定、Esc 放回原位。_follow_cursor 记上一次处理过的光标位置，
        # 用增量位移（而不是绝对定位）以免抹掉按 T 吸附出来的偏移。
        self._follow_items: list = []
        self._follow_start: list[tuple[object, tuple[float, float]]] = []
        self._follow_cursor: QPointF | None = None
        self._follow_dragged = False
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
        # 换场景（切页 / 关窗）时跟手状态必须作废，否则会抓着旧场景的图元
        self._follow_items = []
        self._follow_start = []
        self._follow_cursor = None
        self._follow_dragged = False
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
        """选中集合变化时整屏重绘：中心点标记只覆盖选中项，局部更新会留残影。"""
        if self._follow_items:
            # 图层树 / 属性面板改了选中（或被删掉）时跟手就失去意义了，
            # 直接落定，别让「跟着一个已经取消选中的图元」这种状态留着。
            scene = self.scene()
            index = getattr(scene, "index", None)
            alive, still = False, False
            try:
                for it in self._follow_items:
                    if index is None or it.item_id in index.by_id:
                        alive = True
                        still = still or it.isSelected()
            except RuntimeError:      # 图元已被销毁
                alive = False
            if not alive or not still:
                self.end_follow()
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
        self.end_follow()            # 换到绘制工具：先把跟手的图元落定
        self.setDragMode(QGraphicsView.NoDrag)
        self.setCursor(Qt.CrossCursor)
        self.viewport().update()

    # ------------------------------------------------------------------
    # 画布导航门控
    # ------------------------------------------------------------------
    # 设计态两个开关恒为 True；运行态窗口（PopPick 的 RuntimeView、
    # RackConfig 的 _ReadOnlyView / RackSceneView）构造时调
    # ``set_canvas_navigation_enabled(False)`` 关掉，需要时再单独放开。
    # 门控只拦「中键 / 空格平移」与「滚轮缩放」两条输入，左键仍归各运行
    # 窗口自己处理（PopPick 左键拖动是 PageDeck 的翻页手势，不能被抢）。
    def set_pan_enabled(self, enable: bool) -> None:
        """允许 / 禁止中键、空格拖动平移画布。"""
        self._pan_enabled = bool(enable)
        if not self._pan_enabled and self._panning:
            self._panning = False
            self.unsetCursor()

    def is_pan_enabled(self) -> bool:
        return self._pan_enabled

    def set_zoom_enabled(self, enable: bool) -> None:
        """允许 / 禁止滚轮缩放（``_zoom_at``，以光标为锚点）。"""
        self._zoom_enabled = bool(enable)

    def is_zoom_enabled(self) -> bool:
        return self._zoom_enabled

    def set_canvas_navigation_enabled(self, enable: bool) -> None:
        """一次性开关「拖拽平移 + 滚轮缩放」。"""
        self.set_pan_enabled(enable)
        self.set_zoom_enabled(enable)

    def is_canvas_navigation_enabled(self) -> bool:
        return self._pan_enabled and self._zoom_enabled

    def is_pan_event(self, event: QMouseEvent) -> bool:
        """这次按下是否属于「平移手势」（中键，或按住空格的任意键）。"""
        return event.button() == Qt.MiddleButton or self._space_held

    # ------------------------------------------------------------------
    # 鼠标：平移 / 缩放 / 释放后吸附
    # ------------------------------------------------------------------
    def _zoom_at(self, view_pos: QPoint, factor: float) -> None:
        """以视口点 ``view_pos`` 为锚点缩放，缩放前后该点下的场景位置不变。

        不能只调 ``scale()`` 依赖 ``AnchorUnderMouse``：那个锚点用的是
        QGraphicsView 私有的 ``lastMousePos``，只由基类 ``mouseMoveEvent``
        更新。跟手分支为了不让基类插进拖动流程，自己处理完就 ``return``，
        ``lastMousePos`` 于是停在双击之前的位置 —— 滚轮一滚，视图绕着那个
        过时的点缩放，整幅画面（连着跟手的图元）平移一大段，看上去就是
        「跟手时一缩放图元就飞走」。

        这里改成自己算：先记下光标下的场景点，缩放完再按差值补滚动条，
        与锚点模式彻底解耦。
        """
        anchor = self.mapToScene(view_pos)
        mode = self.transformationAnchor()
        # NoAnchor 让 scale() 不做任何内置锚定，补偿量完全由下面这段决定，
        # 避免「Qt 锚一次 + 我们再锚一次」时因为 lastMousePos 过时叠加出偏差。
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        try:
            self.scale(factor, factor)
        finally:
            self.setTransformationAnchor(mode)
        moved = self.mapToScene(view_pos)
        dx = moved.x() - anchor.x()
        dy = moved.y() - anchor.y()
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return
        scale = abs(self.transform().m11())
        if scale <= 1e-9:
            return
        # 场景单位 → 滚动条单位（像素）：滚动条值加 Δ 就是把画面往左/上推
        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()
        hbar.setValue(hbar.value() - int(round(dx * scale)))
        vbar.setValue(vbar.value() - int(round(dy * scale)))

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self._zoom_enabled:
            # ignore 而不是 accept：运行态关掉缩放时，滚轮继续往上冒泡，
            # 外层若有滚动容器还能照常滚动。
            event.ignore()
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        view_pos = event.position().toPoint()
        self._zoom_at(view_pos, factor)
        # 缩放后网格密度与吸附半径都按屏幕口径重算
        self._sync_view_metrics()
        # 光标下的场景点理论上没变，但滚动条可能在内容边缘被夹住而留下残差，
        # 一律按缩放后的真实映射重取：hover 标记与跟手基准都跟着走。
        scene_pos = self.mapToScene(view_pos)
        self._set_hover(scene_pos)
        if self._follow_items:
            # 跟手图元的场景位置不因缩放而变（缩放是视图操作）；基准同步到
            # 缩放后的光标位置，下一次 mouseMove 的增量才是纯鼠标位移。
            self._follow_cursor = QPointF(scene_pos)
        self.viewport().update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._follow_items and event.button() != Qt.NoButton:
            if event.button() == Qt.LeftButton:
                # 跟手是个「抓住」状态：单击任意位置即落定，不再进入框选
                self.end_follow()
                event.accept()
                return
            # 中键平移 / 右键菜单：先落定，再照原流程处理
            self.end_follow()
        if self.is_pan_event(event):
            if not self._pan_enabled:
                event.ignore()
                return
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
            # 角手柄优先于选中 / 框选：按在手柄上就是改尺寸
            corner = self._handle_at(event.position().toPoint())
            if corner is not None:
                self._begin_resize(corner, event)
                if self._resize_state is not None:
                    event.accept()
                    return
            scene = self.scene()
            if scene is not None:
                self._press_modified = bool(
                    getattr(scene, "is_modified", lambda: False)())
            # 左键按下只做选中 / 框选，**不再拖动图元**：移动图元统一走
            # 双击跟手（见 mouseDoubleClickEvent），避免点选时手抖把图元挪走。
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """双击图元 = 抓住它（跟手）；左键按下拖动图元已被取消，走这里。

        与旧 Core 一致的地方：子图元不能单独拖，双击子图元抓的是它的根父对象；
        运行态 / 绘制中不启用。选中集合里有别的图元时整组一起跟手（与拖动
        多选的语义一致），位移都按光标增量施加。
        """
        if event.button() != Qt.LeftButton:
            return super().mouseDoubleClickEvent(event)
        target = self._follow_target_at(event.position().toPoint())
        if target is None:
            return super().mouseDoubleClickEvent(event)
        self.begin_follow(target, self.mapToScene(event.position().toPoint()))
        event.accept()

    # ------------------------------------------------------------------
    # 双击跟手：抓住图元 → 图元随光标走 → 单击 / Esc 落定
    # ------------------------------------------------------------------
    def _follow_target_at(self, viewport_pos: QPoint):
        """光标下可作为跟手目标的顶层图元（子图元返回根父对象）。"""
        scene = self.scene()
        if (scene is None or getattr(scene, "is_run_mode", False)
                or self._draw_type or self._panning):
            return None
        for it in scene.items(self.mapToScene(viewport_pos)):
            if getattr(it, "item_id", None) is None or not it.isVisible():
                continue
            if not (it.flags() & QGraphicsItem.ItemIsSelectable):
                continue
            if getattr(it, "parent_id", 0):
                root = it.root_parent()
                return None if root is it else root
            return it
        return None

    def begin_follow(self, target, scene_pos: QPointF | None = None) -> bool:
        """开始跟手：确保目标被选中，把被选中的顶层图元挂到光标上。"""
        scene = self.scene()
        if scene is None or target is None:
            return False
        if not target.isSelected():
            scene.clearSelection()
            target.setSelected(True)
        sel = [
            it for it in scene.selected_items()
            if not getattr(it, "parent_id", 0)
            and (it.flags() & QGraphicsItem.ItemIsSelectable)
        ]
        if not sel:
            return False
        self._follow_items = sel
        self._follow_start = [(it, it.page_center()) for it in sel]
        self._follow_cursor = (QPointF(scene_pos) if scene_pos is not None
                               else QPointF(self._last_hover or QPointF()))
        self._follow_dragged = False
        self._snap_offset = QPointF(0.0, 0.0)   # 新的抓取，之前叠加的吸附作废
        self._press_modified = bool(
            getattr(scene, "is_modified", lambda: False)())
        self.setCursor(Qt.ClosedHandCursor)
        self.viewport().update()
        return True

    def _update_follow(self, scene_pos: QPointF, button_held: bool = False) -> None:
        """按光标增量平移跟手图元（增量式才能保住按 T 吸出来的偏移）。"""
        if not self._follow_items:
            return
        if self._follow_cursor is None:
            self._follow_cursor = QPointF(scene_pos)
            return
        delta = scene_pos - self._follow_cursor
        self._follow_cursor = QPointF(scene_pos)
        moved = False
        if abs(delta.x()) > 1e-9 or abs(delta.y()) > 1e-9:
            for it in self._follow_items:
                it.moveBy(delta.x(), delta.y())   # 子图元在 on_item_moved 里随动
            moved = True
        if moved and button_held:
            # 双击后一直按住：松手即落点（"双击拖"手势）
            self._follow_dragged = True
        self.viewport().update()

    def end_follow(self, restore: bool = False) -> None:
        """结束跟手。``restore=True`` 用于 Esc：整组回到抓住时的位置。"""
        if not self._follow_items:
            return
        items = self._follow_items
        starts = self._follow_start
        self._follow_items = []
        self._follow_start = []
        self._follow_cursor = None
        self._follow_dragged = False
        self.unsetCursor()
        scene = self.scene()
        if restore:
            for it, (cx, cy) in starts:
                it.set_page_center(cx, cy)
        if scene is not None:
            if not restore:
                if hasattr(scene, "mark_modified"):
                    scene.mark_modified()
                if hasattr(scene, "geometryChanged"):
                    scene.geometryChanged.emit(items[0] if items else None)
                if hasattr(scene, "contentChanged"):
                    scene.contentChanged.emit()
            self.refresh_snap_points()
        self._notify_drag_done()
        self.viewport().update()

    def is_following(self) -> bool:
        """当前是否处于双击跟手状态（供回归 / 外部判断）。"""
        return bool(self._follow_items)


    def context_page_point(self) -> QPointF | None:
        """最近一次右键点击处的 page 场景坐标。"""
        return self._context_page

    # ------------------------------------------------------------------
    # 拖角改尺寸：选中单一图元时显示 4 个角手柄，按住拖动改宽高
    # ------------------------------------------------------------------
    def _resize_item(self):
        """当前允许拖角的图元：设计模式、单选、可见、不在绘制 / 平移。"""
        scene = self.scene()
        if (scene is None or self._draw_type or self._panning
                or getattr(scene, "is_run_mode", False)
                or not hasattr(scene, "selected_items")):
            return None
        sel = scene.selected_items()
        if len(sel) != 1 or not sel[0].isVisible():
            return None
        return sel[0]

    def _handle_points(self, item) -> dict[str, QPointF]:
        """四个角在视口里的位置（用 snap_points 的端点，自动跟随旋转）。"""
        ends, _ = item.snap_points()
        if len(ends) < 4:
            return {}
        pts = {
            key: QPointF(self.mapFromScene(ends[idx]))
            for key, idx in _CORNER_INDEX.items()
        }
        # 视图缩得很小时四角几乎重合：此时不显示 / 不命中，让点击照常走
        # 原有的「拖图元 / 拖根父对象」链路。
        xs = [p.x() for p in pts.values()]
        ys = [p.y() for p in pts.values()]
        if (max(xs) - min(xs) < _HANDLE_MIN_SPAN
                or max(ys) - min(ys) < _HANDLE_MIN_SPAN):
            return {}
        return pts

    def _handle_at(self, vp) -> str | None:
        """命中测试：返回角名 nw / ne / sw / se，没命中返回 None。"""
        item = self._resize_item()
        if item is None:
            return None
        p = QPointF(vp)
        for key, hp in self._handle_points(item).items():
            if (p - hp).manhattanLength() <= _HANDLE_HIT_PX:
                return key
        return None

    def _begin_resize(self, corner: str, event: QMouseEvent) -> None:
        item = self._resize_item()
        scene = self.scene()
        if item is None or scene is None:
            return
        # 按下瞬间冻结 item 的逆变换：拖动中图元自身在变，用实时变换会让
        # 鼠标局部坐标跟着「追」，比例永远算不准。
        inv, ok = item.sceneTransform().inverted()
        if not ok:
            return
        ends, _ = item.snap_points()
        lp = inv.map(ends[_CORNER_INDEX[corner]])
        la = inv.map(ends[_CORNER_INDEX[_OPPOSITE_INDEX[corner]]])
        d0 = (lp.x() - la.x(), lp.y() - la.y())
        if abs(d0[0]) < 1e-6 or abs(d0[1]) < 1e-6:
            return
        anchor_scene = ends[_CORNER_INDEX[_OPPOSITE_INDEX[corner]]]
        ax, ay = scene.projection.inverse_point(
            anchor_scene.x(), anchor_scene.y())
        self._resize_state = {
            "item": item, "inv": inv, "anchor_local": la,
            "anchor_page": (ax, ay), "d0": d0, "last": (1.0, 1.0),
        }
        self._press_modified = bool(
            getattr(scene, "is_modified", lambda: False)())
        self.setCursor(Qt.SizeFDiagCursor if corner in ("nw", "se")
                       else Qt.SizeBDiagCursor)
        self.viewport().update()

    def _update_resize(self, event: QMouseEvent) -> None:
        st = self._resize_state
        scene = self.scene()
        if st is None or scene is None:
            return
        cur_scene = self.mapToScene(event.position().toPoint())
        lc = st["inv"].map(cur_scene)
        la = st["anchor_local"]
        d1 = (lc.x() - la.x(), lc.y() - la.y())
        # 视图局部轴与 page 轴在 AGV 投影下是交换的（p.size(w,h)=(h,w)）：
        # local y ∝ page 宽 -> sx，local x ∝ page 高 -> sy。
        total = (d1[1] / st["d0"][1], d1[0] / st["d0"][0])
        total = (max(_HANDLE_MIN_SCALE, total[0]),
                 max(_HANDLE_MIN_SCALE, total[1]))
        last = st["last"]
        inc = (total[0] / last[0], total[1] / last[1])
        if abs(inc[0] - 1.0) < 1e-12 and abs(inc[1] - 1.0) < 1e-12:
            return
        # 只传增量：仿射 F(p)=A+(p-A)·s 可复合，等价于「相对按下时的总比例」
        if scene.resize_item_about(st["item"], st["anchor_page"],
                                   inc[0], inc[1]):
            st["last"] = total
        self.viewport().update()

    def _draw_resize_handles(self, painter: QPainter) -> None:
        item = self._resize_item()
        if item is None:
            return
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setPen(QPen(_HANDLE_EDGE, 1.2))
        # 全蓝填充，避免出现白色像素块被「无 ID 白标签」回归误判
        painter.setBrush(QBrush(_HANDLE_COLOR))
        for hp in self._handle_points(item).values():
            painter.drawRect(QRectF(hp.x() - _HANDLE_HALF,
                                    hp.y() - _HANDLE_HALF,
                                    _HANDLE_HALF * 2.0,
                                    _HANDLE_HALF * 2.0))
        painter.restore()

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
        if self._follow_items:
            # 跟手中：不需要按钮按住，光标走到哪图元跟到哪
            self._update_follow(self.mapToScene(event.position().toPoint()),
                                bool(event.buttons() & Qt.LeftButton))
            event.accept()
            return
        if self._resize_state is not None:
            self._update_resize(event)
            event.accept()
            return
        if self._panning and self._pan_enabled:
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
        if self._resize_state is not None:
            self._resize_state = None
            self.unsetCursor()
            scene = self.scene()
            if scene is not None and hasattr(scene, "contentChanged"):
                # 属性面板 / 图层树刷新一次即可，不在拖动中每帧广播
                scene.geometryChanged.emit(None)
                scene.contentChanged.emit()
            self.refresh_snap_points()
            self.viewport().update()
            self._notify_drag_done()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self._follow_items:
            if self._follow_dragged:
                # 双击后接着按住拖过：松手就是落点（与普通拖动一致）
                self.end_follow()
            event.accept()
            return
        if self._panning:
            self._panning = False
            self.unsetCursor()
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
        if key == Qt.Key_Escape and self._follow_items:
            # 跟手中按 Esc：整组放回抓住时的位置（不是落在当前点）
            self.end_follow(restore=True)
            event.accept()
            return
        if key == Qt.Key_Escape and self._draw_type:
            scene = self.scene()
            if scene is not None and getattr(scene, "drawing_active", lambda: False)():
                scene.cancel_draw()
            else:
                self.set_draw_tool(None)
            event.accept()
            return
        if (event.modifiers() & Qt.ControlModifier) and key in (Qt.Key_C, Qt.Key_V):
            # 只在画布有焦点时接管 Ctrl+C/V；不注册窗口级 QAction 快捷键，
            # 否则会抢走属性面板输入框里原生的文本复制 / 粘贴。
            self.actionTriggered.emit("copy" if key == Qt.Key_C else "paste")
            event.accept()
            return
        if key == Qt.Key_Space:
            if not self._pan_enabled:
                # 平移被关掉时空格交还给上层（运行态里它可能用于按钮激活）
                super().keyPressEvent(event)
                return
            self._space_held = True
            self.setCursor(Qt.OpenHandCursor)
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
        # 父子同时选中时只变换顶层：父缩放 / 旋转已经刚体带动了后代，
        # 再单独变换一次子图元就是双重变换。
        batch = (scene.top_level_items(sel)
                 if hasattr(scene, "top_level_items") else sel)
        if key in (Qt.Key_Plus, Qt.Key_Equal):
            for it in batch:
                it.resize_by(1.1)
        elif key == Qt.Key_Minus:
            for it in batch:
                it.resize_by(1.0 / 1.1)
        elif key == Qt.Key_BracketLeft:
            for it in batch:
                it.rotate_by(-5.0)
        elif key == Qt.Key_BracketRight:
            for it in batch:
                it.rotate_by(5.0)
        elif key == Qt.Key_G:
            self.end_follow()          # 跟手中成组：先落定再成组
            if hasattr(scene, "group_selected"):
                scene.group_selected()
        elif key == Qt.Key_U:
            self.end_follow()
            if hasattr(scene, "ungroup_selected"):
                scene.ungroup_selected()
        elif key == Qt.Key_0:
            self.fit_content()
        elif key == Qt.Key_R:
            if scene is not None:
                scene.is_run_mode = not getattr(scene, "is_run_mode", False)
                self.viewport().update()
        elif key == Qt.Key_Delete:
            # 先退出跟手：否则被删的图元还挂在 _follow_items 里，后续鼠标
            # 移动会访问已销毁的 C++ 对象。
            self.end_follow()
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
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        # 跟手状态要收掉：切走再回来时光标已不在原位，继续跟会突然跳一段
        self.end_follow()
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
        if self._follow_items:
            # 跟手中：光标已被挪到捕捉点上，基准跟着改，否则下一次 mouseMove
            # 会把「挪光标这段」再当成位移推一遍，图元越吸越偏。
            self._follow_cursor = QPointF(target)

    def _apply_snap_follow(self, allow_release: bool = True,
                           require_movable: bool = True) -> bool:
        """把光标吸附偏移叠加到选中图元上，返回本次是否真的移动了。

        ``_snap_offset`` 记录「已经叠加过的总偏移」，每帧只补差量，所以：

        * 吸附期间鼠标继续移动 → 图元钉在捕捉点附近不跟着跑（磁性效果）；
        * 鼠标移出阈值 → 差量自动抵消，图元回到跟手位置（``allow_release``）；
        * 同一位置反复按 T → 偏移不变、增量为 0，不会越推越远。

        ``allow_release=False`` 用于 T 键：只做一次正向吸附，鼠标没指到
        任何捕捉点时保持图元不动，避免把之前吸过的偏移又撤回。
        ``require_movable`` 默认 True，只有 ``ItemIsMovable`` 的图元才动；
        视图已取消左键拖动（图元默认不可移动），T 键传 False 才作用到任意类型。

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
        # 设计模式下：选中图元在旋转中心处画一个红色小圆点（最上层，无 ID 文字）
        if self.show_ids and scene is not None and not getattr(scene, "is_run_mode", False):
            self._draw_origin_markers(painter)
            self._draw_selection_marks(painter)
        # 拖角手柄：独立于 show_ids（那是红点开关），设计模式下单选即显示
        if scene is not None and not getattr(scene, "is_run_mode", False):
            self._draw_resize_handles(painter)
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
    # 选中图元旋转中心标记：红色小圆点（仅设计模式，固定屏幕像素）
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
                 if it.has_custom_origin()][:_MAX_SELECTION_MARKS]
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

    def _draw_selection_marks(self, painter: QPainter) -> None:
        """选中图元在**旋转中心**（支点）处画一个红色小圆点。

        默认「绕中心转」时支点即几何中心；用右键「旋转中心设到此处」改过
        支点后，红点跟着挪到支点上（与蓝色支点环同一位置）。
        ID 数字标签已移除，这里只保留位置标识本身。
        """
        scene = self.scene()
        if scene is None or not hasattr(scene, "selected_items"):
            return
        items = scene.selected_items()
        if not items or len(items) > _MAX_SELECTION_MARKS:
            return

        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 1.5))
        painter.setBrush(QBrush(_ID_DOT_COLOR))

        for it in items:
            getter = getattr(it, "pivot_scene_point", None)
            if getter is None:
                getter = getattr(it, "center_scene_point", None)
            scene_pt = getter() if getter is not None else it.scenePos()
            vp = self.mapFromScene(scene_pt)
            painter.drawEllipse(QPointF(float(vp.x()), float(vp.y())),
                                _ID_DOT_RADIUS, _ID_DOT_RADIUS)
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
