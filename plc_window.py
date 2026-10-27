
from PySide6.QtWidgets import (QWidget, QLabel,QHBoxLayout,QSpinBox,QComboBox,QPushButton,QToolButton,QCheckBox,QVBoxLayout,QTabWidget,QFrame,QListWidget,QFrame
,QLineEdit,QSizePolicy,QMessageBox,QGroupBox,QDialogButtonBox)
from PySide6.QtCore import Qt,Signal,QTimer,QRect
from PySide6.QtGui import QPalette,QColor,QPaintEvent,QPen,QPainter,QBrush
from load_ui import LoadWidget,LoadDialog
from resource_manager import resource_manager as res_mng
from plc_manager import PLCManager
from snap7.util import *
from data_broker import DataBroker
from typing import List
# from common import NameValLabel
from functools import partial

from myDesigner import RackStoreWindow,RackStoresWindow

from global_config import global_cfg

from flip_clock import FlipDigit_Time_display



SELECTED_COLOR =QColor(0,0,0)
UN_SELECTED_COLOR =QColor(255,255,255)

A = 0
B = 1

class HostRackStatus(QToolButton):

    def __init__(self, parent = None):
        super().__init__(parent)
        self._need_draw_rect = False
    
    def paintEvent(self, event:QPaintEvent):

        if self._need_draw_rect:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            rect = self.rect().adjusted(2, 2, -2, -2)
            pen = QPen()
            pen.setWidth(3)
            pen.setColor(QColor(0, 120, 215))  # 按下时为蓝色
            painter.setPen(pen)
            # painter.setBrush()
            painter.drawRect(rect)

        return super().paintEvent(event)
    



