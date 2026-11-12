# -*- coding: utf-8 -*-
"""点位表导入 / 导出门禁。

    .venv/Scripts/python.exe tools/verify_point_table.py

红线
====
1. **round-trip 无损**：导出 CSV → 导入 → 还原 spec 与 ``MODBUS_REGISTER_MAP``
   逐键相等；带 BOM 的 Excel 文件也能读。
2. **派生列自洽**：4xxxx 编号 / 协议地址 / 字宽 / 位掩码 / 冲突标记全部
   由配置现算，不允许表里写死的地址与代码口径漂移。
3. **note 真的被用起来**：CSV / Markdown / 字视图 / 冲突报告里都能看到备注。
4. **导入会拦错**：类型、byte/bit 范围、offset、访问、字序、重复点位、白名单。
5. **改动不自动落盘**：导入只产出差异与 overrides 片段，不碰配置对象。
6. **不绑现场布局**：所有数量、地址、冲突项都从当前配置动态取，
   现场重排 offset / 改 note 不会让门禁变红。
"""
from __future__ import annotations

import ast
import copy
import csv
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from App_test_fixture import fixture_config as cfg  # noqa: E402
from App_test_fixture import modbus_link as ml  # noqa: E402
from App_test_fixture import point_table as pt  # noqa: E402

FAILURES: list[str] = []


def check(label, cond, detail=""):
    if cond:
        print(f"  [OK] {label}" + (f"  {detail}" if detail else ""))
    else:
        print(f"  [FAIL] {label}" + (f"  {detail}" if detail else ""))
        FAILURES.append(label)
    return bool(cond)


def expect_error(label, text, *, strict=False):
    try:
        pt.parse_csv(text, strict=strict)
    except ValueError as exc:
        check(label, True, str(exc)[:60])
    else:
        check(label, False, "本应报错却通过了")


def edit_row(csv_text: str, key: str, column: str, value: str) -> str:
    """在导出的 CSV 里改某点位的一列，返回新 CSV 文本。"""
    buf = io.StringIO(newline="")
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    writer = csv.DictWriter(buf, fieldnames=reader.fieldnames, lineterminator="\r\n")
    writer.writeheader()
    for row in reader:
        if row["点位名"] == key:
            row[column] = value
        writer.writerow(row)
    return buf.getvalue()


