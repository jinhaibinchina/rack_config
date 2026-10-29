"""Scene widget used by design-mode pages.

The subclass adds drop handling and a manager-aware delete operation.  All
drawing, zooming, panning, snapping, serialization and quadtree behaviour is
inherited from the existing ``QuadTreeScene``.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal

# from my_elements_v2 import base_element, group_element
from Designer.Core.element import base_element
from Designer.Core.elements import group_element

from Designer.Core.myQuadTreeScene import QuadTreeScene

from .element_factory import ELEMENT_MIME_TYPE
from .template_store import TEMPLATE_MIME_TYPE



class DesignScene(QuadTreeScene):
    """One design page's scene/view."""

    elementDropped = Signal(str, QPointF)
    templateDropped = Signal(str, QPointF)
    groupTemplateRequested = Signal(object)
    undoRequested = Signal()
    redoRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setAcceptDrops(True)

    def snap_auto_enabled(self) -> bool:
        # 设计模式：鼠标停顿不自动吸附，仅按 T 时把光标吸到当前捕捉点。
        return False

    def snap_to_current_point(self) -> bool:
        """按 T 时把鼠标立即吸附到当前捕捉点（无需再移动鼠标）。

        捕捉点扫描（update_grid / update_endpoints / snap_to_point）始终在
        on_mouse_move 中运行，所以 current_snap_pos 是实时最新的；这里只需
        把光标拉过去并通知图元跟随。返回是否吸附成功。
        """
        snap_pos = self.snapSys.current_snap_pos
        if snap_pos is None:
            status_bar = getattr(self, "statusBar", None)
            if status_bar is not None:
                status_bar.showMessage("附近没有捕捉点，按 T 吸附失败", 2000)
            return False
        self.snapSys.move_cursor_to_snaped_pos_V2(snap_pos, True)
        return True

    # ------------------------------------------------------------------
    # Drag & drop from the toolbox dock
    # ------------------------------------------------------------------
    def _drop_format(self, mime_data):
        if mime_data.hasFormat(ELEMENT_MIME_TYPE):
            return ELEMENT_MIME_TYPE
        if mime_data.hasFormat(TEMPLATE_MIME_TYPE):
            return TEMPLATE_MIME_TYPE
        return ""

    def dragEnterEvent(self, event):
        if self._drop_format(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._drop_format(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime_type = self._drop_format(event.mimeData())
        if not mime_type:
            super().dropEvent(event)
            return

        raw_payload = bytes(event.mimeData().data(mime_type))
        try:
            payload = raw_payload.decode("utf-8")
        except UnicodeDecodeError:
            payload = ""

        if payload:
            scene_pos = self.window_position_to_scene(event.position())
            if mime_type == TEMPLATE_MIME_TYPE:
                self.templateDropped.emit(payload, scene_pos)
            else:
                self.elementDropped.emit(payload, scene_pos)

        event.setDropAction(Qt.CopyAction)
        event.accept()
        self.setFocus()


    def window_position_to_scene(self, window_pos: QPointF) -> QPointF:
        """Convert a widget-space position to the scene's logical coordinates.

        This mirrors ``myGraphicsScene.mouseMoveEvent`` so a dropped element
        lands exactly where the mouse cursor is, also when the page is panned
        or zoomed.
        """

        scale = self.scale_factor if self.scale_factor else 1.0
        view_pos = QPointF(
            window_pos.x() / scale + self.view_x0,
            window_pos.y() / scale + self.view_y0,
        )
        return self.viewToScene(view_pos)

    # ------------------------------------------------------------------
    # Selection / deletion
    # ------------------------------------------------------------------
    def delete_selected_items(self) -> int:
        """Delete selected top-level items through the SceneManager.

        ``myGraphicsScene.deleteSelectedItems`` removes items directly from the
        view, leaving stale entries in ``SceneManager.m_items``.  Design mode
        always goes through the manager so IDs, names and serialization stay
        consistent.  ``base_element.Delete`` removes the members of a selected
        group as well, so one Delete press takes the whole group away.
        """

        selected = [
            item
            for item in self.findChildren(base_element)
            if item.get_selected() and not item.is_has_parent()
        ]
        if not selected:
            return 0

        manager = getattr(self, "scene_manager", None)
        before = len(manager.m_items) if manager is not None else 0
        for item in selected:
            item.set_selected(False)
            item.Delete()
        removed = before - len(manager.m_items) if manager is not None else 0

        self.set_current_select_item(self)
        self.update()
        return removed or len(selected)

    def select_all_items(self) -> None:
        for item in self.findChildren(base_element):
            if not item.is_has_parent():
                item.set_selected(True)
        self.set_current_select_item(self)
        self.selectionChanged.emit()
        self.update()

    def clear_selection(self) -> None:
        for item in self.findChildren(base_element):
            item.set_selected(False)
        self.set_current_select_item(self)
        self.selectionChanged.emit()
        self.update()

    def selected_group(self):
        """Return the one selected top-level group, if there is exactly one."""

        groups = [
            item
            for item in self.findChildren(base_element)
            if item.get_selected()
            and not item.is_has_parent()
            and isinstance(item, group_element)
        ]
        return groups[0] if len(groups) == 1 else None

    def extend_context_menu(self, menu) -> None:
        """Append design-mode specific actions to the inherited menu."""

        group = self.selected_group()
        if group is not None:
            menu.addSeparator()
            action = menu.addAction("添加到控件工具箱")
            action.setToolTip("把选中的组保存为可复用的组合模板")
            action.triggered.connect(
                lambda checked=False, selected=group: self.groupTemplateRequested.emit(
                    selected
                )
            )

    def keyPressEvent(self, event):
        # Scene-scoped editing shortcuts.  They are intentionally not window
        # shortcuts so typing in a property editor keeps its normal behaviour.
        has_ctrl = bool(event.modifiers() & Qt.ControlModifier)
        if has_ctrl and event.key() == Qt.Key_C:
            self.copy_selected()
            event.accept()
            return
        if has_ctrl and event.key() == Qt.Key_V:
            self.paste()
            event.accept()
            return
        if has_ctrl and event.key() == Qt.Key_A:
            self.select_all_items()
            event.accept()
            return
        if has_ctrl and event.key() == Qt.Key_Z:
            # Shift+Ctrl+Z and Ctrl+Y are the two common redo bindings.
            if event.modifiers() & Qt.ShiftModifier:
                self.redoRequested.emit()
            else:
                self.undoRequested.emit()
            event.accept()
            return
        if has_ctrl and event.key() == Qt.Key_Y:
            self.redoRequested.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Delete and not has_ctrl:
            self.delete_selected_items()
            event.accept()
            return
        if event.key() == Qt.Key_T and not has_ctrl:
            self.snap_to_current_point()
            event.accept()
            return
        super().keyPressEvent(event)
