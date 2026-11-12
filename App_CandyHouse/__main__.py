"""糖果屋入口，两种跑法都支持::

    python -m App_CandyHouse                  # 包方式，__package__ = "App_CandyHouse"
    python App_CandyHouse/__main__.py         # 脚本方式，__package__ 为 None

脚本方式下进程没有包上下文，相对导入会失败，因此先把 AppsManagers 根加进
``sys.path``，再按绝对包名导入 ``App_CandyHouse.candy_house_entry``。
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from App_CandyHouse.candy_house_entry import main
else:
    from .candy_house_entry import main

if __name__ == "__main__":
    raise SystemExit(main())
