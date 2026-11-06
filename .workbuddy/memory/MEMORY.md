# RackConfigV2 项目约定
- GUI 框架：PySide6（已从 PyQt6 全量迁移），信号用 Signal/Slot/Property，禁用 pyqtSignal
- .ui 加载走 uic_compat.loadUi（QUiLoader 兼容层），不要直接改回 PyQt 的 uic
- 料仓场景图元按名字识别，见 myDesigner/rack_store_model.py 模块头注释的命名树
- 每个仓位只有一个 rect 型「灯带」本体，没有分色图层；颜色=改填充/边框色，闪烁=定时器切可见性
- 场景大量图元，禁止在 addItem/setParent/completed 等热路径里直接 print，用 debug_log + 环境变量 RACK_DEBUG_SCENE=1 控制
- 料仓分两层：rack_store_model.py 是图元层（读写 QGraphicsScene 对象），rack_stores_status_model.py 是状态层（纯数据，可脱离场景单独存在）。状态层是唯一真值，图形层只做显示
- 隐藏仓位组（group.set_visibility(False)）会递归清掉子图元的可见标志，隐藏后读不回来状态；需要在重新显示时重灌一次状态
- 每个区域「实料」只有一层，FULL_1/FULL_2 视觉等价；从图元反读状态要用 visual_key 判等，否则会把 FULL_2 降级成 FULL_1
- text_element.context 的 setter 会强制前后加空格（渲染留白），比较文本前必须 strip
- text_element 的长度方向是局部 y（paint 里故意把 w/h 换过来画，配合 is_use_for_agv_map 的 90° 映射，不要当成 bug）。改内容时靠 anchor_left_edge 钉住左侧，开关是 keep_left_on_context_change
- 判断料位状态不要用 bool(state)：MaterialState.EMPTY 是枚举成员，恒为真
- RackSlot.set_material 支持两种 calling 方式：传层名（'A库空筒'/'A库实料'）+ bool 表示显示/隐藏该层；传区域（'A'/'单库'）+ MaterialState 表示切换到该状态。改之前先确认调用方用的是哪种
- 「料仓状态」面板（data2.json id=1584）走独立模型 rack_status_panel_model.py：2 个 IO 模块 × 8 通道 × A/B 两盏灯 = 32 盏 + 4 个文本；DB12 位序默认 channel_major，与 ui/rack_config_v2.ui 的 16 个指示灯按钮一致
- IO 指示灯设计态全填绿色，绑定后要 set_all_off() 或等第一帧 DB12，否则 status() 会报 16/16 亮
- 跑脚本必须用项目 .venv（`.venv/Scripts/python.exe`），PySide6 只装在这里；托管 python 3.13 和系统 python 都 import 不到
- 场景重载（load_element_info2）后调 RackStoresWindow.refresh_models()，两套模型的图元引用会一起失效
- group.m_children / m_children_ids 都是 set，子图元顺序**不保存**；data2.json 的 children_ids 是哈希序（不是 1..8）。要顺序必须显式排序
- 组内图元搬家用 change_position(目标场景左上角)，setPos() 在 is_in_group() 时直接 return，搬不动
- 料架仓位几何现状：仓位1 在屏幕最上、8 在最下（y 3479.7 → -2207.0，间距 812.385）；zValue 1=146 → 8=153
- 仓位排列方向 rack_arrangements（DB7 offset 26/28/…/44，0 正序 / 1 反序）在 RackStoresWindow 里落地：只换格子的几何位置，仓位号/名字/PLC 映射不变，靠 _rack_reversed 保证幂等
- 打包（PyInstaller）必须带 `myDesigner/data2.json`（1.3 MB 场景）；漏了程序能起但画面全空。get_json_path 的查找顺序：exe 同目录 → _MEIPASS → _MEIPASS/myDesigner → cwd
- hook-snap7.py 里 os.add_dll_directory 只能传**目录**，且要判存在；传 dll 文件路径会 FileNotFoundError 直接把 exe 顶死在启动阶段
- 场景为空是合法状态（源码里 data2.json 可能还没生成），所有 handle_* 入口都要对 `rack()`/图元返回 None 做兜底，别链式调用

