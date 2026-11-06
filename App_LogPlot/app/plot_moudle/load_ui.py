from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QWidget, QMainWindow, QDialog
import sys

# PySide6 没有 PyQt 的 ``uic.loadUi(ui_file, baseinstance)``，这里用 QUiLoader
# 实现等价能力：把 .ui 的内容加载进已有的 baseinstance，并把子控件挂成它的属性。
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QMenuBar, QStatusBar, QToolBar, QDockWidget


class _UiLoader(QUiLoader):
    """加载 .ui 到已有实例的 QUiLoader。

    QUiLoader.load() 只接受「新建一个顶层控件」，不能直接填充已有对象；
    因此在 createWidget 里把顶层控件替换成 baseinstance。
    """

    def __init__(self, baseinstance=None):
        super().__init__()
        self._baseinstance = baseinstance

    def createWidget(self, class_name, parent=None, name=""):
        if parent is None and self._baseinstance is not None:
            widget = self._baseinstance
        else:
            widget = super().createWidget(class_name, parent, name)
            if self._baseinstance is not None and name:
                setattr(self._baseinstance, name, widget)
        return widget


def _install_central_widget(window):
    """QUiLoader 不会调用 setCentralWidget，这里按名字/类型补上。"""
    if not isinstance(window, QMainWindow) or window.centralWidget() is not None:
        return
    specials = (QMenuBar, QStatusBar, QToolBar, QDockWidget)
    fallback = None
    for child in window.children():
        if not isinstance(child, QWidget) or isinstance(child, specials):
            continue
        if "central" in child.objectName().lower():
            window.setCentralWidget(child)
            return
        if fallback is None:
            fallback = child
    if fallback is not None:
        window.setCentralWidget(fallback)


def load_ui(ui_file, baseinstance=None):
    """等价于 PyQt 的 ``uic.loadUi(ui_file, baseinstance)``。"""
    loader = _UiLoader(baseinstance)
    ui = loader.load(ui_file)
    if ui is not None:
        _install_central_widget(ui)
    return ui


class LoadWidget(QWidget):
    def __init__(self, ui_file, qss_file=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 加载UI文件
        try:
            self.ui = load_ui(ui_file, self)
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

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        return super().keyPressEvent(a0)
    
    def keyReleaseEvent(self, a0: QKeyEvent | None) -> None:
        return super().keyReleaseEvent(a0)
    
    
class LoadDialog(QDialog):
    def __init__(self, ui_file, qss_file=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 加载UI文件
        try:
            self.ui = load_ui(ui_file, self)
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
