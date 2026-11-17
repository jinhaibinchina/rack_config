#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把旧设计器（AGV 投影口径）的 page JSON 转成 DesignerV2.CoreQGraphics 的
Qt 原生场景坐标口径；也可反向转回。纯 Python，不依赖 PySide6 / Qt。

背景
----
旧 ``Designer/Core`` 与 ``Designer/CoreQGraphics`` 在加载页面时，会先用
``SceneProjection`` 把 page 里的「场景坐标」投影成 QGraphicsScene 里实际用的
「视图坐标」。默认参数（``myGraphicsScene.grid_size=50``、
``SceneManager.setSceneUnitsPerGrid(200, 200)``、``is_use_for_agv_map=True``、
``scene_origin=(0,0)``）下：::

    kx = ky = 50 / 200 = 0.25
    point(x, y) = (-y * kx + ox, -x * ky + oy)     轴交换 + 双轴取反
    size(w, h)  = (h * ky, w * kx)                 宽高互换
    angle(a)    = -a                                镜像使旋转反向
    rect(r)     = (point(r.right, r.bottom), h * ky, w * kx)

新的 ``DesignerV2/CoreQGraphics`` 已彻底删除投影层：page JSON 里的
``x/y/w/h/vertices/rotate`` **就是** QGraphicsScene 坐标。因此要让旧页面在
新设计器里保持原来的画面，必须把上面这套投影**烘焙进 JSON 数值**。

字段映射（正向）
----------------
======================  ======================================================
字段                    处理
======================  ======================================================
``center_pos``          point
``origin_pos``          point
``head_pos/end_pos``    point
``vertices``            逐点 point（保留 ``move`` 等其它键）
``path_segments``       逐段 point（自动识别 x/y、c1x/c1y、c2x/c2y）
``width/height``        size（轴交换）
``radius_w/radius_h``   size(2r_w, 2r_h) / 2（轴交换）
``rotate``              取负
``length``              按变换后的 head/end 重算
``style.cornerRadius``  乘 k = sqrt(kx*ky)（旧绘制乘 kx/ky，新绘制直接用）
``sceneRect``           rect；宽高为 0 的占位值原样保留
======================  ======================================================

``style.strokeWidth`` / ``font_size`` / ``widgetFontSize`` 是像素单位，两个
引擎都用同一份数值直接绘制，保持不变；``id / parent_id / children_ids /
group_id / zValue / name / context / image_path / backgroundColor`` 等原样保留。

反向（``--reverse``）用 ``SceneProjection.inverse_point / inverse_size /
inverse_rect``，可把转换后的页面还原成旧口径。

