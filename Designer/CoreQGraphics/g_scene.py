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
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene

from .g_element import BaseItem
from .g_elements import ITEM_TYPES
from .g_projection import SceneProjection

WORLD_RECT = QRectF(-100000, -100000, 200000, 200000)
DEFAULT_BACKGROUND = "#bee1f59b"

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
        # 手动绘制控制器（CAD 式分点落点）
        self._draw_item: BaseItem | None = None
        self._draw_type = ""
        self._draw_polygon = False
        # 移动门控：仅当为 True 时图元可拖动（默认 False，需按住 CTRL）
        self._movable_gate = False
        self.setSceneRect(WORLD_RECT)
        self.setItemIndexMethod(QGraphicsScene.BspTreeIndex)
        self.setBackgroundBrush(QBrush(QColor(DEFAULT_BACKGROUND)))

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
            it.parent_id = iid
            it.group_id = iid
        self.index.rebuild_links()
        self.refresh_movable()   # 成员挂上父对象后不再可单独拖动
        return group

    def ungroup_selected(self) -> int:
        count = 0
        for group in [it for it in self.selected_items() if it.TYPE == "group"]:
            for child in self.index.descendants(group.item_id):
                child.parent_id = 0
                child.group_id = 0
                count += 1
            self.removeItem(group)
            self.index.by_id.pop(group.item_id, None)
            if group.item_id in self.index.order:
                self.index.order.remove(group.item_id)
        self.index.rebuild_links()
        self.refresh_movable()   # 解组后成员重新可独立拖动
        return count

    # ------------------------------------------------------------------
    # 吸附点 / 视图
    # ------------------------------------------------------------------
    def snap_points(self) -> tuple[list[QPointF], list[QPointF]]:
        ends: list[QPointF] = []
        mids: list[QPointF] = []
        for it in self.index.by_id.values():
            if not it.isVisible():
                continue
            e, m = it.snap_points()
            ends.extend(e)
            mids.extend(m)
        return ends, mids

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

    def snapshot(self) -> dict:
        return self.page_data()

    def restore(self, data: dict) -> None:
        """从快照重建（撤销/重做）。保留当前文件路径与脏状态。"""
        was_modified = self._modified
        self.load_data(data)
        self._modified = was_modified
        self.contentChanged.emit()

    def set_scene_mode(self, run: bool) -> None:
        self.is_run_mode = bool(run)
        self.clearSelection()
        for it in self.all_items():
            it.set_selectable(not run)
            it.setFlag(QGraphicsItem.ItemIsMovable,
                       (not run) and self._movable_gate and not it.parent_id)
        self.update()

    def set_movable_gate(self, enabled: bool) -> None:
        """CTRL 门控：为 True 时图元可拖动，否则仅可选中、不可拖动。

        默认 False，即必须按住 CTRL 才能移动选中图元。运行模式恒不可拖动；
        有父对象的图元也不行——它们的位姿只能由父对象带动。
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
        """
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
            record.update({
                "widgetText": "Widget", "widgetType": "label",
                "widgetFontSize": 12, "widgetColor": "#000000",
                "widgetBackground": "#ffffff",
            })
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
        """删除图元：清 Qt 场景 + 索引 + 逻辑父子 + 其它记录的 children_ids。"""
        ids = {
            it.item_id for it in items
            if isinstance(it, BaseItem) and it.item_id in self.index.by_id
        }
        if not ids:
            return 0
        # 删组时保留子图元，只解除父子关系（与旧实现解组语义一致）
        for gid in ids:
            group = self.index.by_id.get(gid)
            if group is not None and group.TYPE == "group":
                for child in self.index.descendants(gid):
                    child.set_page_field("parent_id", 0)
                    child.set_page_field("group_id", 0)
        self.clearSelection()
        for iid in ids:
            item = self.index.by_id.pop(iid, None)
            if item is None:
                continue
            self.removeItem(item)
            self._last_pose.pop(iid, None)
            if iid in self.index.order:
                self.index.order.remove(iid)
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

    def duplicate_selected(self, offset: tuple[float, float] = (100.0, 100.0)) -> list[BaseItem]:
        out: list[BaseItem] = []
        for src in self.selected_items():
            rec = copy.deepcopy(src.page_record())
            iid = self.index.allocate_id()
            rec["id"] = iid
            rec["name"] = f"{rec.get('name', 'item')}_copy{iid}"
            rec["parent_id"], rec["group_id"], rec["children_ids"] = 0, 0, []
            rec["zValue"] = src.zValue() + 0.5
            for key in ("center_pos", "origin_pos", "head_pos", "end_pos"):
                if key in rec and isinstance(rec[key], dict):
                    rec[key] = {
                        "x": float(rec[key].get("x", 0.0)) + offset[0],
                        "y": float(rec[key].get("y", 0.0)) + offset[1],
                    }
            for v in rec.get("vertices") or []:
                v["x"] = float(v.get("x", 0.0)) + offset[0]
                v["y"] = float(v.get("y", 0.0)) + offset[1]
            item = self._spawn(rec)
            if item is not None:
                out.append(item)
        if out:
            self.index.rebuild_links()
            self.mark_modified()
            self.contentChanged.emit()
        return out

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
        """把选中图元的旋转支点设到同一个 page 场景点（右键「旋转中心设到此处」）。

        多个图元共用同一个支点是有意的：整组绕同一点转动时就靠它。
        可视中心不动，只换支点。
        """
        n = 0
        for it in self.selected_items():
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

    def select_all_items(self) -> None:
        for it in self.all_items():
            it.setSelected(True)

    def find_item_by_name(self, name: str) -> BaseItem | None:
        return next((it for it in self.all_items() if it.get_name() == name), None)
