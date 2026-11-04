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

from PySide6.QtCore import QEventLoop, QPointF, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

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
    for fx in (0.1, 0.2, 0.3, 0.4, 0.5):
        for fy in (0.2, 0.35, 0.5, 0.65, 0.8):
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
    check("堆叠 5 张且按 Z 从上到下", [c.get_name() for c in stack]
          == ["Page1", "Page3", "控件_11", "Page4", "Page5"],
          ",".join(c.get_name() for c in stack))

    z_values = sorted(card.zValue() for card in deck.cards())
    check("Z 值落地为连续整数", z_values == [1, 2, 3, 4, 5, 6], str(z_values))

    # ---- 2. 命中测试 ----
    bottom_card = manager.findItemByName("Page5")
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

    # ---- 10. 状态栏 / 关闭 ----
    message = win.statusBar().currentMessage()
    check("状态栏有操作反馈", ("互换" in message) or ("已切换到" in message), message)
    win.close()
    _wait(50)
    check("窗口关闭后动画已停止", not deck.is_busy())

    return _report()


if __name__ == "__main__":
    raise SystemExit(run())
