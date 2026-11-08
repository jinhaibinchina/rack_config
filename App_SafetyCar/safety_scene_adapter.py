"""把 CoreQGraphics 场景包装成旧 ``QuadTreeScene`` / ``SceneManager`` / 图元接口。

为什么要这层
------------
``safety_car_entry.py`` + ``my_plc_safety.py`` 合计 3700 行，但对旧场景只用
到一小组接口：命名查表（``SceneManager.m_name_items`` / ``findItem``）、
可见性、填充色、位姿/朝向、选中联动、模式切换。直接重写这两千多行风险大、
收益低，所以这里做一层**薄适配**，业务代码只改 import 与构造三行。

与 ``App_RackConfig/run/rack_scene_adapter.py`` 同源（同一套壳思路、同一套
page 坐标口径）。**两份文件里的 bug 修复要同步**：料仓那套先落地，之后改这里
也请回头看一眼那边。

角色分工（旧代码里 ``scene`` 是「既是 QWidget 又是场景」，必须拆开）
--------------------------------------------------------------------
* :class:`SafetyScene`（``QGraphicsScene``）—— 页面数据、图元索引、模式、
  ``current_selected``、``run_mode_station_change`` 信号；
* :class:`SafetySceneView`（``QGraphicsView``）—— 真正塞进布局的那个 widget，
  负责取景、输入门控、点击路由，并把场景接口**代理**出来。入口里
  ``self.scene`` 指向它，所以 ``addWidget(self.scene)`` / ``self.scene.mode()``
  / ``self.scene.selectionChanged`` 全都照旧可用。

坐标系铁律
----------
旧场景没有投影层，``sceneBoundingRect()`` / ``get_scene_*_pos()`` 返回的就是
page 坐标；新场景多一层 :class:`SceneProjection`（AGV 场景带轴交换与取反）。
所以对外几何接口一律走 **page 坐标**（``page_center`` / ``page_bounding_rect``）。

可见性为什么要递归
------------------
新场景是平铺层级（只有 ``parent_id`` 记账，不用 ``setParentItem``），组的
``setVisible(False)`` **不会**带到子项。壳里维护两份状态：``_self_visible``
（自身标志，``get_visibility()`` 读它）与 ``_eff_visible``（AND 全部祖先，
真正写进 Qt）；组隐藏前给直接子项拍快照，显示时按快照还原——不然安全车
反复切站会把整场景冲成一片 True。
"""

from __future__ import annotations

import math
import os
import sys
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QFrame

# 允许以脚本方式单独 import 本文件
if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

from Designer.CoreQGraphics import GraphicsScene, GraphicsView   # noqa: E402
from Designer.Core.my_common import SceneMode                    # noqa: E402
from res.designer_resource_manager import resource_manager as res_mng  # noqa: E402

#: 运行态默认加载的场景（相对于 ``res/myDesigner/scene/``）
DEFAULT_SCENE_NAME = "safety_car_scene.json"


def _color_text(color) -> str:
    """QColor -> ``#rrggbb``（旧 ``get_color`` / ``get_fill_color`` 都不带 alpha）。"""
    if isinstance(color, QColor):
        return color.name()
    return str(color)


