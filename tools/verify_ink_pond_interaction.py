# -*- coding: utf-8 -*-
"""``InkPondWidget`` 点击惊鱼交互回归门禁。

覆盖 8 组：

1. 默认态等价：无逃窜时每条鱼的位姿与改动前的旧公式逐项零误差；
   ``reset_fishes()`` 前后渲染帧逐像素一致；空水纹不画任何东西。
2. 命中判定：鱼心 / 鱼身 / 鱼尾都能点中，空白点不中；``contain`` /
   ``cover`` / 任意窗口尺寸下控件像素 ↔ 逻辑画布坐标严格互逆。
3. 惊散曲线：峰值位移、朝向插值、2.8s 归位、同伴强度衰减与延迟、
   重复点击覆盖、``reset_fishes()`` 复位。
4. 时间纯函数：任意跳转顺序结果一致、暂停冻结、``is_fleeing``、
   水纹生成 / 过期清理 / 数量上限。
5. 真实鼠标链路：QTest 左键点击 → ``mousePressEvent`` → 惊动；右键不触发；
   hover 手型光标；``set_interactive`` 开关。
6. 渲染差异：受惊帧确实不同于基线帧，复位后又能逐像素回到基线。
7. 构图 / 水波 / 青蛙：4 片荷叶、往返跳跃的各阶段位姿与周期重复性、
   落地 / 露珠涟漪事件、水波环确实画出像素、任意跳转后帧仍确定。
8. 运行态集成：在 ``PopPickWindow`` 里按鱼的真实视口坐标点一下，验证
   点击能穿透 7 张只读卡片 / QGraphicsProxyWidget 到达背景控件并惊动鱼。

跑法::

    .venv/Scripts/python.exe tools/verify_ink_pond_interaction.py
"""

from __future__ import annotations

import math
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from App_PopPick_V2.ink_pond_widget import (  # noqa: E402
    PAPER, InkPondWidget,
)

_RESULTS: list[tuple[bool, str, str]] = []
_T0 = 12.0


def check(label: str, ok: bool, detail: str = "") -> None:
    _RESULTS.append((bool(ok), label, detail))


def _report() -> int:
    failed = 0
    for ok, label, detail in _RESULTS:
        tag = "PASS" if ok else "FAIL"
        suffix = f"  ({detail})" if detail else ""
        print(f"[{tag}] {label}{suffix}")
        if not ok:
            failed += 1
    print(f"\n{len(_RESULTS) - failed}/{len(_RESULTS)} passed")
    return 0 if failed == 0 else 1


def _group(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 60 - len(title)))


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _frame(w: InkPondWidget) -> bytes:
    """抓一帧同步渲染（grab 内部直接 render，不等 update 事件）。"""
    img = w.grab().toImage()
    bits = img.constBits() if hasattr(img, "constBits") else img.bits()
    return bytes(bits)


def _old_pose(f, t: float) -> tuple[float, float, float, float]:
    """改动前 ``_draw_fish`` 里的位姿公式，作为对拍真值。"""
    ang = t * f.speed + f.phase
    x = f.cx + f.rx * math.cos(ang)
    y = f.cy + f.ry * math.sin(ang) + 10 * math.sin(2 * ang)
    dx = -f.rx * math.sin(ang) * f.speed
    dy = (f.ry * math.cos(ang) + 20 * math.cos(2 * ang)) * f.speed
    return (x, y, math.degrees(math.atan2(dy, dx)),
            math.sin(t * 6.4 + f.tail_phase))


def _local_to_logical(pose, f, u: float, v: float) -> tuple[float, float]:
    """单位鱼局部坐标 → 逻辑画布坐标（正旋转 + 缩放）。"""
    a = math.radians(pose.heading)
    return (pose.x + (u * math.cos(a) - v * math.sin(a)) * f.size,
            pose.y + (u * math.sin(a) + v * math.cos(a)) * f.size)


