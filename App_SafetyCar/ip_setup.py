from PySide6.QtWidgets import QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QMessageBox,QPushButton
from PySide6.QtCore import Qt, Signal, QRunnable, QThreadPool, Slot
from PySide6.QtGui import QIntValidator, QKeyEvent

from . import global_variables as gv
from .my_QWidgets import my_text_value_editable
from .my_data_broker import DataBroker



class IPChangeWorker(QRunnable):
    def __init__(self, callback, ip, parent):
        super().__init__()
        self.callback = callback
        self.ip = ip
        self.parent = parent

    @Slot()
    def run(self):
        try:
            success = self.callback(self.ip)
            self.parent.change_ip_finished.emit(success)
        except Exception as e:
            print(f"修改IP出错: {e}")
            self.parent.change_ip_finished.emit(False)

class ip_setup_window(QDialog):
    change_ip_finished = Signal(bool)
    
    def eventFilter(self, obj, event):
        """处理点号跳转事件"""
        if (event.type() == QKeyEvent.KeyPress and 
            event.key() == Qt.Key_Period and
            obj in [self.ip1, self.ip2, self.ip3]):
            # 找到当前输入框的下一个输入框
            if obj == self.ip1:
                self.ip2.setFocus()
            elif obj == self.ip2:
                self.ip3.setFocus()
            elif obj == self.ip3:
                self.ip4.setFocus()
            return True  # 表示事件已处理
        return super().eventFilter(obj, event)

    def __init__(self,data_broker:DataBroker):
        super().__init__()
        self.resize(300, 200)
        self.setWindowTitle("设置需要访问的PLC ip(A2网口)")
        self.data_broker = data_broker
        self.thread_pool = QThreadPool.globalInstance()
        self.is_processing = False
        main_layout = QVBoxLayout()
        row0 = QHBoxLayout()

        row0.addWidget(QLabel(text="IP地址:"))
        validator = QIntValidator(0, 255, self)  # 设置范围0-255
        self.ip1 = QLineEdit()
        self.ip2 = QLineEdit()
        self.ip3 = QLineEdit()
        self.ip4 = QLineEdit()
        self.ip1.setValidator(validator)
        self.ip2.setValidator(validator)
        self.ip3.setValidator(validator)
        self.ip4.setValidator(validator)
        
        # 安装事件过滤器
        self.ip1.installEventFilter(self)
        self.ip2.installEventFilter(self)
        self.ip3.installEventFilter(self)
        
        row0.addWidget(self.ip1)
        row0.addWidget(QLabel(text="."))
        row0.addWidget(self.ip2)
        row0.addWidget(QLabel(text="."))
        row0.addWidget(self.ip3)
        row0.addWidget(QLabel(text="."))
        row0.addWidget(self.ip4)

        # 初始化文本
        self.ip1.setText("")
        self.ip2.setText("")
        self.ip3.setText("")
        self.ip4.setText("")

        def transfer_ip(callback=None, ip=""):
            if callback is None or self.is_processing:
                return
                
            self.is_processing = True
            worker = IPChangeWorker(callback, ip, self)
            worker.setAutoDelete(True)
            self.thread_pool.start(worker)

        btn = QPushButton(text="确认修改")
        btn.pressed.connect(lambda: transfer_ip(
            callback=self.data_broker.plc_manager.change_ip,
            ip=f"{self.ip1.text()}.{self.ip2.text()}.{self.ip3.text()}.{self.ip4.text()}"
        ))
        
        
        
        def handle_ip_change_result(success):
            self.is_processing = False
            if success:
                QMessageBox.information(
                    None,
                    "通知",
                    "IP已修改",
                    QMessageBox.Ok
                )
            else:
                QMessageBox.warning(
                    None,
                    "错误",
                    "修改IP失败",
                    QMessageBox.Ok
                )
           
            self.deleteLater()
        self.change_ip_finished.connect(handle_ip_change_result)
        # 绑定回车键事件
        def handle_return(e):
            transfer_ip(
                callback=self.data_broker.plc_manager.change_ip,
                ip=f"{self.ip1.text()}.{self.ip2.text()}.{self.ip3.text()}.{self.ip4.text()}"
            )
            
        main_layout.addLayout(row0)
        main_layout.addWidget(btn)
        self.setLayout(main_layout)
