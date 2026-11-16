"""料架 PLC 配置工具 V2 入口（后端 = DesignerV2.CoreQGraphics），两种跑法都支持::

    python -m App_RackConfig_V2                    # 包方式，__package__ = "App_RackConfig_V2"
    python App_RackConfig_V2/__main__.py           # 脚本方式，__package__ 为 None

脚本方式下进程没有包上下文，``from .rack_config_entry import ...`` 会直接抛
``ImportError: attempted relative import with no known parent package``。
这里先把项目根加进 ``sys.path``，再按绝对包名导入：这样
``rack_config_entry`` / ``plc_window`` 都是以 ``App_RackConfig_V2.*`` 的身份
加载的，它们内部的相对导入才有父包可依。
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from App_RackConfig_V2.rack_config_entry import main
else:
    from .rack_config_entry import main

if __name__ == "__main__":
    raise SystemExit(main())
