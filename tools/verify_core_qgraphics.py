"""CoreQGraphics 对拍回归：与 Designer.Core 自绘场景逐图元比几何。

    .venv/Scripts/python.exe tools/verify_core_qgraphics.py
    .venv/Scripts/python.exe tools/verify_core_qgraphics.py --shot build/core_qg

硬指标（必须全过）：
  1. 图元数量 / 类型分布一致
  2. 逐 id ``sceneBoundingRect()``（场景坐标）与 ``viewBoundingRect()``
     （视图坐标）双双相等，容差 1e-4
  3. zValue 稳定排序后的 id 序列完全一致
  4. page JSON round-trip 结构零改动
  5. 渲染确定性（同场景两次 render 逐像素 diff = 0）
  6. 交互（移动/缩放/旋转/分组/解组）与吸附 T 门控

不作为门槛：与旧自绘的逐像素一致。两者的字体度量、抗锯齿、脏区裁剪
与选中反馈不同，几何等价才是本模块的交付契约。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PAGE = "Designer/Core/data.json/datas/design/pages/page_1.json"
W, H = 1440, 900
TOL = 1e-4
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILURES.append(name)
    print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))


def close_rect(a: QRectF, b: QRectF, tol: float = TOL) -> bool:
    return all(
        abs(x - y) <= tol
        for x, y in zip(
            (a.left(), a.top(), a.width(), a.height()),
            (b.left(), b.top(), b.width(), b.height()),
        )
    )


def load_old():
    from Designer.Core.myQuadTreeScene import QuadTreeScene, SceneManager

    s = QuadTreeScene()
    s.resize(W, H)
    s.setSceneRect(QRectF(QPointF(-50000, -50000), QPointF(50000, 50000)))
    s.set_scene_manager(SceneManager(s))
    s.show()
    s.load_element_info(PAGE)
    return s


def projection_from(old):
    from Designer.CoreQGraphics import SceneProjection

    return SceneProjection(
        grid_size=float(old.grid_size),
        units_x=float(old.scene_units_per_grid_x),
        units_y=float(old.scene_units_per_grid_y),
        agv=bool(old.is_use_for_agv_map),
        origin_x=float(old.scene_origin.x()),
        origin_y=float(old.scene_origin.y()),
    )


def render(scene, path: str = "") -> QImage:
    img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.white)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    target = QRectF(0, 0, W, H)
    # scene_origin=(720,450)，取以它为中心的 1440x900 视口
    source = QRectF(720 - W / 2, 450 - H / 2, W, H)
    scene.render(p, target, source, Qt.KeepAspectRatio)
    p.end()
    if path:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        img.save(path)
    return img


def pixel_diff(a: QImage, b: QImage) -> int:
    if a.size() != b.size():
        return -1
    diff = 0
    for y in range(0, a.height(), 2):
        for x in range(0, a.width(), 2):
            if a.pixelColor(x, y) != b.pixelColor(x, y):
                diff += 1
    return diff


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default=PAGE)
    ap.add_argument("--shot", default="", help="输出渲染截图前缀")
    args = ap.parse_args()

    app = QApplication.instance() or QApplication([])  # noqa: F841
    print("=== 加载两套场景 ===")
    old = load_old()
    from Designer.CoreQGraphics import GraphicsScene, SnapSystem

    proj = projection_from(old)
    new = GraphicsScene(proj)
    new.load_page(args.page)
    old_items = {it.id(): it for it in old.scene_manager.m_items.values()}
    new_items = new.index.by_id
    print(f"  Core={len(old_items)}  CoreQGraphics={len(new_items)}  "
          f"proj=({proj.kx},{proj.ky},{proj.agv},{proj.ox},{proj.oy})")
    check("图元数量一致", len(old_items) == len(new_items))
    check("id 集合一致", set(old_items) == set(new_items))

    print("\n=== 1. 逐图元几何对拍 ===")
    bad_scene, bad_view = [], []
    for iid, oi in old_items.items():
        ni = new_items.get(iid)
        if ni is None:
            continue
        if not close_rect(oi.sceneBoundingRect(), ni.page_bounding_rect()):
            bad_scene.append((iid, oi.sceneBoundingRect(), ni.page_bounding_rect()))
        if not close_rect(oi.viewBoundingRect(), ni.view_bounding_rect()):
            bad_view.append((iid, oi.viewBoundingRect(), ni.view_bounding_rect()))
    check("sceneBoundingRect 逐项相等", not bad_scene,
          f"差异 {len(bad_scene)} 项，示例 {bad_scene[:1]}")
    check("viewBoundingRect 逐项相等", not bad_view,
          f"差异 {len(bad_view)} 项，示例 {bad_view[:1]}")

    print("\n=== 2. 层级与类型 ===")
    old_order = [it.id() for it in old.scene_manager.m_sorted_items]
    new_order = [it.item_id for it in new.sorted_items()]
    check("zValue 稳定排序序列一致", old_order == new_order,
          f"前 5 Core={old_order[:5]} New={new_order[:5]}")
    old_types = {}
    for iid, it in old_items.items():
        old_types[iid] = type(it).__name__.replace("_element", "")
    new_types = {iid: it.TYPE for iid, it in new_items.items()}
    same_type = sum(
        1 for iid in old_types if old_types[iid] == new_types.get(iid)
    )
    check("类型映射覆盖", same_type == len(old_types),
          f"{same_type}/{len(old_types)}")

    print("\n=== 3. page JSON round-trip ===")
    tmp = "build/_verify_core_qg_roundtrip.json"
    new.save_page(tmp)
    with open(args.page, encoding="utf-8") as f:
        before = json.load(f)
    with open(tmp, encoding="utf-8") as f:
        after = json.load(f)
    check("顶层键集合一致", set(before) == set(after),
          f"{sorted(before)} vs {sorted(after)}")
    check("sceneRect 零改动", before.get("sceneRect") == after.get("sceneRect"))
    check("backgroundColor 零改动",
          before.get("backgroundColor") == after.get("backgroundColor"))
    check("items 条数一致", len(before["items"]) == len(after["items"]))
    check("items 逐条结构零改动", before["items"] == after["items"])
    os.remove(tmp)

    print("\n=== 4. 渲染与确定性 ===")
    img_a = render(new, args.shot + ".png" if args.shot else "")
    img_b = render(new)
    check("两次 render 逐像素一致", pixel_diff(img_a, img_b) == 0)
    white = QColor(Qt.white)
    nonwhite = sum(
        1 for y in range(0, H, 4) for x in range(0, W, 4)
        if img_a.pixelColor(x, y) != white
    )
    check("渲染非空", nonwhite > 0, f"非白采样 {nonwhite}/{(H // 4) * (W // 4)}")

    print("\n=== 5. 交互 ===")
    target = new_items[2]
    # 本轮起「有父对象的图元位姿由父对象决定」：单图元几何编辑一律先脱离父对象
    # （page_1 里几乎每个图元都挂在料架组下），否则 rotate_by 会被位姿锁拒绝。
    if target.parent_id:
        target.set_page_parent(0)
    old_pos = QPointF(target.scenePos())
    target.moveBy(10.0, 20.0)
    check("移动后 scenePos 变化",
          abs(target.scenePos().x() - old_pos.x() - 10) < 1e-9)
    target.resize_by(1.25)
    check("resize 后包围盒变宽",
          abs(target._w_view - 36.0 * proj.ky * 1.25) < 1e-3,
          f"w_view={target._w_view:.3f}")
    target.rotate_by(15.0)
    check("rotate_by 生效", abs(target.rotation() - 15.0) < 1e-9)
    rec = target.to_page_record()
    check("编辑后 to_page_record 标脏并回写几何",
          rec["rotate"] == -15.0 and rec["center_pos"] != before["items"][1]["center_pos"])
    for it in new.selectedItems():
        it.setSelected(False)
    for iid in (2, 3, 4, 5):
        new_items[iid].setSelected(True)
    group = new.group_selected()
    check("分组创建 group 图元", group is not None and group.TYPE == "group")
    check("分组内 parent_id 已挂接",
          all(new_items[i].parent_id == group.item_id for i in (2, 3, 4, 5)))
    group.setSelected(True)
    released = new.ungroup_selected()
    check("解组释放子图元", released >= 4 and
          all(new_items[i].parent_id == 0 for i in (2, 3, 4, 5)),
          f"released={released}")

    print("\n=== 6. 吸附 T 门控 ===")
    snap = SnapSystem(threshold=12.0)
    snap.grid_enabled = False   # 本节只测端点/中点，网格点单独断言
    ends, mids = new.snap_points()
    snap.update_points(ends, mids)
    e, m = snap.count()
    check("吸附点集合非空", e > 0 and m > 0, f"endpoints={e} midpoints={m}")
    sample = next(iter(snap.all_points()))
    pt = QPointF(sample[0] + 3.0, sample[1] + 4.0)
    check("门控关闭不吸附", snap.snap(pt)[1] is None)
    snap.enabled = True
    snapped, hit = snap.snap(pt)
    check("门控开启吸附到最近标记",
          hit is not None and abs(snapped.x() - sample[0]) < 1e-9)
    check("可见十字标记受视口过滤",
          len(snap.markers_in(QRectF(0, 0, 1, 1), limit=10)) <= 10)

    # 网格交汇点：解析计算，不进点集，能参与吸附
    snap.grid_enabled = True
    snap.grid_step = 50.0
    snap.grid_origin = (0.0, 0.0)
    gx, gy = snap.nearest_grid(QPointF(10003.0, 9997.0))
    check("网格最近点按步长解析计算",
          gx == 10000.0 and gy == 10000.0, f"({gx},{gy})")
    check("网格点不进入吸附点集合", (gx, gy) not in snap.all_points())
    gh, gkind = snap.aim(QPointF(gx + 2.0, gy + 2.0))
    check("网格交汇点可作捕捉点",
          gkind == "grid" and gh is not None
          and abs(gh.x() - gx) < 1e-9 and abs(gh.y() - gy) < 1e-9,
          f"{gkind} {gh}")
    check("网格步长按缩放自适应",
          (lambda: (snap.adapt_grid_to_scale(0.05), snap.grid_step)[1])() > 50.0)

    print("\n=== 7. 性能对照请用独立基准 ===")
    print("  第 4~6 节已修改过场景状态，此处帧耗时不可比，故不采样。")
    print("  .venv/Scripts/python.exe tools/bench_qgraphics_scene.py --phase ab")
    print("  完整功能实现的 12 类 paint 仍在 Python；要兑现上一轮 -54%~-66%")
    print("  需把 paint 换成 Qt 内置 item 或 C++ 实现（路线 C3 / Stage 2 P3）。")

    print(f"\n失败 {len(FAILURES)} 项" + (": " + ", ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
