"""图层 / 对象树 Dock。

旧 ``Designer`` 没有对象树（``NavigationContentWidget`` 里的 QTreeWidget 是
属性分页导航），这里按用户要求补一份：支持「图层顺序」与「分组树」两种
视图、名称过滤、选中双向联动、显隐 / 层级 / 删除 / 重命名右键动作。

树只发信号，不直接改场景；所有写操作由主窗口的 ``_do()`` 统一分发，
保证撤销栈与脏标记不会漏记。
"""

from __future__ import annotations

from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt, Signal
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
        # 可选的「先别同步」探针：主窗口传入视图的框选状态。框选期间每移动
        # 一格都会改选中，这棵树整表同步一次 ~20 ms，全屏拖一趟白烧三四百
        # 毫秒；主窗口松手后会再调一次 sync_selection，这里跳过即可。
        self._defer_probe = None
        # 记录「本树实际连过」的 (signal, slot)，换场景时只断这些。
        # 盲目 disconnect 未连接的槽会让 PySide6 打 RuntimeWarning。
        self._bound: list[tuple] = []

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
        # 换场景必须先解绑，否则旧场景的图元被编辑时还会回调到这棵树，
        # 而旧场景里的 QGraphicsItem 可能已经销毁（文档 D-6）。
        for sig, slot in self._bound:
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._bound = []
        self.scene = scene
        if scene is not None:
            fine = hasattr(scene, "structureChanged") and hasattr(scene, "itemChanged")
            pairs = []
            if fine:
                pairs.append((scene.structureChanged, self.refresh))
                pairs.append((scene.itemChanged, self.update_items))
            else:
                # 老 / 自定义场景只有粗信号，退回全量刷新
                pairs.append((scene.contentChanged, self.refresh))
            pairs.append((scene.selectionChanged, self.sync_selection))
            for sig, slot in pairs:
                sig.connect(slot)
                self._bound.append((sig, slot))
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

    def update_items(self, ids) -> None:
        """只重画 ``ids`` 对应的行（名称 / 显隐灰字），不整树 clear 重建。

        属性面板改一个字段、批量显隐、对齐移动都只走这里，避免每次编辑都
        重建 1618 个 QTreeWidgetItem。下列情况无法安全增量，退化到全量：
        有名称过滤、树还没建、ids 里出现新增 / 已删除的图元。
        """
        if self.scene is None or self._syncing:
            return
        wanted = {int(i) for i in (ids or ()) if i is not None}
        if not wanted:
            return
        if self.filter_edit.text().strip() or self.tree.topLevelItemCount() == 0:
            self.refresh()
            return
        nodes: dict[int, QTreeWidgetItem] = {}
        stack = [self.tree.topLevelItem(i)
                 for i in range(self.tree.topLevelItemCount())]
        while stack:
            node = stack.pop()
            stack.extend(node.child(i) for i in range(node.childCount()))
            raw = node.data(0, ID_ROLE)
            if raw is not None:
                nodes[int(raw)] = node
        if not wanted <= set(nodes):
            self.refresh()          # 有新增图元：结构变了
            return
        items: dict[int, object] = {}
        for iid in wanted:
            it = self.scene.find_item(iid)
            if it is None:
                self.refresh()      # 有图元被删：结构变了
                return
            items[iid] = it
        self.tree.blockSignals(True)
        try:
            for iid, it in items.items():
                node = nodes[iid]
                label = self._label(it)
                if it.get_visibility():
                    node.setText(0, label)
                    node.setData(0, Qt.ForegroundRole, None)
                else:
                    node.setText(0, label + "  （隐藏）")
                    node.setForeground(0, QColor("#999999"))
        finally:
            self.tree.blockSignals(False)

    def selected_ids(self) -> list[int]:
        return [int(n.data(0, ID_ROLE)) for n in self.tree.selectedItems()
                if n.data(0, ID_ROLE) is not None]

    def set_defer_probe(self, probe) -> None:
        """设置「现在先别同步选中」的探针（``() -> bool``），``None`` 表示不延迟。"""
        self._defer_probe = probe

    def sync_selection(self) -> None:
        if self.scene is None or self._syncing:
            return
        probe = self._defer_probe
        if probe is not None and probe():
            return
        wanted = {it.item_id for it in self.scene.selected_items()}
        # Qt 不允许选中隐藏（setVisible(False)）图元，scene.selectedItems() 会漏掉
        # 它们；若直接用它对树回灌，树里刚选中的隐藏节点会被清掉，导致用户再也
        # 右键不到「显示/隐藏」来恢复。这里把树当前选中的隐藏节点并入 wanted。
        selected = self.tree.selectedItems()
        for node in selected:
            raw = node.data(0, ID_ROLE)
            if raw is None:
                continue
            it = self.scene.find_item(int(raw))
            if it is not None and not it.get_visibility():
                wanted.add(it.item_id)
        # 幂等短路：树已经是目标集合就直接返回。主窗口的选中槽和本类的
        # selectionChanged 连接会把 sync_selection 调两次，第二次不该重做。
        current = {int(n.data(0, ID_ROLE)) for n in selected
                   if n.data(0, ID_ROLE) is not None}
        if current == wanted:
            return
        self._syncing = True
        self.tree.blockSignals(True)
        try:
            # 逐节点 setSelected 时 Qt 的 QItemSelectionModel 每次都要维护
            # 已有选中区间，1618 个节点实测 0.8s（近似 O(n²)），全选后一次
            # 同步就够呛。这里攒成一份 QItemSelection 一次性 select。
            batch = QItemSelection()
            stack = [self.tree.topLevelItem(i)
                     for i in range(self.tree.topLevelItemCount())]
            while stack:
                node = stack.pop()
                raw = node.data(0, ID_ROLE)
                if raw is not None and int(raw) in wanted:
                    index = self.tree.indexFromItem(node, 0)
                    if index.isValid():
                        batch.select(index, index)
                stack.extend(node.child(i) for i in range(node.childCount()))
            self.tree.selectionModel().select(
                batch, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        finally:
            self.tree.blockSignals(False)
            self._syncing = False

    # ------------------------------------------------------------------
    def _on_selection_changed(self) -> None:
        if self._syncing:
            return
        self.selectionRequested.emit(self.selected_ids())

    def _menu_target_ids(self, pos) -> list[int]:
        """右键菜单的目标：光标下的行优先，其次当前选中集合。

        Qt 右键不改选中，但用户预期「菜单作用于光标下的行」：若该行不在
        当前选中集合里（甚至什么都没选），静默把树选中改成它——否则右键
        组内的成员行时，菜单会作用于上一选中（比如整组），重命名改的
        是组名，成员看起来「改不动名」。静默（blockSignals）不发
        ``selectionRequested``；真正同步场景选中由 ``_do_tree_action`` 的
        ``_select_from_tree`` 完成。
        """
        node = self.tree.itemAt(pos)
        if node is not None and node.data(0, ID_ROLE) is not None:
            iid = int(node.data(0, ID_ROLE))
            if iid not in set(self.selected_ids()):
                index = self.tree.indexFromItem(node, 0)
                self.tree.blockSignals(True)
                try:
                    self.tree.selectionModel().select(
                        index, QItemSelectionModel.ClearAndSelect
                        | QItemSelectionModel.Rows)
                finally:
                    self.tree.blockSignals(False)
        return self.selected_ids()

    def _show_menu(self, pos) -> None:
        ids = self._menu_target_ids(pos)
        if not ids:
            return
        menu = QMenu(self)
        entries = (
            ("显示 / 隐藏", "toggle_visible"),
            ("锁定所选", "lock"), ("解锁所选", "unlock"),
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
