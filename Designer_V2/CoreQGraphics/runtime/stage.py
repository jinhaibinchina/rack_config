"""统一运行态顶层装配 :class:`RuntimeStage` + 轻量数据总线 :class:`TagBus`。

一个 stage 就是一套完整可运行的画面，装配顺序被固定在这里，业务侧不再需要
记住「先 load_page 还是先 set_scene_mode」「proxy 什么时候会失效」这些坑：

.. code-block:: text

    RuntimeStage(...)
      ├─ RuntimeScene     核心 GraphicsScene + 点击路由
      ├─ RuntimeView      运行态视图（取景 / 导航门控 / 坐标换算）
      ├─ RuntimeRegistry  图元门面索引（自动跟随 structureChanged 重建）
      ├─ WidgetHost       widget 图元 → 真实控件（provider 可插拔）
      └─ TagBus           外部数据 → 图元 / 控件的去抖绑定

    load(path) 时序：
      widgets.reset() → scene.load_page() → enter_run_mode()
      → registry.rebuild() → widgets.rebuild() → view.fit_scene()

``reset`` 必须在 ``load_page`` 之前：``clear_page()`` 会删光场景内所有 item，
包括自建 proxy；等删完再回收就只剩已析构的 C++ wrapper。

普通图元与 widget 图元的两条路径在该装配里是**同一个注册表**：

* 普通图元：``stage.element_of(name)`` → 改颜色 / 文本 / 可见性 / 位置 / 点击；
* widget 图元：``stage.widget(name)`` → 拿真实 QWidget；工厂由
  ``set_factory`` / ``set_mapping`` / ``set_provider`` 注入。

业务数据不绑死 PLC：外部把值推给 :meth:`TagBus.update`，由 :class:`TagBus`
按 ``flush_ms`` 合流后统一灌给绑定目标（PopPick 的 ``HmiPagesHost`` 和 rack
的 model 各自都有这套逻辑，这里抽成一份）。
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QWidget

if __package__ in (None, ""):
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)


from .elements import (  # noqa: E402
    GEOMETRY_PROFILES, STRICT_PROFILE, GeometryProfile, RuntimeElement,
    RuntimeRegistry,
)
from .view import RuntimeScene, RuntimeView  # noqa: E402
from .widgets import (  # noqa: E402
    ControlProvider, DefaultControlProvider, WidgetHost,
)
from ..g_binding import BY_KEY  # noqa: E402


def _control_apply(field: str, apply: str) -> Callable[[Any, Any], None]:
    """widget 图元绑定的写值函数：按字段与控件能力探测 setter。"""
    def _apply(widget, value):
        if widget is None:
            return
        if field == "widgetText":
            text = "" if value is None else str(value)
            setter = (getattr(widget, "setText", None)
                      or getattr(widget, "setPlainText", None))
            if callable(setter):
                setter(text)
            return
        # widgetValue：数值控件 setValue，其余退回 setText
        num = value
        if isinstance(value, str):
            try:
                num = float(value)
            except ValueError:
                num = 0.0
        setter = getattr(widget, "setValue", None)
        if callable(setter):
            try:
                setter(num)
                return
            except (TypeError, ValueError):
                pass
        text_setter = (getattr(widget, "setText", None)
                       or getattr(widget, "setPlainText", None))
        if callable(text_setter):
            text_setter("" if value is None else str(value))

    return _apply


def _default_apply(target: Any, value: Any) -> None:
    """没给 ``apply`` 时的兜底：按控件 / 图元已有方法探测，不猜业务语义。"""
    if target is None:
        return
    if isinstance(target, RuntimeElement):
        target.context = "" if value is None else str(value)
        return
    for name, coerce in (("setChecked", lambda v: bool(v) if not isinstance(v, str)
                          else v.lower() in ("1", "true", "on")),
                         ("setValue", lambda v: int(float(v))),
                         ("setText", str)):
        method = getattr(target, name, None)
        if callable(method):
            try:
                method(coerce(value))
                return
            except (TypeError, ValueError):
                continue
    setter = getattr(target, "apply_value", None)
    if callable(setter):
        setter(value)


class TagBus(QObject):
    """外部数据 → 画面的合流总线。

    PLC / 网络逐点推送的值先进 ``_pending``，由一条 singleShot 定时器合流后
    发 :attr:`valuesChanged`。逐点直刷会让 ``QGraphicsProxyWidget`` 每来一个点
    重画整张页面；这是 PopPick 实测过的卡顿来源。
    """

    valuesChanged = Signal(object)   # dict[str, Any]

    def __init__(self, flush_ms: int = 80, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._values: dict[str, Any] = {}
        self._pending: dict[str, Any] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(16, int(flush_ms)))
        self._timer.timeout.connect(self.flush)

    def flush_ms(self) -> int:
        return self._timer.interval()

    def set_flush_ms(self, ms: int) -> None:
        self._timer.setInterval(max(16, int(ms)))

    def update(self, key: str, value: Any) -> None:  # noqa: A003 - 业务命名
        self._pending[str(key)] = value
        if not self._timer.isActive():
            self._timer.start()

    def update_many(self, values: dict) -> None:
        self._pending.update({str(k): v for k, v in values.items()})
        if not self._timer.isActive():
            self._timer.start()

    def flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, {}
        self._values.update(batch)
        self.valuesChanged.emit(dict(batch))

    def flush_now(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
        self.flush()

    def value(self, key: str, default: Any = None) -> Any:
        return self._values.get(str(key), default)

    def values(self) -> dict[str, Any]:
        return dict(self._values)

    def clear(self) -> None:
        self._pending.clear()
        self._values.clear()

    def stop(self) -> None:
        self._timer.stop()
        self._pending.clear()


class StageBinding:
    """一条 ``tag key → 目标`` 绑定。

    目标用**解析函数**保存而不是缓存对象：换页 / 控件重建后解析到的是新对象，
    不需要业务重写绑定，也不会拿到悬空引用。
    """

    def __init__(self, stage: "RuntimeStage", key: str,
                 resolver: Callable[[], Any],
                 apply: Callable[[Any, Any], None] | None = None,
                 *, is_control: bool = False) -> None:
        self.stage = stage
        self.key = str(key)
        self.resolver = resolver
        self.apply = apply or _default_apply
        self.is_control = is_control
        self.enabled = True

    def target(self) -> Any:
        try:
            return self.resolver()
        except RuntimeError:
            return None

    def push(self, value: Any) -> None:
        if not self.enabled:
            return
        target = self.target()
        if target is not None:
            self.apply(target, value)

    def replay(self) -> None:
        """控件重建 / 换页后用缓存值补灌一次，避免先显示一屏 ``--``。"""
        if self.stage.tags.value(self.key, _MISSING) is not _MISSING:
            self.push(self.stage.tags.value(self.key))

    def close(self) -> None:
        self.enabled = False


_MISSING = object()


class RuntimeStage(QObject):
    """一套完整运行态画面。典型用法：

    >>> stage = RuntimeStage(page_path=".../page_1.json")
    >>> layout.addWidget(stage.view)                       # doctest: +SKIP
    >>> stage.set_factory("HMI1", lambda host: MyHmiPage(host))  # doctest: +SKIP
    >>> stage.load()                                       # doctest: +SKIP
    >>> stage.element_of("仓位编号1").set_color("#ff0000") # doctest: +SKIP
    >>> stage.tags.update("db41.slot1", 3)                 # doctest: +SKIP
    """

    pageAboutToLoad = Signal()
    pageLoaded = Signal(int)
    pageFailed = Signal(str)
    elementClicked = Signal(object)
    controlCreated = Signal(int, object)

    def __init__(self, parent: QObject | None = None, *, page_path: str = "",
                 widget_mode: str = "host", fit_mode: str = "fit",
                 navigation: bool = False, geometry_profile: Any = None,
                 provider: ControlProvider | None = None,
                 flush_ms: int = 80) -> None:
        super().__init__(parent)
        if isinstance(geometry_profile, str):
            geometry_profile = GEOMETRY_PROFILES.get(geometry_profile)
            if geometry_profile is None:
                raise ValueError(f"未知几何口径，可选 {sorted(GEOMETRY_PROFILES)}")
        self.page_path = page_path
        self.load_error = ""
        self.widget_mode = widget_mode
        self.scene = RuntimeScene()
        self.view = RuntimeView(self.scene, fit_mode=fit_mode,
                                navigation=navigation, stage=self)
        self.registry = RuntimeRegistry(
            self.scene, stage=self,
            profile=geometry_profile or STRICT_PROFILE)
        self.widgets = WidgetHost(self.scene, self.registry, stage=self,
                                  mode=widget_mode, provider=provider)
        self.scene.attach_registry(self.registry)
        self.tags = TagBus(flush_ms, self)
        self.tags.valuesChanged.connect(self._dispatch)
        self._bindings: list[StageBinding] = []
        # 由页面 bindings 字段派生的绑定，与业务手动 bind_* 分开记账：
        # reload() 只清这一批，不碰业务在构造时注册的绑定。
        self._page_bindings: list[StageBinding] = []

        # 旧 API 门面：rack 的 model 拿 scene_manager，PopPick 的 PageDeck
        # 拿 pages_manager（只暴露 widget 卡片）。
        self.scene_manager = self.registry.legacy_manager(m_scene=self.view)
        self.pages_manager = self.registry.legacy_manager(
            only_widgets=True, m_scene=self.view)
        self.view.scene_manager = self.scene_manager

        self.scene.elementClicked.connect(self.elementClicked.emit)
        self.widgets.controlCreated.connect(self._on_control_created)
        self.widgets.controlCreated.connect(self.controlCreated.emit)

    # -- 装配 / 生命周期 ------------------------------------------------
    def load(self, path: str | None = None) -> int:
        """载入页面并切运行态；失败时返回 0、发 :attr:`pageFailed`，窗口仍可用。"""
        target = path or self.page_path
        if not target:
            self.load_error = "未指定页面路径"
            self.pageFailed.emit(self.load_error)
            return 0
        self.pageAboutToLoad.emit()
        self.load_error = ""
        try:
            self.widgets.reset()          # 必须在 clear_page 之前
            count = self.scene.load_page(target)
            self.page_path = target
            self.enter_run_mode(True)
            self.registry.rebuild()       # 显式再做一次，保证时序不依赖信号
            self.widgets.rebuild()
            self._clear_page_bindings()
            self._load_page_bindings()    # 设计态存的 bindings → TagBus 注册
            self.fit()
        except (OSError, ValueError, KeyError) as exc:
            self.load_error = f"场景载入失败：{exc}"
            self.pageFailed.emit(self.load_error)
            return 0
        if not count:
            self.load_error = f"场景为空或文件缺失：{target}"
            self.pageFailed.emit(self.load_error)
        self.pageLoaded.emit(count)
        return count

    def reload(self) -> int:
        """重新载入同一页面（设计器改完不想重启时用）。"""
        return self.load(self.page_path)

    def enter_run_mode(self, run: bool = True) -> None:
        """统一切运行态。

        ``builtin`` 走核心的 ``set_scene_mode(True)``（proxy 由核心创建）；
        ``host`` / ``none`` 刻意**不调**它，只写 ``is_run_mode`` 并关掉选中
        / hover / 拖拽——否则核心会按 widgetType 造一套默认控件，和
        :class:`~.widgets.WidgetHost` 的工厂抢同一批图元。
        """
        if self.widgets.mode == "builtin" and run:
            self.scene.set_scene_mode(True)
            self.view.apply_run_mode(True)
        elif run:
            self.scene._widget_layer_on = False
            self.view.apply_run_mode(True)
        else:
            self.scene.set_scene_mode(False)
            self.scene.is_run_mode = False

    @property
    def fit_mode(self) -> str:
        return self.view.fit_mode

    @property
    def geometry_profile(self) -> GeometryProfile:
        return self.registry.profile

    def fit(self) -> bool:
        return self.view.fit_scene()

    def attach(self, layout) -> None:
        """把 view 塞进调用方的 QLayout。"""
        layout.addWidget(self.view)

    def release(self) -> None:
        """关窗：回收控件 / 解绑信号 / 停定时器 / 清场景（可重复调用）。"""
        self.widgets.release()
        self.registry.disconnect_scene()
        self.tags.stop()
        for binding in self._bindings:
            binding.close()
        self._bindings.clear()
        self._page_bindings.clear()
        self.scene.clear_page()

    def __del__(self):  # pragma: no cover - 解释器退出兜底
        try:
            self.widgets.release()
        except Exception:
            pass

    # -- 图元 / 控件查询 ------------------------------------------------
    def element_of(self, key: Any) -> Optional[RuntimeElement]:
        return self.registry.find(key)

    def elements(self) -> list[RuntimeElement]:
        return self.registry.sorted()

    def widget(self, key: Any) -> Optional[QWidget]:
        """按名字 / id 拿 widget 图元上的真实 QWidget。"""
        return self.widgets.control_of(key)

    def controls(self) -> dict[int, QWidget]:
        return self.widgets.controls()

    def set_interactive(self, keys, *, types: tuple[str, ...] | None = None,
                        enable: bool = True) -> int:
        """批量打开点击路由；``keys=None`` 表示全部 / 指定类型。"""
        if types is not None:
            self.scene.hit_types = tuple(types)
        if keys is None:
            targets = [e for e in self.registry.all()
                       if types is None or e.TYPE in types]
        else:
            targets = [self.registry.find(k) for k in keys]
        n = 0
        for element in targets:
            if element is not None:
                element.set_interactive(enable)
                n += 1
        return n

    # -- provider -------------------------------------------------------
    def set_provider(self, provider: ControlProvider) -> None:
        self.widgets.set_provider(provider)

    def set_factory(self, key: Any, factory: Callable) -> None:
        """PopPick 口径：某个 widget 图元用外部工厂造任意 QWidget。"""
        self.widgets.set_factory(key, factory)

    def set_mapping(self, mapping: dict) -> None:
        """批量 ``{图元名或 id: factory | QWidget | ControlProvider}``。"""
        self.widgets.set_mapping(mapping)

    @property
    def default_provider(self) -> DefaultControlProvider:
        return DefaultControlProvider()

    # -- 数据绑定 -------------------------------------------------------
    def _clear_page_bindings(self) -> None:
        """丢弃上一页由 bindings 字段派生的绑定（业务手动绑定不动）。"""
        for binding in self._page_bindings:
            binding.close()
            if binding in self._bindings:
                self._bindings.remove(binding)
        self._page_bindings.clear()

    def _load_page_bindings(self) -> int:
        """扫描当前页每个图元的 ``bindings`` 字段并注册到 :attr:`tags`。

        设计态存的是自由字符串 tag；运行态按 ``target`` 分两路：

        * ``element``：绑到 :class:`RuntimeElement`，apply 走
          :meth:`RuntimeElement.apply_binding`（只写显示字段，不污染 ``_page``）；
        * ``control``：绑到 widget 图元的真实控件，apply 走 :func:`_control_apply`。

        两条路都用 :meth:`bind_element` / :meth:`bind_control`，目标每次现查，
        换页 / 控件重建不断线。返回成功注册的绑定条数。
        """
        scene = self.scene
        count = 0
        for it in scene.all_items():
            rec = it.page_record()
            raw = rec.get("bindings")
            if not isinstance(raw, dict) or not raw:
                continue
            iid = int(it.item_id)
            for field, entry in raw.items():
                spec = BY_KEY.get(str(field))
                if spec is None:
                    continue
                tag = str((entry or {}).get("tag") or "").strip() \
                    if isinstance(entry, dict) else str(entry or "").strip()
                if not tag:
                    continue
                apply = str((entry or {}).get("apply") or spec.apply) \
                    if isinstance(entry, dict) else spec.apply
                if spec.target == "control" and it.TYPE == "widget":
                    binding = self.bind_control(
                        tag, iid, apply=_control_apply(str(field), apply))
                else:
                    binding = self.bind_element(
                        tag, iid,
                        apply=lambda el, v, f=str(field), a=apply:
                        el.apply_binding(f, v, a))
                self._page_bindings.append(binding)
                count += 1
        return count

    def page_binding_count(self) -> int:
        """当前页由 bindings 字段派生的绑定条数（诊断用）。"""
        return len(self._page_bindings)

    def _dispatch(self, values: dict) -> None:
        for binding in list(self._bindings):
            if binding.key in values:
                binding.push(values[binding.key])

    def _on_control_created(self, _iid: int, _widget) -> None:
        # 控件被重建后，用总线缓存把旧值补灌回新控件
        for binding in list(self._bindings):
            if binding.is_control:
                binding.replay()

    def bind(self, key: str, target: Any,
             apply: Callable[[Any, Any], None] | None = None) -> StageBinding:
        """绑定一个**已解析**的对象（RuntimeElement / QWidget / 自定义对象）。"""
        binding = StageBinding(self, key, lambda t=target: t, apply,
                               is_control=isinstance(target, QWidget))
        self._bindings.append(binding)
        binding.replay()
        return binding

    def bind_element(self, key: str, element_key: Any,
                     apply: Callable[[RuntimeElement, Any], None] | None = None
                     ) -> StageBinding:
        """绑定到普通图元；目标按 key **每次现查**，换页不断线。"""
        binding = StageBinding(
            self, key, lambda: self.registry.find(element_key), apply)
        self._bindings.append(binding)
        binding.replay()
        return binding

    def bind_control(self, key: str, element_key: Any,
                     apply: Callable[[QWidget, Any], None] | None = None
                     ) -> StageBinding:
        """绑定到 widget 图元的真实控件；控件重建后自动 replay 缓存值。"""
        binding = StageBinding(
            self, key, lambda: self.widgets.control_of(element_key), apply,
            is_control=True)
        self._bindings.append(binding)
        binding.replay()
        return binding

    def unbind(self, binding: StageBinding) -> None:
        binding.close()
        if binding in self._bindings:
            self._bindings.remove(binding)

    def report(self) -> str:
        """一行状态摘要，便于日志排查。"""
        return (f"RuntimeStage(page={os.path.basename(self.page_path)!r}, "
                f"elements={len(self.registry)}, "
                f"widgets={len(self.registry.widgets())}, "
                f"proxies={len(self.widgets.proxies())}, "
                f"mode={self.widgets.mode}, profile={self.registry.profile.name}, "
                f"bindings={len(self._bindings)}, error={self.load_error!r})")
