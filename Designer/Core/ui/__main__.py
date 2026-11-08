

from __future__ import annotations

if not __package__:
    # ``python modes/design/design_window.py`` puts this folder (not the
    # project root) on sys.path, and the package-relative imports below need a
    # parent package.  Delegate to the documented entry point instead of
    # duplicating its QApplication setup here.
    import os
    import sys

    _PROJECT_ROOT =  os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ))
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)
        print(_PROJECT_ROOT)
    from Designer.Core.ui.design_window_entry import main

else:
    from .design_window_entry import main





if __name__ == "__main__":
    raise SystemExit(main())
