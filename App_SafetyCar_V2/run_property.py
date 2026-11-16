"""运行态属性面板的「分组说明」入口。

这里曾经写死了一条产线的工作站清单和 8 段安全逻辑文案（维修区、安全门、
上架、拣选、输送线、托盘、主电柜……），换个项目就得改框架源码。现在业务
内容全部搬到 :mod:`station_pages` 描述的 JSON 里，本模块只负责：

1. 拿选中分组的名字去目录里查（`StationCatalog.match`）；
2. 命中就把页签挂到导航树上、把每页挂到内容栈里；
3. 没命中就安静退出，由调用方显示"无可用配置"的空状态。

目录由 :class:`~NavigationContentWidget.NavigationContentWidget` 在构造时
注入（见 ``station_catalog`` 参数），框架层因此不认识任何产线名词。
"""

from __future__ import annotations

from typing import Any, Protocol

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from .station_pages import StationCatalog, StationPage, build_station_page


class NavigationHost(Protocol):
    """run_property 用到的最小导航容器接口。

    NavigationContentWidget 反过来会 import 本模块，直接互相 import 会成环，
    所以这里只声明用到的成员，由 NavigationContentWidget 结构化匹配。
    """

    navigation_tree: QTreeWidget
    _building_navigation: bool
    # QObject 信号实例，具体类型由实现方决定
    destory_current: Any

    def add_page(self, page_id: str, title: str, widget: QWidget) -> None: ...

    def select_preferred_page(self) -> None: ...


class CabinetPropertyItem(QObject):
    """运行态：按分组名展示对应的若干说明页。

    分组对象用鸭子类型（``TYPE == "group"`` + ``get_name()``）——DesignerV2 的
    图元门面不是旧 ``Designer.Core.elements.group_element`` 的实例，这里不再
    依赖具体类。
    """

    item: Any
    navi: NavigationHost | None
    catalog: StationCatalog | None

    def __init__(
        self,
        parent: QObject | None = None,
        item: Any = None,
        catalog: StationCatalog | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.navi = None
        self.item = item
        self.catalog = catalog

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def pages(self) -> tuple[StationPage, ...]:
        """当前分组对应的页；无分组、无目录、未命中都返回空元组。"""
        if not self.item or not self.catalog:
            return ()
        return self.catalog.match(self.item.get_name())

    # ------------------------------------------------------------------
    # 导航
    # ------------------------------------------------------------------
    def add_navigation_items(self, navigation: NavigationHost) -> None:
        pages = self.pages()
        if not pages:
            # 未命中：不建树、不挂页，调用方会显示"无可用配置"
            return

        category_item = QTreeWidgetItem(["选择"])
        category_item.setData(0, Qt.UserRole, "category_select")
        navigation.navigation_tree.addTopLevelItem(category_item)
        category_item.setExpanded(True)

        for page in pages:
            child = QTreeWidgetItem([page.title])
            child.setData(0, Qt.UserRole, page.page_id)
            child.setFlags(child.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            category_item.addChild(child)

        self.create_content_pages(navigation, pages)
        self.navi = navigation

        # 设置选择行为
        navigation.navigation_tree.setSelectionMode(QTreeWidget.SingleSelection)
        navigation.navigation_tree.setSelectionBehavior(QTreeWidget.SelectItems)
        navigation.navigation_tree.setFocusPolicy(Qt.StrongFocus)

        # 必须重写mousePressEvent以确保正确触发selectionChanged信号
        # 可能是由于Qt内部事件处理或项目视图的默认行为问题
        navigation.navigation_tree.mousePressEvent = self.debug_mousePressEvent

        navigation.navigation_tree.itemSelectionChanged.connect(
            self.handle_itemSelectionChanged
        )

        if not navigation._building_navigation:
            navigation.select_preferred_page()

        navigation.destory_current.connect(self.on_destory_current)
        self.handle_itemSelectionChanged()

    def create_content_pages(
        self, navi: NavigationHost, pages: tuple[StationPage, ...]
    ) -> None:
        """把每页挂进内容栈。页面渲染本身在 :func:`build_station_page`。"""
        for page in pages:
            navi.add_page(page.page_id, page.title, build_station_page(page))

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def debug_mousePressEvent(self, event: QMouseEvent) -> None:
        """调试鼠标按下事件"""
        print(f"\n鼠标按下事件: {event.pos()}")
        item = self.navi.navigation_tree.itemAt(event.pos())
        if item:
            print(f"点击的项目: {item.text(0)}, 选中状态: {item.isSelected()}")
        else:
            print("未点击到项目")
        # 调用原始事件处理
        QTreeWidget.mousePressEvent(self.navi.navigation_tree, event)

    def handle_itemSelectionChanged(self) -> None:
        if not getattr(self, "navi", None) or not self.item:
            return

        current_item = self.navi.navigation_tree.currentItem()
        if not current_item:
            return

        text = current_item.text(0)
        scene = getattr(self.item, "m_scene", None)
        if scene is not None:
            scene.run_mode_station_change.emit(text)

    def on_destory_current(self) -> None:
        self.item = None
        self.navi.destory_current.disconnect(self.on_destory_current)
