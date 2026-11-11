"""为 graphify 社区生成可读中文标签（无需 LLM）。

策略：按社区成员的主要源码目录判定所属模块，再叠加社区内连接度最高的
1-2 个符号，形成 "模块 · 代表符号" 的标签；写入 .graphify_labels.json。
"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent
graph = json.loads((OUT / "graph.json").read_text(encoding="utf-8"))
nodes = graph["nodes"]
links = graph["links"]

# 模块前缀 -> 中文名（自长到短匹配，先具体后笼统）
MODULE_NAMES = [
    ("Designer/CoreQGraphics", "设计器·CoreQGraphics"),
    ("Designer/Core/ui", "设计器·UI窗口层"),
    ("Designer/Core", "设计器·核心图元场景"),
    ("Designer/", "设计器"),
    ("App_RackConfig/run", "料仓配置·运行层"),
    ("App_RackConfig", "料仓配置"),
    ("App_SafetyCar", "安全车"),
    ("App_PopPick_Motion_Editer", "PopPick·3D运动编辑"),
    ("App_PopPick/hmi", "PopPick·HMI界面"),
    ("App_PopPick", "PopPick"),
    ("App_LogPlot", "日志绘图"),
    ("common/com/modbus", "公共·Modbus通信"),
    ("common/com", "公共·通信层"),
    ("common/tool", "公共·工具控件"),
    ("common/", "公共组件"),
    ("tools/", "辅助脚本"),
    ("res/", "资源与UI模板"),
    ("packTool.py", "打包脚本"),
    ("main.py", "程序入口"),
]


def module_of(path: str) -> str:
    for prefix, name in MODULE_NAMES:
        if path.startswith(prefix):
            return name
    return "其他"


def short(sym: str) -> str:
    """压缩混淆/超长符号，保留可辨识部分。"""
    sym = re.sub(r"^_+", "", sym or "")
    return sym[:28]


# 由 AST 从 import 语句推断出的外部符号，不代表本项目结构
NOISE = {
    "os", "sys", "json", "re", "math", "time", "Path", "typing", "dataclasses",
    "QSizeF", "QPointF", "QRectF", "QColor", "QFont", "QTimer", "pyqtSignal",
    "pyside6_qtcore", "pyside6_qtwidgets", "pyside6_qtgui", "logging", "collections",
    "numpy", "pandas", "pathlib", "subprocess", "threading", "enum",
}


deg = Counter()
for e in links:
    deg[e["source"]] += 1
    deg[e["target"]] += 1

by_community = defaultdict(list)
for n in nodes:
    by_community[n.get("community")].append(n)

labels = {}
stats = {}
for cid, members in by_community.items():
    if cid is None:
        continue
    # 只拿有真实源文件的节点判断所属模块；导入占位节点（无 source_file）会污染统计
    real = [n for n in members if n.get("source_file")]
    pool = real or members
    mods = Counter(module_of(n.get("source_file") or "") for n in pool)
    mod, mod_n = mods.most_common(1)[0]
    share = mod_n / len(pool)

    ranked = sorted(pool, key=lambda n: deg[n["id"]], reverse=True)
    heads = []
    for n in ranked:
        lbl = short(n.get("label", ""))
        # 跳过导入的第三方/Qt 符号，它们不是本项目的抽象
        if not lbl or lbl in heads or lbl in NOISE:
            continue
        heads.append(lbl)
        if len(heads) == 2:
            break

    if share < 0.55:
        top2 = "/".join(m for m, _ in mods.most_common(2))
        name = f"跨模块·{top2}"
    else:
        name = mod
    if heads:
        name = f"{name} · {'/'.join(heads)}"
    labels[str(cid)] = name
    stats[str(cid)] = {"size": len(members), "module": mod, "share": round(share, 2)}

(OUT / ".graphify_labels.json").write_text(
    json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8"
)
(OUT / ".graphify_community_stats.json").write_text(
    json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"labels written: {len(labels)} communities")
for cid, name in sorted(labels.items(), key=lambda kv: -stats[kv[0]]["size"])[:15]:
    print(f"  C{cid:<4} n={stats[cid]['size']:<4} {name}")
