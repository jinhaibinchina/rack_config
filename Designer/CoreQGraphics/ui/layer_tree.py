"""图层 / 对象树 Dock。

旧 ``Designer`` 没有对象树（``NavigationContentWidget`` 里的 QTreeWidget 是
属性分页导航），这里按用户要求补一份：支持「图层顺序」与「分组树」两种
视图、名称过滤、选中双向联动、显隐 / 层级 / 删除 / 重命名右键动作。

树只发信号，不直接改场景；所有写操作由主窗口的 ``_do()`` 统一分发，
保证撤销栈与脏标记不会漏记。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDockWidget, QHBoxLayout, QLineEdit, QMenu, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..g_scene import TYPE_LABELS

ID_ROLE = Qt.UserRole


class LayerTreeDock(QDockWidget):
    selectionRequested = Signal(object)      # list[int]
    actionRequested = Signal(str, object)    # (action, list[int])

    def __init__(self, parent=None) -> None:
        super().__init__("图层 / 对象", parent)
        self.setObjectName("coreQgLayers")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.scene = None
        self._syncing = False

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        top = QHBoxLayout()
        self.mode_box = QComboBox(root)
        self.mode_box.addItems(("图层顺序", "分组树"))
        self.mode_box.currentIndexChanged.connect(self.refresh)
        self.filter_edit = QLineEdit(root)
        self.filter_edit.setPlaceholderText("按名称过滤…")
        self.filter_edit.textChanged.connect(self.refresh)
        top.addWidget(self.mode_box, 1)
        top.addWidget(self.filter_edit, 2)
        layout.addLayout(top)

        self.tree = QTreeWidget(root)
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.customContextMenuRequested.connect(self._show_menu)
        layout.addWidget(self.tree, 1)
        self.setWidget(root)
        self.setMinimumWidth(200)

    # ------------------------------------------------------------------
    def set_scene(self, scene) -> None:
        self.scene = scene
        if scene is not None:
            scene.contentChanged.connect(self.refresh)
            scene.selectionChanged.connect(self.sync_selection)
        self.refresh()

    def _label(self, item) -> str:
        return f"{item.get_name()}   [{TYPE_LABELS.get(item.TYPE, item.TYPE)}]"

    def refresh(self) -> None:
        if self.scene is None or self._syncing:
            return
        scene = self.scene
        keyword = self.filter_edit.text().strip().lower()
        self.tree.blockSignals(True)
        self.tree.clear()
        nodes: dict[int, QTreeWidgetItem] = {}
        grouped = self.mode_box.currentIndex() == 1

        if grouped:
            sequence = scene.all_items()
        else:
            # 图层顺序：顶层图元显示在前
            sequence = list(reversed(scene.sorted_items()))
        pending = [it for it in sequence
                   if not keyword or keyword in it.get_name().lower()]

        def attach(item) -> QTreeWidgetItem:
            iid = item.item_id
            if iid in nodes:
                return nodes[iid]
            node = QTreeWidgetItem([self._label(item)])
            node.setData(0, ID_ROLE, iid)
            if not item.get_visibility():
                node.setForeground(0, QColor("#999999"))
                node.setText(0, self._label(item) + "  （隐藏）")
            nodes[iid] = node
            parent = None
            if grouped and item.parent_id:
                parent_item = scene.find_item(item.parent_id)
                if parent_item is not None and parent_item in pending:
                    parent = attach(parent_item)
            if parent is None:
                self.tree.addTopLevelItem(node)
            else:
                parent.addChild(node)
            return node

        for it in pending:
            node = attach(it)
            node.setExpanded(True)
        self.tree.blockSignals(False)
        self.sync_selection()

    def selected_ids(self) -> list[int]:
        return [int(n.data(0, ID_ROLE)) for n in self.tree.selectedItems()
                if n.data(0, ID_ROLE) is not None]

    def sync_selection(self) -> None:
        if self.scene is None or self._syncing:
            return
        wanted = {it.item_id for it in self.scene.selected_items()}
        # Qt 不允许选中隐藏（setVisible(False)）图元，scene.selectedItems() 会漏掉
        # 它们；若直接用它对树回灌，树里刚选中的隐藏节点会被清掉，导致用户再也
        # 右键不到「显示/隐藏」来恢复。这里把树当前选中的隐藏节点并入 wanted。
        for node in self.tree.selectedItems():
            raw = node.data(0, ID_ROLE)
            if raw is None:
                continue
            it = self.scene.find_item(int(raw))
            if it is not None and not it.get_visibility():
                wanted.add(it.item_id)
        self._syncing = True
        self.tree.blockSignals(True)
        try:
            stack = [self.tree.topLevelItem(i)
                     for i in range(self.tree.topLevelItemCount())]
            while stack:
                node = stack.pop()
                node.setSelected(int(node.data(0, ID_ROLE)) in wanted)
                stack.extend(node.child(i) for i in range(node.childCount()))
        finally:
            self.tree.blockSignals(False)
            self._syncing = False

    # ------------------------------------------------------------------
    def _on_selection_changed(self) -> None:
        if self._syncing:
            return
        self.selectionRequested.emit(self.selected_ids())

    def _show_menu(self, pos) -> None:
        ids = self.selected_ids()
        if not ids:
            return
        menu = QMenu(self)
        entries = (
            ("显示 / 隐藏", "toggle_visible"),
            ("移到最前", "z_front"), ("上移一层", "z_raise"),
            ("下移一层", "z_lower"), ("移到最后", "z_back"),
            (None, None),
            ("重命名…", "rename"), ("复制", "duplicate"), ("删除", "delete"),
        )
        for label, key in entries:
            if label is None:
                menu.addSeparator()
                continue
            action = menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, k=key, v=list(ids):
                    self.actionRequested.emit(k, v)
            )
        menu.exec(self.tree.viewport().mapToGlobal(pos))
