"""Standalone design-mode main window."""

from __future__ import annotations

if __name__ == "__main__" and not __package__:
    # ``python modes/design/design_window.py`` puts this folder (not the
    # project root) on sys.path, and the package-relative imports below need a
    # parent package.  Delegate to the documented entry point instead of
    # duplicating its QApplication setup here.
    import os
    import sys

    _PROJECT_ROOT = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
    from design_main import main as _design_main

    raise SystemExit(_design_main())

import json
from typing import Dict, Optional

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDockWidget,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QToolBar,
)

from Designer.Core.NavigationContentWidget import NavigationContentWidget
# from my_elements_v2 import base_element, group_element
from Designer.Core.element import base_element
from Designer.Core.elements import group_element
from .design_page import DesignPage
from .element_factory import TOOL_DEFINITIONS_BY_KEY
from .element_toolbox_dock import ElementToolboxDock
from .offline_run_dialog import OfflineRunDialog
from .page_manager_dock import PageManagerDock
from .project_store import PageMeta, ProjectStore
from .template_store import TemplateStore, create_template_instance


class DesignWindow(QMainWindow):
    """Design-mode shell: page list, canvas stack, toolbox and properties."""

    def __init__(self, project_root: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("安全车配置 · 设计模式")
        self.resize(1600, 1000)
        self.setDockNestingEnabled(True)

        # QuadTreeScene expects this exact attribute name on its parent.
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("正在加载设计项目…")

        self.project_store = ProjectStore(project_root)
        self.template_store = TemplateStore(self.project_store.design_dir)
        self.pages: Dict[str, DesignPage] = {}
        self.current_page: Optional[DesignPage] = None
        self.property_panel: Optional[NavigationContentWidget] = None
        self.property_dock: Optional[QDockWidget] = None
        self._switching_page = False
        self._page_count_cache: Dict[str, int] = {}

        self.stack = QStackedWidget(self)
        self.stack.setObjectName("designPageStack")
        self.setCentralWidget(self.stack)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_status_widgets()
        self._build_docks()
        self._connect_dock_signals()
        self._apply_style()

        self._reload_page_dock()
        initial_page_id = self.project_store.current_page_id
        if initial_page_id is None and self.project_store.pages:
            initial_page_id = self.project_store.pages[0].id
        if initial_page_id:
            self.activate_page(initial_page_id)

        self._update_grid_actions()
        self._update_status()
        self._update_selection_actions()
        self._update_history_actions()

    # ------------------------------------------------------------------
    # Actions / menus / toolbar
    # ------------------------------------------------------------------
    def _make_action(self, text, slot, shortcut=None, checkable=False) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(shortcut)
        if checkable:
            action.setCheckable(True)
            action.triggered.connect(slot)
        else:
            action.triggered.connect(lambda checked=False, fn=slot: fn())
        return action

    def _make_arrange_action(self, text, method_name, tooltip) -> QAction:
        """Create one alignment/distribution command for the current page."""

        action = self._make_action(
            text,
            lambda name=method_name, label=text: self.apply_arrangement(name, label),
        )
        action.setToolTip(tooltip)
        return action

    def _build_actions(self) -> None:
        self.new_page_action = self._make_action("新建页面", self._create_page, "Ctrl+N")
        self.save_action = self._make_action("保存当前页面", self.save_current_page, "Ctrl+S")
        self.save_all_action = self._make_action(
            "保存全部页面", self.save_all_pages, "Ctrl+Shift+S"
        )
        self.quit_action = self._make_action("退出", self.close, "Ctrl+Q")

        # Undo/redo.  Like copy/paste/delete their key bindings live in
        # DesignScene.keyPressEvent so they never steal Ctrl+Z / Ctrl+Y from
        # the property-panel text editors.
        self.undo_action = self._make_action("撤销", self.undo)
        self.undo_action.setToolTip("撤销上一步编辑（画布内 Ctrl+Z）")
        self.undo_action.setEnabled(False)
        self.redo_action = self._make_action("重做", self.redo)
        self.redo_action.setToolTip("重做被撤销的编辑（画布内 Ctrl+Shift+Z / Ctrl+Y）")
        self.redo_action.setEnabled(False)

        # Clipboard and Delete shortcuts live in DesignScene.keyPressEvent so
        # they do not steal keys from property-panel text editors.
        self.copy_action = self._make_action("复制", self.copy_selected)
        self.paste_action = self._make_action("粘贴", self.paste_clipboard)
        self.delete_selected_action = self._make_action("删除所选图元", self.delete_selected)
        self.select_all_action = self._make_action("全选", self.select_all)
        self.save_template_action = self._make_action(
            "将所选组添加到工具箱…", self.save_selected_group_as_template
        )
        self.save_template_action.setToolTip("把选中的组保存为可复用的组合模板")

        # Arrangement commands.  The geometry helpers live on QuadTreeScene and
        # work in the scene's AGV-map coordinate frame, which is why e.g. the
        # left/right alignment helpers adjust the scene Y coordinate.
        self.align_left_action = self._make_arrange_action(
            "左对齐",
            "left_alignment_for_selected",
            "把所选图元的左边缘对齐（需选中至少两个图元）",
        )
        self.align_right_action = self._make_arrange_action(
            "右对齐",
            "right_alignment_for_selected",
            "把所选图元的右边缘对齐（需选中至少两个图元）",
        )
        self.align_top_action = self._make_arrange_action(
            "上对齐",
            "top_alignment_for_selected",
            "把所选图元的上边缘对齐（需选中至少两个图元）",
        )
        self.align_bottom_action = self._make_arrange_action(
            "下对齐",
            "bottom_alignment_for_selected",
            "把所选图元的下边缘对齐（需选中至少两个图元）",
        )
        self.distribute_h_action = self._make_arrange_action(
            "水平等距",
            "set_same_horizontal_distance",
            "让所选图元在水平方向等间距排列（需选中至少两个图元）",
        )
        self.distribute_v_action = self._make_arrange_action(
            "垂直等距",
            "set_same_vertical_distance",
            "让所选图元在垂直方向等间距排列（需选中至少两个图元）",
        )
        self.arrange_actions = (
            self.align_left_action,
            self.align_right_action,
            self.align_top_action,
            self.align_bottom_action,
            self.distribute_h_action,
            self.distribute_v_action,
        )

        self.grid_action = self._make_action(
            "显示网格", self._toggle_grid, checkable=True
        )
        self.grid_action.setChecked(True)
        self.coord_action = self._make_action(
            "显示坐标", self._toggle_coordinate, checkable=True
        )
        self.coord_action.setChecked(True)
        self.background_action = self._make_action(
            "页面背景色…", self.choose_background_color
        )
        self.background_action.setToolTip(
            "设置当前页面的背景颜色，并随页面 JSON 一起保存"
        )
        self.home_action = self._make_action("调整视图", self.reset_view, "Ctrl+0")
        self.home_action.setToolTip("恢复到页面 sceneRect 记录的视图大小（Ctrl+0）")
        self.offline_run_action = self._make_action(
            "离线运行", self.open_offline_run
        )
        self.offline_run_action.setToolTip(
            "在运行模式下离线预览当前主场景，不连接 PLC 与数据总线"
        )

        self.duplicate_page_action = self._make_action(
            "复制页面", self._duplicate_current_page, "Ctrl+Shift+D"
        )
        self.rename_page_action = self._make_action(
            "重命名页面…", self._rename_current_page, "F2"
        )
        self.delete_page_action = self._make_action(
            "删除页面…", self._delete_current_page
        )
        self.move_page_up_action = self._make_action(
            "页面上移", lambda: self._move_page(self._current_page_id(), -1)
        )
        self.move_page_down_action = self._make_action(
            "页面下移", lambda: self._move_page(self._current_page_id(), 1)
        )
        self.about_action = self._make_action("关于", self.show_about)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(self.new_page_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_all_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        edit_menu = self.menuBar().addMenu("编辑")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.copy_action)
        edit_menu.addAction(self.paste_action)
        edit_menu.addAction(self.delete_selected_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.select_all_action)
        arrange_menu = edit_menu.addMenu("排列")
        arrange_menu.addAction(self.align_left_action)
        arrange_menu.addAction(self.align_right_action)
        arrange_menu.addAction(self.align_top_action)
        arrange_menu.addAction(self.align_bottom_action)
        arrange_menu.addSeparator()
        arrange_menu.addAction(self.distribute_h_action)
        arrange_menu.addAction(self.distribute_v_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.save_template_action)

        page_menu = self.menuBar().addMenu("页面")
        page_menu.addAction(self.new_page_action)
        page_menu.addAction(self.duplicate_page_action)
        page_menu.addAction(self.rename_page_action)
        page_menu.addAction(self.delete_page_action)
        page_menu.addSeparator()
        page_menu.addAction(self.move_page_up_action)
        page_menu.addAction(self.move_page_down_action)

        view_menu = self.menuBar().addMenu("视图")
        view_menu.addAction(self.grid_action)
        view_menu.addAction(self.coord_action)
        view_menu.addAction(self.background_action)
        view_menu.addSeparator()
        view_menu.addAction(self.home_action)

        run_menu = self.menuBar().addMenu("运行")
        run_menu.addAction(self.offline_run_action)

        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction(self.about_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("设计工具", self)
        toolbar.setObjectName("mainToolBar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        toolbar.addAction(self.new_page_action)
        toolbar.addAction(self.save_action)
        toolbar.addSeparator()
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)
        toolbar.addSeparator()
        toolbar.addAction(self.copy_action)
        toolbar.addAction(self.paste_action)
        toolbar.addAction(self.delete_selected_action)
        toolbar.addSeparator()
        for action in self.arrange_actions:
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self.grid_action)
        toolbar.addAction(self.coord_action)
        toolbar.addAction(self.home_action)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

    def _build_status_widgets(self) -> None:
        self.mode_label = QLabel("设计模式", self.status_bar)
        self.mode_label.setObjectName("statusModeLabel")
        self.project_label = QLabel(self.project_store.design_dir, self.status_bar)
        self.project_label.setObjectName("statusPathLabel")
        self.status_bar.addPermanentWidget(self.mode_label)
        self.status_bar.addPermanentWidget(self.project_label)


    # ------------------------------------------------------------------
    # Docks
    # ------------------------------------------------------------------
    def _build_docks(self) -> None:
        self.page_dock = PageManagerDock(self)
        self.toolbox_dock = ElementToolboxDock(self)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.page_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.toolbox_dock)
        self.resizeDocks([self.page_dock], [220], Qt.Horizontal)
        self.resizeDocks([self.toolbox_dock], [210], Qt.Horizontal)
        self.toolbox_dock.set_templates(self.template_store.templates)

    def _build_property_dock(self) -> None:
        if self.property_panel is not None:
            return
        scene = self.current_page.scene if self.current_page else None
        if scene is None:
            return

        self.property_panel = NavigationContentWidget(scene=scene, parent=self)
        self.property_panel.setObjectName("designPropertyPanel")
        self.property_dock = QDockWidget("属性", self)
        self.property_dock.setObjectName("designPropertyDock")
        self.property_dock.setAllowedAreas(
            Qt.BottomDockWidgetArea | Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
        )
        self.property_dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.property_dock.setWidget(self.property_panel)
        self.property_dock.setMinimumHeight(190)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.property_dock)
        self.resizeDocks([self.property_dock], [250], Qt.Vertical)
        self._update_property_panel(scene)

    def _connect_dock_signals(self) -> None:
        self.page_dock.pageActivated.connect(self._on_page_activated)
        self.page_dock.createPageRequested.connect(self._create_page)
        self.page_dock.duplicatePageRequested.connect(self._duplicate_page)
        self.page_dock.renamePageRequested.connect(self._rename_page)
        self.page_dock.deletePageRequested.connect(self._delete_page)
        self.page_dock.movePageRequested.connect(self._move_page)
        self.toolbox_dock.toolActivated.connect(self.begin_tool_draw)
        self.toolbox_dock.templateActivated.connect(self.add_template_at_view_center)
        self.toolbox_dock.captureGroupRequested.connect(
            self.save_selected_group_as_template
        )
        self.toolbox_dock.templateRenameRequested.connect(self._rename_template)
        self.toolbox_dock.templateDeleteRequested.connect(self._delete_template)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background-color: #f3f4f6; }
            QMenuBar { background: #ffffff; border-bottom: 1px solid #e5e7eb; }
            QMenuBar::item { padding: 5px 10px; }
            QMenuBar::item:selected { background: #e0f2fe; }
            QMenu { background: #ffffff; border: 1px solid #d1d5db; padding: 4px; }
            QMenu::item { padding: 5px 22px 5px 12px; }
            QMenu::item:selected { background: #dbeafe; color: #1d4ed8; }
            QToolBar#mainToolBar {
                background: #ffffff;
                border-bottom: 1px solid #e5e7eb;
                spacing: 3px;
                padding: 4px 6px;
            }
            QToolBar#mainToolBar QToolButton {
                padding: 5px 10px;
                border-radius: 5px;
                color: #374151;
            }
            QToolBar#mainToolBar QToolButton:hover { background: #eff6ff; }
            QToolBar#mainToolBar QToolButton:checked {
                background: #dbeafe;
                color: #1d4ed8;
            }
            QDockWidget { color: #111827; }
            QDockWidget::title {
                background: #e5e7eb;
                padding: 7px 10px;
                border-bottom: 1px solid #d1d5db;
            }
            QLabel#dockSectionTitle { font-size: 14px; font-weight: 600; color: #111827; }
            QLabel#dockCountLabel {
                background: #dbeafe;
                color: #1d4ed8;
                border-radius: 9px;
                padding: 1px 8px;
                font-weight: 600;
            }
            QLabel#dockHint { color: #6b7280; font-size: 11px; }
            QListWidget#pageList {
                background: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                padding: 3px;
            }
            QListWidget#pageList::item {
                padding: 5px 8px;
                border-radius: 4px;
                color: #374151;
            }
            QListWidget#pageList::item:selected { background: #dbeafe; color: #1d4ed8; }
            QListWidget#pageList::item:hover { background: #eff6ff; }
            QToolButton#pageToolButton {
                background: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 5px;
                font-size: 15px;
                color: #374151;
            }
            QToolButton#pageToolButton:hover {
                background: #eff6ff;
                border-color: #93c5fd;
            }
            QPushButton#ElementToolButton {
                text-align: left;
                padding: 5px 10px;
                background: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 6px;
                font-size: 13px;
                color: #1f2937;
            }
            QPushButton#ElementToolButton:hover {
                background: #eff6ff;
                border-color: #93c5fd;
            }
            QPushButton#ElementToolButton:pressed { background: #dbeafe; }
            QPushButton#TemplateToolButton {
                text-align: left;
                padding: 5px 10px;
                background: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-size: 13px;
                color: #1f2937;
            }
            QPushButton#TemplateToolButton:hover {
                background: #eff6ff;
                border-color: #60a5fa;
            }
            QPushButton#TemplateToolButton:pressed { background: #dbeafe; }
            QPushButton#TemplateCaptureButton {
                padding: 6px 10px;
                background: #2563eb;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                font-weight: 600;
            }
            QPushButton#TemplateCaptureButton:hover { background: #1d4ed8; }
            QPushButton#TemplateCaptureButton:pressed { background: #1e40af; }
            QPushButton#TemplateCaptureButton:disabled {
                background: #cbd5e1;
                color: #f8fafc;
            }
            QLabel#templateHint { color: #6b7280; font-size: 11px; }
            QGroupBox#toolboxGroup {
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                margin-top: 8px;
                font-weight: 600;
                color: #374151;
            }
            QGroupBox#toolboxGroup::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                background: #f3f4f6;
            }
            QStatusBar { background: #ffffff; border-top: 1px solid #e5e7eb; color: #4b5563; }
            QStatusBar QLabel { color: #6b7280; padding: 0 6px; }
            """
        )

    # ------------------------------------------------------------------
    # Page lifecycle
    # ------------------------------------------------------------------
    def _reload_page_dock(self, current_page_id: Optional[str] = None) -> None:
        if current_page_id is None:
            if self.current_page is not None:
                current_page_id = self.current_page.meta.id
            else:
                current_page_id = self.project_store.current_page_id
        self.page_dock.set_pages(self.project_store.pages, current_page_id)
        self._refresh_page_counts()

    def _refresh_page_counts(self) -> None:
        counts = {}
        for page in self.project_store.pages:
            loaded_page = self.pages.get(page.id)
            if loaded_page is not None:
                count = loaded_page.item_count
                self._page_count_cache[page.id] = count
            else:
                count = self._page_count_cache.get(page.id)
                if count is None:
                    count = self._read_page_item_count(page)
                    self._page_count_cache[page.id] = count
            counts[page.id] = count
        self.page_dock.update_counts(counts)

    def _read_page_item_count(self, page: PageMeta) -> int:
        try:
            with open(self.project_store.page_path(page), "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return len(data.get("items", []))
        except (OSError, ValueError, TypeError):
            return 0

    def _on_item_count_changed(self, page_id: str, count: int) -> None:
        self._page_count_cache[page_id] = count
        self._refresh_page_counts()
        if self.current_page is not None and self.current_page.meta.id == page_id:
            self._update_status()

    def activate_page(self, page_id: str) -> bool:
        if self._switching_page:
            return False
        meta = self.project_store.get_page(page_id)
        if meta is None:
            return False
        if self.current_page is not None and self.current_page.meta.id == page_id:
            self.page_dock.set_current(page_id)
            return True

        self._switching_page = True
        try:
            page = self.pages.get(page_id)
            if page is None:
                page = DesignPage(meta, self.project_store, parent=self)
                try:
                    page.load()
                except Exception as exc:
                    page.dispose()
                    print(f"页面加载失败({page_id}): {exc}")
                    QMessageBox.critical(
                        self,
                        "页面加载失败",
                        f"无法读取页面“{meta.name}”：\n{exc}",
                    )
                    if self.current_page is not None:
                        self.page_dock.set_current(self.current_page.meta.id)
                    return False

                page.scene.selectionChanged.connect(self._on_scene_selection_changed)
                page.scene.templateDropped.connect(self._on_template_dropped)
                page.scene.groupTemplateRequested.connect(
                    self._capture_group_as_template
                )
                page.scene.undoRequested.connect(self.undo)
                page.scene.redoRequested.connect(self.redo)
                page.history.changed.connect(self._update_history_actions)
                page.itemCountChanged.connect(self._on_item_count_changed)
                self.pages[page_id] = page
                self.stack.addWidget(page.scene)

            if self.current_page is not None:
                self._save_page(self.current_page)
                self.current_page.deactivate()

            page.meta = meta
            self.current_page = page
            self.stack.setCurrentWidget(page.scene)
            page.activate()

            self.project_store.set_current_page(page_id)
            self.page_dock.set_current(page_id)
            self._update_grid_actions()
            self._update_property_panel(page.scene)
            self._refresh_page_counts()
            self._update_status()
            self._update_selection_actions()
            self._update_history_actions()
            return True
        finally:
            self._switching_page = False

    def _on_page_activated(self, page_id: str) -> None:
        if self.current_page is not None and self.current_page.meta.id == page_id:
            return
        if not self.activate_page(page_id) and self.current_page is not None:
            self.page_dock.set_current(self.current_page.meta.id)

    def _save_page(self, page: DesignPage, silent: bool = False) -> bool:
        try:
            page.save()
            return True
        except Exception as exc:
            print(f"页面保存失败({page.meta.id}): {exc}")
            if not silent:
                QMessageBox.warning(
                    self,
                    "保存失败",
                    f"页面“{page.meta.name}”保存失败：\n{exc}",
                )
            return False

    def save_current_page(self) -> None:
        if self.current_page is None:
            return
        if self._save_page(self.current_page):
            self.status_bar.showMessage(f"已保存：{self.current_page.meta.name}", 3000)

    def save_all_pages(self) -> None:
        saved = 0
        failed = 0
        for page in self.pages.values():
            if self._save_page(page, silent=True):
                saved += 1
            else:
                failed += 1
        try:
            self.project_store.save_project()
        except OSError as exc:
            failed += 1
            print(f"保存工程文件失败: {exc}")

        if failed:
            QMessageBox.warning(
                self, "保存全部", f"已保存 {saved} 个页面，{failed} 项保存失败。"
            )
        else:
            self.status_bar.showMessage(f"已保存 {saved} 个页面", 3000)

    def _update_grid_actions(self) -> None:
        if self.current_page is None:
            return
        scene = self.current_page.scene
        self.grid_action.setChecked(scene.is_show_grid())
        self.coord_action.setChecked(scene.is_show_coordinate())

    def _update_status(self) -> None:
        if self.current_page is None:
            self.status_bar.showMessage("没有打开的页面")
            return
        page = self.current_page
        zoom = int(round(page.scene.scale_factor * 100))
        self.status_bar.showMessage(
            f"当前页面：{page.meta.name}　|　图元：{page.item_count}　|　缩放：{zoom}%"
        )

    # ------------------------------------------------------------------
    # Page commands
    # ------------------------------------------------------------------
    def _current_page_id(self) -> Optional[str]:
        if self.current_page is not None:
            return self.current_page.meta.id
        return self.page_dock.current_page_id()

    def _create_page(self) -> None:
        after_page_id = self.current_page.meta.id if self.current_page is not None else None
        page = self.project_store.create_page(after_page_id=after_page_id)
        self._reload_page_dock(page.id)
        if not self.activate_page(page.id):
            self._reload_page_dock()

    def _duplicate_page(self, page_id: str) -> None:
        source = self.project_store.get_page(page_id)
        if source is None:
            return
        source_page = self.pages.get(page_id)
        if source_page is not None:
            self._save_page(source_page, silent=True)
        try:
            page = self.project_store.duplicate_page(page_id)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "复制页面", f"复制页面失败：\n{exc}")
            return

        self._reload_page_dock(page.id)
        if not self.activate_page(page.id):
            self._reload_page_dock()

    def _duplicate_current_page(self) -> None:
        page_id = self._current_page_id()
        if page_id:
            self._duplicate_page(page_id)

    def _rename_page(self, page_id: str) -> None:
        page = self.project_store.get_page(page_id)
        if page is None:
            return
        new_name, accepted = QInputDialog.getText(
            self, "重命名页面", "页面名称：", text=page.name
        )
        if not accepted:
            return
        try:
            self.project_store.rename_page(page_id, new_name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "重命名页面", str(exc))
            return

        loaded_page = self.pages.get(page_id)
        if loaded_page is not None:
            loaded_page.meta.name = page.name
        self._reload_page_dock(self._current_page_id())
        self._update_status()

    def _rename_current_page(self) -> None:
        page_id = self._current_page_id()
        if page_id:
            self._rename_page(page_id)

    def _delete_page(self, page_id: str) -> None:
        page = self.project_store.get_page(page_id)
        if page is None:
            return
        if len(self.project_store.pages) <= 1:
            QMessageBox.information(self, "删除页面", "至少需要保留一个页面。")
            return

        reply = QMessageBox.question(
            self,
            "删除页面",
            f"确定删除页面“{page.name}”及其场景文件吗？\n此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        pages = list(self.project_store.pages)
        index = pages.index(page)
        fallback_id = pages[index - 1].id if index > 0 else pages[index + 1].id
        was_current = self.current_page is not None and self.current_page.meta.id == page_id

        if not was_current and self.current_page is not None:
            self._save_page(self.current_page, silent=True)

        if not self.project_store.delete_page(page_id):
            self._reload_page_dock(self._current_page_id())
            return

        self._page_count_cache.pop(page_id, None)
        loaded_page = self.pages.pop(page_id, None)
        if loaded_page is not None:
            if was_current:
                loaded_page.deactivate()
            self.stack.removeWidget(loaded_page.scene)
            loaded_page.dispose()

        if was_current:
            self.current_page = None
            self._reload_page_dock(fallback_id)
            self.activate_page(fallback_id)
        else:
            current_id = self._current_page_id()
            self._reload_page_dock(current_id)
            self._refresh_page_counts()
            self._update_status()

    def _delete_current_page(self) -> None:
        page_id = self._current_page_id()
        if page_id:
            self._delete_page(page_id)

    def _move_page(self, page_id: Optional[str], delta: int) -> None:
        if not page_id:
            return
        if self.project_store.move_page(page_id, delta):
            current_id = self.current_page.meta.id if self.current_page else page_id
            self._reload_page_dock(current_id)
            self._refresh_page_counts()
            self._update_status()

    # ------------------------------------------------------------------
    # Property panel and scene commands
    # ------------------------------------------------------------------
    def _update_property_panel(self, selected=None) -> None:
        if self.current_page is None:
            return
        if self.property_panel is None:
            # Lazy creation keeps startup alive even when the first page file
            # is unreadable; the panel appears as soon as a valid page opens.
            self._build_property_dock()
            return
        scene = self.current_page.scene
        if selected is None:
            selected = scene.current_selected
        if selected is not scene and not isinstance(selected, base_element):
            selected = scene

        self.property_panel.scene = scene
        try:
            self.property_panel.update_for_selected(selected)
        except Exception as exc:
            # A property editor must never take the whole design window down.
            # The most common cause is a stale selection after a deletion.
            print(f"刷新属性面板失败: {exc}")

    def _on_scene_selection_changed(self) -> None:
        scene = self.sender()
        if self.current_page is None or scene is not self.current_page.scene:
            return
        self._update_property_panel(scene.current_selected)
        self._update_status()
        self._update_selection_actions()

    def _selected_top_level_items(self):
        scene = self.current_page.scene if self.current_page else None
        if scene is None:
            return []
        return [
            item
            for item in scene.findChildren(base_element)
            if item.get_selected() and not item.is_has_parent()
        ]

    def _selected_group(self):
        scene = self.current_page.scene if self.current_page else None
        return scene.selected_group() if scene is not None else None

    def _update_selection_actions(self) -> None:
        items = self._selected_top_level_items()
        group = self._selected_group()
        self.save_template_action.setEnabled(group is not None)
        self.toolbox_dock.set_capture_enabled(group is not None)
        self.delete_selected_action.setEnabled(bool(items))
        # The arrangement actions stay enabled on purpose: rubber-band
        # selection does not emit selectionChanged(), so toggling them from
        # here would leave them disabled after a box-select.  They validate
        # the selection themselves in apply_arrangement().

    # ------------------------------------------------------------------
    # Group templates
    # ------------------------------------------------------------------
    def save_selected_group_as_template(self) -> None:
        if self.current_page is None:
            return
        self._capture_group_as_template(self.current_page.scene.selected_group())

    def _capture_group_as_template(self, group) -> None:
        if self.current_page is None:
            return
        if not isinstance(group, group_element):
            self.status_bar.showMessage(
                "请先选中一个组（多个图元请先“设置成组”）", 3000
            )
            return

        default_name = self.template_store.unique_name(
            group.get_name() or "组合模板"
        )
        name, accepted = QInputDialog.getText(
            self,
            "添加到控件工具箱",
            "模板名称：",
            text=default_name,
        )
        if not accepted:
            return

        try:
            template = self.template_store.add_from_group(group, name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "添加到控件工具箱", str(exc))
            return

        self._refresh_template_dock()
        self.status_bar.showMessage(f"已添加组合模板：{template.name}", 3000)

    def _rename_template(self, template_id: str) -> None:
        template = self.template_store.get(template_id)
        if template is None:
            return
        new_name, accepted = QInputDialog.getText(
            self, "重命名模板", "模板名称：", text=template.name
        )
        if not accepted:
            return
        try:
            template = self.template_store.rename(template_id, new_name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "重命名模板", str(exc))
            return
        self._refresh_template_dock()
        self.status_bar.showMessage(f"模板已重命名：{template.name}", 3000)

    def _delete_template(self, template_id: str) -> None:
        template = self.template_store.get(template_id)
        if template is None:
            return
        reply = QMessageBox.question(
            self,
            "删除模板",
            f"确定从控件工具箱删除模板“{template.name}”吗？\n"
            "已经放在画布上的图元不会受影响。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            removed = self.template_store.remove(template_id)
        except OSError as exc:
            QMessageBox.warning(self, "删除模板", str(exc))
            return
        if removed:
            self._refresh_template_dock()
            self.status_bar.showMessage(f"已删除模板：{template.name}", 3000)

    def _refresh_template_dock(self) -> None:
        self.toolbox_dock.set_templates(self.template_store.templates)
        self._update_selection_actions()

    def add_template_at_view_center(self, template_id: str) -> None:
        if self.current_page is None:
            return
        scene = self.current_page.scene
        center = scene.window_position_to_scene(
            QPointF(scene.width() / 2.0, scene.height() / 2.0)
        )
        self._insert_template(template_id, center, scene)

    def _on_template_dropped(self, template_id: str, scene_pos: QPointF) -> None:
        scene = self.sender()
        if self.current_page is None or scene is not self.current_page.scene:
            return
        self._insert_template(template_id, scene_pos, scene)

    def _insert_template(self, template_id: str, scene_pos: QPointF, scene) -> None:
        template = self.template_store.get(template_id)
        if template is None:
            self.status_bar.showMessage("模板不存在或已被删除", 3000)
            return
        if self.current_page is None or scene is not self.current_page.scene:
            return

        try:
            root = create_template_instance(
                self.current_page.manager, template, scene_pos
            )
        except Exception as exc:
            print(f"添加控件模板失败({template.name}): {exc}")
            QMessageBox.warning(
                self,
                "添加控件模板",
                f"无法添加模板“{template.name}”：\n{exc}",
            )
            return

        if root is None:
            self.status_bar.showMessage(f"添加模板失败：{template.name}", 3000)
            return

        for item in scene.findChildren(base_element):
            item.set_selected(False)
        root.set_selected(True)
        scene.set_current_select_item(root)
        scene.selectionChanged.emit()
        scene.update()
        self._update_property_panel(root)
        self._update_status()
        self._update_selection_actions()
        self.status_bar.showMessage(f"已添加组合模板：{template.name}", 3000)

    def _toggle_grid(self, checked: bool) -> None:
        if self.current_page is not None:
            self.current_page.scene.show_grid(checked)

    def _toggle_coordinate(self, checked: bool) -> None:
        if self.current_page is not None:
            self.current_page.scene.show_coordinate(checked)

    def reset_view(self) -> None:
        """Restore the view range recorded in the page's ``sceneRect``."""

        if self.current_page is None:
            return
        scene = self.current_page.scene
        if scene.restore_saved_view():
            self.status_bar.showMessage("已恢复到保存的视图范围", 2000)
        else:
            # A brand-new page has no recorded range yet.
            scene.goto_sence_origin()
            self.status_bar.showMessage("视图已复位", 2000)

    def choose_background_color(self) -> None:
        """Pick the current page's background colour and save it with the page."""

        if self.current_page is None:
            return
        scene = self.current_page.scene
        color = QColorDialog.getColor(scene.get_bg_color(), self, "页面背景色")
        if not color.isValid():
            return
        scene.set_bg_color(QColor(color.red(), color.green(), color.blue()))
        # The colour is page content but emits no scene signal, so push the
        # undo step explicitly before the page is written to disk.
        self.current_page.history.commit()
        self._save_page(self.current_page, silent=True)
        self.status_bar.showMessage(f"背景色已更新：{color.name()}", 3000)

    def open_offline_run(self) -> None:
        """Preview the current page in run mode without any PLC connection."""

        if self.current_page is None:
            self.status_bar.showMessage("没有可运行的页面", 3000)
            return

        page = self.current_page
        if not self._save_page(page, silent=True):
            QMessageBox.warning(
                self,
                "离线运行",
                f"页面“{page.meta.name}”保存失败，无法载入最新场景。",
            )
            return

        try:
            dialog = OfflineRunDialog(page.meta, self.project_store, self)
        except Exception as exc:
            print(f"离线运行窗口创建失败: {exc}")
            QMessageBox.critical(
                self,
                "离线运行",
                f"无法载入页面“{page.meta.name}”：\n{exc}",
            )
            return

        self.status_bar.showMessage(f"离线运行：{page.meta.name}", 3000)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def copy_selected(self) -> None:
        if self.current_page is not None:
            self.current_page.scene.copy_selected()
            self.status_bar.showMessage("已复制所选图元", 2000)

    def paste_clipboard(self) -> None:
        if self.current_page is None:
            return
        self.current_page.scene.paste()
        self._update_property_panel(self.current_page.scene)
        self._update_status()

    def delete_selected(self) -> None:
        if self.current_page is None:
            return
        deleted = self.current_page.scene.delete_selected_items()
        if deleted:
            self._update_property_panel(self.current_page.scene)
            self._update_status()
            # The confirmation goes last: _update_status() writes the permanent
            # page summary and would otherwise overwrite this transient message.
            self.status_bar.showMessage(f"已删除 {deleted} 个图元", 2000)

    def select_all(self) -> None:
        if self.current_page is not None:
            self.current_page.scene.select_all_items()
            self._update_property_panel(self.current_page.scene)

    # ------------------------------------------------------------------
    # Alignment / distribution
    # ------------------------------------------------------------------
    def apply_arrangement(self, method_name: str, label: str) -> None:
        """Run one of the scene's alignment/distribution commands.

        The heavy lifting lives on ``QuadTreeScene`` (see
        ``left_alignment_for_selected`` and friends); this wrapper only handles
        the page lifecycle, the undo step and the UI refresh.
        """

        if self.current_page is None:
            self.status_bar.showMessage("没有打开的页面", 2500)
            return

        scene = self.current_page.scene
        items = self._selected_top_level_items()
        if len(items) < 2:
            self.status_bar.showMessage(f"{label}：请先选中至少两个图元", 3000)
            return

        command = getattr(scene, method_name, None)
        if not callable(command):
            return

        history = self.current_page.history
        # Flush the pending edit first so undo reverts the arrangement on its
        # own instead of folding it into the previous drag.
        history.commit()
        command()
        history.commit()

        # prepareGeometryChange() inside the moved items already queued the
        # quadtree re-index; just repaint and refresh the panels here.
        scene.update()
        self._update_property_panel(scene)
        self._update_status()
        self.status_bar.showMessage(f"{label}：已调整 {len(items)} 个图元", 2500)

    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------
    def undo(self) -> None:
        if self.current_page is None:
            return
        if not self.current_page.history.undo():
            self.status_bar.showMessage("没有可撤销的操作", 2000)
            return
        self._after_history_change("已撤销")

    def redo(self) -> None:
        if self.current_page is None:
            return
        if not self.current_page.history.redo():
            self.status_bar.showMessage("没有可重做的操作", 2000)
            return
        self._after_history_change("已重做")

    def _after_history_change(self, verb: str) -> None:
        """Refresh the window after the page was rebuilt from a snapshot."""

        page = self.current_page
        history = page.history
        self._refresh_page_counts()
        self._update_property_panel(page.scene)
        self._update_status()
        self._update_selection_actions()
        self._update_history_actions()
        # Keep the confirmation last: _update_status() writes the permanent
        # page summary and would otherwise overwrite this transient message.
        self.status_bar.showMessage(
            f"{verb}（可撤销 {history.undo_depth} 步 / 可重做 {history.redo_depth} 步）",
            2500,
        )

    def _update_history_actions(self) -> None:
        history = self.current_page.history if self.current_page is not None else None
        can_undo = history.can_undo if history is not None else False
        can_redo = history.can_redo if history is not None else False
        self.undo_action.setEnabled(can_undo)
        self.redo_action.setEnabled(can_redo)
        if history is None:
            return
        self.undo_action.setToolTip(
            f"撤销上一步编辑（画布内 Ctrl+Z） · 可撤销 {history.undo_depth} 步"
        )
        self.redo_action.setToolTip(
            "重做被撤销的编辑（画布内 Ctrl+Shift+Z / Ctrl+Y）"
            f" · 可重做 {history.redo_depth} 步"
        )

    def begin_tool_draw(self, tool_key: str) -> None:
        """Arm the click-to-draw flow for a toolbox element.

        This mirrors the right-click "绘制..." commands: the element is created
        in the scene's drawing state and follows the mouse until the user
        finishes it with canvas clicks, instead of being inserted with a default
        size at the view centre.
        """

        if self.current_page is None:
            return
        definition = TOOL_DEFINITIONS_BY_KEY.get(tool_key)
        if definition is None:
            return

        item = self.current_page.begin_draw_tool(tool_key)
        if item is None:
            self.status_bar.showMessage(f"无法开始绘制{definition.label}", 3000)
            return

        hints = {
            "triangle": "在画布上依次单击三个顶点",
            "text": "在画布上单击放置文本",
            "image": "在画布上单击放置图片",
        }
        hint = hints.get(tool_key, "在画布上单击起点，再次单击确定终点")
        self.status_bar.showMessage(f"{hint}（{definition.label}）", 5000)

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于设计模式",
            "安全车配置 · 设计模式\n\n"
            "左侧管理多个页面/场景，右侧拖拽元素到画布。\n"
            "每个页面对应 datas/design/pages 下的独立场景文件。",
        )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        saved = True
        if self.current_page is not None:
            saved = self._save_page(self.current_page, silent=True)
        try:
            self.project_store.save_project()
        except OSError as exc:
            print(f"保存工程文件失败: {exc}")
            saved = False

        if not saved:
            reply = QMessageBox.question(
                self,
                "保存失败",
                "页面或工程文件保存失败，仍要退出吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

        for page in self.pages.values():
            page.deactivate()
            page.history.shutdown()
        super().closeEvent(event)
