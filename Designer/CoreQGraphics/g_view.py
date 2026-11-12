"""QGraphicsView 视图与交互层。

Core 没有独立 view 类（自绘 QWidget 兼视图），这里补一层：
框选 / 平移 / 缩放 / 旋转 / 分组解组 / T 抓起-吸附-对齐 / 红色十字标记。

视图变换保持 Qt 默认（y 向下、无镜像）；AGV 轴交换已在加载时投影进
item 几何，所以文字不会被镜像，画面朝向仍与旧实现一致。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFont, QFontMetrics, QKeyEvent, QMouseEvent,
    QPainter, QPainterPath, QPen, QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication, QGraphicsItem, QGraphicsView, QMenu, QRubberBand,
)

from .g_boolean import BOOLEAN_LABELS, BOOLEAN_OPERATIONS, BOOL_SUBTRACT
from .g_scene import ORTHO_DRAW_TYPES
from .g_snap import GRID_MAJOR_EVERY, GRID_STEP, SnapSystem

ELEMENT_MIME_TYPE = "application/x-coreqg-element"
# 组合模板按钮拖的是模板 id，不是图元类型；与旧设计器共用同一种载荷，
# 但 MIME 单独开一个，落在画布上时由主窗口走 TemplateStore 实例化。
TEMPLATE_MIME_TYPE = "application/x-design-template"

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

# 坐标刻度条：画在**视口像素**里（drawForeground 中 resetTransform），
# 条带位置固定，刻度数值按当前视图变换实时换算。默认关，只有设计器主窗口
# 打开，运行态预览 / RuntimeView 等一律不画，避免污染对拍与现场画面。
_RULER_THICKNESS = 22
_RULER_BG = QColor(248, 249, 251)
_RULER_CORNER_BG = QColor(234, 238, 244)
_RULER_BORDER = QColor(196, 200, 208)
_RULER_TICK = QColor(126, 133, 145)
_RULER_TEXT = QColor(66, 74, 88)
_RULER_ZERO = QColor(34, 96, 178)
_RULER_CURSOR = QColor(214, 51, 46)
_RULER_TARGET_PX = 88.0        # 主刻度的目标屏幕间距
_RULER_MINOR = 5               # 每个主刻度细分几格

# 锁定图元左下角的「双同心圆」标记（固定屏幕像素，只在设计态绘制）。
# 与标尺同理在 drawForeground 里切回视口像素坐标，缩放时不会变形；外圈 +
# 内圈 + 中心点三层，浅色底圆保证压在网格 / 图元填充上仍看得清。
_LOCK_BADGE_OUTER = 6.0
_LOCK_BADGE_INNER = 3.0
_LOCK_BADGE_DOT = 1.1
_LOCK_BADGE_OFFSET = QPointF(7.0, -7.0)   # 相对 AABB 左下角，往右上让一点
_LOCK_BADGE_COLOR = QColor(36, 46, 60)
_LOCK_BADGE_BG = QColor(255, 255, 255, 235)


def nice_ruler_step(scene_per_px: float) -> float:
    """挑 1/2/5×10^n 的场景步长，让主刻度屏幕间距接近目标像素。

    纯函数，便于回归直接测；缩放变化时步长跳档但不会密到数字互相压住。
    """
    raw = max(float(scene_per_px), 1e-9) * _RULER_TARGET_PX
    base = 10.0 ** math.floor(math.log10(raw))
    for m in (1.0, 2.0, 5.0, 10.0):
        if m * base >= raw - 1e-12:
            return m * base
    return 10.0 * base


def ruler_label(value: float, step: float) -> str:
    if step >= 1.0:
        return str(int(round(value)))
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"

# 鼠标附近吸附标记：小于这个屏幕像素的偏移不吸附，避免抖动
_SNAP_MIN_PX = 2.0

# 方向键微调：短按走一格；按住超过延迟后按固定间隔连续走。持续移动由
# 视图自己的定时器驱动（不依赖系统键盘自动重复设置，也不会被 autoRepeat
# 事件叠加成双倍位移）；同时按住两个方向键时走合向量（对角）。
_NUDGE_KEYS = {
    Qt.Key_Left: (-1.0, 0.0), Qt.Key_Right: (1.0, 0.0),
    Qt.Key_Up: (0.0, -1.0), Qt.Key_Down: (0.0, 1.0),
}
_NUDGE_DELAY_MS = 350
_NUDGE_INTERVAL_MS = 80
_NUDGE_FAST_FACTOR = 10.0     # Shift + 方向键 = 一次 10 格
# 捕捉点十字：与旧 Core 一致用纯红（选中中心红点 214,51,46 更暗、支点环是蓝的，
# 三者不会混淆）。吸附系统开启时更饱和、更粗，表示「现在按 T 会吸过去」。
_SNAP_CROSS_COLOR = QColor(255, 0, 0)
_SNAP_CROSS_IDLE = QColor(255, 34, 34)

# 拖角改尺寸手柄（固定屏幕像素，仅设计模式 + 单选时显示）
_HANDLE_HALF = 4.0            # 方块半边长
_HANDLE_HIT_PX = 8.0          # 命中半径（曼哈顿距离）
_HANDLE_MIN_SPAN = 28.0       # 四角屏幕跨度下限：太小的图元不画手柄，
                              # 否则四个手柄挤在中心会抢走「拖动」按下
_HANDLE_MIN_SCALE = 0.02      # 缩到 2% 停住，防止翻转 / 零尺寸
_HANDLE_COLOR = QColor(22, 119, 255)
_HANDLE_EDGE = QColor(12, 70, 160)
# item.frame_corners() 的端点顺序：[左上, 右上, 左下, 右下]
_CORNER_INDEX = {"nw": 0, "ne": 1, "sw": 2, "se": 3}
_OPPOSITE_INDEX = {"nw": "se", "ne": "sw", "sw": "ne", "se": "nw"}


class GraphicsView(QGraphicsView):
    """交互视图。``scene()`` 应为 :class:`GraphicsScene`。"""

    elementDropped = Signal(str, QPointF)   # (type_key, 视图场景坐标)
    templateDropped = Signal(str, QPointF)  # (template_id, 视图场景坐标)
    actionTriggered = Signal(str)           # 右键菜单的统一命令名
    orthoModeChanged = Signal(bool)         # 正交开关（F8 / 菜单）状态变化

    def __init__(self, scene=None, parent=None) -> None:
        super().__init__(parent)
        # 状态先就位：setScene() 里要用到 snap / show_grid
        self.snap = SnapSystem()
        # 吸附点表是否已与场景同步。结构变化（增删 / 分组 / 撤销 / 换页）只
        # 置脏，真正全量重建推迟到下一次需要新鲜点表的时刻（按 T / fit /
        # 交互收尾）；纯属性 / 几何变化则由 itemChanged 立即按 owner 增量修。
        self._snap_full_dirty = True
        self._panning = False
        self._pan_start = QPoint()
        self._space_held = False
        # 画布导航门控：设计态恒开，运行态由子类一次性关掉。
        # 平移与缩放分开两个字段，是因为有的运行窗口只想放开滚轮看细节，
        # 不想让用户把画面拖走（反之亦然）。
        self._pan_enabled = True
        self._zoom_enabled = True
        self.show_grid = True
        # 坐标刻度条：默认关，由 DesignerWindow 显式打开；运行态 / 其它视图
        # 一律保持关闭，标尺不进 scene 渲染、不影响几何对拍与页面数据。
        self.show_rulers = False
        # O 键作为「设置旋转中心」的修饰键：按住 O 时右键把选中图元的旋转中心
        # 钉到点击处（见 mousePressEvent），取代原右键菜单项。
        self._origin_key_held = False
        # 按 O + 右键已消费右键菜单，避免随后弹出的 contextMenuEvent 再画菜单
        self._origin_suppress_menu = False
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
        # 上一次画出去的捕捉十字（重绘区并集用，省一次全量 aim）
        self._drawn_marker: QPointF | None = None
        # 选中项自身捕捉点的缓存（见 _selection_own_points）
        self._own_cache: set | None = None
        self._own_key: tuple | None = None
        # T 键「抓起 → 对齐」：被抓图元的 id 与它那个捕捉点（场景绝对坐标）。
        # 抓手期间图元**不实时跟手**，下一次按 T 才把该点对齐到新的捕捉点。
        # 只存 id 不存图元对象，图元被删除 / 撤销重建后不会留下悬空 C++ 引用。
        self._snap_grab_id: int | None = None
        self._snap_grab_point: QPointF | None = None
        # 绘制模式（CAD 式分点）：激活工具后图元跟随鼠标，点击画布落点
        self._draw_type = ""
        # CAD 正交开关：绘制点列图元时只出屏幕水平 / 竖直段。默认关，
        # 不改变既有绘制语义；按住 Shift 临时反转（见 _ortho_for_event）。
        self._ortho_mode = False
        # 最近一次预览锁定的轴（"H" / "V" / ""），用于画 H/V 提示标签
        self._ortho_axis = ""
        # 右键位置（page 场景坐标）：按住 O + 右键时把选中图元旋转中心设到这里
        self._context_page: QPointF | None = None
        # 拖角改尺寸：按下时冻结的逆变换 / 固定对角 / 上一次的总缩放比例
        self._resize_state: dict | None = None
        self._press_modified = False
        # 方向键微调：按键集合 + 延迟/连发两个定时器。步长默认跟随当前网格，
        # 可用 set_nudge_step() 固定（见 nudge_step）。
        self._nudge_step: float | None = None
        self._nudge_keys: dict[int, tuple[float, float]] = {}
        self._nudge_shift = False
        self._nudge_active = False
        self._nudge_delay = QTimer(self)
        self._nudge_delay.setSingleShot(True)
        self._nudge_delay.timeout.connect(self._start_nudge_repeat)
        self._nudge_repeat = QTimer(self)
        self._nudge_repeat.setInterval(_NUDGE_INTERVAL_MS)
        self._nudge_repeat.timeout.connect(self._nudge_tick)
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
        # 尺寸变化时钉住视口左上角对应的场景点（Qt 的 ``NoAnchor`` 语义）。
        # 默认的 ``AnchorViewCenter`` 会在 dock 显隐 / 分隔条拖动 / 窗口缩放时
        # 保持「视口中心场景点」，画面就跟着上下左右平移（底部属性 dock 展开
        # 一次能推掉半屏高度）；旧 ``Core`` 是自绘 QWidget，``scene_origin``
        # 只在 showEvent 定一次，resize 不动，所以观感上是「画面不动、边缘被裁」。
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        if scene is not None:
            self.setScene(scene)

    # ------------------------------------------------------------------
    # 视图
    # ------------------------------------------------------------------
    def setScene(self, scene) -> None:
        # 换场景（切页 / 关窗）时跟手 / 抓手 / 方向键状态必须作废，否则定时器
        # 会拿着旧场景的图元继续移动；这里直接丢弃，不记撤销。
        self._nudge_delay.stop()
        self._nudge_repeat.stop()
        self._nudge_keys.clear()
        self._nudge_active = False
        self._clear_snap_grab()
        self._follow_items = []
        self._follow_start = []
        self._follow_cursor = None
        self._follow_dragged = False
        old = self.scene()
        if old is not None:
            for name, slot in (
                    ("selectionChanged", self._on_scene_selection_changed),
                    ("geometryChanged", self._invalidate_own_points),
                    ("structureChanged", self._on_structure_changed),
                    ("itemChanged", self._on_items_changed)):
                sig = getattr(old, name, None)
                if sig is not None:
                    try:
                        sig.disconnect(slot)
                    except (RuntimeError, TypeError):
                        pass
        self._invalidate_own_points()
        self._snap_full_dirty = True
        super().setScene(scene)
        if scene is not None:
            scene.selectionChanged.connect(self._on_scene_selection_changed)
            geo = getattr(scene, "geometryChanged", None)
            if geo is not None:
                # 图元被改位姿（跟手 / 属性面板 / 撤销）后，自身捕捉点缓存必须失效
                geo.connect(self._invalidate_own_points)
            st = getattr(scene, "structureChanged", None)
            if st is not None:
                st.connect(self._on_structure_changed)
            ic = getattr(scene, "itemChanged", None)
            if ic is not None:
                ic.connect(self._on_items_changed)
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
        self._invalidate_own_points()
        # 图层树 / 属性面板改了选中、或抓手图元被删掉：抓手就此作废，
        # 别把「已经不在选中里」的图元继续挂着。
        if self._snap_grab_id is not None and self._grabbed_item(
                check_selected=True) is None:
            self._clear_snap_grab()
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
        """全量重建吸附点表（保留给 fit / 换页 / 回归 / 结构变化兜底）。"""
        scene = self.scene()
        self._invalidate_own_points()
        if scene is not None and hasattr(scene, "snap_points_with_owners"):
            ends, mids, owners = scene.snap_points_with_owners()
            self.snap.update_points(ends, mids, owners)
        elif scene is not None and hasattr(scene, "snap_points"):
            # 外部自定义场景只有老接口：点集照建，只是没有归属信息
            ends, mids = scene.snap_points()
            self.snap.update_points(ends, mids)
        self._snap_full_dirty = False

    # ------------------------------------------------------------------
    # 吸附点表：按 owner 增量维护
    # ------------------------------------------------------------------
    def _on_structure_changed(self) -> None:
        """图元集合 / 层级变了：点表标脏，等真正要用时再全量重建。"""
        self._snap_full_dirty = True
        self._invalidate_own_points()

    def _on_items_changed(self, ids) -> None:
        """仅这些图元变了：立刻按 owner 增量重算，点表始终与场景一致。"""
        self.refresh_snap_owners(ids)

    def _expanded_owner_ids(self, ids) -> set[int]:
        """把 ids 的后代一并纳入：父图元移动 / 改尺寸时子图元会被刚体带动，
        它们的捕捉点同样变了，只重算父会漏掉。"""
        scene = self.scene()
        index = getattr(scene, "index", None) if scene is not None else None
        out = {int(i) for i in (ids or ()) if i is not None}
        if index is None:
            return out
        for iid in list(out):
            try:
                for child in index.descendants(iid):
                    out.add(child.item_id)
            except (KeyError, RuntimeError):
                pass
        return out

    def refresh_snap_owners(self, ids) -> None:
        """按 owner 增量刷新：只对这些图元调 ``snap_points()``。

        表未建 / 已标脏 / 不是带归属的全量表时回退到全量重建，保证任何
        情况下「增量结果 == 全量结果」。
        """
        scene = self.scene()
        if scene is None or not hasattr(scene, "snap_points_for"):
            self._snap_full_dirty = True
            return
        if self._snap_full_dirty or not self.snap.is_incremental:
            self.refresh_snap_points()
            return
        todo = self._expanded_owner_ids(ids)
        if not todo:
            return
        self._invalidate_own_points()
        ok = True
        for iid in todo:
            ends, mids = scene.snap_points_for(iid)
            ok = self.snap.update_owner(iid, ends, mids) and ok
        if not ok:
            self.refresh_snap_points()

    def sync_snap_points(self) -> None:
        """需要一份新鲜点表时调用；表已由增量维护好则零成本。"""
        if self._snap_full_dirty:
            self.refresh_snap_points()

    def _ensure_snap_table(self) -> None:
        """取点前保证点表新鲜；绘制态再把临时图元的自身点撤掉。

        绘制图元由 ``create_item(commit=False)`` 建立，几何随预览逐帧变化且
        不广播编辑信号；若把它留在点表里，鼠标一动就留下上一帧的「幽灵
        端点」，下一帧可能吸到自己身上。按 owner 撤登记有引用计数兜底，
        同一坐标上别的图元的点不会被误删。
        """
        self.sync_snap_points()
        if not self._draw_type:
            return
        scene = self.scene()
        item = getattr(scene, "_draw_item", None) if scene is not None else None
        if item is not None:
            self.snap.remove_owners([item.item_id])

    def _emit_changes(self, ids=None, *, structural: bool = False) -> None:
        """交互收尾统一广播（兼容只有老 ``contentChanged`` 的自定义场景）。"""
        scene = self.scene()
        if scene is None:
            return
        if structural:
            if hasattr(scene, "emit_structure_changed"):
                scene.emit_structure_changed()
            elif hasattr(scene, "contentChanged"):
                scene.contentChanged.emit()
        else:
            if hasattr(scene, "emit_items_changed"):
                scene.emit_items_changed(ids)
            elif hasattr(scene, "contentChanged"):
                scene.contentChanged.emit()

    # ------------------------------------------------------------------
    # 绘制模式：激活工具后点击画布落点（矩形/线/圆两击，三角三击，
    # 多边形多击 + 右键闭合，文本/图片/复选框等单击）。参考 Core 的绘制流程。
    # ------------------------------------------------------------------
    def set_draw_tool(self, type_key: str | None) -> None:
        """激活/取消绘制工具。空值取消，恢复框选与默认光标。"""
        self._clear_snap_grab()
        self._ortho_axis = ""
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
        # 工具按钮在 Dock 里，点完按钮焦点留在工具箱：不把焦点收回画布，
        # T / Esc / Shift 这些绘制期按键根本送不到 keyPressEvent，按 T 会
        # 像没反应一样（回归里直接把事件发给 view 恰好绕过了这一点）。
        self.setFocus()
        # 进绘制模式就补一份新鲜点表：结构变化（刚画完 / 刚放下图元）只置脏，
        # 等到按 T 才重建的话，那些图元的端点 / 中点还不在表里，十字只能落在
        # 格点上，看起来就是「识别不了已存在图元的特征点」。
        self.refresh_snap_points()
        self.viewport().update()

    # ------------------------------------------------------------------
    # CAD 正交模式：绘制点列图元时把「上一落点 → 当前光标」锁到屏幕主轴
    # ------------------------------------------------------------------
    def set_ortho_mode(self, enable: bool) -> None:
        """打开 / 关闭正交（F8）。状态由视图持有，菜单按钮只是它的镜像。"""
        on = bool(enable)
        if on == self._ortho_mode:
            return
        self._ortho_mode = on
        self._ortho_axis = ""
        self.orthoModeChanged.emit(on)
        self.viewport().update()

    def is_ortho_mode(self) -> bool:
        return self._ortho_mode

    def _draw_page_point(self, event) -> QPointF:
        """绘制取点的唯一入口：光标 → 吸附 → page → 正交约束。

        第一点与后续点都走这里，``mousePressEvent``（落点）与
        ``mouseMoveEvent``（预览）也共用，所以「十字在哪、预览在哪、点下去
        在哪」必然一致。

        旧版只有按 T 时把 ``aim`` 的结果喂给系统光标（``QCursor.setPos``）
        和预览，落点却仍用未吸附的原始坐标；离屏 / 部分平台 setPos 不会
        同步派发 mouseMove，于是「按 T 看着吸过去了、点下去却没吸」。
        现在落点直接吃与红十字同一份 ``aim`` 结果，不再依赖光标 warp。
        """
        scene = self.scene()
        pos_scene = self.mapToScene(event.position().toPoint())
        if self.snap.enabled:
            self._ensure_snap_table()
            target, _kind = self.snap.aim(
                pos_scene, exclude=self._snap_scan_exclude(), always=True)
            if target is not None:
                pos_scene = QPointF(target)
        cx, cy = scene.projection.inverse_point(pos_scene.x(), pos_scene.y())
        return self._ortho_page_point(QPointF(cx, cy), event.modifiers())

    def _ortho_page_point(self, page_pt: QPointF, modifiers) -> QPointF:
        """把绘制用的 page 点锁到屏幕主轴，返回约束后的点。

        预览与落点都走这一个入口，所以「预览看到的是水平线、点下去就是
        水平线」必然一致。锚点取 ``draw_preview_state()`` 的最后一个落点：
        直线是起点，多段线 / 三角形是刚落下的上一个顶点（逐段锁定，与
        CAD 正交一致）。首点之前没有锚点，原样返回。

        Shift 临时反转（CAD 惯例）：开着时按住 = 临时画斜线，关着时按住 =
        临时画正交线。用传进来的 modifiers 而不是全局键盘状态，画布失焦
        或按键事件顺序变化都不会留下残留。
        """
        scene = self.scene()
        self._ortho_axis = ""
        if self._draw_type not in ORTHO_DRAW_TYPES:
            return page_pt
        temp = bool(modifiers & Qt.ShiftModifier)
        if self._ortho_mode == temp:       # XOR：两值相同即正交不生效
            return page_pt
        state = scene.draw_preview_state() if hasattr(scene, "draw_preview_state") else None
        if state is None or not state[1]:
            return page_pt
        constrained, axis = scene.constrain_ortho(state[1][-1], page_pt)
        self._ortho_axis = axis
        return constrained

    def _refresh_ortho_preview(self, modifiers) -> None:
        """Shift 按下 / 松开时，用上一次光标位置立刻重画预览（不必先动鼠标）。"""
        scene = self.scene()
        if (scene is None or self._last_hover is None
                or not hasattr(scene, "draw_preview")):
            return
        cx, cy = scene.projection.inverse_point(
            self._last_hover.x(), self._last_hover.y())
        scene.draw_preview(self._ortho_page_point(QPointF(cx, cy), modifiers))
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

    def _group_root_at(self, scene_pos: QPointF):
        """设计模式点选：命中「组成员」时返回应真正选中的根组，否则 None。

        group 在画布上按 CAD 的块参照处理：单击组内任何成员都选中整个组，
        成员不能被画布单独选中（要精确编辑成员请用图层树 / 属性面板）。
        只有根祖先是 ``TYPE == "group"`` 才重定向——普通逻辑父子（根是
        rect / text 等）保持「按下只选中它自己」的原语义。运行态不改。
        """
        scene = self.scene()
        if scene is None or getattr(scene, "is_run_mode", False):
            return None
        for it in scene.items(scene_pos):
            if getattr(it, "item_id", None) is None or not it.isVisible():
                continue
            if not (it.flags() & QGraphicsItem.ItemIsSelectable):
                continue
            root = it.root_parent()
            if root is not it and getattr(root, "TYPE", "") == "group":
                return root
            break        # 命中的是顶层图元 / 组框本身，交回基类正常处理
        return None

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
                page_pt = self._draw_page_point(event)
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
            # O + 右键：把选中图元的旋转中心设到点击处（取代原右键菜单项），
            # 不弹右键菜单。只在设计模式、非绘制 / 非平移时生效。
            if (self._origin_key_held and scene is not None
                    and not getattr(scene, "is_run_mode", False)
                    and not self._draw_type and not self._panning):
                self.actionTriggered.emit("origin_here")
                self._origin_suppress_menu = True
                event.accept()
                return
            self._origin_suppress_menu = False
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
            # 组成员不单独选中：点在成员上改成选它的根组；空白处按下仍由
            # 基类启动框选（Qt 只在按下点没有 item 时才画橡皮筋），不受影响。
            root = self._group_root_at(
                self.mapToScene(event.position().toPoint()))
            if root is not None:
                multi = bool(event.modifiers()
                             & (Qt.ControlModifier | Qt.ShiftModifier))
                if not multi:
                    scene.clearSelection()
                for it in list(scene.selected_items()):
                    r = it.root_parent()
                    if it is not r and getattr(r, "TYPE", "") == "group":
                        it.setSelected(False)
                root.setSelected(True)
                event.accept()
                return
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
    def _pose_blocked(self, item) -> bool:
        """设计模式下该图元的位姿是否被锁定（含「子树里有锁定成员」的组）。"""
        scene = self.scene()
        if scene is None or getattr(scene, "is_run_mode", False):
            return False
        if hasattr(scene, "pose_blocked"):
            return bool(scene.pose_blocked(item))
        return bool(getattr(item, "is_locked", lambda: False)())

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
        self._clear_snap_grab()      # 跟手与「T 抓手」互斥，别两套状态同时抓
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
            and not self._pose_blocked(it)   # 锁定项不进跟手集合
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
            # T 抓手：被抓的捕捉点也随图元一起走。下一次按 T 的对齐量是
            # 「新捕捉点 - 记录点」，不跟着更新就会把整段跟手位移重复推一遍。
            if self._snap_grab_point is not None:
                self._snap_grab_point = QPointF(self._snap_grab_point) + delta
                # 图元挪了，自身点坐标全变：排除集合的缓存必须作废，否则
                # 移动中十字会按旧坐标筛选，按 T 时也可能排除错点。
                self._invalidate_own_points()
            moved = True
        if moved and button_held:
            # 双击后一直按住：松手即落点（"双击拖"手势）
            self._follow_dragged = True
        self.viewport().update()

    def end_follow(self, restore: bool = False) -> None:
        """结束跟手。``restore=True`` 用于 Esc：整组回到抓住时的位置。"""
        self._clear_snap_grab()
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
                # 跟手落定：只重算这些图元的捕捉点，不再整页 1618 次
                self._emit_changes([it.item_id for it in items])
            else:
                # Esc 回原位：不标脏、不记编辑，但整组位置变了，点表标脏
                self._snap_full_dirty = True
            self.sync_snap_points()
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
        # 锁定的图元不显示角手柄，也不能拖角改尺寸
        return None if self._pose_blocked(sel[0]) else sel[0]

    def _handle_points(self, item) -> dict[str, QPointF]:
        """四个角在视口里的位置（用**包围盒**四角，自动跟随旋转）。

        不能用 ``snap_points()``：顶点类（线 / 三角 / 多边形 / 路径）的捕捉点
        已经改成真实顶点了，拿它当角锚点会把缩放算错。
        """
        ends = item.frame_corners() if hasattr(item, "frame_corners") else []
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
        ends = item.frame_corners() if hasattr(item, "frame_corners") else []
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
        # 点在组成员上：右键目标也改成根组，避免「画布右键反而把成员选中」
        # 与左键「只能选组」的语义打架。
        root = self._group_root_at(pos)
        for it in scene.items(pos):
            if getattr(it, "item_id", None) is None or not it.isVisible():
                continue
            if not (it.flags() & QGraphicsItem.ItemIsSelectable):
                continue
            target = root or it
            if not target.isSelected():
                scene.clearSelection()
                target.setSelected(True)
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
                scene.draw_preview(self._draw_page_point(event))
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
            st = self._resize_state
            self._resize_state = None
            self.unsetCursor()
            scene = self.scene()
            if scene is not None:
                # 属性面板 / 图层树刷新一次即可，不在拖动中每帧广播
                if hasattr(scene, "geometryChanged"):
                    scene.geometryChanged.emit(None)
                self._emit_changes([st["item"].item_id])
            self.sync_snap_points()
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
    # 键盘微调：方向键按「屏幕方向」把选中图元挪一格
    # ------------------------------------------------------------------
    def nudge_step(self) -> float:
        """一次移动的步长（**视图场景坐标**单位，不是 page 单位）。

        默认跟随 ``SnapSystem.grid_step``，即当前可见网格的一格；它随缩放
        自适应，屏幕上恒为 18~90px。要固定步长用 ``set_nudge_step(50.0)``，
        传 ``None`` 恢复跟随网格。AGV 投影交换了轴，所以这里的一格在 page
        坐标里是 x / y 反向换算，方向键本身始终按屏幕上下左右。
        """
        if self._nudge_step is not None:
            return max(0.0, float(self._nudge_step))
        step = float(getattr(self.snap, "grid_step", 0.0) or 0.0)
        return step if step > 0.0 else float(GRID_STEP)

    def set_nudge_step(self, step: float | None) -> None:
        """覆写方向键步长；``None`` = 恢复跟随当前网格步长。"""
        self._nudge_step = None if step is None else max(0.0, float(step))

    def _nudge_targets(self) -> list:
        """真正被移动的顶层图元。

        先按 ``top_level_items`` 去掉「父子同时选中」（否则父带动子、子又被
        单独挪一次 = 双重变换）；再把仍带父对象的项上溯到根——子图元不能
        自行平移（``set_page_center`` 会拒绝），画布单选组时选中的本来就是
        组，这里覆盖的是「图层树里精确选中了某个成员」的情形：方向键仍把
        整组当成一个原子移动，与画布点选语义一致。
        """
        scene = self.scene()
        if scene is None or not hasattr(scene, "selected_items"):
            return []
        sel = [it for it in scene.selected_items()
               if getattr(it, "item_id", None) is not None]
        if not sel:
            return []
        batch = (scene.top_level_items(sel)
                 if hasattr(scene, "top_level_items") else sel)
        out: list = []
        seen: set[int] = set()
        for it in batch:
            if getattr(it, "translate_locked", lambda: False)():
                root = it.root_parent() if hasattr(it, "root_parent") else None
                if root is not None:
                    it = root
            if getattr(it, "item_id", None) is None or it.item_id in seen:
                continue
            if self._pose_blocked(it):
                continue
            seen.add(it.item_id)
            out.append(it)
        return out

    def _nudge_vector(self) -> tuple[float, float]:
        """当前按住的方向键合向量（已乘步长）。"""
        if not self._nudge_keys:
            return (0.0, 0.0)
        step = self.nudge_step()
        if self._nudge_shift:
            step *= _NUDGE_FAST_FACTOR
        dx = sum(v[0] for v in self._nudge_keys.values()) * step
        dy = sum(v[1] for v in self._nudge_keys.values()) * step
        return (dx, dy)

    def _nudge_by(self, dx: float, dy: float, targets=None) -> bool:
        """按视图场景坐标增量平移，与双击跟手共用 ``moveBy`` 链路：
        ``itemChange`` -> ``on_item_moved`` 负责标脏、支点随行、后代刚体随动。
        移动过程中**不**重建吸附点（page_1 有约 1.4 万个点），留到收尾做一次。
        """
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return False
        items = self._nudge_targets() if targets is None else targets
        if not items:
            return False
        for it in items:
            it.moveBy(dx, dy)
        self.viewport().update()
        return True

    def _handle_nudge_press(self, event: QKeyEvent) -> bool:
        """返回 False = 不接管（交还基类，方向键照常滚动画布）。"""
        key = event.key()
        if key not in _NUDGE_KEYS:
            return False
        mods = event.modifiers()
        if mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        scene = self.scene()
        if (scene is None or getattr(scene, "is_run_mode", False)
                or self._draw_type or self._follow_items):
            return False
        if self.nudge_step() <= 0.0:
            return False
        self._nudge_shift = bool(mods & Qt.ShiftModifier)
        if key in self._nudge_keys:
            # 系统键盘自动重复发来的重复 press：我们自己的定时器在驱动，
            # 吞掉即可，绝不重复移动（否则速度随 OS 键盘设置变化）。
            return True
        targets = self._nudge_targets()
        if not targets:
            return False
        self._nudge_keys[key] = _NUDGE_KEYS[key]
        self._nudge_active = True
        # 新按下的键只走「自己那一步」：若这里用合向量，先按右再按上会
        # 把水平分量重复算一次。合向量只在连发定时器的 tick 里使用。
        step = self.nudge_step() * (_NUDGE_FAST_FACTOR if self._nudge_shift else 1.0)
        ux, uy = _NUDGE_KEYS[key]
        self._nudge_by(ux * step, uy * step, targets)   # 短按只走这一步
        # 已经处于连发时不重启延迟，新方向直接并入合向量继续走
        if self._nudge_repeat.isActive():
            self._nudge_delay.stop()
        else:
            self._nudge_delay.start(_NUDGE_DELAY_MS)
        return True

    def _start_nudge_repeat(self) -> None:
        if self._nudge_keys:
            self._nudge_repeat.start()

    def _nudge_tick(self) -> None:
        dx, dy = self._nudge_vector()
        if not self._nudge_by(dx, dy):
            self._finish_nudge()

    def _finish_nudge(self) -> None:
        """一次连续方向键操作收尾：刷新吸附点 / 面板，并只记一次撤销。"""
        self._nudge_delay.stop()
        self._nudge_repeat.stop()
        if not self._nudge_active:
            return
        self._nudge_active = False
        scene = self.scene()
        ids = [it.item_id for it in self._nudge_targets()]
        if scene is not None:
            if hasattr(scene, "geometryChanged"):
                scene.geometryChanged.emit(None)
            self._emit_changes(ids)
        if not ids:
            self._snap_full_dirty = True
        self.sync_snap_points()
        self.viewport().update()
        # 主窗口的 "drag_done" 分支走 history.commit()：整段连续移动合并成
        # 一个撤销步，不会每 80ms 深拷贝一次 1618 图元的整页快照。
        self.actionTriggered.emit("drag_done")

    # ------------------------------------------------------------------
    # 键盘：T 门控 + 常用编辑
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        scene = self.scene()
        key = event.key()
        if key == Qt.Key_Shift and self._nudge_keys:
            # 先按方向键、后按 Shift：连发定时器的下一步就该加速
            self._nudge_shift = True
        if key in _NUDGE_KEYS:
            if self._handle_nudge_press(event):
                event.accept()
            else:
                # 运行态 / 绘制态 / 跟手 / 无选中：交还基类，方向键滚动画布
                super().keyPressEvent(event)
            return
        if key == Qt.Key_Shift and self._draw_type and not event.isAutoRepeat():
            # 正交的 Shift 临时反转：不挪鼠标也立刻改预览
            self._refresh_ortho_preview(Qt.ShiftModifier)
            event.ignore()
            return
        if key == Qt.Key_Escape and self._follow_items:
            # 跟手中按 Esc：整组放回抓住时的位置（不是落在当前点）
            self.end_follow(restore=True)
            event.accept()
            return
        if key == Qt.Key_Escape and self._draw_type:
            scene = self.scene()
            if scene is not None and getattr(scene, "drawing_active", lambda: False)():
                scene.cancel_draw()
                self._ortho_axis = ""
            else:
                self.set_draw_tool(None)
            event.accept()
            return
        if key == Qt.Key_Escape and self.is_snap_grabbing():
            # 兜底：抓手通常伴随跟手（已由上面的 _follow_items 分支处理，
            # Esc 会整组放回抓住时的位置）；这里只收掉残留的抓手状态。
            self._clear_snap_grab()
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
        if (key == Qt.Key_O
                and not (event.modifiers()
                         & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))):
            # O 只作「设置旋转中心」的修饰键：置位后由 O + 右键消费，本身不触发
            # 任何动作，也不抢 Ctrl+O 等带修饰的快捷键。
            self._origin_key_held = True
            event.accept()
            return
        if key == Qt.Key_T:
            # T 现在是一次性「吸附 / 抓起 / 对齐」动作键，不再是开关门控
            self._snap_action()
            event.accept()
            return
        sel = scene.selected_items() if hasattr(scene, "selected_items") else []
        # 父子同时选中时只变换顶层：父缩放 / 旋转已经刚体带动了后代，
        # 再单独变换一次子图元就是双重变换。
        batch = (scene.top_level_items(sel)
                 if hasattr(scene, "top_level_items") else sel)
        # 锁定项（以及含锁定成员的组）不参与快捷键缩放 / 旋转
        pose_batch = [it for it in batch if not self._pose_blocked(it)]
        if key in (Qt.Key_Plus, Qt.Key_Equal):
            for it in pose_batch:
                it.resize_by(1.1)
        elif key == Qt.Key_Minus:
            for it in pose_batch:
                it.resize_by(1.0 / 1.1)
        elif key == Qt.Key_BracketLeft:
            for it in pose_batch:
                it.rotate_by(-5.0)
        elif key == Qt.Key_BracketRight:
            for it in pose_batch:
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
        if event.key() == Qt.Key_Shift:
            self._nudge_shift = False
        if event.key() in _NUDGE_KEYS and not event.isAutoRepeat():
            self._nudge_keys.pop(event.key(), None)
            if not self._nudge_keys:
                self._finish_nudge()
        if event.key() == Qt.Key_Shift and self._draw_type:
            self._refresh_ortho_preview(Qt.NoModifier)
        if event.key() == Qt.Key_Space:
            self._space_held = False
            if not self._panning:
                self.unsetCursor()
        if event.key() == Qt.Key_O:
            self._origin_key_held = False
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        # 跟手状态要收掉：切走再回来时光标已不在原位，继续跟会突然跳一段
        self.end_follow()
        # 焦点切走时系统可能不再补发 keyRelease，方向键状态在这里兜底收尾
        self._nudge_keys.clear()
        self._nudge_shift = False
        self._finish_nudge()
        # O 键状态一并清掉，避免焦点切走后卡在「按住 O」的假状态
        self._origin_key_held = False
        self._origin_suppress_menu = False
        super().focusOutEvent(event)

    # ------------------------------------------------------------------
    # 吸附：以**鼠标位置**为基准，鼠标吸了多少偏移，选中图元就移动多少
    # ------------------------------------------------------------------
    def _selection_own_points(self) -> set:
        """选中项自身的捕捉点：拖动自己时不能吸到自己身上。

        ``_hover_marker`` / ``_apply_snap_follow`` 每次鼠标移动都要这份集合，
        而全选 1600 个图元时它有一万多个点（每次重算约 60ms，鼠标会明显发涩），
        所以按选中集合缓存；几何变化（``geometryChanged`` / ``refresh_snap_points``
        / 换场景）时显式失效。

        **共享坐标例外**：排除的是「选中图元的特征点」，不是「这个坐标」。
        若同一坐标上还有**未选中**图元的点（对齐时极常见：被抓图元的端点已经
        跟手挪到目标图元的端点上，两点重合），就必须保留，否则目标点会一起
        消失，按 T 只能吸到旁边的格点。判据走 ``SnapSystem.owners_at`` 的
        坐标 -> 图元归属表，按 owner 过滤而不是按坐标一刀切。
        """
        scene = self.scene()
        own: set = set()
        if scene is None or not hasattr(scene, "selected_items"):
            return own
        sel = scene.selected_items()
        key = tuple(it.item_id for it in sel)
        if self._own_cache is not None and key == self._own_key:
            return self._own_cache
        for it in sel:
            e, m = it.snap_points()
            for p in e + m:
                own.add((p.x(), p.y()))
        sel_ids = set(key)
        shared = {
            c for c in own
            if any(iid not in sel_ids
                   for iid in self.snap.owners_at(QPointF(c[0], c[1])))
        }
        own -= shared
        self._own_cache, self._own_key = own, key
        return own

    def _draw_own_points(self) -> set:
        """正在绘制的临时图元**自身**的捕捉点：取点吸附不能吸到自己。

        ``begin_draw_tool`` 用 ``create_item(commit=False)`` 建图元，它同样进了
        ``index.by_id``；可见类型（line / rect / circle / text ...）的端点 / 中点
        会被 ``snap_points_with_owners`` 收进捕捉点表，但它没被选中，所以
        ``_selection_own_points()`` 抓不到。不排除就会吸到自己刚落的点或预览
        端点，等于自我牵引。

        只排除「**只有**绘制图元自己」的坐标：若同一坐标上还有别的图元的点
        （例如从已有图元的端点起画），那是合法捕捉目标，必须保留。判据同样
        走 ``SnapSystem.owners_at``，避免按坐标一刀切。
        """
        scene = self.scene()
        item = getattr(scene, "_draw_item", None) if scene is not None else None
        if item is None:
            return set()
        try:
            e, m = item.snap_points()
            iid = item.item_id
        except RuntimeError:      # 绘制图元已被销毁
            return set()
        own = {(p.x(), p.y()) for p in e + m}
        if not own:
            return own
        return {c for c in own
                if set(self.snap.owners_at(QPointF(c[0], c[1]))) <= {iid}}

    def _snap_scan_exclude(self) -> set:
        """本次捕捉点扫描要排除的坐标。

        **绘制态只排除正在画的临时图元自身点**：绘制时没有任何图元跟着
        光标动，已选中图元的特征点恰恰是最常用的起画 / 对齐目标（刚画完
        的图元默认就是选中态）。旧口径把选中项自身点一并排掉，结果是想
        从已有矩形的角上起画一条线，十字却只能落到旁边的格点上 —— 表现
        正是「识别不了已存在图元的特征点」。

        非绘制态仍按旧口径排除选中项自身点（移动 / 抓手时不吸自己）。
        显示（``_hover_marker``）、吸附（``_snap_action``）、落点
        （``_draw_page_point``）都走这一份，口径不会分叉。
        """
        if self._draw_type:
            return self._draw_own_points()
        return self._selection_own_points()

    def _invalidate_own_points(self, *_args) -> None:
        self._own_cache = None
        self._own_key = None

    def _view_scale(self) -> float:
        scale = abs(self.transform().m11())
        return scale if scale > 1e-9 else 1.0

    def _warp_cursor_to_snap(self, target: QPointF | None = None) -> None:
        """把系统光标也挪到捕捉点上（旧 Core ``warp_cursor`` 的等价物）。

        ``target`` 由调用方直接给定时就是本次按 T 吸到的那个点，**不再重算**
        ``_hover_marker()``：抓起图元后它已被选中，刚吸到的点立刻变成「选中项
        自身的点」被排除，重算会漂到旁边的格点 / 别的图元点上 —— 表现就是
        「按 T 鼠标没有吸附到图元的捕捉点」。

        图元与光标走的是同一个偏移，所以挪完仍然对位。状态必须先归位再挪光标：
        某些平台 ``QCursor.setPos`` 会同步派发 ``mouseMoveEvent``，那时
        ``_follow_cursor`` 必须已经是新位置，否则 warp 会被当成一次拖动。
        光标不在画布上时调用方不会调这里，不会把鼠标从别的窗口劫走。
        """
        if target is None:
            target, _active = self._hover_marker()
        if target is None:
            return
        target = QPointF(target)
        vp = self.mapFromScene(target)
        # 光标只会落在整像素上，mapToScene(vp) 与 target 通常差不到 1 个单位。
        # 跟手基准记这个「实际落点」：warp 派发出来的 mouseMove 算出的增量
        # 就是 0，图元不会在按 T 的瞬间微微跳一下。
        landed = self.mapToScene(vp)
        self.snap.hover = QPointF(target)
        self._last_hover = QPointF(target)
        self._snap_offset = QPointF(0.0, 0.0)
        if self._follow_items:
            self._follow_cursor = QPointF(landed)
        QCursor.setPos(self.viewport().mapToGlobal(vp))

    def _apply_snap_follow(self, allow_release: bool = True,
                           require_movable: bool = True) -> bool:
        """（历史兼容入口，T 键已不再调用）把吸附偏移叠加到选中图元上。

        ``_snap_action()`` 现在只在**已抓手**时移动图元（``_align_grab_to``）；
        仅选中 / 未选中状态下按 T 只挪光标，不再走这里。保留方法仅为兼容
        可能的外部调用，设计器自身没有任何调用点。

        ``_snap_offset`` 记录「已经叠加过的总偏移」，每帧只补差量，所以：

        * 吸附期间鼠标继续移动 → 图元钉在捕捉点附近不跟着跑（磁性效果）；
        * 鼠标移出阈值 → 差量自动抵消，图元回到跟手位置（``allow_release``）；
        * 同一位置反复按 T → 偏移不变、增量为 0，不会越推越远。

        ``allow_release=False`` 原用于 T 键的一次性正向吸附（现已不再由 T
        触发）：鼠标没指到任何捕捉点时保持图元不动，避免把之前吸过的偏移撤回。
        ``require_movable`` 默认 True，只有 ``ItemIsMovable`` 的图元才动；
        视图已取消左键拖动（图元默认不可移动），T 键传 False 才作用到任意类型。

        吸附目标用 ``always=True`` 取「最近的捕捉点」：附近有端点 / 中点就吸它，
        没有就吸最近的格子交汇点。因此**每个图元类型**（含顶点类、文本、图片、
        成组）按 T 都能动，不会出现「有的图元按 T 没反应」。

        选中项**自己**的捕捉点会被跳过（十字照样画在那里，但不吸）：吸到自己
        身上等于「点随图元动」，每帧再按 offset 叠加一次会把图元指数级甩飞。
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

        target, _kind = self.snap.aim(hover, exclude=self._snap_scan_exclude(),
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
    # T 键：吸附光标 → 抓起图元 → 下一次按 T 把抓起的捕捉点对齐过去
    # ------------------------------------------------------------------
    def is_snap_grabbing(self) -> bool:
        """当前是否抓着某个图元的捕捉点（供回归 / 外部判断）。"""
        return self._snap_grab_id is not None

    def snap_grab_point(self) -> QPointF | None:
        """记录的被抓捕捉点（场景绝对坐标）；未抓手返回 None。"""
        return (QPointF(self._snap_grab_point)
                if self._snap_grab_point is not None else None)

    def _clear_snap_grab(self) -> None:
        """退出抓手：换场景 / 选中变化 / Esc / 失焦 / 切工具。"""
        had = self._snap_grab_id is not None
        self._snap_grab_id = None
        self._snap_grab_point = None
        if had and not self._follow_items:
            self.unsetCursor()

    def _grabbed_item(self, check_selected: bool = False):
        """抓手图元（子图元返回根父对象）；图元被删 / 取消选中返回 None。"""
        scene = self.scene()
        if scene is None or self._snap_grab_id is None:
            return None
        index = getattr(scene, "index", None)
        item = index.by_id.get(self._snap_grab_id) if index is not None else None
        if item is None:
            return None
        if check_selected and not item.isSelected():
            return None
        try:
            return item.root_parent() if item.parent_id else item
        except RuntimeError:      # 图元 C++ 对象已被销毁
            return None

    def _grab_item_for_point(self, target: QPointF):
        """这个捕捉点来自哪个可抓起的顶层图元；网格点 / 无归属返回 None。"""
        scene = self.scene()
        index = getattr(scene, "index", None) if scene is not None else None
        if index is None:
            return None
        selected = ({it.item_id for it in scene.selected_items()}
                    if hasattr(scene, "selected_items") else set())
        for iid in self.snap.owners_at(target):
            item = index.by_id.get(iid)
            if item is None or not item.isVisible():
                continue
            if not (item.flags() & QGraphicsItem.ItemIsSelectable):
                continue
            # 已选中图元（或其父）的特征点已被排除，不该再被抓起
            if item.item_id in selected or item.parent_id in selected:
                continue
            target = item.root_parent() if item.parent_id else item
            # 锁定的图元不能被 T 抓起（抓起后会跟着光标走）
            if self._pose_blocked(target):
                continue
            return target
        return None

    def _begin_snap_grab(self, item, point: QPointF) -> None:
        """抓起：选中该图元、记住它的捕捉点，并进入**实时跟手**。

        「抓手模式」就是项目里双击抓图元的那套（ClosedHandCursor）：鼠标走到
        哪图元跟到哪，被抓的捕捉点由 ``_update_follow`` 同步平移；下次按 T
        再把该点精修吸附到新的捕捉点上。
        """
        scene = self.scene()
        if scene is None or self._draw_type:
            # 绘制阶段绝不抓起（双保险：_snap_action 已提前返回绘制分支）
            return
        self._clear_snap_grab()
        scene.clearSelection()
        item.setSelected(True)
        # begin_follow 内部会 _clear_snap_grab（此刻已空），所以抓手字段
        # 必须在它之后再设，否则会被清掉。
        if not self.begin_follow(item, QPointF(point)):
            return
        self._snap_grab_id = item.item_id
        self._snap_grab_point = QPointF(point)
        self._invalidate_own_points()

    def _align_grab_to(self, target: QPointF) -> None:
        """把被抓图元整体平移，使被抓的捕捉点精确落到 target；记录同步更新。

        抓手期间图元只做刚体平移，所以「被抓点」当前位置就是记录值（实时跟手
        时由 ``_update_follow`` 逐帧同步）；``target - 记录值`` 既是图元的
        位移，也是记录的更新量。跟手集合整体平移，保持多选时的相对位置。
        """
        scene = self.scene()
        item = self._grabbed_item()
        if (scene is None or item is None or self._snap_grab_point is None
                or self._pose_blocked(item)):
            self._clear_snap_grab()
            return
        delta = target - self._snap_grab_point
        self._snap_grab_point = QPointF(target)
        if abs(delta.x()) < 1e-9 and abs(delta.y()) < 1e-9:
            return
        movers = list(self._follow_items) if self._follow_items else [item]
        if not any(it is item for it in movers):
            movers.append(item)
        for it in movers:
            if not self._pose_blocked(it):
                it.moveBy(delta.x(), delta.y())
        if hasattr(scene, "mark_modified"):
            scene.mark_modified()
        if hasattr(scene, "geometryChanged"):
            scene.geometryChanged.emit(item)
        if hasattr(scene, "geometryChanged"):
            scene.geometryChanged.emit(item)
        self._emit_changes([it.item_id for it in movers])
        # 图元挪了：只重算这些 owner 的捕捉点 / 自身点缓存 / 归属表
        self.sync_snap_points()
        self.actionTriggered.emit("drag_done")   # 记一个撤销点

    def _snap_action(self) -> None:
        """按 T 的一次性动作：光标吸附到最近捕捉点 + 抓起 / 对齐。

        * 未抓手且点**来自图元** → 选中该图元、进入抓手（**实时跟手**）、
          记录它的捕捉点；鼠标走到哪，图元和那个捕捉点就跟到哪；
        * 已抓手 → 把被抓图元平移，使被抓点精确落到新捕捉点，记录同步更新；
          抓手 / 跟手保持，可继续移动或连续对齐；
        * 未抓手（仅选中 / 未选中）时**绝不移动任何图元**：只把光标 warp 到
          捕捉点；点来自图元时选中并抓起它（抓起瞬间同样不改位置）。
          图元因吸附而移动**只发生在已处于抓手的对齐分支**。
        * **绘制工具激活时**（``_draw_type`` 非空）→ 只把光标 / 待落点吸到
          捕捉点并同步预览，不选中、不抓手、不跟手、不移动任何图元。

        光标 warp 用的是**本次算出的 target**，不是重算 ``_hover_marker()``：
        抓起后该点立刻变成「选中项自身的点」被排除，重算会漂到旁边的格点，
        表现就是「按 T 鼠标没有吸附到图元的捕捉点」。

        「自身」点由 ``_snap_scan_exclude()`` 从扫描里**彻底剔除**：已选中
        图元的特征点，以及绘制阶段正在画的临时图元自身的端点 / 中点。既不
        吸附、也不画十字。
        """
        scene = self.scene()
        if scene is None:
            return
        # 一次性动作键：吸附系统恒开（十字常亮为可吸状态），不再按 T 关闭；
        # 外部仍可直接设 snap.enabled=False 关掉门控（回归 / 运行态各管各的）。
        # 先打开门控再判 hover：从工具箱切进绘制、鼠标还没进过画布时按 T，
        # 也应当让随后的第一点按同一份 aim 结果吸附。
        self.snap.enabled = True
        # 第一点之前 / 之后统一走这一条：结构变化只置脏才全量重建，绘制
        # 临时图元的自身点由 remove_owners 撤掉，不再分叉成两条路径。
        self._ensure_snap_table()
        # 记录「鼠标此刻是否还在画布上」：leaveEvent 会清 hover，那时只把图元
        # 吸过去，不去劫持别的窗口里的鼠标。
        cursor_on_canvas = self.snap.hover is not None
        hover = (self.snap.hover if cursor_on_canvas else self._last_hover)
        if hover is None:
            # 刚点完工具箱按钮、还没在画布上移动过鼠标时 hover 是 None。
            # 用全局光标补一个，让「按 T 立刻吸到最近的红十字」仍然成立。
            vp = self.viewport().mapFromGlobal(QCursor.pos())
            if self.viewport().rect().contains(vp):
                hover = self.mapToScene(vp)
                cursor_on_canvas = True
        if hover is None:
            # 光标确实不在画布上：只把吸附打开、点表备好，等下一次落点。
            self.viewport().update()
            return
        hover = QPointF(hover)
        if self.snap.hover is None:
            self.snap.hover = QPointF(hover)
        target, kind = self.snap.aim(
            hover, exclude=self._snap_scan_exclude(), always=True)
        if target is None:
            return
        target = QPointF(target)
        if self._draw_type:
            # 绘制中按 T：只把光标 / 待落点吸附到捕捉点，**不选中已有图元、
            # 不进入抓手跟手、也不平移任何图元**。跟手会抢走 mouseMoveEvent
            # 的绘制预览分支，逐点落子流程直接断掉；绘制阶段 T 只是 CAD 的
            # 「取点吸附」，不是搬图元。
            if cursor_on_canvas or self.viewport().underMouse():
                self._warp_cursor_to_snap(target)
            self._sync_draw_preview_to_snap(target)
            self.viewport().update()
            return
        grabbed = self._grabbed_item()
        if grabbed is not None and self._snap_grab_point is not None:
            self._align_grab_to(target)
        else:
            # 未抓手：只移动光标，绝不把吸附偏移叠加到「已选中」图元上。
            # 旧版这里曾调 _apply_snap_follow() 平移选中项（鼠标吸多少、
            # 图元就走多少），已按需求移除 —— 图元只有在被抓手抓住后、
            # 再次按 T 对齐时才移动。
            # 已经在跟手（双击抓着别的图元）时不额外抓起。
            if kind == "element" and not self._follow_items:
                item = self._grab_item_for_point(target)
                if item is not None:
                    self._begin_snap_grab(item, target)
        if cursor_on_canvas or self.viewport().underMouse():
            self._warp_cursor_to_snap(target)
        self.viewport().update()

    def _sync_draw_preview_to_snap(self, target: QPointF) -> None:
        """绘制中按 T：把吸附点同步进绘制预览。

        预览与落点共用 ``_ortho_page_point``（正交约束都在这里做），所以
        「按 T 吸过去看到的预览」和「点下去的落点」口径一致。warp 派发的
        mouseMove 也会刷一次预览，这里再按精确捕捉点覆盖一遍。
        """
        scene = self.scene()
        if scene is None or not hasattr(scene, "draw_preview"):
            return
        cx, cy = scene.projection.inverse_point(target.x(), target.y())
        page_pt = self._ortho_page_point(QPointF(cx, cy),
                                         QApplication.keyboardModifiers())
        scene.draw_preview(page_pt)

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
        # 坐标刻度条画在最上层（设计态才有，运行预览不显示）
        if self.show_rulers and scene is not None and not getattr(scene, "is_run_mode", False):
            self._draw_rulers(painter)
        # 锁定图元的同心圆标记：常显，不依赖选中；运行态一律不画
        if scene is not None and not getattr(scene, "is_run_mode", False):
            self._draw_lock_badges(painter)

    def _draw_lock_badges(self, painter: QPainter) -> None:
        """锁定图元左下角的两个同心圆（固定屏幕像素）。

        位置取 ``sceneBoundingRect()`` 的左下角：它是视口里稳定的 AABB，
        旋转图元也不会把标记甩到奇怪的方向。刻意不用 ``viewportMargins``，
        标记只是叠在最上层的装饰，命中测试 / fit / resize 口径零改动。
        """
        scene = self.scene()
        if scene is None or getattr(scene, "is_run_mode", False):
            return
        vp = self.viewport()
        w, h = vp.width(), vp.height()
        edge = _LOCK_BADGE_OUTER + 2.0
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(_LOCK_BADGE_COLOR, 1.2)
        for it in scene.all_items():
            if not it.isVisible() or not getattr(it, "is_locked", lambda: False)():
                continue
            r = it.sceneBoundingRect()
            p = QPointF(self.mapFromScene(QPointF(r.left(), r.bottom())))
            p += _LOCK_BADGE_OFFSET
            if (p.x() < -edge or p.y() < -edge
                    or p.x() > w + edge or p.y() > h + edge):
                continue
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(_LOCK_BADGE_BG))
            painter.drawEllipse(p, edge, edge)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(pen)
            painter.drawEllipse(p, _LOCK_BADGE_OUTER, _LOCK_BADGE_OUTER)
            painter.drawEllipse(p, _LOCK_BADGE_INNER, _LOCK_BADGE_INNER)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(_LOCK_BADGE_COLOR))
            painter.drawEllipse(p, _LOCK_BADGE_DOT, _LOCK_BADGE_DOT)
        painter.restore()

    def _draw_rulers(self, painter: QPainter) -> None:
        """顶部 / 左侧坐标刻度条，画在**视口像素**里。

        ``drawForeground`` 的 painter 带着「场景→视口」变换，先
        ``resetTransform()`` 切回视口像素，条带就钉在画布上边 / 左边，平移
        缩放都不漂移；刻度数值由 ``mapToScene`` 反算，跟着实时变。刻意不设
        ``viewportMargins``：所有命中测试、fit、resize 钉角仍用原来的视口
        口径，零改动。
        """
        vp = self.viewport()
        w, h = vp.width(), vp.height()
        t = _RULER_THICKNESS
        if w <= t * 2 or h <= t * 2:
            return
        p0 = self.mapToScene(QPoint(0, 0))
        pr = self.mapToScene(QPoint(w, 0))
        pb = self.mapToScene(QPoint(0, h))
        dx = (pr.x() - p0.x()) / w
        dy = (pb.y() - p0.y()) / h
        if abs(dx) < 1e-9 or abs(dy) < 1e-9:
            return
        step_x = nice_ruler_step(abs(dx))
        step_y = nice_ruler_step(abs(dy))

        painter.save()
        painter.resetTransform()
        painter.setClipping(False)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setFont(QFont("Arial", 8))
        painter.fillRect(QRect(0, 0, w, t), _RULER_BG)
        painter.fillRect(QRect(0, 0, t, h), _RULER_BG)
        painter.setPen(QPen(_RULER_BORDER, 1.0))
        painter.drawLine(QPoint(0, t), QPoint(w, t))
        painter.drawLine(QPoint(t, 0), QPoint(t, h))

        # 水平标尺：场景 x，主刻度带数字、其间均分短刻度
        lo, hi = sorted((p0.x(), pr.x()))
        value = math.floor(lo / step_x) * step_x
        guard = 0
        while value <= hi + 1e-9 and guard < 400:
            x = int(round((value - p0.x()) / dx))
            if x >= t:
                painter.setPen(QPen(_RULER_TICK, 1.0))
                for k in range(1, _RULER_MINOR):
                    xx = int(round(
                        (value + step_x * k / _RULER_MINOR - p0.x()) / dx))
                    if xx >= t:
                        painter.drawLine(QPoint(xx, t - 4), QPoint(xx, t - 1))
                zero = abs(value) < step_x * 1e-6
                painter.setPen(QPen(_RULER_ZERO if zero else _RULER_TICK, 1.0))
                painter.drawLine(QPoint(x, t - 9), QPoint(x, t - 1))
                painter.setPen(_RULER_TEXT)
                painter.drawText(QPoint(x + 2, t - 10),
                                 ruler_label(value, step_x))
            value += step_x
            guard += 1

        # 垂直标尺：场景 y，数字旋转 -90° 沿条带向上读
        lo, hi = sorted((p0.y(), pb.y()))
        value = math.floor(lo / step_y) * step_y
        guard = 0
        while value <= hi + 1e-9 and guard < 400:
            y = int(round((value - p0.y()) / dy))
            if y >= t:
                painter.setPen(QPen(_RULER_TICK, 1.0))
                for k in range(1, _RULER_MINOR):
                    yy = int(round(
                        (value + step_y * k / _RULER_MINOR - p0.y()) / dy))
                    if yy >= t:
                        painter.drawLine(QPoint(t - 4, yy), QPoint(t - 1, yy))
                zero = abs(value) < step_y * 1e-6
                painter.setPen(QPen(_RULER_ZERO if zero else _RULER_TICK, 1.0))
                painter.drawLine(QPoint(t - 9, y), QPoint(t - 1, y))
                painter.save()
                painter.translate(t - 11, y - 2)
                painter.rotate(-90)
                painter.setPen(_RULER_TEXT)
                painter.drawText(QPoint(0, 0), ruler_label(value, step_y))
                painter.restore()
            value += step_y
            guard += 1

        # 左上角交叉块：盖住两条带的交叠，画个小十字
        painter.fillRect(QRect(0, 0, t, t), _RULER_CORNER_BG)
        painter.setPen(QPen(_RULER_BORDER, 1.0))
        painter.drawRect(QRect(0, 0, t, t))
        painter.setPen(QPen(_RULER_TICK, 1.0))
        painter.drawLine(QPoint(6, t // 2), QPoint(t - 6, t // 2))
        painter.drawLine(QPoint(t // 2, 6), QPoint(t // 2, t - 6))

        # 当前光标位置的红色短线（截图里那条红色指示）
        if vp.underMouse():
            cur = vp.mapFromGlobal(QCursor.pos())
            if 0 <= cur.x() <= w and 0 <= cur.y() <= h:
                painter.setPen(QPen(_RULER_CURSOR, 1.0))
                if cur.x() >= t:
                    painter.drawLine(QPoint(cur.x(), t - 11), QPoint(cur.x(), t))
                if cur.y() >= t:
                    painter.drawLine(QPoint(t - 11, cur.y()), QPoint(t, cur.y()))
        painter.restore()

    def _hover_marker(self) -> tuple[QPointF | None, bool]:
        """光标处该显示的那**一个**捕捉点，以及它此刻是否真的会吸附。

        ``always=True``：附近没端点 / 中点时退到最近的格子交汇点，保证「光标
        附近始终只有一个十字」——大图元内部也有标记可吸。

        **自身点彻底不纳入扫描**：``exclude`` 用 ``_snap_scan_exclude()``，
        既剔除已选中图元的特征点，也剔除绘制阶段正在画的临时图元自身的
        端点 / 中点，所以既不吸附、也不画十字。旧版曾有「自身点画细十字」
        的特判，结果是十字画在自己身上、``_warp_cursor_to_snap`` 也把光标
        挪过去，而 ``_apply_snap_follow`` 吸到的却是别处的点 —— 按 T 后
        光标与图元错位。现在显示、吸附、warp 三者共用同一份 ``aim`` 结果。

        取点表在这里兜底同步：增删图元只置脏，若等到按 T 才重建，绘制
        过程中十字会一直停在格点上，看不到刚放下的图元端点 / 中点。
        """
        self._ensure_snap_table()
        hover = self.snap.hover
        if hover is None:
            return None, False
        target, _kind = self.snap.aim(
            hover, exclude=self._snap_scan_exclude(), always=True)
        return target, bool(self.snap.enabled)

    def _draw_hover_snap_points(self, painter: QPainter) -> None:
        """只画**最近的那一个**捕捉点（固定屏幕像素）。

        把附近所有候选点都画出来时，端点 / 中点 / 格点在同一小片区域里会挤成
        一片十字，反而看不出「松手会吸到哪」。``aim()`` 已经按「图元点优先、
        格点严格更近才顶替」排出了最近点，直接画它：门控打开时加粗 + 套圆环
        （表示按 T 会吸过去），门控关闭时只画细十字当预告。

        红色十字先描一圈半透明深色底：捕捉点常常正好落在图元的黑色描边上，
        只画 1px 红线会被描边吃掉，看着就像「端点上没有十字」（旧 Core 也是
        纯红 1px，同样容易被盖住）。
        """
        target, active = self._hover_marker()
        self._drawn_marker = QPointF(target) if target is not None else None
        if target is None:
            return
        vp = QPointF(self.mapFromScene(target))
        half = 10.0 if active else 8.0
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing, True)
        arms = (
            (QPointF(vp.x() - half, vp.y()), QPointF(vp.x() + half, vp.y())),
            (QPointF(vp.x(), vp.y() - half), QPointF(vp.x(), vp.y() + half)),
        )
        # 深色底：让红字在黑描边 / 亮网格上都有对比
        halo = QPen(QColor(20, 20, 20, 110), 2.6 if active else 2.2)
        halo.setCapStyle(Qt.RoundCap)
        painter.setPen(halo)
        for a, b in arms:
            painter.drawLine(a, b)
        pen = QPen(_SNAP_CROSS_COLOR if active else _SNAP_CROSS_IDLE, 
                   2.0 if active else 1.4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        for a, b in arms:
            painter.drawLine(a, b)
        # if active:
        #     painter.setBrush(Qt.NoBrush)
        #     painter.drawEllipse(vp, 8.5, 8.5)
        painter.restore()

    def _set_hover(self, scene_pt: QPointF | None) -> None:
        """更新光标场景坐标，并只重绘「旧位置 + 新位置 + 标记」几小块区域。"""
        old = self.snap.hover
        old_marker = self._drawn_marker
        self.snap.hover = QPointF(scene_pt) if scene_pt is not None else None
        if scene_pt is not None:
            self._last_hover = QPointF(scene_pt)
        if not self.snap.show_markers:
            return
        # 捕捉点可能落在离光标几十像素外的格点 / 邻图元端点上（放大后更远），
        # 只刷光标周围会留下旧十字的残影，所以把新旧标记位置一起并入重绘区。
        new_marker = self._hover_marker()[0]
        for p in (old, self.snap.hover, old_marker, new_marker):
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

        默认「绕中心转」时支点即几何中心；用 O + 右键「旋转中心设到此处」改过
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
            if type_key == "bezier":
                # 四击定曲线：已落点依次是 P0/C1/C2，光标补齐 P3。
                # 曲线本体由图元自己实时画，这里只补两条手柄线，避免重影。
                ctrl = list(pts_view[:4]) + [prev_view] * max(
                    0, 4 - len(pts_view[:4]))
                painter.drawLine(ctrl[0], ctrl[1])
                painter.drawLine(ctrl[3], ctrl[2])
            else:
                painter.drawLine(pts_view[0], prev_view)
            if type_key == "rect":
                r = QRectF(pts_view[0], prev_view).normalized()
                painter.drawRect(r)
            elif type_key == "circle":
                rx = abs(prev_view.x() - pts_view[0].x())
                ry = abs(prev_view.y() - pts_view[0].y())
                r = math.hypot(rx, ry)
                painter.drawEllipse(pts_view[0], r, r)
        # 正交锁定提示：贴在预览终点旁，用屏幕像素画，缩放后不变形
        if self._ortho_axis and type_key in ORTHO_DRAW_TYPES and prev_view is not None:
            vp = self.mapFromScene(prev_view)
            label = "水平 H" if self._ortho_axis == "H" else "竖直 V"
            painter.save()
            painter.resetTransform()
            font = painter.font()
            font.setPointSizeF(9.0)
            painter.setFont(font)
            badge = QRectF(vp.x() + 14, vp.y() - 24,
                           QFontMetrics(font).horizontalAdvance(label) + 14, 20)
            painter.setPen(QPen(QColor(22, 119, 255), 1.0))
            painter.setBrush(QBrush(QColor(230, 241, 255, 235)))
            painter.drawRoundedRect(badge, 3.0, 3.0)
            painter.setPen(QColor(22, 80, 170))
            painter.drawText(badge.adjusted(7, 0, -7, 0),
                             Qt.AlignVCenter | Qt.AlignLeft, label)
            painter.restore()
        painter.restore()

    # ------------------------------------------------------------------
    # 工具箱拖放
    # ------------------------------------------------------------------
    @staticmethod
    def _drop_mime(mime) -> str:
        """模板 MIME 优先：一次拖放只可能带一种载荷。"""
        for fmt in (TEMPLATE_MIME_TYPE, ELEMENT_MIME_TYPE):
            if mime.hasFormat(fmt):
                return fmt
        return ""

    def dragEnterEvent(self, event) -> None:
        if self._drop_mime(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._drop_mime(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        fmt = self._drop_mime(event.mimeData())
        if not fmt:
            super().dropEvent(event)
            return
        raw = bytes(event.mimeData().data(fmt)).decode("utf-8", "ignore")
        scene_pt = QPointF(self.mapToScene(event.position().toPoint()))
        event.setDropAction(Qt.CopyAction)
        event.accept()
        if not raw:
            return
        if fmt == TEMPLATE_MIME_TYPE:
            self.templateDropped.emit(raw, scene_pt)
        else:
            self.elementDropped.emit(raw, scene_pt)

    # ------------------------------------------------------------------
    # 右键菜单：只发命令名，动作由主窗口统一分发（菜单/工具栏/右键共用）
    # ------------------------------------------------------------------
    _CONTEXT_ENTRIES = (
        ("属性…", "property"),
        (None, None),
        ("锁定所选", "lock"), ("解锁所选", "unlock"),
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
        # 布尔与模板入口同主窗口命令表共用，操作后只记一个撤销点。
        scene = self.scene()
        sel = scene.selected_items() if hasattr(scene, "selected_items") else []
        boolean_items = (scene.boolean_items()
                         if hasattr(scene, "boolean_items") else [])
        if len(boolean_items) >= 2:
            menu.addSeparator()
            boolean_menu = QMenu("布尔运算", menu)
            menu.addMenu(boolean_menu)
            # PySide 对 addMenu(QString) 返回值的归属在不同版本表现不一致；
            # 显式 parent + Python 引用，避免菜单构建返回后子菜单被 GC。
            menu._boolean_menu = boolean_menu
            for operation in BOOLEAN_OPERATIONS:
                label = BOOLEAN_LABELS[operation]
                if operation == BOOL_SUBTRACT:
                    label += "（首个减其余）"
                action = boolean_menu.addAction(label)
                action.triggered.connect(
                    lambda checked=False, op=operation:
                        self.actionTriggered.emit(f"boolean_{op}")
                )
        if len(sel) == 1:
            menu.addSeparator()
            action = menu.addAction("添加到控件工具箱")
            action.setToolTip("把选中的图元或组保存为可复用模板")
            action.triggered.connect(
                lambda checked=False: self.actionTriggered.emit("save_template")
            )
        return menu

    def contextMenuEvent(self, event) -> None:
        # 按住 O 或刚执行过 O + 右键时，不弹右键菜单（旋转中心改走 O + 右键）
        if self._origin_suppress_menu or self._origin_key_held:
            self._origin_suppress_menu = False
            return
        scene = self.scene()
        if scene is not None and getattr(scene, "is_run_mode", False):
            return
        self.build_context_menu().exec(event.globalPos())
