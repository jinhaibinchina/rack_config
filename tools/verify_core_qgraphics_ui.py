"""CoreQGraphics UI 外壳离屏回归。

    .venv/Scripts/python.exe tools/verify_core_qgraphics_ui.py

覆盖：主窗口装配 / 全类型属性页分派 / 属性编辑精确回写 / 创建与删除 /
图层树双模式与过滤 / 命令分发 / 撤销重做 / 保存 round-trip / 渲染稳定 /
关窗不重写页面文件。

全程只写 ``build/`` 下的临时 JSON；原始 ``page_*.json`` 只读，脚本首尾
会做哈希比对，确保设计器窗口不会像旧 ``DesignWindow`` 那样关窗时落盘。
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QGraphicsItem,
    QGraphicsView,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
)

SOURCE_PAGE = "Designer/Core/data.json/datas/design/pages/page_1.json"
TMP_PAGE = "build/_verify_ui_page.json"
TMP_SAVED = "build/_verify_ui_saved.json"
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILURES.append(name)
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def digest(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def close_rect(a: QRectF, b: QRectF, tol: float = 1e-3) -> bool:
    return all(
        abs(x - y) <= tol
        for x, y in zip(
            (a.left(), a.top(), a.width(), a.height()),
            (b.left(), b.top(), b.width(), b.height()),
        )
    )


def make_small_page() -> str:
    """从真实 page 里每类取一条，造 10 来条记录的小页面加速回归。"""
    with open(SOURCE_PAGE, encoding="utf-8") as f:
        src = json.load(f)
    by_type: dict[str, dict] = {}
    for record in src["items"]:
        by_type.setdefault(record.get("type", "?"), record)
    items = []
    for index, (type_key, record) in enumerate(sorted(by_type.items()), start=1):
        new = copy.deepcopy(record)
        new["id"] = index
        new["name"] = f"UI_{type_key}_{index}"
        new["parent_id"] = 0
        new["children_ids"] = []
        new["group_id"] = 0
        items.append(new)
    # page_1.json 里没有 checkbox / path，手工补两条以覆盖全部分页
    style = dict(by_type["rect"].get("style") or {})

    def base(iid: int, type_key: str) -> dict:
        return {
            "id": iid, "name": f"UI_{type_key}_{iid}", "type": type_key,
            "parent_id": 0, "children_ids": [], "group_id": 0,
            "center_pos": {"x": 1000.0 + iid, "y": 1000.0 + iid},
            "origin_pos": {"x": 1000.0 + iid, "y": 1000.0 + iid},
            "width": 200.0, "height": 160.0, "rotate": 0.0,
            "style": dict(style), "zValue": float(iid),
        }

    cb = base(900, "checkbox")
    cb["checked"], cb["toggleEnabled"] = False, True
    items.append(cb)
    path = base(901, "path")
    path["vertices"] = [
        {"x": 900.0, "y": 900.0, "move": True},
        {"x": 1100.0, "y": 900.0},
        {"x": 1100.0, "y": 1060.0},
    ]
    items.append(path)
    data = {
        "sceneRect": src.get("sceneRect", {"x": 0, "y": 0, "width": 0, "height": 0}),
        "backgroundColor": src.get("backgroundColor", "#bee1f59b"),
        "items": items,
    }
    os.makedirs(os.path.dirname(TMP_PAGE), exist_ok=True)
    with open(TMP_PAGE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return TMP_PAGE


def render(scene) -> QImage:
    img = QImage(800, 600, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.white)
    painter = QPainter(img)
    scene.render(painter, QRectF(0, 0, 800, 600), scene.fit_rect(0.0),
                 Qt.KeepAspectRatio)
    painter.end()
    return img


def pixel_diff(a: QImage, b: QImage) -> int:
    return sum(
        1 for y in range(0, a.height(), 4) for x in range(0, a.width(), 4)
        if a.pixelColor(x, y) != b.pixelColor(x, y)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", default="", help="输出设计器窗口截图（PNG）")
    args = ap.parse_args()
    app = QApplication.instance() or QApplication([])  # noqa: F841
    source_hash = digest(SOURCE_PAGE)
    page = make_small_page()

    from Designer.CoreQGraphics.ui import DesignerWindow
    from Designer.CoreQGraphics.g_scene import DEFAULT_SIZES, TYPE_LABELS

    print("=== 1. 主窗口装配 ===")
    window = DesignerWindow(page)
    app.processEvents()
    scene = window.scene
    check("初始图元已装载", len(scene.all_items()) >= 8,
          f"n={len(scene.all_items())}")
    check("初始未标脏（关窗不会写盘）", not scene.is_modified())
    check("三个 Dock 齐备",
          all(d is not None for d in
              (window.layers, window.toolbox, window.property_dock)))
    check("动作表覆盖常用命令", len(window.actions) >= 30,
          f"actions={len(window.actions)}")
    check("初始图元数 >= 11", len(scene.all_items()) >= 11,
          f"n={len(scene.all_items())}")
    check("菜单齐备", window.menuBar().actions().__len__() >= 5)
    check("工具箱 12 类 + 9 种 widget 变体按钮",
          len(window.toolbox.buttons) == 21,
          f"buttons={len(window.toolbox.buttons)}")
    check("基本图元组新增「贝塞尔曲线」按钮",
          "bezier" in [b.key for b in window.toolbox.buttons],
          str([b.key for b in window.toolbox.buttons][:8]))
    variant_buttons = [b.key for b in window.toolbox.buttons
                       if b.key.startswith("widget:")]
    check("工具箱含 9 种 widget 变体（含进度条 / 滑动条）",
          len(variant_buttons) == 9
          and {"widget:progressbar", "widget:slider"} <= set(variant_buttons),
          str(variant_buttons))
    check("撤销栈初始不可撤销", not window.history.can_undo())
    check("图层树初始已填充", window.layers.tree.topLevelItemCount() ==
          len(scene.all_items()),
          f"tree={window.layers.tree.topLevelItemCount()}")

    print("\n=== 2. 属性面板按类型分派 ===")
    page_titles: dict[str, list[str]] = {}
    for item in list(scene.all_items()):
        scene.clearSelection()
        item.setSelected(True)
        app.processEvents()
        titles = [window.property_panel.nav.topLevelItem(i).text(0)
                  for i in range(window.property_panel.nav.topLevelItemCount())]
        page_titles[item.TYPE] = titles
    check("每类至少 3 个分页", all(len(v) >= 3 for v in page_titles.values()),
          str({k: len(v) for k, v in page_titles.items()}))
    for type_key, expected in (("text", "文本内容"), ("image", "图片"),
                               ("checkbox", "交互"), ("widget", "控件"),
                               ("group", "组成员"), ("line", "顶点")):
        check(f"{type_key} 有「{expected}」页",
              type_key in page_titles and expected in page_titles[type_key],
              str(page_titles.get(type_key)))
    scene.clearSelection()
    app.processEvents()
    check("空选中显示页面属性",
          any(window.property_panel.nav.topLevelItem(i).text(0) == "页面属性"
              for i in range(window.property_panel.nav.topLevelItemCount())))
    for it in list(scene.all_items())[:3]:
        it.setSelected(True)
    app.processEvents()
    multi_titles = [window.property_panel.nav.topLevelItem(i).text(0)
                    for i in range(window.property_panel.nav.topLevelItemCount())]
    check("多选只显示选择概要（不列图元清单）",
          multi_titles == ["选择概要"], str(multi_titles))
    scene.clearSelection()
    app.processEvents()

    print("\n=== 3. 属性编辑精确回写 ===")
    rect = next(it for it in scene.all_items() if it.TYPE == "rect")
    rect_id = rect.item_id
    original = copy.deepcopy(rect.page_record())
    rect.set_name("UI_改名")
    rec = rect.to_page_record()
    check("名称写回 page 记录", rec["name"] == "UI_改名")
    check("属性编辑不触发几何重建",
          all(rec[k] == original[k] for k in ("center_pos", "origin_pos",
                                              "width", "height", "rotate")),
          "center/width/height/rotate 全部保持原值")
    rect.set_style_value("strokeWidth", 7)
    rect.set_style_value("fill", False)
    check("样式写回 style 子键",
          rect.to_page_record()["style"]["strokeWidth"] == 7
          and rect.to_page_record()["style"]["fill"] is False)
    check("样式编辑同样不改几何",
          rect.to_page_record()["center_pos"] == original["center_pos"])

    cx, cy = rect.page_center()
    w, h = rect.page_size()
    rect.set_page_center(cx + 50.0, cy + 25.0)
    check("set_page_center 精确写入",
          rect.page_center() == (cx + 50.0, cy + 25.0)
          and rect.to_page_record()["center_pos"]["x"] == cx + 50.0)
    rect.set_page_size(w * 2.0, h * 2.0)
    check("set_page_size 精确写入",
          rect.to_page_record()["width"] == w * 2.0
          and abs(rect.boundingRect().width() - scene.projection.size(w * 2, h * 2)[0]) < 1e-6)
    rect.set_page_angle(15.0)
    check("set_page_angle 精确写入",
          rect.to_page_record()["rotate"] == 15.0
          and abs(rect.rotation() + 15.0) < 1e-9)
    check("精确几何写入不触发重建（_geo_dirty 保持 False）",
          rect._dirty and not rect._geo_dirty)

    text = next(it for it in scene.all_items() if it.TYPE == "text")
    text.set_page_field("context", "面板测试文本")
    check("text context 写回", text.to_page_record()["context"] == "面板测试文本")

    # 走一次真实控件链路：找到名称 QLineEdit，模拟编辑完成
    rect.setSelected(True)
    app.processEvents()
    current_page = window.property_panel.stack.currentWidget()
    line_edits = current_page.findChildren(QLineEdit) if current_page else []
    check("当前页有可编辑控件", bool(line_edits), f"n={len(line_edits)}")
    name_edit = next((w for w in line_edits if w.text() == rect.get_name()),
                     line_edits[0] if line_edits else None)
    if name_edit is not None:
        name_edit.setText("控件链路改名")
        name_edit.editingFinished.emit()
        check("控件编辑写回图元并标脏",
              rect.get_name() == "控件链路改名" and scene.is_modified(),
              f"name={rect.get_name()}")

    print("\n=== 4. 创建 / 删除 ===")
    base_count = len(scene.all_items())
    made = {}
    for key in TYPE_LABELS:
        item = scene.create_item(key, center=(1000.0, 1000.0))
        made[key] = item
    check("12 类全部可创建", all(v is not None for v in made.values()),
          str({k: (v.TYPE if v else None) for k, v in made.items()}))
    check("创建后索引与数量同步",
          len(scene.all_items()) == base_count + len(TYPE_LABELS)
          and all(v.item_id in scene.index.by_id for v in made.values()))
    ids = [v.item_id for v in made.values()]
    check("新建 id 唯一且不与旧 id 冲突", len(set(ids)) == len(ids)
          and not (set(ids) & {i.item_id for i in scene.all_items() if i not in made.values()}))
    check("新建记录字段完整",
          all("center_pos" in made[k].page_record() or k == "line" for k in made))
    check("page_data 条数与场景一致",
          len(scene.page_data()["items"]) == len(scene.all_items()))
    removed = scene.delete_items(list(made.values()))
    check("删除清理索引 / order",
          removed == len(TYPE_LABELS)
          and len(scene.all_items()) == base_count
          and all(v.item_id not in scene.index.by_id for v in made.values())
          and all(iid not in scene.index.order for iid in ids))

    # 组被删除时递归删除全部成员（旧 Core base_element.Delete 语义）
    ga = scene.create_item("rect", center=(1200.0, 1200.0), size=(60.0, 40.0))
    gb = scene.create_item("rect", center=(1260.0, 1240.0), size=(60.0, 40.0))
    scene.clearSelection()
    ga.setSelected(True)
    gb.setSelected(True)
    grp = scene.group_selected()
    check("成组成功（组 + 2 个成员）",
          grp is not None and len(scene.index.descendants(grp.item_id)) == 2,
          f"desc={len(scene.index.descendants(grp.item_id)) if grp else '-'}")
    scene.clearSelection()
    grp.setSelected(True)
    app.processEvents()
    before = len(scene.all_items())
    QTest.keyPress(window.view, Qt.Key_Delete)
    app.processEvents()
    check("Delete 键删组连带递归删除成员",
          before == base_count + 3
          and len(scene.all_items()) == base_count
          and not ({grp.item_id, ga.item_id, gb.item_id} & set(scene.index.by_id))
          and not ({grp.item_id, ga.item_id, gb.item_id} & set(scene.index.order))
          and len(scene.page_data()["items"]) == base_count,
          f"before={before} after={len(scene.all_items())}")

    print("\n=== 5. 图层树：双模式 / 过滤 / 选中联动 ===")
    window.layers.mode_box.setCurrentIndex(0)
    window.layers.filter_edit.clear()
    window.layers.refresh()
    check("图层顺序模式行数 = 图元数",
          window.layers.tree.topLevelItemCount() == len(scene.all_items()))
    window.layers.filter_edit.setText("UI_")
    window.layers.refresh()
    filtered = window.layers.tree.topLevelItemCount()
    check("名称过滤生效", 0 < filtered < len(scene.all_items()),
          f"filtered={filtered}")
    window.layers.filter_edit.clear()
    window.layers.mode_box.setCurrentIndex(1)
    window.layers.refresh()
    check("分组树模式可切换",
          window.layers.tree.topLevelItemCount() <= len(scene.all_items()))
    target = scene.all_items()[0]
    target.setSelected(True)
    app.processEvents()
    check("场景选中同步到树",
          target.item_id in window.layers.selected_ids(),
          f"selected={window.layers.selected_ids()[:3]}")
    window.layers.mode_box.setCurrentIndex(0)
    window.layers.refresh()

    print("\n=== 6. 命令分发 / 撤销重做 ===")
    scene.clearSelection()
    pick = [it for it in scene.all_items() if it.has_explicit_geometry()][:3]
    for it in pick:
        it.setSelected(True)
    app.processEvents()
    before_z = [it.zValue() for it in pick]
    window._do("z_front")
    check("z_front 提升层级", all(it.zValue() > z for it, z in zip(pick, before_z)))
    window._do("align_left")
    lefts = [it.page_bounding_rect().left() for it in pick]
    check("左对齐使包围盒左边一致", max(lefts) - min(lefts) < 1e-6,
          f"lefts={[round(v, 2) for v in lefts]}")
    window._do("group")
    groups = [it for it in scene.all_items() if it.TYPE == "group"]
    check("成组产生 group 图元", len(groups) >= 1)
    group = groups[-1]
    scene.clearSelection()
    group.setSelected(True)
    window._do("ungroup")
    check("解组释放子图元",
          all(it.parent_id == 0 for it in pick))

    scene.clearSelection()
    for it in list(scene.all_items())[:2]:
        it.setSelected(True)
    app.processEvents()
    count_before = len(scene.all_items())
    sel_count = len(scene.selected_items())
    orig_sel_ids = sorted(it.item_id for it in scene.selected_items())
    window._do("duplicate")
    check("复制按选中数增加图元",
          len(scene.all_items()) == count_before + sel_count,
          f"{count_before} -> {len(scene.all_items())} (sel={sel_count})")
    window._do("undo")
    check("撤销恢复数量", len(scene.all_items()) == count_before,
          f"n={len(scene.all_items())}")
    window._do("redo")
    check("重做恢复数量", len(scene.all_items()) == count_before + sel_count,
          f"n={len(scene.all_items())}")

    # 撤销/重做要连同「选中 + 脏标记」一起回退：restore() 会重建全部图元，
    # 只恢复页面数据的话属性面板会跳回「页面属性」、标题的 * 也会错。
    hist = window.history
    dup_ids = sorted(it.item_id for it in scene.selected_items())
    window._do("undo")
    undone_ids = sorted(it.item_id for it in scene.selected_items())
    check("撤销后恢复操作前的选中（不是清空）",
          undone_ids == orig_sel_ids,
          f"want={orig_sel_ids} got={undone_ids}")
    panel_target = window.property_panel._target
    if isinstance(panel_target, (list, tuple)):
        panel_ids = sorted(it.item_id for it in panel_target)
    else:
        panel_ids = [getattr(panel_target, "item_id", None)]
    check("撤销后属性面板仍绑定选中的图元",
          panel_target is not None and panel_ids == orig_sel_ids,
          f"target_ids={panel_ids} want={orig_sel_ids}")
    window._do("redo")
    check("重做后恢复副本选中",
          sorted(it.item_id for it in scene.selected_items()) == dup_ids,
          f"want={dup_ids}")
    # 保存点与撤销点的「是否已存盘」必须随历史状态走，不能一律沿用当前值
    scene.mark_saved()
    hist.mark_saved()
    window._do("undo")
    check("保存后撤销应重新标脏（内容与磁盘不同）", scene.is_modified())
    window._do("redo")
    check("重做回保存点应恢复未标脏", not scene.is_modified())

    # 独立小场景：连续撤销到栈底，名称 / 选中 / 脏标记都回到初始状态
    from Designer.CoreQGraphics.g_scene import GraphicsScene  # noqa: E402
    from Designer.CoreQGraphics.ui.history import PageHistory  # noqa: E402

    hs = GraphicsScene()
    ha = hs.create_item("rect", center=(1000.0, 1000.0))
    hs.create_item("rect", center=(1300.0, 1000.0))
    hh = PageHistory(hs)
    name0 = ha.get_name()
    hs.select_items([ha])
    ha.set_page_field("name", "改过")
    hh.commit()
    ha.set_page_field("name", "又改过")
    hh.commit()
    while hh.can_undo():
        hh.undo()
    check("连续撤销到栈底：名称 / 选中 / 脏标记回到初始",
          hs.find_item(ha.item_id).get_name() == name0
          and [it.item_id for it in hs.selected_items()] == [ha.item_id]
          and not hs.is_modified(),
          f"name={hs.find_item(ha.item_id).get_name()} "
          f"sel={[it.item_id for it in hs.selected_items()]} "
          f"modified={hs.is_modified()}")

    print("\n=== 7. 保存 round-trip ===")
    scene.save_page(TMP_SAVED)
    with open(TMP_SAVED, encoding="utf-8") as f:
        saved = json.load(f)
    check("保存后顶层结构完整",
          {"sceneRect", "backgroundColor", "items"} <= set(saved))
    check("保存后未标脏", not scene.is_modified())
    rect_rec = next((r for r in saved["items"] if r.get("id") == rect_id), {})
    check("改名/样式/几何均已落盘",
          rect_rec.get("name") == "控件链路改名"
          and rect_rec.get("style", {}).get("strokeWidth") == 7
          and rect_rec.get("rotate") == 15.0,
          f"name={rect_rec.get('name')} sw={rect_rec.get('style', {}).get('strokeWidth')} "
          f"rotate={rect_rec.get('rotate')}")
    from Designer.CoreQGraphics import GraphicsScene
    reloaded = GraphicsScene(scene.projection)
    reloaded.load_page(TMP_SAVED)
    check("重新加载 id 集合一致",
          set(reloaded.index.by_id) == set(scene.index.by_id),
          f"{len(reloaded.index.by_id)} vs {len(scene.index.by_id)}")
    rect2 = reloaded.find_item(rect_id)
    check("重新加载几何一致",
          rect2 is not None
          and abs(rect2.page_center()[0] - rect_rec["center_pos"]["x"]) < 1e-3
          and rect2.to_page_record()["rotate"] == 15.0)

    print("\n=== 8. 渲染稳定 ===")
    a, b = render(scene), render(scene)
    check("编辑后两次渲染逐像素一致", pixel_diff(a, b) == 0)

    print("\n=== 8.5 手动绘制（CAD 式分点落点） ===")
    window.show()
    app.processEvents()
    view = window.view
    scene = window.scene
    base_count = len(scene.all_items())
    view.set_draw_tool("rect")
    check("进入绘制模式后禁用框选橡皮筋",
          view.dragMode() == QGraphicsView.NoDrag)
    # 矩形 = 两击：起点、终点（参考 Core 的 begin_draw 流程）
    vis = view.mapToScene(view.viewport().rect()).boundingRect()
    a = QPointF(vis.left() + vis.width() * 0.35, vis.top() + vis.height() * 0.35)
    b = QPointF(vis.left() + vis.width() * 0.65, vis.top() + vis.height() * 0.65)
    va = view.mapFromScene(a)
    vb = view.mapFromScene(b)
    # 第一击：仅落起点。图元在激活工具时已预创建（对齐 Core 的 begin_draw），
    # 但应处于「绘制进行中」状态、尚未完成。
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=va)
    app.processEvents()
    check("矩形第一击后处于绘制进行中", scene.drawing_active(),
          f"count={len(scene.all_items())}")
    check("第一击后图元尚未完成（仍是绘制态）", scene.drawing_active())
    # 第二击：落终点，完成矩形
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=vb)
    app.processEvents()
    check("两击后新增一个图元", len(scene.all_items()) == base_count + 1,
          f"n={len(scene.all_items())}")
    check("绘制进行中标志已清除", not scene.drawing_active())
    drawn = scene.all_items()[-1]
    check("新增的是矩形", drawn.TYPE == "rect", f"type={drawn.TYPE}")
    check("绘制后历史可撤销", window.history.can_undo())
    expected = QRectF(a, b).normalized()
    got = drawn.view_bounding_rect()
    # QTest 鼠标坐标是整数像素，mapToScene 回算存在 <1px 视口误差，
    # 换算到场景坐标约几个单位，此为预期精度，非逻辑错误。
    scale = view.transform().m11() or 1.0
    tol = 6.0 / scale
    check("绘制矩形视图包围盒与两击范围一致",
          close_rect(expected, got, tol),
          f"exp={expected} got={got} tol={tol:.1f}")
    # Esc 退出绘制模式（无进行中绘制时）
    QTest.keyPress(view, Qt.Key_Escape)
    app.processEvents()
    check("Esc 退出绘制模式", not view._draw_type)
    view.set_draw_tool(None)

    # 线 = 两击（head/end），验证几何 setter 生效
    # 取斜向两点，避免触发「细轴强制加厚 60 单位」的窄线规则
    view.set_draw_tool("line")
    before = len(scene.all_items())
    c = QPointF(vis.left() + vis.width() * 0.2, vis.top() + vis.height() * 0.3)
    d = QPointF(vis.left() + vis.width() * 0.8, vis.top() + vis.height() * 0.7)
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=view.mapFromScene(c))
    app.processEvents()
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=view.mapFromScene(d))
    app.processEvents()
    check("两击线新增一个图元", len(scene.all_items()) == before + 1,
          f"n={len(scene.all_items())}")
    line_item = scene.all_items()[-1]
    check("新增的是线", line_item.TYPE == "line", f"type={line_item.TYPE}")
    line_expected = QRectF(c, d).normalized()
    line_got = line_item.view_bounding_rect()
    check("绘制线视图包围盒与两击范围一致",
          close_rect(line_expected, line_got, tol),
          f"exp={line_expected} got={line_got} tol={tol:.1f}")
    view.set_draw_tool(None)

    # 多边形 = 多击 + 右键闭合（验证顶点类 setter 与右键闭合路径）
    view.set_draw_tool("polygon")
    before_p = len(scene.all_items())
    poly_pts = [
        QPointF(vis.left() + vis.width() * 0.3, vis.top() + vis.height() * 0.3),
        QPointF(vis.left() + vis.width() * 0.7, vis.top() + vis.height() * 0.3),
        QPointF(vis.left() + vis.width() * 0.7, vis.top() + vis.height() * 0.7),
    ]
    for pp in poly_pts:
        QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=view.mapFromScene(pp))
        app.processEvents()
    check("多边形三击后仍处于绘制进行中", scene.drawing_active())
    QTest.mouseClick(view.viewport(), Qt.RightButton,
                    pos=view.mapFromScene(
                        QPointF(vis.left() + vis.width() * 0.3,
                                vis.top() + vis.height() * 0.7)))
    app.processEvents()
    check("右键闭合后新增一个图元", len(scene.all_items()) == before_p + 1,
          f"n={len(scene.all_items())}")
    poly_item = scene.all_items()[-1]
    check("新增的是多边形", poly_item.TYPE == "polygon", f"type={poly_item.TYPE}")
    check("多边形顶点数=4（含右键闭合点）",
          len(poly_item.page_record().get("vertices", [])) == 4,
          f"v={len(poly_item.page_record().get('vertices', []))}")
    check("多边形绘制进行中标志已清除", not scene.drawing_active())
    view.set_draw_tool(None)

    print("\n=== 8.6 左键按下不再拖动图元（移动只走双击跟手）===")
    view = window.view
    scene = window.scene
    view.set_draw_tool(None)
    scene.set_scene_mode(False)
    prev_snap = view.snap.enabled
    view.snap.enabled = False  # 屏蔽 T 门控吸附，避免干扰位置断言
    rect = scene.create_item("rect", center=(1200.0, 1200.0))
    rect.setSelected(True)
    view.centerOn(rect)
    app.processEvents()
    check("图元默认不可移动（ItemIsMovable=False）",
          not bool(rect.flags() & QGraphicsItem.ItemIsMovable))

    def _drag_item(dx, dy, mods=Qt.NoModifier) -> None:
        p0 = view.mapFromScene(rect.scenePos())
        p0 = QPoint(int(p0.x()), int(p0.y()))
        p1 = QPoint(p0.x() + dx, p0.y() + dy)
        QTest.mousePress(view.viewport(), Qt.LeftButton, mods, p0)
        QTest.mouseMove(view.viewport(), p1)
        QTest.mouseMove(view.viewport(), p1)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, mods, p1)
        app.processEvents()

    before_no_ctrl = QPointF(rect.scenePos())
    _drag_item(60, 40)
    check("左键按下拖动不改位置",
          abs(rect.scenePos().x() - before_no_ctrl.x()) < 1e-6
          and abs(rect.scenePos().y() - before_no_ctrl.y()) < 1e-6,
          f"before={before_no_ctrl} after={rect.scenePos()}")

    QTest.keyPress(view, Qt.Key_Control)
    app.processEvents()
    check("按住 CTRL 也不再开启可拖动",
          not bool(rect.flags() & QGraphicsItem.ItemIsMovable))
    before_ctrl = QPointF(rect.scenePos())
    _drag_item(60, 40, Qt.ControlModifier)
    QTest.keyRelease(view, Qt.Key_Control)
    app.processEvents()
    check("CTRL + 左键拖动同样不改位置",
          abs(rect.scenePos().x() - before_ctrl.x()) < 1e-6
          and abs(rect.scenePos().y() - before_ctrl.y()) < 1e-6,
          f"before={before_ctrl} after={rect.scenePos()}")
    check("拖动尝试后图元仍保持选中（按下只做选择）", rect.isSelected())
    scene.delete_items([rect])
    view.snap.enabled = prev_snap
    app.processEvents()

    print("\n=== 8.7 旋转中心可设置 ===")
    rot = scene.create_item("rect", center=(1000.0, 1000.0))
    check("默认以几何中心旋转（transformOrigin 为 0）",
          rot.transformOriginPoint().isNull())
    check("默认 page_origin == page_center", rot.page_origin() == rot.page_center())
    rot.set_page_origin(1100.0, 1000.0)
    ox, oy = rot.page_origin()
    check("设置旋转中心后 transformOrigin 非零",
          not rot.transformOriginPoint().isNull())
    check("page_origin 反映新支点", abs(ox - 1100.0) < 0.5 and abs(oy - 1000.0) < 0.5,
          f"origin=({ox:.3f},{oy:.3f})")
    rec = rot.to_page_record()
    check("序列化 origin_pos 为自定义支点",
          abs(rec["origin_pos"]["x"] - 1100.0) < 0.5
          and abs(rec["origin_pos"]["y"] - 1000.0) < 0.5,
          str(rec.get("origin_pos")))
    # 绕自定义支点旋转 90°：可视中心会绕支点移动（默认中心旋转则不动）
    rot.set_page_angle(90.0)
    rec2 = rot.to_page_record()
    moved = (abs(rec2["center_pos"]["x"] - 1000.0) > 1.0
             or abs(rec2["center_pos"]["y"] - 1000.0) > 1.0)
    check("自定义支点下旋转会绕支点移动中心", moved, str(rec2.get("center_pos")))
    check("旋转后 origin_pos 仍为支点",
          abs(rec2["origin_pos"]["x"] - 1100.0) < 0.5
          and abs(rec2["origin_pos"]["y"] - 1000.0) < 0.5)
    scene.delete_items([rot])

    print("\n=== 8.8 图元可设置父对象 ===")
    par = scene.create_item("rect", center=(500.0, 500.0))
    kid = scene.create_item("rect", center=(600.0, 600.0))
    check("新建子图元默认无父对象", kid.parent_id == 0)
    ok = kid.set_page_parent(par.item_id)
    check("设置父对象成功", ok and kid.parent_id == par.item_id)
    check("场景索引已建立父子链",
          kid.item_id in [it.item_id for it in scene.index.descendants(par.item_id)])
    before_kid = kid.scenePos()
    before_par = par.scenePos()
    par.setPos(before_par + QPointF(50.0, 30.0))
    app.processEvents()
    dx = kid.scenePos().x() - before_kid.x()
    dy = kid.scenePos().y() - before_kid.y()
    check("父图元移动时子图元随动", abs(dx - 50.0) < 1e-6 and abs(dy - 30.0) < 1e-6,
          f"d=({dx:.3f},{dy:.3f})")
    check("拒绝把父对象设成自己", kid.set_page_parent(kid.item_id) is False)
    check("可清空父对象", kid.set_page_parent(0) is True and kid.parent_id == 0)
    scene.delete_items([par, kid])
    app.processEvents()

    print("\n=== 8.9 选中图元显示旋转中心红点（无 ID 标签） ===")
    # 用像素级断言：红点 = 旋转中心；右上方的白色圆角框 = 已移除的 ID 标签
    tag = scene.create_item("rect", center=(900.0, 700.0))
    tag.set_page_size(300.0, 200.0)
    scene.clearSelection()
    tag.setSelected(True)
    window.view.centerOn(tag.center_scene_point())
    app.processEvents()

    def _scan(img, cx, cy, radius, pred) -> bool:
        for yy in range(int(round(cy)) - radius, int(round(cy)) + radius + 1):
            for xx in range(int(round(cx)) - radius, int(round(cx)) + radius + 1):
                if 0 <= xx < img.width() and 0 <= yy < img.height():
                    if pred(img.pixelColor(xx, yy)):
                        return True
        return False

    def _scan_rect(img, x0, y0, x1, y1, pred) -> bool:
        """矩形扫码（用于避开中心红点自带的白色描边）。"""
        for yy in range(int(y0), int(y1) + 1):
            for xx in range(int(x0), int(x1) + 1):
                if 0 <= xx < img.width() and 0 <= yy < img.height():
                    if pred(img.pixelColor(xx, yy)):
                        return True
        return False

    def _has_label(img, x, y) -> bool:
        # 旧版 ID 标签画在中心点右上方（x+6, y-21 起）；这块区域若还出现
        # 白底框，说明标签没去掉。避开中心红点自带的白色描边。
        return _scan_rect(img, x + 7, y - 30, x + 44, y - 8, _is_white)

    def _is_dot(c) -> bool:
        return c.red() > 150 and c.green() < 120 and c.blue() < 120

    def _is_white(c) -> bool:
        # 旧版标签是半透明白底（alpha 225），叠在灰色图元上约 240；纯白/
        # 浅绿背景会被下面的近中性判定或蓝通道阈值排除。
        return (c.red() > 215 and c.green() > 215 and c.blue() > 215
                and abs(c.red() - c.blue()) < 20)

    def _shot():
        window.view.viewport().update()
        app.processEvents()
        return window.view.viewport().grab().toImage()

    check("默认开启中心点标记", window.view.show_ids is True)
    cpt = tag.center_scene_point()
    lp = tag.mapToScene(tag._local_rect.center())
    check("center_scene_point 等于局部中心映射",
          abs(cpt.x() - lp.x()) < 1e-6 and abs(cpt.y() - lp.y()) < 1e-6,
          f"c=({cpt.x():.2f},{cpt.y():.2f}) local=({lp.x():.2f},{lp.y():.2f})")
    pvt = tag.pivot_scene_point()
    check("默认支点就是几何中心（标识与中心重合）",
          abs(pvt.x() - cpt.x()) < 1e-6 and abs(pvt.y() - cpt.y()) < 1e-6,
          f"pivot=({pvt.x():.2f},{pvt.y():.2f})")
    vp = window.view.mapFromScene(cpt)
    img = _shot()
    check("选中项旋转中心画有红色小圆点", _scan(img, vp.x(), vp.y(), 5, _is_dot),
          f"vp=({vp.x():.1f},{vp.y():.1f})")
    check("旋转中心旁不再画白色 ID 标签", not _has_label(img, vp.x(), vp.y()))

    # 关闭开关后不再绘制。属性面板的分页内容会让底部 Dock 重新布局，视口高度
    # 会变一次（AnchorViewCenter 因此平移画面），断言前重取中心点的屏幕位置。
    app.processEvents()
    vp = window.view.mapFromScene(cpt)
    window.actions["toggle_ids"].setChecked(False)
    window._do("toggle_ids")
    img_off = _shot()
    check("关闭『显示中心点标记』后不再画红点",
          not _scan(img_off, vp.x(), vp.y(), 5, _is_dot))
    window.actions["toggle_ids"].setChecked(True)
    window._do("toggle_ids")
    check("重新开启后红点恢复", _scan(_shot(), vp.x(), vp.y(), 5, _is_dot))

    # 运行模式不标注（选中被清空，且 drawForeground 直接跳过）
    scene.set_scene_mode(True)
    app.processEvents()
    img_run = _shot()
    check("运行模式下不画中心点标记",
          not _scan(img_run, vp.x(), vp.y(), 5, _is_dot))
    scene.set_scene_mode(False)
    scene.delete_items([tag])
    app.processEvents()

    print("\n=== 8.10 右键不清空选中（可继续改属性） ===")
    # Qt 的 QGraphicsView 在右键按下时就会 clearSelection（裸视图实测同样清空），
    # 导致右键菜单 / 属性面板失去目标；视图已接管右键。
    a = scene.create_item("rect", center=(800.0, 900.0))
    a.set_page_size(300.0, 200.0)
    b = scene.create_item("circle", center=(1400.0, 900.0))
    app.processEvents()
    window.view.fit_content()
    app.processEvents()

    def _sel_ids() -> list[int]:
        return sorted(it.item_id for it in scene.selected_items())

    def _rclick(vp_pt) -> None:
        p = QPoint(int(vp_pt.x()), int(vp_pt.y()))
        QTest.mousePress(window.view.viewport(), Qt.RightButton, Qt.NoModifier, p)
        QTest.mouseRelease(window.view.viewport(), Qt.RightButton, Qt.NoModifier, p)
        app.processEvents()

    scene.clearSelection()
    a.setSelected(True)
    app.processEvents()
    _rclick(window.view.mapFromScene(a.center_scene_point()))
    check("右键已选中图元后仍保持选中", _sel_ids() == [a.item_id], str(_sel_ids()))

    _rclick(window.view.mapFromScene(b.center_scene_point()))
    check("右键未选中图元则只选中它", _sel_ids() == [b.item_id], str(_sel_ids()))

    keep = _sel_ids()
    _rclick(QPoint(6, 6))
    check("右键空白处保持原选中", _sel_ids() == keep, str(_sel_ids()))

    # 面板仍绑定选中项
    tgt = window.property_panel._target
    check("属性面板仍绑定选中图元",
          tgt is not None and not isinstance(tgt, (list, tuple))
          and tgt.item_id == b.item_id,
          repr(getattr(tgt, "item_id", tgt)))

    menu = window.view.build_context_menu()
    labels = [act.text() for act in menu.actions() if act.text()]
    check("右键菜单含「属性…」", "属性…" in labels, str(labels[:3]))

    fired: list[str] = []
    window.view.actionTriggered.connect(fired.append)
    next(act for act in menu.actions() if act.text() == "属性…").trigger()
    app.processEvents()
    check("「属性…」命令已下发", fired == ["property"], str(fired))
    check("「属性…」不会清空选中", _sel_ids() == keep, str(_sel_ids()))

    scene.delete_items([a, b])
    app.processEvents()

    print("\n=== 8.11 父对象旋转 / 平移带动子图元位姿 ===")
    par = scene.create_item("rect", center=(1000.0, 1000.0))
    par.set_page_size(400.0, 400.0)
    kid = scene.create_item("rect", center=(1200.0, 1000.0))
    kid.set_page_size(100.0, 100.0)
    grand = scene.create_item("rect", center=(1300.0, 1000.0))
    grand.set_page_size(60.0, 60.0)
    poly_kid = scene.create_item("polygon", center=(1200.0, 1200.0))
    kid.set_page_parent(par.item_id)
    poly_kid.set_page_parent(par.item_id)
    grand.set_page_parent(kid.item_id)          # 孙级：同一套刚体变换
    kid.set_page_origin(1250.0, 1000.0)         # 子图元自己也带铰链支点
    app.processEvents()
    poly_before = poly_kid.page_center()
    par.set_page_angle(90.0)                    # 绕 (1000,1000) 转 90°
    app.processEvents()

    def _close_pt(a, b, tol: float = 1e-6) -> bool:
        return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol

    check("子图元中心绕父对象中心转 90°",
          _close_pt(kid.page_center(), (1000.0, 1200.0)),
          str(kid.page_center()))
    check("孙图元同样跟着转",
          _close_pt(grand.page_center(), (1000.0, 1300.0)),
          str(grand.page_center()))
    check("子图元角度叠加父对象角度", abs(kid.page_angle() - 90.0) < 1e-6,
          f"angle={kid.page_angle()}")
    check("子图元的支点也随刚体变换",
          _close_pt(kid.page_origin(), (1000.0, 1250.0), 1e-6),
          str(kid.page_origin()))
    check("顶点类子图元（polygon）绕父对象中心转",
          _close_pt(poly_kid.page_center(),
                    (1000.0 - (poly_before[1] - 1000.0),
                     1000.0 + (poly_before[0] - 1000.0)), 1e-6),
          str(poly_kid.page_center()))
    check("顶点已烘焙进记录（Qt 旋转归零）",
          abs(poly_kid.rotation()) < 1e-9
          and abs(float(poly_kid.page_record().get("rotate", 0.0)) - 90.0) < 1e-6
          and abs(poly_kid.page_angle() - 90.0) < 1e-6,
          f"rotation={poly_kid.rotation()} "
          f"rotate={poly_kid.page_record().get('rotate')} "
          f"angle={poly_kid.page_angle()}")
    # 记录里 rotate 存「已烘焙的真实朝向」，顶点也已经是旋转后的绝对坐标：
    # 重新建一个图元不能把同一个旋转再施加一次（旧 Core 的读法是先反旋再正旋）
    poly_rec = poly_kid.to_page_record()
    poly_fresh = type(poly_kid)(poly_rec, scene.projection)
    scene.addItem(poly_fresh)
    app.processEvents()
    check("顶点类子图元存盘后重新加载不会二次旋转",
          close_rect(poly_fresh.page_bounding_rect(),
                     poly_kid.page_bounding_rect(), 1e-6),
          f"{poly_fresh.page_bounding_rect()} vs {poly_kid.page_bounding_rect()}")
    scene.delete_items([poly_fresh])
    app.processEvents()

    kid_before = kid.page_center()
    par.set_page_center(1150.0, 1050.0)          # 整体平移 (+150, +50)
    app.processEvents()
    check("父对象平移子图元同步平移",
          _close_pt(kid.page_center(),
                    (kid_before[0] + 150.0, kid_before[1] + 50.0)),
          f"{kid_before} -> {kid.page_center()}")
    check("平移后子图元角度不变", abs(kid.page_angle() - 90.0) < 1e-6)

    print("\n=== 8.12 有父对象的图元：只锁平移，姿态仍可自转 ===")
    check("translate_locked 反映父子关系",
          kid.translate_locked() and grand.translate_locked()
          and not par.translate_locked())
    keep = kid.page_center()
    check("子图元 set_page_center 被拒绝（不能自行平移）",
          kid.set_page_center(2000.0, 2000.0) is False
          and _close_pt(kid.page_center(), keep), str(kid.page_center()))
    angle0 = kid.page_angle()
    par_angle0 = par.page_angle()
    kid.set_page_angle(45.0)
    check("子图元 set_page_angle 生效（可自行旋转）",
          abs(kid.page_angle() - 45.0) < 1e-6,
          f"angle={kid.page_angle()}")
    check("子图元自转不改父对象角度",
          abs(par.page_angle() - par_angle0) < 1e-6, f"par={par.page_angle()}")
    kid.rotate_by(10.0)
    check("子图元 rotate_by 生效（视图增量 → page -10°）",
          abs(kid.page_angle() - 35.0) < 1e-6, f"angle={kid.page_angle()}")
    check("子图元自转后可视中心仍绕自身支点（半径不变）",
          abs(math.hypot(kid.page_center()[0] - kid.page_origin()[0],
                         kid.page_center()[1] - kid.page_origin()[1]) -
              math.hypot(keep[0] - kid.page_origin()[0],
                         keep[1] - kid.page_origin()[1])) < 1.0,
          f"c={kid.page_center()} o={kid.page_origin()}")
    kid.set_page_angle(angle0)
    app.processEvents()
    check("父 / 子图元都不可拖动（左键拖动已取消）",
          not bool(kid.flags() & QGraphicsItem.ItemIsMovable)
          and not bool(par.flags() & QGraphicsItem.ItemIsMovable))

    def _layout_disabled(item) -> int:
        window.property_panel.update_for_selected(item)
        app.processEvents()
        page = next((window.property_panel.stack.widget(i)
                     for i in range(window.property_panel.stack.count())
                     if window.property_panel.stack.widget(i).objectName() == "layout"),
                    None)
        if page is None:
            return -1
        return sum(1 for box in page.findChildren(QDoubleSpinBox) if not box.isEnabled())

    check("子图元布局页只禁用中心 X/Y（旋转仍可编辑）", _layout_disabled(kid) == 2,
          f"disabled={_layout_disabled(kid)}")
    check("父图元布局页仍可编辑", _layout_disabled(par) == 0,
          f"disabled={_layout_disabled(par)}")

    # 按下左键拖子图元：只选中它自己，不再代理成「拖根父对象」
    prev_snap2 = view.snap.enabled
    view.snap.enabled = False
    scene.clearSelection()
    kid.setSelected(True)
    window.view.centerOn(kid.center_scene_point())
    app.processEvents()
    par_before = par.page_center()
    kid_before = kid.page_center()
    p0 = window.view.mapFromScene(kid.center_scene_point())
    p0 = QPoint(int(p0.x()), int(p0.y()))
    p1 = QPoint(p0.x() + 40, p0.y() + 30)
    QTest.mousePress(view.viewport(), Qt.LeftButton, pos=p0)
    QTest.mouseMove(view.viewport(), pos=p1)
    QTest.mouseMove(view.viewport(), pos=p1)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=p1)
    app.processEvents()
    check("左键拖子图元不移动父 / 子图元",
          _close_pt(par.page_center(), par_before, 1e-3)
          and _close_pt(kid.page_center(), kid_before, 1e-3),
          f"par {par_before}->{par.page_center()} kid {kid_before}->{kid.page_center()}")
    check("按下子图元只选中它自己（不再改成选根父）",
          [it.item_id for it in scene.selected_items()] == [kid.item_id],
          str([it.item_id for it in scene.selected_items()]))

    # 斜图元 + 自定义支点：跟手位移必须严格等于光标位移。
    # 跟手走的是 moveBy(场景增量)，不以 pos()/scenePos() 为基准，所以支点只在
    # 旋转时参与，不该影响平移量。
    par.set_page_size(300.0, 200.0)
    _pc = par.page_center()
    par.set_page_origin(_pc[0] + 100.0, _pc[1] - 80.0)
    par.set_page_angle(29.0)
    app.processEvents()
    view.snap.enabled = False
    scene.clearSelection()
    par.setSelected(True)
    window.view.resetTransform()
    window.view.centerOn(par.center_scene_point())
    app.processEvents()
    _q = window.view.mapFromScene(par.center_scene_point())
    _q = QPoint(int(_q.x()), int(_q.y()))
    _q2 = QPoint(_q.x() + 70, _q.y() - 40)
    QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, _q)
    app.processEvents()
    check("斜图元双击进入跟手", view.is_following())
    _pc_before = par.page_center()
    _a = view.mapToScene(_q)
    _b = view.mapToScene(_q2)
    _pa = scene.projection.inverse_point(_a.x(), _a.y())
    _pb = scene.projection.inverse_point(_b.x(), _b.y())
    QTest.mouseMove(view.viewport(), _q2)
    app.processEvents()
    _pc_after = par.page_center()
    check("斜图元跟手：位移 = 光标位移（自定义支点不影响）",
          abs((_pc_after[0] - _pc_before[0]) - (_pb[0] - _pa[0])) < 1.0
          and abs((_pc_after[1] - _pc_before[1]) - (_pb[1] - _pa[1])) < 1.0,
          f"exp=({_pb[0]-_pa[0]:.2f},{_pb[1]-_pa[1]:.2f}) "
          f"act=({_pc_after[0]-_pc_before[0]:.2f},{_pc_after[1]-_pc_before[1]:.2f})")
    QTest.keyPress(view, Qt.Key_Escape)
    app.processEvents()
    par.set_page_angle(0.0)
    par.set_page_origin(_pc[0], _pc[1])
    app.processEvents()
    view.snap.enabled = prev_snap2

    print("\n=== 8.13 O + 右键指定旋转中心 ===")
    scene.clearSelection()
    rot2 = scene.create_item("rect", center=(800.0, 800.0))
    rot2.set_page_size(300.0, 200.0)
    rot2.setSelected(True)
    window.view.resetTransform()      # 1:1 缩放，右键像素误差 ≈ kx 个场景单位
    window.view.centerOn(rot2.center_scene_point())
    app.processEvents()
    hinge = QPointF(900.0, 800.0)
    vp_hinge = window.view.mapFromScene(
        scene.projection.point(hinge.x(), hinge.y()))
    hp = QPoint(int(vp_hinge.x()), int(vp_hinge.y()))
    # 新交互：按住 O + 右键把选中图元旋转中心设到点击处（不再走右键菜单）
    QTest.keyPress(view, Qt.Key_O)
    app.processEvents()
    QTest.mousePress(view.viewport(), Qt.RightButton, Qt.NoModifier, hp)
    QTest.mouseRelease(view.viewport(), Qt.RightButton, Qt.NoModifier, hp)
    QTest.keyRelease(view, Qt.Key_O)
    app.processEvents()
    ctx = window.view.context_page_point()
    px_tol = 4.0 / max(scene.projection.kx, 1e-9)
    check("O + 右键位置已换算成 page 坐标",
          ctx is not None and abs(ctx.x() - 900.0) < px_tol
          and abs(ctx.y() - 800.0) < px_tol, str(ctx))
    menu_labels = [a.text() for a in window.view.build_context_menu().actions() if a.text()]
    check("右键菜单已移除「旋转中心设到此处」",
          "旋转中心设到此处" not in menu_labels, str(menu_labels[:4]))
    check("右键菜单已移除「旋转中心复位到图元中心」",
          "旋转中心复位到图元中心" not in menu_labels, str(menu_labels[:4]))
    check("O + 右键把旋转中心落到点击处",
          abs(rot2.page_origin()[0] - ctx.x()) < 1.0
          and abs(rot2.page_origin()[1] - ctx.y()) < 1.0,
          f"{rot2.page_origin()} vs {ctx}")
    check("设支点不移动可视中心",
          _close_pt(rot2.page_center(), (800.0, 800.0), 1e-3),
          str(rot2.page_center()))

    def _is_blue(c) -> bool:
        return c.blue() > 170 and c.red() < 110 and c.green() < 160

    blue_vp = window.view.mapFromScene(
        scene.projection.point(*rot2.page_origin()))
    check("画布上画出蓝色支点标记",
          _scan(_shot(), blue_vp.x(), blue_vp.y(), 8, _is_blue),
          f"vp=({blue_vp.x():.0f},{blue_vp.y():.0f})")

    # 旋转中心红点必须跟着支点走，不再钉在几何中心
    dot_vp = window.view.mapFromScene(rot2.pivot_scene_point())
    center_vp = window.view.mapFromScene(rot2.center_scene_point())
    check("中心点标识画在旋转中心处",
          _scan(_shot(), dot_vp.x(), dot_vp.y(), 5, _is_dot),
          f"pivot_vp=({dot_vp.x():.0f},{dot_vp.y():.0f})")
    check("中心点标识不再画在几何中心",
          not _scan(_shot(), center_vp.x(), center_vp.y(), 3, _is_dot),
          f"center_vp=({center_vp.x():.0f},{center_vp.y():.0f})")

    c0, o0 = rot2.page_center(), rot2.page_origin()
    r0 = math.hypot(c0[0] - o0[0], c0[1] - o0[1])
    rot2.set_page_angle(90.0)
    app.processEvents()
    c1 = rot2.page_center()
    check("绕右键指定的支点旋转（中心到支点距离不变）",
          abs(math.hypot(c1[0] - o0[0], c1[1] - o0[1]) - r0) < 0.5 and r0 > 50.0,
          f"r0={r0:.2f} c1={c1}")
    check("旋转后支点不动",
          _close_pt(rot2.page_origin(), o0, 1e-6), str(rot2.page_origin()))
    window._do("origin_center")
    app.processEvents()
    check("旋转中心复位到图元中心",
          _close_pt(rot2.page_origin(), rot2.page_center(), 1e-6),
          f"{rot2.page_origin()} vs {rot2.page_center()}")
    scene.delete_items([par, kid, grand, poly_kid, rot2])
    scene.clearSelection()
    app.processEvents()

    print("\n=== 8.14 有父对象的图元坐标表达在父坐标系 ===")
    fp = scene.create_item("rect", center=(500.0, 500.0))
    fp.set_page_size(400.0, 400.0)
    fk = scene.create_item("rect", center=(700.0, 500.0))
    fk.set_page_size(100.0, 100.0)
    fk.set_page_parent(fp.item_id)
    app.processEvents()
    check("子图元局部中心 = 相对父图元中心 (200, 0)",
          _close_pt(fk.page_local_center(), (200.0, 0.0)),
          str(fk.page_local_center()))
    check("子图元局部角度相对父对象",
          abs(fk.page_local_angle()) < 1e-6, f"{fk.page_local_angle():.3f}")

    fk.set_page_origin(750.0, 500.0)          # 支点放到中心右侧 50
    app.processEvents()
    check("子图元局部支点 = 相对父中心的支点 (250, 0)",
          _close_pt(fk.page_local_origin(), (250.0, 0.0)),
          str(fk.page_local_origin()))

    world0 = fk.page_center()
    fp.set_page_angle(90.0)
    app.processEvents()
    check("父对象旋转 90°，子图元世界坐标确实变了",
          not _close_pt(fk.page_center(), world0, 1.0),
          f"{world0} -> {fk.page_center()}")
    check("父对象旋转后子图元局部坐标不变",
          _close_pt(fk.page_local_center(), (200.0, 0.0)),
          str(fk.page_local_center()))
    check("父对象旋转后子图元局部角度不变",
          abs(fk.page_local_angle()) < 1e-6, f"{fk.page_local_angle():.3f}")

    fp.set_page_center(600.0, 600.0)
    app.processEvents()
    check("父对象平移后子图元局部坐标仍不变",
          _close_pt(fk.page_local_center(), (200.0, 0.0)),
          str(fk.page_local_center()))

    fk.set_page_local_angle(45.0)             # 按父坐标系写角度
    app.processEvents()
    check("按父坐标系写入角度（父 90° + 自身 45°）",
          abs(fk.page_local_angle() - 45.0) < 1e-6
          and abs(fp.page_angle() - 90.0) < 1e-6,
          f"local={fk.page_local_angle():.3f} abs={fk.page_angle():.3f}")
    fk.set_page_local_origin(300.0, 0.0)      # 按父坐标系写支点
    app.processEvents()
    check("按父坐标系写入支点",
          _close_pt(fk.page_local_origin(), (300.0, 0.0)),
          str(fk.page_local_origin()))

    window.property_panel.update_for_selected(fk)
    app.processEvents()
    layout_page = next((window.property_panel.stack.widget(i)
                        for i in range(window.property_panel.stack.count())
                        if window.property_panel.stack.widget(i).objectName() == "layout"),
                       None)
    boxes = layout_page.findChildren(QDoubleSpinBox) if layout_page is not None else []
    check("面板 X 显示的是父坐标系坐标", len(boxes) >= 2
          and abs(boxes[0].value() - fk.page_local_center()[0]) < 1e-3
          and abs(boxes[1].value() - fk.page_local_center()[1]) < 1e-3,
          f"boxes={[round(b.value(), 3) for b in boxes[:2]]} "
          f"local={fk.page_local_center()}")

    scene.delete_items([fp, fk])
    scene.clearSelection()
    app.processEvents()

    print("\n=== 8.15 背景网格 + 网格交汇点吸附（鼠标偏移即图元位移） ===")

    def _is_red_cross(c) -> bool:
        """光标旁的捕捉标记是红色十字（旧 Core 同款纯红，抗锯齿后略有混色）。"""
        return c.red() >= 195 and c.green() <= 110 and c.blue() <= 110

    scene.clearSelection()
    view.snap.enabled = False
    view._snap_offset = QPointF(0.0, 0.0)
    check("默认显示背景网格", view.show_grid and view.snap.grid_enabled)

    ox, oy = view.snap.grid_origin
    step = view.snap.grid_step
    scale = view._view_scale()
    check("网格步长按屏幕像素自适应",
          step > 0 and 6.0 <= step * scale <= 100.0,
          f"step={step} px={step * scale:.1f}")

    # 视口中心对应的网格点：一定可见，供像素与吸附断言共用
    mid_scene = view.mapToScene(view.viewport().rect().center())
    gx = ox + round((mid_scene.x() - ox) / step) * step
    gy = oy + round((mid_scene.y() - oy) / step) * step
    nx, ny = view.snap.nearest_grid(QPointF(gx + step * 0.3, gy - step * 0.2))
    check("最近网格点严格落在格点上",
          abs((nx - ox) / step - round((nx - ox) / step)) < 1e-9
          and abs((ny - oy) / step - round((ny - oy) / step)) < 1e-9,
          f"({nx:.2f},{ny:.2f}) origin=({ox:.1f},{oy:.1f}) step={step}")
    check("网格点不做预先枚举（解析计算）",
          (nx, ny) not in view.snap.all_points(),
          f"端点+中点={sum(len(s) for s in view.snap.points.values())}")

    view.snap.enabled = True
    eps = min(1.0, view.snap.threshold * 0.3)
    hit, kind = view.snap.aim(QPointF(nx + eps, ny + eps),
                              exclude=view._selection_own_points())
    check("网格交汇点可作捕捉点",
          hit is not None and kind == "grid"
          and _close_pt((hit.x(), hit.y()), (nx, ny), 1e-6),
          f"{kind} {hit}")

    cands = view.snap.candidates(QPointF(nx, ny), step * 0.6)
    total_pts = sum(len(s) for s in view.snap.points.values())
    near_ok = all(math.hypot(p.x() - nx, p.y() - ny) <= step * 0.6 + 1e-6
                  for _k, p in cands)
    check("只取光标附近的候选点", 0 < len(cands) <= 40
          and near_ok and len(cands) * 4 < max(total_pts, 1),
          f"n={len(cands)} total={total_pts}")

    view._set_hover(QPointF(nx, ny))
    app.processEvents()
    vp_grid = view.mapFromScene(QPointF(nx, ny))
    check("画布上画出鼠标附近的捕捉标记",
          _scan(_shot(), vp_grid.x(), vp_grid.y(), 10, _is_red_cross),
          f"vp=({vp_grid.x()},{vp_grid.y()})")

    # 端点优先于网格：同距离时网格不得吃掉图元点
    view.snap.update_points([QPointF(nx + eps, ny + eps)], [])
    peek, peek_kind = view.snap.aim(QPointF(nx + eps, ny + eps))
    check("图元捕捉点优先于网格点",
          peek_kind == "element" and _close_pt((peek.x(), peek.y()),
                                               (nx + eps, ny + eps), 1e-6),
          f"{peek_kind} {peek}")
    view.refresh_snap_points()

    # ---- T 键：鼠标吸了多少偏移，选中图元就移动多少 ----
    far = scene.create_item("rect", center=(6000.0, 6000.0))
    far.set_page_size(120.0, 80.0)
    scene.clearSelection()
    far.setSelected(True)
    view.snap.enabled = False          # 先关，按 T 才是「打开并吸附」
    view._snap_offset = QPointF(0.0, 0.0)
    app.processEvents()

    c_scene = far.sceneBoundingRect().center()
    tgx = ox + round((c_scene.x() - ox) / step) * step
    tgy = oy + round((c_scene.y() - oy) / step) * step
    d = view.snap.threshold * 0.5
    hover = QPointF(tgx + d * 0.6, tgy + d * 0.8)
    view._set_hover(hover)
    before = QPointF(far.scenePos())
    QTest.keyClick(view, Qt.Key_T)
    app.processEvents()
    mv = far.scenePos() - before
    check("按下 T 光标吸附到最近捕捉点（仅选中时图元不动）",
          view.snap.enabled
          and abs(mv.x()) < 1e-6 and abs(mv.y()) < 1e-6
          and view._last_hover is not None
          and abs(view._last_hover.x() - tgx) < 1e-6
          and abs(view._last_hover.y() - tgy) < 1e-6,
          f"moved=({mv.x():.3f},{mv.y():.3f}) hover={view._last_hover} "
          f"target=({tgx:.3f},{tgy:.3f})")

    before2 = QPointF(far.scenePos())
    QTest.keyClick(view, Qt.Key_T)     # 一次性动作键，连续按两次
    QTest.keyClick(view, Qt.Key_T)
    app.processEvents()
    mv2 = far.scenePos() - before2
    check("连续按 T 不会移动图元（T 已不是开关门控）",
          abs(mv2.x()) < 1e-6 and abs(mv2.y()) < 1e-6,
          f"moved=({mv2.x():.3f},{mv2.y():.3f})")
    view.snap.enabled = False

    # ---- 多选按 T（未抓手）：只吸光标，任何图元都不动 ----
    buddy = scene.create_item("rect", center=(6000.0, 6120.0))
    buddy.set_page_size(80.0, 60.0)
    scene.clearSelection()
    far.setSelected(True)
    buddy.setSelected(True)
    view.snap.enabled = False
    view._snap_offset = QPointF(0.0, 0.0)
    view.centerOn(far)                  # 挪到视口中央，方便发送鼠标事件
    app.processEvents()

    start = {it.item_id: QPointF(it.scenePos()) for it in (far, buddy)}
    hover2 = QPointF(tgx + d * 0.7, tgy + d * 0.4)
    view._set_hover(hover2)
    marker2, _kind2 = view.snap.aim(hover2,
                                    exclude=view._selection_own_points(),
                                    always=True)
    check("多选时的吸附目标仍是最近捕捉点", marker2 is not None, f"marker={marker2}")
    QTest.keyClick(view, Qt.Key_T)
    app.processEvents()

    offsets = {it.item_id: QPointF(it.scenePos()) - start[it.item_id]
               for it in (far, buddy)}
    same = _close_pt((offsets[far.item_id].x(), offsets[far.item_id].y()),
                     (offsets[buddy.item_id].x(), offsets[buddy.item_id].y()), 1e-6)
    check("多选（未抓手）按 T：图元不动，光标吸到最近捕捉点",
          marker2 is not None
          and abs(offsets[far.item_id].x()) < 1e-6
          and abs(offsets[far.item_id].y()) < 1e-6
          and view._last_hover is not None
          and abs(view._last_hover.x() - marker2.x()) < 1e-6
          and abs(view._last_hover.y() - marker2.y()) < 1e-6,
          f"offset=({offsets[far.item_id].x():.3f},{offsets[far.item_id].y():.3f}) "
          f"hover={view._last_hover} marker={marker2}")
    check("多选图元保持相对位置（都不移动）", same,
          f"{offsets[far.item_id]} vs {offsets[buddy.item_id]}")
    view.snap.enabled = False

    scene.delete_items([far, buddy])
    scene.clearSelection()
    app.processEvents()

    print("\n=== 8.16 各类型布局页对齐矩形 + 光标处只留一个捕捉点 ===")
    kind_pts = {
        "rect": [(7600.0, 7600.0), (7800.0, 7750.0)],
        "line": [(7600.0, 7600.0), (7800.0, 7750.0)],
        "triangle": [(7600.0, 7600.0), (7800.0, 7600.0), (7700.0, 7750.0)],
        "polygon": [(7600.0, 7600.0), (7800.0, 7600.0), (7800.0, 7750.0),
                    (7600.0, 7750.0)],
        "path": [(7600.0, 7600.0), (7800.0, 7600.0), (7800.0, 7750.0)],
        "text": [(7600.0, 7600.0)],
        "group": [(7600.0, 7600.0)],
    }

    def _layout_boxes(item):
        window.property_panel.update_for_selected(item)
        app.processEvents()
        page = next((window.property_panel.stack.widget(i)
                     for i in range(window.property_panel.stack.count())
                     if window.property_panel.stack.widget(i).objectName() == "layout"),
                    None)
        return list(page.findChildren(QDoubleSpinBox)) if page is not None else []

    for kind, pts in kind_pts.items():
        scene.begin_draw_tool(kind)
        for x, y in pts:
            scene.draw_add_point(QPointF(x, y))
        if kind in ("polygon", "path"):
            scene.finish_polygon()
        drawn = scene.selected_items()
        if not drawn:
            check(f"{kind} 绘制后可选中", False)
            continue
        item = drawn[0]
        app.processEvents()
        boxes = _layout_boxes(item)
        check(f"{kind} 布局页字段与矩形同构（7 个输入框且全可编辑）",
              len(boxes) == 7 and all(b.isEnabled() for b in boxes),
              f"n={len(boxes)} enabled={[b.isEnabled() for b in boxes]}")
        ok_pivot = (len(boxes) == 7
                    and abs(boxes[5].value() - boxes[0].value()) < 1e-3
                    and abs(boxes[6].value() - boxes[1].value()) < 1e-3)
        check(f"{kind} 旋转中心默认落在几何中心",
              ok_pivot and _close_pt(item.page_origin(), item.page_center()),
              f"pivot={item.page_origin()} center={item.page_center()}")

        keep = QPointF(*item.page_center())
        item.set_page_angle(30.0)
        app.processEvents()
        now = QPointF(*item.page_center())
        check(f"{kind} 默认支点旋转不挪中心",
              math.hypot(now.x() - keep.x(), now.y() - keep.y()) < 1e-6,
              f"d=({now.x()-keep.x():.4f},{now.y()-keep.y():.4f})")
        item.set_page_angle(0.0)
        app.processEvents()
        scene.delete_items([item.item_id])
        app.processEvents()

    # ---- 光标离所有端点 / 中点都超出阈值时，仍然只有一个格子捕捉点，T 能吸过去 ----
    probe = scene.create_item("polygon", center=(8600.0, 7600.0))
    probe.set_page_vertices([QPointF(8500.0, 7500.0), QPointF(8700.0, 7500.0),
                             QPointF(8700.0, 7700.0), QPointF(8500.0, 7700.0)])
    scene.clearSelection()
    probe.setSelected(True)
    view.snap.enabled = False
    view._snap_offset = QPointF(0.0, 0.0)
    app.processEvents()

    gx0, gy0 = view.snap.grid_origin
    step = view.snap.grid_step
    cx0, cy0 = probe.page_center()
    cell_x = gx0 + (math.floor((cx0 - gx0) / step) + 0.5) * step
    cell_y = gy0 + (math.floor((cy0 - gy0) / step) + 0.5) * step
    view._set_hover(QPointF(cell_x, cell_y))
    strict, _k = view.snap.aim(view.snap.hover,
                               exclude=view._selection_own_points())
    check("远离捕捉点时阈值内确实没有目标", strict is None, f"strict={strict}")
    marker, _active = view._hover_marker()
    check("光标处仍给出唯一一个捕捉点（最近格点）",
          marker is not None
          and math.hypot(marker.x() - cell_x, marker.y() - cell_y) <= step * 0.75,
          f"marker={marker}")
    hover_pt = QPointF(view.snap.hover)
    before = QPointF(probe.scenePos())
    QTest.keyClick(view, Qt.Key_T)
    app.processEvents()
    moved = QPointF(probe.scenePos()) - before
    want = (QPointF(0.0, 0.0) if marker is None else marker - hover_pt)
    check("仅选中按 T 只吸光标、图元不动（旧兜底已移除）",
          abs(moved.x()) < 1e-6 and abs(moved.y()) < 1e-6
          and marker is not None and view._last_hover is not None
          and abs(view._last_hover.x() - marker.x()) < 1e-6
          and abs(view._last_hover.y() - marker.y()) < 1e-6,
          f"moved=({moved.x():.3f},{moved.y():.3f}) "
          f"hover={view._last_hover} marker={marker}")
    view.snap.enabled = False
    scene.delete_items([probe.item_id])
    scene.clearSelection()
    app.processEvents()

    print("\n=== 8.17 顶点类旋转：支点不漂移、绝对角度可反复设 ===")
    # 三角形不是中心对称图形：绕中心转一次，旋转后的包围盒中心必然换了个点。
    # 若烘焙时按「新包围盒中心」重新定位，旋一次支点就跳一大截（用户的报障）。
    # 这里逐类型验证：中心 / 支点 / 宽高全都不动，且「旋转」框读回的是设定值
    # （不是烘焙后归零），因此连续设绝对值不会越转越多。
    rot_cases = (
        ("triangle", [(1000.0, 1000.0), (1200.0, 1000.0), (1000.0, 1160.0)]),
        ("polygon", [(1000.0, 1000.0), (1200.0, 1000.0),
                     (1200.0, 1120.0), (1000.0, 1120.0), (1060.0, 1060.0)]),
        ("line", [(1000.0, 1000.0), (1200.0, 1140.0)]),
        ("path", [(1000.0, 1000.0), (1200.0, 1000.0),
                  (1200.0, 1160.0), (1080.0, 1100.0)]),
    )
    for kind, pts in rot_cases:
        scene.begin_draw_tool(kind)
        for x, y in pts:
            scene.draw_add_point(QPointF(x, y))
        if kind in ("polygon", "path"):
            scene.finish_polygon()
        item = max(scene.all_items(), key=lambda it: it.item_id)
        item.setSelected(True)
        app.processEvents()
        c0, o0 = item.page_center(), item.page_origin()
        w0, h0 = item.page_size()
        worst_c = worst_o = worst_ang = 0.0
        for ang in (30.0, 60.0, 90.0, 30.0, 0.0):
            item.set_page_angle(ang)
            app.processEvents()
            item.to_page_record()                  # 触发烘焙（真正的存盘路径）
            c, o = item.page_center(), item.page_origin()
            worst_c = max(worst_c, math.hypot(c[0] - c0[0], c[1] - c0[1]))
            worst_o = max(worst_o, math.hypot(o[0] - o0[0], o[1] - o0[1]))
            worst_ang = max(worst_ang, abs(item.page_angle() - ang))
        check(f"{kind} 反复转角度后中心不漂移", worst_c < 1e-6, f"max={worst_c:.6f}")
        check(f"{kind} 反复转角度后旋转中心（支点）不漂移",
              worst_o < 1e-6, f"max={worst_o:.6f}")
        check(f"{kind} 「旋转」读回设定的绝对角度", worst_ang < 1e-6,
              f"max={worst_ang:.6f}")
        w1, h1 = item.page_size()
        # 顶点记录只保留 3 位小数，反复烘焙会有丝级累积（5 次 <0.01 场景单位）
        check(f"{kind} 宽高按自身尺寸读（不随旋转变胖）",
              abs(w1 - w0) < 0.01 and abs(h1 - h0) < 0.01,
              f"{(w0, h0)} -> {(w1, h1)}")

        # 绕自定义支点：支点必须钉死在原地，中心按刚体绕它走
        item.set_page_angle(0.0)
        app.processEvents()
        item.to_page_record()
        pivot = (c0[0] + 70.0, c0[1] + 50.0)
        item.set_page_origin(*pivot)
        app.processEvents()
        ok_pin = True
        for ang in (25.0, 70.0):
            item.set_page_angle(ang)
            app.processEvents()
            item.to_page_record()
            o = item.page_origin()
            ok_pin = ok_pin and math.hypot(o[0] - pivot[0], o[1] - pivot[1]) < 1e-3
        check(f"{kind} 自定义支点反复转仍钉在原处", ok_pin, f"pivot={item.page_origin()}")
        scene.delete_items([item.item_id])
        app.processEvents()

    # 面板链路：连续两次在「旋转」框里设绝对值，必须是绝对值语义（不是叠加），
    # 且转完旋转中心不动——这就是用户看到的「转一次中心就偏移 / 角度框归零」。
    scene.begin_draw_tool("triangle")
    for x, y in ((1000.0, 2000.0), (1200.0, 2000.0), (1000.0, 2160.0)):
        scene.draw_add_point(QPointF(x, y))
    tri = max(scene.all_items(), key=lambda it: it.item_id)
    tri.setSelected(True)
    app.processEvents()
    tri_c, tri_o = tri.page_center(), tri.page_origin()
    for ang in (30.0, 60.0):
        boxes = _layout_boxes(tri)
        if len(boxes) != 7:
            break
        boxes[4].setValue(ang)          # 「旋转」是布局页第 5 个框
        app.processEvents()
    boxes = _layout_boxes(tri)
    check("面板连续设绝对角度：图元角度 = 60（不是叠加成 90）",
          abs(tri.page_angle() - 60.0) < 1e-6, f"angle={tri.page_angle()}")
    check("面板「旋转」框读回的是真实朝向（不再烘焙后归零）",
          len(boxes) == 7 and abs(boxes[4].value() - 60.0) < 1e-6,
          f"box={boxes[4].value() if len(boxes) == 7 else 'n/a'}")
    check("面板转角度后旋转中心不动",
          abs(tri.page_origin()[0] - tri_o[0]) < 1e-6
          and abs(tri.page_origin()[1] - tri_o[1]) < 1e-6,
          f"{tri_o} -> {tri.page_origin()}")
    check("面板转角度后中心不动",
          abs(tri.page_center()[0] - tri_c[0]) < 1e-6
          and abs(tri.page_center()[1] - tri_c[1]) < 1e-6,
          f"{tri_c} -> {tri.page_center()}")
    scene.delete_items([tri.item_id])
    scene.clearSelection()
    app.processEvents()

    print("\n=== 8.18 组尺寸属性入口 + 剪贴板动作 ===")
    from PySide6.QtGui import QKeyEvent

    grp = scene.create_item("group", center=(9200.0, 7600.0))
    rect = scene.create_item("rect", center=(9150.0, 7550.0),
                             size=(100.0, 60.0))
    tri2 = scene.create_item("triangle", center=(9300.0, 7700.0))
    rect.set_page_parent(grp.item_id)
    tri2.set_page_parent(grp.item_id)
    grp.set_page_field("children_ids", [rect.item_id, tri2.item_id])
    scene.index.rebuild_links()
    scene.clearSelection()
    grp.setSelected(True)
    app.processEvents()
    gw0, _gh0 = grp.page_size()
    w_rect0 = rect.page_size()[0]
    c_rect0 = rect.page_center()
    anchor = grp.page_origin()
    gboxes = _layout_boxes(grp)
    check("组布局页与矩形同构（7 个输入框）", len(gboxes) == 7,
          f"n={len(gboxes)}")
    if len(gboxes) == 7:
        gboxes[2].setValue(gw0 * 2.0)      # 「宽 W」是第 3 个框
    app.processEvents()
    check("属性面板改组宽递归放大成员宽",
          abs(rect.page_size()[0] - w_rect0 * 2.0) < 1e-3,
          f"{w_rect0} -> {rect.page_size()[0]}")
    check("属性面板改组宽后成员中心按锚点搬走",
          abs(rect.page_center()[0]
              - (anchor[0] + (c_rect0[0] - anchor[0]) * 2.0)) < 1e-3,
          f"{c_rect0} -> {rect.page_center()}")

    n_before = len(scene.all_items())
    scene.clearSelection()
    grp.setSelected(True)
    window._do("copy")
    window._do("paste")
    app.processEvents()
    check("菜单复制 / 粘贴递归带上组成员",
          len(scene.all_items()) == n_before + 3,
          f"{n_before} -> {len(scene.all_items())}")

    n_before2 = len(scene.all_items())
    window.view.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key_C, Qt.ControlModifier))
    window.view.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key_V, Qt.ControlModifier))
    app.processEvents()
    check("画布 Ctrl+C / Ctrl+V 走场景剪贴板",
          len(scene.all_items()) == n_before2 + 3,
          f"{n_before2} -> {len(scene.all_items())}")

    for it in list(scene.all_items()):
        if it.item_id >= grp.item_id:
            scene.delete_items([it.item_id])
    scene.clearSelection()
    app.processEvents()

    print("\n=== 8.19 拖角改尺寸手柄（真实鼠标交互） ===")
    window.view.resetTransform()          # 1:1，保证四角屏幕跨度足够
    h_item = scene.create_item("rect", center=(9600.0, 8200.0),
                               size=(600.0, 400.0))
    window.view.centerOn(h_item.center_scene_point())
    scene.clearSelection()
    h_item.setSelected(True)
    app.processEvents()
    hpts = window.view._handle_points(h_item)
    check("单选图元显示 4 个角手柄", len(hpts) == 4, str(sorted(hpts)))

    def _is_blue(c) -> bool:
        return c.blue() > 150 and c.red() < 110 and c.green() < 170

    hp = hpts.get("se")
    img_h = window.view.viewport().grab().toImage()
    check("角上画出蓝色手柄方块",
          hp is not None and _scan(img_h, hp.x(), hp.y(), 5, _is_blue),
          f"hp={hp}")
    check("角手柄命中测试有效",
          hp is not None
          and window.view._handle_at(QPoint(int(hp.x()), int(hp.y()))) == "se")

    w0, h0 = h_item.page_size()
    ends0, _ = h_item.snap_points()
    ax0, ay0 = scene.projection.inverse_point(ends0[0].x(), ends0[0].y())
    p0 = QPoint(int(hp.x()), int(hp.y()))
    p1 = QPoint(p0.x() + 60, p0.y() + 40)
    QTest.mousePress(window.view.viewport(), Qt.LeftButton, pos=p0)
    check("按下手柄进入缩放状态（不转成拖动图元）",
          window.view._resize_state is not None)
    QApplication.sendEvent(window.view.viewport(), QMouseEvent(
        QEvent.MouseMove, QPointF(p1),
        QPointF(window.view.viewport().mapToGlobal(p1)),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    app.processEvents()
    QTest.mouseRelease(window.view.viewport(), Qt.LeftButton, pos=p1)
    app.processEvents()
    check("松手后退出缩放状态", window.view._resize_state is None)
    check("拖角后宽 / 高都变大",
          h_item.page_size()[0] > w0 * 1.02
          and h_item.page_size()[1] > h0 * 1.02,
          f"{w0}x{h0} -> {h_item.page_size()}")
    ends1, _ = h_item.snap_points()
    ax1, ay1 = scene.projection.inverse_point(ends1[0].x(), ends1[0].y())
    check("拖角时对面的角保持不动",
          abs(ax1 - ax0) < 1e-2 and abs(ay1 - ay0) < 1e-2,
          f"({ax0},{ay0}) -> ({ax1},{ay1})")

    scene.set_scene_mode(True)
    app.processEvents()
    check("运行模式不显示 / 不命中拖角手柄",
          window.view._resize_item() is None
          and window.view._handle_at(p0) is None)
    scene.set_scene_mode(False)
    scene.clearSelection()
    scene.delete_items([h_item])
    app.processEvents()

    print("\n=== 8.20 文本图元：属性面板字体大小 + 边框自适应 ===")
    tx = scene.create_item("text", center=(10400.0, 8600.0), context="测试文本")
    scene.clearSelection()
    tx.setSelected(True)
    app.processEvents()
    panel = window.property_panel

    def _page_by_key(key):
        for i in range(panel.stack.count()):
            wdg = panel.stack.widget(i)
            if wdg.objectName() == key:
                return wdg
        return None

    def _font_box(page):
        if page is None:
            return []
        return [b for b in page.findChildren(QSpinBox)
                if b.minimum() == 4 and b.maximum() == 200]

    ctx_page = _page_by_key("context")
    app_page = _page_by_key("appearance")
    lay_page = _page_by_key("layout")
    check("文本内容页提供字体大小输入", len(_font_box(ctx_page)) == 1,
          str(len(_font_box(ctx_page))))
    check("外观页字号输入仍在", len(_font_box(app_page)) == 1,
          str(len(_font_box(app_page))))

    fs_boxes = _font_box(ctx_page) + _font_box(app_page)
    c0 = tx.page_center()
    size0 = tx.page_size()
    fs_boxes[0].setValue(48)
    app.processEvents()
    check("面板改字体大小写回 style.font_size",
          int(float(tx.style_value("font_size", 10))) == 48,
          str(tx.style_value("font_size")))
    check("改字号后边框背景随之重算", tx.page_size() != size0,
          f"{size0} -> {tx.page_size()}")
    check("两处字号输入跨页同步",
          all(b.value() == 48 for b in fs_boxes),
          str([b.value() for b in fs_boxes]))
    check("改字号后中心不动", tx.page_center() == c0, str(tx.page_center()))
    check("布局页宽高显示随边框刷新",
          lay_page is not None
          and any(abs(b.value() - tx.page_size()[0]) < 1e-3
                  for b in lay_page.findChildren(QDoubleSpinBox)),
          str(tx.page_size()))

    size1 = tx.page_size()
    text_edit = ctx_page.findChild(QPlainTextEdit) if ctx_page else None
    check("文本内容页有文本编辑框", text_edit is not None)
    if text_edit is not None:
        text_edit.setPlainText("更长的一串文字ABCDEFG")
        app.processEvents()
        check("改文本后边框长度方向随文字变化",
              tx.page_size()[1] > size1[1] * 1.05,
              f"{size1} -> {tx.page_size()}")

    size2 = tx.page_size()
    line_boxes = [b for b in app_page.findChildren(QSpinBox)
                  if b.minimum() == 0 and b.maximum() == 64] if app_page else []
    check("外观页线宽输入存在", len(line_boxes) == 1, str(len(line_boxes)))
    if line_boxes:
        line_boxes[0].setValue(5)
        app.processEvents()
        check("改线宽不误触发边框重算", tx.page_size() == size2,
              f"{size2} -> {tx.page_size()}")

    scene.clearSelection()
    scene.delete_items([tx])
    app.processEvents()

    print("\n=== 8.21 文本图元：改 W/H 与拖角反算字号 + 面板回显 ===")
    window.view.resetTransform()
    tb = scene.create_item("text", center=(10800.0, 8600.0), context="联动测试")
    tb.set_style_value("font_size", 30)
    scene.clearSelection()
    tb.setSelected(True)
    app.processEvents()
    panel = window.property_panel
    lay2 = _page_by_key("layout")
    fb2 = (_font_box(_page_by_key("context"))
           + _font_box(_page_by_key("appearance")))
    boxes2 = lay2.findChildren(QDoubleSpinBox) if lay2 else []
    size0 = tb.page_size()
    fs0 = int(float(tb.style_value("font_size", 10)))
    check("初始字号 30 且两处输入同步", fs0 == 30
          and all(b.value() == 30 for b in fb2),
          f"fs={fs0} boxes={[b.value() for b in fb2]}")

    # AGV 轴交换：page W 决定 view 高（行高方向）、page H 决定 view 宽（文字
    # 长度方向）。反算取「两轴都装得下」的最大字号，所以单独缩小任一轴都会
    # 收紧约束让字号变小（正是防裁字），单独放大一个轴则受另一轴限制不变。
    h_box2 = next((b for b in boxes2
                   if abs(b.value() - size0[1]) < 1e-3), None)
    w_box2 = next((b for b in boxes2
                   if abs(b.value() - size0[0]) < 1e-3), None)
    check("布局页找到宽 W / 高 H 输入",
          h_box2 is not None and w_box2 is not None,
          str([b.value() for b in boxes2]))
    if h_box2 is not None:
        h_box2.setValue(size0[1] * 0.5)
        app.processEvents()
        fs1 = int(float(tb.style_value("font_size", 10)))
        check("布局页缩小 H 反算减小字号（防裁字）", fs1 < fs0,
              f"{fs0} -> {fs1}")
        check("缩小 H 后边框保留用户输入值",
              abs(tb.page_size()[1] - size0[1] * 0.5) < 1e-3,
              str(tb.page_size()))
        check("两处字号输入回显反算结果",
              all(b.value() == fs1 for b in fb2),
              str([b.value() for b in fb2]))

        size1 = tb.page_size()
        if w_box2 is not None:
            w_box2.setValue(size1[0] * 2.0)
            h_box2.setValue(size1[1] * 2.0)
            app.processEvents()
            fs2 = int(float(tb.style_value("font_size", 10)))
            check("W/H 同时放大反算放大字号", fs2 > fs1 * 1.7,
                  f"{fs1} -> {fs2}")
            check("两处字号输入回显放大结果",
                  all(b.value() == fs2 for b in fb2),
                  str([b.value() for b in fb2]))

    # 真实拖角：按下手柄 -> 拖动 -> 松手，字号与面板都要跟着变。
    # 这里不要再 clearSelection + setSelected：那会重建属性面板，让上面取到的
    # 控件引用失效。
    window.view.centerOn(tb.center_scene_point())
    app.processEvents()
    hp2 = window.view._handle_points(tb).get("se")
    check("文本图元显示拖角手柄", hp2 is not None, str(hp2))
    if hp2 is not None:
        fs_pre = int(float(tb.style_value("font_size", 10)))
        q0 = QPoint(int(hp2.x()), int(hp2.y()))
        q1 = QPoint(q0.x() + 60, q0.y() + 40)
        QTest.mousePress(window.view.viewport(), Qt.LeftButton, pos=q0)
        QApplication.sendEvent(window.view.viewport(), QMouseEvent(
            QEvent.MouseMove, QPointF(q1),
            QPointF(window.view.viewport().mapToGlobal(q1)),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        app.processEvents()
        QTest.mouseRelease(window.view.viewport(), Qt.LeftButton, pos=q1)
        app.processEvents()
        fs_post = int(float(tb.style_value("font_size", 10)))
        check("拖角放大后字号同步变大", fs_post > fs_pre,
              f"{fs_pre} -> {fs_post}")
        check("拖角后两处字号输入回显",
              all(b.value() == fs_post for b in
                  (_font_box(_page_by_key("context"))
                   + _font_box(_page_by_key("appearance")))),
              str([b.value() for b in fb2]))
        check("拖角后文字仍装得进边框",
              tb._fit_font_size(*scene.projection.size(*tb.page_size())) == fs_post,
              f"fs={fs_post}")

    scene.clearSelection()
    scene.delete_items([tb])
    app.processEvents()

    print("\n=== 8.22 widget 控件变体：属性面板 / 工具箱 / 运行预览 ===")
    from PySide6.QtWidgets import (  # noqa: E402
        QLabel as _QLabel, QProgressBar as _QProgressBar,
        QSlider as _QSlider, QSpinBox as _QSpinBox,
    )

    wg = scene.create_item("widget:combobox", center=(11200.0, 8600.0))
    scene.clearSelection()
    wg.setSelected(True)
    app.processEvents()
    wpage = _page_by_key("widget")
    check("widget 图元有「控件」页", wpage is not None)
    variants = wpage.findChildren(QComboBox) if wpage else []
    check("控件页提供变体下拉", len(variants) == 1, str(len(variants)))
    if variants:
        check("变体下拉含 9 项且当前为 combobox",
              variants[0].count() == 9
              and str(variants[0].currentData()) == "combobox",
              f"n={variants[0].count()} cur={variants[0].currentData()}")
        variants[0].setCurrentIndex(variants[0].findData("spinbox"))
        app.processEvents()
        check("切换变体写回顶层 widgetType",
              wg.page_record()["widgetType"] == "spinbox",
              str(wg.page_record()["widgetType"]))

    wpage = _page_by_key("widget")
    areas = wpage.findChildren(QPlainTextEdit) if wpage else []
    spins = wpage.findChildren(QSpinBox) if wpage else []
    check("控件页提供文本编辑与字号输入",
          len(areas) == 1 and len(spins) == 1,
          f"areas={len(areas)} spins={len(spins)}")
    check("切变体后提示同步到 spinbox 语法",
          wpage is not None and any("min=" in lab.text()
                                    for lab in wpage.findChildren(_QLabel)),
          "hint")
    if areas:
        areas[0].setPlainText("min=2\nmax=8\nvalue=5")
        app.processEvents()
        check("文本编辑写回 widgetText",
              wg.page_record()["widgetText"] == "min=2\nmax=8\nvalue=5",
              repr(wg.page_record()["widgetText"]))
    if spins:
        style_fs_before = wg.style_value("font_size", None)
        spins[0].setValue(28)
        app.processEvents()
        check("字号输入写回 widgetFontSize（不动 style.font_size）",
              wg.page_record()["widgetFontSize"] == 28
              and wg.style_value("font_size", None) == style_fs_before,
              str(wg.page_record()["widgetFontSize"]))

    check("设计态不挂真实控件", len(scene.widget_proxies) == 0)
    scene.set_scene_mode(True)
    proxy = scene.widget_proxies.get(wg.item_id)
    check("运行预览挂载 QSpinBox 并灌入 min/max/value",
          isinstance(proxy.widget() if proxy else None, _QSpinBox)
          and (proxy.widget().minimum(), proxy.widget().maximum(),
               proxy.widget().value()) == (2, 8, 5),
          str(type(proxy.widget()).__name__ if proxy else None))
    scene.set_scene_mode(False)
    check("退出运行预览销毁 proxy", len(scene.widget_proxies) == 0)

    vbtn = next((b for b in window.toolbox.buttons
                 if b.key == "widget:lineedit"), None)
    check("工具箱有 lineedit 变体按钮", vbtn is not None)
    if vbtn is not None:
        vbtn.click()
        check("点击变体按钮进入绘制模式",
              window.view._draw_type == "widget:lineedit",
              str(window.view._draw_type))
        window.view.set_draw_tool(None)
    before = len(scene.all_items())
    window._spawn("widget:lineedit", (11400.0, 8600.0))
    dropped = scene.all_items()[-1]
    check("变体拖放落点创建 widget:lineedit",
          len(scene.all_items()) == before + 1
          and dropped.TYPE == "widget"
          and dropped.page_record()["widgetType"] == "lineedit",
          str(dropped.page_record().get("widgetType")))

    # 新增变体：工具箱按钮 → 点击绘制模式 → 拖放落点 → 属性提示 →
    # 真实 Qt 控件（含方向 / 数值范围）。只写现有 5 个顶层字段。
    extras = []
    widget_keys = {"widgetType", "widgetText", "widgetFontSize",
                   "widgetColor", "widgetBackground"}
    for idx, (key, cfg) in enumerate((
        ("progressbar", "min=0\nmax=200\nvalue=75"),
        ("slider", "min=-10\nmax=10\nvalue=3\norientation=vertical"),
    )):
        new_btn = next((b for b in window.toolbox.buttons
                        if b.key == f"widget:{key}"), None)
        check(f"工具箱有 {key} 变体按钮", new_btn is not None)
        if new_btn is not None:
            new_btn.click()
            check(f"点击 {key} 变体按钮进入绘制模式",
                  window.view._draw_type == f"widget:{key}",
                  str(window.view._draw_type))
            window.view.set_draw_tool(None)
        before = len(scene.all_items())
        window._spawn(f"widget:{key}", (11500.0 + idx * 260.0, 8600.0))
        spawned = scene.all_items()[-1]
        spawned.set_page_field("widgetText", cfg)
        extras.append(spawned)
        rec = spawned.page_record()
        check(f"拖放 {key} 只写 widgetType / widgetText 顶层字段",
              len(scene.all_items()) == before + 1
              and spawned.TYPE == "widget"
              and rec["widgetType"] == key
              and rec["widgetText"] == cfg
              and widget_keys <= set(rec),
              str(rec.get("widgetType")))

    scene.clearSelection()
    extras[0].setSelected(True)
    app.processEvents()
    new_page = _page_by_key("widget")
    check("进度条属性页提示 orientation= 配置",
          new_page is not None
          and any("orientation=" in lab.text()
                  for lab in new_page.findChildren(_QLabel)),
          "hint")

    scene.set_scene_mode(True)
    p_proxy = scene.widget_proxies.get(extras[0].item_id)
    s_proxy = scene.widget_proxies.get(extras[1].item_id)
    p_widget = p_proxy.widget() if p_proxy else None
    s_widget = s_proxy.widget() if s_proxy else None
    check("新变体运行预览挂 QProgressBar / QSlider 并灌入范围 / 方向",
          isinstance(p_widget, _QProgressBar)
          and isinstance(s_widget, _QSlider)
          and (p_widget.minimum(), p_widget.maximum(), p_widget.value(),
               p_widget.orientation()) == (0, 200, 75, Qt.Horizontal)
          and (s_widget.minimum(), s_widget.maximum(), s_widget.value(),
               s_widget.orientation()) == (-10, 10, 3, Qt.Vertical),
          f"{type(p_widget).__name__} / {type(s_widget).__name__}")
    scene.set_scene_mode(False)
    check("退出运行预览销毁新变体 proxy", len(scene.widget_proxies) == 0)

    scene.clearSelection()
    scene.delete_items([wg, dropped, *extras])
    app.processEvents()

    print("\n=== 8.23 运行预览真实控件与图元矩形逐点对齐 ===")

    def _corner_gap(it, proxy):
        """图元局部四角 vs 控件本地 (0,0,w,h) 四角的最大场景坐标差。"""
        w, h = it._w_view, it._h_view
        a = [it.mapToScene(QPointF(x, y)) for x, y in
             ((-w / 2, -h / 2), (w / 2, -h / 2),
              (w / 2, h / 2), (-w / 2, h / 2))]
        b = [proxy.mapToScene(QPointF(x, y)) for x, y in
             ((0, 0), (w, 0), (w, h), (0, h))]
        return max(max(abs(p.x() - q.x()), abs(p.y() - q.y()))
                   for p, q in zip(a, b))

    # 小尺寸 + 旋转 + 自定义支点 + AGV 轴交换，三个坑一次覆盖：
    # 旧写法 setGeometry(-w/2,...) 后 setPos(center) 会整体偏 +w/2,+h/2；
    # 旋转默认绕控件左上角；QComboBox 的 minimumSizeHint 会把 resize 撑大。
    pw = scene.create_item("widget:combobox", center=(11600.0, 8600.0),
                           size=(24.0, 12.0))
    pw.set_page_angle(32.0)
    pcx, pcy = pw.live_page_pose()[:2]
    pw.set_page_origin(pcx + 12.0, pcy + 8.0)
    scene.set_scene_mode(True)
    px = scene.widget_proxies.get(pw.item_id)
    check("小尺寸 combobox 不被 minimumSizeHint 撑大",
          px is not None
          and abs(px.geometry().width() - pw._w_view) < 1e-6
          and abs(px.geometry().height() - pw._h_view) < 1e-6,
          f"geometry={px.geometry() if px else None} "
          f"want={pw._w_view}×{pw._h_view}")
    gap = _corner_gap(pw, px) if px is not None else float("inf")
    check("运行预览控件四角与图元逐点重合（旋转+自定义支点+AGV）",
          gap < 1e-6, f"gap={gap:.6f}")
    pbr = px.sceneBoundingRect() if px is not None else None
    ibr = pw.sceneBoundingRect()
    check("proxy.sceneBoundingRect 与图元一致",
          pbr is not None and abs(pbr.x() - ibr.x()) < 1e-6
          and abs(pbr.y() - ibr.y()) < 1e-6
          and abs(pbr.width() - ibr.width()) < 1e-6
          and abs(pbr.height() - ibr.height()) < 1e-6,
          f"proxy={pbr} item={ibr}")
    pw.set_page_center(pcx + 300.0, pcy - 200.0)
    scene.notify_edit(pw)
    gap2 = _corner_gap(pw, px) if px is not None else float("inf")
    check("改位姿后运行预览自动重对齐", gap2 < 1e-6, f"gap={gap2:.6f}")
    scene.set_scene_mode(False)
    check("退出运行预览后 proxy 清空", len(scene.widget_proxies) == 0,
          str(len(scene.widget_proxies)))
    scene.delete_items([pw])
    app.processEvents()

    print("\n=== 8.24 双击跟手：左键拖动取消后，图元随光标移动 ===")
    view = window.view

    def _vp_of(page_xy):
        return view.mapFromScene(scene.projection.point(*page_xy))

    def _page_of(vp):
        sp = view.mapToScene(vp)
        return scene.projection.inverse_point(sp.x(), sp.y())

    fg = scene.create_item("rect", center=(12200.0, 8800.0), size=(80.0, 50.0))
    fkid = scene.create_item("rect", center=(12200.0, 8800.0), size=(20.0, 20.0))
    fkid.set_page_parent(fg.item_id)
    fg.set_page_field("children_ids", [fkid.item_id])
    scene.index.rebuild_links()
    scene.clearSelection()
    view.centerOn(scene.projection.point(12200.0, 8800.0))
    app.processEvents()

    start = fg.page_center()
    kstart = fkid.page_center()
    p0 = _vp_of(start)
    QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, p0)
    app.processEvents()
    check("双击图元进入跟手并选中它",
          view.is_following() and fg.isSelected()
          and [it.item_id for it in view._follow_items] == [fg.item_id],
          f"following={view.is_following()} sel={[it.item_id for it in scene.selected_items()]}")

    p1 = p0 + QPoint(48, -36)
    QTest.mouseMove(view.viewport(), p1)
    app.processEvents()
    exp = (_page_of(p1)[0] - _page_of(p0)[0], _page_of(p1)[1] - _page_of(p0)[1])
    act = (fg.page_center()[0] - start[0], fg.page_center()[1] - start[1])
    check("跟手位移与光标位移一致（无需任何修饰键）",
          abs(exp[0] - act[0]) < 0.6 and abs(exp[1] - act[1]) < 0.6,
          f"exp=({exp[0]:.2f},{exp[1]:.2f}) act=({act[0]:.2f},{act[1]:.2f})")
    kact = (fkid.page_center()[0] - kstart[0], fkid.page_center()[1] - kstart[1])
    check("成员随根父对象刚体移动",
          abs(kact[0] - act[0]) < 0.6 and abs(kact[1] - act[1]) < 0.6,
          f"kid=({kact[0]:.2f},{kact[1]:.2f}) parent=({act[0]:.2f},{act[1]:.2f})")

    dropped = fg.page_center()
    QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, p1)
    app.processEvents()
    check("单击落定：退出跟手且停在当前位置",
          not view.is_following()
          and abs(fg.page_center()[0] - dropped[0]) < 1e-6
          and abs(fg.page_center()[1] - dropped[1]) < 1e-6,
          f"following={view.is_following()} pos={fg.page_center()}")

    scene.clearSelection()
    fg.setSelected(True)
    p2 = _vp_of(fg.page_center())
    QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, p2)
    app.processEvents()
    QTest.mouseMove(view.viewport(), p2 + QPoint(60, 0))
    app.processEvents()
    moved = fg.page_center()
    QTest.keyPress(view, Qt.Key_Escape)
    app.processEvents()
    check("Esc 放回抓住时的位置",
          not view.is_following()
          and abs(fg.page_center()[0] - dropped[0]) < 0.6
          and abs(fg.page_center()[1] - dropped[1]) < 0.6
          and (abs(moved[0] - dropped[0]) > 1.0
               or abs(moved[1] - dropped[1]) > 1.0),
          f"moved={moved} restored={fg.page_center()} was={dropped}")

    scene.clearSelection()
    kp = _vp_of(fkid.page_center())
    QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, kp)
    app.processEvents()
    check("双击子图元抓的是根父对象",
          view.is_following()
          and [it.item_id for it in view._follow_items] == [fg.item_id],
          f"follow={[it.item_id for it in view._follow_items]} root={fg.item_id}")
    QTest.keyPress(view, Qt.Key_Escape)
    app.processEvents()

    empty = None
    for cand in (QPoint(3, 3), QPoint(3, view.viewport().height() - 4),
                 QPoint(view.viewport().width() - 4, 3)):
        if view._follow_target_at(cand) is None:
            empty = cand
            break
    if empty is not None:
        QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, empty)
        app.processEvents()
    check("双击空白处不进入跟手",
          empty is not None and not view.is_following(),
          f"empty={empty}")

    scene.clearSelection()
    scene.delete_items([fg])      # 组树一起删掉（递归删除）
    app.processEvents()

    print("\n=== 8.25 跟手时滚轮缩放：锚点跟着光标，图元不乱跳 ===")
    from Designer.CoreQGraphics.g_view import GraphicsView  # noqa: PLC0415

    # 独立场景 / 视图：不污染主窗口的缩放与 §9 的可见范围判断
    zscene = GraphicsScene()
    zview = GraphicsView(zscene)
    zview.resize(900, 600)
    zview.show()
    app.processEvents()
    zit = zscene.create_item("rect", center=(300.0, 200.0), size=(160.0, 100.0))
    zview.centerOn(zscene.projection.point(300.0, 200.0))
    app.processEvents()

    def _zwheel(vp, up=True):
        gp = zview.viewport().mapToGlobal(vp)
        ev = QWheelEvent(QPointF(vp), QPointF(gp), QPoint(),
                         QPoint(0, 120 if up else -120),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        app.sendEvent(zview.viewport(), ev)
        app.processEvents()

    zgrab = zview.mapFromScene(zscene.projection.point(300.0, 200.0))
    QTest.mouseMove(zview.viewport(), zgrab)
    app.processEvents()
    QTest.mouseDClick(zview.viewport(), Qt.LeftButton, Qt.NoModifier, zgrab)
    app.processEvents()
    # 先跟手走一段：让跟手分支把基类的 lastMousePos 甩在后面（回归点）
    zcur = zgrab + QPoint(30, 20)
    QTest.mouseMove(zview.viewport(), zcur)
    app.processEvents()
    check("独立视图里双击进入跟手", zview.is_following())

    anchor_a = zview.mapToScene(zcur)
    zpage = zit.page_center()
    _zwheel(zcur, True)
    anchor_b = zview.mapToScene(zcur)
    zpage2 = zit.page_center()
    check("滚轮缩放以光标为锚点（画面不整体平移）",
          abs(anchor_b.x() - anchor_a.x()) < 1.5
          and abs(anchor_b.y() - anchor_a.y()) < 1.5,
          f"err=({anchor_b.x()-anchor_a.x():.3f},{anchor_b.y()-anchor_a.y():.3f}) "
          f"m11={zview.transform().m11():.3f}")
    check("缩放是视图操作，不改图元位置",
          abs(zpage2[0] - zpage[0]) < 1e-6 and abs(zpage2[1] - zpage[1]) < 1e-6,
          f"page={zpage} -> {zpage2}")

    # 缩放后继续拖：位移仍等于光标位移（基准已同步，不补一段）
    za = zview.mapToScene(zcur)
    zp = zit.page_center()
    zcur2 = zcur + QPoint(40, 0)
    QTest.mouseMove(zview.viewport(), zcur2)
    app.processEvents()
    zb = zview.mapToScene(zcur2)
    zp2 = zit.page_center()
    pa = zscene.projection.inverse_point(za.x(), za.y())
    pb = zscene.projection.inverse_point(zb.x(), zb.y())
    exp_page = (pb[0] - pa[0], pb[1] - pa[1])
    check("缩放过一次后跟手位移依然对得上",
          abs((zp2[0] - zp[0]) - exp_page[0]) < 1.2
          and abs((zp2[1] - zp[1]) - exp_page[1]) < 1.2,
          f"exp_page=({exp_page[0]:.2f},{exp_page[1]:.2f}) "
          f"act=({zp2[0]-zp[0]:.2f},{zp2[1]-zp[1]:.2f})")
    check("缩放后仍保持跟手状态", zview.is_following())

    QTest.keyPress(zview, Qt.Key_Escape)
    app.processEvents()

    print("\n=== 8.3 画布导航门控（运行态复用同一套平移 / 缩放） ===")
    check("设计态默认开启平移与缩放",
          zview.is_pan_enabled() and zview.is_zoom_enabled()
          and zview.is_canvas_navigation_enabled())
    zview.set_canvas_navigation_enabled(False)
    check("一次性关闭同时作用到两个开关",
          not zview.is_pan_enabled() and not zview.is_zoom_enabled()
          and not zview.is_canvas_navigation_enabled())

    nav_pt = QPoint(zview.viewport().width() // 2,
                    zview.viewport().height() // 2)
    m_before = zview.transform().m11()
    _zwheel(nav_pt, True)
    check("门控关闭时滚轮不缩放",
          abs(zview.transform().m11() - m_before) < 1e-9,
          f"m11={zview.transform().m11():.6f} was={m_before:.6f}")

    QTest.mousePress(zview.viewport(), Qt.MiddleButton, Qt.NoModifier, nav_pt)
    app.processEvents()
    panning_off = zview._panning
    QTest.mouseMove(zview.viewport(), nav_pt + QPoint(30, 20))
    QTest.mouseRelease(zview.viewport(), Qt.MiddleButton, Qt.NoModifier,
                       nav_pt + QPoint(30, 20))
    app.processEvents()
    check("门控关闭时中键不进入平移", not panning_off)

    QTest.keyPress(zview, Qt.Key_Space)
    app.processEvents()
    space_off = zview._space_held
    QTest.keyRelease(zview, Qt.Key_Space)
    app.processEvents()
    check("门控关闭时空格不平移", not space_off)

    zview.set_canvas_navigation_enabled(True)
    m_before = zview.transform().m11()
    _zwheel(nav_pt, True)
    check("门控打开后滚轮恢复缩放",
          zview.transform().m11() > m_before * 1.01,
          f"m11={zview.transform().m11():.4f} was={m_before:.4f}")

    QTest.mousePress(zview.viewport(), Qt.MiddleButton, Qt.NoModifier, nav_pt)
    app.processEvents()
    panning_on = zview._panning
    QTest.mouseRelease(zview.viewport(), Qt.MiddleButton, Qt.NoModifier, nav_pt)
    app.processEvents()
    check("门控打开后中键恢复平移",
          panning_on and not zview._panning,
          f"press={panning_on} release={zview._panning}")

    QTest.keyPress(zview, Qt.Key_Space)
    app.processEvents()
    space_on = zview._space_held
    QTest.keyRelease(zview, Qt.Key_Space)
    app.processEvents()
    check("门控打开后空格恢复平移手势",
          space_on and not zview._space_held,
          f"press={space_on} release={zview._space_held}")

    # 单独关闭某一个：只想"看细节不许拖走画面"的运行窗口用得上
    zview.set_pan_enabled(False)
    check("平移与缩放可单独关",
          not zview.is_pan_enabled() and zview.is_zoom_enabled()
          and not zview.is_canvas_navigation_enabled())
    zview.set_canvas_navigation_enabled(True)

    zview.close()
    zview.deleteLater()
    app.processEvents()

    print("\n=== 8.26 捕捉点取真实端点：线头 / 三角顶点 / 选中项自身端点 ===")
    # 独立场景 / 视图：不污染主窗口，也不影响 §9 的可见范围判断
    nscene = GraphicsScene()
    nview = GraphicsView(nscene)
    nview.resize(900, 600)
    nview.show()
    app.processEvents()
    hline = nscene.create_item("line", center=(300.0, 200.0))
    hline.set_page_head_end(QPointF(200.0, 200.0), QPointF(400.0, 200.0))
    tri3 = nscene.create_item("triangle", center=(300.0, 500.0))
    tri3.set_page_vertices([QPointF(200.0, 560.0), QPointF(400.0, 560.0),
                            QPointF(300.0, 440.0)])
    nview.centerOn(nscene.projection.point(300.0, 350.0))
    app.processEvents()
    nview.refresh_snap_points()

    def _sc(x, y) -> QPointF:
        p = nscene.projection.point(x, y)
        return QPointF(p.x(), p.y())

    head, tail = _sc(200.0, 200.0), _sc(400.0, 200.0)
    ends, _mids = hline.snap_points()
    check("水平线的两端是真实端点（不再取加厚后的包围盒虚角）",
          len(ends) == 2
          and any(_close_pt((p.x(), p.y()), (head.x(), head.y()), 1e-6)
                  for p in ends)
          and any(_close_pt((p.x(), p.y()), (tail.x(), tail.y()), 1e-6)
                  for p in ends),
          f"ends={[(round(p.x(), 1), round(p.y(), 1)) for p in ends]}")

    apex = _sc(300.0, 440.0)
    tends, _tm = tri3.snap_points()
    check("三角形顶点进入捕捉点",
          len(tends) == 3
          and any(_close_pt((p.x(), p.y()), (apex.x(), apex.y()), 1e-6)
                  for p in tends),
          f"ends={[(round(p.x(), 1), round(p.y(), 1)) for p in tends]}")

    # 光标凑到线头：十字必须落在端点上（旧版这里会跳到旁边的格点）
    nscene.clearSelection()
    hv = nview.mapFromScene(head)
    QTest.mouseMove(nview.viewport(), QPoint(hv.x() + 2, hv.y() + 1))
    app.processEvents()
    mk, _act = nview._hover_marker()
    check("光标靠近线端点时十字就在端点上",
          mk is not None
          and _close_pt((mk.x(), mk.y()), (head.x(), head.y()), 1e-6),
          f"marker=({mk.x():.2f},{mk.y():.2f}) "
          f"head=({head.x():.2f},{head.y():.2f})" if mk else "marker=None")
    check("端点上画出红色十字",
          _scan(nview.viewport().grab().toImage(), hv.x(), hv.y(),
                12, _is_red_cross),
          f"vp=({hv.x()},{hv.y()})")

    # 选中这条线后再凑近它自己的端点：自身点彻底不纳入扫描。
    # 这里的端点恰好压在网格交汇点上，同坐标仍能吸到**格点**十字，但它
    # 已经不是「图元自身特征点」了；真正验证「不显示」的是 §8.27（那里的
    # 端点特意挑在不落在格点上的位置）。
    hline.setSelected(True)
    app.processEvents()
    QTest.mouseMove(nview.viewport(), QPoint(hv.x() + 2, hv.y() + 1))
    app.processEvents()
    mk2, act2 = nview._hover_marker()
    check("选中后自身端点进入排除集合（不纳入捕捉点扫描）",
          (head.x(), head.y()) in nview._selection_own_points(),
          f"own={len(nview._selection_own_points())}")
    check("光标处仍是唯一一个十字（来自同坐标的网格点）",
          mk2 is not None
          and _close_pt((mk2.x(), mk2.y()), (head.x(), head.y()), 1e-6),
          f"marker={mk2}")
    check("自身点不再作为吸附目标（active 只由门控决定）",
          act2 == bool(nview.snap.enabled), f"active={act2}")
    hover_pt = QPointF(nview.snap.hover)
    snap_target, _sk = nview.snap.aim(hover_pt,
                                      exclude=nview._selection_own_points(),
                                      always=True)
    keep = QPointF(hline.scenePos())
    nview.snap.enabled = False
    QTest.keyClick(nview, Qt.Key_T)
    app.processEvents()
    moved = QPointF(hline.scenePos()) - keep
    want = QPointF(0.0, 0.0) if snap_target is None else snap_target - hover_pt
    check("按 T 不吸到自身端点，且仅选中时图元不移动",
          abs(moved.x()) < 1e-6 and abs(moved.y()) < 1e-6
          and snap_target is not None and nview._last_hover is not None
          and math.hypot(nview._last_hover.x() - snap_target.x(),
                         nview._last_hover.y() - snap_target.y()) < 1e-6,
          f"moved=({moved.x():.3f},{moved.y():.3f}) "
          f"hover={nview._last_hover} target={snap_target}")

    nview.snap.enabled = False
    nview.close()
    nview.deleteLater()
    app.processEvents()

    print("\n=== 8.27 T 键：抓起图元捕捉点 → 排除自身点 → 按 T 对齐到别的捕捉点 ===")
    # 独立场景 / 视图：不污染主窗口，也不影响 §9 的可见范围判断
    tscene = GraphicsScene()
    tview = GraphicsView(tscene)
    tview.resize(900, 600)
    tview.show()
    app.processEvents()

    # 故意用非整十的 page 坐标：端点不会恰好压在网格交汇点上，
    # 这样「十字来自图元点还是格点」可以明确区分。
    ga = tscene.create_item("rect", center=(1013.0, 987.0))
    ga.set_page_size(207.0, 123.0)
    gb = tscene.create_item("rect", center=(1613.0, 987.0))
    gb.set_page_size(207.0, 123.0)
    tview.centerOn(tscene.projection.point(1300.0, 1000.0))
    app.processEvents()
    tview.refresh_snap_points()

    def grid_gap(p):
        gx, gy = tview.snap.nearest_grid(p)
        return math.hypot(p.x() - gx, p.y() - gy)

    def off_grid(pts):
        for p in pts:
            if grid_gap(p) > 1e-6:
                return QPointF(p)
        return QPointF(pts[0])

    a_ends, a_mids = ga.snap_points()
    b_ends, b_mids = gb.snap_points()
    a_anchor = off_grid(a_ends)
    b_target = off_grid(b_ends)
    check("两个捕捉点都不压在网格点上（可区分图元点 / 格点）",
          grid_gap(a_anchor) > 1e-6 and grid_gap(b_target) > 1e-6,
          f"a={grid_gap(a_anchor):.3f} b={grid_gap(b_target):.3f}")

    # ---- 需求 1：按 T 吸附到图元捕捉点 → 选中该图元 + 进入抓手 + 记录该点 ----
    tscene.clearSelection()
    tview._snap_offset = QPointF(0.0, 0.0)
    tview._set_hover(QPointF(a_anchor))
    app.processEvents()
    aim_kind = tview.snap.aim(QPointF(a_anchor),
                              exclude=tview._selection_own_points(),
                              always=True)[1]
    check("最近的捕捉点确实来自图元（归属表能查到 id）",
          aim_kind == "element"
          and ga.item_id in tview.snap.owners_at(QPointF(a_anchor)),
          f"kind={aim_kind} owners={tview.snap.owners_at(QPointF(a_anchor))}")

    before_a = QPointF(ga.scenePos())
    QTest.keyClick(tview, Qt.Key_T)
    app.processEvents()
    check("按 T 命中图元点 → 该图元被选中",
          ga.isSelected()
          and [it.item_id for it in tscene.selected_items()] == [ga.item_id],
          f"sel={[it.item_id for it in tscene.selected_items()]}")
    grab_pt = tview.snap_grab_point()
    check("进入抓手并记录下该图元的捕捉点",
          tview.is_snap_grabbing() and grab_pt is not None
          and _close_pt((grab_pt.x(), grab_pt.y()),
                        (a_anchor.x(), a_anchor.y()), 1e-6),
          f"grab={grab_pt}")
    # 抓手后该点已被选中项排除，若 warp 重新 aim 就会漂到旁边的格点 ——
    # 这正是「按 T 鼠标没有吸附到图元捕捉点」的根因。hover 必须仍落在锚点上。
    hover_t = tview.snap.hover
    check("按 T 光标吸附到图元捕捉点（没有漂到旁边格点）",
          hover_t is not None
          and math.hypot(hover_t.x() - a_anchor.x(),
                         hover_t.y() - a_anchor.y()) < 2.0
          and grid_gap(QPointF(hover_t)) > 1e-6,
          f"hover={hover_t} anchor={a_anchor} grid_gap="
          f"{grid_gap(QPointF(hover_t)) if hover_t else -1:.3f}")
    check("抓手 = 实时跟手状态（图元随鼠标走）",
          tview.is_following()
          and [it.item_id for it in tview._follow_items] == [ga.item_id],
          f"follow={[it.item_id for it in tview._follow_items]}")
    check("按 T 瞬间不把光标 warp 当成一次拖动（图元不跳）",
          _close_pt((ga.scenePos().x(), ga.scenePos().y()),
                    (before_a.x(), before_a.y()), 1e-6),
          f"pos={ga.scenePos()}")
    check("T 改为一次性动作键：门控恒开", tview.snap.enabled)

    # ---- 需求 2：已选中图元的特征点彻底不纳入捕捉点扫描 ----
    own = tview._selection_own_points()
    check("已选中图元的特征点全部进入排除集合",
          all((p.x(), p.y()) in own for p in a_ends + a_mids),
          f"own={len(own)}")
    tview._set_hover(QPointF(a_anchor))
    app.processEvents()
    mk3, _act3 = tview._hover_marker()
    check("光标停在自身端点上时，十字不再落在自身点上",
          mk3 is not None
          and not _close_pt((mk3.x(), mk3.y()),
                            (a_anchor.x(), a_anchor.y()), 1e-6)
          and (mk3.x(), mk3.y()) not in own,
          f"marker={mk3}")

    # ---- 实时跟手：鼠标走到哪，图元与被抓的捕捉点就跟到哪 ----
    mid_scene = QPointF(a_anchor) + QPointF(0.0, -60.0)
    vp_mid = tview.mapFromScene(mid_scene)
    QTest.mouseMove(tview.viewport(), QPoint(vp_mid.x(), vp_mid.y()))
    app.processEvents()
    mid_move = QPointF(ga.scenePos()) - before_a
    check("抓手期间鼠标移动 → 图元实时跟手",
          abs(mid_move.x()) < 2.0 and abs(mid_move.y() + 60.0) < 2.0,
          f"moved=({mid_move.x():.2f},{mid_move.y():.2f})")
    grab_mid = tview.snap_grab_point()
    check("被抓捕捉点随跟手同步平移（记录不留在原地）",
          grab_mid is not None
          and abs(grab_mid.x() - a_anchor.x()) < 2.0
          and abs(grab_mid.y() - (a_anchor.y() - 60.0)) < 2.0,
          f"grab={grab_mid}")

    # ---- 需求 3：扫到别的捕捉点按 T → 精修对齐并更新记录的捕捉点 ----
    vp_b = tview.mapFromScene(QPointF(b_target))
    QTest.mouseMove(tview.viewport(), QPoint(vp_b.x(), vp_b.y()))
    app.processEvents()
    before2 = QPointF(ga.scenePos())
    QTest.keyClick(tview, Qt.Key_T)
    app.processEvents()
    total = QPointF(ga.scenePos()) - before_a
    want2 = QPointF(b_target) - QPointF(a_anchor)
    fine = QPointF(ga.scenePos()) - before2
    check("第二次按 T 后捕捉点精确对齐到新点（总位移 = 两点差）",
          abs(total.x() - want2.x()) < 2.0
          and abs(total.y() - want2.y()) < 2.0,
          f"total=({total.x():.3f},{total.y():.3f}) "
          f"want=({want2.x():.3f},{want2.y():.3f}) "
          f"按T补量=({fine.x():.3f},{fine.y():.3f})")
    grab_pt2 = tview.snap_grab_point()
    check("记录的捕捉点坐标更新为新捕捉点",
          grab_pt2 is not None
          and _close_pt((grab_pt2.x(), grab_pt2.y()),
                        (b_target.x(), b_target.y()), 1e-6),
          f"grab={grab_pt2}")
    ends_after, mids_after = ga.snap_points()
    check("图元上确实有一个捕捉点落在新坐标上",
          any(_close_pt((p.x(), p.y()), (b_target.x(), b_target.y()), 1e-6)
              for p in ends_after + mids_after),
          f"ends={[(round(p.x(), 1), round(p.y(), 1)) for p in ends_after]}")
    check("对齐后抓手 / 跟手仍保持（可连续对齐）",
          tview.is_snap_grabbing() and tview.is_following())

    before3 = QPointF(ga.scenePos())
    QTest.keyClick(tview, Qt.Key_T)   # 原地再按一次
    app.processEvents()
    repeat = QPointF(ga.scenePos()) - before3
    check("同一位置重复按 T 不重复推图元",
          abs(repeat.x()) < 1e-6 and abs(repeat.y()) < 1e-6,
          f"moved=({repeat.x():.3f},{repeat.y():.3f})")

    QTest.keyClick(tview, Qt.Key_Escape)
    app.processEvents()
    check("Esc 退出抓手并结束跟手（整组回到抓住时位置）",
          not tview.is_snap_grabbing()
          and tview.snap_grab_point() is None
          and not tview.is_following()
          and _close_pt((ga.scenePos().x(), ga.scenePos().y()),
                        (before_a.x(), before_a.y()), 1e-6),
          f"pos={ga.scenePos()}")

    tscene.delete_items([ga.item_id, gb.item_id])
    tview.close()
    tview.deleteLater()
    app.processEvents()

    print("\n=== 8.28 绘制阶段按 T：只吸附光标，不选中图元 / 不抓手跟手 ===")
    dscene = GraphicsScene()
    dview = GraphicsView(dscene)
    dview.resize(900, 600)
    dview.show()
    app.processEvents()

    existing = dscene.create_item("rect", center=(1013.0, 987.0))
    existing.set_page_size(207.0, 123.0)
    dview.centerOn(dscene.projection.point(1013.0, 987.0))
    app.processEvents()
    dview.refresh_snap_points()
    e_ends, _em = existing.snap_points()

    def dgap(p):
        gx, gy = dview.snap.nearest_grid(p)
        return math.hypot(p.x() - gx, p.y() - gy)

    snap_target = next((QPointF(p) for p in e_ends if dgap(p) > 1e-6),
                       QPointF(e_ends[0]))
    dscene.clearSelection()
    dview.set_draw_tool("line")
    dscene.begin_draw_tool("line")
    dscene.draw_add_point(QPointF(900.0, 900.0))   # 已落第一点，进入绘制中
    dview._set_hover(QPointF(snap_target))
    app.processEvents()
    before_existing = QPointF(existing.scenePos())
    QTest.keyClick(dview, Qt.Key_T)
    app.processEvents()

    check("绘制中按 T 不选中已有图元",
          not existing.isSelected(),
          f"sel={[it.item_id for it in dscene.selected_items()]}")
    check("绘制中按 T 不进入抓手 / 跟手",
          not dview.is_snap_grabbing() and not dview.is_following()
          and dview.snap_grab_point() is None,
          f"grab={dview.is_snap_grabbing()} follow={dview.is_following()}")
    check("绘制中按 T 不移动已有图元",
          _close_pt((existing.scenePos().x(), existing.scenePos().y()),
                    (before_existing.x(), before_existing.y()), 1e-6),
          f"pos={existing.scenePos()}")
    hover_d = dview.snap.hover
    check("绘制中按 T 仍把光标吸附到图元捕捉点",
          hover_d is not None
          and math.hypot(hover_d.x() - snap_target.x(),
                         hover_d.y() - snap_target.y()) < 2.0,
          f"hover={hover_d} target={snap_target}")
    state_d = dscene.draw_preview_state()
    preview_scene = (dscene.projection.point(state_d[2].x(), state_d[2].y())
                     if state_d is not None and state_d[2] is not None else None)
    check("绘制预览同步到吸附点（按 T 取点生效）",
          preview_scene is not None
          and math.hypot(preview_scene.x() - snap_target.x(),
                         preview_scene.y() - snap_target.y()) < 2.0,
          f"preview={state_d[2] if state_d else None} target={snap_target}")
    check("绘制工具仍激活（没被跟手抢走）", dview._draw_type == "line")

    vp_move = dview.mapFromScene(QPointF(snap_target) + QPointF(0.0, -40.0))
    QTest.mouseMove(dview.viewport(), QPoint(vp_move.x(), vp_move.y()))
    app.processEvents()
    state_d2 = dscene.draw_preview_state()
    check("绘制中鼠标移动仍走绘制预览、不触发跟手",
          not dview.is_following()
          and _close_pt((existing.scenePos().x(), existing.scenePos().y()),
                        (before_existing.x(), before_existing.y()), 1e-6)
          and state_d2 is not None and state_d2[2] is not None,
          f"follow={dview.is_following()} pos={existing.scenePos()}")

    # ---- 绘制阶段的「自身」：正在画的临时图元端点 / 中点也要排除 ----
    draw_item = dscene._draw_item
    d_ends, d_mids = draw_item.snap_points()
    dview.refresh_snap_points()
    draw_excluded = dview._draw_own_points()
    check("绘制临时图元的自身点确实进了捕捉点表（否则无需排除）",
          len(draw_excluded) > 0
          and all(c in dview.snap.all_points() for c in draw_excluded),
          f"excluded={len(draw_excluded)} table={dview.snap.count()}")
    self_pt = next(
        (QPointF(p) for p in d_ends + d_mids
         if (p.x(), p.y()) in draw_excluded and dgap(p) > 1e-6),
        None)
    check("存在不压在格点上的自身点（可区分是否误吸）",
          self_pt is not None, f"excluded={sorted(draw_excluded)[:3]}")
    if self_pt is not None:
        dview._set_hover(QPointF(self_pt))
        app.processEvents()
        mk_self, _act_self = dview._hover_marker()
        check("绘制中十字不落在临时图元自身点上",
              mk_self is not None
              and not _close_pt((mk_self.x(), mk_self.y()),
                                (self_pt.x(), self_pt.y()), 1e-6),
              f"marker={mk_self} self={self_pt}")
        QTest.keyClick(dview, Qt.Key_T)
        app.processEvents()
        final_hover = dview.snap.hover
        check("绘制中按 T 不吸到临时图元自身点（排除生效）",
              final_hover is not None
              and not _close_pt((final_hover.x(), final_hover.y()),
                                (self_pt.x(), self_pt.y()), 1e-6),
              f"hover={final_hover} self={self_pt}")

    dscene.cancel_draw()
    dview.set_draw_tool(None)
    dscene.delete_items([existing.item_id])
    dview.close()
    dview.deleteLater()
    app.processEvents()

    print("\n=== 8.29 大页面全选性能 / 批量选中 ===")
    # 逐项 setSelected 会发 N 次 selectionChanged，而图层树回灌 / 属性面板
    # 重建随选中数增长；1618 个图元的 page_1 实测会卡死数分钟。这里用真实
    # 大页面锁住「只发一次信号 + 同步结果不变」。
    big = DesignerWindow(SOURCE_PAGE)
    big.show()
    app.processEvents()
    bs = big.scene
    total = len(bs.all_items())
    hits = [0]
    bs.selectionChanged.connect(lambda: hits.__setitem__(0, hits[0] + 1))
    t0 = time.perf_counter()
    bs.select_all_items()
    elapsed = time.perf_counter() - t0
    check("大页面全选只发一次 selectionChanged", hits[0] == 1,
          f"signals={hits[0]} items={total}")
    check("大页面全选耗时可接受", elapsed < 5.0, f"{elapsed:.3f}s")
    check("全选后场景选中数正确", len(bs.selected_items()) == total,
          f"{len(bs.selected_items())}/{total}")
    check("全选后图层树同步选中全部",
          len(big.layers.selected_ids()) == total,
          f"tree={len(big.layers.selected_ids())}")
    check("全选后属性面板为多选概要",
          big.property_panel.stack.count() > 0
          and big.property_panel.stack.widget(0).objectName() == "multi",
          f"page={big.property_panel.stack.widget(0).objectName() if big.property_panel.stack.count() else '-'}")
    check("全选后状态栏显示选中数", f"选中 {total}" in big.count_label.text(),
          big.count_label.text())
    # 主窗口槽与图层树自身连接会调两次 sync_selection，第二次必须幂等
    big.layers.sync_selection()
    big.layers.sync_selection()
    check("重复 sync_selection 幂等", len(big.layers.selected_ids()) == total,
          f"tree={len(big.layers.selected_ids())}")

    bs.clearSelection()
    app.processEvents()
    check("清空选中后图层树同步清空", len(big.layers.selected_ids()) == 0,
          f"tree={len(big.layers.selected_ids())}")
    one, other = bs.all_items()[0], bs.all_items()[1]
    hits[0] = 0
    bs.select_items([one])
    check("批量单选只发一次信号", hits[0] == 1, f"signals={hits[0]}")
    check("批量单选后图层树只选一个",
          big.layers.selected_ids() == [one.item_id],
          f"tree={big.layers.selected_ids()[:5]}")
    bs.select_items([other], append=True)
    check("append=True 累加选中", len(bs.selected_items()) == 2
          and set(i.item_id for i in bs.selected_items())
          == {one.item_id, other.item_id})
    big.close()
    big.deleteLater()
    app.processEvents()
    try:
        bs.selectionChanged.disconnect()
    except Exception:
        pass

    print("\n=== 8.30 仅选中时按 T 只移动光标、不移动图元 ===")
    # 旧版在「未抓手」时会把吸附偏移叠加到已选中图元上（鼠标吸多少、
    # 图元走多少）。hover 必须**靠近但不落在**格点上，offset 才非零，
    # 否则测不出这个行为（正好落在格点时 offset=0、图元本来就不动）。
    sscene = GraphicsScene()
    sview = GraphicsView(sscene)
    sview.resize(900, 600)
    sview.show()
    app.processEvents()
    sa = sscene.create_item("rect", center=(1013.0, 987.0))
    sa.set_page_size(207.0, 123.0)
    sb = sscene.create_item("rect", center=(1613.0, 987.0))
    sb.set_page_size(207.0, 123.0)
    sview.centerOn(sscene.projection.point(1300.0, 1000.0))
    app.processEvents()
    sview.refresh_snap_points()

    def s_pts(it):
        ends, mids = it.snap_points()
        return ends + mids

    def s_offgrid(p):
        gx, gy = sview.snap.nearest_grid(p)
        return math.hypot(p.x() - gx, p.y() - gy) > 1e-6

    b_anchor = next(QPointF(p) for p in s_pts(sb) if s_offgrid(p))
    grid_pt = QPointF(*sview.snap.nearest_grid(QPointF(2500.0, 2500.0)))
    near_grid = QPointF(grid_pt) + QPointF(3.0, -4.0)

    sscene.clearSelection()
    sa.setSelected(True)
    app.processEvents()
    pos_a = QPointF(sa.scenePos())
    sview._set_hover(QPointF(near_grid))
    app.processEvents()
    aim_t, aim_k = sview.snap.aim(
        QPointF(near_grid), exclude=sview._snap_scan_exclude(), always=True)
    check("hover 靠近格点但不重合（吸附偏移非零，能测出旧兜底）",
          aim_k == "grid" and aim_t is not None
          and math.hypot(aim_t.x() - near_grid.x(),
                         aim_t.y() - near_grid.y()) > 1e-6,
          f"kind={aim_k} target={aim_t}")
    QTest.keyClick(sview, Qt.Key_T)
    app.processEvents()
    d = QPointF(sa.scenePos()) - pos_a
    check("仅选中按 T：图元不移动（不再叠加吸附偏移）",
          abs(d.x()) < 1e-9 and abs(d.y()) < 1e-9, f"delta={d}")
    # warp 到视口外时 leaveEvent 会清 snap.hover，但 _last_hover 保留吸附点
    h = sview._last_hover
    check("仅选中按 T：光标仍吸附到捕捉点",
          h is not None
          and _close_pt((h.x(), h.y()), (grid_pt.x(), grid_pt.y()), 1e-6),
          f"hover={h}")
    check("仅选中按 T：不进入抓手 / 跟手",
          not sview.is_snap_grabbing() and not sview.is_following())
    sview._set_hover(QPointF(near_grid) + QPointF(40.0, 30.0))
    app.processEvents()
    d2 = QPointF(sa.scenePos()) - pos_a
    check("仅选中按 T 后继续移动鼠标：图元仍不动",
          abs(d2.x()) < 1e-9 and abs(d2.y()) < 1e-9, f"delta={d2}")

    # 多选同样不动
    sscene.clearSelection()
    sa.setSelected(True)
    sb.setSelected(True)
    app.processEvents()
    pos_a = QPointF(sa.scenePos())
    pos_b = QPointF(sb.scenePos())
    sview._set_hover(QPointF(near_grid))
    app.processEvents()
    QTest.keyClick(sview, Qt.Key_T)
    app.processEvents()
    da = QPointF(sa.scenePos()) - pos_a
    db = QPointF(sb.scenePos()) - pos_b
    check("多选（未抓手）按 T 也不移动任何图元",
          abs(da.x()) < 1e-9 and abs(da.y()) < 1e-9
          and abs(db.x()) < 1e-9 and abs(db.y()) < 1e-9,
          f"a={da} b={db}")

    # 未抓手吸到图元点 → 抓起，但抓起瞬间不移动任何图元
    sscene.clearSelection()
    sa.setSelected(True)
    app.processEvents()
    pos_a = QPointF(sa.scenePos())
    pos_b = QPointF(sb.scenePos())
    sview._set_hover(QPointF(b_anchor))
    app.processEvents()
    QTest.keyClick(sview, Qt.Key_T)
    app.processEvents()
    da = QPointF(sa.scenePos()) - pos_a
    db = QPointF(sb.scenePos()) - pos_b
    check("未抓手吸到图元点：抓起瞬间所有图元不动",
          abs(da.x()) < 1e-9 and abs(da.y()) < 1e-9
          and abs(db.x()) < 1e-9 and abs(db.y()) < 1e-9,
          f"a={da} b={db}")
    check("抓起后进入抓手（此后按 T 才允许移动图元）",
          sview.is_snap_grabbing() and sview.is_following())

    # 抓手状态按 T → 被抓图元才移动
    sview._set_hover(QPointF(grid_pt))
    app.processEvents()
    QTest.keyClick(sview, Qt.Key_T)
    app.processEvents()
    db2 = QPointF(sb.scenePos()) - pos_b
    check("抓手状态按 T：被抓图元移动（对齐到新捕捉点）",
          abs(db2.x()) > 1e-9 or abs(db2.y()) > 1e-9, f"delta={db2}")
    gp = sview.snap_grab_point()
    check("抓手对齐后记录点更新为新捕捉点",
          gp is not None
          and _close_pt((gp.x(), gp.y()), (grid_pt.x(), grid_pt.y()), 1e-6),
          f"grab={gp}")
    QTest.keyClick(sview, Qt.Key_Escape)
    app.processEvents()
    sview.close()
    sview.deleteLater()
    app.processEvents()

    print("\n=== 8.31 坐标刻度条（视口固定 / 数值随变换） ===")
    from Designer.CoreQGraphics.g_view import (  # noqa: E402
        _RULER_BG, _RULER_CORNER_BG, _RULER_THICKNESS,
        nice_ruler_step, ruler_label,
    )
    from PySide6.QtGui import QTransform  # noqa: E402

    T = _RULER_THICKNESS
    check("刻度步长按缩放挑 1/2/5 档",
          nice_ruler_step(4.0) == 500.0
          and nice_ruler_step(0.25) == 50.0
          and nice_ruler_step(1.0) == 100.0)
    check("刻度标签整数 / 小数格式",
          ruler_label(-500, 500) == "-500"
          and ruler_label(0.5, 0.5) == "0.5")
    window.show()
    app.processEvents()
    check("设计器默认打开刻度条",
          window.view.show_rulers
          and window.actions["toggle_rulers"].isChecked())

    on_img = window.view.viewport().grab().toImage()
    corner = on_img.pixelColor(5, 5).getRgb()[:3]
    hbar = on_img.pixelColor(T + 40, 5).getRgb()[:3]
    vbar = on_img.pixelColor(5, T + 40).getRgb()[:3]
    check("水平 / 垂直 / 交叉块都画出来",
          corner == _RULER_CORNER_BG.getRgb()[:3]
          and hbar == _RULER_BG.getRgb()[:3]
          and vbar == _RULER_BG.getRgb()[:3],
          f"{corner} / {hbar} / {vbar}")
    xmax = min(on_img.width(), 300)
    ticks = sum(
        on_img.pixelColor(x, y).getRgb()[:3] != _RULER_BG.getRgb()[:3]
        for y in range(0, T, 2) for x in range(T, xmax, 2))
    check("水平标尺上有刻度线 / 数字", ticks > 0, str(ticks))

    window.actions["toggle_rulers"].setChecked(False)
    window._do("toggle_rulers")
    app.processEvents()
    off_img = window.view.viewport().grab().toImage()
    check("菜单关掉后不再画刻度条",
          off_img.pixelColor(T + 40, 5) != on_img.pixelColor(T + 40, 5))
    window.actions["toggle_rulers"].setChecked(True)
    window._do("toggle_rulers")
    app.processEvents()

    def _ruler_span():
        p0 = window.view.mapToScene(QPoint(0, 0))
        p1 = window.view.mapToScene(QPoint(1, 0))
        return abs(p1.x() - p0.x())

    # 离屏 grab 在门禁后半段可能返回缓存帧，这里直接验证刻度换算的输入：
    # 视图变换一变，每像素场景跨度与主刻度步长就必须跟着跳档。
    old_tf = QTransform(window.view.transform())
    step_before = nice_ruler_step(_ruler_span())
    window.view.scale(2.0, 2.0)
    app.processEvents()
    step_after = nice_ruler_step(_ruler_span())
    check("缩放后刻度步长随视图变换跳档",
          step_before != step_after,
          f"{step_before} -> {step_after}")
    window.view.setTransform(old_tf)
    window.view.viewport().update()
    app.processEvents()

    # 只切标志，不真的挂 / 销毁运行态 proxy，避免影响后续断言
    old_run = scene.is_run_mode
    scene.is_run_mode = True
    app.processEvents()
    run_img = window.view.viewport().grab().toImage()
    check("运行态不显示刻度条",
          run_img.pixelColor(T + 40, 5) != on_img.pixelColor(T + 40, 5))
    scene.is_run_mode = old_run
    app.processEvents()

    print("\n=== 8.32 图元锁定：同心圆标记 / 设计模式位姿只读 ===")
    from Designer.CoreQGraphics.g_view import _LOCK_BADGE_OFFSET  # noqa: E402
    from PySide6.QtGui import QKeySequence  # noqa: E402

    vp_c = window.view.mapToScene(window.view.viewport().rect().center())
    cx, cy = scene.projection.inverse_point(vp_c.x(), vp_c.y())
    li = scene.create_item("rect", center=(cx, cy), size=(600.0, 400.0))
    li_id = li.item_id
    scene.clearSelection()
    app.processEvents()
    lr = li.sceneBoundingRect()
    bp = (QPointF(window.view.mapFromScene(QPointF(lr.left(), lr.bottom())))
          + _LOCK_BADGE_OFFSET)
    bx, by = int(bp.x()), int(bp.y())

    def _badge_frame():
        # 离屏 grab 会拿到缓存帧，显式 update + 两轮事件循环才可靠
        window.view.viewport().update()
        app.processEvents()
        app.processEvents()
        return window.view.viewport().grab().toImage()

    def _badge_region(img):
        return [img.pixelColor(bx + dx, by + dy).getRgb()[:3]
                for dy in range(-8, 9, 2) for dx in range(-8, 9, 2)]

    off_img = _badge_frame()
    check("存量图元缺省未锁定（记录里没有 locked 键）",
          not li.is_locked() and "locked" not in li.to_page_record())
    li.set_locked(True)
    on_img = _badge_frame()
    changed = sum(u != v for u, v in
                  zip(_badge_region(off_img), _badge_region(on_img)))
    check("锁定后左下角画出同心圆标记", changed > 0, f"changed_px={changed}")
    li.set_locked(False)
    check("解锁后标记消失、画面逐像素还原",
          _badge_region(_badge_frame()) == _badge_region(off_img))
    li.set_locked(True)
    run_flag = scene.is_run_mode
    scene.is_run_mode = True
    check("运行态不显示锁定标记",
          _badge_region(_badge_frame()) == _badge_region(off_img))
    scene.is_run_mode = run_flag
    li.set_locked(False)
    app.processEvents()

    check("锁定 / 解锁动作与快捷键就位",
          window.actions["lock"].shortcut() == QKeySequence("Ctrl+L")
          and window.actions["unlock"].shortcut() == QKeySequence("Ctrl+Shift+U"))
    scene.clearSelection()
    li.setSelected(True)
    app.processEvents()
    window.history.commit()          # 基线：含这个图元、未锁定
    check("未锁定时双击抓得起图元",
          window.view.begin_follow(li, QPointF(vp_c)))
    window.view.end_follow(restore=True)
    window._do("lock")
    app.processEvents()
    li = scene.find_item(li_id)
    check("命令上锁写入 locked 并标脏",
          li.is_locked() and scene.is_modified())
    check("锁定后双击跟手被拒绝",
          not window.view.begin_follow(li, QPointF(vp_c))
          and not window.view.is_following())
    check("方向键微调目标不含锁定项",
          li_id not in [it.item_id for it in window.view._nudge_targets()])
    check("锁定后不再显示拖角手柄", window.view._resize_item() is None)
    angle0 = li.rotation()
    QTest.keyClick(window.view.viewport(), Qt.Key_BracketRight)
    app.processEvents()
    check("] 旋转对锁定图元无效", abs(li.rotation() - angle0) < 1e-9)
    pose_boxes = [box for box, _enabled in window.property_panel._pose_widgets]
    check("属性面板 X/Y/W/H/旋转全部置灰",
          len(pose_boxes) == 5 and all(not box.isEnabled() for box in pose_boxes))

    window._do("undo")
    app.processEvents()
    li = scene.find_item(li_id)
    check("撤销恢复为未锁定", li is not None and not li.is_locked())
    window._do("redo")
    app.processEvents()
    li = scene.find_item(li_id)
    check("重做恢复为锁定", li is not None and li.is_locked())
    scene.clearSelection()
    li.setSelected(True)
    app.processEvents()
    window._do("unlock")
    app.processEvents()
    li = scene.find_item(li_id)
    check("解锁后跟手恢复", window.view.begin_follow(li, QPointF(vp_c)))
    window.view.end_follow(restore=True)
    angle0 = li.rotation()
    QTest.keyClick(window.view.viewport(), Qt.Key_BracketRight)
    app.processEvents()
    check("解锁后 ] 旋转恢复生效（快捷键本身有效）",
          abs(li.rotation() - angle0) > 1e-9)

    # 「常规」页复选框是用户最常用的入口，单独验证（不在 toggled 里重建面板）
    from PySide6.QtWidgets import QCheckBox  # noqa: E402
    scene.clearSelection()
    li.setSelected(True)
    app.processEvents()
    cb = [b for b in window.property_panel.findChildren(QCheckBox)
          if b.text() == "锁定"]
    check("常规页有锁定复选框且当前未勾选",
          len(cb) == 1 and not cb[0].isChecked())
    cb[0].setChecked(True)
    app.processEvents()
    cb_boxes = [box for box, _enabled in window.property_panel._pose_widgets]
    check("勾选复选框即上锁并同步置灰位姿输入框",
          li.is_locked() and len(cb_boxes) == 5
          and all(not box.isEnabled() for box in cb_boxes))
    cb[0].setChecked(False)
    app.processEvents()
    cb_boxes = [box for box, _enabled in window.property_panel._pose_widgets]
    check("取消勾选即解锁并恢复输入框",
          not li.is_locked() and len(cb_boxes) == 5
          and all(box.isEnabled() for box in cb_boxes))
    scene.delete_items([li])
    app.processEvents()

    print("\n=== 8.33 贝塞尔曲线图元：工具箱 / 四击落子 / 控制点手柄 ===")
    from Designer.CoreQGraphics.g_path import PATH_SEGMENTS_KEY  # noqa: E402

    bz_button = next(b for b in window.toolbox.buttons if b.key == "bezier")
    bz_icon = bz_button.icon().pixmap(28, 28).toImage()
    bz_icon_px = sum(1 for y in range(28) for x in range(28)
                     if bz_icon.pixelColor(x, y).alpha() > 0)
    check("工具箱贝塞尔按钮有中文名与非空线稿图标",
          "贝塞尔" in bz_button.text() and not bz_icon.isNull()
          and bz_icon_px > 20, f"icon_px={bz_icon_px}")
    check("「新建图元」菜单自动收录贝塞尔曲线",
          any("贝塞尔" in a.text()
              for m in window.menuBar().actions()
              if m.text().replace("&", "") == "新建图元"
              for a in m.menu().actions()))
    window._activate_draw_tool("bezier")
    app.processEvents()
    check("工具箱点击后进入四点绘制模式",
          window.view._draw_type == "bezier"
          and "四下" in window.status_bar.currentMessage())

    # 真实鼠标四击：起点 / C1 / C2 / 终点
    vp = window.view.viewport()
    for pt in ((240, 300), (300, 220), (380, 300), (450, 220)):
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(*pt))
        app.processEvents()
    drawn = [it for it in scene.all_items() if it.TYPE == "bezier"]
    check("画布四击生成贝塞尔图元并自动选中",
          len(drawn) == 1 and drawn[0].isSelected()
          and not scene.drawing_active())
    window._activate_draw_tool("")
    app.processEvents()
    drawn_rec = drawn[0].to_page_record()
    bz_segs = drawn_rec.get(PATH_SEGMENTS_KEY) or []
    check("手绘结果仍是 move + curve 精确曲线",
          [d["kind"] for d in bz_segs] == ["move", "curve"]
          and all(k in bz_segs[1] for k in
                  ("c1x", "c1y", "c2x", "c2y", "x", "y")))
    check("手绘结束写入撤销栈", window.history.can_undo())
    nav_titles = [window.property_panel.nav.topLevelItem(i).text(0)
                  for i in range(window.property_panel.nav.topLevelItemCount())]
    check("属性面板新增「顶点」页（4 控制点说明）", "顶点" in nav_titles,
          str(nav_titles))

    # 拖放创建 + 控制点手柄渲染（scene.render 不含 view 的标尺 / 锁定标记）
    before_drop = set(i.item_id for i in scene.all_items())
    window._spawn("bezier", (2400.0, 2400.0))
    app.processEvents()
    dropped = [i for i in scene.all_items() if i.item_id not in before_drop]
    check("工具箱拖放也能放置贝塞尔曲线",
          len(dropped) == 1 and dropped[0].TYPE == "bezier")
    bz_item = dropped[0]
    rect_for_bool = scene.create_item("rect", center=(2600.0, 2400.0),
                                      size=(200.0, 120.0))
    scene.clearSelection()
    bz_item.setSelected(True)
    rect_for_bool.setSelected(True)
    app.processEvents()
    check("贝塞尔是开放曲线，不参与布尔面域运算",
          all(it.TYPE != "bezier" for it in scene.boolean_items()))

    def _render_bz():
        img = QImage(320, 260, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.white)
        pt = QPainter(img)
        src = QRectF(bz_item.sceneBoundingRect()).adjusted(-25, -25, 25, 25)
        scene.render(pt, QRectF(0, 0, 320, 260), src, Qt.KeepAspectRatio)
        pt.end()
        return img

    def _handle_px(img):
        return sum(1 for y in range(img.height()) for x in range(img.width())
                   if img.pixelColor(x, y).getRgb()[:3] == (22, 119, 255))

    scene.clearSelection()
    app.processEvents()
    px_off = _handle_px(_render_bz())
    bz_item.setSelected(True)
    app.processEvents()
    px_on = _handle_px(_render_bz())
    check("选中后画出蓝色控制点与手柄线", px_on > px_off and px_on > 0,
          f"off={px_off} on={px_on}")
    run_bz = scene.is_run_mode
    scene.is_run_mode = True
    px_run = _handle_px(_render_bz())
    check("运行态不画控制点手柄", px_run == px_off,
          f"off={px_off} run={px_run}")
    scene.is_run_mode = run_bz
    scene.clearSelection()
    scene.delete_items([bz_item, rect_for_bool] + drawn)
    app.processEvents()

    print("\n=== 9. 关窗不重写页面文件 ===")
    page_hash = digest(TMP_PAGE)

    window.show()
    app.processEvents()
    visible = window.view.mapToScene(window.view.viewport().rect()).boundingRect()
    fit = scene.fit_rect(0.0)
    check("首次 fit 在 show 后按真实 viewport 计算",
          visible.width() < fit.width() * 4 and visible.height() < fit.height() * 4,
          f"visible={visible.width():.0f}×{visible.height():.0f} "
          f"fit={fit.width():.0f}×{fit.height():.0f}")
    window._do("fit_saved")
    check("恢复保存视图可调用",
          window.view.transform().m11() > 0)
    window._do("fit")
    if args.shot:
        os.makedirs(os.path.dirname(os.path.abspath(args.shot)), exist_ok=True)
        window.grab().save(args.shot)
        print(f"  截图已保存: {args.shot}")
    # 保存过但之后又做了编辑？先清脏，模拟「用户选择放弃」
    scene.mark_saved()
    window.close()
    app.processEvents()
    check("设计器关窗未改写源页面", digest(TMP_PAGE) == page_hash)
    check("原始 page_1.json 全程零改动", digest(SOURCE_PAGE) == source_hash)

    for path in (TMP_PAGE, TMP_SAVED):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError as exc:
                # 运行环境可能把 os.remove 接管成回收站操作并失败；临时文件
                # 由 make_small_page() 每次重建，清理失败不影响回归判定，
                # 更不能让它盖掉下面的「失败 N 项」结果输出。
                print(f"  [warn] 临时文件清理失败（不影响断言）: {exc}")
    # 断开场景信号，避免解释器退出时 C++ 对象已销毁仍触发回调的噪声
    try:
        scene.selectionChanged.disconnect()
    except Exception:
        pass
    print(f"\n失败 {len(FAILURES)} 项" +
          (": " + ", ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
