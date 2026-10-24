



from PyQt6.QtWidgets import QApplication,QWidget, QListWidget, QMessageBox, QFrame, QDialog, QToolButton,QVBoxLayout,QHBoxLayout,QLabel,QListWidgetItem
from PyQt6.QtGui import QIcon,QAction,QColor
from PyQt6.QtCore import Qt, QObject, QEvent ,pyqtSignal
from .myQuadTreeScene import QuadTreeScene,SceneManager
from .my_elements import group_element,text_element

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple
from .rack_store_model import RackStoreModel


class RackStoresWindow(QWidget):
        
    def __init__(self, parent = None):
        super().__init__(parent)

        self.Scene = QuadTreeScene(parent=self)
       
        self.SceneManager = SceneManager(self.Scene, parent=self)
        self.Scene.set_scene_manager(self.SceneManager)
        self.Scene.load_element_info2()
        # self.Scene.goto_sence_origin()
        layout =QVBoxLayout(self)
        layout.addWidget(self.Scene)
        self.setLayout(layout)


        self.rack_store_model = RackStoreModel(self.SceneManager,self)

       

        group:group_element = self.SceneManager.findItem(self.SceneManager.m_name_items["料架1_仓位1"])
        self.rack_No:text_element = self.SceneManager.findItem(self.SceneManager.m_name_items["料架1_仓位1_编号"])
        # 场景只在运行态对“有事件绑定 / 开了 toggle / 标记为可交互”的组做点击命中，
        # 单纯 connect 信号不会被命中，所以这里显式打开交互标记。
        group.set_interactive(True)

        group.clicked.connect(self.on_click_rack_store)
        
    # def update_rack_store_display(self,datas):
    #     status=[]
    #     for data in datas:
    #         status.append(data)
    #     item_names = ('A库位空筒','A库位满料','B库位空筒','B库位满料','单库位空筒','单库位满料','双库托盘','单库托盘')
    #     for i in range(8):
    #         self.SceneManager.findItem(self.SceneManager.m_name_items[item_names[i]]).set_visibility(status[i])

    def on_click_rack_store(self):
      
        self.rack_No.set_color(QColor("#00FF00"))
        print(self.rack_store_model)