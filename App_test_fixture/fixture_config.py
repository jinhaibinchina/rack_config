"""test_fixture 运行态的全部可调参数。

标 ``★`` 的是从场景/工艺推出来的**默认值**，接真实 Modbus 前请按现场确认。
其余几何锚点（导轨上下沿、三个光电的 y、滑块初始中心与尺寸）不写死，
由 :func:`fixture_runtime.derive_geometry` 从 JSON 现场推导，改了场景不用改代码。

导入本模块不会碰 ``binding.py`` / ``pages.py`` / ``widgets.py`` 那套旧 HMI 代码。
"""

from __future__ import annotations

from pathlib import Path

# 项目根 = App_test_fixture/ 的上一级
ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- 页面 / 框架
PAGE_PATH = ROOT / "res" / "myDesigner" / "scene" / "test_fixture.json"
GEOMETRY_PROFILE = "rack"     # 旧 Core 场景口径（AABB 角点）；本页 rotate 全 0
WIDGET_MODE = "host"          # 自建 proxy，不调核心 set_scene_mode(True)
FIT_MODE = "fit"              # sceneRect=0 时由框架回退到内容包围盒
FLUSH_MS = 80                 # TagBus 合流间隔
WINDOW_SIZE = (1100, 820)
WINDOW_TITLE = "工装轴监控 · test_fixture"

# ---------------------------------------------------------------- 点位名
# 这些是**逻辑名**，不是 Modbus 地址。接现场时只需在 datasource 的
# register_map 里把它们映射到 (unit, address, type, scale)，业务代码不用改。
TAG = {
    "position": "axis.position_mm",
    "neg_limit": "axis.neg_limit",
    "home": "axis.home",
    "pos_limit": "axis.pos_limit",
    "reduction": "axis.reduction",
    "speed": "axis.speed",
    "neg_pos": "axis.neg_pos",
    "pos_pos": "axis.pos_pos",
    "home_count": "axis.home_count",
    "home_count_now": "axis.home_count_now",
    "total_count": "axis.total_count"

}

# ---------------------------------------------------------------- 图元名
EL = {
    "slider": "滑块",                       # group 109，整体平移
    "rail": "工装_矩形_4",                  # 导轨，用来夹住滑块行程
    "lamp_neg": "工装_负极限光电",
    "lamp_home": "工装_原点光电",
    "lamp_pos": "工装_正极限光电",
    # 新增的两个计数显示 text 图元：JSON 里 name 就是这两个英文串，
    # **不是**「回零计数」/「总计数」——那是标签文字，写在 文本_117 里。
    # element_of() 按 name 查，写错会静默返回 None，界面就一直停在 ### 。
    "home_count_now": "home_count_now",     # id 123，context="###"
    "total_count": "total_count",           # id 124，context="#####"
}


# ---------------------------------------------------------------- text 图元绑定
# (TAG 短名, EL 键, 小数位)：运行态把 Modbus / Demo 点位值写进 text 图元显示。
# 新增计数 / 数值显示图元时只在这里加一行，FixtureRuntime 的业务代码不用动。
# 小数位 0 = 按整数显示；对应寄存器类型见下方 MODBUS_REGISTER_MAP
# （home_count_now → int16 @ offset 201，total_count → uint32 @ offset 202）。
TEXT_BINDINGS = (
    ("home_count_now", "home_count_now", 0),
    ("total_count", "total_count", 0),
)




WIDGET = {
    "monitor": "电机监控窗口",              # 挂伺服轴监控面板（见 servo_panel.py）
    "reduction": "reduction",              # spinbox：每转位移量 mm
    "speed": "speed",                      # spinbox：电机转速 mm/s
    "neg_pos": "negitive_pos",             # spinbox：负向终点（注意 JSON 里拼写）
    "pos_pos": "positive_pos",             # spinbox：正向终点
    "home_count": "home_count",            # spinbox：回零次数
}

# spinbox 的 widgetText 为空 → 核心默认 range 很窄，这里统一放大
SPIN_RANGE = (-1_000_000, 1_000_000)

# ★ 5 个参数初值。运行时以控件当前值为准，用户改动会回写给数据源。
PARAM_DEFAULTS = {
    "reduction": 10,      # 每转位移量 mm/转
    "speed": 50,         # 电机转速 mm/s
    "neg_pos": -100,     # 负向终点 mm
    "pos_pos": 100,      # 正向终点 mm
    "home_count": 0,     # 回来多少次回零
}