# 设计器 widget 图元（嵌入式 QWidget）
- 承载方式：`Designer/Core/embedded_widget_layer.py` 的 `EmbeddedWidgetLayer` = 每个控件一个透明 `QGraphicsView` + `QGraphicsProxyWidget`；不再直接 `QWidget(scene)` 当宿主
- 缩放交 `view.setTransform(scale)`、旋转交 `proxy.setRotation(-angle)`（与 `painter.rotate(-angle)` 同向），文字随缩放矢量放大
- **承载 view 必须 `StrongFocus`**（view + viewport 都要）。设成 `NoFocus` 时点击只给 proxy 一个"逻辑焦点"（`widget.hasFocus()` 为 True），系统焦点仍留在主场景，`QGraphicsView::keyPressEvent` 收不到按键 → 点得进去但打不了字，英文同样不行
- `addWidget` 前**不能**先 `setParent`（哪怕 parent 是 viewport），否则 proxy 静默接管失败、控件退化成普通子窗口 → 不旋转
- `set_widget_factory` 要的是可调用对象 `factory(host) -> QWidget`，不是控件实例；传实例会在重建时报 `TypeError: 'xxx' object is not callable`。延迟创建用闭包/lambda
- `set_scene_mode(Run)` 在 `load_element_info_run_mode()` **之前**调用时（`RackStoresWindow` 就是这样），切换那一刻场景还是空的，加载完必须补一次 `_sync_embedded_widgets(True)`，否则承载层永远不创建，运行态连占位框都不画 → 看起来"控件没加载出来"。已在 `load_element_info_run_mode` 末尾补
- **控件上的左键语义**：承载视图把鼠标事件全接走了，场景原本"左键拖动平移"在控件上就失效。`EmbeddedWidgetLayer` 用延迟派发解决：press 先扣住 → 移动超过 `startDragDistance` 判为拖动画布（改 `scene.offset` + `update_coordinate` + `_sync_embedded_widgets_geometry`）→ 没超阈值则在 release 时补发 press/release 给 viewport（照常点击/取焦）。两次快速点击还会补一个 `MouseButtonDblClick`，否则双击在控件里失效。滚轮不拦（冒泡给场景缩放）
  - **例外：有「按住」语义的控件必须立刻直通**（`PRESS_THROUGH_TYPES` = 按钮/输入框/表格/滑块/下拉/文本区，外加带 `_clickable` 的自绘灯）。否则按住期间控件收不到 press，点动按钮会在松手那一帧才连发 `pressed`+`released`，业务侧表现为「按下即抬起」。命中页面根/卡片空白仍走延迟派发，画布照常能拖。嵌套承载（页面自己就是一个 `QGraphicsView`，如 PopPick 的 `ScrollBody`）靠把 `QGraphicsView` 放进 `PRESS_THROUGH_TYPES` 放行；**宿主 `is_pan_enabled()` 为 False 时整个延迟派发直接跳过**（平移禁用后它只剩副作用）。回归 `tools/verify_press_through.py` + `tools/verify_hmi_press.py`
- 控件必须先 `setMinimumSize(1,1)`（给 0,0 无效），否则 `proxy.resize` 被 minimumSizeHint 卡住（QPushButton 宽 80），包围盒偏大、控件被裁。**只对被承载的顶层 widget 这么做**（`EmbeddedWidgetLayer.set_widget` 自己也会再设一遍）；给内部每个子控件都设会让 QGridLayout 认为一行可压到 1px，密集页面文字直接叠成一条线。子控件要显式给合理的最小高度（按钮 28 / 数值行 22 / 写入行 30）
- 尺寸用 `proxy.resize(w,h)` 驱动，不要 `widget.setFixedSize`（fix 之后 proxy 的 boundingRect 不跟手）
- 几何：中心 = `pos_viewToWindow(sceneToView(get_scene_center_pos()))`，尺寸 = `scene_size.height/width × grid/units`（AGV 下 w/h 是交换的），view 的 geometry = 旋转后包围盒 × scale
- 承载层惰性创建：设计模式不建（只画占位框），切 Run 时 `_sync_embedded_widgets(True)` 建并显示；`Delete()` 里显式 `_release_widget()`
- 视图之间按 zValue 用 `raise_()` 排序（`_restack_embedded_widgets`）；场景自绘内容永远在这些视图下面
- **性能铁律**：代理控件里改一个标签 = 重画整页，且父窗口一脏同区域所有承载视图一起重画。所以（1）别让每个页面各挂 1s 定时器（7 页 = 7 次整页重绘/秒，事件循环直接降到 2 轮/秒）；（2）PLC 点要合流后统一灌控件，别逐点直刷；（3）非活跃卡用 `set_motion_cache(True)` 烘焙位图，切前台再关掉——换完快照必须补 `scene._sync_embedded_widgets_geometry()`，否则交换后视图停原地、画面还是旧页。测量脚本 `tools/profile_hmi.py`
- 回归脚本：`tools/verify_embedded_widget.py`（21 项，含旋转/缩放/自定义工厂/删除回收）、`tools/overlay_widget_probe.py`（独立验证台）
- 注意：用 `DesignWindow` 写冒烟脚本会在关闭时把 page_*.json 全部重写（多出测试图元），跑完必须 `git checkout` 还原

