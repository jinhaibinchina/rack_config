"""CoreQGraphics 的 UI 外壳（设计器窗口 / 属性面板 / 工具箱 / 图层树）。

独立运行::

    .venv/Scripts/python.exe -m DesignerV2.CoreQGraphics

或在代码里::

    from DesignerV2.CoreQGraphics.ui import DesignerWindow
    window = DesignerWindow("path/to/page_1.json")
    window.show()

模块对应旧实现::

    Core/NavigationContentWidget.py + myPropertyForElement.py -> property_panel.py
    modes/design/element_toolbox_dock.py + element_factory.py   -> toolbox.py
    （旧项目无对象树）                                          -> layer_tree.py
    modes/design/page_history.py                                -> history.py
    modes/design/design_window_entry.py                         -> design_window.py
    Core/ui/template_store.py                                   -> template_store.py

``property_panel.py`` 复用了 ``Designer.Core.property_widgets``（纯 Qt 控件
层，零业务耦合），字段绑定按 ``BaseItem`` 重写；其余文件完全独立。
"""

from .design_window import DesignerWindow
from .history import PageHistory
from .layer_tree import LayerTreeDock
from .property_panel import PropertyPanel
from .template_store import TemplateStore, ToolboxTemplate
from .toolbox import ElementToolboxDock


def open_designer(page_path: str = "", template_dir: str = ""):
    """便捷入口：返回 ``(QApplication, DesignerWindow)``，由调用方决定 exec。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    window = DesignerWindow(page_path, template_dir=template_dir)
    window.show()
    return app, window


__all__ = [
    "DesignerWindow", "PropertyPanel", "ElementToolboxDock", "LayerTreeDock",
    "PageHistory", "TemplateStore", "ToolboxTemplate", "open_designer",
]
