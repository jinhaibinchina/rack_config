"""样式解析与 QPen / QBrush / QFont 复用缓存。

对齐 ``Designer/Core/element.py`` 的 ``str_to_color`` / ``set_opacity`` 语义，
以及 ``Designer/Core/scene_fast.py`` 的按 (ARGB, 线宽, 样式) 复用策略。
``painter.setPen/setBrush`` 是值拷贝，共享只读实例安全。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QPen

# 文本图元：边框 / 背景在文字度量之外预留的视图像素
TEXT_PAD_X = 8.0
TEXT_PAD_Y = 4.0

# 文本图元的默认字体族。旧 Core 的 ``text_element`` 恒用 ``QFont("Arial")``，
# 存量 page 的 ``style`` 里没有 ``font_family`` 键，缺省取这个值才能保证
# 1618 图元逐像素对拍与 JSON round-trip 完全不变。
FONT_FAMILY_DEFAULT = "Arial"

# 图元填充样式（对应 Qt Designer 属性面板的「填充样式」下拉 / Qt.BrushStyle）。
# 持久化**字符串键**，与 widgetType / path_fill_rule 同一口径：不写死枚举整数，
# 避免 Qt 版本变动导致数值漂移，存量 page 在缺 fill_style 键时一律兜底为 solid
# ——这正是旧引擎唯一的填充方式，保证存量渲染与 JSON round-trip 零改动。
FILL_STYLE_DEFAULT = "solid"

# 下拉项顺序：实心 → 密集点 → 线 / 网格 → 无填充（对齐截图里 Qt 属性编辑器的排列）
BRUSH_STYLE_KEYS: tuple[str, ...] = (
    "solid", "dense1", "dense2", "dense3", "dense4", "dense5", "dense6", "dense7",
    "hor", "ver", "cross", "bdiag", "fdiag", "diagcross", "none",
)

BRUSH_STYLE_LABELS: dict[str, str] = {
    "solid": "实心",
    "dense1": "密集点 1（最密）",
    "dense2": "密集点 2",
    "dense3": "密集点 3",
    "dense4": "密集点 4（50%）",
    "dense5": "密集点 5",
    "dense6": "密集点 6",
    "dense7": "密集点 7（最疏）",
    "hor": "横线",
    "ver": "竖线",
    "cross": "十字网格",
    "bdiag": "斜线 /",
    "fdiag": "斜线 \\",
    "diagcross": "斜向网格",
    "none": "无填充",
}

_BRUSH_STYLE_VALUES: dict[str, Qt.BrushStyle] = {
    "none": Qt.NoBrush,
    "solid": Qt.SolidPattern,
    "dense1": Qt.Dense1Pattern,
    "dense2": Qt.Dense2Pattern,
    "dense3": Qt.Dense3Pattern,
    "dense4": Qt.Dense4Pattern,
    "dense5": Qt.Dense5Pattern,
    "dense6": Qt.Dense6Pattern,
    "dense7": Qt.Dense7Pattern,
    "hor": Qt.HorPattern,
    "ver": Qt.VerPattern,
    "cross": Qt.CrossPattern,
    "bdiag": Qt.BDiagPattern,
    "fdiag": Qt.FDiagPattern,
    "diagcross": Qt.DiagCrossPattern,
}


def normalize_brush_style(value) -> str:
    """填充样式键兜底：缺失 / 未知值一律退回 ``solid``。

    存量 page 没有 ``fill_style`` 键，读出来即默认值，不需要把键补写回 JSON
    ——这是 round-trip 零改动的前提（同 :func:`normalize_font_family`）。
    """
    key = str(value or "").strip().lower()
    return key if key in _BRUSH_STYLE_VALUES else FILL_STYLE_DEFAULT


def brush_style_value(name) -> Qt.BrushStyle:
    return _BRUSH_STYLE_VALUES[normalize_brush_style(name)]


# 文本水平对齐（属性面板「对齐」下拉，对应 QPainter.drawText 的 alignment flag）。
# 存量页面和旧引擎的文本都是居中，JSON 里也没有 text_align 键，所以**读取侧**
# 兜底 center——这是存量渲染逐字节对拍与 round-trip 零改动的前提；而**新建**
# 文本由 g_scene.create_item 显式写 left，这才是用户要的「默认左对齐」。
TEXT_ALIGN_DEFAULT = "center"   # 缺字段兜底（存量）
TEXT_ALIGN_NEW = "left"         # 新建文本默认值

TEXT_ALIGN_KEYS: tuple[str, ...] = ("left", "center", "right")
TEXT_ALIGN_LABELS: dict[str, str] = {
    "left": "左对齐", "center": "居中", "right": "右对齐",
}
# 垂直方向恒居中（与旧 Qt.AlignCenter 等价），只切换水平对齐；
# 于是存量 center 分支的绘制与改动前逐像素一致。
_TEXT_ALIGN_FLAGS = {
    "left": Qt.AlignLeft | Qt.AlignVCenter,
    "center": Qt.AlignHCenter | Qt.AlignVCenter,
    "right": Qt.AlignRight | Qt.AlignVCenter,
}


def normalize_text_align(value) -> str:
    """对齐键兜底：缺失 / 未知值一律退回 ``center``（存量口径）。"""
    key = str(value or "").strip().lower()
    return key if key in _TEXT_ALIGN_FLAGS else TEXT_ALIGN_DEFAULT


def text_align_flags(name):
    return _TEXT_ALIGN_FLAGS[normalize_text_align(name)]


_CACHE_LIMIT = 512
_pen_cache: dict[tuple, QPen] = {}
_brush_cache: dict[tuple, QBrush] = {}
_dash_cache: dict[int, QPen] = {}
_font_cache: dict[tuple, QFont] = {}
# 字体族「可平滑缩放」判定与过滤后的候选族（字体库一次进程内基本不变）
_scalable_cache: dict[str, bool] = {}
_family_cache: tuple[str, ...] | None = None

HOVER_COLOR = QColor(14, 248, 236)
SELECT_COLOR = QColor(255, 0, 0)


def parse_color(value, default: str = "#000000") -> QColor:
    """支持 ``#rrggbb`` / ``#aarrggbb`` / ``r,g,b[,a]`` / 颜色名。"""
    if isinstance(value, QColor):
        return QColor(value)
    if not isinstance(value, str) or not value.strip():
        return QColor(default)
    text = value.strip()
    if text.startswith("#"):
        c = QColor(text)
        return c if c.isValid() else QColor(default)
    parts = [p.strip() for p in text.split(",")]
    if len(parts) in (3, 4) and all(p.lstrip("-").isdigit() for p in parts):
        nums = [int(p) for p in parts]
        c = QColor(*nums) if len(nums) == 4 else QColor(nums[0], nums[1], nums[2])
        return c if c.isValid() else QColor(default)
    c = QColor(text)
    return c if c.isValid() else QColor(default)


