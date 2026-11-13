# 通用约定
- PySide6；`.ui` 走 `uic_compat.loadUi`；脚本/门禁/打包用 `.venv/Scripts/python.exe`（打包同步 `工具集.spec`/`packTool.py`，返回码 0 也扫 warn）
- 新运行态代码从 `Designer/CoreQGraphics/runtime/RuntimeStage` 起手，别复制 `base_element`；运行态对 `_page` **零污染**
- 料仓真值 `rack_store_model`+`rack_stores_status_model`，重载后 `refresh_models()`，判料位别用 `bool(state)`

# CoreQGraphics（编辑器）
入口 `python -m Designer.CoreQGraphics.ui [page.json]`，属性面板复用 `Core/property_widgets.py`
- **硬约束**：page_1 逐图元 0/1618、JSON round-trip 零改动；门禁 `tools/verify_core_qgraphics*.py`
- 脏标记 `_dirty`/`_geo_dirty`；只写 `_page`；关窗 `is_modified()`
- **模式切换**：`set_scene_mode` 只发自己的 `sceneModeChanged(bool)`（**别用** Qt 内置 `sceneRectChanged`，载荷是 QRectF，emit bool 直接 TypeError）；视图在 `setScene()` 里连/断（只在 `__init__` 连会切页断供）；网格显隐靠 `drawBackground` 判 `is_run_mode`，`show_grid`/`snap.grid_enabled` 是用户偏好不被运行态改写
- **平铺层级** `parent_id/children_ids`+SceneIndex，**不用 setParentItem**；删组递归删后代
- `translate_locked()` **仅设计态**锁子图元自身平移，运行态放行（子自己动不带动父，父之后运动仍刚体带它）；`locked` 字段只在交互层拦（`pose_blocked()`/`editable_pose()`），别动 `set_page_center`/`moveBy`
- **支点** `scene(q)=pos+o+R(q-o)`；平移用 `pos()` 不用 `scenePos()`；中心标识只画红点
- 顶点类旋转烘焙进顶点，`page_angle()=_baked_angle-rotation()`，`closeSubpath()` elementCount 多 1
- 网格步长 2 的幂（屏幕 18~90px）；`aim(always=True)` 退格点；唯一**红十字**（描深色底），T 一次性开门控并对齐
- 捕捉点取真实顶点：`frame_corners()`=包围盒四角；线/三角/多边形/路径走 `_PointBasedItem.snap_points()`；非绘制态排除选中项自身点，**绘制态只排临时图元自身点**；`_selection_own_points()` **必须缓存**（全选 1.4 万点/逐帧 60ms）
- **交互**：左键不拖图元（含 CTRL）；移动只走双击=跟手（增量、单击落定、Esc 回原位、抓根父）；右键自接管；CAD 分点落子；缩放走 `_zoom_at()`
- **框选性能**：Qt 橡皮筋画在视口画布上 → 每格整屏重绘（`drawBackground` 暴露矩形恒等于整页），每帧成本=一帧全画。选中变化只 `_refresh_selection_dirty()`→`updateScene()` 标脏「标记区」，**别再整屏 `update()`**；框选中 `is_band_selecting()` 时窗口只置 `_selection_pending`，`selectionSettled` 松手补面板/图层树（`layers.set_defer_probe`）；`TextItem.paint` 用一次 `drawText(r, AlignCenter|TextDontClip)`，**别再 boundingRect+drawText 双次排版**
- 复制/组缩放 `_capture_subtree`/`_instantiate` 深拷贝重发 id，组 `F(p)=A+(p-A)·(sx,sy)`；**复制偏移是视图坐标**，经 `SceneProjection.inverse_delta()` 反投影（`_instantiate`/`instantiate_template` 仍吃 page 增量）
- 文本双向：`style.font_size` 真值，`style.font_family` 缺省 `Arial`（旧 Core 口径，存量页不补键）；改字号/字体→改框；改框→`_fit_font_size()` 二分；`text_metrics(text, size, family)` 必须与 `paint` 同族；字体下拉候选族走 `available_font_families()`（剔除 GDI 位图字体 Terminal/Fixedsys/System/Courier 等 10 个，否则 `Qt.FontRole` 预览会刷 `DirectWrite: CreateFontFaceFromHDC() failed`）；圆角 `rx=radius*ky`/`ry=radius*kx`，`strokeWidth=0` 用 `NoPen+brush+drawRoundedRect`
- **名字整页唯一**：改名只走 `BaseItem.set_name` → `scene.rename_item`，`rename_problem()` 判空名/重名（去空白全等、区分大小写），被拒**不写字段、不产生撤销点**；组改名重名时组名与成员前缀都不动；存量重名数据加载不校验、不自动改名（只有显式改名才查），1618 对拍与 round-trip 不受影响
- widget 9 类（旧 7 + `progressbar`/`slider`）：`widgetText` 里 `min=/max=/value=/orientation=` 是范围配置唯一真值（**别再为范围加第 7 个顶层字段**）；顶层字段现为 **6 个**（用户已加 `widgetFontFamily`，空串=跟随应用默认字体，存量页不补键），主门禁断言同步为 6 字段；`widget_style_sheet` 必须补 `QProgressBar::chunk`/`QSlider` groove+handle；proxy 独立顶层不进索引；`QSizePolicy.Fixed` 控件须在 provider `create()` 里 `setFixedSize(图元框)`
- **增量刷新**：`structureChanged`/`itemChanged(ids)`；写操作走 `emit_structure_changed()`/`emit_items_changed(ids)`；`_after_edit()` 只剩 `history.commit()`（~43ms，P0-1 未做）；验证几何变化**必须用 `moveBy`**（设计态 `set_page_center` 对带父项被拒→假绿）
- **布尔** rect/circle/triangle/polygon/path 场景坐标并交差，空结果原子失败不占 ID；`path_segments+path_fill_rule` 保留曲线/孔洞；所有变换必须同步 c1/c2；单图元与组均可存 `toolbox_templates.json`，门禁 `verify_core_qgraphics_boolean.py`
- **贝塞尔** `bezier` 继承 `PathItem`，真值 `path_segments` 的 move+curve；四击落子、开放不填充、不参与布尔；`map_path`/`shift_segments` 已同步 c1/c2，**别改回折线化**

