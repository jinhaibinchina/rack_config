"""Headless check for Tab cycling through group members in design mode."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

app = QApplication([])

from Designer.Core.elements import base_element, group_element
from Designer.Core.myQuadTreeScene import SceneManager
from Designer.Core.my_common import SceneMode
from Designer.modes.design.design_scene import DesignScene
from Designer.modes.design.element_factory import create_element

scene = DesignScene()
manager = SceneManager(scene, parent=scene)
scene.set_scene_manager(manager)
scene.set_scene_mode(SceneMode.Design)
scene.resize(800, 600)
scene.show()

m1 = create_element(manager, "rect", QPointF(0, 0))
m2 = create_element(manager, "rect", QPointF(300, 0))
m3 = create_element(manager, "circle", QPointF(600, 0))
for m in (m1, m2, m3):
    assert m is not None
    m.completed()

group = manager.createItem(group_element, m1, m2, m3)
group.initialize()
scene.set_current_select_item(group)
scene.update()
assert scene.selected_group() is group

failures = []


def press_tab(reverse=False):
    key = Qt.Key_Backtab if reverse else Qt.Key_Tab
    mods = Qt.ShiftModifier if reverse else Qt.NoModifier
    QApplication.sendEvent(
        scene, QKeyEvent(QKeyEvent.Type.KeyPress, key, mods)
    )


def selected_info():
    selected = [i for i in scene.findChildren(base_element) if i.get_selected()]
    names = sorted(i.get_name() for i in selected)
    current = scene.current_selected
    cur = current.get_name() if isinstance(current, base_element) else "<scene>"
    return names, cur


def check(step, expect):
    names, cur = selected_info()
    ok = names == [expect] and cur == expect
    status = "OK " if ok else "FAIL"
    print(f"{status} {step}: selected={names} current={cur} (expect {expect})")
    if not ok:
        failures.append(step)


order = [group.get_name(), m1.get_name(), m2.get_name(), m3.get_name()]
print("cycle order:", order)

check("initial", group.get_name())
press_tab();      check("tab#1 -> m1", m1.get_name())
press_tab();      check("tab#2 -> m2", m2.get_name())
press_tab();      check("tab#3 -> m3", m3.get_name())
press_tab();      check("tab#4 -> group (wrap)", group.get_name())
press_tab();      check("tab#5 -> m1 again", m1.get_name())
press_tab(True);  check("shift+tab -> group", group.get_name())
press_tab(True);  check("shift+tab -> m3", m3.get_name())
press_tab(True);  check("shift+tab -> m2", m2.get_name())

# No group context: Tab must be left alone (returns False, event unhandled).
scene.clear_selection()
scene.set_current_select_item(scene)
press_tab()
names, cur = selected_info()
ok = names == [] and cur == "<scene>"
print(("OK " if ok else "FAIL") + f" no-context tab leaves selection alone: {names}/{cur}")
if not ok:
    failures.append("no-context")

# A group whose members were all removed must not swallow Tab either.
for child in list(group.m_children):
    child.removeParentItem(True)
scene.clear_selection()
group.set_selected(True)
scene.set_current_select_item(group)
press_tab()
names, cur = selected_info()
ok = cur == group.get_name() and names == [group.get_name()]
print(("OK " if ok else "FAIL") + f" memberless-group tab keeps group: {names}/{cur}")
if not ok:
    failures.append("memberless-group")

print("FAILURES:", failures if failures else "none")
sys.exit(1 if failures else 0)
