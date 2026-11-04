"""设计模式「组显示/隐藏」回归。

覆盖三件事：
1. ``group_element.set_visibility`` 用快照还原成员可见性，不会把原本单独
   隐藏的成员一起点亮；
2. 组的属性页里「可见性」是可勾选开关，勾掉即整组隐藏；
3. 隐藏的组会出现在「页面背景 → 已隐藏的组」列表里，可以一键恢复
   （隐藏后画布上点不中它，这是唯一入口）。

用法：.venv/Scripts/python.exe tools/verify_group_visibility.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


class _FakeManager:
    def __init__(self, items):
        # 键只是占位：面板这里只遍历 values()。真实 id 由场景分配，
        # 裸构造的图元 id 都是 0，拿 id 当键会互相覆盖。
        self.m_items = {index: item for index, item in enumerate(items)}


class _FakeScene:
    """只提供属性面板用到的场景接口，避免加载整张真实场景。"""

    def __init__(self, items):
        self.scene_manager = _FakeManager(items)
        self.current_selected = self

    def get_bg_color(self):
        return QColor("#ffffff")

    def width(self) -> int:
        return 800

    def height(self) -> int:
        return 600

    def set_current_select_item(self, item):
        self.current_selected = item


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    from Designer.Core.elements import group_element, rect_element
    from Designer.Core.myPropertyForElement import GroupPropertyItem
    from Designer.Core.NavigationContentWidget import NavigationContentWidget

    # ---- 1. 快照还原 -------------------------------------------------
    group = group_element()
    plain = rect_element()
    hidden_member = rect_element()
    hidden_member.setParentItem(group)
    plain.setParentItem(group)
    hidden_member.set_visibility(False)

    check("成员单独隐藏生效", not hidden_member.get_visibility())
    group.set_visibility(False)
    check("组隐藏后整组不可见", not group.get_visibility() and not plain.get_visibility())
    group.set_visibility(True)
    check("组显示后可见", group.get_visibility() and plain.get_visibility())
    check("原先单独隐藏的成员保持隐藏", not hidden_member.get_visibility())

    # 反复隐藏/显示不应把状态冲掉
    group.set_visibility(False)
    group.set_visibility(True)
    check("二次往返仍保持成员原状态", not hidden_member.get_visibility() and plain.get_visibility())

    # ---- 2. 属性页开关 -----------------------------------------------
    prop = GroupPropertyItem(item=group)
    widget = prop._visibility_widget()
    check("可见性字段是复选框", isinstance(widget, QCheckBox), type(widget).__name__)
    check("复选框反映当前可见", widget.isChecked())

    widget.setChecked(False)
    check("取消勾选后隐藏整组", not group.get_visibility())
    widget.setChecked(True)
    check("重新勾选后恢复显示", group.get_visibility())

    # 单个图元仍是只读展示
    from Designer.Core.myPropertyForElement import RectPropertyItem
    from PySide6.QtWidgets import QLabel

    rect_prop = RectPropertyItem(item=plain)
    check("单图元可见性仍只读", isinstance(rect_prop._visibility_widget(), QLabel))

    # ---- 3. 已隐藏的组列表 -------------------------------------------
    group.set_visibility(False)
    fake_scene = _FakeScene([group, plain])
    panel = NavigationContentWidget(scene=fake_scene)
    card = panel._hidden_groups_card()
    check("隐藏组出现在恢复列表", card is not None)
    buttons = card.findChildren(QPushButton) if card is not None else []
    check("恢复列表有对应按钮", len(buttons) == 1, f"buttons={len(buttons)}")
    check("隐藏的成员不被当成顶层组列出", len(buttons) == 1)

    if buttons:
        buttons[0].click()
        check("点击恢复后组可见", group.get_visibility())
        check("恢复后自动选中该组", fake_scene.current_selected is group,
              type(fake_scene.current_selected).__name__)

    group.set_visibility(True)
    check("无隐藏组时不显示该卡片", panel._hidden_groups_card() is None)

    return _report()


def _report() -> int:
    failed = 0
    for name, ok, detail in results:
        if not ok:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
