# -*- coding: utf-8 -*-
"""``App_PopPick_V2`` 运行态回归门禁（统一运行态模板 + 位图顶替）。

覆盖 9 组：

1. 装载：图元数 / widget 数 / JSON 零改动（装 HMI 之前）；
2. **与旧适配层对拍**：同一份 page JSON，新 ``RuntimeElement`` 与
   ``App_PopPick.qgraphics_runtime.RuntimeCard`` 的位姿 / 尺寸 / 包围盒逐卡对齐；
3. proxy：数量、尺寸、位置、旋转支点、只读切换；
4. PageDeck：槽位判定、Z 规范化、命中测试、交换后位姿与 Z 互换、重置；
5. 位图顶替：动画期 7 张全位图 + proxy 全隐藏；结束后后台 5 张静态、
   前台 2 张真实控件；整窗重绘门控与动画窗口同步；
6. 真实鼠标点击链路（QTest 点视口 → eventFilter → 交换）；
7. 取景：窗口尺寸变化后「最前面两页」重新铺满；
8. 背景：任意窗口尺寸 / 取景 / 手动缩放 / 平移下，「背景」图元与控件都覆盖
   整个视口，且运行态同步不污染设计期 ``_page``；
9. 释放：proxy / 位图清空、可重复释放。

页面现在是 **7 张卡片 + 1 张背景 widget 图元**（共 8 个 widget），所以
装载 / proxy / 对拍 / Z / 位图数的断言都按这个口径写。背景不参与 PageDeck
的卡片集合，也不进位图顶替（尺寸随视口实时变、内容逐帧动画）。

跑法::

    .venv/Scripts/python.exe tools/verify_pop_pick_v2.py
"""

from __future__ import annotations

import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, QPoint, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from App_PopPick_V2 import pop_pick_config as cfg  # noqa: E402

_RESULTS: list[tuple[bool, str, str]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    _RESULTS.append((bool(ok), label, detail))


def _report() -> int:
    failed = 0
    for ok, label, detail in _RESULTS:
        tag = "PASS" if ok else "FAIL"
        suffix = f"  ({detail})" if detail else ""
        print(f"[{tag}] {label}{suffix}")
        if not ok:
            failed += 1
    print(f"\n{len(_RESULTS) - failed}/{len(_RESULTS)} passed")
    return 0 if failed == 0 else 1


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _group(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 60 - len(title)))


# ----------------------------------------------------------------------
def group_load(page: str) -> None:
    """组 1：装载与零改动（HMI 尚未挂载）。"""
    _group("1 装载 / registry / JSON 零改动")
    import json

    from App_PopPick_V2.pop_pick_runtime import PopPickRuntime

    runtime = PopPickRuntime()
    count = runtime.load(page)
    expect_names = sorted([f"Page{i}" for i in range(7)] + [cfg.BACKGROUND_NAME])
    check("装载图元数 = 8（7 卡 + 背景）", count == 8, f"count={count}")
    check("无装载错误", not runtime.stage.load_error, runtime.stage.load_error)
    elements = runtime.stage.registry.all()
    widgets = runtime.stage.registry.widgets()
    check("图元 8 / widget 8", len(elements) == 8 and len(widgets) == 8,
          f"{len(elements)}/{len(widgets)}")
    names = [e.get_name() for e in widgets]
    check("卡片名 = Page0..Page6 + 背景",
          sorted(names) == expect_names, str(sorted(names)))
    bg = runtime.stage.element_of(cfg.BACKGROUND_NAME)
    check("背景存在且 Z 在卡片之下",
          bg is not None and bg.zValue() < 0,
          f"z={bg.zValue() if bg is not None else None}")

    with open(page, "r", encoding="utf-8") as handle:
        disk = json.load(handle)
    check("装载后 page_data 与磁盘逐字相等",
          runtime.stage.scene.page_data() == disk)
    check("pages_manager 只暴露 widget 图元（含背景）",
          len(runtime.stage.pages_manager.m_sorted_items) == 8
          and all(e.is_widget()
                  for e in runtime.stage.pages_manager.m_sorted_items))
    check("stage.report 可读", "RuntimeStage" in runtime.stage.report(),
          runtime.stage.report())
    runtime.release()


