"""字体属性专项门禁（CoreQGraphics）。

口径：

* **文本图元**的字体族存 ``style.font_family``，缺字段时取 ``Arial``
  （旧 Core ``text_element`` 恒用 Arial），因此存量 page 零改动；
  换字体后文字宽高变化，边框 / 背景由 ``TextItem`` 按新字体重算。
* **widget 图元**的字体族存顶层 ``widgetFontFamily``，空串 = 跟随应用默认字体
  （旧 Core 那 5 个字段的行为），旧记录缺这个键时只在读取侧兜底、不回写。

覆盖：

1. ``Style`` / ``text_metrics`` 的字体族解析与透传（含空白兜底）；
2. ``TextItem.paint`` 真的按 ``style.font_family`` 取字体；
3. 改字体族触发边框重算（改颜色不触发，避免无谓几何改动）；
4. 字体族写回 page JSON，未编辑的图元不多出 ``font_family`` 键；
5. widget 样式表 / 设计态占位字体 / 运行预览真实控件的字体族；
6. 老 widget 记录 round-trip 零改动；
7. 属性面板：文本「文本内容」页 +「外观」页两个字体下拉跨页同步、
   widget「控件」页字体下拉写顶层字段且不污染 ``style``；
8. 字体下拉剔除 GDI 位图字体（Terminal / Fixedsys / System 这类），
   不再给它们设 ``Qt.FontRole`` 预览——那是
   ``DirectWrite: CreateFontFaceFromHDC() failed`` 告警的来源。

用法：
``.venv/Scripts/python.exe tools/verify_core_qgraphics_font.py``
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

import Designer.CoreQGraphics.g_elements as ge  # noqa: E402
import Designer.CoreQGraphics.g_style as gs  # noqa: E402
from Designer.CoreQGraphics.g_scene import GraphicsScene  # noqa: E402
from Designer.CoreQGraphics.g_style import (  # noqa: E402
    FONT_FAMILY_DEFAULT, Style, font_for, normalize_font_family, text_metrics,
)
from Designer.CoreQGraphics.g_widgets import (  # noqa: E402
    WIDGET_DEFAULTS, _widget_font, widget_font_family, widget_style_sheet,
)

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILURES.append(name)
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def page_by_key(panel, key: str):
    for i in range(panel.stack.count()):
        widget = panel.stack.widget(i)
        if widget.objectName() == key:
            return widget
    return None


app = QApplication.instance() or QApplication([])

# 系统字体库在不同平台上差异很大（离屏平台甚至一个字体都没有），
# 所以机制类断言一律用「任意字符串 + 打桩」验证，不依赖字体是否安装。
FAMILY_A = "字体甲"
FAMILY_B = "字体乙"

print("=== 1. Style / text_metrics 的字体族解析 ===")
check("缺 font_family 时取默认 Arial",
      Style.from_dict({}).font_family == FONT_FAMILY_DEFAULT
      == "Arial", Style.from_dict({}).font_family)
check("显式 font_family 原样解析",
      Style.from_dict({"font_family": "SimSun"}).font_family == "SimSun")
check("空白 font_family 回退默认",
      normalize_font_family("   ") == "Arial"
      and normalize_font_family(None) == "Arial"
      and Style.from_dict({"font_family": "  "}).font_family == "Arial")
check("font_for 保留字体族（QFont.family 可读回）",
      font_for(FAMILY_A, 20, True).family() == FAMILY_A,
      font_for(FAMILY_A, 20, True).family())

captured: list[tuple] = []
_real_font_for = gs.font_for


def _spy_font_for(family, size, bold=False):
    captured.append((family, float(size), bool(bold)))
    return _real_font_for(family, size, bold)


gs.font_for = _spy_font_for
try:
    text_metrics("abc", 24, FAMILY_B)
    metrics_family = captured[-1][0] if captured else None
finally:
    gs.font_for = _real_font_for
check("text_metrics 把字体族透传给 font_for",
      metrics_family == FAMILY_B, str(captured[-1] if captured else None))

print("\n=== 2. 文本图元：paint 用 style.font_family ===")
scene = GraphicsScene()
text = scene.create_item("text", center=(1200.0, 800.0),
                         context="Hello 字体")
check("新建文本图元 style 里没有 font_family 键（存量口径）",
      "font_family" not in (text.page_record().get("style") or {}),
      str(text.page_record().get("style")))
check("未设置时读出来就是默认 Arial",
      text._style.font_family == "Arial")

text.set_style_value("font_family", FAMILY_A)
paint_calls: list[tuple] = []
_real_elem_font_for = ge.font_for


def _spy_elem_font_for(family, size, bold=False):
    paint_calls.append((family, float(size), bool(bold)))
    return _real_elem_font_for(family, size, bold)


img = QImage(400, 200, QImage.Format_ARGB32)
img.fill(0)
ge.font_for = _spy_elem_font_for
try:
    painter = QPainter(img)
    text.paint(painter, None)
    painter.end()
finally:
    ge.font_for = _real_elem_font_for
check("TextItem.paint 按 style.font_family 取字体",
      bool(paint_calls) and paint_calls[0][0] == FAMILY_A, str(paint_calls[:1]))
check("文本仍是粗体（与旧 Core text_element 一致）",
      bool(paint_calls) and paint_calls[0][2] is True)

print("\n=== 3. 换字体触发边框重算；改颜色不触发 ===")
metric_calls: list[tuple] = []
_real_text_metrics = ge.text_metrics


def _spy_text_metrics(text_value, font_size, font_family=FONT_FAMILY_DEFAULT):
    metric_calls.append((text_value, float(font_size), font_family))
    return _real_text_metrics(text_value, font_size, font_family)


ge.text_metrics = _spy_text_metrics
try:
    text.set_style_value("font_family", FAMILY_B)
    after_family = list(metric_calls)
    metric_calls.clear()
    text.set_style_value("stroke", "#ff0000")
    after_color = list(metric_calls)
    metric_calls.clear()
    text.set_style_value("font_family", FAMILY_B)     # 同值不该再次重算
    after_same = list(metric_calls)
finally:
    ge.text_metrics = _real_text_metrics
check("改字体族按新字体重新量文字",
      bool(after_family) and after_family[-1][2] == FAMILY_B,
      str(after_family[-1] if after_family else None))
check("改描边色不重算文字边框", not after_color, str(len(after_color)))
check("字体族同值不重复重算", not after_same, str(len(after_same)))

print("\n=== 4. 字体族写回 page JSON ===")
rec = text.to_page_record()
check("to_page_record 的 style 带 font_family",
      rec["style"].get("font_family") == FAMILY_B,
      str(rec["style"].get("font_family")))
check("样式里其它字段没有被顺手改写",
      rec["style"].get("stroke") == "#ff0000"
      and rec["style"].get("font_size") == text.style_value("font_size"))
fresh = scene.create_item("text", center=(1800.0, 800.0),
                          context="未编辑")
check("未编辑的文本图元记录里没有 font_family",
      "font_family" not in (fresh.to_page_record().get("style") or {}))

print("\n=== 5. widget：样式表 / 设计态占位字体 ===")
check("widgetFontFamily 默认空串（跟随应用默认字体）",
      WIDGET_DEFAULTS["widgetFontFamily"] == "")
check("未设置字体时样式表不含 font-family",
      "font-family" not in widget_style_sheet({"widgetType": "label"}),
      widget_style_sheet({"widgetType": "label"}))
styled = widget_style_sheet(
    {"widgetType": "label", "widgetFontFamily": FAMILY_A})
check("设置字体后样式表带 font-family",
      f'font-family: "{FAMILY_A}";' in styled, styled)
check("widget_font_family 读出字体族",
      widget_font_family({"widgetFontFamily": FAMILY_A}) == FAMILY_A)
check("设计态占位字体跟随 widgetFontFamily",
      _widget_font({"widgetFontFamily": FAMILY_A}).family() == FAMILY_A
      and _widget_font({}).family() == QFont().family(),
      _widget_font({"widgetFontFamily": FAMILY_A}).family())

print("\n=== 6. widget 运行预览：真实控件的字体族 ===")
wg = scene.create_item("widget:label", center=(2600.0, 800.0),
                       widgetText="标签", widgetFontFamily=FAMILY_A)
scene.set_scene_mode(True)
proxy = scene.widget_proxies.get(wg.item_id)
control = proxy.widget() if proxy is not None else None
check("运行预览控件样式表带字体族",
      control is not None and f'font-family: "{FAMILY_A}"' in control.styleSheet(),
      control.styleSheet() if control is not None else "无控件")
old_control = control
wg.set_page_field("widgetFontFamily", FAMILY_B)
scene.notify_edit(wg)
new_control = proxy.widget() if proxy is not None else None
check("改字体后运行预览控件按新样式重建",
      new_control is not None and new_control is not old_control
      and f'font-family: "{FAMILY_B}"' in new_control.styleSheet(),
      "重建" if new_control is not old_control else "未重建")
scene.set_scene_mode(False)
check("退出运行预览销毁 proxy", not scene.widget_proxies)

print("\n=== 7. 老 widget 记录 round-trip 零改动 ===")
from Designer.CoreQGraphics.g_elements import WidgetItem  # noqa: E402

legacy = {
    "id": 9101, "name": "老标签", "type": "widget", "parent_id": 0,
    "children_ids": [], "group_id": 0,
    "center_pos": {"x": 2069.476, "y": 8631.525},
    "origin_pos": {"x": 2069.476, "y": 8631.525},
    "width": 388.0, "height": 1824.0, "rotate": 7.0,
    "style": {"stroke": "#000000", "strokeWidth": 2, "fill": False,
              "fill_color": "#00ff00", "opacity": 255, "cornerRadius": 0.0},
    "zValue": 0.0, "widgetText": "缓存料架监控", "widgetType": "label",
    "widgetFontSize": 57, "widgetColor": "#000000",
    "widgetBackground": "#e1f59b",
}
old_widget = WidgetItem(legacy, scene.projection)
check("缺 widgetFontFamily 的老记录回写逐字不变",
      old_widget.to_page_record() == legacy)

print("\n=== 8. 属性面板：字体下拉 ===")
from Designer.CoreQGraphics.ui.property_panel import PropertyPanel  # noqa: E402

panel = PropertyPanel()
panel.set_scene(scene)
text2 = scene.create_item("text", center=(3200.0, 800.0),
                          context="面板字体")
panel.update_for_selected(text2)
app.processEvents()

ctx_page = page_by_key(panel, "context")
ctx_combo = ctx_page.findChild(QComboBox, "propFontFamily") if ctx_page else None
check("「文本内容」页有字体下拉", ctx_combo is not None)
check("字体下拉当前值是默认 Arial",
      ctx_combo is not None and ctx_combo.currentData() == "Arial",
      str(ctx_combo.currentData() if ctx_combo else None))
app_page = page_by_key(panel, "appearance")
app_combo = app_page.findChild(QComboBox, "propFontFamily") if app_page else None
check("「外观」页也有字体下拉（与旧字号同样双入口）", app_combo is not None)

if ctx_combo is not None:
    # 离屏平台字体库为空，这里补一项假字体来走完整的写回链路
    ctx_combo.addItem(FAMILY_A, FAMILY_A)
    ctx_combo.setCurrentIndex(ctx_combo.findData(FAMILY_A))
    app.processEvents()
    check("选字体写回 style.font_family",
          text2.style_value("font_family") == FAMILY_A,
          str(text2.style_value("font_family")))
    check("另一个页面的字体下拉同步",
          app_combo is not None and app_combo.currentData() == FAMILY_A,
          str(app_combo.currentData() if app_combo else None))
    check("写回后 to_page_record 带字体族",
          text2.to_page_record()["style"].get("font_family") == FAMILY_A)

wg2 = scene.create_item("widget:pushbutton", center=(3800.0, 800.0))
panel.update_for_selected(wg2)
app.processEvents()
w_page = page_by_key(panel, "widget")
w_combo = w_page.findChild(QComboBox, "propFontFamily") if w_page else None
check("「控件」页有字体下拉", w_combo is not None)
check("控件字体下拉默认是「（默认字体）」空值",
      w_combo is not None and w_combo.currentData() == "",
      str(w_combo.currentData() if w_combo else None))
if w_combo is not None:
    w_combo.addItem(FAMILY_B, FAMILY_B)
    w_combo.setCurrentIndex(w_combo.findData(FAMILY_B))
    app.processEvents()
    check("控件选字体写回顶层 widgetFontFamily",
          wg2.page_record().get("widgetFontFamily") == FAMILY_B,
          str(wg2.page_record().get("widgetFontFamily")))
    check("控件选字体不污染 style.font_family",
          "font_family" not in (wg2.page_record().get("style") or {}))
    check("控件字体同步进真实控件样式表",
          f'font-family: "{FAMILY_B}"' in widget_style_sheet(wg2.page_record()))
check("变体下拉仍在且带独立 objectName（字体下拉不抢占它）",
      w_page is not None
      and w_page.findChild(QComboBox, "widgetVariant") is not None)

print("\n=== 9. 字体下拉剔除 GDI 位图字体（DirectWrite 告警源）===")
RASTER_FAMILIES = ["Courier", "Fixedsys", "Modern", "MS Sans Serif", "MS Serif",
                   "Roman", "Script", "Small Fonts", "System", "Terminal"]
check("filter_usable_families 剔除不可平滑缩放的族",
      gs.filter_usable_families(
          ["Arial", "Terminal", "SimSun", "Fixedsys"],
          lambda f: f not in RASTER_FAMILIES) == ["Arial", "SimSun"])
check("全部不可缩放时回退原列表（不给空下拉）",
      gs.filter_usable_families(["Terminal"], lambda f: False) == ["Terminal"])
check("空白族名被丢弃",
      gs.filter_usable_families(["", "   ", "Arial"], lambda f: True) == ["Arial"]
      and gs.filter_usable_families([], lambda f: True) == [])

import Designer.CoreQGraphics.ui.property_panel as pp  # noqa: E402

raster_text = scene.create_item("text", center=(4400.0, 800.0),
                                context="位图字体")
raster_text.set_style_value("font_family", "Terminal")
_real_avail = pp.available_font_families
_real_scalable = pp.is_scalable_font_family
# 离屏平台的字体库是空的（一个族都没有），这里打桩模拟「真机有一堆字体、
# 其中既有可缩放也有位图」，才能覆盖下拉的取舍逻辑。
pp.available_font_families = lambda refresh=False: ["Arial", "SimSun"]
pp.is_scalable_font_family = lambda family: family in ("Arial", "SimSun")
try:
    panel.update_for_selected(raster_text)
    app.processEvents()
    r_page = page_by_key(panel, "context")
    r_combo = r_page.findChild(QComboBox, "propFontFamily") if r_page else None
    check("存量位图字体仍插到最前（不把真实值悄悄换掉）",
          r_combo is not None
          and r_combo.itemText(0) == "Terminal"
          and r_combo.currentData() == "Terminal",
          str([r_combo.itemText(i) for i in range(r_combo.count())]
              if r_combo else None))
    check("位图字体项不设预览字体（不再触发 DirectWrite 解析）",
          r_combo is not None and r_combo.itemData(0, Qt.FontRole) is None)
    arial_index = r_combo.findData("Arial") if r_combo else -1
    check("可缩放字体项仍带预览字体（所见即所得不丢）",
          isinstance(r_combo.itemData(arial_index, Qt.FontRole), QFont)
          if r_combo is not None and arial_index >= 0 else False)
finally:
    pp.available_font_families = _real_avail
    pp.is_scalable_font_family = _real_scalable

raw_families = list(QFontDatabase.families())
usable_families = gs.available_font_families(refresh=True)
if raw_families:
    leftovers = [f for f in usable_families if not gs.is_scalable_font_family(f)]
    check("真实字体库里位图字体已被剔除", not leftovers, str(leftovers))
    check("候选族是系统字体子集且非空",
          bool(usable_families) and set(usable_families) <= set(raw_families),
          f"{len(usable_families)}/{len(raw_families)}")
    print(f"  [INFO] 系统字体 {len(raw_families)} 个 / 下拉可用 "
          f"{len(usable_families)} 个 / 剔除位图字体 "
          f"{len(raw_families) - len(usable_families)} 个")
else:
    print("  [NOTE] 离屏 QPA 字体库为空，真实字体库的过滤断言留给实机验证")

print()
if FAILURES:
    print(f"FAILED {len(FAILURES)} 项：")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
print("ALL PASS：文本图元 / widget 字体属性与属性面板全链路通过")
