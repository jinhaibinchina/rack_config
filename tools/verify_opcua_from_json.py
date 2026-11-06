# -*- coding: utf-8 -*-
"""回归：用导出的节点 JSON 连 PLC（订阅 / 读 / 写 / 业务层复用）。

起一个进程内 mock server，生成三种导出格式的 JSON，再以子进程方式跑
``opcua_from_json.py`` 的全部模式，最后直接复用 ``JsonTagClient``。

跑法::

    .venv/Scripts/python.exe tools/verify_opcua_from_json.py

反向验证：把 ``load_tags()`` 里对 ``variables`` 的兜底去掉，
「结构文件（无 nodes 段）」两项必须失败。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.opcua_mock_server import MockOpcUaServer  # noqa: E402

PORT = 48493
ENDPOINT = f"opc.tcp://127.0.0.1:{PORT}"

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


def main() -> int:
    server = MockOpcUaServer(ENDPOINT)
    server.start()
    time.sleep(0.8)
    ns = server.namespace_index
    tmp = tempfile.gettempdir()
    mapping = os.path.join(tmp, "verify_from_json.json")
    structure = os.path.join(tmp, "verify_from_json_structure.json")

    with open(mapping, "w", encoding="utf-8") as fp:
        json.dump({
            "endpoint": ENDPOINT,
            "count": 4,
            "nodes": {
                "lamp01": f"ns={ns};s=Lamp01",
                "fullcount": f"ns={ns};s=FullCount",
                "message": f"ns={ns};s=Message",
                "heartbeat": f"ns={ns};s=Heartbeat",
            },
            "struct_members": [{"path": "Slot01.Val", "value": 1}],
        }, fp)
    with open(structure, "w", encoding="utf-8") as fp:
        json.dump({
            "endpoint": ENDPOINT,
            "name": "GlobalVars",
            "variables": [{"name": "Lamp01", "node_id": f"ns={ns};s=Lamp01"}],
            "children": [],
        }, fp)

    def run(path: str, *args: str):
        return subprocess.run(
            [sys.executable, "tools/opcua_from_json.py", path, *args],
            capture_output=True, text=True, timeout=90,
        )

    try:
        print("\n[1] --once：读全部")
        r = run(mapping, "--once")
        check(r.returncode == 0, "退出码 0")
        check("[读取] lamp01 = False" in r.stdout, "读到 lamp01 初值")
        check("[读取] heartbeat" in r.stdout, "读到心跳")
        check("另有 1 个结构体成员无 NodeId，已跳过" in r.stdout,
              "struct_members 被明确跳过")

        print("\n[2] --write / --read")
        r = run(mapping, "--write", "lamp01=True", "--read", "lamp01")
        check(r.returncode == 0, "退出码 0")
        check("[写入] lamp01 = True -> 成功" in r.stdout, "写入成功")
        check("[读取] lamp01 = True" in r.stdout, "回读为 True")
        check(server.get_value("Lamp01") is True, "服务端真值确实改变")

        print("\n[3] --watch：订阅推送")
        r = run(mapping, "--watch", "2.5")
        check(r.returncode == 0, "退出码 0")
        check("[变化] heartbeat" in r.stdout, "服务端自增的心跳被推送")
        check("[变化] lamp01 = True" in r.stdout, "订阅首帧拿到当前值")

        print("\n[4] 结构文件（无 nodes 段，从 variables 生成 key）")
        r = run(structure, "--once")
        check(r.returncode == 0, "退出码 0")
        check("变量: 1 个" in r.stdout, "从 variables 段读出 1 个点")
        check("[读取] lamp01" in r.stdout, "生成的 key 可读")

        print("\n[5] 旧文件兼容 / 中文点 / 同名去重")
        from tools.opcua_from_json import load_tags

        legacy = os.path.join(tmp, "verify_legacy_structure.json")
        gbk_text = "\\udcb9\\udca4\\udcb3\\udccc\\udcc3\\udce8\\udcca\\udcf6"
        with open(legacy, "w", encoding="utf-8") as fp:
            json.dump({
                "endpoint": ENDPOINT,
                "variables": [
                    {"name": "Lamp01", "node_id": f"ns={ns};s=Lamp01"},
                    {"name": "Lamp01", "node_id": f"ns={ns};s=Lamp02"},
                    {"name": gbk_text, "node_id": f"ns={ns};s={gbk_text}"},
                ],
            }, fp)
        try:
            tags, _ = load_tags(legacy)
            check(len(tags) == 3, "3 个点都保留，没有被覆盖")
            check("lamp01" in tags and "lamp02" in tags,
                  "同 name 不同 NodeId 时按 NodeId 区分（不再加 _2）")
            check("工程描述" in tags, "GBK 代理项还原成可读中文 key")
            check("\udcb9" in tags["工程描述"],
                  "旧文件的 NodeId 还原成代理字符（可重新订阅）")
            flat, _ = load_tags(legacy, key_style="flat")
            check("lamp01_2" in flat, "key_style=flat 仍保留旧行为")
        finally:
            if os.path.exists(legacy):
                os.remove(legacy)

        print("\n[5b] 数组点用语义 key，不出现 alarmcode_2")
        from tools.opcua_json import build_unique_keys

        items = [
            ("AlarmCode", f"ns={ns};s=GVL_HMI.Alarms2HMII[{i}].AlarmCode", "")
            for i in range(5)
        ]
        items.append(("ack", f"ns={ns};s=GVL_HMI.ack", ""))
        keys = build_unique_keys(items)
        check(len(keys) == 6, "6 个点各有一个 key")
        check("ack" in keys, "不冲突的点保持短名")
        check("alarms2hmii_0_alarmcode" in keys and
              "alarms2hmii_4_alarmcode" in keys,
              "数组下标写进 key：alarms2hmii_0_alarmcode … _4_")
        check(not any(k == "alarmcode_2" for k in keys),
              "不再产生 alarmcode_2 这种无语义名字")

        # --dump-mapping 要能在不连 PLC 的情况下写出干净映射
        out_map = os.path.join(tmp, "verify_dump_mapping.json")
        r = run(mapping, "--dump-mapping", out_map)
        check(r.returncode == 0, "--dump-mapping 退出码 0（不需要连 PLC）")
        check("已写出干净映射" in r.stdout, "提示已写出")
        try:
            with open(out_map, encoding="utf-8") as fp:
                dumped = json.load(fp)
            check(dumped["count"] == 4 and len(dumped["nodes"]) == 4,
                  "导出映射含全部 4 个点")
            check(dumped["nodes"]["lamp01"] == f"ns={ns};s=Lamp01",
                  "导出的 NodeId 正确")
        finally:
            if os.path.exists(out_map):
                os.remove(out_map)

        print("\n[6] 业务层复用 JsonTagClient")
        from PySide6.QtCore import QCoreApplication

        from tools.opcua_from_json import JsonTagClient

        app = QCoreApplication(sys.argv[:1])
        client = JsonTagClient(mapping)
        check(len(client.tags) == 4, "加载 4 个变量")
        client.start()
        deadline = time.time() + 10
        while time.time() < deadline and not client.is_connected():
            app.processEvents()
            time.sleep(0.02)
        check(client.is_connected(), "连接建立")
        check(client.write("fullcount", 42) is True, "同步写入成功")
        check(server.get_value("FullCount") == 42, "写入落到服务端")
        check(client.read("fullcount") == 42, "同步读回 42")
        check(client.read_many(["lamp01", "fullcount"]) ==
              {"lamp01": True, "fullcount": 42}, "批量读返回 {key: value}")
        check(client.stop() is True, "stop() 干净退出")

        print("\n[7] 按需订阅：只订阅部分点，其余点仍可读写")
        from tools.opcua_from_json import JsonTagClient

        client2 = JsonTagClient(mapping)
        changes: list[str] = []
        client2.tag_changed.connect(lambda k, v: changes.append(k))
        client2.start(keys=["lamp01", "heartbeat"])
        deadline = time.time() + 10
        while time.time() < deadline and not client2.is_connected():
            app.processEvents()
            time.sleep(0.02)
        # 事件泵：跨线程信号排队投递
        pump_end = time.time() + 1.5
        while time.time() < pump_end:
            app.processEvents()
            time.sleep(0.01)
        check(client2.is_connected(), "按需订阅也能连上")
        check(bool(changes), "订阅的点有首帧推送")
        check(set(changes) <= {"lamp01", "heartbeat"},
              f"只推送订阅的两个点（实得 {sorted(set(changes))}）")
        check(client2.read("fullcount") is not None, "未订阅的点也能按 key 读")
        check(client2.write("fullcount", 7) is True, "未订阅的点也能按 key 写")
        check(server.get_value("FullCount") == 7, "写入落到服务端")
        check(client2.read("message") == "ready", "未订阅的点读回正确值")
        check(client2.stop() is True, "按需订阅 stop 干净退出")
    finally:
        server.stop()
        for p in (mapping, structure):
            if os.path.exists(p):
                os.remove(p)

    print("\n" + "=" * 62)
    print(f"结果: {_passed} 通过, {len(_failed)} 失败")
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
    except Exception:
        import traceback

        traceback.print_exc()
        raise SystemExit(2)