def color_str(c: QColor) -> str:
    """``QColor.name()`` 的 ``#rrggbb``，与 Core 的 ``color_to_str`` 一致。"""
    return c.name(QColor.HexRgb)


def _guard(cache: dict) -> None:
    if len(cache) > _CACHE_LIMIT:
        cache.clear()


def pen_for(color: QColor, width: float = 1.0, style=Qt.SolidLine) -> QPen:
    # PySide6 6.10 的 Qt.SolidLine 是 PenStyle 枚举，int(enum) 会抛
    # TypeError；而该异常若发生在 QGraphicsScene.render 的 C++ 绘制回调里，
    # 不会被传播，直接变成 access violation。枚举本身可哈希，直接用。
    key = (color.rgba(), float(width), style)
    pen = _pen_cache.get(key)
    if pen is None:
        pen = QPen(QColor(color), float(width), style)
        _guard(_pen_cache)
        _pen_cache[key] = pen
    return pen


def brush_for(color: QColor, style=Qt.SolidPattern) -> QBrush:
    """按 (颜色, 填充样式) 复用只读画刷。

    与 :func:`pen_for` 同理：PySide6 6.10 的 ``Qt.BrushStyle`` 是枚举，
    ``int(enum)`` 会抛 TypeError，而绘制回调里的异常不会被传播；枚举本身
    可哈希，直接进 key。默认 SolidPattern 与旧实现 ``QBrush(QColor(color))``
    完全等价，存量图元走这条路径渲染逐字节不变。
    """
    key = (color.rgba(), style)
    brush = _brush_cache.get(key)
    if brush is None:
        brush = QBrush(QColor(color), style)
        _guard(_brush_cache)
        _brush_cache[key] = brush
    return brush


