"""离屏自检：packTool.py / 工具集.spec / 资源布局三者的收敛状态。

跑法：``.venv/Scripts/python.exe tools/verify_pack_tool.py``
"""
import ast
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

app = QApplication([])
from packTool import PythonPackager, PackagerThread

ok = 0
fail = 0


def check(title, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"[OK] {title} {detail}")
    else:
        fail += 1
        print(f"[FAIL] {title} {detail}")


w = PythonPackager()
check("主窗口构造", w.python_edit is not None and w.collect_submodules_cb is not None)
check("载入旧配置", w.project_path is not None and "asyncua" in w.hidden_imports,
      f"resources={len(w.include_resources)}")
check("旧配置资源目标补全",
      all(k in w.resource_dests for k in w.include_resources),
      str(w.resource_dests))
expected_config_dests = {
    "res", ".",
    "App_LogPlot/app/plot_moudle/cfg",
    "App_LogPlot/app/plot_moudle/data",
    "App_LogPlot/app/plot_moudle/ui",
    "App_LogPlot/app/plot_moudle/ico",
    "App_LogPlot/cfg",
    "App_PopPick/hmi/data",
}
check("工具配置已含收敛后的资源清单",
      expected_config_dests <= set(w.resource_dests.values()),
      str(sorted(set(w.resource_dests.values()) - expected_config_dests)))

# ----------------------------------------------------------------------
# 1. 收敛后的布局：所有资源一律保持源码层级
# ----------------------------------------------------------------------
plot_ui = ROOT / "App_LogPlot/app/plot_moudle/ui"
tag_data = ROOT / "App_PopPick/hmi/data"
PLOT_DEST = "App_LogPlot/app/plot_moudle/ui"
TAG_DEST = "App_PopPick/hmi/data"
check("扫描器不再建议摊平 plot_moudle/ui",
      w._suggest_dest(plot_ui) == PLOT_DEST, w._suggest_dest(plot_ui))
check("扫描器保持 tag_catalog 层级",
      w._suggest_dest(tag_data) == TAG_DEST, w._suggest_dest(tag_data))

# resource_manager 不再有 if frozen 分支：模拟打包态 __file__ 直接算基路径
rm_file = ROOT / "App_LogPlot/app/plot_moudle/resource_manager.py"
rm_src = rm_file.read_text(encoding="utf-8")
rm_tree = ast.parse(rm_src)
rm_fn = next(n for n in ast.walk(rm_tree)
             if isinstance(n, ast.FunctionDef) and n.name == "_get_base_path")
has_if = any(isinstance(n, ast.If) for n in ast.walk(rm_fn))
has_meipass = any(isinstance(n, ast.Attribute) and n.attr == "_MEIPASS"
                  for n in ast.walk(rm_fn))
uses_file = any(isinstance(n, ast.Name) and n.id == "__file__"
                for n in ast.walk(rm_fn))
check("_get_base_path 无 frozen 分支（只看语句，docstring 不算）",
      not has_if and not has_meipass and uses_file,
      f"if={has_if} _MEIPASS={has_meipass} __file__={uses_file}")
fake_meipass = ROOT / "build/_fake_meipass"
fake_frozen = fake_meipass / "App_LogPlot/app/plot_moudle/resource_manager.pyc"
rm_ns = {"__name__": "_fake_resource_manager", "__file__": str(fake_frozen)}
exec(compile(rm_src, str(rm_file), "exec"), rm_ns)
base = rm_ns["_ResourceManager"]._get_base_path(None)
check("frozen 基路径 = __file__ 所在目录", base == fake_frozen.parent, str(base))
rel_ui = (base / "ui/rcd_plot.ui").relative_to(fake_meipass).as_posix()
check("运行时 ui 路径 = 源码层级",
      rel_ui == "App_LogPlot/app/plot_moudle/ui/rcd_plot.ui", rel_ui)

# ----------------------------------------------------------------------
# 2. packTool 生成的 spec
# ----------------------------------------------------------------------
w.resource_dests = {str(plot_ui): PLOT_DEST, str(tag_data): TAG_DEST}
w.include_resources = list(w.resource_dests)
spec = w._generate_spec_content()
check("生成内容非空", len(spec) > 800, f"{len(spec)} chars")
check("含前置自检", "find_spec" in spec and "raise SystemExit(1)" in spec)
check("含 collect_submodules", "collect_submodules('asyncua')" in spec
      or "'asyncua'" in spec and "SUBMODULE_ROOTS" in spec)
check("生成的目标保持层级", PLOT_DEST in spec and TAG_DEST in spec)
check("ROOT 由 SPECPATH 推出", "ROOT = Path(SPECPATH).resolve()" in spec)
check("不再写死绝对路径", "D:/MyProject" not in spec and "D:\\\\MyProject" not in spec)

