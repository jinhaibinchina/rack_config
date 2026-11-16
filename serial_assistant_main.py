"""项目根目录下的串口调试助手启动脚本（与 fixture_main.py / safety_car_main.py 同级）。

    .venv/Scripts/python.exe serial_assistant_main.py
"""

from SerialAssistant.serial_assistant_entry import main
import sys

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
