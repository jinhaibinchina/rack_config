"""料仓图元的数据结构（模型层）。

场景文件（data2.json）里的图元只靠“名字”表达语义，约定形如：

    料架1                                    group  整台料架
    ├── 料架1_仓位1                          group  一个仓位
    │   ├── 料架1_仓位1_框1/框2/框3               rect   背景框（旧文件是 矩形_<序号>）
    │   ├── 料架1_仓位1_托盘                      rect   托盘
    │   ├── 料架1_仓位1_X气缸                     rect   气缸缸体
    │   ├── 料架1_仓位1_X气缸伸出 / X气缸缩回       rect   气缸伸出/缩回两种位置
    │   ├── 料架1_仓位1_Y气缸 (+伸出/缩回)         rect
    │   ├── 料架1_仓位1_托盘接近1/2                rect   传感器
    │   ├── 料架1_仓位1_A库空筒           rect   料位示意层（只显示其中一层）
    │   ├── 料架1_仓位1_A库实料           rect   料位示意层（只显示其中一层）
    │   ├── 料架1_仓位1_B库空筒 / B库实料           rect
    │   ├── 料架1_仓位1_单库空筒 / 单库实料         rect
    │   ├── 料架1_仓位1_灯带                      rect   灯带本体
    │   ├── 料架1_仓位1_灯带红/灯带绿/灯带黄        rect   灯带的三种颜色
    │   └── 料架1_仓位1_编号                      text   仓位编号
    └── 料架1_机台编号                        text   机台号

命名容错：
  * 背景框优先 框1/框2/框3，旧场景的 矩形_<序号> 仍按“矩形”前缀识别；
  * 灯带颜色还接受 红灯/绿灯/黄灯、灯带红灯/灯带绿灯/灯带黄灯；
  * 气缸位置还接受带下划线的 X气缸_伸出 / X气缸_缩回。

本模块把这棵“名字树”解析成 RackStoreModel -> Rack -> RackSlot -> parts，
业务代码按 (料架号, 仓位号, 语义) 访问图元，不用再手写名字查
SceneManager.m_name_items：

    model = RackStoreModel(scene_manager)
    model.set_material(1, 2, "A", MaterialState.FULL)
    model.set_pallet(1, 2, True)
    model.set_light(1, 2, LightColor.GREEN)
    model.set_light(1, 2, "蓝", "1hz")   # 蓝色 1Hz 闪烁
    model.set_cylinder(1, 2, "x", CylinderState.EXTENDED)
    model.set_slot_number(1, 2, "12")
    model.apply_status(1, 2, RackSlotStatus(
        a=MaterialState.EMPTY,
        b=MaterialState.UNKNOWN,
        single=MaterialState.FULL,
        light=LightColor.RED,
        cylinders={"x": CylinderState.RETRACTED},
    ))

所有数据结构都实现了 __str__，现场排查可以直接打印：

    print(model)                # 整仓概览（每台料架 + 每仓位一行）
    print(model.slot(1, 2))     # 单仓位详情（含缺失图元提示）
    print(model.slot(1, 2).summary())   # 只要一行
"""
import re
import weakref
from dataclasses import dataclass, field, InitVar
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, Qt, QTimer, Signal,QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from .elements import base_element, group_element, text_element

# ---------------------------------------------------------------- 命名约定
RACK_NAME_RE = re.compile(r"^料架(?P<rack>\d+)$")
MACHINE_LABEL_RE = re.compile(r"^料架(?P<rack>\d+)_机台编号$")
SLOT_NAME_RE = re.compile(r"^料架(?P<rack>\d+)_仓位(?P<slot>\d+)$")
SLOT_PART_NAME_RE = re.compile(
    r"^料架(?P<rack>\d+)_仓位(?P<slot>\d+)_(?P<part>.+)$"
)

PALLET = "托盘"
CYLINDER_X = "X气缸"
CYLINDER_Y = "Y气缸"
SENSOR_PALLET_1 = "托盘接近1"
SENSOR_PALLET_2 = "托盘接近2"
LIGHT = "灯带"
NUMBER = "编号"

# 传感器序号 -> 图元名
SENSOR_PARTS = {1: SENSOR_PALLET_1, 2: SENSOR_PALLET_2}

# 料位区域顺序（打印 / 遍历用），顺序固定有利于日志比对
AREA_ORDER = ("A", "B", "single")
AREA_LABELS = {"A": "A库", "B": "B库", "single": "单库"}

# 气缸轴顺序
AXIS_ORDER = ("x", "y")

# 背景框：新命名 框1/框2/框3；旧命名 矩形_<序号>（序号不稳定，按前缀识别）
BACKGROUND_NAMES = ("框1", "框2", "框3")
BACKGROUND_LEGACY_PREFIX = "矩形"

# 区域 -> (空筒层, 实料层)，同一时刻只显示其中一层。
# 注意：key 是区域标识（A / B / single），value 才是场景里的图元名。
MATERIAL_LAYERS = {
    "A": ("A库空筒", "A库实料"),
    "B": ("B库空筒", "B库实料"),
    "single": ("单库空筒", "单库实料"),
}

# 六个料位层名（扁平写法，顺序与 data2.json 一致）。
# set_material 接受层名时按“显示/隐藏这一层”处理，用这份名字做判定。
MATERIAL_LAYER_NAMES = (
    "A库空筒",
    "A库实料",
    "B库空筒",
    "B库实料",
    "单库空筒",
    "单库实料",
)


# 灯带颜色 -> 颜色 key。
# 场景里每个仓位只有一个“灯带”本体矩形（没有分色图层），所以颜色是通过
# 修改该矩形的填充色/边框色实现的，这里只负责名字归一化。
LIGHT_COLORS = {
    "red": QColor("#FF0000"),
    "green": QColor("#00FF00"),
    "blue": QColor("#0000FF"),
    "yellow": QColor("#FFFF00"),
    "gray": QColor("#808080"),
}
LIGHT_ORDER = ("red", "green", "blue", "yellow", "gray")

# 灯带闪烁频率 -> 半周期（毫秒）。常亮为 None。
LIGHT_FREQUENCIES = {
    "steady": None,
    "1hz": 500,
    "0.5hz": 1000,
}
LIGHT_DEFAULT_COLOR = "red"
LIGHT_DEFAULT_FREQ = "steady"
# 灯灭的显式写法。用于“完整快照”里区分 None（不改）与“灭”。
LIGHT_OFF = "off"

# 气缸两种位置 -> 候选图元名（按顺序取第一个存在的）
CYLINDER_LAYER_NAMES = {
    "x": {
        "extended": ("X气缸伸出", "X气缸_伸出", "X气缸伸出态", "X缸伸出", "气缸X伸出"),
        "retracted": ("X气缸缩回", "X气缸_缩回", "X气缸缩回态", "X缸缩回", "气缸X缩回"),
    },
    "y": {
        "extended": ("Y气缸伸出", "Y气缸_伸出", "Y气缸伸出态", "Y缸伸出", "气缸Y伸出"),
        "retracted": ("Y气缸缩回", "Y气缸_缩回", "Y气缸缩回态", "Y缸缩回", "气缸Y缩回"),
    },
}

# 仓位里应当存在的语义部件（背景框、灯带颜色、气缸位置单独判定）
EXPECTED_SLOT_PARTS = (
    PALLET,
    CYLINDER_X,
    CYLINDER_Y,
    SENSOR_PALLET_1,
    SENSOR_PALLET_2,
    LIGHT,
    NUMBER,
    "A库空筒",
    "A库实料",
    "B库空筒",
    "B库实料",
    "单库空筒",
    "单库实料",
)

