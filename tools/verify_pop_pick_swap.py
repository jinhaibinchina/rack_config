"""PopPick 页面互换回归测试。

覆盖：场景加载与卡片识别、槽位判定、Z 值落地、命中测试（含旋转卡片）、
真实鼠标点击链路、交换后的位姿/Z 互换、动画中间帧、重复点击保护、重置布局。

跑法::

    .venv/Scripts/python.exe tools/verify_pop_pick_swap.py
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QToolBar

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
    """空转事件循环 ``ms`` 毫秒（动画/重绘都要靠它推进）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait_finished(deck, timeout_ms: int = 3000) -> bool:
    loop = QEventLoop()
    done = {"ok": False}

    def _on_finished(*_args):
        done["ok"] = True
        loop.quit()

    deck.swap_finished.connect(_on_finished)
    QTimer.singleShot(timeout_ms, loop.quit)
    # 交还控制权，等动画自己跑完
    loop.exec()
    deck.swap_finished.disconnect(_on_finished)
    return done["ok"]


def _rect_equal(a: QPointF, b: QPointF, tol: float = 0.5) -> bool:
    return abs(a.x() - b.x()) <= tol and abs(a.y() - b.y()) <= tol


def _pose_equal(a, b, tol: float = 0.5, angle_tol: float = 0.05) -> bool:
    return _rect_equal(a.center, b.center, tol) and abs(a.angle - b.angle) <= angle_tol


