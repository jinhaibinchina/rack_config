"""Entry point for the standalone design-mode application.

Run with::

    python design_main.py

The existing run-mode entry point remains ``main.py`` and is intentionally
left untouched.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from Designer.modes.design.design_window import DesignWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Safety Car Config - Design")
    app.setApplicationDisplayName("组态 · 设计模式")

    window = DesignWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