# 适配层（rack / safety）
- 几何一律 page 坐标；`change_position(pos)` 对齐左上角：`delta=pos-tl` → `setPos(item.pos()+proj.delta(delta))`
- `getSize()` 用 `proj.inverse_size()`；四角解析式 `中心+R(θ)·(±w/2,±h/2)`（rack 例外用 AABB）
- **旧 sceneRect 固定 ±100000** 照抄，否则 `centerOn(0,0)` 被夹→整幅偏移
- 命中测试 `event.position()` 要转场景坐标；`isinstance` 对壳失效用 `_is_group_like`/`_is_element_like`；组隐藏不传子项（`_self_visible`/`_eff_visible`）
- 旧「场景即 QWidget」拆 Scene+View，入口 `self.scene` 指向 View；补 `get_bg_color`/`grid_size`/`scale_factor`/`is_use_for_agv_map`；背景 alpha 按 `QPalette.Base` 合成
- `safety_scene_adapter`：`SceneManager` 复刻 `m_items`/`m_name_items`/`m_sorted_items`/`findItem`；`run_mode_station_change=Signal(object)` 双形态载荷别改 `Signal(int)`；559 图元对拍零差异
- **resize 钉左上角**：`resizeEvent` 里 `anchor=mapToScene(0,0)` → `super()` → `_pin_top_left(anchor)`

# 统一运行态框架 `runtime/`
`RuntimeStage`/`RuntimeScene`/`RuntimeView`/`RuntimeRegistry`+`RuntimeElement`/`WidgetHost`+`ControlProvider`/`TagBus`；文档 `docs/unified_runtime_template_design.md`，门禁 `tools/verify_unified_runtime.py`；**核心 g_*.py 零改动**
- 三个显式口径：`widget_mode=host|builtin|none`（host 自建 proxy，**不调** `set_scene_mode(True)`）、`fit_mode=fit|pin|none`、`geometry_profile=strict|rack|safety`
- `RuntimeElement` 只记 `item_id`、`item()` 现查；`WidgetHost.reset()` 必须在 `load_page()` 前；`set_factory` **只登记不建控件**，逐张 `set_widget_factory` 后补 `stage.widgets.rebuild()`；`set_mapping()` 在 `load()` 前
- proxy：独立顶层 + `resize` + `setTransformOriginPoint(w/2,h/2)` + `pos=mapToScene(0,0)-半尺寸` + `z+0.5`；回收 `setWidget(None)`→hide→setParent(None)→deleteLater
- 旧 API 门面 `stage.scene_manager`/`stage.pages_manager`；未覆盖：位图快照缓存、PageDeck 动画标脏、snap7、活跃页订阅、safety 双形态信号代理
- `sceneRect=0` 回退直接用 `fit_rect()`（已是视图坐标），只有 header 的 sceneRect 才 `projection.rect()`
- **零污染改图元**：改色写 `item._style`+`update()`；位移 `change_position()` 后还原父+后代 `_page`+`mark_clean()`+清 `scene._modified`；text 只写 `item.context`+`update()`
- **AGV 投影轴交换** `(0.25,0.25,True,0,0)`：page 的 y 位移在视图是 x 位移；控件尺寸=projection 后 scene 尺寸
- 整页控件挂 widget 图元（`servo_panel.py`）：`signature()` 固定，`controlCreated`/`controlDestroyed` 清引用；`FixtureRuntime(panel_provider=...)` 可换任意 QWidget 或外部 C++ 窗口

