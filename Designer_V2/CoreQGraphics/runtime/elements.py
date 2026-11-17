"""统一运行态：图元门面 :class:`RuntimeElement` 与索引 :class:`RuntimeRegistry`。

这套东西取代的是四份互相复制的实现：

=========================================  ======================================
现状                                        本模块
=========================================  ======================================
``rack_scene_adapter.base_element``         :class:`RuntimeElement`
``safety_scene_adapter.base_element``       :class:`RuntimeElement`
``qgraphics_runtime.RuntimeCard``           :class:`RuntimeElement`（widget 子集）
三份 ``SceneManager``                       :class:`RuntimeRegistry` + :class:`LegacyManager`
=========================================  ======================================

三条设计取舍
------------
1. **门面不持有图元对象**：只记 ``item_id``，每次用 :meth:`RuntimeElement.item`
   向场景按 id 现查。``load_page`` / ``restore`` 会 ``clear_page()`` 销毁全部
   ``QGraphicsItem``，旧实现缓存包装对象，重载后一律变成悬空引用
   （设计文档 D-3）。这里最多返回 ``None``，绝不会碰已析构的 C++ 对象。
2. **门面对象跨换页复用**：业务 model 在构造时 ``connect(element.clicked)``，
   换页不应把连接弄丢。:meth:`RuntimeRegistry.rebuild` 对仍在的 id 复用同一个
   :class:`RuntimeElement` 实例，只刷新它的附着状态；消失的 id 标成 detached。
3. **运行态不改设计数据**：可见性只写 ``QGraphicsItem.setVisible()``，不走
   ``set_page_field("visible")``，所以 ``page_data()`` / JSON round-trip 不受
   运行态开关影响。文本 / 颜色 / 交互状态按既有 model 口径走
   ``set_page_field`` / ``set_style_value``（运行态不保存页面，因此无副作用）。

坐标口径（与三套适配层一致）
----------------------------
* 对业务暴露的 ``sceneBoundingRect()`` / ``get_scene_*_pos()`` 一律是
  **Qt 场景坐标 = page 坐标**；
* ``contains_view_pos()`` 收的是 ``QGraphicsScene`` 的场景坐标（鼠标事件用）；
* ``getSize()`` 用未旋转的场景尺寸，**不能**用旋转后的包围盒宽高；
* 四角是解析式 ``center + R(theta)·(±w/2, ±h/2)``，不是 AABB 角点。
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any, Callable, Iterable, Optional

from PySide6.QtCore import QObject, QPointF, QRectF, QSizeF, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsItem

if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

try:
    from ..g_binding import BY_KEY, coerce as _coerce
    from ..g_style import (
        FILL_STYLE_DEFAULT, TEXT_ALIGN_DEFAULT, normalize_brush_style,
        normalize_text_align, parse_color as _parse_color,
    )
except ImportError:  # 脚本直跑兜底
    from g_binding import BY_KEY, coerce as _coerce  # type: ignore
    from g_style import (  # type: ignore
        FILL_STYLE_DEFAULT, TEXT_ALIGN_DEFAULT, normalize_brush_style,
        normalize_text_align, parse_color as _parse_color,
    )


def _color_text(color: Any) -> str:
    """把 QColor / 字符串 / RGB 三元组统一成 ``#RRGGBB``。"""
    if isinstance(color, str):
        c = QColor(color)
        return c.name() if c.isValid() else color
    if isinstance(color, QColor):
        return color.name()
    if isinstance(color, (tuple, list)) and len(color) >= 3:
        return QColor(int(color[0]), int(color[1]), int(color[2])).name()
    return QColor(color).name()


def _norm_angle(angle: float) -> float:
    """把角度规整到 [0, 360)，与 PageDeck 的角度账本同口径。"""
    return float(angle) % 360.0


