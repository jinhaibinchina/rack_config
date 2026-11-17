"""test_fixture 运行态装配：普通图元 + widget 图元共用一套 RuntimeStage。

装配顺序与职责
--------------
``FixtureRuntime.load()`` 里固定：

1. ``RuntimeStage.load()`` —— 装载 JSON、切运行态、建 6 个控件 proxy、取景；
2. ``CleanVisuals.capture()`` —— 给每个图元的 ``_page`` 留一份快照；
3. ``derive_geometry()`` —— 从导轨 / 三光电 / 滑块现场推导行程锚点；
4. ``_install_controls()`` —— 放大 spinbox 量程、灌初值、接回写；
5. ``stage.fit()`` —— ``sceneRect=0`` 时框架自动回退到内容包围盒。

「电机监控窗口」widget 图元在 ``stage.load()`` **之前**用
``stage.set_mapping({name: ServoPanelProvider()})`` 注入面板工厂，
``WidgetHost`` 负责造 proxy / 对齐 / 换页重建；面板造好时由
``controlCreated`` 回调接上 ``commandRequested``，不认识的协议一概不碰。
想换挂外部窗口，给 ``FixtureRuntime(panel_provider=...)`` 传另一个
``ControlProvider`` / QWidget / 工厂即可。

数据链路：``DataSource.valuesChanged`` → ``TagBus.update_many`` → 合流
``valuesChanged`` → :meth:`FixtureRuntime._on_values` → 光电变色 / 滑块位移 /
spinbox 回填 / 伺服面板灯与数值 / **text 图元计数显示**。控件回写与面板命令
反向走 ``DataSource.write``。text 图元的绑定表见 ``cfg.TEXT_BINDINGS``，
新增显示图元时只在配置里加一行。

**运行态零污染**（本项目硬约束，见 tools/verify_test_fixture.py）
---------------------------------------------------------------
核心的 ``set_fill_color`` / ``change_position`` 会经 ``set_page_field`` /
``apply_rigid_pose`` 写进 ``_page``，导致 ``page_data()`` 与磁盘 JSON 不一致。
所以这里用 :class:`CleanVisuals`：

* 改色：只写 ``item._style`` 并 ``update()``，不碰 ``_page``；
* 改文本：只写 ``item.context`` 并 ``update()``，不碰 ``_page``；
* 位移：走 ``change_position``（Qt 变换 + 刚体传播带动子项），随后把
  父与所有后代的 ``_page`` 从快照还原并 ``mark_clean()``，同时清场景脏标记。

``item.context`` 之所以安全：``TextItem.paint()`` 读的是 item 属性，而
``to_page_record()`` 只深拷贝 ``_page``、不回读属性，所以 ``page_data()``
恒等于磁盘 JSON。**不能**用 ``RuntimeElement.context`` 的 setter——它走
``set_page_field("context", ...)``，既写 ``_page`` 又会触发
``_on_text_changed()`` 重算边框，属于设计态编辑语义。

因此 Qt 实际位置确实变了，但设计数据在内存里始终是原始 JSON。
注意：还原后 ``get_scene_center_pos()`` 读的是 ``_page`` 里的记录值（原始值），
**要判断实际位置请用 ``item().sceneBoundingRect()``**；联动一律用「绝对目标
y」计算，不依赖读回，所以连续推送不会漂移。
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QPointF, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QSpinBox

from Designer_V2.CoreQGraphics.runtime import RuntimeStage

from . import fixture_config as cfg
from .datasource import DataSource
from .servo_panel import ServoAxisPanel, make_panel_provider
from .flip_number import   FlipNumberProvider

# ---------------------------------------------------------------- 小工具
def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes", "是")
    return bool(value)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- 几何推导
@dataclass(frozen=True)
class FixtureGeometry:
    """从 JSON 现场推导的行程锚点，全部是 **page 坐标**。"""

    rail_top: float
    rail_bottom: float
    y_at_pos: float          # position == pos_mm 时滑块中心的 y
    y_at_neg: float          # position == neg_mm 时滑块中心的 y
    slider_h: float
    slider_x: float          # 滑块左上角 x，位移时保持不变

    @classmethod
    def derive(cls, stage: RuntimeStage) -> "FixtureGeometry":
        rail = stage.element_of(cfg.EL["rail"])
        lamp_pos = stage.element_of(cfg.EL["lamp_pos"])
        lamp_neg = stage.element_of(cfg.EL["lamp_neg"])
        slider = stage.element_of(cfg.EL["slider"])
        missing = [k for k, e in (("rail", rail), ("lamp_pos", lamp_pos),
                                  ("lamp_neg", lamp_neg), ("slider", slider))
                   if e is None or e.item() is None]
        if missing:
            raise ValueError(f"场景缺少必需图元：{missing}")

        r = rail.item().page_bounding_rect()
        s = slider.item().page_bounding_rect()
        half = s.height() / 2.0
        # 端点取三个光电的中心 y，再按配置决定是否内缩半高。
        # 默认内缩 → 滑块整块留在导轨内；关掉则严格对齐光电（会略探出）。
        inset = half if cfg.SLIDER_INSET_TO_RAIL else 0.0
        lo, hi = r.top() + inset, r.bottom() - inset
        if lo > hi:                       # 滑块比导轨还高，退化为不限制
            lo, hi = r.top(), r.bottom()

        def clamp(v: float) -> float:
            return max(lo, min(hi, v))

        return cls(
            rail_top=r.top(), rail_bottom=r.bottom(),
            y_at_pos=clamp(lamp_pos.get_scene_center_pos().y()),
            y_at_neg=clamp(lamp_neg.get_scene_center_pos().y()),
            slider_h=s.height(), slider_x=s.left(),
        )

    def y_for(self, position_mm: float, pos_mm: float, neg_mm: float) -> float:
        """把工程位置线性映射到导轨 y（position 增大 → 往正极限 → y 减小）。"""
        span = pos_mm - neg_mm
        if abs(span) < 1e-9:
            return self.y_at_neg
        t = (pos_mm - position_mm) / span
        if cfg.POSITION_CLAMP:
            t = max(0.0, min(1.0, t))
        return self.y_at_pos + t * (self.y_at_neg - self.y_at_pos)


# ---------------------------------------------------------------- 零污染视觉层
class CleanVisuals:
    """运行态视觉更新的唯一入口，保证 ``page_data()`` 恒等于磁盘 JSON。"""

    def __init__(self, stage: RuntimeStage) -> None:
        self._stage = stage
        self._snapshots: dict[int, dict] = {}

    def capture(self) -> int:
        self._snapshots = {
            e.item_id: copy.deepcopy(e.item()._page)
            for e in self._stage.elements() if e.item() is not None
        }
        return len(self._snapshots)

    def paint(self, element, fill: str, stroke: str | None = None) -> bool:
        it = element.item() if element is not None else None
        if it is None:
            return False
        it._style.fill_color = QColor(fill)
        if stroke is not None:
            it._style.stroke = QColor(stroke)
        it.update()
        return True

    def move_to_y(self, group, target_y: float) -> bool:
        it = group.item() if group is not None else None
        if it is None:
            return False
        rect = it.page_bounding_rect()
        target_top = QPointF(rect.left(), target_y - rect.height() / 2.0)
        group.change_position(target_top)      # 刚体传播会带动全部后代
        self._restore([group] + group.descendants())
        return True

    def paint_text(self, element, text: str) -> bool:
        """运行态刷新 text 图元文字，**零污染**。

        旧实现写 ``it._page.context``：``_page`` 是 ``dict``，给它设属性会直接
        抛 ``AttributeError: 'dict' object has no attribute 'context'``；即使
        改成 ``it._page["context"]`` 也会让 ``page_data()`` 与磁盘 JSON 不等。
        ``TextItem.paint()`` 读的是 ``item.context`` 属性，改这里就够了。
        不走 ``set_page_field`` 是有意的：那会连带重算文本边框（改几何）。
        """
        it = element.item() if element is not None else None
        if it is None or getattr(it, "TYPE", "") != "text":
            return False
        it.context = "" if text is None else str(text)
        it.update()
        return True

    def _restore(self, elements) -> None:
        for element in elements:
            it = element.item()
            if it is None:
                continue
            snap = self._snapshots.get(element.item_id)
            if snap is not None:
                it._page.clear()
                it._page.update(copy.deepcopy(snap))
            it.mark_clean()
        self._stage.scene._modified = False


# ---------------------------------------------------------------- 运行态
class FixtureRuntime(QObject):
    """一个可独立运行的画面：stage + 数据源 + 联动逻辑 + 生命周期。"""

    message = Signal(str, str)
    connectionChanged = Signal(bool, str)

    LAMPS = (
        ("neg_limit", "lamp_neg"),
        ("home", "lamp_home"),
        ("pos_limit", "lamp_pos"),
       
    )

    # (TAG 短名, EL 键, 小数位) —— 由 fixture_config.TEXT_BINDINGS 统一维护
    TEXT_BINDINGS = cfg.TEXT_BINDINGS

    PARAMS = ("reduction", "speed", "neg_pos", "pos_pos", "home_count")

    def __init__(self, page_path: str | Path | None = None,
                 source: DataSource | None = None,
                 parent: QObject | None = None,
                 *, panel_provider=None, flip_provider=None) -> None:
        super().__init__(parent)
        self.page_path = Path(page_path or cfg.PAGE_PATH)
        self.stage = RuntimeStage(
            page_path=str(self.page_path),
            widget_mode=cfg.WIDGET_MODE,
            fit_mode=cfg.FIT_MODE,
            geometry_profile=cfg.GEOMETRY_PROFILE,
            flush_ms=cfg.FLUSH_MS,
        )
        # set_mapping 用图元名登记，registry 此刻还是空的；load() 里
        # widgets.rebuild() 会按名字命中工厂，reload 也仍然有效。
        #
        # 翻页计数**不走** controlCreated：FlipNumberProvider 本身就是稳定的
        # 门面——set_value 转发到 display，换页重建时 create() 用 _latest
        # 补灌，控件 destroyed 时自动清 display。而 controlCreated 的第二个
        # 参数是造出来的 QWidget（这里是 FlipNumberDisplay），**不是**
        # provider；拿 isinstance(widget, FlipNumberProvider) 判断恒为假，
        # 会让引用永远停在 None（见 tools/verify_test_fixture.py 第 11 组）。
        flip_provider = flip_provider or FlipNumberProvider(digits=5)
        self.stage.set_mapping(
            {cfg.WIDGET["monitor"]: panel_provider or make_panel_provider(),
             cfg.WIDGET["flip_total_count"]: flip_provider})

        self.visuals = CleanVisuals(self.stage)
        self.geometry: FixtureGeometry | None = None
        self._source: DataSource | None = None
        self._spins: dict[str, QSpinBox] = {}
        self._panel: ServoAxisPanel | None = None
        self._flip_panel: FlipNumberProvider | None = flip_provider

        self._panel_iid = -1
        self._last_lamps: dict[str, bool] = {}
        self._values: dict[str, Any] = {}
        self.stage.tags.valuesChanged.connect(self._on_values)
        self.stage.controlCreated.connect(self._on_control_created)
        self.stage.widgets.controlDestroyed.connect(
            self._on_control_destroyed)

        self.stage.elementClicked.connect(
            lambda e: self._log(f"点击图元：{e.get_name()}", "info"))
        if source is not None:
            self.attach_source(source)

    # -- 装配 -----------------------------------------------------------
    def load(self) -> int:
        count = self.stage.load()
        if not count:
            return count
        self.visuals.capture()
        self.geometry = FixtureGeometry.derive(self.stage)
        self._install_controls()
        self._check_text_bindings()
        # load() 之前外部可能已经 push 过值：补灌一次，避免首屏停在 0。
        tag = cfg.TAG["total_count"]
        if tag in self._values and self._flip_panel is not None:
            self._flip_panel.set_value(self._values[tag], animate=False)
        self.stage.fit()
        return count

    def _check_text_bindings(self) -> None:
        """装载期把「图元名写错 / 绑到非 text 图元」直接报出来。

        以前这类错误只会表现为界面一直停在 ``###``，且没有任何提示；
        ``element_of()`` 按 name 查，JSON 改一个字就会静默失配。
        """
        for short, el_key, _ in cfg.TEXT_BINDINGS:
            name = cfg.EL[el_key]
            element = self.stage.element_of(name)
            item = element.item() if element is not None else None
            if item is None:
                self._log(f"text 绑定找不到图元 {name!r}"
                          f"（点位 {cfg.TAG.get(short)}）", "warn")
            elif getattr(item, "TYPE", "") != "text":
                self._log(f"text 绑定图元 {name!r} 的类型是 "
                          f"{getattr(item, 'TYPE', '?')}，不是 text", "warn")

    def _install_controls(self) -> None:
        self._spins.clear()
        for short, name in cfg.WIDGET.items():
            control = self.stage.widget(name)
            if not isinstance(control, QSpinBox):
                continue               # 监控窗口由 controlCreated 回调接手
            control.blockSignals(True)
            control.setRange(*cfg.SPIN_RANGE)
            control.setValue(int(cfg.PARAM_DEFAULTS.get(short, 0)))
            control.blockSignals(False)
            control.setToolTip(f"{name} → {cfg.TAG.get(short, short)}")
            control.valueChanged.connect(
                lambda value, s=short: self._on_spin(s, value))
            self._spins[short] = control

        # 参数初值也进总线：让行程映射范围与各控件值一致
        self.stage.tags.update_many(
            {cfg.TAG[k]: v for k, v in cfg.PARAM_DEFAULTS.items()
             if k in cfg.TAG})
        self.stage.tags.flush_now()

    def attach_source(self, source: DataSource) -> None:
        old = self._source
        if old is not None:
            for signal, slot in (
                    (old.valuesChanged, self.stage.tags.update_many),
                    (old.connectionChanged, self.connectionChanged),
                    (old.message, self._source_message)):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            old.stop()
            old_link = getattr(old, "_modbus_link", None)
            if old_link is not None:
                old_link.close()
        self._source = source
        source.setParent(self)
        source.valuesChanged.connect(self.stage.tags.update_many)
        source.connectionChanged.connect(self.connectionChanged)
        source.message.connect(self._source_message)

    def start(self) -> None:
        if self._source is not None:
            self._source.start()

    # -- 数据 -----------------------------------------------------------
    def push(self, key: str, value: Any, *, flush: bool = True) -> None:
        """外部（含回归脚本）手动灌一个点位值。"""
        self.stage.tags.update(key, value)
        if flush:
            self.stage.tags.flush_now()

    def _on_values(self, values: dict) -> None:
        self._values.update(values)
        self._apply_lamps(values)
        self._apply_slider(values)
        self._apply_params(values)
        self._apply_texts(values)
        if self._panel is not None:
            self._panel.set_values(values)
     
        # 只在本次推送确实带了总计数时才翻页。以前写成
        # values.get(tag, 0)，任何别的点位推一次值都会把翻牌清成 0。
        tag = cfg.TAG["total_count"]
        if tag in values and self._flip_panel is not None:
            self._flip_panel.set_value(values[tag])

    def _apply_lamps(self, values: dict) -> None:
        for short, el_key in self.LAMPS:
            tag = cfg.TAG[short]
            if tag not in values:
                continue
            on = _as_bool(values[tag])
            element = self.stage.element_of(cfg.EL[el_key])
            if element is not None:
                self.visuals.paint(
                    element,
                    cfg.LAMP_ON[short] if on else cfg.LAMP_OFF,
                    cfg.LAMP_BORDER_ON if on else cfg.LAMP_BORDER_OFF,
                )
            if self._last_lamps.get(short) != on:
                self._last_lamps[short] = on
                self._log(f"{short}: {'触发' if on else '复位'}", "info")

    def _apply_slider(self, values: dict) -> None:
        tag = cfg.TAG["position"]
        if tag not in values or self.geometry is None:
            return
        slider = self.stage.element_of(cfg.EL["slider"])
        if slider is None:
            return
        pos_mm = _as_float(self._value_of("pos_pos"), cfg.POS_MM_FALLBACK)
        neg_mm = _as_float(self._value_of("neg_pos"), cfg.NEG_MM_FALLBACK)
        if pos_mm < neg_mm:
            pos_mm, neg_mm = neg_mm, pos_mm
        target_y = self.geometry.y_for(_as_float(values[tag]), pos_mm, neg_mm)
        self.visuals.move_to_y(slider, target_y)

    def _apply_params(self, values: dict) -> None:
        for short in self.PARAMS:
            tag = cfg.TAG.get(short)
            control = self._spins.get(short)
            if not tag or control is None or tag not in values:
                continue
            value = _as_int(values[tag], control.value())
            if control.value() == value:
                continue
            control.blockSignals(True)      # 回填不能触发回写，避免自激
            control.setValue(max(cfg.SPIN_RANGE[0],
                                 min(cfg.SPIN_RANGE[1], value)))
            control.blockSignals(False)

    def _apply_texts(self, values: dict) -> None:
        """按 ``TEXT_BINDINGS`` 把 Modbus 点位值刷进 text 图元。

        ``values`` 的 key 是 **逻辑点位名**（``cfg.TAG``），不是图元名；
        旧实现误用 ``cfg.EL.get(...)"取 key，永远命中不了，界面停在 ``###``。
        """
        for short, el_key, digits in cfg.TEXT_BINDINGS:
            tag = cfg.TAG.get(short)
            if not tag or tag not in values:
                continue
            element = self.stage.element_of(cfg.EL[el_key])
            if element is None:
                continue
            value = values[tag]
            try:
                if short=="manual_mode":
                    text = "手动模式" if _as_bool(value) else '自动模式'
                else:
                    text = (f"{float(value):.{digits}f}" if digits
                            else str(_as_int(value, 0)))
            except (TypeError, ValueError):
                text = str(value)
            self.visuals.paint_text(element, text)

    

    def _value_of(self, short: str) -> Any:
        tag = cfg.TAG.get(short)
        if tag and tag in self._values:
            return self._values[tag]
        control = self._spins.get(short)
        return control.value() if control is not None else None

    def _on_spin(self, short: str, value: int) -> None:
        tag = cfg.TAG.get(short)
        if not tag:
            return
        self._values[tag] = value
        if self._source is not None:
            self._source.write(tag, value)
        self._log(f"写入 {tag} = {value}", "info")
        # 行程端点改了，用当前位置立刻重算一次滑块位置
        if short in ("pos_pos", "neg_pos") and cfg.TAG["position"] in self._values:
            self._apply_slider({cfg.TAG["position"]:
                                self._values[cfg.TAG["position"]]})

    # -- 伺服轴面板 -----------------------------------------------------
    def _on_control_created(self, iid: int, widget) -> None:
        """面板被 WidgetHost 造出来（含换页重建）时接信号、补灌缓存值。"""
        if not isinstance(widget, ServoAxisPanel):
            return
        self._panel = widget
        self._panel_iid = int(iid)
        widget.commandRequested.connect(self._on_panel_command)
        widget.set_values(self._values)
        self._log(f"伺服轴监控面板已挂载（{widget.spec.axis_index} 号轴）", "info")

    def _on_control_destroyed(self, iid: int) -> None:
        if int(iid) == self._panel_iid:
            self._panel = None           # proxy 回收后不能留悬空引用
            self._panel_iid = -1

    def _on_panel_command(self, key: str, value: Any) -> None:
        self._values[key] = value
        if self._source is not None:
            self._source.write(key, value)
        self._log(f"面板命令 {key} = {value}", "info")

    def _source_message(self, text: str, level: str) -> None:
        self._log(text, level)

    def _log(self, text: str, level: str = "info") -> None:
        if self._panel is not None:
            self._panel.set_status(
                f"[{time.strftime('%H:%M:%S')}] {text}", level)
        self.message.emit(text, level)


    # -- 生命周期 -------------------------------------------------------
    def report(self) -> str:
        g = self.geometry
        geo = (f"y∈[{g.y_at_pos:.1f}, {g.y_at_neg:.1f}]" if g else "未推导")
        flip = self._flip_panel
        return (f"FixtureRuntime({self.stage.report()}, "
                f"spins={len(self._spins)}, panel={self._panel is not None}, "
                f"flip={'on' if flip and flip.display else 'off'}"
                f"(value={getattr(flip, '_latest', '-')}), "
                f"geo={geo}, "
                f"source={type(self._source).__name__ if self._source else 'none'})")

    def release(self) -> None:
        if self._source is not None:
            self._source.stop()
            link = getattr(self._source, "_modbus_link", None)
            if link is not None:
                link.close()
        self._panel = None
        self._flip_panel = None
        self.stage.release()
