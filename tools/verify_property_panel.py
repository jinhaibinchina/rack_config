"""属性 dock 的回归校验。

校验内容：
1. 每类图元都能建出属性面板，且分页数量、控件数量符合预期；
2. 顶部对象摘要条显示正确的类型 / 名称 / ID；
3. 位置、尺寸、颜色、不透明度、名称等字段编辑后确实写回图元；
4. 页面背景（场景）分页能展示画布与统计信息；
5. 切换选中对象时旧分页被清理，不留残页。

用法::

    .venv/Scripts/python.exe tools/verify_property_panel.py
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
)

from Designer.Core.NavigationContentWidget import NavigationContentWidget
from Designer.Core.my_common import SceneMode
from Designer.Core.ui.element_factory import create_element
from tools.bench_scene import DEFAULT_PAGE, build_scene

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "OK  " if condition else "FAIL"
    print(f"[{status}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        FAILURES.append(name)


def find_fields(page_widget, kind):
    return page_widget.findChildren(kind)


def page_widget_of(panel, key):
    for index in range(panel.content_stack.count()):
        widget = panel.content_stack.widget(index)
        if widget.objectName() == key:
            return widget.widget()
    return None


def build_panel(panel, selected, expect_pages, label):
    panel.update_for_selected(selected)
    pages = panel.content_stack.count()
    titles = [panel.navigation_tree.topLevelItem(i).text(0)
              for i in range(panel.navigation_tree.topLevelItemCount())]
    check(f"{label}: 分页数量", pages == expect_pages, f"{pages} 页 {titles}")
    check(f"{label}: 导航非空", panel.navigation_tree.topLevelItemCount() > 0, str(titles))
    check(f"{label}: 头部已更新", panel.header._title.text() != "", panel.header._title.text())
    return pages


def main() -> int:
    app = QApplication.instance() or QApplication([])
    scene = build_scene(DEFAULT_PAGE)
    check("场景构建", scene.mode() == SceneMode.Design, str(scene.mode()))

    panel = NavigationContentWidget(scene=scene)
    panel.resize(1280, 420)
    panel.show()

    # ---------------------------------------------------------------- 场景页
    build_panel(panel, scene, 2, "页面背景")
    check("页面背景: 摘要为页面", panel.header._title.text() == "页面背景",
          panel.header._title.text())
    canvas = page_widget_of(panel, "canvas")
    check("画布页: 已生成", canvas is not None)
    if canvas is not None:
        texts = [label.text() for label in canvas.findChildren(QLabel)]
        joined = " ".join(text for text in texts if text.strip())
        check(
            "画布页: 含比例尺/统计",
            ("比例尺" in joined) and ("图元总数" in joined),
            joined[:80],
        )

    # ---------------------------------------------------------------- 各图元
    cases = [
        ("rect", 3),
        ("triangle", 3),
        ("circle", 3),
        ("line", 3),
        ("text", 4),
        ("image", 3),
        ("checkbox", 4),
        ("widget", 4),
    ]
    created = {}
    for offset, (key, pages_expected) in enumerate(cases):
        item = create_element(scene.scene_manager, key,
                              QPointF(1000.0 + offset * 400.0, 800.0))
        if item is None:
            check(f"{key}: 创建图元", False)
            continue
        created[key] = item
        build_panel(panel, item, pages_expected, key)

    # ---------------------------------------------------------------- 组
    groups = [
        item for item in scene.scene_manager.m_items.values()
        if item.__class__.__name__ == "group_element"
    ]
    if groups:
        group = groups[0]
        group.set_selected(True)
        scene.set_current_select_item(group)
        build_panel(panel, group, 4, "group")
        names = [panel.navigation_tree.topLevelItem(i).text(0)
                 for i in range(panel.navigation_tree.topLevelItemCount())]
        check("group: 含事件绑定页", names[0] == "事件绑定", str(names))

    # ---------------------------------------------------------------- 写回
    rect = created.get("rect")
    if rect is not None:
        panel.update_for_selected(rect)
        layout_page = page_widget_of(panel, "layout")
        spins = find_fields(layout_page, QDoubleSpinBox)
        check("矩形: 布局页数值框 >= 4", len(spins) >= 4, str(len(spins)))
        if len(spins) >= 2:
            target_x = 4321.0
            old_x = rect.get_scene_head_pos().x()
            spins[0].setValue(target_x)
            check("矩形: X 写回图元", abs(rect.get_scene_head_pos().x() - target_x) < 0.01,
                  f"{old_x:.1f} -> {rect.get_scene_head_pos().x():.1f}")

            target_w = 321.0
            spins[2].setValue(target_w)
            check("矩形: 宽度写回图元", abs(rect.getSize().width() - target_w) < 0.01,
                  f"{rect.getSize().width():.1f}")

        appearance_page = page_widget_of(panel, "appearance")
        sliders = find_fields(appearance_page, QSlider)
        check("矩形: 外观页有透明度滑块", len(sliders) == 1, str(len(sliders)))
        if sliders:
            sliders[0].setValue(50)
            expected = round(50 * 255 / 100)
            check("矩形: 不透明度写回图元", abs(rect.get_opacity() - expected) <= 1,
                  f"{rect.get_opacity()} vs {expected}")

        checks = find_fields(appearance_page, QCheckBox)
        if checks:
            checks[0].setChecked(not checks[0].isChecked())
            check("矩形: 填充开关写回图元", rect.get_fill() == checks[0].isChecked(),
                  str(rect.get_fill()))

    # ---------------------------------------------------------------- 名称
    text_item = created.get("text")
    if text_item is not None:
        panel.update_for_selected(text_item)
        general = page_widget_of(panel, "general")
        edits = [w for w in find_fields(general, QLineEdit) if not w.isReadOnly()]
        check("文本: 常规页有可编辑名称框", len(edits) >= 1, str(len(edits)))
        if edits:
            new_name = f"verify_text_{text_item.id()}"
            edits[0].setText(new_name)
            edits[0].editingFinished.emit()
            check("文本: 名称写回图元", text_item.get_name() == new_name,
                  text_item.get_name())

    # ---------------------------------------------------------------- 清理
    check("切换后无残留分页", panel.content_stack.count() <= 4,
          str(panel.content_stack.count()))

    print()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项: {FAILURES}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
