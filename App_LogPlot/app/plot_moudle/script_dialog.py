"""
脚本输入对话框 - 提供图形界面进行数据转换脚本输入
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, 
                            QPushButton, QLabel, QComboBox, QMessageBox, 
                            QListWidget, QSplitter, QFrame)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from .data_transformer import DataTransformer

class ScriptInputDialog(QDialog):
    """脚本输入对话框"""
    
    script_executed = Signal(str)  # 信号：新生成的数据名称
    
    def __init__(self, transformer: DataTransformer, parent=None):
        super().__init__(parent)
        self.transformer = transformer
        self.setup_ui()
        self.setWindowTitle("数据转换脚本")
        self.resize(800, 600)
        
    def new_data_key(self):
        return self.transformer.get_generated_data_keys()
    
    def setup_ui(self):
        """设置UI界面"""
        main_layout = QVBoxLayout()
        
        # 创建分割器
        splitter = QSplitter(Qt.Horizontal)
        
        # 左侧：脚本编辑区
        left_frame = QFrame()
        left_layout = QVBoxLayout(left_frame)
        
        # 脚本输入标签
        script_label = QLabel("输入脚本 (格式: 新数据名称 = 表达式):")
        left_layout.addWidget(script_label)
        
        # 脚本输入框
        self.script_edit = QTextEdit()
        self.script_edit.setPlaceholderText("例如: filtered_data = rcd_data * 0.5 + 2")
        self.script_edit.setFont(QFont("Consolas", 10))
        left_layout.addWidget(self.script_edit)

        button_layout = QHBoxLayout()
        
        # 验证按钮
        validate_btn = QPushButton("验证脚本")
        validate_btn.clicked.connect(self.validate_script)
        button_layout.addWidget(validate_btn)
        
        # 执行按钮
        execute_btn = QPushButton("执行脚本")
        execute_btn.clicked.connect(self.execute_script)
        button_layout.addWidget(execute_btn)
        
        # 清除按钮
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self.clear_script)
        button_layout.addWidget(clear_btn)
        
        left_layout.addLayout(button_layout)
        
        # 右侧：帮助和示例区
        right_frame = QFrame()
        right_layout = QVBoxLayout(right_frame)
        
        # 可用函数列表
        functions_label = QLabel("可用函数:")
        right_layout.addWidget(functions_label)
        
        self.functions_list = QListWidget()
        functions = self.transformer.get_available_functions()
        self.functions_list.addItems(functions)
        self.functions_list.itemDoubleClicked.connect(self.insert_function)
        right_layout.addWidget(self.functions_list)
        
        # 可用数据列表
        data_label = QLabel("可用数据:")
        right_layout.addWidget(data_label)
        
        self.data_list = QListWidget()
        data_keys = self.transformer.get_available_data_keys()
        self.data_list.addItems(data_keys)
        self.data_list.itemDoubleClicked.connect(self.insert_data)
        right_layout.addWidget(self.data_list)
        

        examples_label = QLabel("示例脚本:")
        right_layout.addWidget(examples_label)
        
        self.examples_list = QListWidget()
        examples = [
            "new_data = sin(x) + cos(x)",
            "filtered_data = rcd_data * 0.5 + 2",
            "derivative = diff(rcd_data)",
            "integral = cumsum(rcd_data)",
            "combined = rcd_data1 + rcd_data2",
            "scaled_data = rcd_data * 2 - 1",
        ]
        self.examples_list.addItems(examples)
        self.examples_list.itemDoubleClicked.connect(self.insert_example)
        right_layout.addWidget(self.examples_list)
        
        # 添加左右区域到分割器
        splitter.addWidget(left_frame)
        splitter.addWidget(right_frame)
        splitter.setSizes([500, 300])
        
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)
    
    def validate_script(self):
        """验证脚本语法"""
        script = self.script_edit.toPlainText().strip()
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
        script = self.script_edit.toPlainText().strip()
        if not script:
            QMessageBox.warning(self, "警告", "请输入脚本")
            return
        
        try:
            new_data_name = self.transformer.transform_data(script)
            QMessageBox.information(self, "执行成功", f"新数据 '{new_data_name}' 已生成")
            self.script_executed.emit(new_data_name)
            self.accept()  # 关闭对话框
        except Exception as e:
            QMessageBox.critical(self, "执行失败", f"执行脚本时发生错误: {str(e)}")
    
    def clear_script(self):
        """清除脚本"""
        self.script_edit.clear()
    
    def insert_function(self, item):
        """插入函数到脚本"""
        function_name = item.text()
        cursor = self.script_edit.textCursor()
        cursor.insertText(function_name + "()")
        self.script_edit.setTextCursor(cursor)
    
    def insert_data(self, item):
        """插入数据引用到脚本"""
        data_key = item.text()
        # data_ref = f"{data_key.replace('/', '_')}"
        cursor = self.script_edit.textCursor()
        cursor.insertText(data_key)
        self.script_edit.setTextCursor(cursor)
    
    # def format_data_reference(self, data_key: str) -> str:
    #     """格式化数据引用"""
    #     return f"data_{data_key.replace('/', '_')}"
    
    def insert_example(self, item):
        """插入示例脚本"""
        example = item.text()
        self.script_edit.setPlainText(example)
