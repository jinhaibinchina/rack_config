"""PySide6 的 uic.loadUi 兼容层。

PySide6 没有 PyQt6 那样的 `uic.loadUi(ui_file, baseinstance)`，
这里用 QUiLoader 实现等价功能：把 .ui 加载到已有的 baseinstance 上，
并把子控件设置为 baseinstance 的属性。
"""
from PySide6.QtCore import QDir

from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QMenuBar,
    QStatusBar,
    QToolBar,
    QDockWidget,
)


class _UiLoader(QUiLoader):
    def __init__(self, baseinstance=None, parent=None):
        super().__init__(parent)
        self._baseinstance = baseinstance

    def createWidget(self, class_name, parent=None, name=""):
        if parent is None and self._baseinstance is not None:
            # 顶层控件：复用 baseinstance 本身
            widget = self._baseinstance
        else:
            widget = super().createWidget(class_name, parent, name)
            if self._baseinstance is not None and name:
                setattr(self._baseinstance, name, widget)
        return widget


def _install_central_widget(window: QMainWindow) -> None:
    """QUiLoader 不会自动调用 setCentralWidget，这里手动补上。

    从 QMainWindow 的直接子控件里找出中央控件：优先名字含 central 的，
    否则取第一个非菜单栏/状态栏/工具栏/停靠窗的 QWidget。
    """
    if window.centralWidget() is not None:
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


def loadUi(uifile, baseinstance=None):
    """等价于 PyQt6 的 uic.loadUi(uifile, baseinstance)"""
    loader = _UiLoader(baseinstance)
    ui = loader.load(uifile)
    if ui is not None and baseinstance is not None and isinstance(ui, QMainWindow):
        _install_central_widget(ui)
    return ui
