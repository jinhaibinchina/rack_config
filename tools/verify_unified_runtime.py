# -*- coding: utf-8 -*-
"""统一运行态模板框架回归门禁。

    .venv/Scripts/python.exe tools/verify_unified_runtime.py

红线
====
1. **几何口径对拍**：``RuntimeElement`` 在 ``rack`` profile 下，1618 个图元的
   ``sceneBoundingRect`` / 四角 / 中心 / head-end 与
   ``App_RackConfig.run.rack_scene_adapter`` 逐项一致；换 profile 后解析式角
   与 AABB 角确实不同（策略生效而不是摆设）。
2. **运行态零污染**：装载、改可见性、挂控件之后 ``page_data()`` 与原始
   page JSON 逐字相等（运行态不写回设计数据）。
3. **承载口径**：框架自建 proxy 的位姿与 ``GraphicsScene._align_widget_proxy``
   同一套公式；外部工厂 / 默认控件 / 核心内置 proxy 三种模式都能拿到控件。
4. **换页不悬空**：门面对象跨 reload 复用、信号连接保住、消失的 id 标
   detached，任何 setter 都不碰已析构的 C++ 对象。

离屏运行，不写任何页面文件（换页用内存 ``load_data`` 模拟）。
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QGraphicsItem, QGraphicsSceneMouseEvent, QLabel, QWidget,
)

try:
    _NO_CONTENTS = QGraphicsItem.GraphicsItemFlag.ItemHasNoContents
    _TRANSPARENT_MOUSE = Qt.WidgetAttribute.WA_TransparentForMouseEvents
except AttributeError:  # pragma: no cover
    _NO_CONTENTS = QGraphicsItem.ItemHasNoContents
    _TRANSPARENT_MOUSE = Qt.WA_TransparentForMouseEvents

from Designer.CoreQGraphics.runtime import (  # noqa: E402
    RACK_PROFILE, STRICT_PROFILE, RuntimeElement, RuntimeStage,
)

PAGE = os.path.join("Designer", "Core", "data.json", "datas",
                    "design", "pages", "page_1.json")
FAILURES: list[str] = []
EPS = 1e-6


def check(label, cond, detail=""):
    if cond:
        print(f"  [OK] {label}" + (f"  {detail}" if detail else ""))
    else:
        print(f"  [FAIL] {label}  {detail}")
        FAILURES.append(label)


def same_point(a: QPointF, b: QPointF, tol: float = EPS) -> bool:
    return abs(a.x() - b.x()) <= tol and abs(a.y() - b.y()) <= tol


def same_rect(a, b, tol: float = EPS) -> bool:
    return (abs(a.x() - b.x()) <= tol and abs(a.y() - b.y()) <= tol
            and abs(a.width() - b.width()) <= tol
            and abs(a.height() - b.height()) <= tol)


def main() -> int:
    app = QApplication([])
    with open(PAGE, "r", encoding="utf-8") as f:
        original = json.load(f)

    print("=== 1. 装载 / 索引 / JSON 零污染 ===")
    stage = RuntimeStage(page_path=PAGE, geometry_profile="rack")
    count = stage.load()
    check("加载 1618 图元", count == 1618, f"count={count}")
    check("registry 数量一致", len(stage.registry) == 1618,
          f"len={len(stage.registry)}")
    check("widget 图元被单独识别", len(stage.registry.widgets()) == 2,
          f"widgets={len(stage.registry.widgets())}")
    check("排序按 z + JSON 顺序稳定",
          stage.registry.sorted() == stage.registry.sorted())
    check("page_data 与原始 JSON 完全一致",
          stage.scene.page_data() == original)
    check("默认 widget 控件已挂载", len(stage.controls()) == 2,
          f"controls={len(stage.controls())}")
    check("report 可用", "elements=1618" in stage.report(), stage.report())

    print("\n=== 2. 运行态可见性不写回 page JSON ===")
    group = next((e for e in stage.registry.sorted()
                  if e.TYPE == "group" and e.is_has_child()), None)
    check("找到带子项的组", group is not None,
          f"children={len(group.children()) if group else 0}")
    if group is not None:
        kids = group.children()
        hidden_before = [k.get_visibility() for k in kids]
        eff_before = [k.effective_visibility() for k in kids]
        group.set_visibility(False)
        check("组隐藏后子项有效可见性递归变 False",
              all(not k.effective_visibility() for k in kids),
              f"eff={[k.effective_visibility() for k in kids]}")
        # 与 rack base_element 同语义：组隐藏时子项自身标志同步置 False，
        # 显示时按隐藏前的快照还原（不是「保持不变」）。
        check("组隐藏后子项自身标志同步为 False",
              all(not k.get_visibility() for k in kids))
        group.set_visibility(True)
        check("组显示后按快照还原子项可见性",
              [k.get_visibility() for k in kids] == hidden_before
              and [k.effective_visibility() for k in kids] == eff_before)
        check("可见性操作后 page_data 仍与原始 JSON 一致",
              stage.scene.page_data() == original)
        # 父不可见时点亮子项应被忽略
        group.set_visibility(False)
        kids[0].set_visibility(True)
        check("父隐藏时点亮子项被忽略", kids[0].effective_visibility() is False)
        group.set_visibility(True)

    print("\n=== 3. 与 rack 适配层逐图元几何对拍（1618 项）===")
    from App_RackConfig.run.rack_scene_adapter import RackScene, SceneManager
    rack_scene = RackScene()
    rack_scene.load_page(PAGE)
    rack_mgr = SceneManager(rack_scene)
    check("rack 适配层图元数一致", len(rack_mgr) == 1618,
          f"len={len(rack_mgr)}")
    diffs: list[str] = []
    for iid, adapter in rack_mgr.m_items.items():
        element = stage.registry.find(iid)
        if element is None:
            diffs.append(f"id={iid} 缺门面")
            continue
        pairs = (
            ("bbox", element.sceneBoundingRect(), adapter.sceneBoundingRect()),
            ("center", element.get_scene_center_pos(),
             adapter.get_scene_center_pos()),
            ("topLeft", element.get_scene_topLeft(),
             adapter.get_scene_topLeft()),
            ("head", element.get_scene_head_pos(),
             adapter.get_scene_head_pos()),
            ("end", element.get_scene_end_pos(),
             adapter.get_scene_end_pos()),
        )
        for label, got, want in pairs:
            if label == "bbox":
                ok = same_rect(got, want)
            else:
                ok = same_point(got, want)
            if not ok:
                diffs.append(f"id={iid} {label}: {got} != {want}")
                break
        if element.get_visibility() != adapter.get_visibility():
            diffs.append(f"id={iid} visibility 不一致")
    check("1618 图元几何 / 可见性零差异", not diffs,
          f"diffs={len(diffs)} 例: {diffs[:3]}")

    print("\n=== 4. 几何 profile 策略生效 ===")
    rotated = next((e for e in stage.registry.sorted()
                    if abs(e.get_angle()) > 1e-6 and e.TYPE == "rect"), None)
    if rotated is None:
        rotated = next((e for e in stage.registry.sorted()
                        if abs(e.get_angle()) > 1e-6), None)
    check("找到旋转图元", rotated is not None,
          f"angle={rotated.get_angle() if rotated else None}")
    if rotated is not None:
        aabb_corner = rotated.get_scene_topLeft()
        stage.registry.profile = STRICT_PROFILE
        analytic_corner = rotated.get_scene_topLeft()
        stage.registry.profile = RACK_PROFILE
        check("解析式角与 AABB 角确实不同",
              not same_point(aabb_corner, analytic_corner, 1e-3),
              f"aabb={aabb_corner} analytic={analytic_corner}")
        check("切回 rack profile 结果还原",
              same_point(rotated.get_scene_topLeft(), aabb_corner))

    print("\n=== 5. widget 承载口径 / 工厂 / 只读 ===")
    widget = stage.registry.widgets()[0]
    proxy = stage.widgets.proxy_of(widget.item_id)
    check("widget 有 proxy", proxy is not None)
    if proxy is not None:
        it = widget.item()
        rect = it.boundingRect()
        center = it.mapToScene(QPointF(0.0, 0.0))
        expected = center - QPointF(rect.width() / 2.0, rect.height() / 2.0)
        check("proxy.pos 与核心 _align_widget_proxy 同口径",
              same_point(proxy.pos(), expected),
              f"pos={proxy.pos()} expected={expected}")
        check("proxy 尺寸 == 图元 boundingRect",
              abs(proxy.size().width() - rect.width()) < EPS
              and abs(proxy.size().height() - rect.height()) < EPS)
        check("proxy 旋转跟随图元",
              abs(proxy.rotation() - it.rotation()) < EPS)
        check("proxy z = 图元 z + 0.5",
              abs(proxy.zValue() - (it.zValue() + 0.5)) < EPS)
        check("变换原点钉在控件中心",
              same_point(proxy.transformOriginPoint(),
                         QPointF(rect.width() / 2.0, rect.height() / 2.0)))
        check("占位图元不产出像素", bool(it.flags() & _NO_CONTENTS))
    check("默认 provider 造出真实控件",
          isinstance(stage.widget(widget.item_id), QWidget))

    created = []
    stage.controlCreated.connect(lambda iid, w: created.append((iid, w)))
    stage.set_factory(widget.item_id,
                      lambda host: QLabel("自定义 HMI 页面", host))
    check("外部工厂替换控件",
          isinstance(stage.widget(widget.item_id), QLabel)
          and stage.widget(widget.item_id).text() == "自定义 HMI 页面")
    check("替换后 proxy 数量不变", len(stage.widgets.proxies()) == 2)
    check("controlCreated 已广播", len(created) == 1,
          f"created={len(created)}")
    stage.widgets.set_readonly(widget.item_id, True)
    check("只读标记生效（不改外观）",
          stage.widgets.readonly(widget.item_id)
          and stage.widget(widget.item_id).isEnabled()
          and stage.widget(widget.item_id).testAttribute(_TRANSPARENT_MOUSE))
    stage.widgets.set_readonly(widget.item_id, False)

    print("\n=== 6. 点击路由 ===")
    target = next((e for e in stage.registry.sorted()
                   if e.TYPE in ("group", "checkbox") and e.effective_visibility()),
                  None)
    check("找到可点击图元", target is not None)
    if target is not None:
        stage.set_interactive([target.item_id], types=("group", "checkbox"))
        hits = []
        target.clicked.connect(lambda: hits.append(1))
        view_pt = target.item().sceneBoundingRect().center()
        check("hit_element 命中正确",
              stage.scene.hit_element(view_pt) is target)
        press = QGraphicsSceneMouseEvent(QEvent.GraphicsSceneMousePress)
        press.setScenePos(view_pt)
        press.setButton(Qt.LeftButton)
        press.setButtons(Qt.LeftButton)
        release = QGraphicsSceneMouseEvent(QEvent.GraphicsSceneMouseRelease)
        release.setScenePos(view_pt)
        release.setButton(Qt.LeftButton)
        release.setButtons(Qt.NoButton)
        stage.scene.mousePressEvent(press)
        stage.scene.mouseReleaseEvent(release)
        check("按下+释放发一次 clicked", len(hits) == 1, f"hits={len(hits)}")
        # 拖出去松手不算点击
        out = QGraphicsSceneMouseEvent(QEvent.GraphicsSceneMouseRelease)
        out.setScenePos(view_pt + QPointF(1e6, 1e6))
        out.setButton(Qt.LeftButton)
        out.setButtons(Qt.NoButton)
        press2 = QGraphicsSceneMouseEvent(QEvent.GraphicsSceneMousePress)
        press2.setScenePos(view_pt)
        press2.setButton(Qt.LeftButton)
        press2.setButtons(Qt.LeftButton)
        stage.scene.mousePressEvent(press2)
        stage.scene.mouseReleaseEvent(out)
        check("拖出图元外松手不触发", len(hits) == 1, f"hits={len(hits)}")

    print("\n=== 7. 数据总线 / 绑定 replay ===")
    stage.bind_element("tag.color", target.item_id if target else widget.item_id,
                       apply=lambda e, v: e.set_color(v))
    stage.tags.update("tag.color", "#ff0000")
    stage.tags.flush_now()
    check("bind_element 合流后生效",
          str(stage.tags.value("tag.color")) == "#ff0000")
    seen: list[str] = []
    stage.bind_control("tag.text", widget.item_id,
                       apply=lambda w, v: (w.setText(str(v)), seen.append(str(v))))
    stage.tags.update("tag.text", "ABC")
    stage.tags.flush_now()
    check("bind_control 生效", seen and seen[-1] == "ABC", f"seen={seen}")
    stage.set_factory(widget.item_id,
                      lambda host: QLabel("新的页面", host))
    check("控件重建后自动 replay 缓存值",
          seen[-1] == "ABC" and stage.widget(widget.item_id).text() == "ABC",
          f"seen={seen} text={stage.widget(widget.item_id).text()}")

    print("\n=== 8. 换页 / reload 不悬空 ===")
    kept = stage.registry.sorted()[0]
    kept_hits = []
    kept.clicked.connect(lambda: kept_hits.append(1))
    before_name = kept.get_name()
    n = stage.reload()
    check("reload 图元数不变", n == 1618, f"n={n}")
    check("门面对象跨 reload 复用", not kept.is_detached()
          and kept.get_name() == before_name)
    check("门面.item() 仍是当前场景对象",
          kept.item() is not None
          and stage.scene.find_item(kept.item_id) is kept.item())
    kept.clicked.emit()
    check("reload 后信号连接仍有效", len(kept_hits) == 1,
          f"hits={len(kept_hits)}")
    check("reload 后 proxy 数正确", len(stage.widgets.proxies()) == 2,
          f"proxies={len(stage.widgets.proxies())}")
    check("reload 后 page_data 仍一致", stage.scene.page_data() == original)

    # 内存换页：只留 1 个图元，验证消失的 id 被安全标 detached
    stage.widgets.reset()
    stage.scene.load_data({"sceneRect": {"x": 0, "y": 0,
                                         "width": 100, "height": 100},
                           "items": [{"type": "rect", "id": 999999,
                                      "name": "临时图元"}]})
    stage.scene.emit_structure_changed()
    check("换页后 registry 收缩", len(stage.registry) <= 1,
          f"len={len(stage.registry)}")
    check("消失的 id 标 detached", kept.is_detached())
    check("detached 门面 item() 返回 None", kept.item() is None)
    try:
        kept.set_visibility(False)
        kept.set_color("#00ff00")
        kept.change_position(QPointF(1, 2))
        check("detached 门面所有 setter 安全", True)
    except RuntimeError as exc:
        check("detached 门面所有 setter 安全", False, str(exc))
    check("换页后 reload 能恢复原页面", stage.reload() == 1618)

    print("\n=== 9. builtin / none 两种承载模式 ===")
    builtin = RuntimeStage(page_path=PAGE, widget_mode="builtin")
    builtin.load()
    check("builtin 模式由核心创建 proxy",
          len(builtin.widgets._proxies) == 0
          and len(builtin.scene.widget_proxies) == 2,
          f"own={len(builtin.widgets._proxies)} "
          f"core={len(builtin.scene.widget_proxies)}")
    check("builtin 模式 control_of 仍可拿控件",
          isinstance(builtin.widget(builtin.registry.widgets()[0].item_id),
                     QWidget))
    builtin.release()

    no_widgets = RuntimeStage(page_path=PAGE, widget_mode="none")
    no_widgets.load()
    check("none 模式不挂任何控件", len(no_widgets.widgets.proxies()) == 0
          and not no_widgets.controls())
    no_widgets.release()

    print("\n=== 10. 旧 API 门面 / 坐标换算 / 取景 ===")
    pm = stage.pages_manager      # PopPick 的 RuntimeSceneManager 口径
    check("pages_manager 只暴露 widget 卡片",
          len(pm.m_sorted_items) == 2
          and all(e.is_widget() for e in pm.all_items()),
          f"cards={len(pm.m_sorted_items)}")
    sm = stage.scene_manager      # rack / safety 的 SceneManager 口径
    sample = stage.registry.sorted()[0]
    check("scene_manager.findItemByName 命中门面",
          sm.findItemByName(sample.get_name()) is sample)
    check("scene_manager.m_items / m_name_items 可用",
          len(sm.m_items) == 1618 and len(sm.m_name_items) > 0,
          f"m_items={len(sm.m_items)} names={len(sm.m_name_items)}")
    check("view.scene_manager 已挂", stage.view.scene_manager is sm)
    check("sceneToView / viewToScene 严格互逆",
          same_point(QPointF(123.5, -456.25),
                     stage.view.viewToScene(
                         stage.view.sceneToView(QPointF(123.5, -456.25)))))
    stage.view.resize(900, 700)
    check("resize 后 fit_scene 生效", stage.view.fit_scene())
    check("fit_scene 后不再是 1:1 变换",
          abs(stage.view.transform().m11() - 1.0) > 1e-9,
          f"scale={stage.view.transform().m11():.6f}")
    pin_stage = RuntimeStage(page_path=PAGE, fit_mode="pin")
    check("pin 模式可选", pin_stage.fit_mode == "pin")
    pin_stage.release()

    print("\n=== 11. release / 解绑 ===")
    old_control = stage.widget(widget.item_id) if not widget.is_detached() else None
    stage.release()
    check("release 后无 proxy", len(stage.widgets.proxies()) == 0)
    check("release 后绑定清空", not stage._bindings)
    check("release 可重复调用", (stage.release() is None))
    if old_control is not None:
        check("承载控件不再可见", not old_control.isVisible())

    print(f"\n失败 {len(FAILURES)} 项" +
          (": " + ", ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
