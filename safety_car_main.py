"""兼容入口：转发到统一入口 ``main.py``（``--app safety``）。

保留本文件是为了不让旧的快捷方式、spec 配置和同事的使用习惯失效。
``sys.argv`` 会原样透传，因此 ``python safety_car_main.py --no-plc`` 仍然有效。
新代码请直接用 ``python main.py --app safety`` 或选择页。
"""

import sys

from main import main

if __name__ == "__main__":
    raise SystemExit(main(["--app", "safety", *sys.argv[1:]]))