# 所有候选的“状态层”名字（气缸位置层 + 料位层）
# 注意：灯带已不再按颜色分层，只剩“灯带”本体（见 LIGHT），不参与这里。
_STATE_LAYER_CANDIDATES = tuple(
    [name for layers in MATERIAL_LAYERS.values() for name in layers]
    + [
        name
        for axis in CYLINDER_LAYER_NAMES.values()
        for group in axis.values()
        for name in group
    ]
)

# 属于“状态层”的部件：hide_all_state_layers() 会全部隐藏（含灯带本体/气缸缸体）
STATE_LAYER_PARTS = (
    PALLET,
    CYLINDER_X,
    CYLINDER_Y,
    SENSOR_PALLET_1,
    SENSOR_PALLET_2,
    LIGHT,
) + _STATE_LAYER_CANDIDATES


# ---------------------------------------------------------------- 枚举
class MaterialState(Enum):
    """料位状态。UNKNOWN 表示“数据未知”，两层示意都隐藏。"""

    UNKNOWN = "unknown"
    EMPTY = "empty"
    FULL_1 = "full_1"
    FULL_2 = "full_2"

    def __str__(self) -> str:
        return {
            "unknown": "未知",
            "empty": "空筒",
            "full_1": "实料1",
            "full_2": "实料2",
        }.get(self.value, self.value)


class LightColor(Enum):
    """灯带颜色：红 / 绿 / 蓝 / 黄 / 灰。"""

    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    YELLOW = "yellow"
    GRAY = "gray"

    def __str__(self) -> str:
        return {
            "red": "红",
            "green": "绿",
            "blue": "蓝",
            "yellow": "黄",
            "gray": "灰",
        }.get(self.value, self.value)

    @property
    def qcolor(self) -> QColor:
        """该颜色对应的 QColor（用于写回灯带图元）。"""
        return QColor(LIGHT_COLORS[self.value])


class LightFreq(Enum):
    """灯带频率：常亮 / 1Hz / 0.5Hz。"""

    STEADY = "steady"
    HZ_1 = "1hz"
    HZ_05 = "0.5hz"

    def __str__(self) -> str:
        return {"steady": "常亮", "1hz": "1Hz", "0.5hz": "0.5Hz"}.get(
            self.value, self.value
        )

    @property
    def half_period(self) -> Optional[int]:
        """闪烁半周期（毫秒）；常亮返回 None。"""
        return LIGHT_FREQUENCIES[self.value]

    def is_blinking(self) -> bool:
        return self.half_period is not None


class CylinderState(Enum):
    """气缸位置：伸出 / 缩回。"""

    EXTENDED = "extended"
    RETRACTED = "retracted"

    def __str__(self) -> str:
        return {"extended": "伸出", "retracted": "缩回"}.get(self.value, self.value)


class SensorState(Enum):
    """托盘接近开关状态。

    ACTIVE / INACTIVE 对应 ``托盘接近N`` 图元可见 / 隐藏：
    场景里传感器是用“亮起的小方块”表示的，可见即触发。
    UNKNOWN 表示两层信息都没有（例如图元缺失）。
    """

    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return {"active": "通", "inactive": "断", "unknown": "未知"}.get(
            self.value, self.value
        )

    @property
    def occupied(self) -> Optional[bool]:
        """是否有托盘：通 → True，断 → False，未知 → None。"""
        return {
            "active": True,
            "inactive": False,
            "unknown": None,
        }[self.value]

    @classmethod
    def from_bool(cls, value) -> "SensorState":
        if value is None:
            return cls.UNKNOWN
        return cls.ACTIVE if value else cls.INACTIVE


# ---------------------------------------------------------------- 写法归一化
_AREA_ALIASES = {
    "a": "A",
    "A": "A",
    "a库": "A",
    "a区": "A",
    "A库": "A",
    "A区": "A",
    "b": "B",
    "B": "B",
    "b库": "B",
    "b区": "B",
    "B库": "B",
    "B区": "B",
    "single": "single",
    "s": "single",
    "单": "single",
    "单库": "single",
    "单库位": "single",
    "单库区": "single",
    "single库": "single",
}

_STATE_ALIASES = {
    "unknown": MaterialState.UNKNOWN,
    "未知": MaterialState.UNKNOWN,
    "无": MaterialState.UNKNOWN,
    "none": MaterialState.UNKNOWN,
    None: MaterialState.UNKNOWN,
    -1: MaterialState.UNKNOWN,
    "empty": MaterialState.EMPTY,
    "空": MaterialState.EMPTY,
    "空筒": MaterialState.EMPTY,
    "无料": MaterialState.EMPTY,
    "0": MaterialState.EMPTY,
    0: MaterialState.EMPTY,
    "full": MaterialState.FULL_1,
    "实料": MaterialState.FULL_1,
    "满料": MaterialState.FULL_1,
    "有料": MaterialState.FULL_1,
    "1": MaterialState.FULL_1,
    1: MaterialState.FULL_1,
    "full_1": MaterialState.FULL_1,
    "实料1": MaterialState.FULL_1,
    "full_2": MaterialState.FULL_2,
    "实料2": MaterialState.FULL_2,
    2: MaterialState.FULL_2,
}

# 颜色写法 -> 颜色 key，None 表示“灭”（灯带本体隐藏）
_LIGHT_ALIASES = {
    "red": "red",
    "r": "red",
    "红": "red",
    "红色": "red",
    "红灯": "red",
    "红态": "red",
    "green": "green",
    "g": "green",
    "绿": "green",
    "绿色": "green",
    "绿灯": "green",
    "绿态": "green",
    "blue": "blue",
    "b": "blue",
    "蓝": "blue",
    "蓝色": "blue",
    "蓝灯": "blue",
    "蓝态": "blue",
    "yellow": "yellow",
    "y": "yellow",
    "黄": "yellow",
    "黄色": "yellow",
    "黄灯": "yellow",
    "黄态": "yellow",
    "gray": "gray",
    "grey": "gray",
    "灰": "gray",
    "灰色": "gray",
    "灰灯": "gray",
    "灰态": "gray",
    "off": None,
    "none": None,
    "灭": None,
    "全灭": None,
    "关": None,
    "隐藏": None,
}

# 频率写法 -> 频率 key
_FREQ_ALIASES = {
    "steady": "steady",
    "on": "steady",
    "const": "steady",
    "constant": "steady",
    "常亮": "steady",
    "常明": "steady",
    "常开": "steady",
    "亮": "steady",
    "1hz": "1hz",
    "1": "1hz",
    "1.0hz": "1hz",
    "1 hz": "1hz",
    "0.5hz": "0.5hz",
    "0.5": "0.5hz",
    ".5hz": "0.5hz",
    "2s": "0.5hz",
    "闪": "0.5hz",
}


_AXIS_ALIASES = {
    "x": "x",
    "1": "x",
    "x轴": "x",
    "y": "y",
    "2": "y",
    "y轴": "y",
}

_CYLINDER_ALIASES = {
    "extended": CylinderState.EXTENDED,
    "extend": CylinderState.EXTENDED,
    "out": CylinderState.EXTENDED,
    "伸出": CylinderState.EXTENDED,
    "伸出态": CylinderState.EXTENDED,
    "正": CylinderState.EXTENDED,
    "1": CylinderState.EXTENDED,
    "retracted": CylinderState.RETRACTED,
    "retract": CylinderState.RETRACTED,
    "in": CylinderState.RETRACTED,
    "缩回": CylinderState.RETRACTED,
    "缩回态": CylinderState.RETRACTED,
    "收": CylinderState.RETRACTED,
    "0": CylinderState.RETRACTED,
}


