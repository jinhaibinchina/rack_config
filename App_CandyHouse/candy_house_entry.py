# -*- coding: utf-8 -*-
"""
糖果屋 · CANDY HOUSE / PySide6 版
=====================================================================
用 Qt Widgets 复刻 Neo-Brutalism 个人作品集单页：
  · 2–4px 纯黑实线边框 + 零模糊纯黑硬阴影（QPainter 自绘，不用 QGraphicsDropShadowEffect）
  · 无渐变 / 无毛玻璃 / 无模糊阴影
  · SVG 纹理 → 程序化生成的平铺 QBrush（圆点 / 斜条纹 / 噪点）
  · hover 位移 + 阴影扩大、:active 物理按压、滚动揭示、进度条计数动画
  · 键盘可达（Tab / Enter / Space + 焦点虚线环）、--no-motion 等价 prefers-reduced-motion

运行（与项目内其他 App 一致，三种方式都可以）：
  python -m App_CandyHouse
  python App_CandyHouse/__main__.py
  python App_CandyHouse/candy_house_entry.py
  python App_CandyHouse/candy_house_entry.py --no-motion

若要从 AppsManagers/main.py 的启动器打开，工厂里直接
``from App_CandyHouse import CandyHouseWindow`` 即可（构造无需参数）。

依赖：仅 PySide6（QtCore / QtGui / QtWidgets），不需要 QtSvg、QtWebEngine 或任何 Web 技术。
"""
from __future__ import annotations

import os
import sys
import math
import random

from PySide6.QtCore import (
    Qt, QRect, QRectF, QPoint, QSize, QUrl, QVariantAnimation, QEasingCurve,
    Signal, QTimer,
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QFontDatabase, QPixmap, QImage,
    QPainterPath, QPolygon, QDesktopServices,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QVBoxLayout,
    QHBoxLayout, QGridLayout, QScrollArea, QSizePolicy, QGraphicsOpacityEffect,
)

# ---------------------------------------------------------------------------
# 设计系统
# ---------------------------------------------------------------------------
INK = QColor('#0A0A0A')
BLACK = QColor('#000000')
WHITE = QColor('#FFFFFF')
PAGE = QColor('#F5F5F0')
DARK = QColor('#0A0A0A')

TONES = {
    'pink':   (QColor('#FF1493'), QColor('#FFDCEF')),
    'yellow': (QColor('#FFE135'), QColor('#FFF7C4')),
    'blue':   (QColor('#00BFFF'), QColor('#CFEEFF')),
    'green':  (QColor('#A3E635'), QColor('#EEFFCD')),
    'orange': (QColor('#FF6B35'), QColor('#FFDDCC')),
    'purple': (QColor('#A855F7'), QColor('#EEDCFF')),
    'white':  (WHITE, WHITE),
}

REDUCED = ('--no-motion' in sys.argv) or (os.environ.get('QT_REDUCED_MOTION') == '1')
TEX = {}          # 纹理 brush 在 QApplication 创建后初始化


