import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Signal,QPointF
from PySide6.QtGui import QColor

from .rack_store_model import LIGHT_COLORS, LightColor, normalize_light
from Designer.Core.elements import base_element, group_element, text_element,rect_element,triangle_element,widget_element

from Designer.Core.myQuadTreeScene import SceneManager

from .test import ConfigWindow,Rcd
from common.com.snap7 import PLCManager
from snap7.util import *
from common.com.snap7 import DataBroker

class RackGlobalParasModel(QObject):
    """料仓状态面板模型：按 (模块, 通道, 灯位) 访问 32 盏灯和 4 个文本。

    图元靠名字识别，所以场景重新加载（再次 ``load_element_info2``）之后
    必须调 ``refresh()``，否则旧引用会随图元删除而失效。
    """

    #: 场景里承载 RCD 日志列表的 widget 图元名。
    WIDGET_NAME = "Widget_1"

    def __init__(self, scene_manager: SceneManager,parent=None):
        super().__init__(parent)
        self._manager = scene_manager

        self.group:widget_element = scene_manager.findItemByName(self.WIDGET_NAME)
        if self.group is None:
            # 场景里没有这个图元时不要继续：后面 set_widget_factory 会
            # AttributeError，把整个料仓窗口的构造带崩（表现为标签页打不开）。
            print(f"料仓全局参数：场景里没有名为 {self.WIDGET_NAME} 的控件图元，"
                  f"RCD 日志列表未挂载")
            return

        plc_mgr = PLCManager("192.168.1.1", 0, 1)
        data_broker = DataBroker(plc_mgr)

        # w = ConfigWindow(plc_mgr,data_broker,'SerialNumber',parent=parent)

        # 注意：set_widget_factory 要的是**可调用对象** ``factory(host) -> QWidget``，
        # 不是控件实例。直接传 ``Rcd(...)`` 实例的话，承载层重建时会去
        # ``instance(host)``，抛 TypeError: 'Rcd' object is not callable。
        # 这里用闭包延迟创建，等 overlay 视图真正建起来才实例化控件。
        self._plc_mgr = plc_mgr
        self._data_broker = data_broker
        self.group.set_widget_factory(self._make_rcd)

    def _make_rcd(self, host):
        """控件工厂：每个承载视图创建一个 RCD 日志列表。"""
        # return Rcd(self._plc_mgr, parent=host)
        return ConfigWindow(self._plc_mgr,self._data_broker,'SerialNumber',parent=host)