def normalize_area(area) -> str:
    """把 'A' / 'a' / 'A库' / '单库' 之类的写法统一成 'A' / 'B' / 'single'。

    也接受 MATERIAL_LAYERS 里的完整名字（'A库空筒' / 'A库实料'），按前缀归档，
    这样调用方从场景里拿到的部件名也能直接传进来。
    """
    if area is None:
        raise ValueError("未知料位区域: None（可用 A / B / single）")

    # 先用原值查（'A' 与 'a' 都是合法 key），再按小写查
    if area in _AREA_ALIASES:
        return _AREA_ALIASES[area]
    if isinstance(area, bool):
        raise ValueError(f"未知料位区域: {area!r}（可用 A / B / single）")

    key = str(area).strip()
    lowered = key.lower()
    if key in _AREA_ALIASES:
        return _AREA_ALIASES[key]
    if lowered in _AREA_ALIASES:
        return _AREA_ALIASES[lowered]

    # 'A库空筒' / 'A库实料' 这类完整部件名 → 取前缀
    for prefix, area_key in (("a库", "A"), ("b库", "B"), ("单库", "single")):
        if lowered.startswith(prefix):
            return area_key

    raise ValueError(
        f"未知料位区域: {area!r}（可用 A / B / single，或 A库 / B库 / 单库）"
    )


def normalize_state(state) -> MaterialState:
    """把 bool / int / 中英文写法统一成 MaterialState。"""
    if isinstance(state, MaterialState):
        return state
    if state in _STATE_ALIASES:
        return _STATE_ALIASES[state]
    if isinstance(state, str):
        lowered = state.strip().lower()
        if lowered in _STATE_ALIASES:
            return _STATE_ALIASES[lowered]
    raise ValueError(f"未知料位状态: {state!r}（可用 empty / full / unknown）")


def normalize_light(value) -> Optional[str]:
    """把灯带颜色写法统一成颜色 key；None 表示灭。

    支持 LightColor / '红' / '红色' / 'red' / 'off' / '灭' 等写法。
    灯带同一时刻只有一种颜色，传入集合时取排序后的第一个（兼容旧数据）。
    """
    if value is None:
        return None
    if isinstance(value, LightColor):
        return value.value
    if isinstance(value, str):
        key = value.strip().lower()
        if key not in _LIGHT_ALIASES:
            raise ValueError(
                f"未知灯带颜色: {value!r}"
                "（可用 red/green/blue/yellow/gray 或 红/绿/蓝/黄/灰，off 表示灭）"
            )
        return _LIGHT_ALIASES[key]
    if isinstance(value, (set, frozenset, list, tuple)):
        keys = {normalize_light(item) for item in value}
        keys.discard(None)
        if not keys:
            return None
        return next(color for color in LIGHT_ORDER if color in keys)
    raise ValueError(
        f"未知灯带颜色: {value!r}"
        "（可用 red/green/blue/yellow/gray 或 红/绿/蓝/黄/灰，off 表示灭）"
    )


def normalize_light_freq(value) -> str:
    """把频率写法统一成 LIGHT_FREQUENCIES 的键（steady / 1hz / 0.5hz）。"""
    if value is None:
        return LIGHT_DEFAULT_FREQ
    if isinstance(value, LightFreq):
        return value.value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # 数值按 Hz 理解：0 / None → 常亮，1 → 1hz，0.5 → 0.5hz
        numeric = float(value)
        if numeric <= 0:
            return "steady"
        for key, half in LIGHT_FREQUENCIES.items():
            if half is not None and abs(numeric - 1000.0 / (2 * half)) < 1e-6:
                return key
        raise ValueError(f"未知灯带频率: {value!r}Hz（可用 0 / 1 / 0.5）")
    key = str(value).strip().lower().replace(" ", "")
    if key in _FREQ_ALIASES:
        return _FREQ_ALIASES[key]
    raise ValueError(
        f"未知灯带频率: {value!r}（可用 steady/常亮、1hz、0.5hz）"
    )


def describe_light(value) -> str:
    """把任意灯带状态转成可读文本，供 __str__ 使用。"""
    if value is None:
        return "不改"
    try:
        color = normalize_light(value)
    except ValueError:
        return repr(value)
    return "灭" if color is None else str(LightColor(color))


def normalize_axis(axis) -> str:
    """把 'X' / 'x轴' / 1 统一成 'x'，'Y' / 2 统一成 'y'。"""
    key = str(axis).strip().lower()
    if key in _AXIS_ALIASES:
        return _AXIS_ALIASES[key]
    raise ValueError(f"未知气缸轴: {axis!r}（可用 x / y）")


def normalize_cylinder_state(state) -> CylinderState:
    """把 True/False、'伸出'/'缩回'、'extended'/'retracted' 统一成 CylinderState。"""
    if isinstance(state, CylinderState):
        return state
    if isinstance(state, bool):
        return CylinderState.EXTENDED if state else CylinderState.RETRACTED
    if state in (0, 1):
        return CylinderState.EXTENDED if state else CylinderState.RETRACTED
    key = state.strip().lower() if isinstance(state, str) else state
    if key in _CYLINDER_ALIASES:
        return _CYLINDER_ALIASES[key]
    raise ValueError(f"未知气缸状态: {state!r}（可用 extended / retracted）")


def describe_light(value) -> str:
    """把任意灯带状态转成可读文本，供 __str__ 使用。"""
    if value is None:
        return "不改"
    if isinstance(value, bool):
        return "红" if value else "灭"
    try:
        color = normalize_light(value)
    except ValueError:
        return repr(value)
    return "灭" if color is None else str(LightColor(color))


def describe_light_freq(value) -> str:
    """把频率转成可读文本（常亮 / 1Hz / 0.5Hz）。"""
    try:
        return str(LightFreq(normalize_light_freq(value)))
    except ValueError:
        return repr(value)


_SENSOR_ALIASES = {
    "active": SensorState.ACTIVE,
    "on": SensorState.ACTIVE,
    "true": SensorState.ACTIVE,
    "1": SensorState.ACTIVE,
    "通": SensorState.ACTIVE,
    "有": SensorState.ACTIVE,
    "有料": SensorState.ACTIVE,
    "触发": SensorState.ACTIVE,
    "遮挡": SensorState.ACTIVE,
    "inactive": SensorState.INACTIVE,
    "off": SensorState.INACTIVE,
    "false": SensorState.INACTIVE,
    "0": SensorState.INACTIVE,
    "断": SensorState.INACTIVE,
    "无": SensorState.INACTIVE,
    "无料": SensorState.INACTIVE,
    "未触发": SensorState.INACTIVE,
    "unknown": SensorState.UNKNOWN,
    "未知": SensorState.UNKNOWN,
}


def normalize_sensor(value) -> SensorState:
    """把 True / False / '通' / '断' 之类统一成 SensorState。"""
    if isinstance(value, SensorState):
        return value
    if value is None:
        return SensorState.UNKNOWN
    if isinstance(value, bool):
        return SensorState.from_bool(value)
    if value in _SENSOR_ALIASES:
        return _SENSOR_ALIASES[value]
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _SENSOR_ALIASES:
            return _SENSOR_ALIASES[lowered]
    raise ValueError(
        f"未知传感器状态: {value!r}（可用 active/通/True 或 inactive/断/False）"
    )


def sensor_index_of(name) -> Optional[int]:
    """'托盘接近1' → 1；不是传感器名返回 None。"""
    for index, sensor_name in SENSOR_PARTS.items():
        if name == sensor_name:
            return index
    return None


