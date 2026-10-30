"""渲染正确性校验：可见性裁剪不能改变任何一个像素。

``refresh_dynamic_buffer`` 会跳过与重绘区域不相交的图元。这个脚本校验两件事：

1. 裁剪前后逐像素一致（没有把该画的图元裁掉）；
2. 每一帧结束后，**所有**图元都拿到了当前的重绘区域——图元自己的 ``paint``
   用 ``m_veiw_dirty_region`` 判断可见性，漏掉的图元会一直空白
   （这正是"部分图元不显示"这类 bug 的来源）。

用法::

    .venv/Scripts/python.exe tools/verify_render.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

from tools.bench_scene import DEFAULT_PAGE, build_scene


def render(scene):
    return scene.grab().toImage()


def empty_rect(_region) -> QRectF:
    """关掉可见性裁剪，回到"全部图元都画"的旧行为。"""

    return QRectF()


def main() -> int:
    QApplication.instance() or QApplication([])
    scene = build_scene(DEFAULT_PAGE)
    scene.resize(860, 545)
    scene.update_coordinate()

    culled_original = scene._scene_rect_for_region
    states = [
        (0.0, 0.0, 1.0),
        (0.0, 0.0, 0.4),
        (0.0, 0.0, 2.0),
        (250.0, -180.0, 0.7),
        (-400.0, 320.0, 1.3),
    ]

    failures = 0
    for offset_x, offset_y, scale in states:
        scene._scene_rect_for_region = culled_original
        scene.scale_factor = scale
        scene.offset = QPointF(offset_x, offset_y)
        scene.update_coordinate()
        scene.update()
        QApplication.processEvents()
        culled = render(scene)

        scene._scene_rect_for_region = empty_rect
        scene.update()
        uncelled = render(scene)

        diff = 0
        if culled.size() == uncelled.size():
            for y in range(culled.height()):
                for x in range(culled.width()):
                    if culled.pixel(x, y) != uncelled.pixel(x, y):
                        diff += 1
        else:
            diff = -1

        scene._scene_rect_for_region = culled_original

        total = culled.width() * culled.height()
        status = "ok" if diff == 0 else "MISMATCH"
        if diff != 0:
            failures += 1
        print(
            f"offset=({offset_x:6.0f},{offset_y:6.0f}) scale={scale:<4} "
            f"diff={diff:<8} {status}"
        )

    # 脏区覆盖检查：每个图元都必须拿到本帧的重绘区域
    scene._scene_rect_for_region = culled_original
    scene.scale_factor = 1.0
    scene.offset = QPointF(0.0, 0.0)
    scene.update_coordinate()
    scene.update()
    render(scene)

    items = list(scene.scene_manager.m_items.values())
    starved = [
        item
        for item in items
        if getattr(item, "m_veiw_dirty_region", None) is None
        or item.m_veiw_dirty_region.isEmpty()
    ]
    print(f"items={len(items)} starved(no dirty region)={len(starved)}")
    if starved:
        failures += 1
        for item in starved[:5]:
            print(f"  starved: {type(item).__name__} id={item.id()}")

    print("RESULT:", "identical — culling is pixel-safe" if not failures else f"{failures} problem(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
