"""从 ``page_9.json`` 派生一份带第 7 张卡片的场景文件。

设计工程 ``page_9.json`` 只有 6 张 widget 卡片（Page0..Page5），而 HMI 页面
有 7 个（主监控 / 轴 / IO / 参数 / 报警 / 日志 / 程序监控）。本脚本**不改动
原设计文件**，只复制出 ``page_10.json``，并按扇形已有规律外推一张 Page6：

* 取 rotate 最大的几张堆叠卡（Page1..Page5）算平均位移与角度增量；
* 复制最外层那张卡的全部属性（尺寸 / 样式 / 层级），只改 id / name /
  center_pos / rotate / widgetText；
* 新卡仍属于左侧堆叠，右侧槽位仍是 Page0（``PageDeck._detect_slot`` 按
  视图 x 自动判定，不用手工登记）；
* **默认把所有 widget 卡片的 width/height 互换**：原设计是
  ``4000×3000``（宽4高3），按现场要求改成 ``3000×4000``（宽3高4）。
  加 ``--landscape`` 可保留原横版尺寸。

注意 AGV 的 90° 轴映射会把这两个值再换一次送进承载层：
``4000×3000`` 实测落地为控件 ``750×1000`` 像素（竖屏），
互换后的 ``3000×4000`` 则是 ``1000×750`` 像素（横屏）。
也就是说这一改只换**场景字段/设计态观感**，屏幕上的比例会反过来。

跑法::

    .venv/Scripts/python.exe tools/gen_hmi_scene.py
    .venv/Scripts/python.exe tools/gen_hmi_scene.py --source <page.json> --out <new.json>

使用::

    python pop_pick_main.py --app PopPick            # 代码里把 page 改成 page_10
    python App_PopPick/pop_pick_entry.py --page page_10
    python App_PopPick/pop_pick_entry.py --scene <page_10.json 绝对路径>

打包运行态：``pop_pick_entry.resolve_page_file`` 在 frozen 下优先找
``res/myDesigner/scene/pop_pick_scene_7.json``（本脚本用 ``--out`` 生成），
找不到才回退到旧的 6 卡 ``pop_pick_scene.json``。原快照不用覆盖。
另外 ``工具集.spec`` 的 datas 已加上 ``App_PopPick/hmi/data``，
少了那两份 JSON 页面会全部起不来；用 ``packTool.py`` 重新生成 spec 时
记得把这条一起勾上。
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "Designer/Core/data.json/datas/design/pages/page_9.json"
DEFAULT_OUT = ROOT / "Designer/Core/data.json/datas/design/pages/page_10.json"


def build(source: Path, out: Path, *, new_name: str = "Page6",
          portrait: bool = True) -> dict:
    data = json.loads(source.read_text(encoding="utf-8"))
    items = data["items"]
    cards = [it for it in items if str(it.get("name", "")).startswith("Page")
             and it.get("type") == "widget"]
    if not cards:
        raise ValueError(f"{source.name} 里没有 Page* 的 widget 卡片")
    if any(it.get("name") == new_name for it in cards):
        raise ValueError(f"{source.name} 里已经有 {new_name}，不必再生成")

    # 右侧槽位 Page0 单独放，其余按旋转角从小到大就是扇形由内到外。
    stack = sorted((it for it in cards if it.get("name") != "Page0"),
                   key=lambda it: float(it.get("rotate") or 0))
    if len(stack) < 2:
        raise ValueError("至少需要两张堆叠卡才能外推新卡位姿")

    # 用最后两张的平均增量外推，比写死坐标更贴合设计者原来的扇形步长。
    tail = stack[-3:] if len(stack) >= 3 else stack
    dx = (tail[-1]["center_pos"]["x"] - tail[0]["center_pos"]["x"]) / (len(tail) - 1)
    dy = (tail[-1]["center_pos"]["y"] - tail[0]["center_pos"]["y"]) / (len(tail) - 1)
    da = (float(tail[-1].get("rotate") or 0) - float(tail[0].get("rotate") or 0)) / (len(tail) - 1)

    template = copy.deepcopy(stack[-1])
    template["id"] = max(int(it.get("id", 0)) for it in items) + 1
    template["name"] = new_name
    template["center_pos"] = {
        "x": round(stack[-1]["center_pos"]["x"] + dx, 3),
        "y": round(stack[-1]["center_pos"]["y"] + dy, 3),
    }
    template["rotate"] = round(float(stack[-1].get("rotate") or 0) + da, 6)
    template["widgetText"] = "程序监控"
    template["children_ids"] = []
    template["parent_id"] = 0
    template["group_id"] = 0
    items.append(template)

    swapped = 0
    if portrait:
        # 7 张卡一视同仁，包括右侧槽位 Page0：只换尺寸字段，中心点/角度不动，
        # 扇形位姿与 PageDeck 的槽位判定都保持原样。
        for item in items:
            if item.get("type") != "widget":
                continue
            width, height = item.get("width"), item.get("height")
            if isinstance(width, (int, float)) and isinstance(height, (int, float)):
                item["width"], item["height"] = height, width
                swapped += 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "source": str(source),
        "out": str(out),
        "cards_before": len(cards),
        "cards_after": len(cards) + 1,
        "new_card": template["name"],
        "center_pos": template["center_pos"],
        "rotate": template["rotate"],
        "swapped": swapped,
        "card_size": f"{template['width']}×{template['height']}",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--name", default="Page6", help="新卡片名字（默认 Page6）")
    ap.add_argument("--landscape", action="store_true",
                    help="保留原 4000×3000（宽4高3）；默认换成 3000×4000（宽3高4）")
    args = ap.parse_args()
    if not args.source.is_file():
        raise SystemExit(f"源页面不存在: {args.source}")
    info = build(args.source, args.out, new_name=args.name,
                 portrait=not args.landscape)
    print(f"原场景: {info['source']}（{info['cards_before']} 张卡片）")
    print(f"新场景: {info['out']}（{info['cards_after']} 张卡片）")
    print(f"卡片尺寸: {info['card_size']}｜互换 {info['swapped']} 张")
    print(f"新增 {info['new_card']}: center={info['center_pos']}, rotate={info['rotate']}°")
    print("原 page_9.json 未改动；用 --page page_10 或 --scene 指向新文件即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
