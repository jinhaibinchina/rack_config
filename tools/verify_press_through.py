"""承载层「按住」语义回归：点动按钮按住必须真的保持按下。

背景
----
``EmbeddedWidgetLayer`` 为了兼顾"点控件"和"拖画布"，对左键做延迟派发：
按下先扣住，超过 ``startDragDistance`` 判为拖动画布、press 永不派发，没超
阈值才在松手时补发 press+release。

这对按钮是致命的：按住期间控件收不到 press，点动按钮（按住写 True /
松开写 False）会在松手那一刻才连续发出 ``pressed`` + ``released``，业务上
看到的就是"按下即抬起"。

修法是按下点命中"有按住语义的控件"（按钮 / 输入框 / 表格 / 滑块 / 可点灯，
见 ``PRESS_THROUGH_TYPES``）时立刻直通，整个手势交还视图；命中页面空白 /
卡片时仍走延迟派发，画布照样能拖。

用法::

    .venv/Scripts/python.exe tools/verify_press_through.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import QEvent, QPoint, QPointF, QSizeF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from Designer.Core.embedded_widget_layer import EmbeddedWidgetLayer

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "OK  " if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -> {detail}" if detail else ""))
    if not condition:
        FAILURES.append(name)


class FakeHost(QWidget):
    """冒充场景宿主：承载层只用到 offset / 平移开关 / 两个回调。"""

    def __init__(self) -> None:
        super().__init__()
        self.offset = QPointF(0.0, 0.0)
        self.pan_calls = 0
        self.sync_calls = 0
        self._pan_enabled = True

    def update_coordinate(self) -> None:
        self.pan_calls += 1

    def _sync_embedded_widgets_geometry(self) -> None:
        self.sync_calls += 1

    def is_pan_enabled(self) -> bool:
        return self._pan_enabled


def send(widget, etype, pos, button=Qt.MouseButton.LeftButton,
         buttons=Qt.MouseButton.LeftButton) -> None:
    ev = QMouseEvent(
        etype,
        QPointF(pos),
        QPointF(widget.mapToGlobal(pos)),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, ev)


def main() -> int:
    app = QApplication.instance() or QApplication([])

    host = FakeHost()
    host.resize(420, 320)
    host.show()

    log: list[str] = []
    button = QPushButton("点动")
    button.setFixedSize(120, 44)
    button.pressed.connect(lambda: log.append("pressed"))
    button.released.connect(lambda: log.append("released"))

    page = QWidget()
    page.setFixedSize(300, 200)
    page_lay = QVBoxLayout(page)
    page_lay.setContentsMargins(0, 0, 0, 0)
    page_lay.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    layer = EmbeddedWidgetLayer(host)
    layer.set_interactive(True)
    layer.set_widget(page)
    layer.apply(QPointF(210.0, 160.0), QSizeF(300.0, 200.0), 1.0, 0.0)
    layer.set_visible(True)
    for _ in range(8):
        app.processEvents()

    viewport = layer._viewport
    center = button.mapTo(viewport, button.rect().center())
    blank = QPoint(viewport.width() - 4, viewport.height() - 4)

    # --- 1. 按住不放：pressed 必须已经发出，按钮保持按下态 -------------
    send(viewport, QEvent.Type.MouseButtonPress, center)
    for _ in range(3):
        app.processEvents()
    check("按住按钮即触发 pressed", log == ["pressed"], f"log={log}")
    check("按钮保持按下态 isDown()", button.isDown(), f"isDown={button.isDown()}")
    check("press 未被承载层扣住",
          layer._press_pending is False, f"_press_pending={layer._press_pending}")

    # --- 2. 松手：released 才出现 ---------------------------------------
    send(viewport, QEvent.Type.MouseButtonRelease, center,
         button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.NoButton)
    for _ in range(3):
        app.processEvents()
    check("松手才 released（不是同帧连发）",
          log == ["pressed", "released"], f"log={log}")

    # --- 3. 空白处按住：仍走延迟派发，保留画布平移 ----------------------
    log.clear()
    send(viewport, QEvent.Type.MouseButtonPress, blank)
    for _ in range(3):
        app.processEvents()
    check("空白处 press 仍被扣住（保留平移）",
          layer._press_pending is True and log == [],
          f"pending={layer._press_pending} log={log}")

    # --- 4. 空白处拖动 → 画布平移生效 ----------------------------------
    before = QPointF(host.offset)
    send(viewport, QEvent.Type.MouseMove, blank + QPoint(40, 30),
         button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.LeftButton)
    for _ in range(3):
        app.processEvents()
    check("空白处拖动平移画布", host.offset != before,
          f"offset {before} -> {host.offset}")
    send(viewport, QEvent.Type.MouseButtonRelease, blank + QPoint(40, 30),
         button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.NoButton)
    for _ in range(3):
        app.processEvents()

    # --- 5. 空白处点一下：不误触按钮 -----------------------------------
    log.clear()
    send(viewport, QEvent.Type.MouseButtonPress, blank)
    send(viewport, QEvent.Type.MouseButtonRelease, blank,
         button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.NoButton)
    for _ in range(3):
        app.processEvents()
    check("空白处点击不误触按钮", log == [], f"log={log}")

    print()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项: {FAILURES}")
    else:
        print("全部通过")

    layer.dispose()
    host.close()
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
