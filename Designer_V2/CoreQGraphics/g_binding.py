"""图元属性 → 变量 tag 的绑定规格（设计态与运行态共用）。

设计取舍
--------
* **绑定表存图元内**：每条 page 记录可选 ``bindings`` 字段，形如
  ``{"context": {"tag": "GVL_HMI.x", "apply": "text"}}``。没有绑定就不写这个
  键，保持「未编辑记录 round-trip 零改动」契约；进 ``_page`` 即自动获得 JSON
  序列化与整页 undo/redo（``PageHistory`` 快照）。
* **属性白名单**：只放开显示类属性（文本 / 勾选 / 可见 / 样式），几何属性
  （id、name、center_pos、width…）一律不绑，避免运行态数据推着画面乱跳。
* **双向**：缺省 ``mode="r"``（只读，外部推值 → 画面刷新，向后兼容存量页面）；
  ``mode="rw"`` / ``"w"`` 额外打开反向写——用户在运行态操作 widget 控件或点击
  checkbox 图元时，把新值作为写请求发到 ``TagBus.writeRequested``，由外部业务
  / PLC 订阅后真正写设备。Designer_V2 自身不碰 PLC。
* **显示写不污染**：读方向把值写进实时显示字段，不写设计数据（见
  :meth:`runtime.elements.RuntimeElement.apply_binding`）。
* **tag 手填字符串**：DesignerV2 刻意不含 PLC / 点位表，tag 是自由字符串，
  外部按同名 key 推给 ``TagBus.update`` / 订阅 ``TagBus.writeRequested`` 即可。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from PySide6.QtGui import QColor


@dataclass(frozen=True)
class BindableProperty:
    """一个可绑定的图元属性。"""

    key: str            # page 记录里的字段名（style.* 用不带前缀的短名）
    label: str          # 属性面板显示名
    apply: str          # 缺省 coercion 种类
    target: str         # "element"（写 RuntimeElement 显示字段）或 "control"（写 QWidget）
    types: tuple[str, ...] | None = None  # 适用图元类型；None 表示全部


# 顺序即属性面板的展示顺序。几何属性刻意不在表内。
BINDABLE_PROPERTIES: tuple[BindableProperty, ...] = (
    BindableProperty("context", "文本内容", "text", "element", ("text",)),
    BindableProperty("checked", "勾选状态", "bool", "element", ("checkbox",)),
    BindableProperty("visible", "可见性", "bool", "element"),
    BindableProperty("stroke", "描边色", "color", "element"),
    BindableProperty("fill_color", "填充色", "color", "element"),
    BindableProperty("fill", "填充开关", "bool", "element"),
    BindableProperty("opacity", "不透明度", "number", "element"),
    BindableProperty("strokeWidth", "线宽", "number", "element"),
    BindableProperty("cornerRadius", "圆角", "number", "element"),
    BindableProperty("font_size", "字号", "number", "element", ("text",)),
    BindableProperty("widgetText", "控件文本", "text", "control", ("widget",)),
    BindableProperty("widgetValue", "控件数值", "number", "control", ("widget",)),
)

BY_KEY: dict[str, BindableProperty] = {p.key: p for p in BINDABLE_PROPERTIES}

# apply 下拉：(内部值, 中文标签)
APPLY_KINDS: tuple[tuple[str, str], ...] = (
    ("text", "文本"),
    ("bool", "布尔"),
    ("number", "数值"),
    ("color", "颜色"),
    ("raw", "原值"),
)
APPLY_LABELS: dict[str, str] = dict(APPLY_KINDS)

# 读写方向下拉：(内部值, 中文标签)。缺省 "r" 保持存量页面只读语义。
MODE_KINDS: tuple[tuple[str, str], ...] = (
    ("r", "只读（画面显示）"),
    ("rw", "读写（可回写）"),
    ("w", "只写（仅回写）"),
)
MODE_LABELS: dict[str, str] = dict(MODE_KINDS)
DEFAULT_MODE = "r"

# 只有这些属性在运行时有"用户交互产出值"的入口，可打开反向写：
#   checked → checkbox 图元点击切换；widgetText/widgetValue → 真实控件编辑。
# 其余属性即使设成 rw 也不会有写事件（纯显示），面板对它们隐藏方向下拉。
WRITABLE_FIELDS: frozenset[str] = frozenset(
    {"checked", "widgetText", "widgetValue"})


def bindables_for(type_name: str) -> list[BindableProperty]:
    """某图元类型可绑定的属性列表。"""
    return [p for p in BINDABLE_PROPERTIES
            if p.types is None or type_name in p.types]


def normalize_binding(entry: Any, default_apply: str = "text") -> dict[str, str]:
    """把一条绑定规格规范成 ``{"tag", "apply", "mode"}``。

    ``mode`` 缺省 ``"r"``（只读），因此存量页面里没有这个键的绑定行为不变。
    """
    if isinstance(entry, str):
        return {"tag": entry, "apply": default_apply, "mode": DEFAULT_MODE}
    if isinstance(entry, dict):
        tag = str(entry.get("tag") or "").strip()
        apply = str(entry.get("apply") or "").strip() or default_apply
        if apply not in APPLY_LABELS:
            apply = default_apply
        mode = str(entry.get("mode") or "").strip().lower() or DEFAULT_MODE
        if mode not in MODE_LABELS:
            mode = DEFAULT_MODE
        return {"tag": tag, "apply": apply, "mode": mode}
    return {"tag": "", "apply": default_apply, "mode": DEFAULT_MODE}


def is_readable(norm: dict[str, str]) -> bool:
    """该绑定是否需要"外部推值 → 画面刷新"。"""
    return norm.get("mode", DEFAULT_MODE) in ("r", "rw")


def is_writable(norm: dict[str, str]) -> bool:
    """该绑定是否需要"用户操作 → 回写 tag"；字段本身还须在 WRITABLE_FIELDS。"""
    return norm.get("mode", DEFAULT_MODE) in ("w", "rw")


def coerce(value: Any, apply: str) -> Any:
    """按 apply 种类把外部值转成图元 / 控件能吃的值。

    * ``bool``：'1' / 'true' / 'on' / 'yes' 及非零数值为真；
    * ``number``：转 float（整数值保持 int 观感由消费方决定）；
    * ``color``：'#rrggbb' / 颜色名 / 0xRRGGBB 数值统一成 '#rrggbb'；
    * 其余按原值 / 字符串透传。
    """
    if apply == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes")
        return bool(value)
    if apply == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    if apply == "color":
        return _color_text(value)
    if apply == "raw":
        return value
    return "" if value is None else str(value)


def _color_text(value: Any) -> str:
    """把数值 / 字符串颜色统一成 ``#rrggbb``；无法识别退回黑。"""
    if isinstance(value, bool):
        return "#ffffff" if value else "#000000"
    if isinstance(value, int):
        return "#{:06x}".format(value & 0xFFFFFF)
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        try:
            c = QColor(int(value[0]), int(value[1]), int(value[2]))
            return c.name() if c.isValid() else "#000000"
        except (TypeError, ValueError):
            return "#000000"
    c = QColor(str(value))
    return c.name() if c.isValid() else "#000000"


def iter_page_bindings(page_record: dict) -> Iterable[tuple[str, dict[str, str]]]:
    """遍历一条 page 记录里所有"属性 → 有效绑定"对，跳过空 tag 与非法属性。"""
    raw = page_record.get("bindings")
    if not isinstance(raw, dict):
        return
    for field, entry in raw.items():
        spec = BY_KEY.get(str(field))
        if spec is None:
            continue
        norm = normalize_binding(entry, spec.apply)
        if norm["tag"]:
            yield field, norm