# ----------------------------------------------------------------------
def group_default(w: InkPondWidget) -> None:
    """组 1：默认态与改动前逐项等价，渲染帧可完全复位。"""
    _group("1 默认态等价 / 零回归")

    worst = 0.0
    for t in (0.0, 1.37, 7.9, _T0, 23.4, 100.25):
        for i, f in enumerate(w.fishes):
            p = w.fish_pose(i, t)
            worst = max(worst, *(abs(a - b) for a, b in
                                 zip((p.x, p.y, p.heading, p.wag),
                                     _old_pose(f, t))))
    check("默认位姿与旧公式零误差", worst == 0.0, f"max={worst}")

    w.reset_fishes()
    w.set_time(_T0)
    base = _frame(w)
    check("初始无水纹", w.splash_count() == 0, str(w.splash_count()))
    check("无鱼在逃窜", not any(w.is_fleeing(i) for i in range(5)))
    w.reset_fishes()
    w.set_time(_T0)
    check("reset 后渲染帧逐像素一致", _frame(w) == base)

    # 塞一条已过期水纹：屏幕上不该有任何变化
    w._splashes.append((600.0, 545.0, _T0 - 99.0))
    w.update()
    check("过期水纹不绘制", _frame(w) == base)
    w.reset_fishes()


def group_hit(w: InkPondWidget) -> None:
    """组 2：鱼身命中与坐标口径。"""
    _group("2 命中判定 / 坐标换算")

    w.reset_fishes()
    w.set_time(_T0)
    for i, f in enumerate(w.fishes):
        p = w.fish_pose(i)
        hit = w.startle_at(p.x, p.y)
        check(f"鱼 {i} 鱼心命中", hit == i, f"hit={hit}")
        w.reset_fishes()

    # 鱼身前段 / 尾鳍 / 远处空白
    f = w.fishes[0]
    p = w.fish_pose(0)
    body_x, body_y = _local_to_logical(p, f, 0.80, 0.0)
    tail_x, tail_y = _local_to_logical(p, f, -1.20, 0.0)
    check("鱼身前段命中", w.startle_at(body_x, body_y) >= 0)
    w.reset_fishes()
    check("尾鳍命中", w.startle_at(tail_x, tail_y) >= 0)
    w.reset_fishes()
    check("远处空白不命中", w.startle_at(50.0, 50.0) == -1)
    check("空白不改变鱼状态", not any(x.flee_power for x in w.fishes))
    check("空白不产生水纹", w.splash_count() == 0)

    # 逻辑 ↔ 控件像素互逆（contain 当前 1200x800）
    for lx, ly in ((0.0, 0.0), (600.0, 545.0), (1199.0, 799.0)):
        wp = w._to_widget(lx, ly)
        lp = w._to_logical(wp.x(), wp.y())
        err = math.hypot(lp.x() - lx, lp.y() - ly)
        check(f"contain 坐标互逆 ({lx:.0f},{ly:.0f})", err < 1e-9,
              f"err={err:.2e}")

    # cover + 非等比窗口：同样严格互逆，且点击控件像素能命中鱼心
    cover = InkPondWidget(fps=30, fit="cover")
    cover.resize(1600, 800)
    cover.set_time(_T0)
    for lx, ly in ((0.0, 0.0), (600.0, 545.0), (1199.0, 799.0)):
        wp = cover._to_widget(lx, ly)
        lp = cover._to_logical(wp.x(), wp.y())
        err = math.hypot(lp.x() - lx, lp.y() - ly)
        check(f"cover 坐标互逆 ({lx:.0f},{ly:.0f})", err < 1e-9,
              f"err={err:.2e}")
    cp = cover.fish_pose(0)
    wp = cover._to_widget(cp.x, cp.y)
    check("cover 下按像素点击命中鱼心",
          cover.startle_at(wp.x(), wp.y(), logical=False) == 0)
    cover.reset_fishes()
    cover.set_time(_T0)
    cover.deleteLater()

    # 换成小窗口后命中仍跟随缩放
    w.resize(700, 460)
    p = w.fish_pose(2)
    wp = w._to_widget(p.x, p.y)
    check("小窗口按像素点击命中", w.startle_at(wp.x(), wp.y(),
                                          logical=False) == 2)
    w.resize(1200, 800)
    w.reset_fishes()


