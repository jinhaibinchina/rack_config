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
