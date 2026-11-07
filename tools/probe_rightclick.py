"""复现：选中图元后右键是否会把选中清掉。"""
from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from Designer.CoreQGraphics.ui.design_window import DesignerWindow  # noqa: E402

PAGE = {"sceneRect": {"x": 0, "y": 0, "width": 2000, "height": 1500},
        "items": [], "version": 1}


def send_press(view, vp, button):
    gp = view.viewport().mapToGlobal(vp)
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(vp), QPointF(gp),
                     button, button, Qt.NoModifier)
    QApplication.sendEvent(view.viewport(), ev)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                      encoding="utf-8")
    json.dump(PAGE, tmp, ensure_ascii=False)
    tmp.close()
    win = DesignerWindow(tmp.name)
    win.resize(1000, 760)
    win.show()
    app.processEvents()
    scene, view = win.scene, win.view

    it = scene.create_item("rect", center=(900.0, 700.0))
    view.centerOn(it.center_scene_point())
    app.processEvents()
    it.setSelected(True)
    app.processEvents()

    print("acceptedMouseButtons =", repr(it.acceptedMouseButtons()))
    print("选中(前):", [x.item_id for x in scene.selected_items()])

    vp = view.mapFromScene(it.center_scene_point())
    send_press(view, vp, Qt.RightButton)
    app.processEvents()
    print("右键按下后:", [x.item_id for x in scene.selected_items()],
          " isSelected:", it.isSelected())

    # 对照：左键重选后再看
    scene.clearSelection()
    it.setSelected(True)
    app.processEvents()
    send_press(view, vp, Qt.LeftButton)
    app.processEvents()
    print("左键按下后:", [x.item_id for x in scene.selected_items()])

    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
