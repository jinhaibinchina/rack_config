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
    BODY_SIZE,
    PAGE_SIZE,
    Card,
    ElidedLabel,
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

    **页面尺寸固定 750×1000**（:data:`PAGE_SIZE`）：页头占 52px，内容区
    750×948（:data:`BODY_SIZE`），按 1:1 呈现不缩放、不滚动。每个页面的布局
    必须在这个画布里排得下，``tools/verify_hmi_layout.py`` 会用
    ``ScrollBody.overflow()`` 断言这一点。
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
        self.body = ScrollBody(BODY_SIZE)
        root.addWidget(self.body, 1)
        # 浮动确认条：不进 layout，显示时不会挤矮内容区导致整体缩放跳动。
        # 它是 HmiPage 的直接子控件，不套内层 QGraphicsProxyWidget，鼠标事件
        # 只经过承载层那一次延迟派发，按钮可以正常点。
        self.confirm = ConfirmBar(self)
        self.confirm.accepted.connect(self.write_requested.emit)

        self.build()
        self._finish_cards()
        # 量一次内容最小尺寸（画布固定，超出用 overflow() 报告）。
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

    def _finish_cards(self) -> None:
        """给每张卡片补竖直弹簧（见 :meth:`widgets.Card.finish`）。

        **必须从 ``self.body.content`` 往下找**：卡片挂在 ``QGraphicsProxyWidget``
        里，QObject 父子链走到代理项就断了，``page.findChildren(Card)`` 一个都
        找不到（``Card.finish()`` 曾经因此从没执行过）。
        """
        for card in self.body.content.findChildren(Card):
            card.finish()

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
        # 客户端事件区（日志页 / 报警页）不灌一句话就是一大片空白，看着像
        # 控件没加载出来；顺便说明"这是模拟数据"，免得误当成真实现场。
        self.on_client_message("离线演示：未连接 PLC，以下为模拟数据", "warn")

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
              labels: Sequence[str] | None = None, compact: bool = False,
              writable: bool = False) -> IndicatorGrid:
        ref = self.catalog.ref(expr)
        widget = IndicatorGrid(rows, cols, prefix=prefix, labels=labels,
                               writable=writable, compact=compact)
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

    def row(self, *widgets: QWidget, weight: int = 1, stretch: bool = False) -> QHBoxLayout:
        """把几张卡并排放进内容区。

        ``weight`` 是**竖直方向**的伸展权重：内容装不满 948px 时，富余空间按
        权重分给这几张卡（卡内的行随之拉开），而不是全堆在页面底部。
        """
        layout = QHBoxLayout()
        layout.setSpacing(6)
        for widget in widgets:
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout.addWidget(widget)
        if stretch:
            layout.addStretch(1)
        self.body.add_layout(layout, weight)
        return layout

    def strip(self, widgets: Sequence[QWidget], *, spacing: int = 4) -> QWidget:
        """把一排控件装进一个横向容器，整行放进卡片网格。

        卡片共用一个 QGridLayout 时，列宽会被其它行"共享"：6 个灯会把 3 个
        写入框挤到 60px 宽。用容器各排各的列就不会互相牵连。
        """
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)
        for widget in widgets:
            layout.addWidget(widget, 1)
        return holder

    def block(self, widgets: Sequence[QWidget], columns: int, *,
              spacing: int = 4) -> QWidget:
        """:meth:`strip` 的多行版：按**固定列数**排成网格，列宽逐行对齐。

        一排灯用 ``strip`` 就行；灯一多会折成两行，这时两行各有各的列宽
        （第一行 6 个、第二行 5 个），看着参差。``block`` 让第二行的灯
        对着第一行的列，才是「阵列」的样子。
        """
        holder = QWidget()
        layout = QGridLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(spacing)
        layout.setVerticalSpacing(2)
        for index, widget in enumerate(widgets):
            layout.addWidget(widget, index // columns, index % columns)
        return holder

    def make_card(self, title: str) -> Card:
        """建一张卡但**先不放进内容区**，用来自己组织并排/嵌套布局。"""
        widget = Card(title)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return widget

    def card(self, title: str, *, weight: int = 1) -> Card:
        widget = self.make_card(title)
        self.body.add(widget, weight)
        return widget

    def grid_cards(self, cards: Sequence[Card], columns: int = 2,
                   weight: int = 2) -> None:
        layout = QGridLayout()
        layout.setSpacing(6)
        for index, card in enumerate(cards):
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
        # 750×948 的排法：从上到下四段，段与段之间按权重分配竖向余量。
        # 权重按各段"需要的高度"分配（129 / 204 / 179 / 79 ≈ 3:5:4:2），富余
        # 竖向空间才会均匀落到每张卡底部；给得悬殊会出现某张卡空一半、
        # 另一张卡挤满的观感。
        status = self.card("设备状态 ｜ device status", weight=3)
        self.add_lamps(status, [
            ("系统运行", "GVL_HMI.wSysRun"),
            ("系统故障", "GVL_HMI.wSysErr", True),
            ("AGV 连接", "GVL_HMI.wAGV_Connected"),
            ("料仓就绪", "GVL_HMI.storageReady"),
            ("手动模式", "GVL_HMI.manual_switch"),
            ("WCS 连接", "GVL.WCS_Connected"),
        ], columns=3)
        self.add_values(status, [
            ("设备模式", "GVL_HMI.wDeviceMode"),
            ("速度倍率", "GVL_HMI.overallRatio", "%"),
            ("CPU 占用", "GVL_HMI.CPU_usage", "%"),
            ("内存占用", "GVL_HMI.MemUsage", "%"),
            ("运行节拍", "GVL_HMI.timestrip_ms", "ms"),
        ], columns=3)

        task = self.make_card("当前任务与节拍")
        self.add_values(task, [
            ("当前任务", "GVL_HMI.current_task"),
            ("上一任务", "GVL_HMI.prev_task"),
            ("执行中", "GVL_HMI.current_task_Executing"),
            ("任务可见", "GVL_HMI.current_task_visible"),
            ("当前应答", "GVL_HMI.currentTaskReply"),
            ("需确认", "GVL_HMI.currentTaskNeedAck"),
            ("主任务平均", "GVL_HMI.avl_main_task_circle_time", "ms"),
            ("主任务最大", "GVL_HMI.max_main_task_circle_time", "ms"),
            ("运动平均", "GVL_HMI.avl_motion_task_exe_time", "us"),
            ("运动最大", "GVL_HMI.max_motion_task_exe_time", "us"),
            ("节拍左", "GVL_HMI.timestrip_left"),
            ("节拍右", "GVL_HMI.timestrip_right"),
        ], columns=2)

        info = self.make_card("系统信息")
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
        ], columns=2)
        self.row(task, info, weight=5)

        control = self.make_card("报警与控制")
        self.add_values(control, [
            ("报警数量", "GVL_HMI.ErrAmount2HMI"),
            ("任意报警（GVL）", "GVL.AnyAlarm"),
            ("当前报警（GVL）", "GVL.CurrentAlarm"),
            ("报警计数（GVL）", "GVL.AlarmCounts"),
            ("报警文本（GVL）", "GVL.CurrentText"),
        ], columns=2)
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        for widget in (
            self.pulse("启动", "GVL_HMI.btn_start"),
            self.pulse("停止", "GVL_HMI.btn_stop", danger=True, confirm=True),
            self.pulse("复位", "GVL_HMI.btn_reset", confirm=True),
            self.pulse("急停", "GVL_HMI.btn_Estop", danger=True, confirm=True),
            self.pulse("清空任务", "GVL_HMI.btnClearAllTask", confirm=True),
        ):
            buttons.addWidget(widget)
        control.grid.addLayout(buttons, control._row, 0, 1, 4)
        control.newline()

        mech = self.make_card("机构与料箱")
        self.add_lamps(mech, [
            ("吸盘开启", "GVL_HMI.bSucker_On"),
            ("臂上有箱", "GVL_HMI.bHasBoxOnArm"),
            ("臂输送有箱", "GVL_HMI.bHasBoxOnArmConvey"),
            ("臂输送正转", "GVL_HMI.bArmConveyRunningPosi"),
            ("臂输送反转", "GVL_HMI.bArmConveyRunningNegi"),
            ("子动画显示", "GVL_HMI.bShowSubAnimation"),
        ], columns=2)
        self.add_values(mech, [
            ("机械手 X", "GVL_HMI.displayArm_x"),
            ("机械手 Y", "GVL_HMI.displayArm_y"),
            ("机械手 Z", "GVL_HMI.displayArm_z"),
            ("臂输送箱位", "GVL_HMI.positionOnArmConvey"),
            ("提示", "GVL_HMI.Tip"),
        ], columns=2)
        self.row(control, mech, weight=4)

        conveyor = self.card("工位输送带 ｜ WorkConvey / 工位有箱", weight=2)
        conveyor.add(self.array("GVL_HMI.WorkConveyRunning", 1, 3, prefix="运行"),
                     row=0, col=0)
        conveyor.add(self.array("GVL_HMI.WorkConveyRunningPosi", 1, 3, prefix="正转"),
                     row=0, col=1)
        conveyor.add(self.array("GVL_HMI.WorkConveyRunningNegi", 1, 3, prefix="反转"),
                     row=1, col=0)
        conveyor.add(self.array("GVL_HMI.displayWorkstationInfo.axHasBox", 1, 3,
                                prefix="有箱"), row=1, col=1)



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
        # 每个轴一张整宽卡片（722px），内部按"灯 / 数值 / 命令 / 写入"分段。
        # 2x2 的半屏卡片试过：357px 里塞 11 灯 + 9 数值 + 11 按钮 + 3 个写入框，
        # 列宽会压到比文字还窄，结果不是切字就是把整页顶出 750。
        for axis in range(1, 5):
            card = self.card(f"轴 {axis} ｜ asServoStatus[{axis}] / asManualServo[{axis}]",
                             weight=4)
            lamps = [
                self.lamp(label, f"GVL_HMI.asServoStatus[{axis}].{field}", alarm=alarm)
                for label, field, alarm in self.STATUS_FIELDS
            ]
            values = [
                self.value(label, f"GVL_HMI.asServoStatus[{axis}].{field}", unit=unit)
                for label, field, unit in self.VALUE_FIELDS
            ]
            manual = [
                self.momentary(text, f"GVL_HMI.asManualServo[{axis}].{field}")
                for text, field in (
                    ("JOG +", "jogPositive"), ("JOG -", "jogNegitive"),
                    ("寸动 +", "InchPositive"), ("寸动 -", "InchNegitive"),
                )
            ]
            commands = [
                self.pulse(text, f"GVL_HMI.asManualServo[{axis}].{field}",
                           confirm=confirm)
                for text, field, confirm in (
                    ("使能", "enable", False), ("回零", "getHome", True),
                    ("停止", "stop", True), ("故障确认", "acknowErr", False),
                    ("定位使能", "absEnable", False), ("定位执行", "absExecute", True),
                    ("速度执行", "velExecute", True),
                )
            ]
            writes = [
                self.writable(text, f"GVL_HMI.asManualServo[{axis}].{field}",
                              unit=unit, label_width=56)
                for text, field, unit in (
                    ("绝对距离", "absDistance", "mm"),
                    ("寸动距离", "inchDistance", "mm"),
                    ("设定速度", "velocity", "mm/s"),
                )
            ]
            # 每段一个容器整行放进卡片：共用一个 QGridLayout 时，6 个灯的
            # 列会被 3 个写入框"共享"，谁都排不下。灯 11 只、数值 9 项会折成
            # 两行，用 block 固定列数（6 / 5）让第二行对着第一行的列。
            card.add(self.block(lamps, 6), row=0, col=0)
            card.add(self.block(values, 5), row=1, col=0)
            card.add(self.strip(manual + commands), row=2, col=0)
            card.add(self.strip(writes), row=3, col=0)

        allow = self.card("点动许可与臂位置", weight=2)
        allow_row = allow._row
        allow.add(self.strip([
            self.array("GVL_HMI.aAllowMoveJogP", 1, 4, prefix="+轴", compact=True),
            self.array("GVL_HMI.aAllowMoveJogN", 1, 4, prefix="-轴", compact=True),
            self.array("GVL.aAllowMoveAxisManual", 1, 3, prefix="手", compact=True),
            self.array("GVL.ArmMotorSpeeds", 1, 3, prefix="速", compact=True),
        ]), row=allow_row, col=0)
        allow.add(self.strip([
            self.value(label, expr) for label, expr in (
                ("臂 X", "GVL_HMI.displayArm_x"),
                ("臂 Y", "GVL_HMI.displayArm_y"),
                ("臂 Z", "GVL_HMI.displayArm_z"),
                ("姿态 X", "GVL_HMI.displayArmPositions.x"),
                ("姿态 Y", "GVL_HMI.displayArmPositions.y"),
                ("姿态 Z", "GVL_HMI.displayArmPositions.z"),
            )
        ]), row=allow_row + 1, col=0)

        speed = self.card("速度倍率与全局设定", weight=2)
        speed.add(self.strip([
            self.writable("速度倍率", "GVL_HMI.overallRatio", unit="%", label_width=64),
            self.writable("全局速度", "GVL_PARAMETERS.speedoverall", label_width=64),
            self.pulse("速度 +", "GVL_HMI.btn_speed_add"),
            self.pulse("速度 -", "GVL_HMI.btn_speed_min"),
        ]), row=speed._row, col=0)


