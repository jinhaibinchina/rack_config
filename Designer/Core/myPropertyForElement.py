"""设计模式下各类图元的属性面板。

每个 ``*PropertyItem`` 负责一类图元的分页内容：把图元的读写接口接到
``property_widgets`` 提供的控件上。分页统一为

    常规 / 外观 / 布局            （文本另有「文本内容」，组另有「事件绑定」）

字段在编辑完成（回车或失焦）后立即写回图元，与旧实现的行为一致；颜色、
不透明度这类改动额外补一次 ``prepareDirtyChange``，让画布立刻重绘。

``add_navigation_items(navigation)`` 是外部唯一入口，签名与旧实现相同，
``NavigationContentWidget`` 不需要感知这里的分页结构。
"""

from __future__ import annotations

import json
import math
import os

from PySide6.QtCore import Property, QObject, QPointF, QSizeF, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QTreeWidgetItem,
    QWidget,
)

from .elements import (
    base_element,
    checkbox_element,
    circle_element,
    group_element,
    image_element,
    line_element,
    rect_element,
    text_element,
    triangle_element,
    widget_element,
)
from .property_widgets import (
    FIELD_HEIGHT,
    ColorField,
    OpacityField,
    PropertyPage,
    SectionCard,
    make_check,
    make_double,
    make_int,
    make_line,
    make_textarea,
    make_value_label,
)


TYPE_LABELS = {
    "rect": "矩形",
    "checkbox": "复选框",
    "widget": "控件",
    "triangle": "三角形",
    "line": "直线",
    "circle": "圆形",
    "text": "文本",
    "image": "图片",
    "group": "组合组",
}


def _fmt(value: float, digits: int = 1) -> str:
    return f"{float(value):.{digits}f}"


