"""PopPick OPC UA HMI 页面包。

* ``tag_catalog`` —— 变量表表达式 → OPC UA 节点（区分已验证 / 推断候选）；
* ``widgets`` —— 深色工业 HMI 通用控件；
* ``pages`` —— 7 个页面 widget 及注册表；
* ``binding`` —— OPC UA 订阅、写入、以及挂到场景卡片上的宿主。

快速用法（不连 PLC、不进场景也能看版式）::

    QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe tools/preview_hmi_pages.py --demo

挂进 PopPick 场景（V2 由 ``pop_pick_runtime.PopPickRuntime.install_hmi`` 负责）::

    from App_PopPick_V2.hmi import attach_hmi_pages
    self._hmi = attach_hmi_pages(
        stage.pages_manager,                     # 只暴露 widget 卡片
        parent=self,
        static_policy=runtime.snapshots,         # 后台页位图交给业务侧
        auto_start=False,
    )
    self._hmi.set_active_cards(window.front_pages())
    self._hmi.start()                            # opc.tcp://192.168.1.88:4840
    # 关窗：self._hmi.shutdown()（PopPickRuntime.release 已包含）
"""

from .tag_catalog import TagCatalog, TagRef, clean_text, format_value

__all__ = ["TagCatalog", "TagRef", "clean_text", "format_value", "attach_hmi_pages"]


def attach_hmi_pages(*args, **kwargs):
    """延迟导入，避免只做变量解析时就把 OPC UA 客户端依赖拉起来。"""
    from .binding import attach_hmi_pages as _attach

    return _attach(*args, **kwargs)
