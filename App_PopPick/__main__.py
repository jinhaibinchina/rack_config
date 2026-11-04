"""``python -m App_PopPick`` 等价于运行 :mod:`App_PopPick.pop_pick_entry`。"""

from .pop_pick_entry import main

if __name__ == "__main__":
    raise SystemExit(main())
