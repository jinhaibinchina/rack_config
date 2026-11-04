"""统计并校验 Designer/Core 下各模块的类型注解覆盖情况。

用法（项目 .venv）：
    .venv/Scripts/python.exe tools/check_type_annotations.py
    .venv/Scripts/python.exe tools/check_type_annotations.py --resolve

默认只做 AST 静态统计 + py_compile 语法检查；
加 --resolve 会真正 import 模块并对每个函数调用 typing.get_type_hints()，
用来抓「注解里写了未导入/拼错的类型名」这类静态检查看不出来的问题。
"""

from __future__ import annotations

import argparse
import ast
import importlib
import os
import py_compile
import sys
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "Designer" / "Core"

SKIP_NAMES = {"self", "cls"}


def iter_functions(tree: ast.AST):
    """遍历模块内所有函数（含嵌套函数与方法）。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def module_stats(path: Path) -> dict:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    funcs = [f for f in iter_functions(tree) if not f.name.startswith("__")]
    total = len(funcs)
    ret = sum(1 for f in funcs if f.returns is not None)
    args_full = 0
    args_total = 0
    for f in funcs:
        a = f.args
        params = list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
        for extra in (a.vararg, a.kwarg):
            if extra is not None:
                params.append(extra)
        params = [p for p in params if p.arg not in SKIP_NAMES]
        args_total += len(params)
        args_full += sum(1 for p in params if p.annotation is not None)
    return {
        "file": path.name,
        "funcs": total,
        "ret": ret,
        "args_total": args_total,
        "args_ann": args_full,
    }


def compile_all(files: list[Path]) -> list[str]:
    errors = []
    for f in files:
        try:
            src = f.read_text(encoding="utf-8")
            compile(src, str(f), "exec")
        except SyntaxError as exc:
            errors.append(f"{f.name}:{exc.lineno}: {exc.msg}")
    return errors


def resolve_hints(files: list[Path]) -> list[str]:
    """导入模块并解析每个函数的类型注解，返回无法求值的注解。"""
    sys.path.insert(0, str(ROOT))
    problems = []
    for f in files:
        mod_name = f"Designer.Core.{f.stem}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001 - 需要把导入失败原样报出来
            problems.append(f"{f.name}: import failed -> {exc!r}")
            continue
        targets = []
        for name, obj in vars(mod).items():
            if isinstance(obj, type) and getattr(obj, "__module__", None) == mod_name:
                for meth_name, meth in vars(obj).items():
                    fn = meth.__func__ if isinstance(meth, (staticmethod, classmethod)) else meth
                    if callable(fn) and getattr(fn, "__module__", None) == mod_name:
                        targets.append(fn)
            elif callable(obj) and getattr(obj, "__module__", None) == mod_name:
                targets.append(obj)
        for fn in targets:
            try:
                typing.get_type_hints(fn)
            except Exception as exc:  # noqa: BLE001
                problems.append(
                    f"{f.name}: {getattr(fn, '__qualname__', fn)} -> {type(exc).__name__}: {exc}"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolve", action="store_true", help="导入模块并解析注解")
    args = parser.parse_args()

    files = sorted(p for p in CORE.glob("*.py"))
    rows = [module_stats(p) for p in files]

    print(f"{'file':<32}{'funcs':>7}{'ret':>6}{'ret%':>7}{'args':>7}{'arg%':>7}")
    print("-" * 66)
    t_funcs = t_ret = t_args = t_args_ann = 0
    for r in rows:
        ret_pct = 100.0 * r["ret"] / r["funcs"] if r["funcs"] else 100.0
        arg_pct = 100.0 * r["args_ann"] / r["args_total"] if r["args_total"] else 100.0
        print(
            f"{r['file']:<32}{r['funcs']:>7}{r['ret']:>6}{ret_pct:>6.0f}%"
            f"{r['args_total']:>7}{arg_pct:>6.0f}%"
        )
        t_funcs += r["funcs"]
        t_ret += r["ret"]
        t_args += r["args_total"]
        t_args_ann += r["args_ann"]
    print("-" * 66)
    print(
        f"{'TOTAL':<32}{t_funcs:>7}{t_ret:>6}"
        f"{(100.0 * t_ret / t_funcs if t_funcs else 100):>6.0f}%"
        f"{t_args:>7}{(100.0 * t_args_ann / t_args if t_args else 100):>6.0f}%"
    )

    errors = compile_all(files)
    print(f"\n语法检查: {'OK' if not errors else str(len(errors)) + ' 个文件失败'}")
    for e in errors:
        print("  " + e)

    if args.resolve:
        problems = resolve_hints(files)
        print(f"\n注解解析: {'OK' if not problems else str(len(problems)) + ' 处问题'}")
        for p in problems:
            print("  " + p)
        return 1 if (errors or problems) else 0

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
