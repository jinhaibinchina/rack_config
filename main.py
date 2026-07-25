
from PyQt6.QtWidgets import QApplication,QWidget, QListWidget, QMessageBox, QFrame, QDialog, QToolButton,QVBoxLayout,QHBoxLayout,QLabel,QListWidgetItem
from PyQt6.QtGui import QIcon,QAction
from PyQt6.QtCore import Qt, QObject, QEvent ,pyqtSignal,QTimer

import sys
import os
from plc_manager import PLCManager
from search_ip import scan_by_arp
from load_ui import LoadMainWindow

from tabbed_wigdet import TabbedPlcWidget
from resource_manager import resource_manager as res_mng

from login_window import LoginWindow
from global_config import global_cfg

from rcd_window import RcdWindow

VERSION = "V3.3.2"
VERSION_INFO = f"版本:{VERSION}\n1、初版"


class Panel(QFrame):
    """基础导航面板，不包含新生成数据和脚本功能"""
    
    ask_open_tab = pyqtSignal(str,str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.Box)
        self.setContentsMargins(5, 5, 5, 5)

        self.ip_SerialNumber = {}
        main_layout =QVBoxLayout()
        
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(1)
        # 添加简单的标签说明
        h_layout =QHBoxLayout()
        label = QLabel("设备列表")
        # label.setAlignment(Qt.AlignCenter)

        self.update_btn =QToolButton()
        self.update_btn.setArrowType(Qt.ArrowType.NoArrow)
        self.update_btn.clicked.connect(self.find_plc)

        self.update_btn.setIcon( QIcon(res_mng.get_icon_path("link.png")))
        h_layout.addWidget(label)
        h_layout.addWidget(self.update_btn)
        h_layout.setStretch(0,5)
        h_layout.setStretch(1,1)
        self.listWidget = QListWidget()
        self.listWidget.itemDoubleClicked.connect(self.on_item_click)

        self.setMinimumHeight(200)

        main_layout.addLayout(h_layout)
        main_layout.addWidget( self.listWidget)


        self.setLayout(main_layout)

    def find_plc(self):
        arp_nodes = scan_by_arp()
        plc_ips = []
        serialNumbers = []
        self.ip_SerialNumber = {}
        plc_mgr = PLCManager(ip="0.0.0.0", rack=0, slot=1)
        for ip in arp_nodes:
            plc_mgr.change_ip(ip)
            if plc_mgr.connect():
                plc_ips.append(ip)
                serialNumbers.append(plc_mgr.client.get_cpu_info().SerialNumber)
                self.ip_SerialNumber =dict( zip(plc_ips,serialNumbers))
                # print(help(plc_mgr.client.get_cpu_info()))
                print( type(plc_mgr.client.get_cpu_info().SerialNumber))
                print(self.ip_SerialNumber )
                # print(plc_mgr.client.plc_cold_start())
                plc_mgr.disconnect()

        
        self.update_list_widget(plc_ips)

       

    def update_list_widget(self,ip_adresses:list):
        """更新列表控件显示脚本生成的新数据"""
        # 清空列表
        self.listWidget.clear()
        if ip_adresses:
            for ip in ip_adresses:
                self.listWidget.addItem(ip)
        
    def on_item_click(self,item:QListWidgetItem):
        if item.text():
            self.ask_open_tab.emit(item.text(),self.ip_SerialNumber[item.text()].decode('utf-8'))

class MainWidget(LoadMainWindow):
    
    def __init__(self):
        ui_file_path = res_mng.get_ui_path('main.ui')
        qss_file     = res_mng.get_ui_path('rcd.qss')
        super().__init__(ui_file_path, qss_file)
        print(ui_file_path)
        # self.setWindowIcon(QIcon('ico/box_1.ico'))  # 设置图标
        self.setWindowTitle(f"料架PLC配置工具 {VERSION}")
        self.setGeometry(100, 100, 1600, 900)
        # self.setFixedSize(900,800)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_status_bar)
        self._timer.start(1000)

        left_area:QFrame = self.ui.leftFrame 
        lest_area_layout:QVBoxLayout = self.ui.leftLayout
        self.panel = Panel(left_area)
        lest_area_layout.insertWidget(0,self.panel)
        left_area.setMaximumWidth(200)

        tabbedPlc = TabbedPlcWidget()
        self.panel.ask_open_tab.connect(tabbedPlc.addTab)
        self._tabbedPlc = tabbedPlc

        self.setContentsMargins(0, 0, 0, 0)
        rightArea_layout :QVBoxLayout = self.ui.rightLayout
     
        rightArea_layout.addWidget(tabbedPlc)

        # global_cfg.status_bar = self.statusBar()
       
        #---------------------------------------------------------------------------------------------------------

        self._createMenu()

    def update_status_bar(self):

        status_bar = self.statusBar()
        if global_cfg.is_logged_in :
            status_bar.showMessage(f'用户:{global_cfg._user_name} 已登入')
        else:
            status_bar.showMessage(f'无用户登入')


    def _createMenu(self):
        """创建菜单"""
        menubar = self.menuBar()
        
        login_menu = menubar.addMenu("用户")
        login_action = QAction("登入", self)
        login_action.triggered.connect(self.slot_login)

        logout_action = QAction("登出", self)
        logout_action.triggered.connect(self.slot_logout)

        login_menu.addAction(login_action)
        login_menu.addAction(logout_action)

        RCD_menu = menubar.addMenu("PLC日志")
        rcd_action = QAction("打开日志文件", self)
        rcd_action.triggered.connect(self.solt_rcd)

        RCD_menu.addAction(rcd_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(MainWidget.slot_version_btn)

        help_menu.addAction(about_action)
    
    
    
    def closeEvent(self, event):
        """
        程序退出事件
        :param event:
        :return:
        """
      
        event.accept()  # 接受事件

    def eventFilter(self, source, event):
        """
        事件过滤器
        :param source:
        :param event:
        :return:
        """
        if event.type() == QEvent.Wheel:
            # ctrl + 滑轮
            if event.modifiers() == Qt.ControlModifier:
                return True  # 返回True以告诉Qt已经处理该事件
        return super().eventFilter(source, event)

    
    

    @staticmethod
    def slot_version_btn():
        msg = QMessageBox()
        msg.setWindowTitle("版本说明")
        msg.setText(VERSION_INFO +'\n designer:jinhaibin')
        msg.exec()# 显示信息框

    # @staticmethod
    def slot_login(self):
        top_window =LoginWindow()
        top_window.login_change_signal.connect(self._tabbedPlc.handle_loggin_out)
        top_window.exec()

    def slot_logout(self):

        global_cfg.is_logged_in = False
        self._tabbedPlc.handle_loggin_out()

    def solt_rcd(self):

        top_window =RcdWindow()
     
        top_window.exec()


class App(QApplication):
    def notify(self, source: QObject, event: QEvent):
        """
        本次重写notify是为了截获应用的所有事件
        :param source: 事件接收对象
        :param event: 具体事件
        :return: True表示事件已经处理，False表示没有处理，需要继续往下传递
        """
        # if event.type() == QEvent.Wheel and event.modifiers() == Qt.ControlModifier:
        #     # print(f"App {source}")
        #     pass
            # return True
        # print(source, event)
        return super().notify(source, event)





if __name__ == '__main__':
    app = App(sys.argv)
    app.setStyle('Fusion')
    w = MainWidget()
    w.show()
    sys.exit(app.exec())




