from PySide6.QtCore import Qt, QObject,QPointF,Signal,QTimer
from PySide6.QtWidgets import  QWidget
# from my_elements_v2 import group_element
from Designer.Core.elements import (
    base_element,
    circle_element,
    group_element,
    image_element,
    line_element,
    rect_element,
    text_element,
    triangle_element,
)
from PySide6.QtGui import QFont,QColor
from Designer.Core.my_common import SceneMode

from dataclasses import dataclass
from typing import List,Optional
from .my_data_broker import DataBroker
from .my_modbus import get_bool,set_bool,get_int
import time
from datetime import datetime

from .safety_status_ui import Ui_Form as safety_Ui

FALSE_COLOR = QColor(54,108,80)
TRUE_COLOR = OK_COLOR  = QColor(0,255,0)
ERR_COLOR  = QColor(255,0,0)
YELLOW_COLOR =QColor(255,255,0)

def validate_bool_list_16(value: List[bool]) -> List[bool]:
    if not isinstance(value, list) or len(value) != 16 or not all(isinstance(x, bool) for x in value):
        raise ValueError("INPUT0 must be a list of 16 booleans")
    return value

def int_to_hex(num, digits=None, uppercase=True):
    """
    将整数转换为十六进制字符串
    :param num: 整数
    :param digits: 指定位数（不足时补0）
    :param uppercase: 是否大写
    :return: 十六进制字符串
    """
    fmt = 'X' if uppercase else 'x'
    hex_str = format(num, fmt)
    if digits is not None:
        hex_str = hex_str.zfill(digits)
    return hex_str


@dataclass
class cabinet_status_data():
    main_is_ok          :bool =None
    maintain_safedoor_ok:List[bool] =None
    shangjiaX4_ok       :List[bool] =None
    jianxuanX4_ok       :List[bool] =None
    safedoorX1_ok       :List[bool] =None
    conveyX2_ok         :List[bool] =None
    q1p_jianxuan_q3p_jianxuan_ok   :List[bool] =None
    q3p_tuopan_X2_ok               :List[bool] =None
    conveyX4_ok         :List[bool] =None

    main_is_err          :bool =None
    maintain_safedoor_err:List[bool] =None
    shangjiaX4_err       :List[bool] =None
    jianxuanX4_err       :List[bool] =None
    safedoorX1_err       :List[bool] =None
    conveyX2_err         :List[bool] =None
    q1p_jianxuan_q3p_jianxuan_err  :List[bool] =None
    q3p_tuopan_X2_err              :List[bool] =None
    conveyX4_err         :List[bool] =None

    def __post_init__(self):
        self.main_is_ok =False
        if self.maintain_safedoor_ok is None:
            self.maintain_safedoor_ok = [False] * 4
        if self.shangjiaX4_ok is None:
            self.shangjiaX4_ok = [False] * 9
        if self.jianxuanX4_ok is None:
            self.jianxuanX4_ok = [False] * 9
        if self.safedoorX1_ok is None:
            self.safedoorX1_ok = [False] * 9
        if self.conveyX2_ok is None:
            self.conveyX2_ok = [False] * 4
        if self.q1p_jianxuan_q3p_jianxuan_ok is None:
            self.q1p_jianxuan_q3p_jianxuan_ok = [False] * 9
        if self.q3p_tuopan_X2_ok is None:
            self.q3p_tuopan_X2_ok = [False] * 4
        if self.conveyX4_ok is None:
            self.conveyX4_ok = [False] * 4

        self.main_is_err =False
        if self.maintain_safedoor_err is None:
            self.maintain_safedoor_err = [False] * 4
        if self.shangjiaX4_err is None:
            self.shangjiaX4_err = [False] * 9
        if self.jianxuanX4_err is None:
            self.jianxuanX4_err = [False] * 9
        if self.safedoorX1_err is None:
            self.safedoorX1_err = [False] * 9
        if self.conveyX2_err is None:
            self.conveyX2_err = [False] * 4    
        if self.q1p_jianxuan_q3p_jianxuan_err is None:
            self.q1p_jianxuan_q3p_jianxuan_err = [False] * 9
        if self.q3p_tuopan_X2_err is None:
            self.q3p_tuopan_X2_err = [False] * 4   
        if self.conveyX4_err is None:
            self.conveyX4_err = [False] * 4   



@dataclass
class IO_data():
    INPUT0 :List[bool] =None
    INPUT1 :List[bool] =None
    INPUT2 :List[bool] =None
    
    OUTPUT0:List[bool] =None
    OUTPUT1:List[bool] =None

    IO_STATUS :List[bool] =None
    animation_status_1:List[bool] =None
    animation_status_2:List[bool] =None
    animation_status_3:List[bool] =None
    animation_status_4:List[bool] =None

    animation_status_5:int =None
    animation_status_6:int =None
    animation_status_7:int =None
    animation_status_8:int =None


    def __post_init__(self):
        # self.INPUT0 = validate_bool_list_16(self.INPUT0)
        if self.INPUT0 is None:
            self.INPUT0 = [False] * 16 
        if self.INPUT1 is None:
            self.INPUT1 = [False] * 16 
        if self.INPUT2 is None:
            self.INPUT2 = [False] * 16 
        if self.IO_STATUS is None:
            self.IO_STATUS = [False] * 16 
        if self.OUTPUT0 is None:
            self.OUTPUT0 = [False] * 16
        if self.OUTPUT1 is None:
            self.OUTPUT1 = [False] * 16     
        if self.animation_status_1 is None:
            self.animation_status_1 = [False] * 16            
        if self.animation_status_2 is None:
            self.animation_status_2 = [False] * 16            
        if self.animation_status_3 is None:
            self.animation_status_3 = [False] * 16            
        if self.animation_status_4 is None:
            self.animation_status_4 = [False] * 16            
        
        if self.animation_status_5 is None:
            self.animation_status_5 = 0            
        if self.animation_status_6 is None:
            self.animation_status_6 = 0            
        if self.animation_status_7 is None:
            self.animation_status_7 = 0            
        if self.animation_status_8 is None:
            self.animation_status_8 = 0   

