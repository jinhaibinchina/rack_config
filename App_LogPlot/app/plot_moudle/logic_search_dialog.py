from .load_ui import LoadDialog
from .resource_manager import resource_manager as res_mng
from PySide6.QtWidgets import QDialog
from .logical_data_generator import LogicalDataGenerator
from .common import rcd_data_bridge
from PySide6.QtCore import  Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, 
                            QPushButton, QLabel, QComboBox, QMessageBox, 
                            QListWidget, QSplitter, QFrame)
from typing import List

class LogicScriptInputDialog(LoadDialog):

    script_executed = Signal(tuple)  # 信号：新生成的数据名称
    
    def __init__(self, transformer: LogicalDataGenerator,data_bridge:rcd_data_bridge,head_names_in_plot:List, parent=None):
        ui_file_path = res_mng.get_ui_path('logic_search.ui')
        qss_file     = res_mng.get_ui_path('rcd.qss')
        super().__init__(ui_file_path, qss_file)
        self.transformer = transformer
        self.data_bridge = data_bridge
        self._data_heads = head_names_in_plot
        
        self.setWindowTitle("条件搜索")
        self.ui.pushButton_validate.clicked.connect(self.validate_script)
        self.ui.pushButton_clear.clicked.connect(self.clear_script)
        self.ui.pushButton_execute.clicked.connect(self.execute_script)

        self.listWidget.itemDoubleClicked.connect(self.insert_data)

        self.listWidget.addItems(self._data_heads)
        if transformer.last_scrip_context:
            self.ui.plainTextEdit_scrip.setPlainText(transformer.last_scrip_context)
        if transformer.last_tips_context:
            self.ui.plainTextEdit_result.setPlainText(transformer.last_tips_context)
    def validate_script(self):
        """验证脚本语法"""
        script = self.ui.plainTextEdit_scrip.toPlainText().strip()

        if not script:
            QMessageBox.warning(self, "警告", "请输入脚本")
            return
        
        try:
            is_valid, message = self.transformer.validate_script(script)
            if is_valid:
                QMessageBox.information(self, "验证通过", message)
            else:
                QMessageBox.warning(self, "验证失败", message)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"验证过程中发生错误: {str(e)}")
    
    def execute_script(self):
        """执行脚本"""
        script = self.plainTextEdit_scrip.toPlainText().strip()
        self.transformer.last_scrip_context = self.plainTextEdit_scrip.toPlainText()
        if not script:
            QMessageBox.warning(self, "警告", "请输入脚本")
            return
        
        try:
            condition_name,new_datas = self.transformer.generate_logical_data(script)
        
            total_time,condition_true_time,trigger_count,quit_count = self.result_handle(new_datas)

            self.transformer.last_tips_context =f"日志总时长:{total_time:.1f}s,满足条件的时长:{condition_true_time:.1f}s,条件触发进入次数:{trigger_count},退出次数:{quit_count}"
                                                    
            self.ui.plainTextEdit_result.clear()

            self.ui.plainTextEdit_result.setPlainText(self.transformer.last_tips_context)
                                                    
            self.ui.plainTextEdit_result.setReadOnly(True)

            QMessageBox.information(self, "执行成功", f"新数据 '{condition_name}' 已生成")

            self.script_executed.emit((condition_name,new_datas))
            # self.accept()  # 关闭对话框
        except Exception as e:
            QMessageBox.critical(self, "执行失败", f"执行脚本时发生错误: {str(e)}")
    def clear_script(self):
        """清除脚本"""
        self.ui.plainTextEdit_scrip.clear()
    
    def insert_data(self, item):
        """插入数据引用到脚本"""
        data_key = item.text()
        # data_ref = f"{data_key.replace('/', '_')}"
        cursor = self.ui.plainTextEdit_scrip.textCursor()
        cursor.insertText(data_key)
        self.ui.plainTextEdit_scrip.setTextCursor(cursor)
    
    def result_handle(self,datas:List):
        total_data_count =  self.data_bridge.idx_count()
        total_time = float( self.data_bridge.total_time_ms() )/1000.0

        condition_true_count = datas.count(1)
        condition_true_time  = float(condition_true_count) / float(total_data_count) *total_time
        data_last = 0

        trigger_count = 0
        quit_count = 0
        for data in datas:
            if data==1 and data_last == 0:
                trigger_count +=1
            if data==0 and data_last == 1:
                quit_count +=1
            data_last = data
        
        return (total_time,condition_true_time,trigger_count,quit_count)

