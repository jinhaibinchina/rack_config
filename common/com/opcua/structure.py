"""结构体（ExtensionObject）展开。

真实 PLC 的结构变量在 OPC UA 里就是一个 ``ExpandedObject``（准确说是
``ua.ExtensionObject``）::

    ExtensionObject(TypeId=ns=3;i=5001, Body=b'\\x2a\\x00\\x01\\x0bA\\x00...')

``Body`` 是按 DataType 里字段声明顺序平铺的二进制，**没有字段名**。所以
"看到 ``Anode_MQ1`` 里面的 ``.Val`` / ``.Sts``" 只有两条路：

1. 服务端把成员也暴露成了子节点（Siemens S7-1500 就是，用 ``HasComponent``
   引用挂在结构变量下面），直接 browse 就有真正的 NodeId——能订阅、能写。
2. 服务端只给一整包 ``ExtensionObject``，那就读 DataType 的
   ``DataTypeDefinition`` 属性（OPC UA 1.04 起），按字段表把 ``Body`` 拆开。
   拆出来的成员是**只读快照**，没有独立 NodeId。

第 1 条在 :meth:`OpcUaManager.browse_children` 里优先尝试（拿到真节点就一定
用它）。这里实现第 2 条，作为兜底，同时被节点浏览器和扫描脚本共用。

解码器只做"看得懂"这件事，不做类型注册——不往 asyncua 的全局
``extension_objects_by_typeid`` 里塞动态生成的类。那套机制会污染进程全局状态，
而且多个 PLC、多个版本的同名结构体互相覆盖时很难查。

支持的编码
----------
* ``Structure``（0）：字段按顺序平铺；
* ``StructureWithOptionalFields``（1）：先读 UInt32 EncodingMask，
  bit0 表示"有可选字段被编码"，其余位按可选字段出现顺序对应（从 bit1 起）；
* ``Union``（2）：先读 UInt32 SwitchField，1 基索引指向唯一被编码的字段；
* 数组字段（``ValueRank >= 0``）：先 Int32 长度，再逐元素；
* 嵌套结构体、结构体数组递归展开。

不认识的类型（服务端没给 DataTypeDefinition 的自定义结构）会把错误写在
``StructField.error`` 上，不抛异常——一个字段看不懂不该让整棵树打不开。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from asyncua import ua
from asyncua.common.utils import Buffer
from asyncua.ua import ua_binary

#: 内建 DataType（ns=0 的数字 NodeId）→ VariantType。
#: 只列 1..25，正好是 OPC UA Part 6 表 1 的那批基础类型。
_BUILTIN: dict[int, ua.VariantType] = {
    1: ua.VariantType.Boolean,
    2: ua.VariantType.SByte,
    3: ua.VariantType.Byte,
    4: ua.VariantType.Int16,
    5: ua.VariantType.UInt16,
    6: ua.VariantType.Int32,
    7: ua.VariantType.UInt32,
    8: ua.VariantType.Int64,
    9: ua.VariantType.UInt64,
    10: ua.VariantType.Float,
    11: ua.VariantType.Double,
    12: ua.VariantType.String,
    13: ua.VariantType.DateTime,
    14: ua.VariantType.Guid,
    15: ua.VariantType.ByteString,
    16: ua.VariantType.XmlElement,
    17: ua.VariantType.NodeId,
    18: ua.VariantType.ExpandedNodeId,
    19: ua.VariantType.StatusCode,
    20: ua.VariantType.QualifiedName,
    21: ua.VariantType.LocalizedText,
    22: ua.VariantType.ExtensionObject,
    23: ua.VariantType.DataValue,
    24: ua.VariantType.Variant,
    25: ua.VariantType.DiagnosticInfo,
}

#: 名字里带 "Struct" / "Union" 的 StructureType 值，见 Part 3 §8.33
_STRUCT_OPTIONAL = int(ua.StructureType.StructureWithOptionalFields)
_UNION_TYPES = (
    int(ua.StructureType.Union),
    int(ua.StructureType.UnionWithSubtypedValues),
)


@dataclass
class StructField:
    """一个结构体成员。``aggregate`` 为真表示"值是子成员"，自己不带标量值。"""

    name: str
    type_name: str = ""
    value: Any = None
    rank: int = -1
    optional: bool = False
    aggregate: bool = False
    error: str = ""
    children: list["StructField"] = field(default_factory=list)

    def to_dict(self) -> dict:
        out: dict = {
            "name": self.name,
            "type": self.type_name,
            "value": self.value,
            "rank": self.rank,
            "optional": self.optional,
            "aggregate": self.aggregate,
        }
        if self.error:
            out["error"] = self.error
        if self.children:
            out["children"] = [c.to_dict() for c in self.children]
        return out

    def text(self) -> str:
        """界面/命令行用的一行摘要。"""
        if self.error:
            return f"<{self.error}>"
        if self.aggregate:
            return f"{{…}} {len(self.children)} 项"
        if self.rank >= 0 and isinstance(self.value, (list, tuple)):
            return _short_list(self.value)
        return _short(self.value)


@dataclass
class StructValue:
    """一个结构体变量的展开结果。"""

    type_name: str = ""
    fields: list[StructField] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.fields)

    def to_dict(self) -> dict:
        out = {"type": self.type_name, "fields": [f.to_dict() for f in self.fields]}
        if self.error:
            out["error"] = self.error
        return out


def _short(value: Any, limit: int = 80) -> str:
    if value is None:
        return "None"
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} 字节>"
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _short_list(value: list, limit: int = 4) -> str:
    head = ", ".join(_short(v, 24) for v in value[:limit])
    return f"[{head}{', …' if len(value) > limit else ''}]"


def _nid_key(node_id: ua.NodeId) -> str:
    try:
        return node_id.to_string()
    except Exception:  # noqa: BLE001
        return str(node_id)


def _ns_of(node_id: ua.NodeId) -> int:
    try:
        return int(node_id.NamespaceIndex)
    except Exception:  # noqa: BLE001
        return 0


class StructureReader:
    """把一个结构体变量的值拆成字段树。

    ``client`` 用来按 DataType 的 NodeId 取节点（DataTypeDefinition 只能从
    DataType 节点上读）。同一个 reader 会缓存已读过的定义/枚举表，扫描一整棵
    树时不要每次 new 一个。
    """

    def __init__(
        self,
        client,
        *,
        max_depth: int = 4,
        max_fields: int = 500,
        max_array: int = 500,
    ) -> None:
        self.client = client
        self.max_depth = max(1, int(max_depth))
        self.max_fields = max(1, int(max_fields))
        self.max_array = max(0, int(max_array))
        self._defs: dict[str, Any] = {}
        self._names: dict[str, str] = {}
        self._enums: dict[str, dict[int, str] | None] = {}

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    async def read(self, node) -> StructValue:
        """读 ``node`` 的当前值并展开。不抛异常，错误写在返回值里。"""
        try:
            dt_id = await self.datatype_of(node)
        except Exception as exc:  # noqa: BLE001
            return StructValue(error=f"读 DataType 失败: {exc}")
        if dt_id is None:
            return StructValue(error="节点没有 DataType 属性")

        type_name = await self.type_name(dt_id)
        try:
            value = await node.read_value()
        except Exception as exc:  # noqa: BLE001
            return StructValue(type_name=type_name, error=f"读值失败: {exc}")
        return await self.decode(value, dt_id, type_name)

    async def decode(
        self, value: Any, dt_id: ua.NodeId, type_name: str = ""
    ) -> StructValue:
        """把已经读到的值拆开（扫描时值是顺带读的，不用再读一遍）。"""
        name = type_name or await self.type_name(dt_id)
        if isinstance(value, (list, tuple)):
            # 结构体数组：外层没有字段名，用 [0] / [1] 区分
            out: list[StructField] = []
            for i, item in enumerate(value):
                if i >= self.max_array:
                    out.append(StructField(name=f"[{i}+]", type_name=name,
                                           error=f"数组超过 {self.max_array} 项，已截断"))
                    break
                out.append(await self._as_field(f"[{i}]", dt_id, item, -1, 0))
            return StructValue(type_name=name, fields=out)

        if not isinstance(value, ua.ExtensionObject):
            return StructValue(
                type_name=name,
                error=f"值不是 ExtensionObject（实际 {type(value).__name__}）",
            )
        if not value.Body:
            return StructValue(type_name=name, error="ExtensionObject 的 Body 为空")

        definition = await self._definition(dt_id)
        if definition is None:
            return StructValue(
                type_name=name,
                error="服务端未提供 DataTypeDefinition，只能按整包字节显示",
            )
        if not isinstance(definition, ua.StructureDefinition):
            return StructValue(type_name=name, error="该 DataType 不是结构体定义")

        # 已知类型（同一个进程里注册过）时 Body 可能已经是 dataclass 了
        if not isinstance(value.Body, (bytes, bytearray)):
            return StructValue(
                type_name=name,
                fields=await self._fields_from_object(value.Body, definition, 0),
            )

        try:
            buf = Buffer(bytes(value.Body))
            fields = await self._decode_fields(buf, definition, 0)
        except Exception as exc:  # noqa: BLE001
            return StructValue(type_name=name, error=f"解码失败: {exc}")
        return StructValue(type_name=name, fields=fields)

    # ------------------------------------------------------------------
    # DataType 元信息
    # ------------------------------------------------------------------
    async def datatype_of(self, node) -> ua.NodeId | None:
        dv = await node.read_attribute(ua.AttributeIds.DataType)
        inner = getattr(dv, "Value", None)
        value = inner.Value if isinstance(inner, ua.Variant) else inner
        return value if isinstance(value, ua.NodeId) else None

    async def type_name(self, dt_id: ua.NodeId) -> str:
        key = _nid_key(dt_id)
        cached = self._names.get(key)
        if cached is not None:
            return cached
        name = key
        try:
            bname = await self.client.get_node(dt_id).read_browse_name()
            name = bname.Name or key
        except Exception:  # noqa: BLE001
            pass
        self._names[key] = name
        return name

    async def _definition(self, dt_id: ua.NodeId):
        """读 DataType 的 DataTypeDefinition 属性（带缓存，失败也缓存）。"""
        key = _nid_key(dt_id)
        if key in self._defs:
            return self._defs[key]
        result = None
        try:
            result = await self.client.get_node(dt_id).read_data_type_definition()
        except Exception:  # noqa: BLE001 - 老服务端没有这个属性
            result = None
        if isinstance(result, ua.ExtensionObject):
            # 客户端没注册这个类型时拿到的是裸 Body，按 StructureDefinition 再解一次
            try:
                body = result.Body
                if isinstance(body, (bytes, bytearray)):
                    result = ua_binary.from_binary(ua.StructureDefinition, Buffer(body))
                else:
                    result = None
            except Exception:  # noqa: BLE001
                result = None
        if not isinstance(result, (ua.StructureDefinition, ua.EnumDefinition)):
            result = None
        self._defs[key] = result
        return result

    async def _enum_names(self, dt_id: ua.NodeId) -> dict[int, str] | None:
        """枚举 → ``{整数值: 文本}``。取 EnumStrings / EnumValues 属性。"""
        key = _nid_key(dt_id)
        if key in self._enums:
            return self._enums[key]
        table: dict[int, str] | None = None
        try:
            node = self.client.get_node(dt_id)
            for desc in await node.get_children_descriptions():
                name = desc.BrowseName.Name
                if name not in ("EnumStrings", "EnumValues"):
                    continue
                value = await self.client.get_node(desc.NodeId).read_value()
                if name == "EnumStrings":
                    table = {i: str(v) for i, v in enumerate(value or [])}
                else:
                    table = {
                        int(v.Value): getattr(v.DisplayName, "Text", "") or str(v.Value)
                        for v in (value or [])
                    }
                break
        except Exception:  # noqa: BLE001
            table = None
        self._enums[key] = table
        return table

    # ------------------------------------------------------------------
    # 解码
    # ------------------------------------------------------------------
    async def _decode_fields(
        self, buf: Buffer, definition: ua.StructureDefinition, depth: int
    ) -> list[StructField]:
        if depth >= self.max_depth:
            return [StructField(name="…", error=f"嵌套超过 {self.max_depth} 层，未展开")]

        specs = list(definition.Fields or [])
        if not specs:
            return []
        if len(specs) > self.max_fields:
            specs = specs[: self.max_fields]

        present = [True] * len(specs)
        stype = int(definition.StructureType or 0)
        if stype == _STRUCT_OPTIONAL:
            mask = int(ua_binary.unpack_uatype(ua.VariantType.UInt32, buf))
            has_optional = bool(mask & 0x01)
            bit = 1
            for i, spec in enumerate(specs):
                if spec.IsOptional:
                    present[i] = bool(has_optional and (mask >> bit) & 0x01)
                    bit += 1
        elif stype in _UNION_TYPES:
            switch = int(ua_binary.unpack_uatype(ua.VariantType.UInt32, buf))
            present = [switch != 0 and i == switch - 1 for i in range(len(specs))]

        out: list[StructField] = []
        for i, spec in enumerate(specs):
            name = spec.Name or f"field{i}"
            if not present[i]:
                out.append(
                    StructField(
                        name=name,
                        type_name=await self.type_name(spec.DataType),
                        optional=bool(spec.IsOptional),
                        error="未编码",
                    )
                )
                continue

            rank = -1 if spec.ValueRank is None else int(spec.ValueRank)
            dt_id = spec.DataType
            dt_name = await self.type_name(dt_id)
            item = StructField(
                name=name, type_name=dt_name, rank=rank, optional=bool(spec.IsOptional)
            )
            try:
                if rank >= 0:
                    await self._decode_array(buf, dt_id, dt_name, item, depth)
                else:
                    await self._decode_into(buf, dt_id, dt_name, item, depth)
            except Exception as exc:  # noqa: BLE001 - 流已经错位，后面没法继续
                item.error = f"解码失败: {exc}"
                out.append(item)
                break
            out.append(item)
        return out

    async def _decode_array(
        self,
        buf: Buffer,
        dt_id: ua.NodeId,
        dt_name: str,
        item: StructField,
        depth: int,
    ) -> None:
        count = int(ua_binary.unpack_uatype(ua.VariantType.Int32, buf))
        if count < 0:  # -1 表示 Null 数组
            item.value = None
            return
        if count > self.max_array:
            raise ValueError(f"数组长度 {count} 超过上限 {self.max_array}")
        # 结构体数组：每个元素没有名字，用 [i] 挂成子节点
        if await self._is_struct(dt_id):
            kids: list[StructField] = []
            for i in range(count):
                kid = StructField(name=f"[{i}]", type_name=dt_name, aggregate=True)
                await self._decode_into(buf, dt_id, dt_name, kid, depth)
                kids.append(kid)
            item.aggregate = True
            item.children = kids
            return
        values = []
        for _ in range(count):
            values.append(await self._scalar(buf, dt_id, dt_name))
        item.value = values

    async def _decode_into(
        self,
        buf: Buffer,
        dt_id: ua.NodeId,
        dt_name: str,
        item: StructField,
        depth: int,
    ) -> None:
        """把一个标量/嵌套结构体读进 ``item``（结构体走 children）。"""
        if await self._is_struct(dt_id):
            definition = await self._definition(dt_id)
            if definition is None or not isinstance(definition, ua.StructureDefinition):
                raise ValueError(f"{dt_name} 缺少 DataTypeDefinition，无法确定字段")
            item.aggregate = True
            item.children = await self._decode_fields(buf, definition, depth + 1)
            return
        item.value = await self._scalar(buf, dt_id, dt_name)

    async def _scalar(self, buf: Buffer, dt_id: ua.NodeId, dt_name: str) -> Any:
        builtin = _builtin_type(dt_id)
        if builtin is not None:
            return ua_binary.unpack_uatype(builtin, buf)
        table = await self._enum_names(dt_id)
        if table is not None:
            raw = int(ua_binary.unpack_uatype(ua.VariantType.Int32, buf))
            return table.get(raw, raw)
        raise ValueError(f"不认识的字段类型 {dt_name}（{_nid_key(dt_id)}）")

    async def _is_struct(self, dt_id: ua.NodeId) -> bool:
        definition = await self._definition(dt_id)
        return isinstance(definition, ua.StructureDefinition)

    async def _as_field(
        self,
        name: str,
        dt_id: ua.NodeId,
        value: Any,
        rank: int,
        depth: int,
    ) -> StructField:
        """把结构体数组里的一个已经解好的元素包成 ``StructField``。"""
        item = StructField(name=name, type_name=await self.type_name(dt_id), rank=rank)
        if isinstance(value, ua.ExtensionObject):
            definition = await self._definition(dt_id)
            if definition is None or not isinstance(definition, ua.StructureDefinition):
                item.error = "服务端未提供 DataTypeDefinition"
                return item
            if not isinstance(value.Body, (bytes, bytearray)):
                item.aggregate = True
                item.children = await self._fields_from_object(value.Body, definition, depth)
                return item
            try:
                item.aggregate = True
                item.children = await self._decode_fields(
                    Buffer(bytes(value.Body)), definition, depth + 1
                )
            except Exception as exc:  # noqa: BLE001
                item.error = f"解码失败: {exc}"
            return item
        item.value = value
        return item

    async def _fields_from_object(
        self, obj: Any, definition: ua.StructureDefinition, depth: int
    ) -> list[StructField]:
        """值已经是 dataclass（类型在进程里注册过）时直接按字段名取值。"""
        out: list[StructField] = []
        for i, spec in enumerate(definition.Fields or []):
            name = spec.Name or f"field{i}"
            raw = getattr(obj, name, None)
            item = StructField(name=name, type_name=await self.type_name(spec.DataType))
            if isinstance(raw, ua.ExtensionObject):
                sub = await self._as_field("", spec.DataType, raw, -1, depth)
                item.aggregate = True
                item.children = sub.children
                if sub.error:
                    item.error = sub.error
            else:
                item.value = raw
            out.append(item)
        return out


def is_builtin_datatype(dt_id: ua.NodeId | None) -> bool:
    """DataType 是不是 ns=0 的内建基础类型（Boolean / Int16 / String …）。"""
    return dt_id is not None and _builtin_type(dt_id) is not None


def is_struct_value(value: Any) -> bool:
    """判断一个读到的值是不是"结构体"（单个或数组）。

    只做外观判断，不读地址空间——浏览一个几百变量的 DB 时每多一次往返都是
    肉眼可见的卡顿。
    """
    if isinstance(value, ua.ExtensionObject):
        return True
    if isinstance(value, (list, tuple)) and value:
        return all(isinstance(v, ua.ExtensionObject) for v in value)
    return False


def _builtin_type(dt_id: ua.NodeId) -> ua.VariantType | None:
    """内建类型才有固定 VariantType；ns != 0 的一定是自定义类型。"""
    if _ns_of(dt_id) != 0:
        return None
    try:
        ident = int(dt_id.Identifier)
    except (TypeError, ValueError):
        return None
    return _BUILTIN.get(ident)


def flatten(fields: list[StructField], prefix: str = "") -> list[tuple[str, StructField]]:
    """把字段树压成 ``[(dotted_path, field)]``，给命令行表格/导出用。"""
    out: list[tuple[str, StructField]] = []
    for f in fields:
        path = f"{prefix}.{f.name}" if prefix else f.name
        out.append((path, f))
        if f.children:
            out.extend(flatten(f.children, path))
    return out
