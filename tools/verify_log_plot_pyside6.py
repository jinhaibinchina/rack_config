"""日志绘图工具（log_plot_main）的 PySide6 迁移回归脚本。

离屏把整套界面建一遍，并用 ``App_LogPlot/log`` 下的样例 CSV 走完
「导入 → 解析 → 绘图 → 播放线程」链路，确认没有 PyQt5 残留。

    .venv/Scripts/python.exe tools/verify_log_plot_pyside6.py

依赖 App_LogPlot/requirements.txt 里声明的包（numpy / pandas / pyarrow /
matplotlib 等）和项目 venv 里的 PySide6。
"""
from __future__ import annotations

import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# matplotlib 会按 PyQt6 → PyQt5 → PySide6 顺序探测绑定，必须钉死
os.environ.setdefault("QT_API", "pyside6")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QMessageBox, QCompleter, QLineEdit  # noqa: E402
from PySide6.QtCore import QTimer, Qt, QStringListModel  # noqa: E402
from PySide6.QtXml import QDomDocument  # noqa: E402

# 导入日志结束时会弹 QMessageBox，离屏脚本里把它变成非阻塞的返回值
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)

# 构造过的对话框统一留引用，避免脚本中途被 GC 掉再被事件循环碰到
_alive: list = []

import App_LogPlot.log_plot_entry as entry  # noqa: E402

SAMPLES = os.path.join(ROOT, "App_LogPlot", "log", "AppLog_2026_07_03_09_18_21.csv")

results: list[tuple[str, bool, str]] = []


def check(name: str, fn) -> None:
    try:
        fn()
        results.append((name, True, ""))
        print(f"[OK]   {name}")
    except Exception as exc:  # noqa: BLE001
        results.append((name, False, f"{type(exc).__name__}: {exc}"))
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=4)


# ---------------------------------------------------------------- 1. 模块导入
def _import_all() -> None:
    import importlib

    mods = [
        "App_LogPlot.app.rcd_log_importer",
        "App_LogPlot.app.rcd_tr",
        "App_LogPlot.app.agv_log_parser",
        "App_LogPlot.app.cset_parser",
        "App_LogPlot.app.record_batch_reader",
        "App_LogPlot.app.plot_moudle.load_ui",
        "App_LogPlot.app.plot_moudle.common",
        "App_LogPlot.app.plot_moudle.interface",
        "App_LogPlot.app.plot_moudle.global_config",
        "App_LogPlot.app.plot_moudle.mat_plot",
        "App_LogPlot.app.plot_moudle.polt_matrix",
        "App_LogPlot.app.plot_moudle.plot_window_with_datalist",
        "App_LogPlot.app.plot_moudle.tabbed_plot_widget",
        "App_LogPlot.app.plot_moudle.data_map_panel",
        "App_LogPlot.app.plot_moudle.work_thread",
        "App_LogPlot.app.plot_moudle.log_generator",
        "App_LogPlot.app.plot_moudle.measure_tool",
        "App_LogPlot.app.plot_moudle.script_dialog",
        "App_LogPlot.app.plot_moudle.combo_plot_dialog",
        "App_LogPlot.app.plot_moudle.logic_search_dialog",
        "App_LogPlot.app.plot_moudle.data_transformer",
        "App_LogPlot.app.plot_moudle.resource_manager",
    ]
    for m in mods:
        importlib.import_module(m)


# QApplication 必须先建：绘图模块 import 时 matplotlib 的 Qt 后端会自己创建
# 一个裸 QApplication，之后再建 App 子类就会报 singleton 冲突。
app = entry.App(sys.argv[:1])

check("导入全部模块", _import_all)

win = entry.MainWidget()
win.show()
plot = win.plot_widget
tabbed = plot.tabbed_widget

# ---------------------------------------------------------------- 2. 界面交互
check("新增选项卡", lambda: tabbed.addTab())
check("当前选项卡", lambda: tabbed.currentTab())
check("多标签开关(P)", plot.handle_pushButtonMultiLabels_click)
check("比率开关(H)", plot.handle_pushButtonRatio_click)
check("网格开关(G)", plot.handle_pushButtonActivateGrid_click)
check("选项面板", plot.handle_pushButtonOptions_click)


def _logic_dialog() -> None:
    from App_LogPlot.app.plot_moudle.logic_search_dialog import LogicScriptInputDialog

    dlg = LogicScriptInputDialog(plot.data_transformer, plot.rcd_data_bridge, ["time"])
    dlg.show()
    _alive.append(dlg)