def group_parity(page: str) -> None:
    """组 2：与旧适配层（App_PopPick.qgraphics_runtime）几何对拍。

    旧包未被本轮改动，作为「改造前后等价」的独立参照：同一份 JSON、同一套
    AGV 投影，7 张卡的中心 / 角度 / 尺寸 / 包围盒必须逐位对齐（容差 0.01）。
    """
    _group("2 与旧适配层几何对拍")
    from App_PopPick.qgraphics_runtime import create_runtime_scene
    from App_PopPick_V2.pop_pick_runtime import PopPickRuntime

    view, manager = create_runtime_scene()
    view.load_scene_file(page)
    old_cards = {c.get_name(): c for c in manager.m_sorted_items}

    runtime = PopPickRuntime()
    runtime.load(page)
    new_cards = {e.get_name(): e for e in runtime.stage.pages_manager.m_sorted_items}

    check("两侧卡片名一致",
          sorted(old_cards) == sorted(new_cards),
          f"{sorted(old_cards)} vs {sorted(new_cards)}")

    worst = {"center": 0.0, "angle": 0.0, "size": 0.0, "bbox": 0.0}
    for name, old in old_cards.items():
        new = new_cards.get(name)
        # 背景是运行态动态图元：它的尺寸由 BackgroundFitter 按视口改写，
        # 与「设计期几何」对拍没有意义。这一组只验证 7 张页面卡片。
        if new is None or name == cfg.BACKGROUND_NAME:
            continue
        oc, nc = old.get_scene_center_pos(), new.get_scene_center_pos()
        worst["center"] = max(worst["center"],
                              abs(oc.x() - nc.x()), abs(oc.y() - nc.y()))
        worst["angle"] = max(worst["angle"],
                             abs(old.get_angle() - new.get_angle()))
        os_, ns = old.getSize(), new.getSize()
        worst["size"] = max(worst["size"],
                            abs(os_.width() - ns.width()),
                            abs(os_.height() - ns.height()))
        ob, nb = old.sceneBoundingRect(), new.sceneBoundingRect()
        worst["bbox"] = max(worst["bbox"],
                            abs(ob.left() - nb.left()), abs(ob.top() - nb.top()),
                            abs(ob.width() - nb.width()),
                            abs(ob.height() - nb.height()))
        # 命中测试的局部坐标换算口径也要一致
        probe = QPointF(nc.x() + nc.y() * 0.0, nc.y())
        ol, nl = old.mapFromScene(probe), new.mapFromScene(probe)
        worst["bbox"] = max(worst["bbox"],
                            abs(ol.x() - nl.x()), abs(ol.y() - nl.y()))
    for key, value in worst.items():
        check(f"{key} 最大偏差 < 0.01", value < 0.01, f"max={value:.6f}")

    runtime.release()
    view.release_embedded_widgets()


def _build_window(page: str):
    from App_PopPick_V2.pop_pick_entry import PopPickWindow

    window = PopPickWindow(scene_path=page, hmi_demo=True)
    window.show()
    _wait(400)                     # showEvent → 最大视图 refit
    return window


