"""料仓状态面板的数据模型（data2.json 中 id=1584 的「料仓状态」组）。

场景里的名字树（共 41 个图元）：

    料仓状态                        group    面板容器
    ├── 料仓状态_IO模块A             group    16 路 IO 指示灯
    │   ├── 料仓状态_IO模块A_1A      circle   通道 1 的 A 灯
    │   ├── 料仓状态_IO模块A_1B      circle   通道 1 的 B 灯
    │   └── …… 1A..8A / 1B..8B 共 16 个
    ├── 料仓状态_IO模块B             group    16 路 IO 指示灯
    │   └── …… 共 16 个
    ├── 料仓状态_图片_1              image    模块外形图（res/rack_io.png）
    ├── 料仓状态_矩形_4906           rect     面板底板
    ├── 料仓状态_标题                text     固定标题
    ├── 料仓状态_灯语文本            text     ← DB12 offset 138（led_tip）
    ├── 料仓状态_提示文本            text     ← DB12 offset 242（tip）
    └── 料仓状态_报警文本            text     ← DB12 offset 34 （err_tip）

A / B 的含义
------------
ELCO 模块每个通道插座旁有一对指示灯，模块丝印上标 **A（上）** 和 **B（下）**。
本模型沿用丝印：``line="A"`` 是上面那一盏，``line="B"`` 是下面那一盏。
（核对过 res/rack_io.png：同一通道的 A 灯在 B 灯上方，通道 1..8 从模块底部往上排。）

每盏灯的实际用途来自图片上的引线标注，见 ``LAMP_LABELS``：模块 A 是传感器 /
灯带 / 按钮类信号，模块 B 是前后、侧面气缸的线圈与磁开。个别通道没有标注，
按“备用”处理（``lamp.label`` 为空串）。

PLC 侧对应 DB12
---------------
与 ``plc_window.ConfigWindow`` 读取 DB12 的口径完全一致（S7 大端）：

    20 + i        每个主机一个字节，bit0 = A 模块在线，bit1 = B 模块在线
    30 / 32       模块 A / 模块 B 的 16 位 IO 状态字
    34            报警文本（WSTRING，104 字节）
    138           灯语文本（WSTRING）
    242           提示文本（WSTRING）
    总长 346 字节 = 242 + 104

16 位状态字到灯位的映射（``IO_BIT_LAYOUT``）：

    "channel_major"（默认）   按通道成对排列，bit = (通道-1)*2 + (A?0:1)
                              bit0=1A, bit1=1B, bit2=2A, … bit15=8B
    "line_major"              A 灯占低 8 位，B 灯占高 8 位
                              bit0..7 = 1A..8A，bit8..15 = 1B..8B

默认值取自旧界面 ``ui/rack_config_v2.ui``：那里 16 个 ``toolButton_A_IO_0..15``
的 label 与位号是成对排的（A库空筒=0 / A库实料=1 / 单库空筒=2 / 单库实料=3 /
B库空筒=4 / B库实料=5 / 托盘接近1=6 / 托盘接近2=7 / 灯带-红=10 / 灯带-蓝=11 /
灯带-绿=12 / 复位按钮灯=14），与 channel_major 完全吻合。现场如果实测相反，
传 ``layout="line_major"`` 或改 ``IO_BIT_LAYOUT`` 即可。

典型用法：

    panel = RackStatusPanelModel(SceneManager)

    # 按语义点灯（label 可以直接查中文含义）
    panel.set_lamp("A", 7, "A", True)          # 灯带-绿 亮
    panel.set_lamp("A", 6, "B", True)          # 灯带-蓝 亮
    panel.set_lamp("B", 7, "A", True)          # 后面气缸伸出线圈 亮
    panel.set_lamp("A", 1, "A", False)         # A库位空筒对射传感器 灭

    # 按中文含义查灯 / 点灯
    panel.find_by_label("托盘接近传感器1").set_on(True)

    # 整块 DB12 一次灌进面板
    panel.apply_db12(db12_bytes)

    # 文本
    panel.set_text("alarm", "3 号料架超时")

    # 取快照 / 灌快照（存档、比对都用这个）
    snap = panel.status()
    panel.apply_status(snap)
    print(panel.format_table())
"""

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Signal,QPointF
from PySide6.QtGui import QColor

from .rack_store_model import LIGHT_COLORS, LightColor, normalize_light
from .elements import base_element, group_element, text_element


__all__ = [
    "PANEL_NAME",
    "IO_MODULES",
    "IO_CHANNELS",
    "IO_LINES",
    "LAMP_LABELS",
    "TEXT_FIELDS",
    "TEXT_FIELD_LABELS",
    "IO_BIT_LAYOUT",
    "DB12_IO_WORD_OFFSETS",
    "DB12_TEXT_OFFSETS",
    "DB12_MODULE_STATUS_BYTE",
    "DB12_SIZE",
    "LampKey",
    "IoLamp",
    "RackPanelStatus",
    "RackStatusPanelModel",
    "bit_index",
    "read_wstring",
]