def _hit_point(deck, card):
    """在卡片包围盒里找只命中它自己的点（扇形叠放时中心可能压着别的卡）。"""
    rect = card.sceneBoundingRect()
    # 采样网格要够密：卡片包围盒里可能含着伸出卡面的子图元（控件承载视图
    # 按旋转后的包围盒算），真正属于这张卡的像素未必落在 0.1~0.5 那一块。
    for fx in (f / 20 for f in range(1, 20)):
        for fy in (f / 20 for f in range(1, 20)):
            point = QPointF(
                rect.left() + rect.width() * fx, rect.top() + rect.height() * fy
            )
            if deck.card_at(point) is card:
                return point
    return None


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])

    from App_PopPick import PopPickWindow
    from App_PopPick.pop_pick_entry import resolve_page_file

    page_file = resolve_page_file("page_9")
    check("页面文件可解析", os.path.isfile(page_file), page_file)

    win = PopPickWindow(enable_plc=False)
    win.resize(1280, 820)
    win.show()
    for _ in range(6):
        app.processEvents()

    scene, deck, manager = win.scene, win.deck, win.scene_manager
    check("窗口创建了页面堆叠", deck is not None)

    # ---- 1. 卡片识别 ----
    names = [card.get_name() for card in deck.cards()]
    check("识别出 6 张卡片", len(names) == 6, ",".join(names))

    slot = deck.slot_card()
    check("槽位卡是最右侧那张", slot.get_name() == "Page0", slot.get_name())

    stack = deck.stack_cards()
    # 名字不写死：页面文件随时会被改（加/删/改名图元），这里校的是不变量——
    # 堆叠里的卡按 Z 从高到低排列，且正好是"除槽位卡以外的全部卡片"。
    expected_stack = [
        card.get_name()
        for card in sorted(
            (card for card in deck.cards() if card is not slot),
            key=lambda card: -card.zValue(),
        )
    ]
    check(
        "堆叠 5 张且按 Z 从上到下",
        len(stack) == 5 and [c.get_name() for c in stack] == expected_stack,
        ",".join(c.get_name() for c in stack),
    )

    z_values = sorted(card.zValue() for card in deck.cards())
    # 起点不写死：设计器里删过图元之后 Z 计数不回退，页面文件里的底数
    # 会变成 14、15…；真正的不变量是这 6 张卡的 Z 连续且互不相同。
    check(
        "Z 值落地为连续整数",
        z_values == list(range(z_values[0], z_values[0] + len(z_values))),
        str(z_values),
    )

    # ---- 2. 命中测试 ----
    bottom_card = stack[-1]  # 堆叠最底层那张（扇形里露在最外/最下）
    hit = _hit_point(deck, bottom_card)
    check("扇形最外层卡片有可点击区域", hit is not None)
    check("命中测试返回最上层卡片", hit is not None and deck.card_at(hit) is bottom_card)
    check("空白处不返回卡片", deck.card_at(QPointF(-100000, -100000)) is None)

    # 旋转卡片的包围盒内、但落在卡片外的点必须判不中（否则会误触发）
    corner = bottom_card.sceneBoundingRect().topLeft() + QPointF(3, 3)
    check("包围盒空角不命中旋转卡片", deck.card_at(corner) is not bottom_card)

    # ---- 3. 控件鼠标穿透 ----
    layer = bottom_card._layer
    check(
        "卡片控件对鼠标透明（点击能落到场景）",
        layer is not None
        and layer.view is not None
        and layer.view.testAttribute(Qt.WA_TransparentForMouseEvents),
    )

    # ---- 4. 真实鼠标点击链路 ----
    start_poses = {card: deck.pose_of(card) for card in deck.cards()}
    start_z = {card: card.zValue() for card in deck.cards()}

    click_pos = scene.pos_viewToWindow(scene.sceneToView(hit))
    QTest.mouseClick(scene, Qt.LeftButton, Qt.NoModifier, click_pos.toPoint())
    check("鼠标点击后进入动画", deck.is_busy())

    # 动画进行中再点一下：必须被忽略
    before_repeat = deck.pose_of(bottom_card)
    QTest.mouseClick(scene, Qt.LeftButton, Qt.NoModifier, click_pos.toPoint())
    check("动画期间的点击被忽略", deck.is_busy(), "仍是同一次动画")

    # 中间帧：位姿要真的在变，不能是瞬移
    _wait(150)
    mid_pose = deck.pose_of(bottom_card)
    check(
        "动画有中间帧（位姿在起点与终点之间）",
        not _pose_equal(mid_pose, start_poses[bottom_card])
        and not _pose_equal(mid_pose, start_poses[slot]),
        f"mid={mid_pose}",
    )

    check("交换在超时前结束", _wait_finished(deck))

    # ---- 5. 位姿与 Z 互换 ----
    check("原来点中的卡进入槽位", deck.slot_card() is bottom_card)
    check(
        "进场卡位姿 = 原槽位卡位姿",
        _pose_equal(deck.pose_of(bottom_card), start_poses[slot]),
        f"{deck.pose_of(bottom_card)}",
    )
    check(
        "退场卡位姿 = 原堆叠卡位姿",
        _pose_equal(deck.pose_of(slot), start_poses[bottom_card]),
        f"{deck.pose_of(slot)}",
    )
    check("Z 值已互换（进场卡拿到槽位 Z）", bottom_card.zValue() == start_z[slot],
          f"{bottom_card.zValue()} vs {start_z[slot]}")
    check("Z 值已互换（退场卡拿到堆叠 Z）", slot.zValue() == start_z[bottom_card],
          f"{slot.zValue()} vs {start_z[bottom_card]}")
    check(
        "其它卡片纹丝不动",
        all(
            _pose_equal(deck.pose_of(card), start_poses[card])
            for card in deck.cards()
            if card not in (bottom_card, slot)
        ),
    )

    # ---- 6. 换回来 ----
    back_hit = _hit_point(deck, slot)
    check("退场卡在扇形里有可点击区域", back_hit is not None)
    if back_hit is not None:
        check("再次交换成功启动", deck.swap_with_slot(slot))
        check("第二次交换完成", _wait_finished(deck))
        check("交换回来后槽位仍是 Page0", deck.slot_card().get_name() == "Page0",
              deck.slot_card().get_name())
        check(
            "交换来回后位姿与初始一致",
            all(_pose_equal(deck.pose_of(card), start_poses[card]) for card in deck.cards()),
        )
        check(
            "交换来回后 Z 与初始一致",
            all(card.zValue() == start_z[card] for card in deck.cards()),
        )

    # ---- 7. 重置布局 ----
    deck.swap_with_slot(bottom_card)
    _wait_finished(deck)
    deck.reset()
    _wait(60)
    check(
        "重置恢复初始位姿",
        all(_pose_equal(deck.pose_of(card), start_poses[card]) for card in deck.cards()),
    )
    check("重置恢复初始 Z", all(card.zValue() == start_z[card] for card in deck.cards()))
    check("重置后槽位仍判定正确", deck.slot_card().get_name() == "Page0")

    # ---- 8. 适应窗口：卡片实体必须跟着视图重排 ----
    win._fit_view()
    _wait(40)
    mismatch = []
    for card in deck.cards():
        expect = scene.pos_viewToWindow(scene.sceneToView(card.get_scene_center_pos()))
        got = card._layer._center
        if abs(expect.x() - got.x()) > 1.0 or abs(expect.y() - got.y()) > 1.0:
            mismatch.append(card.get_name())
    check(
        "适应窗口后承载控件几何同步",
        not mismatch,
        f"错位={','.join(mismatch)}",
    )

    # ---- 8b. 最大窗口：把当前展示的两页撑满 ----
    #
    # 这里的「两页」是右侧槽位上的当前页 + 左侧堆叠最上面那一页，不是
    # Z 前两名——扇形里 Z 最高的两张互相盖住，取它们只会有**一张**撑满，
    # 右侧当前页反而被裁掉。这条断言同时锁住「两张都在视口内」。
    def _window_rect(card) -> QRectF:
        bound = card.sceneBoundingRect()
        top_left = scene.sceneToView(bound.topLeft())
        bottom_right = scene.sceneToView(bound.bottomRight())
        view_rect = QRectF(top_left, bottom_right).normalized()
        scale = scene.scale_factor
        return QRectF(
            view_rect.x() * scale + scene.offset.x(),
            view_rect.y() * scale + scene.offset.y(),
            view_rect.width() * scale,
            view_rect.height() * scale,
        )

    toolbar_texts = [
        action.text()
        for bar in win.findChildren(QToolBar)
        for action in bar.actions()
    ]
    check(
        "工具栏有最大窗口按钮",
        "最大窗口" in toolbar_texts,
        "、".join(toolbar_texts),
    )

    front = [deck.slot_card(), deck.stack_cards()[0]]
    scale_before = scene.scale_factor
    win._maximize_view()
    _wait(80)
    check(
        "最大窗口放大了视图",
        scene.scale_factor > scale_before,
        f"{scale_before:.3f} → {scene.scale_factor:.3f}",
    )

    union = QRectF()
    for card in front:
        rect = _window_rect(card)
        union = rect if union.isNull() else union.united(rect)
    viewport = QRectF(0.0, 0.0, float(scene.width()), float(scene.height()))
    check(
        "两页都完整落在窗口内",
        viewport.adjusted(-1, -1, 1, 1).contains(union),
        f"两页包围盒 ({union.x():.0f},{union.y():.0f}) "
        f"{union.width():.0f}x{union.height():.0f}，"
        f"视口 {scene.width()}x{scene.height()}",
    )
    fill = max(union.width() / scene.width(), union.height() / scene.height())
    check(
        "两页撑满窗口（主方向 ≥ 90%）",
        fill >= 0.90,
        f"填充 {fill * 100:.0f}%",
    )

    # 最大视图下左侧最上层被锁定：这是"专注看"的状态，不能顺手一点就跑掉。
    # 锁定认的是"当前堆叠最上层"这张卡，不是某张固定名字的卡。
    locked = deck.stack_cards()[0]
    slot_card = deck.slot_card()
    slot_before = slot_card.get_name()

    # 锁定的代价是"不能交换"，不是"整页都死"：画面上正对着看的两页（右侧
    # 当前页 + 左侧最上层）交互必须重新打开，否则页内按钮点不动（同一块像素
    # 上"点击=交换"与"按钮可点"互斥，最大视图正好把冲突解掉）。
    check(
        "最大视图下左侧最上层恢复可交互",
        locked.widget_readonly() is False,
        f"readonly={locked.widget_readonly()}",
    )
    check(
        "最大视图下右侧当前页也恢复可交互",
        slot_card.widget_readonly() is False,
        f"readonly={slot_card.widget_readonly()}",
    )
    check(
        "最大视图下只放开这两页，其余仍只读",
        all(
            card.widget_readonly()
            for card in deck.cards()
            if card is not locked and card is not slot_card
        ),
        "仍可交互："
        + "、".join(
            card.get_name() for card in deck.cards() if not card.widget_readonly()
        ),
    )
    check(
        "锁定页的承载视图不再鼠标穿透",
        not locked._layer.view.testAttribute(Qt.WA_TransparentForMouseEvents),
    )

    def _click_probe_button(card, hits: list) -> None:
        """在卡片里塞一个按钮并真的点一下（能点要用点击验证，不看标志位）。"""
        target = card._layer
        button = QPushButton("联锁复位", target.widget)
        button.setGeometry(6, 6, 90, 32)
        button.show()
        button.clicked.connect(lambda: hits.append(1))
        _wait(80)
        pos = target.view.viewport().mapFromGlobal(
            button.mapToGlobal(button.rect().center())
        )
        QTest.mouseClick(target.view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
        _wait(120)
        button.deleteLater()

    left_hits: list[int] = []
    _click_probe_button(locked, left_hits)
    check("锁定页内按钮收到点击", len(left_hits) == 1, f"clicked={len(left_hits)}")
    check(
        "点锁定页内按钮不会触发交换",
        not deck.is_busy() and deck.slot_card().get_name() == slot_before,
        f"槽位 {slot_before} → {deck.slot_card().get_name()}",
    )

    right_hits: list[int] = []
    _click_probe_button(slot_card, right_hits)
    check("右侧当前页内按钮收到点击", len(right_hits) == 1, f"clicked={len(right_hits)}")
    check(
        "点右侧当前页内按钮不会触发交换",
        not deck.is_busy() and deck.slot_card().get_name() == slot_before,
        f"槽位 {slot_before} → {deck.slot_card().get_name()}",
    )

    locked_point = scene.pos_viewToWindow(
        scene.sceneToView(locked.get_scene_center_pos())
    )
    QTest.mouseClick(
        scene,
        Qt.LeftButton,
        Qt.NoModifier,
        QPoint(int(locked_point.x()), int(locked_point.y())),
    )
    _wait(120)
    check(
        "最大视图下点最上层不触发交换",
        not deck.is_busy() and deck.slot_card().get_name() == slot_before,
        f"槽位 {slot_before} → {deck.slot_card().get_name()}",
    )
    check("锁定状态在最大视图内保持", win._maximized)

    # 退出最大视图 → 同一张卡恢复可交换，交互也交还给场景
    win._fit_view()
    _wait(80)
    check("适应窗口解除锁定", not win._maximized)
    check(
        "解除锁定后全卡恢复只读",
        all(card.widget_readonly() for card in deck.cards()),
        "仍可交互："
        + "、".join(card.get_name() for card in deck.cards() if not card.widget_readonly()),
    )
    check(
        "解除锁定后承载视图恢复鼠标穿透",
        locked._layer.view.testAttribute(Qt.WA_TransparentForMouseEvents),
    )
    unlocked_point = scene.pos_viewToWindow(
        scene.sceneToView(locked.get_scene_center_pos())
    )
    QTest.mouseClick(
        scene,
        Qt.LeftButton,
        Qt.NoModifier,
        QPoint(int(unlocked_point.x()), int(unlocked_point.y())),
    )
    _wait(120)
    while deck.is_busy():
        _wait(20)
    check(
        "解除锁定后同一张卡可以交换",
        deck.slot_card().get_name() != slot_before,
        f"槽位 {slot_before} → {deck.slot_card().get_name()}",
    )
    deck.reset()
    _wait(80)
    win._fit_view()
    _wait(80)

    # ---- 9. 动画期间快速渲染：位图快照 + 占位框只描边 ----
    #
    # 放大后卡顿的根因是"每帧把真实控件从头渲染一遍"，且父窗口一脏，所有承载
    # 视图都会被重画（含没动的卡）。这里锁住四件事：动画期间全开、动画结束全关、
    # 动画期间控件几乎不再重绘、以及**画面不能失真**。
    from PySide6.QtCore import QObject
    from PySide6.QtCore import QEvent

    def _render_state():
        return [
            (
                card.is_motion_cache(),
                card.is_widget_fast_paint(),
                getattr(card._layer, "_snapshot", None) is not None
                if card._layer is not None
                else False,
                card._layer.proxy.isVisible()
                if card._layer is not None and card._layer.proxy is not None
                else False,
            )
            for card in deck.cards()
        ]

    idle_state = _render_state()
    check(
        "静止时不启用快速渲染",
        all(not cache and not skip and snapshot is False and shown
            for cache, skip, snapshot, shown in idle_state),
    )

    # 关键回归：快速渲染前后**画面必须基本一致**。
    #
    # 早期版本用 setCacheMode(ItemCoordinateCache, QSize(w*r, h*r)) 提分辨率，
    # 结果 Qt 把控件按这个逻辑尺寸放大后再贴回来：文字撑出卡片、白底和边框错位、
    # 边角被裁成台阶。同一帧数字笔画数 28→12（放大 2.3 倍），截图一眼就看得出。
    # 现在改为自己烘快照，差异只剩边缘抗锯齿：离屏 1.45%、真实字体 0.73%，
    # 而上面那个失真版本在同口径下是 9.36%。阈值取 3% 两边都留足余量。
    fast_paint_before = [card.is_widget_fast_paint() for card in deck.cards()]
    scene.update()
    _wait(120)
    normal_shot = win.grab().toImage().convertToFormat(QImage.Format_RGB32)
    for card in deck.cards():
        card.set_widget_fast_paint(True)
        card.set_motion_cache(True)
    scene.update()
    _wait(200)
    fast_shot = win.grab().toImage().convertToFormat(QImage.Format_RGB32)
    for card, flag in zip(deck.cards(), fast_paint_before):
        card.set_motion_cache(False)
        card.set_widget_fast_paint(flag)
    scene.update()
    _wait(120)

    total = normal_shot.width() * normal_shot.height()
    strong = 0
    if normal_shot.size() == fast_shot.size() and total > 0:
        for y in range(0, normal_shot.height(), 2):
            for x in range(0, normal_shot.width(), 2):
                pa = normal_shot.pixel(x, y)
                pb = fast_shot.pixel(x, y)
                if pa == pb:
                    continue
                if any(abs(((pa >> sh) & 255) - ((pb >> sh) & 255)) > 32
                       for sh in (0, 8, 16)):
                    strong += 1
    sampled = ((normal_shot.width() + 1) // 2) * ((normal_shot.height() + 1) // 2)
    ratio = strong * 100.0 / sampled if sampled else 100.0
    check(
        "快速渲染前后画面不失真（差异仅抗锯齿边缘）",
        ratio < 3.0,
        f"差异 {ratio:.2f}%（阈值 3%）",
    )

    class _PaintCounter(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.count = 0

        def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
            if event.type() == QEvent.Paint:
                self.count += 1
            return False

    counter = _PaintCounter()
    probe = bottom_card._layer.widget
    probe.installEventFilter(counter)

    deck.swap_with_slot(bottom_card)
    busy_state = _render_state()
    check(
        "动画期间所有卡片改用位图快照",
        all(cache and snapshot and not shown
            for cache, _s, snapshot, shown in busy_state),
    )
    check(
        "动画期间占位框只描边不填底",
        all(skip for _c, skip, _s, _v in busy_state),
    )

    # 快照必须按"场景缩放 × DPR"烘，且不超过上限——分辨率不足会糊，超过是浪费
    shot_ok = []
    for card in deck.cards():
        layer = card._layer
        pixmap = layer._snapshot.pixmap() if layer._snapshot is not None else None
        if pixmap is None:
            shot_ok.append(False)
            continue
        design = layer._design
        expect_w = design.width() * layer._snapshot_ratio
        expect_h = design.height() * layer._snapshot_ratio
        shot_ok.append(
            abs(pixmap.width() - expect_w) <= 2.0
            and abs(pixmap.height() - expect_h) <= 2.0
            and 1.0 <= layer._snapshot_ratio <= layer.MOTION_SNAPSHOT_MAX_RATIO + 1e-6
        )
    check("动画快照像素倍率正确（不被拉伸）", all(shot_ok))

    counter.count = 0
    check("动画结束", _wait_finished(deck))
    paints = counter.count
    probe.removeEventFilter(counter)
    check(
        "动画期间控件几乎不重绘（快照生效）",
        paints <= 4,
        f"{paints} 次",
    )

    done_state = _render_state()
    check(
        "动画结束后恢复矢量渲染",
        all(not cache and not skip and snapshot is False and shown
            for cache, skip, snapshot, shown in done_state),
    )

    # 中断（关窗口/切页）也要把快速渲染关掉，否则画面会一直停在发虚的那版
    deck.swap_with_slot(deck.stack_cards()[0])
    _wait(60)
    deck.stop()
    _wait(30)
    check(
        "中断动画后同样恢复矢量渲染",
        all(not cache and not skip and not snapshot
            for cache, skip, snapshot, _v in _render_state()),
    )
    deck.reset()
    _wait(60)

    # ---- 11. 双击空白处收起 / 展开左侧页面 ----
    #
    # 收起形态锁三件事：角度归零、叠成一摞（中心重合）、整摞右边缘贴在
    # 视口左边只露出把手宽度。展开必须回到**收拢前那一刻**的位姿（交换过之后
    # 谁在哪儿已经变了，用设计初始位姿展开会把卡弹到别人的位置）。
    deck.reset()
    _wait(80)
    win._fit_view()
    _wait(80)

    def _blank_point(inset: float = 0.03) -> QPointF:
        """找一个确实落在卡片之外的窗口坐标（双击背景用）。

        放大/最大视图下卡片会占掉大半屏，固定几个候选点很容易全部命中卡片；
        这里扫一张粗网格，从四周往里收（边角最可能是空白）。
        """
        best = None
        steps = 25
        for fy in range(steps):
            for fx in range(steps):
                fx_ratio = inset + (1.0 - 2 * inset) * fx / (steps - 1)
                fy_ratio = inset + (1.0 - 2 * inset) * fy / (steps - 1)
                point = QPointF(scene.width() * fx_ratio, scene.height() * fy_ratio)
                if deck.card_at(win._window_to_scene(point)) is not None:
                    continue
                # 取离中心最远的那个空白点：最不可能被卡片"顺手"延伸到
                distance = abs(fx_ratio - 0.5) + abs(fy_ratio - 0.5)
                if best is None or distance > best[0]:
                    best = (distance, point)
        return best[1] if best is not None else None

    def _dblclick(point: QPointF) -> None:
        QTest.mouseDClick(
            scene, Qt.LeftButton, Qt.NoModifier,
            QPoint(int(point.x()), int(point.y())),
        )

    def _stack_spread() -> float:
        """一摞卡之间最大的中心距离（0 = 完全重合）。"""
        centers = [deck.pose_of(card).center for card in deck.stack_cards()]
        return max(
            (
                (a - b).manhattanLength()
                for a in centers
                for b in centers
            ),
            default=0.0,
        )

    blank = _blank_point()
    check("找到可双击的空白区域", blank is not None, f"{blank}")
    if blank is None:
        return _report()

    before_fold = {card: deck.pose_of(card) for card in deck.cards()}
    slot_before_fold = deck.slot_card()

    _dblclick(blank)
    check("双击空白处进入收拢动画", deck.is_busy() and deck.is_folded())

    stack_now = deck.stack_cards()
    # 用扇形最外层那张（角度 32°）验中间帧：最上层那张本来就是 0°，
    # 拿它验角度看不出动画在跑。
    first = stack_now[-1]
    _wait(120)
    mid_pose = deck.pose_of(first)
    check(
        "收拢动画有中间帧（不是瞬移）",
        not _pose_equal(mid_pose, before_fold[first])
        and abs(mid_pose.angle) > 0.5,
        f"{before_fold[first]} → mid={mid_pose}",
    )
    while deck.is_busy():
        _wait(20)
    _wait(40)

    folded = [deck.pose_of(card) for card in stack_now]
    check("收拢后所有堆叠卡角度归零", all(abs(p.angle) < 0.05 for p in folded),
          "、".join(f"{p.angle:.2f}" for p in folded))
    check(
        "收拢后叠成一摞（中心重合）",
        all(_rect_equal(p.center, folded[0].center, 1.0) for p in folded),
    )
    # 最前面那张是这摞的"封面"，收拢时它必须原地不动——它要是一起跑掉，
    # 用户就看不到自己刚收起来的那一摞了。
    check(
        "收拢时最前面那张原地不动",
        _pose_equal(folded[0], before_fold[stack_now[0]]),
        f"{before_fold[stack_now[0]]} → {folded[0]}",
    )
    check(
        "收拢时右侧当前页纹丝不动",
        _pose_equal(deck.pose_of(slot_before_fold), before_fold[slot_before_fold]),
        f"{deck.pose_of(slot_before_fold)}",
    )
    check("收拢状态下禁止交换", not deck.swap_with_slot(stack_now[0]))

    # 收起后画面上只剩两页：左侧封面 + 右侧当前页。它们已经不会再被一次
    # 点击点走，交互因此必须放开——否则收起状态下页内按钮全都点不动。
    front_card = stack_now[0]
    slot_card_now = deck.slot_card()
    check(
        "收拢后左侧封面恢复可交互",
        front_card.widget_readonly() is False,
        f"readonly={front_card.widget_readonly()}",
    )
    check(
        "收拢后右侧当前页恢复可交互",
        slot_card_now.widget_readonly() is False,
        f"readonly={slot_card_now.widget_readonly()}",
    )
    check(
        "收拢后其余卡片仍只读",
        all(
            card.widget_readonly()
            for card in deck.cards()
            if card is not front_card and card is not slot_card_now
        ),
    )
    check(
        "收拢后封面承载视图不再鼠标穿透",
        not front_card._layer.view.testAttribute(Qt.WA_TransparentForMouseEvents),
    )
    check(
        "收拢后当前页承载视图不再鼠标穿透",
        not slot_card_now._layer.view.testAttribute(Qt.WA_TransparentForMouseEvents),
    )

    # "能点"要用真点击验证，光看标志位不算
    def _click_widget_button(card, text: str) -> int:
        layer = card._layer
        probe = QPushButton(text, layer.widget)
        probe.setGeometry(6, 6, 96, 32)
        probe.show()
        hits: list[int] = []
        probe.clicked.connect(lambda: hits.append(1))
        _wait(60)
        center = layer.view.viewport().mapFromGlobal(
            probe.mapToGlobal(probe.rect().center())
        )
        QTest.mouseClick(
            layer.view.viewport(), Qt.LeftButton, Qt.NoModifier, center
        )
        _wait(80)
        probe.deleteLater()
        return len(hits)

    slot_name_before_click = deck.slot_card().get_name()
    hits_front = _click_widget_button(front_card, "封面按钮")
    check("收拢后封面内按钮收到点击", hits_front == 1, f"clicked={hits_front}")
    check(
        "点封面内按钮不会触发交换",
        not deck.is_busy() and deck.slot_card().get_name() == slot_name_before_click,
        f"槽位 {slot_name_before_click} → {deck.slot_card().get_name()}",
    )
    hits_slot = _click_widget_button(slot_card_now, "当前页按钮")
    check("收拢后当前页内按钮收到点击", hits_slot == 1, f"clicked={hits_slot}")
    check(
        "点当前页内按钮不会触发交换",
        not deck.is_busy() and deck.slot_card().get_name() == slot_name_before_click,
        f"槽位 {slot_name_before_click} → {deck.slot_card().get_name()}",
    )

    # 收拢状态下点左侧那一摞 → 只提示，不交换
    folded_point = scene.pos_viewToWindow(scene.sceneToView(folded[0].center))
    QTest.mouseClick(
        scene, Qt.LeftButton, Qt.NoModifier,
        QPoint(int(folded_point.x()), int(folded_point.y())),
    )
    _wait(80)
    check(
        "收拢状态下点左侧只提示不交换",
        not deck.is_busy() and "收起" in win.statusBar().currentMessage(),
        win.statusBar().currentMessage(),
    )

    # 收拢落点跟着最前面那张走，缩放/平移都不需要重算
    old_scale = scene.scale_factor
    scene.scale_factor = old_scale * 1.6
    scene.refresh_embedded_widgets()
    _wait(60)
    check(
        "缩放后这一摞仍保持重合",
        _stack_spread() <= 1.0,
        f"最大间距 {_stack_spread():.2f}",
    )
    scene.scale_factor = old_scale
    scene.refresh_embedded_widgets()
    _wait(60)

    # 再次双击 → 展开，回到收拢前的位姿
    _dblclick(blank)
    check("再次双击进入展开动画", deck.is_busy() and not deck.is_folded())
    while deck.is_busy():
        _wait(20)
    _wait(40)
    check(
        "展开后位姿回到收拢前",
        all(_pose_equal(deck.pose_of(card), before_fold[card]) for card in stack_now),
        "、".join(f"{card.get_name()}={deck.pose_of(card)}" for card in stack_now[:2]),
    )
    check(
        "展开后卡片恢复只读",
        all(card.widget_readonly() for card in deck.cards()),
        "仍可交互：" + "、".join(
            card.get_name() for card in deck.cards() if not card.widget_readonly()
        ),
    )

    # 收起状态下取景（适应窗口）先展开再取景，否则收拢错位的卡会把缩放拉爆
    _dblclick(blank)
    while deck.is_busy():
        _wait(20)
    check("重新收起成功", deck.is_folded())

    # 收起状态双击左侧封面 / 右侧当前页都**不**展开：这两页现在可交互，
    # 双击落在页内控件上属于正常操作（选词、按钮连点），顺手把整摞展开
    # 等于在用户操作页面时抢走画面。只有空白背景才是收起/展开的开关。
    front_point = scene.pos_viewToWindow(
        scene.sceneToView(deck.pose_of(deck.stack_cards()[0]).center)
    )
    _dblclick(front_point)
    _wait(60)
    check(
        "折叠时双击左侧封面不会展开",
        deck.is_folded() and not deck.is_busy(),
        f"folded={deck.is_folded()} busy={deck.is_busy()}",
    )

    slot_point = scene.pos_viewToWindow(
        scene.sceneToView(deck.pose_of(deck.slot_card()).center)
    )
    _dblclick(slot_point)
    _wait(60)
    check(
        "折叠时双击右侧当前页不会展开",
        deck.is_folded() and not deck.is_busy(),
        f"folded={deck.is_folded()} busy={deck.is_busy()}",
    )

    _dblclick(blank)
    while deck.is_busy():
        _wait(20)
    _wait(40)
    check("折叠后仍可双击空白背景展开", not deck.is_folded())

    _dblclick(blank)
    while deck.is_busy():
        _wait(20)
    check("再次收起以便验证取景连动", deck.is_folded())

    win._fit_view()
    _wait(80)
    check("适应窗口会先展开收拢的页面", not deck.is_folded())

    # 收起动画同样走快速渲染（放大后不卡的前提），结束后必须关掉
    _dblclick(blank)
    busy_state = _render_state()
    check(
        "收拢动画期间启用快速渲染",
        all(cache and skip for cache, skip, _s, _v in busy_state),
    )
    while deck.is_busy():
        _wait(20)
    _wait(40)
    check(
        "收拢动画结束后恢复矢量渲染",
        all(not cache and not skip for cache, skip, _s, _v in _render_state()),
    )
    _dblclick(blank)
    while deck.is_busy():
        _wait(20)
    _wait(40)
    check("收拢状态可以回到展开", not deck.is_folded())

    # ---- 11.5 最大视图下收起/展开：锁定必须跨过折叠状态 ----
    #
    # 「最大窗口」是取景状态，收起/展开只是把左边那一摞挪一挪，取景没变。
    # 因此折叠不能顺手把锁定解掉：展开回来后仍是"专注看这两页"，左侧最上层
    # 照旧不可交换、页内控件照旧可操作。退出锁定只认「适应窗口」/滚轮缩放。
    deck.reset()
    _wait(80)
    win._maximize_view()
    _wait(140)
    check("重新进入最大视图", win._maximized)

    # 最大视图下卡片占满屏幕，原来的空白点多半被盖住了，重新找一个
    max_blank = _blank_point()
    check("最大视图下仍能找到空白背景", max_blank is not None, f"{max_blank}")
    if max_blank is None:
        return _report()

    max_front = deck.stack_cards()[0]
    max_slot = deck.slot_card()
    max_slot_name = max_slot.get_name()
    check("进入最大视图时最前页被锁定", win._is_locked_card(max_front))

    _dblclick(max_blank)
    while deck.is_busy():
        _wait(20)
    _wait(40)
    check("最大视图下双击空白背景可以收起", deck.is_folded())
    check("收起后仍是最大视图状态", win._maximized)
    check(
        "收起后最前页仍被锁定",
        win._is_locked_card(deck.stack_cards()[0]),
        f"locked={win._is_locked_card(deck.stack_cards()[0])}",
    )
    check(
        "收起后最前页仍可交互",
        deck.stack_cards()[0].widget_readonly() is False,
        f"readonly={deck.stack_cards()[0].widget_readonly()}",
    )

    _dblclick(max_blank)
    while deck.is_busy():
        _wait(20)
    _wait(40)
    check("展开后仍停在最大视图", win._maximized and not deck.is_folded())
    check(
        "展开后最前页仍不可交换",
        win._is_locked_card(deck.stack_cards()[0]),
        f"locked={win._is_locked_card(deck.stack_cards()[0])}",
    )
    check(
        "展开后最前页仍可交互",
        max_front.widget_readonly() is False,
        f"readonly={max_front.widget_readonly()}",
    )
    check(
        "展开后当前页仍可交互",
        deck.slot_card().widget_readonly() is False,
        f"readonly={deck.slot_card().widget_readonly()}",
    )

    # 说"可交互"就要有真点击：按钮命中一次，且不触发交换
    fold_hits: list[int] = []
    _click_probe_button(max_front, fold_hits)
    check("展开后最前页内按钮收到点击", len(fold_hits) == 1, f"clicked={len(fold_hits)}")
    check(
        "点最前页内按钮不会触发交换",
        not deck.is_busy() and deck.slot_card().get_name() == max_slot_name,
        f"槽位 {max_slot_name} → {deck.slot_card().get_name()}",
    )

    # 场景级点击同样不能把它换走（事件没被控件吃掉时的兜底路径）
    front_point = scene.pos_viewToWindow(
        scene.sceneToView(max_front.get_scene_center_pos())
    )
    QTest.mouseClick(
        scene, Qt.LeftButton, Qt.NoModifier,
        QPoint(int(front_point.x()), int(front_point.y())),
    )
    _wait(120)
    check(
        "展开后点最前页不触发交换",
        not deck.is_busy() and deck.slot_card().get_name() == max_slot_name,
        f"槽位 {max_slot_name} → {deck.slot_card().get_name()}",
    )

    # 退出最大视图 → 锁定连同交互一起交还
    win._fit_view()
    _wait(80)
    check("适应窗口才解除锁定", not win._maximized)
    check(
        "解除锁定后全卡恢复只读",
        all(card.widget_readonly() for card in deck.cards()),
        "仍可交互："
        + "、".join(card.get_name() for card in deck.cards() if not card.widget_readonly()),
    )
    deck.reset()
    _wait(60)

    # ---- 11.6 窗口尺寸变化：最大视图要跟着重算，普通视图不许被拽进来 ----
    #
    # 最大视图的缩放/平移是按"当时的窗口尺寸"反算的，窗口一变那两页就缩在
    # 中间或溢出边界。规则：只在 _maximized 时重算，且合并连续 resize；
    # 普通视图（扇形全貌）一律不动。
    deck.reset()
    _wait(80)
    win._fit_view()
    _wait(80)
    check("第 11.6 节起点：普通视图", not win._maximized)

    scale_normal = scene.scale_factor
    win.resize(1180, 760)
    _wait(200)  # 超过 80ms 的合并窗口
    check("普通视图下改窗口尺寸不会进入最大视图", not win._maximized)
    check(
        "普通视图下改窗口尺寸不锁定任何卡",
        win._is_locked_card(deck.stack_cards()[0]) is False,
    )
    check(
        "普通视图下改窗口尺寸不改取景缩放",
        abs(scene.scale_factor - scale_normal) < 1e-6,
        f"{scale_normal:.4f} → {scene.scale_factor:.4f}",
    )

    win.resize(1280, 820)
    _wait(60)
    win._maximize_view()
    _wait(120)
    check("第 11.6 节：重新进入最大视图", win._maximized)
    max_scale = scene.scale_factor
    status_before_resize = win.statusBar().currentMessage()

    win.resize(1080, 700)
    timer = win._maximize_refit_timer
    check(
        "resize 后启动合并定时器（未立刻重算）",
        timer is not None and timer.isActive(),
        f"timer={timer}",
    )
    _wait(220)
    check(
        "窗口变小后按新尺寸重算取景",
        abs(scene.scale_factor - max_scale) > 1e-6,
        f"{max_scale:.4f} → {scene.scale_factor:.4f}",
    )
    check("重算后仍是最大视图", win._maximized)
    check(
        "重算不重复播报状态栏",
        win.statusBar().currentMessage() == status_before_resize,
        win.statusBar().currentMessage(),
    )
    resize_union = QRectF()
    for card in (deck.slot_card(), deck.stack_cards()[0]):
        rect = _window_rect(card)
        resize_union = rect if resize_union.isNull() else resize_union.united(rect)
    resize_viewport = QRectF(0.0, 0.0, float(scene.width()), float(scene.height()))
    resize_fill = max(
        resize_union.width() / scene.width(), resize_union.height() / scene.height()
    )
    check(
        "缩小窗口后两页仍完整落在窗口内",
        resize_viewport.adjusted(-1, -1, 1, 1).contains(resize_union),
        f"两页 ({resize_union.width():.0f}x{resize_union.height():.0f})，"
        f"视口 {scene.width()}x{scene.height()}",
    )
    check(
        "缩小窗口后两页仍撑满窗口（主方向 ≥ 90%）",
        resize_fill >= 0.90,
        f"填充 {resize_fill * 100:.0f}%",
    )
    check(
        "缩小窗口后最前页仍被锁定",
        win._is_locked_card(deck.stack_cards()[0]),
    )

    # 收起 + 最大视图同时成立时，重算取景不许把那摞卡摊开（重算只管缩放，
    # 折叠是用户自己的取景选择）
    if not deck.is_folded():
        deck.fold()
        while deck.is_busy():
            _wait(20)
    _wait(40)
    check("收起状态就位", deck.is_folded())
    win.resize(1240, 800)
    _wait(220)
    check("改窗口尺寸不会把收起的左侧页面展开", deck.is_folded())
    check("收起状态下改窗口尺寸仍是最大视图", win._maximized)
    check(
        "收起状态下改窗口尺寸仍锁定最前页",
        win._is_locked_card(deck.stack_cards()[0]),
    )

    deck.unfold(immediate=True)
    _wait(60)
    win._fit_view()
    _wait(80)
    # 让状态栏回到"已切换到…"，第 12 节要验的就是交换反馈
    deck.reset()
    _wait(60)
    deck.swap_with_slot(deck.stack_cards()[0])
    while deck.is_busy():
        _wait(20)

    # ---- 10. 状态栏 / 关闭 ----
    message = win.statusBar().currentMessage()
    check("状态栏有操作反馈", ("互换" in message) or ("已切换到" in message), message)
    win.close()
    _wait(50)
    check("窗口关闭后动画已停止", not deck.is_busy())

    return _report()


if __name__ == "__main__":
    raise SystemExit(run())
