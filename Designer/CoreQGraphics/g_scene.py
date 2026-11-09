"""QGraphicsScene 场景层 + 场景索引 + page JSON 读写。

对应 ``Designer/Core/myGraphicsScene.py`` / ``myQuadTreeScene.py`` 的
``SceneManager`` / ``SceneSerializer``。关键约定（来自代码事实）：

* JSON 的 ``sceneRect`` 是**上次保存时的可见视图范围**，注释明确写了
  「must not be passed to setSceneRect()」，所以只用 ``set_view_scene_rect``
  保存，场景边界用硬编码的世界矩形。
* ``parent_id`` 驱动逻辑关系；``children_ids`` / ``group_id`` 在加载时
  **完全不参与连接**（旧实现只写不读）。
* 1411 个图元 zValue 重复，靠 JSON 数组顺序稳定定层级 —— 因此所有 item
  在 Qt 层**平铺**，绝不用 ``setParentItem``（父的 z 会把整组拉到一起）。
* 保存时未编辑的 item 直接回写原始 dict 深拷贝，做到格式零改动。
"""

from __future__ import annotations

import copy
import json
import math
import os

from PySide6.QtCore import QPointF, QRectF, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsProxyWidget, QGraphicsScene,
)

from .g_element import BaseItem, rotate_xy
from .g_elements import ITEM_TYPES
from .g_projection import SceneProjection
from .g_widgets import (
    WIDGET_DEFAULTS, WIDGET_VARIANT_LABELS, create_control, normalize_variant,
    widget_style_sheet, widget_text, widget_variant,
)

WORLD_RECT = QRectF(-100000, -100000, 200000, 200000)
DEFAULT_BACKGROUND = "#bee1f59b"

# 正交模式（F8）作用的图元：逐点落子的「点列」类。rect / circle 是两点定框的
# 对角定义，锁轴反而画不出矩形，保持原行为。视图层与场景层共用这一份表。
ORTHO_DRAW_TYPES = frozenset(("line", "triangle", "polygon", "path"))