# ======================================================================
# 3. IO 监控页面
# ======================================================================
class IoMonitorPage(HmiPage):
    PAGE_ID = "io"
    TITLE = "IO 监控"
    SUBTITLE = "GVL_HMI · IO / conveys / modebusTCP｜本地 8+8、远程 48+48、执行机构"

    def build(self) -> None:
        # 750 宽：本地 8 点一行放得开；远程 48+48 两块 6×8 灯阵并排（每格 44px，
        # 两块正好 710px），再往下是执行机构、料箱表和寄存器表。
        local = self.card("本地 IO ｜ LOCAL_INPUT / LOCAL_OUTPUT [0..7]", weight=2)
        local.add(self.array("GVL_HMI.LOCAL_INPUT", 1, 8, prefix="DI"), row=0, col=0)
        local.add(self.array("GVL_HMI.LOCAL_OUTPUT", 1, 8, prefix="DO"), row=1, col=0)

        remote = self.card("远程 IO ｜ REMOTE_INPUT / REMOTE_OUTPUT [0..5, 0..7]",
                           weight=5)
        # 灯格只有 40px：里面再写 "RI17" 四个字就会互相压字，序号单独放表头
        remote.add(ElidedLabel("REMOTE_INPUT ｜ RI0–RI47（行 0–5 × 列 0–7）"),
                   row=0, col=0)
        remote.add(ElidedLabel("REMOTE_OUTPUT ｜ RO0–RO47（行 0–5 × 列 0–7）"),
                   row=0, col=1)
        remote.add(self.array("GVL_HMI.REMOTE_INPUT", 6, 8,
                              labels=[str(i) for i in range(48)],
                              compact=True), row=1, col=0)
        remote.add(self.array("GVL_HMI.REMOTE_OUTPUT", 6, 8,
                              labels=[str(i) for i in range(48)],
                              compact=True), row=1, col=1)
        remote.add(ElidedLabel(
            "输出点为数组整体节点，没有逐元素 NodeId；只读展示，不做单点强制写"),
            row=2, col=0, span=2)

        actuator = self.make_card("执行机构 ｜ 吸盘 / 输送 / 料仓")
        self.add_lamps(actuator, [
            ("吸盘开启", "GVL_HMI.bSucker_On"),
            ("臂上有箱", "GVL_HMI.bHasBoxOnArm"),
            ("臂输送有箱", "GVL_HMI.bHasBoxOnArmConvey"),
            ("臂输送正转", "GVL_HMI.bArmConveyRunningPosi"),
            ("臂输送反转", "GVL_HMI.bArmConveyRunningNegi"),
            ("料仓就绪", "GVL_HMI.storageReady"),
        ], columns=4)
        buttons_row = actuator._row
        for index, (text, expr) in enumerate((
            ("真空开", "GVL_HMI.btn_vacuumize"),
            ("左正转", "GVL_HMI.btnFwd_left"),
            ("左反转", "GVL_HMI.btnRev_left"),
            ("中正转", "GVL_HMI.btnFwd_mid"),
            ("中反转", "GVL_HMI.btnRev_mid"),
            ("右正转", "GVL_HMI.btnFwd_right"),
            ("右反转", "GVL_HMI.btnRev_right"),
        )):
            # 半屏宽只有 357px：7 个按钮排一行要 490px，分成 4+3 两行。
            actuator.add(self.momentary(text, expr),
                         row=buttons_row + index // 4, col=index % 4)
        # add(row=...) 已经把游标推到最后一个按钮行的下一行，不用再 newline()
        grid_row = actuator._row
        actuator.add(self.array("GVL_HMI.WorkConveyRunning", 1, 3, prefix="运"),
                     row=grid_row, col=0, span=2)
        actuator.add(self.array("GVL_HMI.WorkConveyRunningPosi", 1, 3, prefix="正"),
                     row=grid_row, col=2, span=2)
        actuator.newline()

        box = self.make_card("工位料箱 ｜ boxInfoOnWorkstation[0..2]")
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

        modbus = self.make_card("Modbus TCP 保持寄存器 ｜ HoldResisterIn / Out")
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

        self.row(actuator, box, weight=4)
        self.body.add(modbus, 7)

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
        # 写入行统一「标签 / 当前值 / 输入框 / 写」，一行 26px；750 宽下
        # 两张并排太窄，参数列表一律整行两列。
        sucker = self.card("工艺参数 ｜ GVL_PARAMETERS（GVL 镜像）", weight=4)
        for row, (label, name, unit) in enumerate(self.SUCKER_PARAMS):
            sucker.add(self.writable(label, f"GVL_PARAMETERS.{name}", unit=unit,
                                     label_width=76),
                       row=row // 2, col=(row % 2) * 2, span=2)

        pose = self.card("示教位置与相机标定 ｜ GVL_PARAMETERS", weight=7)
        for row, (label, name, unit) in enumerate(self.POSE_PARAMS):
            pose.add(self.writable(label, f"GVL_PARAMETERS.{name}", unit=unit,
                                   label_width=76),
                     row=row // 2, col=(row % 2) * 2, span=2)

        transfer = self.make_card("参数下发 / 恢复")
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addWidget(self.pulse("下发", "GVL_PARAMETERS.btn_do", confirm=True))
        buttons.addWidget(self.pulse("恢复", "GVL_PARAMETERS.btn_undo", confirm=True))
        transfer.grid.addLayout(buttons, 0, 0, 1, 2)
        transfer.newline()
        self.add_lamps(transfer, [
            ("下发完成", "GVL_HMI.ParamsTransferDone"),
            ("恢复完成", "GVL_HMI.ParamsRecoverDone"),
        ], columns=2)

        camera = self.make_card("相机状态 ｜ CameraDatas")
        self.add_lamps(camera, [
            ("就绪", "GVL_HMI.CameraDatas.xReady"),
            ("忙", "GVL_HMI.CameraDatas.xBusy"),
            ("故障", "GVL_HMI.CameraDatas.xError", True),
            ("解析成功", "GVL_HMI.CameraDatas.xParseOK"),
        ], columns=2)
        self.add_values(camera, [
            ("错误码", "GVL_HMI.CameraDatas.eErrorID"),
            ("偏移 X", "GVL_HMI.CameraDatas.rOffsetX"),
            ("偏移 Y", "GVL_HMI.CameraDatas.rOffsetY"),
            ("偏移角", "GVL_HMI.CameraDatas.rOffsetAngle"),
        ], columns=2)
        self.row(transfer, camera, weight=4)

        teach = self.card("示教与定位 ｜ GVL_HMI / teach", weight=2)
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

        gvl = self.card("GVL 本体 ｜ 当前未暴露 OPC UA 节点（待重新浏览导出）", weight=3)
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
        summary = self.card("报警汇总", weight=1)
        self.add_values(summary, [
            ("报警数量", "GVL_HMI.ErrAmount2HMI"),
            ("系统故障", "GVL_HMI.wSysErr"),
            ("任意报警（GVL）", "GVL.AnyAlarm"),
            ("当前报警（GVL）", "GVL.CurrentAlarm"),
            ("报警计数（GVL）", "GVL.AlarmCounts"),
            ("报警文本（GVL）", "GVL.CurrentText"),
        ], columns=3)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addWidget(self.pulse("报警复位", "GVL_HMI.btn_reset", confirm=True))
        buttons.addWidget(self.pulse("停止", "GVL_HMI.btn_stop", danger=True, confirm=True))
        summary.grid.addLayout(buttons, summary._row, 0, 1, 4)
        summary.newline()

        table_card = self.card("报警列表 ｜ ST_AlarmShow × 10", weight=4)
        self._table = DataTable(("#", "报警码", "时间戳", "分类", "文本", "可见"), 10,
                                row_height=20)
        table_card.add(self._table, row=0, col=0, span=4)
        self._rows = [[str(i)] + ["--"] * 5 for i in range(10)]
        for i in range(10):
            for col, (field, label) in enumerate(self.FIELDS, start=1):
                ref = self.catalog.member_ref("GVL_HMI.Alarms2HMII", field,
                                              index=i, label=label)
                self.watch(ref, self._make_setter(i, col))
        self._table.set_rows(self._rows)

        log_card = self.card("客户端事件（连接 / 写入 / 错误）", weight=6)
        self.client_log = LogView()
        self.client_log.setMinimumHeight(140)
        log_card.add(self.client_log, row=0, col=0, span=4)

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
        rcd = self.card("PLC 记录 ｜ rcd_texts[0..9]", weight=5)
        self._rcd_view = LogView()
        self._rcd_view.setMinimumHeight(200)
        rcd.add(self._rcd_view, row=0, col=0, span=4)
        self.watch(self.catalog.ref("GVL_HMI.rcd_texts", label="记录文本"),
                   lambda value: self._rcd_view.set_lines(array_items(value, 10)[:10]))
        page_row = QHBoxLayout()
        page_row.setSpacing(6)
        page_row.addWidget(self.value("记录页码", "GVL_HMI.rcd_page"), 1)
        page_row.addWidget(self.writable("翻页", "GVL_HMI.rcd_page", label_width=40), 2)
        rcd.grid.addLayout(page_row, 1, 0, 1, 4)

        runtime = self.card("运行统计 ｜ GVL_HMI / Info", weight=4)
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

        client = self.card("客户端事件日志", weight=5)
        self.client_log = LogView()
        self.client_log.setMinimumHeight(150)
        client.add(self.client_log, row=0, col=0, span=4)
        self.add_values(client, [
            ("提示信息", "GVL_HMI.Tip"),
            ("工程描述", "GVL_HMI.工程描述"),
            ("作者", "GVL_HMI.Author"),
        ], columns=3)

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
        code = self.card("程序文本 ｜ prg_texts[0..13]", weight=6)
        self._code_view = LogView()
        self._code_view.setMinimumHeight(190)
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
        nav.setSpacing(6)
        nav.addWidget(self.value("页码", "GVL_HMI.prg_page"), 1)
        nav.addWidget(self.value("执行行", "GVL_HMI.current_exe_line"), 1)
        nav.addWidget(self.value("行偏移", "GVL_HMI.exe_line_offset"), 1)
        nav.addWidget(self.pulse("上一页", "GVL_HMI.btn_prg_page_prev"))
        nav.addWidget(self.pulse("下一页", "GVL_HMI.btn_prg_page_next"))
        code.grid.addLayout(nav, 1, 0, 1, 4)
        self._refresh_code()

        tasks = self.make_card("任务队列 ｜ taskList[0..9] / btnCancelTask")
        self._task_table = DataTable(("#", "任务文本", "当前", "上一"), 10)
        tasks.add(self._task_table, row=0, col=0, span=4)
        self._task_lines: list[str] = ["--"] * 10
        self.watch(self.catalog.ref("GVL_HMI.taskList", label="任务队列"),
                   self._set_tasks)
        tasks.add(self.array("GVL_HMI.btnCancelTask", 2, 5, prefix="取消 ",
                             compact=True), row=1, col=0, span=4)
        tasks.grid.addWidget(self.pulse("清空全部任务", "GVL_HMI.btnClearAllTask",
                                        confirm=True), tasks._row, 0, 1, 4)
        tasks.newline()

        command = self.make_card("命令与应答 ｜ GVL_HMI / test")
        for index, (label, name) in enumerate((
            ("命令 ID", "cmd_id"), ("方向", "cmd_dir"),
            ("源行", "cmd_src_storage_row"), ("源列", "cmd_src_storage_col"),
            ("目标行", "cmd_dest_storage_row"), ("目标列", "cmd_dest_storage_col"),
            ("源工位", "cmd_src_workstation"), ("目标工位", "cmd_dest_workstation"),
            ("应答 ID", "ack_id"),
        )):
            command.add(self.writable(label, f"GVL_HMI.{name}", label_width=64),
                        row=index, col=0, span=4)
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        buttons.addWidget(self.pulse("添加命令", "GVL_HMI.cmd_add", confirm=True))
        buttons.addWidget(self.pulse("应答", "GVL_HMI.ack", confirm=True))
        buttons.addWidget(self.pulse("启动", "GVL_HMI.btn_start"))
        buttons.addWidget(self.pulse("停止", "GVL_HMI.btn_stop", danger=True, confirm=True))
        command.grid.addLayout(buttons, 9, 0, 1, 4)
        command.newline()
        self.row(tasks, command, weight=7)

        state = self.make_card("任务状态与应答")
        self.add_values(state, [
            ("当前任务", "GVL_HMI.current_task"),
            ("上一任务", "GVL_HMI.prev_task"),
            ("当前执行中", "GVL_HMI.current_task_Executing"),
            ("上一执行中", "GVL_HMI.prev_task_Executing"),
            ("当前应答", "GVL_HMI.currentTaskReply"),
            ("上一应答", "GVL_HMI.prevTaskReply"),
            ("当前需确认", "GVL_HMI.currentTaskNeedAck"),
            ("上一需确认", "GVL_HMI.prevTaskNeedAck"),
            ("当前可见", "GVL_HMI.current_task_visible"),
        ], columns=2)

        workstation = self.make_card("工位任务状态")
        workstation.add(self.array("GVL_HMI.aWorkstationTaskReq", 1, 3,
                                   prefix="请求 ", compact=True), row=0, col=0, span=4)
        workstation.add(self.array("GVL_HMI.aWorkstationTaskInQueue", 1, 3,
                                   prefix="队列 ", compact=True), row=1, col=0, span=4)
        self._src_table = DataTable(("工位", "行", "列", "任务号", "类型"), 3)
        workstation.add(self._src_table, row=2, col=0, span=4)
        self._src_rows = [[str(i), "--", "--", "--", "--"] for i in range(3)]
        for i in range(3):
            for col, field in enumerate(("row", "col", "TaskNo", "storageType"), start=1):
                ref = self.catalog.member_ref("GVL_HMI.aWorkstationSrcPosition", field,
                                              index=i, label=field)
                self.watch(ref, self._make_src_setter(i, col))
        self._src_table.set_rows(self._src_rows)
        self.row(state, workstation, weight=4)

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
