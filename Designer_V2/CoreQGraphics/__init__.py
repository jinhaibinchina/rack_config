"""DesignerV2.CoreQGraphics —— 用原生 QGraphicsScene 重写的 Core 平行实现。

与 ``Designer.Core`` 读同一份 ``page_*.json``，序列化格式零改动；
不改动、也不 import ``Designer.Core`` 的任何运行时代码（仅图片路径解析
复用项目的 resource_manager，失败时回退到相对路径）。

坐标系（与 Designer.Core 的关键差异）：
* ``QGraphicsScene`` 直接使用 Qt 原生场景坐标：page JSON 的 ``center_pos`` /
  ``origin_pos`` / ``width`` / ``height`` / ``vertices`` / ``rotate`` /
  ``sceneRect`` 就是场景坐标，加载、绘制、命中、存盘全程不做投影；
  ``sceneRect`` 的保存值可直接交给 ``fitInView``。
* 不再兼容旧 Core 的 AGV 映射（轴交换 + 双轴取反 + 0.25 单位缩放），
  因此旧页面在本设计器里的朝向与尺寸会与旧引擎不同，两者不再对拍。

典型用法::

    from DesignerV2.CoreQGraphics import load_page, GraphicsView

    scene = load_page("Designer/Core/data.json/datas/design/pages/page_1.json")
    view = GraphicsView(scene)
    view.fit_content()
    view.show()

模块对应关系::

    Core/element.py            -> g_element.py   (BaseItem)
    Core/elements.py           -> g_elements.py  (13 类图元)
    （坐标系）                  -> 直接用 Qt 场景坐标，无投影层
    Core/myGraphicsScene.py    -> g_scene.py     (场景 + 视图范围)
    Core/myQuadTreeScene.py    -> g_scene.py     (SceneIndex + 序列化)
    Core/mySnapSystem.py       -> g_snap.py
    Core/scene_fast.py         -> g_style.py
    Core/elements.py:widget_element -> g_widgets.py (7 种控件变体)
    （Core 无对应物）          -> g_view.py      (QGraphicsView 交互)

UI 外壳在子包 ``DesignerV2.CoreQGraphics.ui``：属性面板 / 工具箱 / 图层树 /
设计器主窗口，命令行 ``python -m DesignerV2.CoreQGraphics page_1.json``。
顶层用 ``__getattr__`` 延迟导出，纯场景用户不会被 UI 依赖拖慢导入。

已知边界（见 docs/stage2_geometry_backend_design.md 附录 C）：
* widget 图元支持 7 种控件变体：设计态自绘占位、运行预览挂真实 Qt 控件，
  但不移植旧 Core ``EmbeddedWidgetLayer`` 的裸 QWidget overlay / 位图快照 /
  延迟事件派发那一整套性能补丁；
* 不含 PLC / 料仓状态绑定与运行态站点说明页。

父对象与旋转支点（口径与 Designer.Core 逐项对齐）：
* 有父对象（``parent_id``）的图元在**设计态不能自行平移、但可以自行旋转**；
  **运行态允许自行平移**（HMI 动画 / 业务脚本调 ``set_page_center`` /
  ``RuntimeElement.setPos`` 在父图元内部偏移子控件）。父对象平移 / 旋转时，
  后代图元的中心、支点、角度始终走同一个刚体变换（顶点类图元把旋转烘焙进
  ``vertices``）；设计态子图元自己拖不动——拖它会转成拖根父对象，而
  ``set_page_angle`` / ``rotate_by`` / 面板「旋转」仍然生效（绕自己的支点转，
  后代跟着转，父对象与兄弟不动）。运行态子图元自身平移不带动父对象，之后
  父对象运动仍会带着它走。
* **坐标系**：设了父对象后，对外读数与写入口径都是**父坐标系**——原点是父图元
  的可视中心、朝向是父图元的绝对角度。``page_local_center()`` /
  ``page_local_angle()`` / ``page_local_origin()`` 取值，父对象怎么动这组数都不
  变；``set_page_local_angle`` / ``set_page_local_origin`` 按父系写入。属性面板
  的「布局」页因此显示 ``（父坐标系）``，中心 X/Y 只读（设计态不能自行平移；
  运行态由业务代码放行）。
  存储与 page JSON 仍是场景绝对坐标（``page_center`` / ``page_angle``），以便
  存量页面零改动、与旧引擎逐项对拍；两套口径靠 ``local_to_world`` /
  ``world_to_local`` 互换。
* 旋转支点 ``origin_pos`` 与可视中心 ``center_pos`` 解耦：``_place()`` 按
  ``q → pos + o + R(q - o)`` 摆位，所以 ``mapToScene(0) == center``、
  支点处不动，改角度即铰链式旋转。画布上按住 O 键 + 右键把支点钉在点击位置
  （取代原右键菜单项），选中时画蓝色十字圆环 + 中心到支点的虚线；**旋转中心标识（红色
  小圆点，不再带 ID 数字标签）画在支点处**（``pivot_scene_point()``），默认绕中心
  转时与几何中心重合。视图菜单「显示中心点标记」（Ctrl+Shift+I）控制这个红点。
* **顶点类的旋转是「记账」不是「重建」**：``line / triangle / polygon /
  polyline / path`` 的几何是烘焙进 ``vertices`` / ``head_pos`` 的绝对坐标，所以
  改角度只是先把 Qt
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
  偏移量就是场景坐标增量，逐点施加；模板实例化的 target 同样是场景坐标，
  直接传 ``_instantiate``。
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
* **名字唯一**：改名只走 ``BaseItem.set_name`` → ``GraphicsScene.rename_item``，
  由 ``rename_problem()`` 判定（空名 / 与别的图元撞名——去空白后全等、区分
  大小写）；被拒时**一个字段都不写**、不产生撤销点，属性面板把输入框回滚到
  真名并用气泡提示，F2 / 右键重命名弹 ``QMessageBox`` 后留在对话框里让人改。
  组的改名校验在写之前做完：重名时组名与成员前缀**都不动**，不留「组叫 A、
  成员还挂着 B_ 前缀」的半成品。存量 page 若是历史重名数据，加载**不**报错、
  也**不**自动改名（只有显式改名才校验），保证 1618 图元对拍与 round-trip
  零改动。
* **拖角手柄**：旧 Core 其实**没有**这个交互（改尺寸只有属性面板 →
  ``change_size``），这里按 ``change_size`` 的锚点 / 递归语义新做。设计模式下
  单选图元在四角画蓝色小方块（``GraphicsView._draw_resize_handles``），按下
  冻结按下瞬间的 ``sceneTransform().invert()``，拖动时把鼠标映射回局部坐标，
  以**对面的角**为固定锚点求总缩放比例，每帧只提交增量给
  ``GraphicsScene.resize_item_about``（仿射可复合，不累积漂移）。局部 x 对应
  宽、局部 y 对应高，故 ``sx = d_local.x / d0.x``、``sy = d_local.y / d0.y``。
  组走 ``resize_group(anchor=…)`` 让成员递归跟随；
  场景级 ``_resizing_group`` 挡住 ``apply_scale_about`` 回到
  ``GroupItem.set_page_size`` 时的二次委托。四角屏幕跨度小于 28px 时不画也不
  命中，避免小图元的手柄挤在中心抢走选中按下；运行模式不显示。

框选（橡皮筋）性能：Qt 的 ``RubberBandDrag`` 把 band 画在视口画布上，每移动
一格都会重画整个视口，所以每帧成本就是「一帧全画」。两条与它无关的额外开销
已经削掉：选中变化只走 ``_refresh_selection_dirty()`` 用 ``updateScene()``
标脏「标记区域」，不再整屏 ``update()``；框选中（``is_band_selecting()``）
主窗口只记 ``_selection_pending``，松手由 ``selectionSettled`` 一次性重建属性
面板 / 同步图层树。另把 ``TextItem.paint`` 里「先 boundingRect 再 drawText」
的双次排版改成一次 ``drawText(..., Qt.TextDontClip)``（逐像素一致）。page_1
实测整屏框选 193 → 99 ms、中等区域 63 → 20 ms。

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
* ``g_style.text_metrics(text, font_size, font_family)`` 用与
  ``TextItem.paint`` 同一份 ``font_for(font_family, size, True)`` 的
  ``QFontMetricsF`` 量出视图像素尺寸；多行按
  ``lineSpacing*(n-1) + height`` 累加（直接 ``height*n`` 会少算
  leading 把字裁掉）。量完外扩 ``TEXT_PAD_X/Y``，直接作为场景宽高写回
  page 的 width / height。
* 字体族存 ``style.font_family``（属性面板「文本内容」页与「外观」页各有一个
  「字体」下拉，跨页同步）。**缺字段时取 ``Arial``**——旧 Core 的
  ``text_element`` 恒用 Arial，所以存量 page 不用补键就有相同观感，JSON
  round-trip 与 1618 图元逐像素对拍都不受影响；只有用户真的换了字体才写键。
  字体名同样在 ``QFont`` 缓存键里，不会互相串。
* 字体下拉的候选族来自 ``g_style.available_font_families()``，会**剔除 GDI
  位图字体**（``Terminal`` / ``Fixedsys`` / ``System`` / ``Modern`` /
  ``Roman`` / ``Script`` / ``Small Fonts`` / ``Courier`` / ``MS Serif`` /
  ``MS Sans Serif``）：DirectWrite 没有它们的字体文件，给它们设
  ``Qt.FontRole`` 预览会刷 ``CreateFontFaceFromHDC() failed`` 告警，而且位图
  字体不支持缩放。存量 page 若真存了这类族名，仍会插到下拉最前保持所见即真值，
  只是不给预览字体。判定用 ``QFontDatabase.isSmoothlyScalable``（整表带缓存）。
* 触发点只有三个显式编辑：``style.font_size`` / ``style.font_family`` 真变了
  （``_sync_field`` 比较新旧值，改颜色 / 线宽不会撑大边框）或 ``context``
  变了；
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
  反算取「两轴都装得下」的最大值：缩小任一轴都会收紧约束让
  字号变小（防裁字），只放大一个轴受另一轴限制，字号可能不变。
* 属性面板 ``refresh_geometry`` 会把反算后的字号回显到「文本内容」/「外观」
  两处输入；布局页对文本图元给出对应 hint。旧 Core 的「宽度→字号→派生高度」
  口径没有照搬，两处设计器互相打开时字号仍不完全等价。
widget 控件变体（对照 ``Core/elements.py:widget_element``）：
* 旧实现把变体做成 ``widgetType`` 一个字符串 → 7 个 Qt 类的一层分发：
  ``textedit`` / ``lineedit`` / ``checkbox`` / ``combobox`` / ``pushbutton`` /
  ``label`` / ``spinbox``，未知值退化 ``textedit``。CoreQGraphics 在原 7 项后
  追加 ``progressbar`` / ``slider``，工具箱与属性面板由同一张标签表派生；
  旧 Core 读到这两个未知值仍安全退化成 ``QTextEdit``。序列化是 6 个
  **顶层**字段（不在 ``style``、不复用 ``context``）：
  ``widgetType`` / ``widgetText`` / ``widgetFontSize`` / ``widgetFontFamily`` /
  ``widgetColor`` / ``widgetBackground``，默认值 ``textedit`` / ``""`` / ``12`` /
  ``""`` / ``#000000`` / ``#ffffff``。**前 5 个与旧 Core 逐字一致**；
  ``widgetFontFamily`` 是本场景扩展的**可选键**，空串表示「跟随应用默认字体」
  （即旧行为），旧 Core 的 ``from_dict`` 只读已知键会忽略它，不会加载失败。
  ``width`` / ``height`` / ``rotate`` / ``style`` / ``zValue``
  与矩形图元完全同构。
* ``widgetText`` 按变体解释：combobox 每行一个选项（空 → ``["选项 1"]``）；
  spinbox 每行 ``min=`` / ``max=`` / ``value=``（缺省 Qt 0 / 99、value 取 min，
  ``min>max`` 交换、value clamp）；progressbar / slider 复用同一个
  ``key=value`` 口径，支持 ``min=`` / ``max=`` / ``value=`` /
  ``orientation=horizontal|vertical``（缺省 0 / 100 / 中值 / 横向，也接受
  ``h`` / ``v`` 与中英文方向名）。checkbox / pushbutton / label 空文本显示
  「选项 / 按钮 / 标签」；lineedit 直接 ``setText``；textedit 只读多行。
  样式统一 ``color / background-color / font-size: Npt``（``widgetFontFamily``
  非空时再补 ``font-family: "族名"``），颜色非法回退黑 / 白；
  新增变体额外补 ``QProgressBar::chunk`` 与 ``QSlider`` groove/handle QSS。
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
* 工具箱用 ``widget:<key>`` 伪类型（9 个变体按钮 + 1 个通用），``create_item``
  在入口解析别名：真正的 ``type`` 仍写 ``widget``，变体只落 ``widgetType``。
  属性面板「控件」页可切变体、编辑文本 / 字体 / 字号 / 文字色 / 背景色；
  注意 widget 的字号与字体族是顶层 ``widgetFontSize`` / ``widgetFontFamily``，
  不是 ``style.font_size`` / ``style.font_family``。
  缺 widget 字段的老页面只在读取侧按默认值兜底，**绝不回写**。

背景网格与鼠标吸附（对照 ``Core/myGraphicsScene.draw_grid`` 与
``Core/mySnapSystem``）：
* 网格画在场景坐标里，基准 ``50`` 场景单位，以 Qt 场景原点 ``(0, 0)``
  为锚点；步长随视图缩放按 2 的幂细分 / 合并，
  保证屏幕格宽落在 18~90 px，**画出来的格子就是能吸的格子**（``grid_step``
  由 ``SnapSystem.adapt_grid_to_scale`` 统一维护）。菜单「显示网格」
  （Ctrl+Shift+N）默认开启。
* 吸附点三类：端点 / 中点（``scene.snap_points()`` 收集）与**网格交汇点**。
  网格不预先枚举——最近格点由 ``nearest_grid()`` 直接算（同 Core 的
  ``get_nearest_grid_point``），图元点优先、网格仅在更近时顶替（同
  ``snap_to_point`` 的顺序）。端点/中点存空间哈希，鼠标移动只扫附近格子。
* **端点取真实顶点**：矩形类用 ``frame_corners()``（包围盒四角），线 / 三角 /
  多边形 / 折线 / 路径改由 ``_PointBasedItem.snap_points()`` 用顶点表——基类的包围盒
  四角在斜图元上可能根本不在图形里（水平线的「细轴加厚 60 单位」会把上下边推
  到线外 30 单位，三角形的顶点也可能不在包围盒角上），拿它当捕捉点就会出现
  「鼠标贴着看得见的端点却没有十字」。拖角改尺寸用 ``frame_corners()``，与
  捕捉点分开，互不干扰。
* 光标附近最近的那**一个**点画成**红色十字**（旧 Core 同款纯红，带一圈深色
  描边保证压在黑色描边上也看得见），门控打开时加粗 + 套圆环；阈值按屏幕像素
  （``pixel_threshold = 12px``）换算成场景单位，缩放后手感一致。
  **非绘制态下，已选中图元的特征点彻底不纳入捕捉点扫描**
  （``exclude=_selection_own_points()``）：既不吸附、也不画十字、光标也不会
  warp 过去。显示 / 吸附 / warp 共用同一份 ``aim()`` 结果，不会出现「十字在
  自己身上、图元却吸到别处」的错位。绘制态例外：已选中图元是最常用的起画 /
  对齐目标，不能排除；只剔除正在画的临时图元自身点。
* ``T`` 是**一次性动作键**（不再是开关门控），见 ``_snap_action()``：
  1. 光标吸附到最近的捕捉点；若该点来自图元（``SnapSystem.owners_at`` 查归属，
     来自 ``GraphicsScene.snap_points_with_owners``），就选中该图元、进入
     **抓手 = 实时跟手**（``begin_follow``，ClosedHandCursor），并记下它的
     捕捉点（``_snap_grab_id`` / ``_snap_grab_point``）。鼠标走到哪图元跟到哪，
     ``_update_follow`` 同步平移记录点。warp 必须用**本次算出的 target**，
     不能重算 ``_hover_marker()``：抓起后该点已被选中项排除，重算会让光标
     漂到旁边的格点（表现就是「按 T 鼠标没吸到图元捕捉点」）。
  2. 抓手期间鼠标扫到别的捕捉点再按 T：图元整体平移 ``新点 - 记录点``，
     被抓的那个捕捉点精确落到新点上，记录同步更新为新坐标；抓手 / 跟手
     保持，可连续对齐多次。单击落定、Esc 整组回到抓住时位置；改选中 /
     换场景 / 切工具 / 失焦也会退出。
   3. **未抓手（仅选中 / 未选中）时绝不移动图元**：按 T 只把光标 warp 到
      捕捉点；若该点来自图元则顺带选中并抓起它，但抓起瞬间位置不变。旧版曾
      在此调 ``_apply_snap_follow()`` 把「鼠标吸了多少」叠加到已选中的无父
      图元上（多选整体平移），已按需求移除；该方法仅作历史兼容保留，设计器
      自身无调用点。图元因吸附而移动**只允许发生在第 2 条的抓手对齐分支**。
  4. **绘制工具激活时**（``_draw_type`` 非空）按 T 只做 CAD 式「取点吸附」：
     光标、绘制预览与真正落点吸到同一个捕捉点（``_draw_page_point`` 与
     ``_sync_draw_preview_to_snap`` 共用 ``_ortho_page_point``），**不选中已有
     图元、不抓手、不跟手、不平移任何图元**——跟手会抢走 ``mouseMoveEvent``
     的绘制预览分支，逐点落子就断了；``_begin_snap_grab`` 里也留了一道同样的门。
     激活绘制工具即 ``setFocus()`` + 刷新点表：否则焦点留在工具箱按钮上，T
     送不到画布；刚创建的图元只把点表置脏，等到按 T 才重建时第一点只能退到
     格点。``_ensure_snap_table()`` 在十字 / 按 T / 落点前同步脏表，并按 owner
     撤掉 ``commit=False`` 临时图元的登记，避免预览逐帧变化留下幽灵端点。
     扫描统一走 ``_snap_scan_exclude()``：绘制态只排除**正在绘制的临时图元自身**的
     端点 / 中点（``_draw_own_points``），已选中图元仍可作为起画 / 对齐目标；
     与别的图元共享的坐标按 owner 保留，仍是合法捕捉目标。

正交模式（CAD 的 F8）：
* ``GraphicsView.set_ortho_mode(True)`` 打开后，绘制 ``line`` / ``triangle`` /
  ``polygon`` / ``polyline`` / ``path`` 时，每个新点相对**上一个落点**锁到屏幕
  水平或竖直；
  ``rect`` / ``circle`` 是两点定框的对角定义，不受影响。开关真值在视图，
  ``orthoModeChanged`` 把菜单 / 工具栏 / 状态栏同步过去；按住 ``Shift`` 临时
  反转（开→斜线、关→正交线），按下 / 松开时不必挪鼠标也会立刻重画预览。
* **约束直接在场景坐标里做**（``GraphicsScene.constrain_ortho``）：按较大的
  位移分量选主轴、把另一轴钉回锚点即可；水平 → H=0，竖直 → W=0。
* 预览与落点共用 ``GraphicsView._draw_page_point`` 一个入口，不会出现
  「预览水平、落点却是斜的」。多段线逐段锁定，锚点取最后一个落点。
* 属性面板「布局」页对直线允许 W 或 H 为 0（``LineItem.set_page_size`` 覆写
  直接重写两个端点，保留方向、中心与支点），两轴不能同时为 0（面板回滚 +
  气泡提示，底层也拒绝）。``_setup_line`` 的零厚度轴命中带改成两侧对称外扩
  30（总 60），修掉旧 Core ``setWidth(60)+setLeft(-30)`` 顺序错误导致的
  「宽 90、中心偏 15」——包围盒中心必须仍钉在线上。

折线图元（``polyline``，开放多段线）：
* 画法与多边形同一条链路（``GraphicsScene.begin_draw_tool`` → ``draw_add_point``
  → ``finish_polygon``），唯一区别是**右键语义**：多边形 / 路径右键把光标点当
  最后一个顶点后**闭合**并填充面域，折线右键只是**停止落点** —— 已有顶点就是
  最终形状，不追加光标点、不补首尾边、不填充。所以 ``_DRAW_CLICKS`` 记 -1，
  ``_MIN_VERTICES`` 是 2（只有一个折点的折线就是两条相连线段）。
* 几何完全复用顶点类口径：``vertices`` 存烘焙了 ``rotate`` 的场景绝对坐标，
  移动 / 旋转 / 缩放 / 成组 / 复制 / 模板都走 ``_PointBasedItem`` 同一套变换。
  支持正交（F8）、按 T 取点吸附、Esc 取消、撤销一步。
* 零厚度问题单独处理：水平 / 竖直折线的包围盒有一条边长度为 0，Qt 默认拿
  ``boundingRect`` 做命中测试点不中，``PolylineItem.shape()`` 改用
  ``QPainterPathStroker`` 按线宽把折线描成一条有厚度的带（最细也留
  ``LINE_HIT_HALF`` 容差），包围盒本身保持真实几何、不虚胖。
* 选中 / 绘制时在每个折点画小圆点，方便看清「折」在哪；描边色 / 线宽 / 不透明度
  与其他图元同源，**填充开关对它无效**（开放线没有面域，与 ``line`` /
  ``bezier`` 一致）。

移动图元：
* **左键按下拖动已取消**（含 CTRL）：``ItemIsMovable`` 恒为 False，按下左键只
  做选中 / 框选，按在角手柄上才是改尺寸。移动图元统一走「双击跟手」，避免点选
  时手抖把图元挪走；普通子图元也一样，按下只选中它自己，不再代理成拖根父对象
  （**组成员除外**，见下一段）。
  ``GraphicsScene.set_movable_gate(True)`` 保留给外部脚本显式启用，视图不再调用。

方向键微调（选中图元后按一下挪一格，按住连续挪）：
* ``GraphicsView.nudge_step()`` 是步长真值（**Qt 场景坐标**单位），默认等于
  ``SnapSystem.grid_step``，即当前可见网格的一格，随缩放自适应、屏幕上恒为
  18~90px；``set_nudge_step(v)`` 可固定步长，``set_nudge_step(None)`` 恢复跟随。
  方向是**屏幕上下左右**，与场景 x / y 轴直接对应。
* 持续移动由视图自己的两个 ``QTimer`` 驱动（350ms 延迟 + 80ms 间隔），
  **不依赖系统键盘自动重复**；OS 发来的 autoRepeat ``keyPressEvent`` 只被吞掉，
  不重复计数，速度不受用户键盘设置影响。``_nudge_keys`` 记录当前按住的方向键，
  同时按两个键走合向量（对角），松开其中一个不停表、只换向。
* 平移走与双击跟手同一条 ``moveBy`` 增量链路：``itemChange`` →
  ``on_item_moved`` 负责标脏、支点随行、后代刚体随动。目标先过
  ``top_level_items`` 去掉「父子同时选中」，再把仍带父对象的项上溯到根
  （子图元在设计态被 ``translate_locked`` 禁止自行平移），因此画布选中的组整体移动、
  图层树单选某个成员时也是整组移动。
* 连续移动期间**不**重建吸附点（page_1 约 1.4 万点，每帧重建会掉帧），
  ``_finish_nudge()`` 在最后一个键松开 / ``focusOutEvent`` 时统一刷新吸附点、
  ``geometryChanged`` / ``contentChanged``，并 emit ``"drag_done"`` 让主窗口
  ``history.commit()`` —— 整段连续移动**只占一个撤销步**。
* 运行态、绘制工具激活、双击跟手中、带 Ctrl/Alt/Meta 修饰、或没有选中图元时
  都不接管，交还基类（方向键照常滚动画布）。Shift + 方向键 = 一次 10 格。

批量选中与全选性能：
* ``GraphicsScene.select_items(items, append=False)`` 是批量选中的统一入口：
  先屏蔽 scene 信号一次性设置完，最后只发**一次** ``selectionChanged``。
  逐项 ``setSelected`` 会让 Qt 每选中一个图元就发一次信号，而
  ``LayerTreeDock.sync_selection``（全树回灌）/ ``PropertyPanel``（重建面板）
  / 视图重绘的槽都随选中数增长；1618 图元的 page_1 全选实测从「数分钟
  卡死」降到 0.07s。``select_all_items()`` 与复制 / 粘贴后选中副本都走它。
* ``LayerTreeDock.sync_selection`` 用「树当前选中集合 == 目标集合」幂等短路
  （主窗口选中槽与图层树自身连接会调两次），有差异时攒一份
  ``QItemSelection`` 交给 ``selectionModel().select(..., ClearAndSelect|Rows)``
  一次回灌。逐节点 ``QTreeWidgetItem.setSelected`` 会让 Qt 反复维护已有选中
  区间，1618 个节点实测 0.8s，是单次同步里最贵的一块。

组选中（CAD 块参照语义）：
* 设计模式下画布**左键点选**命中组成员时，``GraphicsView._group_root_at()``
  把它重定向成根组：清空选中后只选组，成员不会被画布单独选中；Ctrl / Shift
  多选时把根组加入并把已在选中集合里的组成员剔掉。右键目标同样走根组，
  免得「左键只能选组、右键却把成员选中」互相打架。
* 判据是**根祖先的 TYPE == "group"**，不是「有 parent_id」。普通逻辑父子
  （根是 rect / text 等）仍保持「按下只选中它自己」的原语义；运行态不改。
* 只拦「按下点在 item 上」的点选。空白处按下由基类照常启动框选（Qt 只在
  按下点没有 item 时才画橡皮筋），所以框选手势不受影响；框选结果仍按 Qt
  原语义，可能包含成员。要精确编辑单个成员请用图层树 / 属性面板——
  那里直接 ``setSelected(True)``，不走画布重定向。
* 不动 ``ItemIsSelectable`` flag：实测关掉后 ``setSelected(True)`` 也无效，
  会连带废掉图层树、属性面板和成组 / 解组。

双击跟手（双击图元 → 图元钉在光标上；鼠标移动图元的唯一入口）：
* ``GraphicsView.mouseDoubleClickEvent`` 命中可选图元即进入 ``_follow_items``
  状态；命中子图元时抓的是它的**根父对象**（与「设计态有父对象不能自行平移」一致）。
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

布尔运算与可复用模板（对照 ``Core/ui/template_store.py``）：
* 多选矩形 / 圆 / 三角形 / 多边形 / 路径后可做并集、交集、差集、异或；结果
  替换源图元并自动选中，继承首个图元样式，只需一个撤销步。差集按页面顺序
  以首个图元依次减去其余图元；空结果不删源图元，也不消耗新 id。
* 结果仍是 ``path``：``path_segments`` 保存精确 move/line/curve 与填充规则，
  ``vertices`` 同步保存旧 Core 可读的折线兜底，多子路径、孔洞和圆角不会丢；
  移动、旋转、非等比缩放、复制、再次布尔与模板实例化均走同一套控制点变换。

开放线条闭合 / 边界提取（``g_outline.py``）：
* 多选直线 / 三次贝塞尔曲线 / 折线后，画布右键「由所选线条生成闭合路径」
  （编辑菜单同命令）会合成一个与布尔结果同构的 ``path`` 面域图元：源线条被
  替换、结果自动选中、只记一个撤销步，可继续编辑、再次布尔或存为模板。
  **不要求首尾相接**，只要这些线条围出了封闭区域即可：交叉成三角形、井字
  中间那一格、端点落在别的线中段（T 型接触）、端点伸出交点之外、多块互不
  相连的封闭区域都成立；悬空伸出段不参与封闭，随源线条一起被替换。
* 判定走平面排列而不是「连点」：各段统一成参数化三次控制点 -> 求两两交点
  （线-线解析、线-曲线求三次 Bernstein 根、曲线-曲线 de Casteljau 细分）
  与端点投影 -> 按交点参数切段 -> 交点 / 端点按 1 个场景单位聚类成节点 ->
  半边结构（节点出射角排序，``next = prev(twin)``）遍历出所有面，保留非零
  正面积的有界内面（Qt 场景 y 轴向下，无界外面为负），每个面一个 closedSubpath。
  反向半边的曲线 c1/c2 同步交换，节点代表点对齐端点，不留细缝；不处理单条
  曲线的自交叶形与切线相切。
* 几何全在实时场景坐标里算（``sceneTransform``），未存盘的拖动 / 旋转同样
  生效；失败只抛 ValueError，删源图元与 id 分配都发生在全部校验通过之后。

图元 / 组合模板（工具箱里的可复用图元或组）：
* 模板文件 ``toolbox_templates.json`` 与旧设计器**共用同一份**、格式逐字同构：
  ``ToolboxTemplate.items`` 就是 page 记录列表，捕获时把整棵子树的几何点
  统一平移到「根组中心 = 原点」，宽高 / 半径 / 旋转一律不动。目录默认取
  页面所在的 ``.../datas/design/``，可用 ``DesignerWindow(template_dir=…)`` 改。
* 捕获走平铺结构：``SceneIndex.children_of`` 做父在子前的 DFS（``parent_id`` /
  ``children_ids``，不是 Qt 父链），每个成员取 ``to_page_record()``，未存盘的
  旋转会先烘焙。单图元直接捕获；组捕获整棵子树，空组直接拒绝。
* 实例化 ``GraphicsScene.instantiate_template`` 复用 ``_instantiate`` 的重发 id、
  重映射关系、组名前缀命名与整树偏移；额外做三件事：从 root 做可达性 DFS
  （防手工编辑模板的悬空 id）、按记录里的 ``zValue`` 稳定排序再交给
  ``_instantiate``（它按快照下标写 z，154 成员的料架模板按 id 排会打乱层级）、
  预校验类型并在异常时删掉本次新建的图元。
* UI 入口四处：编辑菜单 / 画布右键（单选图元或组时）/ 工具箱「将所选图元存为模板」
  按钮 / 模板按钮点一下插到视口中心或拖到画布指定位置；模板按钮右键可重命名、
  删除。拖放 MIME 与图元工具分开（``application/x-design-template`` 带模板 id）。
  模板操作只写模板文件，**不改页面、不进撤销栈**；插入模板走 ``_after_edit()``。
"""

from .g_element import BaseItem
from .g_elements import ITEM_TYPES
from .g_scene import GraphicsScene, SceneIndex
from .g_snap import SnapSystem
from .g_style import Style
from .g_view import GraphicsView


def load_page(path: str) -> GraphicsScene:
    """读取一份 page JSON，返回已装载的 QGraphicsScene。"""
    scene = GraphicsScene()
    scene.load_page(path)
    return scene


__all__ = [
    "BaseItem", "ITEM_TYPES", "GraphicsScene", "SceneIndex",
    "SnapSystem", "Style", "GraphicsView", "load_page",
    "DesignerWindow", "PropertyPanel", "ElementToolboxDock", "LayerTreeDock",
    "PageHistory", "TemplateStore", "ToolboxTemplate", "open_designer",
]

_UI_EXPORTS = {
    "DesignerWindow", "PropertyPanel", "ElementToolboxDock", "LayerTreeDock",
    "PageHistory", "TemplateStore", "ToolboxTemplate", "open_designer",
}


def __getattr__(name: str):
    """UI 类按需导入：纯场景用法不必拉起 Qt Widgets 面板模块。"""
    if name in _UI_EXPORTS:
        from . import ui
        return getattr(ui, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
