"""RackStoresWindow 集成冒烟：确认料仓状态面板已挂到窗口上并能被 PLC 数据驱动。"""

import os
import sys
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from myDesigner.rack_stores_widget import RackStoresWindow

win = RackStoresWindow()
panel = win.panel_status
print("lamps:", len(panel.lamps), "warnings:", panel.warnings or "无")

win.set_io_lamp("A", 6, "A", True, "红")
print("A/6/A on:", panel.is_on("A", 6, "A"), panel.color_of("A", 6, "A"))

win.set_io_module_bits("B", 0b0000_0000_0000_0011)
print("B 1A/1B:", panel.is_on("B", 1, "A"), panel.is_on("B", 1, "B"))

win.set_io_module_online("A", True)
win.set_panel_alarm("1 号料架超时")
win.set_panel_hint("请检查气源")
win.set_panel_lamp_legend("绿灯常亮")
print("alarm/hint/legend:", panel.text("alarm"), "/", panel.text("hint"), "/", panel.text("lamp_legend"))

db12 = bytearray(346)
db12[20] = 0b11
db12[30:32] = struct.pack(">H", 0x0001)
db12[32:34] = struct.pack(">H", 0x8000)


def wstr(s):
    raw = s.encode("utf-16-be")
    return struct.pack(">I", len(s)) + raw + b"\x00" * (100 - len(raw))


db12[34:138] = wstr("DB12 报警")
db12[138:242] = wstr("DB12 灯语")
db12[242:346] = wstr("DB12 提示")
changed = win.apply_db12(bytes(db12))
print("apply_db12 changed:", changed)
print("A/1/A:", panel.is_on("A", 1, "A"), " B/8/B:", panel.is_on("B", 8, "B"))
print("文本:", panel.text("alarm"), "/", panel.text("lamp_legend"), "/", panel.text("hint"))

win.refresh_models()
print("refresh 后 lamps:", len(win.panel_status.lamps))

print("=== 集成通过 ===")