# 落地项目
- `App_test_fixture/`：`python -m App_test_fixture.fixture_app --source demo|none|modbus`，门禁 `tools/verify_test_fixture.py`；面板字段表 `AXIS_*_FIELDS`→`PanelSpec.from_config()`→`ServoAxisPanel.__init__` 三处解包须同形（3 元组）
- 离屏渲染中文变 □ → `fixture_app.ensure_cjk_fonts()` 手动加载 `msyh.ttc`/`simhei.ttf`
- `App_PopPick_V2/`：`PopPickRuntime` = stage + `PageSnapshots` + `HmiPagesHost`，框架零改动；门禁 `tools/verify_pop_pick_v2.py`（几何对拍 0）
  - 卡片 `getSize()` page 4000×3000；`fit_mode="none"` 否则 resize 抖动；位图三本账 `_animating`/`_static`/`_items`，`_showing()` 唯一真值
  - **背景撑满视口** `background_fitter.py`：目标 `proj.inverse_rect(视口包围盒)` 外扩 2%；零污染同 `CleanVisuals`；**装载期不 sync**；触发三重（wrap resize、滚动条+事件过滤、50ms 轮询）；`_fit_view` 与 `PageSnapshots._cards()` 必须排除背景
  - **水墨交互** `ink_pond_widget.py`：`_fish_pose(f,t)` 唯一真值（绘制/命中/查询共用）；逃窜是时间纯函数、2.8s 归位；`startle_at()` 唯一入口；门禁 `verify_ink_pond_interaction.py` 93/93
  - **水波/青蛙**：`_wave_ring` 唯一水环画法；青蛙涟漪由 `_frog_wave_events(t)` 零状态解析枚举；`_frog_pose(t)` 7s 周期 8 段，朝向取瞬时速度且纵向压平 ×0.28，呼吸项 `sin(2π·3u)`；蛙腿用粗圆笔

# Modbus（`App_test_fixture/modbus_link.py`）
- pymodbus **0-based** 协议地址（40001→0）；`MODBUS_ADDRESS_MODE`/`MODBUS_START` 一处平移；映射表相对 `offset`（字）+`type/scale/access/bit`；读按跨度一次批量读
- `'f'`=2 字、`'d'`=4 字，encode/decode 严格互逆、统一 `>` 网络序；**别用** `common/com/modbus.set_float/set_double`（字节序反）
- `MODBUS_FLOAT_WORD_ORDER="little"`：`_ordered_words()` 做**整体字列表反序**（不是两两交换，double64 会解错）；`uint32/int32` 同吃此开关，单点可 `word_order="big"` 覆盖
- `byte` 类型=BOOL 按字节打包：`byte=0`→bit0、`byte=1`→bit8；写入统一「算掩码→读一字→位或/位与→`&0xFFFF`」幂等读-改-写，**别用 `+=/-=`**；调试 `DEBUG_WRITE=False`
- `PLCManager` 心跳每 500ms 写寄存器 1000 → 映射表占 1000 会被覆盖（`heartbeat_conflicts()`）；`overlap_conflicts()` 把「同地址多个 byte 且 byte 互异」视为合法打包
- **点位名 ≠ 图元名**：`values` key 是 `cfg.TAG[...]`，`element_of()` 按 JSON `name` 查；新增显示图元加 `TEXT_BINDINGS` 一行+映射表一行
