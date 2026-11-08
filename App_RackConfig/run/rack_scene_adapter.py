"""把 CoreQGraphics 场景包装成旧 ``Designer.Core`` 的 SceneManager / 图元接口。

为什么要这层
------------
``App_RackConfig/run`` 下的 4 个 model（``RackStoreModel`` /
``RackStatusPanelModel`` / ``RackHmiConfigModel`` / ``RackProcessModel``）合计
两千多行，但对外只用到旧场景的一小组接口（可见性、几何、颜色、文本、组点击）。
直接重写它们风险大、收益低，因此这里做一层**薄适配**：把 CoreQGraphics 的
``BaseItem`` 包成旧 ``base_element`` 的形状，model 层保持零改动。

坐标系铁律
----------
旧场景没有投影层，``sceneBoundingRect()`` / ``get_scene_*_pos()`` 返回的就是
page 坐标；新场景多了一层 ``SceneProjection``（AGV 场景带轴交换与取反）。
所以这里的**对外几何接口一律走 page 坐标**：

* ``page_center()``            -> ``get_scene_center_pos()``
* ``page_bounding_rect()``     -> ``sceneBoundingRect()`` / ``get_scene_topLeft()``
                                  / ``get_scene_head_pos()`` / ``get_scene_end_pos()``

已实测：``page_bounding_rect()`` 与旧 ``get_scene_topLeft()`` /
``get_scene_end_pos()`` 在矩形类、组、文本上逐位相等（Δ=0.00）。

可见性为什么要递归
------------------
旧场景是 QGraphicsItem 父子层级，组隐藏后子项**不绘制**；新场景是平铺层级
（只有 ``parent_id`` 记账，不用 ``setParentItem``），组的 ``setVisible(False)``
**不会**带到子项。如果照抄「只改自己」，组一隐藏子项会全部浮出来。

所以适配层里每个壳维护两份状态：

* ``_self_visible`` —— 自身标志，对应旧 ``__invisible``，``get_visibility()`` 读它；
* ``_eff_visible``  —— 自身标志 AND 所有祖先，真正写进 ``item.setVisible()``。

``set_visibility(True)`` 在父不可见时直接忽略，与旧 ``base_element`` 一致
（旧注释：「父组不可见时 set_visibility(True) 会被基类直接忽略」）。组隐藏前
会给直接子项做快照，显示时按快照还原——不然「组隐藏→组显示」会把组内原本
单独隐藏的成员一起点亮，运行态反复切站就会把整场景冲成一片 True。
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QFrame

# 允许以脚本方式单独 import 本文件
if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

from Designer.CoreQGraphics import GraphicsScene, GraphicsView   # noqa: E402


def _color_text(color) -> str:
    """QColor -> ``#rrggbb``（旧 ``get_color`` / ``get_fill_color`` 都不带 alpha）。"""
    if isinstance(color, QColor):
        return color.name()
    return str(color)


