"""整页快照式撤销栈（对齐 Designer/modes/design/page_history.py 的语义）。

旧实现用 400ms 去抖 QTimer + ``capture_snapshot()`` 整页 JSON 字符串；
这里直接复用 ``GraphicsScene.snapshot()`` / ``restore()`` 的 dict，由主窗口
在每条编辑命令结束后显式 ``commit()``，省掉定时器也让回归可确定。
"""

from __future__ import annotations

import copy

from PySide6.QtCore import QObject, Signal


class PageHistory(QObject):
    changed = Signal()

    def __init__(self, scene, limit: int = 60, parent=None) -> None:
        super().__init__(parent)
        self.scene = scene
        self.limit = max(2, int(limit))
        self._states: list[dict] = []
        self._index = -1
        self._applying = False
        self.reset()

    def reset(self) -> None:
        self._states = [copy.deepcopy(self.scene.snapshot())]
        self._index = 0
        self.changed.emit()

    def commit(self) -> None:
        if self._applying:
            return
        state = copy.deepcopy(self.scene.snapshot())
        if 0 <= self._index < len(self._states) and state == self._states[self._index]:
            return
        self._states = self._states[: self._index + 1]
        self._states.append(state)
        if len(self._states) > self.limit:
            self._states.pop(0)
        self._index = len(self._states) - 1
        self.changed.emit()

    def can_undo(self) -> bool:
        return self._index > 0

    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    def undo(self) -> bool:
        if not self.can_undo():
            return False
        self._index -= 1
        self._apply()
        return True

    def redo(self) -> bool:
        if not self.can_redo():
            return False
        self._index += 1
        self._apply()
        return True

    def _apply(self) -> None:
        self._applying = True
        try:
            self.scene.restore(copy.deepcopy(self._states[self._index]))
        finally:
            self._applying = False
        self.changed.emit()
