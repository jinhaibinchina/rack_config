"""工作站说明页的回归：业务文案已从框架层抽到 JSON，这里守住"抽完之后行为不变"。

三组断言
--------
1. **目录结构**：``res/App_SafetyCar/cfg/station_pages.json`` 能解析，组数/页数
   与配置一致，``{n}`` 展开正确；
2. **匹配语义**：按子串匹配、按 ``groups`` 顺序取第一个命中，与老 if/elif 链
   等价（``_EXPECTED`` 是从改动前的实现跑出来的固定期望表）；
3. **渲染**：``build_station_page`` 产出的 ``QGroupBox`` 标题和 ``QTextEdit``
   正文与配置逐字相同（含全角/半角标点和行首编号）。

用法::

    .venv/Scripts/python.exe tools/verify_station_pages.py
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QGroupBox, QTextEdit, QTreeWidget

from Designer.Core.station_pages import StationCatalog, build_station_page

CONFIG = os.path.join(_ROOT, "res", "App_SafetyCar", "cfg", "station_pages.json")

#: 场景里真实存在的 126 个组名里，会命中目录的那部分 + 几条伪组名。
#: 值全是 (page_id, title) 列表，顺序即导航顺序。
_EXPECTED = {
    "维修区/安全门(X.X.X.161)": [
        ("maintain_station", "维修区工作站"),
        ("safedoor_station", "安全门工作站"),
    ],
    "上架X4(X.X.X.171)": [
        ("shangjia_station1", "上架工作站1"),
        ("shangjia_station2", "上架工作站2"),
        ("shangjia_station3", "上架工作站3"),
        ("shangjia_station4", "上架工作站4"),
    ],
    "拣选X4(X.X.X.181)": [
        ("jianxuan_station1", "Q1P拣选工作站1"),
        ("jianxuan_station2", "Q1P拣选工作站2"),
        ("jianxuan_station3", "Q1P拣选工作站3"),
        ("jianxuan_station4", "Q1P拣选工作站4"),
    ],
    "安全门X1(X.X.X.191)": [("safedoor_station", "安全门工作站")],
    "输送线X2(X.X.X.201)": [
        ("convey_station1", "输送线工作站1"),
        ("convey_station2", "输送线工作站2"),
    ],
    "Q1P拣选/Q3P拣选(X.X.X.211)": [
        ("q1p_jianxuan_station", "Q1P拣选工作站"),
        ("q3p_jianxuan_station", "Q3P拣选工作站"),
    ],
    "Q3P托盘X2(X.X.X.221)": [
        ("q3p_tuopan_station1", "Q3P托盘工作站1"),
        ("q3p_tuopan_station2", "Q3P托盘工作站2"),
    ],
    "输送线X4(X.X.X.232)": [
        ("convey_station1", "输送线工作站1"),
        ("convey_station2", "输送线工作站2"),
        ("convey_station3", "输送线工作站3"),
        ("convey_station4", "输送线工作站4"),
    ],
    "主电柜": [("main_station", "主电柜工作站")],
}

#: 不该命中的组名（场景里真实存在，且老实现的 if/elif 也不会命中）。
#: 注意 ``上架X4_图片`` 不在此列：它是"上架X4"的子串，老实现同样会命中，
#: 属于历史行为，重构时原样保留，不在这一刀里改语义。
_NOT_MATCHED = [
    "组_28",
    "维修区",
    "安全门",
    "Q3P拣选工作站",
    "IO状态",
    "",
    None,
]


class _Recorder(QObject):
    """假的导航容器：把 add_page 的内容记下来。"""

    destory_current = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.navigation_tree = QTreeWidget()
        self._building_navigation = True
        self.pages: list[tuple[str, str, str, str]] = []

    def add_page(self, page_id: str, title: str, widget) -> None:
        box = widget.findChild(QGroupBox)
        edit = widget.findChild(QTextEdit)
        self.pages.append(
            (
                page_id,
                title,
                box.title() if box is not None else "",
                edit.toPlainText() if edit is not None else "",
            )
        )

    def select_preferred_page(self) -> None:
        pass


def _check(condition: bool, label: str, detail: str = "") -> bool:
    if condition:
        print(f"  [ok] {label}")
        return True
    print(f"  [FAIL] {label}{(' -> ' + detail) if detail else ''}")
    return False


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    passed = 0
    failed = 0

    def check(condition: bool, label: str, detail: str = "") -> None:
        nonlocal passed, failed
        if _check(condition, label, detail):
            passed += 1
        else:
            failed += 1

    print("== 1. 配置文件")
    check(os.path.isfile(CONFIG), f"存在 {os.path.relpath(CONFIG, _ROOT)}")
    with open(CONFIG, encoding="utf-8") as handle:
        raw = json.load(handle)
    check(isinstance(raw.get("groups"), list) and len(raw["groups"]) == 9, "groups 有 9 组")

    catalog = StationCatalog.load(CONFIG)
    check(bool(catalog), "目录非空")
    check(len(catalog) == 9, f"目录载入 9 组（实得 {len(catalog)}）")

    total_pages = sum(len(g.pages) for g in catalog.groups)
    check(total_pages == 22, f"展开后共 22 页（实得 {total_pages}）")

    print("== 2. 匹配语义")
    for name, expected in _EXPECTED.items():
        pages = catalog.match(name)
        actual = [(p.page_id, p.title) for p in pages]
        check(actual == expected, f"{name[:24]} -> {len(expected)} 页", f"{actual}")

    for name in _NOT_MATCHED:
        check(catalog.match(name) == (), f"{name!r} 不命中")

    # 子串匹配的历史副作用：图片组的名字里带着工作站名，同样会命中
    check(
        len(catalog.match("上架X4_图片")) == 4,
        "上架X4_图片 按子串命中（与老实现一致）",
    )

    # 顺序优先：同时含多个片段时取 groups 里靠前的那组
    check(
        [p.page_id for p in catalog.match("上架X4 输送线X4")][0] == "shangjia_station1",
        "多片段命中时取靠前的组",
    )

    print("== 3. 正文渲染")
    maintain = catalog.match("维修区/安全门(X.X.X.161)")[0]
    check(maintain.box_title == "维修区工作站逻辑说明", "分组标题来自 group_title")
    widget = build_station_page(maintain)
    edit = widget.findChild(QTextEdit)
    check(edit is not None and edit.isReadOnly(), "正文框只读")
    lines = edit.toPlainText().splitlines() if edit is not None else []
    check(len(lines) == 6, f"维修区 6 行（实得 {len(lines)}）")
    check(
        lines[5] == "6.红灯/蜂鸣：安全触发状态 ，绿灯：正常状态 ，黄灯：未使用",
        "第 6 行逐字一致（含空格与逗号）",
    )

    shangjia = catalog.match("上架X4(X.X.X.171)")[0]
    sj_lines = shangjia.body.splitlines()
    check(len(sj_lines) == 9, f"上架 9 行（实得 {len(sj_lines)}）")
    check(sj_lines[2] == "3.进箱模式：500ms内同时触发光电1和光电2，屏蔽光栅", "上架第 3 行全角冒号保留")

    convey = catalog.match("输送线X2(X.X.X.201)")[0]
    check(
        convey.body.splitlines()[2] == "3.进箱模式:500ms内同时触发光电1和光电2,屏蔽光栅",
        "输送线第 3 行半角冒号保留",
    )

    print("== 4. 容错")
    check(len(StationCatalog.load(None)) == 0, "空路径 -> 空目录")
    check(len(StationCatalog.load(os.path.join(_ROOT, "不存在的.json"))) == 0, "文件缺失 -> 空目录")
    check(len(StationCatalog.from_dict({})) == 0, "空对象 -> 空目录")
    bad = StationCatalog.from_dict({"groups": [{"match": ["x"], "pages": [{"title": "无id"}]}]})
    check(len(bad) == 0, "缺 page_id 的页被丢弃而不报错")

    del app
    print(f"\n{'=' * 46}\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
