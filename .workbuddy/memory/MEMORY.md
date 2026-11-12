# 通用约定
- PySide6；`.ui` 走 `uic_compat.loadUi`；脚本/回归/打包一律 `.venv/Scripts/python.exe`（打包用本项目 venv，`工具集.spec`/`packTool.py` 同步，返回码 0 也扫 warn）
- 新代码从 `Designer/CoreQGraphics/runtime/RuntimeStage` 起手，别再复制 `base_element`；运行态对页面 `_page` **零污染**
- 料仓真值：`rack_store_model`+`rack_stores_status_model`；重载后 `refresh_models()`；判料位别用 `bool(state)`

# CoreQGraphics（编辑器）
入口 `python -m Designer.CoreQGraphics.ui [page.json]`；复用 `Core/property_widgets.py`
- **硬约束**：page_1 逐图元 0/1618、JSON round-trip 零改动；门禁 `verify_core_qgraphics*.py` / `verify_core_qgraphics_incremental.py`
- 脏标记 `_dirty`/`_geo_dirty`；只写 `_page`；关窗 `is_modified()`
- **平铺层级**：`parent_id/children_ids`+SceneIndex，**不用 setParentItem**；`translate_locked()` 只锁平移；删组递归删后代
- **支点** `scene(q)=pos+o+R(q-o)`；**平移用 `pos()` 不用 `scenePos()`**（自定义支点恒差 `o-R·o`）；中心标识只画红点
- 顶点类旋转烘焙进顶点，`page_angle()=_baked_angle-rotation()`，`closeSubpath()` elementCount 多 1
- 网格步长 2 的幂（屏幕 18~90px）；`aim(always=True)` 退格点；唯一**红十字**（描深色底），T 一次性开门控并对齐
- 捕捉点取真实顶点：`frame_corners()`=包围盒四角（拖角专用）；线/三角/多边形/路径走 `_PointBasedItem.snap_points()`；非绘制态排除选中项自身点，**绘制态只排临时图元自身点**
- `_selection_own_points()` **必须缓存**（全选 1.4 万点、逐帧 60ms）；按选中 id 缓存，`geometryChanged`/`refresh` 失效；绘制落点/预览/红十字共用 `_draw_page_point` 的同一份 `aim`
- **交互**：左键不拖图元（含 CTRL）；移动只走双击=跟手（增量、单击落定、Esc 回原位、抓根父）；右键自接管；CAD 分点落子
- 缩放走 `_zoom_at()`（NoAnchor+补滚动条），别依赖 `AnchorUnderMouse`；导航门控只拦中键/空格/滚轮，左键永不参与
- 递归复制/组缩放 `_capture_subtree`/`_instantiate` 深拷贝重发 id，组 `F(p)=A+(p-A)·(sx,sy)`；成组 prepend `<组名>_`、解组剥一层
- **复制偏移口径**：`duplicate_selected`/`paste_clipboard` 的 offset 是**视图坐标**（旧 Core `item.pos()+paste_offset` 口径），经 `SceneProjection.inverse_delta()` 反投影成 page 增量再逐点写几何；`_instantiate`/`instantiate_template` 仍吃 page 增量，别改。text 圆角与 RectItem 同口径：`rx=radius*ky`、`ry=radius*kx` 夹半边，`strokeWidth=0` 用 `NoPen+brush+drawRoundedRect` 填底，radius=0 逐像素不变
- 文本双向：`style.font_size` 真值；改字号→改框；改框→`_fit_font_size()` 二分；加载/撤销不重算
- widget 9 类（旧 7 + `progressbar`/`slider`）、5 顶层字段；`QFont()` 同族、**别按框高缩**；proxy 独立顶层不进索引：`resize`+`setTransformOriginPoint(中心)`+`setPos(mapToScene(0,0)-半尺寸)`，别 setGeometry 再 setPos
- **增量刷新**：`structureChanged`/`itemChanged(ids)` 细信号（`contentChanged` 照常发）；写操作走 `emit_structure_changed()`/`emit_items_changed(ids)`，空 ids=页面级。吸附表 `_by_owner`+`_entry_owners` 引用计数、`update_owner()` 增量，未建/标脏回退全量；图层树 `update_items(ids)` 按行更新、异常退化全量、`_bound` 记录实际连接再解绑。`_after_edit()` 只剩 `history.commit()`（~43ms 瓶颈，P0-1 未做）。验证几何变化**必须用 `moveBy`**（`set_page_center` 对带父项被拒 → 假绿）
- **进度条 / 滑动条**：`widgetText` 里 `min=/max=/value=/orientation=` 是唯一配置真值（`widget_range_config`，缺省 0/100/中值/横向），别加第 6 个顶层字段；`widget_style_sheet` 必须补 `QProgressBar::chunk` / `QSlider` groove+handle，否则主题可能把填充/滑块画没；设计态竖向从下往上，百分比文字按填充/未填充分段着色，别直接 clip 裁半边。旧 Core 未知变体安全退化 `QTextEdit`
- **布尔/精确路径**：rect/circle/triangle/polygon/path 在场景坐标做并交差，异或=并集−交集；空结果原子失败且不占 ID，结果继承首图元样式并一步撤销。`path_segments+path_fill_rule` 保留曲线/孔洞/多子路径，`vertices` 给旧 Core 兜底；所有几何/模板变换必须同步 c1/c2。非对称路径加载优先 `center_pos`，清 rotation 前 `_account_bake()`，`page_size()` 先反旋再测。单图元和组均可存 `toolbox_templates.json`；专项门禁 `verify_core_qgraphics_boolean.py`
- **图元锁定** `locked` 是可选顶层字段（缺省 False、**解锁直接删键**，别写成 false，否则脏 round-trip）；`is_locked()` 别和 `translate_locked()`（父子平移锁）混。拦截**只在交互层**（`pose_blocked()`/`editable_pose()` 含后代检查，组整体保护），绝不动 `set_page_center`/`moveBy`（组联动、撤销、运行态零污染都要用）。标记画在 `g_view.drawForeground` 视口像素层（`sceneBoundingRect().bottomLeft()`+(7,-7)，外6/内3/点1.1），运行态不画；Ctrl+L / Ctrl+Shift+U；属性面板用 `_pose_widgets` 快照同步置灰，别在 toggled 里重建面板
- **贝塞尔图元** `bezier` 继承 `PathItem`，真值是 `path_segments` 的 `move+curve`（含 c1/c2），`vertices` 只作旧 Core 折线兜底；四击落子 P0/C1/C2/P3、开放不填充、不参与布尔、选中画控制点手柄。`map_path`/`shift_segments` 已保证所有变换同步 c1/c2，**别改回折线化**；`set_page_vertices` 覆写成重建 cubicTo