def group_flee(w: InkPondWidget) -> None:
    """组 3：逃窜曲线、朝向、同伴惊散、复位。"""
    _group("3 惊散曲线 / 归位")

    w.reset_fishes()
    w.set_time(_T0)
    p0 = w.fish_pose(0)
    offsets = (0.0, 0.05, 0.20, 0.40, 1.00, 2.00, 2.79, 2.80, 3.50)
    base = {dt: w.fish_pose(0, _T0 + dt) for dt in offsets}
    hit = w.startle_at(p0.x, p0.y)
    check("startle_at 返回被点中的鱼", hit == 0, f"hit={hit}")
    check("惊动计数 +1", w.startle_count() >= 1)

    devs = {}
    for dt in offsets:
        p = w.fish_pose(0, _T0 + dt)
        devs[dt] = math.hypot(p.x - base[dt].x, p.y - base[dt].y)
    check("起跳时刻位移为 0", devs[0.0] < 1e-9, f"{devs[0.0]:.4f}")
    check("0.2~0.4s 冲出超过 150 单位",
          devs[0.20] > 150 and devs[0.40] > 150,
          f"{devs[0.20]:.1f}/{devs[0.40]:.1f}")
    check("峰值不超过 230 单位", max(devs.values()) <= 230.0,
          f"{max(devs.values()):.1f}")
    check("1s 后开始回落", devs[1.00] < devs[0.40],
          f"{devs[1.00]:.1f} < {devs[0.40]:.1f}")
    check("2.8s 精确归位", devs[2.80] < 1e-9, f"{devs[2.80]:.6f}")
    check("归位后不再反弹", devs[3.50] < 1e-9, f"{devs[3.50]:.6f}")

    # 朝向：受惊时转向逃窜方向，之后回到原巡游切线
    fled = w.fish_pose(0, _T0 + 0.4)
    flee_heading = math.degrees(math.atan2(w.fishes[0].flee_dy,
                                          w.fishes[0].flee_dx))
    def _angle_gap(a, b):
        return abs((a - b + 180.0) % 360.0 - 180.0)
    check("受惊时朝向贴近逃窜方向",
          _angle_gap(fled.heading, flee_heading) < 5.0,
          f"{fled.heading:.1f} vs {flee_heading:.1f}")
    check("归位后朝向回到轨迹切线",
          _angle_gap(w.fish_pose(0, _T0 + 2.8).heading,
                     base[2.80].heading) < 1e-6)
    plain_wag = math.sin((_T0 + 0.4) * 6.4 + w.fishes[0].tail_phase)
    check("受惊时叠加了急摆尾",
          abs(fled.wag - plain_wag) > 1e-6,
          f"{fled.wag:.3f} vs {plain_wag:.3f}")

    # 同伴：强度衰减 + 延迟起逃，且都不超过主鱼
    powers = [f.flee_power for f in w.fishes]
    delays = [f.flee_at - _T0 for f in w.fishes]
    check("主鱼强度为 1", powers[0] == 1.0)
    check("同伴强度均小于主鱼", all(0 < p < 1.0 for p in powers[1:]),
          str([round(p, 3) for p in powers]))
    check("同伴延迟 0.05~0.35s",
          all(0.05 <= d <= 0.35 for d in delays[1:]),
          str([round(d, 3) for d in delays]))
    check("同伴确有惊散", any(w.is_fleeing(i, _T0 + 0.6) for i in range(1, 5)))

    # 重复惊动：以最后一次为准
    w.set_time(_T0 + 1.0)
    p1 = w.fish_pose(3)
    hit2 = w.startle_at(p1.x, p1.y)
    check("重复惊动命中新目标", hit2 == 3, f"hit={hit2}")
    check("新目标强度重置为 1", w.fishes[3].flee_power == 1.0)
    check("新目标起逃时刻 = 当前时刻",
          abs(w.fishes[3].flee_at - (_T0 + 1.0)) < 1e-9)

    w.reset_fishes()
    check("reset 清空全部逃窜状态",
          all(f.flee_power == 0.0 for f in w.fishes))
    check("reset 清空水纹", w.splash_count() == 0)
    check("reset 后位移归零",
          math.hypot(w.fish_pose(0, _T0 + 0.4).x - base[0.40].x,
                     w.fish_pose(0, _T0 + 0.4).y - base[0.40].y) < 1e-9)


