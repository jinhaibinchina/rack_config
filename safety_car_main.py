"""运行态宿主：加载 ``page_5`` (safetyCar) 并启动大小车安全 PLC 客户端。

本模块按 :mod:`modes.runtime.runtime_main` 的宿主结构重写了 ``main.py``：

* 通过 :class:`modes.design.project_store.ProjectStore` 解析 ``--page`` /
  ``--scene``，默认加载设计工程里的 ``page_5``
  (``data.json/datas/design/pages/page_5.json``，页面名 ``safetyCar``)；
* 场景切到 :class:`my_common.SceneMode` 的 ``Run`` 模式，只读取页面文件，
  不会把运行态布局回写到设计数据；
* 保留原客户端的 PLC 数据链路 ``PLCManager`` -> ``DataBroker`` ->
  ``plc_safety``，以及站点配置树、状态总览、站点说明面板；
* 新增 ``--no-plc`` 离线模式，没有 PLC 时也能查看场景。

运行方式::

    python safety_car_main.py
    python safety_car_main.py --no-plc
    python safety_car_main.py --plc-ip 192.168.3.231
    python safety_car_main.py --page page_5
    python safety_car_main.py --scene data.json/datas/design/pages/page_5.json

``main.py`` 保持原样（仍是旧版运行入口）。本模块是独立的运行态入口，配套的
打包配置是同目录下的 ``safety_car_main.spec``（会额外把 ``data.json`` 设计工程
打进包内，见 :func:`_project_store`）：::

    pyinstaller safety_car_main.spec
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from typing import Optional, Sequence, Tuple

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import App_SafetyCar.global_variables as gv
from Designer.Core.NavigationContentWidget import NavigationContentWidget
from App_SafetyCar.ip_setup import ip_setup_window

from Designer.modes.design.project_store import ProjectStore
from Designer.Core.my_common import SceneMode
from App_SafetyCar.my_data_broker import DataBroker
from App_SafetyCar.my_modbus import get_bool, set_bool
from App_SafetyCar.my_plc_manager import PLCManager
from App_SafetyCar.my_plc_safety import Ui_safety_display, int_to_hex, plc_safety
from Designer.Core.myQuadTreeScene import QuadTreeScene, SceneManager
from App_SafetyCar.parames_set_ui import Ui_Dialog as Ui_parames_set
from App_SafetyCar.station_status_query_ui import Ui_Dialog as Ui_station_status_query
from res.app_safety_car_resource_manager import resource_manager as res_manager

DEFAULT_PLC_IP = "192.168.3.231"
APP_TITLE = "大小车安全PLC客户端V3.1.0"

__all__ = [
    "APP_TITLE",
    "DEFAULT_PLC_IP",
    "SafetyCarWindow",
    "get_resource_path",
    "main",
    "page_display_name",
    "resolve_scene_path",
    "safety_paramsters",
    "station_status_query",
]


class safety_paramsters(QDialog):
    """安全参数设置对话框（对应 ``parames_set_ui``）。"""

    def __init__(self, parent=None, data_broker: Optional[DataBroker] = None):
        super().__init__(parent)
        self.ui = Ui_parames_set()
        self.ui.setupUi(self)
        self.data_broker = data_broker

        if self.data_broker is None:
            # 离线模式（--no-plc）下只能查看界面，禁止写入。
            self.ui.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
            self.setToolTip("未连接 PLC，参数不可修改")
            return

        data = self.data_broker.read_config_parameters_2()
        if data is None:
            return

        self.ui.checkBox_enable_fire_signal.setChecked(get_bool(data, 0, 0))
        self.ui.checkBox_ask_bf_open_door.setChecked(get_bool(data, 0, 1))
        self.ui.checkBox_enable_estop_ext.setChecked(get_bool(data, 0, 2))
        self.ui.checkBox_disable_buzzer.setChecked(get_bool(data, 0, 3))
        self.ui.checkBox_disable_worktable_canbit.setChecked(get_bool(data, 0, 4))

    def accept(self):
        if self.data_broker is None:
            return super().reject()

        data = [0, 1]
        set_bool(data, 0, 0, self.ui.checkBox_enable_fire_signal.isChecked())
        set_bool(data, 0, 1, self.ui.checkBox_ask_bf_open_door.isChecked())
        set_bool(data, 0, 2, self.ui.checkBox_enable_estop_ext.isChecked())
        set_bool(data, 0, 3, self.ui.checkBox_disable_buzzer.isChecked())
        set_bool(data, 0, 4, self.ui.checkBox_disable_worktable_canbit.isChecked())
        self.data_broker.write_config_parameters_2(data)
        return super().accept()


class station_status_query(QDialog):
    """设备状态查询对话框（对应 ``station_status_query_ui``）。"""

    @staticmethod
    def extract_bits(value: int, start_bit: int, end_bit: int) -> int:
        """从 16 位整数中提取指定位范围的数值。"""
        if not (0 <= value <= 0xFFFF):
            raise ValueError("输入值必须是16位整数 (0-65535)")

        if not (0 <= start_bit <= 15 and 0 <= end_bit <= 15):
            raise ValueError("位索引必须在0-15范围内")

        if start_bit > end_bit:
            raise ValueError("起始位不能大于结束位")

        mask = (1 << (end_bit - start_bit + 1)) - 1
        return (value >> start_bit) & mask

    def __init__(self, parent=None, data_broker: Optional[DataBroker] = None):
        super().__init__(parent)
        self.ui = Ui_station_status_query()
        self.ui.setupUi(self)
        self.data_broker = data_broker

        self.station_status_dic = {
            "0x1000": "启动",
            "0x2000": "停止",
            "0x3000": "正在连接",
            "0x4000": "正在运行",
            "0x5000": "正在关闭",
            "0x6000": "禁用",
            "0x7000": "正在等待",
            "0x9000": "正在进行固件更新",
            "0xa000": "正在配置",
        }

        if self.data_broker is None:
            self.ui.comboBox_station_select.setEnabled(False)
            self.setToolTip("未连接 PLC，无法查询站点状态")
            return

        self.ui.comboBox_station_select.currentIndexChanged.connect(self.handle_station_change)

    def handle_data_broker(self, data_packet: Tuple):
        if self.data_broker is None:
            return

        name, data = data_packet
        if name != "查询状态":
            return

        plc_data = data[0]
        device_status = station_status_query.extract_bits(plc_data, 4, 7)
        device_fault = station_status_query.extract_bits(plc_data, 8, 11)
        controller_mode = station_status_query.extract_bits(plc_data, 12, 13)
        controller_status = station_status_query.extract_bits(plc_data, 14, 15)

        self.ui.label_PLC_status.setText(
            ("保留", "正在进行闪存更新", "保留", "保留", "闪存状况不良", "故障模式", "运行", "编程")[device_status]
        )
        self.ui.label_PLC_fault_status.setText(
            ("保留", "可恢复的轻微故障", "不可恢复的轻微故障", "可恢复的严重故障", "不可恢复的严重故障")[device_fault]
        )
        self.ui.label_controller_mode.setText(
            ("保留", "钥匙开关处于运行模式", "钥匙开关处于编程模式", "钥匙开关处于远程模式")[controller_mode]
        )
        self.ui.label_controller_status.setText(
            ("保留", "控制器正在切换模式", "调试模式（控制器处于运行模式时")[controller_status]
        )

        if data[5] == 0:
            self.ui.label_status.setText("")
            self.ui.label_errcode.setText("")
            self.ui.label_errinfo.setText("")
            return

        status = self.station_status_dic.get(hex(data[1]), "未知")
        self.ui.label_status.setText(status)
        self.ui.label_errcode.setText("16#" + int_to_hex(data[2], 4))
        self.ui.label_errinfo.setText("16#" + int_to_hex(data[3] << 16 + data[4], 8))

    def handle_station_change(self, station_index: int):
        if self.data_broker is None:
            return
        self.data_broker.plc_manager.write_data(215, station_index)

    def closeEvent(self, arg__1):
        if self.data_broker is not None:
            self.data_broker.enable_station_query(False)
            self.data_broker.plc_manager.write_data(215, 0)
        return super().closeEvent(arg__1)


class SafetyCarWindow(QMainWindow):
    """运行态主窗口：``page_5`` 场景 + 大小车安全 PLC 数据展示。"""

    def __init__(
        self,
        *,
        
        plc_ip: str = DEFAULT_PLC_IP,
        enable_plc: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        
        self.plc_ip = plc_ip
        self.enable_plc = enable_plc

        self.data_broker: Optional[DataBroker] = None
        self.plc_manager: Optional[PLCManager] = None
        self.property_dock: Optional[QDockWidget] = None
        self.update_timer: Optional[QTimer] = None
        self._shutting_down = False

        self.setObjectName("safetyCarWindow")
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 800)
        self.status_bar = self.setup_status_bar()

        # 站点配置树会把树节点写回 father_roots，因此先创建 plc_safety。
        self.plc_safety = plc_safety(self)

        self.setup_ui()
        self.setup_styles()
        self._setup_plc()
        self._start_ui_update()

        # 等窗口完成第一次布局后再恢复页面保存的视图范围。
        QTimer.singleShot(0, self._restore_view)

    # ------------------------------------------------------------------
    # 键盘事件：未获得焦点的按键下沉给场景，保持原客户端的快捷键行为
    # ------------------------------------------------------------------
    def keyPressEvent(self, event):
        self.scene.keyPressEvent(event)

    def keyReleaseEvent(self, event):
        self.scene.keyReleaseEvent(event)

    # ------------------------------------------------------------------
    # 界面搭建
    # ------------------------------------------------------------------
    def setup_ui(self):
        self.create_menubar()
        self.create_toolbar()
        self.create_project_dock()
        self.create_tool_dock()
        self.create_scene_area()
        self.create_property_dock()

        # 底部左右两角留给左右停靠区，保证站点说明面板占满中间宽度。
        self.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)
        self.resizeDocks([self.project_dock, self.tool_dock], [200, 200], Qt.Horizontal)

        # 场景选中变化 -> 安全点位联动 + 站点说明面板
        self.scene.selectionChanged.connect(self.plc_safety.handle_selectionChanged)
        self.scene.selectionChanged.connect(self.update_property_area)
        if hasattr(self.plc_safety, "close_property_window"):
            self.plc_safety.close_property_window.connect(self.handle_close)

        self.property_dock.setVisible(False)

    def create_toolbar(self):
        toolbar = self.addToolBar("快捷工具")
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)

        actions = [
            ("⬆ 上传站点配置", self.read_station_config),
            ("⬇ 下载站点配置", self.write_station_config),
            ("设置ip", self.open_ip_window),
            ("设置参数", self.open_parameters_window),
            ("设备状态查询", self.open_station_status_query_window),
            ("调整视图", self.reset_view),
        ]

        for text, handler in actions:
            action = QAction(text, self)
            action.triggered.connect(lambda _checked=False, func=handler: func())
            toolbar.addAction(action)

    def create_menubar(self):
        menubar = self.menuBar()

        user_menu = menubar.addMenu("用户(&F)")
        self.login_action = QAction("登入", self)
        self.login_action.setEnabled(False)
        self.login_action.setToolTip("登录功能尚未启用")
        user_menu.addAction(self.login_action)

        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close)
        user_menu.addAction(quit_action)

        window_menu = menubar.addMenu("窗口(&W)")

        self.toggle_prop_action = QAction("站点说明", self)
        self.toggle_prop_action.setCheckable(True)
        self.toggle_prop_action.toggled.connect(self.toggle_property_area)
        window_menu.addAction(self.toggle_prop_action)

        self.toggle_proj_action = QAction("站点配置", self)
        self.toggle_proj_action.setCheckable(True)
        self.toggle_proj_action.setChecked(True)
        self.toggle_proj_action.toggled.connect(self.toggle_project_area)
        window_menu.addAction(self.toggle_proj_action)

        self.toggle_tool_action = QAction("状态总览", self)
        self.toggle_tool_action.setCheckable(True)
        self.toggle_tool_action.setChecked(True)
        self.toggle_tool_action.toggled.connect(self.toggle_tool_area)
        window_menu.addAction(self.toggle_tool_action)

        help_menu = menubar.addMenu("帮助(&H)")
        helper_action = QAction("项目实施指导", self)
        helper_action.triggered.connect(self.on_click_open_helper_window)
        help_menu.addAction(helper_action)


    def create_project_dock(self):
        """站点配置树：根节点对应 ``plc_safety.child_roots``，PLC2 单列。"""
        self.project_dock = QDockWidget("站点配置(如采用拨码方式默认192.168.1网段)", self)
        self.project_dock.setObjectName("project_dock")
        self.project_dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetFloatable
        )
        self.project_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.project_dock.setMinimumWidth(150)

        project_container = QWidget()
        project_layout = QVBoxLayout(project_container)
        project_layout.setContentsMargins(0, 0, 0, 0)

        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setColumnCount(1)

        for root_name, root_value in self.plc_safety.child_roots.items():
            root = QTreeWidgetItem(self.tree_widget)
            root.setText(0, root_name)
            root.setCheckState(0, Qt.Unchecked)
            self.plc_safety.father_roots[root_name] = root

            # root_value 的值最终会被替换成子节点本身，便于回查勾选状态。
            for child_name, _ in root_value.items():
                child = QTreeWidgetItem(root)
                child.setText(0, child_name)
                child.setCheckState(0, Qt.Unchecked)
                root_value[child_name] = child

        plc2_root = QTreeWidgetItem(self.tree_widget)
        plc2_root.setText(0, "PLC2")
        plc2_root.setCheckState(0, Qt.Unchecked)
        self.plc_safety.father_roots["PLC2"] = plc2_root

        self.tree_widget.itemClicked.connect(self.plc_safety.on_item_clicked)
        self.tree_widget.itemChanged.connect(self.plc_safety.on_item_changed)

        project_layout.addWidget(self.tree_widget)
        self.project_dock.setWidget(project_container)
        self.project_dock.visibilityChanged.connect(self.on_proj_visibility_changed)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.project_dock)

    def create_tool_dock(self):
        """状态总览面板，由 ``Ui_safety_display`` 渲染 PLC 汇总信息。"""
        self.tool_dock = QDockWidget("状态总览", self)
        self.tool_dock.setObjectName("tool_dock")
        self.tool_dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetFloatable
        )
        self.tool_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.tool_dock.setMinimumWidth(150)

        tool_container = QWidget()
        tool_layout = QVBoxLayout(tool_container)
        tool_layout.setContentsMargins(0, 0, 0, 0)

        self.tool_area_widget = Ui_safety_display(self)
        tool_layout.addWidget(self.tool_area_widget)

        self.tool_dock.setWidget(tool_container)
        self.tool_dock.visibilityChanged.connect(self.on_tool_visibility_changed)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tool_dock)

        self.tool_area_widget.safety_internal_info.connect(self.plc_safety.show_safety_internal_ip)


    def create_scene_area(self):
        """中央场景区：读取 ``page_5`` 并切到运行模式。"""
        self.central_container = QWidget()
        self.central_container.setObjectName("central_container")
        self.setCentralWidget(self.central_container)

        self.central_layout = QVBoxLayout(self.central_container)
        self.central_layout.setContentsMargins(0, 0, 0, 0)
        self.central_layout.setSpacing(0)

        self.scene_frame = QFrame()
        self.scene_frame.setObjectName("scene_frame")
        self.scene_layout_inner = QVBoxLayout(self.scene_frame)
        self.scene_layout_inner.setContentsMargins(0, 0, 0, 0)
        self.scene_layout_inner.setSpacing(0)

        self.scene = QuadTreeScene(parent=self)
        self.scene.setObjectName("safetyCarScene")
        self.scene_manager = SceneManager(self.scene, parent=self)
        self.scene.set_scene_manager(self.scene_manager)

        self.plc_safety.set_scene_manager(self.scene_manager)
        self.plc_safety.set_scene(self.scene)
        # 该信号既承载模式切换(SceneMode)，也承载子站点切换(str)，见回调。
        self.scene.run_mode_station_change.connect(self._on_run_mode_station_change)

        # 只读加载页面文件；运行态布局改动不会写回设计数据。
        self.scene.load_element_info_run_mode('safety_car_scene.json')
        if self.scene.mode() != SceneMode.Run:
            self.scene.toggle_sence_mode()
        self.plc_safety.on_item_changed()

        # 未连接 PLC 前不注册渲染回调，避免访问空的 data_broker。
        self.scene.update_callback = None

        self.scene_layout_inner.addWidget(self.scene)
        self.central_layout.addWidget(self.scene_frame)

    def create_property_dock(self):
        """站点说明面板，内容由 ``NavigationContentWidget`` 按选中项生成。"""
        self.property_dock = QDockWidget("站点说明", self)
        self.property_dock.setObjectName("property_dock")
        self.property_dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetClosable
            | QDockWidget.DockWidgetFloatable
        )
        self.property_dock.setAllowedAreas(Qt.BottomDockWidgetArea)

        self.property_container = NavigationContentWidget(scene=self.scene)
        self.property_container.setObjectName("property_container")

        content = QWidget()
        content.setObjectName("property_dock_content")
        property_layout = QVBoxLayout(content)
        property_layout.setContentsMargins(0, 0, 0, 0)
        property_layout.setSpacing(0)

        property_header = QWidget()
        property_header.setObjectName("property_header")
        property_header.setFixedHeight(25)
        property_header_layout = QHBoxLayout(property_header)
        property_header_layout.setContentsMargins(5, 0, 5, 0)

        title_label = QLabel("属性设置区")
        title_label.setStyleSheet("font-weight: bold;")
        property_header_layout.addWidget(title_label)
        property_header_layout.addStretch()

        self.close_button = QToolButton()
        self.close_button.setIcon(self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        self.close_button.setFixedSize(20, 20)
        self.close_button.setToolTip("关闭属性区")
        self.close_button.clicked.connect(self.handle_close)
        property_header_layout.addWidget(self.close_button)

        property_layout.addWidget(property_header)
        property_layout.addWidget(self.property_container, 1)

        self.property_dock.setWidget(content)
        self.property_dock.visibilityChanged.connect(self.on_property_visibility_changed)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.property_dock)


    # ------------------------------------------------------------------
    # PLC 数据链路
    # ------------------------------------------------------------------
    def _setup_plc(self):
        """建立 PLC 连接、数据轮询并注册场景渲染回调。"""
        if not self.enable_plc:
            self.status_bar.showMessage("离线模式：未连接 PLC（--no-plc）")
            return

        self.plc_manager = PLCManager(self, self.plc_ip)
        self.data_broker = DataBroker(self, self.plc_manager)

        self.plc_safety.set_data_broker(self.data_broker)
        self.tool_area_widget.set_data_broker(self.data_broker)
        self.plc_safety.params_read_done.connect(self.tool_area_widget.handle_read_station_config)
        self.plc_safety.params_write_done.connect(self.tool_area_widget.handle_write_station_config)

        # 连接失败时心跳线程会持续重连，这里不阻塞界面启动。
        connected = self.plc_manager.connect_to_plc()
        self.plc_manager.start_heartbeat()
        self.data_broker.start_data_polling()

        self.scene.update_callback = self.plc_safety.update_items_data

        if connected:
            self.status_bar.showMessage(f"PLC({self.plc_ip}) 已连接")
        else:
            self.status_bar.showMessage(f"PLC({self.plc_ip}) 连接失败，后台自动重连…")

    def _warn_no_plc(self):
        QMessageBox.information(
            self,
            "未连接 PLC",
            "当前为离线模式（--no-plc），该操作需要连接 PLC 后使用。",
        )

    def read_station_config(self):
        """⬆ 上传站点配置：从 PLC 读取站点参数。"""
        if self.data_broker is None:
            self._warn_no_plc()
            return
        self.plc_safety.read_config_from_plc()

    def write_station_config(self):
        """⬇ 下载站点配置：把当前站点参数写入 PLC。"""
        if self.data_broker is None:
            self._warn_no_plc()
            return

        reply = QMessageBox.question(
            self,
            "确认操作",
            "确定要执行此操作吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.plc_safety.write_config_to_plc()

    def reset_view(self):
        """调整视图：恢复页面记录的视图范围，缺失时回到坐标原点。"""
        if not self.scene.restore_saved_view():
            self.scene.goto_sence_origin()

    def open_ip_window(self):
        if self.data_broker is None:
            self._warn_no_plc()
            return
        top_window = ip_setup_window(self.data_broker)
        top_window.exec()

    def open_parameters_window(self):
        top_window = safety_paramsters(self, self.data_broker)
        top_window.exec()

    def open_station_status_query_window(self):
        if self.data_broker is None:
            self._warn_no_plc()
            return
        top_window = station_status_query(self, self.data_broker)
        self.data_broker.device_query_data_ready.connect(top_window.handle_data_broker)
        self.data_broker.enable_station_query(True)
        top_window.exec()

    def on_click_open_helper_window(self):
        # top_window = helper_window(self)
        # top_window.exec()
        pass

    def _on_run_mode_station_change(self, value):
        """``run_mode_station_change`` 同时承载模式切换与子站点切换。

        - :class:`my_common.SceneMode` 载荷由 ``plc_safety`` 内部
          ``handle_scene_mode_change`` 处理（设置根节点可选）；
        - ``str`` 载荷（如 ``shangjia_station1``）交给
          ``plc_safety.handle_station_change`` 切换子站点图元。
        """
        if isinstance(value, str):
            self.plc_safety.handle_station_change(value)

    def _restore_view(self):
        """恢复页面保存的视图范围（page_5 的 sceneRect）。"""
        try:
            if not self.scene.restore_saved_view(True):
                self.scene.goto_sence_origin()
        except RuntimeError:
            # 窗口在动画过程中被关闭时场景可能已失效。
            pass


    # ------------------------------------------------------------------
    # 面板联动
    # ------------------------------------------------------------------
    def update_property_area(self):
        """场景选择变化时刷新站点说明面板。"""
        selected_item = self.scene.current_selected
        if not selected_item:
            return

        if not self.property_dock.isVisible():
            self.property_dock.show()

        self.property_container.update_for_selected(selected_item)

    def toggle_property_area(self, visible):
        self.property_dock.setVisible(visible)

    def toggle_project_area(self, visible):
        self.project_dock.setVisible(visible)

    def toggle_tool_area(self, visible):
        self.tool_dock.setVisible(visible)

    def on_property_visibility_changed(self, visible):
        self.toggle_prop_action.setChecked(visible)

    def on_proj_visibility_changed(self, visible):
        if not visible:
            self.toggle_proj_action.setChecked(False)

    def on_tool_visibility_changed(self, visible):
        if not visible:
            self.toggle_tool_action.setChecked(False)

    def handle_close(self):
        """关闭站点说明面板。"""
        self.property_dock.setVisible(False)

    # ------------------------------------------------------------------
    # 状态栏
    # ------------------------------------------------------------------
    def setup_status_bar(self):
        status_bar = self.statusBar()
        status_bar.showMessage("Not connected")
        status_bar.setFixedHeight(25)

        
        return status_bar

    def _start_ui_update(self):
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._update_status)
        self.update_timer.start(500)

    def _update_status(self):
        if not self.status_bar:
            return

        if self.data_broker is None:
            self.status_bar.showMessage("离线模式 · 未连接 PLC")
            return

        manager = self.data_broker.plc_manager
        self.status_bar.showMessage(
            f"PLC({manager.get_ip_address()}) "
            f"{'已连接' if manager.connected else '已断开'}"
            f"                用户：{'未登入' if gv.g_is_logged_in == False else 'admin已登入'}"
        )


    # ------------------------------------------------------------------
    # 样式
    # ------------------------------------------------------------------
    def setup_styles(self):
        self.setStyleSheet(
            """
            /* 主窗口样式 */
            QMainWindow {
                background-color: #F0F0F0;
                border: 1px solid #00008B;
            }

            /* 菜单栏样式 */
            QMenuBar {
                background-color: #ADD8E6;  /* 浅蓝色 */
                border-bottom: 1px solid #00008B;  /* 深蓝色边框 */
                padding: 4px 0;  /* 减少垂直内边距 */
                font-size: 12px;  /* 增大字体 */
            }

            /* 项目区、工具区和属性区DockWidget样式 */
            #project_dock, #tool_dock, #property_dock {
                border: 1px solid #A0A0A0;
                background: #E0E0E0;
                padding: 0px;
                margin: 0px;
            }

            /* DockWidget标题栏样式 */
            QDockWidget::title {
                background: #D0D0D0;
                border-bottom: 1px solid #A0A0A0;
                padding: 3px;
                text-align: center;
            }

            /* 中央场景区样式 */
            #central_container {
                background: #FFFFFF;
                border: 1px solid #A0A0A0;
            }

            /* 场景区框架样式 */
            #scene_frame {
                background: #FFFFFF;
                border: none;
            }

            /* 属性区容器样式 */
            #property_dock_content, #property_container {
                border: none;
                padding: 0px;
                margin: 0px;
                background: #F0F0F0;
            }

            /* 属性区标题栏样式 */
            #property_header {
                background: #D0D0E0;
                border-bottom: 1px solid #A0A0A0;
            }

            /* 工具按钮样式 */
            QToolButton {
                background: #e0e0e0;
                border: 1px solid #a0a0a0;
                border-radius: 1px;
                padding: 2px 2px;
            }

            QToolButton:hover {
                background: #d0d0ff;
            }

            /* 状态栏样式 */
            QStatusBar {
                background: #00008B;
                border-top: 1px solid #C0C0C0;
                color: white;
                font-size: 12px;
            }

            /* 属性区停靠区域样式 */
            QMainWindow::separator {
                background: #C0C0C0;
                width: 4px;
                height: 4px;
            }
        """
        )


    # ------------------------------------------------------------------
    # 退出清理
    # ------------------------------------------------------------------
    def shutdown(self):
        """停止定时器、数据轮询并断开 PLC。"""
        if self._shutting_down:
            return
        self._shutting_down = True

        if self.update_timer is not None:
            self.update_timer.stop()
            self.update_timer = None

        scene = getattr(self, "scene", None)
        if scene is not None:
            scene.update_callback = None
            for timer_name in ("render_timer", "frame_count_timer", "timer1", "timer2"):
                timer = getattr(scene, timer_name, None)
                if timer is not None:
                    timer.stop()

        if self.data_broker is not None:
            self.data_broker.stop_data_polling()

        if self.plc_manager is not None:
            # 先停心跳/重连线程，再断开连接，避免退出时 QThread 仍在运行
            if not self.plc_manager.stop_heartbeat():
                print("[运行态] 心跳线程未能及时退出", file=sys.stderr)
            self.plc_manager.disconnect()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)






def main(argv: Optional[Sequence[str]] = None) -> int:
    

    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
    app.setApplicationName("安全车配置运行态")
    app.setOrganizationName("SafetyCarConfig")
    app.setApplicationDisplayName(APP_TITLE)

    icon_path = res_manager.get_icon_path("app_icon.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    try:
        
        window = SafetyCarWindow(
            
            plc_ip='192.168.1.150',
            enable_plc=True,
        )
    except Exception as exc:  # noqa: BLE001 - 启动失败要给出可读提示
        traceback.print_exc()
        print(f"[运行态] 启动失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        if owns_app:
            QMessageBox.critical(
                None,
                "运行态启动失败",
                f"{type(exc).__name__}: {exc}\n\n请检查 --scene / --page 参数。",
            )
        return 2

    window.show()
   
    print(
        "PLC: " + ("未连接（离线模式）" if not window.enable_plc else window.plc_ip),
        flush=True,
    )

    if owns_app:
        return app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
