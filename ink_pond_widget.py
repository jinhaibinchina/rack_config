# -*- coding: utf-8 -*-
"""
InkPondWidget —— PySide6 水墨风格动态背景（池塘 / 荷花 / 鱼）

特点
----
* 纯 QPainter 绘制，不依赖任何图片、字体文件或第三方库（除 PySide6）。
* 固定逻辑画布 1200x800，按窗口尺寸等比缩放居中，四周自然留白如宣纸。
* 静态构图由固定随机种子生成一次，动画全部是时间的纯函数，
  因此不闪、不跳、不累积误差，暂停/恢复也自然。
* 水墨质感 = 浓淡对比 + 径向渗墨 + 不规则笔触边缘 + 断续飞白 + 溅墨。
* 水波：氛围涟漪、露珠滴落、青蛙蹬叶/落水、鼠标点击共用一套「略带扰动
  的扩散水环」，水面不会像一组规整的正椭圆。
* 荷：左侧一大一小两片荷叶，一只青蛙在两片叶子之间来回跳（蓄力 → 抛物线
  腾空 → 落地缓冲 → 停留），每次起落都在叶下的水面激起涟漪。
* 交互：左键点中鱼身，被点的鱼朝反方向急窜，附近同伴跟着惊散，点击处
  荡开一圈水纹；片刻后各自归回原来的巡游轨迹。逃窜与跳跃同样都是时间的
  纯函数，不做逐帧积分，暂停与任意时间跳转都不会留下状态误差。

用法
----
    from ink_pond_widget import InkPondWidget
    widget = InkPondWidget()                 # 直接作为窗口背景 / centralWidget
    widget.set_fps(30)                      # 帧率
    widget.set_ink_density(0.9)             # 整体墨色浓淡 0.0~1.5
    widget.set_paused(True)                 # 冻结画面（截图、后台省电）
    widget.save_frame("preview.png")        # 导出当前帧
    widget.set_interactive(False)           # 关掉惊鱼（纯观赏背景）
    widget.set_interactive(True)            # 打开（默认）

    # 若作为窗口背景希望铺满（而非四周留白），构造时传 fit="cover"

    # 程序化触发 / 测试：坐标是逻辑画布 1200x800 口径，返回被点中的鱼序号
    hit = widget.startle_at(600, 545, logical=True)
    pose = widget.fish_pose(hit)            # FishPose(x, y, heading, wag, weight)

直接运行本文件可打开演示窗口（点鱼身试试）：
    python ink_pond_widget.py
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, QSize
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter,
    QPainterPath, QPen, QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

# ---------------------------------------------------------------- 色彩常量
PAPER = (247, 243, 232)        # 宣纸底色
INK = (34, 38, 41)             # 浓墨（略偏冷的炭黑）
INK_SOFT = (96, 101, 104)      # 淡墨
PINK = (208, 122, 128)         # 荷瓣胭脂
POLLEN = (198, 166, 92)        # 花蕊藤黄
SEAL = (176, 56, 44)           # 印泥朱红

_TWO_PI = math.pi * 2.0


# ---------------------------------------------------------------- 数据描述
@dataclass
class Leaf:
    x: float
    y: float
    rx: float
    ry: float
    ink: float
    tilt: float
    phase: float
    seed: int
    veins: int = 7


@dataclass
class Flower:
    x: float
    y: float
    size: float
    openness: float          # 0 含苞 ~ 1 盛开
    stem_end: float          # 花梗末端 y
    lean: float              # 花梗弯曲量
    tint: float              # 胭脂浓度
    phase: float


@dataclass
class Fish:
    cx: float
    cy: float
    rx: float
    ry: float
    speed: float             # 弧度/秒，负值表示反向游
    phase: float
    size: float
    ink: float
    tail_phase: float
    # 惊逃状态：只记「何时 / 往哪 / 多强」，位移是时间的纯函数，
    # 不逐帧积分，所以暂停、set_time() 跳转都不会产生累积误差。
    flee_at: float = -1.0e9  # 起逃时刻（可以略晚于当前 → 同伴延迟反应）
    flee_dx: float = 0.0     # 逃窜单位方向，逻辑画布坐标
    flee_dy: float = 0.0
    flee_power: float = 0.0  # 0~1，1 = 被直接点中的那条


@dataclass
class FishPose:
    """某条鱼在时刻 t 的最终位姿（逻辑画布坐标）。

    绘制、命中测试、外部查询共用这一份结果：鱼逃开以后，可点区域必须跟着
    鱼走，否则会点中它刚才待过的空水面。
    """
    x: float
    y: float
    heading: float           # 度，鱼头朝向
    wag: float               # 摆尾相位值
    flee_weight: float       # 0~1，当前受惊强度


@dataclass
class FrogPose:
    """青蛙在时刻 t 的位姿（逻辑画布坐标），同样是时间的纯函数。"""
    x: float
    y: float
    heading: float           # 度，头朝向
    leg: float               # 0 蹲伏折叠 ~ 1 腾空蹬直（后腿）
    airborne: float          # 0 着叶 ~ 1 抛物线最高点
    squash: float            # 0 常态 ~ 1 压扁（蓄力 / 落地缓冲）
    on_small: bool           # 当前是否在小荷叶一侧


@dataclass
class Ripple:
    x: float
    y: float
    r0: float
    r1: float
    period: float
    offset: float
    alpha: float


@dataclass
class WaterLine:
    y: float
    x: float
    length: float
    alpha: float


class InkPondWidget(QWidget):
    """水墨池塘动态背景。可当普通 QWidget 嵌入任意布局。"""

    CW, CH = 1200.0, 800.0    # 逻辑画布尺寸

    # 惊逃曲线：起步要「猛」，回落要「缓」。峰值位移约 0.76 * DISTANCE。
    FLEE_DURATION = 2.8        # 秒，冲出到归位的完整时长
    FLEE_DISTANCE = 230.0      # 逻辑画布单位，满强度冲出幅度
    FLEE_RISE_TAU = 0.12       # 起步爆发的时间常数
    FLEE_FALL_POWER = 1.7      # 回落曲线指数
    NEIGHBOUR_POWER = 0.55     # 同伴受惊强度上限
    SPLASH_DURATION = 1.6      # 点击水纹存活时长
    SPLASH_MAX = 8             # 同时保留的水纹条数

    # 青蛙：一个大周期里「蓄力 → 跳过去 → 缓冲 → 停留 → 蓄力 → 跳回来」。
    # 阶段边界用周期比例表示，改周期不会打乱节奏。
    FROG_PERIOD = 7.0
    FROG_PHASE = 0.0
    FROG_A = (262.0, 432.0)    # 大荷叶上的落脚点
    FROG_B = (150.0, 576.0)    # 小荷叶上的落脚点
    FROG_SIZE = 30.0           # 单位青蛙 → 逻辑画布的缩放
    FROG_HOP_HEIGHT = 130.0    # 抛物线抬升；两片叶子落差 144，要够高才看得出「跳」
    FROG_REST_HEADING = 20.0   # 停着时朝右下方看
    FROG_WAVE_A = (255.0, 520.0)   # 叶下水面：涟漪中心
    FROG_WAVE_B = (150.0, 618.0)
    WAVE_DURATION = 1.5        # 青蛙 / 露珠涟漪存活时长

    def __init__(self, parent: QWidget | None = None, *,
                 fps: int = 30, seed: int = 20240618,
                 ink_density: float = 1.0, fit: str = "contain"):
        """
        fit="contain" 等比居中、四周留白（默认，构图不变形）；
        fit="cover"   等比铺满、超出部分裁切（适合纯背景铺满窗口）。
        """
        super().__init__(parent)
        self.setMinimumSize(360, 240)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setWindowTitle("水墨 · 荷塘清趣")

        self.fit = fit
        self.ink_density = ink_density
        self._t = 0.0                       # 累计动画时间（秒）
        self._last = time.perf_counter()
        self._paused = False
        self._fps = max(1, fps)

        # 交互状态（不参与构图，reset_fishes() 可一键清干净）
        self._interactive = True
        self._hover = False
        self._startles = 0
        self._splashes: list[tuple[float, float, float]] = []   # (x, y, t0)
        self.setMouseTracking(True)

        self._rng = random.Random(seed)
        self._build_scene()
        self._paper = self._make_paper(512)
        self._font = self._pick_serif_font()

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000 // self._fps)

    # ------------------------------------------------------------ 对外接口
    def set_fps(self, fps: int) -> None:
        self._fps = max(1, int(fps))
        self._timer.start(1000 // self._fps)

    def set_ink_density(self, value: float) -> None:
        """整体墨色浓淡，0 接近全白，1 为默认，>1 更浓。"""
        self.ink_density = max(0.0, float(value))
        self.update()

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        self.update()

    def time(self) -> float:
        return self._t

    def set_time(self, t: float) -> None:
        """跳转到指定时间点（秒），便于导出确定性画面。"""
        self._t = float(t)
        self._last = time.perf_counter()
        self.update()

    def save_frame(self, path: str) -> bool:
        return self.grab().save(path)

    def sizeHint(self) -> QSize:
        return QSize(1200, 800)

    # ------------------------------------------------------------ 交互：惊鱼
    def set_interactive(self, enabled: bool) -> None:
        """开关「点鱼惊逃」。关掉后鼠标事件交回父类 / 上层控件。"""
        self._interactive = bool(enabled)
        self.setMouseTracking(self._interactive)
        if not self._interactive:
            self._hover = False
            self.unsetCursor()
        self.update()

    def startle_count(self) -> int:
        """累计成功惊动鱼群的次数（测试 / 埋点用，reset_fishes 不清零）。"""
        return self._startles

    def splash_count(self) -> int:
        return len(self._splashes)

    def reset_fishes(self) -> None:
        """清掉所有逃窜状态与水纹，让鱼立刻回到原巡游轨迹。"""
        for f in self.fishes:
            f.flee_power = 0.0
            f.flee_at = -1.0e9
        self._splashes.clear()
        self.update()

    def fish_pose(self, index: int, t: float | None = None) -> FishPose:
        """查询某条鱼在时刻 ``t``（默认当前）的位姿，逻辑画布坐标。"""
        return self._fish_pose(self.fishes[index],
                               self._t if t is None else float(t))

    def is_fleeing(self, index: int, t: float | None = None) -> bool:
        return self._flee_state(
            self.fishes[index], self._t if t is None else float(t))[1] > 0.0

    def startle_at(self, x: float, y: float, *, logical: bool = True) -> int:
        """在 ``(x, y)`` 惊动鱼群，返回被直接点中的鱼序号；没点中返回 -1。

        ``logical=True`` 时坐标按逻辑画布 1200x800 解释（程序化触发 / 测试），
        False 时按控件像素解释（鼠标事件）。命中和逃窜都取同一时刻 ``self._t``。
        """
        now = self._t
        lp = QPointF(float(x), float(y)) if logical else self._to_logical(x, y)
        hit = self._fish_at(lp.x(), lp.y(), logical=True)
        if hit is None:
            return -1

        anchor = self._fish_pose(self.fishes[hit], now)
        for i, f in enumerate(self.fishes):
            pose = self._fish_pose(f, now)
            vx, vy = pose.x - lp.x(), pose.y - lp.y()
            length = math.hypot(vx, vy)
            if length < 1e-6:
                # 正点在鱼心上：沿它前进方向的反向窜出去
                a = math.radians(pose.heading + 180.0)
                vx, vy, length = math.cos(a), math.sin(a), 1.0
            if i == hit:
                power, delay = 1.0, 0.0
            else:
                d = math.hypot(pose.x - anchor.x, pose.y - anchor.y)
                power = self.NEIGHBOUR_POWER * math.exp(-d / 340.0)
                delay = 0.06 + min(0.26, d / 1500.0)
            f.flee_at = now + delay
            f.flee_dx, f.flee_dy = vx / length, vy / length
            f.flee_power = power

        self._splashes.append((lp.x(), lp.y(), now))
        del self._splashes[:-self.SPLASH_MAX]
        self._startles += 1
        self.update()
        return hit

    # -- 坐标：绘制与命中必须共用同一套缩放口径 ---------------------------
    def _scale_info(self) -> tuple[float, float, float]:
        w, h = self.width(), self.height()
        s = (max(w / self.CW, h / self.CH) if self.fit == "cover"
             else min(w / self.CW, h / self.CH))
        return s, (w - self.CW * s) / 2.0, (h - self.CH * s) / 2.0

    def _to_logical(self, x: float, y: float) -> QPointF:
        s, ox, oy = self._scale_info()
        if s <= 0:
            return QPointF()
        return QPointF((x - ox) / s, (y - oy) / s)

    def _to_widget(self, x: float, y: float) -> QPointF:
        s, ox, oy = self._scale_info()
        return QPointF(x * s + ox, y * s + oy)

    @staticmethod
    def _event_pos(event) -> QPointF:
        """PySide6 6.x 用 position()；旧版本回退到 pos()。"""
        return (event.position() if hasattr(event, "position")
                else QPointF(event.pos()))

    # -- 逃窜：位移 / 朝向 / 摆尾都是时间的纯函数 -------------------------
    def _flee_state(self, f: Fish, t: float) -> tuple[float, float]:
        """返回 ``(冲出距离, 受惊权重)``；0 表示该时刻不在逃窜。"""
        age = t - f.flee_at
        if f.flee_power <= 0.0 or age < 0.0 or age >= self.FLEE_DURATION:
            return 0.0, 0.0
        u = age / self.FLEE_DURATION
        env = ((1.0 - math.exp(-age / self.FLEE_RISE_TAU))
               * (1.0 - u) ** self.FLEE_FALL_POWER)
        return (self.FLEE_DISTANCE * f.flee_power * env,
                min(1.0, env * 1.45))

    @staticmethod
    def _blend_angle(a: float, b: float, k: float) -> float:
        """角度插值走最短弧，避免 179° → -179° 时整条鱼原地打转。"""
        return a + ((b - a + 180.0) % 360.0 - 180.0) * k

    def _fish_pose(self, f: Fish, t: float) -> FishPose:
        ang = t * f.speed + f.phase
        x = f.cx + f.rx * math.cos(ang)
        y = f.cy + f.ry * math.sin(ang) + 10 * math.sin(2 * ang)
        dx = -f.rx * math.sin(ang) * f.speed
        dy = (f.ry * math.cos(ang) + 20 * math.cos(2 * ang)) * f.speed
        heading = math.degrees(math.atan2(dy, dx))

        dist, weight = self._flee_state(f, t)
        if dist > 0.0:
            x += f.flee_dx * dist
            y += f.flee_dy * dist
            heading = self._blend_angle(
                heading, math.degrees(math.atan2(f.flee_dy, f.flee_dx)),
                weight)

        # 基础摆尾 + 受惊时的高频急摆；后者振幅从 0 平滑升起，相位不跳变
        wag = (math.sin(t * 6.4 + f.tail_phase)
               + weight * 0.60 * math.sin(t * 17.0 + f.tail_phase * 2.0))
        return FishPose(x, y, heading, wag, weight)

    # -- 命中：把点击点逆变换回鱼的「单位鱼」局部坐标 ---------------------
    @staticmethod
    def _hit_local(u: float, v: float) -> bool:
        """单位鱼坐标系里的可点区域 = 身体包络 + 尾鳍，略放宽一点好点。"""
        if ((u - 0.04) / 1.00) ** 2 + (v / 0.46) ** 2 <= 1.0:
            return True
        return (-1.60 <= u <= -0.78
                and abs(v) <= 0.10 + 0.50 * ((-0.78 - u) / 0.82))

    def _fish_at(self, x: float, y: float, *, logical: bool = False):
        """返回被点中的鱼序号（浓墨鱼在上层，优先判定）；没点中返回 None。"""
        s, _ox, _oy = self._scale_info()
        if s <= 0:
            return None
        lp = QPointF(float(x), float(y)) if logical else self._to_logical(x, y)
        t = self._t
        for i in sorted(range(len(self.fishes)),
                        key=lambda k: -self.fishes[k].ink):
            f = self.fishes[i]
            pose = self._fish_pose(f, t)
            dx, dy = lp.x() - pose.x, lp.y() - pose.y
            a = math.radians(-pose.heading)      # 逆旋转到鱼身坐标系
            u = (dx * math.cos(a) - dy * math.sin(a)) / f.size
            v = (dx * math.sin(a) + dy * math.cos(a)) / f.size
            if self._hit_local(u, v):
                return i
        return None

    # -- 鼠标 -------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if self._interactive and event.button() == Qt.LeftButton:
            pos = self._event_pos(event)
            if self.startle_at(pos.x(), pos.y(), logical=False) >= 0:
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._interactive:
            pos = self._event_pos(event)
            over = self._fish_at(pos.x(), pos.y()) is not None
            if over != self._hover:
                self._hover = over
                if over:
                    self.setCursor(Qt.PointingHandCursor)
                else:
                    self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover:
            self._hover = False
            self.unsetCursor()
        super().leaveEvent(event)

    # -- 点击处的水纹 -----------------------------------------------------
    def _draw_splashes(self, p: QPainter, t: float) -> None:
        """鼠标惊鱼留下的水纹：和其它涟漪共用同一套不规则水环。"""
        for x, y, t0 in self._splashes:
            age = t - t0
            if age < 0.0 or age >= self.SPLASH_DURATION:
                continue
            u = age / self.SPLASH_DURATION
            r = 10.0 + 108.0 * (1.0 - (1.0 - u) ** 2)
            alpha = int(self._K(1.0) * 110 * (1.0 - u) ** 2)
            if alpha <= 0:
                continue
            for k, scale in ((1.0, 1.0), (0.74, 0.55),
                             (0.50, 0.30), (0.30, 0.16)):
                self._wave_ring(p, x, y, r * k, alpha * scale,
                                flatten=0.25, phase=t * 1.7 + k * 3.0,
                                width=1.4 if k == 1.0 else 1.0)

    # ------------------------------------------------------------ 水波 / 青蛙
    def frog_pose(self, t: float | None = None) -> FrogPose:
        """查询青蛙在时刻 ``t``（默认当前）的位姿，逻辑画布坐标。"""
        return self._frog_pose(self._t if t is None else float(t))

    def frog_wave_events(self, t: float | None = None) -> list[tuple]:
        """当前存活的「青蛙 + 露珠」涟漪 ``(x, y, t0, strength)``。

        全部由 t 解析得出，不存状态；点击水纹单独记在 ``_splashes``。
        """
        return self._frog_wave_events(self._t if t is None else float(t))

    def _frog_pose(self, t: float) -> FrogPose:
        """往返跳跃：蓄力 → 抛物线 → 落地缓冲 → 停留 → 反向再来一次。"""
        u = ((t - self.FROG_PHASE) / self.FROG_PERIOD) % 1.0
        a, b = self.FROG_A, self.FROG_B
        segments = (
            (0.00, 0.10, "crouch", a, a),
            (0.10, 0.30, "hop",    a, b),
            (0.30, 0.38, "land",   b, b),
            (0.38, 0.52, "rest",   b, b),
            (0.52, 0.58, "crouch", b, b),
            (0.58, 0.78, "hop",    b, a),
            (0.78, 0.86, "land",   a, a),
            (0.86, 1.00, "rest",   a, a),
        )
        u0, u1, kind, start, end = segments[-1]
        for seg in segments:
            if u < seg[1]:
                u0, u1, kind, start, end = seg
                break
        v = (u - u0) / (u1 - u0)

        leg = airborne = squash = 0.0
        move = self.FROG_REST_HEADING
        if kind == "hop":
            x = start[0] + (end[0] - start[0]) * v
            y = start[1] + (end[1] - start[1]) * v
            airborne = 4.0 * v * (1.0 - v)
            y -= self.FROG_HOP_HEIGHT * airborne
            leg = 0.25 + 0.55 * math.sin(math.pi * v)
            # 朝向跟瞬时速度（两端连线 + 抛物线导数）走，起跳朝上、
            # 越过顶点后朝下；只用两端连线的话青蛙会一路「斜着平移」。
            vx = end[0] - start[0]
            vy = (end[1] - start[1]
                  - 4.0 * self.FROG_HOP_HEIGHT * (1.0 - 2.0 * v))
            # 写意画里不必严格照速度方向：压平纵向分量，青蛙更像贴水跃过，
            # 否则一跃而起会变成一根竖着的墨条。
            move = math.degrees(math.atan2(vy * 0.28, vx))
        else:
            x, y = start
            if kind == "crouch":
                squash = 0.55 * v
            elif kind == "land":
                squash = 0.62 * (1.0 - v)
                leg = 0.30 * (1.0 - v)
            else:                       # rest：每周期 3 次呼吸，跟着周期严格复现
                squash = 0.06 + 0.04 * math.sin(_TWO_PI * 3.0 * u)

        # 起跳 / 落地时 airborne→0，朝向自然转回静止方向，不会突然扭头
        heading = self._blend_angle(self.FROG_REST_HEADING, move,
                                    min(1.0, airborne * 1.6))
        return FrogPose(x, y, heading, leg, airborne, squash,
                        0.30 <= u < 0.58)

    def _frog_wave_events(self, t: float) -> list[tuple]:
        """枚举当前仍在水面的事件涟漪（青蛙 4 次/周期 + 两处露珠）。"""
        events: list[tuple] = []
        period, phase = self.FROG_PERIOD, self.FROG_PHASE
        marks = (
            (0.10, self.FROG_WAVE_A, 0.42),   # 蹬离大荷叶
            (0.30, self.FROG_WAVE_B, 0.85),   # 落到小荷叶
            (0.58, self.FROG_WAVE_B, 0.42),   # 蹬离小荷叶
            (0.78, self.FROG_WAVE_A, 0.85),   # 落回大荷叶
        )
        n0 = math.floor((t - phase) / period)
        for n in range(n0 - 1, n0 + 2):
            for frac, (x, y), strength in marks:
                t0 = phase + (n + frac) * period
                if 0.0 <= t - t0 < self.WAVE_DURATION:
                    events.append((x, y, t0, strength))
        for x, y, dp, offset, strength in self.dew_drops:
            n0 = math.floor(t / dp)
            for n in range(max(0, n0 - 1), n0 + 2):
                t0 = (n + offset) * dp
                if 0.0 <= t - t0 < self.WAVE_DURATION * 0.75:
                    events.append((x, y, t0, strength))
        return events

    @staticmethod
    def _wave_ring(p: QPainter, x: float, y: float, radius: float,
                   alpha: float, *, flatten: float = 0.24,
                   phase: float = 0.0, width: float = 1.0,
                   wobble: float = 0.05) -> None:
        """一圈水波：椭圆透视压扁 + 三/五阶谐波扰动 + 随时间微微呼吸。

        正椭圆画出来像靶环；加一点低频扰动才有水面折射的松紧变化。
        """
        if alpha <= 0 or radius <= 0:
            return
        path = QPainterPath()
        n = 36
        for i in range(n + 1):
            ang = _TWO_PI * i / n
            rr = radius * (1.0
                           + wobble * math.sin(3 * ang + phase)
                           + 0.018 * math.sin(5 * ang - phase))
            px = x + math.cos(ang) * rr
            py = y + math.sin(ang) * rr * flatten
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        p.setPen(QPen(QColor(*INK_SOFT, int(alpha)), width))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def _draw_frog_waves(self, p: QPainter, t: float) -> None:
        """青蛙起落与露珠滴落激起的扩散涟漪（纯函数，零状态）。"""
        for x, y, t0, strength in self._frog_wave_events(t):
            u = (t - t0) / self.WAVE_DURATION
            r = 8.0 + 96.0 * strength * (1.0 - (1.0 - u) ** 2)
            alpha = int(self._K(1.0) * 104.0 * strength * (1.0 - u) ** 2)
            if alpha <= 0:
                continue
            for k, scale in ((1.0, 1.0), (0.70, 0.48), (0.44, 0.22)):
                self._wave_ring(p, x, y, r * k, alpha * scale,
                                flatten=0.23, phase=t * 1.3 + x * 0.01,
                                width=1.3 if k == 1.0 else 1.0)

    def _draw_frog(self, p: QPainter, t: float) -> None:
        """水墨青蛙：背浓腹淡一笔身子 + 鼓眼 + 会蹬直的后腿与蹼。"""
        pose = self._frog_pose(t)
        ink = self._K(0.92)

        # 影子画在未旋转的水面坐标系里，腾空越高越淡越小
        if pose.airborne > 0.02:
            sr = (1.0 - 0.35 * pose.airborne) * self.FROG_SIZE * 0.85
            p.save()
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(
                *INK, int(26 * (1.0 - 0.6 * pose.airborne)))))
            p.drawEllipse(QRectF(pose.x - sr,
                                pose.y + 12 + 22 * pose.airborne - sr * 0.18,
                                sr * 2, sr * 0.36))
            p.restore()

        p.save()
        p.translate(pose.x, pose.y)
        p.rotate(pose.heading)
        p.scale(self.FROG_SIZE * (1.0 + 0.10 * pose.airborne),
                self.FROG_SIZE * (1.0 - 0.16 * pose.squash))

        # 后腿：近浓远淡两条，leg=0 折叠成 Z，leg=1 向后蹬直
        leg = pose.leg
        for depth, alpha in ((0.0, 1.0), (0.16, 0.48)):
            knee = (-0.92 - 0.28 * leg, 0.34 + 0.05 * leg + depth)
            heel = (-0.72 - 0.66 * leg, 0.68 - 0.10 * leg + depth)
            toe = (-1.12 - 0.70 * leg, 0.72 - 0.18 * leg + depth)
            limb = QPainterPath()
            limb.moveTo(-0.50, 0.18 + depth)
            limb.quadTo(knee[0], knee[1], heel[0], heel[1])
            limb.quadTo(heel[0] - 0.14, heel[1] + 0.04, toe[0], toe[1])
            # 粗圆笔写腿，细线会让整只蛙看起来像一只蝌蚪
            leg_pen = QPen(QColor(*INK, int(178 * ink * alpha)), 0.24)
            leg_pen.setCapStyle(Qt.RoundCap)
            leg_pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(leg_pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(limb)
            toe_pen = QPen(QColor(*INK, int(130 * ink * alpha)), 0.075)
            toe_pen.setCapStyle(Qt.RoundCap)
            for k in (-1, 0, 1):
                p.setPen(toe_pen)
                p.drawLine(QPointF(toe[0], toe[1]),
                           QPointF(toe[0] - 0.17, toe[1] + k * 0.085))

        # 身体：头圆尾尖，脊浓腹淡的渐变模拟侧锋用墨
        body = QPainterPath()
        body.moveTo(0.80, 0.0)
        body.cubicTo(0.62, -0.50, -0.28, -0.54, -0.88, -0.20)
        body.lineTo(-0.88, 0.20)
        body.cubicTo(-0.28, 0.54, 0.62, 0.50, 0.80, 0.0)
        body.closeSubpath()
        g = QLinearGradient(0, -0.55, 0, 0.55)
        g.setColorAt(0.00, QColor(*INK, int(238 * ink)))
        g.setColorAt(0.55, QColor(*INK, int(186 * ink)))
        g.setColorAt(1.00, QColor(*INK_SOFT, int(88 * ink)))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawPath(body)

        # 一笔脊线 + 几点背斑
        p.setPen(QPen(QColor(*INK_SOFT, int(70 * ink)), 0.045))
        p.setBrush(Qt.NoBrush)
        spine = QPainterPath()
        spine.moveTo(-0.70, -0.22)
        spine.quadTo(-0.05, -0.34, 0.52, -0.20)
        p.drawPath(spine)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(*INK, int(52 * ink))))
        for bx, by, r in ((-0.44, -0.12, 0.10), (-0.10, -0.20, 0.075),
                          (0.22, -0.13, 0.06)):
            p.drawEllipse(QRectF(bx - r, by - r, r * 2, r * 2))

        # 前腿与趾
        for fx, fy, alpha in ((0.38, 0.32, 1.0), (0.20, 0.36, 0.5)):
            fore = QPainterPath()
            fore.moveTo(fx, fy)
            fore.quadTo(fx + 0.10, fy + 0.22, fx - 0.02, fy + 0.34)
            fore_pen = QPen(QColor(*INK, int(150 * ink * alpha)), 0.15)
            fore_pen.setCapStyle(Qt.RoundCap)
            p.setPen(fore_pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(fore)
            for k in (-1, 0, 1):
                p.setPen(QPen(QColor(*INK, int(118 * ink * alpha)), 0.065))
                p.drawLine(QPointF(fx - 0.02, fy + 0.34),
                           QPointF(fx - 0.16, fy + 0.34 + k * 0.07))

        # 一对鼓眼：眼泡 → 纸白眼圈 → 浓墨瞳 → 一点高光
        for ex, ey in ((0.52, -0.26), (0.46, 0.26)):
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(*INK, int(205 * ink))))
            p.drawEllipse(QRectF(ex - 0.21, ey - 0.20, 0.42, 0.40))
            p.setBrush(QBrush(QColor(*PAPER, int(155 * ink))))
            p.drawEllipse(QRectF(ex - 0.10, ey - 0.10, 0.20, 0.20))
            p.setBrush(QBrush(QColor(*INK, int(245 * ink))))
            p.drawEllipse(QRectF(ex - 0.052, ey - 0.052, 0.104, 0.104))
            p.setBrush(QBrush(QColor(*PAPER, int(225 * ink))))
            p.drawEllipse(QRectF(ex - 0.065, ey - 0.065, 0.042, 0.042))

        # 嘴角一笔
        p.setPen(QPen(QColor(*INK, int(110 * ink)), 0.045))
        p.setBrush(Qt.NoBrush)
        mouth = QPainterPath()
        mouth.moveTo(0.79, 0.02)
        mouth.quadTo(0.62, 0.12, 0.44, 0.10)
        p.drawPath(mouth)
        p.restore()

    # ------------------------------------------------------------ 生命周期
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start(1000 // self._fps)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(0.1, now - self._last)     # 限制单帧跳变（休眠唤醒后不突跳）
        self._last = now
        if not self._paused:
            self._t += dt
        if self._splashes:
            self._splashes = [
                (x, y, t0) for x, y, t0 in self._splashes
                if self._t - t0 < self.SPLASH_DURATION
            ]
        self.update()

    # ------------------------------------------------------------ 构图生成
    def _build_scene(self) -> None:
        # 浓 / 中 / 淡拉开墨阶，浓墨是整幅的"骨"；左边大荷叶旁再补一片
        # 小荷叶，两片叶子之间的水面留给青蛙来回跳。
        self.leaves = [
            Leaf(255, 455, 158, 68, 0.95, -13, 0.4, 101, 7),
            Leaf(150, 585, 72, 29, 0.58, -22, 1.6, 404, 6),
            Leaf(905, 388, 114, 50, 0.62, 17, 2.1, 202, 6),
            Leaf(505, 662, 96, 24, 0.22, -7, 3.7, 303, 4),
        ]
        self.flowers = [
            Flower(690, 330, 50, 1.00, 600, 42, 0.95, 0.0),
            Flower(345, 258, 36, 0.32, 520, -26, 0.70, 1.8),
        ]
        # 前两条同轨迹、错相位，像结伴而游；后三条远近浓淡拉开层次
        self.fishes = [
            Fish(600, 545, 232, 78, 0.22, 0.4, 42, 1.00, 0.0),
            Fish(600, 545, 232, 78, 0.22, 2.8, 34, 0.72, 1.7),
            Fish(340, 632, 150, 52, -0.28, 1.1, 30, 0.58, 3.1),
            Fish(930, 600, 175, 60, 0.19, 2.7, 25, 0.48, 4.6),
            Fish(780, 470, 130, 44, -0.16, 4.2, 19, 0.38, 5.5),
        ]
        self.ripples = [
            Ripple(430, 520, 18, 120, 8.5, 0.00, 26),
            Ripple(820, 565, 16, 105, 9.8, 0.37, 22),
            Ripple(275, 605, 14, 92, 7.4, 0.62, 20),
            Ripple(975, 495, 15, 96, 10.6, 0.81, 18),
            Ripple(205, 545, 12, 86, 6.8, 0.28, 16),  # 两片荷叶之间
        ]
        # 叶缘露珠：周期 / 相位 / 强度各不相同，落水时补一圈小涟漪。
        # (x, y, period, offset, strength)，全靠 t 解析，不存状态。
        self.dew_drops = [
            (372.0, 528.0, 5.3, 0.20, 0.48),
            (210.0, 614.0, 6.7, 0.62, 0.38),
        ]
        self.weeds = [
            (160, 792, 5, 1),
            (1082, 792, 4, 2),
        ]
        self.petals = [
            (24.0, 0.00, 1.00),
            (31.0, 0.55, 0.70),
        ]
        rng = self._rng
        self.water_lines = [
            WaterLine(
                y=300 + i * 48 + rng.uniform(-12, 12),
                x=rng.uniform(0, self.CW),
                length=rng.uniform(70, 260),
                alpha=rng.uniform(7, 17),
            )
            for i in range(9)
        ]

    # ------------------------------------------------------------ 宣纸纹理
    def _make_paper(self, n: int) -> QImage:
        """生成一张可无缝平铺的宣纸纹理（纤维 + 噪点 + 淡云斑）。"""
        rng = random.Random(9137)
        img = QImage(n, n, QImage.Format_RGB32)
        img.fill(QColor(*PAPER))
        p = QPainter(img)
        p.setPen(Qt.NoPen)

        # 大块极淡的暖灰云斑。九宫格环绕绘制，保证纹理平铺时边界连续，
        # 否则 tile 边界会露出一条明显的水平色差线。
        for _ in range(14):
            cx, cy = rng.uniform(0, n), rng.uniform(0, n)
            r = rng.uniform(60, 190)
            a = rng.randint(4, 10)
            for ox in (-n, 0, n):
                for oy in (-n, 0, n):
                    g = QRadialGradient(cx + ox, cy + oy, r)
                    g.setColorAt(0.0, QColor(150, 138, 116, a))
                    g.setColorAt(1.0, QColor(150, 138, 116, 0))
                    p.setBrush(QBrush(g))
                    p.drawEllipse(QRectF(cx + ox - r, cy + oy - r,
                                        r * 2, r * 2))

        # 纸纤维：短促的暖灰细线
        for _ in range(1100):
            x, y = rng.uniform(0, n), rng.uniform(0, n)
            length = rng.uniform(2, 13)
            angle = rng.uniform(-0.35, 0.35)
            p.setPen(QPen(QColor(138, 128, 108, rng.randint(3, 11)), 0.6))
            p.drawLine(QPointF(x, y),
                       QPointF(x + length * math.cos(angle),
                               y + length * math.sin(angle)))
        p.end()

        # 细噪点：走 QImage 像素接口，避免上万次切换 QPainter 画笔状态
        dark = QColor(236, 230, 216)
        light = QColor(253, 251, 245)
        for _ in range(2600):
            x, y = rng.randrange(n), rng.randrange(n)
            img.setPixelColor(x, y, dark if rng.random() < 0.55 else light)
        return img

    def _pick_serif_font(self) -> QFont | None:
        """挑一个可用的中文衬线/楷体用于题款；没有则题款降级为纯印章。"""
        families = QFontDatabase.families()
        for name in ("Kaiti SC", "STKaiti", "KaiTi", "楷体",
                     "Noto Serif CJK SC", "Source Han Serif SC",
                     "Songti SC", "SimSun", "宋体", "Noto Serif CJK"):
            if name in families:
                return QFont(name, 26)
        for name in families:
            if any(k in name for k in ("Kai", "Song", "Serif CJK", "楷", "宋")):
                return QFont(name, 26)
        return None

    # ------------------------------------------------------------ 绘制入口
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        # 1) 宣纸：纹理平铺铺满整个控件（不随逻辑画布缩放）
        p.setPen(Qt.NoPen)
        paper_brush = QBrush(self._paper)
        p.fillRect(self.rect(), paper_brush)

        # 2) 切到固定逻辑画布，等比缩放居中，四周留白
        #    缩放口径与 _to_logical / _to_widget 共用 _scale_info()，
        #    否则鼠标命中会和画出来的鱼错开。
        w, h = self.width(), self.height()
        s, ox, oy = self._scale_info()
        p.save()
        p.translate(ox, oy)
        p.scale(s, s)

        t = self._t
        self._draw_mist(p)
        self._draw_water_lines(p, t)
        self._draw_ripples(p, t)
        self._draw_splashes(p, t)
        self._draw_frog_waves(p, t)       # 涟漪在水面层，压在荷叶之下
        self._draw_weeds(p, t)
        self._draw_stems(p, t)
        for leaf in self.leaves:
            self._draw_leaf(p, leaf, t)
        self._draw_frog(p, t)             # 青蛙站在荷叶之上
        for flower in self.flowers:
            self._draw_flower(p, flower, t)
        self._draw_rolled_leaf(p, t)
        # 由淡到浓绘制，浓墨鱼自然压在上层
        for fish in sorted(self.fishes, key=lambda f: f.ink):
            self._draw_fish(p, fish, t)
        self._draw_petals(p, t)
        self._draw_inscription(p)
        p.restore()

        # 3) 极淡的四角旧纸暗角
        self._draw_vignette(p, w, h)
        p.end()

    def _K(self, v: float) -> float:
        """统一浓度系数，便于整体调墨。"""
        return max(0.0, min(1.0, v * self.ink_density))

    # ------------------------------------------------------------ 基础笔触
    @staticmethod
    def _smooth_closed(points) -> QPainterPath:
        """用二次贝塞尔把一圈点连成平滑闭合轮廓。"""
        n = len(points)
        path = QPainterPath()
        x0, y0 = points[-1]
        x1, y1 = points[0]
        path.moveTo((x0 + x1) / 2, (y0 + y1) / 2)
        for i in range(n):
            ax, ay = points[i]
            bx, by = points[(i + 1) % n]
            path.quadTo(ax, ay, (ax + bx) / 2, (ay + by) / 2)
        path.closeSubpath()
        return path

    def _blob_path(self, rng: random.Random, jag: float, n: int = 30) -> QPainterPath:
        """带随机扰动的不规则墨团轮廓（单位圆）。"""
        base = rng.uniform(0, _TWO_PI)
        # 偶尔留一道笔锋缺口，避免规整的椭圆感
        notch_at = rng.uniform(0, _TWO_PI)
        pts = []
        for i in range(n):
            a = _TWO_PI * i / n
            r = (1.0
                 + jag * (rng.random() * 2 - 1)
                 + 0.055 * math.sin(3 * a + base)
                 + 0.035 * math.sin(5 * a - base))
            d = abs((a - notch_at + math.pi) % _TWO_PI - math.pi)
            if d < 0.30:
                r -= 0.15 * (1.0 - d / 0.30)
            pts.append((math.cos(a) * r, math.sin(a) * r))
        return self._smooth_closed(pts)

    def _ink_blot(self, p: QPainter, cx: float, cy: float,
                  rx: float, ry: float, ink: float, seed: int,
                  rotation: float = 0.0, jag: float = 0.13) -> None:
        """一笔侧锋墨团：径向渗墨 + 不规则笔触 + 断续飞白 + 溅墨。

        用径向渐变而不是多层纯色叠加 —— 后者每层都是硬边，会留下
        一圈圈"等高线"水渍感。QRadialGradient(cx, cy, radius) 的
        第三个参数才是渐变半径，写成 0 会让整片墨完全透明。
        """
        ink = self._K(ink)
        if ink <= 0.002 or rx <= 0 or ry <= 0:
            return
        rng = random.Random(seed)
        p.save()
        p.translate(cx, cy)
        if rotation:
            p.rotate(rotation)

        # (a) 外晕：墨在宣纸上洇开的一圈极淡水痕
        halo = QRadialGradient(0, 0, 1.0)
        halo.setColorAt(0.0, QColor(*INK, int(26 * ink)))
        halo.setColorAt(1.0, QColor(*INK, 0))
        p.save()
        p.scale(rx * 1.30, ry * 1.30)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(halo))
        p.drawEllipse(QRectF(-1, -1, 2, 2))
        p.restore()

        # (b) 笔触本体：不规则轮廓 + 中心浓、边缘洇淡的径向渗墨
        outline = self._blob_path(rng, jag)
        body = QRadialGradient(0, 0, 1.0)
        body.setColorAt(0.00, QColor(*INK, int(210 * ink)))
        body.setColorAt(0.42, QColor(*INK, int(168 * ink)))
        body.setColorAt(0.75, QColor(*INK, int(72 * ink)))
        body.setColorAt(1.00, QColor(*INK, 0))
        p.save()
        p.scale(rx, ry)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(body))
        p.drawPath(outline)
        p.restore()

        # (c) 飞白：几组断续短划，模拟笔锋快速擦过留下的丝缕
        for _ in range(3):
            y = rng.uniform(-0.50, 0.50) * ry
            x = rng.uniform(-0.75, 0.00) * rx
            for _ in range(rng.randint(2, 3)):
                seg = rng.uniform(0.12, 0.30) * rx
                p.setPen(QPen(QColor(*PAPER, int(76 * ink)),
                              rng.uniform(0.8, 1.8)))
                p.drawLine(QPointF(x, y),
                           QPointF(x + seg, y + rng.uniform(-2, 2)))
                x += seg + rng.uniform(0.05, 0.16) * rx

        # (d) 轮廓外的溅墨小点，模拟宣纸洇开
        p.setPen(Qt.NoPen)
        for _ in range(13):
            a = rng.uniform(0, _TWO_PI)
            rr = rng.uniform(0.90, 1.24)
            px = math.cos(a) * rx * rr
            py = math.sin(a) * ry * rr
            rad = rng.uniform(0.9, 3.2) * (0.5 + ink)
            p.setBrush(QBrush(QColor(*INK, int(rng.uniform(18, 55) * ink))))
            p.drawEllipse(QRectF(px - rad, py - rad, rad * 2, rad * 2))
        p.restore()

    # ------------------------------------------------------------ 远景与水面
    def _draw_mist(self, p: QPainter) -> None:
        """极淡远水：断续横笔，不用色块，避免生硬的水平色带。"""
        rng = random.Random(414)
        for i in range(3):
            y = 226 + i * 48
            x = 90 + i * 55
            for _ in range(5):
                seg = rng.uniform(40, 95)
                a = int(self._K(1.0) * rng.uniform(4, 10))
                p.setPen(QPen(QColor(*INK_SOFT, a), rng.uniform(0.8, 1.6)))
                yy = y + rng.uniform(-3, 3)
                p.drawLine(QPointF(x, yy), QPointF(x + seg, yy))
                x += seg + rng.uniform(20, 70)

    def _draw_water_lines(self, p: QPainter, t: float) -> None:
        """几道断续的极淡水纹，缓慢横向流动。"""
        for line in self.water_lines:
            x = (line.x + t * 7.0) % (self.CW + 300) - 150
            a = int(self._K(line.alpha / 20.0) * line.alpha)
            p.setPen(QPen(QColor(*INK_SOFT, max(0, a)), 1.1))
            p.drawLine(QPointF(x, line.y),
                       QPointF(x + line.length, line.y - 0.6))
            # 断笔：旁边再补一小截更淡的
            p.setPen(QPen(QColor(*INK_SOFT, max(0, a // 2)), 0.9))
            p.drawLine(QPointF(x + line.length + 24, line.y + 1.4),
                       QPointF(x + line.length + 24 + line.length * 0.35,
                               line.y + 1.0))

    def _draw_ripples(self, p: QPainter, t: float) -> None:
        """常驻的氛围水波：一圈主波 + 三圈余波，带扰动、缓慢扩散淡出。"""
        for r in self.ripples:
            ph = ((t / r.period) + r.offset) % 1.0
            radius = r.r0 + (r.r1 - r.r0) * ph
            alpha = int(self._K(1.0) * r.alpha * 1.7 * (1.0 - ph) ** 1.6)
            if alpha <= 0:
                continue
            for k, scale in ((1.0, 1.0), (0.82, 0.50),
                             (0.62, 0.28), (0.44, 0.14)):
                self._wave_ring(p, r.x, r.y, radius * k, alpha * scale,
                                flatten=0.21,
                                phase=t * 0.9 + r.offset * 10.0,
                                width=1.3 if k == 1.0 else 0.95)

    def _draw_weeds(self, p: QPainter, t: float) -> None:
        """水底几丛水草，随暗流轻轻摆动，墨色极淡。"""
        for bx, by, count, seed in self.weeds:
            rng = random.Random(seed * 31)
            for i in range(count):
                height = rng.uniform(70, 155)
                drift = rng.uniform(-46, 46)
                sway = math.sin(t * 0.55 + i * 0.8 + seed) * 9
                path = QPainterPath()
                x0 = bx + (i - count / 2) * 11
                path.moveTo(x0, by)
                path.cubicTo(x0 - 8 + sway * 0.3, by - height * 0.45,
                             x0 + drift * 0.4 + sway, by - height * 0.75,
                             x0 + drift + sway, by - height)
                p.setPen(QPen(QColor(*INK_SOFT, int(self._K(0.9) * 30)), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)

    # ------------------------------------------------------------ 荷
    def _draw_stems(self, p: QPainter, t: float) -> None:
        for f in self.flowers:
            sway = math.sin(t * 0.42 + f.phase) * 3.5
            x0 = f.x + f.lean * 0.45 + sway
            path = QPainterPath()
            path.moveTo(x0, f.stem_end)
            path.quadTo(f.x - f.lean * 0.85 + sway * 0.5,
                        (f.y + f.stem_end) / 2,
                        f.x + sway * 0.25, f.y)
            p.setPen(QPen(QColor(*INK_SOFT, int(self._K(0.9) * 88)), 2.2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            # 梗上小刺
            p.setPen(QPen(QColor(*INK_SOFT, int(self._K(0.8) * 52)), 1.0))
            for k in (0.35, 0.62):
                yy = f.stem_end + (f.y - f.stem_end) * k
                xx = x0 + (f.x - x0) * k
                p.drawLine(QPointF(xx, yy), QPointF(xx + 6, yy - 5))

    def _draw_leaf(self, p: QPainter, leaf: Leaf, t: float) -> None:
        sway = 1.5 * math.sin(t * 0.38 + leaf.phase)
        p.save()
        p.translate(leaf.x, leaf.y)
        p.rotate(leaf.tilt + sway)
        self._ink_blot(p, 0, 0, leaf.rx, leaf.ry, leaf.ink, leaf.seed, jag=0.17)

        rng = random.Random(leaf.seed + 99)
        # 叶脐：很小的一点纸色，不做规整的大留白
        g = QRadialGradient(0, -leaf.ry * 0.10, leaf.rx * 0.13)
        g.setColorAt(0.0, QColor(*PAPER, int(58 * self._K(leaf.ink))))
        g.setColorAt(1.0, QColor(*PAPER, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QRectF(-leaf.rx * 0.13, -leaf.ry * 0.22,
                            leaf.rx * 0.26, leaf.ry * 0.28))

        # 放射叶脉：略带弧度，浓叶用纸色提，淡叶用极淡墨轻轻带过
        if leaf.ink > 0.5:
            vein = QColor(*PAPER, int(64 * self._K(leaf.ink)))
        else:
            vein = QColor(*INK_SOFT, int(20 * self._K(1.0)))
        for i in range(leaf.veins):
            a = math.pi * (i + 0.5) / leaf.veins + math.pi
            ex = math.cos(a) * leaf.rx * rng.uniform(0.72, 0.90)
            ey = math.sin(a) * leaf.ry * rng.uniform(0.70, 0.88)
            path = QPainterPath()
            path.moveTo(0, 0)
            path.quadTo(ex * 0.5 + rng.uniform(-7, 7),
                        ey * 0.5 + rng.uniform(-5, 5), ex, ey)
            p.setPen(QPen(vein, 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        # 叶柄
        p.setPen(QPen(QColor(*INK_SOFT, int(32 * self._K(leaf.ink))), 2.0))
        p.drawLine(QPointF(0, leaf.ry * 0.2),
                   QPointF(-leaf.rx * 0.12, leaf.ry + 34))
        p.restore()

    def _petal(self, p: QPainter, length: float, width: float,
               tint: float, alpha: int) -> None:
        """一片尖瓣：淡墨勾线 + 瓣尖胭脂。"""
        path = QPainterPath()
        path.moveTo(0, 0)
        path.quadTo(-width, -length * 0.48, 0, -length)
        path.quadTo(width, -length * 0.48, 0, 0)
        p.setPen(QPen(QColor(*INK_SOFT, alpha), 1.6))
        p.setBrush(QBrush(QColor(*PINK, int(34 * tint))))
        p.drawPath(path)
        # 瓣尖一点胭脂：细长形，顺着瓣势，不要圆点
        g = QRadialGradient(0, -length * 0.86, length * 0.42)
        g.setColorAt(0.0, QColor(*PINK, int(112 * tint)))
        g.setColorAt(1.0, QColor(*PINK, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QRectF(-width * 0.52, -length * 1.02,
                            width * 1.04, length * 0.52))

    def _draw_flower(self, p: QPainter, f: Flower, t: float) -> None:
        sway = 2.2 * math.sin(t * 0.42 + f.phase)
        p.save()
        p.translate(f.x + sway * 0.25, f.y)
        p.rotate(sway)
        s = f.size / 47.0
        p.scale(s, s)

        n = 8 if f.openness > 0.8 else 4
        spread = 58 + 36 * f.openness          # 花瓣张开的角度
        alpha = int(self._K(1.0) * 148)

        # 外层花瓣
        for i in range(n):
            a = -spread + (2 * spread) * (i / (n - 1))
            p.save()
            p.rotate(a)
            self._petal(p, 47 * (0.72 + 0.28 * f.openness),
                        15 + 4 * f.openness, f.tint, alpha)
            p.restore()
        # 内层短瓣
        if f.openness > 0.8:
            for i in range(5):
                p.save()
                p.rotate(-40 + i * 20)
                self._petal(p, 30, 11, f.tint * 0.7, int(alpha * 0.85))
                p.restore()

        # 花蕊：藤黄几点 + 浓墨花心
        rng = random.Random(int(f.x))
        for _ in range(9):
            a = rng.uniform(0, _TWO_PI)
            rr = rng.uniform(3, 11)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(*POLLEN, int(self._K(1.0) * 155))))
            p.drawEllipse(QRectF(math.cos(a) * rr - 1.3,
                                math.sin(a) * rr - 1.3, 2.6, 2.6))
        p.setBrush(QBrush(QColor(*INK, int(self._K(1.0) * 190))))
        p.drawEllipse(QRectF(-3, -3, 6, 6))
        p.restore()

    def _draw_rolled_leaf(self, p: QPainter, t: float) -> None:
        """一片未展开的卷叶，两笔弧线，最见简约。"""
        sway = math.sin(t * 0.4 + 1.3) * 2.0
        p.save()
        p.translate(1010 + sway, 520)
        p.rotate(-8 + sway)
        ink = self._K(0.70)
        path = QPainterPath()
        path.moveTo(0, 0)
        path.quadTo(-26, -62, 6, -118)
        path.quadTo(12, -60, 0, 0)
        p.setPen(QPen(QColor(*INK_SOFT, int(150 * ink)), 1.9))
        p.setBrush(QBrush(QColor(*INK, int(58 * ink))))
        p.drawPath(path)
        # 卷叶的叶柄
        p.setPen(QPen(QColor(*INK_SOFT, int(95 * ink)), 2.0))
        p.setBrush(Qt.NoBrush)
        stem = QPainterPath()
        stem.moveTo(0, 0)
        stem.quadTo(-8, 40, 2, 86)
        p.drawPath(stem)
        p.restore()

    # ------------------------------------------------------------ 鱼
    def _draw_fish(self, p: QPainter, f: Fish, t: float) -> None:
        # 位姿统一由 _fish_pose 算（含惊逃位移 / 朝向 / 急摆尾），
        # 命中测试查的也是它，鱼跑开后可点区域会跟着走。
        pose = self._fish_pose(f, t)
        x, y, heading, wag = pose.x, pose.y, pose.heading, pose.wag
        ink = self._K(f.ink)

        p.save()
        p.translate(x, y)
        p.rotate(heading)
        p.scale(f.size, f.size)          # 单位鱼：体长约 2

        # 尾鳍：上下两笔明确分叉，随摆尾张合
        for sign in (-1, 1):
            fin = QPainterPath()
            fin.moveTo(-0.80, 0.0)
            fin.quadTo(-1.12, sign * (0.20 + wag * 0.06),
                       -1.52, sign * (0.48 + wag * 0.17))
            fin.quadTo(-1.14, sign * 0.06, -0.86, 0.0)
            fin.closeSubpath()
            p.setPen(QPen(QColor(*INK, int(70 * ink)), 0.035))
            p.setBrush(QBrush(QColor(*INK, int(140 * ink))))
            p.drawPath(fin)

        # 身体：头圆尾尖的一笔，脊浓腹淡的渐变模拟笔墨层次
        bend = wag * 0.07
        body = QPainterPath()
        body.moveTo(0.95, 0.0)
        body.cubicTo(0.72, -0.34 + bend, -0.20, -0.36 - bend, -0.86, -0.075)
        body.lineTo(-0.86, 0.075)
        body.cubicTo(-0.20, 0.36 - bend, 0.72, 0.34 + bend, 0.95, 0.0)
        body.closeSubpath()
        g = QLinearGradient(0, -0.42, 0, 0.42)
        g.setColorAt(0.0, QColor(*INK, int(242 * ink)))
        g.setColorAt(0.48, QColor(*INK, int(198 * ink)))
        g.setColorAt(1.0, QColor(*INK_SOFT, int(96 * ink)))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawPath(body)

        # 一笔浓墨脊线，写意画鱼的点睛之笔
        spine = QPainterPath()
        spine.moveTo(0.72, -0.17)
        spine.quadTo(0.05, -0.34 + bend, -0.78, -0.05)
        p.setPen(QPen(QColor(*INK, int(130 * ink)), 0.055))
        p.setBrush(Qt.NoBrush)
        p.drawPath(spine)

        # 鳃线：点明头部朝向
        gill = QPainterPath()
        gill.moveTo(0.56, -0.21)
        gill.quadTo(0.40, 0.0, 0.56, 0.21)
        p.setPen(QPen(QColor(*INK, int(95 * ink)), 0.045))
        p.drawPath(gill)

        # 胸鳍：极淡的一笔
        pec = QPainterPath()
        pec.moveTo(0.16, 0.16)
        pec.quadTo(-0.02, 0.36 + wag * 0.06, -0.22, 0.30)
        p.setPen(QPen(QColor(*INK_SOFT, int(62 * ink)), 0.030))
        p.drawPath(pec)

        # 眼睛：一点浓墨，旁留一点纸白
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(*PAPER, int(135 * ink))))
        p.drawEllipse(QRectF(0.55, -0.17, 0.15, 0.15))
        p.setBrush(QBrush(QColor(*INK, int(240 * ink))))
        p.drawEllipse(QRectF(0.585, -0.135, 0.082, 0.082))
        p.restore()

    # ------------------------------------------------------------ 飘落花瓣
    def _draw_petals(self, p: QPainter, t: float) -> None:
        """一两片胭脂花瓣缓缓飘落，与浓墨鱼形成色彩上的对比。"""
        for period, offset, tint in self.petals:
            ph = ((t / period) + offset) % 1.0
            y = 210 + ph * 560
            x = 690 + math.sin(ph * 7.0 + offset * 10) * 72 + ph * 55
            alpha = int(self._K(1.0) * 190 * min(1.0, (1.0 - ph) * 3.0))
            p.save()
            p.translate(x, y)
            p.rotate(ph * 210 + offset * 90)
            petal = QPainterPath()
            petal.moveTo(0, 0)
            petal.quadTo(-9, -14, 0, -26)
            petal.quadTo(9, -14, 0, 0)
            p.setPen(QPen(QColor(*INK_SOFT, int(alpha * 0.45)), 1.0))
            p.setBrush(QBrush(QColor(*PINK, int(alpha * 0.72 * tint))))
            p.drawPath(petal)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(*PINK, int(alpha * 0.55 * tint))))
            p.drawEllipse(QRectF(-2.5, -25, 5, 7))
            p.restore()

    # ------------------------------------------------------------ 题款与印
    def _draw_inscription(self, p: QPainter) -> None:
        # 铺满模式会裁掉上方留白区，题款与印章索性不画，避免残缺
        if self.fit == "cover":
            return
        # 竖排题款
        if self._font is not None:
            f = QFont(self._font)
            f.setPointSize(25)
            p.setFont(f)
            p.setPen(QColor(*INK, int(self._K(1.0) * 125)))
            for i, ch in enumerate("荷塘清趣"):
                p.drawText(QRectF(1002, 96 + i * 38, 34, 38),
                           Qt.AlignCenter, ch)

        # 朱文小印
        x, y, size = 1050, 96, 46
        rng = random.Random(77)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(*SEAL, int(self._K(1.0) * 210))))
        p.drawRoundedRect(QRectF(x, y, size, size), 2.5, 2.5)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(*PAPER, 165), 1.3))
        p.drawRect(QRectF(x + 4, y + 4, size - 8, size - 8))

        if self._font is not None:
            f = QFont(self._font)
            f.setPointSize(25)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(*PAPER, 235))
            p.drawText(QRectF(x, y, size, size), Qt.AlignCenter, "墨")
        else:
            # 无中文字体时用几何篆纹代替
            p.setPen(QPen(QColor(*PAPER, 220), 2.0))
            p.drawLine(QPointF(x + 12, y + 15), QPointF(x + 34, y + 15))
            p.drawLine(QPointF(x + 23, y + 12), QPointF(x + 23, y + 34))
            p.drawLine(QPointF(x + 12, y + 32), QPointF(x + 34, y + 32))

        # 印泥斑驳：几点纸色缺口，添金石味
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(*PAPER, 120)))
        for _ in range(16):
            px = x + rng.uniform(0, size)
            py = y + rng.uniform(0, size)
            r = rng.uniform(0.6, 2.0)
            p.drawEllipse(QRectF(px - r, py - r, r * 2, r * 2))

    def _draw_vignette(self, p: QPainter, w: float, h: float) -> None:
        g = QRadialGradient(w / 2, h / 2, math.hypot(w, h) * 0.62)
        g.setColorAt(0.0, QColor(120, 106, 82, 0))
        g.setColorAt(0.55, QColor(120, 106, 82, 0))
        g.setColorAt(1.0, QColor(120, 106, 82, 26))
        p.setPen(Qt.NoPen)
        p.fillRect(self.rect(), QBrush(g))


# ---------------------------------------------------------------- 演示入口
if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    win = QMainWindow()
    win.setWindowTitle("水墨 · 荷塘清趣  |  InkPondWidget")
    win.resize(1180, 760)
    win.setStyleSheet("QMainWindow{background:#f7f3e8;}")
    pond = InkPondWidget(fps=30)
    win.setCentralWidget(pond)
    win.statusBar().showMessage("左键点一下鱼身：鱼会受惊逃窜，片刻后自行归队")
    win.show()
    sys.exit(app.exec())