def group_proxy(window) -> None:
    """组 3：proxy 位姿与只读切换。"""
    _group("3 proxy 承载")
    stage = window.stage
    proxies = stage.widgets.proxies()
    check("8 个 proxy（7 卡 + 背景）", len(proxies) == 8, f"{len(proxies)}")
    check("每张卡都挂上了控件",
          all(c.has_widget_layer() for c in window.deck.cards()))
    check("背景也挂上了真实控件",
          stage.widgets.proxy_of(cfg.BACKGROUND_NAME) is not None)

    bad = []
    for card in window.deck.cards():
        proxy = proxies.get(card.item_id)
        if proxy is None:
            bad.append((card.get_name(), "no proxy"))
            continue
        rect = card.item().boundingRect()
        center = card.item().mapToScene(QPointF(0.0, 0.0))
        expect = center - QPointF(rect.width() / 2.0, rect.height() / 2.0)
        if abs(proxy.size().width() - rect.width()) > 1e-6:
            bad.append((card.get_name(), f"w {proxy.size().width()}≠{rect.width()}"))
        if (proxy.pos() - expect).manhattanLength() > 0.01:
            bad.append((card.get_name(), f"pos {proxy.pos()}≠{expect}"))
        if abs(proxy.zValue() - (card.zValue() + 0.5)) > 1e-6:
            bad.append((card.get_name(), f"z {proxy.zValue()}"))
        origin = proxy.transformOriginPoint()
        if abs(origin.x() - rect.width() / 2.0) > 1e-6:
            bad.append((card.get_name(), "origin"))
    check("proxy 尺寸 / 位置 / Z / 支点全部对齐", not bad, str(bad[:3]))

    # 只读：常规视图全只读；最大视图放开最前面两页
    window._maximized = False
    window._sync_card_readonly()
    check("常规视图全部只读",
          all(c.widget_readonly() for c in window.deck.cards()))
    window._maximize_view(announce=False)
    front = window._interactive_cards()
    check("最大视图放开两页",
          len(front) == 2 and all(not c.widget_readonly() for c in front))
    check("其余卡片仍只读",
          all(c.widget_readonly() for c in window.deck.cards()
              if c not in front))


def group_deck(window) -> None:
    """组 4：PageDeck 的槽位 / Z / 命中 / 交换 / 重置。"""
    _group("4 PageDeck 交互")
    deck = window.deck
    cards = deck.cards()
    slot = deck.slot_card()
    right_most = max(cards, key=lambda c: deck._scene.sceneToView(
        c.get_scene_center_pos()).x())
    check("槽位判定为视图最右那张", slot is right_most,
          f"slot={slot.get_name()} right={right_most.get_name()}")

    zs = sorted(c.zValue() for c in cards)
    bg = window.stage.element_of(cfg.BACKGROUND_NAME)
    bg_z = bg.zValue() if bg is not None else -1.0
    # 背景 Z=-1 会把 _normalise_z 的基准从 0 拉到 -1，卡片落在 0..6；
    # 只要「7 张连续互异、且都在背景之上」就满足堆叠语义。
    check("7 张卡 Z 连续互异且高于背景",
          len(zs) == 7
          and all(b - a == 1 for a, b in zip(zs, zs[1:]))
          and zs[0] > bg_z,
          f"zs={zs} bg_z={bg_z}")

    center = slot.get_scene_center_pos()
    hit = deck.card_at(center)
    check("槽位中心命中卡片", hit is not None, str(hit and hit.get_name()))
    check("空白处返回 None",
          deck.card_at(QPointF(center.x() + 1e6, center.y())) is None)

    # 旋转卡片：包围盒内、但不在卡片自身矩形里的点不应命中它
    rotated = next((c for c in cards if abs(c.get_angle()) > 5.0), None)
    if rotated is not None:
        box = rotated.sceneBoundingRect()
        inside = deck._contains(
            rotated, QPointF(box.left() + box.width() * 0.02,
                             box.top() + box.height() * 0.02))
        check("旋转卡片按局部矩形命中（角点不误判）", not inside,
              f"{rotated.get_name()} angle={rotated.get_angle():.1f}")

    # 交换
    target = next(c for c in cards if c is not slot)
    before = {c.get_name(): (c.get_scene_center_pos(), c.get_angle(), c.zValue())
              for c in cards}
    started = deck.swap_with_slot(target)
    check("交换动画启动", started and deck.is_busy())
    check("动画期拒绝重复点击", not deck.swap_with_slot(next(
        c for c in cards if c is not slot and c is not target)))
    _wait(900)
    check("动画结束", not deck.is_busy())
    check("槽位换人", deck.slot_card() is target,
          deck.slot_card().get_name())
    after = {c.get_name(): (c.get_scene_center_pos(), c.get_angle(), c.zValue())
             for c in cards}
    pose_ok = True
    for name in (target.get_name(), slot.get_name()):
        (c0, a0, _), (c1, a1, _) = before[name], after[name]
        other = before[slot.get_name()] if name == target.get_name() else before[target.get_name()]
        pose_ok = pose_ok and (c1 - other[0]).manhattanLength() < 0.01
    check("两张卡的位姿互换到位", pose_ok)
    check("Z 值互换", after[target.get_name()][2] == before[slot.get_name()][2]
          and after[slot.get_name()][2] == before[target.get_name()][2])

    # 收拢 / 展开：一次动 N 张卡，位图同样要跟（与交换共用动画内核）
    folded = deck.fold()
    _wait(80)
    check("收拢动画启动", folded and deck.is_folded() and deck.is_busy())
    _wait(700)
    anchor = deck.pose_of(deck.stack_cards()[0])
    drift = max((deck.pose_of(c).center - anchor.center).manhattanLength()
                for c in deck.stack_cards())
    check("收拢后左侧叠成一摞", drift < 0.01, f"max={drift:.4f}")
    check("收起状态下拒绝交换", not deck.swap_with_slot(deck.stack_cards()[-1]))
    unfolded = deck.unfold()
    _wait(700)
    check("展开动画完成", unfolded and not deck.is_folded() and not deck.is_busy())

    # 走窗口的"重置布局"：它会顺带重算「最前面两页」并通知 HMI 恢复位图分配
    # （直接 deck.reset() 不改视图状态，属于半条链路，这里要测完整路径）
    window._reset_layout()
    _wait(120)
    drift = max((c.get_scene_center_pos()
                 - deck._initial_poses[c].center).manhattanLength()
                for c in cards)
    check("重置回初始位姿", drift < 0.01, f"max={drift:.4f}")
    check("重置后最前面两页回到初始槽位",
          window.front_pages()[0] == deck.slot_card().get_name(),
          str(window.front_pages()))


