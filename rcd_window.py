from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QMessageBox,QLabel,QLineEdit,QPushButton,QApplication,QPlainTextEdit
import sys,os
from global_config import global_cfg
from PySide6.QtCore import Signal
from resource_manager import resource_manager as res_mng
from load_ui import LoadDialog
from typing import List, Optional, Dict, Any
from pathlib import Path

from PySide6.QtWidgets import QInputDialog,QFileDialog

def convert_with_error_handling(input_file, output_file):
    """
    带错误处理的转换函数
    """
    try:
        # 检查输入文件是否存在
        if not os.path.exists(input_file):
            print(f"错误：文件 '{input_file}' 不存在")
            return False
        
        # 检查文件是否为空
        if os.path.getsize(input_file) == 0:
            print(f"警告：文件 '{input_file}' 为空")
            # 创建空的 UTF-8 文件
            with open(output_file, 'w', encoding='utf-8') as f:
                pass
            return True
        
        # 转换文件
        with open(input_file, 'r', encoding='utf-16le') as f_in:
            with open(output_file, 'w', encoding='utf-8') as f_out:
                for line in f_in:
                    f_out.write(line)
        
        print(f"转换成功：'{input_file}' -> '{output_file}'")
        return True
        
    except UnicodeDecodeError as e:
        print(f"解码错误：文件可能不是 UTF-16 LE 编码")
        print(f"错误详情：{e}")
        return False
    except Exception as e:
        print(f"转换失败：{e}")
        return False




class RcdWindow(LoadDialog):
    
    def __init__(self, parent=None):
        ui_file_path = res_mng.get_ui_path('dialog_rcd.ui')
        qss_file     = res_mng.get_ui_path('rcd.qss')
        super().__init__(ui_file_path, qss_file)
        self.project_path: Optional[Path] = None

        self.plain:QPlainTextEdit =self.ui.plainTextEdit
        # self.resize(300, 150)  # 调整高度以适应内容
        self.setWindowTitle("日志数据")  # 修正标题
        self.plain.setReadOnly(True)
        self.ui.pushButton.clicked.connect(self._browse_runtime_hook)
    def _browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if dir_path:
            self.output_dir_edit.setText(dir_path)
           

    
    def _browse_runtime_hook(self):

        
        
        # 使用用户主目录作为默认目录
        default_dir = str(Path.home())
        self.project_path = default_dir
        if not self.project_path:
            QMessageBox.warning(self, "提示", "请先选择项目目录")
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "选择日志文件", default_dir, "日志文件 (*.txt)")
        if file_path:
            try:
                # rel = Path(file_path).relative_to(self.project_path)
                # self.runtime_hook_edit.setText(str(rel))
                self.ui.lineEdit.setText(str(file_path))
                outfile_name = Path(file_path).parent.joinpath('a.txt')

                if convert_with_error_handling(file_path,outfile_name):
                    self.plain.clear()
                    with open(outfile_name, 'r', encoding='utf-8') as f:
                        
                        self.plain.appendPlainText(f.read())
            except ValueError:
                self.ui.lineEdit.setText(str(file_path))