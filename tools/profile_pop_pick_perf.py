"""PopPick 交换动画的帧率探针：量化"放大后卡顿"以及两处优化的贡献。

结论（离屏软件渲染，1280×820，520ms 动画，33 帧为 QVariantAnimation 的
16ms 间隔上限）：

    scale   改动前        只加位图快照   快照+占位框只描边
    0.5     33帧/16.0ms   33帧          33帧
    1.0     31帧/17.5ms   33帧          33帧
    1.5     19帧/29.1ms   32帧          30帧
    2.0     11帧/61.5ms   29帧          33帧
    3.0     11帧/56.5ms   27帧          25帧
    4.0     14帧/39.2ms   30帧          26帧

"重绘"列是控件真正收到 paint 的次数：改动前一次动画 77~517 次（6 张卡每帧
都重渲染），优化后固定 6 次（每张卡只在动画开始时烘焙一次）。

跑法::

    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tools/profile_pop_pick_perf.py
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QEvent, QEventLoop, QObject, QPointF, QTimer
from PySide6.QtWidgets import QApplication

from Designer.Core.elements import widget_element
from App_PopPick.page_deck import PageDeck
from App_PopPick.pop_pick_entry import PopPickWindow


def spin(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def set_zoom(window: PopPickWindow, factor: float) -> None:
    """以窗口中心为锚点缩放。

    只改 ``scale_factor`` 不同步 ``offset`` 的话内容会整体移出视野，测出来
    "放大反而更快"，是假象。
    """
    scene = window.scene
    center = QPointF(scene.width() / 2.0, scene.height() / 2.0)
    anchor = (center - scene.offset) / (scene.scale_factor or 1.0)
    scene.scale_factor = factor
    scene.offset = center - anchor * factor
    scene.refresh_embedded_widgets()
    spin(30)


class PaintCounter(QObject):
    """统计控件真正收到 paint 的次数（零噪声，用来验证缓存是否生效）。"""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
        if event.type() == QEvent.Paint:
            self.count += 1
        return False


def run_swap(window: PopPickWindow, counters: list) -> tuple:
    deck = window.deck
    for counter in counters:
        counter.count = 0
    stamps: list[float] = []
    start = time.perf_counter()
    if not deck.swap_with_slot(deck.stack_cards()[0]):
        return 0, 0.0, 0
    deck._anim.valueChanged.connect(lambda _v: stamps.append(time.perf_counter()))
    while deck.is_busy():
        spin(2)
    total = (time.perf_counter() - start) * 1000.0
    paints = sum(counter.count for counter in counters)
    if len(stamps) < 2:
        return len(stamps), total, paints
    gaps = [(b - a) * 1000.0 for a, b in zip(stamps, stamps[1:])]
    return len(stamps), sum(gaps) / len(gaps), paints


def best_of(window: PopPickWindow, counters: list, repeat: int = 3) -> tuple:
    """跑 ``repeat`` 次取帧数最多的一次。

    离屏后端单次跑之间抖动很大（同一配置能差 40%），取最优值才看得出方向；
    要判断绝对值请以真机为准。
    """
    best = (0, 0.0, 0)
    for _ in range(repeat):
        result = run_swap(window, counters)
        if result[0] > best[0]:
            best = result
        window.deck.reset()
        spin(30)
    return best


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = PopPickWindow(enable_plc=False)
    window.show()
    spin(150)
    cards = [c for c in window.deck.cards() if c.has_widget_layer()]

    counters = []
    for card in cards:
        counter = PaintCounter()
        card._layer.widget.installEventFilter(counter)
        counters.append(counter)

    original_fast_render = PageDeck._set_fast_render
    original_fast_paint = widget_element.set_widget_fast_paint

    print(f"窗口 {window.width()}x{window.height()}，卡片 {len(cards)} 张，动画 520ms")
    header = f"{'scale':>6} {'改动前':>20} {'只加位图快照':>20} {'快照+占位框只描边':>21}"
    print(header)
    print("-" * len(header))

    for factor in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
        set_zoom(window, factor)
        row = [f"{factor:>6.1f}"]

        # 改动前：整个快速渲染开关失效
        PageDeck._set_fast_render = lambda self, active: None
        frames, avg, paints = best_of(window, counters)
        row.append(f"{frames:>2}帧/{avg:>5.1f}ms 重绘{paints:>3}")

        # 只加位图缓存：跳过占位框那半边失效
        PageDeck._set_fast_render = original_fast_render
        widget_element.set_widget_fast_paint = lambda self, active: None
        frames, avg, paints = best_of(window, counters)
        row.append(f"{frames:>2}帧/{avg:>5.1f}ms 重绘{paints:>3}")

        # 现状
        widget_element.set_widget_fast_paint = original_fast_paint
        frames, avg, paints = best_of(window, counters)
        row.append(f"{frames:>2}帧/{avg:>5.1f}ms 重绘{paints:>3}")

        print("  ".join(row))

    PageDeck._set_fast_render = original_fast_render
    widget_element.set_widget_fast_paint = original_fast_paint
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
