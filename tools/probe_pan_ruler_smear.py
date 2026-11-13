"""拖动画布：屏幕实况 vs 全量重绘的像素差（刻度带残影回归探针）。

    .venv/Scripts/python.exe tools/probe_pan_ruler_smear.py

需要真实显示环境（不能用 QT_QPA_PLATFORM=offscreen，离屏没有 blit 行为）。

屏幕抓取拿到的是「真实显示出来的东西」，全量 grab 拿到的是「应该长什么样」，
两者的差就是拖动过程中残留的脏像素（刻度带被 blit 推入画布的那种）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SRC = "Designer/Core/data.json/datas/design/pages/page_1.json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out")

app = QApplication.instance() or QApplication(sys.argv)
from Designer.CoreQGraphics.ui import DesignerWindow  # noqa: E402
from Designer.CoreQGraphics.g_view import _RULER_THICKNESS as T  # noqa: E402

window = DesignerWindow(SRC)
window.setWindowFlag(Qt.WindowStaysOnTopHint, True)
window.resize(1200, 800)
window.show()
window.raise_()
window.activateWindow()
app.processEvents()
time.sleep(0.5)
window.view.fit_content()
app.processEvents()
time.sleep(0.3)

vp = window.view.viewport()
print("items:", len(window.scene.all_items()), "vp:", vp.width(), vp.height())


def capture(tag):
    """返回 (屏幕实况, 全量重绘) 两张同尺寸 QImage。"""
    window.raise_()
    window.activateWindow()
    app.processEvents()
    origin = vp.mapToGlobal(QPoint(0, 0))
    scr = QGuiApplication.primaryScreen()
    live = scr.grabWindow(0, origin.x(), origin.y(), vp.width(), vp.height()).toImage()
    clean = vp.grab().toImage()
    live.save(os.path.join(OUT, f"drag_{tag}_live.png"))
    clean.save(os.path.join(OUT, f"drag_{tag}_clean.png"))
    return live, clean


def diff_ratio(live, clean, y0=T):
    total = bad = 0
    for y in range(y0, min(live.height(), clean.height()), 2):
        for x in range(0, min(live.width(), clean.width()), 2):
            total += 1
            if live.pixelColor(x, y) != clean.pixelColor(x, y):
                bad += 1
    return bad / max(total, 1)


def old_refresh():
    w, h = vp.width(), vp.height()
    vp.update(QRect(0, 0, w, T))
    vp.update(QRect(0, 0, T, h))


new_refresh = window.view._refresh_ruler_strips

for tag, refresh in (("old", old_refresh), ("new", new_refresh)):
    window.view._refresh_ruler_strips = refresh
    # 每次从同一位置开始，保证 A/B 可比
    window.view.fit_content()
    app.processEvents()
    hb = window.view.horizontalScrollBar()
    vb = window.view.verticalScrollBar()
    h0, v0 = hb.value(), vb.value()
    QTest.mousePress(vp, Qt.MiddleButton, Qt.NoModifier, QPoint(600, 420))
    app.processEvents()
    for i in range(40):
        QTest.mouseMove(vp, QPoint(600 + i * 4, 420 + i * 2))
        if i % 5 == 0:
            app.processEvents()
    app.processEvents()
    live, clean = capture(tag)
    print(f"{tag}: scroll Δ=({hb.value() - h0},{vb.value() - v0}) "
          f"diff={diff_ratio(live, clean):.4f} pad={window.view._ruler_scroll_pad}")
    QTest.mouseRelease(vp, Qt.MiddleButton, Qt.NoModifier, QPoint(756, 498))
    app.processEvents()
    time.sleep(0.2)

print("done")