# App_LogPlot / log_plot_main.py（PySide6 日志绘图工具）
- 统一入口 `main.py`：工具在 `TOOLS` 注册 `factory(enable_plc, plc_ip) -> QMainWindow`，**点击时才 import**（绘图模块会拉 matplotlib 的 Qt 后端，必须等 QApplication 建好）；`QT_API=pyside6` 在任何 Qt/matplotlib 导入前用 `os.environ.setdefault` 钉死。选择页卡片布局是两列 `QGridLayout`，加工具不要改回单行 `QHBoxLayout`
- `log_plot_main.py` 里 `App_LogPlot.app.*` 的导入只能在 `MainWidget.__init__`（模块顶层导入会让 matplotlib 抢先造 QApplication 单例）
- 主副轴合并图：`PlotMatrixWithVice`（继承 `PlotMatrix`）建 `MplPlotWidget(ax_vice_en=True)`；曲线归属靠 `MplPlotWidget.lines_on_vice`（与 `lines` 等长，`plot`/`del_line`/`clear` 必须同步维护），`_auto_scale_to_fit_all_curves` 按同轴分组，副轴窗口的图例要显式传 `self.lines` 当 handles，否则 `ax.legend()` 看不到 twinx 曲线
- 「主」「副」按钮通过 `global_config.set_axis_visible()` → `axis_visibility_change` 信号广播，别只改 bool（不会有界面反应）
- 回归固定跑 `.venv/Scripts/python.exe tools/verify_log_plot_pyside6.py`（离屏 19 项）。离屏下 `menuBar().actions()` 的 QAction wrapper 要和 QMenu 一起持有引用，否则 Python GC 会把 C++ QMenu 删掉，读 `actions()` 报 `RuntimeError: already deleted`


# 图元几何约定
- `change_size` 的缩放锚点：无父图元 = 旋转中心（`m_origin`，不再被覆盖成新中心，保证基点在场景中的位置不变）；有父图元 = 左上角（组内子图元旧语义）。辅助函数 `_resize_anchor_local` / `_axis_scale` / `_scale_about` 在 `elements.py` 顶部
- 回归：`tools/verify_resize_anchor.py`（23 项，离屏）覆盖 rect/circle/text/triangle + 组内外语义
- 图元尺寸 ↔ 控件像素：`widget_element.fit_widget_size(w,h)`（也收 QWidget/QSize/QSizeF/(w,h)）走 `_scene_size_from_view` + `change_size`，改完 `widget.size()` 正好等于传入尺寸；反向自检用 `widget_pixel_size()`。AGV 90° 下控件宽对应场景高（750×1000 控件 = 1000×750 场景）
- PopPick 页面卡片尺寸由页面控件反推：`App_PopPick/hmi/binding.py` 的 `PAGE_PIXEL_SIZE=1000×750` + `HmiPagesHost._fit_card()`（挂载后 `fit_widget_size`）；`page_size=None` 关闭。**卡片 m_origin 是扇形支点，改尺寸后必须把场景中心推回去**，否则 PageDeck 扇形错位

