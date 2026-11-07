"""属性面板：复用 ``Designer/Core/property_widgets.py`` 的纯 Qt 控件层。

那个模块零业务耦合（只 import PySide6），导入它不会给本包带来旧图元依赖；
包初始化本来就会经 ``Designer/__init__.py`` 加载旧设计器，复用控件层还能
保证新旧属性面板外观一致。字段绑定这一层全部按 ``BaseItem`` 重写。

对齐旧 ``NavigationContentWidget`` 的交互：左侧分页树 + 右侧 QStackedWidget，
单选显示「常规 / 外观 / 布局」+ 类型特有页；多选与空选中显示只读汇总页。
多选只给统计概要，不再逐项罗列图元清单（具体图元交给画布 / 图层树）。
编辑信号直写图元（无「应用」按钮），改完调 ``scene.notify_edit()``。
"""

from __future__ import annotations

from PySide6.QtCore import QFileInfo, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QListWidget, QPushButton, QSplitter, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

# 纯控件层：与旧属性面板共用，零业务依赖
from Designer.Core.property_widgets import (
    PROPERTY_PANEL_QSS, ColorField, EmptyState, ObjectHeader, OpacityField,
    PropertyPage, SectionCard, make_check, make_double, make_int, make_line,
    make_textarea, make_value_label,
)

from ..g_scene import TYPE_LABELS
from ..g_style import color_str, parse_color

PAGE_ROLE = Qt.UserRole


