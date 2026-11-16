"""设计 / 运行二元模式。

原实现在 ``Designer/Core/my_common.py``（一个 5 行枚举）。本包只跑运行态，
没必要再依赖旧设计器包，故就地保留一份——语义与旧枚举完全一致（``Design=0`` /
``Run=1``），适配层 ``mode()`` / ``set_scene_mode()`` 的值类型不变，
``my_plc_safety`` 里 ``SceneMode.Design`` / ``SceneMode.Run`` 的比较照旧成立。

真正的场景开关在 DesignerV2 里是 ``GraphicsScene.set_scene_mode(bool)`` 与
``is_run_mode``；本枚举只是对外保留旧调用面的门面。
"""

from __future__ import annotations

import enum


class SceneMode(enum.Enum):
    Design = 0x0
    Run = 0x1


__all__ = ["SceneMode"]