def group_time(w: InkPondWidget) -> None:
    """组 4：时间纯函数、暂停、水纹。"""
    _group("4 时间纯函数 / 水纹")

    w.reset_fishes()
    w.set_time(_T0)
    p = w.fish_pose(0)
    w.startle_at(p.x, p.y)
    a = w.fish_pose(0, _T0 + 0.7)
    ref = (a.x, a.y, a.heading, a.wag, a.flee_weight)

    w.set_time(40.0)
    w.set_time(2.0)
    w.set_time(_T0)
    b = w.fish_pose(0, _T0 + 0.7)
    check("任意跳转顺序结果一致",
          (b.x, b.y, b.heading, b.wag, b.flee_weight) == ref)

    check("水纹已生成", w.splash_count() == 1)
    check("+0.7s 仍在逃窜", w.is_fleeing(0, _T0 + 0.7))
    check("+3.0s 已结束", not w.is_fleeing(0, _T0 + 3.0))
    check("延迟同伴在 t0 尚未起逃",
          not w.is_fleeing(1, _T0 + 0.01))

    # 暂停：跑几帧 timer，时间不推进、位姿不动
    w.set_paused(True)
    frozen = w.fish_pose(0, w.time() + 0.5)
    for _ in range(3):
        w._tick()
    check("暂停时 _t 不推进", abs(w.time() - _T0) < 1e-6,
          f"t={w.time():.6f}")
    now = w.fish_pose(0, w.time() + 0.5)
    check("暂停时位姿冻结",
          (now.x, now.y, now.heading, now.wag) ==
          (frozen.x, frozen.y, frozen.heading, frozen.wag))
    w.set_paused(False)

    # 水纹数量上限 + 过期清理（直接驱动一次 tick，避免等真实 1.6s）
    p = w.fish_pose(0)
    for k in range(w.SPLASH_MAX + 4):
        w._splashes.append((p.x, p.y, float(k)))
        del w._splashes[:-w.SPLASH_MAX]
    check("水纹数量有上限", w.splash_count() <= w.SPLASH_MAX,
          str(w.splash_count()))
    w.set_time(_T0 + w.SPLASH_DURATION + 1.0)
    w._tick()
    check("过期水纹自动清理", w.splash_count() == 0,
          str(w.splash_count()))
    w.reset_fishes()


def group_mouse(w: InkPondWidget) -> None:
    """组 5：真实鼠标事件链与交互开关。"""
    _group("5 真实鼠标链路 / 开关")

    w.reset_fishes()
    w.set_time(_T0)
    p = w.fish_pose(0)
    wp = w._to_widget(p.x, p.y)
    pt = QPoint(int(wp.x()), int(wp.y()))

    before = w.startle_count()
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, pt)
    check("QTest 左键点鱼身触发惊动",
          w.startle_count() == before + 1,
          f"{before} -> {w.startle_count()}")
    check("点击后鱼确实在逃窜", w.fishes[0].flee_power == 1.0)

    QTest.mouseClick(w, Qt.RightButton, Qt.NoModifier, pt)
    check("右键不触发", w.startle_count() == before + 1)

    blank = QPoint(5, 5)
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, blank)
    check("点空白不触发", w.startle_count() == before + 1)

    w.set_interactive(False)
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, pt)
    check("关闭交互后不触发", w.startle_count() == before + 1)
    w.set_interactive(True)
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, pt)
    check("重新打开后可触发", w.startle_count() == before + 2)

    QTest.mouseMove(w, pt)
    check("悬停鱼身显示手型光标",
          w.cursor().shape() == Qt.PointingHandCursor,
          str(w.cursor().shape()))
    QTest.mouseMove(w, blank)
    check("移开后恢复默认光标",
          w.cursor().shape() != Qt.PointingHandCursor,
          str(w.cursor().shape()))
    w.reset_fishes()


def group_render(w: InkPondWidget) -> None:
    """组 6：受惊帧确实变了，复位后又能完全一致。"""
    _group("6 渲染差异 / 复位")

    w.reset_fishes()
    w.set_time(_T0)
    base = _frame(w)
    p = w.fish_pose(0)
    w.startle_at(p.x, p.y)
    w.set_time(_T0 + 0.4)
    fled = _frame(w)
    check("受惊帧与基线帧不同", base != fled)
    check("受惊帧尺寸不变", len(base) == len(fled))

    w.reset_fishes()
    w.set_time(_T0)
    check("复位后逐像素回到基线", _frame(w) == base)


