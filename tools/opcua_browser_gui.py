"""OPC UA 节点浏览器（GUI）。

对标 UaExpert 的常用部分，但少了证书/加密那些用不上的：**连上 → 展开 →
看到 NodeId 和实时值 → 导出映射表**，一条直线。

功能：

* 地址空间树，**懒加载**（展开才发请求，一次只发 4 个）；
* 结构体变量（ExtensionObject）展开成成员：服务端把成员暴露成子节点时显示真
  NodeId（可订阅/可写），只给整包字节的则按 DataTypeDefinition 解码成只读快照；
* 选中节点看详情（NodeId / 类型 / 权限 / 当前值 / 路径）；
* 双击或右键「加入监视」，走订阅实时刷新——不是定时读；
* 一键导出 ``{key: node_id}`` 给 ``OpcUaManager.subscribe()`` 用；
* 支持账号密码（S7-1500 默认不允许匿名）。

跑法::

    # 连内置模拟服务器（另开一个终端）
    .venv/Scripts/python.exe tools/opcua_mock_server.py
    .venv/Scripts/python.exe tools/opcua_browser_gui.py

    # 连真实 PLC（慢网络 / 忙设备用 --timeout / --watchdog 放宽）
    .venv/Scripts/python.exe tools/opcua_browser_gui.py ^
        --endpoint opc.tcp://192.168.1.10:4840 --user admin --password *** ^
        --timeout 15 --watchdog 8

    # 重连失败只看到 TimeoutError() 时，开诊断拿完整异常栈
    .venv/Scripts/python.exe tools/opcua_browser_gui.py ^
        --endpoint opc.tcp://192.168.1.10:4840 --debug-reconnect
"""

from __future__ import annotations

import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from asyncua import ua

from common.com.opcua import (
    OpcConfig,
    OpcUaManager,
    is_standard_subtree,
    keep_alive_until_stopped,
)
from tools.opcua_json import build_unique_keys, clean_text, dump_json

DEFAULT_ENDPOINT = "opc.tcp://127.0.0.1:48400"

NODE_ROLE = Qt.ItemDataRole.UserRole


def _fmt(value: object, limit: int | None = None) -> str:
    """把节点值转成显示文本。

    ``limit`` 为 ``None``（默认）时**不截断**——截断交给 Qt 的列宽省略号去做，
    用户把列拖宽就能看全，tooltip 里也有完整内容。硬截断（比如 40 字符）会让
    结构体值的后半段永远看不到，而且拖宽列也救不回来。

    结构体（ExtensionObject）不打印 Body 的字节串——那是一坨 8 字节一行的
    ``\\xe5\\xba\\x93``，看不了任何东西，还占满整列。只报类型和大小，成员
    点开左边的小三角看。
    """
    if value is None:
        return ""
    if isinstance(value, ua.ExtensionObject):
        try:
            typeid = value.TypeId.to_string()
        except Exception:  # noqa: BLE001
            typeid = "?"
        size = len(value.Body) if isinstance(value.Body, (bytes, bytearray)) else 0
        return clean_text(f"结构体 {typeid}（{size} 字节，可展开）")
    if isinstance(value, (list, tuple)) and value and all(
        isinstance(v, ua.ExtensionObject) for v in value
    ):
        size = sum(len(v.Body) for v in value if isinstance(v.Body, (bytes, bytearray)))
        return clean_text(f"结构体数组 [{len(value)}]（共 {size} 字节，可展开）")
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return f"{value:.3f}"
    # 现场字符串值可能带孤立 UTF-16 代理项；不清洗的话塞进 Qt 组件或写盘时
    # 会抛 UnicodeEncodeError: surrogates not allowed。
    text = clean_text(str(value))
    if limit is None or len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _safe_key(name: str) -> str:
    base = re.sub(r"[^0-9A-Za-z_]+", "_", name).strip("_").lower()
    return base or "node"