class PropertyItem(QObject):
    """一类图元的属性页基类。"""

    def __init__(self, parent=None, item: base_element = None):
        super().__init__()
        self.item = item
        self.navi = None
        # 几何字段注册表：geo_key -> (控件, 取值回调)。图元在画布上被拖动/缩放时，
        # 场景发出 item_GeometryChange，属性面板据此增量刷新这些字段，而不重建整页
        # （重建会打断正在编辑的输入框、并跳回上次停留的分页）。
        self._geometry_widgets = []

    # ------------------------------------------------------------------
    # 几何字段增量刷新
    # ------------------------------------------------------------------
    def _bind_geo(self, widget, value_fn):
        """注册一个几何字段控件及其取值回调，供 refresh_geometry() 增量更新。"""

        self._geometry_widgets.append((widget, value_fn))

    def refresh_geometry(self):
        """图元几何变化后，把已注册字段的最新值写回控件（不触发写回信号）。"""

        if self.item is None:
            return
        for widget, value_fn in self._geometry_widgets:
            try:
                value = value_fn()
            except Exception:
                continue
            widget.blockSignals(True)
            try:
                if isinstance(widget, (QDoubleSpinBox, QSpinBox)):
                    widget.setValue(float(value))
                else:
                    widget.setText(str(value))
            finally:
                widget.blockSignals(False)

    # ------------------------------------------------------------------
    # Qt 属性：内部分页通过 setattr(self, "xxx", v) 调用
    # ------------------------------------------------------------------
    @Property(float)
    def sizeHeight(self):
        return self.item.getSize().height()

    @sizeHeight.setter
    def sizeHeight(self, val):
        if self.item.getSize().height() != val:
            w = self.item.getSize().width()
            self.item.change_size(w, val)

    @Property(float)
    def sizeWidth(self):
        return self.item.getSize().width()

    @sizeWidth.setter
    def sizeWidth(self, val):
        if self.item.getSize().width() != val:
            h = self.item.getSize().height()
            self.item.change_size(val, h)

    @Property(QSizeF)
    def size(self):
        return self.item.getSize()

    @size.setter
    def size(self, size):  # 接收一个QSizeF对象
        if self.item.getSize() != size:  # 直接比较QSizeF对象
            self.item.change_size(size.width(), size.height())

    @Property(float)
    def posX(self):
        return self.item.pos().x()

    @posX.setter
    def posX(self, val):
        if self.item.pos().x() != val:
            y = self.item.pos().y()
            self.item.setPos(val, y)

    @Property(float)
    def posY(self):
        return self.item.pos().y()

    @posY.setter
    def posY(self, val):
        if self.item.pos().y() != val:
            x = self.item.pos().x()
            self.item.setPos(x, val)

    @Property(float)
    def head_posX(self):
        return self.item.get_scene_head_pos().x()

    @head_posX.setter
    def head_posX(self, val):
        current = self.item.get_scene_head_pos()
        if current.x() != val:
            self.item.change_position(QPointF(val, current.y()))

    @Property(float)
    def head_posY(self):
        return self.item.get_scene_head_pos().y()

    @head_posY.setter
    def head_posY(self, val):
        current = self.item.get_scene_head_pos()
        if current.y() != val:
            self.item.change_position(QPointF(current.x(), val))

    @Property(int)
    def lineWidth(self):
        return self.item.get_line_width()

    @lineWidth.setter
    def lineWidth(self, val):
        if self.item.get_line_width() != val:
            self.item.set_line_width(val)

    @Property(int)
    def opacity(self):
        return self.item.get_opacity()

    @opacity.setter
    def opacity(self, val):
        if self.item.get_opacity() != val:
            self.item.set_opacity(val)

    @Property(str)
    def name(self):
        return self.item.get_name()

    @name.setter
    def name(self, str):
        self.item.set_name(str)

    # ------------------------------------------------------------------
    # 名称编辑
    # ------------------------------------------------------------------
    def apply_name_edit(self, name_edit) -> bool:
        """把输入框里的名字应用到图元，失败时恢复显示。

        名字全局唯一，``set_name`` 遇到已被别的图元占用的名字会返回 False。
        这时要把输入框恢复成当前名字，否则面板上会显示一个并没有生效的名字，
        看起来就像“名字改不了”。
        """

        requested = name_edit.text()
        if self.item.set_name(requested):
            return True

        current = self.item.get_name()
        owner = None
        manager = getattr(self.item, "m_scene_manager", None)
        if manager is not None:
            owner = manager.findItem(manager.m_name_items.get(requested, 0))
        if owner is not None:
            kind = TYPE_LABELS.get(getattr(owner, "type", ""), getattr(owner, "type", ""))
            message = f"名称“{requested}”已被图元 {owner.id()}（{kind}）占用"
        else:
            message = f"名称“{requested}”不可用"
        print(f"{message}，保持“{current}”")
        name_edit.setText(current)
        scene = getattr(self.item, "m_scene", None)
        status_bar = getattr(scene, "statusBar", None) if scene is not None else None
        if status_bar is not None:
            status_bar.showMessage(f"{message}，仍为“{current}”", 4000)
        return False

    # ------------------------------------------------------------------
    # 描述性文本
    # ------------------------------------------------------------------
    def type_key(self) -> str:
        return str(getattr(self.item, "type", "") or "")

    def type_label(self) -> str:
        key = self.type_key()
        return TYPE_LABELS.get(key, key or "图元")

    def group_label(self) -> str:
        if isinstance(self.item, group_element):
            return f"组合组 · {len(self.item.childItems())} 个成员"
        parent = self.item.parentItem() if self.item.is_has_parent() else None
        if parent is None:
            return "未成组"
        return f"{parent.get_name()}（{parent.id()}）"

    def visibility_label(self) -> str:
        return "可见" if self.item.get_visibility() else "已隐藏"

    # ------------------------------------------------------------------
    # 导航
    # ------------------------------------------------------------------
    def navigation_items(self):
        """左侧导航的顶层项：``[(标题, 页面 key), ...]``。"""

        return [("常规", "general"), ("外观", "appearance"), ("布局", "layout")]

    def add_navigation_items(self, navigation):
        tree = navigation.navigation_tree
        for title, key in self.navigation_items():
            node = QTreeWidgetItem([title])
            node.setData(0, Qt.UserRole, key)
            tree.addTopLevelItem(node)

        self.create_content_pages(navigation)
        if not navigation._building_navigation:
            navigation.select_preferred_page()
        navigation.destory_current.connect(self.on_destory_current)
        self.navi = navigation
        # 把当前属性页对象登记到面板，供几何变化时的增量刷新使用。
        navigation._current_property_item = self

    def on_destory_current(self):
        self.item = None
        if self.navi is not None:
            try:
                self.navi.destory_current.disconnect(self.on_destory_current)
            except (RuntimeError, TypeError):
                pass

    def create_content_pages(self, navi):
        navi.add_page("general", "常规", self.create_general_page())
        navi.add_page("appearance", "外观", self.create_appearance_page())
        navi.add_page("layout", "布局", self.create_layout_page())

    # ------------------------------------------------------------------
    # 卡片：常规
    # ------------------------------------------------------------------
    def create_general_page(self):
        page = PropertyPage()
        page.add_card(self._basic_card())
        page.add_card(self._state_card())
        extra = self._general_extra_cards()
        for card in extra:
            page.add_card(card)
        return page

    def _general_extra_cards(self):
        return []

    def _basic_card(self) -> SectionCard:
        card = SectionCard("基本信息")
        name_edit = make_line(
            self.item.get_name(),
            tooltip="图元名称用于变量绑定与模板引用，必须全局唯一",
        )
        name_edit.editingFinished.connect(lambda: self.apply_name_edit(name_edit))
        card.add_row(("名称", name_edit), ("类型", make_value_label(self.type_label())))
        card.add_row(
            ("图元 ID", make_value_label(str(self.item.id()))),
            (self._group_field_label(), make_value_label(self._group_field_value())),
        )
        return card

    def _group_field_label(self) -> str:
        return "所属组"

    def _group_field_value(self) -> str:
        return self.group_label()

    def _state_card(self) -> SectionCard:
        card = SectionCard("显示与层级")
        card.add_row(
            ("层级 Z", make_value_label(f"{self.item.zValue():g}")),
            ("可见性", make_value_label(self.visibility_label())),
        )
        card.add_row(
            ("可选中", make_value_label("是" if self.item.get_selectable() else "否")),
            ("中心点", make_value_label(self._center_text())),
        )
        card.add_hint("层级与可见性由场景和分组统一维护，这里只做展示，避免误操作把图元藏起来。")
        return card

    def _center_text(self) -> str:
        center = self.item.get_scene_center_pos()
        if center is None:
            return "—"
        return f"{_fmt(center.x())}, {_fmt(center.y())}"

    # ------------------------------------------------------------------
    # 卡片：外观
    # ------------------------------------------------------------------
    def create_appearance_page(self):
        page = PropertyPage()
        page.add_card(self._appearance_card())
        return page

    def _appearance_card(self) -> SectionCard:
        card = SectionCard("描边与填充")

        stroke = ColorField(self.item.get_color())
        stroke.colorChanged.connect(self._apply_stroke_color)
        line_width = make_int(
            self.item.get_line_width(),
            0,
            64,
            tooltip="描边宽度，0 表示不描边",
        )
        line_width.valueChanged.connect(lambda value: setattr(self, "lineWidth", int(value)))
        card.add_row(("描边色", stroke), ("线宽", line_width))

        fill_color = ColorField(self.item.get_fill_color())
        fill_color.colorChanged.connect(self._apply_fill_color)
        fill_check = make_check("启用", self.item.get_fill(), tooltip="关闭时只画描边，内部透明")
        fill_check.toggled.connect(self._apply_fill)
        card.add_row(("填充色", fill_color), ("填充", fill_check))

        opacity = OpacityField(self.item.get_opacity())
        opacity.valueChanged.connect(self._apply_opacity)
        card.add_row(("不透明度", opacity))

        self._appearance_extra_rows(card)
        card.add_hint("不透明度作用于整个图元，描边与填充同时生效。")
        return card

    def _appearance_extra_rows(self, card: SectionCard) -> None:
        """子类追加外观行（例如矩形的圆角）。"""

    def _apply_stroke_color(self, color: QColor) -> None:
        self.item.set_color(color)
        self.item.prepareDirtyChange()

    def _apply_fill_color(self, color: QColor) -> None:
        self.item.set_fill_color(color)
        self.item.prepareDirtyChange()

    def _apply_fill(self, enabled: bool) -> None:
        self.item.set_fill(bool(enabled))
        self.item.prepareDirtyChange()

    def _apply_opacity(self, value: int) -> None:
        # set_opacity 只改画笔/填充的 alpha，不推导脏区，这里补一次重绘通知
        self.item.set_opacity(int(value))
        self.item.prepareDirtyChange()

    # ------------------------------------------------------------------
    # 卡片：布局
    # ------------------------------------------------------------------
    def create_layout_page(self):
        page = PropertyPage()
        page.add_card(self._geometry_card())
        extra = self._layout_extra_cards()
        for card in extra:
            page.add_card(card)
        return page

    def _layout_extra_cards(self):
        return []

    def _geometry_card(self, height_editable: bool = True) -> SectionCard:
        card = SectionCard("位置与尺寸")

        pos = self.item.get_scene_head_pos() or QPointF(0, 0)
        x_box = make_double(pos.x(), step=1.0, tooltip="场景坐标，向右为正")
        y_box = make_double(pos.y(), step=1.0, tooltip="场景坐标，向上为正")
        x_box.valueChanged.connect(lambda value: setattr(self, "head_posX", float(value)))
        y_box.valueChanged.connect(lambda value: setattr(self, "head_posY", float(value)))
        self._bind_geo(x_box, lambda: self.item.get_scene_head_pos().x())
        self._bind_geo(y_box, lambda: self.item.get_scene_head_pos().y())
        card.add_row(("X", x_box), ("Y", y_box))

        size = self.item.getSize()
        w_box = make_double(size.width(), 0.0, 1.0e6, step=1.0)
        h_box = make_double(size.height(), 0.0, 1.0e6, step=1.0)
        w_box.valueChanged.connect(lambda value: setattr(self, "sizeWidth", float(value)))
        if height_editable:
            h_box.valueChanged.connect(lambda value: setattr(self, "sizeHeight", float(value)))
        else:
            h_box.setReadOnly(True)
            h_box.setToolTip("文本高度随内容自动计算")
        self._bind_geo(w_box, lambda: self.item.getSize().width())
        self._bind_geo(h_box, lambda: self.item.getSize().height())
        card.add_row(("宽 W", w_box), ("高 H", h_box))

        angle = self.item.get_angle()
        angle_label = make_value_label(f"{_fmt(angle)}°")
        center_label = make_value_label(self._center_text())
        self._bind_geo(angle_label, lambda: f"{_fmt(self.item.get_angle())}°")
        self._bind_geo(center_label, self._center_text)
        card.add_row(
            ("旋转", angle_label),
            ("中心点", center_label),
        )
        card.add_hint("坐标为场景坐标（Y 轴向上为正）；尺寸与描边宽度使用同一场景单位。")
        return card