class PropertyPanel(QWidget):
    itemEdited = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("coreQgPropertyPanel")
        self.scene = None
        self._target = None
        self._updating = False
        self._geo_bindings: list[tuple[object, object]] = []
        self._last_page: dict[str, str] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.header = ObjectHeader(self)
        outer.addWidget(self.header)

        splitter = QSplitter(Qt.Horizontal, self)
        self.nav = QTreeWidget(splitter)
        self.nav.setObjectName("propNavTree")
        self.nav.setHeaderHidden(True)
        self.nav.setColumnCount(1)
        self.nav.setIndentation(8)
        self.nav.setRootIsDecorated(False)
        self.nav.setUniformRowHeights(True)
        self.nav.setFixedWidth(120)
        self.nav.currentItemChanged.connect(self._on_nav_changed)
        self.stack = QStackedWidget(splitter)
        splitter.addWidget(self.nav)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)
        self.setStyleSheet(PROPERTY_PANEL_QSS)
        self.show_empty("未选择图元", "在画布或图层树里选择一个图元即可编辑属性")

    # ------------------------------------------------------------------
    # 外部入口
    # ------------------------------------------------------------------
    def set_scene(self, scene) -> None:
        self.scene = scene
        if scene is not None:
            scene.geometryChanged.connect(self.refresh_geometry)
        self.update_for_selected(None)

    def update_for_selected(self, target) -> None:
        namespace = ("scene" if target is None else
                     "multi" if isinstance(target, (list, tuple)) else "element")
        self._target = target
        self._clear()
        self._geo_bindings.clear()
        if isinstance(target, (list, tuple)):
            self._build_multi(target)
            self.header.set_object("多", f"{len(target)} 个图元", "多选 · 只做汇总")
        elif target is None:
            self._build_scene()
            n = len(self.scene.all_items()) if self.scene is not None else 0
            self.header.set_object("页", "页面属性", f"{n} 个图元 · 未选中")
        else:
            self._build_item(target)
            self.header.set_object(
                TYPE_LABELS.get(target.TYPE, target.TYPE)[:1],
                target.get_name(),
                f"{TYPE_LABELS.get(target.TYPE, target.TYPE)} · ID {target.item_id}",
            )
        self._select_page(self._last_page.get(namespace, ""))

    def _select_page(self, key: str) -> None:
        for i in range(self.stack.count()):
            widget = self.stack.widget(i)
            if key and widget.objectName() == key:
                self.stack.setCurrentIndex(i)
                self._sync_nav(key)
                return
        if self.stack.count():
            self.stack.setCurrentIndex(0)
            self._sync_nav(self.stack.widget(0).objectName())

    def _sync_nav(self, key: str) -> None:
        self.nav.blockSignals(True)
        for i in range(self.nav.topLevelItemCount()):
            node = self.nav.topLevelItem(i)
            if node.data(0, PAGE_ROLE) == key:
                self.nav.setCurrentItem(node)
                break
        self.nav.blockSignals(False)

    def _on_nav_changed(self, current, _previous) -> None:
        if current is None:
            return
        key = str(current.data(0, PAGE_ROLE) or "")
        for i in range(self.stack.count()):
            if self.stack.widget(i).objectName() == key:
                self.stack.setCurrentIndex(i)
                namespace = ("scene" if self._target is None else
                             "multi" if isinstance(self._target, (list, tuple))
                             else "element")
                self._last_page[namespace] = key
                return

    def _clear(self) -> None:
        self.nav.blockSignals(True)
        self.nav.clear()
        self.nav.blockSignals(False)
        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            # 必须脱离对象树：deleteLater() 是延迟删除，旧页控件会继续被
            # findChildren() 命中，导致自动化拿到错误的输入框。
            widget.setParent(None)
            widget.deleteLater()

    def _add_page(self, key: str, title: str, widget: QWidget) -> None:
        widget.setObjectName(key)
        self.stack.addWidget(widget)
        node = QTreeWidgetItem([title])
        node.setData(0, PAGE_ROLE, key)
        self.nav.addTopLevelItem(node)

    def show_empty(self, title: str, hint: str) -> None:
        self._clear()
        placeholder = QWidget(self.stack)
        placeholder.setObjectName("empty")
        lay = QVBoxLayout(placeholder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(EmptyState(title, hint, placeholder))
        self.stack.addWidget(placeholder)

    # ------------------------------------------------------------------
    # 编辑提交
    # ------------------------------------------------------------------
    def _commit(self, action) -> None:
        """所有字段的 signal 都走这里：直写图元 + 广播 + 通知撤销栈。"""
        if self._updating or self._target is None:
            return
        action()
        if self.scene is not None:
            self.scene.notify_edit(self._target)
        self.itemEdited.emit(self._target)

    def refresh_geometry(self, _item=None) -> None:
        """画布上移动/缩放后，把 X/Y/W/H 显示同步回来（不发信号）。"""
        if self._target is not None and hasattr(self._target, "page_center"):
            self._updating = True
            try:
                for widget, getter in self._geo_bindings:
                    widget.blockSignals(True)
                    widget.setValue(float(getter()))
                    widget.blockSignals(False)
            finally:
                self._updating = False

    @staticmethod
    def _card(page: PropertyPage, title: str) -> SectionCard:
        card = SectionCard(title, page)
        page.add_card(card)
        return card

    def _make_parent_combo(self, it) -> QComboBox:
        """父对象选择框：列出其它图元，选「（无）」即清除父对象。"""
        combo = QComboBox()
        combo.addItem("（无）", 0)
        scene = it.scene()
        if scene is not None and hasattr(scene, "all_items"):
            for other in scene.all_items():
                if other.item_id == it.item_id:
                    continue
                combo.addItem(f"{other.get_name()}  #{other.item_id}", other.item_id)
        cur = int(getattr(it, "parent_id", 0) or 0)
        idx = combo.findData(cur)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _i: self._set_parent(it, int(combo.currentData()))
        )
        return combo

    def _set_parent(self, it, pid: int) -> None:
        """改父对象；成功与否都要重建分页（坐标口径会在场景 / 父坐标系间切换）。"""
        done = {"ok": False}

        def apply() -> None:
            done["ok"] = bool(it.set_page_parent(pid))

        self._commit(apply)
        # 延后重建：此刻正在 combo 自己的信号里，立刻删控件会崩
        QTimer.singleShot(0, lambda: self.update_for_selected(it))

    # ------------------------------------------------------------------
    # 单选：常规 / 外观 / 布局
    # ------------------------------------------------------------------
    def _build_item(self, it) -> None:
        self._add_page("general", "常规", self._page_general(it))
        self._add_page("appearance", "外观", self._page_appearance(it))
        self._add_page("layout", "布局", self._page_layout(it))
        extra = self._page_specific(it)
        if extra is not None:
            key, title, widget = extra
            # 类型特有页排在最前（与旧 text/group 页顺序一致）
            self._insert_first(key, title, widget)

    def _insert_first(self, key, title, widget) -> None:
        widget.setObjectName(key)
        self.stack.insertWidget(0, widget)
        node = QTreeWidgetItem([title])
        node.setData(0, PAGE_ROLE, key)
        self.nav.insertTopLevelItem(0, node)

    def _page_general(self, it) -> PropertyPage:
        page = PropertyPage()
        basic = self._card(page, "基本信息")
        name_edit = make_line(it.get_name(), tooltip="图元名称，图层树按它显示")
        name_edit.editingFinished.connect(
            lambda: self._commit(lambda: it.set_name(name_edit.text()))
        )
        basic.add_row(("名称", name_edit))
        basic.add_row(("类型", make_value_label(TYPE_LABELS.get(it.TYPE, it.TYPE))),
                      ("ID", make_value_label(str(it.item_id))))
        # 父对象：可设 / 可清空（逻辑父对象，父移动时自身随动）
        parent_combo = self._make_parent_combo(it)
        basic.add_row(("父对象", parent_combo),
                      ("成员数", make_value_label(str(len(it.children_ids)))))
        basic.add_hint("设置父对象后，本图元的坐标改成父坐标系里的坐标：父对象平移 / 旋转"
                       "会带着它一起走，它自己不能再单独平移，但可以自己旋转。")

        state = self._card(page, "显示与层级")
        vis = make_check("显示", it.get_visibility(), tooltip="取消勾选后画布上隐藏")
        vis.toggled.connect(
            lambda value: self._commit(lambda: it.set_visibility(bool(value)))
        )
        state.add_row(("层级 Z", make_value_label(f"{it.zValue():g}")),
                      ("可见性", vis))
        cx, cy = it.page_center()
        state.add_row(("可选中", make_value_label("是" if it.get_selectable() else "否")),
                      ("中心点", make_value_label(f"{cx:.1f}, {cy:.1f}")))
        zbox = make_int(int(it.zValue()), -100000, 100000, 1,
                        tooltip="层级；数值越大越靠前")
        zbox.valueChanged.connect(
            lambda value: self._commit(lambda: it.set_page_field("zValue", float(value)))
        )
        state.add_row(("Z 值", zbox))
        return page

    def _page_appearance(self, it) -> PropertyPage:
        page = PropertyPage()
        card = self._card(page, "描边与填充")
        stroke = ColorField(parse_color(it.style_value("stroke", "#000000")))
        stroke.colorChanged.connect(
            lambda c: self._commit(lambda: it.set_style_value("stroke", color_str(c)))
        )
        width = make_int(int(float(it.style_value("strokeWidth", 2))), 0, 64, 1,
                         tooltip="描边宽度，0 表示不描边")
        width.valueChanged.connect(
            lambda v: self._commit(lambda: it.set_style_value("strokeWidth", int(v)))
        )
        card.add_row(("描边色", stroke), ("线宽", width))

        fill_color = ColorField(parse_color(it.style_value("fill_color", "#ffffff")))
        fill_color.colorChanged.connect(
            lambda c: self._commit(lambda: it.set_style_value("fill_color", color_str(c)))
        )
        fill = make_check("启用", bool(it.style_value("fill", False)),
                          tooltip="关闭时只画描边，内部透明")
        fill.toggled.connect(
            lambda v: self._commit(lambda: it.set_style_value("fill", bool(v)))
        )
        card.add_row(("填充色", fill_color), ("填充", fill))

        opacity = OpacityField(int(it.style_value("opacity", 255)))
        opacity.valueChanged.connect(
            lambda v: self._commit(lambda: it.set_style_value("opacity", int(v)))
        )
        card.add_row(("不透明度", opacity))

        if it.TYPE in ("rect", "circle", "text", "image", "checkbox", "widget"):
            radius = make_int(int(float(it.style_value("cornerRadius", 0))), 0, 9999, 1,
                              tooltip="圆角半径（场景单位）")
            radius.valueChanged.connect(
                lambda v: self._commit(lambda: it.set_style_value("cornerRadius", float(v)))
            )
            card.add_row(("圆角", radius))
        if it.TYPE in ("text", "widget"):
            size = make_int(int(float(it.style_value("font_size", 10))), 4, 200, 1,
                            tooltip="字号（pt）")
            size.valueChanged.connect(
                lambda v: self._commit(lambda: it.set_style_value("font_size", int(v)))
            )
            card.add_row(("字号", size))
        card.add_hint("颜色控件里的不透明度会写进 style.opacity，与旧 Core 一致。")
        return page

    def _page_layout(self, it) -> PropertyPage:
        page = PropertyPage()
        # 有父对象时坐标即「父坐标系」坐标（父图元可视中心为原点、父角度为朝向）；
        # 无父对象时就是场景坐标。两种情况都走 *_local_* 口径，代码同一套。
        parented = bool(it.parent_id)
        title = "位置与尺寸（父坐标系）" if parented else "位置与尺寸（场景坐标）"
        card = self._card(page, title)
        cx, cy = it.page_local_center()
        w, h = it.page_size()
        x_box = make_double(cx, decimals=3,
                            tooltip="中心 X" + ("（相对父图元中心）" if parented else ""))
        y_box = make_double(cy, decimals=3,
                            tooltip="中心 Y" + ("（相对父图元中心）" if parented else ""))
        x_box.valueChanged.connect(
            lambda v: self._commit(lambda: it.set_page_center(v, it.page_center()[1]))
        )
        y_box.valueChanged.connect(
            lambda v: self._commit(lambda: it.set_page_center(it.page_center()[0], v))
        )
        if parented:
            # 有父对象：不能自行平移，位置只由父对象带动，输入框只读展示
            x_box.setEnabled(False)
            y_box.setEnabled(False)
        card.add_row(("中心 X", x_box), ("中心 Y", y_box))
        self._geo_bindings.extend([
            (x_box, lambda: it.page_local_center()[0]),
            (y_box, lambda: it.page_local_center()[1]),
        ])

        # 宽/高：矩形类改几何矩形，顶点类按比例缩放顶点；两个方向都可能因
        # 「当前长度为 0」（水平 / 垂直线）而无法缩放，此时只读展示。
        explicit = it.has_explicit_geometry()
        w_ok = explicit or w > 1e-6
        h_ok = explicit or h > 1e-6
        w_box = make_double(w, 0.0 if explicit else 0.1, 1e6, 1.0, 3, tooltip="宽")
        h_box = make_double(h, 0.0 if explicit else 0.1, 1e6, 1.0, 3, tooltip="高")
        w_box.valueChanged.connect(
            lambda v: self._commit(lambda: it.set_page_size(v, it.page_size()[1]))
        )
        h_box.valueChanged.connect(
            lambda v: self._commit(lambda: it.set_page_size(it.page_size()[0], v))
        )
        if not w_ok:
            w_box.setEnabled(False)
            w_box.setToolTip("该方向长度为 0（端点在同一竖线上），请在画布上拖端点")
        if not h_ok:
            h_box.setEnabled(False)
            h_box.setToolTip("该方向长度为 0（端点在同一横线上），请在画布上拖端点")
        card.add_row(("宽 W", w_box), ("高 H", h_box))
        self._geo_bindings.extend([
            (w_box, lambda: it.page_size()[0]),
            (h_box, lambda: it.page_size()[1]),
        ])

        # 旋转不被父对象锁：子图元可以自己转（绕自己的支点，带后代一起转）
        angle = make_double(it.page_local_angle(), -360.0, 360.0, 1.0, 3,
                            tooltip="旋转角（度）"
                                    + ("，相对父图元" if parented else ""))
        angle.valueChanged.connect(
            lambda v: self._commit(lambda: it.set_page_local_angle(v))
        )
        card.add_row(("旋转", angle))
        self._geo_bindings.append((angle, lambda: it.page_local_angle()))

        ox, oy = it.page_local_origin()
        ox_box = make_double(ox, decimals=3,
                             tooltip="旋转中心 X，默认等于几何中心")
        oy_box = make_double(oy, decimals=3,
                             tooltip="旋转中心 Y，默认等于几何中心")
        ox_box.valueChanged.connect(
            lambda v: self._commit(
                lambda: it.set_page_local_origin(v, it.page_local_origin()[1]))
        )
        oy_box.valueChanged.connect(
            lambda v: self._commit(
                lambda: it.set_page_local_origin(it.page_local_origin()[0], v))
        )
        card.add_row(("旋转中心 X", ox_box), ("旋转中心 Y", oy_box))
        self._geo_bindings.extend([
            (ox_box, lambda: it.page_local_origin()[0]),
            (oy_box, lambda: it.page_local_origin()[1]),
        ])
        card.add_hint("旋转中心默认是几何中心；也可以直接在画布上右键，"
                      "选「旋转中心设到此处」把支点钉在指定位置。")
        if not explicit:
            card.add_hint("该图元的形状由顶点 / 端点决定：宽高按比例缩放顶点"
                          "（保持形状），改形状本身请在画布上拖点。")
            card.add_hint("「中心」是图元自己身上的中心点（默认即几何中心）："
                          "旋转时它和旋转中心都钉在原地，不随转完的包围盒移动。")

        if parented:
            parent = self.scene.find_item(it.parent_id) if self.scene is not None else None
            name = parent.get_name() if parent is not None else f"#{it.parent_id}"
            card.add_hint(f"该图元有父对象「{name}」：坐标以父图元中心为原点，"
                          f"父对象怎么动这组数都不变；不能单独平移，"
                          f"但可以自己旋转（绕上面的旋转中心）。")

        rect = it.page_bounding_rect()
        card.add_row(("场景包围盒", make_value_label(
            f"{rect.left():.1f}, {rect.top():.1f}  {rect.width():.1f}×{rect.height():.1f}"
        )))
        card.add_hint("未编辑的字段保存时原样回写，page JSON 不会被重排。")
        return page

    # ------------------------------------------------------------------
    # 类型特有页
    # ------------------------------------------------------------------
    def _page_specific(self, it):
        if it.TYPE == "text":
            page = PropertyPage()
            card = self._card(page, "文本内容")
            edit = make_textarea(str(it.context or ""), "输入显示文本…", min_height=90)
            edit.textChanged.connect(
                lambda: self._commit(lambda: it.set_page_field("context", edit.toPlainText()))
            )
            card.add_widget(edit)
            return "context", "文本内容", page

        if it.TYPE == "image":
            page = PropertyPage()
            card = self._card(page, "图片来源")
            path_edit = make_line(str(it.image_path or ""), read_only=True)
            card.add_row(("文件", path_edit))
            browse = QPushButton("浏览…")
            browse.setObjectName("propField")
            browse.clicked.connect(lambda: self._pick_image(it, path_edit))
            card.add_widget(browse)
            card.add_hint("图片名按 basename 在资源目录里查找；缺失时只画边框。")
            return "image", "图片", page

        if it.TYPE == "checkbox":
            page = PropertyPage()
            card = self._card(page, "交互状态")
            checked = make_check("默认勾选", bool(it.checked))
            checked.toggled.connect(
                lambda v: self._commit(lambda: it.set_page_field("checked", bool(v)))
            )
            toggle = make_check("运行时可切换", bool(it.page_record().get("toggleEnabled", True)))
            toggle.toggled.connect(
                lambda v: self._commit(lambda: it.set_page_field("toggleEnabled", bool(v)))
            )
            card.add_row(("状态", checked), ("交互", toggle))
            return "interaction", "交互", page

        if it.TYPE == "widget":
            page = PropertyPage()
            card = self._card(page, "占位控件")
            card.add_row(("类型", make_value_label(
                str(it.page_record().get("widgetType", "label")))))
            card.add_row(("文本", make_value_label(
                str(it.page_record().get("widgetText", "")))))
            card.add_hint("CoreQGraphics 的 widget 图元只画占位框，"
                          "不创建 EmbeddedWidgetLayer 真实控件。")
            return "widget", "控件", page

        if it.TYPE == "group":
            page = PropertyPage()
            card = self._card(page, "组成员")
            listing = QListWidget()
            listing.setObjectName("propMemberList")
            listing.setFixedHeight(120)
            for cid in it.children_ids:
                child = self.scene.find_item(cid) if self.scene is not None else None
                label = child.get_name() if child is not None else f"(缺失 {cid})"
                listing.addItem(f"{cid:>5}   {label}")
            card.add_widget(listing)
            return "members", "组成员", page

        if it.TYPE in ("line", "triangle", "polygon", "path"):
            page = PropertyPage()
            card = self._card(page, "顶点几何")
            verts = it.page_record().get("vertices") or []
            if it.TYPE == "line":
                text = (f"起点 {it.page_record().get('head_pos')}  "
                        f"终点 {it.page_record().get('end_pos')}")
            else:
                text = f"{len(verts)} 个顶点（场景绝对坐标）"
            card.add_row(("几何", make_value_label(text)))
            card.add_hint("顶点在 page JSON 里已烘焙 rotate，"
                          "属性面板不提供逐点编辑（避免与 Qt 几何不同步）。")
            return "vertices", "顶点", page
        return None

    def _pick_image(self, it, path_edit) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.svg)"
        )
        if not file_name:
            return
        name = QFileInfo(file_name).fileName()
        self._commit(lambda: it.set_page_field("image_path", name))
        path_edit.setText(name)

    # ------------------------------------------------------------------
    # 空选中 / 多选
    # ------------------------------------------------------------------
    def _build_scene(self) -> None:
        page = PropertyPage()
        card = self._card(page, "页面")
        scene = self.scene
        count = len(scene.all_items()) if scene is not None else 0
        card.add_row(("图元数", make_value_label(str(count))))
        if scene is not None:
            r = scene.view_scene_rect()
            card.add_row(("保存视图", make_value_label(
                f"{r.x():.0f}, {r.y():.0f}  {r.width():.0f}×{r.height():.0f}")))
            bg = ColorField(scene.backgroundBrush().color())
            bg.colorChanged.connect(
                lambda c: self._scene_background(c)
            )
            card.add_row(("背景色", bg))
        card.add_hint("背景色随 page JSON 的 backgroundColor 字段保存。")
        self._add_page("scene", "页面属性", page)

    def _scene_background(self, color: QColor) -> None:
        if self.scene is None:
            return
        self.scene.set_background(color)
        self.scene.notify_edit(None)
        self.itemEdited.emit(None)

    def _build_multi(self, items) -> None:
        page = PropertyPage()
        card = self._card(page, "选择概要")
        actual = [it for it in items if hasattr(it, "TYPE")]
        kinds: dict[str, int] = {}
        for it in actual:
            kinds[it.TYPE] = kinds.get(it.TYPE, 0) + 1
        card.add_row(("数量", make_value_label(str(len(items)))),
                     ("类型数", make_value_label(str(len(kinds)))))
        detail = "  ".join(f"{TYPE_LABELS.get(k, k)}×{v}" for k, v in
                           sorted(kinds.items(), key=lambda kv: -kv[1])[:8])
        card.add_row(("类型分布", make_value_label(detail or "—")))
        if actual:
            zs = [it.zValue() for it in actual]
            card.add_row(("Z 范围", make_value_label(f"{min(zs):g} ~ {max(zs):g}")))
        card.add_hint("多选状态只做汇总；要看或编辑具体某个图元，请单独点选它"
                      "或在图层树里定位。")
        self._add_page("multi", "选择概要", page)