captured = {}


def fake_analysis(scripts, **kw):
    captured.update(kw)
    captured["scripts"] = scripts
    return type("A", (), {"pure": [], "zipped_data": [], "scripts": [],
                          "binaries": [], "zipfiles": [], "datas": []})()


ns = {
    "SPECPATH": str(ROOT),
    "Analysis": fake_analysis,
    "PYZ": lambda *a, **kw: None,
    "EXE": lambda *a, **kw: None,
    "COLLECT": lambda *a, **kw: None,
}
try:
    exec(compile(spec, "generated.spec", "exec"), ns)
    check("spec 可执行", True)
    check("hiddenimports 收全子模块", len(ns["hiddenimports"]) > 100,
          f"{len(ns['hiddenimports'])} 个")
    dests = {d for _, d in captured["datas"]}
    check("生成的 datas 目标正确",
          dests == {PLOT_DEST, TAG_DEST}, str(dests))
    check("入口脚本解析正确",
          str(Path(captured["scripts"][0]).name) == "main.py",
          str(captured["scripts"][0]))
except Exception as exc:
    check("spec 可执行", False, repr(exc))

# ----------------------------------------------------------------------
# 2b. 回归：UI 的「隐藏导入」被清空时，兜底必须仍然生效
#     （23:21 的配置文件里 hidden_imports 真的变成过 []）
# ----------------------------------------------------------------------
python_exe = w.python_edit.text().strip() or sys.executable
auto_roots = w._optional_import_roots(python_exe)
check("AST 识别出 try/except ImportError 的关键包",
      "asyncua" in auto_roots, str(auto_roots))
check("依赖探针能识别 asyncua 来自 site-packages",
      "asyncua" in w._installed_third_party(python_exe))

saved_hidden = list(w.hidden_imports)
w.hidden_imports = []
w.hidden_imports_list.clear()
empty_spec = w._generate_spec_content()
check("空隐藏导入时 spec 写明警告", "隐藏导入」为空" in empty_spec)
empty_ns = {
    "SPECPATH": str(ROOT),
    "Analysis": fake_analysis,
    "PYZ": lambda *a, **kw: None,
    "EXE": lambda *a, **kw: None,
    "COLLECT": lambda *a, **kw: None,
}
try:
    exec(compile(empty_spec, "empty.spec", "exec"), empty_ns)
    check("空隐藏导入时自检仍覆盖 asyncua",
          "asyncua" in empty_ns["REQUIRED_IMPORTS"],
          str(empty_ns["REQUIRED_IMPORTS"][:8]))
    check("空隐藏导入时仍收全子模块",
          len(empty_ns["hiddenimports"]) > 100,
          f"{len(empty_ns['hiddenimports'])} 个")
    check("空隐藏导入时 SUBMODULE_ROOTS 自动兜底",
          "asyncua" in empty_ns["SUBMODULE_ROOTS"],
          str(empty_ns["SUBMODULE_ROOTS"]))
except Exception as exc:
    check("空隐藏导入时 spec 可执行", False, repr(exc))
w.hidden_imports = saved_hidden
for _m in saved_hidden:
    w.hidden_imports_list.addItem(_m)

# 一键应用资源时不能把项目根 / 工具目录 / 设计工程塞进 datas
saved_res = list(w.include_resources)
saved_dests = dict(w.resource_dests)
w._apply_scan_resources([ROOT] + [d for d, _ in w._scan_resource_dirs()])
resolved = {str(Path(x).resolve()) for x in w.include_resources}
check("一键应用不会加入项目根", str(ROOT.resolve()) not in resolved)
check("一键应用不会加入 tools / 设计工程",
      not any("/tools" in x.replace("\\", "/")
              or "data.json" in x for x in w.include_resources),
      str([x for x in w.include_resources if "/tools" in x.replace("\\", "/")][:3]))
parents = sorted(resolved, key=lambda x: (x.count("/") + x.count("\\"), x))
check("一键应用无父子重复目录",
      not any(a != b and b.startswith(a + "/") for a in parents for b in parents))
w.include_resources = saved_res
w.resource_dests = saved_dests
w._reload_resource_list()

# ----------------------------------------------------------------------
# 3. 手工维护的 工具集.spec 必须与运行时布局一致
# ----------------------------------------------------------------------
real_spec = ROOT / "工具集.spec"
spec2_captured = {}


def fake_analysis2(scripts, **kw):
    spec2_captured.update(kw)
    return type("A", (), {"pure": [], "zipped_data": [], "scripts": [],
                          "binaries": [], "zipfiles": [], "datas": []})()