def group_snapshots(window) -> None:
    """组 5：位图顶替与整窗重绘门控。"""
    _group("5 位图顶替 / 重绘门控")
    shots = window.runtime.snapshots
    deck = window.deck
    stage = window.stage

    check("空闲时前台 2 张真实控件",
          len(shots.static_ids()) == 5,
          f"static={len(shots.static_ids())}")
    front_names = [n for n in window.front_pages() if n]
    front_cards = [window.scene_manager.findItemByName(n) for n in front_names]
    check("前台两张不是静态位图",
          front_cards and all(c is not None and not shots.is_static(c)
                              for c in front_cards),
          f"front={front_names} static={[c.get_name() for c in front_cards if c and shots.is_static(c)]}")

    check("空闲时门控关闭", not shots.suppresses_full_repaint())

    target = next(c for c in deck.cards() if c is not deck.slot_card())
    deck.swap_with_slot(target)
    _wait(60)
    showing = [iid for iid in shots._items if shots._showing(iid)]
    hidden = [iid for iid, p in stage.widgets.proxies().items() if not p.isVisible()]
    check("动画期全部卡片走位图", len(showing) == 7, f"{len(showing)}")
    check("动画期 proxy 全部隐藏", len(hidden) == 7, f"{len(hidden)}")
    check("动画期整窗重绘被吞掉", shots.suppresses_full_repaint())
    # 位图位姿必须与 proxy 同帧一致（否则会看到内容与轮廓错位）
    worst = 0.0
    for card in deck.cards():
        proxy = stage.widgets.proxies().get(card.item_id)
        item = shots._items.get(card.item_id)
        if proxy is None or item is None:
            continue
        worst = max(worst, (item.pos() - proxy.pos()).manhattanLength(),
                    abs(item.rotation() - proxy.rotation()))
    check("位图与 proxy 位姿同步", worst < 0.01, f"max={worst:.4f}")

    _wait(900)
    check("动画结束关闭门控", not shots.suppresses_full_repaint())
    check("动画结束恢复 5 张静态",
          len(shots.static_ids()) == 5, str(sorted(shots.static_ids())))
    slot = deck.slot_card()
    check("槽位卡恢复真实控件", not shots.is_static(slot))
    check("槽位 proxy 可见",
          stage.widgets.proxies()[slot.item_id].isVisible())