# ---------------------------------------------------------------- 常量
#: 面板组图元名（data2.json id=1584）
PANEL_NAME = "料仓状态"

#: IO 模块标识：A / B
IO_MODULES = ("A", "B")

#: 每个模块的通道号：1..8
IO_CHANNELS = tuple(range(1, 9))

#: 每通道的一对指示灯（模块丝印 A 上 / B 下）
IO_LINES = ("A", "B")

#: 每盏灯的业务含义。来自 res/rack_io.png 上的引线标注；
#: 表里没有的就是“备用 / 未接线”。
LAMP_LABELS: Dict[Tuple[str, int, str], str] = {
    # ---- 模块 A：传感器、灯带、按钮 ----
    ("A", 1, "A"): "A库位空筒对射传感器",
    ("A", 1, "B"): "A库位实料对射传感器",
    ("A", 2, "A"): "单库位空筒对射传感器",
    ("A", 2, "B"): "单库位实料对射传感器",
    ("A", 3, "A"): "B库位空筒对射传感器",
    ("A", 3, "B"): "B库位实料对射传感器",
    ("A", 4, "A"): "托盘接近传感器1",
    ("A", 4, "B"): "托盘接近传感器2",
    # 通道 5 这一对，图片引线是 A=启用/禁用、B=复位按钮；旧界面 ui 里
    # bit8 的标签是“复位按钮”、bit9 是“启用/禁用”，两者正好相反。
    # 这里按图片（图元丝印 A 在上）填，现场核对时优先看这两个灯。
    ("A", 5, "A"): "启用/禁用",
    ("A", 5, "B"): "复位按钮",
    ("A", 6, "A"): "灯带-红",
    ("A", 6, "B"): "灯带-蓝",
    ("A", 7, "A"): "灯带-绿",
    ("A", 8, "A"): "复位按钮灯",
    # ---- 模块 B：前后 / 侧面气缸线圈与磁开 ----
    ("B", 4, "A"): "侧面气缸伸出磁开",
    ("B", 4, "B"): "侧面气缸退回磁开",
    ("B", 5, "A"): "后面气缸伸出磁开",
    ("B", 5, "B"): "后面气缸退回磁开",
    ("B", 6, "A"): "侧面气缸伸出线圈",
    ("B", 6, "B"): "侧面气缸退回线圈",
    ("B", 7, "A"): "后面气缸伸出线圈",
    ("B", 7, "B"): "后面气缸退回线圈",
}

#: 面板上的文本字段（顺序即显示顺序）
TEXT_FIELDS = ("title", "lamp_legend", "hint", "alarm")

#: 文本字段 -> 中文名
TEXT_FIELD_LABELS = {
    "title": "标题",
    "lamp_legend": "灯语",
    "hint": "提示",
    "alarm": "报警",
}

#: 文本字段的中文/英文别名（兼容调用方各种写法）
TEXT_FIELD_ALIASES = {
    "title": "title",
    "标题": "title",
    "lamp_legend": "lamp_legend",
    "灯语": "lamp_legend",
    "灯语文本": "lamp_legend",
    "hint": "hint",
    "提示": "hint",
    "提示文本": "hint",
    "alarm": "alarm",
    "报警": "alarm",
    "报警文本": "alarm",
}

#: 文本图元名里的关键字（用于在场景里按名字后缀认领文本）
TEXT_NAME_KEYWORDS = {
    "title": ("标题",),
    "lamp_legend": ("灯语",),
    "hint": ("提示",),
    "alarm": ("报警",),
}

#: 灯亮 / 灯灭 / 报警 的默认颜色
LAMP_ON_COLOR = LightColor.GREEN
LAMP_OFF_COLOR = LightColor.GRAY
LAMP_ALARM_COLOR = LightColor.RED

#: 16 位状态字 -> 灯位的排法。默认按通道成对（bit=(通道-1)*2+(A?0:1)），
#: 依据是旧界面 ui/rack_config_v2.ui 里 16 个指示灯按钮的位号与标签对应关系。
IO_BIT_LAYOUT = "channel_major"
_BIT_LAYOUTS = ("line_major", "channel_major")

#: DB12 里 IO 状态字的偏移（按模块）
DB12_IO_WORD_OFFSETS = {"A": 30, "B": 32}

#: DB12 里“每主机 IO 模块在线状态”字节的起始偏移（bit0=A, bit1=B）
DB12_MODULE_STATUS_BYTE = 20

#: DB12 里三个文本的偏移（WSTRING，每个 104 字节）
DB12_TEXT_OFFSETS = {"alarm": 34, "lamp_legend": 138, "hint": 242}

#: DB12 读取长度：242 + 104
DB12_SIZE = 346

# (模块, 通道, A/B)
LampKey = Tuple[str, int, str]