class GeometryProfile:
    """几何口径策略——三套旧适配层对「角点」的定义并不相同。

    ====================  =====================  ==========================
    预设                   四角                    线段 head/end
    ====================  =====================  ==========================
    :data:`STRICT_PROFILE` 解析式旋转角（正确）   记录优先，无记录回退解析式角
    :data:`RACK_PROFILE`   ``page_bounding_rect``  记录优先，无记录回退 AABB 角
    :data:`SAFETY_PROFILE` 解析式旋转角           同 strict，保留别名标来源
    ====================  =====================  ==========================

    三套旧适配层的 ``line_element`` 都用 ``head_pos`` / ``end_pos`` 记录取真实
    端点（斜线起点不在包围盒角上），所以端点默认一律「记录优先」；只有四角
    的定义真的不同。

    迁移既有 model 时**必须选对 profile**，否则旋转图元的坐标会差几十到几百
    page 单位，看起来像「框架算错了」其实只是口径不同。新写的业务建议统一
    用 :data:`STRICT_PROFILE`。
    """

    def __init__(self, name: str, corners: str, endpoints: str) -> None:
        if corners not in ("analytic", "aabb"):
            raise ValueError("corners 必须是 analytic / aabb")
        if endpoints not in ("record", "analytic", "aabb"):
            raise ValueError("endpoints 必须是 record / analytic / aabb")
        self.name = name
        self.corners = corners
        self.endpoints = endpoints

    def __repr__(self) -> str:
        return f"<GeometryProfile {self.name}>"


STRICT_PROFILE = GeometryProfile("strict", "analytic", "record")
RACK_PROFILE = GeometryProfile("rack", "aabb", "record")
SAFETY_PROFILE = GeometryProfile("safety", "analytic", "record")
GEOMETRY_PROFILES = {
    p.name: p for p in (STRICT_PROFILE, RACK_PROFILE, SAFETY_PROFILE)}


