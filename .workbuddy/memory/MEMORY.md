# 通用约定
- PySide6；`.ui` 走 `uic_compat.loadUi`；脚本/回归/打包一律 `.venv/Scripts/python.exe`
- 打包用本项目 .venv；`工具集.spec`/`packTool.py` 同步；返回码 0 也扫 warn
- 资源保持源码层级（例外 cset_parser cfg）、必带 myDesigner/data2.json；hook-snap7 add_dll_directory 只收目录；冒烟 `--app PopPick --no-plc` exit=124 正常

# 旧 Designer/Core
- 料仓：`rack_store_model`+`rack_stores_status_model`（唯一真值）；重载后 `refresh_models()`；隐藏组递归清子可见；`visual_key` 判等；判料位别用 `bool(state)`
- `change_size` 锚点：无父=旋转中心 `m_origin`、有父=左上角；AGV 90° 控件宽=场景高
- App_PopPick HMI 750×1000 1:1；`QSizePolicy.Ignored`+setMinimumWidth 会重叠→覆写 minimumSizeHint；Qt6 行数外 rowStretch 无效→底部 Spacer

# CoreQGraphics
入口 `python -m Designer.CoreQGraphics.ui [page.json]`；顶层 `__getattr__`；复用 `Core/property_widgets.py`
- **硬约束**：page_1 逐图元 0/1618、JSON round-trip 零改动；回归 `verify_core_qgraphics.py`、`_ui.py` + 外围 8 项
- **脏标记**：`_dirty`/`_geo_dirty`；只写 `_page` 字段；关窗 `is_modified()`
- **平铺层级**：`parent_id/children_ids`+SceneIndex，**不用 setParentItem**；`translate_locked()` 只锁平移；父移动 `on_item_moved` 传播；**删组递归删后代**，删成员只删自己
- **支点**：`scene(q)=pos+o+R(q-o)`；`_place()` 解 o=R⁻¹(O-C)；中心标识只画红点、无 ID
- **平移用 `pos()` 不用 `scenePos()`**：自定义支点+旋转恒差 `o-R·o`；验证位姿只读 `mapToScene(0,0)`
- **顶点类**旋转烘焙进顶点；center/pivot 原样带；`page_angle()=_baked_angle-rotation()`；`closeSubpath()` elementCount 多 1
- **网格/吸附**：步长 2 的幂（屏幕 18~90px）；`aim(always=True)` 退格点；唯一橙十字；T 键 offset=target-hover；拖动中不要 moveBy
- **交互**：**左键不拖图元**（含 CTRL）；移动只走双击=跟手（增量位移、单击落定、Esc 回原位、T 吸附不被抹、抓根父对象；`_warp_cursor_to_snap` 同步 `_follow_cursor`）；右键自接管；CAD 分点落子
- **缩放走 `_zoom_at()` 自算锚点**（NoAnchor+量光标场景点差值补滚动条）；**别依赖 `AnchorUnderMouse`/`lastMousePos`**——跟手分支不走基类 mouseMove，lastMousePos 停旧点，`scale()` 会整幅平移
- **画布导航门控在 `GraphicsView`**：`set_pan_enabled`/`set_zoom_enabled`/`set_canvas_navigation_enabled`（默认 True），只拦中键/空格平移与滚轮缩放，**左键永不参与**（PopPick 左键是 PageDeck 翻页手势）；运行视图构造时统一关，别在子类另存布尔
- **递归复制/组缩放**：`_capture_subtree`/`_instantiate` 深拷贝重发 id；组 `F(p)=A+(p-A)·(sx,sy)`，锚点无父=page_origin、有父=旋转后左上角
- **组名前缀/拖角**：成组 prepend `<组名>_`、解组剥一层；四角蓝方块（对面角锚、AGV 轴交换、跨度<28px 不画）
- **文本双向**：`style.font_size` 真值；改字号/context→改边框；改框→`_fit_font_size()` 二分；加载/撤销不重算
- **widget 变体**：7 类、5 个顶层字段；`g_widgets.py` 自绘（字号=widgetFontSize、`QFont()` 同族，**别按框高缩**）；工具箱 `widget:<key>`
- **运行预览 proxy**：独立顶层、不进索引/page_data；`create_control` 必须 `setMinimumSize(1,1)`；对齐 `resize`+`setTransformOriginPoint(中心)`+`setPos(mapToScene(0,0)-半尺寸)`，**别 setGeometry 再 setPos**；删图元按 id 销毁
- **面板取代旧 QuadTreeScene 取景照抄**：`setFrameShape(NoFrame)`+手算 scale 再 `scale()`（**别用 fitInView**）