class base_element(QObject):
    """单个图元的适配壳：接口形状对齐旧 ``Designer.Core.elements.base_element``。"""

    # 旧场景里点击由 ``toggle()`` + ``_emit_event(EVENT_CLICK)`` 发信号，
    # 这里由 :class:`RackScene` 的鼠标事件路由触发。
    clicked = Signal()

    def __init__(self, item, manager: "SceneManager") -> None:
        super().__init__()
        self._item = item
        self._mgr = manager
        self._self_visible = bool(item.isVisible())
        self._eff_visible = self._self_visible
        self._interactive = False
        # 组隐藏时给直接子项拍的可见性快照，显示时按它还原
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

        model 里有 ``isinstance(item, text_element)`` 这种判断；旧栈传进来的是
        旧 ``text_element`` 实例，新栈是适配壳。两栈同时兼容要靠这个标签：
        ``isinstance(...) or getattr(item, "TYPE", "") == "text"``。
        """
        return str(getattr(self._item, "TYPE", ""))

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
    # 交互 / 点击
    # ------------------------------------------------------------------
    def set_interactive(self, enable: bool) -> None:
        self._interactive = bool(enable)

    def is_interactive(self) -> bool:
        return self._interactive

    # ------------------------------------------------------------------
    # 几何（page 坐标）
    # ------------------------------------------------------------------
    def get_scene_center_pos(self) -> QPointF:
        cx, cy = self._item.page_center()
        return QPointF(cx, cy)

    def get_scene_topLeft(self) -> QPointF:
        return self._item.page_bounding_rect().topLeft()

    def get_scene_head_pos(self) -> QPointF:
        return self.get_scene_topLeft()

    def get_scene_end_pos(self) -> QPointF:
        return self._item.page_bounding_rect().bottomRight()

    def sceneBoundingRect(self) -> QRectF:
        """旧口径：返回 page 坐标的包围盒（不是 Qt scene 坐标）。"""
        return self._item.page_bounding_rect()

    def change_position(self, pos: QPointF) -> None:
        """把图元**左上角**移到 ``pos``（旧 ``group_element.change_position`` 语义）。

        实测旧实现：``change_position(100,200)`` 之后
        ``sceneBoundingRect().topLeft() == (100,200)``，尺寸不变。

        平移用 ``item.pos()`` 而不是 ``scenePos()``：有自定义支点
        （``origin_pos`` ≠ 中心）且旋转非 0 时两者恒差「绕支点那一转」的位移，
        拿 ``scenePos()`` 当基准会越挪越偏（详见 g_element.set_page_center 的注释）。
        """
        cur = self._item.page_bounding_rect().topLeft()
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

    def is_has_child(self) -> bool:
        return bool(self._item.children_ids)

    def is_has_parent(self) -> bool:
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
    返回的是第一个/最后一个顶点，不是包围盒角点——斜线的起点根本不在
    bbox 的左上角（实测斜线差 917 page 单位）。所以这里必须走 ``head_pos`` /
    ``end_pos`` 记录，不能用基类那套包围盒口径。
    """

    def _page_point(self, key: str) -> QPointF:
        item = self._item
        if getattr(item, "_geo_dirty", False):
            # 拖动 / change_position 只改 Qt 变换，记录会陈旧；烘焙一次把实时
            # 几何折回 _page（设计器存盘走的就是这条路）
            bake = getattr(item, "_bake_live_geometry", None)
            if bake is not None:
                bake()
        raw = item._page.get(key) or {}
        return QPointF(float(raw.get("x", 0.0)), float(raw.get("y", 0.0)))

    def get_scene_head_pos(self) -> QPointF:
        return self._page_point("head_pos")

    def get_scene_end_pos(self) -> QPointF:
        return self._page_point("end_pos")


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


# 新场景 ``TYPE`` -> 适配类。旧代码用 ``isinstance(item, text_element)`` 判文本，
# 所以类型必须映射到真实的子类，不能统一返回 base_element。
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
    """旧 ``SceneManager`` 的替身：``m_items`` / ``m_sorted_items`` / ``findItemByName``。"""

    def __init__(self, scene: "RackScene", parent=None) -> None:
        super().__init__(parent)
        self.scene = scene
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
            # 重名保留第一个：``RackStoreModel._register`` 也是「已忽略后一个」
            if name and name not in self.m_name_items:
                self.m_name_items[name] = item.item_id
            self.m_sorted_items.append(adapter)

        self.m_sorted_items.sort(key=lambda a: a._item.zValue())

        # 平铺层级下组的隐藏不会带到子项，这里从每棵树的根往下一层层刷有效可见性；
        # 不刷的话 JSON 里「组 visible=false、子项 visible=true」会直接画出来。
        for adapter in self.m_sorted_items:
            if not adapter._item.parent_id:
                adapter._refresh_visible()

        if isinstance(self.scene, RackScene):
            self.scene.scene_manager = self

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

    def __len__(self) -> int:
        return len(self.m_items)


class RackScene(GraphicsScene):
    """运行时场景：只加点击路由，其余行为与 ``GraphicsScene`` 一致。

    旧场景在 ``mouseReleaseEvent`` 里发 ``clicked``（按下记锚点、释放判是否
    仍在组内），这里照抄同一套时序，避免「按下后拖出去松手」误触发。
    """

    double_clicked_without_group = Signal()

    def __init__(self, projection=None, parent=None) -> None:
        super().__init__(projection, parent)
        self.scene_manager: Optional[SceneManager] = None
        self._pressed_group: Optional[base_element] = None

    # ------------------------------------------------------------------
    def _hit_group(self, scene_pos: QPointF) -> Optional[base_element]:
        """最顶层的可点击图元：组 / 复选框 + 可见 + 交互开启 + 命中包围盒。

        与旧 ``_find_event_group_at`` 同口径（按 z 从大到小取第一个），
        但只认 ``is_interactive()``——旧实现还认事件绑定与复选框开关，
        料仓这套场景只用 ``set_interactive(True)``。
        """
        manager = self.scene_manager
        if manager is None:
            return None
        for adapter in reversed(manager.m_sorted_items):
            if not isinstance(adapter, (group_element, checkbox_element)):
                continue
            if not adapter.get_visibility():
                continue
            if not adapter.is_interactive():
                continue
            if adapter._item.sceneBoundingRect().contains(scene_pos):
                return adapter
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton and self.is_run_mode:
            self._pressed_group = self._hit_group(event.scenePos())

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton or not self.is_run_mode:
            return
        pressed, self._pressed_group = self._pressed_group, None
        if pressed is None:
            return
        # 松手时鼠标已经移出组外就不算一次点击（旧 handle_mouse_release(inside)）
        if pressed._item.sceneBoundingRect().contains(event.scenePos()):
            pressed.clicked.emit()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        super().mouseDoubleClickEvent(event)
        if event.button() == Qt.LeftButton and self.is_run_mode:
            if self._hit_group(event.scenePos()) is None:
                self.double_clicked_without_group.emit()