class RectPropertyItem(PropertyItem):
    """矩形、复选框、控件、三角形的公共实现。"""

    def __init__(self, parent=None, item: rect_element = None):
        super().__init__(parent=parent, item=item)

    @Property(float)
    def cornerRadius(self):
        return self.item.get_corner_radius()

    @cornerRadius.setter
    def cornerRadius(self, val):
        if self.item.get_corner_radius() != val:
            self.item.set_corner_radius(val)

    def _appearance_extra_rows(self, card: SectionCard) -> None:
        if not hasattr(self.item, "get_corner_radius"):
            return
        if isinstance(self.item, triangle_element):
            # 三角形按顶点路径绘制，圆角对其无效
            return
        size = self.item.getSize()
        max_radius = int(min(size.width(), size.height()) / 2.0)
        radius = make_int(
            int(round(self.item.get_corner_radius())),
            0,
            max(0, max_radius),
            tooltip="圆角半径，单位为场景坐标；上限是短边的一半",
        )
        radius.valueChanged.connect(lambda value: setattr(self, "cornerRadius", float(value)))
        card.add_row(("圆角", radius))


class TrianglePropertyItem(RectPropertyItem):
    """三角形：位置 + 三个顶点。"""

    def __init__(self, parent=None, item: triangle_element = None):
        super().__init__(parent=parent, item=item)

    def _layout_extra_cards(self):
        card = SectionCard("顶点坐标")
        vertices = self.item.get_scene_vertices()
        for index, label in enumerate(("A", "B", "C")):
            point = vertices[index] if index < len(vertices) else QPointF(0, 0)
            x_box = make_double(point.x(), step=1.0)
            y_box = make_double(point.y(), step=1.0)
            x_box.valueChanged.connect(
                lambda value, i=index: self._apply_vertex_axis(i, x=float(value))
            )
            y_box.valueChanged.connect(
                lambda value, i=index: self._apply_vertex_axis(i, y=float(value))
            )
            self._bind_geo(
                x_box,
                lambda i=index: (
                    self.item.get_scene_vertices()[i].x()
                    if i < len(self.item.get_scene_vertices())
                    else 0.0
                ),
            )
            self._bind_geo(
                y_box,
                lambda i=index: (
                    self.item.get_scene_vertices()[i].y()
                    if i < len(self.item.get_scene_vertices())
                    else 0.0
                ),
            )
            card.add_row((f"顶点 {label} X", x_box), ("Y", y_box))
        card.add_hint("三个顶点决定三角形形状；改动顶点不会同时移动整体位置。")
        return [card]

    def _apply_vertex_axis(self, index: int, x=None, y=None) -> None:
        vertices = self.item.get_scene_vertices()
        if len(vertices) != 3:
            return
        point = QPointF(vertices[index])
        if x is not None:
            point.setX(x)
        if y is not None:
            point.setY(y)
        vertices[index] = point
        self.item.set_scene_vertices(vertices)


