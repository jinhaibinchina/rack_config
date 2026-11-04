"""运行态选中联动回归：点击可选中组应触发 scene.selectionChanged。

在此之前 Run 模式下 mousePressEvent 完全跳过选中逻辑，
current_selected 永不更新、selectionChanged 永不发射，
safety_car_main 里连的两个槽（IO 联动 / 站点说明面板）等于死代码。

用法：.venv/Scripts/python.exe tools/verify_run_selection.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from Designer.Core.my_common import SceneMode

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    from safety_car_main import SafetyCarWindow

    win = SafetyCarWindow(enable_plc=False)
    win.resize(1600, 1000)
    win.show()
    app.processEvents()

    scene = win.scene
    check("场景进入运行模式", scene.mode() == SceneMode.Run, f"mode={scene.mode()}")

    manager = scene.scene_manager

    from Designer.Core.elements import group_element

    candidates = [
        item
        for item in manager.m_sorted_items
        if isinstance(item, group_element)
        and item.get_visibility()
        and item.get_selectable()
        and not item.is_in_group()
    ]
    check("存在运行态可选中组", len(candidates) > 0, f"count={len(candidates)}")
    if not candidates:
        _report()
        return 1

    # 统计信号发射次数
    fired = {"n": 0}
    scene.selectionChanged.connect(lambda: fired.__setitem__("n", fired["n"] + 1))

    target = candidates[0]
    center = target.sceneBoundingRect().center()
    view_pos = scene.sceneToView(center)

    before = scene.current_selected
    QTest.mouseClick(scene, Qt.LeftButton, Qt.NoModifier, view_pos.toPoint())
    app.processEvents()

    after = scene.current_selected
    check("current_selected 被更新", after is not before,
          f"before={type(before).__name__} after={type(after).__name__}")
    check("current_selected 命中目标组", after is target,
          f"target={target.get_name()!r} after={getattr(after, 'get_name', lambda: '')()!r}")
    check("selectionChanged 已发射", fired["n"] >= 1, f"fired={fired['n']}")

    # 重复点击同一组不应重复发射（set_current_select_item 有变化才 emit）
    n_before = fired["n"]
    QTest.mouseClick(scene, Qt.LeftButton, Qt.NoModifier, view_pos.toPoint())
    app.processEvents()
    check("重复点击同一组不重复发射", fired["n"] == n_before,
          f"before={n_before} after={fired['n']}")

    # 运行态不得给图元打选中标记（否则 paint 会画设计期红色 id）
    selected_flags = [i.get_selected() for i in manager.m_sorted_items if i.get_selected()]
    check("运行态未设置 set_selected", not selected_flags, f"selected={len(selected_flags)}")

    # 槽函数本身可执行（panel 刷新 / IO 联动不抛异常）
    try:
        win.update_property_area()
        win.plc_safety.handle_selectionChanged()
        check("两个槽函数执行无异常", True)
    except Exception as exc:  # noqa: BLE001
        check("两个槽函数执行无异常", False, f"{type(exc).__name__}: {exc}")

    # 运行态事件路由（myQuadTreeScene._find_event_group_at）只把「绑定了事件 /
    # 可切换 / 可交互」的组写进 current_selected，普通站点组点上去不抢选中。
    # 这里按图元实际能力决定断言方向，语义调整时不用改测试。
    win.scene.set_current_select_item(manager.findItem(manager.m_name_items["主电柜"]))
    win.plc_safety.handle_station_change("安全门工作站")
    station = manager.findItem(manager.m_name_items["安全门"])
    check("切站后站点组可见", station.get_visibility())

    drives = bool(
        station.has_event_bindings()
        or station.is_toggle_enabled()
        or station.is_interactive()
    )
    fired["n"] = 0
    hit = _find_hit_point(scene, station)
    check("站点组几何可命中", hit is not None)
    if hit is not None:
        QTest.mouseClick(scene, Qt.LeftButton, Qt.NoModifier, scene.sceneToView(hit).toPoint())
        app.processEvents()
        cur = scene.current_selected
        cur_name = getattr(cur, "get_name", lambda: "")()
        if drives:
            check("点击站点组后选中它", cur is station, f"current={cur_name!r}")
            check("点击站点组触发 selectionChanged", fired["n"] == 1, f"fired={fired['n']}")
        else:
            check("无事件绑定的站点组不抢选中", cur is not station, f"current={cur_name!r}")
            check("无事件绑定的站点组不触发 selectionChanged", fired["n"] == 0,
                  f"fired={fired['n']}")
        check("站点说明面板已显示", win.property_dock.isVisible())
        check("站点说明面板有内容", win.property_container.content_stack.count() > 0,
              f"pages={win.property_container.content_stack.count()}")

    win.close()
    return _report()


def _find_hit_point(scene, item):
    """在组包围盒里找一个能命中它的场景点（组中心可能落在空洞上）。"""
    rect = item.sceneBoundingRect()
    for fx in (0.5, 0.35, 0.65, 0.2, 0.8):
        for fy in (0.5, 0.35, 0.65, 0.2, 0.8):
            p = QPointF(rect.left() + rect.width() * fx, rect.top() + rect.height() * fy)
            finder = getattr(scene, "_find_visible_group_at", None)
            if finder is None or finder(p) is item:
                return p
    return None


def _report() -> int:
    failed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{mark}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
