"""OPC UA 通信层回归测试。

不需要真实 PLC：起一个进程内的 asyncua 服务器（``tools/opcua_mock_server.py``），
走完整的 connect / subscribe / read / write / 断线重连链路。

跑法::

    .venv/Scripts/python.exe tools/verify_opcua.py

每一项都尽量做成"能反向验证"的：把对应实现去掉，断言必须失败。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication

from common.com.opcua import OpcConfig, OpcUaManager
from common.com.opcua.opcua_manager import _ReconnectNoiseFilter
from tools.opcua_mock_server import KEYS, MockOpcUaServer

ENDPOINT = "opc.tcp://127.0.0.1:48400"

_passed = 0
_failed: list[str] = []


class _LogCapture(logging.Handler):
    """把根 logger 收到的记录留一份，用来断言"谁被静音了"。"""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]


def check(cond: bool, desc: str) -> bool:
    global _passed
    if cond:
        _passed += 1
        print(f"  ok   {desc}")
    else:
        _failed.append(desc)
        print(f"  FAIL {desc}")
    return cond


def pump(app: QCoreApplication, seconds: float) -> None:
    """跑 Qt 事件循环 N 秒——跨线程信号是排队投递的，不 pump 就永远收不到。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def wait_until(app: QCoreApplication, pred, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    app.processEvents()
    return pred()


def main() -> int:
    app = QCoreApplication(sys.argv[:1])

    server = MockOpcUaServer(ENDPOINT)
    server.start()
    print(f"\n模拟服务器: {ENDPOINT}  ns={server.namespace_index}")
    node_ids = server.node_ids()
    check(server.namespace_index is not None, "服务器启动并拿到命名空间索引")
    check(
        len(node_ids) == len(KEYS) and all(v.startswith("ns=") for v in node_ids.values()),
        f"节点表 {len(node_ids)} 条且都是标准 NodeId 形式",
    )

    mgr = OpcUaManager(OpcConfig(endpoint=ENDPOINT, publish_period_ms=100))
    received: list[tuple[str, object]] = []
    conn_states: list[bool] = []
    errors: list[tuple[str, str]] = []
    mgr.node_changed.connect(lambda k, v: received.append((k, v)))
    mgr.connected_changed.connect(lambda s: conn_states.append(s))
    mgr.node_error.connect(lambda k, e: errors.append((k, e)))

    # --- 1. 未连接时的行为 -------------------------------------------
    check(mgr.read("lamp01") is None, "未 start 时 read 返回 None 而不抛异常")
    check(mgr.write("lamp01", True) is False, "未 start 时 write 返回 False")
    check(mgr.is_connected() is False, "未 start 时 is_connected 为 False")
    check(mgr.browse_children("") == [], "未 start 时 browse_children 返回空表")

    # --- 2. subscribe 先于 start（现场常见：先配置、后连接）-----------
    mgr.subscribe(node_ids)
    check(
        mgr.debug_state()["desired"] == node_ids,
        "start 之前 subscribe 能记录订阅意图",
    )

    mgr.start()
    mgr.start()  # 幂等
    ok = wait_until(app, mgr.is_connected, 8.0)
    check(ok, "连接建立")
    # is_connected() 直接查底层状态，会比信号早一步变 True（信号是 worker
    # 每 500ms 采样后排队投递的），所以这里必须等信号，不能紧接着断言。
    ok = wait_until(app, lambda: bool(conn_states) and conn_states[-1] is True, 3.0)
    check(ok, "connected_changed 发出 True")

    # --- 3. 订阅建立时服务端会先推一次当前值 -------------------------
    ok = wait_until(app, lambda: len(received) >= len(KEYS), 5.0)
    first = dict(received)
    check(ok, f"订阅后立即收到全部 {len(KEYS)} 个节点当前值")
    check(first.get("lamp01") is False, "首轮 lamp01 = False")
    check(first.get("fullcount") == 0, "首轮 fullcount = 0")
    check(first.get("message") == "ready", "首轮 message = 'ready'")
    check(isinstance(first.get("heartbeat"), int), "心跳是整数而不是字符串")

    # --- 4. 同步读 ---------------------------------------------------
    check(mgr.read("lamp01") is False, "read('lamp01') = False")
    check(mgr.read("fullcount") == 0, "read('fullcount') = 0")

    # --- 5. 同步写 + 服务端真值核对 -----------------------------------
    check(mgr.write("lamp01", True) is True, "write('lamp01', True) 成功")
    check(server.get_value("Lamp01") is True, "服务端真值确实变成 True")
    check(mgr.read("lamp01") is True, "回读 = True")

    check(mgr.write("fullcount", 42) is True, "write('fullcount', 42) 成功")
    check(server.get_value("FullCount") == 42, "服务端 FullCount = 42（Int16 没被写成 Int64）")
    check(mgr.write("fullcount", -7) is True, "Int16 负值可写")
    check(mgr.read("fullcount") == -7, "负值回读 = -7")

    check(mgr.write("message", "上料完成") is True, "写中文字符串成功")
    check(server.get_value("Message") == "上料完成", "服务端 Message 为中文且未乱码")

    # 写 1 到 Boolean 节点：必须被收敛成 True，否则服务端回 BadTypeMismatch
    check(mgr.write("lamp02", 1) is True, "Boolean 节点写 int 1 自动收敛")
    check(server.get_value("Lamp02") is True, "服务端 Lamp02 = True")

    # --- 6. 服务端改值 → 订阅推送（不经过本地 read）-------------------
    received.clear()
    server.set_value("Lamp03", True)
    server.set_value("FullCount", 99)
    ok = wait_until(
        app,
        lambda: any(k == "lamp03" and v is True for k, v in received)
        and any(k == "fullcount" and v == 99 for k, v in received),
        4.0,
    )
    check(ok, "服务端改值后订阅推送到界面（不经本地 read）")

    # 心跳是服务器自己变的，用来验证推送是持续行为而不是一次性
    received.clear()
    ok = wait_until(app, lambda: len([1 for k, _ in received if k == "heartbeat"]) >= 2, 4.0)
    check(ok, "心跳持续推送（服务器自增，客户端被动接收）")

    # --- 7. 单点读未订阅的节点 ---------------------------------------
    check(mgr.read(node_ids["lamp04"]) is False, "key 直接传 NodeId 也能读（免订阅单点读）")

    # --- 8. 地址空间浏览（GUI 浏览器依赖这块）-------------------------
    children = mgr.browse_children("")
    check(isinstance(children, list) and len(children) >= 1, "browse_children('') 返回根节点列表")
    app_node = next((c for c in children if c["name"] == "AppsManagers"), None)
    check(app_node is not None, "根下能找到 AppsManagers")
    if app_node:
        check(
            set(app_node) >= {"node_id", "name", "namespace", "node_class",
                              "value", "writable", "has_children"},
            "节点字典字段齐全（node_id/name/namespace/node_class/value/writable/has_children）",
        )
        check(app_node["node_class"] == "Object", "AppsManagers 是 Object")
        check(app_node["has_children"] is True, "Object 标记为有子节点")
        check(app_node["namespace"] != 0, "自定义节点 namespace 不为 0")

    rack_children = mgr.browse_children(app_node["node_id"]) if app_node else []
    rack_node = next((c for c in rack_children if c["name"] == "Rack"), None)
    check(rack_node is not None, "能向下展开到 Rack")
    leaves = mgr.browse_children(rack_node["node_id"]) if rack_node else []
    by_name = {c["name"]: c for c in leaves}
    # 7 个基础变量 + 2 个结构体变量（Slot01 / Slots）；结构体展开单独在
    # tools/verify_opcua_struct.py 里回归
    expected = len(KEYS) + 2
    check(len(leaves) == expected, f"Rack 下有 {expected} 个变量（实得 {len(leaves)}）")
    check(by_name.get("Lamp01", {}).get("node_class") == "Variable", "Lamp01 是 Variable")
    check(by_name.get("Lamp01", {}).get("has_children") is False, "Variable 不提供展开")
    # 批量读到的值要和真实一致
    check(by_name.get("Message", {}).get("value") == "上料完成", "浏览时顺带读到 Message 当前值")
    check(by_name.get("FullCount", {}).get("value") == 99, "浏览时顺带读到 FullCount 当前值")
    # 权限：只读节点不能被标成可写（踩过 ua.AccessLevel 是位序号的坑）
    check(by_name.get("Heartbeat", {}).get("writable") is False, "Heartbeat 浏览结果为只读")
    check(by_name.get("Lamp01", {}).get("writable") is True, "Lamp01 浏览结果为可写")

    check(mgr.node_type(node_ids["fullcount"]) == "Int16", "node_type 返回 Int16")
    check(mgr.node_type(node_ids["lamp01"]) == "Boolean", "node_type 返回 Boolean")

    # --- 9. 断线 → 自动重连 → 订阅重建 --------------------------------
    conn_states.clear()
    # 抓日志：断线窗口里 asyncua 的 publish 循环每秒崩一次、每次打一整段
    # traceback。真上手时控制台就是这么被刷满的，这里量化它。
    capture = _LogCapture()
    root_logger = logging.getLogger()
    root_logger.addHandler(capture)

    # 过滤器本身的两面：该吞的吞、不该吞的照旧
    _flt = _ReconnectNoiseFilter()

    def _rec(msg: str, exc: BaseException) -> logging.LogRecord:
        record = logging.LogRecord("asyncua.client.ua_session.UaSession",
                                   logging.ERROR, __file__, 1, msg, None, None)
        record.exc_info = (type(exc), exc, None)
        return record

    check(
        _flt.filter(_rec("Publish iteration crashed; retrying in 1s",
                         ConnectionError("Connection is closed"))) is False,
        "过滤器吞掉断线期间的 publish traceback",
    )
    check(
        _flt.filter(_rec("Publish iteration crashed; retrying in 1s",
                         RuntimeError("真的出事了"))) is True,
        "同一句文案但异常不是传输层症状时照旧放行",
    )
    check(
        _flt.filter(_rec("close_session raised during disconnect; continuing teardown",
                         TimeoutError())) is False,
        "掉线时关窗口的 CloseSession 超时也不刷 traceback",
    )
    check(
        _flt.filter(_rec("ServiceFault received", ConnectionError("x"))) is True,
        "非白名单消息照旧放行（不按 logger 一刀切）",
    )

    server.stop()
    ok = wait_until(app, lambda: mgr.is_connected() is False, 12.0)
    check(ok, "服务器停止后客户端判定为断开")
    ok = wait_until(app, lambda: False in conn_states, 3.0)
    check(ok, "connected_changed 发出 False")

    # 停 3 秒：publish 循环正常会崩 2~3 次，一分钟不掉线才怪
    pump(app, 3.0)
    publish_crash = [
        m for m in capture.messages() if m == "Publish iteration crashed; retrying in 1s"
    ]
    check(
        not publish_crash,
        f"断线窗口内 publish 崩溃日志已静音（实际漏出 {len(publish_crash)} 条）",
    )
    check(
        any("Reconnect attempt failed" in m for m in capture.messages()),
        "重连退避仍然每轮一条 warning（没把有用的日志一起吞掉）",
    )
    check(
        any(
            getattr(f, "_opcua_quiet", False)
            for f in logging.getLogger("asyncua.client.ua_session.UaSession").filters
        ),
        "过滤器挂在 publish 循环实际使用的实例 logger 上",
    )

    received.clear()
    server.start()
    ok = wait_until(app, mgr.is_connected, 35.0)
    check(ok, "服务器恢复后自动重连成功（无需人工干预）")
    # 状态信号是 worker 每 500ms 采一次再排队投递的，is_connected() 会先变 True，
    # 这里必须再等一轮事件循环，不能紧接着断言。
    ok = wait_until(app, lambda: bool(conn_states) and conn_states[-1] is True, 3.0)
    check(ok, "connected_changed 发出 True")
    root_logger.removeHandler(capture)

    ok = wait_until(app, lambda: len(received) >= len(KEYS), 8.0)
    check(ok, f"重连后订阅自动重建，收到 {len(received)} 条推送")
    # 模拟服务器重启是"新设备"，节点值回到初值；真实 PLC 不会这样，所以这里
    # 断言的是"客户端读到的和服务端真值一致"，而不是"记得断线前的值"。
    check(
        mgr.read("lamp03") == server.get_value("Lamp03"),
        "重连后读到的值与重启后的服务端真值一致",
    )

    # 重连后写入依然可用
    check(mgr.write("message", "reconnected") is True, "重连后写入可用")
    check(server.get_value("Message") == "reconnected", "重连后写入落到服务端")

    # --- 10. 全程没有未处理的节点错误 ---------------------------------
    check(not errors, f"全程无 node_error（实际 {len(errors)} 条: {errors[:3]}）")

    # --- 11. 停止与资源回收 ------------------------------------------
    state = mgr.debug_state()
    check(state["thread_alive"] is True, "stop 之前后台线程存活")
    stopped = mgr.stop(wait_ms=3000)
    check(stopped is True, "stop() 后线程已真正退出")
    check(mgr.debug_state()["thread_alive"] is False, "debug_state 反映线程已退出")
    check(mgr.is_connected() is False, "stop 后 is_connected 为 False")

    # stop 之后应能再次 start（页签反复打开关闭是常态）
    received.clear()
    mgr.subscribe(node_ids)
    mgr.start()
    ok = wait_until(app, mgr.is_connected, 10.0)
    check(ok, "stop 之后可以再次 start")
    ok = wait_until(app, lambda: len(received) >= len(KEYS), 6.0)
    check(ok, f"二次 start 后订阅重建成功（收到 {len(received)} 条）")
    check(mgr.stop(wait_ms=3000) is True, "二次 stop 干净退出")

    # --- 12. 断线途中 stop：publish 常驻任务必须被收掉 ------------------
    # 现场最常见的一种退出：PLC 掉电了，操作员直接关窗口。这时 asyncua 的
    # close_session() 会因为"协议已经没了"提前 return，跳过 cancel publish
    # 任务，任务就永远 pending，解释器退出时打 "Task was destroyed"。
    received.clear()
    mgr.subscribe(node_ids)
    mgr.start()
    check(wait_until(app, mgr.is_connected, 10.0), "断线测试前重新连上")
    check(wait_until(app, lambda: bool(mgr._subscribed), 6.0), "断线测试前订阅已建立")
    pub_task = None

    def _publish_task():
        client = mgr._client
        return None if client is None else client.uaclient._publish_task

    check(wait_until(app, lambda: _publish_task() is not None, 5.0), "publish 常驻任务已启动")
    pub_task = _publish_task()
    server.stop()
    check(wait_until(app, lambda: mgr.is_connected() is False, 12.0), "断线测试：已判定断开")
    pump(app, 1.5)  # 让 publish 循环至少崩一次，停在 sleep 里
    check(mgr.stop(wait_ms=3000) is True, "断线途中 stop() 仍能干净退出")
    check(pub_task is not None and pub_task.done(), "断线途中 stop 收掉了 publish 任务")

    # --- 13. 超时配置：短探测周期会把慢 PLC 误判成掉线 ------------------
    # asyncua 里 watchdog_intervall 同时是「探测周期」和「探测超时」：
    #   probe_timeout = min(revised_session_timeout/2, watchdog_intervall)
    # 服务器把会话超时压到 30s 时，旧默认 1.0s = 每秒读一次 ServerState 且只
    # 等 1 秒；真机偶发卡顿就判掉线，重连握手又被 4s 掐成 TimeoutError。
    defaults = OpcConfig()
    check(defaults.timeout == 10.0, "底层请求/握手超时默认 10s（旧 4s 掐死重连）")
    check(defaults.operation_timeout == 5.0, "UI 同步桥接超时独立为 5s")
    check(defaults.watchdog_interval == 5.0, "健康探测周期默认 5s（探头超时同值）")

    server.start()
    custom = OpcUaManager(OpcConfig(endpoint=ENDPOINT, timeout=15.0, watchdog_interval=8.0))
    custom.start()
    check(wait_until(app, custom.is_connected, 10.0), "自定义超时配置能连上")
    check(custom._client.uaclient._timeout == 15.0, "timeout 传给了 UaClient（握手用它）")
    check(custom._client._watchdog_intervall == 8.0, "watchdog 传给了 Client 探测循环")
    custom.stop()

    def _probe_case(watchdog: float, slow: float) -> bool:
        probe = OpcUaManager(
            OpcConfig(endpoint=ENDPOINT, watchdog_interval=watchdog, timeout=10.0)
        )
        states: list[bool] = []
        probe.connected_changed.connect(states.append)
        probe.start()
        wait_until(app, probe.is_connected, 10.0)

        async def slow_read():
            await asyncio.sleep(slow)
            return 0

        # 模拟真机读 ServerStatus 偶发 1.2s 才回
        probe._client.nodes.server_state.read_value = slow_read
        pump(app, 3.0)
        dropped = False in states
        probe.stop()
        return dropped

    check(_probe_case(0.3, 1.2) is True, "短探测周期（0.3s）把慢 ServerState 误判成掉线")
    check(_probe_case(3.0, 1.2) is False, "放宽到 3s 后同样慢读不再误判（旧默认 1s 会）")

    # --- 14. 真机协商噪声静音 + 重连异常栈诊断 --------------------------
    import common.com.opcua.opcua_manager as _om

    def _plain(msg: str, args=None) -> logging.LogRecord:
        return logging.LogRecord(
            "asyncua.client.client", logging.WARNING, "x.py", 1, msg, args, None
        )

    flt = _ReconnectNoiseFilter()
    check(OpcConfig().publish_period_ms == 1000, "订阅发布间隔按 PLC 实际值改为 1000ms")
    for msg in (
        "close_session but connection wasn't established",
        "close_secure_channel was called but connection is closed",
        "Revised values returned differ from subscription values: X",
        "Requested session timeout to be 3600000ms, got 30000ms instead",
    ):
        check(flt.filter(_plain(msg)) is False, f"协商/清理 warning 静音: {msg[:26]}")
    check(flt.filter(_plain("ServiceFault (BadSessionIdInvalid)")) is True,
          "真错误日志不被静音")
    check(
        flt.filter(_plain("Reconnect attempt failed: %r; retrying in %.1fs",
                          (TimeoutError(), 1.0))) is True,
        "重连失败日志保留（诊断开关要靠它取栈）",
    )

    trace_path = os.path.join(tempfile.gettempdir(), "verify_opcua_trace.log")
    if os.path.exists(trace_path):
        os.remove(trace_path)
    old_path = _om._RECONNECT_TRACE_PATH
    _om._RECONNECT_TRACE_PATH = trace_path
    try:
        trace_flt = _om._ReconnectTraceFilter()
        try:
            raise TimeoutError()
        except TimeoutError as exc:
            trace_flt.filter(_plain(
                "Reconnect attempt failed: %r; retrying in %.1fs", (exc, 1.0)
            ))
        text = ""
        if os.path.exists(trace_path):
            with open(trace_path, encoding="utf-8") as fp:
                text = fp.read()
    finally:
        _om._RECONNECT_TRACE_PATH = old_path
        if os.path.exists(trace_path):
            os.remove(trace_path)
    check(
        "Traceback (most recent call last)" in text and "TimeoutError" in text,
        "重连诊断把 TimeoutError 的完整异常栈写进文件",
    )

    server.stop()

    print(f"\n结果: {_passed} 通过, {len(_failed)} 失败")
    if _failed:
        for item in _failed:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
