# 通用约定
- PySide6；`.ui` 走 `uic_compat.loadUi`；脚本/回归/打包一律 `.venv/Scripts/python.exe`
- 打包用本项目 venv；`工具集.spec`/`packTool.py` 同步；返回码 0 也扫 warn

# 旧 Core
- 料仓：`rack_store_model`+`rack_stores_status_model` 唯一真值；重载后 `refresh_models()`；判料位别用 `bool(state)`
- PopPick HMI 750×1000 1:1；`QSizePolicy.Ignored`+setMinimumWidth 重叠→覆写 minimumSizeHint

# CoreQGraphics
入口 `python -m Designer.CoreQGraphics.ui [page.json]`；复用 `Core/property_widgets.py`
- **硬约束**：page_1 逐图元 0/1618、JSON round-trip 零改动；回归 `verify_core_qgraphics.py`/`_ui.py`+外围
- **脏标记**：`_dirty`/`_geo_dirty`；只写 `_page`；关窗 `is_modified()`
- **平铺层级**：`parent_id/children_ids`+SceneIndex，**不用 setParentItem**；`translate_locked()` 只锁平移；**删组递归删后代**
- **支点**：`scene(q)=pos+o+R(q-o)`；中心标识只画红点、无 ID；**平移用 `pos()` 不用 `scenePos()`**（自定义支点恒差 `o-R·o`）
- **顶点类**：旋转烘焙进顶点；`page_angle()=_baked_angle-rotation()`；`closeSubpath()` elementCount 多 1
- **网格/吸附**：步长 2 的幂（屏幕 18~90px）；`aim(always=True)` 退格点；唯一**红十字**（描深色底）；T=offset target-hover
- **捕捉点取真实顶点**：`frame_corners()`=包围盒四角（拖角专用）；线/三角/多边形/路径走 `_PointBasedItem.snap_points()` 顶点表（水平线加厚 60 把包围盒推离线 30）；自身点只画细十字、不吸附（否则自我牵引）
- **`_selection_own_points()` 必须缓存**：全选=1.4 万点、逐帧 60ms；按选中 id 缓存，`geometryChanged`/`refresh` 失效
- **交互**：**左键不拖图元**（含 CTRL）；移动只走双击=跟手（增量、单击落定、Esc 回原位、抓根父）；右键自接管；CAD 分点落子
- **缩放走 `_zoom_at()`**（NoAnchor+补滚动条）；别依赖 `AnchorUnderMouse`/`lastMousePos`（跟手不走基类，会整幅平移）
- **导航门控**：`set_pan_enabled`/`set_zoom_enabled`/`set_canvas_navigation_enabled` 只拦中键/空格/滚轮，左键永不参与
- **递归复制/组缩放**：`_capture_subtree`/`_instantiate` 深拷贝重发 id；组 `F(p)=A+(p-A)·(sx,sy)`，锚点无父=page_origin
- **组名前缀/拖角**：成组 prepend `<组名>_`、解组剥一层；四角蓝方块（跨度<28px 不画）
- **文本双向**：`style.font_size` 真值；改字号→改框；改框→`_fit_font_size()` 二分；加载/撤销不重算
- **widget**：7 类、5 顶层字段；`QFont()` 同族、**别按框高缩**；proxy 独立顶层不进索引，`resize`+`setTransformOriginPoint(中心)`+`setPos(mapToScene(0,0)-半尺寸)`，别 setGeometry 再 setPos

# 适配层 rack_scene_adapter（包壳，model 只改 import）
- 几何一律 page 坐标；`change_position(pos)` 对齐左上角：`delta=pos-tl` 后 `setPos(item.pos()+proj.delta(delta))`
- 线图元 head/end ≠ bbox 角；组隐藏不传子项（`_self_visible`+`_eff_visible`，隐藏前快照）
- 背景 alpha 按 `QPalette.Base` 合成→Base 设成 Window；`centerOn` ~1.4px 取整

