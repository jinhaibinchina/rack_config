# -*- coding: utf-8 -*-
"""统一运行态模板框架的两个可跑样例（同一框架 / 两种业务形态）。

    .venv/Scripts/python.exe tools/demo_unified_runtime.py --mode rack
    .venv/Scripts/python.exe tools/demo_unified_runtime.py --mode poppick
    .venv/Scripts/python.exe tools/demo_unified_runtime.py --mode both --show

* ``rack`` 用真实的 ``page_5.json``（料仓全局参数面板）：默认 widget 控件
  （QCheckBox / QSpinBox）+ 普通图元 + PLC 点位绑定 + 点击路由。
* ``poppick`` 用真实的 ``page_9.json``（7 张页面卡片）：外部工厂把整张
  QWidget 页面挂到 widget 图元上 + pages_manager 门面 + 坐标换算。

默认离屏跑完即退出（只打印，不开窗）；加 ``--show`` 会真的显示一个窗口，
``--seconds`` 控制自动关闭时间。全程不写任何页面文件。

这两个样例演示的是**怎么在新项目里用统一框架**，不改动 PopPick /
RackConfig 任何既有代码；迁移步骤见
``docs/unified_runtime_template_design.md``。
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QLabel, QMainWindow, QSpinBox, QVBoxLayout,
    QWidget,
)

from Designer.CoreQGraphics.runtime import RuntimeStage  # noqa: E402

PAGE_DIR = os.path.join("Designer", "Core", "data.json", "datas",
                        "design", "pages")
RACK_PAGE = os.path.join(PAGE_DIR, "page_5.json")
POPPICK_PAGE = os.path.join(PAGE_DIR, "page_9.json")


def demo_rack() -> RuntimeStage:
    """料仓形态：普通图元 + 默认 widget 控件 + 点位绑定。"""
    print("\n" + "=" * 68)
    print("样例 A —— RackConfig 形态（page_5.json 料仓全局参数面板）")
    print("=" * 68)
    stage = RuntimeStage(page_path=RACK_PAGE,
                         geometry_profile="rack",   # 四角用 AABB 角，与 rack 对拍
                         widget_mode="host",        # 框架自建 proxy
                         fit_mode="fit",            # resize 时重算取景
                         flush_ms=60)
    print("[1] load:", stage.load(), stage.report())
    print("[2] 普通图元:",
          [(e.TYPE, e.get_name()) for e in stage.elements()
           if not e.is_widget()][:6])
    print("[3] widget 图元及其默认控件:")
    for element in stage.registry.widgets():
        control = stage.widget(element.item_id)
        print(f"      {element.get_name():<20} -> "
              f"{type(control).__name__ if control else 'None'}")

    # 业务约束由业务侧加，框架不猜语义：仓位编号允许 -1（未指定）
    # 对应真实 RackGlobalParasModelV2.SLOT_NO_RANGE
    for name in ("仓位编号1", "仓位编号2"):
        spin = stage.widget(name)
        if isinstance(spin, QSpinBox):
            spin.setRange(-1, 9)

    # 真实业务绑定：DB41 的三个勾选框 + 两个仓位编号
    stage.bind_control("db41.membrane_alarm", "屏蔽膜卷号报警")
    stage.bind_control("db41.material_ng_alarm", "屏蔽物料状态NG报警")
    stage.bind_control("db41.slot_no_1", "仓位编号1")
    stage.bind_control("db41.slot_no_2", "仓位编号2")
    # 普通图元也能绑：改文本图元内容 / 颜色
    text_items = [e for e in stage.elements() if e.TYPE == "text"]
    if text_items:
        stage.bind_element("plc.status", text_items[0].item_id)
    stage.tags.update_many({
        "db41.membrane_alarm": True,
        "db41.material_ng_alarm": False,
        "db41.slot_no_1": 3,
        "db41.slot_no_2": -1,
        "plc.status": "运行中",
    })
    stage.tags.flush_now()
    print("[4] PLC 点位合流后的控件值:")
    for name in ("屏蔽膜卷号报警", "屏蔽物料状态NG报警",
                 "仓位编号1", "仓位编号2"):
        control = stage.widget(name)
        value = None
        if isinstance(control, QCheckBox):
            value = control.isChecked()
        elif isinstance(control, QSpinBox):
            value = control.value()
        elif isinstance(control, QLabel):
            value = control.text()
        print(f"      {name:<20} = {value}")

    # 点击路由：demo 里打开全部图元；生产环境建议限定
    # types=("group", "checkbox") 或只传业务需要的名字列表
    stage.set_interactive(None)
    stage.elementClicked.connect(
        lambda e: print(f"      [click] {e.get_name()} ({e.TYPE})"))
    print("[5] 已打开点击路由的图元数:",
          sum(1 for e in stage.elements() if e.is_interactive()))
    print("[6] 运行态零污染检查:",
          "page_data 未写回" if _page_clean(stage, RACK_PAGE) else "!!! 有写回")
    return stage


def demo_poppick() -> RuntimeStage:
    """PopPick 形态：widget 卡片挂整页工厂控件。"""
    print("\n" + "=" * 68)
    print("样例 B —— PopPick 形态（page_9.json 7 张页面卡片）")
    print("=" * 68)
    stage = RuntimeStage(page_path=POPPICK_PAGE,
                         geometry_profile="strict",  # 解析式四角
                         widget_mode="host",
                         fit_mode="pin",             # 钉左上角，resize 不动画面
                         flush_ms=100)
    print("[1] load:", stage.load(), stage.report())

    # 外部工厂：host 是 proxy 需要的无父 QWidget；第二参数会自动传入门面
    def make_page(host, element):
        page = QWidget(host)
        layout = QVBoxLayout(page)
        title = QLabel(f"HMI 页面 · {element.get_name()}", page)
        title.setObjectName("title")
        value = QLabel("--", page)
        value.setObjectName("value")
        layout.addWidget(title)
        layout.addWidget(value)
        layout.addStretch(1)
        page.setStyleSheet("QWidget{background:#162334;color:#e8f1ff;}"
                           "QLabel#title{font-size:20px;}")
        return page

    cards = [e.get_name() for e in stage.registry.widgets()]
    stage.set_mapping({name: make_page for name in cards})
    print("[2] 注入页面工厂:", cards)
    print("[3] 控件挂载结果:")
    for name in cards:
        control = stage.widget(name)
        title = control.findChild(QLabel, "title") if control else None
        print(f"      {name:<8} -> {type(control).__name__ if control else 'None'}"
              f"  title={title.text() if title else '-'}")

    # pages_manager 就是旧 PopPick RuntimeSceneManager 的形状
    print("[4] pages_manager.m_sorted_items:",
          [e.get_name() for e in stage.pages_manager.m_sorted_items])

    # 数据绑定：只刷新最前面一张卡（其余用缓存 replay）
    front = cards[0]
    stage.bind_control(
        "hmi.speed", front,
        apply=lambda w, v: w.findChild(QLabel, "value").setText(f"{v} mm/s"))
    stage.tags.update("hmi.speed", 1280)
    stage.tags.flush_now()
    print("[5] 前台页实时值:",
          stage.widget(front).findChild(QLabel, "value").text())

    # 坐标换算：窗口像素 / 视图坐标 / page 坐标
    from PySide6.QtCore import QPointF
    p = QPointF(120.0, -340.0)
    v = stage.view.sceneToView(p)
    print("[6] sceneToView / viewToScene:",
          f"page{p.x(), p.y()} -> view({v.x():.2f},{v.y():.2f}) "
          f"-> page{stage.view.viewToScene(v).x(), stage.view.viewToScene(v).y()}")
    print("[7] 运行态零污染检查:",
          "page_data 未写回" if _page_clean(stage, POPPICK_PAGE) else "!!! 有写回")
    return stage


def _page_clean(stage: RuntimeStage, path: str) -> bool:
    """装载 + 挂控件之后，page_data 仍与磁盘上的 JSON 逐字相等。"""
    import json
    with open(path, "r", encoding="utf-8") as f:
        disk = json.load(f)
    return stage.scene.page_data() == disk


def _show_window(stage: RuntimeStage, title: str) -> QMainWindow:
    window = QMainWindow()
    window.setWindowTitle(title)
    window.resize(900, 700)
    host = QWidget()
    layout = QVBoxLayout(host)
    stage.attach(layout)
    window.setCentralWidget(host)
    window.show()
    stage.view.fit_scene()
    return window


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("rack", "poppick", "both"),
                        default="both")
    parser.add_argument("--show", action="store_true", help="显示真实窗口")
    parser.add_argument("--seconds", type=float, default=3.0,
                        help="--show 时自动关闭秒数")
    args = parser.parse_args()
    if args.show:
        os.environ.pop("QT_QPA_PLATFORM", None)   # 用真实平台

    app = QApplication.instance() or QApplication([])
    stages: list[tuple[RuntimeStage, str]] = []
    if args.mode in ("rack", "both"):
        stages.append((demo_rack(), "统一运行态 - RackConfig 形态"))
    if args.mode in ("poppick", "both"):
        stages.append((demo_poppick(), "统一运行态 - PopPick 形态"))

    windows = []
    if args.show:
        for stage, title in stages:
            windows.append(_show_window(stage, title))
        QTimer.singleShot(int(args.seconds * 1000), app.quit)
        app.exec()
    for stage, _title in stages:
        stage.release()
    print("\n完成：两种形态共用同一套 RuntimeStage，普通图元与 widget 图元并行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