_PANEL_RE = re.compile(r"^" + re.escape(PANEL_NAME) + r"$")
_MODULE_RE = re.compile(r"^" + re.escape(PANEL_NAME) + r"_IO模块\s*([AaBb])$")
_LAMP_RE = re.compile(
    r"^" + re.escape(PANEL_NAME) + r"_IO模块\s*([AaBb])_(\d{1,2})\s*([AaBb])$"
)
_IMAGE_RE = re.compile(r"^" + re.escape(PANEL_NAME) + r"_图片(_\d+)?$")
_FRAME_RE = re.compile(r"^" + re.escape(PANEL_NAME) + r"_矩形(_\d+)?$")

# kind -> 图元名里的关键字（用于在场景里按名字后缀认领文本）
_TEXT_KINDS = ("title", "lamp_legend", "hint", "alarm")

# ---------------------------------------------------------------- 工具函数


def normalize_module(module) -> str:
    """把 'a' / 'A' / '模块A' 统一成 'A'。"""
    text = str(module).strip().upper().replace("模块", "")
    if text in IO_MODULES:
        return text
    raise ValueError(f"未知 IO 模块: {module!r}（可用 A / B）")


def normalize_line(line) -> str:
    """把 'a' / 'A' / 'a灯' 统一成 'A'。"""
    text = str(line).strip().upper().replace("灯", "")
    if text in IO_LINES:
        return text
    raise ValueError(f"未知灯位: {line!r}（可用 A / B）")


def normalize_channel(channel) -> int:
    """通道号 1..8。"""
    try:
        number = int(channel)
    except (TypeError, ValueError):
        raise ValueError(f"未知通道号: {channel!r}（可用 1..8）") from None
    if number not in IO_CHANNELS:
        raise ValueError(f"未知通道号: {channel!r}（可用 1..8）")
    return number


def normalize_text_field(field_key) -> str:
    """把 '报警' / '报警文本' / 'alarm' 统一成 'alarm'。"""
    key = str(field_key).strip()
    if key in TEXT_FIELD_ALIASES:
        return TEXT_FIELD_ALIASES[key]
    lowered = key.lower()
    if lowered in TEXT_FIELD_ALIASES:
        return TEXT_FIELD_ALIASES[lowered]
    raise ValueError(
        f"未知文本字段: {field_key!r}（可用 title/lamp_legend/hint/alarm "
        "或 标题/灯语/提示/报警）"
    )


def bit_index(channel: int, line: str, layout: str = None) -> int:
    """返回某盏灯在 16 位状态字里的位号（0..15）。"""
    channel = normalize_channel(channel)
    line = normalize_line(line)
    layout = (layout or IO_BIT_LAYOUT).strip().lower()
    if layout not in _BIT_LAYOUTS:
        raise ValueError(f"未知位序: {layout!r}（可用 {' / '.join(_BIT_LAYOUTS)}）")
    if layout == "channel_major":
        return (channel - 1) * 2 + (0 if line == "A" else 1)
    return (channel - 1) + (0 if line == "A" else 8)


def nearest_light_color(color: QColor) -> LightColor:
    """把任意 QColor 归到 LIGHT_COLORS 里最接近的一个颜色。"""
    if not isinstance(color, QColor):
        return LAMP_OFF_COLOR
    best, best_distance = LAMP_OFF_COLOR, None
    for key, reference in LIGHT_COLORS.items():
        dr = color.red() - reference.red()
        dg = color.green() - reference.green()
        db = color.blue() - reference.blue()
        distance = dr * dr + dg * dg + db * db
        if best_distance is None or distance < best_distance:
            best, best_distance = LightColor(key), distance
    return best


def read_wstring(buffer, offset: int) -> str:
    """读 S7 WSTRING（4 字节头 + UTF-16BE 字符）。越界或非法返回空串。"""
    if not buffer:
        return ""
    try:
        if offset + 4 > len(buffer):
            return ""
        length = int.from_bytes(bytes(buffer[offset + 2:offset + 4]), "big")
        start = offset + 4
        end = min(start + length * 2, len(buffer))
        if end <= start:
            return ""
        raw = bytes(buffer[start:end])
        return raw.decode("utf-16-be", errors="ignore").replace("\x00", "").strip()
    except Exception:
        return ""


def _text_of(item) -> str:
    """读文本图元的文字（context 的 setter 会前后加空格，读回要 strip）。"""
    if item is None:
        return ""
    try:
        return str(item.context).strip()
    except Exception:
        return ""


def _display_width(text: str) -> int:
    """终端显示宽度：中日韩字符按 2 个字符位算。"""
    width = 0
    for char in str(text):
        wide = (
            "\u1100" <= char <= "\u115f"
            or "\u2e80" <= char <= "\ua4cf"
            or "\uac00" <= char <= "\ud7a3"
            or "\uf900" <= char <= "\ufaff"
            or "\ufe30" <= char <= "\ufe6f"
            or "\uff00" <= char <= "\uff60"
            or "\uffe0" <= char <= "\uffe6"
        )
        width += 2 if wide else 1
    return width


def _pad(text, width: int) -> str:
    """按显示宽度左对齐补空格。"""
    text = str(text)
    return text + " " * max(0, width - _display_width(text))


# ---------------------------------------------------------------- 灯