# 适配层硬规则（rack/safety 共用）
- `getSize()` 用 `_proj.inverse_size(_w_view,_h_view)`（不是 page_bounding，它是旋转后 AABB）
- 四角是解析式 `中心+R(θ)·(±w/2,±h/2)`，不是 AABB 角点
- **旧 sceneRect 固定 ±100000**，适配层必须照抄，否则 `centerOn(0,0)` 被夹→整幅偏移
- 命中测试 `event.position()` 是视口坐标，要转场景坐标；`group_element.set_visibility` 递归
- 旧「场景即 QWidget」拆 Scene+View，入口 `self.scene` 指向 View；View 要补 `get_bg_color`/`grid_size`/`scale_factor`/`is_use_for_agv_map`
- `isinstance` 对壳失效用 `_is_group_like`/`_is_element_like` 兜底

# safety_scene_adapter（App_SafetyCar）
- `SafetyScene`+`SafetySceneView`；`SceneManager` 复刻 `m_items`/`m_name_items`/`m_sorted_items`/`findItem`
- 对拍：559 图元零差异、`m_name_items` 559 键、映射 max=1.50px；回归 `verify_safety_car_v2.py`
- `run_mode_station_change = Signal(object)` 载荷双形态，别改 `Signal(int)`；`safety_car_scene.json` sceneRect=0 → `restore_saved_view()` 回退
- **resize 钉左上角**：QGraphicsView 默认保持「视口中心场景点」，底部 dock 展开画面就上移半高差（825→517 实测上移 154px）；旧版自绘 `scene_origin` 只在 showEvent 定一次、resize 不动。`resizeEvent` 里 `anchor=mapToScene(0,0)` → `super()` → `_pin_top_left(anchor)`（零漂移）

# 增量刷新（2026-11-10，P0-2/P0-3 已落地）
- 信号：新增 `structureChanged` / `itemChanged(ids)`；**`contentChanged` 保留照常发射**（状态栏/外部兼容），图层树与吸附表只连细信号；写操作统一走 `emit_structure_changed()` / `emit_items_changed(ids)`，空 ids = 页面级改动
- 吸附表：`SnapSystem._by_owner` + `_entry_owners` 引用计数（点按坐标去重，删 owner 别一刀切）；`update_owner(oid,ends,mids)` 增量；表未建/无 owners/标脏 → 回退全量，保证「增量 == 全量」
- 视图：`structureChanged` 只置 `_snap_full_dirty`，`sync_snap_points()` 惰性全量；`itemChanged` 立即 `refresh_snap_owners(ids)` 并**扩到后代**（父刚体带子）；`_draw_item` 存在时按 T 仍全量
- 图层树：`update_items(ids)` 按行更新；过滤/新增/删除/未知 id → 退化全量；`set_scene` 用 `_bound` 记录实际连接再解绑（否则 PySide6 打 disconnect warning）
- `_after_edit()` 只剩 `history.commit()`；`history.commit` ~43ms 仍是单条命令最大瓶颈（P0-1 未做）
- 门禁 `tools/verify_core_qgraphics_incremental.py`；**验证几何变化必须用 `moveBy`**：`set_page_center` 对带父项被 `translate_locked()` 拒绝，会得到「空操作对空操作」的假绿

# 统一运行态模板框架（2026-11-10 新增，纯增量）
- 入口 `Designer/CoreQGraphics/runtime/`：`RuntimeStage`（装配/生命周期）、`RuntimeScene`（点击路由）、
  `RuntimeView`（取景/门控/坐标）、`RuntimeRegistry`+`RuntimeElement`（索引/门面）、
  `WidgetHost`+`ControlProvider`（widget 承载）、`TagBus`（去抖绑定）。文档 `docs/unified_runtime_template_design.md`，
  门禁 `tools/verify_unified_runtime.py`，样例 `tools/demo_unified_runtime.py`。**核心 g_*.py 零改动**。
- 现状 4 套装配（PopPick 1056 / rack 适配 580 / rack 全局参数 277 / safety 898 行）不统一；
  新代码一律从 `RuntimeStage` 起手，别再复制 `base_element`。
- **三个显式口径**：`widget_mode=host|builtin|none`（host 自建 proxy，**不调** `set_scene_mode(True)`；
  builtin 走核心内置 proxy）、`fit_mode=fit|pin|none`、`geometry_profile=strict|rack|safety`
  （rack 四角 AABB、strict/safety 解析式；迁移旧 model 选错会差上百 page 单位）。