# ---------------------------------------------------------------- 数据结构
@dataclass
class RackSlotStatus:
    """一个仓位的完整期望状态，供模型一次性套用。

    字段与 data2.json 的图元一一对应（每个仓位固定 18 个部件）：

        a / b / single   A库、B库、单库的料位（各含 空筒 / 实料 两层）
        pallet           托盘是否在仓位里（``托盘``）
        sensors           托盘接近 1 / 2 开关（``托盘接近1`` / ``托盘接近2``）
        light / freq      灯带颜色与闪烁频率（``灯带``，唯一一个本体图元）
        cylinders         X / Y 气缸位置
        number            仓位编号文本

    取值的写法：

    light：
        None                     不改
        True / False             兼容旧数据：True=红色常亮，False=灭
        LightColor / '红'        该色常亮（其余颜色互斥，直接覆盖）
        'off' / '灭'             灭
    light_freq：
        None                     常亮
        LightFreq / '1hz' / 1    闪烁频率，取值 steady / 1hz / 0.5hz
    color 与 freq 也可以合并成一个二元组传入：light=("红", "1hz")

    sensors：
        {1: True, 2: '断'} 或 '通断' 之类的写法；没写进去的传感器保持原样。
        含义同 ``托盘接近N`` 图元可见（通 / 有托盘）。

    cylinders：
        {"x": CylinderState.EXTENDED, ...}，没写进去的轴保持原样。

    构造时也接受 ``areas={"A": "空筒", ...}`` 这种“按区域一把设置”的写法，
    也可以在构造后用 ``set_area()`` / ``set_cylinders()`` 逐个补。
    """

    a: MaterialState = MaterialState.UNKNOWN
    b: MaterialState = MaterialState.UNKNOWN
    single: MaterialState = MaterialState.UNKNOWN
    pallet: Optional[bool] = None
    light: Optional[object] = None
    light_freq: Optional[object] = None
    cylinders: Dict[str, CylinderState] = field(default_factory=dict)
    # 托盘接近开关：序号 1/2 -> SensorState。空字典表示不改。
    sensors: Dict[int, SensorState] = field(default_factory=dict)
    # 仓位编号文本；None 表示不改
    number: Optional[object] = None
    # 只允许在构造时使用：areas={"A": "空筒", "B": "实料"}，会摊进 a / b / single
    areas: InitVar[Optional[Dict[str, object]]] = None

    def __post_init__(self, areas) -> None:
        if areas:
            for area, state in areas.items():
                self.set_area(area, state)

    # ------------------------------------------------------------ 组装
    def set_area(self, area, state) -> "RackSlotStatus":
        """按区域（A / B / single）设置料位，返回自身便于链式调用。"""
        key = normalize_area(area)
        value = normalize_state(state)
        if key == "A":
            self.a = value
        elif key == "B":
            self.b = value
        else:
            self.single = value
        return self

    def set_cylinders(self, **axes) -> "RackSlotStatus":
        """按轴设置气缸位置：set_cylinders(x='伸出', y='缩回')。"""
        for axis, state in axes.items():
            self.cylinders[axis] = state
        return self

    def set_sensor(self, index, state) -> "RackSlotStatus":
        """设置托盘接近开关：set_sensor(1, True) / set_sensor(2, '断')。"""
        index = int(index)
        if index not in SENSOR_PARTS:
            raise ValueError(f"未知传感器序号: {index!r}（可用 1 / 2）")
        self.sensors[index] = normalize_sensor(state)
        return self

    def set_light(self, color, freq=None) -> "RackSlotStatus":
        """设置灯带颜色 / 频率，返回自身便于链式调用。"""
        if isinstance(color, (tuple, list)) and len(color) == 2:
            color, freq = color
        self.light = color
        self.light_freq = freq
        return self

    # ------------------------------------------------------------ 归一化
    def normalized(self) -> "RackSlotStatus":
        """返回所有字段都已归一化的新对象（不修改自身）。"""
        cylinders: Dict[str, CylinderState] = {}
        for axis, state in (self.cylinders or {}).items():
            cylinders[normalize_axis(axis)] = normalize_cylinder_state(state)

        sensors: Dict[int, SensorState] = {}
        for index, state in (self.sensors or {}).items():
            index = int(index)
            if index not in SENSOR_PARTS:
                raise ValueError(f"未知传感器序号: {index!r}（可用 1 / 2）")
            sensors[index] = normalize_sensor(state)

        light, freq = self.light, self.light_freq
        if isinstance(light, (tuple, list)) and len(light) == 2:
            light, freq = light

        return RackSlotStatus(
            a=normalize_state(self.a),
            b=normalize_state(self.b),
            single=normalize_state(self.single),
            pallet=self.pallet,
            light=light,
            light_freq=freq,
            cylinders=cylinders,
            sensors=sensors,
            number=self.number,
        )

    # ------------------------------------------------------------ 读取
    def area_state(self, area) -> MaterialState:
        """按区域名读回料位状态。"""
        key = normalize_area(area)
        return {
            "A": normalize_state(self.a),
            "B": normalize_state(self.b),
            "single": normalize_state(self.single),
        }[key]

    def sensor_state(self, index) -> Optional[SensorState]:
        """按序号读回传感器状态；该序号未给出时返回 None（表示“不改”）。"""
        return (self.sensors or {}).get(int(index))

    def cylinder_state(self, axis) -> Optional[CylinderState]:
        """按轴读回气缸位置；该轴未给出时返回 None（表示“不改”）。"""
        state = (self.cylinders or {}).get(normalize_axis(axis))
        return None if state is None else normalize_cylinder_state(state)

    def is_empty(self) -> bool:
        """是否所有字段都是“不改”（用于跳过无意义的 apply）。"""
        return (
            self.a is MaterialState.UNKNOWN
            and self.b is MaterialState.UNKNOWN
            and self.single is MaterialState.UNKNOWN
            and self.pallet is None
            and self.light is None
            and self.number is None
            and not self.cylinders
            and not self.sensors
        )

    # ------------------------------------------------------------ 比对
    def diff(self, other: "RackSlotStatus") -> Dict[str, tuple]:
        """比较两个状态，返回 {字段名: (self 的值, other 的值)}。

        只比较两边都“明确给出”的字段：UNKNOWN 料位、None 托盘、
        未指定的气缸 / 传感器 / 灯带都不会产生差异项。
        用于“PLC 只报了变化的部分”时判断要不要刷新界面。
        """
        left, right = self.normalized(), other.normalized()
        result: Dict[str, tuple] = {}

        for area in AREA_ORDER:
            mine, theirs = left.area_state(area), right.area_state(area)
            if MaterialState.UNKNOWN in (mine, theirs):
                continue
            if mine != theirs:
                result[AREA_LABELS[area]] = (mine, theirs)

        if left.pallet is not None and right.pallet is not None:
            if bool(left.pallet) != bool(right.pallet):
                result["托盘"] = (
                    "有" if left.pallet else "无",
                    "有" if right.pallet else "无",
                )

        for axis in AXIS_ORDER:
            mine, theirs = left.cylinder_state(axis), right.cylinder_state(axis)
            if mine is None or theirs is None:
                continue
            if mine != theirs:
                result[f"{axis.upper()}气缸"] = (mine, theirs)

        for index in sorted(SENSOR_PARTS):
            mine = left.sensor_state(index)
            theirs = right.sensor_state(index)
            if mine is None or theirs is None:
                continue
            if mine is not SensorState.UNKNOWN and mine != theirs:
                result[f"接近{index}"] = (mine, theirs)

        if left.light is not None and right.light is not None:
            mine, theirs = describe_light(left.light), describe_light(right.light)
            if mine != theirs:
                result["灯带"] = (mine, theirs)
            elif (
                left.light_freq is not None
                and right.light_freq is not None
                and describe_light_freq(left.light_freq)
                != describe_light_freq(right.light_freq)
            ):
                result["灯带频率"] = (
                    describe_light_freq(left.light_freq),
                    describe_light_freq(right.light_freq),
                )

        if left.number is not None and right.number is not None:
            if str(left.number) != str(right.number):
                result["编号"] = (str(left.number), str(right.number))

        return result

    def __str__(self) -> str:
        parts = [
            f"A={normalize_state(self.a)}",
            f"B={normalize_state(self.b)}",
            f"单库={normalize_state(self.single)}",
        ]
        if self.pallet is not None:
            parts.append(f"托盘={'有' if self.pallet else '无'}")
        for index in sorted(self.sensors or {}):
            parts.append(f"接近{index}={normalize_sensor(self.sensors[index])}")
        if self.light is not None:
            light = describe_light(self.light)
            if self.light_freq is not None:
                light += "/" + describe_light_freq(self.light_freq)
            parts.append(f"灯={light}")
        for axis in AXIS_ORDER:
            state = self.cylinder_state(axis)
            if state is not None:
                parts.append(f"{axis.upper()}气缸={state}")
        if self.number is not None:
            parts.append(f"编号={self.number!r}")
        return "RackSlotStatus(" + "，".join(parts) + ")"


