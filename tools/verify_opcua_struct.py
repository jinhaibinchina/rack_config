# -*- coding: utf-8 -*-
"""结构体（ExtensionObject）展开回归。

覆盖三条链路：

1. **解码器**：按 ``DataTypeDefinition`` 把裸 Body 拆成字段树——嵌套结构体、
   数组、结构体数组、可选字段 EncodingMask、Union SwitchField，都用内存里
   造的定义 + 字节流验证（不需要服务端配合）；
2. **浏览层**：``OpcUaManager.browse_children`` 对结构体变量给出可展开标记，
   展开后拿到成员；普通标量变量不该被当成结构体；
3. **界面层**：值列不再打印 Body 字节串、成员标成"无独立 NodeId"、不能加入
   监视、"展开结构体"开关能关掉。

跑法::

    .venv/Scripts/python.exe tools/verify_opcua_struct.py

反向验证：把 ``_struct_children`` 里的 ``is_builtin_datatype`` 判断去掉，
"Boolean 变量展开为空"必须失败；把 ``_fill_variable_meta`` 里的 struct 标记
去掉，"Slot01 可展开"必须失败。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from asyncua import ua
from asyncua.ua import ua_binary
from PySide6.QtWidgets import QApplication

from common.com.opcua import OpcConfig, OpcUaManager
from common.com.opcua.structure import (
    StructureReader,
    is_builtin_datatype,
    is_struct_value,
)
from tools.opcua_mock_server import MockOpcUaServer

PORT = 48533
ENDPOINT = f"opc.tcp://127.0.0.1:{PORT}"
NODE_ROLE_MARK = "（结构体成员）"

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


def pump(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def wait_until(app, pred, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    app.processEvents()
    return pred()


# ----------------------------------------------------------------------
# 假 client：只提供 DataTypeDefinition，用来单独测解码分支
# ----------------------------------------------------------------------
class _FakeDataTypeNode:
    def __init__(self, name: str, definition) -> None:
        self._name = name
        self._definition = definition
        self.definition_reads = 0

    async def read_data_type_definition(self):
        node_owner.definition_reads += 1
        if self._definition is None:
            raise RuntimeError("BadAttributeIdInvalid")
        return self._definition

    async def read_browse_name(self):
        return ua.QualifiedName(self._name, 2)

    async def get_children_descriptions(self):
        return []


class _FakeClient:
    def __init__(self, nodes: dict) -> None:
        self._nodes = nodes
        self.definition_reads = 0

    def get_node(self, node_id):
        key = node_id.to_string() if hasattr(node_id, "to_string") else str(node_id)
        return self._nodes[key]


node_owner = _FakeClient({})


def _struct_def(fields, stype=ua.StructureType.Structure):
    definition = ua.StructureDefinition()
    definition.StructureType = stype
    definition.BaseDataType = ua.NodeId(ua.ObjectIds.Structure)
    definition.Fields = [
        ua.StructureField(Name=name, DataType=ua.NodeId(dt), ValueRank=rank,
                          IsOptional=optional)
        for name, dt, rank, optional in fields
    ]
    return definition


def test_decoder() -> None:
    """解码器单测：不需要服务端，直接喂字节。"""
    global node_owner

    print("\n[1] 解码器（内存里的定义 + 裸字节）")

    # 可选字段：A 必选 + B/C 可选，本次只有 B 在场 → mask = 0b011
    def_opt = _struct_def(
        [("A", 4, -1, False), ("B", 4, -1, True), ("C", 12, -1, True)],
        stype=ua.StructureType.StructureWithOptionalFields,
    )
    body_opt = ua_binary.pack_uatype(ua.VariantType.UInt32, 0b011)
    body_opt += ua_binary.pack_uatype(ua.VariantType.Int16, 7)
    body_opt += ua_binary.pack_uatype(ua.VariantType.Int16, 9)

    # Union：switch=2 表示只有第 2 个字段（Y）被编码
    def_union = _struct_def(
        [("X", 4, -1, False), ("Y", 12, -1, False)],
        stype=ua.StructureType.Union,
    )
    body_union = ua_binary.pack_uatype(ua.VariantType.UInt32, 2)
    body_union += ua_binary.pack_uatype(ua.VariantType.String, "only-y")

    dt_opt = ua.NodeId("OptType", 2)
    dt_union = ua.NodeId("UnionType", 2)
    dt_nodef = ua.NodeId("NoDefType", 2)
    node_owner = _FakeClient(
        {
            dt_opt.to_string(): _FakeDataTypeNode("OptType", def_opt),
            dt_union.to_string(): _FakeDataTypeNode("UnionType", def_union),
            dt_nodef.to_string(): _FakeDataTypeNode("NoDefType", None),
        }
    )
    reader = StructureReader(node_owner)

    import asyncio

    def run(coro):
        return asyncio.run(coro)

    opt = run(
        reader.decode(
            ua.ExtensionObject(TypeId=dt_opt, Body=body_opt), dt_opt, "OptType"
        )
    )
    by_name = {f.name: f for f in opt.fields}
    check(not opt.error, f"可选字段结构体解码无错（{opt.error or 'ok'}）")
    check(by_name.get("A") and by_name["A"].value == 7, "必选字段 A = 7")
    check(by_name.get("B") and by_name["B"].value == 9, "EncodingMask 位1 → B 在场且 = 9")
    check(
        by_name.get("C") is not None and "未编码" in by_name["C"].error,
        "EncodingMask 位2 为 0 → C 标为未编码",
    )

    union = run(
        reader.decode(
            ua.ExtensionObject(TypeId=dt_union, Body=body_union), dt_union, "UnionType"
        )
    )
    ub = {f.name: f for f in union.fields}
    check(ub.get("Y") and ub["Y"].value == "only-y", "Union switch=2 → 只有 Y 解出值")
    check(ub.get("X") is not None and "未编码" in ub["X"].error, "Union 未选中的 X 标为未编码")

    nodef = run(
        reader.decode(
            ua.ExtensionObject(TypeId=dt_nodef, Body=b"\x00\x01"), dt_nodef, "NoDefType"
        )
    )
    check(
        "DataTypeDefinition" in nodef.error,
        f"缺 DataTypeDefinition 时给明确错误（实得 {nodef.error!r}）",
    )

    reads_before = node_owner.definition_reads
    run(reader.decode(ua.ExtensionObject(TypeId=dt_opt, Body=body_opt), dt_opt, "OptType"))
    check(
        node_owner.definition_reads == reads_before,
        "DataTypeDefinition 只读一次（带缓存，展开大结构体不重复请求）",
    )

    check(is_struct_value(ua.ExtensionObject()), "is_struct_value 认单个 ExtensionObject")
    check(
        is_struct_value([ua.ExtensionObject(), ua.ExtensionObject()]),
        "is_struct_value 认结构体数组",
    )
    check(not is_struct_value(True), "is_struct_value 不把 Boolean 当结构体")
    check(
        is_builtin_datatype(ua.NodeId(4)) and not is_builtin_datatype(ua.NodeId("X", 2)),
        "is_builtin_datatype 区分内建类型和自定义类型",
    )


# ----------------------------------------------------------------------
def main() -> int:
    print("=" * 66)
    print("OPC UA 结构体展开回归")
    print("=" * 66)

    test_decoder()

    # --- 0. JSON 导出的代理项兜底 -------------------------------------
    print("\n[0] surrogateescape 代理项（现场导出崩过 / NodeId 要可逆）")
    from tools.opcua_browser_gui import _fmt
    from tools.opcua_json import clean_text, dump_json, restore_escaped

    # \udcb9\udca4 = GBK「工」，asyncua 用 surrogateescape 解出来的低代理
    gbk = "\udcb9\udca4\udcb3\udccc\udcc3\udce8\udcca\udcf6"
    check("工程描述" in clean_text(gbk), "clean_text 把 GBK 代理项显示成中文")
    check(
        gbk.encode("utf-8", errors="surrogateescape").hex() == "b9a4b3ccc3e8caf6",
        "原始代理字符能往返还原成服务端认得的 GBK 字节",
    )
    check(
        restore_escaped("\\udcb9\\udca4") == "\udcb9\udca4",
        "旧导出文件里的 \\udcXX 文本能还原成代理字符",
    )

    dirty = "上料完成\udcff\ud800尾"
    check("上料完成" in _fmt(dirty) and "尾" in _fmt(dirty), "_fmt 保住中文且不崩")

    tmp_json = os.path.join(tempfile.gettempdir(), "verify_opcua_surrogate.json")
    payload = {
        "endpoint": "opc.tcp://192.168.1.88:4840",
        "children": [{"name": "消息", "value": gbk, "nested": {"text": gbk}}],
    }
    try:
        dump_json(tmp_json, payload)
        raw = Path(tmp_json).read_text(encoding="utf-8")  # 合法 UTF-8，不抛异常
        check("\\udcb9" in raw, "写盘用可逆的 JSON 转义而不是可见字面量")
        with open(tmp_json, encoding="utf-8") as fp:
            back = json.load(fp)
        check(back["children"][0]["nested"]["text"] == gbk,
              "json.load 还原成同一个代理字符（NodeId 仍可订阅）")
        check(
            back["children"][0]["value"].encode("utf-8", errors="surrogateescape")
            .endswith(bytes.fromhex("b9a4b3ccc3e8caf6")),
            "读回来的 NodeId 编码后字节与 PLC 一致",
        )
    finally:
        if os.path.exists(tmp_json):
            os.remove(tmp_json)

    app = QApplication(sys.argv[:1])
    server = MockOpcUaServer(ENDPOINT)
    server.start()
    ns = server.namespace_index
    print(f"\n模拟服务器: {ENDPOINT}  ns={ns}")

    mgr = OpcUaManager(OpcConfig(endpoint=ENDPOINT, publish_period_ms=100))
    errors: list[tuple[str, str]] = []
    mgr.node_error.connect(lambda k, e: errors.append((k, e)))
    mgr.start()
    ok = wait_until(app, mgr.is_connected, 10.0)
    check(ok, "连接建立")

    def child_of(node_id: str, name: str) -> dict | None:
        return next((c for c in mgr.browse_children(node_id) if c["name"] == name), None)

    root = mgr.browse_children("")
    apps_node = next((c for c in root if c["name"] == "AppsManagers"), None)
    rack = child_of(apps_node["node_id"], "Rack") if apps_node else None
    check(rack is not None, "浏览到 AppsManagers/Rack")

    print("\n[2] 浏览层")
    leaves = mgr.browse_children(rack["node_id"]) if rack else []
    slot = next((c for c in leaves if c["name"] == "Slot01"), None)
    check(slot is not None, "Rack 下找到结构体变量 Slot01")
    check(slot is not None and slot["has_children"] is True, "结构体变量标记为可展开")
    check(slot is not None and slot.get("struct") is True, "结构体变量额外带 struct 标记")
    lamp = next((c for c in leaves if c["name"] == "Lamp01"), None)
    check(lamp is not None and lamp["has_children"] is False, "普通 Boolean 变量不可展开")

    members = mgr.browse_children(slot["node_id"]) if slot else []
    names = [m["name"] for m in members]
    check(names == ["Index", "Main", "Temps", "Note"], f"成员顺序与定义一致（实得 {names}）")
    by_name = {m["name"]: m for m in members}
    check(by_name.get("Index", {}).get("value") == 1, "Index = 1")
    check(by_name.get("Note", {}).get("value") == "ready", "Note = 'ready'（UTF-8 没解错）")
    check(by_name.get("Temps", {}).get("value") == [1.5, 2.25, -0.5], "Temps 数组解出 3 个 Double")
    main = by_name.get("Main", {})
    check(main.get("has_children") is True and main.get("text", "").startswith("{…}"),
          "嵌套结构体 Main 显示为聚合节点")
    sub = {c["name"]: c for c in main.get("children", [])}
    check(sub.get("Val", {}).get("value") == 37, "Main.Val = 37")
    check(sub.get("Sts", {}).get("value") is True, "Main.Sts = True")
    check(sub.get("Name", {}).get("value") == "A库空筒", "Main.Name = 'A库空筒'")
    check(all(m["node_id"] == "" and m.get("synthetic") for m in members),
          "解码成员没有 NodeId，并标记 synthetic")
    check(all(m["writable"] is False for m in members), "解码成员一律只读（不能写）")

    check(mgr.browse_children(lamp["node_id"]) == [], "展开 Boolean 变量返回空（不硬解）")

    struct_arr = next((c for c in leaves if c["name"] == "Slots"), None)
    arr_children = mgr.browse_children(struct_arr["node_id"]) if struct_arr else []
    check(len(arr_children) == 2, f"结构体数组展开成 2 个元素（实得 {len(arr_children)}）")
    check(
        [c["name"] for c in arr_children] == ["[0]", "[1]"]
        and arr_children[1]["children"][0]["value"] == 2,
        "数组元素按 [0]/[1] 命名，[1].Index = 2",
    )

    print("\n[3] read_structure 结构化输出")
    result = mgr.read_structure(slot["node_id"])
    check(result["type"] == "RackSlot", f"type = RackSlot（实得 {result['type']}）")
    check(len(result["fields"]) == 4, "顶层 4 个字段")
    check(
        result["fields"][1]["children"][0]["name"] == "Val"
        and result["fields"][1]["children"][0]["value"] == 37,
        "to_dict 保留嵌套 children",
    )
    check(mgr.read_structure("ns=9;s=NotExist")["error"], "读不存在的节点返回 error 而不是抛异常")

    print("\n[4] 界面（离屏）")
    from tools.opcua_browser_gui import NODE_ROLE, NodeBrowser

    win = NodeBrowser(ENDPOINT)
    win._toggle_connection()
    ok = wait_until(app, lambda: win._items.get(apps_node["node_id"]) is not None, 10.0)
    check(ok, "界面连接并铺开根节点")
    win._on_expanded(win._items[apps_node["node_id"]])
    win._on_expanded(win._items[rack["node_id"]])
    slot_item = win._items.get(slot["node_id"])
    check(slot_item is not None, "树里能找到 Slot01")
    check(
        slot_item is not None and "结构体" in slot_item.text(2) and "字节" in slot_item.text(2),
        f"结构体值列不打印字节流（实得 {slot_item.text(2) if slot_item else ''!r}）",
    )
    win._on_expanded(slot_item)
    kid_items = [slot_item.child(i) for i in range(slot_item.childCount())]
    kid_names = [k.text(0) for k in kid_items]
    check(kid_names == ["Index", "Main", "Temps", "Note"], f"树上展开出 4 个成员（实得 {kid_names}）")
    check(kid_items[0].text(2) == "1", "成员值列 = 1")
    check(kid_items[0].text(1) == NODE_ROLE_MARK, "成员 NodeId 列标注'（结构体成员）'")
    check(
        kid_items[1].childCount() == 3,
        f"嵌套结构体在树上直接铺开 3 个子项（实得 {kid_items[1].childCount()}）",
    )
    check(
        kid_items[1].child(0).text(2) == "37",
        "嵌套成员值列 = 37",
    )

    win._tree.setCurrentItem(kid_items[0])
    check(win._read_btn.isEnabled() is False, "选中结构体成员时'读取一次'不可用")
    check("成员" in win._d_access.text(), f"详情里访问权限标为成员（实得 {win._d_access.text()}）")

    before = win._table.rowCount()
    win._add_to_monitor(kid_items[0].data(0, NODE_ROLE))
    check(win._table.rowCount() == before, "结构体成员不能加入监视")

    # --- 导出：监视表映射里也要能看到已展开的结构体成员 ---------------
    mapping = win._collect_mapping()
    members = mapping.get("struct_members", [])
    check(len(members) == 7, f"订阅映射附带 7 个结构体成员（实得 {len(members)}）")
    check(
        any(m["path"].endswith("Main/Val") for m in members),
        "成员路径保留嵌套层级（Main/Val）",
    )
    check(
        all(not m.get("node_id") for m in members),
        "struct_members 里不放 NodeId（这些成员订阅不了）",
    )

    # --- 右键「导出此节点结构」：真成员 + 解码字段双路 -----------------
    from PySide6.QtWidgets import QFileDialog

    out = os.path.join(tempfile.gettempdir(), "verify_struct_export.json")
    orig_dialog = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, "JSON (*.json)"))
    try:
        win._export_structure(slot_item.data(0, NODE_ROLE))
        exported = json.loads(Path(out).read_text(encoding="utf-8"))
    finally:
        QFileDialog.getSaveFileName = orig_dialog
        if os.path.exists(out):
            os.remove(out)
    check(exported.get("name") == "Slot01", "导出结构文件带节点名")
    check(exported.get("node_class") == "Variable", "导出结构文件带节点类型")
    check(exported.get("children_count") == 4, "整包 EO 的 4 个合成成员仍在 children 里")
    check(exported.get("variables_count") == 0, "合成成员没有 NodeId，不进可订阅变量表")
    check(exported.get("decoded_type") == "RackSlot", "导出结构文件带 DataType 名")
    check(len(exported.get("decoded_fields", [])) == 4, "导出结构文件带 4 个顶层字段")
    main_row = next(
        (c for c in exported.get("children", []) if c["name"] == "Main"), {}
    )
    check(len(main_row.get("children", [])) == 3, "嵌套结构体在导出文件里也铺开")
    check(exported.get("truncated") is False, "未触发深度/数量上限")

    # --- 文件夹节点：递归下钻 + 不再报 BadAttributeIdInvalid ------------
    # 现场在 GlobalVars(Object) 上导出，旧实现只给两个 GVL 子 Object，还会
    # 用 read_structure 撞 BadAttributeIdInvalid 显示成"读 DataType 失败"。
    apps_item = win._items[apps_node["node_id"]]
    folder = win._collect_structure(apps_item.data(0, NODE_ROLE), max_depth=4)
    check(folder.get("node_class") == "Object", "文件夹节点标记为 Object")
    check(folder.get("decoded_error") == "", "Object 节点不再报读 DataType 失败")
    check(folder.get("decoded_fields") == [], "Object 节点不产生解码字段")
    check(
        folder.get("variables_count", 0) >= 9,
        f"递归下钻拿到 Rack 下的全部变量（实得 {folder.get('variables_count')}）",
    )
    check(
        all(v["node_id"] for v in folder.get("variables", [])),
        "variables 里每项都有 NodeId，可直接订阅",
    )
    check(
        any(v["name"] == "Lamp01" for v in folder.get("variables", [])),
        "深层变量 Lamp01 在扁平清单里",
    )

    # 上限保护
    capped = win._collect_structure(apps_item.data(0, NODE_ROLE), max_nodes=2)
    check(capped.get("truncated") is True, "超过 max_nodes 时标记 truncated")
    check(capped.get("variables_count", 99) <= 2, "截断后变量数不超上限")

    win._expand_struct.setChecked(False)  # 触发 _reload_root，树整个重建
    win._on_expanded(win._items[apps_node["node_id"]])
    win._on_expanded(win._items[rack["node_id"]])
    slot_off = win._items.get(slot["node_id"])
    check(
        slot_off is not None
        and slot_off.data(0, NODE_ROLE).get("has_children") is False
        and slot_off.childCount() == 0,
        "'展开结构体'关掉后结构体变量不再可展开",
    )
    win._expand_struct.setChecked(True)

    check(not errors, f"全程无 node_error（实际 {len(errors)} 条: {errors[:3]}）")

    win.close()
    win._mgr.stop(wait_ms=2000)
    mgr.stop(wait_ms=3000)
    server.stop()

    print("\n" + "=" * 66)
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
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2)
