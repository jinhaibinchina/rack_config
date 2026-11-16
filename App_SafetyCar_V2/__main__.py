"""安全车运行态入口（后端 = DesignerV2.CoreQGraphics），两种跑法都支持::

    python -m App_SafetyCar_V2                  # 包方式，__package__ = "App_SafetyCar_V2"
    python App_SafetyCar_V2/__main__.py         # 脚本方式，__package__ 为 None

脚本方式下进程没有包上下文，``from .safety_car_entry import ...`` 会直接抛
``ImportError: attempted relative import with no known parent package``。
这里先把项目根加进 ``sys.path``，再按绝对包名导入：这样
``safety_car_entry`` / ``my_plc_safety`` 都是以 ``App_SafetyCar_V2.*`` 的身份
加载的，它们内部的相对导入才有父包可依。
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from App_SafetyCar_V2.safety_car_entry import main
else:
    from .safety_car_entry import main

if __name__ == "__main__":
    raise SystemExit(main())