class ConfigWindow(LoadWidget):

    name_update = Signal(str)
    host_selected_change =Signal(int)
    update_rcd_window = Signal()

    class HmiConfig(LoadDialog):
        def __init__(self,plc_mgr:PLCManager,host_start_No=1,host_count=1, parent=None):
            datas = plc_mgr.read_data(21,124,20, priority=True)
            if datas is None:
                self.close()
                return
            self.plc_mgr =plc_mgr

            ui_file_path = res_mng.get_ui_path('hmi_config.ui')
            qss_file     = res_mng.get_ui_path('rcd.qss')
            super().__init__(ui_file_path,qss_file)
            self.resize(300, 400)
            self.setWindowTitle("触摸屏配置")

            self.comboBox_HMIs:List[QComboBox] = (self.ui.comboBox_HMI_1_A,self.ui.comboBox_HMI_1_B,
                                                  self.ui.comboBox_HMI_2_A,self.ui.comboBox_HMI_2_B,
                                                  self.ui.comboBox_HMI_3_A,self.ui.comboBox_HMI_3_B,
                                                  self.ui.comboBox_HMI_4_A,self.ui.comboBox_HMI_4_B,
                                                  self.ui.comboBox_HMI_5_A,self.ui.comboBox_HMI_5_B
                                                  )
            
            items = []
            for i in range(host_count):
                items.append(f'关联主机{i+host_start_No}')

            for comboBox_HMI in self.comboBox_HMIs:
                comboBox_HMI.addItems(items)
            HMIs  = []   
            for i in range(10):
                HMIs.append( get_int(datas,i*2))

            for comboBox_HMI,HMI in zip(self.comboBox_HMIs,HMIs):
                if HMI < host_count+1:
                    comboBox_HMI.setCurrentIndex(HMI)
                else:
                    comboBox_HMI.setCurrentIndex(0)

            buttonBox:QDialogButtonBox = self.ui.buttonBox
            buttonBox.accepted.connect(self.write_paras)

        def write_paras(self):

            datas = bytearray([0]*10)
            for i,comboBox_HMI in enumerate(self.comboBox_HMIs):
                set_int(datas,i*2,comboBox_HMI.currentIndex()) 
            self.plc_mgr.write_data(21,124,datas, priority=True)





    def __init__(self,plc_mgr:PLCManager,data_broker:DataBroker,SerialNumber:str, parent=None):

        ui_file_path = res_mng.get_ui_path('rack_config_v2.ui')
        qss_file     = res_mng.get_ui_path('rcd.qss')
        super().__init__(ui_file_path,qss_file)
        ui:QWidget =self.ui
        ui.setMaximumWidth(800)

        self.ui.label_SerialNumber.setText(SerialNumber)
        
        time_frame :QFrame = self.ui.frame_time
        time_frame_layout =QVBoxLayout()
        self.flip_time = FlipDigit_Time_display(self,size_factor=0.5)
        time_frame_layout.addWidget(self.flip_time)
        time_frame.setLayout(time_frame_layout)


        scene_frame :QFrame = self.ui.frame_scene
        scene_frame_layout =QVBoxLayout()
        self.rack_stores = RackStoresWindow()

        self.rack_stores.slot_clicked.connect(self.on_slot_clicked)
        scene_frame_layout.addWidget(self.rack_stores)
        scene_frame.setLayout(scene_frame_layout)

        self.plc_mgr = plc_mgr
        self.plc_mgr.connect()
        # self.data_broker = DataBroker(plc_mgr)
        self.data_broker =data_broker
        plc_mgr.start_heartbeat()
        self.data_broker.data_ready.connect(self.handle_data_broker)

        # PLC 未连接时 read_data 返回 None，这里必须兜底，否则启动就崩溃；
        # 真正的数据到达后由 handle_data_broker 刷新这些标签。
        datas = plc_mgr.read_data(21,0,60, priority=True)
        if datas is None:
            datas = bytearray(60)

        def _safe_string(buf, offset):
            try:
                return get_string(buf, offset)
            except (TypeError, IndexError, UnicodeDecodeError):
                return ""

        plc_name  = _safe_string(datas, 2)
        check_sum = _safe_string(datas, 24)
        self.soft_major_ver = get_usint(datas,46)
        version = str(get_usint(datas,46)) + '.'+ str(get_usint(datas,47)) +'.'+str(get_usint(datas,48))
        run_elapse_time = get_dint(datas,50)
        self.cpu_led_rn = get_int(datas,54)
        self.cpu_led_er = get_int(datas,56)
        self.cpu_led_mt = get_int(datas,58)
        label_name :QLabel = self.ui.label_name
        label_version :QLabel = self.ui.label_version
        label_checksum :QLabel = self.ui.label_checksum
        self.label_runtime :QLabel = self.ui.label_runtime
        btn_led :QPushButton = self.ui.pushButton_LED
        btn_led.pressed.connect(lambda:self.handle_btn_led(1))
        btn_led.released.connect(lambda:self.handle_btn_led(0))
        # btn_stop :QPushButton = self.ui.pushButton_stop
        # btn_start :QPushButton = self.ui.pushButton_start
        spinBox_host_No_start :QSpinBox = self.ui.spinBox_host_No_start
        spinBox_host_No_start.valueChanged.connect(self.handle_host_No_start_change)

        comboBox_host_type:QComboBox =  self.ui.comboBox_host_type
        comboBox_host_type.currentIndexChanged.connect(self.handle_host_type_change)
        # btn_stop.clicked.connect(lambda:self.plc_mgr.stop_plc())
        # btn_start.clicked.connect(lambda:self.plc_mgr.start_plc())
        self.ui.pushButton_read.clicked.connect(self.read_paras)
        self.ui.pushButton_write.clicked.connect(self.write_paras)

        self.ui.pushButton_rst.pressed.connect( lambda:self.on_reset_click(1))
        self.ui.pushButton_rst.released.connect(lambda:self.on_reset_click(0))

        self.host_start_No = 0
        self.host_count = 0

        self.ui.pushButton_hmi_config.clicked.connect(lambda : self.open_hmi_config_window(self.host_start_No,self.host_count))

        # label_name :QLabel = self.ui.label_name
        label_name.setText(plc_name)
        label_checksum.setText(check_sum)
        label_version.setText(version)
        self.label_runtime.setText(str(run_elapse_time))

        QTimer.singleShot(500,self.read_paras)
        # self.read_paras()

        

        self.btn_RN:QToolButton = self.ui.toolButton_LED_RN
        self.btn_ER:QToolButton = self.ui.toolButton_LED_ER
        self.btn_MT:QToolButton = self.ui.toolButton_LED_MT

        palette = self.btn_RN.palette()
        self.default_color = palette.color(QPalette.ColorRole.Button)

    
        # 必须启用自动填充背景
        # self.btn_RN.setAutoFillBackground(True)
        # self.btn_ER.setAutoFillBackground(True)
        # self.btn_MT.setAutoFillBackground(True)
        
        self.enable_test_mode:QCheckBox = self.ui.checkBox_IO_test
        self.enable_test_mode.clicked.connect(self.on_enable_test_mode_click)

        btn_write:QPushButton = self.ui.pushButton_write

        if global_cfg.is_logged_in and global_cfg._user_name == 'admin':
            btn_write.setEnabled(True)
            # self.enable_test_mode.setEnabled(True)
        else:
            btn_write.setEnabled(False)
            # self.enable_test_mode.setEnabled(False)
        self.handle_login_out()

        self.host_racks_arragement:List[QComboBox] = [
            self.ui.comboBox_arrangement1,self.ui.comboBox_arrangement2,self.ui.comboBox_arrangement3,self.ui.comboBox_arrangement4,self.ui.comboBox_arrangement5,
            self.ui.comboBox_arrangement6,self.ui.comboBox_arrangement7,self.ui.comboBox_arrangement8,self.ui.comboBox_arrangement9,self.ui.comboBox_arrangement10
        ]

        self.rack_status:List[List[QToolButton]]=[
        [self.ui.toolButton_host1_rack1 ,self.ui.toolButton_host1_rack2,self.ui.toolButton_host1_rack3,self.ui.toolButton_host1_rack4,
         self.ui.toolButton_host1_rack5 ,self.ui.toolButton_host1_rack6,self.ui.toolButton_host1_rack7,self.ui.toolButton_host1_rack8],
        [self.ui.toolButton_host2_rack1 ,self.ui.toolButton_host2_rack2,self.ui.toolButton_host2_rack3,self.ui.toolButton_host2_rack4,
         self.ui.toolButton_host2_rack5 ,self.ui.toolButton_host2_rack6,self.ui.toolButton_host2_rack7,self.ui.toolButton_host2_rack8],
        [self.ui.toolButton_host3_rack1 ,self.ui.toolButton_host3_rack2,self.ui.toolButton_host3_rack3,self.ui.toolButton_host3_rack4,
         self.ui.toolButton_host3_rack5 ,self.ui.toolButton_host3_rack6,self.ui.toolButton_host3_rack7,self.ui.toolButton_host3_rack8],
        [self.ui.toolButton_host4_rack1 ,self.ui.toolButton_host4_rack2,self.ui.toolButton_host4_rack3,self.ui.toolButton_host4_rack4,
         self.ui.toolButton_host4_rack5 ,self.ui.toolButton_host4_rack6,self.ui.toolButton_host4_rack7,self.ui.toolButton_host4_rack8],
        [self.ui.toolButton_host5_rack1 ,self.ui.toolButton_host5_rack2,self.ui.toolButton_host5_rack3,self.ui.toolButton_host5_rack4,
         self.ui.toolButton_host5_rack5 ,self.ui.toolButton_host5_rack6,self.ui.toolButton_host5_rack7,self.ui.toolButton_host5_rack8],
        [self.ui.toolButton_host6_rack1 ,self.ui.toolButton_host6_rack2,self.ui.toolButton_host6_rack3,self.ui.toolButton_host6_rack4,
         self.ui.toolButton_host6_rack5 ,self.ui.toolButton_host6_rack6,self.ui.toolButton_host6_rack7,self.ui.toolButton_host6_rack8],
        [self.ui.toolButton_host7_rack1 ,self.ui.toolButton_host7_rack2,self.ui.toolButton_host7_rack3,self.ui.toolButton_host7_rack4,
         self.ui.toolButton_host7_rack5 ,self.ui.toolButton_host7_rack6,self.ui.toolButton_host7_rack7,self.ui.toolButton_host7_rack8],
        [self.ui.toolButton_host8_rack1 ,self.ui.toolButton_host8_rack2,self.ui.toolButton_host8_rack3,self.ui.toolButton_host8_rack4,
         self.ui.toolButton_host8_rack5 ,self.ui.toolButton_host8_rack6,self.ui.toolButton_host8_rack7,self.ui.toolButton_host8_rack8],
        [self.ui.toolButton_host9_rack1 ,self.ui.toolButton_host9_rack2,self.ui.toolButton_host9_rack3,self.ui.toolButton_host9_rack4,
         self.ui.toolButton_host9_rack5 ,self.ui.toolButton_host9_rack6,self.ui.toolButton_host9_rack7,self.ui.toolButton_host9_rack8],
        [self.ui.toolButton_host10_rack1,self.ui.toolButton_host10_rack2,self.ui.toolButton_host10_rack3,self.ui.toolButton_host10_rack4,
         self.ui.toolButton_host10_rack5,self.ui.toolButton_host10_rack6,self.ui.toolButton_host10_rack7,self.ui.toolButton_host10_rack8]
        
        ]
        # 当前选中的主机/料架下标。必须在任何可能失败的 PLC 读取之前赋初值：
        # 否则 PLC 断线时构造函数中途 return，_on_toolButton_hostX_rackX_click
        # 会报 "'ConfigWindow' object has no attribute 'row_last'"。
        self.row_last = 0
        self.col_last = 0

        data = plc_mgr.read_data(22,2,1, priority=True)
        # 读不到就按 (0,0) 处理，不能 return——后面还有按钮信号连接等初始化
        selected = get_usint(data, 0) if data else 0
        if not 0 <= selected < len(self.rack_status) * len(self.rack_status[0]):
            selected = 0

        row, col = selected // 10, selected % 10
        self.row_last = row
        self.col_last = col
        for i in range(10):
            for j in range(8):

                self.rack_status[i][j].setEnabled(True)
                if row ==i and col == j:
                    self.set_rack_status_text_color(self.rack_status[i][j],SELECTED_COLOR)
                else:
                    self.set_rack_status_text_color(self.rack_status[i][j],UN_SELECTED_COLOR)
                
                # 用 partial 绑死 (i, j) 后连接，避免闭包拿到循环结束后的值
                self.rack_status[i][j].clicked.connect(
                    partial(self._on_toolButton_hostX_rackX_click, i, j)
                )
        self.rack_io_moudle_status:List[List[QToolButton]]=[
            [self.ui.toolButton_1a ,self.ui.toolButton_1b ],
            [self.ui.toolButton_2a ,self.ui.toolButton_2b ],
            [self.ui.toolButton_3a ,self.ui.toolButton_3b ],
            [self.ui.toolButton_4a ,self.ui.toolButton_4b ],
            [self.ui.toolButton_5a ,self.ui.toolButton_5b ],
            [self.ui.toolButton_6a ,self.ui.toolButton_6b ],
            [self.ui.toolButton_7a ,self.ui.toolButton_7b ],
            [self.ui.toolButton_8a ,self.ui.toolButton_8b ],
            [self.ui.toolButton_9a ,self.ui.toolButton_9b ],
            [self.ui.toolButton_10a ,self.ui.toolButton_10b ]
        ]
        for tool_btns in self.rack_io_moudle_status:
            for tool_btn in tool_btns:
                tool_btn.setFixedWidth(34)


        self.racks_store_label:List[QLabel]=[self.ui.label_host1_racks ,self.ui.label_host2_racks ,self.ui.label_host3_racks ,self.ui.label_host4_racks ,self.ui.label_host5_racks ,
                                             self.ui.label_host6_racks ,self.ui.label_host7_racks ,self.ui.label_host8_racks ,self.ui.label_host9_racks ,self.ui.label_host10_racks ]
        self.read_config_actual()

        self.rack_io:List[List[QToolButton]]=[

            [self.ui.toolButton_A_IO_0 ,self.ui.toolButton_A_IO_1 ,self.ui.toolButton_A_IO_2 ,self.ui.toolButton_A_IO_3,
             self.ui.toolButton_A_IO_4 ,self.ui.toolButton_A_IO_5 ,self.ui.toolButton_A_IO_6 ,self.ui.toolButton_A_IO_7,
             self.ui.toolButton_A_IO_8 ,self.ui.toolButton_A_IO_9 ,self.ui.toolButton_A_IO_10 ,self.ui.toolButton_A_IO_11,
             self.ui.toolButton_A_IO_12 ,self.ui.toolButton_A_IO_13 ,self.ui.toolButton_A_IO_14 ,self.ui.toolButton_A_IO_15],

             [self.ui.toolButton_B_IO_0  ,self.ui.toolButton_B_IO_1  ,self.ui.toolButton_B_IO_2  ,self.ui.toolButton_B_IO_3,
              self.ui.toolButton_B_IO_4  ,self.ui.toolButton_B_IO_5  ,self.ui.toolButton_B_IO_6  ,self.ui.toolButton_B_IO_7,
              self.ui.toolButton_B_IO_8  ,self.ui.toolButton_B_IO_9  ,self.ui.toolButton_B_IO_10 ,self.ui.toolButton_B_IO_11,
              self.ui.toolButton_B_IO_12 ,self.ui.toolButton_B_IO_13 ,self.ui.toolButton_B_IO_14 ,self.ui.toolButton_B_IO_15]

        ]
        self.rack_io[A][11].pressed.connect(lambda:self.on_led_blue_click(1))
        self.rack_io[A][11].released.connect(lambda:self.on_led_blue_click(0))

        self.rack_io[A][10].pressed.connect(lambda:self.on_led_red_click(1))
        self.rack_io[A][10].released.connect(lambda:self.on_led_red_click(0))

        self.rack_io[A][12].pressed.connect(lambda:self.on_led_grn_click(1))
        self.rack_io[A][12].released.connect(lambda:self.on_led_grn_click(0))

        self.rack_io[A][14].pressed.connect(lambda:self.on_led_rst_click(1))
        self.rack_io[A][14].released.connect(lambda:self.on_led_rst_click(0))

        self.rack_io[B][12].pressed.connect(lambda:self.on_back_cylinder_coil_ext_click(1))
        self.rack_io[B][12].released.connect(lambda:self.on_back_cylinder_coil_ext_click(0))

        self.rack_io[B][13].pressed.connect(lambda:self.on_back_cylinder_coil_ret_click(1))
        self.rack_io[B][13].released.connect(lambda:self.on_back_cylinder_coil_ret_click(0))

        self.rack_io[B][10].pressed.connect(lambda:self.on_side_cylinder_coil_ext_click(1))
        self.rack_io[B][10].released.connect(lambda:self.on_side_cylinder_coil_ext_click(0))

        self.rack_io[B][11].pressed.connect(lambda:self.on_side_cylinder_coil_ret_click(1))
        self.rack_io[B][11].released.connect(lambda:self.on_side_cylinder_coil_ret_click(0))



        datas = plc_mgr.read_data(31,0,640, priority=True)
        if datas is None:
            datas = bytearray(640)

        for i in range(10):
            for j in range(8):
                try:
                    text = get_string(datas, i * 64 + j * 8)
                except (TypeError, IndexError, UnicodeDecodeError):
                    text = ""
                self.rack_stores.set_slot_number(i+1, j+1, text)


        self.data_broker.start_data_polling()

    def open_hmi_config_window(self,host_start_No,host_count):
        print(host_start_No,host_count)
        top_window=self.HmiConfig(self.plc_mgr,host_start_No,host_count)
        top_window.exec()
    
    def handle_login_out(self):
        groupBox :QGroupBox = self.ui.groupBox_rack_paras
        if global_cfg.is_logged_in :
            groupBox.setVisible(True)
        else:
            groupBox.setVisible(False)

        groupBox :QGroupBox = self.ui.groupBox_rack_status
        if global_cfg.is_logged_in :
            groupBox.setVisible(True)
        else:
            groupBox.setVisible(False)

    def on_led_blue_click(self,en):
        datas = bytearray([en])
        self.plc_mgr.write_data(22,6,datas, priority=True)

    def on_led_red_click(self,en):
        datas = bytearray([en])
        self.plc_mgr.write_data(22,5,datas, priority=True)
    
    def on_led_grn_click(self,en):
        datas = bytearray([en])
        self.plc_mgr.write_data(22,4,datas, priority=True)
    
    def on_led_rst_click(self,en):
        datas = bytearray([en])
        self.plc_mgr.write_data(22,7,datas, priority=True) 

    def on_back_cylinder_coil_ext_click(self,en):
        datas = bytearray([en])
        self.plc_mgr.write_data(22,8,datas, priority=True)
    
    def on_back_cylinder_coil_ret_click(self,en):
        datas = bytearray([en])
        self.plc_mgr.write_data(22,9,datas, priority=True)
    
    def on_side_cylinder_coil_ext_click(self,en):
        datas = bytearray([en])
        self.plc_mgr.write_data(22,10,datas, priority=True)
    
    def on_side_cylinder_coil_ret_click(self,en):
        datas = bytearray([en])
        self.plc_mgr.write_data(22,11,datas, priority=True)
    
    def on_reset_click(self,en):
        datas = bytearray([en])
        self.plc_mgr.write_data(22,12,datas, priority=True)

        if  en:
            QTimer.singleShot(3000,self.update_rcd_window.emit)

    def on_enable_test_mode_click(self):
       
             
        if self.enable_test_mode.isChecked():
            datas = bytearray([1])
           
            if not self.plc_mgr.write_data(22,0,datas, priority=True):
                self.enable_test_mode.setChecked(False)
        else:
            datas = bytearray([0])
           
            if not self.plc_mgr.write_data(22,0,datas, priority=True):
                self.enable_test_mode.setChecked(True)


    def on_slot_clicked(self,rack_no:int,slot_no:int):
        '''设置料架仓位的显示颜色'''
        self._on_toolButton_hostX_rackX_click(rack_no-1,slot_no-1)

    def _on_toolButton_hostX_rackX_click(self,row:int,col:int):
        '''设置料架仓位的显示颜色

        row/col 可能来自 on_slot_clicked 的 rack_no-1 / slot_no-1，
        越界时直接忽略，避免索引 self.rack_status 抛 IndexError。
        '''
        if not 0 <= row < len(self.rack_status):
            return
        if not 0 <= col < len(self.rack_status[row]):
            return

        # 兜底：正常构造流程会初始化，这里再保证一次，防止 PLC 断线等异常路径
        if getattr(self, "row_last", None) is None:
            self.row_last = 0
        if getattr(self, "col_last", None) is None:
            self.col_last = 0

        value = row * 10 + col

        datas = bytearray([0])
        set_sint(datas,0 , value)
        if self.plc_mgr.write_data(22,2,datas, priority=True):

            # row_last/col_last 也可能因外部数据变化而越界，统一走安全访问
            self._set_rack_status_color_safe(self.row_last, self.col_last, UN_SELECTED_COLOR)
            self.set_rack_status_text_color(self.rack_status[row][col],SELECTED_COLOR)
            if row!= self.row_last or col!=self.col_last:
                self.host_selected_change.emit(row+1)
                print(f'选中主机号{row+1}')
            self.row_last,self.col_last =row,col

    def _set_rack_status_color_safe(self, row: int, col: int, color) -> None:
        '''按 (row, col) 设置料架按钮文字颜色，下标越界时静默忽略'''
        if not 0 <= row < len(self.rack_status):
            return
        if not 0 <= col < len(self.rack_status[row]):
            return
        self.set_rack_status_text_color(self.rack_status[row][col], color)

    
    def read_config_actual(self):
        datas = self.plc_mgr.read_data(7,0,68, priority=True)
        if datas is None:
            return
        
        host_type = get_int(datas,0)
        host_start_No = get_int(datas,2)

        host_count = get_int(datas,4) 
        host1_racks_count = get_int(datas, 6 ) 
        host2_racks_count = get_int(datas, 8 ) 
        host3_racks_count = get_int(datas, 10) 
        host4_racks_count = get_int(datas, 12) 
        host5_racks_count = get_int(datas, 14) 
        host6_racks_count = get_int(datas, 16) 
        host7_racks_count = get_int(datas, 18) 
        host8_racks_count = get_int(datas, 20) 
        host9_racks_count = get_int(datas, 22) 
        host10_racks_count = get_int(datas,24) 
        racks_counts = [host1_racks_count,host2_racks_count,host3_racks_count,host4_racks_count,host5_racks_count,host6_racks_count,host7_racks_count,host8_racks_count,host9_racks_count,host10_racks_count]
        rack_arrangements =[get_int(datas, 26),get_int(datas, 28),get_int(datas, 30),get_int(datas, 32),get_int(datas, 34),get_int(datas, 36),get_int(datas, 38),get_int(datas, 40),get_int(datas, 42),get_int(datas, 44)]

        hmi_config = {
                        "HMI_1":(get_int(datas, 48),get_int(datas, 50)),
                        "HMI_2":(get_int(datas, 52),get_int(datas, 54)),
                        "HMI_3":(get_int(datas, 56),get_int(datas, 58)),
                        "HMI_4":(get_int(datas, 60),get_int(datas, 62)),
                        "HMI_5":(get_int(datas, 64),get_int(datas, 66))
                      }
      
        self.handle_rack_status(host_type,host_start_No,host_count,racks_counts)

        self.rack_stores.handle_rack_status(host_type,host_start_No,host_count,racks_counts,rack_arrangements,hmi_config)


    def handle_rack_status(self,host_type,host_start_No,host_count:int,rack_counts:List[int]):
        type_map =('未配置','阴极冷压','阳极冷压','阴极模切','阳极模切','阴极预分切','阳极预分切','阴极冷压3+3','阳极冷压3+3')
        for i in range(10):
            for j in range(8):
                if i<=host_count-1 and j<rack_counts[i]:
                    self.rack_status[i][j].setVisible(True)                    
                else:
                    self.rack_status[i][j].setVisible(False)
                    

            if i<=host_count-1:
                self.racks_store_label[i].setVisible(True)
                context = type_map[host_type] + str(host_start_No+i) +'料架联排' 
                if host_start_No+i<10:
                    context = context+'  '
                    
                self.racks_store_label[i].setText(context)
            else:
                self.racks_store_label[i].setVisible(False)
            
            if i<= host_count-1:
                self.rack_io_moudle_status[i][0].setVisible(True)

                self.rack_io_moudle_status[i][1].setVisible(True)
                if rack_counts[i]>4:
                    # self.rack_io_moudle_status[i][1].setVisible(True)
                    pass
                else:
                    # self.rack_io_moudle_status[i][1].setVisible(False)
                    self.rack_io_moudle_status[i][1].setText("   ")
            else:
                self.rack_io_moudle_status[i][0].setVisible(False)
                self.rack_io_moudle_status[i][1].setVisible(False)

            
            

    def handle_btn_led(self,en):
        datas = bytearray([0])
        set_sint(datas,0 , en) 
        self.plc_mgr.write_data(22,1,datas, priority=True)

    def handle_host_No_start_change(self,No):
       
        label_host_1_name:QLabel = self.ui.label_host_1_name
        label_host_2_name:QLabel = self.ui.label_host_2_name
        label_host_3_name:QLabel = self.ui.label_host_3_name
        label_host_4_name:QLabel = self.ui.label_host_4_name
        label_host_5_name:QLabel = self.ui.label_host_5_name
        label_host_6_name:QLabel = self.ui.label_host_6_name
        label_host_7_name:QLabel = self.ui.label_host_7_name
        label_host_8_name:QLabel = self.ui.label_host_8_name
        label_host_9_name:QLabel = self.ui.label_host_9_name
        label_host_10_name:QLabel = self.ui.label_host_10_name
        label_host_1_name.setText('主机'+ str(No)    +'料架仓位数量')
        label_host_2_name.setText('主机'+ str(No+1)  +'料架仓位数量')
        label_host_3_name.setText('主机'+ str(No+2)  +'料架仓位数量')
        label_host_4_name.setText('主机'+ str(No+3)  +'料架仓位数量')
        label_host_5_name.setText('主机'+ str(No+4)  +'料架仓位数量')
        label_host_6_name.setText('主机'+ str(No+5)  +'料架仓位数量')
        label_host_7_name.setText('主机'+ str(No+6)  +'料架仓位数量')
        label_host_8_name.setText('主机'+ str(No+7)  +'料架仓位数量')
        label_host_9_name.setText('主机'+ str(No+8)  +'料架仓位数量')
        label_host_10_name.setText('主机'+ str(No+9) +'料架仓位数量')

    def handle_host_type_change(self,index):

        spinBox_host_No_start :QSpinBox = self.ui.spinBox_host_No_start
        if   index ==1 or index ==2:#冷压
            spinBox_host_No_start.setRange(1,50)
        elif index ==3  or index ==4:
            # spinBox_host_No_start.setRange(1,40)
            spinBox_host_No_start.setRange(1,50)
        elif index ==5  or index ==6:
            spinBox_host_No_start.setRange(1,50)
        elif index ==7  or index ==8:
            spinBox_host_No_start.setRange(1,50)

            


    def set_btn_color(self,btn:QToolButton,color1,color2,cmd,en):
        palette = btn.palette()
        if not en:
            palette.setColor(QPalette.ColorRole.Button, self.default_color)
            btn.setPalette(palette)
        else:
            if cmd == 2:
                palette.setColor(QPalette.ColorRole.Button, color1)
                btn.setPalette(palette)
            elif cmd == 3:
                palette.setColor(QPalette.ColorRole.Button, color2)
                btn.setPalette(palette)
            elif cmd == 4:
                if en:
                    palette.setColor(QPalette.ColorRole.Button, color1)
                else:
                    palette.setColor(QPalette.ColorRole.Button, self.default_color)
                btn.setPalette(palette)
            elif cmd == 5:
                if en:
                    palette.setColor(QPalette.ColorRole.Button, color2)
                else:
                    palette.setColor(QPalette.ColorRole.Button, self.default_color)
                btn.setPalette(palette)
            elif cmd == 6:
                if en:
                    palette.setColor(QPalette.ColorRole.Button, color1)
                else:
                    palette.setColor(QPalette.ColorRole.Button, color2)
                btn.setPalette(palette)


    
    def handle_data_broker(self,name_datas):
        key,datas =name_datas
        if key == 'db21':
            run_elapse_time = get_dint(datas,0)
            cpu_led_rn = get_int(datas,4)
            cpu_led_er = get_int(datas,6)
            cpu_led_mt = get_int(datas,8)
            cpu_led_rn_en = get_int(datas,10)
            cpu_led_er_en = get_int(datas,12)
            cpu_led_mt_en = get_int(datas,14)
   
            # PLC 时间字符串可能还没初始化或数据异常（get_string 会抛 TypeError），
            # 读失败时传 None，由翻页时钟自行保持当前显示。
            try:
                plc_time_str = get_string(datas,16)
            except (TypeError, IndexError, UnicodeDecodeError):
                plc_time_str = None

            self.set_btn_color( self.btn_RN,QColor(0,255,0),QColor(255,255,0),cpu_led_rn,cpu_led_rn_en)
            self.set_btn_color( self.btn_ER,QColor(255,0,0),QColor(255,255,0),cpu_led_er,cpu_led_er_en)
            self.set_btn_color( self.btn_MT,QColor(255,0,0),QColor(255,255,0),cpu_led_mt,cpu_led_mt_en)

            self.label_runtime.setText(str(run_elapse_time))

            self.flip_time.update_time_by_plc(plc_time_str)
        elif key == 'db12':
            # print(datas)
            err_bytes = []
            run_bytes = []
            io_modlue_status_bytes =[]
            io_status_words = [get_word(datas,30),get_word(datas,32)]
            err_tip = get_wstring(datas,34)
            led_tip = get_wstring(datas,138)
            tip = get_wstring(datas,242)

            for i in range(10):
                err_bytes.append( get_byte(datas,i))
                run_bytes.append( get_byte(datas,i+10))
                io_modlue_status_bytes.append( get_byte(datas,i+20))
            
            
                

            for i in range(10):
                for j in range(8):
                    if self.get_bit_value_from_byte(err_bytes[i],j):
                        self.set_rack_status_color( self.rack_status[i][j],QColor(255,0,0))
                    elif self.get_bit_value_from_byte(run_bytes[i],j):
                        self.set_rack_status_color( self.rack_status[i][j],QColor(0,255,0))
                    else:
                        self.set_rack_status_color( self.rack_status[i][j],self.default_color)

                    if j<2:
                        if self.get_bit_value_from_byte(io_modlue_status_bytes[i],j):
                            self.set_rack_status_color( self.rack_io_moudle_status[i][j],QColor(0,255,0))
                        else:
                            self.set_rack_status_color( self.rack_io_moudle_status[i][j],QColor(255,0,0))

            for i in range(2):
                for j in range(16):
                    if self.get_bit_value_from_word(io_status_words[i],j):
                        self.set_rack_status_color( self.rack_io[i][j],QColor(0,255,0))
                    else:
                        self.set_rack_status_color( self.rack_io[i][j],self.default_color)
            
            self.ui.label_alarm_tip.setText(err_tip)
            self.ui.label_led_tip.setText(led_tip)
            self.ui.label_tip.setText(tip)

            self.rack_stores.apply_db12(datas)

            

        elif key == 'db31':
            for i in range(10):
                for j in range(8):

                    is_has_pallet = get_bool(datas, i * 8 + j, 6) or get_bool(datas, i * 8 + j, 7)
                    self.rack_stores.set_pallet(i+1,j+1,is_has_pallet)

                    self.rack_stores.set_material(i+1,j+1,"A库空筒",get_bool(datas, i * 8 + j, 0))
                    self.rack_stores.set_material(i+1,j+1,"A库实料",get_bool(datas, i * 8 + j, 1))
                    self.rack_stores.set_material(i+1,j+1,"B库空筒",get_bool(datas, i * 8 + j, 2))
                    self.rack_stores.set_material(i+1,j+1,"B库实料",get_bool(datas, i * 8 + j, 3))
                    self.rack_stores.set_material(i+1,j+1,"单库空筒",get_bool(datas, i * 8 + j, 4))
                    self.rack_stores.set_material(i+1,j+1,"单库实料",get_bool(datas, i * 8 + j, 5))

                    light_val = get_usint(datas,160 + i * 8 + j )
                    colors = {0:'灰',2:'绿',1:'红',3:'蓝',4:'黄'}
                    freqs = {0:'常亮',2:'1hz',1:'0.5hz'}
                    c =  light_val // 10

                    f =  light_val % 10

                    self.rack_stores.set_slot_light(i+1,j+1,colors.get(c, '灰'),freqs.get(f, '常亮'))


                    self.rack_stores.set_cylinder(i+1,j+1,'x',get_bool(datas, 80 + i * 8 + j, 0))
                
                    self.rack_stores.set_cylinder(i+1,j+1,'y',get_bool(datas, 80 + i * 8 + j, 2))


                    self.rack_stores.set_sensor(i+1,j+1,1,get_bool(datas, 80 + i * 8 + j, 1))
                    self.rack_stores.set_sensor(i+1,j+1,2,get_bool(datas, 80 + i * 8 + j, 3))

    def set_rack_status_color(self,btn:QToolButton,color):
        palette = btn.palette()
        palette.setColor(QPalette.ColorRole.Button, color)
        btn.setPalette(palette)

    def set_rack_status_text_color(self,btn:QToolButton,color):
        palette = btn.palette()
        palette.setColor(QPalette.ColorRole.ButtonText, color)
        btn.setPalette(palette)

    def set_rack_io_status_color(self,btn:QToolButton,en:bool):
        if en:
            btn.setStyleSheet("QToolButton{background-color:green;}")
        else:
            btn.setStyleSheet("QToolButton{background-color:grey;}")
    
    def set_rack_station_status_color(self,btn:QToolButton,status:int):
        if   status ==0: #default
            btn.setStyleSheet("QToolButton{background-color:grey;}")
        elif status ==1: #err
            btn.setStyleSheet("QToolButton{background-color:red;}")
        else:
            btn.setStyleSheet("QToolButton{background-color:green;}")
    
    def set_rack_station_text_color(self,btn:QToolButton,selected:bool):

        if selected:
            btn.setStyleSheet("QToolButton{color:white;}")
        else:
            btn.setStyleSheet("QToolButton{color:black;}")

    def set_rack_io_moudle_status_color(self,btn:QToolButton,en:bool):
        if en:
            btn.setStyleSheet("QToolButton{background-color:green;}")
        else:
            btn.setStyleSheet("QToolButton{background-color:red;}")


    def get_bit_value_from_byte(self, data,  bit_pos):
        """读取bool型控制位""" 
        return bool(data & (1 << bit_pos))
    
    def get_bit_value_from_word(self, data,  bit_pos):
        """读取bool型控制位""" 
        return bool(data & (1 << bit_pos))
    
    def read_paras(self):
        datas = self.plc_mgr.read_data(21,76,48, priority=True)
        if datas is None:
            return
        host_type = get_int(datas,0)
        host_start_No = get_int(datas,2)
        host_count = get_int(datas,4) 
        host1_racks_count = get_int(datas, 6 ) 
        host2_racks_count = get_int(datas, 8 ) 
        host3_racks_count = get_int(datas, 10) 
        host4_racks_count = get_int(datas, 12) 
        host5_racks_count = get_int(datas, 14) 
        host6_racks_count = get_int(datas, 16) 
        host7_racks_count = get_int(datas, 18) 
        host8_racks_count = get_int(datas, 20) 
        host9_racks_count = get_int(datas, 22) 
        host10_racks_count = get_int(datas,24) 
        comboBox_host_type:QComboBox =  self.ui.comboBox_host_type
        comboBox_host_counts:QComboBox =  self.ui.comboBox_host_counts
        spinBox_host_No_start:QSpinBox =  self.ui.spinBox_host_No_start
        comboBox_workType:QComboBox =  self.ui.comboBox_workType

        comboBox_host_type.setCurrentIndex(host_type)
        comboBox_workType.setCurrentIndex(get_int(datas,46) )
        comboBox_host_counts.setCurrentIndex(host_count-1)
        spinBox_host_No_start.setValue(host_start_No)
        self.ui.comboBox_host_1_rack_count.setCurrentIndex( host1_racks_count)
        self.ui.comboBox_host_2_rack_count.setCurrentIndex( host2_racks_count)
        self.ui.comboBox_host_3_rack_count.setCurrentIndex( host3_racks_count)
        self.ui.comboBox_host_4_rack_count.setCurrentIndex( host4_racks_count)
        self.ui.comboBox_host_5_rack_count.setCurrentIndex( host5_racks_count)
        self.ui.comboBox_host_6_rack_count.setCurrentIndex( host6_racks_count)
        self.ui.comboBox_host_7_rack_count.setCurrentIndex( host7_racks_count)
        self.ui.comboBox_host_8_rack_count.setCurrentIndex( host8_racks_count)
        self.ui.comboBox_host_9_rack_count.setCurrentIndex( host9_racks_count)
        self.ui.comboBox_host_10_rack_count.setCurrentIndex(host10_racks_count)

       
        for i in range(10):
            self.host_racks_arragement[i].setCurrentIndex(get_int(datas, 26+i*2 ))

        
        context =self.plc_mgr.ip +"("+ comboBox_host_type.currentText() + str(host_start_No) +'-' + str(host_start_No + host_count-1 ) +')'

        self.host_start_No ,self.host_count = host_start_No,host_count
        self.name_update.emit(context)
        self.handle_host_No_start_change(host_start_No)

    def write_paras(self):
        datas = bytearray([0]*46)
        comboBox_host_type:QComboBox =  self.ui.comboBox_host_type
        comboBox_workType:QComboBox =  self.ui.comboBox_workType
        comboBox_host_counts:QComboBox =  self.ui.comboBox_host_counts
        spinBox_host_No_start:QSpinBox =  self.ui.spinBox_host_No_start

        host_type = comboBox_host_type.currentIndex()
        workType  = comboBox_workType.currentIndex()
        host_start_No = spinBox_host_No_start.value()
        host_count = comboBox_host_counts.currentIndex() +1
        host1_racks_count  = self.ui.comboBox_host_1_rack_count.currentIndex()
        host2_racks_count  = self.ui.comboBox_host_2_rack_count.currentIndex()
        host3_racks_count  = self.ui.comboBox_host_3_rack_count.currentIndex()
        host4_racks_count  = self.ui.comboBox_host_4_rack_count.currentIndex()
        host5_racks_count  = self.ui.comboBox_host_5_rack_count.currentIndex()
        host6_racks_count  = self.ui.comboBox_host_6_rack_count.currentIndex()
        host7_racks_count  = self.ui.comboBox_host_7_rack_count.currentIndex()
        host8_racks_count  = self.ui.comboBox_host_8_rack_count.currentIndex()
        host9_racks_count  = self.ui.comboBox_host_9_rack_count.currentIndex()
        host10_racks_count = self.ui.comboBox_host_10_rack_count.currentIndex()

        racks_counts = [host1_racks_count,host2_racks_count,host3_racks_count,host4_racks_count,host5_racks_count,host6_racks_count,host7_racks_count,host8_racks_count,host9_racks_count,host10_racks_count]
        set_int(datas,0,host_type) 
        set_int(datas,2,host_start_No) 
        set_int(datas,4,host_count) 


        # set_int(datas,6 ,host1_racks_count) 
        # set_int(datas,8 ,host2_racks_count) 
        # set_int(datas,10,host3_racks_count) 
        # set_int(datas,12,host4_racks_count) 
        # set_int(datas,14,host5_racks_count) 
        # set_int(datas,16,host6_racks_count) 
        # set_int(datas,18,host7_racks_count) 
        # set_int(datas,20,host8_racks_count) 
        # set_int(datas,22,host9_racks_count) 
        # set_int(datas,24,host10_racks_count) 

        for i in range(10):
            if i> host_count-1:
                racks_counts[i] = 0

        print(racks_counts)


        for i in range(10):
            set_int(datas,6+i*2 ,racks_counts[i]) 

        for i in range(10):
            set_int(datas,26+i*2 ,self.host_racks_arragement[i].currentIndex()) 
            
        set_int(datas,46,workType) 


        # if host_count ==10:
        for i,count in enumerate( racks_counts):
            if i<host_count:
                if count==0:
                    msg = QMessageBox()
                    msg.setWindowTitle("failure")
                    msg.setText('参数验证失败')
                    msg.exec()# 显示信息框
                    return
        if host_type ==1:#阴极冷压
            if host_start_No + host_count-1>50 or workType>0:
                msg = QMessageBox()
                msg.setWindowTitle("failure")
                msg.setText('参数验证失败')
                msg.exec()# 显示信息框
                return
        elif host_type ==2:#阳极冷压
            if host_start_No + host_count-1>50 or workType>0:
                msg = QMessageBox()
                msg.setWindowTitle("failure")
                msg.setText('参数验证失败')
                msg.exec()# 显示信息框
                return

        elif host_type ==3:
            if host_start_No + host_count-1>50 :
                                msg = QMessageBox()
                                msg.setWindowTitle("failure")
                                msg.setText('参数验证失败')
                                msg.exec()# 显示信息框
                                return   
        elif host_type ==4:
            if host_start_No + host_count-1>50 :
                                msg = QMessageBox()
                                msg.setWindowTitle("failure")
                                msg.setText('参数验证失败')
                                msg.exec()# 显示信息框
                                return   

        elif host_type ==5:
            if host_start_No + host_count-1>50 :
                                msg = QMessageBox()
                                msg.setWindowTitle("failure")
                                msg.setText('参数验证失败')
                                msg.exec()# 显示信息框
                                return   
        elif host_type ==6:
            if host_start_No + host_count-1>50 :
                                msg = QMessageBox()
                                msg.setWindowTitle("failure")
                                msg.setText('参数验证失败')
                                msg.exec()# 显示信息框
                                return   

        elif host_type ==7:
            if host_start_No + host_count-1>50 :
                                msg = QMessageBox()
                                msg.setWindowTitle("failure")
                                msg.setText('参数验证失败')
                                msg.exec()# 显示信息框
                                return   
        elif host_type ==8:
            if host_start_No + host_count-1>50 :
                                msg = QMessageBox()
                                msg.setWindowTitle("failure")
                                msg.setText('参数验证失败')
                                msg.exec()# 显示信息框
                                return   

        
        else:
            msg = QMessageBox()
            msg.setWindowTitle("failure")
            msg.setText('参数验证失败')
            msg.exec()# 显示信息框
            return

        
        
        if self.plc_mgr.write_data(21,76,datas, priority=True):
            context =self.plc_mgr.ip +"("+ comboBox_host_type.currentText() + str(host_start_No) +'-' + str(host_start_No + host_count-1 ) +')'
            self.name_update.emit(context)

            self.read_paras()
            msg = QMessageBox()
            msg.setWindowTitle("success")
            msg.setText('参数写入成功，重启PLC生效')
            msg.exec()# 显示信息框
        else:
            msg = QMessageBox()
            msg.setWindowTitle("failure")
            msg.setText('参数写入失败')
            msg.exec()# 显示信息框

    def on_login_success(self):
        if global_cfg._user_name != 'admin':
            return
        btn_write:QPushButton = self.ui.pushButton_write
        btn_write.setEnabled(True)
        # self.enable_test_mode.setEnabled(True)

    def on_logout(self):

        btn_write:QPushButton = self.ui.pushButton_write
        btn_write.setEnabled(False)
        # self.enable_test_mode.setEnabled(False)

        # data_broker.start_data_polling()

        # mainlayout = QVBoxLayout()
        # group_box_PLC = QGroupBox("PLC")

        # group_box_PLC_layout = QVBoxLayout(group_box_PLC)

        # h_layout1 = QHBoxLayout()
        # h_layout2 = QHBoxLayout()
        # h_layout3 = QHBoxLayout()

        # self._plc_name = NameValLabel('名称:')
        # self._ip_addr = NameValLabel('IP地址:')
        # self._proj_ver = NameValLabel('程序版本号:')
        # self._checksum = NameValLabel('程序校验码:')
        # h_layout1.addWidget(self._plc_name)
        # h_layout1.addWidget(self._ip_addr)
        # h_layout1.addWidget(self._proj_ver)
        # h_layout1.addWidget(self._checksum)

        # self._led_grn = QToolButton()
        # self._led_red = QToolButton()
        # self._led_yel = QToolButton()
        # h_layout2.addWidget(QLabel('状态指示灯'))
        # spacer1 =  QSpacerItem(20, 20, hPolicy = QSizePolicy.Policy.Expanding, vPolicy = QSizePolicy.Policy.Preferred)
        # spacer2 =  QSpacerItem(20, 20, hPolicy = QSizePolicy.Policy.Expanding, vPolicy = QSizePolicy.Policy.Preferred)
        # spacer3 =  QSpacerItem(20, 20, hPolicy = QSizePolicy.Policy.Expanding, vPolicy = QSizePolicy.Policy.Preferred)
        # h_layout2.addSpacerItem(spacer1)
        # h_layout2.addWidget(self._led_grn)
        # # h_layout2.addSpacerItem(spacer2)
        # h_layout2.addWidget(self._led_red)
        # # h_layout2.addSpacerItem(spacer3)
        # h_layout2.addWidget(self._led_yel)

        # reboot_btn = QPushButton('重启PLC')
        # spacer =  QSpacerItem(20, 20, hPolicy = QSizePolicy.Policy.Expanding, vPolicy = QSizePolicy.Policy.Preferred)
        # h_layout3.addWidget(reboot_btn)
        # h_layout3.addSpacerItem(spacer)

        # group_box_PLC_layout.addLayout(h_layout1)
        # group_box_PLC_layout.addLayout(h_layout2)
        # group_box_PLC_layout.addLayout(h_layout3)
        # group_box_PLC_layout.setStretch(0,1)
        # group_box_PLC_layout.setStretch(1,1)
        # group_box_PLC_layout.setStretch(2,1)


        






        # mainlayout.addWidget(group_box_PLC)



        # self.setLayout(mainlayout)