用法
----
::

    # 单文件，生成同目录的 xxx.native.json（不覆盖原文件）
    python tools/convert_page_to_native.py rack_config_scene2.json

    # 批量 / 目录 / 通配符
    python tools/convert_page_to_native.py pages/ --output-dir converted/

    # 先看报告不写盘
    python tools/convert_page_to_native.py pages/*.json --dry-run

    # 覆盖原文件（自动备份成 xxx.json.bak）
    python tools/convert_page_to_native.py pages/*.json --in-place

    # 旧页面用的不是默认投影参数时
    python tools/convert_page_to_native.py page_1.json \
        --grid-size 50 --units-x 100 --units-y 200 --origin-x 720 --origin-y 450

    # 反向转回旧口径
    python tools/convert_page_to_native.py xxx.native.json --reverse

注意
----
* 默认参数与 ``SceneProjection()`` 一致。若旧页面来自别的场景配置（例如
  ``setSceneUnitsPerGrid`` 被改过），请显式传 ``--units-x/--units-y``。
* 非 AGV 口径（``--no-agv``）下旧包的 ``rect()/size()`` 与 ``point()`` 本身
  不自洽，工具会给出警告；项目默认始终是 AGV。
* ``--mode identity`` 完全不换算数值，只重新序列化 JSON。用于「保留原物理坐标
  数值」的口径：新设计器能直接打开，但画面会旋转 / 镜像 / 放大 4 倍。
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
import math
import shutil
import sys
from pathlib import Path

NATIVE_SUFFIX = ".native.json"
LEGACY_SUFFIX = ".legacy.json"
MARK_KEY = "coordinateSystem"
MARK_NATIVE = "qt-native"
MARK_LEGACY = "legacy-agv"

POINT_KEYS = ("center_pos", "origin_pos", "head_pos", "end_pos")
RECT_KEYS = ("x", "y", "width", "height")


# ---------------------------------------------------------------------------
# 投影（严格复刻 Designer/CoreQGraphics/g_projection.py 的默认口径）
# ---------------------------------------------------------------------------
class Projection:
    def __init__(self, grid_size=50.0, units_x=200.0, units_y=200.0,
                 agv=True, origin_x=0.0, origin_y=0.0):
        self.kx = grid_size / units_x if units_x else 1.0
        self.ky = grid_size / units_y if units_y else 1.0
        self.k = math.sqrt(self.kx * self.ky)
        self.agv = bool(agv)
        self.ox = float(origin_x)
        self.oy = float(origin_y)

    def point(self, x, y):
        if self.agv:
            return (-y * self.kx + self.ox, -x * self.ky + self.oy)
        return (x * self.kx + self.ox, -y * self.ky + self.oy)

    def inverse_point(self, vx, vy):
        if self.agv:
            return (-(vy - self.oy) / self.ky, -(vx - self.ox) / self.kx)
        return ((vx - self.ox) / self.kx, -(vy - self.oy) / self.ky)

    def size(self, w, h):
        return (h * self.ky, w * self.kx)

    def inverse_size(self, wv, hv):
        return (hv / self.kx, wv / self.ky)

    @staticmethod
    def angle(a):
        return -a  # 镜像取负，正反相同

    def rect(self, x, y, w, h):
        px, py = self.point(x + w, y + h)
        return (px, py, h * self.ky, w * self.kx)

    def inverse_rect(self, x, y, w, h):
        top, bottom = y, y + h
        left, right = x, x + w
        if self.agv:
            x0 = (self.oy - bottom) / self.ky
            x1 = (self.oy - top) / self.ky
            y0 = (self.ox - right) / self.kx
            y1 = (self.ox - left) / self.kx
        else:
            x0, x1 = (left - self.ox) / self.kx, (right - self.ox) / self.kx
            y1, y0 = (self.oy - top) / self.ky, (self.oy - bottom) / self.ky
        return (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))


class Mapping:
    """把正/反向的一组映射打包，供字段转换使用。"""

    def __init__(self, proj: Projection, reverse=False, mode="visual",
                 keep_scene_rect=False, mark=False, round_to=None):
        self.proj = proj
        self.reverse = reverse
        self.mode = mode
        self.keep_scene_rect = keep_scene_rect
        self.mark = mark
        self.round_to = round_to
        self.map_point = proj.inverse_point if reverse else proj.point
        self.map_size = proj.inverse_size if reverse else proj.size
        self.map_rect = proj.inverse_rect if reverse else proj.rect
        self.scale = 1.0 / proj.k if reverse else proj.k

    def num(self, value):
        value = float(value)
        if abs(value) < 1e-12:
            return 0.0
        if self.round_to is not None:
            value = round(value, self.round_to)
            if abs(value) < 0.5 * 10 ** (-self.round_to):
                return 0.0
        return value


# ---------------------------------------------------------------------------
# 字段转换
# ---------------------------------------------------------------------------
def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def map_point_dict(d, m: Mapping):
    out = dict(d)  # 保序，且保留 move 等额外键
    if is_num(d.get("x")) and is_num(d.get("y")):
        nx, ny = m.map_point(float(d["x"]), float(d["y"]))
        out["x"], out["y"] = m.num(nx), m.num(ny)
    return out


def map_segments(segments, m: Mapping):
    """path_segments 里的 x/y、c1x/c1y、c2x/c2y 成对投影。"""
    out = []
    for seg in segments or ():
        if not isinstance(seg, dict):
            out.append(seg)
            continue
        s = dict(seg)
        for key in list(s.keys()):
            if not key.endswith("x"):
                continue
            ykey = key[:-1] + "y"
            if ykey in s and is_num(s[key]) and is_num(s[ykey]):
                nx, ny = m.map_point(float(s[key]), float(s[ykey]))
                s[key], s[ykey] = m.num(nx), m.num(ny)
        out.append(s)
    return out


def convert_item(record, m: Mapping):
    if m.mode == "identity":
        return copy.deepcopy(record)
    out = copy.deepcopy(record)

    for key in POINT_KEYS:
        value = out.get(key)
        if isinstance(value, dict):
            out[key] = map_point_dict(value, m)

    if isinstance(out.get("vertices"), list):
        out["vertices"] = [
            map_point_dict(v, m) if isinstance(v, dict) else v
            for v in out["vertices"]
        ]

    if isinstance(out.get("path_segments"), list):
        out["path_segments"] = map_segments(out["path_segments"], m)

    # width / height：缺失的一轴按 radius 推（与 BaseItem.__init__ 同口径）
    w_raw, h_raw = out.get("width"), out.get("height")
    if w_raw is not None or h_raw is not None:
        w0 = (float(w_raw) if is_num(w_raw)
              else float(out.get("radius_w") or 0.0) * 2.0)
        h0 = (float(h_raw) if is_num(h_raw)
              else float(out.get("radius_h") or 0.0) * 2.0)
        nw, nh = m.map_size(w0, h0)
        if w_raw is not None:
            out["width"] = m.num(nw)
        if h_raw is not None:
            out["height"] = m.num(nh)

    # radius_w / radius_h：等价于 size(2r_w, 2r_h) / 2
    rw, rh = out.get("radius_w"), out.get("radius_h")
    if rw is not None or rh is not None:
        rw0 = float(rw) if is_num(rw) else float(rh or 0.0)
        rh0 = float(rh) if is_num(rh) else float(rw or 0.0)
        nw, nh = m.map_size(2.0 * rw0, 2.0 * rh0)
        if rw is not None:
            out["radius_w"] = m.num(nw / 2.0)
        if rh is not None:
            out["radius_h"] = m.num(nh / 2.0)

    if is_num(out.get("rotate")):
        # 不走 num()：旧包 setRotation(-a) 用的就是这个值，连 1e-15 的浮点
        # 噪声都保留，才能让新旧加载器算出的旋转角逐位相同。
        a = Projection.angle(float(out["rotate"]))
        if m.round_to is not None:
            a = round(a, m.round_to)
        out["rotate"] = a

    if is_num(out.get("length")):
        # length 是冗余字段（加载只看 head_pos/end_pos），按比例缩放即可。
        # 不能用变换后的端点重算：JSON 里的端点已被 round(3)，而原 length
        # 来自更高精度端点，重算会引入不可逆的 1e-4 级偏差。
        out["length"] = m.num(float(out["length"]) * m.scale)

    style = out.get("style")
    if isinstance(style, dict) and is_num(style.get("cornerRadius")):
        style["cornerRadius"] = m.num(float(style["cornerRadius"]) * m.scale)

    return out


def convert_page(data, m: Mapping):
    out = copy.deepcopy(data)
    items = data.get("items") or []
    out["items"] = [convert_item(r, m) for r in items]

    sr = out.get("sceneRect")
    if (not m.keep_scene_rect and isinstance(sr, dict)
            and all(is_num(sr.get(k)) for k in RECT_KEYS)
            and float(sr["width"]) > 0 and float(sr["height"]) > 0):
        x, y, w, h = m.map_rect(
            float(sr["x"]), float(sr["y"]),
            float(sr["width"]), float(sr["height"]))
        out["sceneRect"] = {
            "x": m.num(x), "y": m.num(y),
            "width": m.num(w), "height": m.num(h),
        }

    if m.mark:
        out[MARK_KEY] = MARK_LEGACY if m.reverse else MARK_NATIVE
    return out


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def brief(data):
    items = data.get("items") or []
    xs = [float(r["center_pos"]["x"]) for r in items
          if isinstance(r.get("center_pos"), dict)
          and is_num(r["center_pos"].get("x"))]
    ys = [float(r["center_pos"]["y"]) for r in items
          if isinstance(r.get("center_pos"), dict)
          and is_num(r["center_pos"].get("y"))]
    sr = data.get("sceneRect") or {}
    rng = (f"x[{min(xs):.1f},{max(xs):.1f}] y[{min(ys):.1f},{max(ys):.1f}]"
           if xs and ys else "no center_pos")
    rect = (f"sceneRect=({sr.get('x', 0):.1f},{sr.get('y', 0):.1f},"
            f"{sr.get('width', 0):.1f},{sr.get('height', 0):.1f})")
    pivots = sum(
        1 for r in items
        if isinstance(r.get("center_pos"), dict)
        and isinstance(r.get("origin_pos"), dict)
        and is_num(r["center_pos"].get("x")) and is_num(r["origin_pos"].get("x"))
        and (abs(float(r["origin_pos"]["x"]) - float(r["center_pos"]["x"])) >= 0.05
             or abs(float(r["origin_pos"]["y"]) - float(r["center_pos"]["y"])) >= 0.05)
    )
    return len(items), rng, rect, pivots


def warn(msg):
    print(f"  [warn] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def collect_inputs(raw_paths):
    found = []
    for raw in raw_paths:
        if any(ch in raw for ch in "*?["):
            found.extend(Path(p) for p in glob.glob(raw, recursive=True))
            continue
        p = Path(raw)
        if p.is_dir():
            found.extend(sorted(x for x in p.rglob("*.json") if x.is_file()))
        elif p.is_file():
            found.append(p)
        else:
            warn(f"路径不存在: {raw}")
    unique, seen = [], set()
    for p in found:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def output_for(src: Path, args, count: int) -> Path:
    suffix = LEGACY_SUFFIX if args.reverse else NATIVE_SUFFIX
    if args.output and count == 1:
        return Path(args.output)
    if args.output_dir:
        return Path(args.output_dir) / (src.stem + suffix)
    if args.in_place:
        return src
    return src.with_name(src.stem + suffix)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="旧 AGV 投影页面 <-> DesignerV2 Qt 原生坐标页面（可逆）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例: python tools/convert_page_to_native.py page_1.json --dry-run")
    ap.add_argument("inputs", nargs="+", help="JSON 文件 / 目录 / 通配符")
    ap.add_argument("-o", "--output", help="单个输入时的输出路径")
    ap.add_argument("--output-dir", help="批量输出目录")
    ap.add_argument("--in-place", action="store_true",
                    help="覆盖原文件（先备份成 <name>.json.bak）")
    ap.add_argument("--no-backup", action="store_true",
                    help="配合 --in-place 跳过备份（不推荐）")
    ap.add_argument("--force", action="store_true", help="允许覆盖已存在的输出文件")
    ap.add_argument("--dry-run", action="store_true", help="只打印报告，不写文件")
    ap.add_argument("--reverse", action="store_true",
                    help="反向：qt-native -> 旧 AGV 投影口径")
    ap.add_argument("--mode", choices=("visual", "identity"), default="visual",
                    help="visual=烘焙投影保持画面一致（默认）；identity=不换算数值")
    ap.add_argument("--keep-scene-rect", action="store_true",
                    help="不转换 sceneRect（保留原取景数值）")
    ap.add_argument("--mark", action="store_true",
                    help="在顶层写入 coordinateSystem 标记")
    ap.add_argument("--round", type=int, default=None, metavar="N",
                    help="输出坐标保留 N 位小数（默认保留完整浮点）")
    # 投影参数：默认与 SceneProjection() / myGraphicsScene 一致
    ap.add_argument("--grid-size", type=float, default=50.0)
    ap.add_argument("--units-x", type=float, default=200.0)
    ap.add_argument("--units-y", type=float, default=200.0)
    ap.add_argument("--no-agv", action="store_true", help="旧页面用的是非 AGV 口径")
    ap.add_argument("--origin-x", type=float, default=0.0)
    ap.add_argument("--origin-y", type=float, default=0.0)
    args = ap.parse_args(argv)

    if args.output and args.output_dir:
        ap.error("--output 与 --output-dir 不能同时用")
    if args.output and args.in_place:
        ap.error("--output 与 --in-place 不能同时用")
    if args.round is not None and args.round < 0:
        ap.error("--round 必须是非负整数")

    proj = Projection(args.grid_size, args.units_x, args.units_y,
                      agv=not args.no_agv,
                      origin_x=args.origin_x, origin_y=args.origin_y)
    if args.no_agv:
        warn("非 AGV 口径下旧包 rect()/size() 与 point() 不自洽，结果请人工核对")
    m = Mapping(proj, reverse=args.reverse, mode=args.mode,
                keep_scene_rect=args.keep_scene_rect,
                mark=args.mark, round_to=args.round)

    sources = collect_inputs(args.inputs)
    if not sources:
        ap.error("没有找到任何 JSON 文件")
    if args.output and len(sources) != 1:
        ap.error("--output 只能配合单个输入文件使用")

    print(f"方向: {'qt-native -> legacy-agv' if args.reverse else 'legacy-agv -> qt-native'}"
          f"  模式: {args.mode}")
    print(f"参数: grid={args.grid_size} units=({args.units_x},{args.units_y}) "
          f"agv={not args.no_agv} origin=({args.origin_x},{args.origin_y}) "
          f"=> kx={proj.kx:.6g} ky={proj.ky:.6g}")
    print("-" * 78)

    done, skipped, failed = 0, 0, 0
    for src in sources:
        name = src.name
        if name.endswith((NATIVE_SUFFIX, LEGACY_SUFFIX, ".json.bak")) \
                and not args.force and not args.in_place:
            print(f"[skip] {name}  已是转换产物/备份（--force 可强制转换）")
            skipped += 1
            continue
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            print(f"[fail] {name}  读取/解析失败: {exc}")
            failed += 1
            continue
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            print(f"[skip] {name}  不是 page JSON（缺 items 数组）")
            skipped += 1
            continue
        if not args.force and data.get(MARK_KEY) in (MARK_NATIVE, MARK_LEGACY):
            expected = MARK_LEGACY if args.reverse else MARK_NATIVE
            if data[MARK_KEY] == expected:
                print(f"[skip] {name}  已标记 {data[MARK_KEY]}（--force 可强制转换）")
                skipped += 1
                continue

        before = brief(data)
        try:
            result = convert_page(data, m)
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            print(f"[fail] {name}  转换失败: {exc}")
            failed += 1
            continue
        after = brief(result)

        dst = output_for(src, args, len(sources))
        print(f"[{'dry' if args.dry_run else ' ok '}] {name} -> {dst.name}")
        print(f"       items={before[0]}  {before[1]}  {before[2]}")
        if args.mode == "visual":
            print(f"        =>   {after[1]}  {after[2]}")
            if before[3]:
                print(f"       自定义旋转支点 {before[3]} 个（已随坐标一起换算）")

        if args.dry_run:
            done += 1
            continue
        if dst.exists() and not args.force and dst != src:
            print(f"[skip] {name}  输出已存在: {dst}（--force 覆盖）")
            skipped += 1
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst == src and not args.no_backup:
                backup = src.with_suffix(src.suffix + ".bak")
                shutil.copy2(src, backup)
                print(f"       备份: {backup.name}")
            text = json.dumps(result, ensure_ascii=False, indent=4) + "\n"
            dst.write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"[fail] {name}  写入失败: {exc}")
            failed += 1
            continue
        done += 1

    print("-" * 78)
    print(f"完成: {done}  跳过: {skipped}  失败: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
