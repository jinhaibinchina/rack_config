import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, 
    QTreeWidget, QTreeWidgetItem, QStackedWidget, QLabel, QFrame,QScrollArea,
    QListWidget, QListWidgetItem, QPushButton, QGroupBox,QColorDialog,QCheckBox,
    QTextEdit, QStyleFactory,QLineEdit,QPlainTextEdit,QComboBox,QSpinBox
)
from PySide6.QtCore import QObject, Signal,QPointF
from PySide6.QtGui import QColor

from .rack_store_model import LIGHT_COLORS, LightColor, normalize_light
from Designer.Core.elements import base_element, group_element, widget_element,rect_element,triangle_element

from Designer.Core.myQuadTreeScene import SceneManager
from snap7.util import *
from App_RackConfig.plc_manager import PLCManager

class RackGlobalParasModel(QObject):
    """料仓状态面板模型：按 (模块, 通道, 灯位) 访问 32 盏灯和 4 个文本。

    图元靠名字识别，所以场景重新加载（再次 ``load_element_info2``）之后
    必须调 ``refresh()``，否则旧引用会随图元删除而失效。
    """

   

    def __init__(self, plc_mgr:PLCManager, scene_manager: SceneManager,parent=None):
        super().__init__(parent)
        self._manager = scene_manager

        self.plc_mgr = plc_mgr
        self.屏蔽膜卷号报警 : widget_element = scene_manager.findItemByName(f"屏蔽膜卷号报警")
        self.屏蔽物料状态NG报警 : widget_element = scene_manager.findItemByName(f"屏蔽物料状态NG报警")
        self.非运行状态下仍响应泊车 : widget_element = scene_manager.findItemByName(f"非运行状态下仍响应泊车")
        self.仓位编号1 : widget_element = scene_manager.findItemByName(f"仓位编号1")
        self.仓位编号2 : widget_element = scene_manager.findItemByName(f"仓位编号2")

        self.屏蔽膜卷号报警_checkbox:QCheckBox =  self.屏蔽膜卷号报警._leaf_widget()
        self.屏蔽物料状态NG报警_checkbox:QCheckBox =  self.屏蔽物料状态NG报警._leaf_widget()
        self.非运行状态下仍响应泊车_checkbox:QCheckBox =  self.非运行状态下仍响应泊车._leaf_widget()
        self.仓位编号1_spinbox:QSpinBox =  self.仓位编号1._leaf_widget()
        self.仓位编号2_spinbox:QSpinBox =  self.仓位编号2._leaf_widget()

        self.仓位编号1_spinbox.setRange(-1,9)
        self.仓位编号2_spinbox.setRange(-1,9)


        self.屏蔽膜卷号报警_checkbox.clicked.connect(lambda e: self.handle_check_屏蔽膜卷号报警(e))
        self.屏蔽物料状态NG报警_checkbox.clicked.connect(lambda e: self.handle_check_屏蔽物料状态NG报警(e))
        self.非运行状态下仍响应泊车_checkbox.clicked.connect(lambda e: self.handle_check_非运行状态下仍响应泊车(e))

        self.仓位编号1_spinbox.valueChanged.connect(lambda e: self.handle_spinbox_仓位编号1(e))
        self.仓位编号2_spinbox.valueChanged.connect(lambda e: self.handle_spinbox_仓位编号2(e)) 

    def handle_check_屏蔽膜卷号报警(self,checked:bool):
        a= bytearray([0,0])
        set_int(a,0,int(checked))
        self.plc_mgr.write_data(41,0,a)

    def handle_check_屏蔽物料状态NG报警(self,checked:bool):
        a= bytearray([0,0])
        set_int(a,0,int(checked))
        self.plc_mgr.write_data(41,2,a)

    def handle_check_非运行状态下仍响应泊车(self,checked:bool):     
        a= bytearray([0,0])
        set_int(a,0,int(checked))
        self.plc_mgr.write_data(41,4,a)

    def handle_spinbox_仓位编号1(self,value:int):
        a= bytearray([0,0])
        set_int(a,0,value)
        self.plc_mgr.write_data(41,6,a)

    def handle_spinbox_仓位编号2(self,value:int):
        a= bytearray([0,0])
        set_int(a,0,value)
        self.plc_mgr.write_data(41,8,a)

    def apply_db41(self, db41: bytes):
        """解析 DB41 数据，更新图元显示。"""
        

        if len(db41) < 10:
            raise ValueError(f"DB41 数据长度不足：{len(db41)} < 10")
        


        checkbox:QCheckBox = self.屏蔽膜卷号报警._leaf_widget()
        checkbox.setChecked(bool(get_int(db41,0)))

        checkbox:QCheckBox = self.屏蔽物料状态NG报警._leaf_widget()
        checkbox.setChecked(bool(get_int(db41,2)))

        checkbox:QCheckBox = self.非运行状态下仍响应泊车._leaf_widget()
        checkbox.setChecked(bool(get_int(db41,4)))

        spinbox:QSpinBox = self.仓位编号1._leaf_widget()
        spinbox.setValue(get_int(db41,6))
        spinbox:QSpinBox = self.仓位编号2._leaf_widget()
        spinbox.setValue(get_int(db41,8))