class base_element(QObject):
    """单个图元的适配壳：接口形状对齐旧 ``Designer.Core.elements.base_element``。"""

    # 旧场景里点击由 ``handle_mouse_release`` + ``_emit_event(EVENT_CLICK)`` 发信号，
    # 这里由 :class:`SafetySceneView` 的鼠标事件路由触发。
    clicked = Signal()

    def __init__(self, item, manager: "SceneManager") -> None:
        super().__init__()
        self._item = item
        self._mgr = manager
        self._self_visible = bool(item.isVisible())
        self._eff_visible = self._self_visible
        self._interactive = False
        self._selectable = False
        self._pressed = False
        #: 组隐藏时给直接子项拍的可见性快照，显示时按它还原
        self._visibility_snapshot: Dict[int, bool] = {}

    # ------------------------------------------------------------------
    # 标识
    # ------------------------------------------------------------------
    def id(self) -> int:
        return int(self._item.item_id)

    def get_name(self) -> str:
        return self._item.get_name()

    def set_name(self, name: str) -> None:
        self._item.set_page_field("name", str(name))

    def base_item(self):
        """拿到被包装的 CoreQGraphics 图元（调试 / 逃生口用）。"""
        return self._item

    @property
    def TYPE(self) -> str:
        """转发新场景的图元类型（``text`` / ``group`` / ``rect`` …）。

        业务代码里有 ``isinstance(item, group_element)`` 这种判断；旧栈传进来的
        是旧 ``group_element``，新栈是这里的壳。两栈同时兼容靠这个标签：
        ``isinstance(x, group_element) or getattr(x, "TYPE", "") == "group"``。
        """
        return str(getattr(self._item, "TYPE", ""))

    @property
    def type(self) -> str:
        """旧 ``base_element.type`` 的同义属性（属性面板按它查中文标签）。"""
        return self.TYPE

    @property
    def m_scene(self):
        """旧图元持有场景引用（``run_property.CabinetPropertyItem`` 靠它发信号）。"""
        return self._mgr.scene

    # ------------------------------------------------------------------
    # 可见性
    # ------------------------------------------------------------------
    def get_visibility(self) -> bool:
        """自身可见标志（不看祖先），与旧 ``__invisible`` 同口径。"""
        return self._self_visible

    def set_visibility(self, enable: bool) -> None:
        enable = bool(enable)

        # 父组不可见时不允许把子项点亮——旧基类同样直接 return
        if enable and self._parent_hidden():
            return

        children = self._child_adapters()
        if not children and self._self_visible == enable:
            return          # 叶子图元：状态没变，既不用刷子树也不用重绘

        if not enable and self._self_visible and children:
            # 先记下每个成员自己的可见性，显示回来时按快照还原
            self._visibility_snapshot = {
                child.id(): child.get_visibility() for child in children
            }

        self._self_visible = enable
        self._refresh_visible()

        # 组要递归到成员：先改自己再递归，:meth:`_parent_hidden` 的判定才自洽
        for child in children:
            if enable and child.id() in self._visibility_snapshot:
                child._restore_self_visible(self._visibility_snapshot[child.id()])
            else:
                child.set_visibility(enable)

    def _restore_self_visible(self, flag: bool) -> None:
        """按快照还原某一层的自身标志（不走父可见性门控，父此时已变可见）。"""
        self._self_visible = bool(flag)
        self._refresh_visible()
        for child in self._child_adapters():
            if child.id() in self._visibility_snapshot:
                child._restore_self_visible(self._visibility_snapshot[child.id()])
            else:
                child._restore_self_visible(True)

    def _refresh_visible(self) -> None:
        """重算自己 + 全部后代的有效可见性，并写进 Qt。"""
        parent = self._mgr.parent_adapter(self._item)
        parent_eff = True if parent is None else parent._eff_visible
        self._eff_visible = self._self_visible and parent_eff
        self._item.setVisible(self._eff_visible)
        for child in self._child_adapters():
            child._refresh_visible()

    def _parent_hidden(self) -> bool:
        parent = self._mgr.parent_adapter(self._item)
        return parent is not None and not parent.get_visibility()

    # ------------------------------------------------------------------
    # 交互 / 选中 / 点击
    # ------------------------------------------------------------------
    def set_interactive(self, enable: bool) -> None:
        self._interactive = bool(enable)

    def is_interactive(self) -> bool:
        return self._interactive

    def set_selectable(self, enable: bool) -> None:
        """运行态也有「可选」概念：``handle_scene_mode_change`` 会把它打开。

        旧实现里它同时是 ``__selectable``（影响设计态选中与 hover），新场景的
        选中由 ``GraphicsScene`` 自己管，这里只记标志供业务判断，不写回 Qt。
        """
        self._selectable = bool(enable)

    def get_selectable(self) -> bool:
        return self._selectable

    def has_event_bindings(self) -> bool:
        """旧事件绑定表。安全车场景没有绑定，点击路由只认 ``is_interactive``。"""
        return False

    def is_toggle_enabled(self) -> bool:
        return False

    def handle_mouse_press(self) -> None:
        self._pressed = True

    def handle_mouse_release(self, inside: bool = True) -> None:
        if not self._pressed:
            return
        self._pressed = False
        if inside:
            self.clicked.emit()

    def contains_scene_pos(self, pos) -> bool:
        if pos is None or not self.get_visibility():
            return False
        return bool(self._item.sceneBoundingRect().contains(QPointF(pos)))

    # ------------------------------------------------------------------
    # 几何（page 坐标）
    # ------------------------------------------------------------------
    def get_scene_center_pos(self) -> QPointF:
        cx, cy = self._item.page_center()
        return QPointF(cx, cy)

    def _corner(self, sx: float, sy: float) -> QPointF:
        """图元四个角（page 坐标），旧 ``get_scene_*`` 的同一口径。

        旧实现是 ``mapToScene(_topLeft)`` 之类：把**未旋转**的局部角点绕支点
        转到场景。等价解析式就是「中心 + R(角度)·(±w/2, ±h/2)」。实测 559 个
        图元（含 70 个旋转组、8.5° 斜线）与旧值逐位相等；用旋转后的 AABB 角点
        会差到 10 单位以上，``change_position`` 绝对对齐就偏了。
        """
        w, h = self.getSize().width(), self.getSize().height()
        theta = math.radians(float(self._item.page_angle()))
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        hx, hy = sx * w / 2.0, sy * h / 2.0
        cx, cy = self._item.page_center()
        return QPointF(cx + hx * cos_t - hy * sin_t,
                       cy + hx * sin_t + hy * cos_t)

    def get_scene_topLeft(self) -> QPointF:
        return self._corner(-1.0, -1.0)

    def get_scene_topRight(self) -> QPointF:
        return self._corner(1.0, -1.0)

    def get_scene_bottomLeft(self) -> QPointF:
        return self._corner(-1.0, 1.0)

    def get_scene_bottomRight(self) -> QPointF:
        return self._corner(1.0, 1.0)

    def get_scene_head_pos(self) -> QPointF:
        return self.get_scene_topLeft()

    def get_scene_end_pos(self) -> QPointF:
        return self.get_scene_bottomRight()

    def sceneBoundingRect(self) -> QRectF:
        """旧口径：返回 page 坐标的包围盒（不是 Qt scene 坐标）。"""
        return self._item.page_bounding_rect()

    def getSize(self) -> QSizeF:
        """旧 ``getSize()``：**未旋转**的场景尺寸（旧 ``scene_size``）。

        不能用 ``page_bounding_rect()`` 的宽高——那是旋转后的轴对齐包围盒，
        转 90° 的矩形容器会宽高互换、45° 的圆会放大 √2（实测 98 个矩形全差）。
        新场景的 ``_w_view`` / ``_h_view`` 是局部矩形的视图尺寸，反投影回 page
        后与旧 ``scene_size`` 逐位相等（除线段，见 :class:`line_element`）。
        """
        w, h = self._item._proj.inverse_size(self._item._w_view,
                                             self._item._h_view)
        return QSizeF(w, h)

    def change_position(self, pos: QPointF) -> None:
        """把图元**左上角**移到 ``pos``（旧 ``change_position`` 语义）。

        平移用 ``item.pos()`` 而不是 ``scenePos()``：有自定义支点
        （``origin_pos`` ≠ 中心）且旋转非 0 时两者恒差「绕支点那一转」的位移，
        拿 ``scenePos()`` 当基准会越挪越偏（见 ``g_element.set_page_center``）。
        """
        cur = self.get_scene_topLeft()
        dx, dy = float(pos.x()) - cur.x(), float(pos.y()) - cur.y()
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return
        proj = self._item._proj
        delta = proj.point(dx, dy) - proj.point(0.0, 0.0)
        self._item.setPos(self._item.pos() + delta)

    def change_end_pos(self, pos: QPointF) -> None:
        """线段类专用：把终点挪到 ``pos``，起点不动。"""
        setter = getattr(self._item, "set_page_head_end", None)
        if setter is None:
            return
        setter(self.get_scene_head_pos(), QPointF(pos))

    def rotate_to_ang(self, ang: float) -> None:
        """绝对角度（度）。旧实现是 ``ang + m_angle_init``，初值通常是 0。"""
        setter = getattr(self._item, "set_page_angle", None)
        if setter is not None:
            setter(float(ang))

    def get_angle(self) -> float:
        return float(self._item.page_angle())

    # ------------------------------------------------------------------
    # 颜色 / 填充（映射到新场景的 Style）
    # ------------------------------------------------------------------
    def get_color(self) -> QColor:
        c = self._item._style.stroke
        return QColor(c.red(), c.green(), c.blue())

    def set_color(self, color) -> None:
        self._item.set_style_value("stroke", _color_text(color))

    def get_fill_color(self) -> QColor:
        c = self._item._style.fill_color
        return QColor(c.red(), c.green(), c.blue())

    def set_fill_color(self, color) -> None:
        self._item.set_style_value("fill_color", _color_text(color))

    def get_fill(self) -> bool:
        return bool(self._item._style.fill)

    def set_fill(self, state: bool) -> None:
        self._item.set_style_value("fill", bool(state))

    # ------------------------------------------------------------------
    # 文本
    # ------------------------------------------------------------------
    @property
    def context(self) -> str:
        return getattr(self._item, "context", "") or ""

    @context.setter
    def context(self, value) -> None:
        """走 ``set_page_field`` 才会触发重绘与边框联动（新场景 context 是裸属性）。"""
        self._item.set_page_field("context", "" if value is None else str(value))

    # ------------------------------------------------------------------
    # 父子
    # ------------------------------------------------------------------
    def _child_adapters(self) -> List["base_element"]:
        return [self._mgr.adapter_of(cid) for cid in self._item.children_ids
                if self._mgr.adapter_of(cid) is not None]

    def childItems(self) -> List["base_element"]:
        return self._child_adapters()

    def parentItem(self) -> Optional["base_element"]:
        """旧 ``parentItem()``：返回父组的壳（无父时 None）。"""
        return self._mgr.parent_adapter(self._item)

    def is_has_child(self) -> bool:
        return bool(self._item.children_ids)

    def is_has_parent(self) -> bool:
        return bool(self._item.parent_id)

    def is_in_group(self) -> bool:
        """与旧 ``is_in_group()`` 同义：有父对象即视为组内成员。"""
        return bool(self._item.parent_id)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.get_name()!r} id={self.id()}>"


