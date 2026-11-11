"""verify_ascii_panel.py —— AsciiPanel 渲染自检：出图到 tools/_out/。

跑法：
    .venv/Scripts/python.exe tools/verify_ascii_panel.py
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from common.com.ascii_panel import AsciiPanel, BannerStyle  # noqa: E402

OUT_DIR = os.path.join(_ROOT, "tools", "_out")


def main() -> int:
    app = QApplication(sys.argv)
    os.makedirs(OUT_DIR, exist_ok=True)

    host = QWidget()
    host.setStyleSheet("background:#191a1b;")
    lay = QVBoxLayout(host)
    lay.setContentsMargins(14, 14, 14, 14)
    lay.setSpacing(10)

    # 1) 复刻参考图：琥珀竖笔画 + 青灰横笔画 + 栅格底纹 + 细边框
    a = AsciiPanel("WARNING")
    a.set_style(BannerStyle.LINE)
    a.set_frame_visible(True)
    a.set_grid_visible(True)
    a.set_blink(True, 900)

    # 2) LED 点阵屏风格
    b = AsciiPanel("RACK 12")
    b.set_style(BannerStyle.BLOCK)
    b.set_colors(fg="#7daacc", fg_alt="#7daacc")
    b.set_frame_visible(True)

    # 3) 灰度线条，塞进任何 HMI 面板都不违和
    c = AsciiPanel("STOP 0-9")
    c.set_style(BannerStyle.LINE)
    c.set_colors(fg="#cccccc", fg_alt="#8fa1b3")
    c.set_frame_visible(True)
    c.set_grid_visible(True, "#212325")

    for w in (a, b, c):
        lay.addWidget(w)

    host.resize(780, 400)
    host.show()
    app.processEvents()

    path = os.path.join(OUT_DIR, "ascii_panel_preview.png")
    host.grab().save(path)
    print("saved:", path)

    # 纯文本形态：可贴进 QPlainTextEdit / 日志 / 终端
    print(AsciiPanel.render_text("HALO 0123", mark="#"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
