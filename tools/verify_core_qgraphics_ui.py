"""CoreQGraphics UI 外壳离屏回归。

    .venv/Scripts/python.exe tools/verify_core_qgraphics_ui.py

覆盖：主窗口装配 / 12 类属性页分派 / 属性编辑精确回写 / 创建与删除 /
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
    check("工具箱 11 类 + 7 种 widget 变体按钮",
          len(window.toolbox.buttons) == 18,
          f"buttons={len(window.toolbox.buttons)}")
    variant_buttons = [b.key for b in window.toolbox.buttons
                       if b.key.startswith("widget:")]
    check("工具箱含 7 种 widget 变体", len(variant_buttons) == 7,
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
    check("11 类全部可创建", all(v is not None for v in made.values()),
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

    print("\n=== 8.13 右键指定旋转中心 ===")
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
    QTest.mousePress(view.viewport(), Qt.RightButton, Qt.NoModifier, hp)
    QTest.mouseRelease(view.viewport(), Qt.RightButton, Qt.NoModifier, hp)
    app.processEvents()
    ctx = window.view.context_page_point()
    px_tol = 4.0 / max(scene.projection.kx, 1e-9)
    check("右键位置已换算成 page 坐标",
          ctx is not None and abs(ctx.x() - 900.0) < px_tol
          and abs(ctx.y() - 800.0) < px_tol, str(ctx))
    menu_labels = [a.text() for a in window.view.build_context_menu().actions() if a.text()]
    check("右键菜单含「旋转中心设到此处」", "旋转中心设到此处" in menu_labels,
          str(menu_labels[:4]))
    window._do("origin_here")
    app.processEvents()
    check("旋转中心落到右键位置",
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

    def _is_amber(c) -> bool:
        """光标旁的捕捉标记是橙色，与选中红点 (214,51,46) / 支点蓝要区分得开。"""
        return c.red() > 200 and 90 < c.green() < 195 and c.blue() < 90

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
          _scan(_shot(), vp_grid.x(), vp_grid.y(), 10, _is_amber),
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
    want = (tgx - hover.x(), tgy - hover.y())
    check("按下 T 立即吸附到最近捕捉点",
          view.snap.enabled and abs(mv.x() - want[0]) < 1e-6
          and abs(mv.y() - want[1]) < 1e-6,
          f"moved=({mv.x():.3f},{mv.y():.3f}) want=({want[0]:.3f},{want[1]:.3f})")

    before2 = QPointF(far.scenePos())
    QTest.keyClick(view, Qt.Key_T)     # 关
    QTest.keyClick(view, Qt.Key_T)     # 再开
    app.processEvents()
    mv2 = far.scenePos() - before2
    check("重复开关 T 不会重复推图元",
          abs(mv2.x()) < 1e-6 and abs(mv2.y()) < 1e-6,
          f"moved=({mv2.x():.3f},{mv2.y():.3f})")
    view.snap.enabled = False

    # ---- 多选按 T 吸附：位移 = 光标偏移，整体同量平移（左键拖动已取消）----
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
    snap_extra = (0.0, 0.0) if marker2 is None else (
        marker2.x() - hover2.x(), marker2.y() - hover2.y())
    check("多选按 T 吸附：位移 = 光标到捕捉点的偏移",
          marker2 is not None
          and abs(offsets[far.item_id].x() - snap_extra[0]) < 1e-6
          and abs(offsets[far.item_id].y() - snap_extra[1]) < 1e-6,
          f"item=({offsets[far.item_id].x():.3f},{offsets[far.item_id].y():.3f}) "
          f"snap=({snap_extra[0]:.3f},{snap_extra[1]:.3f})")
    check("多选图元同步平移（保持相对位置）", same,
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
    check("按 T 吸附到那个最近捕捉点（鼠标吸多少图元走多少）",
          abs(moved.x() - want.x()) < 1e-6 and abs(moved.y() - want.y()) < 1e-6,
          f"moved=({moved.x():.3f},{moved.y():.3f}) want=({want.x():.3f},{want.y():.3f})")
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
    from PySide6.QtWidgets import QLabel as _QLabel, QSpinBox as _QSpinBox  # noqa: E402

    wg = scene.create_item("widget:combobox", center=(11200.0, 8600.0))
    scene.clearSelection()
    wg.setSelected(True)
    app.processEvents()
    wpage = _page_by_key("widget")
    check("widget 图元有「控件」页", wpage is not None)
    variants = wpage.findChildren(QComboBox) if wpage else []
    check("控件页提供变体下拉", len(variants) == 1, str(len(variants)))
    if variants:
        check("变体下拉含 7 项且当前为 combobox",
              variants[0].count() == 7
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

    scene.clearSelection()
    scene.delete_items([wg, dropped])
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
            os.remove(path)
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
