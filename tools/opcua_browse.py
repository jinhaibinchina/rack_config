"""扫描 OPC UA 服务器上的节点，输出可直接喂给 ``OpcUaManager.subscribe`` 的映射表。

UaExpert 这类 GUI 一次只能看一个节点、手动抄 NodeId；料仓 32 盏灯 + 4 个文本
要一个个抄太慢，而且容易抄错引号（Siemens 的 NodeId 长这样：
``ns=3;s="DB_Rack"."Lamp01"``，引号是标识符的一部分，不能丢）。

这个脚本递归 browse 整棵树，把变量节点的 NodeId、数据类型、当前值、是否可写
列成表，并可用 ``--json`` 直接导出 ``{key: node_id}`` 给 ``subscribe()``。

跑法::

    # 匿名访问
    .venv/Scripts/python.exe tools/opcua_browse.py ^
        --endpoint opc.tcp://192.168.1.10:4840

    # S7-1500 默认要账号密码
    .venv/Scripts/python.exe tools/opcua_browse.py ^
        --endpoint opc.tcp://192.168.1.10:4840 --user admin --password ***

    # 只保留某个命名空间的变量（容器照常遍历，能下钻到深层）
    .venv/Scripts/python.exe tools/opcua_browse.py ^
        --endpoint opc.tcp://192.168.1.10:4840 --ns 3 --json res/opcua_nodes.json

    # 本机模拟服务器自测（另开一个终端跑 opcua_demo.py --no-server 不行，
    # 直接用 mock server 起一个）
    .venv/Scripts/python.exe tools/opcua_browse.py --endpoint opc.tcp://127.0.0.1:48400

深度说明：默认 **不限深度**（``--depth 0``）。真实设备的变量经常埋在 8 层
以上，而地址空间本身就是有限的有向图（有 ``seen`` 去重 + ``--max-nodes``
兜底），没有必要人为设层数上限。

命名空间说明：``--ns`` 只过滤**收进结果的变量**，不参与遍历。真实 PLC 的
中间容器通常在 ns=0（DeviceSet / DataBlocksGlobal 之类），变量才在 ns=3；
按命名空间剪枝会在第 1 层就把树砍断。

结构体说明：值为 ``ExtensionObject`` 的变量默认展开（``--no-struct`` 关掉）。
服务端把成员挂成了子节点（Siemens S7-1500 就是这样）时，走的是普通浏览，
列出来的是**真 NodeId**，能订阅、能写；只给一整包字节的服务端则按
``DataTypeDefinition`` 解码，成员只有名字/类型/值、没有 NodeId，导出时会放进
JSON 的 ``struct_members`` 段而不是 ``nodes`` 映射表。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asyncua import Client, ua

# AccessLevel 位掩码与判断逻辑统一放在 common/com/opcua（asyncua 的
# ua.AccessLevel 是位序号而不是位掩码，坑见那边的注释）
from common.com.opcua import is_standard_subtree, is_writable as _is_writable
from common.com.opcua.structure import StructureReader, flatten
from tools.opcua_json import build_unique_keys, dump_json


@dataclass
class NodeInfo:
    path: str
    node_id: str
    name: str
    namespace: int
    data_type: str = ""
    value: object = None
    writable: bool = False
    error: str = ""
    #: 结构体解码出来的成员：只有值，没有 NodeId（不能订阅/写）
    synthetic: bool = False
    has_children: bool = False

    @property
    def key(self) -> str:
        """从 browse name 生成业务 key：``Lamp01`` -> ``lamp01``。"""
        base = re.sub(r"[^0-9A-Za-z_]+", "_", self.name).strip("_").lower()
        return base or "node"


@dataclass
class ScanStats:
    folders: int = 0
    variables: int = 0
    structs: int = 0
    struct_members: int = 0
    errors: int = 0
    truncated: bool = False
    #: 因深度上限停下（``False`` 表示是撞了 ``max_nodes``）
    truncated_by_depth: bool = False
    by_namespace: dict[int, int] = field(default_factory=dict)


async def _read_writable(node) -> bool:
    """判断"当前用户能不能写"。

    ``AccessLevel`` 是节点能力，``UserAccessLevel`` 是本次会话的权限——
    真实 PLC 上两者可能不同（比如节点支持写、但这个账号只给读），
    所以取交集，而不是只看其中一个。
    """
    result = True
    for attr in (ua.AttributeIds.AccessLevel, ua.AttributeIds.UserAccessLevel):
        try:
            dv = await node.read_attribute(attr)
        except Exception:  # noqa: BLE001
            continue
        inner = dv.Value
        if not isinstance(inner, ua.Variant):
            continue
        if not _is_writable(inner.Value):
            return False
    return result


def _looks_like_struct(info: NodeInfo) -> bool:
    """该变量该不该试着展开（先找真子节点，再退回按定义解码）。

    **不能只认 ``data_type == "ExtensionObject"``**。S7-1500 / 汇川这类服务端
    对自定义结构体，``read_data_type_as_variant_type()`` 沿 HasSubtype 反查基类
    时经常落到 ``Variant``，甚至直接抛异常；而成员其实是挂在 HasComponent 下的
    真节点。漏判的后果就是整包变量只导出 1 条、内部成员全不见。
    """
    if info.data_type in ("ExtensionObject", "Variant"):
        return True
    if info.error:  # DataType 映射失败，多半是自定义类型
        return True
    value = info.value
    if isinstance(value, ua.ExtensionObject):
        return True
    if (
        isinstance(value, (list, tuple))
        and value
        and isinstance(value[0], ua.ExtensionObject)
    ):
        return True
    return False


async def scan(
    client: Client,
    *,
    root_node=None,
    max_depth: int = 0,
    namespace: int | None = None,
    max_nodes: int = 20000,
    skip_standard: bool = True,
    expand_struct: bool = True,
    struct_depth: int = 3,
    verbose: bool = False,
) -> tuple[list[NodeInfo], ScanStats]:
    """递归遍历地址空间，收集变量节点。

    ``max_depth <= 0`` 表示**不限深度**（默认）——地址空间本身就是有限的有向
    图，再加上 ``seen`` 去重和 ``max_nodes`` 兜底，不需要人为设一个层数上限。
    真实设备的变量经常埋在 8 层以上，设死上限只会让人以为"没节点"。

    ``namespace`` 只过滤**收进结果的变量**，不参与遍历剪枝。容器节点无论属于
    哪个命名空间都会继续往下走，否则容器在 ns=0、变量在 ns=3 的设备会一条都扫不到。

    ``expand_struct`` 打开时，值为 ExtensionObject 的变量会被展开：服务端把
    成员暴露成子节点（Siemens 就是这样）就照常往下递归，拿到的是真 NodeId；
    只给整包字节的则按 DataTypeDefinition 解码，成员标 ``synthetic=True``，
    有值但没有 NodeId（订阅不了，只能看）。
    """
    stats = ScanStats()
    found: list[NodeInfo] = []
    seen: set[str] = set()
    reader = StructureReader(client, max_depth=max(1, struct_depth))

    root = root_node if root_node is not None else client.nodes.objects

    async def walk_struct(node, info: NodeInfo, path: str, depth: int) -> None:
        """展开一个 ExtensionObject 变量。"""
        stats.structs += 1
        # 路线 1：成员就是子节点。Siemens S7-1500 把结构体成员挂成 HasComponent，
        # 这些是真节点，能订阅、能写，比解码出来的快照有用得多。
        try:
            child_nodes = await node.get_children()
        except Exception:  # noqa: BLE001
            child_nodes = []
        if child_nodes:
            info.has_children = True
            await walk(node, path, depth + 1)
            return

        # 路线 2：只给一整包字节，按 DataTypeDefinition 拆。
        # 值不是 ExtensionObject 的普通变量（只是被 _looks_like_struct 因为
        # DataType=Variant 误捞进来）直接放过，别把"不是结构体"写进 error。
        if not isinstance(info.value, (ua.ExtensionObject, list, tuple)):
            return
        result = await reader.read(node)
        if not result.fields:
            info.error = info.error or result.error
            if verbose and result.error:
                print(f"    ! {path}: {result.error}", file=sys.stderr)
            return
        info.has_children = True
        members = flatten(result.fields)
        for sub_path, fld in members:
            found.append(
                NodeInfo(
                    path=f"{path}.{sub_path}",
                    node_id="",
                    name=fld.name,
                    namespace=info.namespace,
                    data_type=fld.type_name,
                    value=None if fld.aggregate else fld.value,
                    writable=False,
                    error=fld.error,
                    synthetic=True,
                    has_children=bool(fld.children),
                )
            )
        stats.struct_members += len(members)

    async def walk(node, path: str, depth: int) -> None:
        if len(found) >= max_nodes:
            stats.truncated = True
            return
        if max_depth > 0 and depth > max_depth:
            stats.truncated = True
            stats.truncated_by_depth = True
            return
        try:
            children = await node.get_children()
        except Exception as exc:  # noqa: BLE001 - 单个子树读不了不该中断整棵树
            stats.errors += 1
            if verbose:
                print(f"    ! {path}: {exc}", file=sys.stderr)
            return

        for child in children:
            ref = child.nodeid
            nid = ref.to_string()
            if nid in seen:
                continue
            seen.add(nid)

            try:
                browse_name = await child.read_browse_name()
                name = browse_name.Name
            except Exception:  # noqa: BLE001
                stats.errors += 1
                continue

            child_path = f"{path}/{name}" if path else name
            ns = ref.NamespaceIndex

            # 只剪 ns=0 的内建类型/服务子树，其余容器一律递归。
            if skip_standard and is_standard_subtree(name, ns):
                continue

            try:
                node_class = await child.read_node_class()
            except Exception:  # noqa: BLE001
                stats.errors += 1
                continue

            if node_class == ua.NodeClass.Variable:
                # 命名空间过滤只作用在这里：变量要不要收进结果。
                # 不指定 --ns 时仍排除 ns=0 的变量——那是方法参数
                # （InputArguments/OutputArguments）、ServerStatus 这类内建，
                # 不是业务点，混进映射表只会碍事。要看就显式 --ns 0。
                if namespace is None:
                    if ns == 0:
                        continue
                elif ns != namespace:
                    continue
                info = NodeInfo(
                    path=child_path,
                    node_id=nid,
                    name=name,
                    namespace=ns,
                )
                try:
                    vtype = await child.read_data_type_as_variant_type()
                    info.data_type = vtype.name
                except Exception as exc:  # noqa: BLE001
                    info.error = str(exc)
                try:
                    info.value = await child.read_value()
                except Exception as exc:  # noqa: BLE001
                    info.error = info.error or str(exc)
                try:
                    info.writable = await _read_writable(child)
                except Exception:  # noqa: BLE001
                    pass

                found.append(info)
                stats.variables += 1
                stats.by_namespace[ns] = stats.by_namespace.get(ns, 0) + 1
                if verbose:
                    print(f"    {nid:<45} {info.data_type:<10} {child_path}")
                if expand_struct and _looks_like_struct(info):
                    await walk_struct(child, info, child_path, depth)
            else:
                stats.folders += 1
                await walk(child, child_path, depth + 1)

    await walk(root, "", 0)
    return found, stats


def _fmt_value(info: NodeInfo, width: int = 22) -> str:
    text = repr(info.value)
    if len(text) > width:
        text = text[: width - 3] + "..."
    return text


def print_table(nodes: list[NodeInfo]) -> None:
    if not nodes:
        print("  （没扫到变量节点）")
        return
    # 按 NodeId 长度自适应，Siemens 的地址能到 50+ 字符
    lengths = [len(n.node_id) for n in nodes if n.node_id]
    id_width = min(max(lengths or [12]), 60)
    type_width = min(max([9] + [len(n.data_type) for n in nodes]), 20)
    print(f"  {'NodeId':<{id_width}}  {'类型':<{type_width}} {'W':<2} {'当前值':<22} 路径")
    print(f"  {'-' * id_width}  {'-' * type_width} {'--'} {'-' * 22} {'-' * 24}")
    for info in nodes:
        mark = "- " if info.synthetic else ("RW" if info.writable else "R ")
        node_id = info.node_id or "（成员）"
        print(
            f"  {node_id:<{id_width}}  {info.data_type:<{type_width}} {mark} "
            f"{_fmt_value(info):<22} {info.path}"
        )


def print_tree(nodes: list[NodeInfo]) -> None:
    """按路径层级缩进打印，方便对照 PLC 里的 DB / 变量结构。"""
    for info in nodes:
        # 结构体成员用 '.' 连接（``Rack/Slot01.Val``），层级要一起算
        depth = info.path.count("/") + info.path.count(".")
        indent = "  " + "    " * depth
        mark = "-" if info.synthetic else ("*" if info.writable else " ")
        node_id = info.node_id or "（无独立 NodeId）"
        print(f"{indent}{mark}{info.name:<24} {info.data_type:<9} {node_id}")


def build_subscription_map(nodes: list[NodeInfo]) -> dict[str, str]:
    """``{key: node_id}``，key 从 NodeId 路径生成并保留数组下标。

    同名点（如 ``Alarms2HMII[0..4].AlarmCode``）不再叫 ``alarmcode_2``，
    而是 ``alarms2hmii_0_alarmcode``…；不冲突的点保持短名。
    结构体解码成员没有 NodeId，跳过（订阅会 BadNodeIdUnknown）。
    """
    items = [
        (info.name, info.node_id, info.path)
        for info in nodes
        if not info.synthetic and info.node_id
    ]
    return build_unique_keys(items)


async def run(args) -> int:
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)

    client = Client(url=args.endpoint, timeout=args.timeout)
    if args.user:
        client.set_user(args.user)
        client.set_password(args.password or "")

    print(f"连接 {args.endpoint} …", flush=True)
    try:
        await client.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"连接失败: {exc}", file=sys.stderr)
        return 2

    try:
        depth_text = "不限" if args.depth <= 0 else str(args.depth)
        start_text = args.start or "Objects"
        print(f"已连接。开始扫描（起点 {start_text}，最大深度 {depth_text}，命名空间 "
              f"{'全部' if args.ns is None else args.ns}）…\n")

        root = (
            client.get_node(args.start) if args.start else client.nodes.objects
        )
        nodes, stats = await scan(
            client,
            root_node=root,
            max_depth=args.depth,
            namespace=args.ns,
            max_nodes=args.max_nodes,
            expand_struct=not args.no_struct,
            struct_depth=args.struct_depth,
            verbose=args.verbose,
        )

        if args.tree:
            print_tree(nodes)
        else:
            print_table(nodes)

        real = sum(1 for n in nodes if not n.synthetic)
        print(
            f"\n  目录 {stats.folders} 个，变量 {stats.variables} 个"
            + (f"，结构体 {stats.structs} 个（成员 {stats.struct_members} 项）"
               if stats.structs else "")
            + (f"，错误 {stats.errors} 个" if stats.errors else "")
        )
        if real != stats.variables:
            print(f"  其中可直接订阅的节点 {real} 个（结构体成员没有 NodeId，不能订阅）")
        if stats.by_namespace:
            detail = "，".join(f"ns={k}:{v}" for k, v in sorted(stats.by_namespace.items()))
            print(f"  按命名空间：{detail}")
        if stats.truncated:
            if stats.truncated_by_depth:
                print(f"  ⚠ 已到深度上限 {args.depth}，更深处的变量没扫（去掉 --depth 即不限）")
            else:
                print(f"  ⚠ 已达变量数上限 {args.max_nodes}，结果可能不完整（调大 --max-nodes）")

        if args.start and not nodes and not stats.folders:
            print(
                f"  ⚠ 起点 {args.start} 下什么都没读到，确认这个 NodeId 是否存在"
                f"（错误 {stats.errors} 次）"
            )

        if args.json:
            mapping = build_subscription_map(nodes)
            by_id = {n.node_id: n for n in nodes if n.node_id}
            payload = {
                "endpoint": args.endpoint,
                "count": len(mapping),
                "nodes": mapping,
                "detail": [
                    {
                        "key": k,
                        "node_id": v,
                        "type": by_id[v].data_type if v in by_id else "",
                        "writable": by_id[v].writable if v in by_id else False,
                    }
                    for k, v in mapping.items()
                ],
                # 结构体成员没有 NodeId，进不了映射表，但路径和当前值对调试有用
                "struct_members": [
                    {
                        "path": n.path,
                        "type": n.data_type,
                        "value": n.value,
                        "error": n.error,
                    }
                    for n in nodes
                    if n.synthetic
                ],
            }
            dump_json(args.json, payload)
            print(f"\n  订阅映射已写入 {args.json}（{len(mapping)} 条）")
            if payload["struct_members"]:
                print(
                    f"  另有 {len(payload['struct_members'])} 个结构体成员只写了路径"
                    f"和值（struct_members 段），它们没有 NodeId，不能订阅"
                )
            print("  用法：mgr.subscribe(json.load(open(...))['nodes'])")
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    return 0 if nodes else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="扫描 OPC UA 地址空间，导出 NodeId 映射表",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--endpoint", required=True, help="opc.tcp://host:4840")
    parser.add_argument("--user", default="", help="用户名（S7-1500 默认要鉴权）")
    parser.add_argument("--password", default="", help="密码")
    parser.add_argument(
        "--start",
        default="",
        help='从该 NodeId 开始扫（默认 Objects 根）。'
        "例：--start 'ns=3;s=\"AGV-Rack\"'",
    )
    parser.add_argument(
        "--ns",
        type=int,
        default=None,
        help="只保留该命名空间的变量（不影响遍历，容器照常往下走）",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=0,
        help="最大递归深度，0 或负数表示不限（默认 0）",
    )
    parser.add_argument("--max-nodes", type=int, default=20000, help="变量数上限")
    parser.add_argument("--timeout", type=float, default=10.0, help="单请求超时秒")
    parser.add_argument("--json", default="", help="导出订阅映射到该 JSON 文件")
    parser.add_argument(
        "--no-struct",
        action="store_true",
        help="不展开结构体变量（默认展开：成员是子节点就列真节点，否则按定义解码）",
    )
    parser.add_argument(
        "--struct-depth",
        type=int,
        default=3,
        help="结构体嵌套展开层数（默认 3；再深的成员显示类型名不展开）",
    )
    parser.add_argument("--tree", action="store_true", help="按层级缩进打印，而不是表格")
    parser.add_argument("--verbose", action="store_true", help="逐个节点打印进度")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
