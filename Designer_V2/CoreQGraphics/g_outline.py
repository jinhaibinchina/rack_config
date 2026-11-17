"""开放线条 -> 闭合面域路径图元（交点切分 + 平面面提取）。

与 ``g_boolean.py`` 的布尔结果同构：产出 ``path`` 记录（``path_segments``
保存精确 move/line/curve，``vertices`` 保存旧 Core 可读的折线兜底），可直接
交给 ``GraphicsScene._spawn``。计算全部在实时场景坐标（page 绝对坐标）里做，
未存盘的拖动和旋转也参与，和布尔运算用同一套 ``sceneTransform`` 口径。

判定的是「这些线条能不能围出封闭区域」，不要求端点首尾相接：

1. 把直线 / 折线 / 三次贝塞尔拆成参数化段（直线也用退化三次控制点统一表示）；
2. 求所有段两两之间的交点（线-线解析解、线-曲线求三次 Bernstein 根、
   曲线-曲线 de Casteljau 细分），并把端点投影到别的段上以识别 T 型接触；
3. 按交点参数把每段切开，交点 / 端点按容差聚类成平面图的节点；
4. 每条子段生成一对有向半边，节点处按出射角排序，用 ``next = prev(twin)``
   做面遍历，有向面积符合内部面符号、且非零的环就是可填充的封闭区域；
5. 每个区域写成一个 closedSubpath，曲线段原样保留 cubicTo 控制点。

因此交叉成三角形、井字中间那一格、端点落在别的线中段、多块独立封闭区域、
带悬空伸出段都能生成；悬空边来回走出的零面积环会被丢弃。反向半边的曲线
控制点同步交换。不处理单条曲线自身的自交（三次曲线叶形），也不处理切线
相切（不穿越、不产生封闭区域）。
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath

from .g_path import (
    PATH_FILL_RULE_KEY,
    PATH_SEGMENTS_KEY,
    fill_rule_name,
    path_to_segments,
    path_to_vertices,
)

OUTLINE_TYPES = frozenset(("line", "bezier", "polyline"))
# 节点聚类 / 端点吸附容差（场景单位）。覆盖页 JSON 保留 3 位小数的取整误差、
# 吸附点落点与未存盘的小幅拖动；曲线数值交点远小于这个值。
ENDPOINT_TOLERANCE = 1.0
# 曲线细分收敛精度（场景单位）；越小越准，代价是递归更深。
INTERSECTION_TOLERANCE = 0.02
_CURVE_MAX_DEPTH = 18
_CURVE_SAMPLES = 24
_MAX_PAIR_HITS = 64
_MIN_FACE_AREA = 1e-3
# Qt 场景坐标 y 轴向下，面遍历得到的有界内面是正有向面积、无界外面（会绕着
# 悬空伸出段走一大圈）是负的；实测矩形 / 交叉三角形 / 井字均符合（见 _extract_faces）。
_INTERIOR_SIGN = 1.0


def supports_outline(item) -> bool:
    return getattr(item, "TYPE", "") in OUTLINE_TYPES


# ----------------------------------------------------------------------
# 点 / 包围盒工具（不依赖 QPointF 的运算符重载差异）
# ----------------------------------------------------------------------
def _lerp(a: QPointF, b: QPointF, t: float) -> QPointF:
    return QPointF(a.x() + (b.x() - a.x()) * t,
                   a.y() + (b.y() - a.y()) * t)


def _delta(a: QPointF, b: QPointF) -> QPointF:
    return QPointF(a.x() - b.x(), a.y() - b.y())


def _cross(a: QPointF, b: QPointF) -> float:
    return a.x() * b.y() - a.y() * b.x()


def _dot(a: QPointF, b: QPointF) -> float:
    return a.x() * b.x() + a.y() * b.y()


def _dist(a: QPointF, b: QPointF) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


def _bbox(piece: "_Piece") -> tuple[float, float, float, float]:
    xs = [p.x() for p in (piece.p0, piece.p1, piece.p2, piece.p3)]
    ys = [p.y() for p in (piece.p0, piece.p1, piece.p2, piece.p3)]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_near(a, b, pad: float) -> bool:
    return not (a[2] + pad < b[0] or b[2] + pad < a[0]
                or a[3] + pad < b[1] or b[3] + pad < a[1])


def _point_near_bbox(point: QPointF, box, pad: float) -> bool:
    return (box[0] - pad <= point.x() <= box[2] + pad
            and box[1] - pad <= point.y() <= box[3] + pad)


def _bbox_diagonal(box) -> float:
    return math.hypot(box[2] - box[0], box[3] - box[1])


@dataclass
class _Piece:
    """一段 line / curve；直线用 p1=p0、p2=p3 的退化三次控制点统一表示。"""

    kind: str
    p0: QPointF
    p1: QPointF
    p2: QPointF
    p3: QPointF

    @classmethod
    def line(cls, a: QPointF, b: QPointF) -> "_Piece":
        return cls("line", QPointF(a), QPointF(a), QPointF(b), QPointF(b))

    @classmethod
    def curve(cls, a: QPointF, c1: QPointF, c2: QPointF,
              b: QPointF) -> "_Piece":
        return cls("curve", QPointF(a), QPointF(c1), QPointF(c2), QPointF(b))

    def copy(self) -> "_Piece":
        return _Piece(self.kind, QPointF(self.p0), QPointF(self.p1),
                      QPointF(self.p2), QPointF(self.p3))

    def reversed(self) -> "_Piece":
        if self.kind == "line":
            return _Piece.line(self.p3, self.p0)
        return _Piece.curve(self.p3, self.p2, self.p1, self.p0)

    def with_endpoints(self, start: QPointF, end: QPointF) -> "_Piece":
        """把端点对齐到节点代表点，内部控制点不动。"""
        if self.kind == "line":
            return _Piece.line(start, end)
        return _Piece(self.kind, QPointF(start), QPointF(self.p1),
                      QPointF(self.p2), QPointF(end))

    def point_at(self, t: float) -> QPointF:
        if self.kind == "line":
            return _lerp(self.p0, self.p3, t)
        u = 1.0 - t
        a, b, c = u * u * u, 3.0 * u * u * t, 3.0 * u * t * t
        d = t * t * t
        return QPointF(
            a * self.p0.x() + b * self.p1.x() + c * self.p2.x() + d * self.p3.x(),
            a * self.p0.y() + b * self.p1.y() + c * self.p2.y() + d * self.p3.y(),
        )

    def derivative_at(self, t: float) -> QPointF:
        if self.kind == "line":
            return _delta(self.p3, self.p0)
        u = 1.0 - t
        a, b, c = 3.0 * u * u, 6.0 * u * t, 3.0 * t * t
        return QPointF(
            a * (self.p1.x() - self.p0.x())
            + b * (self.p2.x() - self.p1.x())
            + c * (self.p3.x() - self.p2.x()),
            a * (self.p1.y() - self.p0.y())
            + b * (self.p2.y() - self.p1.y())
            + c * (self.p3.y() - self.p2.y()),
        )

    def split(self, t: float) -> tuple["_Piece", "_Piece"]:
        """de Casteljau 分割；直线单独走插值，避免退化出伪 cubicTo。"""
        if self.kind == "line":
            middle = _lerp(self.p0, self.p3, t)
            return _Piece.line(self.p0, middle), _Piece.line(middle, self.p3)
        a = _lerp(self.p0, self.p1, t)
        b = _lerp(self.p1, self.p2, t)
        c = _lerp(self.p2, self.p3, t)
        d = _lerp(a, b, t)
        e = _lerp(b, c, t)
        f = _lerp(d, e, t)
        return (_Piece.curve(self.p0, a, d, f),
                _Piece.curve(f, e, c, self.p3))

    def outgoing_angle(self) -> float:
        direction = self.derivative_at(0.0)
        if math.hypot(direction.x(), direction.y()) < 1e-9:
            direction = _delta(self.p3, self.p0)
        if math.hypot(direction.x(), direction.y()) < 1e-9:
            direction = _delta(self.p2, self.p0)
        return math.atan2(direction.y(), direction.x())

    def extent(self) -> float:
        """控制点折线长度，用于丢掉交点切分产生的极短碎片。"""
        return (max(_dist(self.p0, self.p3),
                    _dist(self.p0, self.p1) + _dist(self.p1, self.p2)
                    + _dist(self.p2, self.p3)))


# ----------------------------------------------------------------------
# 图元 -> 参数化段
# ----------------------------------------------------------------------
def _item_pieces(item) -> list[_Piece]:
    transform = item.sceneTransform()
    if item.TYPE in ("line", "polyline"):
        points = [transform.map(QPointF(pt))
                  for pt in getattr(item, "_points_local", []) or []]
        if len(points) < 2:
            return []
        return [_Piece.line(points[i], points[i + 1])
                for i in range(len(points) - 1)]
    # BezierItem 继承 PathItem；_live_page_path 已含实时旋转 / 平移。
    return _path_pieces(item._live_page_path())


def _path_pieces(path: QPainterPath) -> list[_Piece]:
    """按 QPainterPath 元素拆段；口径与 g_path.path_to_segments 一致。"""
    pieces: list[_Piece] = []
    cursor = QPointF()
    index = 0
    count = path.elementCount()
    while index < count:
        element = path.elementAt(index)
        if element.isMoveTo():
            cursor = QPointF(element.x, element.y)
            index += 1
        elif element.isLineTo():
            end = QPointF(element.x, element.y)
            pieces.append(_Piece.line(cursor, end))
            cursor = end
            index += 1
        elif element.isCurveTo() and index + 2 < count:
            second = path.elementAt(index + 1)
            third = path.elementAt(index + 2)
            end = QPointF(third.x, third.y)
            pieces.append(_Piece.curve(
                cursor, QPointF(element.x, element.y),
                QPointF(second.x, second.y), end,
            ))
            cursor = end
            index += 3
        else:
            index += 1
    return pieces


# ----------------------------------------------------------------------
# 交点
# ----------------------------------------------------------------------
def _line_line(a: _Piece, b: _Piece) -> list[tuple[float, float, QPointF]]:
    r = _delta(a.p3, a.p0)
    s = _delta(b.p3, b.p0)
    denominator = _cross(r, s)
    if abs(denominator) < 1e-9:
        return []          # 平行 / 共线：交给端点投影处理
    qp = _delta(b.p0, a.p0)
    t = _cross(qp, s) / denominator
    u = _cross(qp, r) / denominator
    if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
        t = _clamp01(t)
        return [(t, _clamp01(u), a.point_at(t))]
    return []


def _bernstein(f0: float, f1: float, f2: float, f3: float,
               t: float) -> float:
    u = 1.0 - t
    return (u * u * u * f0 + 3.0 * u * u * t * f1
            + 3.0 * u * t * t * f2 + t * t * t * f3)


def _line_curve(line: _Piece, curve: _Piece
                ) -> list[tuple[float, float, QPointF]]:
    """把曲线控制点代入直线法向方程，求三次 Bernstein 标量多项式的根。"""
    r = _delta(line.p3, line.p0)
    rr = _dot(r, r)
    if rr < 1e-12:
        return []
    normal = QPointF(-r.y(), r.x())
    controls = (curve.p0, curve.p1, curve.p2, curve.p3)
    f = [_dot(normal, _delta(point, line.p0)) for point in controls]

    roots: list[float] = []
    steps = 40
    previous_t, previous_f = 0.0, f[0]
    if abs(previous_f) < 1e-9:
        roots.append(0.0)
    for step in range(1, steps + 1):
        t = step / steps
        value = _bernstein(*f, t)
        if previous_f * value < 0.0:
            lo, hi, flo = previous_t, t, previous_f
            for _ in range(48):
                middle = (lo + hi) / 2.0
                fm = _bernstein(*f, middle)
                if flo * fm <= 0.0:
                    hi = middle
                else:
                    lo, flo = middle, fm
            roots.append((lo + hi) / 2.0)
        previous_t, previous_f = t, value
    if abs(_bernstein(*f, 1.0)) < 1e-9:
        roots.append(1.0)

    hits: list[tuple[float, float, QPointF]] = []
    for t in roots:
        point = curve.point_at(t)
        u = _dot(_delta(point, line.p0), r) / rr
        if -1e-9 <= u <= 1.0 + 1e-9:
            hits.append((_clamp01(u), t, point))
    return hits


def _dedupe(hits, tolerance: float) -> list[tuple[float, float, QPointF]]:
    groups: list[dict] = []
    for ta, tb, point in hits:
        for group in groups:
            if _dist(point, group["point"]) <= tolerance:
                group["pairs"].append((ta, tb))
                break
        else:
            groups.append({"point": point, "pairs": [(ta, tb)]})
    out = []
    for group in groups:
        pairs = group["pairs"]
        out.append((
            sum(pair[0] for pair in pairs) / len(pairs),
            sum(pair[1] for pair in pairs) / len(pairs),
            group["point"],
        ))
    return out


def _curve_curve(a: _Piece, b: _Piece
                 ) -> list[tuple[float, float, QPointF]]:
    """包围盒剪枝 + 双向 de Casteljau 细分，收敛后取参数区间中点。"""
    hits: list[tuple[float, float, QPointF]] = []
    tolerance = INTERSECTION_TOLERANCE

    def recurse(pa: _Piece, ta0: float, ta1: float,
                pb: _Piece, tb0: float, tb1: float, depth: int) -> None:
        if len(hits) >= _MAX_PAIR_HITS:
            return
        box_a, box_b = _bbox(pa), _bbox(pb)
        if not _bbox_near(box_a, box_b, tolerance):
            return
        converged = (_bbox_diagonal(box_a) < tolerance
                     and _bbox_diagonal(box_b) < tolerance)
        if converged or depth >= _CURVE_MAX_DEPTH:
            ma, mb = (ta0 + ta1) / 2.0, (tb0 + tb1) / 2.0
            point = _lerp(pa.point_at(0.5), pb.point_at(0.5), 0.5)
            hits.append((ma, mb, point))
            return
        a1, a2 = pa.split(0.5)
        b1, b2 = pb.split(0.5)
        tma, tmb = (ta0 + ta1) / 2.0, (tb0 + tb1) / 2.0
        recurse(a1, ta0, tma, b1, tb0, tmb, depth + 1)
        recurse(a1, ta0, tma, b2, tmb, tb1, depth + 1)
        recurse(a2, tma, ta1, b1, tb0, tmb, depth + 1)
        recurse(a2, tma, ta1, b2, tmb, tb1, depth + 1)

    recurse(a, 0.0, 1.0, b, 0.0, 1.0, 0)
    return _dedupe(hits, max(tolerance * 3.0, 0.06))


def _pair_intersections(a: _Piece, b: _Piece
                        ) -> list[tuple[float, float, QPointF]]:
    """返回 (段 a 上的参数, 段 b 上的参数, 交点坐标)。"""
    if a.kind == "line" and b.kind == "line":
        return _line_line(a, b)
    if a.kind == "line":
        # _line_curve(line, curve) 已经返回 (a 参数, b 参数)。
        return _line_curve(a, b)
    if b.kind == "line":
        # 反过来 a 是曲线、b 是直线：_line_curve(b, a) 返回的是
        # (直线参数, 曲线参数)，必须交换回 (a 参数, b 参数)，否则会按
        # 错误参数切段，交点找不到、封闭区域也就提不出来。
        return [(t_curve, u_line, point)
                for u_line, t_curve, point in _line_curve(b, a)]
    return _curve_curve(a, b)


def _nearest_param(piece: _Piece, point: QPointF) -> tuple[float, float]:
    """点到段的最近参数与距离，用于端点落在别的段中间（T 型接触）。"""
    box = _bbox(piece)
    if not _point_near_bbox(point, box, ENDPOINT_TOLERANCE):
        return 0.0, float("inf")
    if piece.kind == "line":
        r = _delta(piece.p3, piece.p0)
        rr = _dot(r, r)
        if rr < 1e-12:
            return 0.0, _dist(point, piece.p0)
        t = _clamp01(_dot(_delta(point, piece.p0), r) / rr)
        return t, _dist(point, piece.point_at(t))

    def squared(t: float) -> float:
        offset = _delta(point, piece.point_at(t))
        return _dot(offset, offset)

    best_t = 0.0
    best = float("inf")
    for step in range(_CURVE_SAMPLES + 1):
        t = step / _CURVE_SAMPLES
        value = squared(t)
        if value < best:
            best, best_t = value, t
    span = 1.0 / _CURVE_SAMPLES
    lo, hi = max(0.0, best_t - span), min(1.0, best_t + span)
    for _ in range(28):
        m1, m2 = lo + (hi - lo) / 3.0, hi - (hi - lo) / 3.0
        if squared(m1) < squared(m2):
            hi = m2
        else:
            lo = m1
    t = (lo + hi) / 2.0
    return t, _dist(point, piece.point_at(t))


def _cut_parameters(pieces: list[_Piece], tolerance: float
                    ) -> list[list[float]]:
    """收集每一段上需要切开的参数（交点 + 别的段落在本段上的端点）。"""
    params: list[list[float]] = [[] for _ in pieces]
    boxes = [_bbox(piece) for piece in pieces]
    for i, first in enumerate(pieces):
        for j in range(i + 1, len(pieces)):
            second = pieces[j]
            if not _bbox_near(boxes[i], boxes[j], tolerance):
                continue
            for ti, tj, _point in _pair_intersections(first, second):
                params[i].append(ti)
                params[j].append(tj)
            # T 型接触：i 的端点落在 j 上 -> j 要在该处切开（反之亦然）。
            for endpoint in (first.p0, first.p3):
                if not _point_near_bbox(endpoint, boxes[j], tolerance):
                    continue
                tj, distance = _nearest_param(second, endpoint)
                if distance <= tolerance:
                    params[j].append(tj)
            for endpoint in (second.p0, second.p3):
                if not _point_near_bbox(endpoint, boxes[i], tolerance):
                    continue
                ti, distance = _nearest_param(first, endpoint)
                if distance <= tolerance:
                    params[i].append(ti)
    return params


def _split_all(pieces: list[_Piece], params: list[list[float]]
               ) -> list[_Piece]:
    parts: list[_Piece] = []
    for piece, raw in zip(pieces, params):
        cuts = sorted({_clamp01(t) for t in raw if 1e-5 < t < 1.0 - 1e-5})
        merged: list[float] = []
        for t in cuts:
            if not merged or t - merged[-1] > 1e-4:
                merged.append(t)
        current, previous = piece, 0.0
        chunks: list[_Piece] = []
        for t in merged:
            left, right = current.split((t - previous) / (1.0 - previous))
            chunks.append(left)
            current, previous = right, t
        chunks.append(current)
        parts.extend(chunk for chunk in chunks if chunk.extent() > 1e-4)
    return parts


# ----------------------------------------------------------------------
# 平面图：节点聚类 -> 半边 -> 面遍历
# ----------------------------------------------------------------------
def _cluster_nodes(points, tolerance: float
                   ) -> tuple[list[int], list[QPointF]]:
    """网格桶聚类，返回 (每点所属节点 id, 节点代表点)。"""
    representatives: list[QPointF] = []
    buckets: dict[tuple[int, int], list[int]] = {}
    node_ids: list[int] = []
    for point in points:
        gx = int(math.floor(point.x() / tolerance))
        gy = int(math.floor(point.y() / tolerance))
        found = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for node in buckets.get((gx + dx, gy + dy), ()):
                    if _dist(point, representatives[node]) <= tolerance:
                        found = node
                        break
                if found is not None:
                    break
            if found is not None:
                break
        if found is None:
            found = len(representatives)
            representatives.append(QPointF(point))
            buckets.setdefault((gx, gy), []).append(found)
        node_ids.append(found)
    return node_ids, representatives


@dataclass
class _HalfEdge:
    start: int
    end: int
    piece: _Piece
    twin: int = -1
    angle: float = 0.0


def _build_half_edges(parts: list[_Piece], tolerance: float
                      ) -> tuple[list[_HalfEdge], int]:
    endpoints: list[QPointF] = []
    for piece in parts:
        endpoints.extend((piece.p0, piece.p3))
    if not endpoints:
        return [], 0
    node_ids, representatives = _cluster_nodes(endpoints, tolerance)
    halves: list[_HalfEdge] = []
    for index, piece in enumerate(parts):
        a, b = node_ids[2 * index], node_ids[2 * index + 1]
        forward = piece.with_endpoints(representatives[a], representatives[b])
        backward = piece.reversed().with_endpoints(
            representatives[b], representatives[a])
        base = len(halves)
        halves.append(_HalfEdge(a, b, forward, twin=base + 1,
                                angle=forward.outgoing_angle()))
        halves.append(_HalfEdge(b, a, backward, twin=base,
                                angle=backward.outgoing_angle()))
    return halves, len(representatives)


def _extract_faces(halves: list[_HalfEdge],
                   node_count: int) -> list[list[int]]:
    """DCEL 面遍历。

    节点处的出射半边按角度升序排成环，``prev(h)`` 是该环里的前一个；面内
    下一条半边是 ``prev(twin(h))``（twin 的起点正是 h 的终点）。这样每个面
    被走成一个闭环；Qt 场景 y 轴向下，有界内面走出来是正的有向面积，无界
    外面（绕着悬空伸出段走一圈）是负的，悬空边来回走出的是零面积。
    """
    outgoing: list[list[int]] = [[] for _ in range(node_count)]
    for index, half in enumerate(halves):
        outgoing[half.start].append(index)
    previous: dict[int, int] = {}
    for ring in outgoing:
        if not ring:
            continue
        ring.sort(key=lambda index: halves[index].angle)
        for position, index in enumerate(ring):
            previous[index] = ring[(position - 1) % len(ring)]
    following = [previous[half.twin] for half in halves]

    visited = [False] * len(halves)
    loops: list[list[int]] = []
    for start in range(len(halves)):
        if visited[start]:
            continue
        loop: list[int] = []
        current = start
        while not visited[current]:
            visited[current] = True
            loop.append(current)
            current = following[current]
        loops.append(loop)
    return loops


def _loop_area(loop: list[int], halves: list[_HalfEdge]) -> float:
    """环的有向面积；曲线用 8 段折线近似（只用于判面，不影响输出精度）。"""
    points: list[QPointF] = [QPointF(halves[loop[0]].piece.p0)]
    for index in loop:
        piece = halves[index].piece
        if piece.kind == "line":
            points.append(piece.p3)
        else:
            for step in range(1, 9):
                points.append(piece.point_at(step / 8.0))
    if len(points) < 3:
        return 0.0
    cross = 0.0
    for position, a in enumerate(points):
        b = points[(position + 1) % len(points)]
        cross += a.x() * b.y() - b.x() * a.y()
    return cross / 2.0


def _faces_to_path(loops: list[list[int]],
                   halves: list[_HalfEdge]) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.OddEvenFill)
    for loop in loops:
        path.moveTo(halves[loop[0]].piece.p0)
        for index in loop:
            piece = halves[index].piece
            if piece.kind == "curve":
                path.cubicTo(piece.p1, piece.p2, piece.p3)
            else:
                path.lineTo(piece.p3)
        path.closeSubpath()
    return path


def _outline_has_area(path: QPainterPath) -> bool:
    """共线性检测：排除所有子路径都退化成一条线的情况。"""
    points = [QPointF(point) for polygon in path.toSubpathPolygons()
              for point in polygon]
    if len(points) < 3:
        return False
    base = points[0]
    far = max(points, key=lambda point: math.hypot(
        point.x() - base.x(), point.y() - base.y()))
    dx, dy = far.x() - base.x(), far.y() - base.y()
    if math.hypot(dx, dy) < 1e-9:
        return False
    return max(abs(dx * (point.y() - base.y()) - dy * (point.x() - base.x()))
               for point in points) > 1e-6


# ----------------------------------------------------------------------
# 对外接口
# ----------------------------------------------------------------------
def closed_path_from_outline(items, tolerance: float = ENDPOINT_TOLERANCE,
                             ) -> QPainterPath:
    """校验并生成闭合 QPainterPath（page 绝对坐标；每个封闭区域一个子路径）。

    任何失败都抛 ValueError，且不消耗新图元 id、不改动源图元。
    """
    if len(items) < 2:
        raise ValueError("请先选中至少 2 条直线、贝塞尔曲线或折线")
    pieces: list[_Piece] = []
    for item in items:
        if not supports_outline(item):
            raise ValueError("选区包含不支持的图元类型"
                             "（只支持直线 / 贝塞尔曲线 / 折线）")
        pieces.extend(_item_pieces(item))
    if len(pieces) < 2:
        raise ValueError("选中的线条没有有效几何")

    tolerance = max(float(tolerance), 1e-6)
    params = _cut_parameters(pieces, tolerance)
    parts = _split_all(pieces, params)
    halves, node_count = _build_half_edges(parts, tolerance)
    if not halves:
        raise ValueError("选中的线条没有围出封闭区域")
    loops = _extract_faces(halves, node_count)
    interior = [loop for loop in loops
                if _loop_area(loop, halves) * _INTERIOR_SIGN > _MIN_FACE_AREA]
    if not interior:
        raise ValueError("选中的线条没有围出封闭区域"
                         "（端点或交点都没有把区域闭合起来）")

    path = _faces_to_path(interior, halves)
    bounds = path.boundingRect()
    if (bounds.isEmpty() or bounds.width() < 1e-6 or bounds.height() < 1e-6
            or not _outline_has_area(path)):
        raise ValueError("选中的线条只围成了一条线，不是有效闭合面域")
    return path


def can_form_closed_path(items, tolerance: float = ENDPOINT_TOLERANCE) -> bool:
    """右键菜单 / 菜单项显隐用的轻量判定：不抛异常、不改场景。"""
    if len(items) < 2:
        return False
    try:
        closed_path_from_outline(items, tolerance)
    except (ValueError, TypeError, IndexError, ZeroDivisionError):
        return False
    return True


def make_outline_record(items, item_id: int, z_value: float,
                        tolerance: float = ENDPOINT_TOLERANCE) -> dict:
    """生成可直接交给 ``GraphicsScene._spawn`` 的 path 记录。"""
    page_path = closed_path_from_outline(items, tolerance)
    bounds = page_path.boundingRect()
    cx, cy = bounds.center().x(), bounds.center().y()
    first = items[0]
    style = copy.deepcopy(first.to_page_record().get("style") or {})
    # 源是开放线（贝塞尔 / 折线默认 fill=False）；结果是有面积的面域，同布尔
    # 结果一样按填充图元呈现，之后仍可在属性面板里关掉填充。
    style["fill"] = True
    return {
        "id": int(item_id),
        "name": f"闭合路径_{int(item_id)}",
        "type": "path",
        "parent_id": 0,
        "children_ids": [],
        "group_id": 0,
        "center_pos": {"x": round(cx, 3), "y": round(cy, 3)},
        "origin_pos": {"x": round(cx, 3), "y": round(cy, 3)},
        "width": round(bounds.width(), 3),
        "height": round(bounds.height(), 3),
        "rotate": 0.0,
        "style": style,
        "zValue": float(z_value),
        PATH_SEGMENTS_KEY: path_to_segments(page_path),
        PATH_FILL_RULE_KEY: fill_rule_name(page_path.fillRule()),
        "vertices": path_to_vertices(page_path),
    }