class RuntimeElement(QObject):
    """一个 page 图元在运行态的稳定门面（普通图元与 widget 图元共用）。

    ``clicked`` 由 :class:`~.view.RuntimeScene` 的点击路由发出；业务只需要
    ``set_interactive(True)`` 打开某个图元的点击。
    """

    clicked = Signal()
    visibilityChanged = Signal(bool)

    def __init__(self, item_id: int, registry: "RuntimeRegistry") -> None:
        super().__init__(registry)
        self._item_id = int(item_id)
        self._registry = registry
        self._self_visible = True
        self._eff_visible = True
        self._interactive = False
        self._readonly = False
        self._motion_cache = False
        self._visibility_snapshot: dict[int, bool] = {}
        self._detached = False

    # -- 附着 / 生命周期 ------------------------------------------------
    def item(self):
        """当前页面里对应的 ``BaseItem``；页面已换掉时返回 ``None``。

        不缓存，避免持有已析构的 QGraphicsItem。
        """
        if self._detached:
            return None
        scene = self._registry.scene
        if scene is None:
            return None
        return scene.find_item(self._item_id)

    def base_item(self):
        """``rack_scene_adapter.base_element`` 同名兼容接口。"""
        return self.item()

    def is_detached(self) -> bool:
        return self._detached

    def _adopt(self, item, *, reset_visibility: bool = True) -> None:
        self._detached = False
        if reset_visibility:
            self._self_visible = bool(item.get_visibility())
            self._visibility_snapshot.clear()

    def _detach(self) -> None:
        self._detached = True
        self._eff_visible = False

    # -- 标识 / 类型 ----------------------------------------------------
    @property
    def item_id(self) -> int:
        return self._item_id

    def id(self) -> int:  # noqa: A003 - 旧 API 命名
        return self._item_id

    def get_name(self) -> str:
        it = self.item()
        return it.get_name() if it is not None else ""

    def set_name(self, name: str) -> None:
        it = self.item()
        if it is not None:
            it.set_name(str(name))
            self._registry.reindex_names()

    @property
    def name(self) -> str:
        return self.get_name()

    @property
    def TYPE(self) -> str:  # noqa: N802 - 旧 API 命名
        it = self.item()
        return str(it.TYPE) if it is not None else ""

    def type(self) -> str:  # noqa: A003 - safety 适配层口径
        return self.TYPE

    def is_widget(self) -> bool:
        return self.TYPE == "widget"

    def is_group_like(self) -> bool:
        return self.TYPE in ("group", "checkbox")

    def __repr__(self) -> str:
        return (f"<{type(self).__name__} {self.get_name()!r} "
                f"id={self._item_id} type={self.TYPE!r}"
                f"{' [detached]' if self._detached else ''}>")

    # -- 逻辑父子（平铺层级，不用 setParentItem） -----------------------
    @property
    def parent_id(self) -> int:
        it = self.item()
        return int(it.parent_id or 0) if it is not None else 0

    def parent(self) -> Optional["RuntimeElement"]:
        return self._registry.find(self.parent_id)

    def parentItem(self) -> Optional["RuntimeElement"]:  # noqa: N802 - 旧 API
        return self.parent()

    def children(self) -> list["RuntimeElement"]:
        it = self.item()
        if it is None:
            return []
        out = [self._registry.find(int(cid)) for cid in it.children_ids]
        return [e for e in out if e is not None]

    def childItems(self):  # noqa: N802 - 旧 API
        return self.children()

    def descendants(self) -> list["RuntimeElement"]:
        it = self.item()
        if it is None:
            return []
        return [self._registry.find(int(x.item_id)) for x in
                self._registry.scene.index.descendants(self._item_id)
                if self._registry.find(int(x.item_id)) is not None]

    def is_has_child(self) -> bool:
        it = self.item()
        return bool(it.children_ids) if it is not None else False

    def is_has_parent(self) -> bool:
        return bool(self.parent_id)

    def is_in_group(self) -> bool:
        return self.is_has_parent()

    # -- 可见性（自身标志 + 有效标志，组隐藏递归） ----------------------
    def get_visibility(self) -> bool:
        """自身可见标志，不看祖先（旧 ``base_element`` 口径）。"""
        return self._self_visible

    def effective_visibility(self) -> bool:
        return self._eff_visible

    def set_visibility(self, enable: bool) -> None:
        """设置自身可见，并把有效可见性递归刷到全部后代。

        父不可见时点亮子项会被直接忽略；组隐藏前给直接子项做快照，显示回来
        按快照还原，避免「组隐藏→组显示」把组内原本单独隐藏的成员一起点亮
        （料仓反复切站的真实 bug）。
        """
        enable = bool(enable)
        if self._detached:
            return
        parent = self.parent()
        if enable and parent is not None and not parent.get_visibility():
            return
        children = self.children()
        if not children and self._self_visible == enable:
            return
        if not enable and self._self_visible and children:
            self._visibility_snapshot = {
                child.item_id: child.get_visibility() for child in children}
        self._self_visible = enable
        self._refresh_visible()
        for child in children:
            if enable and child.item_id in self._visibility_snapshot:
                child._restore_self_visible(
                    self._visibility_snapshot[child.item_id])
            else:
                child.set_visibility(enable)
        self.visibilityChanged.emit(enable)

    def _restore_self_visible(self, flag: bool) -> None:
        self._self_visible = bool(flag)
        self._refresh_visible()
        for child in self.children():
            child._restore_self_visible(
                self._visibility_snapshot.get(child.item_id, True))

    def _refresh_visible(self) -> None:
        parent = self.parent()
        parent_eff = True if parent is None else parent.effective_visibility()
        self._eff_visible = self._self_visible and parent_eff
        it = self.item()
        if it is not None:
            it.setVisible(self._eff_visible)
        for child in self.children():
            child._refresh_visible()

    # -- 交互 -----------------------------------------------------------
    def set_interactive(self, enable: bool) -> None:
        self._interactive = bool(enable)

    def is_interactive(self) -> bool:
        return self._interactive

    def set_selectable(self, enable: bool) -> None:
        it = self.item()
        if it is not None:
            it.set_selectable(bool(enable))

    def get_selectable(self) -> bool:
        it = self.item()
        return bool(it.get_selectable()) if it is not None else False

    def has_event_bindings(self) -> bool:
        return self._interactive

    def is_toggle_enabled(self) -> bool:
        return self._interactive and self.TYPE == "checkbox"

    def handle_mouse_press(self) -> None:
        pass

    def handle_mouse_release(self, inside: bool = True) -> None:
        if inside:
            self.clicked.emit()

    def contains_page_pos(self, pos: QPointF) -> bool:
        """page 坐标是否落在图元的旋转后包围盒内。"""
        it = self.item()
        if it is None:
            return False
        return it.page_bounding_rect().contains(QPointF(pos))

    def contains_view_pos(self, pos: QPointF) -> bool:
        """场景坐标（``event.scenePos()``）是否落在该图元上。"""
        it = self.item()
        if it is None:
            return False
        return it.sceneBoundingRect().contains(QPointF(pos))

    def contains_scene_pos(self, pos: QPointF) -> bool:
        """safety 适配层同名接口：收场景坐标。"""
        return self.contains_view_pos(pos)

    # -- 几何（page 坐标） ----------------------------------------------
    def get_scene_center_pos(self) -> QPointF:
        it = self.item()
        return QPointF(*it.page_center()) if it is not None else QPointF()

    def getSize(self) -> QSizeF:  # noqa: N802 - 旧 API
        """未旋转的 page 尺寸；不能用旋转后的 AABB 宽高。"""
        it = self.item()
        if it is None:
            return QSizeF()
        w, h = it._w_scene, it._h_scene
        return QSizeF(w, h)

    def page_size(self) -> QSizeF:
        it = self.item()
        return QSizeF(*it.page_size()) if it is not None else QSizeF()

    def _corner(self, sx: float, sy: float) -> QPointF:
        """按 :class:`GeometryProfile` 取一角。

        analytic 是解析式 ``中心 + R(theta)·(±w/2, ±h/2)``；aabb 是旋转后
        包围盒的角点。旋转过的图元两者差可达几百 page 单位。
        """
        it = self.item()
        if it is None:
            return QPointF()
        profile = self._registry.profile
        if profile.corners == "aabb":
            rect = it.page_bounding_rect()
            return QPointF(rect.right() if sx > 0 else rect.left(),
                           rect.bottom() if sy > 0 else rect.top())
        size = self.getSize()
        theta = math.radians(float(it.page_angle()))
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        hx, hy = sx * size.width() / 2.0, sy * size.height() / 2.0
        cx, cy = it.page_center()
        return QPointF(cx + hx * cos_t - hy * sin_t,
                       cy + hx * sin_t + hy * cos_t)

    def get_scene_topLeft(self) -> QPointF:  # noqa: N802
        return self._corner(-1.0, -1.0)

    def get_scene_topRight(self) -> QPointF:  # noqa: N802
        return self._corner(1.0, -1.0)

    def get_scene_bottomLeft(self) -> QPointF:  # noqa: N802
        return self._corner(-1.0, 1.0)

    def get_scene_bottomRight(self) -> QPointF:  # noqa: N802
        return self._corner(1.0, 1.0)

    def _page_point(self, key: str) -> QPointF:
        """顶点类线段的真实端点（``head_pos`` / ``end_pos`` 记录）。

        几何被拖动改写后记录会陈旧，先按设计器存盘的同一条路径烘焙一次。
        """
        it = self.item()
        if getattr(it, "_geo_dirty", False):
            bake = getattr(it, "_bake_live_geometry", None)
            if callable(bake):
                bake()
        raw = it._page.get(key) or {}
        return QPointF(float(raw.get("x", 0.0)), float(raw.get("y", 0.0)))

    def get_scene_head_pos(self) -> QPointF:
        profile = self._registry.profile
        it = self.item()
        if it is None:
            return QPointF()
        has_record = ("head_pos" in it._page or "end_pos" in it._page)
        if profile.endpoints == "record" and has_record:
            return self._page_point("head_pos")
        # 没有记录时按四角口径回退（_corner 自己处理 analytic / aabb）
        return self._corner(-1.0, -1.0)

    def get_scene_end_pos(self) -> QPointF:
        profile = self._registry.profile
        it = self.item()
        if it is None:
            return QPointF()
        has_record = ("head_pos" in it._page or "end_pos" in it._page)
        if profile.endpoints == "record" and has_record:
            return self._page_point("end_pos")
        return self._corner(1.0, 1.0)

    def sceneBoundingRect(self) -> QRectF:  # noqa: N802 - 旧 API
        """page 坐标 AABB（**不是** Qt 的 sceneBoundingRect）。"""
        it = self.item()
        return it.page_bounding_rect() if it is not None else QRectF()

    def get_angle(self) -> float:
        it = self.item()
        return float(it.page_angle()) if it is not None else 0.0

    def rotate_to_ang(self, angle: float) -> None:
        self.set_page_angle(angle)

    def set_page_angle(self, angle: float) -> None:
        it = self.item()
        if it is not None:
            it.set_page_angle(float(angle))
            self._registry.widget_host.align(self._item_id)

    def set_angle(self, angle: float) -> None:
        """PageDeck 的绝对角度账本：先转角、再把可视中心拉回**转角前**的值。

        ``set_page_angle`` 绕支点转，可视中心会跟着画一段弧；顺序不能反，
        否则纯旋转帧会留下中心漂移（``RuntimeCard._flush_pose`` 同一口径）。
        """
        it = self.item()
        if it is None:
            return
        cx, cy = it.page_center()
        it.set_page_angle(_norm_angle(angle))
        it.set_page_center(cx, cy)
        self._registry.widget_host.align(self._item_id)

    def setRotation(self, delta: float) -> None:  # noqa: N802 - 旧 API
        """PageDeck 紧接着会 set_angle + setPos 给绝对位姿，增量旋转可省。"""
        return None

    def pos(self) -> QPointF:
        """旧 Core 的 ``pos()`` 是 page 场景中心，供 ``setPos(pos()+shift)`` 自洽。"""
        return self.get_scene_center_pos()

    def setPos(self, pos: QPointF) -> None:  # noqa: N802 - 旧 API
        it = self.item()
        if it is not None:
            it.set_page_center(float(pos.x()), float(pos.y()))
            self._registry.widget_host.align(self._item_id)

    def set_page_center(self, x: float, y: float) -> bool:
        it = self.item()
        if it is None:
            return False
        ok = it.set_page_center(float(x), float(y))
        if ok:
            self._registry.widget_host.align(self._item_id)
        return ok

    def change_position(self, pos: QPointF) -> None:
        """把 page 包围盒**左上角**移到 ``pos``（旧 ``change_position`` 语义）。

        平移用 ``item.pos()`` 而不是 ``scenePos()``：自定义支点 + 旋转时两者
        恒差 ``o - R·o``，用 scenePos 当基准会越挪越偏。
        """
        it = self.item()
        if it is None:
            return
        cur = it.page_bounding_rect().topLeft()
        dx = float(pos.x()) - cur.x()
        dy = float(pos.y()) - cur.y()
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return
        delta = QPointF(dx, dy)
        it.setPos(it.pos() + delta)
        self._registry.widget_host.align(self._item_id)

    def change_end_pos(self, pos: QPointF) -> None:
        it = self.item()
        if it is None:
            return
        setter = getattr(it, "set_page_head_end", None)
        if callable(setter):
            setter(self.get_scene_head_pos(), QPointF(pos))
            self._registry.widget_host.align(self._item_id)

    def get_center_pos(self) -> QPointF:
        size = self.page_size()
        return QPointF(size.width() / 2.0, size.height() / 2.0)

    def mapFromScene(self, scene_pos: QPointF) -> QPointF:  # noqa: N802
        """page 场景点 → 图元局部矩形 ``(0,0,w,h)`` 里的点（PageDeck 命中用）。"""
        it = self.item()
        if it is None:
            return QPointF()
        local = it.mapFromScene(QPointF(scene_pos))
        px, py = local.x(), local.y()
        w, h = it.page_size()
        return QPointF(px + w / 2.0, py + h / 2.0)

    def zValue(self):  # noqa: N802 - 旧 API
        it = self.item()
        if it is None:
            return 0
        v = float(it.zValue())
        return int(v) if v.is_integer() else v

    def set_zValue(self, value: float) -> None:  # noqa: N802
        it = self.item()
        if it is not None:
            it.setZValue(float(value))
            self._registry.widget_host.align(self._item_id)

    # -- 外观 / 文本 ----------------------------------------------------
    def get_color(self) -> QColor:
        it = self.item()
        return QColor(it._style.stroke) if it is not None else QColor()

    def set_color(self, color: Any) -> None:
        it = self.item()
        if it is not None:
            it.set_style_value("stroke", _color_text(color))

    def get_fill_color(self) -> QColor:
        it = self.item()
        return QColor(it._style.fill_color) if it is not None else QColor()

    def set_fill_color(self, color: Any) -> None:
        it = self.item()
        if it is not None:
            it.set_style_value("fill_color", _color_text(color))

    def get_fill(self) -> bool:
        it = self.item()
        return bool(it._style.fill) if it is not None else False

    def set_fill(self, state: bool) -> None:
        it = self.item()
        if it is not None:
            it.set_style_value("fill", bool(state))

    def get_fill_style(self) -> str:
        """填充样式字符串（``solid`` / ``bdiag`` / ``none`` …），缺字段兜底 solid。"""
        it = self.item()
        return (normalize_brush_style(it._style.fill_style)
                if it is not None else FILL_STYLE_DEFAULT)

    def set_fill_style(self, style: Any) -> None:
        """运行态切换填充样式；未知值归一到 solid，不往 JSON 写垃圾键。"""
        it = self.item()
        if it is not None:
            it.set_style_value("fill_style", normalize_brush_style(style))

    def get_text_align(self) -> str:
        """文本水平对齐（left / center / right），缺字段兜底 center。"""
        it = self.item()
        return (normalize_text_align(it._style.text_align)
                if it is not None else TEXT_ALIGN_DEFAULT)

    def set_text_align(self, align: Any) -> None:
        """运行态切换文本对齐；未知值归一到 center。"""
        it = self.item()
        if it is not None:
            it.set_style_value("text_align", normalize_text_align(align))

    @property
    def context(self) -> str:
        it = self.item()
        return str(getattr(it, "context", "") or "") if it is not None else ""

    @context.setter
    def context(self, value: Any) -> None:
        it = self.item()
        if it is not None:
            it.set_page_field("context", "" if value is None else str(value))

    # -- 变量绑定：运行态显示写入（不污染设计数据） --------------------
    def apply_binding(self, field: str, value: Any, apply: str) -> bool:
        """把 tag 值写进**实时显示字段**，不写 ``_page``、不置脏、不进 undo。

        这是「设计态绑定 / 运行态单向读」的落点：设计数据（``_page``）只在
        设计器里由属性面板修改，运行态刷新一律走这里直接刷 Qt 可见状态，
        因此运行一段时间后 ``page_data()`` / JSON 仍与保存时逐字段一致。

        支持的属性见 :data:`g_binding.BINDABLE_PROPERTIES` 中 ``target ==
        'element'`` 的项；widget 图元的 ``widgetText`` / ``widgetValue`` 是
        ``target == 'control'``，由 :class:`~.stage.RuntimeStage` 走
        ``bind_control`` 写到真实 QWidget，不经过这里。

        返回是否命中并写入了某个显示字段。
        """
        spec = BY_KEY.get(str(field))
        if spec is None or spec.target != "element":
            return False
        it = self.item()
        if it is None:
            return False
        v = _coerce(value, apply)
        key = str(field)
        if key == "visible":
            # 走门面的可见性（含组级联 / 有效可见性），只 setVisible，不写 page
            self.set_visibility(bool(v))
            return True
        if key == "context":
            it.context = "" if v is None else str(v)
        elif key == "checked":
            it.checked = bool(v)
        elif key == "stroke":
            it._style.stroke = _parse_color(v)
        elif key == "fill_color":
            it._style.fill_color = _parse_color(v)
        elif key == "fill":
            it._style.fill = bool(v)
        elif key == "opacity":
            op = max(0, min(255, int(v)))
            it._style.opacity = op
            it._style.stroke.setAlpha(op)
            it._style.fill_color.setAlpha(op)
        elif key == "strokeWidth":
            it._style.stroke_width = max(0.0, float(v))
        elif key == "cornerRadius":
            it._style.corner_radius = max(0.0, float(v))
        elif key == "font_size":
            it._style.font_size = max(0.0, float(v))
        else:
            return False
        it.update()
        return True

    # -- widget 门面（委托给 WidgetHost，普通图元调用是安全的 no-op） ----
    def set_widget_factory(self, factory: Callable) -> None:
        """PopPick 口径：给这个 widget 图元指定 ``factory(host) -> QWidget``。"""
        host = self._registry.widget_host
        host.set_factory(self._item_id, factory)

    def widget_control(self):
        return self._registry.widget_host.control_of(self._item_id)

    def has_widget_layer(self) -> bool:
        return self._registry.widget_host.has_proxy(self._item_id)

    def set_widget_readonly(self, readonly: bool) -> None:
        self._readonly = bool(readonly)
        self._registry.widget_host.set_readonly(self._item_id, self._readonly)

    def widget_readonly(self) -> bool:
        return self._readonly

    def set_motion_cache(self, active: bool) -> None:
        """兼容钩子：**本模板不含位图快照缓存**，只记账不切位图。

        PopPick 的 ``HmiPagesHost.apply_static_pages`` 会调用它；接入本模板后
        调用不报错，但后台页仍是真实控件。需要静态位图优化时请在业务侧挂
        一个 ``SnapshotPolicy``（见设计文档「未覆盖能力」）。
        """
        self._motion_cache = bool(active)

    def is_motion_cache(self) -> bool:
        return self._motion_cache

    def set_widget_fast_paint(self, active: bool) -> None:
        """兼容钩子：动画期的批量位图化，本模板不实现。"""
        self._motion_cache = bool(active)

    def widget_pixel_size(self) -> QSizeF:
        it = self.item()
        return QSizeF(it.boundingRect().width(),
                      it.boundingRect().height()) if it is not None else QSizeF()

    def fit_widget_size(self, size) -> None:
        """按目标**像素**尺寸校正图元尺寸，不改位姿（PopPick 页面统一观感用）。"""
        it = self.item()
        if it is None:
            return
        if isinstance(size, (tuple, list)):
            w, h = float(size[0]), float(size[1])
        else:
            w = float(size.width())
            h = float(size.height())
        pw, ph = w, h
        it.set_page_size(pw, ph)
        self._registry.widget_host.align(self._item_id)

    def sync_widget_geometry(self) -> None:
        self._registry.widget_host.align(self._item_id)

    def update_boundingRect(self) -> None:  # noqa: N802 - 旧 API
        self.sync_widget_geometry()

    def raise_widget_view(self) -> None:
        self.sync_widget_geometry()


