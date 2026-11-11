"""verify_ascii_art.py —— AsciiArtPanel 自检：出图到 tools/_out/。

跑法：
    .venv/Scripts/python.exe tools/verify_ascii_art.py
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from common.com.ascii_art import AsciiArtPanel, make_banner  # noqa: E402

OUT_DIR = os.path.join(_ROOT, "tools", "_out")

# 用户贴进来的原文，一个字符都不动
USER_ART = """\
_____ _____ _____ _____ _____ _____ _____ _____
|     |     |     |   | |     |  _  |  |  |   __|
| | | |  |  |  |  | | | |   --|     |    -|   __|
|_|_|_|_____|_____|_|___|_____|__|__|__|__|_____|"""


def main() -> int:
    app = QApplication(sys.argv)
    os.makedirs(OUT_DIR, exist_ok=True)

    host = QWidget()
    host.setStyleSheet("background:#191a1b;")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)

    # 1) 用户原文，按笔画分色（竖=琥珀，横=青灰）
    a = AsciiArtPanel(USER_ART)
    a.set_frame_visible(True)

    # 2) digital 字体：每格一个框，最接近参考截图的线条面板
    b = AsciiArtPanel(make_banner("WARNING", font="digital"))
    b.set_frame_visible(True)

    # 3) small 字体 + 单色，塞进任何 HMI 都不违和
    c = AsciiArtPanel(make_banner("STOP 9", font="small"))
    c.set_frame_visible(True)
    c.set_colored(False)
    c.set_colors(fg="#8fa1b3")

    for w in (a, b, c):
        lay.addWidget(w, 1)

    host.resize(780, 620)
    host.show()
    app.processEvents()

    path = os.path.join(OUT_DIR, "ascii_art_preview.png")
    host.grab().save(path)
    print("saved:", path)
    print()
    print("=== digital ===")
    print(b.art())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
