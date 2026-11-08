"""料仓全局参数模型 V2：图元来自 ``Designer/CoreQGraphics`` 的运行态场景。

对照 ``rack_global_paras_model.RackGlobalParasModel``（旧 ``Designer.Core``
EmbeddedWidgetLayer 方案）：**识别口径、DB41 字节偏移、信号处理逐项一致**，
唯一被替换的是「怎么拿到真实控件」——

* 旧：``widget_element._leaf_widget()`` → ``EmbeddedWidgetLayer.widget``
* 新：``GraphicsScene.widget_proxies[iid].widget()`` → ``QGraphicsProxyWidget``

新场景的 proxy 只在 ``set_scene_mode(True)``（运行态）才创建，所以本模型必须
在场景切运行态**之后**构造。场景若重新 ``load_page()``，proxy 会被销毁重建，
旧引用立刻失效——届时调 :meth:`bind` 重新绑定即可（对应旧版的 ``refresh()``）。

控件类型不自己猜：``widgetType`` 来自 page JSON，``create_control`` 已经按变体
建好 ``QCheckBox`` / ``QSpinBox``。这里只加业务约束（仓位编号范围 -1..9）并把
交互接到 PLC 写 DB41。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QCheckBox, QSpinBox, QWidget

from common.com.snap7 import PLCManager
from snap7.util import get_int, set_int

# 三个勾选框：(模型属性名, 图元名, DB41 字节偏移)
CHECKBOX_BINDINGS: tuple[tuple[str, str, int], ...] = (
    ("membrane_alarm", "屏蔽膜卷号报警", 0),
    ("material_ng_alarm", "屏蔽物料状态NG报警", 2),
    ("park_while_idle", "非运行状态下仍响应泊车", 4),
)
# 两个仓位编号：(模型属性名, 图元名, DB41 字节偏移)
SPINBOX_BINDINGS: tuple[tuple[str, str, int], ...] = (
    ("slot_no_1", "仓位编号1", 6),
    ("slot_no_2", "仓位编号2", 8),
)
# 仓位编号允许 -1（未指定）到 9（旧实现同样写死这两个界）
SLOT_NO_RANGE = (-1, 9)
DB41_MIN_LEN = 10


class RackGlobalParasModelV2(QObject):
    """按图元名绑定 3 个勾选框 + 2 个数字输入，读写 PLC DB41。"""

    def __init__(self, plc_mgr: Optional[PLCManager], scene, parent=None) -> None:
        super().__init__(parent)
        self.plc_mgr = plc_mgr
        self._scene = scene
        # 图元 / 控件缓存：bind() 填，refresh 前为空
        self.items: dict[str, object] = {}
        self.checkboxes: dict[str, QCheckBox] = {}
        self.spinboxes: dict[str, QSpinBox] = {}
        self._linked: list[tuple[object, object]] = []
        self.bind()

    # ------------------------------------------------------------------
    # 绑定
    # ------------------------------------------------------------------
    def leaf_widget(self, name: str) -> Optional[QWidget]:
        """取图元 ``name`` 对应的真实控件；场景没切运行态时返回 None。"""
        item = self.items.get(name)
        if item is None:
            item = self._scene.find_item_by_name(name)
            if item is None:
                return None
            self.items[name] = item
        proxy = self._scene.widget_proxies.get(getattr(item, "item_id", -1))
        return None if proxy is None else proxy.widget()

    def bind(self) -> bool:
        """（重新）绑定全部控件并接好信号；缺控件时返回 False。

        幂等：重复调用会先断开上一次的信号连接，不会出现「一个点击写两遍
        DB41」。场景重载后 proxy 重建，也必须再调一次。
        """
        self.unbind()
        self.items.clear()

        ok = True
        for attr, name, offset in CHECKBOX_BINDINGS:
            widget = self.leaf_widget(name)
            if not isinstance(widget, QCheckBox):
                ok = False
                continue
            self.checkboxes[attr] = widget
            widget.clicked.connect(
                lambda checked, _o=offset: self._write_int(_o, int(checked)))
            self._linked.append((widget.clicked, None))
        for attr, name, offset in SPINBOX_BINDINGS:
            widget = self.leaf_widget(name)
            if not isinstance(widget, QSpinBox):
                ok = False
                continue
            # 先设范围再连信号：setRange 可能触发 valueChanged，不该写 PLC
            widget.setRange(*SLOT_NO_RANGE)
            self.spinboxes[attr] = widget
            widget.valueChanged.connect(
                lambda value, _o=offset: self._write_int(_o, int(value)))
            self._linked.append((widget.valueChanged, None))
        self._ok = ok
        return ok

    def unbind(self) -> None:
        """断开全部信号（不销毁控件——控件归场景的 proxy 所有）。"""
        for signal, _slot in self._linked:
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass
        self._linked.clear()
        self.checkboxes.clear()
        self.spinboxes.clear()

    def is_bound(self) -> bool:
        return bool(self.checkboxes) and bool(self.spinboxes)

    # ------------------------------------------------------------------
    # 状态读写
    # ------------------------------------------------------------------
    def _write_int(self, offset: int, value: int) -> None:
        if self.plc_mgr is None:
            return
        buf = bytearray(2)
        set_int(buf, 0, int(value))
        self.plc_mgr.write_data(41, offset, buf)

    def read_state(self) -> dict[str, int]:
        """当前界面上的值（顺序与 DB41 偏移一致），便于回归 / 存档。"""
        out: dict[str, int] = {}
        for attr, _name, _off in CHECKBOX_BINDINGS:
            widget = self.checkboxes.get(attr)
            out[attr] = int(bool(widget.isChecked())) if widget else 0
        for attr, _name, _off in SPINBOX_BINDINGS:
            widget = self.spinboxes.get(attr)
            out[attr] = int(widget.value()) if widget else 0
        return out

    def apply_db41(self, db41: bytes) -> None:
        """解析 DB41 数据，更新图元显示（旧实现逐字段对齐）。"""
        # snap7 的 get_int 会原地把高位字节 & 0xFF，只吃 bytearray；
        # 统一转一次，bytes / bytearray 两种入参都能用。
        db = bytearray(db41)
        if len(db) < DB41_MIN_LEN:
            raise ValueError(f"DB41 数据长度不足：{len(db)} < {DB41_MIN_LEN}")
        # 写控件期间会触发 valueChanged / clicked → 回写 PLC，形成回路。
        # 这里屏蔽信号：DB 是唯一事实来源，界面只做回显。
        for widget in list(self.checkboxes.values()) + list(self.spinboxes.values()):
            widget.blockSignals(True)
        try:
            for attr, _name, offset in CHECKBOX_BINDINGS:
                widget = self.checkboxes.get(attr)
                if widget is not None:
                    widget.setChecked(bool(get_int(db, offset)))
            for attr, _name, offset in SPINBOX_BINDINGS:
                widget = self.spinboxes.get(attr)
                if widget is not None:
                    widget.setValue(int(get_int(db, offset)))
        finally:
            for widget in list(self.checkboxes.values()) + list(self.spinboxes.values()):
                widget.blockSignals(False)
