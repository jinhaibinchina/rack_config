"""可复用的「组合模板」：把设计态的一个组（含全部后代）存成工具箱控件。

参考 ``Designer/Core/ui/template_store.py``，但按 CoreQGraphics 的平铺结构重写：
组不是 Qt 父链，而是 ``parent_id`` / ``children_ids``；图元记录直接取
``BaseItem.to_page_record()``（未存盘的旋转会先烘焙进顶点），因此写出来的
``toolbox_templates.json`` 与旧设计器**逐字同构、共用同一份文件**
（``Designer/Core/data.json/datas/design/toolbox_templates.json``），两边
互相打开对方保存的模板都能用。

本模块只负责存取与「从组捕获」；实例化在 ``GraphicsScene.instantiate_template``，
不在这里 import 任何旧 Core 的图元类。
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import QPointF

# MIME 与视图层共用一份常量（g_view 不依赖 ui 包，避免循环导入）；
# 这里 re-export 一下，外部脚本按旧路径 import 也不会断。
from ..g_view import TEMPLATE_MIME_TYPE  # noqa: F401

TEMPLATE_FILE_NAME = "toolbox_templates.json"
TEMPLATE_VERSION = 1

# 所有 ``to_page_record`` 都用这些嵌套字典存 page 绝对坐标；捕获时整体平移
# 到「根组中心 = 原点」，宽高 / 半径 / 旋转一律不动。
POSITION_KEYS = ("center_pos", "origin_pos", "head_pos", "end_pos")


@dataclass
class ToolboxTemplate:
    """工具箱里的一个可复用组。``items`` 是父在子前的 page 记录列表。"""

    id: str
    name: str
    root_id: int
    width: float
    height: float
    items: List[dict] = field(default_factory=list)
    created_at: str = ""

    @property
    def node_count(self) -> int:
        return len(self.items)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "root_id": self.root_id,
            "width": self.width,
            "height": self.height,
            "created_at": self.created_at,
            "items": self.items,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolboxTemplate":
        if not isinstance(data, dict):
            raise ValueError("模板数据必须是对象")
        template_id = str(data.get("id", "")).strip()
        name = str(data.get("name", "")).strip()
        items = data.get("items", [])
        if not template_id:
            raise ValueError("模板缺少 id")
        if not isinstance(items, list) or not items:
            raise ValueError("模板缺少图元数据")
        clean_items = [item for item in items if isinstance(item, dict)]
        if not clean_items:
            raise ValueError("模板缺少有效的图元数据")
        root_id = _to_int(data.get("root_id", clean_items[0].get("id")))
        if root_id is None:
            raise ValueError("模板缺少 root_id")
        if not any(_to_int(item.get("id")) == root_id for item in clean_items):
            raise ValueError("模板根图元不存在")
        try:
            width = float(data.get("width", 0.0))
            height = float(data.get("height", 0.0))
        except (TypeError, ValueError):
            width = height = 0.0
        return cls(
            id=template_id,
            name=name or template_id,
            root_id=root_id,
            width=width,
            height=height,
            items=clean_items,
            created_at=str(data.get("created_at", "")),
        )


class TemplateStore:
    """一个设计项目的工具箱模板：加载 / 持久化 / 增删改。"""

    def __init__(self, directory: str):
        self.directory = os.path.abspath(directory)
        self.path = os.path.join(self.directory, TEMPLATE_FILE_NAME)
        self.templates: List[ToolboxTemplate] = []
        self.load()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get(self, template_id: str) -> Optional[ToolboxTemplate]:
        for template in self.templates:
            if template.id == template_id:
                return template
        return None

    def unique_name(self, base_name: str) -> str:
        base_name = (base_name or "").strip() or "组合模板"
        existing = {template.name for template in self.templates}
        if base_name not in existing:
            return base_name
        index = 2
        while f"{base_name} ({index})" in existing:
            index += 1
        return f"{base_name} ({index})"

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def load(self) -> None:
        self.templates = []
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError, TypeError) as exc:
            print(f"读取控件模板失败: {exc}")
            return
        raw_templates = data.get("templates", []) if isinstance(data, dict) else []
        if not isinstance(raw_templates, list):
            return
        for raw in raw_templates:
            try:
                self.templates.append(ToolboxTemplate.from_dict(raw))
            except ValueError as exc:
                print(f"忽略无效的控件模板: {exc}")

    def save(self) -> None:
        os.makedirs(self.directory, exist_ok=True)
        payload = {
            "version": TEMPLATE_VERSION,
            "templates": [template.to_dict() for template in self.templates],
        }
        temp_path = f"{self.path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=4)
        os.replace(temp_path, self.path)

    # ------------------------------------------------------------------
    # 增删改
    # ------------------------------------------------------------------
    def add_from_group(self, scene, group, name: Optional[str] = None) -> ToolboxTemplate:
        """把 ``group`` 及整棵后代子树捕获成新模板（几何整体平移到原点）。

        ``scene`` 是 ``GraphicsScene``。平铺结构没有 Qt 父链，所以从
        ``SceneIndex.children_of`` 做父在子前的 DFS，而不是 ``childItems()``；
        记录一律走 ``to_page_record()``，保证未存盘的旋转也烘焙进模板。
        """
        if getattr(group, "TYPE", "") != "group":
            raise ValueError("只能把组保存为控件模板")
        root_id = int(group.item_id)
        ids = _collect_tree_ids(scene, root_id)
        if len(ids) < 2:
            raise ValueError("该组内没有可保存的图元")

        records = {
            iid: copy.deepcopy(scene.index.by_id[iid].to_page_record())
            for iid in ids
        }
        root_data = records[root_id]
        center = _read_point(root_data.get("center_pos"))
        if center is None:
            x, y = group.page_center()
            center = QPointF(x, y)
        delta = QPointF(-center.x(), -center.y())

        items = []
        for iid in ids:
            record = records[iid]
            _shift_item_positions(record, delta)
            items.append(record)

        wanted_name = (name or "").strip() or group.get_name() or "组合模板"
        template = ToolboxTemplate(
            id=self._next_template_id(),
            name=self.unique_name(wanted_name),
            root_id=root_id,
            width=float(root_data.get("width", 0.0) or 0.0),
            height=float(root_data.get("height", 0.0) or 0.0),
            items=items,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.templates.append(template)
        try:
            self.save()
        except OSError:
            self.templates.remove(template)
            raise
        return template

    def rename(self, template_id: str, new_name: str) -> ToolboxTemplate:
        template = self.get(template_id)
        if template is None:
            raise ValueError("模板不存在")
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValueError("模板名称不能为空")
        if any(other.id != template_id and other.name == new_name
               for other in self.templates):
            raise ValueError(f"模板名称已存在: {new_name}")
        old_name = template.name
        template.name = new_name
        try:
            self.save()
        except OSError:
            template.name = old_name
            raise
        return template

    def remove(self, template_id: str) -> bool:
        for index, template in enumerate(self.templates):
            if template.id != template_id:
                continue
            self.templates.pop(index)
            try:
                self.save()
            except OSError:
                self.templates.insert(index, template)
                raise
            return True
        return False

    def _next_template_id(self) -> str:
        used = set()
        for template in self.templates:
            suffix = template.id.removeprefix("tpl_")
            if suffix.isdigit():
                used.add(int(suffix))
        number = 1
        while number in used:
            number += 1
        return f"tpl_{number}"


# ----------------------------------------------------------------------
# 内部工具
# ----------------------------------------------------------------------
def _collect_tree_ids(scene, root_id: int) -> List[int]:
    """父在子前的 DFS（只认 SceneIndex 的逻辑关系，不含祖先）。"""
    scene.index.rebuild_links()
    by_id = scene.index.by_id
    children_of = scene.index.children_of
    out: List[int] = []
    seen = set()

    def visit(iid: int) -> None:
        if iid in seen or iid not in by_id:
            return
        seen.add(iid)
        out.append(iid)
        for child in children_of.get(iid, []):
            visit(child)

    visit(root_id)
    return out


def _shift_item_positions(data: dict, delta: QPointF) -> None:
    for key in POSITION_KEYS:
        point = data.get(key)
        if not isinstance(point, dict) or "x" not in point or "y" not in point:
            continue
        try:
            point["x"] = round(float(point["x"]) + delta.x(), 3)
            point["y"] = round(float(point["y"]) + delta.y(), 3)
        except (TypeError, ValueError):
            continue
    for point in data.get("vertices") or []:
        if not isinstance(point, dict):
            continue
        try:
            point["x"] = round(float(point["x"]) + delta.x(), 3)
            point["y"] = round(float(point["y"]) + delta.y(), 3)
        except (KeyError, TypeError, ValueError):
            continue


def _read_point(value) -> Optional[QPointF]:
    if not isinstance(value, dict):
        return None
    try:
        return QPointF(float(value["x"]), float(value["y"]))
    except (KeyError, TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
