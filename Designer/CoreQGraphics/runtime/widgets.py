"""统一运行态：widget 图元的控件承载层 :class:`WidgetHost`。

现状是两条互不相干、还会互相抢同一批图元的路径：

* ``GraphicsScene.set_scene_mode(True)`` —— 内置 ``_sync_widget_proxies()``，
  按 ``widgetType`` 造 QLineEdit / QCheckBox / QSpinBox（rack 全局参数面板用它）；
* ``App_PopPick.qgraphics_runtime.RuntimeWidgetLayer`` —— 外部
  ``factory(host)`` 造整张 HMI 页面，刻意把 ``_widget_layer_on`` 关掉。

本模块把「谁来造控件」抽象成 :class:`ControlProvider`，把「怎么挂 / 对齐 /
回收 proxy」固定成一套实现，三条装配口径（自定义工厂 / 内置控件 / 不挂控件）
用 ``widget_mode`` 一个开关收口：

===================  =======================================================
``widget_mode``       行为
===================  =======================================================
``"host"``（默认）    本模块自建 proxy；``is_run_mode=True``，内置 layer 保持关闭
``"builtin"``         调 ``scene.set_scene_mode(True)`` 用核心内置 proxy；
                      :meth:`WidgetHost.control_of` 转成读 ``scene.widget_proxies``
``"none"``            只切运行模式，一个控件都不挂
===================  =======================================================

proxy 对齐是硬规则（与设计器 ``_align_widget_proxy``、PopPick
``sync_card`` 完全一致的口径）：

* proxy 是**独立顶层项**，不做图元 Qt 子项、不进 SceneIndex、不参与 page JSON；
* 控件本地矩形恒为 ``(0,0,w,h)``，用 ``resize`` 改尺寸（``setGeometry`` 会
  同步改写 pos），变换原点钉到 ``(w/2,h/2)``；
* ``pos = item.mapToScene(0,0) - (w/2,h/2)``，旋转 / z 跟随图元，z 加 0.5
  保证真实控件盖住占位框；
* 位姿没变就一个 Qt 调用都不发（7 张 750×1000 页面每帧全量 setPos 会到 100ms）。
"""

from __future__ import annotations

import inspect
import os
import sys
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsProxyWidget, QWidget,
)

if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)

from Designer.CoreQGraphics.g_widgets import (  # noqa: E402
    create_control, widget_style_sheet, widget_text, widget_variant,
)

try:
    _TRANSPARENT_MOUSE = Qt.WidgetAttribute.WA_TransparentForMouseEvents
except AttributeError:  # pragma: no cover - 旧式枚举别名
    _TRANSPARENT_MOUSE = Qt.WA_TransparentForMouseEvents

try:
    _ITEM_SELECTABLE = QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
    _ITEM_MOVABLE = QGraphicsItem.GraphicsItemFlag.ItemIsMovable
    _NO_CONTENTS = QGraphicsItem.GraphicsItemFlag.ItemHasNoContents
except AttributeError:  # pragma: no cover
    _ITEM_SELECTABLE = QGraphicsItem.ItemIsSelectable
    _ITEM_MOVABLE = QGraphicsItem.ItemIsMovable
    _NO_CONTENTS = QGraphicsItem.ItemHasNoContents


class ControlProvider:
    """控件工厂协议：``signature`` 决定是否重建，``create`` 负责造控件。"""

    def signature(self, element) -> tuple:
        return ()

    def create(self, element, host: QWidget | None = None) -> QWidget | None:
        raise NotImplementedError


class DefaultControlProvider(ControlProvider):
    """按 page JSON 的 ``widgetType`` 造基础控件（核心内置那一套）。"""

    def signature(self, element) -> tuple:
        it = element.item()
        if it is None:
            return ()
        record = it.page_record()
        return ("builtin", widget_variant(record), widget_text(record),
                widget_style_sheet(record))

    def create(self, element, host: QWidget | None = None) -> QWidget | None:
        it = element.item()
        if it is None:
            return None
        return create_control(it.page_record(), host)


