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
    │   ├── 料架1_仓位1_A库空筒 / A库实料           rect   料位示意层（只显示其中一层）
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
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

from PyQt6.QtCore import QObject, pyqtSignal

from .my_elements import base_element, group_element, text_element

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

# 背景框：新命名 框1/框2/框3；旧命名 矩形_<序号>（序号不稳定，按前缀识别）
BACKGROUND_NAMES = ("框1", "框2", "框3")
BACKGROUND_LEGACY_PREFIX = "矩形"

# 区域 -> (空筒层, 实料层)，同一时刻只显示其中一层
MATERIAL_LAYERS = {
    "A": ("A库空筒", "A库实料"),
    "B": ("B库空筒", "B库实料"),
    "single": ("单库空筒", "单库实料"),
}

# 灯带三种颜色 -> 候选图元名（按顺序取第一个存在的）
LIGHT_LAYER_NAMES = {
    "red": (LIGHT + "红", LIGHT + "_红", LIGHT + "红灯", LIGHT + "红色", "红灯", "红"),
    "green": (LIGHT + "绿", LIGHT + "_绿", LIGHT + "绿灯", LIGHT + "绿色", "绿灯", "绿"),
    "yellow": (LIGHT + "黄", LIGHT + "_黄", LIGHT + "黄灯", LIGHT + "黄色", "黄灯", "黄"),
}
# 显示顺序：红 → 绿 → 黄
LIGHT_ORDER = ("red", "green", "yellow")

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

