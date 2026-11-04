"""统一入口 main.py 回归：选择页、卡片启动、关窗返回、直接 --app 启动、薄壳转发。

用法：.venv/Scripts/python.exe tools/verify_unified_entry.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import main as entry

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def click_card(card, app) -> None:
    """直接给卡片派发按下+抬起，避免依赖真实鼠标。"""
    center = card.rect().center()
    for etype in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        ev = QMouseEvent(
            etype,
            center.toPointF(),
            card.mapToGlobal(center).toPointF(),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        QApplication.sendEvent(card, ev)
    app.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])

    # ---- 1. 选择页 ----
    launcher = entry.ToolLauncher(enable_plc=False)
    launcher.show()
    app.processEvents()
    check("选择页可创建并显示", launcher.isVisible())

    cards = launcher.findChildren(entry.ToolCard)
    check("卡片数量等于注册工具数", len(cards) == len(entry.TOOLS),
          f"cards={len(cards)} tools={len(entry.TOOLS)}")
    check("卡片标题齐全", {c.tool.key for c in cards} == {t.key for t in entry.TOOLS},
          str(sorted(c.tool.key for c in cards)))

    # ---- 2. 点安全车卡片：应创建窗口并隐藏选择页 ----
    safety_card = next(c for c in cards if c.tool.key == "safety")
    click_card(safety_card, app)

    win = launcher._active
    check("点击卡片创建了工具窗口", win is not None,
          type(win).__name__ if win else "None")
    if win is None:
        launcher.close()
        return _report()

    check("工具窗口已显示", win.isVisible())
    check("选择页已隐藏", not launcher.isVisible())
    check("工具窗口继承自 QMainWindow", isinstance(win, entry.QMainWindow))
    check("重复点击不重复建窗",
          (click_card(safety_card, app), launcher._active is win)[1])

    # ---- 3. 关掉工具窗口：回到选择页，实例被清空 ----
    win.close()
    app.processEvents()
    app.processEvents()
    check("关闭工具窗口后回到选择页", launcher.isVisible())
    check("活动窗口引用已清空", launcher._active is None)
    check("关闭后窗口对象已销毁", not _alive(win))

    # ---- 4. 同样的流程换成料架工具 ----
    rack_card = next(c for c in cards if c.tool.key == "rack")
    click_card(rack_card, app)
    rack_win = launcher._active
    check("料架工具可启动", rack_win is not None,
          type(rack_win).__name__ if rack_win else "None")
    if rack_win is not None:
        rack_win.close()
        app.processEvents()
        app.processEvents()
        check("料架关窗后回到选择页", launcher.isVisible())
        check("料架活动引用已清空", launcher._active is None)

    launcher.close()
    app.processEvents()

    # ---- 5. 直接 --app 启动：不建选择页，返回 0 ----
    app.setQuitOnLastWindowClosed(True)
    rc = entry.run("safety", enable_plc=False)
    check("--app safety 直接启动返回 0", rc == 0, f"rc={rc}")
    tops = [w for w in app.topLevelWidgets()
            if isinstance(w, entry.QMainWindow) and w.isVisible()]
    check("直接启动时存在顶层工具窗口", bool(tops), f"count={len(tops)}")
    for w in tops:
        w.close()
    app.processEvents()

    # ---- 6. 薄壳转发 ----
    import rack_config_main
    import safety_car_main

    check("料架薄壳已转发 main", _forwards(rack_config_main, "rack"),
          os.path.basename(getattr(rack_config_main, "__file__", "?")))
    # 包内也有 App_SafetyCar/safety_car_main.py，同名模块容易被包目录的
    # sys.path 污染遮住，这里连文件路径一起校验。
    check("安全车薄壳已转发 main", _forwards(safety_car_main, "safety"),
          os.path.basename(getattr(safety_car_main, "__file__", "?")))

    return _report()


def _alive(widget) -> bool:
    try:
        widget.objectName()
        return True
    except RuntimeError:
        return False


SHIM_FILES = {"rack": "rack_config_main.py", "safety": "safety_car_main.py"}


def _forwards(module, key: str) -> bool:
    """薄壳必须是根目录那份文件，并且转发的是 main.main。"""
    path = os.path.abspath(getattr(module, "__file__", "") or "")
    return (
        getattr(module, "main", None) is entry.main
        and path == os.path.join(ROOT, SHIM_FILES[key])
    )


def _report() -> int:
    failed = 0
    for name, ok, detail in results:
        if not ok:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