# 适配层硬规则（rack / safety 共用）
- 几何一律 page 坐标；`change_position(pos)` 对齐左上角：`delta=pos-tl` 后 `setPos(item.pos()+proj.delta(delta))`；线图元 head/end ≠ bbox 角
- `getSize()` 用 `_proj.inverse_size(_w_view,_h_view)`（不是旋转后 AABB 的 page_bounding）；四角是解析式 `中心+R(θ)·(±w/2,±h/2)`，rack 口径例外用 AABB
- **旧 sceneRect 固定 ±100000**，必须照抄，否则 `centerOn(0,0)` 被夹→整幅偏移
- 命中测试 `event.position()` 是视口坐标要转场景坐标；`isinstance` 对壳失效用 `_is_group_like`/`_is_element_like` 兜底；组隐藏不传子项（`_self_visible`/`_eff_visible`，隐藏前快照）
- 旧「场景即 QWidget」拆 Scene+View，入口 `self.scene` 指向 View；View 补 `get_bg_color`/`grid_size`/`scale_factor`/`is_use_for_agv_map`；背景 alpha 按 `QPalette.Base` 合成→Base 设成 Window
- `safety_scene_adapter`：`SafetyScene`+`SafetySceneView`，`SceneManager` 复刻 `m_items`/`m_name_items`/`m_sorted_items`/`findItem`；`run_mode_station_change = Signal(object)` 双形态载荷别改 `Signal(int)`；559 图元对拍零差异（`verify_safety_car_v2.py`）
- **resize 钉左上角**：QGraphicsView 默认保持视口中心场景点，底部 dock 展开画面上移半高差；`resizeEvent` 里 `anchor=mapToScene(0,0)` → `super()` → `_pin_top_left(anchor)`（零漂移）