class AGV_interact(LoadWidget):

    def __init__(self,plc_mgr:PLCManager,data_broker:DataBroker, parent=None):

        ui_file_path = res_mng.get_ui_path('agv_interface.ui')
        qss_file     = res_mng.get_ui_path('rcd.qss')
        super().__init__(ui_file_path,qss_file)
        data_broker.data_ready.connect(self.handle_data_broker)

    def handle_data_broker(self,name_datas):
        key,datas =name_datas
        if key == 'db24':

            self.ui.lcdNumber_Rack_Station_Enable.display(get_int(datas,270)) 
            self.ui.lcdNumber_Rack_Allow_AGVEnter.display(get_int(datas,272)) 
            self.ui.lcdNumber_Rack_AGVInside.display(get_int(datas,274)) 
            self.ui.lcdNumber_Rack_Allow_AGVWrite.display(get_int(datas,276)) 
            self.ui.lcdNumber_Rack_TrayStatus.display(get_int(datas,278)) 
            self.ui.lcdNumber_Rack_TrayStatusA.display(get_int(datas,280)) 
            self.ui.lcdNumber_Rack_TrayStatusB.display(get_int(datas,282)) 
            self.ui.lcdNumber_Rack_MaterialAttribute.display(get_int(datas,284)) 
            self.ui.lcdNumber_Rack_RollerType.display(get_int(datas,286)) 
            self.ui.lcdNumber_Rack_MaterialType.display(get_int(datas,288)) 
            self.ui.lcdNumber_Rack_MaterialState.display(get_int(datas,354)) 
            self.ui.label_Rack_RollerNumberA.setText(get_string(datas,290)) 
            self.ui.label_Rack_RollerNumberB.setText(get_string(datas,322)) 
            
            self.ui.lcdNumber_AGV_Racktasking.display(get_int(datas,184)) 
            self.ui.lcdNumber_AGV_Rack_ReqEnter.display(get_int(datas,180)) 
            self.ui.lcdNumber_AGV_Rack_Entering.display(get_int(datas,182)) 
            self.ui.lcdNumber_AGV_Req_LAGVLeave.display(get_int(datas,186)) 
            self.ui.lcdNumber_AGV_Rack_Write.display(get_int(datas,188)) 
            self.ui.lcdNumber_AGV_TrayStatus.display(get_int(datas,190)) 
            self.ui.lcdNumber_AGV_TrayStatusA.display(get_int(datas,192)) 
            self.ui.lcdNumber_AGV_TrayStatusB.display(get_int(datas,194)) 
            self.ui.lcdNumber_AGV_MaterialAttribute.display(get_int(datas,196)) 
            self.ui.lcdNumber_AGV_RollerType.display(get_int(datas,198)) 
            self.ui.lcdNumber_AGV_MaterialType.display(get_int(datas,200)) 
            self.ui.label_AGV_RollerNumberA.setText(get_string(datas,202)) 
            self.ui.label_AGV_RollerNumberB.setText(get_string(datas,234)) 
            self.ui.lcdNumber_AGV_MaterialState.display(get_int(datas,266)) 

            #------------------------------------------------------------------------
            self.ui.lcdNumber_ToLAGV_Rack_Station_Enable.display(get_int(datas,90)) 
            self.ui.lcdNumber_Rack_Allow_LAGVEnter.display(get_int(datas,92)) 
            self.ui.lcdNumber_Rack_Req_LAGVLeave.display(get_int(datas,94)) 
            self.ui.lcdNumber_Rack_Allow_LAGVWrite.display(get_int(datas,96)) 
            self.ui.lcdNumber_ToLAGV_Rack_TrayStatus.display(get_int(datas,100)) 
            self.ui.lcdNumber_ToLAGV_Rack_TrayStatusA.display(get_int(datas,102)) 
            self.ui.lcdNumber_ToLAGV_Rack_TrayStatusB.display(get_int(datas,104)) 
            self.ui.lcdNumber_ToLAGV_Rack_MaterialAttribute.display(get_int(datas,106)) 
            self.ui.lcdNumber_ToLAGV_Rack_RollerType.display(get_int(datas,108)) 
            self.ui.lcdNumber_ToLAGV_Rack_MaterialType.display(get_int(datas,110)) 
            self.ui.lcdNumber_ToLAGV_Rack_MaterialState.display(get_int(datas,176)) 
            self.ui.label_ToLAGV_Rack_RollerNumberA.setText(get_string(datas,112)) 
            self.ui.label_ToLAGV_Rack_RollerNumberB.setText(get_string(datas,144)) 
            
            self.ui.lcdNumber_LAGV_Racktasking.display(get_int(datas,4)) 
            self.ui.lcdNumber_LAGV_Rack_ReqEnter.display(get_int(datas,0)) 
            self.ui.lcdNumber_LAGV_Rack_Entering.display(get_int(datas,2)) 
            self.ui.lcdNumber_Rack_LAGVInside.display(get_int(datas,6)) 
            self.ui.lcdNumber_LAGV_Rack_Write.display(get_int(datas,8)) 
            self.ui.lcdNumber_LAGV_TrayStatus.display(get_int(datas,10)) 
            self.ui.lcdNumber_LAGV_TrayStatusA.display(get_int(datas,12)) 
            self.ui.lcdNumber_LAGV_TrayStatusB.display(get_int(datas,14)) 
            self.ui.lcdNumber_LAGV_MaterialAttribute.display(get_int(datas,16)) 
            self.ui.lcdNumber_LAGV_RollerType.display(get_int(datas,18)) 
            self.ui.lcdNumber_LAGV_MaterialType.display(get_int(datas,20)) 
            self.ui.label_LAGV_RollerNumberA.setText(get_string(datas,22)) 
            self.ui.label_LAGV_RollerNumberB.setText(get_string(datas,54)) 
            self.ui.lcdNumber_LAGV_MaterialState.display(get_int(datas,86)) 

            #------------------------------------------------------------------------
            self.ui.lcdNumber_StationEnable.display(get_int(datas,374)) 
            self.ui.lcdNumber_AGVtasking.display(get_int(datas,384)) 
            self.ui.lcdNumber_WriteEnable.display(get_int(datas,376)) 
            self.ui.lcdNumber_TrayStatus.display(get_int(datas,378)) 
            self.ui.lcdNumber_TrayStatusA.display(get_int(datas,380)) 
            self.ui.lcdNumber_TrayStatusB.display(get_int(datas,382)) 
            self.ui.lcdNumber_MaterialAttribute.display(get_int(datas,386)) 
            self.ui.lcdNumber_DrumType.display(get_int(datas,388)) 
            self.ui.lcdNumber_MaterialType.display(get_int(datas,390)) 
            self.ui.lcdNumber_MaterialState.display(get_int(datas,456)) 
            self.ui.label_RollerNumberA.setText(get_string(datas,392)) 
            self.ui.label_RollerNumberB.setText(get_string(datas,424)) 

            self.ui.lcdNumber_LightStatus.display(get_int(datas,368)) 
            self.ui.lcdNumber_RackMessage.display(get_int(datas,370)) 

