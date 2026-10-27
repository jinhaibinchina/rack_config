"""料仓状态数据模型（与绘图解耦的业务状态层）。

本模块与 ``rack_store_model.py`` 是两个层次：

    rack_store_model.py       图元层：把 data2.json 的图元名字映射成语义部件，
                              读写的是 QGraphicsScene 里的真实对象。
    rack_stores_status_model.py（本模块）
                              状态层：只保存“每个仓位现在是什么状态”，
                              不持有任何图元引用，也不需要 QGraphicsScene。

这样分层的好处：

  * 状态可以先于界面存在——PLC 数据已经收到，但场景还没加载完；
  * 界面重载（再次 ``load_element_info2``）不会丢状态，重新灌一次即可；
  * 单元测试不需要构造 1581 个图元、不需要 QApplication 跑事件循环；
  * 变化检测集中在 ``status_delta``，UI 只订阅信号，不用自己比对。

data2.json 里每个仓位固定 18 个部件，归并成 7 个状态维度：

    料位 A / B / 单库     各含 空筒 / 实料 两层（同一时刻只显示一层）
    托盘                  ``托盘`` 有 / 无
    托盘接近 1 / 2        ``托盘接近1`` / ``托盘接近2`` 通 / 断
    X / Y 气缸            各含 伸出 / 缩回 两个位置层
    灯带                  颜色 + 闪烁频率（只有一个本体，不是分层）
    编号                  ``编号`` 文本

典型用法：

    status = RackStoreStatusModel(graphics_model)

    # 单点改：只改灯带
    status.set_light(2, 1, "绿", "1hz")

    # 一次改多项
    status.set_status(2, 1, RackSlotStatus(
        areas={"A": "空筒", "B": "空筒"},
        pallet=False,
        sensors={1: "断", 2: "断"},
        number="07",
    ))

    # 批量改（只发一次 bulk_changed）
    with status.batch():
        for slot_no in range(1, 9):
            status.set_area(2, slot_no, "A", "空筒")

    # 灌到场景
    status.apply_to_graphics()

    # 订阅变化
    status.slot_changed.connect(on_slot_changed)
    status.slot_changed_detail.connect(on_slot_detail)   # 带差异字典
"""

from contextlib import contextmanager
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from PySide6.QtCore import QObject, Signal

from .rack_store_model import (
    AREA_LABELS,
    AREA_ORDER,
    AXIS_ORDER,
    LIGHT_OFF,
    SENSOR_PARTS,
    CylinderState,
    LightColor,
    LightFreq,
    MaterialState,
    RackSlotStatus,
    SensorState,
    normalize_area,
    normalize_light,
    normalize_light_freq,
    normalize_state,
)

__all__ = [
    "SlotKey",
    "DEFAULT_RACK_COUNT",
    "DEFAULT_SLOTS_PER_RACK",
    "empty_status",
    "copy_status",
    "status_fields",
    "status_delta",
    "visual_key",
    "RackStoreStatusModel",
]

# (料架号, 仓位号)
SlotKey = Tuple[int, int]

# data2.json 的实际规模：10 台料架 × 每台 8 个仓位
DEFAULT_RACK_COUNT = 10
DEFAULT_SLOTS_PER_RACK = 8


# ---------------------------------------------------------------- 状态工具
def empty_status() -> RackSlotStatus:
    """一个仓位的初始状态：灯带灭，料位未知（未知 = 两个料位层都隐藏）。"""
    return RackSlotStatus(light=LIGHT_OFF)


def copy_status(status: RackSlotStatus, **changes) -> RackSlotStatus:
    """复制一个状态并覆盖部分字段。

    不用 ``dataclasses.replace``，因为 ``RackSlotStatus.areas`` 是 InitVar，
    构造后不再是实例属性，replace 会取不到它的值。
    """
    st = status.normalized()
    data = {
        "a": st.a,
        "b": st.b,
        "single": st.single,
        "pallet": st.pallet,
        "light": st.light,
        "light_freq": st.light_freq,
        "cylinders": dict(st.cylinders),
        "sensors": dict(st.sensors),
        "number": st.number,
    }
    data.update(changes)
    return RackSlotStatus(**data)


def _light_labels(status: RackSlotStatus) -> Tuple[str, Optional[str]]:
    """返回 (灯带, 频率) 的可读文本；灯灭时频率为 None。

    ``RackSlotStatus`` 里 None 与 "off" 都表示灭（前者是“不改”的默认值，
    后者是显式关灯），这里统一归一成同一个可读值，避免同一个状态
    因为内部写法不同而被判成“有变化”。
    """
    if status.light is None:
        return "灭", None
    key = normalize_light(status.light)
    if key is None:
        return "灭", None
    return str(LightColor(key)), str(LightFreq(normalize_light_freq(status.light_freq)))


