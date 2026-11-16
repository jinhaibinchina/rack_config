"""SerialAssistant 入口，和工程里其他 App 一样支持两种跑法::

    python -m SerialAssistant                       # 包方式
    python SerialAssistant/__main__.py              # 脚本方式

脚本方式没有包上下文，``from .serial_assistant_entry import ...`` 会抛
``ImportError: attempted relative import with no known parent package``。
这里先把项目根加进 ``sys.path``，再按绝对包名导入，保证
``serial_assistant_entry`` 内部的相对导入能正常解析。
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from SerialAssistant.serial_assistant_entry import main
else:
    from .serial_assistant_entry import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