class Recipe(LoadWidget):
    def __init__(self,plc_mgr:PLCManager,data_broker:DataBroker, parent=None):

        ui_file_path = res_mng.get_ui_path('Recipe.ui')
        qss_file     = res_mng.get_ui_path('rcd.qss')
        super().__init__(ui_file_path,qss_file)
        self.plc_mgr = plc_mgr

        self.spinBox_DrumType:QSpinBox = self.ui.spinBox_DrumType
        self.spinBox_LoadDrumType:QSpinBox = self.ui.spinBox_LoadDrumType
        self.spinBox_UnLoadDrumType:QSpinBox = self.ui.spinBox_UnLoadDrumType
        self.spinBox_DrumType.editingFinished.connect(self.on_spinBox_DrumType_editingFinished)
        self.spinBox_LoadDrumType.editingFinished.connect(self.on_spinBox_LoadDrumType_editingFinished)
        self.spinBox_UnLoadDrumType.editingFinished.connect(self.on_spinBox_UnLoadDrumType_editingFinished)

        pushButton_write:QPushButton = self.ui.pushButton_write
        pushButton_write_all:QPushButton = self.ui.pushButton_write_all
        pushButton_write.pressed.connect(lambda:self.plc_mgr.write_data(26,12,bytearray([1]), priority=True))
        pushButton_write.released.connect(lambda:self.plc_mgr.write_data(26,12,bytearray([0]), priority=True))

        pushButton_write_all.pressed.connect(lambda:self.plc_mgr.write_data(26,13,bytearray([1]), priority=True))
        pushButton_write_all.released.connect(lambda:self.plc_mgr.write_data(26,13,bytearray([0]), priority=True))

        if global_cfg.is_logged_in:
            pushButton_write.setEnabled(True)
            pushButton_write_all.setEnabled(True)
        else:
            pushButton_write.setEnabled(False)
            pushButton_write_all.setEnabled(False)

    def on_spinBox_DrumType_editingFinished(self):
        datas = bytearray([0]*2)
        set_int(datas,0,self.spinBox_DrumType.value())
        self.plc_mgr.write_data(26,6,datas, priority=True)
    
    def on_spinBox_LoadDrumType_editingFinished(self):
        datas = bytearray([0]*2)
        set_int(datas,0,self.spinBox_LoadDrumType.value())
        self.plc_mgr.write_data(26,8,datas, priority=True)
    
    def on_spinBox_UnLoadDrumType_editingFinished(self):
        datas = bytearray([0]*2)
        set_int(datas,0,self.spinBox_UnLoadDrumType.value())
        self.plc_mgr.write_data(26,10,datas, priority=True)



    def read_paras(self):

        datas = self.plc_mgr.read_data(7,0,2, priority=True)
        if datas is None:
            return
       
        groupBox_LY :QGroupBox = self.ui.groupBox_LY
        groupBox_MQ :QGroupBox = self.ui.groupBox_MQ
        if get_int(datas,0) ==1 or get_int(datas,0) ==2:
            groupBox_LY.setVisible(True)
            groupBox_MQ.setVisible(False)
        elif get_int(datas,0) ==3 or get_int(datas,0) ==4 or get_int(datas,0) >=5 and get_int(datas,0) <=8:
            groupBox_LY.setVisible(False)
            groupBox_MQ.setVisible(True)

        else:
            groupBox_LY.setVisible(False)
            groupBox_MQ.setVisible(False)
            return
        datas = self.plc_mgr.read_data(26,0,6, priority=True)
        if datas is None:
            return

        self.spinBox_DrumType.setValue(get_int(datas,0))
        self.spinBox_LoadDrumType.setValue(get_int(datas,2))
        self.spinBox_UnLoadDrumType.setValue(get_int(datas,4))

    def on_login_success(self):

        pushButton_write:QPushButton = self.ui.pushButton_write
        pushButton_write_all:QPushButton = self.ui.pushButton_write_all
        pushButton_write.setEnabled(True)
        pushButton_write_all.setEnabled(True)
      

    def on_logout(self):

        pushButton_write:QPushButton = self.ui.pushButton_write
        pushButton_write_all:QPushButton = self.ui.pushButton_write_all
        pushButton_write.setEnabled(False)
        pushButton_write_all.setEnabled(False)
        
        