@dataclass
class RackSlot:
    """一个仓位：持有仓位组图元和它的语义部件表。"""

    rack_no: int
    slot_no: int
    group: Optional[group_element] = None
    parts: Dict[str, base_element] = field(default_factory=dict)
    number_label: Optional[text_element] = None

    # ------------------------------------------------------------ 灯带状态
    # 当前颜色（None 表示灯灭）与频率（默认常亮）
    light_color: Optional[LightColor] = None
    light_freq: LightFreq = LightFreq.STEADY
    # 闪烁定时器（懒创建，需要 QApplication 已存在）
    _blink_timer: Optional[QTimer] = field(default=None, repr=False, compare=False)
    _blink_on: bool = field(default=True, repr=False, compare=False)

    def _ensure_blink_timer(self) -> Optional[QTimer]:
        if self._blink_timer is None and QApplication.instance() is not None:
            timer = QTimer()
            timer.setTimerType(Qt.PreciseTimer)
            timer.timeout.connect(self._on_light_blink_tick)
            self._blink_timer = timer
        return self._blink_timer

    # ------------------------------------------------------------ 查询
    @property
    def number_label_position(self) -> QPointF:
        return self.number_label.get_scene_end_pos() if self.number_label is not None else QPointF(0, 0)
    
    @property
    def position(self) -> QPointF:
        return self.group.get_scene_head_pos() if self.group is not None else QPointF(0, 0)

    @property
    def key(self) -> tuple:
        return (self.rack_no, self.slot_no)

    @property
    def name(self) -> str:
        return f"料架{self.rack_no}_仓位{self.slot_no}"

    def part(self, name: str) -> Optional[base_element]:
        return self.parts.get(name)

    def has_part(self, name: str) -> bool:
        return name in self.parts

    def _first_part(self, names) -> Optional[base_element]:
        for name in names:
            item = self.parts.get(name)
            if item is not None:
                return item
        return None

    def _is_visible(self, name: str) -> bool:
        item = self.parts.get(name)
        return bool(item is not None and item.get_visibility())

    def background_parts(self) -> List[base_element]:
        """背景框：新命名 框1/框2/框3；旧命名 矩形_<序号> 兼容。"""
        found = [self.parts[name] for name in BACKGROUND_NAMES if name in self.parts]
        found.extend(
            item
            for key, item in self.parts.items()
            if key.startswith(BACKGROUND_LEGACY_PREFIX)
        )
        return found

    def missing_backgrounds(self) -> List[str]:
        """返回缺失的背景框名字；旧文件只有 矩形_* 时视为齐全。"""
        if any(name in self.parts for name in BACKGROUND_NAMES):
            return [name for name in BACKGROUND_NAMES if name not in self.parts]
        if any(key.startswith(BACKGROUND_LEGACY_PREFIX) for key in self.parts):
            return []
        return ["框1/框2/框3（背景）"]

    def missing_parts(self) -> List[str]:
        missing = [name for name in EXPECTED_SLOT_PARTS if name not in self.parts]
        # 灯带允许只有颜色层、气缸允许只有位置层（没有本体）
        if LIGHT in missing and self._first_part(_LIGHT_LAYER_CANDIDATES):
            missing.remove(LIGHT)
        for axis, base_name in (("x", CYLINDER_X), ("y", CYLINDER_Y)):
            if base_name not in missing:
                continue
            for names in CYLINDER_LAYER_NAMES[axis].values():
                if self._first_part(names):
                    missing.remove(base_name)
                    break
        missing.extend(self.missing_backgrounds())
        return missing

    # ------------------------------------------------------------ 显示控制
    def set_part_visible(self, name: str, visible: bool) -> bool:
        """返回是否真的发生了可见性变化（图元不存在或状态没变都返回 False）。"""
        item = self.parts.get(name)
        if item is None:
            return False
        before = bool(item.get_visibility())
        item.set_visibility(bool(visible))
        return bool(item.get_visibility()) != before

    def set_part_color(self, name: str, color) -> bool:
        """返回是否真的发生了颜色变化（图元不存在或颜色没变都返回 False）。"""
        item = self.parts.get(name)
        if item is None:
            return False
        before = item.get_fill_color()
        item.set_fill_color(color)
        return item.get_fill_color() != before

    def set_material(self, area, state) -> bool:
        """设置某个区域的料位状态（A/B/单库 → 空筒层 或 实料层）。

        area 支持两种写法：

            具体层名 'A库空筒' / 'A库实料'
                按“显示 / 隐藏这一层”处理，state 当 bool 用。

            区域 'A' / 'a' / 'A库' / '单库'
                state 按 MaterialState 解释，自动切换该区域的空筒层与实料层。

        注意：区域写法里不能用 bool(state)，MaterialState.EMPTY 作为枚举成员
        本来就是真值。
        """
        name = str(area).strip()
        if name in MATERIAL_LAYER_NAMES:
            # 直接给层名：显示/隐藏这一层
            self.set_part_visible(name, bool(state))
            return True

        empty_name, full_name = MATERIAL_LAYERS[normalize_area(area)]
        state = normalize_state(state)
        show_empty = state is MaterialState.EMPTY
        show_full = state in (MaterialState.FULL_1, MaterialState.FULL_2)
        changed = self.set_part_visible(empty_name, show_empty)
        return self.set_part_visible(full_name, show_full) or changed

    def material_state(self, area) -> MaterialState:
        """读回当前的料位状态（两层都不可见即 UNKNOWN）。"""
        empty_name, full_name = MATERIAL_LAYERS[normalize_area(area)]
        if self._is_visible(full_name):
            return MaterialState.FULL_1
        if self._is_visible(empty_name):
            return MaterialState.EMPTY
        return MaterialState.UNKNOWN

    def set_pallet(self, visible: bool) -> bool:
        return self.set_part_visible(PALLET, visible)

    def set_light_color(self, color, freq=None) -> bool:
        """设置灯带颜色与闪烁频率。

        color：红 / 绿 / 蓝 / 黄 / 灰（LightColor 或中英文写法）
               'off' / '灭' 表示关灯；None 表示不改颜色；
               True / False 兼容旧数据（True=红色，False=灭）。
               color 也可以是 (颜色, 频率) 二元组，此时忽略 freq 参数。
        freq ：常亮 / 1hz / 0.5hz（LightFreq 或 '常亮' / '1Hz' / '0.5Hz'），
               None 视为常亮。

        场景里每个仓位只有一个“灯带”本体矩形，因此颜色通过修改它的
        填充色与边框色实现；闪烁通过 Start/Stop 定时器周期切换可见性实现。
        """
        if color is None:
            return False
        if isinstance(color, bool):
            if not color:
                return self.turn_off_light()
            color = LIGHT_DEFAULT_COLOR
        if isinstance(color, (tuple, list)) and len(color) == 2:
            color, freq = color

        color_key = normalize_light(color)
        if color_key is None:
            return self.turn_off_light()

        freq_key = normalize_light_freq(freq)
        self.light_color = LightColor(color_key)
        self.light_freq = LightFreq(freq_key)

        changed = self._apply_light_paint(self.light_color)
        changed = self._apply_light_blink() or changed
        return changed

    def _apply_light_paint(self, color: LightColor) -> bool:
        """把颜色写进灯带本体并让其可见。"""
        item = self.parts.get(LIGHT)
        if item is None:
            return False
        changed = self.set_part_visible(LIGHT, True)
        for setter_name in ("set_fill_color", "set_color"):
            setter = getattr(item, setter_name, None)
            if setter is None:
                continue
            before = getattr(item, setter_name.replace("set_", "get_"), lambda: None)()
            setter(color.qcolor)
            after = getattr(item, setter_name.replace("set_", "get_"), lambda: None)()
            if before is not None and after is not None and before != after:
                changed = True
        return changed

    def _apply_light_blink(self) -> bool:
        """按当前频率启动 / 停止闪烁定时器。"""
        freq = self.light_freq or LightFreq.STEADY
        timer = self._ensure_blink_timer()
        if timer is None:
            # 没有 QApplication 时无法起定时器，退化成常亮
            self.set_part_visible(LIGHT, True)
            return False
        changed = False
        if freq.is_blinking():
            if timer.interval() != freq.half_period:
                timer.setInterval(freq.half_period)
                changed = True
            if not timer.isActive():
                timer.start()
                changed = True
        else:
            if timer.isActive():
                timer.stop()
                changed = True
            changed = self.set_part_visible(LIGHT, True) or changed
            self._blink_on = True
        return changed

    def _on_light_blink_tick(self) -> None:
        """闪烁定时器：在可见 / 隐藏之间切换。"""
        item = self.parts.get(LIGHT)
        if item is None or not self.is_light_blinking():
            self.stop_light_blink()
            return
        self._blink_on = not self._blink_on
        item.set_visibility(self._blink_on)

    def stop_light_blink(self) -> None:
        """停止闪烁并恢复常显（不改颜色）。"""
        if self._blink_timer is not None:
            self._blink_timer.stop()
        self.light_freq = LightFreq.STEADY
        self._blink_on = True

    def turn_off_light(self) -> bool:
        """关灯：停止闪烁并隐藏灯带本体。"""
        was_active = bool(self._blink_timer and self._blink_timer.isActive())
        if self._blink_timer is not None:
            self._blink_timer.stop()
        self.light_color = None
        self.light_freq = LightFreq.STEADY
        self._blink_on = True
        changed = self.set_part_visible(LIGHT, False)
        return changed or was_active

    def is_light_blinking(self) -> bool:
        return bool(self.light_freq and self.light_freq.is_blinking())

    def light_colors(self) -> Set[LightColor]:
        """当前灯带颜色集合（空集合表示灯灭）。"""
        if self.light_color is None or not self._is_visible(LIGHT):
            return set()
        return {self.light_color}

    def set_cylinder(self, axis, state) -> bool:
        """气缸位置。

        state：extended / '伸出' / True；retracted / '缩回' / False；
               None 表示两种位置都隐藏。
        缸体（X气缸 / Y气缸）在两种位置下都保持显示。
        """
        axis_key = normalize_axis(axis)
        base_name = CYLINDER_X if axis_key == "x" else CYLINDER_Y
        layers = CYLINDER_LAYER_NAMES[axis_key]
        if state is None:
            changed = self.set_part_visible(base_name, False)
            for names in layers.values():
                for name in names:
                    changed = self.set_part_visible(name, False) or changed
            return changed
        state = normalize_cylinder_state(state)
        changed = self.set_part_visible(base_name, True)
        for position, names in layers.items():
            for name in names:
                changed = self.set_part_visible(name, position == state.value) or changed
        return changed

    def cylinder_state(self, axis) -> Optional[CylinderState]:
        """当前气缸位置；场景里没有位置层时返回 None（例如旧数据只有缸体）。"""
        for position, names in CYLINDER_LAYER_NAMES[normalize_axis(axis)].items():
            for name in names:
                if self._is_visible(name):
                    return CylinderState(position)
        return None

    def set_sensor(self, index: int, state) -> bool:
        """设置托盘接近开关。state 接受 True / False / '通' / '断' / SensorState。"""
        name = SENSOR_PARTS.get(int(index))
        if name is None:
            raise ValueError(f"未知传感器序号: {index!r}（可用 1 / 2）")
        state = normalize_sensor(state)
        if state is SensorState.UNKNOWN:
            return False
        return self.set_part_visible(name, state is SensorState.ACTIVE)

    def sensor_state(self, index: int) -> SensorState:
        """读回托盘接近开关状态；图元缺失时返回 UNKNOWN。"""
        name = SENSOR_PARTS.get(int(index))
        if name is None:
            raise ValueError(f"未知传感器序号: {index!r}（可用 1 / 2）")
        if name not in self.parts:
            return SensorState.UNKNOWN
        return SensorState.from_bool(self._is_visible(name))

    def sensor_active(self, index: int) -> bool:
        """兼容旧接口：True 表示通（有托盘）。"""
        return self.sensor_state(index) is SensorState.ACTIVE

    def set_number(self, text) -> bool:
        """设置仓位编号文本（JSON 里编号是 text_element）。

        注意 text_element.context 的 setter 会强制在前后各补一个空格
        （渲染留白用），所以比较与对外读回都按 strip 后的文本处理。
        """
        if self.number_label is None:
            return False
        text = str(text).strip()
        if self.number().strip() == text:
            return False
        self.number_label.context = text
        return True

    def hide_all_state_layers(self) -> None:
        # 灯带也要跟着停：否则定时器会继续把灯带本体切回可见
        self.turn_off_light()
        for name in STATE_LAYER_PARTS:
            self.set_part_visible(name, False)

    def apply(self, status: RackSlotStatus) -> bool:
        """按 RackSlotStatus 刷新：料位每次重设，其余项只在明确给出时改动。

        返回是否真的有任何一项发生了变化，方便调用方决定要不要发信号。
        """
        status = status.normalized()
        changed = False
        changed = self.set_material("A", status.a) or changed
        changed = self.set_material("B", status.b) or changed
        changed = self.set_material("single", status.single) or changed
        if status.pallet is not None:
            changed = self.set_pallet(status.pallet) or changed
        if status.light is not None:
            changed = self.set_light_color(status.light, status.light_freq) or changed
        for axis in AXIS_ORDER:
            state = status.cylinder_state(axis)
            if state is not None:
                changed = self.set_cylinder(axis, state) or changed
        for index, state in status.sensors.items():
            changed = self.set_sensor(index, state) or changed
        if status.number is not None:
            changed = self.set_number(status.number) or changed
        return changed

    # ------------------------------------------------------------ 打印
    def _cylinder_text(self, axis: str) -> str:
        state = self.cylinder_state(axis)
        if state is not None:
            return str(state)
        base_name = CYLINDER_X if axis == "x" else CYLINDER_Y
        return "隐藏" if not self._is_visible(base_name) else "未知"

    def number(self) -> str:
        """仓位编号文本（已去掉 text_element 为渲染补的前后空格）。"""
        if self.number_label is None:
            return ""
        return str(self.number_label.context).strip()

    def status(self) -> RackSlotStatus:
        """读回当前显示出来的完整状态（与 RackStoreModel.status 对应）。"""
        cylinders: Dict[str, CylinderState] = {}
        for axis in AXIS_ORDER:
            state = self.cylinder_state(axis)
            if state is not None:
                cylinders[axis] = state

        sensors: Dict[int, SensorState] = {}
        for index in sorted(SENSOR_PARTS):
            state = self.sensor_state(index)
            if state is not SensorState.UNKNOWN:
                sensors[index] = state

        # 读回的是“完整快照”：灯灭时显式给 "off"，而不是 None。
        # 在 RackSlotStatus 的输入语义里 None 表示“不改”，两者不能混用。
        if self.light_colors():
            light, light_freq = self.light_color, self.light_freq
        else:
            light, light_freq = LIGHT_OFF, None

        return RackSlotStatus(
            a=self.material_state("A"),
            b=self.material_state("B"),
            single=self.material_state("single"),
            pallet=self._is_visible(PALLET),
            light=light,
            light_freq=light_freq,
            cylinders=cylinders,
            sensors=sensors,
            number=self.number() if self.number_label is not None else None,
        )

    def summary(self) -> str:
        """一行摘要，供 Rack / RackStoreModel 的 __str__ 使用。"""
        if self.light_color is not None and self._is_visible(LIGHT):
            light = str(self.light_color)
            if self.is_light_blinking():
                light += "/" + str(self.light_freq)
        else:
            light = "灭"
        number = self.number() if self.number_label is not None else None
        return (
            f"仓位{self.slot_no}: A={self.material_state('A')}"
            f" B={self.material_state('B')}"
            f" 单库={self.material_state('single')}"
            f" 托盘={'有' if self._is_visible(PALLET) else '无'}"
            f" 接近1={self.sensor_state(1)} 接近2={self.sensor_state(2)}"
            f" 灯={light}"
            f" 气缸 X={self._cylinder_text('x')} Y={self._cylinder_text('y')}"
            f" 编号={number!r}"
        )

    def __str__(self) -> str:
        lines = [
            f"{self.name}（{len(self.parts)} 个图元）",
            f"  {self.summary()}",
            "  传感器: "
            + " ".join(
                f"接近{index}={self.sensor_state(index)}"
                for index in sorted(SENSOR_PARTS)
            ),
        ]
        missing = self.missing_parts()
        if missing:
            lines.append(f"  缺少图元: {', '.join(missing)}")
        return "\n".join(lines)