class group_element(base_element):
    """组（旧 ``group_element`` 继承 ``rect_element``，这里保持同样层次）。"""


class rect_element(base_element):
    pass


class text_element(base_element):
    pass


class line_element(base_element):
    """线段。

    旧场景里 ``get_scene_head_pos()`` / ``get_scene_end_pos()`` 对**顶点类**
    返回第一个/最后一个顶点，不是包围盒角点——斜线起点根本不在 bbox 左上角
    （料仓实测差 917 page 单位）。所以这里走 ``head_pos`` / ``end_pos`` 记录。
    """

    def _page_point(self, key: str) -> QPointF:
        item = self._item
        if getattr(item, "_geo_dirty", False):
            bake = getattr(item, "_bake_live_geometry", None)
            if bake is not None:
                bake()
        raw = item._page.get(key) or {}
        return QPointF(float(raw.get("x", 0.0)), float(raw.get("y", 0.0)))

    def get_scene_head_pos(self) -> QPointF:
        return self._page_point("head_pos")

    def get_scene_end_pos(self) -> QPointF:
        return self._page_point("end_pos")

    def getSize(self) -> QSizeF:
        """旧 ``line_element.scene_size`` 是「起点到终点的跨度」，不含线宽且**未旋转**。

        新场景 ``_page["head_pos"/"end_pos"]`` 存的是 page 场景坐标（已被旋转），
        直接求差是「转过的向量」（一条 8.5° 的近竖线会算成 90.86×593.02，旧值
        是 2.20×599.94）。先把差值按 ``-page_angle`` 转回图元自身方向，再取绝对值。
        """
        head, end = self.get_scene_head_pos(), self.get_scene_end_pos()
        dx, dy = end.x() - head.x(), end.y() - head.y()
        theta = math.radians(float(self._item.page_angle()))
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        # 屏幕坐标（y 向下）里把向量转回未旋转方向
        lx = dx * cos_t + dy * sin_t
        ly = -dx * sin_t + dy * cos_t
        return QSizeF(abs(lx), abs(ly))


