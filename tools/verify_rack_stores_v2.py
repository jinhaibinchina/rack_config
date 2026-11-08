"""回归：料仓总览窗口 / 单页料仓窗口 V2（CoreQGraphics 后端）。

覆盖点
------
1. 适配层图元壳的类型层次（组/文本/线/矩形各归各类，``isinstance`` 可用）；
2. 几何口径与旧场景逐位一致（``page_center`` / ``page_bounding_rect`` /
   ``get_scene_topLeft`` / ``get_scene_head_pos`` / ``get_scene_end_pos``）；
3. ``change_position`` 对齐的是左上角（旧 ``group_element`` 语义），斜图元也精确；
4. 可见性三层语义：叶子直改、组递归、组隐藏→显示按快照还原、
   「父不可见时 set_visibility(True) 被忽略」；
5. 颜色 / 填充映射到新场景 Style，读写 round-trip；
6. ``context`` 写入走 ``set_page_field``（会重绘、会联动边框）；
7. 真实鼠标点击命中仓位组并发 ``slot_clicked``，空白处不误触发；
8. 双击空白发 ``double_clicked_without_group``；
9. 4 个 model 全部绑定成功（10 料架 / 80 仓位 / 32 灯 / 5 HMI / 流程组）；
10. 取景与旧窗口同口径（viewport 尺寸、``min(vw/pw, vh/ph)``、背景色合成）；
11. 旧窗口仍可用（model 层双栈兼容，没有把旧路径改坏）。

用法::

    .venv/Scripts/python.exe tools/verify_rack_stores_v2.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QPoint, QPointF, Qt                     # noqa: E402
from PySide6.QtGui import QColor, QWheelEvent                      # noqa: E402
from PySide6.QtTest import QTest                                   # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])

    from App_RackConfig.run import rack_scene_adapter as A
    from App_RackConfig.run.rack_stores_widget_v2 import RackStoresWindowV2

    win = RackStoresWindowV2()
    win.resize(900, 700)
    win.show()
    app.processEvents()
    app.processEvents()

    scene, view, mgr = win.scene, win.view, win.SceneManager
    store = win.rack_store_model

    # ------------------------------------------------------------------
    print("\n=== 1. 适配层索引与类型 ===")
    check("场景载入成功", not win.load_error, win.load_error)
    check("图元数与场景一致", len(mgr) == len(scene.all_items()),
          f"{len(mgr)} vs {len(scene.all_items())}")
    check("m_sorted_items 按 z 升序",
          all(mgr.m_sorted_items[i]._item.zValue() <= mgr.m_sorted_items[i + 1]._item.zValue()
              for i in range(len(mgr.m_sorted_items) - 1)))
    check("按名查找命中仓位组",
          isinstance(mgr.findItemByName("料架2_仓位1"), A.group_element))
    check("按名查找命中文本",
          isinstance(mgr.findItemByName("料架2_仓位1_编号"), A.text_element))
    check("按名查找命中直线",
          isinstance(mgr.findItemByName("HMI1_直线_1"), A.line_element))
    check("不存在的名字返回 None", mgr.findItemByName("不存在的图元") is None)
    check("适配壳可哈希且稳定（_click_groups 用 set 去重）",
          len({mgr.findItemByName("料架2_仓位1"),
               mgr.findItemByName("料架2_仓位1")}) == 1)

    # ------------------------------------------------------------------
    print("\n=== 2. 几何口径与旧场景逐位一致 ===")
    from Designer.Core.myQuadTreeScene import QuadTreeScene, SceneManager as OldMgr
    from Designer.Core.my_common import SceneMode
    from res.designer_resource_manager import resource_manager as res_mng

    old = QuadTreeScene()
    old.set_scene_mode(SceneMode.Run)
    old_mgr = OldMgr(old)
    old.set_scene_manager(old_mgr)
    old.load_element_info_run_mode("rack_config_scene2.json")
    # 旧场景的取景是在 show 时算的（``_apply_pending_view_rect``），不 show
    # 就只有 640×480 的默认尺寸和 scale=1.0。另外它在新窗口里是「被布局塞进去
    # 的子控件」（878×678），所以这里也套一层同样的布局，尺寸口径才可比。
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    host = QWidget()
    host_layout = QVBoxLayout(host)
    host_layout.addWidget(old)
    host.resize(900, 700)
    host.show()
    app.processEvents()
    app.processEvents()

    names = ("料架2_仓位1", "料架2_仓位1_编号", "料架2", "HMI1", "流程", "HMI1_直线_1")
    worst = 0.0
    for name in names:
        a, b = old_mgr.findItemByName(name), mgr.findItemByName(name)
        if a is None or b is None:
            check(f"{name} 两边都能找到", False, f"old={a is None} new={b is None}")
            continue
        pairs = (
            (a.get_scene_center_pos(), b.get_scene_center_pos()),
            (a.get_scene_topLeft(), b.get_scene_topLeft()),
            (a.get_scene_head_pos(), b.get_scene_head_pos()),
            (a.get_scene_end_pos(), b.get_scene_end_pos()),
        )
        d = max(max(abs(p.x() - q.x()), abs(p.y() - q.y())) for p, q in pairs)
        worst = max(worst, d)
    check("中心 / 左上 / 头 / 尾 与旧场景逐位一致（<0.01）", worst < 0.01, f"最大偏差 {worst:.4f}")

    # change_position 对齐左上角
    grp = mgr.findItemByName("料架3_仓位1")
    grp.change_position(QPointF(100.0, 200.0))
    tl = grp.get_scene_topLeft()
    check("change_position 后左上角精确落在目标点",
          abs(tl.x() - 100.0) < 0.01 and abs(tl.y() - 200.0) < 0.01,
          f"({tl.x():.3f},{tl.y():.3f})")
    size_before = grp.sceneBoundingRect().size()
    grp.change_position(QPointF(400.0, -300.0))
    check("change_position 不改尺寸",
          abs(grp.sceneBoundingRect().width() - size_before.width()) < 0.01
          and abs(grp.sceneBoundingRect().height() - size_before.height()) < 0.01)

    # ------------------------------------------------------------------
    print("\n=== 3. 可见性三层语义 ===")
    slot = store.rack(2).slot(1)
    g = slot.group
    pallet = slot.parts["托盘"]

    pallet.set_visibility(False)
    check("叶子图元自身标志 = False", pallet.get_visibility() is False)
    check("叶子图元真的不绘制", not pallet.base_item().isVisible())
    pallet.set_visibility(True)
    check("叶子图元恢复", pallet.base_item().isVisible())

    pallet.set_visibility(False)           # 故意留一个单独隐藏的成员
    kids = g.childItems()
    g.set_visibility(False)
    check("组隐藏：成员自身标志全 False", all(k.get_visibility() is False for k in kids),
          f"成员 {len(kids)}")
    check("组隐藏：成员真的不绘制", all(not k.base_item().isVisible() for k in kids))
    g.set_visibility(True)
    check("组显示：成员自身标志按快照还原",
          pallet.get_visibility() is False
          and all(k.get_visibility() for k in kids if k is not pallet))
    check("组显示：不点亮本来单独隐藏的成员", not pallet.base_item().isVisible())
    pallet.set_visibility(True)

    # 父不可见时子项 set_visibility(True) 被忽略
    g.set_visibility(False)
    pallet.set_visibility(True)
    check("父不可见时子项 set_visibility(True) 被忽略",
          pallet.get_visibility() is False)
    g.set_visibility(True)
    check("父恢复后子项按快照还原（那次被忽略的调用不留痕）",
          pallet.get_visibility() is True)
    pallet.set_visibility(True)

    # ------------------------------------------------------------------
    print("\n=== 4. 颜色 / 填充 / 文本 ===")
    num = slot.number_label
    num.set_color(QColor("#FF0000"))
    check("set_color / get_color round-trip",
          num.get_color() == QColor("#FF0000"), num.get_color().name())
    num.set_color(QColor("#000000"))

    light = slot.parts["灯带"]
    slot.set_light_color("绿")
    check("灯带填充色 = 绿", light.get_fill_color() == QColor("#00FF00"),
          light.get_fill_color().name())

    num.set_fill(True)
    check("set_fill(True) 生效", num.get_fill() is True)
    num.set_fill(False)
    check("set_fill(False) 生效", num.get_fill() is False)

    slot.set_number("77")
    check("编号文本写入并 strip 后一致", num.context.strip() == "77", repr(num.context))
    check("重复写同一文本不报错", (slot.set_number("77"), True)[1])

    # ------------------------------------------------------------------
    print("\n=== 5. 点击路由（真实鼠标事件）===")
    hits: list[tuple[int, int]] = []
    win.slot_clicked.connect(lambda r, s: hits.append((r, s)))

    def click_slot(rack_no: int, slot_no: int) -> None:
        c = store.rack(rack_no).slot(slot_no).group.get_scene_center_pos()
        sp = scene.projection.point(c.x(), c.y())
        vp = view.mapFromScene(sp)
        QTest.mouseClick(view.viewport(), Qt.LeftButton,
                         pos=QPoint(int(vp.x()), int(vp.y())))
        app.processEvents()

    view.setFocus()
    hits.clear()
    click_slot(2, 1)
    check("点击仓位组发 slot_clicked", hits == [(2, 1)], str(hits))
    check("被点仓位编号变红",
          store.rack(2).slot(1).number_label.get_color() == QColor("#FF0000"))
    check("其它仓位编号恢复黑",
          store.rack(2).slot(2).number_label.get_color() == QColor("#000000"))

    hits.clear()
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=QPoint(15, 15))
    app.processEvents()
    check("点空白处不发 slot_clicked", hits == [], str(hits))

    dbl: list[int] = []
    scene.double_clicked_without_group.connect(lambda: dbl.append(1))
    QTest.mouseDClick(view.viewport(), Qt.LeftButton, pos=QPoint(15, 15))
    app.processEvents()
    check("双击空白发 double_clicked_without_group", bool(dbl))
    check("双击空白后面板被隐藏", win.panel_status.group.get_visibility() is False)

    # ------------------------------------------------------------------
    print("\n=== 6. 四个 model 绑定 ===")
    check("料架 10 台", store.rack_numbers() == list(range(1, 11)), str(store.rack_numbers()))
    check("每台 8 个仓位",
          all(sorted(r.slots) == list(range(1, 9)) for r in store.racks.values()))
    check("料仓模型无告警", not store.warnings, str(store.warnings[:2]))
    check("状态面板 32 盏灯", len(win.panel_status.lamps) == 32,
          str(len(win.panel_status.lamps)))
    check("状态面板无告警", not win.panel_status.warnings, str(win.panel_status.warnings[:2]))
    check("5 个 HMI 面板都绑定",
          all(m.text is not None and m.line1 is not None and m.line2 is not None
              for m in win.rack_hmi_config_models))
    check("流程面板绑定", win.rack_process_model.group is not None
          and win.rack_process_model.text is not None)

    # ------------------------------------------------------------------
    print("\n=== 7. 取景与旧窗口同口径 ===")
    import json
    data = json.load(open(res_mng.get_json_path("rack_config_scene2.json"), encoding="utf-8"))
    sr = data["sceneRect"]
    from PySide6.QtCore import QRectF
    page_rect = QRectF(sr["x"], sr["y"], sr["width"], sr["height"])
    check("view_scene_rect = JSON sceneRect", scene.view_scene_rect() == page_rect)
    target = scene.projection.rect(page_rect)
    avail = view.viewport().rect()
    want_scale = min(avail.width() / target.width(), avail.height() / target.height())
    check("缩放 = min(视口宽/页宽, 视口高/页高)",
          abs(view.transform().m11() - want_scale) < 1e-12,
          f"m11={view.transform().m11():.15f} want={want_scale:.15f}")
    check("缩放与旧场景 scale_factor 逐位相同",
          abs(view.transform().m11() - old.scale_factor) < 1e-12,
          f"{view.transform().m11():.15f} vs {old.scale_factor:.15f}")
    check("viewport 尺寸与旧控件一致", view.viewport().size() == old.size(),
          f"{view.viewport().size()} vs {old.size()}")
    center_vp = view.mapToScene(view.viewport().rect().center())
    # QGraphicsView 的 centerOn 是靠调滚动条实现的，滚动条只有整像素，缩放之后
    # 会残留 1~2 个**屏幕像素**的取整误差；旧场景是纯数学 offset，没有这一层。
    # 这里换算成像素再卡阈值（1 scene 单位只有 0.16px，直接比 scene 单位没意义）。
    scale_now = view.transform().m11()
    dx_px = abs(center_vp.x() - target.center().x()) * scale_now
    dy_px = abs(center_vp.y() - target.center().y()) * scale_now
    check("页面中心落在视口中心（整像素取整误差内）",
          dx_px < 2.0 and dy_px < 2.0, f"Δ=({dx_px:.2f}px, {dy_px:.2f}px)")

    # 导航门控：总览窗口装着 1618 个图元，默认放开滚轮缩放/中键平移
    # （``rack_stores_widget_v2`` 显式打开）；开关本身仍然可关。
    # 测试完必须 fit_scene() 复原，第 8 节要按同一变换渲染对比。
    check("总览窗口默认放开画布导航", view.is_canvas_navigation_enabled())
    view.set_canvas_navigation_enabled(False)
    check("可一键关掉两个开关",
          not view.is_pan_enabled() and not view.is_zoom_enabled()
          and not view.is_canvas_navigation_enabled())
    m0 = view.transform().m11()
    nav_pt = view.viewport().rect().center()
    nav_ev = QWheelEvent(QPointF(nav_pt),
                         QPointF(view.viewport().mapToGlobal(nav_pt)),
                         QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                         Qt.NoModifier, Qt.NoScrollPhase, False)
    app.sendEvent(view.viewport(), nav_ev)
    app.processEvents()
    check("门控关闭时滚轮不缩放", abs(view.transform().m11() - m0) < 1e-12,
          f"{m0:.15f} -> {view.transform().m11():.15f}")
    view.set_canvas_navigation_enabled(True)
    app.sendEvent(view.viewport(), nav_ev)
    app.processEvents()
    check("门控打开后滚轮缩放生效",
          view.transform().m11() > m0 * 1.01,
          f"{m0:.6f} -> {view.transform().m11():.6f}")
    view.set_canvas_navigation_enabled(False)
    view.fit_scene()
    check("关回后取景恢复原状",
          abs(view.transform().m11() - m0) < 1e-12,
          f"{view.transform().m11():.15f} want={m0:.15f}")

    # ------------------------------------------------------------------
    print("\n=== 8. 渲染与旧窗口对齐（视觉护栏）===")
    old_win = None
    try:
        from App_RackConfig.run.rack_stores_widget import RackStoresWindow
        old_win = RackStoresWindow()
        old_win.resize(900, 700)
        old_win.show()
        app.processEvents()
        app.processEvents()
        check("旧窗口仍可构造（model 层双栈兼容）",
              old_win.rack_store_model.rack(2).slot(1).number_label is not None)
    except Exception as exc:                       # noqa: BLE001
        check("旧窗口仍可构造（model 层双栈兼容）", False, repr(exc))

    if old_win is not None:
        from PySide6.QtGui import QImage
        img_old = old_win.grab().toImage().convertToFormat(QImage.Format_RGB32)
        img_new = win.grab().toImage().convertToFormat(QImage.Format_RGB32)

        def centroid(img) -> tuple[float, float]:
            bg1, bg2 = img.pixel(12, 12), img.pixel(5, 300)   # 页面底色 / 窗口底色
            n = sx = sy = 0
            for y in range(0, img.height(), 3):
                for x in range(0, img.width(), 3):
                    p = img.pixel(x, y)
                    if p not in (bg1, bg2):
                        n += 1
                        sx += x
                        sy += y
            return (sx / n, sy / n) if n else (0.0, 0.0)

        ca, cb = centroid(img_old), centroid(img_new)
        dx, dy = cb[0] - ca[0], cb[1] - ca[1]
        check("画面内容质心偏移 < 3px（取景/图元位置一致）",
              abs(dx) < 3.0 and abs(dy) < 3.0, f"Δ=({dx:+.2f},{dy:+.2f})")
        check("页面背景色与旧窗口一致",
              img_old.pixel(12, 12) == img_new.pixel(12, 12),
              f"{img_old.pixel(12, 12):#010x} vs {img_new.pixel(12, 12):#010x}")
        old_win.close()

    # ------------------------------------------------------------------
    print("\n=== 9. 单页料仓窗口（scene1）===")
    from App_RackConfig.run.rack_store_widget_v2 import RackStoreWindowV2
    w2 = RackStoreWindowV2()
    w2.resize(400, 700)
    w2.show()
    app.processEvents()
    app.processEvents()
    check("scene1 载入成功", not w2.load_error, w2.load_error)
    check("scene1 图元 23 个", len(w2.SceneManager) == 23, str(len(w2.SceneManager)))
    item_names = ("A库位空筒", "A库位满料", "B库位空筒", "B库位满料",
                  "单库位空筒", "单库位满料", "双库托盘", "单库托盘")
    check("8 个状态图元都在",
          all(w2.SceneManager.findItemByName(n) is not None for n in item_names))
    w2.update_rack_store_display([1, 0, 0, 1, 0, 0, 1, 0])
    app.processEvents()
    got = [w2.SceneManager.findItemByName(n).get_visibility() for n in item_names]
    check("按 8 位状态刷新可见性", got == [True, False, False, True, False, False, True, False],
          str(got))

    # ------------------------------------------------------------------
    print("\n=== 10. 静态检查：运行时不再依赖旧场景 ===")
    import ast
    import pathlib
    adir = pathlib.Path(ROOT) / "App_RackConfig" / "run"
    offenders = []
    for fname in ("rack_scene_adapter.py", "rack_stores_widget_v2.py",
                  "rack_store_widget_v2.py"):
        tree = ast.parse((adir / fname).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("Designer.Core."):
                    offenders.append(f"{fname}: {node.module}")
    check("V2 三个模块不 import Designer.Core.*", not offenders, str(offenders))
    check("model 层也已切到适配层",
          "from .rack_scene_adapter import" in
          (adir / "rack_store_model.py").read_text(encoding="utf-8"))

    print()
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for name in FAILS:
            print("  -", name)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
