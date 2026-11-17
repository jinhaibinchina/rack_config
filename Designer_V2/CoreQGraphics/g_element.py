"""图元基类：几何、样式、页面记录与坐标对拍接口。

对应 ``Designer/Core/element.py`` 的 ``base_element``。设计要点：

* **坐标系**：``QGraphicsScene`` 直接用 Qt 原生场景坐标 —— page JSON 的
  ``center_pos / origin_pos / width / height / vertices / rotate`` 就是场景坐标，
  加载、绘制、命中、存盘全程不做任何坐标换算。
* **不用 Qt 父子层级**：旧实现按 zValue 平铺排序，1411 个图元 zValue 重复，
  靠 JSON 顺序定层级；Qt 的 parent zValue 会把整组拉到一起，所以分组只在
  ``SceneManager`` 里做逻辑映射，所有 item 在 Qt 层平铺。
* **boundingRect 不加 pen 宽度**，也不用 ``QGraphicsRectItem``（它会自动加）。
* **round-trip 零改动**：未被编辑时直接回写原始 ``_page`` 深拷贝。
"""

from __future__ import annotations

import copy
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsItem

from .g_style import HOVER_COLOR, Style, parse_color
from .g_binding import BY_KEY, normalize_binding


def _page_xy(data: dict, key: str, default: float = 0.0) -> tuple[float, float]:
    p = data.get(key) or {}
    return float(p.get("x", default)), float(p.get("y", default))


def rotate_xy(x: float, y: float, px: float, py: float, deg: float) -> tuple[float, float]:
    """Qt 场景坐标里把 (x, y) 绕 (px, py) 旋转 deg 度（y 向下，正角顺时针）。"""
    if not deg:
        return x, y
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    dx, dy = x - px, y - py
    return px + dx * c - dy * s, py + dx * s + dy * c


def norm_deg(deg: float) -> float:
    """角度规整到 (-180, 180]，避免父链累加后显示成 720 这种值。"""
    d = float(deg) % 360.0
    if d > 180.0:
        d -= 360.0
    return d


def scene_aabb_of_corners(
    cx: float, cy: float, w: float, h: float, angle_deg: float
) -> QRectF:
    """旧 ``update_boundingRect``：局部四角经 R(a) 后取轴对齐包围盒。"""
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)
    pts = [
        (cx + dx * c - dy * s, cy + dx * s + dy * c)
        for dx, dy in (
            (-w / 2, -h / 2), (w / 2, -h / 2),
            (-w / 2, h / 2), (w / 2, h / 2),
        )
    ]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))


