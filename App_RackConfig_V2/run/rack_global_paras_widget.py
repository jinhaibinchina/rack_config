from PySide6.QtWidgets import QApplication,QWidget, QListWidget, QMessageBox, QFrame, QDialog, QToolButton,QVBoxLayout,QHBoxLayout,QLabel,QListWidgetItem
from PySide6.QtGui import QIcon,QAction
from PySide6.QtCore import Qt, QObject, QEvent ,Signal
from Designer.Core.myQuadTreeScene import QuadTreeScene,SceneManager
from Designer.Core.my_common import SceneMode

from .rack_global_paras_model import RackGlobalParasModel

from common.com.snap7.snap7_plc_manager import PLCManager

class RackGlobalParasWindow(QWidget):
        
    def __init__(self, plc_mgr:PLCManager, parent = None):
        super().__init__(parent)

        self.Scene = QuadTreeScene(parent=self)
        self.Scene.set_scene_mode(SceneMode.Run)

        self.SceneManager = SceneManager(self.Scene, parent=self)
        self.Scene.set_scene_manager(self.SceneManager)
        self.Scene.load_element_info_run_mode('rack_requirements_scene3.json')
        # self.Scene.goto_sence_origin()
        self.Scene.set_canvas_navigation_enabled(False)
        
        self.rack_parameters_model = RackGlobalParasModel(plc_mgr,self.SceneManager, self)

        layout =QVBoxLayout(self)
        layout.addWidget(self.Scene)
        self.setLayout(layout)

    def apply_db41(self, db41: bytes):
        """解析 DB41 数据，更新图元显示。"""
        self.rack_parameters_model.apply_db41(db41)

