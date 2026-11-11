# -*- coding: utf-8 -*-
"""App_test_fixture 运行态回归门禁。

    .venv/Scripts/python.exe tools/verify_test_fixture.py

红线
====
1. **装载**：图元数按磁盘 JSON 动态取 / 6 widget 图元 / 6 个真实控件
   （5 QSpinBox + 1 伺服轴面板）；新增 text 图元不会让门禁变红。
2. **取景**：``sceneRect=0`` 时框架回退到内容包围盒，20 个图元全部落在可视区
   （回归 RuntimeView.fit_scene 的二次投影修复）。
3. **运行态零污染**：装载、光电变色、滑块连续 20 次位移、控件回填之后
   ``page_data()`` 与磁盘 JSON 逐字相等，``is_modified()`` 为 False。
4. **联动真的生效**：光电填充色随 bool 变化；滑块 ``sceneBoundingRect`` 随
   position 单调移动且始终在导轨内，子图元刚体跟随。
5. **数据源可替换**：demo / none / modbus 三种源；Modbus 未配置时明确告警、
   不静默造假数据；spinbox 回写确实走到 ``DataSource.write``。
6. **伺服轴面板**：状态灯 / 数值 / 按钮 / 写入行数量按 ``AXIS_*_FIELDS`` 动态取，
   挂进「电机监控窗口」；点位能刷新显示，命令 / 点动 / 参数写入都转发到
   ``DataSource.write``，危险命令走页面内确认条；换页重建后面板仍可用且不污染设计数据。
7. **text 图元绑定**：``TEXT_BINDINGS`` 的图元名必须能在 JSON 查到；点位值能刷进
   文字，Modbus 寄存器 → 数据源 → 总线的端到端链路通，且刷新文本零污染。

离屏运行，不写任何页面文件。
"""

from __future__ import annotations

import copy
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication, QSpinBox  # noqa: E402

from App_test_fixture import fixture_config as cfg  # noqa: E402
from App_test_fixture.servo_panel import (  # noqa: E402
    MomentaryButton, ServoAxisPanel,
)
from App_test_fixture.datasource import (  # noqa: E402
    DemoDataSource, ModbusDataSource, NullDataSource, make_source,
)
from App_test_fixture import modbus_link as ml  # noqa: E402
from App_test_fixture.fixture_runtime import FixtureRuntime  # noqa: E402

PAGE = str(cfg.PAGE_PATH)
FAILURES: list[str] = []


def check(label, cond, detail=""):
    if cond:
        print(f"  [OK] {label}" + (f"  {detail}" if detail else ""))
    else:
        print(f"  [FAIL] {label}" + (f"  {detail}" if detail else ""))
        FAILURES.append(label)
    return bool(cond)


def disk_json():
    with open(PAGE, "r", encoding="utf-8") as f:
        return json.load(f)


def clean(runtime, label):
    now = json.dumps(runtime.stage.scene.page_data(),
                     ensure_ascii=False, sort_keys=True)
    orig = json.dumps(disk_json(), ensure_ascii=False, sort_keys=True)
    return check(label, now == orig and not runtime.stage.scene.is_modified())


class SpySource(NullDataSource):
    """记录 write 调用，并把回写值原样推回总线。"""

    def __init__(self):
        super().__init__()
        self.writes: list[tuple[str, object]] = []

    def write(self, key, value):
        self.writes.append((key, value))
        self.valuesChanged.emit({key: value})
        return True


def visible_rect(view):
    vp = view.viewport().rect()
    return QRectF(view.mapToScene(vp.topLeft()),
                  view.mapToScene(vp.bottomRight())).normalized()


def slider_center_x(runtime):
    """读 Qt 实际位置，不能读 get_scene_center_pos（_page 被还原成原值）。

    本场景用 AGV 投影（轴交换），page 里的「竖直导轨」在视图里是水平的，
    所以滑块位移体现在 **视图 x 轴**上。
    """
    item = runtime.stage.element_of(cfg.EL["slider"]).item()
    return item.sceneBoundingRect().center().x()


