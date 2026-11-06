"""OPC UA 导出的编码兜底。

现场设备的字符串里偶尔带**孤立 UTF-16 代理项**（``\\udcxx``）。要分清两类，
处理方式完全不同：

1. **``\\udc80..\\udcff``（surrogateescape 产物）** —— 国产 PLC 把 GBK 字节当
   UTF-8 发过来，asyncua 在 ``ua_binary._String.unpack`` 里用
   ``errors="surrogateescape"`` 解码，每个非法字节变成一个低代理字符；
   ``_String.pack`` 编码时同样用 surrogateescape，**原样保留就能往返还原成
   服务端认得的字节**。这类字符在 NodeId 里尤其要保住：改成中文文本或
   ``\\udcb9`` 字面量都会让订阅拿到 ``BadNodeIdUnknown``。
   写盘时用 JSON 的 ``\\udcXX`` 转义，文件是合法 UTF-8，``json.load`` 又还原成
   同一个代理字符，双向无损。
2. **其他孤立代理（``\\ud800..\\udbff`` / ``\\udd00..\\udfff``）** —— 无法还原，
   退化成可见文本。

``clean_text()`` 只用于**界面显示**：把第 1 类试着按 GBK/UTF-8 解码成人能读的
中文，不改数据本身。``dump_json()`` 用于**写盘**：保留可逆性。
``restore_escaped()`` 负责把上一版误写成字面量的旧文件救回来。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

#: 数组下标 ``Alarms2HMII[0] -> Alarms2HMII_0_``，保留语义而不是丢掉
_INDEX = re.compile(r"\[(\d+)\]")

#: surrogateescape 产生的低代理字节段（U+DC80..U+DCFF）
_LOW_SURROGATES = re.compile(r"[\udc80-\udcff]+")
#: 其余无法还原的孤立代理
_OTHER_SURROGATES = re.compile(r"[\ud800-\udc7f\udd00-\udfff]")
#: 旧版导出文件里已经写成文本的字面量 ``\udcXX``（\udc + 两位字节）
_ESCAPED_LOW = re.compile(r"\\udc([89a-fA-F][0-9a-fA-F])")
#: JSON 文本里所有代理字符
_ANY_SURROGATES = re.compile(r"[\ud800-\udfff]+")


def _decode_run(raw: bytes) -> str:
    """把还原出来的原始字节按最可能的编码解释（显示用）。"""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def clean_text(text: str) -> str:
    """显示用：surrogateescape 片段尽量还原成中文，其余代理变可见文本。"""
    out = _LOW_SURROGATES.sub(
        lambda m: _decode_run(bytes(ord(c) - 0xDC00 for c in m.group())), text
    )
    return _OTHER_SURROGATES.sub(
        lambda m: f"\\u{ord(m.group()):04x}", out
    )


def restore_escaped(text: str) -> str:
    """把旧导出文件里的 ``\\udcXX`` 文本还原成代理字符，让 NodeId 能重新订阅。

    上一版 ``dump_json`` 曾把代理项写成可见字面量；那种文件直接订阅会失败，
    这里做一次反向还原，省得现场必须重新导出。
    """
    return _ESCAPED_LOW.sub(
        lambda m: chr(0xDC00 + int(m.group(1), 16)), text
    )


def dump_json(path: str | Path, payload: Any, *, default: Any = str) -> str:
    """写 JSON 并返回写出的文本：中文原样保留，代理项用**可逆**的 JSON 转义。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=default)
    text = _ANY_SURROGATES.sub(
        lambda m: "".join(f"\\u{ord(c):04x}" for c in m.group()), text
    )
    Path(path).write_bytes(text.encode("utf-8", errors="backslashreplace"))
    return text


# ----------------------------------------------------------------------
# 业务 key 命名
# ----------------------------------------------------------------------
def _norm(seg: str) -> str:
    """规范化一段路径：GBK 代理先显示成中文，数组下标保留，其余符号变下划线。"""
    seg = clean_text(seg)
    seg = _INDEX.sub(r"_\1_", seg)
    return re.sub(r"[^\w]+", "_", seg).strip("_").lower()


def semantic_key(*, node_id: str = "", path: str = "", name: str = "", depth: int = 1) -> str:
    """从 NodeId / 扫描路径生成业务 key，保留数组下标。

    ``Alarms2HMII[0].AlarmCode`` 取末尾 2 段 -> ``alarms2hmii_0_alarmcode``；
    取 1 段就是短名 ``alarmcode``。冲突时由 :func:`build_unique_keys` 自动
    多取父级，**不再加 ``_2`` 这种无语义的序号**。
    """
    parts: list[str] = []
    # 优先用 NodeId 的字符串标识符：设备侧最完整、一定含数组下标。
    # 扫描路径的末段可能只是 "[0]"，拿它当 key 会退化成 "0_alarmcode"。
    if ";s=" in node_id:
        ident = node_id.split(";s=", 1)[1]
        for prefix in ("|var|", "|appo|", "|obj|"):
            if ident.startswith(prefix):
                ident = ident[len(prefix):]
                break
        parts = [p for p in ident.split(".") if p]
    if not parts:
        parts = [p for p in path.split("/") if p]
    if not parts:
        parts = [name or "node"]
    segs = parts[-max(1, depth):]
    return "_".join(x for x in (_norm(s) for s in segs) if x) or "node"


def build_unique_keys(items: list[tuple[str, str, str]]) -> dict[str, str]:
    """``[(name, node_id, path), ...] -> {key: node_id}``。

    不冲突的点保持短名（``aallowmovejogp``）；同名点（比如 5 组报警数组）
    自动多取一层父级，得到 ``alarms2hmii_0_alarmcode`` …
    ``alarms2hmii_4_alarmcode``。只有整条路径都相同的真重复节点才退化为序号。
    """
    short = [
        semantic_key(node_id=nid, path=path, name=name, depth=1)
        for name, nid, path in items
    ]
    counts = Counter(short)
    out: dict[str, str] = {}
    for (name, nid, path), base in zip(items, short):
        if counts[base] == 1:
            key = base
        else:
            d = 2
            key = semantic_key(node_id=nid, path=path, name=name, depth=d)
            while key in out and out[key] != nid and d < 8:
                d += 1
                key = semantic_key(node_id=nid, path=path, name=name, depth=d)
        if key in out and out[key] != nid:
            n = 2
            while f"{key}_{n}" in out:
                n += 1
            key = f"{key}_{n}"
        out[key] = nid
    return out

