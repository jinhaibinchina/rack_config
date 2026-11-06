# -*- coding: utf-8 -*-
"""地址空间扫描回归：混合命名空间 + 深层嵌套。

不需要真实 PLC，也不需要 mock server——这里自己造一棵"像真实 S7-1500"的树::

    Objects(ns=0) -> DeviceSet(ns=0) -> S7-1500(ns=0) -> DataBlocksGlobal(ns=0)
        -> "DB_Rack"(ns=2) -> Level1(ns=2) -> ... -> Level12(ns=2) -> Var12

这条结构的要点是：**中间容器全在 ns=0，变量在 ns=2**。旧实现按命名空间
剪枝（`ns == 0 and path: continue` / `ns != namespace: continue`），会在第 1 层
就把整棵树砍断，`--depth 8` 扫出的变量是 0 个。

跑法::

    .venv/Scripts/python.exe tools/verify_opcua_scan.py

反向验证：把 `scan()` 里的命名空间剪枝加回去（容器也按 ns 过滤），
"深层变量能扫到""--ns 仍能下钻"两项必须失败。
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from asyncua import Client, Server, ua

from common.com.opcua import is_standard_subtree
from tools.opcua_browse import scan

PORT = 48512
ENDPOINT = f"opc.tcp://127.0.0.1:{PORT}"
NS = 2
DEEPEST = 12  # 变量埋在 12 层目录之下
#: 13 个常规变量 + Anode_MQ12 本身及其 Val / Sts 两个真成员
BASE_COUNT = DEEPEST + 1 + 3

_passed = 0
_failed: list[str] = []


def check(cond: bool, desc: str) -> bool:
    global _passed
    if cond:
        _passed += 1
        print(f"  ok   {desc}")
    else:
        _failed.append(desc)
        print(f"  FAIL {desc}")
    return cond


async def build_server() -> Server:
    srv = Server()
    await srv.init()
    srv.set_endpoint(ENDPOINT)
    ns = await srv.register_namespace("http://verify.local/scan")
    # 注册顺序决定索引，这里把上面的 NS 对齐
    if ns != NS:
        raise RuntimeError(f"命名空间索引不是 {NS}，实际 {ns}，测试常量需要同步改")

    objects = srv.nodes.objects
    # 中间容器：模拟 DeviceSet / 设备节点，全部落在 ns=0
    device_set = await objects.add_object(ua.NodeId("DeviceSet", 0), "DeviceSet")
    device = await device_set.add_object(ua.NodeId("S7-1500", 0), "S7-1500")
    dbs = await device.add_object(ua.NodeId("DataBlocksGlobal", 0), "DataBlocksGlobal")

    container = await dbs.add_object(ua.NodeId("DB_Rack", NS), "DB_Rack")
    await container.add_variable(
        ua.NodeId("Lamp01", NS), "Lamp01", ua.Variant(False, ua.VariantType.Boolean)
    )

    # 模拟 S7-1500 / 汇川的自定义结构体：成员挂在 HasComponent 下（真节点），
    # 但 DataType 沿 HasSubtype 反查落到 BaseDataType，客户端
    # read_data_type_as_variant_type() 只会返回 Variant(24) 而不是
    # ExtensionObject。旧扫描器只认 ExtensionObject，会漏掉整个内部结构。
    anode = await container.add_variable(
        ua.NodeId("Anode_MQ12", NS), "Anode_MQ12",
        ua.Variant(0, ua.VariantType.Int16),
        datatype=ua.NodeId(ua.ObjectIds.BaseDataType),
    )
    await anode.add_variable(
        ua.NodeId("Anode_MQ12.Val", NS), "Val", ua.Variant(37, ua.VariantType.Int16)
    )
    await anode.add_variable(
        ua.NodeId("Anode_MQ12.Sts", NS), "Sts", ua.Variant(True, ua.VariantType.Boolean)
    )

    cur = container
    for i in range(1, DEEPEST + 1):
        nxt = await cur.add_object(ua.NodeId(f"Level{i}", NS), f"Level{i}")
        await nxt.add_variable(
            ua.NodeId(f"Var{i}", NS), f"Var{i}", ua.Variant(i, ua.VariantType.Int16)
        )
        # 每 3 层插一个 ns=0 的容器，把"混合命名空间"这条真实情况覆盖到
        cur = nxt
        if i % 3 == 0:
            cur = await nxt.add_object(ua.NodeId(f"Bridge{i}", 0), f"Bridge{i}")
    return srv


async def run_checks() -> None:
    srv = await build_server()
    async with srv:
        await asyncio.sleep(0.2)
        client = Client(ENDPOINT)
        await client.connect()
        try:
            # --- 1. is_standard_subtree 的语义 ---------------------------
            print("\n[1] 标准子树判定")
            check(is_standard_subtree("Server", 0), "Server(ns=0) -> 剪")
            check(is_standard_subtree("TypeHierarchy", 0), "TypeHierarchy(ns=0) -> 剪")
            check(not is_standard_subtree("DeviceSet", 0), "DeviceSet(ns=0) -> 保留（关键）")
            check(not is_standard_subtree("Server", 3), "Server(ns=3) -> 保留（同名自定义节点）")
            check(not is_standard_subtree("Lamp01", NS), "Lamp01(ns=2) -> 保留")

            # --- 2. 不限深度能扫到最深层的变量 ---------------------------
            print("\n[2] 不限深度（默认 --depth 0）")
            nodes, stats = await scan(client, root_node=client.nodes.objects, max_depth=0)
            names = {n.name for n in nodes}
            check(len(nodes) == BASE_COUNT, f"扫到 {BASE_COUNT} 个变量（实得 {len(nodes)}）")
            check(f"Var{DEEPEST}" in names, f"最深处的 Var{DEEPEST} 也在结果里")
            check("Lamp01" in names, "靠上的 Lamp01 也在结果里")
            check(stats.truncated is False, "未触发截断")

            # --- 3. 标准变量不混进映射表 --------------------------------
            print("\n[3] 内建变量过滤")
            check(
                not any(n.namespace == 0 for n in nodes),
                "结果里没有 ns=0 的变量（方法参数 / ServerStatus 之类）",
            )
            check(
                all(n.node_id for n in nodes),
                "每个结果都有 NodeId",
            )

            # --- 4. --ns 只过滤输出，不影响下钻 -------------------------
            print("\n[4] 命名空间过滤不影响遍历")
            ns_nodes, ns_stats = await scan(
                client, root_node=client.nodes.objects, max_depth=0, namespace=NS
            )
            check(
                len(ns_nodes) == BASE_COUNT,
                f"指定 ns={NS} 仍能下钻到 ns=0 容器之下（实得 {len(ns_nodes)}）",
            )
            check(all(n.namespace == NS for n in ns_nodes), "结果全属于 ns=2")
            # 拿 ns=9（不存在）当反例：容器照样遍历，只是不收变量
            other, other_stats = await scan(
                client, root_node=client.nodes.objects, max_depth=0, namespace=9
            )
            check(other == [], "指定不存在的 ns -> 0 个变量")
            check(other_stats.folders > 0, "但容器仍被遍历（folders > 0）")

            # --- 5. 深度上限仍然有效 ------------------------------------
            print("\n[5] --depth 显式限深")
            shallow, shallow_stats = await scan(
                client, root_node=client.nodes.objects, max_depth=3
            )
            shallow_names = {n.name for n in shallow}
            check(len(shallow) < BASE_COUNT, f"depth=3 时结果更少（{len(shallow)} 个）")
            check(f"Var{DEEPEST}" not in shallow_names, "最深处的变量被挡在深度上限外")
            check(shallow_stats.truncated is True, "truncated 标记为 True")
            check(
                shallow_stats.truncated_by_depth is True,
                "truncated_by_depth 为 True（提示语才能说清是深度还是数量）",
            )

            # --- 6. 标准子树确实被剪掉 ----------------------------------
            print("\n[6] 内建子树剪枝")
            paths = " | ".join(n.path for n in nodes)
            check("Server" not in paths, "路径里没有 Server 子树（ns=0 内建已剪）")
            check("TypeHierarchy" not in paths, "路径里没有 TypeHierarchy 子树")
            check("DB_Rack" in paths, "自定义子树完整保留（路径带 DB_Rack）")

            # --- 7. 从任意容器起扫（对应 CLI 的 --start）---------------
            print("\n[7] 指定起点")
            rack = client.get_node(f"ns={NS};s=DB_Rack")
            sub, sub_stats = await scan(client, root_node=rack, max_depth=0)
            sub_names = {n.name for n in sub}
            check(len(sub) == BASE_COUNT, f"从 DB_Rack 起扫到 {BASE_COUNT} 个（实得 {len(sub)}）")
            check("Lamp01" in sub_names, "起点的直接子变量在结果里")
            check(all("/DB_Rack/" not in n.path for n in sub),
                  "路径是相对起点的（不再带 DB_Rack 前缀）")

            # --- 8. 导出的映射表能直接喂 subscribe ----------------------
            print("\n[8] 订阅映射")
            from tools.opcua_browse import build_subscription_map

            mapping = build_subscription_map(nodes)
            check(len(mapping) == len(nodes), f"映射条数与变量数一致（{len(mapping)}）")
            check(mapping.get("lamp01") == f"ns={NS};s=Lamp01", "Lamp01 的 key/NodeId 正确")
            check(mapping.get(f"var{DEEPEST}") == f"ns={NS};s=Var{DEEPEST}",
                  f"Var{DEEPEST} 的 key/NodeId 正确")
            check(len(set(mapping.values())) == len(mapping), "NodeId 无重复")

            # --- 9. 自定义结构体的真成员不能漏 ---------------------------
            # 现场症状：只导出一个 Anode_MQ12、内部成员全不见。原因是旧实现
            # 只在 data_type == "ExtensionObject" 时才检查变量有没有子节点，
            # 而这类服务端把 DataType 报成 Variant(24)。
            print("\n[9] 自定义结构体（DataType=Variant + HasComponent 成员）")
            from tools.opcua_browse import NodeInfo, _looks_like_struct

            check(
                _looks_like_struct(NodeInfo(path="", node_id="", name="", namespace=NS,
                                            data_type="Variant")),
                "Variant 被识别为可能的结构体",
            )
            check(
                not _looks_like_struct(NodeInfo(path="", node_id="", name="", namespace=NS,
                                                data_type="Int16", value=3)),
                "普通标量不触发额外展开请求",
            )
            struct_children = [n for n in nodes if n.name in ("Val", "Sts")]
            check(len(struct_children) == 2,
                  f"Anode_MQ12 的 2 个真成员被扫到（实得 {len(struct_children)}）")
            check(all(n.node_id for n in struct_children),
                  "真成员带 NodeId，可以直接订阅/写入")
            check(any(n.path.endswith("Anode_MQ12/Val") for n in struct_children),
                  "成员路径带父结构体名")
        finally:
            await client.disconnect()


def main() -> int:
    print("=" * 62)
    print("OPC UA 地址空间扫描回归（混合命名空间 + 深层嵌套）")
    print("=" * 62)
    try:
        asyncio.run(run_checks())
    except Exception:
        traceback.print_exc()
        _failed.append("脚本异常退出")

    print("\n" + "=" * 62)
    total = _passed + len(_failed)
    if _failed:
        print(f"结果：{_passed}/{total} 通过，{len(_failed)} 项失败")
        for name in _failed:
            print(f"  - {name}")
        return 1
    print(f"结果：{_passed}/{total} 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
