"""App_PopPick 新场景后端（``Designer/CoreQGraphics``）回归。

运行::

    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tools/verify_pop_pick_qgraphics.py

覆盖四组契约：

1. **装配与数据**：主链路不再 import ``Designer.Core``；同一份 page JSON；
   7 张卡 / 7 个真实 HMI 页面 / 7 个 QGraphicsProxyWidget；proxy 不进
   ``SceneIndex``、不改 page_data；源文件零改动。
2. **几何对拍**：与旧 Core 逐卡比 ``sceneBoundingRect`` / 中心 / 角度 / Z，
   38 个采样点逐点比命中测试，坐标往返精确。
3. **运行态**：网格 / 选中标记 / 画布导航关闭；只读穿透、后台页位图快照、
   缩放取景、交换动画与收拢展开。
4. **关窗**：proxy 与页面控件全部回收，没有幽灵顶层窗口。

旧的 ``verify_pop_pick_swap.py`` 是 ``Designer/Core`` 基线：它直接访问
``EmbeddedWidgetLayer.view``、把自绘 scene 当 QWidget 点击，并断言旧的 6 卡
布局，迁移后不再适用；本脚本是它的新后端对应物。
"""

from __future__ import annotations

import ast
import os
import sys
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, QPointF, QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsView  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

try:
    _NO_CACHE = QGraphicsItem.CacheMode.NoCache
    _MIN_UPDATE = QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate
except AttributeError:  # pragma: no cover - 兼容旧式枚举别名
    _NO_CACHE = QGraphicsItem.NoCache
    _MIN_UPDATE = QGraphicsView.MinimalViewportUpdate

PAGE = os.path.join(ROOT, "Designer", "Core", "data.json", "datas", "design",
                    "pages", "page_9.json")
SCENE = os.path.join(ROOT, "res", "myDesigner", "scene", "pop_pick_scene.json")

_PASSED = 0
_FAILED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global _PASSED, _FAILED
    if ok:
        _PASSED += 1
        print(f"  [OK] {label}" + (f"  {detail}" if detail else ""))
    else:
        _FAILED += 1
        print(f"  [FAIL] {label}" + (f"  {detail}" if detail else ""))


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_finished(deck, timeout_ms: int = 3000) -> bool:
    spent = 0
    while deck.is_busy() and spent < timeout_ms:
        wait(40)
        spent += 40
    return not deck.is_busy()


def main_chain_imports(path: str) -> list[str]:
    """主链路里所有 ``from Designer.Core...`` 的模块名（排除 CoreQGraphics）。"""
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if mod.startswith("Designer.Core") and mod != "Designer.CoreQGraphics" \
                    and not mod.startswith("Designer.CoreQGraphics."):
                hits.append(mod)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                if mod.startswith("Designer.Core") and mod != "Designer.CoreQGraphics" \
                        and not mod.startswith("Designer.CoreQGraphics."):
                    hits.append(mod)
    return hits


