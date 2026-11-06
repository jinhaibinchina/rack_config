"""进程内 OPC UA 模拟服务器。

用途有两个：

* ``tools/opcua_demo.py`` —— 手边没有真实 PLC 时，demo 也能跑起来；
* ``tools/verify_opcua.py`` —— 回归测试起一个真实端点，走完整的
  connect / subscribe / write 链路，而不是 mock 掉 asyncua。

节点树（挂在 Objects 下）::

    AppsManagers
      Rack
        Lamp01..Lamp04   Boolean   可写
        FullCount        Int16     可写
        Message          String    可写
        Heartbeat        UInt32    服务器每 500ms 自增（演示订阅推送）
        Slot01           RackSlot  结构体（ExtensionObject，Body 是裸字节）
        Slots            RackSlot[] 结构体数组

结构体类型 ``RackStruct`` / ``RackSlot`` 带 ``DataTypeDefinition`` 属性
（OPC UA 1.04），用来回归"结构体展开"——真实 PLC 的结构变量就是这样：一个
ExtensionObject 加一包没有字段名的字节流。
"""

from __future__ import annotations

import asyncio
import threading

from asyncua import Server, ua
from asyncua.ua import ua_binary

#: (标识符, 类型, 初值, 是否可写)
NODE_SPECS = (
    ("Lamp01", ua.VariantType.Boolean, False, True),
    ("Lamp02", ua.VariantType.Boolean, False, True),
    ("Lamp03", ua.VariantType.Boolean, False, True),
    ("Lamp04", ua.VariantType.Boolean, False, True),
    ("FullCount", ua.VariantType.Int16, 0, True),
    ("Message", ua.VariantType.String, "ready", True),
    ("Heartbeat", ua.VariantType.UInt32, 0, False),
)

#: 结构体定义。字段顺序 = 二进制 Body 里的排列顺序，名字只存在于定义里。
STRUCT_SPECS = {
    "RackStruct": (("Val", ua.VariantType.Int16, -1), ("Sts", ua.VariantType.Boolean, -1),
                   ("Name", ua.VariantType.String, -1)),
    "RackSlot": (("Index", ua.VariantType.UInt16, -1),
                 ("Main", "RackStruct", -1),           # 字符串 = 嵌套的自定义类型
                 ("Temps", ua.VariantType.Double, 1),  # 1 = 一维数组
                 ("Note", ua.VariantType.String, -1)),
}

#: 结构体变量的初值，按 STRUCT_SPECS 的顺序排（嵌套层用 dict）
SLOT_SPECS = (
    ("Slot01", {"Index": 1,
                "Main": {"Val": 37, "Sts": True, "Name": "A库空筒"},
                "Temps": [1.5, 2.25, -0.5],
                "Note": "ready"}),
)


def _data_type_id(ftype) -> ua.NodeId:
    """字段类型 → DataType 的 NodeId。内建类型用 ObjectIds 里的数字 id。"""
    if isinstance(ftype, str):
        raise ValueError("自定义类型要走 types 表")
    return ua.NodeId(getattr(ua.ObjectIds, ftype.name))


def _pack_struct(spec, values: dict, types: dict) -> bytes:
    """按字段声明顺序把 dict 打成结构体 Body（OPC UA 二进制编码）。"""
    out = b""
    for fname, ftype, rank in spec:
        v = values[fname]
        if isinstance(ftype, str):
            out += _pack_struct(STRUCT_SPECS[ftype], v, types)
        elif rank >= 0:
            out += ua_binary.pack_uatype_array(ftype, list(v))
        else:
            out += ua_binary.pack_uatype(ftype, v)
    return out


async def _make_struct_type(server, idx: int, name: str, spec, types: dict):
    """建一个带 DataTypeDefinition 的 Structure DataType。

    ``DataTypeDefinition`` 是 OPC UA 1.04 才有的属性，也是客户端唯一能拿到
    "字段名 + 字段类型"的地方——Body 里只有值，没有名字。
    """
    dt = await server.nodes.base_structure_type.add_data_type(ua.NodeId(name, idx), name)
    sdef = ua.StructureDefinition()
    sdef.BaseDataType = ua.NodeId(ua.ObjectIds.Structure)
    sdef.StructureType = ua.StructureType.Structure
    fields = []
    for fname, ftype, rank in spec:
        nid = types[ftype].nodeid if isinstance(ftype, str) else _data_type_id(ftype)
        fields.append(
            ua.StructureField(
                Name=fname,
                DataType=nid,
                ValueRank=rank,
                # asyncua 的 StructureField 默认 IsOptional=True，不显式关掉
                # 会被当成"可选字段"，解码时 EncodingMask 对不上
                IsOptional=False,
            )
        )
    sdef.Fields = fields
    await dt.write_data_type_definition(sdef)
    return dt

