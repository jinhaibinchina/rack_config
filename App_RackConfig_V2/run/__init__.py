
# 本分支（App_RackConfig_V2）只跑 DesignerV2.CoreQGraphics 一套后端。
# 旧 Designer.Core 版（rack_store_widget / rack_stores_widget /
# rack_global_paras_widget）文件仍在磁盘上，但它们 import
# ``Designer.Core.myQuadTreeScene`` —— DesignerV2 里没有 ``Core`` 这个包，
# 一旦被导入整个 run 包就 ImportError，所以这里**不再**急切导入。
# 需要回滚旧窗口时，用旧项目 App_RackConfig，或在本环境的 sys.path 里补上
# 旧 ``Designer`` 包后手动 ``from .rack_store_widget import RackStoreWindow``。
from .rack_store_widget_v2 import RackStoreWindowV2

from .rack_stores_widget_v2 import RackStoresWindowV2

from .rack_global_paras_widget_v2 import RackGlobalParasWindowV2

from .rack_store_model import (
    CylinderState,
    LightColor,
    LightFreq,
    MaterialState,
    Rack,
    RackSlot,
    RackSlotStatus,
    RackStoreModel,
    SensorState,
)

from .rack_status_panel_model import (
    LAMP_LABELS,
    RackPanelStatus,
    RackStatusPanelModel,
    bit_index,
    read_wstring,
)


__all__ = [
    "RackStoreWindowV2",
    "RackStoresWindowV2",
    "RackGlobalParasWindowV2",
    "RackStoreModel",
    "RackStoreStatusModel",
    "RackStatusPanelModel",
    "RackPanelStatus",
    "LAMP_LABELS",
    "bit_index",
    "read_wstring",
    "RackSlotStatus",
    "RackSlot",
    "Rack",
    "MaterialState",
    "LightColor",
    "LightFreq",
    "CylinderState",
    "SensorState",
    "status_delta",
    "status_fields",
    "visual_key",
    "copy_status",
    "empty_status",
]