class CirclePropertyItem(PropertyItem):
    """圆形：外观 + 直径 / 半径。"""

    def __init__(self, parent=None, item: circle_element = None):
        super().__init__(parent=parent, item=item)

    def _layout_extra_cards(self):
        size = self.item.getSize()
        short_edge = min(size.width(), size.height())
        card = SectionCard("尺寸换算")
        dw_label = make_value_label(_fmt(size.width()))
        dh_label = make_value_label(_fmt(size.height()))
        radius_label = make_value_label(_fmt(short_edge / 2.0))
        perimeter_label = make_value_label(_fmt(math.pi * short_edge))
        self._bind_geo(dw_label, lambda: _fmt(self.item.getSize().width()))
        self._bind_geo(dh_label, lambda: _fmt(self.item.getSize().height()))
        self._bind_geo(radius_label, lambda: _fmt(min(self.item.getSize().width(), self.item.getSize().height()) / 2.0))
        self._bind_geo(perimeter_label, lambda: _fmt(math.pi * min(self.item.getSize().width(), self.item.getSize().height())))
        card.add_row(
            ("直径 W", dw_label),
            ("直径 H", dh_label),
        )
        card.add_row(
            ("半径", radius_label),
            ("周长", perimeter_label),
        )
        card.add_hint("圆由外接矩形决定；宽高不等时是椭圆，半径与周长按短边估算，仅供读数参考。")
        return [card]


