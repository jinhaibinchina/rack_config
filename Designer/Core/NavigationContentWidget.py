"""设计模式的属性 dock 主体。

面板结构（自上而下）：

    对象摘要条   —— 当前选中的是哪个图元（类型 / 名称 / ID / 所属组）
    导航 + 内容  —— 左侧是属性分页索引，右侧是可滚动的属性表单

具体分页内容由 ``myPropertyForElement`` 里的 ``*PropertyItem`` 提供，
本模块只负责分派、布局和整体样式，以及“选中页面背景”时的页面属性。
"""

import sys

from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStyleFactory,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from .elements import (
    base_element,
    checkbox_element,
    circle_element,
    group_element,
    image_element,
    line_element,
    path_element,
    polygon_element,
    rect_element,
    text_element,
    triangle_element,
    widget_element,
)
from .myGraphicsScene import myGraphicsScene
from .property_widgets import (
    PROPERTY_PANEL_QSS,
    ColorField,
    EmptyState,
    ObjectHeader,
    PropertyPage,
    SectionCard,
    make_value_label,
)
from .myPropertyForElement import (
    TYPE_LABELS,
    CheckboxPropertyItem,
    CirclePropertyItem,
    GroupPropertyItem,
    ImagePropertyItem,
    LinePropertyItem,
    PathPropertyItem,
    PolygonPropertyItem,
    RectPropertyItem,
    TextPropertyItem,
    TrianglePropertyItem,
    WidgetPropertyItem,
)
from .run_property import CabinetPropertyItem
from .my_common import SceneMode


GLYPHS = {
    "rect": "矩",
    "checkbox": "复",
    "widget": "控",
    "triangle": "三",
    "line": "线",
    "circle": "圆",
    "text": "文",
    "image": "图",
    "group": "组",
    "path": "径",
    "polygon": "多",
}


