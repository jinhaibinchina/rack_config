"""Per-page undo/redo history for design mode.

Design-mode edits reach the scene through many different paths (toolbox
drops, click-to-draw elements, grouping, property panel edits, alignment
helpers, deletions).  Instead of pushing an undo command from every one of
them, the history stores serialized scene snapshots: whenever the scene
reports a change the current state is captured, and undo/redo simply rebuilds
the page from a stored snapshot.

Snapshots reuse the same element ``to_dict()`` format as the page files, so
restoring goes through the regular ``SceneSerializer`` code path that also
opens a saved page.  That keeps undo/redo in sync with every element type the
page format supports, including nested groups.
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QObject, QTimer, Signal


class PageHistory(QObject):
    """Snapshot based undo/redo stack for one design page."""

    #: Emitted whenever undo/redo availability or depth changes.
    changed = Signal()

    #: Undo steps kept in memory.  The design mode requirement is at least 3.
    DEFAULT_LIMIT = 20

    #: Delay used to coalesce a burst of scene changes into a single step, so
    #: dragging an item does not fill the whole stack with tiny movements.
    SETTLE_MS = 400

    #: Safety net for edits that change the page without emitting a scene
    #: signal (opacity, image path, text content...): when the scene has been
    #: quiet for this long, take a look anyway.  Only runs for visible pages.
    IDLE_CHECK_MS = 1200

    def __init__(self, page, limit: int = DEFAULT_LIMIT, parent=None) -> None:
        super().__init__(page if parent is None else parent)
        self.page = page
        self.limit = max(int(limit), 3)
        self._states: List[str] = []
        self._index = -1
        self._applying = False

        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(self.SETTLE_MS)
        self._settle.timeout.connect(self.commit)

        self._idle = QTimer(self)
        self._idle.setInterval(self.IDLE_CHECK_MS)
        self._idle.timeout.connect(self._check_idle)

        self._connect_scene()
        self.reset()

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def _connect_scene(self) -> None:
        """Record every scene change that can alter the saved page content."""

        scene = self.page.scene
        manager = self.page.manager
        # Item creation / deletion through the SceneManager.
        manager.completed_item_signal.connect(self._on_scene_changed)
        manager.delete_item_signal.connect(self._on_scene_changed)
        # Geometry (move/resize/rotation) and style edits (colour, width,
        # text content) are reported through these two repaint hooks.
        scene.item_GeometryChange.connect(self._on_scene_changed)
        scene.item_DirtyChange.connect(self._on_scene_changed)

    def shutdown(self) -> None:
        """Stop pending work before the owning page is destroyed."""

        self._settle.stop()
        self._idle.stop()

    def activate(self) -> None:
        """Watch for silent edits while the page is visible."""

        if not self._idle.isActive():
            self._idle.start()

    def deactivate(self) -> None:
        """A hidden page does not need the idle scan."""

        self._idle.stop()

    def _check_idle(self) -> None:
        if self._applying or self._settle.isActive():
            # A burst of scene changes is already being tracked.
            return
        self.commit()

    # ------------------------------------------------------------------
    # Stack maintenance
    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Drop the stack and use the current scene as the new baseline."""

        self._settle.stop()
        self._states = [self._capture()]
        self._index = 0
        self.changed.emit()

    def _capture(self) -> str:
        try:
            return self.page.capture_snapshot()
        except Exception as exc:  # never let history break editing
            print(f"撤销历史快照失败: {exc}")
            return ""

    def _on_scene_changed(self, *_args) -> None:
        if self._applying:
            return
        self._settle.start()

    def commit(self) -> None:
        """Push the current scene state if it differs from the latest one."""

        self._settle.stop()
        if self._applying:
            return
        state = self._capture()
        if not state or state == self._states[self._index]:
            return

        # A new edit invalidates the redo branch.
        del self._states[self._index + 1:]
        self._states.append(state)
        self._index += 1
        while self._index > self.limit:
            self._states.pop(0)
            self._index -= 1
        self.changed.emit()

    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------
    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index + 1 < len(self._states)

    @property
    def undo_depth(self) -> int:
        """How many undo steps are currently available."""

        return max(self._index, 0)

    @property
    def redo_depth(self) -> int:
        """How many redo steps are currently available."""

        return max(len(self._states) - 1 - self._index, 0)

    def undo(self) -> bool:
        # Pick up any edit the debounce timer has not pushed yet, otherwise
        # Ctrl+Z right after a drag would skip the drag itself.
        self.commit()
        if not self.can_undo:
            return False
        return self._apply(self._index - 1)

    def redo(self) -> bool:
        self.commit()
        if not self.can_redo:
            return False
        return self._apply(self._index + 1)

    def _apply(self, index: int) -> bool:
        state = self._states[index]
        self._applying = True
        try:
            restored = self.page.restore_snapshot(state)
        finally:
            self._applying = False
            self._settle.stop()
        if not restored:
            return False

        self._index = index
        # Rebuilding goes through the serializer, so an immediate re-capture
        # should match ``state``.  Re-baseline anyway; that guarantees a later
        # capture can never create a duplicate step for the same content.
        current = self._capture()
        if current and current != state:
            self._states[index] = current
        self.changed.emit()
        return True