# App_PopPick HMI 7 页（OPC UA 页面控件）
- 画布固定 **750×1000、1:1 不缩放**：`widgets.PAGE_SIZE` / `HEADER_HEIGHT=52` / `BODY_SIZE=750×948`；容器是 `ScrollBody(design=BODY_SIZE)`（QGraphicsView + ProxyWidget），`_refit()` 把 `fitInView` 得到的 scale 钉回 1.0。**装不下就改布局，不许缩放/滚动**，用 `body.overflow()` 量（负数=装得下）
- `binding.PAGE_PIXEL_SIZE` 必须是 `QSize(750, 1000)`（页面设计尺寸）。给 1000×750 会被 fitInView 缩到 0.79 整页发虚。AGV 90° 下 750×1000 控件 = 场景 1000×750 矩形（场景 4:1 单位）
- **`QSizePolicy.Ignored` + `setMinimumWidth` 会让同行控件重叠**：Ignored 让布局项 `sizeHint()` 恒为 0 → 按 0 宽排位 → `setGeometry` 被最小宽度 clamp → 尺寸变大位置没变。要"文字不撑宽"就覆写 `minimumSizeHint()=minimumWidth()`，sizePolicy 用 `Preferred`
- 卡片挂在 `QGraphicsProxyWidget` 里，`page.findChildren(Card)` 找不到（父子链到代理项就断），要用 `self.body.content.findChildren(...)`
- `QGridLayout.setRowStretch(行数之外的行, 1)` 在 Qt6 里**无效**，卡片底部留白要真的塞 `QSpacerItem(0,0,Minimum,Expanding)`
- `HmiPage`：`card(title, weight)` 竖直权重按"每段需要的高度"分配；`row(*w, weight)` 并排；`strip(widgets)` 单排；`block(widgets, columns)` 多行固定列数（灯阵 6/5 列对齐）
- 字号一律 `_pixel_font(w, px)`，**不能靠 QSS**：页面根 `QWidget { font-size }` 是类型选择器，会盖掉子控件的 `setStyleSheet("font-size")`
- `DataTable` 行高 `Stretch` 铺满；行高不合适调卡片权重，`setMaximumSectionSize` 只在 Interactive/Fixed 下生效
- 回归：`.venv/Scripts/python.exe tools/verify_hmi_layout.py --shot build/hmi_layout`（7 页 1:1、无重叠、无滚动条）；场景挂载 `tools/preview_hmi_pages.py --attach`
- 改 `pages.py`（CRLF）禁用 `read_text().replace("\n","\r\n")` 写法，会写坏成 `\r\r\n`；用 `open(..., newline="")`

# 打包（工具集.spec / PyInstaller 6）
- **必须用本项目 .venv 打包**：`.venv/Scripts/python.exe -m PyInstaller 工具集.spec --noconfirm`。PyInstaller 收集模块用的是**它自己所在解释器**的 site-packages，spec 里的 `pathex` 管不着；用 `D:/rack/rack_config/.venv` 的 pyinstaller 打包过，那边没装 asyncua，`hiddenimports` 静默失败只在 warn 里留一行，产物照出、打开才报错
- spec 里已加**前置自检**（find_spec 检查 PySide6/asyncua/aiosqlite/sortedcontainers/pytz/dateutil/cryptography/snap7/matplotlib/PIL），缺包直接 SystemExit 并打印解释器路径，别再删掉
- `asyncua` 要 `collect_submodules`（112 个子模块），只写顶层包名会漏 `asyncua.client.*` / `asyncua.ua`
- 数据文件三套：`res` → `res`；`App_LogPlot/app/plot_moudle/{cfg,data,ui,ico,templates}` → **根目录**（resource_manager 把 `_MEIPASS` 当根）；`App_PopPick/hmi/data` → **保持原相对路径**（tag_catalog 用 `Path(__file__).parent/"data"`）
- COLLECT 会 rmtree 旧 `dist/工具集`；被安全策略拦下时先 `mv` 走再跑，Analysis 有缓存，二次跑只要 1 分钟
- 冒烟：`cd dist/工具集 && QT_QPA_PLATFORM=offscreen timeout 25 ./工具集.exe --app PopPick --no-plc`，exit=124 表示窗口活着没崩

# packTool.py（生成 spec 的 GUI 工具）
- **`工具集.spec` 是 packTool 生成的**：点「保存 Spec 文件」会覆盖人工修改，修 spec 必须同步修工具。配置在 `~/.python_packager_spec_config.json`
- 打包命令必须 `[UI 里指定的 python.exe, '-m', 'PyInstaller', ...]`，**别再用 `shutil.which('pyinstaller')` 优先**；PATH 指到别的 venv 会静默缺库
- 打包返回码 0 不代表成功：要扫 `build/<spec名>/warn-*.txt` 的 `missing module named`，声明过的隐藏导入缺失必须判失败
- 隐藏导入要生成 `collect_submodules`（UI 开关默认开）；依赖自检要在**打包用的解释器**里跑 `find_spec`，GUI 自己的解释器不算
- 资源必须有「包内目标目录」：`resource_manager` 同级目录（plot_moudle 的 ui/cfg/ico/data）要**摊平**，`Path(__file__).parent/'data'` 类（App_PopPick/hmi/data）要**保持层级**；扫描器检测到同级 `resource_manager.py` 会自动建议摊平
- 回归：`.venv/Scripts/python.exe tools/verify_pack_tool.py`（离屏 19 项）
- **冒烟别跑 `--app Designer`**：DesignWindow 关窗会重写 `Designer/Core/data.json/datas/design/pages/page_*.json` 和 `project.json`（含离线 offscreen 冒烟），跑完必须 `git checkout` 还原
