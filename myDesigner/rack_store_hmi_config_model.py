import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Signal,QPointF
from PySide6.QtGui import QColor

from .rack_store_model import LIGHT_COLORS, LightColor, normalize_light
from .elements import base_element, group_element, text_element,line_element

from .myQuadTreeScene import SceneManager

class RackHmiConfigModel(QObject):
    """料仓状态面板模型：按 (模块, 通道, 灯位) 访问 32 盏灯和 4 个文本。

    图元靠名字识别，所以场景重新加载（再次 ``load_element_info2``）之后
    必须调 ``refresh()``，否则旧引用会随图元删除而失效。
    """

   

    def __init__(self, scene_manager: SceneManager,parent=None, group_name: str = "HMI1"):
        super().__init__(parent)
        self._manager = scene_manager
        self.text : text_element = scene_manager.findItemByName(f"{group_name}")
        self.line1:line_element = scene_manager.findItemByName(f"{group_name}_直线_1")
        self.line2:line_element = scene_manager.findItemByName(f"{group_name}_直线_2")                                                       
      


    def set_text(self, text: str):
        """设置文本内容"""
        if self.text is not None:
            self.text.context = text

    def move_endpos_of_line(self,index:int, target: QPointF):
        """移动两条直线的终点坐标"""
        if index == 1 and self.line1 is not None:
            self.line1.change_end_pos(target)
        elif index == 2 and self.line2 is not None:
            self.line2.change_end_pos(target)

    def hide_all(self):
        """隐藏所有图元"""
        if self.text is not None:
            self.text.set_visibility(False)
        if self.line1 is not None:
            self.line1.set_visibility(False)
        if self.line2 is not None:
            self.line2.set_visibility(False)
    