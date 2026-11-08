"""Designer.CoreQGraphics —— 用原生 QGraphicsScene 重写的 Core 平行实现。

与 ``Designer.Core`` 读同一份 ``page_*.json``，序列化格式零改动；
不改动、也不 import ``Designer.Core`` 的任何运行时代码（仅图片路径解析
复用项目的 resource_manager，失败时回退到相对路径）。

典型用法::

    from Designer.CoreQGraphics import load_page, GraphicsView

    scene = load_page("Designer/Core/data.json/datas/design/pages/page_1.json")
    view = GraphicsView(scene)
    view.fit_content()
    view.show()

模块对应关系::

    Core/element.py            -> g_element.py   (BaseItem)
    Core/elements.py           -> g_elements.py  (12 类图元)
    Core/my_transform_v2.py    -> g_projection.py(坐标投影)
    Core/myGraphicsScene.py    -> g_scene.py     (场景 + 视图范围)
    Core/myQuadTreeScene.py    -> g_scene.py     (SceneIndex + 序列化)
    Core/mySnapSystem.py       -> g_snap.py
    Core/scene_fast.py         -> g_style.py
    Core/elements.py:widget_element -> g_widgets.py (7 种控件变体)
    （Core 无对应物）          -> g_view.py      (QGraphicsView 交互)

UI 外壳在子包 ``Designer.CoreQGraphics.ui``：属性面板 / 工具箱 / 图层树 /
设计器主窗口，命令行 ``python -m Designer.CoreQGraphics.ui page_1.json``。
顶层用 ``__getattr__`` 延迟导出，纯场景用户不会被 UI 依赖拖慢导入。

已知边界（见 docs/stage2_geometry_backend_design.md 附录 C）：
* widget 图元支持 7 种控件变体：设计态自绘占位、运行预览挂真实 Qt 控件，
  但不移植旧 Core ``EmbeddedWidgetLayer`` 的裸 QWidget overlay / 位图快照 /
  延迟事件派发那一整套性能补丁；
* 不含 PLC / 料仓状态绑定与运行态站点说明页。

父对象与旋转支点（口径与 Designer.Core 逐项对齐）：
* 有父对象（``parent_id``）的图元**不能自行平移、但可以自行旋转**：父对象平移 /
  旋转时，后代图元的中心、支点、角度一起走同一个刚体变换（顶点类图元把旋转
  烘焙进 ``vertices``）；子图元自己拖不动——拖它会转成拖根父对象，而
  ``set_page_angle`` / ``rotate_by`` / 面板「旋转」仍然生效（绕自己的支点转，
  后代跟着转，父对象与兄弟不动）。
* **坐标系**：设了父对象后，对外读数与写入口径都是**父坐标系**——原点是父图元
  的可视中心、朝向是父图元的绝对角度。``page_local_center()`` /
  ``page_local_angle()`` / ``page_local_origin()`` 取值，父对象怎么动这组数都不
  变；``set_page_local_angle`` / ``set_page_local_origin`` 按父系写入。属性面板
  的「布局」页因此显示 ``（父坐标系）``，中心 X/Y 只读（不能自行平移）。
  存储与 page JSON 仍是场景绝对坐标（``page_center`` / ``page_angle``），以便
  存量页面零改动、与旧引擎逐项对拍；两套口径靠 ``local_to_world`` /
  ``world_to_local`` 互换。
* 旋转支点 ``origin_pos`` 与可视中心 ``center_pos`` 解耦：``_place()`` 按
  ``q → pos + o + R(q - o)`` 摆位，所以 ``mapToScene(0) == center``、
  支点处不动，改角度即铰链式旋转。画布上右键菜单「旋转中心设到此处」把支点
  钉在点击位置，选中时画蓝色十字圆环 + 中心到支点的虚线；**旋转中心标识（红色
  小圆点，不再带 ID 数字标签）画在支点处**（``pivot_scene_point()``），默认绕中心
  转时与几何中心重合。视图菜单「显示中心点标记」（Ctrl+Shift+I）控制这个红点。
* **顶点类的旋转是「记账」不是「重建」**：``line / triangle / polygon / path`` 的
  几何是烘焙进 ``vertices`` / ``head_pos`` 的绝对坐标，所以改角度只是先把 Qt
  旋转挂上去（``_apply_pose``），存盘时才 ``bake_rotation()`` 折进顶点。烘焙
  必须原样带上中心与支点（``set_page_vertices(center=…, pivot=…)``）——
  三角形不是中心对称图形，绕中心转一次后**包围盒中心本来就换了个点**，若按
  新包围盒重新定位，支点会跟着跳一大截。真实朝向记在 ``_baked_angle``（落盘即
  ``rotate`` 字段，旧 Core 读法是「先反旋再正旋」，等价恒等，不会二次旋转），
  所以面板「旋转」读回的是绝对值，连续设 30→60 就是 60，不是叠加成 90。

递归复制与组尺寸（对照 ``Core/myQuadTreeScene.copy_selected`` / ``paste`` 与
``Core/elements.py:rect_element.change_size``）：
* 复制（Ctrl+D 直接复制；Ctrl+C / Ctrl+V 走场景剪贴板）只取**顶层**图元
  （祖先也在选中集合里的跳过），但会按 ``index.descendants`` 递归带上整棵子树；
  快照用 ``to_page_record()``（未存盘的旋转会先烘焙进顶点），父在子前展平。
* 粘贴时统一重发 id，并重映射 ``parent_id`` / ``group_id`` / ``children_ids``；
  快照外引用一律断开。平铺结构没有 Qt 父链，**偏移必须施加到树里每个几何点**
  （center / origin / head / end / vertices），否则只有顶层动、后代留在原地。
  剪贴板快照深拷贝后再改写，连续粘贴按 ``_paste_count`` 阶梯偏移。
* 组改宽高（布局页 W/H 或 ``+`` / ``-``）会**递归改变组内成员尺寸与位置**：
  ``GroupItem.set_page_size`` 委托 ``GraphicsScene.resize_group``，把整棵子树
  的 page 绝对几何点统一过 ``F(p) = A + (p - A)·(sx, sy)``。锚点沿用旧规则
  ——无父取旋转中心、有父取左上角。矩形类走 ``BaseItem.apply_scale_about``
  （``_apply_pose`` 绕过 ``translate_locked``），顶点类走
  ``_PointBasedItem.apply_scale_about``（``center=`` / ``pivot=`` 原样带过去）。
  ``_scaling`` 防重入、``_suppress_propagate`` 防双重刚体传播。

组名前缀体系与拖角改尺寸（对照 ``Core/elements.py:group_element`` 的
``_prefix_name_subtree`` / ``set_name`` 与 ``myQuadTreeScene.paste`` 的
``free_name`` / ``rename_members``）：
* **成员名带组名前缀**：成组时给整棵子树 prepend ``<组名>_``（嵌套组逐层
  累加）；组改名时把旧前缀换成新前缀；解组时剥掉一层。三个入口分别是
  ``group_selected`` / ``BaseItem.set_name`` → ``GraphicsScene.rename_group``
  （属性面板与 F2 都覆盖）/ ``ungroup_selected``。
* **粘贴命名**：组自身 ``原名_2``、``原名_3``…（``_free_from`` 从 2 起，同时
  对场景已有名字与本次批次查重）；组内成员只做**字符串前缀替换**
  ``原名_`` → ``新名_``，不再追加后缀；前缀不匹配或撞名时退回
  ``类型_序号`` 默认命名。名字表用 ``names_in_use()`` 现算，不维护全局字典。
  这里刻意修掉旧 Core 三处历史缺陷：非组顶层不再丢弃用户自定义名、连续粘贴
  不再产生 ``原名_2_2_2``（剪贴板始终是原始快照）、默认命名包含 ``path``
  分支。
* **拖角手柄**：旧 Core 其实**没有**这个交互（改尺寸只有属性面板 →
  ``change_size``），这里按 ``change_size`` 的锚点 / 递归语义新做。设计模式下
  单选图元在四角画蓝色小方块（``GraphicsView._draw_resize_handles``），按下
  冻结按下瞬间的 ``sceneTransform().invert()``，拖动时把鼠标映射回局部坐标，
  以**对面的角**为固定锚点求总缩放比例，每帧只提交增量给
  ``GraphicsScene.resize_item_about``（仿射可复合，不累积漂移）。视图局部轴与
  page 轴在 AGV 投影下是交换的，故 ``sx = d_local.y / d0.y``、
  ``sy = d_local.x / d0.x``。组走 ``resize_group(anchor=…)`` 让成员递归跟随；
  场景级 ``_resizing_group`` 挡住 ``apply_scale_about`` 回到
  ``GroupItem.set_page_size`` 时的二次委托。四角屏幕跨度小于 28px 时不画也不
  命中，避免小图元的手柄挤在中心抢走选中按下；运行模式不显示。

删除语义（对照 ``Core/element.py:base_element.Delete``）：
* 删除组（或任何拥有成员的图元）时**递归删除全部后代**，嵌套组逐层展开。
  旧 Core 的 ``Delete()`` 就是先让每个子项走自己的删除路径再删自己，以前
  新场景只解除 ``parent_id``、把成员留成散图元，与旧场景不一致。
* 反方向不成立：删成员只删它自己，父对象 ``children_ids`` 同步剔除（兜底
  清理指向已删 id 的残留引用）；运行态 ``QGraphicsProxyWidget`` 按 id 一起
  销毁，不会留下盖住别人的孤儿控件。

文本图元：字号与边框背景（对照 ``Core/elements.py:text_element``）：
* 旧 Core 是**由宽度反算字号**（``calc_font_size`` 逐步试到文字
  ``boundingRect`` 高度达标，再用文字宽度反算高度），``font_size`` 不是独立
  真值。新场景反过来：``style.font_size`` 由属性面板直接给定（「文本内容」
  页的「字体大小」与「外观」页的「字号」两处同步），边框 / 背景只是文字的
  容器，随文字重新计算。
* ``g_style.text_metrics(text, font_size)`` 用与 ``TextItem.paint`` 同一份
  ``font_for("Arial", size, True)`` 的 ``QFontMetricsF`` 量出视图像素尺寸；
  多行按 ``lineSpacing*(n-1) + height`` 累加（直接 ``height*n`` 会少算
  leading 把字裁掉）。量完外扩 ``TEXT_PAD_X/Y``，再用
  ``SceneProjection.inverse_size`` 反算 page 宽高——AGV 投影交换了轴，
  **view 宽对应 page 的 height、view 高对应 page 的 width**。
* 触发点只有两个显式编辑：``style.font_size`` 真变了（``_sync_field`` 比较
  新旧值，改颜色 / 线宽不会撑大边框）或 ``context`` 变了；
  ``BaseItem._on_text_changed`` 是空 hook，``TextItem`` 覆写后调
  ``set_page_size``，中心与支点都不动。**加载 / 撤销重建绝不重算**，否则
  page_1 的 1618 图元对拍和 JSON round-trip 零改动会立刻失效。
* 布局页 W/H、拖角手柄、组缩放、``+`` / ``-`` 快捷键都会**反向反算字号**，
  即「双向联动」。``BaseItem.set_page_size`` / ``resize_by`` 成功后调
  ``_on_size_changed`` 空 hook，``TextItem`` 覆写后按新视口边框二分找出
  「文字 + 内边距装得下」的最大整数字号（``_fit_font_size``，与旧 Core
  ``calc_font_size`` 从 1 逐步试同口径，上界 200 / 下界 4 与属性面板一致），
  只写 ``style.font_size``、**保留用户给定的 W/H**——旧 Core 会由文字宽度
  派生高度，那会让拖角每帧的比例基准抖动、组子树几何失真。
* 两个方向用同一个 ``_text_resizing`` 标志互斥：字号 / 文本编辑时抑制反算、
  尺寸编辑时抑制边框重算，不会互相递归；**加载 / 撤销走 ``_setup_rect``
  构造路径，绝不触发任何联动**，这是 page_1 对拍与 round-trip 零改动的前提。
  AGV 轴交换后 page W 决定 view 高（行高方向）、page H 决定 view 宽（文字
  长度方向），反算取「两轴都装得下」的最大值：缩小任一轴都会收紧约束让
  字号变小（防裁字），只放大一个轴受另一轴限制，字号可能不变。
* 属性面板 ``refresh_geometry`` 会把反算后的字号回显到「文本内容」/「外观」
  两处输入；布局页对文本图元给出对应 hint。旧 Core 的「宽度→字号→派生高度」
  口径没有照搬，两处设计器互相打开时字号仍不完全等价。

widget 控件变体（对照 ``Core/elements.py:widget_element``）：
* 旧实现把变体做成 ``widgetType`` 一个字符串 → 7 个 Qt 类的一层分发：
  ``textedit`` / ``lineedit`` / ``checkbox`` / ``combobox`` / ``pushbutton`` /
  ``label`` / ``spinbox``，未知值退化 ``textedit``。序列化只有 5 个**顶层**
  字段（不在 ``style``、不复用 ``context``）：
  ``widgetType`` / ``widgetText`` / ``widgetFontSize`` / ``widgetColor`` /
  ``widgetBackground``，默认值 ``textedit`` / ``""`` / ``12`` / ``#000000`` /
  ``#ffffff``。``width`` / ``height`` / ``rotate`` / ``style`` / ``zValue``
  与矩形图元完全同构。
* ``widgetText`` 按变体解释：combobox 每行一个选项（空 → ``["选项 1"]``）；
  spinbox 每行 ``min=`` / ``max=`` / ``value=``（缺省 Qt 0 / 99、value 取 min，
  ``min>max`` 交换、value clamp）；checkbox / pushbutton / label 空文本显示
  「选项 / 按钮 / 标签」；lineedit 直接 ``setText``；textedit 只读多行。
  样式统一 ``color / background-color / font-size: Npt``，颜色非法回退黑 / 白。
* 旧 Core 的 ``paint`` 完全不区分变体（矩形 + "Widget" 字样），不同外观来自
  ``EmbeddedWidgetLayer`` 挂载的真实 QWidget。重写版是平铺 QGraphicsItem，
  所以 ``g_widgets.paint_variant`` 在设计态按变体自绘可辨识占位（下拉三角、
  微调箭头、勾选框、按钮立体边、多行横线等），只画不改几何，对拍与
  round-trip 不受影响；``GraphicsScene.set_scene_mode(True)`` 再用
  ``QGraphicsProxyWidget`` 挂真实控件。
* proxy 是**独立顶层 item**：不做图元的 Qt 子项（否则 ``sceneBoundingRect``
  被撑大、page_1 对拍崩），不注册进 ``SceneIndex``（``all_items`` /
  ``page_data`` 都看不到它），按 ``_align_widget_proxy`` 手工对齐：控件本地
  矩形恒 ``(0,0,w,h)``，``resize`` 只改尺寸、``setTransformOriginPoint(w/2,h/2)``
  把旋转支点钉在控件中心、``pos = mapToScene(0,0)-(w/2,h/2)``、旋转角取
  图元 ``rotation()``。**不要用 ``setGeometry(-w/2,-h/2,w,h)`` 再 ``setPos``**：
  前者会同步改写 pos，控件左上角会跑到图元中心并绕左上角旋转。
  设计态完全不创建，退出运行预览即销毁；字段变了按签名重建控件，
  图元位姿变了由 ``geometryChanged`` / ``on_item_moved`` 调用
  ``align_widget_proxies()`` 只重排、不重建。
* 工具箱用 ``widget:<key>`` 伪类型（7 个变体按钮 + 1 个通用），``create_item``
  在入口解析别名：真正的 ``type`` 仍写 ``widget``，变体只落 ``widgetType``。
  属性面板「控件」页可切变体、编辑文本 / 字号 / 文字色 / 背景色；注意 widget
  的字号是顶层 ``widgetFontSize``，不是 ``style.font_size``。
  缺 5 字段的老页面只在读取侧按默认值兜底，**绝不回写**。

背景网格与鼠标吸附（对照 ``Core/myGraphicsScene.draw_grid`` 与
``Core/mySnapSystem``）：
* 网格画在场景坐标里，基准 ``50`` 视图单位（= 页面 200 单位），以
  ``projection.point(0, 0)`` 为锚点；步长随视图缩放按 2 的幂细分 / 合并，
  保证屏幕格宽落在 18~90 px，**画出来的格子就是能吸的格子**（``grid_step``
  由 ``SnapSystem.adapt_grid_to_scale`` 统一维护）。菜单「显示网格」
  （Ctrl+Shift+N）默认开启。
* 吸附点三类：端点 / 中点（``scene.snap_points()`` 收集）与**网格交汇点**。
  网格不预先枚举——最近格点由 ``nearest_grid()`` 直接算（同 Core 的
  ``get_nearest_grid_point``），图元点优先、网格仅在更近时顶替（同
  ``snap_to_point`` 的顺序）。端点/中点存空间哈希，鼠标移动只扫附近格子。
* **端点取真实顶点**：矩形类用 ``frame_corners()``（包围盒四角），线 / 三角 /
  多边形 / 路径改由 ``_PointBasedItem.snap_points()`` 用顶点表——基类的包围盒
  四角在斜图元上可能根本不在图形里（水平线的「细轴加厚 60 单位」会把上下边推
  到线外 30 单位，三角形的顶点也可能不在包围盒角上），拿它当捕捉点就会出现
  「鼠标贴着看得见的端点却没有十字」。拖角改尺寸用 ``frame_corners()``，与
  捕捉点分开，互不干扰。
* 光标附近最近的那**一个**点画成**红色细十字**（旧 Core 同款纯红，带一圈深色
  描边保证压在黑色描边上也看得见），会命中的那个加粗 + 套圆环；阈值按屏幕像素
  （``pixel_threshold = 12px``）换算成场景单位，缩放后手感一致。``T`` 键只是
  **开关吸附**，不影响标记显示。选中项**自己**的端点 / 中点也画（否则鼠标凑到
  刚选中的图元端点上看不到十字），但它恒为细十字且**不参与吸附**——吸到自己
  身上等于「点随图元动」，每帧按 offset 再叠加一次会把图元甩飞。
* 吸附位移以**鼠标位置**为基准：``_apply_snap_follow()`` 算出
  ``目标点 - 光标点`` 的偏移，原样叠加到选中的无父图元上——鼠标吸了多少，
  图元就移动多少，多选整体平移保持相对位置。按 T 立即吸一次（左键拖动已取消，
  吸附只由 T 触发，不再有「松手补一次」）。``_snap_offset`` 记录已叠加量，
  重复按 T 或原地不动都不会重复推图元。

移动图元：
* **左键按下拖动已取消**（含 CTRL）：``ItemIsMovable`` 恒为 False，按下左键只
  做选中 / 框选，按在角手柄上才是改尺寸。移动图元统一走「双击跟手」，避免点选
  时手抖把图元挪走；子图元也一样，按下只选中它自己，不再代理成拖根父对象。
  ``GraphicsScene.set_movable_gate(True)`` 保留给外部脚本显式启用，视图不再调用。

双击跟手（双击图元 → 图元钉在光标上；鼠标移动图元的唯一入口）：
* ``GraphicsView.mouseDoubleClickEvent`` 命中可选图元即进入 ``_follow_items``
  状态；命中子图元时抓的是它的**根父对象**（与「有父对象不能自行平移」一致）。
  运行态、绘制工具激活、平移中都不启用。
* 位移按**光标增量**施加（``_update_follow``），不是「绝对定位到光标」：这样
  按 T 吸出来的偏移不会被下一帧抹掉。``_warp_cursor_to_snap`` 把系统光标挪到
  捕捉点时，同函数把 ``_follow_cursor`` 一并改成捕捉点，否则下一帧会把「挪
  光标」这段再当成位移推一遍。
* 结束方式：单击任意位置落定（该次按下不再进入拖动 / 框选，等价 Visio 的
  「点一下放下」）、``Esc`` 放回抓住时的位置；删图元 / 成组 / 换工具 / 切场景 /
  失焦也会自动退出。
* **缩放**：滚轮统一走 ``_zoom_at()``，自己量「光标下场景点缩放前后的差值」
  再补滚动条，不依赖 Qt 的 ``AnchorUnderMouse``。那个锚点读的是基类私有
  ``lastMousePos``，只由 ``QGraphicsView.mouseMoveEvent`` 更新，而跟手分支
  处理完就 ``return``，它于是停在双击前的位置 —— 直接 ``scale()`` 会让整幅
  画面绕那个过时点平移，表现就是「跟手时一滚轮图元就飞走」。缩放本身是视图
  操作，不改图元几何；缩放后 ``_follow_cursor`` 同步到光标实际场景点，下一次
  移动仍是纯鼠标位移。
"""

from .g_element import BaseItem
from .g_elements import ITEM_TYPES
from .g_projection import SceneProjection
from .g_scene import GraphicsScene, SceneIndex
from .g_snap import SnapSystem
from .g_style import Style
from .g_view import GraphicsView


def load_page(path: str, projection: SceneProjection | None = None) -> GraphicsScene:
    """读取一份 page JSON，返回已装载的 QGraphicsScene。"""
    scene = GraphicsScene(projection)
    scene.load_page(path)
    return scene


__all__ = [
    "BaseItem", "ITEM_TYPES", "SceneProjection", "GraphicsScene", "SceneIndex",
    "SnapSystem", "Style", "GraphicsView", "load_page",
    "DesignerWindow", "PropertyPanel", "ElementToolboxDock", "LayerTreeDock",
    "PageHistory", "open_designer",
]

_UI_EXPORTS = {
    "DesignerWindow", "PropertyPanel", "ElementToolboxDock", "LayerTreeDock",
    "PageHistory", "open_designer",
}


def __getattr__(name: str):
    """UI 类按需导入：纯场景用法不必拉起 Qt Widgets 面板模块。"""
    if name in _UI_EXPORTS:
        from . import ui
        return getattr(ui, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
