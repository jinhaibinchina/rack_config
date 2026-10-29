
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QMessageBox,QLabel,QLineEdit,QPushButton,QApplication
import sys
from App.global_config import global_cfg
from PySide6.QtCore import Signal

# class LoginWindow(QDialog):

#     login_signal = Signal(bool)


#     def __init__(self, parent = None):
#         super().__init__(parent)


#         self.resize(300,200)
#         self.setWindowTitle("用户登入")

#         layout=QVBoxLayout()


#         row0 = QHBoxLayout()
#         row0.addWidget(QLabel(text='密码：'))
#         self.user_name = QLineEdit()
#         self.user_name.setText("admin")
#         row0.addWidget(self.user_name)


     
#         #密码行
#         row1 = QHBoxLayout()
#         row1.addWidget(QLabel(text="密码：")) 
#         self.password = QLineEdit()
#         self.password.setEchoMode(QLineEdit.EchoMode.Password)#设置为密码输入模式 row1.addwidget(self.password)
#         #确认按钮
#         self.btn = QPushButton("确认")
#         self.btn.clicked.connect(self.verify_login)
#         layout.addLayout(row0) 
#         layout.addLayout(row1)
#         layout.addWidget(self.btn) 
#         self.setLayout(layout)


#     def showEvent(self, event):
#         """窗口显示时自动聚焦到密码输入框""" 
#         super().showEvent(event) 
#         self.password.setFocus()


#     def verify_login(self):
#         username = self.user_name.text() 
#         password = self.password.text()
#         valid_users ={
#         "admin":"1234","user":"pasaword"}

#         if username in valid_users and valid_users[username] == password:
#             self.is_logged_in = True
#             global_config.is_logged_in  = self.is_logged_in 
#             global_config._user_name =  username
#             self.login_signal.emit(True) 
#             self.close() 
#         else:
#             self.is_logged_in = False
#             global_config.is_logged_in  = self.is_logged_in 
#             global_config._user_name =  username
#             self.login_signal.emit(False) 
            

#             QMessageBox.information(
#                     None,
#                     "登录失败",
#                     "用户名或密码错误"
#                     )



# if __name__ == '__main__':
#     app = QApplication(sys.argv)
   
#     w = LoginWindow()
#     w.show()
#     sys.exit(app.exec())



class LoginWindow(QDialog):
    login_change_signal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(300, 150)  # 调整高度以适应内容
        self.setWindowTitle("用户登录")  # 修正标题

        layout = QVBoxLayout()

        # 用户名行
        row0 = QHBoxLayout()
        row0.addWidget(QLabel(text='用户名：'))
        self.user_name = QLineEdit()
        # self.user_name.setText("admin")
        row0.addWidget(self.user_name)
        layout.addLayout(row0)

        # 密码行
        row1 = QHBoxLayout()
        row1.addWidget(QLabel(text="密码："))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)  # 设置为密码输入模式
        row1.addWidget(self.password)  # 修复：添加密码框到布局
        layout.addLayout(row1)

        # 确认按钮
        self.btn = QPushButton("确认")
        self.btn.setDefault(True)  # 设置为默认按钮，支持回车登录
        self.btn.clicked.connect(self.verify_login)
        layout.addWidget(self.btn)

        self.setLayout(layout)

        self.user_name.setPlaceholderText("输入用户名")

        hot_words = ["admin","user"]
        self.setupCompleter(hot_words)

    def showEvent(self, event):
        """窗口显示时自动聚焦到密码输入框"""
        super().showEvent(event)
        self.password.setFocus()

    def verify_login(self):
        username = self.user_name.text()
        password = self.password.text()
        
        # 修正拼写错误：pasaword -> password
        valid_users = {
            "admin": "1234", 
            "user": "123"  # 修正拼写
        }

        if username in valid_users and valid_users[username] == password:
            # 假设 global_config 已正确导入
            # global_cfg.is_logged_in = True
            global_cfg._user_name = username
            global_cfg.login_enable_disable(True)

            self.login_change_signal.emit()
            self.accept()  # 推荐使用 accept() 代替 close()，它会返回 QDialog.Accepted
        else:
            global_cfg.is_logged_in = False
            global_cfg._user_name = username
            global_cfg.login_enable_disable(False)
            self.login_change_signal.emit()
            QMessageBox.warning(  # 建议使用 warning 而不是 information
                self,  # 父窗口设为 self，使提示框居中显示
                "登录失败",
                "用户名或密码错误"
            )
    

    def setupCompleter(self, word_list):

        from PySide6.QtWidgets import QCompleter
        from PySide6.QtCore import QStringListModel ,Qt
        # 创建补全器
        self.completer = QCompleter()
        
        # 创建字符串列表模型
        model = QStringListModel(word_list)
        self.completer.setModel(model)
        
        # 设置补全模式
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)  # 不区分大小写
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)  # 包含匹配
        self.user_name.mousePressEvent = self.customMousePressEvent
        # 设置弹出框样式
        self.completer.popup().setStyleSheet("""
            QListView {
                background-color: white;
                border: 1px solid #ccc;
                font-size: 12px;
                outline: none;
            }
            QListView::item {
                padding: 5px 10px;
                border-bottom: 1px solid #f0f0f0;
            }
            QListView::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
            }
            QListView::item:hover {
                background-color: #f5f5f5;
            }
        """)
        # 关联到 QLineEdit
        self.user_name.setCompleter(self.completer)
        # 连接选择信号
        self.completer.activated.connect(self.on_completion_selected)

    def on_completion_selected(self,text):
        print(f"选择了{text} ")

    def customMousePressEvent(self, event):
        
        """自定义鼠标点击事件，点击时显示补全列表"""
        from PySide6.QtCore import QTimer
        # 调用原始的鼠标点击事件
        QLineEdit.mousePressEvent(self.user_name, event)
        
        # 延迟显示补全列表，确保焦点已经获得
        QTimer.singleShot(50, self.show_completer_popup)
    
    def show_completer_popup(self):
        """显示补全弹出框"""
        if self.user_name.hasFocus():
            # 设置一个空字符串来触发显示所有选项
            self.completer.setCompletionPrefix("")
            self.completer.complete()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = LoginWindow()
    w.show()
    sys.exit(app.exec())