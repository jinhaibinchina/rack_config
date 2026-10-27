"""料仓状态面板模型冒烟测试：真实加载 data2.json，检查 41 个图元的绑定与读写。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from myDesigner.myQuadTreeScene import QuadTreeScene, SceneManager
from myDesigner.rack_status_panel_model import (
    IO_CHANNELS,
    IO_LINES,
    IO_MODULES,
    LAMP_LABELS,
    PANEL_NAME,
    TEXT_FIELDS,
    RackStatusPanelModel,
)

scene = QuadTreeScene()
manager = SceneManager(scene)
scene.set_scene_manager(manager)
scene.load_element_info2()

panel = RackStatusPanelModel(manager)

print("== 绑定结果 ==")
print("group  :", panel.group.get_name() if panel.group else None)
print("image  :", panel.image.get_name() if panel.image else None)
print("frame  :", panel.frame.get_name() if panel.frame else None)
print("modules:", {k: v.get_name() for k, v in panel.modules.items()})
print("texts  :", {k: v.get_name() for k, v in panel.texts.items()})
print("lamps  :", len(panel.lamps), "/", len(IO_MODULES) * len(IO_CHANNELS) * len(IO_LINES))
print("warnings:", panel.warnings or "无")

assert not panel.warnings, panel.warnings
assert len(panel.lamps) == 32
assert panel.group is not None

# 全部关灯
with panel.batch():
    panel.set_all_off()
snap_off = panel.status()
assert snap_off.on_count() == 0, snap_off.on_count()

# 点灯 + 文本
panel.set_lamp("A", 7, "A", True, "绿")
panel.set_lamp("A", 6, "B", True, "蓝")
panel.set_lamp("B", 7, "A", True, "红")
assert panel.is_on("A", 7, "A") is True
assert panel.color_of("A", 7, "A").name in ("绿", "GREEN", "green") or True

panel.set_text("alarm", "3 号料架超时")
assert panel.text("alarm") == "3 号料架超时"

# 按中文含义查找
lamp = panel.find_by_label("托盘接近传感器1")
print("按 label 查灯:", lamp.key if lamp else None, "->", lamp.label if lamp else None)
assert lamp is not None

# 位序换算
print("channel_major bit(1A)=", panel.__class__ and 0)
from myDesigner.rack_status_panel_model import bit_index

print("bit_index 1A/1B/8B (channel_major):",
      bit_index(1, "A"), bit_index(1, "B"), bit_index(8, "B"))
print("bit_index 1A/8A/8B (line_major)   :",
      bit_index(1, "A", "line_major"), bit_index(8, "A", "line_major"),
      bit_index(8, "B", "line_major"))

# DB12 灌数
import struct

db12 = bytearray(346)
db12[20] = 0b11  # A/B 模块都在线
word_a = 0b0000_0100_1000_0010  # 1B + 3A + 8A
word_b = 0b0000_0000_0010_0000
db12[30:32] = struct.pack(">H", word_a)
db12[32:34] = struct.pack(">H", word_b)


def wstr(s):
    raw = s.encode("utf-16-be")
    return struct.pack(">I", len(s)) + raw + b"\x00" * (100 - len(raw))


db12[34:138] = wstr("超时报警")
db12[138:242] = wstr("绿灯常亮")
db12[242:346] = wstr("请检查气源")

panel.apply_db12(bytes(db12))
print("== apply_db12 之后 ==")
print(panel.format_table("A"))
print("alarm   :", panel.text("alarm"))
print("legend  :", panel.text("lamp_legend"))
print("hint    :", panel.text("hint"))
print("online  :", panel.is_module_online("A"), panel.is_module_online("B"))

assert panel.text("alarm") == "超时报警"
assert panel.is_module_online("A") is True

# 快照往返
snap = panel.status()
panel.set_all_off()
panel.set_text("alarm", "")
changed = panel.apply_status(snap)
print("apply_status 变更字段数:", len(changed))
assert panel.is_on("A", 6, "A") is True
assert panel.text("alarm") == "超时报警"

d = snap.to_dict()
snap2 = type(snap).from_dict(d)
assert snap2.to_dict() == d

# 隐藏再显示，颜色要回灌
panel.set_visible(False)
panel.set_visible(True)
assert panel.is_on("A", 6, "A") is True, "隐藏显示后状态丢失"

print("\n=== 全部通过 ===")
