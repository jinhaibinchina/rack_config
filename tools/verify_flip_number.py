# -*- coding: utf-8 -*-
"""翻页多位整数显示器门禁 + 动画帧预览。

    .venv/Scripts/python.exe tools/verify_flip_number.py

覆盖：位数格式化 / 前导零 / 越界夹取 / 负数 / 非法输入、逐位动画触发、
动画中连续改值不丢、动画结束落值、信号、字体自适应、翻页各阶段的
真实渲染帧（输出 ``build/preview/flip_number_frames.png``），以及按 widget
图元框反推卡片尺寸（运行态/设计态包围盒一致）。

离屏运行，不连设备、不写页面文件。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QEvent, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from App_test_fixture.fixture_app import ensure_cjk_fonts  # noqa: E402
from Designer.CoreQGraphics.runtime import ControlProvider  # noqa: E402
from Designer.CoreQGraphics.runtime.widgets import MappingProvider  # noqa: E402
from App_test_fixture.flip_number import (  # noqa: E402
    FlipDigitWidget, FlipNumberDisplay, FlipNumberProvider,
)

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "build", "preview")
FAILURES: list[str] = []


def check(label, cond, detail=""):
    if cond:
        print(f"  [OK] {label}" + (f"  {detail}" if detail else ""))
    else:
        print(f"  [FAIL] {label}" + (f"  {detail}" if detail else ""))
        FAILURES.append(label)
    return bool(cond)


def text_of(display: FlipNumberDisplay) -> str:
    return "".join(" " if d._blank else str(d.value()) for d in display.digits())


def bright_count(img: QImage) -> int:
    """亮色像素数（数字前景色）。离屏字体缺失时整帧为 0，用来防假绿。"""
    rgb = img.convertToFormat(QImage.Format_RGB32)
    data = bytes(rgb.constBits())
    return sum(1 for i in range(0, len(data), 4)
               if data[i] > 190 and data[i + 1] > 190 and data[i + 2] > 190)


def finish_all(display: FlipNumberDisplay) -> None:
    """把正在跑的动画直接推到终点，触发 finished 落值。"""
    for d in display.digits():
        if d.is_animating():
            d._anim.setCurrentTime(d._duration_ms)
    QApplication.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    # 离屏 QPA 字体库为空时 QPainter.drawText 会画不出任何字符（连 ASCII
    # 都变方块），必须手动补载，否则渲染帧全是空卡片、门禁会假绿。
    ensure_cjk_fonts()
    os.makedirs(OUT, exist_ok=True)

    print("\n=== 1. 位数格式化 ===")
    d = FlipNumberDisplay(digits=6)
    check("初始 6 位全 0", text_of(d) == "000000", text_of(d))
    check("set_value(12345) 返回 True", d.set_value(12345, animate=False))
    check("前导零补满", text_of(d) == "012345", text_of(d))
    check("value() 一致", d.value() == 12345)
    check("越界夹到最大值", d.set_value(9_999_999, animate=False)
          and text_of(d) == "999999" and d.value() == 999999, text_of(d))
    check("非法输入不改显示", not d.set_value("abc", animate=False)
          and text_of(d) == "999999")
    check("None 不改显示", not d.set_value(None, animate=False)
          and text_of(d) == "999999")
    check("字符串数字可解析", d.set_value("000042", animate=False)
          and text_of(d) == "000042", text_of(d))

    signed = FlipNumberDisplay(digits=4, signed=True)
    signed.set_value(-7, animate=False)
    check("signed 负号 + 绝对值", signed._sign.text() == "-"
          and text_of(signed) == "0007" and signed.value() == -7, text_of(signed))
    unsigned = FlipNumberDisplay(digits=4)
    unsigned.set_value(-7, animate=False)
    check("非 signed 负数夹到 0", text_of(unsigned) == "0000")

    sparse = FlipNumberDisplay(digits=5, leading_zeros=False)
    sparse.set_value(42, animate=False)
    # digits=5 → 3 个高位熄灭 + "42"；0 时熄灭 4 位、至少留个位。
    check("无前导零时高位熄灭", text_of(sparse) == "   42", repr(text_of(sparse)))
    sparse.set_value(0, animate=False)
    check("0 至少保留个位", text_of(sparse) == "    0", repr(text_of(sparse)))
    sparse.set_value(123, animate=False)
    check("熄灭位恢复显示后不残留", text_of(sparse) == "  123", repr(text_of(sparse)))

    d.set_digits(3)
    check("set_digits 重建位数", d.digit_count() == 3 and text_of(d) == "042",
          text_of(d))
    d.set_digits(6)

    print("\n=== 2. 逐位动画触发 ===")
    d.set_value(0, animate=False)
    d.set_value(12345)
    running = [i for i, x in enumerate(d.digits()) if x.is_animating()]
    check("只有变化的位翻页", running == [1, 2, 3, 4, 5], str(running))
    check("无变化的位不动", not d.digits()[0].is_animating())
    finish_all(d)
    check("动画结束落到目标值", text_of(d) == "012345", text_of(d))
    check("结束后无残留动画", not d.is_animating())

    d.set_value(12345)
    check("相同值不触发动画", not d.is_animating())
    d.set_value(12346)
    check("只有个位再次翻页",
          [i for i, x in enumerate(d.digits()) if x.is_animating()] == [5])
    finish_all(d)
    check("逐位落值正确", text_of(d) == "012346", text_of(d))

    print("\n=== 3. 动画中连续改值 ===")
    d.set_value(12346)
    d.set_value(12347)      # 排队
    d.set_value(12348)      # 覆盖 pending，只保留最终值
    finish_all(d)
    QApplication.processEvents()
    finish_all(d)
    check("pending 最终值不丢", text_of(d) == "012348", text_of(d))
    check("队列清空后静止", not d.is_animating())

    print("\n=== 4. 信号 ===")
    sig = FlipNumberDisplay(digits=3)
    seen: list[int] = []
    finished: list[int] = []
    sig.valueChanged.connect(seen.append)
    sig.flipFinished.connect(finished.append)
    sig.set_value(7)
    finish_all(sig)
    check("valueChanged 只发一次", seen == [7], str(seen))
    check("flipFinished 发一次", finished == [7], str(finished))
    sig.set_value(7)
    check("重复 set 不再发信号", seen == [7] and finished == [7])

    print("\n=== 5. 字体自适应 ===")
    for factor in (0.5, 1.0, 2.0, 3.0):
        big = FlipNumberDisplay(digits=2, size_factor=factor)
        digit = big.digits()[0]
        font = digit._fit_font()
        fm = QFontMetrics(font)
        px = font.pixelSize()
        ok = (px > 4 and fm.horizontalAdvance("0") <= digit.width()
              and fm.ascent() - fm.descent() <= digit.height())
        check(f"size_factor={factor} 字号不溢出", ok,
              f"{digit.width()}x{digit.height()} px={px}")
        check(f"size_factor={factor} 字型对齐 flip_clock（Arial Bold）",
              font.family() == "Arial" and font.bold(),
              f"family={font.family()} bold={font.bold()}")
        advances = {fm.horizontalAdvance(str(n)) for n in range(10)}
        check(f"size_factor={factor} 0~9 等宽（翻页不跳位）",
              len(advances) == 1, str(advances))

    print("\n=== 6. 渲染帧 ===")
    frames: list[QImage] = []
    labels: list[str] = []
    anim = FlipNumberDisplay(digits=3, size_factor=1.5)
    anim.set_value(0, animate=False)
    anim.set_value(1)                        # 个位 0 → 1
    for x in anim.digits():
        if x.is_animating():
            x._anim.pause()
    QApplication.processEvents()
    for p in (0.0, 0.25, 0.5, 0.75, 0.99):
        for x in anim.digits():
            if x.is_animating():
                x._set_progress(int(p * 100))
        QApplication.processEvents()
        frames.append(anim.grab().toImage().copy())
        labels.append(f"p={p:.2f}")
    check("抓到 5 帧", len(frames) == 5 and all(not f.isNull() for f in frames))
    check("帧宽高一致", len({(f.width(), f.height()) for f in frames}) == 1,
          f"{frames[0].width()}x{frames[0].height()}")
    counts = [bright_count(f) for f in frames]
    check("帧里真的画出了数字（非空白卡片）", all(c > 50 for c in counts),
          str(counts))
    check("各阶段画面确实在变化", len(set(counts)) > 1, str(counts))

    if frames:
        fw, fh = frames[0].width(), frames[0].height()
        row_h = fh + 24
        sheet = QImage(fw, row_h * len(frames), QImage.Format_ARGB32)
        sheet.fill(QColor("#eef2f8"))
        p = QPainter(sheet)
        p.setPen(QPen(QColor("#334155")))
        for i, (img, lab) in enumerate(zip(frames, labels)):
            p.drawImage(0, i * row_h + 24, img)
            p.drawText(4, i * row_h + 16, lab)
        p.end()
        path = os.path.join(OUT, "flip_number_frames.png")
        check("动画帧拼图已保存", sheet.save(path), path)

    still = FlipNumberDisplay(digits=6, signed=True, size_factor=1.5)
    still.set_value(12345, animate=False)
    QApplication.processEvents()
    check("整体示例图已保存",
          still.grab().save(os.path.join(OUT, "flip_number_display.png")))

    print("\n=== 7. 运行态 widget 图元挂载 ===")

    class FakeElement:
        item_id = 999

        def get_name(self):
            return "计数翻牌"

    provider = FlipNumberProvider(digits=4, size_factor=1.2)
    check("provider 是 ControlProvider 子类", isinstance(provider, ControlProvider))
    check("signature 固定", provider.signature(FakeElement())
          == ("flip_number", 4, 1.2, False))
    mapped = MappingProvider({"计数翻牌": provider})
    check("MappingProvider 走 provider 分支不报错",
          mapped.signature(FakeElement())[0] == "map"
          and mapped.signature(FakeElement())[1] == "flip_number",
          str(mapped.signature(FakeElement())))
    widget = mapped.create(FakeElement())
    check("create 造出 FlipNumberDisplay",
          isinstance(widget, FlipNumberDisplay) and provider.display is widget)
    check("set_value 转发到控件", provider.set_value(321, animate=False)
          and provider.display.value() == 321, text_of(provider.display))
    provider.set_value(456)
    finish_all(provider.display)
    check("转发带动画也能落值", text_of(provider.display) == "0456",
          text_of(provider.display))
    widget.deleteLater()
    widget.setParent(None)
    # deleteLater 是 DeferredDelete 事件，普通 processEvents 不一定派发它。
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    check("控件回收后引用清空", provider.display is None)
    rebuilt = provider.create(FakeElement())
    check("换页重建后恢复最近值", text_of(rebuilt) == "0456", text_of(rebuilt))

    print("\n=== 8. 按 widget 图元框反推卡片尺寸 ===")
    # 回归根因：FlipNumberDisplay 是 QSizePolicy.Fixed + setFixedSize，
    # QGraphicsProxyWidget 会把 fixed size 当 maximumSize；只要它比设计态
    # 图元框小，WidgetHost.align() 的 proxy.resize() 就被直接拒绝。
    # 结果是左上角对齐、右下角缩一圈，看起来像「位置不对」。
    class FrameItem:
        def __init__(self, w, h):
            self._r = QRectF(0, 0, w, h)

        def boundingRect(self):
            return self._r

    class SizedElement(FakeElement):
        def __init__(self, w, h):
            self._item = FrameItem(w, h)

        def item(self):
            return self._item

    sized = SizedElement(350.12, 111.89)
    fit_provider = FlipNumberProvider(digits=5)
    fitted = fit_provider.create(sized)
    check("控件尺寸取整到图元框", fitted.size().toTuple() == (350, 112),
          str(fitted.size().toTuple()))
    check("卡片高度铺满框高",
          all(d.height() == 112 for d in fitted.digits()),
          str([d.height() for d in fitted.digits()]))
    cards_w = (sum(d.width() for d in fitted.digits())
               + 4 * fitted._gap)
    check("余量摊进间距、卡片铺满框宽",
          cards_w <= 350 and 350 - cards_w < 5,
          f"cards={cards_w} digit={fitted._digit_size} gap={fitted._gap}")
    check("自适应后推值链路仍通",
          fit_provider.set_value(4321, animate=False)
          and text_of(fitted) == "04321", text_of(fitted))

    plain = FlipNumberProvider(digits=5).create(FakeElement())
    off = FlipNumberProvider(digits=5, fit_to_element=False).create(sized)
    tiny = FlipNumberProvider(digits=5).create(SizedElement(4, 4))
    check("无图元框时退回 size_factor 口径（336x92）",
          plain.size().toTuple() == (336, 92), str(plain.size().toTuple()))
    check("fit_to_element=False 可关闭自适应",
          off.size().toTuple() == (336, 92), str(off.size().toTuple()))
    check("过小/非法尺寸不破坏控件",
          tiny.size().toTuple() == (336, 92) and len(tiny.digits()) == 5,
          str(tiny.size().toTuple()))
    signed_fit = FlipNumberProvider(digits=5, signed=True).create(sized)
    signed_w = (sum(d.width() for d in signed_fit.digits())
                + 4 * signed_fit._gap + signed_fit._sign.minimumWidth())
    check("带负号时总宽仍不超框",
          signed_fit.size().toTuple() == (350, 112) and signed_w <= 350,
          f"total={signed_w} sign={signed_fit._sign.minimumWidth()}")
    for w in (fitted, plain, off, tiny, signed_fit):
        w.deleteLater()
        w.setParent(None)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} 项")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