class LinePropertyItem(PropertyItem):
    """直线：两端点坐标 + 长度/角度。"""

    def __init__(self, parent=None, item: line_element = None):
        super().__init__(parent=parent, item=item)

    @Property(float)
    def head_posX(self):
        return self.item.get_scene_head_pos().x()

    @head_posX.setter
    def head_posX(self, val):
        current = self.item.get_scene_head_pos()
        if current.x() != val:
            self.item.change_head_pos(QPointF(val, current.y()))

    @Property(float)
    def head_posY(self):
        return self.item.get_scene_head_pos().y()

    @head_posY.setter
    def head_posY(self, val):
        current = self.item.get_scene_head_pos()
        if current.y() != val:
            self.item.change_head_pos(QPointF(current.x(), val))

    @Property(float)
    def end_posX(self):
        return self.item.get_scene_end_pos().x()

    @end_posX.setter
    def end_posX(self, val):
        current = self.item.get_scene_end_pos()
        if current.x() != val:
            self.item.change_end_pos(QPointF(val, current.y()))

    @Property(float)
    def end_posY(self):
        return self.item.get_scene_end_pos().y()

    @end_posY.setter
    def end_posY(self, val):
        current = self.item.get_scene_end_pos()
        if current.y() != val:
            self.item.change_end_pos(QPointF(current.x(), val))

    def create_appearance_page(self):
        page = PropertyPage()
        card = SectionCard("线条样式")
        color = ColorField(self.item.get_color())
        color.colorChanged.connect(self._apply_stroke_color)
        card.add_row(("线条颜色", color))

        line_width = make_int(self.item.get_line_width(), 0, 64, tooltip="线宽，0 表示不描边")
        line_width.valueChanged.connect(lambda value: setattr(self, "lineWidth", int(value)))
        card.add_row(("线宽", line_width))

        opacity = OpacityField(self.item.get_opacity())
        opacity.valueChanged.connect(self._apply_opacity)
        card.add_row(("不透明度", opacity))
        page.add_card(card)
        return page

    def create_layout_page(self):
        page = PropertyPage()
        card = SectionCard("端点坐标")

        head = self.item.get_scene_head_pos() or QPointF(0, 0)
        start_x = make_double(head.x(), step=1.0)
        start_y = make_double(head.y(), step=1.0)
        start_x.valueChanged.connect(lambda value: setattr(self, "head_posX", float(value)))
        start_y.valueChanged.connect(lambda value: setattr(self, "head_posY", float(value)))
        self._bind_geo(start_x, lambda: self.item.get_scene_head_pos().x())
        self._bind_geo(start_y, lambda: self.item.get_scene_head_pos().y())
        card.add_row(("起点 X", start_x), ("起点 Y", start_y))

        end = self.item.get_scene_end_pos() or QPointF(0, 0)
        end_x = make_double(end.x(), step=1.0)
        end_y = make_double(end.y(), step=1.0)
        end_x.valueChanged.connect(lambda value: setattr(self, "end_posX", float(value)))
        end_y.valueChanged.connect(lambda value: setattr(self, "end_posY", float(value)))
        self._bind_geo(end_x, lambda: self.item.get_scene_end_pos().x())
        self._bind_geo(end_y, lambda: self.item.get_scene_end_pos().y())
        card.add_row(("终点 X", end_x), ("终点 Y", end_y))

        def _derived():
            head = self.item.get_scene_head_pos() or QPointF(0, 0)
            end = self.item.get_scene_end_pos() or QPointF(0, 0)
            dx = end.x() - head.x()
            dy = end.y() - head.y()
            length = math.hypot(dx, dy)
            angle = math.degrees(math.atan2(dy, dx)) if length else 0.0
            return length, angle

        length, angle = _derived()
        length_label = make_value_label(_fmt(length))
        angle_label = make_value_label(f"{_fmt(angle)}°")
        self._bind_geo(length_label, lambda: _fmt(_derived()[0]))
        self._bind_geo(angle_label, lambda: f"{_fmt(_derived()[1])}°")
        card.add_row(
            ("长度", length_label),
            ("角度", angle_label),
        )
        card.add_hint("长度与角度由两个端点推导，只读展示；角度以 X 轴正方向为 0°。")
        page.add_card(card)
        return page


