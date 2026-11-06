"""HMI 页面性能剖析 + 压测。

用法（项目 .venv）::

    .venv/Scripts/python.exe tools/profile_hmi.py                # 全量体检
    .venv/Scripts/python.exe tools/profile_hmi.py --idle         # 只测空闲重绘
    .venv/Scripts/python.exe tools/profile_hmi.py --stress new   # 改造后的推送节奏
    .venv/Scripts/python.exe tools/profile_hmi.py --stress old   # 还原改造前的路径

为什么 ``--stress`` 要单独跑一个进程：上一轮的绘制积压会算进下一轮的间隔里
（实测把「改造后」也测成 1.2s 的假尖峰），两个场景必须在干净进程里各测一次
才有可比性。

背景（实测结论）
----------------
* 页面控件被 ``QGraphicsProxyWidget`` 接管后，**改一个标签就要重画整页**，
  而且任意一页重绘会连带重画同一区域里所有承载视图。
* 改造前：7 个页面各挂一个 1s 页头时钟 + 每个点直刷控件。空闲时每秒触发
  7 次整页重绘，事件循环每秒只能跑 **2 轮**；10Hz 推送 3s 只能完成 6 次
  （间隔中位 480ms、最大 1.68s）。
* 改造后：只有一条定时器给槽位页走时钟，推送值先合流再统一灌控件/一次重绘，
  空闲重绘 0~1 次/秒，10Hz 推送间隔中位 ~106ms。
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, QTimer  # noqa: E402


class PaintCounter(QObject):
    """统计某个 widget 收到多少次 Paint（只计数，不改行为）。"""

    def __init__(self, widget) -> None:
        super().__init__()
        self.count = 0
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
        if event.type() == QEvent.Paint:
            self.count += 1
        return False


def pump(app, ms: float) -> None:
    end = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.0005)


def build_window(app):
    from App_PopPick.pop_pick_entry import PopPickWindow

    win = PopPickWindow(hmi_demo=True)
    win.resize(1280, 820)
    win.show()
    pump(app, 2500)                      # 让首帧级联绘制跑完再开始计数
    return win


def counters(win):
    from PySide6.QtWidgets import QGraphicsView

    views = list(win.scene.findChildren(QGraphicsView))
    return (PaintCounter(win.scene),
            {f"v{i}": PaintCounter(v.viewport()) for i, v in enumerate(views)})


def cmd_idle(app, win, seconds: float) -> None:
    scene, views = counters(win)
    scene.count = 0
    for c in views.values():
        c.count = 0
    pump(app, seconds * 1000)
    hot = {k: v.count for k, v in views.items() if v.count}
    print(f"空闲 {seconds:.1f}s：场景重绘 {scene.count} 次"
          f"（{scene.count/seconds:.1f}/s）｜承载视图 {hot or '无'}")
    print("  改造前同一指标：场景 7 次/s、每个视图 6 次/s（7 个页头时钟各滴答一次）")


def cmd_stress(app, win, mode: str, seconds: float) -> None:
    hmi = win._hmi
    keys = hmi.active_keys()
    pages = [p for pl in hmi._pages.values() for p in pl]
    active = set(hmi._active_page_ids)

    if mode == "old":
        # 还原改造前：后台页不用快照 + 每个页面自己跑页头时钟 + 逐点直刷控件
        hmi.static_background = False
        hmi.apply_static_pages()
        for page in pages:
            page.header.start_clock()
        pump(app, 500)

    state = {"i": 0}
    ticks: list[float] = []

    def tick() -> None:
        index = state["i"]
        state["i"] += 1
        for key in keys[index * 20:(index + 1) * 20]:
            if mode == "old":
                for page in pages:
                    if page.PAGE_ID in active:
                        page.on_tag(key, index % 100)
            else:
                hmi._on_tag(key, index % 100)
        ticks.append(time.perf_counter())

    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(tick)
    start = time.perf_counter()
    cpu0 = time.process_time()
    timer.start()
    while time.perf_counter() - start < seconds:
        app.processEvents()
        time.sleep(0.0005)
    timer.stop()
    cpu = time.process_time() - cpu0

    gaps = [(b - a) * 1000 for a, b in zip(ticks, ticks[1:])]
    expect = int(seconds * 10)
    print(f"推送节奏 10Hz×20点（{mode}）：完成 {len(ticks)}/{expect} 次"
          f"｜间隔 中位 {statistics.median(gaps):.0f}ms"
          f" 最大 {max(gaps):.0f}ms"
          f"｜超时(>150ms) {sum(1 for g in gaps if g > 150)} 次"
          f"｜CPU {cpu:.2f}s/{seconds:.0f}s（{100*cpu/seconds:.0f}%）")


def cmd_frames(app, win) -> None:
    frames: list[float] = []
    original = win.deck._on_progress

    def spy(value):
        frames.append(time.perf_counter())
        original(value)

    win.deck._on_progress = spy
    card = win.deck.stack_cards()[0]
    start = time.perf_counter()
    win.deck.swap_with_slot(card)
    while win.deck.is_busy() and time.perf_counter() - start < 5:
        app.processEvents()
    elapsed = time.perf_counter() - start
    gaps = [(b - a) * 1000 for a, b in zip(frames, frames[1:])]
    print(f"交换动画 {elapsed:.2f}s｜进度回调 {len(frames)} 次"
          f"｜帧间隔 中位 {statistics.median(gaps):.1f}ms"
          f" 最大 {max(gaps):.1f}ms")
    win.deck._on_progress = original


def cmd_costs(app, win) -> None:
    from PySide6.QtWidgets import QGraphicsView

    from App_PopPick.hmi.widgets import TagValue

    samples = []
    for _ in range(3):
        start = time.perf_counter()
        win.scene.grab()
        samples.append((time.perf_counter() - start) * 1000)
    print(f"整窗 grab 一帧：中位 {statistics.median(samples):.0f}ms"
          f"（离屏软件光栅，现场更快）")

    views = list(win.scene.findChildren(QGraphicsView))
    for shown, label in ((views, "7 页全可见"), (views[:2], "只留 2 页")):
        keep = set(id(v) for v in shown)
        for v in views:
            v.setVisible(id(v) in keep)
        pump(app, 300)
        samples = []
        for _ in range(3):
            start = time.perf_counter()
            win.scene.grab()
            samples.append((time.perf_counter() - start) * 1000)
        print(f"   {label}：{statistics.median(samples):.0f}ms")
    for v in views:
        v.setVisible(True)
    pump(app, 300)

    page = win._hmi._pages["main"][0]
    vals = page.body.content.findChildren(TagValue)[:20]
    if vals:
        rounds = 20
        start = time.perf_counter()
        for i in range(rounds):
            for w in vals:
                w.set_value(i)
        cost = (time.perf_counter() - start) * 1000
        print(f"   {rounds*len(vals)} 次 set_value：{cost:.1f}ms"
              f"（{len(vals)} 个控件，含样式表去重）")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--idle", action="store_true", help="只测空闲重绘")
    ap.add_argument("--stress", choices=("old", "new"), help="推送压测（old=改造前路径）")
    ap.add_argument("--frames", action="store_true", help="测交换动画帧率")
    ap.add_argument("--costs", action="store_true", help="测单帧 / 单控件成本")
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--rounds", type=int, default=1,
                    help="压测轮数；第 1 轮含字体/样式预热，稳态看第 2 轮之后")
    args = ap.parse_args(argv)

    from tools.preview_hmi_pages import make_app

    app = make_app()
    win = build_window(app)
    hmi = win._hmi
    print(f"卡片 {len(win.deck.cards())}｜页面 {sum(len(v) for v in hmi._pages.values())}"
          f"｜活跃 {sorted(hmi._active_page_ids)}"
          f"｜订阅点 {len(hmi.active_keys())}/{len(hmi.subscribe_keys)}"
          f"｜合流 {hmi._flush_ms}ms")

    picked = args.idle or args.stress or args.frames or args.costs
    if not picked:
        cmd_idle(app, win, 2.0)
        cmd_costs(app, win)
        cmd_stress(app, win, "new", args.seconds)
        cmd_frames(app, win)
    else:
        if args.idle:
            cmd_idle(app, win, args.seconds)
        if args.stress:
            for _ in range(max(1, args.rounds)):
                cmd_stress(app, win, args.stress, args.seconds)
        if args.frames:
            cmd_frames(app, win)
        if args.costs:
            cmd_costs(app, win)

    win.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