# 统一运行态框架 `Designer/CoreQGraphics/runtime/`
`RuntimeStage`/`RuntimeScene`/`RuntimeView`/`RuntimeRegistry`+`RuntimeElement`/`WidgetHost`+`ControlProvider`/`TagBus`；文档 `docs/unified_runtime_template_design.md`，门禁 `tools/verify_unified_runtime.py`，样例 `tools/demo_unified_runtime.py`；**核心 g_*.py 零改动**
- 三个显式口径：`widget_mode=host|builtin|none`（host 自建 proxy，**不调** `set_scene_mode(True)`）、`fit_mode=fit|pin|none`、`geometry_profile=strict|rack|safety`（选错差上百 page 单位）
- `RuntimeElement` 只记 `item_id`、`item()` 现查，跨换页复用门面，消失 id 标 detached；可见性只写 `item.setVisible()`；`WidgetHost.reset()` 必须在 `scene.load_page()` 前
- proxy 独立顶层 + `resize` + `setTransformOriginPoint(w/2,h/2)` + `pos=mapToScene(0,0)-半尺寸` + `z+0.5`；回收 `setWidget(None)`→hide→setParent(None)→deleteLater
- `QSizePolicy.Fixed` 控件会把 `WidgetHost.align()` 的 `proxy.resize()` 顶回去 → 必须在 provider `create()` 里读 `element.item().boundingRect()` 反推尺寸并 `setFixedSize(图元框取整)`（参考 `FlipNumberDisplay.fit_to_size()`），别改框架
- `WidgetHost.set_factory` **只登记不建控件**；逐张 `set_widget_factory` 后必须自己补 `stage.widgets.rebuild()`，否则 proxy=0 全白；`stage.set_mapping()` 必须在 `load()` 前
- 旧 API 门面 `stage.scene_manager`（rack 口径）/`stage.pages_manager`（PopPick 只 widget 卡片）；未覆盖：位图快照缓存、PageDeck 动画精确标脏、snap7、活跃页订阅、safety 双形态信号代理
- `sceneRect=0` 取景回退分支直接用 `fit_rect()`（已是视图坐标），只有 header 的 sceneRect（page 坐标）才 `projection.rect()`；二次投影画面全空
- **运行态零污染改图元**：改色写 `item._style`+`update()`；位移 `change_position()` 后把父+后代 `_page` 从快照还原 +`mark_clean()`+清 `scene._modified`（判位置用 `item().sceneBoundingRect()`）；text 只写 `item.context`+`update()`（`to_page_record()` 只深拷 `_page`），别用 `RuntimeElement.context` setter
- **AGV 投影轴交换**默认 `(0.25,0.25,True,0,0)`：page 的 y 位移在视图里是 x 位移；图元给控件的尺寸 = projection 后 scene 尺寸，不是 page 宽高
- widget 图元挂整页控件（`servo_panel.py`）：`signature()` 固定，业务用 `controlCreated`/`controlDestroyed` 接信号清引用；`FixtureRuntime(panel_provider=...)` 可换任意 QWidget 或外部 C++ 窗口（`QWindow.fromWinId`+`createWindowContainer`）

# 落地项目
- `App_test_fixture/`（2026-11-10）：`python -m App_test_fixture.fixture_app --source demo|none|modbus`，门禁 `tools/verify_test_fixture.py`；`DataSource` 抽象默认 Demo
- `App_PopPick_V2/`（2026-11-12）：删旧 `qgraphics_runtime.py`，改 `RuntimeStage` 装配（`PopPickRuntime` = stage + `page_snapshots.PageSnapshots` + `HmiPagesHost`），框架零改动，位图顶替落业务侧
  - 卡片 `getSize()` 是 page 单位 4000×3000；AGV k=0.25+轴交换下正好 750×1000 像素，`fit_widget_size` 恒等；`fit_mode="none"`（取景由窗口驱动）否则 resize 抖动
  - 位图三本账 `_animating`/`_static`/`_items`，`_showing()` 唯一真值，动画窗口内不改 `_static`；`follow()` 只抄 proxy 位姿，调用点 deck `_apply_pose`/`_lift_top`/`_restack`
  - 门禁 `tools/verify_pop_pick_v2.py`，与旧适配层几何对拍 0.000000（背景除外，它是运行态动态图元）
  - **背景撑满视口**（`background_fitter.py`）：`BackgroundElement.change_pos/change_size` 分别委托 `element.change_position`（左上角）/ `fit_widget_size`（先用 `proj.size()` 把 page 宽高换成视图像素）；目标 = `proj.inverse_rect(view.mapToScene(viewport.rect()).boundingRect())` 外扩 2%。零污染口径同 `CleanVisuals`：capture `_page` 快照 → 改几何 → 还原 + `mark_clean()` + 清 `scene._modified`；**装载期不 sync**（否则与旧适配层对拍失败）。触发三重：包装 `on_viewport_resized`、滚动条信号 + viewport 事件过滤、50ms 轮询视图变换签名（兜住静默 `scale()`/`fitInView()`）。`_fit_view` 必须排除背景（否则自激缩小）；`PageSnapshots._cards()` 也必须排除（尺寸随视口变 + 逐帧动画，位图会冻住）
  - **背景水墨交互**（`ink_pond_widget.py`）：`_fish_pose(f,t)` 是位姿唯一真值，绘制/命中/查询共用（鱼逃开后可点区跟着走），无逃窜时与旧公式 0 误差 → 默认帧逐像素不变。逃窜是时间纯函数：`Fish` 只存 `flee_at/dx/dy/power`，`(1-e^{-age/0.12})·(1-age/2.8)^1.7` 峰值约 170 单位、2.8s 归位；朝向最短弧插值 + 急摆尾。命中走 `_scale_info()` 逆变换到 1200×800 再进「单位鱼」局部坐标，`startle_at()` 唯一入口（主鱼 power=1、同伴按距离衰减并延迟、点击水纹）。运行态点击能穿透只读卡片到 z=-1 背景 proxy；**没改 `pop_pick_entry.py`**，点卡片换页语义不动。门禁 `tools/verify_ink_pond_interaction.py` 93/93
  - **水波 / 青蛙**：`_wave_ring` 是唯一水环画法（椭圆压扁 + 谐波扰动），氛围/点击/青蛙/露珠共用；青蛙与露珠涟漪由 `_frog_wave_events(t)` 按 t 解析枚举、零状态；青蛙 `_frog_pose(t)` 用 7s 周期 8 段比例表，朝向取瞬时速度且纵向压平 ×0.28（否则画成竖墨条），呼吸项必须 `sin(2π·3u)` 才随周期复现；画蛙腿用粗圆笔、别用细线（会像蝌蚪）