class TextPropertyItem(PropertyItem):
    """文本：内容 / 外观 / 布局（高度由内容自动计算）。"""

    def __init__(self, parent=None, item: text_element = None):
        super().__init__(parent=parent, item=item)

    def navigation_items(self):
        return [
            ("文本内容", "context"),
            ("常规", "general"),
            ("外观", "appearance"),
            ("布局", "layout"),
        ]

    def create_content_pages(self, navi):
        navi.add_page("context", "文本内容", self.create_context_page())
        navi.add_page("general", "常规", self.create_general_page())
        navi.add_page("appearance", "外观", self.create_appearance_page())
        navi.add_page("layout", "布局", self.create_layout_page())

    def create_context_page(self):
        page = PropertyPage()
        card = SectionCard("文本内容")

        editor = QTextEdit()
        editor.setObjectName("propTextArea")
        editor.setPlaceholderText("输入要显示的文字")
        editor.setFixedHeight(96)
        # context 的读值带额外的绘制留白空格，回填时要 strip，否则每轮编辑都会加长
        editor.setPlainText(str(self.item.context).strip())
        editor.textChanged.connect(
            lambda e=editor: setattr(self.item, "context", e.toPlainText())
        )
        card.add_widget(editor)

        card.add_row(
            ("字号", make_value_label(str(getattr(self.item, "font_size", "—")))),
            ("字数", make_value_label(str(len(str(self.item.context).strip())))),
        )
        card.add_hint(
            "字号由文本框高度自动推算；内容两侧各补一个空格用于绘制留白，"
            "所以画布上的文字会比输入内容略宽。"
        )
        page.add_card(card)
        return page

    def _geometry_card(self, height_editable: bool = False) -> SectionCard:
        return super()._geometry_card(height_editable=height_editable)


