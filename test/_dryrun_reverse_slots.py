"""干跑：把每台料架的 8 个仓位组按几何顺序反转（不存盘，只看结果对不对）。

做法说明见回复；这里只验证：
  1) 用 group.change_position(scene_topLeft + delta) 能移动仓位组
  2) 反序后每台料架的包围盒不变
  3) 仓位 k 的 y 等于原仓位 (9-k) 的 y
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF

app = QApplication.instance() or QApplication([])

from myDesigner.myQuadTreeScene import QuadTreeScene, SceneManager
from myDesigner.rack_store_model import RackStoreModel

scene = QuadTreeScene()
manager = SceneManager(scene)
scene.set_scene_manager(manager)
scene.load_element_info2()
model = RackStoreModel(manager)


def slot_map(rack_no):
    rack = model.rack(rack_no)
    return {no: rack.slots[no].group for no in sorted(rack.slots)}


def snapshot(groups):
    return {no: (g.get_scene_topLeft(), g.get_scene_center_pos()) for no, g in groups.items()}


def rack_box(rack_no):
    rack = model.rack(rack_no)
    xs, ys = [], []
    for g in slot_map(rack_no).values():
        for p in (g.get_scene_topLeft(), g.get_scene_bottomRight()):
            xs.append(p.x())
            ys.append(p.y())
    return min(xs), min(ys), max(xs), max(ys)


def reverse_rack(rack_no):
    groups = slot_map(rack_no)
    before = snapshot(groups)
    # 按几何 y 排：scene y 越大越靠上
    order = sorted(before, key=lambda no: -before[no][1].y())
    # 反转：原来的第 i 个位置交给 order[-1-i] 这个仓位
    targets = {}
    for index, no in enumerate(order):
        donor = order[len(order) - 1 - index]
        targets[no] = before[donor][0]  # 用 donor 的左上角做目标
    # 全部算完再写，避免读改交错
    for no, target_tl in targets.items():
        g = groups[no]
        delta = target_tl - g.get_scene_topLeft()
        g.change_position(g.get_scene_topLeft() + delta)
    return before, targets


for rack_no in (2, 5):
    box_before = rack_box(rack_no)
    before, targets = reverse_rack(rack_no)
    box_after = rack_box(rack_no)
    print(f"== 料架{rack_no}")
    print("   包围盒 before:", tuple(round(v, 3) for v in box_before))
    print("   包围盒 after :", tuple(round(v, 3) for v in box_after))
    for no in sorted(targets):
        now = slot_map(rack_no)[no].get_scene_center_pos()
        print(f"   仓位{no}: y {before[no][1].y():9.3f} -> {now.y():9.3f}"
              f"   (原仓位{9 - no} 的 y= {before[9 - no][1].y():9.3f})")
    assert abs(box_before[1] - box_after[1]) < 1e-6 and abs(box_before[3] - box_after[3]) < 1e-6

print("\n=== 干跑完成（未写文件）===")
os._exit(0)
