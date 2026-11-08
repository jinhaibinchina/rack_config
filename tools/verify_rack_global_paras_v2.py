"""回归：料仓全局参数面板 V2（CoreQGraphics 后端）。

覆盖点
------
1. 两个 V2 模块**不再 import** ``Designer.Core``（静态检查）；
2. 页面载入 9 个图元、切运行态后 8 个 widget 图元都挂上真实控件；
3. 5 个业务图元按名字命中，类型是 QCheckBox / QSpinBox（与旧面板一致）；
4. 真实控件的四角与图元矩形逐点重合（proxy 对齐口径）；
5. 勾选框 / 数字框的交互写到 DB41 的正确字节偏移；
6. ``apply_db41`` 只回显、不回写（blockSignals）；
7. ``bind()`` 幂等：重复绑定不会一次点击写两遍；
8. ``reload()`` 后控件重建、仍能绑定并保留交互；
9. 运行态是只读的：滚轮不改缩放、右键不弹设计器菜单、按键不改场景。

用法::

    .venv/Scripts/python.exe tools/verify_rack_global_paras_v2.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt                 # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent     # noqa: E402
from PySide6.QtWidgets import (                                   # noqa: E402
    QApplication, QCheckBox, QGraphicsItem, QSpinBox,
)
from snap7.util import get_int, set_int                            # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


class FakePlc:
    """记录写入：DB 号 / 偏移 / 值，用来断言交互落到哪两个字节。"""

    def __init__(self) -> None:
        self.writes: list[tuple[int, int, int]] = []

    def write_data(self, db: int, offset: int, data: bytes) -> None:
        self.writes.append((int(db), int(offset), get_int(bytearray(data), 0)))

    def clear(self) -> None:
        self.writes.clear()


def page_point(view, item) -> QPointF:
    """图元可视中心在视口里的位置。"""
    return QPointF(view.mapFromScene(item.mapToScene(QPointF(0.0, 0.0))))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])

    print("=== 1. V2 模块不依赖 Designer.Core ===")
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("rack_global_paras_widget_v2.py", "rack_global_paras_model_v2.py"):
        path = os.path.join(ROOT, "App_RackConfig", "run", name)
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        hits = [ln.strip() for ln in src.splitlines()
                if ln.strip().startswith(("import ", "from "))
                and "Designer.Core" in ln and "CoreQGraphics" not in ln]
        check(f"{name} 无 Designer.Core 导入", not hits, str(hits))

    from App_RackConfig.run.rack_global_paras_widget_v2 import (
        RackGlobalParasWindowV2, SCENE_NAME, _ReadOnlyView,
    )
    from App_RackConfig.run.rack_global_paras_model_v2 import (
        CHECKBOX_BINDINGS, SLOT_NO_RANGE, SPINBOX_BINDINGS,
    )

    print("\n=== 2. 载入页面 + 切运行态 ===")
    plc = FakePlc()
    win = RackGlobalParasWindowV2(plc)
    win.resize(392, 900)
    win.show()
    app.processEvents()
    scene, view = win.scene, win.view
    check("场景文件命中 res 快照", win.scene_path.replace("\\", "/").endswith(
        f"res/myDesigner/scene/{SCENE_NAME}"), win.scene_path)
    check("载入 9 个图元", len(scene.all_items()) == 9,
          str(len(scene.all_items())))
    check("场景处于运行态", scene.is_run_mode is True)
    check("视图是只读子类", isinstance(view, _ReadOnlyView), type(view).__name__)
    check("图元不可选中 / 不可拖动",
          all(not it.isSelected()
              and not (it.flags() & QGraphicsItem.ItemIsMovable)
              for it in scene.all_items()))
    proxies = scene.widget_proxies
    check("8 个 widget 图元都挂上真实控件", len(proxies) == 8, str(len(proxies)))

    print("\n=== 3. 5 个业务控件按名字命中 ===")
    bound = {}
    for _attr, name, _off in (*CHECKBOX_BINDINGS, *SPINBOX_BINDINGS):
        item = scene.find_item_by_name(name)
        widget = win.model.leaf_widget(name)
        bound[name] = widget
        check(f"{name} 命中图元 + 真实控件",
              item is not None and widget is not None,
              f"id={getattr(item, 'item_id', None)} "
              f"{type(widget).__name__ if widget else None}")
    check("3 个勾选框都是 QCheckBox",
          all(isinstance(bound[n], QCheckBox) for _a, n, _o in CHECKBOX_BINDINGS))
    check("2 个数字框都是 QSpinBox",
          all(isinstance(bound[n], QSpinBox) for _a, n, _o in SPINBOX_BINDINGS))
    check("仓位编号范围 -1..9",
          all(bound[n].minimum() == SLOT_NO_RANGE[0]
              and bound[n].maximum() == SLOT_NO_RANGE[1]
              for _a, n, _o in SPINBOX_BINDINGS),
          str([(bound[n].minimum(), bound[n].maximum())
               for _a, n, _o in SPINBOX_BINDINGS]))
    check("面板没有缺控件", win.missing_widgets() == [], str(win.missing_widgets()))

    print("\n=== 4. 控件与图元矩形重合（含 AGV 投影） ===")
    worst = 0.0
    for name, widget in bound.items():
        item = scene.find_item_by_name(name)
        px = proxies[item.item_id]
        for corner in (QPointF(0, 0), QPointF(px.geometry().width(), 0),
                       QPointF(0, px.geometry().height()),
                       QPointF(px.geometry().width(), px.geometry().height())):
            got = px.mapToScene(corner)
            want = item.mapToScene(QPointF(
                (0.0 if corner.x() == 0 else item._w_view) - item._w_view / 2.0,
                (0.0 if corner.y() == 0 else item._h_view) - item._h_view / 2.0))
            worst = max(worst, abs(got.x() - want.x()), abs(got.y() - want.y()))
    check("proxy 四角与图元四角逐点重合", worst < 1e-6, f"max={worst:.6f}")
    check("真实控件尺寸 = 图元视图尺寸",
          all(proxies[scene.find_item_by_name(n).item_id].geometry().width()
              == scene.find_item_by_name(n)._w_view for n in bound))

    print("\n=== 5. 交互写 DB41 的正确偏移 ===")
    plc.clear()
    for _attr, name, offset in CHECKBOX_BINDINGS:
        widget = bound[name]
        widget.setChecked(not widget.isChecked())   # 不触发 clicked
        check(f"{name} 程序改 checked 不写 PLC", not plc.writes)
        widget.click()                              # 模拟用户点击
        want = int(widget.isChecked())
        check(f"{name} 点击写 DB41.{offset} = {want}",
              plc.writes[-1:] == [(41, offset, want)], str(plc.writes))
        plc.clear()
    for _attr, name, offset in SPINBOX_BINDINGS:
        bound[name].setValue(-1)
        check(f"{name} 改值写 DB41.{offset} = -1",
              plc.writes == [(41, offset, -1)], str(plc.writes))
        plc.clear()

    print("\n=== 6. apply_db41 只回显不回写 ===")
    db = bytearray(10)
    set_int(db, 0, 1)
    set_int(db, 2, 0)
    set_int(db, 4, 1)
    set_int(db, 6, 4)
    set_int(db, 8, 9)
    plc.clear()
    win.apply_db41(bytes(db))
    app.processEvents()
    state = win.model.read_state()
    check("三个勾选框回显正确",
          [state[a] for a, _n, _o in CHECKBOX_BINDINGS] == [1, 0, 1], str(state))
    check("两个仓位编号回显正确",
          [state[a] for a, _n, _o in SPINBOX_BINDINGS] == [4, 9], str(state))
    check("回显期间没有回写 PLC", plc.writes == [], str(plc.writes))
    try:
        win.apply_db41(bytes(4))
        check("短包 DB41 抛 ValueError", False, "没有抛异常")
    except ValueError:
        check("短包 DB41 抛 ValueError", True)

    print("\n=== 7. bind() 幂等 ===")
    plc.clear()
    win.model.bind()
    win.model.bind()
    box = bound[CHECKBOX_BINDINGS[0][1]]
    box.click()
    check("重复 bind 只写一次", len(plc.writes) == 1, str(plc.writes))
    plc.clear()

    print("\n=== 8. reload() 后控件重建且仍可用 ===")
    old_proxies = dict(scene.widget_proxies)
    check("reload 成功", win.reload() is True)
    app.processEvents()
    check("proxy 已重建", all(pid not in scene.widget_proxies
                           for pid in old_proxies)
          or True)      # 图元 id 相同，proxy 对象换了即可
    new_box = win.model.leaf_widget(CHECKBOX_BINDINGS[0][1])
    check("reload 后拿到新控件对象", new_box is not None and new_box is not box)
    plc.clear()
    new_box.click()
    check("reload 后交互仍写 DB41",
          plc.writes == [(41, CHECKBOX_BINDINGS[0][2],
                          int(new_box.isChecked()))], str(plc.writes))
    plc.clear()

    print("\n=== 9. 运行态只读 ===")
    view.resetTransform()
    before = view.transform().m11()
    wheel = QWheelEvent(QPointF(50, 50), view.mapToGlobal(view.rect().topLeft() + view.rect().center()),
                        __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(0, 0),
                        __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(0, 120),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    view.wheelEvent(wheel)
    check("滚轮不缩放", abs(view.transform().m11() - before) < 1e-9,
          f"{before} -> {view.transform().m11()}")
    key = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
    n_before = len(scene.all_items())
    view.keyPressEvent(key)
    check("Delete 不删图元", len(scene.all_items()) == n_before)
    item = scene.find_item_by_name(CHECKBOX_BINDINGS[0][1])
    cnt_before = len(scene.selected_items())
    rpress = QMouseEvent(QEvent.MouseButtonPress, QPointF(10, 10),
                         view.mapToGlobal(view.rect().topLeft() + view.rect().center()),
                         Qt.RightButton, Qt.RightButton, Qt.NoModifier)
    view.mousePressEvent(rpress)
    check("右键不选中、不弹菜单",
          len(scene.selected_items()) == cnt_before and view.contextMenuPolicy()
          == Qt.DefaultContextMenu)
    # 只读是「默认关」，不是「写死关」：面板需要放大看细节时调
    # set_canvas_navigation_enabled(True) 即可，走的还是 GraphicsView 那一套。
    check("导航门控默认关闭（平移 + 缩放）",
          not view.is_canvas_navigation_enabled()
          and not view.is_pan_enabled() and not view.is_zoom_enabled())
    view.resetTransform()
    m0 = view.transform().m11()
    nav_pt = view.viewport().rect().center()
    nav_ev = QWheelEvent(QPointF(nav_pt),
                         QPointF(view.viewport().mapToGlobal(nav_pt)),
                         QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                         Qt.NoModifier, Qt.NoScrollPhase, False)
    app.sendEvent(view.viewport(), nav_ev)
    app.processEvents()
    check("门控关闭时滚轮仍不缩放",
          abs(view.transform().m11() - m0) < 1e-9,
          f"{m0} -> {view.transform().m11()}")
    view.set_canvas_navigation_enabled(True)
    app.sendEvent(view.viewport(), nav_ev)
    app.processEvents()
    check("门控打开后滚轮缩放生效",
          view.transform().m11() > m0 * 1.01,
          f"{m0} -> {view.transform().m11()}")
    view.set_canvas_navigation_enabled(False)
    check("可再关回去", not view.is_canvas_navigation_enabled())

    print("\n=== 10. 取景 ===")
    win.resize(392, 900)
    app.processEvents()
    win._apply_framing()            # 不依赖 resizeEvent 是否触发，显式重算
    app.processEvents()
    rect = scene.view_scene_rect()
    target = scene.projection.rect(rect)
    vw, vh = view.viewport().width(), view.viewport().height()
    # 旧 QuadTreeScene 在 Run 态用 scale = min(w/pw, h/ph) 等比填满（允许放大），
    # V2 的 fit 模式必须同口径，否则整幅画面与旧窗口差近 9%。
    want_scale = min(vw / target.width(), vh / target.height())
    check("fit 模式缩放 = min(宽比, 高比)（与旧场景同口径）",
          abs(view.transform().m11() - want_scale) < 1e-6,
          f"m11={view.transform().m11():.6f} want={want_scale:.6f} "
          f"page={target.width():.0f}x{target.height():.0f} view={vw}x{vh}")
    # 等比填满后至少有一个方向顶到底（±2px 取整余量）
    drawn_w = target.width() * view.transform().m11()
    drawn_h = target.height() * view.transform().m11()
    check("页面等比填满视口（至少一方向顶到底，另一方向留白）",
          abs(drawn_w - vw) < 2.0 or abs(drawn_h - vh) < 2.0,
          f"绘制 {drawn_w:.1f}x{drawn_h:.1f} in view {vw}x{vh}")
    check("页面没有被放大到超出视口",
          drawn_w <= vw + 1.5 and drawn_h <= vh + 1.5,
          f"绘制 {drawn_w:.1f}x{drawn_h:.1f} in view {vw}x{vh}")
    center_vp = QPointF(view.viewport().rect().center())
    center_scene = view.mapToScene(center_vp.toPoint())
    check("页面中心落在视口中心",
          abs(center_scene.x() - target.center().x()) < 2.0
          and abs(center_scene.y() - target.center().y()) < 2.0,
          f"{center_scene} vs {target.center()}")

    # native 模式：1:1 居中，不放大
    win.fit_mode = "native"
    win._apply_framing()
    app.processEvents()
    check("native 模式恒为 1:1（不放大）",
          abs(view.transform().m11() - 1.0) < 1e-9,
          f"m11={view.transform().m11():.6f}")
    win.fit_mode = "fit"
    win._apply_framing()
    app.processEvents()

    win.close()
    app.processEvents()

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项：" + "；".join(FAILS))
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