@dataclass
class IoLamp:
    """一盏 IO 指示灯（场景里的一个 circle 图元）。"""

    module: str
    channel: int
    line: str
    item: object = field(default=None, repr=False, compare=False)
    meaning: str = field(default="", compare=False)

    # ------------------------------------------------------------ 标识
    @property
    def key(self) -> LampKey:
        return (self.module, self.channel, self.line)

    @property
    def label(self) -> str:
        """业务含义（来自模块丝印），备用灯返回空串。"""
        return self.meaning or LAMP_LABELS.get(self.key, "")

    @property
    def display_name(self) -> str:
        """模块A 通道7-A（灯带-绿）"""
        base = f"模块{self.module} 通道{self.channel}-{self.line}"
        return f"{base}（{self.label}）" if self.label else f"{base}（备用）"

    def __str__(self) -> str:
        state = "亮" if self.is_on() else "灭"
        return f"{self.display_name} {state}"

    # ------------------------------------------------------------ 读
    def visible(self) -> bool:
        if self.item is None:
            return False
        return bool(self.item.get_visibility())

    def color(self) -> LightColor:
        """当前灯色；图元缺失或不可见时按“灭”处理。"""
        if self.item is None or not self.visible():
            return LAMP_OFF_COLOR
        try:
            raw = (
                self.item.get_fill_color()
                if self.item.get_fill()
                else self.item.get_color()
            )
        except Exception:
            return LAMP_OFF_COLOR
        return nearest_light_color(raw)

    def is_on(self) -> bool:
        """灰 = 灭，其余颜色 = 亮。"""
        return self.color() is not LAMP_OFF_COLOR

    def to_dict(self) -> Dict[str, object]:
        return {
            "module": self.module,
            "channel": self.channel,
            "line": self.line,
            "label": self.label,
            "on": self.is_on(),
            "color": self.color().value,
        }

    # ------------------------------------------------------------ 写
    def set_color(self, color) -> bool:
        """点灯：把填充色改成 color，并保证图元可见。返回是否真的变了。"""
        if self.item is None:
            return False
        key = normalize_light(color)
        target = LightColor(key) if key else LAMP_OFF_COLOR
        changed = False
        if not self.item.get_fill():
            self.item.set_fill(True)
            changed = True
        if not self.visible():
            # 父组不可见时 set_visibility(True) 会被基类直接忽略，
            # 这里不需要特判——调用方应先让面板可见。
            self.item.set_visibility(True)
            changed = True
        target_color = target.qcolor
        if self.item.get_fill_color() != target_color:
            self.item.set_fill_color(target_color)
            changed = True
        return changed

    def set_on(self, on: bool = True, color=None) -> bool:
        """亮/灭。color=None 时亮用绿色、灭用灰色。"""
        return self.set_color(color if on and color else (LAMP_ON_COLOR if on else LAMP_OFF_COLOR))

    def set_visible(self, enable: bool) -> bool:
        if self.item is None:
            return False
        if self.visible() == bool(enable):
            return False
        self.item.set_visibility(bool(enable))
        return True


# ---------------------------------------------------------------- 快照