class GroupPropertyItem(PropertyItem):
    """组合组：事件绑定 + 常规（含成员管理）+ 外观 + 布局。"""

    def __init__(self, parent=None, item: group_element = None):
        super().__init__(parent=parent, item=item)

    def navigation_items(self):
        return [
            ("事件绑定", "events"),
            ("常规", "general"),
            ("外观", "appearance"),
            ("布局", "layout"),
        ]

    def _group_field_label(self) -> str:
        return "成员规模"

    def _group_field_value(self) -> str:
        return f"组合组 · {len(self.item.childItems())} 个"

    def create_content_pages(self, navi):
        navi.add_page("events", "事件绑定", self.create_events_page())
        navi.add_page("general", "常规", self.create_general_page())
        navi.add_page("appearance", "外观", self.create_appearance_page())
        navi.add_page("layout", "布局", self.create_layout_page())

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def create_events_page(self):
        page = PropertyPage()

        intro = SectionCard("事件说明")
        intro.add_hint(
            "事件触发时优先调用「处理函数」（运行态已注册的 Python 函数），参数使用 JSON 对象；"
            "处理函数留空时才把「变量」写入运行态变量表。\n"
            "值留空时：pressed 写 true、released 写 false、click 写 true、toggle 写当前选中状态。\n"
            "attach 仅在进入运行态时执行一次，适合初始化图元状态。"
        )
        page.add_card(intro)

        state = SectionCard("交互状态")
        self.toggle_enabled_checkbox = make_check(
            "启用 toggle（点击后切换选中状态）", self.item.is_toggle_enabled()
        )
        self.toggle_checked_checkbox = make_check("初始为选中状态", self.item.is_checked())
        self.toggle_checked_checkbox.setEnabled(self.item.is_toggle_enabled())
        state.add_widget(self.toggle_enabled_checkbox)
        state.add_widget(self.toggle_checked_checkbox)
        self.toggle_enabled_checkbox.toggled.connect(self.handle_toggle_enabled_change)
        self.toggle_checked_checkbox.toggled.connect(self.handle_toggle_checked_change)
        page.add_card(state)

        event_specs = (
            ("attach", "初始化 attach", "进入运行态时执行一次"),
            ("pressed", "按下 pressed", "鼠标在组内按下"),
            ("released", "松开 released", "鼠标松开"),
            ("click", "点击 clicked", "一次完整的按下 + 松开"),
            ("toggle", "切换 toggled", "选中状态翻转，值为当前状态"),
        )
        for event_name, label, description in event_specs:
            page.add_card(self._event_card(event_name, label, description))
        return page

    def _event_card(self, event_name: str, label: str, description: str) -> SectionCard:
        binding = self.item.get_event_binding(event_name) or {}
        card = SectionCard(label)
        if binding.get("handler") or binding.get("variable"):
            card.set_badge("已绑定")

        handler = make_line(
            str(binding.get("handler", "")),
            placeholder="处理函数名（如 safety_door.toggle）",
            max_width=520,
        )
        raw_args = binding.get("args")
        args_text = json.dumps(raw_args, ensure_ascii=False) if raw_args else ""
        args = make_line(args_text, placeholder='参数 JSON，如 {"door": "4"}', max_width=520)
        variable = make_line(
            str(binding.get("variable", "")), placeholder="变量名（处理函数为空时使用）"
        )
        value = make_line(str(binding.get("value", "")), placeholder="值（留空=事件默认值）")

        card.add_row(("处理函数", handler))
        card.add_row(("参数 JSON", args))
        card.add_row(("变量", variable), ("值", value))
        card.add_hint(description + "；清空处理函数与变量即解除该事件的绑定。")

        for edit in (handler, args, variable, value):
            edit.editingFinished.connect(
                lambda e=event_name, h=handler, a=args, v=variable, val=value: self.save_event_binding(
                    e, v, val, h, a
                )
            )
        return card

    def save_event_binding(
        self, event_name, variable_edit, value_edit, handler_edit=None, args_edit=None
    ):
        handler = handler_edit.text().strip() if handler_edit is not None else ""
        args = None
        args_text = args_edit.text().strip() if args_edit is not None else ""
        if handler and args_text:
            try:
                args = json.loads(args_text)
            except ValueError as exc:
                print(f"事件参数不是合法 JSON，未保存 {event_name}: {exc}")
                if args_edit is not None:
                    args_edit.setStyleSheet("border: 1px solid #dc2626")
                    args_edit.setToolTip("参数必须是 JSON 对象，例如 {\"door\": \"4\"}")
                return
            if not isinstance(args, dict):
                print(f"事件参数必须是 JSON 对象，未保存 {event_name}: {args_text!r}")
                if args_edit is not None:
                    args_edit.setStyleSheet("border: 1px solid #dc2626")
                    args_edit.setToolTip('参数必须是 JSON 对象，例如 {"door": "4"}')
                return
        if args_edit is not None:
            args_edit.setStyleSheet("")
            args_edit.setToolTip("")

        self.item.set_event_binding(
            event_name,
            variable_edit.text(),
            value_edit.text(),
            handler,
            args,
        )
        if event_name == "toggle" and (variable_edit.text().strip() or handler):
            # Binding the toggle event is the common case; enable the state
            # machine automatically so the event can actually fire.
            self.toggle_enabled_checkbox.setChecked(True)

    def handle_toggle_enabled_change(self, checked):
        self.item.set_toggle_enabled(checked)
        self.toggle_checked_checkbox.setEnabled(checked)

    def handle_toggle_checked_change(self, checked):
        self.item.set_checked(checked)

    # ------------------------------------------------------------------
    # 成员
    # ------------------------------------------------------------------
    def _general_extra_cards(self):
        return [self._members_card()]

    def _members_card(self) -> SectionCard:
        card = SectionCard("成员")
        members = sorted(
            (child for child in self.item.childItems() if isinstance(child, base_element)),
            key=lambda child: child.id(),
        )
        if not members:
            card.add_hint("该组合组没有成员。解散分组后成员会回到画布顶层。")
            return card

        combo = QComboBox()
        combo.setObjectName("propField")
        combo.setFixedHeight(FIELD_HEIGHT)
        combo.setMaximumWidth(280)
        for member in members:
            combo.addItem(f"{member.id()} · {member.get_name()}", member.id())

        name_edit = make_line("", read_only=True, tooltip="组员名称随组名自动变化（组名_成员名）")
        visible_check = make_check("显示", True, tooltip="取消后该成员在画布和运行态都不绘制")

        listing = QListWidget()
        listing.setObjectName("propMemberList")
        listing.setFixedHeight(92)
        listing.setMaximumWidth(780)
        for member in members:
            suffix = "" if member.get_visibility() else "   （隐藏）"
            item = QListWidgetItem(f"{member.id():>4}  {member.get_name()}{suffix}")
            item.setData(Qt.UserRole, member.id())
            listing.addItem(item)

        card.add_row(("成员", combo))
        card.add_row(("名称", name_edit), ("可见", visible_check))
        card.add_widget(listing)

        def current_member():
            member_id = combo.currentData()
            manager = getattr(self.item, "m_scene_manager", None)
            if manager is None or member_id is None:
                return None
            return manager.findItem(int(member_id))

        def sync_fields():
            member = current_member()
            if member is None:
                return
            name_edit.setText(member.get_name())
            visible_check.blockSignals(True)
            visible_check.setChecked(bool(member.get_visibility()))
            visible_check.blockSignals(False)

        def apply_visibility(checked):
            member = current_member()
            if member is not None:
                member.set_visibility(bool(checked))

        combo.currentIndexChanged.connect(lambda _index: sync_fields())
        visible_check.toggled.connect(apply_visibility)
        listing.currentRowChanged.connect(
            lambda row: combo.setCurrentIndex(row) if 0 <= row < combo.count() else None
        )
        sync_fields()
        return card


