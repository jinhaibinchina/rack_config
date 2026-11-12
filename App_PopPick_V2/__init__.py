"""PopPick 拣选工作站（V2）：页面卡片点击互换。

V2 与 ``App_PopPick`` 的差别只在**运行态装配**：画面改由
``Designer.CoreQGraphics.runtime.RuntimeStage`` 承载，旧的
``qgraphics_runtime.py``（1056 行手工适配层）已删除，改由
:mod:`App_PopPick_V2.pop_pick_runtime` 按
``App_test_fixture/fixture_runtime.py`` 的口径装配。

入口见 :mod:`App_PopPick_V2.pop_pick_entry`，交互逻辑见
:mod:`App_PopPick_V2.page_deck`，位图顶替见
:mod:`App_PopPick_V2.page_snapshots`。
"""

from .pop_pick_entry import PopPickWindow

__all__ = ["PopPickWindow"]