def group_click(window) -> None:
    """组 6：真实鼠标链路（视口 → eventFilter → 交换）+ 页内交互不误交换。"""
    _group("6 鼠标点击交换")
    window._fit_view()            # 退出最大视图，卡片回到全只读
    _wait(120)
    deck = window.deck
    slot = deck.slot_card()
    target = next(c for c in deck.cards()
                  if c is not slot and abs(c.get_angle()) < 1.0)
    page_pos = target.get_scene_center_pos()
    view_pos = window.stage.view.mapFromScene(
        window.stage.view.projection.point(page_pos.x(), page_pos.y()))
    QTest.mouseClick(window.stage.view.viewport(), Qt.LeftButton,
                     Qt.NoModifier, QPoint(int(view_pos.x()), int(view_pos.y())))
    _wait(900)
    check("点击左侧卡片完成交换", deck.slot_card() is target,
          f"slot={deck.slot_card().get_name()}")

    # 最大视图下最前页放开交互：点它不该触发交换（点击被页内控件吃掉）
    window._maximize_view(announce=False)
    _wait(120)
    locked = window._unswappable_card()
    before = deck.slot_card()
    if locked is not None:
        pos = locked.get_scene_center_pos()
        vpos = window.stage.view.mapFromScene(
            window.stage.view.projection.point(pos.x(), pos.y()))
        QTest.mouseClick(window.stage.view.viewport(), Qt.LeftButton,
                         Qt.NoModifier, QPoint(int(vpos.x()), int(vpos.y())))
        _wait(700)
        check("最大视图下点最前页不触发交换", deck.slot_card() is before,
              f"slot={deck.slot_card().get_name()}")
        check("最前页仍保持可交互（未被改回只读）",
              not locked.widget_readonly())


def group_fit(window) -> None:
    """组 7：窗口尺寸变化后最前面两页重新铺满。"""
    _group("7 取景 / resize")
    window.resize(1000, 700)
    _wait(400)                    # resize → 合并 80ms → _refit_maximized
    view = window.stage.view
    front = window._interactive_cards()
    rect = None
    for card in front:
        bound = card.sceneBoundingRect()
        rect = bound if rect is None else rect.united(bound)
    projected = view.projection.rect(rect)
    scale = float(view.transform().m11())
    viewport = view.viewport().rect()
    span = max(projected.width(), projected.height()) * scale
    target = max(viewport.width(), viewport.height())
    check("最前面两页铺满短边方向",
          abs(span - target) / target < 0.06,
          f"span={span:.1f} target={target}")
    check("resize 后仍在最大视图", window._maximized)

    window.resize(*cfg.WINDOW_SIZE)
    _wait(300)


