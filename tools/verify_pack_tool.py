"""离屏自检：packTool.py 改动后能不能生成一份「不会再静默缺库」的 spec。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(r"D:\MyProject\qt_project\AppsManagers")
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

# 逐项资源目标：摊平 ui / 保持层级
w.resource_dests = {
    str(ROOT / "App_LogPlot/app/plot_moudle/ui"): "ui",
    str(ROOT / "App_PopPick/hmi/data"): "App_PopPick/hmi/data",
}
w.include_resources = list(w.resource_dests)
spec = w._generate_spec_content()
check("生成内容非空", len(spec) > 800, f"{len(spec)} chars")
check("含前置自检", "find_spec" in spec and "raise SystemExit(1)" in spec)
check("含 collect_submodules", "collect_submodules('asyncua')" in spec
      or "'asyncua'" in spec and "SUBMODULE_ROOTS" in spec)
check("资源目标摊平到 ui", "'ui'" in spec)
check("资源目标保持层级", "'App_PopPick/hmi/data'" in spec)
check("ROOT 由 SPECPATH 推出", "ROOT = Path(SPECPATH).resolve()" in spec)
check("不再写死绝对路径", "D:/MyProject" not in spec and "D:\\\\MyProject" not in spec)

# 当成真正的 spec 执行（桩掉 PyInstaller 的构造类），校验变量取值
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
    check("datas 目标正确",
          dests == {"ui", "App_PopPick/hmi/data"}, str(dests))
    check("入口脚本解析正确",
          str(Path(captured["scripts"][0]).name) == "main.py",
          str(captured["scripts"][0]))
except Exception as exc:
    check("spec 可执行", False, repr(exc))

# 资源目标推断：resource_manager 同级目录要摊平，其它保持层级
plot_ui = ROOT / "App_LogPlot/app/plot_moudle/ui"
tag_data = ROOT / "App_PopPick/hmi/data"
check("扫描识别摊平目标", w._suggest_dest(plot_ui) == "ui", w._suggest_dest(plot_ui))
check("扫描保持层级目标",
      w._suggest_dest(tag_data) == "App_PopPick/hmi/data",
      w._suggest_dest(tag_data))

# 依赖自检：本 venv 通过、缺 asyncua 的 venv 不通过
good = str(ROOT / ".venv/Scripts/python.exe")
bad = r"D:\rack\rack_config\.venv\Scripts\python.exe"
check("正确解释器自检通过", w._preflight(good)[0], w._preflight(good)[1])
if Path(bad).is_file():
    ok_bad, msg_bad = w._preflight(bad)
    check("错误解释器被拦下", not ok_bad and "asyncua" in msg_bad, msg_bad[:60])

# warn 扫描：拿上次事故留下的 warn 文件当样本
warn_dir = ROOT / "build" / "temp_工具集"
if warn_dir.is_dir():
    probe = ROOT / "build/temp_工具集.spec"
    t = PackagerThread(probe, ROOT, hidden_imports=["asyncua"])
    declared, others = t._scan_warn_files()
    check("warn 文件扫出缺失的隐藏导入", "asyncua" in declared,
          f"declared={declared[:5]} others={len(others)}")

print(f"\n===== 通过 {ok} 项，失败 {fail} 项 =====")
raise SystemExit(1 if fail else 0)
