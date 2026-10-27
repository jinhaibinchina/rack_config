from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QWidget, QMainWindow, QDialog
from uic_compat import loadUi as uic_loadUi



import sys


class LoadWidget(QWidget):
    def __init__(self, ui_file, qss_file=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 加载UI文件
        try:
           

            self.ui = uic_loadUi(ui_file, self)
        except Exception as e:
            print(f"Failed to load UI file: {str(e)}")
            sys.exit(1)
        # return
        # 设置QSS样式
        if qss_file:
            try:
                with open(qss_file, 'r', encoding='utf-8') as f:
                    self.setStyleSheet(f.read())
            except Exception as e:
                print(f"Failed to load QSS file: {str(e)}")
                sys.exit(1)

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        return super().keyPressEvent(a0)
    
    def keyReleaseEvent(self, a0: QKeyEvent | None) -> None:
        return super().keyReleaseEvent(a0)
    
    
class LoadDialog(QDialog):
    def __init__(self, ui_file, qss_file=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 加载UI文件
        try:
            self.ui = uic_loadUi(ui_file, self)
        except Exception as e:
            print(f"Failed to load UI file: {str(e)}")
            sys.exit(1)

        # 设置QSS样式
        if qss_file:
            try:
                with open(qss_file, 'r', encoding='utf-8') as f:
                    self.setStyleSheet(f.read())
            except Exception as e:
                print(f"Failed to load QSS file: {str(e)}")
                sys.exit(1)


class LoadMainWindow(QMainWindow):
    def __init__(self, ui_file, qss_file=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 加载UI文件
        try:
            self.ui = uic_loadUi(ui_file, self)
        except Exception as e:
            print(f"Failed to load UI file: {str(e)}")
            sys.exit(1)
        # return
        # 设置QSS样式
        if qss_file:
            try:
                with open(qss_file, 'r', encoding='utf-8') as f:
                    self.setStyleSheet(f.read())
            except Exception as e:
                print(f"Failed to load QSS file: {str(e)}")
                sys.exit(1)