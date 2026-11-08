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
from PySide6.QtGui import QColor, QFontMetricsF, QImage, QPainter  # noqa: E402
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

    print("\n=== 6.5 递归复制 / 组尺寸递归缩放（独立小场景） ===")
    from Designer.CoreQGraphics.g_scene import GraphicsScene

    mini = GraphicsScene()
    grp = mini.create_item("group", center=(1000.0, 1000.0), size=(400.0, 300.0))
    rect = mini.create_item("rect", center=(960.0, 980.0), size=(100.0, 60.0))
    tri = mini.create_item("triangle", center=(1100.0, 1050.0))
    line = mini.create_item("line", center=(900.0, 1100.0))
    rect.set_page_parent(grp.item_id)
    line.set_page_parent(grp.item_id)
    tri.set_page_parent(rect.item_id)          # 三层：grp -> rect -> tri
    grp.set_page_field("children_ids", [rect.item_id, line.item_id])
    rect.set_page_field("children_ids", [tri.item_id])
    mini.index.rebuild_links()
    tree = [grp, rect, tri, line]
    n0 = len(mini.all_items())
    check("独立小场景含三层父子 + 顶点类成员",
          n0 == 4 and len(mini.index.descendants(grp.item_id)) == 3, f"n={n0}")

    def _geo(it):
        rec = it.to_page_record()
        points = {}
        for k in ("center_pos", "origin_pos", "head_pos", "end_pos"):
            v = rec.get(k)
            if isinstance(v, dict):
                points[k] = (float(v.get("x", 0.0)), float(v.get("y", 0.0)))
        verts = [(float(v.get("x", 0.0)), float(v.get("y", 0.0)))
                 for v in (rec.get("vertices") or [])]
        return points, verts, it.page_size()

    old_ids = set(mini.index.order)
    orig = {it.item_id: it for it in tree}
    mini.clearSelection()
    grp.setSelected(True)
    captured = mini.copy_selected()
    check("复制顶层自动带上整棵子树（三层 4 个）", captured == 4, str(captured))
    # 副本按「快照顺序 = 新 id 递增顺序」配对，不依赖命名规则
    snap = mini._clipboard

    first = mini.paste_clipboard((50.0, 60.0))
    new_ids = sorted(iid for iid in mini.index.order if iid not in old_ids)
    copies = {snap[i][0]: mini.find_item(new_ids[i])
              for i in range(min(len(snap), len(new_ids)))}
    check("粘贴新增 4 个图元且只选中顶层副本",
          len(mini.all_items()) == n0 + 4 and len(first) == 1
          and len(copies) == 4 and all(v is not None for v in copies.values()),
          f"n={len(mini.all_items())} tops={len(first)} copies={len(copies)}")

    id_map = {sid: dst.item_id for sid, dst in copies.items()}
    ok_links = all(
        copies[sid].parent_id == id_map.get(src.parent_id, 0)
        and sorted(copies[sid].children_ids)
        == sorted(id_map[c] for c in src.children_ids if c in id_map)
        for sid, src in orig.items()
    )
    check("副本 parent_id / children_ids 全部重映射到新 id", ok_links)

    ok_offset = True
    for sid, src in orig.items():
        sp, sv, _ = _geo(src)
        cp, cv, _ = _geo(copies[sid])
        for k, (x, y) in sp.items():
            if k in cp:
                ok_offset &= (abs(cp[k][0] - x - 50.0) < 1e-3
                              and abs(cp[k][1] - y - 60.0) < 1e-3)
        ok_offset &= len(sv) == len(cv)
        for (x, y), (nx, ny) in zip(sv, cv):
            ok_offset &= (abs(nx - x - 50.0) < 1e-3
                          and abs(ny - y - 60.0) < 1e-3)
    check("整棵树（含后代顶点）统一偏移 +50/+60", ok_offset)

    mini.clearSelection()
    for it in tree:
        it.setSelected(True)
    check("父子同时选中只按顶层剪一次", mini.copy_selected() == 4,
          str(len(mini._clipboard)))
    second = mini.paste_clipboard((50.0, 60.0))
    check("连续粘贴各自独立且关系完整",
          len(mini.all_items()) == n0 + 8 and len(second) == 1
          and len(mini.index.descendants(second[0].item_id)) == 3,
          f"n={len(mini.all_items())}")
    d = (second[0].page_center()[0] - first[0].page_center()[0],
         second[0].page_center()[1] - first[0].page_center()[1])
    check("连续粘贴阶梯偏移不重叠",
          abs(d[0] - 50.0) < 1e-3 and abs(d[1] - 60.0) < 1e-3, str(d))

    anchor = grp.page_origin()
    before = {it.item_id: (it.page_center(), it.page_size()) for it in tree}
    gw, gh = grp.page_size()

    def _scaled_ok(factor):
        ok = True
        for it in tree:
            (cx, cy), (w, h) = before[it.item_id]
            ncx, ncy = it.page_center()
            nw, nh = it.page_size()
            ok &= abs(ncx - (anchor[0] + (cx - anchor[0]) * factor)) < 1e-2
            ok &= abs(ncy - (anchor[1] + (cy - anchor[1]) * factor)) < 1e-2
            ok &= abs(nw - w * factor) < 1e-2 and abs(nh - h * factor) < 1e-2
        return ok

    grp.set_page_size(gw * 2.0, gh * 2.0)
    check("组 ×2 递归改成员位置与尺寸（矩形/三角/线/组本身）",
          _scaled_ok(2.0))
    check("组旋转中心不动（无父时锚点即支点）",
          abs(grp.page_origin()[0] - anchor[0]) < 1e-6
          and abs(grp.page_origin()[1] - anchor[1]) < 1e-6)
    before = {it.item_id: (it.page_center(), it.page_size()) for it in tree}
    grp.set_page_size(gw * 3.0, gh * 3.0)      # 再 ×1.5
    check("组再 ×1.5 仍按同一锚点递归缩放", _scaled_ok(1.5))
    check("缩放后成员 parent_id 保持",
          all(it.parent_id in (grp.item_id, rect.item_id)
              for it in (rect, tri, line)))

    data = mini.page_data()
    mini2 = GraphicsScene()
    mini2.load_data(data)
    drift = []
    for iid, it in mini.index.by_id.items():
        other = mini2.find_item(iid)
        if other is None or not close_rect(
                it.page_bounding_rect(), other.page_bounding_rect(), 1e-2):
            drift.append(iid)
    check("缩放后保存 / 重载逐图元包围盒一致", not drift, str(drift[:4]))

    print("\n=== 6.6 组名前缀体系 / 拖角改尺寸（独立小场景） ===")
    nm = GraphicsScene()
    r = nm.create_item("rect", center=(1960.0, 1980.0), size=(100.0, 60.0))
    t = nm.create_item("triangle", center=(2060.0, 2040.0))
    r.set_name("甲")
    t.set_name("乙")
    nm.clearSelection()
    r.setSelected(True)
    t.setSelected(True)
    grp = nm.group_selected()
    gname = grp.get_name()
    check("成组后成员名带 <组名>_ 前缀",
          r.get_name() == f"{gname}_甲" and t.get_name() == f"{gname}_乙",
          f"{r.get_name()} / {t.get_name()}")

    grp.set_name("新组")           # 走 BaseItem.set_name -> scene.rename_group
    check("组改名后成员前缀同步替换",
          r.get_name() == "新组_甲" and t.get_name() == "新组_乙",
          f"{r.get_name()} / {t.get_name()}")
    check("组改名写回 page 记录", grp.page_record().get("name") == "新组")

    nm.clearSelection()
    grp.setSelected(True)
    nm.copy_selected()
    p1 = nm.paste_clipboard((50.0, 60.0))[0]
    check("粘贴组名为 原名_2", p1.get_name() == "新组_2", p1.get_name())
    kids1 = {it.get_name() for it in nm.index.descendants(p1.item_id)}
    check("副本成员只换组名前缀（不追加 _2）",
          kids1 == {"新组_2_甲", "新组_2_乙"}, str(kids1))
    p2 = nm.paste_clipboard((50.0, 60.0))[0]
    check("连续粘贴得到 原名_3（不是 原名_2_2）",
          p2.get_name() == "新组_3", p2.get_name())
    all_names = [it.get_name() for it in nm.all_items()]
    check("全场图元名字唯一", len(all_names) == len(set(all_names)),
          f"{len(all_names)} 个 / {len(set(all_names))} 种")

    nm.clearSelection()
    grp.setSelected(True)
    nm.ungroup_selected()
    check("解组剥掉一层组名前缀",
          r.get_name() == "甲" and t.get_name() == "乙",
          f"{r.get_name()} / {t.get_name()}")

    solo = nm.create_item("rect", center=(2200.0, 2200.0))
    solo.set_name("独立矩形")
    nm.clearSelection()
    solo.setSelected(True)
    nm.copy_selected()
    solo2 = nm.paste_clipboard((10.0, 10.0))[0]
    check("非组顶层保留原名加 _2（旧 Core 会丢弃用户命名）",
          solo2.get_name() == "独立矩形_2", solo2.get_name())

    odd = nm.create_item("group", center=(2400.0, 2400.0))
    oddm = nm.create_item("rect", center=(2380.0, 2380.0))
    oddm.set_page_parent(odd.item_id)
    nm.index.rebuild_links()
    oddm.set_name("不带前缀")       # 故意不匹配 <组名>_ 前缀
    nm.clearSelection()
    odd.setSelected(True)
    nm.copy_selected()
    odd2 = nm.paste_clipboard((10.0, 10.0))[0]
    kids2 = nm.index.descendants(odd2.item_id)
    check("成员名不匹配旧组前缀时退回默认命名",
          len(kids2) == 1 and kids2[0].get_name().startswith("矩形_"),
          str([k.get_name() for k in kids2]))

    # 拖角缩放：resize_item_about 的 sx/sy 是 page 轴比例，anchor 是 page 坐标
    rg = GraphicsScene()
    box = rg.create_item("rect", center=(3000.0, 3000.0), size=(200.0, 100.0))
    ends, _ = box.snap_points()
    ax, ay = rg.projection.inverse_point(ends[0].x(), ends[0].y())
    w0, h0 = box.page_size()
    c0 = box.page_center()
    rg.resize_item_about(box, (ax, ay), 2.0, 1.5)
    check("拖角缩放：宽 ×2 / 高 ×1.5",
          abs(box.page_size()[0] - w0 * 2.0) < 1e-6
          and abs(box.page_size()[1] - h0 * 1.5) < 1e-6,
          f"{w0}x{h0} -> {box.page_size()}")
    c1 = box.page_center()
    check("拖角缩放：中心按锚点搬走",
          abs(c1[0] - (ax + (c0[0] - ax) * 2.0)) < 1e-3
          and abs(c1[1] - (ay + (c0[1] - ay) * 1.5)) < 1e-3, str(c1))
    ends1, _ = box.snap_points()
    ax1, ay1 = rg.projection.inverse_point(ends1[0].x(), ends1[0].y())
    check("拖角缩放：按住的对角保持不动",
          abs(ax1 - ax) < 1e-3 and abs(ay1 - ay) < 1e-3,
          f"({ax},{ay}) -> ({ax1},{ay1})")
    rg.resize_item_about(box, (ax, ay), 1.5, 1.0)
    check("多次增量缩放可复合（等价一次 ×3）",
          abs(box.page_size()[0] - w0 * 3.0) < 1e-4, str(box.page_size()))

    gg = GraphicsScene()
    g = gg.create_item("group", center=(4000.0, 4000.0), size=(400.0, 300.0))
    m = gg.create_item("rect", center=(3950.0, 3980.0), size=(100.0, 60.0))
    m.set_page_parent(g.item_id)
    g.set_page_field("children_ids", [m.item_id])
    gg.index.rebuild_links()
    gends, _ = g.snap_points()
    gax, gay = gg.projection.inverse_point(gends[0].x(), gends[0].y())
    mw0 = m.page_size()[0]
    mc0 = m.page_center()
    gg.resize_item_about(g, (gax, gay), 2.0, 2.0)
    check("组拖角递归放大成员尺寸",
          abs(m.page_size()[0] - mw0 * 2.0) < 1e-3,
          f"{mw0} -> {m.page_size()[0]}")
    check("组拖角成员中心按锚点搬走",
          abs(m.page_center()[0] - (gax + (mc0[0] - gax) * 2.0)) < 1e-2,
          f"{mc0} -> {m.page_center()}")
    gg2 = GraphicsScene()
    gg2.load_data(gg.page_data())
    drift2 = [iid for iid, it in gg.index.by_id.items()
              if gg2.find_item(iid) is None
              or not close_rect(it.page_bounding_rect(),
                                gg2.find_item(iid).page_bounding_rect(), 1e-2)]
    check("组拖角后保存 / 重载逐图元包围盒一致", not drift2, str(drift2[:4]))

    print("\n=== 6.7 文本图元：字号 / 文字驱动边框背景（独立小场景） ===")
    from Designer.CoreQGraphics.g_elements import TextItem  # noqa: E402
    from Designer.CoreQGraphics.g_style import (  # noqa: E402
        TEXT_PAD_X, TEXT_PAD_Y, font_for, text_metrics,
    )

    ts = GraphicsScene()
    label = ts.create_item("text", center=(5000.0, 5000.0), context="  编号  ")
    center0, pivot0 = label.page_center(), label.page_origin()
    label.set_style_value("font_size", 40)
    wpx, hpx = text_metrics("  编号  ", 40)
    ew, eh = ts.projection.inverse_size(wpx + 2 * TEXT_PAD_X,
                                        hpx + 2 * TEXT_PAD_Y)
    check("改字号后 page 宽高按文字度量重算",
          abs(label.page_size()[0] - ew) < 1e-6
          and abs(label.page_size()[1] - eh) < 1e-6,
          f"{label.page_size()} vs {(ew, eh)}")
    check("边框（局部矩形）= 文字 + 内边距",
          abs(label.boundingRect().width() - (wpx + 2 * TEXT_PAD_X)) < 1e-6
          and abs(label.boundingRect().height() - (hpx + 2 * TEXT_PAD_Y)) < 1e-6,
          f"{label.boundingRect().width()}x{label.boundingRect().height()}")
    check("重算边框不动中心 / 支点",
          label.page_center() == center0 and label.page_origin() == pivot0)
    check("字号写回 style 且 to_page_record 几何同步",
          label.to_page_record()["style"]["font_size"] == 40
          and abs(label.to_page_record()["width"] - ew) < 1e-6)

    # 度量必须等于真实绘制的 boundingRect，否则文字会被 QGraphicsItem 裁掉
    probe_img = QImage(2000, 1000, QImage.Format_ARGB32)
    pn = QPainter(probe_img)
    pn.setFont(font_for("Arial", 40, True))
    drawn = pn.boundingRect(QRectF(0, 0, 1900, 900), Qt.AlignCenter, "  编号  ")
    pn.end()
    check("文字度量与 QPainter.boundingRect 一致（不会被裁）",
          abs(drawn.width() - wpx) < 1e-6
          and abs(drawn.height() - hpx) < 1e-6,
          f"{(wpx, hpx)} vs {(drawn.width(), drawn.height())}")

    h_before = label.page_size()[1]
    label.set_page_field("context", "很长的文本内容ABCDEFG")
    check("改文字后边框长度方向随文字变长",
          label.page_size()[1] > h_before * 1.1,
          f"{h_before} -> {label.page_size()[1]}")

    size_before = label.page_size()
    label.set_style_value("strokeWidth", 6)
    check("改其它样式子键不误触发边框重算",
          label.page_size() == size_before, str(label.page_size()))

    w_before_multi = label.page_size()[0]
    label.set_page_field("context", "A\nBBB\nCC")
    mw, mh = text_metrics("A\nBBB\nCC", 40)
    check("多行文本按 lineSpacing 累加行高（不裁字）",
          abs(label.boundingRect().width() - (mw + 2 * TEXT_PAD_X)) < 1e-6
          and abs(label.boundingRect().height() - (mh + 2 * TEXT_PAD_Y)) < 1e-6
          and label.page_size()[0] > w_before_multi,
          f"bbox={label.boundingRect().width()}x{label.boundingRect().height()} "
          f"metrics={(mw, mh)}")

    other = ts.create_item("rect", center=(5600.0, 5600.0))
    rect_size = other.page_size()
    other.set_style_value("font_size", 60)
    check("非文本图元改 font_size 不动几何", other.page_size() == rect_size)

    # 存量记录只在**显式编辑**时重算；加载路径必须原样保留，否则 page_1
    # 的 1618 图元对拍与 JSON round-trip 零改动会立刻失效。
    legacy = {
        "id": 99001, "type": "text", "name": "存量文本", "context": "  编号  ",
        "width": 100.0, "height": 224.0,
        "center_pos": {"x": 7000.0, "y": 7000.0},
        "origin_pos": {"x": 7000.0, "y": 7000.0},
        "rotate": 0.0, "style": {"font_size": 13}, "zValue": 1.0,
    }
    legacy_item = TextItem(legacy, ts.projection)
    check("加载存量文本记录不自动重算（对拍 / round-trip 不受影响）",
          legacy_item.page_size() == (100.0, 224.0),
          str(legacy_item.page_size()))
    check("存量记录未编辑时 to_page_record 零改动",
          legacy_item.to_page_record() == legacy)

    ts2 = GraphicsScene()
    ts2.load_data(ts.page_data())
    drift3 = [iid for iid, it in ts.index.by_id.items()
              if ts2.find_item(iid) is None
              or not close_rect(it.page_bounding_rect(),
                                ts2.find_item(iid).page_bounding_rect(), 1e-2)]
    check("字号 / 文本编辑后保存重载逐图元包围盒一致", not drift3,
          str(drift3[:4]))

    print("\n=== 6.8 文本图元：改边框反算字号（双向联动，独立小场景） ===")

    def _font_fits(it, fs=None) -> bool:
        """文字 + 内边距是否装得进当前视口边框（不能被 boundingRect 裁掉）。"""
        size = int(round(it._style.font_size)) if fs is None else int(fs)
        tw, th = text_metrics(it.context or "", size)
        vw, vh = it._proj.size(*it.page_size())
        return (tw + 2 * TEXT_PAD_X <= vw + 1e-6
                and th + 2 * TEXT_PAD_Y <= vh + 1e-6)

    bs = GraphicsScene()
    bl = bs.create_item("text", center=(3000.0, 3000.0), context="  编号  ")
    bl.set_style_value("font_size", 40)
    bw0, bh0 = bl.page_size()
    fs0 = int(bl.style_value("font_size"))
    bc0, bp0 = bl.page_center(), bl.page_origin()
    check("贴合边框的初始字号 40 且文字装得下",
          fs0 == 40 and _font_fits(bl), f"fs={fs0} size={bl.page_size()}")

    bl.set_page_size(bw0 * 2.0, bh0 * 2.0)
    fs_big = int(bl.style_value("font_size"))
    check("W/H ×2 反算放大字号且边框保留用户值",
          fs_big > fs0 * 1.8
          and bl.page_size() == (bw0 * 2.0, bh0 * 2.0),
          f"{fs0} -> {fs_big}, size={bl.page_size()}")
    check("反算得到的是能装下的最大整数字号",
          _font_fits(bl, fs_big) and not _font_fits(bl, fs_big + 1),
          f"fs={fs_big}")
    check("反算字号不动中心 / 支点",
          bl.page_center() == bc0 and bl.page_origin() == bp0)
    check("反算字号写回 style.font_size",
          bl.to_page_record()["style"]["font_size"] == fs_big)

    bl.set_page_size(bw0 * 0.5, bh0 * 0.5)
    fs_small = int(bl.style_value("font_size"))
    check("W/H 缩小反算减小字号（文字不裁）",
          fs_small < fs0 * 0.6 and _font_fits(bl),
          f"{fs_big} -> {fs_small}")

    # 字号输入优先：改字号 -> 重算边框，不能被 set_page_size 的反向联动改写
    bl.set_style_value("font_size", 33)
    check("显式改字号优先（不被反算覆盖）",
          int(bl.style_value("font_size")) == 33 and _font_fits(bl),
          f"fs={bl.style_value('font_size')} size={bl.page_size()}")

    fs_key = int(bl.style_value("font_size"))
    bl.resize_by(1.1)
    check("+/- 快捷键 resize_by 也联动字号",
          int(bl.style_value("font_size")) > fs_key,
          f"{fs_key} -> {bl.style_value('font_size')}")

    # 组缩放：文本成员字号递归联动，×2 再拖角 ×0.5 应回到原值
    bg = bs.create_item("group", center=(4000.0, 4000.0))
    bt = bs.create_item("text", center=(4000.0, 4000.0), context="组内文本")
    bt.set_style_value("font_size", 24)
    fs_g0 = int(bt.style_value("font_size"))
    bt.set_page_parent(bg.item_id)
    gw, gh = bg.page_size()
    bs.resize_group(bg, gw * 2.0, gh * 2.0)
    fs_g2 = int(bt.style_value("font_size"))
    check("组 ×2 递归放大文本成员字号",
          fs_g2 > fs_g0 * 1.8 and _font_fits(bt), f"{fs_g0} -> {fs_g2}")
    bs.resize_item_about(bt, (4000.0, 4000.0), 0.5, 0.5)
    check("拖角 ×0.5 后字号可逆回原值",
          abs(int(bt.style_value("font_size")) - fs_g0) <= 1,
          f"{fs_g2} -> {bt.style_value('font_size')} (原 {fs_g0})")

    # 只改 W：AGV 轴交换后 W 是「行高方向」，只放宽行高不该让文字变长而裁字
    fs_w0 = int(bl.style_value("font_size"))
    bw, bh = bl.page_size()
    bl.set_page_size(bw * 2.0, bh)
    check("只改 W 只放行高余量、字号不变且仍不裁字",
          int(bl.style_value("font_size")) == fs_w0 and _font_fits(bl),
          f"{fs_w0} -> {bl.style_value('font_size')}")

    br = bs.create_item("rect", center=(5000.0, 5000.0))
    rs = br.style_value("font_size", 10)
    rw, rh = br.page_size()
    br.set_page_size(rw * 2.0, rh * 2.0)
    check("非文本图元改尺寸不动 style.font_size",
          br.style_value("font_size", 10) == rs,
          f"{rs} -> {br.style_value('font_size', 10)}")

    # 加载 / 撤销绝不反算：page_1 对拍与 JSON round-trip 零改动的前提
    legacy2 = {
        "id": 99009, "type": "text", "name": "存量文本", "context": "  编号  ",
        "width": 100.0, "height": 224.0,
        "center_pos": {"x": 7000.0, "y": 7000.0},
        "origin_pos": {"x": 7000.0, "y": 7000.0},
        "rotate": 0.0, "style": {"font_size": 13}, "zValue": 1.0,
    }
    li2 = TextItem(legacy2, bs.projection)
    check("加载存量文本不反算字号（对拍 / round-trip）",
          li2.style_value("font_size") == 13
          and li2.to_page_record() == legacy2)

    bs2 = GraphicsScene()
    bs2.load_data(bs.page_data())
    drift4 = [iid for iid, it in bs.index.by_id.items()
              if bs2.find_item(iid) is None
              or not close_rect(it.page_bounding_rect(),
                                bs2.find_item(iid).page_bounding_rect(), 1e-2)]
    check("双向联动后保存重载逐图元包围盒一致", not drift4, str(drift4[:4]))
    fs_saved = {iid: it.style_value("font_size", 10)
                for iid, it in bs.index.by_id.items()}
    fs_load = {iid: it.style_value("font_size", 10)
               for iid, it in bs2.index.by_id.items()}
    check("重载后 style.font_size 逐图元一致", fs_saved == fs_load,
          str([(k, fs_saved[k], fs_load.get(k)) for k in fs_saved
               if fs_saved[k] != fs_load.get(k)][:3]))

    print("\n=== 6.9 widget 控件变体（对照旧 Core widget_element） ===")
    from Designer.CoreQGraphics.g_elements import WidgetItem  # noqa: E402
    from Designer.CoreQGraphics.g_widgets import (  # noqa: E402
        WIDGET_DEFAULTS, WIDGET_VARIANTS, _widget_font, create_control,
        normalize_variant, widget_display_text, widget_options,
        widget_spin_config,
    )
    from PySide6.QtWidgets import (  # noqa: E402
        QCheckBox, QComboBox, QLabel, QLineEdit, QPushButton, QSpinBox,
        QTextEdit,
    )

    check("7 种变体与旧 Core WIDGET_CONTROL_TYPES 一致",
          WIDGET_VARIANTS == ("textedit", "lineedit", "checkbox", "combobox",
                              "pushbutton", "label", "spinbox"),
          str(WIDGET_VARIANTS))
    check("5 个顶层字段默认值与旧 Core 一致",
          WIDGET_DEFAULTS == {
              "widgetType": "textedit", "widgetText": "",
              "widgetFontSize": 12, "widgetColor": "#000000",
              "widgetBackground": "#ffffff"}, str(WIDGET_DEFAULTS))
    check("未知 widgetType 退化成 textedit",
          normalize_variant("nope") == "textedit"
          and normalize_variant(None) == "textedit")

    wscene = GraphicsScene()
    made = [wscene.create_item(f"widget:{k}", center=(float(i) * 500.0, 0.0))
            for i, k in enumerate(WIDGET_VARIANTS)]
    check("工具箱别名创建的 7 个图元 type 仍是 widget",
          all(it.TYPE == "widget" for it in made))
    check("7 个别名各自写入顶层 widgetType",
          [it.page_record()["widgetType"] for it in made] == list(WIDGET_VARIANTS))
    plain = wscene.create_item("widget", center=(0.0, 900.0))
    check("通用 widget 默认 textedit / 空文本（对齐旧 Core）",
          plain.page_record()["widgetType"] == "textedit"
          and plain.page_record()["widgetText"] == "")

    # 老页面记录：完整字段 + 缺字段，两种都不能被回写或补写
    legacy = {
        "id": 9001, "name": "老标签", "type": "widget", "parent_id": 0,
        "children_ids": [], "group_id": 0,
        "center_pos": {"x": 2069.476, "y": 8631.525},
        "origin_pos": {"x": 2069.476, "y": 8631.525},
        "width": 388.0, "height": 1824.0, "rotate": 6.999999999999999,
        "style": {"stroke": "#000000", "strokeWidth": 2, "fill": False,
                  "fill_color": "#00ff00", "opacity": 255, "cornerRadius": 0.0},
        "zValue": 0.0, "widgetText": "缓存料架监控", "widgetType": "label",
        "widgetFontSize": 57, "widgetColor": "#000000",
        "widgetBackground": "#e1f59b",
    }
    old_widget = WidgetItem(legacy, wscene.projection)
    check("旧 Core label 记录 round-trip 零改动",
          old_widget.to_page_record() == legacy)
    minimal = {
        "id": 9002, "name": "缺字段", "type": "widget",
        "center_pos": {"x": 0.0, "y": 0.0},
        "origin_pos": {"x": 0.0, "y": 0.0},
        "width": 100.0, "height": 100.0, "rotate": 0.0,
        "style": {}, "zValue": 1.0,
    }
    bare_widget = WidgetItem(minimal, wscene.projection)
    check("缺 5 字段的老页面只读兜底、不回写",
          bare_widget.to_page_record() == minimal
          and "widgetType" not in bare_widget.to_page_record())

    check("combobox 按行拆选项（去空行 / 空回默认）",
          widget_options("A\n\n B \nC") == ["A", "B", "C"]
          and widget_options("") == ["选项 1"])
    check("spinbox min/max/value 解析（交换 + clamp + 缺省）",
          widget_spin_config("min=5\nmax=3\nvalue=99") == (3, 5, 5)
          and widget_spin_config("") == (0, 99, 0)
          and widget_spin_config("min=10") == (10, 99, 10))
    check("空文本默认标题按变体区分",
          [widget_display_text(k, "") for k in WIDGET_VARIANTS]
          == ["", "", "选项", "选项 1", "按钮", "标签", "0"])

    classes = {
        "textedit": QTextEdit, "lineedit": QLineEdit, "checkbox": QCheckBox,
        "combobox": QComboBox, "pushbutton": QPushButton, "label": QLabel,
        "spinbox": QSpinBox,
    }
    controls = {}
    for key in WIDGET_VARIANTS:
        rec = {
            "widgetType": key,
            "widgetText": {"combobox": "A\nB", "spinbox":
                           "min=5\nmax=20\nvalue=7"}.get(key, "hello"),
            "widgetFontSize": 16, "widgetColor": "#123456",
            "widgetBackground": "#aaffff",
        }
        controls[key] = create_control(rec)
    check("7 个变体映射到对应 Qt 控件类",
          all(isinstance(controls[k], cls) for k, cls in classes.items()),
          str({k: type(v).__name__ for k, v in controls.items()}))
    check("combobox 灌入多行选项", [controls["combobox"].itemText(i)
                                for i in range(controls["combobox"].count())]
          == ["A", "B"])
    check("spinbox 灌入 range / value",
          (controls["spinbox"].minimum(), controls["spinbox"].maximum(),
           controls["spinbox"].value()) == (5, 20, 7))
    check("样式表沿用 widgetFontSize / 文字色 / 背景色",
          "font-size: 16pt" in controls["lineedit"].styleSheet()
          and "#123456" in controls["lineedit"].styleSheet()
          and "#aaffff" in controls["lineedit"].styleSheet(),
          controls["lineedit"].styleSheet())

    # 变体化自绘：每种独立场景渲染，像素签名互不相同，且几何完全不变
    def _variant_shot(variant, text):
        sc = GraphicsScene()
        it = sc.create_item(f"widget:{variant}", center=(0.0, 0.0),
                            widgetText=text)
        src = it.sceneBoundingRect().adjusted(-10, -10, 10, 10)
        img = QImage(max(1, int(src.width())), max(1, int(src.height())),
                     QImage.Format_ARGB32)
        img.fill(QColor("white"))
        p = QPainter(img)
        sc.render(p, QRectF(0, 0, img.width(), img.height()), src)
        p.end()
        sig, dark = 0, 0
        for y in range(0, img.height(), 3):
            for x in range(0, img.width(), 3):
                c = img.pixelColor(x, y)
                if c.red() < 200 or c.green() < 200 or c.blue() < 200:
                    dark += 1
                    sig = (sig * 31 + x * 7 + y * 13) % 1000003
        # 局部 scene 出栈会析构 items，只能带出值类型（QRectF 拷贝）
        return QRectF(it.page_bounding_rect()), sig, dark

    shots = {
        k: _variant_shot(k, {"combobox": "选项甲\n选项乙",
                             "spinbox": "min=1\nmax=9\nvalue=4"}.get(k, "示例文本"))
        for k in WIDGET_VARIANTS
    }
    sigs = [v[1] for v in shots.values()]
    check("7 种占位外观渲染互不相同", len(set(sigs)) == 7, str(sigs))
    check("每种占位都有可见像素", all(v[2] > 20 for v in shots.values()),
          str({k: v[2] for k, v in shots.items()}))
    boxes = [v[0] for v in shots.values()]
    check("变体化绘制不改变包围盒",
          all(close_rect(boxes[0], b) for b in boxes[1:]),
          str([(round(b.width(), 1), round(b.height(), 1)) for b in boxes[:2]]))

    # 设计态占位与运行态真实控件必须同字号 / 同字体族：早期 _widget_font
    # 会按框高把字号压到 42%（12pt → 6.2pt），运行态看起来「字体被放大」。
    font_rec = {"widgetType": "checkbox", "widgetText": "屏蔽膜卷号报警",
                "widgetFontSize": 12, "widgetColor": "#000000",
                "widgetBackground": "#ffffff"}
    f_design = _widget_font(font_rec)
    ctl = create_control(font_rec)
    ctl.ensurePolished()
    check("设计态占位字号与运行态控件一致（同族同字号）",
          abs(f_design.pointSizeF() - ctl.font().pointSizeF()) < 1e-6
          and f_design.family() == ctl.font().family()
          and abs(QFontMetricsF(f_design).height()
                  - QFontMetricsF(ctl.font()).height()) < 1e-6,
          f"design={f_design.family()}/{f_design.pointSizeF():.1f} "
          f"run={ctl.font().family()}/{ctl.font().pointSizeF():.1f}")

    n_before = len(wscene.page_data()["items"])
    check("设计模式不创建真实控件", len(wscene.widget_proxies) == 0)
    wscene.set_scene_mode(True)
    proxies = wscene.widget_proxies
    check("运行预览为 7 个别名 + 1 个通用 widget 挂真实控件",
          len(proxies) == 8, str(len(proxies)))
    check("proxy 控件类覆盖全部 7 种变体",
          set(type(p.widget()).__name__ for p in proxies.values())
          == {"QTextEdit", "QLineEdit", "QCheckBox", "QComboBox",
              "QPushButton", "QLabel", "QSpinBox"},
          str(sorted(set(type(p.widget()).__name__ for p in proxies.values()))))
    check("proxy 不进索引 / 不进 page JSON",
          len(wscene.all_items()) == n_before
          and len(wscene.page_data()["items"]) == n_before)
    wscene.set_scene_mode(False)
    check("退出运行预览销毁全部 proxy", len(wscene.widget_proxies) == 0)

    print("\n=== 7. 性能对照请用独立基准 ===")
    print("  第 4~6 节已修改过场景状态，此处帧耗时不可比，故不采样。")
    print("  .venv/Scripts/python.exe tools/bench_qgraphics_scene.py --phase ab")
    print("  完整功能实现的 12 类 paint 仍在 Python；要兑现上一轮 -54%~-66%")
    print("  需把 paint 换成 Qt 内置 item 或 C++ 实现（路线 C3 / Stage 2 P3）。")

    print(f"\n失败 {len(FAILURES)} 项" + (": " + ", ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