def status_fields(status: RackSlotStatus) -> Dict[str, object]:
    """把状态摊平成 {字段名: 可读值}，顺序固定（打印与比较都用它）。"""
    st = status.normalized()
    fields: Dict[str, object] = {}

    for area in AREA_ORDER:
        fields[AREA_LABELS[area]] = st.area_state(area)

    fields["托盘"] = st.pallet

    for index in sorted(SENSOR_PARTS):
        fields[f"接近{index}"] = st.sensor_state(index)

    for axis in AXIS_ORDER:
        fields[f"{axis.upper()}气缸"] = st.cylinder_state(axis)

    light, freq = _light_labels(st)
    fields["灯带"] = light
    fields["灯带频率"] = freq

    fields["编号"] = st.number
    return fields


#: 料位状态 → 画面上实际能看见的层。场景里每个区域只有「空筒 / 实料」两层，
#: 所以 FULL_1 与 FULL_2 视觉上无法区分，反读时要折成同一个值。
_MATERIAL_VISUAL = {
    MaterialState.UNKNOWN: "unknown",
    MaterialState.EMPTY: "empty",
    MaterialState.FULL_1: "full",
    MaterialState.FULL_2: "full",
}


def visual_key(status: RackSlotStatus) -> Tuple:
    """把状态折叠成“画面上能看出来的东西”。

    从图形层反读状态时用它判等：读回来的 ``FULL_1`` 与状态模型里的
    ``FULL_2`` 视觉完全一致，此时不该拿 ``FULL_1`` 覆盖，否则会丢信息。
    """
    st = status.normalized()
    light = normalize_light(st.light)
    return (
        _MATERIAL_VISUAL[st.a],
        _MATERIAL_VISUAL[st.b],
        _MATERIAL_VISUAL[st.single],
        st.pallet,
        light,
        normalize_light_freq(st.light_freq) if light else None,
        tuple(sorted((str(k), str(v)) for k, v in st.cylinders.items())),
        tuple(sorted((int(k), str(v)) for k, v in st.sensors.items())),
        st.number,
    )


def status_delta(
    old: RackSlotStatus, new: RackSlotStatus
) -> Dict[str, Tuple[object, object]]:
    """严格比较两个状态快照，返回 ``{字段: (旧值, 新值)}``。

    与 ``RackSlotStatus.diff`` 的区别：

        diff         只比较两边都“明确给出”的字段，适合“PLC 只报了一部分变化”
                     的场景；
        status_delta 全部字段都参与比较（UNKNOWN、None 也算具体值），适合
                     判断“界面显示到底变没变”。

    状态模型内部存的是完整快照，所以变化检测必须用严格比较，否则
    “未知 → 空筒”这种变化会被漏掉。
    """
    left, right = status_fields(old), status_fields(new)
    delta: Dict[str, Tuple[object, object]] = {}
    for name, old_value in left.items():
        new_value = right.get(name)
        if old_value != new_value:
            delta[name] = (old_value, new_value)
    return delta


