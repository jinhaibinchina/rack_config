"""整页快照式撤销栈（对齐 Designer/modes/design/page_history.py 的语义）。

旧实现用 400ms 去抖 QTimer + ``capture_snapshot()`` 整页 JSON 字符串；
这里直接复用 ``GraphicsScene.snapshot()`` / ``restore()`` 的 dict，由主窗口
在每条编辑命令结束后显式 ``commit()``，省掉定时器也让回归可确定。

``_states`` 只存页面内容（page JSON 结构）。**选中集合与脏标记不进快照**，
否则会破坏 round-trip 零改动；它们作为与 ``_states`` 平行的数组单独保存，
``undo`` / ``redo`` 后一并回填：``restore()`` 会销毁并重建全部
QGraphicsItem，只恢复页面数据的话属性面板会跳回「页面属性」、图层树选中
丢失，标题的 ``*`` 也会停在错误状态（保存后撤销不提示、撤销回初始仍提示）。
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
        self._modified: list[bool] = []
        self._selection: list[list[int]] = []
        self._index = -1
        self._applying = False
        # 命令分发开头记下的「本次操作前选中」。duplicate / paste / group
        # 这类命令会先改选中再 commit，光看 commit 时的选中会把上一状态的
        # 选中写成副本 id（副本在上一状态不存在），撤销回来就变成全不选。
        self._pre_selection: list[int] | None = None
        self.reset()

    # ------------------------------------------------------------------
    # 快照之外的两条 UI 状态
    # ------------------------------------------------------------------
    def _selected_ids(self) -> list[int]:
        return sorted(it.item_id for it in self.scene.selected_items())

    def note_pre_edit_selection(self, ids) -> None:
        """记录一次命令开始前的选中；不经过命令分发的编辑传 ``None``。"""
        self._pre_selection = (
            None if ids is None else sorted(int(i) for i in ids))

    def _trim(self, n: int) -> None:
        """三条平行数组一起截断，别让重做栈被剪掉后选中/脏标记错位。"""
        self._states = self._states[:n]
        self._modified = self._modified[:n]
        self._selection = self._selection[:n]

    def reset(self) -> None:
        self._states = [copy.deepcopy(self.scene.snapshot())]
        self._modified = [False]
        self._selection = [self._selected_ids()]
        self._index = 0
        self._pre_selection = None
        self.changed.emit()

    def mark_saved(self) -> None:
        """保存成功后调用：当前历史状态与磁盘一致，撤销再回来不应标脏。"""
        if 0 <= self._index < len(self._modified):
            self._modified[self._index] = False

    def commit(self) -> None:
        if self._applying:
            return
        state = copy.deepcopy(self.scene.snapshot())
        if 0 <= self._index < len(self._states) and state == self._states[self._index]:
            self._pre_selection = None
            return
        self._trim(self._index + 1)
        selected = self._selected_ids()
        # 当前状态就是「这一步操作之前」的样子，选中要回填成操作前的那份；
        # 属性面板 / 画布移动不经过命令分发，操作前后选中相同，直接用当前值。
        pre = selected if self._pre_selection is None else self._pre_selection
        self._pre_selection = None
        if self._selection:
            self._selection[-1] = pre
        self._states.append(state)
        self._modified.append(bool(self.scene.is_modified()))
        self._selection.append(selected)
        if len(self._states) > self.limit:
            self._states.pop(0)
            self._modified.pop(0)
            self._selection.pop(0)
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
            self._pre_selection = None
            self.scene.restore(copy.deepcopy(self._states[self._index]))
            # 先回填脏标记再恢复选中：select_items 会发 selectionChanged，
            # 主窗口 _refresh() 这时读到的必须已经是正确的值。
            if self._modified[self._index]:
                self.scene.mark_modified()
            else:
                self.scene.mark_saved()
            # restore 重建了图元对象，只能按 id 找回；目标状态里已经不存在的
            # id（例如撤销掉刚创建的图元）直接跳过，选中清空是正确结果。
            wanted = [self.scene.find_item(i)
                      for i in self._selection[self._index]]
            self.scene.select_items([it for it in wanted if it is not None])
        finally:
            self._applying = False
        self.changed.emit()
