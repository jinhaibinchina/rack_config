import os
import sys
import socket
import json
import time

import traceback
from typing import Optional, Sequence, Tuple
# matplotlib 的 Qt 后端会按 PyQt6 → PyQt5 → PySide6 的顺序自动挑绑定，
# 机器上装了 PyQt 时会抢到 PyQt 上，跟本项目的 PySide6 混用会崩。
# 必须在任何 matplotlib 导入之前钉死（App_LogPlot/app/plot_moudle/__init__.py
# 里也做了同样的兜底）。
os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtWidgets import QApplication,QMainWindow, QFileDialog, QMessageBox, QProgressDialog, QDialog,QScrollArea
# Qt6 起 QAction 在 QtGui 下（PyQt5 时代在 QtWidgets）
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import Qt, QObject, QEvent

# 注意：下面这些绘图相关模块在 import 时就会拉起 matplotlib 的 Qt 后端，
# 而那个后端会顺手创建一个 QApplication 单例；单例一旦存在，后面再创建
# App（QApplication 子类）就会报 "Please destroy the QApplication singleton"。
# 所以这里不能放在模块顶层，统一延迟到 MainWidget.__init__ 里导入，
# 保证 __main__ 里先建好 App。
# from App_LogPlot.app.rcd_log_importer import RcdLogImporter
# from App_LogPlot.app.rcd_tr import RcdTr
# from App_LogPlot.app.agv_log_parser import AGVLogParser
# from App_LogPlot.app.cset_parser import CSetParser
# from App_LogPlot.app.plot_moudle import plot_window,rcd_data_bridge,LogDataGenerator



APP_TITLE = "日志分析工具"
VERSION = "V1.0.0"
VERSION_INFO = f"版本:{VERSION}\n1、初版"


