"""CoreQGraphics 基本图元布尔与单图元模板回归。

    .venv/Scripts/python.exe tools/verify_core_qgraphics_boolean.py

只写 build/ 下的临时模板，不改真实页面或共享模板库。
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu  # noqa: E402

from Designer.CoreQGraphics.g_boolean import (  # noqa: E402
    BOOL_INTERSECT, BOOL_SUBTRACT, BOOL_UNION, BOOL_XOR,
    item_scene_path, record_page_path,
)
from Designer.CoreQGraphics.g_path import PATH_SEGMENTS_KEY  # noqa: E402
from Designer.CoreQGraphics.g_scene import GraphicsScene  # noqa: E402
from Designer.CoreQGraphics.ui import DesignerWindow  # noqa: E402
from Designer.CoreQGraphics.ui.template_store import TemplateStore  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILURES.append(name)
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def overlapping_scene(operation: str):
    scene = GraphicsScene()
    first = scene.create_item("rect", (0, 0), (200, 200))
    second = scene.create_item("rect", (100, 0), (200, 200))
    scene.select_items([first, second])
    result = scene.apply_boolean(operation)
    return scene, first, second, result


def contains(record: dict, x: float, y: float) -> bool:
    return record_page_path(record).contains(QPointF(x, y))


def curve_count(record: dict) -> int:
    return sum(segment.get("kind") == "curve"
               for segment in record.get(PATH_SEGMENTS_KEY) or ())


def main() -> int:
    app = QApplication.instance() or QApplication([])  # noqa: F841

    print("=== 1. 四种布尔运算与替换语义 ===")
    expectations = {
        BOOL_UNION: ((-50, 0), (150, 0), (50, 0)),
        BOOL_INTERSECT: ((50, 0), (-50, 0), (150, 0)),
        BOOL_SUBTRACT: ((-50, 0), (50, 0), (150, 0)),
        BOOL_XOR: ((-50, 0), (50, 0), (150, 0)),
    }
    for operation, points in expectations.items():
        scene, first, second, result = overlapping_scene(operation)
        record = result.to_page_record()
        check(f"{operation} 结果替换两个源图元",
              len(scene.all_items()) == 1 and result.TYPE == "path"
              and scene.selected_items() == [result])
        if operation == BOOL_UNION:
            ok = all(contains(record, *point) for point in points)
        elif operation == BOOL_INTERSECT:
            ok = (contains(record, *points[0])
                  and not contains(record, *points[1])
                  and not contains(record, *points[2]))
        elif operation == BOOL_SUBTRACT:
            ok = (contains(record, *points[0])
                  and not contains(record, *points[1])
                  and not contains(record, *points[2]))
        else:
            ok = (contains(record, *points[0])
                  and not contains(record, *points[1])
                  and contains(record, *points[2]))
        check(f"{operation} 面域包含关系正确", ok)
        check(f"{operation} 写精确段与旧版折线双格式",
              bool(record.get(PATH_SEGMENTS_KEY)) and bool(record.get("vertices")))
        check(f"{operation} 继承首个图元样式",
              record.get("style") == first.to_page_record().get("style"))

    print("\n=== 2. 空结果原子性 / 类型门控 ===")
    scene = GraphicsScene()
    a = scene.create_item("rect", (0, 0), (100, 100))
    b = scene.create_item("rect", (1000, 0), (100, 100))
    scene.select_items([a, b])
    before = [it.item_id for it in scene.all_items()]
    next_id_before = scene.index._next_id
    try:
        scene.apply_boolean(BOOL_INTERSECT)
    except ValueError as exc:
        check("空交集抛出明确错误", "结果为空" in str(exc), str(exc))
    else:
        check("空交集抛出明确错误", False)
    check("空结果不删源图元", [it.item_id for it in scene.all_items()] == before)
    check("空结果不消耗新图元 id", scene.index._next_id == next_id_before)
    line = scene.create_item("line", (0, 500), (100, 100))
    text = scene.create_item("text", (500, 500))
    scene.select_items([a, line, text])
    check("线与文本不参与面域布尔", scene.boolean_items() == [a])
    try:
        scene.apply_boolean(BOOL_UNION)
    except ValueError:
        check("有效图元不足时拒绝操作", True)
    else:
        check("有效图元不足时拒绝操作", False)

    print("\n=== 3. 曲线 / 孔洞 / 保存重载 ===")
    scene = GraphicsScene()
    outer = scene.create_item("rect", (0, 0), (400, 400))
    inner = scene.create_item("circle", (0, 0), (120, 120))
    scene.select_items([outer, inner])
    ring = scene.apply_boolean(BOOL_SUBTRACT)
    ring_record = ring.to_page_record()
    check("圆参与差集保留贝塞尔曲线", curve_count(ring_record) > 0,
          f"curves={curve_count(ring_record)}")
    check("外框减内圆形成真实孔洞",
          contains(ring_record, 150, 0) and not contains(ring_record, 0, 0))
    check("孔洞是多子路径而非填回外框",
          sum(segment.get("kind") == "move"
              for segment in ring_record[PATH_SEGMENTS_KEY]) >= 2)
    snapshot = scene.page_data()
    scene.load_data(snapshot)
    loaded = scene.all_items()[0]
    loaded_record = loaded.to_page_record()
    check("页面 round-trip 后孔洞仍在",
          contains(loaded_record, 150, 0) and not contains(loaded_record, 0, 0))
    check("页面 round-trip 后曲线仍在", curve_count(loaded_record) > 0)

    print("\n=== 4. 结果继续旋转 / 缩放 / 平移 / 再次布尔 ===")
    loaded.set_page_angle(30.0)
    rotated = loaded.to_page_record()
    check("旋转不丢精确曲线", curve_count(rotated) > 0
          and abs(rotated.get("rotate", 0.0) - 30.0) < 1e-9)
    loaded.set_page_size(500.0, 300.0)
    w, h = loaded.page_size()
    check("非等比缩放精确曲线", abs(w - 500.0) < 0.01 and abs(h - 300.0) < 0.01,
          f"size=({w:.3f}, {h:.3f})")
    old_center = loaded.page_center()
    loaded.set_page_center(old_center[0] + 700.0, old_center[1] - 200.0)
    moved = loaded.to_page_record()
    check("平移同时写回曲线控制点",
          abs(moved["center_pos"]["x"] - (old_center[0] + 700.0)) < 0.01
          and abs(moved["center_pos"]["y"] - (old_center[1] - 200.0)) < 0.01
          and curve_count(moved) > 0)
    cutter = scene.create_item("rect", loaded.page_center(), (100.0, 500.0))
    scene.select_items([loaded, cutter])
    recut = scene.apply_boolean(BOOL_SUBTRACT)
    check("布尔结果可继续参与下一轮布尔", recut.TYPE == "path"
          and len(scene.all_items()) == 1)

    print("\n=== 4b. 非对称路径的旋转 / 重载 / 未保存直接缩放 ===")
    for custom_pivot in (False, True):
        asymmetric_scene = GraphicsScene()
        triangle = asymmetric_scene.create_item("triangle", (0, 0), (200, 200))
        patch = asymmetric_scene.create_item("rect", (20, 0), (40, 40))
        asymmetric_scene.select_items([triangle, patch])
        asymmetric = asymmetric_scene.apply_boolean(BOOL_UNION)
        if custom_pivot:
            asymmetric.set_page_origin(15.0, 20.0)
        asymmetric.set_page_angle(30.0)
        saved = asymmetric_scene.page_data()
        saved_record = saved["items"][0]
        expected_center = saved_record["center_pos"]
        expected_origin = saved_record["origin_pos"]
        expected_bounds = asymmetric.sceneBoundingRect()
        asymmetric_scene.load_data(saved)
        reloaded = asymmetric_scene.all_items()[0]
        reread = reloaded.to_page_record()
        check(f"非对称路径重载不改中心（custom={custom_pivot}）",
              abs(reread["center_pos"]["x"] - expected_center["x"]) < 0.002
              and abs(reread["center_pos"]["y"] - expected_center["y"]) < 0.002,
              f'{reread["center_pos"]} vs {expected_center}')
        check(f"非对称路径重载不改支点（custom={custom_pivot}）",
              abs(reread["origin_pos"]["x"] - expected_origin["x"]) < 0.002
              and abs(reread["origin_pos"]["y"] - expected_origin["y"]) < 0.002)
        bounds = reloaded.sceneBoundingRect()
        check(f"非对称路径重载不改几何（custom={custom_pivot}）",
              abs(bounds.center().x() - expected_bounds.center().x()) < 0.01
              and abs(bounds.center().y() - expected_bounds.center().y()) < 0.01
              and abs(bounds.width() - expected_bounds.width()) < 0.01
              and abs(bounds.height() - expected_bounds.height()) < 0.01)

    unbaked_scene = GraphicsScene()
    triangle = unbaked_scene.create_item("triangle", (0, 0), (200, 200))
    patch = unbaked_scene.create_item("rect", (20, 0), (40, 40))
    unbaked_scene.select_items([triangle, patch])
    unbaked = unbaked_scene.apply_boolean(BOOL_UNION)
    unbaked.set_page_angle(30.0)  # 故意不调用 to_page_record()
    unbaked_scene.resize_item_about(unbaked, (0.0, 0.0), 1.5, 0.75)
    unbaked_record = unbaked.to_page_record()
    check("旋转后未保存直接缩放仍保留角度", abs(unbaked_record["rotate"] - 30.0) < 1e-9,
          f'rotate={unbaked_record["rotate"]}')
    unbaked.set_page_angle(60.0)
    check("缩放后再次设绝对角度基准正确",
          abs(unbaked.to_page_record()["rotate"] - 60.0) < 1e-9)

    print("\n=== 5. 单图元模板持久化与实例化 ===")
    with tempfile.TemporaryDirectory(prefix="_verify_boolean_", dir="build") as directory:
        # 独立的完整圆孔结果：Qt 对「曲线被直线切开」可能合法输出折线，
        # 模板测试必须使用确实含曲线控制点的输入。
        template_scene = GraphicsScene()
        template_outer = template_scene.create_item("rect", (0, 0), (400, 400))
        template_inner = template_scene.create_item("circle", (0, 0), (120, 120))
        template_scene.select_items([template_outer, template_inner])
        template_result = template_scene.apply_boolean(BOOL_SUBTRACT)
        store = TemplateStore(directory)
        template = store.add_from_item(template_scene, template_result, "布尔环模板")
        check("单图元模板写入磁盘", template.node_count == 1
              and os.path.isfile(store.path))
        template_record = template.items[0]
        check("模板几何归一到根中心原点",
              abs(template_record["center_pos"]["x"]) < 1e-9
              and abs(template_record["center_pos"]["y"]) < 1e-9)
        check("模板同时保留精确曲线控制点", curve_count(template_record) > 0)
        reloaded_store = TemplateStore(directory)
        restored = reloaded_store.get(template.id)
        check("模板库重载后仍可读取", restored is not None
              and restored.name == "布尔环模板")
        target = QPointF(1200.0, -800.0)
        copy_item = template_scene.instantiate_template(restored, target)
        copy_record = copy_item.to_page_record()
        check("模板实例化为独立新 id",
              copy_item.item_id != template_result.item_id and copy_item.TYPE == "path")
        check("模板实例化落点精确",
              abs(copy_item.page_center()[0] - target.x()) < 0.01
              and abs(copy_item.page_center()[1] - target.y()) < 0.01)
        check("模板实例化保留曲线", curve_count(copy_record) > 0)
        check("模板实例化不修改模板源数据",
              restored.items[0] == reloaded_store.get(template.id).items[0])
        line = template_scene.create_item("line", (100.0, 200.0), (200.0, 100.0))
        line_template = store.add_from_item(template_scene, line, "直线模板")
        line_copy = template_scene.instantiate_template(
            line_template, QPointF(500.0, 600.0))
        check("无 center_pos 的直线也可存为单图元模板",
              abs(line_copy.page_center()[0] - 500.0) < 0.01
              and abs(line_copy.page_center()[1] - 600.0) < 0.01)

        print("\n=== 6. 真实主窗口命令 / 右键菜单 / 撤销重做 ===")
        window = DesignerWindow(template_dir=directory)
        first = window.scene.create_item("rect", (0, 0), (200, 200))
        second = window.scene.create_item("circle", (100, 0), (200, 200))
        # 场景 API 不自动记历史；真实绘制 / 拖放由主窗口提交。这里对齐到
        # 「两个源图元」这一初始状态，再检查布尔只增加一个撤销步。
        window.history.reset()
        window.scene.select_items([first, second])
        app.processEvents()
        check("多选闭合图元启用四个布尔动作",
              all(window.actions[f"boolean_{op}"].isEnabled()
                  for op in (BOOL_UNION, BOOL_INTERSECT, BOOL_SUBTRACT, BOOL_XOR)))
        menu = window.view.build_context_menu()
        boolean_menus = [child for child in menu.findChildren(QMenu)
                         if child.title() == "布尔运算"]
        check("画布右键出现布尔子菜单", len(boolean_menus) == 1)
        boolean_actions = ([sub_action for sub_action in boolean_menus[0].actions()]
                           if boolean_menus else [])
        if boolean_actions:
            boolean_actions[0].trigger()
        else:
            window._do("boolean_union")
        check("菜单命令生成并选中一个路径",
              len(window.scene.all_items()) == 1
              and window.scene.selected_items()[0].TYPE == "path")
        check("结果可直接保存为模板",
              window.actions["save_template"].isEnabled())
        check("布尔操作只产生一个撤销步", window.history.can_undo())
        window._do("undo")
        check("撤销恢复两个源图元", len(window.scene.all_items()) == 2)
        window._do("redo")
        check("重做恢复布尔结果", len(window.scene.all_items()) == 1
              and window.scene.all_items()[0].TYPE == "path")
        original_get_text = QInputDialog.getText
        try:
            QInputDialog.getText = staticmethod(
                lambda *args, **kwargs: ("菜单独布尔模板", True))
            window._do("save_template")
        finally:
            QInputDialog.getText = original_get_text
        saved_templates = [t for t in window.template_store.templates
                           if t.name == "菜单独布尔模板"]
        check("主窗口保存动作写入模板库并刷新工具箱", len(saved_templates) == 1
              and any(b.template.name == "菜单独布尔模板"
                      for b in window.toolbox._template_buttons))
        if saved_templates:
            window.add_template_at_view_center(saved_templates[0].id)
            check("点击工具箱模板可再次实例化", len(window.scene.all_items()) == 2
                  and sum(it.TYPE == "path" for it in window.scene.all_items()) == 2)
        window.scene.mark_saved()
        window.close()

    print(f"\n失败 {len(FAILURES)} 项" + (f": {FAILURES}" if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