def _script_dialog() -> None:
    from App_LogPlot.app.plot_moudle.script_dialog import ScriptInputDialog

    dlg = ScriptInputDialog(plot.data_transformer)
    dlg.show()
    _alive.append(dlg)


def _version_info() -> None:
    # 不真的弹模态框（离屏环境会挂住事件循环），只校验文案能取到
    assert entry.VERSION in entry.VERSION_INFO


check("条件搜索对话框（QUiLoader 载 logic_search.ui）", _logic_dialog)
check("脚本输入对话框", _script_dialog)
check("版本说明文案", _version_info)


def _xml_roundtrip() -> None:
    doc = QDomDocument()
    root = doc.createElement("TabbedPlotWidget")
    root.setAttribute("name", tabbed.name())
    doc.appendChild(root)
    doc2 = QDomDocument()
    doc2.setContent(doc.toString())
    assert doc2.documentElement().attribute("name") == tabbed.name()


def _completer() -> None:
    edit = QLineEdit()
    comp = QCompleter()
    comp.setModel(QStringListModel(["linear", "wheel", "motor"]))
    comp.setCompletionMode(QCompleter.PopupCompletion)
    comp.setCaseSensitivity(Qt.CaseInsensitive)
    comp.setFilterMode(Qt.MatchContains)
    edit.setCompleter(comp)


check("QDomDocument 往返（QtXml）", _xml_roundtrip)
check("QCompleter 配置", _completer)

# ---------------------------------------------------------------- 3. 真实日志
bridge = plot.rcd_data_bridge


def _import_log() -> None:
    assert os.path.exists(SAMPLES), f"缺少样例日志: {SAMPLES}"
    win.slot_import_log([SAMPLES])
    heads = bridge.head_names() or []
    assert heads, "导入后表头为空"
    assert len(bridge.xdata_rcd()) > 0, "导入后没有时间轴数据"


check("导入样例 CSV（含线程/信号）", _import_log)


def _plot_curve() -> None:
    heads = bridge.head_names() or []
    title = heads[1]
    y = bridge.request_data_by_head_name(title)[1]
    plot.tabbed_widget.currentTab().plotAt(0, 0).plot(bridge.xdata_rcd(), y, label=title)


check("绘制曲线", _plot_curve)


def _playback() -> None:
    plot.start_task_player()
    QTimer.singleShot(1200, plot.start_task_player)  # 再点一次 = 停止
    loop = QTimer()
    loop.setSingleShot(True)
    loop.timeout.connect(app.quit)
    loop.start(1600)
    app.exec()
    plot.stop_all_tasks()


check("播放线程启停", _playback)

# ---------------------------------------------------------------- 4. 本轮修复
def _menu_bindings() -> None:
    """「文件」放两个导入动作，「帮助」放关于；且各自触发对应的槽。"""
    # 保持 QAction / QMenu 的 Python wrapper 引用：只把 menu() 存进 dict，
    # 临时 action wrapper 被 GC 后会把 C++ QMenu 一起带走（离屏下尤其明显）。
    top_actions = win.menuBar().actions()
    assert [a.text() for a in top_actions] == ["文件", "帮助"]
    file_menu = top_actions[0].menu()
    help_menu = top_actions[1].menu()
    file_actions = file_menu.actions()
    help_actions = help_menu.actions()
    assert [a.text() for a in file_actions] == ["导入文件夹", "导入文件"]
    assert [a.text() for a in help_actions] == ["关于"]

    calls: list = []
    exec_titles: list = []
    original = (
        win.get_files_by_file_dialog,
        win.get_path_by_folder_dialog,
        win.slot_import_log,
        win.slot_import_log_by_folder,
        QMessageBox.exec,
    )
    try:
        # 文件对话框本身是模态的，换成哨兵值；导入槽也只记录调用
        win.get_files_by_file_dialog = lambda: ["<测试文件>"]
        win.get_path_by_folder_dialog = lambda: "<测试目录>"
        win.slot_import_log = lambda files: calls.append(("导入文件", files))
        win.slot_import_log_by_folder = lambda path, *a, **k: calls.append(("导入文件夹", path))
        QMessageBox.exec = lambda self, *a, **k: exec_titles.append(self.windowTitle()) or 0

        file_actions[0].trigger()
        file_actions[1].trigger()
        help_actions[0].trigger()
    finally:
        (
            win.get_files_by_file_dialog,
            win.get_path_by_folder_dialog,
            win.slot_import_log,
            win.slot_import_log_by_folder,
            QMessageBox.exec,
        ) = original

    assert ("导入文件夹", "<测试目录>") in calls, calls
    assert ("导入文件", ["<测试文件>"]) in calls, calls
    assert "版本说明" in exec_titles, exec_titles


