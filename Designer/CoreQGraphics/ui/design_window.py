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

from ..g_boolean import (
    BOOL_INTERSECT, BOOL_SUBTRACT, BOOL_UNION, BOOL_XOR, BOOLEAN_LABELS,
)
from ..g_scene import (
    DEFAULT_SIZES, ORTHO_DRAW_TYPES, TYPE_LABELS, WIDGET_TOOL_LABELS,
    GraphicsScene,
)
from ..g_view import GraphicsView
from .history import PageHistory
from .layer_tree import LayerTreeDock
from .property_panel import PropertyPanel
from .template_store import TemplateStore
from .toolbox import ElementToolboxDock


def _default_template_dir(page_path: str) -> str:
    """模板文件与旧设计器共用一份，两个设计器互相打开对方的模板都能用。

    页面在 ``.../datas/design/pages/`` 下时取上一级 design 目录；否则回退到
    项目自带的 ``Designer/Core/data.json/datas/design``。
    """
    if page_path:
        pages_dir = os.path.dirname(os.path.abspath(page_path))
        if os.path.basename(pages_dir).lower() == "pages":
            return os.path.dirname(pages_dir)
    return os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "Core", "data.json",
        "datas", "design"))


class DesignerWindow(QMainWindow):
    """可独立运行的设计器窗口。"""

    def __init__(self, page_path: str = "", projection=None, parent=None,
                 template_dir: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("CoreQGraphics 设计器")
        self.resize(1500, 940)
        self.scene = GraphicsScene(projection)
        if page_path:
            self.scene.load_page(page_path)
        self.template_store = TemplateStore(
            os.path.abspath(template_dir) if template_dir
            else _default_template_dir(page_path))

        self.view = GraphicsView(self.scene, self)
        self.setCentralWidget(self.view)
        self.status_bar = self.statusBar()
        self.mode_label = QLabel("设计模式")
        self.count_label = QLabel("")
        self.zoom_label = QLabel("")
        self.path_label = QLabel("")
        # 正交状态常驻状态栏：CAD 里这个开关需要随时可见
        self.ortho_label = QLabel("正交 关")
        self.ortho_label.setToolTip(
            "F8 切换；绘制直线 / 多段线时只出水平或竖直线，按住 Shift 临时反转")
        for widget in (self.mode_label, self.ortho_label, self.count_label,
                       self.zoom_label, self.path_label):
            self.status_bar.addPermanentWidget(widget)

        self.history = PageHistory(self.scene)
        self.pending_tool = ""
        # 构造期 viewport 只有 98x28，fitInView 会算出错误缩放；
        # 首次 fit 必须等 showEvent 之后 viewport 有真实尺寸。
        self._initial_fit_pending = True
        # 框选期间攒下的「选中变了」标记，松手时一次性同步（见 _on_selection_changed）
        self._selection_pending = False

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
        # 框选中（左键还按着）先别整表同步图层树，松手由 _flush_selection 补
        self.layers.set_defer_probe(self.view.is_band_selecting)
        self.actions: dict[str, QAction] = {}
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._connect_signals()
        self._refresh_template_dock()
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
        # 不设窗口级快捷键：属性面板输入框要保留原生 Ctrl+C / Ctrl+V，
        # 画布焦点下的 Ctrl+C / Ctrl+V 由 GraphicsView.keyPressEvent 转发。
        self._make("copy", "复制 (Ctrl+C)")
        self._make("paste", "粘贴 (Ctrl+V)")
        self._make("delete", "删除所选", "Delete")
        self._make("select_all", "全选", "Ctrl+A")
        self._make("group", "成组", "Ctrl+G")
        self._make("ungroup", "解组", "Ctrl+Shift+G")
        self._make("rename", "重命名…", "F2")
        self._make("toggle_visible", "显示 / 隐藏", "Ctrl+H")
        # 锁定：Ctrl+L / Ctrl+Shift+U 不与既有窗口级快捷键冲突
        self._make("lock", "锁定所选", "Ctrl+L")
        self.actions["lock"].setToolTip(
            "锁定后图元左下角显示同心圆，设计模式不能移动 / 旋转 / 缩放")
        self._make("unlock", "解锁所选", "Ctrl+Shift+U")
        self.actions["unlock"].setToolTip("解除位姿锁定，恢复移动 / 旋转 / 缩放")
        self._make("save_template", "将所选图元存为模板…")
        self.actions["save_template"].setToolTip(
            "把选中的单个图元或组保存为可复用模板；布尔结果可直接保存")
        for operation in (BOOL_UNION, BOOL_INTERSECT, BOOL_SUBTRACT, BOOL_XOR):
            title = BOOLEAN_LABELS[operation]
            if operation == BOOL_SUBTRACT:
                title += "（首个减其余）"
            action = self._make(f"boolean_{operation}", title)
            action.setToolTip(
                f"对至少两个闭合基本图元求{BOOLEAN_LABELS[operation]}，"
                "生成可继续编辑的路径图元；差集按页面顺序取首个图元")
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
        # CAD 正交：F8 是事实标准，做成可勾选动作（窗口级，焦点在属性面板
        # 里也能切），状态真值放在 GraphicsView，动作只是它的镜像。
        self._make("toggle_ortho", "正交模式 (F8)", "F8", checkable=True)
        self.actions["toggle_ortho"].setToolTip(
            "绘制直线 / 三角形 / 多边形 / 路径时只出水平或竖直线；"
            "按住 Shift 临时反转（开→斜线，关→正交线）")
        # 动作 key 沿用 toggle_ids，但开关现在控制的是「选中图元的旋转中心红点」
        self._make("toggle_ids", "显示中心点标记", "Ctrl+Shift+I", checkable=True)
        self.actions["toggle_ids"].setChecked(True)
        self._make("run_mode", "运行模式预览", "Ctrl+R", checkable=True)
        self._make("toggle_rulers", "显示坐标刻度", "Ctrl+Shift+L",
                   checkable=True)
        self.actions["toggle_rulers"].setChecked(True)
        self.actions["toggle_rulers"].setToolTip(
            "画布上边 / 左边显示坐标刻度条；数值是视图坐标，随缩放平移实时更新")
        self._make("about", "关于…")
        # 标尺只给设计器主窗口打开；GraphicsView 默认关，运行态视图保持关
        self.view.show_rulers = self.actions["toggle_rulers"].isChecked()

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
        for key in ("duplicate", "copy", "paste", "delete", "select_all",
                    "group", "ungroup", "rename", "toggle_visible",
                    "lock", "unlock"):
            edit.addAction(self.actions[key])
        edit.addSeparator()
        boolean_menu = edit.addMenu("布尔运算")
        for operation in (BOOL_UNION, BOOL_INTERSECT, BOOL_SUBTRACT, BOOL_XOR):
            boolean_menu.addAction(self.actions[f"boolean_{operation}"])
        edit.addAction(self.actions["save_template"])

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
                    "toggle_grid", "toggle_rulers", "toggle_ids",
                    "toggle_ortho", "run_mode"):
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
                    "z_front", "z_back", "fit", "lock"):
            bar.addAction(self.actions[key])
        bar.addSeparator()
        bar.addWidget(QLabel("  绘制："))
        for key in ("rect", "circle", "line", "text", "image", "checkbox"):
            action = QAction(TYPE_LABELS[key], self)
            action.triggered.connect(
                lambda checked=False, k=key: self._activate_draw_tool(k)
            )
            bar.addAction(action)
        bar.addSeparator()
        bar.addAction(self.actions["toggle_ortho"])

    def _connect_signals(self) -> None:
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.scene.contentChanged.connect(self._refresh)
        self.property_panel.itemEdited.connect(lambda _item: self._after_edit())
        self.toolbox.toolActivated.connect(self._activate_draw_tool)
        self.toolbox.templateActivated.connect(self.add_template_at_view_center)
        self.toolbox.captureGroupRequested.connect(
            lambda: self._do("save_template"))
        self.toolbox.templateRenameRequested.connect(self._rename_template)
        self.toolbox.templateDeleteRequested.connect(self._delete_template)
        self.scene.drawFinished.connect(self._on_draw_finished)
        self.view.elementDropped.connect(self._on_drop)
        self.view.templateDropped.connect(self._on_template_dropped)
        self.view.actionTriggered.connect(self._do)
        self.view.memberRenameRequested.connect(
            lambda iid: self._rename([int(iid)]))
        self.view.orthoModeChanged.connect(self._on_ortho_changed)
        # 框选松手才把选中「定下来」：拖动中每格都改选中，重建属性面板 +
        # 图层树同步一次约 38 ms，一屏拖下来就是几百毫秒的卡顿。
        self.view.selectionSettled.connect(self._flush_selection)
        self.layers.selectionRequested.connect(self._select_from_tree)
        self.layers.actionRequested.connect(self._do_tree_action)
        self.history.changed.connect(self._update_history_actions)

    # ------------------------------------------------------------------
    # 命令分发
    # ------------------------------------------------------------------
    def _do(self, key: str, payload=None) -> None:
        scene, view = self.scene, self.view
        sel = scene.selected_items()
        # duplicate / paste / group 等命令会先改选中再提交历史。先把本次操作
        # 前的选中交给撤销栈，撤销回上一状态时才能恢复用户当时选中的图元。
        self.history.note_pre_edit_selection([it.item_id for it in sel])
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
            if made:
                scene.select_items(made)   # 批量选中：只发一次 selectionChanged
                self._after_edit()
        elif key == "copy":
            n = scene.copy_selected()
            self.status_bar.showMessage(
                f"已复制 {n} 个图元（含子图元）", 2500)
        elif key == "paste":
            made = scene.paste_clipboard()
            if made:
                scene.select_items(made)   # 批量选中：只发一次 selectionChanged
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
                    "请先选中图元，再按住 O 键 + 右键把旋转中心设到点击处", 4000)
            self._after_edit()
        elif key == "origin_center":
            n = scene.reset_selected_origin()
            self.status_bar.showMessage(
                f"已把 {n} 个图元的旋转中心复位到图元中心" if n
                else "选中图元的旋转中心本来就在中心", 3000)
            self._after_edit()
        elif key == "drag_done":
            # 一次画布交互结束（拖角改尺寸 / 跟手落定后，视图发现页面被改动才发）
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
        elif key == "toggle_rulers":
            view.show_rulers = self.actions["toggle_rulers"].isChecked()
            view.viewport().update()
        elif key == "toggle_ids":
            view.show_ids = self.actions["toggle_ids"].isChecked()
            view.viewport().update()
        elif key == "toggle_ortho":
            view.set_ortho_mode(self.actions["toggle_ortho"].isChecked())
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
                "widget 图元支持 9 种控件变体（含进度条 / 滑动条；设计态自绘占位、运行预览挂载真实 Qt 控件），\n"
                "F8 正交模式：绘制点列图元时锁水平 / 竖直，Shift 临时反转；\n"
                "直线的宽或高设为 0 即水平 / 竖直线，两者不能同时为 0。\n"
                "方向键：选中图元后按一下挪一格，按住连续挪；Shift 加速 10 倍，\n"
                "画布有焦点时生效（无选中时方向键仍用于滚动画布）。\n"
                "布尔运算：多选矩形、圆、三角形、多边形或路径，可做并 / 交 / 差 / 异或；\n"
                "结果保留多轮廓、孔洞和精确曲线，可继续编辑或再次布尔。\n"
                "模板：选中单个图元或组后保存进工具箱，点击 / 拖放即可重复实例化，\n"
                "模板文件与旧设计器共用 toolbox_templates.json。\n"
                "锁定：Ctrl+L 锁定所选、Ctrl+Shift+U 解锁；锁定图元左下角显示同心圆，\n"
                "设计模式下不能移动 / 旋转 / 缩放，但可选中、改名、改外观、复制和删除。\n"
                "不含 PLC / 料仓状态绑定。",
            )
        elif key == "toggle_visible":
            # 隐藏图元 Qt 无法选中，scene.selected_items() 会漏掉它们；回退到
            # 图层树的选中集合，保证「只选中隐藏项时 Ctrl+H 也能恢复」。
            targets = payload or [it.item_id for it in sel] or self.layers.selected_ids()
            self._toggle_visible(targets)
        elif key == "rename":
            self._rename(payload or [it.item_id for it in sel])
        elif key.startswith("boolean_"):
            operation = key.removeprefix("boolean_")
            try:
                result = scene.apply_boolean(operation)
            except ValueError as exc:
                self.status_bar.showMessage(f"布尔运算失败：{exc}", 4500)
            else:
                self._after_edit()
                self.status_bar.showMessage(
                    f"已生成布尔{BOOLEAN_LABELS[operation]}路径；"
                    "可继续编辑，或选择「将所选图元存为模板」", 5000)
        elif key in ("lock", "unlock"):
            # payload 来自图层树（可只选中隐藏项）；画布命令用当前选中。
            targets = payload or [it.item_id for it in sel]
            n = scene.set_items_locked(targets, key == "lock")
            if n:
                self._after_edit()
                # 属性面板要立刻把 X/Y/W/H/旋转切到只读（或恢复可编辑）
                self._on_selection_changed()
            self.status_bar.showMessage(
                (f"已锁定 {n} 个图元（设计模式不能移动 / 旋转 / 缩放）"
                 if key == "lock" else f"已解锁 {n} 个图元")
                if n else "所选图元的锁定状态没有变化", 3000)
        elif key == "save_template":
            self._capture_group_as_template(None)
        self._refresh()

    # ------------------------------------------------------------------
    # 组合模板：菜单 / 画布右键 / 工具箱按钮 / 拖放共用这一组入口
    # ------------------------------------------------------------------
    def _refresh_template_dock(self) -> None:
        self.toolbox.set_templates(self.template_store.templates)
        can_capture = self._selected_template_item() is not None
        self.toolbox.set_capture_enabled(can_capture)
        self.actions["save_template"].setEnabled(can_capture)

    def _selected_group(self):
        item = self._selected_template_item()
        return item if item is not None and item.TYPE == "group" else None

    def _selected_template_item(self):
        sel = self.scene.selected_items()
        return sel[0] if len(sel) == 1 else None

    def _capture_group_as_template(self, item=None) -> None:
        item = item or self._selected_template_item()
        if item is None:
            self.status_bar.showMessage(
                "请先选中一个图元或组；多选图元可先成组或做布尔运算", 3000)
            return
        default_name = self.template_store.unique_name(
            item.get_name() or "图元模板")
        name, ok = QInputDialog.getText(
            self, "添加到控件工具箱", "模板名称：", text=default_name)
        if not ok:
            return
        try:
            template = self.template_store.add_from_item(self.scene, item, name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "添加到控件工具箱", str(exc))
            return
        self._refresh_template_dock()
        self.status_bar.showMessage(
            f"已添加模板「{template.name}」（{template.node_count} 个图元）",
            3500)

    def _rename_template(self, template_id: str) -> None:
        template = self.template_store.get(template_id)
        if template is None:
            return
        new_name, ok = QInputDialog.getText(
            self, "重命名模板", "模板名称：", text=template.name)
        if not ok:
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
            self, "删除模板",
            f"确定从控件工具箱删除模板「{template.name}」吗？\n"
            "已经放在画布上的图元不会受影响。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
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

    def add_template_at_view_center(self, template_id: str) -> None:
        """点击模板按钮：插到当前视口中心（不是场景原点）。"""
        center = self.view.viewport().rect().center()
        self._insert_template(template_id, self.view.mapToScene(center))

    def _on_template_dropped(self, template_id: str, scene_pt: QPointF) -> None:
        self._insert_template(template_id, scene_pt)

    def _insert_template(self, template_id: str, scene_pt: QPointF) -> None:
        template = self.template_store.get(template_id)
        if template is None:
            self.status_bar.showMessage("模板不存在或已被删除", 3000)
            return
        cx, cy = self.scene.projection.inverse_point(scene_pt.x(), scene_pt.y())
        try:
            root = self.scene.instantiate_template(template, QPointF(cx, cy))
        except Exception as exc:
            print(f"添加控件模板失败({template.name}): {exc}")
            QMessageBox.warning(
                self, "添加控件模板",
                f"无法添加模板「{template.name}」：\n{exc}")
            return
        if root is None:
            self.status_bar.showMessage(f"添加模板失败：{template.name}", 3000)
            return
        self.scene.clearSelection()
        root.setSelected(True)
        self._after_edit()
        self.status_bar.showMessage(
            f"已添加组合模板「{template.name}」（{template.node_count} 个图元）",
            3500)

    def _do_tree_action(self, key: str, ids: list[int]) -> None:
        self._select_from_tree(ids)
        self._do(key, ids)

    def _on_ortho_changed(self, on: bool) -> None:
        """视图才是正交状态的真值；这里把菜单 / 工具栏 / 状态栏对齐过去。

        ``setChecked`` 不发 ``triggered``，再叠一层 blockSignals 保证以后
        从画布快捷键切正交时也不会绕回 ``_do`` 形成二次 toggle。
        """
        action = self.actions.get("toggle_ortho")
        if action is not None and action.isChecked() != on:
            action.blockSignals(True)
            action.setChecked(on)
            action.blockSignals(False)
        self.ortho_label.setText("正交 开" if on else "正交 关")
        self.status_bar.showMessage(
            "正交已开启：直线只画水平 / 竖直线（按住 Shift 临时画斜线）" if on
            else "正交已关闭：按住 Shift 可临时画正交线", 3000)

    def _toggle_visible(self, ids: list[int]) -> None:
        for iid in ids:
            item = self.scene.find_item(iid)
            if item is not None:
                item.set_visibility(not item.get_visibility())
        # 显式带上 ids：隐藏图元不在 scene.selected_items() 里，按选中推断会漏
        self.scene.notify_edit(None, ids)
        self._after_edit()

    def _rename(self, ids: list[int]) -> None:
        """F2 / 右键重命名：重名或空名**拒绝并提示**，对话框留着让人改。

        名字整页唯一（图层树、``find_item_by_name``、运行态按名绑定都靠它），
        所以这里在写之前先问场景要原因；被拒时把刚输入的名字留在框里，改一个
        能用的即可，取消则什么都不写。
        """
        if not ids:
            return
        item = self.scene.find_item(ids[0])
        if item is None:
            return
        proposed = item.get_name()
        while True:
            name, ok = QInputDialog.getText(self, "重命名", "新名称：", text=proposed)
            if not ok:
                return
            text = name.strip()
            problem = self.scene.rename_problem(text, item.item_id)
            if problem:
                QMessageBox.warning(self, "重命名", problem)
                proposed = name
                continue
            if text != str(item.get_name() or "").strip():
                item.set_name(text)
                self.scene.notify_edit(item)
                self._after_edit()
            return

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
        # 只记撤销点。图层树 / 状态栏的刷新已经由 scene 的细粒度变更广播
        # 在写操作发生的当下做过了；这里再 refresh 一遍会重复重建整棵树
        # （一次属性编辑 = contentChanged 一次 + _after_edit 一次）。
        # history.commit() 自身发 changed -> _update_history_actions()。
        self.history.commit()

    # ------------------------------------------------------------------
    # 图元创建 / 拖放
    # ------------------------------------------------------------------
    def _activate_draw_tool(self, type_key: str) -> None:
        """工具箱/工具栏/菜单统一入口：进入绘制模式（点击画布落点）。"""
        self.view.set_draw_tool(type_key)
        if type_key:
            label = WIDGET_TOOL_LABELS.get(
                type_key, TYPE_LABELS.get(type_key, type_key))
            if type_key in ("polygon", "path"):
                tip = f"左键加点、右键闭合以创建「{label}」"
            elif type_key in ("line", "rect", "circle"):
                tip = f"在画布上点击两下（起点、终点）以创建「{label}」"
            elif type_key == "triangle":
                tip = f"在画布上点击三下以创建「{label}」"
            elif type_key == "bezier":
                tip = (f"在画布上点击四下（起点、控制点 1、控制点 2、终点）"
                       f"以创建「{label}」")
            else:
                tip = f"在画布上单击以放置「{label}」"
            if self.view.is_ortho_mode() and type_key in ORTHO_DRAW_TYPES:
                tip += "（正交已开启：只出水平/竖直线，按 Shift 临时画斜线）"
            self.status_bar.showMessage(
                f"绘制模式：{tip}，按 Esc 退出、F8 切换正交", 6000)
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
            f"已放置「{WIDGET_TOOL_LABELS.get(type_key, TYPE_LABELS.get(type_key, type_key))}」，"
            f"双击可跟手拖动，或用属性面板调整位置", 4000
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
        # 当前历史状态已与磁盘一致：撤销再重做回来不该重新标脏
        self.history.mark_saved()
        self._refresh()

    def _save_page(self) -> None:
        try:
            self.scene.save_page()
        except ValueError:
            self._save_as()
            return
        self.history.mark_saved()
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
        # 析构期 Qt 会先销毁 C++ GraphicsScene，若此时还留着选中项，
        # scene.clear() 会补发 selectionChanged，图层树 / 属性面板的槽就会
        # 访问已删除对象（stderr 冒 RuntimeError）。关窗前先清干净选中，
        # 销毁过程便不会再回调 Python 侧。
        self.scene.clearSelection()
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
        """选中集合变化：同步属性面板 / 图层树 / 状态栏。

        框选中（左键还按着）只记一个「待同步」标记就返回——框选每一格都会改
        选中，面板重建 + 图层树同步实测 ~38 ms/次，全屏拖一趟会白烧几百毫秒，
        而且中途那些半成品多选状态用户根本看不清。松手时视图发
        ``selectionSettled``，这里一次性补齐（见 ``_flush_selection``）。
        """
        if self.view.is_band_selecting():
            self._selection_pending = True
            return
        self._apply_selection_ui()

    def _flush_selection(self) -> None:
        """框选松手：把拖动期间攒下的选中变化一次性同步到面板 / 图层树。"""
        if not getattr(self, "_selection_pending", False):
            return
        self._selection_pending = False
        self._apply_selection_ui()

    def _apply_selection_ui(self) -> None:
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
                    "z_back", "z_raise", "z_lower", "lock", "unlock"):
            self.actions[key].setEnabled(has_sel)
        can_capture = self._selected_template_item() is not None
        self.actions["save_template"].setEnabled(can_capture)
        self.toolbox.set_capture_enabled(can_capture)
        can_boolean = len(self.scene.boolean_items()) >= 2
        for operation in (BOOL_UNION, BOOL_INTERSECT, BOOL_SUBTRACT, BOOL_XOR):
            self.actions[f"boolean_{operation}"].setEnabled(can_boolean)