# ★ 工程行程（mm）。position 落在这个区间内线性映射到导轨上的 y。
#    实际映射的上下限会改用 pos_pos / neg_pos 两个 spinbox 的当前值，
#    所以现场只要把这两个框填对，滑块就自动对齐。
POS_MM_FALLBACK = 100.0
NEG_MM_FALLBACK = -100.0
POSITION_CLAMP = True     # 越行程时把滑块夹在导轨内，而不是画出界

# ★ 滑块端点的对齐口径。
#    True  —— 端点内缩半个滑块高，保证滑块整块都在导轨里（当前默认，
#             实测 y∈[7859.9, 10324.6]）；
#    False —— 端点严格取「正/负极限光电」的中心 y（7897 / 10291 附近），
#             滑块到端点时会稍微探出导轨，适合挡片式光电。
#    现场看哪种更贴合机械实际就改这里，不用改代码。
SLIDER_INSET_TO_RAIL = True

# ---------------------------------------------------------------- 视觉
LAMP_OFF = "#4a5a6d"
LAMP_BORDER_OFF = "#2b3d52"
LAMP_ON = {
    "neg_limit": "#ff5f6d",
    "home": "#36d08a",
    "pos_limit": "#ff5f6d",
}
LAMP_BORDER_ON = "#ffffff"

# ---------------------------------------------------------------- 伺服轴监控面板
# 「电机监控窗口」widget 图元上挂载的面板（servo_panel.py）。字段名与
# App_test_fixture/pages.py 的 AxisMonitorPage 逐项一致，接 OPC UA 时这些
# 表达式可直接交给 TagCatalog 解析；在新框架里它们就是 TagBus 的逻辑点位名。
# 面板不 import 旧 pages.py / widgets.py：那套是 750×1000 的 HmiPage 外壳，
# 且依赖 App_test_fixture/data/ 下并不存在的节点导出文件。
AXIS_INDEX = 1                          # ★ 轴号，截图是「轴 1」
AXIS_STATUS_VAR = "GVL_HMI.asServoStatus"
AXIS_MANUAL_VAR = "GVL_HMI.asManualServo"

# (标签, 结构体成员, 是否报警灯)
AXIS_STATUS_FIELDS = (
    
    ("驱动就绪", "xDriveReady", False),
    ("故障", "xErr", True),
    
    ("已使能", "xEnabled", False),
    ("故障停机", "xErrStop", True),
    
    ("回零完成", "xHomeDone", False),
     ("静止", "xStandStill", False),

    ("负限位", "xNegLimit", True),
    ("参考点", "xReference", False),
    ("正限位", "xPosLimit", True),
   
    ("定位完成", "xLocDone", False),
    
    
)
# (标签, 结构体成员, 单位)
AXIS_VALUE_FIELDS = (
    ("当前位置", "fPositionNow", "mm"),
    ("当前速度", "fVelocityNow", "mm/s"),
    ("状态码", "iState", ""),
    ("驱动错误码", "sDriverErrorID", ""),
    
)
# (标签, 成员, 是否需要二次确认)：按住写 True、松开写 False 的点动按钮。
# 带确认的三项（定位执行 / 速度执行 / 回零）确认后发 True→False 脉冲。
AXIS_MOMENTARY_FIELDS = (

    ("JOG +", "jogPositive", False), ("JOG -", "jogNegitive", False),
    ("寸动 +", "InchPositive", False), ("寸动 -", "InchNegitive", False),
    ("定位执行", "absExecute", False),
    ("    ", "absEnable", False),
    ("速度执行", "velExecute", False),
    ("    ", "velEnable", False),
    ("回零", "getHome", False),
    ("停止", "stop", False),
    ("故障确认", "acknowErr", False),
)
# (标签, 成员, 是否需要二次确认)：点一下写 True，PLC 侧自复位
AXIS_COMMAND_FIELDS = (
    ("使能", "enable", False),
)
# (标签, 成员, 单位)：当前值 + 新值输入 + 「写」
AXIS_WRITE_FIELDS = (
    ("寸动距离", "inchDistance", "mm"),
    ("绝对距离", "absDistance", "mm"),
    ("设定速度", "velocity", "mm/s"),
)

