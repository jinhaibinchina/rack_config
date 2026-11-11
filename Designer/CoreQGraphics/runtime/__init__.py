"""CoreQGraphics 统一运行态模板框架。

**这个包只新增、不修改核心代码。** ``GraphicsScene`` / ``GraphicsView`` /
``BaseItem`` 一行未动，设计器的几何对拍与 page JSON round-trip 不受影响。

它把散在四个文件里的运行态装配收成一套：

===================  ======================================================
类                    职责
===================  ======================================================
:class:`RuntimeStage` 顶层装配（load / reload / enter_run_mode / release）
:class:`RuntimeScene` 核心场景 + 点击路由
:class:`RuntimeView`  只读视图 / 取景 / 坐标换算 / 旧 API 门面
:class:`RuntimeElement` 普通图元与 widget 图元共用的稳定门面
:class:`RuntimeRegistry` 门面索引，自动跟随结构变化重建
:class:`WidgetHost`   widget 图元 → 真实 QWidget 的承载层
:class:`ControlProvider` 控件来源（默认控件 / 外部工厂 / 按名映射）
:class:`TagBus`       外部数据的去抖合流总线
===================  ======================================================

最小用法（同时覆盖普通图元与 widget 图元）::

    from Designer.CoreQGraphics.runtime import create_stage

    stage = create_stage(page_path=".../page_1.json",
                         geometry_profile="rack")
    layout.addWidget(stage.view)
    stage.load()

    # 普通图元
    stage.element_of("仓位编号1").set_color("#ff0000")
    stage.set_interactive(["HMI1"], types=("group", "checkbox"))

    # widget 图元：默认控件由 widgetType 决定，也可以按名注入整页工厂
    stage.set_factory("Page0", lambda host: MyHmiPage(host))
    stage.bind_control("db41.slot1", "仓位编号1")
    stage.tags.update("db41.slot1", 3)

三个必须显式选择的口径（旧项目迁移时按现状选，别用默认值硬套）：

* ``widget_mode``：``"host"``（本框架管 proxy）/ ``"builtin"``（核心内置 proxy）
  / ``"none"``；
* ``fit_mode``：``"fit"``（每次 resize 重算缩放）/ ``"pin"``（钉左上角）
  / ``"none"``；
* ``geometry_profile``：``"strict"`` / ``"rack"`` / ``"safety"``，四角与线段
  端点的定义不同，选错会让旋转图元坐标差几十到几百 page 单位。

详见 ``docs/unified_runtime_template_design.md``。
"""

from .elements import (
    GEOMETRY_PROFILES,
    RACK_PROFILE,
    SAFETY_PROFILE,
    STRICT_PROFILE,
    GeometryProfile,
    LegacyManager,
    RuntimeElement,
    RuntimeRegistry,
)
from .stage import RuntimeStage, StageBinding, TagBus
from .view import RuntimeScene, RuntimeView
from .widgets import (
    CallableProvider,
    ChainedProvider,
    ControlProvider,
    DefaultControlProvider,
    MappingProvider,
    WidgetHost,
)

__all__ = [
    "RuntimeStage", "RuntimeScene", "RuntimeView",
    "RuntimeElement", "RuntimeRegistry", "LegacyManager",
    "WidgetHost", "ControlProvider", "DefaultControlProvider",
    "CallableProvider", "MappingProvider", "ChainedProvider",
    "TagBus", "StageBinding",
    "GeometryProfile", "GEOMETRY_PROFILES",
    "STRICT_PROFILE", "RACK_PROFILE", "SAFETY_PROFILE",
    "create_stage",
]


def create_stage(**kwargs) -> RuntimeStage:
    """:class:`RuntimeStage` 的便捷构造入口（语义与直接构造完全一致）。"""
    return RuntimeStage(**kwargs)
