"""Left dock: page/scene management."""

from __future__ import annotations

from typing import Dict, Iterable, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .project_store import PageMeta


PAGE_ID_ROLE = Qt.UserRole
PAGE_NAME_ROLE = Qt.UserRole + 1
PAGE_COUNT_ROLE = Qt.UserRole + 2


class PageManagerDock(QDockWidget):
    """Lists pages and exposes the page CRUD commands as signals."""

    pageActivated = Signal(str)
    createPageRequested = Signal()
    duplicatePageRequested = Signal(str)
    renamePageRequested = Signal(str)
    deletePageRequested = Signal(str)
    movePageRequested = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__("页面 / 场景", parent)
        self.setObjectName("pageManagerDock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.setMinimumWidth(190)

        self._loading = False
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        container = QWidget(self)
        container.setObjectName("pageManagerContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        self.header_label = QLabel("页面", container)
        self.header_label.setObjectName("dockSectionTitle")
        self.count_label = QLabel("0", container)
        self.count_label.setObjectName("dockCountLabel")
        header_layout.addWidget(self.header_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.count_label)
        layout.addLayout(header_layout)

        separator = QFrame(container)
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        self.list_widget = QListWidget(container)
        self.list_widget.setObjectName("pageList")
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.currentItemChanged.connect(self._on_current_item_changed)
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list_widget, 1)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(3)
        self.new_button = self._make_button(container, "＋", "新建页面", self.createPageRequested.emit)
        self.duplicate_button = self._make_button(
            container, "⧉", "复制当前页面", self._request_duplicate
        )
        self.rename_button = self._make_button(
            container, "✎", "重命名当前页面", self._request_rename
        )
        self.delete_button = self._make_button(
            container, "−", "删除当前页面", self._request_delete
        )
        self.up_button = self._make_button(
            container, "↑", "上移页面", lambda: self._request_move(-1)
        )
        self.down_button = self._make_button(
            container, "↓", "下移页面", lambda: self._request_move(1)
        )
        for button in (
            self.new_button,
            self.duplicate_button,
            self.rename_button,
            self.delete_button,
            self.up_button,
            self.down_button,
        ):
            button_layout.addWidget(button)
        button_layout.addStretch(1)
        layout.addLayout(button_layout)

        hint = QLabel("双击重命名；设计内容会自动保存", container)
        hint.setObjectName("dockHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.setWidget(container)

    def _make_button(self, parent: QWidget, text: str, tooltip: str, slot) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName("pageToolButton")
        button.setText(text)
        button.setToolTip(tooltip)
        button.setFixedSize(QSize(30, 28))
        button.clicked.connect(lambda checked=False, fn=slot: fn())
        return button

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_pages(self, pages: Iterable[PageMeta], current_page_id: Optional[str] = None) -> None:
        pages = list(pages)
        self._loading = True
        try:
            self.list_widget.clear()
            for page in pages:
                item = QListWidgetItem()
                item.setData(PAGE_ID_ROLE, page.id)
                item.setData(PAGE_NAME_ROLE, page.name)
                item.setData(PAGE_COUNT_ROLE, 0)
                self._refresh_item_text(item)
                self.list_widget.addItem(item)

            self.count_label.setText(str(len(pages)))
            if current_page_id and self._find_item(current_page_id) is not None:
                self.set_current(current_page_id)
            elif pages:
                self.list_widget.setCurrentRow(0)
        finally:
            self._loading = False

    def set_current(self, page_id: str) -> None:
        item = self._find_item(page_id)
        if item is None:
            return
        if self.list_widget.currentItem() is item:
            return
        previous = self._loading
        self._loading = True
        try:
            self.list_widget.setCurrentItem(item)
        finally:
            self._loading = previous

    def current_page_id(self) -> Optional[str]:
        item = self.list_widget.currentItem()
        return item.data(PAGE_ID_ROLE) if item is not None else None

    def update_counts(self, counts: Dict[str, int]) -> None:
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            page_id = item.data(PAGE_ID_ROLE)
            count = counts.get(page_id, item.data(PAGE_COUNT_ROLE) or 0)
            item.setData(PAGE_COUNT_ROLE, count)
            self._refresh_item_text(item)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _find_item(self, page_id: str) -> Optional[QListWidgetItem]:
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.data(PAGE_ID_ROLE) == page_id:
                return item
        return None

    def _refresh_item_text(self, item: QListWidgetItem) -> None:
        name = item.data(PAGE_NAME_ROLE) or item.data(PAGE_ID_ROLE)
        count = item.data(PAGE_COUNT_ROLE) or 0
        item.setText(f"{name}\n{count} 个图元")
        item.setSizeHint(QSize(0, 48))
        item.setToolTip(f"{name}（{count} 个图元）")

    def _on_current_item_changed(
        self, current: Optional[QListWidgetItem], previous: Optional[QListWidgetItem]
    ) -> None:
        if self._loading or current is None:
            return
        page_id = current.data(PAGE_ID_ROLE)
        if page_id:
            self.pageActivated.emit(page_id)


    def _request_duplicate(self) -> None:
        page_id = self.current_page_id()
        if page_id:
            self.duplicatePageRequested.emit(page_id)

    def _request_rename(self) -> None:
        page_id = self.current_page_id()
        if page_id:
            self.renamePageRequested.emit(page_id)

    def _request_delete(self) -> None:
        page_id = self.current_page_id()
        if page_id:
            self.deletePageRequested.emit(page_id)

    def _request_move(self, delta: int) -> None:
        page_id = self.current_page_id()
        if page_id:
            self.movePageRequested.emit(page_id, delta)

    def _show_context_menu(self, pos) -> None:
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        self.list_widget.setCurrentItem(item)
        page_id = item.data(PAGE_ID_ROLE)

        menu = QMenu(self)
        menu.addAction("新建页面", lambda: self.createPageRequested.emit())
        menu.addAction("复制页面", lambda: self.duplicatePageRequested.emit(page_id))
        menu.addAction("重命名", lambda: self.renamePageRequested.emit(page_id))
        menu.addAction("删除", lambda: self.deletePageRequested.emit(page_id))
        menu.addSeparator()
        menu.addAction("上移", lambda: self.movePageRequested.emit(page_id, -1))
        menu.addAction("下移", lambda: self.movePageRequested.emit(page_id, 1))
        menu.exec(self.list_widget.viewport().mapToGlobal(pos))

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        page_id = item.data(PAGE_ID_ROLE)
        if page_id:
            self.renamePageRequested.emit(page_id)