def group_background(window, page: str) -> None:
    """组 8：背景在任意缩放 / 尺寸 / 平移下都撑满视口，且零污染。

    两把尺子同时量，缺一不可：

    * page 几何：背景的 ``sceneBoundingRect()`` 要盖住当前视口反投影出来的
      page 矩形（证明 ``change_pos`` / ``change_size`` 真的按取景算过）；
    * 屏幕像素：背景 proxy 的四角映回视口坐标后要包住整个 viewport
      （证明承载控件跟着 ``WidgetHost.align`` 一起铺满，不是只有图元变大）。
    """
    import json

    _group("8 背景撑满视口")
    stage = window.stage
    view = stage.view
    fitter = window.runtime.background
    bg = stage.element_of(cfg.BACKGROUND_NAME)
    check("背景图元存在", bg is not None and bg.item() is not None)
    if bg is None or bg.item() is None:
        return

    with open(page, "r", encoding="utf-8") as handle:
        disk = json.load(handle)
    disk_bg = next((r for r in disk["items"]
                    if r["name"] == cfg.BACKGROUND_NAME), None)
    check("设计文件里有背景记录", disk_bg is not None)

    proxy = stage.widgets.proxy_of(cfg.BACKGROUND_NAME)
    check("背景挂上了真实控件",
          proxy is not None and proxy.widget() is not None)

    def covers(label: str) -> bool:
        _wait(220)                 # 轮询 50ms + 合并 16ms，留足余量
        visible = fitter.visible_page_rect()
        rect = bg.sceneBoundingRect()
        ok_page = (rect.left() <= visible.left() + 1.0
                   and rect.top() <= visible.top() + 1.0
                   and rect.right() >= visible.right() - 1.0
                   and rect.bottom() >= visible.bottom() - 1.0)
        check(f"{label}｜背景 page 矩形覆盖可见区域", ok_page,
              f"bg=({rect.left():.0f},{rect.top():.0f},"
              f"{rect.width():.0f}x{rect.height():.0f}) "
              f"vis=({visible.left():.0f},{visible.top():.0f},"
              f"{visible.width():.0f}x{visible.height():.0f})")
        if proxy is None:
            return ok_page
        sr = proxy.sceneBoundingRect()
        pts = [view.mapFromScene(p) for p in (
            sr.topLeft(), sr.topRight(), sr.bottomLeft(), sr.bottomRight())]
        xs = [float(p.x()) for p in pts]
        ys = [float(p.y()) for p in pts]
        vp = view.viewport().rect()
        ok_screen = (min(xs) <= 1.0 and min(ys) <= 1.0
                     and max(xs) >= vp.width() - 1.0
                     and max(ys) >= vp.height() - 1.0)
        check(f"{label}｜控件屏幕矩形覆盖视口", ok_screen,
              f"screen=({min(xs):.0f},{min(ys):.0f})-"
              f"({max(xs):.0f},{max(ys):.0f}) vp={vp.width()}x{vp.height()}")
        return ok_page and ok_screen

    covers("初始")
    window.resize(900, 620)
    covers("缩小窗口 900x620")
    window.resize(1500, 950)
    covers("放大窗口 1500x950")
    window._fit_view()
    covers("适应窗口")
    window._maximize_view(announce=False)
    covers("最大窗口")
    view.scale(1.8, 1.8)          # 视图静默变换，只能靠轮询兜底
    covers("视图再放大 1.8x")
    view.scale(0.45, 0.45)
    covers("视图缩小 0.45x")
    center = view.mapToScene(view.viewport().rect().center())
    view.centerOn(center + QPointF(220.0, 160.0))
    covers("平移画面")
    window.resize(*cfg.WINDOW_SIZE)
    _wait(400)

    # 运行态几何同步不能写进设计数据：只比背景那一条记录，因为 PageDeck
    # 的交换 / Z 变化本来就会把卡片的实时位姿烘焙进 page_data()。
    it = bg.item()
    live_bg = next((r for r in stage.scene.page_data()["items"]
                    if r["name"] == cfg.BACKGROUND_NAME), None)
    check("多轮缩放后背景 _page 记录 == 磁盘 JSON",
          live_bg is not None and live_bg == disk_bg,
          f"live={live_bg}")
    check("背景无脏标记",
          not getattr(it, "_dirty", False)
          and not getattr(it, "_geo_dirty", False))
    check("scene._modified 已清", not stage.scene._modified)
    check("背景不进位图快照",
          fitter.element.item_id() not in window.runtime.snapshots._items,
          f"items={sorted(window.runtime.snapshots._items)}")


def group_release(window) -> None:
    """组 9：释放。"""
    _group("9 释放")
    stage = window.stage
    window.close()
    _wait(60)
    check("proxy 全部回收", not stage.widgets.proxies())
    check("位图全部回收", window.runtime.snapshots.snapshot_count() == 0)
    # clear_page 之后 registry 的门面对象仍在（框架刻意保留以保住信号连接），
    # 但它们必须全部 detached —— item() 返回 None 才是"场景真的空了"。
    leftovers = [e.get_name() for e in stage.registry.all() if e.item() is not None]
    check("场景已清空（门面全部 detached）", not leftovers, str(leftovers))
    window.runtime.release()      # 可重复调用
    check("重复释放不抛异常", True)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    from App_PopPick_V2.pop_pick_entry import resolve_page_file

    page = resolve_page_file("page_9")
    window = None
    try:
        group_load(page)
        group_parity(page)
        window = _build_window(page)
        group_proxy(window)
        group_deck(window)
        group_snapshots(window)
        group_click(window)
        group_fit(window)
        group_background(window, page)
        group_release(window)
    except Exception:  # noqa: BLE001 - 门禁要打印完整现场
        traceback.print_exc()
        check("脚本未中断", False, "见上方 traceback")
    finally:
        if window is not None:
            try:
                window.deleteLater()
            except RuntimeError:
                pass
    return _report()


if __name__ == "__main__":
    raise SystemExit(main())