# 面板外观（逻辑像素；视图还会再乘 fit_scene 的缩放，当前约 0.79）
PANEL_BG = "#dbe6f3"
PANEL_BORDER = "#7b8ea8"
PANEL_TEXT = "#2c3a4c"
PANEL_MUTED = "#7c8ea5"
PANEL_LAMP_OFF = "#4a5a6d"          # 无数据 / False 都是深灰
PANEL_LAMP_ON = "#36d08a"
PANEL_LAMP_ALARM = "#ff5f6d"
PANEL_BTN_BG = "#eef3fa"
PANEL_FONT_PX = 11                  # 基础字号，标题单独放大
PANEL_TITLE_PX = 14
PANEL_SHOW_STATUS = True            # 底部一条最近消息（不占截图主布局）
PANEL_CONFIRM = True                # 危险命令走页面内确认条，不弹模态框


def axis_status_key(field: str, index: int | None = None) -> str:
    """``GVL_HMI.asServoStatus[1].xConnected``。"""
    return f"{AXIS_STATUS_VAR}[{AXIS_INDEX if index is None else index}].{field}"


def axis_manual_key(field: str, index: int | None = None) -> str:
    """``GVL_HMI.asManualServo[1].enable``。"""
    return f"{AXIS_MANUAL_VAR}[{AXIS_INDEX if index is None else index}].{field}"


def axis_display_keys() -> tuple[str, ...]:
    """面板要订阅显示的点位（灯 / 数值 / 写入行当前值）。"""
    return tuple(
        [axis_status_key(f) for _, f, _ in AXIS_STATUS_FIELDS]
        + [axis_status_key(f) for _, f, _ in AXIS_VALUE_FIELDS]
        + [axis_manual_key(f) for _, f, _ in AXIS_WRITE_FIELDS]
    )


def axis_command_keys() -> tuple[str, ...]:
    """面板只写的点位（点动 / 命令 / 写入动作）。"""
    return tuple(
        [axis_manual_key(f) for _, f ,_ in AXIS_MOMENTARY_FIELDS]
        + [axis_manual_key(f) for _, f, _ in AXIS_COMMAND_FIELDS]
        + [axis_manual_key(f) for _, f, _ in AXIS_WRITE_FIELDS]
    )


def known_keys() -> frozenset[str]:
    """数据源允许收发的全部逻辑点位名。

    ``ModbusDataSource.submit`` 用它过滤外部推送，``DemoDataSource`` 用它
    生成模拟值；新增字段时不用再改数据源代码。
    """
    return frozenset(
        list(TAG.values()) + list(axis_display_keys()) + list(axis_command_keys())
    )


# ---------------------------------------------------------------- 模拟数据源
DEMO_INTERVAL_MS = 200        # 模拟推送周期
DEMO_AMPLITUDE_MM = 95.0      # 往复幅度（配合默认 ±100 行程）
DEMO_PERIOD_MS = 6000         # 一个往复周期

# ---------------------------------------------------------------- Modbus（40001 起）
# 现场数据区从保持寄存器 40001 开始。表里一律写「相对 40001 的**字偏移**」：
#     offset=0 → 40001，offset=2 → 40003；float32 占 2 个字（40003、40004）。
# 整个数据区平移只需改 MODBUS_START 一处，不用逐行重算地址。
#
# ★ 地址口径（最容易踩的坑）：
#   common/com/modbus 的 PLCManager.read_data / ModbusClient.read_holding_registers
#   用的是 pymodbus 的 0-based 协议地址，而 40001 是 4xxxx 编号。
#   "4xxxx" —— 40001 换算成协议地址 0（Modicon / 绝大多数 PLC，默认）；
#   "raw"   —— 直接把 40001 发给设备（部分国产 PLC / 网关按编号寻址）。
#   连上后读出来全是 0 或天文数字，先翻这个开关再查字节序。
MODBUS_START = 40001            # ★ 数据区首寄存器（4xxxx 编号）
MODBUS_ADDRESS_MODE = "4xxxx"   # ★ "4xxxx" | "raw"
MODBUS_UNIT = 1                 # ★ 从站号 device_id
MODBUS_IP = "192.168.1.88"                  # ★ 留空 = 不自动连设备；填 IP 或 --ip 才真正连接
MODBUS_PORT = 502
MODBUS_TIMEOUT = 1.0
MODBUS_USE_PLC_MANAGER = True  # True → 改用 PLCManager（带心跳 / 断线重连）
# ★ 浮点/LREAL 的寄存器字序。现场实测 12.5 = [0, 0, 0, 0x4029]：低字在前，
#   但每个字内部仍是大端字节（0x4029 不是 0x2940）。"little" = 整个字列表反序，
#   对 float32(2 字) / double64(4 字) 统一生效；若设备是高字在前再改回 "big"。
MODBUS_FLOAT_WORD_ORDER = "little"
MODBUS_POLL_MS = 200


