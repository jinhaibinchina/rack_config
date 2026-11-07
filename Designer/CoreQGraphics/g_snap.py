"""吸附系统：端点 / 中点 / 网格交汇点、T 门控、鼠标附近的红色十字标记。

对应 ``Designer/Core/mySnapSystem.py``。点集用 ``(x, y)`` 元组去重，
兼容旧 SnapSystem 的输入口径；坐标是 QGraphicsScene 的视图坐标。

与旧实现的两点差异（都是为了避免「网格点把集合撑爆」）：

* 网格点**不做预先枚举**：网格是规则点阵，最近交汇点直接
  ``round((p - origin) / step)`` 算出来即可（同 ``get_nearest_grid_point``）。
* 图元捕捉点（端点 / 中点）**优先**，网格只在比它更近时才顶替
  （同 ``snap_to_point`` 里「网格最后比较」的顺序）。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF

MARKER_COLOR = (255, 0, 0)

# 网格基准步长（视图场景单位）。投影 kx = 0.25，即页面 200 单位一格。
GRID_STEP = 50.0
GRID_MAJOR_EVERY = 5      # 每隔几条画一条主线
MIN_GRID_PX = 18.0        # 屏幕上最小格宽；低于它步长翻倍
MAX_GRID_PX = 90.0        # 屏幕上最大格宽；高于它步长减半
SNAP_PIXELS = 12.0        # 吸附半径的屏幕像素口径


class SnapSystem:
    """持续检测吸附点，T 门控启用吸附。"""

    def __init__(
        self,
        threshold: float = SNAP_PIXELS,
        grid_step: float = GRID_STEP,
        grid_origin: tuple[float, float] = (0.0, 0.0),
    ) -> None:
        # threshold 是场景单位；视图在缩放后会把 pixel_threshold 换算过来
        self.threshold = float(threshold)
        self.pixel_threshold = float(threshold)
        self.enabled = False
        self.show_markers = True
        self.points: dict[str, set[tuple[float, float]]] = {
            "endpoints": set(),
            "midpoints": set(),
        }
        # 网格：步长按缩放自适应，视觉网格与可捕捉网格始终是同一份
        self.grid_enabled = True
        self.base_grid_step = float(grid_step)
        self.grid_step = float(grid_step)
        self.grid_origin = (float(grid_origin[0]), float(grid_origin[1]))
        # 鼠标当前所在的场景坐标（视图每次移动都灌进来）
        self.hover: QPointF | None = None
        # 空间哈希：抓取点动辄上万（page_1 约 1.4 万），每帧线性扫描会拖慢鼠标
        self._cell = 64.0
        self._index: dict[tuple[int, int], list[tuple[str, float, float]]] = {}

    # ------------------------------------------------------------------
    def clear(self) -> None:
        self.points["endpoints"].clear()
        self.points["midpoints"].clear()
        self._index.clear()

    def update_points(self, ends, mids) -> None:
        e = self.points["endpoints"]
        m = self.points["midpoints"]
        e.clear()
        m.clear()
        for p in ends:
            e.add((float(p.x()), float(p.y())))
        for p in mids:
            m.add((float(p.x()), float(p.y())))
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """把端点 / 中点塞进空间哈希，查询时只扫光标附近的格子。"""
        idx: dict[tuple[int, int], list[tuple[str, float, float]]] = {}
        cell = self._cell
        for kind, key in (("endpoint", "endpoints"), ("midpoint", "midpoints")):
            for x, y in self.points[key]:
                idx.setdefault((int(math.floor(x / cell)), int(math.floor(y / cell))),
                               []).append((kind, x, y))
        self._index = idx

    def _cells_around(self, point: QPointF, radius: float):
        cell = self._cell
        x0 = int(math.floor((point.x() - radius) / cell))
        x1 = int(math.floor((point.x() + radius) / cell))
        y0 = int(math.floor((point.y() - radius) / cell))
        y1 = int(math.floor((point.y() + radius) / cell))
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                bucket = self._index.get((cx, cy))
                if bucket:
                    yield from bucket

    def all_points(self):
        return self.points["endpoints"] | self.points["midpoints"]

    def count(self) -> tuple[int, int]:
        return len(self.points["endpoints"]), len(self.points["midpoints"])

    # ------------------------------------------------------------------
    # 网格
    # ------------------------------------------------------------------
    def adapt_grid_to_scale(self, scale: float) -> None:
        """按视图缩放调整网格步长，让屏幕格宽落在 [MIN, MAX] 像素之间。

        网格既是背景线又是捕捉点阵，两者共用同一个步长；缩放后按 2 的幂
        细分 / 合并，视觉密度和捕捉粒度始终一致。基准 50 视图单位对应页面
        200 单位（投影 kx = 0.25），细分两级就是页面 50 单位一格。
        """
        if scale <= 0:
            return
        step = self.base_grid_step
        lowest = self.base_grid_step / 16.0
        while step * scale > MAX_GRID_PX and step > lowest:
            step /= 2.0
        while step * scale < MIN_GRID_PX:
            step *= 2.0
        self.grid_step = step

    def grid_index(self, value: float, axis: int = 0) -> float:
        """把坐标吸附到最近的网格索引（返回索引，不是坐标）。"""
        origin = self.grid_origin[axis]
        if self.grid_step <= 0:
            return 0.0
        return round((value - origin) / self.grid_step)

    def grid_coord(self, index: float, axis: int = 0) -> float:
        return self.grid_origin[axis] + index * self.grid_step

    def nearest_grid(self, point: QPointF) -> tuple[float, float]:
        """离 ``point`` 最近的网格交汇点（解析计算，不枚举）。"""
        return (
            self.grid_coord(self.grid_index(point.x(), 0), 0),
            self.grid_coord(self.grid_index(point.y(), 1), 1),
        )

    def grid_points_near(self, point: QPointF, radius: float) -> list[tuple[float, float]]:
        """鼠标附近的网格交汇点（用于画标记，最多 2~4 个）。"""
        if not self.grid_enabled or self.grid_step <= 0 or radius <= 0:
            return []
        out: list[tuple[float, float]] = []
        px, py = point.x(), point.y()
        step = self.grid_step
        ox, oy = self.grid_origin
        i0 = math.ceil((px - radius - ox) / step)
        i1 = math.floor((px + radius - ox) / step)
        j0 = math.ceil((py - radius - oy) / step)
        j1 = math.floor((py + radius - oy) / step)
        for i in range(int(i0), int(i1) + 1):
            for j in range(int(j0), int(j1) + 1):
                out.append((ox + i * step, oy + j * step))
        return out

    # ------------------------------------------------------------------
    # 候选与吸附
    # ------------------------------------------------------------------
    def nearest(self, point: QPointF, exclude=None):
        """返回 (最近点, 距离)；无候选返回 (None, inf)。"""
        best, best_d = None, math.inf
        px, py = point.x(), point.y()
        for x, y in self.all_points():
            if exclude is not None and (x, y) in exclude:
                continue
            d = (x - px) ** 2 + (y - py) ** 2
            if d < best_d:
                best, best_d = (x, y), d
        if best is None:
            return None, math.inf
        return QPointF(best[0], best[1]), math.sqrt(best_d)

    def _nearest_indexed(self, point: QPointF, radius: float, exclude=None):
        """在光标附近的格子里找最近点（只扫局部，不遍历全部吸附点）。"""
        best = None
        best_d2 = math.inf
        px, py = point.x(), point.y()
        for _kind, x, y in self._cells_around(point, radius):
            if exclude is not None and (x, y) in exclude:
                continue
            d2 = (x - px) ** 2 + (y - py) ** 2
            if d2 < best_d2:
                best, best_d2 = (x, y), d2
        if best is None:
            return None, math.inf
        return QPointF(best[0], best[1]), math.sqrt(best_d2)

    def aim(self, point: QPointF, exclude=None,
            always: bool = False) -> tuple[QPointF | None, str | None]:
        """返回本次会命中的捕捉点与类型（``element`` / ``grid``）。

        图元点优先；网格点只有在**严格更近**时才顶替（同旧
        ``snap_to_point`` 的顺序），避免格点把端点/中点吃掉。

        ``always=True`` 时至少给出一个点：阈值内没有端点 / 中点时退到**最近的
        格子交汇点**（格点不枚举、解析算得出来，永远存在）。画布上「光标附近
        那一个十字」和 T 键吸附都走这个口径，所以鼠标停在大图元内部、附近又没
        有别人的端点时，照样有标记、照样能吸过去。
        """
        near, dist = self._nearest_indexed(point, self.threshold, exclude)
        best: QPointF | None = near if dist <= self.threshold else None
        kind = "element" if best is not None else None

        if self.grid_enabled and self.grid_step > 0:
            gx, gy = self.nearest_grid(point)
            gd = math.hypot(gx - point.x(), gy - point.y())
            if gd <= self.threshold and (best is None or gd < dist - 1e-9):
                best, kind = QPointF(gx, gy), "grid"
            elif best is None and always:
                best, kind = QPointF(gx, gy), "grid"
        elif best is None and always:
            # 网格关掉时退到「够得着」的图元点：放宽到 4 倍阈值，仍不枚举全表
            near, dist = self._nearest_indexed(point, self.threshold * 4.0, exclude)
            if near is not None:
                best, kind = near, "element"
        return best, kind

    def snap(self, point: QPointF, exclude=None) -> tuple[QPointF, QPointF | None]:
        """门控开启且落在阈值内才吸附，返回 (修正后点, 命中的标记)。"""
        if not self.enabled:
            return QPointF(point), None
        target, _kind = self.aim(point, exclude)
        if target is None:
            return QPointF(point), None
        return QPointF(target), QPointF(target)

    def candidates(self, point: QPointF, radius: float, exclude=None,
                   limit: int = 48) -> list[tuple[str, QPointF]]:
        """鼠标附近的候选捕捉点（画标记用），含网格交汇点。"""
        out: list[tuple[str, QPointF]] = []
        r2 = radius * radius
        px, py = point.x(), point.y()
        for kind, x, y in self._cells_around(point, radius):
            if exclude is not None and (x, y) in exclude:
                continue
            if (x - px) ** 2 + (y - py) ** 2 <= r2:
                out.append((kind, QPointF(x, y)))
                if len(out) >= limit:
                    return out
        for gx, gy in self.grid_points_near(point, radius):
            out.append(("grid", QPointF(gx, gy)))
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------
    def markers_in(self, scene_rect: QRectF, limit: int = 1200):
        """只返回可见范围内的标记，避免一帧画上万个十字。"""
        out: list[QPointF] = []
        left, top = scene_rect.left(), scene_rect.top()
        right, bottom = scene_rect.right(), scene_rect.bottom()
        for x, y in self.all_points():
            if left <= x <= right and top <= y <= bottom:
                out.append(QPointF(x, y))
                if len(out) >= limit:
                    break
        return out
