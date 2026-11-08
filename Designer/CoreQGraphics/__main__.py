"""``python -m Designer.CoreQGraphics.ui [page.json]`` 启动设计器。"""

from __future__ import annotations

import argparse
import os
import sys



if __package__ in (None, ""):
    _ROOT =  os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
        print(_ROOT)
    from Designer.CoreQGraphics.ui import DesignerWindow
    def open_designer(page_path: str = "", projection=None):
        """便捷入口：返回 ``(QApplication, DesignerWindow)``，由调用方决定 exec。"""
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        window = DesignerWindow(page_path, projection)
        window.show()
        return app, window

else:
    from .ui.design_window import DesignerWindow
    



def main() -> int:
    ap = argparse.ArgumentParser(description="CoreQGraphics 设计器")
    ap.add_argument("page", nargs="?", default="", help="要打开的 page JSON")
    ap.add_argument("--offscreen", action="store_true", help="离屏（自动化/截图用）")
    args = ap.parse_args()
    if args.offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # from . import open_designer

    app, _window = open_designer(args.page)
    if args.offscreen:
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
