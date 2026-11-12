import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, Signal,QPointF
from PySide6.QtGui import QColor

from Designer.Core.elements import base_element, group_element, text_element,rect_element,triangle_element,widget_element

from Designer.Core.myQuadTreeScene import SceneManager

from .test import ConfigWindow,Rcd,Recipe,AGV_interact
from common.com.snap7 import PLCManager
from snap7.util import *
from common.com.snap7 import DataBroker

class _PlcBackendMixin:
    """页面模型的 PLC 后台资源回收。

    每个模型都会建 ``PLCManager`` + ``DataBroker``，而这两样东西各自带
    长生命周期线程：

    * ``PLCManager`` 的心跳线程 / 重连线程（``threading.Thread``，daemon）；
    * ``DataBroker`` 的 ``PollingThread``（``QThread``）。

    宿主窗口关掉时如果不停它们：重连线程会一直打印"尝试重连"（PLC 未
    上线时尤其明显），``QThread`` 在对象被回收时仍在运行还会让 Qt 直接
    终止进程。所以关窗必须显式调 :meth:`shutdown`。
    """

    _plc_mgr: Optional[PLCManager]
    _data_broker: Optional[DataBroker]

    def shutdown(self) -> None:
        """停掉数据轮询与 PLC 心跳/重连线程。可在 UI 线程直接调用。"""
        broker = getattr(self, "_data_broker", None)
        if broker is not None:
            stopped = True
            try:
                # 只等很短时间：关闭流程跑在 UI 线程上，等多久窗口就卡多久，
                # 而 launcher 的回落是排在事件循环里的定时器，卡住就表现为
                # "关掉工具后选择页迟迟不出现"。轮询线程的断线睡眠是 100ms，
                # 300ms 足够它醒来看到中断标志。
                stopped = broker.stop_data_polling(wait_ms=300)
            except RuntimeError:
                # 底层 C++ 对象已随宿主销毁
                stopped = True
            if not stopped:
                # 线程没停住（多半正卡在 db_read 里）。**绝不能**让它随窗口
                # 一起销毁：窗口一删，broker 的 C++ 对象就没了，线程下一轮
                # 摸 broker.data_ready 会直接段错误，整个进程崩掉——界面上
                # 看起来就是"工具页出来了，但点什么都没反应"。
                # 摘下来保活，等线程自己退出后再回收。
                try:
                    from common.com.snap7.snap7_data_broker import (
                        keep_alive_until_stopped,
                    )

                    keep_alive_until_stopped(broker)
                except Exception:  # noqa: BLE001
                    pass
        mgr = getattr(self, "_plc_mgr", None)
        if mgr is not None:
            try:
                mgr.shutdown()
            except Exception:
                pass


class Page0_Model(_PlcBackendMixin, QObject):
    """料仓状态面板模型：按 (模块, 通道, 灯位) 访问 32 盏灯和 4 个文本。

    图元靠名字识别，所以场景重新加载（再次 ``load_element_info2``）之后
    必须调 ``refresh()``，否则旧引用会随图元删除而失效。
    """

    #: 场景里承载 RCD 日志列表的 widget 图元名。
    WIDGET_NAME = "Page0"

    def __init__(self, scene_manager: SceneManager,parent=None):
        super().__init__(parent)
        self._manager = scene_manager
        # 后台资源先置空：场景里找不到图元时会提前 return，那时也必须能
        # 安全地调 shutdown()（否则关窗流程会 AttributeError）。
        self._plc_mgr: Optional[PLCManager] = None
        self._data_broker: Optional[DataBroker] = None

        self.group:widget_element = scene_manager.findItemByName(self.WIDGET_NAME)
        if self.group is None:
            # 场景里没有这个图元时不要继续：后面 set_widget_factory 会
            # AttributeError，把整个料仓窗口的构造带崩（表现为标签页打不开）。
            print(f"场景里没有名为 {self.WIDGET_NAME} 的控件图元，"
                  f"未挂载")
            return

        plc_mgr = PLCManager("192.168.1.1", 0, 1)
        data_broker = DataBroker(plc_mgr)

        # w = ConfigWindow(plc_mgr,data_broker,'SerialNumber',parent=parent)

        # 注意：set_widget_factory 要的是**可调用对象** ``factory(host) -> QWidget``，
        # 不是控件实例。直接传 ``Rcd(...)`` 实例的话，承载层重建时会去
        # ``instance(host)``，抛 TypeError: 'Rcd' object is not callable。
        # 这里用闭包延迟创建，等 overlay 视图真正建起来才实例化控件。
        self._plc_mgr = plc_mgr
        self._data_broker = data_broker
        self.group.set_widget_factory(self._make_rcd)

    def _make_rcd(self, host):
        """控件工厂：每个承载视图创建一个 RCD 日志列表。"""
        # return Rcd(self._plc_mgr, parent=host)
        return ConfigWindow(self._plc_mgr,self._data_broker,'SerialNumber',parent=host)


