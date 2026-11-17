"""启动变量绑定 demo：``python -m App_Demo``。"""

import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from App_Demo.demo_app import main as _main
    return _main()


if __name__ == "__main__":
    raise SystemExit(main())
