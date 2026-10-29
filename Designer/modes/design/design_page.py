"""One design page: a QuadTreeScene plus its SceneManager and timer state."""

from __future__ import annotations

import json
import os
import tempfile

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

from Designer.Core.elements import (
    base_element,
    circle_element,
    group_element,
    image_element,
    line_element,
    rect_element,
    text_element,
    triangle_element,
)

from Designer.Core.myQuadTreeScene import SceneManager, SceneSerializer
from Designer.Core.my_common import SceneMode
from Designer.Core.myGraphicsScene import DEFAULT_BACKGROUND_COLOR

from .design_scene import DesignScene
from .element_factory import TOOL_DEFINITIONS_BY_KEY, create_element
from .page_history import PageHistory
from .project_store import PageMeta, ProjectStore


class DesignPage(QObject):
    """Owns the scene and the per-page persistence bookkeeping."""

    itemCountChanged = Signal(str, int)

    def __init__(self, meta: PageMeta, store: ProjectStore, parent=None):
        super().__init__(parent)
        self.meta = meta
        self.store = store
        self.loaded = False
        self.load_error = None
        self._suspend_item_signals = False

        self.scene = DesignScene(parent=parent)
        self.scene.setObjectName(f"design_scene_{meta.id}")
        # The inherited right-click "save/load elements" actions must target
        # this page, never the run-mode datas/data.json.
        self.scene.scene_file_path = self.store.page_path(meta)
        self.manager = SceneManager(self.scene, parent=self)
        self.scene.set_scene_manager(self.manager)

        # Design mode is the only state a design page should ever enter.
        self.scene.set_scene_mode(SceneMode.Design)
        self.scene.show_grid(True)
        self.scene.show_coordinate(True)

        self.scene.elementDropped.connect(self._on_element_dropped)
        self.manager.completed_item_signal.connect(self._on_items_changed)
        self.manager.delete_item_signal.connect(self._on_items_changed)

        # Keep the inherited right-click "draw" commands functional instead of
        # leaving dead menu entries in design mode.  The toolbox buttons use the
        # same entry point, so both start the identical click-to-draw flow.
        self.scene.action_begin_draw_line.connect(
            lambda: self.begin_draw_element(line_element)
        )
        self.scene.action_begin_draw_rect.connect(
            lambda: self.begin_draw_element(rect_element)
        )
        self.scene.action_begin_draw_triangle.connect(
            lambda: self.begin_draw_element(triangle_element)
        )
        self.scene.action_begin_draw_circle.connect(
            lambda: self.begin_draw_element(circle_element)
        )
        self.scene.action_begin_new_text.connect(
            lambda: self.begin_draw_element(text_element)
        )
        self.scene.action_begin_new_image.connect(
            lambda: self.begin_draw_element(image_element)
        )
        self.scene.action_set_group.connect(self._group_selected_items)

        # Undo/redo history for this page.  It is created after the scene and
        # manager exist and re-baselines itself in ``load()``.
        self.history = PageHistory(self)

        # A page that is not visible must not keep redrawing at 60 FPS.  The
        # window starts the timers again when the page is activated.
        self.deactivate()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load(self) -> None:
        self._suspend_item_signals = True
        try:
            self.scene.load_element_info(self.store.page_path(self.meta))
        finally:
            self._suspend_item_signals = False
        self.loaded = True
        # The file on disk is the new starting point: undo must not walk back
        # into the previous session's history.
        self.history.reset()
        self.itemCountChanged.emit(self.meta.id, self.item_count)

    def save(self) -> None:
        if self.loaded:
            # Fold a still-pending edit into the history first, so a state the
            # user can see on disk is always reachable with undo.
            self.history.commit()
            self.store.save_page(self.meta, self.scene)

    # ------------------------------------------------------------------
    # Undo/redo snapshots
    # ------------------------------------------------------------------
    def capture_snapshot(self) -> str:
        """Serialize the page content for the undo history.

        The layout matches a page file (``backgroundColor`` + ``items``) but
        deliberately leaves out ``sceneRect``: undo/redo must never move the
        camera or change the range "调整视图" restores.
        """

        background = self.scene.get_bg_color()
        if not isinstance(background, QColor) or not background.isValid():
            background = QColor(DEFAULT_BACKGROUND_COLOR)

        items = []
        for item in self.scene.findChildren(base_element):
            data = SceneSerializer.item_to_dict(item)
            children = data.get("children_ids")
            if children:
                # ``m_children`` is a set, so its iteration order is arbitrary;
                # sorting keeps two captures of the same page comparable.
                data["children_ids"] = sorted(children)
            items.append(data)
        items.sort(key=lambda entry: entry.get("id", 0))

        return json.dumps(
            {
                "backgroundColor": background.name(QColor.HexArgb),
                "items": items,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def restore_snapshot(self, snapshot: str) -> bool:
        """Rebuild the page content from a snapshot produced above.

        Restoring goes through ``SceneSerializer`` (the page file loader), so
        ids, names, parent/child links, z-order and the quadtree end up exactly
        as they would after reopening a saved page.
        """

        try:
            data = json.loads(snapshot)
        except (TypeError, ValueError) as exc:
            print(f"撤销快照解析失败: {exc}")
            return False
        if not isinstance(data, dict):
            return False

        handle, path = tempfile.mkstemp(prefix="design_snapshot_", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
            self._suspend_item_signals = True
            try:
                self.scene.load_element_info(path)
            finally:
                self._suspend_item_signals = False
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

        self.scene.set_current_select_item(self.scene)
        self.scene.update()
        self.itemCountChanged.emit(self.meta.id, self.item_count)
        return True

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------
    def activate(self) -> None:
        self.history.activate()
        scene = self.scene
        for name, interval in (
            ("render_timer", 16),
            ("frame_count_timer", 1000),
            ("timer1", 500),
        ):
            timer = getattr(scene, name, None)
            if timer is not None and not timer.isActive():
                timer.start(interval)
        self.scene.setFocus()

    def deactivate(self) -> None:
        self.history.deactivate()
        for name in ("render_timer", "frame_count_timer", "timer1", "timer2"):
            timer = getattr(self.scene, name, None)
            if timer is not None:
                timer.stop()

    def dispose(self) -> None:
        self.deactivate()
        self.history.shutdown()
        self.scene.deleteLater()
        # The page QObject is parented to the window; drop that ownership so a
        # deleted page (and its SceneManager) can actually be released.
        self.setParent(None)
        self.deleteLater()

    # ------------------------------------------------------------------
    # Interactive drawing (right-click menu and toolbox click)
    # ------------------------------------------------------------------
    def begin_draw_element(self, element_class):
        """Create ``element_class`` in the legacy click-to-draw state.

        Both the inherited right-click "绘制..." commands and the toolbox
        buttons call this, so a new element follows the mouse and is finished
        by clicking the canvas instead of appearing with a default size.
        """

        self._discard_pending_draw()
        self.scene.setFocus()
        return self.manager.createItem(element_class)

    def begin_draw_tool(self, tool_key: str):
        """Start drawing the toolbox element identified by ``tool_key``."""

        definition = TOOL_DEFINITIONS_BY_KEY.get(tool_key)
        if definition is None:
            print(f"未知的设计控件: {tool_key}")
            return None
        return self.begin_draw_element(definition.element_class)

    def _discard_pending_draw(self) -> None:
        """Remove an unfinished element left over from a previous draw command."""

        scene = self.scene
        item = getattr(scene, "current_element", None)
        if item is None:
            return
        try:
            if not item.get_actived():
                return
        except RuntimeError:
            # The C++ object is already gone; just forget the stale reference.
            scene.current_element = None
            scene.current_element_id = 0
            return

        scene.current_element = None
        scene.current_element_id = 0
        if item.id() in self.manager.m_items:
            # Already registered; only stop the pending state.
            return

        try:
            if item.m_scene is not None:
                item.m_scene.shine_flag_change.disconnect(item.handle_shine_flag)
        except (RuntimeError, TypeError):
            pass
        item.m_scene = None
        item.m_scene_manager = None
        item.setParent(None)
        item.deleteLater()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_element_dropped(self, tool_key: str, scene_pos) -> None:
        create_element(self.manager, tool_key, scene_pos)

    def _group_selected_items(self, items) -> None:
        """Create a group from the right-click selection.

        ``QuadTreeScene.action_set_group`` has no receiver in design mode
        unless we connect it here (the legacy main window connects its own
        handler).  Only top-level scene items may become members; the scene
        already filters them, but the signal is public so validate again.
        """

        members = []
        seen_ids = set()
        for item in items or []:
            if not isinstance(item, base_element):
                continue
            if item.m_scene is not self.scene:
                continue
            if item.is_has_parent() or item.is_in_group():
                continue
            if item.id() in seen_ids:
                continue
            seen_ids.add(item.id())
            members.append(item)

        if not members:
            print("未选择需要组合的元素")
            return

        group = self.manager.createItem(group_element, *members)
        # Group creation selects itself internally, but the scene's
        # current-selected item also drives the property panel/status bar.
        self.scene.set_current_select_item(group)
        self.scene.update()

    def _on_items_changed(self, *_args) -> None:
        if self._suspend_item_signals:
            return
        self.itemCountChanged.emit(self.meta.id, len(self.manager.m_items))

    @property
    def item_count(self) -> int:
        return len(self.manager.m_items)