def old_backend():
    """加载旧 Core 场景作对拍基线（只在回归脚本里用，不属于运行主链路）。"""
    from Designer.Core.myQuadTreeScene import (
        QuadTreeScene, SceneManager, SceneSerializer,
    )
    from Designer.Core.my_common import SceneMode
    from Designer.Core.elements import widget_element
    from App_PopPick.page_deck import PageDeck

    scene = QuadTreeScene()
    manager = SceneManager(scene, parent=scene)
    scene.set_scene_manager(manager)
    SceneSerializer.deserialize_scene(scene, SCENE, mode=SceneMode.Design)
    cards = [it for it in manager.m_sorted_items if isinstance(it, widget_element)]
    return scene, PageDeck(scene, cards)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    print("=== 0. 主链路依赖 / 数据文件 ===")
    main_files = [
        os.path.join(ROOT, "App_PopPick", "pop_pick_entry.py"),
        os.path.join(ROOT, "App_PopPick", "page_deck.py"),
        os.path.join(ROOT, "App_PopPick", "qgraphics_runtime.py"),
        os.path.join(ROOT, "App_PopPick", "hmi", "binding.py"),
    ]
    legacy = []
    for path in main_files:
        legacy += [(os.path.basename(path), m) for m in main_chain_imports(path)]
    check("主链路零 Designer.Core import", not legacy, str(legacy))
    check("页面文件存在", os.path.isfile(PAGE) and os.path.isfile(SCENE))
    before_page = open(PAGE, "rb").read()
    before_scene = open(SCENE, "rb").read()

    from App_PopPick import PopPickWindow
    from App_PopPick.page_deck import find_page_cards
    from App_PopPick.hmi.pages import HmiPage

    win = PopPickWindow(enable_plc=False, hmi_demo=True, scene_path=SCENE)
    win.resize(1280, 820)
    win.show()
    wait(180)                       # 等初始 resize 的取景重算收敛

    view, scene, deck, manager = win.scene, win.scene.scene(), win.deck, win.scene_manager
    layer = view._layer

    print("\n=== 1. 装配与数据 ===")
    check("场景是 CoreQGraphics.GraphicsScene",
          type(scene).__name__ == "GraphicsScene", type(scene).__name__)
    check("视图是 QGraphicsView 子类",
          type(view).__name__ == "RuntimeView" and view.viewport() is not None)
    cards = deck.cards()
    check("识别出 7 张页面卡片", len(cards) == 7, ",".join(c.get_name() for c in cards))
    check("find_page_cards 走鸭子类型也得到 7 张",
          len(find_page_cards(manager.m_sorted_items)) == 7)
    check("槽位卡是 Page0", deck.slot_card().get_name() == "Page0",
          deck.slot_card().get_name())
    check("7 个真实 HMI 页面已挂载", sum(len(v) for v in win._hmi._pages.values()) == 7,
          str({k: len(v) for k, v in win._hmi._pages.items()}))
    check("HMI 无缺失卡片", not win._hmi._missing, str(win._hmi._missing))
    proxies = layer.proxies()
    check("7 个 QGraphicsProxyWidget", len(proxies) == 7, str(len(proxies)))
    sizes = {(p.widget().size().width(), p.widget().size().height())
             for p in proxies.values() if p.widget() is not None}
    check("页面控件尺寸 750x1000", sizes == {(750, 1000)}, str(sizes))
    check("proxy 不进 SceneIndex", len(scene.all_items()) == 7,
          str(len(scene.all_items())))
    check("proxy 不进 page_data", len(scene.page_data()["items"]) == 7,
          str(len(scene.page_data()["items"])))
    check("页面文件全程零改动",
          open(PAGE, "rb").read() == before_page
          and open(SCENE, "rb").read() == before_scene)

    print("\n=== 1.5 proxy 与图元几何对齐（白框 / 内容溢出回归） ===")

    def proxy_misalignment():
        bad = []
        for card in cards:
            proxy = proxies.get(card.item_id)
            if proxy is None:
                bad.append((card.get_name(), "no proxy"))
                continue
            a, b = card.item.sceneBoundingRect(), proxy.sceneBoundingRect()
            d = max(abs(a.x() - b.x()), abs(a.y() - b.y()),
                    abs(a.width() - b.width()), abs(a.height() - b.height()))
            if d > 1e-4:
                bad.append((card.get_name(), round(d, 3)))
        return bad

    check("7 张卡 proxy 包围盒与图元逐项对齐（含 5 张旋转卡）",
          not proxy_misalignment(), str(proxy_misalignment()))
    flat = [c for c in cards if abs(c.item.rotation()) < 1e-6]
    check("未旋转卡无「半卡片偏移」",
          all(abs(proxies[c.item_id].pos().x()
                  - (c.item.mapToScene(QPointF(0, 0)).x()
                     - c.item.boundingRect().width() / 2.0)) < 1e-4
              for c in flat))

    def snapshot_misalignment():
        """位图（动画期真正在画的东西）必须和图元包围盒逐项一致。

        位图是按显示分辨率缩过的，DPR 换算一旦算错就会差出几个像素：
        平时看不出来，动画里就是「卡片边缘多一条白边」。
        """
        bad = []
        for card in cards:
            snap = layer._snapshots.get(card.item_id)
            if snap is None:
                continue
            a, b = card.item.sceneBoundingRect(), snap.sceneBoundingRect()
            d = max(abs(a.x() - b.x()), abs(a.y() - b.y()),
                    abs(a.width() - b.width()), abs(a.height() - b.height()))
            if d > 1e-4:
                bad.append((card.get_name(), round(d, 3)))
        return bad

    def drawn_pose_drift():
        """每张卡**真正画在哪儿**是否等于 ``PageDeck`` 期望的位姿。

        必须从图元的实时变换反读（``mapToScene(0,0)`` + ``rotation()``），
        不能读 ``page_center()`` / ``page_angle()``：那两个是记录值，位姿写错
        时它们照样"自洽"，2026-11-08 的斜卡飞走事故就是这么漏掉的
        （``set_page_center`` 拿 ``scenePos`` 平移，旋转过的图元会偏心）。
        """
        proj = view.projection
        bad = []
        for card in cards:
            pose = deck.pose_of(card)
            item = card.item
            c = item.mapToScene(QPointF(0.0, 0.0))
            cx, cy = proj.inverse_point(c.x(), c.y())
            dc = max(abs(cx - pose.center.x()), abs(cy - pose.center.y()))
            da = abs((-float(item.rotation()) - pose.angle + 180) % 360 - 180)
            if dc > 0.5 or da > 0.05:
                bad.append((card.get_name(), f"绘制中心偏 {dc:.1f}", f"角度偏 {da:.2f}"))
        return bad

    print("\n=== 2. 与旧 Core 几何 / 命中对拍 ===")
    old_scene, old_deck = old_backend()
    old_map = {c.get_name(): c for c in old_deck.cards()}
    bad_rect, bad_pose = [], []
    for card in cards:
        o = old_map[card.get_name()]
        r1, r2 = o.sceneBoundingRect(), card.sceneBoundingRect()
        if any(abs(a - b) > 1e-4 for a, b in
               ((r1.x(), r2.x()), (r1.y(), r2.y()),
                (r1.width(), r2.width()), (r1.height(), r2.height()))):
            bad_rect.append(card.get_name())
        p1, p2 = o.get_scene_center_pos(), card.get_scene_center_pos()
        if (abs(p1.x() - p2.x()) > 1e-4 or abs(p1.y() - p2.y()) > 1e-4
                or abs(o.get_angle() - card.get_angle()) > 1e-4
                or abs(o.zValue() - card.zValue()) > 1e-9):
            bad_pose.append(card.get_name())
    check("逐卡 sceneBoundingRect 与旧场景一致", not bad_rect, str(bad_rect))
    check("逐卡中心 / 角度 / Z 与旧场景一致", not bad_pose, str(bad_pose))

    samples = []
    for card in cards:
        p, size = card.get_scene_center_pos(), card.getSize()
        samples.append(QPointF(p))
        for dx, dy in ((0.25, 0.25), (-0.25, -0.25), (0.3, -0.3), (-0.3, 0.3)):
            samples.append(QPointF(p.x() + dx * size.width(),
                                   p.y() + dy * size.height()))
    samples += [QPointF(-100000, -100000), QPointF(0, 0), QPointF(3000, -5000)]
    mismatch = []
    for p in samples:
        a, b = old_deck.card_at(p), deck.card_at(p)
        na = a.get_name() if a else None
        nb = b.get_name() if b else None
        if na != nb:
            mismatch.append((p.x(), p.y(), na, nb))
    check(f"{len(samples)} 个采样点命中结果与旧场景一致", not mismatch,
          str(mismatch[:3]))

    probe = QPointF(123.5, -456.25)
    back = view.viewToScene(view.sceneToView(probe))
    check("sceneToView / viewToScene 往返精确",
          abs(back.x() - probe.x()) < 1e-6 and abs(back.y() - probe.y()) < 1e-6,
          f"({back.x()}, {back.y()})")
    check("sceneToView 与旧场景逐点一致",
          all(abs(view.sceneToView(p).x() - old_scene.sceneToView(p).x()) < 1e-6
              and abs(view.sceneToView(p).y() - old_scene.sceneToView(p).y()) < 1e-6
              for p in samples[:5]))

    print("\n=== 3. 运行态门控 / 取景 ===")
    check("运行模式已开启", scene.is_run_mode is True)
    check("网格 / 中心点标记关闭", not view.show_grid and not view.show_ids)
    check("运行态关闭图元 hover 高亮",
          all(not it.acceptHoverEvents() for it in scene.all_items()))
    check("运行态按最小脏区重绘（动画期只重画变化的卡）",
          view.viewportUpdateMode() == _MIN_UPDATE)
    check("proxy 不启用 ItemCoordinateCache（避免缓存变换错乱）",
          all(p.cacheMode() == _NO_CACHE for p in proxies.values()))
    check("运行态占位框不产出像素（真实控件已完全覆盖）",
          all(bool(c.item.flags() & QGraphicsItem.ItemHasNoContents) for c in cards))
    check("画布导航关闭", not view.is_canvas_navigation_enabled())
    scale0 = view.transform().m11()

    class _WheelProbe:
        ignored = False

        def ignore(self):
            self.ignored = True

    wheel = _WheelProbe()
    view.wheelEvent(wheel)              # 导航禁用时 wheelEvent 只调 event.ignore()
    check("滚轮事件被忽略（不会缩放画布）", wheel.ignored
          and abs(view.transform().m11() - scale0) < 1e-9,
          f"{scale0} -> {view.transform().m11()}")
    win._fit_view()
    check("适应窗口后变换有效", view.transform().m11() > 0,
          str(round(view.transform().m11(), 5)))
    win._maximize_view(announce=False)
    check("最大窗口后变换有效", view.transform().m11() > 0,
          str(round(view.transform().m11(), 5)))
    front = win.front_pages()
    ro = {c.get_name(): c.widget_readonly() for c in cards}
    check("最前面两页放开交互，其余只读",
          not ro[front[0]] and not ro[front[1]]
          and all(v for k, v in ro.items() if k not in front), str(ro))
    cache = {c.get_name(): c.is_motion_cache() for c in cards}
    check("后台页标记静态 / 前台两页实时",
          not cache[front[0]] and not cache[front[1]]
          and all(v for k, v in cache.items() if k not in front), str(cache))
    check("只读卡的 proxy 不吃鼠标",
          all(proxies[c.item_id].acceptedMouseButtons() == Qt.MouseButton.NoButton
              for c in cards if ro[c.get_name()]))

    print("\n=== 4. 真实鼠标点击 → 交换动画 ===")
    win._set_maximized(False)
    target = None
    for card in cards:
        if card is deck.slot_card():
            continue
        p, size = card.get_scene_center_pos(), card.getSize()
        for dx, dy in ((0, 0), (0.3, 0), (-0.3, 0), (0, 0.3), (0, -0.3),
                       (0.35, 0.35), (-0.35, -0.35)):
            pt = QPointF(p.x() + dx * size.width(), p.y() + dy * size.height())
            if deck.card_at(pt) is card:
                target = (card, pt)
                break
        if target:
            break
    check("找到可点击的非槽位卡片", target is not None,
          target[0].get_name() if target else "")
    if target:
        card, page_pt = target
        win_pt = view.mapFromScene(view.sceneToView(page_pt))
        before_slot = deck.slot_card()
        z_before = {c.get_name(): c.zValue() for c in cards}
        pose_target = deck.pose_of(card)
        pose_slot = deck.pose_of(before_slot)
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, win_pt)
        check("鼠标点击后进入交换动画", deck.is_busy())
        # 动画期必须「全部卡换成位图 + proxy 全隐藏」。这条是新后端的性能
        # 命门：只要能画出真实控件，一帧就是 100ms（7 × 750×1000 页面），
        # 而且位图与控件同时可见时等于两遍都画，比不换更慢。
        snap_vis = {iid: s.isVisible() for iid, s in layer._snapshots.items()}
        proxy_vis = {iid: p.isVisible() for iid, p in layer.proxies().items()}
        check("动画期全部卡切成位图、proxy 全部隐藏",
              len(layer._snapshots) == len(cards) and not any(proxy_vis.values()),
              f"位图 {len(snap_vis)} / 可见 proxy {sum(proxy_vis.values())}")
        check("动画期无「位图与控件双显」",
              all(not (snap_vis.get(iid) and proxy_vis.get(iid))
                  for iid in proxy_vis))
        wait(120)                      # 动画中间帧，连续旋转/平移最容易留残影
        costs = []
        for _ in range(6):
            app.processEvents()
            t0 = time.perf_counter()
            view.viewport().repaint()
            costs.append((time.perf_counter() - t0) * 1000.0)
            wait(8)
        costs.sort()
        mid_cost = costs[len(costs) // 2]
        widths = sorted({s.pixmap().width() for s in layer._snapshots.values()})
        check("动画期单帧油漆 <25ms（≈40fps 以上）", mid_cost < 25.0,
              f"{mid_cost:.1f}ms | 样本 {[round(c, 1) for c in costs]} | 位图宽 {widths}")
        check("动画中间帧 proxy 仍与图元对齐", not proxy_misalignment(),
              str(proxy_misalignment()))
        check("动画中间帧位图精确覆盖图元（无半像素/尺寸偏差）",
              not snapshot_misalignment(), str(snapshot_misalignment()))
        check("交换在超时前结束", wait_finished(deck))
        check("点中的卡进入槽位", deck.slot_card() is card,
              deck.slot_card().get_name())
        check("两张卡 Z 互换",
              card.zValue() == z_before[before_slot.get_name()]
              and before_slot.zValue() == z_before[card.get_name()])
        check("进场卡落到原槽位位姿",
              abs(deck.pose_of(card).center.x() - pose_slot.center.x()) < 1e-3
              and abs(deck.pose_of(card).center.y() - pose_slot.center.y()) < 1e-3
              and abs(deck.pose_of(card).angle - pose_slot.angle) < 1e-3)
        half = QPointF(card.item.boundingRect().width() / 2.0,
                       card.item.boundingRect().height() / 2.0)
        check("proxy 跟随卡片位姿",
              proxies[card.item_id].pos()
              == card.item.mapToScene(QPointF(0, 0)) - half)
        check("交换后 proxy 仍与图元对齐", not proxy_misalignment(),
              str(proxy_misalignment()))
        check("交换后位图仍精确覆盖图元", not snapshot_misalignment(),
              str(snapshot_misalignment()))
        check("交换后每张卡的实际绘制位姿 = deck 期望位姿（斜卡不偏心）",
              not drawn_pose_drift(), str(drawn_pose_drift()))
        check("front_page_changed 已更新", win.front_pages()[0] == card.get_name(),
              str(win.front_pages()))

    print("\n=== 5. 收拢 / 展开 / 重置 ===")
    deck._duration_ms = 30
    deck.FOLD_DURATION_MS = 30
    check("收拢成功", deck.fold(), "")
    check("收拢动画结束", wait_finished(deck))
    check("已处于收拢态", deck.is_folded())
    check("立即展开成功", deck.unfold(immediate=True) and not deck.is_folded())
    win._reset_layout()
    check("重置布局回到初始槽位", deck.slot_card().get_name() == "Page0",
          deck.slot_card().get_name())

    print("\n=== 5.5 连点多次交换的位姿不变量 ===")

    def pose_multiset():
        return sorted((round(c.get_scene_center_pos().x(), 3),
                       round(c.get_scene_center_pos().y(), 3),
                       round(c.get_angle(), 3)) for c in cards)

    base_poses = pose_multiset()
    drift = []
    for index in range(6):
        stack = deck.stack_cards()
        target = stack[index % len(stack)] if stack else None
        if target is None or not deck.swap_with_slot(target):
            drift.append((index, "swap refused"))
            break
        if not wait_finished(deck):
            drift.append((index, "timeout"))
            break
        if pose_multiset() != base_poses:
            drift.append((index, f"{target.get_name()} 位姿漂移"))
            break
        if proxy_misalignment():
            drift.append((index, "proxy 未对齐"))
            break
    check("连点 6 次交换后位姿集合恒定且 proxy 全程对齐", not drift, str(drift))

    print("\n=== 5.4 逐张斜卡交换：绘制位姿必须落回扇形 ===")
    tilted = [c for c in cards if abs(c.get_angle()) > 1.0]
    check("存在起始带角度的卡（斜卡场景）", bool(tilted),
          ",".join(c.get_name() for c in tilted))
    tilt_bad = []
    for target in tilted:
        if target is deck.slot_card() or not deck.swap_with_slot(target):
            tilt_bad.append((target.get_name(), "swap refused"))
            break
        if not wait_finished(deck):
            tilt_bad.append((target.get_name(), "timeout"))
            break
        wait(80)
        bad = drawn_pose_drift()
        if bad:
            tilt_bad.append((target.get_name(), bad))
            break
    check("每张斜卡交换后都落在正确位姿（不再飞走）", not tilt_bad, str(tilt_bad))

    print("\n=== 5.6 动画起手开销（位图应复用，不得重复重烘）===")
    rebuilds = {"n": 0}
    _orig_rebuild = layer._rebuild_snapshot

    def _counting_rebuild(card):
        rebuilds["n"] += 1
        return _orig_rebuild(card)

    layer._rebuild_snapshot = _counting_rebuild
    startups = []
    try:
        for _ in range(3):
            stack = deck.stack_cards()
            if not stack:
                break
            rebuilds["n"] = 0
            t0 = time.perf_counter()
            started = deck.swap_with_slot(stack[0])
            startups.append((time.perf_counter() - t0) * 1000.0)
            if not (started and wait_finished(deck)):
                break
    finally:
        layer._rebuild_snapshot = _orig_rebuild
    check("动画起手不重新烘位图（复用常驻快照）", rebuilds["n"] == 0,
          f"{rebuilds['n']} 次")
    check("动画起手 <10ms", bool(startups) and max(startups) < 10.0,
          f"max {max(startups):.1f}ms" if startups else "未测到")

    print("\n=== 5.7 静态位图内容 / 分辨率（空闲刷新）===")
    wait(1200)                      # 让分片空闲刷新把 7 张都补完

    def snapshot_palette(snapshot) -> int:
        """采样位图上的不同颜色数：空白抓图（启动时控件还没首绘）只有 1 种。"""
        image = snapshot.pixmap().toImage()
        if image.isNull():
            return 0
        return len({image.pixel(x, y)
                    for x in range(0, image.width(), 37)
                    for y in range(0, image.height(), 47)})

    blanks = []
    for c in cards:
        snap = layer._snapshots.get(c.item_id)
        if snap is None or snapshot_palette(snap) <= 1:
            blanks.append(c.get_name())
    check("7 张常驻位图都有真实画面（不是空白抓图）", not blanks, str(blanks))

    try:
        scale = (float(view.transform().m11() or 0.0)
                 * float(view.devicePixelRatioF() or 1.0))
    except (AttributeError, RuntimeError):
        scale = float(view.transform().m11() or 0.0)
    off = []
    for c in cards:
        snap = layer._snapshots.get(c.item_id)
        if snap is None:
            off.append((c.get_name(), "no snapshot"))
            continue
        pixmap = snap.pixmap()
        logical_w = pixmap.width() / float(pixmap.devicePixelRatio() or 1.0)
        expected = logical_w * scale
        if expected > 1.0 and abs(pixmap.width() - expected) / expected > 0.15:
            off.append((c.get_name(), pixmap.width(), round(expected)))
    check("位图按显示分辨率烘（1:1 贴图，不逐帧降采样）", not off, str(off))
    check("空闲刷新队列已排空", not layer._dirty, str(len(layer._dirty)))

    print("\n=== 6. 关窗回收 ===")
    win.close()
    wait(120)
    check("proxy 全部回收", not layer.proxies(), str(len(layer.proxies())))
    ghosts = [type(w).__name__ for w in QApplication.topLevelWidgets()
              if isinstance(w, HmiPage) and w.isVisible()]
    check("关窗无幽灵 HmiPage 顶层窗口", not ghosts, str(ghosts))
    check("页面文件仍零改动",
          open(PAGE, "rb").read() == before_page
          and open(SCENE, "rb").read() == before_scene)

    print(f"\n=== 结果：{_PASSED}/{_PASSED + _FAILED} passed，失败 {_FAILED} 项 ===")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
