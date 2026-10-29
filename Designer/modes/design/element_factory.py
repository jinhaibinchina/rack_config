"""Toolbox definitions and scene-element creation for design mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QPointF

from Designer.Core.elements import (
    base_element,
    circle_element,
    image_element,
    line_element,
    rect_element,
    text_element,
    triangle_element,
)
from Designer.Core.myQuadTreeScene import SceneManager


ELEMENT_MIME_TYPE = "application/x-design-element"


@dataclass(frozen=True)
class ToolDefinition:
    key: str
    label: str
    category: str
    element_class: type
    default_width: float
    default_height: float
    description: str


TOOL_DEFINITIONS = [
    ToolDefinition(
        key="rect",
        label="矩形",
        category="基本图元",
        element_class=rect_element,
        default_width=160.0,
        default_height=100.0,
        description="拖拽到画布，创建矩形区域",
    ),
    ToolDefinition(
        key="triangle",
        label="三角形",
        category="基本图元",
        element_class=triangle_element,
        default_width=140.0,
        default_height=120.0,
        description="拖拽到画布，创建等腰三角形",
    ),
    ToolDefinition(
        key="line",
        label="直线",
        category="基本图元",
        element_class=line_element,
        default_width=160.0,
        default_height=0.0,
        description="拖拽到画布，创建水平直线",
    ),
    ToolDefinition(
        key="circle",
        label="圆",
        category="基本图元",
        element_class=circle_element,
        default_width=60.0,
        default_height=60.0,
        description="拖拽到画布，创建圆形",
    ),
    ToolDefinition(
        key="text",
        label="文本",
        category="文本与素材",
        element_class=text_element,
        default_width=100.0,
        default_height=60.0,
        description="拖拽到画布，创建文本标签",
    ),
    ToolDefinition(
        key="image",
        label="图片",
        category="文本与素材",
        element_class=image_element,
        default_width=240.0,
        default_height=240.0,
        description="拖拽到画布，创建图片（可在属性面板选择图片）",
    ),
]

TOOL_DEFINITIONS_BY_KEY = {definition.key: definition for definition in TOOL_DEFINITIONS}
TOOL_CATEGORIES = ["基本图元", "文本与素材"]


def tools_in_category(category: str) -> list[ToolDefinition]:
    return [tool for tool in TOOL_DEFINITIONS if tool.category == category]


def create_element(
    manager: SceneManager,
    tool_key: str,
    scene_pos: QPointF,
) -> Optional[object]:
    """Create one element at ``scene_pos`` using the manager's normal path.

    Creation goes through ``SceneManager.createItem`` so IDs, names, z-order,
    quadtree registration and dirty-region handling stay identical to the
    legacy drawing workflow.
    """

    definition = TOOL_DEFINITIONS_BY_KEY.get(tool_key)
    if definition is None:
        print(f"未知的设计控件: {tool_key}")
        return None

    scene = manager.m_scene
    item = None
    try:
        item = manager.createItem(definition.element_class)
        pos = QPointF(scene_pos)

        if isinstance(item, triangle_element):
            # Triangles are defined by three vertices; the toolbox drop creates
            # the legacy apex-up shape inside the requested bounding box.
            item.set_default_geometry(
                pos, definition.default_width, definition.default_height
            )
        elif isinstance(item, rect_element):
            item.transfer_head_pos(pos)
            item.transfer_end_pos(pos + QPointF(definition.default_width, definition.default_height))
        elif isinstance(item, line_element):
            item.transfer_head_pos(pos)
            item.transfer_end_pos(pos + QPointF(definition.default_width, 0.0))
        elif isinstance(item, circle_element):
            item.transfer_head_pos(pos)
            item.transfer_end_pos(pos + QPointF(definition.default_width, 0.0))
        elif isinstance(item, text_element):
            item.transfer_head_pos(pos)
        elif isinstance(item, image_element):
            # image_element has no transfer_head_pos(); position it with
            # transfer_pos() and finish through the regular completed() path.
            item.transfer_pos(pos)
            item.completed()
        else:
            raise TypeError(f"不支持创建该图元类型: {type(item).__name__}")

        # Only one element is selected after creation, matching the existing
        # scene's selection model.
        for other in scene.findChildren(base_element):
            other.set_selected(False)
        item.set_selected(True)
        scene.set_current_select_item(item)
        scene.update()
        return item
    except Exception as exc:
        print(f"创建图元失败({tool_key}): {exc}")
        if item is not None:
            try:
                if item.id() in manager.m_items:
                    manager.deleteItem(item)
                else:
                    item.setParent(None)
                    item.deleteLater()
            except Exception:
                pass
        scene.current_element = None
        scene.current_element_id = 0
        return None