class triangle_element(base_element):
    pass


class circle_element(base_element):
    pass


class polygon_element(base_element):
    pass


class path_element(base_element):
    pass


class image_element(base_element):
    pass


class checkbox_element(base_element):
    pass


# 新场景 ``TYPE`` -> 适配类。业务代码用 ``isinstance(item, text_element)`` 判类型，
# 所以必须映射到真实子类，不能统一返回 base_element。
_KIND_TO_CLASS = {
    "group": group_element,
    "rect": rect_element,
    "text": text_element,
    "line": line_element,
    "triangle": triangle_element,
    "circle": circle_element,
    "polygon": polygon_element,
    "path": path_element,
    "image": image_element,
    "checkbox": checkbox_element,
}


class SceneManager(QObject):
    """旧 ``SceneManager`` 的替身：``m_items`` / ``m_sorted_items`` / ``findItem``。"""

    def __init__(self, scene: "SafetySceneView", parent=None) -> None:
        super().__init__(parent)
        self.view = scene
        self.scene: SafetyScene = scene._scene
        self.m_items: Dict[int, base_element] = {}
        self.m_name_items: Dict[str, int] = {}
        self.m_sorted_items: List[base_element] = []
        self.rebuild()

    # ------------------------------------------------------------------
    def rebuild(self) -> None:
        """按当前场景内容重建索引（图元增删、场景重载后调用）。"""
        self.m_items.clear()
        self.m_name_items.clear()
        self.m_sorted_items.clear()

        for item in self.scene.all_items():
            adapter = self._wrap(item)
            self.m_items[item.item_id] = adapter
            name = item.get_name()
            # 重名保留第一个（旧 ``construct_name_items`` 也是后一个覆盖前一个，
            # 但安全车场景的名字唯一，取第一个更稳定）
            if name and name not in self.m_name_items:
                self.m_name_items[name] = item.item_id
            self.m_sorted_items.append(adapter)

        self.m_sorted_items.sort(key=lambda a: a._item.zValue())

        # 平铺层级下组的隐藏不会带到子项：从每棵树的根往下一层层刷有效可见性，
        # 否则 JSON 里「组 visible=false、子项 visible=true」会直接画出来。
        for adapter in self.m_sorted_items:
            if not adapter._item.parent_id:
                adapter._refresh_visible()

        self.scene.scene_manager = self
        self.view.scene_manager = self

    def _wrap(self, item) -> base_element:
        cached = self.m_items.get(item.item_id)
        if cached is not None:
            return cached
        cls = _KIND_TO_CLASS.get(getattr(item, "TYPE", ""), base_element)
        return cls(item, self)

    # ------------------------------------------------------------------
    def adapter_of(self, item_id: int) -> Optional[base_element]:
        return self.m_items.get(int(item_id))

    def parent_adapter(self, item) -> Optional[base_element]:
        pid = getattr(item, "parent_id", 0)
        return self.m_items.get(int(pid)) if pid else None

    def findItemByName(self, name: str) -> Optional[base_element]:
        item_id = self.m_name_items.get(name)
        return self.m_items.get(item_id) if item_id is not None else None

    def findItem(self, item_id: int) -> Optional[base_element]:
        return self.m_items.get(int(item_id))

    def all_items(self) -> List[base_element]:
        return list(self.m_sorted_items)

    def __len__(self) -> int:
        return len(self.m_items)