def group_scene(w: InkPondWidget) -> None:
    """组 7（构图）：新增小荷叶、往返跳跃的青蛙、水波涟漪。"""
    _group("7 荷叶 / 青蛙 / 水波")

    # -- 构图 -----------------------------------------------------------
    check("荷叶 4 片", len(w.leaves) == 4, str(len(w.leaves)))
    big, small = w.leaves[0], w.leaves[1]
    check("小荷叶在左侧大荷叶附近",
          small.x < big.x and small.rx < big.rx * 0.6
          and abs(small.x - big.x) < 200 and abs(small.y - big.y) < 200,
          f"big=({big.x},{big.y}) small=({small.x},{small.y})")
    check("小荷叶墨色介于浓淡之间",
          w.leaves[-1].ink < small.ink < big.ink,
          f"{w.leaves[-1].ink}/{small.ink}/{big.ink}")
    check("两片荷叶之间补了氛围涟漪源", len(w.ripples) == 5,
          str(len(w.ripples)))
    check("两处叶缘露珠", len(w.dew_drops) == 2, str(len(w.dew_drops)))

    # -- 青蛙：阶段位姿 -------------------------------------------------
    p = w.FROG_PERIOD
    a, b = w.FROG_A, w.FROG_B
    crouch = w.frog_pose(0.05 * p)
    hop = w.frog_pose(0.20 * p)
    rest_small = w.frog_pose(0.45 * p)
    hop_back = w.frog_pose(0.68 * p)
    rest_big = w.frog_pose(0.92 * p)

    check("蓄力时蹲在大荷叶",
          math.hypot(crouch.x - a[0], crouch.y - a[1]) < 1e-6
          and not crouch.on_small and crouch.squash > 0)
    check("去程腾空且高于两端",
          hop.airborne > 0.9 and hop.leg > 0.5
          and min(a[0], b[0]) <= hop.x <= max(a[0], b[0])
          and hop.y < min(a[1], b[1]) - 30,
          f"pos=({hop.x:.1f},{hop.y:.1f}) air={hop.airborne:.2f}")
    check("停在小荷叶",
          math.hypot(rest_small.x - b[0], rest_small.y - b[1]) < 1e-6
          and rest_small.on_small and rest_small.airborne == 0.0)
    check("回程也腾空",
          hop_back.airborne > 0.9
          and min(a[0], b[0]) <= hop_back.x <= max(a[0], b[0])
          and hop_back.y < min(a[1], b[1]) - 30)
    check("最终回到大荷叶",
          math.hypot(rest_big.x - a[0], rest_big.y - a[1]) < 1e-6
          and not rest_big.on_small)
    gap = abs((hop.heading - hop_back.heading + 180.0) % 360.0 - 180.0)
    check("去 / 回朝向基本相反", gap > 100.0, f"gap={gap:.1f}")

    fields = lambda q: (q.x, q.y, q.heading, q.leg, q.airborne, q.squash)
    later = w.frog_pose(0.20 * p + 3 * p)
    check("青蛙动画按周期严格复现",
          all(abs(x - y) < 1e-9 for x, y in zip(fields(hop), fields(later)))
          and hop.on_small == later.on_small)

    # -- 涟漪事件：解析、零状态 -----------------------------------------
    land_small = 0.30 * p + 0.05
    land_big = 0.78 * p + 0.05
    ev_small = w.frog_wave_events(land_small)
    ev_big = w.frog_wave_events(land_big)
    check("落到小荷叶激起涟漪",
          any(abs(t0 - 0.30 * p) < 1e-6 for _x, _y, t0, _s in ev_small),
          str(len(ev_small)))
    check("落回大荷叶激起涟漪",
          any(abs(t0 - 0.78 * p) < 1e-6 for _x, _y, t0, _s in ev_big),
          str(len(ev_big)))
    check("露珠滴落也有涟漪",
          any(abs(x - 372.0) < 1e-6 and abs(y - 528.0) < 1e-6
              for x, y, _t0, _s in w.frog_wave_events(1.11))
          and any(abs(x - 210.0) < 1e-6 and abs(y - 614.0) < 1e-6
                  for x, y, _t0, _s in w.frog_wave_events(4.20)))
    check("事件涟漪是时间的纯函数",
          w.frog_wave_events(land_small) == ev_small)

    # -- 水波环：真的画出像素，且带扰动 ---------------------------------
    def ring(wobble: float) -> QImage:
        img = QImage(200, 120, QImage.Format_ARGB32)
        img.fill(QColor(*PAPER))
        painter = QPainter(img)
        InkPondWidget._wave_ring(painter, 100, 60, 62, 210,
                                 flatten=0.25, width=1.5, wobble=wobble)
        painter.end()
        return img

    plain, wobbled = ring(0.0), ring(0.05)
    dark = sum(1 for y in range(120) for x in range(200)
               if wobbled.pixelColor(x, y).red() < 200)
    check("水波环确实画出墨线", dark > 100, f"dark px={dark}")
    check("水波环带不规则扰动",
          bytes(plain.constBits()) != bytes(wobbled.constBits()))

    # -- 渲染：动起来、可复现、与点击水纹共存 ---------------------------
    w.reset_fishes()
    w.set_time(0.0)
    f0 = _frame(w)
    w.set_time(1.4)
    check("青蛙在动：不同时刻帧不同", _frame(w) != f0)
    w.set_time(12.0)
    base12 = _frame(w)
    w.set_time(30.0)
    w.set_time(2.0)
    w.set_time(12.0)
    check("任意跳转后同一帧逐像素相同", _frame(w) == base12)
    w.set_time(12.4)
    check("水波 / 鱼 / 蛙随时间变化", _frame(w) != base12)

    w.set_time(12.0)
    w.reset_fishes()
    no_click = _frame(w)
    fp = w.fish_pose(0)
    w.startle_at(fp.x, fp.y)
    check("点击水纹与青蛙涟漪共存",
          w.splash_count() == 1 and len(w.frog_wave_events(12.0)) > 0,
          f"splash={w.splash_count()} events={len(w.frog_wave_events(12.0))}")
    check("点击后画面确实变化", _frame(w) != no_click)

    w.reset_fishes()
    w.set_time(3.1)
    w.set_paused(True)
    frozen, frozen_frame = fields(w.frog_pose()), _frame(w)
    for _ in range(3):
        w._tick()
    check("暂停时青蛙位姿冻结", fields(w.frog_pose()) == frozen)
    check("暂停时整帧不变", _frame(w) == frozen_frame)
    w.set_paused(False)
    w.reset_fishes()
    w.set_time(_T0)


