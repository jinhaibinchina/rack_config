



from PySide6.QtWidgets import QApplication,QWidget, QListWidget, QMessageBox, QFrame, QDialog, QToolButton,QVBoxLayout,QHBoxLayout,QLabel,QListWidgetItem
from PySide6.QtGui import QIcon,QAction
from PySide6.QtCore import Qt, QObject, QEvent ,Signal
from Designer.Core.myQuadTreeScene import QuadTreeScene,SceneManager
from Designer.Core.my_common import SceneMode





class RackStoreWindow(QWidget):
        
    def __init__(self, parent = None):
        super().__init__(parent)

        self.Scene = QuadTreeScene(parent=self)
        self.Scene.set_scene_mode(SceneMode.Run)

        self.SceneManager = SceneManager(self.Scene, parent=self)
        self.Scene.set_scene_manager(self.SceneManager)
        self.Scene.load_element_info_run_mode('rack_config_scene1.json')
        # self.Scene.goto_sence_origin()
        layout =QVBoxLayout(self)
        layout.addWidget(self.Scene)
        self.setLayout(layout)

    def update_rack_store_display(self,datas):
        """按 8 个状态位刷新这一页的料仓显示。

        图元是按名字找的，场景没加载到时（比如打包漏了 data.json）找回来是 None，
        逐个跳过即可 —— 否则 PLC 每帧回调都会抛一次 KeyError 把控制台刷满。
        """
        status = list(datas)
        item_names = ('A库位空筒','A库位满料','B库位空筒','B库位满料','单库位空筒','单库位满料','双库托盘','单库托盘')
        for i, name in enumerate(item_names):
            item = self.SceneManager.findItemByName(name)
            if item is None:
                continue
            item.set_visibility(bool(status[i]) if i < len(status) else False)

        