class SafetyScene(GraphicsScene):
    """页面场景：模式、选中、站点切换信号，语义对齐旧 ``QuadTreeScene``。"""

    #: 旧 ``QuadTreeScene.run_mode_station_change``（``Signal(SceneMode)``）。
    #: 这里的载荷**既是** ``SceneMode``（模式切换）**又是** ``str``（切换子站点，
    #: 由 ``run_property.CabinetPropertyItem`` 发出），所以用 ``object``。
    run_mode_station_change = Signal(object)
    #: 双击空白处（旧 ``QuadTreeScene`` 同名信号）
    double_clicked_without_group = Signal()

    def __init__(self, projection=None, parent=None) -> None:
        super().__init__(projection, parent)
        self.scene_manager: Optional[SceneManager] = None
        self.view: Optional["SafetySceneView"] = None
        #: 旧场景初始值就是场景自身（业务代码靠 ``is self.scene`` 判"没选中"）
        self.current_selected = self
        #: 旧场景的渲染回调，运行态一直赋 None；保留属性避免 AttributeError
        self.update_callback = None
        self._load_done = False
        # 旧 ``QuadTreeScene`` 把 sceneRect 固定成 ±100000，视图因此可以滚到任意
        # 位置（``goto_sence_origin`` / ``centerOn(0,0)`` 不被夹住）。新场景默认
        # 用图元包围盒当 sceneRect，``centerOn`` 会被滚动条范围夹住，取景就跑偏
        # （实测画面整体偏了半个场景）。这里照旧给一个足够大的范围。
        self.setSceneRect(QRectF(-100000.0, -100000.0, 200000.0, 200000.0))

    # ------------------------------------------------------------------
    # 模式
    # ------------------------------------------------------------------
    def mode(self) -> SceneMode:
        return SceneMode.Run if self.is_run_mode else SceneMode.Design

    def set_scene_mode(self, mode) -> None:
        """兼容 ``SceneMode`` 与 ``bool`` 两种写法（新场景原生是 bool）。"""
        run = (mode == SceneMode.Run) if isinstance(mode, SceneMode) else bool(mode)
        super().set_scene_mode(run)
        if run:
            self.current_selected = self
        self.run_mode_station_change.emit(
            SceneMode.Run if run else SceneMode.Design)

    def toggle_sence_mode(self) -> None:
        """旧语义：切回设计态会把所有图元显示出来。"""
        if self.is_run_mode:
            for adapter in (self.scene_manager.m_sorted_items
                            if self.scene_manager else []):
                adapter.set_visibility(True)
            self.set_scene_mode(SceneMode.Design)
        else:
            self.set_scene_mode(SceneMode.Run)

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def resolve_scene_path(self, filename: str) -> str:
        """``safety_car_scene.json`` -> ``res/myDesigner/scene/...``（绝对路径原样）。"""
        name = filename or DEFAULT_SCENE_NAME
        return name if os.path.isabs(name) else res_mng.get_json_path(name)

    def load_element_info_run_mode(self, filename: str = DEFAULT_SCENE_NAME) -> int:
        """旧入口名：只读加载页面。返回图元数量（0 表示文件不存在或为空）。"""
        path = self.resolve_scene_path(filename)
        if not os.path.isfile(path):
            print(f"场景文件不存在，按空场景处理: {path}")
            self._load_done = True
            return 0
        count = self.load_page(path)
        self._load_done = True
        if self.scene_manager is not None:
            self.scene_manager.rebuild()
        return count

    def loadDone(self) -> bool:
        return self._load_done

    # ------------------------------------------------------------------
    # 选中
    # ------------------------------------------------------------------
    def set_current_select_item(self, item) -> None:
        if item is not self.current_selected:
            self.current_selected = item
            self.selectionChanged.emit()

    def selected_top_level_items(self) -> List[base_element]:
        if self.scene_manager is None:
            return []
        return [a for a in self.scene_manager.m_sorted_items
                if a.get_selectable() and not a.is_has_parent()]

    # ------------------------------------------------------------------
    # 取景（旧场景是自绘 widget，实际动作落在 view 上）
    # ------------------------------------------------------------------
    def restore_saved_view(self, animate: bool = True) -> bool:
        """按页面保存的 ``sceneRect`` 恢复视图范围；没有记录返回 False。"""
        rect = self.view_scene_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            return False
        if self.view is None:
            return False
        self.view.fit_page_rect(rect)
        return True

    def goto_sence_origin(self) -> None:
        if self.view is not None:
            self.view.goto_origin()