class RackStorage(LoadWidget):

    rack_store_data = Signal(tuple)

    def __init__(self,plc_mgr:PLCManager,data_broker:DataBroker, parent=None):

        ui_file_path = res_mng.get_ui_path('rack_storage.ui')
        qss_file     = res_mng.get_ui_path('rcd.qss')
        super().__init__(ui_file_path,qss_file)
        self.plc_mgr = plc_mgr
        data_broker.data_ready.connect(self.handle_data_broker)

        self.flag = 0
        self._Rack_TrayStatus = ('0-空库位','1-空托盘','2-单空筒','3-双空筒','4-单实料','5-双实料')
        self._Rack_TrayStatusAB = ('0-无','1-空库位','2-空卷筒','3-有实料')
        self._Rack_MaterialAttribute = ('0-无属性','1-亮面顺时针','2-亮面逆时针','3-暗面顺时针','4-暗面逆时针')
        self._Rack_MaterialState = ('0-空','1-NG','2-OK')

        self.Rack_TrayStatus_w:QComboBox = self.ui.comboBox_Rack_TrayStatus_w
        self.Rack_TrayStatusA_w:QComboBox = self.ui.comboBox_Rack_TrayStatusA_w
        self.Rack_TrayStatusB_w:QComboBox = self.ui.comboBox_Rack_TrayStatusB_w
        self.Rack_MaterialAttribute_w:QComboBox = self.ui.comboBox_Rack_MaterialAttribute_w
        self.Rack_MaterialState_w:QComboBox = self.ui.comboBox_Rack_MaterialState_w

        self.Rack_RollerType_w:QSpinBox = self.ui.spinBox_Rack_RollerType_w
        self.Rack_MaterialType_w:QSpinBox = self.ui.spinBox_Rack_MaterialType_w

        self.Rack_RollerNumberA_w:QLineEdit = self.ui.lineEdit_Rack_RollerNumberA_w
        self.Rack_RollerNumberB_w:QLineEdit = self.ui.lineEdit_Rack_RollerNumberB_w

        self.pushButton_write_prev:QPushButton = self.ui.pushButton_write_prev
        self.pushButton_write_prev.pressed.connect(lambda:self.plc_mgr.write_data(25,158,bytearray([1]), priority=True))
        self.pushButton_write_prev.released.connect(lambda:self.plc_mgr.write_data(25,158,bytearray([0]), priority=True))
        self.pushButton_write_prev.released.connect(self.read_rack_paras_w)

        self.pushButton_write:QPushButton = self.ui.pushButton_write
        self.pushButton_write.pressed.connect(lambda:self.plc_mgr.write_data(25,159,bytearray([1]), priority=True))
        self.pushButton_write.released.connect(lambda:self.plc_mgr.write_data(25,159,bytearray([0]), priority=True))

        if global_cfg.is_logged_in:
            self.pushButton_write.setEnabled(True)
        else:
            self.pushButton_write.setEnabled(False)


        self.Rack_TrayStatus_w.currentIndexChanged.connect(lambda e : self.handle_combox_current_change(80,e))
        self.Rack_TrayStatusA_w.currentIndexChanged.connect(lambda e : self.handle_combox_current_change(82,e))
        self.Rack_TrayStatusB_w.currentIndexChanged.connect(lambda e : self.handle_combox_current_change(84,e))

        self.Rack_MaterialAttribute_w.currentIndexChanged.connect(lambda e : self.handle_combox_current_change(86,e))
        self.Rack_MaterialState_w.currentIndexChanged.connect(lambda e : self.handle_combox_current_change(156,e))

        self.Rack_RollerType_w.valueChanged.connect(lambda e : self.handle_combox_current_change(88,e))
        self.Rack_MaterialType_w.valueChanged.connect(lambda e : self.handle_combox_current_change(90,e))

       

        self.Rack_RollerNumberA_w.editingFinished.connect(self.on_RollerNumberA_w_editingFinished)
        self.Rack_RollerNumberB_w.editingFinished.connect(self.on_RollerNumberB_w_editingFinished)

        groupBox_display:QGroupBox = self.ui.groupBox_display
        layout =QVBoxLayout()
        w = RackStoreWindow()
        layout.addWidget(w)
        groupBox_display.setLayout(layout)

        self.rack_store_data.connect(w.update_rack_store_display)


    def handle_combox_current_change(self,offset:int,index:int):
       
        datas = bytearray([0]*2)
        set_int(datas,0,index)
        self.plc_mgr.write_data(25,offset,datas, priority=True)

        #if 80<=offset<=90:
        #    self.flag = 1
        

    def on_RollerNumberA_w_editingFinished(self):

        context = self.Rack_RollerNumberA_w.text()
        datas = bytearray([0]*32)
        try:
            set_string(datas,0,context,30)
            self.plc_mgr.write_data(25,92,datas, priority=True)
        except Exception as e:
            print(e)
    
    def on_RollerNumberB_w_editingFinished(self):

        context = self.Rack_RollerNumberB_w.text()
        datas = bytearray([0]*32)
        try:
            set_string(datas,0,context,30)
            self.plc_mgr.write_data(25,124,datas, priority=True)
        except Exception as e:
            print(e)

    def read_rack_paras_w(self):

        datas = self.plc_mgr.read_data(25,80,159-80+1, priority=True)

        if datas is None:
            return
        self.Rack_TrayStatus_w.setCurrentIndex(get_int(datas,0))
        self.Rack_TrayStatusA_w.setCurrentIndex(get_int(datas,2))
        self.Rack_TrayStatusB_w.setCurrentIndex(get_int(datas,4))
        self.Rack_MaterialAttribute_w.setCurrentIndex(get_int(datas,6))
        self.Rack_MaterialState_w.setCurrentIndex(get_int(datas,76))

        self.Rack_RollerType_w.setValue(get_int(datas,8))
        self.Rack_MaterialType_w.setValue(get_int(datas,10))


        self.Rack_RollerNumberA_w.setText(get_string(datas,12))
        self.Rack_RollerNumberB_w.setText(get_string(datas,44))


    def handle_data_broker(self,name_datas):
        key,datas =name_datas
     
        if key == 'db25':
            self.ui.label_Rack_TrayStatus.setText(self._Rack_TrayStatus[get_int(datas,0)])
            self.ui.label_Rack_TrayStatusA.setText(self._Rack_TrayStatusAB[get_int(datas,2)])
            self.ui.label_Rack_TrayStatusB.setText(self._Rack_TrayStatusAB[get_int(datas,4)])
            self.ui.label_Rack_MaterialAttribute.setText(self._Rack_MaterialAttribute[get_int(datas,6)])
            self.ui.label_Rack_MaterialState.setText(self._Rack_MaterialState[get_int(datas,76)])
            self.ui.label_Rack_RollerType.setText(str(get_int(datas,8)))
            self.ui.label_Rack_MaterialType.setText(str(get_int(datas,10)))

            str_A = get_string(datas,12)
            str_B = get_string(datas,44)
            self.ui.label_Rack_RollerNumberA.setText(str_A) if str_A  else self.ui.label_Rack_RollerNumberA.setText(' ')
            self.ui.label_Rack_RollerNumberB.setText(str_B) if str_B  else self.ui.label_Rack_RollerNumberB.setText(' ')
            # if self.flag==1 :
            #     self.Rack_TrayStatus_w.setCurrentIndex(get_int(datas,80))
            #     self.Rack_TrayStatusA_w.setCurrentIndex(get_int(datas,82))
            #     self.Rack_TrayStatusB_w.setCurrentIndex(get_int(datas,84))
             
            #     self.Rack_MaterialAttribute_w.setCurrentIndex(get_int(datas,86))
            #     self.Rack_MaterialState_w.setCurrentIndex(get_int(datas,156))

            #     self.Rack_RollerType_w.setValue(get_int(datas,88))
            #     self.Rack_MaterialType_w.setValue(get_int(datas,90))


            #     self.Rack_RollerNumberA_w.setText(get_string(datas,92))
            #     self.Rack_RollerNumberB_w.setText(get_string(datas,124))

            #     self.flag = 0
            

            self.rack_store_data.emit((get_bool(datas,78,0),get_bool(datas,78,1),get_bool(datas,78,2),get_bool(datas,78,3),
                                       get_bool(datas,78,4),get_bool(datas,78,5),get_bool(datas,78,6),get_bool(datas,78,7)))
            
    
    def on_login_success(self):

       
        self.pushButton_write.setEnabled(True)
      
      

    def on_logout(self):

      
        self.pushButton_write.setEnabled(False)
      

