# -*- coding: utf-8 -*-
"""点位表（逻辑点位 → Modbus 寄存器）的导入 / 导出 / 冲突定位。

``fixture_config._reg(note=...)`` 里的 ``note`` 是给现场对表用的业务备注，
本模块把它变成一张能交给电气同事的表，并提供改完再导回来的闭环：

.. code-block:: bash

    # 导出（默认 CSV，Excel 直接打开；- 表示 stdout）
    .venv/Scripts/python.exe -m App_test_fixture.point_table \
        --export build/preview/point_table.csv
    .venv/Scripts/python.exe -m App_test_fixture.point_table \
        --export - --format word          # 按 PLC 字分组，最贴合现场对表
    .venv/Scripts/python.exe -m App_test_fixture.point_table \
        --export build/preview/point_table.md --format md

    # 导入（校验 / 看差异 / 生成可粘贴的配置片段）
    .venv/Scripts/python.exe -m App_test_fixture.point_table \
        --import point_table.csv --check
    .venv/Scripts/python.exe -m App_test_fixture.point_table \
        --import point_table.csv --diff
    .venv/Scripts/python.exe -m App_test_fixture.point_table \
        --import point_table.csv --overrides build/preview/overrides.py

    # 冲突定位（带 note，一眼看出是哪两个字撞了）
    .venv/Scripts/python.exe -m App_test_fixture.point_table --report

设计约束
========
* **只读**：不连设备、不改 ``MODBUS_REGISTER_MAP``、不写页面文件。
* **round-trip 无损**：导出的 CSV 再导入，还原出的 spec 与原表逐键相等。
  因此 ``4xxxx地址 / 协议地址 / 字宽 / 位掩码 / 冲突`` 都是派生列，
  导出给人看、导入时忽略；地址口径始终以 ``fixture_config`` 为准。
* **改动不自动落盘**：导入只给差异和 overrides 片段，由人确认后再粘进配置。
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import fixture_config as cfg
from . import modbus_link as ml

# ---------------------------------------------------------------- 表结构
# (内部键, CSV 表头, 是否派生列)。派生列导入时忽略。
COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("key", "点位名", False),
    ("offset", "字偏移", False),
    ("address", "4xxxx地址", True),
    ("protocol", "协议地址", True),
    ("type", "类型", False),
    ("width", "字宽", True),
    ("byte", "byte", False),
    ("bit", "bit", False),
    ("mask", "位掩码", True),
    ("access", "访问", False),
    ("scale", "比例", False),
    ("word_order", "字序", False),
    ("unit", "从站", False),
    ("words", "字数", False),
    ("note", "备注", False),
    ("conflict", "冲突", True),
)
HEADERS = tuple(c[1] for c in COLUMNS)
REQUIRED_HEADERS = ("点位名", "字偏移", "类型")

TYPES = frozenset({
    "bit", "bool", "byte", "uint16", "int16", "uint32", "int32",
    "float32", "double64", "string",
})
ACCESS = frozenset({"r", "w", "rw"})
WORD_ORDERS = frozenset({"big", "little"})


def _mask(spec: dict) -> tuple[str, str]:
    """返回 (位说明, 掩码十六进制)。非位类型返回空串。"""
    if spec.get("byte") is not None:
        m = ml._byte_bit(spec)
        return f"byte{int(spec['byte'])}", f"0x{m:04X}"
    if spec.get("bit") is not None:
        m = 1 << int(spec["bit"])
        return f"bit{int(spec['bit'])}", f"0x{m:04X}"
    return "", ""


def build_rows(register_map: dict | None = None, *,
               start: int | None = None,
               mode: str | None = None) -> list[dict]:
    """把 ``MODBUS_REGISTER_MAP`` 展平成按寄存器地址排序的表。

    每行既含原始 spec 字段（可无损还原），也含给人看的派生列
    （4xxxx 编号、pymodbus 协议地址、字宽、位掩码、冲突标记 + ``note``）。
    """
    rm = cfg.MODBUS_REGISTER_MAP if register_map is None else register_map
    base = int(cfg.MODBUS_START if start is None else start)
    bad = ml.overlap_conflicts(rm)
    bad_addresses = {base + a for a in bad}

    rows: list[dict] = []
    for key, spec in rm.items():
        off = int(spec["offset"])
        addr = base + off
        width = ml.width(spec)
        slot, mask = _mask(spec)
        hits = sorted(a for a in bad_addresses
                      if addr <= a < addr + width)
        rows.append({
            "key": key,
            "offset": off,
            "address": addr,
            "protocol": ml.protocol_address(off, start=base, mode=mode),
            "type": spec["type"],
            "width": width,
            "byte": "" if spec.get("byte") is None else int(spec["byte"]),
            "bit": "" if spec.get("bit") is None else int(spec["bit"]),
            "mask": f"{slot} {mask}".strip(),
            "access": str(spec.get("access", "r")),
            "scale": float(spec.get("scale", 1.0)),
            "word_order": str(spec.get("word_order", "")),
            "unit": int(spec.get("unit", cfg.MODBUS_UNIT)),
            "words": int(spec.get("words", 1)) if spec["type"] == "string" else "",
            "note": str(spec.get("note", "")),
            "conflict": ",".join(str(a) for a in hits),
        })
    def order(r: dict) -> tuple:
        # 同一个字里 byte0 在前、byte1 在后；非 byte 点位排在后面。
        b = r["byte"]
        return (r["offset"], 0 if b != "" else 1,
                int(b) if b != "" else 0, r["key"])

    rows.sort(key=order)
    return rows


# ---------------------------------------------------------------- 导出
def to_csv(rows: list[dict], *, bom: bool = False) -> str:
    """CSV 文本；``bom=True`` 供 Excel 直接双击打开不乱码。"""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(HEADERS)
    for r in rows:
        writer.writerow([r[k] for k, _, _ in COLUMNS])
    return ("\ufeff" if bom else "") + buf.getvalue()


def _md_cell(value: Any) -> str:
    s = "" if value is None else str(value)
    return s.replace("|", "\\|").replace("\n", " ") or "—"


def to_markdown(rows: list[dict], *, columns: tuple[str, ...] | None = None) -> str:
    """精简 Markdown 表，适合贴进文档 / 工单。"""
    cols = columns or ("address", "offset", "key", "type", "mask",
                       "access", "note", "conflict")
    label = {k: h for k, h, _ in COLUMNS}
    out = ["| " + " | ".join(label[c] for c in cols) + " |",
           "| " + " | ".join("---" for _ in cols) + " |"]
    for r in rows:
        out.append("| " + " | ".join(_md_cell(r[c]) for c in cols) + " |")
    return "\n".join(out)


def to_word_view(rows: list[dict]) -> str:
    """按 PLC 寄存器字分组的纯文本视图，现场拿着变量表逐字核对用。"""
    groups: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        groups[int(r["address"])].append(r)
    out: list[str] = []
    for addr in sorted(groups):
        entries = groups[addr]
        out.append(f"{addr}  (offset={entries[0]['offset']}, "
                   f"协议地址={entries[0]['protocol']})")
        for r in entries:
            span = (f"  占{r['width']}字 {r['address']}~{r['address'] + r['width'] - 1}"
                    if r["width"] > 1 else "")
            slot = r["mask"] or r["type"]
            note = f"  [{r['note']}]" if r["note"] else ""
            flag = f"  << 冲突 {r['conflict']}" if r["conflict"] else ""
            out.append(f"    {slot:<16} {r['key']}{span}{note}{flag}")
        out.append("")
    return "\n".join(out)


def export_text(rows: list[dict], fmt: str, *, bom: bool = False) -> str:
    if fmt == "csv":
        return to_csv(rows, bom=bom)
    if fmt == "md":
        return to_markdown(rows) + "\n"
    if fmt == "word":
        return to_word_view(rows)
    raise ValueError(f"未知导出格式：{fmt!r}（可选 csv / md / word）")


# ---------------------------------------------------------------- 导入
def parse_csv(text: str, *, strict: bool = False) -> tuple[list[dict], list[str]]:
    """解析导出的 CSV，返回 ``(rows, warnings)``；硬错误抛 ``ValueError``。

    校验类型、offset、byte/bit 范围、访问方向、字序、点位名白名单。
    派生列一律忽略，地址永远按 ``字偏移`` + 配置重算。
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff"), newline=""))
    headers = reader.fieldnames or []
    missing = [h for h in REQUIRED_HEADERS if h not in headers]
    if missing:
        raise ValueError(f"缺少必需列：{missing}")

    rows: list[dict] = []
    warnings: list[str] = []
    known = cfg.known_keys()
    seen: set[str] = set()
    for lineno, raw in enumerate(reader, start=2):
        key = (raw.get("点位名") or "").strip()
        if not key:
            continue
        if key in seen:
            raise ValueError(f"第 {lineno} 行点位名重复：{key}")
        seen.add(key)
        if key not in known:
            msg = f"第 {lineno} 行点位名不在 known_keys() 白名单：{key}"
            if strict:
                raise ValueError(msg)
            warnings.append(msg + "（会被 DataSource 过滤掉）")

        try:
            off = int(str(raw.get("字偏移") or "").strip())
        except ValueError as exc:
            raise ValueError(f"第 {lineno} 行字偏移不是整数：{raw.get('字偏移')!r}") from exc
        if off < 0:
            raise ValueError(f"第 {lineno} 行字偏移为负：{off}")

        kind = (raw.get("类型") or "").strip()
        if kind not in TYPES:
            raise ValueError(f"第 {lineno} 行未知类型：{kind!r}")

        def opt_int(col: str) -> str:
            v = (raw.get(col) or "").strip()
            return "" if v in ("", "—", "-") else v

        byte, bit = opt_int("byte"), opt_int("bit")
        if byte and (kind != "byte" or int(byte) not in (0, 1)):
            raise ValueError(f"第 {lineno} 行 byte 必须是 byte 类型的 0/1，得到 {byte!r}")
        if bit and (kind != "bit" or not 0 <= int(bit) <= 15):
            raise ValueError(f"第 {lineno} 行 bit 必须是 bit 类型的 0..15，得到 {bit!r}")
        if kind == "byte" and not byte:
            raise ValueError(f"第 {lineno} 行 byte 类型必须指定 byte=0/1")
        if kind == "bit" and not bit:
            raise ValueError(f"第 {lineno} 行 bit 类型必须指定 bit")

        access = (raw.get("访问") or "r").strip()
        if access not in ACCESS:
            raise ValueError(f"第 {lineno} 行 access 必须是 r/w/rw：{access!r}")
        order = (raw.get("字序") or "").strip()
        if order and order not in WORD_ORDERS:
            raise ValueError(f"第 {lineno} 行字序必须是 big/little：{order!r}")

        try:
            scale = float((raw.get("比例") or "1").strip() or "1")
            unit = int(raw.get("从站") or cfg.MODBUS_UNIT)
        except ValueError as exc:
            raise ValueError(f"第 {lineno} 行比例/从站不是数字") from exc
        words = opt_int("字数") if kind == "string" else ""

        rows.append({
            "key": key, "offset": off, "type": kind,
            "byte": int(byte) if byte else "", "bit": int(bit) if bit else "",
            "access": access, "scale": scale, "word_order": order,
            "unit": unit, "words": int(words) if words else "",
            "note": (raw.get("备注") or "").strip(),
        })

    if not rows:
        raise ValueError("表里没有任何点位")
    return rows, warnings


