"""CoreQGraphics 设计器外壳：主窗口 + 菜单/工具栏 + 三块 Dock。

与旧 ``DesignWindow`` 的关键差异（刻意为之）：
* 中央是原生 ``QGraphicsView``，不是每页一个自绘 QWidget 的 QStackedWidget；
* 新增「图层 / 对象树」Dock（旧项目只有属性分页树和页面列表）；
* **关窗不无条件写盘**。旧版 ``closeEvent`` 因为设计器没有脏标记，
  关窗时强制保存页面，导致所有 verify 脚本都得先备份 page_*.json。
  这里用 ``scene.is_modified()`` 判断，未编辑直接退出。
* 菜单 / 工具栏 / 画布右键 / 图层树右键全部走 ``_do()`` 同一个命令分发，
  保证撤销快照与脏标记不会漏记。
"""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget, QFileDialog, QInputDialog, QLabel, QMainWindow, QMessageBox,
    QToolBar,
)

from ..g_scene import DEFAULT_SIZES, TYPE_LABELS, GraphicsScene
from ..g_view import GraphicsView
from .history import PageHistory
from .layer_tree import LayerTreeDock
from .property_panel import PropertyPanel
from .toolbox import ElementToolboxDock


class DesignerWindow(QMainWindow):
    """可独立运行的设计器窗口。"""

    def __init__(self, page_path: str = "", projection=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("CoreQGraphics 设计器")
        self.resize(1500, 940)
        self.scene = GraphicsScene(projection)
        if page_path:
            self.scene.load_page(page_path)

        self.view = GraphicsView(self.scene, self)
        self.setCentralWidget(self.view)
        self.status_bar = self.statusBar()
        self.mode_label = QLabel("设计模式")
        self.count_label = QLabel("")
        self.zoom_label = QLabel("")
        self.path_label = QLabel("")
        for widget in (self.mode_label, self.count_label,
                       self.zoom_label, self.path_label):
            self.status_bar.addPermanentWidget(widget)

        self.history = PageHistory(self.scene)
        self.pending_tool = ""
        # 构造期 viewport 只有 98x28，fitInView 会算出错误缩放；
        # 首次 fit 必须等 showEvent 之后 viewport 有真实尺寸。
        self._initial_fit_pending = True

        self.layers = LayerTreeDock(self)
        self.toolbox = ElementToolboxDock(self)
        self.property_panel = PropertyPanel(self)
        self.property_dock = QDockWidget("属性", self)
        self.property_dock.setObjectName("coreQgPropertyDock")
        self.property_dock.setWidget(self.property_panel)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.layers)
        self.addDockWidget(Qt.RightDockWidgetArea, self.toolbox)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.property_dock)
        self.property_dock.setMinimumHeight(240)

        self.layers.set_scene(self.scene)
        self.property_panel.set_scene(self.scene)
        self.actions: dict[str, QAction] = {}
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._connect_signals()

        self._refresh()

    # ------------------------------------------------------------------
    # 动作 / 菜单 / 工具栏
    # ------------------------------------------------------------------
    def _make(self, key: str, title: str, shortcut: str = "",
              checkable: bool = False) -> QAction:
        action = QAction(title, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        action.triggered.connect(lambda checked=False, k=key: self._do(k))
        self.actions[key] = action
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        self._make("open", "打开页面…", "Ctrl+O")
        self._make("save", "保存", "Ctrl+S")
        self._make("save_as", "另存为…", "Ctrl+Shift+S")
        self._make("exit", "退出", "Ctrl+Q")
        self._make("undo", "撤销", "Ctrl+Z")
        self._make("redo", "重做", "Ctrl+Y")
        self._make("duplicate", "复制所选", "Ctrl+D")
        self._make("delete", "删除所选", "Delete")
        self._make("select_all", "全选", "Ctrl+A")
        self._make("group", "成组", "Ctrl+G")
        self._make("ungroup", "解组", "Ctrl+Shift+G")
        self._make("rename", "重命名…", "F2")
        self._make("toggle_visible", "显示 / 隐藏", "Ctrl+H")
        for entry in (
            ("align_left", "左对齐"), ("align_right", "右对齐"),
            ("align_top", "顶对齐"), ("align_bottom", "底对齐"),
            ("align_hcenter", "水平居中"), ("align_vcenter", "垂直居中"),
            ("distribute_h", "水平等距"), ("distribute_v", "垂直等距"),
            ("z_front", "移到最前"), ("z_raise", "上移一层"),
            ("z_lower", "下移一层"), ("z_back", "移到最后"),
            ("fit", "适应内容", "Ctrl+0"),
            ("fit_saved", "恢复保存视图", "Ctrl+9"),
            ("zoom_in", "放大", "+"), ("zoom_out", "缩小", "-"),
        ):
            self._make(*entry)
        self._make("origin_center", "旋转中心复位")
        self._make("toggle_grid", "显示网格", "Ctrl+Shift+N", checkable=True)
        self.actions["toggle_grid"].setChecked(True)
        self._make("toggle_ids", "显示图元ID", "Ctrl+Shift+I", checkable=True)
        self.actions["toggle_ids"].setChecked(True)
        self._make("run_mode", "运行模式预览", "Ctrl+R", checkable=True)
        self._make("about", "关于…")

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("文件")
        for key in ("open", "save", "save_as"):
            file_menu.addAction(self.actions[key])
        file_menu.addSeparator()
        file_menu.addAction(self.actions["exit"])

        edit = bar.addMenu("编辑")
        for key in ("undo", "redo"):
            edit.addAction(self.actions[key])
        edit.addSeparator()
        for key in ("duplicate", "delete", "select_all", "group", "ungroup",
                    "rename", "toggle_visible"):
            edit.addAction(self.actions[key])

        arrange = bar.addMenu("排列")
        for key in ("align_left", "align_right", "align_top", "align_bottom",
                    "align_hcenter", "align_vcenter", "distribute_h", "distribute_v"):
            arrange.addAction(self.actions[key])
        arrange.addSeparator()
        for key in ("z_front", "z_raise", "z_lower", "z_back"):
            arrange.addAction(self.actions[key])
        arrange.addSeparator()
        arrange.addAction(self.actions["origin_center"])

        view_menu = bar.addMenu("视图")
        for key in ("fit", "fit_saved", "zoom_in", "zoom_out",
                    "toggle_grid", "toggle_ids", "run_mode"):
            view_menu.addAction(self.actions[key])

        create = bar.addMenu("新建图元")
        for key in TYPE_LABELS:
            action = QAction(TYPE_LABELS[key], self)
            action.triggered.connect(
                lambda checked=False, k=key: self._activate_draw_tool(k)
            )
            create.addAction(action)
        bar.addMenu("帮助").addAction(self.actions["about"])

    def _build_toolbar(self) -> None:
        bar = QToolBar("设计工具", self)
        bar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, bar)
        for key in ("open", "save", "undo", "redo", "duplicate", "delete",
                    "group", "ungroup", "align_left", "align_hcenter",
                    "z_front", "z_back", "fit"):
            bar.addAction(self.actions[key])
        bar.addSeparator()
        bar.addWidget(QLabel("  绘制："))
        for key in ("rect", "circle", "line", "text", "image", "checkbox"):
            action = QAction(TYPE_LABELS[key], self)
            action.triggered.connect(
                lambda checked=False, k=key: self._activate_draw_tool(k)
            )
            bar.addAction(action)

    def _connect_signals(self) -> None:
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.scene.contentChanged.connect(self._refresh)
        self.property_panel.itemEdited.connect(lambda _item: self._after_edit())
        self.toolbox.toolActivated.connect(self._activate_draw_tool)
        self.scene.drawFinished.connect(self._on_draw_finished)
        self.view.elementDropped.connect(self._on_drop)
        self.view.actionTriggered.connect(self._do)
        self.layers.selectionRequested.connect(self._select_from_tree)
        self.layers.actionRequested.connect(self._do_tree_action)
        self.history.changed.connect(self._update_history_actions)

    # ------------------------------------------------------------------
    # 命令分发
    # ------------------------------------------------------------------
    def _do(self, key: str, payload=None) -> None:
        scene, view = self.scene, self.view
        sel = scene.selected_items()
        if key == "open":
            self._open_page()
        elif key == "save":
            self._save_page()
        elif key == "save_as":
            self._save_as()
        elif key == "exit":
            self.close()
        elif key == "undo":
            self.history.undo()
            self._on_selection_changed()
        elif key == "redo":
            self.history.redo()
            self._on_selection_changed()
        elif key == "property":
            # 右键「属性…」：把底部属性面板显示出来并重新绑定当前选中项
            self.property_dock.show()
            self.property_dock.raise_()
            self._on_selection_changed()
            n = len(scene.selected_items())
            self.status_bar.showMessage(
                f"属性面板已定位到 {n} 个选中图元" if n
                else "属性面板（当前未选中图元）", 2500
            )
        elif key == "duplicate":
            made = scene.duplicate_selected()
            for it in made:
                it.setSelected(True)
            self._after_edit()
        elif key == "delete":
            scene.delete_items(sel)
            self._after_edit()
        elif key == "select_all":
            scene.select_all_items()
        elif key == "group":
            group = scene.group_selected()
            if group is not None:
                scene.clearSelection()
                group.setSelected(True)
            self._after_edit()
        elif key == "ungroup":
            scene.ungroup_selected()
            self._after_edit()
        elif key.startswith("align_"):
            scene.align_selected(key[6:])
            self._after_edit()
        elif key == "distribute_h":
            scene.distribute_selected(True)
            self._after_edit()
        elif key == "distribute_v":
            scene.distribute_selected(False)
            self._after_edit()
        elif key in ("z_front", "z_back", "z_raise", "z_lower"):
            scene.set_item_z(sel, key[2:])
            self._after_edit()
        elif key == "origin_here":
            point = self.view.context_page_point()
            n = scene.set_selected_origin(point.x(), point.y()) if point is not None else 0
            if n:
                self.status_bar.showMessage(
                    f"已把 {n} 个图元的旋转中心设到 "
                    f"({point.x():.1f}, {point.y():.1f})", 3500
                )
            else:
                self.status_bar.showMessage(
                    "请先用右键在画布上点一个位置，再选「旋转中心设到此处」", 4000)
            self._after_edit()
        elif key == "origin_center":
            n = scene.reset_selected_origin()
            self.status_bar.showMessage(
                f"已把 {n} 个图元的旋转中心复位到图元中心" if n
                else "选中图元的旋转中心本来就在中心", 3000)
            self._after_edit()
        elif key == "drag_child":
            # 拖的是子图元：视图已把拖动转成拖根父对象，这里说明一下
            cur = scene.selected_items()
            name = cur[0].get_name() if cur else "父对象"
            self.status_bar.showMessage(
                f"该图元有父对象，已改为拖动根父对象「{name}」"
                f"（子图元位姿由父对象决定）", 5000)
        elif key == "drag_done":
            # 画布拖拽结束（视图发现页面被改动才会发这个命令）
            self._after_edit()
        elif key == "fit":
            view.fit_content()
        elif key == "fit_saved":
            view.fit_saved_rect()
        elif key == "zoom_in":
            view.scale(1.15, 1.15)
        elif key == "zoom_out":
            view.scale(1 / 1.15, 1 / 1.15)
        elif key == "toggle_grid":
            show = self.actions["toggle_grid"].isChecked()
            view.show_grid = show
            # 网格关掉后就不该再吸到「看不见的」格点
            view.snap.grid_enabled = show
            view.viewport().update()
        elif key == "toggle_ids":
            view.show_ids = self.actions["toggle_ids"].isChecked()
            view.viewport().update()
        elif key == "run_mode":
            run = self.actions["run_mode"].isChecked()
            scene.set_scene_mode(run)
            self.view.set_draw_tool(None)
            self.toolbox.setEnabled(not run)
            self.mode_label.setText("运行预览" if run else "设计模式")
            self._on_selection_changed()
        elif key == "about":
            QMessageBox.about(
                self, "关于",
                "Designer.CoreQGraphics 设计器\n\n"
                "原生 QGraphicsScene 平行实现；page_*.json 格式与 Core 一致。\n"
                "widget 图元为占位实现，不含 PLC / 料仓状态绑定。",
            )
        elif key == "toggle_visible":
            # 隐藏图元 Qt 无法选中，scene.selected_items() 会漏掉它们；回退到
            # 图层树的选中集合，保证「只选中隐藏项时 Ctrl+H 也能恢复」。
            targets = payload or [it.item_id for it in sel] or self.layers.selected_ids()
            self._toggle_visible(targets)
        elif key == "rename":
            self._rename(payload or [it.item_id for it in sel])
        self._refresh()

    def _do_tree_action(self, key: str, ids: list[int]) -> None:
        self._select_from_tree(ids)
        self._do(key, ids)

    def _toggle_visible(self, ids: list[int]) -> None:
        for iid in ids:
            item = self.scene.find_item(iid)
            if item is not None:
                item.set_visibility(not item.get_visibility())
        self.scene.notify_edit(None)
        self._after_edit()

    def _rename(self, ids: list[int]) -> None:
        if not ids:
            return
        item = self.scene.find_item(ids[0])
        if item is None:
            return
        name, ok = QInputDialog.getText(self, "重命名", "新名称：", text=item.get_name())
        if ok and name.strip():
            item.set_name(name.strip())
            self.scene.notify_edit(item)
            self._after_edit()

    def _select_from_tree(self, ids: list[int]) -> None:
        wanted = set(ids or [])
        self.scene.blockSignals(True)
        try:
            for it in self.scene.all_items():
                it.setSelected(it.item_id in wanted)
        finally:
            self.scene.blockSignals(False)
        self._on_selection_changed()
        self._refresh()

    def _after_edit(self) -> None:
        self.history.commit()
        self.layers.refresh()
        self._refresh()

    # ------------------------------------------------------------------
    # 图元创建 / 拖放
    # ------------------------------------------------------------------
    def _activate_draw_tool(self, type_key: str) -> None:
        """工具箱/工具栏/菜单统一入口：进入绘制模式（点击画布落点）。"""
        self.view.set_draw_tool(type_key)
        if type_key:
            label = TYPE_LABELS.get(type_key, type_key)
            if type_key in ("polygon", "path"):
                tip = f"左键加点、右键闭合以创建「{label}」"
            elif type_key in ("line", "rect", "circle"):
                tip = f"在画布上点击两下（起点、终点）以创建「{label}」"
            elif type_key == "triangle":
                tip = f"在画布上点击三下以创建「{label}」"
            else:
                tip = f"在画布上单击以放置「{label}」"
            self.status_bar.showMessage(f"绘制模式：{tip}，按 Esc 退出", 6000)
        else:
            self.status_bar.showMessage("已退出绘制模式", 2000)
        self._refresh()

    def _on_draw_finished(self, item) -> None:
        """一次手动绘制完成：选中并写入历史。"""
        self.scene.clearSelection()
        if item is not None:
            item.setSelected(True)
            self.status_bar.showMessage(
                f"已创建「{TYPE_LABELS.get(item.TYPE, item.TYPE)}」", 3000
            )
        self._after_edit()

    def _on_drop(self, type_key: str, scene_pos: QPointF) -> None:
        cx, cy = self.scene.projection.inverse_point(scene_pos.x(), scene_pos.y())
        self._spawn(type_key, (cx, cy))

    def _spawn(self, type_key: str, center: tuple[float, float]) -> None:
        item = self.scene.create_item(type_key, center)
        if item is None:
            return
        self.scene.clearSelection()
        item.setSelected(True)
        self.status_bar.showMessage(
            f"已放置「{TYPE_LABELS.get(type_key, type_key)}」，可拖动或用属性面板调整", 4000
        )
        self._after_edit()

    # ------------------------------------------------------------------
    # 文件
    # ------------------------------------------------------------------
    def _open_page(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开页面", "", "页面 JSON (*.json)"
        )
        if not path:
            return
        self.scene.load_page(path)
        self.history.reset()
        self.view.fit_content()
        self._on_selection_changed()

    def _save_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "另存为", "", "页面 JSON (*.json)"
        )
        if not path:
            return
        self.scene.save_page(path)
        self._refresh()

    def _save_page(self) -> None:
        try:
            self.scene.save_page()
        except ValueError:
            self._save_as()
            return
        self.status_bar.showMessage("已保存", 2500)
        self._refresh()

    def closeEvent(self, event) -> None:
        # 关键：只在真有改动时才询问，绝不无条件重写 page_*.json。
        if self.scene.is_modified():
            reply = QMessageBox.question(
                self, "未保存的修改",
                "当前页面有未保存的修改，是否保存？",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Save:
                self._save_page()
        event.accept()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._initial_fit_pending:
            self._initial_fit_pending = False
            self.view.fit_content()

    # ------------------------------------------------------------------
    # 状态同步
    # ------------------------------------------------------------------
    def _on_selection_changed(self) -> None:
        sel = self.scene.selected_items()
        target = sel[0] if len(sel) == 1 else (sel if len(sel) > 1 else None)
        self.property_panel.update_for_selected(target)
        self.layers.sync_selection()
        self._refresh()

    def _update_history_actions(self) -> None:
        if "undo" in self.actions:
            self.actions["undo"].setEnabled(self.history.can_undo())
            self.actions["redo"].setEnabled(self.history.can_redo())

    def _refresh(self) -> None:
        n = len(self.scene.all_items())
        self.count_label.setText(f"{n} 个图元 · 选中 {len(self.scene.selected_items())}")
        transform = self.view.transform()
        self.zoom_label.setText(f"缩放 {transform.m11() * 100:.0f}%")
        path = getattr(self.scene, "_page_path", "")
        self.path_label.setText(os.path.basename(path) if path else "未命名")
        title = (os.path.basename(path) if path else "未命名")
        self.setWindowTitle(f"{title} · CoreQGraphics 设计器"
                            + (" *" if self.scene.is_modified() else ""))
        self._update_history_actions()
        has_sel = bool(self.scene.selected_items())
        for key in ("delete", "duplicate", "group", "ungroup", "z_front",
                    "z_back", "z_raise", "z_lower"):
            self.actions[key].setEnabled(has_sel)