class NodeBrowser(QMainWindow):
    """节点浏览器主窗口。"""

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        user: str = "",
        password: str = "",
        timeout: float = 10.0,
        watchdog: float = 5.0,
    ) -> None:
        super().__init__()
        self.setWindowTitle("OPC UA 节点浏览器")
        self.resize(1120, 720)

        self._timeout = timeout
        self._watchdog = watchdog
        self._mgr = OpcUaManager(
            OpcConfig(
                endpoint=endpoint,
                timeout=timeout,
                watchdog_interval=watchdog,
            ),
            parent=self,
        )
        self._mgr.connected_changed.connect(self._on_connected)
        self._mgr.node_changed.connect(self._on_node_changed)
        self._mgr.node_error.connect(self._on_node_error)
        self._mgr.state_message.connect(self._log)

        self._items: dict[str, QTreeWidgetItem] = {}      # node_id -> 树节点
        self._monitored: dict[str, dict] = {}             # node_id -> {name, row}
        self._current: dict | None = None                 # 当前选中的节点

        self._build_ui(endpoint, user, password)
        if self._mgr.reconnect_trace_path:
            self._log(
                f"重连诊断已开启，异常栈写入 {self._mgr.reconnect_trace_path}"
            )

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self, endpoint: str, user: str, password: str) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(8)

        # -- 连接栏 --
        bar = QHBoxLayout()
        bar.addWidget(QLabel("端点"))
        self._endpoint_edit = QLineEdit(endpoint)
        self._endpoint_edit.setMinimumWidth(260)
        self._user_edit = QLineEdit(user)
        self._user_edit.setPlaceholderText("用户名")
        self._user_edit.setFixedWidth(110)
        self._pass_edit = QLineEdit(password)
        self._pass_edit.setPlaceholderText("密码")
        self._pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_edit.setFixedWidth(110)
        self._connect_btn = QPushButton("连接")
        self._connect_btn.setFixedWidth(80)
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(12, 12)
        self._status_text = QLabel("未连接")

        bar.addWidget(self._endpoint_edit, 1)
        bar.addWidget(self._user_edit)
        bar.addWidget(self._pass_edit)
        bar.addWidget(self._connect_btn)
        bar.addWidget(self._status_dot)
        bar.addWidget(self._status_text)
        self._connect_btn.clicked.connect(self._toggle_connection)
        outer.addLayout(bar)

        # -- 第二行工具条 --
        tools = QHBoxLayout()
        self._hide_ns0 = QCheckBox("隐藏内建类型子树")
        self._hide_ns0.setToolTip(
            "只隐藏 ns=0 的 Server / TypeHierarchy / DataTypes 等内建子树；\n"
            "DeviceSet 这类中间容器会保留，否则展不到深层的变量。"
        )
        self._hide_ns0.setChecked(True)
        self._hide_ns0.toggled.connect(self._reload_root)
        self._expand_struct = QCheckBox("展开结构体")
        self._expand_struct.setToolTip(
            "结构体变量（ExtensionObject）展开成成员列表。\n"
            "服务端把成员暴露成子节点时（Siemens S7-1500 就是这样）显示的是真\n"
            "NodeId，能订阅、能写；只给整包字节的服务端则按 DataTypeDefinition\n"
            "解码出成员，这些成员只有值、没有独立 NodeId。"
        )
        self._expand_struct.setChecked(True)
        self._expand_struct.toggled.connect(self._reload_root)
        self._search = QLineEdit()
        self._search.setPlaceholderText("过滤 Name / NodeId（只作用于已展开的部分）")
        self._search.textChanged.connect(self._apply_filter)
        self._export_btn = QPushButton("导出映射…")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export)
        self._read_btn = QPushButton("读取一次")
        self._read_btn.setEnabled(False)
        self._read_btn.clicked.connect(self._read_current)

        tools.addWidget(self._hide_ns0)
        tools.addWidget(self._expand_struct)
        tools.addWidget(self._search, 1)
        tools.addWidget(self._read_btn)
        tools.addWidget(self._export_btn)
        outer.addLayout(tools)

        # -- 主体：左树 / 右详情 --
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["名称", "NodeId", "值"])
        self._tree.setColumnWidth(0, 200)
        self._tree.setColumnWidth(1, 230)
        # 值列放的是完整文本（可能是上千字符的结构体），必须明确"超宽就画省略号"，
        # 否则 QTreeWidget 会按内容算 idealWidth，撑出横向滚动条把整棵树挤歪。
        self._tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._tree.header().setStretchLastSection(True)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.itemExpanded.connect(self._on_expanded)
        self._tree.currentItemChanged.connect(self._on_current_changed)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.setMinimumWidth(520)
        splitter.addWidget(self._tree)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        detail_box = QGroupBox("节点详情")
        detail_form = QFormLayout(detail_box)
        detail_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._d_name = QLabel("—")
        self._d_path = QLabel("—")
        self._d_path.setWordWrap(True)
        self._d_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._d_nodeid = QLabel("—")
        self._d_nodeid.setWordWrap(True)
        self._d_nodeid.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._d_class = QLabel("—")
        self._d_type = QLabel("—")
        self._d_access = QLabel("—")
        self._d_value = QLabel("—")
        self._d_value.setWordWrap(True)
        detail_form.addRow("名称", self._d_name)
        detail_form.addRow("路径", self._d_path)
        detail_form.addRow("NodeId", self._d_nodeid)
        detail_form.addRow("节点类型", self._d_class)
        detail_form.addRow("数据类型", self._d_type)
        detail_form.addRow("访问权限", self._d_access)
        detail_form.addRow("当前值", self._d_value)
        right_layout.addWidget(detail_box)

        monitor_box = QGroupBox("监视（订阅推送，双击变量可加入）")
        monitor_layout = QVBoxLayout(monitor_box)
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["名称", "NodeId", "值"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        monitor_layout.addWidget(self._table)

        monitor_btns = QHBoxLayout()
        clear_btn = QPushButton("清空监视")
        clear_btn.clicked.connect(self._clear_monitor)
        monitor_btns.addStretch(1)
        monitor_btns.addWidget(clear_btn)
        monitor_layout.addLayout(monitor_btns)
        right_layout.addWidget(monitor_box, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        # 给个明确的初始比例：树要够宽才看得清 NodeId 和值，别让右侧详情抢空间
        splitter.setSizes([720, 400])
        outer.addWidget(splitter, 1)

        # -- 日志 --
        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(400)
        self._log_view.setFixedHeight(84)
        self._log_view.setFont(QFont("Consolas", 9))
        outer.addWidget(self._log_view)

        self._set_status(False)

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------
    def _toggle_connection(self) -> None:
        if self._mgr._thread is not None:
            stopped = self._mgr.stop(wait_ms=2000)
            if not stopped:
                keep_alive_until_stopped(self._mgr)
                self._log("⚠ 后台线程未及时退出，已摘出保活")
            self._connect_btn.setText("连接")
            self._set_status(False)
            self._tree.clear()
            self._items.clear()
            return

        endpoint = self._endpoint_edit.text().strip()
        if not endpoint:
            self._log("端点不能为空")
            return
        cfg = OpcConfig(
            endpoint=endpoint,
            user=self._user_edit.text().strip(),
            password=self._pass_edit.text(),
            timeout=self._timeout,
            watchdog_interval=self._watchdog,
        )
        if not self._mgr.configure(cfg):
            self._log("上一轮连接还没停干净，稍等再试")
            return
        self._connect_btn.setText("断开")
        self._log(f"连接 {endpoint} …（请求超时 {self._timeout:g}s / 探测周期 {self._watchdog:g}s）")
        self._mgr.start()

    def _on_connected(self, connected: bool) -> None:
        self._set_status(connected)
        if connected:
            self._reload_root()
            self._export_btn.setEnabled(True)
        else:
            self._export_btn.setEnabled(bool(self._monitored))

    def _set_status(self, connected: bool) -> None:
        color = "#22c55e" if connected else "#ef4444"
        self._status_dot.setStyleSheet(f"background:{color}; border-radius:6px;")
        self._status_text.setText("已连接" if connected else "未连接")

    # ------------------------------------------------------------------
    # 树
    # ------------------------------------------------------------------
    def _reload_root(self) -> None:
        if not self._mgr.is_connected():
            return
        self._tree.clear()
        self._items.clear()
        children = self._browse("")
        for data in children:
            self._add_item(None, data)
        self._log(f"根节点下 {len(children)} 项（过滤后 {self._tree.topLevelItemCount()}）")

    def _add_item(self, parent: QTreeWidgetItem | None, data: dict) -> QTreeWidgetItem:
        # 解码出来的结构体成员是"一次给一棵树"（数据都在手里，不用再发请求），
        # 所以 children 直接建出来，标 _loaded 免得多发一次空的 browse。
        kids = data.get("children") or []
        synthetic = bool(data.get("synthetic"))
        value_text = data.get("text") or _fmt(data.get("value"))
        if synthetic:
            node_id_text = "（结构体成员）"
        else:
            node_id_text = data.get("node_id", "")
        item = QTreeWidgetItem([data["name"], node_id_text, value_text])

        # 路径按层级累积（树里只显示相对名，滚到深处就不知道自己在哪了）
        path = data["name"]
        if parent is not None:
            pdata = parent.data(0, NODE_ROLE) or {}
            parent_path = pdata.get("_path") or pdata.get("name", "")
            path = f"{parent_path}/{data['name']}" if parent_path else data["name"]
        payload = {k: v for k, v in data.items() if k != "children"}
        payload["_loaded"] = False
        payload["_path"] = path
        item.setData(0, NODE_ROLE, payload)
        item.setToolTip(0, path)
        if synthetic:
            item.setToolTip(
                1,
                "解码出来的结构体成员，没有独立 NodeId，不能单独订阅或写入。\n"
                "要订阅请到上一层的结构体变量，或换用把成员暴露成子节点的服务端。",
            )
        else:
            item.setToolTip(1, data.get("node_id", ""))

        # 单元格里放完整文本，超宽由 Qt 画省略号（拖宽列即可看全）；
        # tooltip 再兜一层，省得为了看一个结构体的尾部去拖列宽。
        if value_text:
            item.setToolTip(2, value_text)
        if data.get("struct_error"):
            item.setForeground(2, QColor("#dc2626"))
            item.setToolTip(2, data["struct_error"])

        cls = data.get("node_class", "")
        if cls == "Variable":
            # 变量值列给个灰底，一眼区分目录和变量
            item.setForeground(2, QColor("#9ca3af"))
        if synthetic:
            item.setForeground(0, QColor("#7c3aed"))
        elif data.get("writable"):
            item.setForeground(0, QColor("#2563eb"))

        if parent is None:
            self._tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        if data.get("node_id"):
            self._items[data["node_id"]] = item

        if kids:
            payload["_loaded"] = True
            item.setData(0, NODE_ROLE, payload)
            for child in kids:
                self._add_item(item, child)
        elif data.get("has_children"):
            item.setChildIndicatorPolicy(
                QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
            )
            item.addChild(QTreeWidgetItem(["…"]))
        return item

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, NODE_ROLE)
        if not data or data.get("_loaded"):
            return
        data["_loaded"] = True
        item.takeChildren()  # 去掉占位
        children = self._browse(data["node_id"]) if data.get("node_id") else []
        for child in children:
            self._add_item(item, child)
        if not children:
            item.setChildIndicatorPolicy(
                QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator
            )
        item.setData(0, NODE_ROLE, data)

    @contextmanager
    def _busy(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            yield
        finally:
            QApplication.restoreOverrideCursor()

    def _browse(self, node_id: str) -> list[dict]:
        with self._busy():
            children = self._mgr.browse_children(node_id)
        if self._hide_ns0.isChecked():
            # 只藏 ns=0 的内建类型/服务子树，**不能把所有 ns=0 都藏掉**：
            # 真实 PLC 里 DeviceSet / DataBlocksGlobal 这些中间容器就在 ns=0，
            # 变量却埋在 ns=3。整片隐藏会让树在第 1 层就断了，看起来像"深度不够"、
            # 展不出东西。（node_id 前缀也不可靠：to_string() 对 ns=0 省略前缀）
            children = [
                c
                for c in children
                if not is_standard_subtree(c["name"], c.get("namespace", 0))
            ]
        if not self._expand_struct.isChecked():
            for c in children:
                if c.get("struct"):
                    c["has_children"] = False
        return children

    # ------------------------------------------------------------------
    # 选中 / 详情
    # ------------------------------------------------------------------
    def _on_current_changed(self, current: QTreeWidgetItem | None, _prev) -> None:
        data = current.data(0, NODE_ROLE) if current is not None else None
        self._current = data
        self._read_btn.setEnabled(
            bool(data and data.get("node_class") == "Variable" and data.get("node_id"))
        )
        if not data:
            for label in (self._d_name, self._d_path, self._d_nodeid, self._d_class,
                          self._d_type, self._d_access, self._d_value):
                label.setText("—")
                label.setToolTip("")
            return

        self._d_name.setText(data["name"])
        self._d_path.setText(data.get("_path", ""))
        if data.get("synthetic"):
            self._d_nodeid.setText("（结构体成员，不是独立节点）")
            self._d_nodeid.setToolTip(
                "解码出来的成员只有值，没有 NodeId——订阅/写入得针对上一层的结构体变量。"
            )
        else:
            self._d_nodeid.setText(data.get("node_id", ""))
            self._d_nodeid.setToolTip(data.get("node_id", ""))
        self._d_class.setText(data.get("node_class", ""))
        self._set_detail_value(data.get("value"), data.get("text"))

        if data.get("node_class") == "Variable":
            if data.get("synthetic"):
                self._d_type.setText(data.get("data_type") or "—")
                self._d_access.setText(
                    "只读（结构体成员）" if not data.get("struct_error") else "—"
                )
            else:
                with self._busy():
                    vtype = self._mgr.node_type(data["node_id"])
                self._d_type.setText(vtype or "（读取失败）")
                self._d_access.setText("读写" if data.get("writable") else "只读")
        else:
            self._d_type.setText("—")
            self._d_access.setText("—")
        if data.get("struct_error"):
            self._d_value.setText(f"<{data['struct_error']}>")

    def _set_detail_value(self, value: object, text: str | None = None) -> None:
        """详情区有 wordWrap，能比单元格多显示一些。

        结构体值的完整文本可能上千字符（含 Body 字节流），整段塞进来会把
        面板撑得很高、把监视表挤没，所以这里留 1000 字符，完整内容挂 tooltip。
        """
        full = text if text is not None else _fmt(value)
        self._d_value.setText(_fmt(value, 1000) if text is None else text)
        self._d_value.setToolTip(full)

    def _read_current(self) -> None:
        if not self._current:
            return
        node_id = self._current.get("node_id")
        if not node_id:
            self._log("这是结构体成员，只有快照值，没有可读的 NodeId")
            return
        with self._busy():
            value = self._mgr.read(node_id)
        if value is None:
            self._log(f"读取 {node_id} 失败（节点可能不可读）")
            return
        self._current["value"] = value
        self._set_detail_value(value)
        item = self._items.get(node_id)
        if item is not None:
            text = _fmt(value)
            item.setText(2, text)
            item.setToolTip(2, text)
            item.setData(0, NODE_ROLE, dict(self._current, _loaded=True))

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, NODE_ROLE)
        if data and data.get("node_class") == "Variable":
            self._add_to_monitor(data)

    def _on_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, NODE_ROLE)
        if not data:
            return
        menu = QMenu(self)
        if data.get("node_class") == "Variable" and data.get("node_id"):
            act = QAction("加入监视", self)
            act.triggered.connect(lambda: self._add_to_monitor(data))
            menu.addAction(act)
            act_read = QAction("读取一次", self)
            act_read.triggered.connect(self._read_current)
            menu.addAction(act_read)
            menu.addSeparator()
        if data.get("node_id"):
            act_copy = QAction("复制 NodeId", self)
            act_copy.triggered.connect(
                lambda: QApplication.clipboard().setText(data["node_id"])
            )
            menu.addAction(act_copy)
            act_struct = QAction("导出此节点结构…", self)
            act_struct.setToolTip("把该节点的真成员节点 + 解码字段一并写成 JSON")
            act_struct.triggered.connect(lambda: self._export_structure(data))
            menu.addAction(act_struct)
        else:
            act_path = QAction("复制路径", self)
            act_path.triggered.connect(
                lambda: QApplication.clipboard().setText(data.get("_path", ""))
            )
            menu.addAction(act_path)
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # 监视
    # ------------------------------------------------------------------
    def _add_to_monitor(self, data: dict) -> None:
        node_id = data.get("node_id")
        if not node_id:
            self._log("结构体成员没有独立 NodeId，订阅请选上一层的结构体变量")
            return
        if node_id in self._monitored:
            self._log(f"{node_id} 已在监视列表中")
            return
        if not self._mgr.is_connected():
            self._log("未连接，无法订阅")
            return
        self._mgr.subscribe({node_id: node_id})
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(data["name"]))
        self._table.setItem(row, 1, QTableWidgetItem(node_id))
        value_text = _fmt(data.get("value"))
        value_cell = QTableWidgetItem(value_text)
        value_cell.setToolTip(value_text)
        self._table.setItem(row, 2, value_cell)
        self._monitored[node_id] = {"name": data["name"], "row": row}
        self._export_btn.setEnabled(True)
        self._log(f"已订阅 {node_id}")

    def _clear_monitor(self) -> None:
        self._monitored.clear()
        self._table.setRowCount(0)
        self._mgr.unsubscribe_all()
        self._export_btn.setEnabled(False)
        self._log("已清空监视列表")

    def _on_node_changed(self, key: str, value) -> None:
        info = self._monitored.get(key)
        if info is None:
            return
        text = _fmt(value)
        row = info["row"]
        cell = self._table.item(row, 2)
        if cell is not None:
            cell.setText(text)
            cell.setToolTip(text)
        item = self._items.get(key)
        if item is not None:
            item.setText(2, text)
            item.setToolTip(2, text)
            payload = item.data(0, NODE_ROLE)
            if isinstance(payload, dict):
                payload["value"] = value
        data = self._current
        if data and data.get("node_id") == key:
            self._set_detail_value(value)

    def _on_node_error(self, key: str, message: str) -> None:
        self._log(f"[{key}] {message}")

    # ------------------------------------------------------------------
    # 过滤 / 导出
    # ------------------------------------------------------------------
    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()

        def walk(item: QTreeWidgetItem, parent_matched: bool) -> bool:
            data = item.data(0, NODE_ROLE) or {}
            hit = parent_matched or (
                not needle
                or needle in str(data.get("name", "")).lower()
                or needle in str(data.get("node_id", "")).lower()
            )
            any_child = False
            for i in range(item.childCount()):
                if walk(item.child(i), hit):
                    any_child = True
            visible = hit or any_child
            item.setHidden(not visible)
            return visible

        for i in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(i), False)
        if needle:
            self._tree.expandAll()

    def _collect_mapping(self) -> dict:
        """把监视列表整理成 ``{key: node_id}`` 的导出结构。

        另外把**树里已展开**的结构体成员放进 ``struct_members``：它们没有
        NodeId、不能订阅，但对写映射表/核对字段很有用。树是懒加载的，没展开
        的节点不会出现在这里——要看某个节点的完整结构请用右键
        「导出此节点结构…」。
        """
        # key 从 NodeId 生成、保留数组下标；同名点自动多取父级而不是加 _2
        # （应用层要的是 alarms2hmii_0_alarmcode，不是 alarmcode_2）。
        by_id = build_unique_keys(
            [(info["name"], node_id, info.get("path", ""))
             for node_id, info in self._monitored.items()]
        )
        nodes = by_id
        detail = [
            {"key": key, "node_id": node_id, "name": self._monitored[node_id]["name"]}
            for key, node_id in by_id.items()
        ]

        struct_members: list[dict] = []

        def collect(item) -> None:
            data = item.data(0, NODE_ROLE)
            if isinstance(data, dict):
                if data.get("synthetic"):
                    struct_members.append(
                        {
                            "path": data.get("_path", ""),
                            "name": data.get("name", ""),
                            "type": data.get("type", "") or data.get("data_type", ""),
                            "value": _fmt(data.get("value")),
                            "text": data.get("text", ""),
                        }
                    )
                for i in range(item.childCount()):
                    collect(item.child(i))

        for i in range(self._tree.topLevelItemCount()):
            collect(self._tree.topLevelItem(i))

        return {
            "endpoint": self._endpoint_edit.text().strip(),
            "count": len(nodes),
            "nodes": nodes,
            "detail": detail,
            "struct_members": struct_members,
        }

    def _write_export(self, path: str) -> int:
        payload = self._collect_mapping()
        dump_json(path, payload)
        return payload["count"]

    def _export(self) -> None:
        if not self._monitored:
            self._log("监视列表为空，先双击几个变量再加进来")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出订阅映射", "opcua_nodes.json", "JSON (*.json)"
        )
        if not path:
            return
        count = self._write_export(path)
        members = self._collect_mapping()["struct_members"]
        self._log(
            f"已导出 {count} 条订阅映射到 {path}"
            + (f"（另含 {len(members)} 个结构体成员，无 NodeId 不能订阅）"
               if members else "；要看某个节点的内部结构请右键「导出此节点结构…」")
        )

    def _collect_structure(
        self, data: dict, max_depth: int = 8, max_nodes: int = 500
    ) -> dict:
        """递归收集一个节点的整棵子树，返回可直接序列化的 payload。

        之前只导一层：选中 ``GlobalVars`` 这类**文件夹节点**时只得到 GVL_HMI /
        GVL_PARAMETERS 两个 Object，真正的变量还在好几层之下。这里按
        ``has_children`` 递归下钻，同时把所有带 NodeId 的 Variable 扁平进
        ``variables``（可直接喂 ``OpcUaManager.subscribe()``）。

        ``max_depth`` / ``max_nodes`` 防止在 Objects 根上误点把整台设备拉爆；
        触顶时 ``truncated=True``。合成成员（无 NodeId）自带预解码树，直接铺开
        不再发请求。
        """
        node_id = data.get("node_id", "")
        name = data.get("name", "node")
        node_class = data.get("node_class", "")
        root_path = data.get("_path", "")
        variables: list[dict] = []
        seen: set[str] = set()
        counter = [0]
        truncated = [False]

        def entry_of(c: dict, path: str) -> dict:
            nid = c.get("node_id") or ""
            entry = {
                "name": c.get("name", ""),
                "path": path,
                "node_id": nid,
                "node_class": c.get("node_class", ""),
                "value": c.get("text") or _fmt(c.get("value")),
                "writable": bool(c.get("writable")),
                "synthetic": bool(c.get("synthetic")),
            }
            if c.get("node_class") == "Variable" and nid and nid not in seen:
                seen.add(nid)
                variables.append(dict(entry))
            return entry

        def fetch(nid: str, path: str, depth: int) -> list[dict]:
            if depth > max_depth or counter[0] >= max_nodes:
                truncated[0] = True
                return []
            try:
                kids = self._mgr.browse_children(nid)
            except Exception:  # noqa: BLE001 - 单个子树读不了不该中断整棵
                return []
            out = []
            for c in kids:
                if counter[0] >= max_nodes:
                    truncated[0] = True
                    break
                counter[0] += 1
                out.append(expand(c, f"{path}/{c['name']}", depth))
            return out

        def expand(c: dict, path: str, depth: int) -> dict:
            entry = entry_of(c, path)
            pre = c.get("children") or []
            sub_id = c.get("node_id") or ""
            if pre:
                entry["children"] = [
                    expand(sub, f"{path}/{sub['name']}", depth + 1) for sub in pre
                ]
            elif sub_id and c.get("has_children") and not c.get("synthetic"):
                entry["children"] = fetch(sub_id, path, depth + 1)
            return entry

        with self._busy():
            children = fetch(node_id, root_path, 1)
            # Object / 文件夹节点没有 DataType 属性，调 read_structure 只会报
            # BadAttributeIdInvalid，看着像故障。只对「确实是结构体」的变量解。
            decoded: dict = {"type": "", "fields": [], "error": ""}
            if node_class == "Variable" and node_id and (
                data.get("struct") or data.get("has_children")
            ):
                try:
                    decoded = self._mgr.read_structure(node_id)
                except Exception as exc:  # noqa: BLE001
                    decoded = {"type": "", "fields": [], "error": str(exc)}

        return {
            "endpoint": self._endpoint_edit.text().strip(),
            "node_id": node_id,
            "name": name,
            "path": root_path,
            "node_class": node_class,
            "value": _fmt(data.get("value")),
            "children_count": len(children),
            "children": children,
            "variables_count": len(variables),
            "variables": variables,
            "decoded_type": decoded.get("type", ""),
            "decoded_fields": decoded.get("fields", []),
            "decoded_error": decoded.get("error", ""),
            "truncated": truncated[0],
            "max_depth": max_depth,
            "max_nodes": max_nodes,
        }

    def _export_structure(self, data: dict) -> None:
        """右键「导出此节点结构…」：写盘并回报层数/可订阅变量数。"""
        payload = self._collect_structure(data)
        name = payload["name"]
        path, _ = QFileDialog.getSaveFileName(
            self, "导出节点结构", f"{_safe_key(name)}_structure.json", "JSON (*.json)"
        )
        if not path:
            return
        dump_json(path, payload)
        self._log(
            f"已导出 {name} 结构：{len(payload['children'])} 个直接子节点 / "
            f"{payload['variables_count']} 个可订阅变量"
            + (f" / 解码字段 {len(payload['decoded_fields'])} 项"
               if payload["decoded_fields"] else "")
            + ("（已达上限，结果被截断）" if payload["truncated"] else "")
            + f" → {path}"
        )

    # ------------------------------------------------------------------
    def _log(self, message: str) -> None:
        self._log_view.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {message}")

    def closeEvent(self, event) -> None:
        stopped = self._mgr.stop(wait_ms=2000)
        if not stopped:
            keep_alive_until_stopped(self._mgr)
        super().closeEvent(event)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="OPC UA 节点浏览器")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    parser.add_argument(
        "--timeout", type=float, default=10.0,
        help="底层请求/握手超时秒数（真机慢网络调大，默认 10）",
    )
    parser.add_argument(
        "--watchdog", type=float, default=5.0,
        help="健康探测周期秒数，同时也是探测超时（真机误判掉线时调大，默认 5）",
    )
    parser.add_argument("--autoconnect", action="store_true", help="启动后立即连接")
    parser.add_argument(
        "--debug-reconnect", action="store_true",
        help="把重连失败的完整异常栈写入 opcua_reconnect_trace.log（排查 TimeoutError 用）",
    )
    parser.add_argument("--autoclose", type=float, default=0.0, help="N 秒后关闭（冒烟用）")
    args = parser.parse_args()

    if args.debug_reconnect:
        os.environ["OPCUA_DEBUG_RECONNECT"] = "1"

    app = QApplication(sys.argv[:1])
    win = NodeBrowser(
        args.endpoint, args.user, args.password,
        timeout=args.timeout, watchdog=args.watchdog,
    )
    win.show()

    if args.autoconnect:
        win._toggle_connection()
    if args.autoclose > 0:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(int(args.autoclose * 1000), win.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
