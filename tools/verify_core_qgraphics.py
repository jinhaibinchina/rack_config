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
    try:
        os.remove(tmp)
    except OSError as exc:
        # 某些运行环境把 os.remove 接管成回收站操作，可能抛 OSError /
        # PermissionError。临时文件是脚本自己刚写的，下次运行会覆盖，
        # 清理失败不该把后面的 §4~§7 回归段落一起截断。
        print(f"  [warn] 临时文件清理失败（不影响断言）: {exc}")

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

    # 偏移参数 (50, 60) 是**视图坐标**；写进 page 记录的应是反投影后的增量。
    dx, dy = mini.projection.inverse_delta(50.0, 60.0)
    ok_offset = True
    for sid, src in orig.items():
        sp, sv, _ = _geo(src)
        cp, cv, _ = _geo(copies[sid])
        for k, (x, y) in sp.items():
            if k in cp:
                ok_offset &= (abs(cp[k][0] - x - dx) < 1e-3
                              and abs(cp[k][1] - y - dy) < 1e-3)
        ok_offset &= len(sv) == len(cv)
        for (x, y), (nx, ny) in zip(sv, cv):
            ok_offset &= (abs(nx - x - dx) < 1e-3
                          and abs(ny - y - dy) < 1e-3)
    check("整棵树（含后代顶点）统一按视图 +50/+60 反投影偏移", ok_offset,
          f"page delta=({dx:.1f}, {dy:.1f})")

    # 黑盒：把副本和原件都投回视图坐标，位移必须恰好 (50, 60)。用正向投影
    # 校验反向换算，符号 / 轴交换写反会立刻暴露，而不是跟着公式自证。
    def view_center(it):
        v = mini.projection.point(*it.page_center())
        return v.x(), v.y()

    ok_view = True
    for sid, src in orig.items():
        ax, ay = view_center(src)
        bx, by = view_center(copies[sid])
        ok_view &= abs(bx - ax - 50.0) < 1e-3 and abs(by - ay - 60.0) < 1e-3
    check("粘贴后每个图元在视图里恰好偏移 +50/+60（不是场景单位）", ok_view)

    # 连续粘贴（中途不改选区）按次数阶梯偏移。改选 / 重新复制会清零计数，
    # 那部分单独放到下面，别把两件事混进同一批粘贴。
    second = mini.paste_clipboard((50.0, 60.0))
    check("连续粘贴各自独立且关系完整",
          len(mini.all_items()) == n0 + 8 and len(second) == 1
          and len(mini.index.descendants(second[0].item_id)) == 3,
          f"n={len(mini.all_items())}")
    d = (second[0].page_center()[0] - first[0].page_center()[0],
         second[0].page_center()[1] - first[0].page_center()[1])
    check("连续粘贴阶梯偏移不重叠（按视图坐标累加）",
          abs(d[0] - dx) < 1e-3 and abs(d[1] - dy) < 1e-3, str(d))

    # 「父子同时选中只按顶层剪一次」原本夹在两次粘贴中间，它调用的
    # copy_selected() 会清零阶梯；挪到这里，顺带验证归零语义。
    mini.clearSelection()
    for it in tree:
        it.setSelected(True)
    check("父子同时选中只按顶层剪一次", mini.copy_selected() == 4,
          str(len(mini._clipboard)))
    check("重新复制后粘贴计数归零", mini._paste_count == 0,
          str(mini._paste_count))

    print("\n=== 6.5b 粘贴阶梯：改选 / 重新复制归零，连续 Ctrl+V 不受影响 ===")
    ps = GraphicsScene()
    pa = ps.create_item("rect", center=(1000.0, 1000.0))
    pb = ps.create_item("rect", center=(1300.0, 1000.0))

    def _paste_view(it):
        v = ps.projection.point(*it.page_center())
        return v.x(), v.y()

    ps.clearSelection()
    pa.setSelected(True)
    ps.copy_selected()
    q1 = ps.paste_clipboard((20.0, 30.0))[0]
    ps.select_items([q1])          # 主窗口 Ctrl+V 后自动选中副本
    check("粘贴后自动选中副本不清零（连续 Ctrl+V 仍阶梯）",
          ps._paste_count == 1, str(ps._paste_count))
    q2 = ps.paste_clipboard((20.0, 30.0))[0]
    d12 = (_paste_view(q2)[0] - _paste_view(q1)[0],
           _paste_view(q2)[1] - _paste_view(q1)[1])
    check("连续第二次粘贴仍是 +20/+30 阶梯",
          abs(d12[0] - 20.0) < 1e-3 and abs(d12[1] - 30.0) < 1e-3,
          str(d12))
    ps.select_items([q2])
    ps.clearSelection()
    pb.setSelected(True)
    check("用户改选图元后粘贴计数归零", ps._paste_count == 0,
          str(ps._paste_count))
    q3 = ps.paste_clipboard((20.0, 30.0))[0]
    d13 = (_paste_view(q3)[0] - _paste_view(q1)[0],
           _paste_view(q3)[1] - _paste_view(q1)[1])
    check("改选后第一批副本回到 1× 起点（不继承 3×）",
          abs(d13[0]) < 1e-3 and abs(d13[1]) < 1e-3, str(d13))
    ps.copy_selected()
    check("重新复制后粘贴计数归零", ps._paste_count == 0,
          str(ps._paste_count))
    q4 = ps.paste_clipboard((20.0, 30.0))[0]
    d4 = (_paste_view(q4)[0] - _paste_view(pb)[0],
          _paste_view(q4)[1] - _paste_view(pb)[1])
    check("换内容后首批副本只偏移 1×（+20/+30）",
          abs(d4[0] - 20.0) < 1e-3 and abs(d4[1] - 30.0) < 1e-3, str(d4))

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

    # Ctrl+D 走同一套视图偏移口径；用独立小场景避免干扰上面的组缩放对拍。
    from Designer.CoreQGraphics.g_projection import SceneProjection  # noqa: E402

    ds = GraphicsScene()
    dsrc = ds.create_item("rect", center=(3000.0, 3000.0), size=(200.0, 100.0))
    ds.clearSelection()
    dsrc.setSelected(True)
    dcpy = ds.duplicate_selected((20.0, 30.0))[0]
    dv0 = ds.projection.point(*dsrc.page_center())
    dv1 = ds.projection.point(*dcpy.page_center())
    check("Ctrl+D 副本在视图里偏移 +20/+30（与粘贴同口径）",
          abs(dv1.x() - dv0.x() - 20.0) < 1e-3
          and abs(dv1.y() - dv0.y() - 30.0) < 1e-3,
          f"({dv1.x() - dv0.x():.1f}, {dv1.y() - dv0.y():.1f})")

    # 反投影增量必须与正向 point 严格互逆：AGV 轴交换 / 取反、非 AGV 只取
    # 反 y，两种投影都查，别让公式只在默认参数下碰巧成立。
    inv_ok = True
    for pr in (SceneProjection(), SceneProjection(agv=False)):
        o = pr.point(0.0, 0.0)
        for dvx, dvy in ((50.0, 60.0), (-12.5, 7.25), (0.0, 100.0)):
            sx, sy = pr.inverse_delta(dvx, dvy)
            q = pr.point(sx, sy)
            inv_ok &= (abs(q.x() - o.x() - dvx) < 1e-9
                       and abs(q.y() - o.y() - dvy) < 1e-9)
    check("视图位移反投影与正向投影互逆（AGV / 非 AGV）", inv_ok)

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

    print("\n=== 6.6b 名称唯一性：改名重复 / 空名一律拒绝 ===")
    un = GraphicsScene()
    na = un.create_item("rect", center=(100.0, 100.0))
    nb = un.create_item("rect", center=(200.0, 200.0))
    na.set_name("唯一甲")
    nb.set_name("唯一乙")
    un.mark_saved()
    before_rec = nb.to_page_record()
    check("重名改名被拒绝（返回 False）", nb.set_name("唯一甲") is False)
    check("被拒后名字与 page 记录一字不动",
          nb.get_name() == "唯一乙" and nb.to_page_record() == before_rec)
    check("被拒的改名不标脏", not un.is_modified())
    owner = un.name_conflict("唯一甲")
    check("name_conflict 指到占用者",
          owner is not None and owner.item_id == na.item_id)
    check("同名不算冲突（exclude_id 传自己）",
          un.name_conflict("唯一甲", na.item_id) is None)
    check("前后空白不算另一个名字",
          nb.set_name("  唯一甲  ") is False and nb.get_name() == "唯一乙")
    check("空名被拒绝", nb.set_name("   ") is False and nb.get_name() == "唯一乙")
    ok, reason = un.rename_item(nb, "唯一甲")
    check("rename_item 给出可直接提示的原因",
          not ok and "已存在同名图元" in reason, reason)
    ok, reason = un.rename_item(nb, "唯一乙B")
    check("换成不冲突的名字可以改", ok and nb.get_name() == "唯一乙B", reason)
    check("改名后旧名字空出来、新名字归自己",
          un.name_conflict("唯一乙") is None and un.name_conflict("唯一乙B") is nb)

    # 组改名：重名时组名与成员前缀**都不动**，不留半成品
    gr = GraphicsScene()
    gm1 = gr.create_item("rect", center=(10.0, 10.0))
    gm2 = gr.create_item("rect", center=(20.0, 20.0))
    gr.clearSelection()
    gm1.setSelected(True)
    gm2.setSelected(True)
    g1 = gr.group_selected()
    gname = g1.get_name()
    taker = gr.create_item("group", center=(400.0, 400.0))
    taker.set_name("占用名")
    mem_before = (gm1.get_name(), gm2.get_name())
    check("组改重名被拒绝", g1.set_name("占用名") is False)
    check("被拒后组名与成员前缀都不动",
          g1.get_name() == gname and (gm1.get_name(), gm2.get_name()) == mem_before,
          f"{g1.get_name()} / {gm1.get_name()} / {gm2.get_name()}")
    suffix = mem_before[0][len(gname) + 1:]
    check("组换成不冲突的名字仍然联动成员前缀",
          g1.set_name("新组名2") is True
          and gm1.get_name() == f"新组名2_{suffix}",
          f"{g1.get_name()} / {gm1.get_name()}")

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

    print("\n=== 6.7b 文本图元：style.cornerRadius 真正生效（离屏渲染） ===")
    from Designer.CoreQGraphics.g_elements import RectItem  # noqa: E402

    def _round_rec(typ: str, radius: float, stroke_width: float) -> dict:
        # 直接构造存量记录，绕开 create_item 的「文字度量 -> 边框」联动：
        # width/height 固定 400×240（AGV 投影后即 60×100 视图像素）。
        return {
            "id": 99100, "type": typ, "name": "圆角文本", "context": "",
            "width": 400.0, "height": 240.0,
            "center_pos": {"x": 0.0, "y": 0.0},
            "origin_pos": {"x": 0.0, "y": 0.0},
            "rotate": 0.0, "zValue": 1.0,
            "style": {"fill": True, "fill_color": "#ff0000",
                      "stroke": "#000000", "strokeWidth": stroke_width,
                      "cornerRadius": radius, "opacity": 255,
                      "font_size": 12},
        }

    def _paint_item(item) -> QImage:
        img = QImage(240, 240, QImage.Format_ARGB32)
        img.fill(Qt.white)
        p = QPainter(img)
        p.translate(120, 120)
        item.paint(p, None)
        p.end()
        return img

    img_round = _paint_item(TextItem(_round_rec("text", 40.0, 0), ts.projection))
    img_square = _paint_item(TextItem(_round_rec("text", 0.0, 0), ts.projection))
    # 局部矩形 (-30,-50,60,100)，圆角 rx=ry=10；左上角内缩 2px 的圆外点
    px, py = 120 - 30 + 2, 120 - 50 + 2
    check("text 圆角=场景40：四角被切掉而内部仍填充（圆角真正生效）",
          img_round.pixelColor(px, py) == QColor(Qt.white)
          and img_round.pixelColor(120, 120) == QColor("#ff0000"),
          f"corner={img_round.pixelColor(px, py).name()} "
          f"center={img_round.pixelColor(120, 120).name()}")
    check("text 圆角=0 仍是直角填充（存量页面逐像素不变）",
          img_square.pixelColor(px, py) == QColor("#ff0000"),
          img_square.pixelColor(px, py).name())
    # 描边分支与 RectItem 同口径：空文本下两者画的是同一个圆角矩形。
    img_text_stroke = _paint_item(
        TextItem(_round_rec("text", 40.0, 2), ts.projection))
    img_rect_stroke = _paint_item(
        RectItem(_round_rec("rect", 40.0, 2), ts.projection))
    check("text 描边圆角与 RectItem 逐像素一致",
          pixel_diff(img_text_stroke, img_rect_stroke) == 0,
          str(pixel_diff(img_text_stroke, img_rect_stroke)))

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
    from Designer.Core.elements import widget_element  # noqa: E402
    from Designer.CoreQGraphics.g_elements import WidgetItem  # noqa: E402
    from Designer.CoreQGraphics.g_widgets import (  # noqa: E402
        WIDGET_DEFAULTS, WIDGET_VARIANTS, _widget_font, create_control,
        normalize_variant, widget_display_text, widget_options,
        widget_range_config, widget_spin_config,
    )
    from Designer.CoreQGraphics.runtime.stage import _default_apply  # noqa: E402
    from PySide6.QtWidgets import (  # noqa: E402
        QCheckBox, QComboBox, QLabel, QLineEdit, QProgressBar, QPushButton,
        QSlider, QSpinBox, QTextEdit,
    )

    check("前 7 种变体与旧 Core WIDGET_CONTROL_TYPES 一致",
          WIDGET_VARIANTS[:7] == tuple(widget_element.WIDGET_CONTROL_TYPES),
          str(WIDGET_VARIANTS[:7]))
    check("追加进度条 / 滑动条两种变体",
          WIDGET_VARIANTS[7:] == ("progressbar", "slider")
          and len(WIDGET_VARIANTS) == 9, str(WIDGET_VARIANTS))
    check("6 个顶层字段默认值与旧 Core 一致（含字体族扩展）",
          WIDGET_DEFAULTS == {
              "widgetType": "textedit", "widgetText": "",
              "widgetFontSize": 12, "widgetFontFamily": "",
              "widgetColor": "#000000",
              "widgetBackground": "#ffffff"}, str(WIDGET_DEFAULTS))
    check("未知 widgetType 退化成 textedit",
          normalize_variant("nope") == "textedit"
          and normalize_variant(None) == "textedit")

    wscene = GraphicsScene()
    made = [wscene.create_item(f"widget:{k}", center=(float(i) * 500.0, 0.0))
            for i, k in enumerate(WIDGET_VARIANTS)]
    check("工具箱别名创建的 9 个图元 type 仍是 widget",
          all(it.TYPE == "widget" for it in made))
    check("9 个别名各自写入顶层 widgetType",
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
    check("缺 widget 字段的老页面只读兜底、不回写",
          bare_widget.to_page_record() == minimal
          and "widgetType" not in bare_widget.to_page_record())

    check("combobox 按行拆选项（去空行 / 空回默认）",
          widget_options("A\n\n B \nC") == ["A", "B", "C"]
          and widget_options("") == ["选项 1"])
    check("spinbox min/max/value 解析（交换 + clamp + 缺省）",
          widget_spin_config("min=5\nmax=3\nvalue=99") == (3, 5, 5)
          and widget_spin_config("") == (0, 99, 0)
          and widget_spin_config("min=10") == (10, 99, 10))
    check("progressbar / slider 复用 widgetText 解析范围与方向",
          widget_range_config("") == (0, 100, 50, "horizontal")
          and widget_range_config("min=8\nmax=2\nvalue=99\norientation=v")
          == (2, 8, 8, "vertical")
          and widget_range_config("min=7\nmax=7\norientation=横向")
          == (7, 7, 7, "horizontal"))
    check("空文本默认标题按变体区分",
          [widget_display_text(k, "") for k in WIDGET_VARIANTS]
          == ["", "", "选项", "选项 1", "按钮", "标签", "0", "50%", "50"])

    classes = {
        "textedit": QTextEdit, "lineedit": QLineEdit, "checkbox": QCheckBox,
        "combobox": QComboBox, "pushbutton": QPushButton, "label": QLabel,
        "spinbox": QSpinBox, "progressbar": QProgressBar, "slider": QSlider,
    }
    controls = {}
    for key in WIDGET_VARIANTS:
        rec = {
            "widgetType": key,
            "widgetText": {
                "combobox": "A\nB",
                "spinbox": "min=5\nmax=20\nvalue=7",
                "progressbar": "min=10\nmax=30\nvalue=20",
                "slider": "min=-5\nmax=5\nvalue=0\norientation=vertical",
            }.get(key, "hello"),
            "widgetFontSize": 16, "widgetColor": "#123456",
            "widgetBackground": "#aaffff",
        }
        controls[key] = create_control(rec)
    check("9 个变体映射到对应 Qt 控件类",
          all(isinstance(controls[k], cls) for k, cls in classes.items()),
          str({k: type(v).__name__ for k, v in controls.items()}))
    check("combobox 灌入多行选项", [controls["combobox"].itemText(i)
                                for i in range(controls["combobox"].count())]
          == ["A", "B"])
    check("spinbox 灌入 range / value",
          (controls["spinbox"].minimum(), controls["spinbox"].maximum(),
           controls["spinbox"].value()) == (5, 20, 7))
    check("进度条 / 滑动条灌入 range / value / orientation",
          (controls["progressbar"].minimum(),
           controls["progressbar"].maximum(),
           controls["progressbar"].value(),
           controls["progressbar"].orientation()) == (10, 30, 20, Qt.Horizontal)
          and (controls["slider"].minimum(), controls["slider"].maximum(),
               controls["slider"].value(), controls["slider"].orientation())
          == (-5, 5, 0, Qt.Vertical))
    check("运行态标签 setValue 能推进度条 / 滑动条",
          (_default_apply(controls["progressbar"], "27") is None
           and _default_apply(controls["slider"], "-4") is None
           and controls["progressbar"].value() == 27
           and controls["slider"].value() == -4))
    check("样式表沿用 widgetFontSize / 文字色 / 背景色",
          "font-size: 16pt" in controls["lineedit"].styleSheet()
          and "#123456" in controls["lineedit"].styleSheet()
          and "#aaffff" in controls["lineedit"].styleSheet(),
          controls["lineedit"].styleSheet())
    check("新增变体 QSS 显式画 chunk / groove / handle",
          "QProgressBar::chunk" in controls["progressbar"].styleSheet()
          and "QSlider::groove:horizontal" in controls["slider"].styleSheet()
          and "QSlider::handle:vertical" in controls["slider"].styleSheet())

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
        k: _variant_shot(k, {
            "combobox": "选项甲\n选项乙",
            "spinbox": "min=1\nmax=9\nvalue=4",
            "progressbar": "min=0\nmax=100\nvalue=65",
            "slider": "min=0\nmax=100\nvalue=35",
        }.get(k, "示例文本"))
        for k in WIDGET_VARIANTS
    }
    sigs = [v[1] for v in shots.values()]
    check("9 种占位外观渲染互不相同",
          len(set(sigs)) == len(WIDGET_VARIANTS), str(sigs))
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
    check("运行预览为 9 个别名 + 1 个通用 widget 挂真实控件",
          len(proxies) == 10, str(len(proxies)))
    check("proxy 控件类覆盖全部 9 种变体",
          set(type(p.widget()).__name__ for p in proxies.values())
          == {"QTextEdit", "QLineEdit", "QCheckBox", "QComboBox",
              "QPushButton", "QLabel", "QSpinBox", "QProgressBar",
              "QSlider"},
          str(sorted(set(type(p.widget()).__name__ for p in proxies.values()))))
    check("proxy 不进索引 / 不进 page JSON",
          len(wscene.all_items()) == n_before
          and len(wscene.page_data()["items"]) == n_before)
    wscene.set_scene_mode(False)
    check("退出运行预览销毁全部 proxy", len(wscene.widget_proxies) == 0)

    # 新增变体也走同一份 5 顶层字段：JSON 往返后记录逐字不变。
    rt = GraphicsScene()
    rt.create_item("widget:progressbar", center=(0.0, 0.0),
                   widgetText="min=0\nmax=200\nvalue=75")
    rt.create_item("widget:slider", center=(500.0, 0.0),
                   widgetText="min=-10\nmax=10\nvalue=3\norientation=vertical")
    rt_data = rt.page_data()
    rt2 = GraphicsScene()
    rt2.load_data(json.loads(json.dumps(rt_data, ensure_ascii=False)))
    check("进度条 / 滑动条 page JSON 往返零改动",
          rt2.page_data() == rt_data,
          str([r.get("widgetType") for r in rt_data["items"]]))

    print("\n=== 6.10 删组递归删成员（对照旧 Core base_element.Delete） ===")
    dl = GraphicsScene()
    g1 = dl.create_item("group", center=(300.0, 300.0), size=(200.0, 160.0))
    g2 = dl.create_item("group", center=(320.0, 320.0), size=(80.0, 80.0))
    bx = dl.create_item("rect", center=(310.0, 310.0), size=(40.0, 30.0))
    wd = dl.create_item("widget:label", center=(340.0, 340.0), size=(100.0, 26.0))
    keep = dl.create_item("rect", center=(900.0, 900.0), size=(50.0, 50.0))
    g2.set_page_parent(g1.item_id)
    bx.set_page_parent(g2.item_id)
    wd.set_page_parent(g1.item_id)
    g1.set_page_field("children_ids", [g2.item_id, wd.item_id])
    g2.set_page_field("children_ids", [bx.item_id])
    dl.index.rebuild_links()
    check("删前组树三层 4 个图元", len(dl.all_items()) == 5
          and len(dl.index.descendants(g1.item_id)) == 3,
          f"n={len(dl.all_items())} desc={len(dl.index.descendants(g1.item_id))}")

    dl.set_scene_mode(True)
    check("运行态组内控件已挂 proxy", wd.item_id in dl.widget_proxies)
    removed = dl.delete_items([g1])
    check("删组返回组 + 全部后代的数量", removed == 4, str(removed))
    check("删组后场景只剩组外图元",
          [it.item_id for it in dl.all_items()] == [keep.item_id],
          str([it.item_id for it in dl.all_items()]))
    check("删组后索引/order/链接无残留",
          not ({g1.item_id, g2.item_id, bx.item_id, wd.item_id}
               & set(dl.index.by_id))
          and not ({g1.item_id, g2.item_id, bx.item_id, wd.item_id}
                   & set(dl.index.order))
          and not any(g1.item_id in v for v in dl.index.children_of.values()))
    check("删组连带移除运行态 proxy",
          len(dl.widget_proxies) == 0, str(list(dl.widget_proxies)))
    check("组外图元不受影响（父子/尺寸不变）",
          keep.parent_id == 0 and keep.page_size() == (50.0, 50.0),
          str(keep.page_size()))
    check("删组后 page_data 与场景一致",
          len(dl.page_data()["items"]) == 1, str(len(dl.page_data()["items"])))
    dl.set_scene_mode(False)

    # 删成员只删自己，父组仍在（父子关系单向：拥有者删成员，成员不删父）
    solo = GraphicsScene()
    sg = solo.create_item("group", center=(100.0, 100.0), size=(200.0, 200.0))
    sa = solo.create_item("rect", center=(110.0, 110.0), size=(30.0, 30.0))
    sb = solo.create_item("rect", center=(150.0, 150.0), size=(30.0, 30.0))
    sa.set_page_parent(sg.item_id)
    sb.set_page_parent(sg.item_id)
    sg.set_page_field("children_ids", [sa.item_id, sb.item_id])
    solo.index.rebuild_links()
    solo.delete_items([sa])
    check("删成员不连带父组，且父组 children_ids 同步剔除",
          sg.item_id in solo.index.by_id
          and sa.item_id not in solo.index.by_id
          and sg.children_ids == [sb.item_id]
          and sb.parent_id == sg.item_id,
          f"children={sg.children_ids}")

    print("\n=== 6.11 组复制保持组内 Z 序（含 zValue 相同的数组顺序兜底） ===")

    def check_group_copy_z(z_values, label):
        zs = GraphicsScene()
        members = []
        for i, z in enumerate(z_values):
            it = zs.create_item("rect", center=(1000.0 + i * 300.0, 1000.0))
            it.set_page_field("zValue", z)
            it.setSelected(True)
            members.append(it)
        grp = zs.group_selected()
        # 原 Z 序：按 zValue 稳定排序，同值按 index.order（JSON 数组顺序）
        orig_order = [it.item_id for it in zs.index.sorted_items()]
        zs.clearSelection()
        grp.setSelected(True)
        zs.copy_selected()
        snap = zs._clipboard
        snap_z = [float(r.get("zValue", 0.0) or 0.0) for _, r in snap]
        check(f"{label}：复制快照按原 Z 序排列（不是父在子前的树序）",
              snap_z == sorted(snap_z), f"snap_z={snap_z}")

        old_ids = set(zs.index.order)
        made = zs.paste_clipboard((500.0, 500.0))
        new_ids = sorted(i for i in zs.index.order if i not in old_ids)
        zmap = {snap[i][0]: zs.find_item(new_ids[i])
                for i in range(min(len(snap), len(new_ids)))}
        ok_map = (len(made) == 1 and len(zmap) == len(snap)
                  and all(v is not None for v in zmap.values()))
        check(f"{label}：副本 id 配对完整", ok_map,
              f"map={len(zmap)} snap={len(snap)}")
        if not ok_map:
            return
        copies = [zmap[i] for i in orig_order]
        by_z = sorted(copies, key=lambda it: it.zValue())
        check(f"{label}：副本整体保持原 Z 序（含组框）",
              [it.item_id for it in by_z] == [it.item_id for it in copies],
              f"by_z={[it.item_id for it in by_z]} "
              f"want={[it.item_id for it in copies]}")
        gcopy = zmap[grp.item_id]
        check(f"{label}：组框复制后仍在所有成员之上",
              all(gcopy.zValue() > zmap[m.item_id].zValue() for m in members),
              f"group={gcopy.zValue()} "
              f"members={[zmap[m.item_id].zValue() for m in members]}")

    check_group_copy_z([5.0, 1.0, 3.0], "z 值乱序")
    check_group_copy_z([1.0, 1.0, 1.0], "z 值全相同")

    # 模板实例化走另一条捕获路径（树序 DFS），同值兜底同样必须是模板
    # items 的数组顺序。这里故意让「数组顺序」和「DFS 顺序」不同：
    # 数组 A,B,C,组；从组出发 DFS 是 组,A,C,B（C 挂在 A 下面）。
    import copy as _copy
    from types import SimpleNamespace
    tsrc = GraphicsScene()
    ta = tsrc.create_item("rect", center=(1000.0, 1000.0))
    tb = tsrc.create_item("rect", center=(1300.0, 1000.0))
    tc = tsrc.create_item("rect", center=(1600.0, 1000.0))
    tg = tsrc.create_item("group", center=(1300.0, 1400.0))
    for it in (ta, tb, tc, tg):
        it.set_page_field("zValue", 1.0)   # 全部同值，只能靠数组顺序定层级
    tg.set_page_field("zValue", 2.0)
    ta.set_page_parent(tg.item_id)
    tb.set_page_parent(tg.item_id)
    tc.set_page_parent(ta.item_id)
    tg.set_page_field("children_ids", [ta.item_id, tb.item_id])
    ta.set_page_field("children_ids", [tc.item_id])
    tsrc.index.rebuild_links()
    tpl_items = [_copy.deepcopy(tsrc.index.by_id[i].to_page_record())
                 for i in (ta.item_id, tb.item_id, tc.item_id, tg.item_id)]
    tpl = SimpleNamespace(items=tpl_items, root_id=tg.item_id)

    tscene = GraphicsScene()
    tscene.instantiate_template(tpl, QPointF(1300.0, 1400.0))
    tnew = sorted(tscene.index.order)
    by_z = sorted((tscene.find_item(i) for i in tnew),
                  key=lambda it: it.zValue())
    got_keys = [(it.TYPE, round(it.page_center()[0], 1)) for it in by_z]
    want_keys = [("rect", 1000.0), ("rect", 1300.0),
                 ("rect", 1600.0), ("group", 1300.0)]
    check("模板实例化同值层级按数组顺序（不是 DFS 树序）",
          got_keys == want_keys, f"got={got_keys} want={want_keys}")

    print("\n=== 6.12 自定义支点子图元：父旋转时父系位姿恒定 ===")
    # 报障场景：A 的旋转中心 ≠ 可视中心（O + 右键设到绝对点），B 设为 A 的父，
    # 旋转 B 时 A 必须在父坐标系里保持刚体位姿，图形本体也不能漂。
    # 顶点类不能拿 frame_corners（那是旋转后的 AABB 角），要取真实顶点。
    def rigid_points(scene, it):
        if hasattr(it, "_live_page_points"):
            return [it.world_to_local(x, y)
                    for x, y in it._live_page_points()]
        p = scene.projection
        return [it.world_to_local(*p.inverse_point(q.x(), q.y()))
                for q in it.frame_corners()]

    for typ in ("rect", "line", "triangle", "polygon", "path"):
        ps = GraphicsScene()
        pb = ps.create_item("rect", center=(1000.0, 1000.0))
        pb.set_page_size(200.0, 100.0)
        pa = ps.create_item(typ, center=(1200.0, 1000.0))
        ps.clearSelection()
        pa.setSelected(True)
        ps.set_selected_origin(1250.0, 1050.0)       # O + 右键：绝对点作支点
        pa.set_page_parent(pb.item_id)
        ps.index.rebuild_links()
        c0 = pa.page_local_center()
        o0 = pa.page_local_origin()
        a0 = pa.page_local_angle()
        pts0 = rigid_points(ps, pa)
        pb.set_page_angle(30.0)
        c1 = pa.page_local_center()
        o1 = pa.page_local_origin()
        a1 = pa.page_local_angle()
        pts1 = rigid_points(ps, pa)
        dev = max([abs(c1[0] - c0[0]), abs(c1[1] - c0[1]),
                   abs(o1[0] - o0[0]), abs(o1[1] - o0[1]), abs(a1 - a0)]
                  + [max(abs(u[0] - v[0]), abs(u[1] - v[1]))
                     for u, v in zip(pts0, pts1)])
        check("%s：父旋转 30° 后子图元父系位姿零漂移" % typ,
              len(pts0) == len(pts1) and dev < 1e-3,
              f"pts={len(pts0)} max_dev={dev:.6f}")

    # O + 右键对「所有选中图元」生效：父自己也可能同时被改了支点
    qs = GraphicsScene()
    qb = qs.create_item("rect", center=(1000.0, 1000.0))
    qb.set_page_size(200.0, 100.0)
    qa = qs.create_item("rect", center=(1200.0, 1000.0))
    qs.clearSelection()
    qa.setSelected(True)
    qb.setSelected(True)
    qs.set_selected_origin(1250.0, 1050.0)
    qa.set_page_parent(qb.item_id)
    qs.index.rebuild_links()
    c0, o0 = qa.page_local_center(), qa.page_local_origin()
    p0 = rigid_points(qs, qa)
    qb.set_page_angle(30.0)
    c1, o1 = qa.page_local_center(), qa.page_local_origin()
    p1 = rigid_points(qs, qa)
    dev = max([abs(c1[0] - c0[0]), abs(c1[1] - c0[1]),
               abs(o1[0] - o0[0]), abs(o1[1] - o0[1])]
              + [max(abs(u[0] - v[0]), abs(u[1] - v[1]))
                 for u, v in zip(p0, p1)])
    check("父也带自定义支点时，子的图形四角在父系里仍恒定",
          dev < 1e-3, f"max_dev={dev:.6f}")

    # 报障根因：Qt 拖动（moveBy / 双击跟手）只改 pos，走 shift_origin_by；
    # 旧版「默认支点」分支只更新 _page_center、没同步 _origin_xy，导致
    # live_page_pose 把默认支点误判成自定义支点（支点＝拖之前的旧中心）。
    # 父随后旋转就绕旧中心转，整棵子树相对父漂移，面板父系 X/Y 也跟着变。
    for amt in ((12.0, -8.0), (-30.0, 20.0)):
        ds = GraphicsScene()
        db = ds.create_item("rect", center=(1000.0, 1000.0))
        db.set_page_size(200.0, 100.0)
        da = ds.create_item("rect", center=(1200.0, 1000.0))
        da.set_page_size(100.0, 80.0)
        da.set_page_parent(db.item_id)
        ds.index.rebuild_links()
        ds.clearSelection()
        da.setSelected(True)
        ds.set_selected_origin(1250.0, 1050.0)
        db.moveBy(amt[0], amt[1])          # Qt 层拖动 / 双击跟手
        live = db.live_page_pose()[:2]
        check("拖动后默认支点的 _origin_xy 与实时中心一致 %s" % (amt,),
              abs(db._origin_xy[0] - live[0]) < 1e-6
              and abs(db._origin_xy[1] - live[1]) < 1e-6,
              f"origin={db._origin_xy} live={live}")
        c0, o0 = da.page_local_center(), da.page_local_origin()
        db.set_page_angle(30.0)
        c1, o1 = da.page_local_center(), da.page_local_origin()
        dev = max(abs(c1[0] - c0[0]), abs(c1[1] - c0[1]),
                  abs(o1[0] - o0[0]), abs(o1[1] - o0[1]))
        check("父被 Qt 拖动 %s 后再旋转：子父系位姿零漂移" % (amt,),
              dev < 1e-3, f"max_dev={dev:.6f}")

    print("\n=== 6.13 图元锁定：可选字段 / 位姿 API 过滤（独立小场景） ===")
    from Designer.CoreQGraphics.g_scene import GraphicsScene
    from PySide6.QtWidgets import QGraphicsItem  # noqa: E402

    lk = GraphicsScene()
    la = lk.create_item("rect", center=(1000.0, 1000.0), size=(400.0, 200.0))
    lb = lk.create_item("rect", center=(1400.0, 1000.0), size=(400.0, 200.0))
    lc = lk.create_item("rect", center=(1800.0, 1000.0), size=(400.0, 200.0))
    ld = lk.create_item("rect", center=(2600.0, 1000.0), size=(400.0, 200.0))
    ids = [la.item_id, lb.item_id, lc.item_id, ld.item_id]
    check("存量记录没有 locked 键、缺省全部未锁定",
          all("locked" not in r for r in lk.page_data()["items"])
          and not any(lk.find_item(i).is_locked() for i in ids))
    box0 = la.sceneBoundingRect()
    n_lock = lk.set_items_locked([ids[0]], True)
    check("批量上锁只改一个并写进 page 记录",
          n_lock == 1 and la.is_locked()
          and la.to_page_record().get("locked") is True
          and not lb.is_locked())
    check("上锁不改几何（包围盒逐项相等）",
          close_rect(box0, la.sceneBoundingRect()))
    check("pose_blocked / editable_pose 口径",
          lk.pose_blocked(la) and not lk.pose_blocked(lb)
          and [i.item_id for i in lk.editable_pose([la, lb])] == [ids[1]])

    lk.clearSelection()
    for it in (la, lb, lc, ld):
        it.setSelected(True)
    p0, b0 = la.page_center(), lb.page_center()
    lk.align_selected("left")
    check("左对齐跳过锁定项、其它图元照常移动",
          la.page_center() == p0 and lb.page_center() != b0)
    check("拖角缩放拒绝锁定项、接受未锁定项",
          not lk.resize_item_about(la, (0.0, 0.0), 1.2, 1.2)
          and lk.resize_item_about(lb, (0.0, 0.0), 1.2, 1.2))
    lk.clearSelection()
    la.setSelected(True)
    check("旋转支点设置跳过锁定项",
          lk.set_selected_origin(1234.0, 567.0) == 0)
    lb.setSelected(True)
    check("旋转支点设置对未锁定项仍生效",
          lk.set_selected_origin(1234.0, 567.0) == 1)
    check("旋转支点复位也跳过锁定项",
          lk.reset_selected_origin() == 1)
    la.setSelected(False)
    lb.setSelected(False)

    # distribute：4 个图元里锁中间那个，只应移动另一个中间项
    for it, cx in zip((la, lb, lc, ld), (1000.0, 1400.0, 1800.0, 2600.0)):
        it.set_page_center(cx, 1000.0)
    lk.set_items_locked([ids[0]], False)
    lk.set_items_locked([ids[1]], True)
    lk.clearSelection()
    for it in (la, lb, lc, ld):
        it.setSelected(True)
    lc0 = lc.page_center()[0]
    lk.distribute_selected(True)
    check("水平等距跳过锁定中间项、未锁定中间项照常移动",
          abs(lb.page_center()[0] - 1400.0) < 1e-6
          and abs(lc.page_center()[0] - lc0) > 1e-6)

    # 组：成员锁定后整组位姿受保护（防「拖父组把锁定的成员带走」）
    grp = lk.create_item("group", center=(3000.0, 1000.0), size=(400.0, 300.0))
    kid = lk.create_item("rect", center=(3000.0, 1000.0), size=(100.0, 60.0))
    kid.set_page_parent(grp.item_id)
    grp.set_page_field("children_ids", [kid.item_id])
    lk.index.rebuild_links()
    kid.set_locked(True)
    check("组内成员锁定 -> 整组位姿受保护",
          lk.pose_blocked(grp) and lk.editable_pose([grp]) == [])
    lk.set_movable_gate(True)
    check("锁定项拿不到 ItemIsMovable，未锁定项仍能拿到",
          not (lb.flags() & QGraphicsItem.ItemIsMovable)
          and not (grp.flags() & QGraphicsItem.ItemIsMovable)
          and bool(la.flags() & QGraphicsItem.ItemIsMovable))
    lk.set_movable_gate(False)

    # 落盘 / 重载：locked 是可选顶层字段，旧页缺省为零改动
    os.makedirs("tools/_out", exist_ok=True)
    tmp_lock = "tools/_out/lock_roundtrip.json"
    lk.save_page(tmp_lock)
    with open(tmp_lock, encoding="utf-8") as fp:
        disk = json.load(fp)
    written = {r["id"] for r in disk["items"] if r.get("locked")}
    check("落盘只给锁定的图元写 locked", written == {ids[1], kid.item_id},
          str(sorted(written)))
    rl = GraphicsScene()
    rl.load_data(disk)
    check("重载后锁定状态保持、未锁定项仍缺省",
          rl.find_item(ids[1]).is_locked()
          and rl.find_item(kid.item_id).is_locked()
          and not rl.find_item(ids[0]).is_locked())
    rl.set_items_locked([i for i in rl.index.order], False)
    check("解锁后 locked 键彻底消失（回到存量记录原貌）",
          all("locked" not in r for r in rl.page_data()["items"]))
    try:
        os.remove(tmp_lock)
    except OSError:
        pass

    print("\n=== 6.14 贝塞尔曲线图元：精确曲线 / 四点落子 / 变换（独立小场景） ===")
    from Designer.CoreQGraphics.g_scene import GraphicsScene  # noqa: E402
    from Designer.CoreQGraphics.g_elements import BezierItem  # noqa: E402
    from Designer.CoreQGraphics.g_path import PATH_SEGMENTS_KEY  # noqa: E402
    from Designer.CoreQGraphics.g_boolean import supports_boolean  # noqa: E402

    def _segments(rec):
        return rec.get(PATH_SEGMENTS_KEY) or []

    def _curve(rec):
        return next((d for d in _segments(rec) if d["kind"] == "curve"), {})

    bz = GraphicsScene()
    b1 = bz.create_item("bezier", center=(1000.0, 1000.0))
    rec0 = b1.page_record()
    check("bezier 已注册，默认记录是 move + curve",
          isinstance(b1, BezierItem)
          and [d["kind"] for d in _segments(rec0)] == ["move", "curve"])
    c0 = _curve(b1.to_page_record())
    check("c1/c2 与端点都进 path_segments、vertices 折线兜底在",
          all(k in c0 for k in ("c1x", "c1y", "c2x", "c2y", "x", "y"))
          and len(rec0.get("vertices") or []) >= 2
          and rec0["style"]["fill"] is False)
    check("开放曲线：不填充、不参与布尔、4 个控制点进吸附表",
          not b1.snap_closed() and not supports_boolean(b1)
          and len(b1.snap_points()[0]) == 4
          and len(b1._bezier_points_local()) == 4)

    c1_before = (c0["c1x"], c0["c1y"])
    b1.rotate_by(15.0)
    rec_rot = b1.to_page_record()
    cr = _curve(rec_rot)
    check("旋转后仍是精确曲线且 c1/c2 同步刚体变换",
          [d["kind"] for d in _segments(rec_rot)] == ["move", "curve"]
          and (abs(cr["c1x"] - c1_before[0])
               + abs(cr["c1y"] - c1_before[1])) > 1.0)
    w0, h0 = b1.page_size()
    b1.set_page_size(w0 * 1.5, h0 * 1.2)
    rec_sc = b1.to_page_record()
    check("改宽高仍是精确曲线且 c1/c2 同步缩放",
          [d["kind"] for d in _segments(rec_sc)] == ["move", "curve"]
          and abs(_curve(rec_sc)["c1x"] - cr["c1x"]) > 1.0)
    before_move = _curve(b1.to_page_record())
    b1.moveBy(20.0, 30.0)
    after_move = _curve(b1.to_page_record())
    check("moveBy 平移后 c1/c2 同步平移",
          abs(after_move["c1x"] - before_move["c1x"]) > 1e-6
          or abs(after_move["c1y"] - before_move["c1y"]) > 1e-6)

    # CAD 四点落子：起点 / 控制点 1 / 控制点 2 / 终点
    bz2 = GraphicsScene()
    draft = bz2.begin_draw_tool("bezier")
    check("绘制工具按 4 击落子、绘制期图元可见",
          bz2._draw_clicks("bezier") == 4 and draft is not None
          and draft.isVisible() and not bz2.drawing_polygon())
    four = [(1000.0, 1200.0), (1100.0, 800.0),
            (1300.0, 1200.0), (1400.0, 800.0)]
    for x, y in four[:3]:
        bz2.draw_add_point(QPointF(x, y))
        bz2.draw_preview(QPointF(x + 50.0, y + 50.0))
    check("前三击仍在绘制、曲线实时生成",
          bz2.drawing_active() and draft._segment_mode
          and draft._path_local is not None)
    bz2.draw_add_point(QPointF(*four[3]))
    check("第四击自动落定、不留临时图元",
          not bz2.drawing_active() and len(bz2.all_items()) == 1
          and not bz2.all_items()[0]._drawing)
    done = bz2.all_items()[0].to_page_record()
    seg = _segments(done)
    cv = _curve(done)
    check("落点顺序精确等于 P0 / C1 / C2 / P3",
          len(seg) == 2 and seg[0]["kind"] == "move"
          and (seg[0]["x"], seg[0]["y"]) == four[0]
          and (cv["c1x"], cv["c1y"]) == four[1]
          and (cv["c2x"], cv["c2y"]) == four[2]
          and (cv["x"], cv["y"]) == four[3],
          f"{seg}")

    # 手工 JSON 只有 4 个 vertices 时自动补出精确曲线
    raw = {
        "id": 1, "name": "raw_bezier", "type": "bezier",
        "parent_id": 0, "children_ids": [], "group_id": 0,
        "center_pos": {"x": 1000.0, "y": 1000.0},
        "origin_pos": {"x": 1000.0, "y": 1000.0},
        "width": 400.0, "height": 200.0, "rotate": 0.0, "zValue": 1.0,
        "style": {"stroke": "#000000", "strokeWidth": 2, "fill": False},
        "vertices": [{"x": x, "y": y} for x, y in four],
    }
    bz3 = GraphicsScene()
    bz3.load_data({"backgroundColor": "#ffffff", "items": [raw]})
    manual = bz3.all_items()[0]
    check("只有 vertices 的手工 JSON 自动补出精确曲线",
          len(bz3.all_items()) == 1 and manual._segment_mode
          and [d["kind"] for d in _segments(manual.to_page_record())]
          == ["move", "curve"])

    # 剪贴板 / 模板走 _shift_record：精确段 c1/c2 与折线兜底都要一起平移
    hand = bz2.all_items()[0]
    bz2.clearSelection()
    hand.setSelected(True)
    bz2.copy_selected()
    copies = bz2.paste_clipboard((50.0, 60.0))
    copy_rec = copies[0].to_page_record()
    orig_cv = _curve(hand.to_page_record())
    copy_cv = _curve(copy_rec)
    check("复制 / 粘贴同步平移 c1/c2（shift_segments 口径）",
          [d["kind"] for d in _segments(copy_rec)] == ["move", "curve"]
          and (abs(copy_cv["c1x"] - orig_cv["c1x"])
               + abs(copy_cv["c1y"] - orig_cv["c1y"])) > 1e-6)

    os.makedirs("tools/_out", exist_ok=True)
    tmp_bz = "tools/_out/bezier_roundtrip.json"
    bz2.save_page(tmp_bz)
    with open(tmp_bz, encoding="utf-8") as fp:
        first_text = fp.read()
    bz4 = GraphicsScene()
    bz4.load_data(json.loads(first_text))
    bz4.save_page(tmp_bz)
    with open(tmp_bz, encoding="utf-8") as fp:
        second_text = fp.read()
    check("贝塞尔页 save → load → save 字节一致",
          first_text == second_text)
    try:
        os.remove(tmp_bz)
    except OSError:
        pass

    print("\n=== 7. 性能对照请用独立基准 ===")
    print("  第 4~6 节已修改过场景状态，此处帧耗时不可比，故不采样。")
    print("  .venv/Scripts/python.exe tools/bench_qgraphics_scene.py --phase ab")
    print("  完整功能实现的 13 类 paint 仍在 Python；要兑现上一轮 -54%~-66%")
    print("  需把 paint 换成 Qt 内置 item 或 C++ 实现（路线 C3 / Stage 2 P3）。")

    print(f"\n失败 {len(FAILURES)} 项" + (": " + ", ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
