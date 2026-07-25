from __future__ import annotations
from PyQt6.QtWidgets import (QApplication, QWidget,  QTabWidget, QVBoxLayout, QSizePolicy,
                            QHBoxLayout, QPushButton,  QMenu, QMessageBox, QDialog,QSpacerItem,
                            QInputDialog)
from PyQt6.QtCore import pyqtSignal, pyqtSlot, Qt,QObject
from PyQt6.QtGui import QCloseEvent,QIcon
from typing import Dict, Optional

from plc_window import ConfigWindow ,WindowContainer
from plc_manager import PLCManager
from data_broker import DataBroker


# 主窗口类
class TabbedPlcWidget(QWidget):
    # 静态实例映射
    # _instances: Dict[str, 'TabbedPlcWidget'] = {}
    
    # 信号定义
    
    sendTabToNewWindow = pyqtSignal(object)
    tabWidget_currentChanged = pyqtSignal()  #用于关闭播放器

 

    def __init__(self,  parent: QWidget=None):
        super().__init__(parent)
      
       
      
        self._existed_ips = set()

       
        
        # 创建标签页控件
        self.tab_widget = QTabWidget()
       
        self.tab_widget.setTabsClosable(True)
        

       
        

        # 设置主布局
        layout = QVBoxLayout()
        layout.addWidget(self.tab_widget)
        self.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
       
        
      
        
        # 连接信号槽
        self._setup_connections()
        
        # 注册实例
        # TabbedPlcWidget._instances[] = self
        
        
 
       

    def _setup_connections(self):
        """初始化信号槽连接"""
        self.tab_widget.currentChanged.connect(self.on_tabWidget_currentChanged)
        self.tab_widget.tabCloseRequested.connect(self.on_tabWidget_tabCloseRequested)
              
    
    def currentTab(self) -> Optional[WindowContainer]:
        """获取当前标签页"""
        current_widget = self.tab_widget.currentWidget()
        return current_widget if isinstance(current_widget, WindowContainer) else None
    
    def allTab(self) -> Optional[WindowContainer]:
        
        PlotMatrix_list = []
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            PlotMatrix_list.append(widget)
        return PlotMatrix_list

    def handle_loggin_out(self):
        for Container in self.allTab():
            Container.on_login_change()

    def tabWidget(self) -> QTabWidget:
        return self.tab_widget


    def addTab(self, ip_addr:str,serialNumber:str):
        if ip_addr in self._existed_ips:
            return
        plc_mgr = PLCManager(ip=ip_addr, rack=0, slot=1)
        if plc_mgr.connect():
            self._existed_ips.add(ip_addr)
        else:
            return
        data_broker = DataBroker(plc_mgr)
        tab_name = ip_addr
        tab = WindowContainer(plc_mgr,data_broker,serialNumber)
        tab.name_update.connect(self.renameCurrentTab)
        
        index = self.tab_widget.addTab(tab, tab_name)
        self.tab_widget.setCurrentIndex(index)

        
       
    def renameCurrentTab(self,new_name):
        """重命名当前标签页"""
        current_index = self.tab_widget.currentIndex()
        if current_index >= 0:
            
            self.tab_widget.setTabText(current_index, new_name)


  

   

 
  


    
   

          

    

   

   

   
   

   
           
   

    @pyqtSlot(int)
    def on_tabWidget_currentChanged(self, index: int):
        """标签页切换"""
        self.tabWidget_currentChanged.emit()

    @pyqtSlot(int)
    def on_tabWidget_tabCloseRequested(self, index: int):
        """关闭标签页请求"""
        self.currentTab().plc_mgr.stop_thread()
        self.currentTab().data_broker.stop_data_polling()
        self._existed_ips.remove(self.currentTab().plc_mgr.ip)
        self.tab_widget.removeTab(index)
      

    def closeEvent(self, event: QCloseEvent):
        """关闭事件"""
        if self._name in TabbedPlcWidget._instances:
            del TabbedPlcWidget._instances[self._name]
        super().closeEvent(event)
    
    
    
 

   
