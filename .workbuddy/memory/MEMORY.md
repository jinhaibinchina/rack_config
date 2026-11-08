# 通用约定
- PySide6；`.ui` 走 `uic_compat.loadUi`；脚本/回归/打包一律 `.venv/Scripts/python.exe`
- 打包必须本项目 .venv；`工具集.spec` 与 `packTool.py` 同步；返回码 0 也扫 warn；spec 前置 find_spec、asyncua collect_submodules
- 资源保持源码层级；例外 cset_parser cfg/config.json；必带 myDesigner/data2.json；hook-snap7 add_dll_directory 只收目录；冒烟 `--app PopPick --no-plc` exit=124 正常，**别冒烟 Designer**

# 旧 Designer/Core
- 料仓：`rack_store_model.py`+`rack_stores_status_model.py`（状态唯一真值）；重载后 `refresh_models()`；隐藏组递归清子可见、重显重灌；`visual_key` 判等；判料位别用 `bool(state)`；`m_children` 不保序，组内搬家 `change_position()`
- `change_size` 锚点：无父=旋转中心 `m_origin`，有父=左上角（`_resize_anchor_local/_axis_scale/_scale_about`）；`fit_widget_size`/`widget_pixel_size`；AGV 90° 控件宽=场景高
- 嵌入控件：透明 QGraphicsView+ProxyWidget，`view.setTransform`、`proxy.setRotation(-angle)`；承载层 StrongFocus；`addWidget` 前不能 setParent；顶层 widget `setMinimumSize(1,1)`；Run 惰性创建；回归 embedded_widget/press_through
- `scene_fast.py` 复用 QPen/QBrush/QFont，`RACK_SCENE_FAST=0` 退回；numpy 5~620 点更慢，别引入
- App_PopPick HMI 750×1000 1:1；`QSizePolicy.Ignored`+setMinimumWidth 会重叠→覆写 minimumSizeHint；Qt6 行数外 rowStretch 无效→底部 Spacer；`_pixel_font`
- App_PopPick 运行态已跑 `qgraphics_runtime.py`（CoreQGraphics，Core 零改动）；动画靠「控件 grab 成位图」：proxy 对齐= `resize`+`setTransformOriginPoint(w/2,h/2)`+`pos=center-半尺寸`（**别用 setGeometry(-w/2,-w/2)**）；`_static`(长期意图) 与 `_cached`(谁在显示) 必须分开记账；位图按**逻辑宽×m11×view.dpr** 定标、启用 `devicePixelRatio()` 反算；重烘走 `_mark_snapshot_dirty`+分片空闲刷新（别同步 grab 一批）；`NoCache`+`MinimalViewportUpdate`+`ItemHasNoContents`；回归 `tools/verify_pop_pick_qgraphics.py`（63 项）

# CoreQGraphics
入口 `python -m Designer.CoreQGraphics.ui [page.json]`；顶层 `__getattr__`；复用 `Core/property_widgets.py`；旧项目无图层树
- **硬约束**：page_1 sceneBoundingRect 0/1618、JSON round-trip 零改动；主回归 `tools/verify_core_qgraphics.py`、`_ui.py` + 外围 8 项
- **脏标记**：`_dirty`/`_geo_dirty`；属性编辑只写 `_page` 对应字段；关窗 `is_modified()`；Delete 走 `delete_items()`
- **平铺层级**：`parent_id/children_ids`+SceneIndex，**不用 setParentItem**；`translate_locked()` 只锁平移；父移动 `on_item_moved` 刚体传播 `p'=R(dA)(p-C)+C'`
- **支点**：`scene(q)=pos+o+R(q-o)`；`_place()` 解 o=R⁻¹(O-C)、pos=O-o；`set_page_origin` 保中心；`pivot_scene_point()`=page_origin；中心标识只画红点 r=3、**无 ID**
- **平移必须用 `pos()` 不能 `scenePos()`**：有自定义支点+旋转非 0 时二者恒差 `o-R·o`，`setPos(scenePos()+delta)` 每帧白走这一段（斜图元漂/飞出，正放不暴露）。已修 `g_element.set_page_center`、`g_view` 拖根父分支；验证位姿只能读 `mapToScene(0,0)`，别读记录值（自洽）
- **顶点类**旋转烘焙进顶点；烘焙纯记账，center=/pivot= 原样带（重找中心会让三角支点跳）；`_baked_angle`、`page_angle()=_baked_angle-rotation()`；`closeSubpath()` elementCount 多 1
- **网格/吸附**：步长 2 的幂（屏幕 18~90px）；格点解析不进点集；`aim(always=True)` 退格点；唯一橙十字 (255,150,0)；T 键 offset=target-hover；**拖动中不要 moveBy**
- **交互**：移动需 CTRL；右键自接管；CAD 分点落子（`set_draw_tool`/`draw_add_point`）；Esc 取消、右键 finish_polygon
- **递归复制/组缩放**：`top_level_items()`；`_capture_subtree`；`_instantiate` 深拷贝、重发 id、重映射；平铺 offset 施加到每个几何点；组 `F(p)=A+(p-A)·(sx,sy)`，锚点无父=page_origin、有父=旋转后左上角；`apply_scale_about` 用 `_apply_pose`；成组/解组 `set_page_field`
- **组名前缀/拖角**：成组 prepend `<组名>_`，解组剥一层，粘贴 `_free_from`；四角蓝方块（对面角锚、AGV `sx=d_local.y/d0.y`、跨度<28px 不画、运行态禁用）
- **文本双向**：`style.font_size` 真值；字号/context 变→`text_metrics()`+`TEXT_PAD_X/Y` 改边框；W/H/拖角/组缩放→`_fit_font_size()` 二分（只写 font_size）；`_text_resizing`；加载/撤销不重算；AGV 两轴取 min
- **widget 变体**：7 类；5 个**顶层**字段（不进 style/context）；`g_widgets.py` 占位自绘（字号=widgetFontSize 原值、`QFont()` 同族同字号，**别按框高缩**）；工具箱 `widget:<key>`
- **运行预览 proxy**：`set_scene_mode(True)` 挂独立顶层 proxy（不做 Qt 子项、不进索引/page_data）；`create_control` 必须 `setMinimumSize(1,1)`；对齐 `resize(w,h)`+`setTransformOriginPoint(w/2,h/2)`+`setPos(mapToScene(0,0)-(w/2,h/2))`+`setRotation(it.rotation())`，**别用 setGeometry 再 setPos**