@dataclass
class Rack:
    """一台料架：包含多个仓位和机台号文本。"""

    number: int
    group: Optional[group_element] = None
    machine_label: Optional[text_element] = None
    slots: Dict[int, RackSlot] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"料架{self.number}"
    @property
    def label_position(self) -> QPointF:
        return (
            self.machine_label.get_scene_end_pos()
            if self.machine_label is not None
            else QPointF(0, 0)
        )

    def slot(self, slot_no: int) -> Optional[RackSlot]:
        return self.slots.get(int(slot_no))

    def sorted_slots(self) -> List[RackSlot]:
        return [self.slots[no] for no in sorted(self.slots)]

    def sorted_slot_numbers(self) -> List[int]:
        """仓位号升序列表。"""
        return sorted(self.slots)

    def set_machine_number(self, text) -> bool:
        if self.machine_label is None:
            return False
        text = str(text)
        if self.machine_label.context == text:
            return False
        self.machine_label.context = text
        return True

    def setVisible(self, visible: bool) -> None:
        if self.group is not None:
            self.group.set_visibility(visible)
        for slot in self.slots.values():
            if slot.group is not None:
                slot.group.set_visibility(visible)

    def __str__(self) -> str:
        number = self.machine_label.context if self.machine_label is not None else None
        lines = [f"{self.name}（{len(self.slots)} 个仓位，机台编号={number!r}）"]
        lines.extend(f"  {slot.summary()}" for slot in self.sorted_slots())
        return "\n".join(lines)


