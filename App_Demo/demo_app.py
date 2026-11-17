"""变量绑定 Demo —— 设计态配好的 bindings，运行态双向（读 + 反向写）。

这个 demo 演示四件事：

1. **绑定表存图元内**：``binding_demo.json`` 里每个图元的 ``bindings`` 字段
   形如 ``{"context": {"tag": "demo.status", "apply": "text"}}``；带 ``mode``
   的另外声明方向（r 只读 / rw 读写 / w 只写）。
2. **读（外部 → 画面）**：``RuntimeStage.load()`` 自动扫描 bindings 注册到
   ``TagBus``；外部 ``stage.tags.update(tag, value)`` 即刷新画面显示。
3. **反向写（画面 → 外部 / PLC）**：用户操作 widget 控件（输入框回车、
   spinbox 改值、slider 拖动）或点击 checkbox 图元，新值通过
   ``TagBus.writeRequested`` 发出；业务侧订阅后写设备。
4. **不污染设计数据**：无论读还是写，都只动实时显示字段；「验证」按钮证明
   ``page_data()`` 与磁盘 JSON 始终逐字段一致。

运行：在项目根 ``python -m App_Demo``。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QDateTime
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget,QCheckBox
)

# 脚本直跑时也能 import Designer_V2
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Designer_V2.CoreQGraphics.runtime import RuntimeStage  # noqa: E402

PAGE_PATH = str(Path(__file__).resolve().parent / "binding_demo.json")

# 读方向推值控件：(tag, 标签, 默认值, 值类型, 可选值)
PUSH_FIELDS = [
    ("demo.status", "状态文本", "设备运行中", "text", None),
    ("demo.statusColor", "状态颜色", "#89ddff", "color", None),
    ("demo.temp", "温度数值", "温度: 23.5 ℃", "text", None),
    ("demo.lamp", "指示灯颜色", "#00ff00", "color",
     ["#00ff00", "#ff0000", "#ffcc00", "#524848"]),
    ("demo.lampVisible", "指示灯可见", "true", "bool", ["true", "false"]),
]


class DemoWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("变量绑定 Demo — 读（外部→画面）/ 写（画面→PLC）")
        self.resize(1440, 820)

        # 运行态舞台：load() 自动扫描页面 bindings 注册读 / 写
        self.stage = RuntimeStage(page_path=PAGE_PATH, widget_mode="host")
        self._edits: dict[str, QWidget] = {}

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # ---- 左：画面 ----
        left = QVBoxLayout()
        title = QLabel("画面（RuntimeStage）— 右侧推值刷新显示；直接操作控件触发写出")
        title.setFont(QFont("", 11, QFont.Bold))
        left.addWidget(title)
        self.stage.attach(left)
        root.addLayout(left, 3)

        # ---- 中：控制台 ----
        mid = QVBoxLayout()
        mid.addWidget(self._make_read_panel())
        mid.addWidget(self._make_write_panel())
        mid.addWidget(self._make_verify_panel())
        mid.addStretch(1)
        root.addLayout(mid, 2)

        # ---- 右：日志 ----
        logcol = QVBoxLayout()
        logcol.addWidget(QLabel("外部推值日志（数据 → 画面）"))
        self.read_log = QTextEdit(self)
        self.read_log.setReadOnly(True)
        self.read_log.setMaximumHeight(180)
        logcol.addWidget(self.read_log)
        logcol.addWidget(QLabel("模拟 PLC 收到的写请求（画面 → PLC）"))
        self.write_log = QTextEdit(self)
        self.write_log.setReadOnly(True)
        logcol.addWidget(self.write_log)
        root.addLayout(logcol, 2)

        # 订阅反向写：业务层在这里把值真正写进 PLC（demo 只记日志）
        self.stage.tags.writeRequested.connect(self._on_write_request)

        n = self.stage.load()
        if not n:
            self._read_log(f"载入失败：{self.stage.load_error}")
        else:
            self._read_log(
                f"页面载入：{n} 个图元；读绑定 {self.stage.page_binding_count()} 条，"
                f"反向写 {self.stage.page_write_count()} 条")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _make_read_panel(self) -> QGroupBox:
        box = QGroupBox("① 读方向：推值刷新画面")
        lay = QVBoxLayout(box)
        for tag, label, default, kind, choices in PUSH_FIELDS:
            row = QHBoxLayout()
            row.addWidget(QLabel(label), 1)
            if choices is not None:
                combo = QComboBox()
                combo.addItems(choices)
                if default in choices:
                    combo.setCurrentText(default)
                widget: QWidget = combo
            else:
                widget = QLineEdit(default)
                widget.setObjectName(f"tag_{tag}")
            self._edits[tag] = widget
            row.addWidget(widget, 2)
            btn = QPushButton("推送")
            btn.clicked.connect(lambda _c=False, t=tag: self._push_one(t))
            row.addWidget(btn)
            lay.addLayout(row)
        batch = QPushButton("一键推送全部")
        batch.clicked.connect(self._push_all)
        lay.addWidget(batch)
        return box

    def _make_write_panel(self) -> QGroupBox:
        box = QGroupBox("② 写方向：操作画面 → 写请求")
        lay = QVBoxLayout(box)
        hint = QLabel(
            "可直接操作画面里的输入框 / spinbox / slider / 报警勾选（点一下图元）；"
            "或点下面按钮模拟操作。写请求会出现在右侧「模拟 PLC」日志。")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row1 = QHBoxLayout()
        b1 = QPushButton("模拟改输入框")
        b1.clicked.connect(self._sim_lineedit)
        b2 = QPushButton("模拟改速度")
        b2.clicked.connect(self._sim_spinbox)
        row1.addWidget(b1)
        row1.addWidget(b2)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        b3 = QPushButton("模拟拖滑块")
        b3.clicked.connect(self._sim_slider)
        b4 = QPushButton("模拟点报警勾选")
        b4.clicked.connect(self._sim_checkbox)
        row2.addWidget(b3)
        row2.addWidget(b4)
        lay.addLayout(row2)
        return box

    def _make_verify_panel(self) -> QGroupBox:
        box = QGroupBox("③ 验证：运行态不污染设计数据")
        lay = QVBoxLayout(box)
        hint = QLabel("推值 / 写出前后对比 page_data() 与磁盘 JSON，应始终逐字段一致。")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        btn = QPushButton("验证一致性")
        btn.clicked.connect(self._verify)
        lay.addWidget(btn)
        return box

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------
    def _read_widget(self, tag: str):
        w = self._edits[tag]
        if isinstance(w, QComboBox):
            return w.currentText()
        return w.text()

    def _push_one(self, tag: str) -> None:
        value = self._read_widget(tag)
        self.stage.tags.update(tag, value)
        self.stage.tags.flush_now()
        self._read_log(f"推送 {tag} = {value!r}")

    def _push_all(self) -> None:
        values = {tag: self._read_widget(tag) for tag, *_ in PUSH_FIELDS}
        self.stage.tags.update_many(values)
        self.stage.tags.flush_now()
        self._read_log(f"一键推送 {len(values)} 个 tag")

    # ------------------------------------------------------------------
    # 写（模拟用户在画面上操作真实控件）
    # ------------------------------------------------------------------
    def _sim_lineedit(self) -> None:
        w = self.stage.widget("控件文本")
        if w is not None:
            w.setText(f"用户录入 {QDateTime.currentDateTime().toString('hh:mm:ss')}")
            w.editingFinished.emit()

    def _sim_spinbox(self) -> None:
        w = self.stage.widget("速度设定")
        if w is not None and hasattr(w, "setValue"):
            w.setValue((w.value() + 15) % 201)

    def _sim_slider(self) -> None:
        w = self.stage.widget("亮度滑块")
        if w is not None and hasattr(w, "setValue"):
            w.setValue((w.value() + 10) % 101)

    def _sim_checkbox(self) -> None:
        w:QCheckBox = self.stage.widget("报警勾选")
        if w is not None:
            w.setChecked(not w.isChecked())

    def _on_write_request(self, tag: str, value) -> None:
        ts = QDateTime.currentDateTime().toString("hh:mm:ss")
        self.write_log.append(f"[{ts}] 写 {tag} = {value!r}")

    # ------------------------------------------------------------------
    def _verify(self) -> None:
        with open(PAGE_PATH, encoding="utf-8") as f:
            disk = json.load(f)
        same = self.stage.scene.page_data() == disk
        self._read_log("验证：" + ("一致 ✓ 设计数据未被污染"
                                 if same else "不一致 ✗ 检查写入路径"))

    def _read_log(self, text: str) -> None:
        self.read_log.append(text)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.stage.release()
        super().closeEvent(event)


def main() -> int:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    win = DemoWindow()
    win.show()
    return app.exec()
