"""PopPick V2 入口，两种跑法都支持::

    python -m App_PopPick_V2                 # 包方式，__package__ = "App_PopPick_V2"
    python App_PopPick_V2/__main__.py        # 脚本方式，__package__ 为 None

脚本方式下进程没有包上下文，``from .pop_pick_entry import ...`` 会直接抛
``ImportError: attempted relative import with no known parent package``。
这里先把项目根加进 ``sys.path``，再按绝对包名导入：这样
``pop_pick_entry`` / ``pop_pick_runtime`` 都是以 ``App_PopPick_V2.*`` 的身份
加载的，它们内部的相对导入才有父包可依。

默认按**设计工程里的 page_9** 起（设计器改完直接生效），打包运行
（``sys.frozen``）时才回退到 ``res`` 下的运行态场景副本；要指定别的页面就
传 ``--page`` / ``--scene``，命令行参数原样透传。
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from App_PopPick_V2.pop_pick_entry import main
else:
    from .pop_pick_entry import main

try:
    # 预加载资源，避免首次打开时卡顿（打包运行才用得到）
    from res.designer_resource_manager import resource_manager  # noqa: F401
except Exception:  # noqa: BLE001 - 源码运行 / 资源包缺失都不影响
    resource_manager = None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