class MainWidget(QMainWindow):
    def __init__(self,parent=None):
        super().__init__(parent)
        # 延迟导入（原因见文件头注释）：必须在 QApplication 建好之后才能碰绘图模块
        from App_LogPlot.app.rcd_log_importer import RcdLogImporter
        from App_LogPlot.app.rcd_tr import RcdTr
        from App_LogPlot.app.agv_log_parser import AGVLogParser
        from App_LogPlot.app.cset_parser import CSetParser
        from App_LogPlot.app.plot_moudle import plot_window, rcd_data_bridge, LogDataGenerator

        # self.setWindowIcon(QIcon('ico/box_1.ico'))  # 设置图标
        self.setWindowTitle(f"日志解析工具 {VERSION}")
        self.setGeometry(100, 100, 1200, 800)

        
        self.rcd_log_importer = RcdLogImporter()
        self.agv_log_parser = AGVLogParser()
        self.cset_parser  = CSetParser()
        self.rcd_tr = RcdTr()

        # 绘图模块相关  -------------------------------------------------------------------------------------------
        self.log_generator = LogDataGenerator("日志数据生成器",self.rcd_log_importer)
        data_bridge = rcd_data_bridge("数据中转器")
        self.log_generator.add_observer(data_bridge.on_data_ready)
        self.plot_widget = plot_window(data_bridge,self.rcd_tr)
        self.plot_widget.off_row_data_read.connect(self.rcd_log_importer.slot_clear_read_feather)
        self.plot_widget.on_off_row_data_read.connect(lambda e: self.rcd_log_importer.slot_on_off_row_data_read(e))
        self.setContentsMargins(0, 0, 0, 0)
      
        self.setCentralWidget(self.plot_widget)
        #---------------------------------------------------------------------------------------------------------

        self._createMenu()


    def _createMenu(self):
        """创建菜单。

        导入类动作属于「文件」，「关于」才是「帮助」。之前三个动作全塞在
        「帮助」里，而且 about -> 导入文件、导入文件 -> 版本说明，槽是错位的。
        """
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")
        import_folder_action = QAction("导入文件夹", self)
        import_file_action = QAction("导入文件", self)
        import_folder_action.triggered.connect(
            lambda: self.slot_import_log_by_folder(self.get_path_by_folder_dialog())
        )
        import_file_action.triggered.connect(
            lambda: self.slot_import_log(self.get_files_by_file_dialog())
        )
        file_menu.addAction(import_folder_action)
        file_menu.addAction(import_file_action)

        help_menu = menubar.addMenu("帮助")
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.slot_version_btn)
        help_menu.addAction(about_action)
    
    


    def slot_import_log_by_folder(self, folder_path, rcd_impoort_en = True):
        """导入agv和cset日志并解析"""
        if folder_path is None or len(folder_path) == 0:
            return
        # 界面显示
        progress_dialog = QProgressDialog()
        progress_dialog.setFixedSize(250, 100)  # 设置弹窗大小
        progress_dialog.setWindowModality(Qt.ApplicationModal)  # 设置为模态窗口
        progress_dialog.setWindowTitle("日志导入")
        progress_dialog.setLabelText("日志导入中...")
        progress_dialog.setRange(0, 0)
        progress_dialog.show()  # 立即显示进度条对话框
        # 隐藏取消按钮
        progress_dialog.setCancelButton(None)
        # 用于跟踪导入是否完成
        import_finished = [False]
        import_success = [False]
        def import_result_show(success: bool):
            """处理导入结果"""
            # todo 解压过程会自动导入，有可能导入完成信号量先发送，导致进度条无法关闭，需要进一步优化
            import_success[0] = success
            import_finished[0] = True

        # 连接导入完成信号
        self.rcd_log_importer.logs_imported.connect(import_result_show)
        
        # 手动导入rcd,解压自带导入则不再重新导入rcd
        if rcd_impoort_en:
            self.rcd_log_importer.import_logs_async(folder_path)
        self.agv_log_parser.parse_log_folder(folder_path)
        software_id = self.agv_log_parser.get_software_id()
        car_type = self.agv_log_parser.get_car_type()
        self.cset_parser.parse_log_folder(folder_path, software_id=software_id)
        self.rcd_tr.parse_tr_json(car_type)
        act_name_map = self.cset_parser.get_actuator_mapping()
        self.rcd_tr.set_act_name_map(act_name_map)


        # 等待导入完成
        while not import_finished[0]:
            QApplication.instance().processEvents()  # 处理事件队列
            time.sleep(0.1)
            
        # 断开信号连接
        self.rcd_log_importer.logs_imported.disconnect(import_result_show)
        progress_dialog.close()
        # 显示结果提示
        if import_success[0]:          
            QMessageBox.information(self, '日志导入', '导入完成')
        else:
            QMessageBox.warning(self, '日志导入失败', '导入过程中出现错误')


    def slot_import_log(self, files_path):
        """导入指定文件列表的日志"""
        if files_path is None or len(files_path) == 0:
            return
            
        # 界面显示
        progress_dialog = QProgressDialog(self)
        progress_dialog.setFixedSize(250, 100)  # 设置弹窗大小
        progress_dialog.setWindowModality(Qt.ApplicationModal)  # 设置为模态窗口
        progress_dialog.setWindowTitle("日志导入")
        progress_dialog.setLabelText("日志导入中...")
        progress_dialog.setRange(0, 0)
        progress_dialog.show()  # 立即显示进度条对话框
        # 隐藏取消按钮
        progress_dialog.setCancelButton(None)
        # 用于跟踪导入是否完成
        import_finished = [False]
        import_success = [False]
        def import_result_show(success: bool):
            """处理导入结果"""
            import_success[0] = success
            import_finished[0] = True


        # 连接导入完成信号
        self.rcd_log_importer.logs_imported.connect(import_result_show)
        
        # 导入rcd日志
        self.rcd_log_importer.import_logs_async("", files_path)
        # 解析agv和cset日志
        # 从文件列表中获取第一个文件所在目录作为源路径
        src_path = os.path.dirname(files_path[0])
        self.agv_log_parser.parse_log_folder(src_path)
        software_id = self.agv_log_parser.get_software_id()
        car_type = self.agv_log_parser.get_car_type()
        self.cset_parser.parse_log_folder(src_path, software_id=software_id)
        self.rcd_tr.parse_tr_json(car_type)
        act_name_map = self.cset_parser.get_actuator_mapping()
        self.rcd_tr.set_act_name_map(act_name_map)

        # 等待导入完成
        while not import_finished[0]:
            QApplication.instance().processEvents()  # 处理事件队列
            time.sleep(0.1)
            
        # 断开信号连接
        self.rcd_log_importer.logs_imported.disconnect(import_result_show)
        progress_dialog.close()
        # 显示结果提示
        if import_success[0]:
            QMessageBox.information(self, '日志导入', '导入完成')
        else:
            QMessageBox.warning(self, '日志导入失败', '导入过程中出现错误')


    def closeEvent(self, event):
        """
        程序退出事件
        :param event:
        :return:
        """
        # 清理 plot_window 中的线程
        self.plot_widget.stop_all_tasks()
        # self.config.save_cfg()  # 在关闭窗口时保存配置
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

    def get_files_by_file_dialog(self):
        """
        获取选择的文件列表
        :return:
        """
        file_paths, _ = QFileDialog.getOpenFileNames(self, '选择文件', '', '所有文件 (*.*);;文本文件 (*.txt)')
        if 0 == len(file_paths):
            # 用户未选择文件
            QMessageBox.warning(None, '警告', '未选择任何文件！')
            return None
        return file_paths

    def get_path_by_folder_dialog(self):
        folder_dialog = QFileDialog(self)
        folder_path = folder_dialog.getExistingDirectory(self, "选择文件夹")
        if folder_path is None or len(folder_path) == 0:
            QMessageBox.warning(None, '警告', '未选择任何文件！')
            return None
        return folder_path

    def get_files_by_folder_dialog(self, folder_path=None):
        """
        获取选择的文件夹,返回文件夹中的列表
        :return:
        """
        if folder_path is None:
            folder_dialog = QFileDialog(self)
            folder_path = folder_dialog.getExistingDirectory(self, "选择文件夹")
        if folder_path is None:
            return None
        file_list = []
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                file_path = os.path.join(root, file)
                file_list.append(file_path)
        if 0 == len(file_list):
            QMessageBox.warning(None, '警告', '未选择任何文件！')
            return None
        return file_list

    @staticmethod
    def slot_version_btn():
        msg = QMessageBox()
        msg.setWindowTitle("版本说明")
        msg.setText(VERSION_INFO)
        msg.exec()  # 显示信息框