def _template_int(value):
    """模板文件可能是手工编辑的，id 字段一律容错解析。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _template_point(value):
    if not isinstance(value, dict):
        return None
    try:
        return float(value["x"]), float(value["y"])
    except (KeyError, TypeError, ValueError):
        return None

# 新建图元的默认外观与尺寸（场景单位，与 Core 的 element_factory 口径一致）
DEFAULT_STYLE = {
    "stroke": "#000000", "strokeWidth": 2, "fill": True,
    "fill_color": "#919191", "opacity": 255, "cornerRadius": 0.0,
    "font_size": 10,
}
DEFAULT_SIZES: dict[str, tuple[float, float]] = {
    "rect": (400.0, 240.0), "circle": (240.0, 240.0),
    "text": (400.0, 120.0), "image": (320.0, 240.0),
    "checkbox": (120.0, 120.0), "widget": (400.0, 200.0),
    "group": (600.0, 400.0), "line": (400.0, 240.0),
    "triangle": (300.0, 260.0), "polygon": (320.0, 260.0),
    "path": (320.0, 260.0),
}
TYPE_LABELS: dict[str, str] = {
    "rect": "矩形", "circle": "圆", "text": "文本", "image": "图片",
    "checkbox": "复选框", "widget": "控件", "group": "组", "line": "直线",
    "triangle": "三角形", "polygon": "多边形", "path": "路径",
}
# 工具箱里 7 个 widget 变体共用 ``widget:<key>`` 形式的伪类型；真正的
# ``type`` 仍写 ``widget``，变体只落在顶层 ``widgetType`` 字段（旧 Core 口径）。
WIDGET_TOOL_KEYS: tuple[str, ...] = tuple(
    f"widget:{key}" for key in WIDGET_VARIANT_LABELS
)
WIDGET_TOOL_LABELS: dict[str, str] = {
    f"widget:{key}": f"控件·{label}"
    for key, label in WIDGET_VARIANT_LABELS.items()
}


class SceneIndex:
    """id / 逻辑父子 / JSON 顺序的索引，不参与 Qt 层级。"""

    def __init__(self) -> None:
        self.by_id: dict[int, BaseItem] = {}
        self.order: list[int] = []
        self.parent_of: dict[int, int] = {}
        self.children_of: dict[int, list[int]] = {}
        self._next_id = 1

    def register(self, item: BaseItem) -> None:
        iid = item.item_id
        self.by_id[iid] = item
        self.order.append(iid)
        self.parent_of[iid] = item.parent_id
        self.children_of.setdefault(iid, [])
        if item.parent_id and item.parent_id in self.children_of:
            self.children_of[item.parent_id].append(iid)
        self._next_id = max(self._next_id, iid + 1)

    def rebuild_links(self) -> None:
        self.children_of = {iid: [] for iid in self.by_id}
        for iid, item in self.by_id.items():
            self.parent_of[iid] = item.parent_id
            pid = item.parent_id
            if pid in self.children_of:
                self.children_of[pid].append(iid)

    def descendants(self, iid: int) -> list[BaseItem]:
        out: list[BaseItem] = []
        stack = list(self.children_of.get(iid, []))
        while stack:
            cid = stack.pop()
            child = self.by_id.get(cid)
            if child is not None:
                out.append(child)
                stack.extend(self.children_of.get(cid, []))
        return out

    def sorted_items(self) -> list[BaseItem]:
        """与旧 ``sort_items_by_zValue`` 一致：稳定排序，同值按 JSON 顺序。"""
        seq = [self.by_id[i] for i in self.order if i in self.by_id]
        return sorted(seq, key=lambda it: it.zValue())

    def allocate_id(self) -> int:
        iid = self._next_id
        self._next_id += 1
        return iid


class GraphicsScene(QGraphicsScene):
    """CoreQGraphics 的场景对象。"""

    # UI 外壳用：结构变化 / 属性变化 / 脏状态
    contentChanged = Signal()
    geometryChanged = Signal(object)
    drawFinished = Signal(object)        # 一次手动绘制完成，携带新图元
    drawCancelled = Signal()             # 取消进行中的绘制

    def __init__(self, projection: SceneProjection | None = None, parent=None) -> None:
        super().__init__(parent)
        self.projection = projection or SceneProjection()
        self.index = SceneIndex()
        self.is_run_mode = False
        self._page_path = ""
        self._header: dict = {}
        self._background_override: QColor | None = None
        self._last_pose: dict[int, tuple[float, float, float]] = {}
        self._syncing = False
        self._modified = False
        # 剪贴板存的是「(原 id, page 记录)」快照，粘贴时统一重发 id 与父子关系
        self._clipboard: list[tuple[int, dict]] = []
        self._paste_count = 0
        # 组缩放链路重入保护：apply_scale_about 会回到 GroupItem.set_page_size，
        # 不能再委托一次「默认锚点」的 resize_group，否则整棵子树被缩放两遍。
        self._resizing_group = False
        # 运行预览：为 widget 变体挂真实 Qt 控件（独立顶层 proxy，不进索引、
        # 不参与 page JSON，也不影响设计态的对拍 / round-trip）。
        self._widget_layer_on = False
        self._widget_proxies: dict[int, QGraphicsProxyWidget] = {}
        # 手动绘制控制器（CAD 式分点落点）
        self._draw_item: BaseItem | None = None
        self._draw_type = ""
        self._draw_polygon = False
        # 可拖动开关：默认 False（左键拖动已取消，移动走双击跟手）；
        # 仅外部脚本显式 set_movable_gate(True) 时才让图元带 ItemIsMovable
        self._movable_gate = False
        self.setSceneRect(WORLD_RECT)
        self.setItemIndexMethod(QGraphicsScene.BspTreeIndex)
        self.setBackgroundBrush(QBrush(QColor(DEFAULT_BACKGROUND)))
        # 运行预览下，属性面板 / 批量变换改了图元的位姿或尺寸后要立刻重排
        # 真实控件；控件内容本身是否重建仍由 _sync_widget_proxies 按签名判断。
        self.geometryChanged.connect(self._on_geometry_changed)

    # ------------------------------------------------------------------
    # 加载 / 保存
    # ------------------------------------------------------------------
    def load_page(self, path: str) -> int:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._page_path = path
        return self.load_data(data)

    def load_data(self, data: dict) -> int:
        """从内存 dict 装载（撤销栈 / 单测用），不改动 ``_page_path``。"""
        self.clear_page()
        self._header = {k: copy.deepcopy(v) for k, v in data.items() if k != "items"}
        bg = data.get("backgroundColor")
        if isinstance(bg, str) and bg.strip():
            color = QColor(bg.strip())
            if color.isValid():
                self.setBackgroundBrush(QBrush(color))
        view_rect = data.get("sceneRect") or {}
        candidate = QRectF(
            float(view_rect.get("x", 0.0)), float(view_rect.get("y", 0.0)),
            float(view_rect.get("width", 0.0)), float(view_rect.get("height", 0.0)),
        )
        if candidate.width() > 0 and candidate.height() > 0:
            self.set_view_scene_rect(candidate)
        # 旧实现：先建全部对象，最后统一连父子；这里索引在 register 时同步建链
        for record in data.get("items", []):
            cls = ITEM_TYPES.get(record.get("type"))
            if cls is None:
                continue
            item = cls(record, self.projection)
            self.addItem(item)            # 顺序即 JSON 顺序，同 z 定层级
            self.index.register(item)
            self._last_pose[item.item_id] = item.live_page_pose()[:3]
        # JSON 里子是 id 升序、父常在后面，注册时父可能还不在索引里；
        # 与旧实现一样「先建全部对象，最后统一连父子」。
        self.index.rebuild_links()
        return len(self.index.order)

    def save_page(self, path: str | None = None) -> dict:
        target = path or self._page_path
        if not target:
            raise ValueError("save_page() 需要显式路径或先 load_page()")
        header = self.page_data()
        out_dir = os.path.dirname(os.path.abspath(target))
        os.makedirs(out_dir, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(header, f, ensure_ascii=False, indent=4)
        for item in self.index.by_id.values():
            item.mark_clean()
        self.mark_saved()
        return header

    def page_data(self) -> dict:
        """当前场景的完整 page 数据（内存快照，不落盘、不改脏标记）。"""
        header = copy.deepcopy(self._header)
        if self._background_override is not None:
            header["backgroundColor"] = self._background_override.name(QColor.HexArgb)
        if "sceneRect" not in header:
            header["sceneRect"] = {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
        header["items"] = [
            self.index.by_id[iid].to_page_record()
            for iid in self.index.order if iid in self.index.by_id
        ]
        return header

    def clear_page(self) -> None:
        # proxy 与其承载的 QWidget 由 scene.clear() 一并销毁；先断掉 Python 侧
        # 引用，避免留下指向已析构 C++ 对象的 wrapper。
        self._widget_proxies.clear()
        self._widget_layer_on = False
        self.clear()
        self.index = SceneIndex()
        self._last_pose.clear()

    def set_view_scene_rect(self, rect: QRectF) -> None:
        """保存「上次可见视图范围」，只写进 header，不调用 setSceneRect。"""
        self._header["sceneRect"] = {
            "x": rect.x(), "y": rect.y(),
            "width": rect.width(), "height": rect.height(),
        }

    def view_scene_rect(self) -> QRectF:
        r = self._header.get("sceneRect") or {}
        return QRectF(
            float(r.get("x", 0.0)), float(r.get("y", 0.0)),
            float(r.get("width", 0.0)), float(r.get("height", 0.0)),
        )

    def set_background(self, color: QColor) -> None:
        self._background_override = QColor(color)
        self.setBackgroundBrush(QBrush(QColor(color)))

    # ------------------------------------------------------------------
    # 查询 / 逻辑分组
    # ------------------------------------------------------------------
    def find_item(self, iid: int) -> BaseItem | None:
        return self.index.by_id.get(int(iid))

    def sorted_items(self) -> list[BaseItem]:
        return self.index.sorted_items()

    def selected_items(self) -> list[BaseItem]:
        return [it for it in self.selectedItems() if isinstance(it, BaseItem)]

    def on_item_moved(self, item: BaseItem) -> None:
        """父对象位姿传播：把父的刚体运动（平移 + 旋转 + 支点）施加给所有后代。

        只用「可视中心 + 角度」描述刚体运动：中心从 C 走到 C'、角度转了 dA，
        刚体上的任意点满足 ``p' = R(dA)·(p - C) + C'``。支点也按此映射，
        所以父对象换支点（中心不动）不会被误当成平移——那种情况 dA、C 都没变，
        自然不产生任何位移。

        顶点类图元把旋转烘焙进顶点（见 ``_PointBasedItem.apply_rigid_pose``），
        矩形类走 ``_apply_pose`` 直接改 Qt 变换。
        """
        cx, cy, angle, _ox, _oy = item.live_page_pose()
        last = self._last_pose.get(item.item_id)
        self._last_pose[item.item_id] = (cx, cy, angle)
        if (self._syncing or last is None
                or getattr(item, "_suppress_propagate", False)):
            return
        dx, dy, da = cx - last[0], cy - last[1], angle - last[2]
        if abs(dx) < 1e-9 and abs(dy) < 1e-9 and abs(da) < 1e-12:
            return
        if abs(da) < 1e-12 and not getattr(item, "_suppress_geo", False):
            # 纯平移时图元自己记的支点要跟着走；旋转时支点不动、只有中心在动，
            # 所以不能在这里平移支点。
            item.shift_origin_by(dx, dy)
            # 拖拽只改 Qt 变换、不经过 notify_edit，这里至少标脏：否则关窗时
            # 不会提示保存，拖了半天最后一关窗全丢了。
            self._modified = True
        self._syncing = True
        try:
            for child in self.index.descendants(item.item_id):
                child.apply_rigid_pose(last[0], last[1], da, dx, dy)
        finally:
            self._syncing = False
        # 运行预览里父对象刚体带动子图元时，控件也要跟着走（拖动被运行门控
        # 禁用，这里主要覆盖脚本 / 外部位姿绑定）。
        if self._widget_layer_on:
            self.align_widget_proxies()

    def group_selected(self) -> BaseItem | None:
        """建立逻辑分组，并创建一个 group 类型图元作为组框。"""
        selected = self.selected_items()
        if len(selected) < 2:
            return None
        union = QRectF()
        for it in selected:
            union = union.united(it.sceneBoundingRect())
        p = self.projection
        cx, cy = p.inverse_point(union.center().x(), union.center().y())
        w, h = p.inverse_size(union.width(), union.height())
        iid = self.index.allocate_id()
        record = {
            "id": iid, "name": f"group_{iid}", "type": "group",
            "parent_id": 0, "children_ids": [it.item_id for it in selected],
            "group_id": 0,
            "center_pos": {"x": round(cx, 3), "y": round(cy, 3)},
            "origin_pos": {"x": round(cx, 3), "y": round(cy, 3)},
            "width": w, "height": h, "rotate": 0.0,
            "style": {
                "stroke": "#000000", "strokeWidth": 2, "fill": False,
                "fill_color": "#00ff00", "opacity": 255, "cornerRadius": 0.0,
            },
            "zValue": max(it.zValue() for it in selected) + 1.0,
        }
        group = ITEM_TYPES["group"](record, p)
        self.addItem(group)
        self.index.register(group)
        self._last_pose[iid] = group.live_page_pose()[:3]
        for it in selected:
            # 必须写回 _page：复制快照与存盘都读 page 记录，只改运行时属性
            # 会让成组关系在复制 / 重新打开后丢失。
            it.set_page_field("parent_id", iid)
            it.set_page_field("group_id", iid)
        self.index.rebuild_links()
        # 旧 Core group_element.initialize() -> apply_member_name_prefix()：
        # 成员名带上 <组名>_ 前缀，嵌套组逐层累加，图层树才能看出层级。
        self.replace_name_prefix(
            [c.item_id for c in self.index.descendants(iid)],
            "", f"{group.get_name()}_", self.names_in_use())
        self.refresh_movable()   # 成员挂上父对象后不再可单独拖动
        return group

    def ungroup_selected(self) -> int:
        count = 0
        removed: list[int] = []
        for group in [it for it in self.selected_items() if it.TYPE == "group"]:
            children = self.index.descendants(group.item_id)
            # 解组前剥掉一层组名前缀（旧 Core free_group 的语义），
            # 名字冲突时 replace_name_prefix 会自动退回默认命名。
            used = self.names_in_use()
            used.discard(group.get_name())
            self.replace_name_prefix(
                [c.item_id for c in children],
                f"{group.get_name()}_", "", used)
            for child in children:
                child.set_page_field("parent_id", 0)
                child.set_page_field("group_id", 0)
                count += 1
            removed.append(group.item_id)
            self.removeItem(group)
            self.index.by_id.pop(group.item_id, None)
            if group.item_id in self.index.order:
                self.index.order.remove(group.item_id)
        for it in self.all_items():
            cids = it.page_record().get("children_ids") or []
            if any(cid in removed for cid in cids):
                it.set_page_field("children_ids",
                                  [c for c in cids if c not in removed])
        self.index.rebuild_links()
        self.refresh_movable()   # 解组后成员重新可独立拖动
        if removed:
            self.mark_modified()
        return count

    # ------------------------------------------------------------------
    # 吸附点 / 视图
    # ------------------------------------------------------------------
    def snap_points(self) -> tuple[list[QPointF], list[QPointF]]:
        ends, mids, _owners = self.snap_points_with_owners()
        return ends, mids

    def snap_points_with_owners(
            self) -> tuple[list[QPointF], list[QPointF], list[int]]:
        """端点 / 中点，外加每个点所属图元的 id。

        ``owners`` 与 ``ends + mids`` **同序**（先全部端点、再全部中点），
        ``SnapSystem.update_points`` 按这个顺序把归属挂到坐标上，供视图按 T
        抓起「这个捕捉点来自的图元」。老调用点继续用 ``snap_points()``。
        """
        ends: list[QPointF] = []
        mids: list[QPointF] = []
        end_owners: list[int] = []
        mid_owners: list[int] = []
        for it in self.index.by_id.values():
            if not it.isVisible():
                continue
            e, m = it.snap_points()
            ends.extend(e)
            mids.extend(m)
            end_owners.extend([it.item_id] * len(e))
            mid_owners.extend([it.item_id] * len(m))
        return ends, mids, end_owners + mid_owners

    def fit_rect(self, margin: float = 40.0) -> QRectF:
        """所有图元的可见包围盒（视图坐标），供 QGraphicsView.fitInView。"""
        rect = QRectF()
        for it in self.index.by_id.values():
            rect = rect.united(it.sceneBoundingRect())
        if rect.isEmpty():
            return QRectF(-500, -500, 1000, 1000)
        return rect.adjusted(-margin, -margin, margin, margin)

    # ==================================================================
    # UI 外壳：编辑命令门面
    # ==================================================================
    def all_items(self) -> list[BaseItem]:
        return list(self.index.by_id.values())

    def is_modified(self) -> bool:
        return self._modified

    def mark_modified(self) -> None:
        self._modified = True

    def mark_saved(self) -> None:
        self._modified = False

    def notify_edit(self, item: BaseItem | None = None) -> None:
        """属性面板改完字段后调用：标脏 + 广播几何/外观刷新。"""
        self.mark_modified()
        self.geometryChanged.emit(item)
        self.contentChanged.emit()
        # 改了 widgetType / widgetText / 样式时，运行预览里的真实控件要重建
        if self._widget_layer_on:
            self._sync_widget_proxies()

    def snapshot(self) -> dict:
        return self.page_data()

    def restore(self, data: dict) -> None:
        """从快照重建（撤销/重做）。保留当前文件路径与脏状态。"""
        was_modified = self._modified
        run = self._widget_layer_on
        self.load_data(data)
        self._modified = was_modified
        self._widget_layer_on = run
        if run:
            self._sync_widget_proxies()
        self.contentChanged.emit()

    def set_scene_mode(self, run: bool) -> None:
        self.is_run_mode = bool(run)
        self._widget_layer_on = bool(run)
        self.clearSelection()
        for it in self.all_items():
            it.set_selectable(not run)
            it.setFlag(QGraphicsItem.ItemIsMovable,
                       (not run) and self._movable_gate and not it.parent_id)
        self._sync_widget_proxies()
        self.update()

    # ------------------------------------------------------------------
    # 运行预览：widget 变体的真实 Qt 控件（对照旧 Core EmbeddedWidgetLayer）
    # ------------------------------------------------------------------
    def _sync_widget_proxies(self) -> None:
        """运行态为每个可见 widget 挂一个独立顶层的 ``QGraphicsProxyWidget``。

        关键取舍：proxy **不做图元的 Qt 子项**（``setParentItem`` 会把
        ``sceneBoundingRect`` 撑大，破坏 page_1 逐图元对拍），也不注册进
        ``SceneIndex``（``all_items`` / ``page_data`` 都不受影响）。它按图元
        的局部原点 + 旋转 + view 尺寸手工对齐，设计态完全不创建。
        """
        wanted: dict[int, BaseItem] = {}
        if self._widget_layer_on:
            for it in self.all_items():
                if it.TYPE == "widget" and it.get_visibility():
                    wanted[it.item_id] = it
        for iid, proxy in list(self._widget_proxies.items()):
            if iid in wanted:
                continue
            self.removeItem(proxy)
            old = proxy.widget()
            proxy.setWidget(None)
            if old is not None:
                old.deleteLater()
            del self._widget_proxies[iid]
        for iid, it in wanted.items():
            proxy = self._widget_proxies.get(iid)
            if proxy is None:
                proxy = QGraphicsProxyWidget()
                proxy.setFlag(QGraphicsItem.ItemIsSelectable, False)
                proxy.setFlag(QGraphicsItem.ItemIsMovable, False)
                self.addItem(proxy)
                self._widget_proxies[iid] = proxy
            sig = (widget_variant(it._page), widget_text(it._page),
                   widget_style_sheet(it._page))
            if getattr(proxy, "_wg_sig", None) != sig:
                old = proxy.widget()
                proxy.setWidget(create_control(it._page))
                if old is not None:
                    old.deleteLater()
                proxy._wg_sig = sig
            self._align_widget_proxy(proxy, it)

    @staticmethod
    def _align_widget_proxy(proxy: QGraphicsProxyWidget, it: BaseItem) -> None:
        """把真实控件精确盖到图元矩形上（含旋转 / 自定义支点 / AGV）。

        ``QGraphicsWidget.setGeometry()`` 会**同步改写 pos**：旧写法先
        ``setGeometry(-w/2,-h/2,w,h)`` 再 ``setPos(center)``，实际把控件
        左上角挪到了图元中心（整体偏 +w/2,+h/2），而且 rotation 默认绕
        本地 (0,0)（控件左上角）转，与图元绕可视中心转又差一次。

        正确口径：控件本地矩形恒为 (0,0,w,h)，用 ``resize`` 只改尺寸，
        把变换原点钉到控件中心 (w/2,h/2)，令 ``pos = C - (w/2,h/2)``——
        此时 ``scene(center) = pos + o = C``（o 为变换原点），四角与图元
        的 ``(-w/2,-h/2,w,h)`` 经 R(θ) 后逐点重合。
        """
        w, h = it._w_view, it._h_view
        geo = proxy.geometry()
        if abs(geo.width() - w) > 1e-6 or abs(geo.height() - h) > 1e-6:
            proxy.resize(w, h)
        proxy.setTransformOriginPoint(QPointF(w / 2.0, h / 2.0))
        center = it.mapToScene(QPointF(0.0, 0.0))
        proxy.setPos(center - QPointF(w / 2.0, h / 2.0))
        proxy.setRotation(it.rotation())
        proxy.setZValue(it.zValue() + 0.5)
        proxy.setVisible(True)

    def align_widget_proxies(self) -> None:
        """图元几何变化后只重排已有 proxy，不重建 / 不销毁 QWidget。"""
        if not self._widget_layer_on:
            return
        for iid, proxy in self._widget_proxies.items():
            it = self.index.by_id.get(iid)
            if it is not None:
                self._align_widget_proxy(proxy, it)

    def _on_geometry_changed(self, _item) -> None:
        self.align_widget_proxies()

    @property
    def widget_proxies(self) -> dict[int, QGraphicsProxyWidget]:
        """只读：运行预览下已挂载的真实控件代理（供回归 / 外部绑定使用）。"""
        return dict(self._widget_proxies)

    def set_movable_gate(self, enabled: bool) -> None:
        """兼容用的「可拖动」开关：为 True 时图元带 ``ItemIsMovable``。

        视图**不再**打开它 —— 左键按下拖动图元已被取消（移动统一走双击
        跟手），这里保留给外部脚本 / 旧调用方显式启用。运行模式恒不可拖动；
        有父对象的图元也不行，它们的位姿只能由父对象带动。
        """
        self._movable_gate = bool(enabled)
        self.refresh_movable()

    def refresh_movable(self) -> None:
        movable = (not self.is_run_mode) and self._movable_gate
        for it in self.all_items():
            it.setFlag(QGraphicsItem.ItemIsMovable, movable and not it.parent_id)

    def _spawn(self, record: dict) -> BaseItem | None:
        cls = ITEM_TYPES.get(record.get("type"))
        if cls is None:
            return None
        item = cls(record, self.projection)
        self.addItem(item)
        item.setFlag(QGraphicsItem.ItemIsMovable,
                     (not self.is_run_mode) and self._movable_gate
                     and not item.parent_id)
        self.index.register(item)
        self._last_pose[item.item_id] = item.live_page_pose()[:3]
        return item

    def create_item(
        self,
        type_key: str,
        center: tuple[float, float] = (0.0, 0.0),
        size: tuple[float, float] | None = None,
        commit: bool = True,
        **fields,
    ) -> BaseItem | None:
        """按类型新建一个图元。``center``/``size`` 是 **page 场景坐标**。

        ``commit=False`` 用于手动绘制：先创建但不标脏/不广播，待绘制完成
        （``_finish_draw``）再统一标脏并通知历史，取消时可直接删除不留痕。

        工具箱的 7 个控件变体用 ``widget:<key>`` 伪类型传入；真正的 ``type``
        仍是 ``widget``，变体只写进顶层 ``widgetType``（与旧 Core 完全一致）。
        """
        variant = ""
        if type_key.startswith("widget:"):
            variant = normalize_variant(type_key.split(":", 1)[1])
            type_key = "widget"
        if type_key not in ITEM_TYPES:
            return None
        w, h = size or DEFAULT_SIZES.get(type_key, (400.0, 240.0))
        cx, cy = float(center[0]), float(center[1])
        iid = self.index.allocate_id()
        top_z = max((it.zValue() for it in self.all_items()), default=0.0)
        record: dict = {
            "id": iid,
            "name": f"{TYPE_LABELS.get(type_key, type_key)}_{iid}",
            "type": type_key,
            "parent_id": 0, "children_ids": [], "group_id": 0,
            "center_pos": {"x": cx, "y": cy},
            "origin_pos": {"x": cx, "y": cy},
            "width": w, "height": h, "rotate": 0.0,
            "style": dict(DEFAULT_STYLE),
            "zValue": top_z + 1.0,
        }
        if type_key == "circle":
            record.pop("width"), record.pop("height")
            record["radius_w"], record["radius_h"] = w / 2.0, h / 2.0
        elif type_key == "line":
            record.pop("center_pos"), record.pop("width"), record.pop("height")
            record["head_pos"] = {"x": cx - w / 2, "y": cy - h / 2}
            record["end_pos"] = {"x": cx + w / 2, "y": cy + h / 2}
            record["length"] = math.hypot(w, h)
        elif type_key in ("triangle", "polygon", "path"):
            pts = [
                {"x": cx, "y": cy - h / 2},
                {"x": cx + w / 2, "y": cy + h / 2},
                {"x": cx - w / 2, "y": cy + h / 2},
            ]
            if type_key == "polygon":
                pts = pts + [{"x": cx, "y": cy + h / 2}]
            if type_key == "path":
                pts[0]["move"] = True
            record["vertices"] = pts
        elif type_key == "text":
            record["context"] = fields.pop("context", "文本")
        elif type_key == "image":
            record["image_path"] = fields.pop("image_path", "")
        elif type_key == "checkbox":
            record["checked"] = False
            record["toggleEnabled"] = True
        elif type_key == "widget":
            # 5 个顶层字段与默认值逐字对齐旧 Core widget_element.to_dict，
            # 老页面缺字段时也只在读取侧兜底、绝不回写。
            record.update(dict(WIDGET_DEFAULTS))
            if variant:
                record["widgetType"] = variant
        record.update(fields)
        item = self._spawn(record)
        if item is not None:
            self.index.rebuild_links()
            if commit:
                self.mark_modified()
                self.contentChanged.emit()
        return item

    # ==================================================================
    # 手动绘制（CAD 式分点落点，参考 Designer/Core 的 begin_draw 流程）
    # ==================================================================
    # 落点次数：box/circle/line 两击，triangle 三击，polygon/path 多击 + 右键闭合
    _DRAW_CLICKS = {
        "rect": 2, "circle": 2, "line": 2, "triangle": 3,
        "polygon": -1, "path": -1,
    }
    def constrain_ortho(self, anchor: QPointF, point: QPointF) -> tuple[QPointF, str]:
        """把 ``point`` 相对 ``anchor`` 锁到屏幕水平 / 竖直，返回 ``(page 点, 轴)``。

        约束**必须在视图坐标里做**：AGV 投影是「轴交换 + 双轴取反」
        （``view = (-y*kx, -x*ky)``），page 的 Δy=0 在屏幕上其实是竖线，
        page 的 Δx=0 反而是横线。所以先投影 → 按屏幕上较大的位移分量选主轴
        → 把另一条轴钉回锚点 → 反投影回 page，画出来才是所见即所得。

        轴标记 ``H``（屏幕水平，落盘后 page W=0）/ ``V``（屏幕竖直，
        page H=0），正好对应属性面板「宽或高为 0 即水平 / 竖直线」的口径。
        两点重合时原样返回、轴为空，避免零长度线。
        """
        proj = self.projection
        a = proj.point(anchor.x(), anchor.y())
        b = proj.point(point.x(), point.y())
        dx, dy = b.x() - a.x(), b.y() - a.y()
        if abs(dx) < 1e-12 and abs(dy) < 1e-12:
            return QPointF(point), ""
        if abs(dx) >= abs(dy):
            locked, axis = QPointF(b.x(), a.y()), "H"
        else:
            locked, axis = QPointF(a.x(), b.y()), "V"
        x, y = proj.inverse_point(locked.x(), locked.y())
        return QPointF(x, y), axis

    def _draw_clicks(self, type_key: str) -> int:
        return self._DRAW_CLICKS.get(type_key, 1)

    def drawing_active(self) -> bool:
        return self._draw_item is not None

    def drawing_polygon(self) -> bool:
        return self._draw_polygon

    def begin_draw_tool(self, type_key: str) -> BaseItem | None:
        """激活绘制工具：立即创建图元（跟随鼠标），点击画布落点。"""
        if self.is_run_mode:
            return None
        self.cancel_draw()
        item = self.create_item(type_key, center=(0.0, 0.0), commit=False)
        if item is None:
            return None
        self._draw_item = item
        self._draw_type = type_key
        self._draw_polygon = type_key in ("polygon", "path")
        item._drawing = True
        item._draw_points = []
        item._draw_preview = None
        # 顶点类图元在落足前无法构成有效几何，先隐藏，靠预览层画顶点连线。
        if self._draw_polygon or item.TYPE == "triangle":
            item.setVisible(False)
        return item

    def draw_add_point(self, page_pt: QPointF) -> None:
        """左键落点。收集足够点数后自动完成，否则仅更新预览。"""
        item = self._draw_item
        if item is None:
            return
        item._draw_points.append(QPointF(page_pt))
        clicks = self._draw_clicks(item.TYPE)
        if clicks > 0 and len(item._draw_points) >= clicks:
            item.draw_step(item._draw_points, None)
            self._finish_draw()
        else:
            item.draw_step(item._draw_points, page_pt)

    def draw_preview(self, page_pt: QPointF) -> None:
        """鼠标移动时刷新预览（顶点类只更新落点连线，不参与图元几何）。"""
        item = self._draw_item
        if item is None:
            return
        item._draw_preview = QPointF(page_pt)
        if item.TYPE not in ("triangle", "polygon", "path"):
            item.draw_step(item._draw_points, page_pt)
        item.update()

    def finish_polygon(self, page_pt: QPointF | None = None) -> None:
        """右键结束多边形：把当前光标作为最后一个顶点后闭合。"""
        item = self._draw_item
        if item is None or not self._draw_polygon:
            return
        if page_pt is not None:
            item._draw_points.append(QPointF(page_pt))
        if len(item._draw_points) < 3:
            return
        item.set_page_vertices(item._draw_points)
        item.setVisible(True)
        self._finish_draw()

    def _finish_draw(self) -> None:
        item = self._draw_item
        if item is None:
            return
        if item.TYPE in ("triangle", "polygon", "path"):
            if len(item._draw_points) >= 3:
                item.set_page_vertices(item._draw_points)
                item.setVisible(True)
            else:
                return  # 顶点不足，继续绘制（polygon 不会走到这里）
        item._drawing = False
        item._draw_points = []
        item._draw_preview = None
        self._draw_item = None
        self._modified = True
        self.contentChanged.emit()
        self.drawFinished.emit(item)

    def cancel_draw(self) -> None:
        """放弃进行中的绘制：删除未提交的图元，不留痕迹。"""
        item = self._draw_item
        if item is None:
            return
        self.delete_items([item])
        self._draw_item = None
        self._draw_type = ""
        self._draw_polygon = False
        self._modified = False
        self.drawCancelled.emit()

    def draw_preview_state(self):
        """供视图绘制预览层：返回 (type_key, [page 点], preview_page 或 None)。"""
        item = self._draw_item
        if item is None:
            return None
        return (
            item.TYPE,
            list(item._draw_points),
            item._draw_preview,
            self._draw_polygon,
        )

    def delete_items(self, items) -> int:
        """删除图元（含递归成员）：清 Qt 场景 + 索引 + 逻辑父子 + 残留引用。

        与旧 Core ``base_element.Delete()`` 一致：删除组（或任何拥有成员的
        图元）时先把它名下的成员全部递归删掉，嵌套组继续递归；不会像以前
        那样只解除父子关系、把成员留成散图元。反方向不成立——成员不拥有
        父对象，删成员只删它自己，父对象的 children_ids 由下面的兜底清理。
        """
        ids = {
            it.item_id for it in items
            if isinstance(it, BaseItem) and it.item_id in self.index.by_id
        }
        if not ids:
            return 0
        # 递归展开后代。SceneIndex.descendants() 本身已是深度优先全展开，
        # 用 list(ids) 快照遍历基集即可（后代的后代已在各自结果里）。
        for pid in list(ids):
            for child in self.index.descendants(pid):
                ids.add(child.item_id)
        self.clearSelection()
        for iid in ids:
            # 运行预览的真实控件独立于索引，必须按 id 一起收掉，否则会留在
            # 场景里盖住别的东西（下一次 _sync_widget_proxies 才会清）。
            proxy = self._widget_proxies.pop(iid, None)
            if proxy is not None:
                self.removeItem(proxy)
                widget = proxy.widget()
                proxy.setWidget(None)
                if widget is not None:
                    widget.deleteLater()
            item = self.index.by_id.pop(iid, None)
            if item is None:
                continue
            self.removeItem(item)
            self._last_pose.pop(iid, None)
            if iid in self.index.order:
                self.index.order.remove(iid)
        # 兜底：别的记录里可能还留着指向已删 id 的 children_ids / parent_id
        # （手工改过的 JSON、非法数据），一并清掉，避免索引指向不存在的图元。
        for it in self.all_items():
            rec = it.page_record()
            cids = rec.get("children_ids") or []
            if any(cid in ids for cid in cids):
                it.set_page_field("children_ids", [c for c in cids if c not in ids])
            if rec.get("parent_id") in ids:
                it.set_page_field("parent_id", 0)
                it.set_page_field("group_id", 0)
        self.index.rebuild_links()
        self.refresh_movable()   # 成员被删后解除父对象的图元恢复可拖动
        self.mark_modified()
        self.contentChanged.emit()
        return len(ids)

    # ------------------------------------------------------------------
    # 组名前缀体系（对照旧 Core group_element._prefix_name_subtree 与
    # myQuadTreeScene.paste 的 free_name / rename_members）
    # ------------------------------------------------------------------
    @staticmethod
    def _free_from(candidate: str, used: set[str]) -> str:
        """原名 + ``_2`` / ``_3``…，跳过 ``used``；结果登记回 ``used``。"""
        base = str(candidate or "").strip() or "图元"
        name, i = base, 2
        while name in used:
            name = f"{base}_{i}"
            i += 1
        used.add(name)
        return name

    def names_in_use(self) -> set[str]:
        return {it.get_name() for it in self.all_items()}

    def default_name(self, type_key: str, iid: int, used: set[str]) -> str:
        """``类型_序号`` 命名（旧 Core createItem / next_default_name 口径）。"""
        return self._free_from(
            f"{TYPE_LABELS.get(type_key, type_key)}_{iid}", used)

    def replace_name_prefix(self, ids, old_prefix: str, new_prefix: str,
                            used: set[str]) -> None:
        """替换整棵子树名字里的组名前缀；冲突 / 前缀不匹配则退回默认命名。

        ``old_prefix=""`` 表示成组时给整棵子树加前缀；``new_prefix=""`` 表示
        解组时剥掉一层。这里不沿用旧 Core「前缀不匹配仍强行拼整名」的行为，
        避免嵌套组复制后名字越拼越长；查重同时覆盖场景已有名字与本次批次。
        """
        for iid in ids:
            it = self.index.by_id.get(iid)
            if it is None:
                continue
            name = str(it.get_name() or "")
            if old_prefix and name.startswith(old_prefix):
                cand = f"{new_prefix}{name[len(old_prefix):]}"
            elif not old_prefix:
                cand = f"{new_prefix}{name}"
            else:
                cand = ""
            if cand and cand not in used:
                used.add(cand)
                it.set_page_field("name", cand)
            else:
                it.set_page_field(
                    "name", self.default_name(it.TYPE, it.item_id, used))

    def rename_group(self, group, new_name: str) -> None:
        """改组名并把成员前缀一起换掉（旧 Core ``group_element.set_name``）。"""
        old = str(group.get_name() or "")
        new = str(new_name or "").strip()
        if not new or new == old:
            return
        used = self.names_in_use()
        used.discard(old)
        used.add(new)
        group.set_page_field("name", new)
        if old:
            self.replace_name_prefix(
                [it.item_id for it in self.index.descendants(group.item_id)],
                f"{old}_", f"{new}_", used)

    # ------------------------------------------------------------------
    # 组尺寸：递归改变组内成员（对照旧 Core rect_element.change_size）
    # ------------------------------------------------------------------
    def resize_group(self, group, w: float, h: float,
                     anchor=None) -> bool:
        """把组及其整棵子树按同一仿射变换 ``F(p)=A+(p-A)·(sx,sy)`` 缩放。

        旧 Core 是「三个角点缩放后求新宽高 + 显式 ``child.change_size``」逐层
        递归；新场景是平铺结构，直接对整棵子树的**全部 page 绝对几何点**做同一
        变换，天然覆盖嵌套组、顶点类、自定义支点，也不会重复传播刚体变换。
        锚点沿用旧规则：无父取旋转中心（支点），有父取旋转后的左上角。
        ``anchor`` 供拖角手柄覆盖：固定的是用户按住的那个对角，而不是支点。
        """
        if self._resizing_group:
            # 已在缩放链路里（apply_scale_about 回到了 GroupItem.set_page_size）
            return False
        old_w, old_h = group.page_size()
        w, h = float(w), float(h)
        if old_w <= 0 or old_h <= 0 or w <= 0 or h <= 0:
            return False
        sx, sy = w / old_w, h / old_h
        if abs(sx - 1.0) < 1e-12 and abs(sy - 1.0) < 1e-12:
            return False
        if anchor is None:
            cx, cy = group.page_center()
            if group.parent_id:
                dx, dy = rotate_xy(-old_w / 2.0, -old_h / 2.0,
                                   0.0, 0.0, group.page_angle())
                ax, ay = cx + dx, cy + dy
            else:
                ax, ay = group.page_origin()
        else:
            ax, ay = float(anchor[0]), float(anchor[1])
        targets = [group] + self.index.descendants(group.item_id)
        self._resizing_group = True
        try:
            self._scale_subtree(targets, (ax, ay), sx, sy)
        finally:
            self._resizing_group = False
        return True

    def _scale_subtree(self, targets, anchor, sx: float, sy: float) -> None:
        """整棵子树绕同一锚点按 ``(sx, sy)`` 缩放，抑制双重刚体传播。"""
        saved = [(it, bool(getattr(it, "_suppress_propagate", False)))
                 for it in targets]
        try:
            # 缩放期间 setRotation / setPos 会产生位姿差分，别再刚体传播一次
            for it, _ in saved:
                it._suppress_propagate = True
            for it, _ in saved:
                it.apply_scale_about(anchor, sx, sy)
        finally:
            for it, flag in saved:
                it._suppress_propagate = flag
        for it, _ in saved:
            self._last_pose[it.item_id] = it.live_page_pose()[:3]
        self.mark_modified()

    def resize_item_about(self, item, anchor, sx: float,
                          sy: float) -> bool:
        """拖角手柄入口：按**增量**比例绕 ``anchor`` 缩放图元及其子树。

        ``anchor`` 是 page 坐标下保持不动的那个对角。组走
        ``resize_group``（与属性面板同一条链路，成员会递归跟随）；其余图元
        直接走 ``_scale_subtree``，父对象带后代时后代也一起缩放。
        每帧传的是 ``本次总比例 / 上次总比例``，仿射变换可复合，不会累积漂移。
        """
        if sx <= 0 or sy <= 0:
            return False
        if item.TYPE == "group":
            w, h = item.page_size()
            return self.resize_group(item, w * sx, h * sy, anchor=anchor)
        targets = [item] + self.index.descendants(item.item_id)
        # 子树里若有嵌套组，挡住它委托回默认锚点的 resize_group
        self._resizing_group = True
        try:
            self._scale_subtree(targets, anchor, sx, sy)
        finally:
            self._resizing_group = False
        return True

    # ------------------------------------------------------------------
    # 递归复制 / 剪贴板（对照旧 Core copy_selected + paste）
    # ------------------------------------------------------------------
    def top_level_items(self, items=None) -> list[BaseItem]:
        """过滤掉「祖先也在集合里」的图元，只留顶层。"""
        src = list(self.selected_items() if items is None else items)
        ids = {it.item_id for it in src}
        out: list[BaseItem] = []
        for it in src:
            pid, seen, nested = it.parent_id, set(), False
            while pid and pid not in seen:
                if pid in ids:
                    nested = True
                    break
                seen.add(pid)
                parent = self.index.by_id.get(pid)
                pid = parent.parent_id if parent is not None else 0
            if not nested:
                out.append(it)
        return out

    def _capture_subtree(self, items) -> list[tuple[int, dict]]:
        """展平整棵子树并快照成 (原 id, page 记录)，**按原 Z 序排列**。

        展平本身是「父在子前」的树序遍历，但那**不是层级顺序**：
        ``_instantiate`` 按快照下标写 ``z_base + i``，照树序写 z 会把组内
        成员的相对层级打乱，连组框（z 最高）都会被压到副本最底层。

        排序键是 ``(zValue, index.order 位次)``，与 ``SceneIndex.sorted_items()``
        的稳定排序口径一致 —— 页面里大量图元 zValue 相同，层级完全靠 JSON
        数组顺序定，同值必须退回数组顺序，不能退回树序。``_spawn`` 不依赖
        「父已存在」（循环后统一 ``rebuild_links``），所以排序不会破坏父子关系。
        """
        out: list[tuple[int, dict]] = []
        seen: set[int] = set()
        for top in self.top_level_items(items):
            for it in [top] + self.index.descendants(top.item_id):
                if it.item_id in seen:
                    continue
                seen.add(it.item_id)
                # to_page_record 会把尚未存盘的旋转烘焙进顶点，副本不丢姿态
                out.append((it.item_id, copy.deepcopy(it.to_page_record())))
        rank = {iid: i for i, iid in enumerate(self.index.order)}

        def z_of(rec: dict) -> float:
            try:
                return float(rec.get("zValue", 0.0) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        # Python 排序稳定：z 与位次都相同时保持原来的树序，不会抖
        out.sort(key=lambda pair: (z_of(pair[1]),
                                   rank.get(pair[0], len(rank))))
        return out

    @staticmethod
    def _shift_record(rec: dict, dx: float, dy: float) -> None:
        """平铺结构没有 Qt 父链：偏移必须施加到树里每个几何点。"""
        for key in ("center_pos", "origin_pos", "head_pos", "end_pos"):
            v = rec.get(key)
            if isinstance(v, dict):
                v["x"] = float(v.get("x", 0.0)) + dx
                v["y"] = float(v.get("y", 0.0)) + dy
        for v in rec.get("vertices") or []:
            v["x"] = float(v.get("x", 0.0)) + dx
            v["y"] = float(v.get("y", 0.0)) + dy

    @staticmethod
    def _snapshot_descendants(snapshot, root: int) -> list[int]:
        """快照里 ``root`` 的全部后代原 id（只认 parent_id）。"""
        children: dict[int, list[int]] = {}
        for old, rec in snapshot:
            children.setdefault(int(rec.get("parent_id") or 0), []).append(old)
        out, stack = [], list(children.get(root, []))
        while stack:
            i = stack.pop()
            out.append(i)
            stack.extend(children.get(i, []))
        return out

    def _name_copies(self, snapshot, id_map, top_ids) -> dict[int, str]:
        """按旧 Core ``paste`` 口径命名副本：组 ``原名_2``、成员只换前缀。

        对照 ``myQuadTreeScene.paste`` 的 ``free_name`` + ``rename_members``，
        但修掉三处历史缺陷：非组顶层不再丢弃用户自定义名改用 类型_序号；
        剪贴板始终是原始快照，连续粘贴得到 原名_2 / 原名_3 而不是
        原名_2_2_2；成员前缀不匹配或撞名时退回默认命名，不把整名拼到
        新组名后面越拼越长。
        """
        recs = dict(snapshot)
        used = self.names_in_use()
        names: dict[int, str] = {}
        for old, rec in snapshot:
            if old not in top_ids or rec.get("type") != "group":
                continue
            old_name = str(rec.get("name") or "").strip()
            new_name = self._free_from(old_name or "组", used)
            names[old] = new_name
            old_prefix = f"{old_name}_" if old_name else ""
            new_prefix = f"{new_name}_"
            for cid in self._snapshot_descendants(snapshot, old):
                crec = recs[cid]
                cname = str(crec.get("name") or "")
                if old_prefix and cname.startswith(old_prefix):
                    cand = f"{new_prefix}{cname[len(old_prefix):]}"
                elif not old_prefix:
                    cand = f"{new_prefix}{cname}"
                else:
                    cand = ""
                if cand and cand not in used:
                    names[cid] = cand
                    used.add(cand)
                else:
                    names[cid] = self.default_name(
                        str(crec.get("type") or ""), id_map[cid], used)
        for old, rec in snapshot:
            if old not in names:
                names[old] = self._free_from(
                    str(rec.get("name") or "").strip()
                    or TYPE_LABELS.get(str(rec.get("type") or ""), "图元"),
                    used)
        return names

    def _instantiate(self, snapshot, offset) -> list[BaseItem]:
        """从快照造一棵新子树：重发 id、重映射关系、整树统一偏移。"""
        if not snapshot:
            return []
        # 剪贴板快照必须留着连续粘贴，绝不能原地改写
        snapshot = [(old, copy.deepcopy(rec)) for old, rec in snapshot]
        dx, dy = float(offset[0]), float(offset[1])
        known = {old for old, _ in snapshot}
        id_map = {old: self.index.allocate_id() for old, _ in snapshot}
        top_ids = {old for old, rec in snapshot
                   if int(rec.get("parent_id") or 0) not in known}
        names = self._name_copies(snapshot, id_map, top_ids)
        z_base = max((it.zValue() for it in self.all_items()), default=0.0) + 1.0
        made: list[BaseItem] = []
        for i, (old, rec) in enumerate(snapshot):
            rec["id"] = id_map[old]
            rec["name"] = names[old]
            pid = int(rec.get("parent_id") or 0)
            gid = int(rec.get("group_id") or 0)
            rec["parent_id"] = id_map[pid] if pid in known else 0
            rec["group_id"] = id_map[gid] if gid in known else 0
            if "children_ids" in rec:
                rec["children_ids"] = [
                    id_map[c] for c in (rec.get("children_ids") or [])
                    if c in id_map
                ]
            rec["zValue"] = z_base + i
            self._shift_record(rec, dx, dy)
            item = self._spawn(rec)
            if item is not None:
                made.append(item)
        if made:
            self.index.rebuild_links()
            self.mark_modified()
            self.contentChanged.emit()
        wanted = {id_map[o] for o in top_ids}
        return [it for it in made if it.item_id in wanted]

    def instantiate_template(self, template, target: QPointF) -> BaseItem | None:
        """把工具箱模板实例化到 ``target``（page 坐标），返回新的根组图元。

        模板文件与旧设计器共用（``ToolboxTemplate.items`` 就是 page 记录，
        捕获时根组中心已平移到原点）。这里复用 ``_instantiate`` 的重发 id /
        重映射关系 / 组名前缀命名 / 整树统一偏移，只额外做三件事：

        1. **可达性**：按 ``parent_id`` 从 root 做父在子前的 DFS，手工编辑过、
           带悬空 id 的模板不会把无关图元一起带进来；
        2. **保持层级**：按 ``(zValue, 模板数组顺序)`` 稳定排序再交给
           ``_instantiate``（它按快照顺序写 ``z_base + i``）。154 个成员的
           料架模板里 id 顺序和 z 顺序并不一致，按 id 排会把层级整个打乱；
           zValue 大量相同时，兜底用模板 items 的数组顺序而不是 DFS 树序；
        3. **失败回滚**：预校验全部类型，真出异常时删掉本次新建的图元。
        """
        raw_items = list(getattr(template, "items", ()) or ())
        by_old: dict[int, dict] = {}
        for rec in raw_items:
            if not isinstance(rec, dict):
                continue
            old_id = _template_int(rec.get("id"))
            if old_id is not None:
                by_old[old_id] = rec
        if not by_old:
            raise ValueError("模板没有图元数据")

        root_id = _template_int(getattr(template, "root_id", 0)) or 0
        if root_id not in by_old:
            # 兼容手工编辑过的模板：退化到第一个 parent_id 为 0 的记录
            root_id = next(
                (oid for oid, rec in by_old.items()
                 if (_template_int(rec.get("parent_id")) or 0) == 0),
                next(iter(by_old)),
            )

        children: dict[int, list[int]] = {}
        for old_id, rec in by_old.items():
            parent_old = _template_int(rec.get("parent_id")) or 0
            if parent_old != old_id:
                children.setdefault(parent_old, []).append(old_id)

        reachable: list[int] = []
        seen: set[int] = set()

        def visit(old_id: int) -> None:
            if old_id in seen or old_id not in by_old:
                return
            seen.add(old_id)
            reachable.append(old_id)
            for child in children.get(old_id, []):
                visit(child)

        visit(root_id)
        if not reachable:
            raise ValueError("模板没有可实例化的图元")
        for old_id in reachable:
            item_type = str(by_old[old_id].get("type") or "")
            if item_type not in ITEM_TYPES:
                raise ValueError(f"不支持的图元类型: {item_type or '<空>'}")

        # z 升序 + **模板数组顺序**兜底：_instantiate 用「快照下标」写 z。
        # 同值必须退回 raw_items 的数组顺序，不能退回 DFS 树序 —— 页面里
        # 大量图元 zValue 相同，层级靠数组顺序定，用树序会把组内层级打乱。
        def source_z(old_id: int) -> float:
            try:
                return float(by_old[old_id].get("zValue", 0.0) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        array_rank = {oid: i for i, oid in enumerate(by_old)}
        ordered = sorted(
            reachable,
            key=lambda oid: (source_z(oid),
                             array_rank.get(oid, len(array_rank))))
        root_center = _template_point(by_old[root_id].get("center_pos")) or (0.0, 0.0)
        offset = (float(target.x()) - root_center[0],
                  float(target.y()) - root_center[1])
        snapshot = [(oid, copy.deepcopy(by_old[oid])) for oid in ordered]

        before = set(self.index.by_id)
        try:
            made = self._instantiate(snapshot, offset)
        except Exception:
            extra = [it for iid, it in self.index.by_id.items() if iid not in before]
            if extra:
                try:
                    self.delete_items(extra)
                except Exception:
                    pass
            raise
        return made[0] if made else None

    def copy_selected(self) -> int:
        """Ctrl+C：只剪顶层，但递归带整棵子树。"""
        self._clipboard = self._capture_subtree(self.selected_items())
        return len(self._clipboard)

    def paste_clipboard(self, offset=(100.0, 100.0)) -> list[BaseItem]:
        """Ctrl+V：连续粘贴按次数阶梯偏移，避免副本叠在一起。"""
        if not self._clipboard:
            return []
        self._paste_count += 1
        k = self._paste_count
        return self._instantiate(self._clipboard,
                                 (offset[0] * k, offset[1] * k))

    def duplicate_selected(self, offset=(100.0, 100.0)) -> list[BaseItem]:
        """Ctrl+D：等价于「复制 + 立即粘贴」，递归带上整棵子树。"""
        return self._instantiate(
            self._capture_subtree(self.selected_items()), offset)

    def set_item_z(self, items, mode: str) -> None:
        """``front`` / ``back`` / ``raise`` / ``lower``。"""
        zs = [it.zValue() for it in self.all_items()]
        top, bottom = max(zs, default=0.0), min(zs, default=0.0)
        for it in items:
            if mode == "front":
                z = top + 1.0
            elif mode == "back":
                z = bottom - 1.0
            elif mode == "raise":
                z = it.zValue() + 1.0
            elif mode == "lower":
                z = it.zValue() - 1.0
            else:
                continue
            it.set_page_field("zValue", z)
        if items:
            self.mark_modified()
            self.contentChanged.emit()

    def align_selected(self, direction: str) -> None:
        sel = self.selected_items()
        if len(sel) < 2:
            return
        rects = {it.item_id: it.page_bounding_rect() for it in sel}
        union = QRectF()
        for r in rects.values():
            union = union.united(r)
        for it in sel:
            r = rects[it.item_id]
            cx, cy = it.page_center()
            nx, ny = cx, cy
            if direction == "left":
                nx = cx + (union.left() - r.left())
            elif direction == "right":
                nx = cx + (union.right() - r.right())
            elif direction == "top":
                ny = cy + (union.top() - r.top())
            elif direction == "bottom":
                ny = cy + (union.bottom() - r.bottom())
            elif direction == "hcenter":
                nx = cx + (union.center().x() - r.center().x())
            elif direction == "vcenter":
                ny = cy + (union.center().y() - r.center().y())
            it.set_page_center(nx, ny)
        self.mark_modified()
        self.geometryChanged.emit(None)

    def distribute_selected(self, horizontal: bool = True) -> None:
        sel = self.selected_items()
        if len(sel) < 3:
            return
        key = (lambda it: it.page_center()[0]) if horizontal else (lambda it: it.page_center()[1])
        ordered = sorted(sel, key=key)
        first, last = key(ordered[0]), key(ordered[-1])
        step = (last - first) / (len(ordered) - 1)
        for index, it in enumerate(ordered[1:-1], start=1):
            cx, cy = it.page_center()
            target = first + step * index
            it.set_page_center(target, cy) if horizontal else it.set_page_center(cx, target)
        self.mark_modified()
        self.geometryChanged.emit(None)

    def set_selected_origin(self, x: float, y: float) -> int:
        """把选中图元的旋转支点设到同一个 page 场景点（按住 O + 右键「旋转中心设到此处」）。

        多个图元共用同一个支点是有意的：整组绕同一点转动时就靠它。
        可视中心不动，只换支点。
        """
        n = 0
        for it in self.selected_items():
            if it.parentItem() is not None:
                continue
            it.set_page_origin(float(x), float(y))
            n += 1
        if n:
            self.mark_modified()
            self.geometryChanged.emit(None)
            self.contentChanged.emit()
        return n

    def reset_selected_origin(self) -> int:
        """选中图元的旋转支点回到各自的可视中心。"""
        n = 0
        for it in self.selected_items():
            if not it.has_custom_origin():
                continue
            it.reset_page_origin()
            n += 1
        if n:
            self.mark_modified()
            self.geometryChanged.emit(None)
            self.contentChanged.emit()
        return n

    def select_items(self, items, *, append: bool = False) -> None:
        """批量选中：只发**一次** ``selectionChanged``。

        逐项 ``setSelected`` 会让 Qt 每选中一个图元就发一次信号，而
        ``DesignerWindow`` / ``LayerTreeDock`` / ``GraphicsView`` 的槽里都有
        「遍历整棵树回灌选中 + 重建属性面板」这类随选中数增长的工作。全选
        1600 个图元实测会被执行 1600 次、耗时数分钟（纯 Qt 选中本身只要
        0.02s），表现就是「全选卡死」。这里屏蔽信号一次性设置完再补发一次，
        最终选中集合、槽的可见结果与逐项选中完全一致。
        """
        targets = list(items)
        was_blocked = self.blockSignals(True)
        try:
            if not append:
                self.clearSelection()
            for it in targets:
                if it is not None:
                    it.setSelected(True)
        finally:
            self.blockSignals(was_blocked)
            self.selectionChanged.emit()

    def select_all_items(self) -> None:
        self.select_items(self.all_items())

    def find_item_by_name(self, name: str) -> BaseItem | None:
        return next((it for it in self.all_items() if it.get_name() == name), None)