def import_csv(path: str | Path, *, strict: bool = False) -> tuple[list[dict], list[str]]:
    return parse_csv(Path(path).read_text(encoding="utf-8-sig"), strict=strict)


def to_register_map(rows: list[dict]) -> dict[str, dict]:
    """导入的表 → ``MODBUS_REGISTER_MAP`` 形状，可直接交给 ``ModbusDataSource``。"""
    out: dict[str, dict] = {}
    for r in rows:
        spec: dict[str, Any] = {
            "offset": int(r["offset"]), "type": r["type"],
            "scale": float(r.get("scale", 1.0)),
            "unit": int(r.get("unit", cfg.MODBUS_UNIT)),
            "access": r.get("access", "r"),
        }
        if r.get("byte") not in ("", None):
            spec["byte"] = int(r["byte"])
        if r.get("bit") not in ("", None):
            spec["bit"] = int(r["bit"])
        if r.get("words") not in ("", None):
            spec["words"] = int(r["words"])
        if r.get("word_order"):
            spec["word_order"] = r["word_order"]
        if r.get("note"):
            spec["note"] = r["note"]
        out[r["key"]] = spec
    return out


def diff_table(rows: list[dict], base: dict | None = None) -> dict:
    """导入表 vs 当前配置的差异，供人工确认后再落到配置。"""
    cur = cfg.MODBUS_REGISTER_MAP if base is None else base
    new = to_register_map(rows)
    added = {k: v for k, v in new.items() if k not in cur}
    removed = [k for k in cur if k not in new]
    changed: dict[str, dict] = {}
    for k, v in new.items():
        if k not in cur or cur[k] == v:
            continue
        patch = {f: val for f, val in v.items() if cur[k].get(f) != val}
        cleared = [f for f in cur[k] if f not in v]
        changed[k] = {"before": cur[k], "after": v,
                      "patch": patch, "cleared": cleared}
    return {"added": added, "removed": removed, "changed": changed}


