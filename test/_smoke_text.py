"""text_element 内容变化时左侧固定 —— 回归测试。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF

app = QApplication.instance() or QApplication([])

from myDesigner.myQuadTreeScene import QuadTreeScene, SceneManager

scene = QuadTreeScene()
manager = SceneManager(scene)
scene.set_scene_manager(manager)
scene.load_element_info2()


def find(name):
    for it in manager.m_items.values():
        if it is not None and it.get_name() == name:
            return it
    return None


def view_box(item):
    pts = [scene.sceneToView(item.mapToScene(item._topLeft)),
           scene.sceneToView(item.mapToScene(item._topRight)),
           scene.sceneToView(item.mapToScene(item._bottomLeft)),
           scene.sceneToView(item.mapToScene(item._bottomRight))]
    xs = [p.x() for p in pts]
    ys = [p.y() for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def check(name, texts):
    item = find(name)
    assert item is not None, name
    print(f"== {name}")
    left0 = None
    for t in texts:
        item.context = t
        x0, x1, y0, y1 = view_box(item)
        print(f"   {t[:14]!r:<20} 左={x0:9.2f} 右={x1:9.2f} 宽={x1-x0:7.2f} 高={y1-y0:6.2f}")
        if left0 is None:
            left0 = x0
        else:
            assert abs(x0 - left0) < 1e-6, f"左边跑了：{x0} vs {left0}"
    return item, left0


check("料仓状态_报警文本", ["短", "这是一个中等长度的报警", "超长超长超长超长超长超长超长超长超长", "短"])
check("料架2_仓位1_编号", ["01", "02", "123456", "1"])

# --- 旋转的文本：左边缘同样要钉住
item = find("料仓状态_提示文本")
item.rotate_to_ang(90)
scene.update() if hasattr(scene, "update") else None
x0, x1, y0, y1 = view_box(item)
item.context = "旋转之后的很长很长的提示文字"
x0b, x1b, y0b, y1b = view_box(item)
print(f"== 旋转 90°：左 {x0:.2f} -> {x0b:.2f}，上 {y0:.2f} -> {y0b:.2f}，下 {y1:.2f} -> {y1b:.2f}")
assert abs(x0 - x0b) < 1e-6, "旋转后左边也跑了"
# 旋转后长度方向变成竖直，只应该朝一侧长
assert (y0b - y0) * (y1b - y1) <= 1e-9, "旋转后应该只朝一侧伸出"

# --- 存盘 / 读盘往返，画框位置不能变
item2 = find("料仓状态_灯语文本")
item2.context = "绿灯常亮，蓝灯闪烁"
box_before = view_box(item2)
data = item2.to_dict()
again = type(item2).from_dict(data)
box_after = (lambda it: (lambda pts: (min(p.x() for p in pts), max(p.x() for p in pts),
                                      min(p.y() for p in pts), max(p.y() for p in pts)))(
    [scene.sceneToView(it.mapToScene(it._topLeft)),
     scene.sceneToView(it.mapToScene(it._topRight)),
     scene.sceneToView(it.mapToScene(it._bottomLeft)),
     scene.sceneToView(it.mapToScene(it._bottomRight))]))(again)
print("== to_dict/from_dict 往返")
print("   before:", tuple(round(v, 3) for v in box_before))
print("   after :", tuple(round(v, 3) for v in box_after))
for a, b in zip(box_before, box_after):
    assert abs(a - b) < 1e-6, (box_before, box_after)

# --- 拖动一次后，几何关系仍自洽（中心 = 四角中点）
item3 = find("料架2_仓位2_编号")
item3.context = "很长很长的编号"
item3.change_position(QPointF(1000, 1000))
c = item3._center_pos
mid = (item3._head_pos + item3._end_pos) / 2.0
print(f"== 拖动后 center={c} 四角中点={mid}")
assert abs(c.x() - mid.x()) < 1e-6 and abs(c.y() - mid.y()) < 1e-6

# --- 关掉开关就回到老行为
item4 = find("料仓状态_标题")
item4.keep_left_on_context_change = False
x0, x1, _, _ = view_box(item4)
before_center = item4.get_scene_center_pos()
item4.context = "关掉开关以后很长很长的标题"
after_center = item4.get_scene_center_pos()
print(f"== 关闭开关：left {x0:.2f} -> {view_box(item4)[0]:.2f}，"
      f"中心 {before_center.x():.2f} -> {after_center.x():.2f}")
assert abs(before_center.x() - after_center.x()) < 1e-6, "关闭后应保持中心不变"

print("\n=== 全部通过 ===")
os._exit(0)