- 面板字段表 `fixture_config.AXIS_*_FIELDS` → `PanelSpec.from_config()` → `ServoAxisPanel.__init__` 三处解包须同形（3 元组）；改配置漏改构造会在装载期 `ValueError` 被包成「场景载入失败」。带确认点动按钮确认后发 `True→False` 脉冲，普通点动按住 True/松开 False
- 离屏渲染 `QT_QPA_PLATFORM=offscreen` 中文变 □ → `fixture_app.ensure_cjk_fonts()` 只在字体库为空时手动加载 `msyh.ttc`/`simhei.ttf`

# Modbus / 现场协议（`App_test_fixture/modbus_link.py`）
- 底层 pymodbus 是 **0-based 协议地址**，40001 → 0；`MODBUS_ADDRESS_MODE="4xxxx"|"raw"`、`MODBUS_START` 一处平移；映射表相对 `offset`（字）+`type/scale/access/bit`，单点改写 `MODBUS_REGISTER_OVERRIDES`；读按跨度一次批量读；填 `MODBUS_IP` 或 `--ip` 才连设备
- `'f'`=2 字、`'d'`=4 字（`width()` 跟着 type 走、offset 步长按 4）；encode/decode 严格互逆、统一 `>` 网络序。**别用** `common/com/modbus.set_double/set_float`（字节序反）
- PLC 实测 `12.5` LREAL=`[0,0,0,0x4029]`：低字在前但字内字节仍大端 → `MODBUS_FLOAT_WORD_ORDER="little"`，`_ordered_words()` 做**整体字列表反序**（不是两两交换，double64 会解错）；`uint32/int32` 也吃此开关，单点可 `word_order="big"` 覆盖
- `byte` 类型=BOOL 按字节打包：一字放两个 BOOL，`byte=0` 用 bit0(0x0001)、`byte=1` 用 bit8(0x0100)；写入统一「算掩码→读一字→位或/位与→`&0xFFFF`」幂等读-改-写。**别用 `+=/-=`**（进位污染、False 出负数）；调试 print 走 `DEBUG_WRITE=False`
- `PLCManager` 心跳每 500ms 写寄存器 1000，映射表占 1000 会被周期覆盖（`heartbeat_conflicts()` 会警告）→ 关掉 PLCManager 最省事；`overlap_conflicts(map)` 把「同地址多个 `byte` 且 byte 互异」视为合法打包，其余重叠警告
- 门禁不绑现场布局：`verify_test_fixture.py` 7b 组用固定 spec+独立紧凑 `test_map`，`rmap` 只查 ⊆ known_keys；面板数量按 `AXIS_*_FIELDS` 动态算；图元数量按 `len(disk_json()["items"])`
- **点位名 ≠ 图元名**：`values` key 是 `cfg.TAG[...]`，`element_of()` 按 JSON `name` 查（写错静默返回 None）；新增显示图元加 `fixture_config.TEXT_BINDINGS` 一行+映射表一行，`_check_text_bindings()` load 期 warn
