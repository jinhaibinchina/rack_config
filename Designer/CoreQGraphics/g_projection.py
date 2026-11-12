"""场景坐标 <-> 视图坐标投影。

复刻 ``Designer/Core/myGraphicsScene.py:658`` 的 ``sceneToView`` 与 ``:690``
的 ``rect_sceneToView``。Core 的 AGV 映射是「轴交换 + 双轴取反」(det < 0)，
等价于先用 ``M = [[0, -kx], [-ky, 0]]`` 变换几何、再把旋转角取负::

    M * R(a) = R(-a) * M

所以把几何在加载时投影后交给 ``QGraphicsItem``：

* Qt 算出的 ``sceneBoundingRect()`` == 旧的 ``viewBoundingRect()``
* 反投影后 == 旧的 ``sceneBoundingRect()``（含旋转后的 AABB）

推导要点：M 只做轴交换/取反，与 AABB 可交换，且
``AABB(R(-a) * M(rect)) == M(AABB(R(a) * rect))``，所以即使 rotate != 0
两者仍精确相等。这正是 ``tools/verify_core_qgraphics.py`` 的硬指标。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF


class SceneProjection:
    """旧场景的坐标投影参数容器，全部是纯数值运算，不依赖 Qt widget。"""

    def __init__(
        self,
        grid_size: float = 50.0,
        units_x: float = 200.0,
        units_y: float = 200.0,
        agv: bool = True,
        origin_x: float = 0.0,
        origin_y: float = 0.0,
    ) -> None:
        self.kx = grid_size / units_x if units_x else 1.0
        self.ky = grid_size / units_y if units_y else 1.0
        self.agv = agv
        self.ox = origin_x
        self.oy = origin_y

    # ------------------------------------------------------------------
    # 正向：场景 -> 视图
    # ------------------------------------------------------------------
    def point(self, x: float, y: float) -> QPointF:
        if self.agv:
            return QPointF(-y * self.kx + self.ox, -x * self.ky + self.oy)
        return QPointF(x * self.kx + self.ox, -y * self.ky + self.oy)

    def rect(self, r: QRectF) -> QRectF:
        """等价 ``rect_sceneToView``：topLeft 取 ``sceneToView(bottomRight)``。"""
        p = self.point(r.right(), r.bottom())
        return QRectF(p.x(), p.y(), r.height() * self.ky, r.width() * self.kx)

    def size(self, w: float, h: float) -> tuple[float, float]:
        """场景宽高 -> 视图宽高（AGV 下轴交换）。"""
        return h * self.ky, w * self.kx

    def angle(self, a: float) -> float:
        """投影后的旋转角。轴交换是镜像，角度取负。"""
        return -a

    def rotated_point(
        self, x: float, y: float, cx: float, cy: float, angle_deg: float
    ) -> QPointF:
        """场景点绕 ``(cx, cy)`` 旋转后再投影（顶点类图元用）。"""
        a = math.radians(angle_deg)
        c, s = math.cos(a), math.sin(a)
        dx, dy = x - cx, y - cy
        return self.point(cx + dx * c - dy * s, cy + dx * s + dy * c)

    # ------------------------------------------------------------------
    # 反向：视图 -> 场景
    # ------------------------------------------------------------------
    def inverse_point(self, vx: float, vy: float) -> tuple[float, float]:
        if self.agv:
            return (-(vy - self.oy) / self.ky, -(vx - self.ox) / self.kx)
        return ((vx - self.ox) / self.kx, -(vy - self.oy) / self.ky)

    def inverse_rect(self, r: QRectF) -> QRectF:
        """从视图 AABB 反推场景 AABB（== 旧 ``sceneBoundingRect()``）。"""
        if self.agv:
            x0 = (self.oy - r.bottom()) / self.ky
            x1 = (self.oy - r.top()) / self.ky
            y0 = (self.ox - r.right()) / self.kx
            y1 = (self.ox - r.left()) / self.kx
        else:
            x0, x1 = (r.left() - self.ox) / self.kx, (r.right() - self.ox) / self.kx
            y1, y0 = (self.oy - r.top()) / self.ky, (self.oy - r.bottom()) / self.ky
        return QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized()

    def inverse_size(self, w_view: float, h_view: float) -> tuple[float, float]:
        return h_view / self.kx, w_view / self.ky

    def inverse_delta(self, dvx: float, dvy: float) -> tuple[float, float]:
        """视图位移 -> 场景位移（纯增量，含 AGV 轴交换与取反）。

        ``inverse_point`` 里带 origin 常量，虽然两点相减也能得到增量，但复制
        / 粘贴要的是「位移」而不是「点」：单独给一个方法，避免调用方去凑原点。
        旧 Core ``paste`` 是 ``item.setPos(item.pos() + paste_offset)``，
        ``pos()`` 是 ``sceneToView`` 之后的**视图坐标**，所以那个 100 是视图
        单位。平铺结构的偏移只能逐点写进 page 记录，必须先反投影。

        AGV 下是轴交换：视图 x 偏移来自场景 y（除 kx）、视图 y 偏移来自场景
        x（除 ky），两轴都带负号；非 AGV 下只有 y 取反。注意别用
        ``inverse_size`` 代替——那是无量纲尺寸换算，符号与轴配对都不同。
        """
        if self.agv:
            return (-float(dvy) / self.ky, -float(dvx) / self.kx)
        return (float(dvx) / self.kx, -float(dvy) / self.ky)

    def signature(self) -> tuple:
        return (self.kx, self.ky, self.agv, self.ox, self.oy)
