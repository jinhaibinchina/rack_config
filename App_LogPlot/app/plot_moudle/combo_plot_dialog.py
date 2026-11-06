from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTextEdit,QLineEdit, 
                            QPushButton, QLabel, QComboBox, QMessageBox, 
                            QListWidget, QSplitter, QFrame)
from PySide6.QtCore import Qt, Signal,QObject
from PySide6.QtGui import QFont, QTextCursor,QCloseEvent
import json,sys,os
from .resource_manager import resource_manager as res_mng

class ConnectionManager:
    """连接管理器"""
    def __init__(self):
        self.connections = []
    
    def add_connection(self, connection):
        """添加连接"""
        self.connections.append(connection)
    
    def disconnect_all(self):
        """断开所有连接"""
        for connection in self.connections:
            try:
                if connection:
                    QObject.disconnect(connection)
            except:
                pass
        self.connections.clear()

class ComboPoltDataDialog(QDialog):
    """脚本输入对话框"""
    data_updated = Signal()

    @staticmethod
    def remove_tr_name(text):
        import re
        result = re.sub(r'\([^)]*\)', '', text)
        return result
    
    def __init__(self, info: list,translater ,parent=None):
        super().__init__(parent)
        self._info = info
        self._rcd_translater = translater
        # self._file_path = "./cfg/combo_data.json"
        self._file_path = res_mng.get_data_path("combo_data.json")
        self.setup_ui()
        self.setWindowTitle("生成组合绘制数据项")
        self.resize(400, 300)
    
    def setup_ui(self):
        """设置UI界面"""
        main_layout = QVBoxLayout()
       
        up_layout = QVBoxLayout()

        data_label = QLabel("图表1-4存在的数据:")
        up_layout.addWidget(data_label)
        
        self.data_list_00 = QListWidget()
        self.data_list_01 = QListWidget()
        self.data_list_10 = QListWidget()
        self.data_list_11 = QListWidget()
		
        for info in self._info:
            location   = info["location"]
            head_names = info["items"]
            if location == "00":
                contexts =         []
                for data_head in head_names:
                    tr = self._rcd_translater.translate_title(data_head)
                    if tr is None:
                        contexts.append(data_head)
                    else:
                        contexts.append(data_head +"(" + tr +")")
                self.data_list_00.addItems(contexts)
            elif location == "01":
                contexts =         []
                for data_head in head_names:
                    tr = self._rcd_translater.translate_title(data_head)
                    if tr is None:
                        contexts.append(data_head)
                    else:
                        contexts.append(data_head +"(" + tr +")")
                self.data_list_01.addItems(contexts)
            elif location == "10":
                contexts =         []
                for data_head in head_names:
                    tr = self._rcd_translater.translate_title(data_head)
                    if tr is None:
                        contexts.append(data_head)
                    else:
                        contexts.append(data_head +"(" + tr +")")
                self.data_list_10.addItems(contexts)
            elif location == "11":
                contexts =         []
                for data_head in head_names:
                    tr = self._rcd_translater.translate_title(data_head)
                    if tr is None:
                        contexts.append(data_head)
                    else:
                        contexts.append(data_head +"(" + tr +")")
                self.data_list_11.addItems(contexts)

        up_layout.addWidget(self.data_list_00)
        up_layout.addWidget(self.data_list_01)
        up_layout.addWidget(self.data_list_10)
        up_layout.addWidget(self.data_list_11)
        
        

        # 按钮区域
        button_layout = QHBoxLayout()
        self.script_edit = QLineEdit()
        self.script_edit.setPlaceholderText("请为当前的组合数据命名")
        self.script_edit.setFont(QFont("Consolas", 10))
        button_layout.addWidget(self.script_edit)
        # 验证按钮
        validate_btn = QPushButton("生成组合绘制数据")
        validate_btn.clicked.connect(self.serialize_data)
        button_layout.addWidget(validate_btn)

        main_layout.addLayout(up_layout)
        main_layout.addLayout(button_layout)


        self.setLayout(main_layout)


    def closeEvent(self, event: QCloseEvent | None) -> None:

        return super().closeEvent(event)
	
    def serialize_data(self):
        """序列化为JSON文件"""

        combo_data = {}
        json_data = {}
        # json_path = ComboPoltDataDialog.get_json_path(self._file_path)
        json_path = self._file_path
        if not json_path:
            return
        
        # 读取现有数据
        try:
            with open(json_path, 'r', encoding='utf-8') as file:
                json_data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            # 如果文件不存在或格式错误，创建新的空字典
            json_data = {}

        combo_name = self.script_edit.text().strip()
        if not combo_name:
            QMessageBox.warning(self, "警告", "请输入组合数据名称")
            return
            
        if combo_name in json_data.keys():
            QMessageBox.warning(self, "警告", "已存在同名数据项")
            return

        combo ={}
        plot_info =[]
        
        plot_type = None
        if self.data_list_00.count() > 0 and self.data_list_01.count() > 0 and self.data_list_10.count() > 0 and self.data_list_11.count() > 0:
            plot_type = "3"
            

        elif self.data_list_01.count() > 0:
            plot_type = "1"
            
        elif self.data_list_10.count() > 0:
            plot_type = "2"
        else:
            plot_type = "0"
        combo["plot_type"] = plot_type

        if self.data_list_00.count()>0:
            head_names = []
            info = {}
            # 获取所有选中的数据项
            for i in range(self.data_list_00.count()):
                item = self.data_list_00.item(i)
                head_names.append(item.text())
            data_heads_without_tr = list(map(ComboPoltDataDialog.remove_tr_name,head_names))
            info["location"] = "00"
            info["items"] = data_heads_without_tr
            plot_info.append(info)
        
        if self.data_list_01.count()>0:
            head_names = []
            info = {}
            # 获取所有选中的数据项
            for i in range(self.data_list_01.count()):
                item = self.data_list_01.item(i)
                head_names.append(item.text())
            data_heads_without_tr = list(map(ComboPoltDataDialog.remove_tr_name,head_names))
            info["location"] = "01"
            info["items"] = data_heads_without_tr
            plot_info.append(info)

        if self.data_list_10.count()>0:
            head_names = []
            info = {}
            # 获取所有选中的数据项
            for i in range(self.data_list_10.count()):
                item = self.data_list_10.item(i)
                head_names.append(item.text())
            data_heads_without_tr = list(map(ComboPoltDataDialog.remove_tr_name,head_names))
            info["location"] = "10"
            info["items"] = data_heads_without_tr
            plot_info.append(info)

        if self.data_list_11.count()>0:
            head_names = []
            info = {}
            # 获取所有选中的数据项
            for i in range(self.data_list_11.count()):
                item = self.data_list_11.item(i)
                head_names.append(item.text())
            data_heads_without_tr = list(map(ComboPoltDataDialog.remove_tr_name,head_names))
            info["location"] = "11"
            info["items"] = data_heads_without_tr
            plot_info.append(info)
        combo["plot_info"] = plot_info
		
		# 合并现有数据和新数据
        combo_data = json_data.copy()
        combo_data[combo_name] = combo

        # 写入 JSON 文件
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(combo_data, f, ensure_ascii=False, indent=4)
            QMessageBox.information(self, "成功", f"组合数据 '{combo_name}' 已保存")
            self.data_updated.emit()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")

    @staticmethod
    def get_json_path(relative_path=""):
        """获取json文件路径
        Args:
            relative_path: 相对于exe或脚本目录的子路径，如"config/data.json"
        """
        if getattr(sys, 'frozen', False):
            try:
            # PyInstaller 创建的临时文件夹，包含所有添加的资源文件
                base_dir = sys._MEIPASS
            except AttributeError:
                # 如果 _MEIPASS 不存在，回退到可执行文件目录
                base_dir = os.path.dirname(sys.executable)
        else:
            # 脚本文件所在路径
            base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 处理相对路径
        if relative_path:
            return os.path.join(base_dir, relative_path)
        return None