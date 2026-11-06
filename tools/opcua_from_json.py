"""用导出的节点 JSON 直接和 PLC 通信（示例 + 现场调试工具）。

导出文件可以来自三个地方，本工具都认：

* ``opcua_browse.py --json``：``{"nodes": {key: node_id}, "struct_members": [...]}``
* GUI「导出订阅映射」：``{"nodes": {...}, "detail": [...]}``
* GUI 右键「导出此节点结构」：没有 ``nodes``，从 ``variables`` 里按名字生成 key

``struct_members`` 里的解码字段**没有 NodeId，不能订阅/写入**，会被明确跳过。

跑法::

    # 订阅全部点，一直打印变化（Ctrl+C 退出）
    .venv/Scripts/python.exe tools/opcua_from_json.py opcua_nodes.json

    # 连上后只读一次全部，打印完就退出
    .venv/Scripts/python.exe tools/opcua_from_json.py opcua_nodes.json --once

    # 单次写 + 回读
    .venv/Scripts/python.exe tools/opcua_from_json.py opcua_nodes.json ^
        --write lamp01=True --read lamp01

    # 覆盖端点 / 带账号 / 只看 5 秒
    .venv/Scripts/python.exe tools/opcua_from_json.py opcua_nodes.json ^
        --endpoint opc.tcp://192.168.1.88:4840 --user admin --password *** --watch 5

接到 Qt 页面时直接用 :class:`JsonTagClient`，见文件末尾的说明。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import time
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication, QObject, Signal  # noqa: E402

from common.com.opcua import (  # noqa: E402
    OpcConfig,
    OpcUaManager,
    keep_alive_until_stopped,
)
from tools.opcua_json import (  # noqa: E402
    build_unique_keys,
    clean_text,
    dump_json,
    restore_escaped,
)


def _safe_key(name: str) -> str:
    base = re.sub(r"[^0-9A-Za-z_]+", "_", name).strip("_").lower()
    return base or "node"


def load_tags(path: str, key_style: str = "path") -> tuple[dict[str, str], dict]:
    """返回 ``({key: node_id}, 原 payload)``。

    ``key_style="path"``（默认）：key 从 NodeId 路径生成并保留数组下标，
    同名点自动多取父级，不会再出现 ``alarmcode_2`` 这种无语义名字。
    ``key_style="flat"``：保留旧行为（短名 + 数字后缀），用于兼容旧映射。

    ``restore_escaped`` 是必须的：旧版导出把 surrogateescape 代理项写成了
    ``\\udcb9`` 文本，那种 NodeId 直接发给 PLC 会 ``BadNodeIdUnknown``；还原成
    代理字符后 asyncua 用 surrogateescape 编码回原始 GBK 字节，服务端才认得。
    """
    with open(path, encoding="utf-8") as fp:
        payload = json.load(fp)

    items: list[tuple[str, str, str]] = []
    raw_nodes = payload.get("nodes") or {}
    if raw_nodes:
        items = [(k, restore_escaped(v), "") for k, v in raw_nodes.items()]
    else:
        # 右键导出的结构文件：扁平变量清单在 variables 段
        for v in payload.get("variables") or []:
            nid = restore_escaped(v.get("node_id") or "")
            if not nid:
                continue
            name = clean_text(restore_escaped(v.get("name", "node")))
            items.append((name, nid, v.get("path", "")))
    if not items:
        raise ValueError(
            f"{path} 里既没有 nodes 也没有 variables，"
            "请先导出订阅映射或节点结构"
        )

    if key_style == "path":
        return build_unique_keys(items), payload

    # 旧行为：短名 + 数字后缀
    nodes: dict[str, str] = {}
    for name, nid, _ in items:
        key = _safe_key(name)
        if key == "node" and name != "node":
            key = name
        if key in nodes and nodes[key] != nid:
            suffix = 2
            while f"{key}_{suffix}" in nodes:
                suffix += 1
            key = f"{key}_{suffix}"
        nodes[key] = nid
    return nodes, payload


class JsonTagClient(QObject):
    """把「一份 JSON + 一个 endpoint」包成一个变量表客户端。

    业务层只需要::

        tags = JsonTagClient("cfg/opcua_tags.json", endpoint="opc.tcp://...")
        tags.tag_changed.connect(on_change)      # (key, value)
        tags.start()                             # 订阅全表
        # tags.start(keys=["enable", "velocity"])  # 或只订阅部分点
        tags.write("enable", True)               # 同步写（未订阅的点也能写）
        val = tags.read("velocity")              # 同步读（未订阅的点也能读）
        tags.stop()                              # 关窗口时必须调

    所有点共用一条 Subscription，服务端变化才推；断线重连、订阅重建由
    ``OpcUaManager`` 负责，不用自己写线程。``keys`` 里的业务名就是导出 JSON
    里 ``nodes`` 的 key（语义化、带数组下标）。
    """

    tag_changed = Signal(str, object)
    tag_error = Signal(str, str)
    connection_changed = Signal(bool)

    def __init__(
        self,
        json_path: str,
        endpoint: str = "",
        user: str = "",
        password: str = "",
        key_style: str = "path",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.tags, self.payload = load_tags(json_path, key_style=key_style)
        self.json_path = json_path
        endpoint = endpoint or self.payload.get("endpoint", "")
        if not endpoint:
            raise ValueError("JSON 里没有 endpoint，请用 --endpoint 指定")
        self.endpoint = endpoint
        self._mgr = OpcUaManager(
            OpcConfig(endpoint=endpoint, user=user, password=password), parent=self
        )
        self._mgr.node_changed.connect(self.tag_changed)
        self._mgr.node_error.connect(self.tag_error)
        self._mgr.connected_changed.connect(self.connection_changed)

    def start(self, subscribe: bool = True, keys: list[str] | None = None) -> None:
        """启动。默认订阅全表；``keys`` 给定时只订阅这些业务 key。

        PLC 对 monitored item 数量常有上限，几百个点一次全订阅不一定吃得消；
        按需订阅时**未订阅的点仍然可以 read/write**（按 key 解析成 NodeId 单点读）。
        """
        if subscribe:
            items = self.tags if keys is None else {k: self._node_id(k) for k in keys}
            self._mgr.subscribe(items)
        self._mgr.start()

    def _node_id(self, key: str) -> str:
        """key -> NodeId；key 不在表里就当它本身就是 NodeId。"""
        return self.tags.get(key, key)

    def read(self, key: str) -> Any:
        # 必须先解析：OpcUaManager 只在订阅表里查 key，未订阅的点直接把
        # "velocity" 当 NodeId 会 BadNodeIdUnknown。
        return self._mgr.read(self._node_id(key))

    def read_many(self, keys: list[str] | None = None) -> dict[str, Any]:
        targets = keys if keys is not None else list(self.tags)
        out: dict[str, Any] = {}
        for key in targets:
            val = self.read(key)
            if val is not None:
                out[key] = val
        return out

    def write(self, key: str, value: Any) -> bool:
        return self._mgr.write(self._node_id(key), value)

    def is_connected(self) -> bool:
        return self._mgr.is_connected()

    def stop(self) -> bool:
        ok = self._mgr.stop(wait_ms=3000)
        if not ok:
            keep_alive_until_stopped(self._mgr)
        return ok


def _parse_value(text: str) -> Any:
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def _pump(app: QCoreApplication, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def _wait_connected(app: QCoreApplication, client: JsonTagClient, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if client.is_connected():
            # 订阅在连接后异步补上，给它一轮事件循环
            _pump(app, 0.5)
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="用导出的节点 JSON 和 PLC 通信")
    parser.add_argument("json_file", help="导出的 JSON 文件")
    parser.add_argument("--endpoint", default="", help="覆盖 JSON 里的 endpoint")
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--timeout", type=float, default=15.0, help="等连接建立的秒数")
    parser.add_argument("--watch", type=float, default=0.0, help="订阅并打印变化 N 秒（0=一直跑）")
    parser.add_argument("--once", action="store_true", help="连上后读一次全部就退出")
    parser.add_argument("--read", action="append", default=[], metavar="KEY", help="单次读某个 key")
    parser.add_argument("--write", action="append", default=[], metavar="KEY=VALUE",
                        help="单次写（True/1/3.14/字符串）")
    parser.add_argument("--no-subscribe", action="store_true", help="只读写，不订阅")
    parser.add_argument("--key-style", choices=("path", "flat"), default="path",
                        help="key 命名：path=保留数组下标（默认），flat=旧版短名+序号")
    parser.add_argument("--dump-mapping", default="", metavar="FILE",
                        help="把最终 {key: NodeId} 写成一份干净 JSON 给业务层用")
    args = parser.parse_args()

    app = QCoreApplication(sys.argv[:1])
    client = JsonTagClient(
        args.json_file, args.endpoint, args.user, args.password,
        key_style=args.key_style,
    )
    skipped = len(client.payload.get("struct_members") or [])
    print(f"端点: {client.endpoint}")
    print(f"变量: {len(client.tags)} 个"
          + (f"（另有 {skipped} 个结构体成员无 NodeId，已跳过）" if skipped else ""))
    print("  " + "\n  ".join(
        f"{clean_text(k):<30} {clean_text(v)}" for k, v in client.tags.items()
    ))
    print("-" * 70, flush=True)

    if args.dump_mapping:
        dump_json(args.dump_mapping, {
            "endpoint": client.endpoint,
            "count": len(client.tags),
            "nodes": client.tags,
            "detail": [
                {"key": k, "node_id": v} for k, v in client.tags.items()
            ],
        })
        print(f"已写出干净映射: {args.dump_mapping}", flush=True)
        # 只导出映射时不必连 PLC；有读/写/订阅动作才继续往下走
        if not (args.once or args.read or args.write or args.watch or args.no_subscribe):
            return 0

    client.tag_changed.connect(lambda k, v: print(f"[变化] {k} = {v!r}", flush=True))
    client.tag_error.connect(lambda k, e: print(f"[错误] {k}: {e}", flush=True))
    if not args.no_subscribe:
        client.start()
    else:
        client.start(subscribe=False)
    if not _wait_connected(app, client, args.timeout):
        print(f"连接超时（{args.timeout}s）", file=sys.stderr)
        client.stop()
        return 2
    print("已连接", flush=True)

    for item in args.write:
        if "=" not in item:
            print(f"--write 格式应为 KEY=VALUE，忽略 {item!r}", file=sys.stderr)
            continue
        key, raw = item.split("=", 1)
        value = _parse_value(raw)
        ok = client.write(key, value)
        print(f"[写入] {key} = {value!r} -> {'成功' if ok else '失败'}", flush=True)

    keys = list(args.read)
    if args.once:
        keys = list(client.tags)
    for key in keys:
        print(f"[读取] {key} = {client.read(key)!r}", flush=True)

    # 有明确的读/写/--once 动作且没指定 --watch 时，做完就退；
    # 只传 JSON 文件则表示「持续订阅」，Ctrl+C 退出。
    if args.watch <= 0 and (args.once or args.read or args.write):
        client.stop()
        return 0

    if args.no_subscribe and not args.watch:
        client.stop()
        return 0

    try:
        if args.watch > 0:
            _pump(app, args.watch)
        else:
            print("订阅中，Ctrl+C 退出…", flush=True)
            while True:
                _pump(app, 0.2)
    except KeyboardInterrupt:
        print("\n停止中…", flush=True)
    finally:
        client.stop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"启动失败: {exc}", file=sys.stderr)
        raise SystemExit(2)
