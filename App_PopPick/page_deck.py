"""页面卡片堆叠：点左侧页签，与右侧「当前页」互换；双击背景收起左侧。

设计原型见 ``Designer/Core/data.json/datas/design/pages/page_9.json``：
左侧几张卡以左下角为支点扇形展开，右侧一张是「当前页」槽位。

本模块只负责四件事，不关心窗口/工具栏：

1. **读位姿**：每张卡的场景中心点 + 旋转角 + Z 值；
2. **命中测试**：按 Z 从高到低找最上面那张，局部矩形判断（旋转卡片不能
   直接拿包围盒判，扇形叠在一起时包围盒会互相咬住）；
3. **交换动画**：两张卡同时沿弧线平移并旋转，结束时互换 Z 值；
4. **收拢 / 展开**：左侧扇形叠成一摞（最前面那张原地不动），再散开回扇形。

交换和收拢共用一套动画内核（:meth:`PageDeck._start_motion`）：都是"把若干
张卡从当前位姿插值到目标位姿"，区别只在参与卡数、要不要走弧线、收尾时
做什么（交换要换 Z；收拢只要落位）。

坐标约定：插值全部在**视图（屏幕）坐标系**里做，再转回场景坐标。场景用的是
AGV 的 90° 轴映射（``sceneToView`` 交换 x/y），直接在场景坐标里插值，弧线的
弯向在屏幕上会是歪的。

位姿的落地方式（见 :meth:`PageDeck._apply_pose`）分两步，缺一不可：

- 绕图元自身 ``m_origin`` 旋转：扇形展开本来就是绕共同支点转出来的，这一步
  会顺带把中心点带出一段弧；
- 再把中心点平移回插值出来的位置：旋转后中心已经偏移，不补这一步终点会跑偏。

放大后卡顿的两个来源（见 :meth:`PageDeck._set_fast_render`）
--------------------------------------------------------------
画面放大时动画会明显掉帧，原因不在动画本身（两帧间只改了两个角度和位置），
而在**重绘**。实测（离屏软件渲染、1280×820、520ms 动画）：

1. **每帧重渲染真实控件**。proxy 一带旋转，``QGraphicsProxyWidget::paint``
   就得把控件从头画一遍；更糟的是父窗口一脏，该区域下**所有**承载视图都被
   重画——6 张卡里只有 2 张在动，另外 4 张一帧不落地重新渲染。2~3 倍缩放时
   每帧 60~75ms，只剩 9~13 帧。对策：动画期间把控件烘成位图快照
   （``EmbeddedWidgetLayer.set_motion_cache``）。
2. **占位框照画**。``rect_element.paint`` 那张旋转矩形 100% 被真实控件盖住，
   但每帧仍要做一次抗锯齿填充 + 描边，放大后一张卡就是几千像素见方。对策：
   动画期间只描边、不填底（``set_widget_fast_paint``）。**边框不能省**，卡片的
   轮廓全靠它，省掉后页面糊成一片白——那就是"画面失真"。

两项叠加后，1.5~4 倍缩放下约 26~31 帧（上限 33 帧/60fps），改动前是 11~14 帧。
两者都只在动画期间打开、动画结束立刻关掉——静止画面必须回到矢量渲染 +
完整占位框，否则放大后文字发虚。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPointF,
    QRectF,
    QVariantAnimation,
    Signal,
)


def normalize_angle(angle: float) -> float:
    """把角度规范到 [0, 360)。

    浮点取模在 -1e-14 这类极小负数上会返回 360.0（而不是 0），角度账本里就会
    出现"转完停在 360°"这种看着别扭、比较起来又要额外判断的值，这里一起抹平。
    """
    value = angle % 360.0
    if value < 1e-9 or 360.0 - value < 1e-9:
        return 0.0
    return value


def shortest_delta(start: float, end: float) -> float:
    """从 ``start`` 转到 ``end`` 的最短角度差（-180, 180]。

    直接相减会在跨越 0/360 时绕远路（例如 350° → 10° 会倒转 340°）。
    """
    return (normalize_angle(end) - normalize_angle(start) + 180.0) % 360.0 - 180.0


@dataclass(frozen=True)
class CardPose:
    """一张卡的位姿：场景中心点 + 旋转角（度）。"""

    center: QPointF
    angle: float

    def __str__(self) -> str:  # 便于日志排查
        return f"({self.center.x():.1f}, {self.center.y():.1f}) @ {self.angle:.1f}°"


@dataclass(frozen=True)
class _Motion:
    """一次动画里单张卡的起止位姿。"""

    card: object
    start: CardPose
    end: CardPose


class PageDeck(QObject):
    """卡片堆叠的交互与动画。

    :param scene: ``QuadTreeScene``（只用到 ``sceneToView`` / ``viewToScene`` /
        ``update`` 这几个接口）；
    :param cards: 卡片图元（``widget_element``）。至少两张：一张槽位 + 若干堆叠；
    :param duration_ms: 单次交换时长，测试里可以调小。
    """

    # (飞入槽位的卡名, 从槽位退回堆叠的卡名)
    swap_started = Signal(str, str)
    swap_finished = Signal(str, str)
    busy_changed = Signal(bool)
    # True = 已收拢（左侧叠成一摞）
    fold_changed = Signal(bool)

    DEFAULT_DURATION_MS = 520
    # 收拢比交换略快：动作简单（只有旋转归零 + 平移），拖太久显得拖沓
    FOLD_DURATION_MS = 420
    # 弧线高度 = 屏幕位移 × ARC_RATIO，并限制上限，避免大跨度时甩得太夸张
    ARC_RATIO = 0.22
    MAX_ARC_PX = 140.0
    ANGLE_EPS = 1e-4
    CENTER_EPS = 1e-3

    def __init__(
        self,
        scene,
        cards: Sequence,
        parent: Optional[QObject] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        super().__init__(parent)
        cards = list(cards)
        if len(cards) < 2:
            raise ValueError("页面堆叠至少需要两张卡片（一张槽位 + 一张堆叠）")
        self._scene = scene
        self._cards: List = cards
        self._duration_ms = int(duration_ms or self.DEFAULT_DURATION_MS)

        # Z 值在设计文件里可能全是 1（叠放顺序靠插入顺序），这里落成显式的
        # 1..N，交换才有可互换的东西，也避免相等 Z 下排序依赖插入顺序。
        self._normalise_z()

        self._initial_poses: Dict[object, CardPose] = {
            card: self.pose_of(card) for card in self._cards
        }
        self._initial_z: Dict[object, int] = {
            card: card.zValue() for card in self._cards
        }

        self._slot = self._detect_slot()
        self._pair: Optional[tuple] = None
        self._swap_z: tuple = ()
        self._arc_len = 0.0
        self._anim: Optional[QVariantAnimation] = None

        # 通用动画内核的状态（交换 / 收拢 / 展开共用）
        self._motion: List[_Motion] = []
        self._motion_kind = ""

        # 收拢状态：_folded 是当前状态，_fold_saved 是展开时要还原的位姿。
        # 存"收拢前那一刻"的位姿而不是设计初始位姿——交换过之后谁在哪儿已经
        # 变了，用初始值展开会把卡片弹到别人的位置上。
        self._folded = False
        self._fold_saved: Dict[object, CardPose] = {}

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def cards(self) -> List:
        return list(self._cards)

    def slot_card(self):
        """右侧「当前页」槽位上的卡。"""
        return self._slot

    def stack_cards(self) -> List:
        """左侧堆叠里的卡，按 Z 从高到低（最上面那张在前）。"""
        others = [card for card in self._cards if card is not self._slot]
        return sorted(others, key=lambda card: card.zValue(), reverse=True)

    def is_busy(self) -> bool:
        return self._anim is not None

    def pose_of(self, card) -> CardPose:
        """读取卡片当前位姿。

        角度取自 ``get_angle()``（图元的记账角度），与 :meth:`_apply_pose`
        推进时用的是同一个来源，避免两个角度源各走各的、越动越偏。
        """
        return CardPose(QPointF(card.get_scene_center_pos()), float(card.get_angle()))

    # ------------------------------------------------------------------
    # 命中测试
    # ------------------------------------------------------------------
    def card_at(self, scene_pos: QPointF):
        """返回该场景点上最上层的卡片，空白处返回 ``None``。"""
        if scene_pos is None:
            return None
        for card in sorted(self._cards, key=lambda item: item.zValue(), reverse=True):
            if not card.get_visibility():
                continue
            if self._contains(card, scene_pos):
                return card
        return None

    @staticmethod
    def _local_rect(card) -> QRectF:
        """图元局部坐标系下的矩形（中心是 ``_center_pos``，不是 (0,0)）。"""
        size = card.getSize()
        if size is None:
            return QRectF()
        center = card.get_center_pos() or QPointF(0.0, 0.0)
        return QRectF(
            center.x() - size.width() / 2.0,
            center.y() - size.height() / 2.0,
            size.width(),
            size.height(),
        )

    def _contains(self, card, scene_pos: QPointF) -> bool:
        rect = self._local_rect(card)
        if rect.isNull():
            return False
        return rect.contains(card.mapFromScene(scene_pos))

    # ------------------------------------------------------------------
    # 交换
    # ------------------------------------------------------------------
    def swap_with_slot(self, card) -> bool:
        """把 ``card`` 与槽位上的卡互换。忙 / 点的是槽位卡时返回 ``False``。"""
        if self._anim is not None:
            return False
        # 收拢状态下左侧卡片已经被收进左边缘，位置不再对应任何"页签"，
        # 这时允许交换会把卡片从屏幕外抽出来，画面很突兀。
        if self._folded:
            return False
        if card is None or card is self._slot or card not in self._cards:
            return False

        entering = card                 # 从堆叠飞进槽位
        leaving = self._slot            # 从槽位退回堆叠
        start_entering = self.pose_of(entering)
        start_leaving = self.pose_of(leaving)

        self._pair = (entering, leaving)
        # 互换前的 Z：进场卡拿走槽位的 Z，退场卡接过堆叠里那张的 Z
        self._swap_z = (entering.zValue(), leaving.zValue())

        # 动画期间两张卡都抬到最上层（退场的更高一层）：否则从扇形中间
        # 抽出来的那张会被同层卡片盖住，看起来像"卡在下面穿过去了"。
        self._lift_top(leaving, entering)

        self.swap_started.emit(entering.get_name(), leaving.get_name())
        # 动画期间所有卡片改用位图缓存渲染控件。只给要动的两张开是不够的：
        # 父窗口一脏，该区域下所有承载视图都会被重画，没开缓存的静止卡每帧
        # 仍要把真实控件从头渲染一遍——放大后这正是卡顿的主因。见 _set_fast_render。
        return self._start_motion(
            (
                _Motion(entering, start_entering, start_leaving),
                _Motion(leaving, start_leaving, start_entering),
            ),
            kind="swap",
            duration_ms=self._duration_ms,
            arc_len=self._view_distance(start_entering.center, start_leaving.center),
        )

    def reset(self) -> None:
        """回到设计文件的初始布局（位姿 + Z 值）。"""
        self._cancel_animation()
        was_folded = self._folded
        self._folded = False
        self._fold_saved = {}
        for card in self._cards:
            pose = self._initial_poses[card]
            self._apply_pose(card, pose.center, pose.angle)
            card.set_zValue(self._initial_z[card])
        self._slot = self._detect_slot()
        self._restack()
        self._scene.update()
        if was_folded:
            self.fold_changed.emit(False)

    def stop(self) -> None:
        """中断进行中的动画但不还原布局（窗口关闭时用）。"""
        self._cancel_animation()

    # ------------------------------------------------------------------
    # 收拢 / 展开
    # ------------------------------------------------------------------
    def is_folded(self) -> bool:
        return self._folded

    def fold(self, duration_ms: Optional[int] = None) -> bool:
        """把左侧堆叠收拢成一摞。忙 / 已收拢时返回 ``False``。

        收拢形态：**最前面那张（Z 最高）原地不动**，其余卡旋转角与中心点都对齐
        到它，叠成整齐一摞。最前那张是这摞的"封面"，也是展开时唯一的把手——
        它要是一起滑走，用户就看不到自己刚收起来的那一摞了。
        """
        if self._anim is not None or self._folded:
            return False
        stack = self.stack_cards()
        if len(stack) < 2:
            return False

        anchor = self.pose_of(stack[0])
        movers = stack[1:]
        # 只记要动的这几张：展开时最前那张本来就没挪，不需要"还原"
        self._fold_saved = {card: self.pose_of(card) for card in movers}
        self._folded = True
        return self._start_motion(
            [_Motion(card, self._fold_saved[card], anchor) for card in movers],
            kind="fold",
            duration_ms=int(duration_ms or self.FOLD_DURATION_MS),
        )

    def unfold(
        self, duration_ms: Optional[int] = None, *, immediate: bool = False
    ) -> bool:
        """展开回收拢前的扇形。``immediate=True`` 时不做动画直接落位。"""
        if self._anim is not None or not self._folded:
            return False
        saved = dict(self._fold_saved)
        self._folded = False

        if immediate or not saved:
            for card, pose in saved.items():
                self._apply_pose(card, pose.center, pose.angle)
            self._fold_saved = {}
            self._restack()
            self._scene.update()
            self.fold_changed.emit(False)
            return True

        return self._start_motion(
            [_Motion(card, self.pose_of(card), pose) for card, pose in saved.items()],
            kind="unfold",
            duration_ms=int(duration_ms or self.FOLD_DURATION_MS),
        )

    def toggle_fold(self) -> bool:
        return self.unfold() if self._folded else self.fold()

    # ------------------------------------------------------------------
    # 动画内核
    # ------------------------------------------------------------------
    def _start_motion(
        self,
        motions: Sequence[_Motion],
        *,
        kind: str,
        duration_ms: int,
        arc_len: float = 0.0,
    ) -> bool:
        """跑一次"若干张卡从 A 位姿到 B 位姿"的动画。

        交换（2 张、带弧线、收尾换 Z）和收拢/展开（N 张、直线、收尾只落位）
        只是在参数与收尾动作上不同，插值、快速渲染开关、busy 信号全部共用。
        """
        motions = list(motions)
        if not motions or self._anim is not None:
            return False

        self._motion = motions
        self._motion_kind = kind
        self._arc_len = float(arc_len)
        # 动画期间全量卡片改用位图快照 + 占位框只描边（放大后不卡的关键）
        self._set_fast_render(True)

        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(int(duration_ms))
        # InOutCubic：起步和收尾都软，中段快，像被人抽走又放下
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.valueChanged.connect(self._on_progress)
        anim.finished.connect(self._on_finished)
        self._anim = anim

        self.busy_changed.emit(True)
        anim.start()
        return True

    # ------------------------------------------------------------------
    # 动画回调
    # ------------------------------------------------------------------
    def _on_progress(self, value) -> None:
        if not self._motion:
            return
        t = float(value)
        for item in self._motion:
            self._apply_pose(
                item.card,
                self._interpolate(item.start.center, item.end.center, t),
                self._lerp_angle(item.start.angle, item.end.angle, t),
            )
        # 整窗重绘：试过按动到的卡片的并集做局部 update()，实测帧数没有提升
        # （真正的开销在真实控件旋转时的重绘），就不引入这层复杂度了。
        self._scene.update()

    def _on_finished(self) -> None:
        if not self._motion:
            return
        # 收尾对齐到目标位姿：插值在 t=1 时理论值就是目标，但浮点误差会让
        # 卡片停在差几分之一度的位置，与记录值对不上（再次交换会越差越多）。
        for item in self._motion:
            self._apply_pose(item.card, item.end.center, item.end.angle)

        kind = self._motion_kind
        self._motion = []
        self._motion_kind = ""
        swapped: Optional[tuple] = None

        if kind == "swap" and self._pair is not None:
            entering, leaving = self._pair
            z_entering, z_leaving = self._swap_z
            leaving.set_zValue(z_entering)
            entering.set_zValue(z_leaving)
            self._slot = entering
            self._pair = None
            swapped = (entering.get_name(), leaving.get_name())

        # 先换回矢量渲染再重排：收尾这一帧要把卡片按最终角度重画成清晰的
        self._set_fast_render(False)
        self._restack()
        self._scene.update()
        self._dispose_animation()
        self.busy_changed.emit(False)

        if swapped is not None:
            self.swap_finished.emit(*swapped)
        elif kind in ("fold", "unfold"):
            self.fold_changed.emit(self._folded)

    # ------------------------------------------------------------------
    # 位姿落地
    # ------------------------------------------------------------------
    def _apply_pose(self, card, center: QPointF, angle: float) -> None:
        delta = shortest_delta(card.get_angle(), angle)
        if abs(delta) > self.ANGLE_EPS:
            # 绕自身 m_origin 转，中心点会跟着画一段弧（扇形就是这么展开的）
            card.setRotation(delta)
        # 角度账本始终对齐到目标值：旋转量在 EPS 以内时也要落账，否则收尾
        # 会留下 359.9999 这类值，下一次交换的最短路径就会算错方向。
        card.set_angle(normalize_angle(angle))

        moved = False
        shift = center - card.get_scene_center_pos()
        if abs(shift.x()) > self.CENTER_EPS or abs(shift.y()) > self.CENTER_EPS:
            # setPos 对 widget_element 会顺带同步承载控件的几何，不必再补一次
            card.setPos(card.pos() + shift)
            moved = True

        # 包围盒用于裁剪与命中测试，动画每帧都得刷新，否则会被判定在视口外
        card.update_boundingRect()
        if not moved:
            # 纯旋转（中心恰好没动）时 setPos 没被调用，控件几何得手动同步
            card.sync_widget_geometry()

    def _interpolate(self, start: QPointF, end: QPointF, t: float) -> QPointF:
        """屏幕坐标下走直线 + 垂直方向的一段正弦弧，再转回场景坐标。"""
        view_start = self._scene.sceneToView(start)
        view_end = self._scene.sceneToView(end)
        point = view_start + (view_end - view_start) * t
        if self._arc_len > 1.0:
            arc = min(self.MAX_ARC_PX, self._arc_len * self.ARC_RATIO)
            # 屏幕 y 向下为正，取负号 → 两张卡都往上鼓，不会互相穿过去
            point = QPointF(point.x(), point.y() - arc * math.sin(math.pi * t))
        return self._scene.viewToScene(point)

    def _view_distance(self, start: QPointF, end: QPointF) -> float:
        view_start = self._scene.sceneToView(start)
        view_end = self._scene.sceneToView(end)
        return math.hypot(view_end.x() - view_start.x(), view_end.y() - view_start.y())

    @staticmethod
    def _lerp_angle(start: float, end: float, t: float) -> float:
        return normalize_angle(start + shortest_delta(start, end) * t)

    # ------------------------------------------------------------------
    # 槽位判定 / Z 值 / 层级
    # ------------------------------------------------------------------
    def _detect_slot(self):
        """找出右侧「当前页」槽位上的卡：屏幕坐标最靠右的那张。

        设计上左侧是一把扇形叠放（彼此叠压、共同支点），右侧单独一张。用
        "最右"判定比按名字匹配稳：改名、增删卡都不影响；交换后原来那张仍在
        最右，结构不变。
        """

        def view_x(card) -> float:
            return self._scene.sceneToView(card.get_scene_center_pos()).x()

        return max(self._cards, key=view_x)

    def _normalise_z(self) -> None:
        """按当前绘制顺序把卡片 Z 落成 base+1..base+N（避免与其它图元撞值）。"""
        manager = getattr(self._scene, "scene_manager", None)
        ordered = list(getattr(manager, "m_sorted_items", None) or self._cards)
        # m_sorted_items 是「先画的在前」，相等的 Z 由稳定排序保留插入顺序，
        # 也就是设计文件里的叠放顺序，直接沿用即可。
        ordered = [item for item in ordered if item in self._cards]
        for card in self._cards:            # 兜底：未进 manager 的卡追加在后
            if card not in ordered:
                ordered.append(card)
        base = max(
            (item.zValue() for item in (getattr(manager, "m_sorted_items", None) or [])
             if item not in self._cards),
            default=0,
        )
        for index, card in enumerate(ordered, start=1):
            card.set_zValue(base + index)

    def _lift_top(self, bottom, top) -> None:
        cards = set(self._cards)
        base = max(
            (item.zValue() for item in self._all_items() if item not in cards),
            default=0,
        )
        highest = max((card.zValue() for card in self._cards), default=base)
        bottom.set_zValue(max(base, highest) + 1)
        top.set_zValue(max(base, highest) + 2)
        # 只抬这两张的承载视图，不走全量 _restack()：全量会对 6 个上千像素的
        # 视图逐个 raise_()，每次 raise_ 都要重绘被遮挡区域，实测动画起步会被
        # 拖慢 100ms 以上（表现成"点下去先卡一下再动"）。完整重排留到收尾时
        # 做一次，那时动画已经停住，不会影响手感。
        for card in (bottom, top):
            raiser = getattr(card, "raise_widget_view", None)
            if callable(raiser):
                raiser()

    def _all_items(self) -> List:
        manager = getattr(self._scene, "scene_manager", None)
        return list(getattr(manager, "m_sorted_items", None) or [])

    def _restack(self) -> None:
        """Z 变了之后重排承载视图。

        场景自绘部分按 ``m_sorted_items`` 画，但卡片的实体是每张卡一个透明
        ``QGraphicsView`` 子窗口，叠放顺序靠 ``raise_()``；只改 zValue 不
        restack，控件层会继续停在旧顺序，看起来就是"Z 值换了但画面没变"。
        """
        sync = getattr(self._scene, "_sync_embedded_widgets_geometry", None)
        if callable(sync):
            sync()

    def _set_fast_render(self, active: bool) -> None:
        """开关动画期间的快速渲染（两件事一起做，见各图元方法的说明）。

        1. ``set_motion_cache``：控件改用位图快照，不再逐帧重渲染真实控件；
        2. ``set_widget_fast_paint``：占位框只描边、不填底（边框必须保留，
           否则卡片轮廓消失、页面糊成一片白，看起来就是"画面失真"）。

        两件事都只在动画期间打开、结束立刻关掉——静止画面必须回到"矢量渲染
        + 完整占位框"，否则放大后文字会发虚。
        """
        for card in self._cards:
            for name in ("set_motion_cache", "set_widget_fast_paint"):
                setter = getattr(card, name, None)
                if callable(setter):
                    setter(active)

    # ------------------------------------------------------------------
    # 动画对象生命周期
    # ------------------------------------------------------------------
    def _cancel_animation(self) -> None:
        if self._anim is None:
            return
        # 中断时同样要把位图缓存关掉，否则画面会一直停在"发虚"的那一版
        self._set_fast_render(False)
        kind = self._motion_kind

        if kind in ("fold", "unfold"):
            # 收拢/展开被打断在半路，卡片会停在"既没收进去也没散开"的位置，
            # 状态和画面就对不上。直接落到目标位姿（Z 和层级本来就没变）。
            for item in self._motion:
                self._apply_pose(item.card, item.end.center, item.end.angle)
            self._restack()
            self._scene.update()

        self._motion = []
        self._motion_kind = ""
        self._pair = None
        self._dispose_animation()
        self.busy_changed.emit(False)
        if kind in ("fold", "unfold"):
            self.fold_changed.emit(self._folded)

    def _dispose_animation(self) -> None:
        anim = self._anim
        self._anim = None
        if anim is None:
            return
        for signal, slot in (
            (anim.valueChanged, self._on_progress),
            (anim.finished, self._on_finished),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        anim.stop()
        anim.deleteLater()


def find_page_cards(items: Sequence) -> List:
    """从场景图元里挑出页面卡片（``widget_element``），保持绘制顺序。"""
    from Designer.Core.elements import widget_element

    return [item for item in items if isinstance(item, widget_element)]
