"""Toolbox definitions and scene-element creation for design mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QPointF

from Designer.Core.elements import (
    base_element,
    checkbox_element,
    circle_element,
    image_element,
    line_element,
    polygon_element,
    rect_element,
    text_element,
    triangle_element,
    widget_element,
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
    widget_type: Optional[str] = None


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
        key="checkbox",
        label="复选框",
        category="功能控件",
        element_class=checkbox_element,
        default_width=40.0,
        default_height=40.0,
        description="拖拽到画布，创建可切换勾选状态的复选框（运行时点击切换）",
    ),
    ToolDefinition(
        key="widget",
        label="控件",
        category="功能控件",
        element_class=widget_element,
        default_width=600.0,
        default_height=800.0,
        description="拖拽到画布，嵌入一个真实 Qt 控件（运行时显示并可交互）",
    ),
    ToolDefinition(
        key="widget_lineedit",
        label="输入框",
        category="功能控件",
        element_class=widget_element,
        default_width=240.0,
        default_height=60.0,
        description="拖拽到画布，嵌入单行文本输入框（QLineEdit）",
        widget_type="lineedit",
    ),
    ToolDefinition(
        key="widget_checkbox",
        label="勾选框",
        category="功能控件",
        element_class=widget_element,
        default_width=160.0,
        default_height=60.0,
        description="拖拽到画布，嵌入真实勾选框（QCheckBox）",
        widget_type="checkbox",
    ),
    ToolDefinition(
        key="widget_combobox",
        label="下拉框",
        category="功能控件",
        element_class=widget_element,
        default_width=240.0,
        default_height=60.0,
        description="拖拽到画布，嵌入下拉选择框（QComboBox）",
        widget_type="combobox",
    ),
    ToolDefinition(
        key="widget_pushbutton",
        label="按钮",
        category="功能控件",
        element_class=widget_element,
        default_width=160.0,
        default_height=80.0,
        description="拖拽到画布，嵌入按钮（QPushButton）",
        widget_type="pushbutton",
    ),
    ToolDefinition(
        key="widget_label",
        label="标签",
        category="功能控件",
        element_class=widget_element,
        default_width=240.0,
        default_height=60.0,
        description="拖拽到画布，嵌入文本标签（QLabel）",
        widget_type="label",
    ),
    ToolDefinition(
        key="widget_spinbox",
        label="数字输入",
        category="功能控件",
        element_class=widget_element,
        default_width=160.0,
        default_height=60.0,
        description="拖拽到画布，嵌入数字微调框（QSpinBox）",
        widget_type="spinbox",
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
        key="polygon",
        label="多边形",
        category="基本图元",
        element_class=polygon_element,
        default_width=140.0,
        default_height=120.0,
        description="拖拽到画布，创建正六边形；点击绘制时左键加点、右键结束",
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
TOOL_CATEGORIES = ["基本图元", "功能控件", "文本与素材"]


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

        # widget_element 的控件变体：创建后按 key 指定真实控件类型。
        if definition.widget_type and isinstance(item, widget_element):
            item.set_widget_type(definition.widget_type)

        if isinstance(item, polygon_element):
            # 拖拽放下生成默认正六边形（点击绘制路径走 myGraphicsScene 的逐点添加）
            item.set_default_geometry(
                pos, definition.default_width, definition.default_height
            )
        elif isinstance(item, triangle_element):
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
        # widget 控件：设计模式下也要立刻挂载真实控件并只读展示，否则新放置的
        # 控件只会画占位框，看起来"没显示控件"。
        if isinstance(item, widget_element):
            item.set_widget_readonly(True)
            item.set_widget_visible(True)
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
