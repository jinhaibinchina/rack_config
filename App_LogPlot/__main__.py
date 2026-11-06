"""PopPick 入口，两种跑法都支持::

    python -m App_PopPick                    # 包方式，__package__ = "App_PopPick"
    python App_PopPick/__main__.py           # 脚本方式，__package__ 为 None

脚本方式下进程没有包上下文，``from .pop_pick_entry import ...`` 会直接抛
``ImportError: attempted relative import with no known parent package``。
这里先把项目根加进 ``sys.path``，再按绝对包名导入：这样
``pop_pick_entry`` / ``rack_global_parameters_model`` 都是以
``App_PopPick.*`` 的身份加载的，它们内部的相对导入才有父包可依。
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from App_LogPlot.log_plot_entry import main
else:
    from .log_plot_entry import main

if __name__ == "__main__":
    raise SystemExit(main())