def as_overrides(diff: dict) -> str:
    """生成可粘贴进 ``fixture_config.py`` 的 ``MODBUS_REGISTER_OVERRIDES``。"""
    lines = [
        "# 由 point_table.py 生成；确认后再粘进 fixture_config.py",
        "# 注意：overrides 用 dict.update 语义，只能新增/覆盖，无法表达删除。",
        "MODBUS_REGISTER_OVERRIDES = {",
    ]
    for k, v in sorted(diff["added"].items()):
        lines.append(f"    {k!r}: {v!r},")
    for k, d in sorted(diff["changed"].items()):
        lines.append(f"    {k!r}: {d['patch']!r},")
    lines.append("}")
    if diff["removed"]:
        lines.append("")
        lines.append("# 以下点位在导入表中被删除，overrides 无法表达，需手工从 "
                     "_build_register_map() 移除：")
        for k in diff["removed"]:
            lines.append(f"#   {k}")
    for k, d in sorted(diff["changed"].items()):
        if d["cleared"]:
            lines.append(f"# 注意：{k} 删除了字段 {d['cleared']}，"
                         "overrides 无法删除字段，需手工清理")
    return "\n".join(lines) + "\n"


def describe_diff(diff: dict) -> str:
    out = [f"新增 {len(diff['added'])} / 删除 {len(diff['removed'])} / 修改 {len(diff['changed'])}"]
    for k, d in sorted(diff["changed"].items()):
        out.append(f"  ~ {k}: {d['patch']}")
    for k in sorted(diff["added"]):
        out.append(f"  + {k}")
    for k in sorted(diff["removed"]):
        out.append(f"  - {k}")
    return "\n".join(out)


