



from PySide6.QtWidgets import QApplication,QWidget, QListWidget, QMessageBox, QFrame, QDialog, QToolButton,QVBoxLayout,QHBoxLayout,QLabel,QListWidgetItem
from PySide6.QtGui import QIcon,QAction,QColor
from PySide6.QtCore import Qt, QObject, QEvent ,Signal,QPointF
from Designer.Core.myQuadTreeScene import QuadTreeScene,SceneManager
from Designer.Core.elements import group_element,text_element

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple
from .rack_store_model import RackStoreModel
from .rack_status_panel_model import RackStatusPanelModel
from .rack_store_hmi_config_model import RackHmiConfigModel
from .rack_store_process_model import RackProcessModel

from Designer.Core.my_common import SceneMode

class RackStoresWindow(QWidget):

    slot_clicked = Signal(int,int)  # rack_no, slot_no    

    def __init__(self, parent = None):
        super().__init__(parent)

        self.Scene = QuadTreeScene(parent=self)
        self.Scene.set_scene_mode(SceneMode.Run)
        self.SceneManager = SceneManager(self.Scene, parent=self)
        self.Scene.set_scene_manager(self.SceneManager)
        self.Scene.load_element_info_run_mode('rack_config_scene2.json')
        # self.Scene.goto_sence_origin()
        layout =QVBoxLayout(self)
        layout.addWidget(self.Scene)
        self.setLayout(layout)


        self.rack_store_model = RackStoreModel(self.SceneManager, self,
                                               connect_slot_clicks=True)
  
        print(self.rack_store_model)

        # 同一场景里还有「料仓状态」面板（data2.json id=1584）：两块 IO 模块指示灯 + 4 个文本
        self.panel_status = RackStatusPanelModel(self.SceneManager, self)
        self.Scene.double_clicked_without_group.connect(self.handle_double_click_without_group)  # 双击空白处时隐藏面板

        self.rack_hmi_config_models = [RackHmiConfigModel(self.SceneManager, self,group_name=f"HMI{i+1}") for i in range(5)]  # HMI1..HMI5

        self.rack_process_model = RackProcessModel(self.SceneManager, self)

        if self.panel_status.warnings:
            if not self.SceneManager.m_items:
                # 场景是空的：多半是打包后没把 myDesigner/data2.json 带上，
                # 这时逐条列 9 个"缺少图元"没意义，直接提示根因。
                print("场景为空（未加载到 data2.json）：料仓与状态面板均未绑定。"
                      "打包时请把 myDesigner/data2.json 一起加进去。")
            else:
                print("料仓状态面板：", self.panel_status.warnings)

        # 点击某个仓位时高亮该仓位的编号（红色），其余仓位编号恢复黑色
        self.rack_store_model.slot_clicked.connect(self.on_slot_clicked)

        # 初始化：所有仓位编号为黑色
        self._selected_slot_key = None
        # 每台料架当前的仓位排列方向：False 正序（编号1在最上）/ True 反序（编号1在最下）
        # 只在方向变化时才翻转，否则 PLC 每帧上报都会把布局来回翻
        self._rack_reversed = {}
        self._reset_all_number_colors()

    # 选中仓位的编号颜色 / 未选中仓位编号颜色
    SELECTED_NUMBER_COLOR = QColor("#FF0000")
    NORMAL_NUMBER_COLOR = QColor(0, 0, 0)

    def _iter_number_labels(self):
        """遍历所有仓位的编号文本图元。"""
        for rack in self.rack_store_model.racks.values():
            for slot in rack.slots.values():
                if slot.number_label is not None:
                    yield (rack.number, slot.slot_no), slot.number_label

    def _reset_all_number_colors(self):
        for _key, label in self._iter_number_labels():
            label.set_color(self.NORMAL_NUMBER_COLOR)

    def on_slot_clicked(self, rack_no: int, slot_no: int):
        """选中仓位：该仓位编号变红，其他仓位编号恢复黑色。"""
        key = (int(rack_no), int(slot_no))
        if self._selected_slot_key == key:
            return
        self._selected_slot_key = key
        for slot_key, label in self._iter_number_labels():
            label.set_color(
                self.SELECTED_NUMBER_COLOR if slot_key == key
                else self.NORMAL_NUMBER_COLOR
            )

        self.slot_clicked.emit(rack_no, slot_no)

        self.panel_status.move(self.rack_store_model.get_end_position(rack_no, slot_no))  # 将面板移动到选中仓位的上方
        self.panel_status.show_all()  # 显示料仓状态面板

        self.rack_process_model.move_endpos_to_tagret(self.rack_store_model.get_head_position(rack_no, slot_no))
        self.rack_process_model.show_all() 

    def handle_rack_status(self,host_type,host_start_No,host_count:int,rack_counts:List[int],rack_arrangements:List[int]=None, hmi_config:dict=None):

        # 仓位排列方向：0 正序（编号 1 在最上面）/ 1 反序（编号 1 在最下面）
        # 只换格子的位置，仓位号、图元名字、PLC 映射口径都不变；
        # 方向没变时不会重复翻转（PLC 会反复下发同一份配置）
        if rack_arrangements is not None:
            self.set_rack_arrangements(rack_arrangements)

        # 场景可能没加载到图元（打包后 data2.json 没带进去），此时模型是空的。
        # 每条链路都按"图元不存在就跳过"处理，不要抛 AttributeError 把界面顶掉。
        rack_counts = list(rack_counts or ())
        host_count = max(0, int(host_count or 0))

        for i in range(10):

            rack = self.rack_store_model.rack(i + 1)
            if i<=host_count-1:

                if rack is not None:
                    rack.set_machine_number(f"{i+host_start_No}")

                self.rack_store_model.setVisible_rack(i+1, True)
            else:

                self.rack_store_model.setVisible_rack(i+1, False)


            for j in range(8):
                # rack_counts 比 host_count 短时按 0 个仓位处理，避免 IndexError
                slot_count = rack_counts[i] if i < len(rack_counts) else 0
                if i<=host_count-1 and j<slot_count:

                    self.rack_store_model.setVisible_slot(i+1,j+1,True)
                else:
                    self.rack_store_model.setVisible_slot(i+1,j+1,False)

        for key, value in (hmi_config or {}).items():
            # key 形如 "HMI_1"，脏数据直接忽略，不要连累后面的配置
            try:
                index = int(str(key).split("_")[1]) - 1
            except (IndexError, ValueError):
                continue
            if not (0 <= index < len(self.rack_hmi_config_models)):
                continue

            model = self.rack_hmi_config_models[index]
            model.set_text(key)

            try:
                rack_no_A, rack_no_B = value
            except (TypeError, ValueError):
                rack_no_A = rack_no_B = 0

            # 图元缺失时 rack() 返回 None，按"这条线不画"处理
            rack_A = self.rack_store_model.rack(rack_no_A) if rack_no_A > 0 else None
            rack_B = self.rack_store_model.rack(rack_no_B) if rack_no_B > 0 else None

            if rack_A is not None and rack_B is not None:
                model.move_endpos_of_line(1, rack_A.label_position)
                model.move_endpos_of_line(2, rack_B.label_position)
            elif rack_A is not None or rack_B is not None:
                pos = (rack_A or rack_B).label_position
                model.move_endpos_of_line(1, pos)
                model.move_endpos_of_line(2, pos)
            else:
                model.hide_all()

    # ------------------------------------------------------------ 仓位排列方向
    def set_rack_arrangements(self, rack_arrangements) -> List[int]:
        """按每台料架的方向批量设置（0 正序 / 1 反序），返回实际翻转过的料架号。

        下标 i 对应料架 i+1，与 PLC DB7 的 26/28/.../44 一一对应。
        列表比 10 短时，多出来的料架按正序处理。
        """
        flipped = []
        arrangements = list(rack_arrangements or ())
        for i in range(10):
            reverse = False
            if i < len(arrangements):
                try:
                    reverse = int(arrangements[i]) == 1
                except (TypeError, ValueError):
                    reverse = False
            if self.set_rack_arrangement(i + 1, reverse):
                flipped.append(i + 1)
        return flipped

    def set_rack_arrangement(self, rack_no: int, reverse: bool) -> bool:
        """设置单台料架的仓位排列方向。方向没变时什么也不做（幂等）。

        reverse=False 正序（编号 1 在最上面），reverse=True 反序（编号 1 在最下面）。
        返回本次是否真的翻转了图元。
        """
        rack_no = int(rack_no)
        reverse = bool(reverse)
        if self._rack_reversed.get(rack_no, False) == reverse:
            return False
        changed = self._reverse_rack_slots(rack_no)
        if changed:
            self._rack_reversed[rack_no] = reverse
        return changed

    def _reverse_rack_slots(self, rack_no: int) -> bool:
        """把一台料架里的仓位组按几何顺序上下对调（1↔8、2↔7 …）。

        只移动场景位置，不改名字/编号/父关系，所以 RackStoreModel 的索引、
        PLC 位序、状态层槽位键全都不受影响 —— 变的是“编号对应的格子”。
        """
        rack = self.rack_store_model.rack(rack_no)
        if rack is None:
            return False
        groups = {no: slot.group for no, slot in rack.slots.items() if slot.group is not None}
        if len(groups) < 2:
            return False

        # 按列分组（x 相同的算同一列），列内按屏幕从上到下排序，再整体对调
        columns = {}
        for no, group in groups.items():
            center = group.get_scene_center_pos()
            columns.setdefault(round(center.x(), 1), []).append(no)

        deltas = {}  # slot_no -> 需要平移的向量
        for numbers in columns.values():
            if len(numbers) < 2:
                continue
            # scene y 越大越靠上，取负号即“从上到下”
            order = sorted(numbers, key=lambda no: -groups[no].get_scene_center_pos().y())
            for index, no in enumerate(order):
                donor = order[len(order) - 1 - index]
                deltas[no] = (groups[donor].get_scene_center_pos()
                              - groups[no].get_scene_center_pos())

        if not deltas:
            return False

        # 目标位置全部算完再统一移动，避免 1↔8 互换时边读边改互相污染
        for no, delta in deltas.items():
            group = groups[no]
            group.change_position(group.get_scene_topLeft() + delta)
        return True

    def set_slot_number(self, rack_no: int, slot_no: int, text) -> bool:
        """设置指定仓位的编号文本"""
        rack = self.rack_store_model.rack(rack_no)
        if rack is None:
            return False
        slot = rack.slot(slot_no)
        if slot is None:
            return False
        slot.set_number(text)
        return True
    
    def set_slot_light(self, rack_no: int, slot_no: int, color, freq=None) -> bool:
        """设置指定仓位的灯带颜色与闪烁频率。

        color: 红/绿/蓝/黄/灰 或 LightColor；'off'/'灭' 表示关灯
        freq : 常亮/1hz/0.5hz 或 LightFreq；None 视为常亮
        """
        rack = self.rack_store_model.rack(rack_no)
        if rack is None:
            return False
        slot = rack.slot(slot_no)
        if slot is None:
            return False
        slot.set_light_color(color, freq)
        return True

    def set_pallet(self, rack_no: int, slot_no: int, visible: bool) -> bool:
        """设置指定仓位的托盘可见性"""
        rack = self.rack_store_model.rack(rack_no)
        if rack is None:
            return False
        slot = rack.slot(slot_no)
        if slot is None:
            return False
        slot.set_pallet(visible)
        return True

    def set_material(self, rack_no: int, slot_no: int, area, state) -> bool:
        """设置指定仓位的料件区域可见性与状态"""
        rack = self.rack_store_model.rack(rack_no)
        if rack is None:
            return False
        slot = rack.slot(slot_no)
        if slot is None:
            return False
        slot.set_material(area, state)
        return True

    def set_cylinder(self, rack_no: int, slot_no: int, axis, state) -> bool:
        """设置指定仓位的气缸状态"""
        rack = self.rack_store_model.rack(rack_no)
        if rack is None:
            return False
        slot = rack.slot(slot_no)
        if slot is None:
            return False
        slot.set_cylinder(axis, state)
        return True
    
    def set_sensor(self, rack_no: int, slot_no: int, index: int, state) -> bool:
        """设置指定仓位的传感器状态"""
        rack = self.rack_store_model.rack(rack_no)
        if rack is None:
            return False
        slot = rack.slot(slot_no)
        if slot is None:
            return False
        slot.set_sensor(index, state)
        return True

    # ------------------------------------------------------------ 料仓状态面板（id=1584）
    # 面板是整机级 IO 指示，与单个仓位无关，所以直接转发给 panel_status。

    def set_io_lamp(self, module: str, channel: int, line: str, on: bool,
                    color=None) -> bool:
        """点亮/熄灭某盏 IO 指示灯。

        module  : 'A' / 'B'（两块 ELCO 模块）
        channel : 1..8
        line    : 'A'（上灯）/ 'B'（下灯）
        on      : True 亮，False 灭
        color   : 亮灯颜色，默认取该灯在 LAMP_LABELS 里的语义色
        """
        return self.panel_status.set_lamp(module, channel, line, on, color)

    def set_io_module_bits(self, module: str, bits: int, layout: str = None) -> int:
        """一次写一个模块的 16 位 IO 状态字（bits 的 bit0 对应 1A）。"""
        return self.panel_status.set_module_bits(module, bits, layout)

    def set_io_module_online(self, module: str, online: bool) -> bool:
        """设置模块在线状态（DB12 的 20+i 字节，bit0=A 模块 / bit1=B 模块）。"""
        return self.panel_status.set_module_online(module, online)

    def set_panel_text(self, field, value) -> bool:
        """设置面板文本：title/标题、lamp_legend/灯语、hint/提示、alarm/报警。"""
        return self.panel_status.set_text(field, value)

    def set_panel_alarm(self, text: str) -> bool:
        """报警文本（DB12 offset 34）。"""
        return self.panel_status.set_alarm(text)

    def set_panel_hint(self, text: str) -> bool:
        """提示文本（DB12 offset 242）。"""
        return self.panel_status.set_hint(text)

    def set_panel_lamp_legend(self, text: str) -> bool:
        """灯语文本（DB12 offset 138）。"""
        return self.panel_status.set_lamp_legend(text)

    def apply_db12(self, datas) -> int:
        """把一整块 DB12 灌进料仓状态面板（口径与 plc_window 完全一致）。

        datas 是 PLC 读回来的原始字节，长度 >= 346：
            20+i  模块在线字节（bit0=A, bit1=B）
            30/32 模块 A / B 的 16 位 IO 状态字
            34/138/242 报警 / 灯语 / 提示 WSTRING
        返回实际发生变化的灯位数（含 2 个模块在线标志）。
        """
        self.panel_status.apply_db12(datas)
        self.rack_process_model.apply_db12(datas)

    def refresh_models(self) -> None:
        """场景重新 load_element_info2 之后调用，重建两套模型的图元索引。"""
        self.rack_store_model.refresh()
        self.panel_status.refresh()
        # 场景重载后图元几何回到设计态（正序），排列方向标记要一起清零
        self._rack_reversed.clear()

    def handle_double_click_without_group(self):
        """场景双击空白处时，取消选中仓位编号（恢复黑色）。"""
        self._selected_slot_key = None
        self._reset_all_number_colors()
        self.panel_status.hide_all()  # 隐藏料仓状态面板
        self.rack_process_model.hide_all()

    def set_hmi_text(self, hmi_index: int, text: str):
        """设置 HMI 面板的文本内容"""
        if 1 <= hmi_index <= len(self.rack_hmi_config_models):
            self.rack_hmi_config_models[hmi_index - 1].set_text(text)

    def move_hmi_line_endpos(self, hmi_index: int, line_index: int, target):
        """移动 HMI 面板的直线终点坐标"""
        if 1 <= hmi_index <= len(self.rack_hmi_config_models):
            self.rack_hmi_config_models[hmi_index - 1].move_endpos_of_line(line_index, target)