#: 业务 key -> 节点标识符。客户端订阅用的就是这套名字。
KEYS = {spec[0].lower(): spec[0] for spec in NODE_SPECS}


class MockOpcUaServer:
    """同进程 OPC UA 服务器，跑在自己的 asyncio 线程上。"""

    def __init__(self, endpoint: str = "opc.tcp://127.0.0.1:48400") -> None:
        self.endpoint = endpoint
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._nodes: dict[str, object] = {}
        self._stop_event: asyncio.Event | None = None
        #: 实际注册到的命名空间索引。**不要硬编码 2** —— asyncua 默认
        #: 已占用 ns=0（OPC UA）和 ns=1（服务器 URI），但新版可能预注册更多，
        #: 猜错就会 BadNodeIdUnknown。
        self.namespace_index: int | None = None

    # ------------------------------------------------------------------
    def start(self, timeout: float = 10.0) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._main, name="MockOpcUa", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError("模拟 OPC UA 服务器启动超时")
        if self._error is not None:
            raise self._error

    def stop(self, timeout: float = 5.0) -> None:
        loop, thread = self._loop, self._thread
        if loop is None or thread is None:
            return
        try:
            loop.call_soon_threadsafe(self._signal_stop)
        except RuntimeError:
            pass
        thread.join(timeout)
        self._thread = None
        self._loop = None

    def _signal_stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    def _main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        except BaseException as exc:  # noqa: BLE001 - 启动失败要回传给主线程
            self._error = exc
            self._ready.set()
        finally:
            # asyncua 服务器在内部起了 session 超时循环、订阅发布循环等任务，
            # 直接 close loop 会让它们变成 "Task was destroyed but it is pending"。
            # 这里统一取消并等它们收尾，输出才干净。
            try:
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:  # noqa: BLE001
                pass
            try:
                loop.close()
            except Exception:  # noqa: BLE001
                pass

    async def _serve(self) -> None:
        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        server.set_server_name("AppsManagers Mock OPC UA")
        # demo/回归不涉及证书，显式关掉安全策略，避免端点不匹配
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])

        idx = await server.register_namespace("http://appsmanagers.local/demo")
        self.namespace_index = idx
        rack = await server.nodes.objects.add_object(idx, "AppsManagers")
        group = await rack.add_object(idx, "Rack")

        for ident, vtype, init, writable in NODE_SPECS:
            # 必须显式给 NodeId：只传 idx 的话 asyncua 会分配数字 id（ns=2;i=3），
            # browse name 才是 "Lamp01"。真实 PLC（Siemens / Kepware）多用
            # 字符串 NodeId，这里保持一致才能演示 ``ns=2;s=Lamp01`` 这种写法。
            node = await group.add_variable(
                ua.NodeId(ident, idx), ident, ua.Variant(init, vtype)
            )
            # asyncua 的变量默认 AccessLevel 就带 CurrentWrite，只读节点必须
            # 显式清掉，否则 UaExpert / browse 脚本会把 Heartbeat 也标成 RW。
            await node.set_writable(writable)
            self._nodes[ident] = node

        # -- 结构体类型 + 结构体变量（回归"结构体展开"用）--
        types = {}
        for type_name in ("RackStruct", "RackSlot"):
            types[type_name] = await _make_struct_type(
                server, idx, type_name, STRUCT_SPECS[type_name], types
            )
        for ident, values in SLOT_SPECS:
            body = _pack_struct(STRUCT_SPECS["RackSlot"], values, types)
            node = await group.add_variable(
                ua.NodeId(ident, idx),
                ident,
                ua.Variant(
                    ua.ExtensionObject(TypeId=types["RackSlot"].nodeid, Body=body),
                    ua.VariantType.ExtensionObject,
                ),
                datatype=types["RackSlot"].nodeid,
            )
            self._nodes[ident] = node

        # 结构体数组：值是多个 ExtensionObject，验证"顶层就是数组"的分支
        slot_body_2 = _pack_struct(
            STRUCT_SPECS["RackSlot"],
            {"Index": 2,
             "Main": {"Val": -8, "Sts": False, "Name": "B库实料"},
             "Temps": [0.0],
             "Note": "busy"},
            types,
        )
        array_node = await group.add_variable(
            ua.NodeId("Slots", idx),
            "Slots",
            ua.Variant(
                [
                    ua.ExtensionObject(TypeId=types["RackSlot"].nodeid,
                                       Body=_pack_struct(STRUCT_SPECS["RackSlot"],
                                                         SLOT_SPECS[0][1], types)),
                    ua.ExtensionObject(TypeId=types["RackSlot"].nodeid, Body=slot_body_2),
                ],
                ua.VariantType.ExtensionObject,
            ),
            datatype=types["RackSlot"].nodeid,
        )
        # add_variable 没有 value_rank 参数，数组要单独写 ValueRank 属性，
        # 否则客户端会把它当标量读（结构体数组的回包是数组，标量解码必错）
        await array_node.write_attribute(
            ua.AttributeIds.ValueRank,
            ua.DataValue(ua.Variant(1, ua.VariantType.Int32)),
        )
        self._nodes["Slots"] = array_node

        self._stop_event = asyncio.Event()
        async with server:
            self._ready.set()
            task = asyncio.create_task(self._heartbeat())
            try:
                await self._stop_event.wait()
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _heartbeat(self) -> None:
        """让 Heartbeat 自己往上走，用来观察订阅是不是真的在推。"""
        node = self._nodes.get("Heartbeat")
        if node is None:
            return
        value = 0
        while True:
            await asyncio.sleep(0.5)
            value += 1
            try:
                await node.write_value(ua.Variant(value, ua.VariantType.UInt32))
            except Exception:  # noqa: BLE001
                return

    # ------------------------------------------------------------------
    def set_value(self, ident: str, value) -> bool:
        """从**任意线程**改一个节点的值。返回是否成功。"""
        node = self._nodes.get(ident)
        loop = self._loop
        if node is None or loop is None:
            return False
        spec = next((s for s in NODE_SPECS if s[0] == ident), None)
        vtype = spec[1] if spec else None
        fut = asyncio.run_coroutine_threadsafe(
            node.write_value(ua.Variant(value, vtype)), loop
        )
        try:
            fut.result(timeout=3)
            return True
        except Exception:  # noqa: BLE001
            return False

    def get_value(self, ident: str, timeout: float = 3.0):
        node = self._nodes.get(ident)
        loop = self._loop
        if node is None or loop is None:
            return None
        fut = asyncio.run_coroutine_threadsafe(node.read_value(), loop)
        try:
            return fut.result(timeout=timeout)
        except Exception:  # noqa: BLE001
            return None

    def node_ids(self, namespace: int | None = None) -> dict[str, str]:
        """``{业务 key: NodeId 字符串}``，可直接丢给 ``OpcUaManager.subscribe``。

        ``namespace`` 不传就用实际注册到的索引（:attr:`namespace_index`）。
        """
        ns = self.namespace_index if namespace is None else namespace
        if ns is None:
            raise RuntimeError("服务器还没启动，拿不到命名空间索引")
        return {key.lower(): f"ns={ns};s={ident}" for key, ident in KEYS.items()}


def _main() -> int:
    """单独起一个模拟服务器（配合 ``opcua_browse.py`` / UaExpert 调试用）。"""
    import argparse
    import time

    parser = argparse.ArgumentParser(description="进程内 OPC UA 模拟服务器")
    parser.add_argument("--endpoint", default="opc.tcp://127.0.0.1:48400")
    args = parser.parse_args()

    server = MockOpcUaServer(args.endpoint)
    server.start()
    print(f"模拟 OPC UA 服务器: {args.endpoint}  ns={server.namespace_index}")
    print("节点:", ", ".join(server.node_ids().values()))
    print("Ctrl+C 退出")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n停止中…")
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
