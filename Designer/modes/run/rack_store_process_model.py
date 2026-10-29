import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Signal,QPointF
from PySide6.QtGui import QColor

from .rack_store_model import LIGHT_COLORS, LightColor, normalize_light
from Designer.Core.elements import base_element, group_element, text_element,rect_element,triangle_element

from Designer.Core.myQuadTreeScene import SceneManager

#: DB12 里 IO 状态字的偏移（按模块）
DB12_IO_WORD_OFFSETS = {"A": 30, "B": 32}

#: DB12 里“每主机 IO 模块在线状态”字节的起始偏移（bit0=A, bit1=B）
DB12_MODULE_STATUS_BYTE = 20

#: DB12 里三个文本的偏移（WSTRING，每个 104 字节）
DB12_TEXT_OFFSETS = {"alarm": 34, "lamp_legend": 138, "hint": 242}


DB12_PROCESS_STATUS_OFFSETS = 346
DB12_TASK_INDEX_OFFSETS = 347
#: DB12 读取长度：242 + 104
DB12_SIZE = 348


class RackProcessModel(QObject):
    """料仓状态面板模型：按 (模块, 通道, 灯位) 访问 32 盏灯和 4 个文本。

    图元靠名字识别，所以场景重新加载（再次 ``load_element_info2``）之后
    必须调 ``refresh()``，否则旧引用会随图元删除而失效。
    """

   

    def __init__(self, scene_manager: SceneManager,parent=None):
        super().__init__(parent)
        self._manager = scene_manager
        self.text : text_element = scene_manager.findItemByName(f"流程_文本_当前任务")
        self.in1:triangle_element = scene_manager.findItemByName(f"流程_IN1")
        self.in2:triangle_element = scene_manager.findItemByName(f"流程_IN2")     
        self.in3:triangle_element = scene_manager.findItemByName(f"流程_IN3")  
        self.in4:triangle_element = scene_manager.findItemByName(f"流程_IN4")  
        self.out1:rect_element = scene_manager.findItemByName(f"流程_OUT1")
        self.out2:rect_element = scene_manager.findItemByName(f"流程_OUT2")
        self.out3:rect_element = scene_manager.findItemByName(f"流程_OUT3")
        self.out4:rect_element = scene_manager.findItemByName(f"流程_OUT4")
        self.group:group_element = scene_manager.findItemByName("流程")  

        self.warnings: List[str] = []

        self.task_contexts={0:"无任务",2:"小AGV取托盘",1:"小AGV放托盘",3:"小AGV泊车",5:"悬臂AGV取",4:"悬臂AGV放"}
    def set_text(self, text: str):
        """设置文本内容"""
        if self.text is not None:
            self.text.context = text

    def move_endpos_to_tagret(self,target:QPointF):
        # 场景没加载到「流程」组时（例如打包漏了 data2.json）直接跳过
        if self.group is None:
            return
        w,h = self.group.sceneBoundingRect().width(),self.group.sceneBoundingRect().height()
        pos =QPointF(target.x()-w , target.y()-h)
        self.group.change_position(pos)

    def hide_all(self):
        """隐藏所有图元"""
        if self.group is not None:
            self.group.set_visibility(False)
        
    def show_all(self):
        if self.group is not None:
            self.group.set_visibility(True)


    def apply_db12(
            self,
            data: Sequence[int]
        ):
        """把一整块 DB12 灌到面板上。

        host_index：哪台主机（决定从 20 + host_index 取模块在线位）。
        返回 {"lamps": 变化灯数, "texts": 变化文本数}。
        """
        
        if data is None or len(data) <= DB12_TASK_INDEX_OFFSETS:
            self.warnings.append("DB12 数据为空或长度不足，已忽略")
            return 
        raw = bytes(bytearray(data))

        # 场景里没有「流程」相关图元时（打包漏了 data2.json），不要继续往下走，
        # 否则 self.in1.set_visibility 会在 None 上抛 AttributeError
        parts = (self.text, self.in1, self.in2, self.in3, self.in4,
                 self.out1, self.out2, self.out3, self.out4)
        if any(part is None for part in parts):
            return

        process_byte = raw[DB12_PROCESS_STATUS_OFFSETS]
        task_byte    = raw[DB12_TASK_INDEX_OFFSETS]
        
        self.set_text(self.task_contexts.get(int(task_byte),"未知"))

        step = process_byte & 0x0f

        self.in1.set_visibility(bool(process_byte>>4 & 0x01))
        self.in2.set_visibility(bool(process_byte>>5 & 0x01))
        self.in3.set_visibility(bool(process_byte>>6 & 0x01))
        self.in4.set_visibility(bool(process_byte>>7 & 0x01))

        if step==0:
            self.out1.set_visibility(False)
            self.out2.set_visibility(False)
            self.out3.set_visibility(False)
            self.out4.set_visibility(False)
        elif step ==1:
            self.out1.set_visibility(True)
            self.out2.set_visibility(False)
            self.out3.set_visibility(False)
            self.out4.set_visibility(False)
        elif step ==2:
            self.out1.set_visibility(False)
            self.out2.set_visibility(True)
            self.out3.set_visibility(False)
            self.out4.set_visibility(False)
        elif step ==3:
            self.out1.set_visibility(False)
            self.out2.set_visibility(False)
            self.out3.set_visibility(True)
            self.out4.set_visibility(False)
        elif step ==4:
            self.out1.set_visibility(False)
            self.out2.set_visibility(False)
            self.out3.set_visibility(False)
            self.out4.set_visibility(True)
    