def group_runtime() -> None:
    """组 8：真实窗口里，点击穿透卡片到达背景控件。"""
    _group("8 运行态集成 / 点击穿透")

    from App_PopPick_V2.pop_pick_entry import (  # noqa: E402
        PopPickWindow, resolve_page_file,
    )

    win = PopPickWindow(scene_path=resolve_page_file("page_9"), hmi_demo=True)
    win.resize(1400, 900)
    win.show()
    _wait(700)          # 等布局收敛 + BackgroundFitter 铺满视口
    try:
        # 必须从「背景」图元的 proxy 取控件：门禁自己还开了一个演示控件，
        # 用 QApplication.allWidgets() 遍历会先拿到它。
        eid = win.runtime.background.element.item_id()
        proxy = win.stage.widgets.proxy_of(eid)
        pond = proxy.widget() if proxy is not None else None
        check("背景 proxy 挂的是 InkPondWidget",
              isinstance(pond, InkPondWidget), type(pond).__name__)
        if pond is None:
            return

        pond.set_time(_T0)
        pose = pond.fish_pose(0)
        # 逻辑画布 → 控件像素 → 场景 → 视口，四层坐标都要走对
        wp = pond._to_widget(pose.x, pose.y)
        vp_pt = win.scene.mapFromScene(proxy.mapToScene(wp))
        vp = win.scene.viewport()
        check("鱼心落在视口内",
              0 <= vp_pt.x() < vp.width() and 0 <= vp_pt.y() < vp.height(),
              f"({vp_pt.x()},{vp_pt.y()}) vp={vp.width()}x{vp.height()}")

        before = pond.startle_count()
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, vp_pt)
        _wait(40)
        check("视口点击穿透并惊动鱼",
              pond.startle_count() == before + 1,
              f"{before} -> {pond.startle_count()}")
        check("被点中的鱼开始逃窜", pond.fishes[0].flee_power == 1.0,
              str(pond.fishes[0].flee_power))
    finally:
        win.close()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    w = InkPondWidget(fps=30)
    w.resize(1200, 800)
    # QTest.mouseMove 只对可见控件投递 MouseMove；show() 之后 hover 链路才真实。
    w.show()
    try:
        group_default(w)
        group_hit(w)
        group_flee(w)
        group_time(w)
        group_mouse(w)
        group_render(w)
        group_scene(w)
        group_runtime()
    except Exception:  # noqa: BLE001 - 门禁要把异常变成失败项
        traceback.print_exc()
        check("门禁执行过程无异常", False, "见上方 traceback")
    finally:
        w.reset_fishes()
        w.close()
    return _report()


if __name__ == "__main__":
    sys.exit(main())