- **硬规则**：`RuntimeElement` 只记 `item_id`、`item()` 现查，跨换页复用门面（信号不断）、
  消失 id 标 detached → 消灭 D-3 悬空；可见性只写 `item.setVisible()` 不碰 `_page`（运行态零污染）；
  `WidgetHost.reset()` 必须在 `scene.load_page()` 之前；proxy 独立顶层 + `resize` +
  `setTransformOriginPoint(w/2,h/2)` + `pos=mapToScene(0,0)-半尺寸` + `z+0.5`；
  回收 `setWidget(None)`→hide→setParent(None)→deleteLater。
- 旧 API 门面：`stage.scene_manager`（rack 口径）/ `stage.pages_manager`（PopPick 只 widget 卡片）。
  **未覆盖**：位图快照缓存、PageDeck 动画精确标脏、snap7 客户端、活跃页订阅、safety 双形态载荷信号代理
  （`set_motion_cache`/`set_exact_repaint` 是明示 no-op 钩子）。
- 对拍：`page_1` 1618 项几何与 rack 适配层 0 差异；装载+挂控件后 `page_data()` 与磁盘 JSON 逐字相等。
- **首个落地项目 `App_test_fixture/`**（2026-11-10）：入口 `python -m App_test_fixture.fixture_app --source demo|none|modbus`，门禁 `tools/verify_test_fixture.py`。数据源抽象 `DataSource`，默认 Demo，接 Modbus 只填 `MODBUS_REGISTER_MAP` + 注入 reader/writer 或 `submit()`。
- **sceneRect=0 取景**：`fit_scene` 回退分支必须直接用 `fit_rect()`（已是视图坐标），只有 header 的 `sceneRect`（page 坐标）才 `projection.rect()`；二次投影会让画面全空。
- **运行态改色/位移零污染**：别用 `set_fill_color`/`set_page_center`（会写 `_page`）。改色写 `item._style`+`update()`；位移 `change_position()` 后把父+后代 `_page` 从快照还原 +`mark_clean()`+清 `scene._modified`。还原后判实际位置用 `item().sceneBoundingRect()`，不是 `get_scene_center_pos()`。
- **AGV 投影轴交换**：默认 `(0.25,0.25,True,0,0)`，page 的 y 位移在视图里是 x 位移，写对拍别读错轴。
- **widget 图元挂整页控件**（`servo_panel.py`）：`stage.set_mapping({name: ControlProvider})` 必须在 `load()` 前；`set_factory` 在 registry 空时会静默失效。`signature()` 固定，业务用 `controlCreated`/`controlDestroyed` 接信号与清引用；`FixtureRuntime(panel_provider=...)` 可换任意 QWidget 或外部 C++ 窗口（`QWindow.fromWinId`+`createWindowContainer`）。图元给控件的尺寸 = projection 后 scene 尺寸（本页 468×345），不是 page 宽高。
- **面板字段表元组形状**：`fixture_config.AXIS_*_FIELDS` → `PanelSpec.from_config()` → `ServoAxisPanel.__init__` 三处解包必须同形（现全 3 元组 `(标签, 成员, 需确认/报警/单位)`）；改配置漏改构造会在装载期 `ValueError` 并被 `RuntimeStage.load()` 包成「场景载入失败」。带确认的点动按钮确认后发 `True→False` 脉冲（确认时鼠标已松开），普通点动才是按住 True / 松开 False。
- **Modbus 40001**（`App_test_fixture/modbus_link.py`）：`common/com/modbus` 底层是 pymodbus **0-based 协议地址**，40001 是 4xxxx 编号 → 默认换算成 0；`MODBUS_ADDRESS_MODE="4xxxx"|"raw"`、`MODBUS_START` 一处平移。映射表用相对 `offset`（字）+ `type/scale/access/bit`，单点改写走 `MODBUS_REGISTER_OVERRIDES`。读必须**按跨度一次批量读**别逐点请求；float32 高低字序 `MODBUS_FLOAT_WORD_ORDER`；命令 BOOL 一点位一字不做位打包。填 `MODBUS_IP` 或 `--ip` 才连设备。
- **离屏渲染**：`QT_QPA_PLATFORM=offscreen` 字体库为空、中文变 □；`fixture_app.ensure_cjk_fonts()` 只在字体库为空时手动加载 `msyh.ttc`/`simhei.ttf`。
- **`struct` 格式符 / Modbus 字数**：`'f'`=binary32=4 字节=**2 字**（约 7 位有效数字），`'d'`=binary64=8 字节=**4 字**（15~16 位）。`modbus_link.width()` 必须跟着 type 走（`double64`→4），offset 步长按 4 递增；`encode/decode` 要严格互逆并统一 `>` 网络序。**别用** `common/com/modbus.set_double/set_float`：本机小端 `pack('d')` 配 `int.from_bytes(...,'big')` 字节序反了，`get_double` 的 `float.fromhex(hex(...))` 也不成立。
- **门禁不绑现场布局**：`verify_test_fixture.py` 第 7b 组用固定 spec + 独立紧凑 `test_map` 测协议（key 仍用真实点位名过白名单），`rmap` 只查「⊆ known_keys」；面板数量按 `AXIS_*_FIELDS` 动态算。现场 offset 重排不会让整组变红。
- **现场 PLC 浮点字序（用户实测）**：`12.5` 的 LREAL = `[0, 0, 0, 0x4029]`，即**低字在前但字内字节仍大端**（`0x4029` 不是 `0x2940`）。`MODBUS_FLOAT_WORD_ORDER="little"`，`_ordered_words()` 做**整体字列表反序**，不是两两交换（后者 double64 会解出 5.3e-315）；float32 2 字时两者等价。反序自逆，encode/decode 共用即严格互逆。别把网络序 `[0x4029,0,0,0]` 当通用解。
- **PLCManager 心跳会写寄存器 1000**：`common/com/modbus/modbus_plc_manager.py` 心跳线程每 500ms `write_registers(1000, seq)`。启用 `MODBUS_USE_PLC_MANAGER=True` 且映射表有点位占 1000 时会被周期覆盖；`modbus_link.heartbeat_conflicts()` 会在 `connect()` 时警告。最省事的解法是关掉 PLCManager。
- **`byte` 类型 = BOOL 按字节打包**：一个字放两个 BOOL，`byte=0` 用 bit0(0x0001)、`byte=1` 用 bit8(0x0100)，每个字节只用最低位。`_byte_bit()` 统一算掩码；`ModbusLink.write()` 把 `bit`/`byte` 合并成「先算掩码 → 读一字 → 位或/位与 → `&0xFFFF`」的幂等读-改-写。**别用 `+= / -=`**（进位污染、重复累加、False 出负数），也别写 `1<<8 if idx==1 else 0`（idx=0 变 0，低字节写不进）。调试 print 走 `DEBUG_WRITE=False`。
- **地址重叠检测**：`overlap_conflicts(map)` 把「同地址多个 `byte` 且 byte 值互异」视为合法打包，其余重叠（状态字与 double64 挤同一 offset）在 `connect()` 警告。现场布局常变，别把某版 offset 写死进门禁。
- **运行态刷新 text 图元（零污染）**：只写 `item.context` + `update()`。`TextItem.paint()` 读 item 属性，`to_page_record()` 只深拷贝 `_page` **不回读属性** → `page_data()` 恒等于磁盘 JSON。`_page` 是 dict，`it._page.context = x` 直接 `AttributeError`；`RuntimeElement.context` setter 走 `set_page_field` 会写 `_page` 且触发 `_on_text_changed()` 重算边框，运行态禁用。
- **点位名 ≠ 图元名**：`values` 的 key 是 `cfg.TAG[...]`，`element_of()` 按 JSON 的 `name` 查（写错静默返回 None，界面停在占位符）。新增显示图元只加 `fixture_config.TEXT_BINDINGS` 一行 + 映射表一行；`_check_text_bindings()` 在 load 期对失配/非 text 类型发 warn。门禁图元数量按 `len(disk_json()["items"])` 动态取，别写死。
- **`uint32` 也吃浮点字序开关**：`decode/encode` 的 `uint32/int32` 同样走 `_ordered_words()`；若 PLC 的 DWORD 与 LREAL 字序不同，用 `MODBUS_REGISTER_OVERRIDES` 给单点设 `word_order="big"`。
