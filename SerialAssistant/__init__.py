"""SerialAssistant —— 基于 PySide6 的串口调试助手。

与 AppsManagers 里其他 App 保持同样的组织方式：本包只放实现，
入口在 :mod:`SerialAssistant.serial_assistant_entry`，可直接：

.. code-block:: bash

    # 项目根目录下（.venv 已装 PySide6 6.10.2）
    .venv/Scripts/python.exe -m SerialAssistant
    .venv/Scripts/python.exe serial_assistant_main.py

串口层只用 PySide6 自带的 ``QtSerialPort``（QSerialPort / QSerialPortInfo），
不依赖 pyserial；读写走 Qt 事件循环的 readyRead / bytesWritten 信号，
不额外开线程，也不会阻塞界面。
"""