def dashed_pen_for(color: QColor) -> QPen:
    """Core 的 ``create_pen_style``：宽 1、[8,4,2,4]、圆角端点。"""
    key = color.rgba()
    pen = _dash_cache.get(key)
    if pen is None:
        pen = QPen()
        pen.setColor(QColor(color))
        pen.setWidth(1)
        pen.setDashPattern([8, 4, 2, 4])
        pen.setStyle(Qt.CustomDashLine)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        _guard(_dash_cache)
        _dash_cache[key] = pen
    return pen


def normalize_font_family(value, default: str = FONT_FAMILY_DEFAULT) -> str:
    """字体族名兜底：空 / 非字符串一律退回 default。

    ``style.font_family`` 缺失（存量 page）时读出来的就是默认值，不需要把
    键补写进 JSON——这是 round-trip 零改动的前提。
    """
    text = str(value or "").strip()
    return text or default


def is_scalable_font_family(family: str) -> bool:
    """该字体族是否可平滑缩放（TrueType / OpenType）。

    Windows 自带一批 **GDI 位图字体**——``Terminal`` / ``Fixedsys`` /
    ``Modern`` / ``Roman`` / ``Script`` / ``System`` / ``Small Fonts`` /
    ``MS Serif`` / ``MS Sans Serif`` / ``Courier``——它们照样出现在
    ``QFontDatabase.families()`` 里，但 DirectWrite 没有对应字体文件：只要
    有人拿这个族去解析一次字体，Qt 就会打一条

        qt.qpa.fonts: DirectWrite: CreateFontFaceFromHDC() failed ... for
        QFontDef(Family="Terminal", pointsize=9, ...)

    属性面板的字体下拉用 ``Qt.FontRole`` 逐项**预览**，正好会触发它；位图
    字体本身也不支持缩放，用户选了改字号也不会变，所以下拉里干脆不提供。
    未安装的族同样返回 False，正好也是「不该出现在下拉里」那一类。
    结果带缓存：面板每次刷新都会把整库过一遍。
    """
    key = str(family or "").strip()
    if not key:
        return False
    cached = _scalable_cache.get(key)
    if cached is None:
        try:
            cached = bool(QFontDatabase.isSmoothlyScalable(key))
        except Exception:            # 没有 QGuiApplication / 平台不提供该接口
            cached = False
        _scalable_cache[key] = cached
    return cached


def filter_usable_families(families, is_scalable=None) -> list[str]:
    """从字体族列表里剔掉不可平滑缩放的位图字体。

    ``is_scalable`` 只给门禁打桩用（离屏 QPA 的字体库是空的，真实判定没法
    覆盖），默认走 :func:`is_scalable_font_family`。
    全部被剔掉时原样返回：宁可给出可能有告警的列表，也不要给用户一个空的
    字体下拉（真选不上字体反而更糟）。
    """
    probe = is_scalable or is_scalable_font_family
    items = [str(f) for f in (families or []) if str(f or "").strip()]
    kept = [f for f in items if probe(f)]
    return kept or items


def available_font_families(refresh: bool = False) -> list[str]:
    """属性面板字体下拉的候选族（已剔除 GDI 位图字体）。

    字体库一次进程内基本不变，这里缓存整张表；``refresh=True`` 强制重取
    （装完字体后刷新下拉用）。
    """
    global _family_cache
    if refresh or _family_cache is None:
        try:
            raw = list(QFontDatabase.families())
        except Exception:
            raw = []
        _family_cache = tuple(filter_usable_families(raw))
    return list(_family_cache)


def font_for(family: str, size: float, bold: bool = False) -> QFont:
    key = (family, float(size), bool(bold))
    font = _font_cache.get(key)
    if font is None:
        font = QFont(family, int(size))
        font.setBold(bold)
        _guard(_font_cache)
        _font_cache[key] = font
    return font