class RackSceneView(GraphicsView):
    """运行态视图：只显示不编辑，取景口径与旧 ``QuadTreeScene`` 一致。

    旧 ``QuadTreeScene`` 在 Run 态按 ``min(视口宽/页面宽, 视口高/页面高)``
    等比铺满（**允许放大**）。这里照抄同一口径，并且：

    * ``setFrameShape(NoFrame)`` —— ``QGraphicsView`` 默认 1px 边框会让 viewport
      比控件小 2px，缩放到不了旧版那个值；
    * 手算 ``scale()`` 而不是 ``fitInView`` —— 后者内部取整，同一面板会比旧版
      小半个百分点；
    * 设计网格必须显式关（``drawBackground`` 只看 ``show_grid`` /
      ``snap.grid_enabled``，不看 ``is_run_mode``）。
    """

    double_clicked_without_group = Signal()

    def __init__(self, scene=None, parent=None) -> None:
        super().__init__(scene, parent)
        self.setDragMode(GraphicsView.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.StrongFocus)
        # 页面背景色带 alpha（scene2 是 #bee1f59b），会按 viewport 底色做合成。
        # QGraphicsView 的 viewport 默认用 QPalette.Base（白），而旧 QuadTreeScene
        # 是自绘 QWidget、底色是 Window（#efefef）—— 不统一的话整幅画面每个像素
        # 都会偏 4~8 级，肉眼几乎看不出但对拍是 90% 差异。
        palette = self.viewport().palette()
        palette.setColor(QPalette.Base, palette.color(QPalette.Window))
        self.viewport().setPalette(palette)
        self.show_grid = False
        self.snap.grid_enabled = False
        self.snap.show_markers = False
        # 运行态默认不许拖拽 / 缩放；要放开只调这一个开关。
        self.set_canvas_navigation_enabled(False)
        # 视图撑开是在 show 时由布局完成的，窗口自己的 resizeEvent 拿不到
        # 「最终的视口尺寸」，所以取景挂在视口这一头。
        self.on_viewport_resized = None
        # 旧代码把 Scene 同时当视图用，双击空白处的信号也挂在它上面；
        # 这里把场景的信号转出来，调用方一行都不用改。
        if scene is not None and hasattr(scene, "double_clicked_without_group"):
            scene.double_clicked_without_group.connect(
                self.double_clicked_without_group)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if callable(self.on_viewport_resized):
            self.on_viewport_resized()

    def fit_scene(self) -> None:
        """等比铺满视口（与旧 ``QuadTreeScene`` 的 ``scale_factor`` 同口径）。"""
        scene = self.scene()
        if scene is None:
            return
        rect = scene.view_scene_rect()
        if rect.isEmpty():
            return
        avail = self.viewport().rect()
        if avail.width() < 8 or avail.height() < 8:
            # 还没 show / 布局没跑完，此时视口是默认极小尺寸，算出来的缩放会离谱
            return
        target = scene.projection.rect(rect)
        if target.width() <= 0 or target.height() <= 0:
            return
        scale = min(avail.width() / target.width(), avail.height() / target.height())
        self.resetTransform()
        self.scale(scale, scale)
        self.centerOn(target.center())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # 右键（设计器上下文菜单）一律吞掉；中键只在导航开启时交给基类平移。
        if event.button() == Qt.RightButton:
            event.accept()
            return
        if event.button() == Qt.MiddleButton and not self.is_pan_enabled():
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            event.accept()
            return
        if event.button() == Qt.MiddleButton and not self.is_pan_enabled():
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # 空格 = 第二种平移手势；其余按键在运行态不应改场景
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
