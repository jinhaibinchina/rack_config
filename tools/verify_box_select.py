"""框选（rubber-band）回归校验。

覆盖三件事：

1. **几何**：四个拖拽方向都要能选中。``QRectF(p1, p2)`` 不做归一化，
   从右下往左上拖时宽高为负，``contains()`` 全部落空——这正是"框选看着
   有虚线框却什么都没选中"的根因。
2. **通知**：框选结束后必须发 ``selectionChanged``。框选只改各图元的
   ``selected`` 标志，不经过 ``single_select_handle``，没人会替它发信号；
   属性面板、状态栏、删除/排列动作的可用性全挂在这个信号上。
3. **属性面板**：一个 → 显示该图元；多个 → 多选概要页；零个 → 页面背景。

用法::

    .venv/Scripts/python.exe tools/verify_box_select.py
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from PySide6.QtCore import QObject, QPointF, QRectF
from PySide6.QtWidgets import QApplication

from Designer.Core.NavigationContentWidget import NavigationContentWidget
from Designer.Core.elements import base_element, group_element
from Designer.Core.ui.design_window_entry import DesignWindow
from Designer.Core.ui.design_scene import DesignScene
from tools.bench_scene import DEFAULT_PAGE, build_scene

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "OK  " if condition else "FAIL"
    print(f"[{status}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        FAILURES.append(name)


class _FakeAction:
    """记录 ``setEnabled`` 的替身，用于单独驱动窗口上的可用性计算。"""

    def __init__(self) -> None:
        self.enabled = None

    def setEnabled(self, value: bool) -> None:  # noqa: N802 - Qt 命名
        self.enabled = value


class _FakeStatusBar:
    def __init__(self) -> None:
        self.text = ""

    def showMessage(self, text: str, *args) -> None:  # noqa: N802 - Qt 命名
        self.text = text


class _FakeWindow(QObject):
    """只带场景与动作替身的窗口壳。

    ``_update_status`` / ``_update_selection_actions`` / ``_panel_target``
    都不依赖窗口的其它部分，直接把 ``DesignWindow`` 上的实现挂过来，
    既不用构造真的窗口（它关闭时会把 page_*.json 全部重写），又能测到
    真实的判断逻辑。

    继承 QObject 是为了 ``_on_scene_selection_changed`` 里的 ``self.sender()``
    ——它靠 sender 判断信号是不是当前页场景发的。
    """

    _selected_top_level_items = DesignWindow._selected_top_level_items
    _update_status = DesignWindow._update_status
    _update_selection_actions = DesignWindow._update_selection_actions
    _update_property_panel = DesignWindow._update_property_panel
    _on_scene_selection_changed = DesignWindow._on_scene_selection_changed
    _panel_target = DesignWindow._panel_target

    def _selected_group(self):
        # 本脚本用的是 QuadTreeScene 基类场景，没有 DesignScene.selected_group
        return None

    def __init__(self, scene, item_count: int) -> None:
        super().__init__()
        self.current_page = SimpleNamespace(
            scene=scene,
            meta=SimpleNamespace(name="page_1"),
            item_count=item_count,
        )
        self.status_bar = _FakeStatusBar()
        self.property_panel = None
        self.save_template_action = _FakeAction()
        self.delete_selected_action = _FakeAction()
        self.arrange_actions = [_FakeAction() for _ in range(6)]
        self.toolbox_dock = SimpleNamespace(set_capture_enabled=lambda value: None)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    scene = build_scene(DEFAULT_PAGE)
    scene.resize(1280, 800)

    top_items = [
        item
        for item in scene.findChildren(base_element)
        if not item.is_has_parent()
    ]
    top_items.sort(key=lambda item: item.zValue())
    check("页面上有顶层图元", len(top_items) >= 5, f"{len(top_items)} 个")

    emitted: list[int] = []
    scene.selectionChanged.connect(lambda: emitted.append(1))

    def clear_selection() -> None:
        for item in scene.findChildren(base_element):
            item.set_selected(False)

    def box(rect: QRectF, reverse: bool = False) -> int:
        """模拟一次 Ctrl + 拖拽；reverse=True 表示从右下往左上拖。"""
        clear_selection()
        emitted.clear()
        frame = scene.frame_select
        if reverse:
            frame.receive_start_pos(rect.bottomRight())
            frame.receive_end_pos(rect.topLeft())
        else:
            frame.receive_start_pos(rect.topLeft())
            frame.receive_end_pos(rect.bottomRight())
        frame.finish()
        return len(scene.selected_top_level_items())

    targets = top_items[:4]
    area = targets[0].sceneBoundingRect()
    for item in targets[1:]:
        area = area.united(item.sceneBoundingRect())
    # 留一圈边距：贴着包围盒边界时浮点误差会让 contains() 时真时假
    area = area.adjusted(-60.0, -60.0, 60.0, 60.0)

    # ---------------------------------------------------------------- 几何
    hit = box(area)
    check("右下方向拖拽能选中", hit == len(targets), f"{hit} / {len(targets)}")
    check("框选后发出一次选中变化", len(emitted) == 1, f"{len(emitted)} 次")

    hit = box(area, reverse=True)
    check("左上方向拖拽能选中（矩形已归一化）", hit == len(targets), f"{hit} 个")

    corner = area.topRight()
    clear_selection()
    frame = scene.frame_select
    frame.receive_start_pos(QPointF(corner))
    frame.receive_end_pos(QPointF(area.bottomLeft()))
    frame.finish()
    hit = len(scene.selected_top_level_items())
    check("右上 → 左下方向拖拽能选中", hit == len(targets), f"{hit} 个")

    small = QRectF(area.center().x() - 5, area.center().y() - 5, 10, 10)
    hit = box(small)
    check("框太小不选中任何图元", hit == 0, f"{hit} 个")
    check("零命中也会通知面板", len(emitted) == 1, f"{len(emitted)} 次")

    # -------------------------------------------------- current_selected 不变
    clear_selection()
    scene.set_current_select_item(scene)
    box(area)
    check(
        "框选不改 current_selected（Ctrl+拖 还能继续框）",
        scene.current_selected is scene,
        type(scene.current_selected).__name__,
    )

    # ---------------------------------------------------------- 只选顶层图元
    box(area)
    members = [
        item
        for item in scene.findChildren(base_element)
        if item.get_selected() and item.is_has_parent()
    ]
    check("框选不会单独选中组内成员", not members, f"{len(members)} 个成员被选中")
    groups = [item for item in targets if isinstance(item, group_element)]
    if groups:
        check(
            "框住整个组时选中的是组本身",
            all(item.get_selected() for item in groups),
            f"{len(groups)} 个组",
        )

    # ------------------------------------------------------------ 属性面板
    panel = NavigationContentWidget(scene=scene)
    panel.resize(940, 360)
    panel.show()
    for _ in range(4):
        app.processEvents()

    def refresh_panel():
        target = DesignWindow._panel_target(SimpleNamespace(), scene)
        panel.update_for_selected(target)
        return target
    def nav_titles() -> list[str]:
        return [
            panel.navigation_tree.topLevelItem(i).text(0)
            for i in range(panel.navigation_tree.topLevelItemCount())
        ]

    box(area)
    target = refresh_panel()
    check("多选时面板目标是列表", isinstance(target, list), type(target).__name__)
    check(
        "多选页数正确",
        nav_titles() == ["选择概要", "图元清单"],
        str(nav_titles()),
    )
    check(
        "多选头部显示数量",
        panel.header._title.text() == f"{len(target)} 个图元",
        panel.header._title.text(),
    )
    summary_page = None
    for index in range(panel.content_stack.count()):
        widget = panel.content_stack.widget(index)
        if widget.objectName() == "multi":
            summary_page = widget.widget()
    labels = (
        [label.text() for label in summary_page.findChildren(type(panel.header._title))]
        if summary_page is not None
        else []
    )
    check(
        "多选概要页列出数量/类型/包围盒",
        any("个图元" in text for text in labels)
        and any(" x " in text for text in labels),
        "、".join(labels[:6]),
    )

    # 单选：直接点选与框选都要给出同一个图元
    clear_selection()
    single = top_items[2]
    single.set_selected(True)
    target = refresh_panel()
    check("单选时面板目标是该图元", target is single, getattr(target, "get_name", lambda: "")())
    check(
        "单选分页是图元属性页",
        "常规" in nav_titles() and "选择概要" not in nav_titles(),
        str(nav_titles()),
    )

    clear_selection()
    box(single.sceneBoundingRect().adjusted(-20.0, -20.0, 40.0, 40.0))
    selected = scene.selected_top_level_items()
    target = refresh_panel()
    check(
        "框选单个图元后面板切到它",
        len(selected) == 1 and target is selected[0],
        f"{len(selected)} 个选中",
    )

    # 组内成员（Tab 循环）选中时没有顶层图元，要退回 current_selected
    group = next((item for item in top_items if isinstance(item, group_element)), None)
    member = None
    if group is not None:
        member = next(
            (child for child in group.m_children if child.get_selectable()), None
        )
    if member is not None:
        clear_selection()
        member.set_selected(True)
        scene.set_current_select_item(member)
        panel.update_for_selected(member)
        target = DesignWindow._panel_target(SimpleNamespace(), scene)
        check("组内成员单独选中时面板仍显示成员", target is member, type(target).__name__)

    # 空选 → 页面背景
    clear_selection()
    scene.set_current_select_item(scene)
    target = refresh_panel()
    check("无选中时面板回到页面背景", target is scene, type(target).__name__)
    check("空选分页为页面背景", nav_titles() == ["页面背景", "画布设置"], str(nav_titles()))

    # Esc / 清空选择：current_selected 还指着旧图元，面板不能停在它上面
    stale = top_items[4]
    clear_selection()
    stale.set_selected(True)
    scene.set_current_select_item(stale)
    panel.update_for_selected(stale)
    emitted.clear()
    scene.clearSelection()
    check("清空选择会发选中变化", len(emitted) == 1, f"{len(emitted)} 次")
    check("清空选择后旧对象确实不再选中", not stale.get_selected())
    target = refresh_panel()
    check(
        "清空选择后面板回到页面背景（不跟随失效的 current_selected）",
        target is scene,
        type(target).__name__,
    )

    # ------------------------------------------------------- 窗口侧联动（替身）
    fake_window = _FakeWindow(scene, len(top_items))
    status_bar = fake_window.status_bar
    box(area)
    fake_window._update_status()
    check(
        "状态栏显示已选数量",
        f"已选 {len(scene.selected_top_level_items())} 个" in status_bar.text,
        status_bar.text,
    )

    delete_action = fake_window.delete_selected_action
    arrange_actions = fake_window.arrange_actions
    fake_window._update_selection_actions()
    check("多选时删除可用", delete_action.enabled is True)
    check(
        "多选时排列动作可用",
        all(action.enabled for action in arrange_actions),
        str([action.enabled for action in arrange_actions]),
    )

    clear_selection()
    fake_window._update_selection_actions()
    check("无选中时删除不可用", delete_action.enabled is False)
    check(
        "无选中时排列动作不可用",
        not any(action.enabled for action in arrange_actions),
    )

    # 端到端：信号 → 窗口刷新。``_on_scene_selection_changed`` 用 sender() 判断
    # 是不是当前页场景，所以这里必须真的经信号回调，而不是直接调面板接口。
    scene.selectionChanged.disconnect()
    fake_window.property_panel = panel
    panel.update_for_selected(scene)
    scene.selectionChanged.connect(fake_window._on_scene_selection_changed)
    box(area)
    count = len(scene.selected_top_level_items())
    check(
        "框选后属性面板自动刷新（信号链路）",
        panel.header._title.text() == f"{count} 个图元",
        panel.header._title.text(),
    )
    check(
        "框选后状态栏同步选中数量",
        f"已选 {count} 个" in fake_window.status_bar.text,
        fake_window.status_bar.text,
    )
    check(
        "框选后排列动作自动可用",
        all(action.enabled for action in fake_window.arrange_actions),
        str([action.enabled for action in fake_window.arrange_actions]),
    )

    print()
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项: {FAILURES}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