class ImagePropertyItem(PropertyItem):
    """图片：源文件 + 填充色 + 尺寸。"""

    def __init__(self, parent=None, item: image_element = None):
        super().__init__(parent=parent, item=item)

    def create_appearance_page(self):
        page = PropertyPage()

        source = SectionCard("图片来源")
        path_edit = make_line(self.item.image_path(), read_only=True, tooltip="相对程序目录的路径，随页面一起保存")
        browse = QPushButton("浏览…")
        browse.setObjectName("propBrowseButton")
        browse.setFixedHeight(FIELD_HEIGHT)
        browse.setMinimumWidth(64)
        browse.clicked.connect(self.select_image)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(path_edit, 1)
        row_layout.addWidget(browse)
        source.add_widget(row)
        source.add_hint("支持 PNG；路径按相对目录保存，换机器打开时请连同资源目录一起拷贝。")
        page.add_card(source)
        page.add_card(self._appearance_card())
        return page

    def select_image(self):
        import sys

        parent = self.navi if self.navi else None
        file_path, _ = QFileDialog.getOpenFileName(parent, "选择图片", "", "图片文件 (*.png)")
        if not file_path:
            return
        if getattr(sys, "frozen", False):
            # 打包后的可执行文件路径（如 PyInstaller）
            base_dir = os.path.dirname(sys.executable)
        else:
            # 脚本文件所在路径
            base_dir = os.path.dirname(os.path.abspath(__file__))
        rel_path = os.path.relpath(file_path, base_dir)
        self.item.set_image_path(rel_path)
        self.item.prepareDirtyChange()


class CheckboxPropertyItem(RectPropertyItem):
    """复选框：外观/布局之外补上勾选相关的交互设置。"""

    def __init__(self, parent=None, item: checkbox_element = None):
        super().__init__(parent=parent, item=item)

    def navigation_items(self):
        return [
            ("常规", "general"),
            ("外观", "appearance"),
            ("布局", "layout"),
            ("交互", "interaction"),
        ]

    def create_content_pages(self, navi):
        super().create_content_pages(navi)
        navi.add_page("interaction", "交互", self.create_interaction_page())

    def create_interaction_page(self):
        page = PropertyPage()
        card = SectionCard("勾选状态")
        toggle = make_check(
            "运行时点击可切换勾选状态", self.item.is_toggle_enabled(),
            tooltip="关闭后复选框只做状态指示，点击不会改变勾选",
        )
        checked = make_check("当前为勾选状态（设计态初始值）", self.item.is_checked())
        toggle.toggled.connect(self.item.set_toggle_enabled)
        checked.toggled.connect(self.item.set_checked)
        card.add_widget(toggle)
        card.add_widget(checked)
        card.add_hint("勾选状态会写进页面数据，运行态按此初始值启动。")
        page.add_card(card)
        return page


class WidgetPropertyItem(RectPropertyItem):
    """嵌入式控件：补上控件文本与承载说明。"""

    def __init__(self, parent=None, item: widget_element = None):
        super().__init__(parent=parent, item=item)

    def navigation_items(self):
        return [
            ("常规", "general"),
            ("外观", "appearance"),
            ("布局", "layout"),
            ("控件", "widget"),
        ]

    def create_content_pages(self, navi):
        super().create_content_pages(navi)
        navi.add_page("widget", "控件", self.create_widget_page())

    def create_widget_page(self):
        page = PropertyPage()
        card = SectionCard("控件内容")
        text_edit = make_textarea(
            self.item.widget_text(),
            placeholder="显示在控件上的多行文字",
        )
        text_edit.textChanged.connect(
            lambda: self.item.set_widget_text(text_edit.toPlainText())
        )
        card.add_row(("文本", text_edit))

        # 字体大小
        font_size = make_int(
            self.item.widget_font_size(),
            minimum=6,
            maximum=200,
            suffix=" pt",
            tooltip="默认控件的字号",
        )
        font_size.valueChanged.connect(
            lambda v: self.item.set_widget_font_size(v)
        )
        card.add_row(("字号", font_size))

        # 文字颜色
        color_field = ColorField(QColor(self.item.widget_color()))
        color_field.colorChanged.connect(
            lambda c: self.item.set_widget_color(c)
        )
        card.add_row(("文字色", color_field))

        # 背景色
        background_field = ColorField(QColor(self.item.widget_background()))
        background_field.colorChanged.connect(
            lambda c: self.item.set_widget_background(c)
        )
        card.add_row(("背景色", background_field))

        card.add_hint(
            "控件图元在运行态挂载真实 Qt 控件（默认是只读的多行文本），"
            "可以滚动、选中、复制；设计态只画占位框。几何由「布局」页的宽高决定。"
            "字号、文字色、背景色只作用于默认控件，自定义控件可忽略。"
        )
        page.add_card(card)
        return page