class CallableProvider(ControlProvider):
    """包一个 ``factory(host)`` 或 ``factory(host, element)`` 的外部工厂。

    PopPick 的 ``HmiPagesHost._make_factory`` 是前者；需要按图元定制时用后者。
    """

    def __init__(self, factory: Callable, *, tag: Any = None) -> None:
        if not callable(factory):
            raise TypeError("factory 必须可调用")
        self.factory = factory
        self.tag = tag if tag is not None else id(factory)
        self._takes_element = self._probe(factory)

    @staticmethod
    def _probe(factory: Callable) -> bool:
        try:
            params = list(inspect.signature(factory).parameters.values())
        except (TypeError, ValueError):
            return False
        positional = [p for p in params if p.kind in (
            p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        return len(positional) >= 2

    def signature(self, element) -> tuple:
        return ("factory", self.tag, element.get_name())

    def create(self, element, host: QWidget | None = None) -> QWidget | None:
        if self._takes_element:
            return self.factory(host, element)
        return self.factory(host)


class MappingProvider(ControlProvider):
    """按图元名 / id 查工厂；没命中返回 ``None`` 以便链式回退到默认控件。

    ``mapping`` 的值可以是 callable、:class:`ControlProvider`，或者直接是一个
    已经造好的 ``QWidget``（同一个控件实例只允许挂一次）。
    """

    def __init__(self, mapping: dict | None = None) -> None:
        self.mapping: dict[Any, Any] = dict(mapping or {})

    def set(self, key: Any, value: Any) -> None:
        self.mapping[key] = value

    def lookup(self, element) -> Any:
        if element.item_id in self.mapping:
            return self.mapping[element.item_id]
        return self.mapping.get(element.get_name())

    def _provider(self, element) -> Optional[ControlProvider]:
        value = self.lookup(element)
        if value is None:
            return None
        if isinstance(value, ControlProvider):
            return value
        if isinstance(value, QWidget):
            return CallableProvider(lambda _host, _e, w=value: w,
                                    tag=id(value))
        return CallableProvider(value, tag=id(value))

    def signature(self, element) -> tuple:
        provider = self._provider(element)
        return ("map",) + provider.signature(element) if provider else ()

    def create(self, element, host: QWidget | None = None) -> QWidget | None:
        provider = self._provider(element)
        return provider.create(element, host) if provider is not None else None


class ChainedProvider(ControlProvider):
    """依次尝试多个 provider，取第一个给出控件的（Mapping → Default 常用）。"""

    def __init__(self, *providers: ControlProvider) -> None:
        self.providers = list(providers)

    def signature(self, element) -> tuple:
        # 只用 create 判定归属会真的造一次控件，这里改查 mapping 的 lookup
        for provider in self.providers:
            if isinstance(provider, MappingProvider):
                if provider.lookup(element) is not None:
                    return ("chain",) + provider.signature(element)
            elif provider.signature(element):
                return ("chain",) + provider.signature(element)
        return ("chain-default",)

    def create(self, element, host: QWidget | None = None) -> QWidget | None:
        for provider in self.providers:
            widget = provider.create(element, host)
            if widget is not None:
                return widget
        return None


class WidgetHost(QObject):
    """widget 图元 → 真实 QWidget 的唯一承载入口。

    自动跟随 ``structureChanged``（换页 / 增删）重建，跟随
    ``geometryChanged`` / ``itemChanged`` 只做位姿对齐，不重建控件。
    """

    controlCreated = Signal(int, object)     # (item_id, QWidget)
    controlDestroyed = Signal(int)

    def __init__(self, scene, registry, *, stage=None, mode: str = "host",
                 provider: ControlProvider | None = None) -> None:
        super().__init__(scene)
        if mode not in ("host", "builtin", "none"):
            raise ValueError("widget_mode 必须是 host / builtin / none")
        self.scene = scene
        self.registry = registry
        self.stage = stage
        self.mode = mode
        self.provider: ControlProvider = provider or DefaultControlProvider()
        self._mapping = MappingProvider()
        self._factories: dict[int, Callable] = {}
        self._proxies: dict[int, QGraphicsProxyWidget] = {}
        self._signatures: dict[int, tuple] = {}
        self._pose_state: dict[int, tuple] = {}
        self._readonly: dict[int, bool] = {}
        self._released = False
        self._bound: list[tuple[Any, Any]] = []
        self._connect_scene()

    @property
    def enabled(self) -> bool:
        return self.mode == "host" and not self._released

    # -- 场景信号 -------------------------------------------------------
    def _connect_scene(self) -> None:
        for name, slot in (("structureChanged", self.rebuild),
                           ("geometryChanged", self.align_all),
                           ("itemChanged", self._on_items_changed)):
            sig = getattr(self.scene, name, None)
            if sig is None:
                continue
            sig.connect(slot)
            self._bound.append((sig, slot))

    def disconnect_scene(self) -> None:
        for sig, slot in self._bound:
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._bound.clear()

    def _on_items_changed(self, ids) -> None:
        """字段变化可能改了 widgetType / widgetText：先按签名决定是否重建。"""
        if not self.enabled:
            return
        target = set(int(i) for i in (ids or []) if isinstance(i, int))
        if not target:
            self.rebuild()
            return
        for iid in target:
            element = self.registry.find(iid)
            if element is None or not element.is_widget():
                continue
            if self._signatures.get(iid) != self._signature(element):
                self._drop(iid)
                self._ensure(element)
        for iid in target:
            self.align(iid)

    # -- provider -------------------------------------------------------
    def set_provider(self, provider: ControlProvider) -> None:
        self.provider = provider
        self.rebuild()

    def set_factory(self, key: Any, factory: Callable) -> None:
        """给某个 widget 图元（名字或 id）单独指定工厂。"""
        element = self.registry.find(key)
        if element is None:
            return
        iid = element.item_id
        self._factories[iid] = factory
        self._mapping.set(iid, factory)
        if iid in self._proxies:
            self._drop(iid)
            self._ensure(element)

    def set_mapping(self, mapping: dict) -> None:
        """批量设置 ``{图元名或 id: factory | QWidget | ControlProvider}``。"""
        for key, value in mapping.items():
            element = self.registry.find(key)
            if element is None:
                self._mapping.set(key, value)
                continue
            self._mapping.set(element.item_id, value)
        self.rebuild()

    def _effective_provider(self) -> ControlProvider:
        return ChainedProvider(self._mapping, self.provider)

    def _signature(self, element) -> tuple:
        return self._effective_provider().signature(element)

    # -- 生命周期 -------------------------------------------------------
    def rebuild(self) -> None:
        """按当前页面同步 proxy 集合；换页后自动被调用。"""
        if self.mode != "host":
            # builtin / none 由 core 自己管，本层只保证不残留自建 proxy
            for iid in list(self._proxies):
                self._drop(iid)
            return
        if self._released:
            return
        wanted = {e.item_id: e for e in self.registry.widgets()
                  if e.get_visibility()}
        for iid in list(self._proxies):
            if iid not in wanted:
                self._drop(iid)
        for iid, element in wanted.items():
            if iid in self._proxies:
                if self._signatures.get(iid) != self._signature(element):
                    self._drop(iid)
                else:
                    continue
            self._ensure(element)
        self.align_all()

    def _ensure(self, element) -> None:
        if not self.enabled or element.item() is None:
            return
        iid = element.item_id
        widget = self._effective_provider().create(element, None)
        if widget is None:
            return
        if widget.parent() is not None:
            widget.setParent(None)
        proxy = QGraphicsProxyWidget()
        proxy.setFlag(_ITEM_SELECTABLE, False)
        proxy.setFlag(_ITEM_MOVABLE, False)
        self.scene.addItem(proxy)
        proxy.setWidget(widget)
        self._proxies[iid] = proxy
        self._signatures[iid] = self._signature(element)
        it = element.item()
        if it is not None:
            # 真实控件不透明，占位框不产出任何像素（大页面每帧省 ~10ms）
            it.setFlag(_NO_CONTENTS, True)
        self._apply_readonly(iid)
        self._pose_state.pop(iid, None)
        self.align(iid)
        self.controlCreated.emit(iid, widget)

    def _drop(self, iid: int) -> None:
        proxy = self._proxies.pop(iid, None)
        self._signatures.pop(iid, None)
        self._pose_state.pop(iid, None)
        element = self.registry.find(iid)
        if element is not None:
            it = element.item()
            if it is not None:
                it.setFlag(_NO_CONTENTS, False)
        if proxy is None:
            return
        widget = proxy.widget()
        try:
            proxy.setWidget(None)
        except RuntimeError:
            pass
        try:
            self.scene.removeItem(proxy)
        except RuntimeError:
            pass
        if widget is not None:
            try:
                # setWidget(None) 会把控件变成无父顶层窗口；不 hide /
                # deleteLater 就会留下盖住画面的「幽灵控件」。
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            except RuntimeError:
                pass
        self.controlDestroyed.emit(int(iid))

    def reset(self) -> None:
        """换页前主动回收全部 proxy，但**保留场景信号连接**。

        必须在 ``scene.load_page()`` 之前调用：``clear_page()`` 里的
        ``scene.clear()`` 会直接删掉场景内所有 item，若那时 proxy 还在
        ``_proxies`` 字典里，后面 rebuild 碰到的就是已析构的 C++ 对象。
        """
        for iid in list(self._proxies):
            self._drop(iid)
        self._signatures.clear()
        self._pose_state.clear()
        self._released = False

    def release(self) -> None:
        """关窗时彻底回收，之后不再重建（可重复调用）。"""
        self._released = True
        for iid in list(self._proxies):
            self._drop(iid)
        self.disconnect_scene()

    # -- 位姿对齐 -------------------------------------------------------
    def align(self, iid: int) -> None:
        proxy = self._proxies.get(int(iid))
        if proxy is None:
            return
        element = self.registry.find(int(iid))
        it = element.item() if element is not None else None
        if it is None:
            return
        rect = it.boundingRect()
        w, h = rect.width(), rect.height()
        center = it.mapToScene(QPointF(0.0, 0.0))
        pos = center - QPointF(w / 2.0, h / 2.0)
        rotation = it.rotation()
        z = it.zValue() + 0.5
        visible = element.effective_visibility() if element is not None else True
        state = (w, h, pos.x(), pos.y(), rotation, z, visible)
        if self._pose_state.get(iid) == state:
            return
        self._pose_state[iid] = state
        if abs(proxy.size().width() - w) > 1e-6 or \
                abs(proxy.size().height() - h) > 1e-6:
            proxy.resize(w, h)
            proxy.setTransformOriginPoint(QPointF(w / 2.0, h / 2.0))
        proxy.setPos(pos)
        proxy.setRotation(rotation)
        proxy.setZValue(z)
        proxy.setVisible(visible)

    def align_all(self, *_args) -> None:
        for iid in list(self._proxies):
            self.align(int(iid))

    # -- 查询 / 只读 ----------------------------------------------------
    def proxies(self) -> dict[int, QGraphicsProxyWidget]:
        if self.mode == "builtin":
            return dict(getattr(self.scene, "widget_proxies", {}) or {})
        return dict(self._proxies)

    def proxy_of(self, key: Any):
        element = self.registry.find(key)
        iid = element.item_id if element is not None else key
        return self.proxies().get(int(iid))

    def control_of(self, key: Any):
        proxy = self.proxy_of(key)
        return proxy.widget() if proxy is not None else None

    def has_proxy(self, iid: int) -> bool:
        return int(iid) in self.proxies()

    def controls(self) -> dict[int, QWidget]:
        return {iid: p.widget() for iid, p in self.proxies().items()
                if p.widget() is not None}

    def set_readonly(self, iid: int, readonly: bool) -> None:
        self._readonly[int(iid)] = bool(readonly)
        self._apply_readonly(int(iid))

    def readonly(self, iid: int) -> bool:
        return bool(self._readonly.get(int(iid), False))

    def _apply_readonly(self, iid: int) -> None:
        proxy = self._proxies.get(int(iid))
        if proxy is None:
            return
        value = self.readonly(iid)
        widget = proxy.widget()
        if widget is None:
            return
        # 只读只挡输入，不改外观（setEnabled(False) 会让整块控件变灰）
        for node in [widget, *widget.findChildren(QWidget)]:
            node.setAttribute(_TRANSPARENT_MOUSE, value)
