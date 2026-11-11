"""ascii_panel.py —— 终端「线段点阵」风格的显示面板。

把文本渲染成用短线段一格一格拼出来的大字（类似 ANSI/figlet banner），
可直接当普通 QWidget 嵌进任意 Qt 窗口 / .ui 提升控件。

设计要点（这几条是踩过的坑）：
  1. 不要用 QLabel + 等宽字体去显示字符画：行高会被 font leading / 缩放
     污染，多行累积后整块错位。这里全部用 QPainter 按整数网格自绘，
     与字体度量完全解耦，缩放窗口也不散架。
  2. 不要靠 QFont.setFixedPitch(True) 保证等宽：它只对真正等宽的族生效，
     存在回退字体时会静默失效。自绘网格不存在这个问题。
  3. 线段长度取格子的 92% 而不是 100%：保留图片里那种「一点点断开的
     虚线感」，同时也避免相邻线段糊成一条实心粗线。

用法：
    panel = AsciiPanel("WARNING")
    panel.set_style(BannerStyle.LINE)      # 线段 / 方块 / 纯文本
    panel.set_colors(fg="#aa7e1b", fg_alt="#7daacc", bg="#191a1b")
    panel.set_blink(True, period_ms=800)

    # 只要文本（贴到 QPlainTextEdit / 日志 / 终端里）：
    print(AsciiPanel.render_text("WARNING", mark="#"))
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

__all__ = ["AsciiPanel", "BannerStyle", "GLYPH_5X7", "build_rows"]

# --------------------------------------------------------------------------
# 5x7 点阵字库：每个字符 7 行 x 5 列，'#' 为亮点。
# 想加字就往这里塞，键是单个大写字符。
# --------------------------------------------------------------------------
GLYPH_5X7: Dict[str, Sequence[str]] = {
    " ": ("     ", "     ", "     ", "     ", "     ", "     ", "     "),
    "0": (" ### ", "#   #", "#  ##", "# # #", "##  #", "#   #", " ### "),
    "1": ("  #  ", " ##  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "),
    "2": (" ### ", "#   #", "    #", "   # ", "  #  ", " #   ", "#####"),
    "3": ("#####", "   # ", "  #  ", "   # ", "    #", "#   #", " ### "),
    "4": ("   # ", "  ## ", " # # ", "#  # ", "#####", "   # ", "   # "),
    "5": ("#####", "#    ", "#### ", "    #", "    #", "#   #", " ### "),
    "6": ("  ## ", " #   ", "#    ", "#### ", "#   #", "#   #", " ### "),
    "7": ("#####", "    #", "   # ", "  #  ", " #   ", " #   ", " #   "),
    "8": (" ### ", "#   #", "#   #", " ### ", "#   #", "#   #", " ### "),
    "9": (" ### ", "#   #", "#   #", " ####", "    #", "   # ", " ##  "),
    "A": (" ### ", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"),
    "B": ("#### ", "#   #", "#   #", "#### ", "#   #", "#   #", "#### "),
    "C": (" ### ", "#   #", "#    ", "#    ", "#    ", "#   #", " ### "),
    "D": ("###  ", "#  # ", "#   #", "#   #", "#   #", "#  # ", "###  "),
    "E": ("#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#####"),
    "F": ("#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#    "),
    "G": (" ### ", "#   #", "#    ", "#  ##", "#   #", "#   #", " ### "),
    "H": ("#   #", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"),
    "I": (" ### ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "),
    "J": ("  ###", "   # ", "   # ", "   # ", "   # ", "#  # ", " ##  "),
    "K": ("#   #", "#  # ", "# #  ", "##   ", "# #  ", "#  # ", "#   #"),
    "L": ("#    ", "#    ", "#    ", "#    ", "#    ", "#    ", "#####"),
    "M": ("#   #", "## ##", "# # #", "# # #", "#   #", "#   #", "#   #"),
    "N": ("#   #", "##  #", "# # #", "#  ##", "#   #", "#   #", "#   #"),
    "O": (" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "),
    "P": ("#### ", "#   #", "#   #", "#### ", "#    ", "#    ", "#    "),
    "Q": (" ### ", "#   #", "#   #", "#   #", "# # #", "#  # ", " ## #"),
    "R": ("#### ", "#   #", "#   #", "#### ", "# #  ", "#  # ", "#   #"),
    "S": (" ####", "#    ", "#    ", " ### ", "    #", "    #", "#### "),
    "T": ("#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "),
    "U": ("#   #", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "),
    "V": ("#   #", "#   #", "#   #", "#   #", "#   #", " # # ", "  #  "),
    "W": ("#   #", "#   #", "#   #", "# # #", "# # #", "## ##", "#   #"),
    "X": ("#   #", "#   #", " # # ", "  #  ", " # # ", "#   #", "#   #"),
    "Y": ("#   #", "#   #", " # # ", "  #  ", "  #  ", "  #  ", "  #  "),
    "Z": ("#####", "    #", "   # ", "  #  ", " #   ", "#    ", "#####"),
    "-": ("     ", "     ", "     ", "#####", "     ", "     ", "     "),
    "_": ("     ", "     ", "     ", "     ", "     ", "     ", "#####"),
    ".": ("     ", "     ", "     ", "     ", "     ", " ##  ", " ##  "),
    ",": ("     ", "     ", "     ", "     ", " ##  ", " ##  ", " #   "),
    ":": ("     ", " ##  ", " ##  ", "     ", " ##  ", " ##  ", "     "),
    "!": ("  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "     ", "  #  "),
    "?": (" ### ", "#   #", "    #", "   # ", "  #  ", "     ", "  #  "),
    "/": ("    #", "    #", "   # ", "  #  ", " #   ", "#    ", "#    "),
    ">": ("#    ", " #   ", "  #  ", "   # ", "  #  ", " #   ", "#    "),
    "<": ("    #", "   # ", "  #  ", " #   ", "  #  ", "   # ", "    #"),
    "%": ("##  #", "##  #", "   # ", "  #  ", " #   ", "#  ##", "#  ##"),
    "+": ("     ", "  #  ", "  #  ", "#####", "  #  ", "  #  ", "     "),
    "*": ("     ", "# # #", " ### ", "#####", " ### ", "# # #", "     "),
}

GLYPH_W = 5
GLYPH_H = 7


def build_rows(text: str, gap: int = 1) -> List[str]:
    """把文本摊成点阵字符行（'#' = 亮）。多行输入会纵向拼接。"""
    lines = text.upper().splitlines() or [""]
    blank = (" " * GLYPH_W,) * GLYPH_H
    out: List[str] = []

    for src in lines:
        glyphs = [GLYPH_5X7.get(ch, GLYPH_5X7["?"]) for ch in src] or [blank]
        sep = " " * gap
        for r in range(GLYPH_H):
            out.append(sep.join(g[r] for g in glyphs))
    return out


class BannerStyle(str, Enum):
    """LINE  逐点画短线段（复刻参考图质感）
    BLOCK 逐点填小方块（LED 点阵屏）
    TEXT  不画，直接给等宽文本（'█' / '·'）
    """

    LINE = "line"
    BLOCK = "block"
    TEXT = "text"


class AsciiPanel(QWidget):
    """线段点阵文本显示面板。"""

    def __init__(
        self,
        text: str = "WARNING",
        parent: Optional[QWidget] = None,
        *,
        style: BannerStyle = BannerStyle.LINE,
    ) -> None:
        super().__init__(parent)
        self._rows: List[str] = []
        self._style = style

        # 配色取自参考截图
        self._fg = QColor("#aa7e1b")       # 竖笔画
        self._fg_alt = QColor("#7daacc")   # 横笔画
        self._fg_off = QColor("#2a2b2d")   # 熄灭态（闪烁时用）
        self._bg = QColor("#191a1b")
        self._frame = QColor("#3a3b3d")

        self._pixel = 7.0          # 单个点阵格的基础像素
        self._pad = 6.0
        self._line_ratio = 0.17    # 线宽 / 格宽
        self._seg_ratio = 0.46     # 线段半长 / 格，0.5 = 完全闭合
        self._gap_ratio = 0.08     # BLOCK 风格留缝
        self._draw_frame = False
        self._draw_grid = False
        self._grid_color = QColor("#242628")
        self._draw_off = False     # 是否画熄灭点

        self._blink = False
        self._blink_on = True
        self._blink_timer = QTimer(self)
        self._blink_timer.setSingleShot(False)
        self._blink_timer.timeout.connect(self._toggle_blink)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setMinimumSize(self.sizeHint())
        self.set_text(text)

    # ---------------- 公共 API ----------------

    def set_text(self, text: str) -> None:
        self._rows = build_rows(text)
        self.updateGeometry()
        self.update()

    def text_rows(self) -> List[str]:
        return list(self._rows)

    def set_style(self, style: BannerStyle) -> None:
        self._style = BannerStyle(style)
        self.update()

    def set_colors(
        self,
        *,
        fg: Optional[str] = None,
        fg_alt: Optional[str] = None,
        bg: Optional[str] = None,
    ) -> None:
        if fg:
            self._fg = QColor(fg)
        if fg_alt:
            self._fg_alt = QColor(fg_alt)
        if bg:
            self._bg = QColor(bg)
        self.update()

    def set_pixel_size(self, px: float) -> None:
        self._pixel = max(2.0, float(px))
        self.setMinimumSize(self.sizeHint())
        self.updateGeometry()
        self.update()

    def set_blink(self, enabled: bool, period_ms: int = 800) -> None:
        self._blink = enabled
        self._blink_timer.stop()
        if enabled:
            self._blink_timer.start(max(120, period_ms))
        else:
            self._blink_on = True
        self.update()

    def set_frame_visible(self, visible: bool) -> None:
        self._draw_frame = visible
        self.update()

    def set_grid_visible(self, visible: bool, color: Optional[str] = None) -> None:
        """底纹点阵：所有格位都画一个暗点，做出硬件点阵屏的栅格感。"""
        self._draw_grid = visible
        if color:
            self._grid_color = QColor(color)
        self.update()

    @staticmethod
    def render_text(text: str, mark: str = "█", off: str = " ") -> str:
        """只要纯文本形态（可贴进 QPlainTextEdit / 日志 / 终端）。"""
        return "\n".join(
            line.replace("#", mark).replace(" ", off) for line in build_rows(text)
        )

    # ---------------- Qt 尺寸 ----------------

    def _grid_shape(self) -> tuple[int, int]:
        if not self._rows:
            return 0, 0
        return len(self._rows[0]), len(self._rows)  # cols, rows

    def sizeHint(self) -> QSize:
        cols, rows = self._grid_shape()
        if not cols:
            return QSize(120, 60)
        w = cols * self._pixel + 2 * self._pad
        h = rows * self._pixel + 2 * self._pad
        return QSize(int(round(w)), int(round(h)))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # ---------------- 绘制 ----------------

    def _toggle_blink(self) -> None:
        self._blink_on = not self._blink_on
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        cols, rows = self._grid_shape()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        painter.fillRect(self.rect(), self._bg)
        if not cols or not rows:
            return

        if self._style is BannerStyle.TEXT:
            self._paint_text(painter, cols, rows)
            return

        pad = self._pad
        avail_w = max(1.0, self.width() - 2 * pad)
        avail_h = max(1.0, self.height() - 2 * pad)
        # 正方形格网：横竖同尺寸，避免字被拉扁或抽高
        cell = min(avail_w / cols, avail_h / rows)
        x0 = (self.width() - cols * cell) / 2.0
        y0 = (self.height() - rows * cell) / 2.0
        cw = ch = cell

        lit = self._blink_on if self._blink else True

        if self._draw_grid:
            # 底纹：每个格位画一个极暗的点，做出 LED 屏的「栅格感」
            dot = max(1.0, cell * 0.16)
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._grid_color)
            for r in range(rows):
                cy = y0 + r * ch + ch / 2.0
                for c in range(cols):
                    cx = x0 + c * cw + cw / 2.0
                    painter.drawRect(QRectF(cx - dot / 2, cy - dot / 2, dot, dot))
            painter.setBrush(Qt.NoBrush)

        if self._draw_frame:
            pen = QPen(self._frame, 1.0)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1))

        def on(r: int, c: int) -> bool:
            if r < 0 or r >= rows or c < 0 or c >= cols:
                return False
            return self._rows[r][c] == "#"

        if self._style is BannerStyle.BLOCK:
            size = cell * (1.0 - self._gap_ratio)
            for r in range(rows):
                row = self._rows[r]
                for c in range(cols):
                    if row[c] != "#":
                        if self._draw_off and not lit:
                            painter.fillRect(
                                QRectF(x0 + c * cw + (cw - size) / 2,
                                       y0 + r * ch + (ch - size) / 2, size, size),
                                self._fg_off,
                            )
                        continue
                    color = self._fg if lit else self._fg_off
                    painter.fillRect(
                        QRectF(x0 + c * cw + (cw - size) / 2,
                               y0 + r * ch + (ch - size) / 2, size, size),
                        color,
                    )
            return

        # ---- LINE：逐点判断走向，画短线段 ----
        # 横笔画铺满整格（否则横线会断成一节一节，字认不出来）；
        # 竖笔画留 8% 缝隙，保留参考图那种「一点点断开」的宿命感。
        lw = max(1.0, cw * self._line_ratio)
        half_w = cw * 0.48          # 留 4% 缝：隐约断点，但仍读得成一条横线
        half_h = ch * self._seg_ratio
        v_color = self._fg if lit else self._fg_off
        h_color = self._fg_alt if lit else self._fg_off

        pen = QPen(v_color, lw)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)

        for r in range(rows):
            row = self._rows[r]
            cy = y0 + r * ch + ch / 2.0
            for c in range(cols):
                if row[c] != "#":
                    if self._draw_off and not lit:
                        painter.fillRect(
                            QRectF(x0 + c * cw + cw / 2 - lw / 2, cy - half_h * 0.3,
                                   lw, half_h * 0.6),
                            self._fg_off,
                        )
                    continue
                cx = x0 + c * cw + cw / 2.0
                left, right = on(r, c - 1), on(r, c + 1)
                up, down = on(r - 1, c), on(r + 1, c)

                if left or right:
                    pen.setColor(h_color)
                    painter.setPen(pen)
                    painter.drawLine(
                        int(round(cx - half_w)), int(round(cy)),
                        int(round(cx + half_w)), int(round(cy)),
                    )
                    if up or down:
                        pen.setColor(v_color)
                        painter.setPen(pen)
                        painter.drawLine(
                            int(round(cx)), int(round(cy - half_h)),
                            int(round(cx)), int(round(cy + half_h)),
                        )
                elif up or down:
                    pen.setColor(v_color)
                    painter.setPen(pen)
                    painter.drawLine(
                        int(round(cx)), int(round(cy - half_h)),
                        int(round(cx)), int(round(cy + half_h)),
                    )
                else:
                    # 孤立点：一个小方块，避免出现空洞
                    s = cw * 0.38
                    painter.fillRect(
                        QRectF(cx - s / 2, cy - s / 2, s, s),
                        v_color,
                    )

    def _paint_text(self, painter: QPainter, cols: int, rows: int) -> None:
        """TEXT 风格：真·等宽字体，逐字符落到固定格子里。"""
        cw = max(2.0, self.width() / max(1, cols))
        ch = max(2.0, self.height() / max(1, rows))

        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPixelSize(max(2, int(ch * 0.95)))
        painter.setFont(font)

        painter.setPen(QPen(self._fg))
        for r in range(rows):
            row = self._rows[r]
            for c in range(cols):
                if row[c] == "#":
                    # 固定格子对齐，不依赖字体真实 advance
                    painter.drawText(
                        QRectF(c * cw, r * ch, cw, ch),
                        int(Qt.AlignCenter),
                        "█",
                    )