# 所有候选的“状态层”名字（灯带颜色层 + 气缸位置层 + 料位层）
_STATE_LAYER_CANDIDATES = tuple(
    [name for group in MATERIAL_LAYERS.values() for name in group]
    + [name for group in LIGHT_LAYER_NAMES.values() for name in group]
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
    FULL = "full"

    def __str__(self) -> str:
        return {"unknown": "未知", "empty": "空筒", "full": "实料"}[self.value]


class LightColor(Enum):
    """灯带颜色（可以同时点亮多个颜色）。"""

    RED = "red"
    GREEN = "green"
    YELLOW = "yellow"

    def __str__(self) -> str:
        return {"red": "红", "green": "绿", "yellow": "黄"}[self.value]


class CylinderState(Enum):
    """气缸位置：伸出 / 缩回。"""

    EXTENDED = "extended"
    RETRACTED = "retracted"

    def __str__(self) -> str:
        return {"extended": "伸出", "retracted": "缩回"}[self.value]


# ---------------------------------------------------------------- 写法归一化
_AREA_ALIASES = {
    "a": "A",
    "b": "B",
    "single": "single",
    "单": "single",
    "单库": "single",
    "单库位": "single",
}

_STATE_ALIASES = {
    "unknown": MaterialState.UNKNOWN,
    "未知": MaterialState.UNKNOWN,
    None: MaterialState.UNKNOWN,
    -1: MaterialState.UNKNOWN,
    "empty": MaterialState.EMPTY,
    "空": MaterialState.EMPTY,
    "空筒": MaterialState.EMPTY,
    0: MaterialState.EMPTY,
    "full": MaterialState.FULL,
    "实料": MaterialState.FULL,
    "满料": MaterialState.FULL,
    1: MaterialState.FULL,
}

# 颜色写法 -> 颜色 key，None 表示“全灭”
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
    "yellow": "yellow",
    "y": "yellow",
    "黄": "yellow",
    "黄色": "yellow",
    "黄灯": "yellow",
    "黄态": "yellow",
    "off": None,
    "none": None,
    "灭": None,
    "全灭": None,
    "关": None,
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
    """把 'A' / 'a' / '单库' 之类的写法统一成 MATERIAL_LAYERS 的键。"""
    key = str(area).strip()
    lowered = key.lower()
    if lowered in _AREA_ALIASES:
        return _AREA_ALIASES[lowered]
    if key in MATERIAL_LAYERS:
        return key
    raise ValueError(f"未知料位区域: {area!r}（可用 A / B / single）")


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


def normalize_light(value) -> Set[str]:
    """把灯带颜色写法统一成颜色 key 集合，空集合表示全灭。"""
    if isinstance(value, LightColor):
        return {value.value}
    if isinstance(value, str):
        key = value.strip().lower()
        if key not in _LIGHT_ALIASES:
            raise ValueError(
                f"未知灯带颜色: {value!r}（可用 red / green / yellow / off）"
            )
        color = _LIGHT_ALIASES[key]
        return set() if color is None else {color}
    if isinstance(value, (set, frozenset, list, tuple)):
        colors: Set[str] = set()
        for item in value:
            colors |= normalize_light(item)
        return colors
    raise ValueError(f"未知灯带颜色: {value!r}（可用 red / green / yellow / off）")


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
        return "亮" if value else "灭"
    try:
        colors = normalize_light(value)
    except ValueError:
        return repr(value)
    if not colors:
        return "灭"
    return "+".join(
        str(LightColor(color)) for color in LIGHT_ORDER if color in colors
    )


# ---------------------------------------------------------------- 数据结构
@dataclass
class RackSlotStatus:
    """一个仓位的完整期望状态，供模型一次性套用。

    light：
        None                不改
        True / False        旧数据单层灯带（True 时若场景没有 灯带 本体则点亮红色）
        LightColor / '红'   该色亮，其余色灭
        {RED, GREEN}        多色同时亮
        'off' / '灭'        全灭
    cylinders：
        {"x": CylinderState.EXTENDED, ...}，没写进去的轴保持原样。
    """

    a: MaterialState = MaterialState.UNKNOWN
    b: MaterialState = MaterialState.UNKNOWN
    single: MaterialState = MaterialState.UNKNOWN
    pallet: Optional[bool] = None
    light: Optional[object] = None
    cylinders: Dict[str, CylinderState] = field(default_factory=dict)

    def normalized(self) -> "RackSlotStatus":
        cylinders: Dict[str, CylinderState] = {}
        for axis, state in (self.cylinders or {}).items():
            cylinders[normalize_axis(axis)] = normalize_cylinder_state(state)
        return RackSlotStatus(
            a=normalize_state(self.a),
            b=normalize_state(self.b),
            single=normalize_state(self.single),
            pallet=self.pallet,
            light=self.light,
            cylinders=cylinders,
        )

    def __str__(self) -> str:
        parts = [f"A={self.a}", f"B={self.b}", f"单库={self.single}"]
        if self.pallet is not None:
            parts.append(f"托盘={'有' if self.pallet else '无'}")
        if self.light is not None:
            parts.append(f"灯={describe_light(self.light)}")
        for axis in sorted(self.cylinders or {}):
            parts.append(f"{str(axis).upper()}气缸={self.cylinders[axis]}")
        return "RackSlotStatus(" + "，".join(parts) + ")"


# 灯带所有候选颜色层名字
_LIGHT_LAYER_CANDIDATES = tuple(
    name for group in LIGHT_LAYER_NAMES.values() for name in group
)


@dataclass
class RackSlot:
    """一个仓位：持有仓位组图元和它的语义部件表。"""

    rack_no: int
    slot_no: int
    group: Optional[group_element] = None
    parts: Dict[str, base_element] = field(default_factory=dict)
    number_label: Optional[text_element] = None

    # ------------------------------------------------------------ 查询
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

    def set_material(self, area, state) -> bool:
        """设置某个区域的料位状态（A/B/单库 → 空筒层 或 实料层）。"""
        empty_name, full_name = MATERIAL_LAYERS[normalize_area(area)]
        state = normalize_state(state)
        changed = self.set_part_visible(empty_name, state is MaterialState.EMPTY)
        return self.set_part_visible(full_name, state is MaterialState.FULL) or changed

    def material_state(self, area) -> MaterialState:
        """读回当前的料位状态（两层都不可见即 UNKNOWN）。"""
        empty_name, full_name = MATERIAL_LAYERS[normalize_area(area)]
        if self._is_visible(full_name):
            return MaterialState.FULL
        if self._is_visible(empty_name):
            return MaterialState.EMPTY
        return MaterialState.UNKNOWN

    def set_pallet(self, visible: bool) -> bool:
        return self.set_part_visible(PALLET, visible)

    def set_light(self, state) -> bool:
        """灯带（红 / 绿 / 黄三色）。

        state：
            None                  不改
            True / False          兼容旧数据：只控制 灯带 本体；
                                  True 且场景里没有 灯带 本体时点亮红色
            LightColor / '红'     该色亮、其余色灭（本体同时显示）
            {RED, GREEN} / ['红']  多色同时亮
            'off' / '灭' / 空集合  全灭
        """
        if state is None:
            return False
        if isinstance(state, bool):
            if state and LIGHT not in self.parts:
                return self._set_light_colors({"red"})
            changed = self.set_part_visible(LIGHT, state)
            for names in LIGHT_LAYER_NAMES.values():
                for name in names:
                    changed = self.set_part_visible(name, False) or changed
            return changed
        return self._set_light_colors(normalize_light(state))

    def _set_light_colors(self, colors) -> bool:
        colors = set(colors)
        changed = self.set_part_visible(LIGHT, bool(colors))
        for color, names in LIGHT_LAYER_NAMES.items():
            for name in names:
                changed = self.set_part_visible(name, color in colors) or changed
        return changed

    def light_colors(self) -> Set[LightColor]:
        """当前点亮的灯带颜色集合。"""
        colors: Set[LightColor] = set()
        for color, names in LIGHT_LAYER_NAMES.items():
            for name in names:
                if self._is_visible(name):
                    colors.add(LightColor(color))
                    break
        return colors

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

    def set_sensor(self, index: int, active: bool) -> bool:
        name = {1: SENSOR_PALLET_1, 2: SENSOR_PALLET_2}.get(int(index))
        if name is None:
            raise ValueError(f"未知传感器序号: {index!r}（可用 1 / 2）")
        return self.set_part_visible(name, active)

    def sensor_active(self, index: int) -> bool:
        name = {1: SENSOR_PALLET_1, 2: SENSOR_PALLET_2}.get(int(index))
        if name is None:
            raise ValueError(f"未知传感器序号: {index!r}（可用 1 / 2）")
        return self._is_visible(name)

    def set_number(self, text) -> bool:
        """设置仓位编号文本（JSON 里编号是 text_element）。"""
        if self.number_label is None:
            return False
        text = str(text)
        if self.number_label.context == text:
            return False
        self.number_label.context = text
        return True

    def hide_all_state_layers(self) -> None:
        for name in STATE_LAYER_PARTS:
            self.set_part_visible(name, False)

    def apply(self, status: RackSlotStatus) -> None:
        """按 RackSlotStatus 刷新：料位每次重设，其余项只在明确给出时改动。"""
        status = status.normalized()
        self.set_material("A", status.a)
        self.set_material("B", status.b)
        self.set_material("single", status.single)
        if status.pallet is not None:
            self.set_pallet(status.pallet)
        if status.light is not None:
            self.set_light(status.light)
        for axis, state in status.cylinders.items():
            self.set_cylinder(axis, state)

    # ------------------------------------------------------------ 打印
    def _cylinder_text(self, axis: str) -> str:
        state = self.cylinder_state(axis)
        if state is not None:
            return str(state)
        base_name = CYLINDER_X if axis == "x" else CYLINDER_Y
        return "隐藏" if not self._is_visible(base_name) else "未知"

    def summary(self) -> str:
        """一行摘要，供 Rack / RackStoreModel 的 __str__ 使用。"""
        colors = self.light_colors()
        if colors:
            light = "+".join(
                str(LightColor(color)) for color in LIGHT_ORDER if LightColor(color) in colors
            )
        else:
            light = "亮" if self._is_visible(LIGHT) else "灭"
        number = self.number_label.context if self.number_label is not None else None
        return (
            f"仓位{self.slot_no}: A={self.material_state('A')}"
            f" B={self.material_state('B')}"
            f" 单库={self.material_state('single')}"
            f" 托盘={'有' if self._is_visible(PALLET) else '无'}"
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
                f"接近{index}={'通' if self.sensor_active(index) else '断'}"
                for index in (1, 2)
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

    def slot(self, slot_no: int) -> Optional[RackSlot]:
        return self.slots.get(int(slot_no))

    def sorted_slots(self) -> List[RackSlot]:
        return [self.slots[no] for no in sorted(self.slots)]

    def set_machine_number(self, text) -> bool:
        if self.machine_label is None:
            return False
        text = str(text)
        if self.machine_label.context == text:
            return False
        self.machine_label.context = text
        return True

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
    slot_changed = pyqtSignal(int, int)
    # 某个仓位被点击（connect_slot_clicks=True 时才生效）
    slot_clicked = pyqtSignal(int, int)

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

    def slot(self, rack_no: int, slot_no: int) -> Optional[RackSlot]:
        rack = self.rack(rack_no)
        return None if rack is None else rack.slot(slot_no)

    def part(self, rack_no: int, slot_no: int, name: str) -> Optional[base_element]:
        slot = self.slot(rack_no, slot_no)
        return None if slot is None else slot.part(name)

    def status(self, rack_no: int, slot_no: int) -> Optional[RackSlotStatus]:
        """读回某个仓位当前显示出来的状态（打印 / 比对用）。"""
        slot = self.slot(rack_no, slot_no)
        if slot is None:
            return None
        cylinders: Dict[str, CylinderState] = {}
        for axis in ("x", "y"):
            state = slot.cylinder_state(axis)
            if state is not None:
                cylinders[axis] = state
        colors = slot.light_colors()
        light = colors if colors else slot._is_visible(LIGHT)
        return RackSlotStatus(
            a=slot.material_state("A"),
            b=slot.material_state("B"),
            single=slot.material_state("single"),
            pallet=slot._is_visible(PALLET),
            light=light,
            cylinders=cylinders,
        )

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

    def set_light(self, rack_no: int, slot_no: int, state) -> bool:
        """灯带：LightColor / '红' / {RED, GREEN} / True / False / 'off'。"""
        slot = self.slot(rack_no, slot_no)
        if slot is None:
            return False
        return self._changed(rack_no, slot_no, slot.set_light(state))

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

    def apply_status(self, rack_no: int, slot_no: int, status: RackSlotStatus) -> bool:
        """按 RackSlotStatus 一次性刷新一个仓位。"""
        slot = self.slot(rack_no, slot_no)
        if slot is None:
            return False
        slot.apply(status)
        self.slot_changed.emit(int(rack_no), int(slot_no))
        return True

    def hide_all(self) -> None:
        """隐藏所有仓位的状态层（例如数据断开时）。"""
        for rack in self.racks.values():
            for slot in rack.slots.values():
                slot.hide_all_state_layers()
                self.slot_changed.emit(rack.number, slot.slot_no)