def init_textures() -> None:
    """等价于网页版的 SVG data URI 纹理，改成程序化生成的平铺 QBrush。"""
    # 圆点矩阵
    img = QImage(24, 24, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(0, 0, 0, 44)))
    p.drawEllipse(QRectF(2, 2, 4.4, 4.4))
    p.end()
    TEX['dots'] = QBrush(QPixmap.fromImage(img))

    # 斜条纹（硬边，无任何渐变）
    img = QImage(18, 18, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    p.setPen(QPen(QColor(0, 0, 0, 38), 2.4))
    for a, b, c, d in ((-4, 14, 14, -4), (2, 20, 20, 2), (10, 24, 24, 10)):
        p.drawLine(a, b, c, d)
    p.end()
    TEX['stripes'] = QBrush(QPixmap.fromImage(img))

    # 噪点（替代 SVG feTurbulence；Qt SVG 渲染器不支持 filter）
    rng = random.Random(7)
    img = QImage(96, 96, QImage.Format.Format_ARGB32)
    img.fill(QColor(0, 0, 0, 0))
    for y in range(96):
        for x in range(96):
            if rng.random() < 0.16:
                img.setPixelColor(x, y, QColor(0, 0, 0, rng.randint(10, 38)))
    TEX['noise'] = QBrush(QPixmap.fromImage(img))


def paint_texture(p: QPainter, rect: QRect, kind: str) -> None:
    if not kind:
        return
    p.save()
    path = QPainterPath()
    path.addRect(QRectF(rect))
    p.setClipPath(path)
    for name in ('dots', 'stripes', 'noise'):
        if name in kind and name in TEX:
            p.fillRect(rect, TEX[name])
    p.restore()


def make_font(kind: str, size: float, bold: bool = False) -> QFont:
    """Google Fonts 需本地安装；未安装时按 Inter / Segoe UI / 雅黑 顺序 fallback。"""
    f = QFont()
    if kind == 'display':
        f.setFamilies(['Plus Jakarta Sans', 'Segoe UI', 'Microsoft YaHei'])
    elif kind == 'mono':
        f.setFamilies(['JetBrains Mono', 'Cascadia Mono', 'Consolas', 'Microsoft YaHei'])
    else:
        f.setFamilies(['Inter', 'Segoe UI', 'Microsoft YaHei'])
    f.setPointSizeF(float(size))
    if bold:
        f.setWeight(QFont.Weight.ExtraBold)
    return f


def label(text: str, size: float = 9.5, bold: bool = False, kind: str = 'body',
          color: QColor = INK, wrap: bool = True, center: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setFont(make_font(kind, size, bold))
    lab.setStyleSheet(f'color:{color.name()};')
    lab.setWordWrap(wrap)
    if center:
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lab


# ---------------------------------------------------------------------------
# 核心：所有卡片/按钮共用的自绘容器
# ---------------------------------------------------------------------------
class BrutalCard(QWidget):
    """
    用 QPainter 手工绘制「纯黑偏移实心矩形 + 纯色底 + 纯黑实线边框」。
    hover/active 不改变 widget 几何（避免触发布局重排），只改变绘制偏移，
    与网页版 transform 的语义一致。
    """
    clicked = Signal()

    PAD_L = 6       # 预留 hover 上移空间
    PAD_R = 14      # 预留最大硬阴影空间

    def __init__(self, tone: str = 'white', border: int = 3, shadow: int = 5,
                 texture: str = '', interactive: bool = False, animated: bool = False,
                 pad: int = 14, deco: str = '', bg: QColor | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.main, self.bg = TONES[tone]
        if bg is not None:
            self.bg = bg
        self.border = border
        self.base_shadow = shadow
        self.shadow = float(shadow)
        self.lift = 0.0
        self.press = 0.0
        self.pressed = False
        self.interactive = interactive
        self.animated = animated and not REDUCED
        self.revealed = not self.animated
        # 揭示动画只做视觉位移；可见性不依赖动画回调是否触发
        self.reveal_shift = 0.0
        self.texture = texture
        self.deco = deco
        self.pad = pad
        self.focus_ring = False
        self._anims: list = []

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if interactive
                            else Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.content = QWidget(self)

        if self.animated:
            self.opacity = QGraphicsOpacityEffect(self)
            self.opacity.setOpacity(0.0)
            self.setGraphicsEffect(self.opacity)

    # -- 几何 ----------------------------------------------------------------
    def body_rect(self) -> QRect:
        l = int(round(self.lift))
        pr = int(round(self.press))
        return QRect(
            self.PAD_L - l + pr,
            self.PAD_L - l + pr,
            max(10, self.width() - self.PAD_L - self.PAD_R - pr),
            max(10, self.height() - self.PAD_L - self.PAD_R - pr),
        )

    def content_rect(self) -> QRect:
        m = self.border + self.pad
        r = self.body_rect().adjusted(m, m, -m, -m)
        return r.translated(0, int(self.reveal_shift))

    def place_content(self) -> None:
        if self.content is not None:
            self.content.setGeometry(self.content_rect())

    def sizeHint(self):
        lay = self.content.layout()
        s = lay.sizeHint() if lay else QSize(120, 60)
        extra = self.PAD_L + self.PAD_R + 2 * (self.border + self.pad)
        return QSize(s.width() + extra, s.height() + extra)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.place_content()

    # -- 绘制 ----------------------------------------------------------------
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        b = self.body_rect()

        # 1) 零模糊纯黑硬阴影
        sh = 0 if self.pressed else int(round(self.shadow))
        if sh > 0:
            p.fillRect(b.translated(sh, sh), BLACK)

        # 2) 底色 + SVG 等价纹理
        p.fillRect(b, self.bg)
        paint_texture(p, b, self.texture)
        self.draw_deco(p, b)

        # 3) 纯黑实线边框（笔宽居中，内缩半个笔宽）
        pen = QPen(BLACK, self.border)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        half = self.border / 2.0
        p.drawRect(QRectF(b).adjusted(half, half, -half, -half))

        # 4) 键盘焦点环（虚线，非模糊）
        if self.focus_ring:
            fp = QPen(QBrush(QColor('#FF1493')), 3, Qt.PenStyle.DashLine)
            p.setPen(fp)
            p.drawRect(QRectF(b).adjusted(-6, -6, 6, 6))
        p.end()

    def draw_deco(self, p: QPainter, b: QRect) -> None:
        """内联 SVG 装饰的 Qt 等价物：几何图形，纯色填充 + 纯黑描边。"""
        if not self.deco:
            return
        x, y = b.right() - 58, b.top() + 12
        r = QRect(x, y, 48, 48)
        p.setPen(QPen(BLACK, 3))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = QColor

        if self.deco == 'circle':
            p.setBrush(QBrush(c('#FFE135')))
            p.drawEllipse(QRectF(r))
            p.drawLine(r.center().x(), r.top() + 8, r.center().x(), r.bottom() - 8)
            p.drawLine(r.left() + 8, r.center().y(), r.right() - 8, r.center().y())
        elif self.deco == 'cross':
            p.setBrush(QBrush(c('#FF1493')))
            p.drawRect(r.left() + 16, r.top(), 16, 48)
            p.drawRect(r.left(), r.top() + 16, 48, 16)
        elif self.deco == 'triangle':
            p.setBrush(QBrush(c('#FFE135')))
            p.drawPolygon(QPolygon([QPoint(r.center().x(), r.top()),
                                    QPoint(r.right(), r.bottom()),
                                    QPoint(r.left(), r.bottom())]))
        elif self.deco == 'dots':
            for dx, dy, col in ((12, 12, '#FFE135'), (36, 12, '#00BFFF'), (24, 36, '#A3E635')):
                p.setBrush(QBrush(c(col)))
                p.drawEllipse(QRectF(r.left() + dx - 9, r.top() + dy - 9, 18, 18))
        elif self.deco == 'bolt':
            p.setBrush(QBrush(c('#FFE135')))
            p.drawPolygon(QPolygon([
                QPoint(r.left() + 28, r.top()), QPoint(r.left() + 6, r.top() + 27),
                QPoint(r.left() + 22, r.top() + 27), QPoint(r.left() + 14, r.bottom()),
                QPoint(r.left() + 42, r.top() + 21), QPoint(r.left() + 25, r.top() + 21),
            ]))
        else:  # star
            pts = []
            for i in range(10):
                ang = -3.14159 / 2 + i * 3.14159 / 5
                rad = 23 if i % 2 == 0 else 10
                pts.append(QPoint(int(r.center().x() + rad * math.cos(ang)),
                                  int(r.center().y() + rad * math.sin(ang))))
            p.setBrush(QBrush(c('#FFE135')))
            p.drawPolygon(QPolygon(pts))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    # -- 交互 ----------------------------------------------------------------
    def animate_to(self, lift: float, shadow: float) -> None:
        if REDUCED:
            self.lift, self.shadow = lift, shadow
            self.place_content()
            self.update()
            return
        a = QVariantAnimation(self)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setDuration(160)
        a.setEasingCurve(QEasingCurve.Type.OutQuad)
        s_lift, s_shadow = self.lift, self.shadow

        def on_val(t):
            t = float(t)
            self.lift = s_lift + (lift - s_lift) * t
            self.shadow = s_shadow + (shadow - s_shadow) * t
            self.place_content()
            self.update()

        a.valueChanged.connect(on_val)
        a.finished.connect(lambda: self._anims.remove(a) if a in self._anims else None)
        self._anims.append(a)
        a.start()

    def enterEvent(self, e) -> None:
        if self.interactive:
            self.animate_to(4, self.base_shadow + 5)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        if self.interactive:
            self.pressed = False
            self.press = 0
            self.animate_to(0, self.base_shadow)
            self.place_content()
            self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:
        if self.interactive and e.button() == Qt.MouseButton.LeftButton:
            self.pressed = True
            self.press = 3
            self.place_content()
            self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if self.interactive and self.pressed:
            self.pressed = False
            self.press = 0
            self.place_content()
            self.update()
            if self.rect().contains(e.position().toPoint()):
                self.clicked.emit()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:
        if self.interactive and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.pressed = True
            self.press = 3
            self.place_content()
            self.update()
            self.clicked.emit()
            QTimer.singleShot(130, self._release_press)
        else:
            super().keyPressEvent(e)

    def _release_press(self) -> None:
        self.pressed = False
        self.press = 0
        self.place_content()
        self.update()

    def focusInEvent(self, e) -> None:
        self.focus_ring = True
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e) -> None:
        self.focus_ring = False
        self.update()
        super().focusOutEvent(e)

    # -- 滚动揭示（IntersectionObserver 等价物）------------------------------
    def reveal(self) -> None:
        """可见性立即落到终态，动画仅负责内容上滑（22px -> 0）。

        这样即使动画时钟没有推进（离屏渲染、极低帧率、远程桌面），
        卡片也不会停留在全透明状态而留下空白。
        """
        if self.revealed:
            return
        self.revealed = True
        self.reveal_shift = 0.0
        if hasattr(self, 'opacity'):
            self.opacity.setOpacity(1.0)
        self.place_content()
        self.update()
        if REDUCED:
            return
        a = QVariantAnimation(self)
        a.setStartValue(22.0)
        a.setEndValue(0.0)
        a.setDuration(520)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)

        def on_val(v):
            self.reveal_shift = float(v)
            self.place_content()
            self.update()

        def done():
            self.reveal_shift = 0.0
            self.opacity.setOpacity(1.0)
            self.place_content()
            self.update()
            if a in self._anims:
                self._anims.remove(a)

        a.valueChanged.connect(on_val)
        a.finished.connect(done)
        self._anims.append(a)
        a.start()


class Chip(BrutalCard):
    def __init__(self, text: str, tone: str = 'white', bg: QColor | None = None,
                 small: bool = True, fg: QColor | None = None, parent=None):
        super().__init__(tone=tone, border=2, shadow=3, pad=0, bg=bg, parent=parent)
        # 紧凑标签用更小的留白，避免 30px 高度下正文被裁切
        self.PAD_L, self.PAD_R = 3, 6
        self.setFixedHeight(30 if small else 36)
        lay = QHBoxLayout(self.content)
        lay.setContentsMargins(7, 1, 7, 1)
        lab = label(text, 7.5 if small else 9, bold=True, kind='mono',
                    color=(fg or INK), wrap=False)
        lay.addWidget(lab)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class BrutalButton(BrutalCard):
    def __init__(self, text: str, tone: str = 'white', arrow: str = '',
                 small: bool = False, parent=None):
        # 按钮用饱和主色（卡片才用淡色底），白字在粉/紫上才有对比度
        super().__init__(tone=tone, border=3, shadow=5, interactive=True,
                         pad=0, bg=TONES[tone][0], parent=parent)
        self.PAD_L, self.PAD_R = 5, 10
        self.setFixedHeight(40 if small else 50)
        lay = QHBoxLayout(self.content)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(8)
        fg = WHITE if tone in ('pink', 'purple') else INK
        lay.addWidget(label(text, 9 if small else 10.5, bold=True,
                            kind='display', color=fg, wrap=False))
        if arrow:
            lay.addWidget(label(arrow, 11 if small else 13, bold=True,
                                kind='mono', color=fg, wrap=False))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class BrutalBar(QWidget):
    """技能进度条：白底 + 2px 黑边 + 3px 硬阴影 + 纯色斜条纹填充。"""

    def __init__(self, tone: str, target: int, pct_label: QLabel, parent=None):
        super().__init__(parent)
        self.main = TONES[tone][0]
        self.target = float(target)
        # 终态优先：动画只做「从 0 回放到目标」的视觉过程，
        # 任何环境下进度条都不会因为动画未推进而停在空条
        self.value = self.target
        self._started = False
        self.pct_label = pct_label
        self.setFixedHeight(20)
        self._anims: list = []
        self.pct_label.setText(f'{int(self.value)}%')

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        b = QRect(0, 0, max(30, self.width() - 3), max(12, self.height() - 3))
        p.fillRect(b.translated(3, 3), BLACK)
        p.fillRect(b, WHITE)
        fill_w = int((b.width() - 4) * self.value / 100.0)
        if fill_w > 0:
            fill = QRect(b.left() + 2, b.top() + 2, fill_w, b.height() - 4)
            p.fillRect(fill, self.main)
            paint_texture(p, fill, 'stripes')
            p.setPen(QPen(BLACK, 2))
            p.drawLine(fill.right(), fill.top(), fill.right(), fill.bottom())
        pen = QPen(BLACK, 2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(b).adjusted(1, 1, -1, -1))
        p.end()

    def animate(self) -> None:
        if REDUCED or self._started:
            self.value = self.target
            self.pct_label.setText(f'{int(self.value)}%')
            self.update()
            return
        self._started = True
        a = QVariantAnimation(self)
        a.setStartValue(0.0)
        a.setEndValue(self.target)
        a.setDuration(1100)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)

        def on_val(v):
            self.value = float(v)
            self.pct_label.setText(f'{int(self.value)}%')
            self.update()

        def done():
            a.stop()
            self.value = self.target
            self.pct_label.setText(f'{int(self.value)}%')
            self.update()
            if a in self._anims:
                self._anims.remove(a)

        a.valueChanged.connect(on_val)
        a.finished.connect(done)
        self._anims.append(a)
        a.start()
        # 兜底：动画时钟未推进时，超时后仍落到终态
        QTimer.singleShot(1250, done)


