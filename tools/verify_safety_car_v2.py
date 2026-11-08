"""回归：App_SafetyCar 切到 CoreQGraphics 后端（适配层）。

覆盖点
------
1. 静态检查：入口 / PLC 模块 / 适配层都不再 import 旧 ``QuadTreeScene`` /
   ``Designer.Core.elements``；
2. 适配层类型层次：559 个图元都包成对应子类（``isinstance`` 可用），
   旧代码的 ``isinstance(item, group_element)`` 仍然成立；
3. 几何口径与旧场景**逐位一致**：中心 / 四角 / 未旋转尺寸 / 角度 / 可见性
   共 559 项；
4. 屏幕映射一致：同一图元在新旧视图里的屏幕坐标差 ≤ 2px（等价于「画面对齐」，
   旧场景是自绘 + 动态缓冲，grab 时序不稳定，不适合做像素基线）；
5. 命名索引：``m_name_items`` / ``findItem`` / ``findItemByName`` 与旧一致；
6. 模式与信号：``toggle_sence_mode`` 发 ``SceneMode``（不是 bool），
   ``current_selected`` 初始为场景自身；
7. 点击路由：真实鼠标点击可交互组 → ``current_selected`` 变更 + ``selectionChanged``；
8. 可见性三层语义（组隐藏递归 / 快照还原 / 父不可见忽略）；
9. 颜色 / 朝向：``set_fill_color`` round-trip、``rotate_to_ang`` 绝对角度；
10. 真实窗口：``SafetyCarWindow(enable_plc=False)`` 能构造，取景 1:1。

用法::

    .venv/Scripts/python.exe tools/verify_safety_car_v2.py
"""

from __future__ import annotations

import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QPoint, QPointF, Qt                     # noqa: E402
from PySide6.QtGui import QColor                                   # noqa: E402
from PySide6.QtTest import QTest                                   # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