class _NullWidgetHost:
    """registry 独立使用（没挂到 RuntimeStage）时的空承载层。

    这样 ``RuntimeElement`` 的几何 / 控件接口在任何装配下都能安全调用，
    不会出现 ``NoneType has no attribute align``。
    """

    def align(self, _iid) -> None:
        return None

    def align_all(self) -> None:
        return None

    def set_factory(self, _iid, _factory) -> None:
        return None

    def control_of(self, _key):
        return None

    def has_proxy(self, _iid) -> bool:
        return False

    def set_readonly(self, _iid, _value) -> None:
        return None


class RuntimeRegistry(QObject):
    """图元门面的唯一真值索引；自动跟随场景结构变化重建。

    连接 ``GraphicsScene.structureChanged`` 后，``load_page`` / ``restore`` /
    增删图元都会自动 :meth:`rebuild`，业务不需要再手写
    ``SceneManager.rebuild()`` —— 这正是 rack 的 ``reload()`` 与 D-3 的痛点。
    """

    aboutToRebuild = Signal()
    structureChanged = Signal()
    elementsChanged = Signal(object)       # list[int]

    def __init__(self, scene, stage=None, *, profile=None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent or scene)
        self.scene = scene
        self.stage = stage
        if isinstance(profile, str):
            profile = GEOMETRY_PROFILES.get(profile)
            if profile is None:
                raise ValueError(f"未知几何口径 {profile!r}，"
                                 f"可选 {sorted(GEOMETRY_PROFILES)}")
        self.profile = profile or STRICT_PROFILE
        self.by_id: dict[int, RuntimeElement] = {}
        self.by_name: dict[str, int] = {}
        self._draw_order: list[int] = []
        self.generation = 0
        self._bound: list[tuple[Any, Any]] = []
        self.rebuild()
        self._connect_scene()

    @property
    def widget_host(self):
        """当前 widget 承载层；没接 stage 时返回空实现。"""
        stage = self.stage
        if stage is None or getattr(stage, "widgets", None) is None:
            if getattr(self, "_null_host", None) is None:
                self._null_host = _NullWidgetHost()
            return self._null_host
        return stage.widgets

    # -- 场景信号 -------------------------------------------------------
    def _connect_scene(self) -> None:
        sig = getattr(self.scene, "structureChanged", None)
        if sig is not None:
            sig.connect(self.rebuild)
            self._bound.append((sig, self.rebuild))
        sig = getattr(self.scene, "itemChanged", None)
        if sig is not None:
            sig.connect(self.elementsChanged.emit)
            self._bound.append((sig, self.elementsChanged.emit))

    def disconnect_scene(self) -> None:
        for sig, slot in self._bound:
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._bound.clear()

    # -- 重建 -----------------------------------------------------------
    def rebuild(self, *, reset_visibility: bool = True) -> None:
        """按当前页面重建索引；复用仍在的门面对象以保住信号连接。"""
        self.aboutToRebuild.emit()
        self.generation += 1
        old = self.by_id
        scene = self.scene
        items = list(scene.all_items()) if scene is not None else []
        order = {iid: n for n, iid in enumerate(scene.index.order)}
        fresh: dict[int, RuntimeElement] = {}
        for it in items:
            iid = int(it.item_id)
            element = old.get(iid)
            if element is None:
                element = RuntimeElement(iid, self)
            element._adopt(it, reset_visibility=reset_visibility)
            fresh[iid] = element
        for iid, element in old.items():
            if iid not in fresh:
                element._detach()
        self.by_id = fresh
        self._draw_order = sorted(
            fresh, key=lambda iid: (float(scene.find_item(iid).zValue()),
                                    order.get(iid, 0)))
        self.reindex_names()
        # 平铺层级下组隐藏不会自动带到子项，从每棵树的根往下刷有效可见性
        for iid in self._draw_order:
            if not self.by_id[iid].parent_id:
                self.by_id[iid]._refresh_visible()
        self.structureChanged.emit()

    def reindex_names(self) -> None:
        names: dict[str, int] = {}
        for element in self.all():
            name = element.get_name()
            if name and name not in names:      # 重名保留第一个，与旧口径一致
                names[name] = element.item_id
        self.by_name = names

    # -- 查询 -----------------------------------------------------------
    def find(self, key) -> Optional[RuntimeElement]:
        if isinstance(key, RuntimeElement):
            return key
        if isinstance(key, int):
            return self.by_id.get(key)
        if isinstance(key, str):
            iid = self.by_name.get(key)
            return self.by_id.get(iid) if iid is not None else None
        iid = getattr(key, "item_id", None) or getattr(key, "id", None)
        return self.by_id.get(int(iid)) if iid is not None else None

    def findItemByName(self, name: str):  # noqa: N802 - 旧 API
        return self.find(name)

    def findItem(self, item_id: int):  # noqa: N802 - 旧 API
        return self.find(int(item_id))

    def adapter_of(self, item_id: int):
        return self.find(int(item_id))

    def parent_adapter(self, key):
        element = self.find(key)
        return element.parent() if element is not None else None

    def all(self) -> list[RuntimeElement]:
        return list(self.by_id.values())

    def all_items(self) -> list[RuntimeElement]:
        return self.all()

    def sorted(self) -> list[RuntimeElement]:
        """按 z + JSON 顺序稳定排序（绘制 / 命中口径）。"""
        return [self.by_id[iid] for iid in self._draw_order]

    def widgets(self) -> list[RuntimeElement]:
        return [e for e in self.sorted() if e.is_widget()]

    def __len__(self) -> int:
        return len(self.by_id)

    def __iter__(self):
        return iter(self.all())

    # -- 兼容门面 -------------------------------------------------------
    def legacy_manager(self, *, only_widgets: bool = False, m_scene=None):
        """生成旧 ``SceneManager`` 形状的对象，让既有 model 零改动接入。

        ``only_widgets=True`` 对应 PopPick 的 ``RuntimeSceneManager``（只暴露
        widget 卡片）；默认对应 rack / safety 的 ``SceneManager``。
        """
        return LegacyManager(self, only_widgets=only_widgets, m_scene=m_scene)


