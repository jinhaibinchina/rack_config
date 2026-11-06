"""OPC UA 通信层（asyncua 封装），与 ``common.com.snap7`` 平级。

典型用法::

    from common.com.opcua import OpcConfig, OpcUaManager

    mgr = OpcUaManager(OpcConfig(endpoint="opc.tcp://192.168.1.10:4840"))
    mgr.subscribe({"lamp01": "ns=2;s=Rack.Lamp01"})
    mgr.node_changed.connect(on_change)      # (key, value)，服务端变化才推
    mgr.start()                              # 不阻塞，连接结果走信号

    mgr.write("lamp01", True)                # 同步写，和 snap7 手感一致
    mgr.read("lamp01")
    mgr.stop()                               # 必须调，否则线程残留
"""

from .opcua_manager import (
    ACCESS_WRITE_BIT,
    STANDARD_SUBTREES,
    OpcConfig,
    OpcUaManager,
    _release_orphan,
    install_quiet_reconnect,
    install_reconnect_diagnostics,
    is_standard_subtree,
    is_writable,
    keep_alive_until_stopped,
)
from .structure import (
    StructField,
    StructureReader,
    StructValue,
    flatten,
    is_builtin_datatype,
    is_struct_value,
)

__all__ = [
    "ACCESS_WRITE_BIT",
    "STANDARD_SUBTREES",
    "OpcConfig",
    "OpcUaManager",
    "StructField",
    "StructValue",
    "StructureReader",
    "flatten",
    "is_builtin_datatype",
    "install_quiet_reconnect",
    "install_reconnect_diagnostics",
    "is_standard_subtree",
    "is_struct_value",
    "is_writable",
    "keep_alive_until_stopped",
    "_release_orphan",
]