ns2 = {
    "SPECPATH": str(ROOT),
    "DISTPATH": str(ROOT / "build/_spec_verify_dist"),
    "Analysis": fake_analysis2,
    "PYZ": lambda *a, **kw: None,
    "EXE": lambda *a, **kw: None,
    "COLLECT": lambda *a, **kw: None,
}
try:
    exec(compile(real_spec.read_text(encoding="utf-8"), str(real_spec), "exec"), ns2)
    check("工具集.spec 可执行", True)
    dests2 = {d for _, d in spec2_captured["datas"]}
    expected_plots = {
        f"App_LogPlot/app/plot_moudle/{n}"
        for n in ("cfg", "data", "ui", "ico")
        if (ROOT / "App_LogPlot/app/plot_moudle" / n).is_dir()
    }
    check("工具集.spec 资源目标保持层级",
          expected_plots <= dests2 and TAG_DEST in dests2
          and "App_LogPlot/cfg" in dests2,
          str(sorted(dests2)))
    check("工具集.spec 不再摊平出通用短名目录",
          not ({"ui", "cfg", "ico", "data", "templates"} & dests2),
          str({"ui", "cfg", "ico", "data", "templates"} & dests2))
    check("工具集.spec 仍收全 asyncua",
          len(ns2["hiddenimports"]) > 100, f"{len(ns2['hiddenimports'])} 个")
except Exception as exc:
    check("工具集.spec 可执行", False, repr(exc))

# ----------------------------------------------------------------------
# 4. 打包环境自检 / warn 扫描（上一轮事故的回归）
# ----------------------------------------------------------------------
good = str(ROOT / ".venv/Scripts/python.exe")
bad = r"D:\rack\rack_config\.venv\Scripts\python.exe"
check("正确解释器自检通过", w._preflight(good)[0], w._preflight(good)[1])
if Path(bad).is_file():
    ok_bad, msg_bad = w._preflight(bad)
    check("错误解释器被拦下", not ok_bad and "asyncua" in msg_bad, msg_bad[:60])

warn_dir = ROOT / "build" / "temp_工具集"
if warn_dir.is_dir():
    probe = ROOT / "build/temp_工具集.spec"
    t = PackagerThread(probe, ROOT, hidden_imports=["asyncua"])
    declared, others = t._scan_warn_files()
    check("warn 文件扫出缺失的隐藏导入", "asyncua" in declared,
          f"declared={declared[:5]} others={len(others)}")

# ----------------------------------------------------------------------
# 5. 若已有打包产物，模拟 frozen 环境逐条验证资源路径真的能命中
# ----------------------------------------------------------------------
dist_internal = ROOT / "dist/工具集/_internal"
if dist_internal.is_dir():
    frozen_file = dist_internal / "App_LogPlot/app/plot_moudle/resource_manager.pyc"
    prod_ns = {"__name__": "_frozen_probe", "__file__": str(frozen_file)}
    exec(compile(rm_src, str(rm_file), "exec"), prod_ns)
    cls = prod_ns["_ResourceManager"]
    mgr = object.__new__(cls)
    mgr._cache = {}
    mgr._base_path = mgr._get_base_path()
    probes = [
        mgr.get_ui_path("rcd_plot.ui"),
        mgr.get_ui_path("rcd.qss"),
        mgr.get_icon_path("add_column.svg"),
        mgr.get_config_path("head_name_map.json"),
        mgr.get_data_path("combo_data.json"),
    ]
    missing = [p for p in probes if not Path(p).is_file()]
    check("产物资源路径全部可命中", not missing, str(missing))
    short_names = [n for n in ("ui", "cfg", "ico", "data")
                   if (dist_internal / n).is_dir()]
    check("产物根下不再有通用短名目录", not short_names, str(short_names))
    check("tag_catalog 的变量清单在产物里",
          (dist_internal / TAG_DEST / "opcua_nodes.json").is_file())
    # rcd_tr.py 是 dirname(dirname(__file__)) 往上跳两级的 __file__ 型
    frozen_rcd = dist_internal / "App_LogPlot/app/rcd_tr.pyc"
    rcd_root = os.path.dirname(os.path.dirname(os.path.abspath(str(frozen_rcd))))
    tr_cfg = Path(rcd_root) / "cfg/ctu/analysis_info.json"
    check("rcd_tr 跳两级后的配置在产物里", tr_cfg.is_file(), str(tr_cfg))
    # cset_parser 读 cwd 相对 cfg/config.json，走 exe 同层那份
    check("cwd 相对读取的配置在 exe 同层",
          (ROOT / "dist/工具集/cfg/config.json").is_file())

print(f"\n===== 通过 {ok} 项，失败 {fail} 项 =====")
raise SystemExit(1 if fail else 0)
