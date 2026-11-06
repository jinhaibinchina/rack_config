"""Does scene.keyPressEvent receive Tab when the scene has focus?"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

app = QApplication([])

from Designer.Core.elements import base_element, group_element
from Designer.modes.design.design_window_entry import DesignWindow
from Designer.modes.design.element_factory import create_element

tmp = tempfile.mkdtemp(prefix="design_tab_repro_")
win = DesignWindow(project_root=tmp)
win.show()
win.activateWindow()
app.processEvents()

page = win.current_page
scene = page.scene

m1 = create_element(page.manager, "rect", QPointF(100, 100))
m2 = create_element(page.manager, "rect", QPointF(400, 100))
m1.completed()
m2.completed()
group = page.manager.createItem(group_element, m1, m2)
group.initialize()
scene.set_current_select_item(group)
scene.update()
app.processEvents()

orig_key_press = scene.keyPressEvent
orig_cycle = scene.cycle_selected_group_member


def logged_key_press(event):
    print(f">> keyPressEvent key={event.key()} accepted-before={event.isAccepted()}")
    orig_key_press(event)
    print(f"<< keyPressEvent done key={event.key()} accepted-after={event.isAccepted()}")


def logged_cycle(reverse=False):
    print(f">> cycle called reverse={reverse}")
    result = orig_cycle(reverse)
    print(f"<< cycle returned {result}")
    return result


scene.keyPressEvent = logged_key_press
scene.cycle_selected_group_member = logged_cycle

center = group.windowBoundingRect().center()
pos = QPointF(center).toPoint()
QTest.mouseMove(scene, pos)
QTest.mouseClick(scene, Qt.MouseButton.LeftButton, pos=pos)
app.processEvents()
print("focus after click:", QApplication.focusWidget() is scene)

scene.setFocus()
app.processEvents()
print("focus forced:", QApplication.focusWidget() is scene)

QTest.keyClick(scene, Qt.Key_Tab)
app.processEvents()

sel = [i.get_name() for i in scene.findChildren(base_element) if i.get_selected()]
print("selected after Tab:", sel)
print("focus after Tab:", QApplication.focusWidget())