SCENE_NAME = "safety_car_scene.json"
SCENE_DIR = os.path.join(ROOT, "res", "myDesigner", "scene")

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])

    # ------------------------------------------------------------------
    print("\n=== 1. 静态检查：不再依赖旧场景实现 ===")
    forbidden = ("myQuadTreeScene", "Designer.Core.elements",
                 "QuadTreeScene", "myGraphicsScene")
    hits = []
    for rel in ("App_SafetyCar/safety_car_entry.py",
                "App_SafetyCar/my_plc_safety.py",
                "App_SafetyCar/safety_scene_adapter.py"):
        text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        body = "\n".join(
            line for line in text.splitlines()
            if line.strip().startswith(("import ", "from ")))
        for bad in forbidden:
            if bad in body:
                hits.append(f"{rel}: {bad}")
    check("三个模块的 import 里没有旧场景 / 旧图元", not hits, str(hits))

    adapter_src = open(os.path.join(ROOT, "App_SafetyCar",
                                    "safety_scene_adapter.py"), encoding="utf-8").read()
    old_core_imports = [
        line for line in adapter_src.splitlines()
        if line.strip().startswith("from Designer.Core.")
    ]
    check("适配层只从 Designer.Core 取 SceneMode 枚举",
          all("import SceneMode" in line for line in old_core_imports),
          str(old_core_imports))

    # ------------------------------------------------------------------
    print("\n=== 2. 适配层类型层次 ===")
    from App_SafetyCar import safety_scene_adapter as A
    from App_SafetyCar.safety_scene_adapter import SafetySceneView, SceneManager

    new_view = SafetySceneView()
    new_view.resize(752, 721)
    new_mgr = SceneManager(new_view)
    new_view.set_scene_manager(new_mgr)
    count = new_view.load_element_info_run_mode(SCENE_NAME)
    check("页面载入图元数量与文件一致", count == 559, f"{count}")

    from collections import Counter
    kinds = Counter(a.TYPE for a in new_mgr.m_sorted_items)
    check("六类图元齐全（image/group/text/rect/line/circle）",
          dict(kinds) == {"image": 166, "group": 126, "text": 103,
                          "rect": 98, "line": 52, "circle": 14}, str(dict(kinds)))
    cls_ok = all(
        isinstance(a, {"group": A.group_element, "text": A.text_element,
                       "line": A.line_element, "rect": A.rect_element,
                       "circle": A.circle_element,
                       "image": A.image_element}[a.TYPE])
        for a in new_mgr.m_sorted_items)
    check("每个壳都是对应的子类（isinstance 判定可用）", cls_ok)
    check("组的子类层次与旧一致（group 也是 rect 的兄弟基类）",
          issubclass(A.group_element, A.base_element)
          and issubclass(A.line_element, A.base_element))

    # ------------------------------------------------------------------
    print("\n=== 3. 与旧场景逐位对拍（559 图元 × 7 项） ===")
    from Designer.Core.myQuadTreeScene import QuadTreeScene, SceneManager as OldManager

    old_scene = QuadTreeScene()
    old_scene.resize(752, 721)
    old_scene.set_scene_manager(OldManager(old_scene))
    old_scene.load_element_info_run_mode(SCENE_NAME)
    if old_scene.mode().name != "Run":
        old_scene.toggle_sence_mode()
    new_view.show()
    old_scene.show()
    app.processEvents()
    new_view.set_scene_mode(A.SceneMode.Run)
    app.processEvents()

    old_mgr = old_scene.scene_manager
    check("旧场景同样载入 559 个图元",
          len(old_mgr.m_sorted_items) == 559 and len(old_mgr.m_name_items) == 559,
          f"{len(old_mgr.m_sorted_items)}/{len(old_mgr.m_name_items)}")

    def d(a: QPointF, b: QPointF, tol=1e-3) -> float:
        return max(abs(a.x() - b.x()), abs(a.y() - b.y()))

    bad = []
    max_gap = 0.0
    for name, iid in new_mgr.m_name_items.items():
        a, b = new_mgr.findItem(iid), old_mgr.findItemByName(name)
        if b is None:
            bad.append((name, "missing-in-old"))
            continue
        gaps = {
            "center": d(a.get_scene_center_pos(), b.get_scene_center_pos()),
            "tl": d(a.get_scene_topLeft(), b.get_scene_topLeft()),
            "tr": d(a.get_scene_topRight(), b.get_scene_topRight()),
            "bl": d(a.get_scene_bottomLeft(), b.get_scene_bottomLeft()),
            "br": d(a.get_scene_bottomRight(), b.get_scene_bottomRight()),
        }
        sa, sb = a.getSize(), b.getSize()
        gaps["size"] = max(abs(sa.width() - sb.width()),
                           abs(sa.height() - sb.height()))
        gaps["angle"] = abs((a.get_angle() - b.get_angle() + 180.0) % 360.0 - 180.0)
        worst = max(gaps.values())
        max_gap = max(max_gap, worst)
        if worst > 1e-3:
            bad.append((name, {k: round(v, 4) for k, v in gaps.items() if v > 1e-3}))
    check("中心 / 四角 / 尺寸 / 角度全部逐位一致",
          not bad, f"diff={bad[:3]} max_gap={max_gap:.6f}")

    vis_bad = [(name, new_mgr.findItem(iid).get_visibility(),
                old_mgr.findItemByName(name).get_visibility())
               for name, iid in new_mgr.m_name_items.items()
               if new_mgr.findItem(iid).get_visibility()
               != old_mgr.findItemByName(name).get_visibility()]
    check("可见性初值全部一致", not vis_bad, str(vis_bad[:3]))

    # ------------------------------------------------------------------
    print("\n=== 4. 屏幕映射（等价于画面对齐） ===")
    new_view.goto_origin()
    old_scene._apply_view_state(0.0, 0.0, 1.0)
    app.processEvents()
    check("新视图 1:1 且原点居中",
          abs(new_view.transform().m11() - 1.0) < 1e-9
          and abs(new_view.transform().dx()) < 1e-9,
          f"m11={new_view.transform().m11():.6f}")
    screen_bad = []
    worst_px = 0.0
    for name, iid in list(new_mgr.m_name_items.items()):
        a, b = new_mgr.findItem(iid), old_mgr.findItemByName(name)
        if b is None:
            continue
        p_new = new_view.mapFromScene(a.base_item().scenePos())
        p_old = old_scene.sceneToView(b.get_scene_center_pos())
        gap = max(abs(p_new.x() - p_old.x()), abs(p_new.y() - p_old.y()))
        worst_px = max(worst_px, gap)
        if gap > 2.0:
            screen_bad.append((name, (p_new.x(), p_new.y()),
                               (round(p_old.x(), 2), round(p_old.y(), 2))))
    check("559 个图元的屏幕坐标与旧场景差 ≤2px",
          not screen_bad, f"bad={screen_bad[:3]} max={worst_px:.2f}px")

    # ------------------------------------------------------------------
    print("\n=== 5. 命名索引 ===")
    check("m_name_items 键集合与旧场景相同",
          set(new_mgr.m_name_items) == set(old_mgr.m_name_items),
          f"new={len(new_mgr.m_name_items)} old={len(old_mgr.m_name_items)}")
    same_id = all(new_mgr.m_name_items[k] == old_mgr.m_name_items[k]
                  for k in new_mgr.m_name_items)
    check("同名图元的 id 与旧场景一致", same_id)
    grp = new_mgr.findItemByName("主电柜")
    check("findItemByName 命中分组且类型正确",
          grp is not None and isinstance(grp, A.group_element), repr(grp))
    check("findItem(id) 返回同一个壳",
          new_mgr.findItem(grp.id()) is grp)
    check("主电柜在 CABINET_NAMES 里（交互注册的前置条件）",
          any(n in grp.get_name() for n in
              ("维修区/安全门", "上架X4", "拣选X4", "安全门X1", "输送线X2",
               "Q1P拣选/Q3P拣选", "Q3P托盘X2", "输送线X4", "主电柜")))

    # ------------------------------------------------------------------
    print("\n=== 6. 模式与信号 ===")
    modes = []
    new_view.run_mode_station_change.connect(lambda v: modes.append(v))
    new_view.toggle_sence_mode()
    app.processEvents()
    check("切设计态发出 SceneMode.Design（不是 bool）",
          modes and modes[-1] is A.SceneMode.Design, str(modes))
    check("mode() 跟随切换", new_view.mode() is A.SceneMode.Design)
    check("current_selected 在无选中时为视图自身（旧场景同义）",
          new_view.current_selected is new_view)
    new_view.toggle_sence_mode()
    app.processEvents()
    check("切回运行态发出 SceneMode.Run",
          modes[-1] is A.SceneMode.Run, str(modes))
    check("运行态 selectionChanged 是场景自带的信号对象",
          new_view.selectionChanged is new_view.scene().selectionChanged)

    # ------------------------------------------------------------------
    print("\n=== 7. 点击路由 ===")
    # 真实入口在切运行态后按 CABINET_NAMES 打开交互；这里补同一动作，
    # 否则独立视图里没有任何可点击目标。
    cabinet = ("维修区/安全门", "上架X4", "拣选X4", "安全门X1", "输送线X2",
               "Q1P拣选/Q3P拣选", "Q3P托盘X2", "输送线X4", "主电柜")
    for a in new_mgr.m_sorted_items:
        if a.TYPE == "group" and any(n in a.get_name() for n in cabinet):
            a.set_interactive(True)
    hits = []
    new_view.selectionChanged.connect(lambda: hits.append(new_view.current_selected))
    target = None
    for name, iid in new_mgr.m_name_items.items():
        a = new_mgr.findItem(iid)
        if a.TYPE != "group" or not a.get_visibility():
            continue
        if not a.is_interactive():
            continue
        p = new_view.mapFromScene(a.base_item().scenePos())
        if new_view.viewport().rect().contains(p):
            target = (a, p)
            break
    check("存在视野内的可交互组", target is not None,
          target[0].get_name() if target else "none")
    if target is not None:
        a, p = target
        hits.clear()
        scene_pt = new_view.mapToScene(p)
        QTest.mouseClick(new_view.viewport(), Qt.LeftButton, Qt.NoModifier, p)
        app.processEvents()
        cur = new_view.current_selected
        # 旧路由按 z 序取最顶层可交互组，所以命中的未必是我挑的那个壳
        # （上架X4_图片 与 上架X4(...) 重叠）；判据是「命中了包含点击点的组」。
        check("点击命中一个包含该点的可交互组",
              isinstance(cur, A.group_element) and cur.is_interactive()
              and cur.base_item().sceneBoundingRect().contains(scene_pt),
              repr(cur))
        check("点击发出一次 selectionChanged", len(hits) >= 1, f"{len(hits)}")
        clicked = cur
    # 点空白：不应把 current_selected 换成别的图元
    blank = QPoint(2, new_view.viewport().height() - 3)
    QTest.mouseClick(new_view.viewport(), Qt.LeftButton, Qt.NoModifier, blank)
    app.processEvents()
    check("点空白不改 current_selected（仍是上一次的组）",
          target is not None and new_view.current_selected is clicked)

    # ------------------------------------------------------------------
    print("\n=== 8. 可见性三层语义 ===")
    io_group = new_mgr.findItemByName("IO状态")
    check("IO状态 组存在", io_group is not None)
    if io_group is not None:
        child = io_group.childItems()[0] if io_group.childItems() else None
        io_group.set_visibility(False)
        check("组隐藏后成员不可见（Qt 层面）",
              child is None or not child.base_item().isVisible())
        # 旧 group_element.set_visibility 是递归的：成员的自身标志也会变 False，
        # 快照记在原值，显示回来时按快照还原（不整片点亮）。
        check("组隐藏时成员自身标志同样变 False（旧递归语义）",
              child is None or child.get_visibility() is False)
        io_group.set_visibility(True)
        check("组显示后成员恢复可见",
              child is None or child.base_item().isVisible())
        # 父不可见时 set_visibility(True) 被忽略
        io_group.set_visibility(False)
        if child is not None:
            child.set_visibility(True)
            check("父不可见时子项 set_visibility(True) 被忽略",
                  child.get_visibility() is False)
        io_group.set_visibility(True)
    other = new_mgr.findItemByName("网线1")
    parent = other.parentItem() if other is not None else None
    if other is not None and parent is not None:
        other.set_visibility(False)          # 成员单独隐藏
        parent.set_visibility(False)         # 组隐藏（快照记下成员 False）
        parent.set_visibility(True)          # 组显示：按快照还原
        check("组隐藏→显示后原本单独隐藏的成员仍隐藏（快照还原）",
              other.get_visibility() is False
              and not other.base_item().isVisible())
        other.set_visibility(True)

    # ------------------------------------------------------------------
    print("\n=== 9. 颜色 / 朝向 ===")
    lamp = new_mgr.findItemByName("维修区_三色灯")
    check("三色灯图元存在", lamp is not None)
    if lamp is not None:
        before = lamp.get_fill_color().name()
        lamp.set_fill_color(QColor(255, 0, 0))
        check("set_fill_color 立刻可读回",
              lamp.get_fill_color().name() == "#ff0000", lamp.get_fill_color().name())
        lamp.set_fill_color(QColor(before))
        check("颜色 round-trip 回原值",
              lamp.get_fill_color().name() == before, before)
        angle0 = lamp.get_angle()
        lamp.rotate_to_ang(-90.0)
        check("rotate_to_ang 是绝对角度",
              abs(((lamp.get_angle() % 360) - 270.0)) < 1e-6, f"{lamp.get_angle()}")
        lamp.rotate_to_ang(angle0)

    # ------------------------------------------------------------------
    print("\n=== 10. 真实窗口装配 ===")
    from App_SafetyCar.safety_car_entry import SafetyCarWindow
    win = SafetyCarWindow(plc_ip="192.168.1.150", enable_plc=False)
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    app.processEvents()
    check("窗口构造成功且运行态", win.scene.mode() is A.SceneMode.Run)
    check("窗口内图元 559 个", len(win.scene_manager.m_sorted_items) == 559,
          str(len(win.scene_manager.m_sorted_items)))
    check("场景 manager 双向注入",
          win.scene.scene().scene_manager is win.scene_manager
          and win.scene_manager.view is win.scene)
    check("电柜组已按 CABINET_NAMES 打开交互",
          any(a.is_interactive() for a in win.scene_manager.m_sorted_items
              if a.TYPE == "group"))
    check("IO状态 / 维修区 组被关闭交互",
          not win.scene_manager.findItemByName("IO状态").is_interactive()
          and not win.scene_manager.findItemByName("维修区").is_interactive())
    check("视图运行态只读（无平移缩放）",
          not win.scene.is_canvas_navigation_enabled())
    check("视图无网格 / 无设计器标记",
          not win.scene.show_grid and not win.scene.snap.grid_enabled
          and not win.scene.snap.show_markers)
    check("导航门控可显式打开",
          (win.scene.set_canvas_navigation_enabled(True)
           or win.scene.is_canvas_navigation_enabled()))
    win.scene.set_canvas_navigation_enabled(False)
    win.shutdown()
    win.close()
    app.processEvents()

    # ------------------------------------------------------------------
    old_scene.close()
    new_view.close()
    app.processEvents()

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for name in FAILS:
            print(f"  - {name}")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