# ---------------------------------------------------------------------------
# 区块容器 / 插画 / 装饰
# ---------------------------------------------------------------------------
class Section(QFrame):
    def __init__(self, bg: QColor = PAGE, texture: str = '',
                 bottom_border: bool = True, vpad: int = 56, parent=None):
        super().__init__(parent)
        self.bg = bg
        self.texture = texture
        self.bottom_border = bottom_border
        self.setFrameStyle(QFrame.Shape.NoFrame)
        # 用 objectName 限定作用域，否则 background 会继承到所有子控件
        self.setObjectName('candySection')
        self.setStyleSheet(f'QWidget#candySection{{background:{bg.name()};border:none;}}')
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(48, vpad, 48, vpad)
        self.lay.setSpacing(0)
        self.inner = QWidget()
        self.lay.addWidget(self.inner)
        self.vbox = QVBoxLayout(self.inner)
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.setSpacing(16)

    def add(self, w: QWidget):
        self.vbox.addWidget(w)
        return w

    def paintEvent(self, e) -> None:
        # 自己填底色，不依赖 QFrame 的样式表背景，保证任何平台一致
        p = QPainter(self)
        p.fillRect(self.rect(), self.bg)
        paint_texture(p, self.rect(), self.texture)
        if self.bottom_border:
            p.fillRect(QRect(0, self.height() - 4, self.width(), 4), BLACK)
        p.end()