class Rcd(QListWidget):

    def __init__(self,plc_mgr:PLCManager, parent=None):
        super().__init__(parent)
        self.plc_mgr = plc_mgr
        self.update_list_widget(4)
        

    def update_list_widget(self,index):
        """更新列表控件显示脚本生成的新数据"""
        # 清空列表
        if index == 4:
            self.clear()
            
            # 只显示脚本生成的新数据（不包含fatherX/dataX格式的数据）
            for i in range(10):
                # 过滤掉原始数据（fatherX/dataX格式），只显示自定义数据
                datas =  self.plc_mgr.read_data(23,2040*i,2040, priority=True)
                if datas is None:
                    return
                for j in range(10):
                    
                    self.addItem(get_wstring(datas,j*204))


class WindowContainer(LoadWidget):

    name_update = Signal(str)

    def __init__(self,plc_mgr:PLCManager,data_broker:DataBroker,SerialNumber:str, parent=None):

        ui_file_path = res_mng.get_ui_path('form.ui')
        qss_file     = res_mng.get_ui_path('rcd.qss')
        super().__init__(ui_file_path,qss_file)
       
        self.plc_mgr =plc_mgr
        self.data_broker =data_broker
        layout = QVBoxLayout()

        leftArea :QFrame= self.ui.left_area
        rightArea:QTabWidget = self.ui.right_area
        
        w = ConfigWindow(plc_mgr,data_broker,SerialNumber)
        w.name_update.connect(lambda e: self.name_update.emit(e))
        layout.addWidget( w)
        w.host_selected_change.connect(self.on_host_select_change)
        
        leftArea.setLayout(layout)
        self._ConfigWindow = w
        
        layout = QVBoxLayout()
        layout.addWidget( AGV_interact(plc_mgr,data_broker))
        self.ui.tab_1.setLayout(layout)

        layout = QVBoxLayout()
        w =Recipe(plc_mgr,data_broker)
        layout.addWidget( w)
        self.ui.tab_2.setLayout(layout)
        rightArea.currentChanged.connect(w.read_paras)
        self._recipe =w


        layout = QVBoxLayout()
        w = RackStorage(plc_mgr,data_broker)
        layout.addWidget( w)
        self.ui.tab_3.setLayout(layout)
        self._RackStorage =w
        rightArea.currentChanged.connect(w.read_rack_paras_w)

        layout = QVBoxLayout()
        w =Rcd(plc_mgr)
        layout.addWidget(w )
        self.ui.tab_5.setLayout(layout)
        rightArea.currentChanged.connect(w.update_list_widget)
        self._ConfigWindow.update_rcd_window.connect(lambda:w.update_list_widget(4))
        self._rcd =w
    

    def on_host_select_change(self,host_No:int):
        
        tab_widget:QTabWidget = self.ui.right_area
        if tab_widget.currentIndex()==1:
            QTimer.singleShot(500,self._recipe.read_paras)
        elif tab_widget.currentIndex()==4:
            QTimer.singleShot(500,lambda:self._rcd.update_list_widget(4))

    def shutdown(self):
        """释放本页面占用的后台线程（关闭标签页 / 程序退出时调用）。

        QThread 未结束就被销毁会触发
        "QThread: Destroyed while thread is still running"，因此这里
        必须先把轮询线程停掉再让窗口被删除。
        """
        broker = getattr(self, "data_broker", None)
        if broker is not None:
            try:
                broker.stop_data_polling()
            except Exception:
                pass
        plc_mgr = getattr(self, "plc_mgr", None)
        if plc_mgr is not None:
            try:
                plc_mgr.stop_thread()
            except Exception:
                pass

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
    
    def on_login_change(self):
        self._ConfigWindow.handle_login_out()
        if global_cfg.is_logged_in:
            self._ConfigWindow.on_login_success()
            self._recipe.on_login_success()
            self._RackStorage.on_login_success()
        else:
            self._ConfigWindow.on_logout()
            self._recipe.on_logout()
            self._RackStorage.on_logout()
            global_cfg._user_name = ''

