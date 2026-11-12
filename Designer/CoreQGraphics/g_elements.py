"""12 类图元：对应 ``Designer/Core/elements.py`` 的 paint 配方。

坐标系已经在 ``BaseItem`` 里投影到视图坐标，因此这里不再做
``sceneToView`` / ``painter.translate`` / ``painter.rotate(-angle)``：
旋转由 ``QGraphicsItem.setRotation`` 承担，paint 只画局部几何。

与旧实现的两处差异：
* 旧 Core ``widget_element.paint`` 不区分变体（只画矩形 + "Widget"），变体
  外观来自 ``EmbeddedWidgetLayer`` 挂载的真实 QWidget；重写版设计态按
  ``g_widgets.paint_variant`` 自绘 7 种占位外观，运行态另挂真实控件。
* 选中时统一补一层青色虚线框；旧实现只有 group/image 画选中框。
  验证脚本在「无选中」状态下对拍，因此该差异不进入 diff。
"""

from __future__ import annotations

import math
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap

from .g_element import BaseItem, _page_xy, norm_deg, rotate_xy
from .g_path import (
    PATH_FILL_RULE_KEY, PATH_SEGMENTS_KEY, fill_rule_value, map_path,
    path_to_segments, path_to_vertices, segments_to_path,
)
from .g_style import (
    HOVER_COLOR, TEXT_PAD_X, TEXT_PAD_Y, dashed_pen_for, font_for, parse_color,
    text_metrics,
)
from .g_widgets import paint_variant

# 零厚度轴的「命中带」半宽（page 场景单位）。水平线 / 竖直线的几何包围盒
# 有一条边长度为 0，Qt 默认用 boundingRect() 做命中测试，退化矩形点不中，
# 所以两侧各外扩这么宽，让线仍然可以点选 / 框选。60 的总带宽沿用旧 Core
# 的口径（``line_element.update_boundingRect`` 里的 60 / 30）。
LINE_HIT_HALF = 30.0
# 触发加厚的「细轴」判定阈值，与旧 Core 一致
LINE_THIN_AXIS = 6.0


def _selection_overlay(painter: QPainter, item: BaseItem) -> None:
    if not item.isSelected():
        return
    painter.save()
    painter.setPen(dashed_pen_for(HOVER_COLOR))
    painter.drawRect(item.boundingRect())
    painter.restore()


def _load_pixmap(name: str) -> QPixmap:
    if not name:
        return QPixmap()
    file_name = os.path.basename(str(name).replace("\\", "/"))
    try:
        from res.designer_resource_manager import resource_manager as res_mng

        path = res_mng.get_img_path(file_name)
    except Exception:
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "res", "myDesigner", "img", file_name
        )
    return QPixmap(path)


class RectItem(BaseItem):
    TYPE = "rect"
    DRAW_KIND = "box"

    def paint(self, painter: QPainter, option, widget=None) -> None:
        s = self._style
        r = self._local_rect
        painter.save()
        if s.fill:
            painter.setBrush(s.brush())
        painter.setPen(s.pen(self.stroke_color()))
        radius = s.corner_radius
        if radius > 0:
            rx = min(radius * self._proj.ky, r.width() / 2.0)
            ry = min(radius * self._proj.kx, r.height() / 2.0)
            painter.drawRoundedRect(r, rx, ry)
        else:
            painter.drawRect(r)
        painter.restore()
        _selection_overlay(painter, self)

    def draw_step(self, points: list[QPointF], preview: QPointF | None) -> bool:
        """两点框选：p1=起点，p2=终点（或实时光标预览）。"""
        if not points:
            return False
        p1 = points[0]
        p2 = points[1] if len(points) >= 2 else preview
        if p2 is None:
            return False
        cx = (p1.x() + p2.x()) / 2.0
        cy = (p1.y() + p2.y()) / 2.0
        w = max(abs(p2.x() - p1.x()), 1e-3)
        h = max(abs(p2.y() - p1.y()), 1e-3)
        self.set_page_center(cx, cy)
        self.set_page_size(w, h)
        return len(points) >= 2


class CircleItem(RectItem):
    TYPE = "circle"
    DRAW_KIND = "circle"

    def paint(self, painter: QPainter, option, widget=None) -> None:
        s = self._style
        painter.save()
        if s.fill:
            painter.setBrush(s.brush())
        painter.setPen(s.pen(self.stroke_color()))
        painter.drawEllipse(self._local_rect)
        painter.restore()
        _selection_overlay(painter, self)

    def draw_step(self, points: list[QPointF], preview: QPointF | None) -> bool:
        """第一点为圆心，第二点（或光标）决定半径（欧氏距离）。"""
        if not points:
            return False
        p1 = points[0]
        p2 = points[1] if len(points) >= 2 else preview
        if p2 is None:
            return False
        r = max(math.hypot(p2.x() - p1.x(), p2.y() - p1.y()), 1e-3)
        self.set_page_center(p1.x(), p1.y())
        self.set_page_radius(r)
        return len(points) >= 2

    def set_page_radius(self, r: float) -> None:
        r = max(float(r), 1e-3)
        self._page["radius_w"] = r
        self._page["radius_h"] = r
        self._page["center_pos"] = {
            "x": round(self._page_center[0], 3), "y": round(self._page_center[1], 3)
        }
        self._page["origin_pos"] = dict(self._page["center_pos"])
        self._w_view, self._h_view = self._proj.size(2.0 * r, 2.0 * r)
        self._local_rect = QRectF(
            -self._w_view / 2, -self._h_view / 2, self._w_view, self._h_view
        )
        self._dirty = True
        self._geo_dirty = True
        self.update()