class Dot(QWidget):
    def __init__(self, tone: str, parent=None):
        super().__init__(parent)
        self.color = TONES[tone][0]
        self.setFixedSize(24, 24)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(1, 1, 18, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(BLACK))
        p.drawEllipse(r.translated(3, 3))
        p.setPen(QPen(BLACK, 2.5))
        p.setBrush(QBrush(self.color))
        p.drawEllipse(r)
        p.end()


class CandyArt(QWidget):
    """Hero 插画：用 QPainter 画糖果角色（等价网页版的内联 SVG）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(320)
        self.setMaximumHeight(420)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), WHITE)
        paint_texture(p, self.rect(), 'dots')
        s = min(w / 400.0, h / 340.0)
        p.save()
        p.translate((w - 400 * s) / 2, (h - 340 * s) / 2)
        p.scale(s, s)
        pen = QPen(BLACK, 3.5)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        # 太阳
        p.setPen(QPen(QBrush(BLACK), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for a in range(0, 360, 45):
            rad = math.radians(a)
            p.drawLine(int(74 + 34 * math.cos(rad)), int(76 + 34 * math.sin(rad)),
                       int(74 + 43 * math.cos(rad)), int(76 + 43 * math.sin(rad)))
        p.setPen(pen)
        p.setBrush(QBrush(QColor('#FFE135')))
        p.drawEllipse(QRectF(47, 49, 54, 54))

        # 云
        p.setBrush(QBrush(QColor('#CFEEFF')))
        p.drawRoundedRect(QRectF(262, 46, 96, 34), 16, 16)
        p.drawEllipse(QRectF(282, 30, 36, 36))

        # 身体（斜条纹）
        body = QRectF(118, 184, 164, 122)
        p.setBrush(QBrush(QColor('#FFE135')))
        p.drawRect(body)
        paint_texture(p, QRect(int(body.left()), int(body.top()),
                               int(body.width()), int(body.height())), 'stripes')
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(body)

        # 脸 + 帽子
        p.setBrush(QBrush(QColor('#FFE135')))
        p.drawEllipse(QRectF(124, 76, 152, 152))
        p.setBrush(QBrush(QColor('#FF1493')))
        p.drawPie(QRectF(124, 76, 152, 152), 0, 180 * 16)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(124, 76, 152, 152))

        # 眼睛 / 腮红 / 笑
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(BLACK))
        p.drawEllipse(QRectF(168, 142, 17, 17))
        p.drawEllipse(QRectF(215, 142, 17, 17))
        p.setPen(QPen(BLACK, 2.5))
        p.setBrush(QBrush(QColor('#FF6B35')))
        p.drawEllipse(QRectF(146, 166, 20, 20))
        p.drawEllipse(QRectF(234, 166, 20, 20))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QBrush(BLACK), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(178, 168, 44, 36), 180 * 16, 180 * 16)

        # 棒棒糖
        p.setPen(QPen(QBrush(BLACK), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(118, 226, 76, 258)
        p.setPen(pen)
        p.setBrush(QBrush(QColor('#00BFFF')))
        p.drawEllipse(QRectF(42, 242, 48, 48))
        p.setBrush(QBrush(QColor('#A3E635')))
        p.drawRect(QRectF(302, 246, 30, 30))

        # 地面
        p.setPen(QPen(BLACK, 4))
        p.drawLine(0, 306, 400, 306)
        p.restore()
        p.end()


class BentoGrid(QWidget):
    """不等宽项目网格，宽屏 4 列 / 窄屏 2 列 / 极窄 1 列。"""

    def __init__(self, cards: list, parent=None):
        super().__init__(parent)
        self.cards = cards
        self.grid = QGridLayout(self)
        self.grid.setSpacing(20)
        self.mode = None
        self.relayout(True)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.relayout(self.width() >= 860)

    def relayout(self, wide: bool) -> None:
        mode = 'wide' if wide else 'narrow'
        if mode == self.mode:
            return
        self.mode = mode
        for c in self.cards:
            self.grid.removeWidget(c)
        if wide:
            spec = [(0, 0, 2, 2), (0, 2, 1, 2), (1, 2, 1, 1),
                    (1, 3, 1, 1), (2, 0, 1, 2), (2, 2, 1, 2)]
        else:
            spec = [(0, 0, 1, 2), (1, 0, 1, 2), (2, 0, 1, 1),
                    (2, 1, 1, 1), (3, 0, 1, 2), (4, 0, 1, 2)]
        for c, (r, col, rs, cs) in zip(self.cards, spec):
            self.grid.addWidget(c, r, col, rs, cs)
        for i in range(3 if wide else 5):
            self.grid.setRowMinimumHeight(i, 200 if i < 3 else 190)


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class CandyHouseWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # 启动器直接 new 窗口时不会走 main()，这里补一次纹理初始化
        if not TEX:
            init_textures()
        self.setWindowTitle('糖果屋 · Candy House / PySide6')
        self.sections: dict[str, QWidget] = {}
        self.animated_cards: list[BrutalCard] = []
        self._keep: list = []

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        # 顶部滚动进度（等价于 fixed 顶部的粉色条）
        self.progress_track = QWidget()
        self.progress_track.setFixedHeight(5)
        lay = QHBoxLayout(self.progress_track)
        lay.setContentsMargins(0, 0, 0, 0)
        self.progress_fill = QWidget()
        self.progress_fill.setStyleSheet('background:#FF1493;')
        self.progress_fill.setFixedWidth(0)
        lay.addWidget(self.progress_fill)
        lay.addStretch(1)
        root.addWidget(self.progress_track)

        # Sticky 导航：放在 QScrollArea 之外，因此不会随内容滚动
        root.addWidget(self.build_nav())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameStyle(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            'QScrollArea{background:#F5F5F0;border:none;}'
            'QScrollBar:vertical{background:#F5F5F0;width:14px;border-left:3px solid #000;margin:0;}'
            'QScrollBar::handle:vertical{background:#FF1493;border:2px solid #000;min-height:40px;}'
            'QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}'
        )
        root.addWidget(self.scroll, 1)

        self.canvas = QWidget()
        self.canvas.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.canvas.setObjectName('candyCanvas')
        self.canvas.setStyleSheet('QWidget#candyCanvas{background:#F5F5F0;}')
        self.canvas_layout = QVBoxLayout(self.canvas)
        self.canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.canvas_layout.setSpacing(0)
        self.scroll.setWidget(self.canvas)

        self.build_hero()
        self.build_skills()
        self.build_projects()
        self.build_experience()
        self.build_about()
        self.build_contact()
        self.build_footer()

        self.scroll.verticalScrollBar().valueChanged.connect(self.on_scroll)
        QTimer.singleShot(0, self.on_scroll)

    # -- 小工具 --------------------------------------------------------------
    def add_section(self, key: str, sec: Section) -> Section:
        self.sections[key] = sec
        self.canvas_layout.addWidget(sec)
        return sec

    def go(self, key: str) -> None:
        target = self.sections.get(key)
        if target is None:
            return
        y = max(0, target.y() - 86)
        sb = self.scroll.verticalScrollBar()
        if REDUCED:
            sb.setValue(y)
            return
        a = QVariantAnimation(self)
        a.setStartValue(float(sb.value()))
        a.setEndValue(float(y))
        a.setDuration(420)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.valueChanged.connect(lambda v: sb.setValue(int(float(v))))
        a.finished.connect(lambda: self._keep.remove(a) if a in self._keep else None)
        self._keep.append(a)
        a.start()

    def on_scroll(self, *_args) -> None:
        if not self.isVisible():
            return
        # IntersectionObserver 等价：用全局坐标判断卡片是否进入 viewport
        vp = self.scroll.viewport()
        vp_top = vp.mapToGlobal(QPoint(0, 0)).y()
        vh = vp.height()
        for c in self.animated_cards:
            if c.revealed:
                continue
            top = c.mapToGlobal(QPoint(0, 0)).y() - vp_top
            # 已滚过视口的卡片也直接显示：快速拖动滚动条时不会留下空白
            if top < vh - 40:
                c.reveal()
                bar = c.findChild(BrutalBar)
                if bar is not None:
                    bar.animate()
        sb = self.scroll.verticalScrollBar()
        ratio = sb.value() / max(1, sb.maximum())
        self.progress_fill.setFixedWidth(int(self.progress_track.width() * ratio))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        QTimer.singleShot(0, self.on_scroll)

    # -- 1 / 导航 ------------------------------------------------------------
    def build_nav(self) -> QWidget:
        nav = QWidget()
        nav.setFixedHeight(76)
        nav.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        nav.setObjectName('candyNav')
        nav.setStyleSheet('QWidget#candyNav{background:#F5F5F0;}')
        lay = QHBoxLayout(nav)
        lay.setContentsMargins(48, 0, 48, 0)
        lay.setSpacing(8)

        mark = BrutalCard(tone='pink', border=2, shadow=3, pad=0,
                          bg=TONES['pink'][0])
        mark.PAD_L, mark.PAD_R = 3, 6
        mark.setFixedSize(38, 38)
        ml = QVBoxLayout(mark.content)
        ml.setContentsMargins(0, 0, 0, 0)
        t = label('糖', 12, bold=True, kind='display', color=WHITE, center=True)
        ml.addWidget(t)
        lay.addWidget(mark)
        lay.addWidget(label('糖果屋', 12, bold=True, kind='display', wrap=False))
        lay.addStretch(1)

        for text, key in (('技能', 'skills'), ('项目', 'projects'), ('经历', 'experience'),
                          ('关于', 'about'), ('联系', 'contact')):
            btn = BrutalButton(text, tone='yellow', small=True)
            btn.clicked.connect(lambda k=key: self.go(k))
            lay.addWidget(btn)
        cta = BrutalButton('打个招呼', tone='pink', arrow='→', small=True)
        cta.clicked.connect(lambda: self.go('contact'))
        lay.addWidget(cta)

        # 底部 4px 纯黑实线
        line = QWidget(nav)
        line.setStyleSheet('background:#000000;')
        line.setGeometry(0, 72, 4000, 4)
        return nav

    # -- 2 / Hero ------------------------------------------------------------
    def build_hero(self) -> None:
        sec = Section(bg=PAGE, texture='dots+noise', vpad=64)
        self.add_section('hero', sec)
        row = QHBoxLayout()
        row.setSpacing(40)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setSpacing(14)
        lv.setContentsMargins(0, 0, 0, 0)

        lv.addWidget(Chip('● 在线 · 开放合作中', bg=TONES['green'][1]))
        lv.addWidget(label('你好，我是', 36, bold=True, kind='display', wrap=False))

        name = BrutalCard(tone='pink', border=4, shadow=8, pad=2,
                          bg=TONES['pink'][0])
        name.setFixedHeight(100)
        nl = QVBoxLayout(name.content)
        nl.setContentsMargins(4, 0, 4, 0)
        nl.addWidget(label('林小糖', 42, bold=True, kind='display', color=WHITE, center=True))
        name.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        lv.addWidget(name)

        roles = QHBoxLayout()
        roles.setSpacing(10)
        for t, tone in (('前端工程师', 'blue'), ('UI 设计爱好者', 'pink'), ('开源贡献者', 'green')):
            c = Chip(t, bg=TONES[tone][1])
            roles.addWidget(c)
        roles.addStretch(1)
        lv.addLayout(roles)

        bio = label('一个用代码画画的深圳开发者。沉迷于把设计稿像素级还原成可交互界面，'
                    '热衷于探索 Web 动效与 3D 交互的边界。糖果色的代码世界，欢迎光临。', 10)
        bio.setMaximumWidth(560)
        lv.addWidget(bio)

        actions = QHBoxLayout()
        actions.setSpacing(14)
        b1 = BrutalButton('看我的作品', tone='pink', arrow='→')
        b1.clicked.connect(lambda: self.go('projects'))
        b2 = BrutalButton('联系我', tone='white', arrow='↗')
        b2.clicked.connect(lambda: self.go('contact'))
        actions.addWidget(b1)
        actions.addWidget(b2)
        actions.addStretch(1)
        lv.addLayout(actions)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        for num, cap in (('4+', '年开发经验'), ('20+', '个上线项目'), ('3K+', 'GitHub Stars')):
            s = BrutalCard(tone='white', border=2, shadow=3, pad=8)
            s.setMinimumHeight(74)
            sv = QVBoxLayout(s.content)
            sv.setSpacing(0)
            sv.addWidget(label(num, 17, bold=True, kind='display', wrap=False))
            sv.addWidget(label(cap, 7.5, bold=True, kind='mono', wrap=False))
            stats.addWidget(s)
        lv.addLayout(stats)
        row.addWidget(left, 6)

        art = BrutalCard(tone='blue', border=4, shadow=11, pad=8, deco='star')
        art.setMinimumWidth(360)
        av = QVBoxLayout(art.content)
        av.setSpacing(8)
        av.addWidget(CandyArt(), 1)
        cap = Chip('CANDY HOUSE / 001  ·  EST. 2020 ✦ SHENZHEN', bg=TONES['yellow'][0])
        av.addWidget(cap)
        row.addWidget(art, 5)
        sec.add(row_wrap(row))

    # -- 3 / 技能 ------------------------------------------------------------
    def build_skills(self) -> None:
        sec = Section()
        self.add_section('skills', sec)
        sec.add(Chip('⚙ 01 / 技术栈', bg=TONES['yellow'][0]))
        sec.add(label('这些是我每天在用的 工具和语言', 24, bold=True, kind='display'))

        grid = QGridLayout()
        grid.setSpacing(20)
        data = [
            ('React / Next.js', '精通 · 4 年', 92, 'blue', 'R'),
            ('TypeScript', '精通 · 3.5 年', 88, 'yellow', 'TS'),
            ('Vue / Nuxt', '熟练 · 3 年', 82, 'green', 'V'),
            ('CSS / 设计系统', '精通 · 4 年', 90, 'pink', 'CSS'),
            ('动效 & 3D Web', '熟练 · 2.5 年', 75, 'purple', '3D'),
            ('Node.js / 全栈', '掌握 · 2 年', 68, 'orange', 'N'),
        ]
        for i, (name, level, val, tone, icon) in enumerate(data):
            c = BrutalCard(tone=tone, animated=True)
            c.setMinimumHeight(176)
            v = QVBoxLayout(c.content)
            v.setSpacing(6)
            top = QHBoxLayout()
            ic = Chip(icon, bg=TONES[tone][0], small=False)
            ic.setFixedWidth(52)
            top.addWidget(ic)
            top.addStretch(1)
            pct = label('0%', 13, bold=True, kind='display', wrap=False)
            top.addWidget(pct)
            v.addLayout(top)
            v.addWidget(label(name, 12, bold=True, kind='display'))
            v.addWidget(label(level, 7.5, bold=True, kind='mono'))
            v.addStretch(1)
            bar = BrutalBar(tone, val, pct)
            v.addWidget(bar)
            grid.addWidget(c, i // 3, i % 3)
            self.animated_cards.append(c)
        sec.add(grid_wrap(grid))
        sec.add(Chip('// 进度条不是 KPI，只是「这周我又在折腾什么」的可视化 ✦'))

    # -- 4 / 项目 ------------------------------------------------------------
    def build_projects(self) -> None:
        sec = Section()
        self.add_section('projects', sec)
        sec.add(Chip('✦ 02 / 项目作品', bg=TONES['yellow'][0]))
        sec.add(label('用心打磨的 每一个作品', 24, bold=True, kind='display'))

        def project(title, desc, tag, tone, deco, tags, featured=False):
            c = BrutalCard(tone=tone, animated=True, deco=deco,
                           texture='dots' if featured else '')
            c.setMinimumHeight(200 if featured else 190)
            v = QVBoxLayout(c.content)
            v.setSpacing(8)
            v.addWidget(Chip(tag))
            v.addWidget(label(title, 18 if featured else 13, bold=True, kind='display'))
            d = label(desc, 9.5)
            d.setMaximumWidth(520 if featured else 360)
            v.addWidget(d)
            v.addStretch(1)
            foot = QHBoxLayout()
            foot.setSpacing(6)
            for t in tags:
                foot.addWidget(Chip(t))
            foot.addStretch(1)
            link = BrutalButton('查看' if not featured else '查看项目',
                                tone='white', arrow='↗', small=True)
            link.clicked.connect(lambda: self.go('contact'))
            foot.addWidget(link)
            v.addLayout(foot)
            self.animated_cards.append(c)
            return c

        cards = [
            project('糖果屋 · 个人网站',
                    'Neo-Brutalism 风格的个人作品集。厚边框、偏移阴影、饱和色块——'
                    '用糖果美学展示技术栈和项目经历，纯单文件实现，零框架依赖。',
                    '★ 主推项目 / 2026', 'yellow', 'star',
                    ['HTML', 'CSS', 'JS', 'A11y'], featured=True),
            project('MarkFlow', '实时协作 Markdown 编辑器：多人光标、版本回溯、离线草稿。',
                    'WEB 应用', 'pink', 'circle', ['React', 'CRDT']),
            project('天气罐子', '把每天的天气装进一颗糖果罐，画会动的云。',
                    '小程序', 'blue', 'triangle', ['Skyline']),
            project('Color-X', '一条命令生成整套设计 Token。',
                    '开源工具', 'green', 'cross', ['CLI']),
            project('粒子画布', 'Three.js 实时粒子生成器，把鼠标轨迹变成小型烟花。',
                    '3D 交互', 'purple', 'dots', ['Three.js', 'WebGL']),
            project('Neko UI', '40+ 组件的糖果风组件库，带完整键盘导航与无障碍语义。',
                    '组件库', 'orange', 'bolt', ['React', 'a11y']),
        ]
        sec.add(BentoGrid(cards))

    # -- 5 / 经历 ------------------------------------------------------------
    def build_experience(self) -> None:
        sec = Section()
        self.add_section('experience', sec)
        sec.add(Chip('⏳ 03 / 工作经历', bg=TONES['yellow'][0]))
        sec.add(label('一路走来 踩过的坑 与成长', 24, bold=True, kind='display'))

        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setSpacing(18)
        grid.setColumnMinimumWidth(0, 190)
        grid.setColumnStretch(0, 0)   # 左列固定 190，竖线才能对齐圆点
        grid.setColumnStretch(1, 1)
        rows = [
            ('2024 — 至今', '高级前端工程师', '某科技公司 · 深圳',
             '主导设计系统重构与组件库建设，推动 Web 动效与 3D 交互在业务场景中落地，'
             '负责前端架构设计与性能优化。', 'pink', ['React', 'Next.js', '设计系统']),
            ('2022 — 2024', '前端工程师', '某互联网公司 · 深圳',
             '负责多个 B 端产品前端开发，参与从 0 到 1 的中台项目，深耕 TypeScript 与 Vue 生态。',
             'blue', ['Vue', 'TypeScript', '微前端']),
            ('2020 — 2022', '计算机科学 · 本科', '深圳大学',
             '主修计算机科学与技术，参与校园项目与黑客松，开始系统学习前端开发。',
             'green', ['CS 基础', '算法', '开源']),
        ]
        for i, (period, title, sub, desc, tone, tags) in enumerate(rows):
            left = QWidget()
            hl = QHBoxLayout(left)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addStretch(1)
            hl.addWidget(label(period, 8, bold=True, kind='mono', wrap=False))
            hl.addWidget(Dot(tone))
            grid.addWidget(left, i, 0)

            c = BrutalCard(tone=tone, animated=True)
            c.setMinimumHeight(150)
            v = QVBoxLayout(c.content)
            v.setSpacing(5)
            v.addWidget(label(title, 13, bold=True, kind='display'))
            v.addWidget(label(sub, 7.5, bold=True, kind='mono'))
            v.addWidget(label(desc, 9.5))
            tl = QHBoxLayout()
            tl.setSpacing(6)
            for t in tags:
                tl.addWidget(Chip(t))
            tl.addStretch(1)
            v.addLayout(tl)
            grid.addWidget(c, i, 1)
            self.animated_cards.append(c)

        line = QWidget(holder)
        line.setStyleSheet('background:#000000;')
        line.setGeometry(176, 8, 4, 3000)
        line.lower()
        sec.add(holder)

    # -- 6 / 关于 ------------------------------------------------------------
    def build_about(self) -> None:
        sec = Section()
        self.add_section('about', sec)
        sec.add(Chip('✿ 04 / 关于我', bg=TONES['yellow'][0]))
        sec.add(label('除了写代码，我还是个怎样的人', 24, bold=True, kind='display'))

        row = QHBoxLayout()
        row.setSpacing(20)
        text = BrutalCard(tone='white', animated=True)
        text.setMinimumHeight(300)
        tv = QVBoxLayout(text.content)
        tv.setSpacing(10)
        for para in (
            '我住在深圳，一个从不熄灯的年轻城市。白天写前端、调动效、和设计师争论 1px 的对齐；'
            '晚上写博客、做开源、偶尔打打游戏。',
            '我相信好的界面应该像糖果——让人看了就想点。Neo-Brutalism 是我的审美语言，'
            '因为它诚实：粗边框告诉你「我就是这样」，偏移阴影说「我有深度」。',
            '如果你也在做有意思的事情，欢迎来戳，我在线的时候回得很快。',
        ):
            tv.addWidget(label(para, 9.5))
        tv.addStretch(1)
        tv.addWidget(Chip('林小糖 / CANDY HOUSE, 深圳', bg=TONES['pink'][1]))
        self.animated_cards.append(text)
        row.addWidget(text, 1)

        right = QGridLayout()
        right.setSpacing(20)
        cards = [
            ('01', '开源爱好者', '维护 3 个开源项目，累计 3K+ Stars。', 'yellow'),
            ('02', '设计敏感', '能实现设计稿，也能反向输出设计建议。', 'pink'),
            ('03', '技术写作', '持续输出前端文章，累计阅读 50 万+。', 'blue'),
            ('04', '终身学习者', '最近在探索 Rust + WASM 的可能性。', 'green'),
        ]
        for i, (n, t, d, tone) in enumerate(cards):
            c = BrutalCard(tone=tone, animated=True)
            c.setMinimumHeight(140)
            v = QVBoxLayout(c.content)
            v.setSpacing(4)
            v.addWidget(label(n, 18, bold=True, kind='display', wrap=False))
            v.addWidget(label(t, 11, bold=True, kind='display'))
            v.addWidget(label(d, 9))
            right.addWidget(c, i // 2, i % 2)
            self.animated_cards.append(c)
        row.addLayout(right, 1)
        sec.add(row_wrap(row))

    # -- 7 / 黄底 CTA --------------------------------------------------------
    def build_contact(self) -> None:
        sec = Section(bg=TONES['yellow'][0], texture='stripes+noise',
                      vpad=72, bottom_border=True)
        self.add_section('contact', sec)
        chip = Chip('05 / 联系方式')
        sec.add(chip)
        sec.vbox.setAlignment(chip, Qt.AlignmentFlag.AlignHCenter)

        title_row = QHBoxLayout()
        title_row.setSpacing(4)
        title_row.addStretch(1)
        title_row.addWidget(label('来一颗', 30, bold=True, kind='display', wrap=False))
        box = BrutalCard(tone='white', border=4, shadow=5, pad=2)
        box.setFixedHeight(80)
        bl = QVBoxLayout(box.content)
        bl.addWidget(label('糖果', 30, bold=True, kind='display', center=True, wrap=False))
        title_row.addWidget(box)
        title_row.addWidget(label('吗？', 30, bold=True, kind='display', wrap=False))
        title_row.addStretch(1)
        sec.add(row_wrap(title_row))

        desc = label('无论是合作项目、技术交流，还是想聊聊 Neo-Brutalism 和糖果色——'
                     '随时欢迎联系我。我在线的时候回得很快。', 10, center=True)
        desc.setMaximumWidth(620)
        # QVBoxLayout 不会自动为居中 QLabel 追加换行高度，预留两行避免第二行被裁
        desc.setMinimumHeight(64)
        sec.add(desc)
        sec.vbox.setAlignment(desc, Qt.AlignmentFlag.AlignHCenter)

        btns = QHBoxLayout()
        btns.setSpacing(14)
        btns.addStretch(1)
        for text, tone, url in (
            ('发邮件给我 ✉', 'pink', 'mailto:hello@candyhouse.dev'),
            ('GitHub ↗', 'blue', 'https://github.com'),
            ('掘金主页 ↗', 'white', 'https://juejin.cn'),
        ):
            btn = BrutalButton(text, tone=tone)
            btn.clicked.connect(lambda u=url: QDesktopServices.openUrl(QUrl(u)))
            btns.addWidget(btn)
        btns.addStretch(1)
        sec.add(row_wrap(btns))

        stamp = Chip('HELLO@CANDYHOUSE.DEV · 深圳 / 远程友好',
                     bg=INK, fg=WHITE)
        sec.add(stamp)
        sec.vbox.setAlignment(stamp, Qt.AlignmentFlag.AlignHCenter)

    # -- 8 / 黑底 Footer -----------------------------------------------------
    def build_footer(self) -> None:
        sec = Section(bg=DARK, vpad=52, bottom_border=False)
        sec.lay.setContentsMargins(48, 52, 48, 24)
        row = QHBoxLayout()
        row.setSpacing(40)

        col1 = QVBoxLayout()
        col1.setSpacing(12)
        col1.addWidget(label('糖  糖果屋', 13, bold=True, kind='display',
                             color=WHITE, wrap=False))
        fdesc = label('林小糖的个人作品集。用 Neo-Brutalism 的糖果色块记录'
                      '每一个项目、每一段成长。深圳 · 远程友好。', 9,
                      color=QColor('#E6E6E6'))
        fdesc.setMaximumWidth(320)
        col1.addWidget(fdesc)
        social = QHBoxLayout()
        social.setSpacing(8)
        for t, tone in (('GH', 'pink'), ('掘', 'yellow'), ('知', 'blue'),
                        ('@', 'green'), ('X', 'purple')):
            b = Chip(t, tone=tone)
            b.setFixedWidth(42)
            social.addWidget(b)
        social.addStretch(1)
        col1.addLayout(social)
        col1.addStretch(1)
        row.addLayout(col1, 3)

        for heading, items in (
            ('导航 / MENU', [('技能', 'skills'), ('项目', 'projects'),
                            ('经历', 'experience'), ('关于', 'about'), ('联系', 'contact')]),
            ('链接 / LINKS', [('GitHub ↗', None), ('掘金 ↗', None),
                             ('知乎 ↗', None), ('Email ↗', None)]),
        ):
            col = QVBoxLayout()
            col.setSpacing(6)
            col.addWidget(label(heading, 9, bold=True, kind='display',
                                color=TONES['yellow'][0], wrap=False))
            for txt, key in items:
                if key:
                    b = BrutalButton(txt, tone='white', small=True)
                    b.setFixedHeight(40)
                    b.clicked.connect(lambda k=key: self.go(k))
                else:
                    b = BrutalButton(txt, tone='white', small=True)
                    b.setFixedHeight(40)
                col.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
            col.addStretch(1)
            row.addLayout(col, 1)
        sec.add(row_wrap(row))

        line = QWidget()
        line.setFixedHeight(2)
        line.setStyleSheet('background:#FFFFFF;')
        sec.add(line)
        bottom = QHBoxLayout()
        bottom.addWidget(label('© 2026 糖果屋 · CANDY HOUSE', 7.5, bold=True,
                              kind='mono', color=QColor('#D0D0D0'), wrap=False))
        bottom.addStretch(1)
        bottom.addWidget(label('BUILT WITH QT / PYSDIE6 · NEO-BRUTALISM', 7.5,
                              bold=True, kind='mono', color=TONES['yellow'][0], wrap=False))
        sec.add(row_wrap(bottom))
        self.canvas_layout.addWidget(sec)


# 布局小工具：把 QLayout 包成一个 QWidget 供 Section.add 使用
def row_wrap(layout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    return w


def grid_wrap(layout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    return w


# ---------------------------------------------------------------------------
def main() -> int:
    argv = [a for a in sys.argv if a != '--no-motion']
    app = QApplication(argv)
    app.setStyle('Fusion')

    # 如果脚本同目录有 fonts/*.ttf|otf，就加载本地 Google Fonts 文件
    font_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
    if os.path.isdir(font_dir):
        for fn in os.listdir(font_dir):
            if fn.lower().endswith(('.ttf', '.otf')):
                QFontDatabase.addApplicationFont(os.path.join(font_dir, fn))

    if not TEX:
        init_textures()
    win = CandyHouseWindow()
    win.resize(1280, 860)
    win.show()
    return app.exec()


__all__ = ['CandyHouseWindow', 'main']


if __name__ == '__main__':
    sys.exit(main())