# def slot_help_doc_btn():
#     os.startfile(r".\doc\RCD日志解析工具使用说明.pdf")


class JsonCfg:
    def __init__(self, file_name="./cfg/config.json"):
        self.cfg_path = file_name
        self.cfg_json = None
        self.read()

    def read(self):
        with open(self.cfg_path, encoding="utf-8") as f:
            self.cfg_json = json.load(f)


class App(QApplication):
    def notify(self, source: QObject, event: QEvent):
        """
        本次重写notify是为了截获应用的所有事件
        :param source: 事件接收对象
        :param event: 具体事件
        :return: True表示事件已经处理，False表示没有处理，需要继续往下传递
        """
        if event.type() == QEvent.Wheel and event.modifiers() == Qt.ControlModifier:
            # print(f"App {source}")
            pass
            # return True
        # print(source, event)
        return super().notify(source, event)



def check_domain():
    return True
    try:
        host_name = socket.gethostname()
        domain_name = socket.getfqdn()
        userdomain = os.environ.get('USERDOMAIN')
        print(f"host_name {host_name} domain_name {domain_name} userdomain {userdomain}")
        if "hikvision.com" in host_name:
            QMessageBox.warning(None, "警告",
                                f"主机名和域名冲突 host_name {host_name} domain_all {domain_name} domain{userdomain}")
            return False
        if "hikvision.com" in domain_name or "HIK" in userdomain:
            return True
        else:
            QMessageBox.warning(None, "警告",
                                f"仅支持HIK加域电脑运行 host_name {host_name} domain_all {domain_name} domain{userdomain}")
            return False
    except Exception as e:
        QMessageBox.warning(None, "警告", f"域名获取失败,尝试管理员运行 {e}")



def main(argv: Optional[Sequence[str]] = None) -> int:
    

    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_TITLE)
    app.setOrganizationName("RcdPlot")
    app.setApplicationDisplayName(APP_TITLE)
    app.setStyle('Fusion')
    # icon_path = res_manager.get_icon_path("app_icon.ico")
    # if os.path.isfile(icon_path):
    #     app.setWindowIcon(QIcon(icon_path))

    try:
        
        window = MainWidget()
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
   
    

    if owns_app:
        return app.exec()
    return 0










if __name__ == '__main__':
    app = App(sys.argv)
    if not check_domain():
        sys.exit(1)
    w = MainWidget()
    w.show()
    sys.exit(app.exec())