class SafetySceneView(GraphicsView):
    """运行态视图：既是布局里的 widget，也是业务代码眼里的「场景」。

    输入门控沿用 ``GraphicsView`` 的统一开关（``set_canvas_navigation_enabled``），
    运行态默认关掉中键/空格平移与滚轮缩放；左键留给点击路由。
    """

    double_clicked_without_group = Signal()

    #: 旧 ``shutdown()`` 会挨个 ``getattr(scene, "<name>", None).stop()``
    _DEAD_TIMER_NAMES = ("render_timer", "frame_count_timer", "timer1", "timer2")

    def __init__(self, scene: Optional[SafetyScene] = None, parent=None) -> None:
        self._scene = scene or SafetyScene()
        super().__init__(self._scene, parent)
        self._scene.view = self
        self.setObjectName("safetyCarScene")
        self.setDragMode(GraphicsView.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.StrongFocus)
        # 页面背景带 alpha 时按 viewport 底色合成；旧 QuadTreeScene 是自绘
        # QWidget，底色取 Window，不统一会让整幅画面每个像素偏几级。
        palette = self.viewport().palette()
        palette.setColor(QPalette.Base, palette.color(QPalette.Window))
        self.viewport().setPalette(palette)
        self.show_grid = False
        self.snap.grid_enabled = False
        self.snap.show_markers = False
        self.set_canvas_navigation_enabled(False)

        self.scene_manager: Optional[SceneManager] = None
        self.update_callback = None
        self._pressed_adapter: Optional[base_element] = None
        self.on_viewport_resized = None
        for name in self._DEAD_TIMER_NAMES:
            setattr(self, name, None)

        # 场景信号转出来：业务代码连的是 ``scene.selectionChanged`` /
        # ``scene.double_clicked_without_group``，这里保持同名。
        self._scene.double_clicked_without_group.connect(
            self.double_clicked_without_group)

    # ------------------------------------------------------------------
    # 代理场景接口（业务代码里的 self.scene 就是本类实例）
    # ------------------------------------------------------------------
    @property
    def selectionChanged(self):
        return self._scene.selectionChanged

    @property
    def run_mode_station_change(self):
        return self._scene.run_mode_station_change

    @property
    def current_selected(self):
        cur = self._scene.current_selected
        # 旧代码用 ``selected_item is self.scene`` 判「没选中任何图元」；
        # 场景自身换成 view 返回，判断才成立。
        return self if cur is self._scene else cur

    @current_selected.setter
    def current_selected(self, value) -> None:
        self._scene.current_selected = value

    def set_current_select_item(self, item) -> None:
        self._scene.set_current_select_item(item)

    def selected_top_level_items(self):
        return self._scene.selected_top_level_items()

    # -- 页面背景 / 画布信息（NavigationContentWidget 的「页面背景」「画布设置」页）--
    def get_bg_color(self) -> QColor:
        return self._scene.backgroundBrush().color()

    def set_bg_color(self, color) -> None:
        self._scene.setBackgroundBrush(QColor(color))

    @property
    def grid_size(self) -> float:
        return float(getattr(self._scene.projection, "grid_size", 0.0) or 0.0)

    @property
    def scene_units_per_grid_x(self) -> float:
        return float(getattr(self._scene.projection, "units_x", 0.0) or 0.0)

    @property
    def scene_units_per_grid_y(self) -> float:
        return float(getattr(self._scene.projection, "units_y", 0.0) or 0.0)

    @property
    def scale_factor(self) -> float:
        """旧场景的当前缩放；这里取视图变换（运行态主要用于只读展示）。"""
        return abs(float(self.transform().m11()))

    @property
    def is_use_for_agv_map(self) -> bool:
        return bool(getattr(self._scene.projection, "agv", False))

    def mode(self) -> SceneMode:
        return self._scene.mode()

    def set_scene_mode(self, mode) -> None:
        self._scene.set_scene_mode(mode)

    def set_scene_manager(self, manager) -> None:
        """旧场景的注入点；转发到场景与自身，两边都拿到同一份索引。"""
        self.scene_manager = manager
        self._scene.scene_manager = manager
        if manager is not None:
            manager.view = self
            manager.scene = self._scene

    def toggle_sence_mode(self) -> None:
        self._scene.toggle_sence_mode()

    def load_element_info_run_mode(self, filename: str = DEFAULT_SCENE_NAME) -> int:
        count = self._scene.load_element_info_run_mode(filename)
        if self.scene_manager is not None:
            self.scene_manager.rebuild()
        return count

    def loadDone(self) -> bool:
        return self._scene.loadDone()

    def restore_saved_view(self, animate: bool = True) -> bool:
        return self._scene.restore_saved_view(animate)

    def goto_sence_origin(self) -> None:
        self._scene.goto_sence_origin()

    def fit_page_rect(self, rect: QRectF) -> None:
        """按 page 矩形等比铺满视口（旧 ``_apply_view_state`` 同口径）。

        必须手算 ``scale()``，不用 ``fitInView``：后者内部取整，同一面板会比旧
        场景小半个百分点。旧公式是 ``min(w/rect_w, h/rect_h)`` 并夹在
        ``[0.01, 10]``，这里照抄。
        """
        avail = self.viewport().rect()
        if avail.width() < 8 or avail.height() < 8:
            return
        target = self._scene.projection.rect(rect)
        if target.width() <= 0 or target.height() <= 0:
            return
        scale = min(avail.width() / target.width(), avail.height() / target.height())
        scale = max(0.01, min(10.0, scale))
        self.resetTransform()
        self.scale(scale, scale)
        self.centerOn(target.center())

    def goto_origin(self) -> None:
        """1:1 回到原点（旧 ``goto_sence_origin`` 是带动画，这里直接落位）。"""
        self.resetTransform()
        self.centerOn(0.0, 0.0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if callable(self.on_viewport_resized):
            self.on_viewport_resized()

    # ------------------------------------------------------------------
    # 运行态点击路由（旧 ``_find_event_group_at`` + press/release 时序）
    # ------------------------------------------------------------------
    def _hit_interactive(self, scene_pos: QPointF) -> Optional[base_element]:
        manager = self.scene_manager
        if manager is None:
            return None
        for adapter in reversed(manager.m_sorted_items):
            if not isinstance(adapter, (group_element, checkbox_element)):
                continue
            if not adapter.get_visibility():
                continue
            if not (adapter.is_interactive() or adapter.has_event_bindings()
                    or adapter.is_toggle_enabled()):
                continue
            if adapter._item.sceneBoundingRect().contains(scene_pos):
                return adapter
        return None

    def _view_to_scene(self, event) -> QPointF:
        """事件位置（视口坐标）→ 场景坐标。命中测试用的是场景坐标。"""
        return self.mapToScene(event.position().toPoint())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.is_pan_event(event):
            if self._pan_enabled:
                GraphicsView.mousePressEvent(self, event)
            else:
                event.accept()
            return
        if event.button() == Qt.RightButton:
            return                      # 运行态不弹设计器右键菜单
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton and self._scene.is_run_mode:
            previous = self._pressed_adapter
            if previous is not None:
                previous.handle_mouse_release(False)
            self._pressed_adapter = self._hit_interactive(self._view_to_scene(event))
            if self._pressed_adapter is not None:
                self._pressed_adapter.handle_mouse_press()
                # 旧场景在运行态补一次选中通知：站点说明面板与 IO 联动靠它
                self._scene.set_current_select_item(self._pressed_adapter)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            GraphicsView.mouseReleaseEvent(self, event)
            return
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton and self._scene.is_run_mode:
            pressed, self._pressed_adapter = self._pressed_adapter, None
            if pressed is not None:
                pressed.handle_mouse_release(
                    pressed.contains_scene_pos(self._view_to_scene(event)))

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.LeftButton and self._scene.is_run_mode:
            if self._hit_interactive(self._view_to_scene(event)) is None:
                self.double_clicked_without_group.emit()
                self._scene.set_current_select_item(self._scene)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            GraphicsView.mouseMoveEvent(self, event)
            return
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # 运行态不响应设计器快捷键；空格是第二种平移手势（门控在基类里）
        if event.key() == Qt.Key_Space and self.is_pan_enabled():
            super().keyPressEvent(event)
            return
        event.accept()

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space:
            super().keyReleaseEvent(event)
            return
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def fit_scene(self) -> None:
        """窗口出现 / 改尺寸时的兜底取景：优先用页面保存范围，没有就 fit_rect。"""
        rect = self._scene.view_scene_rect()
        if rect.width() > 0 and rect.height() > 0:
            self.fit_page_rect(rect)
            return
        fit = self._scene.fit_rect(0.0)
        if fit.width() > 0 and fit.height() > 0:
            self.fit_page_rect(fit)