def text_metrics(text: str, font_size: float,
                 font_family: str = FONT_FAMILY_DEFAULT) -> tuple[float, float]:
    """量出文字在**视图像素**下的 (宽, 高)，供边框背景自适应使用。

    必须与 ``TextItem.paint`` 用同一份 ``font_for`` 字体，否则字号改完边框会
    和文字差一两像素。``font_family`` 缺省 ``Arial``（旧 Core 口径），换字体
    后文字宽高真的会变，所以量文字必须带上字体族一起算。
    多行文本按行累加行高、取最宽的一行；空串按一个空格量，
    避免得到 0 尺寸导致 ``set_page_size`` 直接拒绝。
    ``QFontMetricsF`` 与 QPainter 共享 QGuiApplication 的逻辑 DPI，离屏回归和
    真实窗口口径一致。
    """
    fm = QFontMetricsF(font_for(normalize_font_family(font_family),
                                font_size, True))
    lines = str(text if text else " ").split("\n")
    width = max((fm.horizontalAdvance(line) for line in lines), default=0.0)
    # QPainter.drawText 多行的行距是 lineSpacing，只有最后一行用 height：
    # 实测 40pt 三行是 61*2 + 53 = 175，直接 height*n 会少 16px 把字裁掉。
    height = fm.height() + fm.lineSpacing() * (len(lines) - 1)
    return max(float(width), 1.0), max(float(height), 1.0)


@dataclass
class Style:
    """一条 item 的 ``style`` 字段解析结果。"""

    stroke: QColor
    stroke_width: float
    fill: bool
    fill_color: QColor
    opacity: int
    corner_radius: float
    font_size: float
    # 字体族：``style.font_family``，缺字段时取 ``FONT_FAMILY_DEFAULT``。
    # 放在带默认值的末尾，任何按位置构造的地方都不会被破坏。
    font_family: str = FONT_FAMILY_DEFAULT
    # 填充样式：``style.fill_style``，缺字段时取 ``solid``（旧引擎唯一填充方式）。
    # 同样放在带默认值的末尾；只在属性面板显式编辑时才写进 JSON。
    fill_style: str = FILL_STYLE_DEFAULT
    # 文本对齐：``style.text_align``，缺字段兜底 center（存量/旧引擎口径）；
    # 新建文本由 create_item 显式写 left。只对 TextItem 的绘制有意义。
    text_align: str = TEXT_ALIGN_DEFAULT

    @classmethod
    def from_dict(cls, data: dict | None) -> "Style":
        d = data or {}
        opacity = int(d.get("opacity", 255))
        stroke = parse_color(d.get("stroke", "#000000"))
        fill_color = parse_color(d.get("fill_color", "#ffffff"))
        # Core 的 set_opacity 把 alpha 写进两个颜色，而不是 painter.setOpacity()
        if 0 < opacity <= 255:
            stroke.setAlpha(opacity)
            fill_color.setAlpha(opacity)
        return cls(
            stroke=stroke,
            stroke_width=float(d.get("strokeWidth", 2)),
            fill=bool(d.get("fill", False)),
            fill_color=fill_color,
            opacity=opacity,
            corner_radius=max(0.0, float(d.get("cornerRadius", 0.0) or 0.0)),
            font_size=float(d.get("font_size", 10)),
            font_family=normalize_font_family(d.get("font_family")),
            fill_style=normalize_brush_style(d.get("fill_style")),
            text_align=normalize_text_align(d.get("text_align")),
        )

    def pen(self, color: QColor | None = None, width: float | None = None) -> QPen:
        if width is None:
            # strokeWidth == 0 时 Core 用填充色作笔色、宽 0
            w = self.stroke_width
            c = (color or self.stroke) if w > 0 else self.fill_color
        else:
            w, c = width, (color or self.stroke)
        return pen_for(c, w)

    def brush(self):
        """按 fill / fill_style 返回只读画刷。

        ``fill=False`` 优先于任何样式（等价于Qt Designer 里关掉填充开关）；
        选了「无填充」同样返回 NoBrush。其余样式按 ``(颜色, 样式)`` 走缓存。
        """
        if not self.fill:
            return QBrush(Qt.NoBrush)
        style = brush_style_value(self.fill_style)
        if style == Qt.NoBrush:
            return QBrush(Qt.NoBrush)
        return brush_for(self.fill_color, style)