def _combo_plot() -> None:
    """主副轴合并图：两组曲线分别落到 ax / ax_vice，按钮能显隐。"""
    from App_LogPlot.app.plot_moudle.global_config import global_config
    from App_LogPlot.app.plot_moudle.plotMatrixWithViceAxis import PlotMatrixWithVice
    from App_LogPlot.app.plot_moudle.tabbed_plot_widget import ComboPoltDialog

    heads = bridge.head_names() or []
    assert len(heads) > 2, "样例日志表头不足"
    matrix = PlotMatrixWithVice("组合图", bridge, tabbed._rcd_translater)
    single = matrix.plotAt(0, 0)
    assert single.ax_vice is not None, "合并图没有右侧副轴"

    single._plot_by_data_keys([heads[1]])
    single._plot_by_data_keys([heads[2]], True)
    assert len(single.lines) == 2
    assert single.lines_on_vice == [False, True], single.lines_on_vice
    assert single.lines[0].axes is single.ax
    assert single.lines[1].axes is single.ax_vice
    legend = single.ax.get_legend()
    assert legend is not None and len(legend.get_texts()) == 2, "图例没合并主副轴曲线"

    global_config.set_axis_visible(False, True)
    assert not single.lines[0].get_visible() and single.lines[1].get_visible()
    global_config.set_axis_visible(True, True)
    assert all(line.get_visible() for line in single.lines)

    dlg = ComboPoltDialog(win, matrix)   # 不用 exec()：离屏模态框会挂住事件循环
    dlg.show()
    _alive.append(dlg)
    dlg.on_btn_major_en_click()           # 关主轴
    assert not single.lines[0].get_visible()
    dlg.on_btn_vice_en_click()            # 恢复全开
    assert all(line.get_visible() for line in single.lines)
    matrix.on_Zoom_max()
    dlg.close()
    assert global_config.major_axis_en and global_config.vice_axis_en


def _combo_entry() -> None:
    """选项卡右键「第一列双图合并」的完整入口（空壳时代必崩的路径）。"""
    from App_LogPlot.app.plot_moudle.tabbed_plot_widget import ComboPoltDialog

    tab = tabbed.currentTab()
    tab.addRow()  # 凑成 2 行 1 列，才能做「第一列双图合并」
    heads = bridge.head_names() or []
    bottom = tab.plotAt(1, 0)
    assert bottom is not None
    y = bridge.request_data_by_head_name(heads[3])[1]
    bottom.plot(bridge.xdata_rcd(), y, label=heads[3])

    orig_exec = ComboPoltDialog.exec
    ComboPoltDialog.exec = lambda self, *a, **k: _alive.append(self) or 0
    try:
        tabbed.open_ComboPolt_dialog(3)
    finally:
        ComboPoltDialog.exec = orig_exec

    dlg = _alive[-1]
    single = dlg.PlotMatrix.plotAt(0, 0)
    assert len(single.lines) == 2, "合并后应有两组曲线"
    assert single.lines_on_vice == [False, True], single.lines_on_vice


def _launcher_registration() -> None:
    """日志工具已注册进选择页，能打开、关掉能回到选择页。"""
    import main

    keys = [tool.key for tool in main.TOOLS]
    assert "logplot" in keys, keys
    assert main._tool("logplot").factory is main._make_log_plot

    launcher = main.ToolLauncher(enable_plc=False)
    launcher.show()
    cards = launcher.findChildren(main.ToolCard)
    assert len(cards) == len(main.TOOLS), "卡片数与工具注册表不一致"

    launcher._open("logplot")
    window = launcher._active
    assert isinstance(window, entry.MainWidget), type(window)
    assert window.isVisible() and not launcher.isVisible()
    window.close()
    assert launcher.isVisible(), "关闭工具后没有回到选择页"
    _alive.append(launcher)


check("菜单分组与槽映射", _menu_bindings)
check("主副轴组合图（曲线/图例/显隐/缩放）", _combo_plot)
check("右键菜单双图合并入口", _combo_entry)
check("工具选择页注册与回落", _launcher_registration)

win.close()

failed = [r for r in results if not r[1]]
print(f"\n通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项")
for name, _, err in failed:
    print(f"  - {name}: {err}")
sys.exit(1 if failed else 0)
