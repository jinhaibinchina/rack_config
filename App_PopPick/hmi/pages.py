"""PopPick OPC UA 的 7 个 HMI 页面 widget。

页面划分直接采用 XML 变量表注释里的分节标记（Info / ROBOT SYS / Servos /
IO / display / err / rcd / progrm tests / device status / test …），每个页面
用 :meth:`HmiPage.value` / :meth:`HmiPage.lamp` / :meth:`HmiPage.array` 声明
要显示的变量，节点寻址、数组打包形态、未接入标记都交给 ``tag_catalog``。

**写入策略**：只有标量节点提供写入控件，且写入前弹确认框展示变量名、
当前值、拟写入值与 NodeId。数组整体节点（``LOCAL_OUTPUT`` /
``REMOTE_OUTPUT`` / ``btnCancelTask`` 等）在 OPC UA 里没有逐元素节点，
不做单点强制写，页面按只读展示——硬写一个整包数组会把别的位一起覆盖掉。

**GVL 表**：真机地址空间当前没有暴露 ``GVL``（只有 ``GVL_HMI`` 和
``GVL_PARAMETERS``），所以 ``GVL.*`` 的点全部显示「未接入」。它们在页面里
保留位置并给出推断的候选 NodeId，等重新浏览导出后重跑生成脚本即可点亮。
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .tag_catalog import (
    TagCatalog,
    TagRef,
    array_items,
    as_bool,
    clean_text,
    format_value,
)
from .widgets import (
    Card,
    ConfirmBar,
    DataTable,
    IndicatorGrid,
    Lamp,
    LogView,
    MomentaryButton,
    PageHeader,
    PulseButton,
    ScrollBody,
    TagValue,
    WritableValue,
    apply_theme,
    small_label,
)


def demo_value(ref: TagRef) -> Any:
    """离线预览用的模拟值；按变量类型生成，不假装是真实 PLC 数据。"""
    typ = (ref.variable_type or "").upper()
    seed = sum(ord(ch) for ch in ref.expr)
    if ref.shape:
        count = 1
        for size in ref.shape:
            count *= int(size or 8)
        count = min(count, 200)
        if typ == "BOOL":
            return [(i + seed) % 3 == 0 for i in range(count)]
        if typ in ("STRING", "WSTRING"):
            return [f"[{i:02d}] 模拟记录 {i + seed % 97}｜机械手动作完成" for i in range(count)]
        if typ in ("INT", "UINT", "UDINT", "DINT"):
            return [(i + seed) % 100 for i in range(count)]
        return [round(((i + seed) % 900) / 10.0, 2) for i in range(count)]
    if typ == "BOOL":
        return seed % 3 != 0
    if typ in ("STRING", "WSTRING"):
        return "PopPick V2.0.0 (sim)"
    if typ in ("INT", "UINT", "UDINT", "DINT", "BYTE", "WORD", "DWORD", "SINT", "USINT"):
        return seed % 100
    if typ in ("REAL", "LREAL", "FLOAT", "DOUBLE"):
        return round((seed % 1200) / 10.0, 2)
    return 0


class HmiPage(QWidget):
    """所有页面的基类：tag 注册、值分发、写入转发、离线演示数据。

    一个页面实例对应场景里一张卡片。承载层重建控件时会再调一次工厂，所以
    新实例要靠 :meth:`replay` 把已经收到的值重灌一遍，否则画面会显示 "--"。
    """

    PAGE_ID = ""
    TITLE = ""
    SUBTITLE = ""
    write_requested = Signal(str, object)     # (业务 key, 值)
    log_message = Signal(str, str)            # (文本, 等级)

    def __init__(self, catalog: TagCatalog, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HmiPage")
        self.setMinimumSize(1, 1)
        apply_theme(self)
        self.catalog = catalog
        self.refs: list[TagRef] = []
        self._pending: list[TagRef] = []
        self._sinks: dict[str, list[Callable[[Any], None]]] = {}
        self._key_refs: dict[str, TagRef] = {}
        self._values: dict[str, Any] = {}
        self._demo_overrides: dict[str, Callable[[], Any]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = PageHeader(self.TITLE, self.SUBTITLE)
        root.addWidget(self.header)
        self.body = ScrollBody()
        root.addWidget(self.body, 1)
        # 浮动确认条：不进 layout，显示时不会挤矮内容区导致整体缩放跳动。
        # 它是 HmiPage 的直接子控件，不套内层 QGraphicsProxyWidget，鼠标事件
        # 只经过承载层那一次延迟派发，按钮可以正常点。
        self.confirm = ConfirmBar(self)
        self.confirm.accepted.connect(self.write_requested.emit)

        self.build()
        # 先尝试锁一次设计尺寸；ScrollBody 在每次 resize 时会自行校正，
        # 不依赖这里的调用时机。
        self.body.finalize()
        self.header.set_stats(len(self._key_refs), len(self.refs), len(self._pending))

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        # 第一个被 show 的页面布局 polish 最晚，resizeEvent 可能拿不到最小尺寸。
        # finalize() 是幂等的：设计尺寸没变就不会动 proxy/sceneRect。
        self.body.finalize()
        self._place_confirm()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self._place_confirm()

    def _place_confirm(self) -> None:
        height = max(36, self.confirm.sizeHint().height())
        self.confirm.setGeometry(12, self.header.height() + 4,
                                 max(200, self.width() - 24), height)

    # ------------------------------------------------------------------
    # 构建辅助
    # ------------------------------------------------------------------
    def build(self) -> None:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def watch(self, ref: TagRef, sink: Callable[[Any], None] | None = None) -> TagRef:
        """登记一个显示点；已验证的节点才会在订阅推送时收到值。"""
        self.refs.append(ref)
        if ref.connected and ref.key:
            key = ref.key
            self._key_refs[key] = ref
            if sink is not None:
                self._sinks.setdefault(key, []).append(sink)
            if key in self._values and sink is not None:
                try:
                    sink(self._values[key])
                except Exception:  # noqa: BLE001 - 演示数据格式不合不能拖垮页面
                    pass
        else:
            self._pending.append(ref)
        return ref

    def keys(self) -> list[str]:
        return list(self._key_refs)

    def on_tag(self, key: str, value: Any) -> None:
        self._values[key] = value
        for sink in self._sinks.get(key, ()):
            try:
                sink(value)
            except Exception as exc:  # noqa: BLE001 - 单点解析失败不影响其它点
                self.log_message.emit(f"{key} 显示失败: {exc}", "warn")

    def replay(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if key in self._sinks:
                self.on_tag(key, value)

    def set_connection(self, connected: bool, endpoint: str) -> None:
        self.header.set_connection(connected, endpoint)

    def on_client_message(self, text: str, level: str = "info") -> None:
        """客户端本地消息（连接/错误/写入回执）；默认忽略，日志页会覆盖。"""

    def pending_report(self) -> list[str]:
        return [f"{r.expr}｜{r.status}｜{clean_text(r.node_id) if r.node_id else '无节点'}"
                for r in self._pending]

    def seed_demo(self) -> None:
        """离线预览：按变量类型灌一份模拟数据，方便不连 PLC 检查版式。"""
        for key, ref in self._key_refs.items():
            override = self._demo_overrides.get(key)
            self.on_tag(key, override() if override else demo_value(ref))

    def shutdown(self) -> None:
        self.header.stop()

    # ------------------------------------------------------------------
    # 控件工厂（自动注册 sink / 转发写入信号）
    # ------------------------------------------------------------------
    def value(self, label: str, expr: str, *, unit: str = "",
              precision: int = 2) -> TagValue:
        ref = self.catalog.ref(expr, label=label, unit=unit)
        widget = TagValue(label, ref, unit=unit, precision=precision)
        self.watch(ref, widget.set_value)
        return widget

    def lamp(self, label: str, expr: str, *, alarm: bool = False) -> Lamp:
        ref = self.catalog.ref(expr, label=label)
        widget = Lamp(label)

        def setter(raw: Any) -> None:
            state = as_bool(raw)
            widget.set_state("err" if alarm and state else state)

        self.watch(ref, setter)
        return widget

    def array(self, expr: str, rows: int, cols: int, *, prefix: str = "",
              labels: Sequence[str] | None = None,
              writable: bool = False) -> IndicatorGrid:
        ref = self.catalog.ref(expr)
        widget = IndicatorGrid(rows, cols, prefix=prefix, labels=labels,
                               writable=writable)
        self.watch(ref, widget.set_values)
        if ref.connected and ref.key and rows * cols > 1:
            # 数组整体节点的演示数据要按灯数生成，不能套用变量表里的标量类型
            count = rows * cols
            seed = sum(ord(ch) for ch in expr)
            self._demo_overrides[ref.key] = lambda: [
                (i + seed) % 3 == 0 for i in range(count)
            ]
        if not ref.connected:
            widget.clear()
        return widget

    def writable(self, label: str, expr: str, *, unit: str = "",
                 label_width: int = 110) -> WritableValue:
        ref = self.catalog.ref(expr, label=label, unit=unit)
        widget = WritableValue(label, ref)
        widget._label.setMinimumWidth(label_width)
        self.watch(ref, widget.set_value)
        widget.confirm_requested.connect(self.confirm.request)
        return widget

    def pulse(self, text: str, expr: str, *, danger: bool = False,
              confirm: bool = False) -> PulseButton:
        ref = self.catalog.ref(expr, label=text)
        widget = PulseButton(text, ref, danger=danger, confirm=confirm)
        self.watch(ref)
        if confirm:
            widget.confirm_requested.connect(self.confirm.request)
        else:
            widget.write_requested.connect(self.write_requested.emit)
        return widget

    def momentary(self, text: str, expr: str) -> MomentaryButton:
        ref = self.catalog.ref(expr, label=text)
        widget = MomentaryButton(text, ref)
        self.watch(ref)
        widget.write_requested.connect(self.write_requested.emit)
        return widget

    def add_values(self, card: Card, specs: Sequence[tuple], columns: int = 3) -> None:
        """``specs`` 为 ``(标签, 变量表达式[, 单位])``。"""
        widgets = []
        for spec in specs:
            label, expr = spec[0], spec[1]
            unit = spec[2] if len(spec) > 2 else ""
            widgets.append(self.value(label, expr, unit=unit))
        card.fill_row(widgets, columns)

    def add_lamps(self, card: Card, specs: Sequence[tuple], columns: int = 4) -> None:
        widgets = []
        for spec in specs:
            label, expr = spec[0], spec[1]
            alarm = spec[2] if len(spec) > 2 else False
            widgets.append(self.lamp(label, expr, alarm=alarm))
        card.fill_row(widgets, columns)

    def row(self, *widgets: QWidget, stretch: bool = False) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(10)
        for widget in widgets:
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            layout.addWidget(widget)
        if stretch:
            layout.addStretch(1)
        # 给每行一个伸展因子，内容少的页面（主监控）不会只在顶部挤一小块、
        # 下面留一大片空白；内容多的页面超出视口时仍由 ScrollArea 滚动。
        self.body.add_layout(layout, 1)
        return layout

    def card(self, title: str, *, columns: int = 3) -> Card:
        widget = Card(title)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.body.add(widget)
        return widget

    def grid_cards(self, cards: Sequence[Card], columns: int = 2,
                   weight: int = 2) -> None:
        layout = QGridLayout()
        layout.setSpacing(10)
        for index, card in enumerate(cards):
            layout.addWidget(card, index // columns, index % columns)
        self.body.add_layout(layout, weight)


# ======================================================================
# 1. 主监控页面
# ======================================================================
class MainMonitorPage(HmiPage):
    PAGE_ID = "main"
    TITLE = "主监控页面"
    SUBTITLE = "GVL_HMI · Info / device status / task list / display｜总览与关键操作"

    def build(self) -> None:
        status = Card("设备状态")
        self.add_lamps(status, [
            ("系统运行 wSysRun", "GVL_HMI.wSysRun"),
            ("系统故障 wSysErr", "GVL_HMI.wSysErr", True),
            ("AGV 连接", "GVL_HMI.wAGV_Connected"),
            ("料仓就绪", "GVL_HMI.storageReady"),
            ("手动模式", "GVL_HMI.manual_switch"),
            ("WCS 连接（GVL）", "GVL.WCS_Connected"),
        ], columns=3)
        self.add_values(status, [
            ("设备模式", "GVL_HMI.wDeviceMode"),
            ("速度倍率", "GVL_HMI.overallRatio", "%"),
            ("CPU 占用", "GVL_HMI.CPU_usage", "%"),
            ("内存占用", "GVL_HMI.MemUsage", "%"),
            ("运行节拍", "GVL_HMI.timestrip_ms", "ms"),
        ], columns=3)

        task = Card("当前任务与节拍")
        self.add_values(task, [
            ("当前任务", "GVL_HMI.current_task"),
            ("上一任务", "GVL_HMI.prev_task"),
            ("当前任务执行中", "GVL_HMI.current_task_Executing"),
            ("当前任务可见", "GVL_HMI.current_task_visible"),
            ("当前应答", "GVL_HMI.currentTaskReply"),
            ("需确认", "GVL_HMI.currentTaskNeedAck"),
            ("主任务平均周期", "GVL_HMI.avl_main_task_circle_time", "ms"),
            ("主任务最大周期", "GVL_HMI.max_main_task_circle_time", "ms"),
            ("运动任务平均耗时", "GVL_HMI.avl_motion_task_exe_time", "us"),
            ("运动任务最大耗时", "GVL_HMI.max_motion_task_exe_time", "us"),
            ("节拍左", "GVL_HMI.timestrip_left"),
            ("节拍右", "GVL_HMI.timestrip_right"),
        ], columns=3)
        self.row(status, task)

        info = Card("系统信息")
        self.add_values(info, [
            ("程序版本", "GVL_HMI.program_version"),
            ("PLC 版本", "GVL_HMI.plc_version"),
            ("项目名称", "GVL_HMI.ProjectName"),
            ("版本", "GVL_HMI.Version"),
            ("作者", "GVL_HMI.Author"),
            ("产品名", "GVL_HMI.ProductName"),
            ("启动时间", "GVL_HMI.BootTime"),
            ("内存容量", "GVL_HMI.MemSize"),
            ("IP 地址", "GVL_HMI.IPAddress"),
            ("MAC 地址", "GVL_HMI.MACAddress"),
            ("子网掩码", "GVL_HMI.Netmask"),
            ("网关", "GVL_HMI.Gateway"),
            ("最近修改", "GVL_HMI.LastChanges"),
        ], columns=3)

        alarm = Card("报警摘要与控制")
        self.add_values(alarm, [
            ("报警数量", "GVL_HMI.ErrAmount2HMI"),
            ("任意报警（GVL）", "GVL.AnyAlarm"),
            ("当前报警码（GVL）", "GVL.CurrentAlarm"),
            ("报警计数（GVL）", "GVL.AlarmCounts"),
            ("当前报警文本（GVL）", "GVL.CurrentText"),
        ], columns=2)
        buttons = QHBoxLayout()
        for widget in (
            self.pulse("启动", "GVL_HMI.btn_start"),
            self.pulse("停止", "GVL_HMI.btn_stop", danger=True, confirm=True),
            self.pulse("复位", "GVL_HMI.btn_reset", confirm=True),
            self.pulse("急停", "GVL_HMI.btn_Estop", danger=True, confirm=True),
            self.pulse("清空任务", "GVL_HMI.btnClearAllTask", confirm=True),
        ):
            buttons.addWidget(widget)
        alarm.grid.addLayout(buttons, alarm._row, 0, 1, 4)
        alarm.newline()
        self.row(info, alarm)

        position = Card("机构、输送与料箱")
        self.add_lamps(position, [
            ("吸盘开启", "GVL_HMI.bSucker_On"),
            ("臂上有箱", "GVL_HMI.bHasBoxOnArm"),
            ("臂输送有箱", "GVL_HMI.bHasBoxOnArmConvey"),
            ("臂输送正转", "GVL_HMI.bArmConveyRunningPosi"),
            ("臂输送反转", "GVL_HMI.bArmConveyRunningNegi"),
            ("子动画显示", "GVL_HMI.bShowSubAnimation"),
        ], columns=3)
        self.add_values(position, [
            ("机械手 X", "GVL_HMI.displayArm_x"),
            ("机械手 Y", "GVL_HMI.displayArm_y"),
            ("机械手 Z", "GVL_HMI.displayArm_z"),
            ("臂输送箱位", "GVL_HMI.positionOnArmConvey"),
            ("提示", "GVL_HMI.Tip"),
        ], columns=3)
        conveyor = Card("工位输送带状态")
        conveyor.add(self.array("GVL_HMI.WorkConveyRunning", 1, 3,
                                prefix="工位 "), row=0, col=0, span=4)
        conveyor.add(self.array("GVL_HMI.WorkConveyRunningPosi", 1, 3,
                                prefix="正转 "), row=1, col=0, span=4)
        conveyor.add(self.array("GVL_HMI.WorkConveyRunningNegi", 1, 3,
                                prefix="反转 "), row=2, col=0, span=4)
        conveyor.add(self.array("GVL_HMI.displayWorkstationInfo.axHasBox", 1, 3,
                                prefix="工位有箱 "), row=3, col=0, span=4)
        self.row(position, conveyor)


# ======================================================================
# 2. 轴监控页面
# ======================================================================
class AxisMonitorPage(HmiPage):
    PAGE_ID = "axis"
    TITLE = "轴监控页面"
    SUBTITLE = "GVL_HMI · Servos / ROBOT SYS｜4 轴状态、手动点动与速度倍率"

    STATUS_FIELDS = (
        ("已连接", "xConnected", False),
        ("驱动就绪", "xDriveReady", False),
        ("已使能", "xEnabled", False),
        ("回零完成", "xHomeDone", False),
        ("运动中", "xMoving", False),
        ("静止", "xStandStill", False),
        ("故障", "xErr", True),
        ("故障停机", "xErrStop", True),
        ("正限位", "xPosLimit", True),
        ("负限位", "xNegLimit", True),
        ("参考点", "xReference", False),
    )
    VALUE_FIELDS = (
        ("当前位置", "fPositionNow", "mm"),
        ("当前速度", "fVelocityNow", "mm/s"),
        ("当前转矩", "fTorqueNow", "%"),
        ("跟随误差", "fFollowErrValue", "mm"),
        ("状态码", "iState", ""),
        ("驱动错误码", "sDriverErrorID", ""),
        ("错误说明", "sErrNote", ""),
        ("控制模式", "bControlMode", ""),
        ("伺服模式", "xServoOPmode", ""),
    )

    def build(self) -> None:
        cards = []
        for axis in range(1, 5):
            card = Card(f"轴 {axis} ｜ asServoStatus[{axis}] / asManualServo[{axis}]")
            # 不给 Card 硬编码最小高度：Qt 会按内部控件的 minimumSizeHint
            # 算出真实需要的高度，放不下时由 ScrollArea 滚动。硬塞一个下限
            # 反而会让 QGridLayout 的两行卡片互相溢出、标题压到上一张卡上。
            lamps = [
                self.lamp(label, f"GVL_HMI.asServoStatus[{axis}].{field}", alarm=alarm)
                for label, field, alarm in self.STATUS_FIELDS
            ]
            card.fill_row(lamps, 4)
            card.newline()
            card.fill_row([
                self.value(label, f"GVL_HMI.asServoStatus[{axis}].{field}", unit=unit)
                for label, field, unit in self.VALUE_FIELDS
            ], 3)
            card.newline()

            # 按钮逐个直接放进卡片网格：嵌套 QGridLayout 只占卡片的一行，
            # 里面 3 行按钮会被压成几条没有文字的细杠。
            manual_row = card._row
            for col, (text, field) in enumerate((
                ("JOG +", "jogPositive"), ("JOG -", "jogNegitive"),
                ("寸动 +", "InchPositive"), ("寸动 -", "InchNegitive"),
            )):
                card.add(self.momentary(
                    text, f"GVL_HMI.asManualServo[{axis}].{field}"),
                    row=manual_row, col=col)
            for col, (text, field) in enumerate((
                ("使能", "enable"), ("回零", "getHome"),
                ("停止", "stop"), ("故障确认", "acknowErr"),
            )):
                card.add(self.pulse(
                    text, f"GVL_HMI.asManualServo[{axis}].{field}",
                    confirm=(field in ("stop", "getHome"))),
                    row=manual_row + 1, col=col)
            for col, (text, field) in enumerate((
                ("绝对定位使能", "absEnable"), ("绝对定位执行", "absExecute"),
                ("速度设定执行", "velExecute"), ("", ""),
            )):
                if not field:
                    continue
                card.add(self.pulse(
                    text, f"GVL_HMI.asManualServo[{axis}].{field}",
                    confirm=field.endswith("Execute")),
                    row=manual_row + 2, col=col)
            # 写入行一项一行：卡片只有半屏宽，三个「标签+当前值+输入框+按钮」
            # 并排会互相压字。
            write_row = card._row
            for offset, (text, field, unit) in enumerate((
                ("绝对距离", "absDistance", "mm"),
                ("寸动距离", "inchDistance", "mm"),
                ("设定速度", "velocity", "mm/s"),
            )):
                card.add(self.writable(text, f"GVL_HMI.asManualServo[{axis}].{field}",
                                       unit=unit, label_width=90),
                         row=write_row + offset, col=0, span=4)
            cards.append(card)
        self.grid_cards(cards, columns=2, weight=3)

        allow = Card("点动许可与臂位置")
        allow.add(small_label("GVL.* 的点当前未暴露 OPC UA 节点，灰灯＝待接入（非 OFF）"),
                  row=0, col=0, span=4)
        allow.add(self.array("GVL_HMI.aAllowMoveJogP", 1, 4, prefix="允许 + 轴"),
                  row=1, col=0, span=4)
        allow.add(self.array("GVL_HMI.aAllowMoveJogN", 1, 4, prefix="允许 - 轴"),
                  row=2, col=0, span=4)
        allow.add(self.array("GVL.aAllowMoveAxisManual", 1, 3, prefix="GVL 手动轴 "),
                  row=3, col=0, span=4)
        allow.add(self.array("GVL.ArmMotorSpeeds", 1, 3, prefix="GVL 电机速度 "),
                  row=4, col=0, span=4)
        self.add_values(allow, [
            ("臂 X", "GVL_HMI.displayArm_x"),
            ("臂 Y", "GVL_HMI.displayArm_y"),
            ("臂 Z", "GVL_HMI.displayArm_z"),
            ("姿态 X", "GVL_HMI.displayArmPositions.x"),
            ("姿态 Y", "GVL_HMI.displayArmPositions.y"),
            ("姿态 Z", "GVL_HMI.displayArmPositions.z"),
        ], columns=3)

        speed = Card("速度倍率与全局设定")
        speed.add(self.writable("速度倍率", "GVL_HMI.overallRatio", unit="%"), row=0, col=0, span=2)
        speed.add(self.writable("全局速度", "GVL_PARAMETERS.speedoverall"), row=0, col=2, span=2)
        buttons = QHBoxLayout()
        buttons.addWidget(self.pulse("速度 +", "GVL_HMI.btn_speed_add"))
        buttons.addWidget(self.pulse("速度 -", "GVL_HMI.btn_speed_min"))
        speed.grid.addLayout(buttons, 1, 0, 1, 4)
        self.row(allow, speed)


# ======================================================================
# 3. IO 监控页面
# ======================================================================
class IoMonitorPage(HmiPage):
    PAGE_ID = "io"
    TITLE = "IO 监控"
    SUBTITLE = "GVL_HMI · IO / conveys / modebusTCP｜本地 8+8、远程 48+48、执行机构"

    def build(self) -> None:
        local = Card("本地 IO ｜ LOCAL_INPUT / LOCAL_OUTPUT [0..7]")
        local.add(small_label("BOOL 数组整体节点：一次订阅拿到整个数组，灰灯表示无数据"),
                  row=0, col=0, span=4)
        local.add(self.array("GVL_HMI.LOCAL_INPUT", 1, 8, prefix="DI"),
                  row=1, col=0, span=4)
        local.add(self.array("GVL_HMI.LOCAL_OUTPUT", 1, 8, prefix="DO"),
                  row=2, col=0, span=4)

        # 48+48 个灯，两组并排、独占整行：塞进左右分栏里会把每格压到十几
        # 像素宽，相邻行的文字直接画到一起（见第一次预览截图）。
        remote = Card("远程 IO ｜ REMOTE_INPUT / REMOTE_OUTPUT [0..5, 0..7]")
        remote.add(self.array("GVL_HMI.REMOTE_INPUT", 6, 8, prefix="RI"),
                   row=0, col=0, span=2)
        remote.add(self.array("GVL_HMI.REMOTE_OUTPUT", 6, 8, prefix="RO"),
                   row=0, col=2, span=2)
        remote.add(small_label(
            "输出点为数组整体节点，没有逐元素 NodeId；本页只读展示，不做单点强制写，"
            "以免整包回写覆盖其它位。"), row=1, col=0, span=4)
        self.body.add(remote)

        actuator = Card("吸盘、输送与料箱检测")
        self.add_lamps(actuator, [
            ("吸盘开启", "GVL_HMI.bSucker_On"),
            ("臂上有箱", "GVL_HMI.bHasBoxOnArm"),
            ("臂输送有箱", "GVL_HMI.bHasBoxOnArmConvey"),
            ("臂输送正转", "GVL_HMI.bArmConveyRunningPosi"),
            ("臂输送反转", "GVL_HMI.bArmConveyRunningNegi"),
            ("料仓就绪", "GVL_HMI.storageReady"),
        ], columns=3)
        buttons = QHBoxLayout()
        for text, expr in (
            ("真空开", "GVL_HMI.btn_vacuumize"),
            ("左输送正转", "GVL_HMI.btnFwd_left"),
            ("左输送反转", "GVL_HMI.btnRev_left"),
            ("中输送正转", "GVL_HMI.btnFwd_mid"),
            ("中输送反转", "GVL_HMI.btnRev_mid"),
            ("右输送正转", "GVL_HMI.btnFwd_right"),
            ("右输送反转", "GVL_HMI.btnRev_right"),
        ):
            buttons.addWidget(self.momentary(text, expr))
        buttons_row = actuator._row
        actuator.grid.addLayout(buttons, buttons_row, 0, 1, 4)
        actuator.newline()
        grid_row = actuator._row
        actuator.add(self.array("GVL_HMI.WorkConveyRunning", 1, 3, prefix="运行 "),
                     row=grid_row, col=0, span=2)
        actuator.add(self.array("GVL_HMI.WorkConveyRunningPosi", 1, 3, prefix="正转 "),
                     row=grid_row, col=2, span=2)
        actuator.newline()

        box = Card("工位料箱信息 ｜ boxInfoOnWorkstation[0..2]")
        self._box_table = DataTable(("工位", "箱号", "重量", "可拣", "已拣", "源行", "源列", "任务号"), 3)
        box.add(self._box_table, row=0, col=0, span=4)
        self._box_rows = [[str(i), "--", "--", "--", "--", "--", "--", "--"] for i in range(3)]
        for i in range(3):
            for col, (field, label) in enumerate((
                ("id", "箱号"), ("weight", "重量"), ("readyForPick", "可拣"),
                ("pickDone", "已拣"), ("src_row", "源行"), ("src_col", "源列"),
                ("TaskNo", "任务号"),
            ), start=1):
                ref = self.catalog.member_ref("GVL_HMI.boxInfoOnWorkstation", field,
                                              index=i, label=label)
                self.watch(ref, self._make_cell_setter(i, col))
        self._box_table.set_rows(self._box_rows)

        modbus = Card("Modbus TCP 保持寄存器 ｜ HoldResisterIn / Out")
        self._reg_table = DataTable(("地址", "IN (GVL_HMI)", "OUT (GVL_HMI)"), 16)
        modbus.add(self._reg_table, row=0, col=0, span=4)
        self._reg_in: list[Any] = [None] * 16
        self._reg_out: list[Any] = [None] * 16

        def take_in(raw: Any) -> None:
            self._reg_in = array_items(raw, 16)[:16]
            self._refresh_regs()

        def take_out(raw: Any) -> None:
            self._reg_out = array_items(raw, 16)[:16]
            self._refresh_regs()

        self.watch(self.catalog.ref("GVL_HMI.HoldResisterIn", label="保持寄存器 IN"), take_in)
        self.watch(self.catalog.ref("GVL_HMI.HoldResisterOut", label="保持寄存器 OUT"), take_out)
        self._refresh_regs()

        self.row(local, actuator)
        self.row(box, modbus)

    def _make_cell_setter(self, row: int, col: int):
        def setter(value: Any) -> None:
            self._box_rows[row][col] = format_value(value)
            self._box_table.set_rows(self._box_rows)
        return setter

    def _refresh_regs(self) -> None:
        self._reg_table.set_rows([
            [f"{i:03d}", format_value(self._reg_in[i]), format_value(self._reg_out[i])]
            for i in range(16)
        ])


# ======================================================================
# 4. 参数设置页面
# ======================================================================
class ParameterSettingsPage(HmiPage):
    PAGE_ID = "parameters"
    TITLE = "参数设置"
    SUBTITLE = "GVL_PARAMETERS / GVL_HMI · teach / camera｜写入前逐项确认"

    SUCKER_PARAMS = (
        ("吸盘回退位", "sucker_ret_pos", "mm"),
        ("吸盘前次回退位", "sucker_prev_ret_pos", "mm"),
        ("吸盘进出位", "sucker_gearinout_pos", "mm"),
        ("吸盘前次伸出位", "sucker_prev_ext_pos", "mm"),
        ("吸盘伸出位", "sucker_ext_pos", "mm"),
        ("工位输送速度", "workstationconveyvelocity", "mm/s"),
        ("全局速度", "speedoverall", ""),
        ("料仓类型", "storageType", ""),
    )
    POSE_PARAMS = (
        ("料仓基准 X", "p_storage_xx_x", "mm"), ("料仓基准 Z", "p_storage_xx_z", "mm"),
        ("料仓基准行", "p_storage_xx_row", ""), ("料仓基准列", "p_storage_xx_col", ""),
        ("工位 0 X", "p_workstation_0_x", "mm"), ("工位 0 Z", "p_workstation_0_z", "mm"),
        ("工位 1 X", "p_workstation_1_x", "mm"), ("工位 1 Z", "p_workstation_1_z", "mm"),
        ("工位 2 X", "p_workstation_2_x", "mm"), ("工位 2 Z", "p_workstation_2_z", "mm"),
        ("相机偏移 XZ-X", "camera_offset_xz_p_storage_xx_x", "mm"),
        ("相机偏移 XZ-Z", "camera_offset_xz_p_storage_xx_z", "mm"),
        ("相机偏移 Y", "camera_offset_y", "mm"),
    )

    def build(self) -> None:
        sucker = Card("工艺参数 ｜ GVL_PARAMETERS（对应 GVL 的镜像）")
        for row, (label, name, unit) in enumerate(self.SUCKER_PARAMS):
            sucker.add(self.writable(label, f"GVL_PARAMETERS.{name}", unit=unit),
                       row=row // 2, col=(row % 2) * 2, span=2)

        pose = Card("示教位置与相机标定 ｜ GVL_PARAMETERS")
        for row, (label, name, unit) in enumerate(self.POSE_PARAMS):
            pose.add(self.writable(label, f"GVL_PARAMETERS.{name}", unit=unit),
                     row=row // 2, col=(row % 2) * 2, span=2)
        self.row(sucker, pose)

        transfer = Card("参数下发 / 恢复")
        buttons = QHBoxLayout()
        buttons.addWidget(self.pulse("下发参数 btn_do", "GVL_PARAMETERS.btn_do", confirm=True))
        buttons.addWidget(self.pulse("恢复参数 btn_undo", "GVL_PARAMETERS.btn_undo", confirm=True))
        transfer.grid.addLayout(buttons, 0, 0, 1, 4)
        transfer.newline()
        self.add_lamps(transfer, [
            ("下发完成", "GVL_HMI.ParamsTransferDone"),
            ("恢复完成", "GVL_HMI.ParamsRecoverDone"),
        ], columns=2)

        teach = Card("示教与定位 ｜ GVL_HMI / teach")
        teach_buttons = [
            ("示教料仓位", "GVL_HMI.btn_teach_P_Storage_00"),
            ("示教工位 0", "GVL_HMI.btn_teach_P_WorkStation_0"),
            ("示教工位 1", "GVL_HMI.btn_teach_P_WorkStation_1"),
            ("示教工位 2", "GVL_HMI.btn_teach_P_WorkStation_2"),
            ("移动到料仓位", "GVL_HMI.btn_moveTo_teach_P_Storage_00"),
            ("移动到工位 0", "GVL_HMI.btn_moveTo_P_WorkStation_0"),
            ("移动到工位 1", "GVL_HMI.btn_moveTo_P_WorkStation_1"),
            ("移动到工位 2", "GVL_HMI.btn_moveTo_P_WorkStation_2"),
        ]
        for index, (text, expr) in enumerate(teach_buttons):
            teach.add(self.pulse(text, expr, confirm=True),
                      row=index // 4, col=index % 4)
        self.row(transfer, teach)

        camera = Card("相机状态 ｜ GVL_HMI.CameraDatas")
        self.add_lamps(camera, [
            ("就绪", "GVL_HMI.CameraDatas.xReady"),
            ("忙", "GVL_HMI.CameraDatas.xBusy"),
            ("故障", "GVL_HMI.CameraDatas.xError", True),
            ("解析成功", "GVL_HMI.CameraDatas.xParseOK"),
        ], columns=4)
        self.add_values(camera, [
            ("错误码", "GVL_HMI.CameraDatas.eErrorID"),
            ("偏移 X", "GVL_HMI.CameraDatas.rOffsetX"),
            ("偏移 Y", "GVL_HMI.CameraDatas.rOffsetY"),
            ("偏移角", "GVL_HMI.CameraDatas.rOffsetAngle"),
        ], columns=4)

        gvl = Card("GVL 本体 ｜ 当前未暴露 OPC UA 节点（待重新浏览导出）")
        self.add_values(gvl, [
            ("料仓类型", "GVL.storageType"),
            ("料仓行数", "GVL.MAX_STORAGE_ROW"),
            ("料仓列数", "GVL.MAX_STORAGE_COL"),
            ("工位数", "GVL.MAX_WORKSTATION"),
            ("日志长度", "GVL.RCD_CONTEXT_LEN"),
            ("哈希表大小", "GVL.HASH_TABLE_SIZE"),
            ("工位输送速度", "GVL.WorkStationConveyVelocity"),
            ("吸盘回退位", "GVL.sucker_ret_pos"),
            ("最大报警 ID", "GVL.MAX_ALARM_ID"),
        ], columns=3)
        self.row(camera, gvl)


# ======================================================================
# 5. 报警页面
# ======================================================================
class AlarmPage(HmiPage):
    PAGE_ID = "alarm"
    TITLE = "报警"
    SUBTITLE = "GVL_HMI · err / Alarms2HMII[0..9]｜当前报警、历史与复位"

    FIELDS = (
        ("AlarmCode", "报警码"), ("Timestamp", "时间戳"),
        ("Category", "分类"), ("wsText", "文本"), ("bVisible", "可见"),
    )

    def build(self) -> None:
        summary = Card("报警汇总")
        self.add_values(summary, [
            ("报警数量", "GVL_HMI.ErrAmount2HMI"),
            ("系统故障", "GVL_HMI.wSysErr"),
            ("任意报警（GVL）", "GVL.AnyAlarm"),
            ("当前报警（GVL）", "GVL.CurrentAlarm"),
            ("报警计数（GVL）", "GVL.AlarmCounts"),
            ("当前报警文本（GVL）", "GVL.CurrentText"),
        ], columns=3)
        buttons = QHBoxLayout()
        buttons.addWidget(self.pulse("报警复位", "GVL_HMI.btn_reset", confirm=True))
        buttons.addWidget(self.pulse("停止", "GVL_HMI.btn_stop", danger=True, confirm=True))
        summary.grid.addLayout(buttons, summary._row, 0, 1, 4)
        summary.newline()

        table_card = Card("报警列表 ｜ ST_AlarmShow × 10")
        self._table = DataTable(("#", "报警码", "时间戳", "分类", "文本", "可见"), 10)
        table_card.add(self._table, row=0, col=0, span=4)
        self._rows = [[str(i)] + ["--"] * 5 for i in range(10)]
        for i in range(10):
            for col, (field, label) in enumerate(self.FIELDS, start=1):
                ref = self.catalog.member_ref("GVL_HMI.Alarms2HMII", field,
                                              index=i, label=label)
                self.watch(ref, self._make_setter(i, col))
        self._table.set_rows(self._rows)

        self.client_log = LogView()
        self.client_log.setMaximumHeight(180)
        log_card = Card("客户端事件（连接 / 写入 / 错误）")
        log_card.add(self.client_log, row=0, col=0, span=4)
        self.row(summary, log_card)
        self.body.add(table_card)

    def _make_setter(self, row: int, col: int):
        def setter(value: Any) -> None:
            self._rows[row][col] = format_value(value)
            visible = self._rows[row][5]
            self._table.set_rows(self._rows, highlight=row if "ON" in visible or "True" in visible else -1)
        return setter

    def on_client_message(self, text: str, level: str = "info") -> None:
        self.client_log.append_line(text, level)


# ======================================================================
# 6. 日志页面
# ======================================================================
class LogPage(HmiPage):
    PAGE_ID = "log"
    TITLE = "日志"
    SUBTITLE = "GVL_HMI · rcd / Info｜PLC 记录文本、运行统计与客户端事件"

    def build(self) -> None:
        rcd = Card("PLC 记录 ｜ rcd_texts[0..9]")
        self._rcd_view = LogView()
        self._rcd_view.setMinimumHeight(260)
        rcd.add(self._rcd_view, row=0, col=0, span=4)
        self.watch(self.catalog.ref("GVL_HMI.rcd_texts", label="记录文本"),
                   lambda value: self._rcd_view.set_lines(array_items(value, 10)[:10]))
        page_row = QHBoxLayout()
        page_row.addWidget(self.value("记录页码", "GVL_HMI.rcd_page"))
        page_row.addWidget(self.writable("翻页 rcd_page", "GVL_HMI.rcd_page"))
        rcd.grid.addLayout(page_row, 1, 0, 1, 4)

        runtime = Card("运行统计 ｜ GVL_HMI / Info")
        self.add_values(runtime, [
            ("CPU 占用", "GVL_HMI.CPU_usage", "%"),
            ("内存占用", "GVL_HMI.MemUsage", "%"),
            ("内存容量", "GVL_HMI.MemSize"),
            ("启动时间", "GVL_HMI.BootTime"),
            ("运行节拍", "GVL_HMI.timestrip_ms", "ms"),
            ("节拍左", "GVL_HMI.timestrip_left"),
            ("节拍右", "GVL_HMI.timestrip_right"),
            ("主任务平均", "GVL_HMI.avl_main_task_circle_time", "ms"),
            ("主任务最大", "GVL_HMI.max_main_task_circle_time", "ms"),
            ("运动平均", "GVL_HMI.avl_motion_task_exe_time", "us"),
            ("运动最大", "GVL_HMI.max_motion_task_exe_time", "us"),
            ("程序版本", "GVL_HMI.program_version"),
            ("PLC 版本", "GVL_HMI.plc_version"),
            ("最近修改", "GVL_HMI.LastChanges"),
        ], columns=3)
        self.row(rcd, runtime)

        client = Card("客户端事件日志")
        self.client_log = LogView()
        self.client_log.setMinimumHeight(200)
        client.add(self.client_log, row=0, col=0, span=4)
        self.add_values(client, [
            ("提示信息", "GVL_HMI.Tip"),
            ("工程描述", "GVL_HMI.工程描述"),
            ("作者", "GVL_HMI.Author"),
        ], columns=3)
        self.body.add(client)

    def on_client_message(self, text: str, level: str = "info") -> None:
        self.client_log.append_line(text, level)


# ======================================================================
# 7. 程序监控页面
# ======================================================================
class ProgramMonitorPage(HmiPage):
    PAGE_ID = "program"
    TITLE = "程序监控"
    SUBTITLE = "GVL_HMI · progrm tests / task list / test｜程序行、任务队列与命令应答"

    def build(self) -> None:
        code = Card("程序文本 ｜ prg_texts[0..13]")
        self._code_view = LogView()
        self._code_view.setMinimumHeight(320)
        code.add(self._code_view, row=0, col=0, span=4)
        self._lines: list[str] = ["--"] * 14
        self._exe_line: Any = None
        self._offset: Any = None
        self.watch(self.catalog.ref("GVL_HMI.prg_texts", label="程序文本"),
                   self._set_lines)
        self.watch(self.catalog.ref("GVL_HMI.current_exe_line", label="当前行"),
                   self._set_exe_line)
        self.watch(self.catalog.ref("GVL_HMI.exe_line_offset", label="行偏移"),
                   self._set_offset)
        nav = QHBoxLayout()
        nav.addWidget(self.value("页码", "GVL_HMI.prg_page"))
        nav.addWidget(self.value("当前执行行", "GVL_HMI.current_exe_line"))
        nav.addWidget(self.value("行偏移", "GVL_HMI.exe_line_offset"))
        nav.addWidget(self.pulse("上一页", "GVL_HMI.btn_prg_page_prev"))
        nav.addWidget(self.pulse("下一页", "GVL_HMI.btn_prg_page_next"))
        code.grid.addLayout(nav, 1, 0, 1, 4)
        self._refresh_code()

        tasks = Card("任务队列 ｜ taskList[0..9] / btnCancelTask")
        self._task_table = DataTable(("#", "任务文本", "当前", "上一"), 10)
        tasks.add(self._task_table, row=0, col=0, span=4)
        self._task_lines: list[str] = ["--"] * 10
        self.watch(self.catalog.ref("GVL_HMI.taskList", label="任务队列"),
                   self._set_tasks)
        tasks.add(self.array("GVL_HMI.btnCancelTask", 1, 10, prefix="取消 "),
                  row=1, col=0, span=4)
        self.add_values(tasks, [
            ("当前任务", "GVL_HMI.current_task"),
            ("上一任务", "GVL_HMI.prev_task"),
            ("当前执行中", "GVL_HMI.current_task_Executing"),
            ("上一执行中", "GVL_HMI.prev_task_Executing"),
            ("当前应答", "GVL_HMI.currentTaskReply"),
            ("上一应答", "GVL_HMI.prevTaskReply"),
            ("当前需确认", "GVL_HMI.currentTaskNeedAck"),
            ("上一需确认", "GVL_HMI.prevTaskNeedAck"),
            ("当前可见", "GVL_HMI.current_task_visible"),
        ], columns=3)
        tasks.grid.addWidget(self.pulse("清空全部任务", "GVL_HMI.btnClearAllTask",
                                        confirm=True), tasks._row, 0, 1, 4)
        tasks.newline()
        self.row(code, tasks)

        command = Card("命令与应答 ｜ GVL_HMI / test")
        for index, (label, name) in enumerate((
            ("命令 ID", "cmd_id"), ("方向", "cmd_dir"),
            ("源行", "cmd_src_storage_row"), ("源列", "cmd_src_storage_col"),
            ("目标行", "cmd_dest_storage_row"), ("目标列", "cmd_dest_storage_col"),
            ("源工位", "cmd_src_workstation"), ("目标工位", "cmd_dest_workstation"),
            ("应答 ID", "ack_id"),
        )):
            command.add(self.writable(label, f"GVL_HMI.{name}"),
                        row=index // 2, col=(index % 2) * 2, span=2)
        buttons = QHBoxLayout()
        buttons.addWidget(self.pulse("添加命令 cmd_add", "GVL_HMI.cmd_add", confirm=True))
        buttons.addWidget(self.pulse("应答 ack", "GVL_HMI.ack", confirm=True))
        buttons.addWidget(self.pulse("启动", "GVL_HMI.btn_start"))
        buttons.addWidget(self.pulse("停止", "GVL_HMI.btn_stop", danger=True, confirm=True))
        command.grid.addLayout(buttons, command._row, 0, 1, 4)
        command.newline()

        workstation = Card("工位任务状态")
        workstation.add(self.array("GVL_HMI.aWorkstationTaskReq", 1, 3, prefix="请求 "),
                        row=0, col=0, span=4)
        workstation.add(self.array("GVL_HMI.aWorkstationTaskInQueue", 1, 3, prefix="队列 "),
                        row=1, col=0, span=4)
        self._src_table = DataTable(("工位", "行", "列", "任务号", "料仓类型"), 3)
        workstation.add(self._src_table, row=2, col=0, span=4)
        self._src_rows = [[str(i), "--", "--", "--", "--"] for i in range(3)]
        for i in range(3):
            for col, field in enumerate(("row", "col", "TaskNo", "storageType"), start=1):
                ref = self.catalog.member_ref("GVL_HMI.aWorkstationSrcPosition", field,
                                              index=i, label=field)
                self.watch(ref, self._make_src_setter(i, col))
        self._src_table.set_rows(self._src_rows)
        self.row(command, workstation)

    def _refresh_code(self) -> None:
        try:
            highlight = int(self._exe_line) + int(self._offset or 0)
        except (TypeError, ValueError):
            highlight = -1
        self._code_view.set_lines(self._lines, highlight=highlight)

    def _set_lines(self, value: Any) -> None:
        self._lines = [clean_text(x) if isinstance(x, str) else format_value(x)
                       for x in array_items(value, 14)[:14]]
        self._refresh_code()

    def _set_exe_line(self, value: Any) -> None:
        self._exe_line = value
        self._refresh_code()

    def _set_offset(self, value: Any) -> None:
        self._offset = value
        self._refresh_code()

    def _refresh_tasks(self) -> None:
        self._task_table.set_rows([
            [str(i), self._task_lines[i], "--", "--"] for i in range(10)
        ], highlight=0)

    def _set_tasks(self, value: Any) -> None:
        self._task_lines = [clean_text(x) if isinstance(x, str) else format_value(x)
                            for x in array_items(value, 10)[:10]]
        self._refresh_tasks()

    def _make_src_setter(self, row: int, col: int):
        def setter(value: Any) -> None:
            self._src_rows[row][col] = format_value(value)
            self._src_table.set_rows(self._src_rows)
        return setter


# ======================================================================
# 页面注册表
# ======================================================================
PAGE_CLASSES: tuple[type[HmiPage], ...] = (
    MainMonitorPage,
    AxisMonitorPage,
    IoMonitorPage,
    ParameterSettingsPage,
    AlarmPage,
    LogPage,
    ProgramMonitorPage,
)

#: 默认挂载到场景卡片的顺序。设计文件 ``page_9.json`` 只有 Page0..Page5，
#: 第 7 页需要新增一张卡片（见 tools/gen_hmi_scene.py 生成的 page_10.json），
#: 或者通过 ``attach_hmi_pages(..., mapping=...)`` 改成别的对应关系。
DEFAULT_CARDS = ("Page0", "Page1", "Page2", "Page3", "Page4", "Page5", "Page6")


def make_page_specs() -> list:
    from .tag_catalog import PageSpec

    return [
        PageSpec(page_id=cls.PAGE_ID, title=cls.TITLE, subtitle=cls.SUBTITLE,
                 card=DEFAULT_CARDS[i], factory=cls)
        for i, cls in enumerate(PAGE_CLASSES)
    ]
