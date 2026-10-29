from __future__ import annotations
from PySide6.QtWidgets import (QApplication, QWidget,  QTabWidget, QVBoxLayout, QSizePolicy,
                            QHBoxLayout, QPushButton,  QMenu, QMessageBox, QDialog,QSpacerItem,
                            QInputDialog)
from PySide6.QtCore import Signal, Slot, Qt,QObject
from PySide6.QtGui import QCloseEvent,QIcon
from typing import Dict, Optional

from App_RackConfig.plc_window import ConfigWindow ,WindowContainer
from App_RackConfig.plc_manager import PLCManager
from App_RackConfig.data_broker import DataBroker


# 主窗口类
class TabbedPlcWidget(QWidget):
    # 静态实例映射
    # _instances: Dict[str, 'TabbedPlcWidget'] = {}
    
    # 信号定义
    
    sendTabToNewWindow = Signal(object)
    tabWidget_currentChanged = Signal()  #用于关闭播放器

 

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
        # else:
        #     return
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


  

   

 
  


    
   

          

    

   

   

   
   

   
           
   

    @Slot(int)
    def on_tabWidget_currentChanged(self, index: int):
        """标签页切换"""
        self.tabWidget_currentChanged.emit()

    @Slot(int)
    def on_tabWidget_tabCloseRequested(self, index: int):
        """关闭标签页请求。

        注意必须用 index 取被关闭的那个 tab，不能再用 currentTab()：
        点非当前标签的关闭按钮时，currentTab() 指向的是另一个页面，
        会导致该页面的 QThread 没被停掉（退出时报
        "QThread: Destroyed while thread is still running"），
        而当前页反而被误停。
        """
        widget = self.tab_widget.widget(index)
        if widget is None:
            return
        self._close_tab(widget)
        self.tab_widget.removeTab(index)

    def _close_tab(self, widget):
        """停止并释放某个标签页占用的线程与连接。"""
        shutdown = getattr(widget, "shutdown", None)
        if callable(shutdown):
            shutdown()
            plc_mgr = getattr(widget, "plc_mgr", None)
            if plc_mgr is not None:
                self._existed_ips.discard(plc_mgr.ip)
            return

        broker = getattr(widget, "data_broker", None)
        plc_mgr = getattr(widget, "plc_mgr", None)
        if broker is not None:
            broker.stop_data_polling()
        if plc_mgr is not None:
            plc_mgr.stop_thread()
            self._existed_ips.discard(plc_mgr.ip)

    def closeEvent(self, event: QCloseEvent):
        """关闭事件：先停掉所有标签页的后台线程，再让 Qt 销毁窗口。

        注意：这里不能再引用 self._name / TabbedPlcWidget._instances，
        它们在本类里已被注释掉；一旦引用会在 closeEvent 里抛 AttributeError，
        导致下面的线程清理逻辑根本执行不到，进而出现
        "QThread: Destroyed while thread is still running"。
        """
        self._stop_all_tabs()
        super().closeEvent(event)

    def _stop_all_tabs(self):
        """停止并移除所有标签页（线程安全退出）。"""
        if self.tab_widget is None:
            return
        for index in range(self.tab_widget.count() - 1, -1, -1):
            widget = self.tab_widget.widget(index)
            if widget is not None:
                self._close_tab(widget)
            self.tab_widget.removeTab(index)
    
    
    
 

   
