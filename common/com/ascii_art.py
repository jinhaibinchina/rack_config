"""ascii_art.py —— 等宽字符画面板：把 ASCII art 原文本当显示面板用。

与前一个 ascii_panel.py 的区别：
  ascii_panel  吃「文本」，内部用 5x7 点阵重新画字（矢量，可缩放，但字形固定）
  ascii_art    吃「已经拼好的字符画」，按字符网格 1:1 还原（所见即所得，能画表格/框线/波形）

三个关键实现点，都是会踩坑的地方：
  1. 缩放绝不要改 QFont 的 pixelSize 再重排：
     字号一变，hinting 就把字符 advance 取整成新的整数，字符宽度和行高不再
     保持固定比例，几十列之后整块图形会梯形倾斜、竖线对不上。
     正确做法是定一个基准字号量出基准网格，再用 QPainter 的 world transform
     整体缩放——矢量渲染，任意大小都严丝合缝。
  2. 不要按 fm.horizontalAdvance 累加 x 坐标：它是浮点，累加会有累计误差。
     用 round() 得到的固定整数格宽，逐字符画进 [c*cw, r*ch, cw, ch] 的格子里。
  3. 必须保留行尾空格、按最长行补空格：ASCII art 靠空格占位，一旦 rstrip
     或按行长度不等处理，右边框就会塌进去。

自动分色：| ! 等竖笔画用 fg_vert，_ - = 等横笔画用 fg_horiz，/ \\ 用 fg_diag，
其余字母数字用 fg。参考截图里琥珀竖线 + 青灰横线的配色就是这么来的。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

__all__ = ["AsciiArtPanel", "make_banner", "available_fonts"]

# 字符 → 笔画类别
_VERT = set("|![]{}()IL")
_HORIZ = set("_-=~")
_DIAG = set("/\\<>")
_KIND_V, _KIND_H, _KIND_D, _KIND_X = 0, 1, 2, 3


def _classify(ch: str) -> int:
    if ch in _HORIZ:
        return _KIND_H
    if ch in _VERT:
        return _KIND_V
    if ch in _DIAG:
        return _KIND_D
    return _KIND_X


class AsciiArtPanel(QWidget):
    """等宽字符画显示面板。原样保留空格与行结构，等比缩放不糊。"""

    def __init__(self, art: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._lines: List[str] = []
        self._cols = 0

        # 配色：竖笔画琥珀、横笔画青灰，取自参考截图
        self._bg = QColor("#191a1b")
        self._fg = QColor("#cccccc")
        self._fg_v = QColor("#aa7e1b")
        self._fg_h = QColor("#7daacc")
        self._fg_d = QColor("#8a8f98")

        self._base_px = 22          # 基准字号（只量网格用，不参与布局）
        self._cell_px: Optional[float] = None  # 非空则强制 1:1 显示，不缩放
        self._pad = 8.0
        self._font_family = "Consolas"
        self._colored = True
        self._frame = False

        self._font = QFont(self._font_family)
        self._font.setStyleHint(QFont.Monospace)
        self._font.setPixelSize(self._base_px)
        self._font.setHintingPreference(QFont.PreferNoHinting)

        fm = QFontMetricsF(self._font)
        self._cw = max(1, int(round(fm.horizontalAdvance("M"))))
        self._ch = max(1, int(round(fm.height())))

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.set_art(art)

    # ------------------------------------------------------------------ API

    def set_art(self, art: str) -> None:
        """设置字符画原文。空格必须保留——这里不做任何 strip。"""
        raw = art.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
        self._lines = raw.split("\n")
        # 去掉首尾的全空行（贴进来的文本常带），但保留行内空格
        while self._lines and not self._lines[0].strip():
            self._lines.pop(0)
        while self._lines and not self._lines[-1].strip():
            self._lines.pop()
        if not self._lines:
            self._lines = [""]
        self._cols = max(len(x) for x in self._lines)
        # 按最长行右侧补空格，保证右侧边框不塌
        self._lines = [x.ljust(self._cols) for x in self._lines]
        self.setMinimumSize(self.sizeHint())
        self.updateGeometry()
        self.update()

    def art(self) -> str:
        return "\n".join(self._lines)

    def set_colors(
        self,
        *,
        fg: Optional[str] = None,
        fg_vert: Optional[str] = None,
        fg_horiz: Optional[str] = None,
        fg_diag: Optional[str] = None,
        bg: Optional[str] = None,
    ) -> None:
        if fg:
            self._fg = QColor(fg)
        if fg_vert:
            self._fg_v = QColor(fg_vert)
        if fg_horiz:
            self._fg_h = QColor(fg_horiz)
        if fg_diag:
            self._fg_d = QColor(fg_diag)
        if bg:
            self._bg = QColor(bg)
        self.update()

    def set_colored(self, enabled: bool) -> None:
        """False = 全部单色（有些 HMI 场景不允许彩色）。"""
        self._colored = enabled
        self.update()

    def set_font_family(self, family: str) -> None:
        self._font_family = family
        self._font.setFamily(family)
        fm = QFontMetricsF(self._font)
        self._cw = max(1, int(round(fm.horizontalAdvance("M"))))
        self._ch = max(1, int(round(fm.height())))
        self.setMinimumSize(self.sizeHint())
        self.updateGeometry()
        self.update()

    def set_cell_pixel_size(self, px: Optional[float]) -> None:
        """固定每个字符格的像素尺寸（1:1，不缩放）；None = 自适应填满控件。"""
        self._cell_px = px
        self.setMinimumSize(self.sizeHint())
        self.updateGeometry()
        self.update()

    def set_frame_visible(self, visible: bool) -> None:
        self._frame = visible
        self.update()

    # ------------------------------------------------------------- Qt sizing

    def sizeHint(self) -> QSize:
        if self._cell_px is not None:
            cw = ch = self._cell_px
        else:
            cw, ch = float(self._cw), float(self._ch)
        return QSize(
            int(self._cols * cw + 2 * self._pad),
            int(len(self._lines) * ch + 2 * self._pad),
        )

    def minimumSizeHint(self) -> QSize:
        # 最小尺寸给一个能认出来的下限，避免被 layout 压成一条线
        return QSize(
            int(self._cols * self._cw * 0.35 + 2 * self._pad),
            int(len(self._lines) * self._ch * 0.35 + 2 * self._pad),
        )

    # -------------------------------------------------------------- painting

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._bg)

        if self._frame:
            painter.setPen(QPen(QColor("#3a3b3d"), 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1))

        if not self._lines or self._cols == 0:
            return

        rows = len(self._lines)
        base_w = self._cols * self._cw
        base_h = rows * self._ch

        if self._cell_px is not None:
            scale = self._cell_px / self._cw
        else:
            avail_w = max(1.0, self.width() - 2 * self._pad)
            avail_h = max(1.0, self.height() - 2 * self._pad)
            scale = min(avail_w / base_w, avail_h / base_h)

        # 整体 world transform 缩放：基准网格永远不变，字符宽度/行高比例恒定
        painter.translate(
            (self.width() - base_w * scale) / 2.0,
            (self.height() - base_h * scale) / 2.0,
        )
        painter.scale(scale, scale)

        painter.setFont(self._font)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        # 按笔画类别分桶，pen 只切换 4 次
        buckets: Dict[int, List[tuple[int, int, str]]] = {
            _KIND_V: [],
            _KIND_H: [],
            _KIND_D: [],
            _KIND_X: [],
        }
        for r, line in enumerate(self._lines):
            for c, ch in enumerate(line):
                if ch == " ":
                    continue
                buckets[_classify(ch)].append((r, c, ch))

        if not self._colored:
            # 单色模式：全部并到一组
            pen = QPen(self._fg)
            painter.setPen(pen)
            for items in buckets.values():
                for r, c, ch in items:
                    painter.drawText(
                        QRectF(c * self._cw, r * self._ch, self._cw, self._ch),
                        int(Qt.AlignCenter),
                        ch,
                    )
            return

        color_of = {
            _KIND_V: self._fg_v,
            _KIND_H: self._fg_h,
            _KIND_D: self._fg_d,
            _KIND_X: self._fg,
        }
        for kind, items in buckets.items():
            if not items:
                continue
            painter.setPen(QPen(color_of[kind]))
            for r, c, ch in items:
                painter.drawText(
                    QRectF(c * self._cw, r * self._ch, self._cw, self._ch),
                    int(Qt.AlignCenter),
                    ch,
                )


# ---------------------------------------------------------------------------
# 生成器：pyfiglet 是行业标准（500+ 字体），自己光栅化字体得到的点阵在
# 5 列宽度下必然糊成一片竖线，所以这里直接复用它。
# ---------------------------------------------------------------------------

def make_banner(
    text: str,
    *,
    font: str = "digital",
    width: int = 240,
) -> str:
    """用 figlet 字体生成字符画。

    风格最接近「框线面板」的几个字体：
      digital  每格一个方框  +-+-+-+ / |A|B|C|   ← 最像参考截图
      small    5 行高，线条细，适合紧凑面板
      banner   实心 # 块，粗壮
      standard 经典学院派
      mini     3 行，最省地方
    """
    try:
        import pyfiglet
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "生成字符画需要 pyfiglet：.venv/Scripts/python.exe -m pip install pyfiglet"
        ) from exc

    out = pyfiglet.figlet_format(text, font=font, width=width)
    return out.rstrip("\n")


def available_fonts() -> list[str]:
    """列出 pyfiglet 支持的全部字体名。"""
    try:
        from pyfiglet import FigletFont
    except ImportError:
        return []
    return sorted(FigletFont.getFonts())