@dataclass
class RackPanelStatus:
    """料仓状态面板的一份完整快照（纯数据，不持有图元引用）。"""

    lamps: Dict[LampKey, LightColor] = field(default_factory=dict)
    texts: Dict[str, str] = field(default_factory=dict)
    online: Dict[str, Optional[bool]] = field(default_factory=dict)

    # ------------------------------------------------------------ 访问
    def lamp(self, module, channel, line) -> Optional[LightColor]:
        return self.lamps.get(
            (normalize_module(module), normalize_channel(channel), normalize_line(line))
        )

    def set_lamp(self, module, channel, line, color) -> "RackPanelStatus":
        key = (normalize_module(module), normalize_channel(channel), normalize_line(line))
        light = normalize_light(color)
        self.lamps[key] = LightColor(light) if light else LAMP_OFF_COLOR
        return self

    def text(self, field_key) -> str:
        return self.texts.get(normalize_text_field(field_key), "")

    def set_text(self, field_key, value) -> "RackPanelStatus":
        self.texts[normalize_text_field(field_key)] = str(value)
        return self

    def module_online(self, module) -> Optional[bool]:
        return self.online.get(normalize_module(module))

    # ------------------------------------------------------------ 工具
    def copy(self) -> "RackPanelStatus":
        return RackPanelStatus(
            lamps=dict(self.lamps), texts=dict(self.texts), online=dict(self.online)
        )

    def is_empty(self) -> bool:
        return not self.lamps and not self.texts and not self.online

    def on_count(self, module: str = None) -> int:
        """亮灯数量；给 module 时只统计该模块。"""
        if module is None:
            return sum(1 for color in self.lamps.values() if color is not LAMP_OFF_COLOR)
        module = normalize_module(module)
        return sum(
            1
            for (mod, _channel, _line), color in self.lamps.items()
            if mod == module and color is not LAMP_OFF_COLOR
        )

    def diff(self, other: "RackPanelStatus") -> Dict[str, Tuple[object, object]]:
        """只返回真正不同的项：{可读名: (self, other)}。"""
        changes: Dict[str, Tuple[object, object]] = {}
        for key in sorted(set(self.lamps) | set(other.lamps)):
            mine = self.lamps.get(key, LAMP_OFF_COLOR)
            theirs = other.lamps.get(key, LAMP_OFF_COLOR)
            if mine != theirs:
                module, channel, line = key
                label = LAMP_LABELS.get(key, "")
                name = f"模块{module} 通道{channel}-{line}"
                if label:
                    name += f"（{label}）"
                changes[name] = (mine, theirs)
        for field_key in TEXT_FIELDS:
            mine = self.texts.get(field_key, "")
            theirs = other.texts.get(field_key, "")
            if mine != theirs:
                changes[TEXT_FIELD_LABELS[field_key] + "文本"] = (mine, theirs)
        for module in IO_MODULES:
            mine = self.online.get(module)
            theirs = other.online.get(module)
            if mine != theirs:
                changes[f"模块{module}在线"] = (mine, theirs)
        return changes

    def to_dict(self) -> Dict[str, object]:
        return {
            "lamps": {
                f"{module}-{channel}-{line}": color.value
                for (module, channel, line), color in sorted(self.lamps.items())
            },
            "texts": dict(self.texts),
            "online": dict(self.online),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "RackPanelStatus":
        status = cls()
        for key, value in (data or {}).get("lamps", {}).items():
            module, channel, line = str(key).split("-")
            status.set_lamp(module, channel, line, value)
        for field_key, value in (data or {}).get("texts", {}).items():
            status.set_text(field_key, value)
        online = (data or {}).get("online", {}) or {}
        for module, value in online.items():
            status.online[str(module).upper()] = value
        return status

    def __str__(self) -> str:
        parts = [
            f"模块A 亮 {self.on_count('A')}/16",
            f"模块B 亮 {self.on_count('B')}/16",
        ]
        for field_key in TEXT_FIELDS:
            value = self.texts.get(field_key, "")
            if value:
                parts.append(f"{TEXT_FIELD_LABELS[field_key]}={value!r}")
        return "RackPanelStatus(" + "，".join(parts) + ")"


# ---------------------------------------------------------------- 面板模型


class RackStatusPanelModel(QObject):
    """料仓状态面板模型：按 (模块, 通道, 灯位) 访问 32 盏灯和 4 个文本。

    图元靠名字识别，所以场景重新加载（再次 ``load_element_info2``）之后
    必须调 ``refresh()``，否则旧引用会随图元删除而失效。
    """

    # 某盏灯的状态变了
    lamp_changed = Signal(str, int, str)
    # 某个文本变了
    text_changed = Signal(str)
    # 某个模块的在线状态变了
    module_online_changed = Signal(str, bool)
    # 任意变化（配合 batch() 时只发一次）
    changed = Signal()

    def __init__(self, scene_manager, parent=None, labels: Dict[LampKey, str] = None):
        super().__init__(parent)
        self._manager = scene_manager
        self._labels = dict(labels) if labels else dict(LAMP_LABELS)
        self.lamps: Dict[LampKey, IoLamp] = {}
        self.modules: Dict[str, object] = {}
        self.texts: Dict[str, object] = {}
        self.image = None
        self.frame = None
        self.group:group_element = None
        self.warnings: List[str] = []
        # 业务侧状态：模块在线、文本；色值缓存用于面板重新显示后回灌
        self._online: Dict[str, Optional[bool]] = {module: None for module in IO_MODULES}
        self._texts: Dict[str, str] = {field_key: "" for field_key in TEXT_FIELDS}
        self._cache: Dict[LampKey, LightColor] = {}
        self._suspend = 0
        self._dirty = False
        self.refresh()


    def hide_all(self) -> None:
        """把所有灯和文本都隐藏起来。"""
        if self.group is not None:
            self.group.set_visibility(False)
    def show_all(self) -> None:
        """把所有灯和文本都显示出来。"""
        if self.group is not None:
            self.group.set_visibility(True)
    # ------------------------------------------------------------ 构建
    def label_of(self, module, channel, line) -> str:
        key = (normalize_module(module), normalize_channel(channel), normalize_line(line))
        lamp = self.lamps.get(key)
        if lamp is not None:
            return lamp.label
        return self._labels.get(key, LAMP_LABELS.get(key, ""))

    def refresh(self) -> None:
        """按当前场景内容重建索引。"""
        self.lamps.clear()
        self.modules.clear()
        self.texts.clear()
        self.group = None
        self.image = None
        self.frame = None
        self.warnings.clear()

        manager = self._manager
        if manager is None:
            self.warnings.append("SceneManager 为空，料仓状态面板为空")
            return

        items = [item for item in manager.m_items.values() if item is not None]
        pending_texts: Dict[str, object] = {}
        for item in items:
            name = item.get_name()
            if not name or not name.startswith(PANEL_NAME):
                continue

            if _PANEL_RE.match(name):
                self.group = item
                continue

            match = _MODULE_RE.match(name)
            if match:
                self.modules[match.group(1).upper()] = item
                continue

            match = _LAMP_RE.match(name)
            if match:
                module = match.group(1).upper()
                channel = int(match.group(2))
                line = match.group(3).upper()
                if channel not in IO_CHANNELS:
                    self.warnings.append(f"图元 {name} 的通道号 {channel} 超出 1..8")
                    continue
                key = (module, channel, line)
                if key in self.lamps:
                    self.warnings.append(f"灯位重复，已忽略后一个：{name}")
                    continue
                self.lamps[key] = IoLamp(
                    module, channel, line, item, self._labels.get(key, "")
                )
                continue

            if _IMAGE_RE.match(name):
                self.image = item
                continue

            if _FRAME_RE.match(name):
                self.frame = item
                continue

            tail = name[len(PANEL_NAME):]
            for field_key in _TEXT_KINDS:
                if any(keyword in tail for keyword in TEXT_NAME_KEYWORDS[field_key]):
                    if field_key in pending_texts:
                        self.warnings.append(f"文本重复，已忽略后一个：{name}")
                        break
                    pending_texts[field_key] = item
                    break

        self.texts = pending_texts
        for field_key in TEXT_FIELDS:
            item = self.texts.get(field_key)
            if item is None:
                self.warnings.append(
                    f"缺少{TEXT_FIELD_LABELS[field_key]}文本图元"
                    f"（名字应为 {PANEL_NAME}_{TEXT_FIELD_LABELS[field_key]}文本）"
                )
            else:
                # 场景里的文字是设计时写的，首次建模型时读进来当初始值
                self._texts[field_key] = _text_of(item)

        if self.group is None:
            self.warnings.append(f"缺少面板组图元（名字应为 {PANEL_NAME}）")
        for module in IO_MODULES:
            if module not in self.modules:
                self.warnings.append(f"缺少 IO 模块{module} 组图元")
            missing = [
                f"{channel}{line}"
                for channel in IO_CHANNELS
                for line in IO_LINES
                if (module, channel, line) not in self.lamps
            ]
            if missing:
                self.warnings.append(
                    f"模块{module} 缺少 {len(missing)} 盏灯：{'、'.join(missing)}"
                )

        # 重建缓存：以当前画面为准
        self._cache = {key: lamp.color() for key, lamp in self.lamps.items()}

    # ------------------------------------------------------------ 批量
    @contextmanager
    def batch(self):
        """批量修改时挂起 lamp_changed / changed，退出时只发一次 changed。"""
        self._suspend += 1
        try:
            yield self
        finally:
            self._suspend -= 1
            if self._suspend == 0 and self._dirty:
                self._dirty = False
                self.changed.emit()

    def _notify_lamp(self, key: LampKey) -> None:
        if self._suspend:
            self._dirty = True
            return
        self.lamp_changed.emit(key[0], key[1], key[2])
        self.changed.emit()

    def _notify_text(self, field_key: str) -> None:
        if self._suspend:
            self._dirty = True
            return
        self.text_changed.emit(field_key)
        self.changed.emit()

    def _notify_changed(self) -> None:
        if self._suspend:
            self._dirty = True
            return
        self.changed.emit()

    # ------------------------------------------------------------ 访问
    def lamp(self, module, channel, line) -> Optional[IoLamp]:
        key = (normalize_module(module), normalize_channel(channel), normalize_line(line))
        return self.lamps.get(key)

    def channel(self, module, channel) -> Dict[str, Optional[IoLamp]]:
        """一个通道的两盏灯：{'A': 灯, 'B': 灯}。"""
        return {
            line: self.lamp(module, channel, line) for line in IO_LINES
        }

    def module_lamps(self, module) -> List[IoLamp]:
        module = normalize_module(module)
        return [
            self.lamps[key]
            for key in sorted(
                (key for key in self.lamps if key[0] == module),
                key=lambda key: (key[1], key[2]),
            )
        ]

    def is_on(self, module, channel, line) -> bool:
        lamp = self.lamp(module, channel, line)
        return bool(lamp and lamp.is_on())

    def color_of(self, module, channel, line) -> Optional[LightColor]:
        lamp = self.lamp(module, channel, line)
        return lamp.color() if lamp else None

    def find_by_label(self, label: str) -> Optional[IoLamp]:
        """按中文含义找灯，例如 find_by_label('托盘接近传感器1')。"""
        text = str(label).strip()
        if not text:
            return None
        for lamp in self.lamps.values():
            if lamp.label == text:
                return lamp
        for lamp in self.lamps.values():
            if text in lamp.label:
                return lamp
        return None

    # ------------------------------------------------------------ 写：灯
    def set_lamp(
        self,
        module,
        channel,
        line,
        on: bool = True,
        color=None,
        emit: bool = True,
    ) -> bool:
        """点灯 / 灭灯。color 只在亮时有意义（默认绿色）。"""
        lamp = self.lamp(module, channel, line)
        if lamp is None:
            self.warnings.append(f"没有这盏灯：{module}/{channel}/{line}")
            return False
        target = color if (on and color) else (LAMP_ON_COLOR if on else LAMP_OFF_COLOR)
        if not lamp.set_color(target):
            return False
        self._cache[lamp.key] = lamp.color()
        if emit:
            self._notify_lamp(lamp.key)
        return True

    def set_channel(
        self,
        module,
        channel,
        a=None,
        b=None,
        color=None,
        emit: bool = True,
    ) -> int:
        """一次设置一个通道的两盏灯。a/b 为 None 表示不动。返回变化数。"""
        changed = 0
        with self.batch():
            if a is not None and self.set_lamp(module, channel, "A", a, color, emit=False):
                changed += 1
            if b is not None and self.set_lamp(module, channel, "B", b, color, emit=False):
                changed += 1
        if changed and emit:
            self._notify_changed()
        return changed

    def set_module_bits(
        self,
        module,
        value: int,
        layout: str = None,
        emit: bool = True,
        color=None,
    ) -> int:
        """按 16 位状态字设置一个模块的 16 盏灯，返回变化数。"""
        module = normalize_module(module)
        value = int(value) & 0xFFFF
        changed = 0
        with self.batch():
            for channel in IO_CHANNELS:
                for line in IO_LINES:
                    on = bool(value & (1 << bit_index(channel, line, layout)))
                    if self.set_lamp(module, channel, line, on, color, emit=False):
                        changed += 1
        if changed and emit:
            self._notify_changed()
        return changed

    def set_all_off(self, module=None, emit: bool = True) -> int:
        """整块灭灯。module 为 None 时两个模块都灭。"""
        targets = IO_MODULES if module is None else (normalize_module(module),)
        changed = 0
        with self.batch():
            for target in targets:
                for channel in IO_CHANNELS:
                    for line in IO_LINES:
                        if self.set_lamp(target, channel, line, False, emit=False):
                            changed += 1
        if changed and emit:
            self._notify_changed()
        return changed

    # ------------------------------------------------------------ 写：模块在线
    def set_module_online(self, module, online, emit: bool = True) -> bool:
        """模块在线状态。离线时把该模块 16 盏灯全部置灰。"""
        module = normalize_module(module)
        online = None if online is None else bool(online)
        if self._online.get(module, None) == online:
            return False
        self._online[module] = online
        if online is False:
            for channel in IO_CHANNELS:
                for line in IO_LINES:
                    self.set_lamp(module, channel, line, False, emit=False)
        if emit:
            if self._suspend:
                self._dirty = True
            else:
                self.module_online_changed.emit(module, bool(online))
                self.changed.emit()
        return True

    def is_module_online(self, module) -> Optional[bool]:
        return self._online.get(normalize_module(module))

    # ------------------------------------------------------------ 写：文本
    def text(self, field_key) -> str:
        field_key = normalize_text_field(field_key)
        item = self.texts.get(field_key)
        if item is not None:
            return _text_of(item)
        return self._texts.get(field_key, "")

    def set_text(self, field_key, value, emit: bool = True) -> bool:
        field_key = normalize_text_field(field_key)
        text = "" if value is None else str(value)
        item = self.texts.get(field_key)
        if item is not None:
            if _text_of(item) == text.strip():
                self._texts[field_key] = text
                return False
            item.context = text
        elif self._texts.get(field_key) == text:
            return False
        self._texts[field_key] = text
        if emit:
            self._notify_text(field_key)
        return True

    def set_alarm(self, text: str, emit: bool = True) -> bool:
        return self.set_text("alarm", text, emit)

    def set_hint(self, text: str, emit: bool = True) -> bool:
        return self.set_text("hint", text, emit)

    def set_lamp_legend(self, text: str, emit: bool = True) -> bool:
        return self.set_text("lamp_legend", text, emit)


    def move(self, targetPos: QPointF) -> bool:
        """整体移动面板组。"""
        if self.group is None:
            return False
        try:
            self.group.change_position(targetPos)
            return True
        except Exception:
            return False
    # ------------------------------------------------------------ 显示
    def set_visible(self, visible: bool, emit: bool = False) -> bool:
        """整块面板显示 / 隐藏。

        隐藏组会把组内所有子图元的可见标志一起清掉（基类的行为），
        所以重新显示后要按缓存把 32 盏灯的颜色回灌一次。
        """
        if self.group is None:
            return False
        if not visible:
            self._cache = {key: lamp.color() for key, lamp in self.lamps.items()}
        self.group.set_visibility(bool(visible))
        if visible:
            for key, color in self._cache.items():
                lamp = self.lamps.get(key)
                if lamp is not None:
                    lamp.set_color(color)
        return True

    def is_visible(self) -> bool:
        return bool(self.group and self.group.get_visibility())

    # ------------------------------------------------------------ 快照
    def status(self) -> RackPanelStatus:
        """读回当前显示出来的状态。"""
        status = RackPanelStatus(online=dict(self._online))
        for key, lamp in self.lamps.items():
            status.lamps[key] = lamp.color()
        for field_key in TEXT_FIELDS:
            status.texts[field_key] = self.text(field_key)
        return status

    def apply_status(self, status: RackPanelStatus, emit: bool = True) -> List[str]:
        """把一份快照灌到画面上，返回变化的可读描述。"""
        if status is None:
            return []
        before = self.status()
        with self.batch():
            for module, online in (status.online or {}).items():
                if online is not None:
                    self.set_module_online(module, online, emit=False)
            for key, color in status.lamps.items():
                on = color is not LAMP_OFF_COLOR
                self.set_lamp(key[0], key[1], key[2], on, color, emit=False)
            for field_key, value in status.texts.items():
                self.set_text(field_key, value, emit=False)
        changed = list(before.diff(self.status()).keys())
        if changed and emit:
            self._notify_changed()
        return changed

    def capture(self) -> RackPanelStatus:
        """同 status()，语义更明确：把画面上的东西抓成快照。"""
        return self.status()

    # ------------------------------------------------------------ PLC
    def apply_db12(
        self,
        data: Sequence[int],
        host_index: int = 0,
        layout: str = None,
        emit: bool = True,
    ) -> Dict[str, int]:
        """把一整块 DB12 灌到面板上。

        host_index：哪台主机（决定从 20 + host_index 取模块在线位）。
        返回 {"lamps": 变化灯数, "texts": 变化文本数}。
        """
        

        result = {"lamps": 0, "texts": 0}

        if not self.group.get_visibility():
            return result
        if data is None or len(data) < 34:
            self.warnings.append("DB12 数据为空或长度不足，已忽略")
            return result
        raw = bytes(bytearray(data))
        with self.batch():
            # 1) 模块在线（bit0=A, bit1=B）
            offset = DB12_MODULE_STATUS_BYTE + int(host_index)
            if offset < len(raw):
                status_byte = raw[offset]
                for index, module in enumerate(IO_MODULES):
                    self.set_module_online(module, bool(status_byte & (1 << index)), emit=False)
            # 2) 16 位 IO 状态字
            for module, word_offset in DB12_IO_WORD_OFFSETS.items():
                if word_offset + 2 > len(raw):
                    continue
                word = int.from_bytes(raw[word_offset:word_offset + 2], "big")
                result["lamps"] += self.set_module_bits(module, word, layout=layout, emit=False)
            # 3) 三个文本
            for field_key, text_offset in DB12_TEXT_OFFSETS.items():
                if self.set_text(field_key, read_wstring(raw, text_offset), emit=False):
                    result["texts"] += 1
        if emit:
            self._notify_changed()
        return result

    def module_word(self, module, layout: str = None) -> int:
        """把当前灯色编码回 16 位状态字（自测 / 回写用）。"""
        module = normalize_module(module)
        word = 0
        for key, color in self._cache.items():
            if key[0] != module or color is LAMP_OFF_COLOR:
                continue
            word |= 1 << bit_index(key[1], key[2], layout)
        return word

    # ------------------------------------------------------------ 描述
    def describe(self) -> str:
        online_a = self._online.get("A")
        online_b = self._online.get("B")

        def online_text(value):
            return "未知" if value is None else ("在线" if value else "离线")

        return (
            f"{PANEL_NAME}面板：模块A 亮 {self._count_on('A')}/16（{online_text(online_a)}），"
            f"模块B 亮 {self._count_on('B')}/16（{online_text(online_b)}）；"
            f"报警={self.text('alarm')!r}"
        )

    def _count_on(self, module: str) -> int:
        return sum(
            1
            for key, lamp in self.lamps.items()
            if key[0] == module and lamp.is_on()
        )

    def format_table(self, module: str = None) -> str:
        """每个通道一行的文本表格，现场排查直接 print。"""
        targets = IO_MODULES if module is None else (normalize_module(module),)
        lines: List[str] = []
        for target in targets:
            online = self._online.get(target)
            state = "未知" if online is None else ("在线" if online else "离线")
            lines.append(f"模块{target}（{state}）  亮 {self._count_on(target)}/16")
            lines.append(
                "  " + _pad("通道", 6) + _pad("A 灯（上）", 26) + "B 灯（下）"
            )
            for channel in IO_CHANNELS:
                cells = []
                for line in IO_LINES:
                    lamp = self.lamp(target, channel, line)
                    if lamp is None:
                        cells.append("缺失")
                        continue
                    mark = "●" if lamp.is_on() else "○"
                    meaning = self.label_of(target, channel, line) or "备用"
                    cells.append(f"{mark} {meaning}")
                lines.append("  " + _pad(channel, 6) + _pad(cells[0], 26) + cells[1])
            lines.append("")
        return "\n".join(lines).rstrip()

    def __str__(self) -> str:
        return self.describe()

    def __repr__(self) -> str:
        return (
            f"<RackStatusPanelModel 灯 {len(self.lamps)} 盏，文本 {len(self.texts)} 个，"
            f"警告 {len(self.warnings)} 条>"
        )
