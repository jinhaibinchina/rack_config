# -*- coding: utf-8 -*-
"""临时探针：设计器 dock 显隐 / 窗口缩放对画面位置的影响。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from Designer.CoreQGraphics.ui.design_window import DesignerWindow

page = os.path.join(ROOT, "Designer", "CoreQGraphics", "page1.json")
win = DesignerWindow(page)
win.resize(1500, 940)
win.show()
for _ in range(8):
    app.processEvents()

view = win.view


def snap(tag):
    vp = view.viewport().rect()
    tl = view.mapToScene(0, 0)
    center = view.mapToScene(vp.center())
    print(f"{tag}: vp={vp.width()}x{vp.height()} scale={view.transform().m11():.6f} "
          f"tl=({tl.x():.3f},{tl.y():.3f}) center=({center.x():.3f},{center.y():.3f})")
    return tl, center, view.transform().m11()


print("resizeAnchor =", view.resizeAnchor())
a = snap("初始(属性区可见)")
win.property_dock.setVisible(False)
for _ in range(8):
    app.processEvents()
b = snap("隐藏属性区")
win.property_dock.setVisible(True)
for _ in range(8):
    app.processEvents()
c = snap("再显示")
print("dtl(隐藏) =", (b[0].x() - a[0].x(), b[0].y() - a[0].y()))
print("dcenter(隐藏) =", (b[1].x() - a[1].x(), b[1].y() - a[1].y()))

print("\n--- 窗口连续改尺寸 ---")
base = view.mapToScene(0, 0)
for w, h in ((1400, 900), (1600, 1000), (1200, 800), (1500, 940)):
    win.resize(w, h)
    for _ in range(6):
        app.processEvents()
    tl = view.mapToScene(0, 0)
    print(f"  {w}x{h}: tl=({tl.x():.3f},{tl.y():.3f}) "
          f"dx={tl.x() - base.x():+.3f} dy={tl.y() - base.y():+.3f}")

win.close()
app.processEvents()