# 适配层 rack_scene_adapter.py
包壳不重写；model 只改 import，双栈并存
- **几何一律 page 坐标**：`page_center()`→`get_scene_center_pos()`、`page_bounding_rect()`→`sceneBoundingRect()`
- **`change_position(pos)` 对齐左上角**；`delta=pos-tl` 后 `setPos(item.pos()+proj.delta(delta))`，**别用 scenePos()**
- **线图元 head/end ≠ bbox 角点**：`line_element` 覆写读 `_page["head_pos"/"end_pos"]`
- **组隐藏不传子项**：壳记 `_self_visible`+`_eff_visible`（AND 祖先）；隐藏前快照、显示按快照还原
- **背景色 alpha 按 viewport 底色合成**：`QPalette.Base`(白) vs 旧 `Window`(#efefef) → Base 设成 Window
- **`centerOn` ~1.4px 取整**，断言换像素比；**`clicked`**：按下记锚点→释放判仍在组内才发
- **改 model import 后 `isinstance` 失效**：判文本走 `isinstance / TYPE / type().__name__` 三路
- 回归 `verify_rack_stores_v2.py`（53 项）

# 适配层通用硬规则（rack / safety 共用，已踩过）
- **`getSize()` 用 `_proj.inverse_size(_w_view,_h_view)`**；用 `page_bounding_rect().size()` 会拿到旋转后 AABB，非 90° 倍数角度全差
- **四角是解析式** `中心 + R(θ)·(±w/2,±h/2)`，**不是 AABB 角点**（斜图元差 10+ 单位）
- **线图元尺寸**：`head_pos/end_pos` 存的是已旋转 page 坐标，先按 `-page_angle` 转回图元方向再求差
- **旧场景 `sceneRect` 固定 ±100000**，适配层 `SafetyScene`/`RackScene` 必须照抄；否则 `centerOn(0,0)` 被滚动条夹住 → 整幅偏移半个场景（像素差 98% 就是它）
- **命中测试坐标系**：`event.position()` 是视口坐标，`sceneBoundingRect().contains()` 要场景坐标 → 必须 `_view_to_scene(event)`
- **`group_element.set_visibility` 是递归的**（成员自身标志也变 False）；平铺层级只能手动递归 + 隐藏前快照、显示按快照还原
- **旧「场景即 QWidget」拆成 Scene + View**：入口 `self.scene` 指向 View，由 View 代理场景接口（`selectionChanged`/`current_selected`/`run_mode_station_change`），并把 scene 自身映射成 view 自身（旧 `current_selected` 无选中时是场景对象）
- **View 必须补齐 `NavigationContentWidget` 要的读属性**：`get_bg_color`/`set_bg_color`/`grid_size`/`scale_factor`/`is_use_for_agv_map`，否则页面背景页抛 `AttributeError`
- **`isinstance` 对适配壳失效要双向兜底**：`NavigationContentWidget` 用 `_is_group_like`/`_is_element_like`（`TYPE` + `type().__name__` + 旧类三路）

# 适配层 safety_scene_adapter.py（App_SafetyCar）
- 入口 `self.scene = SafetySceneView(parent=self)`；`SafetyScene(GraphicsScene)` + `SafetySceneView(GraphicsView)`；`SceneManager` 复刻 `m_items`/`m_name_items`/`m_sorted_items`/`findItem`/`findItemByName`
- 对拍基线：559 图元 × 中心/四角/尺寸/角度/可见性 **零差异**，`m_name_items` 559 键一致，屏幕映射 `max=1.50px`；回归 `verify_safety_car_v2.py`（10 组）
- `run_mode_station_change = Signal(object)` 载荷双形态（`SceneMode` 或站点名 `str`），别改成 `Signal(int)`
- 已知差异：`goto_origin()`/`restore_saved_view()` 瞬时 1:1，旧 `goto_sence_origin()` 是 1s 缓动；`safety_car_scene.json` 的 `sceneRect` 为 0 → `restore_saved_view()` 返 False 回退 `goto_sence_origin()`
