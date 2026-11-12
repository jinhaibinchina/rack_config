"""PopPick 运行态的可调参数（唯一来源）。

参照 ``App_test_fixture/fixture_config.py`` 的分工：**本文件只放常量**，不
import 任何 Qt / 场景模块，装配逻辑一律在 :mod:`App_PopPick_V2.pop_pick_runtime`。
这样调参（窗口大小、刷新合流、快照分辨率阈值）不用动装配代码，回归脚本也能
直接读同一份值做断言。

页面文件查找顺序（``--scene`` 优先）见 :func:`App_PopPick_V2.pop_pick_entry
.resolve_page_file`；这里只记默认页 id。
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------- 窗口
APP_TITLE = "PopPick 拣选工作站"
WINDOW_SIZE = (1280, 820)

#: 设计工程里的默认页面 id。page_9 已经是 7 卡版本（Page0..Page6），
#: 与 ``hmi.pages.DEFAULT_CARDS`` 一一对应。
DEFAULT_PAGE = "page_9"
DEFAULT_PLC_IP = "192.168.1.88"

# ---------------------------------------------------------------- 页面
#: HMI 页面控件的设计像素尺寸（与 ``hmi.widgets.PAGE_SIZE`` 一致）。
#: 挂载时用它把卡片场景尺寸校正到「正好容纳这么大」，场景 JSON 里写多少
#: （当前是 4000×3000）都会被拉回同一套观感。``None`` = 不校正。
PAGE_PIXEL_SIZE = (750, 1000)

# ---------------------------------------------------------------- 背景图元
#: 页面里承载水墨控件的 widget 图元名。它不参与 PageDeck 的卡片集合，
#: 由 ``background_fitter.BackgroundFitter`` 按视口实时改位置 / 尺寸。
BACKGROUND_NAME = "背景"
#: 可见矩形外扩比例：压住亚像素 / 描边造成的 1px 露边。
BACKGROUND_OVERSCAN = 0.02
#: 视图变换轮询间隔（毫秒）。QGraphicsView 没有「变换变了」的信号，
#: 这是 ``view.scale()`` / ``fitInView()`` 这类静默变换的兜底。
BACKGROUND_POLL_MS = 50
#: 变化合并窗口（毫秒）：连续 resize / 滚轮只重算最后一次。
BACKGROUND_SYNC_MS = 16

# ---------------------------------------------------------------- 框架口径
#: ``host`` = ``RuntimeStage`` 自建 proxy（PopPick 必须走这条：整页控件
#: 由 ``set_widget_factory`` 提供，绝不能让核心按 widgetType 造 QTextEdit）。
WIDGET_MODE = "host"
#: 运行态的取景由窗口驱动（resize → 最大视图 refit），框架不要自动 fit：
#: ``fit`` 会在每次 resize 先fit 全场景、80ms 后再被最大视图盖掉，看得见抖动。
FIT_MODE = "none"
#: 卡片几何全部按「解析式四角」取，与旧 ``RuntimeCard`` 口径一致。
GEOMETRY_PROFILE = "strict"

#: HMI 数值刷新合流间隔（毫秒）。PLC 逐点推送先攒起来，每拍统一灌一次；
#: 改一个标签就要重画整页，逐点直刷的代价是「每点一次重画一页」。
FLUSH_MS = 100

# ---------------------------------------------------------------- 位图快照
#: 动画窗口内把 7 张 750×1000 页面换成位图。真实控件一旋转，
#: ``QGraphicsProxyWidget`` 就要整页重渲染（单卡 ~14ms，7 卡一帧 100ms）。
SNAPSHOT_ENABLED = True
#: 位图过期后延迟多久补烘（毫秒）。交换刚结束时用户还在看画面，同步 grab
#: 5 张会顿一下，先复用旧图、等这么久没新动作再补。
SNAPSHOT_REFRESH_MS = 180
#: 每次事件循环最多补烘几张，避免一次性 5 张 grab 造成整段顿挫。
SNAPSHOT_REFRESH_BATCH = 2
#: 视图变换稳定多久后预热位图（毫秒）。fit 之前烘出来的是 1:1 大图，白费。
SNAPSHOT_PREWARM_MS = 350
#: 已有位图的物理像素与当前显示分辨率相差超过这个比例才重烘。
SNAPSHOT_RESCALE_TOLERANCE = 0.15

# ---------------------------------------------------------------- 窗口行为
#: 窗口尺寸变化后重算最大视图取景的合并窗口（毫秒）：拖动中不重算。
MAXIMIZE_REFIT_MS = 80

# ---------------------------------------------------------------- 路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 「适应窗口」/「最大窗口」的取景边距（相对包围盒长边）。
FIT_MARGIN_RATIO = 0.04
MAXIMIZE_MARGIN_RATIO = 0.015