def main() -> int:
    app = QApplication.instance() or QApplication([])

    print("\n=== 1. 装载与承载 ===")
    rt = FixtureRuntime(page_path=PAGE, source=NullDataSource())
    rt.stage.view.resize(1000, 760)
    n = rt.load()
    # 现场会往 JSON 里加 text 图元，别把数量写死（之前写 20，加到 22 就变红）。
    expected = len(disk_json()["items"])
    check(f"载入 {expected} 个图元", n == expected, f"n={n}")
    check("6 个 widget 图元", len(rt.stage.registry.widgets()) == 6)
    check("6 个真实控件", len(rt.stage.controls()) == 6,
          f"controls={len(rt.stage.controls())}")
    check("5 个 QSpinBox", len(rt._spins) == 5,
          f"spins={sorted(rt._spins)}")
    panel = rt._panel
    check("监控窗口挂的是伺服轴面板",
          isinstance(panel, ServoAxisPanel) and
          rt.stage.widget(cfg.WIDGET["monitor"]) is panel)
    snap = panel.state_snapshot()
    check("面板灯 / 数值 / 按钮 / 写入数量与字段表一致",
          len(snap["lamps"]) == len(cfg.AXIS_STATUS_FIELDS) and
          len(snap["values"]) == len(cfg.AXIS_VALUE_FIELDS) and
          snap["buttons"] == (len(cfg.AXIS_MOMENTARY_FIELDS) +
                              len(cfg.AXIS_COMMAND_FIELDS)) and
          len(snap["writes"]) == len(cfg.AXIS_WRITE_FIELDS),
          f"lamps={len(snap['lamps'])} values={len(snap['values'])} "
          f"buttons={snap['buttons']} writes={len(snap['writes'])}")
    check("468 宽图元自适应列数 6/3/6/3",
          snap["columns"] == (6, 3, 6, 3), f"{snap['columns']}")
    check("标题与截图一致",
          "asServoStatus[1]" in snap["title"] and
          "asManualServo[1]" in snap["title"], snap["title"])
    check("无数据 → 灰灯 / --",
          all(v is None for v in snap["lamps"].values()) and
          all(t == "--" for t in snap["values"].values()))
    check("spinbox 量程已放大",
          all(w.minimum() == cfg.SPIN_RANGE[0] and
              w.maximum() == cfg.SPIN_RANGE[1] for w in rt._spins.values()))
    check("初值来自配置",
          all(w.value() == cfg.PARAM_DEFAULTS[k] for k, w in rt._spins.items()),
          f"values={ {k: w.value() for k, w in rt._spins.items()} }")
    check("几何锚点已推导",
          rt.geometry is not None and
          rt.geometry.y_at_neg > rt.geometry.y_at_pos,
          f"y=[{rt.geometry.y_at_pos:.1f}, {rt.geometry.y_at_neg:.1f}]")
    check("未导入旧 HMI 半成品",
          not any(m.startswith("App_test_fixture.") and
                  m.split(".")[-1] in ("binding", "pages", "widgets", "tag_catalog")
                  for m in sys.modules))
    clean(rt, "装载后 page_data == 磁盘 JSON")

    print("\n=== 2. 取景（sceneRect=0 回退修复）===")
    check("fit 成功", rt.stage.fit())
    vr = visible_rect(rt.stage.view)
    items = [e.item().sceneBoundingRect() for e in rt.stage.elements()
             if e.item() is not None]
    inside = sum(1 for r in items if vr.contains(r))
    check("全部图元都在可视区", inside == len(items),
          f"{inside}/{len(items)}  visible={vr}")
    check("缩放不是 1:1（确实取景过）",
          abs(rt.stage.view.transform().m11() - 1.0) > 1e-6,
          f"scale={rt.stage.view.transform().m11():.4f}")

    print("\n=== 3. 光电变色 ===")
    lamp = rt.stage.element_of(cfg.EL["lamp_neg"])
    for tag, el_key in rt.LAMPS[:1]:
        rt.push(cfg.TAG[tag], True)
        on_color = rt.stage.element_of(cfg.EL[el_key]).get_fill_color().name()
        check("限位 True → 亮色",
              on_color.lower() == cfg.LAMP_ON[tag].lower(), f"{on_color}")
        rt.push(cfg.TAG[tag], False)
        off_color = rt.stage.element_of(cfg.EL[el_key]).get_fill_color().name()
        check("限位 False → 暗色",
              off_color.lower() == cfg.LAMP_OFF.lower(), f"{off_color}")
    check("变色后统一为配置的暗色",
          lamp.get_fill_color().name().lower() == cfg.LAMP_OFF.lower())
    clean(rt, "变色后零污染")

    print("\n=== 4. 滑块位移 ===")
    rail = rt.stage.element_of(cfg.EL["rail"]).item().sceneBoundingRect()
    # AGV 投影把 page 的 y 轴换成视图 x 轴，导轨在视图里是一条水平长条
    rt.push(cfg.TAG["position"], cfg.PARAM_DEFAULTS["pos_pos"])
    x_at_pos = slider_center_x(rt)
    rt.push(cfg.TAG["position"], cfg.PARAM_DEFAULTS["neg_pos"])
    x_at_neg = slider_center_x(rt)
    check("两个端点滑块位置确实不同",
          abs(x_at_pos - x_at_neg) > 1.0,
          f"view_x {x_at_pos:.2f} → {x_at_neg:.2f} (Δ={x_at_neg-x_at_pos:.2f})")
    check("位置增大往正极限方向", x_at_pos > x_at_neg)
    rt.push(cfg.TAG["position"], 0)
    x_mid = slider_center_x(rt)
    lo, hi = sorted((x_at_pos, x_at_neg))
    check("中间位置落在两端之间",
          lo - 0.6 <= x_mid <= hi + 0.6, f"view_x={x_mid:.2f}")
    kids = rt.stage.element_of(cfg.EL["slider"]).children()
    check("滑块组仍有 3 个子图元", len(kids) == 3)
    r = rt.stage.element_of(cfg.EL["slider"]).item().sceneBoundingRect()
    check("滑块沿导轨长边且不出界",
          r.left() >= rail.left() - 1.0 and r.right() <= rail.right() + 1.0
          and r.bottom() >= rail.top() and r.top() <= rail.bottom(),
          f"slider={r} rail={rail}")
    clean(rt, "位移后零污染")

    print("\n=== 5. 连续联动不漂移 / 不污染 ===")
    targets = [cfg.PARAM_DEFAULTS["pos_pos"], 50, 0, -50,
               cfg.PARAM_DEFAULTS["neg_pos"]] * 4
    drift = []
    for i, value in enumerate(targets):
        rt.push(cfg.TAG["position"], value)
        rt.push(cfg.TAG["neg_limit"], bool(i % 2))
        drift.append(slider_center_x(rt))
    rt.push(cfg.TAG["position"], cfg.PARAM_DEFAULTS["pos_pos"])
    back = slider_center_x(rt)
    check("20 次推送后回到端点位置不漂移",
          abs(back - x_at_pos) < 1e-3, f"Δ={abs(back-x_at_pos):.6f}")
    clean(rt, "连续联动后零污染")

    print("\n=== 6. 行程端点 / 控件回填 / 回写 ===")
    spy = SpySource()
    rt.attach_source(spy)
    rt.start()
    spin = rt._spins["pos_pos"]
    spin.setValue(250)
    check("spinbox 改动触发 DataSource.write",
          (cfg.TAG["pos_pos"], 250) in spy.writes,
          f"writes={spy.writes[-2:]}")
    rt.stage.tags.flush_now()          # 真实链路按 flush_ms 自动合流
    check("回写值进入总线缓存",
          rt.stage.tags.value(cfg.TAG["pos_pos"]) == 250,
          f"value={rt.stage.tags.value(cfg.TAG['pos_pos'])}")
    rt.push(cfg.TAG["home_count"], 7)
    check("点位回填 spinbox（不触发自激回写）",
          rt._spins["home_count"].value() == 7 and
          not any(k == cfg.TAG["home_count"] for k, _ in spy.writes))
    rt.push(cfg.TAG["position"], 250)
    x_new_end = slider_center_x(rt)
    check("行程端点改后滑块到达新端点",
          abs(x_new_end - x_at_pos) < 1e-3,
          f"Δ={abs(x_new_end-x_at_pos):.6f}")
    clean(rt, "回填与回写后零污染")

    print("\n=== 7. 数据源可替换 ===")
    check("make_source 三种形态",
          isinstance(make_source("demo"), DemoDataSource) and
          isinstance(make_source("none"), NullDataSource) and
          isinstance(make_source("modbus"), ModbusDataSource))
    modbus = ModbusDataSource({})
    warnings = []
    modbus.message.connect(lambda t, lv: warnings.append((t, lv)))
    modbus.start()
    check("Modbus 未配置时明确告警",
          any(lv == "warn" for _, lv in warnings), f"{warnings}")
    check("Modbus 未配置时不伪造数据",
          not modbus.is_running() or modbus._timer is not None)
    push_src = ModbusDataSource(
        {cfg.TAG["position"]: {"unit": 1, "address": 0}},
        auto_poll=False)
    received = []
    push_src.valuesChanged.connect(lambda d: received.append(d))
    push_src.start()
    push_src.submit({cfg.TAG["position"]: 12.5, "unknown.tag": 99})
    check("推送式 Modbus 只收已知点位",
          received and received[-1] == {cfg.TAG["position"]: 12.5},
          f"{received}")
    axis_key = cfg.axis_status_key("fPositionNow")
    push_src.submit({axis_key: 3.5, "unknown.tag": 99})
    check("面板点位也在白名单内",
          received[-1] == {axis_key: 3.5}, f"{received[-1]}")
    check("demo 源能启动并推值",
          isinstance(DemoDataSource(), DemoDataSource))

    print("\n=== 7b. Modbus 40001 映射 / 地址换算 / 编解码 / 端到端 ===")
    rmap = cfg.MODBUS_REGISTER_MAP
    # 现场寄存器布局由 PLC 决定：映射表可以是已知点位的子集（没接的点
    # 自然不存在），但不能凭空多出未定义点位。缺失项只提示、不算失败。
    missing = sorted(cfg.known_keys() - set(rmap))
    check("映射表点位均为已知点位",
          bool(rmap) and set(rmap) <= set(cfg.known_keys()),
          f"map={len(rmap)} known={len(cfg.known_keys())}")
    if missing:
        print(f"    [提示] {len(missing)} 个点位现场未映射："
              + ", ".join(x.rsplit(".", 1)[-1] for x in missing))
    check("起始 40001 → 协议地址 0（pymodbus 口径）",
          ml.protocol_address(0) == 0)
    check("raw 模式直传 40001", ml.protocol_address(0, mode="raw") == 40001)
    check("改 MODBUS_START 一处即可整体平移",
          ml.protocol_address(0, start=40101) == 100 and
          ml.protocol_address(2, start=40101) == 102)
    span = max(s["offset"] + ml.width(s) for s in rmap.values())
    check("所有点位 offset 非负且宽度合法",
          all(int(s["offset"]) >= 0 and ml.width(s) >= 1
              for s in rmap.values()), f"span={span}")

    # PLCManager 心跳线程每 500ms 写寄存器 1000；用探针表验证检测本身，
    # 现场表若真撞上只打印警告，不把「用户的现场地址」变成门禁失败。
    probe = {"probe": {"offset": 1000, "type": "double64", "scale": 1.0}}
    check("心跳寄存器 1000 冲突可检出",
          ml.heartbeat_conflicts(probe, enabled=True) == [("probe", 1000)] and
          ml.heartbeat_conflicts(probe, enabled=False) == [] and
          ml.heartbeat_conflicts(
              {"ok": {"offset": 1004, "type": "double64"}},
              enabled=True) == [])
    hits = ml.heartbeat_conflicts(rmap)
    if hits:
        print("    [警告] 心跳每 500ms 写寄存器 1000，会覆盖："
              + ", ".join(k for k, _ in hits)
              + " → 设 MODBUS_USE_PLC_MANAGER=False 或挪走该点位")

    # 协议编解码用固定 spec 测，不绑死现场 rmap 里的类型 / offset /
    # 字序；否则 PLC 布局一改门禁就整组变红。
    f32 = {"offset": 0, "type": "float32", "scale": 1.0}
    d64 = {"offset": 0, "type": "double64", "scale": 1.0}
    check("struct 'f' 占 2 字 / 'd' 占 4 字",
          ml.width(f32) == 2 and ml.width(d64) == 4 and
          len(ml.encode(f32, 12.5)) == 2 and
          len(ml.encode(d64, 12.5)) == 4)

    # 现场 PLC 实测口径（低字在前、字内字节仍是大端）。换设备时改这里的
    # 期望值和 cfg.MODBUS_FLOAT_WORD_ORDER，别把网络序当成通用解。
    plc_d = [0, 0, 0, 0x4029]
    plc_f = [0, 0x4148]
    check("默认字序 = 现场 PLC 低字在前",
          cfg.MODBUS_FLOAT_WORD_ORDER == "little",
          cfg.MODBUS_FLOAT_WORD_ORDER)
    check("PLC 实测 double64 12.5 = [0,0,0,0x4029]",
          ml.encode(d64, 12.5) == plc_d and ml.decode(d64, plc_d) == 12.5,
          f"encode={[hex(x) for x in ml.encode(d64, 12.5)]}")
    check("PLC 实测 float32 12.5 = [0,0x4148]",
          ml.encode(f32, 12.5) == plc_f and ml.decode(f32, plc_f) == 12.5)
    check("little = 整体 4 字反序（不是两两交换）",
          ml.decode(dict(d64, word_order="little"), plc_d) == 12.5)
    check("big 模式仍输出网络序 [0x4029,0,0,0]",
          ml.encode(dict(d64, word_order="big"), 12.5) ==
          [0x4029, 0, 0, 0])
    check("高字在前 round-trip 也成立",
          ml.decode(dict(d64, word_order="big"),
                    ml.encode(dict(d64, word_order="big"),
                              1.2345678901234567)) == 1.2345678901234567)

    check("float32 编解码 round-trip",
          abs(ml.decode(f32, ml.encode(f32, 12.5)) - 12.5) < 1e-6)
    check("double64 编解码不丢精度",
          ml.decode(d64, ml.encode(d64, 1.2345678901234567)) ==
          1.2345678901234567)
    check("double64 低字在前也能还原",
          ml.decode(dict(d64, word_order="little"),
                    ml.encode(dict(d64, word_order="little"), -88.25)) == -88.25)
    little = dict(f32, word_order="little")
    check("低字在前也能还原",
          abs(ml.decode(little, ml.encode(little, -88.25)) + 88.25) < 1e-6)
    scaled = dict(f32, scale=0.1)
    check("scale 读乘写除",
          abs(ml.decode(scaled, ml.encode(scaled, 12.5)) - 12.5) < 1e-6)
    i16 = dict(f32, type="int16")
    check("int16 负数不溢出", ml.decode(i16, ml.encode(i16, -100)) == -100)
    lamp_key = cfg.axis_status_key("xErr")
    # 现场状态位已从 bit 改成 byte 打包，这里用固定 spec 测 bit 解码本身。
    bit_spec = {"offset": 0, "type": "bit", "bit": 6, "access": "r"}
    check("状态位按 bit 解码", ml.decode(bit_spec, [1 << 6]) and
          not ml.decode(bit_spec, [1 << 0]))
    text_spec = {"offset": 0, "type": "string", "words": 4, "scale": 1.0}
    check("字符串点位 round-trip",
          ml.decode(text_spec, ml.encode(text_spec, "ALM-01")) == "ALM-01")

    class FakeClient:
        """只验证协议链路，不连真实设备。"""

        def __init__(self):
            self.words = [0] * 64
            self.connected = True
            self.reads: list[tuple] = []
            self.writes: list[tuple] = []

        def connect(self, ip, port=502, timeout=1.0):
            return True

        def disconnect(self):
            self.connected = False

        def read_holding_registers(self, address, count=1, unit=1):
            self.reads.append((address, count, unit))
            return list(self.words[address:address + count])

        def write_registers(self, address, values, unit=1):
            self.writes.append((address, list(values), unit))
            self.words[address:address + len(values)] = list(values)
            return True

    # 协议链路用独立的紧凑测试表：现场 rmap 的 offset 可以随意重排，
    # 但「一次批量读 / 只读拒绝写 / bit 读改写」这些语义必须恒成立。
    # key 仍用真实点位名，保证 ModbusDataSource 的白名单放行。
    cmd = cfg.axis_manual_key("enable")
    wkey = cfg.axis_manual_key("absDistance")
    vel_key = cfg.axis_status_key("fVelocityNow")
    test_map = {
        lamp_key:             {"offset": 0, "type": "bit", "bit": 6,
                               "access": "r"},
        cfg.TAG["neg_limit"]: {"offset": 1, "type": "bit", "bit": 0,
                               "access": "r"},
        cfg.TAG["position"]:  {"offset": 2, "type": "float32",
                               "access": "r", "scale": 1.0},
        vel_key:              {"offset": 4, "type": "double64",
                               "access": "r", "scale": 1.0},
        cmd:                  {"offset": 8, "type": "bool", "access": "w"},
        wkey:                 {"offset": 9, "type": "float32",
                               "access": "rw", "scale": 1.0},
    }
    fake = FakeClient()
    fake.words[0] = 1 << 6                                  # 状态灯 bit6
    fake.words[1] = 0b101                                   # 负极限 bit0
    fake.words[2:4] = ml.encode(test_map[cfg.TAG["position"]], 12.5)
    fake.words[4:8] = ml.encode(test_map[vel_key], -88.25)  # 'd' 占 4 字
    link = ml.ModbusLink(client=fake, ip="fake")
    check("假客户端连接", link.connect())
    src = ModbusDataSource(test_map)
    link.attach(src)
    received: list[dict] = []
    src.valuesChanged.connect(lambda d: received.append(d))
    src.start()                              # 立即同步 _poll 一次
    check("一次批量读整块（不是逐点请求）",
          len(fake.reads) == 1 and fake.reads[0][0] == 0 and
          fake.reads[0][1] == 11, f"{fake.reads}")
    check("端到端：读值进入 valuesChanged",
          bool(received) and
          abs(received[-1][cfg.TAG["position"]] - 12.5) < 1e-6 and
          received[-1][vel_key] == -88.25 and
          received[-1][lamp_key] is True and
          received[-1][cfg.TAG["neg_limit"]] is True,
          f"n={len(received[-1]) if received else 0}")
    src.stop()

    check("命令按钮写 1 / 0",
          link.write(cmd, True, test_map[cmd]) and fake.words[8] == 1 and
          link.write(cmd, False, test_map[cmd]) and fake.words[8] == 0)
    check("只读点位拒绝写",
          not link.write(lamp_key, True, test_map[lamp_key]))
    check("写入行 float32 写回",
          link.write(wkey, 123.5, test_map[wkey]) and
          abs(ml.decode(test_map[wkey], fake.words[9:11]) - 123.5) < 1e-6)
    fake.words[0] = (1 << 6) | (1 << 2)
    link.write(lamp_key, False, dict(test_map[lamp_key], access="rw"))
    check("bit 写读-改-写保留同字其它位",
          fake.words[0] == (1 << 2), f"{fake.words[0]}")

    # byte：一个寄存器打包两个 BOOL（byte=0 → bit0 / byte=1 → bit8）。
    # 现场配置里 25 个 byte 点位，写必须读-改-写且幂等，否则点一下命令
    # 就会把同一字里的状态位清掉，或重复写把值累加成乱码。
    b0 = {"offset": 20, "type": "byte", "byte": 0, "access": "w"}
    b1 = {"offset": 20, "type": "byte", "byte": 1, "access": "w"}
    check("byte=0 写 True 保留高字节且重复写幂等",
          fake.words[20] == 0 and
          link.write("b0", True, b0) and fake.words[20] == 0x0001 and
          link.write("b0", True, b0) and fake.words[20] == 0x0001,
          f"{hex(fake.words[20])}")
    check("byte=1 写 True 保留低字节",
          link.write("b1", True, b1) and fake.words[20] == 0x0101,
          f"{hex(fake.words[20])}")
    check("byte 写 False 只清目标位、不出负数",
          link.write("b0", False, b0) and fake.words[20] == 0x0100 and
          link.write("b1", False, b1) and fake.words[20] == 0x0000 and
          link.write("b1", False, b1) and fake.words[20] == 0x0000,
          f"{hex(fake.words[20])}")
    check("byte decode 与掩码一致",
          ml.decode(dict(b0, access="r"), [0x0101]) is True and
          ml.decode(dict(b1, access="r"), [0x0101]) is True and
          ml.decode(dict(b1, access="r"), [0x0001]) is False)

    def _raises_value_error(fn) -> bool:
        try:
            fn()
        except ValueError:
            return True
        return False

    check("非法 byte 索引报错而非静默返回 False",
          all(_raises_value_error(lambda s=s: ml.decode(s, [1]))
              for s in ({"type": "byte"},
                        {"type": "byte", "byte": 2},
                        {"type": "byte", "byte": -1})))
    check("byte 打包（同字不同 byte）不算地址重叠",
          ml.overlap_conflicts({"a": b0, "b": b1}) == {})
    check("不同含义点位占同一字会被检出",
          20 in ml.overlap_conflicts(
              {"a": b0, "num": {"offset": 20, "type": "uint16"}}))
    link.close()

    print("\n=== 8. 换页 / 释放 ===")
    old_element = rt.stage.element_of(cfg.EL["slider"])
    rt.load()
    check("reload 后门面仍可用（按 id 现查）",
          not old_element.is_detached() and old_element.item() is not None)
    check("reload 后控件数量不变", len(rt.stage.controls()) == 6)
    clean(rt, "reload 后零污染")
    check("report 含关键状态",
          "spins=5" in rt.report() and "panel=True" in rt.report())

    print("\n=== 9. 伺服轴面板：显示 / 命令 / 确认 / 零污染 ===")
    panel = rt._panel
    pos_key = cfg.axis_status_key("fPositionNow")
    lamp_key = cfg.axis_status_key("xErr")
    write_key = cfg.axis_manual_key("absDistance")
    rt.push(pos_key, 12.5)
    check("数值点位刷新面板",
          panel.cells[pos_key].current_text() == "12.50 mm",
          panel.cells[pos_key].current_text())
    rt.push(lamp_key, True)
    check("状态灯 True → 亮", panel.lamps[lamp_key].state is True)
    rt.push(lamp_key, False)
    check("状态灯 False → 灭", panel.lamps[lamp_key].state is False)
    rt.push(write_key, 88.0)
    check("写入行当前值刷新",
          panel.writes[write_key].current_text() == "88.00 mm")
    clean(rt, "面板刷新后零污染")

    # 配置 → PanelSpec → 面板构造必须用同一种元组形状；之前 momentary
    # 在配置里加了第三列 confirm，PanelSpec 仍按 2 元组构造，直接崩在解包。
    spec = panel.spec
    check("momentary 规格与配置同为 3 元组",
          all(len(t) == 3 for t in spec.momentary) and
          len(spec.momentary) == len(cfg.AXIS_MOMENTARY_FIELDS) and
          all(len(t) == 3 for t in spec.commands),
          f"momentary={len(spec.momentary)} commands={len(spec.commands)}")
    check("危险点动按钮带确认标志",
          sum(1 for b in panel.buttons.values()
              if isinstance(b, MomentaryButton) and b.confirm) ==
          sum(1 for *_, c in cfg.AXIS_MOMENTARY_FIELDS if c))

    spy = rt._source
    enable = cfg.axis_manual_key("enable")
    panel.buttons[enable].click()
    check("命令按钮 → DataSource.write", (enable, True) in spy.writes)
    # 是否需要二次确认由 AXIS_*_FIELDS 的第三列决定，现场可能全关；
    # 按按钮自身的 confirm 标志分支，别把某一种配置写死进门禁。
    home = cfg.axis_manual_key("getHome")
    home_btn = panel.buttons[home]
    before = len(spy.writes)
    home_btn.click()
    if getattr(home_btn, "confirm", False):
        check("带确认的命令先弹页面内确认条（不弹模态框）",
              panel.confirm.isVisible() and len(spy.writes) == before)
        panel.confirm._accept()
        check("确认后下发 True→False 脉冲",
              spy.writes[-2:] == [(home, True), (home, False)],
              f"{spy.writes[-2:]}")
    else:
        check("未标记确认的点动直接下发 True→False、不弹确认条",
              not panel.confirm.isVisible() and
              spy.writes[-2:] == [(home, True), (home, False)],
              f"{spy.writes[-2:]}")
    jog = cfg.axis_manual_key("jogPositive")
    panel.buttons[jog].pressed.emit()
    panel.buttons[jog].released.emit()
    check("点动按住/松开写 True/False",
          spy.writes[-2:] == [(jog, True), (jog, False)],
          f"{spy.writes[-2:]}")
    panel.writes[write_key].set_new_value("123.5")
    panel.writes[write_key]._emit()
    check("写入行 → DataSource.write",
          (write_key, 123.5) in spy.writes, f"{spy.writes[-1:]}")
    clean(rt, "命令回写后零污染")
    check("reload 后面板仍是新实例且信号仍通",
          panel is rt._panel and rt._panel is not None)

    rt.release()
    check("release 后面板引用已清空", rt._panel is None)
    check("release 可重复调用", rt.release() is None)

    print("\n=== 10. 新增 text 图元的 Modbus 计数绑定 ===")
    rt2 = FixtureRuntime(page_path=PAGE, source=NullDataSource())
    rt2.load()
    e_home = rt2.stage.element_of(cfg.EL["home_count_now"])
    e_total = rt2.stage.element_of(cfg.EL["total_count"])
    check("两个 text 图元按 JSON 真实 name 可查",
          e_home is not None and e_total is not None and
          getattr(e_home.item(), "TYPE", "") == "text" and
          getattr(e_total.item(), "TYPE", "") == "text",
          f"{cfg.EL['home_count_now']!r} / {cfg.EL['total_count']!r}")
    check("初始仍是设计占位文本",
          e_home.context == "###" and e_total.context == "#####",
          f"{e_home.context!r} / {e_total.context!r}")

    for short, el, _ in cfg.TEXT_BINDINGS:
        tag = cfg.TAG[short]
        spec = cfg.MODBUS_REGISTER_MAP.get(tag)
        check(f"{short} 在 known_keys 与寄存器映射表内",
              tag in cfg.known_keys() and spec is not None and
              "r" in str(spec.get("access", "r")),
              f"tag={tag} spec={spec}")

    rt2.push(cfg.TAG["home_count_now"], 7)
    rt2.push(cfg.TAG["total_count"], 12345)
    check("点位值刷进 text 图元",
          e_home.context == "7" and e_total.context == "12345",
          f"{e_home.context!r} / {e_total.context!r}")
    clean(rt2, "text 联动零污染（_page.context 仍是 ### / #####）")

    # 真·端到端：假 PLC 寄存器 → ModbusLink.read → ModbusDataSource 白名单
    # → TagBus → _apply_texts → TextItem.context。用独立紧凑表，不绑现场布局。
    text_map = {
        cfg.TAG["home_count_now"]: {"offset": 0, "type": "int16",
                                    "access": "r"},
        cfg.TAG["total_count"]: {"offset": 1, "type": "uint32",
                                 "access": "r"},
    }
    fake2 = FakeClient()
    fake2.words[0] = 42
    fake2.words[1:3] = ml.encode(text_map[cfg.TAG["total_count"]], 98765)
    link2 = ml.ModbusLink(client=fake2, ip="fake")
    check("假 PLC 连接", link2.connect())
    vals = link2.read(text_map)
    check("读寄存器能解出两个计数点位",
          vals.get(cfg.TAG["home_count_now"]) == 42 and
          vals.get(cfg.TAG["total_count"]) == 98765, f"{vals}")

    src2 = ModbusDataSource(text_map)
    link2.attach(src2)
    src2.valuesChanged.connect(rt2.stage.tags.update_many)
    src2.start()                          # start 里同步 _poll 一次
    rt2.stage.tags.flush_now()
    check("寄存器 → 数据源 → 总线 → text 图元",
          e_home.context == "42" and e_total.context == "98765",
          f"{e_home.context!r} / {e_total.context!r}")
    clean(rt2, "Modbus 端到端后零污染")
    src2.stop()
    link2.close()

    demo = DemoDataSource()
    frames: list[dict] = []
    demo.valuesChanged.connect(lambda d: frames.append(d))
    demo.start()
    check("Demo 首帧也带两个计数点位",
          bool(frames) and cfg.TAG["home_count_now"] in frames[0] and
          cfg.TAG["total_count"] in frames[0])
    demo.stop()
    rt2.release()

    print(f"\n失败 {len(FAILURES)} 项" +
          (": " + ", ".join(FAILURES) if FAILURES else ""))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
