"""单页料仓显示窗口（CoreQGraphics 版）。

与旧 ``rack_store_widget.RackStoreWindow`` 同构：属性名（``Scene`` /
``SceneManager``）、方法（``update_rack_store_display``）都不变，只把后端换成
CoreQGraphics + 适配层。
"""

from typing import Optional

from PySide6.QtWidgets import QApplication,QWidget, QListWidget, QMessageBox, QFrame, QDialog, QToolButton,QVBoxLayout,QHBoxLayout,QLabel,QListWidgetItem
from PySide6.QtGui import QIcon,QAction
from PySide6.QtCore import Qt, QObject, QEvent ,Signal

from res.designer_resource_manager import resource_manager as res_mng
from .rack_scene_adapter import RackScene, RackSceneView, SceneManager

# DesignerV2 没有投影层，旧 AGV 口径的页面必须用 Native 版（投影已烘焙进数值），
# 由 tools/convert_page_to_native.py 生成；原文件 rack_config_scene1.json 未动。
SCENE_NAME = "rack_config_scene1.v2.json"


class RackStoreWindowV2(QWidget):

    def __init__(self, parent = None, *, scene_path: Optional[str] = None):
        super().__init__(parent)

        # 先 scene 后 view（视图构造要用场景定网格基准）；load_page → set_scene_mode
        self.scene = RackScene()
        self.view = RackSceneView(self.scene, self)
        self.view.on_viewport_resized = self.view.fit_scene

        self.scene_path = scene_path or res_mng.get_json_path(SCENE_NAME)
        self.load_error = ""
        self._load_scene()

        self.Scene = self.view                  # 兼容旧写法 layout.addWidget(self.Scene)
        self.SceneManager = SceneManager(self.scene, parent=self)

        layout =QVBoxLayout(self)
        layout.addWidget(self.view)
        self.setLayout(layout)

    def _load_scene(self) -> None:
        try:
            count = self.scene.load_page(self.scene_path)
        except Exception as exc:                       # noqa: BLE001
            self.load_error = f"场景载入失败：{exc}"
            print(f"[RackStoreWindowV2] {self.load_error}")
            return
        if not count:
            self.load_error = f"场景为空或文件缺失：{self.scene_path}"
            print(f"[RackStoreWindowV2] {self.load_error}")
            return
        self.scene.set_scene_mode(True)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.view.fit_scene()

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