class BaseItem(QGraphicsItem):
    """所有 CoreQGraphics 图元的公共基类。"""

    TYPE = "base"

    def __init__(self, record: dict) -> None:
        super().__init__()
        self._page = copy.deepcopy(record)
        self._style = Style.from_dict(record.get("style"))
        # _geo_dirty 专门驱动 to_page_record() 的几何重建；属性编辑只写
        # _page 的对应字段并置 _dirty，绝不触发几何重建（否则 center_pos
        # 会被 round(3) 改写，破坏「未编辑记录零改动」的契约）。
        self._dirty = False
        self._geo_dirty = False
        self._suppress_geo = False
        # 重建期（把 Qt 旋转烘焙进顶点）会 setRotation(0)，位姿差分看起来像
        # 「转了 -θ」；但这次重建几何一点没动，不能把后代再反向带一遍。
        self._suppress_propagate = False
        # 文本图元「字号 -> 边框」与「边框 -> 字号」双向联动时抑制反向重算，
        # 否则两个方向会互相触发形成递归（也避免拖角每帧把边框改回去）。
        self._text_resizing = False
        # 已烘焙进几何的角度（只有顶点类会用；矩形类恒为 0，旋转由 Qt 承担）
        self._baked_angle = 0.0
        self._hover = False
        self._visible = bool(record.get("visible", True))
        self._local_rect = QRectF()
        self._w_scene = 0.0
        self._h_scene = 0.0
        self._points_local: list[QPointF] = []
        self._path_local = None
        self._pixmap: QPixmap | None = None
        self._z_original = record.get("zValue", 0.0)
        # 绘制状态：激活绘制工具后图元跟随鼠标，点击画布落点（CAD 式分点）。
        # _draw_points / _draw_preview 存场景坐标，预览直接使用。
        self._drawing = False
        self._draw_points: list[QPointF] = []
        self._draw_preview: QPointF | None = None
        # 绘制交互类型：place=单击放置；box/circle/line=两击；poly=多击+右键闭合
        self.DRAW_KIND = "place"

        self.item_id = int(record.get("id", 0) or 0)
        self.item_name = record.get("name", "")
        self.parent_id = int(record.get("parent_id", 0) or 0)
        self.group_id = int(record.get("group_id", 0) or 0)
        self.children_ids = list(record.get("children_ids") or [])
        self.context = record.get("context", "")
        self.checked = bool(record.get("checked", False))
        self.image_path = record.get("image_path", "")

        self.setZValue(float(self._z_original))
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setVisible(self._visible)

        cx, cy = _page_xy(record, "center_pos")
        angle = float(record.get("rotate", 0.0) or 0.0)
        w = float(record.get("width", record.get("radius_w", 0.0) * 2) or 0.0)
        h = float(record.get("height", record.get("radius_h", 0.0) * 2) or 0.0)
        origin = record.get("origin_pos") or {}
        ox = float(origin.get("x", cx))
        oy = float(origin.get("y", cy))
        # 旋转中心（场景坐标）：默认等于几何中心；可由属性面板改成自定义点。
        self._origin_xy = (ox, oy)
        self._page_center = (cx, cy)
        self._page_angle = angle
        self._page_size = (w, h)
        self._setup_rect(cx, cy, w, h, angle)

    # ------------------------------------------------------------------
    # 几何构建（子类可覆写 _setup_* 前先调用基类 __init__）
    # ------------------------------------------------------------------
    def _setup_rect(
        self, cx: float, cy: float, w: float, h: float, angle: float
    ) -> None:
        """矩形类：局部矩形以 (0,0) 为中心，旋转交给 Qt 的 setRotation。"""
        self._w_scene, self._h_scene = float(w), float(h)
        self._local_rect = QRectF(
            -self._w_scene / 2, -self._h_scene / 2, self._w_scene, self._h_scene
        )
        self._place(cx, cy, angle, *self._origin_xy)

    def _place(self, cx: float, cy: float, angle: float,
               ox: float, oy: float) -> None:
        """按 (可视中心 C, 支点 O, 角度) 摆好 Qt 的 pos / 变换原点。

        page 语义：``center_pos`` 是可视中心、``origin_pos`` 是旋转支点。实测
        Qt 的映射是「先绕局部点 ``originPoint`` 转、再平移 pos」：

            scene(q) = pos + o + R·(q - o)        (o = transformOriginPoint)

        所以支点（旋转时不动的那点，q = o）落在 ``pos + o``、中心（q = 0）落在
        ``pos + o - R·o``。令两者分别等于 O 与 C 解出：

            o   = R⁻¹ · (O - C)
            pos = O - o

        角度为 0 时 R = I，自动退化成 ``o = O-C、pos = C``
        ——正好是「Qt 无旋转时忽略原点」的等价形态；``O == C`` 时退化成
        ``o = 0、pos = C``，与旧实现逐位一致（存量 page 零变化）。
        """
        center = QPointF(cx, cy)
        self._suppress_geo = True
        try:
            self.setRotation(float(angle))
            if abs(ox - cx) < 0.05 and abs(oy - cy) < 0.05:
                self.setTransformOriginPoint(QPointF(0.0, 0.0))
                self.setPos(center)
            else:
                offset = QPointF(ox, oy) - center
                rot = QTransform()
                rot.rotate(float(angle))
                inv, ok = rot.inverted()
                origin_pt = inv.map(offset) if ok else offset
                self.setTransformOriginPoint(origin_pt)
                self.setPos(QPointF(ox, oy) - origin_pt)
        finally:
            self._suppress_geo = False
        self._origin_xy = (float(ox), float(oy))

    def _apply_transform_origin(self, cx: float, cy: float) -> None:
        """兼容入口：按当前位置的实时角度重排 pos / 变换原点（见 ``_place``）。"""
        self._place(cx, cy, float(self.rotation()), *self._origin_xy)

    def _setup_from_scene_rect(
        self, scene_rect: QRectF, cx: float, cy: float
    ) -> None:
        """顶点/线类：几何点已含旋转，直接把场景 AABB 平移成局部矩形。"""
        center = QPointF(cx, cy)
        self.setPos(center)
        self.setRotation(0.0)
        vr = QRectF(scene_rect)
        self._local_rect = vr.translated(-center.x(), -center.y())
        self._w_scene = self._local_rect.width()
        self._h_scene = self._local_rect.height()

    # ------------------------------------------------------------------
    # 位姿：可视中心 / 旋转支点 / 角度（几何重建与父级传播共用同一套口径）
    # ------------------------------------------------------------------
    def live_page_pose(self) -> tuple[float, float, float, float, float]:
        """当前位姿 ``(cx, cy, angle, ox, oy)``，全部是 page 场景坐标。

        中心与角度从实时变换反读（拖动只改 Qt 的 pos、不改记录）；支点读
        ``_origin_xy``——角度为 0 时 Qt 会忽略变换原点，反读不出来。
        """
        # 局部原点 (0,0) 就是可视中心：矩形类的 _local_rect 以原点为中心，
        # 顶点类的 `_setup_vertices` 也把顶点减去包围盒中心后再置 pos。
        # 不能用 scenePos()——自定义支点时 pos 并不等于中心（见 _place 的推导）。
        cscene = self.mapToScene(QPointF(0.0, 0.0))
        cx, cy = cscene.x(), cscene.y()
        ox, oy = self._origin_xy
        if abs(ox - cx) < 0.05 and abs(oy - cy) < 0.05:
            return cx, cy, float(self.rotation()), cx, cy
        return cx, cy, float(self.rotation()), ox, oy

    def _apply_pose(self, cx: float, cy: float, angle: float,
                    ox: float, oy: float) -> None:
        """按绝对位姿重排（不走 ``set_page_*``，不受父对象位姿锁影响）。"""
        self._place(cx, cy, angle, ox, oy)
        self._page_center = (float(cx), float(cy))
        self._page_angle = float(angle)
        if "center_pos" in self._page:
            self._page["center_pos"] = {"x": round(float(cx), 3),
                                        "y": round(float(cy), 3)}
        if "origin_pos" in self._page:
            self._page["origin_pos"] = {"x": round(float(ox), 3),
                                        "y": round(float(oy), 3)}
        if self.has_explicit_geometry():
            self._page["rotate"] = float(angle)
        self._dirty = True
        self._geo_dirty = True
        self.update()

    def apply_rigid_pose(self, px: float, py: float, dangle: float,
                         dx: float, dy: float) -> None:
        """把父对象的刚体运动施加到自身：先绕旧中心 (px, py) 转 dangle，再平移。

        中心与支点都是刚体上的点，一起变换，因此支点也跟着动；角度累加 dangle。
        顶点类图元（line/triangle/polygon/path）覆写此方法，把旋转烘焙进顶点。
        """
        cx, cy, angle, ox, oy = self.live_page_pose()
        ncx, ncy = rotate_xy(cx, cy, px, py, dangle)
        nox, noy = rotate_xy(ox, oy, px, py, dangle)
        self._apply_pose(ncx + dx, ncy + dy, angle + dangle,
                         nox + dx, noy + dy)

    # ------------------------------------------------------------------
    # 坐标系：有父对象时，图元的坐标就表达在「父坐标系」里
    # ------------------------------------------------------------------
    def parent_item(self) -> "BaseItem | None":
        """逻辑父对象（``parent_id`` 指向的图元）；无父或在场景外返回 None。"""
        scene = self.scene()
        index = getattr(scene, "index", None) if scene is not None else None
        if index is None or not self.parent_id:
            return None
        return index.by_id.get(self.parent_id)

    def parent_frame(self) -> tuple[float, float, float]:
        """父坐标系 ``(px, py, 角度)``；无父时返回 ``(0, 0, 0)``＝场景坐标系本身。

        约定：父坐标系的原点在**父图元的可视中心**，朝向是父图元的绝对角度
        （page 坐标，y 轴向上）。父对象整体平移 / 旋转时，子图元的这套局部坐标
        恒定不变——这正是「设置了父对象后，图元的坐标变成父坐标系中的坐标」的
        含义，也是父对象拖一次不用重写 153 个子图元记录的原因。
        """
        parent = self.parent_item()
        if parent is None:
            return 0.0, 0.0, 0.0
        cx, cy = parent.page_center()
        return float(cx), float(cy), float(parent.page_angle())

    def local_to_world(self, x: float, y: float) -> tuple[float, float]:
        """父坐标 → 场景坐标。无父时恒等。"""
        px, py, pa = self.parent_frame()
        if not self.parent_id:
            return float(x), float(y)
        wx, wy = rotate_xy(float(x), float(y), 0.0, 0.0, pa)
        return wx + px, wy + py

    def world_to_local(self, x: float, y: float) -> tuple[float, float]:
        """场景坐标 → 父坐标。无父时恒等。"""
        px, py, pa = self.parent_frame()
        if not self.parent_id:
            return float(x), float(y)
        return rotate_xy(float(x) - px, float(y) - py, 0.0, 0.0, -pa)

    def page_local_center(self) -> tuple[float, float]:
        """可视中心在父坐标系里的坐标（无父时等于 ``page_center``）。"""
        return self.world_to_local(*self.page_center())

    def page_local_origin(self) -> tuple[float, float]:
        """旋转支点在父坐标系里的坐标（无父时等于 ``page_origin``）。"""
        return self.world_to_local(*self.page_origin())

    def page_local_angle(self) -> float:
        """相对父对象的角度（无父时等于 ``page_angle``），规整到 (-180, 180]。"""
        if not self.parent_id:
            return float(self.page_angle())
        return norm_deg(float(self.page_angle()) - self.parent_frame()[2])

    def set_page_local_angle(self, angle: float) -> None:
        """按父坐标系里的角度旋转自身（绕自己的支点转，不带动父 / 兄弟）。"""
        # 不规整基底角度：让写入的绝对角度可逆，避免 ±180 处跳变
        target = float(angle) + self.parent_frame()[2]
        if self.has_explicit_geometry():
            self.set_page_angle(target)
        else:
            # 顶点类没有「改角度」入口（几何是烘焙的），走与 [ / ] 相同的烘焙路径
            self._turn_to(target, rebuild=True)

    def set_page_local_origin(self, x: float, y: float) -> None:
        """按父坐标系设置旋转支点（保持可视中心不动）。"""
        self.set_page_origin(*self.local_to_world(float(x), float(y)))

    # ------------------------------------------------------------------
    # 位姿锁：平移被父对象锁死，旋转仍可自行进行
    # ------------------------------------------------------------------
    def translate_locked(self) -> bool:
        """有父对象时，**仅设计态**不能自行平移——位置由父对象带动。

        运行态允许子图元自行平移：HMI 动画 / 业务脚本经常需要让某个
        子控件在父图元内部偏移（``RuntimeElement.setPos`` /
        ``set_page_center`` 都走这条门控）。运行态仍保留父子刚体联动：
        子图元自己动不带动父对象，父对象之后平移 / 旋转时仍会带着它走。

        判定只看当前场景的 ``is_run_mode``；图元尚未入场景（构造 / 离线
        建模）按设计态处理，保持原有存储语义。
        """
        if not self.parent_id:
            return False
        scene = self.scene()
        return not bool(getattr(scene, "is_run_mode", False))

    def pose_locked(self) -> bool:
        """兼容旧名的入口，语义收敛为「平移锁定」（旋转不锁）。"""
        return self.translate_locked()

    def _pivot_is_default(self) -> bool:
        """支点是否仍是默认值「可视中心」。

        所有类型都必须能从这条判据得出结论：矩形类在 ``__init__`` 里把
        ``_origin_xy`` 初始成 ``center_pos``，顶点类（line/triangle/polygon/path）
        的中心是**顶点算出来的**，构造时还拿不到——新建图元就会留下 (0,0) 或第一个
        落点当支点，属性面板读出来是错的、旋转也会绕到画布外。所以顶点类在几何
        重建后要调 ``_rebase_pivot`` 把它补上。
        """
        cx, cy = self.page_center()
        ox, oy = self._origin_xy
        return abs(ox - cx) < 0.05 and abs(oy - cy) < 0.05

    def _rebase_pivot(self, old_center, new_center) -> None:
        """几何重建导致中心变化后同步支点。

        默认支点（= 可视中心）直接跟到新中心；自定义支点按中心位移整体平移，
        保持「支点相对中心偏多少」不变——否则改一次宽高/顶点就把用户设的
        旋转中心冲掉了。
        """
        ox, oy = self._origin_xy
        dx = float(new_center[0]) - float(old_center[0])
        dy = float(new_center[1]) - float(old_center[1])
        was_default = (abs(ox - float(old_center[0])) < 0.05
                       and abs(oy - float(old_center[1])) < 0.05)
        if was_default:
            ox, oy = float(new_center[0]), float(new_center[1])
        else:
            ox, oy = ox + dx, oy + dy
        self._origin_xy = (ox, oy)
        if "origin_pos" in self._page:
            self._page["origin_pos"] = {"x": round(ox, 3), "y": round(oy, 3)}

    # --- 记录口径的写入口（几何重建时统一从这里落盘，避免各处 round 打架）---
    def _write_center(self, cx: float, cy: float) -> None:
        self._page_center = (float(cx), float(cy))
        if "center_pos" in self._page:
            self._page["center_pos"] = {"x": round(float(cx), 3),
                                        "y": round(float(cy), 3)}

    def _write_origin(self, ox: float, oy: float) -> None:
        self._origin_xy = (float(ox), float(oy))
        if "origin_pos" in self._page:
            self._page["origin_pos"] = {"x": round(float(ox), 3),
                                        "y": round(float(oy), 3)}

    def shift_origin_by(self, dx: float, dy: float) -> None:
        """外部平移（Qt 拖动只改 pos）后让自记住的支点跟着走。

        角度为 0 时 Qt 不使用变换原点，支点只能靠 ``_origin_xy`` 维护，所以拖动
        必须显式补这一步，否则转起来会绕到旧位置。

        **默认支点同样要同步 ``_origin_xy``**：``live_page_pose()`` 是拿
        ``_origin_xy`` 与「实时可视中心」比较来判定是否为默认支点的。只更新
        ``_page_center`` 而把 ``_origin_xy`` 留在拖动前的位置，下一次读位姿就
        会把默认支点误判成「自定义支点」（支点＝拖之前的旧中心）。父图元随后
        旋转会绕旧中心转，整棵子树相对父漂移，属性面板的父系 X/Y 也跟着变。
        """
        if abs(dx) < 1e-12 and abs(dy) < 1e-12:
            return
        ccx, ccy = self._page_center
        ox, oy = self._origin_xy
        self._origin_xy = (ox + dx, oy + dy)
        self._page_center = (ccx + dx, ccy + dy)
        if "origin_pos" in self._page:
            self._page["origin_pos"] = {"x": round(self._origin_xy[0], 3),
                                        "y": round(self._origin_xy[1], 3)}

    def root_parent(self) -> "BaseItem":
        """最顶层父对象（自身无父时返回自身）。"""
        scene = self.scene()
        index = getattr(scene, "index", None) if scene is not None else None
        item = self
        seen = {item.item_id}
        while item.parent_id and index is not None:
            parent = index.by_id.get(item.parent_id)
            if parent is None or parent.item_id in seen:
                break
            seen.add(parent.item_id)
            item = parent
        return item

    # ------------------------------------------------------------------
    # QGraphicsItem 接口
    # ------------------------------------------------------------------
    def boundingRect(self) -> QRectF:
        return self._local_rect

    def paint(self, painter: QPainter, option, widget=None) -> None:
        """默认不画；子类覆写。"""

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        # __init__ 里的 setPos/setRotation 也会触发 itemChange，但那时
        # item 还没加入场景，不能算「用户编辑」，否则 round-trip 会重算坐标。
        scene = self.scene()
        # setRotation 只发 ItemRotationHasChanged（不发 ItemTransformHasChanged），
        # 所以两个都要接：父对象的旋转必须能驱动子图元的位姿传播。
        if scene is not None and change in (
            QGraphicsItem.ItemPositionHasChanged,
            QGraphicsItem.ItemRotationHasChanged,
            QGraphicsItem.ItemTransformHasChanged,
        ):
            self._dirty = True
            if not self._suppress_geo:
                self._geo_dirty = True
            if hasattr(scene, "on_item_moved"):
                scene.on_item_moved(self)
            # 选中项要在视图前景区画「中心点 + ID」标注，标注可能落在图元
            # 包围盒之外；拖动时扩大脏区，避免文字留残影。
            if self.isSelected():
                scene.update(self.sceneBoundingRect().adjusted(-48, -48, 48, 48))
        return super().itemChange(change, value)

    # ------------------------------------------------------------------
    # 对拍 / 序列化
    # ------------------------------------------------------------------
    def page_bounding_rect(self) -> QRectF:
        """Qt 场景包围盒；page 与场景同坐标系，直接返回。"""
        return QRectF(self.sceneBoundingRect())

    def view_bounding_rect(self) -> QRectF:
        """应逐项等于旧 ``base_element.viewBoundingRect()``。"""
        return self.sceneBoundingRect()

    def to_page_record(self) -> dict:
        """回写 page JSON 记录；未编辑时原样深拷贝，保证零改动。"""
        if not self._geo_dirty:
            return copy.deepcopy(self._page)
        out = copy.deepcopy(self._page)
        # 矩形类：可视中心是局部 (0,0) 经变换后的位置（自定义支点会偏离 scenePos）；
        # 顶点类：保持旧口径（scenePos 即中心，几何已烘焙旋转）。
        cscene = (self.mapToScene(self._local_rect.center())
                  if self.has_explicit_geometry() else self.scenePos())
        cx, cy = cscene.x(), cscene.y()
        w, h = self._w_scene, self._h_scene
        out["center_pos"] = {"x": round(cx, 3), "y": round(cy, 3)}
        ox, oy = self.page_origin()
        out["origin_pos"] = {"x": round(ox, 3), "y": round(oy, 3)}
        if "width" in out:
            out["width"], out["height"] = w, h
        elif "radius_w" in out:
            out["radius_w"], out["radius_h"] = w / 2.0, h / 2.0
        out["rotate"] = float(self.rotation()) + 0.0   # +0.0 把 -0.0 归一成 0.0
        out["zValue"] = self.zValue()
        return out

    def mark_clean(self) -> None:
        self._dirty = False
        self._geo_dirty = False

    # ------------------------------------------------------------------
    # 交互 API
    # ------------------------------------------------------------------
    def stroke_color(self):
        if self._hover or self.isSelected():
            return HOVER_COLOR
        return self._style.stroke

    def resize_by(self, factor: float) -> None:
        if factor <= 0:
            return
        self.prepareGeometryChange()
        old_w, old_h = self._w_scene, self._h_scene
        self._w_scene, self._h_scene = old_w * factor, old_h * factor
        self._local_rect = QRectF(
            -self._w_scene / 2, -self._h_scene / 2, self._w_scene, self._h_scene
        )
        self.update()
        self._dirty = True
        self._geo_dirty = True
        # +/- 快捷键直接改视图矩形，不经过 set_page_size；同步写回 _page，
        # 否则 page_size()（属性面板 / 后续 set_page_size 的基准）与实际几何
        # 不一致。to_page_record 的 _geo_dirty 重建用同一组数值，存盘不变。
        w, h = self._w_scene, self._h_scene
        if "width" in self._page:
            self._page["width"], self._page["height"] = float(w), float(h)
        elif "radius_w" in self._page:
            self._page["radius_w"] = float(w) / 2.0
            self._page["radius_h"] = float(h) / 2.0
        # 文本图元同样要反算字号，否则放大后文字相对变小、缩小后被裁。
        self._on_size_changed(w, h)

    def rotate_by(self, delta_deg: float) -> None:
        """按 Qt 场景角度增量旋转（[ / ] 快捷键用），绕自身支点转。

        场景坐标就是 page 坐标，正角与画面顺时针一致；有父对象时照样能转：
        平移被父对象锁住，但姿态仍可自行调整（后代随之刚体跟转）。
        """
        self._turn_to(self.page_angle() + float(delta_deg), rebuild=True)

    def _turn_to(self, angle: float, rebuild: bool) -> None:
        """绕支点转到 angle：支点不动，可视中心随转动绕支点走。

        顶点类的几何是烘焙进顶点的，Qt 只承担「还没烘焙的那一段」：真正的当前
        朝向是 ``_baked_angle + rotation()``，所以这里按 ``page_angle()`` 求
        增量，再把残量 ``angle - _baked_angle`` 交给 ``_apply_pose``。矩形类的
        ``_baked_angle`` 恒为 0，与旧行为逐位一致。
        """
        cx, cy, _qt, ox, oy = self.live_page_pose()
        delta = float(angle) - float(self.page_angle())
        custom = abs(ox - cx) >= 0.05 or abs(oy - cy) >= 0.05
        if custom:
            cx, cy = rotate_xy(cx, cy, ox, oy, delta)
        self._apply_pose(cx, cy, float(angle) - self._baked_angle, ox, oy)
        # 精确写入记录时不需要重建（``_apply_pose`` 已把 center/origin/rotate 写全）
        self._geo_dirty = bool(rebuild)

    def set_page_visible(self, value: bool) -> None:
        self._visible = bool(value)
        self.setVisible(self._visible)

    # ------------------------------------------------------------------
    # UI 外壳：属性读写。``_page`` 是唯一真值，编辑只改对应字段。
    # ------------------------------------------------------------------
    def page_record(self) -> dict:
        """当前 page 记录（只读用途；写入请用 set_page_field）。"""
        return self._page

    def get_name(self) -> str:
        return self.item_name

    def set_name(self, name: str) -> bool:
        """改名，返回是否成功（组的成员名字前缀由场景层一起换）。

        **名字整页唯一**：改成空名或已存在的名字会被拒绝（``False``），且一个
        字段都不写；拒绝原因由场景的 ``rename_problem()`` 统一给，属性面板 /
        F2 重命名据此回滚输入框并提示。图元还没入场景（离线建模 / 构造）时
        无从查重，退回直接写记录的行为。
        """
        scene = self.scene()
        if scene is not None and hasattr(scene, "rename_item"):
            return bool(scene.rename_item(self, str(name or ""))[0])
        self.set_page_field("name", str(name or ""))
        return True

    def get_visibility(self) -> bool:
        return self._visible

    def set_visibility(self, value: bool) -> None:
        self.set_page_field("visible", bool(value))

    def get_selectable(self) -> bool:
        return bool(self.flags() & QGraphicsItem.ItemIsSelectable)

    def set_selectable(self, value: bool) -> None:
        self.setFlag(QGraphicsItem.ItemIsSelectable, bool(value))

    # ------------------------------------------------------------------
    # 图元锁定：设计模式下禁止移动 / 旋转 / 缩放（选中与其余属性仍可编辑）
    # ------------------------------------------------------------------
    # 注意别和 ``translate_locked()`` / ``pose_locked()`` 混淆：那两个是
    # 「有父对象时不能自行平移」的旧位姿锁，与本功能无关。
    #
    # ``locked`` 是**可选顶层字段**：存量 page 没有这个键，缺省即未锁定；
    # 解锁时把键整个删掉，回到存量记录的原始形态，保证 JSON round-trip
    # 零改动，也避免给 1618 个图元凭空多写一个字段。旧 Core 的
    # ``from_dict`` 只读已知键，遇到 locked 会忽略，不会加载失败。
    def is_locked(self) -> bool:
        return bool(self._page.get("locked", False))

    def set_locked(self, value: bool) -> None:
        value = bool(value)
        if value == self.is_locked():
            return
        if not value:
            self._page.pop("locked", None)
            self._dirty = True
            self.update()
            return
        self.set_page_field("locked", True)

    def style_value(self, key: str, default=None):
        return (self._page.get("style") or {}).get(key, default)

    def set_style_value(self, key: str, value) -> None:
        style = dict(self._page.get("style") or {})
        style[key] = value
        self.set_page_field("style", style)

    # ------------------------------------------------------------------
    # 变量绑定（设计态编辑 / 运行态读取，存图元内 bindings 字段）
    # ------------------------------------------------------------------
    # ``bindings`` 是可选顶层字段：未绑定时不写键，保持 round-trip 零改动。
    # 白名单与 coercion 统一在 g_binding，设计态面板与运行态桥共用。
    def bindings(self) -> dict[str, dict[str, str]]:
        """本图元的 ``{属性: {tag, apply}}`` 绑定表（规范化副本）。"""
        raw = self._page.get("bindings")
        if not isinstance(raw, dict):
            return {}
        out: dict[str, dict[str, str]] = {}
        for field, entry in raw.items():
            spec = BY_KEY.get(str(field))
            if spec is None:
                continue
            norm = normalize_binding(entry, spec.apply)
            if norm["tag"]:
                out[str(field)] = norm
        return out

    def binding_tag(self, field: str) -> str:
        """某属性当前绑定的 tag；未绑定返回空串。"""
        return self.bindings().get(str(field), {}).get("tag", "")

    def set_binding(self, field: str, tag: str,
                    apply: str | None = None,
                    mode: str | None = None) -> None:
        """设置一个属性的绑定；``tag`` 为空表示清除该属性。

        写进 ``_page['bindings']`` 走 :meth:`set_page_field`，因此自动被
        ``page_data()`` 序列化、被 ``PageHistory`` 快照撤销。清空最后一条时
        整个键被删掉，回到存量记录的原始形态（零改动契约）。

        ``apply`` / ``mode`` 传 ``None`` 时沿用该属性当前的旧值（缺省 mode='r'），
        这样属性面板单独改方向或值类型不会把另一项重置掉。
        """
        field = str(field)
        spec = BY_KEY.get(field)
        if spec is None:
            return
        tag = str(tag or "").strip()
        table = dict(self._page.get("bindings") or {})
        if not tag:
            if field not in table:
                return
            table.pop(field, None)
        else:
            old = normalize_binding(table.get(field) or {}, spec.apply)
            entry = normalize_binding(
                {"tag": tag,
                 "apply": apply or old["apply"],
                 "mode": mode or old["mode"]}, spec.apply)
            if table.get(field) == entry:
                return
            table[field] = entry
        if table:
            self.set_page_field("bindings", table)
        else:
            self._page.pop("bindings", None)
            self._dirty = True
            self.update()

    # ------------------------------------------------------------------
    # 绘制交互：CAD 式分点落点
    # ------------------------------------------------------------------
    def draw_step(self, points: list[QPointF], preview: QPointF | None) -> bool:
        """按已收集的落点 + 当前光标预览更新几何；返回是否已满足落点数量。

        默认（place）：第 1 个点即落定中心，保持默认尺寸。矩形/圆/线/多边形
        在子类覆写。``points``/``preview`` 均为 **page 场景坐标**。
        """
        if points:
            self.set_page_center(points[0].x(), points[0].y())
        return len(points) >= 1

    def set_page_field(self, key: str, value) -> None:
        """写一个非几何字段，并同步运行时状态；不触碰几何重建。"""
        if key in self._page and self._page[key] == value:
            return
        self._page[key] = value
        self._dirty = True
        self._sync_field(key, value)
        self.update()

    def _on_text_changed(self) -> None:
        """文本 / 字号变化后的几何联动 hook。

        ``TextItem`` 覆写它来按文字尺寸重算边框背景；其余类型保持无操作。
        只在属性面板显式编辑时触发，加载 / 撤销重建走构造路径，不动存量几何
        （否则 page_1 的 1618 图元对拍与 JSON round-trip 会失效）。
        """

    def _on_size_changed(self, w: float, h: float) -> None:
        """显式改边框尺寸后的联动 hook（``TextItem`` 用来反算字号）。

        只在 ``set_page_size`` / ``resize_by`` 的成功路径调用。加载与撤销重建
        走 ``_setup_rect`` 构造路径，不经过这里，所以存量 page 的 style 保持
        原样——这是 page_1 对拍与 JSON round-trip 零改动的前提。
        """

    def _sync_field(self, key: str, value) -> None:
        if key == "name":
            self.item_name = str(value)
        elif key == "visible":
            self._visible = bool(value)
            self.setVisible(self._visible)
        elif key == "style":
            old_font = (self._style.font_size, self._style.font_family)
            self._style = Style.from_dict(value)
            # 只有字号 / 字体族真的变了才联动几何：改颜色 / 线宽不该把文本边框
            # 撑大。字体族换了文字宽高就变（同一个字在「微软雅黑」和「Arial」
            # 里不一样宽），必须按新字体把边框重算，否则文字会被裁。
            # 由尺寸反算字号时（_text_resizing）只更新样式，不再重算边框。
            new_font = (self._style.font_size, self._style.font_family)
            if new_font != old_font and not self._text_resizing:
                self._on_text_changed()
        elif key == "context":
            self.context = value
            self._on_text_changed()
        elif key == "checked":
            self.checked = bool(value)
        elif key == "image_path":
            self.image_path = value
            self._reload_pixmap()
        elif key == "zValue":
            self.setZValue(float(value))
        elif key in ("parent_id", "group_id"):
            setattr(self, key, int(value or 0))
        elif key == "children_ids":
            self.children_ids = list(value or [])

    def _reload_pixmap(self) -> None:
        """ImageItem 覆写；其余类型无图片可重载。"""

    # ------------------------------------------------------------------
    # UI 外壳：几何属性（精确写入，不经过重建）
    # ------------------------------------------------------------------
    def page_center(self) -> tuple[float, float]:
        """可视中心（page 坐标）。记录已陈旧（拖动过）时从实时变换反读。"""
        if self._geo_dirty or "center_pos" not in self._page:
            return self.live_page_pose()[:2]
        return _page_xy(self._page, "center_pos")

    def page_origin(self) -> tuple[float, float]:
        """旋转支点（场景坐标）。默认等于可视中心；自定义时读记录的支点。"""
        cx, cy = self.page_center()
        ox, oy = self._origin_xy
        if abs(ox - cx) < 0.05 and abs(oy - cy) < 0.05:
            return cx, cy
        return ox, oy

    def page_size(self) -> tuple[float, float]:
        w = float(self._page.get("width", self._page.get("radius_w", 0.0) * 2) or 0.0)
        h = float(self._page.get("height", self._page.get("radius_h", 0.0) * 2) or 0.0)
        return w, h

    def page_angle(self) -> float:
        """当前角度。拖动 / 自转只改 Qt 旋转（记录待烘焙），此时从实时变换反读。"""
        if self._geo_dirty:
            return self.live_page_pose()[2]
        return float(self._page.get("rotate", 0.0) or 0.0)

    def has_explicit_geometry(self) -> bool:
        """line / triangle / polygon / path 的尺寸由顶点决定，不能改 W/H。"""
        return not self._points_local and self._path_local is None

    def center_scene_point(self) -> QPointF:
        """可视中心（场景坐标）。局部原点就是中心，自定义支点时也成立。"""
        return self.mapToScene(QPointF(0.0, 0.0))

    def pivot_scene_point(self) -> QPointF:
        """旋转中心（场景坐标）—— 画布上的中心点标识就画在这里。

        严格说这是「旋转时保持不动的那一点」：设过自定义支点时它就是
        ``transformOriginPoint``（可能偏离可视中心），默认「绕中心转」时与
        ``center_scene_point`` 重合（此时原点为 (0,0)，映射出来就是中心）。

        这里不走 ``mapToScene(transformOriginPoint())``：顶点类图元把旋转烘焙进
        顶点后 Qt 旋转归零，变换原点不再被 Qt 使用、也可能留着上一次的残值，
        映射出来就不是支点了。支点以记录口径（``page_origin``）为准，就是场景坐标。
        """
        ox, oy = self.page_origin()
        return QPointF(float(ox), float(oy))

    def has_custom_origin(self) -> bool:
        """旋转支点是否被钉在非几何中心的位置（画布上要画蓝色支点环）。"""
        return not self._pivot_is_default()

    def set_page_center(self, x: float, y: float) -> bool:
        """平移图元，使可视中心落到 page 坐标 (x, y)。

        有父对象时**仅设计态**拒绝：设计器里子图元的位置只能由父对象带动
        （``translate_locked``）。运行态允许自行平移，供 HMI 动画 / 业务脚本
        在父图元内部偏移子控件；父对象之后运动时仍按刚体联动带上它。
        """
        if self.translate_locked():
            return False
        cx, cy = self.live_page_pose()[:2]
        dx, dy = float(x) - cx, float(y) - cy
        if "center_pos" in self._page:
            self._page["center_pos"] = {"x": float(x), "y": float(y)}
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return True
        delta = QPointF(dx, dy)
        # setPos 会触发 itemChange；这里显式写了精确值，故抑制几何重建标记，
        # 但仍然保留 on_item_moved 的父级联动。
        self._suppress_geo = True
        try:
            # 必须用 pos() 而不是 scenePos()：有自定义支点（origin_pos ≠ 中心）
            # 且旋转非 0 时 Qt 的 scenePos 是按支点旋转后的局部原点映射，
            # 与 pos 差着「绕支点那一转」的位移。拿 scenePos 做基准再把结果
            # 塞回 setPos，等于每次平移都多走一段，斜着的图元会越挪越偏
            # （正放时旋转为 0、两者相等，所以只有旋转过的图元暴露）。
            self.setPos(self.pos() + delta)
        finally:
            self._suppress_geo = False
        # 支点随中心刚性平移（局部偏移不变）
        self._origin_xy = (self._origin_xy[0] + dx, self._origin_xy[1] + dy)
        self._page_center = (float(x), float(y))
        if "origin_pos" in self._page:
            self._page["origin_pos"] = {"x": self._origin_xy[0],
                                        "y": self._origin_xy[1]}
        self._dirty = True
        self.update()
        return True

    def set_page_origin(self, x: float, y: float) -> None:
        """设置旋转支点（场景坐标），保持当前可视中心不动。

        顶点类同样支持：支点只是 ``_place`` 的入参，转动时顶点跟着 Qt 变换走，
        存盘前由 ``_PointBasedItem.bake_rotation()`` 折进 ``vertices``。
        """
        cx, cy = self.live_page_pose()[:2]
        self._origin_xy = (float(x), float(y))
        self._page["origin_pos"] = {"x": float(x), "y": float(y)}
        self._suppress_geo = True
        try:
            self._apply_transform_origin(cx, cy)
        finally:
            self._suppress_geo = False
        self._dirty = True
        self._geo_dirty = True
        self.update()

    def reset_page_origin(self) -> None:
        """旋转支点回到可视中心（默认「绕中心转」）。"""
        cx, cy = self.live_page_pose()[:2]
        self.set_page_origin(cx, cy)

    def set_page_parent(self, parent_id: int) -> bool:
        """设置逻辑父对象（parent_id）。拒绝自指/成环；父移动时自身随动。

        挂上父对象后：

        * 本图元在**设计态不能自行平移**（``translate_locked``），位置只由父
          对象的刚体运动带动（平移 + 旋转 + 支点一起走）；运行态允许业务脚本
          自行平移子图元，父对象之后的运动仍会带着它走；
        * 本图元**仍可自行旋转**（``set_page_angle`` / ``rotate_by`` / 面板
          「旋转」字段），绕自己的支点转，不带动父对象和兄弟；
        * 对外暴露的坐标改为**父坐标系**（``page_local_center`` /
          ``page_local_angle`` / ``page_local_origin``），父对象怎么动，这组
          局部坐标都不变。

        注意：CoreQGraphics 刻意不引入 Qt 父子层级（平铺 z 序、1618 图元
        对拍口径），故这里只记录逻辑父子关系，存储与 page JSON 仍是场景绝对
        坐标——父坐标系只作为对外读数 / 写入口径，存量页面因此保持零改动。
        """
        pid = int(parent_id or 0)
        if pid == self.item_id or pid == self.parent_id:
            return False
        scene = self.scene()
        if pid and scene is not None and hasattr(scene, "index"):
            if any(d.item_id == pid for d in scene.index.descendants(self.item_id)):
                return False  # 不能把父设成自己的后代，避免成环
        self.parent_id = pid
        self._page["parent_id"] = pid
        self._dirty = True
        if scene is not None and hasattr(scene, "index"):
            scene.index.rebuild_links()
            # 子图元不可单独拖动（位姿由父对象带动），立即刷新拖拽门控
            if hasattr(scene, "refresh_movable"):
                scene.refresh_movable()
        return True

    def set_page_size(self, w: float, h: float) -> None:
        if not self.has_explicit_geometry() or w <= 0 or h <= 0:
            return
        self.prepareGeometryChange()
        self._w_scene, self._h_scene = float(w), float(h)
        self._local_rect = QRectF(
            -self._w_scene / 2, -self._h_scene / 2, self._w_scene, self._h_scene
        )
        if "width" in self._page:
            self._page["width"], self._page["height"] = float(w), float(h)
        elif "radius_w" in self._page:
            self._page["radius_w"] = float(w) / 2.0
            self._page["radius_h"] = float(h) / 2.0
        self._dirty = True
        self.update()
        self._on_size_changed(float(w), float(h))

    def apply_scale_about(self, anchor, sx: float, sy: float) -> None:
        """组尺寸变化时，把本矩形类图元的全部几何点绕 ``anchor`` 缩放。

        对照旧 Core ``rect_element.change_size``：组改宽高时，组内每个成员的
        尺寸、中心、支点都要按同一组比例搬走。新场景是平铺结构（没有 Qt 父子
        链），所以直接改 page 绝对坐标；用 ``_apply_pose`` 绕过
        ``translate_locked``——子图元平时不允许自行平移，但父组缩放必须带动它。
        """
        ax, ay = float(anchor[0]), float(anchor[1])

        def f(x, y):
            return ax + (float(x) - ax) * sx, ay + (float(y) - ay) * sy

        cx, cy = self.page_center()
        ox, oy = self.page_origin()
        angle = self.page_angle()
        w, h = self.page_size()
        prev = self._suppress_propagate
        self._suppress_propagate = True
        try:
            self.set_page_size(w * sx, h * sy)
            ncx, ncy = f(cx, cy)
            nox, noy = f(ox, oy)
            self._apply_pose(ncx, ncy, angle, nox, noy)
        finally:
            self._suppress_propagate = prev

    def set_page_angle(self, angle: float) -> None:
        """设置绝对角度（绕自身支点转）。有父对象时仍可调——只锁平移不锁旋转。

        顶点类的姿态是烘焙进顶点的，所以要走 ``rebuild=True`` 的路径，让
        ``to_page_record()`` 知道需要重新烘焙（否则存盘丢旋转）。
        """
        if self.has_explicit_geometry():
            self._turn_to(float(angle), rebuild=False)
        else:
            self._turn_to(float(angle), rebuild=True)

    def frame_corners(self) -> list[QPointF]:
        """包围盒四角（视图场景坐标），顺序：[左上, 右上, 左下, 右下]。

        拖角改尺寸要拿「轴对齐包围盒」的四角当锚点，这与捕捉点不是一回事
        （顶点类的捕捉点是真实顶点，见 ``_PointBasedItem.snap_points``），所以
        单独开一个入口，别再用 ``snap_points()`` 取角。
        """
        r = self._local_rect
        corners = [
            QPointF(r.left(), r.top()), QPointF(r.right(), r.top()),
            QPointF(r.left(), r.bottom()), QPointF(r.right(), r.bottom()),
        ]
        tf: QTransform = self.sceneTransform()
        return [tf.map(pt) for pt in corners]

    def snap_points(self) -> tuple[list[QPointF], list[QPointF]]:
        """端点 / 中点，返回视图场景坐标（与旧 SnapSystem 输入口径一致）。"""
        r = self._local_rect
        tf: QTransform = self.sceneTransform()
        ends = self.frame_corners()
        mids = [
            tf.map(r.center()),
            tf.map(QPointF(r.center().x(), r.top())),
            tf.map(QPointF(r.center().x(), r.bottom())),
            tf.map(QPointF(r.left(), r.center().y())),
            tf.map(QPointF(r.right(), r.center().y())),
        ]
        return ends, mids
