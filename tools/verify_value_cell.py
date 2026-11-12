# -*- coding: utf-8 -*-
"""伺服轴面板数值单元宽度门禁 / 截图。

    .venv/Scripts/python.exe tools/verify_value_cell.py

现场反馈「红圈内数值只显示了一半」：ValueCell 里的 QLabel 右对齐，
当分配宽度小于文字实际宽度时 Qt 会**直接从左侧裁掉文字**（没有省略号、
不会缩小字号），例如 ``1174.74 mm/s`` 显示成 ``174.74 mm/s``。
``WriteRow`` 的旧注释里也记着同一坑（``100.00 → 1.00``）。

本门禁按 QFontMetrics 量出「文字需要多宽」与「QLabel 拿到多宽」，
任何 CLIP 都判失败；同时检查字号下限，防止靠把字缩到看不清来蒙混。
另输出不同面板宽度下的截图供人工核对。

不连设备、不写页面文件。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from App_test_fixture import fixture_config as cfg  # noqa: E402
from App_test_fixture.fixture_app import ensure_cjk_fonts  # noqa: E402
from App_test_fixture.servo_panel import ServoAxisPanel  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "build", "preview")
# 覆盖 columns_for 的三档（>=430 / >=320 / 其余）和图元默认 468。
WIDTHS = (240, 320, 430, 468, 600, 964)
MIN_PX = 7
# 现场量级：含 3 位数 + 2 位小数 + 单位，以及 4 位数 / 负数的极端情况。
VALUES = {
    cfg.axis_status_key("fPositionNow"): 29.38,
    cfg.axis_status_key("fVelocityNow"): 1174.74,
    cfg.axis_status_key("iState"): 4,
    cfg.axis_status_key("sDriverErrorID"): 1,
}
for _label, _field, _unit in cfg.AXIS_WRITE_FIELDS:
    VALUES[cfg.axis_manual_key(_field)] = -1234.56

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> bool:
    if not cond:
        FAILURES.append(label + (f"  {detail}" if detail else ""))
    return cond


def inspect(label_obj, owner: str, short: str, width: int) -> None:
    text = label_obj.text()
    need = label_obj.fontMetrics().horizontalAdvance(text)
    got = label_obj.width()
    px = label_obj.font().pixelSize()
    check(f"w={width} {owner}/{short} 文本完整",
          need <= got, f"{text!r} 需 {need}px / 得 {got}px")
    check(f"w={width} {owner}/{short} 字号可读",
          MIN_PX <= px <= cfg.PANEL_FONT_PX, f"px={px}")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    ensure_cjk_fonts()
    os.makedirs(OUT, exist_ok=True)

    for width in WIDTHS:
        panel = ServoAxisPanel()
        panel.resize(width, 345)
        panel.show()
        app.processEvents()
        panel.set_values(VALUES)
        app.processEvents()
        print(f"\n=== 面板宽 {width}，数值列 {panel.columns_for(width)[1]} ===")
        for key, cell in panel.cells.items():
            short = key.split(".")[-1]
            inspect(cell._value, "值", short, width)
            print(f"  {short:<20} {cell._value.text()!r:<20} "
                  f"需 {cell._value.fontMetrics().horizontalAdvance(cell._value.text()):>3}"
                  f" / 得 {cell._value.width():>3}"
                  f"  px={cell._value.font().pixelSize()}")
            # 业务语义不变：文案仍是「数值 单位」，没有被 elide 成 "..."。
            check(f"w={width} 值/{short} 文案未加工",
                  cell.current_text() == cell._value.text())
        for key, row in panel.writes.items():
            short = key.split(".")[-1]
            inspect(row._current, "写入行", short, width)
            check(f"w={width} 写入行/{short} 文案未加工",
                  row.current_text() == row._current.text())
            print(f"  写入行 {short:<14} {row._current.text()!r:<20} "
                  f"需 {row._current.fontMetrics().horizontalAdvance(row._current.text()):>3}"
                  f" / 得 {row._current.width():>3}"
                  f"  px={row._current.font().pixelSize()}")

        # 图元默认尺寸下，布局本身就必须够宽，不能只靠缩字号过关。
        if width == 468:
            velocity = panel.cells[cfg.axis_status_key("fVelocityNow")]._value
            check("468 宽下布局按内容分配（速度仍是基础字号）",
                  velocity.font().pixelSize() == cfg.PANEL_FONT_PX,
                  f"px={velocity.font().pixelSize()}")

        panel.grab().save(os.path.join(OUT, f"value_cell_w{width}.png"))
        panel.hide()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} 项")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("ALL PASS：所有数值文本都有足够显示宽度，字号未失真")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