class TextItem(BaseItem):
    TYPE = "text"
    # 与属性面板 make_int(..., 4, 200) 对齐，反算结果一定能回显
    _MIN_FONT = 4
    _MAX_FONT = 200

    def _on_text_changed(self) -> None:
        """改字号 / 改文本后，边框背景按文字实际尺寸重算（中心与支点不动）。

        对照旧 Core ``text_element``：那边是**由宽度反算字号**
        （``calc_font_size`` 逐步试到 boundingRect 高度达标，再由文字宽度反算
        高度）。新场景反过来——``style.font_size`` 是用户直接给的真值，边框
        只是文字的容器，所以这里按同一份 ``font_for`` 字体量出文字像素尺寸、
        外扩 ``TEXT_PAD_X/Y``，再反投影成 page 的 width / height。

        AGV 投影交换了轴：view 宽对应 page 的 ``height``、view 高对应 page 的
        ``width``，因此用 ``SceneProjection.inverse_size`` 反算，不要手工除 kx。
        另外只在显式编辑时触发，加载 / round-trip 完全不碰存量几何。
        """
        wpx, hpx = text_metrics(self.context or "", self._style.font_size)
        w_view = wpx + 2.0 * TEXT_PAD_X
        h_view = hpx + 2.0 * TEXT_PAD_Y
        w, h = self._proj.inverse_size(w_view, h_view)
        if "width" not in self._page and "radius_w" not in self._page:
            # 极老的存量记录可能没有尺寸字段，补上矩形口径再让 set_page_size 写
            self._page["width"], self._page["height"] = 0.0, 0.0
        # 抑制反向联动：这次是「字号 / 文字 -> 边框」，别再让 set_page_size
        # 把刚设的字号按新边框反算回去。
        prev = self._text_resizing
        self._text_resizing = True
        try:
            self.set_page_size(w, h)
        finally:
            self._text_resizing = prev

    def _on_size_changed(self, w: float, h: float) -> None:
        """手动改边框 / 拖角 / 组缩放时**反算字号**，让文字始终装得进边框。

        对照旧 Core ``text_element.change_size``：那边先按用户给的 width 换算
        出视图像素高度，再用 ``calc_font_size`` 从 1 逐步试到文字
        ``boundingRect`` 高度达标，最后由文字宽度派生 height。新场景保留用户
        给定的 w/h（拖角与组缩放都靠它做仿射变换，派生高度会让每帧比例抖动、
        整棵子树几何失真），只把 ``style.font_size`` 调整到「文字 + 内边距
        装得进新框」的最大整数值。

        由 ``_on_text_changed`` 触发的 set_page_size 已经置了
        ``_text_resizing``，这里直接跳过，两个方向不会互相递归。
        """
        if self._text_resizing or w <= 0 or h <= 0:
            return
        w_view, h_view = self._proj.size(float(w), float(h))
        fs = self._fit_font_size(w_view, h_view)
        if fs == int(round(self._style.font_size)):
            return
        prev = self._text_resizing
        self._text_resizing = True
        try:
            self.set_style_value("font_size", fs)
        finally:
            self._text_resizing = prev

    def _fit_font_size(self, w_view: float, h_view: float) -> int:
        """二分找能装进 ``(w_view, h_view)`` 的最大整数字号。

        与旧 Core ``calc_font_size`` 的「从 1 逐步试到刚好装得下」同口径，
        但用二分代替 1..500 的线性扫描（拖角每帧都要算，组里可能有多个文本）。
        字号上界与属性面板 ``make_int(..., 4, 200)`` 对齐。
        """
        text = self.context or ""
        target_w = max(float(w_view) - 2.0 * TEXT_PAD_X, 1.0)
        target_h = max(float(h_view) - 2.0 * TEXT_PAD_Y, 1.0)

        def fits(fs: int) -> bool:
            tw, th = text_metrics(text, fs)
            return tw <= target_w + 1e-6 and th <= target_h + 1e-6

        lo, hi = self._MIN_FONT, self._MAX_FONT
        if not fits(lo):
            return lo
        if fits(hi):
            return hi
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if fits(mid):
                lo = mid
            else:
                hi = mid - 1
        return lo

    def paint(self, painter: QPainter, option, widget=None) -> None:
        s = self._style
        r = self._local_rect
        painter.save()
        painter.setFont(font_for("Arial", s.font_size, True))
        # 圆角与 RectItem / 旧 Core rect_element 同口径：cornerRadius 是场景
        # 单位，AGV 投影交换了轴（场景 y -> 画笔 x、场景 x -> 画笔 y），所以
        # rx 乘 ky、ry 乘 kx，且各自夹在对应边的一半以内。属性面板本来就给
        # text 提供了「圆角」输入框，这里必须真的读到它。
        radius = s.corner_radius
        rx = ry = 0.0
        if radius > 0:
            rx = min(radius * self._proj.ky, r.width() / 2.0)
            ry = min(radius * self._proj.kx, r.height() / 2.0)
        rounded = rx > 0 and ry > 0
        if s.stroke_width > 0:
            painter.setPen(s.pen(self.stroke_color()))
            if s.fill:
                painter.setBrush(s.brush())
            if rounded:
                painter.drawRoundedRect(r, rx, ry)
            else:
                painter.drawRect(r)
        else:
            painter.setPen(s.pen(self.stroke_color(), 1.0))
            if s.fill:
                if rounded:
                    # fillRect 没有圆角版本：临时切到 NoPen + 画刷只填圆角底，
                    # 再 restore 回文字用的笔（strokeWidth=0 时不画边框，文字
                    # 颜色仍走 stroke_color，与无圆角时逐像素一致）。
                    painter.save()
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(s.brush())
                    painter.drawRoundedRect(r, rx, ry)
                    painter.restore()
                else:
                    painter.fillRect(r, s.fill_color)
        text_rect = painter.boundingRect(r, Qt.AlignCenter, self.context or "")
        painter.drawText(text_rect, Qt.AlignCenter, self.context or "")
        painter.restore()
        _selection_overlay(painter, self)


class ImageItem(BaseItem):
    TYPE = "image"

    def __init__(self, record, projection) -> None:
        super().__init__(record, projection)
        self._pixmap = _load_pixmap(self.image_path)

    def _reload_pixmap(self) -> None:
        self._pixmap = _load_pixmap(self.image_path)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        s = self._style
        r = self._local_rect
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        highlight = self.isSelected() or self._hover
        if highlight:
            painter.setPen(dashed_pen_for(HOVER_COLOR))
            painter.drawRect(r)
        if self._pixmap is not None and not self._pixmap.isNull():
            painter.drawPixmap(r.toRect(), self._pixmap)
        painter.restore()
        if not highlight:
            _selection_overlay(painter, self)


class CheckboxItem(RectItem):
    TYPE = "checkbox"
    DRAW_KIND = "place"

    def paint(self, painter: QPainter, option, widget=None) -> None:
        super().paint(painter, option, widget)
        if not self.checked:
            return
        r = self._local_rect
        short = min(r.width(), r.height())
        if short <= 4.0:
            return
        painter.save()
        painter.setPen(self._style.pen(self.stroke_color(), max(2.0, short * 0.12)))
        path = QPainterPath(QPointF(-r.width() * 0.28, r.height() * 0.02))
        path.lineTo(QPointF(-r.width() * 0.06, -r.height() * 0.22))
        path.lineTo(QPointF(r.width() * 0.30, r.height() * 0.26))
        painter.drawPath(path)
        painter.restore()

    def draw_step(self, points: list[QPointF], preview: QPointF | None) -> bool:
        if points:
            self.set_page_center(points[0].x(), points[0].y())
        return len(points) >= 1


