"""变量表 → OPC UA 节点的解析层。

页面里只写**变量表里的名字**（``GVL_HMI.wSysRun``、
``GVL_HMI.asServoStatus[1].fPositionNow``），由本模块解析成
``globalvars_tags.json`` 里真实存在的业务 key / NodeId。这样页面代码跟
设备名、命名空间、数组展开方式解耦，重新浏览导出后只要重跑
``tools/gen_hmi_tag_catalog.py``，页面不用改。

数据来源与可信度
-----------------
* ``opcua_nodes.json`` 的 ``verified``：真机浏览得到，**事实**；
* ``candidates``：按已验证节点的命名规则拼出来的，**推断、未核实**；
* ``aliases``：XML 变量表里的变量名 → 上述两类节点，含类型/维度/注释分组。

地址空间里目前只有 ``GVL_HMI`` 和 ``GVL_PARAMETERS`` 两张表
（见 ``globalvars_structure.json`` 的 children），``GVL`` 本体没有暴露节点。
因此 ``GVL.*`` 一律返回 ``verified=False``：页面显示「未接入」，不订阅、
不写入。这一点不能靠猜——猜出来的 NodeId 发下去只会拿到 BadNodeIdUnknown。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_NODES = DATA_DIR / "opcua_nodes.json"
DEFAULT_CATALOG = DATA_DIR / "gvl_catalog.json"

#: ``GVL_HMI.asServoStatus[1].fPositionNow`` -> 表 / 变量 / 下标 / 成员。
#: 变量名里可能有中文（``GVL_HMI.工程描述``），所以不用 ``[A-Za-z_]`` 开头。
_REF = re.compile(
    r"^(?P<table>\w+)\.(?P<name>[^\s.\[\]]+)"
    r"(?:\[(?P<index>\d+)\])?(?:\.(?P<member>[^\s.\[\]]+))?$"
)

_LOW_SURROGATES = re.compile(r"[\udc80-\udcff]+")
_OTHER_SURROGATES = re.compile(r"[\ud800-\udc7f\udd00-\udfff]")


def loose_key(name: str) -> str:
    """变量名 -> 导出清单里的短名（保留下划线、去掉其它符号）。"""
    return re.sub(r"[^0-9a-z_]+", "", name.lower()).strip("_")


def norm_key(name: str) -> str:
    """变量名 -> 去掉下划线后的短名（``wSysRun`` -> ``wsysrun``）。"""
    return re.sub(r"[^0-9a-z]+", "", name.lower())


def clean_text(text: Any) -> str:
    """显示用：把 PLC 字符串里的 GBK 代理字节还原成中文。

    NodeId 本身**不能**这样处理（会破坏服务端认得的原始字节），这里只用于
    界面文本。与 ``tools/opcua_json.clean_text`` 同规则，但不依赖 tools 包，
    打包时少一条隐式依赖。
    """
    if not isinstance(text, str):
        return str(text)

    def decode(match) -> str:
        raw = bytes(ord(ch) - 0xDC00 for ch in match.group())
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("latin-1")

    out = _LOW_SURROGATES.sub(decode, text)
    return _OTHER_SURROGATES.sub(lambda m: f"\\u{ord(m.group()):04x}", out)


@dataclass(frozen=True)
class TagRef:
    """一个页面显示/写入点的完整寻址信息。"""

    expr: str
    key: str | None
    node_id: str | None
    verified: bool
    label: str
    variable_type: str = ""
    shape: tuple = ()
    index: int | None = None
    member: str | None = None
    writable: bool = True
    unit: str = ""
    note: str = ""

    @property
    def connected(self) -> bool:
        return bool(self.key and self.verified)

    @property
    def status(self) -> str:
        if self.connected:
            return "已接入"
        return "未接入" if self.node_id else "变量表未找到"


class TagCatalog:
    """加载生成好的目录，把变量名解析成 :class:`TagRef`。"""

    def __init__(self, nodes_path: Path | str = DEFAULT_NODES,
                 catalog_path: Path | str = DEFAULT_CATALOG) -> None:
        self.nodes_path = Path(nodes_path)
        self.catalog_path = Path(catalog_path)
        payload = json.loads(self.nodes_path.read_text(encoding="utf-8"))
        self.endpoint: str = payload.get("endpoint", "")
        self.verified: dict[str, str] = payload.get("verified") or {}
        self.candidates: dict[str, str] = payload.get("candidates") or {}
        self.aliases: dict[str, dict] = payload.get("aliases") or {}
        # 导出时变量名会被拍平/改大小写（sucker_gearInOut_pos ->
        # sucker_gearinout_pos），页面按变量表原名写，这里做大小写不敏感索引。
        self._alias_lookup: dict[str, str] = {k.lower(): k for k in self.aliases}
        self._catalog: dict = {}
        if self.catalog_path.is_file():
            self._catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------
    def ref(self, expr: str, *, label: str = "", unit: str = "",
            writable: bool | None = None, note: str = "") -> TagRef:
        """把变量表表达式解析成节点。

        ``expr`` 支持三种写法：

        * ``GVL_HMI.wSysRun``                           标量
        * ``GVL_HMI.LOCAL_INPUT``  + ``index=``        数组整体节点
        * ``GVL_HMI.asServoStatus[1].fPositionNow``    展开的结构体成员

        找不到时不会抛异常，返回 ``verified=False`` 的 ref，页面据此显示
        「变量表未找到」，避免一个点写错拖垮整页。
        """
        match = _REF.match(expr.strip())
        if not match:
            return TagRef(expr, None, None, False, label or expr, note="表达式格式错误")
        table = match.group("table")
        name = match.group("name")
        index = int(match.group("index")) if match.group("index") else None
        member = match.group("member")
        lookup = self._alias_lookup.get(f"{table}.{name}".lower())
        alias = self.aliases.get(lookup) if lookup else None
        if alias is None:
            # 结构体成员在导出清单里被拍平成独立 key
            # （P_Storage_XX.x -> p_storage_xx_x），变量表里没有这个变量，
            # 但节点是真实浏览到的，按 NodeId 的表名校验后照样可以接。
            flat = loose_key(name)
            flat_id = self.verified.get(flat, "")
            if flat_id and f".{table}." in flat_id:
                return TagRef(expr, flat, flat_id, True, label or name,
                              writable=True if writable is None else writable,
                              unit=unit, note="导出清单里的拍平成员节点")
            return TagRef(expr, None, None, False, label or name,
                          note=f"变量表里没有 {table}.{name}")

        key = alias.get("key")
        node_id = alias.get("node_id")
        if member:
            # 浏览树里的成员路径有两种写法：数组元素带下标
            # （asServoStatus[1].fPositionNow），普通结构体不带父名
            # （CameraDatas 下的 xReady）。两种都要试，再去兜底按语义 key 猜。
            base = f"{name}[{index}]" if index is not None else name
            members = alias.get("members") or {}
            by_lower = {k.lower(): v for k, v in members.items()}
            key = (by_lower.get(f"{base}.{member}".lower())
                   or by_lower.get(member.lower())
                   or by_lower.get(f"{name}.{member}".lower()))
            if key is None:
                for segs in (
                    [name] + ([str(index)] if index is not None else []) + [member],
                    [member],
                ):
                    guess = "_".join(s.lower() for s in segs)
                    if guess in self.verified:
                        key = guess
                        break
            node_id = self.verified.get(key) if key else None
        elif index is not None and not alias.get("key"):
            key = None

        is_verified = bool(key and key in self.verified)
        if not is_verified:
            cand_key = alias.get("candidate_key")
            node_id = self.candidates.get(cand_key) if cand_key else None
            key = None

        # alias 的 shape 描述的是「整个数组变量」，不是单个结构体成员。
        # asServoStatus[1].fPositionNow 是标量，带上 [4] 会让演示数据/显示
        # 逻辑把它当成数组处理。
        shape = () if member else tuple(s for s in (alias.get("shape") or ()) if s)
        return TagRef(
            expr=expr,
            key=key,
            node_id=node_id,
            verified=is_verified,
            label=label or name,
            variable_type=str(alias.get("type") or ""),
            shape=shape,
            index=index,
            member=member,
            writable=bool(alias.get("writable", True)) if writable is None else writable,
            unit=unit,
            note=note or str(alias.get("comment") or alias.get("group") or ""),
        )

    def refs(self, *expressions: str) -> list[TagRef]:
        return [self.ref(expr) for expr in expressions]

    def member_ref(self, variable: str, member: str, *, index: int | None = None,
                   label: str = "", unit: str = "", writable: bool | None = None) -> TagRef:
        """拼 ``GVL_HMI.asServoStatus[1].fPositionNow`` 再解析，页面里更好读。"""
        expr = variable
        if index is not None:
            expr += f"[{index}]"
        if member:
            expr += f".{member}"
        return self.ref(expr, label=label, unit=unit, writable=writable)

    # ------------------------------------------------------------------
    # 订阅 / 读写映射
    # ------------------------------------------------------------------
    def subscribe_items(self, keys: Iterable[str] | None = None) -> dict[str, str]:
        """``{业务 key: NodeId}``，只取已验证节点。"""
        targets = set(keys) if keys is not None else set(self.verified)
        return {k: self.verified[k] for k in targets if k in self.verified}

    def node_id_of(self, key: str) -> str:
        return self.verified.get(key, self.candidates.get(key, key))

    def variable_rows(self, table: str) -> list[dict]:
        return list((self._catalog.get("variables") or {}).get(table) or [])

    def section_of(self, table: str, name: str) -> str:
        for row in self.variable_rows(table):
            if row.get("name") == name:
                return str(row.get("group") or "")
        return ""

    def stats(self) -> dict:
        aliases = list(self.aliases.values())
        return {
            "endpoint": self.endpoint,
            "verified_nodes": len(self.verified),
            "candidate_nodes": len(self.candidates),
            "variables": len(aliases),
            "resolved_variables": sum(1 for a in aliases if a.get("verified")),
            "unresolved_variables": sum(1 for a in aliases if not a.get("verified")),
        }


# ----------------------------------------------------------------------
# 值处理
# ----------------------------------------------------------------------
def array_items(value: Any, count: int = 0) -> list[Any]:
    """把 OPC UA 数组值摊平成一维列表。

    服务端给法不统一：BOOL 数组可能是 ``list[bool]``、``bytes``，多维数组
    （``REMOTE_INPUT[6,8]``）可能是嵌套 list 或直接给 48 个元素的扁平 list。
    取不到值时返回一串 ``None``，页面上就显示灰灯而不是误判成 OFF。
    """
    unknown: list[Any] = [None] * max(0, count)
    if value is None:
        return unknown
    if isinstance(value, (bytes, bytearray)):
        out = list(value)
    elif isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if isinstance(item, (list, tuple, bytes, bytearray)):
                out.extend(array_items(item))
            else:
                out.append(item)
    elif isinstance(value, str):
        out = [value]
    else:
        out = [value]
    if count and len(out) < count:
        out.extend([None] * (count - len(out)))
    return out


def index_of(value: Any, index: int, shape: tuple = ()) -> Any:
    """从数组/结构体值里取第 ``index`` 项；多维时按 shape 折算行。"""
    if index is None:
        return value
    row_size = int(shape[-1]) if shape else 0
    if row_size > 1 and len(shape) > 1:
        return value  # 多维交给页面自己按 shape 展开
    items = array_items(value, index + 1)
    return items[index] if index < len(items) else None


def format_value(value: Any, *, unit: str = "", precision: int = 2,
                 bool_text: tuple[str, str] = ("ON", "OFF")) -> str:
    """显示格式化。``None`` 固定显示 ``--``，与「值就是 0/False」区分开。"""
    if value is None:
        return "--"
    if isinstance(value, bool):
        return bool_text[0] if value else bool_text[1]
    if isinstance(value, float):
        text = f"{value:.{precision}f}"
    elif isinstance(value, (bytes, bytearray)):
        text = value.hex(" ")
    elif isinstance(value, (list, tuple)):
        text = f"[{', '.join(format_value(v, precision=precision) for v in value[:6])}" \
               + (", …]" if len(value) > 6 else "]")
    elif isinstance(value, str):
        text = clean_text(value)
    else:
        text = str(value)
    return f"{text} {unit}".strip() if unit else text


def as_bool(value: Any) -> bool | None:
    """把 PLC 值收敛成三态布尔：True / False / 未知(None)。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "on", "yes")
    return None


@dataclass
class PageSpec:
    """一个页面的注册信息（供挂载与预览共用）。"""

    page_id: str
    title: str
    subtitle: str
    card: str = ""
    factory: Any = None
    tags: list[str] = field(default_factory=list)

    def __repr__(self) -> str:  # 日志里别把工厂对象打出来
        return f"<PageSpec {self.page_id} {self.title} card={self.card}>"
