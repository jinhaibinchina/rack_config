"""handle_rack_status(rack_arrangements) 回归测试：0 正序 / 1 反序，且必须幂等。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from myDesigner.rack_stores_widget import RackStoresWindow
from myDesigner.rack_store_model import MaterialState

win = RackStoresWindow()
model = win.rack_store_model


def ys(rack_no):
    rack = model.rack(rack_no)
    return {no: round(rack.slot(no).group.get_scene_center_pos().y(), 3)
            for no in sorted(rack.slots)}


def box(rack_no):
    rack = model.rack(rack_no)
    vals = []
    for no in sorted(rack.slots):
        g = rack.slot(no).group
        vals += [g.get_scene_topLeft().y(), g.get_scene_bottomRight().y()]
    return round(min(vals), 3), round(max(vals), 3)


before = ys(2)
box_before = box(2)
part_before = model.rack(2).slot(1).parts["A库实料"].get_scene_center_pos()

# 料架1 正序、料架2 反序
flipped = win.handle_rack_status(1, 1, 2, [8, 8], [0, 1] + [0] * 8)
print("首次翻转的料架:", win.set_rack_arrangements([0, 1] + [0] * 8))
after = ys(2)
print("料架2 y 变化:")
for no in sorted(after):
    print(f"   仓位{no}: {before[no]:9.3f} -> {after[no]:9.3f}")
assert abs(after[1] - before[8]) < 1e-6 and abs(after[8] - before[1]) < 1e-6
assert box(2) == box_before, (box(2), box_before)

# 子图元要跟着组走
part_after = model.rack(2).slot(1).parts["A库实料"].get_scene_center_pos()
print(f"仓位1 内 A库实料 位移: {round(part_after.y() - part_before.y(), 3)}"
      f"（组位移 {round(after[1] - before[1], 3)}）")
assert abs((part_after.y() - part_before.y()) - (after[1] - before[1])) < 1e-6

# 幂等：再下发同样的配置，不应该再翻
win.handle_rack_status(1, 1, 2, [8, 8], [0, 1] + [0] * 8)
again = ys(2)
print("重复下发后 y 是否不变:", again == after)
assert again == after, "重复下发又翻了一次！"

# 改回正序
win.handle_rack_status(1, 1, 2, [8, 8], [0, 0] + [0] * 8)
back = ys(2)
print("改回正序:", {no: back[no] for no in sorted(back)})
assert back == before, "没能恢复到正序"

# 不传该参数时完全不动
win.handle_rack_status(1, 1, 2, [8, 8])
assert ys(2) == before

# 反序状态下灌数据：仍然进仓位1，但仓位1 在最下面
win.handle_rack_status(1, 1, 2, [8, 8], [0, 1] + [0] * 8)
model.rack(2).slot(1).set_material("A", MaterialState.FULL_1)
st = ys(2)
print(f"反序后：仓位1 y={st[1]}（最小=最下面），A={model.rack(2).slot(1).material_state('A')}")
assert st[1] < st[8]
assert model.rack(2).slot(1).material_state("A") in (MaterialState.FULL_1, MaterialState.FULL_2)

# 短列表 / 脏值兜底
win.handle_rack_status(1, 1, 2, [8, 8], [1])
print("短列表兜底 OK")
win.handle_rack_status(1, 1, 2, [8, 8], ["x", None])
print("脏值兜底 OK")

print("\n=== 全部通过 ===")
os._exit(0)