class WidgetItem(RectItem):
    """``widget`` 控件图元：7 种变体共用一套 5 字段顶层序列化口径。

    字段与默认值逐字对齐旧 Core ``widget_element``（见 ``g_widgets``），
    缺字段的老页面只按默认值显示、绝不回写，保证 round-trip 零改动。
    """

    TYPE = "widget"
    DRAW_KIND = "place"

    def paint(self, painter: QPainter, option, widget=None) -> None:
        super().paint(painter, option, widget)
        paint_variant(painter, self._local_rect, self._page)

    def draw_step(self, points: list[QPointF], preview: QPointF | None) -> bool:
        if points:
            self.set_page_center(points[0].x(), points[0].y())
        return len(points) >= 1


class GroupItem(BaseItem):
    TYPE = "group"
    _scaling = False

    def set_page_size(self, w: float, h: float) -> None:
        """改组宽高 = 递归改变组内成员的尺寸与位置（对照旧 Core change_size）。

        属性面板布局页、``+`` / ``-`` 快捷键都走这里。委托给场景统一处理，
        因为成员是平铺图元，必须由场景拿到 ``index.descendants()`` 才能覆盖
        整棵子树（含嵌套组）。
        """
        scene = self.scene()
        if (not self._scaling and scene is not None
                and hasattr(scene, "resize_group")):
            self._scaling = True
            try:
                if scene.resize_group(self, float(w), float(h)):
                    return
            finally:
                self._scaling = False
        BaseItem.set_page_size(self, w, h)

    def resize_by(self, factor: float) -> None:
        """``+`` / ``-``：组整体缩放，必须连成员一起缩放。"""
        if factor <= 0:
            return
        w, h = self.page_size()
        self.set_page_size(w * factor, h * factor)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        scene = self.scene()
        if scene is not None and getattr(scene, "is_run_mode", False):
            return
        r = self._local_rect
        corners = [
            QPointF(r.left(), r.top()), QPointF(r.right(), r.top()),
            QPointF(r.right(), r.bottom()), QPointF(r.left(), r.bottom()),
        ]
        painter.save()
        painter.setPen(dashed_pen_for(
            HOVER_COLOR if (self.isSelected() or self._hover) else self._style.stroke
        ))
        painter.drawPolygon(corners)
        painter.restore()
        if not self.isSelected():
            _selection_overlay(painter, self)