class NavigationContentWidget(QWidget):
    destory_current = Signal()

    def __init__(self, parent=None, scene=None):
        super().__init__(parent)
        self.property_items = {}
        self._last_page_keys = {}
        self._current_namespace = "scene"
        self._building_navigation = False
        self._current_property_item = None
        self._current_selected = None
        self.setObjectName("designPropertyPanel")

        self.item = scene
        self.scene = scene

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.header = ObjectHeader(self)
        main_layout.addWidget(self.header)

        body = QWidget(self)
        body.setObjectName("propBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(8, 6, 8, 8)
        body_layout.setSpacing(0)
        main_layout.addWidget(body, 1)

        self.splitter = QSplitter(Qt.Horizontal, body)
        self.splitter.setChildrenCollapsible(False)
        body_layout.addWidget(self.splitter)

        self.navigation_scroll = self.create_navigation_scroll()
        self.splitter.addWidget(self.navigation_scroll)

        self.content_scroll = self.create_content_scroll()
        self.splitter.addWidget(self.content_scroll)

        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([132, 900])

        self.add_navigation_items()
        self.apply_style()

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------
    def create_navigation_scroll(self):
        """左侧分页索引（窄列，跟着内容一起滚动）。"""

        scroll_area = QScrollArea()
        scroll_area.setObjectName("propPageScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setMinimumWidth(96)
        scroll_area.setMaximumWidth(210)

        container = QWidget()
        container.setObjectName("propBody")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(0)

        self.navigation_tree = self.create_navigation_tree()
        layout.addWidget(self.navigation_tree)
        layout.addStretch(1)
        scroll_area.setWidget(container)
        return scroll_area

    def create_content_scroll(self):
        scroll_area = QScrollArea()
        scroll_area.setObjectName("propPageScroll")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)

        self.content_container = QWidget()
        self.content_container.setObjectName("propBody")
        scroll_area.setWidget(self.content_container)

        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self.content_stack = QStackedWidget()
        self.content_layout.addWidget(self.content_stack)
        return scroll_area

    def apply_style(self):
        # Fusion 让自绘控件（滑块、微调框按钮）在各平台表现一致，
        # 面板本身的配色再交给属性样式表覆盖。
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        self.setStyleSheet(PROPERTY_PANEL_QSS)

    def create_navigation_tree(self):
        tree = QTreeWidget()
        tree.setObjectName("propNavTree")
        tree.setHeaderHidden(True)
        tree.setColumnCount(1)
        tree.setIndentation(8)
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tree.setFocusPolicy(Qt.NoFocus)
        tree.currentItemChanged.connect(self.on_navigation_changed)
        return tree

    # ------------------------------------------------------------------
    # 选中对象 → 分页
    # ------------------------------------------------------------------
    def update_for_selected(self, selected_obj):
        # 分页记忆按「对象类别」隔离：页面背景（场景）与图元各用一套记忆，
        # 避免场景页回退选中时把图元上次停留的分页冲掉。
        self._current_namespace = self._namespace_for(selected_obj)
        self._current_selected = selected_obj
        self._current_property_item = None
        # 重建分页时屏蔽导航树的自动选中，避免它把「上一次停留的页」覆盖成
        # 第一个分页；构建完成后再用保存的 key 恢复用户之前停留的位置。
        self._building_navigation = True
        try:
            self.navigation_tree.clear()
            self.clear_stacked_widget()
            self._populate_pages(selected_obj)
        finally:
            self._building_navigation = False
        self.select_preferred_page()
        self._refresh_header(selected_obj)

    def _namespace_for(self, selected_obj):
        if isinstance(selected_obj, myGraphicsScene):
            return "scene"
        return "element"

    def _populate_pages(self, selected_obj):
        if self.scene is not None and self.scene.mode() == SceneMode.Design:
            if isinstance(selected_obj, myGraphicsScene):
                self._show_scene_pages()
            elif isinstance(selected_obj, text_element):
                TextPropertyItem(item=selected_obj).add_navigation_items(self)
            elif isinstance(selected_obj, line_element):
                LinePropertyItem(item=selected_obj).add_navigation_items(self)
            elif isinstance(selected_obj, group_element):
                GroupPropertyItem(item=selected_obj).add_navigation_items(self)
            elif isinstance(selected_obj, polygon_element):
                PolygonPropertyItem(item=selected_obj).add_navigation_items(self)
            elif isinstance(selected_obj, triangle_element):
                TrianglePropertyItem(item=selected_obj).add_navigation_items(self)
            elif isinstance(selected_obj, checkbox_element):
                CheckboxPropertyItem(item=selected_obj).add_navigation_items(self)
            elif isinstance(selected_obj, widget_element):
                WidgetPropertyItem(item=selected_obj).add_navigation_items(self)
            elif isinstance(selected_obj, rect_element):
                RectPropertyItem(item=selected_obj).add_navigation_items(self)
            elif isinstance(selected_obj, circle_element):
                CirclePropertyItem(item=selected_obj).add_navigation_items(self)
            elif isinstance(selected_obj, image_element):
                ImagePropertyItem(item=selected_obj).add_navigation_items(self)
            elif isinstance(selected_obj, path_element):
                PathPropertyItem(item=selected_obj).add_navigation_items(self)
            else:
                self._show_empty_state(
                    "未选择图元",
                    "在画布上点选一个图元查看和编辑它的属性；点空白处可以编辑页面背景。",
                )
        else:
            if isinstance(selected_obj, group_element):
                CabinetPropertyItem(item=selected_obj).add_navigation_items(self)
                if self.content_stack.count() == 0:
                    self._show_empty_state(
                        "无可用配置",
                        "该分组没有对应的工位逻辑说明；选中名称里带电柜信息的分组再试。",
                    )
            else:
                self._show_empty_state(
                    "运行模式",
                    "运行模式下属性面板只显示工作站逻辑说明，选中对应的电柜分组即可查看。",
                )

    def _show_scene_pages(self):
        self.item = self.scene
        self.add_navigation_items()

    def _show_empty_state(self, title: str, hint: str) -> None:
        page = EmptyState(title, hint, self)
        scroll = QScrollArea()
        scroll.setObjectName("propPageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        self.content_stack.addWidget(scroll)

    def _refresh_header(self, selected_obj) -> None:
        if isinstance(selected_obj, myGraphicsScene):
            scene = selected_obj
            manager = getattr(scene, "scene_manager", None)
            count = len(manager.m_items) if manager is not None else 0
            self.header.set_object(
                "页",
                "页面背景",
                f"{scene.width()} x {scene.height()} 视图 · {count} 个图元",
            )
            return
        if isinstance(selected_obj, base_element):
            type_key = str(getattr(selected_obj, "type", "") or "")
            type_label = TYPE_LABELS.get(type_key, type_key or "图元")
            group_text = "未成组"
            if isinstance(selected_obj, group_element):
                group_text = f"{len(selected_obj.childItems())} 个成员"
            elif selected_obj.is_has_parent():
                parent = selected_obj.parentItem()
                if parent is not None:
                    group_text = f"组 {parent.get_name()}"
            self.header.set_object(
                GLYPHS.get(type_key, "图"),
                selected_obj.get_name(),
                f"{type_label} · ID {selected_obj.id()} · {group_text}",
            )
            return
        self.header.set_object("—", "未选择图元", "在画布上点选一个图元查看属性")

    # ------------------------------------------------------------------
    # 页面背景（场景自身）
    # ------------------------------------------------------------------
    def add_navigation_items(self):
        tree = self.navigation_tree
        for title, key in (("页面背景", "appearance"), ("画布设置", "canvas")):
            node = QTreeWidgetItem([title])
            node.setData(0, Qt.UserRole, key)
            tree.addTopLevelItem(node)

        self.create_content_pages()
        if not self._building_navigation:
            self.select_preferred_page()

    def create_content_pages(self):
        self.add_page("appearance", "页面背景", self.create_appearance_page())
        self.add_page("canvas", "画布设置", self.create_canvas_page())

    def create_appearance_page(self):
        page = PropertyPage()
        card = SectionCard("页面背景")

        current = self.item.get_bg_color() if self.item is not None else QColor("#ffffff")
        self.bg_color_btn = ColorField(current)
        self.bg_color_btn.colorChanged.connect(self._apply_bg_color)
        card.add_row(("背景色", self.bg_color_btn))
        card.add_hint("背景色会随页面一起保存，运行态沿用它作为画布底色。")
        page.add_card(card)
        return page

    def create_canvas_page(self):
        page = PropertyPage()
        scene = self.item

        grid_size = getattr(scene, "grid_size", 0) or 0
        units_x = getattr(scene, "scene_units_per_grid_x", 0) or 0
        units_y = getattr(scene, "scene_units_per_grid_y", 0) or 0
        scale = getattr(scene, "scale_factor", 1.0) or 1.0
        agv = bool(getattr(scene, "is_use_for_agv_map", False))

        view = SectionCard("视图")
        view.add_row(
            ("画布尺寸", make_value_label(f"{scene.width()} x {scene.height()}")),
            ("缩放", make_value_label(f"{scale:.2f}x")),
        )
        view.add_row(
            ("虚线网格", make_value_label(f"{grid_size:.0f} px")),
            ("坐标系", make_value_label("AGV（x/y 互换）" if agv else "标准（Y 向上）")),
        )
        page.add_card(view)

        grid = SectionCard("比例尺")
        grid.add_row(
            ("每格 X", make_value_label(f"{units_x:g} 单位")),
            ("每格 Y", make_value_label(f"{units_y:g} 单位")),
        )
        grid.add_row(
            ("1 屏幕格", make_value_label(f"{units_x:g} x {units_y:g} 单位")),
            ("原点", make_value_label("画布中心")),
        )
        grid.add_hint(
            "比例尺决定场景单位与像素的换算，运行态必须与设计态一致；"
            "这里只读展示，避免改比例尺后历史坐标整体偏移。"
        )
        page.add_card(grid)

        stats = SectionCard("图元统计")
        items = []
        manager = getattr(scene, "scene_manager", None)
        if manager is not None:
            items = list(manager.m_items.values())
        groups = [item for item in items if isinstance(item, group_element)]
        top_level = [item for item in items if not item.is_has_parent()]
        stats.add_row(
            ("图元总数", make_value_label(str(len(items)))),
            ("组合组", make_value_label(str(len(groups)))),
        )
        stats.add_row(
            ("顶层图元", make_value_label(str(len(top_level)))),
            ("组内图元", make_value_label(str(len(items) - len(top_level)))),
        )
        page.add_card(stats)
        return page

    # ------------------------------------------------------------------
    # 导航与堆栈
    # ------------------------------------------------------------------
    def add_page(self, page_id, title, widget):
        scroll_widget = QScrollArea()
        scroll_widget.setObjectName("propPageScroll")
        scroll_widget.setWidget(widget)
        scroll_widget.setWidgetResizable(True)
        scroll_widget.setFrameShape(QFrame.NoFrame)
        # 导航按 objectName 匹配页面，这里必须保留页面标识
        scroll_widget.setObjectName(page_id)
        self.content_stack.addWidget(scroll_widget)

    def clear_stacked_widget(self):
        while self.content_stack.count() > 0:
            widget = self.content_stack.widget(0)
            self.content_stack.removeWidget(widget)
            widget.deleteLater()
        self.destory_current.emit()

    def on_navigation_changed(self, current, previous):
        if current is not None:
            page_id = current.data(0, Qt.UserRole)
            if page_id:
                for i in range(self.content_stack.count()):
                    if self.content_stack.widget(i).objectName() == page_id:
                        self.content_stack.setCurrentIndex(i)
                        # 构建期间（clear/addTopLevelItem 触发的自动选中）不记录停留页，
                        # 否则会把用户上次停留的位置覆盖成第一个分页。
                        if not self._building_navigation and not str(page_id).startswith("category_"):
                            self._last_page_keys[self._current_namespace] = page_id
                        return

    def select_preferred_page(self):
        """选中上一次停留的导航页，不存在时回退到第一项。"""

        preferred = self._last_page_keys.get(self._current_namespace)
        if preferred and self._select_navigation_key(preferred):
            return
        tree = self.navigation_tree
        if tree.topLevelItemCount() == 0:
            return
        first_category = tree.topLevelItem(0)
        if first_category.childCount() > 0:
            tree.setCurrentItem(first_category.child(0))
        else:
            tree.setCurrentItem(first_category)

    def _select_navigation_key(self, page_key):
        tree = self.navigation_tree
        for i in range(tree.topLevelItemCount()):
            category_item = tree.topLevelItem(i)
            if category_item.data(0, Qt.UserRole) == page_key and self._has_page(page_key):
                tree.setCurrentItem(category_item)
                return True
            for j in range(category_item.childCount()):
                child = category_item.child(j)
                if child.data(0, Qt.UserRole) == page_key and self._has_page(page_key):
                    tree.setCurrentItem(child)
                    return True
        return False

    def _has_page(self, page_key):
        for i in range(self.content_stack.count()):
            if self.content_stack.widget(i).objectName() == page_key:
                return True
        return False

    # ------------------------------------------------------------------
    # 图元几何变化 → 增量刷新
    # ------------------------------------------------------------------
    def on_item_geometry_changed(self, item):
        """场景里某个图元的几何变化后回调；只刷新当前选中图元的字段。"""

        if item is None or self._current_property_item is None:
            return
        if item is not self._current_selected:
            return
        self._current_property_item.refresh_geometry()

    # ------------------------------------------------------------------
    # 背景色
    # ------------------------------------------------------------------
    def _apply_bg_color(self, color: QColor) -> None:
        if self.item is None:
            return
        self.item.set_bg_color(color)
        self.item.update()