def _reg(offset: int, type_: str, *, scale: float = 1.0, access: str = "r",
         bit: int | None = None,byte: int | None = None, words: int = 1, note: str = "") -> dict:
    """一条「点位 → 寄存器」描述；``offset`` 是相对 ``MODBUS_START`` 的字偏移。"""
    spec = {"offset": int(offset), "type": type_, "scale": float(scale),
            "unit": MODBUS_UNIT, "access": access}
    if bit is not None:
        spec["bit"] = int(bit)
    if byte is not None:
        spec["byte"] = int(byte)
    if type_ == "string":
        spec["words"] = int(words)
    if note:
        spec["note"] = note
    return spec


def _build_register_map() -> dict[str, dict]:
    """默认布局：40001~40049 共 49 字，覆盖 known_keys() 的全部 43 个点位。

    现场布局不同时，改下面的 offset 或用 ``MODBUS_REGISTER_OVERRIDES`` 覆盖
    个别点位；业务代码、面板和联动一行都不用动。
    """
    st, ma = axis_status_key, axis_manual_key
    m: dict[str, dict] = {}

    # 40001 伺服状态字：11 个 BOOL 压在一个字里，bit0..bit10
    for byte, (_, field, _) in enumerate(AXIS_STATUS_FIELDS):
        m[st(field)] = _reg(byte/2+ 112, "byte", byte= byte % 2, note="伺服状态字 40101")
    # 40002 工装光电字：bit0 负极限 / bit1 原点 / bit2 正极限

    m[TAG["neg_limit"]] = _reg(3+ 112, "byte", byte=0, note="工装光电字 40101")
    m[TAG["home"]]      = _reg(3+ 112, "byte", byte=1, note="工装光电字 40101")
    m[TAG["pos_limit"]] = _reg(4+ 112, "byte", byte=0, note="工装光电字 40101")
   

    # 40003~40032 只读数值（float32 占 2 字）
    m[st("fPositionNow")] = _reg(100, "double64", note="滑块与面板位置同源")
    m[TAG["position"]] = _reg(100, "double64", note="滑块与面板位置同源")
    m[st("fVelocityNow")] = _reg(104, "double64")
    m[st("iState")] = _reg(108, "double64")
    m[st("sDriverErrorID")] = _reg(110, "uint16")

    # 两个新增 text 图元的数据源（见 TEXT_BINDINGS）：
    # home_count_now → int16 占 1 字；total_count → uint32 占 2 字（202~203）。
    # uint32 不需要 words 参数（那只对 string 生效）；若 PLC 的 DWORD 是
    # 高字在前，用 MODBUS_REGISTER_OVERRIDES 给这个点位单独设 word_order="big"。
    m[TAG["home_count_now"]] = _reg(201, "int16", note="回零计数")
    m[TAG["total_count"]]    = _reg(202, "uint32", note="总计数")


   
    for offset, short in ((1120, "reduction"), (1108, "speed"),
                          (1100, "neg_pos"), (1104, "pos_pos")):
        m[TAG[short]] = _reg(offset, "double64", access="rw")
    m[TAG["home_count"]] = _reg(1130, "uint16", access="rw")

    # 40033~40038 面板三组写入行的当前值（可读可写）
    for offset, (_, field, _) in zip((0, 4, 8), AXIS_WRITE_FIELDS):
        m[ma(field)] = _reg(offset, "double64", access="rw")

    # 40039~40049 命令：一个 BOOL 占一个字，直接写 1 / 0。
    # 不做位打包——两个点动同时按住时位打包会互相覆盖，还要读-改-写。
    for offset, (_, field, _) in enumerate(AXIS_COMMAND_FIELDS +
            AXIS_MOMENTARY_FIELDS ):
        m[ma(field)] = _reg(offset /2 +12, "byte", access="w",byte=offset % 2)  

    
        
    return m


MODBUS_REGISTER_MAP: dict[str, dict] = _build_register_map()

# ★ 现场只改少数几项时用这个覆盖，不必动上面的默认布局（可只写 offset）：
#   MODBUS_REGISTER_OVERRIDES = {"axis.speed": {"offset": 60, "type": "int16"}}
MODBUS_REGISTER_OVERRIDES: dict[str, dict] = {}
for _key, _patch in MODBUS_REGISTER_OVERRIDES.items():
    MODBUS_REGISTER_MAP.setdefault(_key, {}).update(_patch)
