"""test_fixture 入口，两种跑法都支持::

    python -m App_test_fixture               # 包方式，__package__ = "App_test_fixture"
    python App_test_fixture/__main__.py      # 脚本方式，__package__ 为 None

脚本方式下进程没有包上下文，``from .fixture_app import ...`` 会直接抛
``ImportError: attempted relative import with no known parent package``。
这里先把项目根加进 ``sys.path``，再按绝对包名导入。

不带任何命令行参数时默认跑 modbus（接现场）；显式给参数则以参数为准，
例如 ``--source demo`` / ``--source none --seconds 1``。
"""

from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
        
    from App_test_fixture.fixture_app import main
else:
    from .fixture_app import main

if __name__ == "__main__":
    # main() 收的是参数列表，不是整条命令字符串：传字符串会被 argparse
    # 逐字符拆成 "- - s o u r c e ..."，报 unrecognized arguments。
    raise SystemExit(main(sys.argv[1:] or ["--source", "modbus"]))