class RackStoreModel(QObject):
    """料仓图元模型：从 SceneManager 构建，按 (料架, 仓位, 语义) 访问图元。

    图元是靠名字识别的，所以 ``refresh()`` 必须在场景重新加载（例如再次
    调用 ``load_element_info2``）之后调用，旧引用会随图元删除而失效。
    """

    # 某个仓位的显示状态发生了变化
    slot_changed = Signal(int, int)
    # 某个仓位被点击（connect_slot_clicks=True 时才生效）
    slot_clicked = Signal(int, int)

    def __init__(self, scene_manager, parent=None, connect_slot_clicks=False):
        super().__init__(parent)
        self._manager = scene_manager
        self._connect_slot_clicks = bool(connect_slot_clicks)
        self.racks: Dict[int, Rack] = {}
        self.warnings: List[str] = []
        self._items_by_name: Dict[str, base_element] = {}
        self._click_groups = weakref.WeakSet()
        self.refresh()

    # ------------------------------------------------------------ 构建
    def refresh(self) -> None:
        """按当前场景内容重建索引（图元增删、场景重载后调用）。"""
        self.racks.clear()
        self.warnings.clear()
        self._items_by_name.clear()

        manager = self._manager
        if manager is None:
            self.warnings.append("SceneManager 为空，料仓模型为空")
            return

        items = [item for item in manager.m_items.values() if item is not None]
        for item in items:
            name = item.get_name()
            if not name:
                continue
            if name in self._items_by_name:
                self.warnings.append(f"图元重名，已忽略后一个：{name}")
                continue
            self._items_by_name[name] = item
            self._register(item, name)

        self._validate()

    def _rack(self, rack_no: int) -> Rack:
        rack = self.racks.get(rack_no)
        if rack is None:
            rack = Rack(number=rack_no)
            self.racks[rack_no] = rack
        return rack

    def _slot(self, rack_no: int, slot_no: int) -> RackSlot:
        rack = self._rack(rack_no)
        slot = rack.slots.get(slot_no)
        if slot is None:
            slot = RackSlot(rack_no=rack_no, slot_no=slot_no)
            rack.slots[slot_no] = slot
        return slot

    def _register(self, item: base_element, name: str) -> None:
        match = MACHINE_LABEL_RE.match(name)
        if match:
            self._rack(int(match.group("rack"))).machine_label = item
            return

        match = RACK_NAME_RE.match(name)
        if match:
            self._rack(int(match.group("rack"))).group = item
            return

        match = SLOT_NAME_RE.match(name)
        if match:
            self._slot(int(match.group("rack")), int(match.group("slot"))).group = item
            return

        match = SLOT_PART_NAME_RE.match(name)
        if not match:
            return
        slot = self._slot(int(match.group("rack")), int(match.group("slot")))
        part_name = match.group("part")
        slot.parts[part_name] = item
        if part_name == NUMBER and isinstance(item, text_element):
            slot.number_label = item

    def _validate(self) -> None:
        for rack_no in sorted(self.racks):
            rack = self.racks[rack_no]
            if rack.group is None:
                self.warnings.append(
                    f"料架{rack_no} 缺少料架组图元（名字应为 料架{rack_no}）"
                )
            for slot_no in sorted(rack.slots):
                slot = rack.slots[slot_no]
                if slot.group is None:
                    self.warnings.append(f"{slot.name} 缺少仓位组图元")
                missing = slot.missing_parts()
                if missing:
                    self.warnings.append(f"{slot.name} 缺少图元：{', '.join(missing)}")

        if self._connect_slot_clicks:
            for rack in self.racks.values():
                for slot in rack.slots.values():
                    if slot.group is None:
                        continue
                    slot.group.set_interactive(True)
                    # refresh() 可能被多次调用，避免重复连接导致 slot_clicked 重复发射
                    if slot.group in self._click_groups:
                        continue
                    self._click_groups.add(slot.group)
                    slot.group.clicked.connect(
                        lambda r=rack.number, s=slot.slot_no: self.slot_clicked.emit(r, s)
                    )

    # ------------------------------------------------------------ 访问
    def rack(self, rack_no: int) -> Optional[Rack]:
        return self.racks.get(int(rack_no))

    def racks_sorted(self) -> List[Rack]:
        return [self.racks[no] for no in sorted(self.racks)]

    def rack_numbers(self) -> List[int]:
        """场景里实际存在的料架号（升序）。"""
        return sorted(self.racks)

    def slot_visible(self, rack_no: int, slot_no: int) -> bool:
        """仓位组当前是否显示（被主机配置隐藏的仓位返回 False）。"""
        slot = self.slot(rack_no, slot_no)
        if slot is None or slot.group is None:
            return False
        return bool(slot.group.get_visibility())

    def slot_numbers(self, rack_no: int) -> List[int]:
        """某台料架下实际存在的仓位号（升序）。"""
        rack = self.rack(rack_no)
        return [] if rack is None else rack.sorted_slot_numbers()

    def slot(self, rack_no: int, slot_no: int) -> Optional[RackSlot]:
        rack = self.rack(rack_no)
        return None if rack is None else rack.slot(slot_no)

    def part(self, rack_no: int, slot_no: int, name: str) -> Optional[base_element]:
        slot = self.slot(rack_no, slot_no)
        return None if slot is None else slot.part(name)

    def status(self, rack_no: int, slot_no: int) -> Optional[RackSlotStatus]:
        """读回某个仓位当前显示出来的状态（打印 / 比对用）。"""
        slot = self.slot(rack_no, slot_no)
        return None if slot is None else slot.status()

    def statuses(self) -> Dict[Tuple[int, int], RackSlotStatus]:
        """读回全仓状态：{(料架号, 仓位号): RackSlotStatus}。"""
        result: Dict[Tuple[int, int], RackSlotStatus] = {}
        for rack in self.racks_sorted():
            for slot in rack.sorted_slots():
                result[slot.key] = slot.status()
        return result

    def diff_status(
        self, expected: Dict[Tuple[int, int], RackSlotStatus]
    ) -> Dict[Tuple[int, int], Dict[str, tuple]]:
        """比较“期望状态”与“当前显示”，返回不一致的仓位。

        expected：{(料架号, 仓位号): RackSlotStatus}
        返回：{(料架号, 仓位号): {字段: (当前值, 期望值)}}，只含有差异的仓位。

        典型用法是在 PLC 回报变化后先算 diff，再只对差异项发 slot_changed。
        """
        result: Dict[Tuple[int, int], Dict[str, tuple]] = {}
        for key, want in expected.items():
            slot = self.slot(*key)
            if slot is None:
                continue
            delta = slot.status().diff(want)
            if delta:
                result[key] = delta
        return result

    def describe(self) -> str:
        """一行摘要，便于启动时打印/排查命名问题。"""
        slot_count = sum(len(rack.slots) for rack in self.racks.values())
        text = (
            f"料仓模型：{len(self.racks)} 台料架，{slot_count} 个仓位，"
            f"{len(self._items_by_name)} 个已识别图元"
        )
        if self.warnings:
            text += f"，{len(self.warnings)} 条警告"
        return text

    def __str__(self) -> str:
        """多行概览：每台料架一行标题 + 每仓位一行摘要 + 警告列表。"""
        lines = [self.describe()]
        for rack in self.racks_sorted():
            number = (
                rack.machine_label.context if rack.machine_label is not None else None
            )
            lines.append(f"  {rack.name}（机台编号={number!r}）")
            lines.extend(f"    {slot.summary()}" for slot in rack.sorted_slots())
        if self.warnings:
            lines.append("  警告:")
            lines.extend(f"    - {message}" for message in self.warnings)
        return "\n".join(lines)

    # ------------------------------------------------------------ 写入
    def _changed(self, rack_no: int, slot_no: int, changed: bool) -> bool:
        if changed:
            self.slot_changed.emit(int(rack_no), int(slot_no))
        return changed

    def set_material(self, rack_no: int, slot_no: int, area, state) -> bool:
        """设置某个区域的料位：state = MaterialState / 'empty' / 'full' / 0 / 1。"""
        slot = self.slot(rack_no, slot_no)
        if slot is None:
            return False
        return self._changed(rack_no, slot_no, slot.set_material(area, state))

    def set_pallet(self, rack_no: int, slot_no: int, visible: bool) -> bool:
        slot = self.slot(rack_no, slot_no)
        if slot is None:
            return False
        return self._changed(rack_no, slot_no, slot.set_pallet(visible))

    def set_light(self, rack_no: int, slot_no: int, color, freq=None) -> bool:
        """灯带：color=红/绿/蓝/黄/灰 或 'off'；freq=常亮/1hz/0.5hz。"""
        slot = self.slot(rack_no, slot_no)
        if slot is None:
            return False
        return self._changed(rack_no, slot_no, slot.set_light_color(color, freq))

    def set_cylinder(self, rack_no: int, slot_no: int, axis, state) -> bool:
        """气缸：axis = 'x'/'y'，state = CylinderState / '伸出' / '缩回' / True / False / None。"""
        slot = self.slot(rack_no, slot_no)
        if slot is None:
            return False
        return self._changed(rack_no, slot_no, slot.set_cylinder(axis, state))

    def set_slot_number(self, rack_no: int, slot_no: int, text) -> bool:
        slot = self.slot(rack_no, slot_no)
        if slot is None:
            return False
        return self._changed(rack_no, slot_no, slot.set_number(text))

    def set_machine_number(self, rack_no: int, text) -> bool:
        rack = self.rack(rack_no)
        if rack is None:
            return False
        return rack.set_machine_number(text)

    def apply_status(self, rack_no: int, slot_no: int, status: RackSlotStatus,
                     emit: bool = True) -> bool:
        """按 RackSlotStatus 一次性刷新一个仓位。

        emit=False 用于批量同步（例如状态模型整体回灌），避免逐个仓位发信号。
        返回是否真的发生了变化。
        """
        slot = self.slot(rack_no, slot_no)
        if slot is None:
            return False
        changed = slot.apply(status)
        if changed and emit:
            self.slot_changed.emit(int(rack_no), int(slot_no))
        return changed

    def hide_all(self) -> None:
        """隐藏所有仓位的状态层（例如数据断开时）。"""
        for rack in self.racks.values():
            for slot in rack.slots.values():
                slot.hide_all_state_layers()
                self.slot_changed.emit(rack.number, slot.slot_no)

    def setVisible_slot(self, rack_no: int, slot_no: int, visible: bool) -> None:
        """显示/隐藏某个仓位组图元（不影响仓位状态层）。"""
        slot = self.slot(rack_no, slot_no)
        if slot is None:
            return
        if slot.group is not None:
            slot.group.set_visibility(visible)


    def setVisible_rack(self, rack_no: int, visible: bool) -> None:
        """显示/隐藏某个料架及其所有仓位。"""
        rack = self.rack(rack_no)
        if rack is None:
            return
        rack.setVisible(visible)



    def get_position(self, rack_no: int, slot_no: int,) -> QPointF:
        """返回仓位组图元的场景坐标（没有图元时返回 (0, 0)）。"""
        slot = self.slot(rack_no, slot_no)
        if slot is None:
            return QPointF(0, 0)
        return slot.number_label_position