class plc_safety(QObject):
    close_property_window = Signal()
    page_changed = Signal(str,int)

    params_read_done = Signal(bool)
    params_write_done = Signal(bool)

    def tm1_time_out_handle(self):
        self.shine_flag = True
     
        self.timer1.stop()
        self.timer2.start(300)
  
        # self.update()
        self.roll_dog_need_feed = True
        self.move_dog_need_feed = True
    def tm2_time_out_handle(self):
        self.shine_flag = False
       
        self.timer2.stop()
        self.timer1.start(300)
  

    def __init__(self, parent=None ):
        super().__init__(parent=parent)
        self.data_broker:Optional[DataBroker]  = None
        self.SceneManager = None
        self.Scene    =None
        # self.data_broker.data_ready.connect(self.handle_data_broker)
        self.timer1 = QTimer(self)
        self.timer2 = QTimer(self)
        self.shine_flag = False
        self.timer1.timeout.connect(self.tm1_time_out_handle)
        self.timer2.timeout.connect(self.tm2_time_out_handle)
        self.timer1.start(500)

        maintain_safedoor = [{"维修区": None, "安全门": None} for _ in range(4)] 
        shangjia_X4       = [{"上架工作站1":None,"上架工作站2":None,"上架工作站3":None,"上架工作站4":None} for _ in range(9)] 
        jianxuan_X4       = [{"拣选工作站1":None,"拣选工作站2":None,"拣选工作站3":None,"拣选工作站4":None} for _ in range(9)] 
        safedoor_X1       = [{"安全门":None} for _ in range(9)] 
        convey_X2         = [{"输送线工作站1":None,"输送线工作站2":None} for _ in range(4)] 
        q1p_jianxuan_q3p_jianxuan      = [{"Q1P拣选工作站":None,"Q3P拣选工作站":None} for _ in range(9)] 
        q3p_tuopan_X2       = [{"Q3P托盘工作站1":None,"Q3P托盘工作站2":None} for _ in range(4)]
        convey_X4         = [{"输送线工作站1":None,"输送线工作站2":None,"输送线工作站3":None,"输送线工作站4":None} for _ in range(4)] 
        # root_nodes_name = ("维修区/安全门(X.X.X.161)","维修区/安全门(X.X.X.162)","维修区/安全门(X.X.X.163)","维修区/安全门(X.X.X.164)",
        #                     "上架工作站(X.X.X.171)","上架工作站(X.X.X.172)","上架工作站(X.X.X.173)","上架工作站(X.X.X.174)"),
        self.father_roots ={
            "维修区/安全门(X.X.X.161)"   :None,
            "维修区/安全门(X.X.X.162)"   :None,
            "维修区/安全门(X.X.X.163)"   :None,
            "维修区/安全门(X.X.X.164)"   :None,
            "上架X4(X.X.X.171)"         :None,
            "上架X4(X.X.X.172)"         :None,
            "上架X4(X.X.X.173)"         :None,
            "上架X4(X.X.X.174)"         :None,
            "上架X4(X.X.X.175)"         :None,
            "上架X4(X.X.X.176)"         :None,
            "上架X4(X.X.X.177)"         :None,
            "上架X4(X.X.X.178)"         :None,
            "上架X4(X.X.X.179)"         :None,
            "拣选X4(X.X.X.181)"         :None,
            "拣选X4(X.X.X.182)"         :None,
            "拣选X4(X.X.X.183)"         :None,
            "拣选X4(X.X.X.184)"         :None,
            "拣选X4(X.X.X.185)"         :None,
            "拣选X4(X.X.X.186)"         :None,
            "拣选X4(X.X.X.187)"         :None,
            "拣选X4(X.X.X.188)"         :None,
            "拣选X4(X.X.X.189)"         :None,
            "安全门X1(X.X.X.191)"       :None,
            "安全门X1(X.X.X.192)"       :None,
            "安全门X1(X.X.X.193)"       :None,
            "安全门X1(X.X.X.194)"       :None,
            "安全门X1(X.X.X.195)"       :None,
            "安全门X1(X.X.X.196)"       :None,
            "安全门X1(X.X.X.197)"       :None,
            "安全门X1(X.X.X.198)"       :None,
            "安全门X1(X.X.X.199)"       :None,
            "输送线X2(X.X.X.201)"       :None,
            "输送线X2(X.X.X.202)"       :None,
            "输送线X2(X.X.X.203)"       :None,
            "输送线X2(X.X.X.204)"       :None,
            "Q1P拣选/Q3P拣选(X.X.X.211)"         :None,
            "Q1P拣选/Q3P拣选(X.X.X.212)"         :None,
            "Q1P拣选/Q3P拣选(X.X.X.213)"         :None,
            "Q1P拣选/Q3P拣选(X.X.X.214)"         :None,
            "Q1P拣选/Q3P拣选(X.X.X.215)"         :None,
            "Q1P拣选/Q3P拣选(X.X.X.216)"         :None,
            "Q1P拣选/Q3P拣选(X.X.X.217)"         :None,
            "Q1P拣选/Q3P拣选(X.X.X.218)"         :None,
            "Q1P拣选/Q3P拣选(X.X.X.219)"         :None,
            "Q3P托盘X2(X.X.X.221)"       :None,
            "Q3P托盘X2(X.X.X.222)"       :None,
            "Q3P托盘X2(X.X.X.223)"       :None,
            "Q3P托盘X2(X.X.X.224)"       :None,
            "输送线X4(X.X.X.231)"       :None,
            "输送线X4(X.X.X.232)"       :None,
            "输送线X4(X.X.X.233)"       :None,
            "输送线X4(X.X.X.234)"       :None,
            "PLC2":None
        }
        self.child_roots = {
            "维修区/安全门(X.X.X.161)":maintain_safedoor[0],
            "维修区/安全门(X.X.X.162)":maintain_safedoor[1],
            "维修区/安全门(X.X.X.163)":maintain_safedoor[2],
            "维修区/安全门(X.X.X.164)":maintain_safedoor[3],
            "上架X4(X.X.X.171)"       :shangjia_X4[0],
            "上架X4(X.X.X.172)"       :shangjia_X4[1],
            "上架X4(X.X.X.173)"       :shangjia_X4[2],
            "上架X4(X.X.X.174)"       :shangjia_X4[3],
            "上架X4(X.X.X.175)"       :shangjia_X4[4],
            "上架X4(X.X.X.176)"       :shangjia_X4[5],
            "上架X4(X.X.X.177)"       :shangjia_X4[6],
            "上架X4(X.X.X.178)"       :shangjia_X4[7],
            "上架X4(X.X.X.179)"       :shangjia_X4[8],
            "拣选X4(X.X.X.181)"       :jianxuan_X4[0],
            "拣选X4(X.X.X.182)"       :jianxuan_X4[1],
            "拣选X4(X.X.X.183)"       :jianxuan_X4[2],
            "拣选X4(X.X.X.184)"       :jianxuan_X4[3],
            "拣选X4(X.X.X.185)"       :jianxuan_X4[4],
            "拣选X4(X.X.X.186)"       :jianxuan_X4[5],
            "拣选X4(X.X.X.187)"       :jianxuan_X4[6],
            "拣选X4(X.X.X.188)"       :jianxuan_X4[7],
            "拣选X4(X.X.X.189)"       :jianxuan_X4[8],
            "安全门X1(X.X.X.191)"     :safedoor_X1[0],
            "安全门X1(X.X.X.192)"     :safedoor_X1[1],
            "安全门X1(X.X.X.193)"     :safedoor_X1[2],
            "安全门X1(X.X.X.194)"     :safedoor_X1[3],
            "安全门X1(X.X.X.195)"     :safedoor_X1[4],
            "安全门X1(X.X.X.196)"     :safedoor_X1[5],
            "安全门X1(X.X.X.197)"     :safedoor_X1[6],
            "安全门X1(X.X.X.198)"     :safedoor_X1[7],
            "安全门X1(X.X.X.199)"     :safedoor_X1[8],
            "输送线X2(X.X.X.201)"     :convey_X2[0],
            "输送线X2(X.X.X.202)"     :convey_X2[1],
            "输送线X2(X.X.X.203)"     :convey_X2[2],
            "输送线X2(X.X.X.204)"     :convey_X2[3],
            "Q1P拣选/Q3P拣选(X.X.X.211)"         :q1p_jianxuan_q3p_jianxuan[0],
            "Q1P拣选/Q3P拣选(X.X.X.212)"         :q1p_jianxuan_q3p_jianxuan[1],
            "Q1P拣选/Q3P拣选(X.X.X.213)"         :q1p_jianxuan_q3p_jianxuan[2],
            "Q1P拣选/Q3P拣选(X.X.X.214)"         :q1p_jianxuan_q3p_jianxuan[3],
            "Q1P拣选/Q3P拣选(X.X.X.215)"         :q1p_jianxuan_q3p_jianxuan[4],
            "Q1P拣选/Q3P拣选(X.X.X.216)"         :q1p_jianxuan_q3p_jianxuan[5],
            "Q1P拣选/Q3P拣选(X.X.X.217)"         :q1p_jianxuan_q3p_jianxuan[6],
            "Q1P拣选/Q3P拣选(X.X.X.218)"         :q1p_jianxuan_q3p_jianxuan[7],
            "Q1P拣选/Q3P拣选(X.X.X.219)"         :q1p_jianxuan_q3p_jianxuan[8],
            "Q3P托盘X2(X.X.X.221)"       :q3p_tuopan_X2[0],
            "Q3P托盘X2(X.X.X.222)"       :q3p_tuopan_X2[1],
            "Q3P托盘X2(X.X.X.223)"       :q3p_tuopan_X2[2],
            "Q3P托盘X2(X.X.X.224)"       :q3p_tuopan_X2[3],
            "输送线X4(X.X.X.231)"     :convey_X4[0],
            "输送线X4(X.X.X.232)"     :convey_X4[1],
            "输送线X4(X.X.X.233)"     :convey_X4[2],
            "输送线X4(X.X.X.234)"     :convey_X4[3]
            
        }

        self.io_map_maintain_safedoor = {
            "I0.0":"维修区-门锁0",
            "I0.1":"维修区-门锁1",
            "I0.2":"维修区-急停0",
            "I0.3":"维修区-急停1",
            "I0.4":"维修区-复位",
            "I0.5":"维修区-开锁",
            "I0.6":"维修区-光栅0",
            "I0.7":"维修区-光栅1",
            "I1.0":"安全门-门锁0",
            "I1.1":"安全门-门锁1",
            "I1.2":"安全门-急停0",
            "I1.3":"安全门-急停1",
            "I1.4":"安全门-复位",
            "I1.5":"安全门-开锁",
            "I1.6":"安全门-光栅0",
            "I1.7":"安全门-光栅1",
            "I2.0":"",
            "I2.1":"",
            "I2.2":"",
            "I2.3":"",
            "I2.4":"",
            "I2.5":"",
            "I2.6":"",
            "I2.7":"",
            "I3.0":"",
            "I3.1":"",
            "I3.2":"",
            "I3.3":"",
            "I3.4":"",
            "I3.5":"",
            "I3.6":"",
            "I3.7":"",
            "I4.0":"",
            "I4.1":"",
            "I4.2":"",
            "I4.3":"",
            "I4.4":"",
            "I4.5":"",
            "I4.6":"",
            "I4.7":"",
            "Q0.0":"维修区-红灯",
            "Q0.1":"维修区-绿灯",
            "Q0.2":"维修区-黄灯",
            "Q0.3":"维修区-蜂鸣",
            "Q0.4":"安全门-红灯",
            "Q0.5":"安全门-绿灯",
            "Q0.6":"安全门-黄灯",
            "Q0.7":"安全门-蜂鸣",
            "Q1.0":"维修区-门锁",
            "Q1.1":"安全门-门锁",
            "Q1.2":"备用",
            "Q1.3":"备用",
            "Q1.4":"备用",
            "Q1.5":"备用",
            "Q1.6":"备用",
            "Q1.7":"备用"
        }

        self.io_map_shangjia_X4 = {
            "I0.0":"区域1-光栅0",
            "I0.1":"区域1-光栅1",
            "I0.2":"区域1-急停0",
            "I0.3":"区域1-急停1",
            "I0.4":"区域1-光电1",
            "I0.5":"区域1-光电3",
            "I0.6":"区域1-复位",
            "I0.7":"区域1-光电2",
            "I1.0":"区域2-光栅0",
            "I1.1":"区域2-光栅1",
            "I1.2":"区域2-急停0",
            "I1.3":"区域2-急停1",
            "I1.4":"区域2-光电1",
            "I1.5":"区域2-光电3",
            "I1.6":"区域2-复位",
            "I1.7":"区域2-光电2",
            "I2.0":"区域3-光栅0",
            "I2.1":"区域3-光栅1",
            "I2.2":"区域3-急停0",
            "I2.3":"区域3-急停1",
            "I2.4":"区域3-光电1",
            "I2.5":"区域3-光电3",
            "I2.6":"区域3-复位",
            "I2.7":"区域3-光电2",
            "I3.0":"区域4-光栅0",
            "I3.1":"区域4-光栅1",
            "I3.2":"区域4-急停0",
            "I3.3":"区域4-急停1",
            "I3.4":"区域4-光电1",
            "I3.5":"区域4-光电3",
            "I3.6":"区域4-复位",
            "I3.7":"区域4-光电2",
            "I4.0":"区域1-光电4",
            "I4.1":"区域2-光电4",
            "I4.2":"区域3-光电4",
            "I4.3":"区域4-光电4",
            "I4.4":"备用",
            "I4.5":"备用",
            "I4.6":"备用",
            "I4.7":"备用",
            "Q0.0":"区域1-红灯",
            "Q0.1":"区域1-绿灯",
            "Q0.2":"区域1-黄灯",
            "Q0.3":"区域1-蜂鸣",
            "Q0.4":"区域2-红灯",
            "Q0.5":"区域2-绿灯",
            "Q0.6":"区域2-黄灯",
            "Q0.7":"区域2-蜂鸣",
            "Q0.0":"区域1-红灯",
            "Q0.1":"区域1-绿灯",
            "Q0.2":"区域1-黄灯",
            "Q0.3":"区域1-蜂鸣",
            "Q0.4":"区域2-红灯",
            "Q0.5":"区域2-绿灯",
            "Q0.6":"区域2-黄灯",
            "Q0.7":"区域2-蜂鸣",
            "Q1.0":"区域3-红灯",
            "Q1.1":"区域3-绿灯",
            "Q1.2":"区域3-黄灯",
            "Q1.3":"区域3-蜂鸣",
            "Q1.4":"区域4-红灯",
            "Q1.5":"区域4-绿灯",
            "Q1.6":"区域4-黄灯",
            "Q1.7":"区域4-蜂鸣"
        }

        self.io_map_jianxuan_X4 = {
            "I0.0":"区域1-光电1",
            "I0.1":"区域1-光电2",
            "I0.2":"区域1-急停0",
            "I0.3":"区域1-急停1",
            "I0.4":"区域1-复位",
            "I0.5":"区域1-光栅0",
            "I0.6":"区域1-光栅1",
            "I0.7":"备用",
            "I1.0":"区域2-光电1",
            "I1.1":"区域2-光电2",
            "I1.2":"区域2-急停0",
            "I1.3":"区域2-急停1",
            "I1.4":"区域2-复位",
            "I1.5":"区域2-光栅0",
            "I1.6":"区域2-光栅1",
            "I1.7":"备用",
            "I2.0":"区域3-光电1",
            "I2.1":"区域3-光电2",
            "I2.2":"区域3-急停0",
            "I2.3":"区域3-急停1",
            "I2.4":"区域3-复位",
            "I2.5":"区域3-光栅0",
            "I2.6":"区域3-光栅1",
            "I2.7":"备用",
            "I3.0":"区域4-光电1",
            "I3.1":"区域4-光电2",
            "I3.2":"区域4-急停0",
            "I3.3":"区域4-急停1",
            "I3.4":"区域4-复位",
            "I3.5":"区域4-光栅0",
            "I3.6":"区域4-光栅1",
            "I3.7":"备用",
            "I4.0":"",
            "I4.1":"",
            "I4.2":"",
            "I4.3":"",
            "I4.4":"",
            "I4.5":"",
            "I4.6":"",
            "I4.7":"",
          
            "Q0.0":"区域1-红灯",
            "Q0.1":"区域1-绿灯",
            "Q0.2":"区域1-黄灯",
            "Q0.3":"区域1-蜂鸣",
            "Q0.4":"区域2-红灯",
            "Q0.5":"区域2-绿灯",
            "Q0.6":"区域2-黄灯",
            "Q0.7":"区域2-蜂鸣",
            "Q0.0":"区域1-红灯",
            "Q0.1":"区域1-绿灯",
            "Q0.2":"区域1-黄灯",
            "Q0.3":"区域1-蜂鸣",
            "Q0.4":"区域2-红灯",
            "Q0.5":"区域2-绿灯",
            "Q0.6":"区域2-黄灯",
            "Q0.7":"区域2-蜂鸣",
            "Q1.0":"区域3-红灯",
            "Q1.1":"区域3-绿灯",
            "Q1.2":"区域3-黄灯",
            "Q1.3":"区域3-蜂鸣",
            "Q1.4":"区域4-红灯",
            "Q1.5":"区域4-绿灯",
            "Q1.6":"区域4-黄灯",
            "Q1.7":"区域4-蜂鸣"
        }

        self.io_map_safedoor = {
            "I0.0":"门锁0",
            "I0.1":"门锁1",
            "I0.2":"急停0",
            "I0.3":"急停1",
            "I0.4":"复位",
            "I0.5":"开锁",
            "I0.6":"备用",
            "I0.7":"备用",
            "I1.0":"",
            "I1.1":"",
            "I1.2":"",
            "I1.3":"",
            "I1.4":"",
            "I1.5":"",
            "I1.6":"",
            "I1.7":"",
            "I2.0":"",
            "I2.1":"",
            "I2.2":"",
            "I2.3":"",
            "I2.4":"",
            "I2.5":"",
            "I2.6":"",
            "I2.7":"",
            "I3.0":"",
            "I3.1":"",
            "I3.2":"",
            "I3.3":"",
            "I3.4":"",
            "I3.5":"",
            "I3.6":"",
            "I3.7":"",
            "I4.0":"",
            "I4.1":"",
            "I4.2":"",
            "I4.3":"",
            "I4.4":"",
            "I4.5":"",
            "I4.6":"",
            "I4.7":"",
            "Q0.0":"红灯",
            "Q0.1":"绿灯",
            "Q0.2":"黄灯",
            "Q0.3":"蜂鸣",
            "Q0.4":"门锁",
            "Q0.5":"备用",
            "Q0.6":"备用",
            "Q0.7":"备用",
            "Q1.0":"",
            "Q1.1":"",
            "Q1.2":"",
            "Q1.3":"",
            "Q1.4":"",
            "Q1.5":"",
            "Q1.6":"",
            "Q1.7":""
        }

        self.io_map_convey_X2 = {
            "I0.0":"区域1-光栅0",
            "I0.1":"区域1-光栅1",
            "I0.2":"区域1-急停0",
            "I0.3":"区域1-急停1",
            "I0.4":"区域1-光电1",
            "I0.5":"区域1-光电2",
            "I0.6":"区域1-复位",
            "I0.7":"备用",
            "I1.0":"区域2-光栅0",
            "I1.1":"区域2-光栅1",
            "I1.2":"区域2-急停0",
            "I1.3":"区域2-急停1",
            "I1.4":"区域2-光电1",
            "I1.5":"区域2-光电2",
            "I1.6":"区域2-复位",
            "I1.7":"备用",
            "I2.0":"",
            "I2.1":"",
            "I2.2":"",
            "I2.3":"",
            "I2.4":"",
            "I2.5":"",
            "I2.6":"",
            "I2.7":"",
            "I3.0":"",
            "I3.1":"",
            "I3.2":"",
            "I3.3":"",
            "I3.4":"",
            "I3.5":"",
            "I3.6":"",
            "I3.7":"",
            "I4.0":"",
            "I4.1":"",
            "I4.2":"",
            "I4.3":"",
            "I4.4":"",
            "I4.5":"",
            "I4.6":"",
            "I4.7":"",
            "Q0.0":"区域1-红灯",
            "Q0.1":"区域1-绿灯",
            "Q0.2":"区域1-黄灯",
            "Q0.3":"区域1-蜂鸣",
            "Q0.4":"区域2-红灯",
            "Q0.5":"区域2-绿灯",
            "Q0.6":"区域2-黄灯",
            "Q0.7":"区域2-蜂鸣",
            "Q1.0":"",
            "Q1.1":"",
            "Q1.2":"",
            "Q1.3":"",
            "Q1.4":"",
            "Q1.5":"",
            "Q1.6":"",
            "Q1.7":""
        }

        self.io_map_q1p_jianxuan_q3p_jianxuan = {
            "I0.0":"区域1-光电1",
            "I0.1":"区域1-光电2",
            "I0.2":"区域1-急停0",
            "I0.3":"区域1-急停1",
            "I0.4":"区域1-复位",
            "I0.5":"区域1-光栅0",
            "I0.6":"区域1-光栅1",
            "I0.7":"备用",
            "I1.0":"区域2-光栅10",
            "I1.1":"区域2-光栅11",
            "I1.2":"区域2-急停0",
            "I1.3":"区域2-急停1",
            "I1.4":"区域2-复位",
            "I1.5":"区域2-光栅20",
            "I1.6":"区域2-光栅21",
            "I1.7":"区域2-光电1",
            "I2.0":"区域2-光电2",
            "I2.1":"备用",
            "I2.2":"备用",
            "I2.3":"备用",
            "I2.4":"备用",
            "I2.5":"区域2-光栅30",
            "I2.6":"区域2-光栅31",
            "I2.7":"",
            "I3.0":"",
            "I3.1":"",
            "I3.2":"",
            "I3.3":"",
            "I3.4":"",
            "I3.5":"",
            "I3.6":"",
            "I3.7":"",
            "I4.0":"",
            "I4.1":"",
            "I4.2":"",
            "I4.3":"",
            "I4.4":"",
            "I4.5":"",
            "I4.6":"",
            "I4.7":"",
            "Q0.0":"区域1-红灯",
            "Q0.1":"区域1-绿灯",
            "Q0.2":"区域1-黄灯",
            "Q0.3":"区域1-蜂鸣",
            "Q0.4":"备用",
            "Q0.5":"备用",
            "Q0.6":"备用",
            "Q0.7":"备用",
            "Q1.0":"区域2-红灯",
            "Q1.1":"区域2-绿灯",
            "Q1.2":"区域2-黄灯",
            "Q1.3":"区域2-蜂鸣",
            "Q1.4":"备用",
            "Q1.5":"备用",
            "Q1.6":"备用",
            "Q1.7":"备用"
        }

        self.io_map_q3p_tuopan_X2 = {
            "I0.0":"区域1-光栅10",
            "I0.1":"区域1-光栅11",
            "I0.2":"区域1-急停0",
            "I0.3":"区域1-急停1",
            "I0.4":"区域1-复位",
            "I0.5":"区域1-光栅20",
            "I0.6":"区域1-光栅21",
            "I0.7":"区域1-光电1",
            "I1.0":"区域2-光栅10",
            "I1.1":"区域2-光栅11",
            "I1.2":"区域2-急停0",
            "I1.3":"区域2-急停1",
            "I1.4":"区域2-复位",
            "I1.5":"区域2-光栅20",
            "I1.6":"区域2-光栅21",
            "I1.7":"区域2-光电1",
            "I2.0":"区域1-光电2",
            "I2.1":"区域2-光电2",
            "I2.2":"",
            "I2.3":"",
            "I2.4":"",
            "I2.5":"",
            "I2.6":"",
            "I2.7":"",
            "I3.0":"",
            "I3.1":"",
            "I3.2":"",
            "I3.3":"",
            "I3.4":"",
            "I3.5":"",
            "I3.6":"",
            "I3.7":"",
            "I4.0":"",
            "I4.1":"",
            "I4.2":"",
            "I4.3":"",
            "I4.4":"",
            "I4.5":"",
            "I4.6":"",
            "I4.7":"",
            "Q0.0":"区域1-红灯",
            "Q0.1":"区域1-绿灯",
            "Q0.2":"区域1-黄灯",
            "Q0.3":"区域1-蜂鸣",
            "Q0.4":"区域2-红灯",
            "Q0.5":"区域2-绿灯",
            "Q0.6":"区域2-黄灯",
            "Q0.7":"区域2-蜂鸣",
            "Q1.0":"",
            "Q1.1":"",
            "Q1.2":"",
            "Q1.3":"",
            "Q1.4":"",
            "Q1.5":"",
            "Q1.6":"",
            "Q1.7":""
        }
        self.io_map_convey_X4 = {
            "I0.0":"区域1-光电1",
            "I0.1":"区域1-光电2",
            "I0.2":"区域1-光栅0",
            "I0.3":"区域1-光栅1",
            "I0.4":"区域1234-急停0",
            "I0.5":"区域1234-急停1",
            "I0.6":"区域1234-复位",
            "I0.7":"区域2-光电1",
            "I1.0":"区域2-光电2",
            "I1.1":"区域2-光栅0",
            "I1.2":"区域2-光栅1",
            "I1.3":"区域3-光电1",
            "I1.4":"区域3-光电2",
            "I1.5":"区域3-光栅0",
            "I1.6":"区域3-光栅1",
            "I1.7":"区域4-光电1",
            "I2.0":"区域4-光电2",
            "I2.1":"区域4-光栅0",
            "I2.2":"区域4-光栅1",
            "I2.3":"",
            "I2.4":"",
            "I2.5":"",
            "I2.6":"",
            "I2.7":"",
            "I3.0":"",
            "I3.1":"",
            "I3.2":"",
            "I3.3":"",
            "I3.4":"",
            "I3.5":"",
            "I3.6":"",
            "I3.7":"",
            "I4.0":"",
            "I4.1":"",
            "I4.2":"",
            "I4.3":"",
            "I4.4":"",
            "I4.5":"",
            "I4.6":"",
            "I4.7":"",
            "Q0.0":"区域1234-红灯",
            "Q0.1":"区域1234-绿灯",
            "Q0.2":"区域1234-黄灯",
            "Q0.3":"区域1234-蜂鸣",
            "Q0.4":"",
            "Q0.5":"",
            "Q0.6":"",
            "Q0.7":"",
            "Q1.0":"",
            "Q1.1":"",
            "Q1.2":"",
            "Q1.3":"",
            "Q1.4":"",
            "Q1.5":"",
            "Q1.6":"",
            "Q1.7":""
        }
        self.io_map_main_cabinet = {
            "I0.0":"急停0",
            "I0.1":"急停1",
            "I0.2":"使能",
            "I0.3":"复位",
            "I0.4":"火警信号(可选)",
            "I0.5":"外部急停(可选)",
            "I0.6":"外部复位(可选)",
            "I0.7":"备用",
            "I1.0":"",
            "I1.1":"",
            "I1.2":"",
            "I1.3":"",
            "I1.4":"",
            "I1.5":"",
            "I1.6":"",
            "I1.7":"",
            "I2.0":"",
            "I2.1":"",
            "I2.2":"",
            "I2.3":"",
            "I2.4":"",
            "I2.5":"",
            "I2.6":"",
            "I2.7":"",
            "I3.0":"",
            "I3.1":"",
            "I3.2":"",
            "I3.3":"",
            "I3.4":"",
            "I3.5":"",
            "I3.6":"",
            "I3.7":"",
            "I4.0":"",
            "I4.1":"",
            "I4.2":"",
            "I4.3":"",
            "I4.4":"",
            "I4.5":"",
            "I4.6":"",
            "I4.7":"",
            "Q0.0":"红灯",
            "Q0.1":"绿灯",
            "Q0.2":"黄灯",
            "Q0.3":"蜂鸣",
            "Q0.4":"备用",
            "Q0.5":"备用",
            "Q0.6":"备用",
            "Q0.7":"备用",
            "Q1.0":"",
            "Q1.1":"",
            "Q1.2":"",
            "Q1.3":"",
            "Q1.4":"",
            "Q1.5":"",
            "Q1.6":"",
            "Q1.7":""
        }

        pages = ("主电柜","维修区/安全门","上架X4","拣选X4","安全门X1","输送线X2","Q1P拣选/Q3P拣选","Q3P托盘X2","输送线X4")
        self.current_cabinet_type ="" # "主电柜","维修区/安全门","上架X4","拣选X4","安全门X1","输送线X2","Q1P拣选/Q3P拣选","Q3P托盘X2"
        self.current_cabinet_num = 0  #  电柜序号   type="维修区/安全门" num=2 表示 维修区/安全门 2号电柜
        self.current_station =     0    #  工作站点序号
        self.data  ={
            "主电柜"         : IO_data(),
            "维修区/安全门"  : IO_data(),
            "上架X4"        : IO_data(),
            "拣选X4"        : IO_data(),
            "安全门X1"      : IO_data(),
            "输送线X2"      : IO_data(),
            "Q1P拣选/Q3P拣选": IO_data(),
            "Q3P托盘X2"     : IO_data(),
             "输送线X4"      : IO_data(),
            "电柜状态"      : cabinet_status_data()
           
        }
    def set_scene_manager(self,manager):
        self.SceneManager = manager
    def set_scene(self,scene):
        self.Scene = scene
        if self.Scene:
            self.Scene.run_mode_station_change.connect(self.handle_scene_mode_change)
            
    def set_data_broker(self,data_broker): 
        self.data_broker = data_broker
        self.page_changed.connect(self.data_broker.on_current_select_changed)
        self.data_broker.data_ready.connect(self.handle_data_broker)
        self.data_broker.station_data_ready.connect(self.handle_data_broker)
    def set_station_num(self,num):
        if num:
            self.current_station = num
    def set_current_cabinet_and_num(self,name,num=1):
        if self.current_cabinet_type != name or self.current_cabinet_num !=num:
            self.current_cabinet_type =name
            self.current_cabinet_num = num
            self.page_changed.emit(name,num)
            type = 0
            if "主电柜" == name:
                type = 1
            elif "维修区/安全门" == name:
                type = 2
            elif "上架X4" == name:
                type = 3
            elif "拣选X4" == name:
                type = 4
            elif "安全门X1" == name:
                type = 5
            elif "输送线X2" == name:
                type = 6
            elif "Q1P拣选/Q3P拣选" == name:
                type = 7
            elif "Q3P托盘X2" == name:
                type = 8
            elif "输送线X4" == name:
                type = 9
            if self.data_broker is not None:
                self.data_broker.set_current_selected_type(type)
                self.data_broker.set_current_selected_num(num)

    def read_config_from_plc(self):
        read_data = self.data_broker.read_config_parameters()

        if read_data:
            
            self.father_roots["PLC2"].setCheckState(0, Qt.Checked if get_bool(read_data,0,15) else Qt.Unchecked)
            self.child_roots["维修区/安全门(X.X.X.161)"]["维修区"].setCheckState(0, Qt.Checked if get_bool(read_data,0,0) else Qt.Unchecked)
            self.child_roots["维修区/安全门(X.X.X.162)"]["维修区"].setCheckState(0, Qt.Checked if get_bool(read_data,0,1) else Qt.Unchecked)
            self.child_roots["维修区/安全门(X.X.X.163)"]["维修区"].setCheckState(0, Qt.Checked if get_bool(read_data,0,2) else Qt.Unchecked)
            self.child_roots["维修区/安全门(X.X.X.164)"]["维修区"].setCheckState(0, Qt.Checked if get_bool(read_data,0,3) else Qt.Unchecked)
            self.child_roots["维修区/安全门(X.X.X.161)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,0,4) else Qt.Unchecked)
            self.child_roots["维修区/安全门(X.X.X.162)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,0,5) else Qt.Unchecked)
            self.child_roots["维修区/安全门(X.X.X.163)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,0,6) else Qt.Unchecked)
            self.child_roots["维修区/安全门(X.X.X.164)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,0,7) else Qt.Unchecked)

            self.child_roots["上架X4(X.X.X.171)"]["上架工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,1,0 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.171)"]["上架工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,1,1 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.171)"]["上架工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,1,2 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.171)"]["上架工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,1,3 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.172)"]["上架工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,1,4 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.172)"]["上架工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,1,5 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.172)"]["上架工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,1,6 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.172)"]["上架工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,1,7 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.173)"]["上架工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,1,8 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.173)"]["上架工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,1,9 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.173)"]["上架工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,1,10) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.173)"]["上架工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,1,11) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.174)"]["上架工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,1,12) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.174)"]["上架工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,1,13) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.174)"]["上架工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,1,14) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.174)"]["上架工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,1,15) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.175)"]["上架工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,2,0 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.175)"]["上架工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,2,1 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.175)"]["上架工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,2,2 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.175)"]["上架工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,2,3 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.176)"]["上架工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,2,4 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.176)"]["上架工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,2,5 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.176)"]["上架工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,2,6 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.176)"]["上架工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,2,7 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.177)"]["上架工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,2,8 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.177)"]["上架工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,2,9 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.177)"]["上架工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,2,10) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.177)"]["上架工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,2,11) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.178)"]["上架工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,2,12) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.178)"]["上架工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,2,13) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.178)"]["上架工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,2,14) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.178)"]["上架工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,2,15) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.179)"]["上架工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,3,0 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.179)"]["上架工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,3,1 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.179)"]["上架工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,3,2 ) else Qt.Unchecked)
            self.child_roots["上架X4(X.X.X.179)"]["上架工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,3,3 ) else Qt.Unchecked)

            self.child_roots["拣选X4(X.X.X.181)"]["拣选工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,4,0 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.181)"]["拣选工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,4,1 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.181)"]["拣选工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,4,2 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.181)"]["拣选工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,4,3 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.182)"]["拣选工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,4,4 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.182)"]["拣选工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,4,5 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.182)"]["拣选工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,4,6 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.182)"]["拣选工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,4,7 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.183)"]["拣选工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,4,8 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.183)"]["拣选工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,4,9 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.183)"]["拣选工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,4,10) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.183)"]["拣选工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,4,11) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.184)"]["拣选工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,4,12) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.184)"]["拣选工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,4,13) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.184)"]["拣选工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,4,14) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.184)"]["拣选工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,4,15) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.185)"]["拣选工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,5,0 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.185)"]["拣选工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,5,1 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.185)"]["拣选工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,5,2 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.185)"]["拣选工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,5,3 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.186)"]["拣选工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,5,4 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.186)"]["拣选工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,5,5 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.186)"]["拣选工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,5,6 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.186)"]["拣选工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,5,7 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.187)"]["拣选工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,5,8 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.187)"]["拣选工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,5,9 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.187)"]["拣选工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,5,10) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.187)"]["拣选工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,5,11) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.188)"]["拣选工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,5,12) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.188)"]["拣选工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,5,13) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.188)"]["拣选工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,5,14) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.188)"]["拣选工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,5,15) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.189)"]["拣选工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,6,0 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.189)"]["拣选工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,6,1 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.189)"]["拣选工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,6,2 ) else Qt.Unchecked)
            self.child_roots["拣选X4(X.X.X.189)"]["拣选工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,6,3 ) else Qt.Unchecked)

            self.child_roots["安全门X1(X.X.X.191)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,7,0) else Qt.Unchecked)
            self.child_roots["安全门X1(X.X.X.192)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,7,1) else Qt.Unchecked)
            self.child_roots["安全门X1(X.X.X.193)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,7,2) else Qt.Unchecked)
            self.child_roots["安全门X1(X.X.X.194)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,7,3) else Qt.Unchecked)
            self.child_roots["安全门X1(X.X.X.195)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,7,4) else Qt.Unchecked)
            self.child_roots["安全门X1(X.X.X.196)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,7,5) else Qt.Unchecked)
            self.child_roots["安全门X1(X.X.X.197)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,7,6) else Qt.Unchecked)
            self.child_roots["安全门X1(X.X.X.198)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,7,7) else Qt.Unchecked)
            self.child_roots["安全门X1(X.X.X.199)"]["安全门"].setCheckState(0, Qt.Checked if get_bool(read_data,7,8 ) else Qt.Unchecked)

            self.child_roots["输送线X2(X.X.X.201)"]["输送线工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,8,0 ) else Qt.Unchecked)
            self.child_roots["输送线X2(X.X.X.201)"]["输送线工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,8,1 ) else Qt.Unchecked)
            self.child_roots["输送线X2(X.X.X.202)"]["输送线工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,8,2 ) else Qt.Unchecked)
            self.child_roots["输送线X2(X.X.X.202)"]["输送线工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,8,3 ) else Qt.Unchecked)
            self.child_roots["输送线X2(X.X.X.203)"]["输送线工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,8,4 ) else Qt.Unchecked)
            self.child_roots["输送线X2(X.X.X.203)"]["输送线工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,8,5 ) else Qt.Unchecked)
            self.child_roots["输送线X2(X.X.X.204)"]["输送线工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,8,6 ) else Qt.Unchecked)
            self.child_roots["输送线X2(X.X.X.204)"]["输送线工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,8,7 ) else Qt.Unchecked)

            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.211)"]["Q1P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,9,0) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.212)"]["Q1P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,9,1) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.213)"]["Q1P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,9,2) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.214)"]["Q1P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,9,3) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.215)"]["Q1P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,9,4) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.216)"]["Q1P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,9,5) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.217)"]["Q1P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,9,6) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.218)"]["Q1P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,9,7) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.219)"]["Q1P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,9,8) else Qt.Unchecked)

            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.211)"]["Q3P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,10,0) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.212)"]["Q3P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,10,1) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.213)"]["Q3P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,10,2) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.214)"]["Q3P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,10,3) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.215)"]["Q3P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,10,4) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.216)"]["Q3P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,10,5) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.217)"]["Q3P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,10,6) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.218)"]["Q3P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,10,7) else Qt.Unchecked)
            self.child_roots["Q1P拣选/Q3P拣选(X.X.X.219)"]["Q3P拣选工作站"].setCheckState(0, Qt.Checked if get_bool(read_data,10,8) else Qt.Unchecked)

            self.child_roots["Q3P托盘X2(X.X.X.221)"]["Q3P托盘工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,11,0) else Qt.Unchecked)
            self.child_roots["Q3P托盘X2(X.X.X.221)"]["Q3P托盘工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,11,1) else Qt.Unchecked)
            self.child_roots["Q3P托盘X2(X.X.X.222)"]["Q3P托盘工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,11,2) else Qt.Unchecked)
            self.child_roots["Q3P托盘X2(X.X.X.222)"]["Q3P托盘工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,11,3) else Qt.Unchecked)
            self.child_roots["Q3P托盘X2(X.X.X.223)"]["Q3P托盘工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,11,4) else Qt.Unchecked)
            self.child_roots["Q3P托盘X2(X.X.X.223)"]["Q3P托盘工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,11,5) else Qt.Unchecked)
            self.child_roots["Q3P托盘X2(X.X.X.224)"]["Q3P托盘工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,11,6) else Qt.Unchecked)
            self.child_roots["Q3P托盘X2(X.X.X.224)"]["Q3P托盘工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,11,7) else Qt.Unchecked)

            self.child_roots["输送线X4(X.X.X.231)"]["输送线工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,12,0  ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.231)"]["输送线工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,12,1  ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.231)"]["输送线工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,12,2  ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.231)"]["输送线工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,12,3  ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.232)"]["输送线工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,12,4  ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.232)"]["输送线工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,12,5  ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.232)"]["输送线工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,12,6  ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.232)"]["输送线工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,12,7  ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.233)"]["输送线工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,12,8  ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.233)"]["输送线工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,12,9  ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.233)"]["输送线工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,12,10 ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.233)"]["输送线工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,12,11 ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.234)"]["输送线工作站1"].setCheckState(0, Qt.Checked if get_bool(read_data,12,12 ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.234)"]["输送线工作站2"].setCheckState(0, Qt.Checked if get_bool(read_data,12,13 ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.234)"]["输送线工作站3"].setCheckState(0, Qt.Checked if get_bool(read_data,12,14 ) else Qt.Unchecked)
            self.child_roots["输送线X4(X.X.X.234)"]["输送线工作站4"].setCheckState(0, Qt.Checked if get_bool(read_data,12,15 ) else Qt.Unchecked)

        for name, parent_item in self.father_roots.items():
            any_checked = False

            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                print(i, parent_item.text(0),child.checkState(0))
                if child.checkState(0)==Qt.Checked:
                    any_checked = True
                    break
            if name!="PLC2":
                parent_item.setCheckState(0, Qt.Checked) if any_checked else parent_item.setCheckState(0, Qt.Unchecked)
        
  
        self.params_read_done.emit(bool(read_data))

    def write_config_to_plc(self):
        data = [0,0,0,0,0,0,0,0,0,0,0,0,0,1]
        set_bool(data,0,15,True if self.father_roots["PLC2"].checkState(0)==Qt.Checked else False)
        set_bool(data,0,0,True if self.child_roots["维修区/安全门(X.X.X.161)"]["维修区"].checkState(0)==Qt.Checked else False)
        set_bool(data,0,1,True if self.child_roots["维修区/安全门(X.X.X.162)"]["维修区"].checkState(0)==Qt.Checked else False)
        set_bool(data,0,2,True if self.child_roots["维修区/安全门(X.X.X.163)"]["维修区"].checkState(0)==Qt.Checked else False)
        set_bool(data,0,3,True if self.child_roots["维修区/安全门(X.X.X.164)"]["维修区"].checkState(0)==Qt.Checked else False)
        set_bool(data,0,4,True if self.child_roots["维修区/安全门(X.X.X.161)"]["安全门"].checkState(0)==Qt.Checked else False)
        set_bool(data,0,5,True if self.child_roots["维修区/安全门(X.X.X.162)"]["安全门"].checkState(0)==Qt.Checked else False)
        set_bool(data,0,6,True if self.child_roots["维修区/安全门(X.X.X.163)"]["安全门"].checkState(0)==Qt.Checked else False)
        set_bool(data,0,7,True if self.child_roots["维修区/安全门(X.X.X.164)"]["安全门"].checkState(0)==Qt.Checked else False)

        set_bool(data,1,0 ,True if self.child_roots["上架X4(X.X.X.171)"]["上架工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,1 ,True if self.child_roots["上架X4(X.X.X.171)"]["上架工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,2 ,True if self.child_roots["上架X4(X.X.X.171)"]["上架工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,3 ,True if self.child_roots["上架X4(X.X.X.171)"]["上架工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,4 ,True if self.child_roots["上架X4(X.X.X.172)"]["上架工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,5 ,True if self.child_roots["上架X4(X.X.X.172)"]["上架工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,6 ,True if self.child_roots["上架X4(X.X.X.172)"]["上架工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,7 ,True if self.child_roots["上架X4(X.X.X.172)"]["上架工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,8 , True if self.child_roots["上架X4(X.X.X.173)"]["上架工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,9 , True if self.child_roots["上架X4(X.X.X.173)"]["上架工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,10, True if self.child_roots["上架X4(X.X.X.173)"]["上架工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,11, True if self.child_roots["上架X4(X.X.X.173)"]["上架工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,12, True if self.child_roots["上架X4(X.X.X.174)"]["上架工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,13, True if self.child_roots["上架X4(X.X.X.174)"]["上架工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,14, True if self.child_roots["上架X4(X.X.X.174)"]["上架工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,1,15, True if self.child_roots["上架X4(X.X.X.174)"]["上架工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,0 ,True if self.child_roots["上架X4(X.X.X.175)"]["上架工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,1 ,True if self.child_roots["上架X4(X.X.X.175)"]["上架工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,2 ,True if self.child_roots["上架X4(X.X.X.175)"]["上架工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,3 ,True if self.child_roots["上架X4(X.X.X.175)"]["上架工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,4 ,True if self.child_roots["上架X4(X.X.X.176)"]["上架工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,5 ,True if self.child_roots["上架X4(X.X.X.176)"]["上架工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,6 ,True if self.child_roots["上架X4(X.X.X.176)"]["上架工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,7 ,True if self.child_roots["上架X4(X.X.X.176)"]["上架工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,8 , True if self.child_roots["上架X4(X.X.X.177)"]["上架工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,9 , True if self.child_roots["上架X4(X.X.X.177)"]["上架工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,10, True if self.child_roots["上架X4(X.X.X.177)"]["上架工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,11, True if self.child_roots["上架X4(X.X.X.177)"]["上架工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,12, True if self.child_roots["上架X4(X.X.X.178)"]["上架工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,13, True if self.child_roots["上架X4(X.X.X.178)"]["上架工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,14, True if self.child_roots["上架X4(X.X.X.178)"]["上架工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,2,15, True if self.child_roots["上架X4(X.X.X.178)"]["上架工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,3,0 , True if self.child_roots["上架X4(X.X.X.179)"]["上架工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,3,1 , True if self.child_roots["上架X4(X.X.X.179)"]["上架工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,3,2 , True if self.child_roots["上架X4(X.X.X.179)"]["上架工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,3,3 , True if self.child_roots["上架X4(X.X.X.179)"]["上架工作站4"].checkState(0)==Qt.Checked else False)

        set_bool(data,4,0 ,True if self.child_roots["拣选X4(X.X.X.181)"]["拣选工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,1 ,True if self.child_roots["拣选X4(X.X.X.181)"]["拣选工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,2 ,True if self.child_roots["拣选X4(X.X.X.181)"]["拣选工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,3 ,True if self.child_roots["拣选X4(X.X.X.181)"]["拣选工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,4 ,True if self.child_roots["拣选X4(X.X.X.182)"]["拣选工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,5 ,True if self.child_roots["拣选X4(X.X.X.182)"]["拣选工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,6 ,True if self.child_roots["拣选X4(X.X.X.182)"]["拣选工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,7 ,True if self.child_roots["拣选X4(X.X.X.182)"]["拣选工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,8 , True if self.child_roots["拣选X4(X.X.X.183)"]["拣选工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,9 , True if self.child_roots["拣选X4(X.X.X.183)"]["拣选工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,10, True if self.child_roots["拣选X4(X.X.X.183)"]["拣选工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,11, True if self.child_roots["拣选X4(X.X.X.183)"]["拣选工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,12, True if self.child_roots["拣选X4(X.X.X.184)"]["拣选工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,13, True if self.child_roots["拣选X4(X.X.X.184)"]["拣选工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,14, True if self.child_roots["拣选X4(X.X.X.184)"]["拣选工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,4,15, True if self.child_roots["拣选X4(X.X.X.184)"]["拣选工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,0 ,True if self.child_roots["拣选X4(X.X.X.185)"]["拣选工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,1 ,True if self.child_roots["拣选X4(X.X.X.185)"]["拣选工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,2 ,True if self.child_roots["拣选X4(X.X.X.185)"]["拣选工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,3 ,True if self.child_roots["拣选X4(X.X.X.185)"]["拣选工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,4 ,True if self.child_roots["拣选X4(X.X.X.186)"]["拣选工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,5 ,True if self.child_roots["拣选X4(X.X.X.186)"]["拣选工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,6 ,True if self.child_roots["拣选X4(X.X.X.186)"]["拣选工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,7 ,True if self.child_roots["拣选X4(X.X.X.186)"]["拣选工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,8 , True if self.child_roots["拣选X4(X.X.X.187)"]["拣选工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,9 , True if self.child_roots["拣选X4(X.X.X.187)"]["拣选工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,10, True if self.child_roots["拣选X4(X.X.X.187)"]["拣选工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,11, True if self.child_roots["拣选X4(X.X.X.187)"]["拣选工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,12, True if self.child_roots["拣选X4(X.X.X.188)"]["拣选工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,13, True if self.child_roots["拣选X4(X.X.X.188)"]["拣选工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,14, True if self.child_roots["拣选X4(X.X.X.188)"]["拣选工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,5,15, True if self.child_roots["拣选X4(X.X.X.188)"]["拣选工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,6,0 , True if self.child_roots["拣选X4(X.X.X.189)"]["拣选工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,6,1 , True if self.child_roots["拣选X4(X.X.X.189)"]["拣选工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,6,2 , True if self.child_roots["拣选X4(X.X.X.189)"]["拣选工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,6,3 , True if self.child_roots["拣选X4(X.X.X.189)"]["拣选工作站4"].checkState(0)==Qt.Checked else False)
        
        set_bool(data,7,0, True if self.child_roots["安全门X1(X.X.X.191)"]["安全门"].checkState(0)==Qt.Checked else False)
        set_bool(data,7,1, True if self.child_roots["安全门X1(X.X.X.192)"]["安全门"].checkState(0)==Qt.Checked else False)
        set_bool(data,7,2, True if self.child_roots["安全门X1(X.X.X.193)"]["安全门"].checkState(0)==Qt.Checked else False)
        set_bool(data,7,3, True if self.child_roots["安全门X1(X.X.X.194)"]["安全门"].checkState(0)==Qt.Checked else False)
        set_bool(data,7,4, True if self.child_roots["安全门X1(X.X.X.195)"]["安全门"].checkState(0)==Qt.Checked else False)
        set_bool(data,7,5, True if self.child_roots["安全门X1(X.X.X.196)"]["安全门"].checkState(0)==Qt.Checked else False)
        set_bool(data,7,6, True if self.child_roots["安全门X1(X.X.X.197)"]["安全门"].checkState(0)==Qt.Checked else False)
        set_bool(data,7,7, True if self.child_roots["安全门X1(X.X.X.198)"]["安全门"].checkState(0)==Qt.Checked else False)
        set_bool(data,7,8, True if self.child_roots["安全门X1(X.X.X.199)"]["安全门"].checkState(0)==Qt.Checked else False)

        set_bool(data,8,0, True if self.child_roots["输送线X2(X.X.X.201)"]["输送线工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,8,1, True if self.child_roots["输送线X2(X.X.X.201)"]["输送线工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,8,2, True if self.child_roots["输送线X2(X.X.X.202)"]["输送线工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,8,3, True if self.child_roots["输送线X2(X.X.X.202)"]["输送线工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,8,4, True if self.child_roots["输送线X2(X.X.X.203)"]["输送线工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,8,5, True if self.child_roots["输送线X2(X.X.X.203)"]["输送线工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,8,6, True if self.child_roots["输送线X2(X.X.X.204)"]["输送线工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,8,7, True if self.child_roots["输送线X2(X.X.X.204)"]["输送线工作站2"].checkState(0)==Qt.Checked else False)


        set_bool(data,9,0, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.211)"]["Q1P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,9,1, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.212)"]["Q1P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,9,2, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.213)"]["Q1P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,9,3, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.214)"]["Q1P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,9,4, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.215)"]["Q1P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,9,5, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.216)"]["Q1P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,9,6, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.217)"]["Q1P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,9,7, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.218)"]["Q1P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,9,8, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.219)"]["Q1P拣选工作站"].checkState(0)==Qt.Checked else False)

        set_bool(data,10,0, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.211)"]["Q3P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,10,1, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.212)"]["Q3P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,10,2, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.213)"]["Q3P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,10,3, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.214)"]["Q3P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,10,4, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.215)"]["Q3P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,10,5, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.216)"]["Q3P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,10,6, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.217)"]["Q3P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,10,7, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.218)"]["Q3P拣选工作站"].checkState(0)==Qt.Checked else False)
        set_bool(data,10,8, True if self.child_roots["Q1P拣选/Q3P拣选(X.X.X.219)"]["Q3P拣选工作站"].checkState(0)==Qt.Checked else False)

        set_bool(data,11,0, True if self.child_roots["Q3P托盘X2(X.X.X.221)"]["Q3P托盘工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,11,1, True if self.child_roots["Q3P托盘X2(X.X.X.221)"]["Q3P托盘工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,11,2, True if self.child_roots["Q3P托盘X2(X.X.X.222)"]["Q3P托盘工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,11,3, True if self.child_roots["Q3P托盘X2(X.X.X.222)"]["Q3P托盘工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,11,4, True if self.child_roots["Q3P托盘X2(X.X.X.223)"]["Q3P托盘工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,11,5, True if self.child_roots["Q3P托盘X2(X.X.X.223)"]["Q3P托盘工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,11,6, True if self.child_roots["Q3P托盘X2(X.X.X.224)"]["Q3P托盘工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,11,7, True if self.child_roots["Q3P托盘X2(X.X.X.224)"]["Q3P托盘工作站2"].checkState(0)==Qt.Checked else False)

        set_bool(data,12,0 , True if self.child_roots["输送线X4(X.X.X.231)"]["输送线工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,1 , True if self.child_roots["输送线X4(X.X.X.231)"]["输送线工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,2 , True if self.child_roots["输送线X4(X.X.X.231)"]["输送线工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,3 , True if self.child_roots["输送线X4(X.X.X.231)"]["输送线工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,4 , True if self.child_roots["输送线X4(X.X.X.232)"]["输送线工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,5 , True if self.child_roots["输送线X4(X.X.X.232)"]["输送线工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,6 , True if self.child_roots["输送线X4(X.X.X.232)"]["输送线工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,7 , True if self.child_roots["输送线X4(X.X.X.232)"]["输送线工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,8 , True if self.child_roots["输送线X4(X.X.X.233)"]["输送线工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,9 , True if self.child_roots["输送线X4(X.X.X.233)"]["输送线工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,10, True if self.child_roots["输送线X4(X.X.X.233)"]["输送线工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,11, True if self.child_roots["输送线X4(X.X.X.233)"]["输送线工作站4"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,12, True if self.child_roots["输送线X4(X.X.X.234)"]["输送线工作站1"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,13, True if self.child_roots["输送线X4(X.X.X.234)"]["输送线工作站2"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,14, True if self.child_roots["输送线X4(X.X.X.234)"]["输送线工作站3"].checkState(0)==Qt.Checked else False)
        set_bool(data,12,15, True if self.child_roots["输送线X4(X.X.X.234)"]["输送线工作站4"].checkState(0)==Qt.Checked else False)

        print('--------------------------------')
        print(data)
        print('--------------------------------')
        result = self.data_broker.write_config_parameters(data)
        self.params_write_done.emit(result)

    def on_item_clicked(self,item):
        if item.parent() is None:  # 根节点
            if item.childCount() == 0:
                return
            state = item.checkState(0)
            # if state:
            #     for i in range(item.childCount()):
            #         if item.child(i).checkState(0):
            #             return
            for i in range(item.childCount()):
                child = item.child(i)
                child.setCheckState(0, state)
        else:  # 子节点
            parent = item.parent()
            all_checked = True
            any_checked = False
            for i in range(parent.childCount()):
                child = parent.child(i)
                if child.checkState(0) != Qt.Checked:
                    all_checked = False
                else:
                    any_checked = True
            
            # if all_checked:
            #     parent.setCheckState(0, Qt.Checked)
            # elif not any_checked:
            #     parent.setCheckState(0, Qt.Unchecked)
            if any_checked:
                parent.setCheckState(0, Qt.Checked)
            else:
                parent.setCheckState(0, Qt.Unchecked)

    def on_item_changed(self):
        """节点的勾选状态变换时，处理"""

        a,b,c,d,e,f,g,h = 0,0,0,0,0,0,0,0
        list_a,list_b,list_c,list_d,list_e,list_f,list_g,list_h =[],[],[],[],[],[],[],[]
        for i, (key ,value) in enumerate( self.father_roots.items() ):

            state = value.checkState(0) == Qt.Checked
        
            id = self.SceneManager.m_name_items[key]
            item = self.SceneManager.findItem(id)
            item.set_visibility(state)

            if key=="PLC2":
                id = self.SceneManager.m_name_items["外部网络"]
                item2move = self.SceneManager.findItem(id)
                if state:
                    item2move.change_position(QPointF(565.7,2409.8))
                else:
                    item2move.change_position(QPointF(841.3,2421.7))
            
            if 0<i<4:
                list_a.append(item)
                if state:
                    a = i
            elif 0==i:
                list_a.append(item)
                a= 0 if state else -1
            
            if 4<i<13:
                list_b.append(item)
                if state:
                    b = i-4
            elif 4==i:
                list_b.append(item)
                b= 0 if state else -1
            
            if 13<i<22:
                list_c.append(item)
                if state:
                    c = i-13
            elif 13==i:
                list_c.append(item)
                c= 0 if state else -1
            
            if 22<i<31:
                list_d.append(item)
                if state:
                    d = i-22
            elif 22==i:
                list_d.append(item)
                d= 0 if state else -1
                    
            if 31<i<35:
                list_e.append(item)
                if state:
                    e = i-31
            elif 31==i:
                list_e.append(item)
                e= 0 if state else -1

            if 35<i<44:
                list_f.append(item)
                if state:
                    f = i-35
            elif 35==i:
                list_f.append(item)
                f= 0 if state else -1
            
            if 44<i<48:
                list_g.append(item)
                if state:
                    g = i-44
            elif 44==i:
                list_g.append(item)
                g= 0 if state else -1
            
            if 48<i<52:
                list_h.append(item)
                if state:
                    h = i-48
            elif 48==i:
                list_h.append(item)
                h= 0 if state else -1
        
        id = self.SceneManager.m_name_items["网线1"]
        item = self.SceneManager.findItem(id)
        if a>=0:
            end_pos = list_a[a].get_scene_center_pos()
            item.change_end_pos(end_pos)
        else:
            
            end_pos = item.get_scene_head_pos()
            item.change_end_pos(end_pos)
        
        id = self.SceneManager.m_name_items["网线2"]
        item = self.SceneManager.findItem(id)
        if b>=0:
            end_pos = list_b[b].get_scene_center_pos()
            item.change_end_pos(end_pos)
        else:
           
            end_pos = item.get_scene_head_pos()
            item.change_end_pos(end_pos)

        id = self.SceneManager.m_name_items["网线3"]
        item = self.SceneManager.findItem(id)
        if c>=0:
            end_pos = list_c[c].get_scene_center_pos()
            item.change_end_pos(end_pos)
        else:
            
            end_pos = item.get_scene_head_pos()
            item.change_end_pos(end_pos)

        id = self.SceneManager.m_name_items["网线4"]
        item = self.SceneManager.findItem(id)
        if d>=0:
            end_pos = list_d[d].get_scene_center_pos()
            item.change_end_pos(end_pos)
        else:
            
            end_pos = item.get_scene_head_pos()
            item.change_end_pos(end_pos)

        id = self.SceneManager.m_name_items["网线5"]
        item = self.SceneManager.findItem(id)
        if e>=0:
            end_pos = list_e[e].get_scene_center_pos()
            item.change_end_pos(end_pos)
        else:            
            end_pos = item.get_scene_head_pos()
            item.change_end_pos(end_pos)

        
        id = self.SceneManager.m_name_items["网线6"]
        item = self.SceneManager.findItem(id)
        if f>=0:
            end_pos = list_f[f].get_scene_center_pos()
            item.change_end_pos(end_pos)
        else:            
            end_pos = item.get_scene_head_pos()
            item.change_end_pos(end_pos)
        
        id = self.SceneManager.m_name_items["网线7"]
        item = self.SceneManager.findItem(id)
        if g>=0:
            end_pos = list_g[g].get_scene_center_pos()
            item.change_end_pos(end_pos)
        else:            
            end_pos = item.get_scene_head_pos()
            item.change_end_pos(end_pos)
        
        id = self.SceneManager.m_name_items["网线8"]
        item = self.SceneManager.findItem(id)
        if h>=0:
            end_pos = list_h[h].get_scene_center_pos()
            item.change_end_pos(end_pos)
        else:            
            end_pos = item.get_scene_head_pos()
            item.change_end_pos(end_pos)

    def handle_station_change(self,station):
        """"工作站切换时"""
        if self.Scene.mode() == SceneMode.Design:
            return
        selected_item = self.Scene.current_selected
        if not isinstance(selected_item,group_element):
            return
      
        last_digit = None
        for char in reversed(station):
            if char.isdigit():
                last_digit = int(char)
                break
            
                
        self.set_station_num(last_digit)

        x   =selected_item.get_scene_bottomLeft().x() 
        y   =selected_item.get_scene_bottomLeft().y() 
        pos =    QPointF(x,y)
        self.hide_all_station()
        if  "维修区工作站"==station:
            self.set_station_num(1)
            id = self.SceneManager.m_name_items["维修区"]
            item2move = self.SceneManager.findItem(id)
            item2move.change_position(pos)
            item2move.set_visibility(True)

        elif "安全门工作站"==station:
            self.set_station_num(2)
            id = self.SceneManager.m_name_items["安全门"]
            item2move = self.SceneManager.findItem(id)
            item2move.change_position(pos)
            item2move.set_visibility(True)

        elif "上架工作站" in station:
            id = self.SceneManager.m_name_items["上架工作站"]
            item2move = self.SceneManager.findItem(id)
            item2move.change_position(pos)
            item2move.set_visibility(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_标题"]).context = station
            
        elif "Q1P拣选工作站" in station:
            self.set_station_num(1)
            id = self.SceneManager.m_name_items["Q1P拣选工作站"]
            item2move = self.SceneManager.findItem(id)
            item2move.change_position(pos)
            item2move.set_visibility(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["Q1P拣选工作站_标题"]).context = station
            
        elif "输送线工作站" in station:
            id = self.SceneManager.m_name_items["输送线"]
            item2move = self.SceneManager.findItem(id)
            item2move.change_position(pos)
            item2move.set_visibility(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["输送线工作站_标题"]).context = station

        elif "Q3P拣选工作站" in station:
            self.set_station_num(2)
            id = self.SceneManager.m_name_items["Q3P拣选工作站"]
            item2move = self.SceneManager.findItem(id)
            item2move.change_position(pos)
            item2move.set_visibility(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P拣选工作站_标题"]).context = station
        
        elif "Q3P托盘工作站" in station:
            id = self.SceneManager.m_name_items["Q3P托盘工作站"]
            item2move = self.SceneManager.findItem(id)
            item2move.change_position(pos)
            item2move.set_visibility(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_标题"]).context = station

    def hide_all_station(self):
        id = self.SceneManager.m_name_items["维修区"]
        item2move = self.SceneManager.findItem(id)
        item2move.set_visibility(False)
        id = self.SceneManager.m_name_items["安全门"]
        item2move = self.SceneManager.findItem(id)
        item2move.set_visibility(False)
        id = self.SceneManager.m_name_items["上架工作站"]
        item2move = self.SceneManager.findItem(id)
        item2move.set_visibility(False)
        id = self.SceneManager.m_name_items["Q1P拣选工作站"]
        item2move = self.SceneManager.findItem(id)
        item2move.set_visibility(False)
        id = self.SceneManager.m_name_items["输送线"]
        item2move = self.SceneManager.findItem(id)
        item2move.set_visibility(False)
        id = self.SceneManager.m_name_items["Q3P拣选工作站"]
        item2move = self.SceneManager.findItem(id)
        item2move.set_visibility(False)
        id = self.SceneManager.m_name_items["Q3P托盘工作站"]
        item2move = self.SceneManager.findItem(id)
        item2move.set_visibility(False)
       
    def hide_io_status_window(self):
        id = self.SceneManager.m_name_items["IO状态"]
        io_status_item = self.SceneManager.findItem(id)
        io_status_item.set_visibility(False)
        self.hide_all_station()

    def set_selectable_of_station_windows(self,enable):
        self.SceneManager.findItem(self.SceneManager.m_name_items["维修区"]).set_selectable(enable)
        self.SceneManager.findItem(self.SceneManager.m_name_items["安全门"]).set_selectable(enable)
        self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站"]).set_selectable(enable)
        self.SceneManager.findItem(self.SceneManager.m_name_items["Q1P拣选工作站"]).set_selectable(enable)
        self.SceneManager.findItem(self.SceneManager.m_name_items["输送线"]).set_selectable(enable)
        self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P拣选工作站"]).set_selectable(enable)
        self.SceneManager.findItem(self.SceneManager.m_name_items["IO状态"]).set_selectable(enable)
        self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站"]).set_selectable(enable)
        self.SceneManager.findItem(81).set_selectable(enable)
        self.SceneManager.findItem(82).set_selectable(enable)
        self.SceneManager.findItem(83).set_selectable(enable)
        self.SceneManager.findItem(84).set_selectable(enable)
        self.SceneManager.findItem(635).set_selectable(enable)
        if enable:
            self.SceneManager.findItem(self.SceneManager.m_name_items["维修区"]).set_visibility(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["安全门"]).set_visibility(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站"]).set_visibility(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["Q1P拣选工作站"]).set_visibility(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["输送线"]).set_visibility(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P拣选工作站"]).set_visibility(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["IO状态"]).set_visibility(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站"]).set_visibility(True)

    def handle_scene_mode_change(self,mode:SceneMode):
        
        if mode == SceneMode.Run:
            for key  in self.father_roots.keys():
                self.SceneManager.findItem(self.SceneManager.m_name_items[key]).set_selectable(True)
            self.SceneManager.findItem(self.SceneManager.m_name_items["主电柜"]).set_selectable(True)

    def handle_selectionChanged(self):
        """Run当场景选择变化时更新属性窗口"""
        if self.Scene.mode() == SceneMode.Design:
            return
        selected_item = self.Scene.current_selected
        # self.hide_all_io_group()
        
        if isinstance(selected_item,group_element):
            
            if selected_item.get_name() in self.child_roots.keys() or selected_item.get_name()=="主电柜" :
                
                id = self.SceneManager.m_name_items["IO状态"]
                io_status_item = self.SceneManager.findItem(id)
                io_status_item.set_visibility(False)
                h   = io_status_item.getSize().height()
                x   =selected_item.get_scene_topLeft().x() 
                y   =selected_item.get_scene_topLeft().y() -h
                pos =    QPointF(x,y)
                io_status_item.change_position(pos)
                last_digit = None
                for char in reversed(selected_item.get_name()):
                    if char.isdigit():
                        last_digit = int(char)
                        break
                # self.current_station = last_digit 
                if "维修区/安全门" in selected_item.get_name():
                    
                    self.set_current_cabinet_and_num("维修区/安全门",last_digit)
                    for key,value in self.io_map_maintain_safedoor.items():
                        text = key +"_text"
                        item = self.SceneManager.findItem(self.SceneManager.m_name_items[text])
                        item.context  = value
                    io_status_item.set_visibility(True)
                    id = self.SceneManager.m_name_items["DI2_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI3_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI4_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    # id = self.SceneManager.m_name_items["DO1_group"]
                    # item = self.SceneManager.findItem(id)
                    # item.set_visibility(False)

                elif "上架X4" in selected_item.get_name():
                    self.set_current_cabinet_and_num("上架X4",last_digit)
                    for key,value in self.io_map_shangjia_X4.items():
                        text = key +"_text"
                        item = self.SceneManager.findItem(self.SceneManager.m_name_items[text])
                        item.context  = value
                    io_status_item.set_visibility(True)

                elif "拣选X4" in selected_item.get_name():
                    self.set_current_cabinet_and_num("拣选X4",last_digit)
                    for key,value in self.io_map_jianxuan_X4.items():
                        text = key +"_text"
                        item = self.SceneManager.findItem(self.SceneManager.m_name_items[text])
                        item.context  = value
                    io_status_item.set_visibility(True)

                    self.SceneManager.findItem(self.SceneManager.m_name_items["DI4_group"]).set_visibility(False)
                    
                elif "安全门X1" in selected_item.get_name():
                    self.set_current_cabinet_and_num("安全门X1",last_digit)
                    for key,value in self.io_map_safedoor.items():
                        text = key +"_text"
                        item = self.SceneManager.findItem(self.SceneManager.m_name_items[text])
                        item.context  = value
                    io_status_item.set_visibility(True)

                    id = self.SceneManager.m_name_items["DI1_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI2_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI3_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI4_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DO1_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)

                elif "输送线X2" in selected_item.get_name():
                    self.set_current_cabinet_and_num("输送线X2",last_digit)
                    for key,value in self.io_map_convey_X2.items():
                        text = key +"_text"
                        item = self.SceneManager.findItem(self.SceneManager.m_name_items[text])
                        item.context  = value
                    io_status_item.set_visibility(True)

                    id = self.SceneManager.m_name_items["DI2_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI3_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI4_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DO1_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                
                elif "Q1P拣选/Q3P拣选" in selected_item.get_name():
                    self.set_current_cabinet_and_num("Q1P拣选/Q3P拣选",last_digit)
                    for key,value in self.io_map_q1p_jianxuan_q3p_jianxuan.items():
                        text = key +"_text"
                        item = self.SceneManager.findItem(self.SceneManager.m_name_items[text])
                        item.context  = value
                    io_status_item.set_visibility(True)

           
                    id = self.SceneManager.m_name_items["DI3_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI4_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    
                elif "Q3P托盘X2" in selected_item.get_name():
                    self.set_current_cabinet_and_num("Q3P托盘X2",last_digit)
                    for key,value in self.io_map_q3p_tuopan_X2.items():
                        text = key +"_text"
                        item = self.SceneManager.findItem(self.SceneManager.m_name_items[text])
                        item.context  = value
                    io_status_item.set_visibility(True)

           
                    id = self.SceneManager.m_name_items["DI3_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI4_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DO1_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                
                elif "输送线X4" in selected_item.get_name():
                    self.set_current_cabinet_and_num("输送线X4",last_digit)
                    for key,value in self.io_map_convey_X4.items():
                        text = key +"_text"
                        item = self.SceneManager.findItem(self.SceneManager.m_name_items[text])
                        item.context  = value
                    io_status_item.set_visibility(True)

                  
                    id = self.SceneManager.m_name_items["DI3_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI4_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DO1_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    
                elif "主电柜" in selected_item.get_name():
                    self.set_current_cabinet_and_num("主电柜")
                    print("------------------------------------主电柜-----------------------------------")
                    for key,value in self.io_map_main_cabinet.items():
                        text = key +"_text"
                        item = self.SceneManager.findItem(self.SceneManager.m_name_items[text])
                        item.context  = value
                    io_status_item.set_visibility(True)

                    id = self.SceneManager.m_name_items["DI1_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI2_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI3_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DI4_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)
                    id = self.SceneManager.m_name_items["DO1_group"]
                    item = self.SceneManager.findItem(id)
                    item.set_visibility(False)

        else:
            
            self.set_current_cabinet_and_num("")
            id = self.SceneManager.m_name_items["IO状态"]
            io_status_item = self.SceneManager.findItem(id)
            io_status_item.set_visibility(False)
            self.hide_all_station()
            self.close_property_window.emit()
    
    


    def handle_data_broker(self, data_packet: tuple):
        name, data = data_packet
        
        if name =="电柜状态":
            self.data["电柜状态"].main_is_ok           = get_bool(data,0,0)
            self.data["电柜状态"].maintain_safedoor_ok = [get_bool(data,1,0),get_bool(data,1,1),get_bool(data,1,2),get_bool(data,1,3)]
            self.data["电柜状态"].shangjiaX4_ok        = [get_bool(data,2,0),get_bool(data,2,1),get_bool(data,2,2),get_bool(data,2,3)
                                                      ,get_bool(data,2,4),get_bool(data,2,5),get_bool(data,2,6),get_bool(data,2,7),get_bool(data,2,8)]
            self.data["电柜状态"].jianxuanX4_ok        = [get_bool(data,3,0),get_bool(data,3,1),get_bool(data,3,2),get_bool(data,3,3)
                                                      ,get_bool(data,3,4),get_bool(data,3,5),get_bool(data,3,6),get_bool(data,3,7),get_bool(data,3,8)]
            self.data["电柜状态"].safedoorX1_ok        = [get_bool(data,4,0),get_bool(data,4,1),get_bool(data,4,2),get_bool(data,4,3)
                                                        ,get_bool(data,4,4),get_bool(data,4,5),get_bool(data,4,6),get_bool(data,4,7),get_bool(data,4,8)]
            self.data["电柜状态"].conveyX2_ok          =    [get_bool(data,5,0),get_bool(data,5,1),get_bool(data,5,2),get_bool(data,5,3)]

            self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_ok          =    [get_bool(data,6,0),get_bool(data,6,1),get_bool(data,6,2),get_bool(data,6,3)
                                                        ,get_bool(data,6,4),get_bool(data,6,5),get_bool(data,6,6),get_bool(data,6,7),get_bool(data,6,8)]
            self.data["电柜状态"].q3p_tuopan_X2_ok          =    [get_bool(data,7,0),get_bool(data,7,1),get_bool(data,7,2),get_bool(data,7,3)]

            self.data["电柜状态"].conveyX4_ok          =    [get_bool(data,8,0),get_bool(data,8,1),get_bool(data,8,2),get_bool(data,8,3)]


            self.data["电柜状态"].main_is_err           = get_bool(data,10,0) 

            self.data["电柜状态"].maintain_safedoor_err = [get_bool(data,11,0),get_bool(data,11,1),get_bool(data,11,2),get_bool(data,11,3)] 
    

            self.data["电柜状态"].shangjiaX4_err        = [get_bool(data,12,0),get_bool(data,12,1),get_bool(data,12,2),get_bool(data,12,3)
                                                      ,get_bool(data,11,4),get_bool(data,12,5),get_bool(data,12,6),get_bool(data,12,7),get_bool(data,12,8)] 
            self.data["电柜状态"].jianxuanX4_err        = [get_bool(data,13,0),get_bool(data,13,1),get_bool(data,13,2),get_bool(data,13,3)
                                                      ,get_bool(data,13,4),get_bool(data,13,5),get_bool(data,13,6),get_bool(data,13,7),get_bool(data,13,8)] 
            self.data["电柜状态"].safedoorX1_err       = [get_bool(data,14,0),get_bool(data,14,1),get_bool(data,14,2),get_bool(data,14,3) 
                                                        ,get_bool(data,14,4),get_bool(data,14,5),get_bool(data,14,6),get_bool(data,14,7),get_bool(data,14,8)] 
            self.data["电柜状态"].conveyX2_err          =    [get_bool(data,15,0),get_bool(data,15,1),get_bool(data,15,2),get_bool(data,15,3)] 

            self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_err          =    [get_bool(data,16,0),get_bool(data,16,1),get_bool(data,16,2),get_bool(data,16,3)
                                                        ,get_bool(data,16,4),get_bool(data,16,5),get_bool(data,16,6),get_bool(data,16,7),get_bool(data,16,8)]
            self.data["电柜状态"].q3p_tuopan_X2_err          =    [get_bool(data,17,0),get_bool(data,17,1),get_bool(data,17,2),get_bool(data,17,3)]

            self.data["电柜状态"].conveyX4_err          =    [get_bool(data,18,0),get_bool(data,18,1),get_bool(data,18,2),get_bool(data,18,3)] 


        # elif name =="Q1P拣选/Q3P拣选" or "Q3P托盘X2":
        #     pass
        else:
            
            for i in range(16):
                self.data[name].INPUT0[i]             = get_bool(data,0,i)
                self.data[name].INPUT1[i]             = get_bool(data,1,i)
                self.data[name].INPUT2[i]             = get_bool(data,2,i)
                
                self.data[name].OUTPUT0[i]            = get_bool(data,3,i)
                self.data[name].OUTPUT1[i]            = get_bool(data,4,i)

                self.data[name].IO_STATUS[i]          = get_bool(data,5,i)
                self.data[name].animation_status_1[i] = get_bool(data,6,i)
                self.data[name].animation_status_2[i] = get_bool(data,7,i)
                self.data[name].animation_status_3[i] = get_bool(data,8,i)
                self.data[name].animation_status_4[i] = get_bool(data,9,i)
            self.data[name].animation_status_5 = get_int(data,10)
            self.data[name].animation_status_6 = get_int(data,11)
            self.data[name].animation_status_7 = get_int(data,12)
            self.data[name].animation_status_8 = get_int(data,13)

    def update_items_data(self):
        def get_err_info(errcode:int)->str:
            if int_to_hex(errcode,4)=="8001":
                return "告警信息： 急停触发！"
            elif int_to_hex(errcode,4)=="8002":
                return "告警信息： 光栅触发！"
            elif int_to_hex(errcode,4)=="8003":
                return "告警信息： 门锁信号异常！"
            elif int_to_hex(errcode,4)=="8005":
                return "告警信息： 电柜未连接PLC！"
            elif int_to_hex(errcode,4)=="7001":
                return "告警信息： 急停被按下，无法复位"
            elif int_to_hex(errcode,4)=="7002":
                return "告警信息： 光栅被按下，无法复位"
            elif int_to_hex(errcode,4)=="7003":
                return "告警信息： 门未锁，无法复位"
            elif int_to_hex(errcode,4)=="0000":
                return "告警信息： 未报警"
            else:
                return "告警信息： 未知告警"
        def wcs_cmd_info(cmd:int)->str:
            if   1==cmd:
                return "WCS命令：(1:申请进出站)"
            elif 2==cmd:
                return "WCS命令：(2:申请人工拣选)"
            elif 0==cmd:
                return "WCS命令：(0:初始状态)"
            else:
                return f"WCS命令：({cmd}:未知)"
        # print("更新IO")
        if  self.SceneManager is None:
            return
        if self.Scene.loadDone()==False:
            return
        if self.data_broker.plc_manager.isConnected()==False:
            return
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["主电柜_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].main_is_ok else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#维修区/安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].maintain_safedoor_ok[0] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#维修区/安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].maintain_safedoor_ok[1] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#维修区/安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].maintain_safedoor_ok[2] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#维修区/安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].maintain_safedoor_ok[3] else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#上架X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_ok[0] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#上架X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_ok[1] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#上架X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_ok[2] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#上架X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_ok[3] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["5#上架X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_ok[4] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["6#上架X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_ok[5] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["7#上架X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_ok[6] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["8#上架X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_ok[7] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["9#上架X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_ok[8] else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#拣选X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_ok[0] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#拣选X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_ok[1] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#拣选X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_ok[2] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#拣选X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_ok[3] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["5#拣选X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_ok[4] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["6#拣选X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_ok[5] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["7#拣选X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_ok[6] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["8#拣选X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_ok[7] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["9#拣选X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_ok[8] else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_ok[0] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_ok[1] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_ok[2] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_ok[3] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["5#安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_ok[4] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["6#安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_ok[5] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["7#安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_ok[6] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["8#安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_ok[7] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["9#安全门_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_ok[8] else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#输送线X2_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX2_ok[0] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#输送线X2_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX2_ok[1] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#输送线X2_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX2_ok[2] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#输送线X2_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX2_ok[3] else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#Q1P拣选/Q3P拣选_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_ok[0] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#Q1P拣选/Q3P拣选_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_ok[1] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#Q1P拣选/Q3P拣选_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_ok[2] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#Q1P拣选/Q3P拣选_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_ok[3] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["5#Q1P拣选/Q3P拣选_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_ok[4] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["6#Q1P拣选/Q3P拣选_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_ok[5] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["7#Q1P拣选/Q3P拣选_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_ok[6] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["8#Q1P拣选/Q3P拣选_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_ok[7] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["9#Q1P拣选/Q3P拣选_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_ok[8] else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#Q3P托盘X2_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q3p_tuopan_X2_ok[0] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#Q3P托盘X2_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q3p_tuopan_X2_ok[1] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#Q3P托盘X2_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q3p_tuopan_X2_ok[2] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#Q3P托盘X2_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].q3p_tuopan_X2_ok[3] else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#输送线X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX4_ok[0] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#输送线X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX4_ok[1] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#输送线X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX4_ok[2] else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#输送线X4_OK"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX4_ok[3] else item.set_visibility(False)

        # print("-------------------------------------------------")
        # print(self.current_cabinet_type,self.current_station)
        # print("-------------------------------------------------")
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["主电柜_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].main_is_err and self.shine_flag else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#维修区/安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].maintain_safedoor_err[0] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#维修区/安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].maintain_safedoor_err[1] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#维修区/安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].maintain_safedoor_err[2] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#维修区/安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].maintain_safedoor_err[3] and self.shine_flag else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#上架X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_err[0] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#上架X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_err[1] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#上架X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_err[2] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#上架X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_err[3] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["5#上架X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_err[4] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["6#上架X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_err[5] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["7#上架X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_err[6] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["8#上架X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_err[7] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["9#上架X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].shangjiaX4_err[8] and self.shine_flag else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#拣选X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_err[0] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#拣选X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_err[1] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#拣选X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_err[2] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#拣选X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_err[3] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["5#拣选X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_err[4] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["6#拣选X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_err[5] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["7#拣选X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_err[6] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["8#拣选X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_err[7] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["9#拣选X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].jianxuanX4_err[8] and self.shine_flag else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_err[0] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_err[1] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_err[2] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_err[3] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["5#安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_err[4] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["6#安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_err[5] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["7#安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_err[6] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["8#安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_err[7] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["9#安全门_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].safedoorX1_err[8] and self.shine_flag else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#输送线X2_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX2_err[0] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#输送线X2_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX2_err[1] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#输送线X2_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX2_err[2] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#输送线X2_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX2_err[3] and self.shine_flag else item.set_visibility(False)		

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#Q1P拣选/Q3P拣选_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_err[0] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#Q1P拣选/Q3P拣选_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_err[1] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#Q1P拣选/Q3P拣选_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_err[2] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#Q1P拣选/Q3P拣选_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_err[3] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["5#Q1P拣选/Q3P拣选_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_err[4] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["6#Q1P拣选/Q3P拣选_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_err[5] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["7#Q1P拣选/Q3P拣选_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_err[6] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["8#Q1P拣选/Q3P拣选_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_err[7] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["9#Q1P拣选/Q3P拣选_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q1p_jianxuan_q3p_jianxuan_err[8] and self.shine_flag else item.set_visibility(False)

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#Q3P托盘X2_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q3p_tuopan_X2_err[0] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#Q3P托盘X2_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q3p_tuopan_X2_err[1] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#Q3P托盘X2_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q3p_tuopan_X2_err[2] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#Q3P托盘X2_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].q3p_tuopan_X2_err[3] and self.shine_flag else item.set_visibility(False)		

        item = self.SceneManager.findItem(self.SceneManager.m_name_items["1#输送线X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX4_err[0] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["2#输送线X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX4_err[1] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["3#输送线X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX4_err[2] and self.shine_flag else item.set_visibility(False)
        item = self.SceneManager.findItem(self.SceneManager.m_name_items["4#输送线X4_安全触发"])
        item.set_visibility(True)  if self.data["电柜状态"].conveyX4_err[3] and self.shine_flag else item.set_visibility(False)	

	

        if self.current_cabinet_type != "":
            name = self.current_cabinet_type
            for i in range(8):
                item = self.SceneManager.findItem(self.SceneManager.m_name_items["I0."+str(i) + "_status"])
                item.set_fill_color(TRUE_COLOR)  if self.data[name].INPUT0[i] else item.set_fill_color(FALSE_COLOR)

                item = self.SceneManager.findItem(self.SceneManager.m_name_items["I1."+str(i) + "_status"])
                item.set_fill_color(TRUE_COLOR)  if self.data[name].INPUT0[i+8] else item.set_fill_color(FALSE_COLOR)

                item = self.SceneManager.findItem(self.SceneManager.m_name_items["I2."+str(i) + "_status"])
                item.set_fill_color(TRUE_COLOR)  if self.data[name].INPUT1[i] else item.set_fill_color(FALSE_COLOR)

                item = self.SceneManager.findItem(self.SceneManager.m_name_items["I3."+str(i) + "_status"])
                item.set_fill_color(TRUE_COLOR)  if self.data[name].INPUT1[i+8] else item.set_fill_color(FALSE_COLOR)

                item = self.SceneManager.findItem(self.SceneManager.m_name_items["I4."+str(i) + "_status"])
                item.set_fill_color(TRUE_COLOR)  if self.data[name].INPUT2[i] else item.set_fill_color(FALSE_COLOR)

              
                item = self.SceneManager.findItem(self.SceneManager.m_name_items["Q0."+str(i) + "_status"])
                item.set_fill_color(TRUE_COLOR)  if self.data[name].OUTPUT0[i] else item.set_fill_color(FALSE_COLOR)
                item = self.SceneManager.findItem(self.SceneManager.m_name_items["Q1."+str(i) + "_status"])
                item.set_fill_color(TRUE_COLOR)  if self.data[name].OUTPUT0[i+8] else item.set_fill_color(FALSE_COLOR)
            
            item = self.SceneManager.findItem(self.SceneManager.m_name_items["DI0_status"])
            item.set_fill_color(OK_COLOR)  if self.data[name].IO_STATUS[0] else item.set_fill_color(ERR_COLOR)
            item = self.SceneManager.findItem(self.SceneManager.m_name_items["DI1_status"])
            item.set_fill_color(OK_COLOR)  if self.data[name].IO_STATUS[1] else item.set_fill_color(ERR_COLOR)
            item = self.SceneManager.findItem(self.SceneManager.m_name_items["DI2_status"])
            item.set_fill_color(OK_COLOR)  if self.data[name].IO_STATUS[2] else item.set_fill_color(ERR_COLOR)
            item = self.SceneManager.findItem(self.SceneManager.m_name_items["DI3_status"])
            item.set_fill_color(OK_COLOR)  if self.data[name].IO_STATUS[3] else item.set_fill_color(ERR_COLOR)
            item = self.SceneManager.findItem(self.SceneManager.m_name_items["DI4_status"])
            item.set_fill_color(OK_COLOR)  if self.data[name].IO_STATUS[4] else item.set_fill_color(ERR_COLOR)

            item = self.SceneManager.findItem(self.SceneManager.m_name_items["DO0_status"])
            item.set_fill_color(OK_COLOR)  if self.data[name].IO_STATUS[8] else item.set_fill_color(ERR_COLOR)
            item = self.SceneManager.findItem(self.SceneManager.m_name_items["DO1_status"])
            item.set_fill_color(OK_COLOR)  if self.data[name].IO_STATUS[9] else item.set_fill_color(ERR_COLOR)
        if self.current_cabinet_type =="维修区/安全门": #("主电柜","维修区/安全门","上架X4","拣选X4","安全门X1","输送线X2") or ""
           
            if self.current_station==1:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["维修区_安全门"])
                angle = 0.0 if self.data["维修区/安全门"].animation_status_1[0] else - 90.0
                item.rotate_to_ang(angle)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["维修区_光栅"])
                item.set_visibility(False)  if self.data["维修区/安全门"].animation_status_1[1] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["维修区_三色灯"])
                if   self.data["维修区/安全门"].animation_status_1[2]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["维修区/安全门"].animation_status_1[3]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["维修区/安全门"].animation_status_1[4]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["维修区_errcode"])
                item.context = get_err_info(self.data["维修区/安全门"].animation_status_5)
            elif  self.current_station==2:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["安全门_安全门"])
                angle = 0.0 if self.data["维修区/安全门"].animation_status_2[0] else - 90.0
                item.rotate_to_ang(angle)
               
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["安全门_三色灯"])
                if   self.data["维修区/安全门"].animation_status_2[2]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["维修区/安全门"].animation_status_2[3]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["维修区/安全门"].animation_status_2[4]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["安全门_errcode"])
                item.context = get_err_info(self.data["维修区/安全门"].animation_status_6)

        elif self.current_cabinet_type =="上架X4":
            if self.current_station==1:
        
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电1"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_1[0] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电2"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_1[1] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电3"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_1[2] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电4"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_1[3] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光栅"])
                item.set_visibility(False)  if self.data["上架X4"].animation_status_1[4] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_三色灯"])
                if   self.data["上架X4"].animation_status_1[5]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["上架X4"].animation_status_1[6]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["上架X4"].animation_status_1[7]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_errcode"])
                item.context = get_err_info(self.data["上架X4"].animation_status_5)

            elif self.current_station==2:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电1"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_2[0] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电2"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_2[1] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电3"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_2[2] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电4"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_2[3] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光栅"])
                item.set_visibility(False)  if self.data["上架X4"].animation_status_2[4] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_三色灯"])
                if   self.data["上架X4"].animation_status_2[5]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["上架X4"].animation_status_2[6]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["上架X4"].animation_status_2[7]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_errcode"])
                item.context = get_err_info(self.data["上架X4"].animation_status_6)

            elif self.current_station==3:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电1"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_3[0] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电2"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_3[1] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电3"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_3[2] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电4"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_3[3] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光栅"])
                item.set_visibility(False)  if self.data["上架X4"].animation_status_3[4] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_三色灯"])
                if   self.data["上架X4"].animation_status_3[5]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["上架X4"].animation_status_3[6]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["上架X4"].animation_status_3[7]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_errcode"])
                item.context = get_err_info(self.data["上架X4"].animation_status_7)

            elif self.current_station==4:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电1"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_4[0] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电2"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_4[1] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电3"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_4[2] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光电4"])
                item.set_visibility(True)  if not self.data["上架X4"].animation_status_4[3] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_光栅"])
                item.set_visibility(False)  if self.data["上架X4"].animation_status_4[4] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_三色灯"])
                if   self.data["上架X4"].animation_status_4[5]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["上架X4"].animation_status_4[6]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["上架X4"].animation_status_4[7]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["上架工作站_errcode"])
                item.context = get_err_info(self.data["上架X4"].animation_status_8)
        
        elif self.current_cabinet_type =="拣选X4":
            if self.current_station==1:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光电1"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["拣选X4"].animation_status_1[0] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光电2"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["拣选X4"].animation_status_1[1] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光栅"])
                item.set_visibility(False)  if self.data["拣选X4"].animation_status_1[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_三色灯"])
                if   self.data["拣选X4"].animation_status_1[3]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["拣选X4"].animation_status_1[4]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["拣选X4"].animation_status_1[5]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_errcode"])
                item.context = get_err_info(self.data["拣选X4"].animation_status_5)

            elif self.current_station==2:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光电1"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["拣选X4"].animation_status_2[0] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光电2"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["拣选X4"].animation_status_2[1] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光栅"])
                item.set_visibility(False)  if self.data["拣选X4"].animation_status_2[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_三色灯"])
                if   self.data["拣选X4"].animation_status_2[3]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["拣选X4"].animation_status_2[4]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["拣选X4"].animation_status_2[5]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_errcode"])
                item.context = get_err_info(self.data["拣选X4"].animation_status_6)

            elif self.current_station==3:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光电1"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["拣选X4"].animation_status_3[0] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光电2"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["拣选X4"].animation_status_3[1] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光栅"])
                item.set_visibility(False)  if self.data["拣选X4"].animation_status_3[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_三色灯"])
                if   self.data["拣选X4"].animation_status_3[3]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["拣选X4"].animation_status_3[4]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["拣选X4"].animation_status_3[5]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))

                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_errcode"])
                item.context = get_err_info(self.data["拣选X4"].animation_status_7)

            elif self.current_station==4:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光电1"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["拣选X4"].animation_status_4[0] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光电2"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["拣选X4"].animation_status_4[1] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光栅"])
                item.set_visibility(False)  if self.data["拣选X4"].animation_status_4[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_三色灯"])
                if   self.data["拣选X4"].animation_status_4[3]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["拣选X4"].animation_status_4[4]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["拣选X4"].animation_status_4[5]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
            
            
            
            
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_errcode"])
                item.context = get_err_info(self.data["拣选X4"].animation_status_8)

        elif self.current_cabinet_type =="安全门X1":
            
            item  = self.SceneManager.findItem(self.SceneManager.m_name_items["安全门_安全门"])
            angle = 0.0 if self.data["安全门X1"].animation_status_1[0] else - 90.0
            item.rotate_to_ang(angle)
            
            item  = self.SceneManager.findItem(self.SceneManager.m_name_items["安全门_三色灯"])
            if   self.data["安全门X1"].animation_status_1[2]:
                item.set_fill_color(QColor(255,0,0))
            elif self.data["安全门X1"].animation_status_1[3]:
                item.set_fill_color(QColor(0,255,0))
            elif self.data["安全门X1"].animation_status_1[4]:
                item.set_fill_color(YELLOW_COLOR)
            else:
                item.set_fill_color(QColor(255,255,255))
            
            item  = self.SceneManager.findItem(self.SceneManager.m_name_items["安全门_errcode"])
            item.context = get_err_info(self.data["安全门X1"].animation_status_5)
        
        elif self.current_cabinet_type =="输送线X2":
            if self.current_station==1:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光电1"])
                item.set_visibility(True)  if not self.data["输送线X2"].animation_status_1[0] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光电2"])
                item.set_visibility(True)  if not self.data["输送线X2"].animation_status_1[1] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光栅"])
                item.set_visibility(False)  if self.data["输送线X2"].animation_status_1[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_三色灯"])
                if   self.data["输送线X2"].animation_status_1[3]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["输送线X2"].animation_status_1[4]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["输送线X2"].animation_status_1[5]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_errcode"])
                item.context = get_err_info(self.data["输送线X2"].animation_status_5)

            elif self.current_station==2:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光电1"])
                item.set_visibility(True)  if not self.data["输送线X2"].animation_status_2[0] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光电2"])
                item.set_visibility(True)  if not self.data["输送线X2"].animation_status_2[1] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光栅"])
                item.set_visibility(False)  if self.data["输送线X2"].animation_status_2[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_三色灯"])
                if   self.data["输送线X2"].animation_status_2[3]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["输送线X2"].animation_status_2[4]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["输送线X2"].animation_status_2[5]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_errcode"])
                item.context = get_err_info(self.data["输送线X2"].animation_status_6)
        
        elif self.current_cabinet_type =="Q1P拣选/Q3P拣选": #("主电柜","维修区/安全门","上架X4","拣选X4","安全门X1","输送线X2") or ""
        
            if self.current_station==1:
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光电1"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["Q1P拣选/Q3P拣选"].animation_status_1[0] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光电2"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["Q1P拣选/Q3P拣选"].animation_status_1[1] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_光栅"])
                item.set_visibility(False)  if self.data["Q1P拣选/Q3P拣选"].animation_status_1[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_三色灯"])
                if   self.data["Q1P拣选/Q3P拣选"].animation_status_1[3]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["Q1P拣选/Q3P拣选"].animation_status_1[4]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["Q1P拣选/Q3P拣选"].animation_status_1[5]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["拣选工作站_errcode"])
                item.context = get_err_info(self.data["Q1P拣选/Q3P拣选"].animation_status_5)
               
            elif  self.current_station==2:
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P拣选工作站_光电1"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["Q1P拣选/Q3P拣选"].animation_status_2[0] else item.set_fill_color(FALSE_COLOR)
    
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P拣选工作站_光电2"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["Q1P拣选/Q3P拣选"].animation_status_2[1] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P拣选工作站_光栅1"])
                item.set_visibility(False)  if self.data["Q1P拣选/Q3P拣选"].animation_status_2[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P拣选工作站_光栅2"])
                item.set_visibility(False)  if self.data["Q1P拣选/Q3P拣选"].animation_status_2[3] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P拣选工作站_光栅3"])
                item.set_visibility(False)  if self.data["Q1P拣选/Q3P拣选"].animation_status_2[4] else item.set_visibility(True)

                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P拣选工作站_三色灯"])
                if   self.data["Q1P拣选/Q3P拣选"].animation_status_2[5]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["Q1P拣选/Q3P拣选"].animation_status_2[6]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["Q1P拣选/Q3P拣选"].animation_status_2[7]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))



                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P拣选工作站_errcode"])
                item.context = get_err_info(self.data["Q1P拣选/Q3P拣选"].animation_status_6)

                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P拣选工作站_last_cmd"])
                item.context = wcs_cmd_info(self.data["Q1P拣选/Q3P拣选"].animation_status_8)

        elif self.current_cabinet_type =="Q3P托盘X2":
            
                


            if self.current_station==1:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_光电1"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["Q3P托盘X2"].animation_status_1[0] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_光电2"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["Q3P托盘X2"].animation_status_1[1] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_光栅1"])
                item.set_visibility(False)  if self.data["Q3P托盘X2"].animation_status_1[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_光栅2"])
                item.set_visibility(False)  if self.data["Q3P托盘X2"].animation_status_1[3] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_三色灯"])
                if   self.data["Q3P托盘X2"].animation_status_1[4]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["Q3P托盘X2"].animation_status_1[5]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["Q3P托盘X2"].animation_status_1[6]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))

                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_errcode"])
                item.context = get_err_info(self.data["Q3P托盘X2"].animation_status_5)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_last_cmd"])
                item.context = wcs_cmd_info(self.data["Q3P托盘X2"].animation_status_7)

            elif self.current_station==2:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_光电1"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["Q3P托盘X2"].animation_status_2[0] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_光电2"])
                item.set_fill_color(TRUE_COLOR)  if  self.data["Q3P托盘X2"].animation_status_2[1] else item.set_fill_color(FALSE_COLOR)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_光栅1"])
                item.set_visibility(False)  if self.data["Q3P托盘X2"].animation_status_2[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_光栅2"])
                item.set_visibility(False)  if self.data["Q3P托盘X2"].animation_status_2[3] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_三色灯"])
                if   self.data["Q3P托盘X2"].animation_status_2[4]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["Q3P托盘X2"].animation_status_2[5]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["Q3P托盘X2"].animation_status_2[6]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_errcode"])
                item.context = get_err_info(self.data["Q3P托盘X2"].animation_status_6)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["Q3P托盘工作站_last_cmd"])
                item.context = wcs_cmd_info(self.data["Q3P托盘X2"].animation_status_8)
        
        elif self.current_cabinet_type =="输送线X4":
            if self.current_station==1:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光电1"])
                item.set_visibility(True)  if not self.data["输送线X4"].animation_status_1[0] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光电2"])
                item.set_visibility(True)  if not self.data["输送线X4"].animation_status_1[1] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光栅"])
                item.set_visibility(False)  if self.data["输送线X4"].animation_status_1[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_三色灯"])
                if   self.data["输送线X4"].animation_status_1[3]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["输送线X4"].animation_status_1[4]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["输送线X4"].animation_status_1[5]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_errcode"])
                item.context = get_err_info(self.data["输送线X4"].animation_status_5)

            elif self.current_station==2:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光电1"])
                item.set_visibility(True)  if not self.data["输送线X4"].animation_status_2[0] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光电2"])
                item.set_visibility(True)  if not self.data["输送线X4"].animation_status_2[1] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光栅"])
                item.set_visibility(False)  if self.data["输送线X4"].animation_status_2[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_三色灯"])
                if   self.data["输送线X4"].animation_status_2[3]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["输送线X4"].animation_status_2[4]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["输送线X4"].animation_status_2[5]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_errcode"])
                item.context = get_err_info(self.data["输送线X4"].animation_status_6)
            
            elif self.current_station==3:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光电1"])
                item.set_visibility(True)  if not self.data["输送线X4"].animation_status_3[0] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光电2"])
                item.set_visibility(True)  if not self.data["输送线X4"].animation_status_3[1] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光栅"])
                item.set_visibility(False)  if self.data["输送线X4"].animation_status_3[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_三色灯"])
                if   self.data["输送线X4"].animation_status_3[3]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["输送线X4"].animation_status_3[4]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["输送线X4"].animation_status_3[5]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_errcode"])
                item.context = get_err_info(self.data["输送线X4"].animation_status_7)

            elif self.current_station==4:
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光电1"])
                item.set_visibility(True)  if not self.data["输送线X4"].animation_status_4[0] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光电2"])
                item.set_visibility(True)  if not self.data["输送线X4"].animation_status_4[1] else item.set_visibility(False)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_光栅"])
                item.set_visibility(False)  if self.data["输送线X4"].animation_status_4[2] else item.set_visibility(True)
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_三色灯"])
                if   self.data["输送线X4"].animation_status_4[3]:
                    item.set_fill_color(QColor(255,0,0))
                elif self.data["输送线X4"].animation_status_4[4]:
                    item.set_fill_color(QColor(0,255,0))
                elif self.data["输送线X4"].animation_status_4[5]:
                    item.set_fill_color(YELLOW_COLOR)
                else:
                    item.set_fill_color(QColor(255,255,255))
                
                item  = self.SceneManager.findItem(self.SceneManager.m_name_items["输送线_errcode"])
                item.context = get_err_info(self.data["输送线X4"].animation_status_8)

    def show_safety_internal_ip(self,context:str):
        item  = self.SceneManager.findItem(self.SceneManager.m_name_items["文本_安全系统内部网络"])
        item.context = context

@dataclass
class system_status_data():
    safety_triggered            :bool =None
    enable_fire_signal          :bool =None
    enable_ask_wcs_bf_opendoor  :bool =None
    enable_double_plc           :bool =None
    enable_estop_ext            :bool =None
    disable_buzzer              :bool =None
    configured_count            :int  =None
    online_count                :int  =None
    fault_count                 :int  =None
    agv_configured_count        :int  =None
    agv_offline_count           :int  =None
    agv_err_count               :int  =None
    version_a               :int  =None
    version_b               :int  =None
    version_c               :int  =None

    PLC_A1_IP                   :str  =None
    PLC_A2_IP                   :str  =None
    PLC_A1_MAC                   :str  =None
    PLC_A2_MAC                   :str  =None
    def __post_init__(self):
        self.safety_triggered =False
        self.enable_fire_signal =False
        self.enable_ask_wcs_bf_opendoor =False
        self.enable_double_plc =False
        self.enable_estop_ext =False
        self.disable_buzzer =False
        self.configured_count = 0
        self.online_count = 0
        self.fault_count = 0
        self.agv_configured_count = 0
        self.agv_offline_count = 0
        self.agv_err_count = 0
        self.version_a = 0
        self.version_b = 0
        self.version_c = 0

        self.PLC_A1_IP   = ""
        self.PLC_A2_IP   = ""
        self.PLC_A1_MAC   = ""
        self.PLC_A2_MAC   = ""
    

        
class Ui_safety_display(QWidget):
    safety_internal_info = Signal(str)
    def __init__(self,parent=None,rect_params=None):
        super().__init__(parent)
        self.ui = safety_Ui()
        self.ui.setupUi(self)
        self.data  ={"系统状态":system_status_data()}
        self.data_broker = None
        self.ui.Btn_clear.clicked.connect(self.ui.plainTextEdit.clear)

        self.sys_internal_ip = '安全系统内部网段:192.168.1.x'
        self.safety_internal_info.emit(self.sys_internal_ip)
    def set_data_broker(self,data_broker:DataBroker): 
        self.data_broker = data_broker
        if data_broker is None:
            return
        self.data_broker.sys_status_data_ready.connect(self.handle_data_broker)
        self.data_broker.ip_mac_data_ready.connect(self.handle_data_broker)
        self.data_broker.plc_manager.connected_state_changed.connect(self.handle_connect_state_changed)
        
        
    

    def handle_connect_state_changed(self,state:bool):
        now = time.strftime("%H:%M:%S")
        # dt = datetime.strptime(value, "%Y-%m-%d-%H:%M:%S.%f")
        ip = self.data_broker.plc_manager.get_ip_address()
        if state:
            self.ui.plainTextEdit.appendPlainText(f"{now}    PLC({ip})连接成功")
        else:
            self.ui.plainTextEdit.appendPlainText(f"{now}    PLC({ip})连接断开")
            self.ui.label_safety_triggered.setText("未知")
            self.ui.label_total_carbinet_counts.setText("未知")
            self.ui.label_total_carbinet_online.setText("未知")
            self.ui.label_total_carbinet_err.setText("未知")
            self.ui.label_configured_agv_counts.setText("未知")
            self.ui.label_disconnected_agv_counts.setText("未知")
            self.ui.label_err_agv_counts.setText("未知")



    
    def handle_read_station_config(self,state:bool):
        now = time.strftime("%H:%M:%S")
        if state:
            self.ui.plainTextEdit.appendPlainText(f"{now}    读取站点配置成功")
        else:
            self.ui.plainTextEdit.appendPlainText(f"{now}    读取站点配置失败")

    def handle_write_station_config(self,state:bool):
        now = time.strftime("%H:%M:%S")
        if state:
            self.ui.plainTextEdit.appendPlainText(f"{now}    写入站点配置成功")
        else:
            self.ui.plainTextEdit.appendPlainText(f"{now}    写入站点配置失败")
            
    def handle_data_broker(self, data_packet: tuple):

        
        
        name, data = data_packet
        if name =="系统状态":
            self.data["系统状态"].safety_triggered           = get_bool(data,0,0)
            self.data["系统状态"].enable_fire_signal         = get_bool(data,0,1)
            self.data["系统状态"].enable_ask_wcs_bf_opendoor = get_bool(data,0,2)
            self.data["系统状态"].enable_double_plc          = get_bool(data,0,3)
            self.data["系统状态"].disable_buzzer             = get_bool(data,0,4)
            self.data["系统状态"].enable_estop_ext           = get_bool(data,0,5)

            self.data["系统状态"].configured_count = data[1]
            self.data["系统状态"].online_count     = data[2]
            self.data["系统状态"].fault_count      = data[3]
            self.data["系统状态"].agv_configured_count  = data[4]
            self.data["系统状态"].agv_offline_count     = data[5]
            self.data["系统状态"].agv_err_count         = data[6]

            self.data["系统状态"].version_a = data[7]
            self.data["系统状态"].version_b = data[8]
            self.data["系统状态"].version_c = data[9]

        elif name =="地址状态":
            self.data["系统状态"].PLC_A1_IP  = ".".join(str(x) for x in data[:4])
            self.data["系统状态"].PLC_A2_IP  =str(data[4])+"." +str(data[5])+"." +str(data[6])+"." +str(data[7]) 
            self.sys_internal_ip = "安全系统内部网段:" + ".".join(str(x) for x in data[:3]) + ".X"
            self.safety_internal_info.emit(self.sys_internal_ip)
            
            # self.data["系统状态"].PLC_A1_MAC = int_to_hex(data[8],2) +int_to_hex(data[9],2) +int_to_hex(data[10],2) +int_to_hex(data[11],2) +int_to_hex(data[12],2) +int_to_hex(data[13],2) 
            self.data["系统状态"].PLC_A1_MAC =""
            self.data["系统状态"].PLC_A2_MAC =""
            for i in range(6):
                self.data["系统状态"].PLC_A1_MAC += int_to_hex(data[8+i],2)
                if i==5:
                    break
                self.data["系统状态"].PLC_A1_MAC +='-'
           
            for i in range(6):
                self.data["系统状态"].PLC_A2_MAC += int_to_hex(data[14+i],2)
                if i==5:
                    break
                self.data["系统状态"].PLC_A2_MAC +='-'
          

        self.ui.label_safety_triggered.setText("安全触发") if self.data["系统状态"].safety_triggered else self.ui.label_safety_triggered.setText("信号正常")
        self.ui.label_safety_triggered.setStyleSheet("color: red;") if self.data["系统状态"].safety_triggered else self.ui.label_safety_triggered.setStyleSheet("color: green;")

        self.ui.checkBox_is_fireSignal_enable.setChecked(True if self.data["系统状态"].enable_fire_signal else False) 
        self.ui.checkBox_need_ask_open_door.setChecked(  True if self.data["系统状态"].enable_ask_wcs_bf_opendoor  else False) 
        self.ui.checkBox_is_double_plc.setChecked(       True if self.data["系统状态"].enable_double_plc  else False) 
        self.ui.checkBox_is_disable_buzzer.setChecked(       True if self.data["系统状态"].disable_buzzer  else False) 
        self.ui.checkBox_is_enable_estop_ext.setChecked(       True if self.data["系统状态"].enable_estop_ext  else False) 


        self.ui.label_total_carbinet_counts.setText(str(self.data["系统状态"].configured_count))
        self.ui.label_total_carbinet_online.setText(str(self.data["系统状态"].online_count))
        self.ui.label_total_carbinet_err.setText(str(self.data["系统状态"].fault_count))

        self.ui.label_configured_agv_counts.setText(str(self.data["系统状态"].agv_configured_count))
        self.ui.label_disconnected_agv_counts.setText(str(self.data["系统状态"].agv_offline_count))
        self.ui.label_err_agv_counts.setText(str(self.data["系统状态"].agv_err_count))


        self.ui.label_A1_ip.setText(self.data["系统状态"].PLC_A1_IP)
        self.ui.label_A2_ip.setText(self.data["系统状态"].PLC_A2_IP)
        self.ui.label_A1_MAC.setText(self.data["系统状态"].PLC_A1_MAC)
        self.ui.label_A2_MAC.setText(self.data["系统状态"].PLC_A2_MAC)