# ---------------------------------------------------------------- 状态模型
class RackStoreStatusModel(QObject):
    """料仓状态数据模型：料架 / 仓位 / 每仓位的完整状态。

    槽位是 ``(料架号, 仓位号)``，均从 1 开始，与 data2.json 的命名一致。
    默认按 data2.json 的实际规模建 10 × 8 = 80 个槽位。

    信号：

        slot_changed(rack, slot)          某个仓位的状态变了
        slot_changed_detail(rack, slot, delta)
                                         同上，附带 {字段: (旧值, 新值)}
        rack_changed(rack)                某台料架下有仓位变化（聚合信号）
        bulk_changed(keys)                批量更新结束，keys 为变化的槽位列表
        layout_changed(rack_count, slots_per_rack)
                                         槽位规模或启用状态变了

    注意：``bulk_changed`` 之后仍会补发逐个 ``slot_changed``，方便只关心
    单仓位的订阅方；只想刷一次的订阅方监听 ``bulk_changed`` 并在回调里
    读 ``statuses()`` 即可。
    """

    slot_changed = Signal(int, int)
    slot_changed_detail = Signal(int, int, object)
    rack_changed = Signal(int)
    bulk_changed = Signal(list)
    layout_changed = Signal(int, int)

    def __init__(
        self,
        source_model=None,
        parent=None,
        rack_count: int = DEFAULT_RACK_COUNT,
        slots_per_rack: int = DEFAULT_SLOTS_PER_RACK,
    ):
        """source_model 可以是 RackStoreModel，也可以是 SceneManager。

        传 SceneManager 时会自动包一层 RackStoreModel（不启用点击信号），
        以便沿用原来 ``RackStoreStatusModel(scene_manager)`` 的写法。
        """
        super().__init__(parent)
        self._rack_count = 0
        self._slots_per_rack = 0
        self._slots: Dict[SlotKey, RackSlotStatus] = {}
        self._machine_numbers: Dict[int, str] = {}
        self._enabled_racks: Set[int] = set()
        self._enabled_slots: Dict[int, Set[int]] = {}
        # PLC 里的机型枚举（DB7 的第一个 int），只用于显示，不参与机台号
        self._host_type = 0

        # 图形层（弱引用语义：只用于同步，不作为所有权）
        self._graphics = None

        # 批量更新期间：挂起信号，累积 {槽位: [旧状态, 新状态]}
        self._suppress = 0
        self._pending: Dict[SlotKey, List[RackSlotStatus]] = {}

        self._build_layout(rack_count, slots_per_rack)
        if source_model is not None:
            self.bind_source_model(source_model)

    # ------------------------------------------------------------ 槽位规模
    def _build_layout(self, rack_count: int, slots_per_rack: int) -> None:
        rack_count = max(0, int(rack_count))
        slots_per_rack = max(0, int(slots_per_rack))
        self._rack_count = rack_count
        self._slots_per_rack = slots_per_rack

        self._slots.clear()
        self._enabled_racks.clear()
        self._enabled_slots.clear()
        for rack_no in range(1, rack_count + 1):
            self._enabled_racks.add(rack_no)
            self._enabled_slots[rack_no] = set()
            for slot_no in range(1, slots_per_rack + 1):
                self._slots[(rack_no, slot_no)] = empty_status()
                self._enabled_slots[rack_no].add(slot_no)

    @property
    def rack_count(self) -> int:
        return self._rack_count

    @property
    def slots_per_rack(self) -> int:
        return self._slots_per_rack

    def configure(self, rack_count: int, slots_per_rack: int, emit: bool = True) -> None:
        """重设槽位规模。已有槽位的状态尽量保留，新增的用初始状态。"""
        old = self._slots
        old_enabled_racks = set(self._enabled_racks)
        old_enabled_slots = {k: set(v) for k, v in self._enabled_slots.items()}

        self._build_layout(rack_count, slots_per_rack)

        for key, status in old.items():
            if key in self._slots:
                self._slots[key] = status
        self._enabled_racks = {
            no for no in old_enabled_racks if no in range(1, self._rack_count + 1)
        }
        for rack_no, slots in old_enabled_slots.items():
            if rack_no in self._enabled_slots:
                self._enabled_slots[rack_no] = {
                    no for no in slots if no in range(1, self._slots_per_rack + 1)
                }

        if emit:
            self.layout_changed.emit(self._rack_count, self._slots_per_rack)

    def reset(self) -> None:
        """清空所有状态，回到初始快照（规模不变）。"""
        self.clear(emit=False)
        for key in self._slots:
            self._slots[key] = empty_status()
        self.bulk_changed.emit([])

    # ------------------------------------------------------------ 槽位查询
    def slot_keys(self) -> List[SlotKey]:
        """所有槽位，按 (料架号, 仓位号) 升序。"""
        return sorted(self._slots)

    def rack_numbers(self) -> List[int]:
        return sorted({rack_no for rack_no, _ in self._slots})

    def slot_numbers(self, rack_no: int) -> List[int]:
        rack_no = int(rack_no)
        return sorted(slot_no for r, slot_no in self._slots if r == rack_no)

    def has_slot(self, rack_no: int, slot_no: int) -> bool:
        return (int(rack_no), int(slot_no)) in self._slots

    def enabled_slot_keys(self) -> List[SlotKey]:
        """启用中的槽位（PLC 配置里存在的料架 / 仓位）。"""
        return [
            key
            for key in self.slot_keys()
            if self.is_slot_enabled(key[0], key[1])
        ]

    # ------------------------------------------------------------ 启用状态
    def set_rack_enabled(self, rack_no: int, enabled: bool) -> bool:
        """启用 / 停用一台料架。停用不影响已保存的状态。"""
        rack_no = int(rack_no)
        enabled = bool(enabled)
        if enabled:
            if rack_no in self._enabled_racks:
                return False
            self._enabled_racks.add(rack_no)
        else:
            if rack_no not in self._enabled_racks:
                return False
            self._enabled_racks.discard(rack_no)
        self.layout_changed.emit(self._rack_count, self._slots_per_rack)
        return True

    def set_slot_enabled(self, rack_no: int, slot_no: int, enabled: bool) -> bool:
        """启用 / 停用一个仓位（料架停用时仓位一律视为停用）。"""
        rack_no, slot_no = int(rack_no), int(slot_no)
        slots = self._enabled_slots.setdefault(rack_no, set())
        enabled = bool(enabled)
        if enabled:
            if slot_no in slots:
                return False
            slots.add(slot_no)
        else:
            if slot_no not in slots:
                return False
            slots.discard(slot_no)
        self.layout_changed.emit(self._rack_count, self._slots_per_rack)
        return True

    def is_rack_enabled(self, rack_no: int) -> bool:
        return int(rack_no) in self._enabled_racks

    def is_slot_enabled(self, rack_no: int, slot_no: int) -> bool:
        rack_no, slot_no = int(rack_no), int(slot_no)
        return (
            rack_no in self._enabled_racks
            and slot_no in self._enabled_slots.get(rack_no, set())
        )

    def apply_host_config(
        self,
        host_type,
        host_start_no,
        host_count: int,
        rack_counts: Sequence[int],
        emit: bool = True,
    ) -> None:
        """按 PLC DB7 的主机配置刷新启用状态与机台号。

        与 ``plc_window.ConfigWindow.handle_rack_status`` 的入参一致：
        host_type / host_start_No / host_count / 每台主机下的料架数。
        机台号与现场约定相同：第 i 台主机（从 0 数）的机台号 = 起始号 + i，
        host_type 只是机型枚举，不参与机台号拼接，单独保存在 ``host_type``。
        rack_counts 比 host_count 短时，多出来的主机按 0 个仓位处理
        （原界面实现会直接 IndexError）。
        这里只负责状态，不碰图元；要同步到界面再调 ``apply_enabled_to_graphics``。
        """
        # 机型：PLC 给的是 int 枚举，也允许直接传机型名文本
        try:
            self._host_type = int(host_type)
        except (TypeError, ValueError):
            self._host_type = host_type
        host_count = max(0, min(int(host_count), self._rack_count))
        rack_counts = list(rack_counts or [])

        for rack_no in range(1, self._rack_count + 1):
            index = rack_no - 1
            if index < host_count:
                self._enabled_racks.add(rack_no)
                self._machine_numbers[rack_no] = str(index + int(host_start_no))
                count = rack_counts[index] if index < len(rack_counts) else 0
                count = max(0, min(int(count), self._slots_per_rack))
                self._enabled_slots[rack_no] = set(range(1, count + 1))
            else:
                self._enabled_racks.discard(rack_no)
                self._enabled_slots[rack_no] = set()

        if emit:
            self.layout_changed.emit(self._rack_count, self._slots_per_rack)

    @property
    def host_type(self):
        """机型：PLC 的 int 枚举，或调用方直接传入的机型文本。"""
        return self._host_type

    def machine_number(self, rack_no: int) -> str:
        """机台号文本（``料架N_机台编号``）。"""
        return self._machine_numbers.get(int(rack_no), "")

    def set_machine_number(self, rack_no: int, text) -> bool:
        rack_no = int(rack_no)
        text = "" if text is None else str(text).strip()
        if self._machine_numbers.get(rack_no, "") == text:
            return False
        self._machine_numbers[rack_no] = text
        self.rack_changed.emit(rack_no)
        return True

    # ------------------------------------------------------------ 读状态
    def status(self, rack_no: int, slot_no: int) -> Optional[RackSlotStatus]:
        """读某个仓位的状态快照；槽位不存在返回 None。

        返回的是副本，调用方随便改都不会影响模型内部。
        """
        stored = self._slots.get((int(rack_no), int(slot_no)))
        return None if stored is None else copy_status(stored)

    def statuses(self) -> Dict[SlotKey, RackSlotStatus]:
        """全部槽位的状态快照（副本）。"""
        return {key: copy_status(status) for key, status in self._slots.items()}

    def rack_statuses(self, rack_no: int) -> Dict[int, RackSlotStatus]:
        """某台料架下所有仓位的状态快照。"""
        rack_no = int(rack_no)
        return {
            slot_no: copy_status(status)
            for (r, slot_no), status in self._slots.items()
            if r == rack_no
        }

    # ------------------------------------------------------------ 写状态
    def _as_snapshot(self, status: RackSlotStatus) -> RackSlotStatus:
        """归一化成“完整快照”：灯带显式给 off / 颜色，频率给 key。

        状态模型内部只存快照，这样变化检测和序列化都不会有 None 歧义。
        """
        if not isinstance(status, RackSlotStatus):
            status = RackSlotStatus()

        st = status.normalized()

        light_key = normalize_light(st.light)
        if light_key is None:
            st.light = LIGHT_OFF
            st.light_freq = None
        else:
            st.light = LightColor(light_key)
            st.light_freq = LightFreq(normalize_light_freq(st.light_freq))

        if st.number is not None:
            st.number = str(st.number).strip()

        return st

    def _commit(self, key: SlotKey, new_status: RackSlotStatus, emit: bool = True) -> bool:
        """写入一个槽位，返回是否真的有变化。"""
        old = self._slots.get(key)
        new_status = self._as_snapshot(new_status)

        if old is None:
            self._slots[key] = new_status
            delta = status_delta(empty_status(), new_status)
        else:
            delta = status_delta(old, new_status)
            if not delta:
                return False
            self._slots[key] = new_status

        if not emit:
            return True

        if self._suppress:
            entry = self._pending.get(key)
            if entry is None:
                self._pending[key] = [old or empty_status(), new_status]
            else:
                entry[1] = new_status
            return True

        self.slot_changed.emit(key[0], key[1])
        self.slot_changed_detail.emit(key[0], key[1], delta)
        self.rack_changed.emit(key[0])
        return True

    def set_status(
        self, rack_no: int, slot_no: int, status: RackSlotStatus, emit: bool = True
    ) -> bool:
        """整套替换一个仓位的状态。槽位不存在时返回 False。"""
        key = (int(rack_no), int(slot_no))
        if key not in self._slots:
            return False
        return self._commit(key, status, emit)

    def update_status(self, rack_no: int, slot_no: int, **fields) -> bool:
        """只改指定字段，其余保持原值。

        例：``update_status(2, 1, pallet=True, number="07")``
        """
        key = (int(rack_no), int(slot_no))
        current = self._slots.get(key)
        if current is None:
            return False
        return self._commit(key, copy_status(current, **fields))

    def set_many(self, mapping: Mapping[SlotKey, RackSlotStatus]) -> List[SlotKey]:
        """批量写入 {槽位: 状态}，只发一次 bulk_changed。返回实际变化的槽位。"""
        changed: List[SlotKey] = []
        with self.batch():
            for key, status in mapping.items():
                rack_no, slot_no = key
                if self.set_status(rack_no, slot_no, status):
                    changed.append((int(rack_no), int(slot_no)))
        return changed

    def clear(
        self, rack_no: Optional[int] = None, slot_no: Optional[int] = None
    ) -> List[SlotKey]:
        """把指定范围重置成初始状态。

        clear()                 全部
        clear(2)                料架 2 的所有仓位
        clear(2, 3)             料架 2 的仓位 3
        """
        if rack_no is None:
            keys = self.slot_keys()
        elif slot_no is None:
            keys = [(int(rack_no), no) for no in self.slot_numbers(rack_no)]
        else:
            keys = [(int(rack_no), int(slot_no))]

        changed: List[SlotKey] = []
        with self.batch():
            for key in keys:
                if self._commit(key, empty_status()):
                    changed.append(key)
        return changed

    # ------------------------------------------------------------ 单字段快捷写
    def set_area(self, rack_no: int, slot_no: int, area, state) -> bool:
        """设置某区域料位：set_area(2, 1, 'A', '空筒')。"""
        key = (int(rack_no), int(slot_no))
        current = self._slots.get(key)
        if current is None:
            return False
        return self._commit(
            key, copy_status(current).set_area(area, normalize_state(state))
        )

    def set_areas(self, rack_no: int, slot_no: int, areas: Mapping[str, object]) -> bool:
        """一次设置多个区域：set_areas(2, 1, {'A': '空筒', 'B': '实料'})。"""
        key = (int(rack_no), int(slot_no))
        current = self._slots.get(key)
        if current is None:
            return False
        status = copy_status(current)
        for area, state in areas.items():
            status.set_area(area, state)
        return self._commit(key, status)

    def set_pallet(self, rack_no: int, slot_no: int, visible) -> bool:
        """设置托盘有无。visible=None 表示未知。"""
        key = (int(rack_no), int(slot_no))
        current = self._slots.get(key)
        if current is None:
            return False
        value = None if visible is None else bool(visible)
        return self._commit(key, copy_status(current, pallet=value))

    def set_sensor(self, rack_no: int, slot_no: int, index: int, state) -> bool:
        """设置托盘接近开关：set_sensor(2, 1, 1, '通')。"""
        key = (int(rack_no), int(slot_no))
        current = self._slots.get(key)
        if current is None:
            return False
        status = copy_status(current)
        status.set_sensor(index, state)
        return self._commit(key, status)

    def set_sensors(self, rack_no: int, slot_no: int, sensors: Mapping[int, object]) -> bool:
        """一次设置多个传感器：set_sensors(2, 1, {1: '通', 2: '断'})。"""
        key = (int(rack_no), int(slot_no))
        current = self._slots.get(key)
        if current is None:
            return False
        status = copy_status(current)
        for index, state in sensors.items():
            status.set_sensor(index, state)
        return self._commit(key, status)

    def set_cylinder(self, rack_no: int, slot_no: int, axis, state) -> bool:
        """设置气缸位置：set_cylinder(2, 1, 'x', '伸出')。"""
        key = (int(rack_no), int(slot_no))
        current = self._slots.get(key)
        if current is None:
            return False
        status = copy_status(current)
        status.set_cylinders(**{str(axis): state})
        return self._commit(key, status)

    def set_light(self, rack_no: int, slot_no: int, color, freq=None) -> bool:
        """设置灯带：set_light(2, 1, '绿', '1hz')；color='灭' 表示关灯。"""
        key = (int(rack_no), int(slot_no))
        current = self._slots.get(key)
        if current is None:
            return False
        status = copy_status(current)
        status.set_light(color, freq)
        return self._commit(key, status)

    def set_number(self, rack_no: int, slot_no: int, text) -> bool:
        """设置仓位编号文本。"""
        key = (int(rack_no), int(slot_no))
        current = self._slots.get(key)
        if current is None:
            return False
        value = None if text is None else str(text).strip()
        return self._commit(key, copy_status(current, number=value))

    def clear_lights(self) -> List[SlotKey]:
        """全仓关灯（换班 / 复位时用）。"""
        changed: List[SlotKey] = []
        with self.batch():
            for key, status in list(self._slots.items()):
                if status.light != LIGHT_OFF:
                    if self._commit(key, copy_status(status, light=LIGHT_OFF, light_freq=None)):
                        changed.append(key)
        return changed

    # ------------------------------------------------------------ 批量上下文
    @contextmanager
    def batch(self):
        """批量更新：期间不发信号，退出时合并成一次 bulk_changed。

        嵌套使用时只有最外层负责发信号。
        """
        self._suppress += 1
        try:
            yield self
        finally:
            self._suppress -= 1
            if self._suppress == 0 and self._pending:
                pending = self._pending
                self._pending = {}
                keys = sorted(pending)
                self.bulk_changed.emit([tuple(k) for k in keys])
                for rack_no in sorted({k[0] for k in keys}):
                    self.rack_changed.emit(rack_no)
                for key in keys:
                    old, new = pending[key]
                    self.slot_changed.emit(key[0], key[1])
                    self.slot_changed_detail.emit(
                        key[0], key[1], status_delta(old, new)
                    )

    # ------------------------------------------------------------ 差异
    def diff(
        self, expected: Mapping[SlotKey, RackSlotStatus]
    ) -> Dict[SlotKey, Dict[str, Tuple[object, object]]]:
        """比较“期望状态”与“当前状态”，返回有差异的槽位。

        与 ``RackSlotStatus.diff`` 不同，这里用的是严格比较
        （见 ``status_delta``），所以“未知 → 空筒”也能被检测到。
        """
        result: Dict[SlotKey, Dict[str, Tuple[object, object]]] = {}
        for key, want in expected.items():
            current = self._slots.get((int(key[0]), int(key[1])))
            if current is None:
                continue
            delta = status_delta(current, want)
            if delta:
                result[(int(key[0]), int(key[1]))] = delta
        return result

    def changed_slots(
        self, other: Mapping[SlotKey, RackSlotStatus]
    ) -> List[SlotKey]:
        """哪些槽位与 other 不一致（只返回槽位号）。"""
        return sorted(self.diff(other))

    # ------------------------------------------------------------ 统计
    def count_area(
        self, area, only_enabled: bool = False
    ) -> Dict[MaterialState, int]:
        """统计某个区域各料位状态的仓位数。"""
        area_key = normalize_area(area)
        result = {state: 0 for state in MaterialState}
        for key, status in self._slots.items():
            if only_enabled and not self.is_slot_enabled(*key):
                continue
            result[status.normalized().area_state(area_key)] += 1
        return result

    def count_lights(self, only_enabled: bool = False) -> Dict[str, int]:
        """统计灯带：{'灭': n, '红': n, ...}。"""
        result: Dict[str, int] = {}
        for key, status in self._slots.items():
            if only_enabled and not self.is_slot_enabled(*key):
                continue
            light, _freq = _light_labels(status)
            result[light] = result.get(light, 0) + 1
        return result

    def summary(self) -> str:
        """一行概览。"""
        total = len(self._slots)
        enabled = len(self.enabled_slot_keys())
        lights = self.count_lights()
        light_text = " ".join(
            f"{name}={count}" for name, count in sorted(lights.items())
        )
        return (
            f"料仓状态：{self._rack_count} 台料架 × {self._slots_per_rack} 仓位"
            f"（共 {total} 个，启用 {enabled} 个）；灯带 {light_text or '无'}"
        )

    def format_table(
        self, rack_no: Optional[int] = None, only_enabled: bool = True
    ) -> str:
        """表格形式的状态明细，便于现场排查。"""
        headers = ["料架", "仓位", "A库", "B库", "单库", "托盘",
                   "接近1", "接近2", "X缸", "Y缸", "灯带", "编号"]
        rows: List[str] = ["  ".join(headers)]

        for key in self.slot_keys():
            if rack_no is not None and key[0] != int(rack_no):
                continue
            if only_enabled and not self.is_slot_enabled(*key):
                continue
            status = self._slots[key].normalized()
            fields = status_fields(status)
            light, freq = fields["灯带"], fields["灯带频率"]
            light_text = f"{light}/{freq}" if freq and light != "灭" else light
            rows.append(
                "  ".join(
                    [
                        str(key[0]),
                        str(key[1]),
                        str(fields["A库"]),
                        str(fields["B库"]),
                        str(fields["单库"]),
                        "有" if fields["托盘"] else ("?" if fields["托盘"] is None else "无"),
                        str(fields["接近1"]),
                        str(fields["接近2"]),
                        str(fields["X气缸"]),
                        str(fields["Y气缸"]),
                        light_text,
                        str(fields["编号"] or "-"),
                    ]
                )
            )
        return "\n".join(rows)

    def __str__(self) -> str:
        return self.summary()

    # ------------------------------------------------------------ 与图形层同步
    def _resolve_graphics(self, model=None):
        """确定要同步的图形模型：优先用参数，其次用绑定的那个。"""
        if model is not None:
            return self._coerce_graphics(model)
        return self._graphics

    @staticmethod
    def _coerce_graphics(obj):
        """把 RackStoreModel / SceneManager 统一成 RackStoreModel。"""
        if obj is None:
            return None
        if hasattr(obj, "racks") and hasattr(obj, "slot"):
            return obj
        if hasattr(obj, "m_items"):
            from .rack_store_model import RackStoreModel

            return RackStoreModel(obj)
        return None

    def bind_source_model(self, source_model) -> bool:
        """绑定图形模型，并把场景里现有的状态读进来作为初始值。

        只建立“状态 → 图形”的单向同步；图形层不反向推动状态，
        避免两边互相触发形成循环。
        """
        graphics = self._coerce_graphics(source_model)
        if graphics is None:
            return False
        self._graphics = graphics
        self.capture_from_graphics(graphics, emit=False)
        return True

    @property
    def graphics_model(self):
        return self._graphics

    def capture_from_graphics(self, model=None, emit: bool = False) -> List[SlotKey]:
        """把场景当前显示的状态读进状态模型，返回变化的槽位。

        会跳过被隐藏的仓位：隐藏仓位组时底层 ``set_visibility`` 会把组内
        所有子图元的可见标志一起清成 False，此时读出来是 UNKNOWN，
        不能拿它覆盖状态模型里已经记住的真实状态。

        视觉等价的状态不会覆盖（例如图上的“实料”读回来一律是 FULL_1，
        不能把状态模型里的 FULL_2 降级）。
        """
        graphics = self._resolve_graphics(model)
        if graphics is None:
            return []

        changed: List[SlotKey] = []
        with self.batch():
            for key in self.slot_keys():
                if not graphics.slot_visible(*key):
                    continue
                status = graphics.status(*key)
                if status is None:
                    continue
                current = self._slots.get(key)
                if current is not None and visual_key(current) == visual_key(status):
                    continue
                if self._commit(key, status, emit=emit):
                    changed.append(key)
        return changed

    def apply_to_graphics(
        self, model=None, only_enabled: bool = False
    ) -> List[SlotKey]:
        """把状态灌到场景，返回真正发生变化的槽位。"""
        graphics = self._resolve_graphics(model)
        if graphics is None:
            return []

        changed: List[SlotKey] = []
        for key, status in self._slots.items():
            if only_enabled and not self.is_slot_enabled(*key):
                continue
            if graphics.apply_status(key[0], key[1], status, emit=False):
                changed.append(key)
        return changed

    def apply_enabled_to_graphics(self, model=None, restore_state: bool = True) -> None:
        """按启用状态显示 / 隐藏料架与仓位（对应 PLC 的主机配置）。

        停用的料架整体隐藏，启用料架下停用的仓位隐藏。
        ``restore_state``：显示出来的仓位顺便把状态重新灌一遍。因为隐藏组会
        把组内子图元的可见标志一并清掉，不重灌的话重新启用后会显示不正确。
        """
        graphics = self._resolve_graphics(model)
        if graphics is None:
            return

        for rack_no in graphics.rack_numbers():
            graphics.setVisible_rack(rack_no, self.is_rack_enabled(rack_no))
            number = self.machine_number(rack_no)
            if number:
                graphics.rack(rack_no).set_machine_number(number)
            for slot_no in graphics.slot_numbers(rack_no):
                enabled = self.is_slot_enabled(rack_no, slot_no)
                graphics.setVisible_slot(rack_no, slot_no, enabled)
                if enabled and restore_state:
                    status = self._slots.get((rack_no, slot_no))
                    if status is not None:
                        graphics.apply_status(rack_no, slot_no, status, emit=False)

    # ------------------------------------------------------------ 序列化
    def to_dict(self) -> Dict[str, object]:
        """转成可 JSON 序列化的字典。"""
        slots: Dict[str, Dict[str, object]] = {}
        for (rack_no, slot_no), status in sorted(self._slots.items()):
            st = status.normalized()
            light_key = normalize_light(st.light)
            slots[f"{rack_no}:{slot_no}"] = {
                "a": st.a.value,
                "b": st.b.value,
                "single": st.single.value,
                "pallet": st.pallet,
                "sensors": {str(k): v.value for k, v in st.sensors.items()},
                "cylinders": {k: v.value for k, v in st.cylinders.items()},
                "light": light_key or LIGHT_OFF,
                "light_freq": normalize_light_freq(st.light_freq),
                "number": st.number,
            }

        return {
            "rack_count": self._rack_count,
            "slots_per_rack": self._slots_per_rack,
            "enabled_racks": sorted(self._enabled_racks),
            "enabled_slots": {
                str(rack_no): sorted(slots_) 
                for rack_no, slots_ in sorted(self._enabled_slots.items())
            },
            "machine_numbers": {str(k): v for k, v in sorted(self._machine_numbers.items())},
            "slots": slots,
        }

    def load_dict(self, data: Mapping[str, object], emit: bool = False) -> None:
        """从 ``to_dict()`` 的结果恢复。"""
        if not data:
            return

        rack_count = int(data.get("rack_count", self._rack_count))
        slots_per_rack = int(data.get("slots_per_rack", self._slots_per_rack))
        self._build_layout(rack_count, slots_per_rack)

        enabled_racks = data.get("enabled_racks")
        if enabled_racks is not None:
            self._enabled_racks = {int(no) for no in enabled_racks}
        enabled_slots = data.get("enabled_slots") or {}
        if enabled_slots:
            self._enabled_slots = {
                int(rack_no): {int(no) for no in slots}
                for rack_no, slots in enabled_slots.items()
            }

        self._machine_numbers = {
            int(k): str(v) for k, v in (data.get("machine_numbers") or {}).items()
        }

        with self.batch():
            for key_text, payload in (data.get("slots") or {}).items():
                rack_no, _, slot_no = str(key_text).partition(":")
                key = (int(rack_no), int(slot_no))
                if key not in self._slots:
                    continue
                status = RackSlotStatus(
                    a=payload.get("a"),
                    b=payload.get("b"),
                    single=payload.get("single"),
                    pallet=payload.get("pallet"),
                    sensors={
                        int(index): state
                        for index, state in (payload.get("sensors") or {}).items()
                    },
                    cylinders=dict(payload.get("cylinders") or {}),
                    light=payload.get("light", LIGHT_OFF),
                    light_freq=payload.get("light_freq"),
                    number=payload.get("number"),
                )
                self._commit(key, status, emit=emit)

        self.layout_changed.emit(self._rack_count, self._slots_per_rack)

    def save_json(self, path: str) -> bool:
        """存成 JSON 文件；失败返回 False。"""
        import json
        import os

        try:
            directory = os.path.dirname(os.path.abspath(path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(self.to_dict(), fp, ensure_ascii=False, indent=1)
            return True
        except OSError as error:
            print(f"保存料仓状态失败({path}): {error}")
            return False

    def load_json(self, path: str, emit: bool = False) -> bool:
        """从 JSON 文件恢复；文件不存在或格式错误返回 False。"""
        import json
        import os

        if not os.path.isfile(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, ValueError) as error:
            print(f"读取料仓状态失败({path}): {error}")
            return False

        self.load_dict(data, emit=emit)
        return True
