"""从 PLCopen XML 变量表生成 PopPick HMI 页面的数据目录。

输入（都不修改）：

* ``AM521_PopPick_V2.0.0(sim).xml`` —— InoProShop 导出的工程，取其中
  ``GVL`` / ``GVL_HMI`` / ``GVL_PARAMETERS`` 三张全局变量表（顶层
  ``<globalVars>``，父节点是 ``<data>``）。嵌套在 ``addData`` 里的同名段是
  按属性拆分的副本，不重复计入；
* ``globalvars_tags.json`` —— 用 ``tools/opcua_browse.py`` 从真机浏览导出的
  ``{key: NodeId}``，是**已验证**的节点；
* ``globalvars_structure.json`` —— 同一次浏览的树，用来把结构体/数组变量
  和它展开出来的成员节点对应起来（成员 key 常常不带父名前缀，光靠字符串
  前缀匹配会漏掉 CameraDatas 这类）。

输出：

* ``App_PopPick/hmi/data/gvl_catalog.json`` —— 变量元数据（类型、数组维度、
  注释分组、常量初值），页面上的中文标签和分组都从这里来；
* ``App_PopPick/hmi/data/opcua_nodes.json`` —— 已验证节点、按命名规则推断的
  **候选**节点、以及 ``变量名 -> 成员 key`` 索引。

候选节点是推断、不是事实：真机地址空间里目前只暴露了 ``GVL_HMI`` 与
``GVL_PARAMETERS``（见 structure.json 的 children），``GVL`` 本体没有节点。
所以 ``GVL.*`` 一律标 ``verified=false``，运行时只显示「未接入」，不订阅、
不写入。要接通请先重新浏览导出节点清单，再跑一次本脚本。

跑法::

    .venv/Scripts/python.exe tools/gen_hmi_tag_catalog.py
    .venv/Scripts/python.exe tools/gen_hmi_tag_catalog.py --xml <路径> --outdir <目录>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.opcua_json import clean_text, dump_json, restore_escaped  # noqa: E402

NS = "{http://www.plcopen.org/xml/tc6_0200}"
DEFAULT_XML = Path("C:/Users/GPD/Desktop/AM521_PopPick_V2.0.0(sim).xml")
TABLES = ("GVL_HMI", "GVL", "GVL_PARAMETERS")

#: 变量注释里的分节标记，形如 ``**********Servos**********``。
#: 导出文件用这种标记给变量分组，正好拿来划页面区块。
_SECTION = re.compile(r"\*{3,}\s*(.+?)\s*\*{3,}")
#: 表达式里出现的常量引用，如 ``(GVL.MAX_STORAGE_ROW - 1)``
_CONST_REF = re.compile(r"\b(?:GVL|GVL_HMI|GVL_PARAMETERS)\.([A-Za-z_]\w*)")
_SAFE_EXPR = re.compile(r"^[\d\s+\-*/().]+$")


def lname(node) -> str:
    return node.tag.replace(NS, "")


def read_constants(root) -> dict[str, int]:
    """取 ``GVL`` 的 constant 段初值，用来把数组维度表达式算成数字。"""
    out: dict[str, int] = {}
    for gv in root.iter(NS + "globalVars"):
        if gv.get("name") != "GVL" or gv.get("constant") != "true":
            continue
        for var in gv.findall(NS + "variable"):
            init = var.find(NS + "initialValue")
            simple = init.find(NS + "simpleValue") if init is not None else None
            if simple is None:
                continue
            try:
                out[var.get("name", "")] = int(simple.get("value", ""), 0)
            except ValueError:
                pass
    return out


def dimension(expr: str, constants: dict[str, int]):
    """把维度上界表达式算成 ``int``；算不出就保留原文并置 ``None``。"""
    if not expr:
        return None, ""
    try:
        return int(expr, 0), expr
    except ValueError:
        pass
    substituted = _CONST_REF.sub(lambda m: str(constants.get(m.group(1), 0)), expr)
    if _SAFE_EXPR.match(substituted):
        try:
            return int(eval(substituted, {"__builtins__": {}}, {})), expr  # noqa: S307 - 已做字符集白名单
        except Exception:  # noqa: BLE001
            pass
    return None, expr


def parse_type(type_node, constants: dict[str, int]) -> tuple[str, list[dict]]:
    """返回 ``(元素类型, 维度列表)``；维度含 lower/upper/原文。"""
    if type_node is None:
        return "?", []
    for child in type_node:
        tag = lname(child)
        if tag == "derived":
            return str(child.get("name", "?")), []
        if tag == "array":
            dims = []
            for d in child.findall(NS + "dimension"):
                lower, _ = dimension(d.get("lower", "0"), constants)
                upper, raw = dimension(d.get("upper", ""), constants)
                dims.append({"lower": lower or 0, "upper": upper, "raw": raw})
            inner = child.find(NS + "type")
            base, _ = parse_type(inner, constants)
            return base, dims
        return tag.upper(), []
    return "?", []


def documentation(var) -> str:
    node = var.find(NS + "documentation")
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def parse_tables(xml_path: Path) -> dict[str, list[dict]]:
    root = ET.parse(xml_path).getroot()
    parents = {child: parent for parent in root.iter() for child in parent}
    constants = read_constants(root)
    tables: dict[str, list[dict]] = {}
    for table in TABLES:
        matches = [
            gv for gv in root.iter(NS + "globalVars")
            if gv.get("name") == table
            and parents.get(gv) is not None
            and lname(parents[gv]) == "data"
        ]
        if not matches:
            raise ValueError(f"{xml_path.name} 里找不到顶层 <globalVars name=\"{table}\">")
        section = ""
        rows = []
        for var in matches[0].findall(NS + "variable"):
            doc = documentation(var)
            hit = _SECTION.search(doc)
            if hit:
                section = hit.group(1).strip()
                doc = ""
            base, dims = parse_type(var.find(NS + "type"), constants)
            rows.append({
                "table": table,
                "name": var.get("name", ""),
                "type": base,
                "dimensions": dims,
                "group": section,
                "comment": doc,
            })
        tables[table] = rows
    return tables


def _clean(name: str) -> str:
    """浏览树里的名字可能带 GBK 代理字符；显示层统一还原。"""
    return clean_text(restore_escaped(name))


def collect_members(node: dict, prefix: str = "") -> list[tuple[str, str, str]]:
    """递归收集 ``(成员路径, 变量名, NodeId)``。

    数组元素节点名自带下标（``Alarms2HMII[0]``），把它保留在路径里，
    运行时才能按 ``[1].fPositionNow`` 精确取到某个轴的字段。
    """
    out: list[tuple[str, str, str]] = []
    for child in node.get("children") or []:
        name = _clean(child.get("name", ""))
        nid = restore_escaped(child.get("node_id", ""))
        path = f"{prefix}.{name}" if prefix else name
        if child.get("children"):
            out.extend(collect_members(child, path))
        elif nid:
            out.append((path, name, nid))
    return out


def build_structure_index(struct_path: Path) -> dict[str, dict]:
    """``{表名.变量名: {成员路径: NodeId}}``，同时记录整体节点与可写性。"""
    data = json.loads(struct_path.read_text(encoding="utf-8"))
    index: dict[str, dict] = {}
    for table_node in data.get("children") or []:
        table = _clean(table_node.get("name", ""))
        for var in table_node.get("children") or []:
            name = _clean(var.get("name", ""))
            node_id = restore_escaped(var.get("node_id", ""))
            members = {}
            for path, _member_name, nid in collect_members(var):
                members[path] = nid
            index[f"{table}.{name}"] = {
                "node_id": node_id,
                "writable": bool(var.get("writable")),
                "members": members,
            }
    return index


def norm_key(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", name.lower())


def loose_key(name: str) -> str:
    return re.sub(r"[^0-9a-z_]+", "", name.lower()).strip("_")


def build(tables, tags_path: Path, struct_path: Path) -> tuple[dict, dict]:
    tags_raw = json.loads(tags_path.read_text(encoding="utf-8"))
    endpoint = tags_raw.get("endpoint", "")
    verified = {k: restore_escaped(v) for k, v in (tags_raw.get("nodes") or {}).items()}
    by_node_id: dict[str, str] = {}
    for key, nid in verified.items():
        by_node_id.setdefault(nid, key)

    # 从 NodeId 里抽出设备/应用前缀，供 GVL 候选节点按同一规则拼装
    sample = next(iter(verified.values()), "")
    prefix = sample.rsplit(".", 1)[0] if sample else ""
    prefix = re.sub(r"\.(GVL_HMI|GVL_PARAMETERS)$", "", prefix)

    struct = build_structure_index(struct_path) if struct_path.is_file() else {}
    aliases: dict[str, dict] = {}
    candidates: dict[str, str] = {}

    for table, rows in tables.items():
        for row in rows:
            alias = f"{table}.{row['name']}"
            info = struct.get(alias, {})
            node_id = info.get("node_id", "")
            main_key = by_node_id.get(node_id)

            # 变量在导出清单里可能被写成短名，补一次按名字的直接匹配。
            # 必须核对 NodeId 里的表名：GVL 和 GVL_HMI 有同名变量
            # （HoldResisterIn / sucker_ret_pos …），光按短名匹配会把
            # GVL_HMI 的节点错记到 GVL 名下，页面就会读到另一个变量的值。
            if main_key is None:
                for cand in (loose_key(row["name"]), norm_key(row["name"])):
                    nid = verified.get(cand, "")
                    if cand in verified and f".{table}." in nid:
                        main_key = cand
                        node_id = nid
                        break

            # 结构体/数组展开出来的成员，按 NodeId 反查业务 key
            members: dict[str, str] = {}
            for path, nid in info.get("members", {}).items():
                key = by_node_id.get(nid)
                if key and not path.endswith((".Dimensions", ".IndexMin", ".IndexMax")):
                    members[path] = key
            if not members:
                for prefix_key in (loose_key(row["name"]), norm_key(row["name"])):
                    found = {
                        k[len(prefix_key) + 1:]: k
                        for k in verified
                        if k.startswith(prefix_key + "_")
                        and not k.endswith(("_dimensions", "_indexmin", "_indexmax"))
                    }
                    if found:
                        members = found
                        break

            is_verified = bool(main_key or members)
            if not is_verified:
                # 推断：按已验证节点的命名空间/前缀拼一个候选 NodeId。
                # 未在地址空间里核实，运行时只显示「未接入」。
                cand_key = loose_key(f"{table}_{row['name']}")
                candidates[cand_key] = f"{prefix}.{table}.{row['name']}"

            shape = [
                d["upper"] - d["lower"] + 1 if d["upper"] is not None else None
                for d in row["dimensions"]
            ]
            aliases[alias] = {
                "table": table,
                "name": row["name"],
                "type": row["type"],
                "group": row["group"],
                "comment": row["comment"],
                "dimensions": row["dimensions"],
                "shape": shape,
                "key": main_key,
                "node_id": node_id or None,
                "members": members,
                "writable": bool(info.get("writable", True)),
                "verified": is_verified,
                "candidate_key": None if is_verified else loose_key(f"{table}_{row['name']}"),
            }

    catalog = {
        "source_xml": None,  # main() 里填入实际文件名
        "source": {
            "variable_tables": "PLCopen XML (InoProShop), 顶层 <globalVars> 段",
            "tables": {t: len(rows) for t, rows in tables.items()},
            "sections": sorted({r["group"] for rows in tables.values() for r in rows if r["group"]}),
        },
        "variables": {table: rows for table, rows in tables.items()},
    }
    nodes = {
        "endpoint": endpoint,
        "node_prefix": prefix,
        "source_tags": tags_path.name,
        "source_structure": struct_path.name,
        "verified_count": len(verified),
        "candidate_count": len(candidates),
        "verified": verified,
        "candidates": candidates,
        "aliases": aliases,
    }
    return catalog, nodes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xml", type=Path, default=DEFAULT_XML)
    ap.add_argument("--tags", type=Path, default=ROOT / "globalvars_tags.json")
    ap.add_argument("--structure", type=Path, default=ROOT / "globalvars_structure.json")
    ap.add_argument("--outdir", type=Path, default=ROOT / "App_PopPick/hmi/data")
    args = ap.parse_args()

    if not args.xml.is_file():
        raise SystemExit(f"变量表不存在: {args.xml}")
    if not args.tags.is_file():
        raise SystemExit(f"节点映射不存在: {args.tags}（先用 tools/opcua_browse.py 导出）")

    tables = parse_tables(args.xml)
    catalog, nodes = build(tables, args.tags, args.structure)
    catalog["source_xml"] = args.xml.name

    args.outdir.mkdir(parents=True, exist_ok=True)
    catalog_path = args.outdir / "gvl_catalog.json"
    nodes_path = args.outdir / "opcua_nodes.json"
    dump_json(catalog_path, catalog)
    dump_json(nodes_path, nodes)

    total = sum(len(rows) for rows in tables.values())
    verified_aliases = sum(1 for a in nodes["aliases"].values() if a["verified"])
    print(f"变量表: {', '.join(f'{t}={len(r)}' for t, r in tables.items())}，合计 {total}")
    print(f"已验证节点: {nodes['verified_count']} 个；变量可解析: {verified_aliases}/{len(nodes['aliases'])}")
    print(f"推断候选（未暴露）: {nodes['candidate_count']} 个")
    print(f"写出: {catalog_path}")
    print(f"写出: {nodes_path}")
    missing = [k for k, a in nodes["aliases"].items() if not a["verified"] and a["table"] == "GVL_HMI"]
    if missing:
        print("GVL_HMI 里未匹配到节点的变量:", ", ".join(missing[:20]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