class Page1_Model(_PlcBackendMixin, QObject):
    """料仓状态面板模型：按 (模块, 通道, 灯位) 访问 32 盏灯和 4 个文本。

    图元靠名字识别，所以场景重新加载（再次 ``load_element_info2``）之后
    必须调 ``refresh()``，否则旧引用会随图元删除而失效。
    """

    #: 场景里承载 RCD 日志列表的 widget 图元名。
    WIDGET_NAME = "Page1"

    def __init__(self, scene_manager: SceneManager,parent=None):
        super().__init__(parent)
        self._manager = scene_manager
        # 后台资源先置空：场景里找不到图元时会提前 return，那时也必须能
        # 安全地调 shutdown()（否则关窗流程会 AttributeError）。
        self._plc_mgr: Optional[PLCManager] = None
        self._data_broker: Optional[DataBroker] = None

        self.group:widget_element = scene_manager.findItemByName(self.WIDGET_NAME)
        if self.group is None:
            # 场景里没有这个图元时不要继续：后面 set_widget_factory 会
            # AttributeError，把整个料仓窗口的构造带崩（表现为标签页打不开）。
            print(f"场景里没有名为 {self.WIDGET_NAME} 的控件图元，"
                  f"未挂载")
            return

        plc_mgr = PLCManager("192.168.1.1", 0, 1)
        data_broker = DataBroker(plc_mgr)

        # w = ConfigWindow(plc_mgr,data_broker,'SerialNumber',parent=parent)

        # 注意：set_widget_factory 要的是**可调用对象** ``factory(host) -> QWidget``，
        # 不是控件实例。直接传 ``Rcd(...)`` 实例的话，承载层重建时会去
        # ``instance(host)``，抛 TypeError: 'Rcd' object is not callable。
        # 这里用闭包延迟创建，等 overlay 视图真正建起来才实例化控件。
        self._plc_mgr = plc_mgr
        self._data_broker = data_broker
        self.group.set_widget_factory(self._make_rcd)

    def _make_rcd(self, host):
        """控件工厂：每个承载视图创建一个 RCD 日志列表。"""
        # return Rcd(self._plc_mgr, parent=host)
        return Recipe(self._plc_mgr,self._data_broker,parent=host)


class Page3_Model(_PlcBackendMixin, QObject):
    """料仓状态面板模型：按 (模块, 通道, 灯位) 访问 32 盏灯和 4 个文本。

    图元靠名字识别，所以场景重新加载（再次 ``load_element_info2``）之后
    必须调 ``refresh()``，否则旧引用会随图元删除而失效。
    """

    #: 场景里承载 RCD 日志列表的 widget 图元名。
    WIDGET_NAME = "Page3"

    def __init__(self, scene_manager: SceneManager,parent=None):
        super().__init__(parent)
        self._manager = scene_manager
        # 后台资源先置空：场景里找不到图元时会提前 return，那时也必须能
        # 安全地调 shutdown()（否则关窗流程会 AttributeError）。
        self._plc_mgr: Optional[PLCManager] = None
        self._data_broker: Optional[DataBroker] = None

        self.group:widget_element = scene_manager.findItemByName(self.WIDGET_NAME)
        if self.group is None:
            # 场景里没有这个图元时不要继续：后面 set_widget_factory 会
            # AttributeError，把整个料仓窗口的构造带崩（表现为标签页打不开）。
            print(f"场景里没有名为 {self.WIDGET_NAME} 的控件图元，"
                  f"未挂载")
            return

        plc_mgr = PLCManager("192.168.1.1", 0, 1)
        data_broker = DataBroker(plc_mgr)

        # w = ConfigWindow(plc_mgr,data_broker,'SerialNumber',parent=parent)

        # 注意：set_widget_factory 要的是**可调用对象** ``factory(host) -> QWidget``，
        # 不是控件实例。直接传 ``Rcd(...)`` 实例的话，承载层重建时会去
        # ``instance(host)``，抛 TypeError: 'Rcd' object is not callable。
        # 这里用闭包延迟创建，等 overlay 视图真正建起来才实例化控件。
        self._plc_mgr = plc_mgr
        self._data_broker = data_broker
        self.group.set_widget_factory(self._make_rcd)

    def _make_rcd(self, host):
        """控件工厂：每个承载视图创建一个 RCD 日志列表。"""
        # return Rcd(self._plc_mgr, parent=host)
        return AGV_interact(self._plc_mgr,self._data_broker,parent=host)