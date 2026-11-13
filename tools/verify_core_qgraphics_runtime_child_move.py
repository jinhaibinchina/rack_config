"""运行态子图元自身平移专项门禁（CoreQGraphics）。

设计口径：有父图元的图元在**设计态**不能自行平移，位置只由父对象带动；
运行态则允许 `set_page_center` / `RuntimeElement.setPos` 自行平移，供 HMI
动画、业务脚本让子控件在父图元内部偏移。

覆盖：

* 设计态 `translate_locked()` 为真、`set_page_center` 被拒；
* 设计态父对象平移 / 旋转仍刚体带动子与孙；
* 切运行态后子图元可自身平移，父对象不动，孙图元按刚体跟随；
* 子图元自定义支点随自身平移同步移动；
* `RuntimeElement.setPos` 走同一条链路；
* 子图元自身偏移后，父对象再次运动仍带着它，父坐标系局部值保持不变；
* 切回设计态后平移锁恢复。

用法：
``QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tools/verify_core_qgraphics_runtime_child_move.py``
"""

from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from Designer.CoreQGraphics.g_scene import GraphicsScene  # noqa: E402
from Designer.CoreQGraphics.runtime.elements import RuntimeRegistry  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILURES.append(name)
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def close_pt(a, b, tol: float = 1e-6) -> bool:
    return (a is not None and b is not None
            and math.hypot(a[0] - b[0], a[1] - b[1]) <= tol)


app = QApplication.instance() or QApplication([])

scene = GraphicsScene()
parent = scene.create_item("rect", center=(1000.0, 1000.0), size=(400.0, 300.0))
child = scene.create_item("rect", center=(1200.0, 1000.0), size=(100.0, 80.0))
grand = scene.create_item("rect", center=(1250.0, 1000.0), size=(40.0, 30.0))
child.set_page_parent(parent.item_id)
grand.set_page_parent(child.item_id)
child.set_page_origin(1250.0, 1050.0)       # 自定义支点，验证平移同步搬走
app.processEvents()

print("=== 1. 设计态仍锁子图元自身平移 ===")
check("设计态 translate_locked / pose_locked 都为真",
      child.translate_locked() and child.pose_locked())
check("父图元自身不受平移锁",
      not parent.translate_locked() and not parent.pose_locked())
keep = child.page_center()
check("设计态子图元 set_page_center 被拒绝且位置不变",
      child.set_page_center(1400.0, 1100.0) is False
      and close_pt(child.page_center(), keep),
      f"center={child.page_center()}")

print("\n=== 2. 设计态父对象刚体联动不回归 ===")
grand0 = grand.page_center()
origin0 = child.page_origin()
parent.set_page_center(1100.0, 900.0)       # +100, -100
app.processEvents()
check("父平移子图元同步 +100/-100",
      close_pt(child.page_center(), (1300.0, 900.0)),
      f"child={child.page_center()}")
check("孙图元同步 +100/-100",
      close_pt(grand.page_center(),
               (grand0[0] + 100.0, grand0[1] - 100.0)),
      f"grand={grand.page_center()}")
check("子图元自定义支点同步平移",
      close_pt(child.page_origin(),
               (origin0[0] + 100.0, origin0[1] - 100.0)),
      f"origin={child.page_origin()}")
parent.set_page_center(1000.0, 1000.0)      # 复原
app.processEvents()
check("父图元复原后子图元回到原位",
      close_pt(child.page_center(), (1200.0, 1000.0)),
      f"child={child.page_center()}")

print("\n=== 3. 运行态允许子图元自身平移 ===")
scene.set_scene_mode(True)
app.processEvents()
check("运行态 is_run_mode=True", scene.is_run_mode)
check("运行态 translate_locked / pose_locked 都放行",
      not child.translate_locked() and not child.pose_locked())
parent_before = parent.page_center()
origin_before = child.page_origin()
check("运行态子图元 set_page_center 成功",
      child.set_page_center(1300.0, 1100.0) is True
      and close_pt(child.page_center(), (1300.0, 1100.0)),
      f"child={child.page_center()}")
check("子图元自身平移不带动父图元",
      close_pt(parent.page_center(), parent_before),
      f"parent={parent.page_center()}")
check("孙图元按刚体跟随子图元 +100/+100",
      close_pt(grand.page_center(), (1350.0, 1100.0)),
      f"grand={grand.page_center()}")
check("子图元自定义支点随自身平移 +100/+100",
      close_pt(child.page_origin(),
               (origin_before[0] + 100.0, origin_before[1] + 100.0)),
      f"origin={child.page_origin()}")
check("父坐标系局部中心同步更新为 (300, 100)",
      close_pt(child.page_local_center(), (300.0, 100.0)),
      f"local={child.page_local_center()}")

print("\n=== 4. RuntimeElement.setPos 走同一条运行态链路 ===")
registry = RuntimeRegistry(scene)
element = registry.find(child.item_id)
check("运行态门面可按 id 找到子图元",
      element is not None and element.item() is child,
      str(element))
if element is not None:
    element.setPos(QPointF(1350.0, 1150.0))
    app.processEvents()
    check("门面 setPos 精确移动子图元",
          close_pt(child.page_center(), (1350.0, 1150.0)),
          f"child={child.page_center()}")
    check("门面移动子图元不带动父图元",
          close_pt(parent.page_center(), parent_before),
          f"parent={parent.page_center()}")
    check("孙图元再按 +50/+50 跟随",
          close_pt(grand.page_center(), (1400.0, 1150.0)),
          f"grand={grand.page_center()}")
    check("门面读取的中心与图元一致",
          close_pt((element.get_scene_center_pos().x(),
                    element.get_scene_center_pos().y()),
                   child.page_center()),
          str(element.get_scene_center_pos()))

print("\n=== 5. 子图元自身偏移后，父对象运动仍按刚体带上它 ===")
local_before = child.page_local_center()
origin_local_before = child.page_local_origin()
parent.set_page_center(1050.0, 1025.0)       # +50/+25
app.processEvents()
check("父图元后续平移仍带动已自身偏移的子图元",
      close_pt(child.page_center(), (1400.0, 1175.0)),
      f"child={child.page_center()}")
check("孙图元继续跟随",
      close_pt(grand.page_center(), (1450.0, 1175.0)),
      f"grand={grand.page_center()}")
check("父运动不改变子图元父系局部中心",
      close_pt(child.page_local_center(), local_before),
      f"{local_before} -> {child.page_local_center()}")
check("父运动不改变子图元自定义支点相对父系的局部值",
      close_pt(child.page_local_origin(), origin_local_before),
      f"{origin_local_before} -> {child.page_local_origin()}")

print("\n=== 6. 切回设计态后平移锁恢复 ===")
after_runtime = child.page_center()
scene.set_scene_mode(False)
app.processEvents()
check("切回设计态 translate_locked 恢复为真", child.translate_locked())
check("切回设计态子图元 set_page_center 再次被拒绝",
      child.set_page_center(2000.0, 2000.0) is False
      and close_pt(child.page_center(), after_runtime),
      f"center={child.page_center()}")
check("设计态父图元仍可正常平移",
      parent.set_page_center(1100.0, 1000.0) is True,
      f"parent={parent.page_center()}")

print("\n" + "=" * 60)
if FAILURES:
    print(f"FAILED: {len(FAILURES)} 项")
    for name in FAILURES:
        print("  -", name)
    sys.exit(1)
print("ALL PASS：设计态锁 / 运行态子图元自身平移全链路通过")