# ---------------------------------------------------------------- 冲突定位（note 的真正用途）
def conflict_report(register_map: dict | None = None) -> str:
    """重叠 / 心跳冲突报告，带上 note，现场一眼看出是哪两个字撞了。"""
    rm = cfg.MODBUS_REGISTER_MAP if register_map is None else register_map
    base = int(cfg.MODBUS_START)
    notes = {k: str(v.get("note", "")) for k, v in rm.items()}
    out: list[str] = []
    bad = ml.overlap_conflicts(rm)
    out.append(f"点位表冲突报告：{len(bad)} 个寄存器重叠")
    for addr, keys in bad.items():
        out.append(f"  {base + addr}  (offset={addr})  "
                   + ", ".join(k.split(".")[-1] for k in keys))
        involved = sorted({notes[k] for k in keys if notes.get(k)})
        out.append("      涉及字：" + (", ".join(involved) if involved else "（无备注）"))
    beats = ml.heartbeat_conflicts(rm)
    if beats:
        out.append("")
        out.append("PLCManager 心跳写入协议地址 1000，以下点位会被周期覆盖：")
        for k, a in beats:
            out.append(f"  {k}  @ 协议地址 {a}  [{notes.get(k, '')}]")
    else:
        out.append("")
        out.append("PLCManager 心跳地址 1000：无冲突")
    return "\n".join(out)


# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="App_test_fixture 点位表导入 / 导出（只读，不连设备）")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--export", metavar="PATH", help="导出到文件；- 表示 stdout")
    action.add_argument("--import", dest="import_path", metavar="PATH", help="导入 CSV")
    action.add_argument("--report", action="store_true", help="打印带 note 的冲突报告")
    parser.add_argument("--format", choices=("csv", "md", "word"), default=None,
                        help="导出格式，默认按扩展名推断（.md→md，其余→csv）")
    parser.add_argument("--check", action="store_true", help="导入时只做校验")
    parser.add_argument("--diff", action="store_true", help="导入时打印差异")
    parser.add_argument("--overrides", metavar="PATH",
                         help="导入时生成可粘贴的 overrides 片段")
    parser.add_argument("--strict", action="store_true",
                        help="导入时点位名必须在 known_keys() 白名单内")
    args = parser.parse_args(argv)

    try:
        if args.report:
            print(conflict_report())
            return 0

        if args.export:
            fmt = args.format
            if fmt is None:
                fmt = "md" if args.export.lower().endswith(".md") else "csv"
            rows = build_rows()
            text = export_text(rows, fmt, bom=(fmt == "csv" and args.export != "-"))
            if args.export == "-":
                sys.stdout.write(text)
            else:
                p = Path(args.export)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
                print(f"已导出 {len(rows)} 个点位 → {p}  ({fmt})")
            return 0

        # 导入
        rows, warns = import_csv(args.import_path, strict=args.strict)
        bad = ml.overlap_conflicts(to_register_map(rows))
        print(f"导入校验通过：{len(rows)} 个点位，{len(bad)} 个重叠寄存器")
        for w in warns:
            print("  [warn] " + w)
        delta = diff_table(rows)
        if args.diff or not (args.check or args.overrides):
            print(describe_diff(delta))
        if args.overrides:
            p = Path(args.overrides)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(as_overrides(delta), encoding="utf-8")
            print(f"已生成 overrides 片段 → {p}")
        if bad:
            print(f"  [warn] 导入表仍有 {len(bad)} 个重叠："
                  + ", ".join(str(int(cfg.MODBUS_START) + a) for a in bad))
        return 0
    except (ValueError, OSError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