class LegacyManager(QObject):
    """旧 ``SceneManager`` 的只读门面（属性每次向 registry 现取）。

    rack 的 4 个 model 只用到 ``findItemByName`` / ``m_items`` /
    ``m_name_items`` / ``m_sorted_items`` / ``rebuild``；PopPick 的
    ``PageDeck`` / ``HmiPagesHost`` 用到 ``m_sorted_items`` / ``all_items`` /
    ``findItemByName`` / ``m_scene``。这里全部覆盖。
    """

    def __init__(self, registry: RuntimeRegistry, *, only_widgets: bool = False,
                 m_scene=None) -> None:
        super().__init__(registry)
        self._registry = registry
        self.only_widgets = only_widgets
        self.m_scene = m_scene if m_scene is not None else registry.scene

    def _scope(self) -> list[RuntimeElement]:
        return (self._registry.widgets() if self.only_widgets
                else self._registry.sorted())

    @property
    def m_items(self) -> dict[int, RuntimeElement]:
        if self.only_widgets:
            return {e.item_id: e for e in self._registry.widgets()}
        return dict(self._registry.by_id)

    @property
    def m_name_items(self) -> dict[str, int]:
        if not self.only_widgets:
            return dict(self._registry.by_name)
        return {e.get_name(): e.item_id for e in self._registry.widgets()
                if e.get_name()}

    @property
    def m_sorted_items(self) -> list[RuntimeElement]:
        return self._scope()

    def findItemByName(self, name: str):  # noqa: N802
        found = self._registry.find(name)
        if found is None or (self.only_widgets and not found.is_widget()):
            return None
        return found

    def findItem(self, item_id: int):  # noqa: N802
        found = self._registry.find(int(item_id))
        if found is None or (self.only_widgets and not found.is_widget()):
            return None
        return found

    def all_items(self) -> list[RuntimeElement]:
        return self._scope()

    def adapter_of(self, item_id: int):
        return self.findItem(item_id)

    def parent_adapter(self, key):
        return self._registry.parent_adapter(key)

    def rebuild(self) -> None:
        self._registry.rebuild()

    def __len__(self) -> int:
        return len(self._scope())
