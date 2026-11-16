"""运行态「站点说明」面板（原 ``Designer/Core/NavigationContentWidget.py`` 的运行态子集）。

为什么重写
----------
旧面板是设计器的属性编辑器：699 行里绝大部分是「按图元类型给出可编辑字段」，
拉着 ``elements`` / ``myPropertyForElement`` / ``property_widgets`` /
``myQuadTreeScene`` 一万多行旧设计器内核，而 DesignerV2 里这些都不存在。

安全车运行时**只用得上其中一条路**：运行模式下选中一个电柜分组，按
:mod:`station_pages` 的目录把该工位的说明页挂到左侧导航、渲染到右侧内容区。
所以这里把那条路单独实现出来：

====================================  ====================================
旧面板能力                             本文件
====================================  ====================================
``SceneMode.Design`` 下的分页属性编辑    ✗ 不做（运行态没有编辑入口）
运行态分组说明页（``CabinetPropertyItem``） ✓ 保留
顶部对象摘要（``ObjectHeader``）        ✓ 保留
导航树 + 内容栈 + 分页记忆               ✓ 保留（只记一个命名空间）
====================================  ====================================

对外接口刻意与旧类同名同签名（``NavigationContentWidget`` / ``update_for_selected``
/ ``add_page`` / ``select_preferred_page`` / ``destory_current``），
:class:`~App_SafetyCar_V2.run_property.CabinetPropertyItem` 的
``NavigationHost`` 协议无需任何改动。
"""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt, Signal
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

from .property_widgets import (
    PROPERTY_PANEL_QSS,
    EmptyState,
    ObjectHeader,
)
from .run_property import CabinetPropertyItem
from .station_pages import StationCatalog

#: 分组图元类型牌（顶部摘要左侧的方块）
_GLYPH_GROUP = "组"
_GLYPH_OTHER = "—"


def _is_group_like(obj: Any) -> bool:
    """是不是「电柜分组」。

    DesignerV2 的图元门面不是旧 ``group_element`` 实例，只能按 ``TYPE`` 标签判
    （适配层把新场景的 ``TYPE`` 透传出来，见 :meth:`base_element.TYPE`）。
    """
    return obj is not None and getattr(obj, "TYPE", "") == "group"


def _item_name(obj: Any) -> str:
    getter = getattr(obj, "get_name", None)
    if callable(getter):
        try:
            return str(getter() or "")
        except Exception:  # noqa: BLE001 - 适配层壳拿不到名字时不该炸面板
            return ""
    return ""


class NavigationContentWidget(QWidget):
    """运行态站点说明面板：左导航 + 右内容。"""

    destory_current = Signal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        scene: Any = None,
        station_catalog: Optional[StationCatalog] = None,
    ) -> None:
        super().__init__(parent)
        # 目录由调用方注入（业务数据在 cfg/station_pages.json）；不传就是空目录，
        # 选中分组时显示「无可用配置」，不报错。
        self.station_catalog = station_catalog
        self.scene = scene
        self.item = scene
        self._building_navigation = False
        self._current_namespace = "run"
        self._last_page_keys: dict[str, str] = {}
        self.setObjectName("designPropertyPanel")

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

        self.apply_style()
        self.update_for_selected(None)

    # ------------------------------------------------------------------
    # 布局
    # ------------------------------------------------------------------
    def create_navigation_scroll(self) -> QScrollArea:
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

    def create_content_scroll(self) -> QScrollArea:
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

    def apply_style(self) -> None:
        # Fusion 让自绘控件（滑块、微调框按钮）在各平台表现一致，
        # 面板配色由属性样式表覆盖（与旧面板同一份 QSS）。
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        self.setStyleSheet(PROPERTY_PANEL_QSS)

    def create_navigation_tree(self) -> QTreeWidget:
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
    # 选中对象 -> 分页
    # ------------------------------------------------------------------
    def update_for_selected(self, selected_obj: Any) -> None:
        """选中对象变了就重建分页（运行态只认「分组」）。"""
        self._current_selected = selected_obj
        self.item = selected_obj
        self._building_navigation = True
        try:
            self.navigation_tree.clear()
            self.clear_stacked_widget()
            self._populate_pages(selected_obj)
        finally:
            self._building_navigation = False
        self.select_preferred_page()
        self._refresh_header(selected_obj)

    def _populate_pages(self, selected_obj: Any) -> None:
        if _is_group_like(selected_obj):
            CabinetPropertyItem(
                item=selected_obj,
                catalog=self.station_catalog,
            ).add_navigation_items(self)
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

    def _show_empty_state(self, title: str, hint: str) -> None:
        page = EmptyState(title, hint, self)
        scroll = QScrollArea()
        scroll.setObjectName("propPageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        self.content_stack.addWidget(scroll)

    def _refresh_header(self, selected_obj: Any) -> None:
        if _is_group_like(selected_obj):
            name = _item_name(selected_obj) or "未命名分组"
            id_getter = getattr(selected_obj, "id", None)
            item_id = id_getter() if callable(id_getter) else "—"
            self.header.set_object(_GLYPH_GROUP, name, f"分组 · {item_id}")
            return
        self.header.set_object(_GLYPH_OTHER, "选择电柜分组", "")

    # ------------------------------------------------------------------
    # 分页（run_property 从这里挂页）
    # ------------------------------------------------------------------
    def add_page(self, page_id: str, title: str, widget: QWidget) -> None:
        scroll_widget = QScrollArea()
        scroll_widget.setObjectName(page_id)
        scroll_widget.setWidgetResizable(True)
        scroll_widget.setFrameShape(QFrame.NoFrame)
        scroll_widget.setWidget(widget)
        self.content_stack.addWidget(scroll_widget)

    def clear_stacked_widget(self) -> None:
        while self.content_stack.count() > 0:
            widget = self.content_stack.widget(0)
            self.content_stack.removeWidget(widget)
            widget.deleteLater()
        self.destory_current.emit()

    def on_navigation_changed(
        self,
        current: Optional[QTreeWidgetItem],
        previous: Optional[QTreeWidgetItem],
    ) -> None:
        if current is None:
            return
        page_id = current.data(0, Qt.UserRole)
        if not page_id:
            return
        for i in range(self.content_stack.count()):
            if self.content_stack.widget(i).objectName() == page_id:
                self.content_stack.setCurrentIndex(i)
                if not self._building_navigation and not str(page_id).startswith(
                        "category_"):
                    self._last_page_keys[self._current_namespace] = page_id
                return

    def select_preferred_page(self) -> None:
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

    def _select_navigation_key(self, page_key: str) -> bool:
        tree = self.navigation_tree
        for i in range(tree.topLevelItemCount()):
            category_item = tree.topLevelItem(i)
            if category_item.data(0, Qt.UserRole) == page_key:
                tree.setCurrentItem(category_item)
                return True
            for j in range(category_item.childCount()):
                child = category_item.child(j)
                if child.data(0, Qt.UserRole) == page_key:
                    tree.setCurrentItem(child)
                    return True
        return False


__all__ = ["NavigationContentWidget"]
