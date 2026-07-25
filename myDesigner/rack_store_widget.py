



from PyQt6.QtWidgets import QApplication,QWidget, QListWidget, QMessageBox, QFrame, QDialog, QToolButton,QVBoxLayout,QHBoxLayout,QLabel,QListWidgetItem
from PyQt6.QtGui import QIcon,QAction
from PyQt6.QtCore import Qt, QObject, QEvent ,pyqtSignal
from .myQuadTreeScene import QuadTreeScene,SceneManager






class RackStoreWindow(QWidget):
        
    def __init__(self, parent = None):
        super().__init__(parent)

        self.Scene = QuadTreeScene(parent=self)
       
        self.SceneManager = SceneManager(self.Scene, parent=self)
        self.Scene.set_scene_manager(self.SceneManager)
        self.Scene.load_element_info()
        # self.Scene.goto_sence_origin()
        layout =QVBoxLayout(self)
        layout.addWidget(self.Scene)
        self.setLayout(layout)

    def update_rack_store_display(self,datas):
        status=[]
        for data in datas:
            status.append(data)
        item_names = ('A库位空筒','A库位满料','B库位空筒','B库位满料','单库位空筒','单库位满料','双库托盘','单库托盘')
        for i in range(8):
            self.SceneManager.findItem(self.SceneManager.m_name_items[item_names[i]]).set_visibility(status[i])

        