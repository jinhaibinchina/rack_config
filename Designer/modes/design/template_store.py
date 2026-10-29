"""Reusable group templates for the design-mode toolbox.

A template is a self-contained copy of a group and all of its descendants.
The JSON payload deliberately uses the same item dictionaries as
``SceneSerializer`` so a template can be instantiated through the regular
``*_element.from_dict`` / ``completed(True)`` path.

Template files live next to the design project::

    datas/design/toolbox_templates.json
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from PySide6.QtCore import QPointF

# from my_elements_v2 import (
#     base_element,
#     circle_element,
#     group_element,
#     image_element,
#     line_element,
#     rect_element,
#     text_element,
#     triangle_element,
# )

from Designer.Core.element import base_element
from Designer.Core.elements import (
    base_element,
    circle_element,
    group_element,
    image_element,
    line_element,
    rect_element,
    text_element,
    triangle_element,
)
from Designer.Core.myQuadTreeScene import SceneManager


TEMPLATE_FILE_NAME = "toolbox_templates.json"
TEMPLATE_MIME_TYPE = "application/x-design-template"
TEMPLATE_VERSION = 1

ELEMENT_CLASSES = {
    "line": line_element,
    "rect": rect_element,
    "triangle": triangle_element,
    "circle": circle_element,
    "text": text_element,
    "image": image_element,
    "group": group_element,
}

TYPE_NAME_PREFIX = {
    "group": "组",
    "rect": "矩形",
    "triangle": "三角形",
    "line": "直线",
    "circle": "圆",
    "text": "文本",
    "image": "图片",
}

# Every ``to_dict`` implementation stores absolute scene coordinates in these
# nested dictionaries.  Shifting them lets a template be re-centred on the
# canvas without touching widths, radii or rotations.
POSITION_KEYS = ("center_pos", "origin_pos", "head_pos", "end_pos")


@dataclass
class ToolboxTemplate:
    """One reusable group stored in the toolbox."""

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
            width = 0.0
            height = 0.0

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
    """Loads and persists the toolbox templates of one design project."""

    def __init__(self, directory: str):
        self.directory = os.path.abspath(directory)
        self.path = os.path.join(self.directory, TEMPLATE_FILE_NAME)
        self.templates: List[ToolboxTemplate] = []
        self.load()

    # ------------------------------------------------------------------
    # Query helpers
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
    # Persistence
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
    # Mutations
    # ------------------------------------------------------------------
    def add_from_group(
        self, group: group_element, name: Optional[str] = None
    ) -> ToolboxTemplate:
        """Capture ``group`` (including all descendants) as a new template."""

        if not isinstance(group, group_element):
            raise ValueError("只能把组保存为控件模板")
        if not group.is_has_child():
            raise ValueError("该组内没有可保存的图元")

        root_data = group.to_dict()
        root_center = _read_point(root_data.get("center_pos"))
        if root_center is None:
            root_center = group.get_scene_center_pos()
        delta = QPointF(-root_center.x(), -root_center.y())

        items: List[dict] = []
        for item in _collect_group_tree(group):
            item_data = copy.deepcopy(item.to_dict())
            _shift_item_positions(item_data, delta)
            items.append(item_data)

        wanted_name = (name or "").strip() or group.get_name() or "组合模板"
        template = ToolboxTemplate(
            id=self._next_template_id(),
            name=self.unique_name(wanted_name),
            root_id=group.id(),
            width=float(root_data.get("width", 0.0)),
            height=float(root_data.get("height", 0.0)),
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
        if any(
            other.id != template_id and other.name == new_name
            for other in self.templates
        ):
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
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


def create_template_instance(
    manager: SceneManager,
    template: ToolboxTemplate,
    scene_pos: QPointF,
) -> Optional[base_element]:
    """Create a fresh copy of ``template`` centred at ``scene_pos``.

    New IDs are generated through the page's ``IDGenerator`` so the copy can
    never collide with existing items.  Relationships are rebuilt through
    ``setParentItem`` exactly like the scene deserializer does.
    """

    scene = manager.m_scene
    if scene is None:
        raise ValueError("场景未初始化，无法添加控件模板")

    root_data = _find_root_data(template)
    if root_data is None:
        raise ValueError("模板根图元不存在")

    children_by_parent: Dict[int, List[dict]] = {}
    for data in template.items:
        old_id = _to_int(data.get("id"))
        if old_id is None:
            continue
        parent_old = _to_int(data.get("parent_id")) or 0
        children_by_parent.setdefault(parent_old, []).append(data)

    # Only instantiate nodes reachable from the root.  This protects against
    # manually edited template files with dangling ids.
    ordered: List[dict] = []
    reachable = set()

    def visit(data: dict) -> None:
        old_id = _to_int(data.get("id"))
        if old_id is None or old_id in reachable:
            return
        reachable.add(old_id)
        ordered.append(data)
        for child in _sorted_children(children_by_parent.get(old_id, [])):
            visit(child)

    visit(root_data)
    if not ordered:
        raise ValueError("模板没有可实例化的图元")

    # Assign IDs bottom-up so a parent group always has a higher z-value than
    # its members, matching the result of the regular "create group" flow.
    new_ids: Dict[int, int] = {}

    def assign_ids(data: dict) -> None:
        old_id = _to_int(data.get("id"))
        if old_id is None:
            return
        for child in _sorted_children(children_by_parent.get(old_id, [])):
            child_id = _to_int(child.get("id"))
            if child_id in reachable:
                assign_ids(child)
        if old_id not in new_ids:
            new_ids[old_id] = manager.m_idGenerator.generateID()

    assign_ids(root_data)

    # Only the instance root needs a unique name.  Its members follow the
    # ``<group name>_<member name>`` rule, so their names are derived from the
    # root prefix below instead of being uniquified one by one (that used to
    # append a ``_2`` suffix to every member).
    root_old_id = _to_int(root_data.get("id"))
    root_old_name = str(root_data.get("name") or "")
    root_is_group = str(root_data.get("type", "")) == "group"
    root_old_prefix = f"{root_old_name}_" if (root_old_name and root_is_group) else ""
    root_new_name = ""
    root_new_prefix = ""
    if root_is_group:
        root_new_name = _unique_element_name(
            manager, root_old_name, "group", new_ids[root_old_id]
        )
        root_new_prefix = f"{root_new_name}_" if root_new_name else ""

    root_center = _read_point(root_data.get("center_pos")) or QPointF(0.0, 0.0)
    delta = QPointF(scene_pos.x() - root_center.x(), scene_pos.y() - root_center.y())

    # Keep the stacking order of the captured group.  ``zValue`` used to be the
    # freshly generated id, which re-ordered the copy whenever the group's z
    # order differed from its id order (elements moved with 排列/移到最前, or
    # groups re-created after editing).  Rank the template items by their
    # recorded z value and spread those ranks across the id band of this
    # instance: the copy keeps the original order while using the same z band
    # it had before, so a later drawn element still lands on top of it.
    z_values: Dict[int, float] = {}
    z_base = min(new_ids.values())
    ranked = sorted(
        enumerate(ordered), key=lambda pair: (_source_z_value(pair[1]), pair[0])
    )
    for rank, (_index, data) in enumerate(ranked):
        item_old_id = _to_int(data.get("id"))
        if item_old_id is not None:
            z_values[item_old_id] = float(z_base + rank)

    created: Dict[int, base_element] = {}
    try:
        for data in ordered:
            old_id = _to_int(data.get("id"))
            new_id = new_ids[old_id]
            item_type = str(data.get("type", ""))
            element_class = ELEMENT_CLASSES.get(item_type)
            if element_class is None:
                raise ValueError(f"不支持的图元类型: {item_type or '<空>'}")

            clone = copy.deepcopy(data)
            clone["id"] = new_id
            parent_old = _to_int(data.get("parent_id")) or 0
            clone["parent_id"] = new_ids.get(parent_old, 0)
            clone["children_ids"] = [
                new_ids[child_id]
                for child_id in (
                    _to_int(value) for value in data.get("children_ids", [])
                )
                if child_id in new_ids
            ]
            group_old = _to_int(data.get("group_id")) or 0
            clone["group_id"] = new_ids.get(group_old, 0)
            if root_is_group and old_id == root_old_id:
                clone["name"] = root_new_name
            else:
                clone["name"] = _instance_item_name(
                    manager,
                    data.get("name"),
                    item_type,
                    new_id,
                    root_old_prefix,
                    root_new_prefix,
                )
            clone["zValue"] = z_values.get(old_id, float(new_id))
            _shift_item_positions(clone, delta)

            item = element_class.from_dict(clone)
            item.set_scene_ref(scene)
            item.set_scene_manager_ref(manager)
            item.completed(True)
            created[new_id] = item

        # Rebuild parent/child relationships after every item exists.
        for data in ordered:
            old_id = _to_int(data.get("id"))
            parent_old = _to_int(data.get("parent_id")) or 0
            if parent_old not in new_ids:
                continue
            child = created.get(new_ids[old_id])
            parent = created.get(new_ids[parent_old])
            if child is None or parent is None:
                continue
            if not child.is_has_parent():
                child.setParentItem(parent)
    except Exception:
        _dispose_created_items(manager, created)
        raise

    root = created[new_ids[root_old_id]]
    return root


def _collect_group_tree(group: group_element) -> List[base_element]:
    """Depth-first list with parents before their children."""

    collected: List[base_element] = []
    seen = set()

    def walk(item: base_element) -> None:
        if id(item) in seen:
            return
        seen.add(id(item))
        collected.append(item)
        for child in sorted(
            item.childItems(), key=lambda node: (node.zValue(), node.id())
        ):
            walk(child)

    walk(group)
    return collected


def _sorted_children(items: Iterable[dict]) -> List[dict]:
    return sorted(
        items,
        key=lambda data: (_to_int(data.get("id")) or 0, str(data.get("name", ""))),
    )


def _find_root_data(template: ToolboxTemplate) -> Optional[dict]:
    for data in template.items:
        if _to_int(data.get("id")) == template.root_id:
            return data
    for data in template.items:
        if (_to_int(data.get("parent_id")) or 0) == 0:
            return data
    return None


def _unique_element_name(
    manager: SceneManager, original_name, item_type: str, new_id: int
) -> str:
    candidate = str(original_name or "").strip()
    if not candidate:
        prefix = TYPE_NAME_PREFIX.get(item_type, item_type or "图元")
        candidate = f"{prefix}_{new_id}"

    if candidate not in manager.m_name_items:
        return candidate

    index = 2
    while f"{candidate}_{index}" in manager.m_name_items:
        index += 1
    return f"{candidate}_{index}"


def _instance_item_name(
    manager: SceneManager,
    original_name,
    item_type: str,
    new_id: int,
    old_prefix: str,
    new_prefix: str,
) -> str:
    """Name one member of a template instance.

    Members follow the ``<group name>_<member name>`` rule, so only the captured
    group prefix is swapped for the new one (``组1_abc`` -> ``组1_2_abc``); no
    ``_2`` suffix is appended to the member name.  Templates captured before the
    prefix rule existed still get the new group prefix, and a name that is
    already taken falls back to the regular uniqueness handling so the name
    table never gets overwritten.
    """

    stored = str(original_name or "")
    if old_prefix and stored.startswith(old_prefix):
        base = stored[len(old_prefix):]
    else:
        base = stored
    if base and new_prefix:
        derived = f"{new_prefix}{base}"
    else:
        derived = stored
    if derived and derived not in manager.m_name_items:
        return derived
    return _unique_element_name(manager, derived or stored, item_type, new_id)


def _shift_item_positions(data: dict, delta: QPointF) -> None:
    for key in POSITION_KEYS:
        point = data.get(key)
        if not isinstance(point, dict):
            continue
        if "x" not in point or "y" not in point:
            continue
        try:
            point["x"] = round(float(point["x"]) + delta.x(), 3)
            point["y"] = round(float(point["y"]) + delta.y(), 3)
        except (TypeError, ValueError):
            continue

    # Triangle templates additionally store their three scene-space vertices.
    vertices = data.get("vertices")
    if not isinstance(vertices, list):
        return
    for point in vertices:
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


def _source_z_value(data: dict) -> float:
    """Return the z value recorded in a serialized item (0.0 when invalid)."""

    try:
        return float(data.get("zValue", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _to_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dispose_created_items(
    manager: SceneManager, created: Dict[int, base_element]
) -> None:
    for item in reversed(list(created.values())):
        try:
            if item.is_has_parent():
                item.removeParentItem(True)
            if item.id() in manager.m_items:
                manager.deleteItem(item)
            else:
                item.setParent(None)
                item.deleteLater()
        except Exception as exc:  # pragma: no cover - defensive cleanup
            print(f"清理模板实例失败: {exc}")