class _PointBasedItem(BaseItem):
    """line / triangle / polygon / path 的公共几何构建。"""

    def __init__(self, record, projection) -> None:
        super().__init__(record, projection)
        # 顶点类把旋转烘焙进顶点，记录里的 ``rotate`` 就是「已烘焙的真实朝向」
        # （旧 Core 加载时先反旋再正旋，读它等于恒等，所以这么存是安全的）。
        self._baked_angle = float(record.get("rotate", 0.0) or 0.0)

    def page_angle(self) -> float:
        """当前朝向 = 已烘焙角度 + 还没烘焙的 Qt 旋转。

        顶点类改角度后要烘焙才能存盘（见 ``bake_rotation``），烘焙会把 Qt 旋转
        归零；只读 ``rotation()`` 的话属性面板的「旋转」框会立刻归 0，再输一次
        绝对角就变成「在已转过的姿态上再转一次」。
        """
        if self._geo_dirty:
            return norm_deg(self._baked_angle - float(self.rotation()))
        return float(self._page.get("rotate", 0.0) or 0.0)

    def _sync_baked_angle(self) -> None:
        """把 ``_baked_angle`` 落到记录（顶点类的 rotate 字段就是它）。"""
        self._page["rotate"] = float(self._baked_angle)

    def _account_bake(self, dangle: float = 0.0) -> None:
        """重建前记账：待烘焙的 Qt 旋转（还可能叠加一段刚体增量）要进顶点。

        ``page_angle() = _baked_angle - rotation()``，而重建会把 Qt 旋转清零并把
        它折进顶点，所以朝向要按「旧烘焙角 + 待烘焙角 + 本次刚体增量」重新记。
        """
        self._baked_angle = norm_deg(self._baked_angle - float(self.rotation())
                                     + float(dangle))

    def to_page_record(self) -> dict:
        if self._geo_dirty:
            self.bake_rotation()
        out = super().to_page_record()
        # 基类按 Qt rotation 写 rotate（烘焙后恒为 0），顶点类要写真实朝向。
        # 值相等就别动：未编辑的图元必须原样回写（连 0 和 0.0 都不改）。
        if abs(float(out.get("rotate", 0.0) or 0.0)
               - float(self._baked_angle)) > 1e-12:
            out["rotate"] = float(self._baked_angle)
        return out

    def page_size(self) -> tuple[float, float]:
        """包围盒尺寸（按实时顶点量，且先抵消自身旋转）。

        矩形类的宽高是「自身坐标系」里的尺寸、与角度无关；顶点类要保持同一口径，
        所以把实时顶点绕中心反转 ``-angle`` 再取 AABB——旋转 30° 的多边形照样
        报 300×200，而不是旋转后的 620×473。
        """
        pts = self._live_page_points()
        if not pts:
            return super().page_size()
        cx, cy = self.page_center()
        angle = self.page_angle()
        if abs(angle) > 1e-9:
            pts = [rotate_xy(x, y, cx, cy, -angle) for x, y in pts]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return max(xs) - min(xs), max(ys) - min(ys)

    def set_page_size(self, w: float, h: float) -> None:
        """按比例缩放顶点，把包围盒调成 ``w × h``（顶点类没有几何矩形可改）。

        在**自身坐标系**里缩（先把顶点反转到 -angle，缩完再转回去），否则旋转过的
        图形会被沿着屏幕横竖方向拉斜。缩放基准取**可视中心**而不是包围盒中心：
        改完宽高的图元中心 / 支点都还在原地，否则顶点类转一次再改宽高，旋转中心
        会跟着包围盒跳。某个方向当前长度为 0（水平线 / 垂直线）时该方向保持
        不动：0 乘任何系数还是 0，真想把它拉出来得挪端点，那是画布上的编辑。
        属性面板据此把该输入框置灰，不让人改了没反应。
        """
        if w <= 0 and h <= 0:
            return
        pts = self._live_page_points()
        if len(pts) < 2:
            return
        cx, cy = self.page_center()
        ox, oy = self.page_origin()
        angle = self.page_angle()
        rotated = abs(angle) > 1e-9
        un = ([rotate_xy(x, y, cx, cy, -angle) for x, y in pts]
              if rotated else list(pts))
        xs = [p[0] for p in un]
        ys = [p[1] for p in un]
        cur_w = max(xs) - min(xs)
        cur_h = max(ys) - min(ys)
        fx = (float(w) / cur_w) if cur_w > 1e-6 and w > 0 else 1.0
        fy = (float(h) / cur_h) if cur_h > 1e-6 and h > 0 else 1.0
        if abs(fx - 1.0) < 1e-12 and abs(fy - 1.0) < 1e-12:
            return
        # 支点是刚体上的点：按同一组比例在自身坐标系里缩，默认支点时它等于中心
        uox, uoy = (rotate_xy(ox, oy, cx, cy, -angle) if rotated else (ox, oy))
        scaled = []
        for x, y in un:
            nx, ny = cx + (x - cx) * fx, cy + (y - cy) * fy
            if rotated:
                nx, ny = rotate_xy(nx, ny, cx, cy, angle)
            scaled.append(QPointF(nx, ny))
        nox, noy = cx + (uox - cx) * fx, cy + (uoy - cy) * fy
        if rotated:
            nox, noy = rotate_xy(nox, noy, cx, cy, angle)
        # 缩放要把「还没烘焙的 Qt 旋转」一并折进顶点（set_page_vertices 会
        # setRotation(0)），所以朝向按总角度记账，别只留旧的 _baked_angle
        self._baked_angle = norm_deg(float(angle))
        self._apply_scaled_points(scaled, center=(cx, cy), pivot=(nox, noy))

    def resize_by(self, factor: float) -> None:
        """``+`` / ``-`` 快捷键：顶点类按比例缩放顶点。

        基类只放大 ``_local_rect``，而顶点类的 ``paint`` 画的是 ``_points_local``，
        照基类走会「框变了、形状不变」。
        """
        if factor <= 0:
            return
        w, h = self.page_size()
        self.set_page_size(w * factor, h * factor)

    def apply_scale_about(self, anchor, sx: float, sy: float) -> None:
        """组尺寸变化时，按同一仿射变换搬走顶点类的全部顶点 / 端点。

        顶点类没有「宽高矩形」可改，几何全在 ``vertices`` / ``head_pos`` 里；
        中心与支点必须一起按 ``F(p)`` 变换后显式传下去，否则重建会按新包围盒
        重找中心（三角形转过之后旋转中心会跳）。
        """
        ax, ay = float(anchor[0]), float(anchor[1])

        def f(x, y):
            return ax + (float(x) - ax) * sx, ay + (float(y) - ay) * sy

        cx, cy = self.page_center()
        ox, oy = self.page_origin()
        pts = [QPointF(*f(x, y)) for x, y in self._live_page_points()]
        if len(pts) < 2:
            return
        prev = self._suppress_propagate
        self._suppress_propagate = True
        try:
            self._apply_scaled_points(pts, center=f(cx, cy), pivot=f(ox, oy))
        finally:
            self._suppress_propagate = prev

    def _apply_scaled_points(self, points: list[QPointF], center=None,
                             pivot=None) -> None:
        """把缩放后的 page 顶点写回几何（子类按各自存储格式覆写）。"""
        self.set_page_vertices(points, center=center, pivot=pivot)

    def _local_points(self) -> list[QPointF]:
        """局部顶点（视图坐标，相对可视中心）。路径类按 ``_path_local`` 覆写。"""
        return list(self._points_local)

    def _live_page_points(self) -> list[tuple[float, float]]:
        """把局部顶点反读成 page 场景坐标（顶点类的顶点已是绝对坐标）。"""
        p = self._proj
        out: list[tuple[float, float]] = []
        for pt in self._local_points():
            s = self.mapToScene(pt)
            out.append(p.inverse_point(s.x(), s.y()))
        return out

    def _bake_live_geometry(self, center=None, pivot=None) -> None:
        """把当前实时几何写回记录（顶点类默认走多边形顶点）。"""
        pts = self._live_page_points()
        if len(pts) >= 3:
            self.set_page_vertices([QPointF(x, y) for x, y in pts],
                                   center=center, pivot=pivot)

    def bake_rotation(self) -> None:
        """把 Qt 旋转折进顶点。

        顶点类的 ``vertices`` / ``head_pos`` 是「已烘焙 rotate 的场景绝对坐标」，
        加载时不再按 ``rotate`` 二次旋转（与旧 Core 一致）。因此自行旋转（[ / ]
        或改角度）之后必须先烘焙，否则存盘丢旋转：记录里 ``rotate`` 变了而顶点
        没动，重新打开会弹回原位。

        烘焙是**纯记账**：顶点一个都不动，只把「Qt 变换」换成「绝对顶点 +
        rotate=0」。所以中心 / 支点必须原样带过去（``live_page_pose`` 里已经是
        绕支点转过之后的刚体位置），绝不能让重建按新包围盒重新找中心——那样
        三角形转 30° 之后旋转中心会往下跳一大截（包围盒中心本来就跟着形状转）。
        """
        qt = float(self.rotation())
        if abs(qt) < 1e-9:
            return
        cx, cy, _angle, ox, oy = self.live_page_pose()
        prev = self._suppress_propagate
        self._suppress_propagate = True
        try:
            self._bake_live_geometry(center=(cx, cy), pivot=(ox, oy))
        finally:
            self._suppress_propagate = prev
        # 这一段旋转从「Qt 变换」转成了「顶点坐标」，朝向累计到 _baked_angle
        self._baked_angle = norm_deg(self._baked_angle - qt)
        self._sync_baked_angle()

    def apply_rigid_pose(self, px: float, py: float, dangle: float,
                         dx: float, dy: float) -> None:
        """父级刚体运动直接烘焙进顶点（顶点类不用 Qt 旋转，见 ``_setup_vertices``）。"""
        pts = self._live_page_points()
        if len(pts) < 3:
            return
        cx, cy = self.page_center()
        ox, oy = self.page_origin()
        moved = []
        for x, y in pts:
            nx, ny = rotate_xy(x, y, px, py, dangle)
            moved.append(QPointF(nx + dx, ny + dy))
        ncx, ncy = rotate_xy(cx, cy, px, py, dangle)
        nox, noy = rotate_xy(ox, oy, px, py, dangle)
        self._account_bake(dangle)
        self.set_page_vertices(moved, center=(ncx + dx, ncy + dy),
                               pivot=(nox + dx, noy + dy))

    def set_page_vertices(self, vertices: list[QPointF], center=None,
                          pivot=None) -> None:
        """由落点重建多边形/三角顶点（page 场景坐标，angle=0 烘焙进顶点）。

        ``center`` / ``pivot`` 传了就按传入值落（旋转、父级刚体运动、缩放都要把
        中心与支点一起按同一变换搬走，否则默认支点会被「新包围盒中心」顶掉）；
        都不传就是「新形状」口径——中心落在顶点包围盒中心、默认支点跟过去
        （绘制落子、重建顶点走这条）。
        """
        if len(vertices) < 3:
            return
        self.prepareGeometryChange()
        old_center = self.page_center()
        rec = [{"x": round(p.x(), 3), "y": round(p.y(), 3)} for p in vertices]
        self._page["vertices"] = rec
        if pivot is None:
            # 新形状：顶点就是全部几何，朝向以落点为准
            self._baked_angle = 0.0
        xs = [p.x() for p in vertices]
        ys = [p.y() for p in vertices]
        if "width" in self._page:
            self._page["width"] = round(max(xs) - min(xs), 3)
            self._page["height"] = round(max(ys) - min(ys), 3)
        if center is None:
            cx = (min(xs) + max(xs)) / 2.0
            cy = (min(ys) + max(ys)) / 2.0
        else:
            cx, cy = float(center[0]), float(center[1])
        self._write_center(cx, cy)
        # 重建期间别让 on_item_moved 把这次 setPos 当成「外部拖动」去平移支点
        # （它拿的是旧中心差分，会把默认支点推到包围盒角落）
        self._suppress_geo = True
        try:
            self._setup_vertices(rec, 0.0, center=(cx, cy))
        finally:
            self._suppress_geo = False
        if pivot is None:
            # 顶点决定中心：默认支点要跟着走，否则新建的多边形支点还停在 (0,0) /
            # 第一个落点，面板读数错、旋转绕到画布外
            self._rebase_pivot(old_center, (cx, cy))
        else:
            self._write_origin(float(pivot[0]), float(pivot[1]))
        self._sync_baked_angle()
        self._dirty = True
        self._geo_dirty = True
        self.update()

    def _setup_vertices(self, vertices, angle: float, center=None) -> None:
        # JSON 的 vertices 是「已烘焙 rotate 的场景绝对顶点」：Core 的
        # _apply_scene_vertices 把 angle 折进 _vertices_local，
        # get_scene_vertices() 又还原成原值。这里绝不能再旋转一次，
        # 否则 rotate != 0 的 polygon（page_1 的 1660/1662）bbox 会对不上。
        pts = [(float(v["x"]), float(v["y"])) for v in vertices]
        if not pts:
            self._setup_rect(*self._page_center, *self._page_size, angle)
            return
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if center is None:
            cx = (min(xs) + max(xs)) / 2.0
            cy = (min(ys) + max(ys)) / 2.0
        else:
            cx, cy = float(center[0]), float(center[1])
        scene_rect = QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))
        p = self._proj
        center_v = p.point(cx, cy)
        self._suppress_geo = True
        try:
            self.setPos(center_v)
            self.setRotation(0.0)
            self.setTransformOriginPoint(QPointF(0.0, 0.0))
        finally:
            self._suppress_geo = False
        self._points_local = [p.point(x, y) - center_v for x, y in pts]
        self._local_rect = p.rect(scene_rect).translated(-center_v.x(),
                                                         -center_v.y())
        self._w_view = self._local_rect.width()
        self._h_view = self._local_rect.height()

    # ------------------------------------------------------------------
    # 捕捉点：用真实顶点，而不是包围盒四角
    # ------------------------------------------------------------------
    def _snap_vertices_local(self) -> list[QPointF]:
        """局部坐标下的可视顶点（子类可覆盖，如 path 走 ``_local_points()``）。"""
        return list(getattr(self, "_points_local", []) or [])

    def snap_closed(self) -> bool:
        """形状是否闭合（闭合的再补一条「末点 → 首点」边的中点）。"""
        return False

    def snap_points(self) -> tuple[list[QPointF], list[QPointF]]:
        """端点取**真实顶点**，中点取各边中点 + 图元中心。

        基类按 ``_local_rect`` 取包围盒四角：线一旦斜放、三角形 / 多边形不是
        轴对齐矩形，包围盒角点根本不在图形上（斜线的包围盒角能离可见端点几十个
        单位），鼠标凑到看得见的端点旁边反而没有捕捉点。旧 Core 对线也是取
        ``get_scene_head_pos() / get_scene_end_pos()``，这里与它对齐。
        """
        pts = self._snap_vertices_local()
        if len(pts) < 2:
            return super().snap_points()
        tf = self.sceneTransform()
        ends = [tf.map(p) for p in pts]
        mids = [tf.map(QPointF(0.0, 0.0))]
        for a, b in zip(ends, ends[1:]):
            mids.append(QPointF((a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0))
        if self.snap_closed() and len(ends) > 2:
            a, b = ends[-1], ends[0]
            mids.append(QPointF((a.x() + b.x()) / 2.0, (a.y() + b.y()) / 2.0))
        return ends, mids


class LineItem(_PointBasedItem):
    TYPE = "line"
    DRAW_KIND = "line"

    def __init__(self, record, projection) -> None:
        super().__init__(record, projection)
        hx, hy = _page_xy(record, "head_pos")
        ex, ey = _page_xy(record, "end_pos")
        angle = float(record.get("rotate", 0.0) or 0.0)
        cx, cy = (hx + ex) / 2.0, (hy + ey) / 2.0
        self._page_center = (cx, cy)
        self._page_size = (abs(ex - hx), abs(ey - hy))
        self._setup_line(hx, hy, ex, ey, cx, cy, angle)

    def _setup_line(self, hx, hy, ex, ey, cx, cy, angle) -> None:
        # 零厚度轴要留一条「命中带」才能点选 / 框选。旧 Core 想加厚到 60，
        # 但 setWidth(60) + setLeft(-30) 的顺序错了：QRectF.setLeft 只挪左
        # 边、保持右边不动，结果宽度变 90、中心还往一侧偏 15。这里改成
        # 两侧对称外扩，中心仍钉在线上（拖角手柄 / 选中框才不会歪）。
        left, right = min(hx, ex), max(hx, ex)
        top, bottom = min(hy, ey), max(hy, ey)
        rect = QRectF(QPointF(left, top), QPointF(right, bottom))
        if abs(rect.width()) < LINE_THIN_AXIS and abs(rect.height()) > LINE_THIN_AXIS:
            rect.adjust(-LINE_HIT_HALF, 0.0, LINE_HIT_HALF, 0.0)
        elif abs(rect.height()) < LINE_THIN_AXIS and abs(rect.width()) > LINE_THIN_AXIS:
            rect.adjust(0.0, -LINE_HIT_HALF, 0.0, LINE_HIT_HALF)
        p = self._proj
        center = p.point(cx, cy)
        self._suppress_geo = True
        try:
            self.setPos(center)
            self.setRotation(0.0)
            self.setTransformOriginPoint(QPointF(0.0, 0.0))
        finally:
            self._suppress_geo = False
        self._points_local = [p.point(hx, hy) - center, p.point(ex, ey) - center]
        self._local_rect = p.rect(rect).translated(-center.x(), -center.y())
        self._w_view = self._local_rect.width()
        self._h_view = self._local_rect.height()

    def set_page_size(self, w: float, h: float) -> None:
        """直线专用 W/H：某一轴为 0 即水平 / 竖直线，两轴不能同时为 0。

        基类按「当前尺寸 × 比例」缩放顶点，遇到 0 轴没有比例基准（0 乘任何
        数还是 0），也无法从 0 重新拉开。这里对「目标或当前含 0」的情况直接
        重写两个端点：先在自身坐标系（反转 -angle）里以线段中心为基点把两端
        对称张开 ±w/2 / ±h/2，再转回 page 绝对坐标。端点原有的左右 / 上下
        次序保留，改完不会把线段翻向；中心与支点都不动，旋转烘焙进端点后
        ``set_page_head_end`` 默认路径会把 ``rotate`` 归零，两者正好一致。

        两轴都非 0 仍走基类，保留「自身坐标系缩放 + 支点 / 旋转记账」语义。
        """
        if w <= 0 and h <= 0:
            return
        cur_w, cur_h = self.page_size()
        if w > 0 and h > 0 and cur_w > 1e-6 and cur_h > 1e-6:
            return super().set_page_size(w, h)
        pts = self._live_page_points()
        if len(pts) < 2:
            return
        angle = self.page_angle()
        cx, cy = self.page_center()
        a = rotate_xy(pts[0][0], pts[0][1], cx, cy, -angle)
        b = rotate_xy(pts[1][0], pts[1][1], cx, cy, -angle)
        sx = 1.0 if b[0] >= a[0] else -1.0
        sy = 1.0 if b[1] >= a[1] else -1.0
        hw, hh = max(float(w), 0.0) / 2.0, max(float(h), 0.0) / 2.0
        head = rotate_xy(cx - sx * hw, cy - sy * hh, cx, cy, angle)
        end = rotate_xy(cx + sx * hw, cy + sy * hh, cx, cy, angle)
        # 不传 pivot：中心没变，_rebase_pivot 会把自定义支点原样留下。
        self.set_page_head_end(QPointF(*head), QPointF(*end))

    def draw_step(self, points: list[QPointF], preview: QPointF | None) -> bool:
        """第一点=起点，第二点（或光标）=终点。"""
        if not points:
            return False
        head = points[0]
        end = points[1] if len(points) >= 2 else preview
        if end is None:
            return False
        self.set_page_head_end(head, end)
        return len(points) >= 2

    def apply_rigid_pose(self, px: float, py: float, dangle: float,
                         dx: float, dy: float) -> None:
        pts = self._live_page_points()
        if len(pts) < 2:
            return
        ox, oy = self.page_origin()
        ends = []
        for x, y in pts:
            nx, ny = rotate_xy(x, y, px, py, dangle)
            ends.append(QPointF(nx + dx, ny + dy))
        nox, noy = rotate_xy(ox, oy, px, py, dangle)
        self._account_bake(dangle)
        self.set_page_head_end(ends[0], ends[1],
                               pivot=(nox + dx, noy + dy))

    def _apply_scaled_points(self, points: list[QPointF], center=None,
                             pivot=None) -> None:
        """线只有两个端点，缩放直接改写 ``head_pos`` / ``end_pos``。"""
        if len(points) >= 2:
            self.set_page_head_end(points[0], points[1], pivot=pivot)

    def _bake_live_geometry(self, center=None, pivot=None) -> None:
        """线只有两个端点，烘焙走 ``head_pos`` / ``end_pos``（不用顶点表）。"""
        pts = self._live_page_points()
        if len(pts) >= 2:
            self.set_page_head_end(QPointF(*pts[0]), QPointF(*pts[1]),
                                   pivot=pivot)

    def set_page_head_end(self, head: QPointF, end: QPointF,
                          pivot=None) -> None:
        hx, hy = head.x(), head.y()
        ex, ey = end.x(), end.y()
        old_center = self.page_center()
        cx, cy = (hx + ex) / 2.0, (hy + ey) / 2.0
        self._page["head_pos"] = {"x": round(hx, 3), "y": round(hy, 3)}
        self._page["end_pos"] = {"x": round(ex, 3), "y": round(ey, 3)}
        if pivot is None:
            # 端点是这条线的唯一几何：默认支点跟到新中心，自定义支点整体平移
            # （以前这里无条件写 origin_pos = center，画布上右键设的支点会被拖端点冲掉）
            self._baked_angle = 0.0
            self._rebase_pivot(old_center, (cx, cy))
        else:
            self._write_origin(float(pivot[0]), float(pivot[1]))
        self._write_center(cx, cy)
        self._sync_baked_angle()
        self._page["length"] = math.hypot(ex - hx, ey - hy)
        self._page_size = (abs(ex - hx), abs(ey - hy))
        p = self._proj
        center = p.point(cx, cy)
        self._suppress_geo = True
        try:
            self.setPos(center)
        finally:
            self._suppress_geo = False
        self.prepareGeometryChange()
        self._setup_line(hx, hy, ex, ey, cx, cy, 0.0)
        self._dirty = True
        self._geo_dirty = True
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if len(self._points_local) < 2:
            return
        painter.save()
        painter.setPen(self._style.pen(self.stroke_color()))
        painter.drawLine(self._points_local[0], self._points_local[1])
        painter.restore()
        _selection_overlay(painter, self)


class TriangleItem(_PointBasedItem):
    TYPE = "triangle"

    def __init__(self, record, projection) -> None:
        super().__init__(record, projection)
        vertices = record.get("vertices") or []
        if len(vertices) < 3:
            cx, cy = self._page_center
            w, h = self._page_size
            vertices = [
                {"x": cx, "y": cy - h / 2},
                {"x": cx - w / 2, "y": cy + h / 2},
                {"x": cx + w / 2, "y": cy + h / 2},
            ]
        self._setup_vertices(vertices, self._page_angle)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        self._draw_polygon(painter)

    def snap_closed(self) -> bool:
        """三角形 / 多边形都是闭合图形：补首尾边中点。"""
        return True

    def _draw_polygon(self, painter: QPainter) -> None:
        if len(self._points_local) < 2:
            return
        path = QPainterPath(self._points_local[0])
        for pt in self._points_local[1:]:
            path.lineTo(pt)
        path.closeSubpath()
        painter.save()
        painter.setBrush(self._style.brush())
        painter.setPen(self._style.pen(self.stroke_color()))
        painter.drawPath(path)
        painter.restore()
        _selection_overlay(painter, self)


class PolygonItem(TriangleItem):
    TYPE = "polygon"

    def __init__(self, record, projection) -> None:
        # 不套 TriangleItem 的「顶点不足就造默认三角形」：多边形按记录原样建
        _PointBasedItem.__init__(self, record, projection)
        self._setup_vertices(record.get("vertices") or [], self._page_angle)


class PathItem(_PointBasedItem):
    TYPE = "path"

    def __init__(self, record, projection) -> None:
        # 老页面只有 vertices；布尔结果另有 path_segments 精确曲线表示。
        self._segment_mode = bool(record.get(PATH_SEGMENTS_KEY))
        super().__init__(record, projection)
        if self._segment_mode:
            self._build_segments(record.get(PATH_SEGMENTS_KEY) or [])
        else:
            self._build_path(record.get("vertices") or [])

    def _build_path(self, vertices, center=None) -> None:
        """按旧版折线顶点记录（含 ``move`` 标记）重建 path。"""
        pts = [(float(v["x"]), float(v["y"])) for v in vertices]
        if not pts:
            return
        if center is None:
            cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2.0
            cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2.0
        else:
            cx, cy = float(center[0]), float(center[1])
        scene_rect = QRectF(
            QPointF(min(p[0] for p in pts), min(p[1] for p in pts)),
            QPointF(max(p[0] for p in pts), max(p[1] for p in pts)),
        )
        p = self._proj
        center_v = p.point(cx, cy)
        self._suppress_geo = True
        try:
            self.setPos(center_v)
            self.setRotation(0.0)
            self.setTransformOriginPoint(QPointF(0.0, 0.0))
        finally:
            self._suppress_geo = False
        self._local_rect = p.rect(scene_rect).translated(-center_v.x(),
                                                         -center_v.y())
        self._w_view = self._local_rect.width()
        self._h_view = self._local_rect.height()
        path = QPainterPath()
        for v, (x, y) in zip(vertices, pts):
            pt = p.point(x, y) - center_v
            if v.get("move"):
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()
        self._path_local = path

    def _build_segments(self, segments, center=None) -> None:
        """按精确 move/line/curve 段重建；曲线控制点也参与坐标投影。"""
        if not segments:
            return
        if center is None:
            if "center_pos" in self._page:
                # 非对称路径旋转后，逻辑中心通常不再是旋转几何的 AABB 中心；
                # 加载必须尊重持久化位姿，不能仅读取一次就把它改掉。
                cx, cy = _page_xy(self._page, "center_pos")
            else:
                page_path = segments_to_path(
                    segments,
                    fill_rule=fill_rule_value(self._page.get(PATH_FILL_RULE_KEY)))
                bounds = page_path.boundingRect()
                cx, cy = bounds.center().x(), bounds.center().y()
        else:
            cx, cy = float(center[0]), float(center[1])
        p = self._proj
        center_v = p.point(cx, cy)
        path = segments_to_path(
            segments,
            point_map=lambda pt: p.point(pt.x(), pt.y()) - center_v,
            fill_rule=fill_rule_value(self._page.get(PATH_FILL_RULE_KEY)),
        )
        self._suppress_geo = True
        try:
            self.setPos(center_v)
            self.setRotation(0.0)
            self.setTransformOriginPoint(QPointF(0.0, 0.0))
        finally:
            self._suppress_geo = False
        # 不能用控制点的 AABB：贝塞尔实际极值可能严格小于控制点包围盒。
        self._local_rect = path.boundingRect()
        self._w_view = self._local_rect.width()
        self._h_view = self._local_rect.height()
        self._path_local = path

    def _local_points(self) -> list[QPointF]:
        """可视端点；曲线控制点不当顶点吸附，曲线末端仍保留。"""
        path = self._path_local
        if path is None:
            return []
        if self._segment_mode:
            out: list[QPointF] = []
            index = 0
            while index < path.elementCount():
                element = path.elementAt(index)
                if element.isCurveTo() and index + 2 < path.elementCount():
                    end = path.elementAt(index + 2)
                    out.append(QPointF(end.x, end.y))
                    index += 3
                else:
                    out.append(QPointF(element.x, element.y))
                    index += 1
            return out
        recs = self._page.get("vertices") or []
        n = min(len(recs), path.elementCount()) if recs else path.elementCount()
        return [QPointF(path.elementAt(i).x, path.elementAt(i).y) for i in range(n)]

    def _snap_vertices_local(self) -> list[QPointF]:
        return self._local_points()

    def snap_closed(self) -> bool:
        # 布尔结果是闭合面域；旧手绘路径保持既有吸附点集合不变。
        return self._segment_mode

    def _live_page_path(self) -> QPainterPath:
        """当前实时路径（含 Qt 旋转 / 拖动），反投影为 page 绝对坐标。"""
        if self._path_local is None:
            return QPainterPath()
        scene_path = self.sceneTransform().map(self._path_local)

        def inverse(point: QPointF) -> QPointF:
            return QPointF(*self._proj.inverse_point(point.x(), point.y()))

        return map_path(scene_path, inverse)

    def to_page_record(self) -> dict:
        if self._segment_mode and self._path_local is not None:
            # 与普通顶点不同，曲线还有控制点；即使只平移、Qt rotation == 0，
            # 也必须把整份实时几何写回，不能只更新 center_pos。
            cx, cy, _qt, ox, oy = self.live_page_pose()
            self._baked_angle = norm_deg(self._baked_angle - float(self.rotation()))
            previous = self._suppress_propagate
            self._suppress_propagate = True
            try:
                self._replace_path(self._live_page_path(), center=(cx, cy),
                                   pivot=(ox, oy))
            finally:
                self._suppress_propagate = previous
        return super().to_page_record()

    def page_size(self) -> tuple[float, float]:
        if self._segment_mode and self._path_local is not None:
            # 旋转可已烘焙进绝对路径，局部 AABB 因而可能是旋转后的外框；
            # 与其它顶点类一致，先反转到自身坐标系再量宽高。
            cx, cy = self.page_center()
            angle = self.page_angle()
            path = self._live_page_path()
            if abs(angle) > 1e-9:
                path = map_path(
                    path,
                    lambda pt: QPointF(*rotate_xy(pt.x(), pt.y(), cx, cy, -angle)))
            bounds = path.boundingRect()
            return bounds.width(), bounds.height()
        return super().page_size()

    def _records_from_points(self, points: list[QPointF]) -> list[dict]:
        """按旧记录的 ``move`` 分段标记重排顶点表。"""
        recs = self._page.get("vertices") or []
        if len(recs) != len(points):
            recs = [{} for _ in points]
        out: list[dict] = []
        for rec, pt in zip(recs, points):
            item = {"x": round(pt.x(), 3), "y": round(pt.y(), 3)}
            if rec.get("move"):
                item["move"] = True
            out.append(item)
        if out and not any(v.get("move") for v in out):
            out[0]["move"] = True
        return out

    def _replace_path(self, page_path: QPainterPath, center=None,
                      pivot=None) -> None:
        """精确路径统一写回：曲线段 + 旧版折线兜底 + 中心 / 支点。"""
        if page_path.isEmpty():
            return
        self.prepareGeometryChange()
        old_center = self.page_center()
        self._segment_mode = True
        self._page[PATH_SEGMENTS_KEY] = path_to_segments(page_path)
        self._page[PATH_FILL_RULE_KEY] = (
            "winding" if page_path.fillRule() == Qt.WindingFill else "odd_even")
        self._page["vertices"] = path_to_vertices(page_path)
        if pivot is None:
            self._baked_angle = 0.0
        bounds = page_path.boundingRect()
        if "width" in self._page:
            self._page["width"] = round(bounds.width(), 3)
            self._page["height"] = round(bounds.height(), 3)
        if center is None:
            cx, cy = bounds.center().x(), bounds.center().y()
        else:
            cx, cy = float(center[0]), float(center[1])
        self._write_center(cx, cy)
        self._suppress_geo = True
        try:
            self._build_segments(self._page[PATH_SEGMENTS_KEY], center=(cx, cy))
        finally:
            self._suppress_geo = False
        if pivot is None:
            self._rebase_pivot(old_center, (cx, cy))
        else:
            self._write_origin(float(pivot[0]), float(pivot[1]))
        self._sync_baked_angle()
        self._dirty = True
        self._geo_dirty = True
        self.update()

    def _replace_points(self, points: list[QPointF], center=None,
                        pivot=None) -> None:
        """手绘 / 顶点编辑是显式折线化：移除精确段，保留旧版路径语义。"""
        if len(points) < 3:
            return
        self._segment_mode = False
        self._page.pop(PATH_SEGMENTS_KEY, None)
        self._page.pop(PATH_FILL_RULE_KEY, None)
        self.prepareGeometryChange()
        old_center = self.page_center()
        rec = self._records_from_points(points)
        self._page["vertices"] = rec
        if pivot is None:
            self._baked_angle = 0.0
        xs = [p.x() for p in points]
        ys = [p.y() for p in points]
        if "width" in self._page:
            self._page["width"] = round(max(xs) - min(xs), 3)
            self._page["height"] = round(max(ys) - min(ys), 3)
        if center is None:
            cx = (min(xs) + max(xs)) / 2.0
            cy = (min(ys) + max(ys)) / 2.0
        else:
            cx, cy = float(center[0]), float(center[1])
        self._write_center(cx, cy)
        self._suppress_geo = True
        try:
            self._build_path(rec, center=(cx, cy))
        finally:
            self._suppress_geo = False
        if pivot is None:
            self._rebase_pivot(old_center, (cx, cy))
        else:
            self._write_origin(float(pivot[0]), float(pivot[1]))
        self._sync_baked_angle()
        self._dirty = True
        self._geo_dirty = True
        self.update()

    def set_page_size(self, w: float, h: float) -> None:
        if not self._segment_mode:
            return super().set_page_size(w, h)
        if w <= 0 and h <= 0:
            return
        current = self._live_page_path()
        if current.isEmpty():
            return
        cx, cy = self.page_center()
        ox, oy = self.page_origin()
        angle = self.page_angle()
        local = current.boundingRect()
        if angle:
            local_path = map_path(
                current,
                lambda pt: QPointF(*rotate_xy(pt.x(), pt.y(), cx, cy, -angle)))
            local = local_path.boundingRect()
        else:
            local_path = current
        cur_w, cur_h = local.width(), local.height()
        fx = float(w) / cur_w if cur_w > 1e-6 and w > 0 else 1.0
        fy = float(h) / cur_h if cur_h > 1e-6 and h > 0 else 1.0
        if abs(fx - 1.0) < 1e-12 and abs(fy - 1.0) < 1e-12:
            return

        def scale(point: QPointF) -> QPointF:
            x = cx + (point.x() - cx) * fx
            y = cy + (point.y() - cy) * fy
            return QPointF(*rotate_xy(x, y, cx, cy, angle)) if angle else QPointF(x, y)

        scaled = map_path(local_path, scale)
        uox, uoy = (rotate_xy(ox, oy, cx, cy, -angle) if angle else (ox, oy))
        nox, noy = cx + (uox - cx) * fx, cy + (uoy - cy) * fy
        if angle:
            nox, noy = rotate_xy(nox, noy, cx, cy, angle)
        self._baked_angle = norm_deg(angle)
        self._replace_path(scaled, center=(cx, cy), pivot=(nox, noy))

    def apply_scale_about(self, anchor, sx: float, sy: float) -> None:
        if not self._segment_mode:
            return super().apply_scale_about(anchor, sx, sy)
        ax, ay = float(anchor[0]), float(anchor[1])

        def transform(point: QPointF) -> QPointF:
            return QPointF(ax + (point.x() - ax) * sx,
                           ay + (point.y() - ay) * sy)

        cx, cy = self.page_center()
        ox, oy = self.page_origin()
        previous = self._suppress_propagate
        self._suppress_propagate = True
        try:
            # _live_page_path 含尚未烘焙的 Qt 旋转，而 _replace_path 会清零
            # rotation；先把这段角度入账，否则拖角后几何还转着、rotate 却变 0。
            self._account_bake()
            self._replace_path(map_path(self._live_page_path(), transform),
                               center=transform(QPointF(cx, cy)).toTuple(),
                               pivot=transform(QPointF(ox, oy)).toTuple())
        finally:
            self._suppress_propagate = previous

    def apply_rigid_pose(self, px: float, py: float, dangle: float,
                         dx: float, dy: float) -> None:
        if not self._segment_mode:
            return super().apply_rigid_pose(px, py, dangle, dx, dy)
        cx, cy = self.page_center()
        ox, oy = self.page_origin()

        def transform(point: QPointF) -> QPointF:
            x, y = rotate_xy(point.x(), point.y(), px, py, dangle)
            return QPointF(x + dx, y + dy)

        self._account_bake(dangle)
        self._replace_path(map_path(self._live_page_path(), transform),
                           center=transform(QPointF(cx, cy)).toTuple(),
                           pivot=transform(QPointF(ox, oy)).toTuple())

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self._path_local is None:
            return
        painter.save()
        painter.setBrush(self._style.brush())
        painter.setPen(self._style.pen(self.stroke_color()))
        painter.drawPath(self._path_local)
        painter.restore()
        _selection_overlay(painter, self)

    def _apply_scaled_points(self, points: list[QPointF], center=None,
                             pivot=None) -> None:
        self._replace_points(points, center=center, pivot=pivot)

    def _bake_live_geometry(self, center=None, pivot=None) -> None:
        if self._path_local is None:
            return
        if self._segment_mode:
            self._replace_path(self._live_page_path(), center=center, pivot=pivot)
            return
        pts = self._live_page_points()
        if len(pts) >= 3:
            self._replace_points([QPointF(x, y) for x, y in pts],
                                 center=center, pivot=pivot)

    def set_page_vertices(self, vertices: list[QPointF], center=None,
                          pivot=None) -> None:
        """手绘 / 属性面板顶点编辑走旧版折线格式。"""
        self._replace_points(vertices, center=center, pivot=pivot)


ITEM_TYPES: dict[str, type[BaseItem]] = {
    cls.TYPE: cls
    for cls in (
        LineItem, RectItem, CheckboxItem, WidgetItem, GroupItem,
        CircleItem, TextItem, ImageItem, TriangleItem, PolygonItem, PathItem,
    )
}
