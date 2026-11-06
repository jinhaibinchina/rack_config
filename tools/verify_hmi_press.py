"""在真实 PopPick HMI 页面（嵌套 ScrollBody）上验证按住语义。

复现路径：HmiPage → ScrollBody(QGraphicsView + ProxyWidget) → 内层页面控件
→ MomentaryButton。按钮在**内层场景**里，承载层的 childAt 找不到它，所以
靠两条兜底：
1. 宿主禁用画布平移（PopPick 运行态就是）→ 承载层完全不拦事件；
2. 平移启用时，按下点命中的是嵌套的 QGraphicsView（ScrollBody）→ 直通。

跑法：.venv/Scripts/python.exe build/diag/verify_hmi_press.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import QEvent, QPointF, QSizeF, Qt
from PySide6.QtGui import QFontDatabase, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

from App_PopPick.hmi.pages import make_page_specs
from App_PopPick.hmi.tag_catalog import TagCatalog
from App_PopPick.hmi.widgets import MomentaryButton
from Designer.Core.embedded_widget_layer import EmbeddedWidgetLayer


class FakeHost(QWidget):
    """模拟宿主场景；``pan_enabled`` 对应 pop_pick_entry 的导航开关。"""

    def __init__(self, pan_enabled: bool) -> None:
        super().__init__()
        self.offset = QPointF(0.0, 0.0)
        self._pan_enabled = pan_enabled

    def update_coordinate(self) -> None:
        pass

    def _sync_embedded_widgets_geometry(self) -> None:
        pass

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


def run_case(app, catalog, pan_enabled: bool, failures: list[str]) -> None:
    tag = "平移禁用" if not pan_enabled else "平移启用"
    print(f"\n===== {tag} =====")

    page = {s.page_id: s for s in make_page_specs()}["axis"].factory(catalog)
    page.set_connection(True, "opc.tcp://192.168.1.88:4840")
    page.seed_demo()

    host = FakeHost(pan_enabled)
    host.resize(800, 1060)
    host.show()

    layer = EmbeddedWidgetLayer(host)
    layer.set_interactive(True)
    layer.set_widget(page)
    layer.apply(QPointF(400.0, 530.0), QSizeF(750.0, 1000.0), 1.0, 0.0)
    layer.set_visible(True)
    for _ in range(10):
        app.processEvents()

    buttons = page.body.content.findChildren(MomentaryButton)
    if not buttons:
        print("!! 页面里没有点动按钮")
        failures.append(f"{tag}: 无按钮")
        layer.dispose()
        host.close()
        return

    target = buttons[0]
    log: list[str] = []
    target.pressed.connect(lambda: log.append("pressed"))
    target.released.connect(lambda: log.append("released"))

    viewport = layer._viewport
    pos = viewport.mapFromGlobal(target.mapToGlobal(target.rect().center()))

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"[{'OK  ' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))
        if not ok:
            failures.append(f"{tag}: {name}")

    send(viewport, QEvent.Type.MouseButtonPress, pos)
    for _ in range(4):
        app.processEvents()
    check("按住立刻触发 pressed", log == ["pressed"], f"log={log}")
    check("保持按下态", target.isDown(), f"isDown={target.isDown()}")
    check("press 未被扣住",
          layer._press_pending is False, f"_press_pending={layer._press_pending}")

    send(viewport, QEvent.Type.MouseMove, pos + QPointF(9.0, 7.0).toPoint(),
         button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.LeftButton)
    for _ in range(3):
        app.processEvents()
    check("按住移动不打断按下态", log == ["pressed"] and target.isDown(),
          f"log={log} isDown={target.isDown()}")

    send(viewport, QEvent.Type.MouseButtonRelease, pos,
         button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.NoButton)
    for _ in range(4):
        app.processEvents()
    check("松手才 released", log == ["pressed", "released"], f"log={log}")

    layer.dispose()
    page.shutdown()
    host.close()
    app.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families():
        for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
            if os.path.isfile(path):
                QFontDatabase.addApplicationFont(path)

    catalog = TagCatalog()
    failures: list[str] = []
    run_case(app, catalog, False, failures)
    run_case(app, catalog, True, failures)

    print()
    if failures:
        print(f"失败 {len(failures)} 项: {failures}")
    else:
        print("全部通过")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