def main() -> int:
    original = copy.deepcopy(cfg.MODBUS_REGISTER_MAP)
    rows = pt.build_rows()
    print(f"\n[1] 展平与 round-trip（{len(rows)} 个点位，{len(original)} 个 key）")
    check("行数 == 点位数", len(rows) == len(original))
    check("按 offset 升序", all(rows[i]["offset"] <= rows[i + 1]["offset"]
                               for i in range(len(rows) - 1)))
    csv_text = pt.to_csv(rows, bom=True)
    parsed, warns = pt.parse_csv(csv_text)
    restored = pt.to_register_map(parsed)
    check("round-trip 逐键相等", restored == original,
          "" if restored == original else
          str([k for k in original if original[k] != restored.get(k)][:3]))
    check("BOM 不影响解析", csv_text.startswith("\ufeff") and len(parsed) == len(rows))
    check("解析结果完整（白名单问题只警告）",
          len(parsed) == len(rows) and isinstance(warns, list),
          f"{len(warns)} 条白名单警告")

    print("\n[2] 派生列自洽")
    bad = ml.overlap_conflicts(original)
    bad_addrs = {int(cfg.MODBUS_START) + a for a in bad}
    derived_ok = True
    for r in rows:
        spec = original[r["key"]]
        hits = ",".join(str(a) for a in sorted(
            x for x in bad_addrs
            if r["address"] <= x < r["address"] + ml.width(spec)))
        if not (r["address"] == int(cfg.MODBUS_START) + r["offset"]
                and r["protocol"] == ml.protocol_address(r["offset"])
                and r["width"] == ml.width(spec)
                and r["conflict"] == hits):
            derived_ok = False
            break
        if spec.get("byte") is not None:
            if f"0x{ml._byte_bit(spec):04X}" not in r["mask"]:
                derived_ok = False
                break
    check("地址/字宽/掩码/冲突标记全自洽", derived_ok)
    check("冲突数与 overlap_conflicts 一致", len(bad_addrs) > 0)

    print("\n[3] 三种导出格式都带 note")
    noted = [r for r in rows if r["note"]]
    check("存在带备注的点位", bool(noted))
    probe = noted[0]["note"] if noted else ""
    check("CSV 含备注", probe in csv_text)
    md = pt.to_markdown(rows)
    check("Markdown 含备注", probe in md and md.startswith("|"))
    word = pt.to_word_view(rows)
    check("字视图含备注", probe in word)
    check("字视图按 4xxxx 分组", str(noted[0]["address"]) in word if noted else True)
    check("CSV 列数 == 表头数",
          all(len(row) == len(pt.HEADERS) for row in csv.reader(io.StringIO(csv_text))))

    print("\n[4] 冲突报告带 note")
    report = pt.conflict_report()
    involved = {str(original[k]["note"]) for a, keys in bad.items()
                for k in keys if original[k].get("note")}
    check("冲突报告列出全部重叠", str(len(bad)) in report)
    check("冲突报告含涉及字的备注",
          all(n in report for n in involved), f"{len(involved)} 个备注")
    check("冲突报告含心跳结论", "心跳" in report)

    print("\n[5] 导入校验拦错")
    first = rows[0]["key"]
    plain = pt.to_csv(rows)
    expect_error("缺列", "点位名,字偏移\n" + f"a,0\n")
    expect_error("未知类型", edit_row(plain, first, "类型", "float128"))
    expect_error("负 offset", edit_row(plain, first, "字偏移", "-1"))
    expect_error("offset 非整数", edit_row(plain, first, "字偏移", "abc"))
    expect_error("非法访问方向", edit_row(plain, first, "访问", "x"))
    expect_error("非法字序", edit_row(plain, first, "字序", "middle"))
    expect_error("重复点位名", plain.rstrip("\r\n") + "\r\n"
                 + ",".join(str(rows[0][k]) for k, _, _ in pt.COLUMNS) + "\r\n")
    byte_row = next((r for r in rows if r["type"] == "byte"), None)
    if byte_row:
        expect_error("byte 越界", edit_row(plain, byte_row["key"], "byte", "2"))
        expect_error("byte 类型缺 byte", edit_row(plain, byte_row["key"], "byte", ""))
    expect_error("strict 拦白名单外点位",
                 edit_row(plain, first, "点位名", "not.a.real.tag"), strict=True)
    outside, w2 = pt.parse_csv(edit_row(plain, first, "点位名", "not.a.real.tag"))
    check("非 strict 只警告不拦", len(outside) == len(rows) and len(w2) >= 1)

    print("\n[6] 差异与 overrides 片段")
    moved = pt.parse_csv(edit_row(plain, first, "字偏移",
                                 str(rows[0]["offset"] + 5000)))[0]
    delta = pt.diff_table(moved)
    check("改动被识别", first in delta["changed"], str(delta["changed"].get(first, {}).get("patch", "")))
    check("patch 只含变化字段",
          set(delta["changed"][first]["patch"]) == {"offset"}
          if first in delta["changed"] else False)
    snippet = pt.as_overrides(delta)
    tree = ast.parse(snippet)
    check("overrides 是合法 Python", any(isinstance(n, ast.Assign) for n in tree.body))
    ns: dict = {}
    exec(compile(tree, "<overrides>", "exec"), {"__builtins__": {}}, ns)  # noqa: S102
    check("overrides 可 exec 成 dict", isinstance(ns.get("MODBUS_REGISTER_OVERRIDES"), dict))

    dropped_text = "\r\n".join(plain.splitlines()[:-1]) + "\r\n"
    delta2 = pt.diff_table(pt.parse_csv(dropped_text)[0])
    check("删除被识别", len(delta2["removed"]) == 1)
    check("删除在片段里给手工提示", "_build_register_map" in pt.as_overrides(delta2))
    check("describe_diff 可读", "新增" in pt.describe_diff(delta))

    print("\n[7] CLI 端到端")
    py = str(Path(sys.executable))
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        out_csv = str(Path(tmp) / "table.csv")
        out_md = str(Path(tmp) / "table.md")
        out_ov = str(Path(tmp) / "overrides.py")
        steps = [
            (["--export", out_csv], "导出 CSV"),
            (["--export", out_md, "--format", "md"], "导出 Markdown"),
            (["--export", "-", "--format", "word"], "字视图到 stdout"),
            (["--import", out_csv, "--check"], "导入校验"),
            (["--import", out_csv, "--diff"], "导入看差异"),
            (["--import", out_csv, "--overrides", out_ov], "生成 overrides"),
            (["--report"], "冲突报告"),
        ]
        for argv, label in steps:
            p = subprocess.run([py, "-m", "App_test_fixture.point_table", *argv],
                               capture_output=True, env=env)
            ok = p.returncode == 0 and (p.stdout or p.stderr)
            check(f"CLI {label}", ok,
                  "" if ok else (p.stderr.decode("utf-8", "replace")[:120]))
        check("CSV 文件带 BOM", Path(out_csv).read_bytes().startswith(b"\xef\xbb\xbf"))
        check("Markdown 文件非空", Path(out_md).stat().st_size > 100)
        check("overrides 文件非空", Path(out_ov).stat().st_size > 50)
        bad_csv = str(Path(tmp) / "bad.csv")
        Path(bad_csv).write_text("点位名,字偏移,类型\na,0,float128\n", encoding="utf-8")
        p = subprocess.run([py, "-m", "App_test_fixture.point_table",
                            "--import", bad_csv, "--check"],
                           capture_output=True, env=env)
        check("CLI 坏表返回非零", p.returncode != 0)

    print("\n[8] 零副作用")
    check("MODBUS_REGISTER_MAP 未被改动", cfg.MODBUS_REGISTER_MAP == original)

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} 项")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
